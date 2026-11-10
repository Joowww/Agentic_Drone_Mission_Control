"""Synthetic current session/clock/pipe and transport. Never SDK or ROS/DDS.

NativeRos2Session is constructed against fake_ros modules. Its exchange guard,
source/adapter/controller, executor and lifecycle are real; only transport I/O,
environment reader and the frozen synthetic descriptor boundary are doubles.
"""
from copy import deepcopy
from pathlib import Path
import json,os
from types import SimpleNamespace as NS
import pytest
from planning.artifact_store import fingerprint
from tools import rover_ground_executor as ground,rover_ros2_adapter as ros
from tools import rover_observation_stream as stream,simulation_lifecycle as lifecycle,vehicle_execution_lock as locks
from tools.rover_control import RoverControlCore,Reply,PulseSafety
from tests.test_rover_pulse_guards import current_source,prepare_job,SESSION
from tests.test_rover_ground_executor import setup
from tests.test_rover_transport_preparation import fake_ros


class Frames:
    """Bounded synthetic pipe delivery, same20/120s and10 per stream."""
    def __init__(self,current,clock,*,mode=15,armed=True,fault=None):
        self.current=current;self.clock=clock;self.mode=mode;self.armed=armed;self.v=0.;self.fault=fault
        self.sequence=0;self.pairs=0;self.rows=[];self.commands=[];self.released=False;self.requested=False
        self.stderr=b'';self.observed_return_code=None;self.force_ready=False;self.source=None
        e=current['source_evidence'];self.identity=json.loads(e['observations']['sample_provenance']['status']['raw_record'])['client_process']
        self.templates={k:json.loads(e['observations']['sample_provenance'][k]['raw_record']) for k in ('status','odometry')}
        self.enqueue({'event':'header','process':self.identity,'max_samples':20,'duration_s':120,'spacing_source_ns':500000000,'after_status':True,'clock_scope':'SAME_PROC_BOOT_AND_MONOTONIC'})
        for row in [*e['rpc'],e['catalog']]:self.enqueue(row)
        self.deliver_pair()
    def enqueue(self,row):
        self.sequence+=1;row=deepcopy(row)
        row.update(schema=stream.SCHEMA,session_id=SESSION,client_process=self.identity,sequence=self.sequence,movement_authorized=False,identity_verified=False)
        self.rows.append(json.dumps(row).encode())
    def deliver_pair(self):
        if self.pairs>=10:raise TimeoutError('SYNTHETIC_EXISTING_QUOTA_EXHAUSTED')
        self.pairs+=1;self.clock.sleep(.001)
        stamp={'sec':self.pairs,'nanosec':0}
        for kind in ('status','odometry'):
            row=deepcopy(self.templates[kind]);body=row['body'];body['header']['stamp']=stamp
            if kind=='status':body.update(mode=self.mode,armed=self.armed,flying=False,external_control=True,failsafe=[])
            else:
                body['pose']['pose'].update(position={'x':0.,'y':0.,'z':0.},orientation={'x':0.,'y':0.,'z':0.,'w':1.})
                body['twist']['twist'].update(linear={'x':self.v,'y':0.,'z':0.},angular={'x':0.,'y':0.,'z':0.})
            row['sample']['header']=body['header'];row['sample']['receipt']['steady_ns']=int(self.clock.now*1e9)
            self.enqueue(row)
        if self.pairs==10:
            self.enqueue({'event':'footer','reader_closed':True,'counts':{'/ap/v3/status':10,'/rover1/odometry':10},'termination':'SAMPLE_LIMIT'})
    def ready(self,timeout_s=0.):return self.force_ready
    def read(self,timeout_s):
        assert timeout_s>0
        if self.fault=='source' and self.commands and not self.requested:raise TimeoutError('SYNTHETIC_SOURCE_LOSS')
        if not self.rows:
            if self.requested:raise EOFError('SYNTHETIC_MISSING_FOOTER')
            self.deliver_pair()
        return self.rows.pop(0)
    def request_close(self,timeout_s):
        self.requested=True
        if self.fault!='close' and self.pairs<10:self.enqueue({'event':'footer','reader_closed':True,'counts':self.source.counts})
    def ended(self):return False
    def wait(self,timeout_s):
        self.observed_return_code=2 if self.fault in ('source','close') else 0
        if self.observed_return_code:self.stderr=b'TEST_ONLY TERMINAL WATCHDOG stage=CLOSE\n'
        return self.observed_return_code
    def release(self):self.released=True


