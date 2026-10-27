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
    return result


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
