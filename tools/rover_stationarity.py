"""Offline verifier for passive rover stationarity captures; grants no movement authority."""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class StationarityThresholds:
    minimum_observations: int = 100
    minimum_duration_s: float = 30.0
    maximum_sample_age_s: float = 1.0
    maximum_gap_s: float = 2.0
    maximum_horizontal_displacement_m: float = 0.05
    maximum_vertical_displacement_m: float = 0.05
    maximum_displacement_m: float = 0.05
    maximum_cumulative_drift_m: float = 0.10
    maximum_linear_speed_mps: float = 0.03
    maximum_angular_speed_rad_s: float = 0.03
    maximum_orientation_change_rad: float = 0.02
    maximum_yaw_drift_rad: float = 0.02
    minimum_valid_percent: float = 100.0


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _vector(v, keys):
    if not isinstance(v, dict) or any(not _finite(v.get(k)) for k in keys):
        return None
    return tuple(float(v[k]) for k in keys)


def _norm(v):
    return math.sqrt(sum(x*x for x in v))


def _yaw(q):
    value=_vector(q,('x','y','z','w'))
    if value is None:return None
    x,y,z,w=value;norm=_norm(value)
    if norm<1e-9:return None
    x,y,z,w=(v/norm for v in value)
    return math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))

def _yaw_delta(a,b):
    ya,yb=_yaw(a),_yaw(b)
    if ya is None or yb is None:return None
    return abs((yb-ya+math.pi)%(2*math.pi)-math.pi)

def _orientation_delta(a, b):
    qa, qb = _vector(a, ('x','y','z','w')), _vector(b, ('x','y','z','w'))
    if qa is None or qb is None:
        return None
    na, nb = _norm(qa), _norm(qb)
    if na < 1e-9 or nb < 1e-9:
        return None
    dot = abs(sum(x*y for x,y in zip(qa,qb)) / (na*nb))
    return 2.0 * math.acos(min(1.0, dot))


