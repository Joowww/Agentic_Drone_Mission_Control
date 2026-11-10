"""Host-container rover worker: protocol, identity, watchdog, executor preparation and policy gate.

Offline only: fake ROS backend, in-process loopback transport and OS pipes. No container,
ROS, SITL or vehicle. Synthetic kinematics come from tests/test_rover_navigation.py.
"""
from dataclasses import asdict
import copy
import io
import json
import math
import os
import threading

import pytest

from planning.artifact_store import fingerprint, sha256
from tools import rover_ground_executor as ground, rover_pipe_worker as w, rover_sitl_trial_policy as policy
from tools import rover_pipe_session as ps, rover_ros2_adapter as ros, vehicle_execution_lock as locks
from tools.rover_control import Reply, RoverControlCore, RoverControlError, RoverLimits
from tools.rover_target_frame import goal_from_start_offset, start_pose, verify_goal
from tests.test_rover_ground_executor import setup  # temporary project, TEST-only operational policy
from tests.test_rover_navigation import BIND, GOAL, LIMITS, SESSION, Clock, Session
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE, NOW, raw

STATUS_GID, ODOM_GID = '02' * 24, '01' * 24
LIMITS_HELLO = {'max_linear_mps': 0.5, 'max_angular_rad_s': 1.0, 'watchdog_s': 3.0, 'telemetry_max_age_s': 1.0,
                'max_session_s': 300.0, 'stopped_linear_mps': 0.03, 'stopped_angular_rad_s': 0.03}


def velocity(linear=0.1, angular=0.0, frame='base_link'):
    message = RoverControlCore.velocity_message(linear, angular)
    message['payload']['header']['frame_id'] = frame
    return message


MODE_HOLD = {'kind': 'service', 'endpoint': ros.MODE, 'type': 'ardupilot_msgs/srv/ModeSwitch', 'payload': {'mode': 4}}
MODE_GUIDED = dict(MODE_HOLD, payload={'mode': 15})
ARM = {'kind': 'service', 'endpoint': ros.DISARM, 'type': 'ardupilot_msgs/srv/ArmMotors', 'payload': {'arm': True}}


class FakeBackend:
    """Fake AP_DDS graph: status/odometry samples advance on spin(); services and publisher are recorded."""
    def __init__(self, clock):
        self.clock, self.t, self.sent, self.calls = clock, 0, [], []
        self.graph = {w.STATUS: [{'gid': STATUS_GID}], w.ODOMETRY: [{'gid': ODOM_GID}]}
        self.mode, self.armed, self.boot = 0, False, BOOT
        self.mode_response = None
        self.arm_result = True
        self.service_timeout = False
        self.frozen = False
        self.rx_at = None  # backend clock when the last new status/odometry pair arrived
        self.vel_subscribers = 1

    def spin(self, timeout_s):
        self.clock.now += max(timeout_s, 0.01)
        if not self.frozen:
            self.t += 1
            self.rx_at = self.clock.now

    def telemetry_age_s(self, kind):
        return None if self.rx_at is None else self.clock.now - self.rx_at

    def publishers(self, topic):
        return copy.deepcopy(self.graph.get(topic, []))

    def subscribers(self, topic):
        return self.vel_subscribers

    def topic_type(self, topic):
        return {w.STATUS: 'ardupilot_msgs/msg/Status', w.ODOMETRY: 'nav_msgs/msg/Odometry',
                w.VELOCITY: 'geometry_msgs/msg/TwistStamped'}[topic]

    def service_type(self, name):
        return {w.MODE: 'ardupilot_msgs/srv/ModeSwitch', w.ARM: 'ardupilot_msgs/srv/ArmMotors'}[name]

    def service_ready(self, name):
        return True

    def boot_id(self):
        return self.boot

    def latest(self, kind):
        if self.t == 0:
            return None
        stamp = {'sec': self.t, 'nanosec': 0}
        if kind == 'status':
            message = {'header': {'stamp': stamp}, 'vehicle_type': 1, 'mode': self.mode, 'armed': self.armed,
                       'flying': False, 'external_control': True, 'failsafe': []}
        else:
            zero = {'x': 0.0, 'y': 0.0, 'z': 0.0}
            message = {'header': {'stamp': stamp, 'frame_id': 'odom'}, 'child_frame_id': 'base_link',
                       'pose': {'pose': {'position': {'x': 0.0, 'y': -3.0, 'z': 0.09},
                                         'orientation': {'x': 0.0, 'y': 0.0, 'z': math.sin(0.785), 'w': math.cos(0.785)}},
                                'covariance': [0.0] * 36},
                       'twist': {'twist': {'linear': dict(zero), 'angular': dict(zero)}, 'covariance': [0.0] * 36}}
        return {'message': message, 'stamp_ns': self.t * 10**9, 'received_monotonic_s': self.clock.now}

    def call_mode(self, mode, timeout_s):
        self.calls.append(('mode', mode))
        if self.service_timeout:
            raise TimeoutError('synthetic service silence')
        if self.mode_response is not None:
            return self.mode_response
        self.mode = mode
        return {'status': True, 'curr_mode': mode}

    def call_arm(self, arm, timeout_s):
        self.calls.append(('arm', arm))
        if self.arm_result:
            self.armed = arm
        return {'result': self.arm_result}

    def publish_velocity(self, linear, angular):
        self.sent.append((linear, angular))

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now


def hello(**changes):
    value = {'protocol': w.PROTOCOL, 'op': 'hello', 'session_id': LIFECYCLE, 'mode': 'OPERATIONAL',
             'expected_gids': {'status': STATUS_GID, 'odometry': ODOM_GID}, 'limits': dict(LIMITS_HELLO)}
    value.update(changes)
    return value


