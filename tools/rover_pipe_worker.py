"""Container-side rclpy worker for ONE supervised rover_01/v3 session; JSON Lines on stdin/stdout.

Holds no authority: it cannot create authorizations, touch reservations or decide
to move. It relays the host's exact, already validated requests to AP_DDS and
reports what it observes. stdout carries only protocol lines; diagnostics go to
stderr. Self-contained (no project imports) because it is passed to
`python3 -c` inside the container; rclpy is imported only in main().

Modes, fixed by the hello and never changed later in the session:
- PASSIVE: probe/observe/close only. The ROS backend creates no publisher and no
  service client at all; exchange is refused without touching ROS and ends the
  session; EOF/watchdog/violations end it with no ROS control action.
- OPERATIONAL: limits fixed by the hello and capped by HARD_LIMITS. Its own safety policy,
  independent of any further host message:
  * EOF, host silence longer than watchdog_s, session older than max_session_s, a protocol
    violation, a backend exception or a lost host pipe (stdout write failure) -> safe_stop():
    zero velocity, HOLD once, a bounded look at the next status/odometry, report, exit;
  * a main thread stuck in ONE operation past its deadline + OP_GRACE_S -> the monitor thread
    publishes zero velocity (topic only, no service call) and latches the session;
  * non-zero velocity, GUIDED and ARM are refused when the worker's own latest status or
    odometry is older than telemetry_max_age_s, and after any latch;
  * GUIDED/ARM are accepted only before the session has lost telemetry (an observe timeout) or
    had a stop (HOLD or disarm) acknowledged: no re-arm without a new session and authority;
  * close with motion still possible (GUIDED/armed/moving, no HOLD or disarm since) -> the
    close is acknowledged, then safe_stop().
  The worker never reports a confirmed stop and never retries; the host judges observations.
  Residual risk: if ROS 2 itself is lost (no subscriber, DDS down) nothing here can stop the
  vehicle; ArduRover's own failsafes are the last layer.
"""
from contextlib import contextmanager
import json
import math
import os
import sys
import threading
import time

PROTOCOL = 'tfg.rover.pipe/2'
MAX_LINE_BYTES = 65536
STATUS = '/ap/v3/status'
ODOMETRY = '/rover1/odometry'
MODE = '/ap/v3/mode_switch'
ARM = '/ap/v3/arm_motors'
VELOCITY = '/ap/v3/cmd_vel'
OPS = {'probe', 'observe', 'exchange', 'close'}
MODES = ('PASSIVE', 'OPERATIONAL')
MAX_TIMEOUT_S = 30.0
OPERATIONAL_LIMITS = ('max_linear_mps', 'max_angular_rad_s', 'watchdog_s', 'telemetry_max_age_s', 'max_session_s',
                      'stopped_linear_mps', 'stopped_angular_rad_s')
PASSIVE_MAX_SESSION_S = 300.0
PASSIVE_LIMITS = ('watchdog_s', 'max_session_s')
# Whatever the hello says, the worker never accepts looser values than these.
HARD_LIMITS = {'max_linear_mps': 1.0, 'max_angular_rad_s': 1.5, 'watchdog_s': 5.0, 'telemetry_max_age_s': 3.0,
               'max_session_s': 900.0, 'stopped_linear_mps': 0.1, 'stopped_angular_rad_s': 0.1}
OP_GRACE_S = 0.5        # an operation (or a reply write) blocked this long past its deadline trips the monitor
STOP_OBSERVE_S = 2.0    # safe_stop's bounded look at the vehicle after HOLD
MONITOR_PERIOD_S = 0.1


