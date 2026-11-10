"""Read-only performance and readiness metrics for a running rover simulation.

Four time bases are kept apart and never subtracted across domains:
- host wall time (monotonic receipt of each message, in the container's clock);
- Gazebo simulated time (/rover1/clock, bridged from gz /clock): domain of odometry stamps;
- ArduPilot time (/ap/v3/clock, AP_DDS): domain of /ap/v3 message stamps;
- message header stamps, compared only with the clock of their own domain, and only
  when the stamp falls inside the observed range of that clock (else NOT_COMPARABLE).
No service calls, mode changes, arming or publications; ROS subscriptions only.
AP_DDS exposes neither EKF flags nor pre-arm reasons, so both are NOT_EXPOSED.
"""
import argparse
import json
import subprocess

SCHEMA = 'tfg.rover.sim-metrics/2'
# Binds a sample to the lifecycle that asked for it and to the exact container execution it was taken in.
BINDING_SCHEMA = 'tfg.rover.sim-metrics-binding/1'
MAX_WALL_AGE_S = 1.0       # newest receipt vs end of window; older means the stream is stale
DOMAIN_TOLERANCE_S = 1.0   # stamp must lie within its clock's observed range +- this
STREAMS = {  # stream -> (topic suffix, clock domain of its header stamps)
    'odometry': ('odometry', 'gazebo'),
    'status': ('status', 'ardupilot'),
    'navsat': ('navsat', 'ardupilot'),
}

SAMPLER = r'''
import json, sys, time
cfg = json.load(sys.stdin)
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rosgraph_msgs.msg import Clock
from nav_msgs.msg import Odometry
from sensor_msgs.msg import NavSatFix
from ardupilot_msgs.msg import Status
rclpy.init(); node = rclpy.create_node('tfg_rover_metrics_probe')
qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)
seen = {'gazebo_clock': [], 'ardupilot_clock': [], 'odometry': [], 'status': [], 'navsat': []}
def stamp(m): return m.sec * 10**9 + m.nanosec
node.create_subscription(Clock, cfg['gazebo_clock'], lambda m: seen['gazebo_clock'].append((time.monotonic_ns(), stamp(m.clock))), qos)
node.create_subscription(Clock, cfg['ardupilot_clock'], lambda m: seen['ardupilot_clock'].append((time.monotonic_ns(), stamp(m.clock))), qos)
node.create_subscription(Odometry, cfg['odometry'], lambda m: seen['odometry'].append((time.monotonic_ns(), stamp(m.header.stamp),
    {'frame_id': m.header.frame_id, 'child_frame_id': m.child_frame_id})), qos)
node.create_subscription(Status, cfg['status'], lambda m: seen['status'].append((time.monotonic_ns(), stamp(m.header.stamp),
    {'vehicle_type': m.vehicle_type, 'armed': m.armed, 'mode': m.mode, 'flying': m.flying,
     'external_control': m.external_control, 'failsafe': list(m.failsafe)})), qos)
node.create_subscription(NavSatFix, cfg['navsat'], lambda m: seen['navsat'].append((time.monotonic_ns(), stamp(m.header.stamp),
    {'status': m.status.status, 'latitude': m.latitude, 'longitude': m.longitude, 'altitude': m.altitude})), qos)
start = time.monotonic_ns(); deadline = time.monotonic() + cfg['window_s']
while time.monotonic() < deadline:
    rclpy.spin_once(node, timeout_sec=0.05)
end = time.monotonic_ns(); node.destroy_node(); rclpy.shutdown()
boot_id = open('/proc/sys/kernel/random/boot_id').read().strip()  # host kernel boot: binds the monotonic times
print(json.dumps({'wall_start_ns': start, 'wall_end_ns': end, 'boot_id': boot_id, 'seen': seen}))
'''


def _clock(rows):
    if len(rows) < 2:
        return {'messages': len(rows), 'real_time_factor': None, 'reason': 'FEWER_THAN_TWO_CLOCK_MESSAGES'}
    sim_s = (rows[-1][1] - rows[0][1]) / 1e9
    wall_s = (rows[-1][0] - rows[0][0]) / 1e9
    return {'messages': len(rows), 'sim_advance_s': sim_s, 'wall_span_s': wall_s,
            'real_time_factor': sim_s / wall_s if wall_s > 0 and sim_s >= 0 else None,
            'first_ns': rows[0][1], 'last_ns': rows[-1][1]}


