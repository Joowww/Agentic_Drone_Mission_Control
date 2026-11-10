"""Lazy native ROS 2 adapter; no ROS imports, node or control on module import.

No Docker fallback or CLI. Default independent-motion binding is UNACCREDITED.
The protected executor is disabled operationally until that binding is established.
"""
from dataclasses import asdict, dataclass
import time

from tools.rover_control import Observation, Reply, RoverControlCore, RoverControlError, number, synchronous_deadline
from tools.vehicle_execution_lock import assert_execution_authority, utc_now
from tools.execution_diagnostics import error_evidence
from tools.rover_environment_identity import RoverEnvironmentGuard

STATUS = '/ap/v3/status'
ODOMETRY = '/rover1/odometry'  # expected launch namespace; must be observed, never assumed
DISARM = '/ap/v3/arm_motors'
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
    pose_reference_frame: str | None = None
    pose_reference_sha256: str | None = None

    def check(self):
        for value in (self.environment_identity_sha256, self.active_bridge_config_sha256):
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise RoverControlError('Missing motion binding artifact hashes')
        if self.pose_reference_frame is not None:
            if (not self.pose_reference_frame or not isinstance(self.pose_reference_sha256,str)
                    or len(self.pose_reference_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.pose_reference_sha256)):
                raise RoverControlError('Missing explicit pose-frame accreditation digest')
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
        return self._observation(raw)

    def watch(self,*,timeout_s):
        assert_execution_authority('v3')
        read=getattr(self.session,'watch',self.session.observe)
        raw=read(timeout_s=timeout_s)
        self.journal({'operation':'watch','raw':raw})
        return self._observation(raw)

    def require_stop_target(self):
        assert_execution_authority('v3')
        return self.session.require_stop_target()

    def current(self):
        assert_execution_authority('v3')
        return self._observation(self.session.current())

    def observation_phase(self,phase):
        assert_execution_authority('v3')
        method=getattr(self.session,'observation_phase',None)
        if method is not None:method(phase)

    def reserve_observations(self,pairs):
        assert_execution_authority('v3')
        return self.session.reserve_observations(pairs)

    def _observation(self,raw):
        verify=getattr(self.session,'validate_observation',None)
        if verify is not None:
            result=verify(raw)
            from planning.artifact_store import fingerprint
            if result['binding_sha256']!=fingerprint(asdict(self.binding)):raise RoverControlError('Current source/body binding differs')
        # Native session returns dictionaries from typed messages + separate host receipts.
        status, odom = raw['status'], raw['odometry']
        if raw.get('odometry_publisher_gid') != self.binding.odometry_publisher_gid:
            raise RoverControlError('Observation publisher differs from accredited bridge')
        if odom['child_frame_id'] != self.binding.child_frame:
            raise RoverControlError('Odometry child frame contradicts independent-motion binding')
        from planning.artifact_store import fingerprint
        pose=odom.get('pose',{}).get('pose',{})
        pose_frame=odom.get('header',{}).get('frame_id')
        accredited=(self.binding.pose_reference_frame is not None and pose_frame==self.binding.pose_reference_frame)
        if self.binding.pose_reference_frame is not None and not accredited:
            raise RoverControlError('Pose frame differs from accredited reference')
        return Observation(
            vehicle_id='rover_01', interface='v3', vehicle_type=status['vehicle_type'],
            mode=status['mode'], armed=status['armed'], flying=status['flying'],
            external_control=status['external_control'], failsafe=tuple(status['failsafe']),
            received_monotonic_s=raw['status_received_monotonic_s'], status_source_ns=_stamp(status),
            velocity_source_ns=_stamp(odom),
            linear_mps=_vector(odom['twist']['twist']['linear']),
            angular_rad_s=_vector(odom['twist']['twist']['angular']),
            motion_source=self.binding.gz_topic, motion_frame=odom['child_frame_id'],
            motion_received_monotonic_s=raw['odometry_received_monotonic_s'],
            position_m=_vector(pose['position']) if 'position' in pose else None,
            orientation_xyzw=tuple(number(pose['orientation'][k],'orientation') for k in ('x','y','z','w')) if 'orientation' in pose else None,
            pose_frame=pose_frame, pose_reference_validated=accredited,
            odometry_publisher_gid=raw.get('odometry_publisher_gid'),
            pose_covariance=tuple(number(v,'pose covariance') for v in odom['pose']['covariance']) if 'covariance' in odom.get('pose',{}) else None,
            twist_covariance=tuple(number(v,'twist covariance') for v in odom['twist']['covariance']) if 'covariance' in odom.get('twist',{}) else None,
            status_publisher_gid=raw.get('status_publisher_gid'),
            status_provenance_sha256=raw.get('sample_provenance',{}).get('status',{}).get('sample_sha256'),
            motion_provenance_sha256=raw.get('sample_provenance',{}).get('odometry',{}).get('sample_sha256'),
            observation_transfer_monotonic_s=raw.get('sample_provenance',{}).get('odometry',{}).get('transfer'),
            observation_provenance_sha256=fingerprint(asdict(self.binding)) if accredited else None)

    def exchange(self, command, *, timeout_s):
        assert_execution_authority('v3')
        if self.capabilities is None:
            raise RoverControlError('Probe required before controls')
        _validate_command(command)
        if command.get('endpoint')==DISARM:
            (_assert_preparation_scope if command['payload']['arm'] else _assert_disarm_scope)()
        elif command.get('endpoint')==MODE and command['payload']['mode']==15:_assert_preparation_scope()
        # Journal intent DURABLY before calling the session. Exceptions may have effects.
        self.journal({'operation': 'control_intent', 'command': command,
                      'timeout_s': timeout_s, 'effects': 'UNCONFIRMED'})
        reply = self.session.exchange(command, timeout_s=timeout_s)
        self.journal({'operation': 'control_reply', 'reply': reply.__dict__})
        return reply