@pytest.fixture
def core():
    clock = FakeClock()
    backend = FakeBackend(clock)
    backend.spin(0.0)  # one fresh status/odometry pair: the worker refuses motion on no or stale telemetry
    return w.WorkerCore(backend, hello(), clock=clock.monotonic), backend, clock


def req(op, args=None, rid=None, session=LIFECYCLE):
    return json.dumps({'protocol': w.PROTOCOL, 'session_id': session, 'request_id': rid or os.urandom(8).hex(),
                       'op': op, 'args': args if args is not None else {}})


# ---------------------------------------------------------------- worker core --
@pytest.mark.parametrize('bad', [{'protocol': 'other'}, {'op': 'probe'}, {'session_id': ''},
                                 {'expected_gids': {'status': STATUS_GID}}, {'limits': {'max_linear_mps': 0.5}}])
def test_worker_rejects_an_incomplete_hello(bad):
    clock = FakeClock()
    with pytest.raises(w.ProtocolError):
        w.WorkerCore(FakeBackend(clock), hello(**bad), clock=clock.monotonic)


def test_worker_probe_observe_and_allowed_exchange(core):
    c, b, _ = core
    probe = c.handle(req('probe', {'timeout_s': 1.0}))
    assert probe['ok'] and probe['result']['odometry_publisher_gids'] == [ODOM_GID] and probe['result']['status_publishers'] == 1
    first = c.handle(req('observe', {'timeout_s': 1.0, 'after_status_ns': None, 'after_odometry_ns': None}))
    assert first['ok'] and first['result']['odometry_publisher_gid'] == ODOM_GID
    stamp = first['result']['status']['header']['stamp']['sec'] * 10**9
    second = c.handle(req('observe', {'timeout_s': 1.0, 'after_status_ns': stamp, 'after_odometry_ns': stamp}))
    assert second['result']['status']['header']['stamp']['sec'] * 10**9 > stamp
    assert c.handle(req('exchange', {'timeout_s': 1.0, 'command': velocity(0.2)}))['ok'] and b.sent == [(0.2, 0.0)]
    assert c.handle(req('exchange', {'timeout_s': 1.0, 'command': MODE_GUIDED}))['result'] == {'status': True, 'curr_mode': 15}


@pytest.mark.parametrize('command', [dict(MODE_HOLD, payload={'mode': 9}), velocity(0.2, frame='map'), velocity(0.9),
                                     velocity(0.1, 3.0), {'kind': 'service', 'endpoint': '/ap/v3/experimental/takeoff'},
                                     {'kind': 'topic', 'endpoint': '/ap/v3/cmd_gps_pose'}, 'not-an-object'])
def test_worker_refuses_unknown_or_unauthorized_commands_without_side_effects(core, command):
    c, b, _ = core
    reply = c.handle(req('exchange', {'timeout_s': 1.0, 'command': command}))
    assert reply['ok'] is False and reply['error']['code'] == 'INVALID_ARGUMENTS' and b.sent == [] and b.calls == []


@pytest.mark.parametrize('line,code', [('{not json', 'MALFORMED_JSON'), (json.dumps({'protocol': 'x'}), 'ENVELOPE_INVALID'),
                                       (req('launch_missiles'), 'ENVELOPE_INVALID'), (req('probe', session='other'), 'ENVELOPE_INVALID'),
                                       ('x' * (w.MAX_LINE_BYTES + 1), 'LINE_TOO_LARGE')])
def test_worker_protocol_violations_latch_motion_off(core, line, code):
    c, b, _ = core
    assert c.handle(line)['error']['code'] == code and c.latched == code
    refused = c.handle(req('exchange', {'timeout_s': 1.0, 'command': velocity(0.1)}))
    assert refused['error']['code'] == 'MOTION_REFUSED' and b.sent == []
    assert c.handle(req('exchange', {'timeout_s': 1.0, 'command': velocity(0.0)}))['ok']  # stop still allowed


def test_worker_request_ids_are_single_use(core):
    c, b, _ = core
    line = req('exchange', {'timeout_s': 1.0, 'command': velocity(0.1)}, rid='same')
    assert c.handle(line)['ok']
    again = c.handle(line)
    assert again['error']['code'] == 'DUPLICATE_REQUEST_ID' and b.sent == [(0.1, 0.0)]


@pytest.mark.parametrize('change', ['gid', 'duplicate', 'absent'])
def test_worker_publisher_change_refuses_motion_but_allows_stop(core, change):
    c, b, _ = core
    if change == 'gid': b.graph[w.ODOMETRY] = [{'gid': '09' * 24}]
    elif change == 'duplicate': b.graph[w.STATUS] = [{'gid': STATUS_GID}, {'gid': '08' * 24}]
    else: b.graph[w.STATUS] = []
    observed = c.handle(req('observe', {'timeout_s': 1.0, 'after_status_ns': None, 'after_odometry_ns': None}))
    assert observed['error']['code'] == 'PUBLISHER_CHANGED'
    assert c.handle(req('exchange', {'timeout_s': 1.0, 'command': velocity(0.1)}))['error']['code'] == 'MOTION_REFUSED'
    assert c.handle(req('exchange', {'timeout_s': 1.0, 'command': MODE_HOLD}))['ok'] and b.calls == [('mode', 4)]


def test_worker_service_silence_is_effects_unconfirmed(core):
    c, b, _ = core
    b.service_timeout = True
    reply = c.handle(req('exchange', {'timeout_s': 1.0, 'command': MODE_GUIDED}))
    assert reply['error']['code'] == 'TIMEOUT_EFFECT_UNCONFIRMED' and b.calls == [('mode', 15)]


