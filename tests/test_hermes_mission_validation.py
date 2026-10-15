"""Tests for the Hermes-facing deterministic mission validation wrapper."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from inputs.json_loader import load_mission_json
from tools.hermes_mission_validation import (
    ERRORS,
    EXECUTION_STATUS,
    FAILURE_REASONS,
    MISSION_ID,
    MISSION_STATUS,
    QGC_PLAN_PATH,
    REPLAN_ACTIONS,
    REPLAN_STATUS,
    validate_mission,
    validate_mission_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MISSION = (
    PROJECT_ROOT
    / "missions"
    / "examples"
    / "precision_agriculture_demo.json"
)

REQUIRED_KEYS = {
    MISSION_ID,
    MISSION_STATUS,
    EXECUTION_STATUS,
    QGC_PLAN_PATH,
    FAILURE_REASONS,
    ERRORS,
    REPLAN_STATUS,
    REPLAN_ACTIONS,
}


# ---------------------------------------------------------------------------
# Valid mission
# ---------------------------------------------------------------------------
def test_valid_mission_file_returns_compact_result():
    """A valid mission file yields a result with all required keys."""
    result = validate_mission_file(str(EXAMPLE_MISSION))

    assert set(result) >= REQUIRED_KEYS
    assert result[MISSION_ID] == "precision_agriculture_001"
    assert result[MISSION_STATUS] == "NOT FEASIBLE"
    assert result[ERRORS] == []
    assert len(result[FAILURE_REASONS]) > 0
    assert isinstance(result[REPLAN_ACTIONS], list)
    assert isinstance(result[REPLAN_STATUS], str)


def test_valid_mission_evaluation_is_deterministic():
    """The same mission always produces the same verdict."""
    first = validate_mission_file(str(EXAMPLE_MISSION))
    second = validate_mission_file(str(EXAMPLE_MISSION))
    assert first == second


def test_validate_mission_suppresses_stdout(capsys):
    """No human-readable text leaks to stdout during evaluation."""
    mission = load_mission_json(str(EXAMPLE_MISSION))
    validate_mission(mission)
    captured = capsys.readouterr()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# Invalid / missing input
# ---------------------------------------------------------------------------
def test_missing_mission_file_returns_error():
    """A non-existent path yields an ERROR status with a message."""
    result = validate_mission_file(
        str(PROJECT_ROOT / "nonexistent_mission.json")
    )
    assert result[MISSION_STATUS] == "ERROR"
    assert len(result[ERRORS]) > 0
    assert result[MISSION_ID] is None


def test_malformed_json_returns_invalid(tmp_path):
    """Broken JSON is caught and reported as INVALID."""
    bad = tmp_path / "broken.json"
    bad.write_text("{ not valid json }")

    result = validate_mission_file(str(bad))
    assert result[MISSION_STATUS] == "INVALID"
    assert len(result[ERRORS]) > 0


def test_invalid_schema_returns_invalid(tmp_path):
    """A JSON object missing required fields is INVALID."""
    bad = tmp_path / "incomplete.json"
    bad.write_text(json.dumps({"mission_id": "broken"}))

    result = validate_mission_file(str(bad))
    assert result[MISSION_STATUS] == "INVALID"
    assert len(result[ERRORS]) > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_emits_only_valid_json():
    """The CLI stdout must be parseable JSON with no leaked messages."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.hermes_mission_validation",
            "--mission",
            str(EXAMPLE_MISSION),
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data[MISSION_ID] == "precision_agriculture_001"
    # No internal log messages should leak to stdout
    assert "[LANGGRAPH]" not in proc.stdout
    assert "[NODE]" not in proc.stdout
    assert "[MISSION SAFETY]" not in proc.stdout
    assert "[FLIGHT DYNAMICS]" not in proc.stdout


# ---------------------------------------------------------------------------
# QGC export — FEASIBLE / APPROVED path
# ---------------------------------------------------------------------------
def _make_feasible_mission(tmp_path):
    """Create a temporary feasible mission (high battery) JSON."""
    data = json.loads(EXAMPLE_MISSION.read_text())
    data["mission_id"] = "feasible_recce_001"
    data["vehicle"]["battery_percent"] = 100.0
    path = tmp_path / "feasible.json"
    path.write_text(json.dumps(data))
    return path


