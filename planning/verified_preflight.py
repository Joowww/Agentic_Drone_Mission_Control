"""Read final evidence and its exact snapshot without trusting embedded paths."""
import json

from models.mission_definition import MissionDefinition
from planning.artifact_store import identifier, sha256
from reporting.virtual_preflight_analysis import analyze_executor_result
from tools.hermes_mission_validation import validate_mission
from tools.virtual_preflight_jobs import TERMINAL, locate_preflight_report
from tools.simulated_vehicle import recorded_report_selection, resolve_mission_vehicle


def verified_source(run_id):
    identifier(run_id)
    _, report_path = locate_preflight_report(run_id)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    if not isinstance(report, dict):
        raise ValueError("Invalid report object")
    for key in ("mission_identity", "validation", "readiness", "analysis", "executor_result"):
        if report.get(key) is not None and not isinstance(report[key], dict):
            raise ValueError(f"Invalid {key} evidence object")
    if (report.get("run_id") != run_id or report.get("status") not in TERMINAL
            or not report.get("finished_at") or report.get("report_persisted") is not True):
        raise ValueError("A consistent final persisted report is required")
    if report_path.name == "report.json":
        mission_path = report_path.with_name("mission.json")
    else:
        mission_path = report_path.with_name(report_path.name.replace("_report.json", "_mission.json"))
    if not mission_path.resolve().is_relative_to(report_path.parent.resolve()):
        raise ValueError("Snapshot escapes report directory")
    mission_bytes = mission_path.read_bytes()
    digest = sha256(mission_bytes)
    if digest != report.get("mission_sha256") or report.get("expected_sha256", digest) != digest:
        raise ValueError("Mission snapshot hash mismatch")
    mission = MissionDefinition.model_validate_json(mission_bytes)
    selected = recorded_report_selection(report)
    strict = report.get("schema_version") == "1.1"
    if strict and selected is not None and selected != resolve_mission_vehicle(mission).as_dict():
        raise ValueError("Report vehicle differs from snapshot")
    if mission.mission_id != (report.get("mission_identity") or {}).get("mission_id"):
        raise ValueError("Mission identity mismatch")
    validation = validate_mission(mission)
    saved = report.get("validation")
    if saved is not None and (saved.get("mission_id") != mission.mission_id
                  or saved.get("mission_status") != validation["mission_status"]
                  or saved.get("execution_status") != validation["execution_status"]):
        raise ValueError("Saved validation contradicts the snapshot")
    raw = report.get("executor_result")
    if raw and (raw.get("mission_id", mission.mission_id) != mission.mission_id
                or raw.get("vehicle", "v1") != (selected or {}).get("simulated_vehicle", "v1")):
        raise ValueError("Executor identity mismatch")
    status = report["status"]
    if status in {"PASSED", "FAILED"}:
        actual = analyze_executor_result(mission, raw, require_vehicle_identity=strict, legacy_v1=not strict)
        if (report.get("execution_attempted") is not True
                or (report.get("analysis") or {}).get("passed") is not (status == "PASSED")
                or actual["passed"] is not (status == "PASSED")):
            raise ValueError("Final report contradicts executor evidence")
        if report["analysis"] != actual:
            raise ValueError("Saved analysis contradicts recomputed executor evidence")
        if status == "PASSED" and validation["execution_status"] != "APPROVED":
            raise ValueError("PASSED mission is unsafe")
    elif status == "BLOCKED":
        stage = report.get("stage")
        valid_block = (
            stage == "snapshot" and bool(report.get("reasons")) and selected is None
            or stage == "validate" and validation["execution_status"] != "APPROVED"
            or stage == "check_readiness" and (report.get("readiness") or {}).get("ready") is False
            or stage == "compatibility" and bool(report.get("compatibility_errors"))
            or stage == "analyze" and isinstance(raw, dict) and raw.get("status") == "BLOCKED"
            and not raw.get("events") and not raw.get("recovery")
        )
        if stage != "analyze" and (report.get("execution_attempted") is not False or raw is not None):
            valid_block = False
        if not valid_block:
            raise ValueError("BLOCKED report lacks a consistent blocking reason")
    return {"report": report, "mission": mission, "validation": validation,
            "mission_bytes": mission_bytes, "report_bytes": report_bytes,
            "mission_sha256": digest, "report_sha256": sha256(report_bytes),
            "report_path": str(report_path), "mission_path": str(mission_path)}