class ProtocolError(ValueError):
    pass


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_command(command, *, max_linear_mps, max_angular_rad_s):
    """Exact allowlist, same shapes as tools.rover_ros2_adapter._validate_command."""
    if not isinstance(command, dict):
        raise ProtocolError('Command must be an object')
    if command.get('kind') == 'service' and command.get('endpoint') == MODE:
        if (command != {'kind': 'service', 'endpoint': MODE, 'type': 'ardupilot_msgs/srv/ModeSwitch',
                        'payload': {'mode': command.get('payload', {}).get('mode')}}
                or type(command['payload']['mode']) is not int or command['payload']['mode'] not in (4, 15)):
            raise ProtocolError('Only exact ModeSwitch 4 (HOLD) or 15 (GUIDED)')
        return 'mode'
    if command.get('kind') == 'service' and command.get('endpoint') == ARM:
        arm = command.get('payload', {}).get('arm')
        if type(arm) is not bool or command != {'kind': 'service', 'endpoint': ARM,
                                                'type': 'ardupilot_msgs/srv/ArmMotors', 'payload': {'arm': arm}}:
            raise ProtocolError('Only exact ArmMotors arm/disarm')
        return 'arm'
    if command.get('kind') == 'topic' and command.get('endpoint') == VELOCITY:
        try:
            twist = command['payload']['twist']
            linear, angular = twist['linear']['x'], twist['angular']['z']
        except (KeyError, TypeError) as exc:
            raise ProtocolError('Malformed velocity command') from exc
        expected = {'kind': 'topic', 'endpoint': VELOCITY, 'type': 'geometry_msgs/msg/TwistStamped',
                    'payload': {'header': {'frame_id': 'base_link'}, 'twist': {
                        'linear': {'x': linear, 'y': 0.0, 'z': 0.0}, 'angular': {'x': 0.0, 'y': 0.0, 'z': angular}}}}
        if (command != expected or not _finite(linear) or not _finite(angular)
                or abs(linear) > max_linear_mps or abs(angular) > max_angular_rad_s):
            raise ProtocolError('Velocity outside the exact base_link schema or session limits')
        return 'velocity'
    raise ProtocolError('Unknown or unauthorized command')


def is_stop(command, kind):
    return (kind == 'mode' and command['payload']['mode'] == 4
            or kind == 'arm' and command['payload']['arm'] is False
            or kind == 'velocity' and command['payload']['twist']['linear']['x'] == 0.0
            and command['payload']['twist']['angular']['z'] == 0.0)


