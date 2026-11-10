import copy

import pytest

from tools.rover_xrce_trace import reader_pin_successor_design as design


def scopes():
    parent = {'protocol': 'CURRENT_RESOURCE_REVIEW_V1',
              'historical': {'monitor': {'capture_complete': False}},
              'reader_hashes': {
                  design.RESOURCE_PIN: design.HISTORICAL_RESOURCE_SHA256,
                  'tools/rover_xrce_trace/historical_disposition.py': 'a' * 64,
                  'tools/simulation_profiles.py': 'b' * 64,
                  'tools/rover_xrce_trace/budget.py': 'c' * 64,
              }}
    candidate = copy.deepcopy(parent)
    candidate['reader_hashes'][design.RESOURCE_PIN] = design.CURRENT_RESOURCE_SHA256
    candidate['reader_hashes']['tools/rover_xrce_trace/historical_disposition.py'] = 'd' * 64
    candidate['reader_hashes']['tools/simulation_profiles.py'] = 'e' * 64
    return parent, candidate


def propose(parent, candidate):
    return design.propose(parent, candidate, parent_scope_sha256='1' * 64,
                          predecessor_file_hashes={'intent.json': '2' * 64,
                                                   'originals.json': '3' * 64})


def test_exact_resource_reader_delta_is_only_a_non_enforceable_proposal():
    parent, candidate = scopes()
    result = propose(parent, candidate)
    assert result['status'] == 'PROPOSAL_ONLY_NOT_ENFORCED'
    assert result['protocol'] == 'PRESENT_RESOURCE_READER_SUCCESSOR_V1'
    assert result['reader_revisions'][design.RESOURCE_PIN] == {
        'before_sha256': design.HISTORICAL_RESOURCE_SHA256,
        'after_sha256': design.CURRENT_RESOURCE_SHA256}
    assert result['authorization_required'] is True
    assert result['persisted_audit_changed'] is False
    assert result['precheck_eligibility_changed'] is False
    assert result['opening_authorized'] is result['movement_authorized'] is False


@pytest.mark.parametrize('mutation', ['extra_pin', 'missing_pin', 'wrong_old', 'wrong_new',
                                     'scope_change', 'bad_parent_hash', 'bad_file_hash'])
def test_proposal_rejects_unreviewed_transition_or_incomplete_predecessor(mutation):
    parent, candidate = scopes()
    kwargs = {'parent_scope_sha256': '1' * 64,
              'predecessor_file_hashes': {'intent.json': '2' * 64,
                                          'originals.json': '3' * 64}}
    if mutation == 'extra_pin':
        candidate['reader_hashes']['tools/rover_xrce_trace/budget.py'] = 'f' * 64
    elif mutation == 'missing_pin':
        candidate['reader_hashes'].pop('tools/rover_xrce_trace/budget.py')
    elif mutation == 'wrong_old':
        parent['reader_hashes'][design.RESOURCE_PIN] = '9' * 64
    elif mutation == 'wrong_new':
        candidate['reader_hashes'][design.RESOURCE_PIN] = '8' * 64
    elif mutation == 'scope_change':
        candidate['historical']['monitor']['capture_complete'] = True
    elif mutation == 'bad_parent_hash':
        kwargs['parent_scope_sha256'] = 'invalid'
    else:
        kwargs['predecessor_file_hashes'] = {'intent.json': '2' * 64}
    with pytest.raises(ValueError):
        design.propose(parent, candidate, **kwargs)
