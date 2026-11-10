"""Single exact-pin successor; every application/transport/clock is synthetic /tmp."""
import copy
import json
import hashlib
import shutil
from pathlib import Path

import pytest
from tools.rover_xrce_trace import historical_disposition as d,present_recovery as recovery

ROOT=Path(__file__).resolve().parents[1]
APPLIED=ROOT/'evaluation/operations/rover_clock_execution_2026_10_31/58a4a593-4bbe-4ac1-a645-7ab593f381a8'
REPLAY=ROOT/'evaluation/operations/rover_disposition_consumer_offline_2026_10_31/d5bea33f-c6e9-4cd3-9e2c-70d446e09e0c/replay-inputs.json'

def read(p):return json.loads(p.read_bytes())
def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')

@pytest.fixture
def setup(tmp_path,monkeypatch):
    folder=tmp_path/'synthetic-audit';shutil.copytree(APPLIED/'application-audit',folder)
    value=read(REPLAY);records,current=copy.deepcopy(value['records']),copy.deepcopy(value['current'])
    current['resources']['reader_hashes']=recovery.reader_hashes()
    now=current['observed_monotonic']+2.7
    domain=copy.deepcopy(current['host_acquisition']['clock_context'])
    monkeypatch.setattr(recovery,'host_clock_context',lambda:copy.deepcopy(domain))
    engine=d.OfflineDisposition(folder,owner=records['target']['descriptor']['lifecycle_id'],clock=lambda:now)
    engine.offline_only=False  # Explicit synthetic production-shaped audit, confined to /tmp.
    return engine,records,current,now

def snapshot(engine):return {n:(engine.root/n).read_bytes() for n in ('intent.json','originals.json')}
def report(setup):
    engine,records,current,now=setup
    return d.dry_run(records,{**current,'consumer_predecessor':engine.predecessor_binding()},now=now)
def apply(setup):
    engine,records,current,now=setup;v=report(setup);assert v['status']=='DRY_RUN_ELIGIBLE',v
    sha=v['scope_sha256'];result=engine.apply_successor(records,lambda:copy.deepcopy(current),scope_sha256=sha,
        authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}')
    return result


def test_full_successor_preserves_original_and_is_consumed_with_current_checks(setup):
    engine,records,current,now=setup;before=snapshot(engine);calls=[];parent=engine.predecessor_binding();v=report(setup)
    sha=v['scope_sha256'];authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}'
    def observe():calls.append(1);return copy.deepcopy(current)
    successor=engine.apply_successor(records,observe,scope_sha256=sha,authorization=authorization)
    assert calls==[1,1] and successor['schema']==d.SUCCESSOR_SCHEMA
    assert successor['scope']['consumer_revision']['audit_file_hashes']==parent['audit_file_hashes']
    assert successor['scope']['reader_hashes']==recovery.reader_hashes()
    assert len(successor['application_observations'])==2 and snapshot(engine)==before
    queried=engine.query();assert queried['scope']==read(APPLIED/'audit-after.json')['scope']
    assert queried['consumer_successor']==successor
    current['consumer_predecessor']=engine.predecessor_binding()
    decision=d.diagnostic_precheck(records,current,queried,now=now)
    assert decision['status']=='SATISFIED' and decision['disposition_consumed'],decision
    assert not decision['opening_authorized'] and not decision['movement_authorized']
    assert records['monitor']['phase']=='INCOMPLETE' and records['monitor']['capture_complete'] is False
    assert engine.apply_successor(records,lambda:pytest.fail('No replay'),scope_sha256=sha,authorization=authorization)==successor
    assert snapshot(engine)==before


@pytest.mark.parametrize('bad',['other_pin','extra_pin','removed_pin','context','historical','effect','unknown_from','parent_owner','parent_auth','parent_digest','byte_hash'])
def test_only_the_reviewed_consumer_pin_transition_is_allowed(setup,bad):
    engine,records,current,now=setup;parent=engine.predecessor_binding();v=d.dry_run(records,current,now=now);scope=copy.deepcopy(v['scope'])
    if bad=='other_pin':scope['reader_hashes']['tools/rover_xrce_trace/budget.py']='f'*64
    elif bad=='extra_pin':scope['reader_hashes']['other.py']='f'*64
    elif bad=='removed_pin':scope['reader_hashes'].pop('tools/rover_xrce_trace/budget.py')
    elif bad=='context':scope['environment_execution']['container_boot_id']='other'
    elif bad=='historical':scope['historical']['monitor']['capture_complete']=True
    elif bad=='effect':scope['opening_authorized']=True
    elif bad=='unknown_from':
        parent['audit']['scope']['reader_hashes'][d.SUCCESSOR_PIN]='a'*64
        parent['audit']['scope_sha256']=d.digest(parent['audit']['scope']);parent['audit']['authorization']=f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {parent['audit']['scope_sha256']}"
    elif bad=='parent_owner':parent['audit']['owner_id']='12345678-1234-4234-8234-123456789abc'
    elif bad=='parent_auth':parent['audit']['authorization']='old different authorization'
    elif bad=='parent_digest':parent['audit']['scope_sha256']='0'*64
    elif bad=='byte_hash':parent['audit_file_hashes']['intent.json']='invalid'
    with pytest.raises((ValueError,KeyError)):d._successor_link(parent,scope)


