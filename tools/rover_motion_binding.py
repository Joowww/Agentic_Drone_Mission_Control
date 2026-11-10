"""Session-bound MotionBinding producer for /rover1/odometry; read-only, no controls.

Collection runs inside the simulator container (rclpy and the gz CLI live there);
the host checks the evidence and binds it to ONE container execution, host boot
and lifecycle start. Evidence from another start, boot or container is rejected.

Attribution limit: the installed Humble rclpy callback carries no publisher GID
per message. Samples are attributed to the single publisher observed in the ROS
graph before and after sampling (SINGLE_PUBLISHER_GRAPH_ATTRIBUTION). The odometry
source is associated with the Gazebo model rover1 by comparing its pose with the
model pose that the Gazebo server reports. Topic or namespace names alone never
produce a binding.
"""
from dataclasses import asdict
import inspect
import json
import math
from pathlib import Path
import re
import subprocess
import time

from planning.artifact_store import fingerprint
from tools.rover_control import RoverControlError, number, projected_ground_heading
from tools.rover_ros2_adapter import ODOMETRY, STATUS, MotionBinding

SCHEMA = 'tfg.rover.motion-binding-evidence/1'
COLLECTOR_SCHEMA = 'tfg.rover.motion-binding-collection/2'
ATTRIBUTION = 'SINGLE_PUBLISHER_GRAPH_ATTRIBUTION'
BRIDGE_NODE = ('ros_gz_bridge', '/rover1')
STATUS_NODE = ('ap_v3', '/')
POSE_FRAME, CHILD_FRAME = 'odom', 'base_link'

MAX_SAMPLE_AGE_S = 2.0      # receipt -> collection end, one container clock (legacy realtime, live monotonic)
MAX_EVIDENCE_AGE_S = 60.0   # legacy realtime age; live host acquisition upper bound, one host monotonic clock


def wait_for_publishers(query, expected, *, deadline_s, monotonic, spin, stable_polls=2):
    """Bounded wait until EVERY topic has one fully resolved, stable, expected publisher.

    query(topic) -> [{'node','namespace','gid',...}]; expected = {topic: [node, namespace]}.
    Resolved: exactly one publisher, real (non-placeholder) node/namespace equal to the
    expected ones, and the same (node, namespace, gid) in `stable_polls` consecutive polls.
    A GID change for a topic taints it for the whole wait. Never waits past deadline_s.
    """
    import re as _re
    placeholder = _re.compile(r'^_[A-Z0-9_]+_$')
    started = monotonic()
    first_seen, resolved_at, identity, streak, gids, reasons = {}, {}, {}, {}, {}, {}
    tainted = set()
    while True:
        now = monotonic()
        for topic, (node, namespace) in expected.items():
            rows = query(topic)
            if rows and topic not in first_seen:
                first_seen[topic] = now - started
            seen_gids = {r.get('gid') for r in rows}
            known = gids.setdefault(topic, set())
            if known and seen_gids - known - {None}:
                tainted.add(topic)
            known.update(g for g in seen_gids if g)
            if topic in tainted:
                reasons[topic] = 'GID_CHANGED_DURING_DISCOVERY'
                continue
            if not rows:
                reasons[topic], streak[topic] = 'ABSENT', 0
                continue
            if len(rows) != 1:
                reasons[topic], streak[topic] = 'MULTIPLE_PUBLISHERS', 0
                continue
            row = rows[0]
            current = (row.get('node'), row.get('namespace'), row.get('gid'))
            if any(not isinstance(v, str) or not v or placeholder.match(v) for v in current[:2]) or not current[2]:
                reasons[topic], streak[topic] = 'NODE_IDENTITY_UNRESOLVED', 0
                continue
            if current[:2] != (node, namespace):
                reasons[topic], streak[topic] = 'UNEXPECTED_NODE', 0
                continue
            streak[topic] = streak.get(topic, 0) + 1 if identity.get(topic) == current else 1
            identity[topic] = current
            if streak[topic] >= stable_polls:
                reasons[topic] = 'RESOLVED'
                resolved_at.setdefault(topic, now - started)
            else:
                reasons[topic] = 'NOT_YET_STABLE'
        missing = [topic for topic in expected if reasons.get(topic) != 'RESOLVED']
        if not missing or now - started >= deadline_s:
            return {'complete': not missing, 'missing': missing, 'reasons': reasons, 'deadline_s': deadline_s,
                    'elapsed_s': now - started, 'first_seen_s': {t: first_seen.get(t) for t in expected},
                    'resolved_s': {t: resolved_at.get(t) for t in expected},
                    'identities': {t: dict(zip(('node', 'namespace', 'gid'), identity[t])) if t in identity else None
                                   for t in expected},
                    'gid_changes': sorted(tainted), 'stable_polls': stable_polls}
        spin()