def test_export_qgc_feasible_produces_approved_plan(tmp_path):
    """A FEASIBLE mission yields APPROVED + <mission_id>.plan."""
    mission_path = _make_feasible_mission(tmp_path)
    out_dir = tmp_path / "plans"

    result = validate_mission_file(
        str(mission_path),
        export_qgc=True,
        output_dir=str(out_dir),
    )

    assert set(result) >= REQUIRED_KEYS
    assert result[MISSION_STATUS] == "FEASIBLE"
    assert result[EXECUTION_STATUS] == "APPROVED"
    assert result[MISSION_ID] == "feasible_recce_001"
    expected = out_dir / "feasible_recce_001.plan"
    assert result[QGC_PLAN_PATH] == str(expected)
    assert expected.exists()
    # No stale candidate file should remain
    stale = out_dir / "feasible_recce_001_candidate.plan"
    assert not stale.exists()


# ---------------------------------------------------------------------------
# QGC export — NOT FEASIBLE / BLOCKED path
# ---------------------------------------------------------------------------
def test_export_qgc_not_feasible_produces_blocked_candidate_plan(tmp_path):
    """A NOT FEASIBLE mission yields BLOCKED + <mission_id>_candidate.plan."""
    out_dir = tmp_path / "plans"

    result = validate_mission_file(
        str(EXAMPLE_MISSION),
        export_qgc=True,
        output_dir=str(out_dir),
    )

    assert set(result) >= REQUIRED_KEYS
    assert result[MISSION_STATUS] == "NOT FEASIBLE"
    assert result[EXECUTION_STATUS] == "BLOCKED"
    expected = (
        out_dir / "precision_agriculture_001_candidate.plan"
    )
    assert result[QGC_PLAN_PATH] == str(expected)
    assert expected.exists()
    # No stale approved file should remain
    stale = out_dir / "precision_agriculture_001.plan"
    assert not stale.exists()


# ---------------------------------------------------------------------------
# QGC export — invalid input
# ---------------------------------------------------------------------------
def test_export_qgc_invalid_input_no_plan(tmp_path):
    """Invalid input with --export-qgc does not create a .plan file."""
    bad = tmp_path / "broken.json"
    bad.write_text("{ not valid json }")
    out_dir = tmp_path / "plans"

    result = validate_mission_file(
        str(bad),
        export_qgc=True,
        output_dir=str(out_dir),
    )

    assert result[MISSION_STATUS] == "INVALID"
    assert len(result[ERRORS]) > 0
    assert result[EXECUTION_STATUS] is None
    assert result[QGC_PLAN_PATH] is None
    # No .plan files should have been created
    if out_dir.exists():
        assert not list(out_dir.glob("*.plan"))


# ---------------------------------------------------------------------------
# QGC export — JSON-only CLI stdout
# ---------------------------------------------------------------------------
def test_cli_with_export_qgc_emits_only_valid_json(tmp_path):
    """--export-qgc CLI emits pure JSON to stdout."""
    mission_path = _make_feasible_mission(tmp_path)
    out_dir = tmp_path / "plans"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.hermes_mission_validation",
            "--mission",
            str(mission_path),
            "--export-qgc",
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data[MISSION_ID] == "feasible_recce_001"
    assert data[EXECUTION_STATUS] == "APPROVED"
    expected = out_dir / "feasible_recce_001.plan"
    assert data[QGC_PLAN_PATH] == str(expected)
    assert expected.exists()
    # stdout must be purely valid JSON — no internal log messages
    assert "[LANGGRAPH]" not in proc.stdout
    assert "[NODE]" not in proc.stdout
    assert "[MISSION SAFETY]" not in proc.stdout
    assert "[FLIGHT DYNAMICS]" not in proc.stdout


# ---------------------------------------------------------------------------
# QGC export — existing validation behaviour preserved
# ---------------------------------------------------------------------------
def test_validation_only_no_export(tmp_path):
    """Without --export-qgc, validation result is unchanged."""
    out_dir = tmp_path / "plans"

    result = validate_mission_file(
        str(EXAMPLE_MISSION),
        export_qgc=False,
        output_dir=str(out_dir),
    )

    assert set(result) >= REQUIRED_KEYS
    # Same verdict as the plain validation test
    assert result[MISSION_ID] == "precision_agriculture_001"
    assert result[MISSION_STATUS] == "NOT FEASIBLE"
    assert result[ERRORS] == []
    assert len(result[FAILURE_REASONS]) > 0

    # execution_status is still derived from mission_status
    assert result[EXECUTION_STATUS] == "BLOCKED"

    # No plan file should be created when export is disabled
    assert result[QGC_PLAN_PATH] is None
    assert not out_dir.exists()
