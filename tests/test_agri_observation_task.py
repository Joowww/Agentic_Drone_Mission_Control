"""Drone observation -> validated rover task proposal, OFFLINE and SYNTHETIC end to end.

The aerial dependency is the conserved H2 record re-identified as the SYNTHETIC demo sequence
(tools.agri_ground_demo.synthetic_views, the same view the offline demo uses). The observation,
the drone-frame -> odom transformation and the rover start pose are SYNTHETIC test data. The
existing R1 preparation and ground coordinator are used unchanged. Nothing is admitted, reserved
or sent; no camera or detector exists.
"""
import copy
import math
from pathlib import Path

import pytest

from planning.artifact_store import sha256
from reporting import agri_scenario_summary as summary
from tools import agri_ground_coordinator as coordinator, agri_ground_demo as demo
from tools import agri_observation_task as obs_task, agri_scenario_flow as flow
from tools import rover_ground_executor as ground, vehicle_execution_lock as locks
from tools.rover_motion_binding import assess
from tools.rover_target_frame import start_pose
from tests.test_rover_ground_executor import setup  # noqa: F401  tmp LOCK_ROOT/RUN_ROOT
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE, NOW, raw

ROOT = Path(__file__).resolve().parents[1]
MISSION_FILE = ROOT / 'missions/examples/rover_first_navigation_sitl.json'
NOW_UTC = '2026-11-04T10:00:00+00:00'
DRONE_POINT = (2.0, 5.0)  # SYNTHETIC: where the card is, in drone_01's launch ENU frame


@pytest.fixture(scope='module')
def world():
    sequence, _ = flow.archived_sequence(flow.ARCHIVE)
    binding = summary._bind_expected(*summary.record_associations(flow.BINDING_RECORD))
    views = demo.synthetic_views(sequence, binding)
    evidence = assess(raw(), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                      now_wall_ns=NOW + 10**9)[1]
    start = start_pose(evidence)
    # SYNTHETIC transformation chosen so the card lands 1 m ahead of the rover's accredited start pose.
    gx = start['x_m'] + math.cos(start['heading_rad'])
    gy = start['y_m'] + math.sin(start['heading_rad'])
    transform = obs_task.synthetic_transform(from_frame='drone_launch_enu', tx_m=gx - DRONE_POINT[0],
                                             ty_m=gy - DRONE_POINT[1], yaw_rad=0.0, lifecycle_id=LIFECYCLE,
                                             pose_reference_sha256=start['pose_reference_sha256'])
    return {'views': views, 'binding': binding, 'start': start, 'transform': transform, 'goal': (gx, gy)}


def observation(world, **changes):
    value = {'schema': obs_task.OBSERVATION_SCHEMA, 'observation_id': 'obs-0001', 'drone_id': 'drone_01',
             'mission_id': world['binding']['drone_01']['mission_id'],
             'sequence_id': world['views']['base']['scenario']['sequence']['sequence_id'],
             'detection': {'type': 'COLOUR_CARD', 'colour': 'red', 'confidence': 0.93},
             'observed_at_utc': '2026-11-04T09:59:00+00:00',
             'source': {'kind': 'SYNTHETIC_TEST', 'note': 'no camera exists; hand-written observation'},
             'target': {'frame': 'drone_launch_enu', 'x': DRONE_POINT[0], 'y': DRONE_POINT[1]},
             'evidence': {'kind': 'SYNTHETIC_FIXTURE', 'sha256': sha256(b'synthetic card evidence 0001')}}
    for key, item in changes.items():
        if isinstance(item, dict) and isinstance(value.get(key), dict):
            value[key] = {**value[key], **item}
        else:
            value[key] = item
    return value


def context(world, **changes):
    value = {'lifecycle_id': LIFECYCLE, 'rover_start': world['start'], 'transform': world['transform'],
             'rover': {'vehicle_id': 'rover_01', 'available': True, 'reason': None},
             'mission': {'mission_id': world['binding']['drone_01']['mission_id'], 'drone_id': 'drone_01',
                         'sequence_id': world['views']['base']['scenario']['sequence']['sequence_id'],
                         'admits_ground_task_for': ['red', 'yellow'],
                         'area': {'min_x': -20.0, 'max_x': 20.0, 'min_y': -20.0, 'max_y': 20.0}}}
    value.update(changes)
    return value