class WorkerCore:
    """Protocol and watchdog logic over an injected backend (rclpy in the container, fakes in tests)."""
    def __init__(self, backend, hello, *, clock=time.monotonic):
        if not isinstance(hello, dict) or hello.get('protocol') != PROTOCOL or hello.get('op') != 'hello':
            raise ProtocolError('First line must be a hello for ' + PROTOCOL)
        self.backend, self.clock = backend, clock
        self.session_id = hello.get('session_id')
        self.mode = hello.get('mode')
        expected = hello.get('expected_gids') or {}
        limits = hello.get('limits') or {}
        needed = PASSIVE_LIMITS if self.mode == 'PASSIVE' else OPERATIONAL_LIMITS
        if (self.mode not in MODES or not isinstance(self.session_id, str) or not self.session_id
                or set(expected) != {'status', 'odometry'} or not all(isinstance(v, str) and len(v) == 48 for v in expected.values())
                or not isinstance(limits, dict) or set(limits) != set(needed)
                or not all(_finite(limits[k]) and 0 < limits[k] <= HARD_LIMITS[k] for k in needed)
                or (self.mode == 'PASSIVE' and limits.get('max_session_s', PASSIVE_MAX_SESSION_S + 1) > PASSIVE_MAX_SESSION_S)):
            raise ProtocolError('Hello lacks mode, session, expected GIDs or exact limits within HARD_LIMITS')
        self.expected, self.limits = dict(expected), {k: float(v) for k, v in limits.items()}
        self.seen_ids = set()
        self.started = self.last_request = clock()
        self.latched = None      # reason once motion is refused for the rest of the session
        self.closed = False
        self.stop_record = None
        self.monitor_record = None
        self.motion_possible = False  # GUIDED/armed/moving requested with no HOLD or disarm acknowledged since
        self.preparation_closed = None  # once set, GUIDED/ARM are refused for the rest of the session
        self.publish_lock = threading.Lock()
        self.busy_until, self.busy_label = None, None

    # -- identity --------------------------------------------------------
    def graph(self):
        found = {}
        for name, topic in (('status', STATUS), ('odometry', ODOMETRY)):
            rows = self.backend.publishers(topic)
            found[name] = rows[0]['gid'] if len(rows) == 1 else None
            found[name + '_publishers'] = len(rows)
        return found

    def _identity_ok(self, graph):
        return graph['status'] == self.expected['status'] and graph['odometry'] == self.expected['odometry']

    # -- protocol --------------------------------------------------------
    def handle(self, line):
        """One request -> one reply carrying the worker's own timing (worker monotonic clock only)."""
        received = self.clock()
        reply = self._handle(line)
        reply['timing'] = self._timing(received)
        return reply

    def _timing(self, received):
        # Durations and ages measured on THIS process's monotonic clock. Never to be read as host
        # times; the host compares durations, and absolute values only after a bracketing check.
        ages = {}
        for kind in ('status', 'odometry'):
            try:
                age = self.backend.telemetry_age_s(kind)
                ages[kind] = age if _finite(age) else None
            except Exception:
                ages[kind] = None
        replied = self.clock()
        return {'clock': 'WORKER_MONOTONIC_S', 'received_s': received, 'replied_s': replied,
                'handled_s': replied - received, 'telemetry_age_s': ages}

    def _handle(self, line):
        if len(line.encode()) > MAX_LINE_BYTES:
            return self._violation(None, 'LINE_TOO_LARGE')
        try:
            request = json.loads(line)
        except ValueError:
            return self._violation(None, 'MALFORMED_JSON')
        rid = request.get('request_id') if isinstance(request, dict) else None
        if (not isinstance(request, dict) or request.get('protocol') != PROTOCOL
                or request.get('session_id') != self.session_id or not isinstance(rid, str) or not rid
                or request.get('op') not in OPS or not isinstance(request.get('args', {}), dict)):
            return self._violation(rid, 'ENVELOPE_INVALID')
        if rid in self.seen_ids:
            return self._reply(rid, error=('DUPLICATE_REQUEST_ID', 'Request ids are single-use; nothing executed'))
        self.seen_ids.add(rid)
        self.last_request = self.clock()
        if self.closed:
            return self._reply(rid, error=('CLOSED', 'Session closed'))
        op, args = request['op'], request.get('args', {})
        if self.session_expired():
            self.latched = self.latched or 'SESSION_EXPIRED'
            if self.mode == 'PASSIVE' and op != 'close':
                return self._reply(rid, error=('SESSION_EXPIRED', 'Passive deadline reached; no further observation accepted'))
        bound = args.get('timeout_s') if _finite(args.get('timeout_s')) and 0 < args.get('timeout_s') <= MAX_TIMEOUT_S else 0.0
        try:
            with self.busy(op, bound):
                return getattr(self, '_op_' + op)(rid, args)
        except ProtocolError as exc:
            return self._reply(rid, error=('INVALID_ARGUMENTS', str(exc)))
        except TimeoutError as exc:
            if op == 'exchange':
                self.latched = self.latched or 'EFFECT_UNCONFIRMED'
            elif op == 'observe':
                self.preparation_closed = self.preparation_closed or 'TELEMETRY_LOST'
            return self._reply(rid, error=('TIMEOUT_EFFECT_UNCONFIRMED', str(exc)))
        except Exception as exc:  # a ROS/backend failure: the effect of an exchange is unknown; the session ends
            self.latched = self.latched or 'BACKEND_ERROR'
            code = 'BACKEND_ERROR_EFFECT_UNCONFIRMED' if op == 'exchange' else 'BACKEND_ERROR'
            return self._reply(rid, error=(code, type(exc).__name__ + ': ' + str(exc)[:200]))

    @contextmanager
    def busy(self, label, seconds):
        """Mark the main thread busy until a deadline the monitor can check from its own thread."""
        self.busy_label, self.busy_until = label, self.clock() + seconds + OP_GRACE_S
        try:
            yield
        finally:
            self.busy_until = self.busy_label = None

    def session_expired(self):
        return self.clock() - self.started >= self.limits['max_session_s']

    def _timeout(self, args):
        value = args.get('timeout_s')
        if not _finite(value) or not 0 < value <= min(MAX_TIMEOUT_S, self.limits['watchdog_s']):
            raise ProtocolError('timeout_s must be positive and no longer than watchdog_s')
        return float(value)

    def _op_probe(self, rid, args):
        if set(args) != {'timeout_s'}:
            raise ProtocolError('probe takes timeout_s only')
        self.backend.spin(min(self._timeout(args), 0.5))
        graph = self.graph()
        b = self.backend
        return self._reply(rid, result={
            'status_type': b.topic_type(STATUS), 'odometry_type': b.topic_type(ODOMETRY),
            'mode_type': b.service_type(MODE), 'velocity_type': b.topic_type(VELOCITY),
            'mode_available': b.service_ready(MODE), 'disarm_type': b.service_type(ARM),
            'disarm_available': b.service_ready(ARM), 'velocity_subscribers': b.subscribers(VELOCITY),
            'status_publishers': graph['status_publishers'],
            'odometry_publisher_gids': [graph['odometry']] if graph['odometry'] else [],
            'status_publisher_gid': graph['status'], 'boot_id': b.boot_id()}, graph=graph)

    def _op_observe(self, rid, args):
        if set(args) != {'timeout_s', 'after_status_ns', 'after_odometry_ns'}:
            raise ProtocolError('observe takes timeout_s, after_status_ns, after_odometry_ns')
        timeout = self._timeout(args)
        after = {k: args['after_' + k + '_ns'] for k in ('status', 'odometry')}
        if any(v is not None and type(v) is not int for v in after.values()):
            raise ProtocolError('after_*_ns must be integers or null')
        deadline = self.clock() + timeout
        while True:
            samples = {k: self.backend.latest(k) for k in ('status', 'odometry')}
            if all(s is not None and (after[k] is None or s['stamp_ns'] > after[k]) for k, s in samples.items()):
                break
            if self.clock() >= deadline:
                raise TimeoutError('No new status and odometry pair within timeout')
            self.backend.spin(min(0.05, max(0.0, deadline - self.clock())))
        graph = self.graph()
        if not self._identity_ok(graph):
            self.latched = self.latched or 'PUBLISHER_CHANGED'
            return self._reply(rid, error=('PUBLISHER_CHANGED', 'Observed publisher GIDs differ from the session'), graph=graph)
        return self._reply(rid, result={'status': samples['status']['message'], 'odometry': samples['odometry']['message'],
                                        'sample_metadata': {k: {'stamp_ns': samples[k]['stamp_ns'],
                                                                 'received_monotonic_s': samples[k]['received_monotonic_s'],
                                                                 'stamp_clock': 'SIMULATED_STAMP_NS',
                                                                 'receipt_clock': 'WORKER_MONOTONIC_S',
                                                                 'clock': 'WORKER_MONOTONIC_S'} for k in samples},
                                        'status_publisher_gid': graph['status'],
                                        'odometry_publisher_gid': graph['odometry']}, graph=graph)

    def _op_exchange(self, rid, args):
        if self.mode == 'PASSIVE':
            self.latched = self.latched or 'PASSIVE_EXCHANGE_REFUSED'
            return self._reply(rid, error=('PASSIVE_SESSION', 'Passive session: no command was sent; session ends'))
        if set(args) != {'timeout_s', 'command'}:
            raise ProtocolError('exchange takes timeout_s and command')
        timeout = self._timeout(args)
        command = args['command']
        kind = validate_command(command, max_linear_mps=self.limits['max_linear_mps'],
                                max_angular_rad_s=self.limits['max_angular_rad_s'])
        stopping = is_stop(command, kind)
        graph = self.graph()
        if not self._identity_ok(graph):
            self.latched = self.latched or 'PUBLISHER_CHANGED'
        if self.latched and not stopping:
            return self._reply(rid, error=('MOTION_REFUSED', 'Session latched: ' + self.latched), graph=graph)
        if kind != 'velocity' and not stopping and self.preparation_closed:
            return self._reply(rid, error=('MOTION_REFUSED', f'PREPARATION_CLOSED ({self.preparation_closed}): GUIDED/ARM '
                                           'only once per session, before any stop or telemetry loss'), graph=graph)
        if not stopping:
            ages = {k: self.backend.telemetry_age_s(k) for k in ('status', 'odometry')}
            if any(a is None or not 0 <= a <= self.limits['telemetry_max_age_s'] for a in ages.values()):
                self.preparation_closed = self.preparation_closed or 'TELEMETRY_STALE'
                return self._reply(rid, error=('TELEMETRY_STALE', 'Worker telemetry too old for motion; nothing sent: '
                                               + json.dumps(ages)), graph=graph)
        if kind != 'velocity' and not stopping:
            self.motion_possible = True  # GUIDED/ARM requested: from here on the vehicle may move
        if kind == 'mode':
            response = self.backend.call_mode(command['payload']['mode'], timeout)
            result = {'status': response['status'], 'curr_mode': response['curr_mode']}
            if stopping and result['status'] is True and result['curr_mode'] == 4:
                self.motion_possible = False
                self.preparation_closed = self.preparation_closed or 'STOP_ACKNOWLEDGED'
            elif not stopping and (result['status'] is not True or result['curr_mode'] != 15):
                self.preparation_closed = self.preparation_closed or 'PREPARATION_REFUSED'
        elif kind == 'arm':
            result = {'result': self.backend.call_arm(command['payload']['arm'], timeout)['result']}
            if stopping and result['result'] is True:
                self.motion_possible = False
                self.preparation_closed = self.preparation_closed or 'STOP_ACKNOWLEDGED'
            elif not stopping and result['result'] is not True:
                self.preparation_closed = self.preparation_closed or 'PREPARATION_REFUSED'
        else:
            if self.backend.subscribers(VELOCITY) < 1:
                return self._reply(rid, error=('NO_SUBSCRIBER', 'cmd_vel has no subscriber; nothing published'), graph=graph)
            linear, angular = command['payload']['twist']['linear']['x'], command['payload']['twist']['angular']['z']
            with self.publish_lock:  # the monitor's zero can never be overtaken by a later non-zero
                if self.latched and not stopping:
                    return self._reply(rid, error=('MOTION_REFUSED', 'Session latched: ' + self.latched), graph=graph)
                try:
                    self.backend.publish_velocity(linear, angular)
                finally:
                    # A monitor unable to acquire this lock must not wait here.
                    # If the in-flight publish returns, put its deferred zero LAST.
                    if self.monitor_record and self.monitor_record['zero_velocity'] == 'UNCONFIRMED_PUBLISH_BUSY':
                        try:
                            self.backend.publish_velocity(0.0, 0.0)
                            self.monitor_record['zero_velocity'] = 'PUBLISHED'
                        except Exception as exc:
                            self.monitor_record['zero_velocity'] = 'FAILED: ' + type(exc).__name__
                if not stopping:
                    self.motion_possible = True
            result = {'published': True}
        return self._reply(rid, result=result, graph=graph)

    def _op_close(self, rid, args):
        if args:
            raise ProtocolError('close takes no arguments')
        self.closed = True
        return self._reply(rid, result={'closed': True})

    def _reply(self, rid, *, result=None, error=None, graph=None):
        out = {'protocol': PROTOCOL, 'session_id': self.session_id, 'request_id': rid, 'ok': error is None}
        if error is None:
            out['result'] = result
        else:
            out['error'] = {'code': error[0], 'message': error[1]}
        if graph is not None:
            out['graph'] = graph
        return out

    def _violation(self, rid, code):
        self.latched = self.latched or code
        return self._reply(rid, error=(code, 'Protocol violation; motion refused for the rest of the session'))

    # -- watchdog ----------------------------------------------------------
    def watchdog_due(self):
        return self.clock() - self.last_request > self.limits['watchdog_s']

    def monitor_tick(self):
        """From the monitor thread: zero velocity if the main thread is stuck past an operation deadline."""
        if self.mode == 'PASSIVE' or self.stop_record is not None or self.monitor_record is not None:
            return None
        if self.watchdog_due():
            return self.emergency_zero('WATCHDOG_HOST_SILENT')
        if self.session_expired():
            return self.emergency_zero('SESSION_EXPIRED')
        until, label = self.busy_until, self.busy_label
        if until is None or self.clock() <= until:
            return None
        return self.emergency_zero('MONITOR_' + str(label).upper() + '_OVERRUN')

    def emergency_zero(self, reason):
        """Topic-only stop usable from another thread: latch, then publish zero velocity once."""
        record = {'reason': reason, 'zero_velocity': 'NOT_ATTEMPTED', 'hold': 'NOT_ATTEMPTED_FROM_MONITOR',
                  'confirmation': 'NOT_CLAIMED_BY_WORKER'}
        self.monitor_record = record
        # Latch BEFORE acquiring any ROS/publication resource. A blocked publish
        # cannot silence the monitor or leave the session accepting new motion.
        self.latched = self.latched or reason
        if not self.publish_lock.acquire(blocking=False):
            record['zero_velocity'] = 'UNCONFIRMED_PUBLISH_BUSY'
            self.monitor_record = record
            return record
        try:
            try:
                self.backend.publish_velocity(0.0, 0.0)
                record['zero_velocity'] = 'PUBLISHED'
            except Exception as exc:
                record['zero_velocity'] = 'FAILED: ' + type(exc).__name__
        finally:
            self.publish_lock.release()
        self.monitor_record = record
        return record

    def safe_stop(self, reason):
        """Zero velocity then HOLD, once; a bounded look at the vehicle; never 'confirmed'."""
        if self.stop_record is not None:
            return self.stop_record
        record = {'reason': reason, 'zero_velocity': 'NOT_ATTEMPTED', 'hold': 'NOT_ATTEMPTED', 'observed': None,
                  'worker_observation': 'NOT_ATTEMPTED', 'confirmation': 'NOT_CLAIMED_BY_WORKER', 'mode': self.mode,
                  'monitor': self.monitor_record}
        self.latched, self.closed = self.latched or reason, True
        if self.mode == 'PASSIVE':
            record['control_actions'] = 'NONE_PASSIVE_SESSION'
            self.stop_record = record
            return record
        with self.publish_lock:
            if self.monitor_record and self.monitor_record['zero_velocity'] == 'PUBLISHED':
                record['zero_velocity'] = 'PUBLISHED'
                record['zero_source'] = 'MONITOR'
            else:
                try:
                    self.backend.publish_velocity(0.0, 0.0)
                    record['zero_velocity'] = 'PUBLISHED'
                except Exception as exc:
                    record['zero_velocity'] = 'FAILED: ' + type(exc).__name__
        before = self.backend.latest('status')
        try:
            response = self.backend.call_mode(4, min(2.0, self.limits['watchdog_s']))
            record['hold'] = 'ACKNOWLEDGED' if response.get('status') is True and response.get('curr_mode') == 4 else 'REJECTED'
        except Exception as exc:
            record['hold'] = 'UNCONFIRMED: ' + type(exc).__name__
        record.update(self._look_after_hold(before))
        self.stop_record = record
        return record

    def _look_after_hold(self, before):
        """Bounded wait for a status and odometry newer than the HOLD request; reported, never judged 'confirmed'."""
        after = {'status': before['stamp_ns'] if before else None}
        odometry = self.backend.latest('odometry')
        after['odometry'] = odometry['stamp_ns'] if odometry else None
        deadline = self.clock() + min(STOP_OBSERVE_S, self.limits['watchdog_s'])
        while True:
            samples = {k: self.backend.latest(k) for k in ('status', 'odometry')}
            if all(v is not None and (after[k] is None or v['stamp_ns'] > after[k]) for k, v in samples.items()):
                break
            if self.clock() >= deadline:
                return {'observed': samples['status']['message'] if samples['status'] else None,
                        'worker_observation': 'NO_NEW_TELEMETRY_AFTER_HOLD'}
            try:
                self.backend.spin(min(0.05, max(0.0, deadline - self.clock())))
            except Exception:
                return {'observed': None, 'worker_observation': 'BACKEND_FAILED_AFTER_HOLD'}
        status, twist = samples['status']['message'], samples['odometry']['message']['twist']['twist']
        linear = math.sqrt(sum(float(twist['linear'][a]) ** 2 for a in 'xyz'))
        angular = math.sqrt(sum(float(twist['angular'][a]) ** 2 for a in 'xyz'))
        stopped = linear <= self.limits['stopped_linear_mps'] and angular <= self.limits['stopped_angular_rad_s']
        label = ('HOLD_NOT_OBSERVED' if status.get('mode') != 4 else
                 'HOLD_AND_STOPPED_OBSERVED_BY_WORKER' if stopped else 'HOLD_OBSERVED_STILL_MOVING')
        return {'observed': status, 'observed_speed': {'linear_mps': linear, 'angular_rad_s': angular},
                'worker_observation': label}


