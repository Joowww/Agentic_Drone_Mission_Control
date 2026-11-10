from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import uuid

import pytest

from tools import rover_passive_scope as passive

NOW = datetime(2026, 11, 6, 20, 30, tzinfo=timezone.utc)
ENV = {'persistent_identity': {'engine_id':'engine-1','container_id':'a'*64,'image_id':'sha256:'+'b'*64,
       'name':'/tfg-ardupilot-gazebo','created_at':'2026-10-02T07:28:34Z'},
       'container_started_at':'2026-11-03T09:44:02Z','container_boot_id':'container-boot-1'}

def precheck(at=NOW-timedelta(seconds=2)):
    return {'status':'SATISFIED','precheck_satisfied':True,
      'conditions':{key:True for key in passive.REQUIRED_CONDITIONS},
      'opening_authorized':False,'movement_authorized':False,'source_association_verified':False,
      'audit_state':'DISPOSED_DIAGNOSTICALLY_INCOMPLETE','current_environment_execution':deepcopy(ENV),
      'sources':[{'source':'synthetic current precheck','read_at_utc':at.isoformat()}]}

def prepared():
    p=precheck()
    scope=passive.build_scope(p,host_boot_id='host-boot-1',operator_id='uid:1000',now=NOW,
                              session_id='90a1a4d0-5137-4c84-a1d2-c536b47c7a19')
    digest=passive.scope_sha256(scope)
    auth=passive.authorization_text(scope['operator_id'],digest)
    return p,scope,digest,auth

def test_passive_scope_is_canonical_versioned_and_passive_only():
    p,s,d,a=prepared()
    assert json.loads(passive.canonical_json(s))==s
    assert d==hashlib.sha256(passive.canonical_json(s).encode()).hexdigest()
    assert s['allowed_operations']==list(passive.ALLOWED_OPERATIONS)
    assert s['prohibited_operations']==list(passive.PROHIBITED_OPERATIONS)
    assert s['worker']['observations']==100 and s['motion_binding_protocol']=='/2'
    assert passive.validate_scope(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
                                  host_boot_id='host-boot-1',now=NOW)==[]

def test_scope_rejects_altered_hash_authorization_unknown_fields_and_movement():
    p,s,d,a=prepared()
    bad=deepcopy(s);bad['prohibited_operations'].remove('ARM')
    assert 'SCOPE_HASH_MISMATCH' in passive.validate_scope(bad,supplied_sha256=d,authorization=a,
        fresh_precheck=p,host_boot_id='host-boot-1',now=NOW)
    bad=deepcopy(s);bad['allowed_operations'].append('ARM')
    assert 'ALLOWED_OPERATIONS_MISMATCH' in passive.validate_scope(bad,
        supplied_sha256=passive.scope_sha256(bad),authorization=a,fresh_precheck=p,
        host_boot_id='host-boot-1',now=NOW)
    bad=deepcopy(s);bad['operator_id']='another-operator'
    assert 'EXACT_OPERATOR_DECLARATION_REQUIRED' in passive.validate_scope(bad,
        supplied_sha256=passive.scope_sha256(bad),authorization=a,fresh_precheck=p,
        host_boot_id='host-boot-1',now=NOW)
    bad=deepcopy(s);bad['unexpected']=True
    assert 'SCOPE_FIELDS_UNKNOWN_OR_MISSING' in passive.validate_scope(bad,
        supplied_sha256=passive.scope_sha256(bad),authorization=a,fresh_precheck=p,
        host_boot_id='host-boot-1',now=NOW)