# Metadata precedes the VOLATILE subscription. End time includes ROS cleanup.
COLLECTOR = inspect.getsource(wait_for_publishers) + r'''
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
cfg = json.load(sys.stdin)
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from nav_msgs.msg import Odometry
raw = {'collector_schema': 'tfg.rover.motion-binding-collection/2', 'scope': cfg['scope'],
       'samples': [], 'bridge': [], 'before': {}, 'after': {}, 'timing': [],
       'collector_error': None, 'collector_errors': []}
node = None
def note_error(phase, exc):
    error = {'phase': phase, 'type': type(exc).__name__, 'message': str(exc)[:512]}
    raw['collector_errors'].append(error)
    if raw['collector_error'] is None:
        raw['collector_error'] = error
def mark(phase):
    try:
        raw['timing'].append({'phase': phase, 'container_monotonic_ns': time.monotonic_ns(),
                              'container_wall_unix_ns': time.time_ns()})
    except Exception as exc:
        note_error('timing:' + phase, exc)
def publishers(topic):
    return [{'node': i.node_name, 'namespace': i.node_namespace, 'type': i.topic_type,
             'gid': bytes(i.endpoint_gid).hex(), 'reliability': i.qos_profile.reliability.name}
            for i in node.get_publishers_info_by_topic(topic)]
def graph():
    return {t: publishers(t) for t in (cfg['odometry'], cfg['status'])}
try:
    mark('collector_start')
    rclpy.init()
    node = rclpy.create_node('tfg_motion_binding_probe')
    mark('discovery_start')
    raw['discovery'] = wait_for_publishers(publishers, cfg['expected'], deadline_s=cfg['discovery_s'],
                              monotonic=time.monotonic, spin=lambda: rclpy.spin_once(node, timeout_sec=0.1))
    mark('discovery_end')
    raw['before'] = graph()
    if not raw['discovery']['complete']:
        raise ValueError('Publisher discovery incomplete')
    mark('bridge_start')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        args = [a.decode(errors='replace') for a in argv if a]
        if args and args[0].endswith('parameter_bridge') and '__ns:=' + cfg['namespace'] in args:
            files = [args[i + 1] for i, a in enumerate(args[:-1]) if a == '--params-file']
            params = [{'path': f, 'sha256': hashlib.sha256(Path(f).read_bytes()).hexdigest(),
                       'text': Path(f).read_text()[:65536]} for f in files]
            configs = sorted({c for p in params for c in re.findall(r'(/[^\s\'\"]+\.ya?ml)', p['text'])})
            raw['bridge'].append({'pid': int(proc.name), 'argv': args, 'params': params,
                           'configs': [{'path': c, 'sha256': hashlib.sha256(Path(c).read_bytes()).hexdigest(),
                                        'text': Path(c).read_text()[:65536]} for c in configs if Path(c).is_file()]})
    mark('bridge_end')
    mark('gazebo_query_start')
    gz = subprocess.run(['bash', '-lc', 'source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; '
                         'timeout 20 gz model -m ' + cfg['model'] + ' -p'], capture_output=True, text=True, timeout=25)
    raw.update(gz_model_pose_stdout=gz.stdout[-4096:], gz_return_code=gz.returncode, gz_stderr=gz.stderr[-4096:],
               gazebo_pose_received_monotonic_ns=time.monotonic_ns())
    mark('gazebo_query_end')
    if gz.returncode:
        raise ValueError('Gazebo pose query failed')
    # No earlier subscription queue exists. Record receipt in the callback itself.
    def receive(msg):
        received_mono, received_wall = time.monotonic_ns(), time.time_ns()
        p, o = msg.pose.pose.position, msg.pose.pose.orientation
        if len(raw['samples']) < cfg['samples']:
            raw['samples'].append({'stamp_ns': msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec,
                'frame_id': msg.header.frame_id, 'child_frame_id': msg.child_frame_id,
                'position': [p.x, p.y, p.z], 'orientation_xyzw': [o.x, o.y, o.z, o.w],
                'received_wall_unix_ns': received_wall, 'received_monotonic_ns': received_mono})
    mark('fresh_window_start')
    node.create_subscription(Odometry, cfg['odometry'], receive,
        QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE))
    deadline = time.monotonic() + cfg['sample_s']
    while time.monotonic() < deadline and len(raw['samples']) < cfg['samples']:
        rclpy.spin_once(node, timeout_sec=min(0.1, max(0.0, deadline-time.monotonic())))
        raw['after'] = graph()
        if raw['after'] != raw['before']:
            raise ValueError('Publisher graph changed during collection')
    mark('fresh_window_end')
    raw['after'] = graph()
    if len(raw['samples']) < cfg['samples']:
        raise TimeoutError('No new odometry window within sample_s; no retry')
except Exception as exc:
    note_error('collection', exc)
finally:
    mark('cleanup_start')
    if node is not None:
        try:
            node.destroy_node()
        except Exception as exc:
            note_error('destroy_node', exc)
    try:
        if rclpy.ok():
            rclpy.shutdown()
    except Exception as exc:
        note_error('shutdown', exc)
    mark('cleanup_end')
    for key, read in (('collected_wall_unix_ns', time.time_ns),
                      ('collected_monotonic_ns', time.monotonic_ns),
                      ('boot_id', lambda: Path('/proc/sys/kernel/random/boot_id').read_text().strip()),
                      ('namespaces', lambda: {k: os.readlink('/proc/self/ns/' + k) for k in ('net', 'pid', 'time')})):
        try:
            raw[key] = read()
        except Exception as exc:
            note_error('metadata:' + key, exc)
def json_safe(value):
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
        return {'non_finite_float': repr(value)}
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)
try:
    print(json.dumps(raw, allow_nan=False))
except (TypeError, ValueError) as exc:
    note_error('serialization', exc)
    print(json.dumps(json_safe(raw), allow_nan=False))
'''


