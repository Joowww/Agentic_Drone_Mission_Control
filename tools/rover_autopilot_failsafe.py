"""Independent ArduRover stop layer for the first SITL navigation: facts, required value and envelope.

Nothing here reads or writes ArduPilot parameters, opens ROS, Docker or a worker. It
answers three questions from code that can be checked offline:

1. What the autopilot does on its own when commands stop arriving (SOURCE_FACTS, taken
   from the ArduPilot tree sealed in evaluation/operations/rover_status_diagnostic_build_2026_10_31;
   tests re-hash those files).
2. Which value of that protection the first trial needs (required_guided_timeout_s),
   derived from the trial geometry and speed, not chosen arbitrarily.
3. Whether a value READ LIVE in the same lifecycle (autopilot_fact) satisfies it, and how
   far the rover can travel in each loss scenario A-G (runaway_envelope).

Key facts (ArduPilot 755258dbb, Rover):
- AP_DDS /ap/v3/cmd_vel (TwistStamped, frame base_link) -> AP_ExternalControl_Rover ->
  ModeGuided::set_desired_turn_rate_and_speed: sub-mode TurnRateAndSpeed, timestamp reset.
  Accepted only in GUIDED and armed.
- In that sub-mode, no new setpoint for GUID_TIMEOUT seconds (default 3.0, range 0.1-5)
  -> "target not received last X secs, stopping" and stop_vehicle(): throttle to stop,
  steering 0. It neither changes mode nor disarms. The clock is AP_HAL::millis(), i.e.
  SIMULATED time in SITL: GUID_TIMEOUT x commanded speed is a distance in simulated metres,
  whatever the RTF.
- Nothing in AP_DDS turns an agent/DDS loss into a failsafe: DDS_TIMEOUT_MS/DDS_MAX_RETRY
  only govern the connection ping. FS_GCS_ENABLE (default 0) watches MAVLink GCS
  heartbeats, not DDS. FS_THR_* is RC throttle. None of them covers our transport.
- Our defaults files (rover.parm, rover-skid.parm, dds_udp.parm, dds_use_ns.parm) do not set
  GUID_TIMEOUT, ATC_ACCEL_MAX or ATC_DECEL_MAX. But SITL keeps eeprom.bin in the instance
  directory (use_instance_dir True, wipe False), so a value stored earlier wins over the
  compiled default: the EFFECTIVE value is unknown until read in the running lifecycle.

So the one layer that survives every loss of host, worker, pipe or DDS is GUID_TIMEOUT, and
only if its live value is short enough for the speed. With the default 3.0 s it is not
(see required_guided_timeout_s); the trial stays NO_GO until a reviewed, authorized change
of that parameter is made and then read back live.
"""
import math

from planning.artifact_store import fingerprint
from tools.rover_control import RoverControlError

SOURCE_ROOT = ('evaluation/operations/rover_status_diagnostic_build_2026_10_31/'
               'c29d228d-3170-49ca-a0cb-b93b5874b9f8/source/ardupilot')
