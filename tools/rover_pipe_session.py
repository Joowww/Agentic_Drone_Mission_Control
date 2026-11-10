"""Host side of the private host-container rover channel; the authority stays on the host.

PipeRos2Session gives Ros2RoverAdapter the session interface it already uses
(probe/observe/exchange/close, plus current/validate_observation/require_stop_target)
over JSON Lines to tools/rover_pipe_worker.py started with `docker exec -i` in the
exact container. No network port, no retries, no ROS server for the LLM.

Identity: the session opens only with MotionBinding evidence that require_current()
accepts for THIS lifecycle start, container execution and host boot, and only if the
worker reports the same boot and exactly the accredited status/odometry GIDs. Every
reply must keep those GIDs. Receive times are taken from the HOST monotonic clock
when the reply arrives; container clocks (another time namespace) are never used.

Uncertainty: a lost, late, out-of-order or malformed reply breaks the session; a
command whose reply is missing is reported as effects UNCONFIRMED and is never resent.
After any command whose effect is unconfirmed, only stop commands may be sent.

Time budget: see call_budget(). The worker always gets a deadline that ends before the
host's own (the caller's synchronous_deadline), so a slow vehicle yields a worker
TIMEOUT_EFFECT_UNCONFIRMED reply inside the host budget and the session stays usable for
stop commands, instead of the host alarm breaking the channel mid-read.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from uuid import uuid4

from planning.artifact_store import fingerprint
from tools.rover_control import Reply, RoverControlError, number
from tools.rover_motion_binding import require_current
from tools.rover_pipe_worker import HARD_LIMITS, MAX_LINE_BYTES, OPERATIONAL_LIMITS, PROTOCOL, is_stop, validate_command
from tools.rover_ros2_adapter import Ros2RoverAdapter, _validate_command

# One host operation of T seconds, on ONE monotonic deadline fixed when the call starts
# (T = the caller's timeout_s or what is left of an armed SIGALRM, whichever is shorter):
#   worker wait <= min(WORKER_SHARE * T, T - IPC_RESERVE_S - HOST_GUARD_S)
#   reply read   until T - HOST_GUARD_S  (serialization, docker exec pipe, parse; then host checks)
# Below MIN_WORKER_BUDGET_S nothing is sent: a request that cannot be answered in time is never issued.
WORKER_SHARE = 0.7          # proportional slack for scheduling jitter on a loaded host
IPC_RESERVE_S = 0.25        # ASSUMED pipe round trip + JSON both ways; to be measured in SITL
HOST_GUARD_S = 0.05         # alarm armed before the session is entered; post-reply host checks
MIN_WORKER_BUDGET_S = 0.1   # smallest wait that can still observe or call anything
CLOSE_ACK_S, CLOSE_EXIT_S = 0.5, 0.6   # close() stays inside the executor's 2 s close deadline
MAX_TIMINGS = 4096          # diagnostic per-call timing records kept by a session (then counted, not stored)
WORKER_SOURCE = Path(__file__).with_name('rover_pipe_worker.py')


class TransportClosed(RoverControlError):
    pass


class BudgetExhausted(TimeoutError):
    """Too little host time left to get an answer: the request was NOT sent."""


def _alarm_remaining():
    """What is left of an armed synchronous_deadline (SIGALRM), or None."""
    import signal
    import threading
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, 'getitimer'):
        return None
    remaining = signal.getitimer(signal.ITIMER_REAL)[0]
    return remaining if remaining > 0 else None


def call_budget(timeout_s, alarm_remaining_s=None):
    """Explicit split of one host operation; raises BudgetExhausted (nothing sent) when too small."""
    host = number(timeout_s, 'host operation timeout', positive=True)
    if alarm_remaining_s is not None:
        host = min(host, number(alarm_remaining_s, 'armed host deadline', positive=True))
    worker = min(WORKER_SHARE * host, host - IPC_RESERVE_S - HOST_GUARD_S)
    if worker < MIN_WORKER_BUDGET_S:
        failure = BudgetExhausted(f'Host budget {host:.3f} s leaves no time for a worker answer; not sent')
        failure.diagnostic = {'effects': 'NOT_SENT', 'host_s': host, 'worker_s': max(worker, 0.0)}
        raise failure
    return {'host_s': host, 'worker_s': worker, 'receive_s': host - HOST_GUARD_S,
            'reserve_s': host - worker}


class JsonLineTransport:
    """One child process; stdout carries protocol lines only, stderr is drained to a file."""
    def __init__(self, process):
        self.process = process
        self.buffer = b''
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def send(self, obj):
        data = (json.dumps(obj, allow_nan=False) + '\n').encode()
        if len(data) > MAX_LINE_BYTES:
            raise RoverControlError('Request exceeds the protocol line limit')
        try:
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise TransportClosed('Worker pipe closed while sending') from exc

    def receive(self, timeout_s):
        deadline = time.monotonic() + number(timeout_s, 'receive timeout', positive=True)
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Worker reply absent within its deadline')
            if not self.selector.select(remaining):
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise TransportClosed('Worker closed its output (EOF) before a complete reply')
            self.buffer += chunk
            if len(self.buffer) > MAX_LINE_BYTES:
                raise RoverControlError('Worker reply exceeds the protocol line limit')
        line, self.buffer = self.buffer.split(b'\n', 1)
        try:
            return json.loads(line)
        except ValueError as exc:
            raise RoverControlError('Malformed worker reply') from exc

    def close(self, timeout_s):
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            return self.process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=min(timeout_s, 0.3))
            raise RoverControlError('Worker did not exit after close; killed, stop state not confirmed by exit')


def worker_limits(limits, *, watchdog_s, max_session_s):
    """Hello limits of an OPERATIONAL worker, derived from the request's accredited RoverLimits; never looser."""
    value = {'max_linear_mps': limits.max_forward_mps, 'max_angular_rad_s': limits.max_yaw_rate_rad_s,
             'watchdog_s': number(watchdog_s, 'worker watchdog', positive=True),
             'telemetry_max_age_s': limits.observation_max_age_s,
             'max_session_s': number(max_session_s, 'worker session lifetime', positive=True),
             'stopped_linear_mps': limits.stopped_linear_mps, 'stopped_angular_rad_s': limits.stopped_angular_rad_s}
    if any(value[k] > HARD_LIMITS[k] for k in value):
        raise RoverControlError('Worker limits exceed the worker HARD_LIMITS')
    if value['watchdog_s'] < limits.call_timeout_s:
        raise RoverControlError('Worker watchdog shorter than one host call would trip during a normal call')
    return value


