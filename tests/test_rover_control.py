"""Pure adapter doubles: no ROS/Docker, arming or movement of a real backend."""
from dataclasses import replace
import subprocess

import pytest

from tools.rover_control import (
    Observation, Reply, RoverControlCore, RoverControlError, RoverLimits, RoverMode,
)
from tools.simulated_vehicle import resolve_vehicle, VehicleSelectionError


class Clock:
    def __init__(self):
        self.now = 100.0
    def monotonic(self):
        return self.now
    def sleep(self, duration):
        self.now += duration


def observation(clock, index, **changes):
    clock.now += .01
    values = dict(vehicle_id='rover_01', interface='v3', vehicle_type=1,
                  mode=15, armed=True, flying=False, external_control=True, failsafe=(),
                  received_monotonic_s=clock.now, status_source_ns=index,
                  velocity_source_ns=index, linear_mps=(0., 0., 0.), angular_rad_s=(0., 0., 0.),
                  motion_source='/model/rover1/odometry', motion_frame='base_link',
                  motion_received_monotonic_s=clock.now)
    values.update(changes)
    return Observation(**values)


class Adapter:
    def __init__(self, clock):
        self.clock = clock
        self.commands = []
        self.observations = []
        self.replies = []
        self.index = 0
    def observe(self, *, timeout_s):
        assert timeout_s > 0
        self.index += 1
        change = self.observations.pop(0) if self.observations else {}
        if isinstance(change, Exception):
            raise change
        return observation(self.clock, self.index, **change)
    def exchange(self, command, *, timeout_s):
        assert timeout_s > 0
        self.commands.append(command)
        reply = self.replies.pop(0) if self.replies else Reply(True, 0, {'status': True, 'curr_mode': 4})
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def core():
    clock = Clock()
    adapter = Adapter(clock)
    limits = RoverLimits(.5, .3, 2., 1., 4., .5, .02, .02)
    return RoverControlCore(limits, adapter=adapter, clock=clock)


def stop_samples(adapter):
    adapter.observations += [{}, {'mode': 4}, {'mode': 4}]


def test_default_has_no_operational_path(core):
    blocked = RoverControlCore(core.limits)
    for call in (lambda: blocked.move_for(.1, 0, 1), blocked.stop,
                 lambda: blocked.request_mode(RoverMode.HOLD)):
        with pytest.raises(RoverControlError, match='BLOCKED'):
            call()
    assert blocked.diagnostics == []


@pytest.mark.parametrize('identity', [{'vehicle_id': 'drone_01'}, {'interface': 'v1'},
                                      {'interface': 'v2'}, {'vehicle_id': 'unknown'}])
def test_constructor_rejects_identity(core, identity):
    with pytest.raises(RoverControlError):
        RoverControlCore(core.limits, **identity)


@pytest.mark.parametrize('change', [{'vehicle_id': 'drone_02'}, {'interface': 'v1'},
    {'vehicle_type': 2}, {'vehicle_type': True}, {'armed': 1}, {'mode': True},
    {'failsafe': None}, {'received_monotonic_s': 1}, {'received_monotonic_s': 999}])
def test_wrong_observation_never_controls_or_recovers(core, change):
    core.adapter.observations = [change]
    result = core.move_for(.1, 0, 1)
    assert result['status'] == 'NOT_ATTEMPTED'
    assert result['stop'] is None and core.adapter.commands == []
    assert 'interpretation_error' in result['diagnostics'][0]


@pytest.mark.parametrize('args,kwargs', [((True, 0, 1), {}), ((float('nan'), 0, 1), {}),
    ((.1, float('inf'), 1), {}), ((-.1, 0, 1), {}), ((.6, 0, 1), {}),
    ((.1, .4, 1), {}), ((.1, 0, 3), {}), ((.1, 0, False), {}),
    ((.1, 0, 1), {'linear_unit': 'km/h'}), ((.1, 0, 1), {'angular_unit': 'deg/s'})])
def test_invalid_units_types_or_policy_rejected_before_io(core, args, kwargs):
    with pytest.raises(RoverControlError):
        core.move_for(*args, **kwargs)
    assert core.adapter.commands == [] and core.diagnostics == []


@pytest.mark.parametrize('change', [{'armed': False}, {'mode': 4},
    {'external_control': False}, {'failsafe': (2,)}, {'status_source_ns': None}])
