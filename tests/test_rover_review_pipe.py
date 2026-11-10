"""Independent offline review: fake ROS, synthetic poses, no policy activation or operational stores."""
import copy
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import rover_first_navigation as nav, rover_ground_executor as ground
from tools import rover_pipe_worker as worker, rover_ros2_adapter as ros
from tools.rover_control import RoverControlError, synchronous_deadline
from tests.test_rover_first_navigation import CADENCE, facts, trial
from tests.test_rover_pipe_watchdog import worker as make_worker, ex
from tests.test_rover_pipe_worker import MODE_GUIDED, MODE_HOLD, session, velocity




def test_monitor_latches_without_waiting_for_a_blocked_publication_lock():
    core, backend, clock = make_worker()
    core.publish_lock.acquire()
    done = threading.Event()
    with core.busy('exchange', 0.1):
        clock.now += 1.0
        monitor = threading.Thread(target=lambda: (core.monitor_tick(), done.set()), daemon=True)
        monitor.start()
        try:
            assert done.wait(0.2), 'monitor blocked behind an in-flight publication'
            assert core.latched and core.monitor_record['zero_velocity'] == 'UNCONFIRMED_PUBLISH_BUSY'
        finally:
            core.publish_lock.release()
            monitor.join(1.0)
    assert backend.sent == []  # no claim that ROS accepted a stop


def test_monitor_detects_silence_even_when_main_is_stuck_outside_busy():
    core, backend, clock = make_worker()
    clock.now += core.limits['watchdog_s'] + 0.1
    result = core.monitor_tick()
    assert result and core.latched == 'WATCHDOG_HOST_SILENT'
    assert backend.sent == [(0.0, 0.0)]


def test_worker_after_uncertain_service_refuses_further_motion_but_accepts_stop():
    core, backend, _ = make_worker()
    backend.service_timeout = True
    assert ex(core, MODE_GUIDED)['error']['code'] == 'TIMEOUT_EFFECT_UNCONFIRMED'
    backend.service_timeout = False
    assert ex(core, velocity())['error']['code'] == 'MOTION_REFUSED'
    assert ex(core, MODE_HOLD)['ok']
    assert backend.sent == []


def test_malformed_graph_after_applied_command_breaks_host_session():
    host, transport, backend, _ = session()
    backend.spin(0.0)  # fresh telemetry, as after the preparation's first observation (GUIDED/ARM require it)
    original = transport.receive
    transport.receive = lambda timeout: dict(original(timeout), graph=[])
    with pytest.raises(RoverControlError):
        host.exchange(MODE_GUIDED, timeout_s=1.0)
    assert host.broken and host.effects_uncertain
    assert backend.calls == [('mode', 15)]
    with pytest.raises(RoverControlError):
        host.exchange(MODE_GUIDED, timeout_s=1.0)
    assert backend.calls == [('mode', 15)]  # no replay


def test_new_motion_rechecks_environment_fence_before_sending():
    host, transport, backend, _ = session()
    def expired(execution):
        raise RoverControlError('environment execution changed')
    host.fence = expired
    with pytest.raises(RoverControlError, match='environment'):
        host.exchange(MODE_GUIDED, timeout_s=1.0)
    assert not backend.calls


def test_deferred_monitor_zero_follows_a_publication_that_was_already_in_flight():
    core, backend, clock = make_worker()
    entered, release = threading.Event(), threading.Event()
    publish = backend.publish_velocity
    def blocked(linear, angular):
        if linear:
            entered.set()
            assert release.wait(1.0)
        publish(linear, angular)
    backend.publish_velocity = blocked
    sender = threading.Thread(target=lambda: ex(core, velocity()), daemon=True)
    sender.start()
    try:
        assert entered.wait(1.0)
        clock.now += 2.0
        assert core.monitor_tick()['zero_velocity'] == 'UNCONFIRMED_PUBLISH_BUSY'
    finally:
        release.set()
        sender.join(1.0)
    assert not sender.is_alive()
    assert backend.sent == [(0.1, 0.0), (0.0, 0.0)]
    assert core.monitor_record['zero_velocity'] == 'PUBLISHED'
    assert ex(core, velocity())['error']['code'] == 'MOTION_REFUSED'


def test_worker_cancellation_attempts_stop_before_backend_teardown():
    from tests.test_rover_pipe_watchdog import run_main
    from tests.test_rover_pipe_worker import FakeBackend, FakeClock, hello, req
    import json
    class Interrupted(FakeBackend):
        interrupted = False
        def spin(self, timeout_s):
            if self.calls and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt('synthetic worker cancellation')
            return super().spin(timeout_s)
    backend = Interrupted(FakeClock())
    code, output, backend = run_main([json.dumps(hello()),
        req('exchange', {'timeout_s': 1.0, 'command': MODE_GUIDED})], backend=backend)
    assert code == 6
    assert backend.sent == [(0.0, 0.0)] and backend.calls[-1] == ('mode', 4)
