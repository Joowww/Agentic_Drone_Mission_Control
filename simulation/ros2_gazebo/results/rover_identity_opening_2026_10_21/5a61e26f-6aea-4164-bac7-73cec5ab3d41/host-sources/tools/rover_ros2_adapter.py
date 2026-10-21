"""Lazy native ROS 2 adapter; no ROS imports, node or control on module import.

No Docker fallback or CLI. Default independent-motion binding is UNACCREDITED.
The protected executor is disabled operationally until that binding is established.
"""
from dataclasses import dataclass
import time

from tools.rover_control import Observation, Reply, RoverControlCore, RoverControlError, number
from tools.vehicle_execution_lock import assert_execution_authority, utc_now
from tools.execution_diagnostics import error_evidence
from tools.rover_environment_identity import RoverEnvironmentGuard

STATUS = '/ap/v3/status'
ODOMETRY = '/rover1/odometry'  # expected launch namespace; must be observed, never assumed
MODE = '/ap/v3/mode_switch'
VELOCITY = '/ap/v3/cmd_vel'


@dataclass(frozen=True)
class MotionBinding:
    """Input for a future audited binding collector, NOT created by discovery alone.

    Local ROS graph names cannot prove which Gazebo model supplies a bridge.
    A production source of this accreditation has not yet been implemented.
    """
    environment_identity_sha256: str
    active_bridge_config_sha256: str
    odometry_publisher_gid: str
    gz_topic: str = '/model/rover1/odometry'
    ros_topic: str = ODOMETRY
    child_frame: str = 'base_link'

    def check(self):
        for value in (self.environment_identity_sha256, self.active_bridge_config_sha256):
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise RoverControlError('Missing motion binding artifact hashes')
        if (not isinstance(self.odometry_publisher_gid, str) or not self.odometry_publisher_gid or self.gz_topic != '/model/rover1/odometry'
                or self.ros_topic != ODOMETRY or self.child_frame != 'base_link'):
            raise RoverControlError('Incompatible independent-motion binding')


class Ros2RoverAdapter:
    def __init__(self, session, *, binding=None, clock=time, journal=lambda event: None):
        self.session, self.binding, self.clock, self.journal = session, binding, clock, journal
        self.capabilities = None

    def probe(self, *, timeout_s):
        assert_execution_authority('v3')
        timeout_s = number(timeout_s, 'probe timeout', positive=True)
        started = self.clock.monotonic()
        record = {'operation': 'probe', 'vehicle_id': 'rover_01', 'interface': 'v3',
                  'started_at_utc': utc_now(), 'timeout_s': timeout_s,
                  'capabilities': None, 'effects': 'READ_ONLY'}
        try:
            if not isinstance(self.binding, MotionBinding):
                raise RoverControlError('Independent rover odometry binding not accredited; discovery alone is insufficient')
            self.binding.check()
            caps = self.session.probe(timeout_s=timeout_s)
            record['capabilities'] = caps
            if self.clock.monotonic() - started > timeout_s:
                raise TimeoutError('Transport discovery exceeded finite wall budget')
            expected = {'status_type': 'ardupilot_msgs/msg/Status',
                        'odometry_type': 'nav_msgs/msg/Odometry',
                        'mode_type': 'ardupilot_msgs/srv/ModeSwitch',
                        'velocity_type': 'geometry_msgs/msg/TwistStamped'}
            if (not isinstance(caps, dict) or any(caps.get(k) != v for k, v in expected.items())
                    or caps.get('mode_available') is not True
                    or type(caps.get('velocity_subscribers')) is not int or caps['velocity_subscribers'] < 1
                    or caps.get('odometry_publisher_gids') != [self.binding.odometry_publisher_gid]
                    or type(caps.get('status_publishers')) is not int or caps['status_publishers'] != 1):
                raise RoverControlError('Missing, ambiguous or incompatible ROS transport capabilities')
            self.capabilities = caps
            return caps
        except Exception as exc:
            record['error_evidence'] = error_evidence(exc)
            raise
        finally:
            record.update(finished_at_utc=utc_now(), duration_wall_s=self.clock.monotonic()-started,
                          clock='HOST_UTC_AND_MONOTONIC_NOT_SIMULATED_TIME')
            self.journal(record)

    def observe(self, *, timeout_s):
        assert_execution_authority('v3')
        if self.capabilities is None:
            self.probe(timeout_s=timeout_s)
        raw = self.session.observe(timeout_s=timeout_s)
        self.journal({'operation': 'observe', 'raw': raw})
        # Native session returns dictionaries from typed messages + separate host receipts.
        status, odom = raw['status'], raw['odometry']
        if raw.get('odometry_publisher_gid') != self.binding.odometry_publisher_gid:
            raise RoverControlError('Observation publisher differs from accredited bridge')
        if odom['child_frame_id'] != self.binding.child_frame:
            raise RoverControlError('Odometry child frame contradicts independent-motion binding')
        return Observation(
            vehicle_id='rover_01', interface='v3', vehicle_type=status['vehicle_type'],
            mode=status['mode'], armed=status['armed'], flying=status['flying'],
            external_control=status['external_control'], failsafe=tuple(status['failsafe']),
            received_monotonic_s=raw['status_received_monotonic_s'], status_source_ns=_stamp(status),
            velocity_source_ns=_stamp(odom),
            linear_mps=_vector(odom['twist']['twist']['linear']),
            angular_rad_s=_vector(odom['twist']['twist']['angular']),
            motion_source=self.binding.gz_topic, motion_frame=odom['child_frame_id'],
            motion_received_monotonic_s=raw['odometry_received_monotonic_s'])

    def exchange(self, command, *, timeout_s):
        assert_execution_authority('v3')
        if self.capabilities is None:
            raise RoverControlError('Probe required before controls')
        _validate_command(command)
        # Journal intent DURABLY before calling the session. Exceptions may have effects.
        self.journal({'operation': 'control_intent', 'command': command,
                      'timeout_s': timeout_s, 'effects': 'UNCONFIRMED'})
        reply = self.session.exchange(command, timeout_s=timeout_s)
        self.journal({'operation': 'control_reply', 'reply': reply.__dict__})
        return reply


