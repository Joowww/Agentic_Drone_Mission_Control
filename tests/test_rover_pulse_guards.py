"""Synthetic current clocks/transports only. Archived bytes shape the fixtures.

No SDK, ROS/DDS, subprocess, signal or vehicle operation. Mutated copies are
explicitly synthetic observations, never new evidence about the real session.
"""
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
import hashlib,json,math
import pytest

from tools import rover_environment_identity as identity,rover_ground_executor as ground,vehicle_execution_lock as locks
from tools.rover_control import PulseSafety,RoverLimits,RoverControlCore,Observation,Reply
from tools.rover_ros2_adapter import Ros2RoverAdapter,MotionBinding,NativeRos2Session,MODE,DISARM
from planning.artifact_store import fingerprint,sha256
from tests.test_rover_ground_executor import setup

HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_terminal_authorized_capture_2026_10_30/61282dad-fbbd-4256-bc8a-79739c182dba'
SESSION='22222222-2222-4222-8222-222222222222'


class Clock:
    def __init__(self,now=0.):self.now=now
    def monotonic(self):return self.now
    def sleep(self,dt):self.now+=dt


@pytest.fixture
def current_source():
    old='569e177e-254a-4e95-af50-8c1df5563f6b'
    def read(p):return json.loads(p.read_text().replace(old,SESSION))
    index=read(HISTORY/'sdk-file-index.json');paths={r['path']:HISTORY/r['archive_path'] for r in index}
    prefix='/tmp/tfg_diagnostic_agents/'+SESSION;raw='/tmp/tfg-rover-passive-validation-'+SESSION
    monitor=read(paths[prefix+'/capture/monitor.json'])
    for k in ('finished_monotonic','cleanup_request','cleanup_result'):monitor.pop(k,None)
    monitor.update(phase='OBSERVING',closure_requested=False)
    lines=paths[prefix+'/capture/sockets.jsonl'].read_text().replace(old,SESSION).splitlines(keepends=True)[:24]
    sockets=''.join(lines);monitor['socket_inventory'].update(snapshots=24,incomplete_snapshots=0,error=None,journal_bytes_written=len(sockets.encode()))
    records=[json.loads(l.replace(old,SESSION)) for l in paths[raw+'/journal.jsonl'].read_text().splitlines()]
    latest={}
    for row in records:
        if row['event']=='sample':latest['status' if row['topic']=='/ap/v3/status' else 'odometry']=row
    observations={'sample_gid_source':'RCLCPP_MESSAGE_INFO_PER_SAMPLE','sample_provenance':{}}
    for kind,row in latest.items():
        text=json.dumps(row);meta=row['sample'];receipt=meta['receipt']['steady_ns']/1e9
        observations.update({kind:row['body'],kind+'_publisher_gid':meta['message_publisher_gid'],kind+'_received_monotonic_s':receipt})
        observations['sample_provenance'][kind]={'raw_record':text,'raw_sample':meta,'sample_sha256':hashlib.sha256(text.encode()).hexdigest(),'receipt':receipt}
    expected=read(HISTORY/'start-lifecycle/rover_environment_reference.json')
    expected={**expected,'vehicle_id':'rover_01','interface':'v3','namespace':'/rover1',
        'launch_process':{k:monitor[k2][k] for k,k2 in []}}
    expected['launch_process']=read(paths[prefix+'/launch.json'])['process']
    expected['launch_sha256']=expected.get('launch_sha256','b'*64)
    expected['execution']=read(HISTORY/'start-lifecycle/operation.json')['environment_execution']
    clock=Clock(34961.22)
    clock_context={'boot_id':latest['status']['client_process']['boot_id'],'time_namespace':latest['status']['client_process']['time_namespace']}
    body={'schema':'tfg.rover-body-review/1','pose_frame':'odom','body_frame':'base_link','linear_unit':'m/s',
        'angular_unit':'rad/s','positive_x':'FORWARD','positive_yaw':'ROS_CCW','source_hashes':{'SYNTHETIC_REVIEWED_SOURCE':'a'*64}}
    body['envelope']={k:v for k,v in asdict(safety()).items() if k!='review_sha256'}
    consumer=read(HISTORY/'transport-consumer.json')
    expected['source_contract']={'clock_context':clock_context,'max_target_age_s':5.,'max_sample_age_s':.5,
        'status_gid':observations['status_publisher_gid'],'odometry_gid':observations['odometry_publisher_gid'],
        'mav_sysid':3,'ros_domain_id':0,'model_entity':67,'model_entities':consumer['model_entities']['entities'],
        'pose_frame':'odom','body_review_sha256':identity.digest(body),'binding_sha256':'e'*64}
    expected['source_contract']['artifact_hashes']={k:monitor[k]['library_sha256'] for k in ('agent','identity_bridge','model_source')}
    processes={}
    for p in [expected['launch_process'],monitor['monitor'],monitor['agent'],monitor['identity_bridge'],monitor['model_source'],latest['status']['client_process'],{'pid':999,'start_ticks':1,'boot_id':clock_context['boot_id']},
              {'pid':2858,'start_ticks':3478984,'boot_id':clock_context['boot_id']}]:processes[str(p['pid'])]={k:p[k] for k in ('pid','start_ticks','boot_id')}
    current={'context_sha256':identity.digest(expected),'installed_launch_sha256':expected['launch_sha256'],'environment':expected['environment'],
        'record':{'context_sha256':identity.digest(expected),'state':'OBSERVING','worker':processes['999']},
        'process_clock_scope':'CONTAINER_PROC_BOOT_AND_MONOTONIC','processes':processes,
        'source_evidence':{'schema':'tfg.rover-current-source/1','context_sha256':identity.digest(expected),'clock_context':clock_context,
            'environment_execution':expected['execution'],
            'collection_started_monotonic':clock.now-.01,'observed_monotonic':clock.now,'monitor':monitor,'trace':paths[prefix+'/capture/trace.log'].read_text().replace(old,SESSION),
            'sockets':sockets,'ros_domain_id':0,'rpc':[r for r in records if r['event'] in ('rpc_request','rpc_reply')],
            'catalog':next(r for r in records if r['event']=='scene_catalog'),'frame_samples':[{'kind':'sample','topic':'/rover1/odometry',
                'frame_id':latest['odometry']['body']['header']['frame_id'],'child_frame_id':latest['odometry']['body']['child_frame_id']}],
            'launch_log':paths['/tmp/tfg_demo.log'].read_text(),'observations':observations,'body_review':body,'current_source_hashes':body['source_hashes']}}
    guard=identity.RoverEnvironmentGuard(expected,lambda:deepcopy(current),clock=clock,clock_context=lambda:clock_context)
    return guard,current,clock