def test_worker_observe_timeout_without_fresh_samples(core):
    c, b, _ = core
    b.frozen = True
    current = b.t * 10**9  # nothing newer than the pair already seen will arrive
    reply = c.handle(req('observe', {'timeout_s': 0.2, 'after_status_ns': current, 'after_odometry_ns': current}))
    assert reply['error']['code'] == 'TIMEOUT_EFFECT_UNCONFIRMED'


def test_watchdog_and_safe_stop_never_claim_confirmation(core):
    c, b, clock = core
    clock.now += LIMITS_HELLO['watchdog_s'] + 0.1
    assert c.watchdog_due()
    b.t = 5
    record = c.safe_stop('WATCHDOG_HOST_SILENT')
    assert record['zero_velocity'] == 'PUBLISHED' and record['hold'] == 'ACKNOWLEDGED'
    assert record['confirmation'] == 'NOT_CLAIMED_BY_WORKER' and b.sent == [(0.0, 0.0)] and b.calls == [('mode', 4)]
    assert c.safe_stop('again') is record and len(b.sent) == 1  # once
    assert c.handle(req('exchange', {'timeout_s': 1.0, 'command': velocity(0.1)}))['error']['code'] == 'CLOSED'


def test_worker_main_eof_stops_and_exits_nonzero():
    clock = FakeClock()
    backend = FakeBackend(clock)
    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, 'w') as writer:
        writer.write(json.dumps(hello()) + '\n' + req('exchange', {'timeout_s': 1.0, 'command': velocity(0.1)}) + '\n')
    out = io.StringIO()
    with os.fdopen(read_fd) as reader:
        code = w.main(stdin=reader, stdout=out, backend_factory=lambda passive: backend)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert code == 4 and lines[0]['op'] == 'hello' and lines[0]['ok'] and lines[1]['ok']
    assert backend.sent == [(0.1, 0.0), (0.0, 0.0)] and ('mode', 4) in backend.calls


def test_worker_main_watchdog_on_host_silence():
    import time
    backend = FakeBackend(FakeClock())
    read_fd, write_fd = os.pipe()
    writer = os.fdopen(write_fd, 'w')
    writer.write(json.dumps(hello(limits=dict(LIMITS_HELLO, watchdog_s=0.2))) + '\n')
    writer.flush()
    out = io.StringIO()
    with os.fdopen(read_fd) as reader:
        code = w.main(stdin=reader, stdout=out, backend_factory=lambda passive: backend, clock=time.monotonic)
    writer.close()
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert code == 3 and lines[-1]['op'] == 'watchdog' and lines[-1]['stop']['reason'] == 'WATCHDOG_HOST_SILENT'
    assert backend.sent == [(0.0, 0.0)]


def test_worker_main_rejects_bad_hello_without_backend_use():
    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, 'w') as writer:
        writer.write(json.dumps(hello(protocol='other')) + '\n')
    out = io.StringIO()
    with os.fdopen(read_fd) as reader:
        assert w.main(stdin=reader, stdout=out, backend_factory=lambda passive: FakeBackend(FakeClock())) == 2
    assert json.loads(out.getvalue())['error']['code'] == 'HELLO_REJECTED'


# ------------------------------------------------------------- host session --
class Loopback:
    """In-process transport to a real WorkerCore, with failure injection."""
    def __init__(self, backend, clock, *, fault=None):
        self.backend, self.clock, self.fault, self.core = backend, clock, fault, None
        self.replies, self.sent, self.closed = [], [], False

    def send(self, obj):
        self.sent.append(obj)
        if self.fault == 'eof_on_send' and obj.get('op') != 'hello':
            raise ps.TransportClosed('worker died')
        if obj.get('op') == 'hello':
            self.core = w.WorkerCore(self.backend, obj, clock=self.clock.monotonic)
            self.replies.append({'protocol': w.PROTOCOL, 'op': 'hello', 'ok': True, 'session_id': self.core.session_id,
                                 'mode': self.core.mode, 'boot_id': self.backend.boot_id(), 'graph': self.core.graph()})
            return
        reply = self.core.handle(json.dumps(obj))
        if self.fault == 'drop' and obj['op'] == 'exchange':
            return
        if self.fault == 'out_of_order' and obj['op'] == 'observe':
            reply = dict(reply, request_id='someone-else')
        self.replies.append(reply)

    def receive(self, timeout_s):
        if self.fault == 'eof_on_receive' and len(self.sent) > 1:
            raise ps.TransportClosed('EOF before a complete reply')
        if not self.replies:
            raise TimeoutError('no reply')
        return self.replies.pop(0)

    def close(self, timeout_s):
        self.closed = True
        return 0


def evidence():
    from tools import rover_motion_binding as mb
    return mb.assess(raw(), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                     now_wall_ns=NOW + 10**9)


def session(fault=None, *, motion_allowed=True, backend=None, **changes):
    clock = FakeClock()
    backend = backend or FakeBackend(clock)
    backend.clock = clock
    binding, ev = evidence()
    kwargs = dict(lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT, binding_evidence=ev,
                  limits=LIMITS_HELLO, clock=clock, fence=lambda e: None, motion_allowed=lambda: motion_allowed,
                  authority=lambda: None)
    kwargs.update(changes)
    transport = Loopback(backend, clock, fault=fault)
    return ps.PipeRos2Session(transport, **kwargs), transport, backend, clock


