"""Host-reboot successors chained on a copy of the 891dab60 audit; every store is synthetic /tmp.

A reboot is modelled by changing ONLY what a reboot changes: host/container boot id,
container StartedAt and container namespaces. Historical records stay the sealed copies.
"""
import copy
import json
import shutil

import pytest

from tools.rover_xrce_trace import historical_disposition as d, present_recovery as recovery
from tests.test_rover_consumer_successor import APPLIED, REPLAY, read

ROOT_BOOT = '11f52aeb-7eb2-4fa0-8a68-275cf6d2b8be'
BOOT_1 = 'fd538729-f4ea-4193-a6a3-f5f000fdd14b'
BOOT_2 = '5b0e6a71-3c2d-4e8f-9a1b-0c2d3e4f5a6b'
FILES = ('intent.json', 'originals.json')


class World:
    def __init__(self, tmp_path, monkeypatch):
        folder = tmp_path/'synthetic-audit'
        shutil.copytree(APPLIED/'application-audit', folder)
        value = read(REPLAY)
        self.records, self.current = copy.deepcopy(value['records']), copy.deepcopy(value['current'])
        self.current['resources']['reader_hashes'] = recovery.reader_hashes()
        self.now = self.current['observed_monotonic']+2.7
        self.domain = copy.deepcopy(self.current['host_acquisition']['clock_context'])
        monkeypatch.setattr(recovery, 'host_clock_context', lambda: copy.deepcopy(self.domain))
        self.engine = d.OfflineDisposition(folder, owner=self.records['target']['descriptor']['lifecycle_id'],
                                           clock=lambda: self.now)
        self.engine.offline_only = False

    def reboot(self, boot, started, namespace):
        r, c = self.records, self.current
        context = {'boot_id': boot, 'net_namespace': f'net:[{namespace}]',
                   'pid_namespace': f'pid:[{namespace+1}]', 'time_namespace': f'time:[{namespace+2}]'}
        r['environment']['state']['StartedAt'] = c['environment_observation']['state']['StartedAt'] = started
        r['inventory'].update(boot_id=boot, query_context_before=dict(context), query_context_after=dict(context))
        c['resources']['context'].update(context)
        c['resources']['context']['anchor'].update(net_namespace=context['net_namespace'],
                                                   pid_namespace=context['pid_namespace'])
        c['host_boot_id'] = boot
        for key in ('clock_context', 'received_clock_context'):
            c['host_acquisition'][key]['process']['boot_id'] = boot
        self.domain['process']['boot_id'] = boot

    def review(self):
        tip, _ = self.engine.chain_bindings()
        return d.dry_run(copy.deepcopy(self.records), {**copy.deepcopy(self.current), 'consumer_predecessor': tip},
                         now=self.now)

    def apply(self, sha=None, *, reader=None):
        if sha is None:
            v = self.review()
            assert v['status'] == 'DRY_RUN_ELIGIBLE', v
            sha = v['scope_sha256']
        return self.engine.apply_successor(self.records, reader or (lambda: copy.deepcopy(self.current)),
                                           scope_sha256=sha, authorization=auth(self.engine, sha))

    def precheck(self):
        audit = self.engine.query()
        parent = self.engine.chain_bindings(audit)[1] if 'consumer_successor' in audit else None
        current = {**copy.deepcopy(self.current), **({'consumer_predecessor': parent} if parent else {})}
        return d.diagnostic_precheck(copy.deepcopy(self.records), current, audit, now=self.now)

    def snapshot(self, path=None):
        path = path or self.engine.root
        return {n: (path/n).read_bytes() for n in FILES}


