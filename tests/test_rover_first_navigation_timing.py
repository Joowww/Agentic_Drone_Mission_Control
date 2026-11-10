"""Timing of the first 1 m navigation, OFFLINE: budgets, command rate, stop reserve and host/worker margin.

Same real executor, SITL gate (enabled in-test only), PipeRos2Session, Ros2RoverAdapter and
WorkerCore as tests/test_rover_first_navigation.py. Two things are modelled on top:

- the cadence measured live in rover_only (rover_only_binding_final_2026_11_03): /ap/v3/status
  at about 1.2 Hz of wall clock (2 Hz simulated), odometry at 50 Hz simulated, RTF about 0.6;
- the host deadline: RoverControlCore wraps every call in synchronous_deadline(timeout), a
  SIGALRM that raises TimeoutError inside the pipe read and marks the session broken. A reply
  that would arrive after that deadline is modelled as that TimeoutError, after an ASSUMED
  pipe latency of 50 ms.

Not modelled: the worker's own EOF/watchdog safe stop and ArduRover's GUIDED command timeout.
Passing proves arithmetic and host logic under these models, not ArduRover SITL behaviour.
"""
from dataclasses import asdict
import math

import pytest

from tools import rover_first_navigation as nav, rover_pipe_session as ps
from tools import rover_ros2_adapter as ros
from tools import vehicle_execution_lock as locks
from tests.test_rover_ground_executor import setup  # noqa: F401  tmp LOCK_ROOT/RUN_ROOT
from tests.test_rover_first_navigation import KinematicRover, commands, run
from tests.test_rover_pipe_worker import session as pipe_session

PIPE_LATENCY_S = 0.05  # assumption: docker exec pipe round trip; not measured


class CadencedRover(KinematicRover):
    """Status at status_hz of host (wall) time; odometry at 50 Hz simulated; motion scaled by the RTF."""
    def __init__(self, clock, *, status_hz=1.2, rtf=0.6):
        super().__init__(clock)
        self.status_hz, self.rtf, self.t0 = status_hz, rtf, clock.now
        self.last_n, self.rx = {}, {}

    def telemetry_age_s(self, kind):
        self.latest(kind)
        return self.clock.now - self.rx[kind] if kind in self.rx else None

    def spin(self, timeout_s):
        dt = max(timeout_s, 0.01)
        self.clock.now += dt
        if not self.frozen:
            self.t += 1
        if self.mode == 15 and self.armed and not self.stuck:
            sim_dt = dt * self.rtf
            self.yaw += self.w * sim_dt
            self.x += self.v * math.cos(self.yaw) * sim_dt
            self.y += self.v * math.sin(self.yaw) * sim_dt
        else:
            self.v = self.w = 0.0

    def latest(self, kind):
        value = super().latest(kind)
        if value is None:
            return None
        hz = self.status_hz if kind == 'status' else 50.0 * self.rtf
        n = self.last_n[kind] if self.frozen and kind in self.last_n else int((self.clock.now - self.t0) * hz) + 1
        if self.last_n.get(kind) != n:
            self.rx[kind] = self.clock.now  # worker-side receipt of a NEW sample
        self.last_n[kind] = n  # frozen: the graph delivers nothing new (a status/odometry gap)
        value['message']['header']['stamp'] = {'sec': n, 'nanosec': 0}
        value['stamp_ns'] = n * 10**9
        return value


def cadenced(status_hz, rtf=0.6, stuck=False):
    def factory(clock):
        rover = CadencedRover(clock, status_hz=status_hz, rtf=rtf)
        rover.stuck = stuck
        return rover
    return factory


