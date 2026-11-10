#ifndef TFG_ROVER_PASSIVE_COLLECTOR_CORE_HPP
#define TFG_ROVER_PASSIVE_COLLECTOR_CORE_HPP
#include "observer.hpp"
#include <cmath>
#include <iomanip>
#include <limits>
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

inline void candidates_json(std::ostream & out, const std::vector<Candidate> & candidates) {
  bool first = true;
  for (const auto & candidate : candidates) {
    if (!first) out << ',';
    first = false;
    out << "{\"endpoint_gid\":" << json_quote(hex_gid(candidate.endpoint_gid))
        << ",\"node_name\":" << json_quote(candidate.node_name)
        << ",\"node_namespace\":" << json_quote(candidate.node_namespace)
        << ",\"topic_type\":" << (candidate.topic_type ? json_quote(*candidate.topic_type) : "null")
        << ",\"offered_qos\":";
    if (candidate.offered_qos) {
      const auto & q = *candidate.offered_qos;
      out << "{\"source\":\"TopicEndpointInfo.qos_profile.get_rmw_qos_profile\","
          << "\"reliability_rmw\":" << q.reliability << ",\"durability_rmw\":" << q.durability
          << ",\"history_rmw\":" << q.history << ",\"depth\":" << q.depth
          << ",\"other_policies\":\"NOT_CAPTURED\"}";
    } else out << "null";
    out << '}';
  }
 }
inline std::string serialize_discovery(const Discovery & graph) {
  std::ostringstream out;
  out << "{\"event\":\"discovery\"," << blocked_fields
      << ",\"topic\":" << json_quote(graph.topic)
      << ",\"source\":\"Node.get_publishers_info_by_topic\",\"state\":" << json_quote(graph.state)
      << ",\"receipt\":";
  if (graph.receipt) receipt_json(out, *graph.receipt); else out << "null";
  out << ",\"candidates\":[";
  candidates_json(out, graph.candidates);
  out << "]}";
  return out.str();
}
// Schema /3 opt-in: every nav_msgs/Odometry numeric field as received. Finite values use
// round-trip precision; NaN/Infinity become null AND are listed in "nonfinite" by path,
// never zero. Field names come from the message type; units/frames are NOT validated.
class OdometryFieldsJson {
public:
  explicit OdometryFieldsJson(std::ostream & out) : out_(out) {}
  void number(const char * path, double value) {
    if (std::isfinite(value)) {
      std::ostringstream text;
      text.imbue(std::locale::classic());
      text << std::setprecision(std::numeric_limits<double>::max_digits10) << value;
      out_ << text.str();
    } else {
      out_ << "null";
      nonfinite_.emplace_back(path, std::isnan(value) ? "NaN" : value > 0 ? "Infinity" : "-Infinity");
    }
  }
  template<class Vector>
  void xyz(const char * prefix, const Vector & v) {
    const std::string p(prefix);
    out_ << "{\"x\":"; number((p + ".x").c_str(), v.x);
    out_ << ",\"y\":"; number((p + ".y").c_str(), v.y);
    out_ << ",\"z\":"; number((p + ".z").c_str(), v.z);
    out_ << '}';
  }
  template<class Covariance>
  void covariance(const char * prefix, const Covariance & values) {
    out_ << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
      if (i) out_ << ',';
      number((std::string(prefix) + "[" + std::to_string(i) + "]").c_str(), values[i]);
    }
    out_ << ']';
  }
  bool any_nonfinite() const { return !nonfinite_.empty(); }
  void finish() {
    out_ << ",\"nonfinite\":{";
    for (std::size_t i = 0; i < nonfinite_.size(); ++i)
      out_ << (i ? "," : "") << json_quote(nonfinite_[i].first) << ':' << json_quote(nonfinite_[i].second);
    out_ << '}';
  }
private:
  std::ostream & out_;
  std::vector<std::pair<std::string, std::string>> nonfinite_;
};
template<class Message>
bool odometry_fields_json(std::ostream & out, const Message & message) {
  OdometryFieldsJson json(out);
  const auto & pose = message.pose.pose;
  const auto & twist = message.twist.twist;
  out << ",\"odometry_fields\":{\"source\":\"nav_msgs/msg/Odometry fields as received; units and frames NOT validated\""
      << ",\"validity_flag\":\"NOT_PROVIDED_BY_MESSAGE\",\"pose\":{\"position\":";
  json.xyz("pose.position", pose.position);
  out << ",\"orientation\":{\"x\":"; json.number("pose.orientation.x", pose.orientation.x);
  out << ",\"y\":"; json.number("pose.orientation.y", pose.orientation.y);
  out << ",\"z\":"; json.number("pose.orientation.z", pose.orientation.z);
  out << ",\"w\":"; json.number("pose.orientation.w", pose.orientation.w);
  out << "},\"covariance\":"; json.covariance("pose.covariance", message.pose.covariance);
  out << "},\"twist\":{\"linear\":"; json.xyz("twist.linear", twist.linear);
  out << ",\"angular\":"; json.xyz("twist.angular", twist.angular);
  out << ",\"covariance\":"; json.covariance("twist.covariance", message.twist.covariance);
  out << '}';
  json.finish();
  out << '}';
  return json.any_nonfinite();
}
struct Serialized { std::string json; bool incomplete; };
inline Serialized serialize_sample(const Sample & sample, bool odometry_fields = false) {
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
      if (odometry_fields && odometry_fields_json(out, message)) incomplete = true;  // non-finite: not usable
    }
  }, sample.message);
  out << ",\"graph\":{\"state\":" << json_quote(sample.graph_state)
      << ",\"source\":" << json_quote(sample.graph_source) << ",\"receipt\":";
  if (sample.graph_received) receipt_json(out, *sample.graph_received); else out << "null";
  out << ",\"candidates\":[";
  candidates_json(out, sample.graph_candidates);
  out << "]},\"incomplete\":" << (incomplete ? "true" : "false") << '}';
  return {out.str(), incomplete};
}

