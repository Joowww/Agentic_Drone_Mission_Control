// Explicit local passive source for the EXISTING Python adapter, never control.
#include "../rover_passive_rclcpp/collector_core.hpp"
#include "session_context.hpp"
#include "parameter_rpc.hpp"
#include "receiver_terminal.hpp"
#include "phase_selection.hpp"
#include "status_diagnostic.hpp"
#include <gz/transport/Node.hh>
#include <gz/msgs/empty.pb.h>
#include <gz/msgs/scene.pb.h>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <signal.h>
#include <iostream>
#include <sys/stat.h>
#include <thread>
#include <condition_variable>

using namespace tfg::rover_passive;
namespace {
std::string quote(const std::string&v){return json_quote(v);}
std::string ns(const char*name){char value[128];auto n=readlink((std::string("/proc/self/ns/")+name).c_str(),value,sizeof(value));
 if(n<=0||n==sizeof(value))throw std::runtime_error("Clock namespace unavailable");
 return std::string(value,n);}
std::string process(const tfg_identity_probe::Session&s){struct stat value;if(::stat("/proc/self/exe",&value))throw std::runtime_error("Executable identity unavailable");
 char path[4096];auto n=::readlink("/proc/self/exe",path,sizeof(path));if(n<=0||n==sizeof(path))throw std::runtime_error("Executable path unavailable");
 return "{\"pid\":"+std::to_string(getpid())+
 ",\"start_ticks\":"+tfg_identity_probe::ticks(getpid())+",\"boot_id\":"+quote(s.boot)+
 ",\"executable\":"+quote(std::string(path,n))+",\"exe_inode\":"+std::to_string(value.st_ino)+",\"exe_device\":"+std::to_string(value.st_dev)+
 ",\"net_namespace\":"+quote(ns("net"))+",\"pid_namespace\":"+quote(ns("pid"))+",\"time_namespace\":"+quote(ns("time"))+"}";}
std::string body(const Sample&s){return std::visit([](const auto&m){
 std::ostringstream out;out<<"{\"header\":{\"stamp\":{\"sec\":"<<m.header.stamp.sec<<",\"nanosec\":"<<m.header.stamp.nanosec<<"},\"frame_id\":"<<json_quote(m.header.frame_id)<<"}";
 using M=std::decay_t<decltype(m)>;
 if constexpr(std::is_same_v<M,Status>){out<<",\"vehicle_type\":"<<unsigned(m.vehicle_type)<<",\"mode\":"<<unsigned(m.mode)
  <<",\"armed\":"<<(m.armed?"true":"false")<<",\"flying\":"<<(m.flying?"true":"false")<<",\"external_control\":"<<(m.external_control?"true":"false")<<",\"failsafe\":[";
  bool first=true;for(auto v:m.failsafe){if(!first)out<<',';first=false;out<<unsigned(v);}out<<']';
 }else{OdometryFieldsJson json(out);out<<",\"child_frame_id\":"<<json_quote(m.child_frame_id)<<",\"pose\":{\"pose\":{\"position\":";
  json.xyz("position",m.pose.pose.position);out<<",\"orientation\":{\"x\":";json.number("x",m.pose.pose.orientation.x);
  out<<",\"y\":";json.number("y",m.pose.pose.orientation.y);out<<",\"z\":";json.number("z",m.pose.pose.orientation.z);out<<",\"w\":";json.number("w",m.pose.pose.orientation.w);
  out<<"}},\"covariance\":";json.covariance("pose covariance",m.pose.covariance);out<<"},\"twist\":{\"twist\":{\"linear\":";
  json.xyz("linear",m.twist.twist.linear);out<<",\"angular\":";json.xyz("angular",m.twist.twist.angular);
  out<<"},\"covariance\":";json.covariance("twist covariance",m.twist.covariance);out<<'}';}
 out<<'}';return out.str();},s.message);}
class Output {
 const tfg_identity_probe::Session&s_;unsigned sequence_=0;size_t bytes_=0;
public:
 explicit Output(const tfg_identity_probe::Session&s):s_(s){if(fcntl(1,F_SETFL,fcntl(1,F_GETFL)|O_NONBLOCK)<0)throw std::runtime_error("Output setup failed");}
 void emit(const std::string&event,const std::string&fields){
  auto stamp=receive_time();auto row="{\"schema\":\"tfg.rover-observation-stream/1\",\"identity_verified\":false,\"movement_authorized\":false,\"session_id\":"+quote(s_.id)+
   ",\"sequence\":"+std::to_string(++sequence_)+",\"event\":"+quote(event)+",\"client_instance\":1,\"client_process\":"+process(s_)+
   ",\"receipt_steady_ns\":"+std::to_string(stamp.steady_ns)+","+fields+"}\n";
  if(row.size()>65536||bytes_+row.size()>458752||sequence_>128)throw std::runtime_error("Output budget exhausted");
  auto until=std::chrono::steady_clock::now()+std::chrono::milliseconds(250);size_t pos=0;
  while(pos<row.size()){
   auto n=::write(1,row.data()+pos,row.size()-pos);
   if(n>0){pos+=n;continue;}if(n<0&&errno!=EAGAIN&&errno!=EINTR)throw std::runtime_error("Pipe write failed");
   if(std::chrono::steady_clock::now()>=until)throw std::runtime_error("Pipe write deadline");
   pollfd fd{1,POLLOUT,0};::poll(&fd,1,1);
  }bytes_+=row.size();
 }
};
}
int main(int argc,char**argv){
 signal(SIGPIPE,SIG_IGN);
 if(!tfg_identity_probe::terminal_stderr_ready())return 2;
 const bool rpc_mode=argc>=4&&std::string(argv[3])=="--rpc-metadata";
 const bool phased=argc==5&&rpc_mode&&std::string(argv[4])=="--credit-selection";
 const bool status_mode=argc==4&&std::string(argv[3])=="--status-availability";
 if((argc!=3&&!(argc==4&&rpc_mode)&&!phased&&!status_mode)||std::string(argv[1])!="--session-id"){
  tfg_identity_probe::terminal("DELIBERATE","ARGUMENTS");return 2;
 }
 std::atomic<const char*>stage{"SESSION"};
 try{tfg_identity_probe::Deadline watchdog(stage);const auto started=std::chrono::steady_clock::now();
  tfg_identity_probe::Session session(argv[2]);Output output(session);auto options=rclcpp::NodeOptions().enable_rosout(false).start_parameter_services(false).start_parameter_event_publisher(false).use_global_arguments(false);
  tfg_status::Diagnostic* diagnostic=nullptr;
  if(status_mode){
   const char* owner=std::getenv("TFG_STATUS_DIAGNOSTIC");
   if(!owner||session.id!=owner)throw std::runtime_error("Status diagnostic owner differs");
   diagnostic=&tfg_status::Diagnostic::instance("receiver");
   if(!diagnostic->ready())throw std::runtime_error("Status diagnostic pipe/context unavailable");
  }
  stage="ROS_INIT";rclcpp::init(0,nullptr);auto node=std::make_shared<rclcpp::Node>("tfg_rover_observation_source",options);
  rclcpp::executors::SingleThreadedExecutor executor;executor.add_node(node);
  if(node->get_node_base_interface()->get_context()->get_domain_id()!=0)throw std::runtime_error("Unreviewed DDS domain");
  std::map<std::string,unsigned>counts{{"/ap/v3/status",0},{"/rover1/odometry",0}};
  std::map<std::string,int64_t>last_stamp;unsigned omitted=0,before_status=0,spacing_omitted=0;std::exception_ptr failure;
  std::unique_ptr<tfg_identity_probe::ParameterRpc>rpc;
  tfg_identity_probe::PhaseSelection selection;
  std::map<std::string,unsigned>callbacks,no_credit;
  std::map<std::string,int64_t>first_receipt,last_receipt;
  unsigned diagnostic_callbacks=0;bool matched_marker=false,graph_saved=false,match_query_logged=false;
  Observer::Diagnostic progress;
  if(diagnostic)progress=[&](const char*event,const Sample*sample){
   if(std::strcmp(event,"status_callback_enter")==0)++diagnostic_callbacks;
   if(sample&&diagnostic_callbacks>2)return;
   std::string fields;
   if(sample)fields="\"callback\":"+std::to_string(diagnostic_callbacks)+",\"original_receipt_ns\":"+std::to_string(sample->receipt.steady_ns);
   diagnostic->emit(event,fields);
  };
  output.emit("header","\"process\":"+process(session)+",\"max_samples\":20,\"duration_s\":120,\"spacing_source_ns\":"+std::string(phased?"0":"500000000")+",\"selection_mode\":"+quote(phased?"CREDIT_PHASED_V1":"DIAGNOSTIC_SPACING_V1")+",\"after_status\":true,\"clock_scope\":\"SAME_PROC_BOOT_AND_MONOTONIC\"");
  stage="SUBSCRIPTIONS";auto observer=std::make_unique<Observer>(*node,[&](const Sample&sample){try{
   ++callbacks[sample.topic];
   if(!first_receipt.count(sample.topic))first_receipt[sample.topic]=sample.receipt.steady_ns;
   last_receipt[sample.topic]=sample.receipt.steady_ns;
   if(counts.at(sample.topic)>=10){++omitted;return;}
   if(sample.topic=="/rover1/odometry"&&counts["/ap/v3/status"]==0){++before_status;return;}
   const auto stamp=std::visit([](const auto&m){return int64_t(m.header.stamp.sec)*1000000000+m.header.stamp.nanosec;},sample.message);
   if(phased){if(!selection.retain(sample.topic=="/ap/v3/status"?0:1,stamp)){++no_credit[sample.topic];return;}}
   else if(last_stamp.count(sample.topic)&&stamp-last_stamp.at(sample.topic)<500000000){++spacing_omitted;return;}
   auto serialized=serialize_sample(sample,true);
   output.emit("sample","\"topic\":"+quote(sample.topic)+",\"sample\":"+serialized.json+",\"body\":"+body(sample)+(phased?",\"selection_credit\":"+std::to_string(selection.credit())+",\"selection_phase\":"+quote(std::string(1,selection.current_phase())):""));
   ++counts.at(sample.topic);last_stamp[sample.topic]=stamp;
  }catch(...){failure=std::current_exception();}},receive_time,progress);
  if(diagnostic&&!diagnostic->create_marker(false))throw std::runtime_error("Status request marker uncertain");
  bool closing=false,diagnostic_exhausted=false,model_requested=false,scene_requested=false;auto next=started;
  stage="RECEPTION";
  try {
  while(rclcpp::ok()&&!closing&&counts.begin()->second+counts.rbegin()->second<20&&std::chrono::steady_clock::now()-started<std::chrono::milliseconds(119950)){
   const auto now=std::chrono::steady_clock::now();if(now>=next){session.check();next=now+std::chrono::seconds(1);}
   if(diagnostic&&!matched_marker){
    stage="STATUS_MATCH_QUERY";
    if(!match_query_logged)diagnostic->emit("status_match_query_enter");
    const auto count=observer->status_matches();
    if(!match_query_logged)diagnostic->emit("status_match_query_return","\"matched_publishers\":"+std::to_string(count));
    match_query_logged=true;
    if(count){
     session.check();
     stage="STATUS_DISCOVERY";
     if(!diagnostic->graph_snapshot(serialize_discovery(observer->discover("/ap/v3/status"))))
      throw std::runtime_error("Status discovery persistence uncertain");
     graph_saved=true;
     if(!diagnostic->create_marker(true))throw std::runtime_error("Status matched marker uncertain");
     diagnostic->emit("status_match","\"matched_publishers\":"+std::to_string(count));matched_marker=true;
    }
    stage="RECEPTION";
   }
   pollfd fd{0,POLLIN|POLLHUP,0};if(::poll(&fd,1,0)>0){char value;auto n=::read(0,&value,1);if(n==0||(n==1&&value=='C'))closing=true;
    else if(n==1&&phased){auto credit=selection.grant(value);output.emit("selection_credit","\"credit\":"+std::to_string(credit)+",\"phase\":"+quote(std::string(1,value)));}
    else throw std::runtime_error("Unexpected local input");}
   executor.spin_once(std::chrono::milliseconds(10));if(failure)std::rethrow_exception(failure);
   if(diagnostic&&diagnostic->exhausted())throw tfg_identity_probe::DiagnosticExhausted();
   if(rpc_mode&&counts["/ap/v3/status"]>0){
    if(!model_requested){tfg_identity_probe::trigger_model(session.id,session.prefix+"/capture/model_request");model_requested=true;}
    if(!rpc)rpc=std::make_unique<tfg_identity_probe::ParameterRpc>(0,[&](const auto&event,const auto&fields){output.emit(event,fields);});
    rpc->poll(std::chrono::duration<double>(now.time_since_epoch()).count());
   }
   if(rpc_mode&&!scene_requested&&counts["/ap/v3/status"]>0&&counts["/rover1/odometry"]>0){
    // Same existing read-only world catalog API, no aerial references/poses.
    scene_requested=true;gz::transport::Node gz_node;gz::msgs::Empty request;gz::msgs::Scene response;bool accepted=false;
    bool received=gz_node.Request("/world/runway/scene/info",request,1000,response,accepted);
    std::string catalog="[";
    if(received&&accepted)for(const auto&model:response.model()){
     if(catalog.size()>1)catalog+=",";
     catalog+="{\"id\":"+std::to_string(model.id())+",\"name\":"+quote(model.name())+"}";
    }
    output.emit("scene_catalog","\"received\":"+std::string(received&&accepted?"true":"false")+",\"body\":"+catalog+"]");
   }
  }
  }catch(const tfg_identity_probe::DiagnosticExhausted&){diagnostic_exhausted=true;}
  const bool interrupted=!rclcpp::ok()&&!closing;
  stage="CLOSE";
  if(diagnostic){
   if(!graph_saved)diagnostic->graph_snapshot(serialize_discovery(observer->discover("/ap/v3/status")));
   if(!observer->diagnostic_complete())diagnostic->emit("status_hook_error","\"incomplete\":true");
   diagnostic->finish();
  }
  if(rpc)rpc->close();
  observer.reset();executor.remove_node(node);node.reset();rclcpp::shutdown();
  if(diagnostic_exhausted){tfg_identity_probe::terminal("DELIBERATE","DIAGNOSTIC_CAP");return 2;}
  std::string cadence="{";
  for(const auto&entry:counts){const auto&t=entry.first;if(cadence.size()>1)cadence+=",";
   cadence+=quote(t)+":{\"callbacks\":"+std::to_string(callbacks[t])+",\"not_credited_or_nonprogressing\":"+std::to_string(no_credit[t])+",\"first_receipt_steady_ns\":"+std::to_string(first_receipt[t])+",\"last_receipt_steady_ns\":"+std::to_string(last_receipt[t])+"}";}
  cadence+="}";
  output.emit("footer","\"callback_coverage\":"+cadence+",\"reader_closed\":true,\"counts\":{\"/ap/v3/status\":"+std::to_string(counts["/ap/v3/status"])+",\"/rover1/odometry\":"+std::to_string(counts["/rover1/odometry"])+"},\"omitted_quota\":"+std::to_string(omitted)+",\"omitted_before_status\":"+std::to_string(before_status)+",\"omitted_spacing_or_nonprogressing\":"+std::to_string(spacing_omitted)+",\"termination\":"+quote(interrupted?"INTERRUPTED":closing?"LOCAL_CLOSE":counts.begin()->second+counts.rbegin()->second>=20?"SAMPLE_LIMIT":"DURATION_LIMIT"));
  if(interrupted){tfg_identity_probe::terminal("DELIBERATE","INTERRUPTED");return 2;}
  return 0;
 }catch(const std::exception&error){tfg_identity_probe::terminal_exception(stage.load(),error);return 2;}
 catch(...){tfg_identity_probe::terminal("EXCEPTION",stage.load(),2,"NON_STANDARD_EXCEPTION");return 2;}
}
