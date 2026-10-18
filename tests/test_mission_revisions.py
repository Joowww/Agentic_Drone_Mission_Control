from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path

import pytest

import planning.mission_revisions as revisions
import tools.virtual_preflight_jobs as jobs
from tools.vehicle_execution_lock import restriction

ROOT = Path(__file__).resolve().parents[1] / "simulation/ros2_gazebo/results/virtual_preflight_2026_10_17"
BATTERY = "0844c190-59c8-40cf-991e-93cebbd3cf02"
READINESS = "d7717942-9b43-45c7-bf3a-65b02bb1155a"
FAILED = "d4519cab-ebd1-4359-b547-44be38294a6a"
PASSED = "f5f55084-5af6-4e58-ab1a-ce30a13832b3"


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(revisions, "REVISION_ROOT", tmp_path / "revisions")
    monkeypatch.setattr(jobs, "RUN_ROOT", tmp_path / "runs")
    # Copies allow integrity fault injection without touching original evidence.
    evidence = tmp_path / "evidence/virtual_preflight_copy"
    evidence.mkdir(parents=True)
    for path in ROOT.glob("*.json"):
        (evidence / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(jobs, "LEGACY_ROOT", evidence.parent)
    return evidence


def propose(run_id=BATTERY):
    result = revisions.propose_mission_revision(run_id, "proposal")
    assert result["status"] == "PROPOSED", result
    return result


def build(proposal, battery=95, key="revision", declarations=None):
    return revisions.build_mission_revision(
        proposal["proposal_id"], proposal["proposal_sha256"],
        revisions.RevisionChanges(battery_percent=battery), "He cambiado la batería; declaro el nivel nuevo", key,
        declarations if declarations is not None else {"battery_percent": f"Declaro {battery}% tras intervención"},
    )


def test_battery_intervention_is_proposal_not_a_measurement_and_revision_revalidates(storage):
    original = {p.name: p.read_bytes() for p in storage.iterdir()}
    proposal = propose()
    text = str(proposal["proposal"])
    assert "Recharge or replace" in text and "no generated route" in text.lower()
    assert proposal["proposal"]["automatic_patch"] is None
    revised = build(proposal)
    assert revised["status"] == "REVISED", revised
    assert revised["validation"]["execution_status"] == "APPROVED"
    assert Path(revised["validation"]["qgc_plan_path"]).exists()
    assert revised["declarations"]["battery_percent"]["source"] == "operator_declared_not_telemetry"
    assert any(d["path"] == "/vehicle/battery_percent" and d["before"] == 10 for d in revised["differences"])
    assert {p.name: p.read_bytes() for p in storage.iterdir()} == original
    assert restriction() is None


def test_revision_can_remain_unsafe_and_missing_declaration_is_rejected():
    proposal = propose()
    assert build(proposal, declarations={})["status"] == "ERROR"
    result = build(proposal, battery=11)
    assert result["validation"]["execution_status"] == "BLOCKED"
    assert result["validation"]["qgc_plan_path"].endswith("_candidate.plan")


@pytest.mark.parametrize("run_id,category", [(READINESS, "INFRASTRUCTURE_PENDING"),
    (FAILED, "INVESTIGATE_EXECUTION"), (PASSED, "NO_CORRECTION_REQUIRED")])
def test_reports_do_not_invent_changes(run_id, category):
    result = propose(run_id)["proposal"]
    assert result["category"] == category
    assert result["automatic_patch"] is None and result["proposed_changes"] == []
    if run_id == FAILED:
        assert result["execution_evidence"]["recovery"]["landing_completed"] is True
        assert "unknown" in str(result["pending_conditions"])


def test_reload_idempotence_conflict_and_source_integrity(storage, monkeypatch):
    proposal = propose()
    root = revisions.REVISION_ROOT
    importlib.reload(revisions)
    monkeypatch.setattr(revisions, "REVISION_ROOT", root)
    assert propose()["proposal_id"] == proposal["proposal_id"]
    first = build(proposal)
    assert build(proposal) == first
    assert build(proposal, battery=90)["status"] == "CONFLICT"
    assert revisions.propose_mission_revision(PASSED, "proposal")["status"] == "CONFLICT"
    path = storage / "blocked_battery_mission.json"
    path.write_text(path.read_text().replace('10.0', '12.0'))
    assert build(proposal, key="new")["status"] == "ERROR"


def test_proposal_hash_and_copied_source_must_match():
    proposal = propose()
    path = Path(proposal["proposal_path"])
    data = json.loads(path.read_text())
    data["pending_conditions"].append("changed")
    path.write_text(json.dumps(data))
    assert build(proposal)["status"] == "CONFLICT"
    (path.parent / "source_mission.json").write_text("{}")
    assert revisions.get_revision_proposal(proposal["proposal_id"])["status"] == "ERROR"


@pytest.mark.parametrize("damage", [lambda r: r.update(status="RUNNING"),
    lambda r: r.update(mission_sha256="0"*64),
    lambda r: r["mission_identity"].update(mission_id="wrong"),
    lambda r: r.update(status="PASSED")])
def test_provisional_or_incoherent_report_is_rejected(storage, damage):
    path = storage / "blocked_battery_report.json"
    report = json.loads(path.read_text()); damage(report); path.write_text(json.dumps(report))
    assert revisions.propose_mission_revision(BATTERY, "bad")["status"] == "ERROR"
    assert not (revisions.REVISION_ROOT / "proposals/requests").exists()


def test_explicit_route_edit_uses_existing_editor_and_safety_not_a_guaranteed_solution():
    proposal = propose()
    result = revisions.build_mission_revision(proposal["proposal_id"], proposal["proposal_sha256"],
        revisions.RevisionChanges(waypoint_removals=["WP3"]), "Acepto retirar WP3 de esta planificación", "route")
    assert result["status"] == "REVISED"
    assert len(json.loads(Path(result["mission_path"]).read_text())["route"]["waypoints"]) == 2
    assert result["validation"]["execution_status"] == "BLOCKED"


def test_weaker_constraints_cannot_be_silently_used():
    proposal = propose()
    result = revisions.build_mission_revision(proposal["proposal_id"], proposal["proposal_sha256"],
        revisions.RevisionChanges(minimum_battery_reserve_percent=0), "Cambios", "weak")
    assert result["status"] == "ERROR"


def test_interrupted_build_key_is_not_replayed(monkeypatch):
    proposal = propose()
    monkeypatch.setattr(revisions, "validate_mission_file", lambda *a, **k: (_ for _ in ()).throw(OSError("disk error")))
    assert build(proposal)["status"] == "ERROR"
    assert build(proposal)["status"] == "BUILDING"
    assert len(list((revisions.REVISION_ROOT / "missions").glob("*/mission.json"))) == 1


def test_concurrent_same_keys_produce_one_proposal_and_revision():
    with ThreadPoolExecutor(2) as pool:
        proposals = list(pool.map(lambda _: propose(), range(2)))
    assert proposals[0]["proposal_id"] == proposals[1]["proposal_id"]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: build(proposals[0]), range(2)))
    assert results[0]["revision_id"] == results[1]["revision_id"]
    assert len(list((revisions.REVISION_ROOT / "missions").glob("*/revision.json"))) == 1


