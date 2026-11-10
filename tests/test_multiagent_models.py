"""Model adapters and tracing: offline by default, injected transports only, no secret in any output."""
import json

import pytest

from multiagent import models
from multiagent.interpreters import BriefRejected, ModelInterpreter, extract_json
from multiagent.tracing import Tracer, opik_dry_run, opik_plan, redact
from observability.langsmith_export import ExportError

SECRET = "sk-test-NEVER-LOGGED-0123456789"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no real network call may happen in these tests")
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("socket.socket.connect", refuse)


class Transport:
    def __init__(self, reply, status=200):
        self.reply, self.status, self.requests = reply, status, []

    def __call__(self, url, headers, body, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "body": json.loads(body), "timeout": timeout})
        return self.status, json.dumps(self.reply).encode()


@pytest.mark.parametrize("adapter", [models.OllamaChatAdapter(), models.aida_qwen(), models.AidaClefAdapter()])
def test_every_network_adapter_is_disabled_by_default(adapter):
    with pytest.raises(models.AdapterDisabled):
        adapter.classify("x") if isinstance(adapter, models.AidaClefAdapter) else adapter.complete([{"role": "user", "content": "x"}])


def test_remote_adapter_without_credential_refuses_before_any_request(monkeypatch):
    monkeypatch.delenv(models.AIDA_KEY_ENV, raising=False)
    transport = Transport({})
    with pytest.raises(models.AdapterDisabled, match=models.AIDA_KEY_ENV):
        models.aida_qwen(enabled=True, transport=transport).complete([{"role": "user", "content": "x"}])
    assert transport.requests == []


def test_ollama_request_shape_and_reported_usage():
    transport = Transport({"model": "qwen3:4b", "message": {"role": "assistant", "content": '{"a": 1}'},
                           "prompt_eval_count": 12, "eval_count": 5, "total_duration": 1000})
    adapter = models.OllamaChatAdapter(enabled=True, transport=transport)
    response = adapter.complete([{"role": "user", "content": "hi"}], json_output=True)
    request = transport.requests[0]
    assert request["url"] == "http://127.0.0.1:11434/api/chat" and request["body"]["format"] == "json"
    assert request["body"]["stream"] is False and request["body"]["options"]["temperature"] == 0.0
    assert "Authorization" not in request["headers"]
    assert response.usage == {"prompt_tokens": 12, "completion_tokens": 5}
    assert response.server_timing == {"unit": "ns", "total_duration": 1000} and response.data_kind == "MODEL_OUTPUT"