def test_current_raw_joins_are_checked_without_promoting_historical_monitor(current_source):
    guard,current,clock=current_source
    result=guard.require_motion_source()
    assert result['coverage']=='CURRENT_SAMPLED_SOURCE_BINDING' and not result['movement_authorized']
    current['source_evidence'].pop('observations')  # receiver data unavailable, same current target
    assert guard.require_stop_target()['target_sha256']==result['target_sha256']


@pytest.mark.parametrize('bad',['old','clock','closed','process','gid','rpc','body','sample_hash','context','partial','domain'])
def test_current_source_rejects_unknown_or_contradictory_proof(current_source,bad):
    guard,c,clock=current_source;e=c['source_evidence']
    if bad=='old':clock.now+=10
    elif bad=='clock':e['clock_context']={**e['clock_context'],'time_namespace':'OTHER'}
    elif bad=='closed':e['monitor']['phase']='CLOSED'
    elif bad=='process':c['processes']['2858']['start_ticks']+=1
    elif bad=='gid':e['observations']['status_publisher_gid']='f'*48
    elif bad=='rpc':e['rpc'][1]['values']['MAV_SYSID']=99
    elif bad=='body':e['body_review']['positive_x']='REVERSE'
    elif bad=='sample_hash':e['observations']['sample_provenance']['status']['sample_sha256']='0'*64
    elif bad=='context':c['context_sha256']='0'*64
    elif bad=='partial':e['sockets']=e['sockets'][:-10]
    else:e['ros_domain_id']=9
    with pytest.raises((RuntimeError,ValueError,KeyError)):guard.require_motion_source()


