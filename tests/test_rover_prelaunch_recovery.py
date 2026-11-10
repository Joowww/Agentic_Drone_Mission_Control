"""Offline only. Frozen reviewed proof + temporary runtime + metadata doubles."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import vehicle_execution_lock as locks
from tools.rover_xrce_trace import prelaunch_recovery as r


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, 'LOCK_ROOT', tmp_path/'vehicle_locks')
    locks.LOCK_ROOT.mkdir(exist_ok=True)
    originals = r.proof()
    for name, data in originals.items():
        p = Path(name); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    lease = json.loads((locks.LOCK_ROOT/'lifecycle.json').read_bytes())
    monkeypatch.setattr(r, 'boot', lambda: lease['process']['boot_id'])
    identity = locks.process_identity
    monkeypatch.setattr(locks, 'process_identity', lambda pid=None: None if pid == lease['process']['pid'] else identity(pid))
    observed = {'environment': {'container_id': 'reviewed-container'},
                'inventory': {'processes_clear': True, 'boot_id': 'container-boot'}}
    monkeypatch.setattr(r, 'observe', lambda context=None: observed)
    return originals, observed


def authorize(record):
    return f"RECOVER_PRELAUNCH {r.OWNER} {record['preparation_id']} {record['preparation_sha256']}"


def test_case_recovery_archives_and_preserves_historical_operation(case):
    originals, _ = case
    record = r.prepare()
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()
    result = r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))
    assert result['status'] == 'APPLIED' and result['movement_authorized'] is False
    assert not list(locks.LOCK_ROOT.glob('*.json'))
    target = json.loads((locks.LOCK_ROOT.parent/'diagnostic_agent_session.json').read_bytes())
    assert target['state'] == 'CLOSED'
    for item in result['originals']:
        assert Path(item['archive']).read_bytes() == originals[item['path']]
        if Path(item['path']).name not in {'lifecycle.json', 'diagnostic_agent_session.json'}:
            assert Path(item['path']).read_bytes() == originals[item['path']]
    assert r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))['replayed']


@pytest.mark.parametrize('change', ['owner', 'log', 'target', 'other_guard', 'environment', 'process', 'expired', 'authorization'])
def test_changes_and_uncertainty_never_release(case, monkeypatch, change):
    record = r.prepare()
    guard = locks.LOCK_ROOT/'lifecycle.json'
    before = guard.read_bytes()
    if change == 'owner':
        v = json.loads(before); v['owner_id'] = 'another'; guard.write_text(json.dumps(v))
    elif change == 'log':
        p = next(Path(name) for name in case[0] if name.endswith('backend.log')); p.write_text('changed')
    elif change == 'target':
        (guard.parent.parent/'diagnostic_agent_session.json').write_text('{}')
    elif change == 'other_guard':
        (guard.parent/'v3.json').write_text('{}')
    elif change == 'environment':
        monkeypatch.setattr(r, 'observe', lambda: {'environment': 'changed'})
    elif change == 'process':
        monkeypatch.setattr(locks, 'process_identity', lambda pid=None: {'pid': pid})
    elif change == 'expired':
        now = r.time.monotonic(); monkeypatch.setattr(r.time, 'monotonic', lambda: now+r.TTL+1)
    auth = 'old authorization' if change == 'authorization' else authorize(record)
    with pytest.raises(ValueError):
        r.apply(record['preparation_id'], record['preparation_sha256'], auth)
    assert guard.exists()
    assert not (r.root()/record['preparation_id']/'application.json').exists()


def test_partial_persistence_retains_barrier(case, monkeypatch):
    record = r.prepare(); original = locks.atomic_json
    def fail_target(path, value):
        if path.name == 'diagnostic_agent_session.json':
            raise OSError('synthetic fsync/write failure')
        return original(path, value)
    monkeypatch.setattr(locks, 'atomic_json', fail_target)
    with pytest.raises(OSError):
        r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()
    assert (locks.LOCK_ROOT/'reconciliation.json').exists()
    with pytest.raises(ValueError, match='Partial transaction'):
        r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))


def test_current_inventory_uses_readonly_frozen_entry(monkeypatch):
    environment = json.loads((r.EVIDENCE/'environment_before.json').read_bytes())
    monkeypatch.setattr(r, 'inspect_environment', lambda: environment)
    calls = []
    def read(args, **kwargs):
        calls.append(args)
        assert args[:3] == ['docker', 'exec', '-i']
        assert args[4:6] == ['python3', '-c']
        # Compile the generated read-only program, never execute container code.
        compile(args[-1], '<read-only-inventory>', 'exec')
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(processes_clear=True,
            prefix_exists=False, worker_exists=False, boot_id='boot', state_files={})))
    monkeypatch.setattr(r.subprocess, 'run', read)
    assert r.observe()['inventory']['processes_clear']
    assert len(calls) == 1


@pytest.mark.parametrize('field,value', [('processes_clear', False), ('prefix_exists', True),
                                        ('worker_exists', True), ('state_files', {'unknown': 'state'})])
def test_current_ambiguous_inventory_blocks(monkeypatch, field, value):
    environment = json.loads((r.EVIDENCE/'environment_before.json').read_bytes())
    monkeypatch.setattr(r, 'inspect_environment', lambda: environment)
    inventory = dict(processes_clear=True, prefix_exists=False, worker_exists=False, boot_id='boot', state_files={})
    inventory[field] = value
    monkeypatch.setattr(r.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(inventory)))
    with pytest.raises(ValueError, match='uncertain'):
        r.observe()


def test_other_environment_never_execs_inventory(monkeypatch):
    monkeypatch.setattr(r, 'inspect_environment', lambda: {'status': 'STOPPED'})
    monkeypatch.setattr(r.subprocess, 'run', lambda *a, **kw: pytest.fail('must not exec'))
    with pytest.raises(ValueError, match='Environment'):
        r.observe()


def test_admission_cannot_interleave_revalidation(case, monkeypatch):
    from threading import Event, Thread
    from tools.simulation_lifecycle import run_lifecycle
    record = r.prepare(); entered, release = Event(), Event(); errors = []
    def observe():
        entered.set()
        assert release.wait(5), 'deterministic test barrier was not released'
        return case[1]
    monkeypatch.setattr(r, 'observe', observe)
    def apply():
        try:
            r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))
        except BaseException as exc:
            errors.append(exc)
    thread = Thread(target=apply); thread.start()
    try:
        assert entered.wait(5)
        result = run_lifecycle('start', profile='two_drones_rover')
        assert result['status'] == 'BLOCKED'
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors


def test_new_preparation_cannot_reuse_authorization(case):
    first, second = r.prepare(), r.prepare()
    with pytest.raises(ValueError, match='authorization'):
        r.apply(second['preparation_id'], second['preparation_sha256'], authorize(first))
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()


@pytest.mark.parametrize('failure', ['application_intent', 'application_final'])
def test_audit_write_failure_cannot_silently_clear_barrier(case, monkeypatch, failure):
    record = r.prepare(); original = locks.atomic_json
    def write(path, value):
        if path.name == 'application.json' and value['status'] == ('APPLYING' if failure == 'application_intent' else 'APPLIED'):
            raise OSError('synthetic application audit failure')
        return original(path, value)
    monkeypatch.setattr(locks, 'atomic_json', write)
    with pytest.raises(OSError):
        r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))
    assert (locks.LOCK_ROOT/'reconciliation.json').exists()
    with pytest.raises(ValueError):
        r.apply(record['preparation_id'], record['preparation_sha256'], authorize(record))


def test_reviewed_proof_is_required(case, monkeypatch):
    monkeypatch.setattr(r, 'MANIFEST_SHA', '0'*64)
    with pytest.raises(ValueError, match='manifest changed'):
        r.prepare()
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()


def test_changed_launch_evidence_never_becomes_prelaunch_proof(case, tmp_path, monkeypatch):
    import shutil
    copy = tmp_path/'changed_evidence'; shutil.copytree(r.EVIDENCE, copy)
    monkeypatch.setattr(r, 'EVIDENCE', copy)
    log = copy/'runtime_copies/missions/generated/simulation_lifecycle'/r.OWNER/'backend.log'
    log.write_text('launch may have started; original traceback no longer available')
    with pytest.raises(ValueError, match='evidence changed'):
        r.prepare()
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()


def test_changed_original_host_boot_blocks(case, monkeypatch):
    monkeypatch.setattr(r, 'boot', lambda: 'different-host-boot')
    with pytest.raises(ValueError, match='host boot changed'):
        r.prepare()
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()



def scope_auth(review):
    return f"AUTHORIZE_PRELAUNCH_SCOPE {r.OWNER} {review['inspection_id']} {review['inspection_sha256']}"


def test_informative_inspection_has_no_ttl_or_preparation(case, monkeypatch):
    monkeypatch.setattr(r, 'apply', lambda *a, **kw: pytest.fail('inspection must not apply'))
    review = r.inspect_recovery()
    assert review['status'] == 'REVIEWABLE_NOT_AUTHORIZED'
    assert review['ttl_seconds'] is None and review['preparation_created'] is False
    assert review['scope']['transitions'][0]['after'] == 'ABSENT'
    assert review['application_eligible'] is False
    assert not list(r.root().glob('*/preparation.json'))
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()


def test_scope_authorized_fresh_prepare_then_apply(case):
    review = r.inspect_recovery()
    result = r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], scope_auth(review))
    assert result['status'] == 'APPLIED'
    assert result['review_reference']['inspection_id'] == review['inspection_id']
    with pytest.raises(ValueError, match='already consumed'):
        r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], scope_auth(review))


def test_scope_authorization_wrong_never_creates_preparation(case):
    review = r.inspect_recovery()
    with pytest.raises(ValueError, match='exact inspected scope'):
        r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], 'old authorization')
    assert not list(r.root().glob('*/preparation.json'))


def test_scope_changed_after_review_blocks_fresh_prepare(case, monkeypatch):
    review = r.inspect_recovery()
    monkeypatch.setattr(r, 'observe', lambda: {'environment': 'different'})
    with pytest.raises(ValueError, match='Reviewed scope changed'):
        r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], scope_auth(review))
    assert not list(r.root().glob('*/preparation.json'))
    assert (locks.LOCK_ROOT/'lifecycle.json').exists()


def test_informative_blocked_inspection_keeps_partial_context(case, monkeypatch):
    def observe(context=None):
        context['environment'] = {'status': 'DOCKER_UNAVAILABLE'}
        raise ValueError('Docker inaccessible')
    monkeypatch.setattr(r, 'observe', observe)
    review = r.inspect_recovery()
    assert review['status'] == 'BLOCKED' and review['current_files']
    assert review['observation_context']['environment']['status'] == 'DOCKER_UNAVAILABLE'
    assert review['scope']['transitions'] and review['scope']['observed'] is None
    with pytest.raises(ValueError, match='Review blocked'):
        r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], scope_auth(review))


def test_no_automatic_renewal_after_prepare_failure(case, monkeypatch):
    review = r.inspect_recovery()
    calls = []
    def fail(**kwargs):
        calls.append(kwargs); raise ValueError('synthetic preparation failure')
    monkeypatch.setattr(r, 'prepare', fail)
    with pytest.raises(ValueError, match='synthetic'):
        r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], scope_auth(review))
    with pytest.raises(ValueError, match='already consumed'):
        r.apply_reviewed(review['inspection_id'], review['inspection_sha256'], scope_auth(review))
    assert len(calls) == 1


def test_recorded_runtime_paths_resolve_from_any_installation_path():
    """The sealed index keeps the original checkout's absolute paths; only their part below missions/generated is used."""
    assert r.generated_relative('/home/joelm/TFG/Agentic_Drone_Mission_Control/missions/generated/vehicle_locks/'
                                'lifecycle.json') == Path('vehicle_locks/lifecycle.json')
    assert r.generated_relative('/srv/elsewhere/repo/missions/generated/simulation_lifecycle/x/operation.json') == \
        Path('simulation_lifecycle/x/operation.json')
    for bad in ('missions/generated/vehicle_locks/lifecycle.json',              # relative
                '/a/missions/generated/b/missions/generated/c.json',           # ambiguous
                '/a/missions/generated',                                        # names no file
                '/a/missions/generated/../vehicle_locks/lifecycle.json',       # climbs out
                '/a/missions/other/lifecycle.json'):                            # not below missions/generated
        with pytest.raises(ValueError):
            r.generated_relative(bad)
