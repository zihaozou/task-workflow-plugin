"""Read-only DeepSeek context boundary, source fidelity and isolation checks."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
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
        self.assertEqual(self.context(), {"ok": True, "context": expected})
        result = self.command()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout), {"ok": True, "context": expected})
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
        self.assertEqual(actual, {"ok": True, "context": expected})
        self.assertEqual(actual["context"]["dialogue_contract"]["latest_answer"]["question_text"], text)
        self.assertEqual(actual["context"]["dialogue_contract"]["latest_answer"]["answer"]["text"], raw_answer)
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