def test_session_opens_and_serves_the_adapter_contract(monkeypatch):
    monkeypatch.setattr(ros, 'assert_execution_authority', lambda v: None)  # transport test only
    s, t, b, clock = session()
    adapter = ros.Ros2RoverAdapter(s, binding=s.binding, clock=clock)
    caps = adapter.probe(timeout_s=1.0)
    assert caps['session_id'] == LIFECYCLE and caps['odometry_publisher_gids'] == [ODOM_GID]
    obs = adapter.observe(timeout_s=1.0)
    assert obs.pose_reference_validated and obs.observation_provenance_sha256 == fingerprint(asdict(s.binding))
    assert obs.status_publisher_gid == STATUS_GID and obs.odometry_publisher_gid == ODOM_GID
    assert obs.received_monotonic_s == clock.now and len(obs.pose_covariance) == 36  # host clock at receipt
    reply = adapter.exchange(velocity(0.1), timeout_s=1.0)
    assert reply.sent is True and b.sent == [(0.1, 0.0)]


@pytest.mark.parametrize('bad', ['container', 'lifecycle', 'boot', 'altered', 'stale_status'])
def test_session_refuses_evidence_of_another_session_before_any_hello(bad):
    _, ev = evidence()
    kwargs = {}
    if bad == 'container':
        execution = copy.deepcopy(EXECUTION); execution['persistent_identity']['container_id'] = 'd' * 64
        kwargs['environment_execution'] = execution
    elif bad == 'lifecycle': kwargs['lifecycle_id'] = '00000000-0000-4000-8000-000000000000'
    elif bad == 'boot': kwargs['host_boot_id'] = 'other'
    elif bad == 'altered':
        ev = copy.deepcopy(ev); ev['samples'][0]['position'][0] = 5.0; kwargs['binding_evidence'] = ev
    else:
        ev = copy.deepcopy(ev); ev['status'] = 'EXPIRED'; kwargs['binding_evidence'] = ev
    with pytest.raises(RoverControlError):
        session(**kwargs)


@pytest.mark.parametrize('bad', ['worker_boot', 'worker_gid', 'duplicate_publisher'])
def test_session_refuses_a_worker_with_other_identity(bad):
    clock = FakeClock()
    backend = FakeBackend(clock)
    if bad == 'worker_boot': backend.boot = 'other-boot'
    elif bad == 'worker_gid': backend.graph[w.ODOMETRY] = [{'gid': '09' * 24}]
    else: backend.graph[w.STATUS] = [{'gid': STATUS_GID}, {'gid': '08' * 24}]
    with pytest.raises(RoverControlError):
        session(backend=backend)


def test_publisher_change_mid_session_breaks_it_without_replay():
    s, t, b, _ = session()
    s.observe(timeout_s=1.0)
    b.graph[w.ODOMETRY] = [{'gid': '09' * 24}]
    with pytest.raises(RoverControlError, match='changed'):
        s.observe(timeout_s=1.0)
    sends = len(t.sent)
    with pytest.raises(RoverControlError, match='unusable'):
        s.exchange(velocity(0.0), timeout_s=1.0)
    assert len(t.sent) == sends


@pytest.mark.parametrize('fault', ['drop', 'eof_on_send', 'eof_on_receive'])
def test_lost_or_broken_exchange_is_effects_unconfirmed_and_never_resent(fault):
    s, t, b, _ = session(fault)
    with pytest.raises(TimeoutError) as caught:
        s.exchange(MODE_GUIDED, timeout_s=0.5)
    assert caught.value.diagnostic['effects'] == 'UNCONFIRMED' and s.broken
    with pytest.raises(RoverControlError):
        s.exchange(MODE_HOLD, timeout_s=0.5)
    assert sum(1 for m in t.sent if m.get('op') == 'exchange') <= 1


def test_out_of_order_reply_breaks_the_session():
    s, *_ = session('out_of_order')
    with pytest.raises(RoverControlError, match='not correlated'):
        s.observe(timeout_s=1.0)
    with pytest.raises(RoverControlError):
        s.observe(timeout_s=1.0)


@pytest.mark.parametrize('command', [dict(MODE_HOLD, payload={'mode': 9}), velocity(0.2, frame='map'),
                                     {'kind': 'topic', 'endpoint': '/ap/v3/cmd_gps_pose'}])
def test_session_validates_before_anything_is_sent(command):
    s, t, b, _ = session()
    with pytest.raises(RoverControlError):
        s.exchange(command, timeout_s=1.0)
    assert not any(m.get('op') == 'exchange' for m in t.sent) and b.sent == []


def test_motion_policy_gates_non_stop_commands_only():
    s, t, b, _ = session(motion_allowed=False)
    with pytest.raises(RoverControlError, match='Motion policy'):
        s.exchange(velocity(0.1), timeout_s=1.0)
    assert s.exchange(velocity(0.0), timeout_s=1.0).sent and s.exchange(MODE_HOLD, timeout_s=1.0).payload['curr_mode'] == 4
    assert b.sent == [(0.0, 0.0)]


def test_close_is_idempotent_and_uncertain_closure_is_reported():
    s, t, *_ = session()
    s.close(); s.close()
    assert t.closed
    s2, t2, *_ = session('eof_on_receive')
    with pytest.raises(Exception):
        s2.observe(timeout_s=1.0)
    with pytest.raises(RoverControlError, match='closure uncertain'):
        s2.close()


