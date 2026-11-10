"""rover_only profile, profile-catalogue revision, motion binding, odom goals, metrics and the
inactive SITL policy. Offline only: synthetic fixtures, no Docker, ROS or project state."""
import copy
import math
from pathlib import Path

import pytest

from planning.artifact_store import fingerprint
from tools import rover_motion_binding as mb, rover_sim_metrics as metrics, rover_sitl_trial_policy as policy
from tools import rover_target_frame as frame
from tools.rover_control import NavigationGoal, RoverControlError
from tools.rover_ros2_adapter import ODOMETRY, STATUS
from tools.rover_xrce_trace import historical_disposition as d
from tools.simulation_profiles import PROFILES, ACTIVE_PROFILE, get_profile

ROOT = Path(__file__).resolve().parents[1]
BOOT = 'fd538729-f4ea-4193-a6a3-f5f000fdd14b'
EXECUTION = {'persistent_identity': {'engine_id': 'e', 'container_id': 'c' * 64, 'image_id': 'sha256:' + 'i' * 64,
                                     'name': '/tfg-ardupilot-gazebo', 'created_at': '2026-10-02T07:28:34Z'},
             'container_started_at': '2026-11-03T09:44:02.9887145Z', 'container_boot_id': BOOT}
LIFECYCLE = '72f47371-6d7f-4980-abe8-b7c72a9ce533'
Q = [-0.0033658545799034423, 0.0033794153014570405, 0.7056757729240591, 0.7085188452562139]
GZ = 'Model: [67]\n  - Name: rover1\n  - Pose [ XYZ (m) ] [ RPY (rad) ]:\n    [-0.001244 -3.000450 0.094909]\n    [0.000000 0.009537 1.566770]\n'
CONFIG = '- ros_topic_name: "clock"\n  gz_topic_name: "/clock"\n- ros_topic_name: "odometry"\n  gz_topic_name: "/model/rover1/odometry"\n'
NOW = 1_793_726_000_000_000_000  # synthetic realtime ns of the collection end


def raw():
    pub = lambda node, ns, gid: [{'node': node, 'namespace': ns, 'type': 't', 'gid': gid, 'reliability': 'RELIABLE'}]
    graph = {ODOMETRY: pub('ros_gz_bridge', '/rover1', '01' * 24), STATUS: pub('ap_v3', '/', '02' * 24)}
    samples = [{'stamp_ns': 4_720_000_000 + i * 10_000_000, 'frame_id': 'odom', 'child_frame_id': 'base_link',
                'position': [-0.0012461, -3.0005524, 0.0949062], 'orientation_xyzw': list(Q),
                'received_wall_unix_ns': NOW - (3 - i) * 100_000_000} for i in range(3)]
    return {'boot_id': BOOT, 'before': copy.deepcopy(graph), 'after': copy.deepcopy(graph), 'samples': samples,
            'discovery': {'complete': True, 'missing': [], 'deadline_s': 15.0, 'elapsed_s': 1.2,
                          'first_seen_s': {ODOMETRY: 0.1, STATUS: 1.2}, 'gid_changes': [],
                          'reasons': {ODOMETRY: 'RESOLVED', STATUS: 'RESOLVED'},
                          'identities': {ODOMETRY: {'node': 'ros_gz_bridge', 'namespace': '/rover1', 'gid': '01' * 24},
                                         STATUS: {'node': 'ap_v3', 'namespace': '/', 'gid': '02' * 24}}},
            'collected_wall_unix_ns': NOW,
            'bridge': [{'pid': 9, 'argv': ['parameter_bridge', '__ns:=/rover1'],
                        'params': [{'path': '/tmp/p.yaml', 'sha256': 'a' * 64, 'text': 'config_file: /tmp/b.yaml'}],
                        'configs': [{'path': '/tmp/b.yaml', 'sha256': 'b' * 64, 'text': CONFIG}]}],
            'gz_model_pose_stdout': GZ, 'namespaces': {}}


