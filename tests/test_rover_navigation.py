"""Synthetic kinematics, complete existing protected worker path. No ROS/SITL evidence."""
from dataclasses import asdict, replace
import json
import math
import pytest
from planning.artifact_store import fingerprint, sha256
from tools import rover_ground_executor as ground, vehicle_execution_lock as locks
from tools.rover_control import NavigationGoal, RoverLimits, GoalController, Reply
from tools.rover_ros2_adapter import Ros2RoverAdapter, MotionBinding, MODE, DISARM
from tests.test_rover_ground_executor import setup  # existing temporary-project policy fixture

SESSION='11111111-1111-4111-8111-111111111111'
BIND=MotionBinding('1'*64,'2'*64,'3'*48,pose_reference_frame='odom',pose_reference_sha256='4'*64)
LIMITS=RoverLimits(.4,1.,30.,1.,3.,.5,.03,.03)
GOAL=NavigationGoal(.8,.4,.2,'odom','m','IDENTITY_SAME_ACCREDITED_FRAME',.05,.05,.3,10.,25.,4.,.005,.01,256)

class Clock:
    def __init__(self):self.now=0.;self.session=None
    def monotonic(self):return self.now
    def sleep(self,dt):
        s=self.session
        if s and not s.frozen:
            s.yaw+=s.w*dt;s.x+=s.v*math.cos(s.yaw)*dt;s.y+=s.v*math.sin(s.yaw)*dt
        self.now+=dt

class Session:
    synthetic_model=True
    def __init__(self,clock,pose):
        self.clock=clock;clock.session=self
        self.x,self.y,self.yaw=pose;self.v=self.w=0.;self.mode=15;self.armed=True;self.disarm_requested=False
        self.reads=0;self.commands=[];self.closed=False;self.frozen=False
        self.failure=None
    def probe(self,**kw):
        return dict(status_type='ardupilot_msgs/msg/Status',odometry_type='nav_msgs/msg/Odometry',
                    mode_type='ardupilot_msgs/srv/ModeSwitch',velocity_type='geometry_msgs/msg/TwistStamped',
                    mode_available=True,disarm_type='ardupilot_msgs/srv/ArmMotors',disarm_available=True,velocity_subscribers=1,status_publishers=1,odometry_publisher_gids=[BIND.odometry_publisher_gid],session_id='wrong' if self.failure=='session' else SESSION)
    def observe(self,**kw):
        self.reads+=1;self.clock.now+=.001
        if self.failure=='blocked_observe' and self.reads==3:
            import time
            time.sleep(.4)  # interrupted synchronously; no helper thread exists
            raise AssertionError('late observation continuation')
        if self.failure=='lost' and self.reads>5:raise TimeoutError('synthetic observation lost')
        if self.failure=='disturb' and self.reads==5:self.x-=.2
        if self.disarm_requested and self.failure=='finalization_interrupt':raise KeyboardInterrupt('synthetic closing interruption')
        if self.disarm_requested and self.failure=='finalization_source':raise TimeoutError('synthetic source lost during finalization')
        stamp={'sec':self.reads,'nanosec':0};zero={'x':0.,'y':0.,'z':0.}
        odom={'header':{'stamp':stamp,'frame_id':'wrong' if self.failure=='frame' and self.reads>5 else 'odom'},
              'child_frame_id':'base_link','pose':{'pose':{'position':{'x':self.x,'y':self.y,'z':0.},
              'orientation':{'x':0.,'y':0.,'z':math.sin(self.yaw/2),'w':math.cos(self.yaw/2)}},'covariance':[0.]*36},
              'twist':{'twist':{'linear':{'x':self.v,'y':0.,'z':0.},'angular':{'x':0.,'y':0.,'z':self.w}},'covariance':[0.]*36}}
        if self.failure=='nan':odom['pose']['pose']['position']['x']=float('nan')
        if self.failure=='badquat':odom['pose']['pose']['orientation']['w']=2.
        return {'odometry_publisher_gid':'9'*48 if self.failure=='identity' and self.reads>5 else BIND.odometry_publisher_gid,
                'status':{'header':{'stamp':stamp},'vehicle_type':1,'mode':self.mode,'armed':self.armed,'flying':False,'external_control':True,'failsafe':[]},
                'odometry':odom,'status_received_monotonic_s':self.clock.now,
                'odometry_received_monotonic_s':self.clock.now-(2 if self.failure=='stale' or self.disarm_requested and self.failure=='finalization_stale' else 0)}
    def exchange(self,command,**kw):
        locks.assert_execution_authority('v3');self.commands.append(command)
        if command['endpoint']==DISARM:
            assert command['payload']=={'arm':False}
            self.disarm_requested=True
            if self.failure=='disarm_rejected':return Reply(True,0,{'result':False})
            self.armed=False
            if self.failure=='disarm_lost':raise TimeoutError('synthetic disarm reply lost')
            return Reply(True,0,{'result':True})
        if command['endpoint']==MODE:
            if self.failure=='stop':return Reply(True,0,{'status':False,'curr_mode':15})
            self.mode=command['payload']['mode'];self.v=self.w=0.
            return Reply(True,0,{'status':True,'curr_mode':self.mode})
        if self.failure=='blocked_send':
            import time
            time.sleep(.4)
            raise AssertionError('late order continuation')
        if self.failure=='send':raise TimeoutError('synthetic publication uncertain')
        self.v=command['payload']['twist']['linear']['x'];self.w=command['payload']['twist']['angular']['z']
        return Reply(True,0)
    def close(self):self.closed=True


