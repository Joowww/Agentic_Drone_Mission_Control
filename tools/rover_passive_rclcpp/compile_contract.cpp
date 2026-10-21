// Syntax-only contract probe. No main, node creation, spin or executable target.
#include "observer.hpp"
#include <type_traits>
#include <utility>

using tfg::rover_passive::Observer;
using tfg::rover_passive::Status;
using tfg::rover_passive::Odometry;
using NativeInfo = decltype(std::declval<const rclcpp::MessageInfo &>().get_rmw_message_info());
static_assert(std::is_same_v<NativeInfo, const rmw_message_info_t &>);
static_assert(std::is_same_v<decltype(std::declval<NativeInfo>().publisher_gid), rmw_gid_t>);
static_assert(std::is_same_v<decltype(std::declval<NativeInfo>().from_intra_process), bool>);
static_assert(sizeof(std::declval<rmw_gid_t>().data) == RMW_GID_STORAGE_SIZE);
static_assert(std::is_same_v<decltype(std::declval<Status>().header.stamp.sec), std::int32_t>);
static_assert(std::is_same_v<decltype(std::declval<Odometry>().header.stamp.sec), std::int32_t>);
static_assert(std::is_constructible_v<Observer, rclcpp::Node &, Observer::Sink>);
static_assert(!tfg::rover_passive::Sample::movement_authorized);
static_assert(!tfg::rover_passive::Sample::source_association_verified);
