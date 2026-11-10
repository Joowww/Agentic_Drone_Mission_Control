"""Source-backed frame/bridge contracts. No ROS, middleware or vehicle is run."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import math
import shutil
import subprocess

import pytest

from tools.rover_control import GoalController, RoverControlCore
from tools.rover_identity_inventory import verify_bridge_observations
from tests.test_rover_navigation import GOAL,LIMITS


@pytest.fixture
def bridge_evidence():
    # Synthetic joins shaped like the observed launch/bridge, NOT runtime evidence.
    context={'session_id':'SYNTHETIC','environment':{'engine_id':'fixture','container_id':'fixture','image_id':'fixture'}}
    def reading(value,source):return {'context':deepcopy(context),'value':value,'source':source,'observed_at_utc':'2026-10-26T10:00:00Z'}
    process={'pid':42,'start_ticks':900,'boot_id':'fixture','executable':'/opt/ros/humble/lib/ros_gz_bridge/parameter_bridge',
        'argv':['parameter_bridge','--ros-args','-r','__ns:=/rover1','--params-file','/tmp/params']}
    return {'context':context,
        'sample':reading({'topic':'/rover1/odometry','message_publisher_gid':'1'*48,'frame_id':'odom','child_frame_id':'base_link'},'C++ MessageInfo fixture'),
        'publishers':reading([{'endpoint_gid':'1'*48,'topic_type':'nav_msgs/msg/Odometry'}],'public graph fixture'),
        'process_before':reading(process,'proc before fixture'),'process_after':reading(deepcopy(process),'proc after fixture'),
        'parameters_file':reading({'path':'/tmp/params','content':'/**:\n  ros__parameters:\n    config_file: /tmp/effective.yaml\n'},'argv-selected params fixture'),
        'bridge_configuration':reading({'path':'/tmp/effective.yaml','content':'- ros_topic_name: odometry\n  gz_topic_name: /model/rover1/odometry\n  ros_type_name: nav_msgs/msg/Odometry\n  gz_type_name: gz.msgs.Odometry\n  direction: GZ_TO_ROS\n'},'effective YAML fixture'),
        'model_sdf':reading({'content':'<sdf version="1.9"><model name="wildthumper_with_lidar"><plugin name="gz::sim::systems::OdometryPublisher"><odom_frame>odom</odom_frame><robot_base_frame>base_link</robot_base_frame><dimensions>3</dimensions></plugin></model></sdf>'},'SDF fixture')}


def test_valid_configuration_never_promotes_graph_to_process_or_runtime_model(bridge_evidence):
    r=verify_bridge_observations(bridge_evidence)
    assert r['configuration_chain']=='OBSERVED_FILE_SELECTION_AND_ROUTE_ONLY'
    assert r['configured_dimensions']=='3' and 'MATCHED' in r['sample_endpoint']
    assert r['status']=='BLOCKED' and not r['source_association_verified'] and not r['movement_authorized']
    assert 'UNKNOWN' in r['publisher_process_link'] and 'UNKNOWN' in r['runtime_model_link']


@pytest.mark.parametrize('change',['session','gid','duplicate','process','argv','template','direction','frame'])
def test_inconsistent_bridge_evidence_fails_closed(bridge_evidence,change):
    e=bridge_evidence
    if change=='session':e['model_sdf']['context']['session_id']='OTHER'
    elif change=='gid':e['sample']['value']['message_publisher_gid']=None
    elif change=='duplicate':e['publishers']['value']*=2
    elif change=='process':e['process_after']['value']['start_ticks']+=1
    elif change=='argv':e['process_after']['value']['argv']=[]
    elif change=='template':e['bridge_configuration']['value']['content']=e['bridge_configuration']['value']['content'].replace('/model/rover1/','/model/{{ robot_name }}/')
    elif change=='direction':e['bridge_configuration']['value']['content']=e['bridge_configuration']['value']['content'].replace('GZ_TO_ROS','ROS_TO_GZ')
    else:e['sample']['value']['frame_id']='map'
    r=verify_bridge_observations(e)
    assert r['status']=='BLOCKED' and r['configuration_chain']=='UNKNOWN' and r['reasons']


def test_comment_and_equivalent_yaml_do_not_create_a_false_block(bridge_evidence):
    bridge_evidence['bridge_configuration']['value']['content']+='\n# template reference only: {{ robot_name }}\n'
    bridge_evidence['parameters_file']['value']['content']+='\n/other_node:\n  ros__parameters:\n    use_sim_time: true\n'
    r=verify_bridge_observations(bridge_evidence)
    assert r['configuration_chain']=='OBSERVED_FILE_SELECTION_AND_ROUTE_ONLY'
    assert r['sources']['sample']['source']=='C++ MessageInfo fixture'


def test_duplicate_yaml_selector_is_not_silently_overwritten(bridge_evidence):
    bridge_evidence['parameters_file']['value']['content']+='    config_file: /tmp/other.yaml\n'
    r=verify_bridge_observations(bridge_evidence)
    assert r['configuration_chain']=='UNKNOWN' and 'Duplicate YAML key' in r['reasons'][0]


@pytest.fixture(scope='module')
def ap_dds_contract_binary(tmp_path_factory):
    """Compile actual installed-source method with stub C++ types, NOT a ROS build.

    Matrix is an independent AHRS NED oracle, not the controller's kinematic model.
    Source matched the container read; its hash is deliberately pinned here.
    """
    p=Path('/home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot/libraries/AP_DDS/AP_DDS_ExternalControl.cpp')
    compiler=shutil.which('c++')
    if not compiler or not p.is_file():pytest.skip('Installed AP_DDS source/compiler unavailable; source contract not compiled')
    b=p.read_bytes()
    assert hashlib.sha256(b).hexdigest()=='69fdcd839f9a65f1b8343f0903a25e3064cf4856526f10acad3b6543d7cd9cd9'
    text=b.decode();method=text[text.index('bool AP_DDS_External_Control::handle_velocity_control('):text.index('bool AP_DDS_External_Control::arm(')]
    prefix=r'''
#include <cmath>
#include <cstring>
#include <iostream>
#include <cstdlib>
using std::isnan;
const char* BASE_LINK_FRAME_ID="base_link";const char* MAP_FRAME="map";
struct Vector3f {float x,y,z;};
struct Vec {double x=0,y=0,z=0;};
struct geometry_msgs_msg_TwistStamped {struct {char frame_id[32];} header;struct {Vec linear,angular;} twist;};
struct External {bool set_airspeed(float){return false;} bool set_linear_velocity_and_yaw_rate(Vector3f v,float w){std::cout<<v.x<<" "<<v.y<<" "<<v.z<<" "<<w;return true;}};
struct Ahrs {double compass=0,pitch=0,roll=0;Vector3f body_to_earth(Vector3f v){
double c=cos(compass),s=sin(compass),cp=cos(pitch),sp=sin(pitch),cr=cos(roll),sr=sin(roll);
return {float(c*cp*v.x+(c*sp*sr-s*cr)*v.y+(c*sp*cr+s*sr)*v.z),
float(s*cp*v.x+(s*sp*sr+c*cr)*v.y+(s*sp*cr-c*sr)*v.z),float(-sp*v.x+cp*sr*v.y+cp*cr*v.z)};}};
namespace AP {External e;Ahrs a;External* externalcontrol(){return &e;} Ahrs& ahrs(){return a;}}
struct AP_DDS_External_Control {static bool handle_velocity_control(geometry_msgs_msg_TwistStamped&);};
'''
    main=r'''
int main(int argc,char**argv){geometry_msgs_msg_TwistStamped m;strcpy(m.header.frame_id,"base_link");m.twist.linear.x=atof(argv[1]);m.twist.angular.z=atof(argv[2]);AP::a.compass=atof(argv[3]);AP::a.pitch=argc>4?atof(argv[4]):0;AP::a.roll=argc>5?atof(argv[5]):0;return AP_DDS_External_Control::handle_velocity_control(m)?0:1;}
'''
    root=tmp_path_factory.mktemp('ap-dds-contract');src=root/'contract.cpp';exe=root/'contract'
    src.write_text(prefix+method+main)
    subprocess.run([compiler,'-std=c++17',str(src),'-o',str(exe)],capture_output=True,check=True,timeout=10)
    return exe


@pytest.mark.parametrize('yaw',[0.,math.pi/2,-math.pi/2,math.pi])
@pytest.mark.parametrize('target',[(1.,0.),(0.,1.),(-1.,0.),(0.,-1.)])
def test_goal_commands_against_actual_ap_dds_frame_conversion(ap_dds_contract_binary,yaw,target):
    goal=replace(GOAL,x_m=target[0],y_m=target[1])
    d=GoalController(goal,LIMITS).step(0.,0.,yaw,0.)
    command=RoverControlCore.velocity_message(d['forward_mps'],d['yaw_rate_rad_s'])
    assert command['payload']['header']['frame_id']=='base_link'
    # ROS yaw: ENU CCW from east. AHRS: NED CW from north. This relation is
    # external to the synthetic Session/Clock integrator and uses actual C++.
    compass=math.pi/2-yaw
    raw=subprocess.run([str(ap_dds_contract_binary),str(d['forward_mps']),str(d['yaw_rate_rad_s']),str(compass)],capture_output=True,text=True,check=True,timeout=2)
    north,east,down,ned_rate=map(float,raw.stdout.split())
    assert east==pytest.approx(d['forward_mps']*math.cos(yaw),abs=2e-6)
    assert north==pytest.approx(d['forward_mps']*math.sin(yaw),abs=2e-6)
    assert down==0. and ned_rate==pytest.approx(-d['yaw_rate_rad_s'],abs=2e-6)
    # Positive ROS angular z must turn left/CCW; Rover consumes clockwise
    # centidegrees/s, after its independent earth_to_body conversion.
    assert (-ned_rate)*d['yaw_rate_rad_s']>=0
    assert north*math.cos(compass)+east*math.sin(compass)==pytest.approx(d['forward_mps'],abs=2e-6)


@pytest.mark.parametrize('yaw',[.4,math.pi/2,-math.pi/2,math.pi])
def test_observation_yaw_is_ccw_enu_and_goal_transform_is_not_inferred(yaw):
    from tools.rover_control import RoverControlError
    from tests.test_rover_control import Clock,observation
    clock=Clock();core=RoverControlCore(LIMITS,clock=clock)
    obs=observation(clock,1,position_m=(2.,-4.,0.),orientation_xyzw=(0.,0.,math.sin(yaw/2),math.cos(yaw/2)),
        pose_frame='odom',pose_reference_validated=True,odometry_publisher_gid='1'*48,
        pose_covariance=(0.,)*36,twist_covariance=(0.,)*36,observation_provenance_sha256='2'*64)
    assert core._navigation_observation(obs,GOAL)==pytest.approx((2.,-4.,yaw))
    with pytest.raises(RoverControlError):core._navigation_observation(obs,replace(GOAL,frame='map'))
    with pytest.raises(RoverControlError):core._navigation_observation(replace(obs,linear_unit='cm/s'),GOAL)


def test_real_retained_3d_quaternion_keeps_frame_gate_before_heading_projection():
    import json
    from tools.rover_control import RoverControlError,projected_ground_heading
    from tests.test_rover_control import Clock,observation
    p=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728/analysis-input-journal-copy.jsonl'
    sample=next(v for v in map(json.loads,p.read_text().splitlines()) if v.get('topic')=='/rover1/odometry')
    # Actual received quaternion; all accreditation fields below are TEST fixtures.
    pose=sample['odometry_fields']['pose'];q=pose['orientation'];clock=Clock()
    obs=observation(clock,1,position_m=tuple(pose['position'][k] for k in ('x','y','z')),
        orientation_xyzw=tuple(q[k] for k in ('x','y','z','w')),pose_frame='odom',pose_reference_validated=True,
        odometry_publisher_gid='1'*48,pose_covariance=(0.,)*36,twist_covariance=(0.,)*36,
        observation_provenance_sha256='2'*64)
    core=RoverControlCore(LIMITS,clock=clock)
    with pytest.raises(RoverControlError,match='frame/provenance'):
        core._navigation_observation(replace(obs,pose_reference_validated=False),GOAL)
    x,y,yaw=core._navigation_observation(obs,GOAL)  # TEST fixture accreditation only
    assert (x,y)==obs.position_m[:2]
    assert yaw==projected_ground_heading(obs.orientation_xyzw)['heading_rad']