def execute(setup,pose=(0.,0.,0.),goal=GOAL,failure=None,cancelled=lambda:False,limits=LIMITS,finalization=None,start=True):
    path,_,_,_,_=setup
    clock=Clock();session=Session(clock,pose);session.failure=failure;session.frozen=failure=='stuck'
    request={'kind':'ROVER_NAVIGATE_V1','limits':asdict(limits),'goal':asdict(goal)}
    if finalization is not None:request['finalization']=finalization
    auth={'mission_sha256':sha256(path.read_bytes()),'request_fingerprint':fingerprint(request),'statement':'SYNTHETIC offline scope only'}
    candidate={'vehicle_id':'rover_01','rover_mission':{'value':{'sha256':auth['mission_sha256']}},
               'target_in_rover_frame':{'value':{'x_m':goal.x_m,'y_m':goal.y_m,'frame':goal.frame}},
               'frame_transform':{'value':{'status':'VERIFIED','sha256':BIND.pose_reference_sha256,'to_frame':goal.frame,'from_frame':goal.frame}}}
    if finalization is not None:candidate['finalization_policy']={'value':finalization}
    declared={'source':'OPERATOR_DECLARED','statement':'SYNTHETIC fixture declaration only',
              'candidate_sha256':fingerprint(candidate),'mission_sha256':auth['mission_sha256'],'session_id':SESSION}
    admitted=ground.admit_ground_trial(path,'navigation',request,auth,coordination_context={'candidate':candidate,'authorization':declared})
    assert admitted['status']=='ADMITTED',admitted
    factory=lambda journal:Ros2RoverAdapter(session,binding=BIND,clock=clock,journal=journal)
    query=ground.query_ground_trial(admitted['run_id'])
    start_auth={'run_id':admitted['run_id'],'input_sha256':query['input_sha256'],
                **{k:query['coordination_binding'][k] for k in ('candidate_sha256','session_id','authorization_sha256')},
                'statement':'Explicit synthetic start of existing admission'}
    if not start:return admitted,session,factory,start_auth
    report=ground.start_ground_trial(admitted['run_id'],start_auth,adapter_factory=factory,
                                   readiness=lambda **kw:{'ready':True},cancelled=cancelled)
    return report,session,admitted

