"""Existing real capture plus labelled synthetic transport metadata; no runtime."""
import copy
import json
from pathlib import Path
import pytest
from tools import rover_passive_validation as v
from tools.rover_xrce_trace import socket_inventory as s
from tests.test_rover_identity_trial_analysis import TRIAL,closure
from tests.test_rover_socket_inventory import tree,process,put,udp,HEADER,FixtureClock


def real_report(log=None):
    return v.analyze_reader(TRIAL/'reader/journal.jsonl',TRIAL/'reader/journal.jsonl.receipt.json',
        TRIAL/'container-capture/trace.log',TRIAL/'container-capture/monitor.json',closure_evidence=closure(),launch_log=log)


def test_original_rpc_records_have_distinct_roles_and_no_client_attribution():
    r=real_report();native=r['parameters']['native_exchange']
    assert native['state']=='NATIVE_REPLIER_AND_EXCHANGE_CONTEXT_OBSERVED'
    assert native['request_metadata']['request_writer_guid']!=native['server_reply_writer_guid']
    assert native['reply_metadata']['request_writer_guid']==native['server_reply_writer_guid']
    assert not native['parameter_value_attributed'] and r['parameters']['state']=='UNKNOWN'


def test_original_resolved_odometry_default_needs_no_new_session():
    r=real_report(TRIAL/'launch.log');link=r['odometry_model']
    assert link['state']=='ODOMETRY_BRIDGE_TO_INSTANTIATED_MODEL_ROUTE_OBSERVED'
    assert link['model_entity']==67 and link['route']=='/model/rover1/odometry'
    assert link['route_setting']=='OMITTED_DEFAULT_RESOLVED_IN_ORIGINAL_LOG'
    assert link['pose_frame']=='odom' and link['twist_frame']=='base_link'
    assert not link['dynamic_twist_convention_validated'] and not link['movement_authorized']


@pytest.mark.parametrize('change',['actor','duplicate','entity','frame'])
def test_model_route_cannot_be_reconstructed_by_name_or_order(change):
    r=real_report();rows=v.read_journal(TRIAL/'reader/journal.jsonl',TRIAL/'reader/journal.jsonl.receipt.json')['records']
    p=json.loads((TRIAL/'container-capture/monitor.json').read_bytes())['model_source'];log=(TRIAL/'launch.log').read_text()
    if change=='actor':p['ppid']=999999
    elif change=='duplicate':log+='\n'+next(l for l in log.splitlines() if 'publishing odometry on' in l and 'rover1' in l)
    elif change=='entity':r['model_entities']['entities'][1]['model_entity']=9999
    else:
        for row in rows:
            if row.get('kind')=='sample' and row.get('topic')=='/rover1/odometry':row['child_frame_id']='unknown'
    assert v.correlate_odometry_model(r,rows,p,log)['state']=='UNKNOWN'


def rpc_fixture():
    # SYNTHETIC future native client SampleInfo contract, not available in history.
    from tests.test_rover_passive_validation import events
    e=events();ctx={**e[0],'domain':0};request_id=dict(writer_guid='01'*16,sequence_high=0,sequence_low=8)
    written=dict(writer_guid='03'*16,sequence_high=0,sequence_low=99)
    c=e[0];c.update(reader_guid='02'*16,writer_guid='03'*16)
    for row in e[2:]:row.update(rpc_contract='FASTDDS_RPC_IDENTITIES_V2',request_identity=request_id,
        related_identity=request_id,written_identity=written,replier_reader_guid='02'*16,replier_writer_guid='03'*16)
    e[-1]['related_identity']=written  # post-write output is not the pre-write request identity
    request=dict(client_instance=7,session_id='fixture',client_process={'pid':88,'start_ticks':99,'boot_id':'boot'},request_identity=request_id,sent_steady_ns=100)
    reply=dict(client_instance=7,session_id='fixture',client_process=request['client_process'],metadata_source='FASTDDS_SAMPLE_INFO',related_identity=request_id,sample_identity=written,received_steady_ns=200)
    return tuple(copy.deepcopy(x) for x in (request,reply,e,ctx))


