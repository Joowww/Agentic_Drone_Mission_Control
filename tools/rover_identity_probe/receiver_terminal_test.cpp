// Pure process/pipe fixture, NOT the receiver. No ROS/DDS dependency or init.
#include "receiver_terminal.hpp"
#include <fstream>
#include <stdexcept>
#include <string>
#include <chrono>
#include <thread>
#include <signal.h>
int main(int argc,char**argv){
  signal(SIGPIPE,SIG_IGN);
  if(!tfg_identity_probe::terminal_stderr_ready())return 2;
  if(argc!=3){tfg_identity_probe::terminal("DELIBERATE","ARGUMENTS");return 2;}
  std::atomic<const char*>stage{"REPLAY"};
  try {
    std::ifstream input(argv[2],std::ios::binary);
    std::string data((std::istreambuf_iterator<char>(input)),{});
    if(!input || data.size()>458752)throw std::runtime_error("Fixture input");
    const char*p=data.data();size_t remaining=data.size();
    while(remaining){auto n=::write(1,p,remaining);if(n<=0)throw std::runtime_error("Fixture pipe");p+=n;remaining-=static_cast<size_t>(n);}
    const std::string mode=argv[1];
    tfg_identity_probe::Deadline deadline(stage,std::chrono::milliseconds(80));
    stage="CLOSE";
    if(mode=="watchdog"){std::this_thread::sleep_for(std::chrono::seconds(1));return 3;}
    if(mode=="exception")throw std::runtime_error("Synthetic close failure");
    if(mode=="deliberate"){tfg_identity_probe::terminal("DELIBERATE","TEST_EXIT");return 2;}
    if(mode=="success")return 0;
    if(mode=="signal"){::raise(SIGTERM);return 3;}
    throw std::runtime_error("Unknown fixture mode");
  }catch(...){tfg_identity_probe::terminal("EXCEPTION",stage.load());return 2;}
}
