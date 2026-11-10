"""Pipe/ROS latency of a PASSIVE rover session: measurement runner and offline analysis. Sends no commands.

Purpose: replace the ASSUMED IPC_RESERVE_S (0.25 s, tools/rover_pipe_session.py) by a measured
value in a future, separately AUTHORIZED passive session. Nothing here starts a simulator, a
lifecycle or a worker; measure_passive() only drives a session the caller already opened in
PASSIVE mode (probe/observe, which the worker serves without any publisher or service client).

Three clock domains, never mixed as timestamps:
- HOST_MONOTONIC_S: PipeRos2Session.timings (send start, send done, reply received);
- WORKER_MONOTONIC_S: the worker's reply 'timing' (received, replied, handled, telemetry ages);
- SIMULATED stamps (ns) of status/odometry headers.
Only durations measured inside one domain are computed. host_total - worker_handled is a
difference of two durations (assumes both monotonic clocks tick at the same rate). No
one-way delay is inferred: bracketing timestamps cannot prove a shared clock origin.
Actual stream rates and Gazebo RTF require the independent subscription sampler;
the observe pair rate is limited by the slower stream and is not either publisher rate.
"""
import json
import math
import statistics

from tools.rover_control import RoverControlError
from tools.rover_pipe_session import HOST_GUARD_S, IPC_RESERVE_S

SCHEMA = 'tfg.rover.pipe-latency/1'
MIN_SAMPLES = 50
PASSIVE_OPS = ('probe', 'observe')


def percentile(values, q):
    """Nearest-rank percentile; None for no data."""
    data = sorted(values)
    if not data:
        return None
    rank = max(1, math.ceil(q / 100 * len(data)))
    return data[rank - 1]


def distribution(values):
    data = [v for v in values if v is not None]
    if not data:
        return {'n': 0}
    return {'n': len(data), 'min': min(data), 'p50': percentile(data, 50), 'p90': percentile(data, 90),
            'p95': percentile(data, 95), 'p99': percentile(data, 99), 'max': max(data),
            'mean': statistics.fmean(data), 'stdev': statistics.pstdev(data) if len(data) > 1 else 0.0}


def summarize(timings, *, reserve_s=IPC_RESERVE_S, guard_s=HOST_GUARD_S, min_samples=MIN_SAMPLES):
    """Latency, jitter, telemetry age, effective rate and RTF from one session's timings."""
    usable = [t for t in timings if isinstance(t.get('worker'), dict) and t['worker'].get('clock') == 'WORKER_MONOTONIC_S'
              and t.get('clock') == 'HOST_MONOTONIC_S']
    per_op = {}
    for op in sorted({t['op'] for t in usable}):
        rows = [t for t in usable if t['op'] == op]
        total = [t['reply_s'] - t['send_start_s'] for t in rows]
        handled = [t['worker']['handled_s'] for t in rows]
        overhead = [a - b for a, b in zip(total, handled)]
        entry = {'host_total_s': distribution(total), 'host_send_s': distribution([t['send_done_s'] - t['send_start_s'] for t in rows]),
                 'worker_handled_s': distribution(handled), 'pipe_and_serialization_s': distribution(overhead),
                 'pipe_overhead_basis': 'HOST_DURATION_MINUS_WORKER_DURATION'}
        per_op[op] = entry
    observes = [t for t in usable if t['op'] == 'observe' and t.get('ok')]
    telemetry = {k: distribution([t['worker']['telemetry_age_s'].get(k) for t in observes]) for k in ('status', 'odometry')}
    # Effective observation rate on the host clock; RTF from simulated stamps vs WORKER receipt times.
    rate = None
    if len(observes) >= 2:
        span = observes[-1]['reply_s'] - observes[0]['reply_s']
        rate = (len(observes) - 1) / span if span > 0 else None
    rtf, rx = [], []
    for t in observes:
        age, stamp = t['worker']['telemetry_age_s'].get('status'), (t.get('sample_stamp_ns') or {}).get('status')
        if age is not None and stamp is not None:
            rx.append((t['worker']['replied_s'] - age, stamp))
    for (w0, s0), (w1, s1) in zip(rx, rx[1:]):
        if s1 > s0 and w1 > w0:
            rtf.append((s1 - s0) / 1e9 / (w1 - w0))
    total_overhead = [t['reply_s'] - t['send_start_s'] - t['worker']['handled_s'] for t in usable]
    p99 = percentile(total_overhead, 99)
    if len(total_overhead) < min_samples:
        verdict = 'INSUFFICIENT_SAMPLES'
    elif p99 <= reserve_s:
        verdict = 'RESERVE_SUPPORTED_BY_THIS_MEASUREMENT'
    else:
        verdict = 'RESERVE_EXCEEDED'
    return {'schema': SCHEMA, 'samples': len(usable), 'ignored_without_worker_timing': len(timings) - len(usable),
            'clock_domains': ['HOST_MONOTONIC_S', 'WORKER_MONOTONIC_S', 'SIMULATED_STAMP_NS'],
            'one_way_latency': 'UNAVAILABLE_CLOCK_ORIGIN_NOT_ESTABLISHED', 'per_op': per_op,
            'telemetry_age_at_worker_reply_s': telemetry,
            'observe_rate_host_hz': rate, 'status_rtf_from_sim_stamps_vs_worker_receipt': distribution(rtf),
            'stream_rates': 'USE_INDEPENDENT_ROVER_SIM_METRICS_SAME_LIFECYCLE',
            'observe_reply_interval_s': distribution([b['reply_s'] - a['reply_s'] for a, b in zip(observes, observes[1:])]),
            'reserve': {'assumed_ipc_reserve_s': reserve_s, 'host_guard_s': guard_s, 'overhead_p99_s': p99,
                        'min_samples': min_samples, 'verdict': verdict},
            'movement_authorized': False, 'commands_sent': 0}