def safety(binding='e'*64):
    return PulseSafety('a'*64,binding,'odom',.1,.25,.1,.05,.1,.001,.01,1.,.3,.2,.05,20.,1.)


class Adapter:
    """Explicitly synthetic body/kinematics and authoritative target checks."""
    def __init__(self,clock):
        self.clock=clock;self.x=0.;self.v=0.;self.mode=15;self.armed=True;self.n=0;self.commands=[];self.failure=None;self.closed=False
        self.target=True;self.reads_after_send=0
    def observe(self,*,timeout_s):
        self.n+=1
        if self.failure=='data' and self.commands:raise TimeoutError('SYNTHETIC_DATA_LOSS')
        if self.failure=='identity' and self.commands:self.target=False;raise RuntimeError('SYNTHETIC_IDENTITY_LOSS')
        self.clock.sleep(.001);self.x+=self.v*.001
        if self.failure=='displacement' and self.commands:self.x=1.
        return Observation('rover_01','v3',1,self.mode,self.armed,False,True,(),self.clock.now,self.n,self.n,
            (self.v,0.,0.),(0.,0.,0.),'/model/rover1/odometry','base_link',self.clock.now,
            position_m=(self.x,0.,0.),orientation_xyzw=(0.,0.,0.,1.),pose_frame='odom',pose_reference_validated=True,
            status_publisher_gid='1'*48,odometry_publisher_gid='2'*48,observation_provenance_sha256='e'*64)
    def watch(self,*,timeout_s):
        self.x+=self.v*.05
        return self.observe(timeout_s=timeout_s)
    def require_stop_target(self):
        if not self.target:raise RuntimeError('SYNTHETIC_TARGET_CHANGED')
    def exchange(self,command,*,timeout_s):
        self.require_stop_target();self.commands.append(command)
        if command['kind']=='topic':
            self.v=command['payload']['twist']['linear']['x']
            if self.failure=='send' and self.v:raise TimeoutError('SYNTHETIC_SEND_UNCERTAIN')
            return Reply(True,0)
        self.mode=4;self.v=0.;return Reply(True,0,{'status':True,'curr_mode':4})


@pytest.mark.parametrize('failure',[None,'data','identity','displacement','send','cancel'])
def test_monitored_core_pulse_stop_and_failures(failure):
    clock=Clock(1.);adapter=Adapter(clock);adapter.failure=failure
    core=RoverControlCore(RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01),adapter=adapter,clock=clock)
    result=core.move_for(.05,0.,.3,safety=safety(),cancelled=lambda:failure=='cancel' and bool(adapter.commands))
    assert sum(c['kind']=='topic' and c['payload']['twist']['linear']['x']>0 for c in adapter.commands)==1
    if failure=='identity':assert len(adapter.commands)==1 and result['stop']['status']=='UNCONFIRMED'
    else:assert [c['endpoint'] for c in adapter.commands][-2:]==['/ap/v3/cmd_vel','/ap/v3/mode_switch']
    if failure is None:assert result['status']=='STOP_OBSERVED' and result['observation_samples']
    elif failure=='data':assert result['stop']['status']=='UNCONFIRMED' and result['stop']['stationary_observed'] is False
    assert not result['motion_application_confirmed']


def test_missing_review_or_unknown_envelope_cannot_emit():
    clock=Clock(1);adapter=Adapter(clock);core=RoverControlCore(RoverLimits(.05,.1,3,1,5,.5,.01,.01),adapter=adapter,clock=clock)
    assert core.move_for(.05,0,1)['status']=='NOT_ATTEMPTED' and not adapter.commands
    with pytest.raises(Exception):replace(safety(),max_slope_rad=None)
    with pytest.raises(Exception):replace(safety(),clear_radius_m=.1)