def analyze(capture, *, expected_lifecycle, expected_boot_id, expected_status_gid,
            expected_odometry_gid, expected_frame='odom', expected_child_frame='base_link',
            thresholds=StationarityThresholds(), worker_closed=True):
    """Return a fail-closed report. Clocks are compared only within their named domains."""
    reasons=[]; rows=capture.get('records') if isinstance(capture,dict) else None
    if not isinstance(rows,list) or not rows:
        rows=[]; reasons.append('NO_CAPTURE_RECORDS')
    if not isinstance(capture,dict) or capture.get('capture_complete') is not True: reasons.append('CAPTURE_INCOMPLETE')
    if not isinstance(capture,dict) or capture.get('movement_authorized') is not False or capture.get('commands_sent') != 0:
        reasons.append('CAPTURE_NOT_PASSIVE_OR_COMMANDS_PRESENT')
    if not worker_closed: reasons.append('WORKER_CLOSE_UNCONFIRMED')
    usable=[]; invalid=0
    for i,r in enumerate(rows):
        if not isinstance(r,dict): invalid+=1; continue
        meta=r.get('sample_metadata') or {}; sm=meta.get('status') or {}; om=meta.get('odometry') or {}
        host=r.get('host_received_monotonic_s'); hs=sm.get('received_monotonic_s'); ho=om.get('received_monotonic_s')
        ss=sm.get('stamp_ns'); os=om.get('stamp_ns')
        pos=_vector(r.get('position'),('x','y','z')); ori=r.get('orientation')
        lin=_vector(r.get('linear_velocity'),('x','y','z')); ang=_vector(r.get('angular_velocity'),('x','y','z'))
        status=r.get('status') or {}; ages=r.get('worker_telemetry_age_s') or {}; units=r.get('measurement_units') or {}
        checks=[r.get('lifecycle_id')==expected_lifecycle, r.get('host_boot_id')==expected_boot_id,
                r.get('status_publisher_gid')==expected_status_gid, r.get('odometry_publisher_gid')==expected_odometry_gid,
                r.get('frame_id')==expected_frame, r.get('child_frame_id')==expected_child_frame,
                r.get('host_clock')=='HOST_MONOTONIC_S', sm.get('stamp_clock')=='SIMULATED_STAMP_NS' and om.get('stamp_clock')=='SIMULATED_STAMP_NS',
                sm.get('receipt_clock')=='WORKER_MONOTONIC_S' and om.get('receipt_clock')=='WORKER_MONOTONIC_S',
                _finite(host),_finite(hs),_finite(ho),type(ss)is int,type(os)is int,
                pos is not None, _vector(ori,('x','y','z','w')) is not None,lin is not None,ang is not None,
                units=={'position':'m','linear_velocity':'m/s','angular_velocity':'rad/s','orientation':'quaternion_xyzw'},
                status.get('armed') is False, status.get('flying') is False, r.get('driving') is False,
                isinstance(status.get('failsafe'),list) and not status.get('failsafe'),
                _finite(ages.get('status')) and ages['status']<=thresholds.maximum_sample_age_s,
                _finite(ages.get('odometry')) and ages['odometry']<=thresholds.maximum_sample_age_s]
        if not all(checks): invalid+=1; continue
        usable.append({'host':float(host),'worker_status':float(hs),'worker_odom':float(ho),
                       'status_stamp':ss,'odom_stamp':os,'position':pos,'orientation':r['orientation'],
                       'linear':lin,'angular':ang})
    valid_pct=100.0*len(usable)/len(rows) if rows else 0.0
    if invalid: reasons.append('INVALID_OR_UNATTRIBUTED_OBSERVATIONS')
    if len(rows)<thresholds.minimum_observations: reasons.append('OBSERVATION_COUNT_BELOW_MINIMUM')
    if len(usable)<2:
        reasons.append('INSUFFICIENT_VALID_OBSERVATIONS')
        return {'schema':'tfg.rover.stationarity-analysis/1','verdict':'UNCONFIRMED','reasons':reasons,
                'observations_total':len(rows),'observations_valid':len(usable),'observations_invalid':invalid,
                'valid_percent':valid_pct,'movement_authorized':False,'thresholds':asdict(thresholds)}
    hosts=[r['host'] for r in usable]; gaps=[b-a for a,b in zip(hosts,hosts[1:])]
    duration=hosts[-1]-hosts[0]; max_gap=max(gaps,default=0)
    if any(b['host']<=a['host'] for a,b in zip(usable,usable[1:])): reasons.append('HOST_TIMESTAMPS_NOT_INCREASING')
    if any(b['status_stamp']<=a['status_stamp'] or b['odom_stamp']<=a['odom_stamp'] for a,b in zip(usable,usable[1:])): reasons.append('SOURCE_STAMPS_NOT_STRICTLY_INCREASING')
    if any(b['worker_status']<=a['worker_status'] or b['worker_odom']<=a['worker_odom'] for a,b in zip(usable,usable[1:])): reasons.append('RECEIPT_TIMESTAMPS_NOT_STRICTLY_INCREASING')
    points=[r['position'] for r in usable]; origin=points[0]
    distances=[_norm(tuple(p[j]-origin[j] for j in range(3))) for p in points]
    horizontal=max((math.hypot(p[0]-origin[0],p[1]-origin[1]) for p in points),default=0)
    vertical=max((abs(p[2]-origin[2]) for p in points),default=0)
    path=sum(_norm(tuple(b[j]-a[j] for j in range(3))) for a,b in zip(points,points[1:]))
    max_speed=max(_norm(r['linear']) for r in usable); max_angular=max(_norm(r['angular']) for r in usable)
    orient=max((_orientation_delta(usable[0]['orientation'],r['orientation']) for r in usable),default=None)
    yaw_values=[_yaw(r['orientation']) for r in usable]
    yaw_deltas=[_yaw_delta(usable[0]['orientation'],r['orientation']) for r in usable]
    max_yaw=max((v for v in yaw_deltas if v is not None),default=None)
    final_yaw_delta=yaw_deltas[-1] if yaw_deltas else None
    metrics={'pose_initial':{'position_m':list(usable[0]['position']),'orientation_xyzw':usable[0]['orientation']},
             'pose_final':{'position_m':list(usable[-1]['position']),'orientation_xyzw':usable[-1]['orientation']},
             'yaw_initial_rad':yaw_values[0],'yaw_final_rad':yaw_values[-1],
             'yaw_drift_final_rad':final_yaw_delta,'yaw_drift_max_rad':max_yaw,
             'coverage_s':duration,'maximum_gap_s':max_gap,'horizontal_displacement_max_m':horizontal,
             'vertical_displacement_max_m':vertical,'displacement_from_start_max_m':max(distances),
             'cumulative_drift_m':path,'linear_speed_max_mps':max_speed,
             'angular_speed_max_rad_s':max_angular,'orientation_change_max_rad':orient,
             'valid_percent':valid_pct,'observations_required_minimum':thresholds.minimum_observations}
    if duration<thresholds.minimum_duration_s: reasons.append('INSUFFICIENT_COVERAGE')
    if max_gap>thresholds.maximum_gap_s: reasons.append('TELEMETRY_GAP_EXCEEDED')
    if valid_pct<thresholds.minimum_valid_percent: reasons.append('VALID_PERCENT_BELOW_THRESHOLD')
    if (horizontal>thresholds.maximum_horizontal_displacement_m or vertical>thresholds.maximum_vertical_displacement_m
            or max(distances)>thresholds.maximum_displacement_m): reasons.append('POSITION_DRIFT_EXCEEDED')
    if path>thresholds.maximum_cumulative_drift_m: reasons.append('CUMULATIVE_DRIFT_EXCEEDED')
    if max_speed>thresholds.maximum_linear_speed_mps: reasons.append('LINEAR_SPEED_EXCEEDED')
    if max_angular>thresholds.maximum_angular_speed_rad_s: reasons.append('ANGULAR_SPEED_EXCEEDED')
    if orient is None or orient>thresholds.maximum_orientation_change_rad: reasons.append('ORIENTATION_CHANGE_EXCEEDED_OR_UNKNOWN')
    if max_yaw is None or max_yaw>thresholds.maximum_yaw_drift_rad: reasons.append('YAW_DRIFT_EXCEEDED_OR_UNKNOWN')
    return {'schema':'tfg.rover.stationarity-analysis/1','verdict':'STATIONARY_OBSERVED' if not reasons else 'UNCONFIRMED',
            'reasons':reasons,'observations_total':len(rows),'observations_valid':len(usable),
            'observations_invalid':invalid,'metrics':metrics,'thresholds':asdict(thresholds),
            'clock_domains':['HOST_MONOTONIC_S','WORKER_MONOTONIC_S','SIMULATED_STAMP_NS'],
            'movement_authorized':False,'commands_sent':0}