def test_scope_authorizes_the_exact_link_not_just_a_reader_version(setup):
    engine,records,current,now=setup;v=report(setup);scope=copy.deepcopy(v['scope']);scope['consumer_revision']['audit_file_hashes']['intent.json']='0'*64
    with pytest.raises(ValueError,match='link changed'):d._successor_link(engine.predecessor_binding(),scope)
    assert d.digest(scope)!=v['scope_sha256']


@pytest.mark.parametrize('bad',['old_authorization','different_digest','stale','resources','context_second','parent_changed'])
def test_application_revalidates_and_requires_new_exact_authorization(setup,bad):
    engine,records,current,now=setup;before=snapshot(engine);v=report(setup);sha=v['scope_sha256'];auth=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}';calls=[]
    if bad=='old_authorization':auth=engine.query()['authorization']
    elif bad=='different_digest':sha='f'*64;auth=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}'
    def observe():
        calls.append(1);c=copy.deepcopy(current)
        if bad=='stale':c['observed_monotonic']-=10
        elif bad=='resources':c['resources'].update(status='OCCUPIED',reasons=['IN_USE'])
        elif bad=='context_second' and len(calls)==2:records['environment']['state']['StartedAt']='2026-10-31T15:00:00Z'
        elif bad=='parent_changed' and len(calls)==2:
            (engine.root/'intent.json').write_bytes(before['intent.json']+b' ')
        return c
    with pytest.raises(ValueError):engine.apply_successor(records,observe,scope_sha256=sha,authorization=auth)
    if bad!='parent_changed':assert snapshot(engine)==before
    assert not (engine.root/'revisions').exists()


@pytest.mark.parametrize('phase',['originals','final','after_final'])
def test_interrupted_successor_persistence_keeps_original_and_blocks_replay(setup,phase):
    engine,records,current,now=setup;before=snapshot(engine);v=report(setup);sha=v['scope_sha256'];real=engine.write
    def fail(path,value):
        if phase=='originals' and path.name=='originals.json':raise OSError('SYNTHETIC storage failure')
        if phase=='final' and path.name=='intent.json':raise KeyboardInterrupt('SYNTHETIC interruption')
        real(path,value)
        if phase=='after_final' and path.name=='intent.json':raise OSError('SYNTHETIC lost completion')
    engine.write=fail
    with pytest.raises((OSError,KeyboardInterrupt)):
        engine.apply_successor(records,lambda:copy.deepcopy(current),scope_sha256=sha,
            authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}')
    assert snapshot(engine)==before and engine.query()['status']=='APPLYING_UNCONFIRMED'
    with pytest.raises(ValueError):
        engine.apply_successor(records,lambda:pytest.fail('No replay'),scope_sha256=sha,
            authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}')
    assert snapshot(engine)==before


@pytest.mark.parametrize('bad',['link','scope','authorization','owner','symlink','ambiguous','missing_intent','extra_file'])
def test_corrupt_partial_or_ambiguous_successor_never_falls_back(setup,bad,tmp_path):
    engine,records,current,now=setup;before=snapshot(engine);succ=apply(setup);path=engine.root/'revisions'/succ['scope_sha256'];v=read(path/'intent.json')
    if bad=='link':v['scope']['consumer_revision']['audit_file_hashes']['intent.json']='0'*64;dump(path/'intent.json',v)
    elif bad=='scope':v['scope']['reader_hashes']={};dump(path/'intent.json',v)
    elif bad=='authorization':v['authorization']='old';dump(path/'intent.json',v)
    elif bad=='owner':v['owner_id']='12345678-1234-4234-8234-123456789abc';dump(path/'intent.json',v)
    elif bad=='symlink':
        outside=tmp_path/'outside';shutil.move(path,outside);path.symlink_to(outside,target_is_directory=True)
    elif bad=='ambiguous':(path.parent/('f'*64)).mkdir()
    elif bad=='missing_intent':(path/'intent.json').unlink()
    else:(path.parent/'unrecognized.json').write_text('{}')
    assert engine.query()['status']=='APPLYING_UNCONFIRMED' and snapshot(engine)==before


def test_empty_interrupted_revision_directory_blocks_replay(setup):
    engine,records,current,now=setup;(engine.root/'revisions').mkdir()
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'


def test_predecessor_bytes_changed_after_successor_blocks_even_if_json_same(setup):
    engine,records,current,now=setup;before=snapshot(engine);apply(setup)
    (engine.root/'originals.json').write_bytes(before['originals.json']+b' ')
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'


