"""Drone observation -> VALIDATED ground-task proposal for the rover, offline; never a permission to move.

Vertical slice of the agricultural scenario: a drone reports a red or yellow card; this module
checks the observation (identity, provenance, age, coherence, frame, accredited transformation,
mission, rover availability, bounds, duplicates) and, only if everything holds, turns it into the
R1 inputs that the EXISTING ground coordination already evaluates
(reporting.agri_scenario_summary.prepare_ground_task through tools.agri_ground_coordinator).
The coordinator then still needs an operator authorization, and the executor its own gates.

What does NOT exist and is never assumed here:
- visual perception: no camera or detector runs. Only SYNTHETIC observations are accepted; a
  claimed camera pipeline is refused as NOT_IMPLEMENTED;
- a camera-to-ground transformation: pixel coordinates are never navigation coordinates;
- an accredited drone-frame -> rover-odom transformation: none is produced in this repository.
  Only a SYNTHETIC one (labelled as such, bound to the rover's accredited pose reference) is
  accepted, and only when the caller allows synthetic inputs; the result is then marked TEST_DOUBLE.
- GNSS: WGS84 positions need the same accredited transformation; indoors none is available.

An LLM may PROPOSE a task (check_proposed_task); the deterministic derivation decides.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import math
from pathlib import Path

from planning.artifact_store import fingerprint
from tools.rover_control import RoverControlError, transform_ground_point
from tools.rover_target_frame import goal_from_declared_odom

OBSERVATION_SCHEMA = 'tfg.agri.drone-observation/1'
TRANSFORM_SCHEMA = 'tfg.agri.frame-transform/1'
PROPOSAL_SCHEMA = 'tfg.agri.ground-task-proposal/1'
DETECTION_TYPE = 'COLOUR_CARD'
COLOURS = ('red', 'yellow')
SOURCES = {'SYNTHETIC_TEST': 'SYNTHETIC', 'DRONE_CAMERA_PIPELINE': 'NOT_IMPLEMENTED'}
# Frames a drone observation may use; only an accredited transformation can take one to rover odom.
FRAMES = {'drone_launch_enu': 'NEEDS_ACCREDITED_TRANSFORM', 'wgs84': 'NEEDS_ACCREDITED_TRANSFORM',
          'camera_image_px': 'NEVER_NAVIGABLE'}
ROVER_FRAME = 'odom'
POLICY = {'min_confidence': 0.8, 'max_age_s': 300.0, 'max_future_s': 2.0, 'ground_tolerance_m': 0.25,
          'max_distance_m': 1.5, 'rover_vehicle': 'rover_01', 'allow_synthetic': False}
OBSERVATION_KEYS = {'schema', 'observation_id', 'drone_id', 'mission_id', 'sequence_id', 'detection',
                    'observed_at_utc', 'source', 'target', 'evidence'}


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _utc(text):
    try:
        value = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo is not None else None


def transform_digest(transform):
    return fingerprint({k: v for k, v in transform.items() if k != 'sha256'})


def synthetic_transform(*, from_frame, tx_m, ty_m, yaw_rad, lifecycle_id, pose_reference_sha256):
    """A SYNTHETIC SE(2) drone-frame -> rover-odom transformation, for offline tests and the example only."""
    value = {'schema': TRANSFORM_SCHEMA, 'from_frame': from_frame, 'to_frame': ROVER_FRAME, 'method': 'SE2',
             'tx_m': float(tx_m), 'ty_m': float(ty_m), 'yaw_rad': float(yaw_rad), 'status': 'VERIFIED',
             'source': 'SYNTHETIC_TEST', 'lifecycle_id': lifecycle_id, 'pose_reference_sha256': pose_reference_sha256}
    return {**value, 'sha256': transform_digest(value)}


class Ledger:
    """Observation ids and evidence digests already used; in memory, or persisted under root."""

    def __init__(self, root: Path | None = None):
        self.root, self.observations, self.evidence = (Path(root) if root else None), {}, {}
        if self.root and (self.root / 'ledger.json').is_file():
            import json
            saved = json.loads((self.root / 'ledger.json').read_text(encoding='utf-8'))
            self.observations, self.evidence = saved['observations'], saved['evidence']

    def problems(self, observation_id, observation_sha256, evidence_sha256):
        known = self.observations.get(observation_id)
        if known is not None:
            return ['DUPLICATE_OBSERVATION' if known == observation_sha256 else 'OBSERVATION_CHANGED_AFTER_RECORD']
        owner = self.evidence.get(evidence_sha256)
        return ['EVIDENCE_REUSED_BY_ANOTHER_OBSERVATION'] if owner not in (None, observation_id) else []

    def record(self, observation_id, observation_sha256, evidence_sha256):
        self.observations[observation_id], self.evidence[evidence_sha256] = observation_sha256, observation_id
        if self.root:
            from tools.vehicle_execution_lock import atomic_json, file_mutex
            self.root.mkdir(parents=True, exist_ok=True)
            with file_mutex(self.root / 'ledger.lock'):
                atomic_json(self.root / 'ledger.json', {'observations': self.observations, 'evidence': self.evidence})


def rover_availability(vehicle_id='rover_01'):
    """Read-only: the rover exists in this deployment and no reservation holds v3. Not a readiness check."""
    from tools import vehicle_execution_lock as locks
    if vehicle_id != 'rover_01':
        return {'vehicle_id': vehicle_id, 'available': False, 'reason': 'UNKNOWN_VEHICLE'}
    held = locks.restriction('v3')
    return {'vehicle_id': vehicle_id, 'available': held is None,
            'reason': None if held is None else 'V3_RESERVED_BY_' + str(held.get('owner_id'))}


def _transform_problems(transform, frame, context, policy):
    if transform is None:
        return ['TRANSFORM_ABSENT']
    problems = []
    if transform.get('schema') != TRANSFORM_SCHEMA or transform.get('sha256') != transform_digest(transform):
        problems.append('TRANSFORM_DIGEST_INVALID')
    if transform.get('status') != 'VERIFIED' or transform.get('method') != 'SE2':
        problems.append('TRANSFORM_NOT_VERIFIED')
    if transform.get('from_frame') != frame or transform.get('to_frame') != ROVER_FRAME:
        problems.append('TRANSFORM_FRAMES_DIFFER')
    if transform.get('lifecycle_id') != context.get('lifecycle_id'):
        problems.append('TRANSFORM_NOT_OF_THIS_LIFECYCLE')
    start = context.get('rover_start') or {}
    if transform.get('pose_reference_sha256') != start.get('pose_reference_sha256'):
        problems.append('TRANSFORM_NOT_BOUND_TO_THE_ACCREDITED_ROVER_POSE')
    if transform.get('source') == 'SYNTHETIC_TEST':
        if not policy['allow_synthetic']:
            problems.append('SYNTHETIC_TRANSFORM_NOT_ALLOWED')
    else:
        problems.append('TRANSFORM_PRODUCER_NOT_IMPLEMENTED')  # no accredited calibration exists yet
    if not all(_finite(transform.get(k)) for k in ('tx_m', 'ty_m', 'yaw_rad')):
        problems.append('TRANSFORM_VALUES_INVALID')
    return problems


def validate_observation(observation, *, context, ledger, now_utc, policy=None):
    """Every reason found, not just the first. ACCEPTED only with none; nothing is written here."""
    policy = {**POLICY, **(policy or {})}
    reasons = []
    obs = observation if isinstance(observation, dict) else {}
    if set(obs) != OBSERVATION_KEYS or obs.get('schema') != OBSERVATION_SCHEMA:
        reasons.append('OBSERVATION_SHAPE_INVALID')
    if not all(isinstance(obs.get(k), str) and obs.get(k) for k in ('observation_id', 'drone_id', 'mission_id', 'sequence_id')):
        reasons.append('MISSING_IDENTITY')
    source, evidence = obs.get('source') or {}, obs.get('evidence') or {}
    kind = SOURCES.get(source.get('kind'))
    if kind is None:
        reasons.append('PROVENANCE_UNKNOWN')
    elif kind == 'NOT_IMPLEMENTED':
        reasons.append('PERCEPTION_SOURCE_NOT_IMPLEMENTED')
    elif not policy['allow_synthetic']:
        reasons.append('SYNTHETIC_OBSERVATION_NOT_ALLOWED')
    evidence_sha = evidence.get('sha256')
    if not (isinstance(evidence_sha, str) and len(evidence_sha) == 64) or not evidence.get('kind'):
        reasons.append('EVIDENCE_DIGEST_MISSING')
    observed, now = _utc(obs.get('observed_at_utc')), _utc(now_utc)
    if observed is None or now is None:
        reasons.append('TIMESTAMP_INVALID')
    else:
        age = (now - observed).total_seconds()
        if age > policy['max_age_s']:
            reasons.append('OBSERVATION_STALE')
        if age < -policy['max_future_s']:
            reasons.append('OBSERVATION_FROM_THE_FUTURE')
    detection = obs.get('detection') or {}
    if detection.get('type') != DETECTION_TYPE:
        reasons.append('DETECTION_TYPE_UNSUPPORTED')
    if detection.get('colour') not in COLOURS:
        reasons.append('COLOUR_UNKNOWN')
    confidence = detection.get('confidence')
    if not _finite(confidence) or not 0 <= confidence <= 1:
        reasons.append('CONFIDENCE_INVALID')
    elif confidence < policy['min_confidence']:
        reasons.append('CONFIDENCE_TOO_LOW')
    target = obs.get('target')
    frame = (target or {}).get('frame')
    if not isinstance(target, dict) or not all(_finite(target.get(k)) for k in ('x', 'y')):
        reasons.append('TARGET_WITHOUT_USABLE_COORDINATES')
    elif frame not in FRAMES:
        reasons.append('FRAME_UNKNOWN')
    elif FRAMES[frame] == 'NEVER_NAVIGABLE':
        reasons.append('CAMERA_COORDINATES_ARE_NOT_NAVIGATION_COORDINATES')
    else:
        reasons += _transform_problems(context.get('transform'), frame, context, policy)
    mission = context.get('mission') or {}
    if (obs.get('mission_id') != mission.get('mission_id') or obs.get('drone_id') != mission.get('drone_id')
            or obs.get('sequence_id') != mission.get('sequence_id')):
        reasons.append('OBSERVATION_NOT_FROM_THE_AUTHORIZED_DRONE_MISSION')
    elif detection.get('colour') not in (mission.get('admits_ground_task_for') or ()):
        reasons.append('MISSION_DOES_NOT_ADMIT_THIS_TASK')
    rover = context.get('rover') or {}
    if rover.get('vehicle_id') != policy['rover_vehicle']:
        reasons.append('ROVER_UNKNOWN')
    elif rover.get('available') is not True:
        reasons.append('ROVER_NOT_AVAILABLE')
    area = mission.get('area')  # in the observation frame, declared with the drone mission
    if (area and isinstance(target, dict) and frame in FRAMES and FRAMES[frame] != 'NEVER_NAVIGABLE'
            and all(_finite(target.get(k)) for k in ('x', 'y'))
            and not (area['min_x'] <= target['x'] <= area['max_x'] and area['min_y'] <= target['y'] <= area['max_y'])):
        reasons.append('TARGET_OUTSIDE_MISSION_AREA')
    try:
        observation_sha = fingerprint(obs)
    except (TypeError, ValueError):  # NaN/inf or non-JSON content: not an observation that can be bound
        observation_sha = None
        reasons.append('OBSERVATION_NOT_SERIALIZABLE')
    if observation_sha and isinstance(obs.get('observation_id'), str) and evidence_sha:
        reasons += ledger.problems(obs['observation_id'], observation_sha, evidence_sha)
    goal = None
    if not reasons:
        try:
            goal = target_goal(target, context, policy)
        except RoverControlError as exc:
            reasons.append('TARGET_OUT_OF_ROVER_BOUNDS: ' + str(exc))
    return {'status': 'REJECTED' if reasons else 'ACCEPTED', 'reasons': reasons, 'observation_sha256': observation_sha,
            'goal': goal, 'synthetic': kind == 'SYNTHETIC', 'movement_authorized': False}


def target_goal(target, context, policy):
    """drone frame -> rover odom with the checked transformation, then bounded by the accredited start pose."""
    t = context['transform']
    x, y = transform_ground_point((target['x'], target['y']), (t['tx_m'], t['ty_m']), t['yaw_rad'])
    start = context['rover_start']
    return goal_from_declared_odom(start, x_m=x, y_m=y, yaw_rad=start['heading_rad'],
                                   max_distance_m=policy['max_distance_m'])


def propose_ground_task(observation, validation, *, context, rover_mission, execution_limits, policy=None):
    """A proposal in the R1 input contract. Status PROPOSED_PENDING_VALIDATION; authorization ABSENT."""
    if validation['status'] != 'ACCEPTED':
        raise RoverControlError('Only an ACCEPTED observation can become a proposal')
    policy = {**POLICY, **(policy or {})}
    goal, transform = validation['goal'], context['transform']
    label = 'TEST_DOUBLE synthetic ' if validation['synthetic'] else ''
    source = f"{label}drone observation {observation['observation_id']} ({validation['observation_sha256'][:12]})"
    target = {'x_m': goal['target_in_rover_frame']['x_m'], 'y_m': goal['target_in_rover_frame']['y_m'], 'frame': ROVER_FRAME}
    inputs = {
        'target_in_rover_frame': {'value': target, 'source': source},
        'ground_tolerance_m': {'value': policy['ground_tolerance_m'], 'source': label + 'policy'},
        'rover_mission': {'value': dict(rover_mission), 'source': label + 'rover mission file'},
        'completion_evidence': {'value': 'rover_01 odometry (/rover1/odometry, odom) within tolerance, stop and disarm '
                                         'observed by the executor', 'source': label + 'policy'},
        'frame_transform': {'value': {'status': transform['status'], 'sha256': transform['sha256'],
                                      'from_frame': transform['from_frame'], 'to_frame': transform['to_frame']},
                            'source': label + 'transform ' + transform['source']},
        'execution_limits': {'value': execution_limits, 'source': label + 'derived limits'},
    }
    body = {'schema': PROPOSAL_SCHEMA, 'status': 'PROPOSED_PENDING_VALIDATION', 'task': 'R1',
            'observation_id': observation['observation_id'], 'observation_sha256': validation['observation_sha256'],
            'evidence_sha256': observation['evidence']['sha256'], 'colour': observation['detection']['colour'],
            'origin': 'SYNTHETIC' if validation['synthetic'] else 'OBSERVED',
            'target_in_rover_frame': target, 'goal_sha256': goal['goal_sha256'],
            'dependencies': {'transform_sha256': transform['sha256'], 'transform_source': transform['source'],
                             'rover_pose_reference_sha256': goal['frame_transform']['sha256'],
                             'lifecycle_id': context.get('lifecycle_id')},
            'limits': execution_limits, 'authorization': 'ABSENT', 'admission': 'NOT_REQUESTED',
            'movement_authorized': False, 'r1_inputs': inputs}
    return {**body, 'proposal_sha256': fingerprint(body)}


def check_proposed_task(proposed, proposal):
    """An LLM-proposed task is accepted only if it equals the deterministic derivation."""
    differences = [k for k in ('observation_id', 'colour', 'target_in_rover_frame')
                   if (proposed or {}).get(k) != proposal.get(k)]
    return {'status': 'MATCHES_DERIVATION' if not differences else 'REJECTED',
            'differences': differences, 'decided_by': 'DETERMINISTIC_DERIVATION'}


def observation_to_ground_task(observation, *, view, context, ledger, executor, now_utc, rover_mission,
                               execution_limits, coordination_root, request_key, policy=None):
    """The whole slice: validate -> propose -> existing R1 preparation -> coordinator request WITHOUT authorization.

    The request is expected to be BLOCKED (authorization absent): nothing is admitted, reserved or sent.
    """
    from tools import agri_ground_coordinator as coordinator
    validation = validate_observation(observation, context=context, ledger=ledger, now_utc=now_utc, policy=policy)
    trace = [{'step': 'validate', 'status': validation['status'], 'reasons': validation['reasons']}]
    if validation['status'] != 'ACCEPTED':
        return {'decision': 'OBSERVATION_REJECTED', 'validation': validation, 'proposal': None, 'trace': trace,
                'movement_authorized': False}
    proposal = propose_ground_task(observation, validation, context=context, rover_mission=rover_mission,
                                   execution_limits=execution_limits, policy=policy)
    ledger.record(observation['observation_id'], validation['observation_sha256'], observation['evidence']['sha256'])
    trace.append({'step': 'propose', 'status': proposal['status'], 'proposal_sha256': proposal['proposal_sha256']})
    try:
        prepared = coordinator.prepare(view, proposal['r1_inputs'], executor)
    except Exception as exc:  # the coordination stage failed: no task exists, nothing is retried
        trace.append({'step': 'prepare', 'status': 'COORDINATION_FAILED', 'reason': type(exc).__name__})
        return {'decision': 'COORDINATION_FAILED', 'validation': validation, 'proposal': proposal, 'trace': trace,
                'movement_authorized': False}
    candidate = prepared['candidate']
    consistent = bool(candidate) and candidate['target_in_rover_frame']['value'] == proposal['target_in_rover_frame']
    trace.append({'step': 'prepare', 'status': prepared['stages'], 'blockers': prepared['blockers'],
                  'candidate_sha256': prepared['candidate_sha256'], 'candidate_matches_proposal': consistent,
                  'inputs_include_test_doubles': prepared['inputs_include_test_doubles']})
    if not consistent:
        return {'decision': 'NO_GROUND_TASK', 'validation': validation, 'proposal': proposal, 'preparation': prepared,
                'trace': trace, 'movement_authorized': False}
    request = coordinator.request(Path(coordination_root), request_key, view, proposal['r1_inputs'], None, executor)
    trace.append({'step': 'request_without_authorization', 'status': request.get('request_status'),
                  'reason': request.get('reason'), 'executor_called': request.get('executor_called')})
    decision = ('ROVER_TASK_PENDING_AUTHORIZATION' if request.get('request_status') == 'BLOCKED'
                and request.get('executor_called') is False else 'UNEXPECTED_REQUEST_OUTCOME')
    return {'decision': decision, 'validation': validation, 'proposal': proposal, 'preparation': prepared,
            'request': request, 'trace': trace, 'movement_authorized': False}


def first_navigation_limits():
    """R1 execution_limits from the first-navigation contract (rover_limits + controller)."""
    from tools import rover_first_navigation as nav
    return {'rover_limits': asdict(nav.LIMITS),
            'controller': {'yaw_rad': 0.0, 'yaw_tolerance_rad': nav.GOAL_PARAMETERS['yaw_tolerance_rad'],
                           'command_hz': nav.GOAL_PARAMETERS['command_hz'], 'max_samples': nav.GOAL_PARAMETERS['max_samples'],
                           'progress_rad': nav.GOAL_PARAMETERS['progress_rad']}}


# -- reproducible offline example ----------------------------------------------------
EXAMPLE_LIFECYCLE = 'SYNTHETIC-EXAMPLE-LIFECYCLE'


def example_inputs(now_utc):
    """SYNTHETIC inputs only: own origin pose, own transformation and observation; nothing from a past session."""
    from datetime import timedelta
    from planning.artifact_store import sha256
    start = {'x_m': 0.0, 'y_m': 0.0, 'heading_rad': 0.0, 'frame': ROVER_FRAME, 'stamp_ns': 0,
             'evidence_sha256': sha256(b'SYNTHETIC example: no MotionBinding evidence'),
             'pose_reference_sha256': sha256(b'SYNTHETIC example pose reference')}
    transform = synthetic_transform(from_frame='drone_launch_enu', tx_m=-1.0, ty_m=-4.0, yaw_rad=0.0,
                                    lifecycle_id=EXAMPLE_LIFECYCLE, pose_reference_sha256=start['pose_reference_sha256'])
    observed = (datetime.fromisoformat(now_utc) - timedelta(seconds=30)).isoformat()
    return start, transform, observed


def example_case(now_utc):
    """The example's SYNTHETIC inputs: aerial view, red-card observation, context and rover mission (no I/O writes)."""
    from planning.artifact_store import sha256
    from reporting import agri_scenario_summary as summary
    from tools import agri_ground_demo as demo, agri_scenario_flow as flow
    sequence, _ = flow.archived_sequence(flow.ARCHIVE)
    binding = summary._bind_expected(*summary.record_associations(flow.BINDING_RECORD))
    view = demo.synthetic_views(sequence, binding)['base']  # SYNTHETIC re-identified copy of the H2 record
    start, transform, observed = example_inputs(now_utc)
    mission_id, sequence_id = binding['drone_01']['mission_id'], view['scenario']['sequence']['sequence_id']
    observation = {'schema': OBSERVATION_SCHEMA, 'observation_id': 'example-red-card-001', 'drone_id': 'drone_01',
                   'mission_id': mission_id, 'sequence_id': sequence_id,
                   'detection': {'type': DETECTION_TYPE, 'colour': 'red', 'confidence': 0.9},
                   'observed_at_utc': observed,
                   'source': {'kind': 'SYNTHETIC_TEST', 'note': 'hand-written; no camera or detector exists'},
                   'target': {'frame': 'drone_launch_enu', 'x': 2.0, 'y': 4.0},
                   'evidence': {'kind': 'SYNTHETIC_FIXTURE', 'sha256': sha256(b'SYNTHETIC example red card')}}
    context = {'lifecycle_id': EXAMPLE_LIFECYCLE, 'rover_start': start, 'transform': transform,
               'rover': {'vehicle_id': 'rover_01', 'available': True, 'reason': 'SYNTHETIC: not read from reservations'},
               'mission': {'mission_id': mission_id, 'drone_id': 'drone_01', 'sequence_id': sequence_id,
                           'admits_ground_task_for': list(COLOURS),
                           'area': {'min_x': -20.0, 'max_x': 20.0, 'min_y': -20.0, 'max_y': 20.0}}}
    mission_file = Path(__file__).resolve().parents[1] / 'missions/examples/rover_first_navigation_sitl.json'
    return {'view': view, 'observation': observation, 'context': context, 'now_utc': now_utc,
            'rover_mission': {'path': 'missions/examples/rover_first_navigation_sitl.json',
                              'sha256': sha256(mission_file.read_bytes())}}


