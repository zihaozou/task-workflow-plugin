"""Independent Run startup after source cleanup and explicitly authorized routine fixes."""
import copy
from pathlib import Path
import subprocess
import sys

import test_generations as generations
from test_workflow import Fixture, w


class SameSourceRunTests(Fixture):
    def cleaned_source(self, run_id='first'):
        self.integrated()
        current=self.prepare(run_id=run_id)['run']
        self.assertEqual(current['lifecycle_contract'],2)
        self.assertEqual(self.op('run-validate',run_id=run_id,check_id='startup-'+run_id)['status'],'passed')
        self.op('cleanup',dry_run=False)
        return current

    def test_later_run_validates_and_dispatches_without_reopening_worktree(self):
        first=self.cleaned_source()
        receipt=w.canonical(self.state['generation_history'])
        immutable={str(path):path.read_bytes() for path in [Path(first['directory']) / 'snapshot.json',*Path(first['runtime']['directory']).glob('*.py')]}
        later=self.prepare(run_id='later')['run']
        self.assertFalse(Path(self.state['worktree']['path']).exists())
        self.assertEqual(later['code'],first['code'])
        self.assertNotIn('later',self.state['generation_history'][0]['runs'])
        self.error('generation_cleanup_required',lambda:self.op('run-dispatch',run_id='later'))
        self.op('run-validate',run_id='later',check_id='startup-later')
        result=self.op('run-execute',run_id='later')['run']
        self.assertEqual(result['execution']['returncode'],0)
        self.assertEqual(self.state['runs']['first']['status'],'prepared')
        self.assertEqual(self.op('run-execute',run_id='first')['run']['execution']['returncode'],0)
        self.assertEqual(w.canonical(self.state['generation_history']),receipt)
        for path,value in immutable.items():self.assertEqual(Path(path).read_bytes(),value)

    def test_later_run_with_failed_actual_startup_cannot_dispatch(self):
        self.cleaned_source()
        current=self.prepare(run_id='failed-startup',validation_argv=['python','-c','raise RuntimeError("Actual fixture startup failure")'])['run']
        result=self.op('run-validate',run_id='failed-startup',check_id='failed-validation')
        self.assertEqual(result['status'],'failed')
        self.error('generation_cleanup_required',lambda:self.op('run-dispatch',run_id='failed-startup'))
        self.assertFalse((Path(current['directory']) / 'execution.claim').exists())
        self.op('run-cancel',run_id='failed-startup',reason='Failed fixture startup is terminal')

    def test_original_verification_identity_survives_a_later_successful_check(self):
        self.integrated()
        first=self.prepare()['run']
        original=copy.deepcopy(first['integration_verification'])
        self.op('integration-verify',check_id='verify-again',argv=[sys.executable,'-c','pass'])
        self.assertNotEqual(original,self.state['integration']['verification'])
        self.op('run-validate',run_id='run',check_id='startup')
        self.op('cleanup',dry_run=False)
        self.assertEqual(self.state['runs']['run']['integration_verification'],original)
        w.require_generation_dispatch(self.state,self.state['runs']['run'])
        self.assertEqual(self.op('run-execute',run_id='run')['run']['execution']['returncode'],0)

    def test_source_startup_and_unique_cleanup_guards(self):
        self.cleaned_source()
        current=self.state['runs']['first']
        cases={
            'duplicate cleanup':lambda state:state['generation_history'].append(copy.deepcopy(state['generation_history'][0])),
            'missing source binding':lambda state:state['runs']['first'].pop('source_generation'),
            'different source tree':lambda state:state['generation_history'][0].update(source_tree='unrelated'),
            'different integration token':lambda state:state['generation_history'][0]['integration'].update(token='unrelated'),
            'failed startup':lambda state:state['checks']['startup-first'].update(status='failed'),
            'wrong startup source':lambda state:state['checks']['startup-first']['source_binding'].update(contract_digest='unrelated'),
            'wrong startup Run':lambda state:state['checks']['startup-first']['selectors'].update(run_id='unrelated'),
            'wrong startup bound Run':lambda state:state['checks']['startup-first']['source_binding'].update(run_id='unrelated'),
            'wrong verification source':lambda state:state['checks'][current['integration_verification']['check_id']]['source_binding'].update(commit='unrelated'),
        }
        for label,mutate in cases.items():
            with self.subTest(label=label):
                state=copy.deepcopy(self.state);mutate(state)
                self.error('generation_cleanup_required',lambda:w.require_generation_dispatch(state,state['runs']['first']))
        changed=copy.deepcopy(current);changed['source_generation']['source_tree']='unrelated'
        self.assertNotEqual(w.execution_argv_digest(changed),w.execution_argv_digest(current))

    def test_legacy_contract_digest_and_run_membership_are_unchanged(self):
        self.cleaned_source()
        state=copy.deepcopy(self.state);current=state['runs']['first'];current['lifecycle_contract']=1
        expected=w.digest({'generation':current['generation'],'integration_commit':current['integration_commit'],
            'lifecycle_contract':1,'inputs':{key:current[key] for key in ('snapshot_contract','argv','validation_argv','snapshot_scope','code_store','startup_inputs','environment','manifest_digest')}})
        self.assertEqual(w.execution_argv_digest(current),expected)
        current['startup_validation']['contract_digest']=expected
        state['generation_history'][0]['runs']['first']={'contract_digest':expected,'startup_validation':copy.deepcopy(current['startup_validation'])}
        w.require_generation_dispatch(state,current)
        state['generation_history'][0]['runs'].pop('first')
        self.error('generation_cleanup_required',lambda:w.require_generation_dispatch(state,current))
        current['lifecycle_contract']=3
        self.error('generation_cleanup_required',lambda:w.require_generation_dispatch(state,current))

    def test_contract_two_claim_can_be_cancelled_and_unknown_contract_rejected(self):
        from test_checks import crash_owned_runner
        self.cleaned_source()
        dispatched=self.op('run-dispatch',run_id='first')
        crash_owned_runner(self,dispatched,'owner',kind='run')
        self.refresh()
        self.assertIn('first',w.execution_settlement_targets(self.state)['runs'])
        unsupported=copy.deepcopy(self.state['runs']['first']);unsupported['lifecycle_contract']=3
        self.error('settlement_unsupported',lambda:w.settlement_runtime(self.state,unsupported,'run'))
        result=self.op('run-cancel',run_id='first',reason='Actual dead pre-admission fixture runner')
        self.assertEqual(result['run']['status'],'cancelled')
        self.assertEqual(result['run']['settlement']['kind'],'proven_unstarted')


