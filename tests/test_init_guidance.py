"""Enrollment guidance preserves existing path and ownership guard semantics."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/task-workflow/scripts/workflow.py'
SPEC = importlib.util.spec_from_file_location('init_guidance_workflow', SCRIPT)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


class InitGuidanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Fixture Author')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.project / 'README.md').write_text('Fixture project.\n')
        self.git('add', 'README.md')
        self.git('commit', '-m', 'Initial fixture')
        self.args = dict(root=str(self.project), project=str(self.project),
                         task_id='report-export', title='Report export', actor='coordinator',
                         authorization_source='Synthetic fixture request')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], stderr=subprocess.DEVNULL)

    def test_schema_adds_guidance_without_changing_operation_fields(self):
        schemas = workflow.command_schemas()
        self.assertEqual(len(schemas), 61)
        self.assertEqual({entry['name'] for entry in schemas}, set(workflow.COMMANDS))
        for entry in schemas:
            command = workflow.COMMANDS[entry['name']]
            schema = entry['inputSchema']
            self.assertEqual(schema['required'], list(command['required']))
            fields = {**command['required'], **command['optional']}
            self.assertEqual(set(schema['properties']), set(fields))
            for key, kind in fields.items():
                self.assertEqual(schema['properties'][key]['type'], kind)
            self.assertFalse(schema['additionalProperties'])
        properties = next(entry for entry in schemas if entry['name'] == 'init')['inputSchema']['properties']
        for key in ('root', 'project', 'worktree', 'owned_worktree', 'task_id', 'session_id'):
            self.assertTrue(properties[key]['description'])
        self.assertEqual(properties['owned_worktree']['examples'], [False])

    def test_invalid_project_recovery_keeps_original_error_codes(self):
        subdirectory = self.project / 'nested'
        subdirectory.mkdir()
        plain = self.base / 'plain'
        plain.mkdir()
        for value, code in [('reporting', 'invalid_path'), (str(self.base / 'missing'), 'invalid_path'),
                            (str(subdirectory), 'git_identity'), (str(plain), 'git_error')]:
            with self.subTest(project=value), self.assertRaises(workflow.WorkflowError) as raised:
                workflow.dispatch('init', {**self.args, 'project': value})
            self.assertEqual(raised.exception.code, code)
            self.assertIn('init.project', raised.exception.message)
            self.assertIn('absolute Git checkout root', raised.exception.message)
        self.assertFalse((self.project / '.task-workflow').exists())

    def test_base_ownership_recovery_keeps_existing_rejection(self):
        with self.assertRaises(workflow.WorkflowError) as raised:
            workflow.dispatch('init', {**self.args, 'owned_worktree': True})
        self.assertEqual(raised.exception.code, 'invalid_ownership')
        self.assertIn('false', raised.exception.message)
        self.assertIn('worktree-prepare', raised.exception.message)

    def test_valid_base_enrollment_and_dedicated_worktree_guards(self):
        result = workflow.dispatch('init', {**self.args, 'owned_worktree': False})
        self.assertTrue(result['ok'])
        self.assertEqual(result['state']['project']['path'], str(self.project))
        self.assertEqual(result['state']['worktree']['path'], str(self.project))
        self.assertFalse(result['state']['owned_worktree'])
        other = self.base / 'other-checkout'
        self.git('worktree', 'add', '-b', 'wrong-location', str(other))
        with self.assertRaises(workflow.WorkflowError) as raised:
            workflow.dispatch('init', {**self.args, 'task_id': 'other', 'worktree': str(other)})
        self.assertEqual(raised.exception.code, 'worktree_association')


if __name__ == '__main__':
    unittest.main()