def trial(setup,current_source,fake_ros,monkeypatch,*,fault=None,mode=15,armed=True,duration=.2,close=True,prepare=True,selection_mode="DIAGNOSTIC_SPACING_V1"):
    guard,current,clock=current_source;original=ground.admit_ground_trial
    def admission(path,key,request,auth,**kw):
        request=deepcopy(request)
        if prepare:
            request['preparation']={'kind':'GUIDED_ARM_AFTER_STATIONARY_V1','timeout_s':3.}
            request['context']['destinations']['preparation']={'mode':{'endpoint':ros.MODE,'type':'ardupilot_msgs/srv/ModeSwitch','mode':15},
                'arm':{'endpoint':ros.DISARM,'type':'ardupilot_msgs/srv/ArmMotors','arm':True}}
        if close:request['infrastructure_close']={'kind':'SAME_SESSION_INFRASTRUCTURE_V1'}
        auth={**auth,'request_fingerprint':fingerprint(request)}
        return original(path,key,request,auth,**kw)
    monkeypatch.setattr(ground,'admit_ground_trial',admission)
    admitted,start,_,_=prepare_job(setup,current_source,duration=duration)
    frames=Frames(current,clock,mode=mode,armed=armed,fault=fault)
    frames.cancelled=lambda:fault=='cancel' and any(c['endpoint']==ros.VELOCITY and c['payload']['twist']['linear']['x']>0 for c in frames.commands)
    def read_context(pid):return frames.identity if pid==frames.identity['pid'] else {**frames.identity,'pid':pid}
    source=stream.ObservationStream(frames,session_id=SESSION,identity=frames.identity,read_context=read_context,clock=clock,max_age_s=.5,selection_mode=selection_mode)
    frames.source=source
    # Provider has NO samples/RPC/catalog: these must come from the very pipe
    # consumed by the adapter. Context/trace/socket originals remain separate.
    def read_current():
        packet=deepcopy(current);e=packet['source_evidence']
        for key in ('observations','rpc','catalog','frame_samples'):e.pop(key,None)
        e.update(observed_monotonic=clock.now,collection_started_monotonic=clock.now-.000001)
        return packet
    _,node,_,callbacks=fake_ros
    node.get_topic_names_and_types=lambda:[(ros.STATUS,['ardupilot_msgs/msg/Status']),(ros.ODOMETRY,['nav_msgs/msg/Odometry']),(ros.VELOCITY,['geometry_msgs/msg/TwistStamped'])]
    node.get_service_names_and_types=lambda:[(ros.MODE,['ardupilot_msgs/srv/ModeSwitch']),(ros.DISARM,['ardupilot_msgs/srv/ArmMotors'])]
    node.get_node_names_and_namespaces=lambda:[('SYNTHETIC_ARDUPILOT','/ap/v3')]
    node.get_service_names_and_types_by_node=lambda name,namespace:node.get_service_names_and_types()
    node.get_publishers_info_by_topic=lambda topic:[NS(endpoint_gid=bytes.fromhex(guard.expected['source_contract']['odometry_gid']))]
    node.create_publisher.return_value.get_subscription_count=lambda:1
    node.create_client.return_value.service_is_ready=lambda:True
    fake_ros[2].get_domain_id=lambda:0
    destination=guard._verified_target_cache[1][0]['target']['destinations'][ros.VELOCITY]['reader_guid']+'0'*16
    node.get_subscriptions_info_by_topic=lambda topic:[NS(endpoint_gid=bytes.fromhex(destination),topic_type='geometry_msgs/msg/TwistStamped')]
    fake_ros[0].spin_once=lambda *args,**kw:None
    def exchange(native,command,**kw):
        locks.assert_execution_authority('v3');frames.commands.append(deepcopy(command))
        if command['endpoint']==ros.DISARM:
            arm=command['payload']['arm']
            if arm and fault=='arm_reject' or not arm and fault=='disarm_reject':return Reply(True,0,{'result':False})
            if not (arm and fault=='arm_unobserved'):frames.armed=arm
            if arm and fault=='arm_timeout':raise TimeoutError('SYNTHETIC_ARM_REPLY_LOST')
            return Reply(True,0,{'result':True})
        if command['endpoint']==ros.MODE:
            mode=command['payload']['mode']
            if mode==15 and fault=='mode_reject' or mode==4 and fault=='hold_reject':return Reply(True,0,{'status':False,'curr_mode':frames.mode})
            if not (mode==15 and fault=='mode_unobserved'):frames.mode=mode
            if mode==4:frames.v=0.
            return Reply(True,0,{'status':True,'curr_mode':frames.mode})
        frames.v=command['payload']['twist']['linear']['x']
        if frames.v:
            if fault=='source':frames.force_ready=True
            if fault=='identity':current['processes']['2858']['start_ticks']+=1
            if fault=='context':environment['container_boot_id']='DIFFERENT_SYNTHETIC_EXECUTION'
        return Reply(True,0)
    monkeypatch.setattr(ros.NativeRos2Session,'_exchange',exchange)  # ONLY transport I/O
    factory=ros.physical_adapter_factory(guard.expected,read_current, __import__('tools.rover_ros2_adapter',fromlist=['MotionBinding']).MotionBinding(
        '1'*64,'2'*64,guard.expected['source_contract']['odometry_gid'],pose_reference_frame='odom',pose_reference_sha256='4'*64),
        call_timeout_s=1.,clock=clock,cancelled=frames.cancelled,clock_context=lambda:guard.expected['source_contract']['clock_context'],
        observation_source_factory=lambda journal:(setattr(source,'journal',journal) or source))
    # Symbolic frozen descriptor fixture, not an accepted real preparation.
    descriptor={'lifecycle_id':SESSION,'selection_sha256':'d'*64,'fixture':'EXPLICITLY_SYNTHETIC'}
    from tools.rover_xrce_trace import selection
    monkeypatch.setattr(selection,'check_frozen_descriptor',lambda d: d if d==descriptor else (_ for _ in ()).throw(ValueError('synthetic descriptor changed')))
    start_path=locks.LOCK_ROOT.parent/'simulation_lifecycle'/SESSION/'operation.json';start_path.parent.mkdir(parents=True)
    original_start={'owner_id':SESSION,'action':'start','state':'FINISHED','profile':'two_drones_rover','diagnostic_agent':descriptor,'environment_execution':guard.expected['execution']}
    locks.atomic_json(start_path,original_start)
    target={'state':'STARTED','descriptor':descriptor,'operation_path':str(start_path)}
    locks.atomic_json(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json',target)
    environment=deepcopy(guard.expected['execution']);calls=[]
    def fence(expected):
        if expected!=environment:raise locks.VehicleBusy('SYNTHETIC_ENVIRONMENT_CHANGED')
    monkeypatch.setattr(lifecycle,'assert_environment_execution',fence)
    def backend(action,gui,fd,process,path):
        assert action=='stop' and not gui
        lease=locks.restriction();assert lease['closing_ground_trial']['owner_id']==admitted['run_id']
        assert locks.restriction('v3')['state']=='UNCONFIRMED'  # NEVER removed for cleanup
        calls.append(action)
        if fault=='interrupt':raise KeyboardInterrupt('SYNTHETIC_CLEANUP_INTERRUPTED')
        receipt={'success':True,'signals':[],'errors':[],'unattributed_auxiliaries':[],'diagnostic_coordination_errors':[],
            'remaining':[{'pid':123,'fixture':'SYNTHETIC'}] if fault=='cleanup_partial' else [],'observed_processes':[],
            'diagnostic_agent':{'selection':descriptor,'monitor':{'lifecycle_id':SESSION,'phase':'CLOSED','capture_complete':False},
                'monitor_exit':{'state':'PARENT_WAIT_STATUS_OBSERVED','return_code':1}}}
        path.write_text(json.dumps(receipt)+'\n')
        return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    return admitted,start,factory,source,frames,calls,environment


@pytest.mark.parametrize('fault',[None,'source','identity','hold_reject','disarm_reject','close','cleanup_partial','cancel'])
def test_complete_current_pipe_actor_pulse_stop_finalize_and_owned_cleanup(setup,current_source,fake_ros,monkeypatch,fault):
    admitted,start,factory,source,frames,calls,environment=trial(setup,current_source,fake_ros,monkeypatch,fault=fault)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True},cancelled=frames.cancelled)
    assert calls==['stop'],result
    assert max(source.counts.values())<=10 and frames.pairs<=10
    assert len([c for c in frames.commands if c['endpoint']==ros.VELOCITY and c['payload']['twist']['linear']['x']>0])==1,result
    assert 'observations' not in factory.__dict__  # no historical sample credential
    if fault in (None,'cancel'):
        assert result['finalization']['disarmed_observed'] and result['infrastructure_close']['status']=='SUCCESS'
        assert source.closed and source.footer and source.close_result['return_code']==0
        assert ground.query_ground_trial(admitted['run_id'])['status']=='FINISHED' and locks.restriction() is None
        assert result['infrastructure_close']['operation']['cleanup_receipt']['vehicle_stationary'] is None
        if fault=='cancel':assert result['status']=='PULSE_ABORTED_CLOSURE_OBSERVED'
    else:
        assert result['status']=='UNCONFIRMED' and locks.restriction('v3')['owner_id']==admitted['run_id']
        if fault=='identity':assert len(frames.commands)==1
        if fault in ('source','close'):
            assert source.close_result['return_code']==2 and 'TERMINAL WATCHDOG' in source.close_result['stderr']
        if fault=='cleanup_partial':assert result['infrastructure_close']['status']=='UNCONFIRMED'


