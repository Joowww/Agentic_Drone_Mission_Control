"""The worker's own safety policy: accredited limits, watchdog, monitor thread and safe stop.

Deterministic cases drive WorkerCore with a fake clock and backend. The cases about a dead
host, a lost pipe, a silent host and a blocked ROS call run the production worker main() in a
REAL child process (tests/rover_pipe_fake_worker.py) whose action log is the ground truth.
No ROS, container, SITL or vehicle. Nothing here claims a confirmed stop: the worker only
reports what it attempted and what it saw.
"""
import json
import os
import time

import pytest

from tools import rover_pipe_session as ps, rover_pipe_worker as w
from tools.rover_control import RoverControlError
from tools.vehicle_execution_lock import VehicleBusy
from tests.test_rover_pipe_worker import (LIMITS_HELLO, MODE_GUIDED, MODE_HOLD, ODOM_GID, STATUS_GID, FakeBackend,
                                          FakeClock, Loopback, evidence, hello, req, velocity)
from tests.test_rover_pipe_budget import call, events, spawn  # noqa: F401  (spawn is a fixture)
from tests.test_rover_ground_executor import setup  # noqa: F401  tmp LOCK_ROOT/RUN_ROOT
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE

ARM_ON = {'kind': 'service', 'endpoint': w.ARM, 'type': 'ardupilot_msgs/srv/ArmMotors', 'payload': {'arm': True}}
ARM_OFF = dict(ARM_ON, payload={'arm': False})


def worker(**limit_changes):
    clock = FakeClock()
    backend = FakeBackend(clock)
    backend.spin(0.0)
    return w.WorkerCore(backend, hello(limits=dict(LIMITS_HELLO, **limit_changes)), clock=clock.monotonic), backend, clock


def ex(core, command, timeout=1.0):
    return core.handle(req('exchange', {'timeout_s': timeout, 'command': command}))


# ------------------------------------------------------------------ limits --
@pytest.mark.parametrize('limits', [
    {k: v for k, v in LIMITS_HELLO.items() if k != 'telemetry_max_age_s'},       # missing
    dict(LIMITS_HELLO, extra=1.0),                                                # unknown key
    dict(LIMITS_HELLO, max_linear_mps=5.0),                                       # looser than HARD_LIMITS
    dict(LIMITS_HELLO, watchdog_s=60.0),
    dict(LIMITS_HELLO, max_session_s=float('inf')),
    dict(LIMITS_HELLO, stopped_linear_mps=0.0)])
def test_operational_hello_needs_exact_finite_limits_within_hard_caps(limits):
    with pytest.raises(w.ProtocolError):
        w.WorkerCore(FakeBackend(FakeClock()), hello(limits=limits))


def test_passive_hello_requires_watchdog_and_bounded_session_lifetime():
    for limits in ({'watchdog_s': 3.0}, {'watchdog_s': 3.0, 'max_session_s': 301.0},
                   {'watchdog_s': 3.0, 'max_session_s': 300.0, 'extra': 1.0}):
        with pytest.raises(w.ProtocolError):
            w.WorkerCore(FakeBackend(FakeClock()), hello(mode='PASSIVE', limits=limits))
    core = w.WorkerCore(FakeBackend(FakeClock()),
        hello(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0}))
    assert core.limits['max_session_s'] == 300.0


def test_passive_worker_deadline_rejects_observation_and_keeps_close_available():
    from tests.test_rover_pipe_worker import CountingBackend
    clock = FakeClock(); backend = CountingBackend(clock)
    c = w.WorkerCore(backend, hello(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 1.0}),
                     clock=clock.monotonic)
    clock.now += 1.0
    expired = c.handle(req('observe', {'timeout_s': 1.0, 'after_status_ns': None, 'after_odometry_ns': None}))
    assert expired['error']['code'] == 'SESSION_EXPIRED'
    assert backend.control_actions == 0 and backend.sent == [] and backend.calls == []
    closed = c.handle(req('close'))
    assert closed['result']['closed'] is True and backend.control_actions == 0