def test_current_target_cannot_be_replaced_during_data_loss(current_source):
    guard,current,_=current_source;guard.require_motion_source();current['source_evidence'].pop('observations')
    current['processes']['2858']['start_ticks']+=1
    with pytest.raises(RuntimeError):guard.require_stop_target()


class CurrentSession:
    """Actual current verifier, adapter and executor; all I/O/kinematics synthetic."""
    synthetic_model=True
    def __init__(self,guard,current,clock,binding,review):
        self.guard,self.current,self.clock,self.binding,self.review=guard,current,clock,binding,review
        self.mode=15;self.armed=True;self.v=0.;self.x=0.;self.n=0;self.commands=[];self.order=[];self.failure=None
    def probe(self,**kw):
        proof=self.guard.require_motion_source();c=self.guard.expected['source_contract']
        return {'session_id':SESSION,'observation_source':{'max_samples':20,'duration_s':120,'remaining_sample_pairs':9-self.n},
            'status_type':'ardupilot_msgs/msg/Status','odometry_type':'nav_msgs/msg/Odometry',
            'mode_type':'ardupilot_msgs/srv/ModeSwitch','velocity_type':'geometry_msgs/msg/TwistStamped','mode_available':True,
            'velocity_subscribers':1,'status_publishers':1,'odometry_publisher_gids':[self.binding.odometry_publisher_gid],
            'disarm_available':True,'disarm_type':'ardupilot_msgs/srv/ArmMotors','target_sha256':proof['target_sha256'],
            'source_contract_sha256':identity.digest(c),'body_review_sha256':c['body_review_sha256'],'envelope_sha256':proof['envelope_sha256']}
    def observe(self,**kw):
        if self.failure=='data' and self.commands:raise TimeoutError('SYNTHETIC_DATA_LOSS')
        if self.failure=='identity' and self.commands:self.current['processes']['2858']['start_ticks']+=1
        if self.failure=='disarm_data' and not self.armed:raise TimeoutError('SYNTHETIC_POST_DISARM_DATA_LOSS')
        if self.n>=9:raise TimeoutError('SYNTHETIC_EXISTING_PER_STREAM_QUOTA')
        self.n+=1;self.clock.sleep(.001);self.x+=self.v*.001
        raw=deepcopy(self.current['source_evidence']['observations'])
        for kind in ('status','odometry'):
            data=raw[kind];stamp={'sec':self.n,'nanosec':0};data['header']['stamp']=stamp
            if kind=='status':data.update(mode=self.mode,armed=self.armed,flying=False,external_control=True,failsafe=[])
            else:
                data['pose']['pose']['position']={'x':self.x,'y':0.,'z':0.}
                data['pose']['pose']['orientation']={'x':0.,'y':0.,'z':0.,'w':1.}
                data['twist']['twist']['linear']={'x':self.v,'y':0.,'z':0.}
                data['twist']['twist']['angular']={'x':0.,'y':0.,'z':0.}
            provenance=raw['sample_provenance'][kind];row=json.loads(provenance['raw_record'])
            row['body']=data;row['sample']['header']=data['header'];row['sample']['receipt']['steady_ns']=int(self.clock.now*1e9)
            row['receipt_steady_ns']=int(self.clock.now*1e9)
            text=json.dumps(row);receipt=row['sample']['receipt']['steady_ns']/1e9
            provenance.update(raw_record=text,raw_sample=row['sample'],receipt=receipt,sample_sha256=hashlib.sha256(text.encode()).hexdigest())
            raw[kind+'_received_monotonic_s']=receipt
        e=self.current['source_evidence'];e.update(observations=deepcopy(raw),observed_monotonic=self.clock.now,collection_started_monotonic=self.clock.now-.001)
        return raw
    def watch(self,**kw):
        self.x+=self.v*.05
        if self.failure in ('data','identity'):return self.observe(**kw)
        # Synthetic pipe with no newly delivered pair inside this short pulse.
        # Cached receipts are preserved, and the core still checks age/progress.
        return deepcopy(self.current['source_evidence']['observations'])
    def validate_observation(self,raw):return self.guard.require_observation(raw)
    def require_stop_target(self):return self.guard.require_stop_target()
    def exchange(self,command,**kw):
        locks.assert_execution_authority('v3')
        stopping=command['endpoint']==MODE or command.get('payload',{}).get('twist',{}).get('linear',{}).get('x')==0
        if stopping:self.guard.require_stop_target()
        else:self.guard.require_motion_source()
        self.commands.append(command);self.order.append(command['endpoint'])
        if command['endpoint']==DISARM:
            if self.failure=='disarm_command':raise TimeoutError('SYNTHETIC_DISARM_UNCERTAIN')
            self.armed=False;return Reply(True,0,{'result':True})
        if command['endpoint']==MODE:
            if self.failure=='hold':return Reply(True,0,{'status':False,'curr_mode':15})
            self.mode=4;self.v=0.;return Reply(True,0,{'status':True,'curr_mode':4})
        self.v=command['payload']['twist']['linear']['x']
        if self.failure=='send' and self.v:raise TimeoutError('SYNTHETIC_PUBLICATION_UNCERTAIN')
        return Reply(True,0)
    def close(self):
        self.order.append('close_transport')
        if self.failure=='close':raise OSError('SYNTHETIC_CLOSE_UNCERTAIN')
        if self.failure=='interrupt':raise KeyboardInterrupt('SYNTHETIC_CLOSE_INTERRUPTED')


