"""Independent offline review: fake ROS, synthetic poses, no policy activation or operational stores."""
import copy
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import rover_first_navigation as nav, rover_ground_executor as ground
from tools import rover_pipe_worker as worker, rover_ros2_adapter as ros
from tools.rover_control import RoverControlError, synchronous_deadline
from tests.test_rover_first_navigation import CADENCE, facts, trial
from tests.test_rover_pipe_watchdog import worker as make_worker, ex
from tests.test_rover_pipe_worker import MODE_GUIDED, MODE_HOLD, session, velocity




@pytest.mark.parametrize('field,key', [('limits', 'max_forward_mps'), ('limits', 'observation_max_age_s'),
                                     ('preparation', 'timeout_s'), ('finalization', 'timeout_s'),
                                     ('preparation_safety', 'max_slope_rad')])
def test_sitl_scope_invalidates_each_changed_control_parameter(field, key):
    t = trial()
    request = copy.deepcopy(t['request'])
    request[field][key] *= 1.1
    result = ground.policy_gate(request, t['scope']['mission_sha256'], facts=facts)
    assert 'SCOPE_DIFFERS_FROM_REQUEST' in result['reasons']


def test_scope_binds_cadence_even_if_derived_limits_and_goal_do_not_change():
    original = trial()
    changed = trial(dict(CADENCE, rtf=0.61))
    assert original['request']['goal'] == changed['request']['goal']
    assert original['scope_sha256'] != changed['scope_sha256']


def test_speed_times_wall_age_fits_tolerance_without_credit_from_low_rtf():
    t = trial()
    limits = t['request']['limits']
    assert 0.3 * 1.35 == pytest.approx(0.405)
    assert limits['max_forward_mps'] * limits['observation_max_age_s'] <= t['request']['goal']['tolerance_m']


@pytest.mark.parametrize('field,key', [('worker_limits', 'watchdog_s'), ('cadence', 'rtf'), ('start', 'x_m')])
def test_changed_outer_trial_context_cannot_reuse_its_original_scope(field, key):
    t = copy.deepcopy(trial())
    t[field][key] += 0.1
    with pytest.raises(RoverControlError, match='scope changed'):
        nav.with_operator_statements(t, sitl_authorization='NOT_A_HUMAN_AUTHORIZATION',
                                     admission_statement=nav.PLACEHOLDER, coordination_statement=nav.PLACEHOLDER)


def test_factory_refuses_disabled_motion_policy_before_any_spawn(monkeypatch):
    from tools import rover_pipe_session as pipe
    from tests.test_rover_sitl_preparation import EXECUTION, LIFECYCLE, BOOT
    from tests.test_rover_first_navigation import evidence
    spawn = Mock()
    monkeypatch.setattr(pipe, '_default_authority', lambda: None)  # isolate the policy check, no real owner
    monkeypatch.setattr(pipe, '_default_motion_allowed', lambda: False)
    factory = pipe.pipe_adapter_factory(EXECUTION['persistent_identity']['container_id'],
        lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT,
        binding_evidence=evidence(), limits=trial()['worker_limits'], popen=spawn)
    with pytest.raises(RoverControlError, match='no operational worker'):
        factory(lambda record: None)
    spawn.assert_not_called()


@pytest.mark.parametrize('dx,yaw,frame', [(0.1, 0.0, 'odom'), (0.0, 0.1, 'odom'), (0.0, 0.0, 'map')])
def test_live_start_pose_drift_is_rejected_before_preparation(dx, yaw, frame):
    import math
    from tools.rover_target_frame import verify_trial_start
    context = trial()['scope']['control_context']
    start = context['start_pose']
    angle = start['heading_rad'] + yaw
    observation = SimpleNamespace(position_m=(start['x_m'] + dx, start['y_m'], 0.0),
        orientation_xyzw=(0.0, 0.0, math.sin(angle/2), math.cos(angle/2)), pose_frame=frame,
        pose_reference_validated=True)
    with pytest.raises(RoverControlError, match='pose'):
        verify_trial_start(context, observation)


def test_live_start_pose_within_tolerance_is_read_only():
    import math
    from tools.rover_target_frame import verify_trial_start
    context = trial()['scope']['control_context']; start = context['start_pose']; angle = start['heading_rad']
    observation = SimpleNamespace(position_m=(start['x_m'], start['y_m'], 0.0),
        orientation_xyzw=(0.0, 0.0, math.sin(angle/2), math.cos(angle/2)), pose_frame='odom',
        pose_reference_validated=True)
    assert verify_trial_start(context, observation)['distance_m'] == 0.0
