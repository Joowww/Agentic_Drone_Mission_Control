"""Read-only summary of the agri_demo_001 scenario over an existing two-drone preflight sequence.

Two steps, both without effects:

1. ``bind_scenario`` associates, per drone, one mission artifact (H0 reference or a Hermes
   finalization) with the declared points of interest. It checks the exact bytes: vehicle, explicit
   POI -> waypoint association, geometry equal to the H0 reference and the same deterministic
   validation/compatibility the sequence coordinator applies. The result is identified by the
   artifact's SHA-256. It is not an authorization: consent stays in ``start_preflight_sequence``.
2. ``summarize_scenario`` interprets ``get_preflight_sequence(detail=True)``, which already verifies
   plan, snapshots, child reports and recomputed analyses. Results are attributed to a POI only when
   the executed snapshot has the bound hash; names alone never match. Missing or contradictory
   evidence stays visible as UNKNOWN and is never filled with a favourable value.

Points of interest are operator-declared scenario inputs, not detections: the drones only navigate
over them, with no imagery or crop analysis. Offsets are relative to each vehicle's own launch
position. Records are historical SITL evidence; current availability is not checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from models.mission_definition import MissionDefinition
from tools import hermes_mission_planning as planning
from tools.hermes_mission_validation import validate_mission
from tools.preflight_sequences import digest, get_preflight_sequence
from tools.simulated_vehicle import resolve_mission_vehicle
from tools.simulation_mission_executor import _execution_compatibility_errors
from tools.simulation_mission_mapper import _calculate_local_offset_metres
from tools.vehicle_execution_lock import PROJECT_ROOT, safe_executor_exit
from tools.virtual_preflight_jobs import read_mission_input

SCENARIO_ID = "agri_demo_001"
# H0 is the comparison geometry, pinned by exact content; its waypoint IDs are the POI names.
REFERENCE = {
    "drone_01": {"sector": "A", "path": PROJECT_ROOT / "missions/examples/agri_demo_001_sector_a.json",
                 "sha256": "82ce067c7c83f1b50517e87f904aeb19cfcfadcc6a1063726cfe955367fbe156"},
    "drone_02": {"sector": "B", "path": PROJECT_ROOT / "missions/examples/agri_demo_001_sector_b.json",
                 "sha256": "722c66b9c9e8c0d2e862beceda9c196e7c1b8354ff9576e85632d93997c584af"},
}
OFFSET_TOLERANCE_M = 0.01
GROUND_TASK = {
    "task_id": "R1", "vehicle_id": "rover_01", "target_point": "POI_A1",
    "description": "Ground verification at a declared point of interest",
    "depends_on": "Sequence COMPLETED and POI_A1 REACHED by drone_01",
}
# The ground task cannot leave BLOCKED_PENDING: no rover mission path exists in this repository.
ROVER_BARRIERS = [
    "Rover identity chain (XRCE client to SITL instance/SYSID and bridge/model) not established",
    "No public rover entry point with authorization and reservations",
    "No navigation to a position: rover control offers bounded velocity/turn only",
    "Execution gate covers the two_drones profile only",
]
SCOPE = {"record": "historical", "environment": "SITL", "current_availability": "NOT_CHECKED",
         "operational_authorization": False,
         "points_of_interest": "operator-declared scenario inputs, not detections; no imagery captured",
         "coordinates": "offsets relative to each vehicle's own launch position"}

MISSION_BY_RESULT = {"PASSED": "COMPLETED", "FAILED": "FAILED", "BLOCKED": "BLOCKED"}


class ScenarioBindingError(ValueError):
    pass


def _load(path) -> tuple[bytes, MissionDefinition]:
    content = read_mission_input(path)  # the same regular-file reader the sequence admission uses
    return content, MissionDefinition.model_validate_json(content)


def _geometry(mission: MissionDefinition, waypoint_ids: list[str]) -> list[tuple[float, float, float]]:
    """North/east offsets from the mission home and altitude, as the executor maps them."""
    by_id = {wp.waypoint_id: wp for wp in mission.route.waypoints}
    return [(*_calculate_local_offset_metres(mission.route.home, by_id[i].latitude, by_id[i].longitude),
             by_id[i].altitude_m) for i in waypoint_ids]


def reference(vehicle_id: str) -> tuple[list[str], MissionDefinition]:
    """Declared POIs (in order) and the H0 mission; a changed reference is refused."""
    entry = REFERENCE[vehicle_id]
    content, mission = _load(entry["path"])
    if digest(content) != entry["sha256"]:
        raise ScenarioBindingError(f"H0 reference for {vehicle_id} changed; comparison geometry refused")
    return [wp.waypoint_id for wp in mission.route.waypoints], mission


def bind_mission(vehicle_id: str, mission_path: str, waypoint_by_point: dict[str, str]) -> dict:
    if vehicle_id not in REFERENCE:
        raise ScenarioBindingError(f"{vehicle_id} has no mission in the declared scenario")
    points, ref = reference(vehicle_id)
    content, mission = _load(mission_path)
    errors = []
    if resolve_mission_vehicle(mission).vehicle_id != vehicle_id:
        errors.append(f"Mission vehicle {mission.vehicle.vehicle_id} is not {vehicle_id}")
    if sorted(waypoint_by_point) != sorted(points):
        errors.append(f"Association must cover exactly {points}")
    elif [wp.waypoint_id for wp in mission.route.waypoints] != [waypoint_by_point[p] for p in points]:
        errors.append("Mission waypoints must be exactly the associated waypoints, in POI order")
    elif mission.route.home is None:
        errors.append("Mission home is required to compare offsets")
    else:
        actual = _geometry(mission, [waypoint_by_point[p] for p in points])
        for point, (north, east, altitude), (ref_n, ref_e, ref_alt) in zip(points, actual, _geometry(ref, points)):
            if (math.hypot(north - ref_n, east - ref_e) > OFFSET_TOLERANCE_M
                    or not math.isclose(altitude, ref_alt, abs_tol=1e-6)):
                errors.append(f"{point}: geometry differs from the H0 reference")
    if mission.route.return_to_home is not ref.route.return_to_home:
        errors.append("return_to_home differs from the H0 reference")
    # Same deterministic checks as the sequence coordinator's prevalidation.
    validation = validate_mission(mission)
    compatibility = _execution_compatibility_errors(mission)
    if validation.get("execution_status") != "APPROVED" or validation.get("errors"):
        errors.append(f"Deterministic validation is {validation.get('mission_status')}/"
                      f"{validation.get('execution_status')}")
    errors.extend(compatibility)
    if errors:
        raise ScenarioBindingError(f"{vehicle_id}: " + "; ".join(errors))
    return {"vehicle_id": vehicle_id, "sector": REFERENCE[vehicle_id]["sector"], "mission_id": mission.mission_id,
            "mission_sha256": digest(content), "waypoint_by_point": {p: waypoint_by_point[p] for p in points},
            "validation": {k: validation.get(k) for k in ("mission_status", "execution_status")},
            "authorization": "NOT_GRANTED"}


def bind_scenario(associations: dict[str, dict]) -> dict[str, dict]:
    """associations: {vehicle_id: {"mission_path": ..., "waypoint_by_point": {POI: waypoint_id}}}."""
    if sorted(associations) != sorted(REFERENCE):
        raise ScenarioBindingError(f"Provide exactly one mission for each of {sorted(REFERENCE)}")
    return {vehicle: bind_mission(vehicle, **association) for vehicle, association in associations.items()}


def reference_associations() -> dict[str, dict]:
    """H0 itself, for an executor/sequence test of the reference files."""
    return {vehicle: {"mission_path": str(entry["path"]),
                      "waypoint_by_point": {p: p for p in reference(vehicle)[0]}}
            for vehicle, entry in REFERENCE.items()}


def _mission(child: dict, binding: dict) -> dict:
    selection = child.get("vehicle_selection") or {}
    bound = binding.get(selection.get("vehicle_id"))
    entry = {"vehicle_id": selection.get("vehicle_id"), "simulated_vehicle": selection.get("simulated_vehicle"),
             "run_id": child.get("run_id"), "sequence_state": child.get("state"),
             "result_status": child.get("result_status"), "status": "UNKNOWN", "reasons": []}
    if bound is None:
        entry["reasons"].append("Child vehicle is not part of the declared scenario")
        return entry
    entry.update(mission_id=bound["mission_id"], sector=bound["sector"], mission_sha256=child.get("mission_sha256"))
    if child.get("mission_sha256") != bound["mission_sha256"]:
        entry["reasons"].append("Executed snapshot is not the bound scenario artifact (SHA-256 differs)")
        return entry
    report = (child.get("detail") or {}).get("report")
    state, result = child.get("state"), child.get("result_status")
    if state == "NOT_STARTED":
        if report is not None:
            entry["reasons"].append("NOT_STARTED child has a report; contradiction")
        else:
            entry["status"] = "NOT_EXECUTED"
        return entry
    if state != "FINISHED":
        entry["reasons"].append(f"Child outcome not confirmed (state {state})")
        return entry
    if result not in MISSION_BY_RESULT:
        entry["reasons"].append(f"Child result {result} does not establish the outcome")
        return entry
    if not isinstance(report, dict) or report.get("status") != result:
        entry["reasons"].append("Child report is missing or disagrees with the accepted result")
        return entry
    if report.get("mission_sha256") != bound["mission_sha256"]:
        entry["reasons"].append("Child report belongs to another mission snapshot")
        return entry
    entry["status"] = MISSION_BY_RESULT[result]
    entry["reasons"] = list(report.get("reasons") or [])
    entry["report"] = report
    return entry


def _outcomes(entry: dict, bound: dict | None) -> tuple[dict, str, str]:
    """Per point, return and landing; credited only from the verified analysis of that child.

    The existing analysis credits waypoints only as a complete, consistent set
    (all_waypoints_reached, position_evidence_consistent). It has no per-waypoint verdict, so a
    point reached before a later failure stays NOT_CONFIRMED.
    """
    status, report = entry["status"], entry.pop("report", None)
    association = (bound or {}).get("waypoint_by_point", {})
    points = list(association)
    if status in {"NOT_EXECUTED", "BLOCKED"}:
        return dict.fromkeys(points, "NOT_EXECUTED"), "NOT_EXECUTED", "NOT_EXECUTED"
    if status == "UNKNOWN":
        return dict.fromkeys(points, "UNKNOWN"), "UNKNOWN", "UNKNOWN"
    analysis = report.get("analysis") or {}
    checks = analysis.get("checks") or {}
    if analysis.get("expected_waypoint_ids") != list(association.values()):
        entry["reasons"].append("Analysed waypoints differ from the bound association")
        entry["status"] = "UNKNOWN"
        return dict.fromkeys(points, "UNKNOWN"), "UNKNOWN", "UNKNOWN"
    credited = (checks.get("all_waypoints_reached") is True and checks.get("position_evidence_consistent") is True)
    observed = analysis.get("observed_waypoint_ids") or []
    reached = {p: "REACHED" if credited and w in observed else "NOT_CONFIRMED" for p, w in association.items()}
    home = "CONFIRMED" if checks.get("return_home_reached") is True and credited else "NOT_CONFIRMED"
    raw = report.get("executor_result")
    selection = {"vehicle_id": entry["vehicle_id"], "simulated_vehicle": entry["simulated_vehicle"]}
    if not safe_executor_exit(raw, selection=selection):
        landing = "NOT_CONFIRMED"
    elif status == "COMPLETED" and checks.get("landed_and_disarmed") is True:
        landing = "MISSION_LANDING_CONFIRMED"
    elif status == "FAILED" and (raw or {}).get("recovery"):
        landing = "RECOVERY_LANDING_CONFIRMED"  # never turns the failure into success
    else:
        landing = "NOT_CONFIRMED"
    return reached, home, landing


def summarize_scenario(sequence: dict, binding: dict[str, dict]) -> dict:
    """Interpret one sequence view against a ``bind_scenario`` result. Pure: no reads or writes."""
    reasons, missions, points = [], [], {}
    state, result = sequence.get("job_state"), sequence.get("result_status")
    children = sequence.get("children")
    if state in {"ERROR", "NOT_FOUND"} or not isinstance(children, list):
        reasons.extend(sequence.get("errors") or [f"Sequence lookup returned {state}"])
        children = []
    for child in children:
        entry = _mission(child, binding)
        reached, home, landing = _outcomes(entry, binding.get(entry["vehicle_id"]))
        entry.update(points=reached, return_home=home, landing=landing)
        points.update({p: {"vehicle_id": entry["vehicle_id"], "status": s} for p, s in reached.items()})
        missions.append(entry)
    seen = sorted(m["vehicle_id"] for m in missions if m["vehicle_id"])
    if children and seen != sorted(binding):
        reasons.append("Sequence does not contain exactly the bound drone missions")
    for vehicle, bound in binding.items():
        for point in bound["waypoint_by_point"]:
            points.setdefault(point, {"vehicle_id": vehicle, "status": "UNKNOWN"})
    statuses = {m["status"] for m in missions}
    if not missions or reasons or "UNKNOWN" in statuses or state != "FINISHED":
        aerial = "UNKNOWN"
        if state not in {"FINISHED", "ERROR", "NOT_FOUND"}:
            reasons.append(f"Sequence not finished or unconfirmed (job_state {state})")
    elif "FAILED" in statuses:
        aerial = "FAILED"
    elif "BLOCKED" in statuses:
        aerial = "BLOCKED"
    elif statuses == {"NOT_EXECUTED"}:
        aerial = "NOT_EXECUTED"
    elif statuses == {"COMPLETED"}:
        aerial = "COMPLETED"
    else:
        aerial = "UNKNOWN"
        reasons.append(f"Unexpected mission combination {sorted(statuses)}")
    expected_result = {"COMPLETED": "PASSED", "FAILED": "FAILED", "BLOCKED": "BLOCKED"}.get(aerial)
    if expected_result and result != expected_result:
        reasons.append(f"Sequence result {result} contradicts mission outcomes")
        aerial = "UNKNOWN"
    target = points.get(GROUND_TASK["target_point"], {}).get("status")
    dependency = ("MET" if aerial == "COMPLETED" and target == "REACHED"
                  else "UNKNOWN" if aerial == "UNKNOWN" else "NOT_MET")
    ground = {**GROUND_TASK, "status": "BLOCKED_PENDING", "dependency": dependency,
              "barriers": list(ROVER_BARRIERS), "commands_sent": False}
    status = {"COMPLETED": "AERIAL_COMPLETED_GROUND_PENDING"}.get(aerial, aerial)
    return {"scenario_id": SCENARIO_ID, "status": status, "scenario_complete": False,
            "sequence": {"sequence_id": sequence.get("sequence_id"), "job_state": state, "result_status": result,
                         "reasons": list(sequence.get("reasons") or [])},
            "binding": {v: {k: b[k] for k in ("mission_id", "mission_sha256", "waypoint_by_point")}
                        for v, b in binding.items()},
            "missions": missions, "points": points, "ground_task": ground, "reasons": reasons, "scope": dict(SCOPE)}


FINALIZE_TOOL = "mcp__tfg_mission_control__finalize_mission_draft"  # Hermes registry name


def finalized_artifacts(session: dict) -> tuple[dict[str, dict], list[str]]:
    """Associations for ``bind_scenario`` from the REAL finalize results of the session's last turn.

    The model's text is not used. Each VALIDATED result must name a mission.json under the drafts
    root whose bytes still have the returned hash. Exactly one per drone, or nothing is proposed.
    The POI -> waypoint association follows the POI order of the H1 request; bind_scenario then
    verifies it against the H0 geometry, so a wrong order is refused, not trusted.
    """
    from observability.mission_report_acceptance import _result_document
    from tools.mission_report_query import turn_from_session
    calls, _, reasons = turn_from_session(session)
    reasons, found = list(reasons), {}
    for call in calls:
        if call["tool_name"] != FINALIZE_TOOL:
            continue
        # Hermes delivers MCP output as {"result": "<tool JSON>"} (2026-10-24 H1 session); same unwrapping
        # as the report acceptance. An unreadable result is never treated as an artifact.
        result = _result_document(call["result"])
        if result is None:
            reasons.append("FINALIZE_RESULT_UNREADABLE")
            continue
        if not isinstance(result, dict) or result.get("status") != "VALIDATED":
            continue  # pending fields or an error: not an artifact
        try:
            path = Path(str(result.get("mission_path"))).resolve(strict=True)
        except OSError:
            reasons.append("FINALIZED_MISSION_MISSING")
            continue
        if not path.is_relative_to(planning.DRAFT_ROOT.resolve()) or path.name != "mission.json":
            reasons.append("FINALIZED_PATH_OUTSIDE_DRAFTS")
            continue
        content, mission = _load(path)
        if digest(content) != result.get("mission_sha256"):
            reasons.append("FINALIZED_MISSION_CHANGED")
            continue
        found.setdefault(mission.vehicle.vehicle_id, []).append((path, mission))
    associations = {}
    for vehicle in sorted(set(found) | set(REFERENCE)):
        items = found.get(vehicle, [])
        if vehicle not in REFERENCE:
            reasons.append(f"FINALIZATION_FOR_UNDECLARED_VEHICLE {vehicle}")
        elif len(items) != 1:
            reasons.append(f"{vehicle}: {len(items)} validated finalizations; exactly one required")
        else:
            path, mission = items[0]
            associations[vehicle] = {"mission_path": str(path), "waypoint_by_point": dict(zip(
                reference(vehicle)[0], [wp.waypoint_id for wp in mission.route.waypoints]))}
    return associations, reasons


def bind_planning_session(session: dict) -> dict:
    """BOUND only when the session's own finalized artifacts pass bind_scenario. Never authorizes a
    flight and never falls back to H0: a refused artifact stays refused."""
    associations, reasons = finalized_artifacts(session)
    result = {"status": "NOT_BOUND", "reasons": reasons, "associations": associations, "binding": None,
              "association_basis": "POI order of the H1 request; geometry verified against H0",
              "flight_authorization": "NOT_GRANTED", "fallback_to_h0": False}
    if not reasons:
        try:
            result.update(status="BOUND", binding=bind_scenario(associations))
        except ScenarioBindingError as exc:
            result["reasons"] = [str(exc)]
    return result


def bind_planning_turn(usage_file: Path, *, hermes_bin: Path | None = None, runner=subprocess.run) -> dict:
    """The H1 turn of ``usage_file``, exported with Hermes' local CLI and processed in memory."""
    from tools.mission_report_query import DEFAULT_HERMES_BIN, QueryError, export_session, session_id_from_usage
    try:
        session = export_session(session_id_from_usage(usage_file), hermes_bin=hermes_bin or DEFAULT_HERMES_BIN,
                                 runner=runner)
    except (QueryError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"status": "NOT_BOUND", "reasons": ["TURN_DATA_UNAVAILABLE"], "detail": type(exc).__name__,
                "binding": None, "flight_authorization": "NOT_GRANTED", "fallback_to_h0": False}
    return bind_planning_session(session)