@pytest.mark.parametrize('fault',[None,'arm_reject','arm_timeout','arm_unobserved'])
def test_guided_disarmed_arm_actor_and_full_close_fit_exact_existing_quota(setup,current_source,fake_ros,monkeypatch,fault):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch,fault=fault,armed=False)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert calls==['stop'],result
    assert result['preparation']['arm_attempted'] and frames.commands[0]['payload']=={'arm':True}
    assert result['finalization']['disarmed_observed'],result
    assert locks.restriction() is None and frames.pairs<=10
    if fault is None:assert result['preparation']['status']=='GUIDED_ARMED_STATIONARY_OBSERVED'
    else:
        assert result['status']=='PULSE_ABORTED_CLOSURE_OBSERVED'
        assert any(c['endpoint']==ros.VELOCITY and c['payload']['twist']['linear']['x']==0 for c in frames.commands)


def test_manual_disarmed_mode_and_arm_are_rejected_before_effects_by_quota(setup,current_source,fake_ros,monkeypatch):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch,mode=0,armed=False)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert not frames.commands and calls==['stop']
    assert result['observation_budget']['minimum_required_pairs']==11
    assert 'PULSE_OBSERVATION_QUOTA' in str(result['error_evidence'])
    assert result['status']=='UNCONFIRMED' and locks.restriction('v3') is not None


