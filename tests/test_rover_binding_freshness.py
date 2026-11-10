"""Execute the actual container collector over fake ROS/Gazebo; never starts a service."""
import copy
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from tools import rover_motion_binding as mb
from tools.rover_control import RoverControlError
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE, NOW, Q, GZ, CONFIG, raw
from tests.test_rover_binding_metrics import FakeGraph, ODOM_OK, STATUS_OK, ODOM_EARLY, STATUS_EARLY, EXPECTED
from tools.rover_ros2_adapter import ODOMETRY, STATUS

ROOT=Path(__file__).resolve().parents[1]


def collector(monkeypatch,tmp_path,*,metadata_delay=0.0,subscription_delay=0.0,cleanup_delay=0.0,cleanup_error=False,shutdown_error=False,metadata_error=False,timeline=None,deliver=True,paused=False,sample_s=4.0):
    """The real COLLECTOR runs; only its dependencies are doubles."""
    clock=FakeGraph(timeline or {ODOMETRY:[(0,[ODOM_OK])],STATUS:[(0,[STATUS_OK])]},step=0.1)
    bridge_file=tmp_path/'bridge.yaml';bridge_file.write_text(CONFIG)
    params_file=tmp_path/'params.yaml';params_file.write_text('config_file: '+str(bridge_file))
    count=0;callback=None;active=True
    class Node:
        def get_publishers_info_by_topic(self,topic):
            return [NS(node_name=p['node'],node_namespace=p['namespace'],endpoint_gid=bytes.fromhex(p['gid']),
                topic_type='t',qos_profile=NS(reliability=NS(name='RELIABLE'))) for p in clock.query(topic)]
        def create_subscription(self,*args):
            nonlocal callback
            clock.now+=subscription_delay
            callback=args[2]
        def destroy_node(self):
            clock.now+=cleanup_delay
            if cleanup_error:raise RuntimeError('synthetic destroy failure')
    node=Node()
    def spin(n,timeout_sec):
        nonlocal count
        clock.now+=max(0.001,timeout_sec)
        if callback and deliver:
            count+=1;stamp=1_000_000_000+(0 if paused else count*20_000_000)
            callback(NS(header=NS(stamp=NS(sec=stamp//10**9,nanosec=stamp%10**9),frame_id='odom'),child_frame_id='base_link',
                pose=NS(pose=NS(position=NS(x=-0.0012461,y=-3.0005524,z=0.0949062),orientation=NS(x=Q[0],y=Q[1],z=Q[2],w=Q[3])))))
    ros=ModuleType('rclpy');ros.init=lambda:None;ros.create_node=lambda name:node;ros.spin_once=spin;ros.ok=lambda:active
    def shutdown():
        nonlocal active
        if shutdown_error:raise RuntimeError('synthetic shutdown failure')
        active=False
    ros.shutdown=shutdown
    qos=ModuleType('rclpy.qos');qos.QoSProfile=lambda **k:NS(**k);qos.ReliabilityPolicy=NS(BEST_EFFORT=1);qos.DurabilityPolicy=NS(VOLATILE=0)
    nav=ModuleType('nav_msgs.msg');nav.Odometry=object
    fake_time=ModuleType('time');fake_time.monotonic=clock.monotonic
    fake_time.monotonic_ns=lambda:1_000_000_000+int(clock.now*10**9);fake_time.time_ns=lambda:NOW+int(clock.now*10**9)
    class Proc:
        name='42'
        def __truediv__(self,name):return NS(read_bytes=lambda:b'parameter_bridge\0__ns:=/rover1\0--params-file\0'+str(params_file).encode())
    fake_pathlib=ModuleType('pathlib')
    def fake_path(value):
        if str(value)=='/proc':return NS(iterdir=lambda:[Proc()])
        if str(value)=='/proc/sys/kernel/random/boot_id':
            def read_boot():
                if metadata_error:raise OSError('synthetic boot metadata failure')
                return BOOT
            return NS(read_text=read_boot)
        return Path(value)
    fake_pathlib.Path=fake_path
    def gz(*args,**kwargs):clock.now+=metadata_delay;return NS(returncode=0,stdout=GZ,stderr='')
    cfg=dict(odometry=ODOMETRY,status=STATUS,namespace='/rover1',model='rover1',expected=EXPECTED,
             discovery_s=5.0,sample_s=sample_s,samples=5,
             scope=dict(lifecycle_id=LIFECYCLE,environment_execution=EXECUTION,host_boot_id=BOOT))
    output=io.StringIO()
    with monkeypatch.context() as m:
        for name,mod in [('rclpy',ros),('rclpy.qos',qos),('nav_msgs.msg',nav),('time',fake_time),('pathlib',fake_pathlib)]:m.setitem(sys.modules,name,mod)
        m.setattr('subprocess.run',gz)
        m.setattr('os.readlink',lambda p:'fake-namespace')
        m.setattr(sys,'stdin',io.StringIO(json.dumps(cfg)));m.setattr(sys,'stdout',output)
        exec(compile(mb.COLLECTOR,'<actual-binding-collector>','exec'),{'__name__':'__main__'})
    return json.loads(output.getvalue()),clock.now


def assess(value, elapsed=1.0, **kwargs):
    if value.get('collector_schema'):
        kwargs.setdefault('host_window',dict(started_monotonic_ns=10**15,received_monotonic_ns=10**15+int(elapsed*1e9)))
        kwargs.setdefault('now_monotonic_ns',10**15+int(elapsed*1e9)+1)
    else:kwargs.setdefault('now_wall_ns',value['collected_wall_unix_ns']+1)
    return mb.assess(value,lifecycle_id=LIFECYCLE,environment_execution=EXECUTION,host_boot_id=BOOT,**kwargs)


def test_actual_collector_does_not_age_samples_while_gazebo_query_takes_2727_ms(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path,metadata_delay=2.726745415)
    evidence=assess(value,elapsed)[1]
    assert evidence['status']=='ACCREDITED_FOR_SESSION'
    assert mb.MAX_SAMPLE_AGE_S==2.0
    stamps={item['phase']:item['container_monotonic_ns'] for item in value['timing']}
    assert stamps['bridge_start'] <= stamps['bridge_end'] <= stamps['gazebo_query_start']
    assert stamps['gazebo_query_end'] <= stamps['fresh_window_start'] <= value['samples'][0]['received_monotonic_ns']
    assert value['samples'][-1]['received_monotonic_ns'] <= stamps['fresh_window_end'] <= stamps['cleanup_start'] <= stamps['cleanup_end']
    assert value['collected_monotonic_ns'] >= stamps['cleanup_end']
    assert evidence['freshness']['gazebo_pose_to_first_sample_s'] <= 2.0


def test_immediate_odometry(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path)
    assert assess(value,elapsed)[1]['status']=='ACCREDITED_FOR_SESSION'


@pytest.mark.parametrize('early',[STATUS,ODOMETRY])
def test_either_stream_can_appear_first(monkeypatch,tmp_path,early):
    timeline={ODOMETRY:[(0 if early==ODOMETRY else 1.0,[ODOM_OK])],STATUS:[(0 if early==STATUS else 1.0,[STATUS_OK])]}
    value,elapsed=collector(monkeypatch,tmp_path,timeline=timeline)
    assert value['discovery']['complete'] and assess(value,elapsed)[1]['status']=='ACCREDITED_FOR_SESSION'


def test_unresolved_dds_names_wait_before_sampling(monkeypatch,tmp_path):
    timeline={ODOMETRY:[(0,[ODOM_EARLY]),(2.0,[ODOM_OK])],STATUS:[(0,[STATUS_EARLY]),(3.0,[STATUS_OK])]}
    value,elapsed=collector(monkeypatch,tmp_path,timeline=timeline)
    assert value['discovery']['elapsed_s']>=3.0
    assert assess(value,elapsed)[1]['status']=='ACCREDITED_FOR_SESSION'


def test_old_first_receipt_and_fresh_last_keep_existing_criterion():
    value=raw();value['samples'][0]['received_wall_unix_ns']-=10_000_000_000
    assert assess(value)[1]['status']=='ACCREDITED_FOR_SESSION'


def test_fresh_first_then_old_last_is_rejected():
    value=raw();value['samples'][-1]['received_wall_unix_ns']-=3_000_000_000
    with pytest.raises(RoverControlError):assess(value)


def test_slow_cleanup_is_not_hidden_by_moving_the_collection_timestamp(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path,cleanup_delay=2.726745415)
    with pytest.raises(RoverControlError,match='stale'):assess(value,elapsed)


def test_delayed_odometry_after_gazebo_pose_is_rejected_as_incoherent(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path,subscription_delay=2.1)
    with pytest.raises(RoverControlError,match='temporally coherent'):
        assess(value,elapsed)


def test_paused_simulated_clock_does_not_become_fresh_source_data(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path,paused=True)
    with pytest.raises(RoverControlError,match='clock not strictly increasing'):assess(value,elapsed)

@pytest.mark.parametrize(('phase','options'),[
    ('destroy_node',dict(cleanup_error=True)),
    ('shutdown',dict(shutdown_error=True)),
    ('metadata:boot_id',dict(metadata_error=True)),
])
def test_cleanup_or_metadata_failure_preserves_raw_and_blocks(monkeypatch,tmp_path,phase,options):
    value,elapsed=collector(monkeypatch,tmp_path,**options)
    assert value['collector_error']['phase']==phase
    assert len(value['samples'])==5
    assert any(error['phase']==phase for error in value['collector_errors'])
    with pytest.raises(RoverControlError,match='Collector failed'):
        assess(value,elapsed)


def test_different_host_and_container_clock_origins_are_never_subtracted(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path)
    assert value.get('collector_schema')==mb.COLLECTOR_SCHEMA
    for sample in value['samples']:sample['received_wall_unix_ns']+=10**17
    value['collected_wall_unix_ns']+=10**17
    assert assess(value,elapsed,now_wall_ns=1)[1]['status']=='ACCREDITED_FOR_SESSION'


def test_gid_change_during_sampling_is_rejected(monkeypatch,tmp_path):
    other=dict(ODOM_OK,gid='09'*24)
    value,elapsed=collector(monkeypatch,tmp_path,timeline={ODOMETRY:[(0,[ODOM_OK]),(0.25,[other])],STATUS:[(0,[STATUS_OK])]})
    with pytest.raises(RoverControlError):assess(value,elapsed)


def test_duplicate_publishers_are_rejected(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path,timeline={ODOMETRY:[(0,[ODOM_OK,dict(ODOM_OK,gid='03'*24)])],STATUS:[(0,[STATUS_OK])]})
    with pytest.raises(RoverControlError):assess(value,elapsed)


def test_no_new_samples_times_out_with_raw_evidence(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path,deliver=False,sample_s=0.3)
    assert value.get('collector_error',{}).get('type')=='TimeoutError'
    assert value['samples']==[] and value['before'] and value['after']
    with pytest.raises(RoverControlError):assess(value,elapsed)


def test_foreign_lifecycle_raw_is_not_relabelled(monkeypatch,tmp_path):
    value,elapsed=collector(monkeypatch,tmp_path)
    value.setdefault('scope',{})['lifecycle_id']='a-previous-lifecycle'
    with pytest.raises(RoverControlError,match='another'):assess(value,elapsed)


def test_real_2727_ms_failure_replays_as_rejected():
    report=Path('/home/joelm/TFG/archivo_TFG/rover-passive-2026-11-04.jcpinj4s')
    if not report.is_dir():pytest.skip('Archived passive-session report unavailable on this machine')
    value=json.loads((report/'motion-binding.json').read_text())['raw']
    start=json.loads((report/'start-result.json').read_text())['operation']
    assert (value['collected_wall_unix_ns']-value['samples'][-1]['received_wall_unix_ns'])/1e9==pytest.approx(2.726745415)
    with pytest.raises(RoverControlError,match='stale'):
        mb.assess(value,lifecycle_id=start['owner_id'],environment_execution=start['environment_execution'],
                  host_boot_id=value['boot_id'],now_wall_ns=value['collected_wall_unix_ns']+1)


def test_previously_valid_real_session_still_has_identical_evidence():
    path=ROOT/'simulation/ros2_gazebo/results/rover_only_binding_final_2026_11_03/motion-binding.json'
    old=json.loads(path.read_text());scope=old['evidence']['scope']
    _,ev=mb.assess(old['raw'],**scope,now_wall_ns=old['raw']['collected_wall_unix_ns']+1)
    assert ev==old['evidence']
