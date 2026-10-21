"""Internal, one-shot bounded ground trial; NOT a mission/MCP/CLI execution entry.

No default worker spawn or ROS backend. Operational policy remains CLOSED.
Reuses MissionDefinition, deterministic validation, artifact helpers and project
execution authority rather than the aerial workflow or its acceptance analysis.
"""
import json
from secrets import token_hex
from uuid import uuid4

from models.mission_definition import MissionDefinition
from planning.artifact_store import fingerprint, identifier, request_path, sha256
from tools import vehicle_execution_lock as locks
from tools.execution_diagnostics import error_evidence
from tools.hermes_mission_validation import validate_mission
from tools.virtual_preflight_jobs import read_mission_input
from tools.rover_control import RoverControlCore, RoverControlError, RoverLimits, number
from tools.simulation_status import check_simulation_ready

RUN_ROOT = locks.PROJECT_ROOT / 'missions/generated/rover_ground_trials'
# No environment variable, MCP option, CLI or caller-supplied boolean can enable this.
OPERATIONAL_ROVER_ENABLED = False


def directory(run_id):
    root = RUN_ROOT / identifier(run_id)
    if root.is_symlink() or not root.resolve().is_relative_to(RUN_ROOT.resolve()):
        raise ValueError('Invalid ground trial path')
    return root


def _read(root, name):
    path = root/name
    if path.is_symlink():
        raise ValueError('Symlink ground trial artifact')
    return json.loads(read_mission_input(path))


def _request(value):
    if not isinstance(value, dict) or set(value) != {'kind', 'limits', 'forward_mps', 'yaw_rate_rad_s', 'duration_s'}:
        raise ValueError('Explicit bounded ground trial request required; no waypoint execution')
    if value['kind'] != 'ROVER_BOUNDED_CONTROL':
        raise ValueError('Unsupported ground trial kind')
    limits = RoverLimits(**value['limits'])
    RoverControlCore.velocity_message(value['forward_mps'], value['yaw_rate_rad_s'])
    duration = number(value['duration_s'], 'duration', positive=True)
    if (not 0 <= value['forward_mps'] <= limits.max_forward_mps
            or abs(value['yaw_rate_rad_s']) > limits.max_yaw_rate_rad_s or duration > limits.max_duration_s):
        raise ValueError('Ground trial exceeds explicit limits')
    return limits


def _mission(content):
    mission = MissionDefinition.model_validate_json(content)
    if (mission.vehicle.vehicle_id, mission.vehicle.vehicle_type, mission.vehicle.autopilot) != ('rover_01', 'ugv', 'ArduPilot'):
        raise ValueError('Requires exact rover_01/v3, ugv, ArduPilot identity')
    return mission


def _checked(root):
    job = _read(root, 'job.json')
    content = read_mission_input(root/'mission.json')
    request_bytes = read_mission_input(root/'request.json')
    request = json.loads(request_bytes)
    if (job['run_id'] != root.name or sha256(content) != job['mission_sha256']
            or sha256(request_bytes) != job['request_sha256']
            or fingerprint(job['authorization']) != job['authorization_sha256']
            or fingerprint([job['mission_sha256'], job['request_sha256'], job['authorization_sha256']]) != job['input_sha256']
            or job['vehicle_selection'] != {'vehicle_id': 'rover_01', 'simulated_vehicle': 'v3'}):
        raise ValueError('Ground trial snapshot/request/identity changed')
    return job, _mission(content), request, _request(request)