@pytest.mark.parametrize('bad',[None,'other_request','sequence','stale','client','missing','generation','uncommitted'])
def test_exact_rpc_sample_identities_not_different_writer_roles(bad):
    q,a,e,w=copy.deepcopy(rpc_fixture())
    if bad=='other_request':a['related_identity']['writer_guid']='04'*16
    elif bad=='sequence':a['related_identity']['sequence_low']=9
    elif bad=='stale':a['received_steady_ns']=90
    elif bad=='client':a['client_instance']=8
    elif bad=='missing':a.pop('sample_identity')
    elif bad=='generation':e[-1]['attempt']=999
    elif bad=='uncommitted':e[1]['committed']=False
    result=v.correlate_rpc_v2(q,a,e,w)
    assert (result['state']=='PER_RESPONSE_METADATA_TO_XRCE_OBSERVED')==(bad is None)
    assert not result['movement_authorized']


def fdm_fixture(tree):
    root,c=tree;process(root,400,40,'ruby');c.update(model_process={'pid':400,'start_ticks':40,'boot_id':'boot'},model_executable='/usr/bin/ruby')
    model=dict(pid=400,start_ticks=40,boot_id='boot',verified_overlay_library=True)
    send=dict(schema='tfg.model-source/1',event='fdm_send',lifecycle_id='trial',pid=400,process_start_ticks='40',boot_id='boot',
        steady_ns=155000000000000,sequence=4,model_entity=67,
        destination_address='127.0.0.1',destination_port=35242,bytes_sent=300,bytes_expected=300,
        socket_observation={'address':'127.0.0.1','port':9022,'fd':35,'inode':100})
    row=s.collect(c,reader=s.Reader(root,clock=FixtureClock()));owner=row['owners_after'][0]['process']
    return row,send,model,owner


@pytest.mark.parametrize('case',[None,'remote','connected_other','shared','changed','legacy_eof','other_session','no_send','no_clock','future_send','missing_model','missing_owner','missing_reference'])
def test_fdm_receiver_is_separate_from_xrce_and_requires_complete_current_ownership(tree,case):
    row,send,model,owner=fdm_fixture(tree)
    if case=='remote':send['destination_address']='10.0.0.8'
    elif case=='connected_other':
        # Recollect a kernel row whose connected peer filters another sender.
        root,c=tree;put(root,'self/net/udp',HEADER+udp().replace('00000000:0000','0100007F:23FF')+udp(43,'00000000',2019));row=s.collect(c,reader=s.Reader(root,clock=FixtureClock()))
    elif case=='shared':
        root,c=tree;process(root,500,50,'foreign');(root/'500/fd/9').symlink_to('socket:[42]');row=s.collect(c,reader=s.Reader(root,clock=FixtureClock()))
    elif case=='changed':owner=copy.deepcopy(owner);owner['start_ticks']+=1
    elif case=='legacy_eof':row['table_scope_before'].pop('read_completion')
    elif case=='other_session':send['lifecycle_id']='other'
    elif case=='no_send':send['bytes_sent']=-1
    elif case=='no_clock':send.pop('steady_ns')
    elif case=='future_send':send['steady_ns']=10**20
    elif case=='missing_model':row['context_declared_by_protected_monitor'].pop('model_process')
    elif case=='missing_owner':
        root,c=tree;(root/'200/fd/7').unlink();row=s.collect(c,reader=s.Reader(root,clock=FixtureClock()))
    elif case=='missing_reference':row['table_before_reads']=[999999]
    r=s.match_fdm_receiver(row,send,model,'trial',expected_sitl=owner)
    assert (r['state']=='FDM_DESTINATION_TO_VISIBLE_SITL_SOCKET_OBSERVED')==(case is None)
    assert not r['payload_received'] and not r['effective_sysid_verified'] and not r['movement_authorized']


