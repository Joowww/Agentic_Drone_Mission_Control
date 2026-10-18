"""Offline summary/detail contract, with real artifact checks and immutable evidence."""
import asyncio
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from tests.test_mission_state import storage, finalized, tree
import tools.hermes_mcp_server as server
import tools.mission_state as state
import tools.mission_response_views as views
import tools.virtual_preflight_jobs as jobs
import planning.mission_revisions as revisions
import tools.hermes_mission_planning as drafts
from tools.vehicle_execution_lock import restriction

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "simulation/ros2_gazebo/results/hermes_conversational_2026_10_18"
FAILED = "d4519cab-ebd1-4359-b547-44be38294a6a"
PASSED = "f5f55084-5af6-4e58-ab1a-ce30a13832b3"
PROPOSALS = [
    ("727082c5-4008-4bf2-a61e-87b48eed35a8", "PLANNING_REVIEW"),
    ("e44903a2-0405-4ea5-99c7-7233ce0ea333", "INVESTIGATE_EXECUTION"),
    ("ae3bf4c2-3a56-4402-89b9-020e6232d5cf", "NO_CORRECTION_REQUIRED"),
    ("4bff56e2-48c9-421f-b8b6-1969aa5ddf74", "INFRASTRUCTURE_PENDING"),
]


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def test_summary_and_detail_keep_checks_semantics_and_queries_are_read_only(storage, monkeypatch):
    final = finalized()
    before = tree(storage[0])
    monkeypatch.setattr(drafts, "validate_mission_file", Mock(side_effect=AssertionError("No revalidation")))
    full = state.get_mission_state(draft_id=final["draft_id"])
    assert "view" not in full  # Python default retains old response.
    assert state.get_mission_state(draft_id=final["draft_id"], view="detail") == full
    assert server.get_mission_state(draft_id=final["draft_id"], view="detail") == full
    short = server.get_mission_state(draft_id=final["draft_id"])
    assert short == state.get_mission_state(draft_id=final["draft_id"], view="summary")
    assert short["view"] == "summary" and short["summary_schema_version"] == 1
    for key in ("status", "warnings", "missing_fields", "pending", "next_actions", "consent", "readiness_now", "limits"):
        assert short[key] == full[key]
    for key in ("draft_id", "draft_revision", "draft_sha256"):
        assert short["draft"][key] == full["draft"][key]
    for key in ("validation", "integrity", "mission_sha256", "record_sha256", "qgc_plan_sha256", "matches_current_draft"):
        assert short["artifacts"][0][key] == full["artifacts"][0][key]
    assert short["draft"]["source_counts"]
    assert "field_provenance" not in short["draft"] and "draft" not in short["draft"]
    assert "field_provenance" not in short["artifacts"][0]
    assert size(short) < .7 * size(full)
    assert short["detail_access"]["arguments"] == {"draft_id": final["draft_id"], "view": "detail"}
    assert tree(storage[0]) == before and restriction() is None
    storage[1].assert_not_called()


@pytest.mark.parametrize("damage", ["mission", "plan", "source_state"])
def test_both_views_refuse_the_same_corrupt_artifacts_without_repair(storage, damage):
    final = finalized()
    path = Path(final["mission_path"])
    target = (path if damage == "mission" else Path(final["validation"]["qgc_plan_path"])
              if damage == "plan" else path.with_name("source_draft_state.json"))
    target.write_text("{}")
    before = tree(storage[0])
    full = state.get_mission_state(draft_id=final["draft_id"], view="detail")
    short = state.get_mission_state(draft_id=final["draft_id"], view="summary")
    assert full == short and full["status"] == "ERROR" and full["errors"]
    assert tree(storage[0]) == before and restriction() is None
    storage[1].assert_not_called()


def test_argument_errors_and_missing_identifiers_are_not_hidden(storage):
    for args in ({}, {"run_id": "invented"}, {"run_id": FAILED, "draft_id": "also-invented"}):
        assert state.get_mission_state(**args, view="summary") == state.get_mission_state(**args, view="detail")
    assert state.get_mission_state(view="summary")["inventory_status"] == "UNKNOWN"
    assert state.get_mission_state(view="other")["error_code"] == "INVALID_ARGUMENTS"
    assert not jobs.RUN_ROOT.exists()