# --- Deterministic scenario view (schema 1): one read-only, provider-safe answer to "what does the
# historical record of this scenario establish?". It reuses the binding, the verified sequence query and
# summarize_scenario; it adds nothing that is not in those records and certifies nothing current.
VIEW_SCHEMA = "tfg.agri-scenario-view/1"
SCENARIOS = {SCENARIO_ID: {"binding_record": "evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json"}}
COMMANDS = ("guided", "arm", "takeoff", "return_home", "land")
LIMITATIONS = {
    "perception": "NONE: points of interest are operator-declared scenario inputs; no imagery, detection or crop analysis",
    "speed": {"planning_estimate": "waypoint speed_kmh, or cruise_speed_kmh when null, used only to estimate time/battery",
              "commanded": False, "measured": False,
              "note": "position-only targets (type_mask 3576); actual speed is ArduPilot's configuration"},
    "common_frame": {"validated": False,
                     "note": "each mission is offset from its own vehicle's launch position; launch geoposes are float32"},
    "telemetry_source": "executor observations via AP_DDS, not independent telemetry",
    "simultaneous_flight": False,
}


def _command_times(raw):
    """First start time of each executor command, only from a complete operation record."""
    diagnostics = (raw or {}).get("operation_diagnostics") if isinstance(raw, dict) else None
    if not isinstance(diagnostics, dict) or diagnostics.get("omitted_operations") != 0:
        return dict.fromkeys(COMMANDS), "UNAVAILABLE_OR_TRUNCATED"
    operations = [o for o in (diagnostics.get("initial") or []) + (diagnostics.get("recent") or []) if isinstance(o, dict)]
    if len(operations) != diagnostics.get("total_operations"):
        return dict.fromkeys(COMMANDS), "INCONSISTENT_OPERATION_COUNT"
    return {name: next((o.get("started_at_utc") for o in operations if o.get("operation") == name), None)
            for name in COMMANDS}, "COMPLETE_OPERATION_RECORD"


def _errors_m(report):
    events = ((report.get("executor_result") or {}).get("events") or []) if isinstance(report, dict) else []
    return {(e.get("waypoint_id") or e["event"]): {"horizontal": e.get("horizontal_error_m"), "altitude": e.get("altitude_error_m")}
            for e in events if isinstance(e, dict)
            and e.get("event") in ("TAKEOFF_REACHED", "WAYPOINT_REACHED", "RETURN_HOME_REACHED")}


def _order(runs, sequence):
    """Execution order accredited only by execution evidence, never by admission times."""
    times = [(r["timeline"]["executor_started_at"], r["timeline"]["executor_finished_at"],
              r["timeline"]["commands_started_at"]["arm"], r["timeline"]["commands_started_at"]["land"],
              r["timeline"]["coordinator_dispatched_at"], r["timeline"]["coordinator_accepted_result_at"]) for r in runs]
    basis = {"rule": "tools/preflight_sequence_worker.run_coordinator dispatches child 2 only after verifying child 1's "
                     "final PASSED report", "admission_times_are_order_evidence": False}
    if len(runs) != 2 or any(value is None for row in times for value in row[:2] + row[4:]):
        return {"status": "NOT_ACCREDITED", "reason": "missing execution or coordinator timestamps", **basis}
    first, second = times
    checks = {"executor_windows_disjoint": first[1] < second[0],
              "coordinator_dispatch_after_first_result": first[5] < second[4],
              "first_land_command_before_second_arm_command": (first[3] < second[2]) if first[3] and second[2] else None}
    if sequence.get("result_status") is None or any(v is False for v in checks.values()):
        return {"status": "NOT_ACCREDITED", "reason": "timestamps do not establish sequential execution",
                "checks": checks, **basis}
    return {"status": "ACCREDITED_BY_EXECUTION_TIMESTAMPS", "vehicle_order": [r["vehicle_id"] for r in runs],
            "checks": checks, **basis}


def scenario_view(sequence: dict, binding: dict | None, *, binding_record: dict, refused: str | None = None) -> dict:
    """Pure: the provider-safe historical view. No paths, request keys, process identities or free text."""
    scope = {"record": "historical", "as_of": sequence.get("finished_at"), "current_availability": "NOT_CHECKED",
             "current_restrictions": "NOT_CHECKED", "operational_authorization": False, "hardware_authorized": False,
             "note": "describes a finished historical record; it is not a current safety or permission query"}
    base = {"view": "scenario", "view_schema": VIEW_SCHEMA, "scenario_id": SCENARIO_ID, "scope": scope,
            "limitations": LIMITATIONS, "sources": {"binding_record": binding_record}}
    if refused is not None:
        return {**base, "status": "REJECTED", "reasons": ["SCENARIO_BINDING_REFUSED"], "scenario": None}
    if sequence.get("job_state") in {"ERROR", "NOT_FOUND"} or not isinstance(sequence.get("children"), list):
        return {**base, "status": "UNKNOWN", "reasons": [f"SEQUENCE_{sequence.get('job_state') or 'UNREADABLE'}"],
                "errors_omitted": len(sequence.get("errors") or []), "scenario": None}
    summary = summarize_scenario(sequence, binding)
    missions = {m["run_id"]: m for m in summary["missions"]}
    runs = []
    for index, child in enumerate(sequence["children"], 1):
        report = (child.get("detail") or {}).get("report")
        report = report if isinstance(report, dict) else {}
        commands, command_basis = _command_times(report.get("executor_result"))
        mission = missions.get(child.get("run_id"), {})
        runs.append({
            "index": index, "run_id": child.get("run_id"), "vehicle_id": mission.get("vehicle_id"),
            "simulated_vehicle": mission.get("simulated_vehicle"), "mission_id": mission.get("mission_id"),
            "mission_sha256": child.get("mission_sha256"), "report_sha256": child.get("report_sha256"),
            "status": mission.get("status", "UNKNOWN"), "result_status": child.get("result_status"),
            "points": mission.get("points"), "return_home": mission.get("return_home"), "landing": mission.get("landing"),
            "position_errors_m": _errors_m(report) if mission.get("status") != "UNKNOWN" else None,
            "timeline": {
                "job_admitted_at": report.get("started_at"),  # admission of the job, NOT a take-off time
                "coordinator_dispatched_at": child.get("started_at"),
                "executor_started_at": report.get("execution_started_at"),
                "commands_started_at": commands, "commands_basis": command_basis,
                "executor_finished_at": report.get("execution_finished_at"),
                "coordinator_accepted_result_at": child.get("finished_at"),
                "time_basis": "host wall clock (UTC) of the project processes; not simulated time"},
            "reasons": mission.get("reasons", []),
        })
    plan = sequence.get("plan") or {}
    authorization = plan.get("authorization") or {}
    statement = authorization.get("statement")
    tolerance = {"horizontal_m": 1.0, "altitude_m": 0.75}
    return {**base, "status": "OK" if summary["status"] != "UNKNOWN" else "UNKNOWN", "reasons": summary["reasons"],
            "scenario": {
                "status": summary["status"], "scenario_complete": summary["scenario_complete"],
                "sequence": {"sequence_id": sequence.get("sequence_id"), "job_state": sequence.get("job_state"),
                             "result_status": sequence.get("result_status"), "plan_sha256": sequence.get("plan_sha256"),
                             "created_at": sequence.get("created_at"), "finished_at": sequence.get("finished_at")},
                "authorization_recorded": {
                    "source": authorization.get("source"), "scope": authorization.get("scope"),
                    "statement_sha256": hashlib.sha256(statement.encode()).hexdigest() if isinstance(statement, str) else None,
                    "authenticated": False,
                    "meaning": "operator declaration passed as text and recorded for these two snapshots only"},
                "order": _order(runs, sequence) if summary["status"] != "UNKNOWN" else
                         {"status": "NOT_ACCREDITED", "reason": "scenario status UNKNOWN", "admission_times_are_order_evidence": False},
                "runs": runs, "points": summary["points"], "tolerances": tolerance,
                "ground_task": {**summary["ground_task"], "movement_authorized": False,
                                "dependency_meaning": "MET only states that the declared precondition holds in this "
                                                      "record; it never authorizes rover movement"}}}


def get_scenario_view(scenario_id: str, *, request_key: str | None = None, sequence_id: str | None = None) -> dict:
    """Read-only historical scenario view for the MCP query tool. Never writes, starts or authorizes anything."""
    if scenario_id not in SCENARIOS:
        return {"view": "scenario", "view_schema": VIEW_SCHEMA, "status": "INVALID_ARGUMENTS",
                "reasons": ["UNKNOWN_SCENARIO"], "lookup_performed": False}
    if (request_key is None) == (sequence_id is None):
        return {"view": "scenario", "view_schema": VIEW_SCHEMA, "status": "INVALID_ARGUMENTS",
                "reasons": ["SUPPLY_EXACTLY_ONE_OF_REQUEST_KEY_OR_SEQUENCE_ID"], "lookup_performed": False}
    configured = SCENARIOS[scenario_id]["binding_record"]
    path = PROJECT_ROOT / configured
    # Only a repository-relative reference is published; an absolute path never reaches the provider.
    record = {"path": None if Path(configured).is_absolute() else configured, "sha256": None}
    try:
        record["sha256"] = digest(path.read_bytes())
        binding = _bind_expected(*record_associations(path))
    except (ScenarioBindingError, ValueError, OSError, KeyError, TypeError) as exc:
        return scenario_view({}, None, binding_record=record, refused=type(exc).__name__)
    sequence = (get_preflight_sequence(request_key=request_key, detail=True) if request_key is not None
                else get_preflight_sequence(sequence_id=sequence_id, detail=True))
    return scenario_view(sequence, binding, binding_record=record)


QUERY_TOOL = "mcp__tfg_mission_control__get_mission_state"
H3_RUN_KEYS = ("run_id", "vehicle_id", "simulated_vehicle", "mission_id", "result_status", "reached_waypoint_ids",
               "return_to_home", "mission_landed")


def _expected_run(document: dict) -> dict:
    """The per-run facts an H3 answer must restate, from ONE real external-view result."""
    run = ((document or {}).get("preflights") or [{}])[0]
    identity, facts = run.get("identity") or {}, run.get("executor_facts") or {}
    landing = facts.get("mission_landing_events")
    return {"run_id": identity.get("run_id"), "vehicle_id": identity.get("vehicle_id"),
            "simulated_vehicle": identity.get("simulated_vehicle"), "mission_id": identity.get("mission_id"),
            "result_status": (run.get("record") or {}).get("result_status"),
            "reached_waypoint_ids": facts.get("reached_waypoint_ids"), "return_to_home": facts.get("return_to_home"),
            "mission_landed": (any(e.get("landed") is True for e in landing) if isinstance(landing, list) else None)}


def accept_h3_session(session: dict, scenario_summary: dict, run_ids) -> dict:
    """VALIDATED only if the turn made exactly the intended external-view calls and every key of the
    answer equals the session's REAL results (per run) or the saved deterministic summary (scenario).
    Per-key outcomes only; the free-text explanation is reported, never accepted as evidence."""
    from observability.mission_query_cases import parse_answer
    from observability.mission_report_acceptance import _result_document
    from tools.mission_report_query import turn_from_session
    calls, answer_text, reasons = turn_from_session(session)
    reasons = list(reasons)
    queried = [c for c in calls if c["tool_name"] == QUERY_TOOL]
    if len(calls) != len(queried):
        reasons.append("OTHER_TOOL_CALLED")
    args = sorted(((c["args"] or {}).get("run_id"), (c["args"] or {}).get("view")) for c in queried)
    if args != sorted((r, "external") for r in run_ids):
        reasons.append("CALLS_NOT_EXACTLY_THE_INTENDED_EXTERNAL_QUERIES")
    expected_runs = {}
    for call in queried:
        document = _result_document(call["result"])
        if not isinstance(document, dict) or document.get("view") != "external":
            reasons.append("TOOL_RESULT_UNREADABLE")
            continue
        expected = _expected_run(document)
        expected_runs[expected["run_id"]] = expected
    answer, parse_status = parse_answer(answer_text)
    outcomes = {"parse": parse_status}
    if answer is None:
        reasons.append("ANSWER_NOT_PARSEABLE")
    else:
        ground = scenario_summary["ground_task"]
        association = {m["vehicle_id"]: (scenario_summary.get("binding") or {}).get(m["vehicle_id"], {}).get(
            "waypoint_by_point", {}) for m in scenario_summary["missions"]}
        order = [m["vehicle_id"] for m in scenario_summary["missions"]]
        reached = [p for v in order for p, w in association[v].items()
                   if w in (next((e for e in expected_runs.values() if e["vehicle_id"] == v), {})
                            .get("reached_waypoint_ids") or [])]
        scenario_expected = {
            "sequence_order": order, "reached_points": reached,
            "scenario_complete": scenario_summary["scenario_complete"], "r1_status": ground["status"],
            "r1_dependency": ground["dependency"], "r1_commands_sent": ground["commands_sent"],
            # A satisfied dependency never authorizes rover movement while it is BLOCKED_PENDING.
            "r1_movement_authorized": False}
        for key, value in scenario_expected.items():
            given = answer.get(key, "<absent>")
            same = sorted(given) == sorted(value) if key == "reached_points" and isinstance(given, list) else given == value
            outcomes[key] = "match" if same else ("absent" if given == "<absent>" else "mismatch")
        runs = answer.get("runs") if isinstance(answer.get("runs"), list) else []
        given_runs = {r.get("run_id"): r for r in runs if isinstance(r, dict)}
        for run_id, expected in expected_runs.items():
            given = given_runs.get(run_id)
            for key in H3_RUN_KEYS:
                outcomes[f"runs[{run_id[:8]}].{key}"] = ("absent" if given is None or key not in given
                                                        else "match" if given[key] == expected[key] else "mismatch")
        if len(runs) != len(run_ids):
            outcomes["runs.count"] = "mismatch"
        for key in ("evidence_source", "explanation"):
            outcomes[key] = "present" if isinstance(answer.get(key), str) and answer[key].strip() else "absent"
        failed = sorted(k for k, v in outcomes.items() if v in ("mismatch", "absent"))
        if failed:
            reasons.append("ANSWER_KEYS_NOT_AS_EVIDENCE: " + ", ".join(failed))
    return {"status": "VALIDATED" if not reasons else "NOT_VALIDATED", "reasons": reasons,
            "observed_tool_calls": len(calls), "answer_outcomes": outcomes,
            "answer": answer, "expected_from_session": expected_runs,
            "scope": {"record": "historical H2 run", "current_availability": "NOT_CHECKED",
                      "operational_authorization": False,
                      "explanation": "free text reported for review; not validated automatically"}}


