"""Stop/authority contract of the rover worker, session and factory (NO_GO phase 2). Offline, fakes only.

Each test names the contract clause it checks. Clauses already covered elsewhere are listed in
docs/rover-first-navigation-sitl.md §9 instead of being duplicated here.
"""
import copy
from unittest.mock import Mock

import pytest

from tools import rover_ground_executor as ground, rover_pipe_session as pipe, rover_pipe_worker as w
from tools import vehicle_execution_lock as locks
from tools.rover_control import RoverControlError
from tests.test_rover_first_navigation import evidence, trial
from tests.test_rover_pipe_watchdog import ARM_ON, ARM_OFF, ex, worker
from tests.test_rover_pipe_worker import MODE_GUIDED, MODE_HOLD, req, session, velocity
from tests.test_rover_sitl_preparation import BOOT, EXECUTION, LIFECYCLE


# --------------------------------------- no (re)arm after a communication failure, worker side --
def test_guided_or_arm_is_refused_with_stale_worker_telemetry():
    core, backend, clock = worker()
    clock.now += core.limits['telemetry_max_age_s'] + 0.5  # no new pair since
    for index, command in enumerate((MODE_GUIDED, ARM_ON)):
        reply = ex(core, command)
        assert reply['error']['code'] == ('MOTION_REFUSED' if index else 'TELEMETRY_STALE')
    assert backend.calls == []  # nothing reached the vehicle
    assert ex(core, MODE_HOLD)['ok'] and ex(core, ARM_OFF)['ok']  # stopping stays possible


def test_no_rearm_after_telemetry_was_lost_even_if_it_comes_back():
    core, backend, clock = worker()
    assert ex(core, MODE_GUIDED)['ok']
    backend.frozen = True
    seen = backend.t * 10**9
    lost = core.handle(req('observe', {'timeout_s': 0.2, 'after_status_ns': seen, 'after_odometry_ns': seen}))
    assert lost['error']['code'] == 'TIMEOUT_EFFECT_UNCONFIRMED'
    backend.frozen = False
    backend.spin(0.0)  # telemetry is fresh again
    reply = ex(core, ARM_ON)
    assert reply['error']['code'] == 'MOTION_REFUSED' and 'TELEMETRY_LOST' in reply['error']['message']
    assert ('arm', True) not in backend.calls


@pytest.mark.parametrize('stop', [MODE_HOLD, ARM_OFF])
def test_no_second_preparation_after_an_acknowledged_stop_in_the_same_session(stop):
    core, backend, _ = worker()
    assert ex(core, MODE_GUIDED)['ok'] and ex(core, ARM_ON)['ok']
    assert ex(core, stop)['ok']
    backend.spin(0.0)
    for command in (MODE_GUIDED, ARM_ON):
        reply = ex(core, command)
        assert reply['error']['code'] == 'MOTION_REFUSED' and 'PREPARATION_CLOSED' in reply['error']['message']
    assert ex(core, MODE_HOLD)['ok']


def test_first_preparation_is_unchanged():
    core, backend, _ = worker()
    assert ex(core, MODE_GUIDED)['ok'] and ex(core, ARM_ON)['ok'] and ex(core, velocity(0.1))['ok']
    assert backend.calls == [('mode', 15), ('arm', True)] and backend.sent == [(0.1, 0.0)]


@pytest.mark.parametrize('latch', ['timeout', 'violation'])
def test_rearm_after_a_latched_failure_is_refused(latch):
    core, backend, _ = worker()
    if latch == 'timeout':
        backend.service_timeout = True
        assert ex(core, MODE_GUIDED)['error']['code'] == 'TIMEOUT_EFFECT_UNCONFIRMED'
        backend.service_timeout = False
    else:
        core.handle('not json')
    assert ex(core, ARM_ON)['error']['code'] == 'MOTION_REFUSED'
    assert ex(core, MODE_HOLD)['ok']  # stop still allowed


