#pragma once
// Opt-in Status diagnostics on the existing stderr pipe and private session
// directory. No middleware, publisher, service, control or clock substitution.
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sstream>
#include <utility>
#include <sys/stat.h>
#include <pthread.h>
#include <signal.h>
#include <unistd.h>

namespace tfg_status {
inline long long steady_ns() noexcept {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline bool canonical(const std::string& s) {
  if(s.size()!=36)return false;
  for(unsigned i=0;i<s.size();++i) {
    if(i==8||i==13||i==18||i==23) {if(s[i]!='-')return false;}
    else if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return false;
  }return true;
}
inline bool sha(const std::string& s) {
  if(s.size()!=64)return false;
  for(char c:s)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
  return true;
}
inline std::string bounded_read(const std::string& path,unsigned cap) {
  int fd=::open(path.c_str(),O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
  if(fd<0)return {};
  char b[8193];if(cap>8192)cap=8192;
  auto n=::read(fd,b,cap+1);::close(fd);
  if(n<=0||static_cast<unsigned>(n)>cap)return {};
  return std::string(b,n);
}
inline unsigned long long ticks(int pid) {
  auto s=bounded_read("/proc/"+std::to_string(pid)+"/stat",8192);
  auto end=s.rfind(')');if(end==std::string::npos)return 0;
  const char* p=s.c_str()+end+2;
  if(*p=='Z')return 0;
  for(int field=3;field<22;++field) {p=std::strchr(p,' ');if(!p)return 0;++p;}
  char* e=nullptr;auto result=std::strtoull(p,&e,10);
  return e!=p&&result?result:0;
}
inline std::string boot() {
  auto s=bounded_read("/proc/sys/kernel/random/boot_id",64);
  if(!s.empty()&&s.back()=='\n')s.pop_back();
  return canonical(s)?s:"";
}
inline std::string ns(const char* name) {
  char b[80];auto n=::readlink((std::string("/proc/self/ns/")+name).c_str(),b,sizeof(b));
  return n>0&&n<static_cast<int>(sizeof(b))?std::string(b,n):"UNKNOWN";
}
struct Peer {int pid=0;unsigned long long start=0;};
inline ssize_t pipe_write(int fd,const char* data,unsigned size) noexcept {
  sigset_t mask,previous,pending;sigemptyset(&mask);sigaddset(&mask,SIGPIPE);
  if(::pthread_sigmask(SIG_BLOCK,&mask,&previous))return -1;
  const bool was_pending=::sigpending(&pending)!=0||::sigismember(&pending,SIGPIPE);
  auto rv=::write(fd,data,size);
  if(rv<0&&errno==EPIPE&&!was_pending) {timespec zero{0,0};(void)::sigtimedwait(&mask,nullptr,&zero);}
  (void)::pthread_sigmask(SIG_SETMASK,&previous,nullptr);return rv;
}

class Diagnostic {
  const char* role_;std::string owner_,context_,boot_;unsigned long long start_=0;
  int pipe_=-1,dir_=-1;unsigned seq_=0,normal_=0;
  std::atomic_flag busy_=ATOMIC_FLAG_INIT;
  std::atomic<unsigned> lost_{0};std::atomic<bool> complete_{true},limit_{false};
  std::atomic_flag polling_=ATOMIC_FLAG_INIT;
  unsigned cap_,row_;long long cost_=0,last_poll_=0;
  Peer requested_,matched_;std::atomic<bool> request_seen_{false},match_seen_{false};
  bool wire(const char* event,const std::string& fields,unsigned max) noexcept {
    char line[1025];auto n=std::snprintf(line,sizeof(line),
      "TFG_IDENTITY_TRACE {\"schema\":\"tfg.identity-trace/1\",\"event\":\"%s\",\"sequence\":%u,\"steady_ns\":%lld,\"lost\":%u%s%s}\n",
      event,++seq_,steady_ns(),lost(),fields.empty()?"":",",fields.c_str());
    if(n<=0||static_cast<unsigned>(n)>max||n>=static_cast<int>(sizeof(line))||
       pipe_write(pipe_,line,n)!=n) {complete_=false;++lost_;return false;}
    return true;
  }
  bool read_marker(const char* name,Peer& result) {
    int fd=::openat(dir_,name,O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);
    if(fd<0) {if(errno!=ENOENT) {complete_=false;++lost_;}return false;}
    struct stat st{};char b[257];ssize_t n=-1;
    if(!::fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==::geteuid()&&
       (st.st_mode&0077)==0&&st.st_nlink==1&&st.st_size>0&&st.st_size<=256)
      n=::read(fd,b,sizeof(b)-1);
    ::close(fd);
    if(n!=st.st_size||n<=0) {complete_=false;++lost_;return false;}
    b[n]=0;
    std::string owner,context,observed_boot,extra;int pid=0;unsigned long long start=0;
    std::istringstream in(std::string(b,n));
    if(!(in>>owner>>context>>pid>>start>>observed_boot)||(in>>extra)||b[n-1]!='\n'||
       owner_!=owner||context_!=context||boot_!=observed_boot||
       pid<=0||!start||ticks(pid)!=start) {complete_=false;++lost_;return false;}
    result.pid=pid;result.start=start;return true;
  }
public:
  // Explicit fd constructor is for pure offline fixtures and copied builds.
  // Production from_environment() always derives the fixed protected path.
  Diagnostic(const char* role,std::string owner,std::string context,int directory=-1)
      :role_(role),owner_(std::move(owner)),context_(std::move(context)),
       cap_(std::strcmp(role,"receiver")==0?11:std::strcmp(role,"agent")==0?8:94),
       row_(std::strcmp(role,"receiver")==0?240:768) {
    if(!canonical(owner_)||!sha(context_))return;
    boot_=boot();start_=ticks(::getpid());if(boot_.empty()||!start_)return;
    if(directory>=0)dir_=::fcntl(directory,F_DUPFD_CLOEXEC,3);
    else {
      int tmp=::open("/tmp",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
      int base=tmp<0 ? -1 : ::openat(tmp,"tfg_diagnostic_agents",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
      int session=base<0 ? -1 : ::openat(base,owner_.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
      dir_=session<0 ? -1 : ::openat(session,"capture",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
      if(session>=0)::close(session);
      if(base>=0)::close(base);
      if(tmp>=0)::close(tmp);
    }
    struct stat d{},a{},b{};
    if(dir_<0||::fstat(dir_,&d)||!S_ISDIR(d.st_mode)||d.st_uid!=::geteuid()||(d.st_mode&0077))return;
    // open, not dup: a new open description preserves the original pipe flags.
    pipe_=::open("/proc/self/fd/2",O_WRONLY|O_NONBLOCK|O_CLOEXEC);
    if(pipe_<0||::fstat(2,&a)||::fstat(pipe_,&b)||!S_ISFIFO(a.st_mode)||
       a.st_dev!=b.st_dev||a.st_ino!=b.st_ino) {if(pipe_>=0)::close(pipe_);pipe_=-1;return;}
    std::string fields="\"role\":\""+std::string(role_)+"\",\"owner\":\""+owner_+
      "\",\"context_sha256\":\""+context_+"\",\"pid\":"+std::to_string(::getpid())+
      ",\"process_start_ticks\":"+std::to_string(start_)+",\"boot_id\":\""+boot_+
      "\",\"net_namespace\":\""+ns("net")+"\",\"pid_namespace\":\""+ns("pid")+
      "\",\"time_namespace\":\""+ns("time")+"\"";
    wire("status_context",fields,768);
  }
  ~Diagnostic(){if(pipe_>=0)::close(pipe_);if(dir_>=0)::close(dir_);}
  Diagnostic(const Diagnostic&)=delete;Diagnostic& operator=(const Diagnostic&)=delete;
  static Diagnostic& instance(const char* role) {
#ifdef TFG_STATUS_DIAGNOSTIC_FIXTURE
    const char* fd=::getenv("TFG_STATUS_DIAGNOSTIC_FIXTURE_FD");
    const int directory=fd?std::atoi(fd):-1;
#else
    const int directory=-1;
#endif
    static Diagnostic value(role,::getenv("TFG_STATUS_DIAGNOSTIC")?::getenv("TFG_STATUS_DIAGNOSTIC"):"",
      ::getenv("TFG_STATUS_DIAGNOSTIC_CONTEXT")?::getenv("TFG_STATUS_DIAGNOSTIC_CONTEXT"):"",directory);
    return value;
  }
  bool ready()const noexcept{return pipe_>=0&&dir_>=0;}
  bool complete()const noexcept{return ready()&&complete_&&lost_.load()==0&&!limit_;}
  bool exhausted()const noexcept{return limit_.load();}
  bool matched()const noexcept{return match_seen_;}
  bool requested()const noexcept{return request_seen_;}
  unsigned lost()const noexcept{return lost_.load();}
  bool emit(const char* event,const std::string& fields="") noexcept {
    if(!ready())return false;
    if(busy_.test_and_set()) {++lost_;return false;}
    const auto begin=steady_ns();bool ok=false;
    if(normal_>=cap_) {
      if(!limit_) {limit_=true;wire("status_limit","\"incomplete\":true",row_);}
      ++lost_;
    }else {++normal_;ok=wire(event,fields,row_);}
    cost_+=steady_ns()-begin;busy_.clear();return ok;
  }
  void finish() noexcept {
    if(!ready())return;
    // Separate reserved summary, even after the data count limit. It carries
    // no publication verdict and can itself be absent after EPIPE/EAGAIN.
    if(busy_.test_and_set()) {++lost_;return;}
    try {wire("status_summary","\"complete\":"+std::string(complete()?"true":"false")+
      ",\"diagnostic_cost_ns\":"+std::to_string(cost_),row_);}
    catch(...) {complete_=false;++lost_;}
    busy_.clear();
  }
  bool create_marker(bool match) noexcept {
    if(!ready())return false;
    try {
      auto data=owner_+" "+context_+" "+std::to_string(::getpid())+" "+
        std::to_string(start_)+" "+boot_+"\n";
      int fd=::openat(dir_,match?"status_matched":"status_request",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
      if(fd<0)return false;
      const auto written=::write(fd,data.data(),data.size());int sync=::fsync(fd),closed=::close(fd);
      if(written!=static_cast<ssize_t>(data.size())||sync||closed) {complete_=false;++lost_;return false;}
      return true;
    }catch(...) {complete_=false;++lost_;return false;}
  }
  bool graph_snapshot(const std::string& graph) noexcept {
    if(!ready())return false;
    try {
      auto data="{\"owner\":\""+owner_+"\",\"context_sha256\":\""+context_+"\",\"graph\":"+graph+"}\n";
      if(data.size()>32768) {complete_=false;++lost_;return false;}
      int fd=::openat(dir_,"status-discovery.json",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
      if(fd<0) {complete_=false;++lost_;return false;}
      auto written=::write(fd,data.data(),data.size());int sync=::fsync(fd),closed=::close(fd);
      if(written!=static_cast<ssize_t>(data.size())||sync||closed) {complete_=false;++lost_;return false;}
      return true;
    }catch(...) {complete_=false;++lost_;return false;}
  }
  void poll_markers() noexcept {
    if(!ready()||match_seen_)return;
    if(polling_.test_and_set())return;
    struct Unlock {std::atomic_flag& flag;~Unlock(){flag.clear();}} unlock{polling_};
    try {
    auto now=steady_ns();if(now-last_poll_<250000000)return;last_poll_=now;
    if(!request_seen_&&read_marker("status_request",requested_)) {
      request_seen_=true;emit("status_request_seen","\"receiver_pid\":"+std::to_string(requested_.pid)+
        ",\"receiver_start_ticks\":"+std::to_string(requested_.start));
    }
    if(request_seen_) {
      Peer peer;
      if(read_marker("status_matched",peer)) {
        if(peer.pid!=requested_.pid||peer.start!=requested_.start) {complete_=false;++lost_;return;}
        matched_=peer;match_seen_=true;emit("status_match_seen","\"receiver_pid\":"+std::to_string(peer.pid)+
          ",\"receiver_start_ticks\":"+std::to_string(peer.start));
      }
    }
    }catch(...) {complete_=false;++lost_;}
  }
};
} // namespace tfg_status