def accept_h3_turn(usage_file: Path, summary_path: Path, run_ids, *, hermes_bin: Path | None = None,
                   runner=subprocess.run) -> dict:
    from tools.mission_report_query import DEFAULT_HERMES_BIN, QueryError, export_session, session_id_from_usage
    try:
        session = export_session(session_id_from_usage(usage_file), hermes_bin=hermes_bin or DEFAULT_HERMES_BIN,
                                 runner=runner)
    except (QueryError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"status": "NOT_VALIDATED", "reasons": ["TURN_DATA_UNAVAILABLE"], "detail": type(exc).__name__}
    return accept_h3_session(session, json.loads(Path(summary_path).read_text(encoding="utf-8")), run_ids)


# --- Deterministic readable report of a scenario view -------------------------------------------------
# Every sentence restates a field of the view and cites it. Commands are listed by their recorded time,
# observed temporal order is kept apart from the coordinator's documented rule, and the report never
# narrates causes, repetitions or events the view does not record. Missing values read "desconocido".
UNKNOWN_ES = "desconocido"
COMMAND_ES = {"guided": "modo GUIDED", "arm": "armado", "takeoff": "despegue", "return_home": "regreso al lanzamiento",
              "land": "aterrizaje"}
CHECK_ES = {
    "executor_windows_disjoint": ("fin del ejecutor del hijo 1", "executor_finished_at", 0,
                                  "inicio del ejecutor del hijo 2", "executor_started_at", 1),
    "coordinator_dispatch_after_first_result": ("aceptación del resultado del hijo 1", "coordinator_accepted_result_at", 0,
                                                "despacho del hijo 2", "coordinator_dispatched_at", 1),
    "first_land_command_before_second_arm_command": ("orden de aterrizaje del hijo 1", "commands_started_at.land", 0,
                                                     "orden de armado del hijo 2", "commands_started_at.arm", 1),
}
DEPENDENCY_CONDITIONS = (("secuencia aérea completada", "scenario.status == AERIAL_COMPLETED_GROUND_PENDING"),
                         ("POI_A1 alcanzado por drone_01", "scenario.points.POI_A1.status == REACHED"))


def _v(value):
    return UNKNOWN_ES if value is None else str(value)


def _timeline_value(timeline, dotted):
    value = timeline
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def render_scenario_report(view: dict) -> str:
    """Pure: Markdown report of one scenario view. Deterministic for the same view (no current time)."""
    scope, limitations = view.get("scope") or {}, view.get("limitations") or {}
    source = (view.get("sources") or {}).get("binding_record") or {}
    lines = [f"# Informe determinista del escenario {view.get('scenario_id')}", "",
             f"Generado por código a partir de la vista `{view.get('view_schema')}`; no lo redacta un modelo. "
             "Cada hecho cita su campo de la vista entre corchetes.", "",
             f"- Estado de la vista: **{_v(view.get('status'))}** [status]."]
    scenario = view.get("scenario")
    if not isinstance(scenario, dict):
        lines += [f"- Motivos: {', '.join(view.get('reasons') or []) or UNKNOWN_ES} [reasons].",
                  "- Sin escenario legible: no se informa de ejecuciones, orden, POI ni R1 [scenario = null].", ""]
    else:
        sequence = scenario.get("sequence") or {}
        lines += [
            f"- Escenario: **{_v(scenario.get('status'))}**; completo: **{'sí' if scenario.get('scenario_complete') else 'no'}** "
            "[scenario.status, scenario.scenario_complete].",
            f"- Registro histórico de la secuencia `{_v(sequence.get('sequence_id'))}`: {_v(sequence.get('job_state'))} / "
            f"{_v(sequence.get('result_status'))}, creada {_v(sequence.get('created_at'))}, terminada "
            f"{_v(sequence.get('finished_at'))} [scenario.sequence].", "",
            "## Resultado de cada ejecución", ""]
        runs = scenario.get("runs") or []
        for run in runs:
            timeline = run.get("timeline") or {}
            prefix = f"scenario.runs[{run.get('index', 0) - 1}]"
            points = run.get("points") or {}
            lines += [
                f"### Hijo {_v(run.get('index'))}: {_v(run.get('vehicle_id'))} → {_v(run.get('simulated_vehicle'))}", "",
                f"- Misión `{_v(run.get('mission_id'))}` (snapshot `{_v(run.get('mission_sha256'))}`), informe "
                f"`{_v(run.get('report_sha256'))}` [{prefix}.mission_id, mission_sha256, report_sha256].",
                f"- Estado: **{_v(run.get('status'))}**; resultado: {_v(run.get('result_status'))} "
                f"[{prefix}.status, result_status].",
                "- Puntos de interés: " + (", ".join(f"{p} {_v(s)}" for p, s in points.items()) or UNKNOWN_ES)
                + f" [{prefix}.points].",
                f"- Regreso: {_v(run.get('return_home'))}; aterrizaje: {_v(run.get('landing'))} "
                f"[{prefix}.return_home, landing].",
                f"- Cronología registrada (reloj de pared UTC) [{prefix}.timeline]:",
                f"  - admisión del trabajo: {_v(timeline.get('job_admitted_at'))} (no es evidencia de orden ni un despegue);",
                f"  - despacho del coordinador: {_v(timeline.get('coordinator_dispatched_at'))};",
                f"  - inicio del ejecutor: {_v(timeline.get('executor_started_at'))};"]
            commands = timeline.get("commands_started_at") or {}
            known = sorted((t, name) for name, t in commands.items() if t is not None)
            lines += [f"  - inicio de la orden de {COMMAND_ES.get(name, name)}: {t};" for t, name in known]
            lines += [f"  - inicio de la orden de {COMMAND_ES.get(name, name)}: {UNKNOWN_ES};"
                      for name, t in commands.items() if t is None]
            lines += [f"  - base de las órdenes: {_v(timeline.get('commands_basis'))};",
                      f"  - fin del ejecutor: {_v(timeline.get('executor_finished_at'))};",
                      f"  - aceptación del resultado por el coordinador: {_v(timeline.get('coordinator_accepted_result_at'))}.",
                      ""]
        order = scenario.get("order") or {}
        lines += ["## Orden", "",
                  f"- Estado: **{_v(order.get('status'))}** [scenario.order.status]. Las horas de admisión no se usan "
                  "como evidencia de orden [scenario.order.admission_times_are_order_evidence = false]."]
        if order.get("status") == "ACCREDITED_BY_EXECUTION_TIMESTAMPS":
            lines.append(f"- Orden observado: {' → '.join(order.get('vehicle_order') or [])} [scenario.order.vehicle_order].")
        else:
            lines.append(f"- Orden no acreditado: {_v(order.get('reason'))} [scenario.order.reason].")
        lines.append("- Comprobaciones temporales observadas [scenario.order.checks]:")
        for name, ok in (order.get("checks") or {}).items():
            first, first_key, i, second, second_key, j = CHECK_ES[name]
            t1 = _timeline_value((runs[i].get("timeline") if len(runs) > i else {}), first_key)
            t2 = _timeline_value((runs[j].get("timeline") if len(runs) > j else {}), second_key)
            verdict = {True: "se cumple", False: "NO se cumple", None: UNKNOWN_ES}[ok]
            lines.append(f"  - `{name}`: {first} ({_v(t1)}) anterior a {second} ({_v(t2)}): {verdict}.")
        lines += ["- Regla documentada del coordinador, distinta de la observación temporal: "
                  f"{_v(order.get('rule'))} [scenario.order.rule].", "",
                  "## Tarea terrestre R1", ""]
        ground = scenario.get("ground_task") or {}
        point_a1 = ((scenario.get("points") or {}).get("POI_A1") or {}).get("status")
        conditions = (scenario.get("status") == "AERIAL_COMPLETED_GROUND_PENDING", point_a1 == "REACHED")
        lines += [f"- {_v(ground.get('task_id'))}: {_v(ground.get('vehicle_id'))} hacia {_v(ground.get('target_point'))} "
                  f"[scenario.ground_task].",
                  "- Dependencia completa: requiere **las dos** condiciones [scenario.ground_task.depends_on]:"]
        for (label, field), met in zip(DEPENDENCY_CONDITIONS, conditions):
            lines.append(f"  - {label}: {'se cumple' if met else 'no consta'} [{field}].")
        lines += [f"- Dependencia: **{_v(ground.get('dependency'))}**; estado: **{_v(ground.get('status'))}**; "
                  f"órdenes enviadas: **{'sí' if ground.get('commands_sent') else 'no'}**; movimiento autorizado: "
                  f"**{'sí' if ground.get('movement_authorized') else 'no'}** [scenario.ground_task].",
                  f"- Significado: {_v(ground.get('dependency_meaning'))} [scenario.ground_task.dependency_meaning].",
                  "- Barreras registradas: " + ("; ".join(ground.get("barriers") or []) or UNKNOWN_ES)
                  + " [scenario.ground_task.barriers].", "",
                  "## Autorización registrada", "",
                  f"- {_v((scenario.get('authorization_recorded') or {}).get('source'))}, alcance "
                  f"«{_v((scenario.get('authorization_recorded') or {}).get('scope'))}», autenticada: no "
                  "[scenario.authorization_recorded].", ""]
    speed = limitations.get("speed") or {}
    frame = limitations.get("common_frame") or {}
    lines += ["## Alcance y limitaciones", "",
              f"- Registro {_v(scope.get('record'))} a fecha {_v(scope.get('as_of'))}; disponibilidad actual "
              f"{_v(scope.get('current_availability'))}; restricciones actuales {_v(scope.get('current_restrictions'))}; "
              f"autorización operativa: {'sí' if scope.get('operational_authorization') else 'no'} [scope].",
              f"- Percepción: {_v(limitations.get('perception'))} [limitations.perception].",
              f"- Velocidad: comandada {'sí' if speed.get('commanded') else 'no'}, medida "
              f"{'sí' if speed.get('measured') else 'no'}; {_v(speed.get('planning_estimate'))} [limitations.speed].",
              f"- Marco común entre vehículos validado: {'sí' if frame.get('validated') else 'no'} "
              "[limitations.common_frame].",
              f"- Vuelo simultáneo: {'sí' if limitations.get('simultaneous_flight') else 'no'} "
              "[limitations.simultaneous_flight].",
              f"- Fuente de los datos de vuelo: {_v(limitations.get('telemetry_source'))} [limitations.telemetry_source].",
              "", "## Fuentes", "",
              f"- Registro de vinculación `{_v(source.get('path'))}`, SHA-256 `{_v(source.get('sha256'))}` "
              "[sources.binding_record].",
              f"- Plan de la secuencia, SHA-256 `{_v(((view.get('scenario') or {}).get('sequence') or {}).get('plan_sha256'))}` "
              "[scenario.sequence.plan_sha256].",
              "- Informes y snapshots de cada ejecución: hashes citados en su apartado.", ""]
    return "\n".join(lines)


# --- H3b: acceptance of an answer built from the scenario view (accept_h3 above stays unchanged) --------
VIEW_TOOL = "mcp__tfg_mission_control__get_scenario_view"
# Errors in these keys reject the answer whatever the score: authorization, completion, order and
# invented capabilities are exactly what a reader could act on.
CRITICAL_KEYS = ("r1_movement_authorized", "r1_commands_sent", "scenario_complete", "sequence_order", "order_basis",
                 "claims.images_captured", "claims.detections_made", "claims.speed_commanded", "claims.speed_measured",
                 "claims.simultaneous_flight", "claims.common_frame_validated", "claims.current_permissions_checked")
H3B_RUN_KEYS = ("vehicle_id", "simulated_vehicle", "mission_id", "status", "result_status", "reached_points",
                "return_home", "landing", "executor_started_at", "executor_finished_at")
# Top-level keys named by the H3b prompt. Others are recorded as a classification, never silently scored.
H3B_ANSWER_KEYS = ("scenario_status", "scenario_complete", "sequence_order", "order_basis", "runs", "r1_status",
                   "r1_dependency", "r1_commands_sent", "r1_movement_authorized", "claims", "evidence_source",
                   "explanation")
# Heuristic only: a keyword hit is a reason for human review, never a semantic validation.
EXPLANATION_FLAGS = {
    "may_claim_rover_authorization": r"(?i)autoriz\w*\s+(a\s+)?mover|rover\s+(puede|est[aá]\s+autorizado)|movement\s+authori[sz]ed",
    "may_claim_imagery_or_detection": r"(?i)im[aá]gen(es)?\s+(capturad|tomad)|fotograf[ií]|detect(ó|aron|ado|ada)",
    "may_claim_measured_or_commanded_speed": r"(?i)velocidad\s+(medida|comandada|de\s+\d)|\d+\s*km/h",
    "may_use_admission_as_takeoff": r"(?i)(despeg\w*|take-?off)[^.]{0,60}12:51:18",
}


def _expected_from_view(view):
    scenario = view.get("scenario") or {}
    order, ground = scenario.get("order") or {}, scenario.get("ground_task") or {}
    expected = {
        "scenario_status": scenario.get("status") if view.get("status") == "OK" else view.get("status"),
        "scenario_complete": scenario.get("scenario_complete", False),
        "sequence_order": order.get("vehicle_order") if order.get("status") == "ACCREDITED_BY_EXECUTION_TIMESTAMPS" else None,
        "order_basis": "EXECUTION_TIMESTAMPS" if order.get("status") == "ACCREDITED_BY_EXECUTION_TIMESTAMPS" else "NOT_ACCREDITED",
        "r1_status": ground.get("status", "BLOCKED_PENDING"), "r1_dependency": ground.get("dependency", "UNKNOWN"),
        "r1_commands_sent": False, "r1_movement_authorized": False,
        **{f"claims.{k}": False for k in ("images_captured", "detections_made", "speed_commanded", "speed_measured",
                                          "simultaneous_flight", "common_frame_validated", "current_permissions_checked")},
    }
    runs = {}
    for run in scenario.get("runs") or []:
        timeline = run.get("timeline") or {}
        runs[run.get("run_id")] = {
            "vehicle_id": run.get("vehicle_id"), "simulated_vehicle": run.get("simulated_vehicle"),
            "mission_id": run.get("mission_id"), "status": run.get("status"), "result_status": run.get("result_status"),
            "reached_points": sorted(p for p, s in (run.get("points") or {}).items() if s == "REACHED"),
            "return_home": run.get("return_home"), "landing": run.get("landing"),
            "executor_started_at": timeline.get("executor_started_at"),
            "executor_finished_at": timeline.get("executor_finished_at"),
            "_job_admitted_at": timeline.get("job_admitted_at")}
    return expected, runs


def _same(given, want) -> bool:
    """Strict equality: Python's 0 == False and 1 == True must not turn a wrong type into a match."""
    if isinstance(given, bool) or isinstance(want, bool):
        return type(given) is type(want) and given == want
    return given == want


def _duplicate_json_keys(text: str) -> list:
    """Keys repeated in any object of the answer. json.loads keeps the LAST value silently, so
    {"r1_movement_authorized": true, ..., "r1_movement_authorized": false} would otherwise pass.
    Same body selection as parse_answer (one object, optionally inside one ```json fence)."""
    import re
    repeated = set()

    def hook(pairs):
        names = [name for name, _ in pairs]
        repeated.update(name for name in names if names.count(name) > 1)
        return dict(pairs)
    stripped = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.S)
    try:
        json.loads(fenced.group(1) if fenced else stripped, object_pairs_hook=hook)
    except (ValueError, RecursionError):
        return []
    return sorted(repeated)