def prepare_job(setup,current_source,*,failure=None,finalize=True,duration=.2):
    path,*_=setup;guard,current,clock=current_source
    binding=MotionBinding('1'*64,'2'*64,guard.expected['source_contract']['odometry_gid'],pose_reference_frame='odom',pose_reference_sha256='4'*64)
    review=safety(fingerprint(asdict(binding)));body=current['source_evidence']['body_review']
    body['envelope']={k:v for k,v in asdict(review).items() if k!='review_sha256'}
    c=guard.expected['source_contract'];c['binding_sha256']=review.binding_sha256;c['body_review_sha256']=identity.digest(body)
    review=replace(review,review_sha256=c['body_review_sha256'])
    ctx=identity.digest(guard.expected);current['context_sha256']=ctx;current['record']['context_sha256']=ctx;current['source_evidence']['context_sha256']=ctx
    proof=guard.require_motion_source();limits=RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01)
    request={'kind':'ROVER_PULSE_V1','limits':asdict(limits),'safety':asdict(review),'forward_mps':.05,'yaw_rate_rad_s':0.,'duration_s':duration,
        'context':{'lifecycle_id':SESSION,'target_sha256':proof['target_sha256'],'source_contract_sha256':identity.digest(c),
            'body_review_sha256':c['body_review_sha256'],'destinations':{'velocity':{'endpoint':'/ap/v3/cmd_vel','type':'geometry_msgs/msg/TwistStamped','frame':'base_link'},
            'stop':{'endpoint':'/ap/v3/mode_switch','type':'ardupilot_msgs/srv/ModeSwitch','mode':4}}}}
    if finalize:
        request['finalization']={'kind':'DISARM_AFTER_OBSERVED_STOP_V1','timeout_s':3.}
        request['context']['destinations']['finalization']={'endpoint':'/ap/v3/arm_motors','type':'ardupilot_msgs/srv/ArmMotors','arm':False}
    authorization={'mission_sha256':sha256(path.read_bytes()),'request_fingerprint':fingerprint(request),'statement':'SYNTHETIC TEST ONLY, NO REAL AUTHORIZATION'}
    admitted=ground.admit_ground_trial(path,'pulse-synthetic',request,authorization)
    assert admitted['status']=='ADMITTED',admitted
    job=ground.query_ground_trial(admitted['run_id'])
    assert 'launch_token' not in admitted
    start={'run_id':admitted['run_id'],'input_sha256':admitted['input_sha256'],**ground._read(ground.directory(admitted['run_id']),'job.json')['pulse_binding'],
        'statement':'Explicit SYNTHETIC start, one attempt only'}
    session=CurrentSession(guard,current,clock,binding,review);session.failure=failure
    factory=lambda journal:Ros2RoverAdapter(session,binding=binding,clock=clock,journal=journal)
    return admitted,start,session,factory


