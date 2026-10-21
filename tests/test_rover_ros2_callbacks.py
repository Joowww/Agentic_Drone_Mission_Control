"""Offline regression for the archived installed Humble executor's callback ABI.

Its _take_subscription returns msg_info[0]; _execute_subscription invokes
await await_or_execute(sub.callback, msg). No MessageInfo reaches the callback.
"""
import asyncio
import inspect
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.rover_ros2_adapter import NativeRos2Session, STATUS, ODOMETRY
from tools.rover_control import RoverControlError


def test_installed_one_argument_dispatch_for_both_native_subscriptions(monkeypatch):
    callbacks = {}

    def subscribe(cls, topic, callback, qos):
        callbacks[topic] = callback
        return object()

    node = SimpleNamespace(create_subscription=subscribe, create_client=Mock(),
                           create_publisher=Mock(), destroy_node=Mock())
    rclpy = ModuleType('rclpy')
    rclpy.init = Mock()
    rclpy.create_node = Mock(return_value=node)
    monkeypatch.setitem(sys.modules, 'rclpy', rclpy)
    for package, values in {
        'rclpy.context': {'Context': Mock},
        'rclpy.qos': {'QoSProfile': lambda **kw: kw,
                      'ReliabilityPolicy': SimpleNamespace(BEST_EFFORT=1),
                      'DurabilityPolicy': SimpleNamespace(VOLATILE=1)},
        'ardupilot_msgs.msg': {'Status': object()},
        'ardupilot_msgs.srv': {'ModeSwitch': object()},
        'geometry_msgs.msg': {'TwistStamped': object()},
        'nav_msgs.msg': {'Odometry': object()},
        'rosidl_runtime_py.convert': {'message_to_ordereddict': lambda msg: msg},
    }.items():
        monkeypatch.setitem(sys.modules, package.split('.')[0],
                            sys.modules.get(package.split('.')[0], ModuleType(package.split('.')[0])))
        module = ModuleType(package)
        for name, value in values.items():
            setattr(module, name, value)
        monkeypatch.setitem(sys.modules, package, module)

    session = NativeRos2Session()
    assert set(callbacks) == {STATUS, ODOMETRY}

    async def await_or_execute(callback, *args):
        if inspect.iscoroutinefunction(callback):
            return await callback(*args)
        return callback(*args)

    async def execute_subscription(sub, msg):
        # Exact invocation in the locally archived rclpy executors.py, lines 405–407.
        if msg:
            await await_or_execute(sub.callback, msg)

    for topic, kind in ((STATUS, 'status'), (ODOMETRY, 'odometry')):
        msg = {'header': {'stamp': {'sec': 1, 'nanosec': 0}}}
        assert len(inspect.signature(callbacks[topic]).parameters) == 1
        asyncio.run(execute_subscription(SimpleNamespace(callback=callbacks[topic]), msg))
        converted, received, gid = session.latest[kind]
        assert converted == msg
        assert received > 0
        assert gid is None  # never infer message attribution from graph endpoints

    with pytest.raises(RoverControlError, match='identity worker'):
        session.observe(timeout_s=.1)
    node.create_client.return_value.call_async.assert_not_called()
    node.create_publisher.return_value.publish.assert_not_called()