@pytest.mark.parametrize("run_id", [FAILED, PASSED])
def test_historical_report_preserves_result_analysis_recovery_and_actual_readiness(storage, run_id):
    before = tree(storage[0])
    full = server.get_virtual_preflight(run_id=run_id, view="detail")
    short = server.get_virtual_preflight(run_id=run_id)
    assert full == jobs.get_virtual_preflight(run_id=run_id)
    for key in ("job_state", "result_status", "phase", "mission_sha256", "vehicle_restriction", "paths"):
        assert short[key] == full[key]
    for key in ("validation", "reasons", "analysis", "readiness", "execution_attempted", "scope",
                "hardware_authorized", "subsequent_execution_authorized"):
        assert short["report"][key] == full["report"][key]
    assert short["report"]["validation"]["qgc_plan_path"] is None
    assert "not absence" in short["interpretation"]["exports"]
    assert "NOT" in short["interpretation"]["scope"] or "not hardware" in short["interpretation"]["scope"]
    raw, execution = full["report"]["executor_result"], short["report"]["executor_result"]
    assert execution["status"] == raw["status"] and execution["success"] is raw["success"]
    assert execution.get("recovery") == raw.get("recovery")
    if run_id == FAILED:
        assert execution["recovery"]["landing_completed"] is True
        assert "error" in execution and short["result_status"] == "FAILED"
    assert tree(storage[0]) == before and restriction() is None
    storage[1].assert_not_called()


@pytest.mark.parametrize("identifier,category", PROPOSALS)
def test_proposal_views_keep_hashes_conditions_and_source_copy_verification(storage, identifier, category):
    # Relocate only fixtures; archives and original runtime artifacts are never edited.
    source = ARCHIVE / "artifacts/missions/generated/revisions/proposals" / identifier
    target = revisions.REVISION_ROOT / "proposals" / identifier
    target.mkdir(parents=True)
    for path in source.iterdir():
        (target / path.name).write_bytes(path.read_bytes())
    before = tree(storage[0])
    full = server.get_revision_proposal(identifier, view="detail")
    assert full == revisions.get_revision_proposal(identifier)
    short = server.get_revision_proposal(identifier)
    assert short["proposal"]["category"] == category
    for key in ("proposal_id", "proposal_sha256", "proposal_path", "status"):
        assert short[key] == full[key]
    for key in ("version", "run_id", "mission_sha256", "report_sha256", "reasons", "proposed_changes",
                "pending_conditions", "automatic_patch", "diagnostic", "flight_consent"):
        assert short["proposal"][key] == full["proposal"][key]
    assert tree(storage[0]) == before
    (target / "source_mission.json").write_text("{}")
    assert server.get_revision_proposal(identifier)["status"] == "ERROR"
    assert server.get_revision_proposal(identifier, view="detail")["status"] == "ERROR"
    assert restriction() is None


def test_unconfirmed_result_and_vehicle_restriction_never_become_success():
    full = {"run_id": FAILED, "admission_status": "ACCEPTED", "job_state": "INTERRUPTED", "result_status": None,
            "worker_alive": False, "worker_error": "worker disappeared", "phase": "execute", "report": None,
            "vehicle_restriction": {"owner_id": FAILED, "state": "UNCONFIRMED"}}
    short = views.summarize_preflight(full)
    assert short["job_state"] == "INTERRUPTED" and short["result_status"] is None
    assert short["report"] is None and short["vehicle_restriction"] == full["vehicle_restriction"]
    assert short["worker_error"] == full["worker_error"]
    assert short["detail_access"]["arguments"] == {"run_id": FAILED, "view": "detail"}


def test_large_nested_errors_are_preserved_without_a_size_cutoff_and_projection_is_pure():
    error = "telemetry-error-" * 2000
    full = {"run_id": FAILED, "job_state": "FINISHED", "result_status": "FAILED",
            "report": {"status": "FAILED", "reasons": ["incomplete evidence"], "readiness": {
                "ready": False, "status": "NOT READY", "return_code": 1,
                "output": "[1/5] Docker container...\n[FAIL] Container is not running."},
                "executor_result": {"status": "FAILED", "success": False,
                    "samples": [{"vendor": {"errors": [error]}}],
                    "recovery": {"landing_completed": False, "error": "LAND unconfirmed"}}}}
    before = deepcopy(full)
    short = views.summarize_preflight(full)
    assert full == before
    assert short["report"]["readiness"] == full["report"]["readiness"]
    assert short["report"]["executor_result"]["recovery"]["landing_completed"] is False
    assert any(entry["value"] == [error] for entry in short["error_evidence"])
    assert "[2/5]" not in json.dumps(short)  # No invented readiness step after early failure.
    assert short["result_status"] == "FAILED"


