"""Builder and dry run for the first short SITL rover navigation (about 1 m ahead); no execution.

Everything session-specific comes from a CURRENT accredited MotionBinding and the
CURRENT lifecycle start: start pose, GIDs, pose reference, container execution and
boot. Nothing here starts a simulator, opens a worker, reserves v3 or enables a
policy. dry_run() reports DRY_RUN_ELIGIBLE_EXCEPT_POLICY_FLAG only when the real
SITL gate, fed with real current facts, refuses solely because
SITL_TRIAL_POLICY_ENABLED is False.

Operator statements are never generated: the returned templates carry explicit
placeholders that must be replaced by Joel's own words.
"""
from dataclasses import asdict, replace
import math

from planning.artifact_store import fingerprint, sha256
from tools.rover_control import NavigationGoal, RoverControlError, RoverLimits
from tools.rover_motion_binding import require_current
from tools.rover_pipe_session import HOST_GUARD_S, IPC_RESERVE_S, call_budget, worker_limits
from tools import rover_autopilot_failsafe as autopilot
from tools.rover_target_frame import goal_from_start_offset, start_pose, verify_goal
from tools import rover_sitl_trial_policy as sitl_policy

PROFILE = 'rover_only'
FORWARD_M = 1.0
MAX_DISTANCE_M = autopilot.TRIAL_MAX_DISTANCE_M  # goal bound and runaway area, one value
# Conservative values inside the existing contracts (RoverLimits, NavigationGoal).
LIMITS = RoverLimits(max_forward_mps=0.3, max_yaw_rate_rad_s=0.5, max_duration_s=60.0, call_timeout_s=2.0,
                     stop_timeout_s=8.0, observation_max_age_s=1.0, stopped_linear_mps=0.03, stopped_angular_rad_s=0.03)
GOAL_PARAMETERS = {'unit': 'm', 'transform': 'IDENTITY_SAME_ACCREDITED_FRAME', 'tolerance_m': 0.25,
                   'yaw_tolerance_rad': math.pi, 'dwell_s': 1.0, 'command_hz': 2.0, 'timeout_s': 45.0,
                   'no_progress_s': 15.0, 'progress_m': 0.05, 'progress_rad': 0.05, 'max_samples': 256}
PREPARATION = {'kind': 'GUIDED_ARM_AFTER_STATIONARY_V1', 'timeout_s': 20.0}
FINALIZATION = {'kind': 'DISARM_AFTER_OBSERVED_STOP_V1', 'timeout_s': 10.0}
MAX_SLOPE_RAD = 0.2
# Worker's own limits (hello): host silence that trips its safe stop, and its hard session lifetime
# (worst case of the whole trial is 87 s of wall clock; see docs/rover-first-navigation-sitl.md §5.4).
WORKER_WATCHDOG_S = 3.0
WORKER_MAX_SESSION_S = 120.0

# -- control timing -----------------------------------------------------------------
# Four different frequencies, never to be confused:
#   simulation status rate (ArduPilot, about 2 Hz of SIMULATED time),
#   wall status rate (= simulated rate x RTF; 1.2 Hz measured in rover_only at RTF 0.6),
#   requested command rate (goal.command_hz, an upper bound: the loop sleeps 1/command_hz),
#   effective command rate (<= wall status rate: every command waits for a NEW status pair).
# The freshness limit must cover one wall status period (two consecutive new observations are
# validated together) plus the pipe; it must also keep the distance the rover can cover during
# that age within the arrival tolerance. If not, the speed is lowered; if that is not enough, or
# a new status cannot arrive within one host call, the trial is NOT_VIABLE.
STATUS_JITTER = 1.25          # a status period can stretch this much (irregular delivery)
AGE_HARD_CAP_S = 1.5          # never accept observations older than this, whatever the cadence
MIN_FORWARD_MPS = 0.1         # below this the trial is not worth running: NOT_VIABLE
SPEED_STEP_MPS = 0.05
STOP_TIMEOUT_CAP_S = 12.0
MIN_RTF = 0.3                 # below this nothing is derived: NOT_VIABLE


CADENCE_MAX_AGE_S = 600.0     # metrics older than this (host monotonic clock) are not a current measurement


