"""Synthetic lifecycle/process fixtures only; no Docker, ROS or real signals."""
from dataclasses import replace
import json
from pathlib import Path
import signal
from uuid import uuid4

import pytest
from tools import simulation_lifecycle as lifecycle, vehicle_execution_lock as locks
from tools.rover_xrce_trace import selection
from simulation.ros2_gazebo.scripts import sim_processes as cleanup
from tests.test_rover_model_selection import model
from tests.test_simulation_lifecycle import FakeProcesses, proc, launch, files


@pytest.fixture
def failed(model, monkeypatch):
    owner=model['lifecycle_id'];root=locks.LOCK_ROOT.parent/'simulation_lifecycle'/owner
    root.mkdir(parents=True);locks.LOCK_ROOT.mkdir(exist_ok=True)
    operation={'kind':'SIMULATION_LIFECYCLE','owner_id':owner,'action':'start',
               'profile':'two_drones_rover','state':'UNCONFIRMED','diagnostic_agent':model,
               'process':{'pid':99999999,'start_ticks':1,'boot_id':'synthetic'},
               'environment_execution':{'container_boot_id':'synthetic','persistent_identity':{'fixture':True}}}
    target={'descriptor':model,'state':'UNCONFIRMED','operation_path':str(root/'operation.json')}
    locks.atomic_json(root/'operation.json',operation)
    locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json',operation)
    locks.atomic_json(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json',target)
    monkeypatch.setattr(lifecycle,'assert_environment_execution',lambda expected:None)
    return owner,operation,target


def test_same_owner_close_retains_original_and_barrier_until_success(failed, monkeypatch):
    owner,old,target=failed
    def backend(action,gui,fd,process,path):
        lease=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())
        assert action=='stop' and lease['closing_failed_start']==old
        assert lease['environment_execution']==old['environment_execution']
        assert lease['diagnostic_close_target']==target['descriptor']
        assert locks.restriction()==lease
        assert json.loads(Path(target['operation_path']).read_text())==old
        return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    result=lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',close_owner=owner)
    assert result['status']=='SUCCESS' and locks.restriction() is None
    final=json.loads((locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').read_text())
    assert final['state']=='CLOSED' and final['closed_by']==result['operation']['owner_id']
    assert json.loads(Path(target['operation_path']).read_text())==old


@pytest.mark.parametrize('case',['other_owner','no_owner','start','restart','profile','context','alive','original','reservation','sequence','reconciliation','descriptor'])
def test_scope_and_other_barriers_never_reach_backend(failed,monkeypatch,case):
    owner,old,target=failed;args=dict(gui=False,profile='two_drones_rover',close_owner=owner);action='stop'
    if case=='other_owner':args['close_owner']=str(uuid4())
    elif case=='no_owner':args.pop('close_owner')
    elif case in ('start','restart'):action=case
    elif case=='profile':args['profile']='two_drones'
    elif case=='context':
        def changed(expected):raise locks.VehicleBusy('changed context')
        monkeypatch.setattr(lifecycle,'assert_environment_execution',changed)
    elif case=='alive':monkeypatch.setattr(locks,'identity_alive',lambda p:True)
    elif case=='original':locks.atomic_json(Path(target['operation_path']),{**old,'changed':True})
    elif case=='reservation':locks.atomic_json(locks.LOCK_ROOT/'v3.json',{'owner_id':'other','state':'UNCONFIRMED','vehicle':'v3'})
    elif case=='sequence':locks.atomic_json(locks.LOCK_ROOT/'sequence.json',{'owner_id':'other','state':'UNCONFIRMED'})
    elif case=='reconciliation':locks.atomic_json(locks.LOCK_ROOT/'reconciliation.json',{'owner_id':'other'})
    elif case=='descriptor':
        changed=dict(target,state='STARTED');locks.atomic_json(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json',changed)
    monkeypatch.setattr(lifecycle,'_backend',lambda *a:pytest.fail('forbidden backend'))
    assert lifecycle.run_lifecycle(action,**args)['status']=='BLOCKED'
    assert json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())==old


@pytest.mark.parametrize('outcome',['partial','interrupt','context_after'])
def test_partial_or_interrupted_close_preserves_restriction(failed,monkeypatch,outcome):
    owner,old,target=failed;calls=[]
    def backend(*args):
        calls.append(args)
        if outcome=='interrupt':raise KeyboardInterrupt('synthetic')
        if outcome=='context_after':
            monkeypatch.setattr(lifecycle,'assert_environment_execution',lambda e:(_ for _ in ()).throw(locks.VehicleBusy('context changed after cleanup')))
        return 1 if outcome=='partial' else 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    if outcome=='interrupt':
        with pytest.raises(KeyboardInterrupt):lifecycle.run_lifecycle('stop',profile='two_drones_rover',close_owner=owner)
    else:assert lifecycle.run_lifecycle('stop',profile='two_drones_rover',close_owner=owner)['status']=='UNCONFIRMED'
    barrier=locks.restriction();assert barrier['state']=='UNCONFIRMED' and barrier['action']=='stop'
    assert barrier['closing_failed_start']==old and len(calls)==1
    assert json.loads((locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').read_text())['state']=='UNCONFIRMED'
    assert lifecycle.run_lifecycle('stop',profile='two_drones_rover',close_owner=owner)['status']=='BLOCKED'


@pytest.fixture
def scoped_cleanup(model,monkeypatch):
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    monkeypatch.setenv('TFG_DIAGNOSTIC_CLOSE_BOOT_ID',boot)
    monkeypatch.setenv('TFG_DIAGNOSTIC_CLOSE_TARGET',json.dumps(model))
    monkeypatch.setattr(cleanup,'begin_diagnostic_closure',lambda **kw:None)
    monkeypatch.setattr(cleanup,'diagnostic_summary',lambda:None)
    return selection.digest(model)


def test_scoped_cleanup_excludes_other_session_and_ambiguous_processes(scoped_cleanup):
    own=replace(launch(10,'tfg_demo.launch.py'),diagnostic_selection_sha256=scoped_cleanup)
    foreign=replace(launch(40),diagnostic_selection_sha256='other-session')
    ambiguous=replace(proc(70),argv=('/opt/ros/humble/lib/ros_gz_bridge/parameter_bridge','--ros-args','-r','__ns:=/rover1'))
    env=FakeProcesses([own,proc(11,10),foreign,proc(41,40),ambiguous])
    def send(pid,sig):
        env.sent.append((pid,sig));env.table.pop(pid,None);env.table.pop(11,None)
    env.send=send
    result=env.stop()
    assert not result['success'] and env.sent==[(10,signal.SIGINT)]
    assert set(env.table)=={40,41,70}
    assert {p['pid'] for p in result['unattributed_auxiliaries']}=={40,41,70}
    assert cleanup.STATE.exists()


def test_scoped_pid_or_exec_context_change_never_signals(scoped_cleanup):
    own=replace(launch(10),diagnostic_selection_sha256=scoped_cleanup)
    env=FakeProcesses([own],exit_on=None)
    result=cleanup.shutdown(scan=lambda:dict(env.table),read=lambda pid:replace(own,diagnostic_selection_sha256='other'),
        send=env.send,monotonic=lambda:env.now,sleep=env.sleep)
    assert not result['success'] and result['errors'] and not env.sent


def test_scoped_changed_boot_prevents_all_signals(scoped_cleanup,monkeypatch):
    monkeypatch.setenv('TFG_DIAGNOSTIC_CLOSE_BOOT_ID','other-boot')
    env=FakeProcesses([replace(launch(10),diagnostic_selection_sha256=scoped_cleanup)])
    with pytest.raises(ValueError,match='boot changed'):env.stop()
    assert not env.sent


def test_scoped_cleanup_records_current_identity_and_success(scoped_cleanup):
    own=replace(launch(10),diagnostic_selection_sha256=scoped_cleanup)
    env=FakeProcesses([own]);result=env.stop()
    assert result['success'] and len(result['signals'])==1
    assert result['signals'][0]['process']['diagnostic_selection_sha256']==scoped_cleanup
    assert result['signals'][0]['start_ticks']==own.start_ticks


def test_process_reader_binds_full_descriptor_not_pid_file(tmp_path,scoped_cleanup,model):
    d=tmp_path/'123';d.mkdir();(d/'stat').write_text('123 (synthetic) '+' '.join(['S','1']+['0']*17+['12345']))
    (d/'cmdline').write_bytes(b'python3\0fixture\0')
    (d/'environ').write_bytes(b'TFG_DIAGNOSTIC_AGENT='+json.dumps(model).encode()+b'\0')
    assert cleanup.read_process(123,tmp_path).diagnostic_selection_sha256==scoped_cleanup
