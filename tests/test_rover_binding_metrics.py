"""Discovery, freshness and raw preservation of the motion binding; clock domains of the metrics. Offline only."""
import copy
import json

import pytest

from tools import rover_motion_binding as mb, rover_sim_metrics as metrics
from tools.rover_control import RoverControlError
from tools.rover_ros2_adapter import ODOMETRY, STATUS
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE, NOW, raw

TOPICS = [ODOMETRY, STATUS]
EXPECTED = {ODOMETRY: ['ros_gz_bridge', '/rover1'], STATUS: ['ap_v3', '/']}
ODOM_GID, STATUS_GID = '01' * 24, '02' * 24


def pub(node, namespace, gid):
    return {'node': node, 'namespace': namespace, 'gid': gid, 'type': 't', 'reliability': 'RELIABLE'}


ODOM_OK, STATUS_OK = pub('ros_gz_bridge', '/rover1', ODOM_GID), pub('ap_v3', '/', STATUS_GID)
ODOM_EARLY = pub('_NODE_NAME_UNKNOWN_', '_NODE_NAMESPACE_UNKNOWN_', ODOM_GID)
STATUS_EARLY = pub('_CREATED_BY_BARE_DDS_APP_', '_CREATED_BY_BARE_DDS_APP_', STATUS_GID)


class FakeGraph:
    """timeline = {topic: [(from_time, rows), ...]}; spin() advances the fake monotonic clock."""
    def __init__(self, timeline, step=0.1):
        self.timeline, self.step, self.now, self.spins = timeline, step, 0.0, 0

    def monotonic(self):
        return self.now

    def spin(self):
        self.spins += 1
        self.now += self.step

    def query(self, topic):
        rows = []
        for at, value in self.timeline.get(topic, []):
            if self.now >= at:
                rows = value
        return copy.deepcopy(rows)


def wait(timeline, deadline_s=5.0):
    graph = FakeGraph(timeline)
    return graph, mb.wait_for_publishers(graph.query, EXPECTED, deadline_s=deadline_s,
                                         monotonic=graph.monotonic, spin=graph.spin)


def test_resolved_publishers_need_two_identical_observations():
    graph, result = wait({ODOMETRY: [(0, [ODOM_OK])], STATUS: [(0, [STATUS_OK])]})
    assert result['complete'] and result['missing'] == [] and graph.spins == 1
    assert result['identities'] == {ODOMETRY: {'node': 'ros_gz_bridge', 'namespace': '/rover1', 'gid': ODOM_GID},
                                    STATUS: {'node': 'ap_v3', 'namespace': '/', 'gid': STATUS_GID}}


@pytest.mark.parametrize('timeline', [
    {ODOMETRY: [(0, [ODOM_EARLY]), (1.0, [ODOM_OK])], STATUS: [(0, [STATUS_EARLY]), (2.0, [STATUS_OK])]},
    {ODOMETRY: [(0.5, [ODOM_EARLY]), (2.5, [ODOM_OK])], STATUS: [(0, [STATUS_OK])]},
    {ODOMETRY: [(0, [ODOM_OK])], STATUS: [(1.5, [STATUS_EARLY]), (3.0, [STATUS_OK])]}])
def test_gid_seen_before_the_node_name_waits_until_both_are_resolved(timeline):
    graph, result = wait(timeline)
    assert result['complete'] and result['reasons'] == {ODOMETRY: 'RESOLVED', STATUS: 'RESOLVED'}
    latest = max(at for rows in timeline.values() for at, _ in rows)
    assert min(result['resolved_s'].values()) >= 0 and max(result['resolved_s'].values()) >= latest


