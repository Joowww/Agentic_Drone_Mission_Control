"""Offline tests for the optional Hermes capture plugin.

Synthetic payloads follow the kwargs Hermes passes to post_api_request,
api_request_error and post_tool_call. The contract tests parse the installed
Hermes source with ``ast`` (read-only, never imported or executed); they skip
when that checkout is not present. No Hermes process, model, MCP or network.
"""
import ast
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker
import pytest

import observability.hermes_capture as plugin
from observability.hermes_capture import capture

PACKAGE = Path(capture.__file__).parent
VALIDATOR = Draft202012Validator(json.loads((PACKAGE / "event.schema.json").read_text(encoding="utf-8")),
                                 format_checker=FormatChecker())
HERMES = Path(os.environ.get("TFG_HERMES_AGENT_ROOT", Path.home() / ".hermes" / "hermes-agent"))

SECRET = "sk-ant-THISISAFAKEKEY0123456789abcdef"
PROMPT = "Parcela Loma: HOME 41.27531, 1.98712 altitud 30 m"
PATH = "/home/joelm/TFG/Agentic_Drone_Mission_Control/missions/generated/drafts/x/draft.json"
SENTINELS = (SECRET, PROMPT, PATH, "41.27531", "1.98712", "Parcela", "draft.json", "localhost:11434",
             "raw-session-1", "raw-turn-1", "raw-call-1", "Authorization")


class FakeContext:
    """Records register_hook(hook_name, callback) calls; not a Hermes PluginContext."""

    def __init__(self):
        self.hooks = []

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))


def enabled_env(tmp_path, **extra):
    return {capture.ENABLE_ENV: "1", capture.DIR_ENV: str(tmp_path / "capture"), **extra}


def post_api_kwargs(**override):
    # Shape of agent/turn_response_intake.py:_fire_post_api_request_hook; usage as built by
    # _usage_summary_for_api_request_hook (asdict(CanonicalUsage) without raw_usage + totals).
    kwargs = dict(
        task_id="raw-task-1", turn_id="raw-turn-1", api_request_id="raw-turn-1:api:2", session_id="raw-session-1",
        platform="cli", model="example-org/example-model-1", provider="openrouter",
        base_url=f"http://localhost:11434/v1?key={SECRET}", api_mode="chat_completions",
        api_call_count=2, api_duration=1.25, started_at=1792246298.0, ended_at=1792246299.25,
        first_chunk_at=1792246298.4, finish_reason="tool_calls", message_count=7,
        response_model="example-org/example-model-1",
        response={"model": "example-org/example-model-1", "upstream_provider": "ExampleUpstream",
                  "finish_reason": "tool_calls",
                  "assistant_message": {"role": "assistant", "content": PROMPT, "tool_calls": [
                      {"id": "raw-call-1", "function": {"name": "mcp_tfg_update_mission_draft",
                                                        "arguments": json.dumps({"home": PROMPT, "path": PATH})}}]},
                  "usage": {"input_tokens": 1200}},
        usage={"input_tokens": 1200, "output_tokens": 85, "cache_read_tokens": 0, "cache_write_tokens": 0,
               "reasoning_tokens": 0, "request_count": 1, "prompt_tokens": 1200, "total_tokens": 1285},
        context_length=200000, assistant_message=object(), assistant_content_chars=len(PROMPT),
        assistant_tool_call_count=1, moa_references=[{"text": PROMPT}],
    )
    kwargs.update(override)
    return kwargs


def read_events(tmp_path):
    files = sorted((tmp_path / "capture").glob("hermes-events-*.jsonl"))
    lines = [line for f in files for line in f.read_text(encoding="utf-8").splitlines()]
    return [json.loads(line) for line in lines], "\n".join(lines)


# --- activation -----------------------------------------------------------------------------

@pytest.mark.parametrize("env", [
    {},
    {capture.ENABLE_ENV: "1"},
    {capture.ENABLE_ENV: "true", capture.DIR_ENV: "/tmp/x"},
    {capture.ENABLE_ENV: "1", capture.DIR_ENV: "relative/dir"},
    {capture.DIR_ENV: "/tmp/x"},
])
def test_disabled_unless_explicit_flag_and_absolute_directory(env):
    ctx = FakeContext()
    assert capture.register(ctx, environ=env) is None
    assert ctx.hooks == []


def test_default_process_environment_registers_nothing(monkeypatch):
    monkeypatch.delenv(capture.ENABLE_ENV, raising=False)
    monkeypatch.delenv(capture.DIR_ENV, raising=False)
    ctx = FakeContext()
    plugin.register(ctx)
    assert ctx.hooks == []


def test_enabled_registers_only_observer_hooks_declared_in_manifest(tmp_path):
    ctx = FakeContext()
    capture.register(ctx, environ=enabled_env(tmp_path))
    names = [name for name, _ in ctx.hooks]
    assert names == list(capture.HOOKS)
    # pre_api_request is the only pre_ hook: Hermes discards its return value (contract test below).
    assert not any((name.startswith("pre_") and name != "pre_api_request") or name.startswith("transform_")
                   for name in names)
    manifest = (PACKAGE / "plugin.yaml").read_text(encoding="utf-8")
    declared = [line.strip()[2:] for line in manifest.split("provides_hooks:")[1].splitlines() if line.strip()]
    assert declared == names
    assert not (tmp_path / "capture").exists()  # nothing written until a hook fires