def cadence_from_metrics(metrics, *, lifecycle_id, environment_execution, host_boot_id=None, now_monotonic_ns=None):
    """Cadence of THIS lifecycle from tools.rover_sim_metrics output ({'summary', 'raw'}) taken in it.

    The metrics carry no lifecycle id: the caller binds them, and they must come from the same
    container execution and end less than CADENCE_MAX_AGE_S ago on this host's monotonic clock
    (a historical file from another boot or day is refused). Monotonic times are only comparable within one
    boot, so the metrics must carry the boot_id they were taken in and it must be this host's current boot
    (``host_boot_id``, read from the kernel when omitted); metrics without it are refused. Within one boot the
    same container can run several executions and lifecycles: the metrics must also carry the binding sealed at
    acquisition (tools.rover_sim_metrics.collect) and it must name this lifecycle and this exact container
    execution (persistent identity, start time and boot); metrics without it, or of another execution or lifecycle,
    are refused.
    """
    import time
    summary, raw = metrics.get('summary') or {}, metrics.get('raw') or {}
    now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    end = raw.get('wall_end_ns')
    if host_boot_id is None:
        from pathlib import Path
        host_boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if (not isinstance(raw.get('boot_id'), str) or not raw['boot_id'] or raw['boot_id'] != host_boot_id
            or type(end) is not int or not 0 <= now - end <= CADENCE_MAX_AGE_S * 1e9):
        raise RoverControlError('Metrics are not a current measurement on this host (other or unknown boot, age '
                                'unknown or too old)')
    from tools.rover_sim_metrics import BINDING_SCHEMA
    binding = metrics.get('binding')
    if (not isinstance(binding, dict) or binding.get('schema') != BINDING_SCHEMA
            or binding.get('lifecycle_id') != lifecycle_id
            or binding.get('environment_execution') != environment_execution
            or (binding.get('environment_execution') or {}).get('container_boot_id') != raw.get('boot_id')):
        raise RoverControlError('Metrics are not bound to this lifecycle and container execution '
                                '(binding absent, ambiguous or of another execution)')
    container = environment_execution['persistent_identity']['container_id']
    status = summary.get('status') or {}
    if (summary.get('schema') != 'tfg.rover.sim-metrics/2' or (summary.get('docker_stats') or {}).get('Container') != container
            or summary.get('stale_streams') or not status.get('fresh') or not status.get('stamps_strictly_increasing')
            or not (summary.get('odometry') or {}).get('fresh')):
        raise RoverControlError('Metrics are not a fresh, consistent measurement of this container execution')
    return {'lifecycle_id': lifecycle_id, 'container_id': container, 'rtf': number_or_fail(summary.get('real_time_factor')),
            'status_hz_wall': number_or_fail(status.get('rate_per_wall_s')),
            'status_hz_sim': number_or_fail(status.get('rate_per_sim_s')),
            'window_wall_s': number_or_fail(summary.get('window_wall_s')), 'metrics_sha256': fingerprint(metrics),
            'source': 'tools.rover_sim_metrics'}