def _assert_preparation_scope():
    assert_execution_authority('v3')
    from tools import rover_ground_executor as ground,vehicle_execution_lock as locks
    owner=locks.restriction('v3')
    if not isinstance(owner,dict) or not owner.get('owner_id'):
        raise RoverControlError('Preparation reservation disappeared before scope validation')
    job,_,request,_=ground._checked(ground.directory(owner['owner_id']))
    kind=request.get('kind')
    session_ok=(kind=='ROVER_PULSE_V1' and job.get('session_id')==request['context']['lifecycle_id']
                or kind=='ROVER_NAVIGATE_V1' and job.get('session_id') is not None
                and job.get('session_id')==(job.get('coordination_binding') or {}).get('session_id'))
    if (not session_ok or request.get('preparation',{}).get('kind')!='GUIDED_ARM_AFTER_STATIONARY_V1'
            or job['job_state']!='PREPARING' or job['worker']!=locks.process_identity()
            or owner.get('input_sha256')!=job['input_sha256']):
        raise RoverControlError('Mode/arm requires an exact explicit PREPARING pulse or navigation job')


def _assert_disarm_scope():
    """A v3 lease alone does not authorize finalization of an older job."""
    assert_execution_authority('v3')
    from tools import rover_ground_executor as ground, vehicle_execution_lock as locks
    guard=locks.restriction('v3')
    if not isinstance(guard,dict) or not guard.get('owner_id'):
        raise RoverControlError('Disarm reservation disappeared before scope validation')
    job,_,request,_=ground._checked(ground.directory(guard['owner_id']))
    if (request.get('finalization',{}).get('kind')!='DISARM_AFTER_OBSERVED_STOP_V1'
            or job['job_state']!='FINALIZING' or job['worker']!=locks.process_identity()
            or guard.get('input_sha256')!=job['input_sha256']):
        raise RoverControlError('Disarm requires exact explicit FINALIZING job scope')


