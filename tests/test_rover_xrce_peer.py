"""Public endpoint + lexical context synthetic tests; no agent/ROS instantiation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os

import pytest

from tools.rover_xrce_trace.analyze import analyze
from tools.rover_xrce_trace.prepare import prepare

ROOT=Path(__file__).resolve().parents[1]


def peer(port=35242):
    return {'family':'IPv4','address':'127.0.0.1','port':port,
            'source':'Processor InputMessage metadata before session queue',
            'generation_binding':'SAME_PROXYCLIENT_REFERENCE'}


def record(event,attempt=1,instance=1,port=35242):
    return {'schema':'tfg.xrce-writer/1','event':event,'pid':10,'boot_id':'boot','process_start_ticks':'123',
            'sequence':attempt*2-1+(event=='xrce_result'),'wall_unix_ns':100,'steady_ns':100+(event=='xrce_result'),
            'client_instance':instance,'attempt':attempt,'client_key':3,'session_id':129,'writer_id':14,
            'native_guid':f'{attempt:032x}','rmw_gid':f'{attempt:048x}','rmw_identifier':'rmw_fastrtps_cpp',
            'topic':'rt/ap/v3/status','type':'ardupilot_msgs::msg::dds_::Status_','domain':0,'committed':True,
            'transport_peer':peer(port)}


def test_client_key_session_reused_generation_is_explicit():
    rows=[record('dds_writer'),record('xrce_result'),record('dds_writer',2,2,35243),record('xrce_result',2,2,35243)]
    report=analyze(['TFG_XRCE_TRACE '+json.dumps(r) for r in reversed(rows)])
    assert report['trace_valid'] and len(report['correlations'])==2
    assert {r['client_instance']:r['transport_peer']['port'] for r in report['correlations']}=={1:35242,2:35243}
    assert report['source_association_verified'] is False


@pytest.mark.parametrize('change',['peer','generation','address','source'])
def test_contradictory_or_incomplete_peer_rejected(change):
    rows=[record('dds_writer'),record('xrce_result')]
    if change=='peer':rows[1]['transport_peer']['port']=1234
    elif change=='generation':rows[1]['client_instance']=2
    elif change=='address':
        for r in rows:r['transport_peer']['address']='not-an-ip'
    else:
        for r in rows:r['transport_peer']['source']='guessed from ClientKey'
    assert not analyze(['TFG_XRCE_TRACE '+json.dumps(r) for r in rows])['trace_valid']


def test_legacy_trace_remains_valid_without_inventing_peer():
    rows=[record('dds_writer'),record('xrce_result')]
    for r in rows:r.pop('transport_peer')
    report=analyze(['TFG_XRCE_TRACE '+json.dumps(r) for r in rows])
    assert report['trace_valid'] and 'transport_peer' not in report['correlations'][0]


def test_peer_scope_public_endpoint_and_no_generation_guess(tmp_path):
    compiler=shutil.which('g++');assert compiler
    include=tmp_path/'include';target=include/'uxr/agent/transport/endpoint/IPv4EndPoint.hpp';target.parent.mkdir(parents=True)
    reference=ROOT/'tests/fixtures/rover_xrce/IPv4EndPoint.hpp'
    assert hashlib.sha256(reference.read_bytes()).hexdigest()=='8ac88670b9e7d2a03f8492da6a726c0685d914726e740f1921d64cf1fb5d57c2'
    shutil.copyfile(reference,target)
    diagnostic=include/'uxr/agent/diagnostic';diagnostic.mkdir(parents=True)
    for name in ('trace.hpp','peer_endpoint.hpp'):shutil.copyfile(ROOT/'tools/rover_xrce_trace'/name,diagnostic/name)
    source=tmp_path/'peer.cpp';binary=tmp_path/'peer'
    source.write_text('''#include <uxr/agent/diagnostic/peer_endpoint.hpp>
#include <memory>
#include <netinet/in.h>
int main() {
 using namespace tfg_xrce_trace;
 eprosima::uxr::IPv4EndPoint endpoint(0x0100007f,htons(35242));
 const auto actual=packet_peer(endpoint);
 if (actual.address!="127.0.0.1" || actual.port!=htons(35242) || !actual.available) return 7;
 struct Message { MessagePeer peer; };
 auto received=std::make_unique<Message>();
 received->peer=received_peer(1,3,129,endpoint);
 auto queued=std::move(received);
 if (received || !peer_from_message(queued->peer,1,3,129).available) return 9;
 if (peer_from_message(queued->peer,2,3,129).available) return 10;
 auto newer=std::make_unique<Message>();
 newer->peer=received_peer(1,3,129,eprosima::uxr::IPv4EndPoint(0x0100007f,35243));
 if (peer_from_message(newer->peer,1,3,129).port!=35243 ||
     peer_from_message(queued->peer,1,3,129).port!=htons(35242)) return 11;
 Message reassembled;
 if (peer_from_message(reassembled.peer,1,3,129).available) return 12;
 struct Unsupported {};
 if (packet_peer(Unsupported{}).available) return 8;
 PeerScope first;first.bind(1,3,129,actual);
 Context c{1,1,3,129,14};emit("\\\"event\\\":\\\"peer_test\\\","+fields(c));
 {PeerScope recreated;recreated.bind(2,3,129,PeerEndpoint{"127.0.0.1",35243,true});
  Context other{2,2,3,129,14};emit("\\\"event\\\":\\\"peer_test\\\","+fields(other));
  emit("\\\"event\\\":\\\"peer_test\\\","+fields(c));}
 emit("\\\"event\\\":\\\"peer_test\\\","+fields(c));
 {PeerScope unavailable;unavailable.bind(1,3,129,packet_peer(Unsupported{}));
  emit("\\\"event\\\":\\\"peer_test\\\","+fields(c));}
}''')
    subprocess.run([compiler,'-std=c++14','-Wall','-Wextra','-Werror','-pthread','-I',str(include),str(source),'-o',str(binary)],check=True,capture_output=True)
    env={**os.environ,'TFG_XRCE_TRACE':'1'}
    got=subprocess.run([str(binary)],capture_output=True,env=env,check=True)
    rows=[json.loads(r.split('TFG_XRCE_TRACE ',1)[1]) for r in got.stderr.decode().splitlines()]
    assert [r['transport_peer']['port'] if r['transport_peer'] else None for r in rows]==[__import__('socket').htons(35242),35243,None,__import__('socket').htons(35242),None]
    env['TFG_XRCE_TRACE']='0'
    assert subprocess.run([str(binary)],capture_output=True,env=env,check=True).stderr==b''


@pytest.mark.parametrize('order',['little','big'])
def test_port_normalization_uses_sin_port_contract_not_numeric_similarity(order):
    import socket
    from tools.rover_xrce_trace.analyze import normalized_udp_peer,UDP_PORT_SOURCE_SHA256
    port=47185
    raw=int.from_bytes(port.to_bytes(2,'big'),order)
    writer={'transport_peer':{'family':'IPv4','address':'127.0.0.1','port':raw,
        'source':'Processor InputMessage metadata before session queue','generation_binding':'SAME_PROXYCLIENT_REFERENCE'}}
    before=json.dumps(writer,sort_keys=True)
    assert normalized_udp_peer(writer,native_byte_order=order,transport_source_sha256=UDP_PORT_SOURCE_SHA256)['port']==port
    assert json.dumps(writer,sort_keys=True)==before
    with pytest.raises(ValueError):normalized_udp_peer(writer,native_byte_order=None,transport_source_sha256=UDP_PORT_SOURCE_SHA256)
    with pytest.raises(ValueError):normalized_udp_peer(writer,native_byte_order=order,transport_source_sha256='unknown')
