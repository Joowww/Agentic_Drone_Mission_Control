from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import uuid

import pytest

from tools import simulation_lifecycle as life
from tools import rover_passive_scope as passive

ENV={'persistent_identity':{'engine_id':'engine-1','container_id':'a'*64,'image_id':'sha256:'+'b'*64,
     'name':'/tfg-ardupilot-gazebo','created_at':'2026-10-02T07:28:34Z'},
     'container_started_at':'2026-11-03T09:44:02Z','container_boot_id':'container-boot-1'}

def precheck(now=None):
    now=now or datetime.now(timezone.utc)
    return {'status':'SATISFIED','precheck_satisfied':True,
      'conditions':{key:True for key in passive.REQUIRED_CONDITIONS},
      'opening_authorized':False,'movement_authorized':False,'source_association_verified':False,
      'audit_state':'DISPOSED_DIAGNOSTICALLY_INCOMPLETE','current_environment_execution':ENV,
      'sources':[{'source':'fresh offline precheck double','read_at_utc':(now-timedelta(seconds=1)).isoformat()}]}

def scope_auth(now=None):
    now=now or datetime.now(timezone.utc);p=precheck(now)
    s=passive.build_scope(p,host_boot_id='host-boot-1',operator_id='uid:1000',now=now,
      session_id=str(uuid.uuid4()))
    d=passive.scope_sha256(s)
    return p,s,d,passive.authorization_text(s['operator_id'],d)

def setup(monkeypatch,tmp_path,*,backend_result=0,inventory=None,post_precheck=None):
    lockroot=tmp_path/'locks';sessionroot=tmp_path/'sessions';claims=lockroot/'passive_scope_claims'
    monkeypatch.setattr(life.locks,'LOCK_ROOT',lockroot)
    monkeypatch.setattr(life,'PASSIVE_SESSION_ROOT',sessionroot)
    monkeypatch.setattr(life,'PASSIVE_SCOPE_CLAIM_ROOT',claims)
    monkeypatch.setattr(life,'PASSIVE_SCOPE_POLICY_ENABLED',True)
    monkeypatch.setattr(life.locks,'process_identity',lambda:{'pid':os_getpid(),'start_ticks':1,'boot_id':'host-boot-1'})
    monkeypatch.setattr(life,'assert_environment_execution',lambda expected:None)
    fresh=precheck()
    monkeypatch.setattr(life,'_fresh_passive_precheck',lambda target:fresh if post_precheck is None else post_precheck)
    calls=[]
    def backend(action,gui,descriptor,process,log_path):
        calls.append(action)
        return backend_result
    monkeypatch.setattr(life,'_backend',backend)
    if inventory is None:inventory={'boot_id':'container-boot-1','owned':[],'ambiguous':[],'agents':[],'state_files':{},'files':{}}
    monkeypatch.setattr(life,'read_container_inventory',lambda container:inventory)
    return lockroot,sessionroot,claims,calls

def os_getpid():
    import os
    return os.getpid()

def start(ctx, auth):
    p,s,d,_=ctx
    return life.run_lifecycle('start',gui=False,profile='rover_only',passive_scope=s,
      passive_scope_sha256=d,passive_authorization=auth)

def test_rover_only_start_is_closed_by_default_and_requires_scope(monkeypatch,tmp_path):
    lockroot=tmp_path/'locks';monkeypatch.setattr(life.locks,'LOCK_ROOT',lockroot)
    monkeypatch.setattr(life,'PASSIVE_SCOPE_POLICY_ENABLED',False)
    result=life.run_lifecycle('start',profile='rover_only')
    assert result['status']=='BLOCKED' and 'promotion gate is disabled' in result['message']
    assert not lockroot.exists()

