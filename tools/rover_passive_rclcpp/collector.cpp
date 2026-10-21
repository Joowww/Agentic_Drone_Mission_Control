// Future authorized passive receiver only. Not built/installed by the project.
#include "collector_core.hpp"
#include "private_journal.hpp"
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <thread>

namespace {
class DeadlineGuard {
public:
  explicit DeadlineGuard(double seconds) : thread_([this, seconds] {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!condition_.wait_for(lock, std::chrono::duration<double>(seconds), [this] { return done_; })) {
      // Only this collector process exits. No vehicle/process signals, retries,
      // final writes or fabricated completion. Missing receipt means UNCERTAIN.
      std::_Exit(2);
    }
  }) {}
  ~DeadlineGuard() {
    { std::lock_guard<std::mutex> lock(mutex_); done_ = true; }
    condition_.notify_one();
    thread_.join();
  }
private:
  std::mutex mutex_;
  std::condition_variable condition_;
  bool done_ = false;
  std::thread thread_;
};
struct ContextCleanup {
  std::shared_ptr<rclcpp::Context> context;
  ~ContextCleanup() { if (context->is_valid()) { try { context->shutdown("passive collector finished"); } catch (...) {} } }
};
}  // namespace

int main(int argc, char ** argv) {
  using namespace tfg::rover_passive;
  if (argc != 7 || std::string(argv[1]) != "--output" || std::string(argv[3]) != "--max-samples" ||
      std::string(argv[5]) != "--duration-s") {
    std::cerr << "Required: --output ABSOLUTE_NEW_FILE --max-samples N --duration-s SECONDS\n";
    return 2;
  }
  try {
    std::size_t consumed = 0;
    const auto count = std::stoull(argv[4], &consumed);
    if (consumed != std::string(argv[4]).size() || count > 10000) throw std::invalid_argument("sample count");
    const double duration = std::stod(argv[6], &consumed);
    if (consumed != std::string(argv[6]).size()) throw std::invalid_argument("duration");
    const Limits limits{static_cast<std::size_t>(count), duration};
    limits.validate();
    // Covers setup, blocking discovery/writes, spinning and destruction too.
    // A deadline abort has no success receipt and must remain UNCERTAIN.
    DeadlineGuard deadline(duration);
    PrivateJournal journal(argv[2]);
    auto context = std::make_shared<rclcpp::Context>();
    ContextCleanup cleanup{context};
    context->init(0, nullptr);  // no arbitrary ROS/remapping/parameter arguments
    auto options = rclcpp::NodeOptions().context(context).use_global_arguments(false)
      .enable_rosout(false).start_parameter_services(false).start_parameter_event_publisher(false)
      .use_intra_process_comms(false);
    auto node = std::make_shared<rclcpp::Node>("tfg_rover_passive_collector", options);
    rclcpp::ExecutorOptions executor_options;
    executor_options.context = context;
    rclcpp::executors::SingleThreadedExecutor executor(executor_options);
    executor.add_node(node);
    std::optional<Sample> pending;
    Observer observer(*node, [&](const Sample & sample) { pending = sample; });
    const auto now = [] { return std::chrono::duration<double>(
        std::chrono::steady_clock::now().time_since_epoch()).count(); };
    const auto poll = [&](const auto & sink, double budget) {
      if (!context->is_valid()) return false;
      executor.spin_once(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::duration<double>(budget)));
      if (pending) { sink(*pending); pending.reset(); }
      return context->is_valid();
    };
    const auto result = collect(journal, limits, now, poll);
    executor.remove_node(node);
    context->shutdown("passive capture limits reached");
    // File footer never claims durable completion; stdout receipt comes only
    // after successful finish(), and still never verifies source identity.
    std::cout << '{' << blocked_fields << ",\"capture_state\":"
              << (result.capture_complete ? "\"DATA_RECORDED\"" : "\"UNCERTAIN\"")
              << ",\"capture_complete\":" << (result.capture_complete ? "true" : "false")
              << ",\"samples\":" << result.samples << ",\"termination\":" << json_quote(result.termination) << "}\n";
    if (!std::cout) return 2;
    return result.capture_complete ? 0 : 2;
  } catch (...) {
    // Includes initialization, metadata conversion, writes/fsync/close failures.
    // No raw exception text, automatic retry, cleanup of evidence or fallback.
    std::cerr << "collector: UNCERTAIN; capture not confirmed complete; preserve partial output\n";
    return 2;
  }
}