@pytest.mark.parametrize('fault',[None,'mode_reject','mode_unobserved'])
def test_mode_arm_actor_transaction_in_isolation_does_not_claim_full_pulse_quota(setup,current_source,fake_ros,monkeypatch,fault):
    admitted,start,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch,fault=fault,mode=0,armed=False,close=False)
    root=ground.directory(admitted['run_id']);job,_,request,limits=ground._checked(root)
    job.update(job_state='PREPARING',worker=locks.process_identity());locks.atomic_json(root/'job.json',job)
    with locks.execution_scope(admitted['run_id'],'v3'):
        adapter=factory(lambda event:None);adapter.probe(timeout_s=1.)
        result=RoverControlCore(limits,adapter=adapter,clock=source.clock).prepare_guided_armed(safety=PulseSafety(**request['safety']),timeout_s=3.)
        assert frames.commands[0]['payload']=={'mode':15}
        if fault is None:assert result['mode_acknowledged'] and result['arm_acknowledged'] and result['status']=='GUIDED_ARMED_STATIONARY_OBSERVED'
        else:assert result['status']=='UNCONFIRMED' and not result['arm_attempted']
        assert locks.restriction('v3') is not None  # armed state never frees authority
        adapter.session.close()


def test_reserved_samples_abort_watch_without_consuming_stop_quota(setup,current_source,fake_ros,monkeypatch):
    _,_,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch,close=False,prepare=False)
    # Source-only test, no transport or authority bypass: attach/populate through
    # factory inside the admitted owner's existing scope.
    owner=locks.restriction('v3')['owner_id']
    with locks.execution_scope(owner,'v3'):
        adapter=factory(lambda event:None);adapter.probe(timeout_s=1.)
        while min(10-v for v in source.counts.values())>6:source.observe(timeout_s=.1)
        source.reserve_observations(6);before=deepcopy(source.counts);frames.force_ready=True
        with pytest.raises(ValueError,match='RESERVED_FOR_STOP'):source.poll(timeout_s=.05)
        assert source.counts==before and not source.failed
        source.observe(timeout_s=.1);assert min(10-v for v in source.counts.values())==5
        adapter.session.close()


