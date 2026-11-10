"""First 1 m SITL navigation, prepared and exercised OFFLINE end to end; nothing is ever executed for real.

Real executor, SITL gate, PipeRos2Session, Ros2RoverAdapter and WorkerCore run over an
in-process loopback. Only the vehicle is synthetic: a kinematic ArduRover double that
integrates velocity only in GUIDED and armed. Passing here proves the host logic and
contracts, NOT how ArduRover SITL behaves; see docs/rover-first-navigation-sitl.md.
"""
from dataclasses import asdict
import copy
import math
from pathlib import Path

import pytest

from planning.artifact_store import fingerprint, sha256
from tools import rover_first_navigation as nav, rover_ground_executor as ground, rover_pipe_session as ps
from tools import rover_pipe_worker as w, rover_ros2_adapter as ros, rover_sitl_trial_policy as policy
from tools import vehicle_execution_lock as locks
from tools.rover_control import RoverControlError
from tools.rover_motion_binding import assess
from tests.test_rover_ground_executor import setup  # tmp LOCK_ROOT/RUN_ROOT; blocks real subprocess/Popen
from tests.test_rover_pipe_worker import FakeBackend, Loopback
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE, NOW, Q, raw

ROOT = Path(__file__).resolve().parents[1]
MISSION = ROOT / 'missions/examples/rover_first_navigation_sitl.json'


def evidence():
    return assess(raw(), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                  now_wall_ns=NOW + 10**9)[1]


# SYNTHETIC cadence shaped like rover_only_binding_final_2026_11_03 (1.2 Hz wall, RTF 0.6); a real trial
# must measure its own in the same lifecycle (nav.cadence_from_metrics).
CADENCE = {'lifecycle_id': LIFECYCLE, 'rtf': 0.6, 'status_hz_wall': 1.2, 'status_hz_sim': 2.0, 'window_wall_s': 20.0,
           'source': 'SYNTHETIC_TEST'}


# SYNTHETIC live read of the autopilot's independent stop layer. GUID_TIMEOUT 1.0 s is inside the window this
# trial requires (nominal setpoint interval < GUID_TIMEOUT <= 1.2 s); the compiled default 3.0 s is NOT, and the
# real value has never been read (tools/rover_autopilot_failsafe.py, docs/rover-first-navigation-sitl.md §8).
SYNTHETIC_AUTOPILOT_VALUES = {'GUID_TIMEOUT': 1.0, 'ATC_ACCEL_MAX': 1.0, 'ATC_DECEL_MAX': 0.0, 'FS_GCS_ENABLE': 0,
                              'FS_ACTION': 2, 'FS_CRASH_CHECK': 0}


def autopilot_fact(**changes):
    from tools.rover_autopilot_failsafe import autopilot_fact as make
    return make({**SYNTHETIC_AUTOPILOT_VALUES, **changes}, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                host_boot_id=BOOT)


def trial(cadence=None, **kwargs):
    kwargs.setdefault('autopilot_failsafe', autopilot_fact())
    return nav.build_trial(evidence(), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                           mission_bytes=MISSION.read_bytes(), cadence=dict(cadence or CADENCE), **kwargs)


# ------------------------------------------------------------------ the request --
def test_trial_request_is_one_metre_ahead_in_odom_from_the_accredited_pose():
    t = trial()
    start, goal = t['start'], t['request']['goal']
    heading = math.atan2(2 * (Q[3] * Q[2] + Q[0] * Q[1]), 1 - 2 * (Q[1] ** 2 + Q[2] ** 2))
    assert start['x_m'] == pytest.approx(-0.0012461) and start['y_m'] == pytest.approx(-3.0005524)
    assert math.hypot(goal['x_m'] - start['x_m'], goal['y_m'] - start['y_m']) == pytest.approx(1.0)
    assert goal['x_m'] == pytest.approx(start['x_m'] + math.cos(heading), abs=1e-6)
    assert goal['frame'] == 'odom' and goal['transform'] == 'IDENTITY_SAME_ACCREDITED_FRAME'
    request = t['request']
    assert request['profile'] == 'rover_only' and request['preparation']['kind'] == 'GUIDED_ARM_AFTER_STATIONARY_V1'
    assert request['finalization']['kind'] == 'DISARM_AFTER_OBSERVED_STOP_V1'
    assert ground._request(request).max_forward_mps == 0.15  # wall-age envelope without credit from low RTF
    assert t['candidate']['frame_transform']['value']['sha256'] == t['binding']['pose_reference_sha256']
    assert t['request']['sitl_trial']['authorization'] == nav.PLACEHOLDER and t['movement_authorized'] is False


