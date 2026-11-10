"""Real retained quaternion, isolated legacy rejection and independent geometry oracles.

    No observation below accredits a source. Status/provenance envelopes are TEST
    fixtures; the passive /3 Status record does not contain those payload fields.
"""
import ast
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess

import pytest

from tools import rover_control as rc
from tests.test_rover_navigation import GOAL,LIMITS
from tests.test_rover_source_contracts import ap_dds_contract_binary
from tests.test_rover_transport_preparation import fake_ros
from tests.test_rover_ground_executor import setup


ROOT=Path(__file__).resolve().parents[1]
HISTORY=ROOT/'simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728'
JOURNAL='container-copies/tmp/tfg_rover_xrce_capture/4ac58516-8fad-457e-918e-253483a2d728/journal.jsonl'


def retained_observation():
    manifest=json.loads((HISTORY/'manifest.json').read_bytes())
    entry=next(e for e in manifest['files'] if e['path']==JOURNAL)
    data=(HISTORY/JOURNAL).read_bytes()
    assert hashlib.sha256(data).hexdigest()==entry['sha256']=='13811afdfe8b20b71e3b5f1ff595c546ebdc5ff5c4919ef77424216d679a3f18'
    sample=next(v for v in map(json.loads,data.splitlines()) if v.get('topic')=='/rover1/odometry')
    pose=sample['odometry_fields']['pose'];twist=sample['odometry_fields']['twist']
    q=tuple(pose['orientation'][k] for k in ('x','y','z','w'))
    stamp=sample['header']['stamp'];receipt=sample['receipt']['steady_ns']/1e9
    # Typed unknown-status TEST envelope, not a fabricated real Status payload.
    obs=rc.Observation(vehicle_id='rover_01',interface='v3',vehicle_type=1,mode=4,
        armed=False,flying=False,external_control=False,failsafe=(),received_monotonic_s=receipt,
        status_source_ns=None,velocity_source_ns=stamp['sec']*10**9+stamp['nanosec'],
        linear_mps=tuple(twist['linear'][k] for k in ('x','y','z')),
        angular_rad_s=tuple(twist['angular'][k] for k in ('x','y','z')),
        motion_source='/model/rover1/odometry',motion_frame=sample['child_frame_id'],motion_received_monotonic_s=receipt,
        position_m=tuple(pose['position'][k] for k in ('x','y','z')),orientation_xyzw=q,
        pose_frame=sample['header']['frame_id'],pose_reference_validated=False,
        odometry_publisher_gid=sample['message_publisher_gid'],pose_covariance=tuple(pose['covariance']),
        twist_covariance=tuple(twist['covariance']),observation_provenance_sha256=None)
    return obs,sample


def geometry_fixture(obs):
    # Only for isolating geometry after the real frame gate; NOT accreditation.
    return replace(obs,pose_reference_validated=True,observation_provenance_sha256='1'*64)


def test_real_quaternion_reproduces_old_component_gate_without_changing_original():
    obs,_=retained_observation();obs=geometry_fixture(obs)
    clock=type('ReceiptClock',(),{'monotonic':lambda self:obs.received_monotonic_s})()
    name='final-source-snapshots/tools/rover_control.py';data=(HISTORY/name).read_bytes()
    manifest=json.loads((HISTORY/'manifest.json').read_bytes())
    assert hashlib.sha256(data).hexdigest()==next(e['sha256'] for e in manifest['files'] if e['path']==name)
    node=next(n for n in ast.parse(data).body if isinstance(n,ast.ClassDef) and n.name=='RoverControlCore')
    namespace=vars(rc).copy()
    exec(compile(ast.Module(body=[node],type_ignores=[]),name,'exec'),namespace)
    old=namespace['RoverControlCore'](LIMITS,clock=clock)
    assert old._validate(obs) is obs
    assert math.hypot(*obs.orientation_xyzw)==pytest.approx(1.,abs=1e-15)
    assert abs(obs.orientation_xyzw[0])>1e-3 and abs(obs.orientation_xyzw[1])>1e-3
    with pytest.raises(rc.RoverControlError,match='Non-planar orientation'):old._navigation_observation(obs,GOAL)


