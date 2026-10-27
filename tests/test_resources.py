"""Generic resource ownership, aggregate eligibility, and release recovery."""
import json
import copy
from pathlib import Path
import sys
import subprocess
from unittest import mock
from test_workflow import Fixture, LegacyFixture, w


class ResourceTests(LegacyFixture):
    def register(self, valid_for_seconds=3600, **fields):
        return self.op('resource-register', resource_id='resource', handle='opaque-fixture-1', provided_by='user',
            can_release=True, authorization_source='User granted release permission', ownership_evidence=['Fixture owner receipt'],
            capabilities={'units': 2, 'kind': 'fixture'}, observed_state='available', evidence=['Fixture availability'],
            **({} if valid_for_seconds is None else {"valid_for_seconds": valid_for_seconds}), **fields)['resource']

    def resource(self):
        return w.dispatch('resource-status', {'root': str(self.root), 'resource_id': 'resource'})['resource']

    def close(self):
        self.op('task-complete', outcome='stopped', notes='Fixture work stopped.', evidence=['Fixture conclusion'])

    def release(self, resource, command):
        return self.op('resource-release', resource_id='resource', expected_resource_version=resource['version'],
            eligibility_key=resource['eligibility']['key'], authorization_source='Explicit fixture release', argv=command)

    def test_only_matching_capacity_references_block_release_while_scope_remains_open(self):
        self.approved(); self.register()
        resource = self.resource()
        self.assertEqual(resource['derived_state'], 'releasable')
        self.assertEqual(resource['eligibility']['reason'], 'eligible')
        self.op('run-plan', run_id='planned', resource_id='resource', requirements={'units': 1})
        self.assertEqual(self.resource()['derived_state'], 'in_use')
        self.error('release_denied', lambda: self.release(self.resource(), [sys.executable, '-c', 'pass']))
        self.op('run-cancel', run_id='planned', reason='Fixture cancelled')
        self.assertEqual(self.resource()['derived_state'], 'releasable')
        self.assertEqual(self.state['task_lifecycle']['status'], 'open')

    def test_capability_owner_and_stale_decision_guards(self):
        self.approved(); resource = self.register()
        self.error('resource_mismatch', lambda: self.op('run-plan', run_id='mismatch', resource_id='resource', requirements={'units': 3}))
        self.error('resource_owner', lambda: self.op('resource-observe', actor='other', resource_id='resource', expected_resource_version=resource['version'],
            observed_state='available', capabilities={'units': 2}, evidence=['Observation'], valid_for_seconds=60))
        self.close()
        stale = self.resource()
        self.op('task-reopen', reason='Unrelated task state does not hold idle capacity')
        self.assertEqual(stale['eligibility']['key'], self.resource()['eligibility']['key'])
        self.observe()
        self.error('stale_resource_decision', lambda: self.release(stale, [sys.executable, '-c', 'pass']))

    def test_permission_correction_is_explicit_versioned_and_separate_from_release(self):
        self.approved()
        resource = self.op('resource-register', resource_id='resource', handle='permission-fixture', provided_by='user', can_release=False,
            authorization_source='User supplied capacity without release permission', ownership_evidence=['Owner evidence'],
            capabilities={}, observed_state='available', evidence=['Current idle evidence'])['resource']
        self.assertFalse(resource['eligibility']['eligible'])
        self.assertEqual(resource['eligibility']['reason'], 'release_permission_required')
        self.error('release_permission_required', lambda: self.release(resource, [sys.executable, '-c', 'pass']))
        fields = dict(resource_id='resource', expected_resource_version=resource['version'], capabilities={},
                      observed_state='available', evidence=['Observed idle for the permission correction'])
        for partial in ({'can_release': True}, {'authorization_source': 'Actual user permission'}):
            self.error('resource_permission_source_required', lambda: self.op('resource-observe', **fields, **partial))
        self.assertEqual(self.resource()['version'], resource['version'])
        corrected = self.op('resource-observe', **fields, can_release=True,
            authorization_source='Actual user granted release permission for this handle')['resource']
        self.assertEqual(corrected['version'], resource['version'] + 1)
        self.assertEqual(corrected['permission_source'], 'Actual user granted release permission for this handle')
        self.assertNotIn('release', corrected)
        self.assertTrue(corrected['eligibility']['eligible'])
        self.error('revision_conflict', lambda: self.op('resource-observe', **fields, can_release=False,
            authorization_source='Stale permission edit'))
        released = self.release(corrected, [sys.executable, '-c', 'pass'])['resource']
        self.error('resource_sealed', lambda: self.op('resource-observe', resource_id='resource', expected_resource_version=released['version'],
            capabilities={}, observed_state='available', evidence=['Observation'], can_release=False, authorization_source='Too late to alter this action'))
        _, store = w.store_dir(str(self.root))
        record, _ = w.read_resource(store, 'resource')
        self.assertTrue(record['can_release'])
        events = [json.loads(path.read_text()) for path in (w.resource_dir(store, 'resource') / 'events').glob('*.json')]
        self.assertTrue(any(event['operation'] == 'resource-observe' for event in events))

    def test_exited_awaiting_artifacts_frees_capacity_with_external_receipt_identity(self):
        self.integrated(); self.register()
        current = self.prepare(resource_id='resource')['run']
        dispatched = self.op('run-dispatch', run_id='run')
        completed = subprocess.run(dispatched['runner_argv'], capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.refresh()
        receipt = Path(current['directory']) / 'execution-receipt.json'
        external = self.base / 'external-exit-receipt.json'
        external.write_bytes(receipt.read_bytes()); receipt.unlink()
        self.op('run-observe', run_id='run', receipt_path=str(external), evidence=['Actual external receipt location'])
        self.assertEqual(self.state['runs']['run']['status'], 'awaiting_artifacts')
        self.assertTrue(w.exited_resource_reference(self.state['runs']['run']))
        self.observe()
        resource = self.resource()
        self.assertTrue(resource['eligibility']['eligible'])
        self.assertFalse(resource['run_refs'][0]['release_blocking'])
        self.assertEqual(self.state['task_lifecycle']['status'], 'open')
        # Artifact/log acceptance remains a separate fact from the committed exit.
        (Path(current['directory']) / 'result.txt').unlink()
        external.unlink()
        self.assertTrue(self.resource()['eligibility']['eligible'])
        self.release(self.resource(), [sys.executable, '-c', 'pass'])

    def test_unverified_or_mismatched_awaiting_artifacts_remains_a_capacity_blocker(self):
        self.approved(); self.register()
        self.op('run-plan', run_id='pending', resource_id='resource')
        state = copy.deepcopy(self.state)
        current = state['runs']['pending']
        current.update(status='awaiting_artifacts', execution={'returncode': 0}, environment=None)
        _, store = w.store_dir(str(self.root))
        resource, _ = w.read_resource(store, 'resource')
        with mock.patch.object(w, 'resource_associations', return_value=[(state, 'pending', current)]):
            projected = w.resource_projection(store, resource)
        self.assertEqual(projected['eligibility']['reason'], 'live_references')
        self.assertTrue(projected['run_refs'][0]['release_blocking'])

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
        second = self.enroll({'root': str(self.root), 'project': str(self.repo), 'task_id': 'second', 'title': 'Second task', 'actor': 'owner', 'authorization_source': 'Fixture second task'})['state']
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

    def test_different_runs_share_resource_and_start_rechecks_owner_and_seal(self):
        self.integrated(); self.register()
        self.prepare(resource_id='resource', requirements={'units': 2})
        first = self.op('run-dispatch', run_id='run')
        self.prepare(run_id='second', resource_id='resource', requirements={'units': 2})
        second = self.op('run-dispatch', run_id='second')
        # A claim belongs to its own Run and does not reserve the whole resource.
        claim = Path(first['run']['directory']) / 'execution.claim'
        claim.mkdir()
        self.error('cancellation_denied', lambda: self.op('run-cancel', run_id='run', reason='Claim requires reconciliation'))
        completed = subprocess.run(second['runner_argv'], capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertTrue((Path(second['run']['directory']) / 'execution.claim').exists())
        claim.rmdir()  # Remove only this synthetic empty fixture claim.
        # Admission still checks resource ownership and any sealed release intent.
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
        # Each Run remains at most once, and every live reference blocks release.
        duplicate = subprocess.run(second['runner_argv'], capture_output=True, timeout=30)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(len(self.resource()['run_refs']), 2)
        self.refresh()
        self.error('release_denied', lambda: self.release(self.resource(), [sys.executable, '-c', 'pass']))
        self.refresh(); self.op('run-reconcile', run_id='run')
        self.op('run-reconcile', run_id='second')

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

    def test_optional_and_long_observation_validity(self):
        self.approved()
        resource = self.register(valid_for_seconds=None)
        self.assertIsNone(resource['observation']['valid_until'])
        self.assertNotIn('valid_for_seconds', resource['observation'])
        self.assertTrue(w.observation_current(resource))
        for seconds in (172800, 10 ** 100):
            resource = self.op('resource-observe', resource_id='resource', expected_resource_version=resource['version'],
                capabilities={'units': 2}, observed_state='available', evidence=['Supplied validity'],
                valid_for_seconds=seconds)['resource']
            self.assertEqual(resource['observation']['valid_for_seconds'], seconds)
            self.assertTrue(w.observation_current(resource))
        resource = self.op('resource-observe', resource_id='resource', expected_resource_version=resource['version'],
            capabilities={'units': 2}, observed_state='available', evidence=['No expiry'])['resource']
        self.assertNotIn('valid_for_seconds', resource['observation'])
        self.error('invalid_duration', lambda: self.op('resource-observe', resource_id='resource',
            expected_resource_version=resource['version'], capabilities={'units': 2}, observed_state='available',
            evidence=['Invalid validity'], valid_for_seconds=0))
        schemas = {entry['name']: entry['inputSchema'] for entry in w.command_schemas()}
        for operation in ('resource-register', 'resource-observe'):
            self.assertNotIn('valid_for_seconds', schemas[operation]['required'])
            self.assertIn('valid_for_seconds', schemas[operation]['properties'])

    def test_many_capabilities_and_long_values_preserve_requirement_fit(self):
        capabilities = {'capability_' + str(index): 'v' * 1001 for index in range(101)}
        capabilities['gpu_count'] = 1000000
        w.validate_capabilities(capabilities)
        self.approved()
        self.op('resource-register', resource_id='resource', handle='opaque-large-capabilities', provided_by='user',
            can_release=False, authorization_source='User supplied resource', ownership_evidence=['Owner receipt'],
            capabilities=capabilities, observed_state='available', evidence=['Availability'])
        self.op('run-plan', run_id='large', resource_id='resource', requirements=capabilities)
        self.error('resource_mismatch', lambda: self.op('run-plan', run_id='too-large', resource_id='resource',
            requirements={'gpu_count': 1000001}))

    def test_two_workloads_overlap_on_one_resource(self):
        self.integrated(); self.register()
        gate = self.base / 'shared-resource-gate'
        self.op('run-prepare', run_id='first', environment_id='runtime', lockfiles=['uv.lock'], resource_id='resource',
            argv=['python', '-c', 'import pathlib,sys,time; gate=pathlib.Path(sys.argv[1]); '
                  'exec("while not gate.exists(): time.sleep(0.01)")', str(gate)],
            artifacts=[], dependency_declaration='no-external-local-dependencies')
        first = self.op('run-dispatch', run_id='first')
        self.op('run-prepare', run_id='second', environment_id='runtime', lockfiles=['uv.lock'], resource_id='resource',
            argv=['python', '-c', 'import pathlib,sys; pathlib.Path(sys.argv[1]).touch()', str(gate)],
            artifacts=[], dependency_declaration='no-external-local-dependencies')
        second = self.op('run-dispatch', run_id='second')
        process = subprocess.Popen(first['runner_argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            import time
            deadline = time.monotonic() + 30
            while self.refresh()['runs']['first']['status'] != 'running':
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            self.assertIsNone(process.poll())
            completed = subprocess.run(second['runner_argv'], capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            output, errors = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, errors.decode())
        finally:
            gate.touch()
            if process.poll() is None:
                process.communicate(timeout=30)


class CurrentResourceTests(Fixture):
    """Format3 admission automatically retains future work and tracks capacity."""
    register = ResourceTests.register
    resource = ResourceTests.resource
    release = ResourceTests.release

    def active(self):
        self.tree(); self.approved()
        self.op('item-start', item_id='overall', actor='implementer')
        self.op('item-submit', item_id='overall', actor='implementer')

    def test_normal_verify_automatically_retains_full_scope_until_actual_closure(self):
        self.active(); self.register()
        self.assertFalse(self.state['resource_holds'])
        outcome = self.op('verify', item_id='overall', resource_id='resource', requirements={'units': 2},
                          argv=[sys.executable, '-c', 'print("Actual managed verification")'])
        self.assertEqual(outcome['status'], 'passed')
        hold_id = outcome['check']['retention_hold_id']
        hold = self.state['resource_holds'][hold_id]
        self.assertTrue(hold['program_owned'])
        self.assertEqual(hold['authorization_source'], self.state['enrollment'])
        projection = self.resource()
        self.assertFalse(projection['use_refs'][0]['release_blocking'])
        self.assertEqual(projection['eligibility']['reason'], 'retained_work')
        self.error('release_denied', lambda: self.release(projection, [sys.executable, '-c', 'pass']))
        again = self.op('verify', item_id='overall', resource_id='resource', requirements={'units': 2}, argv=[sys.executable, '-c', 'pass'])
        self.assertEqual(again['check']['retention_hold_id'], hold_id)
        self.op('task-complete', outcome='stopped', notes='The authorized work was stopped.', evidence=['Actual scope outcome'])
        self.assertEqual(self.state['resource_holds'][hold_id]['status'], 'resolved')
        self.assertTrue(self.resource()['eligibility']['eligible'])

    def test_persistent_choice_is_reused_and_survives_closure(self):
        self.active(); self.register()
        self.op('resource-hold', resource_id='resource', hold_id='persistent', purpose='User retained worker',
                work_refs=[{'kind':'task', 'id':'task'}], retention='persistent', authorization_source='Actual persistent user choice')
        result = self.op('verify', item_id='overall', resource_id='resource', argv=[sys.executable, '-c', 'pass'])
        self.assertEqual(result['check']['retention_hold_id'], 'persistent')
        self.assertEqual(len(self.state['resource_holds']), 1)
        self.op('task-complete', outcome='stopped', notes='Actual task stopped.', evidence=['Scope outcome'])
        self.assertEqual(self.state['resource_holds']['persistent']['status'], 'retained')
        self.op('resource-hold-resolve', resource_id='resource', hold_id='persistent', outcome='resolved',
                evidence=['Actual permission to end persistent choice'], authorization_source='User released the persistent hold')
        self.assertTrue(self.resource()['eligibility']['eligible'])

    def test_capacity_counts_reserved_checks_and_frees_only_terminal_use(self):
        self.active(); self.register()
        fields = {'kind':'verification', 'item_id':'overall', 'resource_id':'resource', 'requirements':{'units':2},
                  'argv':[sys.executable, '-c', 'pass']}
        first = self.op('check-dispatch', check_id='first', **fields)
        self.error('resource_capacity', lambda: self.op('check-dispatch', check_id='second', **fields))
        self.op('resource-register', resource_id='independent', handle='other-worker', provided_by='user', can_release=False,
                authorization_source='User supplied independent worker', ownership_evidence=['Owner'], capabilities={'units':2},
                observed_state='available', evidence=['Availability'])
        self.op('check-dispatch', check_id='independent', **{**fields, 'resource_id':'independent'})
        result = subprocess.run(first['runner_argv'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.refresh(); self.op('check-reconcile', check_id='first')
        self.op('check-dispatch', check_id='second', **fields)
        self.assertEqual(self.resource()['eligibility']['reason'], 'live_references')
        self.op('check-cancel', check_id='second', reason='Actual check cancellation')
        self.assertEqual(self.resource()['eligibility']['reason'], 'retained_work')

    def test_resource_coverage_is_retried_after_task_lock_rescan(self):
        import contextlib
        self.active(); self.register()
        self.op('check-dispatch', check_id='rescan', kind='verification', item_id='overall', resource_id='resource', argv=[sys.executable, '-c', 'pass'])
        store = self.root / '.task-workflow'; path = w.task_dir(store, 'task')
        actual_load, actual_lock = w.load_events, w.lock
        calls, acquisitions = [0], []
        def changed_after_pre_read(folder):
            state, previous = actual_load(folder)
            if folder == path:
                calls[0] += 1
                if calls[0] == 1:
                    state = copy.deepcopy(state); state['checks'] = {}
            return state, previous
        @contextlib.contextmanager
        def traced_lock(target):
            acquisitions.append(str(target))
            with actual_lock(target):
                yield
        with mock.patch.object(w, 'load_events', side_effect=changed_after_pre_read), mock.patch.object(w, 'lock', traced_lock):
            with w.mutation_locks(store, {'task_id':'task', 'check_id':'rescan'}, 'check-reconcile'):
                pass
        self.assertEqual(acquisitions, [str(path / 'write.lock'), str(w.resource_dir(store, 'resource') / 'write.lock'), str(path / 'write.lock')])

    def test_two_actual_tasks_race_for_exact_declared_capacity(self):
        from test_workflow import SCRIPT
        self.active(); self.register()
        other = self.enroll({'root':str(self.root), 'project':str(self.repo), 'task_id':'other', 'title':'Concurrent resource task', 'actor':'owner', 'authorization_source':'Independent actual request'})['state']
        def other_op(operation, **fields):
            nonlocal other
            result = w.dispatch(operation, {'root':str(self.root), 'task_id':'other', 'actor':'owner', 'expected_version':other['version'], **fields})
            other = result['state']; return result
        other_op('worktree-prepare', expected_base=self.git(self.repo, 'rev-parse', 'HEAD'), authorization_source='Independent worktree')
        other_op('design', content='Verify on declared resource')
        other_op('approve', design_digest=other['design']['digest'], authorization_source='Actual fixture approval')
        other_op('item-start', item_id='overall', actor='implementer')
        other_op('item-submit', item_id='overall', actor='implementer')
        script = 'import importlib.util,json,sys; s=importlib.util.spec_from_file_location("race",sys.argv[1]); w=importlib.util.module_from_spec(s); s.loader.exec_module(w); a=json.loads(sys.argv[2]); sys.stdin.readline()\ntry:\n r=w.dispatch("check-dispatch",a); print(json.dumps({"ok":True,"check_id":r["check_id"]}))\nexcept w.WorkflowError as e: print(json.dumps({"error":e.code}))\n'
        processes = []
        for task in (self.state, other):
            args = {'root':str(self.root), 'task_id':task['task_id'], 'actor':'owner', 'expected_version':task['version'],
                    'check_id':'race', 'kind':'verification', 'item_id':'overall', 'resource_id':'resource', 'requirements':{'units':2}, 'argv':[sys.executable, '-c', 'pass']}
            processes.append(subprocess.Popen([sys.executable, '-c', script, str(SCRIPT), json.dumps(args)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            process.stdin.write('\n'); process.stdin.flush()
        outcomes = []
        for process in processes:
            output, errors = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, errors); outcomes.append(json.loads(output))
        self.assertEqual(sum(item.get('ok') is True for item in outcomes), 1, outcomes)
        self.assertIn(next(item['error'] for item in outcomes if 'error' in item), ('locked', 'resource_capacity'))
        projection = self.resource()
        self.assertEqual(sum(use['release_blocking'] for use in projection['use_refs']), 1)