struct Limits {
  std::size_t samples;
  double duration_s;
  bool reserve_streams = false;
  bool odometry_fields = false;  // opt-in schema /3; default output unchanged (/1 or /2)
  void validate() const {
    if (reserve_streams && samples > 20)
      throw std::invalid_argument("Reserved-stream diagnostic stores at most 20 samples");
    if (samples < 2 || samples > 10000 || !std::isfinite(duration_s) || duration_s <= 0 || duration_s > 300)
      throw std::invalid_argument("Explicit samples 2..10000 and finite duration (0,300] required");
  }
};
// One wall budget covers setup, collection and finalization. Reserve only time
// *inside* that budget for normal durable closure; the watchdog remains the cap.
struct CaptureDeadlines { double hard, collection; };
inline CaptureDeadlines capture_deadlines(double started, Limits limits) {
  limits.validate();
  if (!std::isfinite(started)) throw std::invalid_argument("Invalid steady clock");
  const double hard = started + limits.duration_s;
  return {hard, hard - std::min(.05, limits.duration_s * .1)};
}

struct CaptureResult {
  std::size_t samples = 0, status_samples = 0, odometry_samples = 0, incomplete = 0;
  std::size_t omitted_status_quota = 0, omitted_odometry_quota = 0;
  bool capture_complete = false;
  std::string termination;
};

// Writer must append a complete line, flush and fsync or throw. No retry on error.
// Poll is a bounded, single-callback poll. Clock uses process wall/steady time.
// Does not construct a node, service, publisher or transport.
template<class Writer, class Clock, class Poll>
CaptureResult collect(Writer & writer, Limits limits, Clock now, Poll poll,
                      std::optional<double> collection_deadline = std::nullopt,
                      std::function<void()> before_footer = {}) {
  limits.validate();
  CaptureResult result;
  const auto deadline = collection_deadline ? *collection_deadline : now() + limits.duration_s;
  if (!std::isfinite(deadline)) throw std::invalid_argument("Invalid collection deadline");
  writer.append("{\"event\":\"start\"," + std::string(blocked_fields) +
                ",\"schema\":" + json_quote(limits.odometry_fields ? "tfg.rover.passive-capture/3" :
                                              limits.reserve_streams ? "tfg.rover.passive-capture/2" : "tfg.rover.passive-capture/1") +
                ",\"sampling_policy\":" + json_quote(limits.reserve_streams ? "RESERVE_BOTH_STREAMS" : "GLOBAL_CAP") +
                ",\"string_encoding\":\"byte_escape_u00\",\"max_samples\":" +
                std::to_string(limits.samples) + ",\"duration_s\":" + std::to_string(limits.duration_s) + "}");
  const auto receive = [&](const Sample & sample) {
    if (result.samples >= limits.samples || now() >= deadline) return;
    // Reserve one slot for the other stream, symmetrically. Omitted samples
    // never enter the journal or stored-sample count; counters are explicit.
    if (limits.reserve_streams && sample.topic == "/rover1/odometry" &&
        result.status_samples == 0 && result.odometry_samples >= limits.samples - 1) {
      ++result.omitted_odometry_quota; return;
    }
    if (limits.reserve_streams && sample.topic == "/ap/v3/status" &&
        result.odometry_samples == 0 && result.status_samples >= limits.samples - 1) {
      ++result.omitted_status_quota; return;
    }
    const auto serialized = serialize_sample(sample, limits.odometry_fields);
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
  if (before_footer) before_footer(); // still inside the original hard deadline
  writer.append("{\"event\":\"end\"," + std::string(blocked_fields) +
                ",\"termination\":" + json_quote(result.termination) + ",\"samples\":" +
                std::to_string(result.samples) +
                ",\"omitted_status_quota\":" + std::to_string(result.omitted_status_quota) +
                ",\"omitted_odometry_quota\":" + std::to_string(result.omitted_odometry_quota) +
                ",\"incomplete_samples\":" + std::to_string(result.incomplete) +
                ",\"data_present_both_streams\":" + (result.status_samples && result.odometry_samples ? "true" : "false") +
                ",\"capture_complete\":null}");
  writer.finish();  // must confirm final fsync/close BEFORE reporting completeness
  result.capture_complete = complete_data;
  return result;
}
}  // namespace tfg::rover_passive
#endif