def _validate_command(command):
    if not isinstance(command, dict):
        raise RoverControlError("Typed ground command required")
    # Exact whitelist prevents arbitrary endpoints/types/fields and Copter commands.
    if command.get('kind') == 'service':
        if not isinstance(command.get('payload'), dict):
            raise RoverControlError('Typed ModeSwitch payload required')
        mode = command['payload'].get('mode')
        if type(mode) is not int or mode not in (4, 15) or command != {
            'kind': 'service', 'endpoint': MODE, 'type': 'ardupilot_msgs/srv/ModeSwitch',
            'payload': {'mode': mode}}:
            raise RoverControlError('Unsupported Rover service request')
    else:
        try:
            twist = command['payload']['twist']
            expected = RoverControlCore.velocity_message(twist['linear']['x'], twist['angular']['z'])
        except (KeyError, TypeError) as exc:
            raise RoverControlError('Malformed ground velocity request') from exc
        if command != expected:
            raise RoverControlError('Unsupported velocity topic, type, frame or axes')


def _stamp(message):
    stamp = message['header']['stamp']
    sec, nanosec = stamp['sec'], stamp['nanosec']
    if type(sec) is not int or type(nanosec) is not int or sec < 0 or not 0 <= nanosec < 10**9:
        raise RoverControlError('Invalid source timestamp')
    return sec * 10**9 + nanosec


def _vector(value):
    return tuple(number(value[k], 'velocity component') for k in ('x', 'y', 'z'))


