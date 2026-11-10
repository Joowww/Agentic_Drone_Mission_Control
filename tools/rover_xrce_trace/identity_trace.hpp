#pragma once
// Optional diagnostics in copied agent/bridge sources. No payloads or controls.
#include "trace.hpp"
#include <map>
namespace tfg_identity_trace {
using tfg_xrce_trace::quote;
using tfg_xrce_trace::hex;
inline void emit(const std::string& fields) noexcept {
    if (!tfg_xrce_trace::enabled()) return;
    try {
        static std::mutex mutex; static unsigned sequence=0; static bool failed=false;
        std::lock_guard<std::mutex> lock(mutex);
        if (failed || sequence>=128) return;
        ++sequence;
        auto wall=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        auto steady=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
        const auto selected=sequence==128?"\"event\":\"identity_limit\",\"incomplete\":true":fields;
        const auto line="TFG_IDENTITY_TRACE {\"schema\":\"tfg.identity-trace/1\","+
            tfg_xrce_trace::process_identity()+",\"sequence\":"+std::to_string(sequence)+
            ",\"wall_unix_ns\":"+std::to_string(wall)+",\"steady_ns\":"+std::to_string(steady)+","+selected+"}\n";
        if (line.size()>4096 || tfg_xrce_trace::diagnostic_write(line.data(),line.size())!=static_cast<ssize_t>(line.size())) failed=true;
    } catch (...) {}
}
struct Context { unsigned long long generation,attempt;unsigned key,session,object;const char* kind; };
inline Context*& current(){static thread_local Context* c=nullptr;return c;}
inline std::string fields(const Context& c){return "\"client_instance\":"+std::to_string(c.generation)+
    ",\"attempt\":"+std::to_string(c.attempt)+",\"client_key\":"+std::to_string(c.key)+
    ",\"session_id\":"+std::to_string(c.session)+",\"object_id\":"+std::to_string(c.object)+",\"entity_kind\":"+quote(c.kind);}
class Scope {
    Context c_; Context* previous_;
public:
    Scope(unsigned long long gen,unsigned key,unsigned session,unsigned object,const char* kind) noexcept:
      c_{gen,tfg_xrce_trace::next_id(),key,session,object,kind},previous_(current()){current()=&c_;}
    ~Scope(){current()=previous_;}
    void commit(bool success) noexcept {if(!tfg_xrce_trace::enabled())return;try{emit("\"event\":\"entity_commit\","+fields(c_)+",\"committed\":"+(success?"true":"false"));}catch(...) {}}
};
template<class Guid>std::string guid(const Guid& g){return hex(g.guidPrefix.value,12)+hex(g.entityId.value,4);}
struct Bound {Context context;std::string request_topic,reply_topic,reader_guid,writer_guid;};
inline std::map<const void*,Bound>& bindings(){static std::map<const void*,Bound> b;return b;}
inline std::mutex& binding_mutex(){static std::mutex m;return m;}
template<class Replier>void bind(Replier* p) noexcept {
    if (!tfg_xrce_trace::enabled())return;
    try {
        std::lock_guard<std::mutex> lock(binding_mutex());bindings().erase(p);
        if (!current() || bindings().size()>=128){emit("\"event\":\"identity_error\",\"incomplete\":true");return;}
        auto* reader=p->get_request_datareader();auto* writer=p->get_reply_datawriter();
        Bound b{*current(),reader->get_topicdescription()->get_name(),writer->get_topic()->get_name(),guid(reader->guid()),guid(writer->guid())};
        bindings().emplace(p,b);
        emit("\"event\":\"replier_created\","+fields(b.context)+",\"reader_guid\":"+quote(b.reader_guid)+
            ",\"writer_guid\":"+quote(b.writer_guid)+",\"request_topic\":"+quote(b.request_topic)+
            ",\"reply_topic\":"+quote(b.reply_topic)+",\"request_type\":"+quote(reader->get_topicdescription()->get_type_name())+
            ",\"reply_type\":"+quote(writer->get_topic()->get_type_name())+
            ",\"domain\":"+std::to_string(p->get_participant()->get_domain_id()));
    }catch(...){emit("\"event\":\"identity_error\",\"incomplete\":true");}
}
template<class Identity>void rpc(const void* p,const Identity& id,const char* event,bool success) noexcept {
    if (!tfg_xrce_trace::enabled())return;
    try {
        std::lock_guard<std::mutex> lock(binding_mutex());auto it=bindings().find(p);
        if (it==bindings().end()){emit("\"event\":\"unbound_rpc\",\"incomplete\":true");return;}
        emit("\"event\":"+quote(event)+","+fields(it->second.context)+
            ",\"request_writer_guid\":"+quote(guid(id.writer_guid()))+
            ",\"request_sequence_high\":"+std::to_string(id.sequence_number().high)+
            ",\"request_sequence_low\":"+std::to_string(id.sequence_number().low)+
            ",\"accepted\":"+(success?"true":"false"));
    }catch(...){emit("\"event\":\"identity_error\",\"incomplete\":true");}
}
template<class Identity>std::string sample(const Identity& id){
    return "{\"writer_guid\":"+quote(guid(id.writer_guid()))+",\"sequence_high\":"+
        std::to_string(id.sequence_number().high)+",\"sequence_low\":"+std::to_string(id.sequence_number().low)+"}";
}
template<class Identity>void rpc_metadata(const void* p,const Identity& request,const Identity& related,
        const Identity& written,const char* event,bool success) noexcept {
    if(!tfg_xrce_trace::enabled())return;
    try{std::lock_guard<std::mutex> lock(binding_mutex());auto i=bindings().find(p);
        if(i==bindings().end()){emit("\"event\":\"unbound_rpc\",\"incomplete\":true");return;}
        emit("\"event\":"+quote(event)+","+fields(i->second.context)+
            ",\"rpc_contract\":\"FASTDDS_RPC_IDENTITIES_V2\",\"request_identity\":"+sample(request)+
            ",\"related_identity\":"+sample(related)+",\"written_identity\":"+sample(written)+
            ",\"replier_reader_guid\":"+quote(i->second.reader_guid)+",\"replier_writer_guid\":"+quote(i->second.writer_guid)+
            ",\"accepted\":"+(success?"true":"false"));
    }catch(...){emit("\"event\":\"identity_error\",\"incomplete\":true");}
}
template<class Reader>void reader(const Reader* p) noexcept {
    if (!tfg_xrce_trace::enabled())return;
    try {if (!current())return;emit("\"event\":\"input_created\","+fields(*current())+
        ",\"reader_guid\":"+quote(guid(p->guid()))+",\"topic\":"+quote(p->get_topicdescription()->get_name())+
        ",\"type\":"+quote(p->get_topicdescription()->get_type_name()));}catch(...){}
}
template<class Publisher,class Config>void bridge(const Publisher& p,const Config& config,const std::string& path,const char* event) noexcept {
    if (!tfg_xrce_trace::enabled())return;
    try {if(std::string(p.get_topic_name())!="/rover1/odometry")return;const auto& gid=p.get_gid();emit("\"event\":"+quote(event)+
        ",\"ros_topic\":"+quote(p.get_topic_name())+",\"gz_topic\":"+quote(config.gz_topic_name)+
        ",\"ros_type\":"+quote(config.ros_type_name)+",\"gz_type\":"+quote(config.gz_type_name)+
        ",\"gid\":"+quote(hex(gid.data,sizeof(gid.data)))+",\"rmw\":"+quote(gid.implementation_identifier?gid.implementation_identifier:"")+
        ",\"config_file\":"+quote(path));}catch(...){}
}
}
