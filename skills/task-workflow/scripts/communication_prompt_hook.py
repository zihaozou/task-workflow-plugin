#!/usr/bin/env python3
"""Supply fixed routing and naming guidance for each nonempty user prompt."""
import json
import math
import re
import sys

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
    "and host session identifier when available. For a legacy CLI enrollment "
    "or recovery, explicitly invoke a lifecycle MCP tool or workflow.status_view "
    "with that same context so the current chat receives its UI binding. "
    "Use bind-session to select an existing task for its known session; "
    "reuse the recorded phase and templates after recovery. "
)
NAMING_REMINDER = (
    "Task Workflow communication guidance: Before sending a normal reply or progress "
    "update, check terminology against the earlier user-visible conversation. "
    "Use consistent names, explain a needed new abbreviation or technical label "
    "at its first user-visible use, and explain the mapping when renaming. "
    "Avoid repeated definitions for familiar, user-used, or already explained "
    "terms. Clarify terms within the normal reply; use a small two-column table "
    "only when useful. Add no separate review notice or extra turn."
)


def context_for(event):
    if not isinstance(event, dict) or event.get("hook_event_name") != "UserPromptSubmit":
        return None
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    guidance = ROUTING_GUIDANCE + NAMING_REMINDER
    session_id = event.get("session_id")
    if isinstance(session_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        guidance += " Host-provided session context for an authorized enrollment or recovery: " + json.dumps({"session_id": session_id}, ensure_ascii=True) + "."
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