def test_state_deduplicates_revision_records_and_retains_warnings_and_unknowns(storage):
    from tests.test_mission_state import admit_and_finish
    final = finalized()
    run = admit_and_finish(final, storage[1])
    proposal = revisions.propose_mission_revision(run["run_id"], "one-proposal")
    revision = revisions.build_mission_revision(proposal["proposal_id"], proposal["proposal_sha256"],
        revisions.RevisionChanges(battery_percent=11), "Simulated test condition 11%", "one-revision",
        {"battery_percent": "Operator-declared simulated scenario, not physical telemetry"})
    before = tree(storage[0])
    full = state.get_mission_state(draft_id=final["draft_id"])
    short = state.get_mission_state(draft_id=final["draft_id"], view="summary")
    candidates = [a for a in short["artifacts"] if a.get("revision_id") == revision["revision_id"]]
    assert len(candidates) == 1 and candidates[0]["validation"]["execution_status"] == "BLOCKED"
    assert candidates[0]["declarations"] == revision["declarations"]
    assert short["revisions"] == [{"revision_id": revision["revision_id"], "artifact_ref": revision["revision_id"]}]
    for key in ("warnings", "next_actions", "missing_fields", "readiness_now", "consent", "limits"):
        assert full[key] == short[key]
    assert short["preflights"][0]["report"]["readiness"]["ready"] is False
    assert tree(storage[0]) == before


def test_mcp_read_schema_declares_new_default_and_explicit_legacy_detail():
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    for name in ("get_mission_state", "get_revision_proposal", "get_virtual_preflight"):
        field = tools[name].input_schema["properties"]["view"]
        assert set(field["enum"]) == {"summary", "detail"} and field["default"] == "summary"


def registered(name, arguments):
    """Use SDK dispatch, argument validation and output conversion, without transport."""
    async def invoke():
        task = asyncio.create_task(server.mcp.call_tool(name, arguments))
        try:
            # Bounded polling also wakes the loop when worker-thread notifications
            # are delayed by the test environment. SDK execution is not replaced.
            for _ in range(500):
                if task.done():
                    return task.result()
                await asyncio.sleep(.01)
            raise TimeoutError("Registered read-only tool did not finish within 5 seconds")
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    result = asyncio.run(invoke())
    assert result.is_error is False
    assert json.loads(result.content[0].text) == result.structured_content
    return result.structured_content


def registered_input(name):
    if name == "get_mission_state":
        final = finalized()
        return {"draft_id": final["draft_id"]}, state.get_mission_state(draft_id=final["draft_id"])
    if name == "get_revision_proposal":
        proposal_id = PROPOSALS[1][0]
        source = ARCHIVE / "artifacts/missions/generated/revisions/proposals" / proposal_id
        target = revisions.REVISION_ROOT / "proposals" / proposal_id
        target.mkdir(parents=True)
        for path in source.iterdir():
            (target / path.name).write_bytes(path.read_bytes())
        return {"proposal_id": proposal_id}, revisions.get_revision_proposal(proposal_id)
    return {"run_id": FAILED}, jobs.get_virtual_preflight(run_id=FAILED)


@pytest.mark.parametrize("name", ["get_mission_state", "get_revision_proposal", "get_virtual_preflight"])
def test_registered_dispatch_projects_default_and_summary_and_keeps_detail(storage, monkeypatch, name):
    args, full = registered_input(name)
    # These calls really use the registered functions, not monkeypatched wrappers.
    # Backends keep their existing checks; no revalidation or infrastructure is allowed.
    monkeypatch.setattr(drafts, "validate_mission_file", Mock(side_effect=AssertionError("No validation on read")))
    before = tree(storage[0])
    detail = registered(name, {**args, "view": "detail"})
    summary = registered(name, {**args, "view": "summary"})
    default = registered(name, args)
    assert detail == full and "view" not in detail
    assert default == summary and summary["view"] == "summary"
    expected = (views.summarize_mission_state(full, args) if name == "get_mission_state"
                else views.summarize_proposal(full) if name == "get_revision_proposal"
                else views.summarize_preflight(full))
    assert summary == expected
    assert tree(storage[0]) == before and restriction() is None
    storage[1].assert_not_called()


