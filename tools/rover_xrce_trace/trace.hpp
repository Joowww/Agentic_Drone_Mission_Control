#pragma once
// Opt-in native-agent diagnostic only. No message payloads or control APIs.
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <unistd.h>
#include <cerrno>
#include <pthread.h>
#include <signal.h>

namespace tfg_xrce_trace {
inline bool enabled() noexcept {
    const char* value = std::getenv("TFG_XRCE_TRACE");
    return value && std::strcmp(value, "1") == 0;
}
inline unsigned long long next_id() noexcept {
    static std::atomic<unsigned long long> counter{0};
    return ++counter;
}
inline std::string quote(const std::string& input) {
    if (input.size() > 256) return "null"; // no silent truncation/association
    std::ostringstream out; out << '"';
    for (unsigned char c : input) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32 || c >= 127) out << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << unsigned(c);
        else out << c;
    }
    out << '"'; return out.str();
}
inline std::string hex(const unsigned char* data, size_t n) {
    std::ostringstream out;
    for (size_t i=0; i<n; ++i) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(data[i]);
    return out.str();
}
inline std::string process_identity() {
    std::string boot, stat;
    std::ifstream b("/proc/sys/kernel/random/boot_id"); std::getline(b, boot);
    std::ifstream s("/proc/self/stat"); std::getline(s, stat);
    std::string ticks;
    const auto close = stat.rfind(')');
    if (close != std::string::npos) {
        std::istringstream fields(stat.substr(close+2));
        for (int field=3; field<=22; ++field) if (!(fields >> ticks)) { ticks.clear(); break; }
    }
    return "\"pid\":" + std::to_string(::getpid()) + ",\"boot_id\":" + (boot.empty()?"null":quote(boot)) +
        ",\"process_start_ticks\":" + (ticks.empty()?"null":quote(ticks));
}
inline ssize_t diagnostic_write(const char* data, size_t size) noexcept {
    // A disappearing log reader must not kill the agent with SIGPIPE. Preserve
    // the caller's thread mask; consume only a newly generated pending SIGPIPE.
    sigset_t pipe, previous, pending;
    sigemptyset(&pipe); sigaddset(&pipe, SIGPIPE);
    if (pthread_sigmask(SIG_BLOCK, &pipe, &previous) != 0) return -1;
    const bool was_pending = sigpending(&pending) != 0 || sigismember(&pending, SIGPIPE);
    const ssize_t result = ::write(STDERR_FILENO, data, size);
    if (result < 0 && errno == EPIPE && !was_pending) {
        const timespec zero{0,0};
        (void)sigtimedwait(&pipe, nullptr, &zero);
    }
    (void)pthread_sigmask(SIG_SETMASK, &previous, nullptr);
    return result;
}
inline void emit(const std::string& fields) noexcept {
    if (!enabled()) return;
    try {
        static std::mutex mutex;
        static unsigned count=0;
        static bool failed=false;
        std::lock_guard<std::mutex> lock(mutex);
        if (failed || count>=512) return;
        ++count;
        const auto wall=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
        const auto steady=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
        std::string selected = count==512 ? "\"event\":\"trace_limit\",\"incomplete\":true" : fields;
        std::string line="TFG_XRCE_TRACE {\"schema\":\"tfg.xrce-writer/1\"," + process_identity() +
            ",\"wall_unix_ns\":" + std::to_string(wall) + ",\"steady_ns\":" + std::to_string(steady) +
            ",\"sequence\":" + std::to_string(count) + "," + selected + "}\n";
        // One bounded write, no retry. Short/error output invalidates the trace,
        // never changes agent control flow or claims a complete association.
        if (line.size()>4096 || diagnostic_write(line.data(),line.size()) != static_cast<ssize_t>(line.size())) failed=true;
    } catch (...) { /* diagnostics must not change agent behavior */ }
}
// Per-packet lexical source, attached to the exact ProxyClient reference used by
// Processor. Never look up a generation later by ClientKey/session alone.
struct MessagePeer {
    unsigned long long instance=0; unsigned key=0, session=0, address=0, port=0; bool available=false;
};
struct PeerEndpoint { std::string address; unsigned port=0; bool available=false; };
struct PeerContext {
    unsigned long long instance=0; unsigned key=0, session=0; PeerEndpoint endpoint;
};
inline PeerContext*& current_peer() { static thread_local PeerContext* value=nullptr; return value; }
class PeerScope {
    PeerContext context_; PeerContext* previous_; bool bound_=false;
public:
    PeerScope() noexcept : previous_(current_peer()) {}
    void bind(unsigned long long instance,unsigned key,unsigned session,const PeerEndpoint& endpoint) noexcept {
        if (!enabled()) return;
        // Install an unavailable context even for unsupported transports so a
        // nested packet can never accidentally inherit its caller's endpoint.
        bound_=true; current_peer()=&context_;
        try { context_.instance=instance; context_.key=key; context_.session=session; context_.endpoint=endpoint; }
        catch (...) { context_.endpoint.available=false; }
    }
    ~PeerScope() noexcept { if (bound_) current_peer()=previous_; }
    PeerScope(const PeerScope&)=delete; PeerScope& operator=(const PeerScope&)=delete;
};
struct Context {
    unsigned long long client_instance, attempt;
    unsigned client_key, session_id, writer_id;
};
inline Context*& current() { static thread_local Context* value=nullptr; return value; }
inline std::string fields(const Context& c) {
    std::string result = "\"client_instance\":"+std::to_string(c.client_instance)+",\"attempt\":"+std::to_string(c.attempt)+
        ",\"client_key\":"+std::to_string(c.client_key)+",\"session_id\":"+std::to_string(c.session_id)+
        ",\"writer_id\":"+std::to_string(c.writer_id);
    const PeerContext* peer=current_peer();
    if (peer && peer->instance==c.client_instance && peer->key==c.client_key && peer->session==c.session_id
            && peer->endpoint.available && peer->endpoint.port>0 && peer->endpoint.port<=65535) {
        result += ",\"transport_peer\":{\"family\":\"IPv4\",\"address\":"+quote(peer->endpoint.address)+
            ",\"port\":"+std::to_string(peer->endpoint.port)+
            ",\"source\":\"Processor InputMessage metadata before session queue\","
            "\"generation_binding\":\"SAME_PROXYCLIENT_REFERENCE\"}";
    } else result += ",\"transport_peer\":null";
    return result;
}
class Scope {
    Context context_; Context* previous_; bool committed_=false;
public:
    Scope(unsigned long long instance,unsigned key,unsigned session,unsigned writer) noexcept
        : context_{instance,next_id(),key,session,writer},previous_(current()) { current()=&context_; }
    void commit(bool success) noexcept { committed_=success; }
    ~Scope() noexcept {
        try { if (enabled()) emit("\"event\":\"xrce_result\","+fields(context_)+",\"committed\":"+(committed_?"true":"false")); } catch (...) {}
        current()=previous_;
    }
};
// Called only in the successful native writer insertion branch, before existing
// middleware callbacks. Context is lexical and writer_id must match explicitly.
inline void writer(unsigned writer_id,const std::string& guid,const std::string& gid,
                   const std::string& rmw,const std::string& topic,const std::string& type,unsigned domain) noexcept {
    if (!enabled()) return;
    try {
        const Context* c=current();
        if (!c || c->writer_id!=writer_id) { emit("\"event\":\"unbound_writer\",\"incomplete\":true"); return; }
        emit("\"event\":\"dds_writer\","+fields(*c)+",\"native_guid\":"+quote(guid)+
             ",\"rmw_gid\":"+quote(gid)+",\"rmw_identifier\":"+quote(rmw)+",\"topic\":"+quote(topic)+
             ",\"type\":"+quote(type)+",\"domain\":"+std::to_string(domain));
    } catch (...) { emit("\"event\":\"trace_error\",\"incomplete\":true"); }
}
}