POLICY = {'allow_synthetic': True}  # offline slice only; the module default refuses synthetic inputs


def validate(world, obs=None, ctx=None, ledger=None, now=NOW_UTC, policy=POLICY):
    return obs_task.validate_observation(obs or observation(world), context=ctx or context(world),
                                         ledger=ledger or obs_task.Ledger(), now_utc=now, policy=policy)


def flow_run(world, tmp_path, obs=None, *, executor=None, view='base', ledger=None, ctx=None, key='obs-r1'):
    return obs_task.observation_to_ground_task(
        obs or observation(world), view=world['views'][view], context=ctx or context(world),
        ledger=ledger or obs_task.Ledger(), executor=executor or demo.TestDoubleGroundExecutor(), now_utc=NOW_UTC,
        rover_mission={'path': str(MISSION_FILE.relative_to(ROOT)), 'sha256': sha256(MISSION_FILE.read_bytes())},
        execution_limits=obs_task.first_navigation_limits(), coordination_root=tmp_path / 'r1', request_key=key,
        policy=POLICY)


# ------------------------------------------------------------- valid cases --
@pytest.mark.parametrize('colour', ['red', 'yellow'])
def test_valid_card_becomes_a_task_pending_authorization(world, tmp_path, colour):
    executor = demo.TestDoubleGroundExecutor()
    result = flow_run(world, tmp_path, observation(world, detection={'colour': colour}), executor=executor)
    assert result['decision'] == 'ROVER_TASK_PENDING_AUTHORIZATION' and result['movement_authorized'] is False
    proposal = result['proposal']
    assert proposal['status'] == 'PROPOSED_PENDING_VALIDATION' and proposal['authorization'] == 'ABSENT'
    assert proposal['origin'] == 'SYNTHETIC' and proposal['colour'] == colour
    target = proposal['target_in_rover_frame']
    assert target['frame'] == 'odom' and (target['x_m'], target['y_m']) == pytest.approx(world['goal'])
    assert proposal['dependencies']['rover_pose_reference_sha256'] == world['start']['pose_reference_sha256']
    prepared = result['preparation']
    assert prepared['candidate']['target_in_rover_frame']['value'] == target
    assert prepared['stages']['authorization'] == 'ABSENT' and prepared['inputs_include_test_doubles']
    assert result['request']['reason'] == 'AUTHORIZATION_ABSENT_OR_MALFORMED'
    assert executor.admit_calls == 0 and not (tmp_path / 'r1' / 'records').exists()  # nothing admitted or written


def test_with_the_real_executor_adapter_the_task_is_not_even_eligible(world, tmp_path):
    result = flow_run(world, tmp_path, executor=coordinator.RoverGroundExecutorAdapter())
    assert result['decision'] == 'ROVER_TASK_PENDING_AUTHORIZATION'
    assert 'operational_rover_policy_enabled' in result['preparation']['blockers']
    assert result['request']['reason'] == 'NOT_ELIGIBLE'


