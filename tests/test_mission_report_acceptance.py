"""Offline tests for observability.mission_report_acceptance.validate_mission_report.

The observed result is the real external view archived in the v2 preparation (byte-identical to what
the model receives in v3/v4); call records and answers are SYNTHETIC. No Hermes, MCP or provider."""
import copy
import json
from pathlib import Path

import pytest

from observability import hermes_capture_run as run
from observability.mission_report_acceptance import NOT_VALIDATED, TOOL, VALIDATED, validate_mission_report

ROOT = Path(__file__).resolve().parents[1]
VIEW = json.loads((ROOT / "evaluation" / "observability" / "hermes_mcp_structured_trial_v2_prepared_2026_10_23"
                   / "tool_result_external_view.json").read_text())
RUN = run.FAILED_RUN_ID
ANSWER = json.dumps(run.FAILED_ANSWER_V3)


def _call(name=TOOL, status="ok", run_id=RUN, view="external", result=VIEW):
    return {"tool_name": name, "status": status, "args": {"run_id": run_id, "view": view}, "result": result}


def _validate(calls, answer=ANSWER, contract="v3"):
    return validate_mission_report(answer_text=answer, intended_run_id=RUN, observed_calls=calls, contract=contract)


def test_one_observed_correct_query_and_a_matching_answer_is_validated():
    result = _validate([_call()])
    assert (result["status"], result["reasons"]) == (VALIDATED, [])
    assert result["answer"]["verdict"] == "ALL_FIELDS_CORRECT" and "prueba_hermes_001" not in json.dumps(result)


def test_result_can_be_hermes_mcp_envelope_text():
    envelope = json.dumps({"result": json.dumps(VIEW)})
    assert _validate([_call(result=envelope)])["status"] == VALIDATED


@pytest.mark.parametrize("calls, reason", [
    ([], "NO_TOOL_EXECUTED"),                                  # the v3 08:53 pattern
    ([_call(), _call()], "MORE_THAN_ONE_TOOL_CALL"),
    ([_call(name="terminal")], "WRONG_TOOL"),
    ([_call(status="error")], "TOOL_NOT_SUCCESSFUL"),
    ([_call(run_id="0844c190-59c8-40cf-991e-93cebbd3cf02")], "ARGUMENTS_NOT_AS_INTENDED"),
    ([_call(view="summary")], "ARGUMENTS_NOT_AS_INTENDED"),
    ([_call(result=None)], "RESULT_NOT_AVAILABLE"),
    ([_call(result="not json")], "RESULT_NOT_AVAILABLE"),
])
def test_a_correct_answer_without_a_valid_observed_query_is_never_validated(calls, reason):
    result = _validate(calls)  # the answer is fully correct for this run
    assert result["status"] == NOT_VALIDATED and reason in result["reasons"]
    if reason in ("NO_TOOL_EXECUTED", "MORE_THAN_ONE_TOOL_CALL", "RESULT_NOT_AVAILABLE"):
        assert result["answer"]["verdict"] == "NOT_COMPARED_NO_VALID_QUERY"


@pytest.mark.parametrize("mutate, reason", [
    (lambda v: v.update(external_schema_version=1), "RESULT_NOT_EXTERNAL_SCHEMA_2"),
    (lambda v: v["queried"].update(run_id="other"), "RESULT_NOT_FOR_INTENDED_RUN"),
    (lambda v: v["preflights"][0]["identity"].update(run_id="other"), "RESULT_NOT_FOR_INTENDED_RUN"),
    (lambda v: v.update(rejected_fields=["preflights/0/executor_facts/return_to_home"]), "RESULT_HAS_REJECTED_FIELDS"),
])
def test_a_result_for_another_query_or_schema_is_not_validated(mutate, reason):
    view = copy.deepcopy(VIEW)
    mutate(view)
    result = _validate([_call(result=view)])
    assert result["status"] == NOT_VALIDATED and result["reasons"] == [reason]


@pytest.mark.parametrize("answer, reason", [
    (json.dumps({**run.FAILED_ANSWER_V3, "return_to_home": False}), "ANSWER_NOT_VALID"),   # deduced from criteria
    (json.dumps({**run.FAILED_ANSWER_V3, "return_to_home": "UNKNOWN"}), "ANSWER_NOT_VALID"),  # v2 spelling in v3
    (json.dumps({k: v for k, v in run.FAILED_ANSWER_V3.items() if k != "return_to_home"}), "ANSWER_NOT_VALID"),
    ("FAILED", "ANSWER_NOT_PARSEABLE"),
    ("", "ANSWER_NOT_PARSEABLE"),
])
def test_invalid_structured_output_after_a_valid_query_is_not_validated(answer, reason):
    result = _validate([_call()], answer=answer)
    assert result["status"] == NOT_VALIDATED and result["reasons"] == [reason]


def test_answer_values_are_compared_with_the_observed_result_not_with_a_fixed_expectation():
    view = copy.deepcopy(VIEW)
    view["preflights"][0]["executor_facts"]["return_to_home"] = True   # a different (synthetic) record
    assert _validate([_call(result=view)])["reasons"] == ["ANSWER_NOT_VALID"]
    answer = json.dumps({**run.FAILED_ANSWER_V3, "return_to_home": True})
    assert _validate([_call(result=view)], answer=answer)["status"] == VALIDATED