def test_stop_confirmed_versus_uncertain_through_the_session(monkeypatch):
    monkeypatch.setattr(ros, 'assert_execution_authority', lambda v: None)
    limits = RoverLimits(.4, 1., 30., 1., 3., .5, .03, .03)
    s, t, b, clock = session()
    b.mode, b.armed = 15, True
    core = RoverControlCore(limits, adapter=ros.Ros2RoverAdapter(s, binding=s.binding, clock=clock), clock=clock)
    stopped = core.stop(force_zero=True)
    assert stopped['status'] == 'STATIONARY_OBSERVED' and b.mode == 4
    s2, t2, b2, clock2 = session('drop')
    b2.mode, b2.armed = 15, True
    core2 = RoverControlCore(limits, adapter=ros.Ros2RoverAdapter(s2, binding=s2.binding, clock=clock2), clock=clock2)
    uncertain = core2.stop(force_zero=True)
    assert uncertain['status'] == 'UNCONFIRMED' and uncertain['stationary_observed'] is False


# ------------------------------------------------- frame / goal correspondence --
def test_goal_frame_reference_is_the_binding_pose_reference_and_recomputes():
    binding, ev = evidence()
    goal = goal_from_start_offset(start_pose(ev), forward_m=1.0, left_m=0.0, max_distance_m=2.0)
    assert goal['frame_transform']['sha256'] == binding.pose_reference_sha256
    assert goal['frame_transform']['goal_sha256'] == fingerprint(goal['target_in_rover_frame']) != goal['frame_transform']['sha256']
    assert verify_goal(goal, ev, binding)['pose_reference_sha256'] == binding.pose_reference_sha256


@pytest.mark.parametrize('bad', ['reference', 'target', 'start', 'binding', 'method'])
def test_inconsistent_goal_references_are_rejected(bad):
    binding, ev = evidence()
    goal = goal_from_start_offset(start_pose(ev), forward_m=1.0, left_m=0.0, max_distance_m=2.0)
    if bad == 'reference': goal['frame_transform']['sha256'] = '0' * 64
    elif bad == 'target': goal['target_in_rover_frame']['x_m'] += 0.5
    elif bad == 'start': goal['start']['y_m'] += 1.0
    elif bad == 'binding': binding = ros.MotionBinding(**dict(asdict(binding), pose_reference_sha256='1' * 64))
    else: goal['frame_transform']['method'] = 'GNSS_TO_ODOM'
    with pytest.raises(RoverControlError):
        verify_goal(goal, ev, binding)


# --------------------------------------------- executor: preparation, readiness, policy --
class PreparingSession(Session):
    """Synthetic kinematics starting disarmed in mode 0; accepts GUIDED and ARM like ArduRover."""
    def __init__(self, clock, pose, *, guided_ok=True, arm_ok=True):
        super().__init__(clock, pose)
        self.mode, self.armed, self.guided_ok, self.arm_ok = 0, False, guided_ok, arm_ok

    def current(self):
        return self.observe()

    def observe(self, **kw):
        value = super().observe(**kw)
        value['status_publisher_gid'] = '5' * 48
        return value

    def exchange(self, command, **kw):
        if command['endpoint'] == ros.DISARM and command['payload']['arm'] is True:
            locks.assert_execution_authority('v3'); self.commands.append(command)
            if self.arm_ok:
                self.armed = True
            return Reply(True, 0, {'result': self.arm_ok})
        if command['endpoint'] == ros.MODE and command['payload']['mode'] == 15 and not self.guided_ok:
            locks.assert_execution_authority('v3'); self.commands.append(command)
            return Reply(True, 0, {'status': False, 'curr_mode': self.mode})
        return super().exchange(command, **kw)


PREPARATION = {'kind': ground.PREPARATION_KIND, 'timeout_s': 20.0}
PREP_SAFETY = {'binding_sha256': fingerprint(asdict(BIND)), 'pose_frame': 'odom', 'max_slope_rad': 0.3}


def navigate(setup, *, profile='rover_only', readiness=None, guided_ok=True, arm_ok=True, frame_sha=None,
             preparation=True, start=True, extra=None):
    path = setup[0]
    clock = Clock()
    s = PreparingSession(clock, (0., 0., 0.), guided_ok=guided_ok, arm_ok=arm_ok)
    request = {'kind': 'ROVER_NAVIGATE_V1', 'limits': asdict(LIMITS), 'goal': asdict(GOAL), 'profile': profile,
               'finalization': {'kind': 'DISARM_AFTER_OBSERVED_STOP_V1', 'timeout_s': 6.0}}
    if preparation:
        request.update(preparation=dict(PREPARATION), preparation_safety=dict(PREP_SAFETY))
    request.update(extra or {})
    auth = {'mission_sha256': sha256(path.read_bytes()), 'request_fingerprint': fingerprint(request), 'statement': 'SYNTHETIC'}
    candidate = {'vehicle_id': 'rover_01', 'rover_mission': {'value': {'sha256': auth['mission_sha256']}},
                 'target_in_rover_frame': {'value': {'x_m': GOAL.x_m, 'y_m': GOAL.y_m, 'frame': 'odom'}},
                 'frame_transform': {'value': {'status': 'VERIFIED', 'sha256': frame_sha or BIND.pose_reference_sha256, 'to_frame': 'odom'}},
                 'finalization_policy': {'value': request['finalization']}}
    if preparation:
        candidate['preparation_policy'] = {'value': request['preparation']}
    declared = {'source': 'OPERATOR_DECLARED', 'statement': 'SYNTHETIC', 'candidate_sha256': fingerprint(candidate),
                'mission_sha256': auth['mission_sha256'], 'session_id': SESSION}
    admitted = ground.admit_ground_trial(path, 'nav-prep-' + os.urandom(4).hex(), request, auth,
                                         coordination_context={'candidate': candidate, 'authorization': declared})
    if not start or admitted.get('status') != 'ADMITTED':
        return admitted, s, request
    q = ground.query_ground_trial(admitted['run_id'])
    start_auth = {'run_id': admitted['run_id'], 'input_sha256': q['input_sha256'],
                  **{k: q['coordination_binding'][k] for k in ('candidate_sha256', 'session_id', 'authorization_sha256')},
                  'statement': 'SYNTHETIC start'}

    class Probe(dict):
        pass
    factory = lambda journal: ros.Ros2RoverAdapter(s, binding=BIND, clock=clock, journal=journal)
    original_probe = s.probe
    s.probe = lambda **kw: dict(original_probe(**kw), session_id=SESSION)
    report = ground.start_ground_trial(admitted['run_id'], start_auth, adapter_factory=factory,
                                       readiness=readiness or (lambda **kw: {'ready': True, 'profile': kw['profile']}))
    return report, s, request