@pytest.mark.parametrize('timeline,reason,topic', [
    ({ODOMETRY: [(0, [ODOM_OK])], STATUS: [(0, [STATUS_EARLY])]}, 'NODE_IDENTITY_UNRESOLVED', STATUS),
    ({ODOMETRY: [(0, [ODOM_EARLY])], STATUS: [(0, [STATUS_OK])]}, 'NODE_IDENTITY_UNRESOLVED', ODOMETRY),
    ({ODOMETRY: [(0, [ODOM_OK])], STATUS: []}, 'ABSENT', STATUS),
    ({ODOMETRY: [(0, [ODOM_OK, pub('ros_gz_bridge', '/rover1', '03' * 24)])], STATUS: [(0, [STATUS_OK])]},
     'MULTIPLE_PUBLISHERS', ODOMETRY),
    ({ODOMETRY: [(0, [pub('impostor', '/rover1', ODOM_GID)])], STATUS: [(0, [STATUS_OK])]}, 'UNEXPECTED_NODE', ODOMETRY),
    ({ODOMETRY: [(0, [ODOM_OK]), (1.0, [pub('ros_gz_bridge', '/rover1', '04' * 24)])], STATUS: [(0, [STATUS_OK])]},
     'RESOLVED', None),
    ({ODOMETRY: [(0, [ODOM_EARLY]), (0.5, [pub('ros_gz_bridge', '/rover1', '04' * 24)])], STATUS: [(0, [STATUS_OK])]},
     'GID_CHANGED_DURING_DISCOVERY', ODOMETRY)])
def test_unresolved_duplicate_foreign_or_changed_publishers_time_out_with_reasons(timeline, reason, topic):
    graph, result = wait(timeline, deadline_s=1.0 if topic else 5.0)
    if topic is None:  # resolved before the later change was ever observed: the wait ended in time
        assert result['complete'] and result['elapsed_s'] < 1.0
        return
    assert result['complete'] is False and topic in result['missing'] and result['reasons'][topic] == reason
    assert 1.0 <= result['elapsed_s'] < 1.0 + 2 * graph.step


def test_gid_change_after_resolution_but_before_stability_taints_the_topic():
    graph, result = wait({ODOMETRY: [(0, [ODOM_OK]), (0.05, [pub('ros_gz_bridge', '/rover1', '04' * 24)])],
                          STATUS: [(0, [STATUS_OK])]}, deadline_s=1.0)
    assert result['complete'] is False and result['gid_changes'] == [ODOMETRY]


def test_stable_identity_across_snapshots_is_required_by_assess():
    value = raw()
    value['discovery']['identities'][STATUS]['gid'] = '09' * 24  # discovery saw another status GID
    with pytest.raises(RoverControlError, match='Discovered identities differ'):
        assess(value)
    value = raw()
    value['discovery']['gid_changes'] = [ODOMETRY]
    with pytest.raises(RoverControlError):
        assess(value)


def assess(value, **kwargs):
    kwargs.setdefault('now_wall_ns', NOW + 1_000_000_000)
    return mb.assess(value, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT, **kwargs)


@pytest.mark.parametrize('bad', ['incomplete', 'missing_status', 'no_discovery', 'second_publisher', 'gid_changed',
                                 'status_gid_changed', 'stale_samples', 'unordered_receipts', 'receipt_missing',
                                 'old_evidence', 'future_evidence', 'no_collection_time', 'stamps', 'boot'])
def test_binding_rejects_incomplete_changed_stale_or_foreign_evidence(bad):
    value = raw()
    if bad == 'incomplete': value['discovery'].update(complete=False, missing=[STATUS])
    elif bad == 'missing_status': value['discovery']['missing'] = [STATUS]
    elif bad == 'no_discovery': value.pop('discovery')
    elif bad == 'second_publisher': value['before'][STATUS].append(dict(value['before'][STATUS][0], gid='05' * 24))
    elif bad == 'gid_changed': value['after'][ODOMETRY][0]['gid'] = '06' * 24
    elif bad == 'status_gid_changed': value['after'][STATUS][0]['gid'] = '07' * 24
    elif bad == 'stale_samples':
        for s in value['samples']: s['received_wall_unix_ns'] -= 10_000_000_000
    elif bad == 'unordered_receipts': value['samples'][2]['received_wall_unix_ns'] = value['samples'][0]['received_wall_unix_ns'] - 1
    elif bad == 'receipt_missing': value['samples'][1].pop('received_wall_unix_ns')
    elif bad == 'old_evidence':
        with pytest.raises(RoverControlError):
            assess(value, now_wall_ns=NOW + 61_000_000_000)
        return
    elif bad == 'future_evidence':
        with pytest.raises(RoverControlError):
            assess(value, now_wall_ns=NOW - 1)
        return
    elif bad == 'no_collection_time': value.pop('collected_wall_unix_ns')
    elif bad == 'stamps': value['samples'][2]['stamp_ns'] = value['samples'][0]['stamp_ns']
    else: value['boot_id'] = 'other-boot'
    with pytest.raises(RoverControlError):
        assess(value)