@pytest.mark.parametrize('bad', ['other_lifecycle', 'other_boot', 'other_container', 'expired'])
def test_trial_cannot_be_built_from_another_or_stale_session(bad):
    ev = evidence()
    kwargs = dict(lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT, mission_bytes=MISSION.read_bytes(),
                  cadence=dict(CADENCE), autopilot_failsafe=autopilot_fact())
    if bad == 'other_lifecycle': kwargs['lifecycle_id'] = '00000000-0000-4000-8000-000000000000'
    elif bad == 'other_boot': kwargs['host_boot_id'] = 'other'
    elif bad == 'other_container':
        execution = copy.deepcopy(EXECUTION); execution['persistent_identity']['container_id'] = 'd' * 64
        kwargs['environment_execution'] = execution
    else: ev = dict(ev, status='EXPIRED')
    with pytest.raises(RoverControlError):
        nav.build_trial(ev, **kwargs)


@pytest.mark.parametrize('forward', [0.0, -1.0, 1.6, 5.0])
def test_goal_outside_the_bounded_offset_is_refused(forward):
    with pytest.raises(RoverControlError):
        trial(forward_m=forward)


def test_statements_are_never_generated_and_authorization_names_one_scope():
    t, other = trial(), trial(forward_m=0.5)
    assert t['scope_sha256'] != other['scope_sha256']
    with pytest.raises(RoverControlError):
        nav.with_operator_statements(t, sitl_authorization=other['required_sitl_authorization'],
                                     admission_statement='A', coordination_statement='B')
    with pytest.raises(RoverControlError):
        nav.with_operator_statements(t, sitl_authorization=t['required_sitl_authorization'],
                                     admission_statement=nav.PLACEHOLDER, coordination_statement='B')


def facts(scope, ev):
    return {'environment_execution': EXECUTION, 'host_boot_id': BOOT, 'lifecycle_id': LIFECYCLE, 'profile': 'rover_only',
            'binding_evidence_sha256': ev['evidence_sha256'], 'trials_consumed': 0}


def test_dry_run_with_current_facts_is_eligible_except_the_disabled_flag():
    result = nav.dry_run(trial(), facts=facts)
    assert result['status'] == 'DRY_RUN_ELIGIBLE_EXCEPT_POLICY_FLAG' and result['gate']['reasons'] == ['SITL_TRIAL_POLICY_DISABLED']
    assert result['required_sitl_authorization'].startswith(policy.AUTHORIZATION_PREFIX + ' ')


@pytest.mark.parametrize('change', ['lifecycle', 'boot', 'execution', 'binding', 'profile', 'consumed'])
def test_dry_run_refuses_when_the_current_environment_differs(change):
    def drifted(scope, ev):
        current = facts(scope, ev)
        if change == 'lifecycle': current['lifecycle_id'] = 'newer-start'
        elif change == 'boot': current['host_boot_id'] = 'rebooted'
        elif change == 'execution': current['environment_execution'] = dict(EXECUTION, container_started_at='later')
        elif change == 'binding': current['binding_evidence_sha256'] = 'f' * 64
        elif change == 'profile': current['profile'] = 'two_drones_rover'
        else: current['trials_consumed'] = 1
        return current
    result = nav.dry_run(trial(), facts=drifted)
    assert result['status'] == 'BLOCKED' and result['required_sitl_authorization'] is None
    assert len(result['gate']['reasons']) > 1


def test_dry_run_without_a_live_environment_is_blocked_not_assumed(monkeypatch):
    def unavailable(scope, ev):
        raise RuntimeError('no active container execution')
    assert nav.dry_run(trial(), facts=unavailable)['status'] == 'BLOCKED'


