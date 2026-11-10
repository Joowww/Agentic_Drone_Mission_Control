"""Offline integration/evidence contracts, never a test of LLM fidelity."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
import pytest

from tools.hermes_mcp_server import mcp

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "evaluation/hermes_conversation"


def read(name):
    return json.loads((PACK / name).read_bytes())


def record_validator():
    return Draft202012Validator(read("run.schema.json"), format_checker=FormatChecker())


def test_server_initialization_announces_instructions_and_registered_query_contracts():
    # No stdio server, connection, LLM or operational tool invocation.
    options = mcp._lowlevel_server.create_initialization_options()
    assert options.instructions == mcp.instructions and options.instructions
    assert options.server_name == "tfg-mission-control"
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    for name in ("get_mission_state", "get_virtual_preflight"):
        schema = tools[name].input_schema
        assert "run_id" in schema["properties"]
        Draft202012Validator(schema).validate({"run_id": "4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4"})
        assert schema["properties"]["view"]["default"] == "summary"
    assert options.capabilities.tools is not None


def test_scenarios_reference_real_registered_tools_and_never_authorize_flight():
    suite = read("scenarios.json")
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    forbidden = set(suite["global_forbidden_project_tools"])
    assert forbidden <= tools.keys()
    assert suite["status"] == "PREPARED_NOT_EXECUTED"
    assert {case["id"] for case in suite["scenarios"]} == {f"S{i}" for i in range(1, 9)}
    turn_ids = set()
    criterion_ids = set()
    for case in suite["scenarios"]:
        assert case["expected_facts"] and case["must_remain_unknown"]
        for turn in case["turns"]:
            assert turn["id"] not in turn_ids
            turn_ids.add(turn["id"])
            assert set(turn["allowed_project_tools"]) <= tools.keys()
            assert not forbidden.intersection(turn["allowed_project_tools"])
            assert "\n" not in turn["prompt"]
            # Natural prompts do not prescribe a specific API call.
            assert not any(name in turn["prompt"] for name in tools)
            assert turn["required_intents"] and turn["prohibited_effects"]
        for criterion in case["acceptance_criteria"]:
            assert criterion["id"] not in criterion_ids
            criterion_ids.add(criterion["id"])
            assert "structured_tool_arguments_and_results" in criterion["evidence_required"]


@pytest.mark.parametrize("case_id", ["S1", "S2", "S3", "S4"])
def test_draft_expectations_are_valid_arguments_under_the_real_registered_schema(case_id):
    case = next(case for case in read("scenarios.json")["scenarios"] if case["id"] == case_id)
    updates = {}
    for pointer, value in case["expected_facts"].items():
        parts = pointer.lstrip("/").split("/")
        current = updates
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
    schema = next(t.input_schema for t in asyncio.run(mcp.list_tools()) if t.name == "update_mission_draft")
    Draft202012Validator(schema).validate({"updates": updates})
    invalid = deepcopy(updates)
    invalid.setdefault("geometry_intent", {})["altitude_reference"] = "AMSL"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate({"updates": invalid})


def test_record_schema_and_not_run_template_are_valid():
    Draft202012Validator.check_schema(read("run.schema.json"))
    record_validator().validate(read("run.template.json"))


@pytest.mark.parametrize("level", ["SUMMARY_ONLY", "TRANSCRIPT_ONLY"])
def test_summary_or_unstructured_transcript_cannot_be_recorded_as_an_evaluated_pass(level):
    record = read("run.template.json")
    record.update(evidence_level=level, status="INSUFFICIENT_EVIDENCE")
    record_validator().validate(record)
    record["status"] = "PASS"
    with pytest.raises(ValidationError):
        record_validator().validate(record)


def captured_call():
    return {"call_id": "synthetic-call", "turn_id": "S1.T1", "client_tool_name": "registered-alias",
            "project_tool_name": "update_mission_draft", "arguments": {"updates": {"name": "fixture"}},
            "result": {"status": "INCOMPLETE"}, "outcome": "RETURNED",
            "started_at": "2026-10-18T10:00:00Z", "finished_at": "2026-10-18T10:00:01Z",
            "trace_ref": "synthetic-test-fixture", "evidence_source": "STRUCTURED_CAPTURE"}


@pytest.mark.parametrize("damage", ["arguments", "result", "summary_source"])
def test_tool_evidence_requires_structured_arguments_and_results(damage):
    record = read("run.template.json")
    record["tool_calls"] = [captured_call()]
    record_validator().validate(record)
    if damage == "arguments":
        record["tool_calls"][0]["arguments"] = "the agent says it saved a mission"
    elif damage == "result":
        record["tool_calls"][0]["result"] = None
    else:
        record["tool_calls"][0]["evidence_source"] = "AGENT_SUMMARY"
    with pytest.raises(ValidationError):
        record_validator().validate(record)


def test_lost_response_can_be_recorded_without_inventing_a_result():
    record = read("run.template.json")
    call = captured_call()
    call.update(outcome="RESPONSE_LOST", result=None)
    record["tool_calls"] = [call]
    record_validator().validate(record)
    call["result"] = {"status": "invented-success"}
    with pytest.raises(ValidationError):
        record_validator().validate(record)


def test_non_sensitive_record_configuration_rejects_credential_fields():
    record = read("run.template.json")
    record["metadata"]["non_sensitive_config"]["api_key"] = "synthetic-not-a-secret"
    with pytest.raises(ValidationError):
        record_validator().validate(record)