@pytest.mark.parametrize('pose',[(0.,0.,0.),(0.,0.,math.pi),(1.,-.3,-1.),(.8,.4,.2)])
def test_mission_worker_controller_adapter_observation_stop_result(setup,pose):
    report,s,a=execute(setup,pose)
    assert report['result']['goal_outcome']=='GOAL_REACHED',report['result'].get('error_evidence')
    assert report['status']=='STOP_OBSERVED' and report['r1']['stop_observed']
    assert report['r1']['samples_sha256']==fingerprint(report['r1']['samples'])
    assert report['r1_ground_result']['schema']=='tfg.agri-r1-ground-result/1'
    assert report['r1_ground_result']['binding']['session_id']==SESSION
    assert ground.lookup_ground_trial('navigation')['session_id']==SESSION
    assert report['r1_ground_result']['origin']=='SYNTHETIC_TEST_DOUBLE'
    assert report['r1_ground_result']['stop']['status']=='STATIONARY_OBSERVED'
    assert s.closed and len(s.commands)<=GOAL.max_samples+2
    # HOLD is not disarm. Existing conservative reservation remains while armed.
    assert ground.query_ground_trial(a['run_id'])['status']=='UNCONFIRMED'
    assert locks.restriction('v3')['owner_id']==a['run_id']

@pytest.mark.parametrize('failure',['stuck','lost','frame','send','stop','nan','badquat','stale'])
def test_failure_or_uncertainty_never_yields_goal_success(setup,failure):
    report,s,a=execute(setup,failure=failure)
    assert report['status'] in ('UNCONFIRMED','NOT_ATTEMPTED')
    if report['result']['motion_command_attempted']:
        assert report['result']['stop_requested'] and locks.restriction('v3')
    else:assert not s.commands
    assert s.closed


def test_cancel_after_possible_control_preserves_restriction(setup):
    calls=[0]
    def cancel():calls[0]+=1;return calls[0]>5
    report,s,a=execute(setup,cancelled=cancel)
    assert report['status']=='UNCONFIRMED' and report['result']['goal_outcome']=='GOAL_FAILED'
    assert report['result']['stop_requested'] and locks.restriction('v3')


def test_dwell_reset_when_leaving_tolerance():
    c=GoalController(GOAL,LIMITS)
    assert not c.step(.8,.4,.2,0)['reached']
    assert not c.step(.7,.4,.2,.2)['inside']
    assert not c.step(.8,.4,.2,.4)['reached']
    assert c.step(.8,.4,.2,.8)['reached']


def test_operational_policy_still_blocks_navigation_before_io(tmp_path,monkeypatch):
    monkeypatch.setattr(ground,'RUN_ROOT',tmp_path/'never')
    assert ground.OPERATIONAL_ROVER_ENABLED is False
    assert ground.admit_ground_trial('missing','x',{}, {})['status']=='BLOCKED'
    assert not ground.RUN_ROOT.exists()


def test_full_worker_dwell_restarts_after_disturbance(setup):
    report,s,a=execute(setup,pose=(.8,.4,.2),failure='disturb')
    assert report['result']['goal_outcome']=='GOAL_REACHED'
    decisions=report['result']['decisions']
    assert decisions[0]['inside'] and any(not d['inside'] for d in decisions)
    last_outside=max(i for i,d in enumerate(decisions) if not d['inside'])
    assert decisions[-1]['received_monotonic_s']-decisions[last_outside+1]['received_monotonic_s']>=GOAL.dwell_s

@pytest.mark.parametrize('goal',[replace(GOAL,timeout_s=.5,no_progress_s=.5),replace(GOAL,max_samples=3)])
def test_timeout_and_sample_budget_are_protected_results(setup,goal):
    report,s,a=execute(setup,goal=goal)
    assert report['status']=='UNCONFIRMED' and report['result']['stop_requested']
    assert len(report['r1']['samples'])<=goal.max_samples and locks.restriction('v3')


def test_inside_tolerance_while_moving_does_not_accrue_dwell():
    c=GoalController(GOAL,LIMITS)
    assert not c.step(.8,.4,.2,0,linear_speed=.2)['reached']
    assert not c.step(.8,.4,.2,1,linear_speed=.2)['reached']
    assert not c.step(.8,.4,.2,2)['reached']
    assert c.step(.8,.4,.2,2.5)['reached']