def test_host_session_refuses_limits_the_worker_would_not_accept():
    for bad in ({'max_linear_mps': 0.3, 'max_angular_rad_s': 0.5, 'watchdog_s': 3.0}, dict(LIMITS_HELLO, max_linear_mps=2.0)):
        transport = Loopback(FakeBackend(FakeClock()), FakeClock())
        with pytest.raises(RoverControlError):
            ps.PipeRos2Session(transport, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                               binding_evidence=evidence()[1], limits=bad, fence=lambda e: None, authority=lambda: None)
        assert transport.sent == []  # nothing reached the worker


def test_operational_session_opens_only_under_the_current_authority():
    transport = Loopback(FakeBackend(FakeClock()), FakeClock())

    def no_reservation():
        raise VehicleBusy('No live v3 reservation for this process')
    with pytest.raises(VehicleBusy):
        ps.PipeRos2Session(transport, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                           binding_evidence=evidence()[1], limits=dict(LIMITS_HELLO), fence=lambda e: None,
                           authority=no_reservation)
    assert transport.sent == []  # no operational worker exists without the authority


def test_trial_worker_limits_come_from_the_accredited_request_and_never_loosen_it():
    from tools import rover_first_navigation as nav
    limits = ps.worker_limits(nav.LIMITS, watchdog_s=nav.WORKER_WATCHDOG_S, max_session_s=nav.WORKER_MAX_SESSION_S)
    assert limits == {'max_linear_mps': 0.3, 'max_angular_rad_s': 0.5, 'watchdog_s': 3.0, 'telemetry_max_age_s': 1.0,
                      'max_session_s': 120.0, 'stopped_linear_mps': 0.03, 'stopped_angular_rad_s': 0.03}
    with pytest.raises(RoverControlError):
        ps.worker_limits(nav.LIMITS, watchdog_s=1.0, max_session_s=120.0)  # shorter than one 2 s host call


def test_an_operation_may_not_block_longer_than_the_watchdog():
    c, b, clock = worker()
    assert ex(c, MODE_GUIDED, timeout=LIMITS_HELLO['watchdog_s'] + 0.1)['error']['code'] == 'INVALID_ARGUMENTS'
    assert b.calls == []


# --------------------------------------------------------- telemetry and expiry --
def test_no_motion_without_fresh_worker_telemetry_but_stops_always_pass():
    clock = FakeClock()
    b = FakeBackend(clock)
    c = w.WorkerCore(b, hello(), clock=clock.monotonic)
    assert ex(c, velocity(0.1))['error']['code'] == 'TELEMETRY_STALE'  # nothing ever received
    b.spin(0.0)
    assert ex(c, velocity(0.1))['ok']
    clock.now += LIMITS_HELLO['telemetry_max_age_s'] + 0.01  # no new sample since
    assert ex(c, velocity(0.1))['error']['code'] == 'TELEMETRY_STALE'
    assert ex(c, velocity(0.0))['ok'] and ex(c, MODE_HOLD)['ok']
    assert b.sent == [(0.1, 0.0), (0.0, 0.0)]


def test_session_lifetime_is_bounded_by_the_worker():
    c, b, clock = worker(max_session_s=10.0)
    assert ex(c, velocity(0.1))['ok']
    clock.now += 10.5
    b.spin(0.0)
    assert ex(c, velocity(0.1))['error']['code'] == 'MOTION_REFUSED' and c.latched == 'SESSION_EXPIRED'
    assert ex(c, MODE_HOLD)['ok']  # stopping is still possible


