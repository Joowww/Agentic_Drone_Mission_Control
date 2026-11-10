"""Offline tests for the historical case catalog, the structured-answer evaluator and the
reduced external view of get_mission_state. No MCP stdio, Hermes, provider or simulation.

Git-tracked report copies always run; checks against the git-ignored local run directories are
skipped where those files are absent. Synthetic inputs are marked as such."""
import hashlib
import json
from pathlib import Path

import pytest

from observability import hermes_capture_run as run
from observability import mission_query_cases as cases
from tools.mission_external_view import external_mission_state

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "missions" / "generated" / "preflights"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- catalog from real records -------------------------------------------------------------

def test_tracked_copies_pin_the_failed_and_blocked_cases():
    for name in ("failed-d4519cab", "blocked-validate-0844c190", "blocked-readiness-d7717942"):
        case = cases.CASES[name]
        report = ROOT / case["tracked"]
        assert _sha(report) == case["report_sha256"]
        data = json.loads(report.read_text())
        assert data["run_id"] == case["run_id"]
        assert cases.CATEGORIES[(data["status"], data["stage"])] == case["category"]


def test_failed_answer_is_derived_from_the_tracked_report_not_from_the_tool():
    report = json.loads((ROOT / cases.CASES["failed-d4519cab"]["tracked"]).read_text())
    assert cases.expected_answer_from_report(report) == run.FAILED_ANSWER
    # Recorded facts that must NOT be turned into answers: no return flag, no mission LANDED event,
    # a failed acceptance check; the recovery landing is a separate record.
    assert report["executor_result"].get("return_to_home") is None
    assert report["analysis"]["checks"]["landed_and_disarmed"] is False
    assert report["executor_result"]["recovery"]["landing_completed"] is True


def test_blocked_records_leave_progress_and_landing_unknown_never_inferred():
    for name in ("blocked-validate-0844c190", "blocked-readiness-d7717942"):
        answer = cases.expected_answer_from_report(json.loads((ROOT / cases.CASES[name]["tracked"]).read_text()))
        for key in ("planned_waypoint_ids", "reached_waypoint_ids", "return_to_home",
                    "mission_landed_event_recorded", "recovery_landing_completed", "current_availability"):
            assert answer[key] == cases.UNKNOWN, (name, key)


def test_passed_does_not_fill_unrecorded_fields():
    # SYNTHETIC report: PASSED but nothing else recorded.
    answer = cases.expected_answer_from_report({"run_id": "r", "status": "PASSED"})
    assert answer["historical_status"] == "PASSED"
    assert all(answer[k] == cases.UNKNOWN for k in cases.ANSWER_FIELDS if k not in ("run_id", "historical_status"))


@pytest.mark.parametrize("name", [n for n, c in cases.CASES.items() if c["report_sha256"]])
def test_local_records_match_the_catalog_and_the_external_view(name):
    case = cases.CASES[name]
    directory = LOCAL / case["run_id"]
    if not (directory / "report.json").is_file():
        pytest.skip("local run directory is git-ignored data")
    before = {p.name: _sha(p) for p in directory.iterdir() if p.is_file()}
    assert before["report.json"] == case["report_sha256"]
    report = json.loads((directory / "report.json").read_text())
    assert cases.CATEGORIES[(report["status"], report["stage"])] == case["category"]
    expected = cases.expected_answer_from_report(report)
    from tools.mission_state import get_mission_state
    view = get_mission_state(run_id=case["run_id"], view="external")
    # The contract applied to the tool's view equals the answer derived from the raw report.
    assert cases.answer_from_external_view(view) == expected
    assert view["external_schema_version"] == 2
    assert view["readiness_now"] == "UNKNOWN_NOT_CHECKED" and view["rejected_fields"] == []
    assert {p.name: _sha(p) for p in directory.iterdir() if p.is_file()} == before  # records untouched


# --- structured answer evaluator (SYNTHETIC answers) ------------------------------------------

