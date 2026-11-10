"""Synthetic pipes/proc/processes only; never queries the current SDK or /proc."""
import base64
import hashlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from tools.rover_xrce_trace import monitor as m, socket_inventory as s, selection
from tests.test_rover_socket_inventory import tree, write_trace, FixtureClock
from tests.test_rover_diagnostic_selection import artifacts, overlay, candidate


def recorder(tmp_path, runner):
    value={'lifecycle_id':'trial','manifest':{'engine_id':'e','container_id':'c','image_id':'i'}}
    root={'pid':100,'start_ticks':10,'boot_id':'boot'}
    agent={'pid':300,'start_ticks':30,'boot_id':'boot',
           'executable':'/usr/bin/micro_ros_agent','native_byte_order':'little'}
    write_trace(tmp_path,agent)
    return m.SocketRecorder(tmp_path,value,runner=runner),root,agent


def reply(**kw):
    return NS(returncode=0,stderr=b'synthetic diagnostic\n',stdout=json.dumps({
        'schema':'tfg.xrce-sockets/1','status':'BLOCKED',
        'movement_authorized':False,'source_association_verified':False,
        'context_declared_by_protected_monitor':json.loads(kw['input']),
        'snapshot_state':'REPEATED_READS_AGREE'}).encode())


def decoded(stream):
    return base64.b64decode(stream['prefix_base64'],validate=True)


def test_existing_cli_with_synthetic_proc_through_monitor_and_persistence(tree,tmp_path,monkeypatch):
    proc,_=tree;real_collect=s.collect;calls=[]
    monkeypatch.setenv('TFG_SIM_PROJECT','Agentic_Drone_Mission_Control')
    # Same entry point and pipe protocol as the monitor, fake proc root only.
    monkeypatch.setattr(s,'collect',lambda expected,**kw:real_collect(expected,reader=s.Reader(proc,clock=FixtureClock()),**kw))
    def runner(args,**kw):
        calls.append((args,kw));out=io.BytesIO();err=io.BytesIO()
        with monkeypatch.context() as patch:
            patch.setattr(s.sys,'stdin',NS(buffer=io.BytesIO(kw['input'])))
            patch.setattr(s.sys,'stdout',NS(buffer=out))
            patch.setattr(s.sys,'stderr',NS(buffer=err))
            assert s.main()==0
        return NS(returncode=0,stdout=out.getvalue(),stderr=err.getvalue())
    rec,root,agent=recorder(tmp_path,runner);rec.sample(root,agent,0);rec.close()
    assert rec.count==1 and not rec.failed
    wire=json.loads((tmp_path/'capture/sockets.jsonl').read_bytes())
    row=s.validate_inventory(s.unpack_inventory(wire))
    assert row['snapshot_state']=='REPEATED_READS_AGREE'
    assert row['table_scope_before']['read_completion']=='EOF_OBSERVED'
    diag=rec.summary()['query_diagnostic']
    assert diag['stage']=='PERSISTED' and diag['persisted'] and diag['return_code']==0
    stages=[json.loads(line)['stage'] for line in decoded(diag['stderr']).splitlines()]
    assert stages==['INPUT','COLLECT','READS_FINISHED','COLLECT_RETURNED','OUTPUT','OUTPUT_FLUSHED']
    assert not diag['stderr']['truncated']
    assert diag['input_sha256']==hashlib.sha256(calls[0][1]['input']).hexdigest()
    assert diag['context']==row['context_declared_by_protected_monitor']
    assert calls[0][1]['timeout']==m.SOCKET.query_timeout_s==.75
    assert 'env' not in calls[0][1]  # existing inheritance, no transport change


@pytest.mark.parametrize('last_stage',['INPUT','COLLECT','READS_FINISHED','COLLECT_RETURNED','OUTPUT','OUTPUT_FLUSHED'])
def test_query_timeout_preserves_partial_pipes_and_does_not_claim_persistence(tmp_path,last_stage):
    partial=b'{"partial":';stderr=json.dumps({'stage':last_stage}).encode()+b'\n'
    def runner(argv,**kw):
        raise subprocess.TimeoutExpired(argv,kw['timeout'],output=partial,stderr=stderr)
    rec,root,agent=recorder(tmp_path,runner)
    rec.sample(root,agent,0);rec.sample(root,agent,10);rec.close()
    d=rec.summary()['query_diagnostic']
    assert d['failure']['stage']=='QUERY' and d['failure']['class']=='TimeoutExpired'
    assert d['return_code'] is None and not d['persisted']
    assert decoded(d['stdout'])==partial and decoded(d['stderr'])==stderr
    assert not d['stdout']['complete_pipe_observed'] and not d['stderr']['complete_pipe_observed']
    assert rec.count==0 and not (tmp_path/'capture/sockets.jsonl').read_bytes()
    assert rec.failed=='TimeoutExpired:SOCKET_QUERY_OR_PERSISTENCE_UNCERTAIN'
    assert list(d['stage_elapsed_s'])==['PREPARE_CONTEXT','OPEN_JOURNAL','QUERY']


