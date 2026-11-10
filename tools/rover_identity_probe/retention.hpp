#pragma once
// Pure storage quota, no ROS, identity authority or movement policy.
#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
namespace tfg_identity_probe {
struct Retention {
  std::size_t samples = 0;
  bool open = true;
  std::map<std::string, std::size_t> count, omitted, before_status,
      omitted_by_spacing, clock_rewinds;
  std::map<std::string, std::int64_t> last_stamp;
  bool retain_at(const std::string &topic, std::size_t quota, std::int64_t ns) {
    auto p = last_stamp.find(topic);
    if (p != last_stamp.end() && ns < p->second) {
      ++clock_rewinds[topic];
      return false;
    }
    if (p != last_stamp.end() && ns - p->second < 500000000) {
      ++omitted_by_spacing[topic];
      return false;
    }
    if (!retain(topic, quota))
      return false;
    last_stamp[topic] = ns;
    return true;
  }
  bool retain(const std::string &topic, std::size_t quota) {
    if (!open)
      return false;
    if (topic != "/ap/v3/status" &&
        count.find("/ap/v3/status") == count.end()) {
      ++before_status[topic];
      return false;
    }
    if (samples >= 20 || count[topic] >= quota) {
      ++omitted[topic];
      return false;
    }
    ++samples;
    ++count[topic];
    return true;
  }
};
} // namespace tfg_identity_probe