# ------------------------------------------------------------------- rejections --
@pytest.mark.parametrize('changes, reason', [
    ({'detection': {'colour': 'blue'}}, 'COLOUR_UNKNOWN'),
    ({'detection': {'confidence': 0.5}}, 'CONFIDENCE_TOO_LOW'),
    ({'detection': {'confidence': 1.5}}, 'CONFIDENCE_INVALID'),
    ({'detection': {'type': 'PERSON'}}, 'DETECTION_TYPE_UNSUPPORTED'),
    ({'drone_id': ''}, 'MISSING_IDENTITY'),
    ({'evidence': {'sha256': None}}, 'EVIDENCE_DIGEST_MISSING'),
    ({'source': {'kind': 'DRONE_CAMERA_PIPELINE'}}, 'PERCEPTION_SOURCE_NOT_IMPLEMENTED'),
    ({'source': {'kind': 'SOMEONE'}}, 'PROVENANCE_UNKNOWN'),
    ({'observed_at_utc': '2026-11-04T09:00:00+00:00'}, 'OBSERVATION_STALE'),
    ({'observed_at_utc': '2026-11-04T10:05:00+00:00'}, 'OBSERVATION_FROM_THE_FUTURE'),
    ({'observed_at_utc': '2026-11-04T09:59:00'}, 'TIMESTAMP_INVALID'),
    ({'target': None}, 'TARGET_WITHOUT_USABLE_COORDINATES'),
    ({'target': {'x': float('nan')}}, 'TARGET_WITHOUT_USABLE_COORDINATES'),
    ({'target': {'frame': 'map'}}, 'FRAME_UNKNOWN'),
    ({'target': {'frame': 'camera_image_px', 'x': 320.0, 'y': 240.0}}, 'CAMERA_COORDINATES_ARE_NOT_NAVIGATION_COORDINATES'),
    ({'target': {'frame': 'wgs84', 'x': 41.275, 'y': 1.987}}, 'TRANSFORM_FRAMES_DIFFER'),  # no GNSS->odom exists
    ({'mission_id': 'another-mission'}, 'OBSERVATION_NOT_FROM_THE_AUTHORIZED_DRONE_MISSION'),
    ({'target': {'x': 30.0}}, 'TARGET_OUTSIDE_MISSION_AREA'),
])
def test_invalid_observations_are_rejected_with_their_reason(world, changes, reason):
    result = validate(world, observation(world, **changes))
    assert result['status'] == 'REJECTED' and reason in result['reasons'] and result['goal'] is None


def test_colour_alone_neither_authorizes_nor_locates(world):
    result = validate(world, observation(world, target=None))
    assert result['status'] == 'REJECTED' and result['movement_authorized'] is False


def test_synthetic_inputs_are_refused_unless_explicitly_allowed(world):
    result = validate(world, policy={})
    assert {'SYNTHETIC_OBSERVATION_NOT_ALLOWED', 'SYNTHETIC_TRANSFORM_NOT_ALLOWED'} <= set(result['reasons'])


def test_mission_that_does_not_admit_the_task(world):
    ctx = context(world)
    ctx['mission'] = {**ctx['mission'], 'admits_ground_task_for': ['red']}
    assert 'MISSION_DOES_NOT_ADMIT_THIS_TASK' in validate(world, observation(world, detection={'colour': 'yellow'}), ctx)['reasons']


@pytest.mark.parametrize('rover, reason', [({'vehicle_id': 'rover_99', 'available': True}, 'ROVER_UNKNOWN'),
                                           ({'vehicle_id': 'rover_01', 'available': False}, 'ROVER_NOT_AVAILABLE')])
def test_rover_missing_or_unavailable(world, rover, reason):
    assert reason in validate(world, ctx=context(world, rover=rover))['reasons']


def test_rover_availability_reads_the_reservation_store_only(setup):
    assert obs_task.rover_availability()['available'] is True and obs_task.rover_availability('rover_99')['available'] is False
    locks.reserve('someone-else', 'test', 'v3')
    assert obs_task.rover_availability()['available'] is False


@pytest.mark.parametrize('mutate, reason', [
    (lambda t: None, 'TRANSFORM_ABSENT'),
    (lambda t: {**t, 'lifecycle_id': 'older-start'}, 'TRANSFORM_DIGEST_INVALID'),
    (lambda t: obs_task.synthetic_transform(from_frame='drone_launch_enu', tx_m=t['tx_m'], ty_m=t['ty_m'], yaw_rad=0.0,
                                            lifecycle_id='older-start', pose_reference_sha256=t['pose_reference_sha256']),
     'TRANSFORM_NOT_OF_THIS_LIFECYCLE'),
    (lambda t: obs_task.synthetic_transform(from_frame='drone_launch_enu', tx_m=t['tx_m'], ty_m=t['ty_m'], yaw_rad=0.0,
                                            lifecycle_id=LIFECYCLE, pose_reference_sha256='0' * 64),
     'TRANSFORM_NOT_BOUND_TO_THE_ACCREDITED_ROVER_POSE'),
    (lambda t: {**{k: v for k, v in t.items() if k != 'sha256'}, 'source': 'CALIBRATION',
                'sha256': obs_task.transform_digest({**t, 'source': 'CALIBRATION'})}, 'TRANSFORM_PRODUCER_NOT_IMPLEMENTED'),
    (lambda t: {**{k: v for k, v in t.items() if k != 'sha256'}, 'status': 'DECLARED',
                'sha256': obs_task.transform_digest({**t, 'status': 'DECLARED'})}, 'TRANSFORM_NOT_VERIFIED'),
])
def test_transformation_must_be_present_current_verified_and_bound(world, mutate, reason):
    assert reason in validate(world, ctx=context(world, transform=mutate(world['transform'])))['reasons']


