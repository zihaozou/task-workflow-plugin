"""Project session selection and recovery preserve task identity and lifecycle."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/task-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
import session_hook
import workflow


class SessionBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '--allow-empty', '-qm', 'Initial fixture'], check=True, capture_output=True)
        self.core = workflow

    def enroll(self, task_id, session_id=None):
        arguments = {'root': str(self.root), 'project': str(self.root), 'task_id': task_id, 'actor': 'owner',
                     'title': 'Fixture task', 'authorization_source': 'Explicit fixture enrollment'}
        if session_id is not None:
            arguments['session_id'] = session_id
        return self.core.dispatch('init', arguments)['state']

    def bind(self, task_id, session_id='session-1', actor='owner'):
        state = self.core.dispatch('status', {'root': str(self.root), 'task_id': task_id})['state']
        return self.core.dispatch('bind-session', {'root': str(self.root), 'task_id': task_id, 'session_id': session_id,
                                                  'actor': actor, 'expected_version': state['version']})

    def restored_context(self):
        result = session_hook.context_for({'hook_event_name': 'SessionStart', 'source': 'resume',
                                           'cwd': str(self.root), 'session_id': 'session-1'})
        if result is None:
            return None
        return json.loads(result['hookSpecificOutput']['additionalContext'].split(': ', 1)[1])

    def test_explicit_binding_is_guarded_idempotent_and_restores_phase_templates(self):
        original = self.enroll('first')
        self.assertIsNone(self.restored_context())
        with self.assertRaises(self.core.WorkflowError) as denied:
            self.bind('first', actor='other')
        self.assertEqual(denied.exception.code, 'coordinator_required')
        bound = self.bind('first')['state']
        self.assertEqual(bound['version'], original['version'] + 1)
        same = self.bind('first')
        self.assertTrue(same['already_bound'])
        self.assertEqual(same['state']['version'], bound['version'])
        context = self.restored_context()
        self.assertEqual(context['task']['task_id'], 'first')
        self.assertEqual(context['task']['stage'], 'exploration')
        self.assertEqual(context['templates'], ['templates/conversation.md', 'templates/record.md'])
        self.assertNotIn('view_tool', context)
        with self.assertRaises(self.core.WorkflowError) as conflict:
            self.bind('first', 'different-session')
        self.assertEqual(conflict.exception.code, 'session_conflict')

    def test_explicit_session_switch_preserves_tasks_and_reconnects_matching_context(self):
        self.enroll('first', 'session-1')
        second = self.enroll('second', 'session-1')
        self.assertEqual(self.restored_context()['task']['task_id'], 'second')
        first = self.bind('first')['state']
        self.assertEqual(self.restored_context()['task']['task_id'], 'first')
        self.assertEqual(self.core.dispatch('status', {'root': str(self.root), 'task_id': 'second'})['state'], second)
        recovered = self.core.dispatch('recover', {'root': str(self.root), 'task_id': 'second', 'actor': 'owner',
                                                  'expected_version': second['version']})
        self.assertTrue(recovered['recovered'])
        self.assertEqual(self.restored_context()['task']['task_id'], 'first')
        self.assertEqual(self.core.dispatch('status', {'root': str(self.root), 'task_id': 'first'})['state'], first)

    def test_stale_explicit_selection_never_falls_back_and_legacy_ambiguity_is_quiet(self):
        self.enroll('first', 'session-1')
        self.enroll('second', 'session-1')
        registry_path = self.root / '.task-workflow/registry.json'
        registry = self.core.read_json(registry_path)
        registry['session_bindings']['session-1'] = 'missing-task'
        self.core.atomic_json(registry_path, registry)
        self.assertIsNone(self.restored_context())
        del registry['session_bindings']
        self.core.atomic_json(registry_path, registry)
        self.assertIsNone(self.restored_context())
        self.bind('first')
        self.assertEqual(self.restored_context()['task']['task_id'], 'first')

    def test_interrupted_selection_can_be_repaired_by_explicit_bind(self):
        self.enroll('first', 'session-1')
        self.enroll('second', 'session-1')
        register_root = self.core.register_root
        with mock.patch.object(self.core, 'register_root', side_effect=OSError('Simulated selection write failure')):
            with self.assertRaises(OSError):
                self.bind('first')
        self.assertEqual(self.restored_context()['task']['task_id'], 'second')
        repaired = self.bind('first')
        self.assertTrue(repaired['ok'])
        self.assertEqual(self.restored_context()['task']['task_id'], 'first')
        self.assertIs(self.core.register_root, register_root)

    def test_failed_initial_event_preserves_previous_selected_task(self):
        self.enroll('first', 'session-1')
        with mock.patch.object(self.core, 'commit_event', side_effect=OSError('Simulated event failure')):
            with self.assertRaises(OSError):
                self.enroll('second', 'session-1')
        self.assertEqual(self.restored_context()['task']['task_id'], 'first')
        self.assertFalse((self.root / '.task-workflow/tasks/second').exists())
        self.enroll('second', 'session-1')
        self.assertEqual(self.restored_context()['task']['task_id'], 'second')

    def test_first_registry_failure_preserves_committed_task_for_explicit_recovery(self):
        with mock.patch.object(self.core, 'register_root', side_effect=OSError('Simulated first registry failure')):
            with self.assertRaises(OSError):
                self.enroll('first', 'session-1')
        state = self.core.dispatch('status', {'root': str(self.root), 'task_id': 'first'})['state']
        self.assertEqual(state['session_id'], 'session-1')
        result = self.core.dispatch('recover', {'root': str(self.root), 'task_id': 'first', 'actor': 'owner',
                                               'expected_version': state['version']})
        self.assertTrue(result['recovered'])
        self.bind('first')
        self.assertEqual(self.restored_context()['task']['task_id'], 'first')

    def test_binding_a_closed_task_preserves_its_closed_lifecycle(self):
        with mock.patch.object(self.core, 'new_process', return_value=None):
            state = self.enroll('closed')
        def operation(name, **fields):
            nonlocal state
            result = self.core.dispatch(name, {'root': str(self.root), 'task_id': 'closed', 'actor': 'owner',
                                               'expected_version': state['version'], **fields})
            state = result['state']
        operation('design', content='Preserve this stopped fixture.')
        operation('approve', design_digest=state['design']['digest'], authorization_source='Fixture approval')
        operation('task-complete', outcome='stopped', notes='Fixture intentionally stopped.', evidence=['Fixture receipt'])
        closed = copy.deepcopy(state['task_lifecycle'])
        selected = self.bind('closed')['state']
        self.assertEqual(selected['task_lifecycle'], closed)
        self.assertEqual(self.restored_context()['task']['task_status'], 'complete')


class CliLifecycleTests(unittest.TestCase):
    def test_cli_lifecycle_results_match_core_output_without_view_hints(self):
        arguments = {"task_id": "task-a", "session_id": "session-a"}
        output = {"ok": True, "state": {"task_id": "task-a", "session_id": "session-a", "version": 7},
                  "session_bindings": {"session-a": "task-a"}, "recovered": True}
        for name in ("init", "status", "bind-session", "recover"):
            with self.subTest(name=name), mock.patch.object(workflow, "dispatch", return_value=output) as dispatch:
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = workflow.main([name, "--root", "/example", "--json-args", json.dumps(arguments)])
                self.assertEqual(result, 0)
                self.assertEqual(json.loads(stdout.getvalue()), output)
                dispatch.assert_called_once_with(name, {**arguments, "root": "/example"})


if __name__ == "__main__":
    unittest.main()
