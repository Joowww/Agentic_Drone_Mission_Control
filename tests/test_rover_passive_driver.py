"""Full protocol with the REAL monitor, files, admission and classifier; fake /proc.

No Docker, Gazebo, ROS or real signals. All outputs are synthetic fixtures.
"""
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import pytest
from tests.test_rover_diagnostic_selection import artifacts,overlay,candidate
from tools.rover_xrce_trace import monitor as m,selection as s
from tools.rover_xrce_trace.passive_trial import execute_once
from tools.rover_xrce_trace.session_precheck import classify_last_session,POINTER
from tools.rover_passive_validation import session_window,read_journal
from tools.rover_xrce_trace.budget import SOCKET


@pytest.mark.parametrize('case',['transient','zombie','foreign_denied','known_denied','recycled','lost_agent','rejected','terminal'])
def test_complete_driver_channels_and_no_replay(artifacts,tmp_path,monkeypatch,case):
    value,prefix=overlay(artifacts);owner=value['lifecycle_id'];proc=tmp_path/'proc';proc.mkdir()
    (proc/'sys/kernel/random').mkdir(parents=True);(proc/'sys/kernel/random/boot_id').write_text('boot')
    def add(pid,ppid,ticks,argv,exe,state='S',children=''):
        p=proc/str(pid);p.mkdir(exist_ok=True)
        (p/'stat').write_text(f'{pid} (fixture) '+' '.join([state,str(ppid)]+['0']*17+[str(ticks)]))
        (p/'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv)+b'\0')
        (p/'task'/str(pid)).mkdir(parents=True,exist_ok=True);(p/'task'/str(pid)/'children').write_text(children)
        if (p/'exe').exists() or (p/'exe').is_symlink():(p/'exe').unlink()
        (p/'exe').symlink_to(exe)
    root=dict(pid=9,ppid=1,start_ticks=90,boot_id='boot')
    agent=candidate(value);agent['argv'][0]=agent['executable']
    add(9,1,90,['ros2','launch','ardupilot_gz_bringup','tfg_demo.launch.py'],'/usr/bin/python3',children='10 55')
    add(10,9,100,agent['argv'],agent['executable'])
    add(55,9,550,['/usr/bin/sleep','1'],'/usr/bin/sleep',state='Z' if case=='zombie' else 'S')
    add(999,1,999,['other'],'/usr/bin/unrelated')
    if case=='transient':(proc/'55/stat').unlink()
    source=tmp_path/'launch.log';source.write_bytes(b'TFG_XRCE_TRACE {"event":"SYNTHETIC_FIXTURE"}\n')
    s.atomic_record(prefix/'launch.json',{'process':root})
    ready=threading.Event();closing=threading.Event();failed=threading.Event();clock=[100.];handlers={};rc=[]
    real_verify=m.verify_agent;real_process=m.process;real_alive=m.root_alive;real_discover=m.launch_candidates;real_write=m.atomic_record;real_readlink=m.os.readlink
    exe_reads=[]
    def readlink(path,*args,**kw):
        exe_reads.append(str(path))
        if str(path)==str(proc/'999/exe') or case=='foreign_denied' and str(path)==str(proc/'55/exe') or case=='known_denied' and str(path)==str(proc/'10/exe'):
            raise PermissionError('SYNTHETIC persistent denial')
        return real_readlink(path,*args,**kw)
    monkeypatch.setattr(m.os,'readlink',readlink)
    def process(pid,*ignored):
        if pid==os.getpid():return dict(pid=77,ppid=1,start_ticks=700,boot_id='boot',argv=['fixture-monitor'],executable='/usr/bin/python3')
        return real_process(pid,proc)
    def persist(path,body):
        real_write(path,body)
        if path.name=='monitor.json':
            if body.get('phase')=='OBSERVING':ready.set()
            if body.get('phase')=='FAILED':failed.set();ready.set()
    class Sockets:
        INTERVAL=5
        def __init__(self,*a):self.bad=case=='foreign_denied'
        def sample(self,*a):pass
        def close(self):
            if case=='terminal':self.bad=True
        def summary(self):return dict(state='SYNTHETIC',snapshots=1,journal_bytes_written=100,error=None,peer_waiting=None,
            incomplete_snapshots=int(self.bad),sampling_limit_reached=False,budget=SOCKET.record(),sample_limit=64,interval_s=5)
    def sleep(seconds):
        if closing.is_set():clock[0]+=.5
        time.sleep(.002)
    monkeypatch.setattr(m,'time',SimpleNamespace(monotonic=lambda:clock[0],time_ns=time.time_ns,sleep=sleep))
    monkeypatch.setattr(m,'verify_agent',lambda *a,**kw:real_verify(*a,**kw,maps_reader=lambda pid:'000-001 r-x 0 00:00 0 '+str(prefix/'lib/libmicroxrcedds_agent.so.2.4')));monkeypatch.setattr(m,'process',process);monkeypatch.setattr(m,'root_alive',lambda p,*ignored:real_alive(p,proc))
    monkeypatch.setattr(m,'launch_candidates',lambda root:real_discover(root,proc))
    monkeypatch.setattr(m,'atomic_record',persist);monkeypatch.setattr(m,'SOURCE',source);monkeypatch.setattr(m,'SocketRecorder',Sockets)
    monkeypatch.setattr(m.signal,'signal',lambda sig,fn:handlers.__setitem__(sig,fn));monkeypatch.setenv('TFG_SIM_PROJECT','Agentic_Drone_Mission_Control')
    def monitor():rc.append(m.main([str(prefix)]))
    thread=threading.Thread(target=monitor,daemon=True);calls=[];target={};history={}
    environment=dict(status='ACTIVE',engine_id='engine',container_id='a'*64,image_id='sha256:'+'b'*64,name='/sim',created_at='2026-01-01T00:00:00Z',state={'Status':'running','Running':True,'Pid':123,'StartedAt':'2026-01-01T00:00:00Z','Restarting':False,'Paused':False,'Dead':False})
    class Ports:
        def start(self):
            calls.append('start');thread.start();assert ready.wait(4)
            target.update(state='STARTED',descriptor=value)
            history['start']=dict(kind='SIMULATION_LIFECYCLE',state='FINISHED',action='start',owner_id=owner,profile='two_drones_rover',movement_authorized=False,finished_at='2026-01-01T01:00:00Z',diagnostic_agent=value)
            return {'status':'SUCCESS','operation':history['start']}
        def admit(self,identifier):
            calls.append('admit');record=s.read_json(prefix/'capture/monitor.json')
            if case=='rejected':return {'measurement_allowed':False,'reason':'SYNTHETIC pre-reader rejection'}
            try:plan=session_window(record,now=clock[0],boot_id='boot')
            except ValueError as e:return {'measurement_allowed':False,'reason':str(e)}
            return {'measurement_allowed':True,'plan':plan}
        def reader(self,identifier):
            calls.append('reader')
            if case in {'recycled','lost_agent'}:
                if case=='recycled':add(10,9,101,agent['argv'],agent['executable'])
                else:(proc/'10/exe').unlink()
                clock[0]+=2;assert failed.wait(4)
                return {'executed':True,'return_code':2,'reader_closed':False,'samples':0}
            base=dict(schema='tfg.rover-passive-validation/1',status='BLOCKED',movement_authorized=False,receipt_wall_ns=100)
            rows=[{**base,'kind':'header','session_id':owner,'probe_session_id':owner,'receipt_steady_ns':100000000000},
                  {**base,'kind':'sample','topic':'/ap/v3/status','receipt_steady_ns':100000000001,'fixture':'SYNTHETIC'},
                  {**base,'kind':'footer','session_id':owner,'reader_closed':True,'counts':{'/ap/v3/status':1},'receipt_steady_ns':100000000002}]
            j=tmp_path/'fixture-journal';j.write_text(''.join(json.dumps(v)+'\n' for v in rows));receipt=tmp_path/'fixture-receipt'
            receipt.write_text(json.dumps(dict(schema='tfg.rover-passive-validation-receipt/1',session_id=owner,reader_closed=True)))
            report=read_journal(j,receipt)
            return {'executed':True,'return_code':0,'reader_closed':True,'counts':report['counts'],'coverage':'PARTIAL_SYNTHETIC_NOT_A_REAL_CAPTURE'}
        def stop(self,identifier):
            calls.append('stop');assert target['descriptor']['lifecycle_id']==identifier
            for pid,ticks in ((9,90),(10,101 if case=='recycled' else 100)):
                if (proc/str(pid)/'stat').exists():(proc/str(pid)/'stat').write_text(f'{pid} (stopped fixture) '+' '.join(['Z','1']+['0']*17+[str(ticks)]))
                p=proc/str(pid)/'exe'
                if p.is_symlink():p.unlink()
            closing.set();handlers[m.signal.SIGINT]()
            thread.join(4);assert not thread.is_alive()
            target.update(state='CLOSED',closed_by='33333333-3333-4333-8333-333333333333')
            history['stop']=dict(kind='SIMULATION_LIFECYCLE',state='FINISHED',action='stop',owner_id=target['closed_by'],profile='two_drones_rover',movement_authorized=False,finished_at='2026-01-01T01:01:00Z',diagnostic_close_target=value)
            return {'status':'SUCCESS','operation':history['stop']}
        def post(self,identifier):
            calls.append('post');record=s.read_json(prefix/'capture/monitor.json')
            inventory=dict(owned=[],ambiguous=[],agents=[],boot_id='boot',state_files={POINTER:json.dumps({**value,'status':'BLOCKED','movement_authorized':False,'source_association_verified':False})})
            classification=classify_last_session(target=target,start_operation=history['start'],stop_operation=history['stop'],environment_reference={'lifecycle_id':owner,'profile':'two_drones_rover','environment':{k:environment[k] for k in ('engine_id','container_id','image_id','name','created_at')},'pre_start_state':environment['state']},environment=environment,inventory=inventory,selection=s.read_json(prefix/'selection.json'),launch=s.read_json(prefix/'launch.json'),monitor=record)
            return {'monitor':record,'actual_monitor_rc':rc[0],'classification':classification}
    result=execute_once(tmp_path/'driver',Ports())
    assert calls.count('start')==calls.count('stop')==1 and result['stop']['status']=='SUCCESS'
    assert result['post']['actual_monitor_rc'] in (0,1) and not result['movement_authorized']
    if case in {'known_denied','rejected'}:assert 'reader' not in calls and result['reader'] is None
    elif case in {'recycled','lost_agent'}:assert result['reader']['return_code']==2 and result['post']['monitor']['capture_complete'] is False
    elif case in {'foreign_denied','terminal'}:
        assert 'reader' in calls and result['post']['monitor']['core_capture_complete'] is True,(result['admission'],result.get('error'))
        assert result['post']['monitor']['capture_complete'] is False and result['post']['classification']['status']=='BLOCKED'
    else:assert 'reader' in calls and result['post']['classification']['status']=='CLEAR',(result['post']['classification'],result.get('error'),result['post']['monitor'].get('error'),result['post']['monitor']['errors'])
    assert str(proc/'999/exe') not in exe_reads
    before=list(calls)
    with pytest.raises(FileExistsError):execute_once(tmp_path/'driver',Ports())
    assert calls==before
