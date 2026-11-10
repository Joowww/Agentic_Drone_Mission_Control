"""The 04/11 XRCE pin revision: sealed, derived only by pins, never a substitute for review. Host files only."""
import copy
import hashlib
import json
from pathlib import Path

from tools.rover_xrce_trace.passive_trial import selection_dry_run

ROOT = Path(__file__).resolve().parents[1]
REV = ROOT / 'evaluation/operations/rover_xrce_pin_revision_2026_11_04/4732a0bc-897e-4b55-bd7b-ea99b0b9f9b3'
OLD = ROOT / 'evaluation/operations/rover_clock_path_preparation_2026_10_31/54b7adc8-690b-4da1-98fa-eacdc78e9e0e'
PREP = OLD / 'preparation'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name):
    return json.loads((REV / name).read_text())


def test_revision_is_sealed():
    for line in (REV / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert sha(REV / name) == digest, name


def test_historical_preparation_is_untouched():
    predecessor = load('revision.json')['predecessor']
    assert sha(OLD / 'SHA256SUMS') == predecessor['seal_sha256']
    assert {p.name: sha(p) for p in sorted(PREP.iterdir())} == predecessor['files_sha256']


def test_only_the_listed_source_pins_differ_from_the_historical_reader():
    old, new, revision = json.loads((PREP / 'reader.prepared.json').read_text()), load('preparation/reader.prepared.json'), load('revision.json')
    assert {k: v for k, v in old.items() if k != 'source_hashes'} == {k: v for k, v in new.items() if k != 'source_hashes'}
    differing = {k for k in old['source_hashes'] if old['source_hashes'][k] != new['source_hashes'][k]}
    assert set(old['source_hashes']) == set(new['source_hashes'])
    listed = {c['path']: c for c in revision['changed_pins']}
    assert differing == set(listed) and len(listed) == 4
    for name, change in listed.items():
        assert change['historical_sha256'] == old['source_hashes'][name] and change['current_sha256'] == new['source_hashes'][name]
        assert sha(ROOT / change['historical_copy']) == change['historical_sha256'] and (REV / change['diff']).stat().st_size
        assert change['review'] == 'PENDING_HUMAN_REVIEW'
    assert revision['status'] == 'PREPARED_FOR_REVIEW_NOT_AUTHORIZED_NOT_APPLIED' and revision['authorization'] == 'NOT_PROVIDED'


def test_the_host_review_is_a_pending_template_not_a_review():
    template = load('host-source-review.pending.json')
    assert template['status'] == 'PENDING_HUMAN_REVIEW_NOT_A_REVIEW' and template['reviewer'] == '<<REVIEWER_REQUIRED>>'
    embedded = load('preparation/reader.prepared.json')['helper_review']['host_source_review']['source_changes']
    assert embedded['tools/simulation_lifecycle.py']['after'] == template['source_changes']['tools/simulation_lifecycle.py']['before']


def _prepared_reader_sources_match():
    reader = load('preparation/reader.prepared.json')
    return all(sha(ROOT / path) == digest for path, digest in reader['source_hashes'].items())


def test_revised_reader_still_blocks_selection_and_executes_nothing():
    result = selection_dry_run(ROOT, PREP / 'agent.prepared.json', REV / 'preparation/reader.prepared.json',
                               socket_helper_review=PREP / 'socket-helper-review.json')
    assert result['selection_files_valid'] is False and result['executed'] is False
    expected = 'Host lifecycle helper review' if _prepared_reader_sources_match() else 'source differs'
    assert expected in result['reason']


def test_accepting_the_host_review_would_make_selection_valid_only_while_sources_match(tmp_path):
    reader = load('preparation/reader.prepared.json')
    template = load('host-source-review.pending.json')
    what_if = copy.deepcopy(reader)
    for name, change in template['source_changes'].items():
        what_if['helper_review']['host_source_review']['source_changes'][name]['after'] = change['after']
    path = tmp_path / 'reader.json'
    path.write_text(json.dumps(what_if))
    result = selection_dry_run(ROOT, PREP / 'agent.prepared.json', path, socket_helper_review=PREP / 'socket-helper-review.json')
    assert result['executed'] is False and result['movement_authorized'] is False and result['status'] == 'BLOCKED'
    assert result['selection_files_valid'] is _prepared_reader_sources_match()
