"""Current format3 reviewed generations, frozen startup and cleanup admission."""
import copy
from pathlib import Path
import subprocess
import sys
from unittest import mock

import test_process as process_fixture
from test_workflow import Fixture, w


class GenerationTests(Fixture):
    structured = True
    discussion = process_fixture.ProcessTests.discussion
    design_content = process_fixture.ProcessTests.design_content
    designed = process_fixture.ProcessTests.designed
    plan_content = process_fixture.ProcessTests.plan_content
    planned = process_fixture.ProcessTests.planned
    approved = process_fixture.ProcessTests.approved

    def generation_integration(self, initial=False):
        if initial:
            self.approved()
        self.tree()
        previous = self.git(self.repo, 'rev-parse', 'HEAD')
        value = 1 + self.state['generation']
        (self.feature / 'code.py').write_text('VALUE = ' + str(value) + '\n')
        self.git(self.feature, 'add', '.'); self.git(self.feature, 'commit', '-m', 'Generation fixture')
        for item in ('code', 'lock', 'overall'):
            self.complete(item)
        self.op('integrate', base_branch='main', expected_base=previous,
                expected_head=self.git(self.feature, 'rev-parse', 'HEAD'), authorization_source='Approved complete generation',
                dry_run=False, commit_message='Integrate generation')
        integrated = self.git(self.repo, 'rev-parse', 'HEAD')
        self.assertEqual(self.git(self.repo, 'rev-list', '--parents', '-n', '1', integrated).split(), [integrated, previous])
        self.op('integration-verify', argv=[sys.executable, '-c', 'assert open("code.py").read() == ' + repr('VALUE = ' + str(value) + '\n')])
        return integrated

    def validate(self, run_id):
        return self.op('run-validate', run_id=run_id, check_id='startup-' + run_id)

    def test_two_complete_generations_preserve_old_run_and_current_main(self):
        first_commit = self.generation_integration(initial=True)
        self.op('experiment-create', experiment_id='study', goal='One complete goal across generations')
        first = self.prepare(run_id='first', experiment_id='study')['run']
        frozen = {str(path): path.read_bytes() for path in [Path(first['directory']) / 'snapshot.json', *Path(first['runtime']['directory']).glob('*.py'), Path(first['code']) / 'code.py']}
        self.error('generation_cleanup_required', lambda: self.op('run-dispatch', run_id='first'))
        self.error('startup_validation_required', lambda: self.op('cleanup', dry_run=False))
        self.assertEqual(self.validate('first')['status'], 'passed')
        self.op('cleanup', dry_run=False)
        first_receipt = copy.deepcopy(self.state['generation_history'][0])
        self.op('run-execute', run_id='first')
        self.op('run-accept', run_id='first', artifact_notes='Actual first generation result')
        accepted_first = copy.deepcopy(self.state['runs']['first'])
        requirements = copy.deepcopy(self.state['process']['requirements'])
        for path in (Path(first['directory']) / name for name in ('result.txt', 'execution.log', 'execution-receipt.json')):
            frozen[str(path)] = path.read_bytes()
        (self.repo / 'unrelated.txt').write_text('Current main addition\n')
        self.git(self.repo, 'add', '.'); self.git(self.repo, 'commit', '-m', 'Independent main advance')
        current_main = self.git(self.repo, 'rev-parse', 'HEAD')
        self.op('process-reenter', question={'id':'next', 'text':'Which continuation is authorized?', 'rationale':'Record the next approved code change.', 'scope':['R1'], 'important':True}, reason='Next generation requested')
        self.op('process-answer', question_id='next', answer='Continue the complete goal with the next value.', source=process_fixture.USER)
        self.op('process-playback', summary='Continue all confirmed requirements in another generation.', confirmation_source=process_fixture.USER)
        self.designed()
        plan = self.plan_content(); plan['items'][0]['steps'][0]['action'] += ' Continue in the next generation.'
        self.planned(plan)
        self.tree()
        self.assertEqual(self.state['generation'], 2)
        self.assertEqual(self.git(self.feature, 'rev-parse', 'HEAD'), current_main)
        self.assertEqual(self.state['generation_history'][0], first_receipt)
        # The helper reuses this newly reserved worktree and integrates one commit.
        self.generation_integration()
        second_fields = self.startup_fields()
        second_fields['validation_argv'][2] = second_fields['validation_argv'][2].replace('== 2', '== 3')
        second = self.prepare(run_id='second', experiment_id='study', **second_fields)['run']
        self.validate('second'); self.op('cleanup', dry_run=False)
        self.op('run-execute', run_id='second')
        self.op('run-accept', run_id='second', artifact_notes='Actual second generation result')
        self.assertEqual(len(self.state['generation_history']), 2)
        self.assertEqual(self.state['runs']['first'], accepted_first)
        self.assertEqual(self.state['process']['requirements'], requirements)
        self.assertEqual(self.state['runs']['first']['integration_commit'], first_commit)
        self.assertEqual(self.state['runs']['second']['generation'], 2)
        for path, content in frozen.items():
            self.assertEqual(Path(path).read_bytes(), content)
        self.op('experiment-complete', experiment_id='study', outcome='completed', notes='Both generations accepted.', evidence=['Both actual outputs'])
        self.op('task-complete', outcome='completed', notes='Whole goal accepted.', evidence=['Both generations and reviews'])

    def test_cleanup_interruption_recovers_without_repeating_removal(self):
        self.generation_integration(initial=True)
        self.prepare(); self.validate('run')
        original = w.commit_event
        def interrupt(path, state, previous, operation, actor):
            if operation == 'cleanup':
                raise RuntimeError('Client lost after actual Git removal')
            return original(path, state, previous, operation, actor)
        with mock.patch.object(w, 'commit_event', side_effect=interrupt):
            with self.assertRaises(RuntimeError):
                self.op('cleanup', dry_run=False)
        self.assertFalse(self.feature.exists())
        self.assertNotIn('cleaned', self.state)
        self.op('cleanup', dry_run=False)
        self.assertEqual(len(self.state['generation_history']), 1)
        self.assertTrue(self.op('cleanup', dry_run=False)['already_cleaned'])
        self.assertEqual(self.op('run-execute', run_id='run')['run']['execution']['returncode'], 0)

    def test_managed_startup_and_formal_admission_share_resource_and_scope_retention(self):
        self.generation_integration(initial=True)
        self.op('resource-register', resource_id='worker', handle='actual-managed-fixture', provided_by='user', can_release=False,
                authorization_source='User supplied worker', ownership_evidence=['Actual owner'], capabilities={'units':1},
                observed_state='available', evidence=['Actual available worker'])
        run = self.prepare(resource_id='worker', requirements={'units':1})['run']
        validation = self.validate('run')
        self.assertEqual(validation['status'], 'reserved')
        self.assertEqual(validation['check']['resource_id'], 'worker')
        self.assertEqual(validation['check']['retention_hold_id'], run['retention_hold_id'])
        result = subprocess.run(validation['runner_argv'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.refresh(); self.op('check-reconcile', check_id=validation['check_id'])
        self.op('cleanup', dry_run=False)
        self.assertEqual(self.op('run-execute', run_id='run')['run']['execution']['returncode'], 0)
        self.op('run-accept', run_id='run', artifact_notes='Actual managed result')
        resource = w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'worker'})['resource']
        self.assertTrue(all(not use['release_blocking'] for use in resource['use_refs']))
        self.assertTrue(resource['retention_refs'][0]['release_blocking'])
        self.assertFalse(resource['can_release'])
        self.op('task-complete', outcome='completed', notes='Actual entire task accepted.', evidence=['Reviews and managed output'])
        self.assertEqual(self.state['resource_holds'][run['retention_hold_id']]['status'], 'resolved')

    def test_current_formal_crash_windows_settle_without_fabricated_execution(self):
        from test_checks import actual_settlement, crash_owned_runner
        self.generation_integration(initial=True)
        self.op('resource-register', resource_id='controller', handle='isolated-formal-controller', provided_by='agent', can_release=True,
                authorization_source='Owned fixture controller permission', ownership_evidence=['Actual owned fixture controller'],
                capabilities={'units':1}, observed_state='available', evidence=['Actual controller availability'])
        phases = ('mkdir', 'owner', 'run-startup-intent', 'spawn', 'run-execution-started', 'receipt')
        counters = {}
        for phase in phases:
            counter = self.base / ('formal-count-' + phase); counters[phase] = counter
            command = 'from pathlib import Path; p=Path(' + repr(str(counter)) + '); p.write_text(p.read_text()+"x" if p.exists() else "x")'
            self.prepare(run_id=phase, resource_id='controller', requirements={'units':1}, argv=['python', '-c', command], artifacts=[])
            validation = self.validate(phase)
            self.assertEqual(subprocess.run(validation['runner_argv'], capture_output=True).returncode, 0)
            self.refresh(); self.op('check-reconcile', check_id=validation['check_id'])
        self.op('cleanup', dry_run=False)
        for phase in phases:
            with self.subTest(phase=phase):
                dispatched = self.op('run-dispatch', run_id=phase)
                pid, group = crash_owned_runner(self, dispatched, phase, kind='run')
                self.refresh(); current = self.state['runs'][phase]
                if phase not in ('mkdir', 'owner'):
                    self.assertEqual(current['execution_owner']['host'], w.lock_host_identity())
                    self.assertEqual(current['execution_owner']['uid'], w.lock_uid())
                if phase == 'owner':
                    before = (Path(current['directory']) / 'execution.claim/owner.json').read_bytes()
                    self.op('run-cancel', run_id=phase, reason='Actual proven unstarted formal claim')
                    self.assertTrue(self.state['runs'][phase]['settlement']['not_started'])
                    self.assertNotIn('start_validated', self.state['runs'][phase])
                    self.assertEqual((Path(current['directory']) / 'execution.claim/owner.json').read_bytes(), before)
                elif phase == 'receipt':
                    self.op('run-reconcile', run_id=phase)
                    self.assertEqual(self.state['runs'][phase]['status'], 'awaiting_artifacts')
                    self.op('run-cancel', run_id=phase, reason='Dispose actual exited unaccepted artifacts')
                else:
                    self.error('cancellation_denied', lambda:self.op('run-cancel', run_id=phase, reason='Unverified formal cancellation'))
                    path, _ = actual_settlement(self, current, 'run', pid, group, outcome='cancelled' if phase == 'mkdir' else 'failed')
                    self.op('run-reconcile', run_id=phase, settlement_path=str(path), evidence=['Actual formal controller terminal observation'])
                    settled = self.state['runs'][phase]
                    self.assertEqual(settled['status'], 'cancelled' if phase == 'mkdir' else 'failed')
                    self.assertNotIn('execution', settled)
                    self.assertTrue(self.op('run-reconcile', run_id=phase, settlement_path=str(path), evidence=['Same observed terminal execution'])['already_recorded'])
                    self.error('execution_conflict', lambda:self.op('run-reconcile', run_id=phase))
                self.assertNotEqual(subprocess.run(dispatched['runner_argv'], capture_output=True).returncode, 0)
                expected = 'x' if phase in ('run-execution-started', 'receipt') else ''
                self.assertEqual(counters[phase].read_text() if counters[phase].exists() else '', expected)
                projection = w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'controller'})['resource']
                # Remaining prepared Runs keep retention and release references, but do not consume admission capacity.
                self.assertFalse(next(use for use in projection['use_refs'] if use.get('run_id') == phase)['release_blocking'])
        self.op('task-complete', outcome='stopped', notes='All actual formal activity settled.', evidence=['Actual controller observations'])
        self.assertTrue(w.dispatch('resource-status', {'root':str(self.root), 'resource_id':'controller'})['resource']['eligibility']['eligible'])
