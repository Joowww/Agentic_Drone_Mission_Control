"""Internal, one-shot bounded ground trial; NOT a mission/MCP/CLI execution entry.

No default worker spawn or ROS backend. Operational policy remains CLOSED.
Reuses MissionDefinition, deterministic validation, artifact helpers and project
execution authority rather than the aerial workflow or its acceptance analysis.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

from models.mission_definition import MissionDefinition
from planning.artifact_store import fingerprint, identifier, request_path, sha256
from tools import vehicle_execution_lock as locks
from tools.execution_diagnostics import error_evidence
from tools.hermes_mission_validation import validate_mission
from tools.virtual_preflight_jobs import read_mission_input
from tools.rover_control import RoverControlCore, RoverControlError, RoverLimits, PulseSafety, NavigationGoal, synchronous_deadline, number
from tools.simulation_status import check_simulation_ready
from tools.simulation_profiles import get_profile
from tools import rover_sitl_trial_policy as sitl_policy

RUN_ROOT = locks.PROJECT_ROOT / 'missions/generated/rover_ground_trials'
# No environment variable, MCP option, CLI or caller-supplied boolean can enable this.
OPERATIONAL_ROVER_ENABLED = False
# Profiles whose launch contains rover_01/v3; readiness of the chosen one is required.
ROVER_PROFILES = ('two_drones_rover', 'rover_only')
PREPARATION_KIND = 'GUIDED_ARM_AFTER_STATIONARY_V1'


@dataclass(frozen=True)
class NavigationPreparationSafety:
    """Minimal envelope prepare_guided_armed() reads: accredited binding, odom frame, slope limit."""
    binding_sha256: str
    pose_frame: str
    max_slope_rad: float

    def __post_init__(self):
        v = self.binding_sha256
        if not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v) or not int(v, 16):
            raise RoverControlError('Navigation preparation needs the accredited binding digest')
        if self.pose_frame != 'odom':
            raise RoverControlError('Navigation preparation is defined for the accredited odom frame only')
        if not 0 < number(self.max_slope_rad, 'max slope', positive=True) < math.pi / 2:
            raise RoverControlError('Navigation preparation slope limit out of range')


def request_profile(request):
    """Explicit allowlist; the profile must actually contain rover_01/v3."""
    profile = request.get('profile', 'two_drones_rover') if isinstance(request, dict) else None
    if profile not in ROVER_PROFILES or ('rover_01', 'v3') not in get_profile(profile).bindings:
        raise ValueError('Rover profile not allowed or without rover_01/v3')
    return profile


def _preparation_safety(request):
    if request['kind'] == 'ROVER_NAVIGATE_V1':
        return NavigationPreparationSafety(**request['preparation_safety'])
    return PulseSafety(**request['safety'])


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
    if isinstance(value,dict) and value.get('kind')=='ROVER_PULSE_V1':
        keys={'kind','limits','safety','context','forward_mps','yaw_rate_rad_s','duration_s'}
        if not keys<=set(value) or set(value)-keys-{'finalization','preparation','infrastructure_close'}:raise ValueError('Exact pulse request required')
        limits=RoverLimits(**value['limits']);safety=PulseSafety(**value['safety'])
        context=value['context']
        if not isinstance(context,dict) or set(context)!={'lifecycle_id','target_sha256','source_contract_sha256','body_review_sha256','destinations'}:
            raise ValueError('Exact pulse owner/destinations required')
        identifier(context['lifecycle_id'])
        for key in ('target_sha256','source_contract_sha256','body_review_sha256'):
            v=context[key]
            if not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) or not int(v,16):raise ValueError('Missing pulse '+key)
        if context['body_review_sha256']!=safety.review_sha256:raise ValueError('Pulse body/envelope review differs')
        destinations={'velocity':{'endpoint':'/ap/v3/cmd_vel','type':'geometry_msgs/msg/TwistStamped','frame':'base_link'},
            'stop':{'endpoint':'/ap/v3/mode_switch','type':'ardupilot_msgs/srv/ModeSwitch','mode':4}}
        if 'preparation' in value:
            p=value['preparation']
            if not isinstance(p,dict) or set(p)!={'kind','timeout_s'} or p['kind']!='GUIDED_ARM_AFTER_STATIONARY_V1':raise ValueError('Exact preparation policy required')
            number(p['timeout_s'],'preparation timeout',positive=True)
            destinations['preparation']={'mode':{'endpoint':'/ap/v3/mode_switch','type':'ardupilot_msgs/srv/ModeSwitch','mode':15},
                'arm':{'endpoint':'/ap/v3/arm_motors','type':'ardupilot_msgs/srv/ArmMotors','arm':True}}
        if 'infrastructure_close' in value and value['infrastructure_close']!={'kind':'SAME_SESSION_INFRASTRUCTURE_V1'}:
            raise ValueError('Exact same-session infrastructure close policy required')
        if value.get('finalization'):
            p=value['finalization']
            if set(p)!={'kind','timeout_s'} or p['kind']!='DISARM_AFTER_OBSERVED_STOP_V1':raise ValueError('Exact pulse finalization required')
            number(p['timeout_s'],'pulse finalization timeout',positive=True)
            destinations['finalization']={'endpoint':'/ap/v3/arm_motors','type':'ardupilot_msgs/srv/ArmMotors','arm':False}
        if context['destinations']!=destinations:raise ValueError('Pulse destinations differ')
        RoverControlCore.velocity_message(value['forward_mps'],value['yaw_rate_rad_s'])
        duration=number(value['duration_s'],'pulse duration',positive=True)
        if (not 0<value['forward_mps']<=limits.max_forward_mps or value['yaw_rate_rad_s']!=0 or
                duration>limits.max_duration_s or safety.close_budget_s<limits.call_timeout_s or
                safety.total_timeout_s<3*limits.call_timeout_s+duration+limits.stop_timeout_s+safety.close_budget_s+value.get('finalization',{}).get('timeout_s',0)+value.get('preparation',{}).get('timeout_s',0)):
            raise ValueError('Pulse limits/timing unresolved')
        return limits
    if isinstance(value,dict) and value.get('kind')=='ROVER_NAVIGATE_V1':
        optional={'finalization','preparation','preparation_safety','profile','sitl_trial'}
        if not {'kind','limits','goal'}<=set(value) or set(value)-{'kind','limits','goal'}-optional:raise ValueError('Exact navigation request required')
        if ('preparation' in value)!=('preparation_safety' in value):raise ValueError('Preparation and its safety envelope go together')
        if 'preparation' in value:
            p=value['preparation']
            if not isinstance(p,dict) or set(p)!={'kind','timeout_s'} or p['kind']!=PREPARATION_KIND:raise ValueError('Exact preparation policy required')
            number(p['timeout_s'],'preparation timeout',positive=True)
            NavigationPreparationSafety(**value['preparation_safety'])
        request_profile(value)
        if 'sitl_trial' in value and (not isinstance(value['sitl_trial'],dict) or set(value['sitl_trial'])!={'scope','authorization','binding_evidence'}):
            raise ValueError('Exact SITL trial declaration required')
        if 'finalization' in value:
            policy=value['finalization']
            if not isinstance(policy,dict) or set(policy)!={'kind','timeout_s'} or policy['kind']!='DISARM_AFTER_OBSERVED_STOP_V1':
                raise ValueError('Explicit finalization policy required')
            number(policy['timeout_s'],'finalization timeout',positive=True)
        limits=RoverLimits(**value['limits']);goal=NavigationGoal(**value['goal'])
        if goal.timeout_s>limits.max_duration_s:raise ValueError('Navigation budget exceeds declared limits')
        return limits
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


def sitl_current_facts(scope, evidence):
    """Real current facts for the SITL policy, read now; only consulted while the policy is enabled."""
    from tools.reconciliation_environment import inspect_active_execution
    from tools.rover_motion_binding import require_current
    execution = inspect_active_execution()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if locks.infrastructure_restriction() is not None:
        raise RoverControlError('Lifecycle lease present; no current confirmed start')
    starts = []
    for path in (locks.LOCK_ROOT.parent/'simulation_lifecycle').glob('*/operation.json'):
        op = json.loads(path.read_text())
        if op.get('environment_execution') == execution or op.get('action') == 'stop':
            starts.append(op)
    starts.sort(key=lambda op: op.get('started_at', ''))
    latest = starts[-1] if starts else {}
    if latest.get('action') != 'start' or latest.get('state') != 'FINISHED':
        raise RoverControlError('Latest lifecycle operation is not a confirmed start of this execution')
    require_current(evidence, lifecycle_id=latest['owner_id'], environment_execution=execution, host_boot_id=boot)
    scope_sha = fingerprint(scope)
    consumed = sum(1 for job_path in RUN_ROOT.glob('*/job.json')
                   if json.loads(job_path.read_text()).get('sitl_scope_sha256') == scope_sha
                   and (job_path.parent/'start-intent.json').exists())
    return {'environment_execution': execution, 'host_boot_id': boot, 'lifecycle_id': latest['owner_id'],
            'profile': latest.get('profile'), 'binding_evidence_sha256': evidence.get('evidence_sha256'),
            'trials_consumed': consumed}


def policy_gate(request, mission_hash, *, facts=None):
    """OPERATIONAL, or one exact SITL trial for this mission/goal/profile; never a bypass of either."""
    if OPERATIONAL_ROVER_ENABLED:
        return {'status': 'AUTHORIZED', 'basis': 'OPERATIONAL'}
    trial = request.get('sitl_trial')
    if not isinstance(trial, dict):
        return {'status': 'BLOCKED', 'reasons': ['OPERATIONAL_ROVER_POLICY_DISABLED', 'NO_SITL_TRIAL_DECLARATION']}
    reasons = []
    scope = trial['scope']
    if (scope.get('schema') != 'tfg.rover.sitl-trial-scope/2'
            or scope.get('request_contract_sha256') != sitl_policy.request_contract(request)):
        reasons.append('SCOPE_DIFFERS_FROM_REQUEST')
    context = scope.get('control_context')
    try:
        from tools.rover_target_frame import start_pose
        from tools.rover_pipe_session import worker_limits
        own = context['worker_limits']
        if (scope.get('profile') != 'rover_only'
                or context['start_pose'] != start_pose(trial['binding_evidence'])
                or context['cadence']['lifecycle_id'] != scope['lifecycle_id']
                or context['control_timing']['cadence_sha256'] != fingerprint(context['cadence'])
                or context['control_timing']['limits'] != request['limits']
                or context['start_tolerance'] != {'position_m': 0.05, 'yaw_rad': 0.05}
                or own != worker_limits(RoverLimits(**request['limits']), watchdog_s=own['watchdog_s'],
                                        max_session_s=own['max_session_s'])):
            reasons.append('CONTROL_CONTEXT_DIFFERS')
        # The only stop layer independent of host, worker, pipe and DDS: re-derived, never trusted.
        from tools.rover_autopilot_failsafe import TRIAL_MAX_DISTANCE_M, verify_trial_entry
        failsafe = verify_trial_entry(context['autopilot_failsafe'], request=request, context=context, scope=scope,
                                      max_distance_m=TRIAL_MAX_DISTANCE_M)
        if failsafe:
            reasons.append(failsafe)
    except (KeyError, TypeError, ValueError, RoverControlError):
        reasons.append('CONTROL_CONTEXT_INVALID_OR_LEGACY')
    if (request.get('kind') != 'ROVER_NAVIGATE_V1' or scope.get('mission_sha256') != mission_hash
            or scope.get('goal_sha256') != fingerprint(request.get('goal')) or scope.get('profile') != request_profile(request)
            or 'preparation' not in request):
        reasons.append('SCOPE_DIFFERS_FROM_REQUEST')
    try:
        current = (facts or sitl_current_facts)(scope, trial['binding_evidence'])
    except Exception as exc:
        current = {}
        reasons.append('CURRENT_FACTS_UNAVAILABLE: ' + type(exc).__name__)
    result = sitl_policy.evaluate(scope, trial['authorization'], current)
    reasons += result['reasons']
    return ({'status': 'AUTHORIZED', 'basis': 'SITL_TRIAL', 'scope_sha256': result['scope_sha256']} if not reasons
            else {'status': 'BLOCKED', 'reasons': reasons, 'scope_sha256': result['scope_sha256']})


def motion_policy_allows_current_owner():
    """For transports: non-stop commands only for the live owner of v3 under a policy basis."""
    guard = locks.restriction('v3')
    if not guard:
        return False
    job, _, _, _ = _checked(directory(guard['owner_id']))
    if job['worker'] != locks.process_identity() or job['job_state'] not in {'RUNNING', 'PREPARING'}:
        return False
    if OPERATIONAL_ROVER_ENABLED:
        return True
    return sitl_policy.SITL_TRIAL_POLICY_ENABLED is True and job.get('policy_basis') == 'SITL_TRIAL'


def executor_facts():
    """Read-only module contract, no filesystem, ROS, credentials or reservations."""
    return {'schema':'tfg.rover.executor-facts/1','policy_enabled':OPERATIONAL_ROVER_ENABLED,
            'navigation_request_supported':True,'navigation_kind':'ROVER_NAVIGATE_V1',
            'pulse_request_supported':True,'pulse_kind':'ROVER_PULSE_V1',
            'recoverable_start':'EXPLICIT_AUTHORIZED_SYNCHRONOUS_MAIN_THREAD_NO_SPAWN',
            'finalization_policies':['DISARM_AFTER_OBSERVED_STOP_V1'],
            'worker_entry':'tools.rover_ground_executor.run_ground_worker',
            'deadline_contract':'POSIX_MAIN_THREAD_PLUS_NATIVE_FINITE_APIS',
            'authorization_basis':'UNVERIFIED_EXPLICIT_DECLARATIONS_NOT_AUTHENTICATION'}


def _coordination(context,mission_hash,request):
    if not isinstance(context,dict) or set(context)!={'candidate','authorization'}:
        raise ValueError('Explicit coordination_context candidate/authorization required')
    candidate=context['candidate'];auth=context['authorization']
    if not isinstance(candidate,dict) or not isinstance(auth,dict) or set(auth)!={
            'source','statement','candidate_sha256','mission_sha256','session_id'}:
        raise ValueError('Malformed coordinator declaration')
    identifier(auth['session_id'])
    if (auth['source']!='OPERATOR_DECLARED' or not isinstance(auth['statement'],str) or not auth['statement'].strip()
            or auth['candidate_sha256']!=fingerprint(candidate) or auth['mission_sha256']!=mission_hash
            or candidate.get('vehicle_id')!='rover_01'
            or candidate.get('rover_mission',{}).get('value',{}).get('sha256')!=mission_hash):
        raise ValueError('Coordinator candidate/mission/authorization contradiction')
    if request.get('finalization') is not None and candidate.get('finalization_policy',{}).get('value')!=request['finalization']:
        raise ValueError('Finalization policy differs from authorized candidate')
    if request.get('preparation') is not None and candidate.get('preparation_policy',{}).get('value')!=request['preparation']:
        raise ValueError('Preparation policy differs from authorized candidate')
    target=candidate.get('target_in_rover_frame',{}).get('value',{})
    transform=candidate.get('frame_transform',{}).get('value',{})
    if (any(target.get(k)!=request['goal'][k] for k in ('x_m','y_m','frame')) or
            transform.get('status')!='VERIFIED' or transform.get('to_frame')!=target.get('frame')
            or not isinstance(transform.get('sha256'),str) or len(transform['sha256'])!=64
            or any(c not in '0123456789abcdef' for c in transform['sha256'])):
        raise ValueError('Coordinator target/frame declaration differs from request')
    return {'candidate_sha256':fingerprint(candidate),'authorization_sha256':fingerprint(auth),
            'session_id':auth['session_id'],'frame_sha256':transform['sha256']}


def lookup_ground_trial(request_key):
    """Read-only lookup with index, snapshot and scope validation; never resumes."""
    path=request_path(RUN_ROOT,request_key)
    if path.is_symlink():raise ValueError('Unsafe request index')
    if not path.exists():return {'found':False}
    index=json.loads(read_mission_input(path));job,_,_,_=_checked(directory(index['run_id']))
    if index['scope']!=job.get('admission_scope_sha256'):
        raise ValueError('Request index scope differs from bound job')
    state=query_ground_trial(job['run_id'])
    return {'found':True,'run_id':job['run_id'],'scope':index['scope'],'session_id':job.get('session_id'),
            'input_sha256':job['input_sha256'],'status':state['status'],'worker_phase':state['worker_phase'],
            'coordination_sha256':job.get('coordination_sha256')}


def _mission(content):
    mission = MissionDefinition.model_validate_json(content)
    if (mission.vehicle.vehicle_id, mission.vehicle.vehicle_type, mission.vehicle.autopilot) != ('rover_01', 'ugv', 'ArduPilot'):
        raise ValueError('Requires exact rover_01/v3, ugv, ArduPilot identity')
    return mission


def _pulse_binding(request,authorization):
    return {'session_id':request['context']['lifecycle_id'],
        'pulse_context_sha256':fingerprint(request['context']),
        'authorization_sha256':fingerprint(authorization)}


def _checked(root):
    job = _read(root, 'job.json')
    content = read_mission_input(root/'mission.json')
    request_bytes = read_mission_input(root/'request.json')
    request = json.loads(request_bytes)
    inputs=[job['mission_sha256'],job['request_sha256'],job['authorization_sha256']]
    if job.get('coordination_sha256'):
        context_bytes=read_mission_input(root/'coordination.json')
        if sha256(context_bytes)!=job['coordination_sha256']:raise ValueError('Coordination snapshot changed')
        context=json.loads(context_bytes);binding=_coordination(context,job['mission_sha256'],request)
        if binding!=job.get('coordination_binding') or binding['session_id']!=job.get('session_id'):
            raise ValueError('Coordination binding/session changed')
        inputs.append(job['coordination_sha256'])
    elif request.get('kind')=='ROVER_NAVIGATE_V1':
        raise ValueError('Navigation snapshot lacks explicit coordination')
    if job.get('start_intent_sha256'):
        intent_bytes=read_mission_input(root/'start-intent.json')
        if sha256(intent_bytes)!=job['start_intent_sha256']:raise ValueError('Start intent changed')
        intent=json.loads(intent_bytes)
        _validate_start_authorization(job,intent['authorization'])
        if fingerprint(intent['authorization'])!=job['start_authorization_sha256']:
            raise ValueError('Start authorization changed')
    if (job['run_id'] != root.name or sha256(content) != job['mission_sha256']
            or sha256(request_bytes) != job['request_sha256']
            or fingerprint(job['authorization']) != job['authorization_sha256']
            or fingerprint(inputs) != job['input_sha256']
            or job['vehicle_selection'] != {'vehicle_id': 'rover_01', 'simulated_vehicle': 'v3'}):
        raise ValueError('Ground trial snapshot/request/identity changed')
    if request.get('kind')=='ROVER_PULSE_V1':
        if job.get('pulse_binding')!=_pulse_binding(request,job['authorization']) or job.get('session_id')!=request['context']['lifecycle_id']:
            raise ValueError('Pulse session/authorization binding changed')
    if job.get('closure_report_sha256'):
        if sha256((root/'closure-report.json').read_bytes())!=job['closure_report_sha256']:raise ValueError('Closure report changed')
    return job, _mission(content), request, _request(request)


def admit_ground_trial(mission_path, request_key, request, authorization, *, coordination_context=None):
    """Internal admission, no spawn. Defaults BLOCKED before any filesystem write.

    Authorization is a declared scope, NOT authenticated human confirmation.
    Returned launch token is single-use; loss never permits a replacement/resume.
    """
    if not OPERATIONAL_ROVER_ENABLED and not (isinstance(request, dict) and 'sitl_trial' in request):
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
    speed = limits.max_forward_mps if request['kind']=='ROVER_NAVIGATE_V1' else request['forward_mps']
    duration = request['goal']['timeout_s'] if request['kind']=='ROVER_NAVIGATE_V1' else request['duration_s']
    if speed > mission.vehicle.cruise_speed_kmh / 3.6:
        raise ValueError('Trial speed exceeds validated mission speed')
    worst_minutes = (duration + 2*limits.call_timeout_s + limits.stop_timeout_s + request.get('finalization',{}).get('timeout_s',0)
                     + (request.get('preparation',{}).get('timeout_s',0) if request['kind']=='ROVER_NAVIGATE_V1' else 0))/60
    if mission.vehicle.battery_percent - worst_minutes*mission.vehicle.battery_consumption_percent_per_minute < mission.constraints.minimum_battery_reserve_percent:
        raise ValueError('Declared battery insufficient for bounded trial budget')
    binding=_coordination(coordination_context,mission_hash,request) if request['kind']=='ROVER_NAVIGATE_V1' else None
    gate=policy_gate(request,mission_hash)
    if gate['status']!='AUTHORIZED':
        return {'status':'BLOCKED','reason':'OPERATIONAL_ROVER_POLICY_DISABLED','policy_gate':gate}
    key = request_path(RUN_ROOT, request_key)
    scope = fingerprint([mission_hash,request_fingerprint,authorization]+([coordination_context] if binding else []))
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
        if binding:
            locks.atomic_json(root/'coordination.json',coordination_context)
            context_hash=sha256((root/'coordination.json').read_bytes())
        else:context_hash=None
        job = {'kind': 'ROVER_GROUND_TRIAL', 'run_id': run_id, 'job_state': 'ADMITTED',
               'vehicle_selection': {'vehicle_id': 'rover_01', 'simulated_vehicle': 'v3'},
               'mission_sha256': mission_hash, 'request_sha256': request_hash,
               'authorization_sha256': fingerprint(authorization),
               'input_sha256': fingerprint([mission_hash,request_hash,fingerprint(authorization)]+([context_hash] if binding else [])), 'worker': None,
               'admission_scope_sha256':scope,'session_id':binding['session_id'] if binding else request['context']['lifecycle_id'] if request['kind']=='ROVER_PULSE_V1' else None,
               'coordination_sha256':context_hash,'coordination_binding':binding,
               'launch_token_sha256':sha256(token.encode()) if request['kind']!='ROVER_NAVIGATE_V1' else None, 'created_at': locks.utc_now(),
               'authorization': authorization, 'authorization_basis': 'UNVERIFIED_CALLER_DECLARATION',
               'validation': validation, 'route_execution': 'NOT_SUPPORTED',
               'policy_admission': gate, 'sitl_scope_sha256': gate.get('scope_sha256') if gate.get('basis') == 'SITL_TRIAL' else None}
        if request['kind']=='ROVER_PULSE_V1':
            job['pulse_binding']=_pulse_binding(request,authorization);job['launch_token_sha256']=None
        locks.atomic_json(root/'job.json', job)
        key.parent.mkdir(parents=True, exist_ok=True)
        # Persist idempotency BEFORE reserving; a failure is not a reason to retry admission.
        locks.atomic_json(key, {'scope': scope, 'run_id': run_id})
        try:
            locks.reserve(run_id, 'rover_ground_trial', 'v3', input_sha256=job['input_sha256'])
        except locks.VehicleBusy as exc:
            locks.atomic_json(root/'job.json', {**job, 'job_state': 'BLOCKED', 'error': str(exc)})
            return query_ground_trial(run_id)
        response={'status':'ADMITTED','run_id':run_id,'session_id':job.get('session_id'),
                  'input_sha256':job['input_sha256'],'mission_sha256':mission_hash,'request_sha256':request_hash}
        if request['kind'] not in ('ROVER_NAVIGATE_V1','ROVER_PULSE_V1'):response['launch_token']=token
        return response


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
    report = (_read(root,'closure-report.json') if job.get('closure_report_sha256') else
              _read(root, 'report.json') if (root/'report.json').exists() else None)
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
    phase=state
    if state=='ADMITTED' and job['worker'] is None:
        if (root/'start-intent.json').exists():state='UNCONFIRMED';phase='START_INTENT_WITHOUT_CONFIRMED_WORKER'
        else:phase='ADMITTED_NOT_STARTED'
    elif state=='STARTING':
        intent=_read(root,'start-intent.json')
        phase='STARTING'
        if locks.identity_alive(intent.get('requester')) is not True:
            state='UNCONFIRMED';phase='STARTING_WORKER_LOST_OR_UNKNOWN'
    elif state in {'RUNNING','PREPARING','FINALIZING'} and alive is not True:
        state = 'UNCONFIRMED';phase='WORKER_LOST_OR_UNKNOWN'  # derived view; never rewrites originals or resumes
    reservation = locks.restriction('v3')
    owns_guard = reservation is not None and reservation.get('owner_id') == run_id
    if (state == 'FINISHED' and owns_guard
            or state in {'ADMITTED','STARTING','RUNNING','PREPARING','FINALIZING'} and (not owns_guard
                or reservation.get('input_sha256') != job['input_sha256'])):
        state = 'UNCONFIRMED'
    if (root/'start-outcome.json').exists():state='UNCONFIRMED';phase='START_UNCONFIRMED'
    if state=='UNCONFIRMED' and phase=='FINISHED':phase='FINAL_RESULT_RESERVATION_RETAINED'
    return {'run_id':run_id,'status':state,'job_closure_confirmed':state=='FINISHED' and not owns_guard,'worker_phase':phase,'input_sha256':job['input_sha256'],'session_id':job.get('session_id'),'coordination_binding':job.get('coordination_binding'), 'worker': job['worker'], 'worker_alive': alive,
            'vehicle_selection': job['vehicle_selection'], 'mission_sha256': job['mission_sha256'],
            'request_sha256': job['request_sha256'], 'report': report,
            'reservation': reservation, 'failure': failure}


def _validate_start_authorization(job,value):
    if job.get('pulse_binding'):
        expected={'run_id':job['run_id'],'input_sha256':job['input_sha256'],**job['pulse_binding']}
        if (not isinstance(value,dict) or set(value)!=set(expected)|{'statement'} or
                not isinstance(value['statement'],str) or not value['statement'].strip() or
                any(value[k]!=v for k,v in expected.items())):
            raise ValueError('Explicit pulse start owner/scope authorization required')
        return
    keys={'run_id','input_sha256','candidate_sha256','session_id','authorization_sha256','statement'}
    if not isinstance(value,dict) or set(value)!=keys or not isinstance(value['statement'],str) or not value['statement'].strip():
        raise ValueError('Explicit start authorization declaration required')
    expected={'run_id':job['run_id'],'input_sha256':job['input_sha256'],
              **{k:job['coordination_binding'][k] for k in ('candidate_sha256','session_id','authorization_sha256')}}
    if any(value[k]!=v for k,v in expected.items()):raise ValueError('Start authorization scope differs from admission')


def _consume_start_claim(root, adapter_factory, readiness, cancelled):
    # Same caller process, no fork/spawn gap or public bearer token.
    with locks.file_mutex(RUN_ROOT/'admission.lock'):
        with locks.file_mutex(locks.LOCK_ROOT/'registry.lock'):
            job,mission,request,limits=_checked(root)
            if job['job_state']!='STARTING' or job['worker'] is not None:
                return {'status':'BLOCKED','reason':'START_ALREADY_CONSUMED'}
            intent=_read(root,'start-intent.json')
            identity=locks.process_identity()
            guard=locks.restriction()
            if (identity is None or identity!=intent['requester'] or guard is None or
                guard['owner_id']!=job['run_id'] or guard.get('input_sha256')!=job['input_sha256'] or
                guard.get('state')!='RESERVED'):
                raise RoverControlError('Start process/reservation changed; do not resume')
            job.update(job_state='RUNNING',worker=identity,started_at=locks.utc_now())
            locks.atomic_json(root/'job.json',job)
    return _execute_ground_job(root,job,mission,request,limits,adapter_factory,readiness,cancelled)


def start_ground_trial(run_id, authorization, *, adapter_factory=None,
                       readiness=check_simulation_ready,cancelled=lambda:False):
    """Explicit start of an existing navigation/pulse admission, synchronous main thread.

    No request-key credential, token recovery, background spawn or automatic retry.
    Recorded scope declaration is not human authentication. Query is separate.
    """
    if adapter_factory is None or not OPERATIONAL_ROVER_ENABLED and not sitl_policy.SITL_TRIAL_POLICY_ENABLED:
        return {'status':'BLOCKED','reason':'OPERATIONAL_ROVER_POLICY_DISABLED_OR_NO_ADAPTER'}
    root=directory(run_id)
    claimed=False
    try:
        with locks.file_mutex(RUN_ROOT/'admission.lock'):
            with locks.file_mutex(locks.LOCK_ROOT/'registry.lock'):
                job,_,request,_=_checked(root)
                if request['kind'] not in ('ROVER_NAVIGATE_V1','ROVER_PULSE_V1'):raise ValueError('Explicit start supports reviewed navigation/pulse admissions only')
                _validate_start_authorization(job,authorization)
                if job['job_state']!='ADMITTED' or job['worker'] is not None or (root/'start-intent.json').exists():
                    return {'status':'BLOCKED','reason':'START_CONSUMED_OR_UNCERTAIN_QUERY_ONLY'}
                gate=policy_gate(request,job['mission_sha256'])
                if gate['status']!='AUTHORIZED':
                    return {'status':'BLOCKED','reason':'OPERATIONAL_ROVER_POLICY_DISABLED','policy_gate':gate}
                job['policy_basis']=gate['basis']
                current=locks.restriction()
                if (current is None or current['owner_id']!=run_id or current.get('state')!='RESERVED'
                        or current.get('input_sha256')!=job['input_sha256']):
                    raise RoverControlError('Start reservation changed')
                requester=locks.process_identity()
                if requester is None:raise RoverControlError('Cannot identify start caller')
                intent={'schema':'tfg.rover.start-intent/1','run_id':run_id,'authorization':authorization,
                        'requester':requester,'at_utc':locks.utc_now(),'spawn':'NONE_CALLER_IS_WORKER',
                        'authorization_basis':'EXPLICIT_DECLARATION_NOT_HUMAN_AUTHENTICATION'}
                import os
                fd=os.open(root/'start-intent.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                claimed=True
                with os.fdopen(fd,'w') as stream:
                    json.dump(intent,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
                parent=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(parent)
                finally:os.close(parent)
                job.update(job_state='STARTING',start_intent_sha256=sha256((root/'start-intent.json').read_bytes()),
                           start_authorization_sha256=fingerprint(authorization))
                locks.atomic_json(root/'job.json',job)
        # Any loss after the durable claim remains STARTING/RUNNING/UNCONFIRMED;
        # another call can only query, never reuse this claim.
        return _consume_start_claim(root,adapter_factory,readiness,cancelled)

    except BaseException as exc:
        if not claimed:raise
        try:
            locks.atomic_json(root/'start-outcome.json',{'status':'START_UNCONFIRMED','run_id':run_id,
                              'error_evidence':error_evidence(exc),'at_utc':locks.utc_now()})
        finally:locks.mark_uncertain(run_id,'v3')
        if not isinstance(exc,Exception):raise
        return {'status':'UNCONFIRMED','reason':'START_CLAIMED_RESPONSE_OR_PERSISTENCE_UNCERTAIN','run_id':run_id}


def run_ground_worker(run_id, launch_token, *, adapter_factory=None, readiness=check_simulation_ready, cancelled=lambda:False):
    """One shot in the owning process. No spawn/restart, no default live adapter.

    A future detached entry can reuse this function after operational policy and
    audited source binding are implemented. No caller can enable the policy.
    """
    if not OPERATIONAL_ROVER_ENABLED or adapter_factory is None:
        return {'status': 'BLOCKED', 'reason': 'OPERATIONAL_ROVER_POLICY_DISABLED_OR_NO_ADAPTER'}
    root = directory(run_id)
    with locks.file_mutex(RUN_ROOT/'admission.lock'):
        job, mission, request, limits = _checked(root)
        if request['kind'] in ('ROVER_NAVIGATE_V1','ROVER_PULSE_V1') or (root/'start-intent.json').exists():
            return {'status':'BLOCKED','reason':'USE_EXPLICIT_START_OR_START_ALREADY_CONSUMED'}
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
    return _execute_ground_job(root,job,mission,request,limits,adapter_factory,readiness,cancelled)


def _execute_ground_job(root,job,mission,request,limits,adapter_factory,readiness,cancelled):
    try:
        report=_run_ground_job(root,job,mission,request,limits,adapter_factory,readiness,cancelled)
    except BaseException:
        if request.get('infrastructure_close'):
            close_ground_infrastructure(job['run_id'])
        raise
    if request.get('infrastructure_close'):
        return close_ground_infrastructure(job['run_id'],report=report)
    return report


def close_ground_infrastructure(run_id,*,report=None):
    """One exact retained owner only. Cleanup never substitutes for vehicle stop."""
    from tools import simulation_lifecycle as lifecycle
    root=directory(run_id)
    try:
        with locks.file_mutex(RUN_ROOT/'admission.lock'):
            job,_,request,_=_checked(root)
            if (request.get('infrastructure_close')!={'kind':'SAME_SESSION_INFRASTRUCTURE_V1'}
                    or not job.get('ground_close_reference') or job['job_state']!='UNCONFIRMED'):
                raise RoverControlError('No retained same-session close scope')
            import os
            claim=root/'infrastructure-close-intent.json'
            if claim.exists():return {'status':'UNCONFIRMED','reason':'CLOSE_ALREADY_CLAIMED_QUERY_AUDIT_NO_REPLAY'}
            fd=os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream:
                json.dump({'run_id':run_id,'input_sha256':job['input_sha256'],'reference_sha256':job['ground_close_reference_sha256'],'at':locks.utc_now()},stream)
                stream.flush();os.fsync(stream.fileno())
            parent=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(parent)
            finally:os.close(parent)
        if report is None:report=_read(root,'failure.json' if (root/'failure.json').exists() else 'report.json')
        locks.atomic_json(root/'pre-infrastructure-report.json',report)
        closed=lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',ground_owner=run_id)
        locks.atomic_json(root/'infrastructure-close.json',{'run_id':run_id,'input_sha256':job['input_sha256'],'result':closed})
        vehicle_resolved=(report.get('closure',{}).get('vehicle_resolution_eligible') is True
            and report.get('closure',{}).get('job_close')=='WAITING_INFRASTRUCTURE'
            and report.get('transport_close',{}).get('status')=='CLOSED')
        resolved=closed.get('status')=='SUCCESS' and vehicle_resolved
        report={**report,'infrastructure_close':closed}
        if not resolved:report['status']='UNCONFIRMED'
        report['closure'].update(job_close='COMMIT_ELIGIBLE' if resolved else 'UNCONFIRMED',
            reservation_release='ELIGIBLE_AFTER_DURABLE_RESULT' if resolved else 'RETAINED')
        locks.atomic_json(root/'closure-report.json',report)
        job.update(job_state='FINISHED' if resolved else 'UNCONFIRMED',closure_report_sha256=sha256((root/'closure-report.json').read_bytes()))
        locks.atomic_json(root/'job.json',job)
        if resolved:locks.release(run_id,'v3')
        return report
    except Exception as exc:
        locks.mark_uncertain(run_id,'v3')
        evidence={'status':'UNCONFIRMED','run_id':run_id,'operation':'close_ground_infrastructure','error_evidence':error_evidence(exc)}
        locks.atomic_json(root/'infrastructure-close-error.json',evidence)
        return evidence


def _run_ground_job(root,job,mission,request,limits,adapter_factory,readiness,cancelled):
    run_id=job['run_id']
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
    close_attempted=False
    def close_transport():
        nonlocal close_attempted
        if adapter is None or close_attempted:return
        close_attempted=True
        report['transport_close']={'status':'UNCERTAIN','source':'OWNING_WORKER_SESSION_CLOSE'}
        with synchronous_deadline(limits.call_timeout_s):adapter.session.close()
        report['transport_close']['status']='CLOSED'
    try:
        with locks.execution_scope(run_id, 'v3'):
            # Recheck exact bytes under authority, then deterministic validation and current readiness.
            _, mission, request, limits = _checked(root)
            if request.get('infrastructure_close'):
                from tools.simulation_lifecycle import ground_close_reference
                job['ground_close_reference']=ground_close_reference(job)
                job['ground_close_reference_sha256']=fingerprint(job['ground_close_reference'])
                locks.atomic_json(root/'job.json',job)
            validation = validate_mission(mission, export_qgc=False)
            report['validation'] = validation
            if validation.get('execution_status') != 'APPROVED' or validation.get('errors'):
                raise RoverControlError('Deterministic validation no longer approves')
            report['readiness'] = readiness(profile=request_profile(request))
            if report['readiness'].get('ready') is not True:
                raise RoverControlError('Current readiness of the rover profile not confirmed')
            vehicles = report['readiness'].get('vehicles')
            if vehicles is not None and not any(v.get('vehicle_id')=='rover_01' and v.get('interface')=='v3'
                    and v.get('status_last_observed')=='PASS' and v.get('prearm_last_observed')=='PASS' for v in vehicles):
                raise RoverControlError('Readiness does not cover an armable rover_01/v3')
            adapter = adapter_factory(journal)
            with synchronous_deadline(limits.call_timeout_s):
                report['capabilities'] = adapter.probe(timeout_s=limits.call_timeout_s)
            if request['kind']=='ROVER_NAVIGATE_V1':
                binding=job['coordination_binding']
                if (report['capabilities'].get('session_id')!=job['session_id']
                        or adapter.binding.pose_reference_sha256!=binding['frame_sha256']):
                    raise RoverControlError('Current transport/session/frame differs from explicit coordination')
            if request['kind']=='ROVER_PULSE_V1':
                context=request['context']
                from tools.rover_environment_identity import digest
                if (report['capabilities'].get('session_id')!=context['lifecycle_id'] or
                        any(report['capabilities'].get(k)!=context[k] for k in ('target_sha256','source_contract_sha256','body_review_sha256')) or
                        report['capabilities'].get('envelope_sha256')!=digest({k:v for k,v in request['safety'].items() if k!='review_sha256'}) or
                        fingerprint(__import__('dataclasses').asdict(adapter.binding))!=request['safety']['binding_sha256']):
                    raise RoverControlError('Current pulse owner/target/source/body differs from authorization')
                source=report['capabilities'].get('observation_source',{})
                available=source.get('remaining_sample_pairs')
                # Lower bound, not a cadence guarantee: two initial pairs,
                # enough progressing pairs to sustain freshness over the pulse,
                # three stop pairs and three for explicit disarm confirmation.
                needed=2+max(0,math.ceil(request['duration_s']/limits.observation_max_age_s)-1)+3+(3 if request.get('finalization') else 0)
                if request.get('preparation'):
                    observed=adapter.current()  # same verified pipe cache, no new pair
                    needed+=-1+2*(observed.mode!=15)+2*(not observed.armed)
                report['observation_budget']={'remaining_pairs':available,'minimum_required_pairs':needed,'guarantees_cadence':False}
                if (source.get('max_samples')!=20 or source.get('duration_s')!=120 or
                        type(available) is not int or not 0<=available<=10 or available<needed):
                    raise RoverControlError('PULSE_OBSERVATION_QUOTA_INSUFFICIENT_OR_UNKNOWN')
            if request.get('finalization') and (report['capabilities'].get('disarm_type')!='ardupilot_msgs/srv/ArmMotors' or report['capabilities'].get('disarm_available') is not True):
                raise RoverControlError('Explicit finalization transport unavailable before motion')
            checked_job, _, _, _ = _checked(root)
            guard = locks.restriction('v3')
            if (checked_job != job or not guard or guard.get('input_sha256') != job['input_sha256']):
                raise RoverControlError('Snapshot, scope or reservation changed during readiness/probe')
            core = RoverControlCore(limits, adapter=adapter, clock=adapter.clock)
            pulse_started=adapter.clock.monotonic()
            prepared=None
            if job.get('policy_admission', {}).get('basis') == 'SITL_TRIAL':
                from tools.rover_target_frame import verify_trial_start
                with synchronous_deadline(limits.call_timeout_s):
                    observation = adapter.current()
                core._validate(observation)
                report['start_pose_review'] = verify_trial_start(
                    request['sitl_trial']['scope']['control_context'], observation)
            if request.get('preparation'):
                job['job_state']='PREPARING';locks.atomic_json(root/'job.json',job)
                prepared=core.prepare_guided_armed(safety=_preparation_safety(request),timeout_s=request['preparation']['timeout_s'],cancelled=cancelled)
                report['preparation']=prepared
                locks.atomic_json(root/'preparation-evidence.json',{'run_id':run_id,'input_sha256':job['input_sha256'],'evidence':prepared})
                job['job_state']='RUNNING';locks.atomic_json(root/'job.json',job)
            if request['kind']=='ROVER_PULSE_V1' and (not prepared or prepared['status']=='GUIDED_ARMED_STATIONARY_OBSERVED') and hasattr(adapter.session,'reserve_observations'):
                adapter.reserve_observations(3+(3 if request.get('finalization') else 0))
            # Core verifies fresh independent motion BEFORE first publication; no arming.
            from dataclasses import replace
            pulse_safety=(replace(PulseSafety(**request['safety']),total_timeout_s=number(request['safety']['total_timeout_s']-(adapter.clock.monotonic()-pulse_started),'pulse remaining after preparation',positive=True)) if request['kind']=='ROVER_PULSE_V1' else None)
            result = ({'status':'UNCONFIRMED','motion_command_attempted':False,'error_evidence':prepared.get('error_evidence'),'stop':prepared.get('stop')}
                      if prepared and prepared['status']!='GUIDED_ARMED_STATIONARY_OBSERVED' else
                      core.navigate(NavigationGoal(**request['goal']),cancelled=cancelled)
                      if request['kind']=='ROVER_NAVIGATE_V1' else
                      core.move_for(request['forward_mps'],request['yaw_rate_rad_s'],request['duration_s'],cancelled=cancelled,
                          safety=pulse_safety,initial_observations=prepared.get('initial_observations') if prepared else None))
            report.update(result=result,control_attempted=result['motion_command_attempted'] or bool(prepared and (prepared['mode_attempted'] or prepared['arm_attempted'])),status=result['status'])
            if request.get('finalization'):
                locks.atomic_json(root/'stop-evidence.json',{'run_id':run_id,'input_sha256':job['input_sha256'],
                    'worker':job['worker'],'goal_outcome':result.get('goal_outcome'),'stop':result.get('stop')})
                job['job_state']='FINALIZING';locks.atomic_json(root/'job.json',job)
                finalization_timeout=request['finalization']['timeout_s']
                if request['kind']=='ROVER_PULSE_V1':
                    finalization_timeout=min(finalization_timeout,number(
                        request['safety']['total_timeout_s']-(adapter.clock.monotonic()-pulse_started)-request['safety']['close_budget_s'],
                        'pulse finalization remaining',positive=True))
                report['finalization']=core.finalize_disarmed(result.get('stop'),timeout_s=finalization_timeout)
            if request['kind']=='ROVER_NAVIGATE_V1':
                report['r1']={'schema':'tfg.rover.navigation-result/1','run_id':run_id,
                    'input_sha256':job['input_sha256'],'worker':job['worker'],
                    'mission_sha256':job['mission_sha256'],'request_sha256':job['request_sha256'],
                    'goal_outcome':result['goal_outcome'],'samples':result['observation_samples'],
                    'samples_sha256':fingerprint(result['observation_samples']),
                    'goal_sha256':fingerprint(result['goal']),'sample_limit':result['sample_limit'],
                    'commands_sent':result['commands_sent'],'stop_requested':result['stop_requested'],
                    'stop_observed':bool(result.get('stop',{}).get('stationary_observed')) if result.get('stop') else False,
                    'source_association_verified':False,'movement_authorized_by_report':False}

            if request['kind']=='ROVER_NAVIGATE_V1':
                # Structural R1 contract only: missing candidate/session association
                # remains explicit. Do not invent coordinator bindings or label EXECUTED.
                report['r1_ground_result']={
                    'schema':'tfg.agri-r1-ground-result/1',
                    'origin':'SYNTHETIC_TEST_DOUBLE' if getattr(adapter.session,'synthetic_model',False) else 'UNVERIFIED_EXECUTOR_OBSERVATIONS',
                    'job_status':result['status'],
                    'binding':{'candidate_sha256':job['coordination_binding']['candidate_sha256'],'mission_sha256':job['mission_sha256'],
                        'authorization_sha256':job['coordination_binding']['authorization_sha256'],'vehicle_id':'rover_01',
                        'simulated_vehicle':'v3','session_id':job['session_id'],'ground_run_id':run_id},
                    'binding_unresolved':[],'binding_basis':'EXPLICIT_SNAPSHOTS_PLUS_CURRENT_TRANSPORT_SESSION_NOT_HUMAN_AUTHENTICATION',
                    'frame':{'name':request['goal']['frame'],'transform_status':'DECLARED_ADAPTER_BINDING_NOT_INDEPENDENTLY_VERIFIED'},
                    'samples':[{'x_m':s['position_m'][0],'y_m':s['position_m'][1],
                        'frame':s['pose_frame'],'linear_mps':sum(v*v for v in s['linear_mps'])**.5,
                        'angular_rad_s':sum(v*v for v in s['angular_rad_s'])**.5,
                        'source_stamp_ns':s['velocity_source_ns'],
                        'received_monotonic_s':s['motion_received_monotonic_s'],
                        'message_publisher_gid':s['odometry_publisher_gid']} for s in result['observation_samples']],
                    'commands':{'attempted':result['motion_command_attempted'],
                        'sent':result['commands_sent'],'started_monotonic_s':result['started_monotonic_s']},
                    'stop':{'status':result['stop']['status'] if result.get('stop') else 'NOT_REQUESTED',
                            'requested':result['stop_requested'],
                            'observed':bool(result.get('stop') and result['stop'].get('stationary_observed'))},
                    'decision_monotonic_s':result['decision_monotonic_s'],
                    'source_association_verified':False,'movement_authorized_by_report':False}
            report.update(result=result, control_attempted=result['motion_command_attempted'] or bool(prepared and (prepared['mode_attempted'] or prepared['arm_attempted'])), status=result['status'])
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
            finalized=report.get('finalization',{}).get('status')=='DISARMED_STATIONARY_OBSERVED'
            releasable = no_control or disarmed_stop or finalized
            if request['kind']=='ROVER_PULSE_V1':
                # The reviewed entry expects an already armed rover. Even an
                # abort before publication cannot certify its state as resolved.
                releasable=disarmed_stop or finalized
            if request['kind']=='ROVER_PULSE_V1' and not releasable:report['status']='UNCONFIRMED'
            report['closure']={'goal_outcome':result.get('goal_outcome','NOT_APPLICABLE'),
                'vehicle_resolution_eligible':releasable,
                'stop_observed':stop.get('stationary_observed') is True,
                'armed_observed':False if finalized or disarmed_stop else (samples[-1].get('armed') if samples else None),
                'job_close':'COMMIT_ELIGIBLE' if releasable else 'UNCONFIRMED',
                'vehicle_close':'DISARMED_STATIONARY_OBSERVED' if finalized or disarmed_stop else 'UNCONFIRMED',
                'reservation_release':'ELIGIBLE_AFTER_DURABLE_RESULT' if releasable else 'RETAINED'}
            if request.get('finalization'):
                if request['kind']=='ROVER_PULSE_V1':
                    completed=result.get('status')=='STOP_OBSERVED'
                    report['pulse_outcome']=('RESPONSE_OBSERVED' if result.get('response_observed') else 'NO_RESPONSE') if completed else 'ABORTED'
                    report['status']=('PULSE_STOP_AND_DISARM_OBSERVED' if completed else 'PULSE_ABORTED_CLOSURE_OBSERVED') if finalized and releasable else 'UNCONFIRMED'
                else:report['status']=('GOAL_REACHED_CLOSURE_OBSERVED' if result.get('goal_outcome')=='GOAL_REACHED' else 'GOAL_FAILED_CLOSURE_OBSERVED') if finalized else 'UNCONFIRMED'
            # Persist finalization and closure before changing job/reservations.
            close_transport()  # an uncertain receiver/resource close must precede any release decision
            if request.get('infrastructure_close'):
                releasable=False
                report['closure'].update(job_close='WAITING_INFRASTRUCTURE',reservation_release='RETAINED_UNTIL_INFRASTRUCTURE')
            locks.atomic_json(root/'report.json',report)
            job['report_sha256']=sha256((root/'report.json').read_bytes())
        # Final job persistence is also required. Any storage error retains uncertainty.
        locks.atomic_json(root/'job.json', {**job, 'job_state': 'FINISHED' if releasable else 'UNCONFIRMED',
                                            'finished_at': locks.utc_now()})
        if releasable:
            locks.release(run_id, 'v3')
        else:
            locks.mark_uncertain(run_id, 'v3')
        return report
    except BaseException as exc:
        try:close_transport()
        except Exception as closing:
            report['transport_close']={'status':'UNCERTAIN','error_evidence':error_evidence(closing)}
        # Includes persistence failure, worker cancellation and controls with uncertain effects.
        locks.mark_uncertain(run_id, 'v3')
        possible_control = any(e.get('operation') == 'control_intent' for e in events)
        known=report.get('result') or {}
        known_stop=known.get('stop') or {}
        report['closure']={'goal_outcome':known.get('goal_outcome','UNKNOWN'),
            'stop_observed':known_stop.get('stationary_observed') is True,
            'vehicle_close':report.get('finalization',{}).get('status','UNKNOWN'),
            'job_close':'UNCONFIRMED','reservation_release':'RETAINED'}
        if request.get('finalization') and 'finalization' not in report:
            report['finalization']={'policy':request['finalization']['kind'],'status':'UNCONFIRMED',
                'disarm_attempted':any(d.get('operation')=='disarm_after_observed_stop' for d in (core.diagnostics if core else [])),
                'error_evidence':error_evidence(exc)}
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