# ------------------------------------------------------- offline operational flow --
class KinematicRover(FakeBackend):
    """ArduRover double: integrates commanded velocity only in GUIDED (15) and armed; HOLD (4) zeroes it."""
    def __init__(self, clock, *, start=(-0.0012461, -3.0005524), yaw=None):
        super().__init__(clock)
        self.x, self.y = start
        self.yaw = math.atan2(2 * (Q[3] * Q[2] + Q[0] * Q[1]), 1 - 2 * (Q[1] ** 2 + Q[2] ** 2)) if yaw is None else yaw
        self.v = self.w = 0.0
        self.stuck = False

    def spin(self, timeout_s):
        dt = max(timeout_s, 0.01)
        self.clock.now += dt
        if not self.frozen:  # frozen: no new status/odometry pair, the vehicle still moves
            self.t += 1
            self.rx_at = self.clock.now
        if self.mode == 15 and self.armed and not self.stuck:
            self.yaw += self.w * dt
            self.x += self.v * math.cos(self.yaw) * dt
            self.y += self.v * math.sin(self.yaw) * dt
        else:
            self.v = self.w = 0.0

    def latest(self, kind):
        value = super().latest(kind)
        if value is not None and kind == 'odometry':
            pose = value['message']['pose']['pose']
            pose['position'].update(x=self.x, y=self.y, z=0.0949)
            pose['orientation'] = {'x': 0.0, 'y': 0.0, 'z': math.sin(self.yaw / 2), 'w': math.cos(self.yaw / 2)}
            value['message']['twist']['twist']['linear']['x'] = self.v
            value['message']['twist']['twist']['angular']['z'] = self.w
        return value

    def call_mode(self, mode, timeout_s):
        reply = super().call_mode(mode, timeout_s)
        if self.mode == 4:
            self.v = self.w = 0.0
        return reply

    def publish_velocity(self, linear, angular):
        super().publish_velocity(linear, angular)
        if self.mode == 15 and self.armed:
            self.v, self.w = linear, angular


class SimClock:
    def __init__(self):
        self.now = 1000.0
        self.rover = None

    def monotonic(self):
        return self.now

    def sleep(self, dt):
        self.rover.spin(dt)


def run(setup, monkeypatch, *, configure=lambda rover, loop: None, fault=None, readiness=None, rover_factory=None,
        cadence=None):
    """Admit and start the prepared trial through the real executor with the SITL gate enabled IN THIS TEST ONLY."""
    monkeypatch.setattr(ground, 'OPERATIONAL_ROVER_ENABLED', False)
    monkeypatch.setattr(policy, 'SITL_TRIAL_POLICY_ENABLED', True)   # TEST ONLY; the module default stays False
    monkeypatch.setattr(ground, 'sitl_current_facts', facts)
    mission_path = setup[0]
    mission_path.write_bytes(MISSION.read_bytes())
    t = trial(cadence)
    filled = nav.with_operator_statements(t, sitl_authorization=t['required_sitl_authorization'],
                                          admission_statement='SYNTHETIC offline admission',
                                          coordination_statement='SYNTHETIC offline coordination')
    admitted = ground.admit_ground_trial(mission_path, 'first-nav-' + fault if fault else 'first-nav', filled['request'],
                                         filled['authorization'], coordination_context=filled['coordination_context'])
    assert admitted['status'] == 'ADMITTED', admitted
    clock = SimClock()
    rover = (rover_factory or KinematicRover)(clock)
    clock.rover = rover
    holder = {}

    def factory(journal):
        loop = Loopback(rover, clock, fault=fault)
        configure(rover, loop)
        session = ps.PipeRos2Session(loop, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                                     binding_evidence=evidence(), limits=dict(t['worker_limits']),
                                     mode='OPERATIONAL', clock=clock, fence=lambda e: None)  # real authority + motion policy
        holder['loop'], holder['session'] = loop, session
        return ros.Ros2RoverAdapter(session, binding=session.binding, clock=clock, journal=journal)
    q = ground.query_ground_trial(admitted['run_id'])
    start = {'run_id': admitted['run_id'], 'input_sha256': q['input_sha256'],
             **{k: q['coordination_binding'][k] for k in ('candidate_sha256', 'session_id', 'authorization_sha256')},
             'statement': 'SYNTHETIC offline start'}
    ready = readiness or (lambda **kw: {'ready': True, 'vehicles': [{'vehicle_id': 'rover_01', 'interface': 'v3',
                                                                     'status_last_observed': 'PASS', 'prearm_last_observed': 'PASS'}]})
    report = ground.start_ground_trial(admitted['run_id'], start, adapter_factory=factory, readiness=ready)
    return report, rover, holder, admitted