def accept_scenario_view_answer(session: dict, *, scenario_id: str = SCENARIO_ID) -> dict:
    """Separate verdicts for tool execution, factual keys, critical keys and the free-text explanation.
    Expected values come ONLY from the get_scenario_view result Hermes received in this session."""
    import re
    from observability.mission_query_cases import parse_answer
    from observability.mission_report_acceptance import _result_document
    from tools.mission_report_query import turn_from_session
    calls, answer_text, turn_reasons = turn_from_session(session)
    tool = {"calls": len(calls), "reasons": list(turn_reasons)}
    viewed = [c for c in calls if c["tool_name"] == VIEW_TOOL]
    if len(calls) != len(viewed):
        tool["reasons"].append("OTHER_TOOL_CALLED")
    if len(viewed) != 1 or (viewed[0]["args"] or {}).get("scenario_id") != scenario_id:
        tool["reasons"].append("NOT_EXACTLY_ONE_SCENARIO_VIEW_CALL")
    view = _result_document(viewed[0]["result"]) if len(viewed) == 1 else None
    if not isinstance(view, dict) or view.get("view") != "scenario" or view.get("view_schema") != VIEW_SCHEMA:
        tool["reasons"].append("SCENARIO_VIEW_RESULT_UNREADABLE")
        view = None
    tool["status"] = "OK" if not tool["reasons"] else "FAILED"
    answer, parse_status = parse_answer(answer_text)
    factual, critical, classifications = {"parse": parse_status}, {}, []
    if view is not None and answer is not None:
        expected, runs = _expected_from_view(view)
        for key, value in expected.items():
            group, name = (key.split(".", 1) if key.startswith("claims.") else (None, key))
            container = answer.get(group) if group else answer
            given = container.get(name, "<absent>") if isinstance(container, dict) else "<absent>"
            outcome = "match" if _same(given, value) else ("absent" if given == "<absent>" else "mismatch")
            (critical if key in CRITICAL_KEYS else factual)[key] = outcome
        # Malformed run lists are explicit mismatches: no exception, no silently dropped or merged entry.
        given_list = answer.get("runs")
        if given_list is not None and not isinstance(given_list, list):
            factual["runs.not_a_list"] = "mismatch"
        given_runs = {}
        for entry in given_list if isinstance(given_list, list) else []:
            run_id = entry.get("run_id") if isinstance(entry, dict) else None
            if not isinstance(run_id, str):
                factual["runs.malformed_entries"] = "mismatch"
            elif run_id in given_runs:
                factual["runs.duplicate_run_ids"] = "mismatch"
            else:
                given_runs[run_id] = entry
        for run_id, want in runs.items():
            got = given_runs.get(run_id) or {}
            for key in H3B_RUN_KEYS:
                value = got.get(key, "<absent>")
                # Only a list of point ids is comparable; any other shape (e.g. objects) stays a mismatch.
                if key == "reached_points" and isinstance(value, list) and all(isinstance(p, str) for p in value):
                    value = sorted(value)
                factual[f"runs[{(run_id or '')[:8]}].{key}"] = ("match" if _same(value, want[key]) else
                                                              "absent" if value == "<absent>" else "mismatch")
                if key == "executor_started_at" and value == want["_job_admitted_at"] and value != want[key]:
                    classifications.append(f"ADMISSION_CONFUSED_WITH_EXECUTION:{(run_id or '')[:8]}")
        if set(given_runs) - set(runs):
            factual["runs.unknown_run_ids"] = "mismatch"
        repeated = _duplicate_json_keys(answer_text)
        if repeated:
            factual["answer.duplicate_json_keys"] = "mismatch"
            classifications.append("DUPLICATE_JSON_KEYS:" + ",".join(repeated))
        extra = sorted(set(answer) - set(H3B_ANSWER_KEYS))
        if extra:  # recorded, not rejected: the contract lists keys but does not forbid others
            classifications.append("EXTRA_TOP_LEVEL_KEYS:" + ",".join(extra))
        if any(v != "match" for v in critical.values()):
            classifications.append("CRITICAL_KEY_INCORRECT")
    explanation = answer.get("explanation") if isinstance(answer, dict) else None
    flags = sorted(name for name, pattern in EXPLANATION_FLAGS.items()
                   if isinstance(explanation, str) and re.search(pattern, explanation))
    scored = list(factual.values())[1:] + list(critical.values())
    score = round(sum(v == "match" for v in scored) / len(scored), 3) if scored else 0.0
    failed = sorted(k for k, v in {**factual, **critical}.items() if v in ("mismatch", "absent"))
    if tool["status"] != "OK" or answer is None or view is None or failed:
        status = "NOT_VALIDATED"
    elif not (isinstance(explanation, str) and explanation.strip()):
        status = "NOT_VALIDATED"
        failed.append("explanation")
    elif flags:
        status = "NEEDS_REVIEW"
    else:
        status = "STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED"
    return {"status": status, "tool_execution": tool, "factual": factual, "critical": critical,
            "failed_keys": failed, "classifications": classifications, "score": score,
            "score_note": "reported only; any critical or factual failure rejects the answer regardless of score",
            "explanation_review": {"heuristic_flags": flags, "method": "keyword heuristics, NOT semantic validation",
                                   "semantic_review": "REQUIRED_HUMAN"},
            "view_status": (view or {}).get("status"), "answer": answer,
            "scope": {"record": "historical", "current_availability": "NOT_CHECKED", "operational_authorization": False}}


def accept_h3b_turn(usage_file: Path, *, hermes_bin: Path | None = None, runner=subprocess.run) -> dict:
    from tools.mission_report_query import DEFAULT_HERMES_BIN, QueryError, export_session, session_id_from_usage
    try:
        session = export_session(session_id_from_usage(usage_file), hermes_bin=hermes_bin or DEFAULT_HERMES_BIN,
                                 runner=runner)
    except (QueryError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"status": "NOT_VALIDATED", "reasons": ["TURN_DATA_UNAVAILABLE"], "detail": type(exc).__name__}
    return accept_scenario_view_answer(session)


# --- R1 preparation (dry-run only). It separates five stages that must never be merged:
# dependency (the declared precondition holds in a verified record) -> eligibility (the ground task could be
# executed by this system) -> authorization (an operator's scope) -> admission (the executor's own gate) ->
# execution (an attributed ground result). It reads a scenario view and caller-supplied, labelled inputs;
# it creates no admission, reservation, process, socket or command, and never sets movement_authorized.
R1_PREPARATION_SCHEMA = "tfg.agri-r1-preparation/1"
# Data without which no R1 task can even be described. None exists in the repository today; nothing here
# is invented (the aerial analyzer's 1.0/0.75 m tolerances are NOT ground tolerances).
R1_REQUIRED_DATA = {
    "target_in_rover_frame": "POI_A1 expressed for rover_01 in a validated common frame (H1 offsets are "
                             "relative to drone_01's own launch position; common_frame.validated is false)",
    "ground_tolerance_m": "horizontal tolerance at which a ground verification counts as reached",
    "rover_mission": "a validated rover_01/v3 (ugv, ArduPilot) mission definition and its SHA-256",
    "completion_evidence": "which attributed observation proves the rover verified POI_A1 (source, frame, timing)",
    "frame_transform": "a VERIFIED transformation (sha256, from_frame, to_frame) from POI_A1's definition "
                       "(offsets from drone_01's observed launch) to the target frame; never assumed",
    "execution_limits": "operator-approved rover_limits (RoverLimits fields) and controller parameters "
                        "(yaw_rad, yaw_tolerance_rad, command_hz, max_samples, progress_rad) of ROVER_NAVIGATE_V1",
}
# Executor facts are supplied PER ATTEMPT by the coordinator's adapter (tools.agri_ground_coordinator), obtained
# from the executor's own read-only checks. Without them nothing is eligible.
UNQUERIED_EXECUTOR_FACTS = {"kind": "NOT_QUERIED"}


# R1 as a VISIT-AND-STOP task: navigation to and stationary dwell at POI_A1. It accredits position and
# permanence only, never an agricultural inspection (no sensor). Values are PROPOSED, NOT APPROVED, and
# each needs real validation (see docs); none is inherited from the aerial 1.0/0.75 m tolerances.
# Two clocks are never mixed: dwell is measured on the SIMULATION clock (source_stamp_ns, sim time), while
# timeouts, gaps and data age are measured on the OBSERVATION clock (received_monotonic_s, host monotonic).
R1_VISIT_PROPOSAL = {
    "status": "PROPOSED_NOT_APPROVED",
    # R1 acceptance radius on independently observed position. NOT the autopilot's WP_RADIUS (which only
    # decides when ArduRover considers a waypoint reached); a default value guarantees no accuracy.
    "arrival_tolerance_m": 2.0,
    "dwell_s": 5.0,                   # continuous inside-and-stopped span, simulation clock
    "max_sample_gap_s": 1.0,          # any larger gap (either clock) interrupts dwell; observation clock: loss
    "min_dwell_samples": 6,           # >= ceil(dwell_s / max_sample_gap_s) + 1, checked by _visit_params
    "stopped_linear_mps": 0.05,       # same meaning as RoverLimits.stopped_*; rest noise must be measured
    "stopped_angular_rad_s": 0.05,
    "max_decision_age_s": 1.0,        # last sample older than this at decision time = stale
    # Experimental operational limits, observation clock. Not derived from any measured rover performance;
    # never lengthened to obtain a pass. Global: command start -> dwell completed. No progress: before the
    # first arrival, the distance must shrink by min_progress_m within every no_progress_window_s.
    "global_timeout_s": 120.0,
    "no_progress_window_s": 10.0,
    "min_progress_m": 0.5,
}
GROUND_RESULT_SCHEMA = "tfg.agri-r1-ground-result/1"
# What a finished passive capture AT REST (tools.rover_passive_journal.analyze_capture) can be set against, per
# EXISTING requirement or proposed parameter. None = the capture has no data for it. Observations never fill a
# required datum, approve a value or lift a blocker; they are kept apart from R1_VISIT_PROPOSAL.
R1_MEASURABLE_AT_REST = {
    "target_in_rover_frame": None, "rover_mission": None, "dwell_s": None, "min_dwell_samples": None,
    "max_decision_age_s": None, "global_timeout_s": None, "no_progress_window_s": None, "min_progress_m": None,
    "ground_tolerance_m": "position", "arrival_tolerance_m": "position",
    "completion_evidence": "source", "frame_transform": "frames",
    "execution_limits": "speeds_and_orientation", "stopped_linear_mps": "speeds", "stopped_angular_rad_s": "speeds",
    "max_sample_gap_s": "receipts",
}
R1_MEASURED_DOES_NOT_PROVIDE = [
    "a frame transformation: frame names and a position numerically close to the declared spawn are not one",
    "arrival, progress or dwell: there was no movement and no target",
    "approval of any threshold: retained samples of one session at rest are a contrast, not a basis",
    "a real-time factor or the cause of the gap between header stamps and receipt times",
    "physical rest independent of the source: the speeds come from the same odometry",
    "certainty from declared zero covariances",
    "publisher, model or SYSID identity",
]


def _measured_group(group: dict) -> dict:
    position, speed = group.get("position_m_as_received") or {}, group.get("linear_speed_norm") or {}
    rpy = group.get("orientation_rpy_deg_from_quaternion") or {}
    quaternion = group.get("orientation_quaternion_as_received") or {}
    receipts = group.get("receipt_interval_steady_ns") or {}
    return {
        "source": {"message_publisher_gid": group.get("message_publisher_gid"), "frame_id": group.get("frame_id"),
                   "child_frame_id": group.get("child_frame_id")},
        "retained_samples": group.get("retained_samples"), "complete_with_fields": group.get("complete_with_fields"),
        "with_nonfinite": group.get("with_nonfinite"),
        "position_m": {axis: {k: (position.get(axis) or {}).get(k) for k in ("min", "max", "pstdev")} for axis in "xyz"},
        "orientation_deg_mean": {k: (rpy.get(k) or {}).get("mean") for k in ("roll", "pitch", "yaw")},
        "max_abs_quaternion_xy": max((abs((quaternion.get(k) or {}).get(e) or 0) for k in "xy" for e in ("min", "max")),
                                     default=None),
        "linear_speed_mps_max": speed.get("max"),
        "angular_rate_rad_s_max": (group.get("angular_rate_norm") or {}).get("max"),
        "all_zero_declared_covariances": group.get("all_zero_declared_covariances"),
        "header_span_s": None if group.get("covered_header_span_ns") is None else group["covered_header_span_ns"] / 1e9,
        "receipt_span_s": None if group.get("covered_receipt_span_ns") is None else group["covered_receipt_span_ns"] / 1e9,
        "retained_receipt_interval_max_s": None if receipts.get("max") is None else receipts["max"] / 1e9,
    }


def measured_facts(capture: dict | None) -> dict:
    """Pure: observations of a finished passive capture, labelled {"value": analyze_capture result, "source": str}.
    Anything not ANALYZED with odometry fields gives NOT_AVAILABLE; nothing here is a parameter or a permit."""
    if not capture:
        return {"status": "NOT_PROVIDED", "requirements": {}}
    value, source = capture.get("value") or {}, capture.get("source")
    if value.get("status") != "ANALYZED" or not value.get("pose_fields_present"):
        return {"status": "NOT_AVAILABLE", "source": source, "requirements": {},
                "detail": value.get("reasons") or f"schema {value.get('capture_schema')} has no odometry fields"}
    groups = [_measured_group(g) for g in (value.get("odometry") or {}).get("groups") or []]

    def described(kind):
        if kind is None:
            return None
        parts = []
        for g in groups:
            tag = f"{g['source']['frame_id']}->{g['source']['child_frame_id']} ({g['retained_samples']} samples)"
            p = g["position_m"]
            parts.append(tag + ": " + {
                "position": f"rest dispersion pstdev x {p['x']['pstdev']:.3g} m, y {p['y']['pstdev']:.3g} m",
                "source": f"odometry with pose/twist fields from one GID {g['source']['message_publisher_gid']}; "
                          "identity not accredited",
                "frames": "frame names only; no transformation",
                "speeds": f"residual speed max {g['linear_speed_mps_max']:.3g} m/s, angular "
                          f"{g['angular_rate_rad_s_max']:.3g} rad/s (same source)",
                "speeds_and_orientation": f"residual speed max {g['linear_speed_mps_max']:.3g} m/s; mean pitch "
                                          f"{g['orientation_deg_mean']['pitch']:.3g} deg, max abs(q.x), abs(q.y) "
                                          f"{g['max_abs_quaternion_xy']:.3g} at rest",
                "receipts": f"retained-sample receipt interval max {g['retained_receipt_interval_max_s']:.3g} s "
                            "(selection, not stream loss)",
            }[kind])
        return "; ".join(parts)
    return {"status": "OBSERVED", "source": source, "accredits": False,
            "trial_manifest_sha256": value.get("trial_manifest_sha256"), "journal_sha256": value.get("journal_sha256"),
            "capture_schema": value.get("capture_schema"), "completion_evidence": value.get("completion_evidence"),
            "selection": (value.get("odometry") or {}).get("capture_selection"), "groups": groups,
            "requirements": {name: {"observed_data": described(kind), "accredited": False}
                             for name, kind in R1_MEASURABLE_AT_REST.items()},
            "does_not_provide": R1_MEASURED_DOES_NOT_PROVIDE}
R1_BINDING_KEYS = ("candidate_sha256", "mission_sha256", "authorization_sha256", "vehicle_id", "simulated_vehicle",
                   "session_id", "ground_run_id")


