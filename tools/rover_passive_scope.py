"""Versioned, fail-closed contract for one passive rover_only lifecycle session.

This module only builds/validates declarations. It grants no authority by itself;
the lifecycle consumer must re-run the protected precheck while holding the
project execution and registry locks before consuming a scope.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from uuid import UUID, uuid4

SCHEMA = 'tfg.rover.passive-session-scope/1'
AUTHORIZATION_PREFIX = 'AUTHORIZE_PASSIVE_ROVER_SESSION'
MAX_SCOPE_AGE_S = 60.0
MAX_SESSION_DURATION_S = 300.0
OBSERVATION_COUNT = 100
ALLOWED_OPERATIONS = (
    'START_ROVER_ONLY', 'MOTION_BINDING_V2', 'READ_PARAMETERS',
    'PASSIVE_OBSERVE_100', 'CLOSE_WORKER', 'STOP_SAME_SESSION', 'FINAL_INVENTORY',
)
PROHIBITED_OPERATIONS = (
    'ARM', 'DISARM', 'GUIDED', 'HOLD', 'CMD_VEL', 'SEND_TARGET', 'MISSION_UPLOAD',
    'MOVE', 'WRITE_PARAMETER', 'ACTIVATE_POLICY', 'PHYSICAL_HARDWARE_CONTROL',
)
REQUIRED_CONDITIONS = (
    'fresh_observation', 'host_window_complete', 'reader_complete', 'no_restrictions',
    'no_guards', 'no_other_sessions', 'no_host_processes', 'host_identity_known',
    'audit_available', 'no_container_processes', 'resource_context', 'resource_duration',
    'resource_complete', 'resources_free', 'reader_version', 'resource_scope',
)
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class PassiveScopeError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def scope_sha256(scope):
    return hashlib.sha256(canonical_json(scope).encode('utf-8')).hexdigest()


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def _latest_precheck_source(precheck):
    rows = precheck.get('sources')
    if not isinstance(rows, list) or not rows:
        raise PassiveScopeError('PRECHECK_SOURCES_MISSING')
    values = [_utc(row.get('read_at_utc')) if isinstance(row, dict) else None for row in rows]
    if any(value is None for value in values):
        raise PassiveScopeError('PRECHECK_SOURCE_TIME_INVALID')
    return max(values)


def validate_precheck(precheck, *, now=None, host_boot_id=None, expected_environment=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    if not isinstance(precheck, dict) or precheck.get('status') != 'SATISFIED' or precheck.get('precheck_satisfied') is not True:
        reasons.append('PRECHECK_NOT_SATISFIED')
    conditions = precheck.get('conditions') if isinstance(precheck, dict) else None
    if not isinstance(conditions, dict) or any(conditions.get(k) is not True for k in REQUIRED_CONDITIONS):
        reasons.append('PRECHECK_CONDITIONS_INCOMPLETE')
    if isinstance(precheck, dict) and (precheck.get('opening_authorized') is not False
            or precheck.get('movement_authorized') is not False
            or precheck.get('source_association_verified') is not False):
        reasons.append('PRECHECK_AUTHORITY_FLAGS_INVALID')
    if isinstance(precheck, dict):
        try:
            age = (now - _latest_precheck_source(precheck)).total_seconds()
            if age < 0 or age > MAX_SCOPE_AGE_S:
                reasons.append('PRECHECK_STALE_OR_FUTURE')
        except PassiveScopeError:
            reasons.append('PRECHECK_SOURCE_TIME_INVALID')
        current = precheck.get('current_environment_execution')
        if not isinstance(current, dict):
            reasons.append('ENVIRONMENT_EXECUTION_MISSING')
        elif expected_environment is not None and current != expected_environment:
            reasons.append('ENVIRONMENT_EXECUTION_CHANGED')
    else:
        current = None
    if host_boot_id is not None:
        if not isinstance(host_boot_id, str) or not host_boot_id:
            reasons.append('HOST_BOOT_ID_MISSING')
    return reasons


def build_scope(precheck, *, host_boot_id, operator_id, now=None, session_id=None):
    now = now or datetime.now(timezone.utc)
    reasons = validate_precheck(precheck, now=now, host_boot_id=host_boot_id)
    if reasons:
        raise PassiveScopeError(';'.join(reasons))
    if not isinstance(operator_id, str) or not operator_id.strip() or len(operator_id) > 128:
        raise PassiveScopeError('OPERATOR_ID_INVALID')
    session_id = str(UUID(session_id)) if session_id is not None else str(uuid4())
    environment = precheck['current_environment_execution']
    persistent = environment.get('persistent_identity')
    if not isinstance(persistent, dict) or any(not isinstance(persistent.get(k), str) or not persistent[k]
            for k in ('engine_id', 'container_id', 'image_id', 'name', 'created_at')):
        raise PassiveScopeError('PERSISTENT_CONTAINER_IDENTITY_INCOMPLETE')
    if not isinstance(environment.get('container_boot_id'), str) or not environment['container_boot_id']:
        raise PassiveScopeError('CONTAINER_BOOT_ID_MISSING')
    observed_at = _latest_precheck_source(precheck).isoformat()
    return {
        'schema': SCHEMA,
        'scope_id': session_id,
        'session_id': session_id,
        'session_type': 'PASSIVE_ROVER_VALIDATION',
        'profile': 'rover_only',
        'vehicle': {'vehicle_id': 'rover_01', 'interface': 'v3', 'platform': 'ArduRover SITL'},
        'operator_id': operator_id.strip(),
        'authorization_basis': 'OPERATOR_DECLARED_NOT_AUTHENTICATED',
        'host': {'boot_id': host_boot_id},
        'environment_execution': environment,
        'protected_resources': ['simulation_lifecycle', 'rover_01/v3', persistent['container_id'], 'SITL_UDP_5780'],
        'precheck': {'status': 'SATISFIED', 'observed_at_utc': observed_at,
                     'report_sha256': hashlib.sha256(canonical_json(precheck).encode()).hexdigest(),
                     'audit_state': precheck.get('audit_state'),
                     'conditions': list(REQUIRED_CONDITIONS)},
        'allowed_operations': list(ALLOWED_OPERATIONS),
        'prohibited_operations': list(PROHIBITED_OPERATIONS),
        'max_session_duration_s': MAX_SESSION_DURATION_S,
        'issued_at_utc': now.isoformat(),
        'expires_at_utc': (now + timedelta(seconds=MAX_SCOPE_AGE_S)).isoformat(),
        'single_use': True,
        'initial_state_requirements': {'armed': False, 'driving': False},
        'motion_binding_protocol': '/2',
        'worker': {'mode': 'PASSIVE', 'observations': OBSERVATION_COUNT,
                   'parameter_capture': 'READ_ONLY', 'stationarity_report': True},
        'close_requirements': ['WORKER_CLOSED', 'STOP_SAME_SESSION', 'FINAL_INVENTORY'],
        'abort_conditions': ['PRECHECK_CHANGED', 'IDENTITY_CHANGED', 'WORKER_NOT_PASSIVE',
                             'OBSERVATION_COUNT_NOT_EXACT', 'WORKER_CLOSE_UNCONFIRMED',
                             'STOP_UNCONFIRMED', 'INVENTORY_INCOMPLETE'],
        'evidence_integrity': {'canonical_json': True, 'sha256': True, 'append_only_consumption': True},
    }


def authorization_text(operator_id, digest):
    """Return the exact declaration format; calling this does not assert consent."""
    if not isinstance(operator_id, str) or not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise PassiveScopeError('AUTHORIZATION_FIELDS_INVALID')
    return f'{AUTHORIZATION_PREFIX} {operator_id} {digest}'


def validate_scope(scope, *, supplied_sha256, authorization, fresh_precheck,
                   host_boot_id, profile='rover_only', now=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    if not isinstance(scope, dict):
        return ['SCOPE_NOT_OBJECT']
    expected_keys = {'schema','scope_id','session_id','session_type','profile','vehicle','operator_id','authorization_basis','host',
        'environment_execution','protected_resources','precheck','allowed_operations','prohibited_operations',
        'max_session_duration_s','issued_at_utc','expires_at_utc','single_use','initial_state_requirements',
        'motion_binding_protocol','worker','close_requirements','abort_conditions','evidence_integrity'}
    if set(scope) != expected_keys:
        reasons.append('SCOPE_FIELDS_UNKNOWN_OR_MISSING')
    try:
        canonical = scope_sha256(scope)
    except (TypeError, ValueError):
        return reasons + ['SCOPE_NOT_CANONICAL_JSON']
    if not isinstance(supplied_sha256, str) or not _SHA.fullmatch(supplied_sha256) or canonical != supplied_sha256:
        reasons.append('SCOPE_HASH_MISMATCH')
    if scope.get('schema') != SCHEMA or scope.get('session_type') != 'PASSIVE_ROVER_VALIDATION':
        reasons.append('SCOPE_TYPE_OR_VERSION_MISMATCH')
    if scope.get('profile') != profile or profile != 'rover_only':
        reasons.append('PROFILE_MISMATCH')
    if scope.get('vehicle') != {'vehicle_id':'rover_01','interface':'v3','platform':'ArduRover SITL'}:
        reasons.append('VEHICLE_IDENTITY_MISMATCH')
    try:
        if str(UUID(scope.get('scope_id'))) != scope.get('scope_id') or scope.get('session_id') != scope.get('scope_id'):
            reasons.append('SESSION_ID_INVALID')
    except (ValueError, TypeError, AttributeError):
        reasons.append('SESSION_ID_INVALID')
    if not isinstance(scope.get('operator_id'), str) or not scope['operator_id']:
        reasons.append('OPERATOR_ID_INVALID')
    if scope.get('authorization_basis')!='OPERATOR_DECLARED_NOT_AUTHENTICATED':
        reasons.append('AUTHENTICATED_OPERATOR_PROOF_UNAVAILABLE')
    if scope.get('host') != {'boot_id': host_boot_id}:
        reasons.append('HOST_BOOT_MISMATCH')
    environment = scope.get('environment_execution')
    if scope.get('environment_execution') != (fresh_precheck or {}).get('current_environment_execution'):
        reasons.append('ENVIRONMENT_EXECUTION_CHANGED')
    if not isinstance(environment, dict) or set(environment) != {'persistent_identity','container_started_at','container_boot_id'}:
        reasons.append('ENVIRONMENT_EXECUTION_FIELDS_INVALID')
    elif not isinstance(environment.get('persistent_identity'), dict) or set(environment['persistent_identity']) != {
            'engine_id','container_id','image_id','name','created_at'}:
        reasons.append('PERSISTENT_IDENTITY_FIELDS_INVALID')
    precheck_record = scope.get('precheck')
    if not isinstance(precheck_record, dict) or set(precheck_record) != {
            'status','observed_at_utc','report_sha256','audit_state','conditions'}:
        reasons.append('PRECHECK_SCOPE_FIELDS_INVALID')
    elif (precheck_record.get('status') != 'SATISFIED'
          or precheck_record.get('conditions') != list(REQUIRED_CONDITIONS)
          or precheck_record.get('audit_state') != (fresh_precheck or {}).get('audit_state')
          or not isinstance(precheck_record.get('report_sha256'), str)
          or not _SHA.fullmatch(precheck_record.get('report_sha256'))):
        reasons.append('PRECHECK_SCOPE_MISMATCH')
    if scope.get('protected_resources') != ['simulation_lifecycle','rover_01/v3',
            (environment or {}).get('persistent_identity',{}).get('container_id'), 'SITL_UDP_5780']:
        reasons.append('PROTECTED_RESOURCES_MISMATCH')
    if scope.get('initial_state_requirements') != {'armed':False,'driving':False}:
        reasons.append('INITIAL_STATE_REQUIREMENTS_MISMATCH')
    if scope.get('close_requirements') != ['WORKER_CLOSED','STOP_SAME_SESSION','FINAL_INVENTORY']:
        reasons.append('CLOSE_REQUIREMENTS_MISMATCH')
    if scope.get('abort_conditions') != ['PRECHECK_CHANGED','IDENTITY_CHANGED','WORKER_NOT_PASSIVE',
            'OBSERVATION_COUNT_NOT_EXACT','WORKER_CLOSE_UNCONFIRMED','STOP_UNCONFIRMED','INVENTORY_INCOMPLETE']:
        reasons.append('ABORT_CONDITIONS_MISMATCH')
    if scope.get('evidence_integrity') != {'canonical_json':True,'sha256':True,'append_only_consumption':True}:
        reasons.append('EVIDENCE_INTEGRITY_CONTRACT_MISMATCH')
    if scope.get('allowed_operations') != list(ALLOWED_OPERATIONS):
        reasons.append('ALLOWED_OPERATIONS_MISMATCH')
    if scope.get('prohibited_operations') != list(PROHIBITED_OPERATIONS):
        reasons.append('PROHIBITED_OPERATIONS_MISMATCH')
    if scope.get('single_use') is not True:
        reasons.append('SINGLE_USE_REQUIRED')
    if scope.get('max_session_duration_s') != MAX_SESSION_DURATION_S:
        reasons.append('SESSION_DURATION_INVALID')
    if scope.get('motion_binding_protocol') != '/2' or scope.get('worker') != {
            'mode':'PASSIVE','observations':OBSERVATION_COUNT,'parameter_capture':'READ_ONLY','stationarity_report':True}:
        reasons.append('PASSIVE_WORKER_CONTRACT_MISMATCH')
    issued = _utc(scope.get('issued_at_utc'))
    expires = _utc(scope.get('expires_at_utc'))
    if issued is None or expires is None or issued >= expires:
        reasons.append('SCOPE_VALIDITY_INVALID')
    elif issued > now or expires <= now or (now - issued).total_seconds() > MAX_SCOPE_AGE_S:
        reasons.append('SCOPE_EXPIRED_OR_STALE')
    expected_auth = authorization_text(scope.get('operator_id'), canonical)
    if authorization != expected_auth:
        reasons.append('EXACT_OPERATOR_DECLARATION_REQUIRED')
    reasons.extend(validate_precheck(fresh_precheck, now=now, host_boot_id=host_boot_id,
                                     expected_environment=scope.get('environment_execution')))
    return list(dict.fromkeys(reasons))


def consume_once(scope, *, supplied_sha256, authorization, fresh_precheck, host_boot_id,
                claim_root, lifecycle_owner, now=None):
    """Durably claim an exact scope before lifecycle side effects; never replay a claim."""
    now = now or datetime.now(timezone.utc)
    reasons = validate_scope(scope, supplied_sha256=supplied_sha256, authorization=authorization,
                             fresh_precheck=fresh_precheck, host_boot_id=host_boot_id, now=now)
    if reasons:
        raise PassiveScopeError(';'.join(reasons))
    if lifecycle_owner != scope['session_id']:
        raise PassiveScopeError('LIFECYCLE_OWNER_DIFFERS_FROM_SCOPE')
    import os
    from pathlib import Path
    root = Path(claim_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    claim = {'schema':'tfg.rover.passive-session-claim/1','state':'CONSUMED',
             'scope_id':scope['scope_id'],'scope_sha256':supplied_sha256,
             'lifecycle_owner':lifecycle_owner,'operator_id':scope['operator_id'],
             'authorization_sha256':hashlib.sha256(authorization.encode()).hexdigest(),
             'precheck_sha256':scope['precheck']['report_sha256'],
             'consumed_at_utc':now.isoformat(),'movement_authorized':False}
    path = root / (supplied_sha256 + '.json')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise PassiveScopeError('SCOPE_ALREADY_CONSUMED_OR_PERSISTENCE_UNCERTAIN') from None
    try:
        raw = canonical_json(claim).encode('utf-8')
        with os.fdopen(fd, 'wb', closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        # The exclusive claim is deliberately retained. Even a partial file
        # means consumption is uncertain and must block replay.
        raise
    return claim



def remaining_session_seconds(session_state, *, current_host_boot_id, now_monotonic):
    """Host-monotonic remaining budget from the lifecycle's START record; no simulated clock."""
    if not isinstance(session_state, dict) or session_state.get('state') not in {'OPENING', 'STARTED'}:
        raise PassiveScopeError('PASSIVE_SESSION_NOT_OPEN')
    if session_state.get('host_boot_id') != current_host_boot_id:
        raise PassiveScopeError('PASSIVE_SESSION_HOST_BOOT_CHANGED')
    started = session_state.get('started_host_monotonic_s')
    deadline = session_state.get('deadline_host_monotonic_s')
    if (not isinstance(started, (int, float)) or isinstance(started, bool)
            or not isinstance(deadline, (int, float)) or isinstance(deadline, bool)
            or not isinstance(now_monotonic, (int, float)) or isinstance(now_monotonic, bool)
            or not all(math.isfinite(v) for v in (started, deadline, now_monotonic))
            or deadline <= started):
        raise PassiveScopeError('PASSIVE_SESSION_DEADLINE_INVALID')
    return max(0.0, min(MAX_SESSION_DURATION_S, deadline - now_monotonic))

def prepare_current(*, operator_id, now=None):
    """Read-only builder used by the CLI; current precheck is not an opening token."""
    from tools.rover_xrce_trace.historical_disposition import current_diagnostic_precheck
    from tools.vehicle_execution_lock import process_identity
    identity = process_identity()
    if not identity or not identity.get('boot_id'):
        raise PassiveScopeError('HOST_IDENTITY_UNKNOWN')
    precheck = current_diagnostic_precheck()
    scope = build_scope(precheck, host_boot_id=identity['boot_id'], operator_id=operator_id, now=now)
    digest = scope_sha256(scope)
    return {'scope':scope,'scope_sha256':digest,
            'authorization_format':f'{AUTHORIZATION_PREFIX} {scope["operator_id"]} {digest}',
            'authorization_is_human_input':True,'opening_authorized':False,'movement_authorized':False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare',))
    parser.add_argument('--operator-id', required=True)
    args = parser.parse_args()
    try:
        result = prepare_current(operator_id=args.operator_id)
    except (PassiveScopeError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc),'opening_authorized':False,
                          'movement_authorized':False}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
