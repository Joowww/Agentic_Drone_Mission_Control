"""Offline-only proposal for a future present-resource reader successor.

This module is deliberately not imported by the precheck or disposition code. It
cannot authorize, apply, persist, or make a precheck eligible. It documents and
checks the narrow transition that a separately reviewed production protocol
would need to accept.
"""
from copy import deepcopy

RESOURCE_PIN = 'tools/rover_xrce_trace/present_resources.py'
PROPOSED_PROTOCOL = 'PRESENT_RESOURCE_READER_SUCCESSOR_V1'
HISTORICAL_RESOURCE_SHA256 = '23550ccfd411ed14aa7b24fe44cf7e2ac80e7a9751c526a6ff0c4c99b1d721c7'
CURRENT_RESOURCE_SHA256 = '5f73e030885eb8118b516e00bd97a3ac7c690458a536e733391d5b20677b4d07'
ALREADY_REVISABLE = frozenset((
    'tools/rover_xrce_trace/historical_disposition.py',
    'tools/simulation_profiles.py',
))


def _sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


def propose(parent_scope, candidate_scope, *, parent_scope_sha256,
            predecessor_file_hashes):
    """Return a non-enforceable review proposal for one exact reader transition."""
    if not _sha256(parent_scope_sha256):
        raise ValueError('Invalid predecessor scope digest')
    if (not isinstance(predecessor_file_hashes, dict)
            or set(predecessor_file_hashes) != {'intent.json', 'originals.json'}
            or not all(_sha256(v) for v in predecessor_file_hashes.values())):
        raise ValueError('Incomplete predecessor byte hashes')
    if not isinstance(parent_scope, dict) or not isinstance(candidate_scope, dict):
        raise ValueError('Scope objects required')
    old = deepcopy(parent_scope)
    new = deepcopy(candidate_scope)
    before = old.pop('reader_hashes', None)
    after = new.pop('reader_hashes', None)
    if old != new:
        raise ValueError('Proposal changes scope fields outside reader_hashes')
    if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
        raise ValueError('Reader pin set changed')
    changed = {name for name in before if before[name] != after[name]}
    allowed = set(ALREADY_REVISABLE) | {RESOURCE_PIN}
    if (RESOURCE_PIN not in changed or not changed <= allowed
            or before.get(RESOURCE_PIN) != HISTORICAL_RESOURCE_SHA256
            or after.get(RESOURCE_PIN) != CURRENT_RESOURCE_SHA256
            or not all(_sha256(after[name]) for name in changed)):
        raise ValueError('Resource reader transition does not match the reviewed offline delta')
    revisions = {name: {'before_sha256': before[name], 'after_sha256': after[name]}
                 for name in sorted(changed)}
    return {
        'status': 'PROPOSAL_ONLY_NOT_ENFORCED',
        'protocol': PROPOSED_PROTOCOL,
        'predecessor_scope_sha256': parent_scope_sha256,
        'predecessor_file_hashes': deepcopy(predecessor_file_hashes),
        'reader_revisions': revisions,
        'authorization_required': True,
        'persisted_audit_changed': False,
        'precheck_eligibility_changed': False,
        'opening_authorized': False,
        'movement_authorized': False,
    }
