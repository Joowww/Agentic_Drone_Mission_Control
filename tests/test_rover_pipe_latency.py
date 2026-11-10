"""Latency instrumentation for a future PASSIVE session: offline, in-process worker, no commands."""
import json

import pytest

from tools import rover_pipe_latency as lat
from tools.rover_control import RoverControlError
from tests.test_rover_pipe_worker import LIMITS_HELLO, FakeBackend, FakeClock, req, session
from tests.test_rover_pipe_watchdog import worker


def passive():
    clock = FakeClock()
    backend = FakeBackend(clock)
    s, transport, backend, clock = session(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0}, backend=backend)
    return s, transport, backend, clock


def test_every_worker_reply_carries_its_own_clock_timing():
    core, backend, clock = worker()
    reply = core.handle(req('probe', {'timeout_s': 0.2}))
    timing = reply['timing']
    assert timing['clock'] == 'WORKER_MONOTONIC_S' and timing['handled_s'] >= 0
    assert timing['replied_s'] - timing['received_s'] == pytest.approx(timing['handled_s'])
    assert set(timing['telemetry_age_s']) == {'status', 'odometry'}
    assert core.handle('not json')['timing']['clock'] == 'WORKER_MONOTONIC_S'  # violations too
    json.dumps(reply, allow_nan=False)


def test_passive_measurement_sends_only_probe_and_observe_and_touches_no_control():
    s, transport, backend, _ = passive()
    report = lat.measure_passive(s, observations=60, timeout_s=1.0)
    assert {m['op'] for m in transport.sent} == {'hello', 'probe', 'observe'}
    assert backend.calls == [] and backend.sent == []  # no service call, no velocity
    assert report['samples'] == 61 and report['commands_sent'] == 0 and report['movement_authorized'] is False
    assert report['reserve']['verdict'] in ('RESERVE_SUPPORTED_BY_THIS_MEASUREMENT', 'RESERVE_EXCEEDED')
    json.dumps(report, allow_nan=False)


def test_operational_sessions_are_refused():
    s, *_ = session()
    with pytest.raises(RoverControlError, match='PASSIVE'):
        lat.measure_passive(s, observations=5)


def _row(op, start, sent, reply, received, replied, *, ages=(0.2, 0.2), stamp=None, ok=True):
    row = {'op': op, 'clock': 'HOST_MONOTONIC_S', 'send_start_s': start, 'send_done_s': sent, 'reply_s': reply,
           'ok': ok, 'worker': {'clock': 'WORKER_MONOTONIC_S', 'received_s': received, 'replied_s': replied,
                                'handled_s': replied - received,
                                'telemetry_age_s': {'status': ages[0], 'odometry': ages[1]}}}
    if stamp is not None:
        row['sample_stamp_ns'] = {'status': stamp, 'odometry': stamp}
    return row


def synthetic(n=60, *, offset=0.0, overhead=0.02):
    rows = []
    for i in range(n):
        t0 = 10.0 + i * 0.8333
        rows.append(_row('observe', t0, t0 + 0.001, t0 + 0.1 + overhead, t0 + overhead / 2 + offset,
                         t0 + 0.1 + overhead / 2 + offset, stamp=10**9 + int(i * 0.5 * 1e9)))
    return rows


def test_durations_percentiles_rate_and_rtf_from_known_values():
    report = lat.summarize(synthetic())
    obs = report['per_op']['observe']
    assert obs['worker_handled_s']['p50'] == pytest.approx(0.1)
    assert obs['pipe_and_serialization_s']['p99'] == pytest.approx(0.02)
    assert report['observe_rate_host_hz'] == pytest.approx(1.2, rel=1e-3)
    assert report['status_rtf_from_sim_stamps_vs_worker_receipt']['p50'] == pytest.approx(0.6, rel=1e-3)
    assert report['reserve']['verdict'] == 'RESERVE_SUPPORTED_BY_THIS_MEASUREMENT'
    assert 'one_way_estimate' not in obs
    assert report['one_way_latency'] == 'UNAVAILABLE_CLOCK_ORIGIN_NOT_ESTABLISHED'


