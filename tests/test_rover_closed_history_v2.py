"""Protocol proof over immutable archived originals; all applications in /tmp."""
import copy
import json
from pathlib import Path
import pytest
from tools.rover_xrce_trace import historical_disposition as d
from tools.rover_xrce_trace.session_precheck import closure_archive_reference,verified_closure_archive,POINTER

HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/5379b30c-ac91-4cc8-808b-a7c28bb41801'

@pytest.fixture
def records():
    ref=closure_archive_reference(HISTORY);r=verified_closure_archive(ref);pointer=r['target']['descriptor']
    r['environment']={'status':'ACTIVE',**r['environment_reference']['environment'],'state':r['environment_reference']['pre_start_state']}
    r['inventory']={'owned':[],'ambiguous':[],'agents':[],'boot_id':r['monitor']['monitor']['boot_id'],'state_files':{POINTER:json.dumps({**pointer,'status':'BLOCKED','movement_authorized':False,'source_association_verified':False})}}
    r['historical_evidence']=ref;return r

@pytest.fixture
def current():return dict(complete=True,observed_monotonic=10,restriction=None,guards={},other_sessions=[],host_processes=[],host_boot_id='fixture')


def test_content_proof_not_uuid_and_history_preserved(records,current,tmp_path):
    before=copy.deepcopy(records);report=d.dry_run(records,current,now=10)
    assert report['status']=='DRY_RUN_ELIGIBLE' and report['scope']['protocol']=='CLOSURE_DISPOSITION_V2'
    owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256'];auth=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}'
    engine=d.OfflineDisposition(tmp_path/'audit',clock=lambda:10,owner=owner)
    audit=engine.apply(records,lambda:current,scope_sha256=sha,authorization=auth)
    assert audit['schema']=='tfg.diagnostic-disposition/2' and audit['status']=='DISPOSED_DIAGNOSTICALLY_INCOMPLETE'
    assert audit==engine.query() and records==before and not audit['opening_authorized']
    assert engine.apply(records,lambda:pytest.fail('No replay'),scope_sha256=sha,authorization=auth)==audit
    assert d.assess_disposition(records,current,audit,now=10)['historical_pointer_resolved']
    assert not d.assess_disposition(records,current,audit,now=14)['historical_pointer_resolved']


@pytest.mark.parametrize('change',['owner','stop','selection','guards','process','query','scope'])
def test_changes_or_unknowns_block(records,current,tmp_path,change):
    report=d.dry_run(records,current,now=10);owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256']
    if change=='owner':records['target']['descriptor']['lifecycle_id']='11111111-1111-4111-8111-111111111111'
    elif change=='stop':records['stop_operation']['finished_at']='bad'
    elif change=='selection':records['selection']['helpers']={}
    elif change=='guards':current['guards']={'v3.json':'UNCONFIRMED'}
    elif change=='process':current['host_processes']=[{'pid':2}]
    elif change=='query':current['complete']=False
    else:sha='0'*64
    engine=d.OfflineDisposition(tmp_path/'audit',clock=lambda:10,owner=owner)
    with pytest.raises(ValueError):engine.apply(records,lambda:current,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert engine.query()['status']=='NOT_ATTEMPTED'


def test_execution_change_between_checks_rejected_even_same_historical_digest(records,current,tmp_path):
    report=d.dry_run(records,current,now=10);owner=records['target']['descriptor']['lifecycle_id'];sha=report['scope_sha256'];calls=[]
    def reader():
        calls.append(1)
        if len(calls)==2:current['host_boot_id']='changed'
        return current
    e=d.OfflineDisposition(tmp_path/'audit',clock=lambda:10,owner=owner)
    with pytest.raises(ValueError,match='Changed'):e.apply(records,reader,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert e.query()['status']=='NOT_ATTEMPTED'


def test_real_application_path_only_in_temporary_project(records,current,tmp_path,monkeypatch):
    lockroot=tmp_path/'generated/vehicle_locks';lockroot.mkdir(parents=True);monkeypatch.setattr(d.locks,'LOCK_ROOT',lockroot)
    monkeypatch.setattr(d,'current_records',lambda context=None:(copy.deepcopy(records),copy.deepcopy(current)))
    owner=records['target']['descriptor']['lifecycle_id'];e=d.ProjectDisposition(owner);e.clock=lambda:10
    report=d.dry_run(records,current,now=10);sha=report['scope_sha256']
    audit=e.apply_reviewed(scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    admission=d.diagnostic_precheck(records,current,audit,now=10)
    assert admission['status']=='SATISFIED' and admission['disposition_consumed'] and not admission['opening_authorized']
    assert not list(lockroot.glob('*.json'))
    bad=copy.deepcopy(audit);bad['owner_id']='11111111-1111-4111-8111-111111111111'
    assert d.diagnostic_precheck(records,current,bad,now=10)['status']=='BLOCKED'


def test_partial_persistence_and_lost_response_do_not_reapply(records,current,tmp_path):
    owner=records['target']['descriptor']['lifecycle_id'];sha=d.dry_run(records,current,now=10)['scope_sha256']
    def write(path,value):
        from tools.vehicle_execution_lock import atomic_json
        atomic_json(path,value)
        if path.name=='intent.json':raise OSError('final acknowledgement lost')
    e=d.OfflineDisposition(tmp_path/'audit',clock=lambda:10,owner=owner,write=write)
    with pytest.raises(OSError):e.apply(records,lambda:current,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert e.query()['status']=='APPLYING_UNCONFIRMED'
    with pytest.raises(ValueError):e.apply(records,lambda:current,scope_sha256=sha,authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
