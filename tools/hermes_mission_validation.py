"""Hermes-facing deterministic mission validation wrapper.

Loads a mission JSON file, evaluates it through the deterministic
waypoint mission graph, and emits a compact, machine-readable JSON
result via the command line.

No LLM is used for mission safety decisions; every safety verdict is
produced by the deterministic models/sessions pipeline
(``sessions.structured_mission_session.evaluate_structured_mission``).

When ``--export-qgc`` is supplied the wrapper additionally exports a
QGroundControl ``.plan`` file for the validated mission:

* FEASIBLE  -> APPROVED  ->  ``<mission_id>.plan``
* NOT FEASIBLE -> BLOCKED ->  ``<mission_id>_candidate.plan``
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
    export_validated_mission_plan,
)

# ---------------------------------------------------------------------------
# Result keys (kept as module-level constants so tests can reference them)
# ---------------------------------------------------------------------------
MISSION_ID = "mission_id"
MISSION_STATUS = "mission_status"
EXECUTION_STATUS = "execution_status"
QGC_PLAN_PATH = "qgc_plan_path"
FAILURE_REASONS = "failure_reasons"
ERRORS = "errors"
REPLAN_STATUS = "replan_status"
REPLAN_ACTIONS = "replan_actions"


def _empty_result() -> dict[str, object]:
    """Create a result dict with all required keys initialised."""
    return {
        MISSION_ID: None,
        MISSION_STATUS: "UNKNOWN",
        EXECUTION_STATUS: None,
        QGC_PLAN_PATH: None,
        FAILURE_REASONS: [],
        ERRORS: [],
        REPLAN_STATUS: "",
        REPLAN_ACTIONS: [],
    }


def _derive_execution_status(
    mission_status: str,
) -> str | None:
    """Map a mission_status to an execution_status.

    FEASIBLE -> APPROVED, NOT FEASIBLE -> BLOCKED, otherwise None.
    """
    if mission_status == "FEASIBLE":
        return "APPROVED"
    if mission_status == "NOT FEASIBLE":
        return "BLOCKED"
    return None


def validate_mission(
    mission: MissionDefinition,
    *,
    export_qgc: bool = False,
    output_dir: str | None = None,
) -> dict[str, object]:
    """Evaluate an already-loaded mission deterministically.

    All human-readable stdout produced by the evaluation pipeline is
    captured and discarded so that callers receive only the machine-
    readable result.

    When *export_qgc* is true a QGroundControl ``.plan`` file is
    exported via ``export_validated_mission_plan`` and the
    ``execution_status`` / ``qgc_plan_path`` fields are populated.
    """
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        final_state = evaluate_structured_mission(mission)

        export_meta = None
        if export_qgc:
            export_meta = export_validated_mission_plan(
                mission=mission,
                final_state=final_state,
                output_directory=output_dir,
            )

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

    # Always derive execution_status from the safety verdict.
    result[EXECUTION_STATUS] = _derive_execution_status(
        result[MISSION_STATUS]
    )

    if export_meta is not None:
        result[EXECUTION_STATUS] = export_meta[
            "execution_status"
        ]
        qgc_path = export_meta.get("qgc_plan_path")
        result[QGC_PLAN_PATH] = (
            str(qgc_path) if qgc_path is not None else None
        )

    return result


def validate_mission_file(
    mission_path: str,
    *,
    export_qgc: bool = False,
    output_dir: str | None = None,
) -> dict[str, object]:
    """Load a mission JSON file and validate it deterministically.

    Load-time errors (missing file, malformed JSON, invalid schema) are
    captured in the ``errors`` list and the ``mission_status`` is set
    to ``ERROR`` or ``INVALID`` accordingly.

    When *export_qgc* is true a QGroundControl ``.plan`` file is
    exported alongside validation (see ``validate_mission``).
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

    return validate_mission(
        mission,
        export_qgc=export_qgc,
        output_dir=output_dir,
    )


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
            "compact JSON result. No LLM is used for safety. "
            "Use --export-qgc to additionally export a "
            "QGroundControl .plan file."
        ),
    )
    parser.add_argument(
        "--mission",
        required=True,
        help="Path to the mission JSON file to validate.",
    )
    parser.add_argument(
        "--export-qgc",
        action="store_true",
        default=False,
        help=(
            "Export a QGroundControl .plan file alongside "
            "validation. APPROVED plans use <mission_id>.plan "
            "while BLOCKED plans use <mission_id>_candidate.plan."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory for exported .plan files. "
            "Defaults to missions/generated."
        ),
    )
    args = parser.parse_args(argv)

    result = validate_mission_file(
        args.mission,
        export_qgc=args.export_qgc,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