def _default_motion_allowed():
    from tools.rover_ground_executor import motion_policy_allows_current_owner
    return motion_policy_allows_current_owner()


def _default_authority():
    from tools.vehicle_execution_lock import assert_execution_authority
    assert_execution_authority('v3')


def _default_fence(expected):
    from tools.simulation_lifecycle import assert_environment_execution
    assert_environment_execution(expected)


class PipeRos2Session:
    def __init__(self, transport, *, lifecycle_id, environment_execution, host_boot_id, binding_evidence, limits,
                 mode='OPERATIONAL', clock=time, fence=_default_fence, motion_allowed=_default_motion_allowed,
                 authority=_default_authority, alarm_remaining=_alarm_remaining):
        if mode not in ('PASSIVE', 'OPERATIONAL'):
            raise RoverControlError('Session mode must be PASSIVE or OPERATIONAL')
        if mode == 'OPERATIONAL':
            authority()  # live v3 reservation of this process before any operational worker exists
        self._mode = mode
        self.alarm_remaining = alarm_remaining
        self.effects_uncertain = None   # first command whose effect is unconfirmed; then stop-only
        self.last_budget = None
        self.timings = []               # per call, host monotonic + the worker's own timing (rover_pipe_latency)
        self.timings_dropped = 0
        self.transport, self.clock, self.fence, self.motion_allowed = transport, clock, fence, motion_allowed
        self.lifecycle_id, self.environment_execution, self.host_boot_id = lifecycle_id, environment_execution, host_boot_id
        self.broken = None
        self.closed = False
        self.last = None
        self.after = {'status': None, 'odometry': None}
        self.binding = require_current(binding_evidence, lifecycle_id=lifecycle_id,
                                       environment_execution=environment_execution, host_boot_id=host_boot_id)
        self.expected = {'status': binding_evidence['status_publisher_gid'],
                         'odometry': binding_evidence['odometry_publisher_gid']}
        if self.expected['odometry'] != self.binding.odometry_publisher_gid:
            raise RoverControlError('Binding evidence and binding disagree on the odometry GID')
        keys = ('watchdog_s', 'max_session_s') if mode == 'PASSIVE' else OPERATIONAL_LIMITS
        if not isinstance(limits, dict) or set(limits) != set(keys):
            raise RoverControlError('Worker limits must be exactly ' + ', '.join(keys))
        self.limits = {k: number(limits[k], k, positive=True) for k in keys}
        if any(self.limits[k] > HARD_LIMITS[k] for k in keys):
            raise RoverControlError('Worker limits exceed the worker HARD_LIMITS')
        if mode == 'PASSIVE' and self.limits['max_session_s'] > 300.0:
            raise RoverControlError('Passive worker deadline exceeds the scope maximum of 300 seconds')
        self.started_host_monotonic_s = self.clock.monotonic()
        self.deadline_host_monotonic_s = (self.started_host_monotonic_s + self.limits['max_session_s']
                                          if mode == 'PASSIVE' else None)
        fence(environment_execution)
        transport.send({'protocol': PROTOCOL, 'op': 'hello', 'session_id': lifecycle_id, 'mode': mode,
                        'expected_gids': self.expected, 'limits': self.limits})
        ack = self._receive(self.limits['watchdog_s'])
        graph = ack.get('graph') or {} if isinstance(ack, dict) else {}
        if (not isinstance(ack, dict) or ack.get('protocol') != PROTOCOL or ack.get('op') != 'hello' or ack.get('ok') is not True
                or ack.get('session_id') != lifecycle_id or ack.get('mode') != mode or ack.get('boot_id') != host_boot_id
                or graph.get('status') != self.expected['status'] or graph.get('odometry') != self.expected['odometry']):
            self._break('HELLO_IDENTITY_MISMATCH')
            raise RoverControlError('Worker identity/boot/publishers differ from the accredited session')

    @property
    def mode(self):
        """Fixed at construction: an operational session can never turn PASSIVE (and lose STOP)."""
        return self._mode

    # -- transport -----------------------------------------------------------
    def _break(self, reason):
        self.broken = self.broken or reason

    def _receive(self, timeout_s):
        try:
            return self.transport.receive(timeout_s)
        except (TimeoutError, TransportClosed, RoverControlError) as exc:
            self._break(type(exc).__name__)
            raise

    def _call(self, op, args, timeout_s, *, effects=False):
        if self.closed or self.broken:
            raise RoverControlError(f'Pipe session unusable ({self.broken or "closed"}); no replay')
        if self.mode == 'PASSIVE':
            remaining = self.deadline_host_monotonic_s - self.clock.monotonic()
            if remaining <= HOST_GUARD_S + IPC_RESERVE_S + MIN_WORKER_BUDGET_S:
                error = TimeoutError('Passive session deadline reached; no new request sent; protected lifecycle STOP required')
                error.diagnostic = {'request_sent': False, 'protected_stop_required': True,
                                    'deadline_host_monotonic_s': self.deadline_host_monotonic_s}
                raise error
            timeout_s = min(timeout_s, remaining)
        budget = call_budget(timeout_s, self.alarm_remaining())  # BudgetExhausted: nothing sent, session intact
        self.last_budget = budget
        started = self.clock.monotonic()
        args = {**args, 'timeout_s': budget['worker_s']}
        rid = str(uuid4())
        try:
            self.transport.send({'protocol': PROTOCOL, 'session_id': self.lifecycle_id, 'request_id': rid,
                                 'op': op, 'args': args})
            sent = self.clock.monotonic()
            left = budget['receive_s'] - (sent - started)
            if left <= 0:
                raise TimeoutError('Host budget spent while sending')
            reply = self._receive(left)
            self._record_timing(op, started, sent, self.clock.monotonic(), reply)
        except (TimeoutError, TransportClosed) as exc:
            self._break(type(exc).__name__)
            if effects:
                failure = TimeoutError(f'{op} reply absent; request effects unconfirmed')
                failure.diagnostic = {'operation': op, 'request': args, 'response_received': False,
                                      'effects': 'UNCONFIRMED', 'transport': type(exc).__name__, 'budget': budget}
                raise failure from None
            raise
        if (not isinstance(reply, dict) or reply.get('protocol') != PROTOCOL
                or reply.get('session_id') != self.lifecycle_id or reply.get('request_id') != rid):
            self._break('REPLY_OUT_OF_ORDER_OR_FOREIGN')
            raise RoverControlError('Worker reply not correlated with this request; session broken')
        graph = reply.get('graph')
        if ((reply.get('ok') is True or graph is not None) and
                (not isinstance(graph, dict) or graph.get('status') != self.expected['status']
                 or graph.get('odometry') != self.expected['odometry'])):
            self._break('PUBLISHER_CHANGED')
            raise RoverControlError('Publisher GIDs changed during the session')
        if reply.get('ok') is not True:
            error = reply.get('error')
            if not isinstance(error, dict):
                self._break('MALFORMED_ERROR_REPLY')
                raise RoverControlError('Malformed worker error; command effects remain unconfirmed')
            code = error.get('code', 'UNKNOWN')
            if code in ('TIMEOUT_EFFECT_UNCONFIRMED', 'BACKEND_ERROR_EFFECT_UNCONFIRMED'):
                if code == 'BACKEND_ERROR_EFFECT_UNCONFIRMED':
                    self._break('WORKER_BACKEND_ERROR')  # the worker stops on its own and ends the session
                failure = TimeoutError(f'{op}: worker reports {code}')
                failure.diagnostic = {'operation': op, 'request': args, 'response_received': True,
                                      'effects': 'UNCONFIRMED', 'worker_code': code, 'budget': budget}
                raise failure
            if code == 'BACKEND_ERROR':
                self._break('WORKER_BACKEND_ERROR')
            raise RoverControlError(f'Worker refused {op}: {code}')
        if not isinstance(reply.get('result'), dict):
            self._break('MALFORMED_RESULT')
            raise RoverControlError('Malformed worker result; command effects remain unconfirmed')
        return reply['result']

    def _record_timing(self, op, started, sent, received, reply):
        """Host monotonic stamps of one call plus the worker's own timing; diagnostic only, bounded."""
        if len(self.timings) >= MAX_TIMINGS:
            self.timings_dropped += 1
            return
        worker = reply.get('timing') if isinstance(reply, dict) else None
        self.timings.append({'op': op, 'clock': 'HOST_MONOTONIC_S', 'send_start_s': started, 'send_done_s': sent,
                             'reply_s': received, 'ok': isinstance(reply, dict) and reply.get('ok') is True,
                             'worker': worker if isinstance(worker, dict) else None})

    # -- interface used by Ros2RoverAdapter / RoverControlCore -----------------
    def probe(self, *, timeout_s):
        self.fence(self.environment_execution)
        caps = self._call('probe', {}, timeout_s)
        if caps.get('boot_id') != self.host_boot_id or caps.get('status_publisher_gid') != self.expected['status']:
            self._break('PROBE_IDENTITY_MISMATCH')
            raise RoverControlError('Probe identity differs from the accredited session')
        return {**{k: caps[k] for k in ('status_type', 'odometry_type', 'mode_type', 'velocity_type', 'mode_available',
                                        'disarm_type', 'disarm_available', 'velocity_subscribers', 'status_publishers',
                                        'odometry_publisher_gids')},
                'session_id': self.lifecycle_id, 'observation_source': None, 'transport': 'PIPE_WORKER_V1'}

    def observe(self, *, timeout_s):
        timing_count = len(self.timings)
        result = self._call('observe', {'after_status_ns': self.after['status'],
                                        'after_odometry_ns': self.after['odometry']}, timeout_s)
        received = self.clock.monotonic()  # host clock, at reply receipt
        for key in ('status', 'odometry'):
            stamp = result[key]['header']['stamp']
            self.after[key] = stamp['sec'] * 10**9 + stamp['nanosec']
        if len(self.timings) > timing_count and self.timings[-1]['op'] == 'observe':
            self.timings[-1]['sample_stamp_ns'] = dict(self.after)
        self.last = {'status': result['status'], 'odometry': result['odometry'],
                     'status_publisher_gid': result['status_publisher_gid'],
                     'odometry_publisher_gid': result['odometry_publisher_gid'],
                     'sample_metadata': result.get('sample_metadata'),
                     'status_received_monotonic_s': received, 'odometry_received_monotonic_s': received,
                     'sample_provenance': {'attribution': 'SINGLE_PUBLISHER_GRAPH_ATTRIBUTION',
                                           'receipt_clock': 'HOST_MONOTONIC_AT_REPLY'}}
        return dict(self.last)

    watch = observe

    def current(self):
        if self.broken:
            raise RoverControlError('No current observation from an intact session')
        if self.last is None:  # first preparation sample: a fresh pair, never a fabricated one
            return self.observe(timeout_s=min(2.0, self.limits['watchdog_s']))
        return dict(self.last)

    def validate_observation(self, raw):
        if (self.broken or raw.get('status_publisher_gid') != self.expected['status']
                or raw.get('odometry_publisher_gid') != self.expected['odometry']):
            raise RoverControlError('Observation not from the accredited publishers of an intact session')
        return {'binding_sha256': fingerprint(asdict(self.binding))}

    def require_stop_target(self):
        if self.broken or self.closed:
            raise RoverControlError('Stop target unverifiable: pipe session ' + (self.broken or 'closed'))
        return {'session_id': self.lifecycle_id, 'gids': dict(self.expected)}

    def observation_phase(self, phase):
        return None

    def exchange(self, command, *, timeout_s):
        if self.mode == 'PASSIVE':
            raise RoverControlError('Passive session: commands are never sent; open a new operational session')
        _validate_command(command)  # adapter allowlist (host side)
        kind = validate_command(command, max_linear_mps=self.limits['max_linear_mps'],
                                max_angular_rad_s=self.limits['max_angular_rad_s'])
        stopping = is_stop(command, kind)
        if not stopping and self.effects_uncertain is not None:
            raise RoverControlError('An earlier command effect is unconfirmed ('
                                    + self.effects_uncertain['operation'] + '); only stop commands may be sent')
        if not stopping and self.motion_allowed() is not True:
            raise RoverControlError('Motion policy does not allow non-stop commands for the current owner')
        if not stopping:
            self.fence(self.environment_execution)
        try:
            result = self._call('exchange', {'command': command}, timeout_s, effects=True)
        except BudgetExhausted:
            raise  # not sent: nothing to be uncertain about
        except (TimeoutError, RoverControlError) as exc:
            self.effects_uncertain = self.effects_uncertain or {
                'operation': kind, 'command': command, 'diagnostic': getattr(exc, 'diagnostic', None)}
            raise
        if kind == 'velocity':
            return Reply(True, None, native_api_completed=True)
        return Reply(True, None, result, native_api_completed=True)

    def close(self):
        if self.closed:
            return
        self.closed = True
        uncertain = None
        if not self.broken:
            try:
                rid = str(uuid4())
                self.transport.send({'protocol': PROTOCOL, 'session_id': self.lifecycle_id, 'request_id': rid,
                                     'op': 'close', 'args': {}})
                reply = self.transport.receive(CLOSE_ACK_S)
                if reply.get('request_id') != rid or reply.get('ok') is not True:
                    uncertain = 'CLOSE_NOT_ACKNOWLEDGED'
            except Exception as exc:
                uncertain = 'CLOSE_' + type(exc).__name__
        try:
            self.transport.close(CLOSE_EXIT_S)
        except Exception as exc:
            uncertain = uncertain or 'EXIT_' + type(exc).__name__
        if uncertain or self.broken:
            raise RoverControlError('Pipe session closure uncertain: ' + (uncertain or self.broken))