def test_preconditions_not_inferred(core, change):
    core.adapter.observations = [change, change]
    assert core.move_for(.1, 0, 1)['status'] == 'NOT_ATTEMPTED'
    assert not core.adapter.commands


def test_explicit_rover_modes_not_copter_numbers(core):
    assert int(RoverMode.GUIDED) == 15 and int(RoverMode.HOLD) == 4
    with pytest.raises(RoverControlError):
        core.request_mode(4)
    core.adapter.replies = [Reply(True, 0, {'status': True, 'curr_mode': 15})]
    assert core.request_mode(RoverMode.GUIDED) == {
        'request_acknowledged': True, 'mode_observed': False, 'stopped': None}
    assert core.adapter.commands[0]['payload'] == {'mode': 15}


@pytest.mark.parametrize('reply', [Reply(True, 0, {'status': False, 'curr_mode': 0}),
    Reply(True, 0, {'status': True, 'curr_mode': 15}), Reply(True, 0, {'status': 'true', 'curr_mode': 4}),
    Reply(None, None), Reply(True, 1), TimeoutError('no response')])
def test_mode_negative_contradiction_missing_and_timeout(core, reply):
    core.adapter.replies = [reply]
    with pytest.raises((RoverControlError, TimeoutError)):
        core.request_mode(RoverMode.HOLD)
    assert not core.diagnostics[-1]['acknowledged']


def test_bounded_move_then_same_target_zero_and_hold(core):
    core.adapter.observations = [{}, {}]
    stop_samples(core.adapter)
    result = core.move_for(.1, .2, .5)
    assert result['status'] == 'STOP_OBSERVED'
    assert not result['motion_application_confirmed']
    assert not result['stop']['ground_contact_confirmed']
    commands = core.adapter.commands
    assert [v['endpoint'] for v in commands] == ['/ap/v3/cmd_vel', '/ap/v3/cmd_vel', '/ap/v3/mode_switch']
    assert commands[0]['payload']['header']['frame_id'] == 'base_link'
    assert commands[0]['payload']['twist']['linear']['x'] == .1
    assert commands[0]['payload']['twist']['angular']['z'] == .2
    assert commands[1]['payload']['twist']['linear']['x'] == 0
    assert commands[2]['payload'] == {'mode': 4}
    assert all(v['timeout_s'] > 0 and v['duration_wall_s'] >= 0 for v in result['diagnostics'])
    assert all(v['vehicle_id'] == 'rover_01' and v['interface'] == 'v3' for v in result['diagnostics'])
    pubs = [d for d in result['diagnostics'] if d['operation'] == 'publish_velocity']
    assert all(not d['acknowledged'] and d['effects'] == 'SENT_APPLICATION_UNCONFIRMED' for d in pubs)


@pytest.mark.parametrize('change', [{'linear_mps': None}, {'motion_source': None},
    {'motion_source': '/ap/v3/twist/filtered'}, {'motion_frame': 'map'},
    {'motion_received_monotonic_s': 0}, {'linear_unit': 'km/h'},
    {'linear_mps': (.1, 0., 0.)}, {'angular_rad_s': (0., 0., .1)},
    {'linear_mps': (False, 0., 0.)}, {'flying': True}, {'mode': 15},
    {'velocity_source_ns': None}, {'status_source_ns': 0}])
def test_zero_and_hold_ack_are_not_stop_observation(core, change):
    core.adapter.observations = [{}, {'mode': 4, **change}, {'mode': 4, **change}]
    result = core.stop()
    assert result['status'] == 'UNCONFIRMED'
    assert result['stationary_observed'] is False
    assert len(core.adapter.commands) == 2


def test_timeout_preserves_partial_output_and_attempts_ground_stop(core):
    core.adapter.observations = [{}, {}]
    stop_samples(core.adapter)
    core.adapter.replies = [subprocess.TimeoutExpired('fake publication', 1, output=b'partial', stderr=b'waiting')]
    result = core.move_for(.1, 0, 1)
    assert result['status'] == 'UNCONFIRMED'
    assert result['stop']['stationary_observed']
    diag = next(d for d in result['diagnostics'] if d['operation'] == 'publish_velocity')
    assert diag['stdout'] == 'partial' and diag['stderr'] == 'waiting'
    assert diag['effects'] == 'UNCONFIRMED'
    assert len(core.adapter.commands) == 3  # no resend of nonzero command