def admit_ground_trial(mission_path, request_key, request, authorization):
    """Internal admission, no spawn. Defaults BLOCKED before any filesystem write.

    Authorization is a declared scope, NOT authenticated human confirmation.
    Returned launch token is single-use; loss never permits a replacement/resume.
    """
    if not OPERATIONAL_ROVER_ENABLED:
        return {'status': 'BLOCKED', 'reason': 'OPERATIONAL_ROVER_POLICY_DISABLED'}
    content = read_mission_input(mission_path)
    mission = _mission(content)
    limits = _request(request)
    mission_hash, request_fingerprint = sha256(content), fingerprint(request)
    if (not isinstance(authorization, dict) or set(authorization) != {'mission_sha256', 'request_fingerprint', 'statement'}
            or authorization['mission_sha256'] != mission_hash
            or authorization['request_fingerprint'] != request_fingerprint
            or not isinstance(authorization['statement'], str) or not authorization['statement'].strip()):
        raise ValueError('Missing exact declared authorization scope')
    if request['forward_mps'] > mission.vehicle.cruise_speed_kmh / 3.6:
        raise ValueError('Trial speed exceeds validated mission speed')
    worst_minutes = (request['duration_s'] + 2*limits.call_timeout_s + limits.stop_timeout_s)/60
    if mission.vehicle.battery_percent - worst_minutes*mission.vehicle.battery_consumption_percent_per_minute < mission.constraints.minimum_battery_reserve_percent:
        raise ValueError('Declared battery insufficient for bounded trial budget')
    key = request_path(RUN_ROOT, request_key)
    scope = fingerprint([mission_hash, request_fingerprint, authorization])
    with locks.file_mutex(RUN_ROOT/'admission.lock'):
        if key.exists():
            previous = json.loads(key.read_bytes())
            if previous['scope'] != scope:
                raise ValueError('request_key already binds different scope')
            return query_ground_trial(previous['run_id'])  # never grants another token
        validation = validate_mission(mission, export_qgc=False)
        if validation.get('execution_status') != 'APPROVED' or validation.get('errors'):
            return {'status': 'BLOCKED', 'validation': validation}
        run_id, token = str(uuid4()), token_hex(32)
        root = directory(run_id)
        root.mkdir(parents=True)
        # Exact mission bytes; fsync+atomic replace from the existing persistence helper.
        # JSON wrapper would change bytes, so use the fsync sequence for this byte snapshot.
        _atomic_bytes(root/'mission.json', content)
        locks.atomic_json(root/'request.json', request)
        request_hash = sha256((root/'request.json').read_bytes())
        job = {'kind': 'ROVER_GROUND_TRIAL', 'run_id': run_id, 'job_state': 'ADMITTED',
               'vehicle_selection': {'vehicle_id': 'rover_01', 'simulated_vehicle': 'v3'},
               'mission_sha256': mission_hash, 'request_sha256': request_hash,
               'authorization_sha256': fingerprint(authorization),
               'input_sha256': fingerprint([mission_hash, request_hash, fingerprint(authorization)]), 'worker': None,
               'launch_token_sha256': sha256(token.encode()), 'created_at': locks.utc_now(),
               'authorization': authorization, 'authorization_basis': 'UNVERIFIED_CALLER_DECLARATION',
               'validation': validation, 'route_execution': 'NOT_SUPPORTED'}
        locks.atomic_json(root/'job.json', job)
        key.parent.mkdir(parents=True, exist_ok=True)
        # Persist idempotency BEFORE reserving; a failure is not a reason to retry admission.
        locks.atomic_json(key, {'scope': scope, 'run_id': run_id})
        try:
            locks.reserve(run_id, 'rover_ground_trial', 'v3', input_sha256=job['input_sha256'])
        except locks.VehicleBusy as exc:
            locks.atomic_json(root/'job.json', {**job, 'job_state': 'BLOCKED', 'error': str(exc)})
            return query_ground_trial(run_id)
        return {'status': 'ADMITTED', 'run_id': run_id, 'launch_token': token,
                'mission_sha256': mission_hash, 'request_sha256': request_hash}


def _atomic_bytes(path, content):
    import os
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    with temporary.open('xb') as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def query_ground_trial(run_id):
    """Read-only: no mutex creation, worker spawn, state repair or lease release."""
    root = directory(run_id)
    if not (root/'job.json').exists():
        return {'run_id': run_id, 'status': 'NOT_FOUND'}
    job, _, _, _ = _checked(root)
    report = _read(root, 'report.json') if (root/'report.json').exists() else None
    failure = _read(root, 'failure.json') if (root/'failure.json').exists() else None
    for name, artifact in (('report', report), ('failure', failure)):
        expected = job.get(name + '_sha256')
        if expected is not None and (artifact is None or sha256(read_mission_input(root/(name+'.json'))) != expected):
            raise ValueError('Ground result artifact hash mismatch')
        if artifact is not None and any(artifact.get(k) != job.get(k) for k in
                ('run_id', 'input_sha256', 'mission_sha256', 'request_sha256', 'vehicle_selection', 'worker')):
            raise ValueError('Ground result identity differs from its admission')
    if report is not None and (report.get('run_id') != run_id or report.get('input_sha256') != job['input_sha256']):
        raise ValueError('Ground report identity/hash mismatch')
    alive = locks.identity_alive(job['worker']) if job['worker'] else None
    state = job['job_state']
    if state in {'ADMITTED', 'RUNNING'} and alive is not True:
        state = 'UNCONFIRMED'  # derived view; never rewrites originals or resumes
    reservation = locks.restriction('v3')
    owns_guard = reservation is not None and reservation.get('owner_id') == run_id
    if (state == 'FINISHED' and owns_guard
            or state in {'ADMITTED', 'RUNNING'} and (not owns_guard
                or reservation.get('input_sha256') != job['input_sha256'])):
        state = 'UNCONFIRMED'
    return {'run_id': run_id, 'status': state, 'worker': job['worker'], 'worker_alive': alive,
            'vehicle_selection': job['vehicle_selection'], 'mission_sha256': job['mission_sha256'],
            'request_sha256': job['request_sha256'], 'report': report,
            'reservation': reservation, 'failure': failure}


