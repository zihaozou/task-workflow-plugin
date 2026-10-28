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
        self.assertEqual(self.state['environment_registry'], {'development':str(self.environment)})
        empty = self.environment
        before = copy.deepcopy(self.state)
        with mock.patch.object(w, 'env_fingerprint', side_effect=AssertionError('Registration must not audit or rebuild')):
            result = self.register(path=empty)
        self.assertFalse(result['already_registered'])
        self.assertEqual(self.state['environment_registry'], {'development':str(self.environment), 'training': str(empty)})
        registration = self.state['environment_registrations']['training']
        self.assertEqual(registration['path'], str(empty))
        self.assertEqual(registration['actor'], 'owner')
        self.assertEqual(registration['authorization_source'], 'Actual fixture request to reuse the existing environment')
        self.assertTrue(registration['time'])
        event = json.loads(self.events()[-1].read_text())
        self.assertEqual(event['operation'], 'environment-register')
        paths = [patch['path'] for patch in event['patches']]
        self.assertIn(['environment_registry', 'training'], paths)
        self.assertIn(['environment_registrations', 'training'], paths)
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
        self.assertTrue(self.register(path=self.environment)['already_registered'])

    def test_existing_frozen_run_environment_and_approval_are_unchanged(self):
        self.op('environment-register', environment_id='runtime', path=str(self.runtime_environment), purpose='runtime', cache_root=str(self.cache_root), install_receipt=str(self.fixture_install_receipt()), project_distributions=[], authorization_source='Actual fixed runtime request')
        self.integrated()
        self.prepare()
        before = copy.deepcopy(self.state)
        another = self.environment
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
        self.assertEqual(len(schemas), 62)
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
        extra = self.environment
        self.op('environment-register', environment_id='extra', path=str(extra), authorization_source='Actual request to reuse an existing environment')
        for key in ('process', 'design', 'approval', 'items', 'integration', 'runs'):
            self.assertEqual(self.state[key], before[key])
        self.assertEqual(w.summary(self.state)['stage'], 'implementation')


