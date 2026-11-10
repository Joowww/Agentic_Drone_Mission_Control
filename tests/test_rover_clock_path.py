"""Synthetic arithmetic and exact pinned send method; no SDK or middleware."""
from pathlib import Path
import io,json,subprocess
import pytest
from tools.rover_xrce_trace.prepare_timing import patch_json,patch_plugin
from tools.rover_xrce_trace.monitor import Drain

ROOT=Path(__file__).resolve().parents[1]
JSON_SOURCE=ROOT/'evaluation/operations/rover_status_diagnostic_build_2026_10_31/c29d228d-3170-49ca-a0cb-b93b5874b9f8/source/ardupilot/libraries/SITL/SIM_JSON.cpp'


def test_clock_window_local_spans_and_explicit_invalidity(tmp_path):
    cpp=r'''
#include "timing_fields.hpp"
#include <cassert>
#include <iostream>
int main(){
 errno=EAGAIN;assert(tfg_timing::now()>0);assert(errno==EAGAIN);
 tfg_timing::Window w;w.observe(100,1000);assert(!w.due());
 w.active[2]=1001;w.spans[1].add(1000,1200,40);w.spans[2].add(1200,2200,-1);
 w.spans[2].add(2200,2300,80);w.observe(200,10000001000ULL);assert(w.due());assert(!w.due());
 assert(w.spans[2].total==1100&&w.spans[2].maximum==1000&&w.spans[2].nonpositive==1);
 w.spans[0].add(1000,1200,1);w.spans[3].add(1200,2300,1);
 std::cout<<"{"<<tfg_timing::fields(w)<<"}";w.observe(199,10000002000ULL);assert(w.invalid);
}'''
    src=tmp_path/'main.cpp';src.write_text(cpp)
    cmd=['c++','-std=c++17','-fno-exceptions','-I',str(ROOT/'tools/rover_identity_probe'),str(src),'-o',str(tmp_path/'test')]
    c=subprocess.run(cmd,capture_output=True);assert c.returncode==0,c.stderr.decode()
    r=subprocess.run([str(tmp_path/'test')],capture_output=True);assert r.returncode==0,r.stderr.decode()
    row=json.loads(r.stdout);assert row['sim_pair_ns']==[100,200]
    assert row['mono_pair_ns']==[1000,10000001000] and row['active_ns'][2]==1001
    assert row['spans'][0][-1] is None and row['spans'][3][-1] is None
    assert row['spans'][1][-1]==40 and row['spans'][2][-1]==80
    assert not row['incomplete']


def test_pinned_json_preserves_sends_errors_and_original_results(tmp_path):
    original=JSON_SOURCE.read_text();instrumented=patch_json(original)
    with pytest.raises(ValueError,match='Unreviewed'):patch_json(original+'\n')
    assert instrumented.count('timed_json_recv(sock,')==2
    outputs=[]
    for name,text in [('original',original),('instrumented',instrumented)]:
        start=text.index('void JSON::output_servos(');end=text.index('/*',start)
        method=text[start:end]
        prefix=r'''
#include "timing_window.hpp"
#include <cstdio>
#include <cstring>
#include <iostream>
bool json_timing_on=true;tfg_timing::Window json_timing_window;
namespace SRV_Channels{bool more=false;bool have_32_channels(){return more;}}
struct sitl_input{unsigned short servos[32]{};};
struct JSON {
 struct servo_packet_16{unsigned short magic=18458,frame_rate;unsigned frame_count;unsigned short pwm[16];};
 struct servo_packet_32{unsigned short magic=29569,frame_rate;unsigned frame_count;unsigned short pwm[32];};
 int rate_hz=400;unsigned frame_counter=7;const char*target_ip="127.0.0.1";unsigned control_port=9022;
 struct Socket{int value=0;int sendto(void*b,size_t n,const char*,unsigned){
  auto*p=static_cast<unsigned char*>(b);std::cout<<n<<":";for(unsigned i=0;i<n;++i)std::cout<<unsigned(p[i])<<",";
  errno=EAGAIN;return value;
 }}sock;
 void output_servos(const sitl_input&);
};
'''
        suffix=r'''int main(){JSON j;sitl_input in;for(unsigned i=0;i<32;++i)in.servos[i]=1500+i;
 for(bool more:{false,true})for(int result:{-1,0,12,40,72}){SRV_Channels::more=more;j.sock.value=result;j.output_servos(in);std::cout<<" errno="<<errno<<"\n";}}'''
        src=tmp_path/(name+'.cpp');src.write_text(prefix+method+suffix)
        c=subprocess.run(['c++','-std=c++17','-fno-exceptions','-I',str(ROOT/'tools/rover_identity_probe'),str(src),'-o',str(tmp_path/name)],capture_output=True)
        assert c.returncode==0,c.stderr.decode()
        r=subprocess.run([str(tmp_path/name)],capture_output=True);assert r.returncode==0
        outputs.append((r.stdout,r.stderr))
    assert outputs[0]==outputs[1]