def test_unbracketed_worker_clock_gives_intervals_only():
    report = lat.summarize(synthetic(offset=1e6))  # e.g. another time namespace
    assert report['one_way_latency'] == 'UNAVAILABLE_CLOCK_ORIGIN_NOT_ESTABLISHED'
    assert 'one_way_estimate' not in report['per_op']['observe']
    # durations are still valid: they never mix the two domains as timestamps
    assert report['per_op']['observe']['pipe_and_serialization_s']['p99'] == pytest.approx(0.02)


@pytest.mark.parametrize('n, overhead, verdict', [(49, 0.02, 'INSUFFICIENT_SAMPLES'), (60, 0.3, 'RESERVE_EXCEEDED')])
def test_reserve_verdict_needs_enough_samples_and_a_p99_within_it(n, overhead, verdict):
    assert lat.summarize(synthetic(n, overhead=overhead))['reserve']['verdict'] == verdict


def test_rows_without_worker_timing_are_counted_not_used():
    rows = synthetic(3) + [{'op': 'observe', 'clock': 'HOST_MONOTONIC_S', 'send_start_s': 1, 'send_done_s': 1,
                            'reply_s': 2, 'ok': True, 'worker': None}]
    report = lat.summarize(rows)
    assert report['samples'] == 3 and report['ignored_without_worker_timing'] == 1


def test_host_session_keeps_bounded_timings(monkeypatch):
    from tools import rover_pipe_session as ps
    monkeypatch.setattr(ps, 'MAX_TIMINGS', 3)
    s, *_ = passive()
    for _ in range(5):
        s.observe(timeout_s=1.0)
    assert len(s.timings) == 3 and s.timings_dropped == 2
    assert s.timings[0]['op'] == 'observe' and 'sample_stamp_ns' in s.timings[0]


def test_dropped_observations_cannot_overwrite_an_earlier_sample_stamp(monkeypatch):
    from tools import rover_pipe_session as ps
    monkeypatch.setattr(ps, 'MAX_TIMINGS', 3)
    s, *_ = passive()
    for _ in range(3): s.observe(timeout_s=1.0)
    retained = dict(s.timings[-1]['sample_stamp_ns'])
    for _ in range(2): s.observe(timeout_s=1.0)
    assert s.timings[-1]['sample_stamp_ns'] == retained


def test_clock_offsets_cannot_change_any_reported_latency():
    a, b = lat.summarize(synthetic()), lat.summarize(synthetic(offset=1024.0))
    assert a['one_way_latency'] == b['one_way_latency']
    for metric in ('host_total_s', 'worker_handled_s', 'pipe_and_serialization_s'):
        assert a['per_op']['observe'][metric] == pytest.approx(b['per_op']['observe'][metric], abs=1e-10)
    assert a['status_rtf_from_sim_stamps_vs_worker_receipt'] == pytest.approx(b['status_rtf_from_sim_stamps_vs_worker_receipt'], abs=1e-10)


def test_exactly_one_hundred_observations_excludes_preexisting_timings():
    s, transport, backend, _ = passive()
    s.observe(timeout_s=1.0)
    report = lat.measure_passive(s, observations=100, timeout_s=1.0)
    assert report['observations_requested'] == report['observations_completed'] == 100
    assert report['samples'] == 101 and report['measurement_status'] == 'COMPLETE'
    assert report['disarmed_in_all_observations'] and len(report['status_observations']) == 100
    assert backend.calls == [] and backend.sent == []


def test_dropped_timings_cannot_claim_a_complete_measurement(monkeypatch):
    from tools import rover_pipe_session as ps
    monkeypatch.setattr(ps, 'MAX_TIMINGS', 3)
    s, *_ = passive()
    report = lat.measure_passive(s, observations=100, timeout_s=1.0)
    assert report['measurement_status'] == 'INCOMPLETE'
    assert report['observations_completed'] < 100
    assert report['stationarity_capture']['capture_complete'] is False


def test_unexpected_armed_state_interrupts_capture_without_sending_a_control():
    s, transport, backend, _ = passive()
    backend.armed = True
    report = lat.measure_passive(s, observations=100, timeout_s=1.0)
    assert report['measurement_status'] == 'INCOMPLETE'
    assert report['observations_completed'] == 1 and not report['disarmed_in_all_observations']
    assert backend.calls == [] and backend.sent == []
