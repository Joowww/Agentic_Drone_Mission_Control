#pragma once
// Same plugin, private request marker and existing capped MODEL trace. No IO
// endpoint, clock substitution, component write or control command is added.
#include "model_trace.hpp"
#include "status_diagnostic.hpp"
#include "timing_fields.hpp"
#include <cstring>
#include <cmath>
#include <cstdio>
namespace tfg_model_timing {
struct Entry {const void* owner=nullptr;tfg_timing::Window window;bool lockstep=false,paused=false;char address[64]{};unsigned port=0;int fd=-1;};
inline std::mutex& mutex(){static std::mutex m;return m;}
inline std::atomic<unsigned>& losses(){static std::atomic<unsigned> v{0};return v;}
inline Entry* entry(const void*p) {
  static Entry entries[8];
  for(auto&e:entries)if(e.owner==p)return &e;
  for(auto&e:entries)if(!e.owner){e.owner=p;return &e;}
  ++losses();return nullptr;
}
inline bool selected() noexcept {return tfg_model_trace::enabled()&&std::getenv("TFG_STATUS_DIAGNOSTIC");}
inline bool active() noexcept {
  if(!selected())return false;
  const int saved=errno;bool result=false;
  try{auto&d=tfg_status::Diagnostic::instance("model");d.poll_markers();result=d.requested();}catch(...){++losses();}
  errno=saved;return result;
}
inline void endpoint(const void*p,int fd,const char*address,unsigned port) noexcept {
  if(!selected())return;
  std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);
  if(!lock){++losses();return;}if(auto*e=entry(p)){
    e->fd=fd;e->port=port;
    const int n=std::snprintf(e->address,sizeof(e->address),"%s",address?address:"");
    if(n<=0||n>=int(sizeof(e->address)))e->window.invalid=true;
  }
}
inline void state_stamp(const void*p,double time) noexcept {
  if(!selected())return;
  std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);
  if(!lock){++losses();return;}if(auto*e=entry(p)){
    if(!std::isfinite(time)||time<0||time>9e9)e->window.invalid=true;
    else e->window.source_stamp_ns=int64_t(time*1e9);
  }
}
inline void report(const void*p,uint64_t checkpoint) noexcept {
  if(!active())return;
  const int saved=errno;
  try{
    tfg_timing::Window snapshot;bool emit=false,lockstep=false,paused=false;char address[64]{};unsigned port=0;int fd=-1;
    {std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);if(!lock){++losses();return;}
     if(auto*e=entry(p)){
       // Emit also while PreUpdate is still waiting. last_mono remains the
       // original simTime read's bracket; checkpoint is a separate clock read.
       auto&w=e->window;
       emit=w.first_mono&&checkpoint>=w.first_mono&&checkpoint-w.first_mono>=1000000000ULL&&
         (!w.emitted||checkpoint-w.emitted>=10000000000ULL);
       if(emit)w.emitted=checkpoint;
       snapshot=w;lockstep=e->lockstep;paused=e->paused;port=e->port;fd=e->fd;std::memcpy(address,e->address,sizeof(address));
     }}
    if(emit){
      std::unique_lock<std::mutex>lock(tfg_model_trace::mutex(),std::try_to_lock);
      if(!lock){++losses();return;}
      auto it=tfg_model_trace::bindings().find(p);
      if(it==tfg_model_trace::bindings().end()){++losses();return;}
      tfg_model_trace::emit("\"event\":\"timing_window\","+tfg_model_trace::context(it->second)+","+
        tfg_timing::fields(snapshot)+",\"checkpoint_mono_ns\":"+std::to_string(checkpoint)+
        ",\"clock\":\"CLOCK_MONOTONIC\",\"time_namespace\":"+tfg_xrce_trace::quote(tfg_status::ns("time"))+
        ",\"context_sha256\":"+tfg_xrce_trace::quote(std::getenv("TFG_STATUS_DIAGNOSTIC_CONTEXT")?std::getenv("TFG_STATUS_DIAGNOSTIC_CONTEXT"):"")+
        ",\"lockstep\":"+(lockstep?"true":"false")+",\"paused\":"+(paused?"true":"false")+
        ",\"fdm_socket\":{"+tfg_model_trace::socket_fields(fd)+",\"destination_address\":"+tfg_xrce_trace::quote(address)+",\"destination_port\":"+std::to_string(port)+"}"+
        ",\"timing_lost\":"+std::to_string(losses().load()));
    }
  }catch(...){++losses();}errno=saved;
}
class SpanScope {
protected:
  const void* owner_;unsigned index_;uint64_t begin_=0;
public:
  int64_t result=INT64_MIN;
  SpanScope(const void*p,unsigned i):owner_(p),index_(i) {
    if(!selected())return;
    begin_=tfg_timing::now();std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);
    if(!lock){++losses();return;}if(auto*e=entry(p))e->window.active[i]=begin_;
  }
  void finish(int64_t value) noexcept {
    if(!begin_)return;
    result=value;
    {std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);
     if(!lock){++losses();return;}if(auto*e=entry(owner_)){
       if(result==INT64_MIN)e->window.invalid=true;
       e->window.spans[index_].add(begin_,tfg_timing::now(),result);e->window.active[index_]=0;
     }}
    begin_=0;
    report(owner_,tfg_timing::now());
  }
  ~SpanScope() noexcept {finish(result);}
};
class Scope {
  const void* owner_;unsigned index_;uint64_t begin_=0,sim_=0;bool lockstep_,paused_;
public:
  template<class Info>Scope(const void*p,unsigned i,const Info&info,bool lockstep):owner_(p),index_(i),lockstep_(lockstep),paused_(info.paused) {
    if(!selected())return;
    sim_=std::chrono::duration_cast<std::chrono::nanoseconds>(info.simTime).count();
    begin_=tfg_timing::now();std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);
    if(!lock){++losses();return;}if(auto*e=entry(p)){e->lockstep=lockstep_;e->paused=paused_;e->window.observe(sim_,begin_);e->window.active[i]=begin_;}
  }
  ~Scope() noexcept {
    if(!begin_)return;
    {std::unique_lock<std::mutex>lock(mutex(),std::try_to_lock);
     if(!lock){++losses();return;}if(auto*e=entry(owner_)){
       auto now=tfg_timing::now();e->window.spans[index_].add(begin_,now,1);e->window.active[index_]=0;
       e->window.observe(sim_,now);
     }}
    report(owner_,tfg_timing::now());
  }
};
}