def _canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _finite(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("not a finite number")
    return float(value)


def _visit_params(params: dict) -> dict:
    """Reject incoherent parameter sets instead of evaluating with them."""
    for key in ("arrival_tolerance_m", "dwell_s", "max_sample_gap_s", "stopped_linear_mps", "stopped_angular_rad_s",
                "max_decision_age_s", "global_timeout_s", "no_progress_window_s", "min_progress_m"):
        if _finite(params[key]) <= 0:
            raise ValueError(f"{key} must be positive")
    needed = math.ceil(params["dwell_s"] / params["max_sample_gap_s"]) + 1
    if type(params["min_dwell_samples"]) is not int or params["min_dwell_samples"] < needed:
        raise ValueError(f"min_dwell_samples must be >= {needed} for dwell_s and max_sample_gap_s")
    if params["global_timeout_s"] <= params["dwell_s"] or params["no_progress_window_s"] < params["max_sample_gap_s"]:
        raise ValueError("global_timeout_s must exceed dwell_s; progress window must cover a sample gap")
    return params


def _sample_measure(sample, target, params):
    """(error_m, stopped) or None for a sample whose measurement is invalid; invalid samples interrupt dwell."""
    try:
        error = math.hypot(_finite(sample["x_m"]) - _finite(target["x_m"]), _finite(sample["y_m"]) - _finite(target["y_m"]))
        stopped = (abs(_finite(sample["linear_mps"])) <= params["stopped_linear_mps"]
                   and abs(_finite(sample["angular_rad_s"])) <= params["stopped_angular_rad_s"])
    except (KeyError, TypeError, ValueError):
        return None
    return error, stopped


def evaluate_ground_result(result: dict, candidate: dict | None, expected: dict | None,
                           params: dict = R1_VISIT_PROPOSAL) -> dict:
    """Pure: derive the R1 visit outcome from the result's own samples, in the order given (never re-sorted).
    Claimed flags and job status are never trusted; a PASSED job without target evidence completes nothing.
    REJECTED (binding, frame, timeline) > UNCERTAIN (stale, loss, stop unconfirmed) >
    FAILED (timeout, no progress, not reached, no dwell) > VERIFIED."""
    params = _visit_params(params)
    reasons = []
    binding = result.get("binding") or {}
    commands = result.get("commands") or {}
    out = {"schema": GROUND_RESULT_SCHEMA, "origin": result.get("origin"), "job_status": result.get("job_status"),
           "commands_attempted": commands.get("attempted"), "commands_sent": commands.get("sent"),
           "arrival_observed": False, "min_error_m": None, "dwell_observed_s": 0.0, "dwell_clock": "simulation",
           "stop_confirmed": False, "observation_lost": None, "invalid_samples": 0,
           "tolerance_m": params["arrival_tolerance_m"], "dwell_required_s": params["dwell_s"]}
    if candidate is None:
        reasons.append("NO_R1_CANDIDATE")
    else:
        want = {"candidate_sha256": _canonical_sha(candidate),
                "mission_sha256": (candidate.get("rover_mission", {}).get("value") or {}).get("sha256"),
                "vehicle_id": candidate.get("vehicle_id"), "simulated_vehicle": "v3", **(expected or {})}
        mismatched = sorted(k for k in R1_BINDING_KEYS if want.get(k) is None or binding.get(k) != want.get(k))
        if mismatched:
            reasons.append("BINDING_MISMATCH:" + ",".join(mismatched))
    target = ((candidate or {}).get("target_in_rover_frame") or {}).get("value") or {}
    frame = result.get("frame") or {}
    if frame.get("name") != target.get("frame") or frame.get("transform_status") != "VERIFIED":
        reasons.append("FRAME_NOT_VERIFIED_OR_DIFFERENT")
    samples = result.get("samples") or []
    if not isinstance(samples, list) or not all(isinstance(s, dict) for s in samples):
        reasons.append("MALFORMED_SAMPLES")
        samples = []
    if any(s.get("frame") != target.get("frame") for s in samples):
        reasons.append("SAMPLE_FRAME_DIFFERENT")
    if not samples:
        reasons.append("NO_TARGET_EVIDENCE")
    try:
        received = [_finite(s["received_monotonic_s"]) for s in samples]
        source = [s["source_stamp_ns"] for s in samples]
        decision = _finite(result["decision_monotonic_s"])
        started = _finite(commands["started_monotonic_s"]) if commands.get("attempted") else received[0] if received else 0.0
        if any(type(x) is not int or x < 0 for x in source):
            raise ValueError("source stamps")
    except (KeyError, TypeError, ValueError, IndexError):
        reasons.append("MALFORMED_TIMELINE")
        received, source = [], []
    if any(b <= a for a, b in zip(received, received[1:])):
        reasons.append("TIMELINE_NOT_ORDERED")  # duplicated or inverted observation timestamps
    if reasons:
        return {**out, "outcome": "REJECTED", "reasons": reasons}
    measures = [_sample_measure(s, target, params) for s in samples]
    out["invalid_samples"] = sum(m is None for m in measures)
    valid_errors = [m[0] for m in measures if m is not None]
    out["min_error_m"] = round(min(valid_errors), 3) if valid_errors else None
    gaps = [b - a for a, b in zip(received, received[1:])]
    out["observation_lost"] = bool(result.get("observation_lost")) or any(g > params["max_sample_gap_s"] for g in gaps)
    stale = (any(b <= a for a, b in zip(source, source[1:]))  # repeated/inverted simulation stamps
             or not 0 <= decision - received[-1] <= params["max_decision_age_s"])
    arrival_index = next((i for i, m in enumerate(measures) if m and m[0] <= params["arrival_tolerance_m"]), None)
    out["arrival_observed"] = arrival_index is not None
    # Dwell: a run of consecutive valid, inside, stopped samples whose gaps on BOTH clocks stay within the
    # maximum; its duration is measured on the simulation clock only.
    best, completed_at, run_start = 0.0, None, None
    for i, measure in enumerate(measures):
        inside = measure is not None and measure[0] <= params["arrival_tolerance_m"] and measure[1]
        contiguous = (run_start is not None and received[i] - received[i - 1] <= params["max_sample_gap_s"]
                      and 0 < (source[i] - source[i - 1]) / 1e9 <= params["max_sample_gap_s"])
        run_start = (run_start if contiguous else i) if inside else None
        if run_start is not None and i - run_start + 1 >= params["min_dwell_samples"]:
            span = (source[i] - source[run_start]) / 1e9
            best = max(best, span)
            if span >= params["dwell_s"] and completed_at is None:
                completed_at = received[i]
    out["dwell_observed_s"] = round(best, 3)
    out["stop_confirmed"] = (result.get("stop") or {}).get("status") == "STATIONARY_OBSERVED"
    if stale:
        reasons.append("STALE_OR_NON_PROGRESSING_DATA")
    if out["observation_lost"]:
        reasons.append("OBSERVATION_LOST")
    if not out["stop_confirmed"]:
        reasons.append("STOP_UNCONFIRMED")
    if reasons:
        return {**out, "outcome": "UNCERTAIN", "reasons": reasons}
    end = completed_at if completed_at is not None else received[-1]
    out["elapsed_observation_s"] = round(end - started, 3)
    if end - started > params["global_timeout_s"]:
        reasons.append("GLOBAL_TIMEOUT")
    approach_end = received[arrival_index] if arrival_index is not None else received[-1]
    for i, measure in enumerate(measures):  # every full window before the first arrival must show progress
        if measure is None or received[i] + params["no_progress_window_s"] > approach_end:
            continue
        later = next(j for j in range(i, len(received)) if received[j] >= received[i] + params["no_progress_window_s"])
        if measures[later] is not None and measure[0] - measures[later][0] < params["min_progress_m"]:
            reasons.append("NO_PROGRESS")
            break
    if not out["arrival_observed"]:
        reasons.append("NOT_REACHED_OUT_OF_TOLERANCE")
    elif completed_at is None:
        reasons.append("PASSED_THROUGH_NO_DWELL")
    if reasons:
        return {**out, "outcome": "FAILED", "reasons": reasons}
    return {**out, "outcome": "VERIFIED", "reasons": []}


def _input_value(inputs: dict, name: str):
    entry = (inputs or {}).get(name)
    if not isinstance(entry, dict) or entry.get("value") in (None, "") or not entry.get("source"):
        return None, None
    return entry["value"], entry["source"]


def _rover_policy_enabled():
    """Read-only: the executor's own constant (False in this repository); unreadable means not enabled."""
    try:
        from tools import rover_ground_executor
    except Exception:  # an import failure must not look like an enabled policy
        return None
    return rover_ground_executor.OPERATIONAL_ROVER_ENABLED is True


def _transform_problem(value, target) -> str | None:
    """A frame transformation is usable only when VERIFIED, hashed and ending in the target's frame."""
    if not isinstance(value, dict) or value.get("status") != "VERIFIED":
        return "frame_transform not VERIFIED"
    if not isinstance(value.get("sha256"), str) or len(value["sha256"]) != 64 or not value.get("from_frame"):
        return "frame_transform without sha256/from_frame"
    if not isinstance(target, dict) or value.get("to_frame") != target.get("frame"):
        return "frame_transform does not end in the target frame"
    return None


def prepare_ground_task(view: dict, *, inputs: dict | None = None, ground_trial: dict | None = None,
                        expected_binding: dict | None = None, policy_enabled=_rover_policy_enabled,
                        executor_facts: dict = UNQUERIED_EXECUTOR_FACTS, capture: dict | None = None,
                        identity: dict | None = None) -> dict:
    """Pure dry-run of R1 over a scenario view (get_scenario_view / scenario_view output).

    ``capture`` is an optional labelled analyze_capture result; its observations go to ``measured_facts`` only,
    never into the candidate, the proposed parameters or the blockers.

    ``inputs`` maps names of R1_REQUIRED_DATA (and ``rover_identity``) to {"value", "source"}; a source starting
    with TEST_DOUBLE marks the result as built from doubles. ``ground_trial`` is either a query_ground_trial-shaped
    result (no position outcome, so it can never complete R1) or a GROUND_RESULT_SCHEMA result, evaluated
    against the candidate and ``expected_binding`` (session_id, authorization_sha256, ground_run_id)."""
    scenario = view.get("scenario") if view.get("status") == "OK" else None
    scenario = scenario or {}
    sequence = scenario.get("sequence") or {}
    target = (scenario.get("points") or {}).get(GROUND_TASK["target_point"]) or {}
    declared = (scenario.get("ground_task") or {}).get("dependency")
    conditions = [
        {"name": "view_verified", "stage": "dependency",
         "status": "SATISFIED" if view.get("status") == "OK" else "NOT_SATISFIED" if view.get("status") == "REJECTED"
         else "UNKNOWN", "detail": f"view status {view.get('status')}"},
        {"name": "sequence_completed", "stage": "dependency",
         "status": "SATISFIED" if (sequence.get("job_state"), sequence.get("result_status")) == ("FINISHED", "PASSED")
         and scenario.get("status") == "AERIAL_COMPLETED_GROUND_PENDING"
         else "NOT_SATISFIED" if scenario.get("status") in ("FAILED", "BLOCKED", "NOT_EXECUTED") else "UNKNOWN",
         "detail": f"sequence {sequence.get('job_state')}/{sequence.get('result_status')}, "
                   f"scenario {scenario.get('status')}"},
        {"name": "target_reached_by_drone_01", "stage": "dependency",
         "status": "SATISFIED" if target == {"vehicle_id": "drone_01", "status": "REACHED"}
         else "UNKNOWN" if target.get("status") in (None, "UNKNOWN") else "NOT_SATISFIED",
         "detail": f"{GROUND_TASK['target_point']}: {target or 'absent'}"},
    ]
    derived = ("MET" if all(c["status"] == "SATISFIED" for c in conditions)
               else "NOT_MET" if any(c["status"] == "NOT_SATISFIED" for c in conditions[1:]) else "UNKNOWN")
    if declared is not None and declared != derived:  # the view and its own facts disagree: trust neither
        conditions.append({"name": "dependency_consistent", "stage": "dependency", "status": "NOT_SATISFIED",
                           "detail": f"view declares {declared}, its facts give {derived}"})
        derived = "UNKNOWN"
    values, sources = {}, {}
    for name in R1_REQUIRED_DATA:
        values[name], sources[name] = _input_value(inputs, name)
    missing = [name for name in R1_REQUIRED_DATA if values[name] is None]
    # Optional, but authorized like everything else: the closure policy the executor must apply.
    finalization, finalization_source = _input_value(inputs, "finalization_policy")
    transform_problem = (_transform_problem(values["frame_transform"], values["target_in_rover_frame"])
                         if values["frame_transform"] is not None else None)
    if transform_problem:  # a declared or mismatched transformation is NOT data for an executable task
        missing.append("frame_transform")
    policy = executor_facts["policy_enabled"] if "policy_enabled" in executor_facts else policy_enabled()
    navigation = executor_facts.get("navigation_request_supported")
    eligibility = [
        {"name": "dependency_met", "status": "SATISFIED" if derived == "MET" else "NOT_SATISFIED",
         "detail": f"dependency {derived}"},
        {"name": "required_data_present", "status": "NOT_SATISFIED" if missing else "SATISFIED",
         "detail": ("missing: " + ", ".join(missing) + (f" ({transform_problem})" if transform_problem else ""))
         if missing else "all present"},
        # Facts of THIS attempt, from the executor's own read-only checks (never a historical record).
        {"name": "executor_accepts_navigation_request",
         "status": "SATISFIED" if navigation is True else "NOT_SATISFIED" if navigation is False else "UNKNOWN",
         "detail": f"{executor_facts.get('kind')}: {executor_facts.get('navigation_request_detail')}"},
        {"name": "operational_rover_policy_enabled",
         "status": "SATISFIED" if policy is True else "NOT_SATISFIED" if policy is False else "UNKNOWN",
         "detail": f"{executor_facts.get('kind')}: OPERATIONAL_ROVER_ENABLED"},
    ]
    if finalization is not None:
        supported = (executor_facts.get("executor_facts") or {}).get("finalization_policies") or []
        eligibility.append({"name": "executor_supports_finalization_policy",
                            "status": "SATISFIED" if isinstance(finalization, dict) and finalization.get("kind")
                            in supported else "NOT_SATISFIED", "detail": f"requested {finalization}; supported {supported}"})
    # Identity, readiness, reservations and stop are the executor's own gates at execution time; the coordinator
    # neither claims nor replaces them, and a historical identity/readiness never counts.
    deferred = [{"name": "rover_identity_readiness_reservation", "status": "DEFERRED_TO_EXECUTOR_GATES",
                 "detail": "checked by the executor when it runs; not asserted here"}]
    eligible = all(c["status"] == "SATISFIED" for c in eligibility)
    candidate = None
    if derived == "MET" and not missing:
        candidate = {"task_id": GROUND_TASK["task_id"], "vehicle_id": GROUND_TASK["vehicle_id"],
                     "target_point": GROUND_TASK["target_point"], "visit_parameters": dict(R1_VISIT_PROPOSAL),
                     **{name: {"value": values[name], "source": sources[name]} for name in R1_REQUIRED_DATA},
                     **({"finalization_policy": {"value": finalization, "source": finalization_source}}
                        if finalization is not None else {}),
                     "depends_on_sequence": sequence.get("sequence_id"),
                     "depends_on_binding": (view.get("sources") or {}).get("binding_record")}
    result = None
    if ground_trial is not None and ground_trial.get("schema") == GROUND_RESULT_SCHEMA:
        result = evaluate_ground_result(ground_trial, candidate, expected_binding)
        # The contract would be satisfied, but a dry-run has no authorization stage: it never completes R1.
        result.update(would_satisfy_r1_contract=result["outcome"] == "VERIFIED" and derived == "MET",
                      counts_as_r1_completion=False,
                      reason="DRY_RUN_HAS_NO_AUTHORIZATION_OR_EXECUTION_STAGE")
    elif ground_trial is not None:
        report = ground_trial.get("report") or {}
        result = {"query_status": ground_trial.get("status"), "report_status": report.get("status"),
                  "counts_as_r1_completion": False,  # no position outcome in the executor contract
                  "reason": "GROUND_TRIAL_RESULT_HAS_NO_POSITION_OUTCOME"}
    if finalization is not None:
        sources = {**sources, "finalization_policy": finalization_source}
    doubles = sorted(n for n, s in sources.items() if isinstance(s, str) and s.startswith("TEST_DOUBLE"))
    blockers = [c["name"] for c in conditions + eligibility if c["status"] != "SATISFIED"]
    return {"schema": R1_PREPARATION_SCHEMA, "task_id": GROUND_TASK["task_id"], "dry_run": True,
            "inputs_include_test_doubles": doubles, "executor_kind": executor_facts.get("kind"),
            "stages": {"dependency": derived, "eligibility": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
                       "authorization": "ABSENT", "admission": "NOT_REQUESTED", "execution": "NOT_STARTED"},
            "conditions": conditions, "eligibility": eligibility, "deferred_to_executor": deferred,
            "blockers": blockers,
            "missing_data": {name: R1_REQUIRED_DATA[name] for name in missing},
            "proposed_parameters": dict(R1_VISIT_PROPOSAL), "measured_facts": measured_facts(capture),
            # facts of a closed identity session (reporting.rover_identity_facts): shown, never a gate
            "identity_facts": identity or {"status": "NOT_PROVIDED"},
            "candidate": candidate, "candidate_sha256": _canonical_sha(candidate) if candidate else None,
            "ground_result": result, "r1_status": "BLOCKED_PENDING",
            "scenario_complete": False, "movement_authorized": False, "commands_sent": False,
            "admission_created": False, "reservation_created": False,
            "note": "dry-run: MET is a precondition only; authorization and admission belong to the operator and "
                    "the existing ground executor gates, which this function never calls"}


def scenario_with_r1(view: dict, record: dict | None) -> dict:
    """Scenario status from the aerial view and an R1 coordination record. Only an EXECUTED, real-executor
    VERIFIED result completes the scenario; a synthetic one is labelled and leaves scenario_complete false."""
    aerial = (view.get("scenario") or {}).get("status") if view.get("status") == "OK" else view.get("status")
    dependency = ((view.get("scenario") or {}).get("ground_task") or {}).get("dependency")
    state = (record or {}).get("state", "NOT_REQUESTED")
    if aerial != "AERIAL_COMPLETED_GROUND_PENDING":
        return {"scenario_status": aerial, "scenario_complete": False, "synthetic_complete": False, "r1_state": state}
    if dependency != "MET":
        return {"scenario_status": f"AERIAL_COMPLETED_R1_DEPENDENCY_{dependency}", "scenario_complete": False,
                "synthetic_complete": False, "r1_state": state}
    if record is None:  # never requested through the coordinator: the view's own status stands, unchanged
        return {"scenario_status": aerial, "scenario_complete": False, "synthetic_complete": False, "r1_state": state}
    complete = state == "VERIFIED"
    return {"scenario_status": "COMPLETED" if complete else "SYNTHETIC_COMPLETE" if state == "VERIFIED_SYNTHETIC"
            else f"AERIAL_COMPLETED_GROUND_{state}", "scenario_complete": complete,
            "synthetic_complete": state == "VERIFIED_SYNTHETIC", "r1_state": state}


NO_R1_RECORD_MEANING = ("no R1 record: it was not requested through this coordinator; this proves no eligibility "
                        "and removes no blocker")


def _execution_dimension(record: dict | None, acceptance: dict) -> dict:
    if record is None or record.get("state") == "REJECTED_BY_EXECUTOR" and not acceptance:
        return {"status": "NOT_STARTED"}  # no record, or an admission the executor refused
    if not record.get("executor_status") and not acceptance:
        return {"status": "NOT_OBSERVED", "record_state": record.get("state")}  # admitted/unconfirmed: unknown yet
    return {"status": record.get("executor_status"), "acceptance": acceptance.get("outcome"),
            "commands_sent": acceptance.get("commands_sent")}


def r1_dimensions(view: dict, preparation: dict | None = None, record: dict | None = None) -> dict:
    """Pure: the separate dimensions of R1 in one scenario. None is derived from another: a MET dependency is
    not eligibility, a missing record is not eligibility nor refusal, and a declared authorization is not
    authentication. The historical view's own R1 status and barriers are kept as recorded."""
    task = ((view or {}).get("scenario") or {}).get("ground_task") or {}
    stages = (preparation or {}).get("stages") or {}
    acceptance = (record or {}).get("acceptance") or {}
    scenario = scenario_with_r1(view or {}, record)
    return {
        "dependency": task.get("dependency", "UNKNOWN"),
        "eligibility": {"historical_view": {"status": task.get("status"), "barriers": task.get("barriers") or []},
                        "this_preparation": {"eligibility": stages.get("eligibility", "NOT_EVALUATED"),
                                             "blockers": (preparation or {}).get("blockers")}},
        "authorization": ("ABSENT" if not (record or {}).get("authorization")
                          else "DECLARED_NOT_AUTHENTICATED"),
        "request": ({"status": "NOT_REQUESTED_VIA_THIS_COORDINATOR", "meaning": NO_R1_RECORD_MEANING}
                    if record is None else {"status": record.get("state"), "run_id": record.get("run_id")}),
        "execution": _execution_dimension(record, acceptance),
        "completeness": {k: scenario[k] for k in ("scenario_status", "scenario_complete", "synthetic_complete")},
    }


def scenario_tasks(view: dict, preparation: dict, record: dict | None = None) -> list[dict]:
    """Pure: the complete mission model (A1, A2, R1) with vehicles, dependencies, artifacts and hashes,
    destination and frame, objective criteria and the authorization/admission/execution/recovery stages.
    Every value is copied from the view, the R1 preparation or the R1 coordination record."""
    scenario = view.get("scenario") or {}
    runs = scenario.get("runs") or []
    auth = scenario.get("authorization_recorded") or {}
    tasks = []
    for index, run in enumerate(runs):
        tasks.append({
            "task_id": f"A{index + 1}", "kind": "AERIAL", "vehicle_id": run.get("vehicle_id"),
            "simulated_vehicle": run.get("simulated_vehicle"),
            "depends_on": [] if index == 0 else ["A1 PASSED (coordinator dispatches child 2 only after it)"],
            "artifacts": {"mission_id": run.get("mission_id"), "mission_sha256": run.get("mission_sha256"),
                          "report_sha256": run.get("report_sha256"),
                          "binding_record": (view.get("sources") or {}).get("binding_record")},
            "destination": {"points": sorted(run.get("points") or {}),
                            "frame": "offsets from this vehicle's observed launch position (not a common frame)"},
            "objective": {"points": run.get("points"), "tolerances": scenario.get("tolerances")},
            "authorization": auth.get("source"), "admission": (scenario.get("sequence") or {}).get("sequence_id"),
            "execution": {"status": run.get("status"), "result_status": run.get("result_status")},
            "recovery": {"return_home": run.get("return_home"), "landing": run.get("landing")}})
    candidate = (preparation or {}).get("candidate") or {}
    acceptance = (record or {}).get("acceptance") or {}
    tasks.append({
        "task_id": GROUND_TASK["task_id"], "kind": "GROUND_VISIT_AND_STOP", "vehicle_id": GROUND_TASK["vehicle_id"],
        "depends_on": [GROUND_TASK["depends_on"]],
        "dependency": (preparation or {}).get("stages", {}).get("dependency"),
        "artifacts": {"candidate_sha256": (preparation or {}).get("candidate_sha256"),
                      "rover_mission": (candidate.get("rover_mission") or {}).get("value"),
                      "frame_transform": (candidate.get("frame_transform") or {}).get("value")},
        "destination": (candidate.get("target_in_rover_frame") or {}).get("value")
        or {"status": "NOT_AVAILABLE", "missing": sorted((preparation or {}).get("missing_data") or {})},
        "objective": {**R1_VISIT_PROPOSAL, "arrival_tolerance_m": (candidate.get("ground_tolerance_m") or {}).get("value")
                      or R1_VISIT_PROPOSAL["arrival_tolerance_m"]},
        "eligibility": (preparation or {}).get("stages", {}).get("eligibility"),
        "blockers": (preparation or {}).get("blockers"),
        "authorization": {"source": ((record or {}).get("authorization") or {}).get("source"),
                          "authorization_sha256": (record or {}).get("authorization_sha256")} if record else "ABSENT",
        "admission": {"state": (record or {}).get("state", "NOT_REQUESTED"), "run_id": (record or {}).get("run_id"),
                      "executor_session_id": (record or {}).get("executor_session_id"),
                      "authorized_session_id": ((record or {}).get("authorization") or {}).get("session_id"),
                      "executor_kind": (record or {}).get("executor_kind")},
        "execution": {"executor_status": (record or {}).get("executor_status"),
                      "commands_attempted": acceptance.get("commands_attempted"),
                      "commands_sent": acceptance.get("commands_sent")},
        "acceptance": acceptance or None,
        "recovery": "executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator",
        "inputs_include_test_doubles": (preparation or {}).get("inputs_include_test_doubles")})
    return tasks


def _r1_reason(state: str, acceptance: dict) -> str:
    """Why R1 does or does not complete the scenario, derived from the record state and acceptance facts."""
    if state == "VERIFIED":
        return "objetivo, permanencia, parada y cierre del ejecutor confirmados con registros reales"
    if state == "VERIFIED_SYNTHETIC":
        return "contrato cumplido con entradas o sesión sintéticas: completo solo como demostración"
    if state == "CLOSURE_PENDING":
        reached = acceptance.get("arrival_observed") and (acceptance.get("dwell_observed_s") or 0) >= (
            acceptance.get("dwell_required_s") or float("inf"))
        return (("llegada y permanencia observadas" if reached else "llegada o permanencia no cumplidas")
                + f"; parada {'confirmada' if acceptance.get('stop_confirmed') else 'NO confirmada'}"
                + "; el ejecutor no ha confirmado el cierre (trabajo UNCONFIRMED, reserva retenida)")
    if state in ("FAILED", "UNCERTAIN", "REJECTED_RESULT"):
        return f"aceptación {acceptance.get('outcome')}: {acceptance.get('reasons') or 'sin motivo registrado'}"
    return f"R1 en estado {state}: sin resultado terrestre aceptable"


def render_ground_report(view: dict, preparation: dict, record: dict | None = None) -> str:
    """Pure Markdown: per-task result and blockers, provenance, commands and evidence, arrival/dwell/stop,
    uncertainty and scenario completeness. Values cite their record field; no model text is included."""
    tasks = scenario_tasks(view, preparation, record)
    result = scenario_with_r1(view, record)

    def v(value):
        return "sin dato" if value is None else value
    lines = ["## Tareas del escenario y R1", "",
             "Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. "
             "Cada valor cita su campo entre corchetes.", "",
             "| Tarea | Vehículo | Depende de | Estado | Artefactos |", "| --- | --- | --- | --- | --- |"]
    for task in tasks[:-1]:
        lines.append(f"| {task['task_id']} | {task['vehicle_id']} | {', '.join(task['depends_on']) or '—'} | "
                     f"{task['execution']['status']}/{task['execution']['result_status']} [scenario.runs] | "
                     f"misión `{(task['artifacts']['mission_sha256'] or '')[:12]}…`, informe "
                     f"`{(task['artifacts']['report_sha256'] or '')[:12]}…` [scenario.runs] |")
    r1 = tasks[-1]
    acceptance = r1["acceptance"] or {}
    lines.append(f"| R1 | {r1['vehicle_id']} | {r1['depends_on'][0]} | {r1['admission']['state']} [record.state] | "
                 f"candidato `{(r1['artifacts']['candidate_sha256'] or 'ninguno')[:12]}` [preparation.candidate_sha256] |")
    lines += ["", "### R1", "",
              f"- Dependencia: **{r1['dependency']}**; elegibilidad: **{r1['eligibility']}** [preparation.stages].",
              "- Bloqueos: " + (", ".join(r1["blockers"] or []) or "ninguno") + " [preparation.blockers].",
              f"- Destino: {json.dumps(r1['destination'], ensure_ascii=False)} [candidate.target_in_rover_frame].",
              f"- Transformación: {json.dumps(r1['artifacts']['frame_transform'], ensure_ascii=False)} "
              "[candidate.frame_transform].",
              f"- Autorización: {json.dumps(r1['authorization'], ensure_ascii=False)} [record.authorization].",
              f"- Admisión: {json.dumps(r1['admission'], ensure_ascii=False)} [record].",
              f"- Órdenes intentadas/enviadas: {v(r1['execution']['commands_attempted'])}/"
              f"{v(r1['execution']['commands_sent'])} [acceptance.commands_*].",
              f"- Llegada observada: {v(acceptance.get('arrival_observed'))} (error mínimo "
              f"{v(acceptance.get('min_error_m'))} m, tolerancia {v(acceptance.get('tolerance_m'))} m) [acceptance].",
              f"- Permanencia: {v(acceptance.get('dwell_observed_s'))} s de {v(acceptance.get('dwell_required_s'))} s "
              "(reloj de simulación) [acceptance.dwell_observed_s].",
              f"- Parada confirmada: {v(acceptance.get('stop_confirmed'))}; pérdida de observación: "
              f"{v(acceptance.get('observation_lost'))} [acceptance].",
              f"- Evaluación del contrato sobre las muestras: {acceptance.get('outcome', 'sin resultado')}; motivos que "
              f"impiden aceptar: {acceptance.get('reasons') or 'ninguno'} [record.acceptance].",
              f"- Estado del trabajo en el ejecutor: {v(acceptance.get('executor_job_status'))}; estado R1: "
              f"**{r1['admission']['state']}** [record.state].",
              f"- Procedencia: {v(acceptance.get('provenance'))}; origen declarado por el ejecutor: "
              f"{v(acceptance.get('declared_origin'))}; contrato sin resolver: "
              f"{acceptance.get('unresolved_contract') if acceptance.get('unresolved_contract') is not None else 'sin dato'} "
              "[acceptance.provenance].",
              f"- Marco: {v(acceptance.get('frame_basis'))}; etiqueta del ejecutor: "
              f"{v(acceptance.get('executor_frame_label'))} [acceptance.frame_basis].",
              "- La autorización es una declaración vinculada al candidato y a la sesión; no es autenticación humana.",
              "- Etapas registradas: " + (" → ".join(h["state"] for h in (record or {}).get("history") or [])
                                         or "ninguna") + " [record.history].",
              f"- Parámetros autorizados: {json.dumps(acceptance.get('authorized_parameters'), ensure_ascii=False)} "
              "[acceptance.authorized_parameters].",
              f"- Armado observado en la parada: {v(acceptance.get('armed_after_stop'))}; política de cierre autorizada: "
              f"{json.dumps(acceptance.get('authorized_finalization'), ensure_ascii=False)}; aplicada: "
              f"{json.dumps(acceptance.get('finalization'), ensure_ascii=False)} [acceptance.finalization].",
              f"- Cierre según el ejecutor: {json.dumps(acceptance.get('closure'), ensure_ascii=False)}; trabajo: "
              f"{v(acceptance.get('executor_closure'))} [acceptance.closure].",
              f"- Motivo: {_r1_reason(r1['admission']['state'], acceptance)}.",
              f"- Dobles de prueba en las entradas: {r1['inputs_include_test_doubles'] or 'ninguno'} "
              "[preparation.inputs_include_test_doubles].",
              f"- Recuperación: {r1['recovery']}.", ""]
    lines += _render_measured((preparation or {}).get("measured_facts") or {})
    lines += _render_identity((preparation or {}).get("identity_facts") or {})
    lines += [
              *_render_dimensions(r1_dimensions(view, preparation, record)),
              f"**Escenario:** `{result['scenario_status']}`; completo: **{'sí' if result['scenario_complete'] else 'no'}**"
              + ("; completo solo en la demostración sintética" if result["synthetic_complete"] else "")
              + " [scenario_with_r1].", ""]
    return "\n".join(lines)


def _render_dimensions(d: dict) -> list:
    """The R1 dimensions as separate lines, so that no single label stands for all of them."""
    view, prep = d["eligibility"]["historical_view"], d["eligibility"]["this_preparation"]
    request = d["request"]
    return ["#### Dimensiones de R1 (independientes) [r1_dimensions]", "",
            f"- Dependencia: **{d['dependency']}** (precondición, no permiso).",
            f"- Elegibilidad en la vista histórica: **{view['status']}**; barreras registradas: "
            + ("; ".join(view["barriers"]) or "ninguna") + ".",
            f"- Elegibilidad en esta preparación: **{prep['eligibility']}**; bloqueos: "
            + (", ".join(prep["blockers"] or []) or "ninguno") + ".",
            f"- Autorización: **{d['authorization']}**.",
            f"- Solicitud y admisión: **{request['status']}**"
            + (f" ({request['meaning']})" if request.get("meaning") else "") + ".",
            f"- Ejecución: {json.dumps(d['execution'], ensure_ascii=False)}.",
            f"- Completitud: `{d['completeness']['scenario_status']}`; completo: "
            f"{'sí' if d['completeness']['scenario_complete'] else 'no'}.", ""]


def _render_identity(facts: dict) -> list:
    """Facts of one identity session, kept apart from other sessions, the candidate and the blockers."""
    if facts.get("status") != "OBSERVED":
        return ["#### Hechos de identidad del rover", "",
                f"Estado: {facts.get('status', 'NOT_PROVIDED')}" + (f" ({facts['reason']})" if facts.get("reason") else "")
                + " [preparation.identity_facts].", ""]
    lines = [f"#### Hechos de identidad del rover (sesión `{facts['session_id']}`; no acreditan identidad)", "",
             f"Evidencia `{facts['evidence_id']}`, manifiesto `{facts['manifest_sha256']}` ({facts['files_verified']} "
             f"archivos verificados). `identity_complete`: {facts['identity_complete']}. No son contemporáneos de "
             "otras sesiones: sus muestras y GID no se combinan con ellas [preparation.identity_facts].", "",
             "| Hecho | Estado | Ámbito | Observado | No acredita | Matriz de requisitos del rover |", "| --- | --- | --- | --- | --- | --- |"]
    scope = {"PULSE_AND_POI_A1": "pulso local y POI_A1", "POI_A1_ONLY": "solo POI_A1"}
    lines += [f"| {f['title']} | `{f['state']}` | {scope.get(f['scope'], f['scope'])} | {f['detail']} | {f['not_accredited']} | "
              f"`{f['rover_side']['result']}` |" for f in facts["facts"]]
    return lines + [""]


def _identity_arg(args):
    """Facts of a closed identity session from the CLI, or None. Offline and manifest-verified."""
    if getattr(args, "identity_trial_root", None) is None:
        return None
    from reporting.rover_identity_facts import identity_facts
    return identity_facts(args.identity_trial_root)


def _capture_arg(args):
    """Labelled analyze_capture result from the CLI, or None. Offline and manifest-verified."""
    if args.capture_trial_root is None:
        return None
    from tools.rover_passive_journal import analyze_capture
    return {"value": analyze_capture(args.capture_trial_root, args.capture_dir or ""),
            "source": f"PASSIVE_CAPTURE {args.capture_trial_root} (origin as declared by its trial)"}


def _render_measured(facts: dict) -> list:
    """Measured facts, kept apart from the proposed parameters. Observations only."""
    if facts.get("status") != "OBSERVED":
        return ["#### Hechos medidos", "", f"Estado: {facts.get('status', 'NOT_PROVIDED')} [preparation.measured_facts].", ""]
    lines = ["#### Hechos medidos (observaciones; no son parámetros ni autorización)", "",
             f"Captura `{facts['capture_schema']}`, manifiesto `{facts['trial_manifest_sha256']}`, diario "
             f"`{facts['journal_sha256']}`; fuente declarada: {facts['source']} [preparation.measured_facts].", ""]
    lines += [f"- `{g['source']['frame_id']}`→`{g['source']['child_frame_id']}`: {g['retained_samples']} muestras "
              f"retenidas; sellos del mensaje cubren {g['header_span_s']:g} s y la recepción {g['receipt_span_s']:.4g} s "
              "(relojes distintos; sin factor de tiempo real ni causa atribuida)" for g in facts["groups"]]
    lines += ["",
             "| Requisito o parámetro propuesto | Dato observado | Acreditado |", "| --- | --- | --- |"]
    for name, item in facts["requirements"].items():
        lines.append(f"| `{name}` | {item['observed_data'] or 'sin datos en esta captura'} | no |")
    lines += ["", "No aporta:"] + [f"- {item}" for item in facts["does_not_provide"]] + [""]
    return lines


# --- Evaluation pilot: dry-run only (no inference). Cases are built by the SAME scenario_view code from the
# real H2 sequence record (REAL, unmodified) or from deterministic, labelled transformations of it
# (SYNTHETIC). get_scenario_view serves only real records, so synthetic cases are evaluable by the code
# but NOT servable to Hermes with the existing mechanism.
PILOT_REAL_REPETITIONS = 10
# Current-state fields of the sequence query; excluded from the fixed input digest of a historical record.
VOLATILE_SEQUENCE_KEYS = ("coordinator_alive", "sequence_restriction", "global_flight_restriction", "paths",
                          "message", "uncertainties")


def _synthetic_failed_first(sequence):
    child, second = sequence["children"]
    report = child["detail"]["report"]
    report["status"] = child["result_status"] = "FAILED"
    report["analysis"]["passed"] = False
    report["analysis"]["checks"]["all_waypoints_reached"] = False
    report["executor_result"].update(status="FAILED", success=False, recovery={
        "landing_completed": True, "landing": {"landed": True, "armed": False, "flying": False}})
    second.update(state="NOT_STARTED", result_status=None, started_at=None, finished_at=None)
    second["detail"]["report"] = None
    sequence["result_status"] = "FAILED"


def _synthetic_incomplete(sequence):
    sequence["children"][1]["detail"]["report"] = None  # second report missing although FINISHED


def _synthetic_order_unaccredited(sequence):
    sequence["children"][1]["detail"]["report"].pop("execution_started_at")


PILOT_CASES = (
    ("real-h2", "REAL", None, "Unmodified H2 record: aerial completed, R1 BLOCKED_PENDING with MET"),
    ("synthetic-failed-first", "SYNTHETIC", _synthetic_failed_first,
     "Child 1 FAILED with recovery landing; child 2 NOT_STARTED"),
    ("synthetic-incomplete", "SYNTHETIC", _synthetic_incomplete, "Child 2 report missing although FINISHED"),
    ("synthetic-order-unaccredited", "SYNTHETIC", _synthetic_order_unaccredited,
     "Child 2 execution start missing: order cannot be accredited"),
    ("synthetic-altered-record", "SYNTHETIC", "REFUSED", "Binding record does not match the recorded hashes"),
)


def _correct_answer(view):
    """What a correct reader returns, derived from the view itself (used only to check evaluability)."""
    expected, runs = _expected_from_view(view)
    answer = {k: v for k, v in expected.items() if not k.startswith("claims.")}
    answer["claims"] = {k.split(".", 1)[1]: v for k, v in expected.items() if k.startswith("claims.")}
    answer["runs"] = [{"run_id": run_id, **{k: v for k, v in run.items() if not k.startswith("_")}}
                      for run_id, run in runs.items()]
    answer.update(evidence_source="get_scenario_view", explanation="Respuesta de comprobación del dry-run.")
    return answer


def _session_for(view, answer):
    content = json.dumps({"result": json.dumps(view)})
    return {"id": "DRY-RUN", "messages": [
        {"role": "user", "content": "pilot dry-run"},
        {"role": "assistant", "tool_calls": [{"id": "d0", "function": {
            "name": VIEW_TOOL, "arguments": json.dumps({"scenario_id": SCENARIO_ID, "request_key": "dry-run"})}}]},
        {"role": "tool", "tool_call_id": "d0", "content": content},
        {"role": "assistant", "content": json.dumps(answer)}]}


def pilot_cases(sequence: dict, binding: dict, binding_record: dict) -> list[dict]:
    """Pure: one entry per pilot case with its fixed input digest, expected code result and evaluability."""
    import copy
    cases = []
    for case_id, kind, transform, description in PILOT_CASES:
        source = copy.deepcopy(sequence)
        if callable(transform):
            transform(source)
        view = (scenario_view({}, None, binding_record=binding_record, refused="ScenarioBindingError")
                if transform == "REFUSED" else scenario_view(source, binding, binding_record=binding_record))
        expected, _ = _expected_from_view(view)
        correct = accept_scenario_view_answer(_session_for(view, _correct_answer(view)))
        wrong_answer = {**_correct_answer(view), "r1_movement_authorized": True}
        wrong = accept_scenario_view_answer(_session_for(view, wrong_answer))
        cases.append({
            "case_id": case_id, "kind": kind, "description": description,
            "input_sha256": hashlib.sha256(json.dumps(
                {k: v for k, v in source.items() if k not in VOLATILE_SEQUENCE_KEYS}, sort_keys=True,
                default=str).encode()).hexdigest(),
            "view_sha256": hashlib.sha256(json.dumps(view, sort_keys=True).encode()).hexdigest(),
            "expected_code_result": {"view_status": view["status"], "scenario_status": expected["scenario_status"],
                                     "order_basis": expected["order_basis"], "r1_dependency": expected["r1_dependency"],
                                     "r1_movement_authorized": False},
            "critical_keys": list(CRITICAL_KEYS),
            "evaluable": correct["status"] == "STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED" and wrong["status"] == "NOT_VALIDATED",
            "evaluability_checks": {"correct_answer": correct["status"], "authorization_error": wrong["status"]},
            "servable_to_hermes": kind == "REAL",
            "serving_note": ("get_scenario_view over the real record" if kind == "REAL" else
                             "NOT servable with the existing mechanism: get_scenario_view reads real records only"),
        })
    return cases


def pilot_dry_run(request_key: str | None = None) -> dict:
    """Read-only: load the real H2 record and binding, build the cases and the execution plan. No inference."""
    request_key = request_key or H2_REQUEST_KEY
    path = PROJECT_ROOT / SCENARIOS[SCENARIO_ID]["binding_record"]
    record = {"path": SCENARIOS[SCENARIO_ID]["binding_record"], "sha256": digest(path.read_bytes())}
    binding = _bind_expected(*record_associations(path))
    sequence = get_preflight_sequence(request_key=request_key, detail=True)
    if sequence.get("job_state") != "FINISHED":
        return {"status": "NOT_READY", "reasons": [f"sequence {sequence.get('job_state')}"], "inference_executed": False}
    cases = pilot_cases(sequence, binding, record)
    return {"status": "PLAN_READY" if all(c["evaluable"] for c in cases) else "NOT_READY",
            "inference_executed": False, "cases": cases,
            "execution_plan": {
                "model_invocations": PILOT_REAL_REPETITIONS, "case": "real-h2",
                "trial_case": "agri-scenario-pilot-real",
                "per_invocation": "one isolated capture run (get_scenario_view only), review, accept-h3b",
                "synthetic_cases": "code-level only; model-level evaluation requires a separately reviewed fixture source",
                "requires": "explicit authorization; no retries; each timeout or failure is a result"}}


# --- Pilot report: every count is derived from the saved records and lists the keys that form it.
VALIDATED = "STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _model_requests(run_dir: Path) -> dict:
    """Logical model requests (one api_request_ref each) and their attempts, from the capture events.
    Hermes' main client has no SDK retry loop (max_retries=0 at d923a5eb); its app-level retries
    (agent.api_max_retries) and auto-recovery cycles appear as llm_error events of the same request."""
    events = []
    for path in sorted((run_dir / "capture").glob("hermes-events-*.jsonl")):
        events += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    requests = {}
    for event in sorted(events, key=lambda e: e.get("recorded_at_utc") or ""):
        if event.get("event_type") not in ("llm_call", "llm_error"):
            continue
        req = requests.setdefault(event.get("api_request_ref"), {"completed": False, "failed_attempts": []})
        if event["event_type"] == "llm_call":
            req["completed"] = True
        else:
            req["failed_attempts"].append({"error_type": event.get("error_type"), "reason": event.get("reason"),
                                           "status_code": event.get("status_code"),
                                           "retry_count": event.get("retry_count"),
                                           "max_retries": event.get("max_retries")})
    reqs = list(requests.values())
    return {"logical_requests_observed": len(reqs), "completed_requests": sum(r["completed"] for r in reqs),
            "failed_attempts": sum(len(r["failed_attempts"]) for r in reqs),
            # A failed attempt followed by another attempt of the same request is a client retry.
            "client_retries": sum(len(r["failed_attempts"]) - (0 if r["completed"] else 1)
                                  for r in reqs if r["failed_attempts"]),
            "requests": reqs}


def pilot_report(evidence_dir: Path, reeval_dir: Path | None = None) -> dict:
    """Read-only: per-key rows and counts of a saved pilot (no Hermes, no inference)."""
    protocol = _load_json(evidence_dir / "protocol.json") or {}
    amendment = _load_json(evidence_dir / "protocol_amendment_01.json") or {}
    frozen_view = (protocol.get("view") or {}).get("view_sha256_sort_keys")
    rows = []
    for key in protocol.get("planned_keys") or []:
        run_dir = evidence_dir / key
        if not run_dir.is_dir():
            rows.append({"key": key, "attempted": False})
            continue
        run = _load_json(run_dir / "run.json") or {}
        trial = (_load_json(run_dir / "capture_summary.json") or {}).get("mcp_tool_trial") or {}
        usage = _load_json(run_dir / "native_usage_reviewed.json")
        original = _load_json(run_dir / "accept_h3b.json")
        post_fix = _load_json(run_dir / "accept_h3b_post_fix.json")
        reeval = _load_json(reeval_dir / f"{key}.accept_h3b_reeval.json") if reeval_dir else None
        effective = post_fix or original
        received = _load_json(run_dir / "tool_result_as_received.json") or []
        view_digests = [hashlib.sha256(json.dumps(c.get("result"), sort_keys=True).encode()).hexdigest()
                        for c in received]
        rows.append({
            "key": key, "attempted": True, "started_at_utc": run.get("started_at_utc"),
            "after_amendment": bool(amendment.get("amended_at_utc") and run.get("started_at_utc")
                                    and run["started_at_utc"] > amendment["amended_at_utc"]),
            "elapsed_wall_s": run.get("elapsed_wall_s"), "timed_out": run.get("timed_out"),
            "return_code": run.get("return_code"), "restore_ok": (run.get("restore") or {}).get("ok"),
            "review_verdict": trial.get("verdict"), "offered": trial.get("offered"),
            "requested_tools": trial.get("requested_tool_names"),
            # Calls as Hermes recorded them; the received view is only known when the session was exported.
            "view_calls": sum(c.get("tool_name") == VIEW_TOOL for c in trial.get("tool_calls") or []),
            "view_matches_frozen": all(d == frozen_view for d in view_digests) if view_digests else None,
            **_model_requests(run_dir),
            "answer_received": original is not None,
            "acceptance_original": (original or {}).get("status") or ("EVALUATOR_ERROR" if original else None),
            "acceptance_post_fix": (post_fix or {}).get("status"),
            "acceptance_reeval": (reeval or {}).get("status"),
            "reeval_identical": None if reeval is None else reeval == effective,
            "acceptance": (effective or {}).get("status"),
            "parse": ((effective or {}).get("factual") or {}).get("parse"),
            "tool_execution": ((effective or {}).get("tool_execution") or {}).get("status"),
            "schema_failures": sorted(k for k in (effective or {}).get("failed_keys") or []
                                      if k not in CRITICAL_KEYS and k != "explanation"),
            "critical_failures": sorted(k for k in (effective or {}).get("failed_keys") or [] if k in CRITICAL_KEYS),
            "r1_movement_authorized": ((effective or {}).get("answer") or {}).get("r1_movement_authorized")
            if isinstance((effective or {}).get("answer"), dict) else None,
            "heuristic_flags": ((effective or {}).get("explanation_review") or {}).get("heuristic_flags"),
            "tokens": None if usage is None else {
                k: usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens",
                                          "total_tokens", "api_calls")},
            "estimated_cost_usd": None if usage is None else usage.get("estimated_cost_usd"),
            "cost_status": None if usage is None else usage.get("cost_status"),
        })
    done = [r for r in rows if r["attempted"]]
    answered = [r for r in done if r["answer_received"]]
    analysable = [r for r in answered if r["parse"] in ("JSON_OBJECT", "FENCED_JSON_OBJECT")]

    def keys(rows_, predicate):
        return [r["key"] for r in rows_ if predicate(r)]
    counts = {
        "planned": [r["key"] for r in rows], "attempted": keys(rows, lambda r: r["attempted"]),
        "answered": keys(done, lambda r: r["answer_received"]),
        "no_answer_technical": keys(done, lambda r: not r["answer_received"]),
        "structured_validated": keys(done, lambda r: r["acceptance"] == VALIDATED),
        "not_validated": keys(done, lambda r: r["acceptance"] == "NOT_VALIDATED"),
        "tool_not_called": keys(done, lambda r: r["view_calls"] == 0),
        "other_tool_requested": keys(done, lambda r: any(t != VIEW_TOOL for t in r["requested_tools"] or [])),
        "unparseable_answer": keys(answered, lambda r: r["parse"] not in ("JSON_OBJECT", "FENCED_JSON_OBJECT")),
        "schema_failures": keys(done, lambda r: r["schema_failures"]),
        "critical_failures": keys(done, lambda r: r["critical_failures"]),
        "analysable_answers": [r["key"] for r in analysable],
        "r1_movement_authorized_false": keys(analysable, lambda r: r["r1_movement_authorized"] is False),
        "heuristic_flags": keys(done, lambda r: r["heuristic_flags"]),
        "client_retries": keys(done, lambda r: r["client_retries"]),
        "timed_out": keys(done, lambda r: r["timed_out"]),
        "evaluator_error_original": keys(done, lambda r: r["acceptance_original"] == "EVALUATOR_ERROR"),
        "before_amendment": keys(done, lambda r: not r["after_amendment"]),
        "after_amendment": keys(done, lambda r: r["after_amendment"]),
        "tokens_unknown": keys(done, lambda r: r["tokens"] is None),
    }
    known = [r for r in done if r["tokens"]]
    return {"evidence": evidence_dir.name, "inference_executed": False, "rows": rows, "counts": counts,
            "denominators": {"structured_validated_of_attempted": f"{len(counts['structured_validated'])}/{len(done)}",
                             "structured_validated_of_answered": f"{len(counts['structured_validated'])}/{len(answered)}",
                             "r1_false_of_analysable": f"{len(counts['r1_movement_authorized_false'])}/{len(analysable)}"},
            "totals_known": {"total_tokens": sum(r["tokens"]["total_tokens"] or 0 for r in known),
                             "sessions_with_usage": len(known),
                             "elapsed_wall_s": round(sum(r["elapsed_wall_s"] or 0 for r in done), 3),
                             "estimated_cost_usd": sum(r["estimated_cost_usd"] or 0 for r in known)},
            "unknown": ["tokens, coste y vista recibida de las sesiones sin uso exportado ("
                        + ", ".join(counts["tokens_unknown"]) + ")",
                        "coste facturado y cuota del proveedor (Hermes solo informa una estimación)",
                        "temperatura, top_p y semilla (valores por defecto del proveedor, no expuestos)",
                        "peticiones en curso cuando el timeout terminó una invocación (no generan evento)",
                        "qué almacenó o reutilizó el proveedor más allá de cache_read_tokens"],
            "amendment": {"amended_at_utc": amendment.get("amended_at_utc"),
                          "driver_changes": amendment.get("driver_changes"), "unchanged": amendment.get("unchanged")}}


