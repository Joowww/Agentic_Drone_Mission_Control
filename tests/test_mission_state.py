"""Read-only lineage queries and admission metadata; all infrastructure is doubled."""
import asyncio
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

import graph.virtual_preflight_graph as graph
import planning.mission_revisions as revisions
import tools.hermes_mcp_server as server
import tools.hermes_mission_planning as drafts
import tools.mission_state as status
import tools.virtual_preflight_jobs as jobs
import tools.virtual_preflight_worker as worker
from models.mission_plan_draft import MissionPlanDraft
from tools.vehicle_execution_lock import restriction

PASSED = "f5f55084-5af6-4e58-ab1a-ce30a13832b3"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "DRAFT_ROOT", tmp_path / "drafts")
    monkeypatch.setattr(revisions, "REVISION_ROOT", tmp_path / "revisions")
    monkeypatch.setattr(jobs, "RUN_ROOT", tmp_path / "runs")
    spawned = Mock(return_value=SimpleNamespace(pid=os.getpid()))
    monkeypatch.setattr(jobs.subprocess, "Popen", spawned)
    monkeypatch.setattr(graph, "check_simulation_ready", Mock(return_value={"ready": False}))
    monkeypatch.setattr(graph, "execute_approved_mission", Mock(side_effect=AssertionError("No flight")))
    return tmp_path, spawned


def finalized():
    # Complete existing JSON -> draft input, no geometry approximation in these tests.
    from tests.test_hermes_mission_planning import complete
    draft = drafts.update_mission_draft(complete())
    return drafts.finalize_mission_draft(draft["draft_id"], draft["draft_revision"])