# ----------------------------------------------------------------- watchdog --
@pytest.mark.parametrize('phase', ['guided', 'armed', 'navigating'])
def test_watchdog_during_each_phase_stops_and_reports_without_claiming(phase):
    c, b, clock = worker()
    assert ex(c, MODE_GUIDED)['ok']
    if phase in ('armed', 'navigating'):
        assert ex(c, ARM_ON)['ok']
    if phase == 'navigating':
        assert ex(c, velocity(0.2))['ok']
    assert c.motion_possible
    clock.now += LIMITS_HELLO['watchdog_s'] + 0.1
    assert c.watchdog_due()
    record = c.safe_stop('WATCHDOG_HOST_SILENT')
    assert record['zero_velocity'] == 'PUBLISHED' and record['hold'] == 'ACKNOWLEDGED'
    assert record['worker_observation'] == 'HOLD_AND_STOPPED_OBSERVED_BY_WORKER'
    assert record['confirmation'] == 'NOT_CLAIMED_BY_WORKER' and b.calls[-1] == ('mode', 4) and b.sent[-1] == (0.0, 0.0)
    assert ex(c, velocity(0.1))['error']['code'] == 'CLOSED'  # nothing more after a safe stop


def test_hold_rejected_is_reported_as_such():
    c, b, clock = worker()
    ex(c, MODE_GUIDED)
    b.mode_response = {'status': False, 'curr_mode': 15}
    record = c.safe_stop('EOF')
    assert record['hold'] == 'REJECTED' and record['worker_observation'] == 'HOLD_NOT_OBSERVED'


def test_hold_without_telemetry_afterwards_is_not_observed():
    c, b, clock = worker()
    ex(c, MODE_GUIDED)
    b.frozen = True
    record = c.safe_stop('EOF')
    assert record['hold'] == 'ACKNOWLEDGED' and record['worker_observation'] == 'NO_NEW_TELEMETRY_AFTER_HOLD'
    assert record['confirmation'] == 'NOT_CLAIMED_BY_WORKER'


def test_hold_timeout_is_unconfirmed_not_rejected():
    c, b, clock = worker()
    b.service_timeout = True
    record = c.safe_stop('EOF')
    assert record['hold'].startswith('UNCONFIRMED') and record['zero_velocity'] == 'PUBLISHED'


# ------------------------------------------------------------------ monitor --
def test_monitor_zeroes_velocity_only_when_the_main_thread_overruns_an_operation():
    c, b, clock = worker()
    ex(c, velocity(0.2))
    assert c.monitor_tick() is None  # idle: the main loop's own watchdog is in charge
    with c.busy('exchange', 1.0):
        clock.now += 1.0 + w.OP_GRACE_S - 0.01
        assert c.monitor_tick() is None
        clock.now += 0.02
        record = c.monitor_tick()
    assert record['zero_velocity'] == 'PUBLISHED' and record['hold'] == 'NOT_ATTEMPTED_FROM_MONITOR'
    assert b.sent[-1] == (0.0, 0.0) and c.latched == 'MONITOR_EXCHANGE_OVERRUN' and b.calls == []
    b.spin(0.0)
    assert ex(c, velocity(0.2))['error']['code'] == 'MOTION_REFUSED'  # the zero is never overtaken
    assert c.monitor_tick() is None  # once


def test_monitor_never_acts_in_a_passive_session():
    clock = FakeClock()
    c = w.WorkerCore(FakeBackend(clock), hello(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0}), clock=clock.monotonic)
    with c.busy('observe', 0.1):
        clock.now += 5.0
        assert c.monitor_tick() is None


# ------------------------------------------------------- protocol over pipes --
def run_main(lines, backend=None):
    backend = backend or FakeBackend(FakeClock())
    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, 'w') as writer:
        writer.write(''.join(line + '\n' for line in lines))
    import io
    out = io.StringIO()
    with os.fdopen(read_fd) as reader:
        code = w.main(stdin=reader, stdout=out, backend_factory=lambda passive: backend)
    return code, [json.loads(l) for l in out.getvalue().splitlines()], backend


def test_a_second_hello_cannot_turn_the_session_passive_to_dodge_the_stop():
    code, out, b = run_main([json.dumps(hello()), req('probe', {'timeout_s': 0.5}),
                             req('exchange', {'timeout_s': 1.0, 'command': velocity(0.2)}),
                             json.dumps(hello(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0}))])
    assert out[-1]['op'] == 'watchdog' and out[-1]['stop']['mode'] == 'OPERATIONAL' and code == 5
    assert b.sent[-1] == (0.0, 0.0) and ('mode', 4) in b.calls


