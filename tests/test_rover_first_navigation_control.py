"""Control rate vs telemetry rate for the first 1 m navigation, OFFLINE.

control_timing() derives the freshness limit, speed and stop budget from the cadence measured in
the same lifecycle; these tests check the derivation and then run the real executor, pipe session
and worker against a kinematic double at each RTF and under telemetry anomalies. The double's
cadences are SYNTHETIC. Passing proves host logic, not ArduRover SITL behaviour, and is no
statement of fitness for movement.
"""
import copy
import json
import math
from pathlib import Path

import pytest

from tools import rover_first_navigation as nav
from tools import vehicle_execution_lock as locks
from tools.rover_control import RoverControlError
from tools.rover_sim_metrics import BINDING_SCHEMA
from tests.test_rover_ground_executor import setup  # noqa: F401  tmp LOCK_ROOT/RUN_ROOT
from tests.test_rover_first_navigation import CADENCE, commands, run, trial
from tests.test_rover_first_navigation_timing import CadencedRover, host_deadline, velocities
from tests.test_rover_sitl_preparation import EXECUTION, LIFECYCLE

ROOT = Path(__file__).resolve().parents[1]
START = (-0.0012461, -3.0005524)


def cadence(rtf, status_hz_wall=None):
    return dict(CADENCE, rtf=rtf, status_hz_wall=status_hz_wall or 2.0 * rtf)


def timing(rtf, status_hz_wall=None):
    return nav.control_timing(cadence(rtf, status_hz_wall), lifecycle_id=LIFECYCLE)


def travelled(rover):
    return math.hypot(rover.x - START[0], rover.y - START[1])


# --------------------------------------------------------------- derivation --
@pytest.mark.parametrize('rtf, status, speed, age, stop, effective_hz', [
    # 0.25 m/s would keep the stale-observation travel within 0.25 m, but then no GUID_TIMEOUT fits between
    # the nominal setpoint interval (0.925 s sim) and the runaway budget (<= 0.6 s): speed drops to 0.15 m/s.
    (1.0, 'VIABLE', 0.15, 0.95, 8.0, 2.0),
    (0.6, 'VIABLE', 0.15, 1.35, 8.0, 1.2),    # do not assume the next interval keeps the measured low RTF
    (0.5, 'NOT_VIABLE', None, 1.55, None, 1.0),
    (0.4, 'NOT_VIABLE', None, 1.90, None, 0.8),
    (0.3, 'NOT_VIABLE', None, 2.40, None, 0.6)])
def test_control_timing_by_rtf(rtf, status, speed, age, stop, effective_hz):
    t = timing(rtf)
    assert t['status'] == status and t['frequencies']['command_hz_effective_max'] == pytest.approx(effective_hz)
    assert t['frequencies']['command_hz_requested'] == 2.0 and t['movement_authorized'] is False
    assert t['limits'].observation_max_age_s == pytest.approx(age)
    if status == 'VIABLE':
        assert t['limits'].max_forward_mps == pytest.approx(speed) and t['limits'].stop_timeout_s == stop
        # never looser than the declared caps
        assert t['limits'].max_forward_mps <= nav.LIMITS.max_forward_mps
        assert t['limits'].observation_max_age_s <= nav.AGE_HARD_CAP_S
        assert t['derivation']['distance_during_age_m'] <= nav.GOAL_PARAMETERS['tolerance_m']
    else:
        assert 'OBSERVATION_AGE_ABOVE_HARD_CAP' in t['reasons']


def test_viable_range_with_the_current_caps():
    """Measured status: 2 Hz simulated. Viable from an RTF of 0.53 (status >= 1.06 Hz wall) upwards."""
    viable = [r / 100 for r in range(30, 101) if timing(r / 100)['status'] == 'VIABLE']
    assert min(viable) == pytest.approx(0.53) and max(viable) == 1.0
    assert all(timing(r / 100)['status'] == 'VIABLE' for r in range(53, 101))


def test_cadence_must_be_of_this_lifecycle():
    with pytest.raises(RoverControlError, match='this lifecycle'):
        nav.control_timing(dict(CADENCE, lifecycle_id='another-start'), lifecycle_id=LIFECYCLE)


def test_not_viable_cadence_refuses_the_trial_before_anything_exists():
    with pytest.raises(RoverControlError, match='NOT_VIABLE'):
        trial(cadence(0.4))


