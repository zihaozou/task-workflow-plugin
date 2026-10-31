"""Pure versioned plan contracts; legacy evidence remains owned by workflow.py."""
import copy
from pathlib import PurePosixPath


class ContractError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def _require(condition, code, message, **details):
    if not condition:
        raise ContractError(code, message, details)


def contract_version(plan):
    version = plan.get('contract_version', 1)
    _require(type(version) is int and version in (1, 2), 'invalid_contract_version',
             'Use contract_version 2 for new contracts or omit it for legacy plans.')
    return version


def dependency_edges(item, version=2):
    result = []
    for edge in item.get('dependencies', []):
        if version == 1:
            _require(isinstance(edge, str), 'invalid_dependency', 'Legacy dependencies are item identifiers.')
            result.append({'item_id': edge, 'kind': 'implementation'})
            continue
        _require(isinstance(edge, dict) and set(edge) <= {'item_id', 'kind', 'interface_id'}
                 and {'item_id', 'kind'} <= set(edge), 'invalid_dependency', 'Typed dependencies need item_id and kind.')
        _require(isinstance(edge['item_id'], str) and bool(edge['item_id']) and
                 edge['kind'] in ('contract', 'implementation', 'integration'),
                 'invalid_dependency', 'Use a producer item and contract, implementation or integration kind.')
        _require('interface_id' not in edge or isinstance(edge['interface_id'], str) and bool(edge['interface_id']),
                 'invalid_dependency', 'Interface identifiers must be nonempty strings.')
        _require(edge['kind'] != 'contract' or bool(edge.get('interface_id')), 'interface_required',
                 'Contract dependencies require an explicit interface identifier.')
        result.append(copy.deepcopy(edge))
    return result


def _overlap(left, right):
    a, b = PurePosixPath(left), PurePosixPath(right)
    return a == b or a in b.parents or b in a.parents


def validate_plan_contract(plan):
    """Validate v2 additions after the workflow's ordinary coverage validation."""
    version = contract_version(plan)
    if version == 1:
        return
    items = {item['id']: item for item in plan['items']}
    contracts = {}
    _require(isinstance(plan.get('interface_contracts', []), list), 'invalid_interface',
             'Interface contracts must be an array.')
    for contract in plan.get('interface_contracts', []):
        _require(isinstance(contract, dict) and set(contract) == {'id', 'producer', 'consumers', 'contract'},
                 'invalid_interface', 'Interfaces need id, producer, consumers and contract.')
        _require(all(isinstance(contract[key], str) and contract[key].strip() for key in ('id', 'producer', 'contract')),
                 'invalid_interface', 'Interface identity, producer and contract must be explicit.')
        _require(isinstance(contract['consumers'], list) and bool(contract['consumers']) and
                 all(isinstance(value, str) for value in contract['consumers']),
                 'invalid_interface', 'Interfaces require explicit consumer item identifiers.')
        _require(contract['id'] not in contracts, 'duplicate_interface', 'Interface identifiers must be unique.')
        _require(contract['producer'] in items and set(contract['consumers']) <= set(items),
                 'unknown_reference', 'Interface participants must name planned items.')
        _require(len(set(contract['consumers'])) == len(contract['consumers']) and
                 contract['producer'] not in contract['consumers'], 'invalid_interface',
                 'Interface consumers must be unique and distinct from the producer.')
        for participant in [contract['producer']] + contract['consumers']:
            _require(contract['id'] in items[participant].get('interfaces', []), 'interface_coverage',
                     'Each interface participant must declare its interface.', item_id=participant)
        contracts[contract['id']] = contract
    graph, ordered = {}, {}
    for item_id, item in items.items():
        _require(isinstance(item.get('owner'), str) and bool(item['owner'].strip()),
                 'owner_required', 'Version-2 items require an explicit owner.', item_id=item_id)
        graph[item_id], ordered[item_id] = set(), set()
        for edge in dependency_edges(item, version):
            producer = edge['item_id']
            _require(producer in items, 'unknown_reference', 'Dependency producer must name a planned item.', item_id=item_id)
            graph[item_id].add(producer)
            if edge['kind'] == 'implementation':
                ordered[item_id].add(producer)
            if edge.get('interface_id'):
                interface = contracts.get(edge['interface_id'])
                _require(interface is not None and interface['producer'] == producer and item_id in interface['consumers'],
                         'interface_mismatch', 'Dependency must consume the named producer interface.', item_id=item_id)
                _require(edge['interface_id'] in item.get('interfaces', []) and
                         edge['interface_id'] in items[producer].get('interfaces', []),
                         'interface_coverage', 'Both participants must declare the dependency interface.', item_id=item_id)
    def ancestors(item_id, edges, trail=()):
        _require(item_id not in trail, 'dependency_cycle', 'Implementation dependencies must not form a cycle.')
        result = set(edges[item_id])
        for producer in edges[item_id]:
            result.update(ancestors(producer, edges, trail + (item_id,)))
        return result
    for item_id in items:
        ancestors(item_id, graph)
    serial = {item_id: ancestors(item_id, ordered) for item_id in items}
    values = list(items.values())
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            collisions = [(a, b) for a in left['files'] for b in right['files'] if _overlap(a, b)]
            _require(not collisions or left['id'] in serial[right['id']] or right['id'] in serial[left['id']],
                     'concurrent_write_overlap', 'Overlapping writers need implementation ordering.',
                     item_ids=[left['id'], right['id']], paths=collisions)


