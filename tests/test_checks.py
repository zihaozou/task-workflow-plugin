"""Real durable check claims, external transport and nonblocking reconciliation."""
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest import mock

from test_workflow import Fixture, w


class CheckTests(Fixture):
    def active(self):
        self.tree(); self.approved()
        self.op('item-start', item_id='overall', actor='implementer')
        self.op('item-submit', item_id='overall', actor='implementer')

    def wait_file(self, path, process):
        deadline = time.monotonic() + 20
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), process.communicate() if process.poll() is not None else 'Worker did not reach gate')

    def reserve(self, name='external', **fields):
        return self.op('check-dispatch', check_id=name, kind='verification', item_id='overall',
                       argv=fields.pop('argv', [sys.executable, '-c', 'print("actual worker")']), **fields)

    def test_main_python_prefix_and_idempotent_submitted_argv(self):
        self.active()
        for name, executable in [('generic', 'python'), ('system', sys.executable), ('versioned', 'python3.13')]:
            command = [executable, '-c', 'import sys; assert sys.prefix == ' + repr(str(self.environment))]
            reserved = self.reserve(name=name, argv=command)
            self.assertEqual(reserved['check']['argv'][0], str(self.environment / 'bin/python'))
            self.assertTrue(self.reserve(name=name, argv=command)['already_dispatched'])
            result = subprocess.run(reserved['runner_argv'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.refresh()
            self.assertEqual(self.op('check-reconcile', check_id=name)['status'], 'passed')

    def test_external_dispatch_does_not_execute_and_reconciles_once(self):
        self.active()
        count = self.base / 'counter'
        result = self.reserve(argv=[sys.executable, '-c', 'from pathlib import Path; p=Path(' + repr(str(count)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x")'])
        self.assertFalse(count.exists())
        process = subprocess.run(result['runner_argv'], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.refresh()
        done = self.op('check-reconcile', check_id='external')
        self.assertEqual(done['status'], 'passed')
        self.assertTrue(self.op('check-reconcile', check_id='external')['already_recorded'])
        duplicate = subprocess.run(result['runner_argv'], capture_output=True)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(count.read_text(), 'x')
        self.assertIn('hostname', done['check']['receipt']['actual_host'])

    def test_long_check_allows_other_task_write_and_retains_stale_result(self):
        self.active()
        ready, release = self.base / 'ready', self.base / 'release'
        script = 'from pathlib import Path; import time; Path(' + repr(str(ready)) + ').touch(); p=Path(' + repr(str(release)) + ');\nwhile not p.exists(): time.sleep(0.01)\n'
        result = self.reserve(argv=[sys.executable, '-c', script])
        process = subprocess.Popen(result['runner_argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.wait_file(ready, process)
        other = self.enroll({'root': str(self.root), 'project': str(self.repo), 'task_id': 'other', 'title': 'Independent task', 'actor': 'owner', 'authorization_source': 'Independent fixture request'})['state']
        w.dispatch('decision', {'root': str(self.root), 'task_id': 'other', 'actor': 'owner', 'expected_version': other['version'], 'content': 'Independent update while check runs'})
        self.refresh()
        self.op('decision', content='Same-task discussion remains available')
        (self.feature / 'code.py').write_text('VALUE = 3\n')
        self.git(self.feature, 'add', '.'); self.git(self.feature, 'commit', '-m', 'Changed source during check')
        release.touch(); _, error = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 0, error)
        self.refresh()
        result = self.op('check-reconcile', check_id='external')
        self.assertEqual(result['status'], 'stale')
        self.assertFalse(self.state['items']['overall']['verifications'][-1]['passed'])

    def test_lost_result_commit_recovers_without_reexecution(self):
        self.active()
        original = w.commit_event
        def interrupt(path, state, previous, operation, actor):
            if operation == 'check-result':
                raise RuntimeError('Lost client after durable receipt')
            return original(path, state, previous, operation, actor)
        counter = self.base / 'lost-counter'
        command = 'from pathlib import Path; p=Path(' + repr(str(counter)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x")'
        with mock.patch.object(w, 'commit_event', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.op('verify', item_id='overall', check_id='lost', argv=[sys.executable, '-c', command])
        self.assertEqual(self.op('check-reconcile', check_id='lost')['status'], 'passed')
        self.assertTrue(self.op('check-reconcile', check_id='lost')['already_recorded'])
        self.assertEqual(counter.read_text(), 'x')

    def test_cancelled_reservation_cannot_start(self):
        self.active(); result = self.reserve()
        self.op('check-cancel', check_id='external', reason='User cancelled pending fixture')
        self.assertNotEqual(subprocess.run(result['runner_argv'], capture_output=True).returncode, 0)

    def test_managed_check_and_retention_are_separate(self):
        self.active()
        self.op('resource-register', resource_id='capacity', handle='owned-worker', provided_by='user', can_release=False,
                authorization_source='User machine', ownership_evidence=['Owner fixture'], capabilities={}, observed_state='available', evidence=['Available worker'], valid_for_seconds=3600)
        self.op('resource-hold', resource_id='capacity', hold_id='later', purpose='Later approved verification',
                work_refs=[{'kind': 'task', 'id': 'task'}], retention='until_work_resolved', authorization_source='User requested full delivery')
        result = self.reserve(resource_id='capacity')
        query = lambda: w.dispatch('resource-status', {'root': str(self.root), 'resource_id': 'capacity'})['resource']
        self.assertTrue(query()['use_refs'][0]['release_blocking'])
        self.assertEqual(subprocess.run(result['runner_argv'], capture_output=True).returncode, 0)
        self.refresh(); self.op('check-reconcile', check_id='external')
        capacity = query()
        self.assertFalse(capacity['use_refs'][0]['release_blocking'])
        self.assertTrue(capacity['retention_refs'][0]['release_blocking'])
        self.assertFalse(capacity['can_release'])

    def test_long_integration_check_allows_independent_and_same_task_updates(self):
        self.integrated()
        ready, release = self.base / 'integration-ready', self.base / 'integration-release'
        script = 'from pathlib import Path; import time; Path(' + repr(str(ready)) + ').touch(); p=Path(' + repr(str(release)) + ');\nwhile not p.exists(): time.sleep(0.01)\n'
        result = self.op('check-dispatch', check_id='integrated-check', kind='integration', argv=[sys.executable, '-c', script])
        process = subprocess.Popen(result['runner_argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.wait_file(ready, process)
        other = self.enroll({'root':str(self.root), 'project':str(self.repo), 'task_id':'other', 'title':'Independent update',
                            'actor':'owner', 'authorization_source':'Independent fixture request'})['state']
        w.dispatch('decision', {'root':str(self.root), 'task_id':'other', 'actor':'owner', 'expected_version':other['version'], 'content':'Actual concurrent write'})
        self.refresh(); self.op('decision', content='Same-task records remain writable during integrated check')
        (self.repo / 'later.txt').write_text('Advance main during live check')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Advance main')
        release.touch(); _, errors = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 0, errors)
        self.refresh(); done = self.op('check-reconcile', check_id='integrated-check')
        self.assertEqual(done['status'], 'stale')
        self.assertNotEqual(self.state['integration']['verification'].get('check_id'), 'integrated-check')

    def test_fabricated_receipt_without_actual_claim_is_rejected(self):
        self.active(); result = self.reserve()
        current = result['check']; directory = Path(current['directory'])
        owner = {'pid':123, 'uid':w.lock_uid(), 'host':w.lock_host_identity(), 'token':current['token'],
                 'contract_digest':current['contract_digest'], 'time':w.now()}
        claim = directory / 'execution.claim'; claim.mkdir(); w.atomic_json(claim / 'owner.json', owner)
        receipt = {'protocol':4, 'token':current['token'], 'contract_digest':current['contract_digest'],
                   'source_binding':current['source_binding'], 'returncode':0, 'actual_host':owner['host'],
                   'owned_process_identity':owner, 'started_at':owner['time'], 'finished_at':w.now()}
        for field, filename, hash_field in (('log','check.log','log_sha256'), ('stderr_log','stderr.log','stderr_sha256'), ('output','output.json','output_sha256')):
            target = directory / filename; target.write_text('Complete matching fabricated output')
            receipt.update({field:str(target), hash_field:w.sha_file(target)})
        w.atomic_json(directory / 'check-receipt.json', receipt)
        self.error('check_receipt_invalid', lambda: self.op('check-reconcile', check_id='external'))
        self.assertEqual(self.state['checks']['external']['status'], 'reserved')

    def test_existing_check_intent_rejects_changed_bound_arguments(self):
        self.active(); original = self.reserve()
        self.assertTrue(self.reserve()['already_dispatched'])
        for changed in ({'resource_id':'other'}, {'requirements':{'units':1}}, {'timeout':30}):
            self.error('check_intent_changed', lambda:self.reserve(**changed))
        self.assertEqual(self.state['checks']['external'], original['check'])
        self.error('checks_incomplete', lambda:self.op('task-complete', outcome='stopped', notes='Pending owned check', evidence=['Requested stop']))
        self.op('check-cancel', check_id='external', reason='Actual pending check cancellation')
        self.op('task-complete', outcome='stopped', notes='All owned activity settled', evidence=['Actual cancellation'])

    def test_actual_claim_and_started_process_crashes_never_replay_or_free_capacity(self):
        self.active()
        self.op('resource-register', resource_id='crash-worker', handle='owned-crash-fixture', provided_by='user', can_release=False,
                authorization_source='User supplied worker', ownership_evidence=['Owner'], capabilities={'units':1}, observed_state='available', evidence=['Availability'])
        for phase, expected in (('check-claimed', ''), ('check-started', 'x')):
            with self.subTest(phase=phase):
                counter = self.base / ('count-' + phase)
                command = 'from pathlib import Path; p=Path(' + repr(str(counter)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x")'
                reserved = self.reserve(name=phase, resource_id='crash-worker', argv=[sys.executable, '-c', command])
                current = reserved['check']
                harness = 'import os,sys; sys.path.insert(0,sys.argv[1]); import runner; actual=runner.w.commit_event\ndef interrupted(path,state,previous,operation,actor):\n value=actual(path,state,previous,operation,actor)\n if operation==sys.argv[2]: os._exit(91)\n return value\nrunner.w.commit_event=interrupted\nrunner.execute_check(sys.argv[3],sys.argv[4],sys.argv[5],sys.argv[6])\n'
                crashed = subprocess.run([sys.executable, '-c', harness, current['runtime']['directory'], phase, str(self.root), 'task', phase, current['token']], capture_output=True)
                self.assertEqual(crashed.returncode, 91, crashed.stderr)
                if expected:
                    deadline = time.monotonic() + 20
                    while not counter.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                self.assertEqual(counter.read_text() if counter.exists() else '', expected)
                self.refresh()
                self.assertTrue(self.state['checks'][phase].get('claim'))
                self.error('corrupt_state', lambda:self.op('check-reconcile', check_id=phase))
                self.assertEqual(self.state['checks'][phase]['status'], 'uncertain')
                duplicate = subprocess.run(reserved['runner_argv'], capture_output=True)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertEqual(counter.read_text() if counter.exists() else '', expected)
                resource = w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'crash-worker'})['resource']
                self.assertTrue(next(use for use in resource['use_refs'] if use.get('check_id') == phase)['release_blocking'])
                self.error('checks_incomplete', lambda:self.op('task-complete', outcome='stopped', notes='Unknown claimed execution', evidence=['Actual crash']))


def crash_owned_runner(fixture, dispatched, phase, kind='check'):
    """Exit a real pinned runner at one exact protocol boundary."""
    current = dispatched['check'] if kind == 'check' else dispatched['run']
    target = current['id'] if kind == 'check' else current['run_id']
    process_file = fixture.base / ('owned-process-' + target)
    script = '''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import runner
phase,kind=sys.argv[2:4]
actual_json,actual_commit,actual_mkdir,actual_spawn=runner.w.atomic_json,runner.w.commit_event,Path.mkdir,runner.subprocess.Popen
def atomic(path,value,*args,**kwargs):
 result=actual_json(path,value,*args,**kwargs)
 if (phase=='owner' and path.name=='owner.json' and path.parent.name=='execution.claim') or (phase=='receipt' and path.name in ('check-receipt.json','execution-receipt.json')): os._exit(92)
 return result
def commit(path,state,previous,operation,actor):
 result=actual_commit(path,state,previous,operation,actor)
 if operation==phase: os._exit(92)
 return result
def mkdir(path,*args,**kwargs):
 result=actual_mkdir(path,*args,**kwargs)
 if phase=='mkdir' and path.name=='execution.claim': os._exit(92)
 return result
def spawn(*args,**kwargs):
 process=actual_spawn(*args,**kwargs)
 if kwargs.get('start_new_session'):
  Path(sys.argv[8]).write_text(str(process.pid))
  if phase=='spawn': os._exit(92)
 return process
runner.w.atomic_json=atomic; runner.w.commit_event=commit; Path.mkdir=mkdir; runner.subprocess.Popen=spawn
if kind=='check': runner.execute_check(sys.argv[4],sys.argv[5],sys.argv[6],sys.argv[7])
else: runner.execute(sys.argv[4],sys.argv[5],sys.argv[6],sys.argv[7])
'''
    process = subprocess.Popen([sys.executable, '-c', script, current['runtime']['directory'], phase, kind,
                                str(fixture.root), 'task', target, current['token'], str(process_file)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, errors = process.communicate(timeout=30)
    fixture.assertEqual(process.returncode, 92, errors)
    return process.pid, int(process_file.read_text()) if process_file.exists() else None


def actual_settlement(fixture, current, kind, runner_pid, workload_pid=None, outcome='failed'):
    """Run a separate owned-process observer and bind its actual raw output."""
    target = current['id'] if kind == 'check' else current['run_id']
    probe = '''import json,os,sys,time
runner,group=int(sys.argv[1]),int(sys.argv[2])
def alive(call,pid):
 try: call(pid,0); return True
 except ProcessLookupError: return False
limit=time.monotonic()+20
while group and alive(os.killpg,group) and time.monotonic()<limit: time.sleep(0.01)
print(json.dumps({'runner_pid':runner,'runner_live':alive(os.kill,runner),'workload_group':group or None,'group_live':alive(os.killpg,group) if group else False}))
'''
    result = subprocess.run([sys.executable, '-c', probe, str(runner_pid), str(workload_pid or 0)], capture_output=True, check=True)
    raw = fixture.base / ('controller-' + target + '.json'); raw.write_bytes(result.stdout)
    observed = json.loads(result.stdout)
    fixture.assertFalse(observed['runner_live'], observed)
    fixture.assertFalse(observed['group_live'], observed)
    command = current['runner_argv'] if kind == 'check' else current['execution_intent']['runner_argv']
    status = w.dispatch('status', {'root':str(fixture.root), 'task_id':'task'})
    exact_target = status['settlement_targets']['checks' if kind == 'check' else 'runs'][target]
    observation = {'kind':'execution-settlement', 'target':exact_target,
        'outcome':outcome, 'observed_at':w.now(),
        'observer':{'identity':'Isolated owned-process controller', 'method':'Actual runner PID and owned process group probes at controlled protocol boundary', 'host':w.lock_host_identity()},
        'terminal':{'runner':True, 'owned_workloads':True, 'process_groups':True},
        'controller_receipt':{'path':str(raw), 'sha256':w.sha_file(raw)}, 'evidence':['Actual isolated process probe', 'Controlled pinned-runner fault boundary']}
    path = fixture.base / ('settlement-' + target + '.json'); w.atomic_json(path, observation)
    return path, observation


class CheckSettlementTests(Fixture):
    active = CheckTests.active
    reserve = CheckTests.reserve

    def register(self):
        self.op('resource-register', resource_id='settlement-worker', handle='isolated-owned-controller', provided_by='agent', can_release=True,
                authorization_source='Fixture-owned worker permission', ownership_evidence=['Owned process controller'], capabilities={'units':1},
                observed_state='available', evidence=['Actual isolated capacity'])

    def test_actual_crash_windows_settle_without_replay_and_release_only_capacity(self):
        self.active(); self.register()
        for phase in ('mkdir', 'owner', 'check-claimed', 'spawn', 'check-started', 'receipt'):
            with self.subTest(phase=phase):
                counter = self.base / ('settlement-count-' + phase)
                script = 'from pathlib import Path; p=Path(' + repr(str(counter)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x")'
                dispatched = self.reserve(name=phase, resource_id='settlement-worker', requirements={'units':1}, argv=[sys.executable, '-c', script])
                pid, group = crash_owned_runner(self, dispatched, phase)
                self.refresh(); current = self.state['checks'][phase]
                if phase == 'owner':
                    owner_bytes = (Path(current['directory']) / 'execution.claim/owner.json').read_bytes()
                    self.op('check-cancel', check_id=phase, reason='Withdraw actual proven unstarted claim')
                    self.assertTrue(self.state['checks'][phase]['settlement']['not_started'])
                    self.assertEqual((Path(current['directory']) / 'execution.claim/owner.json').read_bytes(), owner_bytes)
                elif phase == 'receipt':
                    self.assertEqual(self.op('check-reconcile', check_id=phase)['status'], 'passed')
                else:
                    self.error('cancellation_denied', lambda:self.op('check-cancel', check_id=phase, reason='Unverified cancellation'))
                    path, _ = actual_settlement(self, current, 'check', pid, group, outcome='cancelled' if phase == 'mkdir' else 'failed')
                    result = self.op('check-reconcile', check_id=phase, settlement_path=str(path), evidence=['Actual controller terminal probe'])
                    self.assertEqual(result['status'], 'cancelled' if phase == 'mkdir' else 'failed')
                    self.assertNotIn('receipt', result['check'])
                    self.assertTrue(self.op('check-reconcile', check_id=phase, settlement_path=str(path), evidence=['Same actual observation'])['already_recorded'])
                self.assertNotEqual(subprocess.run(dispatched['runner_argv'], capture_output=True).returncode, 0)
                expected = 'x' if phase in ('spawn', 'check-started', 'receipt') else ''
                self.assertEqual(counter.read_text() if counter.exists() else '', expected)
                projection = w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'settlement-worker'})['resource']
                self.assertTrue(all(not use['release_blocking'] for use in projection['use_refs']))
                self.assertEqual(projection['eligibility']['reason'], 'retained_work')
        self.op('task-complete', outcome='stopped', notes='All actual owned execution settled.', evidence=['Actual terminal controller observations'])
        self.assertTrue(w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'settlement-worker'})['resource']['eligibility']['eligible'])

    def test_settlement_rejects_wrong_incomplete_changed_and_live_evidence(self):
        import copy
        self.active(); dispatched = self.reserve(name='negative')
        pid, group = crash_owned_runner(self, dispatched, 'mkdir')
        self.refresh(); current = self.state['checks']['negative']
        path, observation = actual_settlement(self, current, 'check', pid, group)
        cases = []
        for field in ('token', 'contract_digest', 'claim_digest', 'runner_argv_digest'):
            changed = copy.deepcopy(observation); changed['target'][field] = 'mismatched'; cases.append(changed)
        changed = copy.deepcopy(observation); changed['outcome'] = 'passed'; cases.append(changed)
        changed = copy.deepcopy(observation); changed['terminal']['owned_workloads'] = False; cases.append(changed)
        changed = copy.deepcopy(observation); changed['observer']['host'] = {}; cases.append(changed)
        changed = copy.deepcopy(observation); changed['controller_receipt']['sha256'] = 'changed'; cases.append(changed)
        changed = copy.deepcopy(observation); changed['controller_receipt']['path'] = str(self.base / 'missing-actual-controller-receipt'); cases.append(changed)
        for changed in cases:
            w.atomic_json(path, changed)
            self.error('settlement_invalid', lambda:self.op('check-reconcile', check_id='negative', settlement_path=str(path), evidence=['Actual evidence required']))
        w.atomic_json(path, observation)
        self.error('execution_evidence_required', lambda:self.op('check-reconcile', check_id='negative', settlement_path=str(path), evidence=[]))
        self.error('execution_evidence_required', lambda:self.op('check-reconcile', check_id='negative', settlement_path=str(path), receipt_path=str(path), evidence=['Conflicting modes']))
        self.error('coordinator_required', lambda:self.op('check-reconcile', actor='other', check_id='negative', settlement_path=str(path), evidence=['Unauthorized observer']))
        self.op('check-reconcile', check_id='negative', settlement_path=str(path), evidence=['Actual terminal evidence'])
        self.error('execution_conflict', lambda:self.op('check-reconcile', check_id='negative'))
        # A fabricated terminal assertion cannot override an actual live local owner.
        live = self.reserve(name='live')
        directory = Path(live['check']['directory']); claim = directory / 'execution.claim'; claim.mkdir()
        owner = {'pid':__import__('os').getpid(), 'host':w.lock_host_identity(), 'uid':w.lock_uid(), 'token':live['check']['token'], 'contract_digest':live['check']['contract_digest'], 'time':w.now()}
        w.atomic_json(claim / 'owner.json', owner)
        self.error('cancellation_denied', lambda:self.op('check-cancel', check_id='live', reason='A live owner cannot be cancelled'))
        false_terminal = copy.deepcopy(observation)
        false_terminal['target'].update(id='live', token=live['check']['token'], contract_digest=live['check']['contract_digest'],
            runner_argv_digest=w.digest(live['runner_argv']), claim_digest=w.digest(w.execution_claim(live['check'])))
        w.atomic_json(path, false_terminal)
        self.error('settlement_live', lambda:self.op('check-reconcile', check_id='live', settlement_path=str(path), evidence=['Negative live-owner assertion']))
        owner['host'] = {'hostname':'unverified-foreign-host', 'identity':'unverified-foreign-boot'}
        w.atomic_json(claim / 'owner.json', owner)
        self.error('cancellation_denied', lambda:self.op('check-cancel', check_id='live', reason='A foreign owner requires actual controller evidence'))
        false_terminal['target']['claim_digest'] = w.digest(w.execution_claim(live['check']))
        false_terminal['observer']['host'] = {}
        w.atomic_json(path, false_terminal)
        self.error('settlement_invalid', lambda:self.op('check-reconcile', check_id='live', settlement_path=str(path), evidence=['Unverified foreign observer']))

    def test_changed_disk_claim_cannot_hide_a_genuine_live_recorded_owner(self):
        self.active()
        ready, release = self.base / 'admitted-ready', self.base / 'admitted-release'
        script = 'from pathlib import Path; import time; Path(' + repr(str(ready)) + ').touch(); p=Path(' + repr(str(release)) + ');\nwhile not p.exists(): time.sleep(0.01)\n'
        dispatched = self.reserve(name='admitted-live', argv=[sys.executable, '-c', script])
        process = subprocess.Popen(dispatched['runner_argv'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 20
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            self.refresh(); current = self.state['checks']['admitted-live']
            original = dict(current['claim'])
            changed = {**original, 'host':{'hostname':'foreign', 'identity':{'boot':'unverified-foreign-boot'}}, 'pid':1}
            w.atomic_json(Path(current['directory']) / 'execution.claim/owner.json', changed)
            target = w.dispatch('status', {'root':str(self.root), 'task_id':'task'})['settlement_targets']['checks']['admitted-live']
            raw = self.base / 'live-observer.json'; raw.write_text(json.dumps({'actual_runner_pid':process.pid, 'runner_live':process.poll() is None}))
            observation = {'kind':'execution-settlement', 'target':target, 'outcome':'failed', 'observed_at':w.now(),
                'observer':{'identity':'Actual isolated observer', 'method':'Actual owned runner poll', 'host':w.lock_host_identity()},
                'terminal':{'runner':True, 'owned_workloads':True, 'process_groups':True},
                'controller_receipt':{'path':str(raw), 'sha256':w.sha_file(raw)}, 'evidence':['Negative contradictory live-runner evidence']}
            path = self.base / 'false-live-settlement.json'; w.atomic_json(path, observation)
            self.error('settlement_live', lambda:self.op('check-reconcile', check_id='admitted-live', settlement_path=str(path), evidence=['Actual local owner is still live']))
            self.assertEqual(self.state['checks']['admitted-live']['status'], current['status'])
            before = self.state['version']
            self.error('coordinator_required', lambda:self.op('check-reconcile', actor='other', check_id='admitted-live', settlement_path=str(path), evidence=['Unauthorized observation']))
            self.assertEqual(self.state['version'], before)
            w.atomic_json(Path(current['directory']) / 'execution.claim/owner.json', original)
        finally:
            release.touch(); _, errors = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, errors)
        self.refresh(); self.assertEqual(self.op('check-reconcile', check_id='admitted-live')['status'], 'passed')