def test_trial_carries_the_derived_limits_into_request_and_worker():
    t = trial()
    assert t['request']['limits']['observation_max_age_s'] == pytest.approx(1.35)
    assert t['worker_limits']['telemetry_max_age_s'] == t['request']['limits']['observation_max_age_s']
    assert t['control_timing']['status'] == 'VIABLE' and t['cadence']['source'] == 'SYNTHETIC_TEST'


def historical_metrics():
    text = (ROOT / 'simulation/ros2_gazebo/results/rover_only_binding_final_2026_11_03/metrics.stdout').read_text()
    return json.loads(text)


def test_cadence_parser_reads_the_metrics_format_but_refuses_an_old_measurement():
    metrics = historical_metrics()  # HISTORICAL (03/11); used only to exercise the parser, never as current
    execution = copy.deepcopy(EXECUTION)
    execution['persistent_identity']['container_id'] = metrics['summary']['docker_stats']['Container']
    end = metrics['raw']['wall_end_ns']
    execution['container_boot_id'] = 'test-boot'
    # The historical file predates boot and execution binding: a copy stamped with a test boot and a binding to this
    # test lifecycle and execution exercises the parser only. The sealed file itself is refused (below).
    stamped = copy.deepcopy(metrics)
    stamped['raw']['boot_id'] = 'test-boot'
    stamped['binding'] = {'schema': BINDING_SCHEMA, 'lifecycle_id': LIFECYCLE,
                          'environment_execution': copy.deepcopy(execution)}
    parsed = nav.cadence_from_metrics(stamped, lifecycle_id=LIFECYCLE, environment_execution=execution,
                                      host_boot_id='test-boot', now_monotonic_ns=end + 10**9)
    assert parsed['status_hz_wall'] == pytest.approx(1.1999, abs=1e-3) and parsed['rtf'] == pytest.approx(0.606, abs=1e-3)
    with pytest.raises(RoverControlError, match='current measurement'):
        nav.cadence_from_metrics(metrics, lifecycle_id=LIFECYCLE, environment_execution=execution)  # today: no boot
    with pytest.raises(RoverControlError, match='current measurement'):  # unbound file, even inside the age window
        nav.cadence_from_metrics(metrics, lifecycle_id=LIFECYCLE, environment_execution=execution,
                                 host_boot_id='test-boot', now_monotonic_ns=end + 10**9)
    with pytest.raises(RoverControlError, match='current measurement'):  # another boot whose uptime matches the window
        nav.cadence_from_metrics(stamped, lifecycle_id=LIFECYCLE, environment_execution=execution,
                                 host_boot_id='current-boot', now_monotonic_ns=end + 10**9)
    with pytest.raises(RoverControlError, match='container execution'):
        nav.cadence_from_metrics(stamped, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                                 host_boot_id='test-boot', now_monotonic_ns=end + 10**9)


# ----------------------------------------------------- end to end by RTF --
@pytest.mark.parametrize('rtf', [1.0, 0.6])
def test_viable_rtf_reaches_the_goal_and_closes(setup, monkeypatch, rtf):
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline(monkeypatch), cadence=cadence(rtf),
                                   rover_factory=lambda clock: CadencedRover(clock, status_hz=2.0 * rtf, rtf=rtf))
    assert report['status'] == 'GOAL_REACHED_CLOSURE_OBSERVED'
    assert max(v for v, _ in rover.sent) <= timing(rtf)['limits'].max_forward_mps
    assert travelled(rover) == pytest.approx(1.0, abs=0.3) and holder['loop'].host_alarms == 0


