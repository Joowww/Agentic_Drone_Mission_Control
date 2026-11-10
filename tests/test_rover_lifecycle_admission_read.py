"""Archived metadata replay and full lifecycle/driver with synthetic backends only."""
import copy
import json
import shutil
import traceback
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools import reconciliation_environment as e, simulation_lifecycle as life, vehicle_execution_lock as locks
from tools.rover_xrce_trace import passive_trial as driver, selection as s, historical_disposition as d
from tools.rover_xrce_trace.budget import SOCKET
from tests.test_rover_model_selection import model
from tests.test_rover_transport_driver import selection

HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_socket_capture_2026_10_28/6021022b-f8eb-44c5-a785-0c6adc6644ea'


def read(path):return json.loads(path.read_bytes())


def metadata_run(value,boot):
    def run(argv,**kw):
        assert argv[0]=='docker' and kw['timeout']==3 and kw['check'] is False
        if argv[1]=='info':out=json.dumps(value['engine_id'])
        elif argv[1]=='ps':out=value['container_id']
        elif argv[1]=='inspect':out=json.dumps({k:value[k] for k in ('container_id','name','created_at','image_id','state')})
        elif argv[1]=='exec':out=boot
        else:raise AssertionError('Only fake metadata/boot operations permitted')
        return NS(returncode=0,stdout=out+'\n',stderr='')
    return run


@pytest.mark.parametrize('name',['environment-before.json','environment-after.json','post-environment-before.json','post-environment-after.json','start-lifecycle/rover_environment_reference.json'])
def test_all_archived_views_pass_but_do_not_reconstruct_missing_failed_read(monkeypatch,name):
    expected=read(HISTORY/'start-lifecycle/environment_execution_reference.json');v=read(HISTORY/name)
    if name.startswith('start-lifecycle'):v={'status':'ACTIVE',**v['environment'],'state':v['pre_start_state']}
    monkeypatch.setattr(e.subprocess,'run',metadata_run(v,expected['container_boot_id']))
    assert e.inspect_active_execution()==expected
    life.assert_environment_execution(expected)


@pytest.mark.parametrize('field,bad,reason',[
 ('created_at','secret-invalid-timestamp','INVALID_WALL_TIMESTAMP'),
 ('container_id','secret-short-id','INVALID_ID_FORMAT'),
 ('image_id','secret-invalid-image','INVALID_ID_FORMAT'),
 ('state.StartedAt','secret-invalid-time','INVALID_WALL_TIMESTAMP'),
 ('state.Pid',True,'UNKNOWN_OR_CONTRADICTORY_EXECUTION'),
 ('state.Running',False,'UNKNOWN_OR_CONTRADICTORY_EXECUTION'),
 ('state.Paused',True,'UNKNOWN_OR_CONTRADICTORY_EXECUTION'),
 ('state',None,'MISSING_OR_INVALID_OBJECT')])
def test_execution_validation_still_rejects_with_safe_field_diagnostic(field,bad,reason):
    value=read(HISTORY/'environment-before.json')
    if field.startswith('state.'):value['state'][field.split('.')[1]]=bad
    else:value[field]=bad
    with pytest.raises(e.ActiveExecutionReadError) as raised:e.active_execution_identity(value,'SYNTHETIC-BOOT')
    assert raised.value.diagnostic['field']==field and raised.value.diagnostic['reason']==reason
    assert 'secret-' not in str(raised.value)
    assert 'secret-' not in ''.join(traceback.format_exception(raised.value))


