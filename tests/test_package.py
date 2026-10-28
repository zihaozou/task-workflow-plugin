"""Check unified release assets and Python-only Codex hook and tool discovery."""
import hashlib
import json
import os
import queue
import re
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
NATIVE_RELEASE_FILES = {
    'README.md', 'package.json', 'adapters/deepseek/index.js',
    'adapters/deepseek/cordis.patch.yml', 'adapters/deepseek/delegation.js',
    'adapters/deepseek/recovery.js', 'hooks/hooks.json',
    'skills/task-workflow/SKILL.md', 'skills/task-workflow/agents/openai.yaml',
    'skills/task-workflow/references/workflow.md',
    'assets/icon.svg', 'assets/icon.png',
    'skills/task-workflow/references/deepseek.md',
} | {'skills/task-workflow/scripts/' + name for name in (
    'bootstrap.py', 'workflow.py', 'runner.py', 'mcp_server.py', 'session_hook.py',
    'communication_prompt_hook.py', 'deepseek_context.py',
)} | {'skills/task-workflow/templates/' + name for name in (
    'README.md', 'phases.md', 'conversation.md', 'record.md',
    'worker-briefs.md', 'worker-reports.md', 'spec.md', 'plan.md',
)}
sys.path.insert(0, str(SCRIPTS))
import communication_prompt_hook
import session_hook


