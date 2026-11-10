"""Synthetic ROS/proc evidence ONLY. Never starts ROS, Docker or a real worker."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools.rover_environment_identity import assess_identity, digest, RoverEnvironmentGuard
from tools.rover_identity_worker import PassiveObserver
from tools.rover_ros2_adapter import NativeRos2Session
from tools.rover_control import RoverControlError
from simulation.ros2_gazebo.scripts import sim_processes as supervisor


def evidence():
    launch = dict(pid=100, start_ticks=1000, boot_id='container-boot')
    worker = dict(pid=200, start_ticks=2000, boot_id='container-boot')
    environment = dict(engine_id='engine-synthetic', container_id='a'*64, name='/tfg-ardupilot-gazebo',
                       created_at='synthetic-not-a-clock-comparison', image_id='sha256:synthetic')
    expected = dict(lifecycle_id=str(uuid4()), profile='two_drones_rover', vehicle_id='rover_01',
                    interface='v3', namespace='/rover1', environment=environment, launch_process=launch, launch_sha256='b'*64)
    ros = {}
    for kind, topic, message in [('status', '/ap/v3/status', {'vehicle_type': 1}),
                                 ('odometry', '/rover1/odometry', {'child_frame_id': 'base_link'})]:
        ros[kind] = dict(topic=topic, message=message, publisher_gid='synthetic-gid',
                         publisher_namespace='/rover1', publisher_count=1, age_s=.1, source_progressing=True)
    record = dict(context_sha256=digest(expected), worker=worker, state='OBSERVING', ros=ros)
    current = dict(context_sha256=digest(expected), installed_launch_sha256=expected['launch_sha256'], environment=deepcopy(environment), record=record,
                   receipt_age_s=.1, worker_age_s=.2, process_clock_scope='CONTAINER_PROC_BOOT_AND_MONOTONIC',
                   processes={'100': launch, '200': worker})
    return expected, current


def test_consistent_identity_is_not_source_accreditation_or_motion_permission():
    expected, current = evidence()
    before = deepcopy(current)
    report = assess_identity(expected, current)
    assert report['identity_consistent'] is True
    assert report['status'] == 'BLOCKED'
    assert report['source_association_verified'] is False and report['movement_authorized'] is False
    assert 'XRCE' in report['reasons'][0]
    assert current == before
    guard = RoverEnvironmentGuard(expected, lambda: deepcopy(current))
    for _ in range(2):
        assert guard.query() == report
        with pytest.raises(RuntimeError, match='BLOCKED'):
            guard.require_motion_source()
    assert current == before


@pytest.mark.parametrize('fault', ['container', 'engine', 'launch', 'worker', 'recycled', 'boot',
    'old_start', 'old_worker', 'old_observation', 'wrong_interface', 'wrong_vehicle', 'wrong_namespace',
    'worker_stopped', 'record_absent', 'clock_domain', 'uncollected', 'ambiguous', 'launch_bytes'])
def test_wrong_missing_stale_or_lost_identity_stays_blocked(fault):
    expected, current = evidence()
    if fault == 'launch_bytes':
        current['installed_launch_sha256'] = 'changed'
    elif fault in ('container', 'engine'):
        current['environment'][fault+'_id'] = 'foreign'
    elif fault in ('launch', 'worker'):
        current['processes'].pop('100' if fault == 'launch' else '200')
    elif fault == 'recycled':
        current['processes']['200'] = {**current['processes']['200'], 'start_ticks': 9000}
    elif fault == 'boot':
        current['processes']['200'] = {**current['processes']['200'], 'boot_id': 'other'}
    elif fault == 'old_start':
        current['record']['context_sha256'] = 'old'
    elif fault == 'old_worker':
        current['worker_age_s'] = 4.
    elif fault == 'old_observation':
        current['record']['ros']['status']['age_s'] = 4.
    elif fault == 'wrong_interface':
        current['record']['ros']['status']['topic'] = '/ap/v2/status'
    elif fault == 'wrong_vehicle':
        current['record']['ros']['status']['message']['vehicle_type'] = 2
    elif fault == 'wrong_namespace':
        current['record']['ros']['odometry']['publisher_namespace'] = '/other'
    elif fault == 'worker_stopped':
        current['record']['state'] = 'BLOCKED'
    elif fault == 'record_absent':
        current.pop('record')
    elif fault == 'clock_domain':
        current['process_clock_scope'] = 'HOST_PID_ASSUMED_CONTAINER_PID'
    elif fault == 'uncollected':
        current.pop('worker_age_s')
    else:
        current['record']['ros']['odometry']['publisher_count'] = 2
    before = deepcopy(current)
    report = RoverEnvironmentGuard(expected, lambda: current).query()
    assert report['status'] == 'BLOCKED' and not report['identity_consistent']
    assert report['source_association_verified'] is False
    assert current == before


def test_collector_failure_never_restarts_or_creates_evidence():
    expected, _ = evidence()
    read = Mock(side_effect=TimeoutError('synthetic read-only collector timeout'))
    result = RoverEnvironmentGuard(expected, read).query()
    assert result['status'] == 'BLOCKED'
    assert 'collector unavailable' in result['reasons'][0]
    read.assert_called_once_with()


def test_native_session_no_longer_accepts_motion_binding_shape_alone():
    native = NativeRos2Session.__new__(NativeRos2Session)  # no ROS import or node
    with pytest.raises(RoverControlError, match='identity worker'):
        native.probe(timeout_s=1)
    expected, current = evidence()
    native.identity_guard = RoverEnvironmentGuard(expected, lambda: current)
    with pytest.raises(RuntimeError, match='XRCE'):
        native.probe(timeout_s=1)


def test_simulated_ros_sources_receipts_and_rewind_remain_distinct():
    now = [10.]
    gid = b'fake-endpoint'
    publisher = SimpleNamespace(endpoint_gid=gid, node_namespace='/rover1', node_name='bridge')
    node = SimpleNamespace(get_publishers_info_by_topic=lambda topic: [publisher])  # no publish/client methods
    observer = PassiveObserver(node, lambda msg: msg, monotonic=lambda: now[0])
    receive = observer.callback('odometry')
    for seconds in (1, 2):
        receive({'header': {'stamp': {'sec': seconds, 'nanosec': 0}}, 'child_frame_id': 'base_link'})
        now[0] += .1
    result = observer.observation()
    assert 'status' not in result  # never invent missing data
    assert result['odometry']['header_progressing']
    assert not result['odometry']['source_progressing']
    assert result['odometry']['publisher_gid'] is None
    assert result['odometry']['publisher_namespace'] is None
    assert result['odometry']['publisher_name'] is None
    assert result['odometry']['graph_publishers'] == [
        {'gid': gid.hex(), 'namespace': '/rover1', 'name': 'bridge'}]
    expected, current = evidence()
    current['record']['ros']['odometry'] = result['odometry']
    assessment = assess_identity(expected, current)
    assert not assessment['identity_consistent']
    assert assessment['status'] == 'BLOCKED'
    assert result['odometry']['age_s'] == pytest.approx(.1)
    receive({'header': {'stamp': {'sec': 1, 'nanosec': 0}}})
    receive({'header': {'stamp': {'sec': 3, 'nanosec': 0}}})
    assert not observer.observation()['odometry']['header_progressing']  # no automatic recovery


def test_passive_worker_registered_in_supervisor_without_control_or_respawn(tmp_path, monkeypatch):
    installed = tmp_path/'launch.py'
    installed.write_text('offline effective launch')
    monkeypatch.setattr(supervisor, 'INSTALLED_ROVER_LAUNCH', installed)
    monkeypatch.setattr(supervisor, 'ROVER_IDENTITY_ROOT', tmp_path/'identity')
    monkeypatch.setattr(supervisor, 'STATE', tmp_path/'state.json')
    launch = supervisor.Process(100, 1, 1000, ('ros2', 'launch'), True)
    worker = supervisor.Process(200, 1, 2000, ('python3', '/tmp/tfg_rover_identity_worker.py'), True)
    popen = Mock(return_value=SimpleNamespace(pid=200))
    monkeypatch.setattr(supervisor.subprocess, 'Popen', popen)
    monkeypatch.setattr(supervisor, 'read_process', lambda pid: worker)
    expected, _ = evidence()
    reference = {k: v for k, v in expected.items() if k not in ('launch_process', 'vehicle_id', 'interface', 'namespace')}
    reference['launch_sha256'] = hashlib.sha256(installed.read_bytes()).hexdigest()
    env = {supervisor.MARKER: supervisor.PROJECT, 'TFG_SIM_START_CONTEXT': json.dumps(reference)}
    result = supervisor.start_rover_identity(launch, env)
    assert result['scope'] == 'READ_ONLY_IDENTITY_NOT_MOVEMENT'
    context = json.loads(Path(result['context_path']).read_text())
    assert context['interface'] == 'v3' and context['namespace'] == '/rover1'
    assert context['launch_process']['pid'] == 100
    assert supervisor.remembered_identities() == {(100, 1000), (200, 2000)}
    assert popen.call_args.args[0] == ['python3', '/tmp/tfg_rover_identity_worker.py', '--context', result['context_path']]
    assert popen.call_args.kwargs['env'][supervisor.MARKER] == supervisor.PROJECT
    with pytest.raises(FileExistsError):
        supervisor.start_rover_identity(launch, env)
    popen.assert_called_once()  # repeated invocation never overwrites/restarts


def test_supervisor_cleanup_includes_passive_worker_but_not_an_unowned_pid():
    launch = supervisor.Process(100, 1, 1000, ('ros2', 'launch', 'ardupilot_gz_bringup', 'tfg_demo.launch.py'))
    passive = supervisor.Process(200, 1, 2000, ('python3', '/tmp/tfg_rover_identity_worker.py'), True)
    foreign = supervisor.Process(300, 1, 3000, ('python3', '/tmp/tfg_rover_identity_worker.py'))
    assert set(supervisor.select_owned({p.pid:p for p in (launch,passive,foreign)}, set())) == {100,200}


def test_lifecycle_backend_transmits_persisted_environment_reference(tmp_path, monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    from tools import vehicle_execution_lock as locks
    from tools import reconciliation_environment as environment
    monkeypatch.setattr(locks, 'LOCK_ROOT', tmp_path/'locks')
    locks.LOCK_ROOT.mkdir()
    owner = str(uuid4())
    locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json', {'owner_id': owner, 'profile': 'two_drones_rover'})
    expected, _ = evidence()
    observed = {'status': 'ACTIVE', **expected['environment'], 'state': {'StartedAt': 'synthetic-pre-start'}}
    inspect = Mock(return_value=observed)
    monkeypatch.setattr(environment, 'inspect_environment', inspect)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(lifecycle.subprocess, 'run', run)
    log = tmp_path/'backend.log'
    assert lifecycle._backend('start', True, 123, {'pid': 42}, log) == 0
    saved = json.loads((tmp_path/'rover_environment_reference.json').read_text())
    transferred = json.loads(run.call_args.kwargs['env']['TFG_SIM_START_CONTEXT'])
    assert saved == transferred and saved['lifecycle_id'] == owner
    assert saved['environment'] == expected['environment']
    actual = lifecycle.SCRIPTS.parent/'launch/tfg_demo.launch.py'
    assert saved['launch_sha256'] == hashlib.sha256(actual.read_bytes()).hexdigest()
    inspect.assert_called_once()


def test_missing_environment_blocks_backend_before_spawn(tmp_path, monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    from tools import vehicle_execution_lock as locks
    from tools import reconciliation_environment as environment
    monkeypatch.setattr(locks, 'LOCK_ROOT', tmp_path/'locks')
    locks.LOCK_ROOT.mkdir()
    locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json', {'profile': 'two_drones_rover'})
    monkeypatch.setattr(environment, 'inspect_environment', lambda: {'status':'UNKNOWN'})
    run = Mock(side_effect=AssertionError('No backend'))
    monkeypatch.setattr(lifecycle.subprocess, 'run', run)
    with pytest.raises(locks.VehicleBusy, match='unavailable or ambiguous'):
        lifecycle._backend('start', True, 123, {}, tmp_path/'backend.log')
    run.assert_not_called()


def test_failed_identity_query_does_not_release_existing_rover_guard(tmp_path, monkeypatch):
    from tools import vehicle_execution_lock as locks
    monkeypatch.setattr(locks, 'LOCK_ROOT', tmp_path/'locks')
    locks.reserve(str(uuid4()), 'synthetic-test', 'v3')
    path = locks.LOCK_ROOT/'v3.json'
    before = path.read_bytes()
    expected, current = evidence()
    current['processes'].pop('200')
    guard = RoverEnvironmentGuard(expected, lambda: current)
    for _ in range(2):
        assert guard.query()['status'] == 'BLOCKED'
    assert path.read_bytes() == before
    assert locks.restriction() is not None


def test_combined_sample_and_heartbeat_ages_are_not_reset_by_a_recent_receipt():
    expected, current = evidence()
    current['worker_age_s'] = 2.
    current['record']['ros']['status']['age_s'] = 2.
    report = assess_identity(expected, current)
    assert not report['identity_consistent']
    assert 'stale' in report['reasons'][0]


def test_passive_main_uses_only_subscriptions_and_exits_blocked(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    import tools.rover_identity_worker as worker
    root = tmp_path/'passive'
    root.mkdir()
    expected, _ = evidence()
    context = root/'context.json'
    context.write_text(json.dumps(expected))
    monkeypatch.setattr(worker, 'Path', lambda p: root if str(p) == '/tmp/tfg_rover_identity' else Path(p))
    monkeypatch.setattr(worker, 'process_identity', lambda pid=None: expected['launch_process'] if pid == 100 else
                        {'pid':200,'start_ticks':2000,'boot_id':'container-boot'})
    monkeypatch.setattr(sys, 'argv', ['passive-worker', '--context', str(context)])
    callbacks = {}
    def subscribe(cls, topic, callback, qos):
        callbacks[topic] = callback
        return object()
    # Missing create_publisher/create_client is intentional: calling either fails.
    node = SimpleNamespace(create_subscription=subscribe, destroy_node=Mock(),
                           get_publishers_info_by_topic=lambda topic: [])
    rclpy = ModuleType('rclpy')
    running = iter((True,False))
    rclpy.ok = lambda: next(running)
    rclpy.init = Mock()
    rclpy.create_node = Mock(return_value=node)
    def spin(node, timeout_sec):
        assert timeout_sec == .25
        for stamp in (1,2):
            for topic, callback in callbacks.items():
                callback({'header':{'stamp':{'sec':stamp,'nanosec':0}},
                          'vehicle_type':1,'child_frame_id':'base_link'})
    rclpy.spin_once = spin
    qos = ModuleType('rclpy.qos')
    qos.QoSProfile = lambda **kwargs: kwargs
    qos.ReliabilityPolicy = SimpleNamespace(BEST_EFFORT='best-effort')
    qos.DurabilityPolicy = SimpleNamespace(VOLATILE='volatile')
    monkeypatch.setitem(sys.modules,'rclpy',rclpy)
    monkeypatch.setitem(sys.modules,'rclpy.qos',qos)
    for package, name, value in [('ardupilot_msgs.msg','Status',object()), ('nav_msgs.msg','Odometry',object()),
                                 ('rosidl_runtime_py.convert','message_to_ordereddict',lambda msg:msg)]:
        root_name = package.split('.')[0]
        monkeypatch.setitem(sys.modules,root_name,ModuleType(root_name))
        module = ModuleType(package)
        setattr(module,name,value)
        monkeypatch.setitem(sys.modules,package,module)
    assert worker.main() == 1
    record = json.loads((root/'worker.json').read_text())
    assert record['state'] == 'BLOCKED' and record['movement_authorized'] is False
    assert set(callbacks) == {'/ap/v3/status','/rover1/odometry'}
    assert record['context_sha256'] == digest(expected)
    assert record['error'] == 'Identity worker stopped; no automatic restart'
    for stream in record['ros'].values():
        assert stream['publisher_gid'] is None
        assert stream['publisher_gid_availability'] == 'UNAVAILABLE_CALLBACK_API'
    assert record['ros']['status']['message']['vehicle_type'] == 1
    node.destroy_node.assert_called_once()
