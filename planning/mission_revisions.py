"""Persistent proposals and explicit revisions; no infrastructure/flight operations."""
import json
from pathlib import Path
from uuid import uuid4

from pydantic import ConfigDict

from editing.mission_update_service import apply_mission_update
from models.mission_update import MissionUpdate, WaypointUpdate, WaypointAddition
from planning.artifact_store import (
    Conflict, atomic_json, boundary, child, file_mutex, fingerprint, prior_request,
    read_object, request_path, safe_mission_id, save_request, sha256, structured_diff, utc_now,
)
from planning.mission_plan_service import DIRECTION_BEARINGS
from planning.verified_preflight import verified_source
from tools.hermes_mission_validation import validate_mission_file

REVISION_ROOT = Path(__file__).resolve().parents[1] / "missions/generated/revisions"


class ExplicitWaypointUpdate(WaypointUpdate):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExplicitWaypointAddition(WaypointAddition):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RevisionChanges(MissionUpdate):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    waypoint_updates: list[ExplicitWaypointUpdate] = []
    waypoint_additions: list[ExplicitWaypointAddition] = []


@boundary
def propose_mission_revision(run_id: str, request_key: str):
    with file_mutex(REVISION_ROOT / "proposals.lock"):
        source = verified_source(run_id)
        key = request_path(REVISION_ROOT / "proposals", request_key)
        identity = {"run_id": run_id, "mission_sha256": source["mission_sha256"],
                    "report_sha256": source["report_sha256"]}
        digest = fingerprint(identity)
        prior = prior_request(key, digest)
        if prior:
            if (prior["status"] == "BUILDING" and not (
                    child(REVISION_ROOT / "proposals", prior["proposal_id"]) / "proposal.json").exists()):
                return {**prior, "message": "Incomplete proposal intent; reconcile without recreating it."}
            return get_revision_proposal(prior["proposal_id"])
        report = source["report"]
        status = report["status"]
        conditions = []
        actions = source["validation"].get("replan_actions", [])
        category = "PLANNING_REVIEW"
        if status == "PASSED":
            category, actions = "NO_CORRECTION_REQUIRED", []
        elif status == "FAILED":
            category, actions = "INVESTIGATE_EXECUTION", []
            conditions.append("Investigate the failed waypoint/telemetry/environment; cause unknown. No automatic fix or repeat flight.")
        elif report.get("stage") == "check_readiness":
            category, actions = "INFRASTRUCTURE_PENDING", []
            conditions.append("Simulation readiness must be checked later; no mission edit repairs infrastructure.")
        elif status == "ERROR":
            category, actions = "MANUAL_INVESTIGATION", []
            conditions.append("Resolve the reported error; flight outcome may be unconfirmed.")
        if any("battery" in action.lower() for action in actions):
            conditions.append("Recharge/replace battery physically, then explicitly declare its new level; no telemetry measurement is implied.")
        proposal_id = str(uuid4())
        directory = child(REVISION_ROOT / "proposals", proposal_id)
        save_request(key, digest, {"status": "BUILDING", "proposal_id": proposal_id})
        directory.mkdir(parents=True)
        (directory / "source_mission.json").write_bytes(source["mission_bytes"])
        (directory / "source_report.json").write_bytes(source["report_bytes"])
        proposal = {"proposal_id": proposal_id, "version": 1, "created_at": utc_now(),
                    **identity, "mission_id": source["mission"].mission_id, "category": category,
                    "source_report_path": source["report_path"], "source_mission_path": source["mission_path"],
                    "reasons": report.get("reasons", []), "proposed_changes": actions,
                    "pending_conditions": conditions, "automatic_patch": None,
                    "diagnostic": (report.get("executor_result") or {}).get("waypoint_diagnostic"),
                    "execution_evidence": report.get("executor_result"),
                    "replanner_scope": "Text recommendations only; no generated route, no guaranteed battery solution.",
                    "flight_consent": "NOT_INHERITED"}
        atomic_json(directory / "proposal.json", proposal)
        result = get_revision_proposal(proposal_id)
        save_request(key, digest, result)
        return result


@boundary
def get_revision_proposal(proposal_id: str):
    directory = child(REVISION_ROOT / "proposals", proposal_id)
    content = (directory / "proposal.json").read_bytes()
    proposal = json.loads(content)
    if not isinstance(proposal, dict):
        raise ValueError("Invalid proposal object")
    if proposal["proposal_id"] != proposal_id or proposal["version"] != 1:
        raise ValueError("Invalid proposal identity/version")
    for filename, expected in (("source_mission.json", proposal["mission_sha256"]),
                               ("source_report.json", proposal["report_sha256"])):
        if sha256((directory / filename).read_bytes()) != expected:
            raise ValueError("Proposal source copy changed")
    return {"status": "PROPOSED", "proposal": proposal, "proposal_id": proposal_id,
            "proposal_sha256": sha256(content),
            "proposal_path": str(directory / "proposal.json")}


