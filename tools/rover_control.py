"""Internal offline-tested Rover core. No CLI/MCP; operational use remains disabled by executor policy.

The ROS adapter must borrow protected executor authority. No construction grants
consent or enables the operational execution policy.
No default ROS/Docker path, arming, TAKEOFF or LAND is provided.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import signal
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import IntEnum
import math
import sys
import weakref
import time
from typing import Protocol

from tools.execution_diagnostics import error_evidence


class RoverControlError(ValueError):
    pass


_deadline_owner=ContextVar('rover_synchronous_deadline',default=False)


@contextmanager
def synchronous_deadline(timeout_s):
    """Interruptible same-worker POSIX deadline, never a detached sender thread.

    A weakref callback turns raised exceptions into unraisable exceptions. If
    SIGALRM lands in one, defer it briefly until the callback has returned, then
    raise normally so the guarded operation still stops promptly. Native APIs
    must ALSO retain finite deadlines; Python cannot interrupt arbitrary opaque
    C. Unowned active signal timers are rejected rather than overwritten.
    """
    timeout_s=number(timeout_s,'synchronous timeout',positive=True)
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal,'setitimer'):
        raise RoverControlError('Synchronous deadline requires POSIX main-thread worker')
    previous=signal.getitimer(signal.ITIMER_REAL);handler=signal.getsignal(signal.SIGALRM)
    if previous[0]>0 and not _deadline_owner.get():
        raise RoverControlError('Unowned active deadline; no backend call')
    started=time.monotonic();token=_deadline_owner.set(True);deferred=[False]
    def expired(signum,frame):
        if any(isinstance(value,weakref.ReferenceType) for value in frame.f_locals.values()):
            # Weakref callbacks swallow raised exceptions via sys.unraisablehook.
            # Deliver the timeout from the context manager after callback return.
            deferred[0]=True
            return
        raise TimeoutError('Synchronous rover backend deadline exceeded')
    try:
        # Even an immediately expired timer must restore its owner/handler.
        signal.signal(signal.SIGALRM,expired)
        signal.setitimer(signal.ITIMER_REAL,min(timeout_s,previous[0]) if previous[0]>0 else timeout_s)
        yield
    finally:
        body_exception=sys.exc_info()[0]
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,handler)
        _deadline_owner.reset(token)
        if previous[0]>0:
            signal.setitimer(signal.ITIMER_REAL,max(1e-6,previous[0]-(time.monotonic()-started)),previous[1])
        if deferred[0] and body_exception is None:
            raise TimeoutError('Synchronous rover backend deadline exceeded')


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
class PulseSafety:
    """Exact reviewed local envelope, no agricultural target or safe defaults.

    Digests bind the declaration to the authorized request; they do not certify
    physics or authenticate a human. Unknown measurements must not be filled in.
    """
    review_sha256: str
    binding_sha256: str
    pose_frame: str
    max_slope_rad: float
    displacement_abort_m: float
    speed_abort_mps: float
    angular_abort_rad_s: float
    heading_abort_rad: float
    position_error_m: float
    minimum_response_m: float
    clear_radius_m: float
    footprint_radius_m: float
    stopping_margin_m: float
    interval_s: float
    total_timeout_s: float
    close_budget_s: float

    def __post_init__(self):
        for k in ('review_sha256','binding_sha256'):
            v=getattr(self,k)
            if not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) or not int(v,16):
                raise RoverControlError('Missing reviewed '+k)
        if not isinstance(self.pose_frame,str) or not self.pose_frame:raise RoverControlError('Missing local pose frame')
        for k,v in asdict(self).items():
            if k not in ('review_sha256','binding_sha256','pose_frame'):number(v,k,positive=True)
        if (self.max_slope_rad>=math.pi/2 or self.heading_abort_rad>math.pi or self.interval_s>.05
                or self.minimum_response_m<=2*self.position_error_m
                or self.minimum_response_m>=self.displacement_abort_m-2*self.position_error_m
                or self.clear_radius_m<self.footprint_radius_m+self.displacement_abort_m+2*self.position_error_m+self.stopping_margin_m):
            raise RoverControlError('Unresolved pulse envelope/resolution/timing')


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
    position_m: tuple[float, float, float] | None = None
    orientation_xyzw: tuple[float, float, float, float] | None = None
    pose_frame: str | None = None
    pose_unit: str = 'm'
    pose_reference_validated: bool = False
    odometry_publisher_gid: str | None = None
    pose_covariance: tuple[float, ...] | None = None
    twist_covariance: tuple[float, ...] | None = None
    observation_provenance_sha256: str | None = None
    status_publisher_gid: str | None = None
    status_provenance_sha256: str | None = None
    motion_provenance_sha256: str | None = None
    observation_transfer_monotonic_s: float | None = None


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


@dataclass(frozen=True)
class NavigationGoal:
    # Experimental v1, no operative defaults and no inferred spawn destination.
    x_m: float
    y_m: float
    yaw_rad: float
    frame: str
    unit: str
    transform: str
    tolerance_m: float
    yaw_tolerance_rad: float
    dwell_s: float
    command_hz: float
    timeout_s: float
    no_progress_s: float
    progress_m: float
    progress_rad: float
    max_samples: int

    def __post_init__(self):
        for name in ('x_m','y_m','yaw_rad'):
            number(getattr(self,name),name)
        for name in ('tolerance_m','yaw_tolerance_rad','dwell_s','command_hz',
                     'timeout_s','no_progress_s','progress_m','progress_rad'):
            number(getattr(self,name),name,positive=True)
        if (not isinstance(self.frame,str) or not self.frame or self.unit!='m' or
            self.transform!='IDENTITY_SAME_ACCREDITED_FRAME' or self.command_hz>20 or
            self.yaw_tolerance_rad>math.pi or self.no_progress_s>self.timeout_s or
            type(self.max_samples) is not int or not 2<=self.max_samples<=256):
            raise RoverControlError('Invalid experimental navigation/frame/bounds contract')


def wrap_angle(value):
    return math.atan2(math.sin(value),math.cos(value))


def projected_ground_heading(quaternion_xyzw):
    """Geometry only: body longitudinal +X projected onto reference XY.

    Assumes the quaternion rotates child/body coordinates into the reference
    frame and reference +Z defines the horizontal normal. Neither assumption is
    accredited by this calculation. The norm check retains the existing 1e-3
    squared-norm tolerance; it is NOT an angular or operational slope limit.
    """
    if not isinstance(quaternion_xyzw,(tuple,list)) or len(quaternion_xyzw)!=4:
        raise RoverControlError('Quaternion must contain x,y,z,w')
    q=tuple(number(v,'quaternion component') for v in quaternion_xyzw)
    norm=math.hypot(*q)
    if not math.isfinite(norm) or norm==0. or abs(norm*norm-1.)>1e-3:
        raise RoverControlError('Non-unit orientation quaternion')
    x,y,z,w=(v/norm for v in q)  # normalize only already-near-unit numerical input
    forward=(1.-2.*(y*y+z*z),2.*(x*y+w*z),2.*(x*z-w*y))
    horizontal=math.hypot(forward[0],forward[1])
    # Numerical conditioning only, dimensionless; not a safe tilt threshold.
    if horizontal<=math.sqrt(math.ulp(1.)):
        raise RoverControlError('Degenerate longitudinal heading projection')
    up_z=max(-1.,min(1.,1.-2.*(x*x+y*y)))
    return {'heading_rad':math.atan2(forward[1],forward[0]),
            'forward_in_reference':forward,'horizontal_forward_norm':horizontal,
            'input_norm':norm,'normalization_applied':norm!=1.,
            'body_up_inclination_rad':math.acos(up_z),
            'method':'LONGITUDINAL_AXIS_HORIZONTAL_PROJECTION',
            'frame_association_verified':False,'operational_slope_approved':False}


def transform_ground_point(point_xy_m,translation_xy_m,rotation_rad):
    """Pure SE(2) target calculation, NOT a calibrated frame transformation.

    p_target = translation + R(rotation_rad) p_source, CCW, metres/radians.
    No frame, identity, approval flag or MotionBinding is created from numbers.
    """
    for value in (point_xy_m,translation_xy_m):
        if not isinstance(value,(tuple,list)) or len(value)!=2:
            raise RoverControlError('Explicit two-dimensional point/translation required')
        for v in value:number(v,'transform coordinate')
    angle=number(rotation_rad,'transform rotation');c,s=math.cos(angle),math.sin(angle)
    x,y=point_xy_m;tx,ty=translation_xy_m
    result=(tx+c*x-s*y,ty+s*x+c*y)
    for v in result:number(v,'transformed coordinate')
    return result


class GoalController:
    """Pure feedback decisions; phase changes never grant new time budgets.

    Initial approach uses progress_m. Recovery after an observed arrival uses
    min(progress_m, tolerance_m) as spatial hysteresis: reaching a small goal
    cannot require beating a distance minimum from a completed approach.
    Neither a displacement nor re-entry itself counts as progress. Within one
    recovery episode, only new watermarks count (not back-and-forth travel).
    """
    def __init__(self, goal, limits):
        self.goal,self.limits=goal,limits
        self.inside_since=None
        self.best_distance=self.best_heading=math.inf
        self.last_progress=None
        self.started=None
        self.last_step=None
        self.phase=None
        self.ever_inside=False
        self.was_inside=False
        self.heading_mode=None
        self.progress_age_s=0.

    def step(self, x, y, yaw, now, *, linear_speed=0., angular_speed=0.):
        g=self.goal
        for value in (x,y,yaw,now,linear_speed,angular_speed):number(value,'controller observation')
        if linear_speed<0 or angular_speed<0:raise RoverControlError('Invalid speed norm')
        if self.started is None:self.started=now
        if self.last_step is not None and now<self.last_step:raise RoverControlError('Controller clock regressed')
        if now-self.started>=g.timeout_s:raise RoverControlError('GOAL_TIMEOUT')
        distance=math.hypot(g.x_m-x,g.y_m-y)
        heading_mode='PATH' if distance>g.tolerance_m else 'FINAL'
        target_heading=math.atan2(g.y_m-y,g.x_m-x) if heading_mode=='PATH' else g.yaw_rad
        error=wrap_angle(target_heading-yaw)
        inside=distance<=g.tolerance_m and abs(wrap_angle(g.yaw_rad-yaw))<=g.yaw_tolerance_rad
        stationary=linear_speed<=self.limits.stopped_linear_mps and angular_speed<=self.limits.stopped_angular_rad_s
        phase='DWELL' if inside and stationary else ('RECOVERY' if self.ever_inside else 'APPROACH')
        # Pause only for two consecutive valid dwell observations. Transitions
        # conservatively charge their whole interval and never reset elapsed time.
        if self.last_step is not None and not (self.phase=='DWELL' and phase=='DWELL'):
            self.progress_age_s+=now-self.last_step
        fresh_recovery=(self.was_inside and not inside) or (self.phase=='DWELL' and phase!='DWELL')
        if self.last_step is None or fresh_recovery:
            self.best_distance=distance  # baseline, NOT progress credit
            self.best_heading=abs(error)
        elif self.heading_mode!=heading_mode:
            self.best_heading=abs(error)  # a different angular target is not progress
        quantum=min(g.progress_m,g.tolerance_m) if self.ever_inside else g.progress_m
        distance_progress=self.best_distance-distance>=quantum
        heading_progress=self.best_heading-abs(error)>=g.progress_rad
        if distance_progress:self.best_distance=distance
        if heading_progress:self.best_heading=abs(error)
        if distance_progress or heading_progress:
            self.progress_age_s=0.;self.last_progress=now
        elif self.last_progress is None:self.last_progress=now
        self.last_step=now;self.phase=phase;self.heading_mode=heading_mode
        self.ever_inside=self.ever_inside or inside
        self.was_inside=inside
        if phase=='DWELL':
            if self.inside_since is None:self.inside_since=now
            return {'forward_mps':0.,'yaw_rate_rad_s':0.,'distance_m':distance,
                    'inside':True,'stationary':True,'reached':now-self.inside_since>=g.dwell_s,
                    'phase':phase,'progress_age_s':self.progress_age_s,'progress_quantum_m':quantum}
        self.inside_since=None
        if self.progress_age_s>=g.no_progress_s:raise RoverControlError('NO_PROGRESS')
        return {'forward_mps':min(self.limits.max_forward_mps,distance)*max(0.,math.cos(error))
                    if distance>g.tolerance_m and abs(error)<math.pi/2 else 0.,
                'yaw_rate_rad_s':0. if inside else max(-self.limits.max_yaw_rate_rad_s,min(self.limits.max_yaw_rate_rad_s,error)),
                'distance_m':distance,'inside':inside,'stationary':stationary,'reached':False,
                'phase':phase,'progress_age_s':self.progress_age_s,'progress_quantum_m':quantum}


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

    def _observation_phase(self,phase):
        method=getattr(self.adapter,'observation_phase',None)
        if method is not None:method(phase)

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
            record['deadline_enforcement']='POSIX_SAME_MAIN_THREAD_NO_BACKGROUND_SENDER'
            with synchronous_deadline(timeout):
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

    def stop(self,*,force_zero=False):
        self._require_adapter()
        if type(force_zero) is not bool:raise RoverControlError('Explicit stop zero policy required')
        start_index = len(self.diagnostics)
        deadline = self.clock.monotonic() + self.limits.stop_timeout_s
        def remaining(slots=1):
            # Reserve a share for each remaining distinct stop operation. A
            # failed data read must not consume the zero/HOLD attempt budgets.
            return min(self.limits.call_timeout_s, number(deadline-self.clock.monotonic(), 'stop time remaining', positive=True)/slots)
        observation_error=None
        try:
            try:
                self._observation_phase('S')
                if getattr(getattr(self.adapter,'session',None),'observation_source',None) is not None:
                    before,_=self._operation('current_stop_state','same supervised source cache',remaining(6),self.adapter.current)
                    self._validate(before)
                else:before = self._observe(remaining(6))
            except Exception as exc:
                observation_error=error_evidence(exc);before=None
                # Only an independently revalidated, previously acquired target
                # may authorize stop without the preliminary data observation.
                check=getattr(self.adapter,'require_stop_target',None)
                if check is None:raise RoverControlError('Observation lost; no current protected stop target') from exc
                self._operation('verify_stop_target','same-session zero/HOLD',remaining(5),check)
            zero_error = None
            if force_zero or before is None or before.mode == int(RoverMode.GUIDED) and before.armed:
                try:
                    self._publish(self.velocity_message(0.0, 0.0), remaining(4))
                except Exception as exc:
                    # A failed zero write must not suppress the distinct HOLD attempt.
                    zero_error = error_evidence(exc)
            self._switch(RoverMode.HOLD, remaining(3))  # no TAKEOFF/LAND/disarm
            after_command = self.clock.monotonic()
            samples = [self._observe(remaining(2)), self._observe(remaining())]
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
                    'pre_stop_observation_error':observation_error,
                    'diagnostics': deepcopy(self.diagnostics[start_index:])}
        except Exception as exc:
            return {'status': 'UNCONFIRMED', 'stationary_observed': False,
                    'ground_contact_confirmed': False, 'error_evidence': error_evidence(exc),
                    'pre_stop_observation_error':observation_error,
                    'diagnostics': deepcopy(self.diagnostics[start_index:])}

    def finalize_disarmed(self, stop, *, timeout_s):
        """Explicit new-job policy only, after observed stop. Never arms."""
        started=self.clock.monotonic();deadline=started+number(timeout_s,'finalization timeout',positive=True)
        evidence={'policy':'DISARM_AFTER_OBSERVED_STOP_V1','status':'UNCONFIRMED',
                  'disarm_attempted':False,'disarm_acknowledged':False,'observations':[],
                  'stationary_observed':False,'disarmed_observed':False}
        def remaining():return min(self.limits.call_timeout_s,number(deadline-self.clock.monotonic(),'finalization remaining',positive=True))
        def identity(obs):return (obs.status_publisher_gid,obs.odometry_publisher_gid,obs.observation_provenance_sha256,obs.pose_frame)
        try:
            if not stop or stop.get('status')!='STATIONARY_OBSERVED' or len(stop.get('observations',[]))!=2:
                raise RoverControlError('Finalization requires independently observed stop')
            anchor=Observation(**stop['observations'][-1])
            if getattr(getattr(self.adapter,'session',None),'observation_source',None) is not None:
                before,_=self._operation('current_finalization_state','same supervised source cache',remaining(),self.adapter.current)
                self._validate(before)
                self._progress(Observation(**stop['observations'][0]),before,motion=True)
            else:
                before=self._observe(remaining());self._progress(anchor,before,motion=True)
            self._validate_motion(before)
            if (identity(before)!=identity(anchor) or before.mode!=int(RoverMode.HOLD) or before.flying or before.failsafe):
                raise RoverControlError('Finalization source/HOLD/stop inconsistent')
            if before.armed:
                command={'kind':'service','endpoint':'/ap/v3/arm_motors',
                         'type':'ardupilot_msgs/srv/ArmMotors','payload':{'arm':False}}
                evidence['disarm_attempted']=True
                reply,record=self._operation('disarm_after_observed_stop',command['endpoint'],remaining(),
                    lambda:self.adapter.exchange(deepcopy(command),timeout_s=remaining()),command=command)
                if not transport_completed(reply) or not isinstance(reply.payload,dict) or type(reply.payload.get('result')) is not bool:
                    raise RoverControlError('Disarm response absent or uninterpretable')
                if reply.payload['result'] is not True:raise RoverControlError('Disarm rejected')
                evidence['disarm_acknowledged']=True
                record['effects']='ACKNOWLEDGED_NOT_OBSERVED'
            self._observation_phase('D')
            after_command=self.clock.monotonic()
            samples=[self._observe(remaining()),self._observe(remaining())]
            self._progress(before,samples[0],motion=True);self._progress(*samples,motion=True)
            for obs in samples:
                self._validate_motion(obs)
                if (identity(obs)!=identity(anchor) or obs.armed or obs.flying or obs.failsafe or
                    obs.mode!=int(RoverMode.HOLD) or obs.received_monotonic_s<after_command or
                    obs.motion_received_monotonic_s<after_command):
                    raise RoverControlError('Post-disarm state/source not confirmed')
            evidence.update(status='DISARMED_STATIONARY_OBSERVED',stationary_observed=True,
                            disarmed_observed=True,observations=[asdict(o) for o in samples])
        except Exception as exc:evidence['error_evidence']=error_evidence(exc)
        evidence['duration_s']=self.clock.monotonic()-started
        return evidence

    def _navigation_observation(self, obs, goal):
        self._validate(obs)
        if (obs.pose_reference_validated is not True or obs.pose_frame!=goal.frame or
            obs.pose_unit!='m' or obs.motion_source!='/model/rover1/odometry' or
            obs.motion_frame!='base_link' or obs.linear_unit!='m/s' or obs.angular_unit!='rad/s'):
            raise RoverControlError('Navigation frame/provenance contract not accredited')
        for value, size in ((obs.position_m,3),(obs.orientation_xyzw,4),
                            (obs.linear_mps,3),(obs.angular_rad_s,3),
                            (obs.pose_covariance,36),(obs.twist_covariance,36)):
            if not isinstance(value,tuple) or len(value)!=size:
                raise RoverControlError('Missing navigation pose/twist/covariance')
            for v in value:number(v,'navigation component')
        for value,size in ((obs.odometry_publisher_gid,48),(obs.observation_provenance_sha256,64)):
            if not isinstance(value,str) or len(value)!=size or any(c not in '0123456789abcdef' for c in value) or not int(value,16):
                raise RoverControlError('Missing sample GID or provenance digest')
        age=self.clock.monotonic()-number(obs.motion_received_monotonic_s,'motion receipt')
        if not 0<=age<=self.limits.observation_max_age_s:raise RoverControlError('Stale navigation pose')
        # The source/frame gate above still applies. A valid nonzero roll/pitch
        # is not a malformed quaternion; horizontal heading has its own geometry.
        yaw=projected_ground_heading(obs.orientation_xyzw)['heading_rad']
        return obs.position_m[0],obs.position_m[1],yaw

    def navigate(self, goal, *, cancelled=lambda:False):
        if not isinstance(goal,NavigationGoal):raise RoverControlError('Typed navigation goal required')
        if goal.timeout_s>self.limits.max_duration_s:raise RoverControlError('Navigation exceeds bounded trial duration')
        self._require_adapter()
        started=self.clock.monotonic();controller=GoalController(goal,self.limits)
        samples=[];decisions=[];attempted=False;stop_result=None;error=None
        outcome='NOT_ATTEMPTED';previous=None;identity=None;commands_sent=0
        try:
            for _ in range(goal.max_samples):
                if cancelled():raise RoverControlError('CANCELLED')
                if self.clock.monotonic()-started>=goal.timeout_s:raise RoverControlError('GOAL_TIMEOUT')
                remaining=min(self.limits.call_timeout_s,goal.timeout_s-(self.clock.monotonic()-started))
                obs=self._observe(remaining);x,y,yaw=self._navigation_observation(obs,goal)
                current_identity=(obs.odometry_publisher_gid,obs.observation_provenance_sha256,obs.pose_frame)
                if identity is not None and current_identity!=identity:raise RoverControlError('OBSERVATION_IDENTITY_OR_FRAME_CHANGED')
                identity=current_identity
                if previous is not None:self._progress(previous,obs,motion=True)
                if obs.mode!=int(RoverMode.GUIDED) or not obs.armed or not obs.external_control or obs.failsafe:
                    raise RoverControlError('Navigation requires already armed GUIDED/external-control status')
                samples.append(asdict(obs));previous=obs
                # Two independently progressing observations before the first possible effect.
                if len(samples)<2:
                    self.clock.sleep(1/goal.command_hz);continue
                decision=controller.step(x,y,yaw,self.clock.monotonic(),
                    linear_speed=math.sqrt(sum(v*v for v in obs.linear_mps)),
                    angular_speed=math.sqrt(sum(v*v for v in obs.angular_rad_s)))
                decision['heading_geometry']=projected_ground_heading(obs.orientation_xyzw)
                decision.update(observation_index=len(samples)-1,received_monotonic_s=obs.motion_received_monotonic_s)
                decisions.append(decision)
                attempted=True
                self._publish(self.velocity_message(decision['forward_mps'],decision['yaw_rate_rad_s']),
                              min(self.limits.call_timeout_s,number(goal.timeout_s-(self.clock.monotonic()-started),'navigation remaining',positive=True)))
                commands_sent+=1
                if decision['reached']:
                    outcome='GOAL_REACHED';break
                self.clock.sleep(1/goal.command_hz)
            else:raise RoverControlError('OBSERVATION_SAMPLE_LIMIT')
        except Exception as exc:
            error=error_evidence(exc);outcome='GOAL_FAILED' if attempted else 'NOT_ATTEMPTED'
        finally:
            if attempted:
                stop_result=self.stop()
                if stop_result.get('stationary_observed'):
                    try:
                        for raw in stop_result.get('observations',[]):
                            stopped=Observation(**raw);sx,sy,syaw=self._navigation_observation(stopped,goal)
                            if outcome=='GOAL_REACHED' and (math.hypot(goal.x_m-sx,goal.y_m-sy)>goal.tolerance_m or
                                    abs(wrap_angle(goal.yaw_rad-syaw))>goal.yaw_tolerance_rad):
                                outcome='GOAL_LOST_DURING_STOP'
                            if (stopped.odometry_publisher_gid,stopped.observation_provenance_sha256,stopped.pose_frame)!=identity:
                                raise RoverControlError('Stop observation identity changed')
                    except Exception as exc:
                        stop_result={**stop_result,'status':'UNCONFIRMED','stationary_observed':False,
                                     'identity_error':error_evidence(exc)}
        confirmed=bool(stop_result and stop_result.get('status')=='STATIONARY_OBSERVED')
        return {'status':'STOP_OBSERVED' if outcome=='GOAL_REACHED' and confirmed else
                         'UNCONFIRMED' if attempted else 'NOT_ATTEMPTED',
                'goal_outcome':outcome,'goal':asdict(goal),'motion_command_attempted':attempted,
                'commands_sent':commands_sent,'motion_application_confirmed':False,
                'stop_requested':attempted,'stop':stop_result,'error_evidence':error,
                'started_monotonic_s':started,'decision_monotonic_s':self.clock.monotonic(),
                'observation_samples':samples,'decisions':decisions,
                'sample_limit':goal.max_samples,'samples_truncated':False,
                'movement_observed':'NOT_INDEPENDENTLY_ACCREDITED','ground_contact_confirmed':False}

    def _pulse_base(self,obs,safety):
        self._validate(obs)
        if (obs.pose_reference_validated is not True or obs.pose_frame!=safety.pose_frame or obs.pose_unit!='m' or
                obs.observation_provenance_sha256!=safety.binding_sha256 or obs.motion_frame!='base_link'):
            raise RoverControlError('Pulse body/frame/provenance unknown or changed')
        for gid in (obs.status_publisher_gid,obs.odometry_publisher_gid):
            if not isinstance(gid,str) or len(gid)!=48 or any(c not in '0123456789abcdef' for c in gid) or not int(gid,16):
                raise RoverControlError('Pulse per-message identity missing')
        if obs.position_m is None or len(obs.position_m)!=3:raise RoverControlError('Pulse local position absent')
        for v in obs.position_m:number(v,'pulse position')
        geometry=projected_ground_heading(obs.orientation_xyzw)
        if geometry['body_up_inclination_rad']>safety.max_slope_rad:raise RoverControlError('PULSE_SLOPE_LIMIT')
        return geometry['heading_rad']

    def prepare_guided_armed(self,*,safety,timeout_s,cancelled=lambda:False):
        """Exact PREPARING job actor; requests are distinct from observations."""
        deadline=self.clock.monotonic()+number(timeout_s,'preparation timeout',positive=True)
        evidence={'status':'UNCONFIRMED','mode_attempted':False,'mode_acknowledged':False,
            'arm_attempted':False,'arm_acknowledged':False,'observations':[],'stop':None}
        identity=lambda o:(o.status_publisher_gid,o.odometry_publisher_gid,o.observation_provenance_sha256,o.pose_frame)
        def remaining():return min(self.limits.call_timeout_s,number(deadline-self.clock.monotonic(),'preparation remaining',positive=True))
        def pair(mode=None,armed=None,after=None):
            # The already verified probe pair may serve as the first initial
            # sample. Post-command pairs always require two new observations.
            values=([self.adapter.current(),self._observe(remaining())] if not evidence['observations'] and after is None else
                    [self._observe(remaining()),self._observe(remaining())])
            self._progress(*values,motion=True)
            for obs in values:
                self._pulse_base(obs,safety);self._validate_motion(obs)
                if obs.flying or obs.failsafe or identity(obs)!=identity(values[0]):raise RoverControlError('Preparation state/source inconsistent')
                if mode is not None and (obs.mode!=mode or not obs.external_control):raise RoverControlError('GUIDED state not observed')
                if armed is not None and obs.armed is not armed:raise RoverControlError('Arm state not observed')
                if after is not None and min(obs.received_monotonic_s,obs.motion_received_monotonic_s)<after:raise RoverControlError('Preparation observation predates command')
                if evidence['observations'] and identity(obs)!=identity(Observation(**evidence['observations'][0])):raise RoverControlError('Preparation identity changed')
            evidence['observations'].extend(asdict(v) for v in values)
            return values
        try:
            if cancelled():raise RoverControlError('CANCELLED')
            self._observation_phase('I')
            values=pair();before=values[-1]
            self._observation_phase('P')
            if any(v.mode!=before.mode or v.armed!=before.armed for v in values):raise RoverControlError('Preparation initial state changed')
            if before.armed and before.mode!=int(RoverMode.GUIDED):raise RoverControlError('Already armed in another mode')
            if before.mode!=int(RoverMode.GUIDED):
                evidence['mode_attempted']=True;self._switch(RoverMode.GUIDED,remaining());evidence['mode_acknowledged']=True
                values=pair(int(RoverMode.GUIDED),False,self.clock.monotonic())
            if cancelled():raise RoverControlError('CANCELLED')
            if not values[-1].external_control:raise RoverControlError('GUIDED external control absent')
            if not values[-1].armed:
                command={'kind':'service','endpoint':'/ap/v3/arm_motors','type':'ardupilot_msgs/srv/ArmMotors','payload':{'arm':True}}
                evidence['arm_attempted']=True
                reply,record=self._operation('prepare_arm',command['endpoint'],remaining(),lambda:self.adapter.exchange(command,timeout_s=remaining()),command=command)
                if not transport_completed(reply) or not isinstance(reply.payload,dict) or reply.payload.get('result') is not True:
                    raise RoverControlError('Arm response rejected/absent')
                evidence['arm_acknowledged']=True;record['effects']='ACKNOWLEDGED_NOT_OBSERVED'
                values=pair(int(RoverMode.GUIDED),True,self.clock.monotonic())
            if cancelled():raise RoverControlError('CANCELLED')
            evidence.update(status='GUIDED_ARMED_STATIONARY_OBSERVED',initial_observations=[asdict(v) for v in values])
        except BaseException as exc:
            evidence['error_evidence']=error_evidence(exc)
            if evidence['mode_attempted'] or evidence['arm_attempted']:evidence['stop']=self.stop(force_zero=True)
            if not isinstance(exc,Exception):raise
        return evidence

    def move_for(self, forward_mps, yaw_rate_rad_s, duration_s, *, linear_unit='m/s', angular_unit='rad/s', cancelled=lambda:False, safety=None, initial_observations=None):
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
        samples=[];started=self.clock.monotonic();response_m=0.
        try:
            if not isinstance(safety,PulseSafety):raise RoverControlError('Reviewed pulse safety contract required')
            if safety.speed_abort_mps<forward_mps:raise RoverControlError('Command exceeds reviewed observed speed envelope')
            end=started+safety.total_timeout_s
            def remaining_motion():
                return min(self.limits.call_timeout_s,number(end-self.clock.monotonic()-self.limits.stop_timeout_s-safety.close_budget_s,'reserved pulse time',positive=True))
            def checked(obs,anchor=None):
                nonlocal response_m
                if len(samples)>=128:raise RoverControlError('Pulse observation budget exhausted')
                yaw=self._pulse_base(obs,safety)
                if (obs.mode!=int(RoverMode.GUIDED) or not obs.armed or not obs.external_control or obs.failsafe):
                    raise RoverControlError('Pulse requires already armed GUIDED/external-control status')
                age=self.clock.monotonic()-number(obs.motion_received_monotonic_s,'pulse motion receipt')
                if not 0<=age<=self.limits.observation_max_age_s:raise RoverControlError('Pulse motion stale/future')
                if obs.motion_source!='/model/rover1/odometry' or obs.linear_unit!='m/s' or obs.angular_unit!='rad/s':raise RoverControlError('Pulse motion contract changed')
                norms=[]
                for vector in (obs.linear_mps,obs.angular_rad_s):
                    if not isinstance(vector,tuple) or len(vector)!=3:raise RoverControlError('Pulse motion vector absent')
                    norms.append(math.sqrt(sum(number(v,'pulse velocity')**2 for v in vector)))
                if norms[0]>safety.speed_abort_mps or norms[1]>safety.angular_abort_rad_s:raise RoverControlError('PULSE_SPEED_LIMIT')
                if anchor is not None:
                    if (obs.status_publisher_gid,obs.odometry_publisher_gid)!=(anchor.status_publisher_gid,anchor.odometry_publisher_gid):raise RoverControlError('PULSE_IDENTITY_CHANGED')
                    delta=[a-b for a,b in zip(obs.position_m,anchor.position_m)]
                    if math.sqrt(sum(v*v for v in delta))>=safety.displacement_abort_m:raise RoverControlError('PULSE_DISPLACEMENT_LIMIT')
                    ayaw=projected_ground_heading(anchor.orientation_xyzw)['heading_rad']
                    if abs(wrap_angle(yaw-ayaw))>safety.heading_abort_rad:raise RoverControlError('PULSE_HEADING_LIMIT')
                    # Actual +X of the accredited initial quaternion in local pose frame.
                    ax,ay,az,aw=anchor.orientation_xyzw
                    forward=(1-2*(ay*ay+az*az),2*(ax*ay+aw*az),2*(ax*az-aw*ay))
                    along=sum(a*b for a,b in zip(delta,forward))
                    if along < -2*safety.position_error_m:raise RoverControlError('PULSE_REVERSE_RESPONSE')
                    response_m=max(response_m,along)
                samples.append(asdict(obs));return obs
            if cancelled():raise RoverControlError('CANCELLED')
            initial = ([checked(Observation(**v)) for v in initial_observations] if initial_observations is not None else
                       [checked(self._observe(remaining_motion())), checked(self._observe(remaining_motion()))])
            if len(initial)!=2:raise RoverControlError('Two prepared initial observations required')
            self._progress(*initial, motion=True)
            for sample in initial:
                self._validate_motion(sample)  # BEFORE the first possible motion command
            if any(v.mode != int(RoverMode.GUIDED) or not v.armed or not v.external_control or v.failsafe for v in initial):
                raise RoverControlError('Rover must already be GUIDED, armed, external-control ready, no failsafe')
            if cancelled():raise RoverControlError('CANCELLED')
            checked(initial[1],initial[0])
            self._observation_phase('W')
            attempted = True
            motion_started=self.clock.monotonic();ticks=0
            deadline=min(motion_started+duration,end-self.limits.stop_timeout_s-safety.close_budget_s)
            self._publish(message,min(remaining_motion(),number(deadline-self.clock.monotonic(),'pulse publication budget',positive=True)))
            previous=initial[-1]
            while self.clock.monotonic()<deadline:
                if cancelled():raise RoverControlError('CANCELLED')
                timeout=min(remaining_motion(),deadline-self.clock.monotonic(),safety.interval_s)
                if timeout<=math.ulp(deadline):break  # stop one representable tick early, never extend the pulse
                tick=self.clock.monotonic();watch=getattr(self.adapter,'watch',None)
                if watch:
                    obs,_=self._operation('watch','current pulse observation',timeout,lambda:watch(timeout_s=timeout))
                    obs=checked(obs,initial[0])
                else:obs=checked(self._observe(timeout),initial[0])
                for stamp,receipt in (('status_source_ns','received_monotonic_s'),('velocity_source_ns','motion_received_monotonic_s')):
                    old=getattr(previous,stamp);new=getattr(obs,stamp);a=getattr(previous,receipt);b=getattr(obs,receipt)
                    if (type(old) is not int or type(new) is not int or new<old or b<a or
                            (b>a and new<=old) or (new>old and b<=a)):
                        raise RoverControlError('PULSE_SOURCE_FROZEN_OR_REWOUND')
                previous=obs
                ticks+=1
                # Anchor ticks to the first attempt instead of accumulating
                # floating point sleeps that can leave an infinitesimal tail.
                wake=min(deadline,motion_started+ticks*safety.interval_s)
                self.clock.sleep(max(0.,wake-self.clock.monotonic()))
        except Exception as exc:
            error = error_evidence(exc)
        finally:
            if attempted:
                stop_result = self.stop()  # same-target ground stop after any possible control effect
                if stop_result.get('stationary_observed'):
                    anchor=initial[-1]
                    for raw in stop_result.get('observations',[]):
                        stopped=Observation(**raw)
                        if (stopped.status_publisher_gid,stopped.odometry_publisher_gid,stopped.observation_provenance_sha256,stopped.pose_frame)!=(anchor.status_publisher_gid,anchor.odometry_publisher_gid,anchor.observation_provenance_sha256,anchor.pose_frame):
                            stop_result={**stop_result,'status':'UNCONFIRMED','stationary_observed':False,'identity_error':'Pulse stop observation identity/frame changed'}
                            break
        return {'status': 'STOP_OBSERVED' if error is None and stop_result and stop_result['status'] == 'STATIONARY_OBSERVED' else
                         'UNCONFIRMED' if attempted else 'NOT_ATTEMPTED',
                'motion_command_attempted': attempted, 'motion_application_confirmed': False,
                'error_evidence': error, 'stop': stop_result,
                'observation_samples':samples,'response_forward_m':response_m,
                'response_observed':bool(safety and response_m>=safety.minimum_response_m),
                'elapsed_s':self.clock.monotonic()-started,
                'diagnostics': deepcopy(self.diagnostics[start_index:]),
                'note': 'Internal adapter core only; no production authority, mission or distance acceptance.'}