def test_zero_timeout_does_not_suppress_hold(core):
    stop_samples(core.adapter)
    core.adapter.replies = [TimeoutError('zero uncertain')]
    result = core.stop()
    assert result['status'] == 'UNCONFIRMED' and result['stationary_observed']
    assert result['zero_command_error']
    assert core.adapter.commands[-1]['payload'] == {'mode': 4}


def test_initial_failure_preserves_context_without_recovery(core):
    core.adapter.observations = [TimeoutError('status missing')]
    result = core.move_for(.1, 0, 1)
    assert result['status'] == 'NOT_ATTEMPTED' and not core.adapter.commands
    assert result['diagnostics'][0]['error']


def test_adapter_deadline_violation_is_unconfirmed(core):
    def slow(command, *, timeout_s):
        core.clock.now += timeout_s + .01
        return Reply(True, 0, {'status': True, 'curr_mode': 4})
    core.adapter.exchange = slow
    with pytest.raises(TimeoutError):
        core.request_mode(RoverMode.HOLD)
    assert core.diagnostics[-1]['error']


def test_rover_remains_rejected_by_public_drone_selection():
    with pytest.raises(VehicleSelectionError):
        resolve_vehicle('rover_01', 'v3')
    assert resolve_vehicle('drone_01').simulated_vehicle == 'v1'
    assert resolve_vehicle('drone_02').simulated_vehicle == 'v2'


def test_rover_mission_blocked_before_public_executor_or_admission(tmp_path, monkeypatch):
    import json
    from unittest.mock import Mock
    from tests.test_virtual_preflight import EXAMPLE
    import tools.simulation_mission_executor as executor
    import tools.virtual_preflight_jobs as jobs

    data = json.loads(EXAMPLE.read_bytes())
    data['vehicle']['vehicle_id'] = 'rover_01'
    path = tmp_path / 'rover.json'
    path.write_text(json.dumps(data))
    run = Mock(side_effect=AssertionError('No executor'))
    spawn = Mock(side_effect=AssertionError('No worker'))
    monkeypatch.setattr(executor, '_execute_resolved_mission', run)
    monkeypatch.setattr(jobs.subprocess, 'Popen', spawn)
    monkeypatch.setattr(jobs, 'RUN_ROOT', tmp_path / 'runs')
    assert executor.execute_approved_mission(str(path))['stage'] == 'VEHICLE_SELECTION'
    assert jobs.start_virtual_preflight(str(path), 'blocked-rover')['admission_status'] == 'ERROR'
    run.assert_not_called()
    spawn.assert_not_called()


def test_negative_hold_and_missing_samples_cannot_confirm_stop(core):
    core.adapter.replies = [Reply(True, 0), Reply(True, 0, {'status': False, 'curr_mode': 15})]
    assert core.stop()['status'] == 'UNCONFIRMED'
    core.adapter.observations = [{}, TimeoutError('post HOLD status missing')]
    assert core.stop()['status'] == 'UNCONFIRMED'


def test_motion_receive_time_must_advance(core):
    core.adapter.observations = [{}, {'mode': 4, 'motion_received_monotonic_s': 100.02},
                                 {'mode': 4, 'motion_received_monotonic_s': 100.02}]
    result = core.stop()
    assert result['status'] == 'UNCONFIRMED'
    assert 'progressing independent motion' in str(result['error_evidence'])


def test_native_api_completion_has_no_fabricated_process_exit(core):
    core.adapter.replies = [Reply(True, None, {'status': True, 'curr_mode': 4}, native_api_completed=True)]
    result = core.request_mode(RoverMode.HOLD)
    assert result['request_acknowledged'] and result['mode_observed'] is False
    assert core.diagnostics[-1]['return_code'] is None
    assert core.diagnostics[-1]['return_code_kind'] == 'NO_PROCESS_EXIT_NATIVE_API'


@pytest.mark.parametrize('reply', [Reply(True, None, {'status': True, 'curr_mode': 4}),
    Reply(True, 0, {'status': True, 'curr_mode': 4}, native_api_completed=True)])
def test_missing_or_contradictory_native_completion_rejected(core, reply):
    core.adapter.replies = [reply]
    with pytest.raises(RoverControlError, match='transport/confirmation absent'):
        core.request_mode(RoverMode.HOLD)
    assert core.diagnostics[-1]['acknowledged'] is False