def number_or_fail(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise RoverControlError('Missing or invalid cadence value')
    return float(value)


def _stop_worst_case_ok(stop_timeout_s, call_s, need_s):
    """RoverControlCore.stop: pre-observation, zero, HOLD, then TWO new observations, each op at its full share."""
    pre = min(call_s, stop_timeout_s / 6)
    zero = min(call_s, (stop_timeout_s - pre) / 4)
    hold = min(call_s, (stop_timeout_s - pre - zero) / 3)
    rest = stop_timeout_s - pre - zero - hold
    try:
        first = call_budget(min(call_s, rest / 2))['worker_s']
    except TimeoutError:
        return False
    return first >= need_s and rest >= 2 * (need_s + IPC_RESERVE_S + HOST_GUARD_S)


def control_timing(cadence, *, lifecycle_id, limits=LIMITS, goal=None, forward_m=FORWARD_M):
    """Deterministic derivation from the measured cadence; never looser than LIMITS or the hard caps."""
    goal = dict(GOAL_PARAMETERS if goal is None else goal)
    reasons = []
    if cadence.get('lifecycle_id') != lifecycle_id:
        raise RoverControlError('Cadence was not measured in this lifecycle')
    rtf, status_hz = number_or_fail(cadence.get('rtf')), number_or_fail(cadence.get('status_hz_wall'))
    period = 1.0 / status_hz
    need = period * STATUS_JITTER                                  # wait for one new status, with jitter
    worker_wait = call_budget(limits.call_timeout_s)['worker_s']    # what one observe call can wait
    age_needed = need + IPC_RESERVE_S + HOST_GUARD_S
    age = math.ceil(age_needed * 20) / 20                           # 0.05 s steps
    speed = limits.max_forward_mps
    if rtf < MIN_RTF:
        reasons.append('RTF_BELOW_MINIMUM')
    if need > worker_wait:
        reasons.append('NO_NEW_STATUS_WITHIN_ONE_CALL')
    if age > AGE_HARD_CAP_S:
        reasons.append('OBSERVATION_AGE_ABOVE_HARD_CAP')
    # A measured low RTF is not a guaranteed bound on the next wall-clock interval.
    # Do not credit slow simulation with reducing the stale-observation envelope.
    distance_factor = max(1.0, rtf)
    while speed * distance_factor * age > goal['tolerance_m'] and speed - SPEED_STEP_MPS >= MIN_FORWARD_MPS - 1e-9:
        speed = round(speed - SPEED_STEP_MPS, 3)
    if speed * distance_factor * age > goal['tolerance_m']:
        reasons.append('MOTION_DURING_OBSERVATION_AGE_EXCEEDS_TOLERANCE')
    # Independent stop layer: ArduRover's GUID_TIMEOUT (simulated seconds) must be longer than the nominal
    # interval between two velocity setpoints, yet short enough that speed x GUID_TIMEOUT + braking fits the
    # runaway budget. Lower the speed until such a window exists (rover_autopilot_failsafe).
    budget = autopilot.runaway_budget_m(forward_m=forward_m, tolerance_m=goal['tolerance_m'], max_distance_m=MAX_DISTANCE_M)
    nominal_interval_sim = age_needed * rtf

    def no_window(value):
        top = autopilot.required_guided_timeout_s(value, budget_m=budget)
        return top is None or top <= nominal_interval_sim
    while no_window(speed) and speed - SPEED_STEP_MPS >= MIN_FORWARD_MPS - 1e-9:
        speed = round(speed - SPEED_STEP_MPS, 3)
    if no_window(speed):
        reasons.append('NO_AUTOPILOT_TIMEOUT_WINDOW_FOR_RUNAWAY_BUDGET')
    stop = limits.stop_timeout_s
    while not _stop_worst_case_ok(stop, limits.call_timeout_s, need) and stop + 0.5 <= STOP_TIMEOUT_CAP_S:
        stop += 0.5
    if not _stop_worst_case_ok(stop, limits.call_timeout_s, need):
        reasons.append('STOP_CANNOT_OBSERVE_TWO_NEW_STATUS_IN_BUDGET')
    travel_wall = forward_m / max(speed * rtf, 1e-9)
    if travel_wall + goal['dwell_s'] + 2 * need > goal['timeout_s']:
        reasons.append('GOAL_TIMEOUT_TOO_SHORT_FOR_THIS_RTF')
    if goal['progress_m'] > speed * rtf * goal['no_progress_s']:
        reasons.append('NO_PROGRESS_WINDOW_TOO_SHORT')
    derived = replace(limits, max_forward_mps=speed, observation_max_age_s=age, stop_timeout_s=stop)
    return {'status': 'NOT_VIABLE' if reasons else 'VIABLE', 'reasons': reasons, 'limits': derived,
            'frequencies': {'status_hz_sim': cadence.get('status_hz_sim'), 'status_hz_wall': status_hz,
                            'rtf': rtf, 'command_hz_requested': goal['command_hz'],
                            'command_hz_effective_max': min(goal['command_hz'], status_hz)},
            'derivation': {'status_period_wall_s': period, 'status_wait_needed_s': need,
                           'worker_wait_per_call_s': worker_wait, 'observation_age_needed_s': age_needed,
                           'distance_during_age_m': speed * distance_factor * age, 'tolerance_m': goal['tolerance_m'],
                           'runaway_budget_m': budget,
                           'autopilot_guid_timeout_window_s': [nominal_interval_sim,
                                                               autopilot.required_guided_timeout_s(speed, budget_m=budget)],
                           'distance_rtf_upper_assumption': distance_factor,
                           'travel_wall_s': travel_wall, 'stop_timeout_s': stop},
            'cadence_sha256': fingerprint(cadence), 'movement_authorized': False}
PLACEHOLDER = '<<JOEL_STATEMENT_REQUIRED>>'


def build_trial(evidence, *, lifecycle_id, environment_execution, host_boot_id, mission_bytes, cadence,
                autopilot_failsafe=None, forward_m=FORWARD_M):
    """Request, candidate, SITL scope and authorization templates for ONE current session.

    cadence: the status rate and RTF measured in THIS lifecycle (cadence_from_metrics); the
    limits are derived from it by control_timing() and the trial is refused if NOT_VIABLE.
    autopilot_failsafe: GUID_TIMEOUT and braking limits READ in THIS lifecycle
    (rover_autopilot_failsafe.autopilot_fact). Without it, or if its GUID_TIMEOUT cannot bound
    the travel after a loss of host/worker/DDS, the trial is refused: the worker's own stop
    needs the worker and DDS alive, so it is not an independent layer.
    """
    binding = require_current(evidence, lifecycle_id=lifecycle_id, environment_execution=environment_execution,
                              host_boot_id=host_boot_id)
    if not 0 < forward_m <= MAX_DISTANCE_M:
        raise RoverControlError('Forward offset outside (0, MAX_DISTANCE_M]')
    timing = control_timing(cadence, lifecycle_id=lifecycle_id, forward_m=forward_m)
    if timing['status'] != 'VIABLE':
        raise RoverControlError('Control timing NOT_VIABLE for the measured cadence: ' + ', '.join(timing['reasons']))
    limits = timing['limits']
    start = start_pose(evidence)
    target = goal_from_start_offset(start, forward_m=forward_m, left_m=0.0, max_distance_m=MAX_DISTANCE_M)
    verify_goal(target, evidence, binding)
    point = target['target_in_rover_frame']
    goal = NavigationGoal(x_m=point['x_m'], y_m=point['y_m'], yaw_rad=point['yaw_rad'], frame='odom', **GOAL_PARAMETERS)
    if goal.timeout_s > limits.max_duration_s:
        raise RoverControlError('Goal timeout exceeds the trial duration limit')
    mission_sha256 = sha256(mission_bytes)
    request = {'kind': 'ROVER_NAVIGATE_V1', 'profile': PROFILE, 'limits': asdict(limits), 'goal': asdict(goal),
               'preparation': dict(PREPARATION), 'finalization': dict(FINALIZATION),
               'preparation_safety': {'binding_sha256': fingerprint(asdict(binding)), 'pose_frame': 'odom',
                                      'max_slope_rad': MAX_SLOPE_RAD},
               }
    own_limits = worker_limits(limits, watchdog_s=WORKER_WATCHDOG_S, max_session_s=WORKER_MAX_SESSION_S)
    failsafe = autopilot.trial_entry(autopilot_failsafe, limits=asdict(limits), goal=asdict(goal), forward_m=forward_m,
                                     max_distance_m=MAX_DISTANCE_M, worker_limits=own_limits,
                                     timing={**timing, 'limits': asdict(limits)}, lifecycle_id=lifecycle_id,
                                     environment_execution=environment_execution, host_boot_id=host_boot_id)
    context = {'start_pose': start, 'start_tolerance': {'position_m': 0.05, 'yaw_rad': 0.05},
               'cadence': dict(cadence), 'worker_limits': own_limits,
               'control_timing': {**timing, 'limits': asdict(limits)}, 'autopilot_failsafe': failsafe}
    scope = sitl_policy.trial_scope(environment_execution=environment_execution, host_boot_id=host_boot_id,
                                    lifecycle_id=lifecycle_id, profile=PROFILE, mission_sha256=mission_sha256,
                                    goal_sha256=fingerprint(asdict(goal)), binding_evidence_sha256=evidence['evidence_sha256'],
                                    request=request, control_context=context)
    request['sitl_trial'] = {'scope': scope, 'authorization': PLACEHOLDER, 'binding_evidence': evidence}
    candidate = {'vehicle_id': 'rover_01', 'rover_mission': {'value': {'sha256': mission_sha256}},
                 'target_in_rover_frame': {'value': {'x_m': goal.x_m, 'y_m': goal.y_m, 'frame': 'odom'}},
                 'frame_transform': {'value': {k: target['frame_transform'][k] for k in
                                               ('status', 'to_frame', 'sha256', 'derivation_sha256', 'goal_sha256',
                                                'start_evidence_sha256', 'method')}},
                 'preparation_policy': {'value': dict(PREPARATION)}, 'finalization_policy': {'value': dict(FINALIZATION)}}
    return {'schema': 'tfg.rover.first-navigation-trial/1', 'profile': PROFILE, 'forward_m': forward_m,
            'start': start, 'target': target, 'request': request, 'candidate': candidate,
            'scope': scope, 'scope_sha256': fingerprint(scope),
            'required_sitl_authorization': sitl_policy.expected_authorization(scope),
            'templates': {
                'admission_authorization': {'mission_sha256': mission_sha256, 'request_fingerprint': None,
                                            'statement': PLACEHOLDER},
                'coordination_authorization': {'source': 'OPERATOR_DECLARED', 'statement': PLACEHOLDER,
                                               'candidate_sha256': fingerprint(candidate),
                                               'mission_sha256': mission_sha256, 'session_id': lifecycle_id}},
            'worker_limits': own_limits, 'autopilot_failsafe': failsafe,
            'control_timing': {**timing, 'limits': asdict(limits)}, 'cadence': dict(cadence),
            'binding': asdict(binding), 'movement_authorized': False}


def with_operator_statements(trial, *, sitl_authorization, admission_statement, coordination_statement):
    """Insert Joel's own texts verbatim; rejects placeholders and a SITL text for another scope."""
    context = trial['scope'].get('control_context', {})
    if (fingerprint(trial['scope']) != trial['scope_sha256']
            or trial['scope'].get('request_contract_sha256') != sitl_policy.request_contract(trial['request'])
            or any(context.get(k) != trial.get(v) for k, v in
                   [('start_pose', 'start'), ('cadence', 'cadence'), ('worker_limits', 'worker_limits'),
                    ('control_timing', 'control_timing'), ('autopilot_failsafe', 'autopilot_failsafe')])):
        raise RoverControlError('Trial control scope changed; rebuild and obtain a new declaration')
    for text in (admission_statement, coordination_statement):
        if not isinstance(text, str) or not text.strip() or PLACEHOLDER in text:
            raise RoverControlError('Operator statements must be provided verbatim by the operator')
    if sitl_authorization != trial['required_sitl_authorization']:
        raise RoverControlError('SITL authorization does not name this exact scope')
    request = {**trial['request'], 'sitl_trial': {**trial['request']['sitl_trial'], 'authorization': sitl_authorization}}
    admission = {**trial['templates']['admission_authorization'], 'request_fingerprint': fingerprint(request),
                 'statement': admission_statement}
    coordination = {**trial['templates']['coordination_authorization'], 'statement': coordination_statement}
    return {'request': request, 'authorization': admission,
            'coordination_context': {'candidate': trial['candidate'], 'authorization': coordination}}


def dry_run(trial, *, facts=None):
    """Real gate with real current facts (or injected ones in tests); writes nothing."""
    from tools import rover_ground_executor as ground
    request = {**trial['request'], 'sitl_trial': {**trial['request']['sitl_trial'],
                                                  'authorization': trial['required_sitl_authorization']}}
    gate = ground.policy_gate(request, trial['scope']['mission_sha256'], facts=facts)
    reasons = gate.get('reasons', [])
    eligible = gate['status'] == 'BLOCKED' and reasons == ['SITL_TRIAL_POLICY_DISABLED']
    return {'status': 'DRY_RUN_ELIGIBLE_EXCEPT_POLICY_FLAG' if eligible else 'BLOCKED', 'gate': gate,
            'scope_sha256': trial['scope_sha256'],
            'required_sitl_authorization': trial['required_sitl_authorization'] if eligible else None,
            'movement_authorized': False}