def parse_gz_pose(text):
    """Parse `gz model -m <name> -p` output: two bracketed triples (XYZ m, RPY rad)."""
    import re
    triples = re.findall(r'\[\s*(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)\s*\]', text or '')
    if len(triples) != 2:
        raise RoverControlError('Gazebo model pose absent or ambiguous')
    xyz, rpy = ([number(float(v), 'gz pose') for v in t] for t in triples)
    return {'xyz_m': xyz, 'rpy_rad': rpy}


def _maps_odometry(text):
    """One bridge entry with ros 'odometry' and gz '/model/rover1/odometry' (rendered, not a template)."""
    for entry in text.split('- ros_topic_name')[1:]:
        ros = re.search(r'^\s*:\s*"?([^"\n]+?)"?\s*$', entry.splitlines()[0])
        gz = re.search(r'gz_topic_name:\s*"?([^"\n]+?)"?\s*$', entry, re.M)
        if ros and gz and ros.group(1).strip() == 'odometry' and gz.group(1).strip() == '/model/rover1/odometry':
            return True
    return False


def _single(publishers, expected_node, label):
    if (not isinstance(publishers, list) or len(publishers) != 1
            or (publishers[0].get('node'), publishers[0].get('namespace')) != expected_node):
        raise RoverControlError(f'{label}: exactly one publisher from {expected_node} required')
    gid = publishers[0].get('gid')
    if not isinstance(gid, str) or len(gid) != 48 or any(c not in '0123456789abcdef' for c in gid) or not int(gid, 16):
        raise RoverControlError(f'{label}: publisher GID absent or malformed')
    return gid