def test_navigation_preparation_guided_then_arm_then_goal(setup):
    report, s, _ = navigate(setup)
    prep = report['preparation']
    assert prep['status'] == 'GUIDED_ARMED_STATIONARY_OBSERVED' and prep['mode_attempted'] and prep['arm_attempted']
    assert [c['payload'] for c in s.commands[:2]] == [{'mode': 15}, {'arm': True}]
    assert report['result']['goal_outcome'] == 'GOAL_REACHED' and report['status'] == 'GOAL_REACHED_CLOSURE_OBSERVED'
    assert report['readiness']['profile'] == 'rover_only'


@pytest.mark.parametrize('rejected', ['guided', 'arm'])
def test_rejected_guided_or_arm_aborts_before_any_velocity(setup, rejected):
    report, s, _ = navigate(setup, guided_ok=rejected != 'guided', arm_ok=rejected != 'arm')
    assert report['preparation']['status'] != 'GUIDED_ARMED_STATIONARY_OBSERVED'
    assert report['result']['motion_command_attempted'] is False
    assert not any(c['endpoint'] == ros.VELOCITY and c['payload']['twist']['linear']['x'] for c in s.commands)


def test_readiness_without_an_armable_rover_blocks_before_preparation(setup):
    not_armable = lambda **kw: {'ready': True, 'vehicles': [{'vehicle_id': 'rover_01', 'interface': 'v3',
                                                            'status_last_observed': 'PASS', 'prearm_last_observed': 'FAIL'}]}
    report, s, _ = navigate(setup, readiness=not_armable)
    assert report['status'] == 'UNCONFIRMED' and 'armable rover_01/v3' in json.dumps(report['error_evidence'])
    assert s.commands == []


def test_pose_reference_mismatch_blocks_before_preparation(setup):
    report, s, _ = navigate(setup, frame_sha='7' * 64)
    assert report['status'] == 'UNCONFIRMED' and s.commands == []


@pytest.mark.parametrize('profile', ['two_drones', 'drone_only', None])
def test_profiles_outside_the_rover_allowlist_are_refused(setup, profile):
    with pytest.raises((ValueError, KeyError)):
        navigate(setup, profile=profile, start=False)


@pytest.mark.parametrize('bad', [{'preparation': {'kind': 'OTHER', 'timeout_s': 1.0}},
                                 {'preparation_safety': dict(PREP_SAFETY, pose_frame='map')},
                                 {'preparation_safety': dict(PREP_SAFETY, binding_sha256='x')}])
def test_preparation_schema_is_exact(setup, bad):
    with pytest.raises((ValueError, RoverControlError)):
        navigate(setup, extra=bad, start=False)


def test_preparation_is_never_implicit_for_navigation_without_it(setup):
    report, s, _ = navigate(setup, preparation=False)
    assert 'preparation' not in report and report['result']['goal_outcome'] == 'NOT_ATTEMPTED'
    assert not any(c['payload'] in ({'mode': 15}, {'arm': True}) for c in s.commands)


def test_second_start_after_completion_is_refused(setup):
    report, s, _ = navigate(setup)
    run_id = report['run_id']
    q = ground.query_ground_trial(run_id)
    start_auth = {'run_id': run_id, 'input_sha256': q['input_sha256'],
                  **{k: q['coordination_binding'][k] for k in ('candidate_sha256', 'session_id', 'authorization_sha256')},
                  'statement': 'SYNTHETIC second start'}
    again = ground.start_ground_trial(run_id, start_auth, adapter_factory=lambda j: pytest.fail('no new session'))
    assert again['status'] == 'BLOCKED'


def sitl_extra(setup, *, scope_changes=None):
    path = setup[0]
    _, ev = evidence()
    scope = policy.trial_scope(environment_execution=EXECUTION, host_boot_id=BOOT, lifecycle_id=LIFECYCLE,
                               profile='rover_only', mission_sha256=sha256(path.read_bytes()),
                               goal_sha256=fingerprint(asdict(GOAL)), binding_evidence_sha256=ev['evidence_sha256'])
    scope.update(scope_changes or {})
    return {'sitl_trial': {'scope': scope, 'authorization': policy.expected_authorization(scope), 'binding_evidence': ev}}


def facts_for(scope, evidence):
    """Fixed current facts of the synthetic session; they never come from the request's scope."""
    return {'environment_execution': EXECUTION, 'host_boot_id': BOOT, 'lifecycle_id': LIFECYCLE,
            'profile': 'rover_only', 'binding_evidence_sha256': evidence['evidence_sha256'], 'trials_consumed': 0}


