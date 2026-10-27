"""Confirmed scope survives omission, replacement, reentry and host context."""
import copy
import importlib.util
import sys
from pathlib import Path

import test_process as process_fixture
from test_workflow import Fixture, w


class GoalIntegrityTests(Fixture):
    structured = True
    discussion = process_fixture.ProcessTests.discussion

    def change(self, action, **extra):
        return {'requirement_id': 'R1', 'previous_digest': w.digest(self.requirements[0]), 'action': action,
                'reason': 'Actual user changed the scope', 'authorization_source': {'kind': 'user', 'reference': 'Later actual user scope change'}, **extra}

    def test_confirmed_omission_rename_and_demotion_need_explicit_authority(self):
        self.discussion()
        for mutation in ('omit', 'rename', 'demote'):
            revised = copy.deepcopy(self.requirements)
            if mutation == 'omit':
                revised.pop(0)
            elif mutation == 'rename':
                revised[0]['id'] = 'renamed'
            else:
                revised[0]['status'] = 'proposed'
            self.error('scope_change_required', lambda: self.op('process-requirements', requirements=revised))
        self.assertEqual(self.state['process']['requirements'], self.requirements)

    def test_authorized_replacement_preserves_old_text_and_mapping(self):
        self.discussion()
        revised = copy.deepcopy(self.requirements)
        revised[0]['id'] = 'replacement'
        authority = self.change('replace', replacement_ids=['replacement'])
        revised[0]['confirmation_source'] = authority['authorization_source']
        self.op('process-requirements', requirements=revised, scope_changes=[authority])
        old = self.state['process']['requirement_history'][0]
        self.assertEqual(old['previous'], self.requirements[0])
        self.assertEqual(old['disposition']['replacement_ids'], ['replacement'])
        record = Path(self.root / '.task-workflow/tasks/task/record.md').read_text()
        self.assertIn('Requirement dispositions', record)
        self.assertIn('Update code behavior', record)

    def test_stale_and_agent_scope_change_are_rejected(self):
        self.discussion()
        change = self.change('remove'); change['previous_digest'] = 'stale'
        self.error('stale_scope_change', lambda: self.op('process-requirements', requirements=self.requirements[1:], scope_changes=[change]))
        change = self.change('remove'); change['authorization_source']['kind'] = 'agent'
        self.error('source_required', lambda: self.op('process-requirements', requirements=self.requirements[1:], scope_changes=[change]))

    def test_both_context_paths_emit_same_complete_goal_contract(self):
        scripts = Path(w.__file__).parent
        sys.path.insert(0, str(scripts))
        self.addCleanup(lambda: sys.path.remove(str(scripts)))
        modules = {}
        for name in ('communication_prompt_hook', 'deepseek_context'):
            spec = importlib.util.spec_from_file_location(name, scripts / (name + '.py'))
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
        normal = modules['communication_prompt_hook'].context_for({'hook_event_name': 'UserPromptSubmit', 'prompt': 'Implement the complete importer'})
        self.assertIn(w.GOAL_INTEGRITY, normal['hookSpecificOutput']['additionalContext'])
        guidance = modules['deepseek_context'].stage_guidance(w.dialogue_contract(self.state))
        self.assertEqual(guidance['goal_integrity'], w.GOAL_INTEGRITY)

    def test_retired_confirmed_identity_and_authority_survive_discussion_reentry(self):
        self.discussion()
        self.op('process-requirements', requirements=self.requirements[1:], scope_changes=[self.change('remove')])
        historical = copy.deepcopy(self.state['process']['provenance']['confirmed_requirements']['R1'])
        self.op('process-reenter', question={'id':'continue', 'text':'Which existing requirement continues?',
                'rationale':'Resolve an actual continuation question.', 'scope':['R2'], 'important':True}, reason='Actual continued discussion')
        self.op('process-answer', question_id='continue', answer='Continue the remaining acceptance requirement.',
                source={'kind':'user', 'reference':'Actual continuation answer'})
        altered = copy.deepcopy(self.requirements)
        altered[0]['text'] = 'A different requirement cannot reuse retired confirmation'
        self.error('confirmation_required', lambda:self.op('process-requirements', requirements=altered))
        self.assertEqual(self.state['process']['provenance']['confirmed_requirements']['R1'], historical)
        self.assertEqual(self.state['process']['requirement_history'][0]['previous'], self.requirements[0])
        self.assertEqual(self.state['process']['requirements'], self.requirements[1:])

    def test_retired_and_demoted_scope_need_fresh_confirmation_to_restore(self):
        self.discussion()
        removal = self.change('remove')
        self.op('process-requirements', requirements=self.requirements[1:], scope_changes=[removal])
        self.error('confirmation_required', lambda:self.op('process-requirements', requirements=self.requirements))
        restored = copy.deepcopy(self.requirements)
        restored[0]['confirmation_source'] = removal['authorization_source']
        self.error('confirmation_required', lambda:self.op('process-requirements', requirements=restored))
        fresh = {'kind':'user', 'reference':'Actual user explicitly restores original R1'}
        restored[0]['confirmation_source'] = fresh
        self.op('process-requirements', requirements=restored)
        self.op('process-requirements', requirements=restored)
        self.assertEqual(self.state['process']['requirements'][0]['source'], self.requirements[0]['source'])
        self.assertEqual(self.state['process']['requirements'][0]['confirmation_source'], fresh)
        demotion = {'requirement_id':'R1', 'previous_digest':w.digest(restored[0]), 'action':'demote',
                    'reason':'Actual user demotes restored requirement', 'authorization_source':{'kind':'user', 'reference':'Actual later demotion'}}
        proposed = copy.deepcopy(restored); proposed[0]['status'] = 'proposed'
        self.op('process-requirements', requirements=proposed, scope_changes=[demotion])
        self.error('confirmation_required', lambda:self.op('process-requirements', requirements=restored))
        restored[0]['confirmation_source'] = {'kind':'user', 'reference':'Actual final user reconfirmation'}
        self.op('process-requirements', requirements=restored)
        self.assertEqual([record['disposition']['action'] for record in self.state['process']['requirement_history']], ['remove', 'reconfirm', 'demote', 'reconfirm'])
