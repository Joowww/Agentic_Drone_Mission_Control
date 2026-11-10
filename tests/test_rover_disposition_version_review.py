"""Existing single-intent contract, real sealed audit copies, synthetic reads only."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from tools.rover_xrce_trace import historical_disposition as d,present_recovery as recovery

ROOT=Path(__file__).resolve().parents[1]
APPLIED=ROOT/'evaluation/operations/rover_clock_execution_2026_10_31/58a4a593-4bbe-4ac1-a645-7ab593f381a8'
PLAN=ROOT/'evaluation/operations/rover_consumer_transition_review_2026_10_31/e4b54d21-f416-4d50-932a-79ffbd7ffd13'
REPLAY=ROOT/'evaluation/operations/rover_disposition_consumer_offline_2026_10_31/d5bea33f-c6e9-4cd3-9e2c-70d446e09e0c/replay-inputs.json'

def read(p):return json.loads(p.read_bytes())

@pytest.fixture
def audit():return read(APPLIED/'audit-after.json')

@pytest.fixture
def engine(tmp_path,audit):
    # Production audit is never a target of these calls.
    folder=tmp_path/'synthetic-owner-store';shutil.copytree(APPLIED/'application-audit',folder)
    return d.OfflineDisposition(folder,owner=audit['owner_id'],clock=lambda:10)

def originals(engine):return {n:(engine.root/n).read_bytes() for n in ('intent.json','originals.json')}


def test_offline_candidate_changes_only_the_exact_reader_version(audit):
    new=read(PLAN/'candidate-scope.json');old=audit['scope']
    assert {k for k in old if old[k]!=new[k]}=={'reader_hashes'}
    # Immutable proposal predates the now explicitly authorized implementation.
    assert new['reader_hashes'][d.SUCCESSOR_PIN]=='1c6110f73b80c6f97bbd78d71bf4ebf768e282143b78d390b4f97790e7899d74'
    # Since then only revisable pins may differ (consumer and the profile catalogue).
    changed_current={k for k,v in recovery.reader_hashes().items() if new['reader_hashes'][k]!=v}
    # The exact PRESENT_RESOURCE_READER_SUCCESSOR_V1 was separately authorized and
    # pins only the reviewed current reader bytes; it is not a generic revisable pin.
    assert changed_current<=set(d.REVISABLE_PINS)|{d.RESOURCE_READER_PIN}
    if d.RESOURCE_READER_PIN in changed_current:
        assert new['reader_hashes'][d.RESOURCE_READER_PIN]==d.RESOURCE_READER_LEGACY_SHA256
        assert recovery.reader_hashes()[d.RESOURCE_READER_PIN]==d.RESOURCE_READER_CURRENT_SHA256
    assert {k for k in old['reader_hashes'] if old['reader_hashes'][k]!=new['reader_hashes'][k]}=={'tools/rover_xrce_trace/historical_disposition.py'}
    assert d.digest(new)==(PLAN/'candidate-scope.sha256').read_text().strip()!=audit['scope_sha256']
    operation=read(PLAN/'operation-for-review.json')
    assert not operation['fresh_current_review_performed'] and not operation['authorization_granted']
    assert operation['application_argv'] is None and not operation['opening_authorized']
    for row in operation['predecessor']['audit_files']:
        raw=Path(row['sealed_copy']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==row['sha256'] and len(raw)==row['size_bytes']


def test_different_scope_even_with_new_declaration_is_not_supported(engine,audit):
    before=originals(engine);new=read(PLAN/'candidate-scope.json');sha=d.digest(new);calls=[]
    with pytest.raises(ValueError,match='Prior incompatible or interrupted intent'):
        engine.apply({},lambda:calls.append(True),scope_sha256=sha,
            authorization=f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {audit['owner_id']} {sha}")
    assert calls==[] and originals(engine)==before and engine.query()==audit


def test_old_declaration_cannot_authorize_the_new_hash(engine,audit):
    before=originals(engine);sha=d.digest(read(PLAN/'candidate-scope.json'))
    with pytest.raises(ValueError,match='Exact scope authorization required'):
        engine.apply({},lambda:pytest.fail('No current read authorized by old declaration'),scope_sha256=sha,authorization=audit['authorization'])
    assert originals(engine)==before


def test_old_repeat_is_only_query_not_a_version_transition(engine,audit):
    # Explicitly synthetic /tmp fixture, never submit the production old scope.
    before=originals(engine)
    result=engine.apply({},lambda:pytest.fail('Idempotent query must not claim revalidation'),
        scope_sha256=audit['scope_sha256'],authorization=audit['authorization'])
    assert result==audit and result['scope']['reader_hashes']!=recovery.reader_hashes()
    assert originals(engine)==before


@pytest.mark.parametrize('bad',['scope','authorization','owner','interrupted'])
def test_corrupt_other_owner_or_interrupted_predecessor_cannot_transition(engine,audit,bad):
    if bad=='interrupted':(engine.root/'persistence_failed').write_text('SYNTHETIC interruption')
    else:
        value=read(engine.root/'intent.json')
        if bad=='scope':value['scope']['reader_hashes']={}
        elif bad=='authorization':value['authorization']='unrelated'
        else:value['owner_id']='12345678-1234-4234-8234-123456789abc'
        (engine.root/'intent.json').write_text(json.dumps(value))
    before=originals(engine);sha=d.digest(read(PLAN/'candidate-scope.json'))
    assert engine.query()['status']=='APPLYING_UNCONFIRMED'
    with pytest.raises(ValueError,match='Prior incompatible or interrupted intent'):
        engine.apply({},lambda:pytest.fail('No fallback read or apply'),scope_sha256=sha,
            authorization=f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {audit['owner_id']} {sha}")
    assert originals(engine)==before


def test_unsupported_sidecar_does_not_override_applied_audit(engine,audit):
    (engine.root/'version-transition.json').write_text(json.dumps({'scope':read(PLAN/'candidate-scope.json'),'authorized':True}))
    assert engine.query()==audit


def test_projection_matches_existing_review_only_with_explicit_synthetic_observations(audit,monkeypatch):
    value=read(REPLAY);records,current=copy.deepcopy(value['records']),copy.deepcopy(value['current'])
    current['resources']['reader_hashes']=recovery.reader_hashes()
    monkeypatch.setattr(recovery,'host_clock_context',lambda:copy.deepcopy(current['host_acquisition']['clock_context']))
    now=current['observed_monotonic']+2.7
    report=d.dry_run(records,current,now=now)
    assert report['status']=='DRY_RUN_ELIGIBLE',report
    prior=read(PLAN/'candidate-scope.json')
    assert {k for k in report['scope'] if report['scope'][k]!=prior[k]}=={'reader_hashes'}
    decision=d.assess_disposition(records,current,audit,now=now)
    assert not decision['historical_pointer_resolved']
    assert decision['scope_changed_fields']==['reader_hashes']
    assert not decision['checks']['authorization_matches']