def _answer(**override):
    return json.dumps({**run.FAILED_ANSWER, **override})


@pytest.mark.parametrize("text, verdict, field, outcome", [
    (_answer(), "ALL_FIELDS_CORRECT", "run_id", "match"),
    ("```json\n" + _answer() + "\n```", "ALL_FIELDS_CORRECT", "run_id", "match"),
    (_answer(current_availability="UNKNOWN_NOT_CHECKED"), "ALL_FIELDS_CORRECT", "current_availability", "match"),
    (_answer(return_to_home=False), "FIELDS_INCORRECT", "return_to_home", "invented_value"),
    # v2 trial 2026-10-23: the model copied the source null instead of writing "UNKNOWN".
    (_answer(return_to_home=None), "FIELDS_INCORRECT", "return_to_home", "null_instead_of_unknown"),
    (_answer(recovery_landing_completed=None), "FIELDS_INCORRECT", "recovery_landing_completed", "wrong_type"),
    (_answer(current_availability="READY"), "FIELDS_INCORRECT", "current_availability", "invented_value"),
    (_answer(recovery_landing_completed="UNKNOWN"), "FIELDS_INCORRECT", "recovery_landing_completed",
     "unknown_but_recorded"),
    (_answer(mission_landed_event_recorded="false"), "FIELDS_INCORRECT", "mission_landed_event_recorded", "wrong_type"),
    (_answer(reached_waypoint_ids=["WP1", "WP2", "WP3"]), "FIELDS_INCORRECT", "reached_waypoint_ids", "mismatch"),
    (_answer(historical_status="PASSED"), "FIELDS_INCORRECT", "historical_status", "mismatch"),
    (json.dumps({k: v for k, v in run.FAILED_ANSWER.items() if k != "vehicle_id"}), "FIELDS_INCORRECT",
     "vehicle_id", "missing"),
])
def test_structured_answer_outcomes_per_field(text, verdict, field, outcome):
    result = cases.evaluate_answer(text, run.FAILED_ANSWER)
    assert (result["verdict"], result["fields"][field]) == (verdict, outcome)
    assert "prueba_hermes_001" not in json.dumps(result)  # outcomes only, no values


@pytest.mark.parametrize("text, status", [("FAILED", "NOT_JSON"), ("", "EMPTY"), ("[1, 2]", "NOT_AN_OBJECT"),
                                          ("El resultado es " + _answer(), "NOT_JSON")])
def test_unparseable_answers_are_never_partially_scored(text, status):
    result = cases.evaluate_answer(text, run.FAILED_ANSWER)
    assert (result["verdict"], result["parse_status"], result["fields"]) == ("ANSWER_NOT_PARSEABLE", status, {})


def test_extra_keys_make_the_answer_incorrect_and_are_only_counted():
    result = cases.evaluate_answer(_answer(note="free text"), run.FAILED_ANSWER)
    assert result["verdict"] == "FIELDS_INCORRECT" and result["extra_keys"] == 1 and "free text" not in json.dumps(result)


# --- external view projection (SYNTHETIC summary) --------------------------------------------

SUMMARY = {
    "status": "KNOWN_WITH_WARNINGS", "readiness_now": "UNKNOWN_NOT_CHECKED", "consent": "NOT_GRANTED_BY_THIS_QUERY",
    "hardware_authorized": False, "warnings": [{"path": "/home/someone/x", "message": "m"}],
    "preflights": [{
        "run_id": "r1", "request_key": "joel-secret-key", "job_state": "FINISHED", "result_status": "FAILED",
        "worker": {"pid": 4242, "start_ticks": 7, "boot_id": "boot-xyz"}, "worker_alive": False,
        "paths": {"report_path": "/home/someone/report.json"}, "vehicle_selection": {"vehicle_id": "drone_01",
                                                                                     "simulated_vehicle": "v1"},
        "report": {"status": "FAILED", "stage": "analyze", "reasons": ["Executor error: /home/someone/log"],
                   "mission_identity": {"mission_id": "m/../../etc", "name": "Prueba"},
                   "readiness": {"ready": True, "status": "READY", "output": "LOG LINE"},
                   "executor_result": {"status": "FAILED", "error": "trace", "waypoints_completed": "3",
                                       "reached_waypoint_ids": ["WP1"], "landing_evidence": [],
                                       "recovery": {"landing_completed": True, "landing": {
                                           "landed": True, "armed": False, "flying": False,
                                           "final_position": {"lat": 41.27531, "lon": 1.98712}}}}}}],
}


