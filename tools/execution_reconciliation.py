"""Explicit inspect/apply, never a force unlock or an execution/resume endpoint.

Inspection reads runtime state and telemetry and writes only a separate audit.
Application is bound to exact inspected bytes, boot/monotonic expiry, dead owners,
and either new telemetry + independent ground confirmation, or verified termination
of the exact simulated environment. Neither path repairs a historical result.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
import time
from uuid import uuid4
from typing import Literal
from pydantic import BaseModel, Field


from tools import vehicle_execution_lock as locks
from tools import virtual_preflight_jobs as jobs
from tools import preflight_sequences as sequences
from tools.reconciliation_observer import collect_observations
from tools.reconciliation_environment import inspect_environment, environment_identity, stopped_reasons


class GroundConfirmation(BaseModel):
    vehicle: Literal["v1", "v2"]
    source: Literal["OPERATOR_VISUAL"]
    on_ground: Literal[True]
    statement: str = Field(min_length=1)
    observed_at_utc: str


class LegacyEnvironmentConfirmation(BaseModel):
    """Administrative declaration, never authentication of historical Docker state."""
    model_config = {'extra':'forbid'}
    source: Literal['OPERATOR_ENVIRONMENT_REVIEW']
    engine_id: str = Field(min_length=1)
    container_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    continuous_project_environment: Literal[True] = Field(description=(
        'Operator reviewed continuity from original execution to the retained inspection: '
        'no known Docker context/deployment switch, container substitution, metadata clone/restore '
        'or workspace move to another worker host while previous workers could remain alive. '
        'Cannot be inferred from host boot_id or matching names.'))
    wall_clock_comparison_supported: Literal[True] = Field(description=(
        'Operator has a stated basis for comparing recorded host UTC and Docker daemon wall timestamps; '
        'not ROS/simulation clocks. If unknown, do not declare true.'))
    statement: str = Field(min_length=1, description='Explain the actual continuity and clock evidence reviewed, without inventing historical IDs.')

INSPECTION_ROOT = locks.PROJECT_ROOT / "missions/generated/reconciliation_inspections"
EVIDENCE_TTL_SECONDS = 120
GUARD_NAMES = ("sequence.json", "v1.json", "v2.json", "v3.json", "lifecycle.json")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _inspection_bytes(inspection_id):
    root = INSPECTION_ROOT/jobs.valid_run_id(inspection_id)
    path = root/'inspection.json'
    if root.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(INSPECTION_ROOT.resolve()):
        raise ValueError('Inspection path escapes fixed root or uses a symlink')
    return jobs.read_mission_input(path)


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def _file(root, relative, files, *, required=True):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Reconciliation artifact path escapes fixed root")
    try:
        content = jobs.read_mission_input(path)
    except FileNotFoundError:
        if required:
            raise
        files[str(path)] = {"exists": False}
        return None
    files[str(path)] = {"sha256": digest(content), "content": content.decode("utf-8")}
    return json.loads(content)


def capture(target_id):
    """Exact records + process identities; does not change a job or restriction."""
    jobs.valid_run_id(target_id)
    if (locks.LOCK_ROOT/'reconciliation.json').exists():
        raise ValueError('Unfinished reconciliation transaction; inspect its audit, never resume implicitly')
    files, guards = {}, {}
    for name in GUARD_NAMES:
        value = _file(locks.LOCK_ROOT, name, files, required=False)
        if value is not None:
            guards[name] = value
        elif name == "v3.json":
            # Preserve legacy snapshot/version contracts when no rover guard exists.
            # A later rover admission is still caught by recapture under exclusion.
            files.pop(str(locks.LOCK_ROOT / name), None)
    if "v3.json" in guards:
        raise ValueError("Rover reservation present: drone ground/landing reconciliation is incompatible; retain restrictions")
    if not guards or target_id not in {v.get("owner_id") for v in guards.values()}:
        raise ValueError("Target does not own a current reservation; no reconstruction")
    if 'lifecycle.json' in guards and any(name in guards for name in ('v1.json','v2.json','sequence.json')):
        raise ValueError('Conflicting lifecycle/flight owners; no generic reconciliation')
    # Existing validators catch contradictory guards before inspecting for release.
    locks.restriction()
    responsible = []
    audit_processes = []
    def process(value, role, required=True):
        if value is None:
            if required:
                raise ValueError(f"Missing process identity: {role}")
            return
        if (not isinstance(value, dict) or set(value) != {"pid", "start_ticks", "boot_id"}
                or type(value["pid"]) is not int or type(value["start_ticks"]) is not int):
            raise ValueError(f"Invalid process identity: {role}")
        observed = locks.process_identity(value["pid"])
        item = {"role": role, "registered": value, "observed": observed}
        (responsible if required else audit_processes).append(item)
    for name, guard in guards.items():
        owner = jobs.valid_run_id(guard["owner_id"])
        if name == "sequence.json":
            process(guard.get("coordinator"), "sequence coordinator")
            process(guard.get("process"), "sequence admission", required=False)
            root = sequences.directory(owner)
            op = _file(root, "operation.json", files)
            plan = _file(root, "plan.json", files)
            if (op.get("sequence_id") != owner or plan.get("sequence_id") != owner
                    or digest(files[str(root/'plan.json')]["content"].encode()) != op.get("plan_sha256")
                    or op.get("plan_sha256") != guard.get("plan_sha256")):
                raise ValueError("Sequence identity/hash contradiction")
            expected_children = [{"owner_id": c["run_id"], "vehicle": c["vehicle_selection"]["simulated_vehicle"],
                                  "input_sha256": c["mission_sha256"]} for c in plan["children"]]
            if (guard.get("children") != expected_children or guard.get("coordinator") != op.get("coordinator")
                    or len(op.get("children", [])) != 2):
                raise ValueError("Sequence guard/operation child or coordinator contradiction")
            for index, child in enumerate(plan["children"]):
                mission = _file(root, f"mission_{index+1}.json", files)
                if digest(files[str(root/f'mission_{index+1}.json')]["content"].encode()) != child["mission_sha256"]:
                    raise ValueError("Sequence snapshot hash contradiction")
                job = _capture_job(child["run_id"], files, process)
                if (job.get("sequence_id") != owner or job.get("sequence_index") != index
                        or job.get("input_sha256") != child["mission_sha256"]):
                    raise ValueError("Child admission differs from ordered sequence")
                saved_report = op["children"][index].get("report_sha256")
                report_file = files[str(jobs.run_directory(child["run_id"])/"report.json")]
                if saved_report is not None and report_file.get("sha256") != saved_report:
                    raise ValueError("Previously accepted child report changed")
        elif name in {"v1.json", "v2.json"}:
            process(guard.get("process"), f"{name} executor/owner")
            if (jobs.run_directory(owner) / "job.json").exists():
                _capture_job(owner, files, process)
            elif guard.get("actor") not in {"synchronous_executor", "synchronous_preflight"}:
                raise ValueError("Missing asynchronous job; no reconstruction or unlock")
        else:
            process(guard.get("process"), "lifecycle owner")
    return {"guards": guards, "files": files, "processes": responsible,
            "admission_processes": audit_processes}


def _capture_job(run_id, files, process):
    root = jobs.run_directory(run_id)
    job = _file(root, "job.json", files)
    if job.get("run_id") != run_id:
        raise ValueError("Job identity contradiction")
    content = _file(root, "input.json", files)
    if digest(files[str(root/'input.json')]["content"].encode()) != job["input_sha256"]:
        raise ValueError("Admission input hash contradiction")
    if job.get("worker") is not None:
        process(job["worker"], f"worker {run_id}")
    elif job.get("job_state") != "QUEUED":
        raise ValueError("Missing worker identity; cannot confirm executor termination")
    jobs.job_vehicle_selection(job, root)  # new-format input/selection and legacy binding verification
    report = _file(root, "report.json", files, required=False)
    if report is not None:
        _file(root, "mission.json", files)
        if (report.get("run_id") != run_id or report.get("mission_sha256") != job["input_sha256"]
                or digest(files[str(root/'mission.json')]["content"].encode()) != job["input_sha256"]):
            raise ValueError("Report/snapshot identity contradiction")
    return job


def telemetry_reasons(observation):
    """Strict local receipt/progression/stability checks, never a ground-contact claim."""
    reasons = []
    if not isinstance(observation, dict):
        return ["Missing observation object"]
    if (not isinstance(observation.get("collection_wall_seconds"), (int,float))
            or not 1 <= observation["collection_wall_seconds"] <= 35):
        return ["Missing/invalid bounded collection duration"]
    if observation.get("subscription") != "NEW_VOLATILE":
        reasons.append("Missing new volatile collection evidence")
    for vehicle in ("v1", "v2"):
        try:
            for kind in ("status", "position"):
                samples = observation["samples"][vehicle][kind]
                if len(samples) < 3:
                    raise ValueError("need >=3 samples per stream")
                receipts = [s["receipt_elapsed_seconds"] for s in samples]
                stamps = [s["message"]["header"]["stamp"]["sec"] + s["message"]["header"]["stamp"]["nanosec"]/1e9 for s in samples]
                if (not all(math.isfinite(x) for x in receipts+stamps)
                        or receipts[0] < 0 or receipts[-1] > observation["collection_wall_seconds"]
                        or observation["collection_wall_seconds"]-receipts[-1] > 5
                        or not all(b>a for a,b in zip(receipts,receipts[1:]))
                        or not all(b>a for a,b in zip(stamps,stamps[1:]))):
                    raise ValueError("nonprogressing/invalid stamps or receipts")
                if kind == "status":
                    if any(s["message"]["armed"] is not False or s["message"]["flying"] is not False
                           or s["message"].get("failsafe") != [] for s in samples):
                        raise ValueError("armed/flying/failsafe not safe")
                else:
                    values = [s["message"]["pose"]["position"] for s in samples]
                    for key, delta in (("latitude", 0.000002), ("longitude", 0.000002), ("altitude", 0.20)):
                        axis = [s[key] for s in values]
                        if not all(math.isfinite(x) for x in axis) or max(axis)-min(axis)>delta:
                            raise ValueError("position not stable in observation window")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            reasons.append(f"{vehicle}: {exc}")
    return reasons


def _process_reasons(snapshot):
    return [f"Process alive or PID recycled: {p['role']}" for p in snapshot["processes"] if p["observed"] is not None]


def inspection_summary(snapshot, observation):
    """Reviewable ownership/version/stream evidence without full duplicated files."""
    telemetry = {}
    for vehicle in ("v1", "v2"):
        values = observation.get('samples', {}).get(vehicle, {})
        telemetry[vehicle] = {}
        for kind in ('status', 'position'):
            samples = values.get(kind, [])
            telemetry[vehicle][kind] = {'count':len(samples), 'latest':samples[-1] if samples else None}
    return {'reservations':snapshot['guards'], 'process_checks':snapshot['processes'],
            'admission_process_checks':snapshot['admission_processes'],
            'artifact_versions':{path:{k:v for k,v in value.items() if k!='content'}
                                 for path,value in snapshot['files'].items()},
            'telemetry':telemetry, 'absolute_generation_age_known':False,
            'independent_ground_confirmation':'REQUIRED_SEPARATELY'}


def _identity_reference(target_id, snapshot):
    """Use only retained project audits for this owner, never an arbitrary ID/path.

    Legacy exec errors supply a full identity reference ONLY, not proof of stopped
    state, daemon history, flight incarnation or landing. Fresh Docker metadata is
    still mandatory. New active-environment audits carry a stronger full binding.
    """
    references = []
    for root in sorted(INSPECTION_ROOT.glob('*')) if INSPECTION_ROOT.exists() else ():
        if root.is_symlink() or not root.is_dir():
            continue
        try:
            jobs.valid_run_id(root.name)
            raw = _inspection_bytes(root.name)
            value = json.loads(raw)
            if value.get('target_id') != target_id or value.get('inspection_id') != root.name:
                continue
            reference = {'inspection_id':root.name, 'sha256':digest(raw), 'identity':None,
                         'observed_at':value.get('created_at'), 'original_execution_environment_bound':False}
            env = value.get('environment', {})
            if env.get('status') == 'ACTIVE' and (value.get('snapshot') or {}).get('guards') == snapshot['guards']:
                reference.update(kind='ACTIVE_ENVIRONMENT_AUDIT', identity=environment_identity(env),
                                 historical_engine_identity_known=True)
            elif value.get('status') == 'BLOCKED' and value.get('exception_type') == 'RuntimeError' and value.get('reservations_changed') is False:
                identifiers = set(re.findall(r'Error response from daemon: container ([0-9a-f]{64}) is not running(?:\n|$)', '\n'.join(value.get('reasons', []))))
                if len(identifiers) == 1:
                    reference.update(kind='LEGACY_FAILED_INSPECTION_CONTAINER_ID',
                                     identity={'container_id':identifiers.pop()}, historical_engine_identity_known=False,
                                     limitation='Full ID addressed by a prior inspection of this owner; no historical daemon/incarnation or termination evidence')
            if reference['identity'] is not None:
                references.append(reference)
        except (ValueError, TypeError, OSError):
            continue
    if not references:
        return None
    if len({r['identity']['container_id'] for r in references}) != 1:
        raise ValueError('Conflicting retained container identity references; no automatic choice')
    full = [r for r in references if r['kind']=='ACTIVE_ENVIRONMENT_AUDIT']
    bindings = {json.dumps({**{k:v for k,v in r['identity'].items() if k!='state'},
                            'started_at':r['identity']['state']['StartedAt']}, sort_keys=True) for r in full}
    if len(bindings)>1:
        raise ValueError('Conflicting retained engine/incarnation bindings; no automatic choice')
    # Prefer a full binding; never let a weaker legacy hint override a known daemon/incarnation.
    return next((r for r in references if r['kind']=='ACTIVE_ENVIRONMENT_AUDIT'), references[-1])


def _environment_reasons(environment, reference):
    if environment.get('status') not in {'ACTIVE', 'STOPPED'}:
        return [f"Environment {environment.get('status', 'UNKNOWN')}: {environment.get('reasons', [])}"]
    if reference is not None:
        expected = reference['identity']
        if any(environment.get(k) != v for k,v in expected.items() if k != 'state'):
            return ['Environment REPLACED or incarnation changed relative to retained identity reference']
        # A currently exited exact container terminates *all* its prior incarnations.
        # Do not demand impossible telemetry for an older incarnation. Application
        # still requires the current StartedAt/FinishedAt/Pid to match inspection.
        if (environment['status']=='ACTIVE' and expected.get('state')
                and expected['state'].get('StartedAt') != environment.get('state', {}).get('StartedAt')):
            return ['Environment incarnation restarted since retained active inspection; no automatic identity substitution']
    if environment['status'] == 'STOPPED':
        if reference is None:
            return ['STOPPED container has no prior identity binding to this reservation owner; name/state alone is insufficient']
        return stopped_reasons(environment)
    return []


def _check_reference(reference):
    if reference is not None:
        if digest(_inspection_bytes(reference['inspection_id'])) != reference['sha256']:
            raise ValueError('Prior environment identity reference changed; inspect again')


def _wall_time(value):
    if not isinstance(value, str):
        raise ValueError('Missing wall timestamp')
    timestamp = datetime.fromisoformat(value.replace('Z','+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('Wall timestamp needs explicit timezone')
    return timestamp


def _binding_review(snapshot, environment, reference):
    """Posthoc identity is not an original execution binding, even with engine ID.

    Chronology is a consistency check conditional on comparable wall clocks. It
    does not prove endpoint continuity or absence of a metadata clone. Retain
    unknowns and require a separate, reviewable operator declaration for legacy.
    """
    result = {'original_execution_environment_bound':False,
              'requires_legacy_environment_confirmation':True,
              'association_source':'POSTHOC_IDENTITY_REFERENCE',
              'assumptions_not_machine_verified':['Docker deployment/selector continuity since original execution',
                                                   'No container substitution or metadata clone/restore',
                                                   'Same worker host installation; no unverified workspace relocation',
                                                   'Recorded host and Docker wall clocks comparable'],
              'reasons':[], 'original_activity':[]}
    try:
        starts, ends = [], []
        for name, retained in snapshot['files'].items():
            if Path(name).name not in {'job.json','report.json'} or 'content' not in retained:
                continue
            value = json.loads(retained['content'])
            field = 'execution_started_at' if value.get('execution_started_at') else 'started_at'
            if value.get(field):
                start = _wall_time(value[field]); starts.append(start)
                result['original_activity'].append({'path':name,'sha256':retained['sha256'],
                                                    'field':field,'value':value[field]})
            for key in ('execution_finished_at','finished_at'):
                if value.get(key): ends.append(_wall_time(value[key]))
        if not starts:
            raise ValueError('Missing original job/report start timestamps; cannot check legacy chronology')
        if reference is None:
            raise ValueError('Missing prior identity reference')
        original = json.loads(_inspection_bytes(reference['inspection_id']))
        created = _wall_time(environment['created_at'])
        stopped = _wall_time(environment['state']['FinishedAt'])
        observed = _wall_time(original.get('created_at'))
        result['chronology'] = {'earliest_activity_at':min(starts).isoformat(),
            'latest_activity_start_at':max(starts).isoformat(),
            'latest_recorded_finish_at':max(ends).isoformat() if ends else None,
            'container_created_before_activity':created<=min(starts),
            'container_stopped_after_activity_began':stopped>=min(starts),
            'identity_reference_after_activity_started':observed>=max(starts),
            'stop_covers_recorded_finish':stopped>=max(ends) if ends else None,
            'clock_basis':'CONDITIONAL_ON_OPERATOR_REVIEW_OF_WALL_CLOCKS'}
        # An ERROR may be recorded after a Docker exit/timeout. Do not require the
        # container to remain running until job/report postprocessing has ended.
        for key in ('container_created_before_activity','container_stopped_after_activity_began',
                    'identity_reference_after_activity_started'):
            if not result['chronology'][key]:
                result['reasons'].append(f'Legacy chronology contradiction: {key}')
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result['reasons'].append(f'Legacy association evidence incomplete: {exc}')
    result['status'] = 'BLOCKED' if result['reasons'] else 'AWAITING_OPERATOR_CONTINUITY_REVIEW'
    return result


def _confirm_legacy_environment(value, environment, review):
    if review['reasons']:
        raise ValueError(f"Legacy association blocked: {review['reasons']}")
    if value is None:
        raise ValueError('Posthoc identity does not bind original execution: explicit legacy_environment_confirmation required')
    claim = LegacyEnvironmentConfirmation.model_validate(value).model_dump()
    if (claim['engine_id']!=environment.get('engine_id') or claim['container_id']!=environment.get('container_id')
            or not claim['statement'].strip()):
        raise ValueError('Legacy environment declaration does not match reviewed identity or has no supporting statement')
    return {'source':'UNVERIFIED_OPERATOR_DECLARATION_VIA_AGENT', 'confirmation':claim,
            'review':review, 'original_execution_environment_bound':False,
            'historical_engine_identity_reconstructed':False}


def _evidence_validity(record):
    # Old failed collectors never gathered evidence: absence is not expiry.
    collected = record.get('eligibility_evidence_collected', bool(record.get('observation')))
    if not collected:
        return {'evidence_state':'NOT_COLLECTED', 'evidence_expired':None, 'remaining_seconds':None,
                'application_eligible':False}
    age = time.monotonic()-record['created_monotonic'] if 'created_monotonic' in record else None
    expired = record.get('boot_id') != boot_id() or age is None or not 0<=age<=EVIDENCE_TTL_SECONDS
    return {'evidence_state':'EXPIRED' if expired else 'COLLECTED', 'evidence_expired':expired,
            'remaining_seconds':max(0.,EVIDENCE_TTL_SECONDS-age) if not expired else 0.,
            'requires_legacy_environment_confirmation':record.get('reconciliation_basis')=='ENVIRONMENT_TERMINATED',
            'application_eligible':not expired and record.get('reconciliation_basis')!='ENVIRONMENT_TERMINATED' and record.get('status') in {
                'AWAITING_EXPLICIT_GROUND_CONFIRMATION', 'AWAITING_TERMINATION_RECONCILIATION_AUTHORIZATION'}}


def get_execution_reconciliation(inspection_id):
    """Read retained audit after reload/lost response; never collect, apply or resume."""
    try:
        root = INSPECTION_ROOT / jobs.valid_run_id(inspection_id)
        record = jobs.read_json(root/'inspection.json', INSPECTION_ROOT)
        if record is None:
            return {"status": "NOT_FOUND", "inspection_id": inspection_id}
        if record.get('inspection_id') != inspection_id:
            raise ValueError('Inspection identity mismatch')
        application = jobs.read_json(root/'application.json', INSPECTION_ROOT)
        if application is not None and (application.get('inspection_id') != inspection_id
                or application.get('inspection_sha256') != digest((root/'inspection.json').read_bytes())):
            raise ValueError('Application/inspection identity or hash mismatch')
        return {k:v for k,v in record.items() if k not in {'snapshot','observation'}} | {
            'inspection_sha256': digest((root/'inspection.json').read_bytes()),
            **_evidence_validity(record),
            'telemetry_collection':record.get('telemetry_collection', 'COLLECTED' if record.get('observation') else 'NOT_COLLECTED'),
            'application': ({k:application.get(k) for k in ('status','started_at','finished_at','transition',
                                                          'historical_reports_modified','flight_authorized','reconciliation_basis','ground_contact',
                                                          'environment_association')}
                            if application else None),
            'paths': {'inspection':str(root/'inspection.json'),'application':str(root/'application.json')},
            'message': 'Audit only. No fresh telemetry, release, consent or continuation.'}
    except (ValueError, OSError, TypeError, KeyError) as exc:
        return {'status':'ERROR','reasons':[str(exc)]}


def inspect_execution_reconciliation(target_id):
    """Fresh read-only inspection; persist useful partial context even on failure."""
    started_monotonic = time.monotonic()
    before, observation, environment, reference, binding_review = None, {}, {}, None, None
    reasons, telemetry_collection, stage = [], 'NOT_COLLECTED', 'VALIDATE_TARGET'
    try:
        jobs.valid_run_id(target_id)
        with locks.file_mutex(locks.LOCK_ROOT / "v1.execution.lock", blocking=False):
            with locks.file_mutex(locks.LOCK_ROOT / "registry.lock", blocking=False):
                stage = 'CAPTURE_OWNERS_AND_PROCESSES'
                before = capture(target_id)
                reasons = _process_reasons(before)
                if not reasons:
                    stage = 'ENVIRONMENT_METADATA'
                    environment = inspect_environment()
                    reference = _identity_reference(target_id, before)
                    reasons.extend(_environment_reasons(environment, reference))
                    if not reasons and environment.get('status')=='STOPPED':
                        binding_review = _binding_review(before, environment, reference)
                        reasons.extend(binding_review['reasons'])
                    if not reasons and environment['status'] == 'ACTIVE':
                        stage = 'TELEMETRY_COLLECTION'
                        observation = collect_observations()
                        telemetry_collection = 'COLLECTED'
                        reasons.extend(telemetry_reasons(observation))
                    elif environment.get('status') == 'STOPPED':
                        telemetry_collection = 'NOT_APPLICABLE_ENVIRONMENT_STOPPED'
                stage = 'RECHECK_OWNERS_AND_PROCESSES'
                if capture(target_id) != before:
                    raise ValueError("State changed during inspection")
    except Exception as exc:
        reasons.append(f"{stage}: {type(exc).__name__}: {exc}")
        if stage == 'TELEMETRY_COLLECTION':
            telemetry_collection = 'FAILED_NO_OBSERVATION'
    # Persist outside the short-held mutexes. Application always revalidates exact
    # versions and timestamps under the same exclusion before any guard removal.
    try:
        jobs.valid_run_id(target_id)
        inspection_id = str(uuid4())
        root = INSPECTION_ROOT / inspection_id
        root.mkdir(parents=True)
        summary = inspection_summary(before, observation) if before is not None else {
            'reservations':{}, 'process_checks':[], 'artifact_versions':{},
            'ownership_capture':'UNAVAILABLE', 'independent_ground_confirmation':'UNDETERMINED'}
        # If coherent capture failed, retain identifiable guard bytes as UNVERIFIED
        # context, never as eligible release evidence.
        if before is None:
            for name in GUARD_NAMES:
                try:
                    value = jobs.read_json(locks.LOCK_ROOT/name, locks.LOCK_ROOT)
                    if value is not None:
                        summary['reservations'][name] = value
                except (OSError, ValueError, TypeError) as exc:
                    summary.setdefault('ownership_errors', []).append(f'{name}: {exc}')
        basis = ('ENVIRONMENT_TERMINATED' if environment.get('status') == 'STOPPED'
                 else 'ACTIVE_TELEMETRY_AND_GROUND' if environment.get('status') == 'ACTIVE' else None)
        association_reasons = _environment_reasons(environment, reference)
        environment_assessment = ('REPLACED_OR_RESTARTED' if any('REPLACED' in r or 'incarnation restarted' in r for r in association_reasons)
                                  else environment.get('status', 'UNKNOWN'))
        collected = bool(observation) or (basis == 'ENVIRONMENT_TERMINATED' and reference is not None and not _environment_reasons(environment, reference))
        summary['independent_ground_confirmation'] = ('NOT_APPLICABLE_ENVIRONMENT_TERMINATED' if basis=='ENVIRONMENT_TERMINATED'
                                                      else 'REQUIRED_SEPARATELY' if basis else 'UNDETERMINED')
        if not reasons and not collected:
            reasons.append('No sufficient environment or telemetry evidence collected')
        status = ('BLOCKED' if reasons else 'AWAITING_LEGACY_ENVIRONMENT_REVIEW' if basis=='ENVIRONMENT_TERMINATED'
                  else 'AWAITING_EXPLICIT_GROUND_CONFIRMATION')
        record = {'schema_version':2, 'inspection_id':inspection_id, 'target_id':target_id,
                  'created_at':locks.utc_now(), 'boot_id':boot_id(), 'created_monotonic':started_monotonic,
                  'ttl_seconds':EVIDENCE_TTL_SECONDS, 'snapshot':before, 'observation':observation,
                  'summary':summary, 'environment':environment, 'identity_reference':reference,
                  'binding_review':binding_review,
                  'environment_assessment':environment_assessment,
                  'reconciliation_basis':basis, 'status':status, 'reasons':reasons,
                  'telemetry_collection':telemetry_collection, 'eligibility_evidence_collected':collected,
                  'environment_collection':('COLLECTED' if environment.get('status') in {'ACTIVE','STOPPED'}
                                            else 'PARTIAL' if environment else 'NOT_COLLECTED'),
                  'unknown_fields':(['owners_or_versions_or_processes'] if before is None else [])
                                   + environment.get('unknown_fields', ['environment_identity_and_state'] if not environment else [])
                                   + ([] if observation or basis=='ENVIRONMENT_TERMINATED' else ['telemetry'])
                                   + (['original_execution_environment_binding','host_daemon_wall_clock_continuity'] if basis=='ENVIRONMENT_TERMINATED' else []),
                  'generation_freshness':'NOT_APPLICABLE_ENVIRONMENT_TERMINATED' if basis=='ENVIRONMENT_TERMINATED' else 'ABSOLUTE_AGE_UNKNOWN',
                  'ground_contact':'NOT_ASSERTED', 'reservations_changed':False,
                  'no_flight_or_hardware_consent':True}
        record['applicability'] = {'basis':basis, 'requires_explicit_authorization':True,
                                   'requires_ground_confirmations':basis=='ACTIVE_TELEMETRY_AND_GROUND',
                                   'requires_legacy_environment_confirmation':basis=='ENVIRONMENT_TERMINATED',
                                   'not_applicable': ['telemetry','ground_confirmation'] if basis=='ENVIRONMENT_TERMINATED' else [],
                                   'missing_or_blocking_reasons':reasons}
        locks.atomic_json(root/'inspection.json', record)
        return {k:v for k,v in record.items() if k not in {'snapshot','observation'}} | {
            **_evidence_validity(record), 'inspection_sha256':digest((root/'inspection.json').read_bytes()),
            'inspection_path':str(root/'inspection.json'),
            'message':'Read-only inspection; separate audit persisted. No reservation changed, no ground/success claim.'}
    except (ValueError, OSError, TypeError) as exc:
        return {'status':'BLOCKED','reasons':reasons+[f'Audit: {exc}'], 'reservations_changed':False,
                'summary':inspection_summary(before, observation) if before is not None else None,
                'environment':environment, 'evidence_state':'NOT_COLLECTED', 'application_eligible':False}


def apply_execution_reconciliation(inspection_id, inspection_sha256, authorization_statement, ground_confirmations=None,
                                   legacy_environment_confirmation=None):
    """Release only exact reviewed restrictions; keep history, never repair/replay a run."""
    try:
        root = INSPECTION_ROOT / jobs.valid_run_id(inspection_id)
        if not root.resolve().is_relative_to(INSPECTION_ROOT.resolve()):
            raise ValueError("Inspection escapes fixed root")
        raw = _inspection_bytes(inspection_id)
        if digest(raw) != inspection_sha256:
            raise ValueError("Inspection hash mismatch")
        inspection = json.loads(raw)
        if inspection.get('inspection_id') != inspection_id:
            raise ValueError('Inspection identity mismatch')
        if not isinstance(authorization_statement, str) or not authorization_statement.strip():
            raise ValueError("Explicit reconciliation authorization required; no flight consent inherited")
        ground_confirmations = [] if ground_confirmations is None else ground_confirmations
        request = {"inspection_sha256": inspection_sha256, "authorization_statement": authorization_statement,
                   "ground_confirmations": ground_confirmations}
        if legacy_environment_confirmation is not None:
            request['legacy_environment_confirmation'] = legacy_environment_confirmation
        with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock', blocking=False):
            with locks.file_mutex(locks.LOCK_ROOT/'registry.lock', blocking=False):
                if (root/'inspection.json').read_bytes() != raw:
                    raise ValueError("Inspection changed before application")
                prior = jobs.read_json(root/'application.json', INSPECTION_ROOT)
                if prior is not None:
                    if prior.get("request") != request:
                        raise ValueError("Repeated reconciliation has different authorization/evidence")
                    return {"status": prior["status"], "replayed": True, "application_path": str(root/'application.json')}
                basis = inspection.get('reconciliation_basis', 'ACTIVE_TELEMETRY_AND_GROUND')
                expected_status = ('AWAITING_TERMINATION_RECONCILIATION_AUTHORIZATION' if basis=='ENVIRONMENT_TERMINATED'
                                   else 'AWAITING_EXPLICIT_GROUND_CONFIRMATION')
                validity = _evidence_validity(inspection)
                allowed_statuses = {expected_status}
                if basis=='ENVIRONMENT_TERMINATED': allowed_statuses.add('AWAITING_LEGACY_ENVIRONMENT_REVIEW')
                if (inspection.get('status') not in allowed_statuses or validity['evidence_state']!='COLLECTED'
                        or validity['evidence_expired'] is not False):
                    raise ValueError('Inspection absent, blocked, expired or from a different boot; inspect again')
                if basis == 'ACTIVE_TELEMETRY_AND_GROUND':
                    # Independent declaration, not authenticated by MCP or inferred from AP flags.
                    if not isinstance(ground_confirmations, list) or len(ground_confirmations)!=2:
                        raise ValueError("Both interfaces require recent independent ground confirmations")
                    if {g.get('vehicle') for g in ground_confirmations} != {"v1", "v2"}:
                        raise ValueError("Ground confirmations must cover v1 and v2 exactly")
                    for ground in ground_confirmations:
                        age = (datetime.now(timezone.utc)-datetime.fromisoformat(ground["observed_at_utc"])).total_seconds()
                        if (ground.get("source") != "OPERATOR_VISUAL" or ground.get("on_ground") is not True
                                or not ground.get("statement", "").strip()
                                or not 0<=age<=EVIDENCE_TTL_SECONDS
                                or datetime.fromisoformat(ground["observed_at_utc"]) < datetime.fromisoformat(inspection["created_at"])):
                            raise ValueError("Need explicit visual ON-GROUND declaration after this inspection for both vehicles")
                elif basis != 'ENVIRONMENT_TERMINATED' or ground_confirmations:
                    raise ValueError('Unknown reconciliation basis or irrelevant ground claims for terminated environment')
                before = capture(inspection["target_id"])
                if before != inspection["snapshot"] or _process_reasons(before):
                    raise ValueError("Owners, files or processes changed since inspection; inspect again")
                reference = inspection.get('identity_reference')
                _check_reference(reference)
                association = None
                if basis=='ENVIRONMENT_TERMINATED':
                    association = _confirm_legacy_environment(legacy_environment_confirmation, inspection['environment'],
                                                              _binding_review(before, inspection['environment'], reference))
                elif legacy_environment_confirmation is not None:
                    raise ValueError('Legacy environment confirmation is only applicable to terminated-environment closure')
                environment = inspect_environment()
                reasons = _environment_reasons(environment, reference)
                if inspection.get('environment') and environment_identity(environment) != environment_identity(inspection['environment']):
                    reasons.append('Environment identity/state changed since inspection')
                if basis == 'ENVIRONMENT_TERMINATED':
                    if environment.get('status') != 'STOPPED' or reference is None:
                        reasons.append('Need exact bound environment still verifiably STOPPED')
                    observation = {'environment':environment, 'telemetry_collection':'NOT_APPLICABLE_ENVIRONMENT_STOPPED'}
                else:
                    if environment.get('status') != 'ACTIVE':
                        reasons.append('Active path cannot switch to termination reconciliation; inspect again')
                    observation = {}
                    if not reasons:
                        observation = collect_observations()
                        reasons.extend(telemetry_reasons(observation))
                        for vehicle in ('v1','v2'):
                            old = inspection['observation']['samples'][vehicle]['position'][-1]['message']['pose']['position']
                            new = observation.get('samples', {}).get(vehicle, {}).get('position', [])
                            if not new:
                                reasons.append(f'{vehicle}: no revalidation position')
                            elif any(abs(old[k]-new[-1]['message']['pose']['position'][k]) > d
                                     for k,d in (('latitude',.000002),('longitude',.000002),('altitude',.20))):
                                reasons.append(f'{vehicle}: position changed since inspection')
                        observation = {**observation, 'environment':environment}
                _check_reference(reference)
                if reasons or capture(inspection["target_id"]) != before:
                    raise ValueError(f"Revalidation failed or state changed: {reasons}")
                if (root/'inspection.json').read_bytes() != raw:
                    raise ValueError("Inspection changed during revalidation")
                if time.monotonic()-inspection["created_monotonic"] > EVIDENCE_TTL_SECONDS:
                    raise ValueError("Inspection expired during revalidation")
                # Durable barrier BEFORE any removal; a crash halfway stays blocked and is never auto-resumed.
                marker = locks.LOCK_ROOT/'reconciliation.json'
                if marker.exists():
                    raise ValueError("Unfinished reconciliation transaction; preserve restrictions and inspect audit")
                audit = {"status": "APPLYING", "request": request, "inspection_id": inspection_id,
                         "inspection_sha256": inspection_sha256, "process": locks.process_identity(),
                         "before": before, "revalidation": observation, "started_at": locks.utc_now(),
                         "historical_reports_modified": False, "flight_authorized": False,
                         "environment_association":association,
                         "reconciliation_basis": basis, "ground_contact": "NOT_ASSERTED"}
                locks.atomic_json(root/'application.json', audit)
                locks.atomic_json(marker, {"kind": "RECONCILIATION", "owner_id": inspection_id,
                                           "state": "UNCONFIRMED", "process": locks.process_identity()})
                history = locks.LOCK_ROOT/'history'/inspection_id
                history.mkdir(parents=True)
                for name in before["guards"]:
                    original = locks.LOCK_ROOT/name
                    content = original.read_bytes()
                    import os
                    with (history/name).open('xb') as file:
                        file.write(content)
                        file.flush()
                        os.fsync(file.fileno())
                    descriptor = os.open(history, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                    original.unlink()
                final = {**audit, "status": "APPLIED", "finished_at": locks.utc_now(),
                         "transition": "ADMINISTRATIVE_CLOSURE_ENVIRONMENT_TERMINATED" if basis=="ENVIRONMENT_TERMINATED"
                                       else "RESTRICTIONS_RECONCILED_NOT_HISTORICAL_MISSION_SUCCESS"}
                locks.atomic_json(root/'application.json', final)
                marker.unlink()
                return {"status": "APPLIED", "replayed": False, "application_path": str(root/'application.json'),
                        "historical_reports_modified": False, "flight_authorized": False,
                        "reconciliation_basis": basis, "ground_contact": "NOT_ASSERTED"}
    except Exception as exc:
        result = {"status": "BLOCKED", "reasons": [f"{type(exc).__name__}: {exc}"], "flight_authorized": False}
        try:
            if 'root' in locals() and root.is_relative_to(INSPECTION_ROOT) and root.is_dir():
                attempts = root/'attempts'
                attempts.mkdir(exist_ok=True)
                locks.atomic_json(attempts/(str(uuid4())+'.json'), {**result, "at": locks.utc_now(),
                                  "request": locals().get('request'), "historical_reports_modified": False})
        except (ValueError, OSError) as audit_error:
            result["audit_error"] = str(audit_error)
        return result