def test_fdm_analysis_uses_same_journal_row_as_status_peer_not_a_name(tree,tmp_path):
    from tools.rover_xrce_trace.budget import encode_row
    from tests.test_rover_socket_inventory import writer
    row,send,model,owner=fdm_fixture(tree);data=encode_row(s.pack_inventory(row));path=tmp_path/'sockets.jsonl';path.write_bytes(data)
    summary={'snapshots':1,'journal_bytes_written':len(data)}
    result=s.analyze_series(path,summary,writer(),'trial',fdm_sends=[send],model=model)
    assert result['fdm_rows'][0]['sends'][0]['state']=='FDM_DESTINATION_TO_VISIBLE_SITL_SOCKET_OBSERVED'
    assert not result['covers_entire_monitor_interval'] and not result['movement_authorized']
    # Synthetic disappearance during a later read preserves the local window
    # but prevents claiming the entire series is usable.
    broken=copy.deepcopy(row);broken.update(snapshot_state='INCOMPLETE',associations=[],reasons=['PROC_ENTRY_DISAPPEARED'])
    data+=encode_row(s.pack_inventory(broken));path.write_bytes(data)
    result=s.analyze_series(path,{'snapshots':2,'journal_bytes_written':len(data)},writer(),'trial',fdm_sends=[send],model=model)
    assert result['series_state']=='UNCERTAIN_OR_INCOMPLETE'
    assert result['fdm_rows'][1]['sends'][0]['state']=='UNKNOWN'
    assert len(result['usable_windows'])==1


def test_real_journal_does_not_gain_fdm_owners_retroactively():
    r=v.analyze_reader(TRIAL/'reader/journal.jsonl',TRIAL/'reader/journal.jsonl.receipt.json',
        TRIAL/'container-capture/trace.log',TRIAL/'container-capture/monitor.json',closure_evidence=closure(),
        launch_log=TRIAL/'launch.log',sockets=TRIAL/'container-capture/sockets.jsonl')
    assert r['odometry_model']['model_entity']==67
    assert len(r['socket_series']['fdm_rows'])==27
    assert all(send['state']=='UNKNOWN' for row in r['socket_series']['fdm_rows'] for send in row['sends'])


def test_real_peer_conversion_is_derived_and_has_no_retained_kernel_match():
    from tools.rover_xrce_trace.analyze import analyze,UDP_PORT_SOURCE_SHA256
    writer=next(w for w in analyze((TRIAL/'container-capture/trace.log').read_text().splitlines())['correlations'] if w['topic']=='rt/ap/v3/status')
    before=copy.deepcopy(writer)
    row=s.unpack_inventory(json.loads((TRIAL/'container-capture/sockets.jsonl').read_text().splitlines()[0]))
    result=s.match_peer(row,writer,'e837942d-61b0-428e-8505-ef6ddca38037')
    evidence=result['peer_interpretation']
    assert evidence['raw_recorded']['port']==65185
    assert evidence['normalized_derived']['port']==41470
    assert bytes.fromhex('a1fe')==(65185).to_bytes(2,'little')
    assert evidence['native_elf_byte_order']=='little' and evidence['transport_source_sha256']==UDP_PORT_SOURCE_SHA256
    assert not evidence['normalized_endpoint_is_direct_observation'] and not evidence['full_tables_eof']
    assert evidence['kernel_table_matches']==[] and result['link_state']=='NOT_OBSERVED_NOT_ABSENCE_PROOF'
    assert writer==before  # never substitute the normalized value into raw history


def test_visible_prefix_match_without_eof_does_not_prove_unique_owner(tree):
    from tests.test_rover_socket_inventory import writer
    row=s.collect(tree[1],reader=s.Reader(tree[0],clock=FixtureClock()))
    row['table_scope_before'].pop('read_completion');row['table_scope_after'].pop('read_completion')
    result=s.match_peer(row,writer(),'trial')
    assert result['peer_interpretation']['kernel_table_matches']
    assert result['link_state']=='TABLE_COMPLETENESS_NOT_ESTABLISHED'
    assert not result['source_association_verified']