@pytest.mark.parametrize('outcome',['success','boot_long','boot_empty','boot_failure','metadata_json','execution_changed','unclassified_error'])
def test_backend_ready_acquired_through_lifecycle_to_reader_admission_or_protected_close(model,monkeypatch,tmp_path,outcome):
    env=read(HISTORY/'environment-before.json')
    for k in ('engine_id','container_id','image_id'):env[k]=model['manifest'][k]
    boot=locks.process_identity()['boot_id'];expected=e.active_execution_identity(env,boot)
    target={'descriptor':model,'state':'CLOSED','closed_by':str(uuid4()),'operation_path':'SYNTHETIC prior closed operation'}
    locks.LOCK_ROOT.parent.mkdir(parents=True,exist_ok=True);locks.atomic_json(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json',target)
    monkeypatch.setattr(d,'diagnostic_precheck_locked',lambda **kw:{'precheck_satisfied':True,'current_environment_execution':copy.deepcopy(expected)})
    holder={'ready':False,'closing':False};normal=metadata_run(env,boot)
    def run(argv,**kw):
        if holder['ready'] and not holder['closing']:
            if outcome in ('boot_long','boot_empty','boot_failure') and argv[1]=='exec':
                return NS(returncode=1 if outcome=='boot_failure' else 0,
                          stdout='SECRET'*30 if outcome=='boot_long' else '' if outcome=='boot_empty' else boot,stderr='SECRET')
            if outcome=='metadata_json' and argv[1]=='inspect':return NS(returncode=0,stdout='SECRET invalid JSON',stderr='SECRET')
            if outcome=='execution_changed':
                changed=copy.deepcopy(env);changed['state']['StartedAt']='2026-10-28T08:00:00Z'
                return metadata_run(changed,boot)(argv,**kw)
        return normal(argv,**kw)
    monkeypatch.setattr(e.subprocess,'run',run)
    public_reader=e.inspect_active_execution
    def observe():
        if holder['ready'] and not holder['closing'] and outcome=='unclassified_error':raise ValueError('SECRET do not persist')
        return public_reader()
    monkeypatch.setattr(e,'inspect_active_execution',observe)
    monkeypatch.setattr(driver.time,'monotonic',lambda:100.)
    seen=[]
    def backend(action,gui,fd,process,log):
        lease=read(locks.LOCK_ROOT/'lifecycle.json');seen.append(action)
        assert fd>=0
        if action=='start' or outcome!='success':assert lease['environment_execution']==expected
        if action=='start':
            pointer=lease['diagnostic_agent'];prefix=Path(pointer['prefix'])
            shutil.copytree(Path(model['prefix']),prefix)
            s.atomic_record(prefix/'selection.json',{'descriptor':pointer,'helpers':pointer['helpers']})
            monitor={'lifecycle_id':lease['owner_id'],'phase':'OBSERVING','errors':[],
                'monitor':{'boot_id':boot},'started_monotonic':90.,'observation_monotonic':100.,'duration_limit_s':600.,
                'socket_inventory':{'budget':SOCKET.record(),'snapshots':1,'journal_bytes_written':1000},
                'identity_bridge':{'verified_overlay_library':True},'model_source':{'verified_overlay_library':True}}
            s.atomic_record(prefix/'capture/monitor.json',monitor)
            locks.atomic_json(log.parent/'acquisition.stdout',{'success':True,'decision':{'accepted':True,'coverage':{'table_eof':True}},'synthetic':True})
            (log.parent/'acquisition.returncode').write_text('0\n');(log.parent/'acquisition.stderr').write_text('')
            log.write_text('SIMULATION READY — SYNTHETIC BACKEND ONLY\n');holder['ready']=True
        else:
            assert lease['diagnostic_close_target']['lifecycle_id']==target_after['descriptor']['lifecycle_id']
            if outcome!='success':assert lease['closing_failed_start']['state']=='UNCONFIRMED'
            log.write_text('SYNTHETIC cleanup success; no process or signal\n')
        return 0
    monkeypatch.setattr(life,'_backend',backend)
    ap=tmp_path/'agent.json';ap.write_text(json.dumps(model['manifest']));target_after={}
    def start():return life.run_lifecycle('start',gui=False,profile='two_drones_rover',diagnostic_agent_manifest=ap)
    admit=Mock(side_effect=lambda owner:driver.admit_from_prefix(s.ROOT/owner))
    reader=Mock(return_value={'synthetic':True,'executed':True,'no_real_receiver':True})
    def stop(owner):
        holder['closing']=True;target_after.update(read(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json'))
        # Synthetic previous CLI owner is gone; no real process is queried/signalled.
        monkeypatch.setattr(locks,'identity_alive',lambda identity:False)
        return life.run_lifecycle('stop',gui=False,profile='two_drones_rover',close_owner=owner if target_after['state']=='UNCONFIRMED' else None)
    ports=NS(start=start,admit=admit,reader=reader,stop=stop,post=lambda owner:{'synthetic':True})
    result=driver.execute_once(tmp_path/'driver',ports)
    assert seen==['start','stop'] and result['stop']['status']=='SUCCESS'
    original=result['start']['operation'];persisted=read(Path(original['log_path']).parent/'operation.json')
    assert persisted==original and read(locks.LOCK_ROOT.parent/'diagnostic_agent_session.json')['state']=='CLOSED'
    assert locks.restriction() is None
    if outcome=='success':
        assert original['state']=='FINISHED' and result['admission']['measurement_allowed']
        admit.assert_called_once();reader.assert_called_once()
    else:
        assert original['state']=='UNCONFIRMED' and 'finished_at' not in original
        detail=original['admission_failure'];assert detail['operation']=='start' and detail['phase']=='after_backend'
        assert {'reader_operation','reader_source','reader_field','reader_reason'}<=detail.keys()
        assert 'SECRET' not in json.dumps(original)
        if outcome=='boot_long':assert detail['reader_field']=='stdout' and detail['reader_reason']=='BOOT_ID_OUTPUT_LIMIT'
        admit.assert_not_called();reader.assert_not_called()


@pytest.mark.parametrize('case',['valid','missing','association','native_changed','source_changed'])
def test_selector_consumes_host_review_in_existing_reader_selection(selection,monkeypatch,case):
    root,ap,rp,agent,reader=selection
    names=['tools/simulation_lifecycle.py','tools/reconciliation_environment.py']
    changes={}
    for name in names:
        path=root/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_text('SYNTHETIC host helper')
        import hashlib
        value=hashlib.sha256(path.read_bytes()).hexdigest();reader['source_hashes'][name]=value
        changes[name]={'before':'0'*64,'after':value}
    review={'schema':'tfg.passive-host-helper-review/1','source_changes':changes,
            'native_binary_unchanged':True,'native_dependencies_unchanged':True}
    reader['helper_review']={'host_source_review':review}
    if case=='missing':reader.pop('helper_review')
    elif case=='association':review['source_changes'][names[0]]['after']='f'*64
    elif case=='native_changed':review['native_binary_unchanged']=False
    elif case=='source_changed':(root/names[0]).write_text('changed')
    rp.write_text(json.dumps(reader));command=Mock();monkeypatch.setattr(driver.LocalPorts,'command',command)
    if case=='valid':
        ports=driver.LocalPorts(root,root,ap,rp)
        ports.reader_selection['helper_review']['host_source_review']['source_changes'][names[0]]['after']='f'*64
        # In-memory mutation after construction is also rejected before start.
        with pytest.raises(ValueError):ports.start()
    else:
        with pytest.raises(ValueError):driver.LocalPorts(root,root,ap,rp)
    command.assert_not_called()
