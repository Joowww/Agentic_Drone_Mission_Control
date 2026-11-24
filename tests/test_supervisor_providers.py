"""Providers (offline): configuration of ollama-local / eetac / aida-qwen / aida-clef, transport policy for credentials,
HTTP errors, timeouts, invalid replies, retries and explicit fallback, records without secrets, Hermes model block,
LangChain wrapper, Clef as advisory only, and the model intent going through the supervisor's reconciliation.

Every transport here is a TEST DOUBLE injected in-process: none of these results is evidence of remote inference.
The remote tests that need credentials are listed in test_remote_* and skipped unless explicitly enabled."""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error

import pytest

from multiagent import models as m
from multiagent.supervisor import providers as pv
from multiagent.supervisor.graph import Supervisor

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "multiagent/fixtures/supervisor/agri_parcel_3v.scenario.json"
SECRET = "test-secret-value-never-logged-0123456789"
TEXT = ("Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos "
        "sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen.")


def reply(content, model="m"):
    return json.dumps({"model": model, "choices": [{"message": {"content": content}}],
                       "usage": {"prompt_tokens": 3}}).encode()


class FakeTransport:
    """Scripted HTTP: a list of outcomes (bytes body | int status | Exception). Records URL and headers seen."""

    def __init__(self, *outcomes):
        self.outcomes, self.seen = list(outcomes), []

    def __call__(self, url, headers, body, timeout):
        self.seen.append({"url": url, "headers": dict(headers), "body": json.loads(body), "timeout": timeout})
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, int):
            raise urllib.error.HTTPError(url, out, "err", {}, None)
        return 200, out


def client(env, transport, **kw):
    return pv.ProviderClient.from_env(env, transport=transport, **kw)


# ------------------------------------------------------------------------------------------ configuration
def test_provider_table_and_defaults():
    s = pv.specs({})
    assert (s["eetac"].base_url, s["eetac"].model, s["eetac"].key_env) == \
        ("http://raonador.upc.edu:4000", "eetac-llm", "EETAC_API_KEY")
    assert (s["aida-qwen"].base_url, s["aida-qwen"].model, s["aida-qwen"].key_env) == \
        ("https://aida-hpc.widening.eu", "qwen", "AIDA_TOKEN")
    assert s["ollama-local"].key_env is None
    with pytest.raises(pv.ProviderRefused, match="UNKNOWN_PROVIDER"):
        pv.ProviderClient.from_env({"TFG_LLM_PROVIDER": "nope"})
    with pytest.raises(pv.ProviderRefused, match="DUPLICATE"):
        pv.ProviderClient.from_env({"TFG_LLM_PROVIDER": "eetac", "TFG_LLM_FALLBACK": "eetac"})


def test_hermes_model_block_names_the_variable_never_the_value():
    env = {"EETAC_API_KEY": SECRET, "AIDA_TOKEN": SECRET}
    eetac, aida, local = (pv.hermes_model_block(n, env) for n in ("eetac", "aida-qwen", "ollama-local"))
    assert eetac == {"provider": "custom", "base_url": "http://raonador.upc.edu:4000/v1", "default": "eetac-llm",
                     "key_env": "EETAC_API_KEY"}
    assert aida["base_url"] == "https://aida-hpc.widening.eu/v1" and aida["key_env"] == "AIDA_TOKEN"
    assert "key_env" not in local and local["base_url"].startswith("http://127.0.0.1")
    assert SECRET not in json.dumps([eetac, aida, local])


# ------------------------------------------------------------------------------------------ transport policy
def test_eetac_key_is_never_sent_over_plain_http_without_optin():
    t = FakeTransport(reply("{}"))
    c = client({"TFG_LLM_PROVIDER": "eetac", "EETAC_API_KEY": SECRET}, t)
    with pytest.raises(pv.ProviderRefused, match="INSECURE_TRANSPORT_REFUSED"):
        c.complete([{"role": "user", "content": "x"}])
    assert t.seen == []                                     # nothing left the process
    assert c.records[0]["status"] == "REFUSED" and SECRET not in json.dumps(c.records)