def test_real_sample_geometry_passes_but_unknown_frame_and_control_remain_blocked():
    obs,_=retained_observation()
    clock=type('ReceiptClock',(),{'monotonic':lambda self:obs.received_monotonic_s})()
    core=rc.RoverControlCore(LIMITS,clock=clock)
    assert core._validate(obs) is obs
    with pytest.raises(rc.RoverControlError,match='frame/provenance'):core._navigation_observation(obs,GOAL)
    x,y,yaw=core._navigation_observation(geometry_fixture(obs),GOAL)
    geometry=rc.projected_ground_heading(obs.orientation_xyzw)
    assert math.degrees(yaw)==pytest.approx(89.7694108673417,abs=1e-10)
    assert geometry['input_norm']==pytest.approx(1.,abs=1e-15)
    assert math.degrees(geometry['body_up_inclination_rad'])==pytest.approx(.5454391708,abs=1e-6)
    assert not geometry['frame_association_verified'] and not geometry['operational_slope_approved']
    goal=replace(GOAL,x_m=x+math.cos(yaw),y_m=y+math.sin(yaw))
    d=rc.GoalController(goal,LIMITS).step(x,y,yaw,0.)
    assert d['forward_mps']>0 and abs(d['yaw_rate_rad_s'])<1e-10
    assert core.adapter is None and not core.diagnostics  # no command was emitted
    from tools.rover_ground_executor import OPERATIONAL_ROVER_ENABLED
    assert OPERATIONAL_ROVER_ENABLED is False


def multiply(a,b):
    # Independent Hamilton product of axis-angle quaternions, not a yaw formula.
    x,y,z,w=a;u,v,t,s=b
    return (w*u+x*s+y*t-z*v,w*v-x*t+y*s+z*u,w*t+x*v-y*u+z*s,w*s-x*u-y*v-z*t)


def rpy_quaternion(roll,pitch,yaw):
    return multiply(multiply((0.,0.,math.sin(yaw/2),math.cos(yaw/2)),
        (0.,math.sin(pitch/2),0.,math.cos(pitch/2))),
        (math.sin(roll/2),0.,0.,math.cos(roll/2)))


@pytest.mark.parametrize('roll',[-.8,0.,.8])
@pytest.mark.parametrize('pitch',[-.6,0.,.6])
@pytest.mark.parametrize('yaw',[-math.pi-.01,-math.pi+.01,0.,1.2,math.pi-.01,math.pi+.01])
def test_combined_roll_pitch_yaw_matches_independent_rotation_matrix(roll,pitch,yaw):
    q=rpy_quaternion(roll,pitch,yaw);g=rc.projected_ground_heading(q)
    expected=(math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch),-math.sin(pitch))
    assert g['forward_in_reference']==pytest.approx(expected,abs=2e-15)
    assert g['horizontal_forward_norm']==pytest.approx(abs(math.cos(pitch)),abs=2e-15)
    assert rc.wrap_angle(g['heading_rad']-yaw)==pytest.approx(0.,abs=2e-15)
    assert rc.projected_ground_heading(tuple(-v for v in q))['heading_rad']==g['heading_rad']


def test_near_unit_roundoff_is_normalized_but_large_scaling_is_rejected():
    q=rpy_quaternion(.4,.5,1.2)
    g=rc.projected_ground_heading(tuple(v*(1+1e-5) for v in q))
    assert g['normalization_applied'] and g['heading_rad']==pytest.approx(1.2)
    with pytest.raises(rc.RoverControlError,match='Non-unit'):rc.projected_ground_heading(tuple(v*1.01 for v in q))


@pytest.mark.parametrize('q',[(0.,0.,0.,0.),(0.,0.,0.,2.),(float('nan'),0.,0.,1.),
    (float('inf'),0.,0.,1.),(True,0.,0.,1.),(0.,0.,1.),None])