# ----------------------------------------------------- telemetry anomalies --
class AnomalousRover(CadencedRover):
    """Per-stream freezes and irregular status on top of the measured cadence."""
    def __init__(self, clock, *, jitter=False, **kwargs):
        super().__init__(clock, **kwargs)
        self.frozen_kinds, self.jitter, self.limit_m = set(), jitter, None
        self.frozen_until = {}  # kind -> clock time until which that stream delivers nothing new

    def latest(self, kind):
        gap = self.clock.now < self.frozen_until.get(kind, float('-inf'))
        frozen, self.frozen = self.frozen, self.frozen or kind in self.frozen_kinds or gap
        try:
            value = super().latest(kind)
            if value is not None and kind == 'status' and self.jitter and not self.frozen:
                # irregular delivery: every third status arrives 30 % late
                n = value['stamp_ns'] // 10**9
                if n % 3 == 0 and (self.clock.now - self.t0) * self.status_hz - (n - 1) < 0.3:
                    n -= 1
                    value['message']['header']['stamp'] = {'sec': n, 'nanosec': 0}
                    value['stamp_ns'] = n * 10**9
            return value
        finally:
            self.frozen = frozen

    def spin(self, timeout_s):
        super().spin(timeout_s)
        if self.limit_m is not None and travelled(self) >= self.limit_m:
            self.stuck = True  # stops moving on its own before the target


def anomalous(**kwargs):
    return lambda clock: AnomalousRover(clock, **kwargs)


def after_velocities(n, action):
    def configure(rover, loop):
        host_deadline_configure(rover, loop)
        send = loop.send

        def watched(obj):
            if len(velocities(loop)) >= n:
                action(rover, loop)
            return send(obj)
        loop.send = watched
    return configure


host_deadline_configure = None


@pytest.fixture(autouse=True)
def modelled_alarm(monkeypatch):
    global host_deadline_configure
    host_deadline_configure = host_deadline(monkeypatch)
    yield


def test_irregular_status_still_closes(setup, monkeypatch):
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline_configure, rover_factory=anomalous(jitter=True))
    assert report['status'] == 'GOAL_REACHED_CLOSURE_OBSERVED' and holder['loop'].host_alarms == 0


@pytest.mark.parametrize('stale', ['status', 'odometry'])
def test_one_stale_stream_ends_the_navigation_and_the_stop_is_observed(setup, monkeypatch, stale):
    def freeze_one_observe(rover, loop):
        rover.frozen_until.setdefault(stale, rover.clock.now + 3.0)  # one 3 s gap in that stream, then it resumes
    report, rover, holder, _ = run(setup, monkeypatch, configure=after_velocities(3, freeze_one_observe),
                                   rover_factory=anomalous())
    assert report['result']['goal_outcome'] == 'GOAL_FAILED'  # a fresh other stream never authorizes a command
    assert report['status'] == 'GOAL_FAILED_CLOSURE_OBSERVED' and ('mode', 4) in commands(rover)


def test_duplicated_observation_is_never_used_as_new(setup, monkeypatch):
    def configure(rover, loop):
        host_deadline_configure(rover, loop)
        receive, state = loop.receive, {'previous': None, 'done': False}

        def replay(timeout_s):
            reply = receive(timeout_s)
            result = reply.get('result') or {}
            if 'status' in result and 'odometry' in result:
                if state['previous'] is not None and not state['done'] and len(velocities(loop)) >= 3:
                    state['done'] = True
                    reply = dict(reply, result=state['previous'])  # same samples again, correctly correlated
                state['previous'] = result
            return reply
        loop.receive = replay
    report, rover, holder, _ = run(setup, monkeypatch, configure=configure, rover_factory=anomalous())
    assert report['result']['goal_outcome'] == 'GOAL_FAILED'
    assert 'non-progressing' in json.dumps(report['result']['error_evidence'])
    assert report['result']['stop']['status'] == 'STATIONARY_OBSERVED'


def test_permanent_loss_of_telemetry_sends_hold_but_stays_unconfirmed(setup, monkeypatch):
    report, rover, holder, admitted = run(setup, monkeypatch, rover_factory=anomalous(),
                                          configure=after_velocities(3, lambda r, l: setattr(r, 'frozen_kinds', {'status', 'odometry'})))
    assert report['status'] == 'UNCONFIRMED' and report['result']['stop']['status'] == 'UNCONFIRMED'
    assert ('mode', 4) in commands(rover) and ('arm', False) not in commands(rover)  # no disarm without an observed stop
    assert locks.restriction('v3')['owner_id'] == admitted['run_id'] and not holder['session'].broken


def test_rover_that_stops_before_the_target(setup, monkeypatch):
    def factory(clock):
        rover = AnomalousRover(clock)
        rover.limit_m = 0.5
        return rover
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline_configure, rover_factory=factory)
    assert report['result']['goal_outcome'] == 'GOAL_FAILED' and 'NO_PROGRESS' in json.dumps(report['result']['error_evidence'])
    assert report['status'] == 'GOAL_FAILED_CLOSURE_OBSERVED' and travelled(rover) == pytest.approx(0.5, abs=0.1)


