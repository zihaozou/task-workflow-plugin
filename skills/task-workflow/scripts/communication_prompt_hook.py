#!/usr/bin/env python3
"""Add a fixed naming reminder when the user submits a nonempty prompt."""
import json
import math
import sys

MAX_INPUT = 1024 * 1024
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
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": NAMING_REMINDER}}


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
        data = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(data) > MAX_INPUT:
            return
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
