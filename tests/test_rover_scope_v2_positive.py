"""Positive path of the SITL scope /2, COMPLETELY ISOLATED, with both production policies left False.

Without activating a policy, "accepted" can only mean: the REAL gate (policy_gate, and through it
admit_ground_trial) refuses for exactly one reason, SITL_TRIAL_POLICY_DISABLED, which no test may
lift. Every mutation below must add its own reason on top of it.

Everything is synthetic and lives in tmp_path: mission copy, run/lock roots, cadence, binding,
autopilot read and current facts. The SITL authorization string is computed from the scope by
the project's own expected_authorization(); it is an offline FIXTURE, never written outside
tmp_path, and the operator statements are labelled SYNTHETIC. Nothing spawns, reserves for real,
or talks to ROS/Docker.
"""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from planning.artifact_store import fingerprint
from tools import rover_first_navigation as nav, rover_ground_executor as ground, rover_ros2_adapter as ros
from tools import rover_sitl_trial_policy as policy, vehicle_execution_lock as locks
from tools.rover_control import RoverControlError
from tests.test_rover_first_navigation import CADENCE, EXECUTION, MISSION, autopilot_fact, facts, trial

FLAG = ['SITL_TRIAL_POLICY_DISABLED']


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Temporary stores only; production flags must be, and stay, False."""
    assert (ground.OPERATIONAL_ROVER_ENABLED, policy.SITL_TRIAL_POLICY_ENABLED) == (False, False)
    monkeypatch.setattr(locks, 'LOCK_ROOT', tmp_path / 'locks')
    monkeypatch.setattr(ground, 'RUN_ROOT', tmp_path / 'ground')
    monkeypatch.setattr(ground, 'sitl_current_facts', facts)  # synthetic CURRENT facts, not a policy
    monkeypatch.setattr('subprocess.run', Mock(side_effect=AssertionError('no subprocess')))
    monkeypatch.setattr('subprocess.Popen', Mock(side_effect=AssertionError('no worker spawn')))
    mission = tmp_path / 'mission.json'
    mission.write_bytes(MISSION.read_bytes())
    yield mission, tmp_path
    assert (ground.OPERATIONAL_ROVER_ENABLED, policy.SITL_TRIAL_POLICY_ENABLED) == (False, False)


def filled(t=None):
    t = t or trial()
    return t, nav.with_operator_statements(t, sitl_authorization=t['required_sitl_authorization'],  # FIXTURE
                                           admission_statement='SYNTHETIC offline admission (test fixture)',
                                           coordination_statement='SYNTHETIC offline coordination (test fixture)')


def gate(request, t, current=facts):
    return ground.policy_gate(request, t['scope']['mission_sha256'], facts=current)


# ------------------------------------------------------------------------- 1. accepted --
def test_1_exact_scope_is_accepted_up_to_the_production_flag(isolated):
    mission, tmp_path = isolated
    t, f = filled()
    request = f['request']
    assert request['sitl_trial']['scope']['schema'] == 'tfg.rover.sitl-trial-scope/2'
    assert request['profile'] == 'rover_only'
    assert request['sitl_trial']['scope']['request_contract_sha256'] == policy.request_contract(request)
    result = gate(request, t)
    assert result['status'] == 'BLOCKED' and result['reasons'] == FLAG
    assert result['scope_sha256'] == t['scope_sha256']
    # The real admission runs every check before the gate (mission, authorization, coordination,
    # battery) and stops ONLY at the flag, writing nothing and reserving nothing.
    admitted = ground.admit_ground_trial(mission, 'scope-v2-positive', request, f['authorization'],
                                         coordination_context=f['coordination_context'])
    assert admitted['status'] == 'BLOCKED' and admitted['policy_gate']['reasons'] == FLAG
    assert not (tmp_path / 'ground').exists() and locks.restriction('v3') is None


# --------------------------------------------------------------- 2-8. each change refused --
def _mutate_request(request, change):
    r = copy.deepcopy(request)
    context = r['sitl_trial']['scope']['control_context']
    if change == 'target':
        r['goal']['x_m'] += 0.1
    elif change == 'pose':
        context['start_pose']['x_m'] += 0.1
    elif change == 'cadence':
        context['cadence']['rtf'] = 0.9
    elif change == 'speed':
        r['limits']['max_forward_mps'] = 0.3
    elif change == 'watchdog':
        context['worker_limits']['watchdog_s'] = 5.0
    elif change == 'lifecycle':
        r['sitl_trial']['scope']['lifecycle_id'] = '11111111-2222-4333-8444-555555555555'
    elif change == 'container':
        r['sitl_trial']['scope']['environment_execution'] = dict(EXECUTION, container_started_at='2026-11-05T00:00:00Z')
    return r


@pytest.mark.parametrize('change, expected', [
    ('target', 'SCOPE_DIFFERS_FROM_REQUEST'),            # 2
    ('pose', 'CONTROL_CONTEXT_DIFFERS'),                 # 3
    ('cadence', 'CONTROL_CONTEXT_DIFFERS'),              # 4
    ('speed', 'SCOPE_DIFFERS_FROM_REQUEST'),             # 5
    ('watchdog', 'AUTOPILOT_FAILSAFE_ASSESSMENT_DIFFERS'),  # 6
    ('lifecycle', 'CURRENT_LIFECYCLE_ID_DIFFERS'),       # 7
    ('container', 'CURRENT_ENVIRONMENT_EXECUTION_DIFFERS')])  # 8
def test_2_to_8_a_changed_request_after_the_declaration_is_refused(isolated, change, expected):
    t, f = filled()
    result = gate(_mutate_request(f['request'], change), t)
    assert result['status'] == 'BLOCKED' and expected in result['reasons']
    assert set(result['reasons']) - set(FLAG), result['reasons']
    if change not in ('target', 'speed'):  # the declaration names the old scope, not the changed one
        assert 'EXACT_OPERATOR_AUTHORIZATION_ABSENT' in result['reasons']


@pytest.mark.parametrize('change, expected', [
    ('lifecycle', 'CURRENT_LIFECYCLE_ID_DIFFERS'), ('container', 'CURRENT_ENVIRONMENT_EXECUTION_DIFFERS')])
def test_7_8_the_same_declaration_in_a_newer_lifecycle_or_container_is_refused(isolated, change, expected):
    t, f = filled()

    def drifted(scope, ev):
        current = facts(scope, ev)
        if change == 'lifecycle':
            current['lifecycle_id'] = 'a-newer-start'
        else:
            current['environment_execution'] = dict(EXECUTION, container_started_at='restarted')
        return current
    result = gate(f['request'], t, drifted)
    assert result['reasons'] == [expected] + FLAG or set(result['reasons']) == {expected, *FLAG}


@pytest.mark.parametrize('field', ['target', 'pose', 'cadence', 'speed', 'watchdog', 'autopilot'])
def test_2_to_6_a_rebuilt_trial_gets_a_new_scope_and_the_old_declaration_does_not_fit(isolated, field):
    t, _ = filled()
    if field == 'target':
        other = trial(forward_m=0.9)
    elif field == 'cadence':
        other = trial(dict(CADENCE, rtf=0.62))
    elif field == 'autopilot':
        other = trial(autopilot_failsafe=autopilot_fact(GUID_TIMEOUT=1.1))
    else:
        other = copy.deepcopy(t)
        key = {'pose': ('start', 'x_m'), 'speed': ('worker_limits', 'max_linear_mps'),
               'watchdog': ('worker_limits', 'watchdog_s')}[field]
        other[key[0]][key[1]] += 0.05
        with pytest.raises(RoverControlError, match='scope changed'):
            nav.with_operator_statements(other, sitl_authorization=t['required_sitl_authorization'],
                                         admission_statement='SYNTHETIC', coordination_statement='SYNTHETIC')
        return
    assert other['scope_sha256'] != t['scope_sha256']
    with pytest.raises(RoverControlError, match='does not name this exact scope'):
        nav.with_operator_statements(other, sitl_authorization=t['required_sitl_authorization'],
                                     admission_statement='SYNTHETIC', coordination_statement='SYNTHETIC')


# ----------------------------------------------------------------------------- 9. reuse --
def test_9_a_consumed_scope_cannot_be_used_again(isolated):
    t, f = filled()
    result = gate(f['request'], t, lambda scope, ev: {**facts(scope, ev), 'trials_consumed': 1})
    assert 'TRIAL_ALREADY_CONSUMED' in result['reasons'] and result['reasons'] != FLAG


def test_9_scope_allows_exactly_one_trial(isolated):
    t, f = filled()
    assert t['scope']['max_trials'] == 1
    request = copy.deepcopy(f['request'])
    request['sitl_trial']['scope']['max_trials'] = 2
    assert 'EXACTLY_ONE_TRIAL_REQUIRED' in gate(request, t)['reasons']


# ---------------------------------------------------------------------- 10. reservation --
@pytest.mark.parametrize('check', [ros._assert_preparation_scope, ros._assert_disarm_scope])
def test_10_lost_reservation_is_refused_before_any_scope_read(isolated, monkeypatch, check):
    monkeypatch.setattr(ros, 'assert_execution_authority', lambda vehicle: None)  # isolate the race window only
    monkeypatch.setattr(locks, 'restriction', lambda vehicle=None: None)
    with pytest.raises(RoverControlError, match='reservation disappeared'):
        check()


def test_10_without_any_reservation_the_operational_authority_is_absent(isolated):
    with pytest.raises(locks.VehicleBusy):
        locks.assert_execution_authority('v3')


def test_harness_leaves_nothing_behind(isolated):
    mission, tmp_path = isolated
    t, f = filled()
    gate(f['request'], t)
    written = sorted(p.relative_to(tmp_path).as_posix() for p in Path(tmp_path).rglob('*') if p.is_file())
    assert written == ['mission.json']
    assert json.loads(mission.read_text()) == json.loads(MISSION.read_text())
    assert fingerprint(f['request']['sitl_trial']['scope']) == t['scope_sha256']
