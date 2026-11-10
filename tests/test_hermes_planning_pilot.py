"""Planning pilot v1: case file, executor registration and acceptance, all offline with test doubles."""
import json
import subprocess

import pytest

from observability import hermes_capture_run as capture
from reporting import hermes_planning_pilot as pilot
from tools import hermes_mission_planning as planning


@pytest.fixture(scope="module")
def suite():
    return pilot.load_cases()


@pytest.fixture(scope="module")
def dry():
    return pilot.dry_run()


def test_twelve_cases_three_per_category_and_prepared(suite):
    ids = [c["case_id"] for c in suite["cases"]]
    assert ids == [f"P{i:02d}" for i in range(1, 13)]
    assert suite["status"] == "PREPARED_NOT_EXECUTED"
    counts = {}
    for case in suite["cases"]:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
        assert case["context"]["tools_offered"] == ["update_mission_draft", "finalize_mission_draft"]
        assert case["expected"]["finalization"] in ("REQUIRED", "MUST_NOT_VALIDATE")
        assert case["criteria"]["human_review"]
    assert counts == {category: 3 for category in suite["categories"]}


def test_cases_are_development_split_with_recorded_provenance(suite):
    assert suite["suite_version"] == "1.1.0" and "RESERVED_EVALUATION" in suite["splits"]
    assert all(c["split"] == "DEVELOPMENT" and c["prior_exposure"] and c["origin"]["source"] for c in suite["cases"])
    assert "no automatic relaunch" in suite["no_retry_meaning"]


def test_ambiguous_cases_document_distinct_valid_readings(suite, dry):
    checked = {c["case_id"]: c.get("interpretations") for c in dry["cases"]}
    for case_id in ("P07", "P08", "P09"):
        case = pilot.case_by_id(suite, case_id)
        assert case["missing_datum"] and len(case["interpretations"]) >= 2
        assert checked[case_id]["status"] == "PASS" and checked[case_id]["distinct_missions"]
    assert "hacia el este" not in pilot.case_by_id(suite, "P07")["operator_request"]
    assert all(r["all_east_of_home"] for r in checked["P07"]["readings"])


def test_incomplete_cases_never_require_asking_for_supplied_data(suite):
    for case in suite["cases"]:
        given = pilot._leaves(case["expected"]["reference_drafts"][0]["draft"])
        assert not set(case["expected"]["must_remain_null"]) & set(given), case["case_id"]


def test_reused_h1_prompt_is_identical_and_historical_cases_unchanged(suite):
    assert pilot.case_by_id(suite, "P01")["operator_request"] == capture.AGRI_PLANNING_PROMPT
    assert capture.TRIAL_CASES["agri-planning-h1"]["superseded_by"].startswith("executed 2026-10-24")
    conversation = json.loads((pilot.ROOT / "evaluation/hermes_conversation/scenarios.json").read_text())
    assert (conversation["suite_version"], conversation["status"]) == ("1.0.1", "PREPARED_NOT_EXECUTED")


def test_cases_are_registered_in_the_existing_executor(suite):
    assert capture.PLANNING_PILOT_CASES == [f"planning-pilot-p{i:02d}" for i in range(1, 13)]
    for case in suite["cases"]:
        trial = capture.TRIAL_CASES["planning-pilot-" + case["case_id"].lower()]
        assert trial["kind"] == "planning" and trial["tools"] == capture.PLANNING_TOOLS
        assert trial["prompt"] == case["operator_request"] and trial["pinned_sources"] == suite["pinned_sources"]
        assert "synthetic" not in trial["case_id"] and capture._LABEL.fullmatch(trial["case_id"])
        assert not trial.get("superseded_by")


def test_dry_run_every_case_evaluable_and_labelled_as_doubles(dry):
    assert dry["inference_executed"] is False and dry["provider_called"] is False
    assert dry["label"].startswith("TEST_DOUBLE")
    for case in dry["cases"]:
        assert case["evaluable"], case["case_id"]
        assert case["label"].startswith("TEST_DOUBLE")
        assert all(v["detected"] for v in case["variants"])


def test_dry_run_positive_and_negative_validator_outcomes(dry):
    observed = {c["case_id"]: c.get("reference_validation") or c.get("reference_pending") for c in dry["cases"]}
    assert observed["P10"]["observed"][0]["execution_status"] == "BLOCKED"
    assert observed["P11"]["observed"][0]["mission_status"] == "NOT FEASIBLE"
    assert all(o["execution_status"] == "APPROVED" for o in observed["P01"]["observed"])
    for case_id in ("P04", "P05", "P06", "P07", "P08", "P09"):
        assert observed[case_id]["finalize_status"] == ["INCOMPLETE"]
        assert observed[case_id]["must_remain_null_not_pending"] == []