def test_close_with_motion_possible_still_stops_after_acknowledging():
    code, out, b = run_main([json.dumps(hello()), req('probe', {'timeout_s': 0.5}),
                             req('exchange', {'timeout_s': 1.0, 'command': velocity(0.2)}), req('close')])
    assert code == 0 and out[-1]['result'] == {'closed': True}
    assert b.sent == [(0.2, 0.0), (0.0, 0.0)] and b.calls == [('mode', 4)]


def test_close_after_hold_and_disarm_takes_no_further_action():
    code, out, b = run_main([json.dumps(hello()), req('probe', {'timeout_s': 0.5}),
                             req('exchange', {'timeout_s': 1.0, 'command': velocity(0.2)}),
                             req('exchange', {'timeout_s': 1.0, 'command': velocity(0.0)}),
                             req('exchange', {'timeout_s': 1.0, 'command': MODE_HOLD}),
                             req('exchange', {'timeout_s': 1.0, 'command': ARM_OFF}), req('close')])
    assert code == 0 and b.calls == [('mode', 4), ('arm', False)] and b.sent == [(0.2, 0.0), (0.0, 0.0)]


def test_a_backend_exception_ends_the_session_with_a_stop():
    class Broken(FakeBackend):
        def call_mode(self, mode, timeout_s):
            if mode == 15:
                raise RuntimeError('service vanished')
            return super().call_mode(mode, timeout_s)
    code, out, b = run_main([json.dumps(hello()), req('probe', {'timeout_s': 0.5}),
                             req('exchange', {'timeout_s': 1.0, 'command': MODE_GUIDED})], Broken(FakeClock()))
    assert out[2]['error']['code'] == 'BACKEND_ERROR_EFFECT_UNCONFIRMED' and code == 5
    assert out[-1]['stop']['reason'] == 'BACKEND_ERROR' and ('mode', 4) in b.calls


def test_host_breaks_on_a_backend_error_and_keeps_effects_unconfirmed():
    class Broken(FakeBackend):
        def call_mode(self, mode, timeout_s):
            raise RuntimeError('service vanished')
    clock = FakeClock()
    backend = Broken(clock)
    backend.spin(0.0)  # fresh telemetry: GUIDED/ARM are refused without it
    s = ps.PipeRos2Session(Loopback(backend, clock), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                           host_boot_id=BOOT, binding_evidence=evidence()[1], limits=dict(LIMITS_HELLO), clock=clock,
                           fence=lambda e: None, motion_allowed=lambda: True, authority=lambda: None, alarm_remaining=lambda: None)
    with pytest.raises(TimeoutError) as info:
        s.exchange(MODE_GUIDED, timeout_s=1.0)
    assert info.value.diagnostic['effects'] == 'UNCONFIRMED' and s.broken == 'WORKER_BACKEND_ERROR'


def test_repeated_close_and_no_command_after_close():
    clock = FakeClock()
    backend = FakeBackend(clock)
    s = ps.PipeRos2Session(Loopback(backend, clock), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                           host_boot_id=BOOT, binding_evidence=evidence()[1], limits=dict(LIMITS_HELLO), clock=clock,
                           fence=lambda e: None, motion_allowed=lambda: True, authority=lambda: None, alarm_remaining=lambda: None)
    s.close()
    s.close()  # idempotent
    with pytest.raises(RoverControlError, match='unusable'):
        s.exchange(MODE_HOLD, timeout_s=1.0)
    assert backend.calls == []


# ------------------------------------------------------ real worker process --
def wait_exit(proc, timeout=8.0):
    return proc.wait(timeout=timeout)


def test_host_dead_during_navigation_the_worker_stops_on_its_own(spawn):
    s, proc, actions = spawn()
    for command in (MODE_GUIDED, ARM_ON, velocity(0.2)):
        call(s, command, 1.0)
    proc.stdin.close()   # the host process dies: the kernel closes its end of the pipes
    proc.stdout.close()
    assert wait_exit(proc) == 4  # EOF
    seen = [(a['event'], a.get('linear'), a.get('service')) for a in actions() if a['event'] in ('velocity', 'service_applied')]
    assert seen[-3:] == [('velocity', 0.2, None), ('velocity', 0.0, None), ('service_applied', None, 'mode')]