def test_invalid_quaternion_rejected(q):
    with pytest.raises(rc.RoverControlError):rc.projected_ground_heading(q)


@pytest.mark.parametrize('pitch',[math.pi/2,-math.pi/2,math.pi/2+1e-10,-math.pi/2-1e-10])
def test_vertical_or_numerically_degenerate_longitudinal_axis_rejected(pitch):
    with pytest.raises(rc.RoverControlError,match='Degenerate'):rc.projected_ground_heading(rpy_quaternion(.4,pitch,1.2))


def test_defined_projection_does_not_approve_a_slope_or_inverted_vehicle():
    g=rc.projected_ground_heading(rpy_quaternion(math.pi,0.,.7))
    assert g['heading_rad']==pytest.approx(.7) and g['body_up_inclination_rad']==pytest.approx(math.pi)
    assert g['operational_slope_approved'] is False


@pytest.mark.parametrize('yaw,target_heading,sign',[(math.radians(179),math.radians(-179),1),
    (math.radians(-179),math.radians(179),-1)])
def test_projected_heading_wrap_and_steering_sign(yaw,target_heading,sign):
    g=rc.projected_ground_heading(rpy_quaternion(.4,.5,yaw))
    goal=replace(GOAL,x_m=math.cos(target_heading),y_m=math.sin(target_heading))
    d=rc.GoalController(goal,LIMITS).step(0.,0.,g['heading_rad'],0.)
    assert 0<sign*d['yaw_rate_rad_s']<.05


@pytest.mark.parametrize('rpy',[(.3,.4,.7),(-.6,-.4,-2.8),(.7,.2,3.12)])
@pytest.mark.parametrize('target',[(1.,0.),(0.,1.),(-1.,0.),(0.,-1.)])
def test_tilted_geometry_commands_against_actual_ap_dds_cpp(ap_dds_contract_binary,rpy,target):
    roll,pitch,yaw=rpy;heading=rc.projected_ground_heading(rpy_quaternion(*rpy))['heading_rad']
    d=rc.GoalController(replace(GOAL,x_m=target[0],y_m=target[1]),LIMITS).step(0.,0.,heading,0.)
    raw=subprocess.run([str(ap_dds_contract_binary),str(d['forward_mps']),str(d['yaw_rate_rad_s']),
        str(math.pi/2-yaw),str(-pitch),str(roll)],capture_output=True,text=True,check=True,timeout=2)
    north,east,down,ned_rate=map(float,raw.stdout.split())
    speed=d['forward_mps']
    assert (east,north,down)==pytest.approx((speed*math.cos(yaw)*math.cos(pitch),speed*math.sin(yaw)*math.cos(pitch),speed*math.sin(pitch)),abs=2e-6)
    assert ned_rate==pytest.approx(-d['yaw_rate_rad_s'],abs=2e-6)


@pytest.mark.parametrize('point,expected',[((1.,0.),(2.,4.)),((0.,1.),(1.,3.)),((-1.,0.),(2.,2.)),((0.,-1.),(3.,3.))])
def test_target_rigid_transform_known_axes_and_inverse(point,expected):
    result=rc.transform_ground_point(point,(2.,3.),math.pi/2)
    assert result==pytest.approx(expected)
    assert rc.transform_ground_point((result[0]-2.,result[1]-3.),(0.,0.),-math.pi/2)==pytest.approx(point)


@pytest.mark.parametrize('point,translation,angle',[(None,(0.,0.),0.),((1.,),(0.,0.),0.),((1.,2.),(float('inf'),0.),0.),((1.,2.),(0.,0.),float('nan'))])
def test_target_transform_invalid_geometry_never_accepted(point,translation,angle):
    with pytest.raises(rc.RoverControlError):rc.transform_ground_point(point,translation,angle)


