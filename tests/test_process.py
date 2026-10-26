"""Structured discussion, provenance, approvals and selective evidence contracts."""
import copy
from pathlib import Path
import sys

from test_workflow import Fixture, w


USER = {"kind": "user", "reference": "Conversation turn: fixture request"}
AGENT = {"kind": "agent", "reference": "Fixture exploration proposal"}


class ProcessTests(Fixture):
    structured = True

    def discussion(self):
        self.op('process-intent', intent={'goal': 'Update fixture behavior', 'why': 'Make the requested result observable',
            'success_criteria': ['The scoped verification passes'], 'source': USER})
        self.op('process-exploration', exploration={'current_behavior': 'The fixture has its original value.',
            'evidence': ['code.py and uv.lock inspected'], 'unknowns': []})
        self.op('process-playback', summary='The fixture update and its verification are in scope.', confirmation_source=USER)
        self.requirements = [
            {'id': 'R1', 'text': 'Update code behavior', 'kind': 'scope', 'status': 'confirmed', 'source': USER},
            {'id': 'R2', 'text': 'Preserve lock metadata', 'kind': 'acceptance', 'status': 'confirmed', 'source': USER}]
        self.op('process-requirements', requirements=self.requirements)
        self.op('process-playback', summary='The recorded requirements match the user request.', confirmation_source=USER)

    def design_content(self):
        return {'behavior': 'Implement the requested fixture behavior.',
            'components': [
                {'id': 'code', 'requirement_ids': ['R1'], 'behavior': 'Update the code value.', 'interfaces': ['VALUE'], 'files': ['code.py']},
                {'id': 'lock', 'requirement_ids': ['R2'], 'behavior': 'Retain the lock declaration.', 'interfaces': [], 'files': ['uv.lock']}],
            'decisions': [], 'rationale': 'Use the existing fixture layout.', 'impact': 'Only the declared scopes change.',
            'assumptions': ['The fixture repository is available.'],
            'verification': [{'requirement_id': ref, 'method': 'Inspect and execute the scoped check.', 'expected_result': 'The required scope passes.'} for ref in ['R1', 'R2']],
            'unresolved': [], 'delegated_scope': []}

    def designed(self, content=None):
        if not self.state['process']['playback']:
            self.op('process-playback', summary='The recorded requirements and choices match the discussion.', confirmation_source=USER)
        self.op('process-design', design=content or self.design_content())
        self.op('process-design-review', actor='design-reviewer', design_digest=self.state['design']['digest'],
            verdict='accept', notes='Requirement coverage and gaps inspected.', evidence=['Independent fixture design inspection'])
        self.op('process-design-approve', design_digest=self.state['design']['digest'], authorization_source='Conversation: user confirmed design')

    def plan_content(self):
        return {'shared_requirements': [], 'dependencies': [], 'review_focus': 'Inspect scope coverage and actual checks.',
            'items': [
                {'id': name, 'title': 'Implement ' + name, 'requirement_ids': [ref], 'deliverables': ['Accepted ' + filename],
                 'files': [filename], 'interfaces': [], 'dependencies': [], 'steps': ['Inspect the scope', 'Implement and verify'],
                 'verification': [{'method': 'Execute scoped check', 'expected_result': 'Exit zero'}], 'acceptance': ['Independent review accepts']}
                for name, ref, filename in [('code', 'R1', 'code.py'), ('lock', 'R2', 'uv.lock')]]}

    def planned(self, plan=None):
        self.op('process-plan', plan=plan or self.plan_content())
        self.op('process-plan-approve', plan_digest=self.state['process']['plan']['digest'], authorization_source='Conversation: user confirmed plan')

    def approved(self):
        self.discussion(); self.designed(); self.planned()

    def question(self, name='Q1'):
        return {'id': name, 'text': 'Which behavior is authorized?', 'rationale': 'Current design and delegation do not settle it.',
            'scope': ['R1'], 'important': True}

    def reenter(self):
        self.op('process-reenter', question=self.question(), reason='The next action needs a user decision.')
        self.op('process-answer', question_id='Q1', answer='Keep the scope and revise the code component.', source=USER)
        self.op('process-playback', summary='Revise the code component within the confirmed requirements.', confirmation_source=USER)

    def test_new_protocol_and_exact_structured_schema(self):
        self.assertEqual(self.state['process']['protocol_version'], 2)
        self.assertEqual(w.summary(self.state)['stage'], 'exploration')
        self.error('structured_operation_required', lambda: self.op('design', content='Unstructured bypass'))
        self.error('structured_operation_required', lambda: self.op('approve', design_digest='any', authorization_source='Claimed'))
        self.error('exploration_required', lambda: self.op('process-design', design=self.design_content()))
        schemas = {entry['name']: entry['inputSchema'] for entry in w.command_schemas()}
        design_schema = schemas['process-design']['properties']['design']
        self.assertFalse(design_schema['additionalProperties'])
        self.assertIn('components', design_schema['required'])
        self.assertIn('requirement_ids', design_schema['properties']['components']['items']['required'])

    def test_missing_source_and_proposal_promotion_preserves_origin(self):
        self.discussion()
        proposal = {'id': 'D1', 'title': 'Fixture choice', 'choice': 'Use the existing layout', 'rationale': 'It is already available',
            'scope': ['R1'], 'status': 'proposed', 'source': AGENT}
        missing = copy.deepcopy(proposal); missing.pop('source')
        self.error('invalid_process', lambda: self.op('process-decision', decision=missing))
        self.op('process-decision', decision=proposal)
        self.error('confirmation_required', lambda: self.op('process-decision', decision={**proposal, 'status': 'confirmed'}))
        self.error('origin_changed', lambda: self.op('process-decision', decision={**proposal, 'status': 'confirmed', 'source': USER}))
        self.op('process-decision', decision={**proposal, 'status': 'confirmed', 'confirmation_source': USER})
        self.assertEqual(self.state['process']['decisions'][0]['source'], AGENT)
        reqs = copy.deepcopy(self.requirements)
        reqs[0].update(source=AGENT, status='proposed')
        self.error('origin_changed', lambda: self.op('process-requirements', requirements=reqs))

    def test_single_question_multi_round_and_reexploration(self):
        self.discussion()
        self.op('process-question', question=self.question())
        self.error('question_pending', lambda: self.op('process-question', question=self.question('Q2')))
        self.error('question_pending', lambda: self.op('process-design', design=self.design_content()))
        self.error('source_required', lambda: self.op('process-answer', question_id='Q1', answer='Agent chooses', source=AGENT))
        self.op('process-exploration', exploration={'current_behavior': 'Additional source checked', 'evidence': ['Additional code inspection'], 'unknowns': []})
        self.op('process-answer', question_id='Q1', answer='User selects the requested behavior.', source=USER)
        self.op('process-question', question=self.question('Q2'))
        self.op('process-answer', question_id='Q2', answer='User confirms acceptance.', source=USER)
        self.op('process-playback', summary='Both key questions are resolved.', confirmation_source=USER)
        self.designed()
        self.assertEqual(len(self.state['process']['questions']), 2)

    def test_design_coverage_independent_review_and_plan_gates(self):
        self.tree(); self.discussion()
        incomplete = self.design_content(); incomplete['verification'] = []
        self.error('requirement_coverage', lambda: self.op('process-design', design=incomplete))
        self.op('process-design', design=self.design_content())
        design = self.state['design']['digest']
        self.error('design_review_required', lambda: self.op('process-design-approve', design_digest=design, authorization_source='User says yes'))
        self.error('independent_review_required', lambda: self.op('process-design-review', design_digest=design,
            verdict='accept', notes='Self review', evidence=['Self review']))
        self.op('process-design-review', actor='design-reviewer', design_digest=design, verdict='changes', notes='A gap needs correction.', evidence=['Gap inspection'])
        self.error('design_review_required', lambda: self.op('process-design-approve', design_digest=design, authorization_source='User says yes'))
        self.designed()
        self.error('discussion_required', lambda: self.op('item-start', item_id='overall', actor='implementer'))
        plan = self.plan_content(); del plan['items'][0]['verification']
        self.error('invalid_process', lambda: self.op('process-plan', plan=plan))
        self.op('process-plan', plan=self.plan_content())
        self.error('discussion_required', lambda: self.op('item-start', item_id='overall', actor='implementer'))
        self.op('process-plan-approve', plan_digest=self.state['process']['plan']['digest'], authorization_source='User approves exact plan')
        self.op('item-start', item_id='code', actor='implementer')

    def test_version_bound_design_plan_approvals(self):
        self.discussion()
        self.op('process-design', design=self.design_content())
        old = self.state['design']['digest']
        revised = self.design_content(); revised['components'][0]['behavior'] = 'Use a revised value.'
        self.op('process-design', design=revised)
        self.error('stale_design', lambda: self.op('process-design-approve', design_digest=old, authorization_source='Old confirmation'))
        self.op('process-design-review', actor='design-reviewer', design_digest=self.state['design']['digest'], verdict='accept', notes='Revised design checked', evidence=['Updated design'])
        self.op('process-design-approve', design_digest=self.state['design']['digest'], authorization_source='Current design confirmed')
        self.op('process-plan', plan=self.plan_content())
        old_plan = self.state['process']['plan']['digest']
        plan = self.plan_content(); plan['items'][0]['steps'].append('Inspect final value')
        self.op('process-plan', plan=plan)
        self.error('stale_plan', lambda: self.op('process-plan-approve', plan_digest=old_plan, authorization_source='Old confirmation'))

    def test_proposed_decisions_and_invalid_delegation_block_design(self):
        self.discussion()
        choice = {'id': 'D1', 'title': 'Choice', 'choice': 'Use local implementation', 'rationale': 'Fits existing source',
            'scope': ['R1'], 'status': 'proposed', 'source': AGENT}
        self.op('process-decision', decision=choice)
        self.op('process-playback', summary='The proposal remains unresolved.', confirmation_source=USER)
        self.error('unresolved_decisions', lambda: self.op('process-design', design=self.design_content()))
        self.error('delegation_required', lambda: self.op('process-decision', decision={**choice, 'status': 'delegated', 'delegation_id': 'missing'}))
        self.op('process-decision', decision={'id': 'authority', 'title': 'Implementation authority', 'choice': 'Delegate routine component choices',
            'rationale': 'The implementation scope is settled', 'scope': ['R1'], 'status': 'confirmed', 'source': USER, 'delegates': True})
        self.op('process-decision', decision={**choice, 'status': 'delegated', 'delegation_id': 'authority'})
        self.designed()

    def test_generic_reentry_preserves_unaffected_evidence(self):
        self.tree(); self.approved()
        self.complete('code'); self.complete('lock')
        old_code = copy.deepcopy(self.state['items']['code']['acceptance'])
        old_lock = copy.deepcopy(self.state['items']['lock']['acceptance'])
        self.op('process-reenter', question=self.question(), reason='The current authority does not settle this next step.')
        self.assertEqual(self.state['items']['lock']['acceptance'], old_lock)
        self.error('discussion_required', lambda: self.op('item-start', item_id='overall', actor='implementer'))
        self.op('process-answer', question_id='Q1', answer='Revise only the code component', source=USER)
        self.op('process-playback', summary='The lock component stays accepted.', confirmation_source=USER)
        design = self.design_content(); design['components'][0]['behavior'] = 'Revise the code component.'
        self.designed(design); self.planned()
        revision = w.revision(self.state)
        self.assertFalse(w.evidence_matches(old_code, w.binding(self.state, revision, self.state['items']['code'])))
        self.assertTrue(w.evidence_matches(old_lock, w.binding(self.state, revision, self.state['items']['lock'])))
        self.assertEqual(self.state['items']['lock']['acceptance'], old_lock)
        self.error('invalid_transition', lambda: self.op('item-start', item_id='lock', actor='implementer'))
        self.op('item-start', item_id='code', actor='implementer')

    def test_dependency_and_closure_gating(self):
        self.tree(); self.discussion(); self.designed()
        plan = self.plan_content(); plan['items'][1]['dependencies'] = ['code']
        self.planned(plan)
        self.error('dependency_incomplete', lambda: self.op('item-start', item_id='lock', actor='implementer'))
        self.error('integration_required', lambda: self.op('task-complete', outcome='completed', notes='Premature closure', evidence=['Claim']))
        self.complete('code'); self.complete('lock')
        self.complete('overall')
        self.assertEqual(self.state['process']['stage'], 'delivery')
        self.op('process-reenter', question=self.question(), reason='A delivery question requires discussion.')
        self.error('discussion_required', lambda: self.op('task-complete', outcome='completed', notes='Unresolved', evidence=['Claim']))

    def test_fresh_confirmation_and_current_delegation_required(self):
        self.discussion()
        revised = copy.deepcopy(self.requirements); revised[0]['text'] = 'Change additional behavior'
        self.error('confirmation_required', lambda: self.op('process-requirements', requirements=revised))
        revised[0]['confirmation_source'] = {'kind': 'user', 'reference': 'Conversation turn: user confirms revised behavior'}
        self.op('process-requirements', requirements=revised)
        self.error('playback_required', lambda: self.op('process-design', design=self.design_content()))
        authority = {'id': 'authority', 'title': 'Authority', 'choice': 'Delegate code choices', 'rationale': 'Scope settled',
            'scope': ['R1'], 'status': 'confirmed', 'source': USER, 'delegates': True}
        choice = {'id': 'choice', 'title': 'Choice', 'choice': 'Use a constant', 'rationale': 'Fits scope',
            'scope': ['R1'], 'status': 'delegated', 'source': AGENT, 'delegation_id': 'authority'}
        self.op('process-decision', decision=authority)
        self.op('process-decision', decision=choice)
        self.op('process-decision', decision={**authority, 'delegates': False,
            'confirmation_source': {'kind': 'user', 'reference': 'Conversation turn: delegation withdrawn'}})
        self.op('process-playback', summary='Authority was withdrawn.', confirmation_source=USER)
        self.error('delegation_required', lambda: self.op('process-design', design=self.design_content()))

    def test_confirmation_cannot_be_bypassed_by_downgrade_or_reused_id(self):
        self.discussion()
        downgraded = copy.deepcopy(self.requirements); downgraded[0]['status'] = 'proposed'
        self.op('process-requirements', requirements=downgraded)
        edited = copy.deepcopy(downgraded); edited[0]['text'] = 'Authorize a different behavior'
        self.op('process-requirements', requirements=edited)
        promoted = copy.deepcopy(edited); promoted[0]['status'] = 'confirmed'
        self.error('confirmation_required', lambda: self.op('process-requirements', requirements=promoted))
        proposal = {'id': 'R3', 'text': 'An agent proposal', 'kind': 'constraint', 'status': 'proposed', 'source': AGENT}
        self.op('process-requirements', requirements=[*edited, proposal])
        self.op('process-requirements', requirements=edited)
        self.error('origin_changed', lambda: self.op('process-requirements', requirements=[*edited, {**proposal, 'source': USER, 'status': 'confirmed'}]))
        choice = {'id': 'D1', 'title': 'Choice', 'choice': 'Original behavior', 'rationale': 'User scope', 'scope': ['R1'], 'status': 'confirmed', 'source': USER}
        self.op('process-decision', decision=choice)
        self.op('process-decision', decision={**choice, 'status': 'proposed'})
        self.op('process-decision', decision={**choice, 'status': 'proposed', 'choice': 'Changed behavior'})
        self.error('confirmation_required', lambda: self.op('process-decision', decision={**choice, 'choice': 'Changed behavior'}))

    def test_identical_content_new_revision_does_not_reuse_old_confirmation(self):
        self.discussion()
        self.op('process-design', design=self.design_content())
        old = self.state['design']['digest']
        self.op('process-design', design=self.design_content())
        self.assertNotEqual(old, self.state['design']['digest'])
        self.error('stale_design', lambda: self.op('process-design-review', actor='design-reviewer', design_digest=old, verdict='accept', notes='Old presented revision', evidence=['Old revision']))
        self.designed()
        self.op('process-plan', plan=self.plan_content())
        old_plan = self.state['process']['plan']['digest']
        self.op('process-plan', plan=self.plan_content())
        self.assertNotEqual(old_plan, self.state['process']['plan']['digest'])
        self.error('stale_plan', lambda: self.op('process-plan-approve', plan_digest=old_plan, authorization_source='Old presented revision'))

    def test_transitive_dependency_bytes_invalidate_dependent_evidence(self):
        self.tree(); self.discussion(); self.designed()
        plan = self.plan_content(); plan['items'][1]['dependencies'] = ['code']
        self.planned(plan); self.complete('code'); self.complete('lock')
        accepted = copy.deepcopy(self.state['items']['lock']['acceptance'])
        (self.feature / 'code.py').write_text('VALUE = 7\n')
        self.git(self.feature, 'add', 'code.py'); self.git(self.feature, 'commit', '-m', 'Change dependency bytes')
        self.assertFalse(w.evidence_matches(accepted, w.binding(self.state, w.revision(self.state), self.state['items']['lock'])))
        self.error('implementation_incomplete', lambda: self.op('item-start', item_id='overall', actor='overall-implementer'))

    def test_selected_decision_and_authority_changes_invalidate_only_their_scope(self):
        self.tree(); self.discussion()
        for name in ('first', 'second'):
            self.op('process-decision', decision={'id': name, 'title': 'Authority ' + name,
                'choice': 'Delegate code choices to ' + name, 'rationale': 'The user confirmed this code authority.',
                'scope': ['R1'], 'status': 'confirmed', 'source': USER, 'delegates': True})
        self.op('process-playback', summary='Both code authorities are confirmed.', confirmation_source=USER)
        design = self.design_content(); design['decisions'] = ['first']; design['delegated_scope'] = ['first']
        self.designed(design); self.planned(); self.complete('code'); self.complete('lock')
        accepted_code = copy.deepcopy(self.state['items']['code']['acceptance'])
        accepted_lock = copy.deepcopy(self.state['items']['lock']['acceptance'])
        self.reenter()
        design['decisions'] = ['second']
        self.designed(design); self.planned()
        current = w.revision(self.state)
        self.assertFalse(w.evidence_matches(accepted_code, w.binding(self.state, current, self.state['items']['code'])))
        self.assertTrue(w.evidence_matches(accepted_lock, w.binding(self.state, current, self.state['items']['lock'])))
        self.complete('code')
        accepted_code = copy.deepcopy(self.state['items']['code']['acceptance'])
        self.op('process-reenter', question=self.question('Q2'), reason='Select the second confirmed delegation authority.')
        self.op('process-answer', question_id='Q2', answer='Use the second confirmed authority.', source=USER)
        self.op('process-playback', summary='The delegation reference changes within the code scope.', confirmation_source=USER)
        design['delegated_scope'] = ['second']
        self.designed(design); self.planned()
        current = w.revision(self.state)
        self.assertFalse(w.evidence_matches(accepted_code, w.binding(self.state, current, self.state['items']['code'])))
        self.assertTrue(w.evidence_matches(accepted_lock, w.binding(self.state, current, self.state['items']['lock'])))

    def test_multiline_record_fields_keep_fixed_top_level_chapters(self):
        self.discussion()
        design = self.design_content()
        design['behavior'] = 'First behavior paragraph.\n\n## Embedded behavior heading\n- Embedded behavior detail'
        design['assumptions'] = ['First assumption.\n## Embedded assumption heading\nSecond assumption line.']
        self.designed(design)
        plan = self.plan_content(); plan['items'][0]['title'] = 'Code item\n## Embedded item heading'
        plan['items'][0]['steps'] = ['First step.\n\n## Embedded step heading\nContinue the same step.']
        self.planned(plan)
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        headings = [line for line in record.splitlines() if line.startswith('## ')]
        self.assertEqual(headings, ['## ' + name for name in ('Current state', 'Intent', 'Exploration', 'Confirmed requirements',
            'Sourced decisions', 'Design', 'Implementation plan', 'Execution and review', 'Experiments and runs', 'Delivery', 'Decision history')])
        for heading in ('behavior', 'assumption', 'item', 'step'):
            self.assertIn('  ## Embedded ' + heading + ' heading', record)
        self.op('recover')
        self.assertEqual(record, (self.root / '.task-workflow/tasks/task/record.md').read_text())

    def test_separate_requirements_and_quality_verdicts(self):
        self.tree(); self.approved()
        self.op('item-start', item_id='code', actor='implementer')
        self.op('item-submit', item_id='code', actor='implementer')
        self.error('review_dimensions_required', lambda: self.op('item-review', item_id='code', actor='reviewer', verdict='accept', notes='Missing dimensions'))
        self.error('invalid_verdict', lambda: self.op('item-review', item_id='code', actor='reviewer', verdict='accept',
            requirements_verdict='accept', quality_verdict='changes', notes='Quality has a gap'))
        self.op('item-review', item_id='code', actor='reviewer', verdict='changes', requirements_verdict='accept', quality_verdict='changes',
            notes='Fix quality before acceptance.', findings=['A concrete quality defect'], unverified=[])
        self.assertEqual(self.state['items']['code']['status'], 'implementing')
        self.op('item-submit', item_id='code', actor='implementer')
        self.op('verify', item_id='code', argv=[sys.executable, '-c', 'pass'])
        self.op('item-review', item_id='code', actor='reviewer', verdict='accept', requirements_verdict='accept', quality_verdict='accept', notes='Both checks pass')
        self.op('item-accept', item_id='code', notes='Accepted both verdicts and actual verification')
        self.assertEqual(self.state['items']['code']['review']['quality_verdict'], 'accept')

    def test_record_is_readable_markdown_and_history_references_events(self):
        self.approved()
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        for chapter in ('Current state', 'Intent', 'Exploration', 'Confirmed requirements', 'Sourced decisions', 'Design',
                        'Implementation plan', 'Execution and review', 'Experiments and runs', 'Delivery', 'Decision history'):
            self.assertIn('## ' + chapter, record)
        self.assertNotIn('```json', record)
        self.assertIn('**Goal:** Update fixture behavior', record)
        for entry in self.state['process']['history']:
            self.assertIn('previous_state_version', entry)
            self.assertNotIn('previous', entry)
        self.op('recover')
        self.assertEqual(record, (self.root / '.task-workflow/tasks/task/record.md').read_text())

    def test_invalid_nested_values_return_workflow_errors(self):
        self.discussion()
        self.error('invalid_process', lambda: self.op('process-design', design={'components': []}))
        design = self.design_content(); design['components'][0]['requirement_ids'] = ['absent']
        self.error('unknown_reference', lambda: self.op('process-design', design=design))
        design = self.design_content(); design['components'][0]['files'] = ['../escape']
        self.error('unsafe_path', lambda: self.op('process-design', design=design))


class LegacyProcessTests(Fixture):
    def test_old_records_keep_contract_until_explicit_upgrade(self):
        self.tree(); self.approved(); self.complete()
        accepted = copy.deepcopy(self.state['items']['overall']['acceptance'])
        approval = copy.deepcopy(self.state['approval'])
        self.assertNotIn('process', self.state)
        self.error('process_upgrade_required', lambda: self.op('process-intent', intent={}))
        self.op('recover')
        self.assertEqual(self.state['approval'], approval)
        self.op('process-upgrade', authorization_source='Conversation: explicitly approve contract upgrade')
        self.assertEqual(self.state['approval'], approval)
        self.assertEqual(self.state['items']['overall']['acceptance'], accepted)
        self.assertFalse(w.summary(self.state)['approved'])
        self.error('approval_required', lambda: self.op('item-start', item_id='overall', actor='implementer'))
        self.error('already_upgraded', lambda: self.op('process-upgrade', authorization_source='Repeated'))
