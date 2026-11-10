// Standalone future passive reader. No publishers or control service clients.
#include "../rover_passive_rclcpp/collector_core.hpp"
#include "../rover_passive_rclcpp/private_journal.hpp"
#include "retention.hpp"
#include "session_context.hpp"
#include <fstream>
#include <geographic_msgs/msg/geo_pose_stamped.hpp>
#include <google/protobuf/util/json_util.h>
#include <gz/msgs/empty.pb.h>
#include <gz/msgs/pose_v.pb.h>
#include <gz/msgs/scene.pb.h>
#include <gz/transport/Node.hh>
#include <iomanip>
#include <map>
#include <mutex>
#include <rcl_interfaces/srv/get_parameters.hpp>
#include <sensor_msgs/msg/nav_sat_fix.hpp>
#include <sstream>
#include <thread>
#include <unistd.h>
#include <yaml-cpp/yaml.h>
using namespace tfg::rover_passive;
using Params = rcl_interfaces::srv::GetParameters;
static std::string q(const std::string &s) { return json_quote(s); }
static std::string number(double x) {
  if (!std::isfinite(x))
    return "null";
  std::ostringstream o;
  o << std::setprecision(17) << x;
  return o.str();
}
template <class Array> static std::string numbers(const Array &a) {
  std::string s = "[";
  for (auto v : a) {
    if (s.size() > 1)
      s += ",";
    s += number(v);
  }
  return s + "]";
}
template <class Q> static std::string quat(const Q &v) {
  return "[" + number(v.x) + "," + number(v.y) + "," + number(v.z) + "," +
         number(v.w) + "]";
}
template <class P> static std::string xyz(const P &v) {
  return "[" + number(v.x) + "," + number(v.y) + "," + number(v.z) + "]";
}
static std::string hex(const unsigned char *a, size_t n) {
  std::ostringstream o;
  o << std::hex << std::setfill('0');
  for (size_t i = 0; i < n; ++i)
    o << std::setw(2) << unsigned(a[i]);
  return o.str();
}
using tfg_identity_probe::Session;
using tfg_identity_probe::read;
using tfg_identity_probe::ticks;
struct Writer : tfg_identity_probe::Retention {
  PrivateJournal out;
  std::string session_id, model_request;
  void request_model() { tfg_identity_probe::trigger_model(session_id,model_request); }
  std::mutex mutex;
  size_t bytes = 0;
  std::exception_ptr failure;
  explicit Writer(const std::string &path) : out(path) {}
  void line(const std::string &value) {
    if (value.size() > 256 * 1024 || bytes + value.size() + 1 > 512 * 1024)
      throw std::runtime_error("Reader journal budget exhausted");
    out.append(value);
    bytes += value.size() + 1;
  }
  void emit(std::string fields) {
    auto t = receive_time();
    line("{\"schema\":\"tfg.rover-passive-validation/"
         "1\",\"status\":\"BLOCKED\",\"movement_authorized\":false,\"receipt_"
         "wall_ns\":" +
         std::to_string(t.system_unix_ns) + ",\"receipt_steady_ns\":" +
         std::to_string(t.steady_ns) + "," + fields + "}");
  }
};
static std::string metadata(const rclcpp::MessageInfo &info) {
  const auto &m = info.get_rmw_message_info();
  return "\"message_gid\":" +
         q(hex(m.publisher_gid.data, RMW_GID_STORAGE_SIZE)) + ",\"rmw\":" +
         q(m.publisher_gid.implementation_identifier
               ? m.publisher_gid.implementation_identifier
               : "") +
         ",\"from_intra_process\":" +
         (m.from_intra_process ? "true" : "false") +
         ",\"source_timestamp\":" + std::to_string(m.source_timestamp) +
         ",\"received_timestamp\":" + std::to_string(m.received_timestamp);
}
template <class Msg, class Body>
static rclcpp::SubscriptionBase::SharedPtr
subscribe(rclcpp::Node &node, Writer &w, const std::string &topic, size_t quota,
          Body body) {
  auto qos =
      rclcpp::QoS(rclcpp::KeepLast(5)).best_effort().durability_volatile();
  return node.create_subscription<Msg>(
      topic, qos,
      [&w, topic, quota, body](std::shared_ptr<const Msg> m,
                               const rclcpp::MessageInfo &info) {
        const auto callback_received = receive_time();
        std::lock_guard<std::mutex> l(w.mutex);
        try {
          if (w.retain_at(topic, quota,
                          static_cast<std::int64_t>(m->header.stamp.sec) *
                                  1000000000 +
                              m->header.stamp.nanosec)) {
            if (topic == "/ap/v3/status")
              w.request_model();
            w.emit("\"kind\":\"sample\",\"topic\":" + q(topic) + "," +
                   metadata(info) + ",\"callback_receipt_steady_ns\":" +
                   std::to_string(callback_received.steady_ns) +
                   ",\"callback_receipt_wall_ns\":" +
                   std::to_string(callback_received.system_unix_ns) + "," +
                   body(*m));
          }
        } catch (...) {
          w.failure = std::current_exception();
          w.open = false;
        }
      });
}
static std::string header(const std_msgs::msg::Header &h) {
  return "\"stamp_sec\":" + std::to_string(h.stamp.sec) +
         ",\"stamp_nanosec\":" + std::to_string(h.stamp.nanosec) +
         ",\"frame_id\":" + q(h.frame_id);
}
struct Query {
  std::string endpoint;
  std::vector<std::string> names;
  rclcpp::Client<Params>::SharedPtr client;
  bool sent = false, done = false;
  int64_t request_id = 0;
  std::chrono::steady_clock::time_point deadline;
  Query(rclcpp::Node &n, const rclcpp::CallbackGroup::SharedPtr &g,
        std::string e, std::vector<std::string> keys)
      : endpoint(std::move(e)), names(std::move(keys)) {
    client =
        n.create_client<Params>(endpoint, rmw_qos_profile_services_default, g);
  }
  void poll(rclcpp::Node &node, Writer &w) {
    if (done)
      return;
    if (!sent) {
      auto services = node.get_service_names_and_types();
      auto it = services.find(endpoint);
      if (it == services.end() ||
          it->second !=
              std::vector<std::string>{"rcl_interfaces/srv/GetParameters"})
        return;
      if (!client->service_is_ready())
        return;
      auto request = std::make_shared<Params::Request>();
      request->names = names;
      request_id = client->async_send_request(request).request_id;
      sent = true;
      deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
      return;
    }
    Params::Response response;
    rmw_request_id_t info{};
    if (client->take_response(response, info)) {
      done = true;
      client->remove_pending_request(request_id);
      std::string fields =
          "\"kind\":\"parameter_reply\",\"endpoint\":" + q(endpoint) +
          ",\"request_writer_guid\":" +
          q(hex(reinterpret_cast<const unsigned char *>(info.writer_guid),
                16)) +
          ",\"request_sequence\":" + std::to_string(info.sequence_number) +
          ",\"values\":{";
      if (response.values.size() != names.size())
        throw std::runtime_error("Parameter response length mismatch");
      for (size_t i = 0; i < names.size(); ++i) {
        if (i)
          fields += ",";
        fields += q(names[i]) + ":";
        const auto &v = response.values[i];
        if (v.type == 2)
          fields += std::to_string(v.integer_value);
        else if (v.type == 4)
          fields += q(v.string_value);
        else if (v.type == 1)
          fields += v.bool_value ? "true" : "false";
        else
          fields += "null";
      }
      std::lock_guard<std::mutex> l(w.mutex);
      w.emit(fields + "},\"requester_guid_is_not_server_identity\":true");
    } else if (std::chrono::steady_clock::now() >= deadline) {
      done = true;
      client->remove_pending_request(request_id);
      std::lock_guard<std::mutex> l(w.mutex);
      w.emit("\"kind\":\"parameter_timeout\",\"endpoint\":" + q(endpoint));
    }
  }
  ~Query() {
    if (sent && !done)
      client->remove_pending_request(request_id);
  }
};
int main(int argc, char **argv) {
  // Fixed diagnostics contract. No arbitrary topics/services or configurable
  // controls.
  if (argc != 5 || std::string(argv[1]) != "--session-id" ||
      std::string(argv[3]) != "--output") {
    std::cerr << "Use --session-id UUID --output /private/new.jsonl\n";
    return 2;
  }
  try {
    Session session(argv[2]);
    Writer w(argv[4]);
    w.session_id = session.id;
    w.model_request = session.prefix + "/capture/model_request";
    w.emit("\"kind\":\"header\",\"session_id\":" + q(session.id) +
           ",\"boot_id\":" + q(session.boot) +
           ",\"observer_pid\":" + std::to_string(::getpid()) +
           ",\"observer_start_ticks\":" + q(ticks(::getpid())) +
           ",\"selection_sha256\":" +
           q(YAML::Load(session.selection)["descriptor"]["selection_sha256"]
                 .as<std::string>()) +
           ",\"probe_session_id\":" + q(session.id) +
           ",\"duration_s\":120,\"max_samples\":20,\"reader_limit_bytes\":"
           "524288,\"source_association_verified\":false");
    rclcpp::init(0, nullptr);
    auto options = rclcpp::NodeOptions()
                       .enable_rosout(false)
                       .start_parameter_services(false)
                       .start_parameter_event_publisher(false);
    auto node =
        std::make_shared<rclcpp::Node>("tfg_rover_passive_validation", options);
    rclcpp::executors::SingleThreadedExecutor exec;
    exec.add_node(node);
    auto group = node->create_callback_group(
        rclcpp::CallbackGroupType::MutuallyExclusive, false);
    std::vector<std::unique_ptr<Query>> queries;
    queries.emplace_back(new Query(*node, group, "/ap/v3/get_parameters",
                                   {"MAV_SYSID", "DDS_USE_NS"}));
    queries.emplace_back(
        new Query(*node, group, "/rover1/robot_state_publisher/get_parameters",
                  {"robot_description"}));
    queries.emplace_back(new Query(
        *node, group, "/rover1/ros_gz_bridge/get_parameters",
        {"config_file", "override_frame_id",
         "override_timestamps_with_wall_time", "expand_gz_topic_names"}));
    std::vector<rclcpp::SubscriptionBase::SharedPtr> subs;
    subs.push_back(
        subscribe<Status>(*node, w, "/ap/v3/status", 1, [](const Status &m) {
          return header(m.header) +
                 ",\"armed\":" + (m.armed ? "true" : "false") +
                 ",\"flying\":" + (m.flying ? "true" : "false") +
                 ",\"mode\":" + std::to_string(m.mode);
        }));
    subs.push_back(subscribe<Odometry>(
        *node, w, "/rover1/odometry", 3, [](const Odometry &m) {
          return header(m.header) +
                 ",\"child_frame_id\":" + q(m.child_frame_id) +
                 ",\"position_m\":" + xyz(m.pose.pose.position) +
                 ",\"orientation_xyzw\":" + quat(m.pose.pose.orientation) +
                 ",\"linear_m_s\":" + xyz(m.twist.twist.linear) +
                 ",\"angular_rad_s\":" + xyz(m.twist.twist.angular) +
                 ",\"pose_covariance\":" + numbers(m.pose.covariance) +
                 ",\"twist_covariance\":" + numbers(m.twist.covariance);
        }));
    for (const auto &v : {"v1", "v2", "v3"}) {
      subs.push_back(subscribe<sensor_msgs::msg::NavSatFix>(
          *node, w, std::string("/ap/") + v + "/navsat", 2, [](const auto &m) {
            return header(m.header) +
                   ",\"latitude_deg\":" + number(m.latitude) +
                   ",\"longitude_deg\":" + number(m.longitude) +
                   ",\"altitude_m\":" + number(m.altitude) +
                   ",\"covariance\":" + numbers(m.position_covariance) +
                   ",\"covariance_type\":" +
                   std::to_string(m.position_covariance_type) +
                   ",\"fix_status\":" + std::to_string(m.status.status);
          }));
      subs.push_back(subscribe<geographic_msgs::msg::GeoPoseStamped>(
          *node, w, std::string("/ap/") + v + "/geopose/filtered", 2,
          [](const auto &m) {
            return header(m.header) +
                   ",\"latitude_deg\":" + number(m.pose.position.latitude) +
                   ",\"longitude_deg\":" + number(m.pose.position.longitude) +
                   ",\"altitude_m\":" + number(m.pose.position.altitude) +
                   ",\"orientation_xyzw\":" + quat(m.pose.orientation);
          }));
    }
    gz::transport::Node gz_node;
    std::function<void(const gz::msgs::Pose_V &)> gz_callback =
        [&](const auto &message) {
          std::lock_guard<std::mutex> l(w.mutex);
          try {
            gz::msgs::Pose_V selected;
            *selected.mutable_header() = message.header();
            for (const auto &p : message.pose())
              if (p.name() == "rover1" || p.name() == "drone1" ||
                  p.name() == "drone2")
                *selected.add_pose() = p;
            if (selected.pose_size() == 0 ||
                !w.retain_at(
                    "/world/runway/pose/info", 4,
                    static_cast<std::int64_t>(message.header().stamp().sec()) *
                            1000000000 +
                        message.header().stamp().nsec()))
              return;
            std::string data;
            auto result =
                google::protobuf::util::MessageToJsonString(selected, &data);
            if (!result.ok())
              throw std::runtime_error("Gazebo JSON failed");
            w.emit("\"kind\":\"sample\",\"topic\":\"/world/runway/pose/"
                   "info\",\"source\":\"Gazebo public transport; entity names "
                   "are selectors, not identities\",\"body\":" +
                   data);
          } catch (...) {
            w.failure = std::current_exception();
            w.open = false;
          }
        };
    if (!gz_node.Subscribe("/world/runway/pose/info", gz_callback))
      throw std::runtime_error("Gazebo passive subscription failed");
    const auto start = std::chrono::steady_clock::now();
    auto next_context = start;
    bool scene_requested = false;
    bool graph_recorded = false;
    while (rclcpp::ok() && std::chrono::steady_clock::now() - start <
                               std::chrono::seconds(120)) {
      {
        std::lock_guard<std::mutex> l(w.mutex);
        if (w.failure)
          std::rethrow_exception(w.failure);
      }
      if (std::chrono::steady_clock::now() >= next_context) {
        session.check();
        next_context =
            std::chrono::steady_clock::now() + std::chrono::seconds(1);
      }
      exec.spin_some(std::chrono::milliseconds(20));
      for (auto &query : queries)
        query->poll(*node, w);
      if (!scene_requested) {
        scene_requested = true;
        gz::msgs::Empty request;
        gz::msgs::Scene response;
        bool result = false;
        const bool received = gz_node.Request("/world/runway/scene/info",
                                              request, 1000, response, result);
        std::string body = "null";
        if (received && result) {
          body = "[";
          for (const auto &model : response.model()) {
            if (body.size() > 1)
              body += ",";
            std::string pose;
            auto status = google::protobuf::util::MessageToJsonString(
                model.pose(), &pose);
            if (!status.ok())
              pose = "null";
            body += "{\"id\":" + std::to_string(model.id()) +
                    ",\"name\":" + q(model.name()) + ",\"pose\":" + pose + "}";
          }
          body += "]";
        }
        std::lock_guard<std::mutex> l(w.mutex);
        w.emit("\"kind\":\"scene_catalog\",\"received\":" +
               std::string(received && result ? "true" : "false") +
               ",\"body\":" + body);
      }
      if (!graph_recorded &&
          std::chrono::steady_clock::now() - start > std::chrono::seconds(2)) {
        graph_recorded = true;
        std::lock_guard<std::mutex> l(w.mutex);
        auto services = node->get_service_names_and_types();
        for (const auto &e : services) {
          if (e.first == "/ap/v3/arm_motors" ||
              e.first == "/ap/v3/mode_switch" ||
              e.first == "/ap/v3/get_parameters") {
            std::string types = "[";
            for (const auto &t : e.second) {
              if (types.size() > 1)
                types += ",";
              types += q(t);
            }
            w.emit(
                "\"kind\":\"service_candidates\",\"endpoint\":" + q(e.first) +
                ",\"types\":" + types + "],\"server_identity_verified\":false");
          }
        }
        for (const auto &topic :
             {"/ap/v3/status", "/rover1/odometry", "/ap/v3/cmd_vel"}) {
          std::string values = "[";
          const bool command = std::string(topic) == "/ap/v3/cmd_vel";
          auto endpoints = command
                               ? node->get_subscriptions_info_by_topic(topic)
                               : node->get_publishers_info_by_topic(topic);
          if (endpoints.size() > 32)
            throw std::runtime_error("Discovery candidate cap");
          for (const auto &e : endpoints) {
            if (values.size() > 1)
              values += ",";
            values +=
                "{\"gid\":" +
                q(hex(e.endpoint_gid().data(), e.endpoint_gid().size())) +
                ",\"node\":" + q(e.node_namespace() + "/" + e.node_name()) +
                ",\"type\":" + q(e.topic_type()) + "}";
          }
          w.emit("\"kind\":\"graph_candidates\",\"topic\":" + q(topic) +
                 ",\"attributed_to_sample\":false,\"endpoints\":" + values +
                 "]");
        }
      }
      {
        std::lock_guard<std::mutex> l(w.mutex);
        if (w.samples >= 20 &&
            std::all_of(queries.begin(), queries.end(),
                        [](const auto &query) { return query->done; }) &&
            graph_recorded)
          break;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    {
      std::lock_guard<std::mutex> l(w.mutex);
      w.open = false;
    }
    session.check();
    gz_node.Unsubscribe("/world/runway/pose/info");
    subs.clear();
    for (const auto &query : queries) {
      if (!query->done) {
        std::lock_guard<std::mutex> l(w.mutex);
        w.emit("\"kind\":\"parameter_unavailable\",\"endpoint\":" +
               q(query->endpoint) +
               ",\"request_sent\":" + (query->sent ? "true" : "false"));
      }
    }
    queries.clear();
    exec.remove_node(node);
    node.reset();
    rclcpp::shutdown();
    if (w.failure)
      std::rethrow_exception(w.failure);
    std::string counts = "{", omitted = "{", before = "{", spacing = "{",
                rewinds = "{";
    for (const auto &p : w.count) {
      if (counts.size() > 1)
        counts += ",";
      counts += q(p.first) + ":" + std::to_string(p.second);
    }
    for (const auto &p : w.omitted) {
      if (omitted.size() > 1)
        omitted += ",";
      omitted += q(p.first) + ":" + std::to_string(p.second);
    }
    for (const auto &p : w.before_status) {
      if (before.size() > 1)
        before += ",";
      before += q(p.first) + ":" + std::to_string(p.second);
    }
    for (const auto &p : w.omitted_by_spacing) {
      if (spacing.size() > 1)
        spacing += ",";
      spacing += q(p.first) + ":" + std::to_string(p.second);
    }
    for (const auto &p : w.clock_rewinds) {
      if (rewinds.size() > 1)
        rewinds += ",";
      rewinds += q(p.first) + ":" + std::to_string(p.second);
    }
    w.emit("\"kind\":\"footer\",\"omitted_by_spacing\":" + spacing +
           "},\"clock_rewinds_observed\":" + rewinds +
           "},\"retained_stream_count\":" + std::to_string(w.count.size()) +
           ",\"expected_stream_count\":9,\"session_id\":" + q(session.id) +
           ",\"counts\":" + counts + "},\"omitted_by_quota\":" + omitted +
           "},\"omitted_before_status\":" + before +
           "},\"reader_closed\":true,\"identity_verified\":false");
    w.out.finish();
    PrivateJournal receipt(std::string(argv[4]) + ".receipt.json");
    receipt.append("{\"schema\":\"tfg.rover-passive-validation-receipt/"
                   "1\",\"session_id\":" +
                   q(session.id) +
                   ",\"reader_closed\":true,\"status\":\"BLOCKED\",\"movement_"
                   "authorized\":false}");
    receipt.finish();
    std::cout << "{\"status\":\"BLOCKED\",\"reader_closed\":true,\"movement_"
                 "authorized\":false}\n";
    return 0;
  } catch (const std::exception &) {
    std::cerr
        << "Passive reader incomplete; no identity or control authority\n";
    if (rclcpp::ok())
      rclcpp::shutdown();
    return 2;
  }
}
