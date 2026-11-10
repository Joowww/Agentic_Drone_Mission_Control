#ifndef TFG_ROVER_PASSIVE_OBSERVER_HPP
#define TFG_ROVER_PASSIVE_OBSERVER_HPP

// Passive prototype only. No executable, node creation, spin, services or controls.
// Contract: installed Humble rclcpp 16.0.19 MessageInfo and rmw 6.1.3 headers.
#include <ardupilot_msgs/msg/status.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/message_info.hpp>
#include <rmw/types.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <stdexcept>
#include <utility>
#include <variant>
#include <vector>

namespace tfg::rover_passive {
using Status = ardupilot_msgs::msg::Status;
using Odometry = nav_msgs::msg::Odometry;
using GidBytes = std::array<std::uint8_t, RMW_GID_STORAGE_SIZE>;

struct Receipt {
  std::int64_t system_unix_ns;
  std::int64_t steady_ns;  // process-local; not ROS/simulation time
};
inline Receipt receive_time() {
  return {std::chrono::duration_cast<std::chrono::nanoseconds>(
              std::chrono::system_clock::now().time_since_epoch()).count(),
          std::chrono::duration_cast<std::chrono::nanoseconds>(
              std::chrono::steady_clock::now().time_since_epoch()).count()};
}
struct OfferedQos {
  int reliability, durability, history;
  std::size_t depth;
};
struct Candidate {
  GidBytes endpoint_gid;
  std::string node_name;
  std::string node_namespace;
  std::optional<std::string> topic_type = std::nullopt;
  std::optional<OfferedQos> offered_qos = std::nullopt;
};
struct Discovery {
  std::string topic;
  std::string state = "UNKNOWN";
  std::optional<Receipt> receipt;
  std::vector<Candidate> candidates;
};
struct Sample {
  static constexpr const char * status = "BLOCKED";
  static constexpr bool source_association_verified = false;
  static constexpr bool movement_authorized = false;
  std::string topic;
  std::string message_type;
  Receipt receipt;
  // Exact typed copy retains header stamp, frame_id and original fields/units.
  std::variant<Status, Odometry> message;
  std::optional<GidBytes> message_publisher_gid;
  std::optional<std::string> rmw_implementation_identifier;
  bool from_intra_process = false;
  std::string message_gid_state = "UNKNOWN";
  std::string message_gid_source = "rclcpp callback MessageInfo.rmw_message_info.publisher_gid";
  std::optional<std::string> attributed_publisher_identity;  // always unavailable here
  std::string graph_state = "UNKNOWN";
  std::string graph_source = "Node.get_publishers_info_by_topic";
  std::optional<Receipt> graph_received;
  std::vector<Candidate> graph_candidates;  // NEVER used to populate the sample GID
};

class Observer {
public:
  using Sink = std::function<void(const Sample &)>;
  using Clock = std::function<Receipt()>;
  using Diagnostic = std::function<void(const char*,const Sample*)>;
  // Caller owns the existing node, its context, executor and lifetime. The sink
  // is supplied explicitly; this component does not create files or authority.
  Observer(rclcpp::Node & node, Sink sink, Clock clock = receive_time, Diagnostic diagnostic = {})
  : node_(node), sink_(std::move(sink)), clock_(std::move(clock)),diagnostic_(std::move(diagnostic)) {
    auto qos = rclcpp::QoS(rclcpp::KeepLast(5)).best_effort().durability_volatile();
    notify("status_subscription_requested",nullptr);
    status_ = node_.create_subscription<Status>("/ap/v3/status", qos,
      [this](std::shared_ptr<const Status> msg, const rclcpp::MessageInfo & info) {
        capture("/ap/v3/status", "ardupilot_msgs/msg/Status", std::move(msg), info);
      });
    notify("status_subscription_created",nullptr);
    odometry_ = node_.create_subscription<Odometry>("/rover1/odometry", qos,
      [this](std::shared_ptr<const Odometry> msg, const rclcpp::MessageInfo & info) {
        capture("/rover1/odometry", "nav_msgs/msg/Odometry", std::move(msg), info);
      });
  }
  std::size_t status_matches() const {return status_->get_publisher_count();}
  bool diagnostic_complete() const noexcept {return diagnostic_complete_;}
  // Public graph discovery only. Even no-message topics can be inventoried.
  Discovery discover(const std::string & topic) {
    if (topic != "/ap/v3/status" && topic != "/rover1/odometry")
      throw std::invalid_argument("Unexpected passive discovery topic");
    Discovery result; result.topic = topic;
    try {
      const auto endpoints = node_.get_publishers_info_by_topic(topic);
      result.receipt = clock_();
      for (const auto & endpoint : endpoints) {
        Candidate candidate{endpoint.endpoint_gid(), endpoint.node_name(), endpoint.node_namespace()};
        candidate.topic_type = endpoint.topic_type();
        const auto qos = endpoint.qos_profile().get_rmw_qos_profile();
        candidate.offered_qos = OfferedQos{static_cast<int>(qos.reliability),
          static_cast<int>(qos.durability), static_cast<int>(qos.history), qos.depth};
        result.candidates.push_back(std::move(candidate));
      }
      result.state = "OBSERVED";
    } catch (...) {} // unknown discovery never invents sample attribution
    return result;
  }
  Observer(const Observer &) = delete;
  Observer & operator=(const Observer &) = delete;
  Observer(Observer &&) = delete;
  Observer & operator=(Observer &&) = delete;

private:
  void notify(const char* stage,const Sample* sample) noexcept {
    if(!diagnostic_||(sample&&sample->topic!="/ap/v3/status"))return;
    try {diagnostic_(stage,sample);}catch(...) {diagnostic_complete_=false;}
  }
  template<typename Message>
  void capture(const char * topic, const char * type, std::shared_ptr<const Message> msg,
               const rclcpp::MessageInfo & info) {
    if (!msg) return;  // absent is not a fabricated zero sample
    Sample sample;
    sample.topic = topic;
    sample.message_type = type;
    sample.receipt = clock_();
    notify("status_callback_enter",&sample);
    sample.message = *msg;
    const auto & metadata = info.get_rmw_message_info();
    sample.from_intra_process = metadata.from_intra_process;
    GidBytes bytes;
    std::copy_n(metadata.publisher_gid.data, bytes.size(), bytes.begin());
    sample.message_publisher_gid = bytes;  // raw bytes from THIS callback, including invalid values
    if (metadata.publisher_gid.implementation_identifier &&
        metadata.publisher_gid.implementation_identifier[0] != '\0') {
      sample.rmw_implementation_identifier = metadata.publisher_gid.implementation_identifier;
    }
    const bool nonzero = std::any_of(bytes.begin(), bytes.end(), [](auto b) { return b != 0; });
    if (!sample.from_intra_process && nonzero && sample.rmw_implementation_identifier) {
      sample.message_gid_state = "OBSERVED_NOT_ACCREDITED";
    }
    notify("status_graph_enter",&sample);
    const auto graph = discover(topic);
    notify("status_graph_exit",&sample);
    sample.graph_received = graph.receipt;
    sample.graph_candidates = graph.candidates;
    sample.graph_state = graph.state;
    sink_(sample);
  }
  rclcpp::Node & node_;
  Sink sink_;
  Clock clock_;
  Diagnostic diagnostic_;
  bool diagnostic_complete_=true;
  rclcpp::Subscription<Status>::SharedPtr status_;
  rclcpp::Subscription<Odometry>::SharedPtr odometry_;
};
}  // namespace tfg::rover_passive
#endif