def test_target_beyond_the_rover_bound_is_rejected(world):
    far = obs_task.synthetic_transform(from_frame='drone_launch_enu', tx_m=world['transform']['tx_m'] + 5.0,
                                       ty_m=world['transform']['ty_m'], yaw_rad=0.0, lifecycle_id=LIFECYCLE,
                                       pose_reference_sha256=world['start']['pose_reference_sha256'])
    result = validate(world, ctx=context(world, transform=far))
    assert result['status'] == 'REJECTED' and result['reasons'][0].startswith('TARGET_OUT_OF_ROVER_BOUNDS')


# ------------------------------------------------- duplicates and later changes --
def test_duplicate_changed_target_and_reused_evidence(world, tmp_path):
    ledger = obs_task.Ledger(tmp_path / 'ledger')
    assert flow_run(world, tmp_path, ledger=ledger)['decision'] == 'ROVER_TASK_PENDING_AUTHORIZATION'
    again = obs_task.Ledger(tmp_path / 'ledger')  # persisted: a restart remembers
    assert 'DUPLICATE_OBSERVATION' in validate(world, ledger=again)['reasons']
    moved = observation(world, target={'x': 2.5})
    assert 'OBSERVATION_CHANGED_AFTER_RECORD' in validate(world, moved, ledger=again)['reasons']
    reused = observation(world, observation_id='obs-0002')
    assert 'EVIDENCE_REUSED_BY_ANOTHER_OBSERVATION' in validate(world, reused, ledger=again)['reasons']


def test_rejected_observation_is_not_recorded(world, tmp_path):
    ledger = obs_task.Ledger()
    assert flow_run(world, tmp_path, observation(world, detection={'confidence': 0.1}), ledger=ledger)['decision'] == 'OBSERVATION_REJECTED'
    assert ledger.observations == {}


# --------------------------------------------------------- authority and execution --
def test_a_proposal_without_authorization_is_never_admitted(world, tmp_path):
    executor = demo.TestDoubleGroundExecutor()
    result = flow_run(world, tmp_path, executor=executor)
    blocked = coordinator.request(tmp_path / 'r1b', 'obs-r1-b', world['views']['base'], result['proposal']['r1_inputs'],
                                  None, executor)
    assert blocked['request_status'] == 'BLOCKED' and blocked['executor_called'] is False
    assert blocked['admission_created'] is False and executor.admit_calls == 0


def test_direct_execution_of_the_proposal_is_refused(world, tmp_path, setup):
    result = flow_run(world, tmp_path)
    request = coordinator.navigation_request(result['preparation']['candidate'])
    setup[0].write_bytes(MISSION_FILE.read_bytes())
    # As built today the R1 visit proposal (global 120 s) exceeds the first-navigation limit (60 s): the
    # executor's own schema refuses it before anything else (finding for the R1/first-navigation alignment).
    with pytest.raises(ValueError, match='Navigation budget exceeds declared limits'):
        ground.admit_ground_trial(setup[0], 'direct-from-observation', request, None)
    aligned = {**request, 'goal': {**request['goal'], 'timeout_s': 45.0, 'no_progress_s': 10.0}}
    with pytest.raises(ValueError, match='authorization'):  # and without an operator authorization, never
        ground.admit_ground_trial(setup[0], 'direct-from-observation', aligned, None)
    assert locks.restriction('v3') is None  # nothing reserved