def test_aida_qwen_sends_the_key_only_in_the_header_and_never_returns_it(monkeypatch):
    monkeypatch.setenv(models.AIDA_KEY_ENV, SECRET)
    transport = Transport({"model": "qwen", "choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 3}})
    adapter = models.aida_qwen(enabled=True, transport=transport)
    response = adapter.complete([{"role": "user", "content": "hi"}])
    request = transport.requests[0]
    assert request["url"] == "https://aida-hpc.widening.eu/v1/chat/completions" and request["body"]["model"] == "qwen"
    assert request["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert "response_format" not in request["body"]  # JSON mode is not assumed for AIDA
    for blob in (json.dumps(response.metadata()), json.dumps(adapter.info), repr(adapter)):
        assert SECRET not in blob


def test_clef_is_a_classifier_with_probabilities_not_a_chat_model(monkeypatch):
    monkeypatch.setenv(models.AIDA_KEY_ENV, SECRET)
    transport = Transport({"decisions": [{"label": "UNSAFE", "probability": 0.7}, {"label": "FEASIBLE", "probability": 0.3}]})
    adapter = models.AidaClefAdapter(enabled=True, transport=transport)
    response = adapter.classify("Arm the rover now", ["FEASIBLE", "UNSAFE"])
    assert transport.requests[0]["url"] == "https://aida-hpc.widening.eu/v1/systemone"
    assert transport.requests[0]["body"]["model"] == "clef"
    assert response.structured["top"] == "UNSAFE" and response.structured["probability_sum"] == pytest.approx(1.0)
    assert response.structured["schema_status"].startswith("ASSUMED_UNVERIFIED")
    assert not hasattr(adapter, "complete")


@pytest.mark.parametrize("reply", [{"text": "unsafe"}, {"decisions": [{"label": "X", "probability": 1.5}]},
                                   {"probabilities": {"A": True}}])
def test_clef_replies_of_unknown_shape_are_refused_not_guessed(monkeypatch, reply):
    monkeypatch.setenv(models.AIDA_KEY_ENV, SECRET)
    with pytest.raises(models.AdapterSchemaError):
        models.AidaClefAdapter(enabled=True, transport=Transport(reply)).classify("x")


def test_hermes_provider_needs_an_explicit_endpoint(monkeypatch):
    monkeypatch.delenv("TFG_HERMES_PROVIDER_BASE_URL", raising=False)
    with pytest.raises(models.AdapterDisabled, match="base URL"):
        models.hermes_provider()
    adapter = models.hermes_provider(base_url="http://127.0.0.1:9", api_key_env="HERMES_TEST_KEY")
    assert adapter.provider == "hermes:nous" and adapter.model == "poolside/laguna-s-2.1:free" and not adapter.enabled


def test_http_errors_are_infrastructure_and_malformed_replies_are_schema_errors():
    # Since the qwen pilot: an HTTP error is INFRASTRUCTURE (AdapterUnavailable, the case is BLOCKED), not a model
    # error; a 200 reply without the expected fields stays an AdapterSchemaError.
    with pytest.raises(models.AdapterUnavailable, match="HTTP 503"):
        models.OllamaChatAdapter(enabled=True, transport=Transport({}, status=503)).complete([{"role": "user", "content": "x"}])
    with pytest.raises(models.AdapterSchemaError):
        models.OllamaChatAdapter(enabled=True, transport=Transport({"message": None})).complete([{"role": "user", "content": "x"}])


@pytest.mark.parametrize("text, expected", [
    ('<think>let me think {"no": 1}</think>{"a": 1}', {"a": 1}), ('```json\n{"b": 2}\n```', {"b": 2}),
    ("no json here", None), ("[1, 2]", None)])
def test_model_reply_json_extraction(text, expected):
    assert extract_json(text) == expected


def test_model_interpreter_rejects_replies_that_are_not_a_brief():
    adapter = models.ScriptedAdapter(responder=lambda p: '{"aerial_objectives": "everything", "extra": 1}')
    with pytest.raises(BriefRejected, match="NOT_A_BRIEF"):
        ModelInterpreter(adapter, site_points=["POI_1"]).interpret("Inspect POI_1")
    assert "POI_1" in adapter.calls[0]  # the declared site points are given to the model


# --------------------------------------------------------------------------------- tracing --
def test_redaction_of_keys_values_and_size():
    value = redact({"api_key": "x", "Authorization": "Bearer abc", "nested": {"refresh_token": "t"},
                    "note": f"used {SECRET} and Bearer xyz", "prompt_tokens": 12, "credential_env": "AIDA_HPC_API_KEY",
                    "big": "a" * 10000, "many": list(range(300))})
    assert value["api_key"] == value["Authorization"] == value["nested"]["refresh_token"] == "[REDACTED]"
    assert SECRET not in value["note"] and "xyz" not in value["note"]
    assert value["prompt_tokens"] == 12 and value["credential_env"] == "AIDA_HPC_API_KEY"
    assert len(value["big"]) < 4100 and value["many"][-1] == "[100 MORE ITEMS]"


def test_trace_records_agent_model_mission_io_latency_and_status(tmp_path):
    tracer = Tracer(mission_id="M-1", data_kind="SYNTHETIC")
    with tracer.span("drone_swarm_agent", "llm", "allocate", model={"model": "qwen3:4b", "api_key": SECRET},
                     inputs={"prompt": "p"}) as span:
        tracer.output(span, {"ok": True})
    tracer.validation("mission_orchestrator", "coordination_checks", "PASS", [])
    with pytest.raises(RuntimeError):
        with tracer.span("rover_agent", "tool", "boom"):
            raise RuntimeError(f"failed with {SECRET}")
    lines = tracer.write(tmp_path / "trace.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["status"] for r in records] == ["OK", "PASS", "ERROR"]
    assert records[0]["mission_id"] == "M-1" and records[0]["model"]["model"] == "qwen3:4b"
    assert all(r["duration_s"] >= 0 and r["duration_clock"] == "PERF_COUNTER_THIS_PROCESS" for r in records)
    assert SECRET not in "\n".join(lines)


def test_opik_payload_is_a_dry_run_and_synthetic_traces_need_consent():
    from observability import opik_export
    tracer = Tracer(mission_id="M-1", data_kind="SYNTHETIC")
    with tracer.span("mission_orchestrator", "agent", "mission", inputs={"text": "t"}):
        tracer.validation("mission_orchestrator", "screen", "PASS")
    dry = opik_dry_run(tracer.records)
    assert dry["status"] == "DRY_RUN_NOT_SENT" and dry["trace_kinds"] == ["synthetic_fixture"]
    (traces,), (spans,) = dry["bodies"]["traces"], dry["bodies"]["spans"]
    assert len(traces["traces"]) == 1 and len(spans["spans"]) == 2
    assert spans["spans"][1]["parent_span_id"] == spans["spans"][0]["id"]
    plan = opik_plan(tracer.records, "tfg-multiagent")
    with pytest.raises(ExportError, match="synthetic"):
        opik_export.check_export_allowed(plan)
    again = opik_plan(tracer.records, "tfg-multiagent")
    assert [t["id"] for t in again.traces] == [t["id"] for t in plan.traces]  # deterministic ids