@pytest.mark.parametrize('failure',['identity','session'])
def test_public_worker_rejects_source_or_session_change(setup,failure):
    report,s,a=execute(setup,failure=failure)
    assert report['status']=='UNCONFIRMED'
    assert locks.restriction('v3')

@pytest.mark.parametrize('failure',['blocked_observe','blocked_send'])
def test_public_worker_interrupts_blocked_backend_without_late_sender(setup,failure):
    import time
    started=time.monotonic()
    report,s,a=execute(setup,failure=failure,limits=replace(LIMITS,call_timeout_s=.03))
    assert time.monotonic()-started<1.5
    assert report['status']=='UNCONFIRMED' and locks.restriction('v3')
    assert 'deadline' in str(report)
    before=len(s.commands);time.sleep(.45)
    assert len(s.commands)==before  # no detached sender survives cancellation


def test_restart_only_queries_consumed_worker_and_never_resumes(setup):
    report,s,a=execute(setup)
    root=ground.directory(a['run_id']);before={p.name:p.read_bytes() for p in root.glob('*.json')}
    second=ground.run_ground_worker(a['run_id'],a.get('launch_token','NO_PUBLIC_TOKEN'),adapter_factory=lambda journal:pytest.fail('must not resume'))
    assert second['status']=='BLOCKED'
    assert before=={p.name:p.read_bytes() for p in root.glob('*.json')}
    assert ground.lookup_ground_trial('navigation')['run_id']==a['run_id']

@pytest.mark.parametrize('mutation',['missing','candidate','session','mission','target'])
def test_public_navigation_admission_requires_consistent_explicit_context(setup,mutation):
    path,_,_,_,_=setup
    request={'kind':'ROVER_NAVIGATE_V1','limits':asdict(LIMITS),'goal':asdict(GOAL)}
    auth={'mission_sha256':sha256(path.read_bytes()),'request_fingerprint':fingerprint(request),'statement':'synthetic executor declaration'}
    candidate={'vehicle_id':'rover_01','rover_mission':{'value':{'sha256':auth['mission_sha256']}},
        'target_in_rover_frame':{'value':{'x_m':GOAL.x_m,'y_m':GOAL.y_m,'frame':GOAL.frame}},
        'frame_transform':{'value':{'status':'VERIFIED','sha256':BIND.pose_reference_sha256,'to_frame':GOAL.frame}}}
    declared={'source':'OPERATOR_DECLARED','statement':'synthetic coordinator declaration','candidate_sha256':fingerprint(candidate),'mission_sha256':auth['mission_sha256'],'session_id':SESSION}
    ctx={'candidate':candidate,'authorization':declared}
    if mutation=='missing':ctx=None
    elif mutation=='candidate':declared['candidate_sha256']='0'*64
    elif mutation=='session':declared['session_id']='unknown'
    elif mutation=='mission':declared['mission_sha256']='0'*64
    else:
        candidate['target_in_rover_frame']['value']['x_m']=99
        declared['candidate_sha256']=fingerprint(candidate)
    with pytest.raises(ValueError):ground.admit_ground_trial(path,'bad-context',request,auth,coordination_context=ctx)
    assert not ground.RUN_ROOT.exists()


def test_coordination_tamper_and_lookup_are_readonly_fail_closed(setup):
    report,s,a=execute(setup)
    root=ground.directory(a['run_id']);p=root/'coordination.json';v=json.loads(p.read_bytes())
    v['authorization']['session_id']='22222222-2222-4222-8222-222222222222';p.write_text(json.dumps(v))
    before={p.name:p.read_bytes() for p in root.glob('*.json')}
    with pytest.raises(ValueError,match='Coordination'):ground.lookup_ground_trial('navigation')
    assert before=={p.name:p.read_bytes() for p in root.glob('*.json')}
