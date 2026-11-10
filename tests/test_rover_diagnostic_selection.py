"""Offline selection/monitor tests: fake ELF files, process tables and clocks only."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools.rover_xrce_trace import selection as s, monitor as m

OWNER='12345678-1234-4234-8234-123456789abc'


@pytest.fixture
def artifacts(tmp_path,monkeypatch):
    # Paths intentionally remain /tmp pytest files; none are executables.
    wrapper=tmp_path/'wrapper';wrapper.write_bytes(b'\x7fELF synthetic wrapper')
    library=tmp_path/'library';library.write_bytes(b'\x7fELF synthetic compatible library')
    pair=tuple(hashlib.sha256(p.read_bytes()).hexdigest() for p in (wrapper,library))
    monkeypatch.setattr(s,'PAIR',pair);monkeypatch.setattr(s,'ROOT',tmp_path/'overlays')
    manifest=dict(schema=s.SCHEMA,container_id='a'*64,image_id='sha256:'+'b'*64,engine_id='engine',
                  wrapper_path=str(wrapper),wrapper_sha256=pair[0],library_path=str(library),library_sha256=pair[1])
    value=s.descriptor(manifest,OWNER)
    # TEST_FIXTURE: the active container execution a diagnostic START runs in (same container/image/engine as the
    # manifest); the lifecycle records it so the later STOP can build the exact descriptor/boot pair.
    from tools import reconciliation_environment as execution_reader
    execution={'persistent_identity':{'engine_id':'engine','container_id':'a'*64,'image_id':'sha256:'+'b'*64,
               'name':'/tfg-ardupilot-gazebo','created_at':'2026-11-01T00:00:00Z'},
               'container_started_at':'2026-11-01T00:00:01Z','container_boot_id':'fixture-boot'}
    monkeypatch.setattr(execution_reader,'inspect_active_execution',lambda:json.loads(json.dumps(execution)))
    def elf(path):
        if str(path)==str(wrapper):return {'needed':['libmicroxrcedds_agent.so.2.4'],'soname':[]}
        return {'needed':['librmw_fastrtps_shared_cpp.so'],'soname':['libmicroxrcedds_agent.so.2.4']}
    monkeypatch.delenv('LD_PRELOAD',raising=False);monkeypatch.delenv('LD_AUDIT',raising=False)
    return value,elf


def overlay(artifacts):
    value,elf=artifacts
    s.prepare_overlay(value,elf_reader=elf)
    return value,Path(value['prefix'])


def test_default_preserves_ros_context_and_never_touches_files(monkeypatch):
    verify=Mock(side_effect=AssertionError('default must not read diagnostic files'))
    monkeypatch.setattr(s,'verify_overlay',verify)
    original={'AMENT_PREFIX_PATH':'ros:ardu','LD_LIBRARY_PATH':'libs','ROS_DOMAIN_ID':'0','TFG_XRCE_TRACE':'1'}
    env,value=s.configure(original)
    assert value is None and env=={k:v for k,v in original.items() if k!='TFG_XRCE_TRACE'}
    assert original['TFG_XRCE_TRACE']=='1';verify.assert_not_called()


def test_overlay_explicit_hashes_private_and_compatible(artifacts):
    value,prefix=overlay(artifacts)
    env,selected=s.configure({s.ENV:json.dumps(value),'AMENT_PREFIX_PATH':'normal','LD_LIBRARY_PATH':'normal_lib',
                              'ROS_DOMAIN_ID':'0','TFG_SIM_PROJECT':'project'})
    assert selected==value and env['AMENT_PREFIX_PATH']==str(prefix)+':normal'
    assert env['LD_LIBRARY_PATH']==str(prefix)+'/lib:normal_lib' and env['TFG_XRCE_TRACE']=='1'
    assert env['ROS_DOMAIN_ID']=='0' and env['TFG_SIM_PROJECT']=='project'
    assert prefix.stat().st_mode & 0o077==0
    assert (prefix/'lib/micro_ros_agent/micro_ros_agent').read_bytes().startswith(b'\x7fELF')
    assert s.read_json(prefix/'selection.json')['source_association_verified'] is False
    with pytest.raises(FileExistsError):s.prepare_overlay(value,elf_reader=artifacts[1])


@pytest.mark.parametrize('case',['missing','changed','symlink','mixed_pair','elf','loader'])
def test_bad_artifacts_rejected_before_prefix_creation(artifacts,monkeypatch,case):
    value,elf=artifacts;manifest=value['manifest'];p=Path(manifest['library_path'])
    if case=='missing':p.unlink()
    elif case=='changed':p.write_bytes(b'\x7fELF altered')
    elif case=='symlink':
        other=p.with_name('other');p.rename(other);p.symlink_to(other)
    elif case=='mixed_pair':manifest['library_sha256']='f'*64
    elif case=='elf':elf=lambda p:{'needed':[],'soname':[]}
    else:monkeypatch.setenv('LD_PRELOAD','unreviewed.so')
    with pytest.raises((ValueError,OSError)):s.prepare_overlay(value,elf_reader=elf)
    assert not Path(value['prefix']).exists()


def test_altered_overlay_never_configures_launch(artifacts):
    value,prefix=overlay(artifacts)
    p=prefix/'lib/libmicroxrcedds_agent.so.2.4';p.chmod(0o600);p.write_bytes(b'\x7fELF changed')
    with pytest.raises(ValueError):s.configure({s.ENV:json.dumps(value)})


def candidate(value):
    return dict(pid=10,ppid=9,start_ticks=100,boot_id='boot',executable=value['prefix']+'/lib/micro_ros_agent/micro_ros_agent',
                argv=['agent','udp4','--middleware','dds','--port','2019','--ros-args','-r','__ns:=/drone1'])


def test_process_ancestry_exact_arguments_and_mapped_library(artifacts):
    value,prefix=overlay(artifacts);agent=candidate(value)
    root=dict(pid=9,ppid=1,start_ticks=90,boot_id='boot')
    maps=lambda pid:'000-001 r-x 0 00:00 0 '+str(prefix/'lib/libmicroxrcedds_agent.so.2.4')
    result=m.verify_agent(value,root,[agent],maps_reader=maps,process_reader=lambda pid:agent if pid==agent['pid'] else root)
    assert result['pid']==10
    for bad in ([],[agent,agent]):
        with pytest.raises(ValueError):m.verify_agent(value,root,bad)
    with pytest.raises(ValueError,match='library'):
        m.verify_agent(value,root,[agent],maps_reader=lambda pid:maps(pid)+'\n000-001 r-x 0 00:00 1 /installed/libmicroxrcedds_agent.so.2.4',process_reader=lambda pid:root)
    changed={**agent,'argv':agent['argv']+['--port','9999']}
    with pytest.raises(ValueError,match='arguments'):
        m.verify_agent(value,root,[changed],process_reader=lambda pid:root)
    with pytest.raises(ValueError,match='ancestry'):
        m.verify_agent(value,{**root,'start_ticks':91},[agent],process_reader=lambda pid:root)
    with pytest.raises(ValueError,match='changed'):
        m.verify_agent(value,root,[agent],maps_reader=maps,
            process_reader=lambda pid:{**agent,'argv':agent['argv']+['unexpected']} if pid==10 else root)


def test_drain_split_lines_caps_and_truncated_receipt(tmp_path):
    p=tmp_path/'trace'
    with p.open('w+b') as f:
        drain=m.Drain(f)
        drain.feed(b'ordinary log\nTFG_XRCE_');drain.feed(b'TRACE {"event":"a"}\n')
        for _ in range(600):drain.feed(b'TFG_XRCE_TRACE {}\n')
        drain.feed(b'TFG_XRCE_TRACE incomplete');drain.finish()
        assert drain.records==512 and drain.bytes<=m.BYTE_LIMIT
        assert 'Diagnostic output cap reached' in drain.errors and 'Truncated final trace line' in drain.errors
    assert p.read_bytes().startswith(b'TFG_XRCE_TRACE {"event":"a"}')


def test_output_failure_is_not_a_complete_capture():
    stream=Mock();stream.write.side_effect=OSError('disk failed')
    drain=m.Drain(stream)
    with pytest.raises(OSError):drain.feed(b'TFG_XRCE_TRACE {}\n')
    assert drain.records==0


def test_monitor_closure_with_fake_processes_and_clock(artifacts,tmp_path,monkeypatch):
    value,prefix=overlay(artifacts)
    source=tmp_path/'launch.log';source.write_bytes(b'TFG_XRCE_TRACE {}\n')
    root=dict(pid=9,ppid=1,start_ticks=90,boot_id='boot')
    s.atomic_record(prefix/'launch.json',{'process':root})
    socket_double=Mock();socket_double.summary.return_value={'state':'OFFLINE_DOUBLE','snapshots':1,'incomplete_snapshots':0}
    monkeypatch.setattr(m,'SocketRecorder',lambda *a,**kw:socket_double)
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
    assert m.run(prefix)==0
    report=s.read_json(prefix/'capture/monitor.json')
    assert report['phase']=='CLOSED' and report['capture_complete'] is True
    assert report['source_association_verified'] is False and report['movement_authorized'] is False
    assert (prefix/'capture/trace.log').stat().st_mode & 0o777==0o600


def manifest_file(tmp_path,value):
    path=tmp_path/'manifest.json';path.write_text(json.dumps(value['manifest']));return path


@pytest.mark.parametrize('action,profile',[('stop','two_drones_rover'),('restart','two_drones_rover'),('start','two_drones')])
def test_invalid_diagnostic_selection_precedes_all_backend_effects(artifacts,tmp_path,monkeypatch,action,profile):
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks
    backend=Mock(side_effect=AssertionError('No backend'))
    monkeypatch.setattr(life,'_backend',backend)
    assert life.run_lifecycle(action,profile=profile,diagnostic_agent_manifest=manifest_file(tmp_path,artifacts[0]))['status']=='BLOCKED'
    backend.assert_not_called();assert not locks.LOCK_ROOT.exists()


def test_explicit_selection_persisted_and_global_exclusion(artifacts,tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks
    entered=Event();finish=Event()
    def backend(action,gui,fd,process,log):
        record=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())
        assert record['diagnostic_agent']['manifest']==artifacts[0]['manifest']
        assert record['movement_authorized'] is False
        entered.set();assert finish.wait(5)
        return 0
    monkeypatch.setattr(life,'_backend',backend)
    with ThreadPoolExecutor() as executor:
        f=executor.submit(life.run_lifecycle,'start',profile='two_drones_rover',diagnostic_agent_manifest=manifest_file(tmp_path,artifacts[0]))
        assert entered.wait(5)
        try:
            for vehicle in ('v1','v2','v3'):
                with pytest.raises(locks.VehicleBusy):locks.reserve('foreign','offline',vehicle)
            assert life.run_lifecycle('stop')['status']=='BLOCKED'
        finally:finish.set()
        result=f.result()
    assert result['success'] and 'diagnostic_agent' in result['operation']
    assert locks.restriction() is None


def test_failed_diagnostic_backend_keeps_uncertain_restriction(artifacts,tmp_path,monkeypatch):
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks
    backend=Mock(return_value=1);monkeypatch.setattr(life,'_backend',backend)
    r=life.run_lifecycle('start',profile='two_drones_rover',diagnostic_agent_manifest=manifest_file(tmp_path,artifacts[0]))
    assert r['status']=='UNCONFIRMED' and backend.call_count==1
    assert life.run_lifecycle('start',profile='two_drones_rover')['status']=='BLOCKED'
    assert locks.restriction() is not None


@pytest.mark.parametrize('state',['ACTIVE','STOPPED','wrong_engine'])
def test_host_backend_pins_active_environment_and_sanitizes_default(artifacts,tmp_path,monkeypatch,state):
    from types import SimpleNamespace
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks,reconciliation_environment as env
    value=artifacts[0];locks.LOCK_ROOT.mkdir()
    record={'owner_id':OWNER,'profile':'two_drones_rover','diagnostic_agent':value}
    locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json',record)
    observed=dict(status='ACTIVE' if state=='wrong_engine' else state,**{k:value['manifest'][k] for k in ('engine_id','container_id','image_id')},name='container',created_at='time',state={})
    if state=='wrong_engine':observed['engine_id']='another-engine'
    monkeypatch.setattr(env,'inspect_environment',lambda:observed)
    backend=Mock(return_value=SimpleNamespace(returncode=0));monkeypatch.setattr(life.subprocess,'run',backend)
    if state!='ACTIVE':
        with pytest.raises(locks.VehicleBusy):life._backend('start',True,123,{},tmp_path/'backend.log')
        backend.assert_not_called()
    else:
        assert life._backend('start',True,123,{},tmp_path/'backend.log')==0
        assert json.loads(backend.call_args.kwargs['env'][s.ENV])==value
        record.pop('diagnostic_agent');locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json',record)
        monkeypatch.setenv(s.ENV,'untrusted inherited choice');monkeypatch.setenv('TFG_XRCE_TRACE','1')
        life._backend('start',True,123,{},tmp_path/'backend.log')
        assert s.ENV not in backend.call_args.kwargs['env'] and 'TFG_XRCE_TRACE' not in backend.call_args.kwargs['env']


@pytest.mark.parametrize('failure',[None,'monitor_exit','launch_error','monitor_failed','supervisor_exit'])
def test_supervisor_diagnostic_start_and_failure_do_not_spawn_second_agent(artifacts,tmp_path,monkeypatch,failure):
    from types import SimpleNamespace
    from simulation.ros2_gazebo.scripts import sim_processes as sup
    value,prefix=overlay(artifacts)
    monkeypatch.setenv(s.ENV,json.dumps(value));monkeypatch.setattr(sup,'diagnostic_api',lambda:s)
    monkeypatch.setattr(sup,'LOG_FILE',tmp_path/'launch.log');monkeypatch.setattr(sup,'PID_FILE',tmp_path/'pid')
    monkeypatch.setattr(sup,'DIAGNOSTIC_STATE',tmp_path/'diagnostic.json')
    monkeypatch.setattr(sup,'STATE',tmp_path/'processes.json')
    monkeypatch.setattr(sup,'snapshot',dict);monkeypatch.setattr(sup.signal,'signal',Mock())
    watcher=SimpleNamespace(pid=100,poll=lambda:1 if failure=='supervisor_exit' else None)
    child=SimpleNamespace(pid=200)
    popen=Mock(side_effect=[watcher,OSError('spawn failed') if failure=='launch_error' else child])
    monkeypatch.setattr(sup.subprocess,'Popen',popen)
    monkeypatch.setattr(sup,'read_process',lambda pid:None if failure=='monitor_exit' and pid==100 else sup.Process(pid,1,pid*10,('fake',),True))
    monkeypatch.setattr(sup,'start_rover_identity',lambda *a:None)
    monkeypatch.setattr(sup,'diagnostic_summary',lambda:{'monitor':{'phase':'FAILED' if failure=='monitor_failed' else 'OBSERVING'}})
    if failure:
        with pytest.raises((RuntimeError,OSError)):sup.start('two_drones_rover')
        assert popen.call_count==(1 if failure=='monitor_exit' else 2)
    else:
        result=sup.start('two_drones_rover')
        assert result['success'] and popen.call_count==2
        command=popen.call_args.args[0]
        assert command[:4]==['ros2','launch','ardupilot_gz_bringup','tfg_demo.launch.py']
        assert popen.call_args.kwargs['env']['AMENT_PREFIX_PATH'].startswith(str(prefix)+':')
        assert {(100,1000),(200,2000)}<=sup.remembered_identities()


def test_shutdown_retains_incomplete_diagnostic_as_evidence(tmp_path,monkeypatch):
    from simulation.ros2_gazebo.scripts import sim_processes as sup
    prefix=tmp_path/'old-overlay';(prefix/'capture').mkdir(parents=True)
    s.atomic_record(prefix/'capture/monitor.json',{'phase':'FAILED','capture_complete':False,'errors':['write failed']})
    state=tmp_path/'pointer';state.write_text(json.dumps({'prefix':str(prefix)}))
    monkeypatch.setattr(sup,'DIAGNOSTIC_STATE',state);monkeypatch.setattr(sup,'STATE',tmp_path/'processes')
    monkeypatch.setattr(sup,'PID_FILE',tmp_path/'pid')
    result=sup.shutdown(scan=dict,read=lambda pid:None,send=Mock(side_effect=AssertionError('no real signals')))
    assert result['success'] is True  # infrastructure closed; diagnostic did not become valid
    assert result['diagnostic_agent']['monitor']['capture_complete'] is False
    assert (prefix/'capture/monitor.json').exists()


def test_native_incomplete_marker_and_write_close_failure(tmp_path):
    p=tmp_path/'trace'
    with p.open('w+b') as f:
        d=m.Drain(f);d.feed(b'TFG_XRCE_TRACE {"event":"trace_limit","incomplete":true}\n');d.finish()
        assert 'Native diagnostic reports incomplete coverage' in d.errors
    f=Mock();f.fileno.return_value=-1
    with pytest.raises((OSError,ValueError)):m.Drain(f).finish()


def test_unknown_diagnostic_auxiliaries_block_without_becoming_signal_targets():
    from simulation.ros2_gazebo.scripts import sim_processes as sup
    a=sup.Process(10,1,100,('/tmp/tfg_diagnostic_agents/uuid/lib/micro_ros_agent/micro_ros_agent','udp4','__ns:=/drone1'))
    b=sup.Process(20,1,200,('/usr/bin/python3','/tmp/tfg_diagnostic_agents/uuid/monitor.py','/tmp/tfg_diagnostic_agents/uuid'))
    table={10:a,20:b}
    assert sup.select_owned(table,set())=={}
    assert set(p.pid for p in sup.unattributed_auxiliaries(table,{}))=={10,20}


@pytest.mark.parametrize('prepare_failure',[False,True])
def test_effective_backend_uses_only_pinned_container_and_validates_before_start(tmp_path,artifacts,prepare_failure):
    """Execute real Bash against inert, logging fake docker/metadata tools."""
    import subprocess,sys
    repo=Path(__file__).resolve().parents[1];project=tmp_path/'project';scripts=project/'simulation/ros2_gazebo/scripts';scripts.mkdir(parents=True)
    source=(repo/'simulation/ros2_gazebo/scripts/start_sim_backend.sh').read_text()
    source=source.replace('/tmp/tfg_simulation_control.lock',str(tmp_path/'local.lock'))
    (scripts/'start_sim_backend.sh').write_text(source)
    launch=project/'simulation/ros2_gazebo/launch';launch.mkdir();(launch/'tfg_demo.launch.py').write_text('# synthetic')
    bindir=tmp_path/'bin';bindir.mkdir();log=tmp_path/'calls.jsonl'
    docker=bindir/'docker';docker.write_text('''#!/usr/bin/python3
import json,os,sys
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if args[0]=='inspect':
 if '--format' in args:print('true')
elif args[0]=='exec':
 if args[-1]=='prepare' and os.environ['PREPARE_FAILURE']=='1':sys.exit(9)
 if 'ros2 topic list' in ' '.join(args):print('/ap/v1/status\\n/ap/v2/status\\n/ap/v3/status')
sys.exit(0)
''');docker.chmod(0o755)
    python=project/'.venv/bin/python';python.parent.mkdir(parents=True)
    python.write_text('''#!'''+sys.executable+'''
import os,sys,runpy
if sys.argv[1:]==['-m','tools.simulation_lifecycle','verify']:sys.exit(0)
sys.path.insert(0,os.environ['REPOSITORY'])
if sys.argv[1]=='-c':exec(sys.argv[2]);sys.exit(0)
sys.argv=sys.argv[2:]
runpy.run_module('tools.simulation_profiles',run_name='__main__')
''');python.chmod(0o755)
    result_dir=tmp_path/'lifecycle-result';result_dir.mkdir()
    env={**os.environ,'TFG_LIFECYCLE_RESULT_DIR':str(result_dir),'PATH':str(bindir)+':/usr/bin:/bin','CALLS':str(log),'PREPARE_FAILURE':'1' if prepare_failure else '0',
         'REPOSITORY':str(repo),'TFG_SIM_PROFILE':'two_drones_rover','TFG_SIM_START_CONTEXT':'{}',s.ENV:json.dumps(artifacts[0])}
    result=subprocess.run(['bash',str(scripts/'start_sim_backend.sh')],env=env,capture_output=True,text=True,timeout=10)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert not any(call[0]=='start' for call in calls)
    prepare=next(i for i,c in enumerate(calls) if c[-1]=='prepare')
    if prepare_failure:
        assert result.returncode!=0 and len(calls)==prepare+1
    else:
        assert result.returncode==0,(result.stdout,result.stderr)
        assert (result_dir/'acquisition.returncode').read_text().strip()=='0'
        assert (result_dir/'acquisition.stdout').exists() and (result_dir/'acquisition.stderr').exists()
        stop=next(i for i,c in enumerate(calls) if c[-1]=='stop')
        assert prepare<stop
        start=next(c for c in calls if c[0]=='exec' and '/tmp/tfg_sim_processes.py start' in ' '.join(c))
        assert artifacts[0]['manifest']['container_id'] in start
        assert 'TFG_DIAGNOSTIC_AGENT='+json.dumps(artifacts[0]) in start


def test_short_write_and_unterminated_trace_are_preserved_or_uncertain(tmp_path):
    f=Mock();f.write.return_value=1
    with pytest.raises(OSError,match='Short'):m.Drain(f).feed(b'TFG_XRCE_TRACE {}\n')
    path=tmp_path/'partial'
    with path.open('w+b') as f:
        drain=m.Drain(f);drain.feed(b'log TFG_XRCE_TRACE {"partial":');drain.finish()
        assert drain.errors==['Truncated final trace line','No diagnostic records observed']
    assert path.read_bytes()==b'TFG_XRCE_TRACE {"partial":'


def test_monitor_close_failure_keeps_partial_context_and_fails_closed(tmp_path,monkeypatch):
    path=tmp_path/'capture';path.mkdir()
    s.atomic_record(path/'monitor.json',{'phase':'CLOSED','capture_complete':True,'agent':{'pid':123},'trace_records':2})
    monkeypatch.setattr(m,'run',Mock(side_effect=OSError('close failed')))
    assert m.main([str(tmp_path)])==1
    report=s.read_json(path/'monitor.json')
    assert report['phase']=='FAILED' and report['capture_complete'] is False
    assert report['agent']=={'pid':123} and report['trace_records']==2
    assert report['source_association_verified'] is False


@pytest.mark.parametrize('changed',[False,True])
def test_stop_is_bound_to_original_diagnostic_environment(artifacts,tmp_path,monkeypatch,changed):
    from types import SimpleNamespace
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks,reconciliation_environment as env
    value=artifacts[0];locks.LOCK_ROOT.mkdir()
    execution=env.inspect_active_execution()  # TEST_FIXTURE execution of the artifacts fixture
    # The protected diagnostic close: descriptor, the execution recorded at its START and its boot fence.
    locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json',{'profile':'two_drones_rover','diagnostic_close_target':value,
                                                        'closing_diagnostic_session':True,'environment_execution':execution})
    observed={'status':'ACTIVE',**{k:value['manifest'][k] for k in ('container_id','engine_id','image_id')}}
    if changed:observed['container_id']='c'*64
    monkeypatch.setattr(env,'inspect_environment',lambda:observed)
    backend=Mock(return_value=SimpleNamespace(returncode=0));monkeypatch.setattr(life.subprocess,'run',backend)
    if changed:
        with pytest.raises(locks.VehicleBusy,match='no retargeting'):life._backend('stop',True,123,{},tmp_path/'backend.log')
        backend.assert_not_called()
    else:
        assert life._backend('stop',True,123,{},tmp_path/'backend.log')==0
        child=backend.call_args.kwargs['env']
        assert json.loads(child['TFG_DIAGNOSTIC_CLOSE_TARGET'])==value
        assert child['TFG_DIAGNOSTIC_CLOSE_BOOT_ID']==execution['container_boot_id']
        # The former shape (descriptor alone) degrades the pinned reader to the general selection: refused.
        locks.atomic_json(locks.LOCK_ROOT/'lifecycle.json',{'profile':'two_drones_rover','diagnostic_close_target':value})
        backend.reset_mock()
        with pytest.raises(locks.VehicleBusy,match='without its exact boot fence'):
            life._backend('stop',True,123,{},tmp_path/'backend.log')
        backend.assert_not_called()


def test_started_session_requires_explicit_stop_and_retains_target_history(artifacts,tmp_path,monkeypatch):
    from tools import simulation_lifecycle as life,vehicle_execution_lock as locks
    calls=[]
    def backend(step,gui,fd,process,log):
        lease=json.loads((locks.LOCK_ROOT/'lifecycle.json').read_text())
        calls.append(lease)
        return 0
    monkeypatch.setattr(life,'_backend',backend)
    result=life.run_lifecycle('start',profile='two_drones_rover',diagnostic_agent_manifest=manifest_file(tmp_path,artifacts[0]))
    path=locks.LOCK_ROOT.parent/'diagnostic_agent_session.json'
    assert json.loads(path.read_text())['state']=='STARTED'
    assert life.run_lifecycle('start')['status']=='BLOCKED'
    assert life.run_lifecycle('restart')['status']=='BLOCKED'
    assert life.run_lifecycle('stop',profile='two_drones_rover')['success']
    assert calls[-1]['diagnostic_close_target']==result['operation']['diagnostic_agent']
    saved=json.loads(path.read_text())
    assert saved['state']=='CLOSED' and saved['descriptor']==result['operation']['diagnostic_agent']


@pytest.mark.parametrize('running,code,expected',[('true',0,0),('false',0,0),('',9,9),('unknown',0,1)])
def test_stop_script_does_not_confuse_inspection_failure_with_stopped(tmp_path,artifacts,running,code,expected):
    import subprocess,sys
    repo=Path(__file__).resolve().parents[1];project=tmp_path/'project';scripts=project/'simulation/ros2_gazebo/scripts';scripts.mkdir(parents=True)
    script=scripts/'stop_sim_backend.sh'
    script.write_text((repo/'simulation/ros2_gazebo/scripts/stop_sim_backend.sh').read_text().replace('/tmp/tfg_simulation_control.lock',str(tmp_path/'lock')))
    python=project/'.venv/bin/python';python.parent.mkdir(parents=True)
    python.write_text('#!'+sys.executable+'\nimport sys\nif sys.argv[1]=="-c":exec(sys.argv[2])\n');python.chmod(0o755)
    bindir=tmp_path/'bin';bindir.mkdir();log=tmp_path/'calls'
    docker=bindir/'docker';docker.write_text('''#!/usr/bin/python3
import os,sys,json
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if args[0]=='inspect':
 print(os.environ['RUNNING']);sys.exit(int(os.environ['CODE']))
''');docker.chmod(0o755)
    env={**os.environ,'PATH':str(bindir)+':/usr/bin:/bin','CALLS':str(log),'RUNNING':running,'CODE':str(code),
         'TFG_DIAGNOSTIC_CLOSE_TARGET':json.dumps(artifacts[0]),'TFG_DIAGNOSTIC_CLOSE_BOOT_ID':'fixture-boot'}
    result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==expected,(result.stdout,result.stderr)
    calls=[json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0][-1]==artifacts[0]['manifest']['container_id']
    if running!='true' or code:
        assert len(calls)==1
    else:assert any(c[0]=='exec' and c[-1]=='stop' for c in calls)


def test_closure_target_does_not_require_current_helper_or_pair_revision(artifacts,monkeypatch):
    value=artifacts[0]
    monkeypatch.setattr(s,'PAIR',('0'*64,'1'*64))
    assert s.check_frozen_descriptor(value)==value
    with pytest.raises(ValueError):s.check_descriptor(value)
    changed={**value,'selection_sha256':'0'*64}
    with pytest.raises(ValueError):s.check_frozen_descriptor(changed)


@pytest.mark.parametrize('original_bug', [False, True])
def test_deployed_prepare_entry_without_repo_sibling(tmp_path, monkeypatch, original_bug):
    """Execute the deployed __main__/prepare, not the repository import path.

    Only fixture artifact hashes/root and readelf/process discovery are doubled.
    The original helper fails here looking for the deliberately absent selection.py.
    """
    import runpy
    import shutil
    from types import SimpleNamespace
    deployed = tmp_path/'bootstrap'; deployed.mkdir()
    entry = deployed/s.HELPERS['selection.py'].name
    wrapper = tmp_path/'wrapper'; wrapper.write_bytes(b'\x7fELF wrapper')
    library = tmp_path/'library'; library.write_bytes(b'\x7fELF library')
    pair = tuple(hashlib.sha256(p.read_bytes()).hexdigest() for p in (wrapper, library))
    source = Path(s.__file__).read_text()
    if original_bug:
        source = (Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_22/5d541497-25cb-4b23-af81-07808ade6eab/source_snapshots/tools/rover_xrce_trace/selection.py').read_text()
    source = source.replace(s.PAIR[0], pair[0]).replace(s.PAIR[1], pair[1])
    source = source.replace("ROOT = Path('/tmp/tfg_diagnostic_agents')", f'ROOT = Path({str(tmp_path/"overlays")!r})')
    entry.write_text(source)
    for logical, destination in s.HELPERS.items():
        if logical != 'selection.py':
            shutil.copyfile(Path(s.__file__).with_name(logical), deployed/destination.name)
    assert not (deployed/'selection.py').exists()
    host_source = deployed/'selection.py'
    host_source.write_text(source)
    namespace = runpy.run_path(str(host_source))
    manifest = dict(schema=s.SCHEMA, container_id='a'*64, image_id='sha256:'+'b'*64,
                    engine_id='engine', wrapper_path=str(wrapper), library_path=str(library),
                    wrapper_sha256=pair[0], library_sha256=pair[1])
    value = namespace['descriptor'](manifest, OWNER)
    host_source.unlink()
    monkeypatch.setenv(s.ENV, json.dumps(value))
    monkeypatch.delenv('LD_PRELOAD', raising=False)
    monkeypatch.delenv('LD_AUDIT', raising=False)
    original_iterdir = Path.iterdir
    monkeypatch.setattr(Path, 'iterdir', lambda p: iter(()) if p == Path('/proc') else original_iterdir(p))
    def readelf(command, **kwargs):
        assert command[:2] == ['readelf', '-d']
        text = ('(NEEDED) [libmicroxrcedds_agent.so.2.4]' if command[2] == str(wrapper)
                else '(SONAME) [libmicroxrcedds_agent.so.2.4]\n(NEEDED) [librmw_fastrtps_shared_cpp.so]')
        return SimpleNamespace(stdout=text)
    monkeypatch.setattr(s.subprocess, 'run', readelf)
    monkeypatch.setattr('sys.argv', [str(entry), 'prepare'])
    if original_bug:
        with pytest.raises(FileNotFoundError, match='selection.py'):
            runpy.run_path(str(entry), run_name='__main__')
        assert not Path(value['prefix']).exists()
        return
    runpy.run_path(str(entry), run_name='__main__')
    prefix = Path(value['prefix'])
    assert (prefix/'selection.json').exists()
    assert (prefix/'selection.py').read_bytes() == entry.read_bytes()
    # The monitor uses its sibling selection.py in the overlay, not bootstrap.
    monkeypatch.syspath_prepend(str(prefix))
    imported = runpy.run_path(str(prefix/'monitor.py'))
    assert imported['verify_overlay'](value)['status'] == 'BLOCKED'


def test_deployment_rejects_missing_helper_before_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(s, '__file__', str(tmp_path/'tfg_diagnostic_agent.py'))
    (tmp_path/'tfg_diagnostic_agent.py').write_text('# fixture')
    with pytest.raises(ValueError, match='helper missing'):
        s.deployment()


def test_reviewed_peer_build_pair_is_explicit_and_cannot_mix_generations():
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'tools/rover_xrce_trace/diagnostic-agent.peer.json').read_text())
    assert s.check_manifest(manifest) == manifest
    assert (manifest['wrapper_sha256'],manifest['library_sha256']) == s.PEER_PAIR
    for wrapper, library in ((s.PAIR[0],s.PEER_PAIR[1]), (s.PEER_PAIR[0],s.PAIR[1])):
        with pytest.raises(ValueError, match='incompatible'):
            s.check_manifest({**manifest,'wrapper_sha256':wrapper,'library_sha256':library})


def test_gui_exit_observation_is_separate_from_backend_and_visual_confirmation():
    import io
    drain=m.Drain(io.BytesIO())
    drain.feed(b"[ERROR] [gz sim-2]: process has died [pid 9013, exit code 134, cmd 'ruby /usr/bin/gz sim -v1 -g --force-version 8'].\n")
    assert drain.gui.summary()['state']=='EXITED'
    assert drain.gui.summary()['exit_code']==134
    assert drain.gui.summary()['visual_confirmation']=='OPERATOR_REQUIRED'
    drain.feed(b"[ERROR] [gz sim-1]: process has died [pid 9011, exit code 1, cmd 'ruby /usr/bin/gz sim -s world.sdf'].\n")
    assert drain.gui.summary()['pid']==9013
    unknown=m.GuiObservation();unknown.feed(b'[INFO] [gz sim-2]: process started with pid [9013]\n')
    assert unknown.summary()['state']=='UNKNOWN' and unknown.summary()['exit_code'] is None
    drain.feed(b"[ERROR] [gz sim-2]: process has died [pid 99, exit code 1, cmd 'ruby /usr/bin/gz sim -g'].\n")
    assert drain.gui.summary()['state']=='CONTRADICTORY'


@pytest.mark.parametrize('case',['valid','late_monitor','spent_samples','too_few_samples','stale'])
def test_capture_window_never_uses_stale_or_exhausted_diagnostics(case):
    record={'phase':'OBSERVING','errors':[],'monitor':{'boot_id':'b'},
        'started_monotonic':100.,'duration_limit_s':600.,'observation_monotonic':150.,
        'socket_inventory':{'error':None,'peer_waiting':None,'incomplete_snapshots':0,
            'sampling_limit_reached':False,'snapshots':5,'sample_limit':64,'interval_s':5.,
            'budget':m.SOCKET.record(),'journal_bytes_written':10000,
            'next_observation_monotonic':154.,'last_finished_monotonic':149.}}
    now=150.
    if case=='late_monitor':now=650.;record['observation_monotonic']=now
    elif case=='spent_samples':record['socket_inventory'].update(sampling_limit_reached=True,snapshots=64)
    elif case=='too_few_samples':record['socket_inventory']['snapshots']=50
    elif case=='stale':now=160.
    if case=='valid':assert m.capture_window(record,now=now,observed_boot_id='b')['movement_authorized'] is False
    else:
        with pytest.raises(ValueError):m.capture_window(record,now=now,observed_boot_id='b')


@pytest.mark.parametrize('case',['on_time','one_slot_short','late_visual','overdue','unknown_schedule',
                                 'last_stale','changed_budget','monitor_short','no_close_margin'])
def test_full_capture_and_close_schedule(case):
    record={'phase':'OBSERVING','errors':[],'monitor':{'boot_id':'b'},
        'started_monotonic':100.,'duration_limit_s':600.,'observation_monotonic':150.,
        'socket_inventory':{'error':None,'peer_waiting':None,'incomplete_snapshots':0,
            'sampling_limit_reached':False,'snapshots':23,'sample_limit':64,'interval_s':5.,
            'budget':m.SOCKET.record(),'journal_bytes_written':10000,
            'next_observation_monotonic':154.,'last_finished_monotonic':149.}}
    now=150.;socket=record['socket_inventory']
    if case=='one_slot_short':socket['snapshots']=24  # N*5=200, but final actual slot is at 349 < 350
    elif case=='late_visual':now=155.;record['observation_monotonic']=now
    elif case=='overdue':socket['next_observation_monotonic']=149.
    elif case=='unknown_schedule':socket['next_observation_monotonic']=None
    elif case=='last_stale':socket['last_finished_monotonic']=140.
    elif case=='changed_budget':socket['budget']={}
    elif case=='monitor_short':record['duration_limit_s']=249.
    elif case=='no_close_margin':socket['snapshots']=34
    if case=='on_time':
        result=m.capture_window(record,now=now,observed_boot_id='b')
        assert result['remaining_observations']==41
        assert result['last_programmable_observation_monotonic']==354.
        assert result['scheduled_not_observed'] and not result['movement_authorized']
    else:
        with pytest.raises(ValueError):m.capture_window(record,now=now,observed_boot_id='b')


def test_supervisor_wait_status_is_separate_from_monitor_receipt(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from simulation.ros2_gazebo.scripts import sim_processes as sup
    from tools.rover_xrce_trace.selection import atomic_record
    (tmp_path/'capture').mkdir()
    monkeypatch.setattr(sup,'diagnostic_api',lambda:SimpleNamespace(atomic_record=atomic_record))
    sup.record_monitor_exit(SimpleNamespace(pid=42),1,tmp_path,SimpleNamespace(pid=42,start_ticks=987))
    data=json.loads((tmp_path/'capture/monitor_exit.json').read_text())
    assert data['state']=='PARENT_WAIT_STATUS_OBSERVED' and data['return_code']==1
    assert not data['movement_authorized'] and data['start_ticks']==987
    with pytest.raises(ValueError):sup.record_monitor_exit(SimpleNamespace(pid=41),0,tmp_path,SimpleNamespace(pid=42))


def test_agent_scan_stable_zombie_does_not_read_exe(tmp_path,monkeypatch):
    proc=tmp_path/'proc';p=proc/'1358';p.mkdir(parents=True)
    fields=['Z','1']+['0']*17+['42'];(p/'stat').write_text('1358 (exiting ros2) '+' '.join(fields))
    monkeypatch.setattr(m.os,'readlink',lambda path:pytest.fail('stable zombie has no executable'))
    assert m.agents(proc)==[]


def test_agent_scan_denied_live_executable_retains_unknown(tmp_path,monkeypatch):
    proc=tmp_path/'proc';p=proc/'1358';p.mkdir(parents=True)
    fields=['S','1']+['0']*17+['42'];(p/'stat').write_text('1358 (live) '+' '.join(fields))
    def denied(path):raise PermissionError('synthetic permission denied')
    monkeypatch.setattr(m.os,'readlink',denied)
    found=m.agents(proc)
    assert found[0]['observation_state']=='UNKNOWN'
    with pytest.raises(ValueError,match='UNKNOWN'):m.verify_agent({},None,found)


def test_agent_scan_disappearance_is_not_permission_failure(tmp_path):
    proc=tmp_path/'proc';(proc/'1358').mkdir(parents=True)
    assert m.agents(proc)==[]

@pytest.mark.parametrize('kind',['zombie','denied'])
def test_monitor_drain_to_receipt_with_exit_inventory(artifacts,tmp_path,monkeypatch,kind):
    value,prefix=overlay(artifacts)
    source=tmp_path/'launch.log';source.write_bytes(b'TFG_XRCE_TRACE {}\n')
    root=dict(pid=9,ppid=1,start_ticks=90,boot_id='boot')
    s.atomic_record(prefix/'launch.json',{'process':root})
    proc=tmp_path/'proc';p=proc/'1358';p.mkdir(parents=True)
    fields=['Z' if kind=='zombie' else 'S','1']+['0']*17+['42']
    (p/'stat').write_text('1358 (exiting query) '+' '.join(fields))
    original_link=m.os.readlink
    def link(path,*a,**kw):
        if str(path)==str(p/'exe'):raise PermissionError('fixture denied exe')
        return original_link(path,*a,**kw)
    monkeypatch.setattr(m.os,'readlink',link)
    real_agents=m.agents
    sock=Mock();sock.summary.return_value={'state':'OFFLINE_DOUBLE','snapshots':1,'incomplete_snapshots':0}
    monkeypatch.setattr(m,'SocketRecorder',lambda *a,**kw:sock)
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
    monkeypatch.setattr(m,'agents',lambda:real_agents(proc) if clock[0]>1 else [candidate(value)])
    def verify(value,root,candidates,**kw):
        if any(c.get('observation_state')=='UNKNOWN' for c in candidates):raise ValueError('Agent inventory UNKNOWN')
        return candidate(value)
    monkeypatch.setattr(m,'verify_agent',verify)
    monkeypatch.setattr(m,'launch_candidates',lambda root:m.agents())
    rc=m.main([str(prefix)]);report=s.read_json(prefix/'capture/monitor.json')
    assert report['phase']=='CLOSED'
    assert report['capture_complete'] is True and rc==0
    assert (prefix/'capture/trace.log').read_bytes()==b'TFG_XRCE_TRACE {}\n'


def test_root_liveness_does_not_require_zombie_executable(tmp_path,monkeypatch):
    proc=tmp_path/'proc';(proc/'9').mkdir(parents=True);(proc/'sys/kernel/random').mkdir(parents=True)
    (proc/'sys/kernel/random/boot_id').write_text('boot')
    fields=['Z','1']+['0']*17+['90'];(proc/'9/stat').write_text('9 (launch) '+' '.join(fields))
    monkeypatch.setattr(m.os,'readlink',lambda path:pytest.fail('liveness does not need exe'))
    root={'pid':9,'start_ticks':90,'boot_id':'boot'}
    assert m.root_alive(root,proc) is False
    fields[0]='S';(proc/'9/stat').write_text('9 (launch) '+' '.join(fields))
    assert m.root_alive(root,proc) is True
    assert m.root_alive({**root,'start_ticks':91},proc) is False


@pytest.mark.parametrize('after',['same_zombie','live_denied','recycled_zombie','disappeared'])
def test_exe_denied_after_stat_requires_positive_same_incarnation_exit(tmp_path,monkeypatch,after):
    proc=tmp_path/'proc';p=proc/'5418';p.mkdir(parents=True)
    def stat(state,ticks):return '5418 (fixture exit race) '+' '.join([state,'1']+['0']*17+[str(ticks)])
    (p/'stat').write_text(stat('S',42))
    def denied(path):
        if after=='same_zombie':(p/'stat').write_text(stat('Z',42))
        elif after=='recycled_zombie':(p/'stat').write_text(stat('Z',43))
        elif after=='disappeared':(p/'stat').unlink()
        raise PermissionError(13,'fixture /proc/exe inaccessible')
    monkeypatch.setattr(m.os,'readlink',denied)
    observed=m.agents(proc)
    if after=='same_zombie':assert observed==[]
    else:
        assert len(observed)==1 and observed[0]['observation_state']=='UNKNOWN'
        assert observed[0]['state_before']=={'state':'S','start_ticks':'42'}
        assert observed[0]['states_after_denial']
