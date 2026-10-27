"""Read-only DeepSeek context boundary, source fidelity and isolation checks."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_session_bindings as fixtures


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/task-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
import deepseek_context
import mcp_server
import workflow


class DeepSeekContextTests(unittest.TestCase):
    enroll = fixtures.SessionBindingTests.enroll
    bind = fixtures.SessionBindingTests.bind

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="task-workflow-deepseek-test-")
        self.base = Path(self.temporary.name).resolve()
        # Cleanup is LIFO: remove the owned tree, then verify its removal.
        self.addCleanup(lambda: self.assertFalse(self.base.exists()))
        self.addCleanup(self.temporary.cleanup)
        self.root = self.base / "project"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "--allow-empty",
                        "-qm", "Initial fixture"], check=True, capture_output=True)
        self.core = workflow

    def payload(self, **fields):
        return {"cwd": str(self.root), "session_id": "session-1", **fields}

    def context(self, **fields):
        return deepseek_context.context_for(self.payload(**fields))

    def assert_core_context(self, actual, expected):
        actual = dict(actual)
        guidance = actual.pop("stage_guidance")
        self.assertEqual(actual, expected)
        self.assertEqual(guidance, deepseek_context.stage_guidance(expected["dialogue_contract"], expected))

    def command(self, raw=None, **fields):
        if raw is None:
            raw = json.dumps(self.payload(**fields)).encode("utf-8")
        return subprocess.run([sys.executable, str(SCRIPTS / "deepseek_context.py")],
                              input=raw, cwd=str(self.base), capture_output=True)

    def snapshot(self):
        store = self.root / ".task-workflow"
        return {str(path.relative_to(store)): (hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns, path.stat().st_mode)
                for path in store.rglob("*") if path.is_file()}

    def advance(self, state, operation, **fields):
        return self.core.dispatch(operation, {"root": str(self.root), "task_id": state["task_id"],
            "actor": "owner", "expected_version": state["version"], **fields})["state"]

    def test_bound_context_is_exact_and_does_not_write_state_events_or_projections(self):
        self.enroll("first", "session-1")
        expected = self.core.session_dialogue_context(str(self.root), "session-1")
        before = self.snapshot()
        schemas = self.core.command_schemas()
        self.assert_core_context(self.context()["context"], expected)
        result = self.command()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assert_core_context(json.loads(result.stdout)["context"], expected)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.core.command_schemas(), schemas)
        self.assertEqual(len(schemas), 53)

    def test_unbound_project_and_other_session_are_successful_null_without_enrollment(self):
        self.assertEqual(self.context(), {"ok": True, "context": None})
        self.assertFalse((self.root / ".task-workflow").exists())
        self.enroll("first", "session-1")
        before = self.snapshot()
        self.assertEqual(self.context(session_id="other-session"), {"ok": True, "context": None})
        unrelated = self.base / "unrelated"
        unrelated.mkdir()
        self.assertEqual(self.context(cwd=str(unrelated)), {"ok": True, "context": None})
        self.assertFalse((unrelated / ".task-workflow").exists())
        self.assertEqual(self.snapshot(), before)

    def test_selection_switch_and_registered_worktree_use_actual_payload_identity(self):
        first = self.enroll("first", "session-1")
        self.enroll("second", "session-1")
        self.assertEqual(self.context()["context"]["task"]["task_id"], "second")
        self.bind("first")
        self.assertEqual(self.context()["context"]["task"]["task_id"], "first")
        first = self.core.dispatch("status", {"root": str(self.root), "task_id": "first"})["state"]
        head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip()
        first = self.advance(first, "worktree-prepare", expected_base=head, authorization_source="Explicit fixture worktree")
        result = self.command(cwd=first["worktree"]["path"])
        self.assertEqual(result.returncode, 0)
        context = json.loads(result.stdout)["context"]
        self.assertEqual(context["root"], str(self.root))
        self.assertEqual(context["session_id"], "session-1")
        self.assertEqual(context["task"]["task_id"], "first")

    def test_input_shape_path_and_core_session_rules_are_checked_before_reading(self):
        invalid = [None, [], {}, {"cwd": str(self.root)}, self.payload(extra="PRIVATE_INPUT"),
                   self.payload(cwd="relative"), self.payload(cwd=str(self.root / "missing")),
                   self.payload(cwd=str(self.root / "line\nbreak")), self.payload(cwd=42),
                   self.payload(session_id=""), self.payload(session_id="bad/session"),
                   self.payload(session_id="bad\nsession"), self.payload(session_id=True)]
        with mock.patch.object(workflow, "session_dialogue_context") as shared:
            for payload in invalid:
                with self.subTest(payload=payload):
                    self.assertEqual(deepseek_context.context_for(payload)["error"]["code"], "invalid_input")
            shared.assert_not_called()
        # Match the core's session syntax, which also permits leading underscores.
        self.enroll("first", "_session-1")
        self.assertTrue(self.context(session_id="_session-1")["ok"])

    def test_cli_rejects_malformed_duplicate_and_nonfinite_json_without_echo_or_traceback(self):
        samples = [b"PRIVATE_INPUT not JSON", b"\xff", b"{} trailing PRIVATE_INPUT", b"",
                   b'{"cwd":"PRIVATE_INPUT","cwd":"duplicate","session_id":"session-1"}',
                   b'{"cwd":NaN,"session_id":"session-1"}', b'{"cwd":1e999,"session_id":"session-1"}',
                   b'{"cwd":Infinity,"session_id":"session-1"}']
        for raw in samples:
            with self.subTest(raw=raw):
                result = self.command(raw)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(json.loads(result.stdout), deepseek_context.error_result("invalid_input"))
                self.assertNotIn(b"PRIVATE_INPUT", result.stdout)

    def test_core_failure_is_sanitized_instead_of_returning_a_stale_or_null_context(self):
        with mock.patch.object(workflow, "session_dialogue_context", side_effect=OSError("PRIVATE_SOURCE")):
            result = self.context()
        self.assertEqual(result, deepseek_context.error_result("context_unavailable"))
        self.assertNotIn("PRIVATE_SOURCE", json.dumps(result))

    def test_selected_missing_or_mismatched_task_is_unavailable_without_fallback(self):
        self.enroll("first", "session-1")
        registry_path = self.root / ".task-workflow/registry.json"
        registry = self.core.read_json(registry_path)
        registry["session_bindings"]["session-1"] = "absent-task"
        self.core.atomic_json(registry_path, registry)
        before = self.snapshot()
        result = self.command()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout), deepseek_context.error_result("context_unavailable"))
        self.assertEqual(self.snapshot(), before)
        self.enroll("other", "other-session")
        registry = self.core.read_json(registry_path)
        registry["session_bindings"]["session-1"] = "other"
        self.core.atomic_json(registry_path, registry)
        self.assertEqual(self.context(), deepseek_context.error_result("context_unavailable"))
        self.assertEqual(self.context(session_id="genuinely-unbound"), {"ok": True, "context": None})

    def test_corrupt_bound_events_return_exit_one_and_are_not_repaired(self):
        self.enroll("first", "session-1")
        event = self.root / ".task-workflow/tasks/first/events/00000001.json"
        event.chmod(0o644)
        event.write_text('{"PRIVATE_CORRUPTION":true}\n')
        before = self.snapshot()
        result = self.command()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout), deepseek_context.error_result("context_unavailable"))
        self.assertNotIn(b"PRIVATE_CORRUPTION", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_complete_cli_output_exceeds_buffer_default_and_preserves_source_values(self):
        state = self.enroll("large", "session-1")
        source = {"kind": "user", "reference": "Actual synthetic fixture request"}
        state = self.advance(state, "process-intent", intent={"goal": "Preserve full context", "why": "Test source fidelity",
            "success_criteria": ["The full context round trip is exact"], "source": source})
        state = self.advance(state, "process-exploration", exploration={"current_behavior": "Source inspected.",
            "evidence": ["Fixture source"], "unknowns": []})
        text = "Original fixture data: \"quoted\" \\ literal\n" + "complete source data " * 60000
        state = self.advance(state, "process-question", question={"id": "full-source", "text": text,
            "rationale": "Retain the exact source", "scope": [], "important": True})
        raw_answer = "External literal \u4fdd\u7559\nwith \\ escapes and \"quotes\"."
        self.advance(state, "process-answer", question_id="full-source", answer=raw_answer, source=source)
        before = self.snapshot()
        expected = self.core.session_dialogue_context(str(self.root), "session-1")
        result = self.command()
        self.assertEqual(result.returncode, 0)
        self.assertGreater(len(result.stdout), 1024 * 1024)
        self.assertEqual(result.stderr, b"")
        actual = json.loads(result.stdout)
        self.assert_core_context(actual["context"], expected)
        self.assertEqual(actual["context"]["dialogue_contract"]["latest_answer"]["question_text"], text)
        self.assertEqual(actual["context"]["dialogue_contract"]["latest_answer"]["answer"]["text"], raw_answer)
        self.assertEqual(self.snapshot(), before)

    def test_every_stage_projects_only_complete_current_canonical_sections(self):
        source = deepseek_context.TEMPLATE_ROOT / "conversation.md"
        text = source.read_text()
        common = text.split("## ", 1)[0]
        cases = [("discussion", mode, mode) for mode in ("first_reply", "answer_acknowledgment", "playback", "reentry")]
        cases += [(stage, None, "design") for stage in ("design", "design_review", "design_confirmation")]
        cases += [("discussion", "design_preparation", "design")]
        cases += [(stage, None, "plan") for stage in ("plan", "plan_confirmation")]
        cases += [(stage, None, "execution") for stage in ("implementation", "delivery")]
        for stage, mode, expected in cases:
            with self.subTest(stage=stage, mode=mode):
                guidance = deepseek_context.stage_guidance({"stage": stage, "dialogue_mode": mode})
                heading = deepseek_context.CONVERSATION_SECTIONS[expected]
                section = text.split("## " + heading + "\n", 1)[1].split("\n## ", 1)[0]
                self.assertEqual(guidance["conversation_template"].rstrip(), (common + "## " + heading + "\n" + section).rstrip())
                self.assertIn("current conversation language", guidance["title_language_rule"])
                self.assertIn("semantic sections", guidance["title_language_rule"])
                self.assertEqual("recording_example" in guidance, expected in ("first_reply", "answer_acknowledgment", "playback", "reentry"))
                for filename, key, wanted in (("spec.md", "spec_template", expected == "design"), ("plan.md", "plan_template", expected == "plan")):
                    self.assertEqual(key in guidance, wanted)
                    if wanted:
                        self.assertEqual(guidance[key], (deepseek_context.TEMPLATE_ROOT / filename).read_text())
        legacy = deepseek_context.stage_guidance({"stage": "legacy"})
        self.assertEqual(legacy["mode"], "recorded")
        self.assertEqual(legacy["conversation_template"], common)

    def test_canonical_template_is_refreshed_each_read_and_missing_is_sanitized(self):
        self.enroll("first", "session-1")
        folder = self.base / "templates"
        shutil.copytree(deepseek_context.TEMPLATE_ROOT, folder)
        shutil.copytree(deepseek_context.TEMPLATE_ROOT.parent / "references", self.base / "references")
        before = self.snapshot()
        with mock.patch.object(deepseek_context, "TEMPLATE_ROOT", folder):
            first = self.context()["context"]["stage_guidance"]
            source = folder / "conversation.md"
            source.write_text(source.read_text().replace("## First discussion reply\n", "## First discussion reply\n\nFresh canonical canary.\n"))
            second = self.context()["context"]["stage_guidance"]
            self.assertNotIn("Fresh canonical canary", first["conversation_template"])
            self.assertIn("Fresh canonical canary", second["conversation_template"])
            source.unlink()
            self.assertEqual(self.context(), deepseek_context.error_result("context_unavailable"))
            self.assertEqual(self.context(session_id="unbound"), {"ok": True, "context": None})
        self.assertEqual(self.snapshot(), before)

    def test_direct_example_has_current_identity_and_preserves_canonical_nested_question(self):
        state = self.enroll("first", "session-1")
        guidance = self.context()["context"]["stage_guidance"]
        arguments = guidance["recording_example"]["arguments"]
        self.assertEqual((arguments["root"], arguments["task_id"], arguments["expected_version"]), (str(self.root), "first", state["version"]))
        self.assertEqual(arguments["actor"], "<registered coordinator actor>")
        reference = (SCRIPTS.parent / "references/workflow.md").read_text()
        canonical = json.loads(re.search(r"<!-- process-question-complete-example -->\s*```json\s*(.*?)```", reference, re.S).group(1))
        self.assertEqual(arguments["question"], canonical["question"])
        self.assertIn("not a question or authorization", guidance["recording_example"]["instruction"])

    def test_documented_nested_question_executes_and_malformed_input_never_mutates(self):
        state = self.enroll("first", "session-1")
        source = {"kind": "user", "reference": "Synthetic example test authorization"}
        state = self.advance(state, "process-intent", intent={"goal": "Select output", "why": "Exercise the documented call", "success_criteria": ["Actual nested question is recorded"], "source": source})
        state = self.advance(state, "process-exploration", exploration={"current_behavior": "Fixture inspected", "evidence": ["Fixture README"], "unknowns": []})
        document = (SCRIPTS.parent / "references/workflow.md").read_text()
        match = re.search(r"<!-- process-question-complete-example -->\s*```json\s*(.*?)```", document, re.S)
        self.assertIsNotNone(match, "The executable example must be present in the actual reference")
        arguments = json.loads(match.group(1))
        arguments.update(root=str(self.root), task_id="first", actor="owner", expected_version=state["version"])
        malformed = {key: value for key, value in arguments.items() if key != "question"}
        malformed.update(arguments["question"])
        before = self.snapshot()
        server = mcp_server.Server()
        server.initialized = True
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "process-question", "arguments": malformed}}
        with mock.patch.object(self.core, "dispatch", wraps=self.core.dispatch) as dispatch:
            rejected = server.handle(request)
            self.assertEqual(rejected["error"]["code"], -32602)
            dispatch.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        raw = json.dumps(malformed) + ', "root": ' + json.dumps(str(self.root)) + '}'
        with self.assertRaises(json.JSONDecodeError):
            mcp_server.parse_json(raw)
        self.assertEqual(self.snapshot(), before)
        result = self.core.dispatch("process-question", arguments)
        self.assertEqual(result["dialogue_contract"]["pending_questions"][0]["id"], arguments["question"]["id"])
        self.assertEqual(result["dialogue_contract"]["pending_questions"][0]["choices"], arguments["question"]["choices"])
        # A late tool reply cannot write through its earlier task revision.
        stale = {"root": str(self.root), "task_id": "first", "actor": "owner", "expected_version": state["version"],
                 "question_id": arguments["question"]["id"], "answer": "Synthetic old answer", "source": source}
        before = self.snapshot()
        with self.assertRaises(self.core.WorkflowError) as conflict:
            self.core.dispatch("process-answer", stale)
        self.assertEqual(conflict.exception.code, "revision_conflict")
        self.assertEqual(self.snapshot(), before)

    def test_frozen_core_still_requires_only_workflow_and_runner(self):
        self.enroll("first", "session-1")
        folder = self.base / "pinned-runtime"
        folder.mkdir()
        for name in ("workflow.py", "runner.py"):
            shutil.copyfile(SCRIPTS / name, folder / name)
        spec = importlib.util.spec_from_file_location("deepseek_test_frozen_workflow", folder / "workflow.py")
        frozen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frozen)
        self.assertEqual(frozen.command_schemas(), self.core.command_schemas())
        self.assertEqual(frozen.session_dialogue_context(str(self.root), "session-1")["task"]["task_id"], "first")
        self.assertEqual({path.name for path in folder.iterdir() if path.is_file()}, {"workflow.py", "runner.py"})
        # The new helper uses only syntax available to the declared Python floor.
        ast.parse((SCRIPTS / "deepseek_context.py").read_text(), feature_version=(3, 9))