def assess(value, now=NOW + 1_000_000_000):
    return mb.assess(value, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT, now_wall_ns=now)


def test_rover_only_profile_keeps_the_rover_identity_and_leaves_existing_profiles_alone():
    rover = get_profile('rover_only')
    assert ACTIVE_PROFILE.name == 'two_drones' and set(PROFILES) == {'two_drones', 'two_drones_rover', 'rover_only'}
    assert rover.vehicles == (get_profile('two_drones_rover').vehicles[2],)
    assert rover.bindings == (('rover_01', 'v3'),) and rover.status_topics == ('/ap/v3/status',)
    assert rover.sitl_ports_awaited_before_start == (5780,) and rover.expected_process_counts == (('ardurover', 1),)
    launch = (ROOT/'simulation/ros2_gazebo/launch'/rover.launch_file).read_text()
    assert 'INSTANCE = "2"' in launch and 'SYSID = "3"' in launch and 'ROBOT_NAME = "rover1"' in launch
    assert '"wildthumper", "model.sdf"' in launch and 'with_lidar' not in launch.split('"""', 2)[2]
    assert '"use_dds_agent": "False"' in launch and 'micro_ros_agent.launch.py' in launch


def scope_with_pins(parent, **changes):
    scope = {k: v for k, v in parent['audit']['scope'].items() if k != 'consumer_revision'}
    scope = copy.deepcopy(scope)
    scope['reader_hashes'].update(changes)
    return scope


@pytest.fixture
def parent():
    audit = {'schema': 'tfg.diagnostic-disposition/3', 'status': 'DISPOSED_DIAGNOSTICALLY_INCOMPLETE',
             'owner_id': '891dab60-75f4-4008-b63d-2623ca5221a4',
             'opening_authorized': False, 'movement_authorized': False, 'source_association_verified': False,
             'scope': {'protocol': 'CURRENT_RESOURCE_REVIEW_V1', 'host_boot_id': BOOT,
                       'historical': {'target': {'descriptor': {'lifecycle_id': '891dab60-75f4-4008-b63d-2623ca5221a4'}}},
                       'reader_hashes': {d.SUCCESSOR_PIN: d.SUCCESSOR_FROM, 'tools/simulation_profiles.py': '1' * 64,
                                         'tools/rover_xrce_trace/budget.py': '2' * 64}}}
    audit['scope_sha256'] = d.digest(audit['scope'])
    audit['authorization'] = f"AUTHORIZE_DIAGNOSTIC_DISPOSITION {audit['owner_id']} {audit['scope_sha256']}"
    return {'audit': audit, 'audit_file_hashes': {'intent.json': '3' * 64, 'originals.json': '4' * 64}}


def test_profile_catalogue_revision_is_linked_and_listed(parent):
    link = d._successor_link(parent, scope_with_pins(parent, **{d.SUCCESSOR_PIN: '5' * 64, 'tools/simulation_profiles.py': '6' * 64}))
    assert link['protocol'] == d.SUCCESSOR_PROTOCOL
    assert link['reader_revision'] == {d.SUCCESSOR_PIN: {'before_sha256': d.SUCCESSOR_FROM, 'after_sha256': '5' * 64},
                                       'tools/simulation_profiles.py': {'before_sha256': '1' * 64, 'after_sha256': '6' * 64}}
    only_profiles = d._successor_link(parent, scope_with_pins(parent, **{'tools/simulation_profiles.py': '6' * 64}))
    assert set(only_profiles['reader_revision']) == {'tools/simulation_profiles.py'}


@pytest.mark.parametrize('pins', [{'tools/rover_xrce_trace/budget.py': '7' * 64},
                                  {d.SUCCESSOR_PIN: '5' * 64, 'tools/rover_xrce_trace/budget.py': '7' * 64},
                                  {'tools/simulation_profiles.py': 'not-a-hash'}, {}])
def test_other_readers_or_no_change_are_still_rejected(parent, pins):
    with pytest.raises(ValueError):
        d._successor_link(parent, scope_with_pins(parent, **pins))


