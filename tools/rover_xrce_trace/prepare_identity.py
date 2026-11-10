"""Diagnostic source copies only. Never installs or runs an agent/bridge."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil

from .prepare import prepare,replace_once


def prepare_identity(native_source,bridge_source,destination):
    native_source,bridge_source,destination=map(lambda p:Path(p).resolve(),(native_source,bridge_source,destination))
    if destination.exists() or any(destination.is_relative_to(p) or p.is_relative_to(destination) for p in (native_source,bridge_source)):
        raise ValueError('New disjoint source destination required')
    destination.mkdir(mode=0o700)
    base=prepare(native_source,destination/'native')
    native=destination/'native';bridge=destination/'bridge'
    shutil.copytree(bridge_source,bridge)
    changes=[];inputs={}
    def save(root,name,old,new):
        inputs[str(root.relative_to(destination)/name)]=hashlib.sha256(old.encode()).hexdigest()
        (root/name).write_text(new)
        changes.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
            'a/'+str(root.relative_to(destination)/name),'b/'+str(root.relative_to(destination)/name)))
    name='src/cpp/client/ProxyClient.cpp';old=(native/name).read_text();text=old
    text='#include <uxr/agent/diagnostic/identity_trace.hpp>\n'+text
    for function,kind in [('create_replier','replier'),('create_datareader','datareader')]:
        begin=text.index('bool ProxyClient::'+function+'(');end=text.index('\n}\n',begin)+3
        body=text[begin:end]
        body=replace_once(body,'    bool rv = false;',f'''    tfg_identity_trace::Scope identity_scope(tfg_client_instance_,
        conversion::clientkey_to_raw(representation_.client_key()),
        static_cast<unsigned>(representation_.session_id()),conversion::objectid_to_raw(object_id),"{kind}");
    bool rv = false;''')
        body=replace_once(body,'    return rv;','    identity_scope.commit(rv);\n    return rv;')
        text=text[:begin]+body+text[end:]
    save(native,name,old,text)
    name='src/cpp/middleware/fastdds/FastDDSMiddleware.cpp';old=(native/name).read_text();text='#include <uxr/agent/diagnostic/identity_trace.hpp>\n'+old
    for start,end,statement in [
        ('create_replier_by_ref','delete_participant','tfg_identity_trace::bind(emplace_res.first->second.get());'),
        ('create_datareader_by_ref','create_requester','tfg_identity_trace::reader(emplace_res.first->second->ptr());')]:
        begin=text.index('bool FastDDSMiddleware::'+start+'(')
        finish=text.index(('bool FastDDSMiddleware::' if end=='delete_participant' else 'std::shared_ptr<FastDDSRequester> FastDDSMiddleware::')+end+'(',begin)
        body=text[begin:finish];needle='callback_factory_.execute_callbacks(Middleware::Kind::FASTDDS,'
        if body.count(needle)!=3:raise ValueError('Expected exact three diagnostic creation variants: '+start)
        body=body.replace(needle,statement+'\n                '+needle)
        text=text[:begin]+body+text[finish:]
    save(native,name,old,text)
    name='src/cpp/middleware/fastdds/FastDDSEntities.cpp';old=(native/name).read_text();text='#include <uxr/agent/diagnostic/identity_trace.hpp>\n'+old
    text=replace_once(text,'    return datawriter_ptr_->write(&const_cast<std::vector<uint8_t>&>(output_data), wparams);',
        '    const auto diagnostic_request_before_write = wparams.related_sample_identity();\n'
        '    const bool rv=datawriter_ptr_->write(&const_cast<std::vector<uint8_t>&>(output_data), wparams);\n'
        '    tfg_identity_trace::rpc_metadata(this,diagnostic_request_before_write,wparams.related_sample_identity(),wparams.sample_identity(),"rpc_reply",rv);\n    return rv;')
    begin=text.index('bool FastDDSReplier::read(');end=text.index('const fastdds::dds::DomainParticipant* FastDDSReplier::get_participant()',begin)
    body=replace_once(text[begin:end],'    return rv;',
        '    if(rv)tfg_identity_trace::rpc_metadata(this,info.sample_identity,info.related_sample_identity,info.sample_identity,"rpc_request",true);\n    return rv;')
    text=text[:begin]+body+text[end:];save(native,name,old,text)
    shutil.copyfile(Path(__file__).with_name('identity_trace.hpp'),native/'include/uxr/agent/diagnostic/identity_trace.hpp')
    name='src/bridge_handle_gz_to_ros.cpp';old=(bridge/name).read_text()
    text='#include "tfg_identity_trace.hpp"\n'+old
    for method,end_method,event in [('StartPublisher','HasSubscriber','bridge_publisher'),('StartSubscriber','StopSubscriber','bridge_subscription')]:
        begin=text.index('void BridgeHandleGzToRos::'+method+'(')
        finish=text.index(('bool' if end_method=='HasSubscriber' else 'void')+' BridgeHandleGzToRos::'+end_method+'(',begin)
        body=text[begin:finish];at=body.rfind('}')
        body=body[:at]+'''  if (tfg_xrce_trace::enabled()) {
    try { std::string config_path;this->RosNode()->get_parameter("config_file",config_path);
      tfg_identity_trace::bridge(*this->ros_publisher_,this->config_,config_path,"'''+event+'''");
    } catch (...) { tfg_identity_trace::emit("\\"event\\":\\"identity_error\\",\\"incomplete\\":true"); }
  }
'''+body[at:]
        text=text[:begin]+body+text[finish:]
    save(bridge,name,old,text)
    shutil.copyfile(Path(__file__).with_name('trace.hpp'),bridge/'src/trace.hpp')
    shutil.copyfile(Path(__file__).with_name('identity_trace.hpp'),bridge/'src/tfg_identity_trace.hpp')
    result={'schema':'tfg.identity-build-input/1','base':base,'extra_inputs':inputs,
            'identity_header_sha256':hashlib.sha256(Path(__file__).with_name('identity_trace.hpp').read_bytes()).hexdigest()}
    (destination/'identity.patch').write_text(''.join(changes))
    (destination/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('native');p.add_argument('bridge');p.add_argument('destination');a=p.parse_args()
    print(json.dumps(prepare_identity(a.native,a.bridge,a.destination),indent=2))
