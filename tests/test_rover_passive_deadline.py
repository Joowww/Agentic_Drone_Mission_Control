"""Deterministic fake-ROS budget regression; never executes collector.cpp."""
from pathlib import Path
import shutil
import subprocess

import pytest
from tests.test_rover_passive_rclcpp import STUB, ROOT


def test_setup_is_charged_to_shared_budget_and_closure_has_room(tmp_path):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    (tmp_path/'contract.hpp').write_text(STUB.replace('bool armed=false;', 'bool armed=false; bool flying=false;'))
    for name in ('ardupilot_msgs/msg/status.hpp', 'nav_msgs/msg/odometry.hpp',
                 'rclcpp/rclcpp.hpp', 'rclcpp/message_info.hpp', 'rmw/types.h'):
        p = tmp_path/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('#include "contract.hpp"\n')
    source = r'''
#include "tools/rover_passive_rclcpp/collector_core.hpp"
#include <cassert>
#include <cmath>
using namespace tfg::rover_passive;
struct Writer {
  double &time; double hard; bool finished=false;
  std::vector<std::string> lines{};
  void append(const std::string &line) { assert(time < hard); lines.push_back(line); }
  void finish() { time += .01; assert(time < hard); finished=true; }
};
int main() {
  Limits limits{20,10};
  const auto deadlines=capture_deadlines(100,limits);
  assert(deadlines.hard==110 && std::abs(deadlines.collection-109.95)<1e-9);
  // Setup has already consumed 4 seconds. Collection must not get 10 new seconds.
  double time=104; Writer writer{time,deadlines.hard};
  auto result=collect(writer,limits,[&]{return time;},[&](auto &,double budget){
    assert(budget>0 && budget<=.05); time+=budget; return true;
  },deadlines.collection);
  assert(writer.finished && time<110 && result.termination=="DURATION_LIMIT");
  assert(!result.capture_complete); // no streams fabricated
  // If setup uses the collection window, do not poll or replenish the budget.
  time=109.96; Writer late{time,110};int polls=0;
  collect(late,limits,[&]{return time;},[&](auto &,double){++polls;return true;},deadlines.collection);
  assert(polls==0 && late.finished && time<110);
  const auto small=capture_deadlines(0,Limits{2,.1});
  assert(std::abs(small.collection-.09)<1e-9 && small.hard==.1);
  // A fast single stream can use all 20 slots before a delayed Status callback.
  auto odometry=[] {
    Sample s; s.topic="/rover1/odometry";s.message_type="nav_msgs/msg/Odometry";
    Odometry od;od.header.frame_id="odom";od.child_frame_id="base_link";s.message=od;
    GidBytes gid{};gid[0]=1;s.message_publisher_gid=gid;
    s.message_gid_state="OBSERVED_NOT_ACCREDITED";s.rmw_implementation_identifier="synthetic";
    s.graph_state="OBSERVED";s.graph_received=Receipt{1,1};s.receipt=Receipt{1,1};return s;
  };
  time=104;Writer capped{time,110};int callbacks=0;
  auto single=collect(capped,limits,[&]{return time;},[&](auto &sink,double){
    ++callbacks;time+=.001;auto msg=odometry();sink(msg);return true;
  },deadlines.collection);
  assert(callbacks==20 && single.samples==20 && single.status_samples==0);
  assert(single.termination=="SAMPLE_LIMIT" && !single.capture_complete && capped.finished);
  assert(capped.lines.back().find("\"data_present_both_streams\":false")!=std::string::npos);
  assert(capped.lines.back().find("\"capture_complete\":null")!=std::string::npos);
  // Missing Status at the time limit still produces an explicit footer/finish,
  // not a fabricated complete result; no resetting the time or automatic retry.
  time=104;Writer partial{time,110};callbacks=0;
  auto missing=collect(partial,limits,[&]{return time;},[&](auto &sink,double budget){
    time+=budget;if(++callbacks<=3){auto msg=odometry();sink(msg);}return true;
  },deadlines.collection);
  assert(missing.samples==3 && missing.status_samples==0 && !missing.capture_complete);
  assert(missing.termination=="DURATION_LIMIT" && partial.finished && time<110);
  assert(partial.lines.back().find("\"event\":\"end\"")!=std::string::npos);

}
'''
    path = tmp_path/'budget.cpp'
    path.write_text(source)
    built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-pedantic', '-I', str(tmp_path), '-I', str(ROOT), str(path),
                            '-o', str(tmp_path/'budget')], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    subprocess.run([str(tmp_path/'budget')], check=True, timeout=5)