def test_sitl_gate_is_closed_by_default_and_never_bypasses_operational_policy(setup, monkeypatch):
    monkeypatch.setattr(ground, 'OPERATIONAL_ROVER_ENABLED', False)
    admitted, s, _ = navigate(setup, extra=sitl_extra(setup), start=False)
    assert admitted['status'] == 'BLOCKED' and 'SITL_TRIAL_POLICY_DISABLED' in admitted['policy_gate']['reasons']
    assert not list(ground.RUN_ROOT.glob('*/job.json')) if ground.RUN_ROOT.exists() else True
    assert ground.start_ground_trial('00000000-0000-4000-8000-000000000000', {}, adapter_factory=lambda j: None)['status'] == 'BLOCKED'
    assert ground.motion_policy_allows_current_owner() is False


def test_sitl_gate_when_enabled_still_binds_mission_goal_profile_and_facts(setup, monkeypatch):
    monkeypatch.setattr(ground, 'OPERATIONAL_ROVER_ENABLED', False)
    monkeypatch.setattr(policy, 'SITL_TRIAL_POLICY_ENABLED', True)  # TEST ONLY
    monkeypatch.setattr(ground, 'sitl_current_facts', facts_for)
    path = setup[0]
    # Positive fixture uses the complete v2 control contract; legacy minimal
    # declarations are deliberately rejected by the executor after this review.
    from tests.test_rover_first_navigation import trial
    request = copy.deepcopy(trial()['request'])
    request['sitl_trial']['scope']['mission_sha256'] = sha256(path.read_bytes())
    request['sitl_trial']['authorization'] = policy.expected_authorization(request['sitl_trial']['scope'])
    assert ground.policy_gate(request, sha256(path.read_bytes()))['status'] == 'AUTHORIZED'
    for changes in ({'goal_sha256': '0' * 64}, {'profile': 'two_drones_rover'}, {'lifecycle_id': 'other'}):
        bad = dict(request, **sitl_extra(setup, scope_changes=changes))
        assert ground.policy_gate(bad, sha256(path.read_bytes()))['status'] == 'BLOCKED'
    assert ground.policy_gate(dict(request, sitl_trial=dict(request['sitl_trial'], authorization='yes')),
                              sha256(path.read_bytes()))['status'] == 'BLOCKED'
    no_prep = {k: v for k, v in request.items() if k != 'preparation'}
    assert ground.policy_gate(no_prep, sha256(path.read_bytes()))['status'] == 'BLOCKED'


def test_defaults_remain_disabled():
    assert ground.OPERATIONAL_ROVER_ENABLED is False and policy.SITL_TRIAL_POLICY_ENABLED is False


# ----------------------------------------------------------------- passive mode --
class CountingBackend(FakeBackend):
    """Counts every ROS control action; a passive session must leave all counters at zero."""
    def __init__(self, clock):
        super().__init__(clock)
        self.control_actions = 0

    def call_mode(self, mode, timeout_s):
        self.control_actions += 1
        return super().call_mode(mode, timeout_s)

    def call_arm(self, arm, timeout_s):
        self.control_actions += 1
        return super().call_arm(arm, timeout_s)

    def publish_velocity(self, linear, angular):
        self.control_actions += 1
        return super().publish_velocity(linear, angular)


def passive_core():
    clock = FakeClock()
    backend = CountingBackend(clock)
    return w.WorkerCore(backend, hello(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0}), clock=clock.monotonic), backend, clock


def test_passive_probe_and_observe_need_no_control(core):
    c, b, _ = passive_core()
    assert c.handle(req('probe', {'timeout_s': 1.0}))['ok']
    assert c.handle(req('observe', {'timeout_s': 1.0, 'after_status_ns': None, 'after_odometry_ns': None}))['ok']
    assert c.handle(req('close'))['result'] == {'closed': True}
    assert b.control_actions == 0 and b.sent == [] and b.calls == []


@pytest.mark.parametrize('command', [MODE_HOLD, MODE_GUIDED, ARM, dict(ARM, payload={'arm': False}), velocity(0.0), velocity(0.2)])
def test_passive_session_refuses_every_command_including_stops(command):
    c, b, _ = passive_core()
    reply = c.handle(req('exchange', {'timeout_s': 1.0, 'command': command}))
    assert reply['error']['code'] == 'PASSIVE_SESSION' and c.latched == 'PASSIVE_EXCHANGE_REFUSED'
    assert b.control_actions == 0


@pytest.mark.parametrize('trigger', ['watchdog', 'violation', 'publisher_change'])
def test_passive_safe_stop_and_violations_perform_no_ros_control(trigger):
    c, b, clock = passive_core()
    if trigger == 'watchdog':
        clock.now += 10
        assert c.watchdog_due()
        record = c.safe_stop('WATCHDOG_HOST_SILENT')
    elif trigger == 'violation':
        c.handle('{broken')
        record = c.safe_stop(c.latched)
    else:
        b.graph[w.ODOMETRY] = [{'gid': '09' * 24}]
        c.handle(req('observe', {'timeout_s': 1.0, 'after_status_ns': None, 'after_odometry_ns': None}))
        record = c.safe_stop(c.latched)
    assert record['control_actions'] == 'NONE_PASSIVE_SESSION' and record['zero_velocity'] == 'NOT_ATTEMPTED'
    assert record['hold'] == 'NOT_ATTEMPTED' and b.control_actions == 0


def run_main(lines, backend, **kwargs):
    import time
    read_fd, write_fd = os.pipe()
    with os.fdopen(write_fd, 'w') as writer:
        writer.write(''.join(l + '\n' for l in lines))
    out = io.StringIO()
    with os.fdopen(read_fd) as reader:
        code = w.main(stdin=reader, stdout=out, backend_factory=lambda passive: (setattr(backend, 'passive', passive) or backend),
                      clock=kwargs.get('clock', time.monotonic))
    return code, [json.loads(l) for l in out.getvalue().splitlines()]


