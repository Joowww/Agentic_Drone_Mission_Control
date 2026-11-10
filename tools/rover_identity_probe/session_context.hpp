#pragma once
// Shared existing protected session reader; no process or ROS creation.
#include <chrono>
#include <fcntl.h>
#include <unistd.h>
#include <fstream>
#include <sstream>
#include <string>
#include <stdexcept>
#include <yaml-cpp/yaml.h>
namespace tfg_identity_probe {
struct DiagnosticExhausted : std::runtime_error {
  DiagnosticExhausted():std::runtime_error("Diagnostic cap reached"){}
};
static std::string read(const std::string &path) {
  std::ifstream f(path);
  if (!f)
    throw std::runtime_error("Context read failed");
  std::string s((std::istreambuf_iterator<char>(f)), {});
  if (s.size() > 65536)
    throw std::runtime_error("Context too large");
  return s;
}
static std::string ticks(int pid) {
  auto s = read("/proc/" + std::to_string(pid) + "/stat");
  auto e = s.rfind(')');
  if (e == s.npos)
    throw std::runtime_error("Bad process identity");
  std::istringstream i(s.substr(e + 2));
  std::string v;
  for (int n = 3; n <= 22; ++n)
    if (!(i >> v) || (n == 3 && v == "Z"))
      throw std::runtime_error("Short process identity");
  return v;
}
struct Session {
  std::string id, prefix, boot, selection;
  int root_pid;
  std::string root_ticks;
  explicit Session(std::string value) : id(std::move(value)) {
    if (id.size() != 36 ||
        id.find_first_not_of("0123456789abcdef-") != std::string::npos)
      throw std::runtime_error("Canonical lifecycle id required");
    auto d = YAML::Load(read("/tmp/tfg_demo.diagnostic.json"));
    if (d["lifecycle_id"].as<std::string>() != id)
      throw std::runtime_error("Wrong diagnostic session");
    prefix = "/tmp/tfg_diagnostic_agents/" + id;
    if (d["prefix"].as<std::string>() != prefix)
      throw std::runtime_error("Wrong overlay");
    selection = read(prefix + "/selection.json");
    auto launch = YAML::Load(read(prefix + "/launch.json"));
    auto p = launch["process"];
    root_pid = p["pid"].as<int>();
    root_ticks = p["start_ticks"].as<std::string>();
    boot = p["boot_id"].as<std::string>();
    check();
  }
  void check() const {
    auto b = read("/proc/sys/kernel/random/boot_id");
    while (!b.empty() && isspace(b.back()))
      b.pop_back();
    if (b != boot || ticks(root_pid) != root_ticks ||
        read(prefix + "/selection.json") != selection)
      throw std::runtime_error("Session execution/selection changed");
    auto d = YAML::Load(read("/tmp/tfg_demo.diagnostic.json"));
    if (d["lifecycle_id"].as<std::string>() != id)
      throw std::runtime_error("Session descriptor changed");
    auto m = YAML::Load(read(prefix + "/capture/monitor.json"));
    const double now = std::chrono::duration<double>(
                           std::chrono::steady_clock::now().time_since_epoch())
                           .count();
    const double observed = m["observation_monotonic"].as<double>();
    if (now < observed || now - observed > 5)
      throw std::runtime_error("Stale monitor observation");
    if (YAML::Load(selection)["descriptor"]["manifest"]["schema"]
                .as<std::string>() == "tfg.xrce-agent-selection/3" &&
        (!m["model_source"] ||
         !m["model_source"]["verified_overlay_library"].as<bool>()))
      throw std::runtime_error("Model source library not verified");
    if (!m["identity_bridge"] ||
        !m["identity_bridge"]["verified_overlay_library"].as<bool>())
      throw std::runtime_error("Bridge source not verified");
    if(m["diagnostic_cap_reached"] && m["diagnostic_cap_reached"].as<bool>()) {
      if(m["lifecycle_id"].as<std::string>()!=id)
        throw std::runtime_error("Monitor owner differs");
      throw DiagnosticExhausted();
    }
    if (m["phase"].as<std::string>() != "OBSERVING" || m["errors"].size() != 0)
      throw std::runtime_error("Monitor unavailable");
  }
};
inline void trigger_model(const std::string& session_id,const std::string& model_request) {

    int fd = ::open(model_request.c_str(),
                    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0)
      throw std::runtime_error("Model trigger exclusive creation failed");
    try {
      auto data = session_id + "\n";
      if (::write(fd, data.data(), data.size()) !=
              static_cast<ssize_t>(data.size()) ||
          ::fsync(fd))
        throw std::runtime_error("Model trigger write uncertain");
      const int closing = fd;
      fd = -1;
      if (::close(closing))
        throw std::runtime_error("Model trigger close uncertain");
    } catch (...) {
      if (fd >= 0)
        ::close(fd);
      throw;
    }
  
}
}