def _validate_command(command):
    if not isinstance(command, dict):
        raise RoverControlError("Typed ground command required")
    # Exact whitelist prevents arbitrary endpoints/types/fields and Copter commands.
    if command.get('kind') == 'service':
        if not isinstance(command.get('payload'), dict):
            raise RoverControlError('Typed ModeSwitch payload required')
        if command.get('endpoint')==DISARM:
            if type(command['payload'].get('arm')) is not bool or command!={'kind':'service','endpoint':DISARM,'type':'ardupilot_msgs/srv/ArmMotors','payload':{'arm':command['payload']['arm']}}:
                raise RoverControlError('Only exact typed arm/disarm is supported')
            return
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
    def __init__(self, *, identity_guard=None, cancelled=lambda:False, resource_timeout_s=None, observation_source=None):
        self.identity_guard = identity_guard
        self._bound_owner=None
        if 'source_contract' in getattr(identity_guard,'expected',{}):
            from tools import rover_ground_executor as ground
            if not ground.OPERATIONAL_ROVER_ENABLED:raise RoverControlError('Operational rover policy disabled')
            assert_execution_authority('v3')
            from tools import vehicle_execution_lock as locks
            self._bound_owner=locks.restriction('v3')['owner_id']
        self.observation_source=observation_source
        self.cancelled = cancelled
        self.resource_timeout_s=(None if resource_timeout_s is None else number(resource_timeout_s,'resource timeout',positive=True))
        self.node = self.context = None
        self._close_attempted = False
        try:
            self._initialize()
        except BaseException as exc:
            try:self.close()
            except Exception as closing:
                exc.diagnostic={'initial_diagnostic':getattr(exc,'diagnostic',None),
                    'phase':'NATIVE_INITIALIZATION','resource_close_error':{'type':type(closing).__name__,'message':str(closing)[:240]}}
            raise

    def _initialize(self):
        import rclpy
        from rclpy.context import Context
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from ardupilot_msgs.msg import Status
        from ardupilot_msgs.srv import ModeSwitch, ArmMotors
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
            def receive(msg):
                # Installed Humble executor passes only msg, not MessageInfo.
                # Graph discovery cannot attribute an individual received sample.
                self.latest[kind] = (self.convert(msg), time.monotonic(), None)
            return receive
        self.subscriptions = ([self.node.create_subscription(cls, topic, callback(kind), qos)
            for cls, topic, kind in ((Status, STATUS, 'status'), (Odometry, ODOMETRY, 'odometry'))]
            if self.observation_source is None else [])
        self.mode_type, self.velocity_type = ModeSwitch, TwistStamped
        self.disarm_type=ArmMotors
        self.client = self.node.create_client(ModeSwitch, MODE)
        self.disarm_client=self.node.create_client(ArmMotors,DISARM)
        self.publisher = self.node.create_publisher(TwistStamped, VELOCITY, qos)

    def _require_identity(self,*,stopping=False):
        guard = getattr(self, 'identity_guard', None)
        if type(guard) is not RoverEnvironmentGuard:
            raise RoverControlError('Supervised rover identity worker/current environment collector unavailable')
        request=None
        if 'source_contract' in guard.expected:
            assert_execution_authority('v3')
            from tools import rover_ground_executor as ground,vehicle_execution_lock as locks
            from tools.rover_environment_identity import digest
            lease=locks.restriction('v3')
            if lease['owner_id']!=self._bound_owner:raise RoverControlError('Transport owner changed; no borrowing')
            job,_,request,_=ground._checked(ground.directory(lease['owner_id']))
            if (request['kind']!='ROVER_PULSE_V1' or request['context']['lifecycle_id']!=guard.expected['lifecycle_id']
                    or request['context']['source_contract_sha256']!=digest(guard.expected['source_contract'])
                    or request['context']['body_review_sha256']!=guard.expected['source_contract']['body_review_sha256']):
                raise RoverControlError('Transport job/session/source scope differs')
        result=guard.require_stop_target() if stopping else guard.require_motion_source()
        if request is not None and result['target_sha256']!=request['context']['target_sha256']:
            raise RoverControlError('Transport target differs from current owner authorization')
        return result

    def require_stop_target(self):
        return self._require_identity(stopping=True)

    def validate_observation(self,raw):
        return self.identity_guard.require_observation(raw)

    def current(self):
        self._require_identity()
        if self.observation_source is None:raise RoverControlError('Current supervised source absent')
        return self.observation_source.current()

    def observation_phase(self,phase):
        self._require_identity(stopping=True)
        if self.observation_source is not None:self.observation_source.set_phase(phase)

    def reserve_observations(self,pairs):
        self._require_identity()
        if self.observation_source is None:raise RoverControlError('Supervised source absent')
        self.observation_source.reserve_observations(pairs)

    def _velocity_destination(self,proof):
        if 'source_contract' not in getattr(getattr(self,'identity_guard',None),'expected',{}):return
        contract=self.identity_guard.expected['source_contract']
        domain=self.context.get_domain_id()
        if type(domain) is not int or domain!=contract['ros_domain_id']:raise RoverControlError('Worker DDS domain differs/unknown')
        infos=self.node.get_subscriptions_info_by_topic(VELOCITY)
        expected=proof['target']['destinations'][VELOCITY]['reader_guid']+'0'*16
        if (len(infos)!=1 or bytes(infos[0].endpoint_gid).hex()!=expected or
                infos[0].topic_type!='geometry_msgs/msg/TwistStamped' or self.publisher.get_subscription_count()!=1):
            raise RoverControlError('Velocity destination absent/foreign/ambiguous')

    def _service_destination(self,endpoint,type_name,proof):
        if 'source_contract' not in getattr(getattr(self,'identity_guard',None),'expected',{}):return
        domain=self.context.get_domain_id()
        if type(domain) is not int or domain!=self.identity_guard.expected['source_contract']['ros_domain_id']:
            raise RoverControlError('Worker service DDS domain differs/unknown')
        if endpoint not in proof['target']['destinations']:raise RoverControlError('Service native destination unknown')
        servers=[]
        for name,namespace in self.node.get_node_names_and_namespaces():
            if not name or not namespace:raise RoverControlError('Service graph coverage unknown')
            for service,types in self.node.get_service_names_and_types_by_node(name,namespace):
                if service==endpoint:servers.append((name,namespace,types))
        if len(servers)!=1 or servers[0][2]!=[type_name]:raise RoverControlError('Service destination absent/foreign/ambiguous')

    def watch(self,*,timeout_s):
        self._require_identity(stopping=self.observation_source is not None)
        if self.observation_source is None:raise RoverControlError('Current per-message watch source unavailable')
        with synchronous_deadline(timeout_s):return self.observation_source.poll(timeout_s=timeout_s)

    def probe(self, *, timeout_s):
        self._require_identity()
        self._check_cancelled()
        with synchronous_deadline(timeout_s):
            return self._probe(timeout_s=timeout_s)

    def _check_cancelled(self):
        if getattr(self,'cancelled',lambda:False)():raise RoverControlError('CANCELLED')

    def _probe(self, *, timeout_s):
        # One bounded discovery spin; absent discovery blocks rather than waiting/retrying controls.
        self.rclpy.spin_once(self.node, timeout_sec=min(number(timeout_s, 'timeout', positive=True), .1))
        topics = dict(self.node.get_topic_names_and_types())
        services = dict(self.node.get_service_names_and_types())
        def single(values):
            return values[0] if len(values) == 1 else None
        infos = self.node.get_publishers_info_by_topic(ODOMETRY)
        source=self.observation_source.probe(timeout_s=timeout_s) if self.observation_source is not None else None
        if source and source['session_id']!=self.identity_guard.expected['lifecycle_id']:
            raise RoverControlError('Receiver belongs to another transport session')
        result={'session_id':self.identity_guard.expected['lifecycle_id'],
                'observation_source':source,
                'status_type': single(topics.get(STATUS, [])),
                'odometry_type': single(topics.get(ODOMETRY, [])),
                'mode_type': single(services.get(MODE, [])),
                'velocity_type': single(topics.get(VELOCITY, [])),
                'mode_available': self.client.service_is_ready(),
                'disarm_type':single(services.get(DISARM,[])),
                'disarm_available':self.disarm_client.service_is_ready(),
                'velocity_subscribers': self.publisher.get_subscription_count(),
                'status_publishers': len(self.node.get_publishers_info_by_topic(STATUS)),
                'odometry_publisher_gids': [source['odometry_sample_gid']] if source else [bytes(x.endpoint_gid).hex() for x in infos]}
        contract=self.identity_guard.expected.get('source_contract')
        if contract:
            proof=self._require_identity()
            self._velocity_destination(proof)
            for endpoint,type_name in ((MODE,'ardupilot_msgs/srv/ModeSwitch'),(DISARM,'ardupilot_msgs/srv/ArmMotors')):
                self._service_destination(endpoint,type_name,proof)
            from tools.rover_environment_identity import digest
            result.update(target_sha256=self.identity_guard._target,source_contract_sha256=digest(contract),body_review_sha256=contract['body_review_sha256'],
                envelope_sha256=self.identity_guard._verified_target_cache[1][0]['envelope_sha256'])
        return result

    def observe(self, *, timeout_s):
        self._require_identity(stopping=getattr(self,'observation_source',None) is not None)
        with synchronous_deadline(timeout_s):
            return self._observe(timeout_s=timeout_s)

    def _observe(self, *, timeout_s):
        if getattr(self,'observation_source',None) is not None:
            value=self.observation_source.observe(timeout_s=timeout_s)
            return value
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
            return {'status_publisher_gid':self.latest['status'][2],
                    'odometry_publisher_gid': self.latest['odometry'][2],
                    'sample_gid_source':'UNAVAILABLE_IN_INSTALLED_RCLPY_CALLBACK',
                    'provenance':'NATIVE_TYPED_MESSAGES_WITH_SEPARATE_HOST_RECEIPTS_NOT_SOURCE_ACCREDITATION'} | {k: self.latest[k][0] for k in stamps} | {
                k+'_received_monotonic_s': self.latest[k][1] for k in stamps}
        exc = TimeoutError('Fresh status/independent odometry unavailable within wall deadline')
        exc.diagnostic = {'operation': 'observe', 'timeout_s': timeout_s,
                          'partial_samples': {k: {'message': v[0], 'received_monotonic_s': v[1]}
                                              for k, v in self.latest.items() if v[1] >= started}}
        raise exc

    def exchange(self, command, *, timeout_s):
        assert_execution_authority('v3')
        _validate_command(command)
        # Cancellation blocks new motion; it must not itself prevent the
        # existing, still identity-gated zero/HOLD stop or read-only stop evidence.
        stopping=(command['endpoint']==MODE and command['payload']['mode']==4 or
                  command['endpoint']==VELOCITY and command['payload']['twist']['linear']['x']==0.
                  and command['payload']['twist']['angular']['z']==0.)
        proof=self._require_identity(stopping=stopping)
        if 'source_contract' in getattr(getattr(self,'identity_guard',None),'expected',{}):
            from tools import rover_ground_executor as ground,vehicle_execution_lock as locks
            job,_,_,_=ground._checked(ground.directory(self._bound_owner))
            if (job['worker']!=locks.process_identity() or job['job_state'] not in {'RUNNING','PREPARING','FINALIZING'}
                    or command['endpoint']==VELOCITY and not stopping and job['job_state']!='RUNNING'):
                raise RoverControlError('Transport control phase/worker scope differs')
            if not ground.OPERATIONAL_ROVER_ENABLED and not stopping and not (command['endpoint']==DISARM and command['payload']['arm'] is False):
                raise RoverControlError('Operational policy disabled; only owned stop/finalization allowed')
        if command['endpoint']==VELOCITY:self._velocity_destination(proof)
        else:self._service_destination(command['endpoint'],command['type'],proof)
        if command.get('endpoint')==DISARM:
            (_assert_preparation_scope if command['payload']['arm'] else _assert_disarm_scope)()
            if command['payload']['arm']:self._check_cancelled()
        elif command.get('endpoint')==MODE and command['payload']['mode']==15:
            _assert_preparation_scope();self._check_cancelled()
        elif not stopping:self._check_cancelled()
        try:
            with synchronous_deadline(timeout_s):
                return self._exchange(command,timeout_s=timeout_s)
        except TimeoutError as exc:
            if not hasattr(exc,'diagnostic'):
                exc.diagnostic={'service' if command['kind']=='service' else 'topic':command['endpoint'],
                    'type':command['type'],'request':command['payload'],'timeout_s':timeout_s,
                    'response_received':False,'effects':'UNCONFIRMED'}
            raise

    def _exchange(self, command, *, timeout_s):
        timeout = number(timeout_s, 'timeout', positive=True)
        deadline = time.monotonic() + timeout - min(0.05, timeout * 0.1)
        if command['kind'] == 'service':
            disarm=command['endpoint']==DISARM
            stopping=command['endpoint']==MODE and command['payload']['mode']==4
            request=self.disarm_type.Request() if disarm else self.mode_type.Request()
            if disarm:request.arm=command['payload']['arm']
            else:request.mode=command['payload']['mode']
            future = None
            completed = False
            try:
                future=(self.disarm_client if disarm else self.client).call_async(request)
                while not future.done() and time.monotonic()<deadline:
                    if not stopping and not (disarm and not request.arm):self._check_cancelled()
                    self.rclpy.spin_until_future_complete(self.node, future,
                        timeout_sec=min(.05,max(0.,deadline-time.monotonic())))
                if not stopping and not (disarm and not request.arm):self._check_cancelled()
                if not future.done():
                    exc = TimeoutError((('ArmMotors arm' if request.arm else 'ArmMotors disarm') if disarm else 'ModeSwitch')+' response absent; request effects unconfirmed')
                    exc.diagnostic = {'service':command['endpoint'],'type':command['type'],
                                      'request': command['payload'], 'timeout_s': timeout_s,
                                      'response_received': False, 'effects': 'UNCONFIRMED'}
                    raise exc
                response = future.result()
                completed = True
                return Reply(True,None,{'result':response.result} if disarm else
                             {'status':response.status,'curr_mode':response.curr_mode},native_api_completed=True)
            finally:
                if future is not None and not completed:
                    # No second done() race outside the protected region. Cancelling
                    # this local future never retracts an already delivered command.
                    future.cancel()
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
        if getattr(self,'_close_attempted',False):
            if self.close_errors:raise RoverControlError('ROS resource closure remains uncertain: '+','.join(self.close_errors))
            return
        self._close_attempted=True;self.close_errors=[]
        timeout=getattr(self,'resource_timeout_s',None)
        deadline=None if timeout is None else time.monotonic()+timeout
        source=getattr(self,'observation_source',None)
        if source is not None:
            try:source.close(timeout_s=number(deadline-time.monotonic(),'receiver close remaining',positive=True) if deadline else 1.)
            except Exception as exc:self.close_errors.append('receiver:'+type(exc).__name__)
        for resource,method in ((getattr(self,'node',None),'destroy_node'),(getattr(self,'context',None),'shutdown')):
            if resource is not None:
                try:
                    if deadline is None:getattr(resource,method)()
                    else:
                        with synchronous_deadline(number(deadline-time.monotonic(),'resource remaining',positive=True)):
                            getattr(resource,method)()
                except Exception as exc:self.close_errors.append(method+':'+type(exc).__name__)
        self.closed=not self.close_errors
        if self.close_errors:raise RoverControlError('ROS resource closure uncertain: '+','.join(self.close_errors))


