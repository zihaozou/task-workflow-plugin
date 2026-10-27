"""Append-only environment references preserve existing tasks and old readers."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

from test_workflow import Fixture, w, SCRIPT
import test_process as process_fixtures


class EnvironmentTests(Fixture):
    def enroll(self, arguments):
        return super().enroll({**arguments, 'environment_registry': {}})

    def register(self, name='training', path=None, **fields):
        return self.op('environment-register', environment_id=name, path=str(path or self.environment),
                       authorization_source='Actual fixture request to reuse the existing environment', **fields)

    def events(self):
        return sorted((self.root / '.task-workflow/tasks/task/events').glob('*.json'))

    def test_existing_empty_task_appends_path_and_audit_in_one_event_without_fingerprinting(self):
        self.assertEqual(self.state['environment_registry'], {})
        empty = self.base / 'existing-empty-environment'; empty.mkdir()
        before = copy.deepcopy(self.state)
        with mock.patch.object(w, 'env_fingerprint', side_effect=AssertionError('Registration must not audit or rebuild')):
            result = self.register(path=empty)
        self.assertFalse(result['already_registered'])
        self.assertEqual(self.state['environment_registry'], {'training': str(empty)})
        registration = self.state['environment_registrations']['training']
        self.assertEqual(registration['path'], str(empty))
        self.assertEqual(registration['actor'], 'owner')
        self.assertEqual(registration['authorization_source'], 'Actual fixture request to reuse the existing environment')
        self.assertTrue(registration['time'])
        event = json.loads(self.events()[-1].read_text())
        self.assertEqual(event['operation'], 'environment-register')
        paths = [patch['path'] for patch in event['patches']]
        self.assertIn(['environment_registry', 'training'], paths)
        self.assertIn(['environment_registrations'], paths)
        for key in ('runs', 'design', 'approval', 'items', 'integration', 'task_lifecycle', 'decisions'):
            self.assertEqual(self.state[key], before[key])
        self.assertEqual(self.state['version'], before['version'] + 1)

    def test_same_logical_path_retry_preserves_original_audit_and_event_count(self):
        self.register()
        before, events = copy.deepcopy(self.state), len(self.events())
        result = self.op('environment-register', environment_id='training', path=str(self.environment),
                         authorization_source='Later retry source must not replace the original source')
        self.assertTrue(result['already_registered'])
        self.assertEqual(self.state, before)
        self.assertEqual(len(self.events()), events)
        with mock.patch.dict('os.environ', {'HOME': str(self.base)}):
            result = self.op('environment-register', environment_id='training', path='~/environment',
                             authorization_source='Equivalent expanded logical path retry')
        self.assertTrue(result['already_registered'])
        self.assertEqual(self.state, before)

    def test_init_registered_id_is_idempotent_without_invented_source_backfill(self):
        state = w.dispatch('init', {'root': str(self.root), 'project': str(self.repo), 'task_id': 'enrolled',
            'title': 'Already enrolled environment', 'actor': 'owner', 'authorization_source': 'Actual enrollment',
            'environment_registry': {'runtime': str(self.environment)}})['state']
        result = w.dispatch('environment-register', {'root': str(self.root), 'task_id': 'enrolled', 'actor': 'owner',
            'expected_version': state['version'], 'environment_id': 'runtime', 'path': str(self.environment),
            'authorization_source': 'Actual retry'})
        self.assertTrue(result['already_registered'])
        self.assertEqual(result['state'], state)
        self.assertNotIn('environment_registrations', result['state'])

    def test_actor_version_closed_task_and_conflicting_id_guards_preserve_history(self):
        before = copy.deepcopy(self.state)
        self.error('coordinator_required', lambda: self.register(actor='other'))
        self.assertEqual(self.state, before)
        self.register()
        self.error('revision_conflict', lambda: self.register(expected_version=before['version']))
        other = self.base / 'another-environment'; other.mkdir()
        self.error('environment_conflict', lambda: self.register(path=other))
        self.assertEqual(self.state['environment_registry']['training'], str(self.environment))
        self.approved()
        self.op('task-complete', outcome='stopped', notes='Fixture concluded', evidence=['Fixture completion'])
        self.error('task_closed', lambda: self.register())

    def test_invalid_id_path_and_authorization_do_not_append_events(self):
        before = copy.deepcopy(self.state)
        for name in ('bad/id', '', '../escape'):
            self.error('invalid_identifier', lambda: self.register(name=name))
        for path in ('relative', str(self.base / 'missing'), str(self.repo / 'code.py')):
            self.error('invalid_environment', lambda: self.register(path=path))
        self.error('invalid_text', lambda: self.op('environment-register', environment_id='training', path=str(self.environment), authorization_source=''))
        self.assertEqual(self.state, before)

    def test_logical_symlink_spelling_is_preserved_like_init(self):
        alias = self.base / 'logical-environment'; alias.symlink_to(self.environment, target_is_directory=True)
        self.register(path=alias)
        self.assertEqual(self.state['environment_registry']['training'], str(alias))
        self.error('environment_conflict', lambda: self.register(path=self.environment))

    def test_existing_frozen_run_environment_and_approval_are_unchanged(self):
        self.register(name='runtime')
        self.integrated()
        self.prepare()
        before = copy.deepcopy(self.state)
        another = self.base / 'another-reference'; another.mkdir()
        self.register(name='another', path=another)
        self.assertEqual(self.state['runs'], before['runs'])
        self.assertEqual(self.state['approval'], before['approval'])
        self.assertEqual(self.state['design'], before['design'])
        self.assertEqual(self.state['environment_registry']['runtime'], before['environment_registry']['runtime'])

    def test_old_readers_preserve_registration_and_reject_format3_writes(self):
        self.register()
        root = Path(__file__).resolve().parents[1]
        versions = {'0.1.9': 'cc1711d90b479aa4382758f59ee600d9e933a86e',
                    '0.1.13': '148215d40d000710c33669a94963f0fb789f6afa'}
        for version, revision in versions.items():
            source = subprocess.check_output(['git', '-C', str(root), 'show', revision + ':skills/task-workflow/scripts/workflow.py'])
            reader = self.base / ('reader-' + version + '.py'); reader.write_bytes(source)
            spec = importlib.util.spec_from_file_location('environment_reader_' + version.replace('.', '_'), reader)
            old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
            path = self.root / '.task-workflow/tasks/task'
            current = copy.deepcopy(self.state)
            read, _ = old.load_events(path)
            self.assertEqual(read, current)
            with self.assertRaises(old.WorkflowError) as denied:
                old.dispatch('decision', {'root': str(self.root), 'task_id': 'task', 'actor': 'owner',
                    'expected_version': current['version'], 'content': 'Obsolete writer attempt ' + version})
            self.assertEqual(denied.exception.code, 'legacy_read_only')
            self.op('decision', content='Current canonical writer preserves registration')
            self.refresh()
            self.assertEqual(self.state['environment_registry'], current['environment_registry'])
            self.assertEqual(self.state['environment_registrations'], current['environment_registrations'])

    def test_schema_cli_and_mcp_use_the_actual_append_operation(self):
        schemas = {entry['name']: entry['inputSchema'] for entry in w.command_schemas()}
        self.assertEqual(len(schemas), 61)
        self.assertEqual(set(schemas['environment-register']['required']),
            {'root', 'task_id', 'actor', 'expected_version', 'environment_id', 'path', 'authorization_source'})
        arguments = {'task_id': 'task', 'actor': 'owner', 'expected_version': self.state['version'],
                     'environment_id': 'training', 'path': str(self.environment), 'authorization_source': 'Actual CLI fixture request'}
        result = subprocess.run([sys.executable, str(SCRIPT), 'environment-register', '--root', str(self.root),
                                 '--json-args', json.dumps(arguments)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.refresh()
        scripts = SCRIPT.parent
        sys.path.insert(0, str(scripts))
        import mcp_server
        server = mcp_server.Server(); server.initialized = True
        arguments.update(root=str(self.root), expected_version=self.state['version'])
        reply = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                               'params': {'name': 'environment-register', 'arguments': arguments}})
        self.assertFalse(reply['result']['isError'])
        self.assertTrue(json.loads(reply['result']['content'][0]['text'])['already_registered'])


class EnvironmentApprovalTests(Fixture):
    structured = True
    discussion = process_fixtures.ProcessTests.discussion
    design_content = process_fixtures.ProcessTests.design_content
    designed = process_fixtures.ProcessTests.designed
    plan_content = process_fixtures.ProcessTests.plan_content
    planned = process_fixtures.ProcessTests.planned
    approved = process_fixtures.ProcessTests.approved

    def test_registration_preserves_approved_spec_plan_and_stage(self):
        self.approved()
        before = copy.deepcopy(self.state)
        extra = self.base / 'existing-reference'; extra.mkdir()
        self.op('environment-register', environment_id='extra', path=str(extra), authorization_source='Actual request to reuse an existing environment')
        for key in ('process', 'design', 'approval', 'items', 'integration', 'runs'):
            self.assertEqual(self.state[key], before[key])
        self.assertEqual(w.summary(self.state)['stage'], 'implementation')
