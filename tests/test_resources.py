"""Generic resource ownership, aggregate eligibility, and release recovery."""
import json
from pathlib import Path
import sys
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
