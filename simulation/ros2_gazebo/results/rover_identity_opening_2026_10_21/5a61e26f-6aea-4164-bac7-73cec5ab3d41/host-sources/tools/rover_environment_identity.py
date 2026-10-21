"""Pure identity assessment. No ROS/Docker, flight authority or automatic recovery.

Also deployed beside the container's passive worker; stdlib only. Consistency of
process/ROS records is deliberately not accreditation of an XRCE source session.
"""
import hashlib
import json
import math
from uuid import UUID


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def assess_identity(expected, current, *, max_age_s=3.):
    reasons = []
    result = {'status': 'BLOCKED', 'identity_consistent': False,
              'source_association_verified': False, 'movement_authorized': False,
              'reasons': reasons}
    try:
        if not isinstance(current, dict) or not isinstance(current.get('record'), dict):
            raise ValueError('Identity worker record absent; evidence not collected')
        if str(UUID(expected['lifecycle_id'])) != expected['lifecycle_id']:
            raise ValueError('Invalid lifecycle start identity')
        environment = expected['environment']
        if (not all(isinstance(environment[k], str) and environment[k] for k in
                    ('engine_id', 'container_id', 'name', 'created_at', 'image_id'))
                or environment['name'] != '/tfg-ardupilot-gazebo'
                or not environment['created_at'] or not environment['image_id']
                or len(environment['container_id']) != 64
                or any(c not in '0123456789abcdef' for c in environment['container_id'])):
            raise ValueError('Incomplete protected environment identity')
        if expected['profile'] != 'two_drones_rover' or expected['vehicle_id'] != 'rover_01' or expected['interface'] != 'v3' or expected['namespace'] != '/rover1':
            raise ValueError('Unexpected rover/profile/namespace')
        launch_hash = expected['launch_sha256']
        if (not isinstance(launch_hash, str) or len(launch_hash) != 64
                or any(c not in '0123456789abcdef' for c in launch_hash)
                or current['installed_launch_sha256'] != launch_hash):
            raise ValueError('Installed launch bytes missing or changed')
        if current['context_sha256'] != digest(expected):
            raise ValueError('Launch context changed or belongs to another start')
        if current['environment'] != expected['environment']:
            raise ValueError('Engine/container incarnation differs from protected start')
        record = current['record']
        if record['context_sha256'] != digest(expected):
            raise ValueError('Worker belongs to another launch context')
        for age in ('receipt_age_s', 'worker_age_s'):
            value = current[age]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= max_age_s:
                raise ValueError(f'Missing/stale {age}')
        if record.get('state') != 'OBSERVING':
            raise ValueError('Identity worker stopped/failed; no restart or acceptance on query')
        # PIDs here belong to ONE container proc/boot domain, never host worker PIDs.
        if current['process_clock_scope'] != 'CONTAINER_PROC_BOOT_AND_MONOTONIC':
            raise ValueError('Unknown process/clock namespace')
        for role, identity in (('launch', expected['launch_process']), ('worker', record['worker'])):
            if (set(identity) != {'pid', 'start_ticks', 'boot_id'}
                    or type(identity['pid']) is not int or type(identity['start_ticks']) is not int
                    or not identity['boot_id']):
                raise ValueError(f'Invalid {role} process identity')
            if current['processes'].get(str(identity['pid'])) != identity:
                raise ValueError(f'{role} missing, dead or PID recycled')
        observed = record['ros']
        for key, topic in (('status', '/ap/v3/status'), ('odometry', '/rover1/odometry')):
            stream = observed[key]
            if stream['topic'] != topic or not stream.get('publisher_gid'):
                raise ValueError(f'{key} source/interface absent or wrong')
            if type(stream.get('publisher_count')) is not int or stream['publisher_count'] != 1:
                raise ValueError(f'{key} publisher absent or ambiguous')
            if key == 'status' and (type(stream['message'].get('vehicle_type')) is not int or stream['message']['vehicle_type'] != 1):
                raise ValueError('Status is not Rover')
            if key == 'odometry' and stream['message'].get('child_frame_id') != 'base_link':
                raise ValueError('Odometry frame is not rover body contract')
            # Age computed by the passive worker in its OWN monotonic domain.
            age = stream['age_s']
            if (type(age) not in (int, float) or not math.isfinite(age) or age < 0
                    or age + current['worker_age_s'] + current['receipt_age_s'] > max_age_s):
                raise ValueError(f'{key} observation stale')
            if stream.get('source_progressing') is not True:
                raise ValueError(f'{key} source frozen/rewound or insufficient samples')
        if observed['odometry'].get('publisher_namespace') != '/rover1':
            raise ValueError('Odometry publisher is outside expected bridge namespace')
        result['identity_consistent'] = True
        reasons.append('Runtime XRCE client/SYSID/DDS_USE_NS correlation and active bridge config association not yet accredited')
    except (KeyError, TypeError, ValueError) as exc:
        reasons.append(str(exc))
    return result


class RoverEnvironmentGuard:
    """Reader must collect CURRENT evidence; no constructor accepting verified=True.

    No production collector yet bridges host Docker identity and container proc/
    ROS samples. A callback used in tests does not establish real availability.
    """
    def __init__(self, expected, read_current):
        self.expected, self.read_current = expected, read_current

    def query(self):
        try:
            return assess_identity(self.expected, self.read_current())
        except Exception as exc:
            return {'status': 'BLOCKED', 'identity_consistent': False,
                    'source_association_verified': False, 'movement_authorized': False,
                    'reasons': [f'Identity collector unavailable: {type(exc).__name__}: {exc}']}

    def require_motion_source(self):
        result = self.query()
        # This increment NEVER turns a well-formed snapshot into a motion permit.
        raise RuntimeError('Rover source identity BLOCKED: ' + '; '.join(result['reasons']))
