"""One pinned local legacy case, never a generic unlock or a verified reconciliation.

No subprocesses/controls on import or query. Preparation only reads operational
state and writes an audit. Mutating application/recovery is DISABLED: no verified
human-confirmation channel is integrated. Agent-authored claims are insufficient.
Historical completed results remain readable without replaying the transaction.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from tools import execution_reconciliation as audit
from tools import vehicle_execution_lock as locks
from tools import virtual_preflight_jobs as jobs
from tools import preflight_sequences as sequences
from tools.reconciliation_environment import inspect_environment, environment_identity, stopped_reasons

CASE_ID = 'c6eeb645-17d2-4081-9afb-cecfd23af393'
POLICY_PATH = locks.PROJECT_ROOT/'evaluation/operations/administrative_retirement_c6eeb645_proposal_2026_10_19.json'
POLICY_SHA256 = '32eb6f31ae191174136fa6bf054beb5071f4625d2f6fbcff61209d213c76d99a'
ORIGINAL_ROOT = Path('/home/joelm/TFG/Agentic_Drone_Mission_Control')
ROOT = locks.PROJECT_ROOT/'missions/generated/administrative_retirements'/CASE_ID
TTL_SECONDS = 120
RESULT = 'ADMINISTRATIVELY_RETIRED_UNVERIFIED'
ORDER = ('v2.json', 'sequence.json')  # child before outer guard; barrier covers both
KIND = 'CASE_SPECIFIC_ADMINISTRATIVE_RETIREMENT'


class AdministrativeRetirementAuthorization(BaseModel):
    model_config = {'extra':'forbid'}
    preparation_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        description='Exact reviewed preparation ID. Never substitute a new preparation after expiry/error.')
    preparation_sha256: str = Field(pattern=r'^[0-9a-f]{64}$',
        description='Exact reviewed preparation SHA-256; binding only, not authenticated human confirmation.')
    source: Literal['OPERATOR_ADMINISTRATIVE_DECISION']
    accept_unverified_historical_environment: Literal[True]
    accept_unknown_historical_clocks: Literal[True]
    local_reservations_only: Literal[True]
    statement: str = Field(min_length=1, description=(
        'Explicitly authorize retirement of the exact reviewed local case despite unresolved history. '
        'Acceptance of uncertainty, not a claim of continuity, landing, success or termination. '
        'No lifecycle or flight consent. Agent-carried declaration, not authenticated dialogue.'))


class ConfirmationBlocked(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _bound_authorization(preparation_id, preparation_sha256, authorization):
    claim = AdministrativeRetirementAuthorization.model_validate(authorization).model_dump()
    if (claim['preparation_id'] != preparation_id
            or claim['preparation_sha256'] != preparation_sha256):
        raise ConfirmationBlocked('CONFIRMATION_BINDING_MISMATCH',
            'Declaration belongs to another preparation ID/hash; new scope requires new human confirmation')
    if not claim['statement'].strip():
        raise ValueError('Explicit administrative authorization statement required')
    return claim


def _require_operator_confirmation(preparation_id, preparation_sha256, claim):
    """Fail closed. No production verifier, token, flag or client-accept fallback.

    MCP elicitation and agent arguments do not prove human origin to this server.
    Offline transaction regressions replace this gate with an explicitly named
    test double; they do not establish an available operational approval route.
    Any future verifier must bind one fresh response to this exact scope and
    request/connection, fail on timeout/error, and never carry it across reload.
    """
    raise ConfirmationBlocked('OPERATOR_CONFIRMATION_UNAVAILABLE',
        'No verified human-confirmation channel is integrated. Application/recovery disabled; '
        'do not prepare again, substitute identifiers, retry or resume automatically. Query history only.')


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, boundary, *, optional=False):
    if path.is_symlink() or not path.resolve().is_relative_to(boundary.resolve()):
        raise ValueError('Administrative audit path escapes fixed root or uses a symlink')
    try:
        return jobs.read_mission_input(path)
    except FileNotFoundError:
        if optional: return None
        raise


def _json(path, *, optional=False):
    raw = _read(path, ROOT, optional=optional)
    if raw is None: return None
    value = json.loads(raw)
    if not isinstance(value, dict): raise ValueError('Expected an administrative audit object')
    return value


def _sync(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _mkdir(directory):
    if directory.is_symlink(): raise ValueError('Symlink audit/history directory')
    if not directory.exists():
        _mkdir(directory.parent)
        directory.mkdir()
        _sync(directory.parent)
    _sync(directory)


def _write_once(path, raw):
    """Publish complete fsynced bytes without replacing an existing original/audit."""
    if path.exists() or path.is_symlink():
        current = _read(path, ROOT if path.is_relative_to(ROOT) else locks.LOCK_ROOT)
        if current != raw: raise ValueError(f'Existing immutable audit/archive differs: {path.name}')
        with path.open('rb') as file: os.fsync(file.fileno())
        _sync(path.parent)
        return
    temporary = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    with temporary.open('xb') as file:
        file.write(raw); file.flush(); os.fsync(file.fileno())
    os.link(temporary, path)  # atomic, fails rather than overwrite evidence
    _sync(path.parent)
    temporary.unlink()
    _sync(path.parent)


def _encoded(value):
    return (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()


def _policy():
    raw = jobs.read_mission_input(POLICY_PATH)
    if _hash(raw)!=POLICY_SHA256: raise ValueError('Pinned retirement proposal changed')
    value = json.loads(raw)
    if value['sequence_id']!=CASE_ID or set(value['allowed_records'])!=set(ORDER):
        raise ValueError('Only the pinned c6eeb645 sequence/child case is permitted')
    return value


def _versions(policy):
    result = {}
    for original, version in policy['inspected_artifact_versions'].items():
        relative = Path(original).relative_to(ORIGINAL_ROOT/'missions/generated')
        category, *rest = relative.parts
        base = {'vehicle_locks':locks.LOCK_ROOT, 'preflights':jobs.RUN_ROOT,
                'preflight_sequences':sequences.SEQUENCE_ROOT}.get(category)
        if base is None or not rest or '..' in rest: raise ValueError('Invalid pinned artifact category')
        result[str(base.joinpath(*rest))] = version
    return result


def _marker():
    raw = _read(locks.LOCK_ROOT/'reconciliation.json', locks.LOCK_ROOT, optional=True)
    return json.loads(raw) if raw is not None else None


@contextmanager
def _exclusive():
    with (locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock', blocking=False),
          locks.file_mutex(locks.LOCK_ROOT/'registry.lock', blocking=False)):
        yield


def _preparation(identifier):
    identifier = jobs.valid_run_id(identifier)
    root = ROOT/'preparations'/identifier
    if root.is_symlink(): raise ValueError('Symlink preparation directory')
    raw = _read(root/'preparation.json', ROOT)
    value = json.loads(raw)
    if (value.get('preparation_id')!=identifier or value.get('case_id')!=CASE_ID
            or value.get('policy_sha256')!=POLICY_SHA256):
        raise ValueError('Preparation/case/policy identity mismatch')
    for entry in value['snapshot']['files'].values():
        if 'content' in entry and _hash(entry['content'].encode())!=entry.get('sha256'):
            raise ValueError('Preparation contains corrupted archived artifact content')
    if (set(value['snapshot']['guards'])!=set(ORDER) or any(
            value['snapshot']['guards'][name]!=json.loads(_guard_bytes(value,name)) for name in ORDER)):
        raise ValueError('Preparation guard summary contradicts original bytes')
    return value, raw


def _environment(policy, previous=None):
    value = inspect_environment()
    expected = policy['observed_environment_not_historical_binding']
    reasons = stopped_reasons(value)
    if any(value.get(k)!=expected[k] for k in ('engine_id','container_id','name')):
        reasons.append('Current engine/container differs from the pinned administrative case')
    if previous is not None and environment_identity(value)!=environment_identity(previous):
        reasons.append('Current environment changed since preparation/revalidation')
    if reasons: raise ValueError(f'Administrative environment check blocked: {reasons}')
    return value


def _snapshot(policy):
    value = audit.capture(CASE_ID)
    versions = {path:{k:v for k,v in entry.items() if k!='content'} for path,entry in value['files'].items()}
    if versions != _versions(policy): raise ValueError('Pinned owners or artifact versions changed')
    if set(value['guards'])!=set(ORDER): raise ValueError('Unexpected or missing local restrictions')
    if audit._process_reasons(value): raise ValueError(f'Pertinent process alive/recycled: {audit._process_reasons(value)}')
    return value


def _fresh(preparation):
    elapsed = time.monotonic()-preparation['created_monotonic']
    if preparation['boot_id']!=audit.boot_id() or not 0<=elapsed<=TTL_SECONDS:
        raise ConfirmationBlocked('PREPARATION_EXPIRED_OR_BOOT_CHANGED',
            'Preparation expired or from another worker-host boot. No automatic preparation, '
            'identifier substitution, application or resume; a new scope needs a separate human confirmation.')


def _history(preparation):
    return locks.LOCK_ROOT/'history'/preparation['preparation_id']


def _guard_bytes(preparation, name):
    return preparation['snapshot']['files'][str(locks.LOCK_ROOT/name)]['content'].encode()


def _archives(preparation, *, required):
    history = _history(preparation)
    for name in ORDER:
        raw = _read(history/name, locks.LOCK_ROOT, optional=not required)
        if raw is not None and raw!=_guard_bytes(preparation,name):
            raise ValueError(f'Archived original changed: {name}')


def _verify_recovery(policy, preparation, *, protected):
    """Read current bytes/processes; archived guards never masquerade as live guards."""
    expected = _versions(policy)
    if {path:{k:v for k,v in e.items() if k!='content'} for path,e in preparation['snapshot']['files'].items()} != expected:
        raise ValueError('Preparation differs from pinned artifact versions')
    remaining = []
    for path, version in expected.items():
        file = Path(path)
        boundary = next(base for base in (locks.LOCK_ROOT,jobs.RUN_ROOT,sequences.SEQUENCE_ROOT)
                        if file.is_relative_to(base))
        raw = _read(file, boundary, optional=True)
        if file.parent==locks.LOCK_ROOT and file.name in ORDER:
            if raw is not None:
                if _hash(raw)!=version['sha256'] or raw!=_guard_bytes(preparation,file.name):
                    raise ValueError('Current owner/guard version changed; no retirement of other records')
                remaining.append(file.name)
        elif version.get('exists') is False:
            if raw is not None: raise ValueError('Unexpected new local restriction')
        elif raw is None or _hash(raw)!=version['sha256']:
            raise ValueError(f'Original artifact version changed: {file.name}')
    present = tuple(name for name in ORDER if name in remaining)
    if present not in (ORDER, ('sequence.json',), ()):
        raise ValueError('Contradictory partial removal order')
    if present!=ORDER and not protected:
        raise ValueError('Missing original guard without verified transaction barrier; no reconstruction')
    _archives(preparation, required=present!=ORDER)
    # Derive required identities from pinned bytes, not from editable role labels
    # or from the PID of the administrative caller (which may be an idle MCP server).
    originals = {Path(p).name:json.loads(v['content']) for p,v in preparation['snapshot']['files'].items()
                 if 'content' in v and Path(p).name in ORDER}
    identities = [originals['sequence.json']['coordinator'], originals['v2.json']['process']]
    identities.extend(json.loads(v['content'])['worker'] for p,v in preparation['snapshot']['files'].items()
                      if Path(p).name=='job.json' and 'content' in v)
    expected_processes = {json.dumps(p,sort_keys=True) for p in identities}
    if (None in identities or expected_processes!={json.dumps(p['registered'],sort_keys=True)
                                                for p in preparation['snapshot']['processes']}):
        raise ValueError('Preparation omitted or altered pertinent original process identities')
    checks = []
    for identity in identities:
        observed = locks.process_identity(identity['pid'])
        checks.append({'registered':identity,'observed':observed})
        if observed is not None: raise ValueError('Pertinent original worker/coordinator/executor alive or PID recycled')
    return {'remaining_guards':list(present),'process_checks':checks}


def _barrier_value(preparation, intent_raw):
    return {'kind':KIND,'owner_id':preparation['preparation_id'],'case_id':CASE_ID,
            'state':'UNCONFIRMED','preparation_sha256':_hash(_encoded(preparation)),
            'intent_sha256':_hash(intent_raw),'policy_sha256':POLICY_SHA256}


def _check_barrier(marker, preparation, intent_raw):
    if marker is not None and marker!=_barrier_value(preparation,intent_raw):
        raise ValueError('Different or damaged reconciliation/lifecycle transaction barrier')


def _intent():
    value = _json(ROOT/'intent.json',optional=True)
    if value is not None and (value.get('case_id')!=CASE_ID or value.get('policy_sha256')!=POLICY_SHA256):
        raise ValueError('Administrative intent identity mismatch')
    return value


def _result(intent):
    value = _json(ROOT/'result.json',optional=True)
    if value is not None and (intent is None or value.get('case_id')!=CASE_ID
                             or value.get('policy_sha256')!=POLICY_SHA256
                             or value.get('preparation_id')!=intent['preparation_id']
                             or value.get('preparation_sha256')!=intent['request']['preparation_sha256']
                             or value.get('intent_sha256')!=_hash(_read(ROOT/'intent.json',ROOT))
                             or value.get('status')!=RESULT):
        raise ValueError('Final administrative audit identity/hash mismatch')
    return value


def get_legacy_sequence_retirement(preparation_id=None):
    """Pure file lookup, including interrupted progress; never collects or resumes."""
    try:
        _policy()
        intent = _intent()
        if preparation_id is None:
            latest = _json(ROOT/'latest_preparation.json',optional=True)
            preparation_id = intent['preparation_id'] if intent else (latest or {}).get('preparation_id')
            if preparation_id is None:
                return {'status':'NOT_FOUND','case_id':CASE_ID,'message':'No preparation or application found; nothing initiated'}
        preparation, raw = _preparation(preparation_id)
        applies = intent is not None and intent['preparation_id']==preparation_id
        if applies and _hash(raw)!=intent['request']['preparation_sha256']:
            raise ValueError('Accepted preparation bytes changed')
        result = _result(intent) if applies else None
        if result is not None: _archives(preparation,required=True)
        marker = _marker()
        own_barrier = marker is not None and marker.get('kind')==KIND and marker.get('owner_id')==preparation_id
        remaining = [name for name in ORDER if (locks.LOCK_ROOT/name).exists()]
        if applies and own_barrier:
            _check_barrier(marker,preparation,_read(ROOT/'intent.json',ROOT))
        if applies and (result is None or own_barrier):
            _archives(preparation,required=len(remaining)!=len(ORDER))
            if tuple(remaining) not in (ORDER,('sequence.json',),()):
                raise ValueError('Contradictory partial retirement order')
            if len(remaining)!=len(ORDER) and not own_barrier:
                raise ValueError('Missing restrictions without transaction protection or final audit')
        status = ('RECOVERY_REQUIRED' if applies and (result is None or own_barrier) else RESULT if result
                  else preparation['status'])
        age = time.monotonic()-preparation['created_monotonic']
        expired = preparation['boot_id']!=audit.boot_id() or not 0<=age<=TTL_SECONDS
        return {'status':status,'case_id':CASE_ID,'preparation_id':preparation_id,'preparation_sha256':_hash(raw),
                'preparation_expired':expired,'preparation':{k:v for k,v in preparation.items() if k!='snapshot'},
                'authorization_recorded':applies,'intent_sha256':_hash(_read(ROOT/'intent.json',ROOT)) if applies else None,
                'accepted_request':intent['request'] if applies else None,
                'result':result,'transaction_barrier_present':own_barrier,'observed_remaining_guard_files':remaining,
                'protection_state':('TRANSACTION_BARRIER' if own_barrier else 'FINAL_RESULT_COMMITTED' if result
                                    else 'ORIGINAL_GUARDS_REMAIN' if len(remaining)==len(ORDER) else 'NOT_CONFIRMED'),
                'other_case_preparation_claimed':intent['preparation_id'] if intent and not applies else None,
                'paths':{'preparation':str(ROOT/'preparations'/preparation_id/'preparation.json'),
                         'intent':str(ROOT/'intent.json'),'result':str(ROOT/'result.json'),
                         'journal':str(ROOT/'journal.json'),'history':str(_history(preparation))},
                'historical_environment_termination':'UNKNOWN','flight_authorized':False,
                'application_enabled':False,'recovery_enabled':False,
                'operator_confirmation_verified':False,
                'authorization_provenance':'UNVERIFIED_AGENT_DECLARATION' if applies else None,
                'message':'Read-only audit. No new observation, application, recovery, release or consent. accepted_request is historical agent input, not verified operator consent or a recovery instruction. Mutating application/recovery is disabled. Final result is historical; any current/new guard is unaffected.'}
    except Exception as exc:
        return {'status':'ERROR','case_id':CASE_ID,'reasons':[f'{type(exc).__name__}: {exc}'],'flight_authorized':False}


def prepare_legacy_sequence_retirement(sequence_id=CASE_ID):
    """Operational read-only preparation for this exact case; separate audit only."""
    identifier = None
    try:
        if sequence_id!=CASE_ID: raise ValueError('Only the pinned c6eeb645 case is supported')
        policy = _policy()
        with _exclusive():
            if _intent() is not None:
                return get_legacy_sequence_retirement() | {'message':'Case already has a durable agent declaration/result; query it. No new preparation or recovery; mutating application is disabled.'}
            started = time.monotonic()
            before = _snapshot(policy)
            environment = _environment(policy)
            if _snapshot(policy)!=before: raise ValueError('Owners, versions or processes changed during preparation')
            identifier = str(uuid4())
            preparation = {'schema_version':1,'case_id':CASE_ID,'preparation_id':identifier,'policy_sha256':POLICY_SHA256,
                'status':'AWAITING_EXPLICIT_ADMINISTRATIVE_AUTHORIZATION','created_at':locks.utc_now(),
                'created_monotonic':started,'boot_id':audit.boot_id(),'ttl_seconds':TTL_SECONDS,
                'snapshot':before,'summary':audit.inspection_summary(before,{}),'environment':environment,
                'historical_environment_binding':'UNVERIFIED','historical_clock_comparability':'UNKNOWN',
                'original_environment_termination':'UNKNOWN','ground_contact':'NOT_ASSERTED',
                'acceptance_required':'Retire only the exact local reservations despite unresolved history; no assertion that unknown facts are true',
                'reservations_changed':False,'flight_authorized':False}
            preparation['summary']['independent_ground_confirmation']='NOT_APPLICABLE_ADMINISTRATIVE_RETIREMENT'
            _mkdir(ROOT/'preparations'/identifier)
            _write_once(ROOT/'preparations'/identifier/'preparation.json',_encoded(preparation))
            locks.atomic_json(ROOT/'latest_preparation.json',{'preparation_id':identifier})
            return get_legacy_sequence_retirement(identifier)
    except Exception as exc:
        return {'status':'BLOCKED','case_id':CASE_ID,'preparation_id':identifier,'reasons':[f'{type(exc).__name__}: {exc}'],
                'reservations_changed':False,'flight_authorized':False}


def apply_legacy_sequence_retirement(preparation_id, preparation_sha256, authorization):
    """Blocked without a verified human channel; completed replay is read-only history."""
    phase = 'VALIDATION'
    preparation = None
    try:
        policy = _policy()
        preparation, raw = _preparation(preparation_id)
        if _hash(raw)!=preparation_sha256: raise ValueError('Preparation hash mismatch')
        # Preserve legacy artifacts/contracts: reading a completed result never
        # upgrades its old agent declaration into verified human authorization.
        intent = _intent()
        if intent is not None and intent['preparation_id']==preparation_id:
            result = _result(intent)
            marker = _marker()
            if result is not None and (marker is None or marker.get('owner_id')!=preparation_id):
                return get_legacy_sequence_retirement(preparation_id) | {
                    'replayed':True,'application_performed':False,'message':'Existing historical result only; no application repeated and no operator authorization authenticated.'}
        claim = _bound_authorization(preparation_id, preparation_sha256, authorization)
        # No observations, mutex creation, audit writes or transaction mutation
        # before this barrier. A durable old intent is not human confirmation.
        _fresh(preparation)
        _require_operator_confirmation(preparation_id, preparation_sha256, claim)
        request = {'preparation_id':preparation_id,'preparation_sha256':preparation_sha256,'authorization':claim}
        with _exclusive():
            try:
                if _read(ROOT/'preparations'/preparation_id/'preparation.json',ROOT)!=raw:
                    raise ValueError('Preparation changed before application')
                intent = _intent()
                if intent is not None and intent['request']!=request:
                    raise ValueError('Different preparation/authorization; the one-case intent cannot be reused')
                marker = _marker()
                if intent is not None:
                    intent_raw = _read(ROOT/'intent.json',ROOT)
                    result = _result(intent)
                    if result is not None and (marker is None or marker.get('owner_id')!=preparation_id):
                        return get_legacy_sequence_retirement(preparation_id) | {'replayed':True}
                    _check_barrier(marker,preparation,intent_raw)
                else:
                    if marker is not None: raise ValueError('Another reconciliation barrier exists')
                    _fresh(preparation)
                phase = 'REVALIDATION'
                state = _verify_recovery(policy,preparation,protected=marker is not None)
                environment = _environment(policy,preparation['environment'])
                if _verify_recovery(policy,preparation,protected=marker is not None)!=state:
                    raise ValueError('Files or pertinent processes changed during revalidation')
                if intent is None:
                    _fresh(preparation)
                    actor = locks.process_identity()
                    if actor is None: raise ValueError('Cannot identify administrative caller process')
                    intent = {'schema_version':1,'case_id':CASE_ID,'preparation_id':preparation_id,
                        'policy_sha256':POLICY_SHA256,'request':request,'accepted_at':locks.utc_now(),
                        'process':actor,'environment':environment,
                        'scope':'Only these pinned local restrictions, accepting historical uncertainty',
                        'historical_environment_termination':'UNKNOWN','flight_authorized':False}
                    phase = 'INTENT'
                    _write_once(ROOT/'intent.json',_encoded(intent))
                    intent_raw = _read(ROOT/'intent.json',ROOT)
                phase = 'BARRIER'
                _write_once(ROOT/'intent.json',intent_raw)  # re-fsync a previously interrupted publication
                _write_once(locks.LOCK_ROOT/'reconciliation.json',_encoded(_barrier_value(preparation,intent_raw)))
                phase = 'ARCHIVING'
                _mkdir(_history(preparation))
                for name in ORDER: _write_once(_history(preparation)/name,_guard_bytes(preparation,name))
                _archives(preparation,required=True)
                # Final fresh metadata after archive I/O; no lifecycle can interleave
                # under these mutexes. External/unupdated clients are outside scope.
                phase = 'PRE_REMOVAL_REVALIDATION'
                _environment(policy,environment)
                _verify_recovery(policy,preparation,protected=True)
                if _read(ROOT/'preparations'/preparation_id/'preparation.json',ROOT)!=raw:
                    raise ValueError('Preparation changed during revalidation')
                if _read(ROOT/'intent.json',ROOT)!=intent_raw: raise ValueError('Immutable intent changed')
                for name in ORDER:
                    phase = 'REMOVING_'+name
                    _check_barrier(_marker(),preparation,intent_raw)
                    progress = _verify_recovery(policy,preparation,protected=True)
                    locks.atomic_json(ROOT/'journal.json',{'phase':phase,'at':locks.utc_now(),
                        'process':locks.process_identity(),'preparation_id':preparation_id,**progress})
                    original = locks.LOCK_ROOT/name
                    if original.exists():
                        original.unlink()
                        _sync(locks.LOCK_ROOT)
                phase = 'FINAL_RESULT'
                if _verify_recovery(policy,preparation,protected=True)['remaining_guards']:
                    raise ValueError('Some pinned local guard remains')
                result = _result(intent)
                if result is None:
                    result = {'status':RESULT,'case_id':CASE_ID,'preparation_id':preparation_id,
                        'preparation_sha256':preparation_sha256,'intent_sha256':_hash(intent_raw),
                        'policy_sha256':POLICY_SHA256,'finished_at':locks.utc_now(),
                        'archived_originals':{name:{'path':str(_history(preparation)/name),
                            'sha256':_hash(_guard_bytes(preparation,name))} for name in ORDER},
                        'historical_reports_modified':False,'historical_environment_binding':'UNVERIFIED',
                        'historical_clock_comparability':'UNKNOWN','original_environment_termination':'UNKNOWN',
                        'ground_contact':'NOT_ASSERTED','flight_authorized':False}
                _write_once(ROOT/'result.json',_encoded(result))  # durable even after an interrupted final publication
                phase = 'BARRIER_REMOVAL'
                _check_barrier(_marker(),preparation,intent_raw)
                (locks.LOCK_ROOT/'reconciliation.json').unlink()
                _sync(locks.LOCK_ROOT)
                # No persistence required after this: final decision and all guard
                # removals were fsynced BEFORE removing the protective barrier.
                return get_legacy_sequence_retirement(preparation_id) | {'replayed':False}
            except Exception as exc:
                protection_error = None
                # If an error happens at final barrier fsync, restore protection
                # when possible. Durable result always precedes barrier removal.
                if phase=='BARRIER_REMOVAL' and _marker() is None:
                    try: _write_once(locks.LOCK_ROOT/'reconciliation.json',_encoded(_barrier_value(preparation,intent_raw)))
                    except Exception as error: protection_error = f'{type(error).__name__}: {error}'
                outcome = {'status':'BLOCKED','case_id':CASE_ID,'preparation_id':preparation_id,
                    'phase':phase,'reasons':[f'{type(exc).__name__}: {exc}'],'flight_authorized':False,
                    'error_code':getattr(exc,'code','APPLICATION_BLOCKED'),
                    'recovery_required':_intent() is not None,'protection_error':protection_error}
                try:
                    _mkdir(ROOT/'attempts')
                    locks.atomic_json(ROOT/'attempts'/(str(uuid4())+'.json'),{**outcome,'at':locks.utc_now()})
                except Exception as error: outcome['audit_error']=f'{type(error).__name__}: {error}'
                return outcome
    except Exception as exc:
        return {'status':'BLOCKED','case_id':CASE_ID,'preparation_id':preparation_id,
                'preparation_sha256':preparation_sha256,
                'phase':phase,'reasons':[f'{type(exc).__name__}: {exc}'],'flight_authorized':False,
                'error_code':getattr(exc,'code','APPLICATION_BLOCKED'),
                'application_enabled':False,'operator_confirmation_verified':False,
                'automatic_retry_allowed':False,'new_preparation_authorized':False}
