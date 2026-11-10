"""Copy and patch pinned local sources into a NEW directory. Never patches in place."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import difflib

NATIVE = {
    'include/uxr/agent/message/InputMessage.hpp': '160adf40b4a054142829e3ad35596b3410348b68b5adc64d4e5a6520a1a95ffe',
    'src/cpp/processor/Processor.cpp': '22cd40746b55a00c1d25473f73c48e55ff6358688c84b792dbe5ec19b652f6d9',
    'include/uxr/agent/transport/endpoint/IPv4EndPoint.hpp': '8ac88670b9e7d2a03f8492da6a726c0685d914726e740f1921d64cf1fb5d57c2',
    'include/uxr/agent/client/ProxyClient.hpp': 'e6aadf4a082514ba111802c2c9ba1491fc364c5d723eb94df0c80b0ad210fd9b',
    'CMakeLists.txt': 'c3378bbc6a65bc6170564565b4fa3248f32a779683aca691528985b62fe01a0d',
    'src/cpp/client/ProxyClient.cpp': 'b4cdcc4ff92f263a399bc93ffe9f7b2df8301a81cc43ef5a97624545c19b904c',
    'src/cpp/middleware/fastdds/FastDDSMiddleware.cpp': '213a0760077df770f565d26fc3975298adafcea8fb8a9bc409321a2b1d6a178f',
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Source contract differs: unique patch anchor required')
    return text.replace(old, new, 1)


def prepare(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('New disjoint destination required')
    for name, expected in NATIVE.items():
        if not (source/name).is_file() or hashlib.sha256((source/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned source hash differs: ' + name)
    header = source/'include/uxr/agent/client/ProxyClient.hpp'
    # Check before copying, so a changed header never silently receives the patch.
    header_text = header.read_text()
    if header_text.count('    const dds::xrce::CLIENT_Representation representation_;') != 1:
        raise ValueError('ProxyClient member contract differs')
    shutil.copytree(source, destination)
    changes=[]
    def save(name, text):
        original=(source/name).read_text()
        (destination/name).write_text(text)
        changes.extend(difflib.unified_diff(original.splitlines(True),text.splitlines(True),'a/'+name,'b/'+name,n=0))
    name='include/uxr/agent/client/ProxyClient.hpp'
    text=replace_once(header_text,'    const dds::xrce::CLIENT_Representation representation_;',
        '    unsigned long long tfg_client_instance_;\n    const dds::xrce::CLIENT_Representation representation_;')
    text=replace_once(text, '    Session& session();',
        '    unsigned long long tfg_client_instance() const noexcept { return tfg_client_instance_; }\n\n    Session& session();')
    save(name,text)
    name='src/cpp/client/ProxyClient.cpp';text=(source/name).read_text()
    text='#include <uxr/agent/diagnostic/trace.hpp>\n'+text
    text=replace_once(text,': representation_(representation)',': tfg_client_instance_(tfg_xrce_trace::next_id())\n    , representation_(representation)')
    begin=text.index('bool ProxyClient::create_datawriter(');end=text.index('bool ProxyClient::create_datareader(',begin)
    body=text[begin:end]
    body=replace_once(body,'    bool rv = false;', '''    tfg_xrce_trace::Scope trace_scope(tfg_client_instance_,
        conversion::clientkey_to_raw(representation_.client_key()),
        static_cast<unsigned>(representation_.session_id()), conversion::objectid_to_raw(object_id));
    bool rv = false;''')
    body=replace_once(body,'    return rv;','    trace_scope.commit(rv);\n    return rv;')
    text=text[:begin]+body+text[end:];save(name,text)
    name='src/cpp/middleware/fastdds/FastDDSMiddleware.cpp';text=(source/name).read_text()
    text='#include <uxr/agent/diagnostic/trace.hpp>\n#include <rmw_fastrtps_shared_cpp/create_rmw_gid.hpp>\n'+text
    needle='callback_factory_.execute_callbacks(Middleware::Kind::FASTDDS,\n'
    # Limit changes to by_ref/by_xml/by_bin writer creation, never delete/readers.
    begin=text.index('bool FastDDSMiddleware::create_datawriter_by_ref(')
    end=text.index('bool FastDDSMiddleware::create_datareader_by_ref(',begin)
    body=text[begin:end]
    if body.count(needle)!=3: raise ValueError('Expected three writer creation variants')
    diagnostic='''if (tfg_xrce_trace::enabled()) {
                    try {
                        const auto* native = emplace_res.first->second->ptr();
                        const auto gid = rmw_fastrtps_shared_cpp::create_rmw_gid("rmw_fastrtps_cpp", native->guid());
                        const auto& guid = native->guid();
                        std::string native_hex = tfg_xrce_trace::hex(guid.guidPrefix.value, 12) +
                            tfg_xrce_trace::hex(guid.entityId.value, 4);
                        tfg_xrce_trace::writer(datawriter_id, native_hex,
                            tfg_xrce_trace::hex(gid.data, sizeof(gid.data)), gid.implementation_identifier,
                            native->get_topic()->get_name(), native->get_topic()->get_type_name(),
                            (**it_publisher->second->get_participant())->get_domain_id());
                    } catch (...) { tfg_xrce_trace::emit("\\"event\\":\\"trace_error\\",\\"incomplete\\":true"); }
                }
                '''
    body=body.replace(needle,diagnostic+needle);save(name,text[:begin]+body+text[end:])
    name='src/cpp/processor/Processor.cpp';text=(source/name).read_text()
    text='#include <uxr/agent/diagnostic/peer_endpoint.hpp>\n'+text
    # Attach provenance before unique_ptr ownership moves into the session queue.
    text=replace_once(text, '            session.push_input_message(std::move(input_packet.message), stream_id, sequence_nr);',
        '            if (tfg_xrce_trace::enabled()) {\n'
        '                input_packet.message->tfg_diagnostic_peer_ = tfg_xrce_trace::received_peer(\n'
        '                    client->tfg_client_instance(), conversion::clientkey_to_raw(client->get_client_key()),\n'
        '                    static_cast<unsigned>(client->get_session_id()), input_packet.source);\n'
        '            }\n'
        '            session.push_input_message(std::move(input_packet.message), stream_id, sequence_nr);')
    text=replace_once(text, '                process_input_message(*client, input_packet);', '''                tfg_xrce_trace::PeerScope tfg_peer_scope;
                if (tfg_xrce_trace::enabled()) {
                    tfg_peer_scope.bind(client->tfg_client_instance(),
                        conversion::clientkey_to_raw(client->get_client_key()), static_cast<unsigned>(client->get_session_id()),
                        tfg_xrce_trace::peer_from_message(input_packet.message->tfg_diagnostic_peer_,
                            client->tfg_client_instance(), conversion::clientkey_to_raw(client->get_client_key()),
                            static_cast<unsigned>(client->get_session_id())));
                }
                process_input_message(*client, input_packet);''')
    text=replace_once(text, '        process_input_message(client, fragment_packet);', '''        // Reassembly does not preserve the source of every fragment. Never
        // inherit the last fragment's peer as whole-message provenance.
        tfg_xrce_trace::PeerScope tfg_unknown_fragment;
        if (tfg_xrce_trace::enabled()) {
            tfg_unknown_fragment.bind(client.tfg_client_instance(),
                conversion::clientkey_to_raw(client.get_client_key()), static_cast<unsigned>(client.get_session_id()), {});
        }
        process_input_message(client, fragment_packet);''')
    save(name,text)

    name='include/uxr/agent/message/InputMessage.hpp'
    text='#include <uxr/agent/diagnostic/trace.hpp>\n'+(source/name).read_text()
    text=replace_once(text, 'public:\n    InputMessage(',
        'public:\n    tfg_xrce_trace::MessagePeer tfg_diagnostic_peer_;\n\n    InputMessage(')
    save(name,text)

    extra='''
# TFG opt-in diagnostic dependency. No callbacks removed, no payload tracing.
find_package(rmw_fastrtps_shared_cpp REQUIRED)
target_include_directories(microxrcedds_agent PRIVATE ${rmw_fastrtps_shared_cpp_INCLUDE_DIRS})
target_link_libraries(microxrcedds_agent PRIVATE ${rmw_fastrtps_shared_cpp_LIBRARIES})
'''
    save('CMakeLists.txt',(source/'CMakeLists.txt').read_text()+extra)
    target=destination/'include/uxr/agent/diagnostic/trace.hpp';target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(Path(__file__).with_name('trace.hpp'),target)
    peer_target=target.with_name('peer_endpoint.hpp')
    shutil.copyfile(Path(__file__).with_name('peer_endpoint.hpp'),peer_target)
    (destination/'tfg-trace.patch').write_text(''.join(changes))
    metadata={'schema':'tfg.xrce-trace-build-input/1','native_sources':NATIVE,
              'source':str(source),'destination':str(destination),'trace_header_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'peer_header_sha256':hashlib.sha256(peer_target.read_bytes()).hexdigest(),
              'modified':{name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in [*NATIVE,'include/uxr/agent/client/ProxyClient.hpp','CMakeLists.txt']}}
    (destination/'tfg-trace-input.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    args=p.parse_args();print(json.dumps(prepare(args.source,args.destination),indent=2))
