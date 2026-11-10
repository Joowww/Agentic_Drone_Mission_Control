"""Synthetic local transfer + existing public worker; no ROS or vehicles."""
import copy
import json
import os
import subprocess
import sys
from dataclasses import asdict
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from planning.artifact_store import fingerprint
from tools import rover_observation_stream as stream, rover_ros2_adapter as ros
from tests.test_rover_control import Clock
from tests.test_rover_transport_preparation import fake_ros
from tests.test_rover_ground_executor import setup as ground_setup

SESSION='11111111-1111-4111-8111-111111111111'
IDENTITY=dict(pid=999,start_ticks=12,boot_id='fixture',net_namespace='net:1',pid_namespace='pid:1',time_namespace='time:1')


def test_failed_stream_retains_exited_child_stderr_without_accepting_closure():
    # Plain Python fixture, not a ROS receiver. Reproduce real pipes/EOF/rc2,
    # including the sticky rejection that bypasses the normal footer wait.
    child=subprocess.Popen([sys.executable,'-c',
        "import sys;sys.stderr.write('receiver: UNCERTAIN stage=CLOSE\\n');sys.exit(2)"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    frames=stream.PipeFrames(child)
    src=stream.ObservationStream(frames,session_id=SESSION,identity=IDENTITY,max_age_s=.5)
    try:
        with pytest.raises(ValueError,match='disconnected/truncated before footer'):
            src._next(2,closing=True)
        child.wait(timeout=2)  # process exit known, stderr still unread
        with pytest.raises(ValueError,match='permanently rejected'):
            src.close(timeout_s=1)
        assert frames.stderr==b'receiver: UNCERTAIN stage=CLOSE\n'
        assert src.close_result['return_code']==2 and src.footer is None and not src.closed
        frames.wait(0)  # another wait must not erase the preserved diagnostic
        assert frames.stderr==b'receiver: UNCERTAIN stage=CLOSE\n'
    finally:
        child.wait(timeout=2);frames.release()


def test_ended_child_stderr_keeps_existing_bound():
    child=subprocess.Popen([sys.executable,'-c',"import sys;sys.stderr.write('x'*4097)"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    frames=stream.PipeFrames(child)
    try:
        child.wait(timeout=2)
        with pytest.raises(ValueError,match='stderr budget'):frames.ended()
        assert frames.observed_return_code==0 and len(frames.stderr)==4097
    finally:
        child.wait(timeout=2);frames.release()


def envelope(event,sequence,**fields):
    return dict(schema=stream.SCHEMA,event=event,session_id=SESSION,client_process=IDENTITY,sequence=sequence,
                movement_authorized=False,identity_verified=False,**fields)


def sample(topic,sequence,stamp,receipt,*,mode=15):
    header=dict(frame_id='odom',stamp=dict(sec=0,nanosec=stamp))
    raw=dict(topic=topic,receipt=dict(steady_ns=int(receipt*1e9),system_unix_ns=100),
        message_publisher_gid=('1' if topic.endswith('status') else '2')*48,
        rmw_implementation_identifier='rmw_fastrtps_cpp',from_intra_process=False,incomplete=False,
        message_gid_state='OBSERVED_NOT_ACCREDITED',header=header)
    if topic.endswith('status'):
        body=dict(header=header,vehicle_type=1,mode=mode,armed=True,flying=False,external_control=True,failsafe=[])
    else:
        raw['child_frame_id']='base_link'
        body=dict(header=header,child_frame_id='base_link',
            pose={'pose':{'position':dict(x=0.,y=0.,z=0.),'orientation':dict(x=0.,y=0.,z=0.,w=1.)},'covariance':[0.]*36},
            twist={'twist':{'linear':dict(x=0.,y=0.,z=0.),'angular':dict(x=0.,y=0.,z=0.)},'covariance':[0.]*36})
    return envelope('sample',sequence,topic=topic,sample=raw,body=body)


class Frames:
    def __init__(self,rows,clock):self.rows=copy.deepcopy(rows);self.clock=clock;self.requested=False;self.rc=0;self.released=False
    def ready(self,timeout_s=0.):
        # Synthetic delivery schedule; polling must not consume future samples.
        if not self.rows:return True
        row=self.rows[0]
        if isinstance(row,bytes):return True
        if row.get('event')=='footer':return self.requested
        return row.get('event')!='sample' or row['sample']['receipt']['steady_ns']/1e9<=self.clock.now
    def read(self,timeout_s):
        assert timeout_s>0
        if not self.rows:raise EOFError('synthetic disconnect')
        row=self.rows.pop(0)
        if isinstance(row,bytes):return row
        if row.get('event')=='sample':self.clock.now=max(self.clock.now,row['sample']['receipt']['steady_ns']/1e9+.001)
        return json.dumps(row).encode()
    def request_close(self,timeout_s):self.requested=True
    def wait(self,timeout_s):return self.rc
    def release(self):self.released=True


def header():return envelope('header',1,process=IDENTITY,max_samples=20,duration_s=120,clock_scope='SAME_PROC_BOOT_AND_MONOTONIC')


def pair(start=2,stamp=1,receipt=100.01,mode=15):
    return [sample('/ap/v3/status',start,stamp,receipt,mode=mode),sample('/rover1/odometry',start+1,stamp,receipt+.001)]


def source(rows,clock=None):
    clock=clock or Clock();frames=Frames(rows,clock)
    current=lambda pid:dict(IDENTITY) if pid==999 else {**IDENTITY,'pid':os.getpid()}
    return stream.ObservationStream(frames,session_id=SESSION,identity=IDENTITY,read_context=current,clock=clock,max_age_s=.5),frames


def test_original_receipt_is_separate_from_transfer_and_close_is_observed():
    rows=[header(),*pair(),envelope('footer',4,reader_closed=True,counts={'/ap/v3/status':1,'/rover1/odometry':1})]
    src,f=source(rows);value=src.observe(timeout_s=1)
    assert value['odometry_received_monotonic_s']==pytest.approx(100.011)
    assert value['sample_provenance']['odometry']['transfer']>value['odometry_received_monotonic_s']
    assert src.probe(timeout_s=.1)['session_id']==SESSION
    src.close(timeout_s=1);src.close(timeout_s=1)
    assert src.closed and f.requested and f.released


def test_watch_cache_does_not_refresh_receipt_and_rejects_stale_data():
    src,f=source([header(),*pair()]);original=src.observe(timeout_s=1)
    # No new bytes: readiness double deliberately reports no delivery.
    f.ready=lambda timeout_s:False
    src.clock.now+=.1
    watched=src.poll(timeout_s=.05)
    assert watched==original
    src.clock.now+=.5
    with pytest.raises(ValueError,match='stale'):src.poll(timeout_s=.05)


def test_watch_drains_available_pair_with_original_metadata():
    src,f=source([header(),*pair(),*pair(4,2,100.02),*pair(6,3,101.)])
    src.observe(timeout_s=1);src.clock.now=100.03
    watched=src.poll(timeout_s=.05)
    assert watched['odometry_received_monotonic_s']==pytest.approx(100.021)
    assert watched['sample_provenance']['odometry']['raw_record']
    f.rows=[envelope('footer',6,reader_closed=True,counts={'/ap/v3/status':2,'/rover1/odometry':2})];f.requested=True
    with pytest.raises(ValueError,match='ended'):src.poll(timeout_s=.05)


@pytest.mark.parametrize('fault',['truncated','missing_gid','changed_gid','repeat','late','restarted','different_process','wrong_frame','incomplete','nonfinite','clock'])
def test_failures_never_restore_identity_or_freshness(fault):
    rows=[header(),*pair(),*pair(4,2,100.02)]
    if fault=='truncated':rows[3]=b'{'
    elif fault=='missing_gid':rows[3]['sample']['message_publisher_gid']=None
    elif fault=='changed_gid':rows[3]['sample']['message_publisher_gid']='3'*48
    elif fault=='repeat':rows[3]['sample']['header']['stamp']['nanosec']=1
    elif fault=='restarted':rows[3]=header()
    elif fault=='different_process':rows[3]['client_process']={**IDENTITY,'start_ticks':99}
    elif fault=='wrong_frame':rows[4]['body']['child_frame_id']='map'
    elif fault=='incomplete':rows[3]['sample']['incomplete']=True
    elif fault=='nonfinite':rows[4]['body']['twist']['twist']['linear']['x']=float('nan')
    src,f=source(rows);src.observe(timeout_s=1)
    if fault=='late':src.clock.now+=2
    if fault=='clock':src.read_context=lambda pid:{**IDENTITY,'boot_id':'different'}
    with pytest.raises((ValueError,RuntimeError,EOFError)):src.observe(timeout_s=1)
    assert src.failed
    with pytest.raises(ValueError):src.observe(timeout_s=1)


def test_eof_loss_and_failed_wait_do_not_claim_closure():
    src,f=source([header(),*pair()]);src.observe(timeout_s=1)
    with pytest.raises(EOFError):src.close(timeout_s=1)
    assert not src.closed and not f.released
    src,f=source([header(),*pair(),envelope('footer',4,reader_closed=True,counts={'/ap/v3/status':1,'/rover1/odometry':1})]);src.observe(timeout_s=1);f.rc=2
    with pytest.raises(ValueError):src.close(timeout_s=1)
    assert not src.closed


def test_real_pipe_framing_rejects_partial_record_without_ros():
    read,write=os.pipe();stdin_read,stdin_write=os.pipe()
    child=NS(stdout=os.fdopen(read,'rb',buffering=0),stdin=os.fdopen(stdin_write,'wb',buffering=0))
    frames=stream.PipeFrames(child)
    try:
        os.write(write,b'{"first":1}\n{');os.close(write)
        assert frames.read(.1)==b'{"first":1}'
        with pytest.raises(ValueError,match='disconnected/truncated'):frames.read(.1)
    finally:frames.release();os.close(stdin_read)


def test_native_adapter_consumes_receiver_not_graph_callbacks(fake_ros,monkeypatch):
    src,f=source([header(),*pair(),*pair(4,2,100.02)])
    monkeypatch.setattr(ros.NativeRos2Session,'_require_identity',lambda self,**kw:None)  # TEST ONLY, never accreditation
    session=ros.NativeRos2Session(observation_source=src)
    assert not fake_ros[3]
    raw=session.observe(timeout_s=.1)
    binding=ros.MotionBinding('a'*64,'b'*64,'2'*48,pose_reference_frame='odom',pose_reference_sha256='c'*64)
    # This test checks transfer/conversion only, with an explicitly synthetic
    # verifier. Raw source accreditation is exercised by test_rover_pulse_guards.
    monkeypatch.setattr(session,'validate_observation',lambda raw:{'binding_sha256':fingerprint(asdict(binding))})
    adapter=ros.Ros2RoverAdapter(session,binding=binding,clock=src.clock)
    monkeypatch.setattr(ros,'assert_execution_authority',lambda interface:None)
    adapter.capabilities={'session_id':SESSION}
    obs=adapter.observe(timeout_s=.1)
    assert obs.status_publisher_gid=='1'*48 and obs.odometry_publisher_gid=='2'*48
    assert obs.motion_provenance_sha256 and obs.status_provenance_sha256
    assert obs.motion_received_monotonic_s<obs.observation_transfer_monotonic_s
    assert raw['sample_gid_source']=='RCLCPP_MESSAGE_INFO_PER_SAMPLE'


def test_physical_factory_guard_precedes_receiver_start(monkeypatch):
    receiver=Mock();factory=ros.physical_adapter_factory({},lambda:{},ros.MotionBinding('1'*64,'2'*64,'3'*48),
        call_timeout_s=.1,observation_source_factory=receiver)
    with pytest.raises(RuntimeError,match='BLOCKED'):factory(Mock())
    receiver.assert_not_called()


def configure_graph(fake_ros):
    rclpy,node,_,_=fake_ros;rclpy.spin_once=Mock()
    node.get_topic_names_and_types=lambda:[(ros.STATUS,['ardupilot_msgs/msg/Status']),
        (ros.ODOMETRY,['nav_msgs/msg/Odometry']),(ros.VELOCITY,['geometry_msgs/msg/TwistStamped'])]
    node.get_service_names_and_types=lambda:[(ros.MODE,['ardupilot_msgs/srv/ModeSwitch'])]
    node.get_publishers_info_by_topic=lambda topic:[NS(endpoint_gid=bytes.fromhex('9'*48))]
    node.create_publisher.return_value.get_subscription_count=lambda:1
    node.create_client.return_value.service_is_ready=lambda:True


@pytest.mark.parametrize('fault',[None,'disconnect','cancel','close_failure','no_control_close_failure'])
def test_existing_public_worker_uses_stream_and_retains_uncertain_reservation(ground_setup,fake_ros,monkeypatch,fault):
    from tools import rover_ground_executor as g,vehicle_execution_lock as locks
    from tools.rover_control import Reply
    from tests.test_rover_ground_executor import admit
    configure_graph(fake_ros)
    # Explicit TEST source guard only. Neither real policy nor accreditation is changed.
    monkeypatch.setattr(ros.NativeRos2Session,'_require_identity',lambda self,**kw:None)
    rows=[header()];sequence=2
    for index in range(1,7):
        rows+=pair(sequence,index,100.+index*.2+(.6 if index>=4 else 0.),mode=4 if index>=5 else 15);sequence+=2
    rows.append(envelope('footer',sequence,reader_closed=True,counts={'/ap/v3/status':6,'/rover1/odometry':6}))
    src,f=source(rows);commands=[];cancel=[False]
    if fault=='no_control_close_failure':
        src,f=source([header(),*pair(),envelope('footer',4,reader_closed=True,counts={'/ap/v3/status':1,'/rover1/odometry':1})]);cancel[0]=True
    def factory(journal):
        src.journal=journal
        native=ros.NativeRos2Session(identity_guard=NS(expected={'lifecycle_id':SESSION}),observation_source=src,resource_timeout_s=1)
        binding=ros.MotionBinding('a'*64,'b'*64,'2'*48,pose_reference_frame='odom',pose_reference_sha256='c'*64)
        native.validate_observation=lambda raw:{'binding_sha256':fingerprint(asdict(binding))}  # SYNTHETIC verifier
        real_probe=native._probe
        def probe(**kw):
            caps=real_probe(**kw);caps['execution_kind']='SYNTHETIC_TEST_DOUBLE';return caps
        native._probe=probe
        def exchange(command,**kw):
            commands.append(command)
            if command['endpoint']==ros.VELOCITY and command['payload']['twist']['linear']['x']>0:
                if fault=='disconnect':f.rows=[]
                if fault=='cancel':cancel[0]=True
            if command['endpoint']==ros.MODE and command['payload']['mode']==4:
                # Synthetic future delivery follows the command, not a fixed
                # number of reads (the guarded path can reuse its current pair).
                for row in f.rows:
                    if isinstance(row,dict) and row.get('event')=='sample' and row.get('topic')==ros.STATUS:
                        row['body']['mode']=4
            return Reply(True,0,{'status':True,'curr_mode':4} if command['endpoint']==ros.MODE else None)
        native._exchange=exchange  # ONLY order transport is substituted, read/adapter/core/worker are real
        if fault in {'close_failure','no_control_close_failure'}:f.rc=2
        return ros.Ros2RoverAdapter(native,binding=binding,clock=src.clock,journal=journal)
    admitted=admit(ground_setup)
    result=g.run_ground_worker(admitted['run_id'],admitted['launch_token'],adapter_factory=factory,
        readiness=lambda **kw:{'ready':True},cancelled=lambda:cancel[0])
    assert 'capabilities' in result,result.get('error_evidence')
    assert result['capabilities']['session_id']==SESSION
    assert result['capabilities']['observation_source']['metadata_source']=='RCLCPP_MESSAGE_INFO_PER_SAMPLE'
    assert result['capabilities']['odometry_publisher_gids']==['2'*48]  # NOT the graph candidate 9...
    if fault is None:assert result['result']['stop']['stationary_observed']
    if fault=='disconnect':assert not result['result']['stop']['stationary_observed']
    if fault=='cancel':assert 'CANCELLED' in str(result['result']['error_evidence'])
    assert bool(commands)==(fault!='no_control_close_failure')
    assert locks.restriction('v3')['state']=='UNCONFIRMED'  # still armed or closure uncertain; never auto-disarm
    if fault in {'close_failure','no_control_close_failure'}:assert result['transport_close']['status']=='UNCERTAIN'
    assert g.query_ground_trial(admitted['run_id'])['status']=='UNCONFIRMED'
