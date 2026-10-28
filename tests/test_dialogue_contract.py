"""Recorded dialogue dependencies, prompt recovery and frozen runtime behavior."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

from test_workflow import Fixture, SCRIPT, w
import test_process as process_fixtures
from test_process import USER, AGENT


class DialogueContractTests(Fixture):
    structured = True
    discussion = process_fixtures.ProcessTests.discussion
    design_content = process_fixtures.ProcessTests.design_content
    designed = process_fixtures.ProcessTests.designed
    plan_content = process_fixtures.ProcessTests.plan_content
    planned = process_fixtures.ProcessTests.planned
    approved = process_fixtures.ProcessTests.approved
    question = process_fixtures.ProcessTests.question

    def contract(self):
        return w.dispatch('context', {'root': str(self.root), 'task_id': 'task'})['dialogue_contract']

    def choices(self, name='Q1'):
        return {**self.question(name), 'source': AGENT, 'choices': [
            {'id': 'keep', 'text': 'Keep the current scope', 'consequence': 'Only the recorded component changes.', 'source': AGENT},
            {'id': 'expand', 'text': 'Expand the scope', 'consequence': 'The design needs additional requirements.', 'source': AGENT}]}

    def decision(self, question_id='Q1', source=None):
        return {'id': 'D-' + question_id, 'title': 'Recorded scope choice', 'choice': 'Keep the current scope',
            'rationale': 'The user selected the recorded option.', 'scope': ['R1'], 'status': 'confirmed',
            'source': AGENT, 'confirmation_source': source or USER, 'question_id': question_id, 'choice_id': 'keep'}

    def test_same_turn_enrollment_and_missing_exploration_are_explicit(self):
        contract = self.contract()
        self.assertEqual(contract['stage'], 'exploration')
        self.assertEqual(contract['state_version'], self.state['version'])
        self.assertEqual(contract['missing_records'], ['intent'])
        self.assertEqual(contract['allowed_next_operations'], ['context', 'status', 'process-intent'])
        self.error('exploration_required', lambda: self.op('process-question', question=self.question()))
        result = self.op('process-intent', intent={'goal': 'Inspect the fixture', 'why': 'Resolve actual behavior',
            'success_criteria': ['Evidence supports the design'], 'source': USER})
        self.assertEqual(result['dialogue_contract']['state_version'], self.state['version'])
        self.assertIn('exploration', result['dialogue_contract']['missing_records'])
        self.error('exploration_required', lambda: self.op('process-question', question=self.question()))

    def test_operation_scope_keeps_approved_work_available_and_closed_work_guarded(self):
        self.tree(); self.approved()
        contract = self.contract()
        self.assertEqual(contract['stage'], 'implementation')
        self.assertNotIn('item-start', contract['allowed_next_operations'])
        self.assertIn('not an exhaustive list', contract['operation_scope'])
        self.assertIn('existing user authorization', contract['operation_scope'])
        result = self.op('item-start', item_id='code', actor='implementer')
        self.assertEqual(result['state']['items']['code']['status'], 'implementing')
        self.op('task-complete', outcome='stopped', notes='The fixture user stopped work.', evidence=['Actual fixture stop request'])
        self.assertIn('authorized reopening', self.contract()['operation_scope'])
        self.error('task_closed', lambda: self.op('item-start', item_id='lock', actor='implementer'))
        self.error('coordinator_required', lambda: self.op('task-reopen', actor='other', reason='Unauthorized fixture actor'))
        self.op('task-reopen', reason='The fixture user explicitly requested resumption within the approved plan.')
        result = self.op('item-start', item_id='lock', actor='implementer')
        self.assertEqual(result['state']['items']['lock']['status'], 'implementing')

    def test_sourced_multi_round_choices_must_reach_the_generated_record(self):
        self.discussion()
        self.op('process-question', question=self.choices())
        current = self.contract()
        question = current['pending_questions'][0]
        self.assertEqual(question['choices'][0]['consequence'], 'Only the recorded component changes.')
        self.assertEqual(question['source'], AGENT)
        self.assertIn('question', current['reply_fields'][-1])
        self.assertEqual(current['presentation']['sections'][-1], 'Question')
        self.assertIn('end the turn', current['turn_exit'])
        self.error('answer_required', lambda: self.op('process-decision', decision=self.decision()))
        self.error('question_pending', lambda: self.op('process-design', design=self.design_content()))
        self.error('source_required', lambda: self.op('process-answer', question_id='Q1', answer='Keep', source=AGENT, choice_id='keep'))
        self.error('choice_required', lambda: self.op('process-answer', question_id='Q1', answer='Keep', source=USER, choice_id='missing'))
        self.error('stale_question', lambda: self.op('process-answer', question_id='Q1', answer='Keep', source=USER,
                                                   choice_id='keep', question_digest='old-question'))
        raw_answer = '\u4fdd\u7559\u5f53\u524d\u8303\u56f4'
        self.op('process-answer', question_id='Q1', answer=raw_answer, source=USER,
                choice_id='keep', question_digest=question['question_digest'])
        self.assertIn('decision:Q1', self.contract()['missing_records'])
        self.assertEqual(self.contract()['latest_answer']['answer']['text'], raw_answer)
        self.assertEqual(self.contract()['latest_answer']['selected_choice']['id'], 'keep')
        self.assertEqual(self.contract()['dialogue_mode'], 'answer_acknowledgment')
        self.error('decision_record_required', lambda: self.op('process-question', question=self.choices('Q2')))
        self.error('decision_record_required', lambda: self.op('process-requirements', requirements=self.requirements))
        self.error('decision_record_required', lambda: self.op('process-playback', summary='The selection is settled.', confirmation_source=USER))
        wrong = {**self.decision(), 'choice': 'Expand the scope'}
        self.error('answer_choice_mismatch', lambda: self.op('process-decision', decision=wrong))
        wrong = self.decision(source={'kind': 'user', 'reference': 'An unrelated user turn'})
        self.error('answer_source_mismatch', lambda: self.op('process-decision', decision=wrong))
        self.op('process-decision', decision=self.decision())
        self.assertEqual(self.contract()['latest_answer']['linked_decisions'][0]['confirmation_source'], USER)
        self.op('process-question', question=self.choices('Q2'))
        self.assertEqual(self.contract()['dialogue_mode'], 'answer_acknowledgment')
        self.assertIn('question', self.contract()['reply_fields'][-1])
        second_source = {'kind': 'user', 'reference': 'Conversation: second actual choice'}
        self.op('process-answer', question_id='Q2', answer='Keep this scope too.', source=second_source, choice_id='keep')
        self.op('process-decision', decision=self.decision('Q2', second_source))
        self.op('process-playback', summary='Both actual selections preserve the scope.', confirmation_source=second_source)
        self.designed()
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        self.assertNotIn(raw_answer, record)
        self.assertEqual(self.state['process']['questions'][0]['answer']['text'], raw_answer)
        self.assertEqual(self.contract()['latest_answer']['answer']['text'], 'Keep this scope too.')
        events = list((self.root / '.task-workflow/tasks/task/events').glob('*.json'))
        self.assertTrue(any(raw_answer in json.dumps(json.loads(event.read_text()), ensure_ascii=False) for event in events))
        self.assertIn('Keep the current scope', record)
        self.assertIn('Conversation: second actual choice', record)
        approval = self.contract()['approval_target']
        self.assertIsNone(approval)  # The helper records approval and enters plan.

    def test_exploration_refresh_preserves_answers_and_requires_current_playback(self):
        self.discussion()
        self.op('process-question', question=self.question())
        self.op('process-answer', question_id='Q1', answer='Preserve the scope.', source=USER)
        self.op('process-playback', summary='The answer is recorded.', confirmation_source=USER)
        original_answer = copy.deepcopy(self.state['process']['questions'][0]['answer'])
        self.op('process-exploration', exploration={'current_behavior': 'The child inspection found an evidence gap.',
            'evidence': ['Child report: source function inspected'], 'unknowns': ['Which checkpoint does the user intend?']})
        self.assertEqual(self.state['process']['questions'][0]['answer'], original_answer)
        self.error('unknowns_unresolved', lambda: self.op('process-playback', summary='Premature playback.', confirmation_source=USER))
        self.op('process-question', question={**self.question('Q2'), 'unknowns': ['Which checkpoint does the user intend?']})
        self.op('process-answer', question_id='Q2', answer='Use the latest recorded checkpoint.', source=USER)
        self.error('playback_required', lambda: self.op('process-design', design=self.design_content()))
        self.op('process-playback', summary='The checkpoint choice and original scope are confirmed.', confirmation_source=USER)
        self.designed(); self.planned()
        self.assertTrue(w.plan_is_approved(self.state))
        self.op('process-reenter', question=self.question('Q3'), reason='A new source fact needs discussion.')
        self.assertEqual(self.contract()['dialogue_mode'], 'reentry')
        self.error('discussion_required', lambda: self.op('item-start', item_id='code', actor='implementer'))
        self.assertEqual(self.state['process']['questions'][0]['answer'], original_answer)

    def test_freeform_correction_preserves_source_and_allows_a_new_route(self):
        self.discussion()
        proposal = {'id': 'proposal', 'title': 'Original agent proposal', 'choice': 'Keep the current scope',
            'rationale': 'The inspected layout supports it.', 'scope': ['R1'], 'status': 'proposed', 'source': AGENT}
        self.op('process-decision', decision=proposal)
        self.op('process-question', question=self.choices())
        source = {'kind': 'user', 'reference': 'Conversation: actual third-route correction'}
        raw_answer = 'Neither; use a third option.'
        self.op('process-answer', question_id='Q1', answer=raw_answer, source=source)
        answer = self.state['process']['questions'][0]['answer']
        self.assertEqual(answer['text'], raw_answer)
        self.assertEqual(answer['source'], source)
        self.assertNotIn('choice_id', answer)
        self.assertNotIn('selected_choice', self.contract()['latest_answer'])
        self.error('decision_record_required', lambda: self.op('process-playback', summary='Premature confirmation.', confirmation_source=source))
        fabricated_selection = {**self.decision(source=source), 'choice_id': 'keep'}
        self.error('answer_choice_mismatch', lambda: self.op('process-decision', decision=fabricated_selection))
        alternative = {'id': 'third-route', 'title': 'User correction', 'choice': 'Explore a third option',
            'rationale': 'The user rejected both proposed options.', 'scope': ['R1'], 'status': 'confirmed',
            'source': source, 'question_id': 'Q1'}
        self.op('process-decision', decision=alternative)
        self.assertEqual(next(entry for entry in self.state['process']['decisions'] if entry['id'] == 'proposal'), proposal)
        self.op('process-question', question={**self.question('Q2'), 'text': 'Which third option should the design explore?'})
        self.assertEqual(self.contract()['pending_questions'][0]['id'], 'Q2')
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        self.assertNotIn(raw_answer, record)
        self.assertIn('Explore a third option', record)
        self.assertIn(source['reference'], record)

    def test_generated_current_state_uses_the_actual_dialogue_contract(self):
        self.discussion()
        self.op('process-question', question={**self.choices(), 'purpose': 'clarification'})
        contract = self.contract()
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        current = record.split('## Current state\n', 1)[1].split('\n## Intent\n', 1)[0]
        for value in (contract['pending_questions'][0]['question_digest'], contract['wait_for'],
                      contract['required_recording_steps'][0]['instruction'], 'answer:Q1', 'clarification'):
            self.assertIn(value, current)
        self.assertNotIn('Workflow entrypoint', current)
        self.op('process-answer', question_id='Q1', answer='Keep the current scope.', source=USER, choice_id='keep')
        self.op('process-decision', decision=self.decision())
        self.op('process-playback', summary='The original choice is confirmed.', confirmation_source=USER)
        self.op('process-design', design=self.design_content())
        self.op('process-design-review', actor='reviewer', design_digest=self.state['design']['digest'],
                verdict='accept', notes='Actual design inspected.', evidence=['Independent design evidence'])
        record = (self.root / '.task-workflow/tasks/task/record.md').read_text()
        current = record.split('## Current state\n', 1)[1].split('\n## Intent\n', 1)[0]
        self.assertIn('**Approval target:**', current)
        self.assertIn(self.contract()['approval_target']['digest'], current)

    def test_factual_unknown_can_be_resolved_by_evidence_without_a_user_question(self):
        self.discussion()
        self.op('process-exploration', exploration={'current_behavior': 'A source file still needs inspection.',
            'evidence': ['Initial file inventory'], 'unknowns': ['How does the source parse checkpoints?']})
        self.op('process-exploration', exploration={'current_behavior': 'The parser reads the declared checkpoint path.',
            'evidence': ['Parser implementation inspected'], 'unknowns': []})
        self.op('process-playback', summary='Inspection settled the factual gap.', confirmation_source=USER)
        self.assertEqual(self.state['process']['questions'], [])
        self.designed()

    def test_playback_confirmation_purpose_selects_its_exact_order_and_wait(self):
        self.discussion()
        self.op('process-question', question=self.question())
        self.op('process-answer', question_id='Q1', answer='Keep the confirmed scope.', source=USER)
        self.op('process-question', question={**self.question('arbitrary-name'), 'purpose': 'playback_confirmation'})
        contract = self.contract()
        self.assertEqual(contract['dialogue_mode'], 'playback')
        self.assertEqual(contract['reply_fields'], ['Confirmed user requirements and choices with sources',
            'Agent proposals', 'Delegated choices and authority', 'Remaining unknowns and a request to confirm this playback'])
        self.assertIn('confirmation or correction', contract['wait_for'])
        self.assertEqual(contract['pending_questions'][0]['purpose'], 'playback_confirmation')
        self.error('question_pending', lambda: self.op('process-design', design=self.design_content()))
        self.op('process-answer', question_id='arbitrary-name', answer='This playback is correct.', source=USER)
        self.op('process-playback', summary='The actual playback was confirmed.', confirmation_source=USER)
        self.assertEqual(self.contract()['dialogue_mode'], 'design_preparation')

    def test_exact_approval_target_and_old_protocol_two_records_remain_readable(self):
        self.discussion()
        self.op('process-design', design=self.design_content())
        self.assertEqual(self.contract()['stage'], 'design_review')
        self.op('process-design-review', actor='reviewer', design_digest=self.state['design']['digest'],
                verdict='accept', notes='Independent source inspection.', evidence=['Actual design inspected'])
        target = self.contract()['approval_target']
        self.assertEqual(target, {'kind': 'design', 'version': 1, 'digest': self.state['design']['digest']})
        self.assertIn('end the turn', self.contract()['turn_exit'])
        self.op('process-design-approve', design_digest=target['digest'], authorization_source='Actual design approval')
        self.planned()
        prior = copy.deepcopy(self.state)
        for key in ('intent_digest', 'exploration_digest', 'questions_digest'):
            prior['process']['playback'].pop(key, None)
        for key in ('exploration_digest', 'questions_digest'):
            prior['process']['design'].pop(key, None)
        self.assertTrue(w.playback_is_current(prior['process']))
        self.assertTrue(w.design_is_approved(prior))
        self.assertEqual(w.dialogue_contract(prior)['stage'], 'implementation')

    def test_context_reads_and_every_lifecycle_early_return_emit_current_contract(self):
        self.tree()
        before = copy.deepcopy(self.state)
        with mock.patch.object(w, 'project_resources', side_effect=AssertionError('Context read aggregate resources')):
            context = w.dispatch('context', {'root': str(self.root), 'task_id': 'task'})
        self.assertNotIn('state', context)
        self.assertEqual(self.refresh(), before)
        for operation, fields in [('recover', {}), ('bind-session', {'session_id': 'session-fixture'}),
                                  ('worktree-prepare', {'expected_base': self.git(self.repo, 'rev-parse', 'HEAD'), 'authorization_source': 'Existing fixture checkout'})]:
            result = self.op(operation, **fields)
            self.assertEqual(result['dialogue_contract']['state_version'], self.state['version'])
        self.assertEqual(w.dispatch('list', {'root': str(self.root)})['tasks'][0]['dialogue_contract']['task_id'], 'task')

    def test_every_prompt_restores_latest_selected_task_from_worktree_without_writes(self):
        self.tree(); self.discussion()
        self.op('process-question', question=self.choices())
        hook = SCRIPT.parent / 'communication_prompt_hook.py'
        event = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.feature),
                 'session_id': 'session-fixture', 'prompt': 'Show current progress'}
        def prompt_context(fields=None):
            result = subprocess.run([sys.executable, str(hook)], input=json.dumps({**event, **(fields or {})}),
                                    text=True, capture_output=True, check=True)
            additional = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
            marker = ' Registered Task Workflow context: '
            return json.loads(additional.split(marker, 1)[1]) if marker in additional else None
        before = copy.deepcopy(self.state)
        restored = prompt_context()
        self.assertEqual(restored['dialogue_contract']['pending_questions'][0]['id'], 'Q1')
        self.assertEqual(restored['dialogue_contract']['state_version'], before['version'])
        runtime = restored['dialogue_contract']['current_runtime']
        self.assertEqual(runtime['workflow_entrypoint'], str(SCRIPT.resolve()))
        self.assertEqual(runtime['main_skill'], str(SCRIPT.parent.parent / 'SKILL.md'))
        self.assertIn('read the current main skill', restored['dialogue_contract']['recovery_rule'])
        self.assertIn('status question', restored['dialogue_contract']['applicability'])
        self.assertEqual(self.refresh(), before)
        second = self.enroll({'root': str(self.root), 'project': str(self.repo), 'task_id': 'second',
            'title': 'Second fixture task', 'actor': 'owner', 'session_id': 'session-fixture',
            'authorization_source': 'Actual second request'})['state']
        self.assertEqual(prompt_context()['task']['task_id'], 'second')
        self.op('bind-session', session_id='session-fixture')
        self.assertEqual(prompt_context()['task']['task_id'], 'task')
        self.assertEqual(w.dispatch('status', {'root': str(self.root), 'task_id': 'second'})['state'], second)
        self.assertIsNone(prompt_context({'session_id': 'other-session'}))
        unrelated = self.base / 'unrelated'; unrelated.mkdir()
        self.assertIsNone(prompt_context({'cwd': str(unrelated)}))

    def test_frozen_runtime_needs_only_workflow_and_runner(self):
        self.discussion()
        folder = self.base / 'frozen-runtime'; folder.mkdir()
        for name in ('workflow.py', 'runner.py'):
            shutil.copyfile(SCRIPT.parent / name, folder / name)
        spec = importlib.util.spec_from_file_location('frozen_dialogue_workflow', folder / 'workflow.py')
        frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
        result = frozen.dispatch('context', {'root': str(self.root), 'task_id': 'task'})
        source = self.contract(); frozen_contract = result['dialogue_contract']
        source.pop('current_runtime'); frozen_contract.pop('current_runtime')
        self.assertEqual(frozen_contract, source)
        self.assertNotIn('main_skill', frozen.dialogue_contract(self.state)['current_runtime'])
        self.assertEqual(frozen.session_dialogue_context(str(self.repo), 'session-fixture')['task']['task_id'], 'task')