# --- llm_call -------------------------------------------------------------------------------

def test_llm_call_records_provider_usage_latency_and_tool_names_only(tmp_path):
    env = enabled_env(tmp_path, **{capture.RUN_ENV: "run-2026-10-20", capture.CASE_ENV: "S1"})
    sink = capture.register(FakeContext(), environ=env)
    assert sink.on_post_api_request(**post_api_kwargs()) is None
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["event_type"] == "llm_call" and event["schema"] == capture.SCHEMA
    assert (event["provider"], event["model"], event["upstream_provider"]) == (
        "openrouter", "example-org/example-model-1", "ExampleUpstream")
    assert event["usage_source"] == "hermes_normalized_summary"
    assert event["usage"]["input_tokens"] == {"value": 1200, "status": "nonzero_normalized"}
    assert event["usage"]["output_tokens"] == {"value": 85, "status": "nonzero_normalized"}
    assert event["usage"]["total_tokens"] == {"value": 1285, "status": "derived_nonzero"}
    assert "request_count" not in event["usage"]
    assert (event["timing_source"], event["timing_scope"]) == ("hermes_hook_wall_clock", "api_call_from_first_attempt")
    assert event["api_duration_s"] == 1.25
    assert event["first_chunk_offset_s"] == pytest.approx(0.4, abs=1e-6)
    assert event["requested_tool_names"] == ["mcp_tfg_update_mission_draft"]
    assert event["retry_count"] is None and "retry_count" in event["absent_fields"]
    assert (event["run_id"], event["case_id"]) == ("run-2026-10-20", "S1")
    assert event["session_ref"].startswith("sha256:")
    for sentinel in SENTINELS:
        assert sentinel not in raw
    assert "base_url" not in event and "assistant_message" not in event


def test_requested_names_are_read_from_hermes_normalized_tool_calls(tmp_path):
    """Regression (real trial 2026-10-22, plugin 0.4.0 wrote [null]): Hermes hands the hook its
    ToolCall dataclass, serialized as {id, name, arguments, provider_data} with no ``function``."""
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    response = {"assistant_message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "raw-call-1", "name": "tool_call", "arguments": json.dumps({"args": PROMPT}), "provider_data": None},
        {"id": "raw-call-2", "name": SECRET, "arguments": "{}", "provider_data": None}]}}
    sink.on_post_api_request(**post_api_kwargs(response=response))
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["requested_tool_names"] == ["tool_call", None]
    for sentinel in SENTINELS:
        assert sentinel not in raw


def _summary(**counters):
    """A post_api_request usage summary as Hermes builds it: every canonical field present."""
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "reasoning_tokens": 0, "request_count": 1}
    base.update(counters)
    base["prompt_tokens"] = base["input_tokens"] + base["cache_read_tokens"] + base["cache_write_tokens"]
    base["total_tokens"] = base["prompt_tokens"] + base["output_tokens"]
    return base


def test_legitimate_provider_zero_is_kept_but_not_claimed_confirmed(tmp_path):
    # e.g. provider reported reasoning_tokens=0 and cache_read_tokens=0 explicitly
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage=_summary(input_tokens=900, output_tokens=40)))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["usage"]["reasoning_tokens"] == {"value": 0, "status": "zero_unconfirmed"}
    assert event["usage"]["cache_read_tokens"] == {"value": 0, "status": "zero_unconfirmed"}
    assert event["usage"]["prompt_tokens"] == {"value": 900, "status": "derived_nonzero"}
    assert "usage.reasoning_tokens" in event["ambiguous_zero_fields"]
    assert "usage.reasoning_tokens" not in event["absent_fields"]


def test_default_zero_summary_is_kept_as_received_not_turned_into_absence(tmp_path):
    # usage object present but no recognised field: CanonicalUsage defaults, identical on the wire
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage=_summary()))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["usage_source"] == "hermes_normalized_summary" and event["usage"] is not None
    for name in capture.NORMALIZED_USAGE_FIELDS:
        assert event["usage"][name] == {"value": 0, "status": "zero_unconfirmed"}
    for name in capture.DERIVED_USAGE_FIELDS:
        assert event["usage"][name] == {"value": 0, "status": "derived_zero"}
    assert set(event["ambiguous_zero_fields"]) == {f"usage.{name}" for name in capture.USAGE_FIELDS}
    assert not any(field.startswith("usage") for field in event["absent_fields"])


def test_usage_absent_from_the_hook_is_null_never_zero(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage=None, first_chunk_at=None, response=None))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["usage"] is None and event["usage_source"] == "absent"
    assert "usage" in event["absent_fields"] and event["ambiguous_zero_fields"] == []
    assert event["first_chunk_offset_s"] is None and "first_chunk_offset_s" in event["absent_fields"]
    assert event["requested_tool_names"] is None