PASSIVE_HELLO = json.dumps(hello(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0}))


@pytest.mark.parametrize('tail', [['close'], [], ['broken'], ['exchange']])
def test_passive_main_close_eof_violation_or_exchange_emit_no_ros_control(tail):
    backend = CountingBackend(FakeClock())
    lines = [PASSIVE_HELLO, req('probe', {'timeout_s': 1.0})]
    lines += {'close': [req('close')], 'broken': ['{broken'],
              'exchange': [req('exchange', {'timeout_s': 1.0, 'command': velocity(0.0)})]}.get(tail[0], []) if tail else []
    code, replies = run_main(lines, backend)
    assert backend.passive is True and replies[0]['mode'] == 'PASSIVE' and replies[1]['ok']
    assert backend.control_actions == 0 and backend.sent == [] and backend.calls == []
    assert code == {'close': 0, 'broken': 5, 'exchange': 5}.get(tail[0], 4) if tail else code == 4


def test_passive_main_watchdog_emits_no_ros_control():
    import time
    backend = CountingBackend(FakeClock())
    read_fd, write_fd = os.pipe()
    writer = os.fdopen(write_fd, 'w')
    writer.write(json.dumps(hello(mode='PASSIVE', limits={'watchdog_s': 0.2, 'max_session_s': 300.0})) + '\n'); writer.flush()
    out = io.StringIO()
    with os.fdopen(read_fd) as reader:
        code = w.main(stdin=reader, stdout=out, backend_factory=lambda passive: backend, clock=time.monotonic)
    writer.close()
    last = json.loads(out.getvalue().splitlines()[-1])
    assert code == 3 and last['stop']['control_actions'] == 'NONE_PASSIVE_SESSION' and backend.control_actions == 0


def test_mode_cannot_change_after_hello():
    backend = CountingBackend(FakeClock())
    code, replies = run_main([PASSIVE_HELLO, json.dumps(hello(mode='OPERATIONAL'))], backend)
    assert replies[1]['ok'] is False and code == 5 and backend.control_actions == 0


def passive_session(**changes):
    clock = FakeClock()
    backend = CountingBackend(clock)
    _, ev = evidence()
    kwargs = dict(lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT, binding_evidence=ev,
                  limits={'watchdog_s': 3.0, 'max_session_s': 300.0}, mode='PASSIVE', clock=clock, fence=lambda e: None,
                  motion_allowed=lambda: pytest.fail('passive never asks for motion'), authority=lambda: pytest.fail('no authority needed'))
    kwargs.update(changes)
    transport = Loopback(backend, clock)
    return ps.PipeRos2Session(transport, **kwargs), transport, backend



def test_passive_host_deadline_refuses_new_requests_but_allows_worker_close():
    s, transport, backend = passive_session(limits={'watchdog_s': 3.0, 'max_session_s': 300.0})
    sent_before = len(transport.sent)
    clock = s.clock
    clock.now += 299.7
    with pytest.raises(TimeoutError, match='protected lifecycle STOP required') as caught:
        s.probe(timeout_s=1.0)
    assert caught.value.diagnostic['request_sent'] is False
    assert len(transport.sent) == sent_before
    s.close()
    assert transport.sent[-1]['op'] == 'close' and backend.control_actions == 0

def test_passive_host_session_probe_observe_close_without_commands():
    s, t, b = passive_session()
    assert s.probe(timeout_s=1.0)['odometry_publisher_gids'] == [ODOM_GID]
    raw_obs = s.observe(timeout_s=1.0)
    assert raw_obs['status']['armed'] is False and raw_obs['odometry']['child_frame_id'] == 'base_link'
    for command in (velocity(0.0), MODE_HOLD, ARM):
        with pytest.raises(RoverControlError, match='Passive session'):
            s.exchange(command, timeout_s=1.0)
    s.close()
    assert not any(m.get('op') == 'exchange' for m in t.sent) and b.control_actions == 0


@pytest.mark.parametrize('bad', ['container', 'lifecycle', 'expired', 'gid'])
def test_passive_session_still_requires_current_identity(bad):
    _, ev = evidence()
    changes = {}
    if bad == 'container':
        execution = copy.deepcopy(EXECUTION); execution['persistent_identity']['container_id'] = 'd' * 64
        changes['environment_execution'] = execution
    elif bad == 'lifecycle': changes['lifecycle_id'] = '00000000-0000-4000-8000-000000000000'
    elif bad == 'expired':
        ev = copy.deepcopy(ev); ev['status'] = 'EXPIRED'; changes['binding_evidence'] = ev
    if bad == 'gid':
        s, t, b = passive_session()
        b.graph[w.STATUS] = [{'gid': '08' * 24}]
        with pytest.raises(RoverControlError, match='changed'):
            s.observe(timeout_s=1.0)
        assert b.control_actions == 0
        return
    with pytest.raises(RoverControlError):
        passive_session(**changes)


def test_operational_session_requires_live_reservation_authority():
    with pytest.raises(locks.VehicleBusy, match='flight authority'):
        session(authority=ps._default_authority)  # no reservation held by this process; no hello is sent


def test_operational_session_still_stops_under_supervision():
    s, t, b, clock = session()
    assert s.mode == 'OPERATIONAL'
    assert s.exchange(MODE_HOLD, timeout_s=1.0).payload == {'status': True, 'curr_mode': 4}
