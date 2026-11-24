"""Hermes profile for the supervisor: generated config (one MCP server, four planning/status tools, capture plugin, no
credential values), session verdict computed from evidence only, and an OPTIONAL real Hermes session
(TFG_RUN_HERMES_SESSION=1, needs the local Ollama instance on 127.0.0.1:11435 and the tfg-supervisor profile)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from multiagent.supervisor import hermes_profile as hp
from multiagent.supervisor import mcp_server

TEXT = ("Planifica la inspección de una parcela agrícola utilizando dos drones y un rover. Divide el terreno en dos "
        "sectores aéreos y asigna tres puntos terrestres al rover. Todos deben regresar a su punto de origen.")


def test_profile_config_has_only_the_supervisor_server_and_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDA_TOKEN", "secret-value-1234567890")
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    for provider in ("ollama-local", "eetac", "aida-qwen"):
        cfg = hp.config(out=out, python=Path("/usr/bin/python3"), provider=provider)
        assert list(cfg["mcp_servers"]) == [mcp_server.SERVER]
        server = cfg["mcp_servers"][mcp_server.SERVER]
        assert server["tools"]["include"] == list(mcp_server.TOOLS)
        assert not any("approv" in t or "execut" in t for t in server["tools"]["include"])
        assert cfg["platform_toolsets"] == {"cli": [mcp_server.SERVER]} and cfg["fallback_providers"] == []
        text = yaml.safe_dump(cfg)
        assert "secret-value" not in text
    assert cfg["model"]["key_env"] == "AIDA_TOKEN"


def test_prepare_writes_an_existing_profile_and_installs_capture(tmp_path):
    home, out = tmp_path / "profile", tmp_path / "out"
    with pytest.raises(SystemExit):
        hp.prepare(out=out, home=home)
    home.mkdir()
    (home / "config.yaml").write_text("{}")
    out.mkdir(mode=0o700)
    report = hp.prepare(out=out, home=home, python=Path("/usr/bin/python3"))
    assert yaml.safe_load((home / "config.yaml").read_text())["mcp_servers"][mcp_server.SERVER]["env"][
        "TFG_SUPERVISOR_OUT"] == str(out)
    assert all((home / "plugins" / hp.PLUGIN_NAME / f).is_file() for f in hp.PLUGIN_FILES)
    assert report["mcp_tools"] == list(mcp_server.TOOLS)


def test_clean_env_removes_secrets_except_the_configured_key():
    env = hp.clean_env(Path("/h"), base={"PATH": "/bin", "AIDA_TOKEN": "a", "EETAC_API_KEY": "b",
                                         "OPENAI_API_KEY": "c"}, keep=("AIDA_TOKEN",))
    assert env["AIDA_TOKEN"] == "a" and "EETAC_API_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["HERMES_HOME"] == "/h"


def _m(status, manifest=True, problems=(), plans=3):
    return {"status": status, "manifest_present": manifest, "problems": list(problems),
            "plans": {f"p{i}": "x" for i in range(plans)}}


@pytest.mark.parametrize("capture,server,missions,verdict", [
    (["supervisor_registry", "supervisor_plan_mission"], [("supervisor_plan_mission", "OK", "M1", "PLANNED")],
     {"M1": _m("PLANNED_PENDING_APPROVAL")}, "HERMES_USED_SUPERVISOR_PLANNED"),
    (["supervisor_plan_mission"], [("supervisor_plan_mission", "OK", "M1", "REFUSED_UNSAFE")],
     {"M1": _m("REFUSED_UNSAFE", manifest=False, plans=0)}, "HERMES_USED_SUPERVISOR_REFUSED"),
    (["supervisor_registry"], [("supervisor_registry", "OK", None, None)], {}, "SUPERVISOR_NOT_USED_OR_INCOMPLETE"),
    # the answer may claim a plan, but without the server log and the files it does not count
    ([], [], {}, "SUPERVISOR_NOT_USED_OR_INCOMPLETE"),
    (["supervisor_plan_mission"], [("supervisor_plan_mission", "OK", "M1", "PLANNED")],
     {"M1": _m("PLANNED_PENDING_APPROVAL", problems=["PLAN_MODIFIED_AFTER_VALIDATION"])},
     "SUPERVISOR_NOT_USED_OR_INCOMPLETE"),
    (["supervisor_plan_mission"], [("supervisor_plan_mission", "OK", "M9", "PLANNED")], {},
     "SUPERVISOR_NOT_USED_OR_INCOMPLETE"),
])
def test_verdict_uses_evidence_only(capture, server, missions, verdict):
    cap = [{"tool_name": f"mcp__tfg_supervisor__{n}", "status": "ok"} for n in capture]
    calls = [{"tool": t, "status": s, "mission_id": mid, "result_status": rs} for t, s, mid, rs in server]
    assert hp.verdict_of(calls, cap, missions) == verdict


@pytest.mark.skipif(os.environ.get("TFG_RUN_HERMES_SESSION") != "1",
                    reason="real Hermes session: needs the tfg-supervisor profile and the local model "
                           "(TFG_RUN_HERMES_SESSION=1)")
def test_real_hermes_session_uses_the_supervisor(tmp_path):
    out = Path(os.environ.get("TFG_SUPERVISOR_OUT", Path.home() / "tfg-supervisor-runs/out"))
    report = hp.session(text=TEXT, out=out, run_dir=tmp_path / "run", timeout=580)
    assert report["verdict"] == "HERMES_USED_SUPERVISOR_PLANNED", json.dumps(report["server_tool_calls"])
    mission = next(iter(report["missions_created"].values()))
    assert sorted(Path(p).name for p in mission["plans"]) == ["drone_1.plan", "drone_2.plan", "rover.plan"]


# ------------------------------------------------------------------------------------------ text vs real plan
H = "a" * 64


def test_answer_check_separates_text_from_generated_plans():
    missions = {"SUP-20261124T000000Z-0123456789": _m("PLANNED_PENDING_APPROVAL") | {"plans": {"p": H},
                                                                                       "manifest_sha256": "b" * 64}}
    ok = hp.answer_check(f"plan sha {H}", missions, "HERMES_USED_SUPERVISOR_PLANNED")
    assert (ok["planning"], ok["answer_status"]) == ("PLAN_GENERATED", "CONSISTENT_WITH_FILES")
    # a fluent answer with a hash nobody produced is flagged, whatever the verdict
    fake = hp.answer_check(f"drone_1.plan sha256 {'c' * 64}, mission SUP-20261124T000000Z-ffffffffff", missions,
                           "HERMES_USED_SUPERVISOR_PLANNED")
    assert fake["answer_status"] == "CLAIMS_NOT_BACKED_BY_FILES" and len(fake["unbacked_references"]) == 2
    # no plan call: the text is never a plan
    none = hp.answer_check("The mission is PLANNED with three plans.", {}, "SUPERVISOR_NOT_USED_OR_INCOMPLETE")
    assert (none["planning"], none["answer_status"]) == ("PLANNING_INCOMPLETE", "TEXT_ONLY_NOT_A_PLAN")
    assert none["operator_message"].startswith("PLANNING INCOMPLETE")
    echo = hp.answer_check('{"function": "mcp__tfg_supervisor__supervisor_registry", "arguments": {}}', {},
                           "SUPERVISOR_NOT_USED_OR_INCOMPLETE")
    assert echo["answer_status"] == "TOOL_CALL_WRITTEN_AS_TEXT" and echo["text_imitates_tool_call"]


def _fake_runner(verdicts):
    calls = []

    def runner(*, text, out, run_dir, home, timeout):
        verdict = verdicts[len(calls)]
        calls.append(run_dir)
        return {"run_id": f"r{len(calls)}", "verdict": verdict, "missions_created": {},
                "answer_check": hp.answer_check("", {}, verdict)}
    return runner, calls


@pytest.mark.parametrize("verdicts,max_attempts,expected_calls,planning", [
    (["SUPERVISOR_NOT_USED_OR_INCOMPLETE", "HERMES_USED_SUPERVISOR_PLANNED"], 2, 2, "PLAN_GENERATED"),
    (["SUPERVISOR_NOT_USED_OR_INCOMPLETE", "SUPERVISOR_NOT_USED_OR_INCOMPLETE"], 2, 2, "PLANNING_INCOMPLETE"),
    (["SUPERVISOR_NOT_USED_OR_INCOMPLETE"], 1, 1, "PLANNING_INCOMPLETE"),
    (["HERMES_USED_SUPERVISOR_REFUSED", "HERMES_USED_SUPERVISOR_PLANNED"], 2, 1, "REFUSED_BY_SUPERVISOR"),
])
def test_attempts_are_bounded_and_a_refusal_is_never_retried(tmp_path, verdicts, max_attempts, expected_calls,
                                                             planning):
    runner, calls = _fake_runner(verdicts)
    summary = hp.session_with_attempts(text="t", out=tmp_path / "o", run_dir=tmp_path / "run",
                                       max_attempts=max_attempts, runner=runner)
    assert len(calls) == expected_calls and summary["planning"] == planning
    assert [a["attempt"] for a in summary["attempts"]] == list(range(1, expected_calls + 1))
    assert json.loads((tmp_path / "run/attempts.json").read_text())["planning"] == planning


def test_attempt_limit_cannot_be_raised():
    with pytest.raises(SystemExit):
        hp.session_with_attempts(text="t", out=Path("/x"), run_dir=Path("/x/run"), max_attempts=3)


def test_hermes_model_transport_follows_the_provider_policy():
    from multiagent.supervisor import providers
    eetac = {"model": providers.hermes_model_block("eetac")}
    assert not hp.model_transport(eetac, {"EETAC_API_KEY": "k"})["ok"]                # HTTP without opt-in
    ok = hp.model_transport(eetac, {"EETAC_API_KEY": "k", "EETAC_ALLOW_HTTP_OVER_VPN": "raonador.upc.edu"})
    assert ok["ok"] and ok["provider"] == "eetac" and ok["plaintext_optin"]
    assert hp.model_transport({"model": providers.hermes_model_block("ollama-local")}, {})["ok"]
    assert not hp.model_transport({"model": providers.hermes_model_block("aida-qwen")}, {})["ok"]   # no token