@pytest.mark.parametrize('event,prefix',[('status_limit','TFG_IDENTITY_TRACE'),('trace_limit','TFG_XRCE_TRACE'),('limit','TFG_MODEL_TRACE')])
def test_cap_flag_is_partial_and_raw_record_survives(tmp_path,event,prefix):
    raw=(prefix+' '+json.dumps({'schema':'tfg.model-source/1' if prefix=='TFG_MODEL_TRACE' else 'tfg.identity-trace/1','event':event,'incomplete':True,'movement_authorized':False})+'\n').encode()
    with (tmp_path/'log').open('xb') as f:
        d=Drain(f);d.feed(raw);d.finish()
    assert d.cap_reached and d.errors and (tmp_path/'log').read_bytes()==raw


@pytest.mark.parametrize('loss',['timing_lost','lost','diagnostic_lost'])
def test_timing_loss_cannot_be_complete(tmp_path,loss):
    raw=('TFG_MODEL_TRACE '+json.dumps({'schema':'tfg.model-source/1','event':'timing_window',loss:1,'movement_authorized':False})+'\n').encode()
    with (tmp_path/'log').open('xb') as f:
        d=Drain(f);d.feed(raw);d.finish()
    assert d.errors and not d.cap_reached


def test_monitor_aggregate_cap_requests_partial_close(tmp_path):
    from tools.rover_xrce_trace.monitor import TRACE_LIMIT
    with (tmp_path/'log').open('xb') as f:
        d=Drain(f);d.records=TRACE_LIMIT
        d.feed(b'TFG_IDENTITY_TRACE {"event":"synthetic"}\n');d.finish()
    assert d.cap_reached and 'Diagnostic output cap reached' in d.errors


def test_plugin_reports_inflight_wait_without_renewing_sim_time_pair(tmp_path,monkeypatch):
    import shutil
    monkeypatch.setenv('TFG_STATUS_DIAGNOSTIC','11111111-1111-4111-8111-111111111111')
    shutil.copyfile(ROOT/'tools/rover_xrce_trace/model_probe/model_timing.hpp',tmp_path/'model_timing.hpp')
    (tmp_path/'model_trace.hpp').write_text(r'''
#pragma once
#include <atomic>
#include <mutex>
#include <map>
#include <chrono>
#include <string>
#include <cstdlib>
#include <iostream>
namespace tfg_xrce_trace{inline std::string quote(const std::string&s){return "\""+s+"\"";}}
namespace tfg_model_trace{
struct Bound{};inline bool enabled(){return true;}
inline std::mutex&mutex(){static std::mutex m;return m;}
inline std::map<const void*,Bound>&bindings(){static std::map<const void*,Bound>b;return b;}
inline std::string context(const Bound&){return "\"fixture\":\"SYNTHETIC_NO_GAZEBO\"";}
inline void emit(const std::string&s){std::cout<<"{"<<s<<"}\n";}
inline std::string socket_fields(int){return "\"socket_observation\":null";}
}
''')
    (tmp_path/'status_diagnostic.hpp').write_text(r'''
#pragma once
namespace tfg_status{
inline std::string ns(const char*){return "SYNTHETIC_TIME_NAMESPACE";}
struct Diagnostic{static Diagnostic&instance(const char*){static Diagnostic d;return d;}void poll_markers(){}bool requested(){return std::getenv("SYNTHETIC_REQUEST_READY");}};
}
''')
    (tmp_path/'main.cpp').write_text(r'''
#include "model_timing.hpp"
int main(){int owner;
 auto*e=tfg_model_timing::entry(&owner);e->lockstep=true;
 e->window.observe(1230000000,1000);e->window.active[0]=1000;
 e->window.spans[1].add(2000,10000000000ULL,-1);
 tfg_model_trace::bindings()[&owner]={};
 tfg_model_timing::report(&owner,10000001000ULL); // no request: no output
 setenv("SYNTHETIC_REQUEST_READY","1",1);
 tfg_model_timing::report(&owner,10000001000ULL);
}
''')
    c=subprocess.run(['c++','-std=c++17','-pthread','-I',str(tmp_path),'-I',str(ROOT/'tools/rover_identity_probe'),str(tmp_path/'main.cpp'),'-o',str(tmp_path/'test')],capture_output=True)
    assert c.returncode==0,c.stderr.decode()
    r=subprocess.run([str(tmp_path/'test')],capture_output=True);assert r.returncode==0,r.stderr.decode()
    row=json.loads(r.stdout)
    assert row['mono_pair_ns']==[1000,1000] and row['sim_pair_ns']==[1230000000,1230000000]
    assert row['checkpoint_mono_ns']==10000001000
    assert row['active_ns'][0]==1000 and row['spans'][1][3]==1
    assert row['lockstep'] and row['timing_lost']==0
