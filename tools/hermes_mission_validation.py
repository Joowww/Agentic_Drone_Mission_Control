"""Hermes-facing deterministic mission validation wrapper.

Loads a mission JSON file, evaluates it through the deterministic
waypoint mission graph, and emits a compact, machine-readable JSON
result via the command line.

No LLM is used for mission safety decisions; every safety verdict is
produced by the deterministic models/sessions pipeline
(``sessions.structured_mission_session.evaluate_structured_mission``).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys

from pydantic import ValidationError

from inputs.json_loader import load_mission_json
from models.mission_definition import MissionDefinition
from sessions.structured_mission_session import (
    evaluate_structured_mission,
)

# ---------------------------------------------------------------------------
# Result keys (kept as module-level constants so tests can reference them)
# ---------------------------------------------------------------------------
MISSION_ID = "mission_id"
MISSION_STATUS = "mission_status"
FAILURE_REASONS = "failure_reasons"
ERRORS = "errors"
REPLAN_STATUS = "replan_status"
REPLAN_ACTIONS = "replan_actions"


def _empty_result() -> dict[str, object]:
    """Create a result dict with all required keys initialised."""
    return {
        MISSION_ID: None,
        MISSION_STATUS: "UNKNOWN",
        FAILURE_REASONS: [],
        ERRORS: [],
        REPLAN_STATUS: "",
        REPLAN_ACTIONS: [],
    }


def validate_mission(
    mission: MissionDefinition,
) -> dict[str, object]:
    """Evaluate an already-loaded mission deterministically.

    All human-readable stdout produced by the evaluation pipeline is
    captured and discarded so that callers receive only the machine-
    readable result.
    """
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        final_state = evaluate_structured_mission(mission)

    result = _empty_result()
    result[MISSION_ID] = mission.mission_id
    result[MISSION_STATUS] = final_state.get(
        MISSION_STATUS, "UNKNOWN"
    )
    result[FAILURE_REASONS] = final_state.get(
        FAILURE_REASONS, []
    )
    result[ERRORS] = final_state.get(ERRORS, [])
    result[REPLAN_STATUS] = final_state.get(
        REPLAN_STATUS, ""
    )
    result[REPLAN_ACTIONS] = final_state.get(
        REPLAN_ACTIONS, []
    )
    return result


def validate_mission_file(
    mission_path: str,
) -> dict[str, object]:
    """Load a mission JSON file and validate it deterministically.

    Load-time errors (missing file, malformed JSON, invalid schema) are
    captured in the ``errors`` list and the ``mission_status`` is set
    to ``ERROR`` or ``INVALID`` accordingly.
    """
    result = _empty_result()

    try:
        mission = load_mission_json(mission_path)
    except FileNotFoundError as exc:
        result[MISSION_STATUS] = "ERROR"
        result[ERRORS].append(
            f"File not found: {exc}"
        )
        return result
    except (ValueError, ValidationError) as exc:
        result[MISSION_STATUS] = "INVALID"
        result[ERRORS].append(str(exc))
        return result

    return validate_mission(mission)


def main(
    argv: list[str] | None = None,
) -> int:
    """Command-line entry point.

    Prints a single JSON object to stdout and nothing else.
    """
    parser = argparse.ArgumentParser(
        prog=(
            "python -m tools.hermes_mission_validation"
        ),
        description=(
            "Deterministic mission validation wrapper. Loads a "
            "mission JSON file and evaluates it through the "
            "deterministic waypoint mission graph, printing a "
            "compact JSON result. No LLM is used for safety."
        ),
    )
    parser.add_argument(
        "--mission",
        required=True,
        help="Path to the mission JSON file to validate.",
    )
    args = parser.parse_args(argv)

    result = validate_mission_file(args.mission)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