@pytest.mark.parametrize('bad',['foreign','shared','domain','service_shared','service_type'])
def test_actual_graph_destination_must_match_native_reader(setup,current_source,fake_ros,monkeypatch,bad):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch)
    node=fake_ros[1];read=node.get_subscriptions_info_by_topic
    if bad=='service_shared':node.get_node_names_and_namespaces=lambda:[('A','/ap/v3'),('OTHER','/foreign')]
    elif bad=='service_type':node.get_service_names_and_types_by_node=lambda n,ns:[(ros.MODE,['wrong/srv/Type'])]
    elif bad=='domain':fake_ros[2].get_domain_id=lambda:9
    elif bad=='foreign':node.get_subscriptions_info_by_topic=lambda topic:[NS(endpoint_gid=bytes.fromhex('f'*48),topic_type='geometry_msgs/msg/TwistStamped')]
    else:node.get_subscriptions_info_by_topic=lambda topic:read(topic)*2
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert not frames.commands and calls==['stop']
    assert result['status']=='UNCONFIRMED' and locks.restriction('v3') is not None


def test_changed_execution_blocks_cleanup_without_bypassing_reservation(setup,current_source,fake_ros,monkeypatch):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch,fault='context')
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert calls==[] and result['infrastructure_close']['status']=='BLOCKED'
    assert 'ENVIRONMENT_CHANGED' in result['infrastructure_close']['message']
    assert locks.restriction('v3')['owner_id']==admitted['run_id']


def test_other_ground_owner_and_changed_descriptor_cannot_close(setup,current_source,fake_ros,monkeypatch):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch,fault='context')
    ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',ground_owner='33333333-3333-4333-8333-333333333333')['status']=='BLOCKED'
    p=locks.LOCK_ROOT.parent/'diagnostic_agent_session.json';target=json.loads(p.read_text());target['descriptor']['lifecycle_id']='33333333-3333-4333-8333-333333333333';locks.atomic_json(p,target)
    assert lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',ground_owner=admitted['run_id'])['status']=='BLOCKED'
    assert not calls and locks.restriction('v3') is not None


