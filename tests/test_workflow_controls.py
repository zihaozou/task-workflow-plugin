"""Opt-in controls bind real workers, source scopes, feasibility and native receipts."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

from test_workflow import Fixture, w
import test_process as process_fixtures


class ControlTests(Fixture):
    structured=True
    discussion=process_fixtures.ProcessTests.discussion
    design_content=process_fixtures.ProcessTests.design_content
    designed=process_fixtures.ProcessTests.designed
    plan_content=process_fixtures.ProcessTests.plan_content
    planned=process_fixtures.ProcessTests.planned

    def enroll(self, arguments):
        # Exercise the actual new default; Fixture.enroll represents historical clients.
        return w.dispatch('init', arguments)

    def v2_plan(self):
        plan=self.plan_content(); plan.update(contract_version=2,interface_contracts=[])
        for item in plan['items']:item['owner']='implementer-'+item['id']
        return plan

    def approved(self):
        self.discussion(); self.designed(); self.planned(self.v2_plan()); self.tree()

    def assign(self,name,item,role,worker):
        return self.op('worker-assign',assignment_id=name,item_id=item,role=role,worker_id=worker,authorization_source='Actual approved delegation',**({'owned_paths':['code.py','uv.lock']} if role=='explorer' else {}))

    def activate(self,name):
        return self.op('worker-activate',assignment_id=name,activation={'provider':'native-fixture','parent_session_id':'parent','child_session_id':name,'handle_id':'handle-'+name,'message_id':'message-'+name},evidence=['Actual native dispatch result'])

    def settle(self,name):
        return self.op('worker-settle',assignment_id=name,outcome='succeeded',result={'reference':'Actual terminal child result'},cleanup=True,evidence=['Actual joined activation'])

    def test_default_contract_admission_and_guarded_upgrade(self):
        self.assertEqual(w.control_version(self.state),2)
        context=w.dispatch('context',{'root':str(self.root),'task_id':'task'})
        preparation=next(entry for entry in context['workflow_controls']['next_actions'] if entry['operation']=='worktree-prepare')
        self.assertEqual(preparation['candidate']['path'],str(self.repo/'.worktrees/task'))
        self.assertFalse(preparation['eligible'])
        self.assertTrue(any(entry['code']=='actual_worktree_authority_required' for entry in preparation['missing_prerequisites']))
        self.discussion();self.designed()
        self.error('plan_contract_required',lambda:self.op('process-plan',plan=self.plan_content()))
        self.op('process-plan',plan=self.v2_plan())
        cleaned=copy.deepcopy(self.state);cleaned['cleaned']={'generation':1}
        cleaned['generation_history']=[{'generation':1,'plan_digest':cleaned['process']['plan']['digest'],'design':cleaned['design']}]
        continuation=next(entry for entry in w.workflow_controls(cleaned)['next_actions'] if entry['operation']=='worktree-prepare')
        self.assertTrue(continuation['candidate']['reuse_approved_plan'])
        cleaned['generation_history'][0]['plan_digest']='Earlier approved plan'
        revised=next(entry for entry in w.workflow_controls(cleaned)['next_actions'] if entry['operation']=='worktree-prepare')
        self.assertFalse(revised['candidate']['reuse_approved_plan'])
        old=copy.deepcopy(self.state);old.pop('workflow_control_version');self.assertEqual(w.control_version(old),1)
        original=copy.deepcopy(old['process'])
        w.apply_control('workflow-control-upgrade',{'actor':'owner','authorization_source':'Actual user upgrade'},old)
        self.assertEqual(old['process'],original)

    def test_actual_worker_wait_ordered_reviews_and_main_acceptance(self):
        self.approved()
        self.assign('implement','code','implementer','implementer-code');self.activate('implement')
        context=w.dispatch('context',{'root':str(self.root),'task_id':'task'})
        wait_action=next(entry for entry in context['workflow_controls']['next_actions'] if entry['operation']=='worker-settle')
        self.assertFalse(wait_action['eligible']);self.assertEqual(wait_action['readiness'],'requires_external_evidence')
        self.error('workers_pending',lambda:self.op('verify',item_id='code',argv=[sys.executable,'-c','pass']))
        self.op('item-start',item_id='code',actor='implementer-code')
        self.op('verify',item_id='code',actor='implementer-code',argv=[sys.executable,'-c','pass'])
        self.settle('implement');self.op('item-submit',item_id='code',actor='implementer-code',assignment_id='implement')
        self.error('ordered_review_required',lambda:self.op('item-review',item_id='code',actor='other',verdict='accept',notes='Bypass'))
        self.assign('requirements','code','requirements_reviewer','requirements-worker');self.activate('requirements');self.settle('requirements')
        self.op('item-requirements-review',item_id='code',actor='requirements-worker',assignment_id='requirements',verdict='accept',notes='Requirements checked')
        self.assign('quality','code','quality_reviewer','quality-worker');self.activate('quality');self.settle('quality')
        self.op('item-quality-review',item_id='code',actor='quality-worker',assignment_id='quality',verdict='accept',notes='Quality checked')
        self.op('item-accept',item_id='code',notes='Main accepted actual evidence')
        self.assertEqual(self.state['items']['code']['status'],'complete')
        self.assertTrue(self.op('worker-settle',assignment_id='quality',outcome='succeeded',result={'reference':'Actual terminal child result'},cleanup=True,evidence=['Actual joined activation'])['already_recorded'])

    def test_unrelated_dirty_work_and_scoped_question_preserve_independent_item(self):
        self.approved()
        self.assign('lock-worker','lock','implementer','implementer-lock');self.activate('lock-worker')
        (self.feature/'code.py').write_text('VALUE = 99\n')
        self.op('item-start',item_id='lock',actor='implementer-lock')
        self.op('verify',item_id='lock',actor='implementer-lock',argv=[sys.executable,'-c','assert open("uv.lock").read()'])
        self.op('process-reenter',question={'id':'scope','text':'Which code behavior?', 'rationale':'Code alone needs discussion','scope':['R1'],'important':True},reason='Actual scoped unknown')
        self.assertTrue(w.scoped_execution_ready(self.state,self.state['items']['lock']))
        self.assertFalse(w.scoped_execution_ready(self.state,self.state['items']['code']))
        self.assertEqual(self.state['native_goal']['requested_action']['action'],'start')
        self.error('discussion_required',lambda:self.op('verify',item_id='code',actor='implementer-code',argv=[sys.executable,'-c','pass']))

    def test_prespec_feasibility_durable_runtime_and_no_formal_bypass(self):
        self.op('process-intent',intent={'goal':'Explore actual capability','why':'Resolve compatibility','success_criteria':['Actual evidence'],'source':{'kind':'user','reference':'Actual exploration request'}})
        self.op('worktree-prepare',purpose='exploration',expected_base=self.git(self.repo,'rev-parse','HEAD'),authorization_source='Actual user exploration authority')
        self.feature=Path(self.state['worktree']['path'])
        self.assign('explore','exploration','explorer','explorer-actor');self.activate('explore')
        probe={'question':'Does the actual interpreter execute?','inputs':['Committed code.py'],'versions':{'python':sys.version.split()[0]},'criterion':'Exit zero with actual output','evidence':['Actual user request']}
        result=self.op('feas-check',actor='explorer-actor',assignment_id='explore',check_id='feas',argv=[sys.executable,'-c','print("observed")'],probe=probe,authorization_source='Actual user exploration')
        self.assertEqual(result['status'],'passed')
        runtime=Path(result['check']['runtime']['directory'])
        self.assertFalse((runtime/'process_contracts.py').exists())
        source=runtime/'workflow.py';spec=importlib.util.spec_from_file_location('isolated_fact_runtime',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.contract_call('contract_version',{'contract_version':2}),2)
        self.assertEqual(hashlib.sha256(module.PROCESS_CONTRACT_SOURCE.encode()).hexdigest(),module.PROCESS_CONTRACT_SHA256)
        module.PROCESS_CONTRACT_SOURCE+='\n# changed\n'
        with self.assertRaises(module.WorkflowError) as changed:
            module.contract_call('contract_version',{})
        self.assertEqual(changed.exception.code,'contract_runtime_changed')
        before=result['check']['contract_digest'];again=self.op('feas-check',actor='explorer-actor',assignment_id='explore',check_id='feas',argv=[sys.executable,'-c','print("observed")'],probe=probe,authorization_source='Actual user exploration')
        self.assertTrue(again['already_dispatched']);self.assertEqual(before,again['check']['contract_digest'])
        self.error('workers_pending',lambda:self.op('feas-check',assignment_id='explore',check_id='pm-bypass',argv=[sys.executable,'-c','pass'],probe=probe,authorization_source='Same probe'))
        failed=self.op('feas-check',actor='explorer-actor',assignment_id='explore',check_id='refuted',argv=[sys.executable,'-c','raise SystemExit(2)'],probe=probe,authorization_source='Actual alternative probe')
        self.assertEqual(failed['status'],'failed')
        self.settle('explore')
        self.error('approval_required',lambda:self.prepare())
        self.discussion()
        design=self.design_content();design['feasibility_checks']=[{'check_id':'refuted','requirement_ids':['R1']}]
        self.error('feasibility_required',lambda:self.op('process-design',design=design))
        design['feasibility_checks']=[{'check_id':'feas','requirement_ids':['R1']}]
        self.designed(design)
        self.assertEqual(self.state['process']['design']['content']['feasibility_checks'][0]['check_id'],'feas')
        self.planned(self.v2_plan())
        output=Path(result['check']['receipt']['output']);original=output.read_bytes();output.write_text('Changed actual probe output')
        self.assign('independent','lock','implementer','implementer-lock');self.activate('independent')
        self.op('item-start',item_id='lock',actor='implementer-lock')
        self.error('feasibility_evidence_changed',lambda:w.require_approved(self.state,self.state['items']['code']))
        output.write_bytes(original)

    def test_native_goal_request_does_not_claim_native_creation(self):
        self.op('goal-request',request='Create a goal if the host exposes it',authorization_source='Actual user request',evidence=['Original request'])
        context=w.dispatch('context',{'root':str(self.root),'task_id':'task'})
        self.assertEqual(context['workflow_controls']['goal']['status'],'requested')
        self.assertNotIn('receipt',context['workflow_controls']['goal'])
        self.op('goal-observe',receipt={'capability':'actual-native-tool','native_goal_id':'actual-id','result':{'status':'created'}},evidence=['Actual native tool return'])
        self.assertEqual(self.state['native_goal']['status'],'observed')

    def finish_review(self,item):
        for suffix,role,operation in [('requirements','requirements_reviewer','item-requirements-review'),('quality','quality_reviewer','item-quality-review')]:
            name=item+'-'+suffix;actor=name+'-actor'
            self.assign(name,item,role,actor);self.activate(name);self.settle(name)
            self.op(operation,item_id=item,actor=actor,assignment_id=name,verdict='accept',notes='Actual independent review')
        self.op('item-accept',item_id=item,notes='Actual main acceptance')

    def test_composition_requires_exact_producer_check_and_invalidates_on_change(self):
        self.discussion();self.designed();plan=self.v2_plan()
        plan['items'][1]['dependencies']=[{'item_id':'code','kind':'integration'}]
        self.planned(plan);self.tree()
        self.assign('consumer','lock','implementer','implementer-lock');self.activate('consumer')
        self.op('item-start',item_id='lock',actor='implementer-lock')
        self.assign('producer','code','implementer','implementer-code');self.activate('producer')
        self.op('item-start',item_id='code',actor='implementer-code')
        self.op('verify',item_id='code',actor='implementer-code',argv=[sys.executable,'-c','pass'])
        self.settle('producer');self.op('item-submit',item_id='code',actor='implementer-code',assignment_id='producer')
        self.finish_review('code')
        fresh=w.dispatch('context',{'root':str(self.root),'task_id':'task'})
        self.assertFalse(any(entry.get('item_id')=='code' and entry['operation']=='item-start' for entry in fresh['workflow_controls']['next_actions']))
        self.op('verify',item_id='lock',actor='implementer-lock',argv=[sys.executable,'-c','pass'])
        self.error('dependency_incomplete',lambda:w.require_item_dependencies(self.state,'lock',phase='submission'))
        self.op('verify',item_id='lock',actor='implementer-lock',composition_for=['code'],argv=[sys.executable,'-c','assert open("code.py").read() and open("uv.lock").read()'])
        w.require_item_dependencies(self.state,'lock',phase='submission')
        self.error('unknown_reference',lambda:self.op('verify',item_id='lock',actor='implementer-lock',composition_for=['lock'],argv=[sys.executable,'-c','pass']))
        (self.feature/'code.py').write_text('VALUE = 3\n');self.git(self.feature,'add','code.py');self.git(self.feature,'commit','-m','Actual producer change')
        self.refresh()
        self.error('dependency_incomplete',lambda:w.require_item_dependencies(self.state,'lock',phase='submission'))
        stale=w.dispatch('context',{'root':str(self.root),'task_id':'task'})
        self.assertTrue(any(entry.get('item_id')=='code' and entry['operation']=='item-start' for entry in stale['workflow_controls']['next_actions']))

    def test_stale_reviewer_settlement_retains_original_source(self):
        self.approved();self.assign('impl','code','implementer','implementer-code');self.activate('impl')
        self.op('item-start',item_id='code',actor='implementer-code')
        self.op('verify',item_id='code',actor='implementer-code',argv=[sys.executable,'-c','pass'])
        self.settle('impl');self.op('item-submit',item_id='code',actor='implementer-code',assignment_id='impl')
        self.assign('review','code','requirements_reviewer','requirements-worker');self.activate('review')
        original=copy.deepcopy(self.state['workers']['review']['binding']);original_code=(self.feature/'code.py').read_bytes()
        (self.feature/'code.py').write_text('VALUE = 4\n');self.git(self.feature,'add','code.py');self.git(self.feature,'commit','-m','Changed during actual review')
        self.settle('review')
        self.assertEqual(self.state['workers']['review']['binding'],original)
        self.assertFalse(self.state['workers']['review']['settlement']['source_current'])
        self.error('worker_evidence_required',lambda:self.op('item-requirements-review',item_id='code',actor='requirements-worker',assignment_id='review',verdict='accept',notes='Stale review'))
        (self.feature/'code.py').write_bytes(original_code);self.git(self.feature,'add','code.py');self.git(self.feature,'commit','-m','Restore original checked source')
        self.error('worker_evidence_required',lambda:self.op('item-requirements-review',item_id='code',actor='requirements-worker',assignment_id='review',verdict='accept',notes='Previously stale result remains invalid'))

    def test_global_later_question_revokes_scoped_allowance_and_user_pause_is_explicit(self):
        self.approved()
        self.op('process-reenter',question={'id':'first','text':'Code question','rationale':'Code fact','scope':['R1'],'important':True},reason='Agent-discovered unknown')
        self.assertEqual(self.state['native_goal']['requested_action']['action'],'start')
        self.assertTrue(w.scoped_execution_ready(self.state,self.state['items']['lock']))
        self.op('process-answer',question_id='first',answer='Keep behavior',source={'kind':'user','reference':'Actual answer'})
        self.op('process-question',question={'id':'global','text':'Global question','rationale':'All work affected','scope':[],'important':True})
        self.assertFalse(w.scoped_execution_ready(self.state,self.state['items']['lock']))
        self.op('process-answer',question_id='global',answer='Pause for user replan',source={'kind':'user','reference':'Actual replan'})
        self.op('process-reenter',question={'id':'replan','text':'Which revised scope?','rationale':'User replan','scope':['R1'],'important':True},reason='Actual user replan',goal_pause_authorization='Actual user asked to pause and replan')
        self.assertEqual(self.state['native_goal']['requested_action']['action'],'pause')

    def test_plan_two_scoped_check_reuse_is_independent_of_control_version(self):
        self.approved();self.assign('impl','code','implementer','implementer-code');self.activate('impl')
        self.op('item-start',item_id='code',actor='implementer-code')
        result=self.op('verify',item_id='code',actor='implementer-code',argv=[sys.executable,'-c','assert open("code.py").read()'])
        (self.feature/'unrelated.txt').write_text('Independent source commit\n')
        self.git(self.feature,'add','unrelated.txt');self.git(self.feature,'commit','-m','Independent change outside checked scope')
        state=copy.deepcopy(self.state);state['workflow_control_version']=1
        self.assertTrue(w.check_current(state,result['check']))
        (self.feature/'code.py').write_text('VALUE = 7\n');self.git(self.feature,'add','code.py');self.git(self.feature,'commit','-m','Actual checked source change')
        self.assertFalse(w.check_current(state,result['check']))

    def test_failed_dirty_and_cancelled_reentry_workers_settle_without_losing_work(self):
        self.approved()
        for item in ('code','lock'):
            self.assign(item+'-work',item,'implementer','implementer-'+item);self.activate(item+'-work')
            self.op('item-start',item_id=item,actor='implementer-'+item)
        original={item:copy.deepcopy(self.state['workers'][item+'-work']['binding']) for item in ('code','lock')}
        dirty='VALUE = "unfinished actual work"\n';(self.feature/'code.py').write_text(dirty)
        self.op('worker-settle',assignment_id='code-work',outcome='failed',result={'error':'Actual child failed with uncommitted work'},cleanup=True,evidence=['Actual terminal result and joined child'])
        self.assertFalse(self.state['workers']['code-work']['settlement']['source_current'])
        self.assertEqual(self.state['workers']['code-work']['binding'],original['code'])
        self.op('process-reenter',question={'id':'user-replan','text':'Which lock behavior?', 'rationale':'Actual user replan','scope':['R2'],'important':True},reason='Actual user requested revised behavior')
        self.op('worker-settle',assignment_id='lock-work',outcome='cancelled',result={'reference':'Actual cancelled and joined child'},cleanup=True,evidence=['Actual cancellation cleanup'])
        self.assertFalse(self.state['workers']['lock-work']['settlement']['source_current'])
        self.assertEqual(self.state['workers']['lock-work']['binding'],original['lock'])
        self.assertEqual((self.feature/'code.py').read_text(),dirty)
        self.assertFalse(w.pending_workers(self.state))

    def test_actual_reapproved_metadata_preserves_items_and_semantic_change_resets_dependents(self):
        self.discussion();self.designed();plan=self.v2_plan()
        plan['items'][1]['dependencies']=[{'item_id':'code','kind':'implementation'}]
        self.planned(plan);self.tree()
        for item in ('code','lock'):
            name=item+'-impl';actor='implementer-'+item
            self.assign(name,item,'implementer',actor);self.activate(name)
            self.op('item-start',item_id=item,actor=actor)
            self.op('verify',item_id=item,actor=actor,argv=[sys.executable,'-c','pass'])
            self.settle(name);self.op('item-submit',item_id=item,actor=actor,assignment_id=name)
            self.finish_review(item)
        accepted={item:copy.deepcopy(self.state['items'][item]['acceptance']) for item in ('code','lock')}
        def reapprove(question_id,updated_plan):
            self.op('process-reenter',question={'id':question_id,'text':'Confirm the reviewed revision?', 'rationale':'Actual user requested plan revision','scope':['R1'],'important':True},reason='Actual approved revision requested')
            self.op('process-answer',question_id=question_id,answer='Approve the described revision while preserving all requirements.',source={'kind':'user','reference':'Actual revision '+question_id})
            self.op('process-playback',summary='All requirements remain; review the requested revision.',confirmation_source={'kind':'user','reference':'Actual playback '+question_id})
            self.designed();self.planned(updated_plan)
        metadata=copy.deepcopy(plan);metadata['review_focus']='Reworded review heading'
        for entry in metadata['items']:entry['title']='Readable revised '+entry['id']+' title'
        reapprove('metadata',metadata)
        for item in ('code','lock'):
            self.assertEqual(self.state['items'][item]['status'],'complete')
            self.assertEqual(self.state['items'][item]['acceptance'],accepted[item])
            self.assertEqual(self.state['items'][item]['title'],'Readable revised '+item+' title')
        changed=copy.deepcopy(metadata);changed['items'][0]['verification'][0]['method']='Inspect the new explicit executable acceptance condition.'
        reapprove('check-change',changed)
        self.assertEqual(self.state['items']['code']['status'],'pending')
        self.assertEqual(self.state['items']['lock']['status'],'pending')
        self.assertTrue(any(entry['id']=='code' and entry['item']['acceptance']==accepted['code'] for entry in self.state['item_history']))
