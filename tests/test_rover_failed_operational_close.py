"""Real immutable 050 proof; synthetic format/mutation and current-state fixtures."""
import copy
import hashlib
import json
import shutil
import stat
from pathlib import Path

import pytest

from tools.rover_xrce_trace import session_precheck as p, historical_disposition as d
from tests.test_rover_present_recovery import proc, tree, review_data

REPO=Path(__file__).resolve().parents[1]
FAILED=REPO/'simulation/ros2_gazebo/results/rover_socket_capture_2026_10_28/6021022b-f8eb-44c5-a785-0c6adc6644ea'
SUCCEEDED=REPO/'simulation/ros2_gazebo/results/rover_authorized_capture_2026_10_28/f15f176e-0710-42cc-9dd9-c0c5fa8448e1'


def read(path):return json.loads(path.read_bytes())
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def ref(root):
    return {**p.closure_archive_reference(root),'layout':p.OPERATIONAL_LAYOUT}


def seal(root,schema):
    """Synthetic derivatives only; originals are never rewritten."""
    manifest=read(root/'manifest.json');manifest['schema']=schema
    rows=[]
    for original in manifest['files']:
        path=root/original['path'];raw=path.read_bytes()
        row={'path':original['path'],'sha256':hashlib.sha256(raw).hexdigest()}
        if schema=='tfg.evidence-manifest/1':row.update(size_bytes=len(raw),mode=oct(stat.S_IMODE(path.stat().st_mode)))
        else:row.update(size=len(raw))
        rows.append(row)
    manifest['files']=rows;dump(root/'manifest.json',manifest)


@pytest.fixture(params=[(False,'rover-operational-evidence/1'),(False,'tfg.evidence-manifest/1'),
                             (True,'rover-operational-evidence/1'),(True,'tfg.evidence-manifest/1')])
def represented(request,tmp_path):
    failed,schema=request.param;root=tmp_path/'synthetic-representation'
    shutil.copytree(FAILED if failed else SUCCEEDED,root);seal(root,schema)
    return root,failed,schema


def synthetic_current(reference,review_data):
    records,current,now=copy.deepcopy(review_data)
    records.update(p.recorded_cleanup_archive(reference)['historical'],historical_evidence=reference)
    records['environment']=read(Path(reference['directory'])/'post-environment-after.json')
    pointer=records['target']['descriptor']
    records['inventory']['state_files']={p.POINTER:json.dumps({**pointer,**p.FLAGS})}
    records['inventory']['files']={pointer['prefix']+'/'+name:json.dumps(records[key])
        for key,name in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]}
    return records,current,now


def test_original_050_complete_load_without_rewriting():
    manifest=FAILED/'manifest.json';before=manifest.read_bytes()
    assert hashlib.sha256(before).hexdigest()=='99e76bff61221c2c193589582b1cb3a447a63c9d152526844398c2696d95bb10'
    facts=p.recorded_cleanup_archive(ref(FAILED))['historical']
    assert facts['start_operation']['state']=='UNCONFIRMED'
    assert not facts['start_operation'].get('finished_at')
    assert facts['stop_operation']['state']=='FINISHED'
    assert facts['stop_operation']['closing_failed_start']==facts['start_operation']
    assert facts['monitor']['phase']=='CLOSED' and facts['monitor']['capture_complete'] is False
    index=read(FAILED/'sdk-file-index.json');pointer=facts['target']['descriptor']
    exit_rows=[v for v in index if v['path']==pointer['prefix']+'/capture/monitor_exit.json']
    assert len(exit_rows)==1 and read(FAILED/exit_rows[0]['archive_path'])['return_code']==1
    assert manifest.read_bytes()==before


def test_format_matrix_load_classification_and_present_review(represented,review_data):
    root,failed,_=represented;records,current,now=synthetic_current(ref(root),review_data)
    direct={k:v for k,v in records.items() if k!='recovery_basis'}
    classification=p.classify_last_session(**direct)
    assert classification['pointer_classification']==d.CLASS,classification
    assert classification['start_outcome']==('FAILED_START_INFRASTRUCTURE_CLOSED' if failed else 'COMPLETED_START_CLOSED')
    # Empty synthetic current inventory alone is insufficient for admission.
    precheck=d.diagnostic_precheck(direct,current,{},now=now)
    assert precheck['conditions']['historical_proof'] and not precheck['precheck_satisfied'],precheck
    report=d.dry_run(records,current,now=now)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['scope']['historical']['monitor']['capture_complete'] is False
    assert not report['opening_authorized'] and not report['movement_authorized']


@pytest.mark.parametrize('bad',['owner','environment','partial','uncertain_stop','link','signal_boot','chronology'])
def test_format_matrix_rejects_partial_or_contradictory_closure(represented,bad):
    root,failed,schema=represented
    if bad in {'link','signal_boot'} and not failed:
        pytest.skip('Failed-start protected-stop invariant; successful layout covered separately')
    name='stop-lifecycle/operation.json';value=read(root/name)
    if bad=='owner':value['owner_id']='12345678-1234-4234-8234-123456789abc'
    elif bad=='environment':
        name='start-lifecycle/rover_environment_reference.json';value=read(root/name);value['environment']['engine_id']='other-engine'
    elif bad=='uncertain_stop':value['state']='UNCONFIRMED'
    elif bad=='link':value['closing_failed_start']['error']='SYNTHETIC contradictory original'
    elif bad=='chronology':value['started_at']='2020-01-01T00:00:00Z'
    else:
        name='stop-lifecycle/backend.log';value=json.loads((root/name).read_text().splitlines()[0])
        if bad=='partial':value['remaining']=[{'pid':999}]
        else:
            for signal in value['signals']:signal['boot_id']='SYNTHETIC changed boot'
    dump(root/name,value);seal(root,schema)
    with pytest.raises(ValueError):p.recorded_cleanup_archive(ref(root))


@pytest.mark.parametrize('change',['link','environment','monitor','stop'])
def test_original_050_cannot_be_reassociated_by_consumer(review_data,change):
    records,current,now=synthetic_current(ref(FAILED),review_data)
    if change=='link':records['stop_operation']['closing_failed_start']['error']='SYNTHETIC altered link'
    elif change=='environment':records['environment']['container_id']='0'*64
    elif change=='monitor':records['monitor']['capture_complete']=True
    else:records['stop_operation']['state']='UNCONFIRMED'
    assert d.dry_run(records,current,now=now)['status']=='BLOCKED'


def test_original_050_locked_present_entry_with_synthetic_current(review_data,monkeypatch,tmp_path):
    records,current,now=synthetic_current(ref(FAILED),review_data)
    calls=[]
    def observe(context=None,*,present=False):
        calls.append(present);assert present
        return copy.deepcopy(records),copy.deepcopy(current)
    monkeypatch.setattr(d,'current_records',observe)
    monkeypatch.setattr(d.ProjectDisposition,'query',lambda self:{'status':'NOT_ATTEMPTED'})
    monkeypatch.setattr(d.time,'monotonic',lambda:now)
    lockroot=tmp_path/'synthetic-locks';lockroot.mkdir()
    for name in ('v1.execution.lock','registry.lock'):(lockroot/name).touch()
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lockroot)
    evidence=tmp_path/'reference.json';dump(evidence,ref(FAILED))
    report=d.real_dry_run(evidence=evidence,present=True)
    assert calls==[True]
    assert report['status']=='DRY_RUN_ELIGIBLE',report