@pytest.mark.parametrize("name", ["get_mission_state", "get_revision_proposal", "get_virtual_preflight"])
def test_registered_schema_rejects_invalid_view_before_backend(storage, monkeypatch, name):
    backend_name = {"get_mission_state": "mission_state_backend", "get_revision_proposal": "get_proposal_backend",
                    "get_virtual_preflight": "get_preflight_backend"}[name]
    backend = Mock(side_effect=AssertionError("Invalid view must not reach backend"))
    monkeypatch.setattr(server, backend_name, backend)
    args = {"proposal_id": PROPOSALS[0][0]} if name == "get_revision_proposal" else {"run_id": FAILED}
    with pytest.raises(ToolError, match="view"):
        registered(name, {**args, "view": "other"})
    backend.assert_not_called()
    assert not list(storage[0].rglob("*"))


@pytest.mark.parametrize("name,damage", [("get_mission_state", "plan"),
                                        ("get_revision_proposal", "source_report")])
def test_registered_views_preserve_integrity_errors_without_writes(storage, name, damage):
    args, full = registered_input(name)
    target = (Path(full["artifacts"][0]["validation"]["qgc_plan_path"]) if damage == "plan"
              else Path(full["proposal_path"]).with_name("source_report.json"))
    target.write_text("{}")
    before = tree(storage[0])
    detail = registered(name, {**args, "view": "detail"})
    assert registered(name, args) == registered(name, {**args, "view": "summary"}) == detail
    assert detail["status"] == "ERROR" and detail["errors"]
    assert tree(storage[0]) == before and restriction() is None
    storage[1].assert_not_called()


def test_registered_preflight_preserves_interruption_and_restriction(storage, monkeypatch):
    full = {"run_id": FAILED, "request_key": "same-run", "job_state": "INTERRUPTED", "phase": "execute",
            "result_status": None, "worker_alive": False, "worker_error": "Worker disappeared",
            "report": None, "vehicle_restriction": {"owner_id": FAILED, "state": "UNCONFIRMED"}}
    monkeypatch.setattr(server, "get_preflight_backend", Mock(return_value=full))
    before = tree(storage[0])
    short = registered("get_virtual_preflight", {"request_key": "same-run"})
    assert short["vehicle_restriction"] == full["vehicle_restriction"]
    assert short["job_state"] == "INTERRUPTED" and short["result_status"] is None
    assert short["report"] is None and short["worker_error"] == full["worker_error"]
    assert registered("get_virtual_preflight", {"request_key": "same-run", "view": "detail"}) == full
    assert tree(storage[0]) == before
    storage[1].assert_not_called()


def test_error_evidence_contract_has_original_pointer_and_complete_typed_values():
    value = {"job_state": "FINISHED", "run_id": FAILED, "result_status": "FAILED",
             "report": {"executor_result": {"samples": [{"a/b~c": {"errors": ["x" * 40_000, {"code": 7}]}}]}}}
    short = views.summarize_preflight(value)
    assert short["error_evidence"] == [{
        "path": "/report/executor_result/samples/0/a~1b~0c/errors",
        "value": ["x" * 40_000, {"code": 7}],
    }]
    assert views.summarize_preflight({"job_state": "RUNNING"})["error_evidence"] == []


def test_summary_does_not_label_a_failed_waypoint_observation_as_reached():
    raw = {"status": "FAILED", "message": "Position not reached", "events": [
        {"event": "WAYPOINT_REACHED", "waypoint_id": "WP1", "reached": True},
        {"event": "WAYPOINT_REACHED", "waypoint_id": "WP2", "reached": False},
    ]}
    short = views.summarize_preflight({"job_state": "FINISHED", "report": {"executor_result": raw}})
    execution = short["report"]["executor_result"]
    assert execution["reached_waypoint_ids"] == ["WP1"]
    assert execution["failed_events"] == [raw["events"][1]]
    assert execution["message"] == raw["message"] and execution["status"] == "FAILED"