class PackageTests(unittest.TestCase):
    def test_selected_codex_manifest_declares_shipped_components(self):
        self.assertFalse((ROOT / 'plugin.json').exists())
        manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'task-workflow')
        self.assertEqual(manifest['version'], '0.1.19')
        self.assertNotIn('license', manifest)
        self.assertEqual(manifest['hooks'], './hooks/hooks.json')
        interface = manifest['interface']
        self.assertEqual(interface['category'], 'Productivity')
        self.assertLessEqual(len(interface['shortDescription']), 30)
        self.assertEqual(interface['capabilities'], [])
        for key in ('logo', 'composerIcon'):
            relative = Path(interface[key])
            self.assertFalse(relative.is_absolute())
            self.assertNotIn('..', relative.parts)
            self.assertTrue((ROOT / relative).is_file())
            self.assertIn(relative.as_posix(), NATIVE_RELEASE_FILES)
        for key in ('skills', 'mcpServers', 'hooks'):
            self.assertTrue((ROOT / manifest[key]).exists())

    def test_native_bundle_matches_codex_release_and_declares_shipped_entrypoints(self):
        manifest = json.loads((ROOT / 'package.json').read_text())
        codex = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], '@local/task-workflow')
        self.assertEqual(manifest['version'], codex['version'])
        self.assertTrue(manifest['private'])
        self.assertEqual(manifest['type'], 'module')
        self.assertEqual(manifest['exports']['.'], './adapters/deepseek/index.js')
        patch = manifest['dsh']['bundle']['patch']
        self.assertEqual(patch, './adapters/deepseek/cordis.patch.yml')
        self.assertIn("name: '@local/task-workflow'", (ROOT / patch).read_text())
        for dependency in ('dsh-hooks-codex', 'dsh-hook-protocol'):
            self.assertEqual(manifest['dependencies']['@deepseek-ai/' + dependency], '0.2.1-rc.3')
        for dependency in ('dsh-mcp-client', 'dsh-skill-filesystem', 'dsh-subprocess', 'dsh-tool-subagent', 'dsh-llm-retry', 'dsh-llm'):
            self.assertEqual(manifest['peerDependencies']['@deepseek-ai/' + dependency], '0.2.1-rc.3')
        for relative in NATIVE_RELEASE_FILES:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

    @unittest.skipUnless(shutil.which('npm'), 'npm is needed only for the native archive development check')
    def test_native_pack_contains_release_assets_and_excludes_private_data(self):
        result = subprocess.run(['npm', 'pack', '--dry-run', '--json'], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        packages = json.loads(result.stdout)
        self.assertEqual(len(packages), 1)
        package = packages[0]
        self.assertEqual(package['name'], '@local/task-workflow')
        self.assertEqual(package['version'], '0.1.19')
        paths = [entry['path'] for entry in package['files']]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(set(paths), NATIVE_RELEASE_FILES)
        private_parts = {'.git', '.task-workflow', '.worktrees', '.experiments',
                         'experiments', 'runs', 'profiles', '.dsh', '.agents',
                         'auth', 'credentials', 'node_modules', '__pycache__',
                         '.venv', '.pytest_cache', '.mypy_cache', 'tests'}
        for relative in paths:
            with self.subTest(path=relative):
                path = Path(relative)
                self.assertFalse(path.is_absolute())
                self.assertFalse(set(path.parts) & (private_parts | {'..'}))
                self.assertFalse(path.name.startswith('.env'))
                self.assertNotIn(path.suffix, {'.pyc', '.pyo', '.log', '.tgz'})

    def test_repository_marketplace_exposes_exactly_this_plugin(self):
        marketplace = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual(marketplace['name'], 'task-workflow-plugins')
        self.assertEqual(len(marketplace['plugins']), 1)
        plugin = marketplace['plugins'][0]
        self.assertEqual(plugin['name'], 'task-workflow')
        self.assertEqual(plugin['source'], {'source': 'local', 'path': './'})
        self.assertEqual(plugin['category'], 'Productivity')
        self.assertEqual(plugin['policy'], {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'})

    @unittest.skipUnless(shutil.which('npm'), 'npm is needed for release archive verification')
    def test_generated_runtime_and_lock_are_excluded_from_native_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary)
            for relative in NATIVE_RELEASE_FILES:
                destination = staged / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            runtime = staged / 'skills/task-workflow/.venv'
            runtime.mkdir()
            (runtime / 'unshipped.py').write_text('generated runtime data')
            (runtime.parent / '.runtime-bootstrap.lock').touch()
            result = subprocess.run(['npm', 'pack', '--dry-run', '--json'], cwd=staged,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            paths = {entry['path'] for entry in json.loads(result.stdout)[0]['files']}
            self.assertEqual(paths, NATIVE_RELEASE_FILES)

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
            self.assertEqual(server['cwd'], '.')
            self.assertEqual(server['args'], ['-I', 'skills/task-workflow/scripts/bootstrap.py', '--', 'skills/task-workflow/scripts/mcp_server.py'])
            self.assertTrue((ROOT / server['cwd'] / server['args'][1]).is_file())

    def test_declared_relative_mcp_command_starts_from_plugin_path_with_spaces(self):
        server = json.loads((ROOT / '.mcp.json').read_text())['mcpServers']['task-workflow']
        with tempfile.TemporaryDirectory(prefix='plugin root with spaces ') as temporary:
            plugin = Path(temporary)
            shutil.copyfile(ROOT / 'package.json', plugin / 'package.json')
            target = plugin / 'skills/task-workflow/scripts'
            target.mkdir(parents=True)
            for source in SCRIPTS.glob('*.py'):
                shutil.copyfile(source, target / source.name)
            messages = [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                    'name': 'schema', 'arguments': {'root': str(plugin)}}},
            ]
            result = subprocess.run([server['command']] + server['args'],
                                    cwd=plugin / server['cwd'],
                                    input=''.join(json.dumps(message) + '\n' for message in messages),
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([reply['id'] for reply in replies], [1, 2, 3])
            self.assertEqual(replies[0]['result']['serverInfo']['name'], 'task-workflow')
            package_version = json.loads((ROOT / 'package.json').read_text())['version']
            self.assertEqual(replies[0]['result']['serverInfo']['version'], package_version)
            tools = replies[1]['result']['tools']
            expected = session_hook.workflow.command_schemas()
            expected_names = {entry['name'] for entry in expected}
            actual_names = [tool['name'] for tool in tools]
            self.assertEqual(set(actual_names), expected_names)
            self.assertEqual(len(actual_names), len(expected_names))
            self.assertIn('environment-bind', expected_names)
            self.assertEqual([{key: tool[key] for key in schema}
                              for tool, schema in zip(tools, expected)], expected)
            self.assertFalse(replies[2]['result']['isError'])
            self.assertTrue(json.loads(replies[2]['result']['content'][0]['text'])['ok'])

    def test_skill_supports_implicit_routing_and_has_no_setup_dependency(self):
        skill = (ROOT / 'skills/task-workflow/SKILL.md').read_text()
        self.assertTrue(skill.startswith('---\nname: task-workflow\ndescription: '))
        self.assertIn('allow_implicit_invocation: true', (ROOT / 'skills/task-workflow/agents/openai.yaml').read_text())
        self.assertIn('.worktrees/<task-id>', skill)
        self.assertIn('.experiments/<experiment-id>', skill)
        self.assertFalse((ROOT / 'scripts/configure.py').exists())
        self.assertFalse((ROOT / 'examples').exists())
        self.assertFalse((SCRIPTS / 'install.py').exists())
        self.assertTrue((ROOT / 'skills/task-workflow/references/workflow.md').is_file())

    def test_structured_templates_are_shipped_and_linked(self):
        base = ROOT / 'skills/task-workflow'
        assets = ('README.md', 'phases.md', 'conversation.md', 'record.md',
                  'worker-briefs.md', 'worker-reports.md', 'spec.md', 'plan.md')
        for name in assets:
            path = base / 'templates' / name
            with self.subTest(name=name):
                self.assertTrue(path.is_file())
                content = path.read_text()
                self.assertTrue(content.startswith('# '))
                self.assertTrue(content.isascii(), 'Authored templates must be English ASCII')
                for link in re.findall(r'\]\(([^)]+\.md)\)', content):
                    if link.startswith('https://'):
                        continue
                    self.assertTrue((path.parent / link).is_file(), link)
        for path in (base / 'SKILL.md', base / 'references/workflow.md', ROOT / 'README.md'):
            content = path.read_text()
            for link in re.findall(r'\]\(([^)]+\.md)\)', content):
                if link.startswith('http'):
                    continue
                self.assertTrue((path.parent / link).is_file(), f'{path}: {link}')

    def test_phase_contract_and_record_sections(self):
        base = ROOT / 'skills/task-workflow/templates'
        phases = (base / 'phases.md').read_text()
        for name in ('Intent', 'Exploration', 'Multi-round discussion',
                     'Design draft and independent gap review', 'User design approval',
                     'Implementation plan and user plan approval',
                     'Delegated implementation and item review',
                     'Overall review and integration', 'Optional experiments and delivery'):
            section = phases.split('## ' + name + '\n', 1)[1].split('\n## ', 1)[0]
            for field in ('INPUT:', 'CONVERSATION:', 'WRITE:', 'EXIT:', 'RETURN:'):
                self.assertIn(field, section, f'{name}: {field}')
        record = (base / 'record.md').read_text()
        headings = re.findall(r'^## (.+)$', record, re.MULTILINE)
        self.assertEqual(headings, ['Current state', 'Intent', 'Exploration',
                                    'Confirmed requirements', 'Sourced decisions',
                                    'Design', 'Implementation plan',
                                    'Execution and review', 'Experiments and runs',
                                    'Delivery', 'Decision history'])
        brief = (base / 'worker-briefs.md').read_text()
        for role in ('Coordinator', 'Explorer', 'Design reviewer', 'Implementer',
                     'Task reviewer', 'Overall reviewer'):
            self.assertIn('## ' + role + '\n\n```text', brief)
        reports = (base / 'worker-reports.md').read_text()
        self.assertIn('Requirements verdict:', reports)
        self.assertIn('Quality verdict:', reports)

    def test_runtime_assets_and_python_syntax(self):
        for name in ('workflow.py', 'runner.py', 'mcp_server.py',
                     'session_hook.py', 'communication_prompt_hook.py', 'deepseek_context.py'):
            self.assertTrue((SCRIPTS / name).is_file(), name)
        self.assertFalse((SCRIPTS / 'status_view.py').exists())
        self.assertFalse((ROOT / 'skills/task-workflow/assets/workflow.html').exists())
        for relative in sorted(set(subprocess.check_output(['git', 'ls-files', '--', '*.py'], cwd=ROOT, text=True).splitlines()) | {name for name in NATIVE_RELEASE_FILES if name.endswith('.py')}):
            path = ROOT / relative
            compile(path.read_text(), str(path), 'exec')

    def test_shipped_guidance_uses_persisted_status_and_session_recovery(self):
        paths = (ROOT / 'README.md', ROOT / 'skills/task-workflow/SKILL.md',
                 ROOT / 'skills/task-workflow/references/workflow.md',
                 SCRIPTS / 'session_hook.py', SCRIPTS / 'communication_prompt_hook.py')
        for path in paths:
            with self.subTest(path=path):
                content = path.read_text()
                for removed in ('workflow.status_view', 'workflow.refresh_view', 'view_required',
                                'Workflow tab', 'openai/session'):
                    self.assertNotIn(removed, content)
                self.assertIn('session', content)

    def test_hook_command_supports_plugin_paths_with_spaces(self):
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), {'SessionStart', 'UserPromptSubmit'})
        with tempfile.TemporaryDirectory(prefix='plugin path with spaces ') as temporary:
            target = Path(temporary) / 'skills/task-workflow/scripts'
            target.mkdir(parents=True)
            for name in ('bootstrap.py', 'communication_prompt_hook.py', 'session_hook.py', 'workflow.py'):
                (target / name).write_bytes((SCRIPTS / name).read_bytes())
            for event, entries in hooks.items():
                command = entries[0]['hooks'][0]['command'].replace('${PLUGIN_ROOT}', temporary)
                self.assertEqual(len(shlex.split(command)), 5)
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
                    native_mcp = subprocess.run([cli, 'mcp', 'get', 'task-workflow', '--json'],
                                                env=env, cwd=staged, capture_output=True,
                                                text=True, timeout=30)
                    self.assertEqual(native_mcp.returncode, 0, native_mcp.stderr)
                    transport = json.loads(native_mcp.stdout)['transport']
                    self.assertEqual(transport['command'], 'python3')
                    self.assertEqual(transport['args'], ['-I', 'skills/task-workflow/scripts/bootstrap.py', '--', 'skills/task-workflow/scripts/mcp_server.py'])
                    installed_root = Path(transport['cwd'])
                    self.assertTrue(installed_root.is_relative_to(home))
                    self.assertTrue((installed_root / transport['args'][1]).is_file())
                    self.assertNotIn('${PLUGIN_ROOT}', json.dumps(transport))
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
                        installed = json.loads(source.read_text())['hooks']
                        self.assertEqual(set(installed), {'SessionStart', 'UserPromptSubmit'})
                        for entries in installed.values():
                            for entry in entries:
                                for command in entry['hooks']:
                                    self.assertEqual(set(command), {'type', 'command'})
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

    def test_exact_binding_emits_only_selected_facts(self):
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
            self.assertEqual(dispatch.call_args_list[-1], mock.call('context', {'root': str(path), 'task_id': 'example'}))

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

    def test_prompt_context_is_fixed_and_has_no_enrollment_side_effects(self):
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
        for entries in hooks.values():
            for entry in entries:
                for hook in entry['hooks']:
                    self.assertEqual(set(hook), {'type', 'command'})
        for event in ({}, {'hook_event_name': 'Stop', 'prompt': 'hello'},
                      {'hook_event_name': 'UserPromptSubmit', 'prompt': ' '}):
            self.assertIsNone(communication_prompt_hook.context_for(event))

    def test_hook_rejects_duplicate_or_invalid_input_without_output(self):
        for data in (b'{"hook_event_name":"SessionStart","hook_event_name":"UserPromptSubmit"}', b'x' * (1024 * 1024 + 1)):
            result = subprocess.run([sys.executable, str(SCRIPTS / 'session_hook.py')], input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')
            self.assertEqual(result.stderr, b'')

    def test_both_hooks_accept_input_larger_than_one_mib(self):
        payload = "x" * (1024 * 1024 + 1)
        for name, event in (("communication_prompt_hook.py", {"hook_event_name": "UserPromptSubmit", "prompt": payload}),
                            ("session_hook.py", {"hook_event_name": "SessionStart", "source": "startup", "session_id": "s", "cwd": "/tmp", "extra": payload})):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                (folder / name).write_bytes((SCRIPTS / name).read_bytes())
                (folder / "workflow.py").write_text("from pathlib import Path\nGOAL_INTEGRITY = 'Preserve the complete fixture goal.'\nCHECK_STATES = ()\ndef find_registered_root(path): return path\ndef dispatch(op, args):\n    return {'tasks': [{'task_id': 't', 'session_id': 's'}]} if op == 'list' else {'summary': {'task_id': 't', 'session_id': 's'}}\n")
                result = subprocess.run([sys.executable, str(folder / name)], input=json.dumps(event), text=True,
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('additionalContext', json.loads(result.stdout)['hookSpecificOutput'])

    def test_session_context_preserves_long_identifiers_paths_and_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            for _ in range(9):
                path = path / ("long-directory-" + "x" * 80)
            path.mkdir(parents=True)
            session_id, task_id = "session-" + "s" * 1000, "task-" + "t" * 1000
            count = 10**20
            responses = [{"tasks": [{"task_id": task_id, "session_id": session_id}]},
                         {"summary": {"task_id": task_id, "session_id": session_id, "version": count,
                                      "active_runs": count, "counts": {"complete": count}}}]
            with mock.patch.object(session_hook.workflow, 'find_registered_root', return_value=path), \
                    mock.patch.object(session_hook.workflow, 'dispatch', side_effect=responses):
                result = session_hook.context_for(self.event(path, session_id))
            context = result['hookSpecificOutput']['additionalContext']
            self.assertGreater(len(context), 1600)
            facts = json.loads(context.removeprefix('Registered Task Workflow context: '))
            self.assertEqual(facts['root'], str(path.resolve()))
            self.assertEqual(facts['session_id'], session_id)
            self.assertEqual(facts['task']['task_id'], task_id)
            self.assertEqual(facts['task']['active_runs'], count)
            self.assertEqual(facts['task']['counts']['complete'], count)


if __name__ == '__main__':
    unittest.main()
