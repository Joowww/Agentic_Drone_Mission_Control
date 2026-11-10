#pragma once
// Existing stderr channel only. No sample records, ROS, DDS or signals.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <exception>
#include <fcntl.h>
#include <mutex>
#include <thread>
#include <unistd.h>

namespace tfg_identity_probe {
inline bool terminal_stderr_ready() {
  const int flags=::fcntl(2,F_GETFL);
  return flags>=0 && ::fcntl(2,F_SETFL,flags|O_NONBLOCK)==0;
}
inline void terminal(const char*reason,const char*stage,int code=2,const char*detail=nullptr) noexcept {
  // Fixed literal reason/stage call sites, one small nonblocking write. A full
  // or broken diagnostic pipe must never postpone the watchdog's hard exit.
  char line[192];
  const int n=std::snprintf(line,sizeof(line),"receiver: UNCERTAIN reason=%s stage=%s rc=%d%s%s\n",
      reason,stage,code,detail?" detail=":"",detail?detail:"");
  if(n>0 && n<static_cast<int>(sizeof(line))) {
    const auto ignored=::write(2,line,static_cast<size_t>(n));(void)ignored;
  }
}
inline void terminal_exception(const char*stage,const std::exception&error) noexcept {
  // Only fixed, reviewed reasons leave the catch. Never copy arbitrary what()
  // text (paths, payloads, newlines) into the bounded terminal diagnostic.
  const char*detail="UNCLASSIFIED_STD_EXCEPTION";
  const char*message=error.what();
  if(message) {
    if(!std::strcmp(message,"Monitor unavailable"))detail="MONITOR_UNAVAILABLE";
    else if(!std::strcmp(message,"Diagnostic cap reached"))detail="DIAGNOSTIC_CAP";
    else if(!std::strcmp(message,"Stale monitor observation"))detail="STALE_MONITOR";
    else if(!std::strcmp(message,"Session execution/selection changed"))detail="SESSION_EXECUTION_CHANGED";
    else if(!std::strcmp(message,"Session descriptor changed"))detail="SESSION_DESCRIPTOR_CHANGED";
    else if(!std::strcmp(message,"Output budget exhausted"))detail="OUTPUT_BUDGET";
    else if(!std::strcmp(message,"Pipe write failed"))detail="PIPE_WRITE";
    else if(!std::strcmp(message,"Pipe write deadline"))detail="PIPE_DEADLINE";
  }
  terminal("EXCEPTION",stage,2,detail);
}
class Deadline {
  std::mutex mutex_;std::condition_variable wake_;bool done_=false;std::thread thread_;
public:
  // Production uses the unchanged 120 s. The pure offline contract fixture can
  // exercise this same branch at a short duration without a middleware node.
  explicit Deadline(std::atomic<const char*>&stage,
                    std::chrono::milliseconds duration=std::chrono::seconds(120)):
    thread_([this,&stage,duration]{
      std::unique_lock<std::mutex>lock(mutex_);
      if(!wake_.wait_for(lock,duration,[this]{return done_;})) {
        terminal("WATCHDOG",stage.load());std::_Exit(2);
      }
    }) {}
  ~Deadline(){
    {std::lock_guard<std::mutex>lock(mutex_);done_=true;}
    wake_.notify_one();thread_.join();
  }
};
}
