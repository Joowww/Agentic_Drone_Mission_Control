"""Legacy association is conditional administrative evidence, not historical identity proof."""
import json
from unittest.mock import Mock

import pytest

from tests.test_execution_reconciliation import system, environment
from tests.test_stopped_environment_reconciliation import legacy_reference, stopped, apply, confirmation
from tools import execution_reconciliation as reconcile
from tools import vehicle_execution_lock as locks


def test_post_failure_hint_alone_cannot_authorize_administrative_closure(system,monkeypatch):
    _,inspected=stopped(system,monkeypatch)
    assert inspected['application_eligible'] is False
    assert inspected['binding_review']['status']=='AWAITING_OPERATOR_CONTINUITY_REVIEW'
    assert inspected['binding_review']['original_execution_environment_bound'] is False
    assert apply(inspected,legacy_environment_confirmation=None)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()
    system[2].assert_not_called()


def test_new_container_after_original_execution_rejects_postmortem_matching_id_and_stopped_state(system,monkeypatch):
    legacy_reference(system)
    value=environment(False)
    value.update(created_at='2026-10-19T15:00:00Z')
    value['state']['StartedAt']='2026-10-19T16:00:00Z'
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=value))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='BLOCKED'
    assert 'container_created_before_activity' in ' '.join(inspected['reasons'])
    assert apply(inspected)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


@pytest.mark.parametrize('change',['no_times','reference_before_activity','exit_before_activity'])
def test_missing_or_contradictory_chronology_is_not_repaired_by_a_declaration(system,monkeypatch,change):
    source=legacy_reference(system);env=environment(False)
    if change=='no_times':
        for name in ('job.json','report.json'):
            path=system[1]/name;value=json.loads(path.read_bytes())
            for field in ('started_at','execution_started_at','execution_finished_at','finished_at'):value.pop(field,None)
            locks.atomic_json(path,value)
    elif change=='reference_before_activity':
        value=json.loads(source.read_bytes());value['created_at']='2026-10-17T18:00:00Z';locks.atomic_json(source,value)
    else:env['state']['FinishedAt']='2026-10-17T18:00:00Z'
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=env))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['status']=='BLOCKED' and inspected['binding_review']['reasons']
    assert apply(inspected)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


@pytest.mark.parametrize('change',['different_engine','different_container','continuity_unknown','clock_unknown','blank_basis','missing_field','invented_source'])
def test_review_must_match_exact_identity_and_explicit_supported_declarations(system,monkeypatch,change):
    _,inspected=stopped(system,monkeypatch);claim=confirmation(inspected)
    if change=='different_engine':claim['engine_id']='another-engine'
    elif change=='different_container':claim['container_id']='f'*64
    elif change=='continuity_unknown':claim['continuous_project_environment']=False
    elif change=='clock_unknown':claim['wall_clock_comparison_supported']=False
    elif change=='blank_basis':claim['statement']=' '
    elif change=='missing_field':claim.pop('continuous_project_environment')
    else:claim['source']='BOOT_ID_PROVES_DOCKER_IDENTITY'
    assert apply(inspected,legacy_environment_confirmation=claim)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()


def test_host_boot_change_is_not_docker_engine_change_or_execution_binding(system,monkeypatch):
    monkeypatch.setattr(reconcile,'boot_id',lambda:'different-worker-host-boot')
    _,inspected=stopped(system,monkeypatch)
    assert inspected['boot_id']=='different-worker-host-boot'
    assert inspected['environment']['engine_id']=='synthetic-engine'
    assert inspected['identity_reference']['historical_engine_identity_known'] is False
    assert inspected['binding_review']['original_execution_environment_bound'] is False
    assert inspected['status']=='AWAITING_LEGACY_ENVIRONMENT_REVIEW'
    assert inspected['application_eligible'] is False


def test_full_posthoc_engine_reference_does_not_masquerade_as_original_execution_binding(system,monkeypatch):
    reconcile.inspect_execution_reconciliation(system[0])  # active postmortem audit
    monkeypatch.setattr(reconcile,'inspect_environment',Mock(return_value=environment(False)))
    inspected=reconcile.inspect_execution_reconciliation(system[0])
    assert inspected['identity_reference']['historical_engine_identity_known'] is True  # known at prior audit only
    assert inspected['identity_reference']['original_execution_environment_bound'] is False
    assert apply(inspected,legacy_environment_confirmation=None)[1]['status']=='BLOCKED'
    args,result=apply(inspected);assert result['status']=='APPLIED'
    saved=json.loads((reconcile.INSPECTION_ROOT/inspected['inspection_id']/'application.json').read_bytes())
    assert saved['environment_association']['historical_engine_identity_reconstructed'] is False
    assert saved['environment_association']['source']=='UNVERIFIED_OPERATOR_DECLARATION_VIA_AGENT'
    audit=reconcile.get_execution_reconciliation(inspected['inspection_id'])
    assert audit['application']['environment_association']['original_execution_environment_bound'] is False
    assert audit['application']['environment_association']['confirmation']['engine_id']=='synthetic-engine'


def test_error_report_after_container_exit_is_not_proof_of_a_later_flight(system,monkeypatch):
    p=system[1]/'report.json';raw=json.loads(p.read_bytes())
    raw['execution_finished_at']='2026-10-19T17:00:30Z';locks.atomic_json(p,raw)
    _,inspected=stopped(system,monkeypatch)
    assert inspected['binding_review']['chronology']['stop_covers_recorded_finish'] is False
    # Failure/timeout reporting can end after environment termination. Never infer "no flight".
    assert inspected['status']=='AWAITING_LEGACY_ENVIRONMENT_REVIEW'
    assert apply(inspected)[1]['status']=='APPLIED'
    assert json.loads(p.read_bytes())['status']=='ERROR'


def test_expired_legacy_audit_cannot_be_applied_even_with_new_operator_review(system,monkeypatch):
    _,inspected=stopped(system,monkeypatch)
    now=reconcile.time.monotonic();monkeypatch.setattr(reconcile.time,'monotonic',lambda:now+121)
    view=reconcile.get_execution_reconciliation(inspected['inspection_id'])
    assert view['evidence_state']=='EXPIRED' and view['application_eligible'] is False
    assert view['application'] is None
    assert apply(inspected)[1]['status']=='BLOCKED'
    assert (locks.LOCK_ROOT/'v2.json').exists()