def test_external_view_keeps_typed_allow_list_and_drops_identifying_or_free_text():
    view = external_mission_state(SUMMARY, {"run_id": "r1"})
    text = json.dumps({k: v for k, v in view.items() if k not in ("omitted", "semantics")})
    for leaked in ("/home/", "joel-secret-key", "4242", "boot-xyz", "LOG LINE", "trace", "41.27531", "Executor error"):
        assert leaked not in text
    entry = view["preflights"][0]
    facts, criteria, recovery = entry["executor_facts"], entry["acceptance_criteria"], entry["recovery_after_failure"]
    assert entry["identity"]["mission_id"] is None and "preflights/0/identity/mission_id" in view["rejected_fields"]
    assert facts["waypoints_completed"] is None and "preflights/0/executor_facts/waypoints_completed" in view["rejected_fields"]
    assert facts["return_to_home"] is None and "preflights/0/executor_facts/return_to_home" not in view["rejected_fields"]
    assert (facts["mission_landing_events"], facts["mission_landing_event_count"]) == ([], 0)
    assert recovery["landing_completed"] is True and "final_position" not in json.dumps(recovery)
    assert criteria == {"passed": None, "checks": None}  # no analysis recorded: null, not inferred
    assert entry["reason_count"] == 1 and view["warning_count"] == 1 and view["queried"] == {"run_id": "r1"}


# --- contract v2: one source field per key (SYNTHETIC views/reports) ----------------------------

def _view(facts=None, criteria=None, recovery=None, readiness_now="UNKNOWN_NOT_CHECKED", **identity):
    summary = {"status": "KNOWN", "readiness_now": readiness_now, "preflights": [{
        "run_id": "r1", "result_status": "FAILED",
        "vehicle_selection": {"vehicle_id": "drone_01", "simulated_vehicle": "v1"},
        "report": {"status": "FAILED", "stage": "analyze", "mission_identity": {"mission_id": "m1", **identity},
                   "analysis": {"expected_waypoint_ids": ["WP1"], "passed": False, "checks": criteria or {}},
                   "executor_result": {**(facts or {}), "recovery": recovery or {}}}}]}
    return external_mission_state(summary, {"run_id": "r1"})


def test_return_to_home_null_stays_unknown_even_with_a_false_acceptance_criterion():
    view = _view(facts={"return_to_home": None}, criteria={"return_home_reached": False})
    assert cases.answer_from_external_view(view)["return_to_home"] == cases.UNKNOWN
    wrong = cases.evaluate_answer(json.dumps({**cases.answer_from_external_view(view), "return_to_home": False}),
                                  cases.answer_from_external_view(view))
    assert wrong["fields"]["return_to_home"] == "invented_value"  # the v1 failure mode is caught


@pytest.mark.parametrize("recorded", [True, False])
def test_recorded_return_to_home_true_or_false_is_reported_as_recorded(recorded):
    view = _view(facts={"return_to_home": recorded}, criteria={"return_home_reached": not recorded})
    assert cases.answer_from_external_view(view)["return_to_home"] is recorded  # criteria never override facts
    report = {"run_id": "r1", "status": "FAILED", "executor_result": {"return_to_home": recorded}}
    assert cases.expected_answer_from_report(report)["return_to_home"] is recorded
    answer = json.dumps({**cases.expected_answer_from_report(report), "return_to_home": cases.UNKNOWN})
    assert cases.evaluate_answer(answer, cases.expected_answer_from_report(report))["fields"]["return_to_home"] == \
        "unknown_but_recorded"


