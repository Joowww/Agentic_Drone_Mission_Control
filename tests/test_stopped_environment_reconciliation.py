"""Stopped environment administrative closure with synthetic process/Docker evidence."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.test_execution_reconciliation import system, environment
from tools import execution_reconciliation as reconcile
from tools import vehicle_execution_lock as locks
from tools import simulation_lifecycle as lifecycle


def legacy_reference(system):
    root=reconcile.INSPECTION_ROOT/str(uuid4());root.mkdir(parents=True)
    value={'inspection_id':root.name,'target_id':system[0],'status':'BLOCKED','reservations_changed':False,
           'created_at':'2026-10-19T18:38:58+00:00','exception_type':'RuntimeError',
           'reasons':['RuntimeError: Read-only collector returned 1: Error response from daemon: container '+ 'a'*64+' is not running\n']}
    locks.atomic_json(root/'inspection.json',value)
    return root/'inspection.json'


def stopped(system,monkeypatch):
    reference=legacy_reference(system)
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(side_effect=lambda:environment(False)))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='AWAITING_LEGACY_ENVIRONMENT_REVIEW'
    return reference,inspected


def apply(inspected, **changes):
    args={'inspection_id':inspected['inspection_id'],'inspection_sha256':inspected['inspection_sha256'],
          'authorization_statement':'Explicitly authorize administrative closure of this terminated SITL environment only; no landing/success/flight claim'}
    if inspected.get('reconciliation_basis')=='ENVIRONMENT_TERMINATED':
        args['legacy_environment_confirmation']=confirmation(inspected)
    args.update(changes)
    return args,reconcile.apply_execution_reconciliation(**args)


def confirmation(inspected):
    return {'source':'OPERATOR_ENVIRONMENT_REVIEW','engine_id':inspected['environment'].get('engine_id','unknown'),
            'container_id':inspected['environment'].get('container_id','a'*64),
            'continuous_project_environment':True,'wall_clock_comparison_supported':True,
            'statement':'Synthetic operator reviewed unchanged Docker deployment/selector and UTC wall clock evidence; no substitution or metadata clone known'}


def test_stopped_inspection_keeps_owners_unknowns_and_does_not_collect_or_change_reservations(system,monkeypatch):
    original=(locks.LOCK_ROOT/'v2.json').read_bytes()
    reference,inspected=stopped(system,monkeypatch)
    assert inspected['summary']['reservations']['v2.json']['owner_id']==system[0]
    assert inspected['identity_reference']['sha256']==hashlib.sha256(reference.read_bytes()).hexdigest()
    assert inspected['identity_reference']['historical_engine_identity_known'] is False
    assert inspected['telemetry_collection']=='NOT_APPLICABLE_ENVIRONMENT_STOPPED'
    assert inspected['applicability']['requires_ground_confirmations'] is False
    assert inspected['ground_contact']=='NOT_ASSERTED' and inspected['application_eligible'] is False
    assert inspected['applicability']['requires_legacy_environment_confirmation'] is True
    assert inspected['environment']['engine_id']=='synthetic-engine'
    assert (locks.LOCK_ROOT/'v2.json').read_bytes()==original
    system[2].assert_not_called()


def test_administrative_apply_preserves_failed_job_reports_and_original_reservation_and_reference(system,monkeypatch):
    originals={str(p):p.read_bytes() for p in system[1].iterdir() if p.is_file()}
    guard=(locks.LOCK_ROOT/'v2.json').read_bytes()
    reference,inspected=stopped(system,monkeypatch);ref=reference.read_bytes()
    args,result=apply(inspected)
    assert result['status']=='APPLIED' and result['flight_authorized'] is False
    assert result['reconciliation_basis']=='ENVIRONMENT_TERMINATED' and result['ground_contact']=='NOT_ASSERTED'
    assert (locks.LOCK_ROOT/'history'/inspected['inspection_id']/'v2.json').read_bytes()==guard
    assert locks.restriction() is None
    assert originals=={str(p):p.read_bytes() for p in system[1].iterdir() if p.is_file()}
    assert reference.read_bytes()==ref
    result=reconcile.get_execution_reconciliation(inspected['inspection_id'])
    assert result['application']['transition']=='ADMINISTRATIVE_CLOSURE_ENVIRONMENT_TERMINATED'
    assert result['application']['historical_reports_modified'] is False
    reconcile.inspect_environment.reset_mock()
    assert reconcile.apply_execution_reconciliation(**args)['replayed'] is True
    reconcile.inspect_environment.assert_not_called();system[2].assert_not_called()


@pytest.mark.parametrize('change',['active','different_id','different_engine','different_finish','different_start','absent','unavailable','unknown','source_changed','owner_changed','pid_recycled','expired','boot','authorization_missing','irrelevant_ground'])
def test_revalidation_contradiction_never_removes_restrictions(system,monkeypatch,change):
    reference,inspected=stopped(system,monkeypatch);override={}
    value=environment(False)
    if change=='active':value=environment(True)
    elif change=='different_id':value['container_id']='f'*64
    elif change=='different_engine':value['engine_id']='other-engine'
    elif change=='different_finish':value['state']['FinishedAt']='2026-10-19T17:02:00Z'
    elif change=='different_start':value['state']['StartedAt']='2026-10-19T16:59:00Z'
    elif change in ('absent','unavailable','unknown'):value={'status':{'absent':'CONTAINER_ABSENT','unavailable':'DOCKER_UNAVAILABLE','unknown':'UNKNOWN'}[change]}
    elif change=='source_changed':reference.write_text(reference.read_text()+' ')
    elif change=='owner_changed':
        p=locks.LOCK_ROOT/'v2.json';v=json.loads(p.read_text());v['updated_at']='changed';locks.atomic_json(p,v)
    elif change=='pid_recycled':monkeypatch.setattr(locks,'process_identity',lambda pid=None:{'pid':pid or 123,'start_ticks':999,'boot_id':'test-boot'})
    elif change=='expired':
        now=reconcile.time.monotonic();monkeypatch.setattr(reconcile.time,'monotonic',lambda:now+121)
    elif change=='boot':monkeypatch.setattr(reconcile,'boot_id',lambda:'new-boot')
    elif change=='authorization_missing':override['authorization_statement']=' '
    else:override['ground_confirmations']=[{'vehicle':'v2','on_ground':True}]
    reconcile.inspect_environment.side_effect=lambda:deepcopy(value)
    assert apply(inspected,**override)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()
    system[2].assert_not_called()


@pytest.mark.parametrize('state',['DOCKER_UNAVAILABLE','CONTAINER_ABSENT','UNKNOWN','REPLACED'])
def test_unknown_or_replaced_environment_retains_known_owners_without_telemetry(system,monkeypatch,state):
    legacy_reference(system)
    value={'status':state,'reasons':['synthetic transport/metadata failure'],'unknown_fields':['state']}
    if state=='REPLACED':value=environment(False);value['container_id']='f'*64
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=value))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='BLOCKED' and inspected['reasons']
    assert inspected['summary']['reservations']['v2.json']['owner_id']==system[0]
    assert inspected['evidence_state']=='NOT_COLLECTED' and inspected['evidence_expired'] is None
    assert inspected['application_eligible'] is False
    assert apply(inspected)[1]['status']=='BLOCKED'
    system[2].assert_not_called()


def test_name_and_stopped_state_cannot_bootstrap_their_own_identity_reference(system,monkeypatch):
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=environment(False)))
    for _ in range(2):
        inspected=reconcile.inspect_execution_reconciliation(system[0])
        assert inspected['status']=='BLOCKED' and inspected['identity_reference'] is None
        assert 'no prior identity binding' in ' '.join(inspected['reasons'])
    system[2].assert_not_called()


def test_prior_active_audit_binds_full_engine_and_incarnation(system,monkeypatch):
    active=reconcile.inspect_execution_reconciliation(system[0])
    assert active['status']=='AWAITING_EXPLICIT_GROUND_CONFIRMATION'
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=environment(False)))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['identity_reference']['kind']=='ACTIVE_ENVIRONMENT_AUDIT'
    assert inspected['identity_reference']['historical_engine_identity_known'] is True
    assert apply(inspected)[1]['status']=='APPLIED'


@pytest.mark.parametrize('change',['engine','container','reference_missing'])
def test_stopped_inspection_rejects_replacement_or_restart_against_full_binding(system,monkeypatch,change):
    active=reconcile.inspect_execution_reconciliation(system[0])
    value=environment(False)
    if change=='engine':value['engine_id']='other-daemon'
    elif change=='container':value['container_id']='f'*64
    else:(reconcile.INSPECTION_ROOT/active['inspection_id']/'inspection.json').unlink()
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=value))
    result=reconcile.inspect_execution_reconciliation(system[0])
    assert result['status']=='BLOCKED' and result['application_eligible'] is False
    if change!='reference_missing':assert result['environment_assessment']=='REPLACED_OR_RESTARTED'


def test_same_exact_container_stopped_after_a_later_incarnation_still_terminates_prior_environment(system,monkeypatch):
    reconcile.inspect_execution_reconciliation(system[0])  # full active identity binding
    value=environment(False);value['state']['StartedAt']='2026-10-19T16:00:00Z'
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=value))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='AWAITING_LEGACY_ENVIRONMENT_REVIEW'
    assert apply(inspected)[1]['status']=='APPLIED'


def test_conflicting_legacy_identity_references_are_not_silently_selected(system,monkeypatch):
    legacy_reference(system)
    path=legacy_reference(system)
    path.write_text(path.read_text().replace('a'*64,'f'*64))
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=environment(False)))
    result=reconcile.inspect_execution_reconciliation(system[0])
    assert result['status']=='BLOCKED' and 'Conflicting retained' in ' '.join(result['reasons'])
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_identity_reference_cannot_follow_symlink_outside_fixed_audit_root(system,monkeypatch,tmp_path):
    source=legacy_reference(system)
    outside=tmp_path/'outside.json';outside.write_bytes(source.read_bytes())
    source.unlink();source.symlink_to(outside)
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=environment(False)))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='BLOCKED' and inspected['identity_reference'] is None
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_administrative_apply_rejects_record_id_contradiction_even_with_recomputed_hash(system,monkeypatch):
    _,inspected=stopped(system,monkeypatch)
    path=reconcile.INSPECTION_ROOT/inspected['inspection_id']/'inspection.json'
    data=json.loads(path.read_bytes());data['inspection_id']=str(uuid4());locks.atomic_json(path,data)
    inspected['inspection_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    result=apply(inspected)[1]
    assert result['status']=='BLOCKED' and 'Inspection identity mismatch' in ' '.join(result['reasons'])
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_collector_failure_has_precise_error_and_known_owners_but_no_fabricated_expiry(system):
    system[2].side_effect=RuntimeError('read-only collector synthetic failure')
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='BLOCKED'
    assert inspected['telemetry_collection']=='FAILED_NO_OBSERVATION'
    assert inspected['summary']['reservations']['v2.json']['owner_id']==system[0]
    assert inspected['summary']['process_checks']
    assert 'TELEMETRY_COLLECTION: RuntimeError' in ' '.join(inspected['reasons'])
    assert inspected['evidence_expired'] is None
    before=reconcile.inspect_environment.call_count
    query=reconcile.get_execution_reconciliation(inspected['inspection_id'])
    assert query['evidence_state']=='NOT_COLLECTED' and query['remaining_seconds'] is None
    assert reconcile.inspect_environment.call_count==before


def test_legacy_failed_collection_query_never_describes_absence_as_expired(system):
    path=legacy_reference(system);original=path.read_bytes()
    view=reconcile.get_execution_reconciliation(path.parent.name)
    assert view['evidence_expired'] is None and view['evidence_state']=='NOT_COLLECTED'
    assert view['telemetry_collection']=='NOT_COLLECTED' and view['remaining_seconds'] is None
    assert path.read_bytes()==original
    reconcile.inspect_environment.assert_not_called();system[2].assert_not_called()


def test_failed_environment_probe_exception_preserves_captured_ownership(system,monkeypatch):
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(side_effect=RuntimeError('metadata probe failed')))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='BLOCKED' and inspected['summary']['reservations']
    assert 'environment_identity_and_state' in inspected['unknown_fields']
    assert inspected['telemetry_collection']=='NOT_COLLECTED'
    assert 'ENVIRONMENT_METADATA: RuntimeError' in ' '.join(inspected['reasons'])
    system[2].assert_not_called()


def test_stopped_apply_holds_exclusion_during_metadata_revalidation(system,monkeypatch):
    _,inspected=stopped(system,monkeypatch)
    entered,finish=Event(),Event();backend=Mock(return_value=0)
    monkeypatch.setattr(lifecycle,'_backend',backend)
    def observe():
        entered.set();assert finish.wait(10);return environment(False)
    reconcile.inspect_environment.side_effect=observe
    with ThreadPoolExecutor() as pool:
        future=pool.submit(apply,inspected);assert entered.wait(10)
        try:
            with pytest.raises(locks.VehicleBusy):locks.reserve(str(uuid4()),'foreign flight','v1')
            assert lifecycle.run_lifecycle('restart')['status']=='BLOCKED'
            backend.assert_not_called()
        finally:finish.set()
        assert future.result()[1]['status']=='APPLIED'
    system[2].assert_not_called()