def render_pilot_report(report: dict) -> str:
    """Markdown tables of a pilot_report() result; no number is typed by hand."""
    def cell(value):
        return "—" if value in (None, [], "") else (", ".join(map(str, value)) if isinstance(value, list) else str(value))
    lines = [f"# Informe reproducible del piloto `{report['evidence']}`", "",
             "Generado por `reporting.agri_scenario_summary pilot-report` a partir de los registros guardados.",
             "Sin inferencias. Cada recuento enumera las claves que lo forman.", "",
             "## Denominadores", "", "| Medida | Valor |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in report["denominators"].items()]
    lines += ["", "## Recuentos y claves", "", "| Categoría | n | Claves |", "| --- | ---: | --- |"]
    lines += [f"| `{name}` | {len(ks)} | {cell([k.rsplit('-', 1)[-1] for k in ks])} |"
              for name, ks in report["counts"].items()]
    lines += ["", "## Por invocación", "",
              "| Clave | Periodo | s | Peticiones (completadas/observadas) | Intentos fallidos | Reintentos del cliente "
              "| Llamadas a la vista | Vista congelada | Formato | Esquema | Críticas | Aceptación original "
              "| Tras corrección | Reevaluación idéntica | Tokens totales | Caché leída |",
              "| --- | --- | ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: |"]
    for r in report["rows"]:
        if not r["attempted"]:
            lines.append(f"| {r['key']} | no intentada |" + " — |" * 14)
            continue
        tokens = r["tokens"] or {}
        lines.append("| " + " | ".join(cell(v) for v in (
            r["key"], "tras enmienda" if r["after_amendment"] else "antes de enmienda", r["elapsed_wall_s"],
            f"{r['completed_requests']}/{r['logical_requests_observed']}", r["failed_attempts"], r["client_retries"],
            r["view_calls"], r["view_matches_frozen"], r["parse"], r["schema_failures"], r["critical_failures"],
            r["acceptance_original"], r["acceptance_post_fix"], r["reeval_identical"],
            tokens.get("total_tokens"), tokens.get("cache_read_tokens"))) + " |")
    lines += ["", "## Errores del cliente por invocación", ""]
    for r in report["rows"]:
        for i, req in enumerate(r.get("requests") or []):
            for attempt in req["failed_attempts"]:
                lines.append(f"- {r['key']}, petición {i + 1}: `{attempt['error_type']}` ({attempt['reason']}, "
                             f"HTTP {cell(attempt['status_code'])}, retry_count {attempt['retry_count']}, "
                             f"max_retries {attempt['max_retries']})")
    totals = report["totals_known"]
    lines += ["", "## Tiempos, tokens y coste conocidos", "",
              f"- Tokens totales en {totals['sessions_with_usage']} sesiones con uso registrado: {totals['total_tokens']}.",
              f"- Duración total de las invocaciones (sin pausas): {totals['elapsed_wall_s']} s.",
              f"- Coste estimado por Hermes: {totals['estimated_cost_usd']} USD (estimación, no facturación).",
              "", "## Datos desconocidos", ""]
    lines += [f"- {item}" for item in report["unknown"]]
    amendment = report["amendment"]
    lines += ["", "## Enmienda del driver", "", f"Registrada a las {cell(amendment['amended_at_utc'])} (UTC).",
              f"Cambió: {cell(amendment['driver_changes'])}.", f"Permaneció fijo: {cell(amendment['unchanged'])}.",
              "Los periodos se separan por la hora de inicio de cada invocación; no se atribuye ningún resultado a la enmienda.",
              ""]
    return "\n".join(lines)


def render_explanation_sheet(evidence_dir: Path, observations: dict) -> str:
    """Human review sheet: literal explanations with file/hash references, assisted observations per
    criterion, and EMPTY reviewer columns. The model output and the deterministic report are not mixed."""
    criteria = observations["criteria"]
    protocol = _load_json(evidence_dir / "protocol.json") or {}
    lines = [f"# Hoja de revisión de explicaciones — `{evidence_dir.name}`", "",
             "**Revisión humana: PENDIENTE.** Las columnas «Valoración» y «Nota» están vacías a propósito.", "",
             "- **Texto literal:** campo `explanation` de la aceptación efectiva o, si la respuesta no se pudo",
             "  analizar, la salida completa de Hermes. Nunca se corrige.",
             "- **Referencias:** archivo y SHA-256 de donde procede cada texto.",
             "- **Hechos:** la vista recibida (`tool_result_as_received.json`). El informe determinista",
             "  (`agri_scenario_report_h2_2026_10_24`) los presenta generados por código.",
             f"- **Observaciones asistidas:** {observations['label']}",
             "- La revisión asistida de H3b no se reutiliza aquí.", "",
             "Valores sugeridos para «Valoración»: `CORRECTO`, `INCOMPLETO`, `AMBIGUO`, `INCORRECTO`, `NO MENCIONA`.", ""]
    for key in protocol.get("planned_keys") or []:
        run_dir = evidence_dir / key
        source = run_dir / ("accept_h3b_post_fix.json" if (run_dir / "accept_h3b_post_fix.json").exists()
                            else "accept_h3b.json")
        accepted = _load_json(source)
        answer = (accepted or {}).get("answer")
        explanation = answer.get("explanation") if isinstance(answer, dict) else None
        stdout = run_dir / "hermes_stdout.txt"
        lines += [f"## {key}", ""]
        if accepted is None and not (stdout.exists() and stdout.stat().st_size):
            lines += ["Sin respuesta del modelo: no hay explicación que revisar.", ""]
            continue
        if isinstance(explanation, str):
            lines += [f"Referencia: `{key}/{source.name}` (SHA-256 `{digest(source.read_bytes())[:16]}…`), "
                      f"campo `answer.explanation`. Estado automático: `{accepted.get('status')}`.", "", "Explicación literal:", ""]
            lines += ["> " + line if line else ">" for line in explanation.splitlines()]
        else:
            lines += [f"Referencia: `{key}/hermes_stdout.txt` (SHA-256 `{digest(stdout.read_bytes())[:16]}…`); "
                      f"la respuesta no se pudo analizar (`{((accepted or {}).get('factual') or {}).get('parse')}`). "
                      f"Estado automático: `{(accepted or {}).get('status')}`.", "", "Salida literal completa:", "",
                      "~~~~text", *stdout.read_text(encoding="utf-8").splitlines(), "~~~~"]
        flags = ((accepted or {}).get("explanation_review") or {}).get("heuristic_flags")
        lines += ["", f"Avisos heurísticos automáticos (no validación semántica): {', '.join(flags) if flags else 'ninguno'}.",
                  "", "| Criterio | Observación asistida (preliminar) | Valoración (pendiente) | Nota (pendiente) |",
                  "| --- | --- | --- | --- |"]
        notes = observations["observations"].get(key, {})
        lines += [f"| {label} | {notes.get(name, '—')} |  |  |" for name, label in criteria.items()]
        lines += ["", "Revisor: ________  Fecha: ________", ""]
    return "\n".join(lines)


BINDING_RECORD_SCHEMA = "tfg.agri-demo-h1-binding/1"
H2_ORDER = ("drone_01", "drone_02")  # drone_01 -> v1 first, then drone_02 -> v2
H2_REQUEST_KEY = "agri-demo-001-h2-r01"


def record_associations(record_path) -> tuple[dict[str, dict], dict[str, str]]:
    """(associations, expected SHA-256) from a reviewed H1 evidence ``h1_binding.json``."""
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    if record.get("schema") != BINDING_RECORD_SCHEMA or record.get("status") != "BOUND":
        raise ScenarioBindingError("Not a BOUND agri_demo_001 H1 binding record")
    artifacts = record.get("artifacts") or {}
    if sorted(artifacts) != sorted(REFERENCE):
        raise ScenarioBindingError("Binding record must name exactly one artifact per declared drone")
    associations = {v: {"mission_path": str(PROJECT_ROOT / a["mission_path"]),
                        "waypoint_by_point": a["waypoint_by_point"]} for v, a in artifacts.items()}
    return associations, {v: a["mission_sha256"] for v, a in artifacts.items()}


def _bind_expected(associations, expected_sha256):
    binding = bind_scenario(associations)
    changed = sorted(v for v, sha in (expected_sha256 or {}).items() if binding[v]["mission_sha256"] != sha)
    if changed:
        raise ScenarioBindingError(f"Artifact content differs from the recorded hash: {changed}")
    return binding


def check_h2(record_path, *, request_key: str = H2_REQUEST_KEY) -> dict:
    """Read-only H2 precheck of the bound H1 artifacts: binding, ordered sequence inputs and an unused
    request key. Creates no admission, reservation, job or process; returns the call NOT executed."""
    from tools import preflight_sequences as seq
    result = {"status": "NOT_READY", "reasons": [], "flight_authorization": "NOT_GRANTED",
              "admission_created": False, "fallback_to_h0": False}
    try:
        associations, expected = record_associations(record_path)
        binding = _bind_expected(associations, expected)
        paths = [associations[v]["mission_path"] for v in H2_ORDER]
        values, _ = seq._inputs(paths, "read-only input check; not an authorization")  # admission's own checks
        if [v[2] for v in values] != [{"vehicle_id": "drone_01", "simulated_vehicle": "v1"},
                                      {"vehicle_id": "drone_02", "simulated_vehicle": "v2"}]:
            raise ScenarioBindingError("Sequence order must be drone_01 -> v1, then drone_02 -> v2")
        if seq.request_path(request_key).exists():
            raise ScenarioBindingError(f"request_key {request_key} already names a sequence; never reuse it")
    except (ScenarioBindingError, ValueError, OSError, KeyError, TypeError) as exc:
        result["reasons"].append(str(exc))
        return result
    call = ("import json; from tools.preflight_sequences import start_preflight_sequence as start; "
            f"print(json.dumps(start({paths!r}, {request_key!r}, '<DECLARACION_DEL_OPERADOR>'), indent=2))")
    result.update(status="READY_FOR_OPERATOR_DECISION", request_key=request_key,
                  ordered_missions=[{"vehicle_id": v, "simulated_vehicle": s["simulated_vehicle"],
                                     "mission_path": p, "mission_sha256": binding[v]["mission_sha256"],
                                     "waypoint_by_point": binding[v]["waypoint_by_point"]}
                                    for v, p, (_, _, s) in zip(H2_ORDER, paths, values)],
                  prepared_start_call_NOT_EXECUTED=f'.venv/bin/python -c "{call}"')
    return result


def summarize_sequence(sequence_id: str | None, associations: dict[str, dict], *,
                       expected_sha256: dict[str, str] | None = None, request_key: str | None = None) -> dict:
    """Bind the scenario artifacts, read the sequence through its verified query, then interpret it."""
    try:
        binding = _bind_expected(associations, expected_sha256)
    except (ScenarioBindingError, ValueError, OSError, TypeError) as exc:
        return {"scenario_id": SCENARIO_ID, "status": "UNKNOWN", "scenario_complete": False,
                "sequence": {"sequence_id": sequence_id}, "binding": None, "missions": [], "points": {},
                "ground_task": {**GROUND_TASK, "status": "BLOCKED_PENDING", "dependency": "UNKNOWN",
                                "barriers": list(ROVER_BARRIERS), "commands_sent": False},
                "reasons": [f"Scenario binding refused: {exc}"], "scope": dict(SCOPE)}
    view = (get_preflight_sequence(request_key=request_key, detail=True) if request_key is not None
            else get_preflight_sequence(sequence_id=sequence_id, detail=True))
    return summarize_scenario(view, binding)


def main(argv=None, *, out=None, runner=subprocess.run) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="agri_demo_001 artifact binding (no flight authorization)")
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind-h1", help="bind the missions finalized in one H1 Hermes turn")
    bind.add_argument("--usage-file", type=Path, required=True, help="that turn's native-usage.json")
    bind.add_argument("--hermes-bin", type=Path, default=None)
    check = sub.add_parser("check-h2", help="read-only H2 precheck of a BOUND h1_binding.json; admits nothing")
    check.add_argument("--binding-record", type=Path, required=True)
    check.add_argument("--request-key", default=H2_REQUEST_KEY)
    summ = sub.add_parser("summarize", help="read-only scenario summary of one finished or running sequence")
    summ.add_argument("--binding-record", type=Path, required=True)
    which = summ.add_mutually_exclusive_group(required=True)
    which.add_argument("--sequence-id")
    which.add_argument("--request-key")
    accept = sub.add_parser("accept-h3", help="accept one H3 Hermes turn against its session and the H2 summary")
    accept.add_argument("--usage-file", type=Path, required=True)
    accept.add_argument("--summary", type=Path, required=True, help="the saved H2 scenario_summary.json")
    accept.add_argument("--run-id", action="append", required=True, help="each queried child run_id, in order")
    accept.add_argument("--hermes-bin", type=Path, default=None)
    accept_b = sub.add_parser("accept-h3b", help="accept one H3b turn against the scenario view it received")
    accept_b.add_argument("--usage-file", type=Path, required=True)
    accept_b.add_argument("--hermes-bin", type=Path, default=None)
    view = sub.add_parser("view", help="print the read-only historical scenario view (no Hermes)")
    view.add_argument("--scenario-id", default=SCENARIO_ID)
    which_view = view.add_mutually_exclusive_group(required=True)
    which_view.add_argument("--request-key")
    which_view.add_argument("--sequence-id")
    sub.add_parser("pilot-dry-run", help="list pilot cases, check evaluability and print the plan (no inference)")
    pilot = sub.add_parser("pilot-report", help="counts and per-key table of a saved pilot (no inference)")
    pilot.add_argument("--evidence-dir", type=Path, required=True)
    pilot.add_argument("--reeval-dir", type=Path, default=None)
    pilot.add_argument("--json", action="store_true", help="print the structured result instead of Markdown")
    r1 = sub.add_parser("r1-dry-run", help="R1 preparation over the historical view: stages, blockers, missing data")
    r1.add_argument("--request-key", default=H2_REQUEST_KEY)
    r1.add_argument("--capture-trial-root", type=Path, default=None,
                    help="finished passive capture (manifest-verified) whose observations go to measured_facts")
    r1.add_argument("--capture-dir", default=None, help="capture directory relative to --capture-trial-root")
    r1.add_argument("--identity-trial-root", type=Path, default=None, help="closed identity session (facts only)")
    sheet = sub.add_parser("pilot-review-sheet", help="Markdown review sheet of a saved pilot's explanations")
    sheet.add_argument("--evidence-dir", type=Path, required=True)
    sheet.add_argument("--observations", type=Path, required=True, help="assisted observations by criterion")
    report = sub.add_parser("report", help="deterministic Markdown report of a saved view file (no Hermes)")
    report.add_argument("--view-file", type=Path, required=True)
    report.add_argument("--ground", action="store_true", help="append the task/R1 section (real executor facts)")
    report.add_argument("--r1-record", type=Path, default=None, help="an R1 coordination record (JSON)")
    report.add_argument("--capture-trial-root", type=Path, default=None,
                        help="finished passive capture (manifest-verified) for the R1 measured facts")
    report.add_argument("--capture-dir", default=None, help="capture directory relative to --capture-trial-root")
    report.add_argument("--identity-trial-root", type=Path, default=None, help="closed identity session (facts only)")
    args = parser.parse_args(argv)
    if args.command == "pilot-dry-run":
        result = pilot_dry_run()
        json.dump(result, out, indent=2, ensure_ascii=False)
        out.write("\n")
        return 0 if result["status"] == "PLAN_READY" else 3
    if args.command == "pilot-report":
        result = pilot_report(args.evidence_dir, args.reeval_dir)
        out.write((json.dumps(result, indent=2, ensure_ascii=False) if args.json else render_pilot_report(result)) + "\n")
        return 0
    if args.command == "r1-dry-run":
        view_doc = get_scenario_view(SCENARIO_ID, request_key=args.request_key)
        from tools.agri_ground_coordinator import RoverGroundExecutorAdapter  # current executor facts, read-only
        result = prepare_ground_task(view_doc, executor_facts=RoverGroundExecutorAdapter().facts(),
                                     capture=_capture_arg(args), identity=_identity_arg(args))
        json.dump(result, out, indent=2, ensure_ascii=False)
        out.write("\n")
        return 0
    if args.command == "pilot-review-sheet":
        observations = json.loads(args.observations.read_text(encoding="utf-8"))
        out.write(render_explanation_sheet(args.evidence_dir, observations) + "\n")
        return 0
    if args.command == "report":
        view_doc = json.loads(args.view_file.read_text(encoding="utf-8"))
        out.write(render_scenario_report(view_doc) + "\n")
        if args.ground or args.r1_record or args.capture_trial_root or args.identity_trial_root:
            record = json.loads(args.r1_record.read_text(encoding="utf-8")) if args.r1_record else None
            from tools.agri_ground_coordinator import RoverGroundExecutorAdapter  # current executor facts, read-only
            prepared = prepare_ground_task(view_doc, executor_facts=RoverGroundExecutorAdapter().facts(),
                                           capture=_capture_arg(args), identity=_identity_arg(args))
            out.write("\n" + render_ground_report(view_doc, prepared, record) + "\n")
        return 0 if view_doc.get("status") == "OK" else 3
    if args.command == "view":
        result = get_scenario_view(args.scenario_id, request_key=args.request_key, sequence_id=args.sequence_id)
        code = 0 if result["status"] == "OK" else 3
    elif args.command == "accept-h3b":
        result = accept_h3b_turn(args.usage_file, hermes_bin=args.hermes_bin, runner=runner)
        code = 0 if result["status"] == "STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED" else 3
    elif args.command == "accept-h3":
        result = accept_h3_turn(args.usage_file, args.summary, args.run_id, hermes_bin=args.hermes_bin, runner=runner)
        code = 0 if result["status"] == "VALIDATED" else 3
    elif args.command == "bind-h1":
        result = bind_planning_turn(args.usage_file, hermes_bin=args.hermes_bin, runner=runner)
        code = 0 if result["status"] == "BOUND" else 3
    elif args.command == "check-h2":
        result = check_h2(args.binding_record, request_key=args.request_key)
        code = 0 if result["status"] == "READY_FOR_OPERATOR_DECISION" else 3
    else:
        try:
            associations, expected = record_associations(args.binding_record)
        except (ScenarioBindingError, ValueError, OSError, KeyError) as exc:
            associations, expected = {}, None
            print(f"agri_scenario_summary: {exc}", file=sys.stderr)
        result = summarize_sequence(args.sequence_id, associations, expected_sha256=expected,
                                    request_key=args.request_key)
        code = 0
    json.dump(result, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