class RclpyBackend:
    """Inside the container only; imports rclpy lazily. Passive: no publisher, no service client."""
    def __init__(self, passive):
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from ardupilot_msgs.msg import Status
        from ardupilot_msgs.srv import ModeSwitch, ArmMotors
        from geometry_msgs.msg import TwistStamped
        from nav_msgs.msg import Odometry
        from rosidl_runtime_py.convert import message_to_ordereddict
        self.rclpy, self.convert = rclpy, message_to_ordereddict
        rclpy.init()
        self.node = rclpy.create_node('tfg_rover_pipe_worker')
        qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)
        self._latest = {}
        def keep(kind):
            def receive(msg):
                self._latest[kind] = {'message': json.loads(json.dumps(self.convert(msg))),
                                      'stamp_ns': msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec,
                                      'received_monotonic_s': time.monotonic()}  # container clock, worker-local only
            return receive
        self.node.create_subscription(Status, STATUS, keep('status'), qos)
        self.node.create_subscription(Odometry, ODOMETRY, keep('odometry'), qos)
        self.TwistStamped, self.ModeSwitch, self.ArmMotors = TwistStamped, ModeSwitch, ArmMotors
        self.passive = passive
        if passive:
            self.mode_client = self.arm_client = self.publisher = None
        else:
            self.mode_client = self.node.create_client(ModeSwitch, MODE)
            self.arm_client = self.node.create_client(ArmMotors, ARM)
            self.publisher = self.node.create_publisher(TwistStamped, VELOCITY, qos)

    def spin(self, timeout_s):
        self.rclpy.spin_once(self.node, timeout_sec=timeout_s)

    def publishers(self, topic):
        return [{'node': i.node_name, 'namespace': i.node_namespace, 'gid': bytes(i.endpoint_gid).hex()}
                for i in self.node.get_publishers_info_by_topic(topic)]

    def subscribers(self, topic):
        if topic == VELOCITY and self.publisher is not None:
            return self.publisher.get_subscription_count()
        return self.node.count_subscribers(topic)

    def topic_type(self, topic):
        types = dict(self.node.get_topic_names_and_types()).get(topic, [])
        return types[0] if len(types) == 1 else None

    def service_type(self, name):
        types = dict(self.node.get_service_names_and_types()).get(name, [])
        return types[0] if len(types) == 1 else None

    def service_ready(self, name):
        if self.passive:  # graph presence only; no client is ever created in a passive session
            return name in dict(self.node.get_service_names_and_types())
        return (self.mode_client if name == MODE else self.arm_client).service_is_ready()

    def boot_id(self):
        return open('/proc/sys/kernel/random/boot_id').read().strip()

    def latest(self, kind):
        return self._latest.get(kind)

    def telemetry_age_s(self, kind):
        value = self._latest.get(kind)
        return None if value is None else time.monotonic() - value['received_monotonic_s']

    def _call(self, client, request, timeout_s):
        if self.passive or client is None:
            raise RuntimeError('Passive backend has no service client')
        future = client.call_async(request)
        deadline = time.monotonic() + timeout_s
        while not future.done() and time.monotonic() < deadline:
            self.rclpy.spin_until_future_complete(self.node, future, timeout_sec=min(0.05, max(0.0, deadline - time.monotonic())))
        if not future.done():
            future.cancel()
            raise TimeoutError('Service response absent; request effects unconfirmed')
        return future.result()

    def call_mode(self, mode, timeout_s):
        request = self.ModeSwitch.Request(); request.mode = mode
        response = self._call(self.mode_client, request, timeout_s)
        return {'status': bool(response.status), 'curr_mode': int(response.curr_mode)}

    def call_arm(self, arm, timeout_s):
        request = self.ArmMotors.Request(); request.arm = arm
        return {'result': bool(self._call(self.arm_client, request, timeout_s).result)}

    def publish_velocity(self, linear_x, angular_z):
        if self.passive or self.publisher is None:
            raise RuntimeError('Passive backend has no publisher')
        message = self.TwistStamped()
        message.header.stamp = self.node.get_clock().now().to_msg()
        message.header.frame_id = 'base_link'
        message.twist.linear.x, message.twist.angular.z = float(linear_x), float(angular_z)
        self.publisher.publish(message)

    def close(self):
        self.node.destroy_node()
        self.rclpy.shutdown()


