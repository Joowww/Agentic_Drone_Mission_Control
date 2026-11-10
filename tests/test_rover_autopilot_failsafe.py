"""ArduRover's independent stop layer: source facts, required GUID_TIMEOUT, live-fact gate. Offline only.

The source facts are checked against the ArduPilot tree sealed on 31/10 (hashes listed in its
SHA256SUMS). Nothing here reads a live parameter: the trial facts are SYNTHETIC fixtures.
"""
import copy
import hashlib
import math
import re
from pathlib import Path

import pytest

from tools import rover_autopilot_failsafe as af, rover_first_navigation as nav, rover_ground_executor as ground
from tools.rover_control import RoverControlError
from tests.test_rover_first_navigation import (BOOT, EXECUTION, LIFECYCLE, SYNTHETIC_AUTOPILOT_VALUES, autopilot_fact,
                                               facts, trial)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / af.SOURCE_ROOT
SEAL = SOURCE.parents[1] / 'SHA256SUMS'
EFFECTIVE = ROOT / ('simulation/ros2_gazebo/results/rover_passive_regression_2026_10_22/'
                    '56c886cf-5df9-4ff7-9815-656d8c06c466/effective_files')
SITL_LAUNCH = SOURCE.parents[1] / ('dependencies/root/root/ardu_ws/install/ardupilot_sitl/local/lib/python3.10/'
                                   'dist-packages/ardupilot_sitl/launch.py')


# ------------------------------------------------------------- what ArduRover really does --
def test_source_facts_are_the_sealed_files():
    sealed = dict(line.split('  ', 1)[::-1] for line in SEAL.read_text().splitlines() if '  source/ardupilot/' in line)
    for name, (digest, _) in af.SOURCE_FACTS.items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest
        assert sealed['source/ardupilot/' + name] == digest


def test_cmd_vel_becomes_a_guided_setpoint_that_expires_on_simulated_time():
    guided = (SOURCE / 'Rover/mode_guided.cpp').read_text()
    external = (SOURCE / 'Rover/AP_ExternalControl_Rover.cpp').read_text()
    dds = (SOURCE / 'libraries/AP_DDS/AP_DDS_ExternalControl.cpp').read_text()
    assert 'external_control->set_linear_velocity_and_yaw_rate' in dds and 'BASE_LINK_FRAME_ID' in dds
    assert 'rover.mode_guided.set_desired_turn_rate_and_speed' in external
    assert 'rover.control_mode->in_guided_mode() && rover.arming.is_armed()' in external
    block = guided[guided.index('case SubMode::TurnRateAndSpeed:'):guided.index('case SubMode::Loiter:')]
    assert '(millis() - _des_att_time_ms) > get_timeout_ms()' in block and 'stop_vehicle();' in block
    assert 'set_mode' not in block and 'disarm' not in block  # stops; no HOLD, no disarm
    setter = guided[guided.index('void ModeGuided::set_desired_turn_rate_and_speed'):]
    assert '_des_att_time_ms = AP_HAL::millis();' in setter[:400]
    assert 'return MAX(g2.guided_timeout, 0.1) * 1000;' in guided


def test_parameter_defaults_and_what_does_not_cover_our_transport():
    params = (SOURCE / 'Rover/Parameters.cpp').read_text()
    assert 'AP_GROUPINFO("GUID_TIMEOUT", 62, ParametersG2, guided_timeout, 3.0)' in params
    assert re.search(r'GUID_TIMEOUT.*?@Range: 0\.1 5', params, re.S)
    assert 'GSCALAR(fs_gcs_enabled, "FS_GCS_ENABLE",   FS_GCS_DISABLED)' in params
    client = (SOURCE / 'libraries/AP_DDS/AP_DDS_Client.cpp').read_text()
    for name in ('_TIMEOUT_MS', '_MAX_RETRY'):  # connection ping only
        assert re.search(rf'@Param: {name}\n.*?@Description: [^\n]*(ping|reattempting)', client, re.S)
    gcs = (SOURCE / 'Rover/Rover.cpp').read_text()
    assert 'sysid_mygcs_last_seen_time_ms' in gcs  # GCS failsafe watches MAVLink heartbeats, not DDS
    assert af.COMPILED_DEFAULTS['GUID_TIMEOUT'] == 3.0


def test_our_defaults_files_do_not_set_it_and_eeprom_can_override_the_default():
    names = set()
    for parm in ('048/dds_udp.parm', '049/dds_use_ns.parm', '050/rover-skid.parm', '051/rover.parm'):
        names |= {line.split()[0] for line in (EFFECTIVE / parm).read_text().splitlines()
                  if line.strip() and not line.startswith('#')}
    assert names.isdisjoint({'GUID_TIMEOUT', 'ATC_ACCEL_MAX', 'ATC_DECEL_MAX', 'FS_GCS_ENABLE'})
    launch = SITL_LAUNCH.read_text()
    assert '"wipe",\n                default_value="False"' in launch and 'store eeprom.bin' in launch
    ours = (ROOT / 'simulation/ros2_gazebo/launch/tfg_rover_only.launch.py').read_text()
    assert '"use_instance_dir": "True"' in ours and '"wipe"' not in ours  # persisted values win: read it live