def test_complete_discovery_is_recorded_in_the_accredited_evidence():
    binding, evidence = assess(raw())
    assert evidence['status'] == 'ACCREDITED_FOR_SESSION' and evidence['discovery']['complete'] is True
    assert evidence['status_publisher_gid'] == '02' * 24 and binding.odometry_publisher_gid == '01' * 24
    assert evidence['collected_wall_unix_ns'] == NOW


class Done:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def collect(value=None, *, returncode=0, container='c' * 64, fence=lambda e: None, session_fence=lambda *args: None, **kwargs):
    calls = []
    def run(argv, **kw):
        calls.append(argv)
        return Done(returncode, json.dumps(value) if value is not None else '', 'boom' if returncode else '')
    result = mb.collect(container, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                        run=run, fence=fence, session_fence=session_fence, **kwargs)
    return result, calls


def test_failed_accreditation_keeps_the_raw_originals():
    value = raw()
    value['discovery'].update(complete=False, missing=[STATUS], reasons={ODOMETRY: 'RESOLVED', STATUS: 'NODE_IDENTITY_UNRESOLVED'})
    value['before'][STATUS] = [STATUS_EARLY]
    result, _ = collect(value)
    assert result['status'] == 'BLOCKED' and result['evidence'] is None and result['binding'] is None
    assert result['raw'] == value and 'current scoped monotonic collector protocol' in result['reason']


def test_collector_result_keeps_bounded_diagnostics_without_duplicate_streams():
    result, _ = collect(raw())
    assert 'stdout' not in result['collector'] and 'stderr' not in result['collector']
    assert result['collector']['stdout_tail']
    assert len(result['collector']['stdout_tail']) <= 8192
    assert len(result['collector']['stderr_tail']) <= 2048


@pytest.mark.parametrize(('fail_on','expected_runs'),[(1,0),(2,1)])
def test_lifecycle_session_fence_runs_before_and_after_collection(fail_on,expected_runs):
    calls=[]
    def session_fence(*args):
        calls.append(args)
        if len(calls)==fail_on:
            raise RoverControlError('lifecycle changed during collection')
    result,runs=collect(raw(),session_fence=session_fence)
    assert len(calls)==fail_on and len(runs)==expected_runs
    assert result['status']=='BLOCKED' and 'lifecycle changed' in result['reason']
    if expected_runs:
        assert result['raw'] is not None


def test_reproduces_the_live_failure_of_cf3195614():
    # Same GIDs, placeholder names in the before snapshot, real names after.
    value = raw()
    value['before'] = {ODOMETRY: [ODOM_EARLY], STATUS: [STATUS_EARLY]}
    value['discovery'].update(identities={ODOMETRY: None, STATUS: None}, complete=True, missing=[])
    with pytest.raises(RoverControlError):
        assess(value)


def test_invalid_odometry_frames_remain_blocked():
    value=raw()
    value['samples'][-1]['child_frame_id']='map'
    with pytest.raises(RoverControlError,match='frames differ'):
        assess(value)


def test_collector_failure_is_blocked_with_its_diagnostic():
    result, _ = collect(returncode=1)
    assert result['status'] == 'BLOCKED' and result['raw'] is None and result['collector']['return_code'] == 1


@pytest.mark.parametrize('bad', ['container', 'fence_before', 'fence_after'])
def test_other_container_or_changed_execution_is_never_accredited(bad):
    calls = {'n': 0}
    def fence(expected):
        calls['n'] += 1
        if bad == 'fence_before' or (bad == 'fence_after' and calls['n'] == 2):
            raise RuntimeError('execution changed')
    result, runs = collect(raw(), container='d' * 64 if bad == 'container' else 'c' * 64, fence=fence)
    assert result['status'] == 'BLOCKED' and result['evidence'] is None
    assert (runs == []) if bad != 'fence_after' else (len(runs) == 1 and result['raw'] is not None)