def test_inconsistent_analysis_and_contradictory_block_are_rejected(storage):
    path = storage / "passed_async_report.json"
    report = json.loads(path.read_text())
    report["analysis"]["checks"]["all_waypoints_reached"] = False
    path.write_text(json.dumps(report))
    assert revisions.propose_mission_revision(PASSED, "bad-analysis")["status"] == "ERROR"
    path = storage / "blocked_readiness_report.json"
    report = json.loads(path.read_text())
    report["execution_attempted"] = True
    report["executor_result"] = {"status": "COMPLETED", "events": [{"event": "ARM"}]}
    path.write_text(json.dumps(report))
    assert revisions.propose_mission_revision(READINESS, "contradiction")["status"] == "ERROR"


def test_duplicate_historical_identity_is_ambiguous(storage):
    (storage / "duplicate_report.json").write_bytes((storage / "passed_async_report.json").read_bytes())
    assert revisions.propose_mission_revision(PASSED, "duplicate")["status"] == "ERROR"


def test_corrupt_request_and_revision_are_not_recreated():
    proposal = propose()
    revised = build(proposal)
    key = revisions.request_path(revisions.REVISION_ROOT / "revisions", "revision")
    index = json.loads(key.read_text())
    index["result"] = {}
    key.write_text(json.dumps(index))
    assert build(proposal)["status"] == "ERROR"
    assert len(list((revisions.REVISION_ROOT / "missions").glob("*/mission.json"))) == 1
    index["result"] = revised
    key.write_text(json.dumps(index))
    Path(revised["mission_path"]).write_text("{}")
    assert build(proposal)["status"] == "ERROR"
    assert len(list((revisions.REVISION_ROOT / "missions").glob("*/mission.json"))) == 1


def test_interrupted_proposal_identity_recovers_without_rebuilding(monkeypatch):
    original = revisions.atomic_json
    def fail_proposal(path, value):
        if path.name == "proposal.json":
            raise OSError("Interrupted before proposal publication")
        return original(path, value)
    monkeypatch.setattr(revisions, "atomic_json", fail_proposal)
    assert revisions.propose_mission_revision(BATTERY, "intent")["status"] == "ERROR"
    before = list((revisions.REVISION_ROOT / "proposals").glob("*/source_mission.json"))
    recovered = revisions.propose_mission_revision(BATTERY, "intent")
    assert recovered["status"] == "BUILDING" and recovered["proposal_id"] == before[0].parent.name
    assert list((revisions.REVISION_ROOT / "proposals").glob("*/source_mission.json")) == before