def commands(rover):
    return [('mode', v) if k == 'mode' else ('arm', v) for k, v in rover.calls]


def test_offline_flow_guided_then_arm_then_one_metre_then_hold_and_disarm(setup, monkeypatch):
    report, rover, holder, admitted = run(setup, monkeypatch)
    assert commands(rover)[:2] == [('mode', 15), ('arm', True)]
    assert report['preparation']['status'] == 'GUIDED_ARMED_STATIONARY_OBSERVED'
    assert report['result']['goal_outcome'] == 'GOAL_REACHED' and report['result']['stop']['status'] == 'STATIONARY_OBSERVED'
    assert ('mode', 4) in commands(rover) and commands(rover)[-1] == ('arm', False) and rover.armed is False
    assert report['finalization']['status'] == 'DISARMED_STATIONARY_OBSERVED'
    assert report['status'] == 'GOAL_REACHED_CLOSURE_OBSERVED'
    assert math.hypot(rover.x + 0.0012461, rover.y + 3.0005524) == pytest.approx(1.0, abs=0.3)
    assert max(v for v, _ in rover.sent) <= 0.3 and locks.restriction('v3') is None  # released after closure
    assert ground.query_ground_trial(admitted['run_id'])['status'] == 'FINISHED'


@pytest.mark.parametrize('failure', ['guided_rejected', 'arm_rejected'])
def test_failed_guided_or_arm_never_publishes_motion(setup, monkeypatch, failure):
    def configure(rover, loop):
        if failure == 'guided_rejected': rover.mode_response = {'status': False, 'curr_mode': 0}
        else: rover.arm_result = False
    report, rover, holder, _ = run(setup, monkeypatch, configure=configure)
    assert report['preparation']['status'] != 'GUIDED_ARMED_STATIONARY_OBSERVED'
    assert report['result']['motion_command_attempted'] is False and all(v == 0.0 for v, _ in rover.sent)
    assert ('arm', True) not in commands(rover) if failure == 'guided_rejected' else True


def test_not_armable_readiness_blocks_before_any_command(setup, monkeypatch):
    not_armable = lambda **kw: {'ready': True, 'vehicles': [{'vehicle_id': 'rover_01', 'interface': 'v3',
                                                             'status_last_observed': 'PASS', 'prearm_last_observed': 'FAIL'}]}
    report, rover, holder, _ = run(setup, monkeypatch, readiness=not_armable)
    assert report['status'] == 'UNCONFIRMED' and rover.calls == [] and rover.sent == [] and 'session' not in holder


def test_lost_preparation_reply_is_uncertain_and_keeps_the_reservation(setup, monkeypatch):
    report, rover, holder, admitted = run(setup, monkeypatch, fault='drop')
    assert report['preparation']['status'] != 'GUIDED_ARMED_STATIONARY_OBSERVED'
    assert holder['session'].broken and report['status'] == 'UNCONFIRMED'
    assert locks.restriction('v3') is not None and locks.restriction('v3')['owner_id'] == admitted['run_id']
    assert sum(1 for m in holder['loop'].sent if m.get('op') == 'exchange') == 1  # never resent


