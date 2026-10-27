#!/usr/bin/env python3
"""Expose exact task context through a read-only JSON process boundary."""
import json
import math
from pathlib import Path
import re
import sys

import workflow


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