def host_deadline(monkeypatch, freeze=None):
    """Model SIGALRM: the reply is ready PIPE_LATENCY_S after the worker finishes; later than the host deadline -> TimeoutError."""
    for name in ('observe', 'exchange'):
        original = getattr(ps.PipeRos2Session, name)

        def wrapper(self, *args, timeout_s, _original=original):
            self.transport.host_deadline = self.clock.monotonic() + timeout_s  # same value the alarm uses
            return _original(self, *args, timeout_s=timeout_s)
        monkeypatch.setattr(ps.PipeRos2Session, name, wrapper)

    def configure(rover, loop):
        loop.host_deadline, loop.ready_at, loop.host_alarms, loop.frozen_once = None, None, 0, False
        send, receive = loop.send, loop.receive

        def timed_send(obj):
            if freeze is not None and not loop.frozen_once and freeze(loop, obj):
                loop.frozen_once = rover.frozen = True  # nothing new for the whole of this request
            try:
                send(obj)
            finally:
                rover.frozen = False
            loop.ready_at = rover.clock.now + PIPE_LATENCY_S

        def timed_receive(timeout_s):
            if loop.host_deadline is not None and loop.ready_at is not None and loop.ready_at > loop.host_deadline:
                loop.host_alarms += 1
                rover.clock.now = max(rover.clock.now, loop.host_deadline)
                raise TimeoutError('Synchronous rover backend deadline exceeded')  # what the alarm raises in the read
            if loop.ready_at is not None:
                rover.clock.now = max(rover.clock.now, loop.ready_at)
            return receive(timeout_s)
        loop.send, loop.receive = timed_send, timed_receive
    return configure


def legacy_budget(monkeypatch):
    """The budget before the fix: the worker got the host's whole timeout_s (reproduces the defect)."""
    monkeypatch.setattr(ps, 'WORKER_SHARE', 1.0)
    monkeypatch.setattr(ps, 'IPC_RESERVE_S', 0.0)
    monkeypatch.setattr(ps, 'HOST_GUARD_S', 0.0)


def velocities(loop):
    return [m for m in loop.sent if m.get('op') == 'exchange' and m['args']['command']['endpoint'] == ros.VELOCITY]


def gap_mid_navigation(loop, obj):
    return obj.get('op') == 'observe' and len(velocities(loop)) >= 3


# ------------------------------------------------------------------ budgets --
def worst_case_wall_s(request):
    """Every phase at its own deadline: probe, preparation, navigation, stop, disarm, close (host wall clock)."""
    limits = request['limits']
    return (limits['call_timeout_s'] + request['preparation']['timeout_s'] + request['goal']['timeout_s']
            + limits['stop_timeout_s'] + request['finalization']['timeout_s'] + limits['call_timeout_s'])


def test_sixty_seconds_bounds_the_navigation_phase_only_not_the_whole_trial():
    req = {'limits': asdict(nav.LIMITS), 'preparation': nav.PREPARATION, 'finalization': nav.FINALIZATION,
           'goal': nav.GOAL_PARAMETERS}
    assert req['goal']['timeout_s'] <= nav.LIMITS.max_duration_s  # the only check the executor makes (_request, navigate)
    assert worst_case_wall_s(req) == 2 + 20 + 45 + 8 + 10 + 2 == 87.0
    assert worst_case_wall_s(req) > nav.LIMITS.max_duration_s  # 60 s is NOT a global deadline for ROVER_NAVIGATE_V1
    # The admission battery check (admit_ground_trial) budgets the same 87 s: goal + 2 calls + stop + disarm + preparation.
    assert (req['goal']['timeout_s'] + 2 * req['limits']['call_timeout_s'] + req['limits']['stop_timeout_s']
            + req['finalization']['timeout_s'] + req['preparation']['timeout_s']) == worst_case_wall_s(req)


def test_stop_and_disarm_get_their_own_reserve_after_a_navigation_failure(setup, monkeypatch):
    # The rover never progresses: navigation ends in NO_PROGRESS. RoverControlCore.stop and finalize_disarmed start
    # fresh deadlines (8 s and 10 s) after navigation, so its timeout cannot consume them.
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline(monkeypatch),
                                   rover_factory=cadenced(1.2, stuck=True))
    assert report['result']['goal_outcome'] == 'GOAL_FAILED'
    assert report['result']['stop']['status'] == 'STATIONARY_OBSERVED'
    assert report['finalization']['status'] == 'DISARMED_STATIONARY_OBSERVED'
    assert report['finalization']['duration_s'] <= nav.FINALIZATION['timeout_s']
    assert holder['loop'].host_alarms == 0


