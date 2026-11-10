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




@pytest.mark.parametrize('check', [ros._assert_disarm_scope, ros._assert_preparation_scope])
def test_reservation_lost_between_authority_and_scope_is_explicit(check, monkeypatch):
    monkeypatch.setattr(ros, 'assert_execution_authority', lambda vehicle: None)
    monkeypatch.setattr('tools.vehicle_execution_lock.restriction', lambda vehicle: None)
    with pytest.raises(RoverControlError, match='reservation'):
        check()


@pytest.mark.parametrize('iteration', range(20))
def test_native_service_timeout_cancels_once_without_retry(iteration):
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native.node = object()
    native.mode_type = SimpleNamespace(Request=lambda: SimpleNamespace(mode=None))
    future = SimpleNamespace(done=lambda: False, cancel=Mock())
    native.client = SimpleNamespace(call_async=Mock(return_value=future))
    native.rclpy = SimpleNamespace(spin_until_future_complete=Mock())
    native._check_cancelled = lambda: None
    with pytest.raises(TimeoutError):
        with synchronous_deadline(0.02):
            native._exchange(MODE_HOLD, timeout_s=0.02)
    future.cancel.assert_called_once()
    native.client.call_async.assert_called_once()


def test_deadline_does_not_raise_inside_weakref_finalizer():
    import sys
    import time
    import weakref

    unraisable=[]
    previous=sys.unraisablehook
    sys.unraisablehook=unraisable.append
    try:
        class Referent:
            pass
        value=Referent()
        reference=weakref.ref(value,lambda _: time.sleep(.05))
        with pytest.raises(TimeoutError,match='Synchronous'):
            with synchronous_deadline(.01):
                del value
        assert unraisable==[]
    finally:
        sys.unraisablehook=previous


def test_alarm_after_future_is_assigned_also_runs_local_cleanup():
    import sys
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native.node = object()
    native.mode_type = SimpleNamespace(Request=lambda: SimpleNamespace(mode=None))
    future = SimpleNamespace(done=lambda: False, cancel=Mock())
    native.client = SimpleNamespace(call_async=Mock(return_value=future))
    native._check_cancelled = lambda: None
    def interrupt(frame, event, arg):
        if (frame.f_code is ros.NativeRos2Session._exchange.__code__ and event == 'line'
                and frame.f_locals.get('future') is future):
            sys.settrace(None)
            raise TimeoutError('synthetic alarm immediately after future assignment')
        return interrupt
    previous = sys.gettrace()
    try:
        sys.settrace(interrupt)
        with pytest.raises(TimeoutError):
            native._exchange(MODE_HOLD, timeout_s=0.3)
    finally:
        sys.settrace(previous)
    future.cancel.assert_called_once()
    native.client.call_async.assert_called_once()
