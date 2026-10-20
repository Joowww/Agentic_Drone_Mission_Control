"""Pure projections of already-checked results. Never load files or invoke a workflow.

Detail remains the source response. Summary removes repeated payloads, not errors,
validation/reason lists, identity links or checks. No fixed-size truncation is used.
"""
from collections import Counter
from copy import deepcopy
from typing import Literal

ResponseView = Literal["summary", "detail"]

SEMANTICS = {
    "scope": "SITL requires explicit rehearsal consent, not hardware authorization; hardware_authorized=false does not block SITL",
    "recommendations": "Advisory proposals are not additional technical gates; physical intervention text is not a hardware requirement for a declared simulated scenario",
    "evidence": "PASSED applies to its simulated snapshot; it does not establish the cause or resolution of the earlier WP3 failure",
    "exports": "qgc_plan_path=null records no export in that operation, not absence of earlier exports; missing links remain unknown",
}


def _take(value, keys):
    return {key: deepcopy(value[key]) for key in keys if key in value}


def _non_null(value):
    return {key: deepcopy(item) for key, item in value.items() if item is not None}


def _access(tool, **arguments):
    return {"tool": tool, "arguments": {**arguments, "view": "detail"}}


def _errors(value, path=""):
    """Return complete errors as [{path: JSON Pointer in original, value: ...}].

    The empty result is []; values retain their original JSON types. Do not
    truncate, flatten error objects or interpret their truth as flight evidence.
    """
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            location = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if key in {"error", "errors", "failure_reasons", "reasons"} and item:
                result.append({"path": location, "value": deepcopy(item)})
            else:
                result.extend(_errors(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_errors(item, path + "/" + str(index)))
    return result


def _draft(value):
    result = _take(value, ("status", "draft_id", "draft_revision", "draft_sha256", "path",
                           "geometry_revision", "provenance_status", "stored_provenance_status",
                           "compatibility_defaults"))
    draft = value["draft"]
    result["mission_facts"] = _non_null({key: draft.get(key) for key in (
        "mission_id", "name", "vehicle_id", "vehicle_type", "autopilot", "objective_type",
        "objective_target", "battery_percent", "return_to_home")})
    geometry = value.get("geometry", {})
    result["geometry"] = {"status": geometry.get("status", "UNKNOWN"),
                          "intent": _non_null(value["geometry_intent"]) if value.get("geometry_intent") else None,
                          "waypoint_count": len(draft.get("waypoints", [])),
                          "method": (value.get("route_provenance") or {}).get("method")}
    result["source_counts"] = dict(Counter(entry.get("source", "UNKNOWN")
                                           for entry in value.get("field_provenance", {}).values()))
    result["detail_access"] = _access("get_mission_state", draft_id=value["draft_id"])
    return result


def _artifact(value):
    result = _take(value, ("kind", "status", "finalization_id", "revision_id", "draft_id", "draft_revision",
                           "geometry_revision", "draft_sha256", "draft_state_sha256", "mission_path",
                           "mission_sha256", "record_path", "record_sha256", "integrity", "validation",
                           "qgc_plan_sha256", "matches_current_draft", "proposal_id", "proposal_sha256",
                           "source_run_id", "source_report_sha256", "source_mission_sha256", "flight_consent",
                           "pending_conditions", "declarations", "created_at"))
    # Snapshot provenance and full structured diffs remain accessible by ID.
    if "differences" in value:
        result["changed_paths"] = [entry["path"] for entry in value["differences"]]
    if "explicit_changes" in value:
        result["scalar_changes"] = {key: deepcopy(item) for key, item in value["explicit_changes"].items()
                                    if item is not None and not isinstance(item, (list, dict))}
    result["detail_access"] = (_access("get_mission_state", revision_id=value["revision_id"])
                               if "revision_id" in value else _access("get_mission_state", draft_id=value["draft_id"],
                                                                      finalization_id=value["finalization_id"]))
    return result


def _execution(raw):
    if not isinstance(raw, dict):
        return deepcopy(raw)
    result = _take(raw, ("status", "success", "stage", "mission_id", "vehicle", "vehicle_id", "error", "errors",
                        "waypoints_completed", "return_to_home", "recovery", "waypoint_diagnostic", "message",
                        "control_outcome", "controls_not_attempted"))
    diagnostic = raw.get("operation_diagnostics")
    if isinstance(diagnostic, dict):
        buckets = (diagnostic.get("initial", []), diagnostic.get("recent", []))
        if not all(isinstance(bucket, list) for bucket in buckets):
            # Malformed diagnostics remain visible; summary must not hide them or raise.
            result["operation_diagnostics"] = deepcopy(diagnostic)
            buckets = ([], [])
        else:
            result["operation_diagnostics"] = _take(diagnostic, ("clock", "simulated_time_inferred",
                                                                "total_operations", "omitted_operations"))
        result["operation_diagnostics"]["failed_operations"] = [
            _take(op, ("operation", "stage", "vehicle", "vehicle_id", "endpoint_kind", "endpoint",
                       "started_at_utc", "finished_at_utc", "elapsed_wall_seconds", "timeout_seconds",
                       "inner_timeout_seconds", "return_code", "attempted", "confirmed", "effects", "error"))
            for op in [*buckets[0], *buckets[1]]
            if isinstance(op, dict) and op.get("error")]
    events = raw.get("events")
    if isinstance(events, list):
        result["event_count"] = len(events)
        result["reached_waypoint_ids"] = [e.get("waypoint_id") for e in events
                                           if isinstance(e, dict) and e.get("event") == "WAYPOINT_REACHED"
                                           and e.get("reached") is True]
        result["landing_evidence"] = [_take(e, ("event", "landed", "armed", "flying")) for e in events
                                      if isinstance(e, dict) and e.get("event") == "LANDED"]
        result["failed_events"] = [deepcopy(e) for e in events if isinstance(e, dict)
                                    and (e.get("success") is False or e.get("reached") is False)]
    result["error_evidence"] = _errors(raw)
    return result


def _report(value):
    if not isinstance(value, dict):
        return deepcopy(value)
    result = _take(value, ("run_id", "status", "stage", "report_persisted", "mission_identity", "mission_sha256", "vehicle_selection",
                           "expected_sha256", "source_artifact", "execution_attempted", "validation",
                           "readiness", "compatibility_errors", "analysis", "reasons", "started_at", "finished_at",
                           "execution_started_at", "execution_finished_at", "scope", "hardware_authorized",
                           "subsequent_execution_authorized", "replan_proposals"))
    result["executor_result"] = _execution(value.get("executor_result"))
    return result


def summarize_preflight(value):
    if value.get("job_state") in {"ERROR", "NOT_FOUND"}:
        return deepcopy(value)
    result = _take(value, ("run_id", "request_key", "admission_status", "job_state", "phase", "result_status",
                           "mission_sha256", "worker_alive", "worker", "worker_error", "created_at", "worker_started_at",
                           "worker_finished_at", "paths", "vehicle_restriction", "message", "source_artifact",
                           "snapshot_integrity", "readiness_now", "readiness_scope", "result_scope",
                           "vehicle_selection", "vehicle_selection_basis", "global_flight_restriction",
                           "sequence_id", "sequence_index"))
    result["report"] = _report(value.get("report"))
    if value.get("run_id"):
        result["detail_access"] = _access("get_virtual_preflight", run_id=value["run_id"])
    elif value.get("request_key"):
        result["detail_access"] = _access("get_virtual_preflight", request_key=value["request_key"])
    return {**result, "view": "summary", "summary_schema_version": 1,
            "error_evidence": _errors(value), "interpretation": deepcopy(SEMANTICS)}


def summarize_proposal(value):
    if value.get("status") != "PROPOSED":
        return deepcopy(value)
    result = _take(value, ("status", "proposal_id", "proposal_sha256", "proposal_path"))
    proposal = value["proposal"]
    result["proposal"] = _take(proposal, ("proposal_id", "version", "created_at", "run_id", "mission_id", "category",
        "mission_sha256", "report_sha256", "source_mission_path", "source_report_path", "reasons", "proposed_changes",
        "pending_conditions", "automatic_patch", "diagnostic", "replanner_scope", "flight_consent"))
    result["proposal"]["execution_evidence"] = _execution(proposal.get("execution_evidence"))
    return {**result, "view": "summary", "summary_schema_version": 1,
            "detail_access": _access("get_revision_proposal", proposal_id=value["proposal_id"]),
            "error_evidence": _errors(value), "interpretation": deepcopy(SEMANTICS)}


def summarize_mission_state(value, anchor):
    if value.get("status") not in {"KNOWN", "KNOWN_WITH_WARNINGS"}:
        return deepcopy(value)  # No clipping or reinterpretation of errors/unknown states.
    result = _take(value, ("status", "missing_fields", "warnings", "pending", "next_actions", "readiness_now",
                           "consent", "hardware_authorized", "limits"))
    result["draft"] = _draft(value["draft"]) if value.get("draft") else None
    result["linked_drafts"] = [_draft(draft) for draft in value.get("linked_drafts", [])]
    for short, full in zip(result["linked_drafts"], value.get("linked_drafts", [])):
        short["pending"] = deepcopy(full.get("pending"))
    # Revisions already present in artifacts are represented only once.
    records = {entry.get("revision_id") or entry["finalization_id"]: entry for entry in value.get("artifacts", [])}
    for entry in value.get("revisions", []):
        records.setdefault(entry["revision_id"], entry)
    result["artifacts"] = [_artifact(entry) for entry in records.values()]
    result["revisions"] = [{"revision_id": entry["revision_id"], "artifact_ref": entry["revision_id"]}
                            for entry in value.get("revisions", [])]
    result["preflights"] = [summarize_preflight(run) for run in value.get("preflights", [])]
    result["proposals"] = [summarize_proposal(proposal) for proposal in value.get("proposals", [])]
    # Interpretation is shared rather than repeated for every nested entry.
    for entry in result["preflights"] + result["proposals"]:
        entry.pop("interpretation", None)
    notices = {draft["provenance_notice"] for draft in [value.get("draft"), *value.get("linked_drafts", [])]
               if draft and draft.get("provenance_notice")}
    return {**result, "view": "summary", "summary_schema_version": 1,
            "provenance_notices": sorted(notices), "error_evidence": _errors(value),
            "detail_access": _access("get_mission_state", **anchor), "interpretation": deepcopy(SEMANTICS)}