def test_mission_landing_and_recovery_landing_stay_separate():
    only_recovery = _view(facts={"landing_evidence": []}, recovery={"landing_completed": True})
    answer = cases.answer_from_external_view(only_recovery)
    assert (answer["mission_landed_event_recorded"], answer["recovery_landing_completed"]) == (False, True)
    no_log = cases.answer_from_external_view(_view(facts={}))
    assert (no_log["mission_landed_event_recorded"], no_log["recovery_landing_completed"]) == (cases.UNKNOWN,) * 2
    landed = cases.answer_from_external_view(_view(facts={"landing_evidence": [
        {"event": "LANDED", "landed": True, "armed": False, "flying": False}]}))
    assert landed["mission_landed_event_recorded"] is True


@pytest.mark.parametrize("facts, key, rejected", [
    ({"return_to_home": "false"}, "return_to_home", "preflights/0/executor_facts/return_to_home"),
    ({"reached_waypoint_ids": "WP1"}, "reached_waypoint_ids", "preflights/0/executor_facts/reached_waypoint_ids"),
    ({"landing_evidence": [{"event": "LANDED", "landed": "yes"}]}, "mission_landed_event_recorded",
     "preflights/0/executor_facts/mission_landing_events"),
])
def test_wrong_source_types_are_rejected_and_answered_unknown(facts, key, rejected):
    view = _view(facts=facts)
    assert rejected in view["rejected_fields"] and cases.answer_from_external_view(view)[key] == cases.UNKNOWN


def test_absent_sources_are_unknown_and_current_availability_is_unknown_in_historical_queries():
    answer = cases.answer_from_external_view(external_mission_state({"status": "KNOWN", "preflights": [{}]}, {}))
    assert all(v == cases.UNKNOWN for v in answer.values())
    assert cases.answer_from_external_view(_view())["current_availability"] == cases.UNKNOWN
    assert cases.answer_from_external_view(_view(readiness_now=None))["current_availability"] == cases.UNKNOWN
    answer = json.dumps({**cases.answer_from_external_view(_view()), "current_availability": "READY"})
    assert cases.evaluate_answer(answer, cases.answer_from_external_view(_view()))["fields"]["current_availability"] \
        == "invented_value"


# --- contract v3: return_to_home is true / false / null (SYNTHETIC answers and views) -------------

V3 = {**run.FAILED_ANSWER, "return_to_home": None}  # = run.FAILED_ANSWER_V3


def _v3(**override):
    return json.dumps({**V3, **override})


@pytest.mark.parametrize("expected, answer, outcome", [
    (None, None, "match"),                      # not recorded -> null
    (True, True, "match"), (False, False, "match"),
    (True, False, "mismatch"), (False, True, "mismatch"),
    (None, False, "invented_value"),            # the v1 failure mode
    (None, True, "invented_value"),
    (True, None, "unknown_but_recorded"), (False, None, "unknown_but_recorded"),
    (None, "UNKNOWN", "wrong_type"),            # the v2 convention is NOT accepted for this key in v3
    (None, "null", "wrong_type"), (False, "false", "wrong_type"), (True, 1, "wrong_type"), (False, 0, "wrong_type"),
])
def test_v3_return_to_home_accepts_only_true_false_or_null(expected, answer, outcome):
    result = cases.evaluate_answer(_v3(return_to_home=answer), {**V3, "return_to_home": expected}, "v3")
    assert result["fields"]["return_to_home"] == outcome and result["contract"] == "v3"
    assert (result["verdict"] == "ALL_FIELDS_CORRECT") == (outcome == "match")


