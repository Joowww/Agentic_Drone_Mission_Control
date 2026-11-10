#pragma once
// Opt-in diagnostics in a SOURCE COPY. No control or Gazebo component writes.
#include "trace.hpp"
#include <gz/sim/Util.hh>
#include <gz/sim/components/SystemPluginInfo.hh>
#include <openssl/sha.h>
#include <tinyxml2.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <map>
#include <fcntl.h>
#include <cmath>
namespace tfg_model_trace {
using tfg_xrce_trace::quote;
inline bool enabled(){const char* e=std::getenv("TFG_MODEL_TRACE");return e&&std::strcmp(e,"1")==0;}
inline void emit(const std::string& fields) noexcept {
 if(!enabled())return;
 try{
  static std::mutex m;static unsigned sequence=0;static bool failed=false;
  std::lock_guard<std::mutex> lock(m);if(failed||sequence>=32)return;++sequence;
  auto now=std::chrono::steady_clock::now().time_since_epoch();auto wall=std::chrono::system_clock::now().time_since_epoch();
  auto text="TFG_MODEL_TRACE {\"schema\":\"tfg.model-source/1\","+tfg_xrce_trace::process_identity()+
   ",\"sequence\":"+std::to_string(sequence)+",\"steady_ns\":"+std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(now).count())+
   ",\"wall_unix_ns\":"+std::to_string(std::chrono::duration_cast<std::chrono::nanoseconds>(wall).count())+","+
   (sequence==32?"\"event\":\"limit\",\"incomplete\":true":fields)+",\"movement_authorized\":false}\n";
  if(text.size()>4096||tfg_xrce_trace::diagnostic_write(text.data(),text.size())!=static_cast<ssize_t>(text.size()))failed=true;
 }catch(...){}
}
inline std::string num(double v){if(!std::isfinite(v))return "null";std::ostringstream s;s<<std::setprecision(17)<<v;return s.str();}
template<class Pose>std::string pose(const Pose& p){return "["+num(p.Pos().X())+","+num(p.Pos().Y())+","+num(p.Pos().Z())+","+num(p.Rot().X())+","+num(p.Rot().Y())+","+num(p.Rot().Z())+","+num(p.Rot().W())+"]";}
template<class Vector>std::string vec(const Vector& p){return "["+num(p.X())+","+num(p.Y())+","+num(p.Z())+"]";}
inline std::string config(const std::string& xml){
 if(xml.size()>16384)throw std::runtime_error("Plugin XML exceeds diagnostic read bound");
 tinyxml2::XMLDocument doc;const auto wrapped="<root>"+xml+"</root>";
 if(doc.Parse(wrapped.c_str())!=tinyxml2::XML_SUCCESS)throw std::runtime_error("Invalid plugin XML");
 std::string out="{";auto* root=doc.RootElement();
 for(const char* key:{"odom_topic","odom_frame","robot_base_frame","dimensions","odom_publish_frequency","gaussian_noise","xyz_offset","rpy_offset","fdm_addr","fdm_port_in","gazeboXYZToNED","modelXYZToAirplaneXForwardZDown","imuName"}){
  auto* e=root->FirstChildElement(key);if(e&&e->NextSiblingElement(key))throw std::runtime_error("Duplicate plugin setting");
  if(out.size()>1)out+=",";out+=quote(key)+":"+(e&&e->GetText()?quote(e->GetText()):"null");
 }
 return out+"}";
}
inline std::string socket_fields(int fd){
 struct stat st{};sockaddr_in address{};socklen_t n=sizeof(address);
 if(fd<0||fstat(fd,&st)||!S_ISSOCK(st.st_mode)||getsockname(fd,reinterpret_cast<sockaddr*>(&address),&n)||address.sin_family!=AF_INET)
  return "\"socket_observation\":null";
 char host[INET_ADDRSTRLEN]{};if(!inet_ntop(AF_INET,&address.sin_addr,host,sizeof(host)))return "\"socket_observation\":null";
 return "\"socket_observation\":{\"fd\":"+std::to_string(fd)+",\"inode\":"+std::to_string(st.st_ino)+",\"address\":"+quote(host)+",\"port\":"+std::to_string(ntohs(address.sin_port))+",\"source\":\"fstat + getsockname on actual JSON socket\"}";
}
struct Bound{unsigned instance=0,seen_states=0,retained_state=0,sent_rows=0;gz::sim::Entity model=0;bool metadata=false;double last_sim=-1;unsigned last_sent_generation=0;};
inline std::map<const void*,Bound>& bindings(){static std::map<const void*,Bound> b;return b;}
inline std::mutex& mutex(){static std::mutex m;return m;}
inline std::string context(const Bound& b){return "\"lifecycle_id\":"+(std::getenv("TFG_MODEL_SESSION")?quote(std::getenv("TFG_MODEL_SESSION")):"null")+","+"\"plugin_instance\":"+std::to_string(b.instance)+",\"model_entity\":"+std::to_string(b.model);}
template<class Pose>void configured(const void* instance,gz::sim::Entity model,int fd,const Pose& model_transform,const Pose& world_transform) noexcept {
 if(!enabled())return;try{std::lock_guard<std::mutex> lock(mutex());static unsigned generation=0;
  if(bindings().size()>=8&&bindings().count(instance)==0)throw std::runtime_error("Instance bound");
  auto& b=bindings()[instance];b=Bound{++generation,0,0,0,model};
  emit("\"event\":\"configured\","+context(b)+","+socket_fields(fd)+",\"model_to_aircraft\":"+pose(model_transform)+",\"gazebo_to_ned\":"+pose(world_transform));
 }catch(...){emit("\"event\":\"error\",\"incomplete\":true");}
}
inline bool capture_requested(){
 static bool accepted=false;static auto next=std::chrono::steady_clock::time_point{};
 if(accepted)return true;const auto now=std::chrono::steady_clock::now();if(now<next)return false;next=now+std::chrono::milliseconds(250);
 const char* id=std::getenv("TFG_MODEL_SESSION");const char* path=std::getenv("TFG_MODEL_REQUEST_PATH");
 if(!id||!path)return false;
 const std::string session(id);if(session.size()!=36||std::string(path)!="/tmp/tfg_diagnostic_agents/"+session+"/capture/model_request")throw std::runtime_error("Model request scope differs");
 int fd=::open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
 if(fd<0){if(errno==ENOENT)return false;throw std::runtime_error("Model request unavailable");}
 struct stat st{};char bytes[64]{};const auto length=::read(fd,bytes,sizeof(bytes));const bool valid=::fstat(fd,&st)==0&&S_ISREG(st.st_mode)&&st.st_uid==::geteuid()&&(st.st_mode&0777)==0600&&length==37&&std::string(bytes,37)==session+"\n";
 const int rc=::close(fd);if(!valid||rc)throw std::runtime_error("Model request invalid/close uncertain");accepted=true;return true;
}
template<class Pose,class Vector>void state(const void* instance,double time,const gz::sim::EntityComponentManager& ecm,gz::sim::Entity model,gz::sim::Entity link,const Pose& raw,const Vector& velocity,const Pose& fdm,const Vector& fdm_velocity) noexcept {
 if(!enabled())return;try{std::lock_guard<std::mutex> lock(mutex());auto i=bindings().find(instance);if(i==bindings().end())throw std::runtime_error("Unbound plugin");auto& b=i->second;
  b.retained_state=0;
  if(model!=b.model)throw std::runtime_error("Entity changed");
  if(!b.metadata){b.metadata=true;auto* info=ecm.Component<gz::sim::components::SystemPluginInfo>(model);
   if(!info)emit("\"event\":\"plugins_unknown\","+context(b));
   else{unsigned slot=0;for(const auto& p:info->Data().plugins()){
    ++slot;if(p.name()!="ArduPilotPlugin"&&p.name()!="gz::sim::systems::OdometryPublisher")continue;
    unsigned char digest[SHA256_DIGEST_LENGTH];SHA256(reinterpret_cast<const unsigned char*>(p.innerxml().data()),p.innerxml().size(),digest);
    emit("\"event\":\"attached_plugin\","+context(b)+",\"slot\":"+std::to_string(slot)+",\"name\":"+quote(p.name())+",\"filename\":"+quote(p.filename())+",\"xml_sha256\":"+quote(tfg_xrce_trace::hex(digest,sizeof(digest)))+",\"effective_sdf\":"+config(p.innerxml())+",\"source\":\"ECM SystemPluginInfo populated on instantiation\"");
   }}
  }
  if(!capture_requested()||b.seen_states>=3)return;
  if(!std::isfinite(time)||time<b.last_sim)throw std::runtime_error("Source clock rewind");
  if(b.seen_states&&time-b.last_sim<0.5)return;
  b.last_sim=time;b.retained_state=++b.seen_states;
  std::string ancestry="[";auto current=link;bool reaches=false;for(unsigned n=0;n<32&&current!=gz::sim::kNullEntity;++n){if(ancestry.size()>1)ancestry+=",";ancestry+=std::to_string(current);if(current==model){reaches=true;break;}current=ecm.ParentEntity(current);}ancestry+="]";
  emit("\"event\":\"pose_input\","+context(b)+",\"state_generation\":"+std::to_string(b.retained_state)+",\"sim_time_s\":"+num(time)+",\"input_link_entity\":"+std::to_string(link)+",\"link_parent_chain\":"+ancestry+",\"link_reaches_model\":"+(reaches?"true":"false")+",\"world_link_pose_m_xyzw\":"+pose(raw)+",\"world_model_pose_m_xyzw\":"+pose(gz::sim::worldPose(model,ecm))+",\"world_linear_m_s\":"+vec(velocity)+",\"fdm_pose_m_xyzw\":"+pose(fdm)+",\"fdm_linear_m_s\":"+vec(fdm_velocity)+",\"source\":\"CreateStateJSON actual WorldPose input; THREE_TRIGGERED_STATES_SPACED_0.5_SIM_SECONDS\"");
 }catch(...){emit("\"event\":\"error\",\"incomplete\":true");}
}
inline void sent(const void* instance,int fd,const char* address,unsigned port,ssize_t bytes,size_t expected) noexcept {
 if(!enabled())return;try{std::lock_guard<std::mutex> lock(mutex());auto i=bindings().find(instance);if(i==bindings().end())throw std::runtime_error("Unbound send");auto& b=i->second;if(!b.retained_state||b.sent_rows>=3||b.last_sent_generation==b.retained_state)return;++b.sent_rows;b.last_sent_generation=b.retained_state;
  emit("\"event\":\"fdm_send\","+context(b)+",\"state_generation\":"+std::to_string(b.retained_state)+","+socket_fields(fd)+",\"destination_address\":"+(address?quote(address):"null")+",\"destination_port\":"+std::to_string(port)+",\"bytes_sent\":"+std::to_string(bytes)+",\"bytes_expected\":"+std::to_string(expected)+",\"source\":\"actual sendto result; no payload retained\"");
 }catch(...){emit("\"event\":\"error\",\"incomplete\":true");}
}
}
