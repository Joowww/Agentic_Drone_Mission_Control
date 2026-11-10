"""Synthetic native context tests, not a running DDS/ROS agent."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tools.rover_xrce_trace.analyze import analyze
from tools.rover_xrce_trace.prepare import prepare

ROOT = Path(__file__).resolve().parents[1]


def row(event, attempt=1, instance=1, key=0xad000003, guid='01'*16, gid='02'*24):
    return dict(schema='tfg.xrce-writer/1',event=event,pid=10,boot_id='boot',process_start_ticks='123',
                sequence=attempt*2-1+(event=='xrce_result'),wall_unix_ns=100,steady_ns=100+(event=='xrce_result'),
                client_instance=instance,attempt=attempt,client_key=key,session_id=0x81,writer_id=5,
                native_guid=guid,rmw_gid=gid,rmw_identifier='rmw_fastrtps_cpp',
                topic='rt/ap/v3/status',type='ardupilot_msgs::msg::dds_::Status_',domain=0,committed=True)


def run(rows):
    return analyze(['TFG_XRCE_TRACE '+json.dumps(r) for r in rows])


def test_multiple_clients_reusing_object_and_session_not_joined():
    a=[row('dds_writer'),row('xrce_result')]
    b=[row('dds_writer',2,2,0xad000001,'03'*16,'04'*24),row('xrce_result',2,2,0xad000001)]
    r=run([b[1],a[0],b[0],a[1]])  # order is deliberately irrelevant
    assert r['trace_valid'] and len(r['correlations'])==2
    assert r['status']=='BLOCKED' and not r['source_association_verified']


def test_writer_recreated_gets_new_attempt_and_guid():
    rows=[row('dds_writer'),row('xrce_result'),row('dds_writer',2,guid='03'*16,gid='04'*24),row('xrce_result',2)]
    assert run(rows)['trace_valid']
    rows[2]['rmw_gid']=rows[0]['rmw_gid']
    assert not run(rows)['trace_valid']


@pytest.mark.parametrize('case',['missing','contradiction','process','failed','cap','empty_gid','no_topic','duplicate'])
def test_incomplete_contradictory_never_correlated(case):
    rows=[row('dds_writer'),row('xrce_result')]
    if case=='missing': rows.pop()
    elif case=='contradiction': rows[1]['client_key']=1
    elif case=='process': rows[1]['process_start_ticks']='456'
    elif case=='failed': rows[1]['committed']=False
    elif case=='cap': rows[1]['event']='trace_limit';rows[1]['incomplete']=True
    elif case=='empty_gid': rows[0]['rmw_gid']='00'*24
    elif case=='no_topic': rows[0]['topic']=None
    else: rows.append(rows[0])
    result=run(rows)
    assert not result['trace_valid'] and result['correlations']==[]
    assert result['movement_authorized'] is False


def test_patch_wrong_source_fails_before_copy(tmp_path):
    source=tmp_path/'source';source.mkdir()
    for n in ['src/cpp/client/ProxyClient.cpp','src/cpp/middleware/fastdds/FastDDSMiddleware.cpp']:
        p=source/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('wrong source')
    target=tmp_path/'copy'
    with pytest.raises(ValueError,match='hash'): prepare(source,target)
    assert not target.exists()


def test_native_scope_contract_offline(tmp_path):
    compiler=shutil.which('g++')
    assert compiler, 'Existing host C++ compiler required for offline native regression'
    source=tmp_path/'test.cpp';binary=tmp_path/'test'
    source.write_text('''#include "trace.hpp"
int main() {
 if (std::getenv("TFG_TEST_CAP")) {
   for (int i=0;i<600;++i) tfg_xrce_trace::emit("\\\"event\\\":\\\"unbound_writer\\\",\\\"incomplete\\\":true");
   return 0;
 }
 if (std::getenv("TFG_TEST_PIPE")) { int fds[2]; if (::pipe(fds)!=0) return 3; ::close(fds[0]); ::dup2(fds[1],2); ::close(fds[1]); tfg_xrce_trace::emit("{}"); return 0; }
 if (std::getenv("TFG_TEST_WRITE_ERROR")) { ::close(2); tfg_xrce_trace::emit("{} "); return 0; }
 tfg_xrce_trace::Scope a(1,1,129,5);
 {tfg_xrce_trace::Scope b(2,2,129,5);
 tfg_xrce_trace::writer(5,"03030303030303030303030303030303","040404040404040404040404040404040404040404040404","rmw_fastrtps_cpp","rt/ap/v1/status","type",0);b.commit(true);}
 tfg_xrce_trace::writer(5,"01010101010101010101010101010101","020202020202020202020202020202020202020202020202","rmw_fastrtps_cpp","rt/ap/v3/status","type",0);a.commit(true);
}''')
    subprocess.run([compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pthread','-I',str(ROOT/'tools/rover_xrce_trace'),str(source),'-o',str(binary)],check=True,capture_output=True)
    import os
    env=dict(os.environ);env.pop('TFG_XRCE_TRACE',None)
    assert subprocess.run([str(binary)],capture_output=True,env=env,check=True).stderr==b''
    env['TFG_XRCE_TRACE']='1'
    result=subprocess.run([str(binary)],capture_output=True,env=env,check=True)
    report=analyze(result.stderr.decode().splitlines())
    assert report['trace_valid'],report
    assert {r['client_key'] for r in report['correlations']}=={1,2}
    env['TFG_TEST_CAP']='1'
    capped=subprocess.run([str(binary)],capture_output=True,env=env,check=True).stderr.decode().splitlines()
    assert len(capped)==512 and json.loads(capped[-1].split('TFG_XRCE_TRACE ',1)[1])['event']=='trace_limit'
    assert not analyze(capped)['trace_valid']
    env.pop('TFG_TEST_CAP');env['TFG_TEST_WRITE_ERROR']='1'
    failed=subprocess.run([str(binary)],capture_output=True,env=env,check=True)
    assert failed.stderr==b'' and not analyze([])['trace_valid']
    env.pop('TFG_TEST_WRITE_ERROR');env['TFG_TEST_PIPE']='1'
    assert subprocess.run([str(binary)],capture_output=True,env=env,check=True).returncode==0


def test_missing_sequence_not_accepted_as_complete_prefix():
    records=[row('dds_writer'),row('xrce_result')]
    records[0]['sequence']=1
    records[1]['sequence']=3
    assert not run(records)['trace_valid']


def test_client_generation_cannot_change_key_between_attempts():
    rows=[row('dds_writer'),row('xrce_result'),
          row('dds_writer',2,key=123,guid='03'*16,gid='04'*24),row('xrce_result',2,key=123)]
    assert not run(rows)['trace_valid']


def test_same_key_new_client_generation_allowed_with_new_native_identity():
    rows=[row('dds_writer'),row('xrce_result'),
          row('dds_writer',2,instance=2,guid='03'*16,gid='04'*24),row('xrce_result',2,instance=2)]
    assert run(rows)['trace_valid']
