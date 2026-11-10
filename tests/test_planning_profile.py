"""Planning profile (deploy/planner): launcher checks and the TEST DOUBLE provider, without Hermes or network."""
import importlib.util
import json
from pathlib import Path

import pytest

import observability.hermes_capture_run as capture_run

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


home_mod = _load("planner_hermes_home", "deploy/planner/hermes_home.py")
fake = _load("planner_fake_provider", "deploy/planner/doubles/fake_provider.py")


def test_only_the_filtered_template_is_planning_safe():
    base = home_mod.TEMPLATE.read_bytes()
    assert home_mod.config_problems(base)  # no filter, Tool Search on: refused
    safe = home_mod.planning_config(base)
    assert home_mod.config_problems(safe) == []
    extra = safe.replace(b"        - finalize_mission_draft\n",
                         b"        - finalize_mission_draft\n        - start_simulation\n")
    assert any("include" in p for p in home_mod.config_problems(extra))
    other = safe + b"\n"  # a second enabled MCP server
    other = other.replace(b"mcp_servers:\n", b"mcp_servers:\n  other:\n    command: /bin/true\n")
    assert any("other enabled MCP servers" in p for p in home_mod.config_problems(other))
    assert any("plugins" in p for p in home_mod.config_problems(safe + b"plugins:\n  enabled:\n    - x\n"))
    assert home_mod.config_problems(None) == ["config.yaml absent"]


def test_run_refuses_unsafe_homes_and_toolsets_overrides_and_always_fixes_the_toolset(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(home_mod.os, "execve", lambda path, argv, env: calls.append((path, argv, env)))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    assert home_mod.run(["-z", "x", "--toolsets", "terminal"]) == 2 and calls == []
    assert home_mod.run(["-z", "x", "-t", "web"]) == 2 and calls == []
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "config.yaml").write_bytes(home_mod.TEMPLATE.read_bytes())  # never rewritten
    monkeypatch.setenv("HERMES_HOME", str(unsafe))
    assert home_mod.run(["-z", "x"]) == 2 and calls == []
    assert "not planning-safe" in capsys.readouterr().err
    assert (unsafe / "config.yaml").read_bytes() == home_mod.TEMPLATE.read_bytes()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))  # empty home: filtered config created once
    home_mod.run(["-z", "PROMPT"])
    path, argv, env = calls[0]
    assert argv[1:] == ["-z", "PROMPT", "--toolsets", capture_run.MCP_SERVER] and env["HERMES_HOME"].endswith("home")
    assert home_mod.config_problems((tmp_path / "home" / "config.yaml").read_bytes()) == []


def test_test_double_home_never_overwrites_and_is_labelled(tmp_path):
    target = tmp_path / "double"
    assert home_mod.prepare_test_home(target, "http://fake-provider:8000/v1") == 0
    text = (target / "config.yaml").read_text()
    assert text.startswith("# TEST DOUBLE") and "provider: custom" in text and "nous" not in text
    assert home_mod.config_problems(text.encode()) == []
    assert home_mod.prepare_test_home(target, "http://other/v1") == 2


def test_status_separates_complete_and_incomplete_finalizations(tmp_path, monkeypatch, capsys):
    store = tmp_path / "generated"
    draft = store / "drafts" / "d1"
    (draft / "f-complete").mkdir(parents=True)
    (draft / "f-partial").mkdir()
    (draft / "draft.json").write_text(json.dumps({"mission_id": "m1", "vehicle_id": "drone_01"}))
    (draft / "f-complete" / "finalization.json").write_text(json.dumps(
        {"validation": {"mission_status": "FEASIBLE", "execution_status": "APPROVED",
                        "qgc_export": {"status": "REFUSED", "reasons": ["no AMSL"]}}}))
    (draft / "f-partial" / "mission.json").write_text("{}")
    monkeypatch.setattr(home_mod, "STORE", store)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    home_mod.status()
    out = capsys.readouterr().out
    assert "f-complete: completa · validación FEASIBLE/APPROVED · exportación .plan REFUSED (no AMSL)" in out
    assert "f-partial: INCOMPLETA (sin finalization.json; no es un resultado)" in out
    assert "Credenciales del proveedor (auth.json): ABSENT" in out


