"""Check Codex packaging and project-scoped hook context."""
import hashlib
import json
import os
import queue
import shutil
import threading
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
    def test_selected_codex_manifest_declares_shipped_components(self):
        self.assertFalse((ROOT / 'plugin.json').exists())
        manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'task-workflow')
        self.assertRegex(manifest['version'], r'^\d+\.\d+\.\d+$')
        self.assertNotIn('license', manifest)
        self.assertEqual(manifest['hooks'], './hooks/hooks.json')
        interface = manifest['interface']
        self.assertEqual(interface['category'], 'Productivity')
        self.assertLessEqual(len(interface['shortDescription']), 30)
        self.assertIsInstance(interface['capabilities'], list)
        for key in ('skills', 'mcpServers', 'hooks'):
            self.assertTrue((ROOT / manifest[key]).exists())

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

    def test_skill_supports_implicit_routing_and_has_no_setup_dependency(self):
        skill = (ROOT / 'skills/task-workflow/SKILL.md').read_text()
        self.assertTrue(skill.startswith('---\nname: task-workflow\ndescription: '))
        self.assertLess(len(skill.encode()), 1024 * 1024)
        self.assertIn('allow_implicit_invocation: true', (ROOT / 'skills/task-workflow/agents/openai.yaml').read_text())
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


@unittest.skipUnless(os.environ.get('CODEX_PLUGIN_TEST_CLI'),
                     'Set CODEX_PLUGIN_TEST_CLI to run native isolated hook discovery')
class NativeHookDiscoveryTests(unittest.TestCase):
    def test_clean_install_discovers_plugin_hooks_without_trusting_them(self):
        cli = os.environ['CODEX_PLUGIN_TEST_CLI']
        with tempfile.TemporaryDirectory(prefix='task-workflow-native-') as temporary:
            base = Path(temporary).resolve()
            staged = base / 'package'
            staged.mkdir()
            tracked = subprocess.check_output(
                ['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
            for relative in filter(None, tracked):
                path = Path(relative)
                self.assertFalse(set(path.parts) & {'.git', '.task-workflow', '.worktrees'})
                source = ROOT / path
                if source.is_file():
                    target = staged / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            home = base / 'client-home'
            home.mkdir()
            env = dict(os.environ, CODEX_HOME=str(home))
            for args in (['plugin', 'marketplace', 'add', str(staged), '--json'],
                         ['plugin', 'add', 'task-workflow@task-workflow-plugins', '--json']):
                result = subprocess.run([cli] + args, env=env, cwd=staged,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout))
            messages = queue.Queue()
            with subprocess.Popen([cli, 'app-server'], env=env, cwd=staged,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True) as process:
                def read_messages():
                    for line in process.stdout:
                        try:
                            messages.put(json.loads(line))
                        except ValueError:
                            continue
                threading.Thread(target=read_messages, daemon=True).start()

                def send(message):
                    process.stdin.write(json.dumps(message) + '\n')
                    process.stdin.flush()

                def response(identifier):
                    while True:
                        message = messages.get(timeout=30)
                        if message.get('id') == identifier:
                            self.assertNotIn('error', message, message)
                            return message['result']
                try:
                    send({'id': 1, 'method': 'initialize', 'params': {
                        'clientInfo': {'name': 'task-workflow-package-test', 'version': '1'},
                        'capabilities': {'experimentalApi': True}}})
                    response(1)
                    send({'method': 'initialized', 'params': {}})
                    send({'id': 3, 'method': 'plugin/read', 'params': {
                        'marketplacePath': str(staged / '.agents/plugins/marketplace.json'),
                        'pluginName': 'task-workflow'}})
                    detail = response(3)['plugin']
                    self.assertTrue(detail['summary']['installed'])
                    self.assertTrue(detail['summary']['enabled'])
                    self.assertEqual(len(detail['hooks']), 2)
                    send({'id': 2, 'method': 'hooks/list', 'params': {'cwds': [str(staged)]}})
                    result = response(2)
                    entry = result['data'][0]
                    self.assertEqual(entry['errors'], [])
                    self.assertEqual(entry['warnings'], [])
                    discovered = entry['hooks']
                    self.assertEqual(len(discovered), 2)
                    self.assertEqual({hook['eventName'] for hook in discovered},
                                     {'sessionStart', 'userPromptSubmit'})
                    for hook in discovered:
                        self.assertEqual(hook['source'], 'plugin')
                        self.assertEqual(hook['pluginId'], 'task-workflow@task-workflow-plugins')
                        self.assertEqual(hook['trustStatus'], 'untrusted')
                        self.assertTrue(hook['enabled'])
                        self.assertFalse(hook['isManaged'])
                        source = Path(hook['sourcePath'])
                        self.assertTrue(source.is_relative_to(home))
                        self.assertEqual(source.name, 'hooks.json')
                    print('Native hook discovery: ' + json.dumps([
                        {key: hook[key] for key in ('eventName', 'source', 'pluginId',
                                                   'trustStatus', 'enabled', 'sourcePath')}
                        for hook in discovered], sort_keys=True))
                finally:
                    process.terminate()
                    process.wait(timeout=10)


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

    def test_prompt_context_is_fixed_bounded_and_has_no_enrollment_side_effects(self):
        contexts = []
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            for prompt in ('PRIVATE_PROMPT_SENTINEL', 'Implement the project', 'Show progress'):
                event = {'hook_event_name': 'UserPromptSubmit', 'prompt': prompt,
                         'cwd': temporary, 'transcript_path': '/unreadable/transcript'}
                with mock.patch.object(Path, 'read_text', side_effect=AssertionError('Unexpected read')), \
                        mock.patch.object(Path, 'write_text', side_effect=AssertionError('Unexpected write')):
                    context = communication_prompt_hook.context_for(event)['hookSpecificOutput']['additionalContext']
                contexts.append(context)
            self.assertEqual(list(project.iterdir()), [])
        self.assertEqual(len(set(contexts)), 1)
        context = contexts[0]
        self.assertNotIn('PRIVATE_PROMPT_SENTINEL', context)
        self.assertIn(communication_prompt_hook.ROUTING_GUIDANCE, context)
        self.assertIn(communication_prompt_hook.NAMING_REMINDER, context)
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        limit = hooks['UserPromptSubmit'][0]['hooks'][0]['additionalContextLimit']
        self.assertEqual(limit, 500)
        # English word count catches accidental unbounded prompt inclusion.
        self.assertLess(len(context.split()), limit // 2)
        for event in ({}, {'hook_event_name': 'Stop', 'prompt': 'hello'},
                      {'hook_event_name': 'UserPromptSubmit', 'prompt': ' '}):
            self.assertIsNone(communication_prompt_hook.context_for(event))

    def test_hook_rejects_duplicate_or_oversize_input_without_output(self):
        for data in (b'{"hook_event_name":"SessionStart","hook_event_name":"UserPromptSubmit"}', b'x' * (1024 * 1024 + 1)):
            result = subprocess.run([sys.executable, str(SCRIPTS / 'session_hook.py')], input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')
            self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