def test_lifecycle_mismatch_is_rejected_on_reuse():
    _, evidence = assess(raw())
    with pytest.raises(RoverControlError):
        mb.require_current(evidence, lifecycle_id='00000000-0000-4000-8000-000000000000',
                           environment_execution=EXECUTION, host_boot_id=BOOT)


S = 1_000_000_000
EPOCH = 1_793_726_000 * S  # ArduPilot clock domain (Unix epoch)


def sample(*, gz_clock=True, ap_clock=True, odom_offset=0, stale=False):
    """20 s wall window; Gazebo clock 0..12.8 s, ArduPilot clock in epoch; odometry 50 Hz sim."""
    wall = lambda t: int(t * S)
    gz = [[wall(t), int(t * 0.64 * S)] for t in (0.0, 20.0)] if gz_clock else []
    ap = [[wall(t), EPOCH + int(t * 0.64 * S)] for t in (0.0, 20.0)] if ap_clock else []
    end_receipt = 5.0 if stale else 19.99
    odometry = [[wall(end_receipt * i / 639), int(i / 50 * S) + odom_offset, {'frame_id': 'odom'}] for i in range(640)]
    status = [[wall(19.9), EPOCH + int(12.7 * S), {'armed': False, 'mode': 0}]]
    navsat = [[wall(19.5), EPOCH + int(12.5 * S), {'status': 2, 'latitude': 0.0, 'longitude': 0.0, 'altitude': 0.0}]]
    return {'wall_start_ns': 0, 'wall_end_ns': wall(20.0), 'seen': {
        'gazebo_clock': gz, 'ardupilot_clock': ap, 'odometry': odometry, 'status': status, 'navsat': navsat}}


def test_rtf_and_rates_use_the_gazebo_clock_and_both_time_bases():
    out = metrics.summarize(sample())
    assert out['real_time_factor'] == pytest.approx(0.64) and out['real_time_factor_basis'] == 'GAZEBO_CLOCK'
    assert out['clocks']['ardupilot']['real_time_factor'] == pytest.approx(0.64)
    odom = out['odometry']
    assert odom['clock_domain'] == 'gazebo' and odom['rate_per_wall_s'] == pytest.approx(32.0)
    assert odom['rate_per_sim_s'] == pytest.approx(50.0) and odom['stamps_strictly_increasing']
    assert odom['sim_age_basis'] == 'SAME_DOMAIN_CLOCK' and odom['last_age_sim_s'] == pytest.approx(0.02, abs=1e-6)
    assert odom['last_age_wall_s'] == pytest.approx(0.01, abs=1e-6) and odom['fresh']
    status = out['status']
    assert status['clock_domain'] == 'ardupilot' and status['last_age_sim_s'] == pytest.approx(0.1, abs=1e-6)
    assert out['gps_fix'] is True and out['stale_streams'] == []


def test_stamps_from_another_clock_domain_are_not_subtracted():
    # Odometry stamped in epoch-like time while the Gazebo clock starts at zero.
    out = metrics.summarize(sample(odom_offset=EPOCH))
    assert out['odometry']['last_age_sim_s'] is None
    assert out['odometry']['sim_age_basis'] == 'NOT_COMPARABLE_STAMP_OUTSIDE_CLOCK_RANGE'


def test_missing_clock_gives_unknown_not_a_number():
    out = metrics.summarize(sample(gz_clock=False))
    assert out['real_time_factor'] is None and out['real_time_factor_basis'] == 'UNKNOWN'
    assert out['odometry']['sim_age_basis'] == 'UNKNOWN_CLOCK_ABSENT' and out['odometry']['last_age_sim_s'] is None


def test_stale_streams_are_flagged():
    out = metrics.summarize(sample(stale=True))
    assert out['odometry']['fresh'] is False and 'odometry' in out['stale_streams']
    empty = metrics.summarize({'wall_start_ns': 0, 'wall_end_ns': S, 'seen': {}})
    assert empty['odometry']['reason'] == 'NO_MESSAGES_IN_WINDOW' and set(empty['stale_streams']) == set(metrics.STREAMS)