def test_login_uses_the_homes_own_provider_including_the_unfiltered_trial_home(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(home_mod.os, "execve", lambda path, argv, env: calls.append((argv, env["HERMES_HOME"])))
    trial = tmp_path / "trial"
    trial.mkdir()
    (trial / "config.yaml").write_bytes(home_mod.TEMPLATE.read_bytes())  # base config, not planning-safe
    monkeypatch.setenv("HERMES_HOME", str(trial))
    home_mod.main(["login"])
    assert calls[-1][0][1:] == ["auth", "add", "nous", "--no-browser"] and calls[-1][1] == str(trial)
    assert (trial / "config.yaml").read_bytes() == home_mod.TEMPLATE.read_bytes()  # untouched
    empty = tmp_path / "empty"
    monkeypatch.setenv("HERMES_HOME", str(empty))
    home_mod.main(["login"])  # an empty home gets the planning config first
    assert home_mod.config_problems((empty / "config.yaml").read_bytes()) == []


def test_trial_home_template_passes_the_capture_runner_config_checks(tmp_path):
    home = tmp_path / "trial"
    agent = tmp_path / "agent"
    agent.mkdir()
    monkeypatch_target = home_mod.HERMES_AGENT
    try:
        home_mod.HERMES_AGENT = agent
        assert home_mod.prepare_trial(home) == 0
    finally:
        home_mod.HERMES_AGENT = monkeypatch_target
    assert (home / "hermes-agent").resolve() == agent
    report = capture_run.preflight(home=home, hermes_bin=Path("/bin/true"), trial=True, repo=Path("/opt/tfg"),
                                   trial_case="agri-planning-container", process_lister=lambda: [],
                                   mcp_process_lister=lambda: [])
    checks = {c["check"]: c["ok"] for c in report["checks"]}
    assert checks["config_edit_isolated"] and checks["trial_server_configured"] and checks["trial_case_current"]
    assert checks["no_other_mcp_server_enabled"] and checks["no_plugins_allow_list"]
    assert report["facts"]["provider"] == "nous" and report["facts"]["model"] == "poolside/laguna-s-2.1:free"


def test_container_case_reuses_the_h1_prompt_and_tools_and_pins_current_sources():
    case = capture_run.TRIAL_CASES["agri-planning-container"]
    h1 = capture_run.TRIAL_CASES["agri-planning-h1"]
    assert case["prompt"] == h1["prompt"] and case["tools"] == h1["tools"] and "superseded_by" not in case
    for rel, digest in case["pinned_sources"].items():
        assert capture_run._file_sha(ROOT / rel) == digest, f"{rel} changed: review and re-pin the case"


def test_fake_provider_scripts_update_then_finalize_and_records_no_header_values():
    names = [capture_run.registry_name(t) for t in capture_run.PLANNING_TOOLS]
    body = {"tools": [{"function": {"name": n}} for n in names], "messages": [{"role": "user", "content": "x"}]}
    first = fake._planning_reply(body)
    assert first["tool"].endswith("update_mission_draft") and first["arguments"]["updates"]["mission_id"] == \
        "agri_demo_001_h1_sector_a"
    body["messages"].append({"role": "tool", "content": json.dumps(
        {"draft_id": "0" * 8 + "-0000-4000-8000-" + "0" * 12, "draft_revision": 1})})
    second = fake._planning_reply(body)
    assert second["tool"].endswith("finalize_mission_draft") and second["arguments"]["expected_revision"] == 1
    body["messages"].append({"role": "tool", "content": '{"validation": {"qgc_export": {"status": "REFUSED"}}}'})
    assert "qgc_export status REFUSED" in fake._planning_reply(body)["content"]
    assert "not offered" in fake._planning_reply({"tools": [], "messages": []})["content"]
    with pytest.raises(KeyError):
        fake._message({})