SOURCE_COMMIT = '755258dbb452f46dc7e1e47a36591f3b62e8830d'
# File -> (sha256 of the sealed copy, listed in its SHA256SUMS; what it establishes). Re-hashed by the tests.
SOURCE_FACTS = {
    'Rover/mode_guided.cpp': (
        'c7fb1892849305ad281b61f68d91b99dd8f13ecd724936a270dd11790278be2d', 'TurnRateAndSpeed: no setpoint for get_timeout_ms() -> have_attitude_target=false -> '
        'stop_vehicle(); get_timeout_ms() = MAX(GUID_TIMEOUT, 0.1) s; timer reset by set_desired_turn_rate_and_speed'),
    'Rover/Parameters.cpp': (
        'c9a8d99cdf8d0e3f37dacce6880821e8b10ccc1eab5d02d48a1c5fda5de8a96c', 'GUID_TIMEOUT default 3.0 s, range 0.1-5; FS_ACTION Hold; FS_TIMEOUT 1.5 s; FS_GCS_ENABLE disabled; '
        'FS_CRASH_CHECK disabled'),
    'Rover/AP_ExternalControl_Rover.cpp': (
        'aed06124bfcd86877a97e36bf99283bfccfca700d1562a8e01b953ccf751e053', 'velocity -> set_desired_turn_rate_and_speed, only if in GUIDED and armed'),
    'libraries/AP_DDS/AP_DDS_ExternalControl.cpp': (
        '69fdcd839f9a65f1b8343f0903a25e3064cf4856526f10acad3b6543d7cd9cd9', 'cmd_vel frame base_link/map -> set_linear_velocity_and_yaw_rate; any other frame is ignored'),
    'libraries/AP_DDS/AP_DDS_Client.cpp': (
        'd4e123720ea937e1f73525b4441d56fde8d965bfc35334989bf0a6dab0f6d806', 'DDS_TIMEOUT_MS and DDS_MAX_RETRY are connection ping settings; no control failsafe'),
    'libraries/APM_Control/AR_AttitudeControl.cpp': (
        '1344a09c0883f303849c0ca9c6720b54ffbf80ef9f223ed27569a4414fed7543', 'ATC_ACCEL_MAX default 1.0 m/s/s; ATC_DECEL_MAX default 0 (then the acceleration limit applies)'),
}
COMPILED_DEFAULTS = {'GUID_TIMEOUT': 3.0, 'ATC_ACCEL_MAX': 1.0, 'ATC_DECEL_MAX': 0.0, 'FS_GCS_ENABLE': 0,
                     'FS_ACTION': 2, 'FS_CRASH_CHECK': 0}
GUID_TIMEOUT_RANGE = (0.1, 5.0)
# Read these (read-only GetParameters on /ap/v3/get_parameters) in the SAME lifecycle as the trial.
PARAMETERS = ('GUID_TIMEOUT', 'ATC_ACCEL_MAX', 'ATC_DECEL_MAX', 'FS_GCS_ENABLE', 'FS_ACTION', 'FS_CRASH_CHECK')
FACT_SCHEMA = 'tfg.rover.autopilot-failsafe-fact/1'
# Reviewed trial area: no goal farther than this from the accredited start, and no runaway beyond it.
# rover_first_navigation.MAX_DISTANCE_M is this value; the executor gate reads it from here.
TRIAL_MAX_DISTANCE_M = 1.5
FACT_SOURCE = 'AP_DDS_GET_PARAMETERS_READ_ONLY'

# Declared assumptions, to be measured in an authorized operational commissioning (not here):
SPEED_OVERSHOOT_ALLOWANCE = 1.25   # the speed controller may exceed the commanded speed by this factor
MAX_CREDITED_DECEL_MPS2 = 1.0      # never credit stronger braking than this, whatever ATC_*_MAX says
TIMEOUT_STEP_S = 0.1


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RoverControlError(f'{name} must be a finite number')
    return float(value)


def braking_distance_m(speed_mps, accel_max, decel_max):
    """Distance to stop from speed at the autopilot's configured deceleration (ATC_DECEL_MAX, else ATC_ACCEL_MAX)."""
    decel = decel_max if decel_max > 0 else accel_max
    if decel <= 0:
        return math.inf  # no limit configured: the controller's behaviour is not bounded by these parameters
    return speed_mps ** 2 / (2 * min(decel, MAX_CREDITED_DECEL_MPS2))


def runaway_budget_m(*, forward_m, tolerance_m, max_distance_m):
    """Travel allowed AFTER the last command, from the farthest point where a non-zero command may be in effect.

    The host never commands forward speed once an observation is within tolerance of the goal, and the
    observation-age derivation keeps travel during that age within tolerance: so the farthest onset is
    forward_m + tolerance_m. Beyond max_distance_m (the bound the goal itself is checked against) is
    outside the reviewed trial area.
    """
    return max_distance_m - (forward_m + tolerance_m)


