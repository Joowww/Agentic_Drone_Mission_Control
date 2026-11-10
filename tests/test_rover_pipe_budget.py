"""Host/worker time budget over a REAL worker process, a REAL pipe and a REAL SIGALRM.

The host side is the production PipeRos2Session + JsonLineTransport inside the production
synchronous_deadline (what RoverControlCore._operation does). The worker is the production
rover_pipe_worker.main() in a child process; only its backend is scripted
(tests/rover_pipe_fake_worker.py): no ROS, container, SITL or vehicle. Its action log is the
ground truth of what "physically" happened, independent of what the host was told.
Timings are real but small (well under 2 s per case).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools import rover_pipe_session as ps, rover_pipe_worker as w, rover_ros2_adapter as ros
from tools.rover_control import RoverControlCore, RoverControlError, RoverLimits, synchronous_deadline
from tests.test_rover_pipe_worker import MODE_GUIDED, MODE_HOLD, ODOM_GID, STATUS_GID, evidence, velocity
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE

ROOT = Path(__file__).resolve().parents[1]
WORKER_LIMITS = {'max_linear_mps': 0.3, 'max_angular_rad_s': 0.5, 'watchdog_s': 3.0, 'telemetry_max_age_s': 1.0,
                 'max_session_s': 300.0, 'stopped_linear_mps': 0.03, 'stopped_angular_rad_s': 0.03}


@pytest.fixture
def spawn(tmp_path):
    procs = []

    def start(**config):
        log = tmp_path / f'worker{len(procs)}.jsonl'
        config = {'log': str(log), 'boot': BOOT, 'status_gid': STATUS_GID, 'odometry_gid': ODOM_GID, **config}
        proc = subprocess.Popen([sys.executable, '-B', '-m', 'tests.rover_pipe_fake_worker', json.dumps(config)],
                                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        procs.append(proc)
        session = ps.PipeRos2Session(ps.JsonLineTransport(proc), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                                     host_boot_id=BOOT, binding_evidence=evidence()[1], limits=dict(WORKER_LIMITS),
                                     fence=lambda e: None, motion_allowed=lambda: True, authority=lambda: None)

        def actions():
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return session, proc, actions
    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def call(session, command, T):
    """Exactly what RoverControlCore._operation does around an adapter call."""
    with synchronous_deadline(T):
        return session.exchange(command, timeout_s=T)


def events(actions, kind):
    return [a for a in actions() if a['event'] == kind]


def legacy(monkeypatch):
    monkeypatch.setattr(ps, 'WORKER_SHARE', 1.0)
    monkeypatch.setattr(ps, 'IPC_RESERVE_S', 0.0)
    monkeypatch.setattr(ps, 'HOST_GUARD_S', 0.0)


# ------------------------------------------------------------------ the split --
@pytest.mark.parametrize('T, worker', [(2.0, 1.4), (1.333, 0.9331), (1.0, 0.7), (0.5, 0.2), (0.4, 0.1)])
def test_budget_split_for_the_timeouts_the_controller_actually_uses(T, worker):
    b = ps.call_budget(T)
    assert b['worker_s'] == pytest.approx(worker, abs=1e-3) and b['worker_s'] < b['receive_s'] < T
    assert b['reserve_s'] >= ps.IPC_RESERVE_S + ps.HOST_GUARD_S - 1e-9


@pytest.mark.parametrize('T', [0.39, 0.2, 0.05])
def test_too_small_a_budget_sends_nothing(T):
    with pytest.raises(ps.BudgetExhausted) as info:
        ps.call_budget(T)
    assert info.value.diagnostic['effects'] == 'NOT_SENT'


def test_an_armed_alarm_shorter_than_timeout_s_bounds_the_budget():
    assert ps.call_budget(2.0, alarm_remaining_s=0.8)['host_s'] == 0.8


# ------------------------------------------------------- real pipe, real alarm --
def test_fast_reply(spawn):
    s, proc, actions = spawn()
    reply = call(s, MODE_GUIDED, 1.0)
    assert reply.payload == {'status': True, 'curr_mode': 15} and not s.broken
    # The worker's own deadline: 70 % of what is LEFT of the armed alarm, so a hair under 0.7 s.
    assert 0.69 < events(actions, 'service_call')[0]['timeout_s'] <= 0.7


def test_reply_just_before_the_worker_limit(spawn):
    s, proc, actions = spawn(service_delays=[0.6])  # worker limit 0.7 s of a 1.0 s host budget
    assert call(s, MODE_GUIDED, 1.0).payload['curr_mode'] == 15 and not s.broken


def test_reply_arriving_inside_the_reserved_margin_is_accepted(spawn):
    # The worker answers in 0.1 s but the pipe holds the reply 0.6 s: past the worker limit (0.7 s), inside 0.95 s.
    s, proc, actions = spawn(service_delays=[0.1], delay_reply_ops=['exchange'], reply_delay_s=0.6)
    started = time.monotonic()
    assert call(s, MODE_GUIDED, 1.0).payload['curr_mode'] == 15
    assert 0.7 < time.monotonic() - started < 0.95 and not s.broken


def test_reply_after_the_host_deadline_breaks_the_session_before_the_alarm(spawn):
    s, proc, actions = spawn(service_delays=[0.1], delay_reply_ops=['exchange'], reply_delay_s=1.5)
    with pytest.raises(TimeoutError) as info:
        call(s, MODE_GUIDED, 1.0)
    assert info.value.diagnostic['effects'] == 'UNCONFIRMED'  # the session's own read deadline, not SIGALRM
    assert s.broken == 'TimeoutError' and events(actions, 'service_applied')  # it DID happen in the worker
    with pytest.raises(RoverControlError, match='unusable'):
        call(s, MODE_HOLD, 1.0)  # no replay over a broken channel


def test_lost_reply_of_an_executed_command_is_unconfirmed_and_never_resent(spawn):
    s, proc, actions = spawn(drop_reply_ops=['exchange'])
    with pytest.raises(TimeoutError) as info:
        call(s, MODE_GUIDED, 1.0)
    assert info.value.diagnostic['effects'] == 'UNCONFIRMED' and s.broken
    assert len(events(actions, 'service_applied')) == 1  # executed once, reported uncertain, not resent


def test_eof_during_an_operation(spawn):
    s, proc, actions = spawn(exit_during_service=True)
    with pytest.raises(TimeoutError) as info:
        call(s, MODE_GUIDED, 1.0)
    assert info.value.diagnostic['transport'] == 'TransportClosed' and s.broken == 'TransportClosed'
    assert events(actions, 'service_applied')  # the effect happened although the host saw only EOF


def test_worker_process_terminated(spawn):
    s, proc, actions = spawn()
    proc.kill()
    proc.wait(timeout=5)
    with pytest.raises(TimeoutError) as info:
        call(s, MODE_HOLD, 1.0)
    assert info.value.diagnostic['effects'] == 'UNCONFIRMED' and s.broken


def test_slow_vehicle_keeps_the_session_for_stop_and_reproduces_the_old_defect(spawn, monkeypatch):
    # ArduPilot answers after 1.5 s; host budget 1.0 s.
    s, proc, actions = spawn(service_delays=[1.5, 0.0])
    with pytest.raises(TimeoutError) as info:
        call(s, MODE_GUIDED, 1.0)
    assert info.value.diagnostic['worker_code'] == 'TIMEOUT_EFFECT_UNCONFIRMED' and not s.broken
    assert call(s, MODE_HOLD, 1.0).payload['curr_mode'] == 4  # a stop still goes through


def test_old_budget_lets_the_real_alarm_break_the_session(spawn, monkeypatch):
    legacy(monkeypatch)
    s, proc, actions = spawn(service_delays=[1.5, 0.0])
    started = time.monotonic()
    with pytest.raises(TimeoutError) as info:
        call(s, MODE_GUIDED, 1.0)  # the worker waits the whole 1.0 s: the SIGALRM fires inside the pipe read
    assert 0.99 <= time.monotonic() - started < 1.3
    assert info.value.diagnostic['response_received'] is False and s.broken == 'TimeoutError'
    with pytest.raises(RoverControlError, match='unusable'):
        call(s, MODE_HOLD, 1.0)  # the defect: no stop over this channel any more


def test_repeated_timeouts_never_resend_and_allow_only_stops(spawn):
    s, proc, actions = spawn(service_delays=[5.0], apply_on_timeout=True)
    with pytest.raises(TimeoutError):
        call(s, MODE_GUIDED, 1.0)
    assert s.effects_uncertain['operation'] == 'mode'
    with pytest.raises(RoverControlError, match='only stop commands'):
        call(s, MODE_GUIDED, 1.0)  # refused on the host: never sent
    with pytest.raises(RoverControlError, match='only stop commands'):
        call(s, velocity(0.1), 1.0)
    with pytest.raises(TimeoutError):
        call(s, MODE_HOLD, 1.0)  # a stop is allowed; it times out too and is reported uncertain
    calls = events(actions, 'service_call')
    assert [c['service'] for c in calls] == ['mode', 'mode'] and not s.broken  # GUIDED once, HOLD once


def test_second_order_after_a_failure_only_if_it_is_a_stop(spawn):
    s, proc, actions = spawn(service_delays=[1.5, 0.0])
    with pytest.raises(TimeoutError):
        call(s, MODE_GUIDED, 1.0)
    with pytest.raises(RoverControlError, match='only stop commands'):
        call(s, velocity(0.2), 1.0)
    assert call(s, velocity(0.0), 1.0).sent and call(s, MODE_HOLD, 1.0).payload['curr_mode'] == 4
    assert events(actions, 'velocity') == [{'event': 'velocity', 'linear': 0.0, 'angular': 0.0,
                                            't': events(actions, 'velocity')[0]['t']}]


def test_budget_exhausted_sends_nothing_and_keeps_the_session(spawn):
    s, proc, actions = spawn()
    with pytest.raises(ps.BudgetExhausted):
        call(s, MODE_HOLD, 0.3)
    assert not s.broken and s.effects_uncertain is None and events(actions, 'service_call') == []


# ------------------------------------------------------------- stop end to end --
def core_over(s, monkeypatch, *, stop_timeout_s=8.0):
    monkeypatch.setattr(ros, 'assert_execution_authority', lambda v: None)  # transport test: no reservation store
    limits = RoverLimits(max_forward_mps=0.3, max_yaw_rate_rad_s=0.5, max_duration_s=60.0, call_timeout_s=2.0,
                         stop_timeout_s=stop_timeout_s, observation_max_age_s=1.0, stopped_linear_mps=0.03,
                         stopped_angular_rad_s=0.03)
    adapter = ros.Ros2RoverAdapter(s, binding=s.binding)
    with synchronous_deadline(2.0):
        adapter.probe(timeout_s=2.0)
    return RoverControlCore(limits, adapter=adapter)


def test_stop_with_telemetry_available_is_observed(spawn, monkeypatch):
    s, proc, actions = spawn(status_hz=5.0)
    result = core_over(s, monkeypatch).stop(force_zero=True)
    assert result['status'] == 'STATIONARY_OBSERVED' and result['ground_contact_confirmed'] is False
    assert [a['event'] for a in actions() if a['event'] in ('velocity', 'service_applied')] == ['velocity', 'service_applied']


def test_stop_that_cannot_be_observed_stays_unconfirmed(spawn, monkeypatch):
    s, proc, actions = spawn(status_hz=5.0, freeze_status_after_hold=True)
    result = core_over(s, monkeypatch).stop(force_zero=True)
    assert result['status'] == 'UNCONFIRMED' and result['stationary_observed'] is False
    assert events(actions, 'service_applied')  # HOLD was requested and applied; only its observation is missing
    assert not s.broken  # the worker answered every time-out inside the host budget
