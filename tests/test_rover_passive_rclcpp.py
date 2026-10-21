"""Compile only against explicit contract doubles, never ROS headers/libraries.

This exercises callback data flow, not ABI, the installed executor, DDS or runtime.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUB = r'''
#pragma once
#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>
#define RMW_GID_STORAGE_SIZE 24
struct rmw_gid_t { const char * implementation_identifier=nullptr; std::uint8_t data[24]{}; };
struct rmw_message_info_t { rmw_gid_t publisher_gid; bool from_intra_process=false; };
struct Header { struct Stamp { int sec=0; unsigned nanosec=0; } stamp; std::string frame_id; };
namespace ardupilot_msgs::msg { struct Status { Header header; int vehicle_type=1; bool armed=false; }; }
namespace nav_msgs::msg { struct Odometry { Header header; std::string child_frame_id; double synthetic_velocity=0; }; }
namespace rclcpp {
struct MessageInfo {
  rmw_message_info_t value;
  const rmw_message_info_t & get_rmw_message_info() const { return value; }
};
struct KeepLast { explicit KeepLast(int n): count(n) {} int count; };
struct QoS {
  explicit QoS(KeepLast k): depth(k.count) {}
  QoS & best_effort() { best=true; return *this; }
  QoS & durability_volatile() { vol=true; return *this; }
  int depth; bool best=false, vol=false;
};
template<class T> struct Subscription { using SharedPtr=std::shared_ptr<Subscription<T>>; };
struct TopicEndpointInfo {
  std::array<std::uint8_t,24> gid{};
  auto endpoint_gid() const { return gid; }
  std::string node_name() const { return "synthetic-bridge"; }
  std::string node_namespace() const { return "/rover1"; }
};
struct Node {
  template<class T> using Callback=std::function<void(std::shared_ptr<const T>, const MessageInfo &)>;
  Callback<ardupilot_msgs::msg::Status> status;
  Callback<nav_msgs::msg::Odometry> odometry;
  std::vector<std::string> topics;
  std::vector<TopicEndpointInfo> endpoints;
  bool graph_failure=false;
  template<class T, class F>
  typename Subscription<T>::SharedPtr create_subscription(std::string topic, QoS qos, F fn) {
    if (qos.depth!=5 || !qos.best || !qos.vol) throw std::runtime_error("wrong qos");
    topics.push_back(topic);
    if constexpr (std::is_same_v<T, ardupilot_msgs::msg::Status>) status=fn;
    else odometry=fn;
    return std::make_shared<Subscription<T>>();
  }
  auto get_publishers_info_by_topic(std::string) {
    if(graph_failure) throw std::runtime_error("synthetic discovery failure");
    return endpoints;
  }
  // Deliberately no publisher, client, spin, clock or private-handle API.
};
} // namespace rclcpp
'''
HARNESS = r'''
#include "tools/rover_passive_rclcpp/observer.hpp"
#include <cassert>
int main(int argc, char **argv) {
  assert(argc==2);
  const std::string mode=argv[1];
  using namespace tfg::rover_passive;
  rclcpp::Node node;
  rclcpp::TopicEndpointInfo endpoint; endpoint.gid[0]=99;
  node.endpoints={endpoint}; // one candidate != message GID: never substitute it
  node.graph_failure=(mode=="graph_failure");
  if(mode=="multiple_candidates") node.endpoints.push_back(endpoint);
  std::vector<Sample> samples;
  int tick=0;
  Observer observer(node,[&](const Sample &s){ samples.push_back(s); },
    [&](){ ++tick; return Receipt{1000000+tick,2000000+tick}; });
  assert((node.topics==std::vector<std::string>{"/ap/v3/status","/rover1/odometry"}));
  rclcpp::MessageInfo info;
  info.value.publisher_gid.data[0]=7;
  info.value.publisher_gid.implementation_identifier="synthetic-rmw";
  if(mode=="missing_implementation") info.value.publisher_gid.implementation_identifier=nullptr;
  if(mode=="zero_gid") info.value.publisher_gid.data[0]=0;
  if(mode=="intra_process") info.value.from_intra_process=true;
  auto status=std::make_shared<Status>();
  status->header.stamp.sec=17; status->header.stamp.nanosec=42;
  status->header.frame_id="status-frame";
  if(mode=="wrong_type") status->vehicle_type=2;
  node.status(status,info); // exact public callback: message + MessageInfo
  info.value.publisher_gid.data[0]=8;
  auto odom=std::make_shared<Odometry>();
  odom->header.stamp.sec=3; odom->child_frame_id="base_link";
  odom->synthetic_velocity=1.25;
  node.odometry(odom,info);
  node.status(nullptr,info); assert(samples.size()==2);
  if(mode=="source_replacement") {
    status->header.stamp.sec=1; // rewind is recorded, never normalized or approved
    info.value.publisher_gid.data[0]=9;
    node.status(status,info);
    assert(samples.size()==3);
    assert(samples[2].message_publisher_gid->at(0)==9);
    assert(samples[0].message_publisher_gid->at(0)==7);
    assert(std::get<Status>(samples[0].message).header.stamp.sec==17);
    assert(std::get<Status>(samples[2].message).header.stamp.sec==1);
  }
  assert(std::get<Status>(samples[0].message).header.stamp.sec==17);
  assert(std::get<Status>(samples[0].message).header.stamp.nanosec==42);
  assert(std::get<Status>(samples[0].message).header.frame_id=="status-frame");
  assert(std::get<Odometry>(samples[1].message).synthetic_velocity==1.25);
  assert(samples[1].message_publisher_gid->at(0)==8);
  assert(samples[0].message_publisher_gid->at(0)==(mode=="zero_gid"?0:7));
  assert(samples[0].receipt.system_unix_ns!=17000000042); // never header-as-receipt
  assert(samples[1].receipt.steady_ns>samples[0].receipt.steady_ns);
  const bool unknown=(mode=="missing_implementation" || mode=="zero_gid" || mode=="intra_process");
  assert(samples[0].message_gid_state==(unknown?"UNKNOWN":"OBSERVED_NOT_ACCREDITED"));
  for (const auto &s:samples) {
    assert(std::string(s.status)=="BLOCKED" && !s.movement_authorized && !s.source_association_verified);
    assert(!s.attributed_publisher_identity);
    if(mode=="graph_failure") {
      assert(s.graph_state=="UNKNOWN" && !s.graph_received && s.graph_candidates.empty());
    } else {
      assert(s.graph_state=="OBSERVED" && s.graph_received);
      assert(s.graph_candidates.size()==(mode=="multiple_candidates"?2:1));
      assert(s.graph_candidates[0].endpoint_gid[0]==99);
    }
  }
}
'''


@pytest.fixture(scope='module')
def offline_binary(tmp_path_factory):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++17 compiler absent; no ROS build attempted')
    root = tmp_path_factory.mktemp('rover-cpp-contract')
    (root/'contract.hpp').write_text(STUB)
    for header in ('ardupilot_msgs/msg/status.hpp','nav_msgs/msg/odometry.hpp',
                   'rclcpp/rclcpp.hpp','rclcpp/message_info.hpp','rmw/types.h'):
        path=root/header
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#include "contract.hpp"\n')
    (root/'test.cpp').write_text(HARNESS)
    binary=root/'test'
    result = subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic',
                    '-I',str(root),'-I',str(ROOT),str(root/'test.cpp'),'-o',str(binary)],
                   capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize('mode',['normal','graph_failure','multiple_candidates','zero_gid',
                                  'missing_implementation','intra_process','wrong_type','source_replacement'])
def test_public_message_info_data_flow_stays_blocked(offline_binary,mode):
    subprocess.run([str(offline_binary),mode],capture_output=True,text=True,check=True,timeout=5)
