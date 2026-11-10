"""Pinned source instrumentation only. No simulator/SDK launch or deployment."""
import hashlib
from .prepare import replace_once

JSON_SHA256='9d61150869b2df651b96d7735523693bcaaefa3ef1496144bacd3b8b121118cc'
PLUGIN_PREPARED_SHA256='a8681fe9f5d216d12e78ae6182fe0d1804cf9f7b631355f0f2e32940ff98f49b'


def patch_json(text):
    if hashlib.sha256(text.encode()).hexdigest()!=JSON_SHA256:
        raise ValueError('Unreviewed SIM_JSON source')
    helper=r'''
#include "../AP_DDS/status_producer.hpp"
#include <stddef.h>
#include <sys/types.h>
namespace {
// One JSON backend per SITL process; a second instance is diagnostic failure.
tfg_timing::Window json_timing_window;
bool json_timing_on=false;const void* json_timing_owner=nullptr;const uint64_t* json_sim_us=nullptr;
void json_checkpoint() noexcept {
  if(!json_timing_on)return;
  const int saved=errno;
  json_timing_window.observe(*json_sim_us*1000,tfg_timing::now());
  tfg_status::Producer::json_timing(json_timing_window);errno=saved;
}
struct JsonSpan {
  unsigned index;uint64_t begin;
  explicit JsonSpan(unsigned i):index(i),begin(json_timing_on?tfg_timing::now():0){if(begin)json_timing_window.active[i]=begin;}
  ~JsonSpan(){if(begin){json_timing_window.spans[index].add(begin,tfg_timing::now(),1);json_timing_window.active[index]=0;json_checkpoint();}}
};
template<class Socket>ssize_t timed_json_recv(Socket&s,void*b,size_t n,int timeout){
  const auto begin=json_timing_on?tfg_timing::now():0;
  if(begin)json_timing_window.active[2]=begin;
  const auto result=s.recv(b,n,timeout);
  if(begin){json_timing_window.spans[2].add(begin,tfg_timing::now(),result);json_timing_window.active[2]=0;json_checkpoint();}
  return result;
}
}
'''
    # AP source stays -fno-exceptions; formatting/pipe IO is in the existing
    # exception-enabled Producer object. No result, gate or pacing change.
    text=helper+text
    text=replace_once(text,'void JSON::output_servos(const struct sitl_input &input)\n{',
        'void JSON::output_servos(const struct sitl_input &input)\n{\n    const auto diagnostic_send_begin=json_timing_on?tfg_timing::now():0;')
    text=replace_once(text,'    if ((size_t)send_ret != pkt_size) {',
        '    if(diagnostic_send_begin)json_timing_window.spans[1].add(diagnostic_send_begin,tfg_timing::now(),send_ret);\n    if ((size_t)send_ret != pkt_size) {')
    text=replace_once(text,'void JSON::recv_fdm(const struct sitl_input &input)\n{',
        'void JSON::recv_fdm(const struct sitl_input &input)\n{\n    JsonSpan diagnostic_receive(3);')
    needle='sock.recv(&sensor_buffer[sensor_buffer_len], sizeof(sensor_buffer)-sensor_buffer_len, UDP_TIMEOUT_MS)'
    if text.count(needle)!=2:raise ValueError('JSON receive call coverage changed')
    text=text.replace(needle,'timed_json_recv(sock, &sensor_buffer[sensor_buffer_len], sizeof(sensor_buffer)-sensor_buffer_len, UDP_TIMEOUT_MS)')
    text=replace_once(text,'    frame_counter++;',
        '    frame_counter++;\n    if(json_timing_on)json_timing_window.source_stamp_ns=int64_t(state.timestamp_s*1.0e9);')
    text=replace_once(text,'void JSON::update(const struct sitl_input &input)\n{',r'''void JSON::update(const struct sitl_input &input)
{
    json_timing_on=tfg_status::Producer::timing_active();
    if(json_timing_on){
        if(json_timing_owner&&json_timing_owner!=this)json_timing_window.invalid=true;
        json_timing_owner=this;json_sim_us=&time_now_us;json_checkpoint();
    }
    JsonSpan diagnostic_update(0);''')
    return text


def patch_plugin(text):
    # Input is the already reviewed model-source preparation, not a different
    # layout or a new plugin API. Existing identity hooks remain in place.
    if hashlib.sha256(text.encode()).hexdigest()!=PLUGIN_PREPARED_SHA256:
        raise ValueError('Explicit prepared model source required')
    text='#include "model_timing.hpp"\n'+text
    # Function entry spans include all early exits; original return values stay.
    import re
    for name,index in [('PreUpdate',0),('PostUpdate',3)]:
        pattern=r'(void gz::sim::systems::ArduPilotPlugin::'+name+r'\([\s\S]*?\n\{)'
        text,n=re.subn(pattern,lambda m:m[0]+f'\n    tfg_model_timing::Scope diagnostic_scope(this,{index},_info,this->dataPtr->isLockStep);',text,count=1)
        if n!=1:raise ValueError('Plugin scope anchor changed: '+name)
    text=replace_once(text,'bool gz::sim::systems::ArduPilotPlugin::ReceiveServoPacket()\n{',
        'bool gz::sim::systems::ArduPilotPlugin::ReceiveServoPacket()\n{\n    tfg_model_timing::SpanScope diagnostic_servo(this,1);')
    # Preserve every native return and associate the last syscall outcome.
    text=replace_once(text,"    // didn't receive a packet, increment timeout count if online, then return",
        "    diagnostic_servo.finish(recvSize);\n    // didn't receive a packet, increment timeout count if online, then return")
    text=replace_once(text,'void gz::sim::systems::ArduPilotPlugin::SendState() const\n{',
        'void gz::sim::systems::ArduPilotPlugin::SendState() const\n{\n    tfg_model_timing::endpoint(this,this->dataPtr->sock.diagnostic_fd(),this->dataPtr->fcu_address,this->dataPtr->fcu_port_out);\n    tfg_model_timing::SpanScope diagnostic_send(this,2);')
    text=replace_once(text,'    tfg_model_trace::state(this,_simTime,','    tfg_model_timing::state_stamp(this,_simTime);\n    tfg_model_trace::state(this,_simTime,')
    text=replace_once(text,'    tfg_model_trace::sent(this,', '    diagnostic_send.finish(bytes_sent);\n    tfg_model_trace::sent(this,')
    return text