def test_cleanup_interruption_and_persistence_do_not_release_or_replay(setup,current_source,fake_ros,monkeypatch):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch,fault='interrupt')
    with pytest.raises(KeyboardInterrupt):ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert calls==['stop'] and locks.restriction('v3') is not None and locks.infrastructure_restriction()['state']=='UNCONFIRMED'
    assert ground.close_ground_infrastructure(admitted['run_id'])['reason']=='CLOSE_ALREADY_CLAIMED_QUERY_AUDIT_NO_REPLAY'
    assert calls==['stop']


def test_durable_close_failure_keeps_original_report_and_restriction(setup,current_source,fake_ros,monkeypatch):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch)
    write=locks.atomic_json
    def fail(path,value):
        if path.name=='closure-report.json':raise OSError('SYNTHETIC_CLOSURE_PERSISTENCE_FAILURE')
        return write(path,value)
    monkeypatch.setattr(locks,'atomic_json',fail)
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert result['status']=='UNCONFIRMED' and calls==['stop'] and locks.restriction('v3') is not None
    root=ground.directory(admitted['run_id']);assert (root/'pre-infrastructure-report.json').exists() and (root/'infrastructure-close.json').exists()


def test_mode_and_arm_require_exact_preparing_job_and_native_true_serialization(setup,current_source,fake_ros,monkeypatch):
    original_exchange=ros.NativeRos2Session._exchange
    admitted,start,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch,close=False)
    root=ground.directory(admitted['run_id']);job,_,_,_=ground._checked(root)
    job.update(job_state='RUNNING',worker=locks.process_identity());locks.atomic_json(root/'job.json',job)
    with locks.execution_scope(admitted['run_id'],'v3'):
        adapter=factory(lambda event:None);adapter.probe(timeout_s=1.)
        command={'kind':'service','endpoint':ros.DISARM,'type':'ardupilot_msgs/srv/ArmMotors','payload':{'arm':True}}
        with pytest.raises(ValueError,match='PREPARING'):adapter.exchange(command,timeout_s=1.)
        assert not frames.commands
        job['job_state']='PREPARING';locks.atomic_json(root/'job.json',job)
        native=adapter.session;native.disarm_type=NS(Request=lambda:NS(arm=None));requests=[]
        future=NS(done=lambda:True,result=lambda:NS(result=True))
        native.disarm_client=NS(call_async=lambda r:(requests.append(r) or future))
        monkeypatch.setattr(ros.NativeRos2Session,'_exchange',original_exchange)
        reply=adapter.exchange(command,timeout_s=1.)
        assert requests[0].arm is True and reply.payload=={'result':True}
        adapter.session.close()


def test_historical_24_second_gap_cannot_admit_even_a_short_pulse(setup,current_source,fake_ros,monkeypatch):
    admitted,start,factory,source,frames,calls,_=trial(setup,current_source,fake_ros,monkeypatch)
    original=frames.read
    def replay_gap(timeout_s):
        if not frames.rows and not frames.requested:
            source.clock.sleep(timeout_s)
            raise TimeoutError('TEST_REPLAY_ORIGINAL_INTER_RECEIPT_GAP_24S_EXCEEDS_1S_CALL')
        return original(timeout_s)
    frames.read=replay_gap
    result=ground.start_ground_trial(admitted['run_id'],start,adapter_factory=factory,readiness=lambda **kw:{'ready':True})
    assert not frames.commands and calls==['stop']
    assert result['status']=='UNCONFIRMED' and 'REPLAY_ORIGINAL_INTER_RECEIPT' in str(result['preparation']['error_evidence'])
    assert locks.restriction('v3') is not None