class NativeRos2Session:
    """Explicitly constructed inside a future ROS 2 worker, never by default.

    Uses typed AP_DDS messages/services, volatile subscriptions and finite wall
    deadlines. No ros2 CLI parsing, shell commands, automatic retry or arming.
    """
    def __init__(self, *, identity_guard=None):
        self.identity_guard = identity_guard
        import rclpy
        from rclpy.context import Context
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from ardupilot_msgs.msg import Status
        from ardupilot_msgs.srv import ModeSwitch
        from geometry_msgs.msg import TwistStamped
        from nav_msgs.msg import Odometry
        from rosidl_runtime_py.convert import message_to_ordereddict
        self.rclpy, self.convert = rclpy, message_to_ordereddict
        self.context = Context()
        rclpy.init(context=self.context)
        self.node = rclpy.create_node('tfg_protected_rover_worker', context=self.context)
        qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)
        self.latest = {}
        self.previous = {}
        def callback(kind):
            def receive(msg, info):
                self.latest[kind] = (self.convert(msg), time.monotonic(), bytes(info.publisher_gid).hex())
            return receive
        self.subscriptions = [self.node.create_subscription(cls, topic, callback(kind), qos)
            for cls, topic, kind in ((Status, STATUS, 'status'), (Odometry, ODOMETRY, 'odometry'))]
        self.mode_type, self.velocity_type = ModeSwitch, TwistStamped
        self.client = self.node.create_client(ModeSwitch, MODE)
        self.publisher = self.node.create_publisher(TwistStamped, VELOCITY, qos)

    def _require_identity(self):
        guard = getattr(self, 'identity_guard', None)
        if type(guard) is not RoverEnvironmentGuard:
            raise RoverControlError('Supervised rover identity worker/current environment collector unavailable')
        guard.require_motion_source()  # currently always BLOCKED: no XRCE source accreditation yet

    def probe(self, *, timeout_s):
        self._require_identity()
        # One bounded discovery spin; absent discovery blocks rather than waiting/retrying controls.
        self.rclpy.spin_once(self.node, timeout_sec=min(number(timeout_s, 'timeout', positive=True), .1))
        topics = dict(self.node.get_topic_names_and_types())
        services = dict(self.node.get_service_names_and_types())
        def single(values):
            return values[0] if len(values) == 1 else None
        infos = self.node.get_publishers_info_by_topic(ODOMETRY)
        return {'status_type': single(topics.get(STATUS, [])),
                'odometry_type': single(topics.get(ODOMETRY, [])),
                'mode_type': single(services.get(MODE, [])),
                'velocity_type': single(topics.get(VELOCITY, [])),
                'mode_available': self.client.service_is_ready(),
                'velocity_subscribers': self.publisher.get_subscription_count(),
                'status_publishers': len(self.node.get_publishers_info_by_topic(STATUS)),
                'odometry_publisher_gids': [bytes(x.endpoint_gid).hex() for x in infos]}

    def observe(self, *, timeout_s):
        self._require_identity()
        started = time.monotonic()
        deadline = started + number(timeout_s, 'timeout', positive=True)
        while time.monotonic() < deadline:
            self.rclpy.spin_once(self.node, timeout_sec=min(.05, max(0., deadline-time.monotonic())))
            if not all(k in self.latest and self.latest[k][1] >= started for k in ('status', 'odometry')):
                continue
            stamps = {k: _stamp(self.latest[k][0]) for k in ('status', 'odometry')}
            if any(k in self.previous and stamps[k] <= self.previous[k] for k in stamps):
                raise RoverControlError('Frozen/rewound source clock; observation cannot confirm stop')
            self.previous = stamps
            return {'odometry_publisher_gid': self.latest['odometry'][2]} | {k: self.latest[k][0] for k in stamps} | {
                k+'_received_monotonic_s': self.latest[k][1] for k in stamps}
        exc = TimeoutError('Fresh status/independent odometry unavailable within wall deadline')
        exc.diagnostic = {'operation': 'observe', 'timeout_s': timeout_s,
                          'partial_samples': {k: {'message': v[0], 'received_monotonic_s': v[1]}
                                              for k, v in self.latest.items() if v[1] >= started}}
        raise exc

    def exchange(self, command, *, timeout_s):
        assert_execution_authority('v3')
        self._require_identity()
        _validate_command(command)
        deadline = time.monotonic() + number(timeout_s, 'timeout', positive=True)
        if command['kind'] == 'service':
            request = self.mode_type.Request()
            request.mode = command['payload']['mode']
            future = self.client.call_async(request)
            self.rclpy.spin_until_future_complete(self.node, future, timeout_sec=max(0., deadline-time.monotonic()))
            if not future.done():
                future.cancel()  # cancelling the local future does NOT undo a possibly received request
                exc = TimeoutError('ModeSwitch response absent; request effects unconfirmed')
                exc.diagnostic = {'service': MODE, 'type': 'ardupilot_msgs/srv/ModeSwitch',
                                  'request': command['payload'], 'timeout_s': timeout_s,
                                  'response_received': False, 'effects': 'UNCONFIRMED'}
                raise exc
            response = future.result()
            return Reply(True, None, {'status': response.status, 'curr_mode': response.curr_mode}, native_api_completed=True)
        message = self.velocity_type()
        message.header.stamp = self.node.get_clock().now().to_msg()
        message.header.frame_id = 'base_link'
        message.twist.linear.x = command['payload']['twist']['linear']['x']
        message.twist.angular.z = command['payload']['twist']['angular']['z']
        if self.publisher.get_subscription_count() < 1:
            raise RoverControlError('Velocity subscriber disappeared before publish')
        self.publisher.publish(message)
        return Reply(True, None, native_api_completed=True)  # no process exit code or application response

    def close(self):
        self.node.destroy_node()
        self.context.shutdown()