@pytest.mark.parametrize('failure',[None,'data','identity','send','hold','disarm_command','disarm_data','close'])
def test_full_protected_current_guard_pulse_stop_finalization_and_close(setup,current_source,failure):
    admitted,start,session,factory=prepare_job(setup,current_source,failure=failure)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    positive=[c for c in session.commands if c['endpoint']=='/ap/v3/cmd_vel' and c['payload']['twist']['linear']['x']>0]
    assert len(positive)==1,result
    assert session.order[-1]=='close_transport'
    if failure in (None,'send'):
        assert result['finalization']['status']=='DISARMED_STATIONARY_OBSERVED',result
        assert session.order.index(DISARM)>session.order.index(MODE)
        assert locks.restriction('v3') is None
        if failure=='send':
            assert result['status']=='PULSE_ABORTED_CLOSURE_OBSERVED'
            assert result['result']['error_evidence'] and not result['result']['motion_application_confirmed']
    else:
        assert result['closure']['reservation_release']=='RETAINED',result
        assert locks.restriction('v3')['owner_id']==admitted['run_id']
        if failure in ('data','identity','hold'):assert DISARM not in session.order
        if failure=='identity':assert len(session.commands)==1
    again=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert again['status']=='BLOCKED' and len(positive)==1


def test_explicit_pulse_start_owner_scope_and_default_policy(setup,current_source,monkeypatch):
    admitted,start,session,factory=prepare_job(setup,current_source)
    bad={**start,'session_id':'33333333-3333-4333-8333-333333333333'}
    with pytest.raises(ValueError):ground.start_ground_trial(admitted['run_id'],bad,adapter_factory=factory)
    assert not session.commands
    monkeypatch.setattr(ground,'OPERATIONAL_ROVER_ENABLED',False)
    assert ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory)['status']=='BLOCKED'


def test_stopped_but_armed_pulse_never_releases_reservation(setup,current_source):
    admitted,start,session,factory=prepare_job(setup,current_source,finalize=False)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert result['result']['stop']['status']=='STATIONARY_OBSERVED',result
    assert session.armed and DISARM not in session.order and locks.restriction('v3') is not None
    assert result['status']=='UNCONFIRMED'


def test_interrupted_transport_close_retains_uncertainty(setup,current_source):
    admitted,start,session,factory=prepare_job(setup,current_source,failure='interrupt')
    with pytest.raises(KeyboardInterrupt):ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert locks.restriction('v3')['owner_id']==admitted['run_id']
    assert ground._read(ground.directory(admitted['run_id']),'job.json')['job_state']=='UNCONFIRMED'


@pytest.mark.parametrize('fault',['stale','frozen','gid','mode','failsafe','slope','heading','speed','units','frame'])
def test_continuous_watch_aborts_and_stops_on_each_violation(fault):
    clock=Clock(1.);adapter=Adapter(clock);original=adapter.watch
    def watch(**kw):
        obs=original(**kw)
        changes={
            'stale':{'motion_received_monotonic_s':0.},
            'frozen':{'status_source_ns':2,'velocity_source_ns':2},
            'gid':{'status_publisher_gid':'3'*48},'mode':{'mode':0},'failsafe':{'failsafe':(1,)},
            'slope':{'orientation_xyzw':(math.sin(.2),0.,0.,math.cos(.2))},
            'heading':{'orientation_xyzw':(0.,0.,math.sin(.2),math.cos(.2))},
            'speed':{'linear_mps':(.2,0.,0.)},'units':{'linear_unit':'km/h'},'frame':{'pose_frame':'other'}}
        return replace(obs,**changes[fault])
    adapter.watch=watch
    result=RoverControlCore(RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01),adapter=adapter,clock=clock).move_for(.05,0.,.3,safety=safety())
    assert result['error_evidence'] and result['stop']['stationary_observed']
    assert len(adapter.commands)==3  # one publication, zero, HOLD; no reattempt


