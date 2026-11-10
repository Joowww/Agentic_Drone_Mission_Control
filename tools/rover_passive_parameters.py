"""Prepared GetParameters-only reader for rover_01/v3. No execution on import.

Names/types checked against installed ArduPilot 755258dbb on 2026-11-04.
No parameter writes, publishers, mode/arming clients, retries or lifecycle controls.
Public rclpy responses do not expose the server GID: results remain diagnostic,
never an accredited autopilot fact or an authorization for movement.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import time

SERVICE = '/ap/v3/get_parameters'
SERVICE_TYPE = 'rcl_interfaces/srv/GetParameters'
IDENTITY = ('MAV_SYSID', 'DDS_USE_NS')
# ROS ParameterType INTEGER=2, DOUBLE=3. AP_Float is returned as DOUBLE.
TYPES = {'MAV_SYSID': 2, 'DDS_USE_NS': 2, 'GUID_TIMEOUT': 3, 'ATC_ACCEL_MAX': 3, 'ATC_DECEL_MAX': 3,
         'FS_GCS_ENABLE': 2, 'FS_ACTION': 2, 'FS_CRASH_CHECK': 2, 'FS_TIMEOUT': 3,
         'FS_THR_ENABLE': 2, 'FS_THR_VALUE': 2, 'FS_EKF_ACTION': 2, 'FS_EKF_THRESH': 3,
         'FS_OPTIONS': 2, 'FS_GCS_TIMEOUT': 3}
PARAMETERS = tuple(n for n in TYPES if n not in IDENTITY)
# AP_DDS rejects more than 8 names per request. Repeat identity in every batch.
BATCHES = tuple(IDENTITY + PARAMETERS[i:i+6] for i in range(0, len(PARAMETERS), 6))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _discovery(node):
    return sorted((name, tuple(types)) for name, types in node.get_service_names_and_types()
                  if name.startswith('/ap/v3/') and SERVICE_TYPE in types)


def _read_once(node, names, timeout_s):
    import rclpy
    from rcl_interfaces.srv import GetParameters
    client = future = None
    try:
        client = node.create_client(GetParameters, SERVICE)
        if not client.service_is_ready():
            raise LookupError('GetParameters is not ready; no request sent')
        request = GetParameters.Request()
        request.names = list(names)
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=timeout_s)
        if not future.done():
            raise TimeoutError('GetParameters reply absent; no retry')
        response = future.result()
        if response is None:
            raise ValueError('GetParameters returned no response')
        return response.values
    finally:
        if future is not None:
            future.cancel()  # local cancellation only; safe for a read request
        if client is not None and node.destroy_client(client) is False:
            raise RuntimeError('GetParameters client destruction unconfirmed')


def read_from_node(node, *, timeout_s=3.0, transport=None, utc=utc_now, monotonic=time.monotonic):
    """One fixed set, split into <=8-name reads; injected node must belong to the authorized session."""
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 5:
        raise ValueError('Read timeout must be in (0, 5] seconds')
    transport = transport or _read_once
    result, batches = {}, []
    expected = [(SERVICE, (SERVICE_TYPE,))]
    for names in BATCHES:
        if _discovery(node) != expected:
            raise ValueError('Unique exact v3 GetParameters service not discovered')
        started_at, started = utc(), monotonic()
        values = list(transport(node, names, timeout_s))
        ended, observed_at = monotonic(), utc()
        if _discovery(node) != expected:
            raise ValueError('GetParameters discovery changed during read')
        if len(values) != len(names):
            raise ValueError('GetParameters response shape differs')
        rows = {}
        for name, raw in zip(names, values):
            if raw.type == 0:
                raise ValueError('Parameter absent in running firmware: ' + name)
            if raw.type != TYPES[name]:
                raise ValueError('Unexpected ROS parameter type for ' + name)
            value = raw.integer_value if raw.type == 2 else raw.double_value
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or raw.type == 2 and type(value) is not int):
                raise ValueError('Invalid effective parameter value: ' + name)
            if name in result and result[name]['value'] != value:
                raise ValueError('Parameter changed between batches: ' + name)
            rows[name] = {'value': value, 'ros_parameter_type': int(raw.type), 'observed_at_utc': observed_at}
        if rows['MAV_SYSID']['value'] != 3 or rows['DDS_USE_NS']['value'] != 1:
            raise ValueError('Read response is not the expected sysid=3 with DDS namespace enabled')
        result.update(rows)
        batches.append({'names': list(names), 'started_at_utc': started_at, 'observed_at_utc': observed_at,
                        'duration_s': ended-started, 'clock': 'PARAMETER_READER_MONOTONIC_S', 'parameters': rows})
    return {'parameters': result, 'batches': batches, 'service': SERVICE, 'service_type': SERVICE_TYPE,
            'rover_id': 'rover_01', 'interface': 'v3', 'sysid': 3,
            'source': 'PUBLIC_RCLPY_GET_PARAMETERS_RESPONSE',
            'server_instance_association': 'UNVERIFIED_PUBLIC_FUTURE_HAS_NO_SERVER_GID',
            'atomic_snapshot': False, 'movement_authorized': False, 'parameter_writes': 0}


def collect(container_id, *, lifecycle_id, environment_execution, host_boot_id, binding_evidence,
            timeout_s=3.0, discovery_s=10.0, run=subprocess.run, fence=None):
    """Host entry point for a FUTURE authorized read; validates binding/execution before and after."""
    from tools.rover_motion_binding import require_current, _execution_fence
    fence = fence or _execution_fence
    if container_id != environment_execution['persistent_identity']['container_id']:
        raise ValueError('Parameter reader container differs from bound execution')
    if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= 5
            or isinstance(discovery_s, bool) or not isinstance(discovery_s, (int, float)) or not 0 < discovery_s <= 15):
        raise ValueError('Invalid parameter reader deadlines')
    require_current(binding_evidence, lifecycle_id=lifecycle_id, environment_execution=environment_execution,
                    host_boot_id=host_boot_id)
    fence(environment_execution)
    cfg = dict(host_boot_id=host_boot_id, timeout_s=timeout_s, discovery_s=discovery_s)
    started_at = utc_now()
    reply = run(['docker', 'exec', '-i', container_id, 'bash', '-lc',
                 'source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; '
                 'exec python3 -B -c "$0"', Path(__file__).read_text()],
                input=json.dumps(cfg), capture_output=True, text=True,
                timeout=discovery_s + len(BATCHES)*timeout_s + 25, check=False)
    if reply.returncode:
        raise RuntimeError('Read-only parameter reader failed (code '+str(reply.returncode)+'); preserve stderr privately')
    observed = json.loads(reply.stdout.strip().splitlines()[-1])
    fence(environment_execution)
    if observed.get('host_boot_id') != host_boot_id or set(observed.get('parameters', {})) != set(TYPES):
        raise ValueError('Parameter response boot or set differs')
    return {'schema': 'tfg.rover.passive-parameters/1', 'status': 'READ_DIAGNOSTIC_SERVER_INSTANCE_UNVERIFIED',
            'scope': {'container_id': container_id, 'environment_execution': environment_execution,
                      'host_boot_id': host_boot_id, 'lifecycle_id': lifecycle_id,
                      'binding_evidence_sha256': binding_evidence['evidence_sha256']},
            'started_at_utc': started_at, 'finished_at_utc': utc_now(), 'observation': observed,
            'eligible_for_motion_admission': False, 'movement_authorized': False}


def main():
    """Container-only read runner; the host collect() supplies the fixed scope on stdin."""
    import sys
    cfg = json.load(sys.stdin)
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != cfg['host_boot_id']:
        raise ValueError('Parameter reader boot differs')
    import rclpy
    rclpy.init()
    node = rclpy.create_node('tfg_rover_passive_parameters')
    try:
        deadline = time.monotonic() + cfg['discovery_s']
        while not _discovery(node) and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        observed = read_from_node(node, timeout_s=cfg['timeout_s'])
        observed['host_boot_id'] = cfg['host_boot_id']
        print(json.dumps(observed, allow_nan=False))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