def test_invalid_or_missing_usage_counters_are_flagged_individually(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage={"input_tokens": -1, "output_tokens": True,
                                                      "total_tokens": "85", "prompt_tokens": 1.5}))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    for name in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens"):
        assert event["usage"][name] == {"value": None, "status": "redacted"}
        assert f"usage.{name}" in event["redacted_fields"]
    for name in ("cache_read_tokens", "cache_write_tokens", "reasoning_tokens"):
        assert event["usage"][name] == {"value": None, "status": "absent"}
        assert f"usage.{name}" in event["absent_fields"]


def test_inconsistent_first_chunk_offset_is_redacted(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(first_chunk_at=1792246300.0))  # after ended_at
    sink.on_post_api_request(**post_api_kwargs(first_chunk_at=1792246297.0))  # before started_at
    events, _ = read_events(tmp_path)
    for event in events:
        VALIDATOR.validate(event)
        assert event["first_chunk_offset_s"] is None and "first_chunk_offset_s" in event["redacted_fields"]


def test_secret_like_or_malformed_identifiers_are_redacted(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path, **{capture.CASE_ENV: PROMPT}))
    sink.on_post_api_request(**post_api_kwargs(model=SECRET, provider="http://evil/key", api_mode="a b",
                                               api_duration=float("nan"), message_count=-3))
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert {"model", "provider", "api_mode", "api_duration_s", "message_count"} <= set(event["redacted_fields"])
    assert event["case_id"] is None
    assert SECRET not in raw and "evil" not in raw and PROMPT not in raw


# --- llm_error ------------------------------------------------------------------------------

