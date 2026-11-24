"""The MCP planning tool with a configured interpretation model (TFG_LLM_PROVIDER inside the MCP server process):
the model's intent and its provenance reach LangGraph; a failing or refused model BLOCKS planning (no silent
deterministic substitute, no mission written); credentials never reach the profile, the logs or the result.
Transports are in-process TEST DOUBLES: nothing here is evidence of remote inference."""
from __future__ import annotations

import json
from pathlib import Path
import urllib.error

import pytest
import yaml

from multiagent import models as m
from multiagent.supervisor import hermes_profile as hp
from multiagent.supervisor import mcp_server

SECRET = "mcp-model-secret-0123456789abcdef"
TEXT = ("Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos "
        "sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen.")
INTENT = {"drones_requested": 2, "rovers_requested": 1, "aerial_sectors": 2, "ground_point_count": 3,
          "return_to_start": True}


@pytest.fixture
def server_env(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    key = tmp_path / "key"
    key.write_text(SECRET + "\n")
    key.chmod(0o600)
    monkeypatch.setenv("TFG_SUPERVISOR_OUT", str(out))
    monkeypatch.delenv("EETAC_API_KEY", raising=False)
    return out, key


def transport(outcome, seen):
    def t(url, headers, body, timeout):
        seen.append({"url": url, "auth": headers.get("Authorization")})
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(url, outcome, "err", {}, None)
        return 200, json.dumps({"model": "eetac-llm", "choices": [{"message": {"content": outcome}}]}).encode()
    return t


def test_without_provider_the_planning_only_behaviour_is_unchanged(server_env, monkeypatch):
    monkeypatch.delenv("TFG_LLM_PROVIDER", raising=False)
    res = mcp_server.supervisor_plan_mission(TEXT)
    assert res["status"] == "PLANNED" and res["interpretation"] is None


def test_configured_eetac_intent_reaches_langgraph_with_provenance(server_env, monkeypatch):
    out, key = server_env
    seen = []
    monkeypatch.setattr(m, "urllib_transport", transport(json.dumps(INTENT), seen))
    for k, v in {"TFG_LLM_PROVIDER": "eetac", "TFG_LLM_FALLBACK": "", "EETAC_API_KEY_FILE": str(key),
                 "EETAC_ALLOW_HTTP_OVER_VPN": "raonador.upc.edu"}.items():
        monkeypatch.setenv(k, v)
    res = mcp_server.supervisor_plan_mission(TEXT, intent={"drones_requested": 5})   # Hermes intent is not used
    assert res["status"] == "PLANNED" and len(res["vehicles"]) == 3
    assert res["interpretation"]["provider"] == "eetac" and res["interpretation"]["fallback_used"] is False
    assert seen[0]["url"] == "http://raonador.upc.edu:4000/v1/chat/completions" and seen[0]["auth"] == f"Bearer {SECRET}"
    req = json.loads((out / res["mission_id"] / "request.json").read_text())
    assert req["model_intent"] == INTENT and req["intent_provenance"]["provider"] == "eetac"
    assert req["intent_provenance"]["hermes_intent_received"] is True
    logs = (out / mcp_server.MODEL_CALL_LOG).read_text() + json.dumps(res) + (out / res["mission_id"] / "request.json").read_text()
    assert SECRET not in logs
    evidence = hp.supervisor_model_evidence("eetac", [json.loads(x) for x in (out / mcp_server.MODEL_CALL_LOG).read_text().splitlines()],
                                            {res["mission_id"]: {"status": "PLANNED_PENDING_APPROVAL"}}, out, {})
    assert evidence["ok"] is True


@pytest.mark.parametrize("outcome,expected", [(401, "AUTHENTICATION"), (500, "SERVER_ERROR"),
                                              ("not json at all", "MODEL_INTENT_INVALID")])
def test_model_failure_blocks_planning_without_substitution(server_env, monkeypatch, outcome, expected):
    out, key = server_env
    monkeypatch.setattr(m, "urllib_transport", transport(outcome, []))
    for k, v in {"TFG_LLM_PROVIDER": "eetac", "EETAC_API_KEY_FILE": str(key),
                 "EETAC_ALLOW_HTTP_OVER_VPN": "raonador.upc.edu"}.items():
        monkeypatch.setenv(k, v)
    res = mcp_server.supervisor_plan_mission(TEXT)
    assert res["status"] == "BLOCKED_INTERPRETATION_MODEL" and res["mission_id"] is None
    assert expected in res["reasons"][0] and res["movement_authorized"] is False
    assert not [p for p in out.iterdir() if p.is_dir()]                    # no mission, no plan files


def test_transport_not_accepted_blocks_before_any_request(server_env, monkeypatch):
    out, key = server_env
    seen = []
    monkeypatch.setattr(m, "urllib_transport", transport(json.dumps(INTENT), seen))
    monkeypatch.setenv("TFG_LLM_PROVIDER", "eetac")
    monkeypatch.setenv("EETAC_API_KEY_FILE", str(key))
    monkeypatch.delenv("EETAC_ALLOW_HTTP_OVER_VPN", raising=False)
    res = mcp_server.supervisor_plan_mission(TEXT)
    assert res["status"] == "BLOCKED_INTERPRETATION_MODEL" and seen == []


def test_profile_gets_names_and_paths_never_the_key(tmp_path, server_env):
    out, key = server_env
    env = {"EETAC_API_KEY_FILE": str(key), "EETAC_ALLOW_HTTP_OVER_VPN": "raonador.upc.edu"}
    cfg = hp.config(out=out, python=Path("/usr/bin/python3"), provider="ollama-local", supervisor_provider="eetac",
                    environ=env)
    block = cfg["mcp_servers"][mcp_server.SERVER]["env"]
    assert block["TFG_LLM_PROVIDER"] == "eetac" and block["TFG_LLM_FALLBACK"] == ""
    assert block["EETAC_API_KEY_FILE"] == str(key) and cfg["model"]["base_url"].startswith("http://127.0.0.1")
    assert SECRET not in yaml.safe_dump(cfg) and "EETAC_API_KEY" not in block
    with pytest.raises(SystemExit, match="INSECURE_TRANSPORT_REFUSED"):
        hp.supervisor_model_env("eetac", {"EETAC_API_KEY_FILE": str(key)})
    with pytest.raises(SystemExit, match="_FILE"):
        hp.supervisor_model_env("eetac", {"EETAC_API_KEY": SECRET})


def test_evidence_requires_a_linked_ok_call_without_fallback(tmp_path):
    out = tmp_path
    (out / "M1").mkdir()
    (out / "M1/request.json").write_text(json.dumps({"model_intent": INTENT, "intent_provenance": {
        "status": "MODEL_INTENT", "provider": "eetac", "model": "eetac-llm", "records": [{"run_id": "r1"}]}}))
    missions = {"M1": {"status": "PLANNED_PENDING_APPROVAL"}}
    ok = [{"run_id": "r1", "provider": "eetac", "status": "OK", "fallback": False}]
    assert hp.supervisor_model_evidence("eetac", ok, missions, out, {"EETAC_API_KEY_FILE": "/nonexistent"})["ok"]
    assert not hp.supervisor_model_evidence("eetac", [{**ok[0], "fallback": True}], missions, out, {})["ok"]
    assert not hp.supervisor_model_evidence("eetac", [{**ok[0], "run_id": "other"}], missions, out, {})["ok"]
    assert not hp.supervisor_model_evidence("eetac", [], missions, out, {})["ok"]
    assert hp.supervisor_model_evidence(None, [], missions, out, {})["required"] is False
