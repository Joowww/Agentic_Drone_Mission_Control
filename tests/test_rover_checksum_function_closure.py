"""Immutable real function-result archive; every mutation/current fixture is synthetic."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tools.rover_xrce_trace import session_precheck as p, historical_disposition as d
from tests.test_rover_present_recovery import proc, tree, review_data

REPO=Path(__file__).resolve().parents[1]
HISTORY=REPO/'evaluation/operations/rover_status_authorized_window_2026_10_31/8a4d30bd-ed13-45bc-b181-fd24f1f4dc5c'
OBSERVATIONS=('post-restoration-check.function.json','post-after-restoration.function.json')

def read(path):return json.loads(path.read_bytes())
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def seal(root):
    """Only reseal explicitly synthetic copies; not the historical archive."""
    assert root!=HISTORY
    (root/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+str(f.relative_to(root))+'\n'
        for f in sorted(root.rglob('*')) if f.is_file() and f.name!='SHA256SUMS'))

@pytest.fixture
def archive(tmp_path):
    root=tmp_path/'synthetic-archive';shutil.copytree(HISTORY,root);return root

def test_original_checksum_function_archive_and_causal_wait_are_consumed():
    before=(HISTORY/'SHA256SUMS').read_bytes();ref=p.closure_archive_reference(HISTORY)
    assert ref['layout']==p.FUNCTION_SESSION_LAYOUT
    assert ref['checksum_sha256']=='017e4cd48c11d9c121a6e456592e20ef9bb676de0526f35a6bfaf15c06d5bfa5'
    facts=p.recorded_cleanup_archive(ref);h=facts['historical']
    assert h['monitor']['phase']=='INCOMPLETE' and h['monitor']['capture_complete'] is False
    assert h['monitor']['errors']==['Native diagnostic reports incomplete coverage']*2
    assert facts['limitations']['historical_fresh_observation'] is False
    receipt=read(HISTORY/'preserved/sdk/receiver/receiver-receipt.json')
    assert receipt['return_code']==2 and receipt['footer_sha256'] is None
    assert read(HISTORY/'preserved/sdk/overlay/capture/monitor_exit.json')['return_code']==1
    assert (HISTORY/'SHA256SUMS').read_bytes()==before and not (HISTORY/'manifest.json').exists()
    with pytest.raises(ValueError,match='historical V2 freshness'):p.verified_closure_archive(ref)

@pytest.mark.parametrize('bad',['seal_changed','hash','missing','duplicate','absolute','parent','alias','symlink','symlink_parent','malformed','empty'])
def test_checksum_security_rejects_without_discovery(archive,bad,tmp_path):
    sealpath=archive/'SHA256SUMS';reference=p.closure_archive_reference(archive)
    name='post-host-state.json';path=archive/name
    if bad=='seal_changed':sealpath.write_bytes(sealpath.read_bytes()+b' ')
    elif bad=='hash':path.write_text('{}')
    elif bad=='missing':path.unlink()
    elif bad=='symlink':
        other=tmp_path/'outside';other.write_bytes(path.read_bytes());path.unlink();path.symlink_to(other)
    elif bad=='symlink_parent':
        folder=archive/'preserved';folder.rename(tmp_path/'outside');folder.symlink_to(tmp_path/'outside',target_is_directory=True)
    else:
        lines=sealpath.read_text().splitlines();row=next(x for x in lines if x.endswith('  '+name))
        if bad=='duplicate':lines.append(row)
        elif bad=='absolute':lines[lines.index(row)]=row[:66]+str(path)
        elif bad=='parent':lines[lines.index(row)]=row[:66]+'../outside'
        elif bad=='alias':lines[lines.index(row)]=row[:66]+'./'+name
        elif bad=='malformed':lines[0]='not a checksum'
        elif bad=='empty':lines=[]
        sealpath.write_text('\n'.join(lines)+'\n')
        reference['checksum_sha256']=hashlib.sha256(sealpath.read_bytes()).hexdigest()
    with pytest.raises((ValueError,OSError)):p.recorded_cleanup_archive(reference)

@pytest.mark.parametrize('bad',['descriptor','inventory_missing','inventory_owned','query_rc','complete','provenance',
    'source_provenance','context','boot','environment','restriction','reservation','sessions','retained_monitor',
    'before_stop','source_order','resource_eof','resource_occupied','serialization','environment_order','read_budget'])
def test_function_inventory_rejects_insufficient_or_wrong_association(archive,bad):
    # Mutate the second observation, so an earlier favorable one cannot hide it.
    path=archive/OBSERVATIONS[1];v=read(path);r=v['records'];c=v['current'];ctx=v['observation_context'];inv=r['inventory']
    if bad=='descriptor':r['target']['descriptor']['lifecycle_id']='12345678-1234-4234-8234-123456789abc'
    elif bad=='inventory_missing':inv.pop('agents')
    elif bad=='inventory_owned':inv['owned']=[{'pid':999}]
    elif bad=='query_rc':ctx['inventory_return_code']=1
    elif bad=='complete':c['complete']=False
    elif bad=='provenance':ctx['inventory_source_sha256']='0'*64
    elif bad=='source_provenance':c['resources']['reader_hashes']['tools/simulation_profiles.py']='0'*64
    elif bad=='context':inv['query_context_after']['net_namespace']='net:[999]'
    elif bad=='boot':inv['boot_id']='other'
    elif bad=='environment':ctx['environment_recheck']['state']['StartedAt']='2020-01-01T00:00:00Z'
    elif bad=='restriction':c['restriction']={'status':'UNCONFIRMED'}
    elif bad=='reservation':c['guards']={'r.json':{}}
    elif bad=='sessions':c['other_sessions']=['other']
    elif bad=='retained_monitor':inv['files'][r['target']['descriptor']['prefix']+'/capture/monitor.json']='{}'
    elif bad=='before_stop':ctx['started_at_utc']='2020-01-01T00:00:00Z'
    elif bad=='source_order':ctx['sources']=list(reversed(ctx['sources']));c['sources']=ctx['sources']
    elif bad=='resource_eof':
        for res in (c['resources'],inv['resources']):res['reads'][res['table_reads'][0]]['operation']='bytes'
    elif bad=='resource_occupied':
        for res in (c['resources'],inv['resources']):res['status']='INCOMPLETE'
    elif bad=='serialization':v['Path_serialized_fields']=['everything']
    elif bad=='environment_order':ctx['environment_recheck']['started_at_utc']='2020-01-01T00:00:00Z'
    elif bad=='read_budget':
        for res in (c['resources'],inv['resources']):res['counts']['read_calls']=999999
    dump(path,v);seal(archive)
    with pytest.raises((ValueError,KeyError)):p.recorded_cleanup_archive(p.closure_archive_reference(archive))

@pytest.mark.parametrize('bad',['wait_before_final','utc_previous_second','supervisor','unknown_monitor_source','cleanup_partial','cleanup_in_monitor'])
def test_causal_order_not_inferred_from_coarse_utc_alone(archive,bad):
    ref=p.closure_archive_reference(archive);data,reader=p._verified_closure_data(ref)
    # Directly exercise the affected helper with explicit synthetic mutations;
    # other duplicates stay intact and are separately checked by the full path.
    h=p.recorded_cleanup_archive(ref)['historical'];monitor=copy.deepcopy(h['monitor']);pointer=h['target']['descriptor']
    receipt=reader('monitor-exit.json');finished=reader('cleanup-finished.json')
    if bad=='wait_before_final':receipt['observed_monotonic']=monitor['finished_monotonic']-1
    elif bad=='utc_previous_second':receipt['observed_at_utc']='2026-10-31T14:16:06Z'
    elif bad=='supervisor':
        q=reader('preserved/sdk/overlay/capture/monitor_supervisor.json');q['child']['start_ticks']+=1
        data['preserved/sdk/overlay/capture/monitor_supervisor.json']=json.dumps(q).encode()
    elif bad=='unknown_monitor_source':data['preserved/sdk/overlay/monitor.py']+=b'\n'
    elif bad=='cleanup_partial':finished['infrastructure_cleanup_complete']=False;monitor['cleanup_result']=finished
    elif bad=='cleanup_in_monitor':monitor['cleanup_result']=None
    def read_data(name):return json.loads(data[p.FUNCTION_SESSION_PATHS.get(name,name)])
    from datetime import datetime
    at=lambda value:datetime.fromisoformat(value.replace('Z','+00:00'))
    with pytest.raises(ValueError):p._function_monitor_wait(data,read_data,pointer,monitor,receipt,finished,at('2026-10-31T14:36:08Z'),at)


def test_original_archive_to_present_review_with_explicit_synthetic_current(review_data,monkeypatch,tmp_path):
    records,current,now=copy.deepcopy(review_data);ref=p.closure_archive_reference(HISTORY)
    original=p.recorded_cleanup_archive(ref)['historical'];records.update(original,historical_evidence=ref)
    env=read(HISTORY/OBSERVATIONS[1])['observation_context']['environment_recheck'];records['environment']=env
    pointer=original['target']['descriptor']
    records['inventory']['state_files']={p.POINTER:json.dumps({**pointer,**p.FLAGS})}
    records['inventory']['files']={pointer['prefix']+'/'+n:json.dumps(original[k]) for k,n in [('selection','selection.json'),('launch','launch.json'),('monitor','capture/monitor.json')]}
    direct={k:v for k,v in records.items() if k!='recovery_basis'}
    classified=p.classify_last_session(**direct)
    assert classified['pointer_classification']==d.CLASS,classified
    legacy=d.dry_run(direct,current,now=now)
    assert legacy['status']=='BLOCKED' and legacy['required_review_protocol']=='CURRENT_RESOURCE_REVIEW_V1'
    def synthetic_reader(context=None,*,present=False):
        assert present;return copy.deepcopy(records),copy.deepcopy(current)
    monkeypatch.setattr(d,'current_records',synthetic_reader);monkeypatch.setattr(d.time,'monotonic',lambda:now)
    locks=tmp_path/'synthetic-locks';locks.mkdir()
    for name in ('v1.execution.lock','registry.lock'):(locks/name).touch()
    monkeypatch.setattr(d.locks,'LOCK_ROOT',locks)
    reference=tmp_path/'reference.json';dump(reference,ref)
    report=d.real_dry_run(reference,present=True)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    assert report['scope']['historical']['monitor']==original['monitor']
    assert report['scope']['historical_limitations']['historical_fresh_observation'] is False
    assert not report['opening_authorized'] and not report['movement_authorized']
