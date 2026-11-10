"""Synthetic source-point contracts; no Gazebo plugin/ROS node or vehicle IO."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import pytest
from tools import rover_passive_validation as v
from tools.rover_xrce_trace import monitor as m,prepare_model as prep

ROOT=Path(__file__).resolve().parents[1]


def fixture_records():
    base=dict(schema='tfg.model-source/1',pid=70,process_start_ticks='800',boot_id='fixture',movement_authorized=False,plugin_instance=1,model_entity=42,steady_ns=100,wall_unix_ns=100)
    socket=dict(fd=7,inode=123,address='127.0.0.1',port=9022)
    return [{**base,'event':event,'sequence':i,**fields} for i,event,fields in [
        (1,'configured',dict(socket_observation=socket)),
        (2,'attached_plugin',dict(name='ArduPilotPlugin',filename='TFGArduPilotIdentity',slot=1,xml_sha256='a'*64,effective_sdf={'fdm_port_in':'9022'})),
        (3,'attached_plugin',dict(name='gz::sim::systems::OdometryPublisher',filename='gz-sim-odometry-publisher-system',slot=2,xml_sha256='b'*64,effective_sdf={'odom_topic':'/model/rover1/odometry'})),
        (4,'pose_input',dict(state_generation=1,sim_time_s=.1,input_link_entity=44,link_parent_chain=[44,43,42],link_reaches_model=True,world_link_pose_m_xyzw=[0,1,2,0,0,0,1],world_model_pose_m_xyzw=[0,1,2,0,0,0,1],fdm_pose_m_xyzw=[0,-1,-2,0,0,0,1])),
        (5,'fdm_send',dict(state_generation=1,socket_observation=socket,destination_address='127.0.0.1',destination_port=55001,bytes_sent=300,bytes_expected=300))]]


def expected():return dict(pid=70,start_ticks=800,boot_id='fixture')


def test_instantiated_model_pose_and_fdm_do_not_credit_ros_or_sysid():
    rows=v.model_records(['launch TFG_MODEL_TRACE '+json.dumps(r) for r in fixture_records()])
    r=v.assess_model_source(rows,expected())
    assert r['state']=='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY'
    assert r['models'][0]['model_entity']==42 and r['models'][0]['states'][0]['socket']['inode']==123
    assert 'effective SYSID' in r['pending'] and not r['identity_verified'] and not r['movement_authorized']
    rows[2]['effective_sdf']['odom_topic']=None
    assert v.assess_model_source(rows,expected())['models'][0]['route_default_unknown']


@pytest.mark.parametrize('case',['other_boot','duplicate_plugin','missing_pose','unbound_state','send_error','inode_changed','ancestry_cycle','entity_changed','nonfinite'])
def test_model_source_uncertainty_never_promoted(case):
    rows=fixture_records();owner=expected()
    if case=='other_boot':owner['boot_id']='other'
    elif case=='duplicate_plugin':rows.append({**rows[2],'sequence':6,'slot':3})
    elif case=='missing_pose':rows.pop(3)
    elif case=='unbound_state':rows[-1]['state_generation']=2
    elif case=='send_error':rows[-1]['bytes_sent']=-1
    elif case=='inode_changed':rows[-1]['socket_observation']={**rows[-1]['socket_observation'],'inode':124}
    elif case=='ancestry_cycle':rows[3]['link_parent_chain']=[44,43,44,42]
    elif case=='entity_changed':rows[-1]['model_entity']=43
    else:rows[3]['world_link_pose_m_xyzw'][0]=None
    r=v.assess_model_source(rows,owner)
    assert r['state']=='UNKNOWN' and not r['identity_verified'] and not r['movement_authorized']


@pytest.mark.parametrize('case',['gap','duplicate','cap','incomplete'])
def test_model_records_and_drain_preserve_incomplete(tmp_path,case):
    rows=fixture_records()
    if case=='gap':rows.pop(1)
    elif case=='duplicate':rows.append(rows[-1])
    elif case=='cap':rows[-1]['sequence']=32
    else:rows[-1]['incomplete']=True
    with pytest.raises(ValueError):v.model_records(['TFG_MODEL_TRACE '+json.dumps(r) for r in rows])
    p=tmp_path/'trace'
    with p.open('w+b') as f:
        drain=m.Drain(f);drain.feed(b'launch TFG_MODEL_TRACE {"event":"error","incomplete":true}\n');drain.finish()
        assert drain.records==1 and drain.errors
    assert p.read_bytes().startswith(b'TFG_MODEL_TRACE ')


def test_model_source_copy_preserves_original_and_one_send(tmp_path,monkeypatch):
    source=tmp_path/'source';(source/'src').mkdir(parents=True);(source/'include').mkdir()
    cpp='''  gzlog << "[" << this->dataPtr->modelName << "] "
        << "ArduPilot ready to fly. original";
    // require the duration since sim start in seconds
#if DEBUG_JSON_IO
    auto bytes_sent =
#endif
    this->dataPtr->sock.sendto(
        this->dataPtr->json_str.c_str(),this->dataPtr->json_str.size(),this->dataPtr->fcu_address,
        this->dataPtr->fcu_port_out);

#if DEBUG_JSON_IO
    original_debug(bytes_sent);
#endif
unchanged_motor_forces();
'''
    socket='class SocketUDP { public: void existing(); private: int fd=-1; };'
    (source/'src/ArduPilotPlugin.cc').write_text(cpp);(source/'include/SocketUDP.hh').write_text(socket)
    monkeypatch.setattr(prep,'PINNED',{p:hashlib.sha256((source/p).read_bytes()).hexdigest() for p in prep.PINNED})
    result=prep.prepare(source,tmp_path/'copy');patched=(tmp_path/'copy/src/ArduPilotPlugin.cc').read_text()
    assert (source/'src/ArduPilotPlugin.cc').read_text()==cpp and (source/'include/SocketUDP.hh').read_text()==socket
    assert patched.count('sock.sendto(')==1 and 'unchanged_motor_forces();' in patched
    assert 'tfg_model_trace::state' in patched and not result['loaded'] and not result['default_enabled']
    with pytest.raises(ValueError):prep.prepare(source,tmp_path/'copy')
    (source/'include/SocketUDP.hh').write_text('changed')
    with pytest.raises(ValueError):prep.prepare(source,tmp_path/'other')
    assert not (tmp_path/'other').exists()


def test_native_diagnostic_default_off_no_simulation(tmp_path):
    source=tmp_path/'scope.cpp';binary=tmp_path/'scope'
    source.write_text('''#include "model_trace.hpp"
struct V{double X()const{return 0;}double Y()const{return 0;}double Z()const{return 0;}};
struct Q:V{double W()const{return 1;}};
struct P{V Pos()const{return {};}Q Rot()const{return {};}};
int main(){int object=0;tfg_model_trace::configured(&object,42,-1,P{},P{});
try{tfg_model_trace::config("<odom_topic>a</odom_topic><odom_topic>b</odom_topic>");return 4;}catch(...){}
return 0;}
''')
    flags=subprocess.check_output(['pkg-config','--cflags','gz-sim8','tinyxml2'],text=True).split()
    libraries=subprocess.check_output(['pkg-config','--libs','gz-sim8','tinyxml2'],text=True).split()
    subprocess.run(['g++','-std=c++17','-pthread',*flags,'-I',str(ROOT/'tools/rover_xrce_trace/model_probe'),'-I',str(ROOT/'tools/rover_xrce_trace'),str(source),'-o',str(binary),*libraries,'-ltinyxml2','-lcrypto'],check=True,capture_output=True)
    env={k:x for k,x in os.environ.items() if k!='TFG_MODEL_TRACE'}
    assert subprocess.run([str(binary)],env=env,check=True,capture_output=True).stderr==b''
    env['TFG_MODEL_TRACE']='1';r=subprocess.run([str(binary)],env=env,check=True,capture_output=True)
    rows=v.model_records(r.stderr.decode().splitlines());assert len(rows)==1 and rows[0]['event']=='configured'
    assert rows[0]['socket_observation'] is None  # no socket created by this fixture


def test_real_partial_trial_monitor_blocks_reader():
    history=ROOT/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/5379b30c-ac91-4cc8-808b-a7c28bb41801'
    record=json.loads((history/'container-capture/monitor.json').read_bytes())
    assert record['phase']=='INCOMPLETE' and record['capture_complete'] is False
    assert record['identity_bridge']['verified_overlay_library'] is True
    with pytest.raises(ValueError):m.capture_window(record,now=record['observation_monotonic'],observed_boot_id=record['monitor']['boot_id'])
    assert not (history/'reader-command.json').exists()


def test_model_trigger_closes_fd_on_short_read_and_invalid_metadata(tmp_path):
    """Real header, wrapped libc only. No plugin load, files, sockets or nodes."""
    source=tmp_path/'trigger.cpp';binary=tmp_path/'trigger'
    source.write_text(r'''#include "model_trace.hpp"
#include <cassert>
int opened=0,closed=0,scenario=0;
const char* id="12345678-1234-4234-8234-123456789abc";
extern "C" int __wrap_open(const char*,int,...){++opened;return 234;}
extern "C" ssize_t __wrap_read(int,char* p,size_t){std::string s=std::string(id)+"\n";memcpy(p,s.data(),s.size());return scenario==1?5:scenario==2?-1:37;}
extern "C" int __wrap_fstat(int,struct stat* s){*s={};s->st_mode=S_IFREG|0600;s->st_uid=geteuid();if(scenario==3)s->st_mode=S_IFREG|0644;return scenario==4?-1:0;}
extern "C" int __wrap_close(int fd){assert(fd==234);++closed;return scenario==5?-1:0;}
int main(int argc,char** argv){scenario=std::atoi(argv[1]);setenv("TFG_MODEL_SESSION",id,1);
std::string path="/tmp/tfg_diagnostic_agents/"+std::string(id)+"/capture/model_request";
setenv("TFG_MODEL_REQUEST_PATH",path.c_str(),1);bool accepted=false;
try{accepted=tfg_model_trace::capture_requested();}catch(const std::runtime_error&){}
assert(opened==1&&closed==1);assert(accepted==(scenario==0));}
''')
    flags=subprocess.check_output(['pkg-config','--cflags','gz-sim8','tinyxml2'],text=True).split()
    libs=subprocess.check_output(['pkg-config','--libs','gz-sim8','tinyxml2'],text=True).split()
    subprocess.run(['g++','-std=c++17','-pthread',*flags,'-I',str(ROOT/'tools/rover_xrce_trace/model_probe'),'-I',str(ROOT/'tools/rover_xrce_trace'),str(source),'-o',str(binary),*libs,'-lcrypto',
                    '-Wl,--wrap=open','-Wl,--wrap=read','-Wl,--wrap=fstat','-Wl,--wrap=close'],check=True,capture_output=True)
    for scenario in range(6):subprocess.run([str(binary),str(scenario)],check=True,capture_output=True)