class ApprovedPlanContinuationTests(Fixture):
    structured=True
    discussion=generations.GenerationTests.discussion
    design_content=generations.GenerationTests.design_content
    designed=generations.GenerationTests.designed
    plan_content=generations.GenerationTests.plan_content
    planned=generations.GenerationTests.planned
    approved=generations.GenerationTests.approved
    generation_integration=generations.GenerationTests.generation_integration
    validate=generations.GenerationTests.validate

    def cleaned_generation(self, run=False):
        self.generation_integration(initial=True)
        if run:
            self.prepare(run_id='older');self.validate('older')
        self.op('cleanup',dry_run=False)

    def continuation(self,**fields):
        return self.op('worktree-prepare',expected_base=self.git(self.repo,'rev-parse','HEAD'),
            authorization_source='Actual user authorization for the unchanged approved routine fix',
            reuse_approved_plan=True,**fields)

    def test_same_plan_reopens_from_current_main_and_preserves_history(self):
        self.cleaned_generation()
        previous=w.canonical(self.state['generation_history'])
        approved={key:copy.deepcopy(self.state['process'][key]) for key in ('design','design_approval','plan','plan_approval')}
        self.error('new_plan_required',lambda:self.op('worktree-prepare',expected_base=self.git(self.repo,'rev-parse','HEAD'),authorization_source='No explicit continuation flag'))
        self.error('invalid_text',lambda:self.op('worktree-prepare',expected_base=self.git(self.repo,'rev-parse','HEAD'),authorization_source='',reuse_approved_plan=True))
        (self.repo / 'unrelated.txt').write_text('Current base advance\n')
        self.git(self.repo,'add','.');self.git(self.repo,'commit','-m','Independent base advance')
        base=self.git(self.repo,'rev-parse','HEAD')
        result=self.continuation()
        self.assertEqual(self.state['generation'],2)
        self.assertEqual(self.git(Path(result['worktree']['path']),'rev-parse','HEAD'),base)
        self.assertEqual(self.state['integration'],{})
        self.assertTrue(all(item['status']=='pending' for item in self.state['items'].values()))
        self.assertEqual(w.canonical(self.state['generation_history']),previous)
        for key,value in approved.items():self.assertEqual(self.state['process'][key],value)
        self.assertEqual(self.state['generation_continuations'][-1]['plan_digest'],approved['plan']['digest'])
        version=self.state['version'];self.continuation()
        self.assertEqual(self.state['generation'],2)
        self.assertEqual(self.state['version'],version)

    def test_scope_approval_and_active_check_guards(self):
        self.cleaned_generation()
        args={'actor':'owner','authorization_source':'Actual approved routine fix','reuse_approved_plan':True}
        self.error('revision_conflict',lambda:w.prepare_generation({**args,'expected_generation':self.state['generation']+1},copy.deepcopy(self.state)))
        for field in ('plan_digest','design'):
            with self.subTest(field=field):
                state=copy.deepcopy(self.state)
                if field=='design':state['generation_history'][0]['design']['digest']='different'
                else:state['generation_history'][0][field]='different'
                self.error('approved_plan_mismatch',lambda:w.prepare_generation(args,state))
        active=copy.deepcopy(self.state);next(iter(active['checks'].values()))['status']='running'
        self.error('active_check',lambda:w.prepare_generation(args,active))
        unapproved=copy.deepcopy(self.state);unapproved['process']['stage']='design_confirmation'
        self.error('discussion_required',lambda:w.prepare_generation(args,unapproved))
        schema=next(tool for tool in w.command_schemas() if tool['name']=='worktree-prepare')['inputSchema']
        self.assertEqual(schema['properties']['reuse_approved_plan']['type'],'boolean')

    def test_older_independent_queued_or_running_run_does_not_block_continuation(self):
        self.cleaned_generation(run=True)
        self.op('run-dispatch',run_id='older')
        previous=copy.deepcopy(self.state['runs']['older'])
        running=copy.deepcopy(self.state);running['runs']['older']['status']='running'
        w.prepare_generation({'actor':'owner','authorization_source':'Actual same-Plan fix','reuse_approved_plan':True},running)
        self.assertEqual(running['generation'],2)
        self.continuation()
        self.assertEqual(self.state['runs']['older'],previous)
        w.require_generation_dispatch(self.state,self.state['runs']['older'])
        self.op('run-cancel',run_id='older',reason='Fixture complete; no external workload was launched')