def required_guided_timeout_s(speed_mps, *, budget_m, accel_max=COMPILED_DEFAULTS['ATC_ACCEL_MAX'],
                              decel_max=COMPILED_DEFAULTS['ATC_DECEL_MAX']):
    """Largest GUID_TIMEOUT (0.1 s steps, simulated seconds) keeping the uncontrolled travel within budget_m."""
    speed = speed_mps * SPEED_OVERSHOOT_ALLOWANCE
    room = budget_m - braking_distance_m(speed, accel_max, decel_max)
    if speed <= 0 or room <= 0:
        return None
    value = math.floor(room / speed / TIMEOUT_STEP_S + 1e-9) * TIMEOUT_STEP_S
    return round(value, 1) if value >= GUID_TIMEOUT_RANGE[0] else None


def autopilot_fact(values, *, lifecycle_id, environment_execution, host_boot_id, source=FACT_SOURCE):
    """A live read of PARAMETERS in ONE lifecycle; validated, never defaulted or completed."""
    if source != FACT_SOURCE:
        raise RoverControlError('Autopilot parameters must come from a read-only GetParameters of this lifecycle')
    if not isinstance(values, dict) or set(values) != set(PARAMETERS):
        raise RoverControlError('Autopilot fact must carry exactly ' + ', '.join(PARAMETERS))
    clean = {k: _number(values[k], k) for k in PARAMETERS}
    low, high = GUID_TIMEOUT_RANGE
    if not low <= clean['GUID_TIMEOUT'] <= high:
        raise RoverControlError('GUID_TIMEOUT outside the range ArduRover accepts')
    if clean['ATC_ACCEL_MAX'] < 0 or clean['ATC_DECEL_MAX'] < 0:
        raise RoverControlError('Negative acceleration limits')
    # Freeze the full execution, including StartedAt; a container ID survives restarts.
    import copy
    fact = {'schema': FACT_SCHEMA, 'source': source, 'lifecycle_id': lifecycle_id, 'host_boot_id': host_boot_id,
            'environment_execution': copy.deepcopy(environment_execution),
            'container_id': environment_execution['persistent_identity']['container_id'],
            'values': clean, 'clock_domain': 'GUID_TIMEOUT_IS_SIMULATED_TIME'}
    return {**fact, 'fact_sha256': fingerprint(fact)}


def runaway_envelope(*, speed_mps, guided_timeout_s, accel_max, decel_max, worker_watchdog_s, rtf_upper,
                     budget_m, op_grace_s=0.5):
    """Worst-case travel after the last accepted command, per loss scenario; only layers that survive it count.

    Distances are simulated metres. Worker layers run on wall clock; at most rtf_upper simulated
    seconds pass per wall second. The autopilot layer runs on simulated time.
    """
    speed = speed_mps * SPEED_OVERSHOOT_ALLOWANCE
    brake = braking_distance_m(speed, accel_max, decel_max)
    autopilot = speed * guided_timeout_s + brake
    watchdog = speed * worker_watchdog_s * rtf_upper + brake
    monitor = speed * (worker_watchdog_s + op_grace_s) * rtf_upper + brake
    layers = {
        'AUTOPILOT_GUID_TIMEOUT': {'independent_of': ['host', 'worker', 'pipe', 'DDS'], 'clock': 'SIMULATED',
                                   'bound_m': autopilot},
        'WORKER_WATCHDOG_ZERO_HOLD': {'requires': ['worker', 'DDS'], 'clock': 'WALL', 'bound_m': watchdog},
        'WORKER_MONITOR_ZERO': {'requires': ['worker monitor thread', 'free publisher', 'DDS'], 'clock': 'WALL',
                                'bound_m': monitor},
        'WORKER_EOF_SAFE_STOP': {'requires': ['worker', 'DDS'], 'clock': 'WALL', 'bound_m': brake},
    }
    # Which layers still act in each scenario. The bound is the best layer that is NOT defeated.
    survives = {
        'A_HOST_WORKER_PIPE_LOST': ['WORKER_EOF_SAFE_STOP', 'WORKER_WATCHDOG_ZERO_HOLD', 'AUTOPILOT_GUID_TIMEOUT'],
        'B_WORKER_MAIN_THREAD_BLOCKED': ['WORKER_MONITOR_ZERO', 'AUTOPILOT_GUID_TIMEOUT'],
        'C_DDS_LOST': ['AUTOPILOT_GUID_TIMEOUT'],
        'D_CMD_VEL_PUBLISH_BLOCKED': ['AUTOPILOT_GUID_TIMEOUT'],
        'E_WORKER_CRASHED': ['AUTOPILOT_GUID_TIMEOUT'],
        'F_TELEMETRY_MISSING': ['WORKER_WATCHDOG_ZERO_HOLD', 'AUTOPILOT_GUID_TIMEOUT'],
        'G_HOLD_SERVICE_UNREACHABLE': ['WORKER_EOF_SAFE_STOP', 'AUTOPILOT_GUID_TIMEOUT'],
    }
    scenarios = {}
    for name, names in survives.items():
        # Layers other than the autopilot depend on components that may be partly degraded in the
        # same event; the GUARANTEED bound uses only the independent layer.
        scenarios[name] = {'layers': names, 'best_case_m': min(layers[n]['bound_m'] for n in names),
                           'guaranteed_m': layers['AUTOPILOT_GUID_TIMEOUT']['bound_m'],
                           'within_budget': layers['AUTOPILOT_GUID_TIMEOUT']['bound_m'] <= budget_m}
    return {'layers': layers, 'scenarios': scenarios, 'budget_m': budget_m, 'speed_bound_mps': speed,
            'braking_m': brake, 'residual': ['G: vehicle may stay armed in GUIDED; reservation must stay held',
                                             'SITL itself frozen: no simulated time passes, no simulated travel']}


