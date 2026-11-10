"""Compile production receiver source with explicit middleware/session test doubles.

Not the operational 37c9 binary or installed ROS ABI. No ROS/DDS libraries,
participants, SDK, real session files or alternate production reader are used.
The receiver main, Output, Observer, serializer, PhaseSelection and terminal
code are unchanged. A private extra pipe supplies synthetic callback arrivals.
"""
from pathlib import Path
import shutil, subprocess
from tests.test_rover_passive_rclcpp import STUB

SESSION_STUB = r'''
#pragma once
#include <chrono>
#include <fstream>
#include <sstream>
#include <string>
#include <stdexcept>
#include <unistd.h>
namespace tfg_identity_probe {
struct DiagnosticExhausted:std::runtime_error{DiagnosticExhausted():std::runtime_error("Diagnostic cap reached"){} };
inline std::string ticks(int pid){
 std::ifstream f("/proc/"+std::to_string(pid)+"/stat");std::string s,v;std::getline(f,s);
 std::istringstream in(s.substr(s.rfind(')')+2));for(int n=3;n<=22;++n)in>>v;return v;
}
struct Session {std::string id,prefix="SYNTHETIC_NO_SESSION",boot;
 explicit Session(std::string value):id(value){std::ifstream f("/proc/sys/kernel/random/boot_id");std::getline(f,boot);}
 void check()const{} // explicit synthetic session, not a real admission fixture
};
inline void trigger_model(const std::string&,const std::string&){}
}
'''
RPC_STUB = r'''
#pragma once
#include <functional>
#include <cstdlib>
#include <thread>
namespace tfg_identity_probe {
class ParameterRpc {
 std::function<void(const std::string&,const std::string&)>emit_;bool done_=false;
public:
 ParameterRpc(unsigned,std::function<void(const std::string&,const std::string&)>e):emit_(e){}
 void poll(double){if(done_)return;done_=true;
  emit_("rpc_request","\"accepted\":true,\"fixture\":\"SYNTHETIC_NO_DDS\"");
  if(const char*d=std::getenv("TFG_SYNTHETIC_RPC_DELAY_MS"))std::this_thread::sleep_for(std::chrono::milliseconds(std::atoi(d)));
  emit_("rpc_reply","\"fixture\":\"SYNTHETIC_NO_DDS\"");
 }
 void close(){}
};
}
'''
EXTRA_STUB = r'''
namespace rclcpp {
struct NodeOptions {
 NodeOptions& enable_rosout(bool){return *this;} NodeOptions& start_parameter_services(bool){return *this;}
 NodeOptions& start_parameter_event_publisher(bool){return *this;} NodeOptions& use_global_arguments(bool){return *this;}
};
inline void init(int,char**){} inline bool ok(){return true;} inline void shutdown(){
 if(const char*p=std::getenv("TFG_SYNTHETIC_SHUTDOWN_FILE")){std::ofstream f(p);f<<"SYNTHETIC_RCLCPP_SHUTDOWN\n";}
}
namespace executors {
class SingleThreadedExecutor {
 std::shared_ptr<Node>node_;unsigned ss_=0,os_=0;
public:
 void add_node(std::shared_ptr<Node>n){node_=n;}
 void remove_node(std::shared_ptr<Node>){node_.reset();}
 void spin_once(std::chrono::milliseconds delay){
  int fd=std::atoi(std::getenv("TFG_SYNTHETIC_INPUT_FD"));pollfd f{fd,POLLIN,0};
  if(::poll(&f,1,int(delay.count()))<=0)return;
  char c;if(::read(fd,&c,1)!=1)return;
  if(c=='X'){::write(2,"SYNTHETIC_EXIT_WITHOUT_FOOTER\n",30);std::_Exit(0);}
  MessageInfo info;info.value.publisher_gid.implementation_identifier="rmw_fastrtps_cpp";
  if(c=='S'||c=='s'||c=='T'){
   auto msg=std::make_shared<ardupilot_msgs::msg::Status>();msg->header.frame_id="status";
   if(c=='S')++ss_;if(c=='T')ss_+=50;
   msg->header.stamp.sec=ss_/100;msg->header.stamp.nanosec=(ss_%100)*10000000;info.value.publisher_gid.data[0]=1;node_->status(msg,info);
  } else if(c=='O'||c=='o'){
   auto msg=std::make_shared<nav_msgs::msg::Odometry>();msg->header.frame_id="odom";msg->child_frame_id="base_link";
   if(c=='O')++os_;msg->header.stamp.nanosec=os_*10000000;info.value.publisher_gid.data[0]=2;node_->odometry(msg,info);
  }
  const int feedback=std::atoi(std::getenv("TFG_SYNTHETIC_FEEDBACK_FD"));::write(feedback,&c,1);
 }
};
}
}
'''
GZ_STUB = r'''
#pragma once
#include <vector>
#include <string>
namespace gz {
namespace msgs {struct Empty{};struct Model{int id()const{return 67;}std::string name()const{return "SYNTHETIC_MODEL";}};
 struct Scene{std::vector<Model>model()const{return {Model{}};}};}
namespace transport {struct Node {template<class A,class B>bool Request(const char*,A&,int,B&,bool&ok){ok=true;return true;}};}
}
'''