def test_lost_pre_stop_read_cannot_exhaust_command_budget():
    clock=Clock(1.);adapter=Adapter(clock);original=adapter.observe
    timeouts=[]
    def failing(**kw):
        timeouts.append(kw['timeout_s']);clock.sleep(kw['timeout_s'])
        raise TimeoutError('SYNTHETIC_READ_EXHAUSTS_ITS_SHARE')
    adapter.observe=failing
    result=RoverControlCore(RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01),adapter=adapter,clock=clock).stop()
    assert result['status']=='UNCONFIRMED' and not result['stationary_observed']
    assert [c['endpoint'] for c in adapter.commands]==['/ap/v3/cmd_vel',MODE]
    assert result['pre_stop_observation_error'] and timeouts[0]<5.


def test_publication_latency_counts_toward_nonzero_deadline():
    clock=Clock(1.);adapter=Adapter(clock);exchange=adapter.exchange;attempts=[]
    def delayed(command,**kw):
        attempts.append((command,clock.now))
        result=exchange(command,**kw)
        if adapter.v:clock.sleep(.2)
        return result
    adapter.exchange=delayed
    result=RoverControlCore(RoverLimits(.05,.1,3.,1.,5.,.5,.01,.01),adapter=adapter,clock=clock).move_for(.05,0.,.3,safety=safety())
    assert result['status']=='STOP_OBSERVED'
    # One preliminary stop observation (1ms) precedes the zero; it does not
    # grant another .2s of nonzero wait after the publication returns.
    assert attempts[1][1]-attempts[0][1]<=.302


def test_actual_native_exchange_allows_only_same_current_stop_after_data_loss(setup,current_source,monkeypatch):
    from tools import rover_ros2_adapter as ros
    admitted,_,_,_=prepare_job(setup,current_source)
    guard,current,_=current_source;guard.require_motion_source();current['source_evidence'].pop('observations')
    native=NativeRos2Session.__new__(NativeRos2Session);native.identity_guard=guard;native.cancelled=lambda:True
    native._bound_owner=admitted['run_id']
    root=ground.directory(admitted['run_id']);job=ground._read(root,'job.json')
    job.update(job_state='RUNNING',worker=locks.process_identity());locks.atomic_json(root/'job.json',job)
    from types import SimpleNamespace as NS
    destination=guard._verified_target_cache[1][0]['target']['destinations']['/ap/v3/cmd_vel']['reader_guid']+'0'*16
    native.context=NS(get_domain_id=lambda:0)
    native.publisher=NS(get_subscription_count=lambda:1)
    native.node=NS(get_subscriptions_info_by_topic=lambda topic:[NS(endpoint_gid=bytes.fromhex(destination),topic_type='geometry_msgs/msg/TwistStamped')])
    sent=[];native._exchange=lambda c,**kw:sent.append(c) or Reply(True,0)
    with locks.execution_scope(admitted['run_id'],'v3'):
        native.exchange(RoverControlCore.velocity_message(0.,0.),timeout_s=1.)
        assert len(sent)==1
        current['processes']['2858']['start_ticks']+=1
        with pytest.raises(RuntimeError):native.exchange(RoverControlCore.velocity_message(0.,0.),timeout_s=1.)
    assert len(sent)==1


def test_prepublication_cancel_does_not_release_unresolved_armed_owner(setup,current_source):
    admitted,start,session,factory=prepare_job(setup,current_source)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True},cancelled=lambda:True)
    assert not session.commands and session.armed and result['status']=='UNCONFIRMED'
    assert locks.restriction('v3')['owner_id']==admitted['run_id']


