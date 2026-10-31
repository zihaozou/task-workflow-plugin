"""Versioned dependency readiness, ownership and evidence projections."""
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/task-workflow/scripts/process_contracts.py'
SPEC = importlib.util.spec_from_file_location('process_contracts', SCRIPT)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


def plan():
    return {'contract_version': 2, 'shared_requirements': [], 'review_focus': 'Review behavior.',
        'dependencies': [], 'interface_contracts': [{'id': 'API', 'producer': 'a', 'consumers': ['b'], 'contract': 'Return an integer.'}],
        'items': [{'id': name, 'owner': name + '-worker', 'title': name, 'requirement_ids': [ref],
            'component_ids': [name], 'files': [name + '.py'], 'interfaces': ['API'], 'dependencies': [],
            'verification': [{'id': 'check', 'argv': ['python3', name + '.py'], 'expected_result': 'Integer output.'}]}
            for name, ref in [('a', 'R1'), ('b', 'R2')]]}


class ContractTests(unittest.TestCase):
    def assertCode(self, code, function):
        with self.assertRaises(c.ContractError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)

    def test_legacy_never_adopts_new_validation(self):
        self.assertEqual(c.contract_version({}), 1)
        c.validate_plan_contract({'items': [{'dependencies': ['old']} ]})
        self.assertEqual(c.dependency_edges({'dependencies': ['a']}, 1), [{'item_id': 'a', 'kind': 'implementation'}])
        self.assertCode('invalid_contract_version', lambda: c.contract_version({'contract_version': True}))

    def test_overlap_requires_execution_order_not_contract_agreement(self):
        p = plan(); p['items'][0]['files'] = ['pkg']; p['items'][1]['files'] = ['pkg/module.py']
        self.assertCode('concurrent_write_overlap', lambda: c.validate_plan_contract(p))
        p['items'][1]['dependencies'] = [{'item_id': 'a', 'kind': 'contract', 'interface_id': 'API'}]
        self.assertCode('concurrent_write_overlap', lambda: c.validate_plan_contract(p))
        p['items'][1]['dependencies'] = [{'item_id': 'a', 'kind': 'integration'}]
        self.assertCode('concurrent_write_overlap', lambda: c.validate_plan_contract(p))
        p['items'][1]['dependencies'] = [{'item_id': 'a', 'kind': 'implementation'}]
        c.validate_plan_contract(p)

    def test_disjoint_contract_dependency_and_invalid_contracts(self):
        p = plan(); p['items'][1]['dependencies'] = [{'item_id': 'a', 'kind': 'contract', 'interface_id': 'API'}]
        c.validate_plan_contract(p)
        p['items'][0]['dependencies'] = [{'item_id': 'b', 'kind': 'implementation'}]
        self.assertCode('dependency_cycle', lambda: c.validate_plan_contract(p))
        p['items'][0]['dependencies'] = []; p['items'][1]['dependencies'][0]['interface_id'] = 'absent'
        self.assertCode('interface_mismatch', lambda: c.validate_plan_contract(p))
        del p['items'][1]['dependencies'][0]['interface_id']
        self.assertCode('interface_required', lambda: c.validate_plan_contract(p))

    def test_transitive_writer_order(self):
        p = plan(); third = copy.deepcopy(p['items'][1]); third.update(id='c', files=['a.py'], dependencies=[{'item_id': 'b', 'kind': 'implementation'}])
        p['items'][1]['dependencies'] = [{'item_id': 'a', 'kind': 'implementation'}]; p['items'].append(third)
        c.validate_plan_contract(p)

    def test_each_dependency_has_distinct_evidence_prerequisite(self):
        p = plan(); p['items'][1]['dependencies'] = [
            {'item_id': 'a', 'kind': 'contract', 'interface_id': 'API'},
            {'item_id': 'a', 'kind': 'implementation'}, {'item_id': 'a', 'kind': 'integration'}]
        def missing(items=(), contracts=(), integration=(), phase='accept'):
            return c.dependency_prerequisites(p, 'b', accepted_items=items, accepted_contracts=contracts, integration_accepted=integration, phase=phase)
        self.assertEqual(len(missing()), 3)
        self.assertEqual(len(missing(contracts=['API'])), 2)
        self.assertEqual(len(missing(items=['a'])), 2)
        self.assertEqual(missing(['a'], ['API'], phase='start'), [])
        self.assertEqual(len(missing(contracts=['API'], integration=['a'])), 2)
        self.assertEqual(len(missing(['a'], ['API'], ['unrelated'])), 1)
        self.assertEqual(missing(['a'], ['API'], {'a': {'check': 'validated-current'}}), [])
        self.assertEqual(len(missing(['a'], ['API'], {'a': False})), 1)
        self.assertCode('invalid_integration_evidence', lambda: missing(integration=True))
        self.assertEqual(missing(['a'], ['API'], ['a']), [])

    def process(self):
        p = plan()
        return {'plan': {'content': p}, 'requirements': [{'id': ref, 'text': 'Behavior ' + ref, 'kind': 'acceptance', 'status': 'confirmed', 'source': {'reference': 'user'}} for ref in ('R1', 'R2')],
            'design': {'content': {'behavior': 'Required behavior.', 'rationale': 'Administrative explanation.',
                'components': [{'id': name, 'requirement_ids': [ref], 'behavior': 'Behavior ' + name, 'files': [name + '.py'], 'interfaces': ['API']} for name, ref in [('a', 'R1'), ('b', 'R2')]],
                'verification': [{'requirement_id': ref, 'expected_result': 'Pass'} for ref in ('R1', 'R2')]}}, 'decisions': []}

    def test_administrative_and_unrelated_changes_preserve_scope(self):
        process = self.process(); item = process['plan']['content']['items'][0]
        original = c.semantic_scope(process, item)
        process['plan']['content']['review_focus'] = 'Clarified review wording.'
        item['title'] = 'Clearer title'; process['requirements'][0]['source'] = {'reference': 'different reference'}
        process['design']['content']['rationale'] = 'Updated explanation.'
        process['design']['content']['components'][1]['behavior'] = 'Unrelated behavior update.'
        self.assertEqual(original, c.semantic_scope(process, item))
        process['requirements'][0]['text'] = 'Changed acceptance.'
        self.assertNotEqual(original, c.semantic_scope(process, item))

    def test_checks_interfaces_and_dependency_bindings_invalidate_scope(self):
        for mutate in (
            lambda process, item: item['verification'][0].update(argv=['python3', 'different.py']),
            lambda process, item: process['plan']['content']['interface_contracts'][0].update(contract='Return a string.'),
            lambda process, item: process['design']['content'].update(behavior='Changed global behavior.')):
            process = self.process(); item = process['plan']['content']['items'][0]; original = c.semantic_scope(process, item)
            mutate(process, item); self.assertNotEqual(original, c.semantic_scope(process, item))
        process = self.process(); item = process['plan']['content']['items'][0]
        self.assertNotEqual(c.semantic_scope(process, item, {'b': 'old'}), c.semantic_scope(process, item, {'b': 'new'}))

    def test_only_relevant_feasibility_prerequisites_change_scope(self):
        process = self.process(); item = process['plan']['content']['items'][0]
        checks = [{'check_id': 'probe-a', 'requirement_ids': ['R1']},
                  {'check_id': 'probe-b', 'requirement_ids': ['R2']}]
        process['design']['content']['feasibility_checks'] = checks
        original = c.semantic_scope(process, item)
        checks[1]['check_id'] = 'unrelated-replacement'
        self.assertEqual(original, c.semantic_scope(process, item))
        checks[0]['check_id'] = 'relevant-replacement'
        self.assertNotEqual(original, c.semantic_scope(process, item))
        checks[0]['check_id'] = 'probe-a'
        checks[1]['requirement_ids'] = ['R1']
        self.assertNotEqual(original, c.semantic_scope(process, item))
        process['plan']['content']['shared_requirements'] = ['R2']
        shared = c.semantic_scope(process, item)
        self.assertEqual(len(shared['feasibility_checks']), 2)
        proof = {'feasibility:probe-a': {'receipt_digest': 'old'}}
        changed = {'feasibility:probe-a': {'receipt_digest': 'new'}}
        self.assertNotEqual(c.semantic_scope(process, item, proof), c.semantic_scope(process, item, changed))

    def test_targeted_reentry_includes_consumers_not_unrelated_producers(self):
        p = plan(); p['items'][1]['dependencies'] = [{'item_id': 'a', 'kind': 'contract', 'interface_id': 'API'}]
        self.assertEqual(c.affected_item_ids(p, ['R2']), {'b'})
        self.assertEqual(c.affected_item_ids(p, ['R1']), {'a', 'b'})
        p['shared_requirements'] = ['GLOBAL']
        self.assertEqual(c.affected_item_ids(p, ['GLOBAL']), {'a', 'b'})


if __name__ == '__main__':
    unittest.main()