def test_api_error_keeps_retry_evidence_and_status_but_drops_message_and_request(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_api_request_error(
        task_id="t", turn_id="raw-turn-1", api_request_id="raw-turn-1:api:2", session_id="raw-session-1",
        platform="cli", model="qwen3:4b", provider="ollama", base_url="http://localhost:11434",
        api_mode="chat_completions", api_call_count=1, api_duration=30.0, started_at=1.0, ended_at=31.0,
        status_code=429, retry_count=1, max_retries=3, retryable=True, reason="rate_limited",
        error={"type": "RateLimitError", "message": f"Authorization: Bearer {SECRET} for {PROMPT}"},
        request={"method": "POST", "body": {"messages": [{"content": PROMPT}], "api_key": SECRET}},
    )
    sink.on_post_api_request(**post_api_kwargs())
    (error, call), raw = read_events(tmp_path)
    VALIDATOR.validate(error)
    assert (error["status_code"], error["retry_count"], error["max_retries"], error["retryable"]) == (429, 1, 3, True)
    assert (error["error_type"], error["model"], error["provider"]) == ("RateLimitError", "qwen3:4b", "ollama")
    assert error["api_request_ref"] == call["api_request_ref"]  # same API call across its retries
    assert call["retry_count"] is None
    for sentinel in SENTINELS:
        assert sentinel not in raw


# --- tool_call ------------------------------------------------------------------------------

# --- opt-in result check (SYNTHETIC results; no real tool) ------------------------------------

CHECK_VALIDATOR = Draft202012Validator(json.loads((PACKAGE / "tool-result-check.schema.json").read_text(encoding="utf-8")),
                                       format_checker=FormatChecker())
TOOL = "mcp__tfg_mission_control__get_mission_state"
SECRET_VALUE = "simulation_navigation_3waypoint_001"


def expectation_env(tmp_path, checks, tool=TOOL):
    path = tmp_path / "expectation.json"
    path.write_text(json.dumps({"schema": capture.EXPECTATION_SCHEMA, "tool_name": tool, "checks": checks}))
    return enabled_env(tmp_path, **{capture.EXPECTATION_ENV: str(path)})


CHECKS = [{"pointer": "/preflights/0/result_status", "expected": "PASSED"},
          {"pointer": "/preflights/0/report/mission_identity/mission_id", "expected": SECRET_VALUE},
          {"pointer": "/preflights/0/report/executor_result/waypoints_completed", "expected": 3},
          {"pointer": "/hardware_authorized", "expected": False},
          {"pointer": "/preflights/1", "absent": True}]


def tool_result(status="PASSED", completed=3, extra=None):
    body = {"hardware_authorized": False, "preflights": [{"result_status": status, "report": {
        "mission_identity": {"mission_id": SECRET_VALUE}, "executor_result": {"waypoints_completed": completed}}}]}
    body.update(extra or {})
    return json.dumps({"result": json.dumps(body)})  # Hermes' MCP handler envelope around the text block


def read_checks(tmp_path):
    files = sorted((tmp_path / "capture").glob("hermes-tool-result-checks-*.jsonl"))
    raw = "".join(p.read_text(encoding="utf-8") for p in files)
    return [json.loads(line) for line in raw.splitlines()], raw


def test_result_check_matches_allow_listed_pointers_and_stores_no_values(tmp_path):
    sink = capture.register(FakeContext(), environ=expectation_env(tmp_path, CHECKS))
    sink.on_post_tool_call(tool_name=TOOL, args={"run_id": PROMPT}, result=tool_result(), tool_call_id="raw-call-1",
                           session_id="raw-session-1", duration_ms=12, status="ok")
    (record,), raw = read_checks(tmp_path)
    CHECK_VALIDATOR.validate(record)
    assert record["result_envelope"] == "result_json_text"
    assert record["counts"] == {"match": 5, "mismatch": 0, "absent": 0}
    assert record["expectation_sha256"] == hashlib.sha256((tmp_path / "expectation.json").read_bytes()).hexdigest()
    assert SECRET_VALUE not in raw and "PASSED" not in raw and PROMPT not in raw  # outcomes only
    (event,), _ = read_events(tmp_path)
    assert event["event_type"] == "tool_call"  # the ordinary event is still written


def test_result_check_reports_a_contradictory_state_type_strictly(tmp_path):
    sink = capture.register(FakeContext(), environ=expectation_env(tmp_path, CHECKS))
    contradicting = tool_result(status="FAILED", completed=True, extra={"preflights": [
        {"result_status": "FAILED", "report": {"executor_result": {"waypoints_completed": True}}}, {"run_id": "x"}]})
    sink.on_post_tool_call(tool_name=TOOL, result=contradicting, status="ok")
    (record,), raw = read_checks(tmp_path)
    CHECK_VALIDATOR.validate(record)
    outcomes = {c["pointer"]: c["outcome"] for c in record["checks"]}
    assert outcomes == {"/preflights/0/result_status": "mismatch",
                        "/preflights/0/report/mission_identity/mission_id": "absent",
                        "/preflights/0/report/executor_result/waypoints_completed": "mismatch",  # True is not 3
                        "/hardware_authorized": "match", "/preflights/1": "mismatch"}
    assert "FAILED" not in raw


@pytest.mark.parametrize("result, envelope", [
    (None, "absent"), ("plain text", "not_json"), (json.dumps({"result": "no json"}), "result_text_not_json"),
    (json.dumps({"error": "boom"}), "no_result_field"),
])
def test_result_check_records_absent_or_unusable_results_as_absent(tmp_path, result, envelope):
    sink = capture.register(FakeContext(), environ=expectation_env(tmp_path, CHECKS))
    sink.on_post_tool_call(tool_name=TOOL, result=result, status="error")
    (record,), raw = read_checks(tmp_path)
    CHECK_VALIDATOR.validate(record)
    assert record["result_envelope"] == envelope
    assert record["counts"]["match"] == 1 and record["counts"]["absent"] == 4  # only the absent-expected pointer matches
    assert "boom" not in raw


def test_result_check_reads_structured_content_and_ignores_other_tools(tmp_path):
    sink = capture.register(FakeContext(), environ=expectation_env(tmp_path, CHECKS))
    sink.on_post_tool_call(tool_name="terminal", result=tool_result(), status="ok")
    assert read_checks(tmp_path)[0] == []
    structured = json.dumps({"result": "summary text", "structuredContent": json.loads(json.loads(tool_result())["result"])})
    sink.on_post_tool_call(tool_name=TOOL, result=structured, status="ok")
    (record,), _ = read_checks(tmp_path)
    assert record["result_envelope"] == "structured_content" and record["counts"]["match"] == 5


@pytest.mark.parametrize("spec", [
    {"schema": "other", "tool_name": TOOL, "checks": CHECKS},
    {"schema": capture.EXPECTATION_SCHEMA, "tool_name": TOOL, "checks": [{"pointer": "/a", "expected": {"x": 1}}]},
    {"schema": capture.EXPECTATION_SCHEMA, "tool_name": TOOL, "checks": [{"pointer": "a/b", "expected": 1}]},
    {"schema": capture.EXPECTATION_SCHEMA, "tool_name": TOOL, "checks": []},
])
def test_invalid_expectation_is_recorded_never_silently_skipped(tmp_path, spec):
    path = tmp_path / "expectation.json"
    path.write_text(json.dumps(spec))
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path, **{capture.EXPECTATION_ENV: str(path)}))
    sink.on_post_tool_call(tool_name=TOOL, result=tool_result(), status="ok")
    (record,), _ = read_checks(tmp_path)
    CHECK_VALIDATOR.validate(record)
    assert record["result_envelope"] == "expectation_invalid" and record["checks"] == []


def _expectation_with_arguments(tmp_path, arguments):
    path = tmp_path / "expectation.json"
    path.write_text(json.dumps({"schema": capture.EXPECTATION_SCHEMA, "tool_name": TOOL, "checks": CHECKS,
                                "arguments": arguments}))
    return enabled_env(tmp_path, **{capture.EXPECTATION_ENV: str(path)})