def assess(raw, *, lifecycle_id, environment_execution, host_boot_id, position_tolerance_m=0.05,
           yaw_tolerance_rad=0.02, min_samples=3, now_wall_ns=None, host_window=None, now_monotonic_ns=None):
    """Pure decision over collected originals. Returns (MotionBinding, evidence) or raises."""
    live = raw.get('collector_schema') is not None
    if live and raw.get('collector_error') is not None:
        raise RoverControlError('Collector failed: ' + str(raw['collector_error']))
    if raw.get('boot_id') != host_boot_id or environment_execution.get('container_boot_id') != host_boot_id:
        raise RoverControlError('Collection boot differs from the bound host/container boot')
    discovery = raw.get('discovery')
    if not isinstance(discovery, dict) or discovery.get('complete') is not True or discovery.get('missing') != []:
        missing = discovery.get('reasons') if isinstance(discovery, dict) else 'unknown'
        raise RoverControlError(f'Publisher discovery incomplete within its deadline: {missing}')
    collected = raw.get('collected_wall_unix_ns')
    freshness = None
    if live:
        if raw.get('collector_schema') != COLLECTOR_SCHEMA:
            raise RoverControlError('Unknown collection clock/scope protocol')
        if raw.get('scope') != {'lifecycle_id': lifecycle_id, 'environment_execution': environment_execution,
                                'host_boot_id': host_boot_id}:
            raise RoverControlError('Raw collection belongs to another lifecycle, execution or boot')
        window = host_window or {}
        started, received = window.get('started_monotonic_ns'), window.get('received_monotonic_ns')
        now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        if (any(type(v) is not int for v in (started, received, now))
                or not 0 <= started <= received <= now or now-started > MAX_EVIDENCE_AGE_S*1e9):
            raise RoverControlError('Host acquisition interval absent, unordered or too old to accredit')
        # Causal upper bound includes the ENTIRE acquisition, so it cannot hide return/cleanup delay.
        # No host timestamp is ever subtracted from a container timestamp.
        freshness = {'receipt_clock': 'CONTAINER_MONOTONIC_NS', 'host_clock': 'HOST_MONOTONIC_NS',
                     'host_acquisition_upper_s': (now-started)/1e9, 'host_window': dict(window)}
    else:
        # Historical records retain their exact original protocol, never refreshed for live collection.
        now_wall_ns = time.time_ns() if now_wall_ns is None else now_wall_ns
        if type(collected) is not int or not 0 <= now_wall_ns - collected <= MAX_EVIDENCE_AGE_S * 1e9:
            raise RoverControlError('Collection time absent, in the future or too old to accredit')
    odom_gid = _single(raw['before'].get(ODOMETRY), BRIDGE_NODE, 'odometry before')
    if _single(raw['after'].get(ODOMETRY), BRIDGE_NODE, 'odometry after') != odom_gid:
        raise RoverControlError('Odometry publisher changed during sampling')
    status_gid = _single(raw['before'].get(STATUS), STATUS_NODE, 'status before')
    if _single(raw['after'].get(STATUS), STATUS_NODE, 'status after') != status_gid:
        raise RoverControlError('Status publisher changed during sampling')
    resolved = {ODOMETRY: {'node': BRIDGE_NODE[0], 'namespace': BRIDGE_NODE[1], 'gid': odom_gid},
                STATUS: {'node': STATUS_NODE[0], 'namespace': STATUS_NODE[1], 'gid': status_gid}}
    if discovery.get('identities') != resolved or discovery.get('gid_changes') != []:
        raise RoverControlError('Discovered identities differ from the sampled snapshots')
    samples = raw.get('samples') or []
    if len(samples) < min_samples:
        raise RoverControlError('Too few odometry samples')
    stamps = [s['stamp_ns'] for s in samples]
    if any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise RoverControlError('Odometry source clock not strictly increasing')
    receipt_key = 'received_monotonic_ns' if live else 'received_wall_unix_ns'
    received = [s.get(receipt_key) for s in samples]
    receipt_end = raw.get('collected_monotonic_ns') if live else collected
    if (any(type(r) is not int for r in received) or any(b < a for a, b in zip(received, received[1:]))
            or type(receipt_end) is not int or not 0 <= receipt_end - received[-1] <= MAX_SAMPLE_AGE_S * 1e9):
        raise RoverControlError('Odometry receipts absent, unordered or stale at collection end')
    if live:
        freshness['last_sample_age_s'] = (receipt_end-received[-1])/1e9
        pose_received = raw.get('gazebo_pose_received_monotonic_ns')
        pose_to_sample = received[0] - pose_received if type(pose_received) is int else None
        if pose_to_sample is None or not 0 <= pose_to_sample <= MAX_SAMPLE_AGE_S * 1e9:
            raise RoverControlError('Gazebo pose and fresh odometry are not temporally coherent')
        freshness['gazebo_pose_to_first_sample_s'] = pose_to_sample/1e9
    if any((s['frame_id'], s['child_frame_id']) != (POSE_FRAME, CHILD_FRAME) for s in samples):
        raise RoverControlError('Odometry frames differ from odom -> base_link')
    for s in samples:
        for v in (*s['position'], *s['orientation_xyzw']):
            number(v, 'odometry component')
    bridges = raw.get('bridge') or []
    if len(bridges) != 1 or not bridges[0]['params']:
        raise RoverControlError('Exactly one rover1 bridge process with parameters required')
    if not any(_maps_odometry(c.get('text', '')) for c in bridges[0].get('configs', [])):
        raise RoverControlError('Bridge configuration does not map /model/rover1/odometry to odometry')
    gz = parse_gz_pose(raw.get('gz_model_pose_stdout'))
    last = samples[-1]
    position_error = math.hypot(last['position'][0] - gz['xyz_m'][0], last['position'][1] - gz['xyz_m'][1])
    heading = projected_ground_heading(last['orientation_xyzw'])['heading_rad']
    yaw_error = abs(math.atan2(math.sin(heading - gz['rpy_rad'][2]), math.cos(heading - gz['rpy_rad'][2])))
    if position_error > position_tolerance_m or yaw_error > yaw_tolerance_rad:
        raise RoverControlError('Odometry pose does not match the Gazebo rover1 model pose')
    scope = {'lifecycle_id': lifecycle_id, 'environment_execution': environment_execution,
             'host_boot_id': host_boot_id}
    association = {'gz_model': 'rover1', 'gz_pose': gz, 'odometry_last': last,
                   'position_error_m': position_error, 'yaw_error_rad': yaw_error,
                   'tolerances': {'position_m': position_tolerance_m, 'yaw_rad': yaw_tolerance_rad}}
    binding = MotionBinding(
        environment_identity_sha256=fingerprint(scope),
        active_bridge_config_sha256=fingerprint([[p['sha256'] for p in bridges[0]['params']],
                                                 [c['sha256'] for c in bridges[0]['configs']]]),
        odometry_publisher_gid=odom_gid,
        pose_reference_frame=POSE_FRAME,
        pose_reference_sha256=fingerprint({'scope': scope, 'frames': [POSE_FRAME, CHILD_FRAME],
                                           'association': association}))
    binding.check()
    evidence = {'schema': SCHEMA, 'status': 'ACCREDITED_FOR_SESSION', 'attribution': ATTRIBUTION,
                'scope': scope, 'odometry_publisher_gid': odom_gid, 'status_publisher_gid': status_gid,
                'discovery': discovery, 'collected_wall_unix_ns': collected,
                'publishers': {'before': raw['before'], 'after': raw['after']},
                'samples': samples, 'association': association,
                'bridge': [{'pid': b['pid'], 'argv': b['argv'],
                            'params': [{'path': p['path'], 'sha256': p['sha256']} for p in b['params']],
                            'configs': [{'path': c['path'], 'sha256': c['sha256']} for c in b['configs']]}
                           for b in bridges],
                'namespaces': raw.get('namespaces'), 'binding': asdict(binding),
                'movement_authorized': False}
    if live:
        evidence['freshness'] = freshness
        evidence['collector_timing'] = raw.get('timing')
    evidence['evidence_sha256'] = fingerprint({k: v for k, v in evidence.items() if k != 'evidence_sha256'})
    return binding, evidence


