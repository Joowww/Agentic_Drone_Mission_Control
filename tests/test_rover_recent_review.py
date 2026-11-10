"""Regressions of the six recent commits; synthetic, policies remain closed."""
import copy
from unittest.mock import Mock

import pytest

from tools import rover_pipe_session as pipe
from tools.rover_control import RoverControlError
from tests.test_rover_first_navigation import EXECUTION, autopilot_fact, evidence, trial
from tests.test_rover_stop_contract import _factory
from tests.test_rover_pipe_watchdog import ARM_ON, ex, worker
from tests.test_rover_pipe_worker import MODE_GUIDED


@pytest.mark.parametrize('accel,decel', [(0.01, 0.0), (1.0, 0.01), (0.0, 0.0)])
def test_effective_braking_must_keep_every_runaway_scenario_within_budget(accel, decel):
    with pytest.raises(RoverControlError, match='GUID_TIMEOUT_TOO_LONG|RUNAWAY'):
        trial(autopilot_failsafe=autopilot_fact(ATC_ACCEL_MAX=accel, ATC_DECEL_MAX=decel))


def test_parameter_fact_binds_full_container_execution_not_only_id():
    from tools.rover_autopilot_failsafe import autopilot_fact as make
    from tests.test_rover_first_navigation import BOOT, LIFECYCLE, SYNTHETIC_AUTOPILOT_VALUES
    execution = copy.deepcopy(EXECUTION)
    execution['container_started_at'] = 'another-execution'
    fact = make(SYNTHETIC_AUTOPILOT_VALUES, lifecycle_id=LIFECYCLE, environment_execution=execution, host_boot_id=BOOT)
    with pytest.raises(RoverControlError, match='ANOTHER_SESSION'):
        trial(autopilot_failsafe=fact)


def test_stale_telemetry_refusal_cannot_be_followed_by_rearming():
    core, backend, clock = worker()
    assert ex(core, MODE_GUIDED)['ok']
    clock.now += core.limits['telemetry_max_age_s'] + 0.5
    assert ex(core, ARM_ON)['error']['code'] == 'TELEMETRY_STALE'
    backend.spin(0.0)
    reply = ex(core, ARM_ON)
    assert reply['ok'] is False and 'PREPARATION_CLOSED' in reply['error']['message']
    assert ('arm', True) not in backend.calls


@pytest.mark.parametrize('command', [MODE_GUIDED, ARM_ON])
def test_negative_preparation_response_cannot_be_retried_in_the_same_session(command):
    core, backend, clock = worker()
    backend.mode_response = {'status': False, 'curr_mode': 4}
    backend.arm_result = False
    assert ex(core, command)['ok']  # protocol reply exists; the service refused preparation
    backend.mode_response = None
    backend.arm_result = True
    reply = ex(core, ARM_ON)
    assert reply['ok'] is False and 'PREPARATION_CLOSED' in reply['error']['message']


def test_invalid_binding_is_rejected_before_operational_worker_spawn(monkeypatch):
    t = trial()
    bad = dict(evidence(), status='EXPIRED')
    request = copy.deepcopy(t['request'])
    request['sitl_trial']['scope']['binding_evidence_sha256'] = bad['evidence_sha256']
    factory, spawn = _factory(monkeypatch, restriction={'owner_id': '6f1c2a54-5d0e-4c55-9a77-6a1f0a2b3c4d'},
                              job={'policy_admission': {'basis': 'SITL_TRIAL'}}, request=request, binding_evidence=bad)
    with pytest.raises(RoverControlError, match='not accredited'):
        factory(lambda record: None)
    spawn.assert_not_called()


def test_invalid_binding_is_rejected_before_passive_worker_spawn():
    from tests.test_rover_first_navigation import BOOT, LIFECYCLE
    spawn = Mock(side_effect=AssertionError('worker must not be created'))
    with pytest.raises(RoverControlError, match='not accredited'):
        pipe.open_passive_session(EXECUTION['persistent_identity']['container_id'], lifecycle_id=LIFECYCLE,
                                  environment_execution=EXECUTION, host_boot_id=BOOT,
                                  binding_evidence=dict(evidence(), status='EXPIRED'), popen=spawn)
    spawn.assert_not_called()