# ------------------------------------------------------------- command rate --
def test_effective_command_rate_follows_new_status_not_the_declared_2_hz(setup, monkeypatch):
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline(monkeypatch), rover_factory=cadenced(1.2))
    assert report['status'] == 'GOAL_REACHED_CLOSURE_OBSERVED'
    stamps = [s['received_monotonic_s'] for s in report['result']['observation_samples']]
    rate = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    assert rate <= 1.2 * 1.05 < nav.GOAL_PARAMETERS['command_hz']  # each command waits for a NEW status pair
    assert len(velocities(holder['loop'])) == report['result']['commands_sent'] + 1  # + the zero of the stop
    assert holder['loop'].host_alarms == 0
    assert math.hypot(rover.x + 0.0012461, rover.y + 3.0005524) == pytest.approx(1.0, abs=0.3)


# ------------------------------------------ observation age vs status cadence --
def test_a_vehicle_slower_than_the_measured_cadence_fails_closed(setup, monkeypatch):
    # Trial derived for 1.2 Hz (age limit 1.35 s); the vehicle actually delivers 0.6 Hz (1.67 s periods).
    report, rover, holder, admitted = run(setup, monkeypatch, configure=host_deadline(monkeypatch),
                                          rover_factory=cadenced(0.6))
    assert report['status'] == 'UNCONFIRMED' and report['result']['motion_command_attempted'] is False
    assert ('arm', True) not in commands(rover) and all(v == 0.0 for v, _ in rover.sent)
    assert locks.restriction('v3')['owner_id'] == admitted['run_id']  # fail closed: reservation kept


# ------------------------------------------------ host / worker timeout margin --
def test_worker_is_given_less_time_than_the_host_deadline():
    s, transport, backend, clock = pipe_session()
    s.observe(timeout_s=1.0)
    sent = transport.sent[-1]['args']['timeout_s']
    assert sent == pytest.approx(0.7) and sent == s.last_budget['worker_s'] < s.last_budget['receive_s'] < 1.0


@pytest.mark.parametrize('legacy', [True, False])
def test_a_status_gap_mid_navigation_keeps_the_hold_only_with_the_budget(setup, monkeypatch, legacy):
    if legacy:
        legacy_budget(monkeypatch)
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline(monkeypatch, freeze=gap_mid_navigation),
                                   rover_factory=cadenced(1.2))
    assert report['result']['goal_outcome'] == 'GOAL_FAILED'  # the gap ends the navigation either way: fail closed
    if legacy:  # reproduces the defect: the whole host budget goes to the worker, the session breaks, no zero/HOLD
        # (detected by the modelled alarm or, with the legacy constants, by the session's own spent-budget check)
        assert holder['session'].broken == 'TimeoutError'
        assert commands(rover) == [('mode', 15), ('arm', True)] and rover.armed and rover.mode == 15
        assert report['status'] == 'UNCONFIRMED'
    else:       # the worker answers TIMEOUT inside the host budget; HOLD and disarm are observed
        assert holder['loop'].host_alarms == 0 and not holder['session'].broken
        assert commands(rover) == [('mode', 15), ('arm', True), ('mode', 4), ('arm', False)]
        assert report['status'] == 'GOAL_FAILED_CLOSURE_OBSERVED' and rover.armed is False


@pytest.mark.parametrize('legacy', [True, False])
def test_slow_status_in_the_stop_window_breaks_the_session_only_without_the_budget(setup, monkeypatch, legacy):
    # 0.7 Hz: the stop's first observation gets stop_timeout_s/6 = 1.33 s, less than one status period (1.43 s).
    if legacy:
        legacy_budget(monkeypatch)
    report, rover, holder, _ = run(setup, monkeypatch, configure=host_deadline(monkeypatch), rover_factory=cadenced(0.7))
    assert report['status'] == 'UNCONFIRMED'  # stale observations in both cases: the 1 s age limit (above)
    if legacy:
        assert holder['session'].broken == 'TimeoutError' and ('mode', 4) not in commands(rover)
    else:
        assert not holder['session'].broken and ('mode', 4) in commands(rover)  # HOLD still sent