def test_both_xrce_and_fdm_targets_survive_fragmented_table_to_eof(tree,tmp_path,monkeypatch):
    from tests.test_rover_socket_inventory import writer
    from tests.test_rover_proc_read_completion import split_table_reads
    from tools.rover_xrce_trace.budget import encode_row
    _,send,model,owner=fdm_fixture(tree);root,context=tree
    send['destination_port']=60575
    context['peers'].append({'family':'IPv4','address':'127.0.0.1','port':60575})
    prefix=HEADER+udp();put(root,'self/net/udp',prefix+udp(77,port=60575))
    (root/'200/fd/9').symlink_to('socket:[77]');split_table_reads(monkeypatch,root,len(prefix.encode()))
    row=s.collect(context,reader=s.Reader(root,clock=FixtureClock()))
    raw=encode_row(s.pack_inventory(row));path=tmp_path/'sockets.jsonl';path.write_bytes(raw)
    result=s.analyze_series(path,{'snapshots':1,'journal_bytes_written':len(raw)},writer(),'trial',fdm_sends=[send],model=model)
    assert result['rows'][0]['link_state']=='EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE'
    assert result['fdm_rows'][0]['sends'][0]['state']=='FDM_DESTINATION_TO_VISIBLE_SITL_SOCKET_OBSERVED'
    assert result['rows'][0]['candidates'][0]['inode']=='42' and result['fdm_rows'][0]['sends'][0]['inode']=='77'
    assert row['size_diagnostics']['search_counts']['read_calls']>len(row['reads'])
    assert not result['source_association_verified']


def test_rpc_pair_is_explicit_and_cannot_mix_old_native_with_new_wrapper():
    from tools.rover_xrce_trace import selection
    value=json.loads(Path('tools/rover_xrce_trace/diagnostic-agent.rpc.json').read_bytes())
    assert selection.check_manifest(value)==value
    value['library_sha256']=selection.IDENTITY_ARTIFACTS[1]
    with pytest.raises(ValueError,match='incompatible'):selection.check_manifest(value)


def test_native_rpc_metadata_retains_pre_write_copy_without_running_dds(tmp_path,monkeypatch):
    import subprocess
    source=tmp_path/'metadata.cpp';binary=tmp_path/'metadata'
    source.write_text(r'''#include "identity_trace.hpp"
struct G{struct{unsigned char value[12]{};}guidPrefix;struct{unsigned char value[4]{};}entityId;};
struct S{int high=0;unsigned low=1;};
struct I{G g;S s;const G& writer_guid()const{return g;}const S& sequence_number()const{return s;}};
int main(){I related;related.g.guidPrefix.value[0]=1;const auto before=related;
related.g.guidPrefix.value[0]=3;I written=related;
tfg_identity_trace::Context c{1,2,3,129,5,"replier"};
tfg_identity_trace::bindings()[nullptr]={c,"rq","rr","reader","writer"};
tfg_identity_trace::rpc_metadata(nullptr,before,related,written,"rpc_reply",true);}
''')
    include=Path(__file__).resolve().parents[1]/'tools/rover_xrce_trace'
    subprocess.run(['g++','-std=c++17','-pthread','-I',str(include),str(source),'-o',str(binary)],capture_output=True,check=True)
    import os
    env={**os.environ,'TFG_XRCE_TRACE':'1'}
    out=subprocess.run([str(binary)],env=env,capture_output=True,check=True).stderr.decode()
    event=json.loads(out.split('TFG_IDENTITY_TRACE ',1)[1])
    assert event['request_identity']['writer_guid'].startswith('01')
    assert event['related_identity']['writer_guid'].startswith('03')
    assert event['written_identity']['writer_guid'].startswith('03')
