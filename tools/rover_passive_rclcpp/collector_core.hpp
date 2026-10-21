#ifndef TFG_ROVER_PASSIVE_COLLECTOR_CORE_HPP
#define TFG_ROVER_PASSIVE_COLLECTOR_CORE_HPP
#include "observer.hpp"
#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace tfg::rover_passive {
inline std::string json_quote(std::string_view text) {
  std::ostringstream out;
  out << '"';
  for (unsigned char c : text) {
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (c < 0x20 || c >= 0x7f) {
      // Preserve exact string bytes reversibly, including invalid UTF-8.
      // Consumers must decode these byte escapes before interpreting UTF-8.
      out << "\\u00" << std::hex << std::setw(2) << std::setfill('0') << unsigned(c) << std::dec;
    } else out << c;
  }
  out << '"';
  return out.str();
}
inline std::string hex_gid(const GidBytes & gid) {
  std::ostringstream out;
  for (auto byte : gid) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(byte);
  return out.str();
}
inline void receipt_json(std::ostream & out, const Receipt & receipt) {
  out << "{\"system_unix_ns\":" << receipt.system_unix_ns
      << ",\"steady_ns\":" << receipt.steady_ns << '}';
}
inline constexpr const char * blocked_fields =
  "\"status\":\"BLOCKED\",\"source_association_verified\":false,\"movement_authorized\":false";

struct Serialized { std::string json; bool incomplete; };
inline Serialized serialize_sample(const Sample & sample) {
  bool incomplete = sample.message_gid_state != "OBSERVED_NOT_ACCREDITED" ||
                    !sample.message_publisher_gid || !sample.rmw_implementation_identifier ||
                    sample.graph_state != "OBSERVED" || !sample.graph_received;
  std::ostringstream out;
  out << "{\"event\":\"sample\"," << blocked_fields
      << ",\"topic\":" << json_quote(sample.topic) << ",\"message_type\":" << json_quote(sample.message_type)
      << ",\"receipt\":";
  receipt_json(out, sample.receipt);
  out << ",\"message_gid_state\":" << json_quote(sample.message_gid_state)
      << ",\"message_gid_source\":" << json_quote(sample.message_gid_source)
      << ",\"message_publisher_gid\":"
      << (sample.message_publisher_gid ? json_quote(hex_gid(*sample.message_publisher_gid)) : "null")
      << ",\"rmw_implementation_identifier\":"
      << (sample.rmw_implementation_identifier ? json_quote(*sample.rmw_implementation_identifier) : "null")
      << ",\"from_intra_process\":" << (sample.from_intra_process ? "true" : "false");
  std::visit([&](const auto & message) {
    using Message = std::decay_t<decltype(message)>;
    const auto & stamp = message.header.stamp;
    if (stamp.nanosec >= 1000000000u) incomplete = true;
    out << ",\"header\":{\"stamp\":{\"sec\":" << stamp.sec << ",\"nanosec\":" << stamp.nanosec
        << "},\"frame_id\":" << json_quote(message.header.frame_id) << '}';
    if constexpr (std::is_same_v<Message, Status>) {
      if (sample.topic != "/ap/v3/status" || sample.message_type != "ardupilot_msgs/msg/Status" ||
          message.vehicle_type != 1) incomplete = true;
      out << ",\"status_fields\":{\"vehicle_type\":" << unsigned(message.vehicle_type)
          << ",\"armed\":" << (message.armed ? "true" : "false")
          << ",\"flying\":" << (message.flying ? "true" : "false") << '}';
    } else {
      if (sample.topic != "/rover1/odometry" || sample.message_type != "nav_msgs/msg/Odometry" ||
          message.child_frame_id.empty() || message.header.frame_id.empty()) incomplete = true;
      out << ",\"child_frame_id\":" << json_quote(message.child_frame_id);
    }
  }, sample.message);
  out << ",\"graph\":{\"state\":" << json_quote(sample.graph_state)
      << ",\"source\":" << json_quote(sample.graph_source) << ",\"receipt\":";
  if (sample.graph_received) receipt_json(out, *sample.graph_received); else out << "null";
  out << ",\"candidates\":[";
  bool first = true;
  for (const auto & candidate : sample.graph_candidates) {
    if (!first) out << ',';
    first = false;
    out << "{\"endpoint_gid\":" << json_quote(hex_gid(candidate.endpoint_gid))
        << ",\"node_name\":" << json_quote(candidate.node_name)
        << ",\"node_namespace\":" << json_quote(candidate.node_namespace) << '}';
  }
  out << "]},\"incomplete\":" << (incomplete ? "true" : "false") << '}';
  return {out.str(), incomplete};
}

struct Limits {
  std::size_t samples;
  double duration_s;
  void validate() const {
    if (samples < 2 || samples > 10000 || !std::isfinite(duration_s) || duration_s <= 0 || duration_s > 300)
      throw std::invalid_argument("Explicit samples 2..10000 and finite duration (0,300] required");
  }
};
struct CaptureResult {
  std::size_t samples = 0, status_samples = 0, odometry_samples = 0, incomplete = 0;
  bool capture_complete = false;
  std::string termination;
};

// Writer must append a complete line, flush and fsync or throw. No retry on error.
// Poll is a bounded, single-callback poll. Clock uses process wall/steady time.
// Does not construct a node, service, publisher or transport.
template<class Writer, class Clock, class Poll>
CaptureResult collect(Writer & writer, Limits limits, Clock now, Poll poll) {
  limits.validate();
  CaptureResult result;
  const auto deadline = now() + limits.duration_s;
  writer.append("{\"event\":\"start\"," + std::string(blocked_fields) +
                ",\"schema\":\"tfg.rover.passive-capture/1\",\"string_encoding\":\"byte_escape_u00\",\"max_samples\":" +
                std::to_string(limits.samples) + ",\"duration_s\":" + std::to_string(limits.duration_s) + "}");
  const auto receive = [&](const Sample & sample) {
    if (result.samples >= limits.samples || now() >= deadline) return;
    const auto serialized = serialize_sample(sample);
    writer.append(serialized.json);  // only count a sample AFTER durable append
    ++result.samples;
    if (sample.topic == "/ap/v3/status") ++result.status_samples;
    if (sample.topic == "/rover1/odometry") ++result.odometry_samples;
    if (serialized.incomplete) ++result.incomplete;
  };
  while (result.samples < limits.samples && now() < deadline) {
    if (!poll(receive, std::min(.05, std::max(0., deadline-now())))) {
      result.termination = "INTERRUPTED";
      break;
    }
  }
  if (result.termination.empty())
    result.termination = result.samples == limits.samples ? "SAMPLE_LIMIT" : "DURATION_LIMIT";
  // This is data completeness only. It NEVER credits source/model identity.
  const bool complete_data = result.termination != "INTERRUPTED" && result.status_samples > 0 &&
                             result.odometry_samples > 0 && result.incomplete == 0;
  writer.append("{\"event\":\"end\"," + std::string(blocked_fields) +
                ",\"termination\":" + json_quote(result.termination) + ",\"samples\":" +
                std::to_string(result.samples) + ",\"incomplete_samples\":" + std::to_string(result.incomplete) +
                ",\"data_present_both_streams\":" + (result.status_samples && result.odometry_samples ? "true" : "false") +
                ",\"capture_complete\":null}");
  writer.finish();  // must confirm final fsync/close BEFORE reporting completeness
  result.capture_complete = complete_data;
  return result;
}
}  // namespace tfg::rover_passive
#endif