def build(root, *, source_root, session_stub=SESSION_STUB):
    root=Path(root);source_root=Path(source_root);snapshot=root/'snapshot';snapshot.mkdir(parents=True)
    files=['tools/rover_identity_probe/observation_receiver.cpp','tools/rover_identity_probe/phase_selection.hpp',
           'tools/rover_identity_probe/receiver_terminal.hpp','tools/rover_identity_probe/status_diagnostic.hpp','tools/rover_passive_rclcpp/observer.hpp',
           'tools/rover_passive_rclcpp/collector_core.hpp']
    for name in files:
        p=snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source_root/name,p)
    for name,data in [('session_context.hpp',session_stub),('parameter_rpc.hpp',RPC_STUB)]:
        (snapshot/'tools/rover_identity_probe'/name).write_text(data)
    stub=STUB.replace('bool armed=false;', 'bool armed=false; bool flying=false,external_control=false; int mode=0; std::vector<unsigned char> failsafe;')
    stub=stub.replace('struct Node {','struct NodeOptions;\nstruct Node {\n Node(const char*, const NodeOptions&) {}\n struct Base {struct Context{unsigned get_domain_id()const{return 0;}};std::shared_ptr<Context> get_context(){return std::make_shared<Context>();}};\n std::shared_ptr<Base>get_node_base_interface(){return std::make_shared<Base>();}')
    stub='#include <fstream>\n#include <map>\n#include <atomic>\n#include <chrono>\n#include <thread>\n#include <cstdlib>\n#include <poll.h>\n#include <unistd.h>\n'+stub+EXTRA_STUB
    includes=root/'include';includes.mkdir()
    (includes/'synthetic.hpp').write_text(stub)
    for path in ('ardupilot_msgs/msg/status.hpp','nav_msgs/msg/odometry.hpp','rclcpp/rclcpp.hpp','rclcpp/message_info.hpp','rmw/types.h'):
        p=includes/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "synthetic.hpp"\n')
    for path in ('gz/transport/Node.hh','gz/msgs/empty.pb.h','gz/msgs/scene.pb.h'):
        p=includes/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "gz_test.hpp"\n')
    (includes/'gz_test.hpp').write_text(GZ_STUB)
    import hashlib,json,time
    paths=sorted(p for p in root.rglob('*') if p.is_file());before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (root/'snapshot-hashes-before.json').write_text(json.dumps(before,indent=2))
    compiler=shutil.which('c++');assert compiler,'Installed C++ compiler required'
    cmd=[compiler,'-std=c++17','-pthread','-O0','-g','-DTFG_STATUS_DIAGNOSTIC_FIXTURE=1','-I',str(includes),str(snapshot/files[0]),'-o',str(root/'receiver-synthetic')]
    start=time.monotonic();result=subprocess.run(cmd,capture_output=True)
    (root/'build.stdout').write_bytes(result.stdout);(root/'build.stderr').write_bytes(result.stderr)
    (root/'build-command.json').write_text(json.dumps({'argv':cmd,'returncode':result.returncode,'elapsed_s':time.monotonic()-start},indent=2))
    assert result.returncode==0,result.stderr.decode()
    assert before=={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in before}
    return root/'receiver-synthetic'