def test_full_cancellation_stops_then_disarms_before_close(setup,current_source):
    admitted,start,session,factory=prepare_job(setup,current_source)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True},cancelled=lambda:bool(session.commands))
    assert result['result']['stop']['stationary_observed']
    assert session.order.index(MODE)<session.order.index(DISARM)<session.order.index('close_transport')
    # The trial aborted; distinct current stop/disarm/closure evidence resolves
    # the final vehicle state without turning the failed trial into success.
    assert result['status']=='PULSE_ABORTED_CLOSURE_OBSERVED' and locks.restriction('v3') is None


def test_durable_completion_failure_after_close_retains_reservation(setup,current_source,monkeypatch):
    admitted,start,session,factory=prepare_job(setup,current_source)
    original=locks.atomic_json;failed=[False]
    def fail_final(path,value):
        if path.name=='job.json' and value.get('job_state')=='FINISHED' and not failed[0]:
            failed[0]=True;raise OSError('SYNTHETIC_FINAL_PERSISTENCE_LOSS')
        return original(path,value)
    monkeypatch.setattr(locks,'atomic_json',fail_final)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert failed[0] and result['status']=='UNCONFIRMED'
    assert session.order[-1]=='close_transport' and locks.restriction('v3') is not None


def test_immediate_timer_expiry_restores_deadline_owner(monkeypatch):
    from tools import rover_control as control
    calls=[];old_handler=object()
    monkeypatch.setattr(control.signal,'getitimer',lambda which:(0.,0.))
    monkeypatch.setattr(control.signal,'getsignal',lambda which:old_handler)
    monkeypatch.setattr(control.signal,'signal',lambda which,handler:calls.append(handler))
    def arm(which,value,*rest):
        if value:raise TimeoutError('SYNTHETIC_IMMEDIATE_TIMER_EXPIRY')
    monkeypatch.setattr(control.signal,'setitimer',arm)
    with pytest.raises(TimeoutError):
        with control.synchronous_deadline(.01):raise AssertionError('backend must not run')
    assert control._deadline_owner.get() is False and calls[-1] is old_handler


@pytest.mark.parametrize('cleanup_returncode',[0,1])
def test_resolved_pulse_then_existing_protected_infrastructure_close(setup,current_source,monkeypatch,cleanup_returncode):
    from tools import simulation_lifecycle as lifecycle
    admitted,start,session,factory=prepare_job(setup,current_source)
    report=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    def backend(action,gui,fd,process,path):
        assert action=='stop' and not gui
        assert report['finalization']['disarmed_observed']
        assert session.order[-1]=='close_transport'
        assert ground.query_ground_trial(admitted['run_id'])['status']=='FINISHED'
        session.order.append('protected_lifecycle_stop')
        return cleanup_returncode  # synthetic cleanup only, never a subprocess
    monkeypatch.setattr(lifecycle,'_backend',backend)
    closed=lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover')
    assert closed['status']==('SUCCESS' if cleanup_returncode==0 else 'UNCONFIRMED')
    assert session.order[-1]=='protected_lifecycle_stop'
    assert (locks.restriction() is not None)==bool(cleanup_returncode)


def test_uncertain_ground_owner_does_not_bypass_lifecycle_restriction(setup,current_source,monkeypatch):
    from tools import simulation_lifecycle as lifecycle
    admitted,start,session,factory=prepare_job(setup,current_source,failure='data')
    ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    monkeypatch.setattr(lifecycle,'_backend',lambda *args:pytest.fail('must not bypass retained owner'))
    assert lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover')['status']=='BLOCKED'
    assert locks.restriction('v3')['owner_id']==admitted['run_id']


def test_candidate_three_seconds_cannot_exceed_existing_reader_quota(setup,current_source):
    admitted,start,session,factory=prepare_job(setup,current_source,duration=3.)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert not session.commands
    assert result['observation_budget']=={'remaining_pairs':9,'minimum_required_pairs':13,'guarantees_cadence':False}
    assert 'PULSE_OBSERVATION_QUOTA_INSUFFICIENT_OR_UNKNOWN' in str(result['error_evidence'])
