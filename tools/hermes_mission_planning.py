"""Persistent planning boundary for Hermes; no LLM or flight commands.

Hermes extracts explicit operator facts into MissionPlanDraft. The existing
planning service merges partial updates and builds the shared mission model.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from models.mission_plan_draft import MissionPlanDraft
from planning.mission_plan_service import (
    build_mission_from_draft,
    get_missing_planning_fields,
    merge_mission_plan_drafts,
)
from tools.hermes_mission_validation import validate_mission_file

DRAFT_ROOT = Path(__file__).resolve().parents[1] / "missions/generated/drafts"


def _directory(draft_id: str) -> Path:
    # IDs are opaque UUIDs, never caller-controlled paths or mission names.
    return DRAFT_ROOT / str(UUID(draft_id))


def _read(draft_id: str) -> MissionPlanDraft:
    return MissionPlanDraft.model_validate_json(
        (_directory(draft_id) / "draft.json").read_text()
    )


def _result(draft_id: str, draft: MissionPlanDraft) -> dict[str, object]:
    missing = get_missing_planning_fields(draft)
    return {
        "status": "INCOMPLETE" if missing else "COMPLETE",
        "draft_id": draft_id,
        "draft": draft.model_dump(mode="json"),
        "missing_fields": missing,
        "errors": [],
    }


def _error(exc: Exception) -> dict[str, object]:
    return {"status": "ERROR", "errors": [str(exc)]}


def update_mission_draft(
    updates: MissionPlanDraft, draft_id: str | None = None,
) -> dict[str, object]:
    """Create or merge a draft. Empty updates retrieve it after a restart.

    Null fields preserve prior values; waypoint IDs merge case-insensitively.
    This first increment does not support deleting fields or waypoints.
    """
    try:
        current = _read(draft_id) if draft_id else MissionPlanDraft()
        merged = merge_mission_plan_drafts(current, updates)
        # A new wind representation explicitly replaces the previous one.
        if updates.wind_direction_from is not None and updates.wind_direction_from_deg is None:
            merged.wind_direction_from_deg = None
        elif updates.wind_direction_from_deg is not None:
            merged.wind_direction_from = None
        if not get_missing_planning_fields(merged):
            build_mission_from_draft(merged)
        draft_id = draft_id or str(uuid4())
        directory = _directory(draft_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "draft.tmp"
        temporary.write_text(merged.model_dump_json(indent=2))
        temporary.replace(directory / "draft.json")
        return _result(draft_id, merged)
    except (ValueError, OSError, ValidationError) as exc:
        return _error(exc)


def finalize_mission_draft(draft_id: str) -> dict[str, object]:
    """Materialize a snapshot and run the existing validation/export pipeline."""
    try:
        draft = _read(draft_id)
        result = _result(draft_id, draft)
        if result["missing_fields"]:
            return result
        mission = build_mission_from_draft(draft)
        # Exporter uses mission_id as a filename. Never use an operator path there.
        safe_id = mission.mission_id
        if not safe_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in safe_id):
            raise ValueError("mission_id must contain only letters, digits, underscores or hyphens")
        # Unique snapshot directory avoids overwriting previously reviewed missions.
        directory = _directory(draft_id) / str(uuid4())
        directory.mkdir()
        mission_path = directory / "mission.json"
        mission_path.write_text(mission.model_dump_json(indent=2))
        validation = validate_mission_file(
            str(mission_path), export_qgc=True, output_dir=str(directory),
        )
        return {
            **result, "status": "VALIDATED", "mission_path": str(mission_path),
            "validation": validation,
            "user_execution_authorization_required": True,
        }
    except (ValueError, OSError, ValidationError) as exc:
        return _error(exc)