class LaggyRover(CadencedRover):
    """Velocity follows the command with a lag, and HOLD brakes over time: it can overshoot."""
    TAU_S = 1.5

    def __init__(self, clock, **kwargs):
        super().__init__(clock, **kwargs)
        self.target = (0.0, 0.0)

    def publish_velocity(self, linear, angular):
        FakeBackend_publish(self, linear, angular)
        if self.mode == 15 and self.armed:
            self.target = (linear, angular)

    def call_mode(self, mode, timeout_s):
        reply = FakeBackend_call_mode(self, mode, timeout_s)
        if mode == 4:
            self.target = (0.0, 0.0)
        return reply

    def spin(self, timeout_s):
        dt = max(timeout_s, 0.01)
        self.clock.now += dt
        if not self.frozen:
            self.t += 1
        k = 1 - math.exp(-dt * self.rtf / self.TAU_S)
        self.v += (self.target[0] - self.v) * k
        self.w += (self.target[1] - self.w) * k
        if self.armed:
            self.yaw += self.w * dt * self.rtf
            self.x += self.v * math.cos(self.yaw) * dt * self.rtf
            self.y += self.v * math.sin(self.yaw) * dt * self.rtf


def FakeBackend_publish(rover, linear, angular):
    rover.sent.append((linear, angular))


def FakeBackend_call_mode(rover, mode, timeout_s):
    rover.calls.append(('mode', mode))
    rover.mode = mode
    return {'status': True, 'curr_mode': mode}


def test_overshoot_is_reported_not_hidden(setup, monkeypatch):
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline_configure,
                                   rover_factory=lambda clock: LaggyRover(clock))
    outcome = report['result']['goal_outcome']
    assert outcome in ('GOAL_REACHED', 'GOAL_LOST_DURING_STOP', 'GOAL_FAILED')
    assert report['result']['stop']['stationary_observed'] is True  # it does come to rest, later
    if outcome == 'GOAL_LOST_DURING_STOP':
        assert report['status'] != 'GOAL_REACHED_CLOSURE_OBSERVED'  # an overshoot is never reported as reached


def slow(factor):
    def factory(clock):
        rover = AnomalousRover(clock)
        original = rover.publish_velocity

        def publish(linear, angular):
            original(linear * factor, angular)  # a vehicle that moves at a fraction of the command
        rover.publish_velocity = publish
        return rover
    return factory


def test_goal_timeout_with_an_observed_stop(setup, monkeypatch):
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline_configure, rover_factory=slow(0.05))
    evidence = json.dumps(report['result']['error_evidence'])
    # Ends on GOAL_TIMEOUT, or one step earlier: under 0.4 s before the goal deadline no call is sent (NOT_SENT).
    assert report['result']['goal_outcome'] == 'GOAL_FAILED' and ('GOAL_TIMEOUT' in evidence or 'NOT_SENT' in evidence)
    assert travelled(rover) < 1.0 - nav.GOAL_PARAMETERS['tolerance_m']
    assert report['status'] == 'GOAL_FAILED_CLOSURE_OBSERVED' and rover.armed is False


def test_goal_timeout_with_an_unconfirmed_stop(setup, monkeypatch):
    def configure(rover, loop):
        host_deadline_configure(rover, loop)
        send, state = loop.send, {'first': None}

        def watched(obj):
            if velocities(loop) and state['first'] is None:
                state['first'] = rover.clock.now
            if state['first'] is not None and rover.clock.now - state['first'] > 40.0:
                rover.frozen_kinds = {'status', 'odometry'}  # telemetry dies just before the timeout
            return send(obj)
        loop.send = watched
    report, rover, holder, admitted = run(setup, monkeypatch, configure=configure, rover_factory=slow(0.05))
    assert report['result']['goal_outcome'] == 'GOAL_FAILED' and report['result']['stop']['status'] == 'UNCONFIRMED'
    assert report['status'] == 'UNCONFIRMED' and ('mode', 4) in commands(rover)
    assert locks.restriction('v3')['owner_id'] == admitted['run_id']