def _spawn(container_id, popen, stderr_path):
    stderr = open(stderr_path, 'ab') if stderr_path else subprocess.DEVNULL
    return popen(['docker', 'exec', '-i', container_id, 'bash', '-lc',
                  'source /opt/ros/humble/setup.bash; source /root/ardu_ws/install/setup.bash; '
                  'exec python3 -B -u -c "$0"', WORKER_SOURCE.read_text()],
                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)


def open_passive_session(container_id, *, lifecycle_id, environment_execution, host_boot_id, binding_evidence,
                         max_session_s=300.0, watchdog_s=5.0, worker_reservation_id=None, popen=subprocess.Popen, stderr_path=None):
    """Read-only session: the worker builds no publisher or service client; exchange is impossible."""
    if container_id != environment_execution['persistent_identity']['container_id']:
        raise RoverControlError('Worker container differs from the bound execution')
    if (isinstance(max_session_s, bool) or not isinstance(max_session_s, (int, float))
            or not 0 < max_session_s <= 300.0):
        raise RoverControlError('Passive session lifetime must be within the scope limit (0, 300] seconds')
    require_current(binding_evidence, lifecycle_id=lifecycle_id, environment_execution=environment_execution,
                    host_boot_id=host_boot_id)
    _default_fence(environment_execution)
    if not isinstance(worker_reservation_id,str) or not worker_reservation_id:
        raise RoverControlError('Lifecycle-owned passive worker reservation required')
    try:
        from tools.simulation_lifecycle import consume_passive_worker_reservation
        consume_passive_worker_reservation(lifecycle_id,worker_reservation_id,container_id)
    except Exception as exc:
        raise RoverControlError('Passive worker reservation rejected before spawn: '+str(exc)) from exc
    process = _spawn(container_id, popen, stderr_path)
    try:
        return PipeRos2Session(JsonLineTransport(process), lifecycle_id=lifecycle_id,
                               environment_execution=environment_execution, host_boot_id=host_boot_id,
                               binding_evidence=binding_evidence, limits={'watchdog_s': watchdog_s, 'max_session_s': max_session_s}, mode='PASSIVE',
                               motion_allowed=lambda: False, authority=lambda: None)
    except BaseException:
        process.kill()
        raise


