"""Quota/serialization tests with fake ROS; no real collector process."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from tests.test_rover_passive_rclcpp import STUB, ROOT
from tools.rover_passive_journal import analyze_bytes


@pytest.fixture(scope='module')
def quota_binary(tmp_path_factory):
    cc=shutil.which('c++')
    if not cc:pytest.skip('No C++ compiler')
    root=tmp_path_factory.mktemp('quota')
    (root/'contract.hpp').write_text(STUB.replace('bool armed=false;', 'bool armed=false; bool flying=false;'))
    for name in ('ardupilot_msgs/msg/status.hpp','nav_msgs/msg/odometry.hpp','rclcpp/rclcpp.hpp','rclcpp/message_info.hpp','rmw/types.h'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "contract.hpp"\n')
    source=r'''
#include "tools/rover_passive_rclcpp/collector_core.hpp"
#include <cassert>
#include <iostream>
using namespace tfg::rover_passive;
struct Writer {
 std::vector<std::string> lines;bool finished=false;
 void append(const std::string &s){lines.push_back(s);}void finish(){finished=true;}
};
Sample sample(bool status) {
 Sample s;s.receipt={1,1};s.graph_received=Receipt{2,2};s.graph_state="OBSERVED";
 s.topic=status?"/ap/v3/status":"/rover1/odometry";
 s.message_type=status?"ardupilot_msgs/msg/Status":"nav_msgs/msg/Odometry";
 if(status)s.message=Status{};else{Odometry od;od.header.frame_id="odom";od.child_frame_id="base_link";s.message=od;}
 GidBytes gid{};gid[0]=1;s.message_publisher_gid=gid;s.message_gid_state="OBSERVED_NOT_ACCREDITED";s.rmw_implementation_identifier="synthetic";
 Candidate c{gid,"graph","/rover1"};c.topic_type=s.message_type;c.offered_qos=OfferedQos{1,2,1,1};s.graph_candidates.push_back(c);
 return s;
}
int main(int argc,char **argv) {
 assert(argc==2);
 bool oversized=false;try{Limits{21,120,true}.validate();}catch(const std::invalid_argument&){oversized=true;}
 assert(oversized);Limits{21,120,false}.validate(); // legacy bounds unchanged
 std::string mode=argv[1];Writer w;int calls=0;double time=0;
 bool reverse=mode=="reverse";Limits limits{20,10,true};
 auto result=collect(w,limits,[&]{return time;},[&](auto &sink,double){
  ++calls;
  if(mode=="absent"){time=calls*.125;sink(sample(false));}
  else {time=calls*.01;sink(sample(reverse ? calls!=100 : calls==100));}
  return true;
 },std::nullopt,[&]{
   Discovery d;d.topic="/ap/v3/status";d.state="OBSERVED";d.receipt=Receipt{1,1};
   w.append(serialize_discovery(d));
 });
 assert(w.finished && result.samples<=20);
 if(mode=="absent"){
  assert(result.samples==19 && result.status_samples==0 && !result.capture_complete);
  assert(result.omitted_odometry_quota==60 && result.termination=="DURATION_LIMIT");
 }else{
  assert(result.samples==20 && result.capture_complete && calls==100);
  assert((reverse?result.omitted_status_quota:result.omitted_odometry_quota)==80);
 }
 for(const auto &line:w.lines)std::cout<<line<<'\n';
}
'''
    (root/'quota.cpp').write_text(source)
    r=subprocess.run([cc,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-I',str(root),'-I',str(ROOT),str(root/'quota.cpp'),'-o',str(root/'quota')],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    return root/'quota'


@pytest.mark.parametrize('mode',['delayed','reverse','absent'])
def test_reserved_capacity_and_actual_serializer(quota_binary,mode):
    r=subprocess.run([str(quota_binary),mode],capture_output=True,check=True,timeout=5)
    events=[json.loads(line) for line in r.stdout.splitlines()]
    assert events[0]['schema']=='tfg.rover.passive-capture/2'
    samples=[e for e in events if e['event']=='sample']
    assert len(samples)<=20 and events[-1]['capture_complete'] is None
    assert samples[0]['graph']['candidates'][0]['offered_qos']['depth']==1
    assert not analyze_bytes(r.stdout)['issues']
    if mode=='absent':assert len(samples)==19 and events[-1]['omitted_odometry_quota']==60