def assess(fact, *, limits, goal, forward_m, max_distance_m, worker_watchdog_s, timing, lifecycle_id,
           environment_execution, host_boot_id):
    """VERIFIED_WITHIN_ENVELOPE only for a live fact of THIS lifecycle whose GUID_TIMEOUT bounds the runaway.

    Returns reasons instead of raising so the caller can report every gap at once.
    """
    reasons = []
    speed, tolerance = limits['max_forward_mps'], goal['tolerance_m']
    budget = runaway_budget_m(forward_m=forward_m, tolerance_m=tolerance, max_distance_m=max_distance_m)
    required = required_guided_timeout_s(speed, budget_m=budget)
    rtf = timing['frequencies']['rtf']
    # A normal loop sends one velocity setpoint per new status pair, i.e. at most every
    # observation_age_needed_s of wall time (status period with jitter + pipe reserves). In simulated
    # seconds that is x RTF. A GUID_TIMEOUT not longer than that would stop the rover between two
    # legitimate commands (safe, but the derived timing would no longer describe the trial).
    nominal_interval = timing['derivation']['observation_age_needed_s'] * rtf
    if fact is None:
        reasons.append('AUTOPILOT_FAILSAFE_NOT_READ_IN_THIS_LIFECYCLE')
        envelope = None
    else:
        if (fact.get('schema') != FACT_SCHEMA or fact.get('source') != FACT_SOURCE
                or fact.get('fact_sha256') != fingerprint({k: v for k, v in fact.items() if k != 'fact_sha256'})):
            reasons.append('AUTOPILOT_FACT_INVALID')
        if (fact.get('lifecycle_id') != lifecycle_id or fact.get('host_boot_id') != host_boot_id
                or fact.get('environment_execution') != environment_execution
                or fact.get('container_id') != environment_execution['persistent_identity']['container_id']):
            reasons.append('AUTOPILOT_FACT_FROM_ANOTHER_SESSION')
        values = fact.get('values') or {}
        try:
            # Revalidate even a rehashed fact: the stored assessment is never authority.
            autopilot_fact(values, lifecycle_id=lifecycle_id, environment_execution=environment_execution,
                           host_boot_id=host_boot_id)
            required = required_guided_timeout_s(speed, budget_m=budget, accel_max=values['ATC_ACCEL_MAX'],
                                                 decel_max=values['ATC_DECEL_MAX'])
            envelope = runaway_envelope(speed_mps=speed, guided_timeout_s=_number(values.get('GUID_TIMEOUT'), 'GUID_TIMEOUT'),
                                        accel_max=_number(values.get('ATC_ACCEL_MAX'), 'ATC_ACCEL_MAX'),
                                        decel_max=_number(values.get('ATC_DECEL_MAX'), 'ATC_DECEL_MAX'),
                                        worker_watchdog_s=worker_watchdog_s, rtf_upper=max(1.0, rtf),
                                        budget_m=budget)
        except RoverControlError:
            envelope = None
            reasons.append('AUTOPILOT_FACT_INVALID')
        if envelope is not None:
            timeout = values['GUID_TIMEOUT']
            if required is None or timeout > required + 1e-9:
                reasons.append('GUID_TIMEOUT_TOO_LONG_FOR_RUNAWAY_BUDGET')
            if not all(s['within_budget'] for s in envelope['scenarios'].values()):
                reasons.append('AUTOPILOT_RUNAWAY_EXCEEDS_BUDGET')
            if timeout <= nominal_interval:
                reasons.append('GUID_TIMEOUT_SHORTER_THAN_NOMINAL_COMMAND_INTERVAL')
    return {'status': 'NOT_VERIFIED' if reasons else 'VERIFIED_WITHIN_ENVELOPE', 'reasons': reasons,
            'runaway_budget_m': budget, 'required_guid_timeout_max_s': required,
            'nominal_setpoint_interval_sim_s': nominal_interval,
            'compiled_default_guid_timeout_s': COMPILED_DEFAULTS['GUID_TIMEOUT'],
            'fact_sha256': fact.get('fact_sha256') if fact else None, 'envelope': envelope,
            'movement_authorized': False}