class LineReader:
    """Lines straight from the fd: select() never misses a line hidden in a Python buffer."""
    def __init__(self, stream):
        self.stream, self.buffer = stream, b''
        try:
            self.fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            self.fd = None

    def pending(self):
        return b'\n' in self.buffer

    def ready(self, timeout_s):
        import select
        if self.pending() or self.fd is None:
            return True
        return bool(select.select([self.fd], [], [], timeout_s)[0])

    def readline(self):
        if self.fd is None:
            return self.stream.readline()
        while not self.pending():
            chunk = os.read(self.fd, 65536)
            if not chunk:
                line, self.buffer = self.buffer, b''
                return line.decode(errors='replace')
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line.decode(errors='replace') + '\n'


def main(stdin=sys.stdin, stdout=sys.stdout, backend_factory=RclpyBackend, clock=time.monotonic):
    reader = LineReader(stdin)

    def emit(obj):
        stdout.write(json.dumps(obj, allow_nan=False) + '\n')
        stdout.flush()
    first = reader.readline()
    try:
        hello = json.loads(first) if first else None
        if not isinstance(hello, dict) or hello.get('mode') not in MODES:
            raise ProtocolError('Hello must declare PASSIVE or OPERATIONAL')
        backend = backend_factory(hello['mode'] == 'PASSIVE')
        core = WorkerCore(backend, hello, clock=clock)
    except Exception as exc:
        emit({'protocol': PROTOCOL, 'op': 'hello', 'ok': False, 'error': {'code': 'HELLO_REJECTED', 'message': str(exc)[:240]}})
        return 2
    done = threading.Event()

    def monitor():
        while not done.wait(MONITOR_PERIOD_S):
            try:
                if core.monitor_tick() is not None:
                    print('tfg_rover_pipe_worker: monitor published zero velocity: ' + core.latched, file=sys.stderr)
            except Exception as exc:  # the monitor must never die silently
                print('tfg_rover_pipe_worker: monitor error ' + type(exc).__name__, file=sys.stderr)
    watcher = threading.Thread(target=monitor, name='tfg-rover-monitor', daemon=True)
    watcher.start()

    def stop_and_report(reason, code):
        record = core.safe_stop(reason)
        try:
            with core.busy('emit', 1.0):
                emit({'protocol': PROTOCOL, 'op': 'watchdog', 'ok': False, 'stop': record})
        except Exception:
            print('tfg_rover_pipe_worker: stop attempted, report not deliverable: ' + json.dumps(record)[:2000],
                  file=sys.stderr)
        return code
    try:
        with core.busy('emit', 1.0):
            emit({'protocol': PROTOCOL, 'op': 'hello', 'ok': True, 'session_id': core.session_id, 'mode': core.mode,
                  'boot_id': backend.boot_id(), 'graph': core.graph()})
        while True:
            backend.spin(0.0)
            if not reader.ready(0.05):
                if core.watchdog_due():
                    return stop_and_report('WATCHDOG_HOST_SILENT', 3)
                if core.session_expired():
                    return stop_and_report('SESSION_EXPIRED', 3)
                if core.monitor_record is not None:
                    return stop_and_report(core.latched, 5)
                continue
            line = reader.readline()
            if not line:
                core.safe_stop('EOF')
                print('tfg_rover_pipe_worker: EOF without close, stop attempted', file=sys.stderr)
                return 4
            response = core.handle(line)
            try:
                with core.busy('emit', 1.0):
                    emit(response)
            except (BrokenPipeError, OSError, ValueError) as exc:
                core.safe_stop('HOST_PIPE_LOST')  # the host cannot hear us any more: stop on our own
                print('tfg_rover_pipe_worker: host pipe lost (' + type(exc).__name__ + '), stop attempted', file=sys.stderr)
                return 7
            if core.latched and core.latched not in ('PUBLISHER_CHANGED', 'EFFECT_UNCONFIRMED'):
                return stop_and_report(core.latched, 5)
            if core.closed:
                if core.mode == 'OPERATIONAL' and core.motion_possible:
                    record = core.safe_stop('CLOSE_WITH_MOTION_POSSIBLE')
                    print('tfg_rover_pipe_worker: closed with motion possible, stop attempted: '
                          + json.dumps(record)[:2000], file=sys.stderr)
                return 0
    except BaseException as exc:  # cancellation is also a potentially effective interruption
        core.safe_stop('WORKER_EXCEPTION_' + type(exc).__name__)
        print('tfg_rover_pipe_worker: exception, stop attempted: ' + repr(exc)[:240], file=sys.stderr)
        return 6
    finally:
        done.set()
        try:
            backend.close()
        except Exception as exc:
            print('tfg_rover_pipe_worker: close failed ' + type(exc).__name__, file=sys.stderr)


def exit_with(code):
    """Exit with main()'s code even when the host pipe is gone (a final stdout flush would turn it into 120)."""
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == '__main__':
    exit_with(main())