@pytest.mark.parametrize('bad',['link','other_pin','context','from_version'])
def test_semantic_corruption_rejected_even_with_consistent_new_digest_and_declaration(setup,bad):
    engine,records,current,now=setup;succ=apply(setup);path=engine.root/'revisions'/succ['scope_sha256']
    value=read(path/'intent.json')
    if bad=='link':value['scope']['consumer_revision']['audit_file_hashes']['intent.json']='0'*64
    elif bad=='other_pin':value['scope']['reader_hashes']['tools/rover_xrce_trace/budget.py']='f'*64
    elif bad=='context':value['scope']['environment_execution']['container_boot_id']='different'
    else:value['scope']['consumer_revision']['before_sha256']='a'*64
    sha=d.digest(value['scope']);value['scope_sha256']=sha
    value['authorization']=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}'
    dump(path/'intent.json',value);dump(path/'originals.json',value['scope']);path.rename(path.parent/sha)
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'


def test_different_second_successor_cannot_reuse_existing_authorization(setup):
    # A later successor is possible only on the chain tip, after two fresh
    # revalidations that reproduce its exact reviewed digest.
    engine,records,current,now=setup;succ=apply(setup);sha='a'*64;calls=[]
    def observe():calls.append(1);return copy.deepcopy(current)
    with pytest.raises(ValueError,match='scope changed'):
        engine.apply_successor(records,observe,scope_sha256=sha,
            authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}')
    assert calls==[1] and [p.name for p in (engine.root/'revisions').iterdir()]==[succ['scope_sha256']]


def test_review_expiry_includes_successor_link_validation(setup,monkeypatch):
    engine,records,current,now=setup;clock=iter([current['observed_monotonic']+2.8,current['observed_monotonic']+3.1])
    monkeypatch.setattr(d.time,'monotonic',lambda:next(clock))
    v=d.dry_run(records,{**current,'consumer_predecessor':engine.predecessor_binding()})
    assert v['status']=='BLOCKED' and not v['conditions']['fresh_observation']


def test_project_review_application_and_precheck_use_same_owner_store_and_locks(setup,monkeypatch,tmp_path):
    engine,records,current,now=setup;owner=engine.owner
    lockroot=tmp_path/'project/generated/vehicle_locks';lockroot.mkdir(parents=True)
    for name in ('v1.execution.lock','registry.lock'):(lockroot/name).touch()
    monkeypatch.setattr(d.locks,'LOCK_ROOT',lockroot);monkeypatch.setattr(d.time,'monotonic',lambda:now)
    store=d.ProjectDisposition(owner);store.root.parent.mkdir(parents=True)
    shutil.copytree(engine.root,store.root);before=snapshot(store);calls=[]
    def synthetic_current(context=None,*,present=False):
        # Standalone precheck calls the default route; current_records itself
        # upgrades it to present-resource observation for a V3 retained audit.
        calls.append(present)
        assert present or store.query().get('schema')=='tfg.diagnostic-disposition/3'
        c=copy.deepcopy(current)
        if store.query().get('consumer_successor') is not None:c['consumer_predecessor']=store.predecessor_binding()
        return copy.deepcopy(records),c
    monkeypatch.setattr(d,'current_records',synthetic_current)
    v=d.real_dry_run(present=True,successor_owner=owner);assert v['status']=='DRY_RUN_ELIGIBLE',v
    sha=v['scope_sha256'];succ=store.apply_successor_reviewed(scope_sha256=sha,
        authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {owner} {sha}')
    assert succ['scope_sha256']==sha and calls==[True,True,True]
    decision=d.current_diagnostic_precheck()
    assert decision['status']=='SATISFIED' and decision['disposition_consumed'],decision
    assert snapshot(store)==before and not list(lockroot.glob('*.json'))


def test_existing_project_exclusion_also_blocks_successor(setup):
    engine,records,current,now=setup;v=report(setup);sha=v['scope_sha256']
    with d.locks.file_mutex(engine.lock_root/'v1.execution.lock'):
        with pytest.raises(d.locks.VehicleBusy):
            engine.apply_successor(records,lambda:pytest.fail('No unlocked read'),scope_sha256=sha,
                authorization=f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}')


@pytest.mark.parametrize('bad',['missing','stale','failed','reader','malformed','conditions','resources'])
def test_stored_successor_requires_both_valid_revalidation_receipts(setup,bad):
    engine,records,current,now=setup;succ=apply(setup);path=engine.root/'revisions'/succ['scope_sha256'];value=read(path/'intent.json')
    if bad=='missing':value['application_observations'].pop()
    elif bad=='stale':value['application_observations'][1]['host_window_s']=3.1
    elif bad=='failed':value['application_observations'][1]['current_conditions']['fresh_observation']=False
    elif bad=='reader':value['application_observations'][1]['resources']['reader_hashes']={}
    elif bad=='malformed':value['application_observations'][1]=[]
    elif bad=='conditions':value['application_observations'][1]['current_conditions']=[]
    else:value['application_observations'][1]['resources']=[]
    dump(path/'intent.json',value)
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'