def test_eetac_optin_is_explicit_host_bound_and_recorded():
    wrong = pv.transport_check(pv.specs()["eetac"], {"EETAC_API_KEY": "k", "EETAC_ALLOW_HTTP_OVER_VPN": "1"})
    assert not wrong["ok"]
    t = FakeTransport(reply("hola", "eetac-llm"))
    env = {"TFG_LLM_PROVIDER": "eetac", "EETAC_API_KEY": SECRET, "EETAC_ALLOW_HTTP_OVER_VPN": "raonador.upc.edu"}
    resp, rec = client(env, t).complete([{"role": "user", "content": "x"}])
    assert resp.text == "hola" and rec["plaintext_optin"].startswith("EETAC_ALLOW_HTTP_OVER_VPN=raonador.upc.edu")
    assert t.seen[0]["url"] == "http://raonador.upc.edu:4000/v1/chat/completions"
    assert t.seen[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert t.seen[0]["body"]["model"] == "eetac-llm"
    assert SECRET not in json.dumps(rec)
    assert os.environ.get("EETAC_API_KEY") != SECRET          # the temporary export is undone


def test_missing_credentials_refuse_without_any_request():
    t = FakeTransport(reply("x"))
    c = client({"TFG_LLM_PROVIDER": "aida-qwen"}, t)
    with pytest.raises(pv.ProviderRefused, match="CREDENTIAL_NOT_SET: AIDA_TOKEN"):
        c.complete([{"role": "user", "content": "x"}])
    assert t.seen == []


def test_aida_qwen_uses_https_bearer_and_choices_content():
    t = FakeTransport(reply("respuesta", "qwen"))
    resp, rec = client({"TFG_LLM_PROVIDER": "aida-qwen", "AIDA_TOKEN": SECRET}, t).complete(
        [{"role": "user", "content": "x"}], run_id="run-1")
    assert t.seen[0]["url"] == "https://aida-hpc.widening.eu/v1/chat/completions"
    assert t.seen[0]["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert resp.text == "respuesta" and rec["run_id"] == "run-1" and rec["provider"] == "aida-qwen"
    assert rec["scheme"] == "https" and rec["plaintext_optin"] is None and rec["data_kind"] == "MODEL_OUTPUT"


# ------------------------------------------------------------------------------------------ errors, retries, fallback
@pytest.mark.parametrize("outcome,cls,code", [
    (401, "AUTHENTICATION", 401), (403, "AUTHENTICATION", 403), (429, "RATE_LIMIT", 429), (500, "SERVER_ERROR", 500),
    (404, "HTTP_ERROR", 404), (TimeoutError("timed out"), "TIMEOUT", None),
    (urllib.error.URLError("refused"), "CONNECTION", None), (b"not json", "INVALID_RESPONSE", None),
    (json.dumps({"choices": []}).encode(), "INVALID_RESPONSE", None)])
def test_errors_are_classified_and_recorded(outcome, cls, code):
    c = client({"TFG_LLM_PROVIDER": "aida-qwen", "AIDA_TOKEN": SECRET}, FakeTransport(outcome))
    with pytest.raises(Exception):
        c.complete([{"role": "user", "content": "x"}])
    rec = c.records[-1]
    assert (rec["status"], rec["error_class"], rec["http_status"]) == ("ERROR", cls, code)
    assert SECRET not in json.dumps(c.records)


def test_retries_only_for_transient_errors():
    t = FakeTransport(TimeoutError("timed out"), reply("ok"))
    resp, rec = client({"TFG_LLM_PROVIDER": "aida-qwen", "AIDA_TOKEN": "k", "TFG_LLM_RETRIES": "1"}, t).complete(
        [{"role": "user", "content": "x"}])
    assert resp.text == "ok" and rec["attempt"] == 1
    c = client({"TFG_LLM_PROVIDER": "aida-qwen", "AIDA_TOKEN": "k", "TFG_LLM_RETRIES": "2"}, FakeTransport(401))
    with pytest.raises(m.AdapterUnavailable):
        c.complete([{"role": "user", "content": "x"}])
    assert len(c.records) == 1                                # authentication errors are not retried


def test_no_silent_fallback_and_explicit_fallback_is_recorded():
    c = client({"TFG_LLM_PROVIDER": "aida-qwen", "AIDA_TOKEN": "k"}, FakeTransport(500, reply("local")))
    with pytest.raises(m.AdapterUnavailable):
        c.complete([{"role": "user", "content": "x"}])
    assert [r["provider"] for r in c.records] == ["aida-qwen"]      # no fallback configured: none happens
    env = {"TFG_LLM_PROVIDER": "aida-qwen", "AIDA_TOKEN": "k", "TFG_LLM_FALLBACK": "ollama-local"}
    c = client(env, FakeTransport(500, reply("local")))
    resp, rec = c.complete([{"role": "user", "content": "x"}])
    assert resp.text == "local" and rec["provider"] == "ollama-local" and rec["fallback"] is True
    assert [(r["provider"], r["status"]) for r in c.records] == [("aida-qwen", "ERROR"), ("ollama-local", "OK")]


def test_records_go_to_a_log_without_prompt_text(tmp_path):
    log = tmp_path / "calls.jsonl"
    c = client({"TFG_LLM_PROVIDER": "ollama-local"}, FakeTransport(reply("ok")), log_path=log)
    c.complete([{"role": "user", "content": "texto del operador"}])
    data = log.read_text()
    assert "texto del operador" not in data and json.loads(data)["prompt_sha256"]


# ------------------------------------------------------------------------------------------ intent + supervisor
def test_model_intent_is_parsed_and_reconciled_by_the_supervisor(tmp_path):
    good = json.dumps({"drones_requested": 2, "rovers_requested": 1, "aerial_sectors": 2, "ground_point_count": 3,
                       "return_to_start": True})
    intent, prov = pv.model_intent(client({"TFG_LLM_PROVIDER": "ollama-local"}, FakeTransport(reply(good))), TEXT)
    assert prov["status"] == "MODEL_INTENT" and intent["aerial_sectors"] == 2
    out = Supervisor(SCENARIO, out_root=tmp_path).plan(TEXT, model_intent=intent, intent_provenance=prov)
    assert out["status"] == "PLANNED"
    req = json.loads((Path(out["mission_dir"]) / "request.json").read_text())
    assert req["intent_provenance"]["provider"] == "ollama-local"
    # a model that contradicts the text cannot change the plan
    bad = json.dumps({"drones_requested": 3})
    intent, prov = pv.model_intent(client({"TFG_LLM_PROVIDER": "ollama-local"}, FakeTransport(reply(bad))), TEXT)
    out = Supervisor(SCENARIO, out_root=tmp_path).plan(TEXT, model_intent=intent, intent_provenance=prov)
    assert out["status"] == "NEEDS_CLARIFICATION"


@pytest.mark.parametrize("text", ["no json here", '{"drones_requested": "two"}', '{"return_to_start": "yes"}',
                                  '{"drones_requested": 99}', "[1, 2]"])
def test_invalid_model_intent_falls_back_to_the_deterministic_reading_and_is_recorded(text):
    intent, prov = pv.model_intent(client({"TFG_LLM_PROVIDER": "ollama-local"}, FakeTransport(reply(text))), TEXT)
    assert intent is None and prov["status"] in ("MODEL_INTENT_INVALID",)


def test_unreachable_provider_gives_no_intent_and_a_record():
    intent, prov = pv.model_intent(client({"TFG_LLM_PROVIDER": "ollama-local"},
                                          FakeTransport(urllib.error.URLError("down"))), TEXT)
    assert intent is None and prov["status"] == "NO_MODEL_INTENT" and prov["error_class"] == "CONNECTION"


def test_langchain_wrapper_uses_the_same_client():
    from langchain_core.messages import HumanMessage
    model = pv.langchain_chat_model(client({"TFG_LLM_PROVIDER": "ollama-local"}, FakeTransport(reply("hola"))))
    out = model.invoke([HumanMessage(content="x")])
    assert out.content == "hola" and out.response_metadata["provider"] == "ollama-local"


# ------------------------------------------------------------------------------------------ Clef (advisory)
QUESTIONS = [{"id": "q1", "question": "Which vehicle class fits task GROUND_rover_01?", "options": ["drone", "rover"]}]


def test_clef_request_shape_and_advisory_result():
    t = FakeTransport(json.dumps({"answers": [{"id": "q1", "probabilities": {"drone": 0.1, "rover": 0.9}}]}).encode())
    rec = pv.ClefAdvisor(transport=t, environ={"AIDA_TOKEN": SECRET}).advise({"task": "visit 3 ground points"},
                                                                              QUESTIONS)
    assert t.seen[0]["url"] == "https://aida-hpc.widening.eu/v1/systemone"
    assert t.seen[0]["body"] == {"model": "clef", "state": {"task": "visit 3 ground points"}, "questions": QUESTIONS}
    assert rec["status"] == "OK" and rec["advice"]["q1"]["top"] == "rover"
    assert rec["authority"].startswith("ADVISORY_ONLY") and rec["schema_status"].startswith("ASSUMED_UNVERIFIED")
    assert SECRET not in json.dumps(rec)


@pytest.mark.parametrize("body", [
    {"answers": [{"id": "q1", "probabilities": {"plane": 1.0}}]},            # option outside the allowed set
    {"answers": [{"id": "q1", "probabilities": {"rover": 1.5}}]},            # probability outside [0, 1]
    {"answers": [{"id": "qX", "probabilities": {"rover": 1.0}}]},            # unknown question
    {"answers": []}, {"something": "else"}])
def test_clef_invalid_replies_are_refused(body):
    rec = pv.ClefAdvisor(transport=FakeTransport(json.dumps(body).encode()), environ={"AIDA_TOKEN": "k"}).advise(
        {}, QUESTIONS)
    assert rec["status"] == "ERROR" and rec["error_class"] == "INVALID_RESPONSE"


def test_clef_without_token_makes_no_request():
    t = FakeTransport(b"{}")
    rec = pv.ClefAdvisor(transport=t, environ={}).advise({}, QUESTIONS)
    assert rec["status"] == "REFUSED" and t.seen == []
    with pytest.raises(ValueError):
        pv.clef_state_request("clef", {}, [{"id": "q", "question": "?", "options": ["only-one"]}])


def test_status_report_shows_requirements_without_values():
    report = pv.status_report({"AIDA_TOKEN": SECRET, "EETAC_API_KEY": SECRET})
    assert report["aida-qwen"]["ok"] and report["aida-qwen"]["credential_present"]
    assert not report["eetac"]["ok"] and "INSECURE_TRANSPORT_REFUSED" in report["eetac"]["problems"][0]
    assert SECRET not in json.dumps(report)


# ------------------------------------------------------------------------------------------ remote (credentials)
REMOTE = pytest.mark.skipif(os.environ.get("TFG_REMOTE_PROVIDER_TESTS") != "1",
                            reason="remote inference needs valid credentials and explicit authorization "
                                   "(TFG_REMOTE_PROVIDER_TESTS=1)")


@REMOTE
@pytest.mark.parametrize("name", ["eetac", "aida-qwen"])
def test_remote_chat_completion(name):
    c = pv.ProviderClient.from_env({**os.environ, "TFG_LLM_PROVIDER": name, "TFG_LLM_FALLBACK": ""})
    resp, rec = c.complete([{"role": "user", "content": "Reply with the single word: ok"}])
    assert rec["status"] == "OK" and rec["provider"] == name and resp.text.strip()


@REMOTE
def test_remote_clef():
    rec = pv.ClefAdvisor().advise({"task": "visit three ground points"}, QUESTIONS)
    assert rec["status"] == "OK", rec


# ------------------------------------------------------------------------------------------ key from a private file
def test_key_file_is_used_only_when_private_and_never_recorded(tmp_path):
    key = tmp_path / "eetac_key"
    key.write_text(SECRET + "\n")
    key.chmod(0o600)
    env = {"TFG_LLM_PROVIDER": "eetac", "EETAC_API_KEY_FILE": str(key), "EETAC_ALLOW_HTTP_OVER_VPN": "raonador.upc.edu"}
    t = FakeTransport(reply("ok", "eetac-llm"))
    resp, rec = client(env, t).complete([{"role": "user", "content": "x"}])
    assert t.seen[0]["headers"]["Authorization"] == f"Bearer {SECRET}" and SECRET not in json.dumps(rec)
    assert "EETAC_API_KEY" not in os.environ
    key.chmod(0o644)
    t2 = FakeTransport(reply("ok"))
    with pytest.raises(pv.ProviderRefused, match="CREDENTIAL_FILE_INVALID"):
        client(env, t2).complete([{"role": "user", "content": "x"}])
    assert t2.seen == []
    inside = ROOT / "multiagent" / "fixtures" / "supervisor" / "README_not_a_key"
    with pytest.raises(pv.SecretFileError):
        pv.resolve_secret("EETAC_API_KEY", {"EETAC_API_KEY_FILE": str(inside)})
