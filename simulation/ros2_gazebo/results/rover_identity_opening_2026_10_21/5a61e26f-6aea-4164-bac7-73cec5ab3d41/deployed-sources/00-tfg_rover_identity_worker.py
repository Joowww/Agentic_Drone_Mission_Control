"""Passive ROS identity worker, supervised with the launch. NO control endpoints.

Only subscriptions and publisher discovery. No publisher, client, arming or modes.
The JSON record is a candidate observation, never a MotionBinding or a permit.
"""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4

try:
    from tools.rover_environment_identity import digest
except ModuleNotFoundError as exc:
    if exc.name not in {'tools', 'tools.rover_environment_identity'}:
        raise
    from tfg_rover_environment_identity import digest


def process_identity(pid=None):
    pid = os.getpid() if pid is None else pid
    fields = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()
    if fields[0] == 'Z':
        raise RuntimeError('Process is zombie')
    return {'pid': pid, 'start_ticks': int(fields[19]),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def publish_record(path, value):
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    with temporary.open('x') as file:
        json.dump(value, file, allow_nan=False)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class PassiveObserver:
    def __init__(self, node, convert, *, monotonic=time.monotonic):
        self.node, self.convert, self.monotonic = node, convert, monotonic
        self.samples = {}
        self.previous = {}
        self.invalid_sources = set()

    def callback(self, kind):
        def receive(message, info):
            msg = self.convert(message)
            stamp = msg['header']['stamp']
            source = stamp['sec'] * 10**9 + stamp['nanosec']
            gid = bytes(info.publisher_gid).hex()
            previous = self.previous.get(kind)
            if previous is not None and (previous[0] != gid or source <= previous[1]):
                self.invalid_sources.add(kind)  # no silent recovery after rewind/source replacement
            self.samples[kind] = {'message': msg, 'publisher_gid': gid,
                                  'received_monotonic_s': self.monotonic(),
                                  'source_progressing': kind not in self.invalid_sources and previous is not None and previous[0] == gid and source > previous[1]}
            self.previous[kind] = gid, source
        return receive

    def observation(self):
        result = {}
        for kind, topic in (('status', '/ap/v3/status'), ('odometry', '/rover1/odometry')):
            sample = self.samples.get(kind)
            if sample is None:
                continue  # absent is absent, never a zero sample
            publishers = self.node.get_publishers_info_by_topic(topic)
            matches = [p for p in publishers if bytes(p.endpoint_gid).hex() == sample['publisher_gid']]
            result[kind] = {**sample, 'topic': topic,
                            'age_s': self.monotonic()-sample['received_monotonic_s'],
                            'publisher_namespace': matches[0].node_namespace if len(matches) == 1 else None,
                            'publisher_name': matches[0].node_name if len(matches) == 1 else None,
                            'publisher_count': len(publishers)}
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    args = parser.parse_args()
    root = Path('/tmp/tfg_rover_identity')
    context_path = Path(args.context)
    if not context_path.resolve().is_relative_to(root) or context_path.is_symlink():
        raise ValueError('Context must be in supervised rover identity root')
    context = json.loads(context_path.read_text())
    if context['profile'] != 'two_drones_rover' or process_identity(context['launch_process']['pid']) != context['launch_process']:
        raise ValueError('Wrong profile or launch process replaced')
    record = {'context_sha256': digest(context), 'worker': process_identity(),
              'state': 'BLOCKED', 'ros': {}, 'movement_authorized': False}
    path = context_path.with_name('worker.json')
    node = None
    try:
        # Imports occur only in an explicitly started infrastructure process.
        import rclpy
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from ardupilot_msgs.msg import Status
        from nav_msgs.msg import Odometry
        from rosidl_runtime_py.convert import message_to_ordereddict
        rclpy.init()
        node = rclpy.create_node('tfg_rover_identity_observer', namespace='/rover1')
        observer = PassiveObserver(node, message_to_ordereddict)
        qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)
        subscriptions = [node.create_subscription(cls, topic, observer.callback(kind), qos)
                         for kind, topic, cls in [('status', '/ap/v3/status', Status),
                                                  ('odometry', '/rover1/odometry', Odometry)]]
        last_heartbeat = float('-inf')
        while rclpy.ok():
            if process_identity(context['launch_process']['pid']) != context['launch_process']:
                raise RuntimeError('Protected launch disappeared or was replaced')
            rclpy.spin_once(node, timeout_sec=.25)
            now = time.monotonic()
            if now - last_heartbeat >= 1.:
                record.update(state='OBSERVING', ros=observer.observation(), heartbeat_monotonic_s=now)
                publish_record(path, record)
                last_heartbeat = now
    except BaseException as exc:
        record.update(state='BLOCKED', error=f'{type(exc).__name__}: {exc}', heartbeat_monotonic_s=time.monotonic())
        publish_record(path, record)
    finally:
        record.update(state='BLOCKED', error=record.get('error', 'Identity worker stopped; no automatic restart'),
                      heartbeat_monotonic_s=time.monotonic())
        publish_record(path, record)
        if node is not None:
            node.destroy_node()
    return 1  # exiting is never an identity approval


if __name__ == '__main__':
    raise SystemExit(main())