def _stream(rows, clock, wall_end_ns, wall_s):
    if not rows:
        return {'messages': 0, 'reason': 'NO_MESSAGES_IN_WINDOW', 'fresh': False}
    stamps = [r[1] for r in rows]
    span_sim_s = (stamps[-1] - stamps[0]) / 1e9
    out = {'messages': len(rows), 'rate_per_wall_s': len(rows) / wall_s if wall_s > 0 else None,
           'rate_per_sim_s': (len(rows) - 1) / span_sim_s if len(rows) > 1 and span_sim_s > 0 else None,
           'stamps_strictly_increasing': all(b > a for a, b in zip(stamps, stamps[1:])),
           'last_age_wall_s': (wall_end_ns - rows[-1][0]) / 1e9, 'last': rows[-1][2] if len(rows[-1]) > 2 else None}
    out['fresh'] = out['last_age_wall_s'] <= MAX_WALL_AGE_S
    tolerance = DOMAIN_TOLERANCE_S * 1e9
    if clock.get('real_time_factor') is None:
        out.update(last_age_sim_s=None, sim_age_basis='UNKNOWN_CLOCK_ABSENT')
    elif clock['first_ns'] - tolerance <= stamps[-1] <= clock['last_ns'] + tolerance:
        out.update(last_age_sim_s=(clock['last_ns'] - stamps[-1]) / 1e9, sim_age_basis='SAME_DOMAIN_CLOCK')
    else:
        out.update(last_age_sim_s=None, sim_age_basis='NOT_COMPARABLE_STAMP_OUTSIDE_CLOCK_RANGE')
    return out


def summarize(raw, docker_stats=None):
    """Pure computation from the sampler output; clock domains never mixed."""
    seen = raw['seen']
    wall_s = (raw['wall_end_ns'] - raw['wall_start_ns']) / 1e9
    clocks = {'gazebo': _clock(seen.get('gazebo_clock', [])), 'ardupilot': _clock(seen.get('ardupilot_clock', []))}
    out = {'schema': SCHEMA, 'window_wall_s': wall_s, 'docker_stats': docker_stats, 'clocks': clocks,
           'real_time_factor': clocks['gazebo']['real_time_factor'],
           'real_time_factor_basis': 'GAZEBO_CLOCK' if clocks['gazebo']['real_time_factor'] is not None else 'UNKNOWN',
           'ekf_state': 'NOT_EXPOSED_BY_AP_DDS', 'prearm_reasons': 'NOT_EXPOSED_BY_AP_DDS',
           'movement_authorized': False}
    for name, (_, domain) in STREAMS.items():
        out[name] = {'clock_domain': domain, **_stream(seen.get(name, []), clocks[domain], raw['wall_end_ns'], wall_s)}
    navsat = out['navsat']
    out['gps_fix'] = (navsat['last']['status'] >= 0) if navsat.get('last') else None
    out['stale_streams'] = [name for name in STREAMS if not out[name]['fresh']]
    return out


def collect(container_id, *, lifecycle_id, window_s=20.0, run=subprocess.run, interface='v3', namespace='/rover1',
            inspect_execution=None):
    """(raw, summary, binding) of one window, sealed to ``lifecycle_id`` and to the container execution.

    The active execution (persistent container identity, container start time and boot) is read before and after
    sampling with the lifecycle's own reader; the sample is discarded if it cannot be read, is another container,
    changes during the window, or the sampler ran under another boot. The lifecycle id is the caller's declaration
    at acquisition and is checked again when the sample is consumed."""
    if not isinstance(lifecycle_id, str) or not lifecycle_id:
        raise ValueError('A lifecycle_id is required to bind the sample')
    if inspect_execution is None:
        from tools.reconciliation_environment import inspect_active_execution as inspect_execution
    before = inspect_execution()
    if not isinstance(before, dict) or (before.get('persistent_identity') or {}).get('container_id') != container_id:
        raise RuntimeError('Sampled container is not the active container execution')
    cfg = {'gazebo_clock': f'{namespace}/clock', 'ardupilot_clock': f'/ap/{interface}/clock',
           'odometry': f'{namespace}/odometry', 'status': f'/ap/{interface}/status',
           'navsat': f'/ap/{interface}/navsat', 'window_s': window_s}
    stats = run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', container_id],
                capture_output=True, text=True, timeout=30, check=False)
    result = run(['docker', 'exec', '-i', container_id, 'bash', '-lc',
                  'source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; '
                  'exec python3 -B -c "$0"', SAMPLER],
                 input=json.dumps(cfg), capture_output=True, text=True, timeout=window_s + 40, check=False)
    if result.returncode:
        raise RuntimeError('Metrics sampler failed: ' + result.stderr[-512:])
    raw = json.loads(result.stdout.strip().splitlines()[-1])
    after = inspect_execution()
    if after != before:
        raise RuntimeError('Container execution changed or became unreadable during sampling')
    if raw.get('boot_id') != before.get('container_boot_id'):
        raise RuntimeError('Sampler boot differs from the container execution boot')
    docker_stats = json.loads(stats.stdout) if stats.returncode == 0 and stats.stdout.strip() else None
    binding = {'schema': BINDING_SCHEMA, 'lifecycle_id': lifecycle_id, 'environment_execution': before}
    return raw, summarize(raw, docker_stats), binding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('container_id')
    parser.add_argument('--lifecycle-id', required=True, help='the lifecycle this sample is taken for')
    parser.add_argument('--window-s', type=float, default=20.0)
    args = parser.parse_args()
    raw, summary, binding = collect(args.container_id, lifecycle_id=args.lifecycle_id, window_s=args.window_s)
    print(json.dumps({'summary': summary, 'raw': raw, 'binding': binding}))


if __name__ == '__main__':
    main()