# ------------------------------------------------------------------- the required value --
def test_required_timeout_is_derived_from_speed_and_trial_geometry():
    budget = af.runaway_budget_m(forward_m=1.0, tolerance_m=0.25, max_distance_m=nav.MAX_DISTANCE_M)
    assert budget == pytest.approx(0.25)
    # 0.15 m/s x 1.25 overshoot allowance = 0.1875 m/s; braking at 1 m/s/s = 0.0176 m; (0.25-0.0176)/0.1875 = 1.24
    assert af.required_guided_timeout_s(0.15, budget_m=budget) == 1.2
    assert af.required_guided_timeout_s(0.25, budget_m=budget) == 0.6  # (0.25-0.0488)/0.3125 = 0.64
    assert af.required_guided_timeout_s(0.30, budget_m=budget) == 0.4  # (0.25-0.0703)/0.375 = 0.48
    assert af.required_guided_timeout_s(2.0, budget_m=budget) is None


def test_default_three_seconds_does_not_bound_the_runaway():
    envelope = af.runaway_envelope(speed_mps=0.15, guided_timeout_s=3.0, accel_max=1.0, decel_max=0.0,
                                   worker_watchdog_s=3.0, rtf_upper=1.0, budget_m=0.25)
    assert envelope['layers']['AUTOPILOT_GUID_TIMEOUT']['bound_m'] == pytest.approx(0.1875 * 3 + 0.1875 ** 2 / 2)
    assert not any(s['within_budget'] for s in envelope['scenarios'].values())
    with pytest.raises(RoverControlError, match='GUID_TIMEOUT_TOO_LONG_FOR_RUNAWAY_BUDGET'):
        trial(autopilot_failsafe=autopilot_fact(GUID_TIMEOUT=3.0))


def test_the_worker_watchdog_cannot_be_the_bound_even_at_its_shortest_legal_value():
    shortest = nav.LIMITS.call_timeout_s  # worker_limits refuses a watchdog shorter than one host call
    envelope = af.runaway_envelope(speed_mps=0.15, guided_timeout_s=1.0, accel_max=1.0, decel_max=0.0,
                                   worker_watchdog_s=shortest, rtf_upper=1.0, budget_m=0.25)
    assert envelope['layers']['WORKER_WATCHDOG_ZERO_HOLD']['bound_m'] > 0.25
    assert envelope['layers']['AUTOPILOT_GUID_TIMEOUT']['bound_m'] <= 0.25


@pytest.mark.parametrize('scenario', ['C_DDS_LOST', 'D_CMD_VEL_PUBLISH_BLOCKED', 'E_WORKER_CRASHED'])
def test_without_dds_or_worker_only_the_autopilot_layer_remains(scenario):
    envelope = af.runaway_envelope(speed_mps=0.15, guided_timeout_s=1.0, accel_max=1.0, decel_max=0.0,
                                   worker_watchdog_s=3.0, rtf_upper=1.0, budget_m=0.25)
    assert envelope['scenarios'][scenario]['layers'] == ['AUTOPILOT_GUID_TIMEOUT']
    assert all(s['guaranteed_m'] == envelope['layers']['AUTOPILOT_GUID_TIMEOUT']['bound_m']
               for s in envelope['scenarios'].values())
    assert all(s['within_budget'] for s in envelope['scenarios'].values())


def test_autopilot_bound_is_simulated_distance_independent_of_rtf():
    a, b = (af.runaway_envelope(speed_mps=0.15, guided_timeout_s=1.0, accel_max=1.0, decel_max=0.0,
                                worker_watchdog_s=3.0, rtf_upper=r, budget_m=0.25) for r in (1.0, 2.0))
    assert a['layers']['AUTOPILOT_GUID_TIMEOUT'] == b['layers']['AUTOPILOT_GUID_TIMEOUT']
    assert b['layers']['WORKER_WATCHDOG_ZERO_HOLD']['bound_m'] > a['layers']['WORKER_WATCHDOG_ZERO_HOLD']['bound_m']


def test_no_braking_credit_without_a_configured_limit_and_capped_otherwise():
    assert af.braking_distance_m(0.2, 0.0, 0.0) == math.inf
    assert af.braking_distance_m(0.2, 50.0, 0.0) == pytest.approx(0.2 ** 2 / 2)  # capped at 1 m/s/s


