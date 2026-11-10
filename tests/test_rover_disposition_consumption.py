"""Applied audit is immutable; replayed clock/input wiring is explicitly synthetic."""
import copy
import json
from pathlib import Path

import pytest

from tools.rover_xrce_trace import historical_disposition as d,present_recovery as recovery

ROOT=Path(__file__).resolve().parents[1]
APPLIED=ROOT/'evaluation/operations/rover_clock_execution_2026_10_31/58a4a593-4bbe-4ac1-a645-7ab593f381a8'
REPLAY=ROOT/'evaluation/operations/rover_disposition_consumer_offline_2026_10_31/d5bea33f-c6e9-4cd3-9e2c-70d446e09e0c/replay-inputs.json'

@pytest.fixture
def replay(monkeypatch):
    data=json.loads(REPLAY.read_bytes());audit=json.loads((APPLIED/'audit-after.json').read_bytes())
    records,current=copy.deepcopy(data['records']),copy.deepcopy(data['current'])
    # This tests consumption with the producer's exact reviewed reader version.
    # Production is deliberately NOT allowed to bypass version/hash changes.
    monkeypatch.setattr(recovery,'reader_hashes',lambda:copy.deepcopy(audit['scope']['reader_hashes']))
    domain=current['host_acquisition']['clock_context']
    monkeypatch.setattr(recovery,'host_clock_context',lambda:copy.deepcopy(domain))
    return records,current,audit,current['observed_monotonic']


def test_applied_audit_is_consumed_with_one_report_and_final_age_check(replay,monkeypatch):
    records,current,audit,start=replay;real=d.dry_run;calls=[]
    def once(*a,**kw):
        calls.append(1);return real(*a,**kw)
    monkeypatch.setattr(d,'dry_run',once)
    clock=iter([start+2.5,start+2.6]);monkeypatch.setattr(d.time,'monotonic',lambda:next(clock))
    value=d.diagnostic_precheck(records,current,audit)
    assert value['status']=='SATISFIED' and value['disposition_consumed']
    assert calls==[1] and all(value['disposition_checks'].values())
    assert not value['opening_authorized'] and not value['movement_authorized']
    assert audit==json.loads((APPLIED/'audit-after.json').read_bytes())


def test_expiration_during_consumption_still_blocks_and_is_published(replay,monkeypatch):
    records,current,audit,start=replay
    clock=iter([start+2.8,start+3.1]);monkeypatch.setattr(d.time,'monotonic',lambda:next(clock))
    value=d.diagnostic_precheck(records,current,audit)
    assert value['status']=='BLOCKED' and not value['disposition_consumed']
    assert value['conditions']['fresh_observation'] is False
    assert not value['disposition_checks']['current_assessment_valid']
    assert value['disposition_assessment_reason']=='Disposition consumption observation expired or clock context changed'


@pytest.mark.parametrize('bad',['hash','scope','owner','authorization','flags','applying','offline','schema','malformed_scope'])
def test_altered_or_inapplicable_audit_never_consumed(replay,bad):
    records,current,audit,start=replay
    if bad=='hash':audit['scope_sha256']='0'*64
    elif bad=='scope':audit['scope']['historical']['monitor']['capture_complete']=True
    elif bad=='owner':audit['owner_id']='12345678-1234-4234-8234-123456789abc'
    elif bad=='authorization':audit['authorization']='unrelated approval'
    elif bad=='flags':audit['opening_authorized']=True
    elif bad=='applying':audit['status']='APPLYING_UNCONFIRMED'
    elif bad=='offline':audit['offline_only']=True
    elif bad=='schema':audit['schema']='unknown/1'
    elif bad=='malformed_scope':audit['scope']=[]
    value=d.diagnostic_precheck(records,current,audit,now=start+2.6)
    assert value['status']=='BLOCKED' and not value['disposition_consumed']
    assert not value['opening_authorized'] and not value['movement_authorized']


@pytest.mark.parametrize('bad',['boot','started_at','net','host_boot','descriptor','resources_occupied','reservation','reader'])
def test_new_context_or_pending_resources_cannot_reuse_audit(replay,bad):
    records,current,audit,start=replay
    if bad=='boot':records['inventory']['boot_id']='new-boot'
    elif bad=='started_at':records['environment']['state']['StartedAt']='2026-10-31T14:00:00Z'
    elif bad=='net':current['resources']['context']['net_namespace']='net:[999]'
    elif bad=='host_boot':current['host_boot_id']='other'
    elif bad=='descriptor':records['target']['descriptor']['selection_sha256']='0'*64
    elif bad=='resources_occupied':current['resources'].update(status='OCCUPIED',reasons=['RELEVANT_LOCAL_ENDPOINT_OCCUPIED'])
    elif bad=='reservation':current['guards']={'pending.json':{}}
    elif bad=='reader':current['resources']['reader_hashes']={}
    value=d.diagnostic_precheck(records,current,audit,now=start+2.6)
    assert value['status']=='BLOCKED' and not value['disposition_consumed']


def test_clock_context_change_after_scope_checks_blocks(replay,monkeypatch):
    records,current,audit,start=replay;domain=copy.deepcopy(current['host_acquisition']['clock_context']);other=copy.deepcopy(domain);other['time_namespace']='time:[CHANGED]'
    domains=iter([domain,other]);monkeypatch.setattr(recovery,'host_clock_context',lambda:next(domains))
    value=d.diagnostic_precheck(records,current,audit,now=start+2.6)
    assert value['status']=='BLOCKED' and not value['conditions']['host_window_complete']
    assert not value['disposition_consumed']


def test_actual_reader_change_is_rejected_without_recovery_or_reapplication(replay,monkeypatch):
    records,current,audit,start=replay;hashes=recovery.reader_hashes();hashes['tools/rover_xrce_trace/historical_disposition.py']='f'*64
    monkeypatch.setattr(recovery,'reader_hashes',lambda:copy.deepcopy(hashes));current['resources']['reader_hashes']=copy.deepcopy(hashes)
    value=d.diagnostic_precheck(records,current,audit,now=start+2.6)
    assert value['status']=='BLOCKED' and not value['disposition_consumed']
    assert all(value['conditions'].values())
    assert value['disposition_checks']['scope_digest_matches'] is False
    assert value['disposition_checks']['scope_matches'] is False
    assert value['scope_changed_fields']==['reader_hashes']
