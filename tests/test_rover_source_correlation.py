"""Offline mutations of copies; original trial evidence is never rewritten."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tools.rover_identity_inventory import correlate_capture
from tools.rover_passive_journal import main

RUN = '40e8c751-6d70-4280-b94b-b1512e1e2802'
SOURCE = Path(__file__).resolve().parents[1] / 'simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22' / RUN


@pytest.fixture
def archive(tmp_path):
    # Deliberately use the actual on-disk format, including original hash chains.
    target = tmp_path / RUN
    shutil.copytree(SOURCE, target)
    return target


def read(root, name):
    return json.loads((root / name).read_bytes())


def write(root, name, value):
    (root / name).write_text(json.dumps(value))


def rehash(root):
    manifest = read(root, 'manifest.json')
    for entry in manifest['files']:
        data = (root / entry['path']).read_bytes()
        entry.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    write(root, 'manifest.json', manifest)


def test_actual_archive_partial_chain_no_numeric_inference(archive):
    report = correlate_capture(archive)
    assert report['evidence_valid'], report['errors']
    assert report['verified_manifest_entries'] == 170
    assert report['status'] == 'BLOCKED'
    assert report['movement_authorized'] is False
    assert report['matrix'][1]['state'] == 'MISSING'
    assert report['executed_binary']['sha256'].startswith('43d5b5eb')
    assert report['later_unexecuted_binary']['sha256'].startswith('94c0a9dd')
    assert report['inventory_replay']['status'] == 'BLOCKED'
    assert report['first_missing_link'] == 'DDS publisher endpoint -> XRCE client/session'


def test_corrupt_bytes_rejected(archive):
    with (archive / 'capture/journal.jsonl').open('ab') as stream:
        stream.write(b'\n')
    report = correlate_capture(archive)
    assert not report['evidence_valid']
    assert 'Manifest integrity mismatch' in report['errors'][0]
    assert report['matrix'] == []


@pytest.mark.parametrize('mutation', ['lifecycle', 'environment', 'process', 'sysid', 'binary', 'run'])
def test_rehashed_cross_session_and_identity_contradictions(archive, mutation):
    if mutation == 'lifecycle':
        value = read(archive, 'lifecycle_start_result.json')
        value['operation']['owner_id'] = 'another-session'
        write(archive, 'lifecycle_start_result.json', value)
    elif mutation == 'environment':
        value = read(archive, 'environment_before_capture.json')
        value['container_id'] = 'another-container'
        write(archive, 'environment_before_capture.json', value)
    elif mutation == 'process':
        value = read(archive, 'container_processes_before_close.stdout')
        value['boot_id'] = 'another-boot'
        write(archive, 'container_processes_before_close.stdout', value)
    elif mutation == 'sysid':
        value = read(archive, 'effective_readonly_report.json')
        process = next(p for p in value['processes'] if p['argv'][0] == 'ardurover')
        process['argv'][process['argv'].index('--sysid') + 1] = '2'
        write(archive, 'effective_readonly_report.json', value)
        write(archive, 'effective_readonly.stdout', value)
        snapshot = read(archive, 'container_processes_before_close.stdout')
        next(p for p in snapshot['relevant'] if p['pid'] == process['pid'])['argv'] = process['argv']
        write(archive, 'container_processes_before_close.stdout', snapshot)
    elif mutation == 'binary':
        write(archive, 'binary.json', read(archive, 'post_trial_cap_build/binary.json'))
    else:
        value = read(archive, 'collector_result.json')
        value['directory'] = '/tmp/different-session'
        write(archive, 'collector_result.json', value)
    rehash(archive)
    report = correlate_capture(archive)
    assert not report['evidence_valid'], mutation
    assert report['matrix'] == []
    assert report['status'] == 'BLOCKED'


def test_semantic_bridge_contradiction_even_with_consistent_hashes(archive):
    value = read(archive, 'effective_readonly_report.json')
    f = next(f for f in value['files'].values() if '/model/rover1/odometry' in f.get('text', '') and f['path'].endswith('.yaml'))
    old_hash = f['sha256']
    f['text'] = f['text'].replace('/model/rover1/odometry', '/model/other/odometry')
    f['sha256'] = hashlib.sha256(f['text'].encode()).hexdigest()
    f['size'] = len(f['text'].encode())
    copies = read(archive, 'effective_copies.json')
    copy = next(c for c in copies if c['source'] == f['path'] and c['sha256'] == old_hash)
    (archive / copy['copy']).write_text(f['text'])
    copy['sha256'] = f['sha256']
    copy['size'] = len(f['text'].encode())
    write(archive, 'effective_copies.json', copies)
    write(archive, 'effective_readonly_report.json', value)
    write(archive, 'effective_readonly.stdout', value)
    rehash(archive)
    report = correlate_capture(archive)
    assert not report['evidence_valid']
    assert 'Bridge odometry' in report['errors'][0]


def test_graph_candidate_cannot_replace_sample_gid(archive):
    records = [json.loads(line) for line in (archive / 'capture/journal.jsonl').read_bytes().splitlines()]
    sample = next(r for r in records if r.get('event') == 'sample')
    # Inspect the real schema rather than fabricating a second message API.
    sample['graph']['candidates'][0]['endpoint_gid'] = '01' * 24
    (archive / 'capture/journal.jsonl').write_text('\n'.join(json.dumps(r) for r in records) + '\n')
    value = read(archive, 'collector_result.json')
    data = (archive / 'capture/journal.jsonl').read_bytes()
    entry = next(e for e in value['files'] if e['path'] == 'journal.jsonl')
    entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    write(archive, 'collector_result.json', value)
    rehash(archive)
    assert not correlate_capture(archive)['evidence_valid']


def test_cli_is_read_only_and_reports_blocked(archive, capsys):
    before = {p.relative_to(archive): p.read_bytes() for p in archive.rglob('*') if p.is_file()}
    assert main(['--correlate-capture', str(archive)]) == 2
    assert json.loads(capsys.readouterr().out)['evidence_valid'] is True
    after = {p.relative_to(archive): p.read_bytes() for p in archive.rglob('*') if p.is_file()}
    assert before == after
    with pytest.raises(SystemExit):
        main(['--correlate-capture', str(archive), 'other.jsonl'])