@pytest.mark.parametrize("args, outcomes", [
    ({"run_id": "run-A", "view": "external"}, ["match", "match"]),
    ({"run_id": "run-B", "view": "external"}, ["mismatch", "match"]),   # another run was queried
    ({"run_id": "run-A"}, ["match", "absent"]),                         # view left to the default
    ({"run_id": ["run-A"], "view": "external"}, ["mismatch", "match"]),  # type-strict
])
def test_argument_checks_verify_the_executed_query_without_storing_it(tmp_path, args, outcomes):
    env = _expectation_with_arguments(tmp_path, [{"key": "run_id", "expected": "run-A"},
                                                 {"key": "view", "expected": "external"}])
    sink = capture.register(FakeContext(), environ=env)
    sink.on_post_tool_call(tool_name=TOOL, args=args, result=tool_result(), status="ok")
    (record,), raw = read_checks(tmp_path)
    CHECK_VALIDATOR.validate(record)
    assert [c["outcome"] for c in record["argument_checks"]] == outcomes
    assert "run-A" not in raw and "run-B" not in raw


@pytest.mark.parametrize("arguments", [[{"key": "run_id"}], [{"key": "run_id", "expected": 3}],
                                       [{"key": "a b", "expected": "x"}], "run_id"])
def test_malformed_argument_expectations_are_invalid(tmp_path, arguments):
    sink = capture.register(FakeContext(), environ=_expectation_with_arguments(tmp_path, arguments))
    sink.on_post_tool_call(tool_name=TOOL, args={}, result=tool_result(), status="ok")
    (record,), _ = read_checks(tmp_path)
    assert record["result_envelope"] == "expectation_invalid"


def test_no_expectation_means_no_result_check_file(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_tool_call(tool_name=TOOL, result=tool_result(), status="ok")
    assert not list((tmp_path / "capture").glob("hermes-tool-result-checks-*.jsonl"))


def test_tool_call_keeps_name_duration_status_and_drops_args_and_result(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_tool_call(
        tool_name="mcp_tfg_update_mission_draft", args={"updates": {"home_latitude": 41.27531}, "path": PATH},
        result=json.dumps({"draft": PROMPT, "error": f"bad {SECRET}"}), task_id="t", session_id="raw-session-1",
        tool_call_id="raw-call-1", turn_id="raw-turn-1", api_request_id="r", duration_ms=742, status="error",
        error_type="tool_error", error_message=f"{PROMPT} {PATH}", middleware_trace=[{"note": PROMPT}],
    )
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert (event["tool_name"], event["duration_ms_received"], event["duration_ms_measured"],
            event["duration_source"], event["status"], event["error_type"]) == (
        "mcp_tfg_update_mission_draft", 742, 742, "hermes_reported_ms", "error", "tool_error")
    for sentinel in SENTINELS:
        assert sentinel not in raw


OFFER_VALIDATOR = Draft202012Validator(json.loads((PACKAGE / "tool-offer.schema.json").read_text(encoding="utf-8")),
                                       format_checker=FormatChecker())


def pre_api_kwargs(request):
    # Shape of agent/turn_api_request.py:_fire_pre_api_request_hook (the parts we read plus content).
    return dict(task_id="raw-task-1", turn_id="raw-turn-1", api_request_id="raw-turn-1:api:1",
                session_id="raw-session-1", user_message=PROMPT, conversation_history=[{"content": PROMPT}],
                platform="cli", model="m", provider="nous", base_url=f"http://localhost:11434/v1?key={SECRET}",
                api_mode="chat_completions", api_call_count=1, retry_count=0,
                request_messages=[{"role": "user", "content": PROMPT}], system_prompt=PATH, message_count=2,
                tool_count=1, approx_input_tokens=10, request_char_count=99, max_tokens=None, started_at=1.0,
                middleware_trace=[], request=request)


def read_offers(tmp_path):
    files = sorted((tmp_path / "capture").glob("hermes-tool-offers-*.jsonl"))
    raw = "".join(p.read_text(encoding="utf-8") for p in files)
    return [json.loads(line) for line in raw.splitlines()], raw


def test_tool_offer_keeps_only_offered_names_and_count_in_a_separate_file(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    tool = {"type": "function", "function": {"name": "mcp__tfg_mission_control__get_mission_state",
                                             "description": f"{PROMPT} {PATH}",
                                             "parameters": {"properties": {SECRET: {"description": PROMPT}}}}}
    sink.on_pre_api_request(**pre_api_kwargs({"method": "POST", "body": {
        "model": "m", "messages": [{"role": "user", "content": PROMPT}], "tools": [tool]}}))
    (offer,), raw = read_offers(tmp_path)
    OFFER_VALIDATOR.validate(offer)
    assert (offer["offered_tool_names"], offer["tool_count"], offer["offered_tool_names_source"]) == (
        ["mcp__tfg_mission_control__get_mission_state"], 1, "request_body_tools")
    assert not list((tmp_path / "capture").glob("hermes-events-*.jsonl"))  # event files keep their schema
    for sentinel in SENTINELS:
        assert sentinel not in raw


@pytest.mark.parametrize("request_payload, names, source", [
    ({"body": {"messages": []}}, [], "request_body_without_tools"),          # Hermes omits tools when none
    ({"body": {"tools": [{"function": {"name": SECRET}}, {"name": "ok_tool"}]}}, [None, "ok_tool"],
     "request_body_tools"),
    ({"body": {"tools": "not-a-list"}}, None, "unreadable"),
    (None, None, "absent"),
])
def test_tool_offer_distinguishes_no_tools_from_unknown_and_redacts_names(tmp_path, request_payload, names, source):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_pre_api_request(**pre_api_kwargs(request_payload))
    (offer,), raw = read_offers(tmp_path)
    OFFER_VALIDATOR.validate(offer)
    assert (offer["offered_tool_names"], offer["offered_tool_names_source"]) == (names, source)
    assert ("offered_tool_names" in offer["redacted_fields"]) == (names is not None and None in names)
    assert ("offered_tool_names" in offer["absent_fields"]) == (names is None)
    assert SECRET not in raw


@pytest.mark.parametrize("kwargs, received, source, listed", [
    ({"duration_ms": 0, "status": "blocked"}, 0, "zero_default_or_below_1ms", "ambiguous_zero_fields"),
    ({"duration_ms": 0, "status": "ok"}, 0, "zero_default_or_below_1ms", "ambiguous_zero_fields"),
    ({"duration_ms": 30000, "status": "timeout"}, 30000, "timeout_configured_not_measured", None),
    ({"status": "ok"}, None, "absent", "absent_fields"),
    ({"duration_ms": -5, "status": "ok"}, None, "redacted", "redacted_fields"),
])
def test_tool_durations_that_are_not_measurements_are_never_measured(tmp_path, kwargs, received, source, listed):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_tool_call(tool_name="terminal", **kwargs)
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["duration_ms_received"] == received
    assert event["duration_ms_measured"] is None and event["duration_source"] == source
    if listed:
        assert "duration_ms" in event[listed]


# --- containment ----------------------------------------------------------------------------

def test_write_failures_never_raise_or_print(tmp_path, capfd):
    blocker = tmp_path / "capture"
    blocker.write_text("not a directory", encoding="utf-8")
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    assert sink.on_post_api_request(**post_api_kwargs()) is None
    assert sink.on_post_tool_call(tool_name="x", args={"secret": SECRET}) is None
    assert sink.on_api_request_error(error={"message": SECRET}) is None
    assert sink.failures == 3
    assert blocker.read_text(encoding="utf-8") == "not a directory"
    out, err = capfd.readouterr()
    assert out == "" and err == ""


def test_successful_capture_writes_nothing_to_stdout_or_stderr(tmp_path, capfd):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs())
    sink.on_post_tool_call(tool_name="x", duration_ms=3, status="ok")
    assert capfd.readouterr() == ("", "")


def test_unexpected_payload_types_never_raise(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(response=["not", "a", "dict"], usage=["x"], started_at="soon", first_chunk_at=2)
    sink.on_api_request_error(error="plain string", status_code="500")
    (llm, error), _ = read_events(tmp_path)
    VALIDATOR.validate(llm)
    VALIDATOR.validate(error)
    assert sink.failures == 0 and error["status_code"] is None and "status_code" in error["redacted_fields"]


def test_files_are_private_append_only_and_lines_stay_whole_under_threads(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: sink.on_post_tool_call(tool_name=f"tool_{i}", duration_ms=i + 1, status="ok"),
                      range(64)))
    events, _ = read_events(tmp_path)
    assert len(events) == 64 and {e["duration_ms_measured"] for e in events} == set(range(1, 65))
    (path,) = (tmp_path / "capture").glob("*.jsonl")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "capture").stat().st_mode) == 0o700


