"""Concrete Spec/Plan structures and compatible semantic record projections."""
import copy
import sys
from unittest import mock

from test_workflow import Fixture, w
import test_process as fixtures


class SpecPlanTests(Fixture):
    structured = True
    discussion = fixtures.ProcessTests.discussion
    design_content = fixtures.ProcessTests.design_content
    designed = fixtures.ProcessTests.designed
    plan_content = fixtures.ProcessTests.plan_content
    planned = fixtures.ProcessTests.planned

    def test_new_spec_requires_impact_scope_and_failure_fields_with_empty_lists_allowed(self):
        self.discussion()
        for field in ('current_impact', 'out_of_scope', 'failure_conditions'):
            design = self.design_content(); design.pop(field)
            self.error('invalid_process', lambda: self.op('process-design', design=design))
        design = self.design_content(); design.update(out_of_scope=[], failure_conditions=[])
        self.designed(design)
        self.assertTrue(w.design_is_approved(self.state))

    def test_generic_phases_and_incomplete_file_maps_do_not_form_a_new_plan(self):
        self.discussion(); self.designed()
        cases = [
            ('invalid_process', lambda item: item.update(steps=['Implement', 'Review', 'Integrate'])),
            ('file_coverage', lambda item: item.update(file_changes=[])),
            ('invalid_process', lambda item: item['file_changes'][0].update(action='phase')),
            ('invalid_process', lambda item: item['file_changes'].append(copy.deepcopy(item['file_changes'][0]))),
            ('unknown_reference', lambda item: item.update(component_ids=['absent'])),
            ('requirement_coverage', lambda item: item.update(component_ids=['lock'])),
            ('unknown_reference', lambda item: item['steps'][0].update(files=['uv.lock'])),
            ('unknown_reference', lambda item: item['steps'][0].update(interfaces=['undeclared-interface'])),
            ('unknown_reference', lambda item: item['steps'][0].update(verification_ids=['absent'])),
            ('unknown_reference', lambda item: item['verification'][0].update(requirement_ids=['R2'])),
            ('invalid_process', lambda item: item['steps'].append(copy.deepcopy(item['steps'][0]))),
            ('invalid_process', lambda item: item['verification'].append(copy.deepcopy(item['verification'][0])))]
        for code, mutate in cases:
            with self.subTest(code=code, mutation=mutate):
                plan = self.plan_content(); mutate(plan['items'][0])
                self.error(code, lambda: self.op('process-plan', plan=plan))

    def test_owned_file_and_check_coverage_are_explicit(self):
        self.discussion(); self.designed()
        plan = self.plan_content()
        item = plan['items'][0]
        item['files'].append('new-test.py')
        item['file_changes'].append({'path': 'new-test.py', 'action': 'test', 'responsibility': 'Verify the scoped value.'})
        self.error('file_coverage', lambda: self.op('process-plan', plan=plan))
        plan = self.plan_content(); item = plan['items'][0]
        item['verification'].append({**copy.deepcopy(item['verification'][0]), 'id': 'orphan'})
        self.error('check_coverage', lambda: self.op('process-plan', plan=plan))
        plan = self.plan_content(); item = plan['items'][0]
        item.update(requirement_ids=['R1', 'R2'], component_ids=['code', 'lock'])
        self.error('requirement_coverage', lambda: self.op('process-plan', plan=plan))

    def test_checks_allow_repeated_command_tokens_and_safe_dependency_inspection(self):
        self.discussion(); self.designed()
        plan = self.plan_content()
        check = plan['items'][0]['verification'][0]
        check.update(kind='command', argv=[sys.executable, '-c', 'import sys; assert sys.argv[1:] == ["a", "a"]', 'a', 'a'], targets=['tests/existing-check.py'])
        self.planned(plan)
        self.assertEqual(self.state['process']['plan']['content']['items'][0]['verification'][0]['argv'][-2:], ['a', 'a'])
        schema = {entry['name']: entry['inputSchema'] for entry in w.command_schemas()}['process-plan']
        argv_schema = schema['properties']['plan']['properties']['items']['items']['properties']['verification']['items']['properties']['argv']
        self.assertNotIn('uniqueItems', argv_schema)
        self.assertFalse((self.repo / 'tests/existing-check.py').exists())

    def test_component_and_declared_interface_coverage_cannot_hide_behind_shared_requirements(self):
        self.discussion()
        design = self.design_content()
        design['components'].append({**copy.deepcopy(design['components'][0]), 'id': 'companion'})
        self.designed(design)
        plan = self.plan_content()
        self.error('component_coverage', lambda: self.op('process-plan', plan=plan))
        plan['items'][0]['component_ids'].append('companion')
        plan['items'][0]['interfaces'] = ['VALUE']
        self.error('interface_coverage', lambda: self.op('process-plan', plan=plan))
        plan['items'][0]['steps'][0]['interfaces'] = ['VALUE']
        self.planned(plan)
        self.assertTrue(w.plan_is_approved(self.state))

    def test_command_and_inspection_checks_require_their_declared_method(self):
        self.discussion(); self.designed()
        for kind, fields, code in [
            ('command', {}, 'invalid_process'), ('command', {'argv': []}, 'invalid_process'),
            ('inspection', {'targets': []}, 'invalid_process'),
            ('inspection', {'argv': ['echo', 'not-an-inspection']}, 'invalid_process'),
            ('inspection', {'targets': ['../outside']}, 'unsafe_path')]:
            with self.subTest(kind=kind, fields=fields):
                plan = self.plan_content(); plan['items'][0]['verification'][0].update(kind=kind, **fields)
                self.error(code, lambda: self.op('process-plan', plan=plan))

    def test_documentation_plan_needs_no_code_signature_and_can_check_deleted_paths(self):
        self.discussion()
        design = self.design_content()
        design['components'][0].update(files=['guide.md'], interfaces=[], behavior='Document the required behavior.')
        self.designed(design)
        plan = self.plan_content(); item = plan['items'][0]
        item.update(files=['guide.md'], interfaces=[], file_changes=[{'path': 'guide.md', 'action': 'delete', 'responsibility': 'Remove obsolete guidance.'}])
        item['steps'][0].update(action='Remove the obsolete guide and inspect its references.', files=['guide.md'], interfaces=[])
        item['verification'][0].update(targets=['guide.md', 'README.md'], method='Inspect guide absence and preserved references.', expected_result='The guide is absent and the remaining references identify the current document.')
        self.planned(plan)
        self.assertTrue(w.plan_is_approved(self.state))

    def old_design(self):
        design = self.design_content()
        for field in ('current_impact', 'out_of_scope', 'failure_conditions'):
            design.pop(field)
        return design

    def record_old_design(self):
        # Reproduce an envelope accepted before detailed-submission validation.
        # Current review and approval operations run without patched guards.
        with mock.patch.object(w, 'validate_process_design', return_value=None):
            self.op('process-design', design=self.old_design())
        self.op('process-design-review', actor='independent', design_digest=self.state['design']['digest'],
                verdict='accept', notes='Historical Spec reviewed.', evidence=['Historical source inspected'])
        self.op('process-design-approve', design_digest=self.state['design']['digest'], authorization_source='Actual historical Spec approval')

    def test_old_stored_artifacts_keep_digests_and_can_complete_approval_and_recovery(self):
        self.discussion(); self.record_old_design()
        plan = self.plan_content()
        for item in plan['items']:
            item.pop('component_ids'); item.pop('file_changes')
            item['steps'] = ['Inspect the scope', 'Implement and verify']
            item['verification'] = [{'method': 'Inspect the historical scope.', 'expected_result': 'The declared value is present.'}]
        with mock.patch.object(w, 'validate_process_plan', return_value=None):
            self.op('process-plan', plan=plan)
        design = copy.deepcopy(self.state['process']['design'])
        stored_plan = copy.deepcopy(self.state['process']['plan'])
        self.op('process-plan-approve', plan_digest=stored_plan['digest'], authorization_source='Actual historical plan approval')
        approval = copy.deepcopy(self.state['process']['plan_approval'])
        self.op('recover')
        self.assertEqual(self.state['process']['design'], design)
        self.assertEqual(self.state['process']['plan'], stored_plan)
        self.assertEqual(self.state['process']['plan_approval'], approval)
        self.assertTrue(w.plan_is_approved(self.state))
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        self.assertIn('Spec (Design) D1', record)
        self.assertIn('Not recorded in this revision.', record)

    def test_old_approved_spec_can_receive_a_new_detailed_plan(self):
        self.discussion(); self.record_old_design(); self.planned()
        self.assertTrue(w.plan_is_approved(self.state))

    def test_new_discussion_context_does_not_become_content_of_a_historical_spec(self):
        self.discussion(); self.designed(); self.planned()
        original = copy.deepcopy(self.state['process']['design'])
        question = {'id': 'changed-scope', 'text': 'Which new behavior is intended?', 'rationale': 'The approved Spec does not settle this addition.',
                    'scope': ['R1'], 'important': True}
        self.op('process-reenter', question=question, reason='New scope requires discussion.')
        self.op('process-answer', question_id='changed-scope', answer='Discuss the added requirement first.', source=fixtures.USER)
        requirements = copy.deepcopy(self.requirements)
        requirements.append({'id': 'R3', 'text': 'Unconfirmed extra behavior', 'kind': 'scope', 'status': 'proposed', 'source': fixtures.AGENT})
        self.op('process-requirements', requirements=requirements)
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        spec = record.split('## Design\n', 1)[1].split('\n## Implementation plan\n', 1)[0]
        self.assertIn('historical; discussion changed', spec)
        self.assertIn('not approved by this revision', spec)
        self.assertIn('Revision source', spec)
        self.assertNotIn('Unconfirmed extra behavior', spec)
        self.assertNotIn(fixtures.AGENT['reference'], spec)
        self.assertIn('Unconfirmed extra behavior', record.split('## Design\n', 1)[0])
        self.assertIn('**Status:** proposed', record)
        self.assertEqual(self.state['process']['design'], original)

    def test_semantic_record_and_stage_presentation_expose_the_concrete_artifacts(self):
        self.discussion(); self.designed()
        contract = w.dialogue_contract(self.state)
        self.assertIn('templates/spec.md', contract['templates'])
        self.assertIn('File responsibilities', contract['presentation']['sections'])
        self.op('process-plan', plan=self.plan_content())
        contract = w.dialogue_contract(self.state)
        self.assertEqual(contract['presentation']['sections'][-1], 'Approve')
        self.assertIn('templates/plan.md', contract['templates'])
        record_path = self.root / '.task-workflow/tasks/task/record.md'
        record = record_path.read_text()
        for label in ('Spec (Design) D1', 'Intent and success', 'Current behavior and impact', 'Decisions and authority',
                      'Acceptance and failure conditions', 'Plan P1', 'File responsibilities', 'Ordered actions', 'Checks and expected outcomes'):
            self.assertIn(label, record)
        self.assertIn('| code.py | modify | Implement the declared code behavior. | code | code |', record)
        self.assertIn('| scope-check | Inspect the declared code value. | code.py | R1 |', record)
        self.op('recover')
        self.assertEqual(record_path.read_text(), record)
        self.op('process-plan-approve', plan_digest=self.state['process']['plan']['digest'], authorization_source='Actual detailed fixture plan approval')
        presentation = w.dialogue_contract(self.state)['presentation']
        self.assertEqual(presentation['sections'], ['Result', 'Checks', 'Needs attention', 'Next'])
        self.assertEqual(presentation['optional_sections'], ['Needs attention'])
        approved_record = record_path.read_text()
        item = self.state['items']['code']['plan_item']
        self.assertEqual(approved_record.count(item['steps'][0]['action']), 1)
        execution = approved_record.split('## Execution and review\n', 1)[1].split('\n## Experiments and runs\n', 1)[0]
        self.assertNotIn(item['steps'][0]['action'], execution)
        self.assertIn('Work item code in Plan P1', execution)