class MainEnvironmentTests(Fixture):
    def test_append_once_alias_and_interrupted_event_retry(self):
        before = copy.deepcopy(self.state)
        alias = self.repo / '.venv'; alias.symlink_to(self.environment, target_is_directory=True)
        result = self.op('environment-bind', path=str(alias), authorization_source='Actual same main environment')
        self.assertTrue(result['already_bound'])
        self.assertEqual(self.state, before)
        other = self.base / 'other'; other.mkdir()
        self.error('environment_conflict', lambda: self.op('environment-bind', path=str(other), authorization_source='Actual conflicting selection'))
        # A shared record can survive a failed task event. Retry reconciles its reference.
        state = copy.deepcopy(self.state); state.pop('main_environment_binding')
        result, changed = w.bind_environment({'actor':'owner','path':str(alias),'authorization_source':'Actual retry'}, state, self.root / '.task-workflow')
        self.assertTrue(changed)
        self.assertEqual(state['main_environment_binding'], before['main_environment_binding'])

    def test_stale_registry_cannot_prepare_another_environment(self):
        other = self.base / 'other'; other.mkdir()
        state = copy.deepcopy(self.state); state['environment_registry']['old'] = str(other)
        self.error('environment_conflict', lambda: w.require_project_environment(state, state['environment_registry']['old']))
        self.error('environment_conflict', lambda: self.op('environment-register', environment_id='other', path=str(other), authorization_source='Actual conflicting request'))

    def test_binding_rejects_worktree_and_overlay_without_importing_them(self):
        (self.root / '.task-workflow/environment.json').unlink()
        task_env = self.repo / '.worktrees' / 'task' / 'env'; task_env.mkdir(parents=True)
        self.error('environment_conflict', lambda: self.op('environment-bind', path=str(task_env), authorization_source='Actual selection'))
        overlay = self.base / 'overlay'; package = overlay / 'lib/python3/site-packages'; package.mkdir(parents=True)
        (package / 'reference-runtime.pth').write_text(str(self.environment / 'lib') + '\n')
        self.op('environment-bind', path=str(overlay), authorization_source='Actual development selection')
        self.error('external_import', lambda: w.env_fingerprint(overlay))

    def test_main_environment_contained_pth_and_external_overlay(self):
        main = self.repo / '.venv'; package = main / 'lib/python3/site-packages'; package.mkdir(parents=True)
        contained = package / 'contained'; contained.mkdir()
        pth = package / 'paths.pth'; pth.write_text(str(contained) + '\n')
        self.assertTrue(w.audit_environment_paths(main, (str(self.repo),)))
        pth.write_text(str(self.repo) + '\n')
        self.error('development_import', lambda: w.audit_environment_paths(main, (str(self.repo),)))

    def test_check_environment_uses_main_and_rejects_another_interpreter(self):
        binding = self.state['main_environment_binding']
        current = {'cwd':str(self.repo), 'argv':[str(self.environment / 'bin/python'), '-c', 'pass'], 'main_environment_binding':binding}
        with mock.patch.dict('os.environ', {'VIRTUAL_ENV':'/different', 'PYTHONPATH':'/different'}):
            env = w.check_execution_environment(self.state, current)
        self.assertEqual(env['VIRTUAL_ENV'], str(self.environment))
        self.assertEqual(env['UV_PROJECT_ENVIRONMENT'], str(self.environment))
        self.assertNotIn('PYTHONPATH', env)
        other = self.base / 'other'; (other / 'bin').mkdir(parents=True); (other / 'pyvenv.cfg').write_text('')
        current['argv'] = [str(other / 'bin/python')]
        self.error('environment_conflict', lambda: w.check_execution_environment(self.state, current))

    def test_fixed_check_accepts_alias_and_init_preserves_legacy_reference(self):
        alias = self.repo / '.venv'; alias.symlink_to(self.environment, target_is_directory=True)
        current = {'cwd':str(self.base / 'frozen'), 'source_checkout':{},
                   'main_environment_binding':self.state['main_environment_binding'], 'argv':[str(alias / 'bin/python')]}
        current['source_checkout'] = {'path':current['cwd']}
        self.assertEqual(w.check_execution_environment(self.state, current)['VIRTUAL_ENV'], str(self.environment))
        other = self.base / 'other'; other.mkdir()
        enrolled = self.enroll({'root':str(self.root),'project':str(self.repo),
            'task_id':'other','title':'Other task','actor':'owner','authorization_source':'Actual fixture',
            'environment_registry':{'other':str(other)}})['state']
        self.assertEqual(enrolled['environment_registry'], {'other':str(other)})
        self.error('runtime_environment_required', lambda:w.require_runtime_environment(enrolled, 'other'))

    def test_retained_legacy_preparation_accepts_main_environment_alias(self):
        self.integrated()
        alias = self.base / 'runtime-alias'; alias.symlink_to(self.runtime_environment, target_is_directory=True)
        arguments = {'run_id':'retained', 'environment_id':'runtime', 'lockfiles':['uv.lock'],
                     'argv':[str(alias / 'bin/python'), '-c', 'pass'], 'artifacts':[],
                     'dependency_declaration':'no-external-local-dependencies'}
        state = copy.deepcopy(self.state)
        state['runs']['retained'] = {**w.run_association(arguments, state), 'status':'preparing',
                                    'preparation_token':'fixture', 'preparation_intent':{'argv':arguments['argv']}}
        recovery = copy.deepcopy(state)
        prepared = w.prepare_run_legacy(arguments, state, self.root)['run']
        self.assertEqual(prepared['argv'][0], str(self.runtime_environment / 'bin/python'))
        self.assertTrue(w.prepare_run_legacy(arguments, recovery, self.root)['recovered'])

    def test_retargeted_main_alias_fails(self):
        path = self.root / '.task-workflow/environment.json'
        binding = json.loads(path.read_text())
        alias = self.repo / '.venv'; alias.symlink_to(self.environment, target_is_directory=True)
        binding['logical_path'] = str(alias); w.atomic_json(path, binding)
        other = self.base / 'other'; other.mkdir(); alias.unlink(); alias.symlink_to(other, target_is_directory=True)
        self.error('environment_changed', lambda: w.project_environment(self.state))


