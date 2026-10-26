"""Frozen runtime execution, receipts, artifact acceptance, and closure checks."""
import json
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
