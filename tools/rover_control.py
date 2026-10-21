"""Internal offline-tested Rover core. No CLI/MCP; operational use remains disabled by executor policy.

The ROS adapter must borrow protected executor authority. No construction grants
consent or enables the operational execution policy.
No default ROS/Docker path, arming, TAKEOFF or LAND is provided.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import IntEnum
import math
import time
from typing import Protocol

from tools.execution_diagnostics import error_evidence


class RoverControlError(ValueError):
    pass


class RoverMode(IntEnum):
    HOLD = 4
    GUIDED = 15


def number(value, label, *, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (positive and value <= 0)):
        raise RoverControlError(f'Invalid {label}')
    return float(value)


@dataclass(frozen=True)
class RoverLimits:
    max_forward_mps: float
    max_yaw_rate_rad_s: float
    max_duration_s: float
    call_timeout_s: float
    stop_timeout_s: float
    observation_max_age_s: float
    stopped_linear_mps: float
    stopped_angular_rad_s: float

    def __post_init__(self):
        for key, value in asdict(self).items():
            number(value, key, positive=True)


@dataclass(frozen=True)
class Observation:
    # Envelope identity comes from adapter routing, not authenticated dialogue or ROS ids.
    vehicle_id: str
    interface: str
    vehicle_type: int
    mode: int
    armed: bool
    flying: bool  # Status.idl: driving for Rover, not an airborne test
    external_control: bool
    failsafe: tuple[int, ...]
    received_monotonic_s: float
    status_source_ns: int | None
    velocity_source_ns: int | None = None
    linear_mps: tuple[float, float, float] | None = None
    angular_rad_s: tuple[float, float, float] | None = None
    # Simulator odometry, independently sampled from DDS; not DDS twist freshness.
    motion_source: str | None = None
    motion_frame: str | None = None
    motion_received_monotonic_s: float | None = None
    linear_unit: str = 'm/s'
    angular_unit: str = 'rad/s'


@dataclass(frozen=True)
class Reply:
    sent: bool | None
    return_code: int | None
    payload: dict | None = None
    stdout: str = ''
    stderr: str = ''
    # Native rclpy has no process exit code; completion is only local API return.
    native_api_completed: bool = False


def transport_completed(reply):
    return (isinstance(reply, Reply) and reply.sent is True and (
        reply.native_api_completed is True and reply.return_code is None
        or reply.native_api_completed is False and type(reply.return_code) is int and reply.return_code == 0))


class RoverAdapter(Protocol):
    def observe(self, *, timeout_s: float) -> Observation: ...
    def exchange(self, command: dict, *, timeout_s: float) -> Reply: ...


class RoverControlCore:
    """No production backend: construction alone never grants movement authority."""
    def __init__(self, limits: RoverLimits, *, vehicle_id='rover_01', interface='v3',
                 adapter: RoverAdapter | None = None, clock=time):
        if vehicle_id != 'rover_01' or interface != 'v3':
            raise RoverControlError('Only infrastructure alias rover_01/v3 is supported here')
        if not isinstance(limits, RoverLimits):
            raise RoverControlError('Explicit RoverLimits required; no safety defaults')
        self.limits, self.adapter, self.clock = limits, adapter, clock
        self.diagnostics = []

    def _require_adapter(self):
        if self.adapter is None:
            raise RoverControlError('BLOCKED: no operational rover adapter or execution authority integrated')

    def _operation(self, name, endpoint, timeout, fn, *, command=None):
        self._require_adapter()
        timeout = number(timeout, 'remaining timeout', positive=True)
        record = {'operation': name, 'vehicle_id': 'rover_01', 'interface': 'v3',
                  'endpoint': endpoint, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
                  'timeout_s': timeout, 'attempted': True, 'acknowledged': False,
                  'effects': 'UNCONFIRMED' if command else 'READ_ONLY',
                  'command': deepcopy(command), 'return_code': None}
        self.diagnostics.append(record)
        started = self.clock.monotonic()
        try:
            value = fn()
            record['result'] = deepcopy(asdict(value) if is_dataclass(value) else value)
            if isinstance(value, Reply):
                record['return_code'] = value.return_code
                record['return_code_kind'] = 'NO_PROCESS_EXIT_NATIVE_API' if value.native_api_completed else 'PROCESS_OR_DOUBLE'
            if self.clock.monotonic() - started > timeout:
                raise TimeoutError('Adapter exceeded its finite deadline; effects not confirmed')
            return value, record
        except Exception as exc:
            record['error'] = error_evidence(exc)
            for stream in ('stdout', 'stderr'):
                partial = getattr(exc, stream, None)
                if partial is not None:
                    record[stream] = partial.decode('utf-8', errors='replace') if isinstance(partial, bytes) else str(partial)
            raise
        finally:
            record.update(finished_at_utc=datetime.now(timezone.utc).isoformat(),
                          duration_wall_s=self.clock.monotonic() - started,
                          clock='HOST_UTC_AND_MONOTONIC_NOT_SIMULATED_TIME')

    def _validate(self, obs):
        if not isinstance(obs, Observation):
            raise RoverControlError('Missing typed Rover observation')
        if (obs.vehicle_id, obs.interface) != ('rover_01', 'v3') or type(obs.vehicle_type) is not int or obs.vehicle_type != 1:
            raise RoverControlError('Observation is not APM_ROVER on rover_01/v3')
        if type(obs.mode) is not int or not 0 <= obs.mode <= 255:
            raise RoverControlError('Invalid mode type')
        if any(type(v) is not bool for v in (obs.armed, obs.flying, obs.external_control)):
            raise RoverControlError('Status booleans missing/invalid')
        if not isinstance(obs.failsafe, tuple) or any(type(x) is not int or not 0 <= x <= 255 for x in obs.failsafe):
            raise RoverControlError('Failsafe observation missing/invalid')
        age = self.clock.monotonic() - number(obs.received_monotonic_s, 'receive timestamp')
        if not 0 <= age <= self.limits.observation_max_age_s:
            raise RoverControlError('Observation receipt stale or in the future')
        return obs

    def _observe(self, timeout=None):
        timeout = self.limits.call_timeout_s if timeout is None else timeout
        value, record = self._operation('observe', '/ap/v3/status + independent rover1 odometry', timeout,
                                       lambda: self.adapter.observe(timeout_s=timeout))
        try:
            return self._validate(value)
        except Exception as exc:
            record['interpretation_error'] = error_evidence(exc)
            raise

    @staticmethod
    def _progress(first, second, *, motion=False):
        names = ['status_source_ns'] + (['velocity_source_ns'] if motion else [])
        for name in names:
            a, b = getattr(first, name), getattr(second, name)
            if type(a) is not int or type(b) is not int or a < 0 or b <= a:
                raise RoverControlError(f'Missing/non-progressing {name}; no freshness inference')
        if second.received_monotonic_s <= first.received_monotonic_s:
            raise RoverControlError('No progressing receive time')
        if motion and (first.motion_received_monotonic_s is None
                       or second.motion_received_monotonic_s is None
                       or second.motion_received_monotonic_s <= first.motion_received_monotonic_s):
            raise RoverControlError('No progressing independent motion receive time')

    def _switch(self, mode, timeout):
        command = {'kind': 'service', 'endpoint': '/ap/v3/mode_switch',
                   'type': 'ardupilot_msgs/srv/ModeSwitch', 'payload': {'mode': int(mode)}}
        reply, record = self._operation('mode_switch', command['endpoint'], timeout,
            lambda: self.adapter.exchange(deepcopy(command), timeout_s=timeout), command=command)
        if not transport_completed(reply):
            raise RoverControlError('Mode request transport/confirmation absent')
        payload = reply.payload
        if (not isinstance(payload, dict) or type(payload.get('status')) is not bool
                or type(payload.get('curr_mode')) is not int or not 0 <= payload['curr_mode'] <= 255):
            raise RoverControlError('Uninterpretable ModeSwitch response')
        record['response'] = deepcopy(payload)
        if payload['status'] is not True:
            record['rejected'] = True
            raise RoverControlError('ModeSwitch negative response')
        if payload['curr_mode'] != int(mode):
            raise RoverControlError('ModeSwitch response contradicts requested Rover mode')
        record.update(acknowledged=True, effects='ACKNOWLEDGED_NOT_OBSERVED')

    def request_mode(self, mode):
        if not isinstance(mode, RoverMode):
            raise RoverControlError('Use explicit RoverMode.GUIDED or RoverMode.HOLD, not Copter numbers')
        self._require_adapter()
        self._observe()  # type/interface checked before a mode number can mean anything
        try:
            self._switch(mode, self.limits.call_timeout_s)
        except Exception as exc:
            self.diagnostics[-1]['interpretation_error'] = error_evidence(exc)
            raise
        return {'request_acknowledged': True, 'mode_observed': False, 'stopped': None}

    @staticmethod
    def velocity_message(forward_mps, yaw_rate_rad_s, *, linear_unit='m/s', angular_unit='rad/s'):
        if linear_unit != 'm/s' or angular_unit != 'rad/s':
            raise RoverControlError('Only m/s and rad/s accepted')
        forward_mps = number(forward_mps, 'forward velocity')
        yaw_rate_rad_s = number(yaw_rate_rad_s, 'yaw rate')
        return {'kind': 'topic', 'endpoint': '/ap/v3/cmd_vel',
                'type': 'geometry_msgs/msg/TwistStamped',
                'payload': {'header': {'frame_id': 'base_link'}, 'twist': {
                    'linear': {'x': forward_mps, 'y': 0.0, 'z': 0.0},
                    'angular': {'x': 0.0, 'y': 0.0, 'z': yaw_rate_rad_s}}}}

    def _publish(self, message, timeout):
        reply, record = self._operation('publish_velocity', message['endpoint'], timeout,
            lambda: self.adapter.exchange(deepcopy(message), timeout_s=timeout), command=message)
        # A topic publish has no autopilot application response, even on return code 0.
        record['application_confirmation'] = 'NOT_AVAILABLE_FOR_TOPIC'
        if not transport_completed(reply):
            raise RoverControlError('Velocity publication unconfirmed; effects may be uncertain')
        record['effects'] = 'SENT_APPLICATION_UNCONFIRMED'

    def _validate_motion(self, obs):
        if (obs.motion_source != '/model/rover1/odometry' or obs.motion_frame != 'base_link'
                or obs.motion_received_monotonic_s is None):
            raise RoverControlError('Independent simulator odometry contract absent')
        motion_age = self.clock.monotonic() - number(obs.motion_received_monotonic_s, 'motion receive timestamp')
        if not 0 <= motion_age <= self.limits.observation_max_age_s:
            raise RoverControlError('No recent post-command motion observation')
        if obs.linear_unit != 'm/s' or obs.angular_unit != 'rad/s':
            raise RoverControlError('Invalid observation units')
        for name, limit in [('linear_mps', self.limits.stopped_linear_mps),
                            ('angular_rad_s', self.limits.stopped_angular_rad_s)]:
            vector = getattr(obs, name)
            if not isinstance(vector, tuple) or len(vector) != 3:
                raise RoverControlError('Motion observation absent')
            norm = math.sqrt(sum(number(v, name)**2 for v in vector))
            if norm > limit:
                raise RoverControlError('Motion still observed above explicit threshold')

    def stop(self):
        self._require_adapter()
        start_index = len(self.diagnostics)
        deadline = self.clock.monotonic() + self.limits.stop_timeout_s
        def remaining():
            return min(self.limits.call_timeout_s, number(deadline-self.clock.monotonic(), 'stop time remaining', positive=True))
        try:
            before = self._observe(remaining())
            zero_error = None
            if before.mode == int(RoverMode.GUIDED) and before.armed:
                try:
                    self._publish(self.velocity_message(0.0, 0.0), remaining())
                except Exception as exc:
                    # A failed zero write must not suppress the distinct HOLD attempt.
                    zero_error = error_evidence(exc)
            self._switch(RoverMode.HOLD, remaining())  # no TAKEOFF/LAND/disarm
            after_command = self.clock.monotonic()
            samples = [self._observe(remaining()), self._observe(remaining())]
            self._progress(*samples, motion=True)
            for obs in samples:
                if obs.mode != int(RoverMode.HOLD) or obs.flying or obs.failsafe or obs.received_monotonic_s < after_command:
                    raise RoverControlError('No consistent post-command HOLD/non-driving evidence')
                self._validate_motion(obs)
                if obs.motion_received_monotonic_s < after_command:
                    raise RoverControlError('Motion observation predates HOLD request')
            if zero_error is not None:
                return {'status': 'UNCONFIRMED', 'stationary_observed': True,
                        'ground_contact_confirmed': False, 'zero_command_error': zero_error,
                        'observations': [asdict(v) for v in samples],
                        'diagnostics': deepcopy(self.diagnostics[start_index:])}
            return {'status': 'STATIONARY_OBSERVED', 'stationary_observed': True,
                    'ground_contact_confirmed': False, 'observations': [asdict(v) for v in samples],
                    'diagnostics': deepcopy(self.diagnostics[start_index:])}
        except Exception as exc:
            return {'status': 'UNCONFIRMED', 'stationary_observed': False,
                    'ground_contact_confirmed': False, 'error_evidence': error_evidence(exc),
                    'diagnostics': deepcopy(self.diagnostics[start_index:])}

    def move_for(self, forward_mps, yaw_rate_rad_s, duration_s, *, linear_unit='m/s', angular_unit='rad/s'):
        message = self.velocity_message(forward_mps, yaw_rate_rad_s, linear_unit=linear_unit, angular_unit=angular_unit)
        duration = number(duration_s, 'duration', positive=True)
        if (not 0 <= forward_mps <= self.limits.max_forward_mps
                or abs(yaw_rate_rad_s) > self.limits.max_yaw_rate_rad_s or duration > self.limits.max_duration_s):
            raise RoverControlError('Request exceeds explicit policy; reverse not enabled')
        self._require_adapter()
        start_index = len(self.diagnostics)
        attempted = False
        error = None
        stop_result = None
        try:
            initial = [self._observe(), self._observe()]
            self._progress(*initial, motion=True)
            for sample in initial:
                self._validate_motion(sample)  # BEFORE the first possible motion command
            if any(v.mode != int(RoverMode.GUIDED) or not v.armed or not v.external_control or v.failsafe for v in initial):
                raise RoverControlError('Rover must already be GUIDED, armed, external-control ready, no failsafe')
            attempted = True
            self._publish(message, self.limits.call_timeout_s)  # single send, no hidden retry
            self.clock.sleep(duration)
        except Exception as exc:
            error = error_evidence(exc)
        finally:
            if attempted:
                stop_result = self.stop()  # same-target ground stop after any possible control effect
        return {'status': 'STOP_OBSERVED' if error is None and stop_result and stop_result['status'] == 'STATIONARY_OBSERVED' else
                         'UNCONFIRMED' if attempted else 'NOT_ATTEMPTED',
                'motion_command_attempted': attempted, 'motion_application_confirmed': False,
                'error_evidence': error, 'stop': stop_result,
                'diagnostics': deepcopy(self.diagnostics[start_index:]),
                'note': 'Internal adapter core only; no production authority, mission or distance acceptance.'}