def run_ground_worker(run_id, launch_token, *, adapter_factory=None, readiness=check_simulation_ready):
    """One shot in the owning process. No spawn/restart, no default live adapter.

    A future detached entry can reuse this function after operational policy and
    audited source binding are implemented. No caller can enable the policy.
    """
    if not OPERATIONAL_ROVER_ENABLED or adapter_factory is None:
        return {'status': 'BLOCKED', 'reason': 'OPERATIONAL_ROVER_POLICY_DISABLED_OR_NO_ADAPTER'}
    root = directory(run_id)
    with locks.file_mutex(RUN_ROOT/'admission.lock'):
        job, mission, request, limits = _checked(root)
        current = locks.restriction('v3')
        if (job['job_state'] != 'ADMITTED' or job['worker'] is not None
                or sha256(launch_token.encode()) != job['launch_token_sha256']
                or not current or current['owner_id'] != run_id or current.get('state') != 'RESERVED'
                or current.get('input_sha256') != job['input_sha256']):
            return {'status': 'BLOCKED', 'reason': 'WORKER_OR_SCOPE_ALREADY_CONSUMED_OR_CHANGED'}
        job.update(job_state='RUNNING', worker=locks.process_identity(), started_at=locks.utc_now())
        if job['worker'] is None:
            raise ValueError('Cannot identify ground worker')
        locks.atomic_json(root/'job.json', job)  # identity durably recorded BEFORE any backend
    events = []
    def journal(event):
        events.append({'received_at_utc': locks.utc_now(), **event})
        locks.atomic_json(root/'events.json', {'run_id': run_id, 'events': events})
    report = {'run_id': run_id, 'input_sha256': job['input_sha256'],
              'mission_sha256': job['mission_sha256'], 'request_sha256': job['request_sha256'],
              'vehicle_selection': job['vehicle_selection'], 'worker': job['worker'],
              'status': 'BLOCKED', 'control_attempted': False, 'result': None,
              'movement_observed': 'NOT_MEASURED', 'route_executed': False,
              'ground_contact_confirmed': False}
    core = None
    adapter = None
    try:
        with locks.execution_scope(run_id, 'v3'):
            # Recheck exact bytes under authority, then deterministic validation and current readiness.
            _, mission, request, limits = _checked(root)
            validation = validate_mission(mission, export_qgc=False)
            report['validation'] = validation
            if validation.get('execution_status') != 'APPROVED' or validation.get('errors'):
                raise RoverControlError('Deterministic validation no longer approves')
            report['readiness'] = readiness(profile='two_drones_rover')
            if report['readiness'].get('ready') is not True:
                raise RoverControlError('Current three-vehicle readiness not confirmed')
            adapter = adapter_factory(journal)
            report['capabilities'] = adapter.probe(timeout_s=limits.call_timeout_s)
            checked_job, _, _, _ = _checked(root)
            guard = locks.restriction('v3')
            if (checked_job != job or not guard or guard.get('input_sha256') != job['input_sha256']):
                raise RoverControlError('Snapshot, scope or reservation changed during readiness/probe')
            core = RoverControlCore(limits, adapter=adapter, clock=adapter.clock)
            # Core verifies fresh independent motion BEFORE first publication; no arming.
            result = core.move_for(request['forward_mps'], request['yaw_rate_rad_s'], request['duration_s'])
            report.update(result=result, control_attempted=result['motion_command_attempted'], status=result['status'])
            report['diagnostics'] = core.diagnostics
            report['finished_at'] = locks.utc_now()
            report = json.loads(json.dumps(report, allow_nan=False))
            locks.atomic_json(root/'report.json', report)  # final evidence BEFORE any release
            job['report_sha256'] = sha256((root/'report.json').read_bytes())
            # Never release a still-armed rover just because zero/HOLD was acknowledged.
            stop = result.get('stop') or {}
            samples = stop.get('observations') or []
            no_control = not result['motion_command_attempted'] and not any(e.get('operation') == 'control_intent' for e in events)
            disarmed_stop = (stop.get('status') == 'STATIONARY_OBSERVED' and len(samples) == 2
                             and all(s.get('armed') is False and s.get('flying') is False for s in samples))
            releasable = no_control or disarmed_stop
        # Final job persistence is also required. Any storage error retains uncertainty.
        locks.atomic_json(root/'job.json', {**job, 'job_state': 'FINISHED' if releasable else 'UNCONFIRMED',
                                            'finished_at': locks.utc_now()})
        if releasable:
            locks.release(run_id, 'v3')
        else:
            locks.mark_uncertain(run_id, 'v3')
        return report
    except BaseException as exc:
        # Includes persistence failure, worker cancellation and controls with uncertain effects.
        locks.mark_uncertain(run_id, 'v3')
        possible_control = any(e.get('operation') == 'control_intent' for e in events)
        report.update(status='UNCONFIRMED',
                      control_attempted=report['control_attempted'] or (None if possible_control else False),
                      control_effects_uncertain=possible_control,
                      error_evidence=error_evidence(exc), finished_at=locks.utc_now(),
                      diagnostics=core.diagnostics if core else [])
        # Do not overwrite a final result already persisted if a later write failed.
        locks.atomic_json(root/'failure.json', report)
        job['failure_sha256'] = sha256((root/'failure.json').read_bytes())
        locks.atomic_json(root/'job.json', {**job, 'job_state': 'UNCONFIRMED', 'error': str(exc)})
        if not isinstance(exc, Exception):
            raise
        return report
    finally:
        # Session destruction is not vehicle stopping/disarming.
        if adapter is not None and hasattr(adapter.session, 'close'):
            adapter.session.close()
