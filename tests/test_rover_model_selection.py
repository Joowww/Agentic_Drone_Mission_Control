"""Synthetic ELF/proc contracts. No library is loaded or simulator started."""
import hashlib
import json
from pathlib import Path
import subprocess
import pytest
from tools.rover_xrce_trace import selection as s, monitor as m
from tests.test_rover_diagnostic_selection import OWNER


@pytest.fixture
def model(tmp_path,monkeypatch):
    manifest=dict(schema=s.MODEL_SCHEMA,engine_id='fixture',container_id='a'*64,image_id='sha256:'+'b'*64)
    for key in ('wrapper','library','bridge','bridge_library','model_library'):
        path=tmp_path/key;path.write_bytes(b'\x7fELF fixture '+key.encode())
        manifest[key+'_path']=str(path);manifest[key+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(s,'ROOT',tmp_path/'overlays')
    monkeypatch.setattr(s,'IDENTITY_ARTIFACTS',tuple(manifest[k+'_sha256'] for k in ('wrapper','library','bridge','bridge_library')))
    monkeypatch.setattr(s,'MODEL_LIBRARY_SHA256',manifest['model_library_sha256'])
    info={'wrapper':dict(needed=['libmicroxrcedds_agent.so.2.4'],soname=[]),
          'library':dict(needed=['librmw_fastrtps_shared_cpp.so'],soname=['libmicroxrcedds_agent.so.2.4']),
          'bridge':dict(needed=['libros_gz_bridge.so'],soname=[]),
          'bridge_library':dict(needed=[],soname=['libros_gz_bridge.so']),
          'model_library':dict(needed=['libgz-sim8.so.8'],soname=['libTFGArduPilotIdentity.so'])}
    value=s.descriptor(manifest,OWNER);s.prepare_overlay(value,elf_reader=lambda p:info[Path(p).name])
    return value


def test_one_isolated_plugin_slot_and_explicit_environment(model):
    p=Path(model['prefix']);env,_=s.configure({s.ENV:json.dumps(model),'GZ_SIM_SYSTEM_PLUGIN_PATH':'installed'})
    assert env['GZ_SIM_SYSTEM_PLUGIN_PATH']==str(p)+'/lib:installed'
    assert env['TFG_MODEL_SESSION']==OWNER and env['TFG_MODEL_REQUEST_PATH']==str(p)+'/capture/model_request'
    assert (p/'lib/libArduPilotPlugin.so').read_bytes()==Path(model['manifest']['model_library_path']).read_bytes()
    assert not (p/'lib/libTFGArduPilotIdentity.so').exists()  # no second plugin slot/SDF insertion
    normal,_=s.configure({'TFG_MODEL_TRACE':'1','TFG_MODEL_SESSION':'old','TFG_MODEL_REQUEST_PATH':'old'})
    assert not normal


@pytest.mark.parametrize('bad',['other_session','mixed','duplicate','recycled','altered'])
def test_model_supervision_rejects_mix_and_replacement(model,bad):
    root=dict(pid=9,ppid=1,start_ticks=10,boot_id='boot')
    process=dict(pid=70,ppid=9,start_ticks=80,boot_id='boot',argv=['gz','sim'],executable='/usr/bin/gz')
    event=dict(event='configured',pid=70,process_start_ticks='80',boot_id='boot',model_entity=42,lifecycle_id=OWNER)
    rows=[event];maps='000-001 r-x 0 00:00 0 '+model['prefix']+'/lib/libArduPilotPlugin.so\n000-001 r-x 0 00:00 0 /installed/libgz-sim8.so.8'
    if bad=='other_session':event['lifecycle_id']='other'
    elif bad=='mixed':maps+='\n000-001 r-x 0 00:00 0 /installed/libArduPilotPlugin.so'
    elif bad=='duplicate':rows.append(dict(event,plugin_instance=2))
    elif bad=='recycled':process['start_ticks']=81
    else:
        path=Path(model['prefix'])/'lib/libArduPilotPlugin.so';path.chmod(0o600);path.write_bytes(b'altered')
        with pytest.raises(ValueError):s.verify_overlay(model)
        return
    with pytest.raises(ValueError):m.verify_model_library(model,root,rows,process_reader=lambda pid:process if pid==70 else root,maps_reader=lambda pid:maps)


def test_model_same_process_three_distinct_entities_and_libraries(model):
    root=dict(pid=9,ppid=1,start_ticks=10,boot_id='boot')
    p=dict(pid=70,ppid=9,start_ticks=80,boot_id='boot',argv=['gz','sim'],executable='/usr/bin/gz')
    rows=[dict(event='configured',pid=70,process_start_ticks='80',boot_id='boot',model_entity=e,lifecycle_id=OWNER) for e in (42,43,44)]
    maps='000-001 r-x 0 00:00 0 '+model['prefix']+'/lib/libArduPilotPlugin.so\n000-001 r-x 0 00:00 0 /installed/libgz-sim8.so.8'
    r=m.verify_model_library(model,root,rows,process_reader=lambda pid:p if pid==70 else root,maps_reader=lambda pid:maps)
    assert r['entities_observed']==[42,43,44] and r['verified_overlay_library']


def test_spaced_retention_real_cpp_core_without_ros(tmp_path):
    source=tmp_path/'quota.cpp';binary=tmp_path/'quota'
    source.write_text('''#include "retention.hpp"
#include <cassert>
int main(){tfg_identity_probe::Retention q;
assert(!q.retain_at("odom",3,1));assert(q.before_status["odom"]==1);
assert(q.retain_at("/ap/v3/status",1,100));
assert(q.retain_at("odom",3,100));assert(!q.retain_at("odom",3,499999999));
assert(q.omitted_by_spacing["odom"]==1);assert(!q.retain_at("odom",3,99));
assert(q.clock_rewinds["odom"]==1);
assert(q.retain_at("odom",3,500000100));assert(q.retain_at("odom",3,1000000100));
for(auto topic:{"gps1","gps2","gps3","geo1","geo2","geo3"})for(int n=0;n<2;++n)assert(q.retain_at(topic,2,100+n*500000000LL));
for(int n=0;n<4;++n)assert(q.retain_at("world",4,100+n*500000000LL));
assert(q.samples==20);assert(!q.retain_at("new",1,1));q.open=false;assert(!q.retain_at("world",4,2000000100));}
''')
    include=Path(__file__).resolve().parents[1]/'tools/rover_identity_probe'
    subprocess.run(['g++','-std=c++17','-I',str(include),str(source),'-o',str(binary)],check=True,capture_output=True)
    subprocess.run([str(binary)],check=True,capture_output=True)
