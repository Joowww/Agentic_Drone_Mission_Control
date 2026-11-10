"""Synthetic failed start -> real lifecycle with fake cleanup -> pure classification.

No Docker, ROS, simulator, native binary, real signal or disposition application.
"""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4
import pytest

from tools import simulation_lifecycle as lifecycle,vehicle_execution_lock as locks
from tools.rover_xrce_trace import session_precheck as p,selection as s,historical_disposition as d
from tests.test_failed_start_protected_close import failed,model
from tests.test_rover_present_recovery import review_data,proc,tree


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n')


def seal(root):
    files=[{'path':str(f.relative_to(root)),'size_bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(root.rglob('*')) if f.is_file() and f.name!='manifest.json']
    dump(root/'manifest.json',{'schema':'tfg.evidence-manifest/1','scope':'EXPLICIT_SYNTHETIC_OFFLINE_FIXTURE','files':files})


@pytest.fixture
def closed_failed(failed,monkeypatch,tmp_path):
    owner,start,target=failed;pointer=target['descriptor'];boot='boot'
    identity={k:pointer['manifest'][k] for k in ('engine_id','container_id','image_id')}
    identity.update(name='/tfg-ardupilot-gazebo',created_at='2026-01-01T00:00:00Z')
    state={'Status':'running','Running':True,'Pid':123,'Paused':False,'Restarting':False,'Dead':False,'StartedAt':'2026-01-02T00:00:00Z','FinishedAt':'0001-01-01T00:00:00Z'}
    execution={'persistent_identity':identity,'container_started_at':state['StartedAt'],'container_boot_id':boot}
    start.update(environment_execution=execution,movement_authorized=False,started_at='2026-01-03T00:00:00+00:00')
    dump(Path(target['operation_path']),start);dump(locks.LOCK_ROOT/'lifecycle.json',start)
    environment_reference={'lifecycle_id':owner,'profile':'two_drones_rover','environment':identity,'pre_start_state':state}
    root={'pid':100,'start_ticks':1000,'boot_id':boot}
    launch={**p.FLAGS,'process':root}
    selection={**p.FLAGS,'descriptor':pointer,'helpers':pointer['helpers']}
    monitor={**p.FLAGS,'kind':'PASSIVE_DIAGNOSTIC_MONITOR','lifecycle_id':owner,'phase':'INCOMPLETE','capture_complete':False,
        'errors':['SYNTHETIC missing monitor observation'],
        'agent':{'pid':101,'start_ticks':1010,'boot_id':boot,'executable':pointer['prefix']+'/lib/micro_ros_agent/micro_ros_agent',
                 'mapped_native_library':pointer['prefix']+'/lib/libmicroxrcedds_agent.so.2.4','library_sha256':pointer['manifest']['library_sha256']},
        'monitor':{'pid':102,'start_ticks':1020,'boot_id':boot}}
    captured={}
    def backend(action,*args):
        assert action=='stop' and locks.restriction()['closing_failed_start']==start
        request={**p.FLAGS,'lifecycle_id':owner,'selection_sha256':pointer['selection_sha256'],
            'cleanup_owner':{'pid':103,'start_ticks':1030,'boot_id':boot},'source':'PROTECTED_PROCESS_CLEANUP',
            'observer_errors':['SYNTHETIC retained parent missing'],'requested_at_utc':locks.utc_now()}
        finished={**request,'finished_at_utc':locks.utc_now(),'infrastructure_cleanup_complete':True}
        report={'success':True,'signals':[dict(root,signal='SIGINT',process={**root,'diagnostic_selection_sha256':s.digest(pointer)})],
                'errors':[],'remaining':[],'unattributed_auxiliaries':[],'diagnostic_agent':{'monitor':monitor,'selection':{**pointer,**p.FLAGS}}}
        captured.update(request=request,finished=finished,report=report)
        args[-1].write_text(json.dumps(report)+'\nSIMULATION STOPPED\n')
        return 0
    monkeypatch.setattr(lifecycle,'_backend',backend)
    response=lifecycle.run_lifecycle('stop',gui=False,profile='two_drones_rover',close_owner=owner)
    assert response['status']=='SUCCESS'
    assert json.loads(Path(target['operation_path']).read_bytes())==start
    final=json.loads((locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').read_bytes())
    inventory={'owned':[],'ambiguous':[],'agents':[],'boot_id':boot,
        'state_files':{p.POINTER:json.dumps({**pointer,**p.FLAGS})},
        'files':{pointer['prefix']+'/'+n:json.dumps(v) for n,v in [('selection.json',selection),('launch.json',launch),('capture/monitor.json',monitor)]}}
    archive=tmp_path/'closure-archive';start_archive=tmp_path/'start-archive'
    dump(start_archive/'start-lifecycle/operation.json',start)
    dump(start_archive/'start-lifecycle/rover_environment_reference.json',environment_reference);seal(start_archive)
    dump(archive/'original-restriction.json',start);dump(archive/'stop-lifecycle/operation.json',response['operation'])
    (archive/'stop-lifecycle/backend.log').write_text(json.dumps(captured['report'])+'\nSIMULATION STOPPED\n')
    dump(archive/'protected-stop.stdout',response)
    dump(archive/'protected-stop-command.json',{'return_code':0,'error':None,'finished_at_utc':locks.utc_now()})
    dump(archive/'after-observation.json',{'at_utc':locks.utc_now(),'inventory':inventory,'diagnostic':{'monitor':monitor,'monitor_exit':{'state':'UNKNOWN','return_code':None}}})
    dump(archive/'after-host.json',{'at_utc':locks.utc_now(),'target':final,'restriction':None,'files':{}})
    index=[]
    for n,v in [('selection.json',selection),('launch.json',launch),('capture/monitor.json',monitor),('capture/closure-request.json',captured['request']),('capture/cleanup-finished.json',captured['finished'])]:
        path='sdk/'+n;dump(archive/path,v)
        index.append({'path':pointer['prefix']+'/'+n,'archive_path':path,'sha256':hashlib.sha256((archive/path).read_bytes()).hexdigest(),'stable_stat':True,'truncated_prefix':False})
    dump(archive/'after-files.json',index);seal(archive)
    reference=p.closure_archive_reference(archive);reference.update(layout=p.PROTECTED_FAILED_LAYOUT,start_archive=p.closure_archive_reference(start_archive))
    records=dict(target=final,start_operation=copy.deepcopy(start),stop_operation=response['operation'],environment_reference=environment_reference,
        environment={'status':'ACTIVE',**identity,'state':state},inventory=inventory,selection=selection,launch=launch,monitor=monitor,historical_evidence=reference)
    return records,archive,start_archive


def test_failed_start_protected_success_is_classified_without_rewriting_history(closed_failed):
    records,_,_=closed_failed;before=copy.deepcopy(records)
    result=p.classify_last_session(**records)
    assert result['start_outcome']=='FAILED_START_INFRASTRUCTURE_CLOSED',result
    assert result['infrastructure_closure']=='VERIFIED_FROM_RECORDS'
    assert result['pointer_classification']==d.CLASS and result['status']=='BLOCKED'
    assert records==before and records['start_operation']['state']=='UNCONFIRMED'
    assert 'finished_at' not in records['start_operation']
    assert records['monitor']['phase']=='INCOMPLETE'
    current={'complete':True,'observed_monotonic':10,'restriction':None,'guards':{},'other_sessions':[],'host_processes':[],'host_boot_id':'synthetic'}
    precheck=d.diagnostic_precheck(records,current,{},now=10)
    assert not precheck['precheck_satisfied'] and precheck['conditions']['historical_proof']
    assert precheck['reason']=='Historical diagnostics incomplete; separate scope review required'
    review=d.dry_run(records,current,now=10)
    assert review['status']=='BLOCKED' and review['scope_sha256'] is None
    assert review['required_review_protocol']=='CURRENT_RESOURCE_REVIEW_V1'
    with pytest.raises(ValueError,match='current-resource scope review required'):
        p.verified_closure_archive(records['historical_evidence'])


@pytest.mark.parametrize('bad',['other_owner','environment','stop_execution','link','partial_cleanup','uncertain_stop','post_inventory','current_process','original_altered','missing_proof','descriptor','index_wrong_path','index_ambiguous','report_selection','signal_identity'])
def test_failed_start_closure_rejects_mismatch_or_missing_associations(closed_failed,bad):
    records,archive,_=closed_failed
    # Resealed synthetic fixtures test semantic checks, not just manifest integrity.
    if bad=='other_owner':records['target']['closed_by']=str(uuid4())
    elif bad=='environment':records['environment']['engine_id']='another-engine'
    elif bad=='stop_execution':
        path=archive/'stop-lifecycle/operation.json';v=json.loads(path.read_text());v['environment_execution']['container_boot_id']='another-boot';dump(path,v);seal(archive)
    elif bad=='link':
        value=json.loads((archive/'stop-lifecycle/operation.json').read_text());value['closing_failed_start']['error']='tampered';dump(archive/'stop-lifecycle/operation.json',value);seal(archive)
    elif bad=='partial_cleanup':
        path=archive/'sdk/capture/cleanup-finished.json';v=json.loads(path.read_text());v['infrastructure_cleanup_complete']=False;dump(path,v)
        index=json.loads((archive/'after-files.json').read_text());next(e for e in index if e['archive_path']=='sdk/capture/cleanup-finished.json')['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();dump(archive/'after-files.json',index);seal(archive)
    elif bad=='uncertain_stop':records['stop_operation']['state']='UNCONFIRMED'
    elif bad=='post_inventory':
        path=archive/'after-observation.json';v=json.loads(path.read_text());v['inventory']['owned']=[{'pid':999}];dump(path,v);seal(archive)
    elif bad=='current_process':records['inventory']['owned']=[{'pid':999}]
    elif bad=='original_altered':
        path=archive/'original-restriction.json';path.write_bytes(path.read_bytes()+b' ')
    elif bad=='missing_proof':records['historical_evidence']=None
    elif bad=='descriptor':records['target']['descriptor']['helpers']={}
    elif bad=='index_wrong_path':
        path=archive/'after-files.json';index=json.loads(path.read_text());index[0]['path']='/tmp/another-session/selection.json';dump(path,index);seal(archive)
    elif bad=='index_ambiguous':
        path=archive/'after-files.json';index=json.loads(path.read_text());index.append(index[0]);dump(path,index);seal(archive)
    elif bad in ('report_selection','signal_identity'):
        path=archive/'stop-lifecycle/backend.log';v=json.loads(path.read_text().splitlines()[0])
        if bad=='report_selection':v['diagnostic_agent']['selection']={}
        else:v['signals'][0]['process']['start_ticks']+=1
        path.write_text(json.dumps(v)+'\nSIMULATION STOPPED\n');seal(archive)
    if bad not in {'original_altered','missing_proof'}:
        records['historical_evidence']['manifest_sha256']=hashlib.sha256((archive/'manifest.json').read_bytes()).hexdigest()
    result=p.classify_last_session(**records)
    assert result['pointer_classification']=='UNKNOWN_OR_CONTRADICTORY' and result['status']=='BLOCKED',result


def test_remaining_present_review_route_accepts_same_failed_close_proof_offline(closed_failed,review_data):
    records,_,_=closed_failed;_,current,now=review_data
    records.update(recovery_basis='CURRENT_RESOURCE_REVIEW_V1')
    ctx=current['resources']['context']
    records['inventory'].update(query_context_before={k:ctx[k] for k in ('boot_id','net_namespace','pid_namespace','time_namespace')})
    records['inventory']['query_context_after']=dict(records['inventory']['query_context_before'])
    report=d.dry_run(records,current,now=now)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['scope']['historical']['start_operation']['state']=='UNCONFIRMED'
    assert report['scope']['historical']['monitor']['phase']=='INCOMPLETE'
    assert not report['opening_authorized'] and not report['movement_authorized']


def test_explicit_proof_file_is_usable_by_existing_locked_precheck(closed_failed,monkeypatch,tmp_path):
    records,_,_=closed_failed
    path=tmp_path/'reference.json';dump(path,records['historical_evidence'])
    current={'complete':True,'observed_monotonic':10,'restriction':None,'guards':{},'other_sessions':[],'host_processes':[],'host_boot_id':'synthetic'}
    monkeypatch.setattr(d,'current_records',lambda context:(copy.deepcopy(records),copy.deepcopy(current)))
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{'status':'NOT_ATTEMPTED'})
    monkeypatch.setattr(d.time,'monotonic',lambda:10)
    result=d.current_diagnostic_precheck(evidence=path)
    assert result['historical_classification']['start_outcome']=='FAILED_START_INFRASTRUCTURE_CLOSED'
    assert not result['precheck_satisfied'] and result['conditions']['historical_proof']