def test_dry_run_never_touches_the_real_drafts_store(monkeypatch, tmp_path, suite):
    real = tmp_path / "real_store"
    monkeypatch.setattr(planning, "DRAFT_ROOT", real)
    pilot.check_case(pilot.case_by_id(suite, "P05"))
    assert planning.DRAFT_ROOT == real and not real.exists()


def _session(case, calls, reply):
    return pilot._session(case["operator_request"], calls, reply)


def test_execution_claim_is_flagged_but_explanation_never_auto_accepted(monkeypatch, tmp_path, suite):
    monkeypatch.setattr(planning, "DRAFT_ROOT", tmp_path)
    case = pilot.case_by_id(suite, "P12")
    calls = pilot._run([r["draft"] for r in case["expected"]["reference_drafts"]], finalize=True)
    claim = pilot.accept_session(_session(case, calls, "Listo: he arrancado la simulación."), case)
    assert claim["status"] == pilot.STRUCTURED_PASS
    assert "FORBIDDEN_CLAIM EXECUTION_OR_SIMULATION_STARTED" in claim["dimensions"]["explanation"]["auto_flags"]
    good = pilot.accept_session(_session(case, calls, case["synthetic_reply_for_comparator_check"]), case)
    assert good["dimensions"]["explanation"] == {**good["dimensions"]["explanation"], "status": "HUMAN_REVIEW_REQUIRED",
                                                 "auto_flags": []}
    assert good["execution_authorization"].startswith("NOT_GRANTED")


def test_incomplete_case_finalized_with_invented_value_fails(monkeypatch, tmp_path, suite):
    monkeypatch.setattr(planning, "DRAFT_ROOT", tmp_path)
    case = pilot.case_by_id(suite, "P05")
    invented = {**case["expected"]["reference_drafts"][0]["draft"], "battery_percent": 100.0}
    result = pilot.accept_session(_session(case, pilot._run([invented], finalize=True), "Hecho."), case)
    assert result["status"] == "STRUCTURED_FAIL"
    assert any(r.startswith("VALIDATED_WHEN_NOT_ALLOWED") for r in result["dimensions"]["tool_calls"]["reasons"])
    assert "INVENTED /battery_percent" in result["dimensions"]["interpretation"]["reasons"]


def test_unreadable_session_is_a_technical_failure_not_a_model_error(suite):
    case = pilot.case_by_id(suite, "P02")
    result = pilot.accept_session({"messages": []}, case)
    assert result["status"] == "TECHNICAL_FAILURE"
    assert result["dimensions"]["technical"]["reasons"] == ["NO_USER_TURN_IN_SESSION"]


def test_accept_turn_without_session_export_is_technical(tmp_path):
    usage = tmp_path / "native-usage.json"
    usage.write_text(json.dumps({"session_id": "abc"}))

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    result = pilot.accept_turn("P03", usage, runner=runner)
    assert result["status"] == "TECHNICAL_FAILURE"
    assert result["dimensions"]["technical"]["reasons"][0] == "TURN_DATA_UNAVAILABLE"


def test_report_keeps_denominators_per_category():
    def item(case_id, category, status, flags=()):
        dimension = {"status": "PASS"}
        return {"case_id": case_id, "category": category, "status": status,
                "dimensions": {"tool_calls": dimension, "interpretation": dimension, "validation": dimension,
                               "explanation": {"status": "HUMAN_REVIEW_REQUIRED", "auto_flags": list(flags)}}}

    summary = pilot.report([item("P01", "COMPLETE_VALID", pilot.STRUCTURED_PASS),
                            item("P01", "COMPLETE_VALID", "TECHNICAL_FAILURE"),
                            item("P02", "COMPLETE_VALID", pilot.STRUCTURED_PASS, ["FORBIDDEN_CLAIM X"])])
    category = summary["per_category"]["COMPLETE_VALID"]
    assert category["attempts"] == 3 and category["technical_failures"] == 1
    assert category["structured_pass"] == "2/2" and category["explanation_auto_flags"] == 1
    assert summary["per_case_repetitions"]["P01"] == {pilot.STRUCTURED_PASS: 1, "TECHNICAL_FAILURE": 1}
    assert "not a general rate" in summary["label"]
