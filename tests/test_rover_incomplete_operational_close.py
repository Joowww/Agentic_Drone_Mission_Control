"""Immutable incomplete capture; mutations/current observations are synthetic."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tools.rover_xrce_trace import session_precheck as p, historical_disposition as d
from tests.test_rover_failed_operational_close import read, dump, ref, seal, synthetic_current
from tests.test_rover_present_recovery import proc, tree, review_data

HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_050_authorized_capture_2026_10_30/e7fc9f9b-76d9-42a5-8276-e852a17451ad'


def test_original_incomplete_capture_preserves_independent_closure():
    before=(HISTORY/'manifest.json').read_bytes()
    assert hashlib.sha256(before).hexdigest()=='8376ce03c811be172f1f519f77b3977d2f960352dc210a3068e966ee0cd4e307'
    facts=p.recorded_cleanup_archive(ref(HISTORY))
    historical=facts['historical'];monitor=historical['monitor']
    assert monitor['phase']=='INCOMPLETE' and monitor['core_capture_complete'] is False
    assert monitor['capture_complete'] is False and monitor['errors']==['Model server exit not observed by monitor']
    assert historical['stop_operation']['state']=='FINISHED'
    assert read(HISTORY/'post-current-observation.json')['diagnostic_summary']['monitor_exit']['return_code']==1
    # Exact original receipt, never a success footer or a synthetic replacement.
    pointer=historical['target']['descriptor'];index=read(HISTORY/'sdk-file-index.json')
    source='/tmp/tfg-rover-passive-validation-'+pointer['lifecycle_id']+'/receiver-receipt.json'
    receipt=next(row for row in index if row['path']==source)
    receiver=read(HISTORY/receipt['archive_path'])
    assert receiver['return_code']==2 and receiver['footer_sha256'] is None and not receiver['identity_verified']
    assert (HISTORY/'manifest.json').read_bytes()==before


def test_incomplete_original_reaches_locked_present_review_with_synthetic_current(review_data,monkeypatch,tmp_path):
    records,current,now=synthetic_current(ref(HISTORY),review_data)
    classification=p.classify_last_session(**{k:v for k,v in records.items() if k!='recovery_basis'})
    assert classification['pointer_classification']==d.CLASS,classification
    assert classification['requires_explicit_scope_review'] and not classification['movement_authorized']
    def observe(context=None,*,present=False):
        assert present
        return copy.deepcopy(records),copy.deepcopy(current)
    monkeypatch.setattr(d,'current_records',observe)
    monkeypatch.setattr(d.time,'monotonic',lambda:now)
    locks=tmp_path/'synthetic-locks';locks.mkdir()
    for name in ('v1.execution.lock','registry.lock'):(locks/name).touch()
    monkeypatch.setattr(d.locks,'LOCK_ROOT',locks)
    evidence=tmp_path/'closure-reference.json';dump(evidence,ref(HISTORY))
    report=d.real_dry_run(evidence=evidence,present=True)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['scope']['historical']['monitor']==records['monitor']
    assert report['scope']['historical_limitations']['historical_capture_complete'] is False
    assert not report['opening_authorized'] and not report['movement_authorized']


@pytest.fixture
def archive(tmp_path):
    root=tmp_path/'synthetic-mutated-archive';shutil.copytree(HISTORY,root);return root


def mutate(root,change):
    """Reseal synthetic derivatives with all duplicate representations updated.

    This reaches semantic checks rather than merely failing an old file hash.
    """
    def walk(value):
        if isinstance(value,dict):
            change(value)
            for child in list(value.values()):walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    for path in root.rglob('*'):
        if path.is_file() and path.name!='manifest.json':
            try:value=json.loads(path.read_bytes())
            except (ValueError,UnicodeDecodeError):
                if path==root/'stop-lifecycle/backend.log':
                    lines=path.read_text().splitlines(keepends=True)
                    value=json.loads(lines[0]);walk(value)
                    path.write_text(json.dumps(value)+'\n'+''.join(lines[1:]))
                continue
            walk(value);dump(path,value)
    # Raw post-query stores indexed original file bytes; update those too.
    import base64
    index=read(root/'sdk-file-index.json');raw=read(root/'post-current-read.stdout')
    for row in index:
        content=(root/row['archive_path']).read_bytes()
        row.update(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
        original=next(v for v in raw['files'] if v['path']==row['path'])
        original.update(bytes=len(content),sha256=row['sha256'])
        # Keep the producer's original byte-field name, when present.
        original['base64']=base64.b64encode(content).decode()
    dump(root/'sdk-file-index.json',index);dump(root/'post-current-read.stdout',raw)
    seal(root,'tfg.evidence-manifest/1')


@pytest.mark.parametrize('bad',['owner','stop','cleanup','remaining','post_process','post_context','wait','phase','core','complete','closure'])
def test_incomplete_capture_rejects_partial_or_contradictory_closure(archive,bad):
    def change(v):
        if bad=='owner' and v.get('kind')=='SIMULATION_LIFECYCLE' and v.get('action')=='stop':v['owner_id']='12345678-1234-4234-8234-123456789abc'
        elif bad=='stop' and v.get('kind')=='SIMULATION_LIFECYCLE' and v.get('action')=='stop':v['state']='UNCONFIRMED'
        elif bad=='cleanup' and 'infrastructure_cleanup_complete' in v:v['infrastructure_cleanup_complete']=False
        elif bad=='remaining' and 'unattributed_auxiliaries' in v:v['remaining']=[{'pid':999}]
        elif bad=='post_process' and all(k in v for k in ('owned','ambiguous','agents')):v['owned']=[{'pid':999}]
        elif bad=='post_context' and 'context_after' in v:v['context_after']['boot_id']='SYNTHETIC-CHANGED'
        elif bad=='wait' and v.get('state')=='PARENT_WAIT_STATUS_OBSERVED':v['return_code']=0
        elif v.get('kind')=='PASSIVE_DIAGNOSTIC_MONITOR':
            if bad=='phase':v['phase']='CLOSED'
            elif bad=='core':v['core_capture_complete']=True
            elif bad=='complete':v['capture_complete']=True
            elif bad=='closure':v['closure_requested']=False
    mutate(archive,change)
    expected={
        'owner':'descriptor/owner', 'stop':'operation incomplete',
        'cleanup':'cleanup receipts', 'remaining':'independent cleanup',
        'post_process':'post-close state/context', 'post_context':'post-close state/context',
        'wait':'monitor wait', 'phase':'separate-channel closure',
        'core':'separate-channel closure','complete':'incomplete retained diagnostic',
        'closure':'separate-channel closure'}
    with pytest.raises(ValueError,match=expected[bad]):p.recorded_cleanup_archive(ref(archive))


def test_incomplete_original_alteration_rejected(archive):
    (archive/'stop-lifecycle/backend.log').write_text('{}\n')
    with pytest.raises(ValueError):p.recorded_cleanup_archive(ref(archive))


@pytest.mark.parametrize('bad',['remaining','reservation','context'])
def test_present_review_still_requires_current_absence(review_data,bad):
    records,current,now=synthetic_current(ref(HISTORY),review_data)
    if bad=='remaining':records['inventory']['owned']=[{'pid':999}]
    elif bad=='reservation':current['guards']={'pending':'SYNTHETIC'}
    else:current['resources']['context']['boot_id']='SYNTHETIC-CHANGED'
    assert d.dry_run(records,current,now=now)['status']=='BLOCKED'