def auth(engine, sha):
    return f'AUTHORIZE_DIAGNOSTIC_DISPOSITION {engine.owner} {sha}'


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def test_two_consecutive_reboots_recover_and_keep_every_prior_record_byte_exact(world):
    original = world.snapshot()
    assert world.precheck()['status'] == 'BLOCKED'  # current reader pin is not the audited one
    world.reboot(BOOT_1, '2026-11-03T09:00:00.123456789Z', 4026540000)
    assert world.precheck()['status'] == 'BLOCKED'
    first = world.apply()
    link = first['scope']['consumer_revision']
    assert link['protocol'] == d.RESOURCE_READER_SUCCESSOR_PROTOCOL
    assert link['reader_transition'] == d._verified_resource_reader_transition()
    assert set(link['boot_transition']) == {'from_host_boot_id', 'to_host_boot_id',
        'from_container_started_at', 'to_container_started_at'}
    assert link['boot_transition']['from_host_boot_id'] == ROOT_BOOT
    assert link['boot_transition']['to_host_boot_id'] == BOOT_1 and first['scope']['host_boot_id'] == BOOT_1
    decision = world.precheck()
    assert decision['status'] == 'SATISFIED' and decision['disposition_consumed'], decision
    assert not decision['opening_authorized'] and not decision['movement_authorized']
    first_bytes = world.snapshot(world.engine.root/'revisions'/first['scope_sha256'])

    world.reboot(BOOT_2, '2026-11-04T08:00:00.5Z', 4026550000)
    stale = world.precheck()
    assert stale['status'] == 'BLOCKED' and not stale['disposition_consumed']
    second = world.apply()
    assert second['scope']['consumer_revision']['predecessor_scope_sha256'] == first['scope_sha256']
    assert second['scope']['consumer_revision']['boot_transition']['from_host_boot_id'] == BOOT_1
    decision = world.precheck()
    assert decision['status'] == 'SATISFIED' and decision['disposition_consumed'], decision

    queried = world.engine.query()
    assert [s['scope_sha256'] for s in queried['consumer_chain']] == [first['scope_sha256'], second['scope_sha256']]
    assert world.snapshot() == original
    assert world.snapshot(world.engine.root/'revisions'/first['scope_sha256']) == first_bytes
    for record in (queried, first, second):
        assert all(record[k] is False for k in ('opening_authorized', 'movement_authorized', 'source_association_verified'))
        assert record['scope']['historical'] == read(APPLIED/'audit-after.json')['scope']['historical']
        assert record['scope']['environment_execution']['persistent_identity'] == \
            queried['scope']['environment_execution']['persistent_identity']
    assert world.records['monitor']['capture_complete'] is False


def test_same_boot_pin_successor_then_reboot_extends_the_same_chain(world):
    same = world.apply()
    assert same['scope']['consumer_revision']['protocol'] == d.RESOURCE_READER_SUCCESSOR_PROTOCOL
    assert same['scope']['consumer_revision']['reader_transition'] == d._verified_resource_reader_transition()
    assert 'boot_transition' not in same['scope']['consumer_revision']
    assert world.precheck()['status'] == 'SATISFIED'
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    assert world.precheck()['status'] == 'BLOCKED'
    after = world.apply()
    assert after['scope']['consumer_revision']['predecessor_scope_sha256'] == same['scope_sha256']
    assert world.precheck()['status'] == 'SATISFIED'


@pytest.fixture
def boot_candidate(world):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    v = world.review()
    assert v['status'] == 'DRY_RUN_ELIGIBLE', v
    return world.engine.chain_bindings()[0], {k: v for k, v in v['scope'].items() if k != 'consumer_revision'}


@pytest.mark.parametrize('bad', ['container', 'image', 'engine', 'created', 'historical', 'proof', 'limitations',
                                 'opening', 'movement', 'source', 'effects', 'preserved', 'host_time_namespace',
                                 'env_boot', 'ctx_boot', 'same_started_at', 'empty_namespace', 'extra_context',
                                 'other_pin', 'extra_field', 'removed_field', 'restart_without_reboot'])
def test_reboot_link_rejects_anything_beyond_the_new_execution_context(boot_candidate, bad):
    parent, scope = boot_candidate
    scope = copy.deepcopy(scope)
    old = parent['audit']['scope']
    identity = scope['environment_execution']['persistent_identity']
    if bad == 'container': identity['container_id'] = 'f'*64
    elif bad == 'image': identity['image_id'] = 'sha256:'+'e'*64
    elif bad == 'engine': identity['engine_id'] = 'other-engine'
    elif bad == 'created': identity['created_at'] = '2026-11-03T08:00:00Z'
    elif bad == 'historical': scope['historical']['monitor']['capture_complete'] = True
    elif bad == 'proof': scope['proof'] = {**scope['proof'], 'layout': 'other'}
    elif bad == 'limitations': scope['historical_limitations'] = []
    elif bad == 'opening': scope['opening_authorized'] = True
    elif bad == 'movement': scope['movement_authorized'] = True
    elif bad == 'source': scope['source_association_verified'] = True
    elif bad == 'effects': scope['effects'] = ['RELEASE_RESERVATIONS']
    elif bad == 'preserved': scope['preserved'] = []
    elif bad == 'host_time_namespace': scope['host_time_namespace'] = 'time:[1]'
    elif bad == 'env_boot': scope['environment_execution']['container_boot_id'] = BOOT_2
    elif bad == 'ctx_boot': scope['resource_context']['boot_id'] = BOOT_2
    elif bad == 'same_started_at':
        scope['environment_execution']['container_started_at'] = old['environment_execution']['container_started_at']
    elif bad == 'empty_namespace': scope['resource_context']['pid_namespace'] = ''
    elif bad == 'extra_context': scope['resource_context']['extra'] = 'x'
    elif bad == 'other_pin': scope['reader_hashes']['tools/rover_xrce_trace/budget.py'] = 'f'*64
    elif bad == 'extra_field': scope['opening_scope'] = 'x'
    elif bad == 'removed_field': scope.pop('freshness_basis')
    else:  # container restart inside the audited boot: not a reboot recovery
        scope['host_boot_id'] = old['host_boot_id']
        scope['environment_execution']['container_boot_id'] = scope['resource_context']['boot_id'] = old['host_boot_id']
    with pytest.raises((ValueError, KeyError)):
        d._successor_link(parent, scope)