def require_current(evidence, *, lifecycle_id, environment_execution, host_boot_id):
    """Reject reuse in another start, container execution or host boot; never refreshes."""
    if (not isinstance(evidence, dict) or evidence.get('schema') != SCHEMA
            or evidence.get('status') != 'ACCREDITED_FOR_SESSION'
            or evidence.get('evidence_sha256') != fingerprint({k: v for k, v in evidence.items() if k != 'evidence_sha256'})):
        raise RoverControlError('Motion binding evidence absent, altered or not accredited')
    if evidence['scope'] != {'lifecycle_id': lifecycle_id, 'environment_execution': environment_execution,
                             'host_boot_id': host_boot_id}:
        raise RoverControlError('Motion binding belongs to another start, container execution or boot')
    binding = MotionBinding(**evidence['binding'])
    binding.check()
    return binding


def _execution_fence(expected):
    from tools.simulation_lifecycle import assert_environment_execution
    assert_environment_execution(expected)


def _lifecycle_fence(lifecycle_id, environment_execution, host_boot_id):
    """Read only: a caller's label is not proof that this is still the active start."""
    from tools import vehicle_execution_lock as locks
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != host_boot_id:
        raise RoverControlError('Collection host boot changed')
    if locks.restriction() is not None:
        raise RoverControlError('Collection blocked by a reservation or lifecycle lease')
    operations = [json.loads(p.read_text()) for p in (locks.LOCK_ROOT.parent/'simulation_lifecycle').glob('*/operation.json')]
    latest = max(operations, key=lambda op: op.get('started_at', ''), default={})
    if (latest.get('owner_id') != lifecycle_id or latest.get('action') != 'start' or latest.get('state') != 'FINISHED'
            or latest.get('profile') not in ('rover_only', 'two_drones_rover')
            or latest.get('environment_execution') != environment_execution):
        raise RoverControlError('Collection belongs to another or noncurrent lifecycle start')


