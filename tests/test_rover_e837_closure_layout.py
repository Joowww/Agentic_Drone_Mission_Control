"""Original e837 records and negative mutations in isolated archive copies."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tools.rover_xrce_trace import session_precheck as s

HISTORY=Path(__file__).resolve().parents[1]/'simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f'


def test_real_layout_uses_complete_later_read_without_rewriting_stale_stdout():
    ref=s.closure_archive_reference(HISTORY)
    assert ref['layout']==s.PASSIVE_SESSION_LAYOUT
    with pytest.raises(ValueError,match='freshness unverified'):
        s.verified_closure_archive(ref)
    assert json.loads((HISTORY/'passive-session/post-precheck.stdout').read_text())['conditions']['fresh_observation'] is False
    # The failed partial serialization is irrelevant, not parsed or repaired.
    with pytest.raises(json.JSONDecodeError):json.loads((HISTORY/'post-current-records.json').read_text())
    assert hashlib.sha256((HISTORY/'manifest.json').read_bytes()).hexdigest()==s.PASSIVE_SESSION_MANIFEST


@pytest.fixture
def archive(tmp_path):
    root=tmp_path/'archive';shutil.copytree(HISTORY,root)
    return root,s.closure_archive_reference(root)


def reseal(root,ref):
    manifest=json.loads((root/'manifest.json').read_text())
    for item in manifest['files']:
        p=root/item['path']
        item.update(size_bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),mode=oct(p.stat().st_mode&0o777))
    raw=(json.dumps(manifest,indent=2)+'\n').encode();(root/'manifest.json').write_bytes(raw)
    ref['manifest_sha256']=hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('case',['altered','wrong_path','unlisted','missing','other_session','inventory_missing',
    'failed_reader','unknown_reader','stale','before_stop','wrong_boot','other_pointer','embedded_mismatch','prior_other_session'])
def test_fail_closed_for_bad_originals_and_semantics(archive,case):
    root,ref=archive
    name='post-current-records-serializable.json'
    if case=='altered':
        (root/name).write_text('{}')
        with pytest.raises(ValueError,match='original changed'):s.verified_closure_archive(ref)
        return
    if case in {'wrong_path','unlisted','missing'}:
        manifest=json.loads((root/'manifest.json').read_text())
        entry=next(v for v in manifest['files'] if v['path']==name)
        if case=='wrong_path':
            # Same suffix at a different path must never be discovered.
            new=root/'unreviewed'/name;new.parent.mkdir();(root/name).rename(new);entry['path']='unreviewed/'+name
        else:
            manifest['files'].remove(entry)
            if case=='missing':(root/name).unlink()
        raw=json.dumps(manifest).encode();(root/'manifest.json').write_bytes(raw);ref['manifest_sha256']=hashlib.sha256(raw).hexdigest()
        with pytest.raises(ValueError,match='absent from manifest'):s.verified_closure_archive(ref)
        return
    records=json.loads((root/name).read_text());context=json.loads((root/'post-current-context.json').read_text())
    if case=='other_session':records['target']['closed_by']='11111111-1111-4111-8111-111111111111'
    elif case=='inventory_missing':records['inventory'].pop('agents')
    elif case=='failed_reader':context['inventory_return_code']=1
    elif case=='unknown_reader':context['inventory_source_sha256']='0'*64
    elif case=='stale':context['started_at_utc']='2026-10-26T22:05:00+00:00'
    elif case=='before_stop':context['started_at_utc']='2026-10-26T21:59:00+00:00'
    elif case=='wrong_boot':records['inventory']['boot_id']='different-boot'
    elif case=='other_pointer':records['inventory']['state_files'][s.POINTER]='{}'
    elif case=='embedded_mismatch':records['inventory']['files'][records['target']['descriptor']['prefix']+'/launch.json']='{}'
    elif case=='prior_other_session':
        p=root/'passive-session/post-precheck.stdout';v=json.loads(p.read_text());v['historical_classification']['lifecycle_id']='other';p.write_text(json.dumps(v))
    (root/name).write_text(json.dumps(records));(root/'post-current-context.json').write_text(json.dumps(context));reseal(root,ref)
    expected = {
        'other_session':'another session: target',
        'inventory_missing':'Independent post-close processes',
        'failed_reader':'inventory read failed/incomplete',
        'unknown_reader':'reader provenance',
        'stale':'chronology/freshness', 'before_stop':'chronology/freshness',
        'wrong_boot':'execution context mismatch',
        'other_pointer':'Retained record flags differ',
        'embedded_mismatch':'retained file mismatch',
        'prior_other_session':'Post-precheck associated with another session',
    }
    with pytest.raises(ValueError,match=expected[case]):s.verified_closure_archive(ref)


def test_unknown_layout_is_not_accepted(archive):
    _,ref=archive;ref['layout']='discover-by-suffix'
    with pytest.raises(ValueError,match='Unknown closure archive layout'):s.verified_closure_archive(ref)


def test_synthetic_fresh_verdict_exercises_remaining_layout_contract(archive):
    # Synthetic positive fixture only: never add a verdict to historical originals.
    root,ref=archive;p=root/'passive-session/post-precheck.stdout'
    v=json.loads(p.read_text());v['conditions']['fresh_observation']=True;p.write_text(json.dumps(v));reseal(root,ref)
    proof=s.verified_closure_archive(ref)
    assert proof['target']['descriptor']['lifecycle_id']=='e837942d-61b0-428e-8505-ef6ddca38037'
    assert proof['monitor']['capture_complete'] is False
