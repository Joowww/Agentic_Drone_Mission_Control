"""Offline adapter from the multi-agent neutral rover request to the rover plan-bound v2 contract.

This adapter checks hashes and field associations. It does not authenticate an
operator, query revocation, create a vehicle command, or call an executor.
"""
from __future__ import annotations

import hashlib
import json
import math

from tools import rover_mission_payload as contract

# Value of provenance.source in every v2 proposal built here. It is part of the plan digest: callers that must
# derive the same plan scope read this constant. Plans built by earlier revisions carry the value recorded in
# multiagent/historical_identifiers.py (SNAPSHOT_ADAPTER_PROVENANCE_SOURCE).
PROVENANCE_SOURCE = 'multiagent-rover-executor-bridge'

REQUEST_SCHEMA = 'tfg.multiagent.rover-execution-request/1'


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _bridge_scope(plan, vehicle_id, proposal_sha256):
    body = {'plan': plan, 'vehicle_id': vehicle_id, 'proposal_sha256': proposal_sha256}
    # Match the bridge's canonical JSON algorithm (ensure_ascii defaults to True).
    raw = json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def validate_bridge_request(request):
    reasons = []
    if not isinstance(request, dict) or request.get('schema') != REQUEST_SCHEMA:
        return ['UNKNOWN_BRIDGE_SCHEMA']
    for key in ('task_id', 'vehicle_id', 'proposal_sha256', 'frame', 'target', 'dependencies'):
        if request.get(key) in (None, ''):
            reasons.append('MISSING_FIELD:' + key)
    if not _sha(request.get('proposal_sha256')):
        reasons.append('PROPOSAL_DIGEST_INVALID')
    plan = request.get('navigation_plan')
    if plan is None:
        reasons.append('NAVIGATION_PLAN_PENDING')
    elif not isinstance(plan, dict):
        reasons.append('NAVIGATION_PLAN_MALFORMED')
    else:
        if not isinstance(plan.get('plan_id'), str) or not plan['plan_id']:
            reasons.append('PLAN_ID_MISSING')
        if plan.get('frame') != request.get('frame'):
            reasons.append('FRAME_MISMATCH')
        if any(type(plan.get(k)) not in (int, float) or not math.isfinite(plan[k])
               for k in ('target_x_m', 'target_y_m', 'max_speed_mps', 'timeout_s')):
            reasons.append('PLAN_NUMERIC_FIELDS_INVALID')
        elif plan['max_speed_mps'] <= 0 or plan['timeout_s'] <= 0:
            reasons.append('PLAN_LIMITS_INVALID')
        if _sha(request.get('proposal_sha256')) and request.get('vehicle_id'):
            expected = _bridge_scope(plan, request['vehicle_id'], request['proposal_sha256'])
            if request.get('expected_scope_sha256') != expected:
                reasons.append('BRIDGE_SCOPE_HASH_MISMATCH')
            auth = request.get('authorization')
            if auth is not None and (not isinstance(auth, dict)
                    or auth.get('scope_sha256') != expected or auth.get('human_authorized') is not True):
                reasons.append('BRIDGE_AUTHORIZATION_PLAN_MISMATCH')
    target = request.get('target') or {}
    if not isinstance(target, dict) or not target.get('point_id'):
        reasons.append('TARGET_POINT_PENDING')
    return list(dict.fromkeys(reasons))


def adapt_request(request, *, mission, rover, localization, dependencies, constraints, operator_limits,
                  provenance, validity, executor, stop_conditions, operator_verification=None):
    """Build a v2 proposal only when the bridge plan and rover authorization both bind exactly.

    Missing target coordinates remain a conditional planning record. Missing
    localization on a nonconditional plan is rejected by the downstream validator.
    """
    reasons = validate_bridge_request(request)
    if 'NAVIGATION_PLAN_PENDING' in reasons or 'TARGET_POINT_PENDING' in reasons:
        return {'decision': 'WAITING', 'reasons': reasons, 'proposal': {
            'task_id': (request or {}).get('task_id'), 'target': (request or {}).get('target'),
            'frame': (request or {}).get('frame'), 'conditional': True,
            'coordinates': None, 'commands': [], 'movement_authorized': False}}
    hard = [r for r in reasons if r not in {'NAVIGATION_PLAN_PENDING', 'TARGET_POINT_PENDING'}]
    if hard:
        return {'decision': 'REJECTED', 'reasons': hard, 'commands': [], 'movement_authorized': False}
    plan = request['navigation_plan']
    if not isinstance(operator_verification, dict):
        return {'decision': 'WAITING', 'reasons': ['AUTHENTICATED_OPERATOR_RECEIPT_UNAVAILABLE'],
                'plan_id': plan['plan_id'], 'commands': [], 'movement_authorized': False}
    value = {'schema': contract.SCHEMA, 'mission': mission, 'plan_id': plan['plan_id'], 'rover': rover,
        'goal': {'objective': 'reach_agent_declared_point:' + request['target']['point_id'],
                 'frame': plan['frame'], 'x_m': plan['target_x_m'], 'y_m': plan['target_y_m'],
                 'conditional': False},
        'localization': localization, 'dependencies': list(dependencies), 'constraints': constraints,
        'operator_limits': {**operator_limits, 'max_speed_mps': plan['max_speed_mps'],
                            'timeout_s': plan['timeout_s']},
        'provenance': {**provenance, 'source': PROVENANCE_SOURCE,
                       'source_sha256': hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()},
        'authorization': operator_verification, 'validity': validity, 'executor': executor,
        'stop_conditions': list(stop_conditions)}
    value['plan_sha256'] = contract.plan_sha256(value)
    bridge_hash = request['expected_scope_sha256']
    if operator_verification.get('bridge_scope_sha256') != bridge_hash:
        return {'decision': 'REJECTED', 'reasons': ['OPERATOR_RECEIPT_NOT_BOUND_TO_BRIDGE_SCOPE'],
                'commands': [], 'movement_authorized': False}
    expected_plan_scope = contract.authorization_scope_sha256(value)
    if operator_verification.get('scope_sha256') != expected_plan_scope:
        return {'decision': 'REJECTED', 'reasons': ['OPERATOR_RECEIPT_NOT_BOUND_TO_ROVER_PLAN'],
                'commands': [], 'movement_authorized': False}
    result = contract.validate(value)
    return {'decision': result['decision'], 'reasons': result['reasons'], 'payload': value,
            'commands': [], 'movement_authorized': False}