def collect(container_id, *, lifecycle_id, environment_execution, host_boot_id, run=subprocess.run,
            discovery_s=15.0, sample_s=60.0, samples=5, fence=_execution_fence, session_fence=_lifecycle_fence):
    """Read-only collection in the exact container, then assess(). Wall-clock bounded.

    Always returns the raw originals; status is ACCREDITED_FOR_SESSION only when
    assess() passes and the container execution is unchanged before and after.
    """
    out = {'status': 'BLOCKED', 'raw': None, 'binding': None, 'evidence': None, 'reason': None}
    try:
        if container_id != environment_execution['persistent_identity']['container_id']:
            raise RoverControlError('Collection container differs from the bound execution')
        if type(samples) is not int or not 3 <= samples <= 64:
            raise RoverControlError('Collection needs 3 to 64 new samples')
        for value in (discovery_s, sample_s):
            if not 0 < number(value, 'collection timeout', positive=True) <= 120:
                raise RoverControlError('Collection timeout exceeds 120 seconds')
        session_fence(lifecycle_id, environment_execution, host_boot_id)
        fence(environment_execution)
        cfg = {'odometry': ODOMETRY, 'status': STATUS, 'namespace': '/rover1', 'model': 'rover1',
               'expected': {ODOMETRY: list(BRIDGE_NODE), STATUS: list(STATUS_NODE)},
               'discovery_s': discovery_s, 'sample_s': sample_s, 'samples': samples,
               'scope': {'lifecycle_id': lifecycle_id, 'environment_execution': environment_execution, 'host_boot_id': host_boot_id}}
        started = time.monotonic_ns()
        result = run(['docker', 'exec', '-i', container_id, 'bash', '-lc',
                      'source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; '
                      'exec python3 -B -c "$0"', COLLECTOR],
                     input=json.dumps(cfg), capture_output=True, text=True,
                     timeout=discovery_s + sample_s + 40, check=False)
        out['collector'] = {'return_code': result.returncode,
                            'stdout_tail': result.stdout[-8192:], 'stderr_tail': result.stderr[-2048:]}
        out['host_window'] = {'started_monotonic_ns': started, 'received_monotonic_ns': time.monotonic_ns()}
        if result.stdout.strip():
            out['raw'] = json.loads(result.stdout.strip().splitlines()[-1])
        if result.returncode:
            raise RoverControlError('Container collection failed: ' + result.stderr[-512:])
        fence(environment_execution)
        session_fence(lifecycle_id, environment_execution, host_boot_id)
        if (out['raw'] or {}).get('collector_schema') != COLLECTOR_SCHEMA:
            raise RoverControlError('Live collection needs the current scoped monotonic collector protocol')
        binding, evidence = assess(out['raw'], lifecycle_id=lifecycle_id,
                                   environment_execution=environment_execution, host_boot_id=host_boot_id,
                                   host_window=out['host_window'])
        out.update(status='ACCREDITED_FOR_SESSION', binding=asdict(binding), evidence=evidence)
    except Exception as exc:  # the originals are kept; the result stays BLOCKED
        out['reason'] = f'{type(exc).__name__}: {exc}'
    return out