def test_motion_binding_is_produced_from_graph_frames_and_gazebo_pose():
    binding, evidence = assess(raw())
    assert binding.odometry_publisher_gid == '01' * 24 and binding.pose_reference_frame == 'odom'
    assert evidence['status'] == 'ACCREDITED_FOR_SESSION' and evidence['attribution'] == mb.ATTRIBUTION
    assert evidence['association']['position_error_m'] < 0.01 and evidence['movement_authorized'] is False
    assert mb.require_current(evidence, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT) == binding


@pytest.mark.parametrize('bad', ['two_publishers', 'other_node', 'gid_changed', 'status_missing', 'frame', 'clock',
                                 'few_samples', 'pose_far', 'yaw_far', 'template_config', 'no_bridge', 'boot',
                                 'gz_missing', 'short_gid'])
def test_motion_binding_rejects_names_alone_and_any_inconsistency(bad):
    value = raw()
    if bad == 'two_publishers': value['before'][ODOMETRY].append(dict(value['before'][ODOMETRY][0], gid='03' * 24))
    elif bad == 'other_node': value['before'][ODOMETRY][0]['node'] = 'impostor'
    elif bad == 'gid_changed': value['after'][ODOMETRY][0]['gid'] = '04' * 24
    elif bad == 'status_missing': value['after'][STATUS] = []
    elif bad == 'frame': value['samples'][1]['frame_id'] = 'map'
    elif bad == 'clock': value['samples'][2]['stamp_ns'] = value['samples'][1]['stamp_ns']
    elif bad == 'few_samples': value['samples'] = value['samples'][:2]
    elif bad == 'pose_far': value['samples'][-1]['position'][1] = -2.5
    elif bad == 'yaw_far': value['gz_model_pose_stdout'] = GZ.replace('1.566770', '1.766770')
    elif bad == 'template_config':
        value['bridge'][0]['configs'][0]['text'] = CONFIG.replace('/model/rover1/odometry', '/model/{{ robot_name }}/odometry')
    elif bad == 'no_bridge': value['bridge'] = []
    elif bad == 'boot': value['boot_id'] = 'other'
    elif bad == 'gz_missing': value['gz_model_pose_stdout'] = ''
    else:
        for side in ('before', 'after'): value[side][ODOMETRY][0]['gid'] = '01' * 16
    with pytest.raises(RoverControlError):
        assess(value)


@pytest.mark.parametrize('bad', ['lifecycle', 'started_at', 'boot', 'container', 'altered', 'status'])
def test_binding_evidence_cannot_be_reused_in_another_start_or_altered(bad):
    _, evidence = assess(raw())
    kwargs = {'lifecycle_id': LIFECYCLE, 'environment_execution': copy.deepcopy(EXECUTION), 'host_boot_id': BOOT}
    if bad == 'lifecycle': kwargs['lifecycle_id'] = '00000000-0000-4000-8000-000000000000'
    elif bad == 'started_at': kwargs['environment_execution']['container_started_at'] = '2026-11-04T08:00:00Z'
    elif bad == 'boot': kwargs['host_boot_id'] = 'other'
    elif bad == 'container': kwargs['environment_execution']['persistent_identity']['container_id'] = 'd' * 64
    elif bad == 'altered': evidence['samples'][0]['position'][0] = 1.0
    else: evidence['status'] = 'VERIFIED'
    with pytest.raises(RoverControlError):
        mb.require_current(evidence, **kwargs)


def test_parse_gz_pose_matches_the_observed_cli_output():
    assert mb.parse_gz_pose(GZ) == {'xyz_m': [-0.001244, -3.00045, 0.094909], 'rpy_rad': [0.0, 0.009537, 1.56677]}


