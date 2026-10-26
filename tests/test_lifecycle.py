"""Frozen runtime execution, receipts, artifact acceptance, and closure checks."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest import mock
from test_workflow import Fixture, w


class LifecycleTests(Fixture):
    def test_real_frozen_execution_and_artifact_acceptance(self):
        self.integrated()
        self.op('experiment-create', experiment_id='study', goal='Verify frozen execution')
        current = self.prepare(experiment_id='study')['run']
        self.assertEqual(set(current['runtime']['files']), {'workflow.py', 'runner.py'})
        self.assertEqual(Path(current['directory']), self.repo / '.experiments/study/runs/run')
        self.assertNotEqual(os.stat(Path(current['code']) / 'code.py').st_ino, os.stat(self.repo / 'code.py').st_ino)
        result = self.op('run-execute', run_id='run', timeout=30)['run']
        self.assertEqual(result['status'], 'awaiting_artifacts')
        self.assertEqual(result['execution']['returncode'], 0)
        self.error('execution_denied', lambda: self.op('run-execute', run_id='run'))
        self.op('run-accept', run_id='run', artifact_notes='Output contains expected fixture result.')
        self.op('experiment-complete', experiment_id='study', outcome='completed', notes='Research output accepted.', evidence=['result.txt'])
        self.op('task-complete', outcome='completed', notes='Integrated task and research accepted.', evidence=['Integration verification', 'result.txt'])
        self.assertEqual(self.state['task_lifecycle']['status'], 'complete')

    def test_runtime_and_snapshot_tampering_are_rejected(self):
        self.integrated(); current = self.prepare()['run']
        code = Path(current['code']) / 'code.py'; code.chmod(0o644); code.write_text('CHANGED = True\n')
        self.error('snapshot_changed', lambda: self.op('run-execute', run_id='run'))
        self.assertEqual(self.state['runs']['run']['status'], 'prepared')

    def test_receipt_recovers_interrupted_state_update_without_repeat(self):
        self.integrated(); self.prepare()
        original = w.commit_event
        def interrupt(path, state, previous, operation, actor):
            if operation == 'run-execution-result':
                raise RuntimeError('Fixture interrupted after receipt')
            return original(path, state, previous, operation, actor)
        with mock.patch.object(w, 'commit_event', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.op('run-execute', run_id='run', timeout=30)
        self.assertEqual(self.state['runs']['run']['status'], 'running')
        self.op('run-reconcile', run_id='run')
        self.assertEqual(self.state['runs']['run']['status'], 'awaiting_artifacts')
        self.assertTrue(self.op('run-reconcile', run_id='run')['already_recorded'])

    def test_timeout_has_actual_failed_receipt(self):
        self.integrated()
        self.op('run-prepare', run_id='timeout', environment_id='runtime', lockfiles=['uv.lock'],
            argv=['python','-c','import time; time.sleep(30)'], artifacts=['unused.txt'], dependency_declaration='no-external-local-dependencies')
        result = self.op('run-execute', run_id='timeout', timeout=1)['run']
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['execution']['returncode'], 124)
        self.error('run_execution_unknown', lambda: self.op('run-accept', run_id='timeout', artifact_notes='Cannot accept timeout'))

    def test_detached_runtime_receipt_reconciles_without_reexecution(self):
        self.integrated(); self.prepare()
        result = self.op('run-execute', run_id='run', timeout=30, detached=True)
        self.assertTrue(result['reconciliation_required'])
        directory = Path(result['run']['directory'])
        import time
        deadline = time.monotonic() + 10
        while not (directory / 'execution-receipt.json').exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((directory / 'execution-receipt.json').is_file())
        self.refresh()  # The actual runner records a separate start event.
        self.op('run-reconcile', run_id='run')
        self.assertEqual(self.state['runs']['run']['status'], 'awaiting_artifacts')

    def test_finished_snapshot_preparation_recovers_after_event_interruption(self):
        self.integrated()
        original = w.commit_event
        def interrupt(path, state, previous, operation, actor):
            if operation == 'run-prepare':
                raise RuntimeError('Fixture interruption after snapshot')
            return original(path, state, previous, operation, actor)
        with mock.patch.object(w, 'commit_event', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.prepare()
        self.assertEqual(self.state['runs']['run']['status'], 'preparing')
        result = self.prepare()
        self.assertTrue(result['recovered'])
        self.assertEqual(result['run']['status'], 'prepared')

    def test_owned_partial_snapshot_recovers_without_deleting_material(self):
        self.integrated()
        with mock.patch.object(w, 'pin_runtime', side_effect=RuntimeError('Fixture runtime interruption')):
            with self.assertRaises(RuntimeError):
                self.prepare()
        current = self.state['runs']['run']
        directory = self.repo / '.experiments/verification/task/run'
        self.assertTrue((directory / '.preparation-intent.json').is_file())
        self.assertFalse((directory / 'snapshot.json').exists())
        preserved = directory / 'unique.txt'; preserved.write_text('preserve')
        self.error('preparation_changed', self.prepare)
        self.assertEqual(preserved.read_text(), 'preserve')
        preserved.unlink()
        self.assertEqual(self.prepare()['run']['status'], 'prepared')

    def test_changed_or_deleted_accepted_artifacts_block_success_and_release(self):
        self.integrated()
        self.op('resource-register', resource_id='resource', handle='artifact-fixture', provided_by='user', can_release=True,
            authorization_source='Fixture permission', ownership_evidence=['Owner evidence'], capabilities={},
            observed_state='available', evidence=['Available evidence'], valid_for_seconds=3600)
        self.op('experiment-create', experiment_id='study', goal='Check accepted output proof')
        current = self.prepare(experiment_id='study', resource_id='resource')['run']
        self.op('run-execute', run_id='run', timeout=30)
        self.op('run-accept', run_id='run', artifact_notes='Accepted fixture output')
        artifact = Path(current['directory']) / 'result.txt'
        original = artifact.read_bytes()
        for change in ('changed', 'deleted'):
            if change == 'changed':
                artifact.write_text('changed')
            else:
                artifact.unlink()
            self.error('accepted_evidence_changed', lambda: self.op('experiment-complete', experiment_id='study',
                outcome='completed', notes='Must retain accepted output', evidence=['Output']))
            artifact.write_bytes(original)
        self.op('experiment-complete', experiment_id='study', outcome='completed', notes='Output proof current', evidence=['Output'])
        artifact.write_text('changed')
        self.error('accepted_evidence_changed', lambda: self.op('task-complete', outcome='completed', notes='Must retain proof', evidence=['Output']))
        artifact.write_bytes(original)
        self.op('task-complete', outcome='completed', notes='Proof verified', evidence=['Output'])
        self.op('cleanup', dry_run=False)
        (self.repo / 'later.txt').write_text('Later unrelated commit')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Later base change')
        query = lambda: w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'resource'})['resource']
        self.assertTrue(query()['eligibility']['eligible'])
        for change in ('changed', 'deleted'):
            eligible = query()
            if change == 'changed':
                artifact.write_text('changed')
            else:
                artifact.unlink()
            self.assertEqual(query()['eligibility']['reason'], 'accepted_evidence_changed')
            self.error('release_denied', lambda: self.op('resource-release', resource_id='resource', expected_resource_version=eligible['version'],
                eligibility_key=eligible['eligibility']['key'], authorization_source='Fixture release', argv=[sys.executable, '-c', 'pass']))
            artifact.write_bytes(original)

    def test_unbounded_default_waits_without_timeout(self):
        self.integrated(); current = self.prepare()['run']
        dispatched = self.op('run-dispatch', run_id='run')
        self.assertNotIn('--timeout', dispatched['runner_argv'])
        self.assertIsNone(dispatched['run']['execution_intent']['timeout'])
        spec = importlib.util.spec_from_file_location('pinned_runner_test', Path(current['runtime']['directory']) / 'runner.py')
        runner = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'workflow': w}):
            spec.loader.exec_module(runner)
        process = mock.Mock(pid=987654321)
        process.wait.return_value = 0
        actual_popen = subprocess.Popen
        def popen(argv, **kwargs):
            return process if kwargs.get('env', {}).get('TASK_WORKFLOW_OUTPUT_DIR') else actual_popen(argv, **kwargs)
        with mock.patch.object(runner.subprocess, 'Popen', side_effect=popen), mock.patch.object(runner.os, 'killpg'):
            receipt = runner.execute(str(self.root), 'task', 'run', current['token'])
        self.assertEqual(receipt['returncode'], 0)
        self.assertEqual(process.wait.call_args_list[0], mock.call(timeout=None))
        self.assertEqual(process.wait.call_args_list[1], mock.call())
        self.refresh()
        self.op('run-observe', run_id='run', receipt_path=str(Path(current['directory']) / 'execution-receipt.json'), evidence=['Actual fixture runner receipt'])
        self.assertEqual(self.state['runs']['run']['status'], 'awaiting_artifacts')

    def test_explicit_run_timeout_above_one_hour(self):
        self.integrated(); self.prepare()
        result = self.op('run-execute', run_id='run', timeout=7200)['run']
        self.assertEqual(result['execution']['returncode'], 0)
        self.assertEqual(result['execution_intent']['timeout'], 7200)
        verified = self.op('integration-verify', argv=[sys.executable, '-c', 'pass'], timeout=7200)
        self.assertTrue(verified['verification']['passed'])
        self.error('invalid_arguments', lambda: self.op('run-dispatch', run_id='run', timeout=0))

    def test_external_dispatch_is_durable_and_at_most_once(self):
        self.integrated(); current = self.prepare()['run']
        first = self.op('run-dispatch', run_id='run')
        self.assertEqual(first['run']['status'], 'queued')
        self.assertNotIn('start_validated', first['run'])
        self.assertFalse((Path(current['directory']) / 'execution.claim').exists())
        self.assertEqual(first['summary']['run_counts']['queued'], 1)
        version = first['state']['version']
        repeated = self.op('run-dispatch', run_id='run')
        self.assertTrue(repeated['already_dispatched'])
        self.assertEqual(repeated['state']['version'], version)
        self.assertEqual(first['runner_argv'], repeated['runner_argv'])
        self.error('execution_denied', lambda: self.op('run-dispatch', run_id='run', timeout=1))
        self.error('execution_receipt_invalid', lambda: self.op('run-observe', run_id='run', receipt_path=str(Path(current['directory']) / 'execution-receipt.json'), evidence=['No actual start']))
        completed = subprocess.run(first['runner_argv'], capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.refresh()
        started = self.state['runs']['run']
        self.assertEqual(started['status'], 'running')
        self.assertGreater(started['start_validated']['pid'], 0)
        self.assertTrue(started['start_validated']['host'])
        duplicate = subprocess.run(first['runner_argv'], capture_output=True, timeout=30)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual((Path(current['directory']) / 'result.txt').read_text(), 'ok')
        self.op('run-observe', run_id='run', receipt_path=str(Path(current['directory']) / 'execution-receipt.json'), evidence=['Actual frozen execution'])
        self.assertEqual(self.state['runs']['run']['status'], 'awaiting_artifacts')
        self.assertEqual(self.op('run-dispatch', run_id='run')['runner_argv'], first['runner_argv'])

    def test_synchronous_default_caller_has_no_timeout(self):
        self.integrated(); self.prepare()
        original = w.run
        def capture(argv, **kwargs):
            if '--run-id' in argv:
                self.assertIsNone(kwargs['timeout'])
                self.assertNotIn('--timeout', argv)
            return original(argv, **kwargs)
        with mock.patch.object(w, 'run', side_effect=capture):
            self.assertEqual(self.op('run-execute', run_id='run')['run']['execution']['returncode'], 0)

    def test_unclaimed_dispatch_cancels_and_delayed_runner_is_denied(self):
        self.integrated(); current = self.prepare()['run']
        dispatched = self.op('run-dispatch', run_id='run')
        self.op('run-cancel', run_id='run', reason='Withdraw unclaimed external intent')
        self.assertEqual(self.state['runs']['run']['status'], 'cancelled')
        delayed = subprocess.run(dispatched['runner_argv'], capture_output=True, timeout=30)
        self.assertNotEqual(delayed.returncode, 0)
        self.assertFalse((Path(current['directory']) / 'execution.claim').exists())

    def test_actual_legacy_runtime_is_rejected_before_any_launch_or_mutation(self):
        self.integrated()
        source = self.base / 'baseline-runtime'; source.mkdir()
        baseline = '3b73c52e1a0aa59abb9ffa823e9957811ace2b73'
        repository = Path(__file__).resolve().parents[1]
        for name in ('workflow.py', 'runner.py'):
            content = subprocess.check_output(['git', '-C', str(repository), 'show', baseline + ':skills/task-workflow/scripts/' + name])
            (source / name).write_bytes(content)
        self.assertIn('default=3600', (source / 'runner.py').read_text())
        spec = importlib.util.spec_from_file_location('legacy_workflow_fixture', source / 'workflow.py')
        legacy = importlib.util.module_from_spec(spec); spec.loader.exec_module(legacy)
        with mock.patch.object(w, 'pin_runtime', side_effect=legacy.pin_runtime):
            current = self.prepare(run_id='legacy')['run']
        version = self.state['version']
        frozen_files = {name: (Path(current['runtime']['directory']) / name).read_bytes() for name in current['runtime']['files']}
        for operation in ('run-execute', 'run-dispatch'):
            with mock.patch.object(subprocess, 'Popen') as launch:
                self.error('legacy_runtime', lambda: self.op(operation, run_id='legacy'))
            launch.assert_not_called()
            self.assertEqual(self.state['version'], version)
            self.assertEqual(self.state['runs']['legacy'], current)
            self.assertFalse((Path(current['directory']) / 'execution.claim').exists())
        # Metadata alone cannot turn old hashed runtime bytes into the new protocol.
        _, store = w.store_dir(str(self.root)); path = w.task_dir(store, 'task')
        state, previous = w.load_events(path)
        state['runs']['legacy']['runtime']['execution_protocol'] = w.EXECUTION_PROTOCOL
        w.commit_event(path, state, previous, 'fixture-protocol-metadata', 'owner'); self.refresh()
        version = self.state['version']
        with mock.patch.object(subprocess, 'Popen') as launch:
            self.error('legacy_runtime', lambda: self.op('run-dispatch', run_id='legacy'))
        launch.assert_not_called(); self.assertEqual(self.state['version'], version)
        for name, content in frozen_files.items():
            self.assertEqual((Path(current['runtime']['directory']) / name).read_bytes(), content)
        self.prepare(run_id='current')
        self.assertEqual(self.state['runs']['current']['runtime']['execution_protocol'], w.EXECUTION_PROTOCOL)
        self.assertEqual(self.op('run-execute', run_id='current')['run']['execution']['returncode'], 0)
