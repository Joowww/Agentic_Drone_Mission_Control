"""Parent wait/persistence doubles and analysis of immutable historical data."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import subprocess

import pytest

from tests.test_rover_diagnostic_selection import artifacts,overlay
from tools.rover_xrce_trace import monitor as m,selection as s,socket_inventory as sockets


@pytest.mark.parametrize('return_code',[0,1,-15])
def test_retained_parent_records_actual_wait_even_after_startup(artifacts,monkeypatch,return_code):
    _,prefix=overlay(artifacts)
    identity={'pid':42,'start_ticks':90,'boot_id':'fixture'}
    child=NS(pid=42,wait=Mock(return_value=return_code),send_signal=Mock())
    spawn=Mock(return_value=child)
    monkeypatch.setattr(m.signal,'signal',lambda *a:None)
    assert m.supervise(prefix,popen=spawn,process_reader=lambda pid:identity)==return_code
    assert spawn.call_args.args[0][-2:]==['--observe-child',str(prefix)]
    child.wait.assert_called_once_with(timeout=m.DURATION)
    receipt=s.read_json(prefix/'capture/monitor_exit.json')
    assert receipt['pid']==42 and receipt['start_ticks']==90 and receipt['return_code']==return_code
    assert receipt['source']=='RETAINED_MONITOR_PARENT_POPEN_WAIT'
    assert s.read_json(prefix/'capture/monitor_supervisor.json')['phase']=='CHILD_REAPED'


@pytest.mark.parametrize('failure',['wait','exit_write','finish_write'])
def test_wait_and_partial_persistence_are_uncertain_no_restart(artifacts,monkeypatch,failure):
    _,prefix=overlay(artifacts)
    child=NS(pid=42,wait=Mock(return_value=0),send_signal=Mock())
    if failure=='wait':child.wait.side_effect=subprocess.TimeoutExpired('fixture',600)
    def persist(path,value):
        if failure=='exit_write' and path.name=='monitor_exit.json':raise OSError('fixture fsync failure')
        if failure=='finish_write' and value.get('phase')=='CHILD_REAPED':raise OSError('fixture finish failure')
        s.atomic_record(path,value)
    spawn=Mock(return_value=child);monkeypatch.setattr(m.signal,'signal',lambda *a:None)
    assert m.supervise(prefix,popen=spawn,process_reader=lambda pid:{'pid':42,'start_ticks':90,'boot_id':'fixture'},persist=persist)==1
    r=s.read_json(prefix/'capture/monitor_supervisor.json')
    assert r['phase']=='UNCERTAIN' and r['return_code']==(None if failure=='wait' else 0)
    spawn.assert_called_once();child.send_signal.assert_not_called()


def test_signal_is_forwarded_only_to_current_child_identity(artifacts,monkeypatch):
    _,prefix=overlay(artifacts);handlers={};current=[{'pid':42,'start_ticks':90,'boot_id':'fixture'}]
    monkeypatch.setattr(m.signal,'signal',lambda sig,fn:handlers.setdefault(sig,fn))
    child=NS(pid=42,send_signal=Mock())
    def wait(**kw):
        handlers[m.signal.SIGINT](m.signal.SIGINT,None)
        current[0]={**current[0],'start_ticks':91}
        handlers[m.signal.SIGINT](m.signal.SIGINT,None)
        return 0
    child.wait=wait
    assert m.supervise(prefix,popen=lambda *a,**kw:child,process_reader=lambda pid:current[0])==0
    child.send_signal.assert_called_once_with(m.signal.SIGINT)


def test_startup_parent_poll_does_not_overwrite_actual_monitor_child_wait(tmp_path):
    from simulation.ros2_gazebo.scripts import sim_processes as sup
    (tmp_path/'capture').mkdir()
    original={'state':'PARENT_WAIT_STATUS_OBSERVED','pid':43,'start_ticks':90,'return_code':0}
    s.atomic_record(tmp_path/'capture/monitor_exit.json',original)
    before=(tmp_path/'capture/monitor_exit.json').read_bytes()
    sup.record_monitor_exit(NS(pid=42),1,tmp_path,NS(pid=42,start_ticks=80))
    assert (tmp_path/'capture/monitor_exit.json').read_bytes()==before
    assert s.read_json(tmp_path/'capture/monitor_supervisor_exit.json')['return_code']==1


def test_failed_retained_parent_is_not_a_monitor_child_exit(tmp_path):
    from simulation.ros2_gazebo.scripts import sim_processes as sup
    (tmp_path/'capture').mkdir()
    sup.record_monitor_exit(NS(pid=42,args=['python3','monitor.py','--supervise',str(tmp_path)]),
        1,tmp_path,NS(pid=42,start_ticks=80))
    assert not (tmp_path/'capture/monitor_exit.json').exists()
    assert s.read_json(tmp_path/'capture/monitor_supervisor_exit.json')['return_code']==1


def test_consumed_supervisor_cannot_restart_or_rewrite_receipts(artifacts,monkeypatch):
    _,prefix=overlay(artifacts)
    child=NS(pid=42,wait=lambda **kw:0,send_signal=Mock());spawn=Mock(return_value=child)
    monkeypatch.setattr(m.signal,'signal',lambda *a:None)
    read=lambda pid:{'pid':42,'start_ticks':90,'boot_id':'fixture'}
    assert m.supervise(prefix,popen=spawn,process_reader=read)==0
    before={p.name:p.read_bytes() for p in (prefix/'capture').iterdir()}
    assert m.supervise(prefix,popen=spawn,process_reader=read)==1
    assert before=={p.name:p.read_bytes() for p in (prefix/'capture').iterdir()}
    spawn.assert_called_once()


HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728'


def historical_inputs():
    # Immutable real input. New analysis in memory only; never rewrite its reports.
    prefix=HISTORY/'container-copies/tmp/tfg_diagnostic_agents/a4e77c9e-827f-43a6-ad33-d41729b18ff1/capture'
    monitor=json.loads((prefix/'monitor.json').read_bytes())
    writer=json.loads((HISTORY/'passive-status-writer-links.json').read_bytes())[0]
    closure={'monitor':monitor,'stop_operation':json.loads((HISTORY/'runtime-copies/stop/operation.json').read_bytes()),
             'target':json.loads((HISTORY/'passive-post-close-host.json').read_bytes())['target']}
    return (prefix/'sockets.jsonl').read_bytes(),monitor,writer,closure


def test_six_local_windows_and_terminal_loss_never_complete_historical_series():
    data,monitor,link,closure=historical_inputs()
    r=sockets.analyze_series(data,monitor['socket_inventory'],link['writer'],monitor['lifecycle_id'],
        receipt_wall_ns=[link['receipt']['system_unix_ns']],closure_evidence=closure)
    assert not r['errors'] and not r['usable_windows'] and len(r['partial_table_windows'])==6
    assert r['terminal_context_loss']['classification']=='AGENT_CONTEXT_LOST_DURING_RECORDED_PROTECTED_CLOSURE'
    assert r['series_state']=='UNCERTAIN_OR_INCOMPLETE' and not r['covers_entire_monitor_interval']
    assert r['reception_coverage']['within_usable_sampled_span'] is False  # legacy /proc reader did not establish EOF
    assert r['reception_coverage']['inside_individual_usable_sweeps']==[False]
    assert r['status']=='BLOCKED' and not r['source_association_verified']


@pytest.mark.parametrize('change',['no_closure','other_session','wrong_stop','truncated','count'])
def test_terminal_loss_and_bad_closure_cannot_become_verified(change):
    data,monitor,link,closure=historical_inputs()
    if change=='no_closure':closure=None
    elif change=='other_session':closure['target']['descriptor']['lifecycle_id']='OTHER'
    elif change=='wrong_stop':closure['stop_operation']['action']='start'
    elif change=='truncated':data=data[:-5]
    else:monitor['socket_inventory']['snapshots']+=1
    r=sockets.analyze_series(data,monitor['socket_inventory'],link['writer'],monitor['lifecycle_id'],closure_evidence=closure)
    assert r['series_state']=='UNCERTAIN_OR_INCOMPLETE' and r['status']=='BLOCKED'
    if change=='no_closure':assert r['terminal_context_loss']['classification']=='UNATTRIBUTED_TERMINAL_CONTEXT_LOSS'
    else:assert r['errors']