@pytest.mark.parametrize('failure',['write','flush','fsync'])
def test_persistence_failure_retains_successful_query_and_initial_failure(tmp_path,monkeypatch,failure):
    calls=[]
    def runner(*a,**kw):calls.append(1);return reply(**kw)
    rec,root,agent=recorder(tmp_path,runner)
    with (tmp_path/'probe').open('w+b') as probe:
        output=Mock(wraps=probe);output.fileno.return_value=probe.fileno()
        if failure=='fsync':monkeypatch.setattr(m.os,'fsync',Mock(side_effect=OSError(5,'synthetic fsync failure')))
        else:getattr(output,failure).side_effect=OSError(5,'synthetic persistence failure')
        rec.output=output;rec.sample(root,agent,0)
        before=json.loads(json.dumps(rec.summary()['query_diagnostic']))
        rec.sample(root,agent,10);rec.close()
        d=rec.summary()['query_diagnostic']
        assert d['failure']['stage']=='PERSIST_'+failure.upper()
        assert d['failure']==before['failure'] and d['return_code']==0 and not d['persisted']
        assert decoded(d['stderr'])==b'synthetic diagnostic\n'
        assert calls==[1] and rec.count==0
        if failure!='write':assert d['close_error']['class']=='OSError'


def test_nonzero_child_retains_diagnostics_without_parsing_a_row(tmp_path):
    rec,root,agent=recorder(tmp_path,lambda *a,**kw:NS(returncode=2,stdout=b'partial',stderr=b'synthetic traceback'))
    rec.sample(root,agent,0);rec.close();d=rec.summary()['query_diagnostic']
    assert d['return_code']==2 and d['failure']['stage']=='VALIDATE_QUERY'
    assert decoded(d['stderr'])==b'synthetic traceback' and not d['persisted']
    assert rec.count==0


def test_pipe_diagnostic_is_bounded_hashed_and_explicitly_truncated(tmp_path):
    raw=b'x'*5000
    def runner(a,**kw):raise subprocess.TimeoutExpired(a,.75,output=raw,stderr=raw)
    rec,root,agent=recorder(tmp_path,runner);rec.sample(root,agent,0);rec.close()
    d=rec.summary()['query_diagnostic']
    for key in ('stdout','stderr'):
        assert decoded(d[key])==raw[:2048] and d[key]['available_bytes']==5000
        assert d[key]['sha256']==hashlib.sha256(raw).hexdigest() and d[key]['truncated']
    assert len(json.dumps(d).encode())<m.SOCKET.row_bytes


def test_close_error_cannot_erase_query_timeout_diagnostic(tmp_path):
    def runner(a,**kw):raise subprocess.TimeoutExpired(a,.75,stderr=b'last child stage')
    rec,root,agent=recorder(tmp_path,runner);rec.sample(root,agent,0)
    rec.output.close();rec.output=Mock();rec.output.flush.side_effect=OSError(5,'synthetic close failure')
    rec.close();d=rec.summary()['query_diagnostic']
    assert rec.failed=='TimeoutExpired:SOCKET_QUERY_OR_PERSISTENCE_UNCERTAIN'
    assert d['failure']['stage']=='QUERY' and decoded(d['stderr'])==b'last child stage'
    assert d['close_error']['errno']==5


def test_monitor_closes_core_with_failed_socket_channel_and_keeps_diagnosis(artifacts,tmp_path,monkeypatch):
    value,prefix=overlay(artifacts);source=tmp_path/'launch.log';source.write_bytes(b'TFG_XRCE_TRACE {}\n')
    root=dict(pid=9,ppid=1,start_ticks=90,boot_id='boot');selection.atomic_record(prefix/'launch.json',{'process':root})
    def runner(a,**kw):raise subprocess.TimeoutExpired(a,.75,stderr=b'synthetic COLLECT stage')
    rec,rr,aa=recorder(tmp_path/'socket-channel',runner);rec.sample(rr,aa,0)
    monkeypatch.setattr(m,'SocketRecorder',lambda *a,**kw:rec)
    monkeypatch.setattr(m,'SOURCE',source);monkeypatch.setenv('TFG_SIM_PROJECT','Agentic_Drone_Mission_Control')
    handlers={};clock=[0.]
    monkeypatch.setattr(m.signal,'signal',lambda sig,fn:handlers.__setitem__(sig,fn))
    monkeypatch.setattr(m.time,'monotonic',lambda:clock[0])
    def sleep(seconds):
        clock[0]+=seconds
        if clock[0]>1:handlers[m.signal.SIGINT]()
    monkeypatch.setattr(m.time,'sleep',sleep)
    monkeypatch.setattr(m,'process',lambda pid:candidate(value) if pid==10 else {**root,'pid':pid})
    monkeypatch.setattr(m,'root_alive',lambda root:clock[0]<=1)
    monkeypatch.setattr(m,'agents',lambda:[] if clock[0]>1 else [candidate(value)])
    monkeypatch.setattr(m,'verify_agent',lambda *a,**kw:candidate(value))
    monkeypatch.setattr(m,'launch_candidates',lambda root:m.agents())
    assert m.run(prefix)==1
    report=selection.read_json(prefix/'capture/monitor.json')
    assert report['phase']=='CLOSED' and report['core_capture_complete']
    assert not report['socket_capture_complete'] and not report['capture_complete']
    d=report['socket_inventory']['query_diagnostic']
    assert d['failure']['stage']=='QUERY' and decoded(d['stderr'])==b'synthetic COLLECT stage'
    assert not report['source_association_verified'] and not report['movement_authorized']
