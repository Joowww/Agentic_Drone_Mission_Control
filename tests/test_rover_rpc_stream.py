"""Synthetic public native-client wire contract; never a received real RPC."""
import copy
import hashlib
import json
import pytest
from tools import rover_passive_validation as validation
from tests.test_rover_pending_links import rpc_fixture
from tests.test_rover_xrce_trace import row
from tests.test_rover_observation_stream import header,sample,envelope,SESSION,IDENTITY


@pytest.mark.parametrize('bad',[None,'other_request','sequence','old','client','incomplete','monitor','lost_wait','mixed_session'])
def test_native_rpc_wire_is_consumed_and_bad_associations_fail_closed(tmp_path,bad):
    request,reply,events,ctx=rpc_fixture()
    for e in events:e['boot_id']=IDENTITY['boot_id']
    for v in (request,reply):v.update(client_process=IDENTITY,session_id=SESSION)
    request['accepted']=True
    reply['values']={'MAV_SYSID':3,'DDS_USE_NS':1}  # explicitly synthetic typed response
    if bad=='other_request':reply['related_identity']['writer_guid']='7'*32
    elif bad=='sequence':reply['related_identity']['sequence_low']+=1
    elif bad=='old':reply['received_steady_ns']=99
    elif bad=='client':reply['client_instance']+=1
    elif bad=='incomplete':reply.pop('sample_identity')
    status=sample('/ap/v3/status',2,1,100.01)
    native=[row('dds_writer'),row('xrce_result')]
    for v in native:
        v.update({k:ctx[k] for k in ('pid','process_start_ticks','client_instance','client_key','session_id')})
        v.update(boot_id=IDENTITY['boot_id'],rmw_gid=status['sample']['message_publisher_gid'])
    records=[header(),status,{**envelope('rpc_request',3),**request},{**envelope('rpc_reply',4),**reply},
             envelope('footer',5,reader_closed=True,counts={'/ap/v3/status':1,'/rover1/odometry':0})]
    for v in records:v['receipt_steady_ns']=100_000_000_000
    if bad=='mixed_session':records[3]['session_id']='other'
    wire=b''.join((json.dumps(v)+'\n').encode() for v in records)
    journal=tmp_path/'journal';journal.write_bytes(wire)
    receipt=tmp_path/'receipt';receipt.write_text(json.dumps(dict(status='RECEIVER_CLOSED',session_id=SESSION,receiver_process=IDENTITY,
        return_code=None if bad=='lost_wait' else 0,footer_sha256=hashlib.sha256(wire.splitlines(keepends=True)[-1]).hexdigest())))
    trace=tmp_path/'trace';trace.write_text(''.join('TFG_XRCE_TRACE '+json.dumps(v)+'\n' for v in native)+''.join('TFG_IDENTITY_TRACE '+json.dumps(v)+'\n' for v in events))
    monitor=tmp_path/'monitor';monitor.write_text(json.dumps(dict(lifecycle_id=SESSION,monitor={'boot_id':IDENTITY['boot_id']},agent={'pid':ctx['pid'],'start_ticks':int(ctx['process_start_ticks']),'boot_id':IDENTITY['boot_id']},started_monotonic=0,
        finished_monotonic=200,phase='CLOSED',errors=[],core_capture_complete=bad!='monitor',capture_complete=False,socket_capture_complete=False)))
    result=validation.analyze_transport_stream(journal,receipt,trace,monitor)
    assert (result['parameters_link']['state']=='PER_RESPONSE_METADATA_TO_XRCE_OBSERVED')==(bad is None),result
    assert not result['movement_authorized'] and result['state']=='BLOCKED'
    if bad is None:assert result['parameters_received']==reply.get('values')