def test_symlinked_event_file_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep", encoding="utf-8")
    directory = tmp_path / "capture"
    directory.mkdir(mode=0o700)
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    day = capture.datetime.now(capture.timezone.utc).isoformat()[:10]
    (directory / f"hermes-events-{day}.jsonl").symlink_to(target)
    sink.on_post_tool_call(tool_name="x")
    assert target.read_text(encoding="utf-8") == "keep"
    assert sink.failures == 1


# --- static contract with the installed Hermes source (read-only, never imported) -----------

requires_hermes = pytest.mark.skipif(not (HERMES / "hermes_cli" / "plugins.py").is_file(),
                                     reason=f"Hermes source not found at {HERMES}")


def _tree(relative):
    return ast.parse((HERMES / relative).read_text(encoding="utf-8"))


def _function(tree, name):
    return next(node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def _hook_call_keywords(relative, function, hook):
    calls = [node for node in ast.walk(_function(_tree(relative), function)) if isinstance(node, ast.Call)
             and ast.unparse(node.func).split(".")[-1] in {"invoke_hook", "_invoke_hook"}  # not has_hook()
             and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == hook]
    assert len(calls) == 1, f"{relative}:{function} must dispatch {hook} exactly once"
    return {kw.arg for kw in calls[0].keywords if kw.arg}, [kw.value for kw in calls[0].keywords if kw.arg is None]


def _class_fields(relative, name):
    node = next(n for n in ast.walk(_tree(relative)) if isinstance(n, ast.ClassDef) and n.name == name)
    return {s.target.id: s.value for s in node.body if isinstance(s, ast.AnnAssign)}


@requires_hermes
def test_hermes_commit_matches_the_reviewed_contract_or_is_reported():
    head = (HERMES / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        head = (HERMES / ".git" / head[5:]).read_text(encoding="utf-8").strip()
    if head != capture.VERIFIED_HERMES_COMMIT:
        pytest.skip(f"Hermes {head[:10]} differs from reviewed {capture.VERIFIED_HERMES_COMMIT[:10]}; "
                    "structural contract tests below still run")


@requires_hermes
def test_hermes_declares_our_hooks_and_plugin_registration_api():
    tree = _tree("hermes_cli/plugins.py")
    valid = next(node.value for node in ast.walk(tree) if isinstance(node, ast.AnnAssign)
                 and getattr(node.target, "id", None) == "VALID_HOOKS")
    names = {elt.value for elt in valid.elts if isinstance(elt, ast.Constant)}
    assert set(capture.HOOKS) <= names
    register_hook = _function(tree, "register_hook")
    assert [a.arg for a in register_hook.args.args] == ["self", "hook_name", "callback"]
    loader = (HERMES / "hermes_cli" / "plugins_loader.py").read_text(encoding="utf-8")
    assert 'getattr(module, "register", None)' in loader and "register_fn(ctx)" in loader
    assert "submodule_search_locations=[str(plugin_dir)]" in loader  # relative ``from .capture`` import
    discovery = (HERMES / "hermes_cli" / "plugins_discovery.py").read_text(encoding="utf-8")
    assert 'get_hermes_home() / "plugins"' in discovery and "not in plugins.enabled" in discovery
    manifest = (HERMES / "hermes_cli" / "plugins_manifest.py").read_text(encoding="utf-8")
    assert 'data.get("name", plugin_dir.name)' in manifest and 'data.get("provides_hooks"' in manifest


@requires_hermes
def test_post_api_request_payload_provides_every_field_we_read():
    keywords, spread = _hook_call_keywords("agent/turn_response_intake.py", "_fire_post_api_request_hook",
                                           "post_api_request")
    read = {"session_id", "task_id", "turn_id", "api_request_id", "provider", "model", "response_model",
            "api_mode", "finish_reason", "api_duration", "started_at", "ended_at", "first_chunk_at",
            "api_call_count", "message_count", "assistant_tool_call_count", "context_length", "usage", "response"}
    assert read <= keywords and not spread and "retry_count" not in keywords
    payload = _function(_tree("agent/api_request_hooks.py"), "_api_response_payload_for_hook")
    keys = {k.value for d in ast.walk(payload) if isinstance(d, ast.Dict) for k in d.keys if isinstance(k, ast.Constant)}
    assert {"upstream_provider", "assistant_message", "tool_calls"} <= keys
    usage = _class_fields("agent/usage_pricing.py", "CanonicalUsage")
    derived = ast.unparse(_function(_tree("agent/api_request_hooks.py"), "_usage_summary_for_api_request_hook"))
    assert set(capture.USAGE_FIELDS) <= set(usage) | {"prompt_tokens", "total_tokens"}
    assert "summary['prompt_tokens']" in derived and "summary['total_tokens']" in derived  # ast.unparse quoting
    assert set(capture.NORMALIZED_USAGE_FIELDS) <= set(usage)
    assert all(isinstance(usage[f], ast.Constant) and usage[f].value == 0 for f in capture.NORMALIZED_USAGE_FIELDS)
    # Why a received 0 stays unconfirmed: provider zero and missing field both fall back to 0,
    # and the raw provider usage is removed before the hook sees the summary.
    pricing = _tree("agent/usage_pricing.py")
    assert ast.unparse(_function(pricing, "_first_nonzero")).rstrip().endswith("if v), 0)")
    assert 'summary.pop("raw_usage", None)' in (HERMES / "agent" / "api_request_hooks.py").read_text(encoding="utf-8")
    canonical = next(n for n in ast.walk(pricing) if isinstance(n, ast.ClassDef) and n.name == "CanonicalUsage")
    properties = {f.name for f in canonical.body if isinstance(f, ast.FunctionDef)
                  and any(ast.unparse(d) == "property" for d in f.decorator_list)}
    assert set(capture.DERIVED_USAGE_FIELDS) <= properties  # sums computed by Hermes, not provider fields


@requires_hermes
def test_pre_api_request_provides_tool_count_and_request_and_its_result_is_discarded():
    keywords, spread = _hook_call_keywords("agent/turn_api_request.py", "_fire_pre_api_request_hook",
                                           "pre_api_request")
    assert {"session_id", "task_id", "turn_id", "api_request_id", "api_call_count", "tool_count",
            "request"} <= keywords and not spread
    fire = _function(_tree("agent/turn_api_request.py"), "_fire_pre_api_request_hook")
    calls = [n for n in ast.walk(fire) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and ast.unparse(n.value.func).endswith("invoke_hook")]
    assert len(calls) == 1  # a bare expression statement: Hermes ignores what the plugin returns
    payload = ast.unparse(_function(_tree("agent/api_request_hooks.py"), "_api_request_payload_for_hook"))
    assert "'body': body" in payload  # the request body (with its 'tools' list) is what we read names from


@requires_hermes
def test_hook_tool_calls_are_normalized_tool_call_dataclasses_with_top_level_name():
    fields = _class_fields("agent/transports/types.py", "ToolCall")
    assert {"id", "name", "arguments"} <= set(fields) and "function" not in fields  # function is a property
    payload = ast.unparse(_function(_tree("agent/api_request_hooks.py"), "_api_response_payload_for_hook"))
    assert "getattr(assistant_message, 'tool_calls', None)" in payload
    jsonable = ast.unparse(_function(_tree("agent/api_request_hooks.py"), "_hook_jsonable"))
    assert "asdict(value)" in jsonable  # dataclasses serialize by fields, properties are dropped


@requires_hermes
def test_api_request_error_payload_provides_retry_evidence():
    keywords, spread = _hook_call_keywords("agent/api_request_hooks.py", "_invoke_api_request_error_hook",
                                           "api_request_error")
    assert {"provider", "model", "api_mode", "api_duration", "started_at", "ended_at", "api_call_count",
            "status_code", "retry_count", "max_retries", "retryable", "reason", "error", "api_request_id"} <= keywords
    assert not spread


@requires_hermes
def test_post_tool_call_payload_and_zero_default_duration():
    keywords, spread = _hook_call_keywords("model_tools.py", "_emit_post_tool_call_hook", "post_tool_call")
    assert {"tool_name", "duration_ms", "status", "error_type"} <= keywords
    assert len(spread) == 1 and "_CallIds" in ast.unparse(spread[0])
    assert {"task_id", "session_id", "tool_call_id", "turn_id", "api_request_id"} <= set(
        _class_fields("model_tools.py", "_CallIds"))
    emit = _function(_tree("model_tools.py"), "_emit_post_tool_call_hook")
    defaults = dict(zip((a.arg for a in emit.args.kwonlyargs), emit.args.kw_defaults))
    assert isinstance(defaults["duration_ms"], ast.Constant) and defaults["duration_ms"].value == 0
    executor = (HERMES / "agent" / "tool_executor.py").read_text(encoding="utf-8")
    assert 'duration_ms=int(timeout_s * 1000), status="timeout"' in executor


@requires_hermes
def test_post_tool_call_result_is_the_mcp_handler_json_envelope():
    keywords, _ = _hook_call_keywords("model_tools.py", "_emit_post_tool_call_hook", "post_tool_call")
    assert "result" in keywords
    render = ast.unparse(_function(_tree("tools/mcp_tool_handlers.py"), "_render_call_tool_result"))
    assert "json.dumps({'result': text_result}" in render  # text block(s) under "result"
    assert "'structuredContent' if text_result else 'result'" in render  # structured data alongside or instead


@requires_hermes
def test_api_call_identity_and_start_are_shared_by_retries():
    loop = (HERMES / "agent" / "conversation_loop.py").read_text(encoding="utf-8")
    assert "s.api_start_time, s.retry_count, s.max_retries = time.time(), 0" in loop
    assert 'f"{s.turn_id}:api:{s.api_call_count}"' in loop
    request = (HERMES / "agent" / "turn_api_request.py").read_text(encoding="utf-8")
    assert "agent._last_api_first_chunk_at = None" in request  # reset per attempt, start is not


# --- sink provenance record --------------------------------------------------------------

def _named_context(module, name):
    cls = type(name, (), {"register_hook": lambda self, hook, callback: None})
    cls.__module__ = module
    return cls()


@pytest.mark.parametrize("ctx, origin", [
    (lambda: _named_context("hermes_cli.plugins", "PluginContext"), "hermes_plugin_context"),
    (lambda: FakeContext(), "non_hermes_context"),
])
def test_sink_writes_one_private_provenance_record_before_its_first_event(tmp_path, ctx, origin):
    sink = capture.register(ctx(), environ=enabled_env(tmp_path))
    assert not (tmp_path / "capture").exists()  # nothing until an event arrives
    sink.on_post_api_request(**post_api_kwargs())
    sink.on_post_tool_call(tool_name="x", duration_ms=3, status="ok")
    (record_path,) = (tmp_path / "capture").glob("capture-provenance-*.json")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["origin"] == origin and record["schema"] == capture.PROVENANCE_SCHEMA
    assert record["capture_schema"] == capture.SCHEMA and record["sink_id"] == sink.sink_id
    assert record_path.name == f"capture-provenance-{sink.sink_id}.json"
    assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
    events, raw = read_events(tmp_path)
    assert record["created_at_utc"] <= min(e["recorded_at_utc"] for e in events)
    assert set(record) == {"schema", "origin", "context_type", "plugin", "plugin_version", "capture_schema",
                           "verified_hermes_commit", "sink_id", "created_at_utc"}


def test_direct_sink_is_labelled_direct(tmp_path):
    sink = capture.JsonlSink(tmp_path / "capture")
    sink.on_post_tool_call(tool_name="x", duration_ms=1, status="ok")
    (record_path,) = (tmp_path / "capture").glob("capture-provenance-*.json")
    assert json.loads(record_path.read_text())["origin"] == "direct_jsonl_sink"