def test_prepared_native_probe_reports_exact_guard_session(fake_ros,monkeypatch):
    from tools import rover_ros2_adapter as ros
    # Public ROS API doubles only. This is NOT an accredited live guard.
    monkeypatch.setattr(ros.RoverEnvironmentGuard,'require_motion_source',lambda self:None)
    expected={'lifecycle_id':'fixture-session'}
    session=ros.NativeRos2Session(identity_guard=ros.RoverEnvironmentGuard(expected,lambda:{}))
    rclpy,node,_,_=fake_ros
    from types import SimpleNamespace as NS
    from unittest.mock import Mock
    rclpy.spin_once=Mock()
    node.get_topic_names_and_types=lambda:[(ros.STATUS,['ardupilot_msgs/msg/Status']),
        (ros.ODOMETRY,['nav_msgs/msg/Odometry']),(ros.VELOCITY,['geometry_msgs/msg/TwistStamped'])]
    node.get_service_names_and_types=lambda:[(ros.MODE,['ardupilot_msgs/srv/ModeSwitch']),
        (ros.DISARM,['ardupilot_msgs/srv/ArmMotors'])]
    node.get_publishers_info_by_topic=lambda topic:[NS(endpoint_gid=bytes.fromhex('1'*48))]
    session.client.service_is_ready.return_value=True;session.disarm_client.service_is_ready.return_value=True
    session.publisher.get_subscription_count.return_value=1
    caps=session.probe(timeout_s=.1)
    assert caps['session_id']=='fixture-session' and caps['odometry_publisher_gids']==['1'*48]
    assert session.latest=={}  # discovery did not invent a sample attribution
    session.publisher.publish.assert_not_called();session.client.call_async.assert_not_called()
    session.close()


def test_public_physical_start_remains_blocked_before_factory_or_readiness(tmp_path,monkeypatch):
    from tools import rover_ground_executor as ground
    from unittest.mock import Mock
    assert ground.OPERATIONAL_ROVER_ENABLED is False
    monkeypatch.setattr(ground,'RUN_ROOT',tmp_path/'never-created')
    factory=Mock();readiness=Mock()
    reply=ground.start_ground_trial('00000000-0000-4000-8000-000000000001',{},
        adapter_factory=factory,readiness=readiness)
    assert reply['status']=='BLOCKED' and not ground.RUN_ROOT.exists()
    factory.assert_not_called();readiness.assert_not_called()


def test_tilted_observations_cross_protected_worker_and_scoped_closure(setup,monkeypatch):
    from tests import test_rover_navigation as nav
    from tools import rover_ground_executor as ground
    roll,pitch=.2,.25
    class TiltedClock(nav.Clock):
        def sleep(self,dt):
            s=self.session
            if s and not s.frozen:
                s.yaw+=s.w*dt
                s.x+=s.v*math.cos(pitch)*math.cos(s.yaw)*dt
                s.y+=s.v*math.cos(pitch)*math.sin(s.yaw)*dt
            self.now+=dt
    class TiltedSession(nav.Session):
        def observe(self,**kw):
            raw=super().observe(**kw)
            raw['odometry']['pose']['pose']['orientation']=dict(zip(('x','y','z','w'),rpy_quaternion(roll,pitch,self.yaw)))
            return raw
    monkeypatch.setattr(nav,'Clock',TiltedClock);monkeypatch.setattr(nav,'Session',TiltedSession)
    report,session,admission=nav.execute(setup,pose=(0.,0.,.7),
        finalization={'kind':'DISARM_AFTER_OBSERVED_STOP_V1','timeout_s':3.})
    assert report['result']['goal_outcome']=='GOAL_REACHED'
    assert all(d['heading_geometry']['method']=='LONGITUDINAL_AXIS_HORIZONTAL_PROJECTION'
        and d['heading_geometry']['operational_slope_approved'] is False for d in report['result']['decisions'])
    assert report['r1_ground_result']['origin']=='SYNTHETIC_TEST_DOUBLE'
    assert ground.query_ground_trial(admission['run_id'])['status']=='FINISHED' and session.closed