def test_source_factory_preserves_initial_failure_and_terminal_close_error(setup,current_source,fake_ros,monkeypatch):
    admitted,_,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch,fault='close',close=False)
    fake_ros[1].create_client.side_effect=RuntimeError('SYNTHETIC_INIT_PRIMARY')
    with locks.execution_scope(admitted['run_id'],'v3'):
        with pytest.raises(RuntimeError,match='INIT_PRIMARY') as error:factory(lambda event:None)
    assert error.value.diagnostic['resource_close_error']
    assert source.footer is None and source.close_result['return_code']==2
    assert 'TERMINAL WATCHDOG' in source.close_result['stderr']


def test_current_pipe_factory_requires_live_owner_before_source_or_ros(setup,current_source,fake_ros,monkeypatch):
    admitted,_,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch)
    with pytest.raises(locks.VehicleBusy):factory(lambda event:None)
    fake_ros[0].init.assert_not_called()
    assert source.sequence==0 and not frames.commands


def test_native_transport_cannot_be_borrowed_by_another_job(setup,current_source,fake_ros,monkeypatch):
    import shutil
    admitted,_,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch,close=False,prepare=False)
    with locks.execution_scope(admitted['run_id'],'v3'):
        adapter=factory(lambda event:None);adapter.probe(timeout_s=1.)
    # Explicit synthetic association corruption, not a second admission/run.
    other='33333333-3333-4333-8333-333333333333';root=ground.directory(other)
    shutil.copytree(ground.directory(admitted['run_id']),root)
    job=ground._read(root,'job.json');job.update(run_id=other,job_state='RUNNING',worker=locks.process_identity());locks.atomic_json(root/'job.json',job)
    lease=locks.restriction('v3');lease['owner_id']=other;locks.atomic_json(locks.LOCK_ROOT/'v3.json',lease)
    with locks.execution_scope(other,'v3'):
        with pytest.raises(ValueError,match='owner changed'):adapter.session.exchange(RoverControlCore.velocity_message(0.,0.),timeout_s=1.)
    assert not frames.commands
    adapter.session.close()


def test_disabled_policy_cannot_construct_current_source_backend(setup,current_source,fake_ros,monkeypatch):
    admitted,_,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch)
    monkeypatch.setattr(ground,'OPERATIONAL_ROVER_ENABLED',False)
    with locks.execution_scope(admitted['run_id'],'v3'):
        with pytest.raises(ValueError,match='policy disabled'):factory(lambda event:None)
    assert source.sequence==0 and not frames.commands
    fake_ros[0].init.assert_not_called()


def test_policy_disable_still_allows_previously_owned_zero_hold_and_explicit_disarm(setup,current_source,fake_ros,monkeypatch):
    admitted,_,factory,source,frames,_,_=trial(setup,current_source,fake_ros,monkeypatch,close=False,prepare=False)
    root=ground.directory(admitted['run_id']);job,_,request,limits=ground._checked(root)
    job.update(job_state='RUNNING',worker=locks.process_identity());locks.atomic_json(root/'job.json',job)
    with locks.execution_scope(admitted['run_id'],'v3'):
        adapter=factory(lambda event:None);adapter.probe(timeout_s=1.)
        monkeypatch.setattr(ground,'OPERATIONAL_ROVER_ENABLED',False)
        with pytest.raises(ValueError,match='policy disabled'):adapter.exchange(RoverControlCore.velocity_message(.05,0.),timeout_s=1.)
        assert not frames.commands
        core=RoverControlCore(limits,adapter=adapter,clock=source.clock);stopped=core.stop(force_zero=True)
        assert stopped['stationary_observed']
        job['job_state']='FINALIZING';locks.atomic_json(root/'job.json',job)
        result=core.finalize_disarmed(stopped,timeout_s=3.)
        assert result['disarmed_observed'] and frames.commands[-1]['payload']=={'arm':False}
        adapter.session.close()
