#!/usr/bin/env python3
"""Restore selected facts for an existing task bound to this project and session."""
import json
from pathlib import Path
import re
import sys

import workflow

SAFE_ID = re.compile(r'[A-Za-z0-9_-]+\Z')
ITEM_STATES = ('pending', 'implementing', 'reviewing', 'complete')
RUN_STATES = ('planned', 'preparing', 'prepared', 'queued', 'running', 'awaiting_artifacts', 'complete',
              'failed', 'cancelled', 'unknown')


def safe_id(value):
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def safe_counts(value, allowed):
    if not isinstance(value, dict):
        return {}
    return {key: number for key, number in value.items()
            if key in allowed and type(number) is int and 0 <= number}


def context_for(event):
    if not isinstance(event, dict) or event.get('hook_event_name') != 'SessionStart':
        return None
    if event.get('source') not in ('startup', 'resume', 'compact'):
        return None
    session_id, cwd = event.get('session_id'), event.get('cwd')
    if not safe_id(session_id) or not isinstance(cwd, str) or any(ord(c) < 32 for c in cwd):
        return None
    path = Path(cwd)
    if not path.is_absolute() or not path.is_dir():
        return None
    root = workflow.find_registered_root(path)
    if root is None:
        return None
    root = Path(root).resolve()
    if not root.is_absolute() or any(ord(c) < 32 for c in str(root)):
        return None
    listing = workflow.dispatch('list', {'root': str(root)})
    tasks = listing.get('tasks', [])
    if not isinstance(tasks, list):
        return None
    matches = [item for item in tasks if isinstance(item, dict)
               and item.get('session_id') == session_id and safe_id(item.get('task_id'))]
    selections = listing.get('session_bindings', {})
    if not isinstance(selections, dict):
        return None
    if session_id in selections:
        selected = selections[session_id]
        matches = [item for item in matches if item['task_id'] == selected]
    if len(matches) != 1:
        return None
    task_id = matches[0]['task_id']
    result = workflow.dispatch('status', {'root': str(root), 'task_id': task_id})
    status = result.get('summary')
    if not isinstance(status, dict) or status.get('task_id') != task_id or status.get('session_id') != session_id:
        return None
    current_selection = result.get('session_bindings', {})
    if not isinstance(current_selection, dict) or (session_id in current_selection and current_selection[session_id] != task_id):
        return None
    facts = {'task_id': task_id}
    for key in ('version', 'active_runs', 'open_experiments'):
        number = status.get(key)
        if type(number) is int and 0 <= number:
            facts[key] = number
    if status.get('task_status') in ('open', 'complete', 'unrecorded'):
        facts['task_status'] = status['task_status']
    for key in ('approved', 'integrated'):
        if type(status.get(key)) is bool:
            facts[key] = status[key]
    facts['counts'] = safe_counts(status.get('counts'), ITEM_STATES)
    facts['run_counts'] = safe_counts(status.get('run_counts'), RUN_STATES)
    stages = ('exploration', 'discussion', 'design', 'design_review', 'design_confirmation',
              'plan', 'plan_confirmation', 'implementation', 'delivery')
    if status.get('process_protocol') == 2 and status.get('stage') in stages:
        facts['process_protocol'] = 2
        facts['stage'] = status['stage']
        if type(status.get('plan_approved')) is bool:
            facts['plan_approved'] = status['plan_approved']
    templates = ['templates/conversation.md', 'templates/record.md']
    if facts.get('stage') in ('implementation', 'delivery'):
        templates += ['templates/worker-briefs.md', 'templates/worker-reports.md']
    context = 'Registered Task Workflow context: ' + json.dumps(
        {'root': str(root), 'session_id': session_id, 'status_tool': 'status', 'task': facts,
         'templates': templates,
         'view_tool': {'name': 'workflow.status_view', 'arguments': {'root': str(root), 'task_id': task_id, 'session_id': session_id}},
         'recovery_guidance': 'Restore the recorded phase and its template. Call a lifecycle MCP tool or workflow.status_view to supply this chat view binding. CLI calls and hook delivery do not invoke native UI or authorize work.'},
        separators=(',', ':'), ensure_ascii=True)
    return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': context}}


def unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def main():
    try:
        data = sys.stdin.buffer.read()
        event = json.loads(data.decode('utf-8'), object_pairs_hook=unique_pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
        result = context_for(event)
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=True) + '\n')
    except Exception:
        # Recovery must not obstruct unrelated sessions or expose private input.
        return


if __name__ == '__main__':
    main()