def test_positive_simulated_start_and_same_session_stop_consume_exact_scope(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc);p,s,d,a=scope_auth(now);ctx=(p,s,d,a)
    lockroot,sessions,claims,calls=setup(monkeypatch,tmp_path)
    opened=start(ctx,a)
    assert opened['status']=='SUCCESS' and opened['operation']['movement_authorized'] is False
    assert opened['operation']['owner_id']==s['session_id']
    assert opened['operation']['passive_scope_sha256']==d
    assert calls==['start'] and (claims/(d+'.json')).is_file()
    state=json.loads((sessions/(s['session_id']+'.json')).read_text())
    assert state['state']=='STARTED' and state['scope_sha256']==d
    duplicate=start(ctx,a)
    assert duplicate['status']=='BLOCKED' and calls==['start']
    stopped=life.run_lifecycle('stop',gui=False,profile='rover_only',passive_session_owner=s['session_id'])
    assert stopped['status']=='SUCCESS' and calls==['start','stop']
    assert stopped['operation']['final_inventory']['status']=='COMPLETE'
    assert stopped['operation']['post_stop_precheck']['precheck_satisfied'] is True
    final=json.loads((sessions/(s['session_id']+'.json')).read_text())
    assert final['state']=='CLOSED_INCOMPLETE' and final['movement_authorized'] is False
    assert final['phase_verification']['complete'] is False
    assert not (lockroot/'lifecycle.json').exists()

def test_scope_mutation_stale_precheck_and_wrong_stop_owner_are_blocked(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc);p,s,d,a=scope_auth(now)
    lockroot,sessions,claims,calls=setup(monkeypatch,tmp_path)
    mutated=json.loads(json.dumps(s));mutated['allowed_operations'].append('ARM')
    bad=life.run_lifecycle('start',gui=False,profile='rover_only',passive_scope=mutated,
      passive_scope_sha256=passive.scope_sha256(mutated),passive_authorization=a)
    assert bad['status']=='BLOCKED' and not calls and not claims.exists()
    stale=precheck(now-timedelta(seconds=passive.MAX_SCOPE_AGE_S+5))
    monkeypatch.setattr(life,'_fresh_passive_precheck',lambda target:stale)
    expired=life.run_lifecycle('start',gui=False,profile='rover_only',passive_scope=s,
      passive_scope_sha256=d,passive_authorization=a)
    assert expired['status']=='BLOCKED' and not calls
    monkeypatch.setattr(life,'_fresh_passive_precheck',lambda target:p)
    assert start((p,s,d,a),a)['status']=='SUCCESS'
    wrong=life.run_lifecycle('stop',gui=False,profile='rover_only',passive_session_owner=str(uuid.uuid4()))
    assert wrong['status']=='BLOCKED' and calls==['start']

def test_uncertain_start_is_retained_and_cannot_be_replayed_or_stopped(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc);p,s,d,a=scope_auth(now)
    lockroot,sessions,claims,calls=setup(monkeypatch,tmp_path,backend_result=2)
    result=start((p,s,d,a),a)
    assert result['status']=='UNCONFIRMED' and calls==['start']
    state=json.loads((sessions/(s['session_id']+'.json')).read_text())
    assert state['state']=='UNCONFIRMED'
    replay=start((p,s,d,a),a)
    assert replay['status']=='BLOCKED' and calls==['start']
    stopped=life.run_lifecycle('stop',gui=False,profile='rover_only',passive_session_owner=s['session_id'])
    assert stopped['status']=='BLOCKED' and calls==['start']

def test_incomplete_final_inventory_keeps_stop_unconfirmed(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc);p,s,d,a=scope_auth(now)
    bad_inventory={'boot_id':'container-boot-1','owned':[{'pid':9}], 'ambiguous':[],'agents':[],'state_files':{},'files':{}}
    lockroot,sessions,claims,calls=setup(monkeypatch,tmp_path,inventory=bad_inventory)
    assert start((p,s,d,a),a)['status']=='SUCCESS'
    result=life.run_lifecycle('stop',gui=False,profile='rover_only',passive_session_owner=s['session_id'])
    assert result['status']=='UNCONFIRMED' and calls==['start','stop']
    state=json.loads((sessions/(s['session_id']+'.json')).read_text())
    assert state['state']=='UNCONFIRMED' and (lockroot/'lifecycle.json').exists()

def test_concurrent_duplicate_start_has_one_backend_invocation(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc);p,s,d,a=scope_auth(now)
    lockroot,sessions,claims,calls=setup(monkeypatch,tmp_path)
    barrier=threading.Barrier(2)
    def attempt():
        barrier.wait()
        return start((p,s,d,a),a)['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==['BLOCKED','SUCCESS'] and calls==['start']