def trial_entry(fact, *, limits, goal, forward_m, max_distance_m, worker_limits, timing, lifecycle_id,
                environment_execution, host_boot_id):
    """What build_trial binds into the SITL scope; raises unless VERIFIED_WITHIN_ENVELOPE."""
    result = assess(fact, limits=limits, goal=goal, forward_m=forward_m, max_distance_m=max_distance_m,
                    worker_watchdog_s=worker_limits['watchdog_s'], timing=timing, lifecycle_id=lifecycle_id,
                    environment_execution=environment_execution, host_boot_id=host_boot_id)
    if result['status'] != 'VERIFIED_WITHIN_ENVELOPE':
        raise RoverControlError('Independent autopilot stop not verified for this trial: ' + ', '.join(result['reasons']))
    return {'fact': fact, 'inputs': {'forward_m': forward_m, 'max_distance_m': max_distance_m}, 'assessment': result}


def verify_trial_entry(entry, *, request, context, scope, max_distance_m):
    """Gate side: recompute from the bound fact and the request; never trust the stored verdict."""
    start, goal = context['start_pose'], request['goal']
    forward = math.hypot(goal['x_m'] - start['x_m'], goal['y_m'] - start['y_m'])
    inputs = entry['inputs']
    if inputs['max_distance_m'] != max_distance_m or abs(inputs['forward_m'] - forward) > 1e-6:
        return 'AUTOPILOT_FAILSAFE_INPUTS_DIFFER'
    again = assess(entry['fact'], limits=request['limits'], goal=goal, forward_m=inputs['forward_m'],
                   max_distance_m=max_distance_m, worker_watchdog_s=context['worker_limits']['watchdog_s'],
                   timing=context['control_timing'], lifecycle_id=scope['lifecycle_id'],
                   environment_execution=scope['environment_execution'], host_boot_id=scope['host_boot_id'])
    if again != entry['assessment']:
        return 'AUTOPILOT_FAILSAFE_ASSESSMENT_DIFFERS'
    if again['status'] != 'VERIFIED_WITHIN_ENVELOPE':
        return 'AUTOPILOT_FAILSAFE_NOT_VERIFIED'
    return None
