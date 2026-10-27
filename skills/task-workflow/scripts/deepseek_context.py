#!/usr/bin/env python3
"""Expose exact task context through a read-only JSON process boundary."""
import json
import math
from pathlib import Path
import re
import sys

import workflow


TEMPLATE_ROOT = Path(__file__).resolve().parent.parent / "templates"
CONVERSATION_SECTIONS = {
    "first_reply": "First discussion reply",
    "answer_acknowledgment": "Answer acknowledgement and discussion",
    "playback": "Playback",
    "reentry": "Status and reentry",
    "design": "Spec and approval",
    "plan": "Plan and approval",
    "execution": "Execution, review, and delivery",
}


def stage_guidance(contract, context=None):
    """Project current canonical instructions without storing a second template."""
    stage = contract["stage"]
    mode = contract.get("dialogue_mode")
    if stage in ("design", "design_review", "design_confirmation") or mode == "design_preparation":
        mode, extra = "design", "spec.md"
    elif stage in ("plan", "plan_confirmation"):
        mode, extra = "plan", "plan.md"
    elif stage in ("implementation", "delivery"):
        mode, extra = "execution", None
    else:
        mode, extra = mode if mode in CONVERSATION_SECTIONS else "recorded", None
    source = TEMPLATE_ROOT / "conversation.md"
    text = source.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", text)
    sections = {part.split("\n", 1)[0]: "## " + part for part in parts[1:]}
    selected = sections[CONVERSATION_SECTIONS[mode]] if mode in CONVERSATION_SECTIONS else ""
    result = {
        "mode": mode,
        "source_paths": [str(source)],
        "conversation_template": parts[0] + selected,
        "title_language_rule": "The English template labels identify semantic sections. Render headings, questions and option text in the current conversation language while preserving recorded meaning and question/choice identities. Persist authored record summaries in English with original source references.",
    }
    if extra:
        source = TEMPLATE_ROOT / extra
        result["spec_template" if extra == "spec.md" else "plan_template"] = source.read_text(encoding="utf-8")
        result["source_paths"].append(str(source))
    if mode in ("first_reply", "answer_acknowledgment", "playback", "reentry"):
        source = TEMPLATE_ROOT.parent / "references/workflow.md"
        reference = source.read_text(encoding="utf-8")
        match = re.search(r"<!-- process-question-complete-example -->\s*```json\s*(.*?)```", reference, re.S)
        if match is None:
            raise ValueError("Missing canonical question example")
        example = json.loads(match.group(1), object_pairs_hook=unique_pairs)
        if context is not None:
            example.update(root=context["root"], task_id=context["task"]["task_id"],
                           expected_version=contract["state_version"])
        example["actor"] = "<registered coordinator actor>"
        result["recording_example"] = {
            "operation": "process-question", "arguments": example,
            "instruction": "This is a complete structural example, not a question or authorization for this task. Use the actual current root, task_id and expected_version. Replace actor with the actual registered coordinator from current status/context state.coordinator. Replace all illustrative question, scope, choice and source content with the actual current discussion. Record intent and exploration first; use process-reenter only where the current stage requires it. Never copy illustrative source references as evidence or repair malformed JSON by guessing.",
        }
        result["source_paths"].append(str(source))
    if context is not None:
        drafts = argument_drafts(context)
        if drafts:
            result["argument_drafts"] = drafts
    return result