def test_odom_goal_from_observed_start_offset_is_explicit_and_bounded():
    _, evidence = assess(raw())
    start = frame.start_pose(evidence)
    goal = frame.goal_from_start_offset(start, forward_m=2.0, left_m=0.0, max_distance_m=3.0)
    target = goal['target_in_rover_frame']
    # Heading ~ +89.77 deg: two metres forward moves almost purely along +y in odom.
    assert abs(target['x_m'] - (start['x_m'] + 2 * math.cos(start['heading_rad']))) < 1e-9
    assert target['y_m'] == pytest.approx(-1.0005524 + (2 * math.sin(start['heading_rad']) - 2), abs=1e-6)
    assert goal['distance_m'] == pytest.approx(2.0) and target['frame'] == 'odom'
    transform = goal['frame_transform']
    assert transform['status'] == 'VERIFIED' and transform['to_frame'] == 'odom' and len(transform['sha256']) == 64
    assert transform['start_evidence_sha256'] == evidence['evidence_sha256']
    NavigationGoal(x_m=target['x_m'], y_m=target['y_m'], yaw_rad=target['yaw_rad'], frame='odom', unit='m',
                   transform='IDENTITY_SAME_ACCREDITED_FRAME', tolerance_m=0.3, yaw_tolerance_rad=math.pi,
                   dwell_s=1.0, command_hz=5.0, timeout_s=120.0, no_progress_s=30.0, progress_m=0.05,
                   progress_rad=0.05, max_samples=256)


@pytest.mark.parametrize('kwargs', [{'forward_m': 5.0, 'left_m': 0.0}, {'forward_m': 0.0, 'left_m': 0.0},
                                    {'forward_m': float('nan'), 'left_m': 0.0}])
def test_odom_goal_rejects_out_of_bounds_or_invalid_offsets(kwargs):
    start = frame.start_pose(assess(raw())[1])
    with pytest.raises(RoverControlError):
        frame.goal_from_start_offset(start, max_distance_m=3.0, **kwargs)


def test_start_pose_requires_accredited_odom_evidence():
    _, evidence = assess(raw())
    with pytest.raises(RoverControlError):
        frame.start_pose({**evidence, 'status': 'OBSERVED'})


def trial():
    scope = policy.trial_scope(environment_execution=EXECUTION, host_boot_id=BOOT, lifecycle_id=LIFECYCLE,
                               profile='rover_only', mission_sha256='m' * 64, goal_sha256='g' * 64,
                               binding_evidence_sha256='e' * 64)
    current = {k: scope[k] for k in ('environment_execution', 'host_boot_id', 'lifecycle_id', 'profile',
                                     'binding_evidence_sha256')}
    return scope, current


def test_sitl_policy_is_inactive_by_default_even_with_exact_authorization():
    scope, current = trial()
    result = policy.evaluate(scope, policy.expected_authorization(scope), current)
    assert policy.SITL_TRIAL_POLICY_ENABLED is False
    assert result['status'] == 'BLOCKED' and result['reasons'] == ['SITL_TRIAL_POLICY_DISABLED']
    assert result['movement_authorized'] is False


@pytest.mark.parametrize('bad', ['authorization', 'boot', 'lifecycle', 'binding', 'profile', 'consumed'])
def test_sitl_policy_when_enabled_still_binds_every_fact(monkeypatch, bad):
    monkeypatch.setattr(policy, 'SITL_TRIAL_POLICY_ENABLED', True)
    scope, current = trial()
    authorization = policy.expected_authorization(scope)
    assert policy.evaluate(scope, authorization, current)['status'] == 'AUTHORIZED_FOR_THIS_SCOPE'
    if bad == 'authorization': authorization = f'{policy.AUTHORIZATION_PREFIX} ' + fingerprint({'other': 1})
    elif bad == 'boot': current['host_boot_id'] = 'other'
    elif bad == 'lifecycle': current['lifecycle_id'] = 'other'
    elif bad == 'binding': current['binding_evidence_sha256'] = 'f' * 64
    elif bad == 'profile': scope['profile'] = 'two_drones'; authorization = policy.expected_authorization(scope); current['profile'] = 'two_drones'
    else: current['trials_consumed'] = 1
    assert policy.evaluate(scope, authorization, current)['status'] == 'BLOCKED'
