"""Persistence regressions under an OFFLINE confirmation verifier double.

The production verifier is deliberately blocked. These transaction tests preserve
durability/exclusion coverage; they are not proof of an available human channel.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tools import legacy_administrative_retirement as retirement
from tools import execution_reconciliation as audit
from tools import vehicle_execution_lock as locks
from tools import virtual_preflight_jobs as jobs
from tools import preflight_sequences as sequences
from tools import simulation_lifecycle as lifecycle
from tests.test_mission_response_views import registered

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'simulation/ros2_gazebo/results/legacy_binding_review_2026_10_19/expired_inspection_original.json'
PRODUCTION_CONFIRMATION_GATE = retirement._require_operator_confirmation


@pytest.fixture
def system(tmp_path,monkeypatch):
    monkeypatch.setattr(retirement,'ROOT',tmp_path/'administrative_case')
    monkeypatch.setattr(jobs,'RUN_ROOT',tmp_path/'runs')
    monkeypatch.setattr(sequences,'SEQUENCE_ROOT',tmp_path/'sequences')
    monkeypatch.setattr(audit,'boot_id',lambda:'offline-host-boot')
    def offline_confirmation_double(identifier, digest, claim):
        assert claim['preparation_id']==identifier
        assert claim['preparation_sha256']==digest
    monkeypatch.setattr(retirement,'_require_operator_confirmation',offline_confirmation_double)
    actor={'pid':123,'start_ticks':1,'boot_id':'offline-host-boot'}
    monkeypatch.setattr(locks,'process_identity',lambda pid=None:None if pid is not None else deepcopy(actor))
    record=json.loads(FIXTURE.read_bytes())
    for name,entry in record['snapshot']['files'].items():
        rel=Path(name).relative_to(retirement.ORIGINAL_ROOT/'missions/generated')
        base={'vehicle_locks':locks.LOCK_ROOT,'preflights':jobs.RUN_ROOT,'preflight_sequences':sequences.SEQUENCE_ROOT}[rel.parts[0]]
        path=base.joinpath(*rel.parts[1:])
        if 'content' in entry:
            raw=entry['content'].encode();assert hashlib.sha256(raw).hexdigest()==entry['sha256']
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    environment=Mock(side_effect=lambda:deepcopy(record['environment']))
    monkeypatch.setattr(retirement,'inspect_environment',environment)
    collector=Mock(side_effect=AssertionError('No telemetry/control in administrative retirement'))
    monkeypatch.setattr(audit,'collect_observations',collector)
    spawn=Mock(side_effect=AssertionError('No workers or flights may start'))
    monkeypatch.setattr(jobs.subprocess,'Popen',spawn)
    originals={p:p.read_bytes() for base in (locks.LOCK_ROOT,jobs.RUN_ROOT,sequences.SEQUENCE_ROOT)
               for p in base.rglob('*.json')}
    return SimpleNamespace(record=record,environment=environment,collector=collector,spawn=spawn,
                           originals=originals,root=retirement.ROOT)


def prepare():
    value=retirement.prepare_legacy_sequence_retirement()
    assert value['status']=='AWAITING_EXPLICIT_ADMINISTRATIVE_AUTHORIZATION',value
    return value


def authorization():
    return {'source':'OPERATOR_ADMINISTRATIVE_DECISION','accept_unverified_historical_environment':True,
            'accept_unknown_historical_clocks':True,'local_reservations_only':True,
            'statement':'Authorize only retirement of these exact local restrictions despite unresolved historical environment and clocks; no landing or flight claim'}


def arguments(prepared):
    return {'preparation_id':prepared['preparation_id'],'preparation_sha256':prepared['preparation_sha256'],
            'authorization':{**authorization(),'preparation_id':prepared['preparation_id'],
                             'preparation_sha256':prepared['preparation_sha256']}}


def apply(prepared):
    return retirement.apply_legacy_sequence_retirement(**arguments(prepared))


def assert_history_untouched(system):
    for path,raw in system.originals.items():
        if path.parent!=locks.LOCK_ROOT:assert path.read_bytes()==raw


def tree(root):
    return {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_prepare_reads_only_original_case_and_unknown_history_is_not_a_true_claim(system):
    original={p:p.read_bytes() for p in system.originals}
    prepared=prepare()
    assert prepared['preparation']['original_environment_termination']=='UNKNOWN'
    assert prepared['preparation']['historical_clock_comparability']=='UNKNOWN'
    assert prepared['preparation']['reservations_changed'] is False
    assert all(path.read_bytes()==raw for path,raw in original.items())
    assert not (system.root/'intent.json').exists()
    assert not (locks.LOCK_ROOT/'reconciliation.json').exists()
    system.collector.assert_not_called();system.spawn.assert_not_called()


def test_apply_archives_both_exact_originals_and_preserves_error_passed_unconfirmed(system):
    prepared=prepare();result=apply(prepared)
    assert result['status']==retirement.RESULT and result['flight_authorized'] is False
    for name in retirement.ORDER:
        assert not (locks.LOCK_ROOT/name).exists()
        assert (locks.LOCK_ROOT/'history'/prepared['preparation_id']/name).read_bytes()==system.originals[locks.LOCK_ROOT/name]
    assert locks.restriction() is None
    assert result['result']['original_environment_termination']=='UNKNOWN'
    assert result['result']['ground_contact']=='NOT_ASSERTED'
    assert_history_untouched(system)
    op=json.loads((sequences.SEQUENCE_ROOT/retirement.CASE_ID/'operation.json').read_bytes())
    assert op['job_state']=='UNCONFIRMED' and op['children'][0]['result_status']=='PASSED'
    failed=jobs.RUN_ROOT/'1b69dfc7-0707-4b68-a009-062610418fe4'/'report.json'
    assert json.loads(failed.read_bytes())['status']=='ERROR'
    system.collector.assert_not_called();system.spawn.assert_not_called()


def test_completed_application_and_query_are_idempotent_without_new_observations(system):
    prepared=prepare();assert apply(prepared)['status']==retirement.RESULT
    before=tree(system.root)|tree(locks.LOCK_ROOT)
    system.environment.reset_mock()
    result=apply(prepared)
    assert result['status']==retirement.RESULT and result['replayed'] is True
    assert retirement.get_legacy_sequence_retirement()['status']==retirement.RESULT
    assert (tree(system.root)|tree(locks.LOCK_ROOT))==before
    system.environment.assert_not_called()
    # A later unrelated barrier must not be removed by replaying the old result.
    unrelated={'kind':'RECONCILIATION','owner_id':str(uuid4()),'state':'UNCONFIRMED'}
    locks.atomic_json(locks.LOCK_ROOT/'reconciliation.json',unrelated)
    assert apply(prepared)['status']==retirement.RESULT
    assert json.loads((locks.LOCK_ROOT/'reconciliation.json').read_bytes())==unrelated


@pytest.mark.parametrize('change',['owner','guard_version','report','unexpected_v1','policy','expired','boot','alive','pid_recycled','environment','hash'])
def test_changed_or_uncertain_preconditions_block_before_intent_or_removal(system,monkeypatch,change):
    prepared=prepare();args=arguments(prepared)
    if change in ('owner','guard_version'):
        p=locks.LOCK_ROOT/'v2.json';v=json.loads(p.read_bytes())
        v['owner_id' if change=='owner' else 'state']=str(uuid4()) if change=='owner' else 'EXECUTING'
        locks.atomic_json(p,v)
    elif change=='report':
        p=jobs.RUN_ROOT/'1b69dfc7-0707-4b68-a009-062610418fe4'/'report.json';p.write_text('{}')
    elif change=='unexpected_v1':locks.atomic_json(locks.LOCK_ROOT/'v1.json',{'owner_id':str(uuid4())})
    elif change=='policy':monkeypatch.setattr(retirement,'POLICY_SHA256','0'*64)
    elif change=='expired':
        now=retirement.time.monotonic();monkeypatch.setattr(retirement.time,'monotonic',lambda:now+121)
    elif change=='boot':monkeypatch.setattr(audit,'boot_id',lambda:'another-host-boot')
    elif change in ('alive','pid_recycled'):
        pid=system.record['snapshot']['guards']['sequence.json']['coordinator']['pid']
        monkeypatch.setattr(locks,'process_identity',lambda requested=None:{'pid':requested or 123,'start_ticks':8003617 if change=='alive' else 999,'boot_id':'test-boot'})
    elif change=='environment':
        value=deepcopy(system.record['environment']);value['container_id']='a'*64
        system.environment.side_effect=lambda:value
    else:args['preparation_sha256']='f'*64
    result=retirement.apply_legacy_sequence_retirement(**args)
    assert result['status']=='BLOCKED',result
    assert (locks.LOCK_ROOT/'sequence.json').exists() and (locks.LOCK_ROOT/'v2.json').exists()
    assert not (system.root/'intent.json').exists()
    assert not (locks.LOCK_ROOT/'reconciliation.json').exists()


@pytest.mark.parametrize('change',['missing','refuses_uncertainty','refuses_clocks','blank','extra_force'])
def test_explicit_administrative_acceptance_is_required_without_false_historical_facts(system,change):
    prepared=prepare();args=arguments(prepared)
    if change=='missing':args['authorization']={}
    elif change=='refuses_uncertainty':args['authorization']['accept_unverified_historical_environment']=False
    elif change=='refuses_clocks':args['authorization']['accept_unknown_historical_clocks']=False
    elif change=='blank':args['authorization']['statement']=' '
    else:args['authorization']['force']=True
    assert retirement.apply_legacy_sequence_retirement(**args)['status']=='BLOCKED'
    assert not (system.root/'intent.json').exists()
    assert all((locks.LOCK_ROOT/name).exists() for name in retirement.ORDER)


def test_other_case_is_rejected_without_operational_observation(system):
    system.environment.reset_mock()
    assert retirement.prepare_legacy_sequence_retirement(str(uuid4()))['status']=='BLOCKED'
    system.environment.assert_not_called()


@pytest.mark.parametrize('cut',['intent_before','barrier_before','archive_one_after','archive_two_after','remove_sequence','final_before','final_after','barrier_remove','barrier_dirsync'])
def test_partial_failures_keep_auditable_protection_and_explicit_identical_recovery(system,monkeypatch,cut):
    prepared=prepare();write=retirement._write_once;unlink=Path.unlink;sync=retirement._sync
    injected=False
    def write_cut(path,raw):
        nonlocal injected
        trigger=(cut=='intent_before' and path==system.root/'intent.json'
                 or cut=='barrier_before' and path==locks.LOCK_ROOT/'reconciliation.json'
                 or cut=='final_before' and path==system.root/'result.json')
        if trigger and not injected:injected=True;raise OSError('injected persistence failure before publication')
        write(path,raw)
        trigger=(cut=='archive_one_after' and path==locks.LOCK_ROOT/'history'/prepared['preparation_id']/'v2.json'
                 or cut=='archive_two_after' and path==locks.LOCK_ROOT/'history'/prepared['preparation_id']/'sequence.json'
                 or cut=='final_after' and path==system.root/'result.json')
        if trigger and not injected:injected=True;raise OSError('injected interruption after durable publication')
    def unlink_cut(path,*args,**kwargs):
        nonlocal injected
        if not injected and (cut=='remove_sequence' and path==locks.LOCK_ROOT/'sequence.json'
                             or cut=='barrier_remove' and path==locks.LOCK_ROOT/'reconciliation.json'):
            injected=True;raise OSError('injected removal failure')
        return unlink(path,*args,**kwargs)
    def sync_cut(directory):
        nonlocal injected
        if (cut=='barrier_dirsync' and not injected and directory==locks.LOCK_ROOT
                and (system.root/'result.json').exists() and not (locks.LOCK_ROOT/'reconciliation.json').exists()):
            injected=True;raise OSError('injected final directory fsync failure')
        return sync(directory)
    monkeypatch.setattr(retirement,'_write_once',write_cut)
    monkeypatch.setattr(Path,'unlink',unlink_cut)
    monkeypatch.setattr(retirement,'_sync',sync_cut)
    failed=apply(prepared);assert failed['status']=='BLOCKED' and injected,failed
    assert_history_untouched(system)
    remaining=[name for name in retirement.ORDER if (locks.LOCK_ROOT/name).exists()]
    if remaining!=list(retirement.ORDER):
        assert (locks.LOCK_ROOT/'reconciliation.json').exists()
        assert locks.restriction()['kind']==retirement.KIND
        for name in retirement.ORDER:
            assert (locks.LOCK_ROOT/'history'/prepared['preparation_id']/name).read_bytes()==system.originals[locks.LOCK_ROOT/name]
    state_before=tree(system.root)|tree(locks.LOCK_ROOT)
    system.environment.reset_mock()
    view=retirement.get_legacy_sequence_retirement()
    assert view['status']==('RECOVERY_REQUIRED' if (system.root/'intent.json').exists() else 'AWAITING_EXPLICIT_ADMINISTRATIVE_AUTHORIZATION')
    assert view['observed_remaining_guard_files']==remaining
    assert (tree(system.root)|tree(locks.LOCK_ROOT))==state_before
    system.environment.assert_not_called()
    recovered=apply(prepared)
    assert recovered['status']==retirement.RESULT,recovered
    assert locks.restriction() is None
    assert_history_untouched(system)


def test_interrupted_transaction_stays_blocked_after_expiry_and_module_reload(system,monkeypatch):
    prepared=prepare();original=Path.unlink
    def stop(path,*args,**kwargs):
        if path==locks.LOCK_ROOT/'sequence.json':raise OSError('synthetic crash after child removal')
        return original(path,*args,**kwargs)
    with monkeypatch.context() as local:
        local.setattr(Path,'unlink',stop)
        assert apply(prepared)['status']=='BLOCKED'
    now=retirement.time.monotonic();monkeypatch.setattr(retirement.time,'monotonic',lambda:now+121)
    spec=importlib.util.spec_from_file_location('reloaded_retirement',retirement.__file__)
    reloaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(reloaded)
    # Configure the shared temporary store BEFORE any API call; no real runtime writes.
    monkeypatch.setattr(reloaded,'ROOT',system.root)
    monkeypatch.setattr(reloaded,'inspect_environment',system.environment)
    before=tree(system.root)|tree(locks.LOCK_ROOT);system.environment.reset_mock()
    view=reloaded.get_legacy_sequence_retirement()
    assert view['status']=='RECOVERY_REQUIRED' and view['preparation_expired'] is True
    assert view['accepted_request']==arguments(prepared)
    assert (tree(system.root)|tree(locks.LOCK_ROOT))==before
    system.environment.assert_not_called()
    result=reloaded.apply_legacy_sequence_retirement(**arguments(prepared))
    assert result['status']=='BLOCKED' and result['error_code']=='PREPARATION_EXPIRED_OR_BOOT_CHANGED'
    assert (tree(system.root)|tree(locks.LOCK_ROOT))==before
    system.environment.assert_not_called()
    assert (locks.LOCK_ROOT/'reconciliation.json').exists()


def test_persistent_barrier_blocks_real_async_admission_and_lifecycle_after_interruption(system,monkeypatch):
    prepared=prepare();write=retirement._write_once
    def cut(path,raw):
        if path==system.root/'result.json':raise OSError('interrupted after both local removals')
        return write(path,raw)
    with monkeypatch.context() as local:
        local.setattr(retirement,'_write_once',cut);assert apply(prepared)['status']=='BLOCKED'
    backend=Mock();monkeypatch.setattr(lifecycle,'_backend',backend)
    for action in ('start','stop','restart'):assert lifecycle.run_lifecycle(action)['status']=='BLOCKED'
    backend.assert_not_called()
    path=jobs.RUN_ROOT/'467f7ec6-b2a6-4b68-9d97-766d85732f8e'/'input.json'
    admitted=jobs.start_virtual_preflight(str(path),'must-not-start-during-retirement')
    assert admitted['admission_status']=='VEHICLE_BUSY'
    for vehicle in ('v1','v2'):
        with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'interloper',vehicle)
    system.spawn.assert_not_called()
    assert apply(prepared)['status']==retirement.RESULT


def test_new_authorization_or_another_preparation_cannot_take_over_accepted_transaction(system,monkeypatch):
    prepared=prepare();other=prepare();write=retirement._write_once
    def cut(path,raw):
        if path==locks.LOCK_ROOT/'reconciliation.json':raise OSError('interrupt after intent')
        return write(path,raw)
    with monkeypatch.context() as local:
        local.setattr(retirement,'_write_once',cut)
        assert apply(prepared)['status']=='BLOCKED'
    args=arguments(prepared);args['authorization']['statement']='different authorization'
    assert retirement.apply_legacy_sequence_retirement(**args)['status']=='BLOCKED'
    assert apply(other)['status']=='BLOCKED'
    assert retirement.prepare_legacy_sequence_retirement()['preparation_id']==prepared['preparation_id']
    assert apply(prepared)['status']==retirement.RESULT


def test_archive_failure_at_atomic_link_is_recoverable_without_overwriting_published_evidence(system,monkeypatch):
    prepared=prepare();link=retirement.os.link;injected=False
    def cut(source,destination,*a,**k):
        nonlocal injected
        result=link(source,destination,*a,**k)
        if destination==locks.LOCK_ROOT/'history'/prepared['preparation_id']/'sequence.json' and not injected:
            injected=True;raise OSError('crash between link and directory fsync')
        return result
    monkeypatch.setattr(retirement.os,'link',cut)
    assert apply(prepared)['status']=='BLOCKED' and injected
    raw=(locks.LOCK_ROOT/'history'/prepared['preparation_id']/'sequence.json').read_bytes()
    assert apply(prepared)['status']==retirement.RESULT
    assert (locks.LOCK_ROOT/'history'/prepared['preparation_id']/'sequence.json').read_bytes()==raw


def test_final_result_link_failure_recovery_refsyncs_result_before_barrier_removal(system,monkeypatch):
    prepared=prepare();link=retirement.os.link;injected=False
    def cut(source,destination,*a,**k):
        nonlocal injected
        value=link(source,destination,*a,**k)
        if destination==system.root/'result.json' and not injected:
            injected=True;raise OSError('interrupted final publication before parent directory fsync')
        return value
    monkeypatch.setattr(retirement.os,'link',cut)
    assert apply(prepared)['status']=='BLOCKED' and injected
    assert retirement.get_legacy_sequence_retirement()['status']=='RECOVERY_REQUIRED'
    sync=retirement._sync;unlink=Path.unlink;events=[]
    def seen_sync(directory):
        events.append(('sync',directory));return sync(directory)
    def seen_unlink(path,*a,**k):
        if path==locks.LOCK_ROOT/'reconciliation.json':events.append(('remove_barrier',path))
        return unlink(path,*a,**k)
    monkeypatch.setattr(retirement,'_sync',seen_sync);monkeypatch.setattr(Path,'unlink',seen_unlink)
    assert apply(prepared)['status']==retirement.RESULT
    assert events.index(('sync',system.root)) < events.index(('remove_barrier',locks.LOCK_ROOT/'reconciliation.json'))


@pytest.mark.parametrize('damage',['owner','artifact','archive','barrier','missing_barrier'])
def test_changed_partial_transaction_stays_blocked_without_silent_release(system,monkeypatch,damage):
    prepared=prepare();unlink=Path.unlink
    def cut(path,*a,**k):
        if path==locks.LOCK_ROOT/'sequence.json':raise OSError('synthetic crash after child removal')
        return unlink(path,*a,**k)
    with monkeypatch.context() as local:
        local.setattr(Path,'unlink',cut);assert apply(prepared)['status']=='BLOCKED'
    if damage=='owner':
        p=locks.LOCK_ROOT/'sequence.json';v=json.loads(p.read_bytes());v['owner_id']=str(uuid4());locks.atomic_json(p,v)
    elif damage=='artifact':
        p=jobs.RUN_ROOT/'1b69dfc7-0707-4b68-a009-062610418fe4'/'report.json';p.write_text('{}')
    elif damage=='archive':(locks.LOCK_ROOT/'history'/prepared['preparation_id']/'v2.json').write_text('{}')
    elif damage=='barrier':
        p=locks.LOCK_ROOT/'reconciliation.json';v=json.loads(p.read_bytes());v['intent_sha256']='f'*64;locks.atomic_json(p,v)
    else:(locks.LOCK_ROOT/'reconciliation.json').unlink()
    assert apply(prepared)['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'sequence.json').exists()
    if damage in ('archive','barrier','missing_barrier'):
        assert retirement.get_legacy_sequence_retirement()['status']=='ERROR'


def test_artifact_change_during_environment_probe_blocks_before_intent(system):
    prepared=prepare()
    def observe():
        p=jobs.RUN_ROOT/'1b69dfc7-0707-4b68-a009-062610418fe4'/'report.json';p.write_text('{}')
        return deepcopy(system.record['environment'])
    system.environment.side_effect=observe
    assert apply(prepared)['status']=='BLOCKED'
    assert not (system.root/'intent.json').exists()
    assert all((locks.LOCK_ROOT/name).exists() for name in retirement.ORDER)


def test_execution_mutex_blocks_preparation_and_application_without_waiting_or_observing(system):
    prepared=prepare();system.environment.reset_mock()
    with locks.file_mutex(locks.LOCK_ROOT/'v1.execution.lock'):
        assert retirement.prepare_legacy_sequence_retirement()['status']=='BLOCKED'
        assert apply(prepared)['status']=='BLOCKED'
    system.environment.assert_not_called()
    assert not (system.root/'intent.json').exists()


@pytest.mark.parametrize('damage',['guard_content','process_list','case_id','symlink'])
def test_preparation_corruption_or_path_alias_never_expands_scope(system,damage,tmp_path):
    prepared=prepare();path=Path(prepared['paths']['preparation']);value=json.loads(path.read_bytes())
    if damage=='guard_content':value['snapshot']['files'][str(locks.LOCK_ROOT/'v2.json')]['content']='{}'
    elif damage=='process_list':value['snapshot']['processes']=[]
    elif damage=='case_id':value['case_id']=str(uuid4())
    else:
        external=tmp_path/'external.json';external.write_bytes(path.read_bytes());path.unlink();path.symlink_to(external)
    if damage!='symlink':locks.atomic_json(path,value)
    args=arguments(prepared);args['preparation_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    assert retirement.apply_legacy_sequence_retirement(**args)['status']=='BLOCKED'
    assert all((locks.LOCK_ROOT/name).exists() for name in retirement.ORDER)
    assert not (system.root/'intent.json').exists()


def test_concurrent_admissions_lifecycle_and_second_application_excluded_after_both_guard_removals(system,monkeypatch):
    prepared=prepare();entered,finish=Event(),Event();write=retirement._write_once
    backend=Mock();monkeypatch.setattr(lifecycle,'_backend',backend)
    def pause(path,raw):
        if path==system.root/'result.json':
            entered.set();assert finish.wait(10)
        return write(path,raw)
    monkeypatch.setattr(retirement,'_write_once',pause)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(apply,prepared);assert entered.wait(10)
        try:
            assert not (locks.LOCK_ROOT/'sequence.json').exists() and not (locks.LOCK_ROOT/'v2.json').exists()
            assert locks.restriction()['kind']==retirement.KIND
            for vehicle in ('v1','v2'):
                with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'interloper',vehicle)
            with pytest.raises(locks.VehicleBusy):locks.reserve_sequence(str(uuid4()),'a'*64,[])
            for action in ('start','stop','restart'):assert lifecycle.run_lifecycle(action)['status']=='BLOCKED'
            assert apply(prepared)['status']=='BLOCKED'
            backend.assert_not_called();system.spawn.assert_not_called()
        finally:finish.set()
        assert future.result()['status']==retirement.RESULT


def test_environment_or_files_changing_while_archiving_block_before_guard_removal(system,monkeypatch):
    prepared=prepare();write=retirement._write_once
    def change(path,raw):
        write(path,raw)
        if path==locks.LOCK_ROOT/'history'/prepared['preparation_id']/'sequence.json':
            value=deepcopy(system.record['environment']);value['state']['Pid']=99
            system.environment.side_effect=lambda:value
    monkeypatch.setattr(retirement,'_write_once',change)
    assert apply(prepared)['status']=='BLOCKED'
    assert all((locks.LOCK_ROOT/name).exists() for name in retirement.ORDER)
    assert (locks.LOCK_ROOT/'reconciliation.json').exists()


def test_registered_mcp_schemas_enforce_one_case_and_accept_uncertainty_not_claims(system,monkeypatch):
    import asyncio
    from tools import hermes_mcp_server as server
    schemas={t.name:t.input_schema for t in asyncio.run(server.mcp.list_tools())}
    assert schemas['prepare_legacy_sequence_retirement']['properties']['sequence_id']['const']==retirement.CASE_ID
    assert 'force' not in schemas['apply_legacy_sequence_retirement']['properties']
    model=schemas['apply_legacy_sequence_retirement']['$defs']['AdministrativeRetirementAuthorization']
    assert model['properties']['accept_unverified_historical_environment']['const'] is True
    assert 'continuous_project_environment' not in model['properties']
    call=Mock(return_value={'status':'DOUBLE'});monkeypatch.setattr(retirement,'apply_legacy_sequence_retirement',call)
    prepared=prepare();args=arguments(prepared)
    assert registered('apply_legacy_sequence_retirement',args)['status']=='DOUBLE'
    call.assert_called_once_with(args['preparation_id'],args['preparation_sha256'],args['authorization'])
    prepare_call=Mock();monkeypatch.setattr(retirement,'prepare_legacy_sequence_retirement',prepare_call)
    with pytest.raises(Exception):registered('prepare_legacy_sequence_retirement',{'sequence_id':str(uuid4())})
    prepare_call.assert_not_called()


def test_registered_query_never_prepares_applies_or_observes(system,monkeypatch):
    prepared=prepare();before=tree(system.root)|tree(locks.LOCK_ROOT)
    system.environment.reset_mock()
    prepare_call=Mock(side_effect=AssertionError('query cannot prepare'))
    apply_call=Mock(side_effect=AssertionError('query cannot apply'))
    monkeypatch.setattr(retirement,'prepare_legacy_sequence_retirement',prepare_call)
    monkeypatch.setattr(retirement,'apply_legacy_sequence_retirement',apply_call)
    assert registered('get_legacy_sequence_retirement',{})['preparation_id']==prepared['preparation_id']
    assert (tree(system.root)|tree(locks.LOCK_ROOT))==before
    system.environment.assert_not_called()


@pytest.mark.parametrize('identifier',['../outside','bad-id',str(uuid4())])
def test_lookup_rejects_arbitrary_paths_and_unknown_identifiers_without_effects(system,identifier):
    before=tree(system.root)|tree(locks.LOCK_ROOT)
    assert retirement.get_legacy_sequence_retirement(identifier)['status']=='ERROR'
    assert (tree(system.root)|tree(locks.LOCK_ROOT))==before
    system.environment.assert_not_called()