def pipe_adapter_factory(container_id, *, lifecycle_id, environment_execution, host_boot_id, binding_evidence, limits,
                         popen=subprocess.Popen, stderr_path=None):
    """Explicit wiring for start_ground_trial(adapter_factory=...); spawns nothing until called."""
    if container_id != environment_execution['persistent_identity']['container_id']:
        raise RoverControlError('Worker container differs from the bound execution')
    def build(journal):
        _default_authority()  # before creating even an operational worker process
        if _default_motion_allowed() is not True:
            raise RoverControlError('Motion policy closed; no operational worker spawned')
        from tools import rover_ground_executor as ground, vehicle_execution_lock as locks
        owner = locks.restriction('v3')
        if not isinstance(owner, dict) or not owner.get('owner_id'):
            raise RoverControlError('v3 reservation disappeared before the worker was spawned')
        job, _, request, _ = ground._checked(ground.directory(owner['owner_id']))
        if job.get('policy_admission', {}).get('basis') == 'SITL_TRIAL':
            scope = request.get('sitl_trial', {}).get('scope', {})
            context = scope.get('control_context', {})
            if limits != context.get('worker_limits'):
                raise RoverControlError('Worker limits differ from the admitted SITL scope')
            # The worker must open the very session that was admitted, not another live one.
            if (lifecycle_id != scope.get('lifecycle_id') or host_boot_id != scope.get('host_boot_id')
                    or environment_execution != scope.get('environment_execution')
                    or binding_evidence.get('evidence_sha256') != scope.get('binding_evidence_sha256')):
                raise RoverControlError('Worker wiring differs from the admitted SITL scope')
        require_current(binding_evidence, lifecycle_id=lifecycle_id, environment_execution=environment_execution,
                        host_boot_id=host_boot_id)
        _default_fence(environment_execution)
        process = _spawn(container_id, popen, stderr_path)
        try:
            session = PipeRos2Session(JsonLineTransport(process), lifecycle_id=lifecycle_id,
                                      environment_execution=environment_execution, host_boot_id=host_boot_id,
                                      binding_evidence=binding_evidence, limits=limits, mode='OPERATIONAL')
        except BaseException:
            process.kill()
            raise
        return Ros2RoverAdapter(session, binding=session.binding, journal=journal)
    return build
