"""Offline validator for the versioned agent-to-rover mission proposal contract.

Validation binds a proposal hash and an authorization scope to the exact plan. It
never authenticates an operator, grants execution authority, or emits a command.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re

SCHEMA = 'tfg.rover.mission-execution/2'
SHA = re.compile(r'^[0-9a-f]{64}$')
PLAN_FIELDS = ('schema', 'mission', 'plan_id', 'rover', 'goal', 'localization',
               'dependencies', 'constraints', 'operator_limits', 'provenance',
               'validity', 'executor', 'stop_conditions')


def _sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def plan_sha256(payload):
    """Hash every proposal field that can change what the protected executor receives."""
    if not isinstance(payload, dict) or any(k not in payload for k in PLAN_FIELDS):
        raise ValueError('Incomplete mission plan projection')
    return _digest({key: payload[key] for key in PLAN_FIELDS})


def authorization_scope_sha256(payload):
    """Bind an authorization to this exact plan, mission, vehicle and contract version."""
    if not isinstance(payload, dict) or not _sha(payload.get('plan_sha256')):
        raise ValueError('Plan digest absent or malformed')
    mission = payload.get('mission')
    rover = payload.get('rover')
    mission = mission if isinstance(mission, dict) else {}
    rover = rover if isinstance(rover, dict) else {}
    if not mission.get('id') or not payload.get('plan_id') or not rover.get('vehicle_id'):
        raise ValueError('Plan identity incomplete')
    auth = payload.get('authorization')
    auth = auth if isinstance(auth, dict) else {}
    bridge_scope = auth.get('bridge_scope_sha256')
    if bridge_scope is not None and not _sha(bridge_scope):
        raise ValueError('Bridge scope digest malformed')
    binding = {'schema': payload.get('schema'), 'mission_id': mission['id'],
               'plan_id': payload['plan_id'], 'vehicle_id': rover['vehicle_id'],
               'plan_sha256': payload['plan_sha256']}
    # Preserve the original /2 scope digest for payloads created before the
    # optional bridge binding was introduced. A present bridge digest is bound.
    if bridge_scope is not None:
        binding['bridge_scope_sha256'] = bridge_scope
    return _digest(binding)


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_transform(transform, *, source_frame, target_frame, now):
    reasons = []
    if not isinstance(transform, dict):
        return ['FRAME_TRANSFORM_REQUIRED']
    if (transform.get('source_frame') != source_frame or transform.get('target_frame') != target_frame
            or source_frame == target_frame):
        reasons.append('FRAME_TRANSFORM_ENDPOINT_MISMATCH')
    if transform.get('validated') is not True:
        reasons.append('FRAME_TRANSFORM_NOT_VALIDATED')
    if not transform.get('source') or not _sha(transform.get('source_sha256')):
        reasons.append('FRAME_TRANSFORM_PROVENANCE_MISSING')
    matrix = transform.get('matrix')
    if (not isinstance(matrix, list) or len(matrix) != 3
            or any(not isinstance(row, list) or len(row) != 3 for row in matrix)
            or any(not _finite(v) for row in matrix for v in row)):
        reasons.append('FRAME_TRANSFORM_MATRIX_INVALID')
    else:
        a, b, tx = matrix[0]
        c, d, ty = matrix[1]
        bottom = matrix[2]
        tol = 1e-6
        if (abs(bottom[0]) > tol or abs(bottom[1]) > tol or abs(bottom[2] - 1.0) > tol
                or abs(a*a + c*c - 1.0) > tol or abs(b*b + d*d - 1.0) > tol
                or abs(a*b + c*d) > tol or abs(a*d - b*c - 1.0) > tol):
            reasons.append('FRAME_TRANSFORM_NOT_RIGID_2D')
    if not all(_finite(transform.get(k)) for k in ('uncertainty_m', 'uncertainty_rad')):
        reasons.append('FRAME_TRANSFORM_UNCERTAINTY_INVALID')
    elif transform['uncertainty_m'] < 0 or transform['uncertainty_rad'] < 0:
        reasons.append('FRAME_TRANSFORM_UNCERTAINTY_INVALID')
    start, end = _time(transform.get('not_before_utc')), _time(transform.get('expires_at_utc'))
    if start is None or end is None or start >= end:
        reasons.append('FRAME_TRANSFORM_VALIDITY_INVALID')
    elif start > now or end <= now:
        reasons.append('FRAME_TRANSFORM_EXPIRED_OR_NOT_YET_VALID')
    return reasons


def _authorization_and_localization(payload, *, now, reasons):
    goal = payload.get('goal')
    goal = goal if isinstance(goal, dict) else {}
    localization = payload.get('localization')
    limits = payload.get('operator_limits')
    limits = limits if isinstance(limits, dict) else {}
    conditional = goal.get('conditional') is True
    if not isinstance(localization, dict):
        if conditional:
            reasons.append('LOCALIZATION_PENDING_FOR_CONDITIONAL_PLAN')
        else:
            reasons.append('LOCALIZATION_MISSING_OR_UNVALIDATED')
    else:
        if localization.get('validated') is not True:
            reasons.append('LOCALIZATION_MISSING_OR_UNVALIDATED')
        if not localization.get('source') or not _sha(localization.get('source_sha256')):
            reasons.append('LOCALIZATION_PROVENANCE_MISSING')
        if (not _finite(localization.get('x_m')) or not _finite(localization.get('y_m'))
                or not _finite(localization.get('uncertainty_m')) or localization.get('uncertainty_m', -1) < 0):
            reasons.append('LOCALIZATION_POSITION_OR_UNCERTAINTY_INVALID')
        observed = _time(localization.get('observed_at_utc'))
        if observed is None:
            reasons.append('LOCALIZATION_TIMESTAMP_INVALID')
        elif observed > now:
            reasons.append('LOCALIZATION_TIMESTAMP_FUTURE')
        elif _finite(limits.get('localization_max_age_s')) and (now - observed).total_seconds() > limits['localization_max_age_s']:
            reasons.append('LOCALIZATION_STALE')
        max_uncertainty = limits.get('localization_max_uncertainty_m')
        if _finite(localization.get('uncertainty_m')) and _finite(max_uncertainty) and localization['uncertainty_m'] > max_uncertainty:
            reasons.append('LOCALIZATION_UNCERTAINTY_EXCEEDS_OPERATOR_LIMIT')
        goal_frame, localization_frame = goal.get('frame'), localization.get('frame')
        if not isinstance(goal_frame, str) or not isinstance(localization_frame, str) or not goal_frame or not localization_frame:
            reasons.append('FRAME_IDENTITY_MISSING')
        elif goal_frame == localization_frame:
            if localization.get('transform') is not None:
                reasons.append('UNNEEDED_FRAME_TRANSFORM_REJECTED')
        else:
            reasons.extend(_valid_transform(localization.get('transform'), source_frame=localization_frame,
                                            target_frame=goal_frame, now=now))

    auth = payload.get('authorization')
    auth = auth if isinstance(auth, dict) else {}
    expected_scope = None
    try:
        expected_scope = authorization_scope_sha256(payload)
    except (KeyError, TypeError, ValueError):
        pass
    has_authorization = bool(auth)
    if has_authorization and (not _sha(auth.get('scope_sha256')) or auth.get('scope_sha256') != expected_scope):
        reasons.append('AUTHORIZATION_PLAN_SCOPE_MISMATCH')
    if auth.get('human_authorized') is not True:
        reasons.append('HUMAN_AUTHORIZATION_MISSING_OR_INVALID')
    if not isinstance(auth.get('operator_id'), str) or not auth['operator_id'].strip():
        reasons.append('OPERATOR_ID_MISSING')
    if auth.get('operator_status') != 'AUTHENTICATED':
        reasons.append('OPERATOR_NOT_AUTHENTICATED')
    if auth.get('revocation_status') == 'REVOKED':
        reasons.append('AUTHORIZATION_REVOKED')
    elif auth.get('revocation_status') != 'ACTIVE':
        reasons.append('AUTHORIZATION_REVOCATION_UNCONFIRMED')
    bridge_scope = auth.get('bridge_scope_sha256')
    if bridge_scope is not None and not _sha(bridge_scope):
        reasons.append('BRIDGE_SCOPE_HASH_INVALID')
    if not _sha(auth.get('authorization_receipt_sha256')):
        reasons.append('AUTHORIZATION_RECEIPT_MISSING')


def validate(payload, *, now=None):
    """Return REJECTED, WAITING, or READY_TO_SUBMIT; never READY_TO_EXECUTE.

    AUTHENTICATED/ACTIVE are claims from the caller's authorization provider. This
    offline module has no mechanism to authenticate or query revocation itself.
    """
    reasons = []
    if not isinstance(payload, dict):
        return {'schema': SCHEMA, 'decision': 'REJECTED', 'reasons': ['PAYLOAD_NOT_OBJECT'],
                'commands': [], 'movement_authorized': False}
    if payload.get('schema') != SCHEMA:
        reasons.append('SCHEMA_MISMATCH')
    def obj(name):
        value = payload.get(name)
        return value if isinstance(value, dict) else {}
    mission, rover, goal = obj('mission'), obj('rover'), obj('goal')
    provenance, valid, executor = obj('provenance'), obj('validity'), obj('executor')
    if not mission.get('id') or not _sha(mission.get('sha256')):
        reasons.append('MISSION_ID_OR_DIGEST_MISSING')
    if not isinstance(payload.get('plan_id'), str) or not payload['plan_id']:
        reasons.append('PLAN_ID_MISSING')
    if not rover.get('vehicle_id') or not rover.get('platform'):
        reasons.append('ROVER_IDENTITY_MISSING')
    if not isinstance(goal.get('objective'), str) or not goal.get('objective'):
        reasons.append('OBJECTIVE_MISSING')
    if not isinstance(goal.get('frame'), str) or not goal.get('frame'):
        reasons.append('GOAL_FRAME_MISSING')
    if any(not _finite(goal.get(k)) for k in ('x_m', 'y_m')):
        reasons.append('GOAL_POSITION_INVALID')
    if type(goal.get('conditional')) is not bool:
        reasons.append('CONDITIONAL_FLAG_INVALID')
    if not isinstance(payload.get('dependencies'), list) or any(not isinstance(v, str) or not v for v in payload['dependencies']):
        reasons.append('DEPENDENCIES_INVALID')
    if not isinstance(payload.get('constraints'), dict) or not payload['constraints']:
        reasons.append('CONSTRAINTS_MISSING')
    limits = obj('operator_limits')
    auth = obj('authorization')
    if any(not _finite(limits.get(k)) or limits[k] <= 0 for k in
           ('max_speed_mps', 'timeout_s', 'max_distance_m', 'localization_max_uncertainty_m', 'localization_max_age_s')):
        reasons.append('OPERATOR_LIMITS_INVALID')
    if not _sha(provenance.get('source_sha256')) or not provenance.get('source'):
        reasons.append('MISSION_PROVENANCE_MISSING')
    if not _sha(payload.get('plan_sha256')):
        reasons.append('PLAN_HASH_MISSING_OR_INVALID')
    else:
        try:
            if plan_sha256(payload) != payload['plan_sha256']:
                reasons.append('PLAN_HASH_MISMATCH')
        except (TypeError, ValueError):
            reasons.append('PLAN_HASH_UNCANONICAL')
    start, end = _time(valid.get('not_before_utc')), _time(valid.get('expires_at_utc'))
    now = now or datetime.now(timezone.utc)
    if start is None or end is None or start >= end:
        reasons.append('VALIDITY_WINDOW_INVALID')
    elif end <= now:
        reasons.append('PAYLOAD_EXPIRED')
    elif start > now:
        reasons.append('PAYLOAD_NOT_YET_VALID')
    if not executor.get('id') or not executor.get('version'):
        reasons.append('EXECUTOR_IDENTITY_MISSING')
    stops = payload.get('stop_conditions')
    if not isinstance(stops, list) or not stops or any(not isinstance(v, str) or not v for v in stops):
        reasons.append('STOP_CONDITIONS_MISSING')
    _authorization_and_localization(payload, now=now, reasons=reasons)
    if reasons:
        conditional_wait = goal.get('conditional') is True and all(
            r in {'LOCALIZATION_PENDING_FOR_CONDITIONAL_PLAN', 'HUMAN_AUTHORIZATION_MISSING_OR_INVALID',
                  'OPERATOR_ID_MISSING', 'OPERATOR_NOT_AUTHENTICATED', 'AUTHORIZATION_REVOCATION_UNCONFIRMED',
                  'AUTHORIZATION_RECEIPT_MISSING'}
            for r in reasons)
        decision = 'WAITING' if conditional_wait else 'REJECTED'
    elif goal['conditional']:
        decision = 'WAITING'
    else:
        decision = 'READY_TO_SUBMIT'
    return {'schema': SCHEMA, 'decision': decision, 'reasons': reasons, 'commands': [],
            'movement_authorized': False, 'execution_requires_protected_executor': True,
            'operator_identity_authenticated': False, 'authorization_receipt_verified': False,
            'execution_authorized': False,
            'plan_sha256': payload.get('plan_sha256'),
            'authorization_scope_sha256': (auth if isinstance(auth, dict) else {}).get('scope_sha256')}