# ------------------------------------------------------------------- the live fact gate --
def test_trial_without_a_live_read_is_refused():
    with pytest.raises(RoverControlError, match='AUTOPILOT_FAILSAFE_NOT_READ_IN_THIS_LIFECYCLE'):
        trial(autopilot_failsafe=None)


def test_timeout_shorter_than_the_nominal_setpoint_interval_is_refused():
    with pytest.raises(RoverControlError, match='SHORTER_THAN_NOMINAL_COMMAND_INTERVAL'):
        trial(autopilot_failsafe=autopilot_fact(GUID_TIMEOUT=0.5))


@pytest.mark.parametrize('where', ['lifecycle', 'boot', 'container'])
def test_a_read_from_another_session_is_refused(where):
    execution = copy.deepcopy(EXECUTION)
    kwargs = {'lifecycle_id': LIFECYCLE, 'environment_execution': execution, 'host_boot_id': BOOT}
    if where == 'lifecycle': kwargs['lifecycle_id'] = 'older-start'
    elif where == 'boot': kwargs['host_boot_id'] = 'previous-boot'
    else: execution['persistent_identity']['container_id'] = 'e' * 64
    fact = af.autopilot_fact(dict(SYNTHETIC_AUTOPILOT_VALUES), **kwargs)
    with pytest.raises(RoverControlError, match='AUTOPILOT_FACT_FROM_ANOTHER_SESSION'):
        trial(autopilot_failsafe=fact)


@pytest.mark.parametrize('values', [
    {k: v for k, v in SYNTHETIC_AUTOPILOT_VALUES.items() if k != 'GUID_TIMEOUT'},
    {**SYNTHETIC_AUTOPILOT_VALUES, 'EXTRA': 1}, {**SYNTHETIC_AUTOPILOT_VALUES, 'GUID_TIMEOUT': float('nan')},
    {**SYNTHETIC_AUTOPILOT_VALUES, 'GUID_TIMEOUT': 9.0}, {**SYNTHETIC_AUTOPILOT_VALUES, 'GUID_TIMEOUT': True},
    {**SYNTHETIC_AUTOPILOT_VALUES, 'ATC_ACCEL_MAX': -1.0}])
def test_incomplete_or_invalid_reads_are_refused_not_completed(values):
    with pytest.raises(RoverControlError):
        af.autopilot_fact(values, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION, host_boot_id=BOOT)


def test_only_the_read_only_parameter_source_is_accepted():
    with pytest.raises(RoverControlError, match='read-only GetParameters'):
        af.autopilot_fact(dict(SYNTHETIC_AUTOPILOT_VALUES), lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                          host_boot_id=BOOT, source='COMPILED_DEFAULT')


def test_valid_trial_binds_the_fact_and_its_assessment_into_the_scope():
    t = trial()
    entry = t['scope']['control_context']['autopilot_failsafe']
    assert entry['assessment']['status'] == 'VERIFIED_WITHIN_ENVELOPE' and entry['fact']['values']['GUID_TIMEOUT'] == 1.0
    window = t['control_timing']['derivation']['autopilot_guid_timeout_window_s']
    assert window[0] < 1.0 <= window[1] == 1.2
    assert nav.dry_run(t, facts=facts)['gate']['reasons'] == ['SITL_TRIAL_POLICY_DISABLED']


@pytest.mark.parametrize('tamper', ['verdict', 'value', 'inputs'])
def test_gate_recomputes_the_assessment_and_never_trusts_the_stored_verdict(tamper):
    t = copy.deepcopy(trial())
    entry = t['request']['sitl_trial']['scope']['control_context']['autopilot_failsafe']
    if tamper == 'verdict':
        entry['assessment']['required_guid_timeout_max_s'] = 5.0
    elif tamper == 'value':
        values = {**entry['fact']['values'], 'GUID_TIMEOUT': 3.0}
        entry['fact'] = af.autopilot_fact(values, lifecycle_id=LIFECYCLE, environment_execution=EXECUTION,
                                          host_boot_id=BOOT)
    else:
        entry['inputs']['max_distance_m'] = 5.0
    gate = ground.policy_gate(t['request'], t['scope']['mission_sha256'], facts=facts)
    assert gate['status'] == 'BLOCKED'
    assert {'AUTOPILOT_FAILSAFE_ASSESSMENT_DIFFERS', 'AUTOPILOT_FAILSAFE_INPUTS_DIFFER'} & set(gate['reasons'])


def test_module_reads_and_writes_nothing():
    import ast
    tree = ast.parse((ROOT / 'tools/rover_autopilot_failsafe.py').read_text())
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert imported <= {'copy', 'math', 'planning.artifact_store', 'tools.rover_control'}
    assert 'open(' not in (ROOT / 'tools/rover_autopilot_failsafe.py').read_text()