# ------------------------------------------------------ host side: timeout is never a stop --
def test_after_a_lost_reply_the_host_session_sends_nothing_more():
    s, transport, backend, _ = session('drop')
    with pytest.raises(TimeoutError):
        s.exchange(MODE_GUIDED, timeout_s=1.0)
    sent = len(transport.sent)
    with pytest.raises(RoverControlError, match='unconfirmed'):
        s.exchange(ARM_ON, timeout_s=1.0)   # stop-only after an uncertain effect
    with pytest.raises(RoverControlError, match='unusable'):
        s.exchange(MODE_HOLD, timeout_s=1.0)  # and the broken pipe is not reused, not even to stop
    assert len(transport.sent) == sent  # no replay, no arm; the worker's EOF stop is what remains


def test_mode_is_fixed_for_the_whole_session():
    s, transport, _, _ = session(mode='PASSIVE', limits={'watchdog_s': 3.0, 'max_session_s': 300.0})
    with pytest.raises(AttributeError):
        s.mode = 'OPERATIONAL'
    with pytest.raises(RoverControlError, match='Passive'):
        s.exchange(MODE_GUIDED, timeout_s=1.0)
    core = transport.core
    reply = core.handle(req('hello', {}))  # a second hello cannot change it either
    assert reply['ok'] is False and core.mode == 'PASSIVE'


# --------------------------------------------- factory: bound to the admitted scope, pre-spawn --
def _factory(monkeypatch, *, restriction, job=None, request=None, **wiring):
    spawn = Mock()
    monkeypatch.setattr(pipe, '_default_authority', lambda: None)       # isolate: no real owner
    monkeypatch.setattr(pipe, '_default_fence', lambda execution: None)  # synthetic execution only
    monkeypatch.setattr(pipe, '_default_motion_allowed', lambda: True)  # isolate: no policy activation
    monkeypatch.setattr(locks, 'restriction', lambda vehicle=None: restriction)
    if job is not None:
        monkeypatch.setattr(ground, '_checked', lambda root: (job, None, request, None))
    kwargs = dict(lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
                  binding_evidence=evidence(), limits=trial()['worker_limits'], popen=spawn)
    kwargs.update(wiring)
    return pipe.pipe_adapter_factory(EXECUTION['persistent_identity']['container_id'], **kwargs), spawn


def test_factory_reservation_vanishing_before_spawn_is_an_explicit_refusal(monkeypatch):
    factory, spawn = _factory(monkeypatch, restriction=None)
    with pytest.raises(RoverControlError, match='reservation disappeared'):
        factory(lambda record: None)
    spawn.assert_not_called()


@pytest.mark.parametrize('field', ['lifecycle_id', 'host_boot_id', 'environment_execution', 'binding_evidence'])
def test_factory_wiring_must_be_the_admitted_sitl_scope(monkeypatch, field):
    t = trial()
    job = {'policy_admission': {'basis': 'SITL_TRIAL'}}
    scope = copy.deepcopy(t['scope'])
    if field == 'binding_evidence':
        scope['binding_evidence_sha256'] = 'f' * 64
    elif field == 'environment_execution':
        scope['environment_execution'] = dict(scope['environment_execution'], container_started_at='other')
    else:
        scope[field] = 'other'
    request = {**t['request'], 'sitl_trial': {**t['request']['sitl_trial'], 'scope': scope}}
    factory, spawn = _factory(monkeypatch, restriction={'owner_id': '6f1c2a54-5d0e-4c55-9a77-6a1f0a2b3c4d'},
                             job=job, request=request)
    with pytest.raises(RoverControlError, match='admitted SITL scope'):
        factory(lambda record: None)
    spawn.assert_not_called()


def test_factory_with_the_admitted_wiring_reaches_the_spawn(monkeypatch):
    t = trial()
    factory, spawn = _factory(monkeypatch, restriction={'owner_id': '6f1c2a54-5d0e-4c55-9a77-6a1f0a2b3c4d'},
                              job={'policy_admission': {'basis': 'SITL_TRIAL'}}, request=t['request'])
    spawn.side_effect = RuntimeError('stop at spawn: no process in this test')
    with pytest.raises(RuntimeError, match='stop at spawn'):
        factory(lambda record: None)
    spawn.assert_called_once()
