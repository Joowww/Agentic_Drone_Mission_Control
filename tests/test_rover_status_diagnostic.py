"""Status-only offline tests. Native methods use explicit middleware doubles."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import time

import pytest

from tools.rover_xrce_trace.prepare_status import patch_ap, patch_agent

ROOT=Path(__file__).resolve().parents[1]
AP=Path('/home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot/libraries/AP_DDS/AP_DDS_Client.cpp')
OWNER='11111111-1111-4111-8111-111111111111'
CONTEXT='a'*64


def compile_frozen(directory,code,*,extra_flags=()):
    directory.mkdir(parents=True)
    for name in ('status_diagnostic.hpp','status_producer.hpp','status_producer_impl.hpp','status_producer.cpp','timing_window.hpp','timing_fields.hpp'):
        shutil.copyfile(ROOT/'tools/rover_identity_probe'/name,directory/name)
    (directory/'test.cpp').write_text(code)
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    argv=['c++','-std=c++17','-pthread','-Wall','-Wextra',*extra_flags,'-I',str(directory),
          str(directory/'test.cpp'),str(directory/'status_producer.cpp'),'-o',str(directory/'test')]
    r=subprocess.run(argv,capture_output=True)
    (directory/'build.stdout').write_bytes(r.stdout);(directory/'build.stderr').write_bytes(r.stderr)
    (directory/'build-command.json').write_text(json.dumps({'argv':argv,'returncode':r.returncode,'kind':'FROZEN_SOURCE_WITH_EXPLICIT_DOUBLES'},indent=2))
    assert r.returncode==0,r.stderr.decode()
    assert all(hashlib.sha256((directory/n).read_bytes()).hexdigest()==h for n,h in before.items())
    return directory/'test'


@pytest.fixture(scope='module')
def diagnostic_binary(tmp_path_factory):
    return compile_frozen(tmp_path_factory.mktemp('status-header')/'source',r'''
#include "status_diagnostic.hpp"
#include <cassert>
#include <iostream>
#include <signal.h>
int main(int argc,char**argv){
 assert(argc==3);std::string mode=argv[1];int dir=open(argv[2],O_RDONLY|O_DIRECTORY);
 int pipefd[2]{-1,-1};
 if(mode=="full"||mode=="broken"){assert(pipe(pipefd)==0);assert(dup2(pipefd[1],2)==2);close(pipefd[1]);}
 tfg_status::Diagnostic d("receiver","11111111-1111-4111-8111-111111111111",std::string(64,'a'),dir);
 assert(d.ready());assert(!(fcntl(2,F_GETFL)&O_NONBLOCK));
 if(mode=="full"){
  int fd=open("/proc/self/fd/2",O_WRONLY|O_NONBLOCK);char b[1024]{};unsigned count=0;
  while(write(fd,b,sizeof(b))>0){count+=sizeof(b);assert(count<=1024*1024);}
  assert(errno==EAGAIN);auto now=tfg_status::steady_ns();assert(!d.emit("test"));
  assert(tfg_status::steady_ns()-now<500000000);assert(!d.complete());assert(!(fcntl(2,F_GETFL)&O_NONBLOCK));
  close(fd);close(pipefd[0]);std::cout<<"FULL_NONBLOCKING";return 0;
 }
 if(mode=="broken"){
  signal(SIGPIPE,SIG_DFL);close(pipefd[0]);assert(!d.emit("test"));assert(!d.complete());
  std::cout<<"BROKEN_SURVIVED";return 0;
 }
 assert(d.create_marker(false));assert(!d.create_marker(false)); // never overwrite
 if(mode=="symlink"){assert(symlink("status_request",(std::string(argv[2])+"/status_matched").c_str())==0);}
 else if(mode=="fifo"){assert(mkfifo((std::string(argv[2])+"/status_matched").c_str(),0600)==0);}
 else if(mode=="valid"||mode=="limit"||mode=="graph"){assert(d.create_marker(true));}
 else {
  int fd=openat(dir,"status_matched",O_CREAT|O_EXCL|O_WRONLY,0600);
  std::string owner=mode=="owner"?"22222222-2222-4222-8222-222222222222":"11111111-1111-4111-8111-111111111111";
  auto ticks=tfg_status::ticks(getpid())+(mode=="pid"?1:0);
  auto data=owner+" "+std::string(64,mode=="context"?'b':'a')+" "+std::to_string(getpid())+" "+
   std::to_string(ticks)+" "+tfg_status::boot()+"\n";
  if(mode=="truncated")data.resize(40);
  assert(write(fd,data.data(),data.size())==ssize_t(data.size()));close(fd);
 }
 d.poll_markers();assert(d.requested());
 bool valid=mode=="valid"||mode=="limit"||mode=="graph";
 assert(d.matched()==valid);assert(d.complete()==valid);
 if(mode=="graph"){assert(d.graph_snapshot("{\"state\":\"OBSERVED\"}"));assert(!d.graph_snapshot("{}"));}
 if(mode=="limit")for(int i=0;i<1000;++i)d.emit("test");
 d.finish();std::cout<<"MATCHED="<<d.matched()<<" COMPLETE="<<d.complete();
}''')


@pytest.mark.parametrize('mode',['valid','owner','context','pid','symlink','fifo','truncated','limit','full','broken','graph'])
def test_real_pipes_markers_limits_and_failures(diagnostic_binary,tmp_path,mode):
    directory=tmp_path/'capture';directory.mkdir(mode=0o700)
    r=subprocess.run([str(diagnostic_binary),mode,str(directory)],capture_output=True,timeout=3)
    assert r.returncode==0,r.stderr.decode()
    assert len(r.stderr)<=4096
    if mode=='valid':
        rows=[json.loads(line.split(b' ',1)[1]) for line in r.stderr.splitlines()]
        assert [v['event'] for v in rows]==['status_context','status_request_seen','status_match_seen','status_summary']
        assert rows[-1]['complete'] and all(v['lost']==0 for v in rows)
    if mode=='limit':
        rows=[json.loads(line.split(b' ',1)[1]) for line in r.stderr.splitlines()]
        assert any(v['event']=='status_limit' and v['incomplete'] for v in rows)
        assert rows[-1]['lost']>0 and not rows[-1]['complete']
    if mode=='graph':
        g=json.loads((directory/'status-discovery.json').read_text())
        assert g['owner']==OWNER and g['context_sha256']==CONTEXT


AP_STUB=r'''
#include "status_producer.hpp"
#include <cstdint>
#include <iostream>
#define AP_DDS_CLOCK_SUB_ENABLED 1
#define WITH_SEMAPHORE(x)
struct builtin_interfaces_msg_Time{int32_t sec=0;uint32_t nanosec=0;};
struct ardupilot_msgs_msg_Status{
 enum{FS_RADIO=1,FS_BATTERY=2,FS_GCS=3,FS_EKF=4};
 struct {builtin_interfaces_msg_Time stamp;}header;
 uint8_t vehicle_type=0,mode=0;bool armed=false,flying=false,external_control=false;
 uint8_t failsafe[10]{};unsigned failsafe_size=0;
};
using Status=ardupilot_msgs_msg_Status;
unsigned long long ap_ms=0;unsigned mode_value=0;
namespace AP_HAL{uint64_t millis64(){return ap_ms;}uint64_t micros64(){return ap_ms*1000;}}
struct Vehicle{int get_mode()const{return mode_value;}bool get_likely_flying()const{return false;}};
struct Battery{bool has_failsafed()const{return false;}};
struct RTC{bool get_utc_usec(uint64_t&)const{return false;}};
namespace AP{Vehicle*vehicle(){static Vehicle v;return &v;}Battery&battery(){static Battery b;return b;}
 struct FW{int vehicle_type=1;};FW&fwversion(){static FW f;return f;}RTC&rtc(){static RTC r;return r;}}
struct RC{bool in_rc_failsafe()const{return false;}};RC&rc(){static RC r;return r;}
namespace AP_Notify{struct Flags{bool failsafe_gcs=false,failsafe_ekf=false;}flags;}
struct Utility{bool get_soft_armed()const{return false;}};struct HAL{Utility*util;}hal{new Utility};
constexpr uint16_t DELAY_STATUS_TOPIC_MS=100;
unsigned prepare_count=0,serialize_count=0;bool serialize_ok=false;
struct ucdrBuffer{};struct Obj{unsigned id=14;};struct Topic{Obj dw_id;};
enum class TopicIndex{STATUS_PUB};unsigned to_underlying(TopicIndex){return 0;}
unsigned ardupilot_msgs_msg_Status_size_of_topic(Status*,int){return 32;}
uint16_t uxr_prepare_output_stream(void*,int,Obj,ucdrBuffer*,unsigned){++prepare_count;return prepare_count%2?0:17;}
bool ardupilot_msgs_msg_Status_serialize_topic(ucdrBuffer*,Status*){++serialize_count;return serialize_ok;}
struct AP_DDS_Client{
 bool connected=true,has_received_clock=false;builtin_interfaces_msg_Time external_clock_time;
 Status last_status_msg_,status_topic;uint64_t last_status_publish_time_ms=0,last_status_check_time_ms=0;
 int csem=0,reliable_out=0,session=0;Topic topics[1];
 void update_topic(builtin_interfaces_msg_Time&);bool update_topic(Status&);void write_status_topic();
 void tick(uint64_t cur_time_ms);
};
'''


def extract(text,start,end):
    return text[text.index(start):text.index(end,text.index(start))]


def test_exact_ap_methods_preserve_gates_payloads_and_failed_calls(tmp_path):
    if not AP.is_file():pytest.skip('Installed AP_DDS source unavailable on this machine')
    original=AP.read_text();patched=patch_ap(original)
    outputs=[]
    for label,text in [('original',original),('instrumented',patched)]:
        macro='#define TFG_STATUS(call) do {} while(0)\n#define TFG_STATUS_NOW() 0\n' if label=='original' else '#define TFG_STATUS(call) tfg_status::Producer::call\n#define TFG_STATUS_NOW() tfg_status::Producer::now()\n'
        methods=extract(text,'void AP_DDS_Client::update_topic(builtin_interfaces_msg_Time& msg)','#endif // AP_DDS_TIME_PUB_ENABLED')
        methods+=extract(text,'bool AP_DDS_Client::update_topic(ardupilot_msgs_msg_Status& msg)','#endif // AP_DDS_STATUS_PUB_ENABLED')
        methods+=extract(text,'void AP_DDS_Client::write_status_topic()','#endif // AP_DDS_STATUS_PUB_ENABLED')
        update=text[text.index('void AP_DDS_Client::update()'):]
        branch=extract(update,'    if (cur_time_ms - last_status_check_time_ms > DELAY_STATUS_TOPIC_MS) {','#endif // AP_DDS_STATUS_PUB_ENABLED')
        code=AP_STUB+macro+methods+'void AP_DDS_Client::tick(uint64_t cur_time_ms){'+branch+'}\n'
        code+=r'''int main(){AP_DDS_Client c;for(unsigned t=0;t<3000;t+=37){
 ap_ms=t;mode_value=t>1300?15:0;serialize_ok=t%2;c.connected=t%3;
 c.has_received_clock=t>2000;c.external_clock_time.sec=123;
 c.tick(t);auto&m=c.status_topic;
 std::cout<<t<<" "<<c.last_status_check_time_ms<<" "<<c.last_status_publish_time_ms<<" "
 <<unsigned(m.mode)<<" "<<m.armed<<" "<<m.external_control<<" "<<m.header.stamp.sec<<" "
 <<m.header.stamp.nanosec<<" "<<prepare_count<<" "<<serialize_count<<"\n";}}'''
        binary=compile_frozen(tmp_path/label,code)
        run=subprocess.run([str(binary)],capture_output=True,timeout=3)
        assert run.returncode==0,run.stderr.decode()
        outputs.append(run.stdout)
    assert outputs[0]==outputs[1]
    with pytest.raises(ValueError,match='differs'):patch_ap(original+'\n')


def test_exact_agent_write_preserves_false_and_exception(tmp_path):
    agent_source=Path('/home/joelm/TFG/ardupilot_ros2_ws/build/micro_ros_agent/agent/src/xrceagent/src/cpp/middleware/fastdds/FastDDSEntities.cpp')
    if not agent_source.is_file():pytest.skip('Built micro-ROS agent source unavailable on this machine')
    source=agent_source.read_text()
    text=patch_agent(source)
    body=extract(text,'bool FastDDSDataWriter::write(const std::vector<uint8_t>& data)','const fastdds::dds::DataWriter* FastDDSDataWriter::ptr()')
    prefix=r'''
#include "status_diagnostic.hpp"
#include <cassert>
#include <vector>
#include <stdexcept>
namespace tfg_xrce_trace{std::string hex(const unsigned char*,size_t){return "00";}}
struct Topic{const char*get_name(){throw std::runtime_error("synthetic diagnostic error");}};
struct Guid{struct{unsigned char value[12]{};}guidPrefix;struct{unsigned char value[4]{};}entityId;};
struct Writer{int calls=0;bool ok=false,fail=false;Topic t;Guid g;
 Topic*get_topic(){return &t;}const Guid&guid(){return g;}
 bool write(std::vector<uint8_t>*){++calls;if(fail)throw std::runtime_error("original write");return ok;}};
struct FastDDSDataWriter{Writer*ptr_;bool write(const std::vector<uint8_t>&);};
'''
    main=r'''int main(){setenv("TFG_STATUS_DIAGNOSTIC","synthetic",1);Writer w;FastDDSDataWriter d{&w};std::vector<uint8_t> b{1,2};
 assert(!d.write(b));assert(w.calls==1);w.ok=true;assert(d.write(b));assert(w.calls==2);
 w.fail=true;try{d.write(b);assert(false);}catch(const std::runtime_error&e){assert(std::string(e.what())=="original write");}
 assert(w.calls==3);}'''
    binary=compile_frozen(tmp_path/'agent',prefix+body+main)
    r=subprocess.run([str(binary)],capture_output=True,timeout=3)
    assert r.returncode==0,r.stderr.decode()


def test_same_native_main_real_pipes_and_consumer_status_mode(tmp_path):
    from tests.fixtures.rover_receiver_protocol_native import build
    from tools.rover_observation_stream import start_receiver
    import select
    binary=build(tmp_path/'native',source_root=ROOT)
    capture=tmp_path/'capture';capture.mkdir(mode=0o700)
    directory=os.open(capture,os.O_RDONLY|os.O_DIRECTORY)
    rd,writer=os.pipe();feedback,wr=os.pipe()
    env={**os.environ,'TFG_STATUS_DIAGNOSTIC':OWNER,'TFG_STATUS_DIAGNOSTIC_CONTEXT':CONTEXT,
         'TFG_STATUS_DIAGNOSTIC_FIXTURE_FD':str(directory),
         'TFG_SYNTHETIC_INPUT_FD':str(rd),'TFG_SYNTHETIC_FEEDBACK_FD':str(wr)}
    rows=[];events=[]
    def popen(argv,**kwargs):
        assert argv[-1]=='--status-availability' and '--rpc-metadata' not in argv
        return subprocess.Popen(argv,env=env,pass_fds=(rd,wr,directory),**kwargs)
    source=start_receiver(str(binary),hashlib.sha256(binary.read_bytes()).hexdigest(),OWNER,
        timeout_s=2,max_age_s=.5,journal=events.append,raw_sink=rows.append,popen=popen,
        rpc_metadata=False,probe_on_start=False,status_availability=True)
    os.close(rd);os.close(wr);os.close(directory)
    try:
        source._next(2)
        for c in 'TOTT':
            os.write(writer,c.encode());assert select.select([feedback],[],[],2)[0]
            assert os.read(feedback,1)==c.encode()
            while source.frames.ready(.02):source._next(1)
        assert source.counts['/ap/v3/status']==3
        source.close(timeout_s=2)
        assert source.close_result['return_code']==0 and source.closed
        raw=b''.join(rows)
        assert b'rpc_request' not in raw and b'selection_credit' not in raw
        diagnostics=[json.loads(line.split(b' ',1)[1]) for line in source.frames.stderr.splitlines()]
        assert sum(r['event']=='status_callback_enter' for r in diagnostics)==2
        assert sum(r['event']=='status_graph_exit' for r in diagnostics)==2
        assert any(r['event']=='status_subscription_requested' for r in diagnostics)
        assert any(r['event']=='status_match_query_return' for r in diagnostics)
        assert diagnostics[-1]['event']=='status_summary' and diagnostics[-1]['complete']
        assert (capture/'status_request').read_bytes()==(capture/'status_matched').read_bytes()
        graph=json.loads((capture/'status-discovery.json').read_text())
        assert graph['owner']==OWNER
        assert len(source.frames.stderr)<=4096
    finally:
        if source.frames.child.poll() is None:
            if not source.close_attempted:
                try:source.close(timeout_s=2)
                except Exception:pass
            source.frames.child.wait(timeout=3)
        os.close(writer);os.close(feedback)


@pytest.mark.parametrize('failure',[None,'query','close'])
def test_status_window_reserves_drain_and_keeps_initial_error(failure):
    from tools.rover_observation_stream import ObservationStream
    from tools.rover_xrce_trace.passive_trial import observe_status_window
    from types import SimpleNamespace
    class Clock:
        value=0.
        def monotonic(self):return self.value
    clock=Clock()
    source=object.__new__(ObservationStream)
    source.clock=clock;source.selection_mode='DIAGNOSTIC_SPACING_V1'
    source.max_age=.5;source.footer=None;source.close_result=None
    source.counts={'/ap/v3/status':0,'/rover1/odometry':0}
    def ready(timeout):
        clock.value+=timeout
        return failure=='query'
    source.frames=SimpleNamespace(ready=ready,child=SimpleNamespace(poll=lambda:None))
    source._live=lambda:None
    def next_row(timeout,closing=False):
        raise TimeoutError('synthetic query failure')
    source._next=next_row
    budgets=[]
    def close(*,timeout_s):
        budgets.append(timeout_s)
        clock.value+=2. # demonstrate a drain longer than one second
        if failure=='close':raise OSError('synthetic persistence failure')
        source.close_result={'return_code':0,'reader_closed':True}
    source.close=close
    result=observe_status_window(source,started_monotonic_s=0)
    assert budgets and budgets[0]>19.9
    assert result['source_qualified_for_pulse'] is False
    assert result['finished_monotonic_s']<=140.
    assert ('initial_error' in result)==(failure=='query')
    assert ('close_error' in result)==(failure=='close')
    assert result['status']==('DIAGNOSTIC_EVIDENCE_ONLY' if failure is None else 'UNCONFIRMED')


def test_producer_progress_keeps_previous_clock_without_renewing_it(tmp_path):
    binary=compile_frozen(tmp_path/'native',r'''
#include "status_producer.hpp"
#include "status_diagnostic.hpp"
#include <cassert>
#include <thread>
#include <iostream>
int main(int argc,char**argv){
 assert(argc==2);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);
 setenv("TFG_STATUS_DIAGNOSTIC","11111111-1111-4111-8111-111111111111",1);
 setenv("TFG_STATUS_DIAGNOSTIC_CONTEXT",std::string(64,'a').c_str(),1);
 setenv("TFG_STATUS_DIAGNOSTIC_FIXTURE_FD",std::to_string(fd).c_str(),1);
 auto& d=tfg_status::Diagnostic::instance("ap");assert(d.ready());
 assert(d.create_marker(false)&&d.create_marker(true));
 tfg_status::Producer::loop_enter();
 // Explicit synthetic AP_HAL reads and read brackets, not current evidence.
 for(int i=1;i<=6;++i)tfg_status::Producer::clock(i,100+i,200+i);
 std::this_thread::sleep_for(std::chrono::milliseconds(2020));
 tfg_status::Producer::loop_enter();d.finish();
 std::cout<<"EXPLICIT_SYNTHETIC_AP_HAL_READS";
}''',extra_flags=['-DTFG_STATUS_DIAGNOSTIC_FIXTURE=1'])
    directory=tmp_path/'capture';directory.mkdir(mode=0o700)
    r=subprocess.run([str(binary),str(directory)],capture_output=True,timeout=4)
    assert r.returncode==0 and r.stdout==b'EXPLICIT_SYNTHETIC_AP_HAL_READS'
    rows=[json.loads(line.split(b' ',1)[1]) for line in r.stderr.splitlines()]
    assert sum(v['event']=='status_ap_clock' for v in rows)==3
    last=[v for v in rows if v['event']=='status_update_enter'][-1]
    assert (last['previous_ap_ms'],last['previous_read_begin_ns'],last['previous_read_end_ns'])==(6,106,206)
    assert rows[-1]['complete'] and rows[-1]['lost']==0


@pytest.fixture
def status_overlay(tmp_path,monkeypatch):
    # All ELF and launch inputs in this fixture are explicitly SYNTHETIC.
    from tools.rover_xrce_trace import selection as s
    manifest=dict(schema=s.STATUS_SCHEMA,engine_id='SYNTHETIC',container_id='a'*64,image_id='sha256:'+'b'*64)
    for key in ('wrapper','library','bridge','bridge_library','model_library','rover'):
        p=tmp_path/key;p.write_bytes(b'\x7fELF SYNTHETIC '+key.encode())
        manifest[key+'_path']=str(p);manifest[key+'_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    sitl=tmp_path/'sitl.py';sitl.write_text('f"exec {command} "')
    wild=tmp_path/'wild.py';wild.write_text('"command": "ardurover"')
    manifest['sitl_launch_sha256']=hashlib.sha256(sitl.read_bytes()).hexdigest()
    manifest['wildthumper_launch_sha256']=hashlib.sha256(wild.read_bytes()).hexdigest()
    monkeypatch.setattr(s,'SITL_LAUNCH',sitl);monkeypatch.setattr(s,'WILDTHUMPER_LAUNCH',wild)
    monkeypatch.setattr(s,'STATUS_PAIR',tuple(manifest[k+'_sha256'] for k in ('wrapper','library')))
    monkeypatch.setattr(s,'STATUS_ROVER_SHA256',manifest['rover_sha256'])
    monkeypatch.setattr(s,'RPC_PREPARED_ARTIFACTS',tuple(manifest[k+'_sha256'] for k in ('wrapper','library','bridge','bridge_library')))
    monkeypatch.setattr(s,'MODEL_LIBRARY_SHA256',manifest['model_library_sha256'])
    monkeypatch.setattr(s,'ROOT',tmp_path/'overlay')
    info={'wrapper':(['libmicroxrcedds_agent.so.2.4'],[]),
          'library':(['librmw_fastrtps_shared_cpp.so'],['libmicroxrcedds_agent.so.2.4']),
          'bridge':(['libros_gz_bridge.so'],[]),'bridge_library':([],['libros_gz_bridge.so']),
          'model_library':(['libgz-sim8.so.8'],['libTFGArduPilotIdentity.so'])}
    return s.descriptor(manifest,OWNER),lambda path:dict(zip(('needed','soname'),info[Path(path).name]))


def test_status_selection_has_one_rover_slot_and_causal_context(status_overlay):
    from tools.rover_xrce_trace import selection as s
    value,elf=status_overlay
    s.prepare_overlay(value,elf_reader=elf)
    env,_=s.configure({s.ENV:json.dumps(value),'PATH':'installed','TFG_STATUS_DIAGNOSTIC_FIXTURE_FD':'99'})
    assert env['PATH']==value['prefix']+'/bin:installed'
    assert env['TFG_STATUS_DIAGNOSTIC']==OWNER
    assert env['TFG_STATUS_DIAGNOSTIC_CONTEXT']==value['selection_sha256']
    assert 'TFG_STATUS_DIAGNOSTIC_FIXTURE_FD' not in env
    assert (Path(value['prefix'])/'bin/ardurover').read_bytes()==Path(value['manifest']['rover_path']).read_bytes()
    assert list((Path(value['prefix'])/'bin').iterdir())==[Path(value['prefix'])/'bin/ardurover']
    assert s.read_json(Path(value['prefix'])/'selection.json')['movement_authorized'] is False
    normal,_=s.configure({'TFG_STATUS_DIAGNOSTIC':OWNER,'TFG_STATUS_DIAGNOSTIC_CONTEXT':'a'*64})
    assert not normal


@pytest.mark.parametrize('bad',['rover','launch','agent','shape','altered_overlay'])
def test_status_selection_rejects_wrong_associations(status_overlay,bad):
    from tools.rover_xrce_trace import selection as s
    value,elf=status_overlay
    if bad=='altered_overlay':
        s.prepare_overlay(value,elf_reader=elf)
        p=Path(value['prefix'])/'bin/ardurover';p.chmod(0o700);p.write_bytes(b'altered')
        with pytest.raises(ValueError):s.configure({s.ENV:json.dumps(value)})
        return
    if bad=='rover':value['manifest']['rover_sha256']='b'*64
    if bad=='launch':s.SITL_LAUNCH.write_text('changed lookup')
    if bad=='agent':value['manifest']['library_sha256']='c'*64
    if bad=='shape':value['manifest']['arbitrary_override']='yes'
    with pytest.raises(ValueError):s.prepare_overlay(value,elf_reader=elf)
    assert not Path(value['prefix']).exists()


def test_existing_agent_trace_opt_in_never_blocks_full_pipe(tmp_path):
    from tools.rover_xrce_trace.prepare_status import patch_trace
    directory=tmp_path/'source';directory.mkdir()
    (directory/'trace.hpp').write_text(patch_trace((ROOT/'tools/rover_xrce_trace/trace.hpp').read_text()))
    binary=compile_frozen(directory/'native',r'''
#include "../trace.hpp"
#include <cassert>
#include <fcntl.h>
#include <iostream>
int main(){
 int f[2];assert(pipe(f)==0);assert(dup2(f[1],2)==2);close(f[1]);
 setenv("TFG_STATUS_DIAGNOSTIC","EXPLICIT_SYNTHETIC",1);
 int out=open("/proc/self/fd/2",O_WRONLY|O_NONBLOCK);char b[1024]{};
 while(write(out,b,sizeof(b))>0){}
 assert(errno==EAGAIN);
 auto before=std::chrono::steady_clock::now();
 assert(tfg_xrce_trace::diagnostic_write("test",4)==-1);
 assert(std::chrono::steady_clock::now()-before<std::chrono::milliseconds(500));
 assert(!(fcntl(2,F_GETFL)&O_NONBLOCK));
 close(f[0]);close(out);std::cout<<"NONBLOCKING_SAME_PIPE";}''')
    run=subprocess.run([str(binary)],capture_output=True,timeout=2)
    assert run.returncode==0 and run.stdout==b'NONBLOCKING_SAME_PIPE'


@pytest.mark.parametrize('bad',[None,'review','window','receiver','source','build'])
def test_reader_selector_consumes_status_review_and_selects_same_route(status_overlay,tmp_path,bad):
    from tools.rover_xrce_trace import passive_trial as d,selection as s
    from tests.test_rover_transport_driver import REQUIRED
    from unittest.mock import Mock
    root=tmp_path/'repo';root.mkdir()
    required={'tools/rover_identity_probe/status_diagnostic.hpp','tools/rover_identity_probe/status_producer.hpp',
              'tools/rover_identity_probe/status_producer_impl.hpp','tools/rover_identity_probe/status_producer.cpp',
              'tools/rover_xrce_trace/prepare_status.py'}
    sources={}
    for name in [*REQUIRED,*required]:
        p=root/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text('EXPLICIT_SYNTHETIC')
        sources[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    agent=status_overlay[0]['manifest'];ap=root/'agent.json';ap.write_text(json.dumps(agent))
    binary={'path':'/tmp/synthetic/rover_observation_receiver','sha256':'a'*64}
    dependencies={'/opt/ros/humble/lib/SYNTHETIC.so':'b'*64}
    build={'schema':'tfg.rover-transport-build-review/1','fixture':'EXPLICIT_SYNTHETIC',
           'preparation_valid':True,'snapshot_unchanged':True,'artifacts':{'receiver':binary},
           'native_dependencies':dependencies,'contract':{'pure_cpp_contract':'PASSED',
             'dds_participant_created':False,'ros_initialized':False}}
    bp=root/'build.json';bp.write_text(json.dumps(build));bh=hashlib.sha256(bp.read_bytes()).hexdigest()
    review={'purpose':'STATUS_AVAILABILITY_ONLY','movement_authorized':False,
            'receiver_sha256':binary['sha256'],'agent_selection_sha256':s.digest(agent),
            'source_hashes':{name:sources[name] for name in required}}
    reader={'schema':'tfg.rover-transport-reader/1','prepared':True,'fixture':'EXPLICIT_SYNTHETIC',
            'agent_selection_sha256':s.digest(agent),'source_hashes':sources,'native_dependencies':dependencies,
            'max_samples':20,'duration_s':120,'max_wire_bytes':448*1024,'binary':binary,
            'status_window':dict(d.STATUS_WINDOW),'provenance':str(bp),'provenance_sha256':bh,
            'helper_review':{'status_source_review':review,'receiver_build_review_sha256':bh}}
    if bad=='review':del reader['helper_review']['status_source_review']
    if bad=='window':reader['status_window']['observation_s']=121.
    if bad=='receiver':review['receiver_sha256']='c'*64
    if bad=='source':review['source_hashes'][sorted(required)[0]]='d'*64
    if bad=='build':del reader['helper_review']['receiver_build_review_sha256']
    rp=root/'reader.json';rp.write_text(json.dumps(reader))
    if bad:
        with pytest.raises(ValueError):d.LocalPorts(root,root,ap,rp)
        return
    ports=d.LocalPorts(root,root,ap,rp);ports.command=Mock(return_value=0)
    assert ports.reader(OWNER)['executed']
    code=ports.command.call_args_list[-1].args[1]
    assert any('status_availability=True' in arg and 'stationary_limits=None' in arg for arg in code)


@pytest.mark.parametrize('status',[False,True])
def test_discovery_reservation_stays_inside_existing_aggregate(status):
    import io
    from tools.rover_xrce_trace.monitor import Drain,BYTE_LIMIT
    output=io.BytesIO();drain=Drain(output,status_diagnostic=status)
    assert drain.byte_limit+(32768 if status else 0)==BYTE_LIMIT
    drain.bytes=BYTE_LIMIT-32768
    row=b'TFG_IDENTITY_TRACE {"event":"EXPLICIT_SYNTHETIC"}\n'
    drain.feed(row)
    assert bool(output.getvalue()) is not status
    assert ('Diagnostic output cap reached' in drain.errors) is status
