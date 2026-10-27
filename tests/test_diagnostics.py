"""Precise rejected-call diagnostics preserve state, authority and guard behavior."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

from test_workflow import Fixture, SCRIPT, w
import test_process as fixtures

USER = {'kind': 'user', 'reference': 'Fixture actual request'}
AGENT = {'kind': 'agent', 'reference': 'Fixture implementation proposal'}


class DiagnosticTests(Fixture):
    structured = True
    discussion = fixtures.ProcessTests.discussion
    design_content = fixtures.ProcessTests.design_content
    designed = fixtures.ProcessTests.designed
    plan_content = fixtures.ProcessTests.plan_content

    def reject(self, operation, expected_code, expected_path, **fields):
        before = copy.deepcopy(self.state)
        path = self.root / '.task-workflow/tasks/task'
        event_files = {entry.name: entry.read_bytes() for entry in (path / 'events').iterdir()}
        with self.assertRaises(w.WorkflowError) as caught:
            self.op(operation, **fields)
        error = caught.exception
        self.assertEqual(error.code, expected_code)
        self.assertEqual(error.details['path'], expected_path)
        self.assertEqual(self.state, before)
        self.assertEqual({entry.name:entry.read_bytes() for entry in (path / 'events').iterdir()},event_files)
        return error

    def arguments(self, **fields):
        return {'root':str(self.root),'task_id':'task','actor':'owner','expected_version':self.state['version'],**fields}

    def transport(self):
        spec = importlib.util.spec_from_file_location('diagnostic_mcp',SCRIPT.parent / 'mcp_server.py')
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'workflow':w}):
            spec.loader.exec_module(module)
        server = module.Server(); server.initialized = True
        return server

    def test_top_level_confirmation_source_has_nested_allowed_fields_without_source_copy(self):
        self.discussion()
        decision = {'id':'d-one','title':'Keep requested scope','choice':'Use the recorded scope','rationale':'Actual request confirms the scope',
            'scope':['R1'],'status':'confirmed','source':USER}
        error = self.reject('process-decision','invalid_arguments','arguments.confirmation_source',decision=decision,confirmation_source=USER)
        self.assertEqual(error.message,'Arguments contain unknown fields or omit required fields; use schema.')
        self.assertEqual(error.details['unknown_fields'],['confirmation_source'])
        self.assertIn('decision',error.details['allowed_fields'])
        self.assertNotIn(USER['reference'],json.dumps(error.details))
        self.op('process-decision',decision=decision)
        self.assertEqual(self.state['process']['decisions'][-1]['source'],USER)

    def test_nested_unknown_fields_and_types_show_precise_paths_before_correct_call(self):
        self.discussion(); self.designed()
        bad = self.plan_content(); bad.update(id='invented',acceptance=['wrong level'])
        error = self.reject('process-plan','invalid_process','arguments.plan.acceptance',plan=bad)
        self.assertEqual(error.details['unknown_fields'],['acceptance','id'])
        self.assertEqual(error.details['allowed_fields'],['dependencies','items','review_focus','shared_requirements'])
        bad = self.plan_content(); bad['items'][0]['steps'] = ['Generic phase']
        error = self.reject('process-plan','invalid_process','arguments.plan.items[0].steps[0]',plan=bad)
        self.assertEqual(error.details['expected_type'],'object')
        bad = self.plan_content(); bad['items'][0]['verification'][0]['kind']='unknown'
        error = self.reject('process-plan','invalid_process','arguments.plan.items[0].verification[0].kind',plan=bad)
        self.assertEqual(error.details['allowed_values'],['command','inspection'])
        bad = self.plan_content(); bad['items'][0]['deliverables']='single string'
        error = self.reject('process-plan','invalid_process','arguments.plan.items[0].deliverables',plan=bad)
        self.assertEqual(error.details['expected_type'],'nonempty array')
        self.op('process-plan',plan=self.plan_content())
        self.assertEqual(self.state['process']['stage'],'plan_confirmation')

    def test_exact_reference_names_are_derived_from_each_current_plan_item(self):
        self.discussion(); self.designed()
        plan = self.plan_content()
        plan['items'][0]['interfaces']=['lookup query path']
        plan['items'][0]['steps'][0]['interfaces']=['lookup']
        error = self.reject('process-plan','unknown_reference','arguments.plan.items[0].steps[0].interfaces',plan=plan)
        self.assertEqual(error.details['value'],['lookup'])
        self.assertEqual(error.details['allowed_reference_ids'],['lookup query path'])
        self.assertEqual(error.details['unknown_references'],['lookup'])
        plan['items'][0]['interfaces']=['different interface']
        error = self.reject('process-plan','unknown_reference','arguments.plan.items[0].steps[0].interfaces',plan=plan)
        self.assertEqual(error.details['allowed_reference_ids'],['different interface'])
        plan['items'][0]['steps'][0]['interfaces']=['different interface']
        self.op('process-plan',plan=plan)

    def test_scoped_reference_and_coverage_failures_name_actual_missing_ids(self):
        self.discussion(); self.designed()
        cases = [
            ('arguments.plan.items[0].component_ids',lambda p:p['items'][0].update(component_ids=['unknown']),['code','lock']),
            ('arguments.plan.items[0].verification[0].requirement_ids',lambda p:p['items'][0]['verification'][0].update(requirement_ids=['R2']),['R1']),
            ('arguments.plan.items[0].steps[0].verification_ids',lambda p:p['items'][0]['steps'][0].update(verification_ids=['unknown']),['scope-check']),
            ('arguments.plan.items[1].dependencies',lambda p:p['items'][1].update(dependencies=['unknown']),['code','lock'])]
        for path, mutate, allowed in cases:
            plan=self.plan_content(); mutate(plan)
            error=self.reject('process-plan','unknown_reference',path,plan=plan)
            self.assertEqual(error.details['allowed_reference_ids'],allowed)
        plan=self.plan_content();plan['items']=plan['items'][:1]
        error=self.reject('process-plan','requirement_coverage','arguments.plan.items',plan=plan)
        self.assertEqual(error.details['missing_coverage'],['R2'])
        plan=self.plan_content();plan['items'][0]['interfaces']=['lookup query path']
        error=self.reject('process-plan','interface_coverage','arguments.plan.items[0].steps',plan=plan)
        self.assertEqual(error.details['missing_coverage'],['lookup query path'])
        self.op('process-plan',plan=self.plan_content())

    def test_cli_and_mcp_preserve_codes_with_actionable_details_and_no_mutation(self):
        self.discussion();self.designed()
        before=copy.deepcopy(self.state)
        bad=self.plan_content();bad['items'][0]['steps'][0]['files']=['missing.py']
        arguments=self.arguments(plan=bad)
        cli=subprocess.run([sys.executable,str(SCRIPT),'process-plan','--root',str(self.root),'--json-args','-'],
            input=json.dumps({key:value for key,value in arguments.items() if key!='root'}),text=True,capture_output=True)
        self.assertEqual(cli.returncode,2,cli.stderr)
        cli_error=json.loads(cli.stdout)['error']
        server=self.transport()
        response=server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'process-plan','arguments':arguments}})
        self.assertTrue(response['result']['isError'])
        mcp_error=json.loads(response['result']['content'][0]['text'])['error']
        self.assertEqual(mcp_error,cli_error)
        self.assertEqual(cli_error['details']['path'],'arguments.plan.items[0].steps[0].files')
        arguments=self.arguments(plan={**self.plan_content(),'extra':{'reference':'Private source must not be duplicated'}})
        response=server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'process-plan','arguments':arguments}})
        self.assertEqual(response['error']['code'],-32602)
        self.assertEqual(response['error']['data']['path'],'arguments.plan.extra')
        self.assertNotIn('Private source',json.dumps(response))
        self.assertEqual(self.refresh(),before)
        self.op('process-plan',plan=self.plan_content())

    def test_worktree_base_conflict_only_reports_observed_commits(self):
        before=copy.deepcopy(self.state)
        actual=self.git(self.repo,'rev-parse','HEAD')
        error=self.reject('worktree-prepare','revision_conflict','arguments.expected_base',expected_base='0'*40,authorization_source='Fixture preparation request')
        self.assertEqual(error.details['value'],'0'*40)
        self.assertEqual(error.details['current_base'],actual)
        self.assertNotIn('worktree_preparation',self.state)
        self.op('worktree-prepare',expected_base=actual,authorization_source='Fixture preparation request')
        self.assertEqual(self.state['worktree_preparation']['base'],actual)
        error=self.reject('worktree-prepare','revision_conflict','arguments.expected_base',expected_base='1'*40,authorization_source='Fixture retry')
        self.assertEqual(error.details['recorded_base'],actual)
        self.assertEqual(error.details['current_base'],actual)
        original = w.git
        def unavailable(project, *arguments):
            if arguments == ('rev-parse','HEAD'):
                w.fail('git_failed','Fixture unavailable current base')
            return original(project,*arguments)
        with mock.patch.object(w,'git',side_effect=unavailable):
            error=self.reject('worktree-prepare','revision_conflict','arguments.expected_base',expected_base='2'*40,authorization_source='Fixture retry')
        self.assertIsNone(error.details['current_base'])
        self.assertEqual(error.details['current_base_status'],'unavailable')
        self.assertEqual(w.error_payload(w.WorkflowError('legacy','Preserved message')),{'code':'legacy','message':'Preserved message'})