@boundary
def build_mission_revision(proposal_id: str, expected_proposal_sha256: str,
                           changes: RevisionChanges, operator_statement: str,
                           request_key: str, declarations: dict[str, str] | None = None):
    if not operator_statement.strip():
        raise ValueError("Explicit operator changes/acceptance statement is required")
    declarations = declarations or {}
    with file_mutex(REVISION_ROOT / "revisions.lock"):
        reviewed = get_revision_proposal(proposal_id)
        if reviewed["status"] != "PROPOSED":
            raise ValueError(str(reviewed))
        if reviewed["proposal_sha256"] != expected_proposal_sha256:
            raise Conflict("Proposal version changed since review")
        proposal = reviewed["proposal"]
        source = verified_source(proposal["run_id"])
        if any(source[k] != proposal[k] for k in ("mission_sha256", "report_sha256")):
            raise ValueError("Original source changed since proposal review")
        submitted = changes.model_dump(mode="json")
        digest = fingerprint({"proposal_sha256": expected_proposal_sha256, "changes": submitted,
                              "operator_statement": operator_statement, "declarations": declarations})
        key = request_path(REVISION_ROOT / "revisions", request_key)
        previous = prior_request(key, digest)
        if previous:
            if previous["status"] == "REVISED":
                from planning.mission_artifacts import load_revision
                load_revision(previous["revision_id"])
                saved = read_object(child(REVISION_ROOT / "missions", previous["revision_id"]) / "revision.json")
                if saved != previous:
                    raise ValueError("Saved revision differs from its request record")
            return previous
        physical = {"battery_percent", "wind_speed_kmh", "wind_direction_from", "wind_direction_from_deg",
                    "battery_consumption_percent_per_minute"}
        for field in physical:
            if submitted.get(field) is not None and not declarations.get(field, "").strip():
                raise ValueError(f"Explicit operator declaration required for {field}")
        original = source["mission"]
        if (changes.minimum_battery_reserve_percent is not None
                and changes.minimum_battery_reserve_percent < original.constraints.minimum_battery_reserve_percent
                or changes.maximum_altitude_m is not None and changes.maximum_altitude_m > original.constraints.maximum_altitude_m
                or changes.maximum_wind_speed_kmh is not None and changes.maximum_wind_speed_kmh > original.constraints.maximum_wind_speed_kmh):
            raise ValueError("Weakening safety constraints is outside this revision interface")
        effective = changes
        if changes.wind_direction_from is not None:
            degrees = DIRECTION_BEARINGS[changes.wind_direction_from]
            if changes.wind_direction_from_deg not in (None, degrees):
                raise ValueError("Contradictory wind direction representations")
            effective = changes.model_copy(update={"wind_direction_from_deg": degrees})
        revised, _ = apply_mission_update(original, effective)
        differences = structured_diff(original.model_dump(mode="json"), revised.model_dump(mode="json"))
        if not differences:
            raise ValueError("No effective explicit changes; no revision created")
        safe_mission_id(revised.mission_id)
        revision_id = str(uuid4())
        directory = child(REVISION_ROOT / "missions", revision_id)
        save_request(key, digest, {"status": "BUILDING", "revision_id": revision_id,
                                   "message": "Do not repeat construction; reconcile incomplete artifact if interrupted."})
        directory.mkdir(parents=True)
        mission_path = directory / "mission.json"
        mission_path.write_text(revised.model_dump_json(indent=2), encoding="utf-8")
        validation = validate_mission_file(str(mission_path), export_qgc=True, output_dir=str(directory))
        record = {"status": "REVISED", "revision_id": revision_id, "proposal_id": proposal_id,
                  "kind": "revision",
                  "proposal_sha256": expected_proposal_sha256, "proposal_version": proposal["version"],
                  "source_run_id": proposal["run_id"], "source_report_sha256": source["report_sha256"],
                  "source_mission_sha256": source["mission_sha256"], "created_at": utc_now(),
                  "mission_path": str(mission_path), "mission_sha256": sha256(mission_path.read_bytes()),
                  "validation": validation,
                  "qgc_plan_sha256": sha256(Path(validation["qgc_plan_path"]).read_bytes())
                      if validation.get("qgc_plan_path") else None,
                  "differences": differences, "explicit_changes": submitted,
                  "operator_statement": operator_statement,
                  "declarations": {k: {"statement": v, "source": "operator_declared_not_telemetry"}
                                   for k, v in declarations.items()},
                  "pending_conditions": ["New mission content requires a new explicitly authorized preflight."],
                  "flight_consent": "NOT_GRANTED"}
        atomic_json(directory / "revision.json", record)
        save_request(key, digest, record)
        return record