def test_reviewed_reboot_link_itself_is_exact(boot_candidate):
    parent, scope = boot_candidate
    link = d._successor_link(parent, scope)
    for field in ('to_host_boot_id', 'to_container_started_at'):
        forged = copy.deepcopy(link)
        forged['boot_transition'][field] = 'other'
        with pytest.raises(ValueError, match='link changed'):
            d._successor_link(parent, {**scope, 'consumer_revision': forged})


def test_different_container_blocks_the_review_before_any_scope(world):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    world.records['environment']['container_id'] = 'f'*64
    v = world.review()
    assert v['status'] == 'BLOCKED' and v.get('scope_sha256') is None and 'identity mismatch' in v['reason']


@pytest.mark.parametrize('bad', ['occupied', 'incomplete_reader', 'restriction', 'guard', 'host_process',
                                 'other_session', 'container_process'])
def test_occupied_uncertain_or_reserved_current_state_never_reviews_or_applies(world, bad):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    eligible = world.review()['scope_sha256']
    c, r = world.current, world.records
    if bad == 'occupied': c['resources'].update(status='OCCUPIED', reasons=['IN_USE'])
    elif bad == 'incomplete_reader': c['complete'] = False
    elif bad == 'restriction': c['restriction'] = {'owner_id': 'reservation', 'state': 'UNCONFIRMED'}
    elif bad == 'guard': c['guards'] = {'v3.json': '0'*64}
    elif bad == 'host_process': c['host_processes'] = [{'pid': 1, 'start_ticks': 1}]
    elif bad == 'other_session': c['other_sessions'] = ['unknown-or-extra-state']
    else: r['inventory']['owned'] = [{'pid': 7, 'start_ticks': 7}]
    assert world.review()['status'] == 'BLOCKED'
    before = world.snapshot()
    with pytest.raises(ValueError):
        world.apply(eligible)
    assert world.snapshot() == before and not (world.engine.root/'revisions').exists()


@pytest.mark.parametrize('bad', ['previous_authorization', 'unreviewed_hash', 'other_owner', 'llm_style_text'])
def test_wrong_hash_or_authorization_writes_nothing(world, bad):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    sha = world.review()['scope_sha256']
    authorization = auth(world.engine, sha)
    if bad == 'previous_authorization': authorization = world.engine.query()['authorization']
    elif bad == 'unreviewed_hash': sha = 'f'*64; authorization = auth(world.engine, sha)
    elif bad == 'other_owner': authorization = f'AUTHORIZE_DIAGNOSTIC_DISPOSITION 12345678-1234-4234-8234-123456789abc {sha}'
    else: authorization = f'The operator approved the recovery of {sha}'
    calls = []
    def observe():
        calls.append(1)
        return copy.deepcopy(world.current)
    with pytest.raises(ValueError):
        world.engine.apply_successor(world.records, observe, scope_sha256=sha, authorization=authorization)
    assert not (world.engine.root/'revisions').exists()
    assert calls == ([] if bad != 'unreviewed_hash' else [1])


def test_scope_reviewed_before_a_reboot_cannot_be_applied_after_it(world):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    reviewed = world.review()['scope_sha256']
    world.reboot(BOOT_2, '2026-11-04T08:00:00Z', 4026550000)
    with pytest.raises(ValueError, match='scope changed'):
        world.apply(reviewed)
    assert not (world.engine.root/'revisions').exists()


def test_revision_applied_twice_is_never_written_twice(world):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    first = world.apply()
    path = world.engine.root/'revisions'/first['scope_sha256']
    first_bytes = world.snapshot(path)
    repeat = world.engine.apply_successor(world.records, lambda: pytest.fail('No replay observation'),
                                          scope_sha256=first['scope_sha256'], authorization=auth(world.engine, first['scope_sha256']))
    assert repeat == first and world.snapshot(path) == first_bytes
    world.reboot(BOOT_2, '2026-11-04T08:00:00Z', 4026550000)
    second = world.apply()
    with pytest.raises(ValueError, match='Superseded'):
        world.engine.apply_successor(world.records, lambda: pytest.fail('No replay observation'),
                                     scope_sha256=first['scope_sha256'], authorization=auth(world.engine, first['scope_sha256']))
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([first['scope_sha256'], second['scope_sha256']])