def test_worker_alive_with_a_silent_host_trips_its_watchdog(spawn):
    s, proc, actions = spawn()
    call(s, velocity(0.2), 1.0)
    started = time.monotonic()
    assert wait_exit(proc) == 3  # host silent > watchdog_s (3 s): the pipes stay open, nothing more arrives
    assert 3.0 <= time.monotonic() - started < 6.0
    assert [a['linear'] for a in events(actions, 'velocity')] == [0.2, 0.0] and events(actions, 'service_applied')


def test_lost_host_pipe_while_replying_still_stops(spawn):
    s, proc, actions = spawn(publish_delay_s=0.3)
    s.transport.send({'protocol': w.PROTOCOL, 'session_id': LIFECYCLE, 'request_id': 'r-velocity', 'op': 'exchange',
                      'args': {'timeout_s': 0.7, 'command': velocity(0.2)}})
    proc.stdout.close()  # the host stops listening before the reply is written
    assert wait_exit(proc) == 7  # HOST_PIPE_LOST
    assert [a['linear'] for a in events(actions, 'velocity')] == [0.2, 0.0] and events(actions, 'service_applied')


def test_worker_blocked_in_a_ros_call_still_zeroes_velocity_from_its_monitor(spawn):
    s, proc, actions = spawn(block_service_s=2.5)
    call(s, velocity(0.2), 2.0)
    with pytest.raises(TimeoutError):
        call(s, MODE_GUIDED, 2.0)  # worker budget 1.4 s, but the ROS call ignores it for 2.5 s
    assert s.broken  # the host never got the reply; its stop path through this session is gone
    wait_exit(proc, timeout=10.0)
    log = actions()
    zero = next(a for a in log if a['event'] == 'velocity' and a['linear'] == 0.0)
    unblocked = next(a for a in log if a['event'] == 'service_applied')
    assert zero['t'] < unblocked['t']  # the monitor stopped the motion WHILE the main thread was stuck
    assert zero['t'] - events(actions, 'service_call')[0]['t'] < 1.4 + w.OP_GRACE_S + 0.4


# Disarm is only possible inside an executor FINALIZING job (the adapter checks the job and the v3
# reservation), so these two go through the real executor + session + worker, in process.
def test_disarm_observed_after_the_stop(setup, monkeypatch):
    from tests.test_rover_first_navigation import run
    report, rover, holder, admitted = run(setup, monkeypatch)
    assert report['finalization']['status'] == 'DISARMED_STATIONARY_OBSERVED' and rover.armed is False
    from tools import vehicle_execution_lock as locks
    assert locks.restriction('v3') is None  # released only after the observed disarm


def test_disarm_without_an_answer_stays_unconfirmed_and_keeps_the_reservation(setup, monkeypatch):
    from tests.test_rover_first_navigation import run
    from tools import vehicle_execution_lock as locks

    def configure(rover, loop):
        original = rover.call_arm

        def call_arm(arm, timeout_s):
            if arm is False:
                rover.calls.append(('arm', False))
                raise TimeoutError('synthetic: ArmMotors(false) never answered')
            return original(arm, timeout_s)
        rover.call_arm = call_arm
    report, rover, holder, admitted = run(setup, monkeypatch, configure=configure)
    final = report['finalization']
    assert final['status'] == 'UNCONFIRMED' and final['disarm_attempted'] and not final['disarm_acknowledged']
    assert report['result']['stop']['status'] == 'STATIONARY_OBSERVED'  # the stop itself was observed
    assert locks.restriction('v3')['owner_id'] == admitted['run_id']  # an unconfirmed disarm keeps the protection
    assert holder['session'].effects_uncertain['operation'] == 'arm' and not holder['session'].broken
