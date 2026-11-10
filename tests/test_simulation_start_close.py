"""Protected close of an ordinary UNCONFIRMED start; offline only (tmp LOCK_ROOT, fake inventory/backend)."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools import simulation_lifecycle as lc
from tools import vehicle_execution_lock as locks

ROOT = Path(__file__).resolve().parents[1]
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
OWNER = '8eefc494-6d81-42b7-ac11-c3d47bceb65d'
STARTED = '2026-11-03T11:25:41.279960+00:00'
EXECUTION = {'persistent_identity': {'engine_id': 'e', 'container_id': 'c' * 64, 'image_id': 'sha256:' + 'i' * 64,
                                     'name': '/tfg-ardupilot-gazebo', 'created_at': '2026-10-02T07:28:34Z'},
             'container_started_at': '2026-11-03T09:44:02.9887145Z', 'container_boot_id': BOOT}
ROOT_ARGV = ['/usr/bin/python3', '/opt/ros/humble/bin/ros2', 'launch', 'ardupilot_gz_bringup',
             'tfg_rover_only.launch.py', 'rviz:=false', 'gui:=false']
RECEIPT = {'success': True, 'signals': [[5737, 15]], 'errors': [], 'diagnostic_coordination_errors': [],
           'unattributed_auxiliaries': [], 'remaining': [], 'observed_processes': [], 'diagnostic_agent': None}


def row(pid, ppid, ticks, argv, **extra):
    return {'pid': pid, 'ppid': ppid, 'start_ticks': ticks, 'argv': argv, 'tagged': True, 'zombie': False,
            'diagnostic_selection_sha256': None, 'profile_tag': 'rover_only', **extra}


def inventory():
    owned = [row(5737, 1, 6448039, ROOT_ARGV), row(5781, 5737, 6448100, ['/bin/sh', '-c', 'ruby gz sim']),
             row(5784, 5781, 6448101, ['gz', 'sim', '-s']), row(5788, 5737, 6448102, ['/root/micro_ros_agent', 'udp4']),
             row(5790, 5737, 6448103, ['ardurover', '--instance', '2'])]
    started = lc._wall(STARTED)
    return {'boot_id': BOOT, 'owned': owned, 'ambiguous': [], 'agents': [owned[3]],
            'state_files': {'/tmp/tfg_demo.processes.json': json.dumps(
                {'project': 'Agentic_Drone_Mission_Control', 'identities': [[5737, 6448039]]}),
                '/tmp/tfg_demo.diagnostic.json': '{}'},
            'launch_state_mtime': started + 6.6, 'container_init_ticks': 5934888, 'pid_file': '5737', 'files': {}}


def lease():
    return {'kind': 'SIMULATION_LIFECYCLE', 'owner_id': OWNER, 'state': 'UNCONFIRMED', 'action': 'start',
            'gui': False, 'profile': 'rover_only', 'scope': 'SIMULATION_INFRASTRUCTURE_ONLY',
            'movement_authorized': False, 'process': {'pid': 999999, 'start_ticks': 1, 'boot_id': BOOT},
            'started_at': STARTED, 'log_path': '/tmp/backend.log', 'environment_execution': copy.deepcopy(EXECUTION),
            'error': "TimeoutExpired: start backend timed out after 180 s"}


class World:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path/'generated/vehicle_locks'
        self.root.mkdir(parents=True)
        for name in ('v1.execution.lock', 'registry.lock'):
            (self.root/name).touch()
        monkeypatch.setattr(locks, 'LOCK_ROOT', self.root)
        monkeypatch.setattr(lc.locks, 'LOCK_ROOT', self.root)
        self.write_lease(lease())
        self.inventories = []
        self.after = {'boot_id': BOOT, 'owned': [], 'ambiguous': [], 'agents': [], 'state_files': {}, 'files': {}}
        self.alive = False
        self.roles = []
        self.backend_calls = []
        self.receipt = dict(RECEIPT)
        self.fence = lambda expected: None
        monkeypatch.setattr(lc, 'read_container_inventory', self.read_inventory)
        monkeypatch.setattr(lc, 'assert_environment_execution', lambda expected: self.fence(expected))
        monkeypatch.setattr(lc, 'host_role_processes', lambda: list(self.roles))
        real_alive = locks.identity_alive
        monkeypatch.setattr(lc.locks, 'identity_alive',
                            lambda identity: self.alive if identity == lease()['process'] else real_alive(identity))
        monkeypatch.setattr(lc, '_backend', self.backend)

    def write_lease(self, value):
        op = self.root.parent/'simulation_lifecycle'/value['owner_id']
        op.mkdir(parents=True, exist_ok=True)
        locks.atomic_json(op/'operation.json', value)
        (self.root/'lifecycle.json').write_bytes((op/'operation.json').read_bytes())

    def read_inventory(self, container_id):
        assert container_id == 'c' * 64
        return copy.deepcopy(self.inventories.pop(0) if self.inventories else (self.after if self.closed else inventory()))

    closed = False

    def backend(self, step, gui, descriptor, process, log_path):
        self.backend_calls.append(step)
        assert json.loads((self.root/'lifecycle.json').read_text())['closing_ordinary_start']['scope']['owner_id'] == OWNER
        log_path.write_text('[INFO] stop\n' + json.dumps(self.receipt) + '\n')
        self.closed = True
        return 0

    def lease_bytes(self):
        return (self.root/'lifecycle.json').read_bytes()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def apply(sha, authorization=None):
    return lc.run_lifecycle('stop', gui=False, profile='rover_only',
                            start_close_request=(OWNER, sha, authorization or f'{lc.START_CLOSE_AUTHORIZATION} {OWNER} {sha}'))


def test_inspection_is_read_only_and_eligible_for_the_recorded_launch_tree(world):
    before = world.lease_bytes()
    result = lc.inspect_start_close(OWNER)
    assert result['status'] == 'ELIGIBLE', result
    assert result['scope']['launch_identity'] == [5737, 6448039] and result['scope']['profile'] == 'rover_only'
    assert [p[0] for p in result['scope']['processes']] == [5737, 5781, 5784, 5788, 5790]
    assert result['required_authorization'] == f"{lc.START_CLOSE_AUTHORIZATION} {OWNER} {result['scope_sha256']}"
    assert world.lease_bytes() == before and world.backend_calls == []


def assess(**changes):
    kwargs = dict(host_boot_id=BOOT, owner_alive=False, vehicle_restrictions={'v1': None, 'v2': None, 'v3': None},
                  other_guards=set(), diagnostic_target={'state': 'CLOSED'}, host_roles=[])
    value, inv = lease(), inventory()
    mutate = changes.pop('mutate', None)
    if mutate:
        mutate(value, inv)
    kwargs.update(changes)
    raw = json.dumps(value).encode()
    return lc.assess_start_close(OWNER, raw, raw, inv, **kwargs)


def drop(key):
    return lambda v, i: v.pop(key)


@pytest.mark.parametrize('changes', [
    {'owner_alive': True}, {'owner_alive': None},
    {'host_boot_id': 'other-boot'},
    {'vehicle_restrictions': {'v1': None, 'v2': None, 'v3': {'owner_id': 'x'}}},
    {'other_guards': {'reconciliation.json'}}, {'other_guards': {'sequence.json'}},
    {'diagnostic_target': {'state': 'STARTED'}}, {'host_roles': [{'pid': 1}]},
    {'mutate': lambda v, i: v.update(state='FINISHED')}, {'mutate': lambda v, i: v.update(action='stop')},
    {'mutate': lambda v, i: v.update(diagnostic_agent={'x': 1})},
    {'mutate': lambda v, i: v.update(closing_ordinary_start={'x': 1})},
    {'mutate': lambda v, i: v['environment_execution'].update(container_boot_id='other')},
    {'mutate': lambda v, i: v['process'].update(boot_id='other')},
    {'mutate': lambda v, i: i.update(boot_id='other')},
    {'mutate': lambda v, i: i['owned'][0].update(start_ticks=1)},
    {'mutate': lambda v, i: i.update(owned=i['owned'][1:])},
    {'mutate': lambda v, i: i['owned'].append(row(7000, 1, 5, ['other']))},
    {'mutate': lambda v, i: i.update(ambiguous=[row(8000, 1, 5, ['ardurover'])])},
    {'mutate': lambda v, i: i['owned'][4].update(tagged=False)},
    {'mutate': lambda v, i: i['owned'][4].update(profile_tag='two_drones')},
    {'mutate': lambda v, i: i.update(agents=i['agents'] + [row(9000, 1, 5, ['micro_ros_agent'])])},
    {'mutate': lambda v, i: i['owned'][0].update(argv=ROOT_ARGV[:4] + ['tfg_demo.launch.py'] + ROOT_ARGV[5:])},
    {'mutate': lambda v, i: i['owned'][0].update(argv=['bash', '-c'] + ROOT_ARGV[1:])},
    {'mutate': lambda v, i: i.update(launch_state_mtime=i['launch_state_mtime'] - 3600)},
    {'mutate': lambda v, i: i.update(launch_state_mtime=i['launch_state_mtime'] + 400)},
    {'mutate': lambda v, i: i.update(launch_state_mtime=None)},
    {'mutate': lambda v, i: i.update(container_init_ticks=7000000)},
    {'mutate': lambda v, i: i.update(pid_file='5790')},
    {'mutate': lambda v, i: i['state_files'].pop('/tmp/tfg_demo.processes.json')},
    {'mutate': lambda v, i: i['state_files'].update({'/tmp/tfg_demo.processes.json': json.dumps(
        {'project': 'Agentic_Drone_Mission_Control', 'identities': [[5737, 6448039], [5790, 6448103]]})})},
])
def test_any_missing_or_contradictory_condition_blocks(changes):
    with pytest.raises(locks.VehicleBusy):
        assess(**changes)


def test_owner_dead_with_recorded_identity_is_eligible():
    scope = assess()
    assert scope['host_boot_id'] == BOOT and scope['environment_execution'] == EXECUTION
    assert scope['movement_authorized'] is False


def test_different_container_run_blocks_through_the_execution_fence(world):
    def fence(expected):
        raise locks.VehicleBusy('Active lifecycle container execution changed/unknown')
    world.fence = fence
    assert lc.inspect_start_close(OWNER)['status'] == 'BLOCKED'


@pytest.mark.parametrize('bad', ['authorization', 'scope'])
def test_wrong_scope_or_authorization_changes_nothing(world, bad):
    sha = lc.inspect_start_close(OWNER)['scope_sha256']
    before = world.lease_bytes()
    result = apply('f' * 64 if bad == 'scope' else sha, None if bad == 'scope' else 'The operator approved it')
    assert result['status'] == 'BLOCKED' and world.backend_calls == [] and world.lease_bytes() == before


def test_scope_change_between_review_and_application_blocks(world):
    sha = lc.inspect_start_close(OWNER)['scope_sha256']
    changed = inventory()
    changed['owned'].append(row(5799, 5737, 6448200, ['relay']))
    world.inventories = [changed]
    before = world.lease_bytes()
    assert apply(sha)['status'] == 'BLOCKED' and world.backend_calls == [] and world.lease_bytes() == before


def test_complete_close_releases_the_lease_only_after_confirmed_cleanup_and_is_idempotent(world):
    sha = lc.inspect_start_close(OWNER)['scope_sha256']
    original = (world.root.parent/'simulation_lifecycle'/OWNER/'operation.json').read_bytes()
    result = apply(sha)
    assert result['status'] == 'SUCCESS', result
    assert not (world.root/'lifecycle.json').exists() and world.backend_calls == ['stop']
    operation = result['operation']
    assert operation['closing_ordinary_start']['scope_sha256'] == sha
    assert operation['cleanup_receipt']['post_close_inventory'] == {'owned': [], 'ambiguous': [], 'agents': []}
    assert (world.root.parent/'simulation_lifecycle'/OWNER/'operation.json').read_bytes() == original
    again = apply(sha)
    assert again['status'] == 'SUCCESS' and again['already_completed'] is True and world.backend_calls == ['stop']


@pytest.mark.parametrize('bad', ['remaining', 'ambiguous_cleanup', 'still_owned', 'agent_left', 'no_receipt'])
def test_partial_or_unverified_cleanup_keeps_a_protected_lease(world, bad, monkeypatch):
    sha = lc.inspect_start_close(OWNER)['scope_sha256']
    if bad == 'remaining': world.receipt['remaining'] = [{'pid': 5790}]
    elif bad == 'ambiguous_cleanup': world.receipt['unattributed_auxiliaries'] = [{'pid': 8000}]
    elif bad == 'still_owned': world.after['owned'] = [row(5790, 5737, 6448103, ['ardurover'])]
    elif bad == 'agent_left': world.after['agents'] = [row(5788, 1, 6448102, ['micro_ros_agent'])]
    else: world.receipt = {'note': 'no cleanup json'}
    result = apply(sha)
    assert result['status'] == 'UNCONFIRMED'
    held = json.loads((world.root/'lifecycle.json').read_text())
    assert held['state'] == 'UNCONFIRMED' and held['closing_ordinary_start']['scope']['owner_id'] == OWNER
    assert apply(sha)['status'] == 'BLOCKED' and world.backend_calls == ['stop']  # no automatic replay


def test_interruption_during_close_keeps_the_closing_lease_and_never_replays(world, monkeypatch):
    sha = lc.inspect_start_close(OWNER)['scope_sha256']
    def interrupted(*args):
        world.backend_calls.append('stop')
        raise KeyboardInterrupt('SYNTHETIC interruption')
    monkeypatch.setattr(lc, '_backend', interrupted)
    with pytest.raises(KeyboardInterrupt):
        apply(sha)
    held = json.loads((world.root/'lifecycle.json').read_text())
    assert held['state'] == 'UNCONFIRMED' and held['action'] == 'stop'
    assert apply(sha)['status'] == 'BLOCKED' and world.backend_calls == ['stop']


def test_concurrent_lifecycle_holder_blocks_close(world):
    sha = lc.inspect_start_close(OWNER)['scope_sha256']
    with locks.file_mutex(world.root/'registry.lock'):
        assert apply(sha)['status'] == 'BLOCKED'
    assert world.backend_calls == []


def test_ordinary_close_cannot_be_combined_with_other_close_paths_or_actions(world):
    sha = 'a' * 64
    request = (OWNER, sha, f'{lc.START_CLOSE_AUTHORIZATION} {OWNER} {sha}')
    for kwargs in ({'close_owner': OWNER}, {'ground_owner': OWNER}):
        assert lc.run_lifecycle('stop', profile='rover_only', start_close_request=request, **kwargs)['status'] == 'BLOCKED'
    assert lc.run_lifecycle('start', profile='rover_only', start_close_request=request)['status'] == 'BLOCKED'


def test_plain_stop_still_refuses_the_retained_barrier(world):
    before = world.lease_bytes()
    assert lc.run_lifecycle('stop', profile='rover_only')['status'] == 'BLOCKED'
    assert world.lease_bytes() == before and world.backend_calls == []


def test_sealed_historical_records_are_not_read_as_close_candidates():
    # The new path only looks below the (patched) project LOCK_ROOT; evidence stays out of reach.
    source = (ROOT/'tools/simulation_lifecycle.py').read_text()
    assert 'evaluation/' not in source.split('START_CLOSE_KIND', 1)[1].split('def run_lifecycle', 1)[0]
    assert 'simulation/ros2_gazebo/results' not in source.split('START_CLOSE_KIND', 1)[1].split('def run_lifecycle', 1)[0]