def test_v3_absent_key_fails_and_is_not_treated_as_null():
    answer = json.dumps({k: v for k, v in V3.items() if k != "return_to_home"})
    result = cases.evaluate_answer(answer, V3, "v3")
    assert result["fields"]["return_to_home"] == "missing" and result["verdict"] == "FIELDS_INCORRECT"


def test_v3_changes_only_return_to_home_other_keys_keep_unknown():
    expected = {**V3, "recovery_landing_completed": cases.UNKNOWN}
    assert cases.evaluate_answer(_v3(recovery_landing_completed=cases.UNKNOWN), expected, "v3")["verdict"] == \
        "ALL_FIELDS_CORRECT"
    result = cases.evaluate_answer(_v3(recovery_landing_completed=None), expected, "v3")
    assert result["fields"]["recovery_landing_completed"] == "null_instead_of_unknown"  # still UNKNOWN there


def test_v3_null_with_false_acceptance_criterion_through_view_and_report():
    view = _view(facts={"return_to_home": None}, criteria={"return_home_reached": False})
    assert cases.answer_from_external_view(view, "v3")["return_to_home"] is None
    report = {"run_id": "r1", "status": "FAILED", "executor_result": {"return_to_home": None},
              "analysis": {"checks": {"return_home_reached": False}}}
    assert cases.expected_answer_from_report(report, "v3")["return_to_home"] is None
    for recorded in (True, False):
        view = _view(facts={"return_to_home": recorded}, criteria={"return_home_reached": not recorded})
        assert cases.answer_from_external_view(view, "v3")["return_to_home"] is recorded
    bad = _view(facts={"return_to_home": "false"})  # wrong source type: rejected, answered null in v3
    assert cases.answer_from_external_view(bad, "v3")["return_to_home"] is None


def test_v3_answer_json_schema_matches_the_evaluator_shape_rules():
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(cases.answer_json_schema("v3"))
    assert not list(validator.iter_errors(V3))
    for bad in ({**V3, "return_to_home": "UNKNOWN"}, {k: v for k, v in V3.items() if k != "return_to_home"},
                {**V3, "return_to_home": "false"}, {**V3, "extra": 1}, {**V3, "recovery_landing_completed": None}):
        assert list(validator.iter_errors(bad)), bad
    v2 = Draft202012Validator(cases.answer_json_schema("v2"))
    assert not list(v2.iter_errors(run.FAILED_ANSWER)) and list(v2.iter_errors(V3))


def test_failed_v3_answer_is_derived_from_the_tracked_report():
    report = json.loads((ROOT / cases.CASES["failed-d4519cab"]["tracked"]).read_text())
    assert cases.expected_answer_from_report(report, "v3") == run.FAILED_ANSWER_V3 == V3


def test_contract_never_reads_acceptance_criteria():
    for contract in cases.CONTRACTS.values():
        assert all("acceptance_criteria" not in pointer for pointer, _, _ in contract.values())
        assert set(contract) == set(cases.ANSWER_FIELDS)
    # v3 differs from v2 only in return_to_home, whose source field stays the executor fact.
    assert {k for k in cases.ANSWER_CONTRACT if cases.ANSWER_CONTRACT[k] != cases.ANSWER_CONTRACT_V3[k]} == {"return_to_home"}
    assert cases.ANSWER_CONTRACT_V3["return_to_home"][0] == "/preflights/0/executor_facts/return_to_home"


def test_default_views_are_unchanged_and_external_is_explicit():
    from tools.mission_state import get_mission_state
    bad = get_mission_state(run_id=run.TRIAL_RUN_ID, view="compact")
    assert bad["error_code"] == "INVALID_ARGUMENTS" and "external" in bad["errors"][0]
    assert get_mission_state.__wrapped__.__kwdefaults__["view"] == "detail"  # Python default preserved
    found = get_mission_state(run_id=run.TRIAL_RUN_ID, view="external")
    assert found["status"] == "NOT_FOUND" and found["view"] == "external" and found["preflights"] == []
