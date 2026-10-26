"""Generic resource ownership, aggregate eligibility, and release recovery."""
import json
from pathlib import Path
import sys
import subprocess
from unittest import mock
from test_workflow import Fixture, w


class ResourceTests(Fixture):
    def register(self, **fields):
        return self.op('resource-register', resource_id='resource', handle='opaque-fixture-1', provided_by='user',
            can_release=True, authorization_source='User granted release permission', ownership_evidence=['Fixture owner receipt'],
            capabilities={'units': 2, 'kind': 'fixture'}, observed_state='available', evidence=['Fixture availability'],
            valid_for_seconds=3600, **fields)['resource']

    def resource(self):
        return w.dispatch('resource-status', {'root': str(self.root), 'resource_id': 'resource'})['resource']

    def close(self):
        self.op('task-complete', outcome='stopped', notes='Fixture work stopped.', evidence=['Fixture conclusion'])

    def release(self, resource, command):
        return self.op('resource-release', resource_id='resource', expected_resource_version=resource['version'],
            eligibility_key=resource['eligibility']['key'], authorization_source='Explicit fixture release', argv=command)

    def test_planned_references_and_aggregate_closure_block_release(self):
        self.approved(); self.register()
        resource = self.resource()
        self.assertEqual(resource['derived_state'], 'available')
        self.assertEqual(resource['eligibility']['reason'], 'aggregate_scope_open')
        self.op('run-plan', run_id='planned', resource_id='resource', requirements={'units': 1})
        self.assertEqual(self.resource()['derived_state'], 'in_use')
        self.error('release_denied', lambda: self.release(self.resource(), [sys.executable, '-c', 'pass']))
        self.op('run-cancel', run_id='planned', reason='Fixture cancelled')
        self.close()
        self.assertEqual(self.resource()['derived_state'], 'releasable')

    def test_capability_owner_and_stale_decision_guards(self):
        self.approved(); resource = self.register()
        self.error('resource_mismatch', lambda: self.op('run-plan', run_id='mismatch', resource_id='resource', requirements={'units': 3}))
        self.error('resource_owner', lambda: self.op('resource-observe', actor='other', resource_id='resource', expected_resource_version=resource['version'],
            observed_state='available', capabilities={'units': 2}, evidence=['Observation'], valid_for_seconds=60))
        self.close()
        stale = self.resource()
        self.op('task-reopen', reason='Reopen invalidates release eligibility')
        self.error('stale_resource_decision', lambda: self.release(stale, [sys.executable, '-c', 'pass']))

    def test_release_intent_receipt_and_no_repeat(self):
        self.approved(); self.register(); self.close()
        counter = self.base / 'release-count'
        command = [sys.executable, '-c', 'from pathlib import Path; p=Path(__import__("sys").argv[1]); p.write_text(p.read_text()+"x" if p.exists() else "x")', str(counter)]
        result = self.release(self.resource(), command)['resource']
        self.assertEqual(counter.read_text(), 'x')
        self.assertEqual(result['derived_state'], 'unknown')
        self.error('release_denied', lambda: self.release(result, command))
        confirmed = self.op('resource-release-reconcile', resource_id='resource', expected_resource_version=result['version'],
            token=result['release']['token'], evidence=['Verified release receipt'])['resource']
        self.assertEqual(confirmed['derived_state'], 'released')
        self.assertEqual(counter.read_text(), 'x')

    def test_interrupted_release_receipt_recovery(self):
        self.approved(); self.register(); self.close()
        original = w.commit_event
        def interrupt(path, state, previous, operation, actor):
            if operation == 'resource-release-result':
                raise RuntimeError('Fixture interruption after receipt')
            return original(path, state, previous, operation, actor)
        with mock.patch.object(w, 'commit_event', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.release(self.resource(), [sys.executable, '-c', 'pass'])
        current = self.resource()
        self.assertEqual(current['release']['status'], 'releasing')
        result = self.op('resource-release-reconcile', resource_id='resource', expected_resource_version=current['version'],
            token=current['release']['token'], evidence=['Recovered successful receipt'])
        self.assertEqual(result['resource']['derived_state'], 'released')

    def test_cross_task_references_are_project_scoped(self):
        self.approved(); self.register()
        second = w.dispatch('init', {'root': str(self.root), 'project': str(self.repo), 'task_id': 'second', 'title': 'Second task', 'actor': 'owner', 'authorization_source': 'Fixture second task'})['state']
        for operation, fields in [('design', {'content':'Second scope'}), ('approve', {'design_digest':w.digest('Second scope'), 'authorization_source':'Approved'}), ('run-plan', {'run_id':'shared', 'resource_id':'resource'})]:
            second = w.dispatch(operation, {'root':str(self.root), 'task_id':'second', 'actor':'owner', 'expected_version':second['version'], **fields})['state']
        self.close()
        self.assertEqual(self.resource()['eligibility']['reason'], 'live_references')
        self.assertEqual(self.resource()['run_refs'][0]['task_id'], 'second')

    def observe(self, observed_state='available', capabilities=None, stale=False):
        fields = dict(resource_id='resource', expected_resource_version=self.resource()['version'],
            observed_state=observed_state, capabilities=capabilities or {'units': 2, 'kind': 'fixture'},
            evidence=['Fixture updated availability'], valid_for_seconds=3600)
        if stale:
            original = w.make_observation
            def expired(args):
                return {**original(args), 'valid_until': '2000-01-01T00:00:00+00:00'}
            with mock.patch.object(w, 'make_observation', side_effect=expired):
                return self.op('resource-observe', **fields)
        return self.op('resource-observe', **fields)

    def test_pending_reservation_prepares_and_waits_for_actual_admission(self):
        self.integrated(); self.register(); self.observe('unavailable')
        self.op('run-plan', run_id='run', resource_id='resource', requirements={'units': 2})
        current = self.prepare(resource_id='resource', requirements={'units': 2})['run']
        self.assertEqual(current['status'], 'prepared')
        dispatched = self.op('run-dispatch', run_id='run')
        command = dispatched['runner_argv']
        directory = Path(current['directory'])
        for observation in ('pending', 'stale', 'mismatch'):
            if observation == 'stale':
                self.observe(stale=True)
            elif observation == 'mismatch':
                self.observe(capabilities={'units': 1})
            denied = subprocess.run(command, capture_output=True, timeout=30)
            self.assertNotEqual(denied.returncode, 0, observation)
            self.assertFalse((directory / 'execution.claim').exists(), observation)
            self.refresh()
            self.assertEqual(self.state['runs']['run']['status'], 'queued')
            self.error('runs_incomplete', lambda: self.close())
            self.error('release_denied', lambda: self.release(self.resource(), [sys.executable, '-c', 'pass']))
        self.observe()
        done = subprocess.run(command, capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        self.refresh(); self.op('run-reconcile', run_id='run')
        self.assertEqual(self.state['runs']['run']['status'], 'awaiting_artifacts')

    def test_dispatch_and_start_recheck_owner_seal_and_active_conflict(self):
        self.integrated(); self.register()
        self.prepare(resource_id='resource', requirements={'units': 2})
        first = self.op('run-dispatch', run_id='run')
        self.prepare(run_id='second', resource_id='resource', requirements={'units': 2})
        second = self.op('run-dispatch', run_id='second')
        # A crash after claiming but before recording start must still block capacity reuse.
        claim = Path(first['run']['directory']) / 'execution.claim'
        claim.mkdir()
        self.error('cancellation_denied', lambda: self.op('run-cancel', run_id='run', reason='Claim requires reconciliation'))
        denied = subprocess.run(second['runner_argv'], capture_output=True, timeout=30)
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse((Path(second['run']['directory']) / 'execution.claim').exists())
        claim.rmdir()  # Remove only this synthetic empty fixture claim.
        # Preserve the first actual start as an unreconciled capacity reference.
        original = w.commit_event
        _, store = w.store_dir(str(self.root))
        resource_path = w.resource_dir(store, 'resource')
        def resource_change(**changes):
            resource, previous = w.load_events(resource_path)
            resource.update(changes)
            if resource.get('release', True) is None:
                resource.pop('release')
            original(resource_path, resource, previous, 'fixture-resource-change', 'owner')
        for changes in ({'owner': 'other'}, {'owner': 'owner', 'release': {'status': 'unknown'}}):
            resource_change(**changes)
            denied = subprocess.run(first['runner_argv'], capture_output=True, timeout=30)
            self.assertNotEqual(denied.returncode, 0)
            self.assertFalse((Path(first['run']['directory']) / 'execution.claim').exists())
        resource_change(release=None)
        done = subprocess.run(first['runner_argv'], capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        # An unreconciled actual start still owns capacity after its process exits.
        denied = subprocess.run(second['runner_argv'], capture_output=True, timeout=30)
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse((Path(second['run']['directory']) / 'execution.claim').exists())
        self.refresh(); self.op('run-reconcile', run_id='run')
        self.assertEqual(subprocess.run(second['runner_argv'], capture_output=True, timeout=30).returncode, 0)

    def test_unclaimed_local_admission_failure_stays_cancellable(self):
        self.integrated(); self.register(); current = self.prepare(resource_id='resource')['run']
        original = w.run
        def lose_availability(argv, **kwargs):
            if '--run-id' in argv:
                self.refresh(); self.observe('unavailable')
            return original(argv, **kwargs)
        with mock.patch.object(w, 'run', side_effect=lose_availability):
            self.error('execution_receipt_invalid', lambda: self.op('run-execute', run_id='run'))
        self.assertEqual(self.state['runs']['run']['status'], 'queued')
        self.assertNotIn('start_validated', self.state['runs']['run'])
        self.assertFalse((Path(current['directory']) / 'execution.claim').exists())
        self.op('run-cancel', run_id='run', reason='Withdraw unclaimed admission failure')
        self.assertEqual(self.state['runs']['run']['status'], 'cancelled')
        # A concurrent cancellation before admission must also stay cancelled.
        self.observe(); self.prepare(run_id='cancelled', resource_id='resource')
        def cancel_before_start(argv, **kwargs):
            if '--run-id' in argv:
                self.refresh(); self.op('run-cancel', run_id='cancelled', reason='Cancel before actual admission')
            return original(argv, **kwargs)
        with mock.patch.object(w, 'run', side_effect=cancel_before_start):
            self.error('execution_receipt_invalid', lambda: self.op('run-execute', run_id='cancelled'))
        self.assertEqual(self.state['runs']['cancelled']['status'], 'cancelled')