def physical_adapter_factory(expected, read_current, binding, *, call_timeout_s, cancelled=lambda:False, observation_source_factory=None, clock=time, clock_context=None):
    """Explicit, lazy worker wiring, NOT an operational policy switch.

    No ROS import/node on factory creation. Legacy/missing current-source
    contexts reject before construction; fallback callbacks have no message GID.
    A current-source caller must supply freshly collected passive originals and
    the same owned receiver pipe, never replay a historical journal as current.
    The executor's policy, reservations and snapshots are unchanged.
    """
    timeout=number(call_timeout_s,'physical session construction timeout',positive=True)
    if not isinstance(binding,MotionBinding):raise RoverControlError('Typed motion binding required')
    binding.check()
    from copy import deepcopy
    expected=deepcopy(expected)
    def build(journal):
        guard=RoverEnvironmentGuard(expected,read_current,clock=clock,clock_context=clock_context)
        if cancelled():raise RoverControlError('CANCELLED')
        session=None;source=None
        try:
            with synchronous_deadline(timeout):
                started=clock.monotonic()
                if 'source_contract' in expected:
                    from tools import rover_ground_executor as ground
                    if not ground.OPERATIONAL_ROVER_ENABLED:raise RoverControlError('Operational rover policy disabled')
                    assert_execution_authority('v3')
                    guard.require_passive_context()  # no controls/backend before source accreditation
                    if observation_source_factory is None:raise RoverControlError('Supervised current receiver required')
                    source=observation_source_factory(journal);guard.attach_source(source)
                    source.prepare_identity(timeout_s=number(timeout-(clock.monotonic()-started),'source remaining',positive=True))
                    guard.require_motion_source()
                else:
                    guard.require_motion_source()  # legacy/default remains blocked before source construction
                    if observation_source_factory is not None:source=observation_source_factory(journal)
                session=NativeRos2Session(identity_guard=guard,cancelled=cancelled,resource_timeout_s=timeout,observation_source=source)
            return Ros2RoverAdapter(session,binding=binding,journal=journal,clock=clock)
        except BaseException as exc:
            try:
                if session is not None:session.close()
                elif source is not None:source.close(timeout_s=timeout)
            except Exception as closing:
                exc.diagnostic={'initial_diagnostic':getattr(exc,'diagnostic',None),
                    'phase':'CURRENT_SOURCE_FACTORY','resource_close_error':{'type':type(closing).__name__,'message':str(closing)[:240]}}
            raise
    return build
