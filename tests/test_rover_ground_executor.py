"""Protected ground path with doubles only. Synthetic binding is NOT live evidence."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
import json
from threading import Event
from unittest.mock import Mock

import pytest

from planning.artifact_store import fingerprint, sha256
from tools import vehicle_execution_lock as locks
from tools import rover_ground_executor as ground
from tools import simulation_lifecycle as lifecycle
from tools import execution_reconciliation as reconciliation
from tools.rover_control import Reply, RoverControlError, RoverLimits, RoverControlCore, RoverMode
from tools.rover_ros2_adapter import Ros2RoverAdapter, MotionBinding, MODE, VELOCITY
from tests.test_rover_control import Clock
from tests.test_virtual_preflight import EXAMPLE


BINDING = MotionBinding('0'*64, '1'*64, 'fake-gid-offline-only')


class Session:
    def __init__(self, clock):
        self.clock = clock
        self.commands = []
        self.reads = 0
        self.overrides = {}
        self.cap_changes = {}
        self.fail = None
        self.closed = False
        self.on_publish = None
        self.post_disarmed = True

    def probe(self, *, timeout_s):
        return dict(status_type='ardupilot_msgs/msg/Status', odometry_type='nav_msgs/msg/Odometry',
                    mode_type='ardupilot_msgs/srv/ModeSwitch', velocity_type='geometry_msgs/msg/TwistStamped',
                    mode_available=True, velocity_subscribers=1, status_publishers=1,
                    odometry_publisher_gids=[BINDING.odometry_publisher_gid]) | self.cap_changes

    def observe(self, *, timeout_s):
        self.reads += 1
        self.clock.now += .01
        stopped = self.reads >= 4
        stamp = {'sec': self.reads, 'nanosec': 0}
        raw = {'odometry_publisher_gid': BINDING.odometry_publisher_gid, 'status': {'header': {'stamp': stamp}, 'vehicle_type': 1,
                         'mode': 4 if stopped else 15, 'armed': not (stopped and self.post_disarmed),
                         'flying': False, 'external_control': True, 'failsafe': []},
               'odometry': {'header': {'stamp': stamp}, 'child_frame_id': 'base_link',
                            'twist': {'twist': {'linear': dict(x=0., y=0., z=0.),
                                                'angular': dict(x=0., y=0., z=0.)}}},
               'status_received_monotonic_s': self.clock.now,
               'odometry_received_monotonic_s': self.clock.now}
        for key, value in self.overrides.items():
            if key in ('status', 'odometry'):
                raw[key].update(value)
            else:
                raw[key] = value
        return raw

    def exchange(self, command, *, timeout_s):
        locks.assert_execution_authority('v3')
        self.commands.append(deepcopy(command))
        if self.on_publish and command['endpoint'] == VELOCITY:
            self.on_publish()
        if command['endpoint'] == MODE:
            if self.fail == 'negative':
                return Reply(True, 0, {'status': False, 'curr_mode': 15})
            return Reply(True, 0, {'status': True, 'curr_mode': command['payload']['mode']})
        if self.fail == 'timeout':
            raise TimeoutError('synthetic write uncertain')
        return Reply(True, 0)

    def close(self):
        self.closed = True


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, 'LOCK_ROOT', tmp_path/'locks')
    monkeypatch.setattr(ground, 'RUN_ROOT', tmp_path/'ground')
    monkeypatch.setattr(ground, 'OPERATIONAL_ROVER_ENABLED', True)  # TEST POLICY ONLY
    monkeypatch.setattr('subprocess.run', Mock(side_effect=AssertionError('NO real subprocess')))
    monkeypatch.setattr('subprocess.Popen', Mock(side_effect=AssertionError('NO real worker spawn')))
    data = json.loads(EXAMPLE.read_bytes())
    data['vehicle'].update(vehicle_id='rover_01', vehicle_type='ugv', autopilot='ArduPilot')
    path = tmp_path/'mission.json'
    path.write_text(json.dumps(data))
    limits = RoverLimits(.5, .3, 2., 1., 4., .5, .02, .02)
    request = dict(kind='ROVER_BOUNDED_CONTROL', limits=asdict(limits), forward_mps=.1, yaw_rate_rad_s=.1, duration_s=.5)
    auth = dict(mission_sha256=sha256(path.read_bytes()), request_fingerprint=fingerprint(request),
                statement='Synthetic exact-scope declaration for offline test only')
    clock = Clock()
    session = Session(clock)
    factory = lambda journal: Ros2RoverAdapter(session, binding=BINDING, clock=clock, journal=journal)
    return path, request, auth, session, factory


def admit(setup, key='ground-test'):
    path, request, auth, _, _ = setup
    return ground.admit_ground_trial(path, key, request, auth)


def run(setup, admitted):
    return ground.run_ground_worker(admitted['run_id'], admitted['launch_token'], adapter_factory=setup[-1],
                                    readiness=lambda **kwargs: {'ready': kwargs == {'profile': 'two_drones_rover'}})


def test_default_policy_no_io_or_backend(setup, monkeypatch):
    monkeypatch.setattr(ground, 'OPERATIONAL_ROVER_ENABLED', False)
    assert admit(setup)['status'] == 'BLOCKED'
    assert not ground.RUN_ROOT.exists() and not locks.LOCK_ROOT.exists()
    assert ground.run_ground_worker('not-even-a-uuid', 'bad')['status'] == 'BLOCKED'


def test_protected_snapshot_validation_persistence_and_safe_stop(setup):
    admitted = admit(setup)
    assert admitted['status'] == 'ADMITTED'
    root = ground.directory(admitted['run_id'])
    assert (root/'mission.json').read_bytes() == setup[0].read_bytes()
    assert locks.restriction()['vehicle'] == 'v3'
    result = run(setup, admitted)
    assert result['status'] == 'STOP_OBSERVED'
    assert result['validation']['execution_status'] == 'APPROVED'
    assert result['movement_observed'] == 'NOT_MEASURED' and not result['route_executed']
    assert result['result']['motion_application_confirmed'] is False
    assert result['result']['stop']['stationary_observed'] is True
    assert result['ground_contact_confirmed'] is False
    assert locks.restriction() is None
    saved = json.loads((root/'report.json').read_bytes())
    assert saved == result and saved['worker'] == locks.process_identity()
    events = json.loads((root/'events.json').read_bytes())['events']
    assert len([e for e in events if e['operation'] == 'control_intent']) == 3
    assert setup[-2].closed
    assert ground.query_ground_trial(admitted['run_id'])['status'] == 'FINISHED'


@pytest.mark.parametrize('change', [dict(vehicle_id='drone_01'), dict(vehicle_type='multirotor'), dict(autopilot='PX4')])
def test_wrong_mission_identity_before_reservation(setup, change):
    data = json.loads(setup[0].read_bytes())
    data['vehicle'].update(change)
    setup[0].write_text(json.dumps(data))
    with pytest.raises(ValueError, match='exact rover'):
        admit(setup)
    assert not locks.LOCK_ROOT.exists() and not setup[-2].commands


def test_exact_scope_and_request_validation(setup):
    setup[2]['request_fingerprint'] = 'wrong'
    with pytest.raises(ValueError, match='authorization'):
        admit(setup)
    assert not locks.LOCK_ROOT.exists()


def test_snapshot_mutation_prevents_worker(setup):
    admitted = admit(setup)
    root = ground.directory(admitted['run_id'])
    (root/'mission.json').write_text('{}')
    with pytest.raises(ValueError, match='changed'):
        run(setup, admitted)
    assert locks.restriction()['owner_id'] == admitted['run_id']
    assert not setup[-2].commands


@pytest.mark.parametrize('cap', [dict(velocity_subscribers=0), dict(mode_available=False),
    dict(odometry_type=None), dict(status_publishers=2), dict(mode_type='wrong'),
    dict(odometry_publisher_gids=['unrelated']), dict(velocity_type='wrong')])
def test_incompatible_transport_blocks_before_controls(setup, cap):
    setup[-2].cap_changes = cap
    admitted = admit(setup)
    result = run(setup, admitted)
    assert result['status'] == 'UNCONFIRMED'
    assert not setup[-2].commands
    assert locks.restriction()['state'] == 'UNCONFIRMED'


def test_no_accredited_binding_even_with_discovered_topics(setup):
    admitted = admit(setup)
    result = ground.run_ground_worker(admitted['run_id'], admitted['launch_token'],
        adapter_factory=lambda journal: Ros2RoverAdapter(setup[-2], binding=None, clock=setup[-2].clock, journal=journal),
        readiness=lambda **kwargs: {'ready': True})
    assert 'not accredited' in str(result['error_evidence']) and not setup[-2].commands


@pytest.mark.parametrize('override', [dict(odometry_received_monotonic_s=0),
    dict(odometry={'child_frame_id': 'other_rover/base_link'}), dict(status={'vehicle_type': 2}),
    dict(status={'armed': False}), dict(status={'failsafe': [1]}),
    dict(odometry={'header': {'stamp': {'sec': 1, 'nanosec': 0}}})])
def test_missing_stale_or_wrong_observation_no_movement(setup, override):
    setup[-2].overrides = override
    admitted = admit(setup)
    result = run(setup, admitted)
    assert result.get('result', {}).get('motion_command_attempted') is not True
    assert not setup[-2].commands


@pytest.mark.parametrize('failure', ['timeout', 'negative'])
def test_uncertain_stop_or_negative_retains_reservation(setup, failure):
    setup[-2].fail = failure
    admitted = admit(setup)
    result = run(setup, admitted)
    assert result['status'] == 'UNCONFIRMED'
    assert locks.restriction()['state'] == 'UNCONFIRMED'
    assert all(c['endpoint'] in (MODE, VELOCITY) for c in setup[-2].commands)
    assert ground.query_ground_trial(admitted['run_id'])['status'] == 'UNCONFIRMED'


def test_stationary_still_armed_is_not_released(setup):
    setup[-2].post_disarmed = False
    admitted = admit(setup)
    result = run(setup, admitted)
    assert result['status'] == 'STOP_OBSERVED'
    assert locks.restriction()['state'] == 'UNCONFIRMED'
    assert ground.query_ground_trial(admitted['run_id'])['status'] == 'UNCONFIRMED'


def test_lost_response_duplicate_worker_and_read_only_query(setup):
    admitted = admit(setup)
    root = ground.directory(admitted['run_id'])
    before = {p: p.read_bytes() for p in root.iterdir()}
    duplicate = admit(setup)  # response lost: never another token
    assert duplicate['status'] == 'UNCONFIRMED' and 'launch_token' not in duplicate
    assert before == {p: p.read_bytes() for p in root.iterdir()}
    assert run(setup, admitted)['status'] == 'STOP_OBSERVED'
    commands = len(setup[-2].commands)
    assert run(setup, admitted)['status'] == 'BLOCKED'
    assert len(setup[-2].commands) == commands


def test_dead_or_recycled_worker_query_retains_originals(setup, monkeypatch):
    admitted = admit(setup)
    root = ground.directory(admitted['run_id'])
    job = ground._read(root, 'job.json')
    job.update(job_state='RUNNING', worker={'pid': 99999, 'start_ticks': 123, 'boot_id': 'old'})
    locks.atomic_json(root/'job.json', job)
    before = {p: p.read_bytes() for p in root.iterdir()}
    monkeypatch.setattr(locks, 'identity_alive', lambda identity: False)
    assert ground.query_ground_trial(admitted['run_id'])['status'] == 'UNCONFIRMED'
    assert before == {p: p.read_bytes() for p in root.iterdir()}
    assert locks.restriction() is not None
    assert run(setup, admitted)['status'] == 'BLOCKED'


def test_report_persistence_failure_never_releases(setup, monkeypatch):
    admitted = admit(setup)
    original = locks.atomic_json
    def fail_report(path, value):
        if path.name == 'report.json':
            raise OSError('synthetic disk failure')
        original(path, value)
    monkeypatch.setattr(locks, 'atomic_json', fail_report)
    assert run(setup, admitted)['status'] == 'UNCONFIRMED'
    assert locks.restriction()['state'] == 'UNCONFIRMED'
    assert (ground.directory(admitted['run_id'])/'failure.json').exists()


def test_rover_reservation_blocks_lifecycle_and_drone_reconciliation(setup, monkeypatch):
    admitted = admit(setup)
    backend = Mock(side_effect=AssertionError('No lifecycle'))
    monkeypatch.setattr(lifecycle, '_backend', backend)
    for action in ('start', 'stop', 'restart'):
        assert lifecycle.run_lifecycle(action)['status'] == 'BLOCKED'
    backend.assert_not_called()
    with pytest.raises(ValueError, match='Rover reservation'):
        reconciliation.capture(admitted['run_id'])
    assert locks.restriction()['owner_id'] == admitted['run_id']


def test_global_exclusion_between_rover_drone_and_lifecycle(setup, monkeypatch):
    admitted = admit(setup)
    entered, finish = Event(), Event()
    def pause_once():
        if not entered.is_set():
            entered.set()
            assert finish.wait(5), 'test barrier timeout'
    setup[-2].on_publish = pause_once
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, setup, admitted)
        assert entered.wait(5), 'worker did not reach publication barrier'
        try:
            for vehicle in ('v1', 'v2', 'v3'):
                with pytest.raises(locks.VehicleBusy):
                    locks.reserve('other', 'test', vehicle)
            assert lifecycle.run_lifecycle('stop')['status'] == 'BLOCKED'
        finally:
            finish.set()
        assert future.result()['status'] == 'STOP_OBSERVED'
    assert locks.restriction() is None


def test_adapter_cannot_control_without_authority(setup):
    adapter = setup[-1](lambda event: None)
    with pytest.raises(locks.VehicleBusy):
        adapter.probe(timeout_s=1)
    with pytest.raises(locks.VehicleBusy):
        adapter.exchange(RoverControlCore.velocity_message(.1, 0), timeout_s=1)


def test_adapter_rejects_wrong_interface_and_copter_services_under_authority(setup):
    admitted = admit(setup)
    with locks.execution_scope(admitted['run_id'], 'v3'):
        adapter = setup[-1](lambda event: None)
        adapter.probe(timeout_s=1)
        for command in (dict(kind='service', endpoint=MODE, type='ardupilot_msgs/srv/ModeSwitch', payload={'mode': 9}),
                        dict(kind='service', endpoint='/ap/v1/mode_switch', type='ardupilot_msgs/srv/ModeSwitch', payload={'mode': 4}),
                        RoverControlCore.velocity_message(.1, 0) | {'endpoint': '/ap/v1/cmd_vel'}):
            with pytest.raises(RoverControlError):
                adapter.exchange(command, timeout_s=1)
    assert not setup[-2].commands


def test_final_report_without_completed_release_is_uncertain(setup):
    admitted = admit(setup)
    setup[-2].post_disarmed = False
    run(setup, admitted)
    root = ground.directory(admitted['run_id'])
    job = ground._read(root, 'job.json')
    # Simulate crash after final job publication, before guard removal.
    locks.atomic_json(root/'job.json', {**job, 'job_state': 'FINISHED'})
    before = {p: p.read_bytes() for p in root.iterdir()}
    assert ground.query_ground_trial(admitted['run_id'])['status'] == 'UNCONFIRMED'
    assert before == {p: p.read_bytes() for p in root.iterdir()}
    assert locks.restriction() is not None


def test_declared_authorization_tamper_cannot_reach_backend(setup):
    admitted = admit(setup)
    root = ground.directory(admitted['run_id'])
    job = ground._read(root, 'job.json')
    job['authorization']['statement'] = 'substituted'
    locks.atomic_json(root/'job.json', job)
    with pytest.raises(ValueError, match='changed'):
        run(setup, admitted)
    assert not setup[-2].commands and locks.restriction() is not None


def test_forged_observation_publisher_blocks_controls(setup):
    setup[-2].overrides = {'odometry_publisher_gid': 'foreign'}
    admitted = admit(setup)
    result = run(setup, admitted)
    assert result['result']['motion_command_attempted'] is False
    assert not setup[-2].commands


def test_current_readiness_failure_persists_without_controls(setup):
    admitted = admit(setup)
    report = ground.run_ground_worker(admitted['run_id'], admitted['launch_token'], adapter_factory=setup[-1],
                                     readiness=lambda **kwargs: {'ready': False})
    assert report['status'] == 'UNCONFIRMED'
    assert not setup[-2].commands
    query = ground.query_ground_trial(admitted['run_id'])
    assert query['failure']['readiness'] == {'ready': False}
    assert query['reservation']['state'] == 'UNCONFIRMED'


def test_failed_intent_persistence_does_not_send_or_release(setup, monkeypatch):
    admitted = admit(setup)
    original = locks.atomic_json
    def fail_intent(path, value):
        if path.name == 'events.json' and any(e.get('operation') == 'control_intent' for e in value['events']):
            raise OSError('synthetic journal failure')
        original(path, value)
    monkeypatch.setattr(locks, 'atomic_json', fail_intent)
    report = run(setup, admitted)
    assert report['status'] == 'UNCONFIRMED'
    assert not setup[-2].commands
    assert locks.restriction()['state'] == 'UNCONFIRMED'


def test_native_observer_timeout_preserves_actual_partial_sample(setup, monkeypatch):
    from types import SimpleNamespace
    import tools.rover_ros2_adapter as ros
    clock = setup[-2].clock
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)  # never imports/starts ROS
    native._require_identity = lambda: None  # isolated transport test; not identity accreditation
    native.node = object()
    native.latest, native.previous = {}, {}
    def spin(node, timeout_sec):
        clock.now += max(timeout_sec, .001)
        native.latest['status'] = ({'header': {'stamp': {'sec': 1, 'nanosec': 0}}}, clock.now, 'status-gid')
    native.rclpy = SimpleNamespace(spin_once=spin)
    monkeypatch.setattr(ros, 'time', clock)
    with pytest.raises(TimeoutError) as caught:
        native.observe(timeout_s=.2)
    diagnostic = caught.value.diagnostic
    assert diagnostic['timeout_s'] == .2
    assert set(diagnostic['partial_samples']) == {'status'}
    assert diagnostic['partial_samples']['status']['message']['header']['stamp']['sec'] == 1


def test_native_observer_rejects_rewind_and_keeps_separate_receipts(setup, monkeypatch):
    from types import SimpleNamespace
    import tools.rover_ros2_adapter as ros
    clock = setup[-2].clock
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native._require_identity = lambda: None  # isolated transport test; not identity accreditation
    native.node = object()
    native.latest, native.previous = {}, {}
    def spin(node, timeout_sec):
        clock.now += .01
        for stream in ('status', 'odometry'):
            native.latest[stream] = ({'header': {'stamp': {'sec': 3, 'nanosec': 10}}}, clock.now, 'fake-gid')
    native.rclpy = SimpleNamespace(spin_once=spin)
    monkeypatch.setattr(ros, 'time', clock)
    first = native.observe(timeout_s=1)
    assert first['status_received_monotonic_s'] == clock.now
    assert first['odometry_publisher_gid'] == 'fake-gid'
    with pytest.raises(RoverControlError, match='Frozen/rewound'):
        native.observe(timeout_s=1)


def test_native_service_timeout_has_no_confirmation_or_resend(setup, monkeypatch):
    from types import SimpleNamespace
    import tools.rover_ros2_adapter as ros
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native._require_identity = lambda: None  # isolated transport test; not identity accreditation
    native.node = object()
    native.mode_type = SimpleNamespace(Request=lambda: SimpleNamespace(mode=None))
    future = SimpleNamespace(done=lambda: False, cancel=Mock())
    native.client = SimpleNamespace(call_async=Mock(return_value=future))
    native.rclpy = SimpleNamespace(spin_until_future_complete=Mock())
    admitted = admit(setup)
    command = dict(kind='service', endpoint=MODE, type='ardupilot_msgs/srv/ModeSwitch', payload={'mode': 4})
    with locks.execution_scope(admitted['run_id'], 'v3'):
        with pytest.raises(TimeoutError) as caught:
            native.exchange(command, timeout_s=.3)
        with pytest.raises(RoverControlError):
            native.exchange(command | {'payload': {'mode': 9}}, timeout_s=.3)
    assert caught.value.diagnostic['response_received'] is False
    assert caught.value.diagnostic['effects'] == 'UNCONFIRMED'
    native.client.call_async.assert_called_once()
    assert native.client.call_async.call_args.args[0].mode == 4
    future.cancel.assert_called_once()


def test_native_topic_publish_is_transport_only(setup):
    from types import SimpleNamespace
    import tools.rover_ros2_adapter as ros
    native = ros.NativeRos2Session.__new__(ros.NativeRos2Session)
    native._require_identity = lambda: None  # isolated transport test; not identity accreditation
    native.velocity_type = lambda: SimpleNamespace(header=SimpleNamespace(stamp=None, frame_id=''),
        twist=SimpleNamespace(linear=SimpleNamespace(x=0., y=0., z=0.), angular=SimpleNamespace(x=0., y=0., z=0.)))
    native.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: 'sim-stamp')))
    native.publisher = SimpleNamespace(get_subscription_count=lambda: 1, publish=Mock())
    admitted = admit(setup)
    with locks.execution_scope(admitted['run_id'], 'v3'):
        reply = native.exchange(RoverControlCore.velocity_message(.1, .2), timeout_s=.2)
    assert reply.sent is True and reply.payload is None
    assert reply.return_code is None and reply.native_api_completed is True
    message = native.publisher.publish.call_args.args[0]
    assert message.header.frame_id == 'base_link'
    assert message.twist.linear.x == .1 and message.twist.angular.z == .2


def test_snapshot_change_during_readiness_blocks_before_controls(setup):
    admitted = admit(setup)
    root = ground.directory(admitted['run_id'])
    def readiness(**kwargs):
        (root/'mission.json').write_text('{}')
        return {'ready': True}
    report = ground.run_ground_worker(admitted['run_id'], admitted['launch_token'],
                                     adapter_factory=setup[-1], readiness=readiness)
    assert report['status'] == 'UNCONFIRMED'
    assert not setup[-2].commands
    assert locks.restriction()['state'] == 'UNCONFIRMED'


def test_incompatible_capabilities_are_kept_in_durable_diagnostics(setup):
    setup[-2].cap_changes = {'velocity_subscribers': 0}
    admitted = admit(setup)
    run(setup, admitted)
    events = ground._read(ground.directory(admitted['run_id']), 'events.json')['events']
    probe = next(e for e in events if e['operation'] == 'probe')
    assert probe['capabilities']['velocity_subscribers'] == 0
    assert probe['timeout_s'] == setup[1]['limits']['call_timeout_s']
    assert probe['duration_wall_s'] >= 0 and probe['error_evidence']
