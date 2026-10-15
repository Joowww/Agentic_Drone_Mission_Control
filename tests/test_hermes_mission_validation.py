"""Tests for the Hermes-facing deterministic mission validation wrapper."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from inputs.json_loader import load_mission_json
from tools.hermes_mission_validation import (
    ERRORS,
    FAILURE_REASONS,
    MISSION_ID,
    MISSION_STATUS,
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