def tree(root):
    return {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def admit_and_finish(final, spawned, key="preflight"):
    admitted = jobs.start_virtual_preflight(final["mission_path"], key)
    assert admitted["admission_status"] == "ACCEPTED", admitted
    token = spawned.call_args.args[0][-1]
    assert worker.run_worker(admitted["run_id"], token)
    return admitted


def test_state_reads_version_validation_plan_without_revalidation_or_side_effects(storage, monkeypatch):
    final = finalized()
    before = tree(storage[0])
    monkeypatch.setattr(drafts, "validate_mission_file", Mock(side_effect=AssertionError("Already validated")))
    state = server.get_mission_state(draft_id=final["draft_id"])
    assert state["status"] == "KNOWN"
    assert state["draft"]["draft_revision"] == final["draft_revision"]
    artifact = state["artifacts"][0]
    assert artifact["validation"]["execution_status"] == "APPROVED"
    assert artifact["mission_sha256"] == final["mission_sha256"]
    assert artifact["qgc_plan_sha256"] and artifact["matches_current_draft"] is True
    assert state["readiness_now"] == "UNKNOWN_NOT_CHECKED"
    assert state["consent"] == "NOT_GRANTED_BY_THIS_QUERY"
    assert tree(storage[0]) == before and restriction() is None
    graph.check_simulation_ready.assert_not_called()
    graph.execute_approved_mission.assert_not_called()
    storage[1].assert_not_called()


def test_edit_changes_current_version_does_not_reuse_saved_validation(storage):
    final = finalized()
    drafts.update_mission_draft(MissionPlanDraft(battery_percent=1), final["draft_id"], final["draft_revision"])
    state = status.get_mission_state(draft_id=final["draft_id"])
    assert state["artifacts"][0]["matches_current_draft"] is False
    assert state["draft"]["draft"]["battery_percent"] == 1
    assert any("Finalize the current" in action for action in state["next_actions"])
    assert state["preflights"] == []


def test_admission_report_links_survive_reload_and_chain_proposal_revision(storage, monkeypatch):
    final = finalized()
    other = finalized()  # Same mission name AND same bytes, but different explicit artifact ID.
    admitted = admit_and_finish(final, storage[1])
    run_id = admitted["run_id"]
    assert restriction() is None
    report = jobs.get_virtual_preflight(run_id=run_id)["report"]
    assert report["source_artifact"]["artifact_id"] == final["finalization_id"]
    proposal = revisions.propose_mission_revision(run_id, "proposal")
    assert proposal["proposal"]["category"] == "INFRASTRUCTURE_PENDING"
    revised = revisions.build_mission_revision(proposal["proposal_id"], proposal["proposal_sha256"],
        revisions.RevisionChanges(battery_percent=90), "Declaro batería al 90%", "revision",
        {"battery_percent": "Declaración del operador tras revisión física"})
    assert revised["status"] == "REVISED", revised
    next_run = admit_and_finish(revised, storage[1], "revision-flight")
    root, evidence = jobs.RUN_ROOT, jobs.LEGACY_ROOT
    importlib.reload(jobs)
    monkeypatch.setattr(jobs, "RUN_ROOT", root)
    monkeypatch.setattr(jobs, "LEGACY_ROOT", evidence)
    importlib.reload(status)
    before = tree(storage[0])
    state = status.get_mission_state(draft_id=final["draft_id"])
    assert {run["run_id"] for run in state["preflights"]} == {run_id, next_run["run_id"]}
    assert {r["revision_id"] for r in state["revisions"]} == {revised["revision_id"]}
    assert state["proposals"][0]["proposal_id"] == proposal["proposal_id"]
    assert all(run["readiness_now"] == "UNKNOWN_NOT_CHECKED" for run in state["preflights"])
    assert state["preflights"][0]["report"]["readiness"]["ready"] is False
    assert status.get_mission_state(draft_id=other["draft_id"])["preflights"] == []
    by_revision = status.get_mission_state(revision_id=revised["revision_id"])
    assert len(by_revision["linked_drafts"]) == 1
    assert status.get_mission_state(run_id=run_id)["linked_drafts"][0]["draft_id"] == final["draft_id"]
    assert tree(storage[0]) == before
    graph.execute_approved_mission.assert_not_called()
    assert storage[1].call_count == 2


def test_active_job_query_and_missing_worker_have_no_write_or_release(storage, monkeypatch):
    final = finalized()
    admitted = jobs.start_virtual_preflight(final["mission_path"], "only-one")
    before = tree(storage[0])
    state = status.get_mission_state(run_id=admitted["run_id"])
    assert state["preflights"][0]["result_status"] is None
    assert "SAME run_id" in str(state["next_actions"])
    monkeypatch.setattr(jobs, "identity_alive", lambda identity: False)
    interrupted = status.get_mission_state(run_id=admitted["run_id"])
    assert interrupted["preflights"][0]["job_state"] == "INTERRUPTED"
    assert restriction()["owner_id"] == admitted["run_id"]
    assert tree(storage[0]) == before
    storage[1].assert_called_once()


def test_sync_preflight_records_the_same_artifact_lineage_without_worker(storage, monkeypatch):
    from tools import virtual_preflight as workflow
    final = finalized()
    monkeypatch.setattr(workflow, "PREFLIGHT_ROOT", jobs.RUN_ROOT)
    report = workflow.run_virtual_preflight(final["mission_path"])
    assert report["status"] == "BLOCKED" and report["source_artifact"]["artifact_id"] == final["finalization_id"]
    state = status.get_mission_state(draft_id=final["draft_id"])
    assert {run["run_id"] for run in state["preflights"]} == {report["run_id"]}
    graph.execute_approved_mission.assert_not_called()
    storage[1].assert_not_called()
    assert restriction() is None


def test_damaged_known_artifact_is_rejected_before_admission_or_reservation(storage):
    final = finalized()
    Path(final["validation"]["qgc_plan_path"]).write_text("{}")
    result = jobs.start_virtual_preflight(final["mission_path"], "do-not-admit")
    assert result["admission_status"] == "ERROR" and result["spawned"] is False
    storage[1].assert_not_called()
    assert restriction() is None
    assert not list(jobs.RUN_ROOT.glob("*/job.json"))


def test_historical_passed_snapshot_does_not_guess_a_draft(storage):
    before = tree(storage[0])
    state = status.get_mission_state(run_id=PASSED)
    assert state["status"] == "KNOWN_WITH_WARNINGS", state
    assert state["preflights"][0]["result_status"] == "PASSED"
    assert state["preflights"][0]["snapshot_integrity"] == "VERIFIED_LOCAL_HASH"
    assert state["artifacts"] == [] and state["draft"] is None
    assert state["hardware_authorized"] is False
    assert "UNKNOWN" in str(state["warnings"])
    assert tree(storage[0]) == before and restriction() is None
    storage[1].assert_not_called()


@pytest.mark.parametrize("damage", ["mission", "plan", "link", "source_draft"])
def test_hash_damage_is_not_associated_and_never_starts_or_repairs(storage, damage):
    final = finalized()
    admitted = jobs.start_virtual_preflight(final["mission_path"], "hash-check")
    if damage == "mission":
        Path(final["mission_path"]).write_text("{}")
    elif damage == "plan":
        Path(final["validation"]["qgc_plan_path"]).write_text("{}")
    elif damage == "source_draft":
        Path(final["mission_path"]).with_name("source_draft.json").write_text("{}")
    else:
        path = Path(admitted["paths"]["job_path"])
        job = json.loads(path.read_text())
        job["source_artifact"]["record_sha256"] = "0" * 64
        path.write_text(json.dumps(job))
    before = tree(storage[0])
    assert status.get_mission_state(run_id=admitted["run_id"])["status"] == "ERROR"
    assert tree(storage[0]) == before and restriction()["owner_id"] == admitted["run_id"]
    storage[1].assert_called_once()


def test_bad_anchor_and_unknown_are_read_only(storage):
    before = tree(storage[0])
    for kwargs in ({}, {"run_id": "../outside"}, {"draft_id": str(uuid4()), "run_id": str(uuid4())},
                   {"finalization_id": str(uuid4())}):
        assert status.get_mission_state(**kwargs)["status"] == "ERROR"
    assert status.get_mission_state(run_id=str(uuid4()))["status"] == "NOT_FOUND"
    assert tree(storage[0]) == before


def test_new_tools_expose_typed_versions_and_state_schema():
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    expected = {"propose_mission_revision", "get_revision_proposal", "build_mission_revision",
                "generate_draft_route", "get_mission_state"}
    assert expected.issubset(tools)
    assert "expected_revision" in tools["generate_draft_route"].input_schema["required"]
    assert "expected_proposal_sha256" in tools["build_mission_revision"].input_schema["required"]