class RuntimeProvenanceTests(Fixture):
    def install_distribution(self, environment, name='demo', version='1.0', source=None, linked=False):
        package = next((environment / 'lib').glob('python*/site-packages'))
        metadata = package / (name + '-' + version + '.dist-info'); metadata.mkdir(exist_ok=True)
        (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: ' + name + '\nVersion: ' + version + '\n')
        (metadata / 'RECORD').write_text(name + '.py,,\n')
        module = package / (name + '.py')
        if linked:
            cached = self.cache_root / (name + '.py'); cached.write_text('VALUE = 7\n')
            module.symlink_to(cached)
        else:
            module.write_text('VALUE = 7\n')
        if source is not None:
            (metadata / 'direct_url.json').write_text(json.dumps({'url':Path(source).as_uri(), 'dir_info':{'editable':True}}))
        return metadata, module

    def matching(self):
        main_metadata, _ = self.install_distribution(self.environment)
        runtime_metadata, runtime_module = self.install_distribution(self.runtime_environment, linked=True)
        return main_metadata, runtime_metadata, runtime_module

    def register_runtime(self, name='derived', **fields):
        return self.op('environment-register', environment_id=name, path=str(self.runtime_environment), purpose='runtime',
            cache_root=str(self.cache_root), project_distributions=fields.pop('project_distributions', []),
            install_receipt=str(self.fixture_install_receipt()), authorization_source='Explicit fixture runtime installation', **fields)

    def test_development_editable_and_fixed_runtime_survive_later_main_changes(self):
        main_metadata, runtime_metadata, _ = self.matching()
        source = self.repo / 'src'; source.mkdir()
        self.install_distribution(self.environment, name='spad', source=source)
        package = next((self.environment / 'lib').glob('python*/site-packages'))
        (package / '_editable_impl_spad.pth').write_text(str(source) + '\n')
        w.env_fingerprint(self.environment, (str(self.repo),), allow_development=True)
        result = self.register_runtime(project_distributions=['spad'])
        proof = result['runtime_provenance']
        self.assertEqual(proof['dependency_baseline'], {'demo':'1.0'})
        self.assertEqual(proof['link_mode'], 'symlink')
        self.integrated()
        self.error('runtime_environment_required', lambda:self.prepare(environment_id='development'))
        self.assertNotIn('run', self.refresh()['runs'])
        prepared = self.prepare(environment_id='derived')['run']
        self.assertEqual(prepared['environment']['path'], str(self.runtime_environment))
        self.assertEqual(prepared['argv'][0], str(self.runtime_environment / 'bin/python'))
        self.assertNotIn('main_environment_binding', prepared)
        (main_metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: demo\nVersion: 2.0\n')
        self.assertEqual(w.require_runtime_environment(self.state, 'derived'), proof)
        w.check_run(self.state, prepared)
        self.assertTrue(self.register_runtime(project_distributions=['spad'])['already_registered'])
        (runtime_metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: demo\nVersion: 3.0\n')
        self.error('environment_changed', lambda:w.require_runtime_environment(self.state, 'derived'))

    def test_versions_and_project_exclusions_are_checked(self):
        _, runtime_metadata, _ = self.matching()
        (runtime_metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: demo\nVersion: 2.0\n')
        self.error('dependency_mismatch', lambda:self.register_runtime())
        self.error('project_distribution_required', lambda:self.register_runtime(project_distributions=['demo']))

    def test_cache_copy_hardlink_and_missing_receipt_are_rejected(self):
        _, _, module = self.matching()
        self.error('runtime_install_required', lambda:self.op('environment-register', environment_id='adhoc',
            path=str(self.runtime_environment), purpose='runtime', cache_root=str(self.cache_root),
            authorization_source='Fixture missing actual installer evidence'))
        module.unlink(); module.write_text('VALUE = 7\n')
        self.error('cache_link_required', lambda:self.register_runtime())
        module.unlink()
        import os
        os.link(self.cache_root / 'demo.py', module)
        self.error('cache_link_required', lambda:self.register_runtime())

    def test_receipt_selects_exact_runtime_and_log_content(self):
        self.matching()
        receipt = self.fixture_install_receipt()
        value = json.loads(receipt.read_text()); value['argv'][value['argv'].index('--link-mode') + 1] = 'hardlink'
        w.atomic_json(receipt, value)
        self.error('runtime_install_required', lambda:w.runtime_install_receipt(receipt, self.runtime_environment, self.cache_root))
        receipt = self.fixture_install_receipt()
        value = json.loads(receipt.read_text()); Path(value['stdout_log']).write_text('Changed installation log')
        self.error('runtime_install_required', lambda:w.runtime_install_receipt(receipt, self.runtime_environment, self.cache_root))

    def test_receipt_rejects_dry_run_and_destination_overrides(self):
        cases = [('--dry-run',), ('--dry-run=true',), ('--target', '/elsewhere'),
                 ('--target=/elsewhere',), ('--prefix', '/elsewhere'),
                 ('--prefix=/elsewhere',), ('--system',), ('--system=true',)]
        for flags in cases:
            with self.subTest(flags=flags):
                receipt = self.fixture_install_receipt()
                value = json.loads(receipt.read_text())
                value['argv'].extend(flags)
                w.atomic_json(receipt, value)
                self.error('runtime_install_required', lambda:w.runtime_install_receipt(receipt, self.runtime_environment, self.cache_root))

    def test_metadata_only_distribution_has_explicit_frozen_proof(self):
        for environment in (self.environment, self.runtime_environment):
            metadata, module = self.install_distribution(environment, name='dependency-bundle')
            module.unlink()
            prefix = metadata.name + '/'
            (metadata / 'RECORD').write_text(prefix + 'METADATA,,\n' + prefix + 'RECORD,,\n')
        result = self.register_runtime()
        proof = result['runtime_provenance']
        origin = proof['cache_origins'][0]
        self.assertEqual(origin['distribution'], 'dependency-bundle')
        self.assertEqual(origin['kind'], 'metadata-only')
        self.assertEqual(origin['version'], '1.0')
        self.assertEqual(origin['metadata']['sha256'], w.sha_file(metadata / 'METADATA'))
        self.assertEqual(origin['record']['sha256'], w.sha_file(metadata / 'RECORD'))
        self.assertEqual(w.require_runtime_environment(self.state, 'derived'), proof)

    def test_declared_missing_payload_is_not_metadata_only(self):
        self.matching()
        package = next((self.runtime_environment / 'lib').glob('python*/site-packages'))
        (package / 'demo.py').unlink()
        self.error('cache_link_required', lambda:self.register_runtime())

    def test_runtime_can_live_in_experiment_outputs(self):
        self.matching()
        target = self.repo / '.experiments' / 'experiment' / 'runs' / 'run' / 'runtime'
        target.parent.mkdir(parents=True)
        self.runtime_environment.rename(target); self.runtime_environment = target
        result = self.register_runtime()
        self.assertEqual(result['runtime_provenance']['environment']['path'], str(target))
