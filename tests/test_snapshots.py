"""Selected Git storage and protocol3 startup admission regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from test_workflow import Fixture, SCRIPT, w


class ScopedSnapshotTests(Fixture):
    def test_selected_blobs_literal_paths_attributes_and_unrelated_inventory(self):
        tree = self.repo / 'unrelated'; tree.mkdir()
        for number in range(16001):
            (tree / str(number)).touch()
        (self.repo / '.gitattributes').write_text('code.py export-ignore\n*.txt export-subst\n')
        (self.repo / 'literal*.txt').write_text('$Format:%H$\n')
        (self.repo / 'literal-other.txt').write_text('outside')
        (self.repo / 'entry.sh').write_text('#!/bin/sh\nexit 0\n'); (self.repo / 'entry.sh').chmod(0o755)
        (tree / 'unsupported').symlink_to('../code.py')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Scope fixture')
        scope = {'entrypoints': ['entry.sh'], 'code': ['code.py'], 'configs': [], 'assets': ['literal*.txt']}
        commands = []
        actual = subprocess.run
        def capture(argv, **kwargs):
            commands.append(argv)
            return actual(argv, **kwargs)
        with mock.patch.object(w.subprocess, 'run', side_effect=capture):
            with w.selected_snapshot(str(self.repo), 'HEAD', scope) as (files, modes, objects):
                self.assertEqual(set(files), {'entry.sh', 'code.py', 'literal*.txt'})
                self.assertEqual(files['literal*.txt'].read_text(), '$Format:%H$\n')
                self.assertEqual(files['code.py'].read_bytes(), (self.repo / 'code.py').read_bytes())
                self.assertEqual(modes['entry.sh'], '100755')
                self.assertEqual(set(objects), set(files))
        self.assertEqual(len(commands), 2)
        self.assertIn('--literal-pathspecs', commands[0])
        missing = {**scope, 'assets': ['untracked']}
        self.error('snapshot_path_missing', lambda: self.export(missing))
        selected_link = {**scope, 'assets': ['unrelated/unsupported']}
        self.error('unsupported_dependency', lambda: self.export(selected_link))
        (self.repo / 'pointer').write_text('version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n')
        self.git(self.repo, 'add', 'pointer'); self.git(self.repo, 'commit', '-m', 'Pointer fixture')
        self.error('unsupported_dependency', lambda: self.export({**scope, 'assets': ['pointer']}))

    def export(self, scope):
        with w.selected_snapshot(str(self.repo), 'HEAD', scope) as result:
            return result

    def test_store_reuse_commit_independence_modes_corruption_and_race(self):
        scope = w.normalize_snapshot_scope({'entrypoints': ['code.py'], 'code': [], 'configs': ['uv.lock'], 'assets': []})
        container = self.base / 'store'
        with w.selected_snapshot(str(self.repo), 'HEAD', scope) as (files, modes, objects):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(w.immutable_code_store, container, scope, files, modes) for _ in range(2)]
                results = []
                for future in futures:
                    try:
                        results.append(future.result())
                    except w.WorkflowError as error:
                        self.assertEqual(error.code, 'locked')
                first = results[0]
            second = w.immutable_code_store(container, scope, files, modes)
        self.assertEqual(first, second)
        (self.repo / 'irrelevant').write_text('different commit')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Unrelated change')
        with w.selected_snapshot(str(self.repo), 'HEAD', scope) as (files, modes, objects):
            self.assertEqual(w.immutable_code_store(container, scope, files, modes), first)
            identity = {'format': 1, 'snapshot_scope': scope, 'files': {name: {'sha256': w.sha_file(path), 'mode': modes[name]} for name, path in files.items()}}
            corrupt = self.base / 'corrupt'; corrupt.mkdir(); winner = corrupt / w.digest(identity); winner.mkdir()
            self.error('snapshot_changed', lambda: w.immutable_code_store(corrupt, scope, files, modes))
            self.assertEqual(list(winner.iterdir()), [])
        file = Path(first['directory']) / 'code/code.py'; file.chmod(0o644)
        self.error('snapshot_changed', lambda: w.check_code_store(first))

    def test_new_contract_required_before_preparation_event(self):
        self.integrated()
        version = self.state['version']
        self.error('snapshot_scope_required', lambda: w.dispatch('run-prepare', {'root':str(self.root), 'task_id':'task',
            'actor':'owner', 'expected_version':version, 'run_id':'missing', 'environment_id':'runtime', 'lockfiles':['uv.lock'],
            'argv':['python','-c','pass'], 'artifacts':[]}))
        self.assertEqual(self.refresh()['version'], version)
        schema = next(value['inputSchema'] for value in w.command_schemas() if value['name'] == 'run-prepare')
        self.assertEqual(set(schema['properties']['snapshot_scope']['properties']), set(w.SCOPE_ROLES))
        self.assertIn('reference', schema['properties']['origin_checks']['items']['properties'])

    def test_verification_baseline_calls_same_store_and_real_startup_gate(self):
        self.integrated()
        args = self.startup_fields()
        current = self.prepare()['run']
        result = w.prepare_verification_snapshot(self.state, commit=self.git(self.repo, 'rev-parse','HEAD'),
            directory=self.root / '.experiments/verification/task/baselines/check', environment_id='runtime',
            authorization_source='Fixture project baseline request', **args)
        self.assertEqual(result['startup']['status'], 'passed')
        self.assertEqual(result['baseline']['code_store'], current['code_store'])
        self.assertEqual(result['baseline']['purpose'], 'development-verification')
        self.assertNotIn('integration', result['baseline'])
        self.assertTrue(w.startup_receipt_valid(result['baseline'], result['startup']))
        self.assertEqual(set(self.refresh()['runs']), {'run'})

    def test_uv_environment_origins_and_mutable_code_redirection(self):
        self.integrated()
        package_root = next((self.environment / 'lib').glob('python*/site-packages'))
        cache = self.base / 'uv-cache'; cache.mkdir(); (cache / 'module.py').write_text('VALUE=7\n')
        (package_root / 'module.py').symlink_to(cache / 'module.py')
        logical = self.repo / '.venv'; logical.symlink_to(self.environment, target_is_directory=True)
        self.op('environment-register', environment_id='uv', path=str(logical), authorization_source='Existing uv environment')
        relative = str((package_root / 'module.py').relative_to(self.environment))
        current = self.prepare(environment_id='uv', origin_checks=[{'id':'package', 'reference':'environment','path':relative},
            {'id':'interpreter','reference':'environment','path':'bin/python'}], validation_argv=[str(logical / 'bin/python'), '-c',
                'import module,sys,json,os; from pathlib import Path; assert module.VALUE == 7; '
                'Path(os.environ["TASK_WORKFLOW_STARTUP_REPORT"]).write_text(json.dumps({'
                '"token":os.environ["TASK_WORKFLOW_STARTUP_TOKEN"],"references":[],"origins":['
                '{"id":"entrypoint:code.py","path":str(Path("code.py").absolute())},'
                '{"id":"package","path":module.__file__},{"id":"interpreter","path":sys.executable}]}))'])['run']
        self.assertEqual(self.op('run-execute', run_id='run')['run']['status'], 'awaiting_artifacts')
        inputs = current['startup_inputs']['origins']
        self.assertEqual(next(item for item in inputs if item['id']=='package')['resolved_path'], str(cache / 'module.py'))
        self.assertNotEqual(next(item for item in inputs if item['id']=='interpreter')['resolved_path'], str(logical / 'bin/python'))
        (package_root / 'module.py').unlink(); (package_root / 'module.py').symlink_to(self.repo / 'code.py')
        self.error('development_reference', lambda: self.prepare(run_id='bad', environment_id='uv',
            origin_checks=[{'id':'bad','reference':'environment','path':relative}]))

    def test_report_missing_bad_origin_reference_and_missing_dependency_never_start_main(self):
        self.integrated()
        data = self.base / 'weights'; data.write_bytes(b'versioned weights')
        ref = {'id':'weights','role':'checkpoint','path':str(data),'identity':'weights-v1','evidence':['Fixture fixed content']}
        variants = [(['python','-c','print("ok")'], []),
            (['python','-c','raise SystemExit(9)'], []),
            (['python','-c','import missing_selected_dependency'], [])]
        for index, (command, refs) in enumerate(variants):
            run_id = 'failure' + str(index)
            current = self.prepare(run_id=run_id, validation_argv=command, fixed_references=refs)['run']
            result = self.op('run-execute', run_id=run_id)['run']
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['execution']['workload_started'])
            self.assertFalse((Path(current['directory']) / 'result.txt').exists())
            self.error('run_execution_unknown', lambda: self.op('run-accept', run_id=run_id, artifact_notes='Must not accept startup only'))
        # The validator's real observations must cover the reference as well as origins.
        current = self.prepare(run_id='reference', fixed_references=[ref])['run']
        result = self.op('run-execute', run_id='reference')['run']
        self.assertEqual(result['startup']['error'], 'startup_report_invalid')
        bad_identity = self.startup_fields()['validation_argv'][-1].replace('\"references\":[]', '\"references\":[{\"id\":\"weights\",\"identity\":\"wrong-version\"}]')
        self.prepare(run_id='wrong-reference', fixed_references=[ref], validation_argv=['python','-c',bad_identity])
        self.assertEqual(self.op('run-execute',run_id='wrong-reference')['run']['startup']['error'], 'startup_report_invalid')
        self.assertEqual(current['startup_inputs']['references'][0]['sha256'], w.sha_file(data))
        bad = self.startup_fields()['validation_argv'][-1].replace('str(Path("code.py").absolute())','str(Path("uv.lock").absolute())')
        self.prepare(run_id='wrong-origin', validation_argv=['python','-c',bad])
        self.assertEqual(self.op('run-execute',run_id='wrong-origin')['run']['startup']['error'], 'startup_report_invalid')

    def test_startup_is_outside_lifecycle_lock_and_final_resource_admission_is_fresh(self):
        self.integrated()
        self.op('resource-register', resource_id='capacity', handle='fixture',provided_by='user',can_release=False,
            authorization_source='Fixture external resource',ownership_evidence=['Fixture owner'],capabilities={},
            observed_state='available',evidence=['Available now'])
        started, release = self.base / 'probe-started', self.base / 'probe-release'
        command = self.startup_fields()['validation_argv'][-1]
        command = ('import time; from pathlib import Path; Path(' + repr(str(started)) + ').touch(); '
            'exec("while not Path(' + repr(str(release)) + ').exists(): time.sleep(0.01)"); ' + command)
        current = self.prepare(resource_id='capacity', validation_argv=['python','-c',command])['run']
        dispatch = self.op('run-dispatch',run_id='run')
        runner = subprocess.Popen(dispatch['runner_argv'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            while not started.exists() and runner.poll() is None:
                time.sleep(0.01)
            self.assertTrue(started.exists(), runner.communicate() if runner.poll() is not None else '')
            self.refresh()
            self.assertEqual(self.state['runs']['run']['status'], 'starting')
            resource = w.dispatch('resource-status',{'root':str(self.root),'resource_id':'capacity'})['resource']
            self.op('resource-observe',resource_id='capacity',expected_resource_version=resource['version'],
                observed_state='unknown',capabilities={},evidence=['Capacity changed while validator ran'])
            release.touch()
            output, errors = runner.communicate()
            self.assertEqual(runner.returncode,0,errors.decode())
        finally:
            release.touch()
            if runner.poll() is None:
                runner.kill(); runner.communicate()
        self.refresh(); self.op('run-reconcile',run_id='run')
        self.assertEqual(self.state['runs']['run']['startup']['error'],'resource_unavailable')
        self.assertFalse((Path(current['directory']) / 'result.txt').exists())

    def test_failed_main_spawn_and_changed_startup_receipt_are_explicit(self):
        self.integrated()
        self.prepare(argv=['/nonexistent/workflow-test-executable'])
        failed = self.op('run-execute', run_id='run')['run']
        self.assertEqual(failed['status'], 'failed')
        self.assertFalse(failed['execution']['workload_started'])
        self.assertEqual(failed['execution']['workload_error'], 'workload_spawn_failed')
        self.assertEqual(failed['startup']['status'], 'passed')
        self.prepare(run_id='good')
        current = self.op('run-execute', run_id='good')['run']
        receipt = Path(current['directory']) / 'startup-receipt.json'
        receipt.write_text('{}')
        self.error('execution_receipt_invalid', lambda: self.op('run-accept',run_id='good',artifact_notes='Changed validation receipt'))

    def test_legacy_unfinished_preparation_preserves_original_inputs_and_backend(self):
        self.integrated()
        legacy = self.legacy_module('148215d')
        arguments = {'root':str(self.root),'task_id':'task','actor':'owner','expected_version':self.state['version'],
            'run_id':'old','environment_id':'runtime','lockfiles':['uv.lock'],'argv':['python','-c','pass'],
            'artifacts':[],'dependency_declaration':'no-external-local-dependencies'}
        with mock.patch.object(legacy, 'pin_runtime', side_effect=RuntimeError('Interrupted old preparation')):
            with self.assertRaises(RuntimeError):
                legacy.dispatch('run-prepare', arguments)
        self.refresh(); before = copy.deepcopy(self.state)
        self.error('legacy_preparation', lambda: self.prepare(run_id='old',argv=['python','-c','pass'],artifacts=[]))
        self.assertEqual(self.refresh(), before)
        arguments['expected_version'] = before['version']
        recovered = legacy.dispatch('run-prepare', arguments)['run']; self.refresh()
        self.assertEqual(recovered['runtime']['execution_protocol'], 2)
        self.assertEqual(self.op('run-execute',run_id='old')['run']['execution']['returncode'],0)

    def test_environment_change_during_validator_denies_main_and_claim_prevents_replay(self):
        self.integrated()
        command = self.startup_fields()['validation_argv'][-1]
        command += '; Path(os.environ["VIRTUAL_ENV"],"pyvenv.cfg").write_text(Path(os.environ["VIRTUAL_ENV"],"pyvenv.cfg").read_text()+"# changed by fixture\\n")'
        current = self.prepare(validation_argv=['python','-c',command])['run']
        dispatched = self.op('run-dispatch',run_id='run')
        result = subprocess.run(dispatched['runner_argv'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())
        self.refresh(); self.op('run-reconcile',run_id='run')
        self.assertEqual(self.state['runs']['run']['startup']['error'],'environment_changed')
        self.assertFalse((Path(current['directory']) / 'result.txt').exists())
        log_hash = w.sha_file(Path(current['directory']) / 'startup.log')
        second = subprocess.run(dispatched['runner_argv'],capture_output=True)
        self.assertNotEqual(second.returncode,0)
        self.assertEqual(w.sha_file(Path(current['directory']) / 'startup.log'),log_hash)

    def legacy_module(self, commit):
        folder = self.base / ('legacy-' + commit); folder.mkdir(exist_ok=True)
        repository = Path(__file__).resolve().parents[1]
        for name in ('workflow.py','runner.py'):
            (folder / name).write_bytes(subprocess.check_output(['git','-C',str(repository),'show',commit + ':skills/task-workflow/scripts/' + name]))
        spec = importlib.util.spec_from_file_location('legacy_'+commit,folder / 'workflow.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_actual_protocol2_continues_and_old_backend_cannot_execute_or_reconcile_three(self):
        self.integrated()
        legacy = self.legacy_module('148215d')
        fields = {'root':str(self.root),'task_id':'task','actor':'owner','expected_version':self.state['version'],
            'run_id':'old','environment_id':'runtime','lockfiles':['uv.lock'],'argv':['python','-c','pass'],
            'artifacts':[],'dependency_declaration':'no-external-local-dependencies'}
        old = legacy.dispatch('run-prepare',fields)['run']; self.refresh()
        frozen = {name:(Path(old['runtime']['directory'])/name).read_bytes() for name in old['runtime']['files']}
        self.assertEqual(self.op('run-execute',run_id='old')['run']['execution']['returncode'],0)
        for name, content in frozen.items():
            self.assertEqual((Path(old['runtime']['directory'])/name).read_bytes(),content)
        current = self.prepare(run_id='new')['run']
        arguments = {'root':str(self.root),'task_id':'task','actor':'owner','expected_version':self.state['version'],'run_id':'new'}
        with self.assertRaises(legacy.WorkflowError) as caught:
            legacy.dispatch('run-dispatch',arguments)
        self.assertEqual(caught.exception.code,'legacy_runtime')
        dispatched = self.op('run-dispatch',run_id='new')
        result = subprocess.run(dispatched['runner_argv'],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode()); self.refresh()
        for commit in ('148215d','cc1711d'):
            old_reader = legacy if commit == '148215d' else self.legacy_module(commit)
            with self.assertRaises(old_reader.WorkflowError) as caught:
                old_reader.dispatch('run-reconcile',{**arguments,'expected_version':self.state['version']})
            self.assertEqual(caught.exception.code,'execution_receipt_invalid')
        self.op('run-reconcile',run_id='new')
        receipt = self.state['runs']['new']['execution']
        self.assertNotEqual(receipt['argv_digest'],w.digest(current['argv']))
        report = Path(receipt['startup']['report']); report.write_text('{}')
        self.error('execution_receipt_invalid',lambda:self.op('run-accept',run_id='new',artifact_notes='Changed startup proof'))