def run_example(out_dir: Path, *, now_utc=None, case=None):
    """DRON_01 -> synthetic red-card observation -> validations -> proposal -> coordinator -> pending authorization."""
    import json
    from datetime import timezone
    from planning.artifact_store import sha256
    from tools import agri_ground_coordinator as coordinator, agri_ground_demo as demo
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f'{out_dir} exists and is not empty: use a NEW directory')
    out_dir.mkdir(parents=True, exist_ok=True)
    case = case or example_case(now_utc or datetime.now(timezone.utc).isoformat())
    view, observation, context, now_utc = case['view'], case['observation'], case['context'], case['now_utc']
    executor = demo.TestDoubleGroundExecutor()
    result = observation_to_ground_task(
        observation, view=view, context=context, ledger=Ledger(out_dir / 'ledger'), executor=executor,
        now_utc=now_utc, rover_mission=case['rover_mission'],
        execution_limits=first_navigation_limits(), coordination_root=out_dir / 'r1', request_key='example-red-card-r1',
        policy={'allow_synthetic': True})
    real = coordinator.prepare(view, result['proposal']['r1_inputs'], coordinator.RoverGroundExecutorAdapter()) \
        if result['proposal'] else None
    files = {'input_observation.json': observation, 'input_context.json': context,
             'validation.json': result['validation'], 'proposal.json': result['proposal'],
             'preparation_test_double.json': result.get('preparation'), 'request.json': result.get('request'),
             'preparation_real_executor_facts.json': real,
             'decision.json': {'decision': result['decision'], 'trace': result['trace'], 'now_utc': now_utc,
                               'origin': 'SYNTHETIC', 'movement_authorized': False,
                               'executor_admit_calls': executor.admit_calls, 'executor_kind': executor.kind,
                               'not_claimed': ['visual detection', 'accredited transformation', 'joint drone-rover run',
                                               'any rover movement']}}
    for name, value in files.items():
        (out_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    manifest = {name: sha256((out_dir / name).read_bytes()) for name in sorted(files)}
    (out_dir / 'SHA256SUMS').write_text(''.join(f'{h}  {n}\n' for n, h in manifest.items()), encoding='utf-8')
    return result, real


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Offline SYNTHETIC drone observation -> rover task pending authorization')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('example', help='red-card example; writes its evidence to a NEW directory').add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result, real = run_example(args.out)
    print('[SYNTHETIC] drone_01 observation example-red-card-001 (red card, no camera)')
    for step in result['trace']:
        print(f"  {step['step']}: {step.get('status')}" + (f" · {step['reason']}" if step.get('reason') else '')
              + (f" · reasons {step['reasons']}" if step.get('reasons') else ''))
    proposal = result['proposal'] or {}
    print(f"  target in rover odom: {proposal.get('target_in_rover_frame')}")
    print(f"  with the real executor adapter: {real['stages']['eligibility'] if real else None}, blockers "
          f"{real['blockers'] if real else None}")
    print(f"DECISION: {result['decision']} · movement_authorized: False · evidence: {args.out}")
    return 0 if result['decision'] == 'ROVER_TASK_PENDING_AUTHORIZATION' else 1


if __name__ == '__main__':
    raise SystemExit(main())