@pytest.mark.parametrize('bad', ['fork', 'orphan', 'interrupted_second', 'edited_first'])
def test_forked_orphaned_or_interrupted_chains_fail_closed_without_fallback(world, bad):
    world.reboot(BOOT_1, '2026-11-03T09:00:00Z', 4026540000)
    first = world.apply()
    revisions = world.engine.root/'revisions'
    first_path = revisions/first['scope_sha256']
    if bad == 'fork':  # a second, different successor of the same predecessor
        value = read(first_path/'intent.json')
        value['scope']['environment_execution']['container_started_at'] = '2026-11-03T09:30:00Z'
        value['scope_sha256'] = sha = d.digest(value['scope'])
        value['authorization'] = auth(world.engine, sha)
        (revisions/sha).mkdir()
        (revisions/sha/'intent.json').write_text(json.dumps(value))
        (revisions/sha/'originals.json').write_text(json.dumps(value['scope']))
    elif bad == 'orphan':
        shutil.copytree(first_path, revisions/('e'*64))
    elif bad == 'interrupted_second':
        world.reboot(BOOT_2, '2026-11-04T08:00:00Z', 4026550000)
        sha = world.review()['scope_sha256']
        real = world.engine.write
        def fail(path, value):
            if path.name == 'originals.json': raise OSError('SYNTHETIC storage failure')
            real(path, value)
        world.engine.write = fail
        with pytest.raises(OSError):
            world.apply(sha)
    else:  # bytes of a record already bound by the next link
        world.reboot(BOOT_2, '2026-11-04T08:00:00Z', 4026550000)
        world.apply()
        (first_path/'originals.json').write_bytes((first_path/'originals.json').read_bytes()+b' ')
    assert world.engine.query()['status'] == 'APPLYING_UNCONFIRMED'
    assert world.precheck()['status'] == 'BLOCKED'
    with pytest.raises(ValueError):
        world.apply('a'*64, reader=lambda: pytest.fail('No observation on an uncertain chain'))


def test_historical_stores_remain_exact_and_new_reader_link_is_versioned(world):
    # Sealed copy without revisions: identical audit, no chain fields added.
    assert world.engine.query() == read(world.engine.root/'intent.json')
    parent = world.engine.predecessor_binding()
    assert world.engine.record_binding(parent['audit']) == parent
    assert world.engine.chain_bindings() == (parent, None)
    scope = {k: v for k, v in world.review()['scope'].items() if k != 'consumer_revision'}
    link = d._successor_link(parent, scope)
    assert set(link) - {'reader_revision', 'reader_transition'} == {'protocol', 'owner_id',
        'predecessor_scope_sha256', 'predecessor_authorization', 'audit_file_hashes',
        'pin', 'before_sha256', 'after_sha256'}
    assert link['protocol'] == d.RESOURCE_READER_SUCCESSOR_PROTOCOL
    assert link['reader_transition'] == d._verified_resource_reader_transition()
    assert set(link.get('reader_revision', {})) <= set(d.REVISABLE_PINS) | {d.RESOURCE_READER_PIN}


@pytest.mark.parametrize('bad', ['unknown_protocol', 'missing_transition', 'altered_transition',
                                 'wrong_current_pin', 'unapproved_pin'])
def test_versioned_present_reader_successor_is_exact_and_fail_closed(boot_candidate, bad):
    parent, scope = boot_candidate
    link = d._successor_link(parent, scope)
    assert link['protocol'] == d.RESOURCE_READER_SUCCESSOR_PROTOCOL
    assert link['reader_transition'] == d._verified_resource_reader_transition()
    candidate = copy.deepcopy(scope)
    if bad == 'unknown_protocol':
        link['protocol'] = 'PRESENT_RESOURCE_READER_SUCCESSOR_V999'
    elif bad == 'missing_transition':
        link.pop('reader_transition')
    elif bad == 'altered_transition':
        link['reader_transition']['introduced_by_commit'] = 'f' * 40
    elif bad == 'wrong_current_pin':
        candidate['reader_hashes'][d.RESOURCE_READER_PIN] = 'f' * 64
    else:
        candidate['reader_hashes']['tools/rover_xrce_trace/budget.py'] = 'f' * 64
    candidate['consumer_revision'] = link
    with pytest.raises(ValueError):
        d._successor_link(parent, candidate)
