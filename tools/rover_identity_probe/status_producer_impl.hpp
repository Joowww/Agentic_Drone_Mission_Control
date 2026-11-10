#pragma once
#include "status_diagnostic.hpp"
#include "timing_fields.hpp"
// Included only by the isolated SITL source copy. Never drives the gates.
namespace tfg_status {
class ProducerImplementation {
  struct State {
    unsigned long long check=0,last_check=0,evaluation=0,heartbeat=0;
    unsigned delay=0,clock_rows=0;bool stamp_expected=false;
    long long last_loop=0,read_begin=0,read_end=0;
    unsigned long long last_ap_ms=0;
  };
  static State& state(){static State s;return s;}
  static Diagnostic& diagnostic(){return Diagnostic::instance("ap");}
public:
  static bool timing_active() noexcept {try{auto&d=diagnostic();d.poll_markers();return d.requested();}catch(...){return false;}}
  static void json_timing(tfg_timing::Window&w) noexcept {try{
    if(w.due())diagnostic().emit("json_timing",tfg_timing::fields(w));
  }catch(...) {}}
  static long long now() noexcept {try{return diagnostic().requested()?steady_ns():0;}catch(...){return 0;}}
  static void loop_enter() noexcept {try{
    auto& d=diagnostic();d.poll_markers();auto& s=state();auto now=steady_ns();
    if(d.requested()&&now-s.last_loop>=2000000000LL) {
      s.last_loop=now;d.emit("status_update_enter",
        "\"previous_ap_ms\":"+std::to_string(s.last_ap_ms)+
        ",\"previous_read_begin_ns\":"+std::to_string(s.read_begin)+
        ",\"previous_read_end_ns\":"+std::to_string(s.read_end));
    }
  }catch(...) {}}
  static void clock(unsigned long long ap,long long before,long long after) noexcept {try{
    auto& d=diagnostic();auto& s=state();
    s.last_ap_ms=ap;s.read_begin=before;s.read_end=after;
    // First three exact reads plus the preceding read in each loop heartbeat.
    // Do not spend two periodic records on the same progress observation.
    if(d.requested()&&s.clock_rows<3) {
      ++s.clock_rows;d.emit("status_ap_clock","\"ap_ms\":"+std::to_string(ap)+
        ",\"read_begin_ns\":"+std::to_string(before)+",\"read_end_ns\":"+std::to_string(after));
    }
  }catch(...) {}}
  static void check(unsigned long long now,unsigned long long previous,unsigned delay) noexcept {
    auto& s=state();s.check=now;s.last_check=previous;s.delay=delay;
  }
  static void evaluate(unsigned long long now,unsigned long long previous,bool changed,bool connected,long long before,long long after) noexcept {try{
    auto& s=state();auto& d=diagnostic();s.stamp_expected=false;
    if(!d.requested())return;
    ++s.evaluation;
    const bool due=changed||now-previous>static_cast<unsigned long long>(s.delay)*5;
    s.stamp_expected=due;
    if(d.matched()&&!changed&&due&&connected)++s.heartbeat;
    d.emit("status_evaluation","\"evaluation\":"+std::to_string(s.evaluation)+
      ",\"ap_ms\":"+std::to_string(now)+",\"check_ap_ms\":"+std::to_string(s.check)+
      ",\"last_check_ap_ms\":"+std::to_string(s.last_check)+",\"last_publish_ap_ms\":"+std::to_string(previous)+
      ",\"delay_ms\":"+std::to_string(s.delay)+",\"changed\":"+(changed?"true":"false")+
      ",\"connected\":"+(connected?"true":"false")+",\"gate\":"+(due?"true":"false")+
      ",\"after_match\":"+(d.matched()?"true":"false")+",\"heartbeat_opportunities\":"+std::to_string(s.heartbeat)+
      ",\"read_begin_ns\":"+std::to_string(before)+",\"read_end_ns\":"+std::to_string(after));
  }catch(...) {}}
  static void stamp(const char* source,long long sec,unsigned nano) noexcept {try{
    auto& s=state();if(!s.stamp_expected)return;s.stamp_expected=false;
    diagnostic().emit("status_stamp","\"evaluation\":"+std::to_string(s.evaluation)+
      ",\"source\":\""+source+"\",\"sec\":"+std::to_string(sec)+",\"nanosec\":"+std::to_string(nano));
  }catch(...) {}}
  static void stream_enter(unsigned writer) noexcept {try{
    if(diagnostic().requested())diagnostic().emit("status_stream_enter", "\"evaluation\":"+
      std::to_string(state().evaluation)+",\"writer_id\":"+std::to_string(writer));
  }catch(...) {}}
  static void stream_return(unsigned request_id) noexcept {try{
    if(diagnostic().requested())diagnostic().emit("status_stream_return", "\"evaluation\":"+
      std::to_string(state().evaluation)+",\"request_id\":"+std::to_string(request_id));
  }catch(...) {}}
  static void serialized(bool success) noexcept {try{
    if(diagnostic().requested())diagnostic().emit("status_serialized", "\"evaluation\":"+
      std::to_string(state().evaluation)+",\"success\":"+(success?"true":"false"));
  }catch(...) {}}
};
}