def test_scope_rejects_stale_blocked_or_changed_precheck_identity():
    _,s,d,a=prepared()
    stale=precheck(NOW-timedelta(seconds=passive.MAX_SCOPE_AGE_S+1))
    assert 'PRECHECK_STALE_OR_FUTURE' in passive.validate_scope(s,supplied_sha256=d,authorization=a,
        fresh_precheck=stale,host_boot_id='host-boot-1',now=NOW)
    blocked=precheck();blocked['status']='BLOCKED';blocked['precheck_satisfied']=False
    assert 'PRECHECK_NOT_SATISFIED' in passive.validate_scope(s,supplied_sha256=d,authorization=a,
        fresh_precheck=blocked,host_boot_id='host-boot-1',now=NOW)
    changed=precheck();changed['current_environment_execution']['container_boot_id']='other'
    assert 'ENVIRONMENT_EXECUTION_CHANGED' in passive.validate_scope(s,supplied_sha256=d,authorization=a,
        fresh_precheck=changed,host_boot_id='host-boot-1',now=NOW)
    assert 'HOST_BOOT_MISMATCH' in passive.validate_scope(s,supplied_sha256=d,authorization=a,
        fresh_precheck=precheck(),host_boot_id='other-host',now=NOW)

def test_consume_once_is_atomic_and_replay_is_rejected(tmp_path):
    p,s,d,a=prepared();root=tmp_path/'claims'
    receipt=passive.consume_once(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
        host_boot_id='host-boot-1',claim_root=root,lifecycle_owner=s['session_id'],now=NOW)
    assert receipt['state']=='CONSUMED' and receipt['movement_authorized'] is False
    with pytest.raises(passive.PassiveScopeError,match='ALREADY_CONSUMED'):
        passive.consume_once(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
            host_boot_id='host-boot-1',claim_root=root,lifecycle_owner=s['session_id'],now=NOW)

def test_concurrent_claim_has_exactly_one_winner(tmp_path):
    p,s,d,a=prepared();root=tmp_path/'claims'
    def claim():
        try:
            passive.consume_once(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
                host_boot_id='host-boot-1',claim_root=root,lifecycle_owner=s['session_id'],now=NOW)
            return 'CONSUMED'
        except passive.PassiveScopeError:
            return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(lambda _:claim(),range(2)))
    assert sorted(outcomes)==['BLOCKED','CONSUMED']
    assert len(list(root.glob('*.json')))==1

def test_consume_persistence_failure_leaves_replay_blocking_claim(tmp_path,monkeypatch):
    import os
    p,s,d,a=prepared();root=tmp_path/'claims';original=os.fsync
    def fail_once(fd):
        monkeypatch.setattr(os,'fsync',original)
        raise OSError('synthetic fsync failure')
    monkeypatch.setattr(os,'fsync',fail_once)
    with pytest.raises(OSError,match='fsync'):
        passive.consume_once(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
            host_boot_id='host-boot-1',claim_root=root,lifecycle_owner=s['session_id'],now=NOW)
    monkeypatch.setattr(os,'fsync',original)
    assert len(list(root.glob('*.json')))==1
    with pytest.raises(passive.PassiveScopeError,match='ALREADY_CONSUMED'):
        passive.consume_once(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
            host_boot_id='host-boot-1',claim_root=root,lifecycle_owner=s['session_id'],now=NOW)

def test_expired_scope_and_lifecycle_owner_mismatch_block(tmp_path):
    p,s,d,a=prepared()
    assert 'SCOPE_EXPIRED_OR_STALE' in passive.validate_scope(s,supplied_sha256=d,authorization=a,
        fresh_precheck=p,host_boot_id='host-boot-1',now=NOW+timedelta(seconds=61))
    with pytest.raises(passive.PassiveScopeError,match='LIFECYCLE_OWNER'):
        passive.consume_once(s,supplied_sha256=d,authorization=a,fresh_precheck=p,
            host_boot_id='host-boot-1',claim_root=tmp_path/'claims',lifecycle_owner=str(uuid.uuid4()),now=NOW)


def test_lifecycle_deadline_uses_host_monotonic_and_rejects_boot_change():
    from tools.rover_passive_scope import PassiveScopeError, remaining_session_seconds

    state={'state':'STARTED','host_boot_id':'boot-a','started_host_monotonic_s':50.0,
           'deadline_host_monotonic_s':350.0}
    assert remaining_session_seconds(state,current_host_boot_id='boot-a',now_monotonic=125.0)==225.0
    assert remaining_session_seconds(state,current_host_boot_id='boot-a',now_monotonic=351.0)==0.0
    with pytest.raises(PassiveScopeError,match='BOOT_CHANGED'):
        remaining_session_seconds(state,current_host_boot_id='boot-b',now_monotonic=125.0)
