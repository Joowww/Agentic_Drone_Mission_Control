"""Immutable real archive and explicitly synthetic mutations/current observations."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tools.rover_xrce_trace import session_precheck as p, historical_disposition as d, present_recovery
from tests.test_rover_present_recovery import proc, tree, review_data

HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_authorized_capture_2026_10_28/f15f176e-0710-42cc-9dd9-c0c5fa8448e1'


def read(path):return json.loads(path.read_bytes())
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def test_real_operational_producer_output_is_consumed_without_rewriting():
    assert hashlib.sha256((HISTORY/'manifest.json').read_bytes()).hexdigest()=='e9ff4634187790ed7b4bdcfc287fd3eed0b78b094e5a031181438c47eece0c2e'
    ref=p.closure_archive_reference(HISTORY);facts=p.recorded_cleanup_archive(ref)
    assert ref['layout']==p.OPERATIONAL_LAYOUT
    assert facts['historical']['monitor']['phase']=='CLOSED'
    assert facts['historical']['monitor']['core_capture_complete']
    assert not facts['historical']['monitor']['capture_complete']
    # Producer was the operational evidence-sealing recipe, not lifecycle itself:
    # exact schema/entry shape emitted by that recipe, including absent modes.
    manifest=read(HISTORY/'manifest.json')
    assert manifest['schema']=='rover-operational-evidence/1'
    assert manifest['session_id']==facts['historical']['start_operation']['owner_id']
    assert all(set(row)=={'path','size','sha256'} for row in manifest['files'])
    assert read(HISTORY/'post-current-observation.json')['diagnostic_summary']['monitor_exit']['return_code']==1
    with pytest.raises(ValueError,match='historical V2 freshness'):p.verified_closure_archive(ref)


@pytest.fixture
def archive(tmp_path):
    dest=tmp_path/'operational';shutil.copytree(HISTORY,dest);return dest


def reseal_like_producer(root):
    # Synthetic derivative only. Same operational producer recipe, no new format.
    manifest=read(root/'manifest.json')
    for row in manifest['files']:
        file=root/row['path']
        row.update(size=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
    dump(root/'manifest.json',manifest)


@pytest.mark.parametrize('kind',['altered_manifest','altered','absent','duplicate','absolute','parent','alias','symlink','symlink_parent','schema','size_bool','extra_field'])
def test_operational_manifest_security(archive,kind):
    manifest=read(archive/'manifest.json');row=manifest['files'][0]
    if kind=='altered_manifest':
        ref=p.closure_archive_reference(archive);(archive/'manifest.json').write_bytes((archive/'manifest.json').read_bytes()+b' ')
    elif kind=='altered':(archive/row['path']).write_bytes(b'altered')
    elif kind=='absent':(archive/row['path']).unlink()
    elif kind=='symlink':
        file=archive/row['path'];data=file.read_bytes();file.unlink();external=archive.parent/'external';external.write_bytes(data);file.symlink_to(external)
    elif kind=='symlink_parent':
        original=archive/'sdk-evidence';outside=archive.parent/'outside';original.rename(outside);original.symlink_to(outside,target_is_directory=True)
    else:
        if kind=='duplicate':manifest['files'].append(copy.deepcopy(row))
        elif kind=='absolute':row['path']=str((archive/row['path']).resolve())
        elif kind=='parent':row['path']='../outside'
        elif kind=='alias':row['path']='./'+row['path']
        elif kind=='schema':manifest['schema']='anything/1'
        elif kind=='size_bool':row['size']=False
        elif kind=='extra_field':row['mode']='0o600'
        dump(archive/'manifest.json',manifest)
    if kind!='altered_manifest':
        ref={'kind':'VERIFIED_CLOSURE_ARCHIVE_V2','directory':str(archive),'manifest_sha256':hashlib.sha256((archive/'manifest.json').read_bytes()).hexdigest(),'layout':p.OPERATIONAL_LAYOUT}
    with pytest.raises((ValueError,OSError)):p.recorded_cleanup_archive(ref)


@pytest.mark.parametrize('kind',['manifest_session','start','stop','cleanup','index_duplicate','index_missing','index_hash','index_size','index_unstable','monitor_wait','wait_identity','post_inventory','environment','context','chronology'])
def test_contradictory_operational_associations_are_rejected_even_with_valid_hashes(archive,kind):
    if kind=='manifest_session':
        manifest=read(archive/'manifest.json');manifest['session_id']='12345678-1234-4234-8234-123456789abc';dump(archive/'manifest.json',manifest)
    elif kind in ('index_duplicate','index_missing','index_hash','index_size','index_unstable'):
        path=archive/'sdk-file-index.json';index=read(path)
        if kind=='index_duplicate':index.append(copy.deepcopy(index[0]))
        elif kind=='index_missing':index.pop(0)
        elif kind=='index_hash':index[0]['sha256']='0'*64
        elif kind=='index_size':index[0]['bytes']+=1
        else:index[0]['stable_stat']=False
        dump(path,index)
    else:
        names={'start':'start-lifecycle/operation.json','stop':'stop-lifecycle/operation.json','cleanup':'sdk-evidence/3/cleanup-finished.json',
               'monitor_wait':'sdk-evidence/8/monitor_exit.json','wait_identity':'sdk-evidence/8/monitor_exit.json',
               'post_inventory':'post-current-observation.json','context':'post-current-observation.json','environment':'post-environment-after.json',
               'chronology':'post-host-state.json'}
        path=archive/names[kind];v=read(path)
        if kind in ('start','stop'):v['owner_id']='12345678-1234-4234-8234-123456789abc'
        elif kind=='cleanup':v['infrastructure_cleanup_complete']=False
        elif kind=='monitor_wait':v['return_code']=0
        elif kind=='wait_identity':v['start_ticks']+=1
        elif kind=='post_inventory':v['inventory']['owned']=[{'pid':999}]
        elif kind=='environment':v['state']['StartedAt']='2026-10-28T00:00:00Z'
        elif kind=='context':v['context_after']['namespaces']['net']='net:[999]'
        elif kind=='chronology':v['read_at_utc']='2020-01-01T00:00:00Z'
        dump(path,v)
        # Keep SDK index consistent, so semantic changes reach association checks.
        index=read(archive/'sdk-file-index.json')
        for row in index:
            if row['archive_path']==names[kind]:row.update(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        dump(archive/'sdk-file-index.json',index)
    reseal_like_producer(archive)
    with pytest.raises(ValueError):p.recorded_cleanup_archive(p.closure_archive_reference(archive))


def test_operational_manifest_does_not_assert_absent_modes(archive):
    (archive/'README.md').chmod(0o600)
    assert p.recorded_cleanup_archive(p.closure_archive_reference(archive))['historical']['monitor']['phase']=='CLOSED'


def test_full_operational_load_to_present_review_with_explicit_synthetic_current(review_data):
    records,current,now=review_data
    ref=p.closure_archive_reference(HISTORY);original=p.recorded_cleanup_archive(ref)['historical']
    records.update(copy.deepcopy(original),historical_evidence=ref,recovery_basis=present_recovery.BASIS)
    records['environment']=read(HISTORY/'post-environment-after.json')
    pointer=original['target']['descriptor']
    records['inventory']['state_files']={p.POINTER:json.dumps({**pointer,**p.FLAGS})}
    records['inventory']['files']={pointer['prefix']+'/'+n:json.dumps(original[k]) for k,n in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]}
    report=d.dry_run(records,current,now=now)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['scope']['historical']['monitor']['phase']=='CLOSED'
    assert report['scope']['historical_limitations']['historical_capture_complete'] is False
    assert report['scope']['protocol']==present_recovery.BASIS
    assert not report['opening_authorized'] and not report['movement_authorized']
    # Generic classifier can also consume the recorded closure without V2
    # historical freshness; it still requires separate current-scope review.
    direct={k:v for k,v in records.items() if k not in ('recovery_basis',)}
    classified=p.classify_last_session(**direct)
    assert classified['pointer_classification']==d.CLASS,classified