def argument_drafts(context):
    """Build incomplete, read-only shapes from this exact task revision only."""
    contract = context["dialogue_contract"]
    allowed = set(contract["allowed_next_operations"])
    relevant = allowed.intersection({"process-plan", "process-decision"})
    if not relevant:
        return []
    root, store = workflow.store_dir(context["root"])
    state, _ = workflow.load_events(workflow.task_dir(store, context["task"]["task_id"]))
    if (state["version"] != contract["state_version"] or state["root"] != str(root)
            or state.get("session_id") != context["session_id"]
            or workflow.session_bindings(store).get(context["session_id"]) != state["task_id"]):
        raise ValueError("Task changed during draft projection")
    process = state["process"]
    base = {"root": str(root), "task_id": state["task_id"], "actor": state["coordinator"],
            "expected_version": state["version"]}
    requirement_ids = [entry["id"] for entry in process["requirements"]]
    instruction = ("READ-ONLY INCOMPLETE DRAFT: never submit nulls. Fill and review every required_fill_path "
                   "using actual authorized semantics and source evidence. Scaffold file/interface names are suggestions copied from approved components; select actual component and requirement coverage. Mechanical coverage is not a plan, "
                   "decision, approval or authorization. You may regroup items and add steps/checks; preserve exact "
                   "declared references and current schema. Ordinary/status requests remain direct and preserve "
                   "the current wait; tool availability does not authorize progression.")
    drafts = []
    if "process-plan" in relevant:
        design = process.get("design")
        approval = process.get("design_approval")
        if design and approval and approval.get("digest") == design["digest"]:
            items = []
            for component in design["content"]["components"]:
                files = list(component["files"])
                interfaces = list(component["interfaces"])
                items.append({"id": "item-" + component["id"], "title": None,
                    "component_ids": [None], "requirement_ids": [None],
                    "deliverables": [None], "files": files or [None],
                    "file_changes": [{"path": path, "action": None, "responsibility": None}
                                     for path in files] or [{"path": None, "action": None, "responsibility": None}],
                    "interfaces": interfaces, "dependencies": [],
                    "steps": [{"id": "action-1", "action": None, "files": files or [None],
                               "interfaces": interfaces, "verification_ids": ["check-1"]}],
                    "verification": [{"id": "check-1", "kind": None, "requirement_ids": [None],
                        "targets": files or [None], "method": None, "expected_result": None}],
                    "acceptance": [None]})
            arguments = {**base, "plan": {"shared_requirements": [], "dependencies": [],
                                         "review_focus": None, "items": items}}
            drafts.append({"operation": "process-plan", "arguments": arguments,
                "approved_design_digest": design["digest"],
                "valid_references": {"requirement_ids": requirement_ids,
                    "components": [{key: component[key] for key in ("id", "requirement_ids", "files", "interfaces")}
                                   for component in design["content"]["components"]]},
                "instruction": instruction + " Plan has no id or acceptance field at its top level. "
                    "Each step.interfaces must use the exact strings declared by its item; verification_ids "
                    "name that item's checks. Every item requirement needs a check, and every declared interface "
                    "must occur in an action. Command checks also need a nonempty argv; inspection checks need targets."})
    if "process-decision" in relevant:
        arguments = {**base, "decision": {"id": None, "title": None, "choice": None,
            "rationale": None, "scope": [], "status": None, "source": None,
            "confirmation_source": None}}
        drafts.append({"operation": "process-decision", "arguments": arguments,
            "valid_references": {"scope": requirement_ids,
                "questions": [{"id": question["id"], "choices": question.get("choices", [])}
                              for question in process["questions"]]},
            "instruction": instruction + " confirmation_source belongs inside decision, never at the operation "
                "top level. Use actual recorded answer/source for confirmed choices; a draft cannot create human "
                "authority. Add question_id/choice_id only when supported by that exact recorded answer. For a "
                "proposed choice omit confirmation_source instead of inventing confirmation."})
    def missing(value, path):
        if value is None:
            return [path]
        if isinstance(value, dict):
            return [field for key, child in value.items() for field in missing(child, path + "." + key)]
        if isinstance(value, list):
            return [field for index, child in enumerate(value) for field in missing(child, path + "[" + str(index) + "]")]
        return []
    for draft in drafts:
        draft["required_fill_paths"] = missing(draft["arguments"], "arguments")
    return drafts


def error_result(code):
    messages = {
        "invalid_input": "Expected actual cwd and session_id.",
        "context_unavailable": "Current Task Workflow context is unavailable. Inspect status before dependent work.",
    }
    return {"ok": False, "error": {"code": code, "message": messages[code]}}


def context_for(payload):
    """Return current shared-core context; never repair or advance task state."""
    if not isinstance(payload, dict) or set(payload) != {"cwd", "session_id"}:
        return error_result("invalid_input")
    cwd, session_id = payload["cwd"], payload["session_id"]
    if (not isinstance(cwd, str) or any(ord(character) < 32 for character in cwd)
            or not isinstance(session_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]+", session_id) is None):
        return error_result("invalid_input")
    try:
        directory = Path(cwd)
        if not directory.is_absolute() or not directory.is_dir():
            return error_result("invalid_input")
    except (OSError, ValueError):
        return error_result("invalid_input")
    try:
        context = workflow.session_dialogue_context(cwd, session_id)
        if context is None:
            # The shared core is deliberately quiet for stale selection. This
            # boundary distinguishes that failure from a genuinely unbound chat.
            root = workflow.find_registered_root(directory)
            if root is not None:
                _, store = workflow.store_dir(str(root))
                if session_id in workflow.session_bindings(store):
                    return error_result("context_unavailable")
        else:
            context["stage_guidance"] = stage_guidance(context["dialogue_contract"], context)
        return {"ok": True, "context": context}
    except Exception:
        # Do not expose exception text, inputs, paths or private source material.
        return error_result("context_unavailable")


def unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"),
                             object_pairs_hook=unique_pairs,
                             parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, UnicodeError, OSError, RecursionError):
        result = error_result("invalid_input")
    else:
        result = context_for(payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=True, allow_nan=False) + "\n")
    if result["ok"]:
        return 0
    return 2 if result["error"]["code"] == "invalid_input" else 1


if __name__ == "__main__":
    raise SystemExit(main())
