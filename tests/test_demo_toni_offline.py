"""The one-command offline demo: outcomes per stage, clear failures, and no side effects."""
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tools import demo_toni_offline as demo

ROOT = Path(__file__).resolve().parents[1]
NOW = '2026-11-04T10:00:00+00:00'


def run(tmp_path, name='out', **kwargs):
    lines = []
    stages, code = demo.run(tmp_path / name, now_utc=NOW, emit=lines.append, **kwargs)
    summary = json.loads((tmp_path / name / 'summary.json').read_text())
    return stages, code, lines, summary


def checks(summary, stage):
    return {c['label']: c for c in summary['stages'][stage - 1]['checks']}


def test_the_real_command_runs_and_reports_every_stage(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'tools.demo_toni_offline', '--out', str(tmp_path / 'cli')],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    for n in range(1, 8):
        assert f'\n[{n}] ' in result.stdout
    assert 'FAILED 0' in result.stdout and 'DEMO COMPLETA, todo según lo esperado' in result.stdout


def test_valid_mission_passes_and_the_infeasible_copy_is_rejected_and_replanned(tmp_path):
    _, code, _, summary = run(tmp_path)
    c = checks(summary, 1)
    assert c['grafo de validación: misión viable']['status'] == 'PASS'
    infeasible = c['misma misión con viento de 45 km/h: rechazada y replanteada']
    assert infeasible['status'] == infeasible['expected'] == 'BLOCKED' and code == 0
    facts = summary['stages'][0]['facts']['infeasible']
    assert facts['status'] == 'NOT FEASIBLE' and any('waypoint_replanner' in t for t in facts['trace'])


def test_plan_is_refused_without_amsl_then_exported_verified_and_reimported(tmp_path):
    _, _, _, summary = run(tmp_path)
    statuses = [c['status'] for c in summary['stages'][1]['checks']]
    assert statuses == ['BLOCKED', 'PASS', 'PASS', 'PASS']
    plan = json.loads((tmp_path / 'out' / 'simulation_navigation_3waypoint.plan').read_text())
    assert plan['fileType'] == 'Plan' and plan['mission']['plannedHomePosition'][2] == demo.DECLARED_HOME_AMSL_M


def test_valid_observation_accepted_and_invalid_variants_rejected(tmp_path):
    _, _, _, summary = run(tmp_path)
    c = summary['stages'][3]['checks']
    assert c[0]['status'] == 'PASS' and [x['status'] for x in c[1:]] == ['BLOCKED'] * 4
    assert {x['detail'] for x in c[1:]} == {'CAMERA_COORDINATES_ARE_NOT_NAVIGATION_COORDINATES', 'CONFIDENCE_TOO_LOW',
                                           'PERCEPTION_SOURCE_NOT_IMPLEMENTED', 'TRANSFORM_ABSENT'}


def test_proposal_ends_pending_authorization_without_any_admission(tmp_path):
    _, _, _, summary = run(tmp_path)
    assert summary['stages'][4]['facts']['proposal']['authorization'] == 'ABSENT'
    assert summary['stages'][5]['facts']['decision'] == 'ROVER_TASK_PENDING_AUTHORIZATION'
    decision = json.loads((tmp_path / 'out' / 'agri_red_card' / 'decision.json').read_text())
    assert decision['executor_admit_calls'] == 0 and decision['movement_authorized'] is False
    assert not (tmp_path / 'out' / 'agri_red_card' / 'r1' / 'records').exists()
    assert summary['movement_authorized'] is False and summary['offline'] is True


def test_a_missing_dependency_fails_clearly_and_its_dependents_are_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'MISSION', ROOT / 'missions/examples/does_not_exist.json')
    stages, code, lines, summary = run(tmp_path)
    assert code == 1 and summary['ok'] is False
    first, second = summary['stages'][0], summary['stages'][1]
    assert first['checks'][0]['status'] == 'FAILED' and 'FileNotFoundError' in first['checks'][0]['detail']
    assert second['link'] == 'SKIPPED' and 'depends on stage_mission' in second['checks'][0]['detail']
    assert all(s['ok'] for s in summary['stages'][2:])  # the agricultural slice does not depend on stages 1-2
    assert any('HAY FALLOS' in line for line in lines)


def test_a_missing_historical_plan_fails_only_its_check(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, 'QGC_RESAVED', tmp_path / 'missing.plan')
    _, code, _, summary = run(tmp_path)
    assert code == 1 and summary['stages'][1]['checks'][-1]['status'] == 'FAILED'
    assert summary['stages'][0]['ok'] and all(s['ok'] for s in summary['stages'][2:])


def test_refuses_a_non_empty_output_directory(tmp_path):
    (tmp_path / 'used').mkdir()
    (tmp_path / 'used' / 'x').write_text('keep')
    result = subprocess.run([sys.executable, '-m', 'tools.demo_toni_offline', '--out', str(tmp_path / 'used')],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and 'NEW directory' in result.stderr
    assert (tmp_path / 'used' / 'x').read_text() == 'keep'


def _project_state():
    from tools import rover_ground_executor as ground, rover_sitl_trial_policy as policy
    from tools import vehicle_execution_lock as locks
    generated = sorted((p.relative_to(ROOT).as_posix(), p.stat().st_mtime_ns)
                       for p in (ROOT / 'missions/generated').rglob('*') if p.is_file()) \
        if (ROOT / 'missions/generated').exists() else []
    git = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return {'reservations': {v: locks.restriction(v) for v in ('v1', 'v2', 'v3')},
            'infra': locks.infrastructure_restriction(), 'sequence': locks.sequence_restriction(),
            'policies': (ground.OPERATIONAL_ROVER_ENABLED, policy.SITL_TRIAL_POLICY_ENABLED),
            'generated': generated, 'git': git}


def test_no_side_effects_no_network_no_processes(tmp_path, monkeypatch):
    before = _project_state()

    def forbidden(*args, **kwargs):
        raise AssertionError('the offline demo must not open sockets or start processes')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    _, code, _, _ = run(tmp_path)
    monkeypatch.undo()
    assert code == 0
    after = _project_state()
    assert after == before  # reservations, policies, missions/generated and the Git tree untouched
    assert before['policies'] == (False, False)


def test_importing_the_module_loads_nothing_heavy():
    probe = ('import sys, tools.demo_toni_offline; '
             'print([m for m in ("graph.waypoint_mission_graph", "tools.agri_observation_task", '
             '"tools.rover_ground_executor", "rclpy", "langchain_ollama") if m in sys.modules])')
    result = subprocess.run([sys.executable, '-c', probe], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout.strip() == '[]'


def test_output_is_stable_across_runs(tmp_path):
    _, _, first, _ = run(tmp_path, 'a')
    _, _, second, _ = run(tmp_path, 'b')
    strip = lambda lines: [line for line in lines if 'Evidencias de esta ejecución' not in line]
    assert strip(first) == strip(second)