def test_selected_archive_manifest_and_copies_are_complete_and_unchanged():
    manifest = json.loads((ARCHIVE / "manifest.json").read_bytes())
    assert manifest["archive_date_local"] == "2026-10-18"
    # The initial selection remains intact as this evidence archive grows.
    initial_count = 31
    for extension in manifest.get("extensions", []):
        previous_bytes = (ARCHIVE / extension["previous_manifest_path"]).read_bytes()
        assert hashlib.sha256(previous_bytes).hexdigest() == extension["previous_manifest_sha256"]
        previous = json.loads(previous_bytes)
        assert len(previous["files"]) == initial_count == extension["previous_file_count"]
        assert manifest["files"][:initial_count] == previous["files"]
        initial_count += len(extension["added_copy_paths"])
    assert len(manifest["files"]) == initial_count
    paths = set()
    for entry in manifest["files"]:
        assert Path(entry["original_path"]).is_absolute()
        target = ARCHIVE / entry["copy_path"]
        assert target.resolve().is_relative_to(ARCHIVE.resolve())
        assert entry["copy_path"] not in paths
        paths.add(entry["copy_path"])
        content = target.read_bytes()
        assert len(content) == entry["bytes"] and hashlib.sha256(content).hexdigest() == entry["sha256"]
    checks = {item["id"]: item for item in manifest["verification"]}
    assert checks["b880d6c3-4557-42c7-ada4-5a04db5e9237"]["execution_status"] == "APPROVED"
    assert checks["89c3da7d-bc20-42ae-baeb-21d4e839355a"]["execution_status"] == "BLOCKED"
    assert checks["89c3da7d-bc20-42ae-baeb-21d4e839355a"]["battery_percent"] == 11
    assert {item[0] for item in PROPOSALS}.issubset(checks)


def test_archived_geometric_preflight_links_exact_source_and_recomputes_acceptance():
    from models.mission_definition import MissionDefinition
    from reporting.virtual_preflight_analysis import analyze_executor_result

    run_id = "4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4"
    generated = ARCHIVE / "artifacts/missions/generated"
    run = generated / "preflights" / run_id
    report = json.loads((run / "report.json").read_bytes())
    job = json.loads((run / "job.json").read_bytes())
    mission_bytes = (run / "mission.json").read_bytes()
    source = report["source_artifact"]
    finalization = generated / "drafts" / source["draft_id"] / source["artifact_id"]
    record_bytes = (finalization / "finalization.json").read_bytes()
    record = json.loads(record_bytes)
    assert source == job["source_artifact"]
    assert record["finalization_id"] == source["artifact_id"]
    assert record["draft_id"] == source["draft_id"]
    assert hashlib.sha256(record_bytes).hexdigest() == source["record_sha256"]
    assert mission_bytes == (run / "input.json").read_bytes() == (finalization / "mission.json").read_bytes()
    assert (hashlib.sha256(mission_bytes).hexdigest() == report["mission_sha256"]
            == report["expected_sha256"] == job["input_sha256"]
            == source["mission_sha256"] == record["mission_sha256"])
    for name, key in (("source_draft.json", "draft_sha256"),
                      ("source_draft_state.json", "draft_state_sha256")):
        assert hashlib.sha256((finalization / name).read_bytes()).hexdigest() == record[key]
    plan = finalization / Path(record["validation"]["qgc_plan_path"]).name
    assert hashlib.sha256(plan.read_bytes()).hexdigest() == record["qgc_plan_sha256"]
    mission = MissionDefinition.model_validate_json(mission_bytes)
    assert report["analysis"] == analyze_executor_result(mission, report["executor_result"])
    assert report["status"] == "PASSED" and report["report_persisted"] is True
    assert all(report["analysis"]["checks"].values())
    assert report["analysis"]["observed_waypoint_ids"] == ["WP1", "WP2", "WP3", "WP4", "WP5"]
    assert report["executor_result"]["status"] == "COMPLETED" and job["job_state"] == "FINISHED"
    request = generated / "preflights/requests" / (hashlib.sha256(job["request_key"].encode()).hexdigest() + ".json")
    assert json.loads(request.read_bytes()) == {"run_id": run_id, "input_sha256": report["mission_sha256"]}
    manifest = json.loads((ARCHIVE / "manifest.json").read_bytes())
    check = next(item for item in manifest["verification"] if item["id"] == run_id)
    metrics_bytes = (ARCHIVE / check["details_path"]).read_bytes()
    assert hashlib.sha256(metrics_bytes).hexdigest() == check["details_sha256"]
    assert hashlib.sha256((run / "report.json").read_bytes()).hexdigest() == check["report_sha256"]
    metrics = json.loads(metrics_bytes)
    for start, end, key in (("started_at", "finished_at", "workflow_seconds"),
                            ("execution_started_at", "execution_finished_at", "executor_seconds")):
        seconds = (datetime.fromisoformat(report[end]) - datetime.fromisoformat(report[start])).total_seconds()
        assert seconds == metrics[key] == check[key] and seconds > 300
    assert metrics["airborne_seconds"] is None
    assert "vehicle_restriction" not in job and "vehicle_restriction" not in report
