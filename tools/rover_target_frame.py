"""Explicit SE(2) construction of rover goals in the accredited odom frame; pure, no I/O.

A goal is either a declared offset from the OBSERVED start pose (forward/left in
the rover body frame at start) or a declared point already in odom. The start pose
must come from session-bound MotionBinding evidence (tools.rover_motion_binding);
no global or invented coordinates are accepted, and no frame is inferred.
"""
import math

from planning.artifact_store import fingerprint
from tools.rover_control import RoverControlError, number, projected_ground_heading, transform_ground_point

SCHEMA = 'tfg.rover.odom-goal/1'
FRAME = 'odom'


def verify_trial_start(context, observation):
    """Reject a live pose that has drifted from the declared starting pose, before GUIDED/ARM."""
    start, tolerance = context['start_pose'], context['start_tolerance']
    position = observation.position_m
    if (observation.pose_frame != FRAME or not observation.pose_reference_validated
            or position is None or observation.orientation_xyzw is None):
        raise RoverControlError('Current start pose/frame is not accredited')
    distance = math.hypot(number(position[0], 'current x') - start['x_m'],
                          number(position[1], 'current y') - start['y_m'])
    heading = projected_ground_heading(observation.orientation_xyzw)['heading_rad']
    yaw_error = abs(math.atan2(math.sin(heading - start['heading_rad']), math.cos(heading - start['heading_rad'])))
    if distance > tolerance['position_m'] or yaw_error > tolerance['yaw_rad']:
        raise RoverControlError('Current start pose differs from the authorized starting pose')
    return {'distance_m': distance, 'yaw_error_rad': yaw_error, 'status': 'WITHIN_DECLARED_START_TOLERANCE'}


def start_pose(evidence):
    """Last odometry sample of accredited evidence; caller has already run require_current()."""
    if evidence.get('status') != 'ACCREDITED_FOR_SESSION':
        raise RoverControlError('Start pose requires accredited session evidence')
    last = evidence['association']['odometry_last']
    if last.get('frame_id') != FRAME:
        raise RoverControlError('Start pose is not in the odom frame')
    heading = projected_ground_heading(last['orientation_xyzw'])['heading_rad']
    reference = evidence.get('binding', {}).get('pose_reference_sha256')
    if not isinstance(reference, str) or len(reference) != 64:
        raise RoverControlError('Accredited evidence lacks the pose reference digest')
    return {'x_m': number(last['position'][0], 'start x'), 'y_m': number(last['position'][1], 'start y'),
            'heading_rad': heading, 'frame': FRAME, 'stamp_ns': last['stamp_ns'],
            'evidence_sha256': evidence['evidence_sha256'], 'pose_reference_sha256': reference}


def _goal(start, x, y, yaw, *, max_distance_m, method, inputs):
    distance = math.hypot(x - start['x_m'], y - start['y_m'])
    if not 0 < distance <= number(max_distance_m, 'max distance', positive=True):
        raise RoverControlError('Goal distance outside (0, max_distance_m]')
    target = {'x_m': x, 'y_m': y, 'yaw_rad': yaw, 'frame': FRAME}
    derivation = {'from': inputs, 'to_frame': FRAME, 'method': method, 'start': start,
                  'max_distance_m': max_distance_m, 'target': target}
    # sha256 is the accredited pose-frame reference the executor compares with
    # binding.pose_reference_sha256; the derivation and the target have their own digests.
    transform = {'from': inputs, 'to_frame': FRAME, 'method': method, 'status': 'VERIFIED',
                 'start_evidence_sha256': start['evidence_sha256'], 'sha256': start['pose_reference_sha256'],
                 'derivation_sha256': fingerprint(derivation), 'goal_sha256': fingerprint(target)}
    return {'schema': SCHEMA, 'start': start, 'target_in_rover_frame': target, 'max_distance_m': max_distance_m,
            'frame_transform': transform, 'distance_m': distance, 'goal_sha256': fingerprint(target)}


def goal_from_start_offset(start, *, forward_m, left_m, max_distance_m):
    """Target = start + R(heading)·(forward, left); final yaw keeps the start heading."""
    forward, left = number(forward_m, 'forward offset'), number(left_m, 'left offset')
    x, y = transform_ground_point((forward, left), (start['x_m'], start['y_m']), start['heading_rad'])
    return _goal(start, x, y, start['heading_rad'], max_distance_m=max_distance_m,
                 method='SE2_OFFSET_FROM_OBSERVED_START_POSE',
                 inputs={'frame': 'rover_body_at_start', 'forward_m': forward, 'left_m': left})


def goal_from_declared_odom(start, *, x_m, y_m, yaw_rad, max_distance_m):
    """A point declared directly in odom; still bounded by the observed start."""
    x, y, yaw = number(x_m, 'goal x'), number(y_m, 'goal y'), number(yaw_rad, 'goal yaw')
    return _goal(start, x, y, math.atan2(math.sin(yaw), math.cos(yaw)), max_distance_m=max_distance_m,
                 method='IDENTITY_DECLARED_IN_ODOM', inputs={'frame': FRAME, 'x_m': x, 'y_m': y, 'yaw_rad': yaw})


def verify_goal(goal, evidence, binding):
    """Recompute the goal from the accredited evidence; reject any inconsistent reference."""
    start = start_pose(evidence)
    transform, target = goal['frame_transform'], goal['target_in_rover_frame']
    if binding.pose_reference_sha256 != start['pose_reference_sha256'] or transform['sha256'] != start['pose_reference_sha256']:
        raise RoverControlError('Goal frame reference differs from the accredited binding')
    if goal['start'] != start or transform['start_evidence_sha256'] != evidence['evidence_sha256']:
        raise RoverControlError('Goal start pose is not the accredited one')
    inputs = transform['from']
    if transform['method'] == 'SE2_OFFSET_FROM_OBSERVED_START_POSE':
        again = goal_from_start_offset(start, forward_m=inputs['forward_m'], left_m=inputs['left_m'],
                                       max_distance_m=goal_max_distance(goal))
    elif transform['method'] == 'IDENTITY_DECLARED_IN_ODOM':
        again = goal_from_declared_odom(start, x_m=inputs['x_m'], y_m=inputs['y_m'], yaw_rad=inputs['yaw_rad'],
                                        max_distance_m=goal_max_distance(goal))
    else:
        raise RoverControlError('Unknown goal derivation method')
    if again != goal or transform['goal_sha256'] != fingerprint(target):
        raise RoverControlError('Goal derivation or target digest does not recompute')
    return start


def goal_max_distance(goal):
    return number(goal['max_distance_m'], 'max distance', positive=True)