@pytest.mark.parametrize('loss', ['eof_mid_navigation', 'publisher_change_mid_navigation'])
def test_loss_of_supervision_mid_navigation_ends_uncertain_and_protected(setup, monkeypatch, loss):
    def configure(rover, loop):
        original = loop.send
        def send(obj):
            velocities = sum(1 for m in loop.sent if m.get('op') == 'exchange'
                             and m['args']['command']['endpoint'] == ros.VELOCITY)
            if velocities >= 3 and obj.get('op') in ('observe', 'exchange'):
                if loss == 'eof_mid_navigation':
                    loop.sent.append(obj)
                    raise ps.TransportClosed('synthetic worker death')
                rover.graph[w.ODOMETRY] = [{'gid': '09' * 24}]
            return original(obj)
        loop.send = send
    report, rover, holder, admitted = run(setup, monkeypatch, configure=configure)
    assert report['status'] == 'UNCONFIRMED' and report['result']['goal_outcome'] in ('GOAL_FAILED', 'NOT_ATTEMPTED')
    assert report['result']['stop']['status'] == 'UNCONFIRMED'  # stop could not be observed through a broken session
    assert locks.restriction('v3')['owner_id'] == admitted['run_id']  # protection kept


def test_no_progress_stops_and_is_observed(setup, monkeypatch):
    report, rover, holder, _ = run(setup, monkeypatch, configure=lambda rover, loop: setattr(rover, 'stuck', True))
    assert report['result']['goal_outcome'] == 'GOAL_FAILED'
    assert report['result']['stop']['status'] == 'STATIONARY_OBSERVED' and ('mode', 4) in commands(rover)
    assert report['status'] == 'GOAL_FAILED_CLOSURE_OBSERVED' and rover.armed is False


def test_the_same_authorization_cannot_start_a_second_trial(setup, monkeypatch):
    report, rover, holder, admitted = run(setup, monkeypatch)
    assert report['status'] == 'GOAL_REACHED_CLOSURE_OBSERVED'
    # Same scope, consumed trial: a new admission is refused by the gate (max_trials 1).
    monkeypatch.setattr(ground, 'sitl_current_facts', lambda scope, ev: dict(facts(scope, ev), trials_consumed=1))
    t = trial()
    filled = nav.with_operator_statements(t, sitl_authorization=t['required_sitl_authorization'],
                                          admission_statement='SYNTHETIC', coordination_statement='SYNTHETIC')
    again = ground.admit_ground_trial(setup[0], 'first-nav-again', filled['request'], filled['authorization'],
                                      coordination_context=filled['coordination_context'])
    assert again['status'] == 'BLOCKED' and 'TRIAL_ALREADY_CONSUMED' in again['policy_gate']['reasons']


def test_module_defaults_still_disabled():
    assert ground.OPERATIONAL_ROVER_ENABLED is False and policy.SITL_TRIAL_POLICY_ENABLED is False


# --------------------------------------------------- known race in NativeRos2Session --
def test_native_exchange_alarm_between_loop_and_cancel_still_cancels_the_future():
    from types import SimpleNamespace
    from unittest.mock import Mock
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native.node = object()
    native.mode_type = SimpleNamespace(Request=lambda: SimpleNamespace(mode=None))
    calls = {'done': 0}
    def done():
        calls['done'] += 1
        if calls['done'] == 2:  # first check after the loop: the SIGALRM handler fires right here
            raise TimeoutError('Synchronous rover backend deadline exceeded')
        return False
    future = SimpleNamespace(done=done, cancel=Mock())
    native.client = SimpleNamespace(call_async=Mock(return_value=future))
    native.rclpy = SimpleNamespace(spin_until_future_complete=Mock())
    native._check_cancelled = lambda: None
    # deadline = 0.0 + 0.3; the loop condition then reads 99.0 and exits at once, leaving the try normally.
    # The NEXT done() (line 'if not future.done(): future.cancel()') is where the alarm lands.
    clock = iter([0.0, 99.0])
    original = ros.time.monotonic
    ros.time.monotonic = lambda: next(clock, 99.0)
    try:
        with pytest.raises(TimeoutError):
            native._exchange({'kind': 'service', 'endpoint': ros.MODE, 'type': 'ardupilot_msgs/srv/ModeSwitch',
                              'payload': {'mode': 4}}, timeout_s=0.3)
    finally:
        ros.time.monotonic = original
    future.cancel.assert_called_once()
