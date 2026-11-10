"""Offline metrics for a future, separately authorized rover stop trace.

This analyzer derives observed values from timestamped samples. It never emits a
control, and parameter values or theoretical braking models are not accepted as
substitutes for measured motion.
"""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class Thresholds:
    maximum_sample_age_s: float = 0.2
    maximum_gap_s: float = 1.0
    stopped_linear_mps: float = 0.03
    stopped_angular_rad_s: float = 0.03
    reaction_speed_drop_mps: float = 0.01


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _vec(value, n):
    if not isinstance(value, (list, tuple)) or len(value) != n or not all(_finite(x) for x in value):
        return None
    return tuple(float(x) for x in value)


def _norm(value):
    return math.sqrt(sum(x*x for x in value))


def analyze(trace, *, thresholds=Thresholds()):
    """Return an observed-trace report or UNCONFIRMED; makes no safety claim."""
    reasons=[]
    if not isinstance(trace,dict):
        return {'schema':'tfg.rover.failsafe-analysis/1','verdict':'UNCONFIRMED',
                'reasons':['TRACE_MALFORMED'],'movement_authorized':False}
    rows=trace.get('records')
    if trace.get('schema')!='tfg.rover.failsafe-trace/1': reasons.append('TRACE_SCHEMA_UNKNOWN')
    if trace.get('capture_complete') is not True: reasons.append('CAPTURE_INCOMPLETE')
    identity=trace.get('identity') or {}
    loss=trace.get('loss_event') or {}
    loss_at=loss.get('monotonic_s')
    if not all(identity.get(k) for k in ('lifecycle_id','host_boot_id','status_gid','odometry_gid','frame_id','child_frame_id')):
        reasons.append('TRACE_IDENTITY_INCOMPLETE')
    if not _finite(loss_at): reasons.append('LOSS_EVENT_TIME_MISSING')
    if not isinstance(rows,list) or len(rows)<2:
        reasons.append('INSUFFICIENT_TRACE_SAMPLES')
        rows=[]
    usable=[]
    for row in rows:
        if not isinstance(row,dict): reasons.append('MALFORMED_SAMPLE'); continue
        t=row.get('host_monotonic_s'); pos=_vec(row.get('position_m'),3); linear=_vec(row.get('linear_velocity_mps'),3); angular=_vec(row.get('angular_velocity_rad_s'),3)
        ages=row.get('telemetry_age_s') or {}; status=row.get('status') or {}
        checks=[_finite(t),pos is not None,linear is not None,angular is not None,
                row.get('lifecycle_id')==identity.get('lifecycle_id'),row.get('host_boot_id')==identity.get('host_boot_id'),
                row.get('status_gid')==identity.get('status_gid'),row.get('odometry_gid')==identity.get('odometry_gid'),
                row.get('frame_id')==identity.get('frame_id'),row.get('child_frame_id')==identity.get('child_frame_id'),
                row.get('position_unit')=='m',row.get('linear_velocity_unit')=='m/s',row.get('angular_velocity_unit')=='rad/s',
                _finite(ages.get('status')) and ages['status']<=thresholds.maximum_sample_age_s,
                _finite(ages.get('odometry')) and ages['odometry']<=thresholds.maximum_sample_age_s,
                type(status.get('armed')) is bool, isinstance(status.get('failsafe'),list)]
        if not all(checks): reasons.append('SAMPLE_INVALID_OR_STALE'); continue
        usable.append({'t':float(t),'p':pos,'v':linear,'w':angular,'status':status,
                       'status_age':float(ages['status']),'odometry_age':float(ages['odometry'])})
    if len(usable)!=len(rows): reasons.append('TRACE_COVERAGE_INCOMPLETE')
    if len(usable)>=2:
        if any(b['t']<=a['t'] for a,b in zip(usable,usable[1:])): reasons.append('TIMESTAMPS_NOT_STRICTLY_INCREASING')
        gaps=[b['t']-a['t'] for a,b in zip(usable,usable[1:])]
        if gaps and max(gaps)>thresholds.maximum_gap_s: reasons.append('SAMPLE_GAP_EXCEEDED')
    else: gaps=[]
    if not _finite(loss_at) or not usable or not (usable[0]['t']<=loss_at<=usable[-1]['t']):
        reasons.append('LOSS_EVENT_OUTSIDE_CAPTURE')
    if reasons:
        return {'schema':'tfg.rover.failsafe-analysis/1','verdict':'UNCONFIRMED','reasons':list(dict.fromkeys(reasons)),
                'samples_total':len(rows),'samples_usable':len(usable),'thresholds':asdict(thresholds),
                'source_class':trace.get('source_class'),'movement_authorized':False}
    before=[r for r in usable if r['t']<=loss_at]
    after=[r for r in usable if r['t']>=loss_at]
    if not before or not after:
        return {'schema':'tfg.rover.failsafe-analysis/1','verdict':'UNCONFIRMED','reasons':['LOSS_EVENT_NOT_BRACKETED'],
                'samples_total':len(rows),'samples_usable':len(usable),'movement_authorized':False}
    anchor=before[-1]; initial_speed=_norm(anchor['v'])
    reaction=next((r for r in after if _norm(r['v'])<=max(0.0,initial_speed-thresholds.reaction_speed_drop_mps)),None)
    stopped_index=None
    for index,row in enumerate(after):
        if all(_norm(x['v'])<=thresholds.stopped_linear_mps and _norm(x['w'])<=thresholds.stopped_angular_rad_s for x in after[index:]):
            stopped_index=index; break
    motion=[r for r in usable if loss_at<=r['t']<=after[-1]['t']]
    distances=[math.dist(anchor['p'],r['p']) for r in motion]
    path=sum(math.dist(a['p'],b['p']) for a,b in zip(motion,motion[1:]))
    final=usable[-1]
    metrics={'initial_speed_mps':initial_speed,
             'loss_to_reaction_s':None if reaction is None else reaction['t']-loss_at,
             'reaction_observed':reaction is not None,
             'loss_to_stop_s':None if stopped_index is None else after[stopped_index]['t']-loss_at,
             'stop_observed_and_held_through_capture':stopped_index is not None,
             'maximum_displacement_from_loss_position_m':max(distances,default=0.0),
             'path_length_after_loss_m':path,'maximum_sample_gap_s':max(gaps,default=0.0),
             'maximum_status_age_s':max(r['status_age'] for r in rows),
             'maximum_odometry_age_s':max(r['odometry_age'] for r in rows),
             'final_status':dict(final['status'])}
    return {'schema':'tfg.rover.failsafe-analysis/1','verdict':'OBSERVED_TRACE_METRICS',
            'reasons':[] if reaction is not None and stopped_index is not None else ['REACTION_OR_STOP_NOT_OBSERVED'],
            'metrics':metrics,'thresholds':asdict(thresholds),'samples_total':len(rows),
            'samples_usable':len(usable),'source_class':trace.get('source_class'),
            'interpretation':'Observed trace only; does not establish hardware behavior or guarantee a future stop.',
            'movement_authorized':False}
