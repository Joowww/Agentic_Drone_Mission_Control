"""Offline core/file tests and syntax-only program check with fake ROS headers.

Never builds against ROS or executes collector.cpp / a ROS node.
"""
from pathlib import Path
import json
import shutil
import stat
import subprocess

import pytest

from tests.test_rover_passive_rclcpp import STUB, ROOT

HARNESS = r'''
#include "tools/rover_passive_rclcpp/collector_core.hpp"
#include "tools/rover_passive_rclcpp/private_journal.hpp"
#include <cassert>
#include <iostream>
#include <limits>
using namespace tfg::rover_passive;
struct Writer {
  int calls=0, finished=0, fail_at=0;
  bool fail_finish=false;
  std::vector<std::string> lines;
  void append(const std::string & line) {
    if (++calls==fail_at) throw std::runtime_error("synthetic write/fsync failure");
    lines.push_back(line);
  }
  void finish() { ++finished; if(fail_finish) throw std::runtime_error("synthetic close failure"); }
};
Sample sample(bool status=true) {
  Sample s; s.topic=status?"/ap/v3/status":"/rover1/odometry";
  s.message_type=status?"ardupilot_msgs/msg/Status":"nav_msgs/msg/Odometry";
  if(status) s.message=Status{};
  else { Odometry odom; odom.child_frame_id="base_link"; odom.header.frame_id="odom"; s.message=odom; }
  s.receipt={100,200}; s.graph_received=Receipt{101,201};
  GidBytes gid{}; gid[0]=7; s.message_publisher_gid=gid;
  s.rmw_implementation_identifier="synthetic"; s.message_gid_state="OBSERVED_NOT_ACCREDITED";
  s.graph_state="OBSERVED"; gid[0]=99;
  s.graph_candidates.push_back({gid,"graph-\"candidate\n","/rover1"});
  return s;
}
int main(int argc,char **argv) {
  assert(argc>=2); const std::string mode=argv[1];
  if(mode=="file" || mode=="file_reject") {
    assert(argc==3);
    try {
      PrivateJournal out(argv[2]); out.append("{\"event\":\"offline_test\"}"); out.finish();
      assert(mode=="file");
    } catch(...) { assert(mode=="file_reject"); }
    return 0;
  }
  Writer writer; double time=0; int polls=0;
  if(mode=="start_failure") writer.fail_at=1;
  if(mode=="sample_failure") writer.fail_at=3;
  if(mode=="footer_failure") writer.fail_at=4;
  if(mode=="close_failure") writer.fail_finish=true;
  Limits limits{2,.5};
  if(mode=="invalid_limits") limits.samples=1;
  if(mode=="oversize_limit") limits.samples=10001;
  if(mode=="zero_duration") limits.duration_s=0;
  if(mode=="nan_duration") limits.duration_s=std::numeric_limits<double>::quiet_NaN();
  bool threw=false;
  try {
    auto result=collect(writer,limits,[&]{return time;},[&](const auto &sink,double budget){
      ++polls; assert(budget>=0 && budget<=.05);
      if(mode=="interrupted") return false;
      if(mode=="duration") {time+=.25; return true;}
      auto first=sample();
      if(mode=="incomplete") {first.message_publisher_gid.reset();first.message_gid_state="UNKNOWN";}
      if(mode=="zero_gid") {first.message_publisher_gid->fill(0); first.message_gid_state="UNKNOWN";}
      if(mode=="intra_process") {first.from_intra_process=true; first.message_gid_state="UNKNOWN";}
      if(mode=="missing_rmw") {first.rmw_implementation_identifier.reset(); first.message_gid_state="UNKNOWN";}
      if(mode=="graph_unknown") {first.graph_state="UNKNOWN"; first.graph_received.reset();}
      if(mode=="late_poll") time=1.;
      sink(first);
      sink(sample(mode=="one_stream"));
      sink(sample()); // must be ignored beyond the explicit max sample count
      return true;
    });
    assert(mode!="start_failure" && mode!="sample_failure" && mode!="footer_failure" && mode!="close_failure" && mode!="invalid_limits" && mode!="oversize_limit" && mode!="zero_duration" && mode!="nan_duration");
    assert(result.samples<=2 && writer.finished==1);
    if(mode=="normal") assert(result.capture_complete && result.samples==2 && polls==1);
    else assert(!result.capture_complete);
    if(mode=="duration") assert(result.termination=="DURATION_LIMIT" && polls==2);
    if(mode=="interrupted") assert(result.termination=="INTERRUPTED");
    std::cout << "{\"complete\":" << (result.capture_complete?"true":"false") << "}\n";
  } catch(...) { threw=true; }
  if(mode=="start_failure") assert(threw && polls==0 && writer.calls==1 && writer.finished==0);
  if(mode=="sample_failure") assert(threw && polls==1 && writer.calls==3 && writer.finished==0);
  if(mode=="footer_failure") assert(threw && writer.calls==4 && writer.finished==0);
  if(mode=="close_failure") assert(threw && writer.finished==1);
  if(mode=="invalid_limits" || mode=="oversize_limit" || mode=="zero_duration" || mode=="nan_duration") assert(threw && polls==0 && writer.calls==0);
  for(const auto &line:writer.lines) std::cout << line << '\n';
}
'''
# Only used for syntax checking the program, never executed. They implement no ROS.
EXTRA = r'''
namespace rclcpp {
struct Context { void init(int,const char *const*) {} bool is_valid() const {return true;} void shutdown(const char*) {} };
struct NodeOptions {
  NodeOptions &context(std::shared_ptr<Context>) {return *this;}
  NodeOptions &use_global_arguments(bool) {return *this;}
  NodeOptions &enable_rosout(bool) {return *this;}
  NodeOptions &start_parameter_services(bool) {return *this;}
  NodeOptions &start_parameter_event_publisher(bool) {return *this;}
  NodeOptions &use_intra_process_comms(bool) {return *this;}
};
struct ExecutorOptions {std::shared_ptr<Context> context;};
namespace executors { struct SingleThreadedExecutor {
  explicit SingleThreadedExecutor(ExecutorOptions) {}
  void add_node(std::shared_ptr<Node>) {} void remove_node(std::shared_ptr<Node>) {}
  template<class Duration> void spin_once(Duration) {}
}; }
}
'''


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:
        pytest.skip('No C++17 compiler; no real-header compilation claimed')
    root=tmp_path_factory.mktemp('passive-collector-contract')
    stub=STUB.replace('bool armed=false;', 'bool armed=false; bool flying=false;')
    (root/'contract.hpp').write_text(stub)
    for name in ('ardupilot_msgs/msg/status.hpp','nav_msgs/msg/odometry.hpp',
                 'rclcpp/rclcpp.hpp','rclcpp/message_info.hpp','rmw/types.h'):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('#include "contract.hpp"\n')
    flags=[compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic','-pthread','-I',str(root),'-I',str(ROOT)]
    (root/'harness.cpp').write_text(HARNESS)
    built=subprocess.run([*flags,str(root/'harness.cpp'),'-o',str(root/'harness')],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stderr
    # Adapt the fake Node declaration to accept NodeOptions only for syntax check.
    stub=stub.replace('struct Node {','struct NodeOptions;\nstruct Node {\n  Node()=default;\n  Node(const char*, const NodeOptions&) {}')
    (root/'contract.hpp').write_text(stub+EXTRA)
    built=subprocess.run([*flags,'-fsyntax-only',str(ROOT/'tools/rover_passive_rclcpp/collector.cpp')],
                         capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stderr
    return root/'harness'


@pytest.mark.parametrize('mode',['normal','duration','interrupted','one_stream','incomplete',
                                 'start_failure','sample_failure','footer_failure','close_failure','invalid_limits','oversize_limit','zero_duration','nan_duration',
                                 'zero_gid','intra_process','missing_rmw','graph_unknown','late_poll'])
def test_bounded_core_and_uncertain_failures(compiled,mode):
    run=subprocess.run([str(compiled),mode],capture_output=True,text=True,timeout=5)
    assert run.returncode==0,run.stderr
    rows=[json.loads(line) for line in run.stdout.splitlines()]
    samples=[r for r in rows if r.get('event')=='sample']
    assert len(samples)<=2
    for row in rows:
        if 'status' in row:
            assert row['status']=='BLOCKED' and row['movement_authorized'] is False
            assert row['source_association_verified'] is False
            assert 'attributed_publisher_identity' not in row
    if mode=='normal':
        assert rows[0]=={'complete':True}
        assert samples[0]['message_publisher_gid'].startswith('07')
        assert samples[0]['graph']['candidates'][0]['endpoint_gid'].startswith('63')
        assert samples[0]['graph']['candidates'][0]['node_name']=='graph-"candidate\n'
        assert rows[-1]['capture_complete'] is None # file alone never claims confirmed close
    elif mode in ('duration','interrupted','one_stream','incomplete','zero_gid','intra_process','missing_rmw','graph_unknown','late_poll'):
        assert rows[0]=={'complete':False}


def test_private_exclusive_file_and_no_symlinks(compiled,tmp_path):
    private=tmp_path/'private';private.mkdir(mode=0o700)
    output=private/'samples.jsonl'
    def run(mode,path):
        done=subprocess.run([str(compiled),mode,str(path)],capture_output=True,text=True,timeout=5)
        assert done.returncode==0,done.stderr
    run('file',output)
    original=output.read_bytes()
    assert stat.S_IMODE(output.stat().st_mode)==0o600
    run('file_reject',output)
    assert output.read_bytes()==original
    link=private/'link';link.symlink_to(output)
    run('file_reject',link)
    alias=tmp_path/'alias';alias.symlink_to(private,target_is_directory=True)
    run('file_reject',alias/'new.jsonl')
    run('file_reject',Path('relative.jsonl'))
    public=tmp_path/'public';public.mkdir(mode=0o755)
    run('file_reject',public/'new.jsonl')
    assert not (public/'new.jsonl').exists()

# Fault injection at the POSIX boundary, not a replacement Journal implementation.
# Only this temporary stdlib-only test helper is executed; collector.cpp is not.
JOURNAL_HARNESS = r'''
#include <cerrno>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cassert>
int writes=0, syncs=0;
std::string mode;
bool fail_close=false;
ssize_t test_write(int fd,const void *data,size_t length) {
  ++writes;
  if(mode=="write_error" || (mode=="partial_error" && writes==2)) {errno=ENOSPC;return -1;}
  if((mode=="partial_ok" || mode=="partial_error") && writes==1) length=3;
  return ::write(fd,data,length);
}
int test_fsync(int fd) {
  ++syncs;
  int fail=0;
  if(mode=="file_sync_error") fail=1;
  if(mode=="parent_sync_error") fail=2;
  if(mode=="final_sync_error") fail=3;
  if(mode=="final_parent_sync_error") fail=4;
  if(syncs==fail) {errno=EIO;return -1;}
  return ::fsync(fd);
}
int test_close(int fd) {
  const int result=::close(fd);
  if(fail_close) {errno=EIO;return -1;}
  return result;
}
#define write test_write
#define fsync test_fsync
#define close test_close
#include "tools/rover_passive_rclcpp/private_journal.hpp"
#undef write
#undef fsync
#undef close
int main(int argc,char **argv) {
  assert(argc==3); mode=argv[1]; bool threw=false, finished=false;
  {
    tfg::rover_passive::PrivateJournal journal(argv[2]);
    try {
      journal.append("{\"status\":\"BLOCKED\",\"movement_authorized\":false}");
      fail_close=(mode=="close_error");
      journal.finish(); finished=true;
    } catch(...) {threw=true;}
    if(mode=="partial_ok") assert(!threw && finished && writes==2 && syncs==4);
    else assert(threw && !finished);
    if(mode=="write_error") assert(writes==1 && syncs==0);
    if(mode=="partial_error") assert(writes==2 && syncs==0);
    if(mode=="file_sync_error") assert(writes==1 && syncs==1);
    if(mode=="parent_sync_error") assert(writes==1 && syncs==2);
    if(mode=="final_sync_error") assert(writes==1 && syncs==3);
    if(mode=="final_parent_sync_error") assert(writes==1 && syncs==4);
    if(mode=="close_error") assert(writes==1 && syncs==3);
  }
}
'''


@pytest.fixture(scope='module')
def journal_binary(tmp_path_factory):
    compiler=shutil.which('c++')
    if not compiler:
        pytest.skip('No C++17 compiler; no ROS check claimed')
    root=tmp_path_factory.mktemp('private-journal-syscalls')
    source=root/'test.cpp'; source.write_text(JOURNAL_HARNESS)
    binary=root/'test'
    build=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pedantic',
                          '-I',str(ROOT),str(source),'-o',str(binary)],
                         capture_output=True,text=True,timeout=30)
    assert build.returncode==0,build.stderr
    return binary


@pytest.mark.parametrize('mode',['partial_ok','partial_error','write_error','file_sync_error',
                                 'parent_sync_error','final_sync_error','final_parent_sync_error','close_error'])
def test_real_journal_syscall_failures_stop_without_retry(journal_binary,tmp_path,mode):
    private=tmp_path/'private';private.mkdir(mode=0o700)
    output=private/'samples.jsonl'
    done=subprocess.run([str(journal_binary),mode,str(output)],capture_output=True,text=True,timeout=5)
    assert done.returncode==0,done.stderr
    assert stat.S_IMODE(output.stat().st_mode)==0o600
    contents=output.read_bytes()
    if mode=='write_error':
        assert contents==b''
    elif mode=='partial_error':
        assert contents==b'{"s' # exact partial bytes retained; no truncation/repair
    else:
        row=json.loads(contents)
        assert row=={'status':'BLOCKED','movement_authorized':False}
        assert 'capture_complete' not in row
