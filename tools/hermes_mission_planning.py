"""Versioned planning boundary; Hermes interprets, services preserve explicit input."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from models.mission_plan_draft import MissionPlanDraft
from planning.artifact_store import (
    Conflict, atomic_json, boundary, child, file_mutex, fingerprint, read_object,
    safe_mission_id, sha256, utc_now,
)
from planning.draft_provenance import (
    InputAttribution, SHARED_MISSION_FIELDS, facts, provenance_view, record_sources,
)
from planning.mission_plan_service import (
    build_mission_from_draft, get_missing_planning_fields, merge_mission_plan_drafts,
)
from planning.relative_routes import RelativeRouteRequest, generate_relative_route
from tools.hermes_mission_validation import validate_mission_file

DRAFT_ROOT = Path(__file__).resolve().parents[1] / "missions/generated/drafts"


def _directory(draft_id: str) -> Path:
    return child(DRAFT_ROOT, draft_id)


def _geometry_digest(draft):
    return fingerprint(draft.geometry_intent.model_dump(mode="json") if draft.geometry_intent else None)


def read_draft_record(draft_id: str) -> tuple[MissionPlanDraft, dict]:
    """Verify without migration/writes. A concurrent edit may cause a retryable read error."""
    directory = _directory(draft_id)
    content = (directory / "draft.json").read_bytes()
    draft = MissionPlanDraft.model_validate_json(content)
    state_path = directory / "draft_state.json"
    state = read_object(state_path) if state_path.exists() else {
        "draft_id": draft_id, "draft_revision": 0, "draft_sha256": sha256(content),
        "route_provenance": None, "provenance_status": "LEGACY_UNKNOWN",
    }
    if (state.get("draft_id") != draft_id or type(state.get("draft_revision")) is not int
            or state["draft_revision"] < 0 or state.get("draft_sha256") != sha256(content)):
        raise ValueError("Draft metadata/hash inconsistent; reconcile files before further edits")
    if state.get("route_provenance") is not None and not isinstance(state["route_provenance"], dict):
        raise ValueError("Invalid route provenance record")
    if state.get("schema_version") == 2:
        if (state.get("geometry_intent_sha256") != _geometry_digest(draft)
                or type(state.get("geometry_revision")) is not int or state["geometry_revision"] < 0):
            raise ValueError("Geometry metadata/version inconsistent")
        values, sources = facts(draft), state.get("field_provenance")
        if not isinstance(sources, dict):
            raise ValueError("Invalid field provenance record")
        for path, entry in sources.items():
            if (not isinstance(entry, dict) or path not in values
                    or entry.get("value_sha256") != fingerprint(values[path])
                    or entry.get("authenticated") is not False
                    or entry.get("source") not in {"UNKNOWN", "OPERATOR_DECLARED_VIA_AGENT",
                                                   "DETERMINISTIC_GENERATION", "DETERMINISTIC_DERIVATION"}):
                raise ValueError("Field provenance/content inconsistent")
    if draft.geometry_intent is not None:
        if state.get("schema_version") != 2:
            raise ValueError("Geometry intent requires matching versioned metadata")
        geometry = generate_relative_route(draft.geometry_intent)
        for field in SHARED_MISSION_FIELDS:
            if getattr(draft, field) != getattr(draft.geometry_intent, field):
                raise ValueError("Shared mission/geometry fields inconsistent")
        if geometry["status"] == "INCOMPLETE":
            if draft.waypoints or state.get("route_provenance") is not None:
                raise ValueError("Incomplete geometry cannot retain an old route")
        elif (draft.waypoints != MissionPlanDraft(waypoints=geometry["waypoints"]).waypoints
              or state.get("route_provenance") != geometry["provenance"]):
            raise ValueError("Generated route does not match its geometry intent/provenance")
    return draft, state


def _read(draft_id: str) -> MissionPlanDraft:
    return read_draft_record(draft_id)[0]


def draft_result(draft_id: str, draft: MissionPlanDraft, state: dict) -> dict:
    mission_missing = get_missing_planning_fields(draft)
    geometry = (generate_relative_route(draft.geometry_intent) if draft.geometry_intent
                else {"status": "NOT_REQUESTED", "missing_fields": []})
    geometry_missing = geometry["missing_fields"]
    missing = mission_missing + ["geometry." + key for key in geometry_missing]
    route_provenance = state.get("route_provenance")
    if route_provenance and route_provenance.get("source") == "explicit_operator_parameters":
        route_provenance = {**route_provenance, "source": "LEGACY_GENERATION_METADATA",
                            "stored_source": "explicit_operator_parameters", "input_authentication": "UNKNOWN_NOT_VERIFIED"}
    return {**state, "status": "INCOMPLETE" if missing else "COMPLETE", "draft_id": draft_id,
            "draft": draft.model_dump(mode="json"), "geometry": geometry,
            "geometry_intent": draft.geometry_intent.model_dump(mode="json") if draft.geometry_intent else None,
            "geometry_revision": state.get("geometry_revision"),
            "route_provenance": route_provenance,
            "mission_missing_fields": mission_missing, "geometry_missing_fields": geometry_missing,
            "pending": {"route_generation": geometry_missing, "mission_finalization": missing},
            "missing_fields": missing, "errors": [], **provenance_view(draft, state)}


def _check_revision(state, expected_revision):
    if expected_revision is not None and (type(expected_revision) is not int
                                         or expected_revision != state["draft_revision"]):
        raise Conflict("Draft version changed; read the current draft before editing")


def _save(draft_id, current, draft, previous, route_provenance, sources):
    if not draft_result(draft_id, draft, previous)["missing_fields"]:
        build_mission_from_draft(draft)
    directory = _directory(draft_id)
    directory.mkdir(parents=True, exist_ok=True)
    content = draft.model_dump_json(indent=2).encode()
    state = {"schema_version": 2, "draft_id": draft_id,
             "draft_revision": previous["draft_revision"] + 1,
             "draft_sha256": sha256(content), "route_provenance": route_provenance,
             "geometry_revision": previous.get("geometry_revision", 0) + int(draft.geometry_intent != current.geometry_intent),
             "geometry_intent_sha256": _geometry_digest(draft), "field_provenance": sources,
             "provenance_status": "UNVERIFIED_AGENT_INPUT", "updated_at": utc_now()}
    if not (directory / "draft.json").exists():
        atomic_json(directory / "draft_state.json", state)
    temporary = directory / "draft.tmp"
    temporary.write_bytes(content)
    temporary.replace(directory / "draft.json")
    atomic_json(directory / "draft_state.json", state)
    return draft_result(draft_id, draft, state)


def _prepare(current, updates, replace_route):
    normalized = updates
    if current.geometry_intent is not None or updates.geometry_intent is not None:
        # Shared facts can be supplied in either location; contradictory facts
        # in one request are errors, never arbitrarily resolved by precedence.
        patch = updates.geometry_intent or RelativeRouteRequest()
        values = patch.model_dump(exclude_none=True)
        if current.geometry_intent is None:
            values = {**{k: getattr(current, k) for k in SHARED_MISSION_FIELDS if getattr(current, k) is not None}, **values}
        for field in SHARED_MISSION_FIELDS:
            value = getattr(updates, field)
            if value is not None:
                if getattr(patch, field) is not None and value != getattr(patch, field):
                    raise ValueError(f"Contradictory mission/geometry {field}")
                values[field] = value
        normalized = updates.model_copy(update={"geometry_intent": RelativeRouteRequest.model_validate(values)})
    merged = merge_mission_plan_drafts(current, normalized)
    if updates.wind_direction_from is not None and updates.wind_direction_from_deg is None:
        merged.wind_direction_from_deg = None
    elif updates.wind_direction_from_deg is not None:
        merged.wind_direction_from = None
    route_provenance = None
    generated = False
    if merged.geometry_intent is not None and updates.waypoints:
        if updates.geometry_intent is not None:
            raise ValueError("Cannot combine a geometry patch and a manual waypoint list")
        if not replace_route:
            raise Conflict("Manual replacement of geometry requires replace_route=true; the intent will be detached")
        merged.geometry_intent = None
        merged.waypoints = updates.waypoints
    elif merged.geometry_intent is not None:
        if merged.geometry_intent != current.geometry_intent and current.waypoints and not replace_route:
            raise Conflict("Existing route: geometry changes require explicit replace_route=true")
        for field in SHARED_MISSION_FIELDS:
            setattr(merged, field, getattr(merged.geometry_intent, field))
        geometry = generate_relative_route(merged.geometry_intent)
        if geometry["status"] == "GENERATED":
            merged.waypoints = MissionPlanDraft(waypoints=geometry["waypoints"]).waypoints
            route_provenance = geometry["provenance"]
            generated = merged.geometry_intent != current.geometry_intent
        else:
            merged.waypoints = []
    elif replace_route and "waypoints" in updates.model_fields_set:
        merged.waypoints = updates.waypoints
    return merged, route_provenance, generated


@boundary
def update_mission_draft(updates: MissionPlanDraft, draft_id: str | None = None,
                         expected_revision: int | None = None, replace_route: bool = False,
                         attributions: dict[str, InputAttribution] | None = None) -> dict:
    """Merge mission/geometry facts. Null preserves; mode changes clear old shape parameters.

    New geometry/replacement edits to an existing draft require its current
    revision. Legacy ordinary mission merges may still omit expected_revision.
    """
    creating = draft_id is None
    draft_id = draft_id or str(uuid4())
    directory = _directory(draft_id)
    if not creating and not (directory / "draft.json").is_file():
        raise ValueError("Draft not found")
    with file_mutex(directory / "draft.lock"):
        current, state = (MissionPlanDraft(), {"draft_revision": 0}) if creating else read_draft_record(draft_id)
        _check_revision(state, expected_revision)
        geometry_edit = (updates.geometry_intent is not None or replace_route
                         or current.geometry_intent is not None and any(
                             getattr(updates, key) is not None for key in SHARED_MISSION_FIELDS))
        if not creating and geometry_edit and type(expected_revision) is not int:
            raise ValueError("Geometry/replacement edits require the current integer expected_revision")
        merged, route_provenance, generated = _prepare(current, updates, replace_route)
        if current.geometry_intent is None and updates.geometry_intent is None and not replace_route:
            route_provenance = state.get("route_provenance")
            if route_provenance and (merged.waypoints != current.waypoints or any(
                    getattr(merged, key) != getattr(current, key) for key in SHARED_MISSION_FIELDS)):
                route_provenance = {**route_provenance, "subsequently_edited": True,
                                    "note": "Earlier generated parameters do not describe the edited route"}
        sources = record_sources(current, merged, state, updates, attributions or {}, generated, replace_route)
        if not creating and merged == current and sources == state.get("field_provenance", {}):
            return draft_result(draft_id, current, state)
        return _save(draft_id, current, merged, state, route_provenance, sources)


@boundary
def generate_draft_route(draft_id: str, expected_revision: int, request: RelativeRouteRequest,
                         replace_route: bool = False,
                         attributions: dict[str, InputAttribution] | None = None) -> dict:
    """Persist partial intent or deterministically generate the complete route, never fly."""
    if type(expected_revision) is not int:
        raise ValueError("A current integer expected_revision is required")
    return update_mission_draft(MissionPlanDraft(geometry_intent=request), draft_id,
                                expected_revision, replace_route, attributions)


@boundary
def finalize_mission_draft(draft_id: str, expected_revision: int | None = None) -> dict:
    """Snapshot one coherent version; validation/export once, with effective defaults shown."""
    directory = _directory(draft_id)
    if not (directory / "draft.json").is_file():
        raise ValueError("Draft not found")
    with file_mutex(directory / "draft.lock"):
        draft, state = read_draft_record(draft_id)
        _check_revision(state, expected_revision)
        result = draft_result(draft_id, draft, state)
        if result["missing_fields"]:
            return result
        mission = build_mission_from_draft(draft)
        safe_mission_id(mission.mission_id)
        finalization_id = str(uuid4())
        snapshot = directory / finalization_id
        snapshot.mkdir()
        (snapshot / "source_draft.json").write_bytes((directory / "draft.json").read_bytes())
        # Copy the exact stored sidecar, including any old labels, without migrating it.
        stored_state = directory / "draft_state.json"
        state_bytes = stored_state.read_bytes() if stored_state.exists() else None
        if state_bytes is not None:
            (snapshot / "source_draft_state.json").write_bytes(state_bytes)
    mission_path = snapshot / "mission.json"
    mission_path.write_text(mission.model_dump_json(indent=2), encoding="utf-8")
    validation = validate_mission_file(str(mission_path), export_qgc=True, output_dir=str(snapshot))
    plan = validation.get("qgc_plan_path")
    record = {"kind": "finalization", "finalization_id": finalization_id,
              "draft_id": draft_id, "draft_revision": state["draft_revision"],
              "draft_sha256": state["draft_sha256"], "route_provenance": result["route_provenance"],
              "geometry_intent": result["geometry_intent"], "geometry_revision": result["geometry_revision"],
              "draft_state_sha256": sha256(state_bytes) if state_bytes is not None else None,
              **provenance_view(draft, state), "created_at": utc_now(), "mission_path": str(mission_path),
              "mission_sha256": sha256(mission_path.read_bytes()), "validation": validation,
              "qgc_plan_sha256": sha256(Path(plan).read_bytes()) if plan else None,
              "flight_consent": "NOT_GRANTED"}
    atomic_json(snapshot / "finalization.json", record)
    return {**result, "status": "VALIDATED", "finalization_id": finalization_id,
            "mission_path": str(mission_path), "mission_sha256": record["mission_sha256"],
            "validation": validation, "user_execution_authorization_required": True,
            "before_rehearsal": "Present effective mission values, compatibility_defaults and provenance caveats before obtaining explicit rehearsal consent"}
