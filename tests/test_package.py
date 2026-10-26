"""Check portable packaging and project-scoped hook context."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/task-workflow/scripts'
sys.path.insert(0, str(SCRIPTS))
import communication_prompt_hook
import session_hook


class PackageTests(unittest.TestCase):
    def test_manifests_match_published_field_constraints(self):
        manifest = json.loads((ROOT / 'plugin.json').read_text())
        compatibility = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['$schema'], 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json')
        self.assertFalse(set(manifest) - {'$schema', 'name', 'version', 'description', 'author',
                                         'homepage', 'repository', 'license', 'keywords', 'extensions'})
        self.assertRegex(manifest['name'], r'^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$')
        self.assertLessEqual(len(manifest['name']), 64)
        self.assertRegex(manifest['version'], r'^\d+\.\d+\.\d+$')
        self.assertNotIn('license', manifest)
        interface = manifest['extensions']['com.openai']['interface']
        self.assertEqual(interface['category'], 'Productivity')
        self.assertLessEqual(len(interface['shortDescription']), 30)
        self.assertIsInstance(interface['capabilities'], list)
        self.assertEqual(interface, compatibility['interface'])
        for key in ('name', 'version', 'description', 'author'):
            self.assertEqual(manifest[key], compatibility[key])
        for key in ('skills', 'mcpServers', 'hooks'):
            self.assertTrue((ROOT / compatibility[key]).exists())

    def test_repository_marketplace_exposes_exactly_this_plugin(self):
        marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual(marketplace['name'], 'task-workflow-plugins')
        self.assertEqual(len(marketplace['plugins']), 1)
        plugin = marketplace['plugins'][0]
        self.assertEqual(plugin['name'], 'task-workflow')
        self.assertEqual(plugin['source'], {'source': 'local', 'path': './'})
        self.assertEqual(plugin['category'], 'Productivity')
        self.assertEqual(plugin['policy'], {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'})

    def test_mcp_manifest_points_to_shipped_python_entrypoint(self):
        portable = json.loads((ROOT / 'mcp.json').read_text())
        compatibility = json.loads((ROOT / '.mcp.json').read_text())
        self.assertEqual(portable['$schema'], 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json')
        self.assertEqual(portable['mcpServers'], compatibility['mcpServers'])
        self.assertEqual(set(portable), {'$schema', 'mcpServers'})
        for server in portable['mcpServers'].values():
            self.assertEqual(set(server), {'type', 'command', 'args', 'cwd'})
            self.assertEqual(server['type'], 'stdio')
            self.assertEqual(server['command'], 'python3')
            self.assertEqual(server['cwd'], '${PLUGIN_ROOT}')
            self.assertTrue(Path(server['args'][0].replace('${PLUGIN_ROOT}', str(ROOT))).is_file())

    def test_skill_is_explicit_and_has_no_setup_dependency(self):
        skill = (ROOT / 'skills/task-workflow/SKILL.md').read_text()
        self.assertTrue(skill.startswith('---\nname: task-workflow\ndescription: '))
        self.assertLess(len(skill.encode()), 1024 * 1024)
        self.assertIn('allow_implicit_invocation: false', (ROOT / 'skills/task-workflow/agents/openai.yaml').read_text())
        self.assertIn('.worktrees/<task-id>', skill)
        self.assertIn('.experiments/<experiment-id>', skill)
        self.assertFalse((ROOT / 'scripts/configure.py').exists())
        self.assertFalse((ROOT / 'examples').exists())
        self.assertFalse((SCRIPTS / 'install.py').exists())
        self.assertTrue((ROOT / 'skills/task-workflow/references/workflow.md').is_file())

    def test_runtime_assets_and_python_syntax(self):
        for name in ('workflow.py', 'runner.py', 'mcp_server.py', 'status_view.py',
                     'session_hook.py', 'communication_prompt_hook.py'):
            self.assertTrue((SCRIPTS / name).is_file(), name)
        self.assertTrue((ROOT / 'skills/task-workflow/assets/workflow.html').is_file())
        for path in ROOT.rglob('*.py'):
            compile(path.read_text(), str(path), 'exec')

    def test_hook_command_supports_plugin_paths_with_spaces(self):
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), {'SessionStart', 'UserPromptSubmit'})
        with tempfile.TemporaryDirectory(prefix='plugin path with spaces ') as temporary:
            target = Path(temporary) / 'skills/task-workflow/scripts'
            target.mkdir(parents=True)
            for name in ('communication_prompt_hook.py', 'session_hook.py', 'workflow.py'):
                (target / name).write_bytes((SCRIPTS / name).read_bytes())
            for event, entries in hooks.items():
                command = entries[0]['hooks'][0]['command'].replace('${PLUGIN_ROOT}', temporary)
                self.assertEqual(len(shlex.split(command)), 2)
                result = subprocess.run(command, shell=True, text=True, input=json.dumps({
                    'hook_event_name': event, 'source': 'startup', 'session_id': 'session-1',
                    'cwd': temporary, 'prompt': 'Check terminology'}),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                if event == 'UserPromptSubmit':
                    self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['hookEventName'], event)
                else:
                    self.assertEqual(result.stdout, '')


class ContextTests(unittest.TestCase):
    def event(self, path, session='session-1'):
        return {'hook_event_name': 'SessionStart', 'source': 'startup', 'cwd': str(path), 'session_id': session}

    def test_unenrolled_or_unbound_session_is_quiet(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            with mock.patch.object(session_hook.workflow, 'find_registered_root', return_value=None), \
                    mock.patch.object(session_hook.workflow, 'dispatch') as dispatch:
                self.assertIsNone(session_hook.context_for(self.event(path)))
                dispatch.assert_not_called()
            with mock.patch.object(session_hook.workflow, 'find_registered_root', return_value=path), \
                    mock.patch.object(session_hook.workflow, 'dispatch', return_value={'tasks': [
                        {'task_id': 'other-task', 'session_id': 'other-session'}]}) as dispatch:
                self.assertIsNone(session_hook.context_for(self.event(path)))
                self.assertEqual(dispatch.call_count, 1)

    def test_exact_binding_emits_only_bounded_facts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            responses = [{'tasks': [{'task_id': 'example', 'session_id': 'session-1'}]}, {'summary': {
                'task_id': 'example', 'session_id': 'session-1', 'version': 2, 'approved': True, 'task_status': 'open',
                'counts': {'complete': 1, 'secret': 'PRIVATE'}, 'run_counts': {'running': 1},
                'prompt': 'PRIVATE', 'record': 'PRIVATE', 'command': 'PRIVATE'}}]
            with mock.patch.object(session_hook.workflow, 'find_registered_root', return_value=path), \
                    mock.patch.object(session_hook.workflow, 'dispatch', side_effect=responses) as dispatch:
                result = session_hook.context_for(self.event(path))
            context = result['hookSpecificOutput']['additionalContext']
            self.assertIn('example', context)
            self.assertNotIn('PRIVATE', context)
            self.assertLessEqual(len(context), 1600)
            self.assertEqual(dispatch.call_args_list[-1], mock.call('status', {'root': str(path), 'task_id': 'example'}))

    def test_ambiguous_binding_and_invalid_identifiers_are_quiet(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            with mock.patch.object(session_hook.workflow, 'find_registered_root', return_value=path), \
                    mock.patch.object(session_hook.workflow, 'dispatch', return_value={'tasks': [
                        {'task_id': 'first', 'session_id': 'session-1'},
                        {'task_id': 'second', 'session_id': 'session-1'}]}):
                self.assertIsNone(session_hook.context_for(self.event(path)))
            with mock.patch.object(session_hook.workflow, 'find_registered_root') as find:
                self.assertIsNone(session_hook.context_for(self.event(path, 'bad\nsession')))
                event = self.event(path)
                del event['session_id']
                self.assertIsNone(session_hook.context_for(event))
                find.assert_not_called()

    def test_hooks_neither_read_nor_modify_private_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()
            instructions = path / 'AGENTS.md'
            instructions.write_text('Private instructions sentinel.')
            before = hashlib.sha256(instructions.read_bytes()).hexdigest()
            with mock.patch.object(session_hook.workflow, 'find_registered_root', return_value=None), \
                    mock.patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected instruction read')):
                self.assertIsNone(session_hook.context_for(self.event(path)))
                result = communication_prompt_hook.context_for({'hook_event_name': 'UserPromptSubmit', 'prompt': 'Question'})
            self.assertEqual(hashlib.sha256(instructions.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(p.name for p in path.iterdir()), ['AGENTS.md'])
            self.assertNotIn('AGENTS', result['hookSpecificOutput']['additionalContext'])

    def test_real_project_enrollment_and_session_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve()
            commands = [
                ['git', 'init', '-q', str(project)],
                ['git', '-C', str(project), '-c', 'user.name=Example',
                 '-c', 'user.email=example@example.invalid', '-c', 'commit.gpgsign=false',
                 'commit', '--allow-empty', '-qm', 'Test fixture'],
            ]
            for command in commands:
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            instructions = project / 'AGENTS.md'
            instructions.write_text('Private instruction sentinel.')
            before = instructions.read_bytes()
            self.assertIsNone(session_hook.context_for(self.event(project)))
            self.assertFalse((project / '.task-workflow').exists())
            session_hook.workflow.dispatch('init', {
                'root': str(project), 'project': str(project), 'task_id': 'example',
                'title': 'Context fixture', 'actor': 'tester',
                'authorization_source': 'Explicit test enrollment', 'session_id': 'session-1'})
            result = session_hook.context_for(self.event(project))
            self.assertIsNotNone(result)
            context = result['hookSpecificOutput']['additionalContext']
            self.assertIn('"version":1', context)
            self.assertIn('"task_id":"example"', context)
            self.assertIsNone(session_hook.context_for(self.event(project, 'other-session')))
            self.assertEqual(instructions.read_bytes(), before)

    def test_hook_rejects_duplicate_or_oversize_input_without_output(self):
        for data in (b'{"hook_event_name":"SessionStart","hook_event_name":"UserPromptSubmit"}', b'x' * (1024 * 1024 + 1)):
            result = subprocess.run([sys.executable, str(SCRIPTS / 'session_hook.py')], input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')
            self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
