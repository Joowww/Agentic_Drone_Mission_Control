"""A REAL worker process for pipe tests: tools.rover_pipe_worker.main() over a scripted backend, no ROS.

Run as `python -m tests.rover_pipe_fake_worker '<json config>'`. Everything the backend does is
appended to config['log'] (one JSON line per action, flushed) so a test can read what physically
"happened" even when the process was killed or the host never saw the reply.

Config keys (all optional except log): boot, status_gid, odometry_gid, status_hz, service_delays
(list, consumed per service call; last value repeats), apply_on_timeout, drop_reply_ops, reply_delay_s,
exit_during_service, freeze_status_after_hold, publish_delay_s, block_service_s, initial_mode, initial_armed.
"""
import json
import math
import os
import sys
import time

from tools import rover_pipe_worker as w


class ScriptedBackend:
    def __init__(self, config, passive):
        self.c, self.passive = config, passive
        self.t0 = time.monotonic()
        self.mode, self.armed = config.get('initial_mode', 0), config.get('initial_armed', False)
        self.delays = list(config.get('service_delays', [0.0]))
        self.frozen_status = None
        self.log({'event': 'backend', 'passive': passive})

    def log(self, entry):
        with open(self.c['log'], 'a') as f:
            f.write(json.dumps({**entry, 't': round(time.monotonic() - self.t0, 3)}) + '\n')

    def spin(self, timeout_s):
        time.sleep(max(0.0, min(timeout_s, 0.05)))

    def publishers(self, topic):
        gid = self.c.get('status_gid') if topic == w.STATUS else self.c.get('odometry_gid')
        return [{'gid': gid}]

    def subscribers(self, topic):
        return 1

    def topic_type(self, topic):
        return {w.STATUS: 'ardupilot_msgs/msg/Status', w.ODOMETRY: 'nav_msgs/msg/Odometry',
                w.VELOCITY: 'geometry_msgs/msg/TwistStamped'}[topic]

    def service_type(self, name):
        return {w.MODE: 'ardupilot_msgs/srv/ModeSwitch', w.ARM: 'ardupilot_msgs/srv/ArmMotors'}[name]

    def service_ready(self, name):
        return True

    def boot_id(self):
        return self.c['boot']

    def latest(self, kind):
        elapsed = time.monotonic() - self.t0
        n = int(elapsed * (self.c.get('status_hz', 10.0) if kind == 'status' else 50.0)) + 1
        if kind == 'status' and self.frozen_status is not None:
            n = self.frozen_status
        stamp = {'sec': n, 'nanosec': 0}
        if kind == 'status':
            message = {'header': {'stamp': stamp}, 'vehicle_type': 1, 'mode': self.mode, 'armed': self.armed,
                       'flying': False, 'external_control': True, 'failsafe': []}
        else:
            zero = {'x': 0.0, 'y': 0.0, 'z': 0.0}
            message = {'header': {'stamp': stamp, 'frame_id': 'odom'}, 'child_frame_id': 'base_link',
                       'pose': {'pose': {'position': {'x': 0.0, 'y': -3.0, 'z': 0.09},
                                         'orientation': {'x': 0.0, 'y': 0.0, 'z': math.sin(0.785), 'w': math.cos(0.785)}},
                                'covariance': [0.0] * 36},
                       'twist': {'twist': {'linear': dict(zero), 'angular': dict(zero)}, 'covariance': [0.0] * 36}}
        return {'message': message, 'stamp_ns': n * 10**9, 'received_monotonic_s': time.monotonic()}

    def telemetry_age_s(self, kind):
        elapsed = time.monotonic() - self.t0
        hz = self.c.get('status_hz', 10.0) if kind == 'status' else 50.0
        n = self.frozen_status if kind == 'status' and self.frozen_status is not None else int(elapsed * hz) + 1
        return elapsed - (n - 1) / hz

    def _service(self, name, apply, timeout_s):
        delay = self.delays.pop(0) if len(self.delays) > 1 else self.delays[0]
        self.log({'event': 'service_call', 'service': name, 'delay_s': delay, 'timeout_s': timeout_s})
        if self.c.get('block_service_s'):
            time.sleep(self.c['block_service_s'])  # a ROS call that ignores its own deadline
        if delay <= timeout_s:
            time.sleep(delay)
            apply()
            self.log({'event': 'service_applied', 'service': name})
            if self.c.get('exit_during_service'):
                os._exit(0)  # effect applied, reply never written
            return True
        time.sleep(timeout_s)
        if self.c.get('apply_on_timeout'):
            apply()
            self.log({'event': 'service_applied_after_timeout', 'service': name})
        self.log({'event': 'service_timeout', 'service': name})
        raise TimeoutError('Service response absent; request effects unconfirmed')

    def call_mode(self, mode, timeout_s):
        def apply():
            self.mode = mode
            if mode == 4 and self.c.get('freeze_status_after_hold'):
                self.frozen_status = int((time.monotonic() - self.t0) * self.c.get('status_hz', 10.0)) + 1
        self._service('mode', apply, timeout_s)
        return {'status': True, 'curr_mode': mode}

    def call_arm(self, arm, timeout_s):
        self._service('arm', lambda: setattr(self, 'armed', arm), timeout_s)
        return {'result': True}

    def publish_velocity(self, linear, angular):
        if self.c.get('publish_delay_s'):
            time.sleep(self.c['publish_delay_s'])
        self.log({'event': 'velocity', 'linear': linear, 'angular': angular})

    def close(self):
        self.log({'event': 'close'})


class ScriptedStdout:
    """Optionally drops or delays replies to chosen ops, as a lossy or slow pipe would."""
    def __init__(self, real, config):
        self.real, self.c, self.pending = real, config, []

    def write(self, text):
        self.pending.append(text)

    def flush(self):
        text, self.pending = ''.join(self.pending), []
        try:
            op = json.loads(text).get('op')
        except ValueError:
            op = None
        kind = getattr(self, 'last_op', None) if op is None else op
        if kind in self.c.get('drop_reply_ops', []):
            return
        if kind in self.c.get('delay_reply_ops', []):
            time.sleep(self.c.get('reply_delay_s', 0.0))
        self.real.write(text)
        self.real.flush()


if __name__ == '__main__':
    config = json.loads(sys.argv[1])
    out = ScriptedStdout(sys.stdout, config)
    handle = w.WorkerCore.handle

    def tracking(self, line):
        try:
            out.last_op = json.loads(line).get('op')
        except ValueError:
            out.last_op = None
        return handle(self, line)
    w.WorkerCore.handle = tracking  # only to let ScriptedStdout drop/delay replies per op
    w.exit_with(w.main(stdin=sys.stdin, stdout=out, backend_factory=lambda passive: ScriptedBackend(config, passive)))
