"""Real monitor + shutdown protocol; fake processes/signals/clock and private files."""
import json
import os
from pathlib import Path
import signal
import threading
import time
from types import SimpleNamespace
import pytest
from simulation.ros2_gazebo.scripts import sim_processes as sup
from tools.rover_xrce_trace import monitor as m,selection as s
from tests.test_rover_model_selection import model


@pytest.mark.parametrize('case',['late_server','late_agent','persistent','cleanup_denied','early_agent_exit','lost_observation','lost_parent'])
def test_cleanup_keeps_real_monitor_until_server_outcome(model,tmp_path,monkeypatch,case):
    prefix=Path(model['prefix']);boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    def p(pid,parent,argv):return sup.Process(pid,parent,pid*10,tuple(argv),True)
    launch=p(9,1,['ros2','launch','ardupilot_gz_bringup','tfg_demo.launch.py'])
    agent=p(10,9,[str(prefix/'lib/micro_ros_agent/micro_ros_agent'),'udp4','--middleware','dds','--port','2019','--ros-args','-r','__ns:=/drone1'])
    bridge=p(12,9,[str(prefix/'lib/ros_gz_bridge/parameter_bridge'),'--ros-args','-r','__ns:=/rover1'])
    server=p(11,9,['gz','sim','-s']);child=p(77,78,['python3',str(prefix/'monitor.py'),'--observe-child',str(prefix)])
    parent=p(78,1,['python3',str(prefix/'monitor.py'),'--supervise',str(prefix)])
    table={x.pid:x for x in (launch,agent,bridge,server,child,parent)};clock=[100.];sent=[];ready=threading.Event();failed=threading.Event();rc=[]
    monkeypatch.setattr(sup,'STATE',tmp_path/'state');monkeypatch.setattr(sup,'PID_FILE',tmp_path/'pid');monkeypatch.setattr(sup,'DIAGNOSTIC_STATE',tmp_path/'pointer')
    s.atomic_record(sup.DIAGNOSTIC_STATE,model);monkeypatch.setenv('TFG_DIAGNOSTIC_CLOSE_TARGET',json.dumps(model));monkeypatch.setenv('TFG_SIM_PROJECT',sup.PROJECT)
    def identity(value):
        return dict(pid=value.pid,ppid=value.ppid,start_ticks=value.start_ticks,boot_id=boot,argv=list(value.argv),
            executable=agent.argv[0] if value.pid==10 else bridge.argv[0] if value.pid==12 else '/usr/bin/ruby' if value.pid==11 else '/usr/bin/python3')
    root=identity(launch);s.atomic_record(prefix/'launch.json',{'process':root})
    s.atomic_record(prefix/'capture/monitor_supervisor.json',{'phase':'WAITING_CHILD','child':identity(child),'supervisor':identity(parent)})
    event=dict(schema='tfg.model-source/1',event='configured',sequence=1,lifecycle_id=model['lifecycle_id'],pid=11,process_start_ticks='110',boot_id=boot,model_entity=42,movement_authorized=False)
    source=tmp_path/'launch.log';source.write_text('TFG_MODEL_TRACE '+json.dumps(event)+'\nTFG_XRCE_TRACE {}\n')
    def process(pid):
        if pid==os.getpid():return identity(child)
        if pid not in table:raise FileNotFoundError('synthetic /proc exit')
        return identity(table[pid])
    def alive(value):
        if value and value['pid']==os.getpid():return True  # fake cleanup owner, not a middleware process
        if case=='lost_observation' and value and value['pid']==11 and (prefix/'capture/closure-request.json').exists():
            raise PermissionError('synthetic lost observation')
        return value is not None and value['pid'] in table and table[value['pid']].start_ticks==value['start_ticks']
    def maps(pid):
        library={10:'libmicroxrcedds_agent.so.2.4',12:'libros_gz_bridge.so',11:'libArduPilotPlugin.so'}[pid]
        return '0-1 r-x 0 00:00 0 '+str(prefix/'lib'/library)+'\n0-1 r-x 0 00:00 0 /installed/libgz-sim8.so.8'
    agent_verify,bridge_verify,model_verify=m.verify_agent,m.verify_bridge,m.verify_model_library
    monkeypatch.setattr(m,'verify_agent',lambda *a,**kw:agent_verify(*a,**kw,maps_reader=maps))
    monkeypatch.setattr(m,'verify_bridge',lambda *a,**kw:bridge_verify(*a,**kw,maps_reader=maps))
    monkeypatch.setattr(m,'verify_model_library',lambda *a,**kw:model_verify(*a,**kw,maps_reader=maps))
    monkeypatch.setattr(m,'process',process);monkeypatch.setattr(m,'root_alive',alive)
    monkeypatch.setattr(m,'launch_candidates',lambda root:[identity(x) for x in (agent,bridge) if x.pid in table])
    monkeypatch.setattr(m,'SOURCE',source);monkeypatch.setattr(m.signal,'signal',lambda *a:None)
    monkeypatch.setattr(m,'time',SimpleNamespace(monotonic=lambda:clock[0],time_ns=time.time_ns,
        strftime=time.strftime,gmtime=time.gmtime,sleep=lambda n:time.sleep(.001)))
    class Sockets:
        def __init__(self,*a):pass
        def sample(self,*a):pass
        def close(self):pass
        def summary(self):return {'snapshots':1,'incomplete_snapshots':0}
    monkeypatch.setattr(m,'SocketRecorder',Sockets)
    persist=m.atomic_record
    def record(path,body):
        persist(path,body)
        if path.name=='monitor.json' and body.get('phase')=='OBSERVING':ready.set()
        if path.name=='monitor.json' and body.get('phase')=='FAILED':failed.set()
    monkeypatch.setattr(m,'atomic_record',record)
    def observe():
        try:rc.append(m.main([str(prefix)]))
        finally:table.pop(77,None)
    worker=threading.Thread(target=observe,daemon=True)
    class Child:
        pid=77
        def wait(self,timeout):
            worker.join(3)
            if worker.is_alive():raise TimeoutError('simulated child still observing')
            return rc[0]
        def send_signal(self,sig):raise AssertionError('Protected cleanup must defer observer signals')
    def spawn(*a,**kw):worker.start();return Child()
    parent_rc=[]
    def supervise():
        try:parent_rc.append(m.supervise(prefix,popen=spawn,
            process_reader=lambda pid:identity(parent if pid==os.getpid() else child)))
        finally:table.pop(78,None)
    supervisor=threading.Thread(target=supervise,daemon=True);supervisor.start();assert ready.wait(3)
    if case=='early_agent_exit':
        table.pop(10);clock[0]+=2;assert failed.wait(3)
    if case=='lost_parent':table.pop(78)
    def read(pid):
        if pid==os.getpid():return sup.Process(pid,1,123,('python3','sim_processes.py','stop'))
        return table.get(pid)
    def send(pid,sig):
        sent.append((pid,sig))
        assert pid not in (77,78),'Observers must not be signaled with the vehicle roots'
        if pid==9:
            for i in ((9,12) if case=='late_agent' else (9,10,12)):table.pop(i,None)
        elif pid==10:table.pop(10,None)
        elif pid==11:
            if case=='cleanup_denied':raise PermissionError('synthetic denial')
            if case!='persistent':table.pop(11,None)
    def sleep(dt):clock[0]+=dt;time.sleep(.002)
    result=sup.shutdown(scan=lambda:dict(table),send=send,read=read,monotonic=lambda:clock[0],sleep=sleep)
    supervisor.join(2);assert not worker.is_alive() and not supervisor.is_alive()
    final=s.read_json(prefix/'capture/monitor.json')
    assert final.get('cleanup_request') is not None,(final.get('error'),final.get('errors'),result)
    assert final['cleanup_request']['lifecycle_id']==model['lifecycle_id']
    assert clock[0]<=122.25  # unchanged 20s cleanup, plus pre-request fixture advancement
    if case in {'late_server','late_agent'}:assert result['success'] and final['core_capture_complete'] and rc==[0]
    else:assert not final.get('core_capture_complete',False) and rc==[1]
    if case in {'persistent','cleanup_denied'}:assert not result['success'] and result['remaining']
    if case=='lost_parent':assert result['success'] and result['diagnostic_coordination_errors']
    assert (11,signal.SIGTERM) in sent
    assert parent_rc==rc
    exit_receipt=s.read_json(prefix/'capture/monitor_exit.json')
    assert exit_receipt['return_code']==rc[0] and exit_receipt['source']=='RETAINED_MONITOR_PARENT_POPEN_WAIT'


def test_cleanup_owner_loss_is_not_completion_or_resume(model,monkeypatch):
    prefix=Path(model['prefix']);request={'lifecycle_id':model['lifecycle_id'],'selection_sha256':model['selection_sha256'],
        'source':'PROTECTED_PROCESS_CLEANUP','cleanup_owner':{'pid':999,'start_ticks':100,'boot_id':'fixture'}}
    s.atomic_record(prefix/'capture/closure-request.json',request)
    monkeypatch.setattr(m,'root_alive',lambda identity:False)
    with pytest.raises(ValueError,match='owner lost'):m.managed_closure(prefix,model,None)
    assert not (prefix/'capture/cleanup-finished.json').exists()