def measure_passive(session, *, observations=MIN_SAMPLES * 2, timeout_s=2.0):
    """Probe once and observe N times on an already opened PASSIVE session; never an exchange."""
    if getattr(session, 'mode', None) != 'PASSIVE':
        raise RoverControlError('Latency measurement only on a PASSIVE session; no commands are ever sent')
    if not isinstance(observations, int) or not 1 <= observations <= 1000:
        raise RoverControlError('observations must be an integer in [1, 1000]')
    errors = []
    states = []
    records = []
    first = len(session.timings)
    session.probe(timeout_s=timeout_s)
    for _ in range(observations):
        try:
            observation = session.observe(timeout_s=timeout_s)
            status = observation['status']
            states.append({k: status.get(k) for k in ('armed', 'mode', 'flying', 'failsafe')})
            states[-1]['driving'] = status.get('flying')  # Status.driving semantic for Rover; normalized pipe field is flying.
            odom = observation.get('odometry') or {}
            pose = ((odom.get('pose') or {}).get('pose') or {})
            twist = ((odom.get('twist') or {}).get('twist') or {})
            worker_timing = session.timings[-1].get('worker') if session.timings and session.timings[-1].get('op') == 'observe' else None
            records.append({'worker_telemetry_age_s': (worker_timing or {}).get('telemetry_age_s'),
                            'lifecycle_id': getattr(session, 'lifecycle_id', None),
                            'host_boot_id': getattr(session, 'host_boot_id', None),
                            'host_received_monotonic_s': observation.get('status_received_monotonic_s'),
                            'host_clock': 'HOST_MONOTONIC_S', 'sample_metadata': observation.get('sample_metadata'),
                            'status': status, 'odometry': odom,
                            'driving': status.get('flying'),
                            'measurement_units': {'position': 'm', 'linear_velocity': 'm/s',
                                                  'angular_velocity': 'rad/s', 'orientation': 'quaternion_xyzw'},
                            'status_publisher_gid': observation.get('status_publisher_gid'),
                            'odometry_publisher_gid': observation.get('odometry_publisher_gid'),
                            'position': pose.get('position'), 'orientation': pose.get('orientation'),
                            'linear_velocity': twist.get('linear'), 'angular_velocity': twist.get('angular'),
                            'frame_id': (odom.get('header') or {}).get('frame_id'),
                            'child_frame_id': odom.get('child_frame_id')})
            if status.get('armed') is not False:
                errors.append('DISARMED_STATE_NOT_CONFIRMED: passive capture interrupted, no control sent')
                break
        except (TimeoutError, RoverControlError) as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc)[:200])
            if session.broken:
                break
    timings = session.timings[first:]
    ops = {t['op'] for t in timings}
    if not ops <= set(PASSIVE_OPS):
        raise RoverControlError('Unexpected operation in a passive measurement: ' + ', '.join(sorted(ops)))
    report = summarize(timings)
    completed = sum(t['op'] == 'observe' and t.get('ok') is True for t in timings)
    report.update(observations_requested=observations, observations_completed=completed,
                  measurement_status='COMPLETE' if completed == observations and not errors and not session.timings_dropped else 'INCOMPLETE')
    report.update(status_observations=states,
                  disarmed_in_all_observations=bool(states) and all(s['armed'] is False for s in states))
    report.update(errors=errors, session_broken=session.broken, timings_dropped=session.timings_dropped)
    report['stationarity_capture'] = {'schema': 'tfg.rover.stationarity-capture/1',
                                      'records': records, 'records_captured': len(records),
                                      'capture_complete': (report.get('measurement_status') == 'COMPLETE' and len(records) == observations
                                                          and not session.broken and session.timings_dropped == 0),
                                      'movement_authorized': False, 'commands_sent': 0}
    json.dumps(report, allow_nan=False)  # the report must be storable as evidence
    return report