def test_the_task_is_prepared_for_the_existing_validation(world, tmp_path):
    prepared = flow_run(world, tmp_path)['preparation']
    assert prepared['stages'] == {'dependency': 'MET', 'eligibility': 'ELIGIBLE', 'authorization': 'ABSENT',
                                  'admission': 'NOT_REQUESTED', 'execution': 'NOT_STARTED'}
    candidate = prepared['candidate']
    assert candidate['frame_transform']['value']['status'] == 'VERIFIED'
    assert candidate['frame_transform']['source'].startswith('TEST_DOUBLE')  # labelled synthetic, not accredited


def test_llm_proposal_is_checked_against_the_deterministic_derivation(world, tmp_path):
    proposal = flow_run(world, tmp_path)['proposal']
    same = {k: copy.deepcopy(proposal[k]) for k in ('observation_id', 'colour', 'target_in_rover_frame')}
    assert obs_task.check_proposed_task(same, proposal)['status'] == 'MATCHES_DERIVATION'
    nudged = {**same, 'target_in_rover_frame': {**same['target_in_rover_frame'], 'x_m': same['target_in_rover_frame']['x_m'] + 0.3}}
    assert obs_task.check_proposed_task(nudged, proposal) == {'status': 'REJECTED', 'differences': ['target_in_rover_frame'],
                                                              'decided_by': 'DETERMINISTIC_DERIVATION'}


# --------------------------------------------------------------- coordination --
def test_coordination_failure_yields_no_task(world, tmp_path):
    class Unreachable(demo.TestDoubleGroundExecutor):
        def facts(self):
            raise RuntimeError('executor facts unavailable')
    result = flow_run(world, tmp_path, executor=Unreachable())
    assert result['decision'] == 'COORDINATION_FAILED' and 'request' not in result


@pytest.mark.parametrize('view', ['first_drone_failed', 'poi_not_reached'])
def test_unmet_aerial_dependency_yields_no_task(world, tmp_path, view):
    result = flow_run(world, tmp_path, view=view)
    assert result['decision'] == 'NO_GROUND_TASK' and result['preparation']['candidate'] is None


# ------------------------------------------------------------ reproducible example --
def test_example_end_to_end_writes_input_validations_decision_result_and_evidence(tmp_path):
    import json
    import subprocess
    import sys
    out = tmp_path / 'example'
    run = subprocess.run([sys.executable, '-m', 'tools.agri_observation_task', 'example', '--out', str(out)],
                         cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    assert 'DECISION: ROVER_TASK_PENDING_AUTHORIZATION · movement_authorized: False' in run.stdout
    read = lambda name: json.loads((out / name).read_text())
    assert read('input_observation.json')['source']['kind'] == 'SYNTHETIC_TEST'                 # the input
    assert read('validation.json')['status'] == 'ACCEPTED' and read('validation.json')['reasons'] == []  # the checks
    decision = read('decision.json')                                                            # the decision
    assert [s['step'] for s in decision['trace']] == ['validate', 'propose', 'prepare', 'request_without_authorization']
    assert decision['origin'] == 'SYNTHETIC' and decision['executor_admit_calls'] == 0
    assert read('proposal.json')['target_in_rover_frame'] == {'x_m': 1.0, 'y_m': 0.0, 'frame': 'odom'}  # the result
    assert read('request.json')['request_status'] == 'BLOCKED'
    assert read('preparation_real_executor_facts.json')['blockers'] == ['operational_rover_policy_enabled']
    assert read('input_context.json')['rover_start']['pose_reference_sha256'] == sha256(b'SYNTHETIC example pose reference')
    for line in (out / 'SHA256SUMS').read_text().splitlines():                                  # the evidence
        digest, name = line.split('  ')
        assert sha256((out / name).read_bytes()) == digest
    assert not (out / 'r1' / 'records').exists()  # the coordinator recorded no admission intent
    again = subprocess.run([sys.executable, '-m', 'tools.agri_observation_task', 'example', '--out', str(out)],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert again.returncode != 0 and 'NEW directory' in again.stderr  # evidence is never overwritten