def _fields(value, keys):
    return {key: copy.deepcopy(value[key]) for key in keys if key in value}


def semantic_scope(process, plan_item, dependency_bindings=None):
    """Project behavior-bearing v2 inputs; callers hash this, never legacy records."""
    plan = process['plan']['content']
    _require(contract_version(plan) == 2, 'legacy_projection', 'Keep legacy scope projection unchanged.')
    design = process['design']['content']
    refs = set(plan_item['requirement_ids']) | set(plan.get('shared_requirements', []))
    component_ids = set(plan_item['component_ids'])
    decisions = [entry for entry in process.get('decisions', []) if not entry.get('scope') or refs.intersection(entry['scope'])]
    decision_ids = {entry['id'] for entry in decisions}
    interfaces = set(plan_item.get('interfaces', []))
    return {
        'contract_version': 2,
        'requirements': sorted((_fields(entry, ('id', 'text', 'kind', 'status')) for entry in process['requirements'] if entry['id'] in refs), key=lambda value: value['id']),
        'global_design': _fields(design, ('behavior', 'assumptions', 'out_of_scope', 'failure_conditions')),
        'components': sorted((_fields(entry, ('id', 'requirement_ids', 'behavior', 'interfaces', 'files')) for entry in design['components'] if entry['id'] in component_ids), key=lambda value: value['id']),
        'decisions': sorted((_fields(entry, ('id', 'choice', 'scope', 'status', 'delegates', 'delegation_id')) for entry in decisions), key=lambda value: value['id']),
        'selected_decisions': sorted(set(design.get('decisions', [])) & decision_ids),
        'delegated_scope': sorted(set(design.get('delegated_scope', [])) & decision_ids),
        'verification': [copy.deepcopy(entry) for entry in design['verification'] if entry['requirement_id'] in refs],
        'feasibility_checks': sorted((copy.deepcopy(entry) for entry in design.get('feasibility_checks', [])
                                      if refs.intersection(entry['requirement_ids'])), key=lambda value: value['check_id']),
        'plan_item': _fields(plan_item, ('id', 'owner', 'requirement_ids', 'component_ids', 'deliverables', 'files', 'file_changes', 'interfaces', 'dependencies', 'steps', 'verification', 'acceptance')),
        'interface_contracts': sorted((copy.deepcopy(entry) for entry in plan.get('interface_contracts', []) if entry['id'] in interfaces), key=lambda value: value['id']),
        'dependencies': copy.deepcopy(dependency_bindings or {}),
    }


def dependency_prerequisites(plan, item_id, *, accepted_items, accepted_contracts, integration_accepted, phase='accept'):
    """Inputs are current validated evidence IDs, not unverified persisted claims.

    The caller must validate contract source authority, exact contract semantics and
    approved Spec binding before including its ID in accepted_contracts. Likewise,
    accepted_items contains only evidence matching current producer bindings.
    integration_accepted is a producer-ID set or mapping of validated current
    consumer composition-check evidence. Git publication is not composition proof.
    Start ignores composition edges; submission/acceptance checks them.
    """
    _require(phase in ('start', 'submission', 'accept'), 'invalid_dependency_phase',
             'Dependency phase must be start, submission or accept.')
    _require(not isinstance(integration_accepted, bool), 'invalid_integration_evidence',
             'Composition evidence must identify its producer items, not Git publication.')
    item = next(item for item in plan['items'] if item['id'] == item_id)
    missing = []
    for edge in dependency_edges(item, contract_version(plan)):
        kind = edge['kind']
        if kind == 'integration' and phase == 'start':
            continue
        composition = (bool(integration_accepted.get(edge['item_id'])) if isinstance(integration_accepted, dict)
                       else edge['item_id'] in integration_accepted)
        ready = (edge.get('interface_id') in accepted_contracts if kind == 'contract' else
                 edge['item_id'] in accepted_items if kind == 'implementation' else
                 edge['item_id'] in accepted_items and composition)
        if not ready:
            missing.append({**edge, 'reason': {'contract': 'accepted_interface_contract_required',
                'implementation': 'accepted_producer_evidence_required',
                'integration': 'accepted_producer_and_composition_evidence_required'}[kind]})
    return missing


def affected_item_ids(plan, requirement_ids):
    """Return affected items plus transitive consumers for a scoped reentry."""
    refs = set(requirement_ids)
    affected = {item['id'] for item in plan['items'] if refs.intersection(item['requirement_ids']) or refs.intersection(plan.get('shared_requirements', []))}
    while True:
        expanded = affected | {item['id'] for item in plan['items'] if any(edge['item_id'] in affected for edge in dependency_edges(item, contract_version(plan)))}
        if expanded == affected:
            return affected
        affected = expanded
