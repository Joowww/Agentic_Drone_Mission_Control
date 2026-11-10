"""Synthetic passive contracts only; no ROS nodes, vehicle services or runtime writes."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import pytest
from tools import rover_passive_validation as v
from tools.rover_xrce_trace import selection as s,monitor as m
from tests.test_rover_diagnostic_selection import artifacts


def point(i,x,y,*,error=.001,quant=.001):
    return dict(observation_id=i,session_id='fixture',source_frame='source',target_frame='target',
        source_ref='fixture/source/'+i,target_ref='fixture/target/'+i,uncertainty_ref='fixture/error',resolution_ref='fixture/resolution',
        source_receipt_s=10,target_receipt_s=10.01,source_stamp_s=2,target_stamp_s=2.01,source_clock='fixture-clock',target_clock='fixture-clock',clock_contract_ref='fixture/clock',source_xy_m=[x,y],target_xy_m=[5-y,8+x],
        uncertainty_radius_m=error,quantization_radius_m=quant)


def dataset():
    return dict(session_id='fixture',source_frame='source',target_frame='target',fit=[point('a',0,0),point('b',10,0)],
        holdout=[point('c',4,5)],required_error_bound_m=.1,max_pair_skew_s=.1)


def test_separate_fit_holdout_and_propagated_calibration_uncertainty():
    result=v.evaluate_transform(dataset())
    assert result['state']=='NUMERICALLY_SUPPORTED_ONLY' and not result['frame_transform_verified']
    assert result['holdout'][0]['residual_m']<1e-9 and result['holdout'][0]['calibration_bound_m']>0
    d=dataset();d['holdout'][0]=point('c',10000,10000)
    assert v.evaluate_transform(d)['state']=='REJECTED'  # fit uncertainty grows away from the baseline


@pytest.mark.parametrize('case',['reuse','stationary','mixed','missing_accuracy','time','contradiction','quantization'])
def test_missing_degrees_of_freedom_or_evidence_never_approved(case):
    d=dataset()
    if case=='reuse':d['holdout']=[d['fit'][0]]
    elif case=='stationary':d['fit'][1]['source_xy_m']=[0,0]
    elif case=='mixed':d['holdout'][0]['session_id']='other'
    elif case=='missing_accuracy':d['fit'][0]['uncertainty_radius_m']=None
    elif case=='time':d['holdout'][0]['target_receipt_s']=100
    elif case=='contradiction':d['holdout'][0]['target_xy_m']=[100,100]
    else:d['fit'][0]['quantization_radius_m']=v.quantization_radius(41,1e-5,1e-5)
    r=v.evaluate_transform(d)
    assert r['state'] in {'UNKNOWN','REJECTED'} and not r['movement_authorized']


def test_geodetic_axes_and_resolution_is_not_accuracy():
    assert v.geodetic_enu(41,2,41,2)==(0,0)
    assert v.geodetic_enu(41,2.00001,41,2)[0]>0
    assert v.geodetic_enu(41.00001,2,41,2)[1]>0
    assert .006<v.quantization_radius(41,1e-7,1e-7)<.008
    with pytest.raises(ValueError):v.quantization_radius(41,0,1e-7)


def events():
    context=dict(pid=1,process_start_ticks='20',boot_id='boot',client_instance=2,client_key=3,session_id=129,attempt=4,object_id=5,entity_kind='replier')
    return [{**context,'schema':'tfg.identity-trace/1','wall_unix_ns':100,'steady_ns':100,'sequence':i,'event':event,**fields} for i,event,fields in [
        (1,'replier_created',dict(request_topic='rq/ap/v3/get_parametersRequest',reply_topic='rr/ap/v3/get_parametersReply',
            request_type='rcl_interfaces::srv::dds_::GetParameters_Request_',reply_type='rcl_interfaces::srv::dds_::GetParameters_Response_',domain=0)),
        (2,'entity_commit',dict(committed=True)),
        (3,'rpc_request',dict(accepted=True,request_writer_guid='01'*16,request_sequence_high=0,request_sequence_low=8)),
        (4,'rpc_reply',dict(accepted=True,request_writer_guid='01'*16,request_sequence_high=0,request_sequence_low=8))]]


def test_legacy_parameter_guid_coincidence_cannot_replace_received_sample_info():
    rows=events();reply=dict(endpoint='/ap/v3/get_parameters',request_writer_guid='01'*16,request_sequence=8,values={'MAV_SYSID':3})
    writer={**rows[0],'domain':0}
    result=v.correlate_parameter(reply,rows,writer)
    assert result['state']=='UNKNOWN' and 'received SampleInfo' in result['reason']
    assert result['native_exchange']['state']=='NATIVE_REPLIER_AND_EXCHANGE_CONTEXT_OBSERVED'
    for key in ('process_start_ticks','client_instance','client_key','session_id','domain'):
        changed={**writer,key:999}
        assert v.correlate_parameter(reply,rows,changed)['state']=='UNKNOWN'
    for change in ['missing_commit','wrong_sequence','duplicate','type','order']:
        changed=copy.deepcopy(rows)
        if change=='missing_commit':changed.pop(1)
        elif change=='wrong_sequence':changed[-1]['request_sequence_low']=9
        elif change=='duplicate':changed.append(changed[-1])
        elif change=='type':changed[0]['request_type']='other'
        else:changed[-1]['sequence']=2
        assert v.correlate_parameter(reply,changed,writer)['state']=='UNKNOWN'


def test_identity_trace_monitor_preserves_both_prefixes_and_rejects_truncation(tmp_path):
    out=tmp_path/'trace'
    with out.open('w+b') as stream:
        drain=m.Drain(stream)
        for row in events():drain.feed(('launch: TFG_IDENTITY_TRACE '+json.dumps(row)+'\n').encode())
        drain.feed(b'TFG_XRCE_TRACE {"event":"fixture"}\n');drain.finish()
        assert drain.records==5 and not drain.errors
    assert len(v.identity_records(out.read_text().splitlines()))==4
    missing=events();missing.pop(2)
    with pytest.raises(ValueError):v.identity_records(['TFG_IDENTITY_TRACE '+json.dumps(r) for r in missing])
    with out.open('w+b') as stream:
        drain=m.Drain(stream);drain.feed(b'TFG_IDENTITY_TRACE {');drain.finish()
        assert 'Truncated final trace line' in drain.errors


def test_identity_overlay_uses_all_four_exact_artifacts(artifacts,monkeypatch,tmp_path):
    value,oldelf=artifacts;manifest=value['manifest']
    for name in ('bridge','bridge_library'):
        p=tmp_path/name;p.write_bytes(b'\x7fELF '+name.encode());manifest[name+'_path']=str(p);manifest[name+'_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    manifest['schema']=s.IDENTITY_SCHEMA
    monkeypatch.setattr(s,'IDENTITY_ARTIFACTS',tuple(manifest[k+'_sha256'] for k in s.artifact_names(manifest)))
    value=s.descriptor(manifest,value['lifecycle_id'])
    def elf(path):
        if str(path)==manifest['bridge_path']:return dict(needed=['libros_gz_bridge.so'],soname=[])
        if str(path)==manifest['bridge_library_path']:return dict(needed=[],soname=['libros_gz_bridge.so'])
        return oldelf(path)
    s.prepare_overlay(value,elf_reader=elf);prefix=Path(value['prefix'])
    assert (prefix/'lib/ros_gz_bridge/parameter_bridge').read_bytes()==Path(manifest['bridge_path']).read_bytes()
    assert s.check_frozen_descriptor(value)==value
    p=prefix/'lib/libros_gz_bridge.so';p.chmod(0o600);p.write_bytes(b'\x7fELF changed')
    with pytest.raises(ValueError):s.configure({s.ENV:json.dumps(value)})


def test_bridge_native_gid_and_process_are_separate_from_graph(artifacts):
    value,_=artifacts;p=dict(pid=3,start_ticks=22,boot_id='boot',executable=value['prefix']+'/lib/ros_gz_bridge/parameter_bridge',ppid=2,argv=['bridge','--ros-args','-r','__ns:=/rover1'])
    root=dict(pid=2,start_ticks=20,boot_id='boot',ppid=1)
    value['manifest']['bridge_library_sha256']='fixture'
    expected=value['prefix']+'/lib/libros_gz_bridge.so'
    reader=lambda pid:p if pid==3 else root
    actual=m.verify_bridge(value,root,[p],maps_reader=lambda pid:'0-1 r-x 0 00:00 1 '+expected,process_reader=reader)
    event=dict(sequence=2,event='bridge_subscription',gid='01'*24,rmw='rmw_fastrtps_cpp',ros_topic='/rover1/odometry',gz_topic='/model/rover1/odometry',
        ros_type='nav_msgs/msg/Odometry',gz_type='gz.msgs.Odometry',pid=3,process_start_ticks='22',boot_id='boot',config_file='/tmp/config.yaml')
    sample=dict(message_gid='01'*24,rmw='rmw_fastrtps_cpp',from_intra_process=False)
    publisher={**event,'sequence':1,'event':'bridge_publisher'}
    r=v.correlate_bridge(sample,[publisher,event],[actual]);assert r['state']=='SAMPLE_TO_BRIDGE_PROCESS_OBSERVED' and not r['model_identity_verified']
    assert v.correlate_bridge(sample,[event],[])['state']=='UNKNOWN'
    assert v.correlate_bridge({**sample,'message_gid':'02'*24},[event],[actual])['state']=='UNKNOWN'
    with pytest.raises(ValueError):m.verify_bridge(value,root,[p],maps_reader=lambda pid:'0-1 r-x 0 00:00 1 /installed/libros_gz_bridge.so',process_reader=reader)


def test_native_probe_has_no_control_or_default_execution_route():
    root=Path(__file__).resolve().parents[1];source=(root/'tools/rover_identity_probe/probe.cpp').read_text();source=''.join(source.split())
    assert 'create_publisher' not in source and 'Params=rcl_interfaces::srv::GetParameters' in source
    assert 'take_response(response,info)' in source and 'MutuallyExclusive,false' in source
    assert 'probe_session_id' in source and 'queries.clear()' in source
    assert 'std::chrono::seconds(120)' in source and '512*1024' in source
    assert '"/ap/v3/status",1' in source and '"/rover1/odometry",3' in source
    assert 'count.find("/ap/v3/status")==count.end()' in ''.join((root/'tools/rover_identity_probe/retention.hpp').read_text().split())
    assert not any('rover_identity_probe' in p.read_text() for p in (root/'simulation/ros2_gazebo/launch').glob('*.py'))


def test_native_identity_default_off_context_and_recreation(tmp_path):
    root=Path(__file__).resolve().parents[1];src=tmp_path/'test.cpp';binary=tmp_path/'test'
    src.write_text('''#include "identity_trace.hpp"
int main(){tfg_identity_trace::Scope a(1,5,129,9,"replier");a.commit(true);
{tfg_identity_trace::Scope b(2,5,129,9,"replier");b.commit(true);}a.commit(false);}
''')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-pthread','-I',str(root/'tools/rover_xrce_trace'),str(src),'-o',str(binary)],check=True,capture_output=True)
    env={k:x for k,x in os.environ.items() if k!='TFG_XRCE_TRACE'}
    assert subprocess.run([str(binary)],capture_output=True,env=env,check=True).stderr==b''
    env['TFG_XRCE_TRACE']='1';out=subprocess.run([str(binary)],capture_output=True,env=env,check=True).stderr
    rows=v.identity_records(out.decode().splitlines());assert [r['client_instance'] for r in rows]==[1,2,1]


def test_combined_budget_includes_reader_trace_and_close(monkeypatch):
    from tools.rover_xrce_trace.budget import SOCKET
    record={'socket_inventory':dict(journal_bytes_written=256*1024,snapshots=1)}
    monkeypatch.setattr(v,'capture_window',lambda *a,**kw:dict(capture_budget_s=140,close_budget_s=60))
    r=v.session_window(record,now=10,boot_id='fixture')
    assert r['future_socket_rows']==41
    assert r['projected_total_bytes']==13631488 and r['aggregate_limit_bytes']==16*1024*1024
    record['socket_inventory']['journal_bytes_written']=5*1024*1024
    with pytest.raises(ValueError):v.session_window(record,now=10,boot_id='fixture')
    record['socket_inventory'].update(journal_bytes_written=10,snapshots=24)
    with pytest.raises(ValueError):v.session_window(record,now=10,boot_id='fixture')


def test_new_reader_journal_requires_footer_receipt_and_truthful_counts(tmp_path):
    base=dict(schema='tfg.rover-passive-validation/1',status='BLOCKED',movement_authorized=False,receipt_wall_ns=10)
    rows=[{**base,'kind':'header','session_id':'fixture','probe_session_id':'fixture','receipt_steady_ns':1},
          {**base,'kind':'sample','topic':'/ap/v3/status','message_gid':'01'*24,'receipt_steady_ns':2},
          {**base,'kind':'footer','session_id':'fixture','counts':{'/ap/v3/status':1},'reader_closed':True,'receipt_steady_ns':3}]
    journal=tmp_path/'journal';receipt=tmp_path/'receipt'
    receipt.write_text(json.dumps(dict(schema='tfg.rover-passive-validation-receipt/1',session_id='fixture',reader_closed=True)))
    raw=''.join(json.dumps(row)+'\n' for row in rows);journal.write_text(raw)
    assert v.read_journal(journal,receipt)['counts']=={'/ap/v3/status':1}
    for changed in (raw[:-1],raw.splitlines()[0]+'\n',raw.replace('"/ap/v3/status": 1','"/ap/v3/status": 2')):
        journal.write_text(changed)
        with pytest.raises(ValueError):v.read_journal(journal,receipt)
    journal.write_text(raw);receipt.write_text('{"session_id":"other"}')
    with pytest.raises(ValueError):v.read_journal(journal,receipt)


def test_actual_retention_core_caps_and_anchors_without_ros(tmp_path):
    root=Path(__file__).resolve().parents[1];src=tmp_path/'quota.cpp';exe=tmp_path/'quota'
    src.write_text(r'''#include "retention.hpp"
#include <cassert>
int main(){tfg_identity_probe::Retention q;
for(int i=0;i<1000;++i)assert(!q.retain("odom",3));
assert(q.before_status["odom"]==1000&&q.samples==0);
assert(q.retain("/ap/v3/status",1));assert(!q.retain("/ap/v3/status",1));
for(int i=0;i<3;++i)assert(q.retain("odom",3));assert(!q.retain("odom",3));
for(int i=0;i<4;++i)assert(q.retain("gazebo",4));
for(auto name:{"gps1","gps2","gps3","geo1","geo2","geo3"})for(int j=0;j<2;++j)assert(q.retain(name,2));
assert(q.samples==20);assert(!q.retain("unexpected",1));q.open=false;assert(!q.retain("closed",1));
}
''')
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I',str(root/'tools/rover_identity_probe'),str(src),'-o',str(exe)],check=True,capture_output=True)
    subprocess.run([str(exe)],check=True,capture_output=True)


def test_intended_routes_require_same_generation_commit_not_service_name_only():
    rows=events();ctx=rows[0];writer={**ctx}
    input_row={**ctx,'event':'input_created','sequence':5,'attempt':9,'object_id':99,'entity_kind':'datareader',
        'topic':'rt/ap/v3/cmd_vel','type':'geometry_msgs::msg::dds_::TwistStamped_'}
    commit={**input_row,'event':'entity_commit','sequence':6,'committed':True}
    result=v.transport_routes(rows+[input_row,commit],writer)
    assert result['/ap/v3/cmd_vel']['state']=='XRCE_ENTITY_CONTEXT_OBSERVED'
    assert result['/ap/v3/mode_switch']['state']=='UNKNOWN' and not result['/ap/v3/cmd_vel']['control_command_sent']
    assert v.transport_routes(rows+[input_row],writer)['/ap/v3/cmd_vel']['state']=='UNKNOWN'
    assert v.transport_routes(rows+[input_row,commit],{**writer,'client_instance':3})['/ap/v3/cmd_vel']['state']=='UNKNOWN'


def test_whole_saved_reader_analysis_keeps_legacy_rpc_unattributed(tmp_path):
    from tests.test_rover_xrce_trace import row
    journal=tmp_path/'journal';receipt=tmp_path/'receipt';trace=tmp_path/'trace';monitor=tmp_path/'monitor'
    base=dict(schema='tfg.rover-passive-validation/1',status='BLOCKED',movement_authorized=False,receipt_wall_ns=10)
    rows=[{**base,'kind':'header','session_id':'fixture','probe_session_id':'fixture','boot_id':'boot','receipt_steady_ns':1},
          {**base,'kind':'sample','topic':'/ap/v3/status','message_gid':'02'*24,'rmw':'rmw_fastrtps_cpp','from_intra_process':False,'receipt_steady_ns':2},
          {**base,'kind':'parameter_reply','endpoint':'/ap/v3/get_parameters','request_writer_guid':'01'*16,'request_sequence':8,'values':{'MAV_SYSID':3},'receipt_steady_ns':3},
          {**base,'kind':'footer','session_id':'fixture','counts':{'/ap/v3/status':1},'reader_closed':True,'receipt_steady_ns':4}]
    journal.write_text(''.join(json.dumps(r)+'\n' for r in rows));receipt.write_text(json.dumps(dict(schema='tfg.rover-passive-validation-receipt/1',session_id='fixture',reader_closed=True)))
    native=[row('dds_writer'),row('xrce_result')]
    identity=[{**e,'pid':10,'process_start_ticks':'123','client_instance':1,'client_key':0xad000003} for e in events()]
    trace.write_text(''.join('TFG_XRCE_TRACE '+json.dumps(r)+'\n' for r in native)+''.join('TFG_IDENTITY_TRACE '+json.dumps(r)+'\n' for r in identity))
    monitor.write_text(json.dumps(dict(lifecycle_id='fixture',errors=[],phase='CLOSED',capture_complete=True,monitor={'boot_id':'boot'},started_monotonic=0,finished_monotonic=1)))
    result=v.analyze_reader(journal,receipt,trace,monitor)
    assert result['parameters']['state']=='UNKNOWN'
    assert result['parameters']['native_exchange']['state']=='NATIVE_REPLIER_AND_EXCHANGE_CONTEXT_OBSERVED'
    assert result['counts']=={'/ap/v3/status':1} and result['frame_transform']['state']=='UNKNOWN'
    assert result['state']=='BLOCKED' and not result['source_association_verified']
    from tests.test_rover_model_source import fixture_records,expected
    records=[{**r,'lifecycle_id':'fixture','boot_id':'boot'} for r in fixture_records()]
    with trace.open('a') as f:f.write(''.join('TFG_MODEL_TRACE '+json.dumps(r)+'\n' for r in records))
    monitored=json.loads(monitor.read_bytes());monitored['model_source']={**expected(),'boot_id':'boot','verified_overlay_library':True}
    monitor.write_text(json.dumps(monitored))
    assert v.analyze_reader(journal,receipt,trace,monitor)['model_source']['state']=='MODEL_SOURCE_CONTEXT_OBSERVED_ONLY'
    # A valid trace in another session is still not this capture's source.
    trace.write_text(trace.read_text().replace('"lifecycle_id": "fixture"','"lifecycle_id": "other"'))
    assert v.analyze_reader(journal,receipt,trace,monitor)['model_source']['state']=='UNKNOWN'
    monitor.write_text(json.dumps(dict(lifecycle_id='other',errors=[],phase='CLOSED',capture_complete=True)))
    with pytest.raises(ValueError):v.analyze_reader(journal,receipt,trace,monitor)
