#!/usr/bin/env python3
"""Supply routing guidance and the exact selected task's current dialogue contract."""
import json
import math
import re
import sys

sys.dont_write_bytecode = True

import workflow
from communication_policy import load_policy

ROUTING_GUIDANCE = (
    "Task Workflow routing guidance: The main agent judges the current request "
    "using conversation context; the user's explicit routing choice wins. "
    "Handle ordinary chat, advice, read-only status, and simple bounded requests "
    "directly. For substantive development or experiment action requests, "
    "automatically use $task-workflow for exploration and design. For an existing "
    "task, reuse its correct identity and authorization and perform only the "
    "current requested action. A progress question must not restart experiments "
    "or release resources. If intent or task identity is unclear, clarify before "
    "enrollment or mutation. Confirm the design before implementation; actual "
    "implementation, experiment execution, integration, and release require "
    "applicable authorization. Hook delivery itself grants none. "
    "For enrollment use the native init MCP tool with the known project/task "
    "and host session identifier when available. "
    "Use bind-session to select an existing task for its known session; "
    "reuse the recorded phase and templates after recovery. "
)
def context_for(event):
    if not isinstance(event, dict) or event.get("hook_event_name") != "UserPromptSubmit":
        return None
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    guidance = ROUTING_GUIDANCE + " " + load_policy() + " Complete-goal contract: " + workflow.GOAL_INTEGRITY
    session_id = event.get("session_id")
    if isinstance(session_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        guidance += " Host-provided session context for an authorized enrollment or recovery: " + json.dumps({"session_id": session_id}, ensure_ascii=True) + "."
        try:
            context = workflow.session_dialogue_context(event.get("cwd"), session_id)
        except Exception:
            # Invalid or unavailable state must not obstruct unrelated requests.
            context = None
        if context is not None:
            guidance += " Registered Task Workflow context: " + json.dumps(context, ensure_ascii=True, separators=(",", ":"))
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": guidance}}


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
        data = sys.stdin.buffer.read()
        event = json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=reject_constant, parse_float=finite_float)
        result = context_for(event)
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
    except Exception:
        # Invalid input must not obstruct prompts or expose input in errors.
        return


if __name__ == "__main__":
    main()
