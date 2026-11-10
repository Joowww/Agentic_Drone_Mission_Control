"""Local Hermes + Ollama planning demo: profile config, recorded turns, review and view (no Hermes, no model)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

from observability import hermes_capture_run as hcr
from observability import local_planning_demo as demo
from observability.hermes_capture import capture

ROOT = Path(__file__).resolve().parents[1]
AGENT = hcr.DEFAULT_HOME / "hermes-agent"
UPDATE = "mcp__tfg_demo_planning__update_mission_draft"
FINALIZE = "mcp__tfg_demo_planning__finalize_mission_draft"


@pytest.fixture
def profile(tmp_path):
    home = tmp_path / "profiles" / demo.PROFILE_NAME
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("model:\n  provider: nous\n")
    (home / "profile.yaml").write_text("description: test\n")
    (home / ".env").write_text("# no secrets\n")
    data = tmp_path / "data"
    demo.prepare_profile(home=home, repo=ROOT, python=Path(sys.executable), data_root=data)
    return home, data


def _failing(home):
    report = demo.verify_profile(home=home, repo=ROOT, agent=AGENT)
    failing = {c["check"] for c in report["checks"] if not c["ok"]}
    if not AGENT.is_dir():  # Hermes is not installed on every machine that runs the suite
        failing.discard("hermes_sources_verified")
    return failing


def _edit(home, change):
    config = yaml.safe_load((home / "config.yaml").read_text())
    change(config)
    (home / "config.yaml").write_text(yaml.safe_dump(config))


def test_case_is_registered_with_two_turns_and_the_planning_server():
    case = hcr.TRIAL_CASES[demo.CASE]
    assert case["server"] == "tfg-demo-planning" and case["tools"] == ("update_mission_draft", "finalize_mission_draft")
    assert len(case["prompts"]) == 2 and case["local_demo"]
    for omitted in ("reserva mínima", "viento máximo", "altitud máxima"):
        assert omitted not in case["prompts"][0] and omitted in case["prompts"][1]
    assert demo.registry_names() == sorted([UPDATE, FINALIZE])


def test_historical_cases_keep_the_full_server_prefix():
    assert hcr.registry_name("get_mission_state") == "mcp__tfg_mission_control__get_mission_state"
    assert hcr.case_server("agri-planning-h1") == "tfg-mission-control"


def test_case_cannot_run_through_the_temporary_edit_flow(tmp_path):
    with pytest.raises(hcr.CaptureError, match="own profile"):
        hcr.execute_capture(home=tmp_path, run_id="x", case_id="y", trial=True, trial_case=demo.CASE)


def test_prepared_profile_passes_every_static_check(profile):
    home, data = profile
    assert _failing(home) == set()
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert config["tools"]["tool_search"]["enabled"] == "off"  # a string, not YAML's boolean off
    assert (data / "drafts").stat().st_mode & 0o777 == 0o700
    assert list((home / "backups").iterdir())  # the previous config was kept


@pytest.mark.parametrize("change, failing", [
    (lambda c: c["model"].update(provider="nous"), "provider_local_custom"),
    (lambda c: c["model"].update(base_url="https://inference-api.nousresearch.com/v1"), "base_url_loopback_http"),
    (lambda c: c["model"].update(context_length=32768), "context_meets_hermes_minimum"),
    (lambda c: c.update(fallback_providers=[{"provider": "openrouter"}]), "no_fallback_or_custom_providers"),
    (lambda c: c["platform_toolsets"].update(cli=["tfg-demo-planning", "terminal"]), "only_planning_toolset"),
    (lambda c: c["tools"]["tool_search"].update(enabled="auto"), "tool_search_off"),
    (lambda c: c["mcp_servers"].update({"other": {"command": "x"}}), "only_demo_mcp_server"),
    (lambda c: c["mcp_servers"]["tfg-demo-planning"].update(args=["-m", "tools.hermes_mcp_server"]),
     "server_module_planning_only"),
    (lambda c: c["mcp_servers"]["tfg-demo-planning"]["tools"]["include"].append("get_mission_state"),
     "server_tools_filter"),
    (lambda c: c["mcp_servers"]["tfg-demo-planning"]["env"].update(PYTHONPATH="/elsewhere"),
     "server_code_is_this_checkout"),
    (lambda c: c["plugins"].update(enabled=[]), "capture_plugin_enabled_only"),
    (lambda c: c.update(hooks={"pre_tool_call": ["x"]}), "no_shell_hooks"),
    (lambda c: c["auxiliary"]["title_generation"].update(enabled=True), "title_generation_off"),
])
def test_each_isolation_property_is_checked(profile, change, failing):
    home, _ = profile
    _edit(home, change)
    assert failing in _failing(home)


def test_credentials_and_plugin_changes_are_detected(profile):
    home, _ = profile
    (home / "auth.json").write_text("{}")
    assert "no_credentials_in_profile" in _failing(home)
    (home / "auth.json").unlink()
    (home / "plugins" / hcr.PLUGIN_NAME / "capture.py").write_text("# changed\n")
    assert "plugin_files_match_repository" in _failing(home)


def test_prepare_refuses_default_home_secrets_and_non_profiles(tmp_path, monkeypatch):
    with pytest.raises(demo.DemoError, match="not a Hermes profile"):
        demo.prepare_profile(home=tmp_path, data_root=tmp_path / "d")
    (tmp_path / "config.yaml").write_text("{}\n")
    (tmp_path / "profile.yaml").write_text("{}\n")
    (tmp_path / ".env").write_text("NOUS_API_KEY=x\n")
    with pytest.raises(demo.DemoError, match="no credentials"):
        demo.prepare_profile(home=tmp_path, data_root=tmp_path / "d")
    monkeypatch.setattr(hcr, "DEFAULT_HOME", tmp_path)
    with pytest.raises(demo.DemoError, match="default Hermes home"):
        demo.prepare_profile(home=tmp_path, data_root=tmp_path / "d")


@pytest.fixture
def turns(profile, monkeypatch):
    home, data = profile
    monkeypatch.setattr(demo, "verify_profile", lambda **k: {
        "ok": True, "checks": [], "model": "m", "base_url": "http://127.0.0.1:11435/v1",
        "config_sha256": "c", "draft_root": str(data / "drafts")})
    calls = []

    def runner(argv, *, env, cwd, stdout_path, stderr_path, timeout):
        calls.append({"argv": argv, "env": env, "cwd": cwd})
        stdout_path.write_text("respuesta")
        stderr_path.write_text("")
        return 0, False
    monkeypatch.setattr(demo, "_latest_session", lambda home, since: [{"id": "s-1"}])
    return home, data, calls, runner


def test_turns_run_once_each_resume_the_session_and_strip_credentials(turns, tmp_path):
    home, _, calls, runner = turns
    run_dir = tmp_path / "runs" / "r1"
    env = {"PATH": "/bin", "NOUS_API_KEY": "secret", "OPIK_API_KEY": "k", "OPENROUTER_API_KEY": "k",
           "TFG_OBSERVABILITY_DIR": "/old"}
    first = demo.run_turn(home=home, run_dir=run_dir, turn=1, base_env=env, runner=runner)
    second = demo.run_turn(home=home, run_dir=run_dir, turn=2, base_env=env, runner=runner)
    assert first["session_id"] == second["session_id"] == "s-1"
    assert "--resume" not in calls[0]["argv"] and calls[1]["argv"][-2:] == ["--resume", "s-1"]
    for call, n in zip(calls, (1, 2)):
        assert call["argv"][1:2] == ["-z"] and call["argv"][2] == hcr.TRIAL_CASES[demo.CASE]["prompts"][n - 1]
        assert {"--toolsets", "tfg-demo-planning", "--ignore-rules"} <= set(call["argv"])
        assert not {"NOUS_API_KEY", "OPIK_API_KEY", "OPENROUTER_API_KEY"} & set(call["env"])
        assert call["env"]["HERMES_HOME"] == str(home)
        assert call["env"]["TFG_OBSERVABILITY_DIR"] == str(run_dir / "capture")
        assert call["env"]["TFG_OBSERVABILITY_RUN_ID"] == f"r1-t{n}"
        assert call["cwd"] == str(run_dir / "workspace")
    assert run_dir.stat().st_mode & 0o777 == 0o700
    with pytest.raises(demo.DemoError, match="no turn-2.json"):
        demo.run_turn(home=home, run_dir=run_dir, turn=2, base_env=env, runner=runner)
    with pytest.raises(demo.DemoError, match="already exists"):
        demo.run_turn(home=home, run_dir=run_dir, turn=1, base_env=env, runner=runner)


def test_turn_2_refuses_without_an_identified_session(turns, tmp_path, monkeypatch):
    home, _, calls, runner = turns
    monkeypatch.setattr(demo, "_latest_session", lambda home, since: [{"id": "a"}, {"id": "b"}])
    run_dir = tmp_path / "runs" / "r2"
    demo.run_turn(home=home, run_dir=run_dir, turn=1, base_env={}, runner=runner)
    with pytest.raises(demo.DemoError, match="single identifiable session"):
        demo.run_turn(home=home, run_dir=run_dir, turn=2, base_env={}, runner=runner)
    assert len(calls) == 1


def _synthetic_capture(directory, run_id, offered, requested, executed):
    env = {capture.RUN_ENV: run_id, capture.CASE_ENV: "mcp-local-planning-demo"}
    # Same named-context double as tests/test_hermes_observability_capture.py: the sink records the origin
    # Hermes' PluginContext would give it. The capture remains SYNTHETIC test data.
    context = type("PluginContext", (), {"register_hook": lambda self, hook, callback: None})
    context.__module__ = "hermes_cli.plugins"
    sink = capture.JsonlSink(directory, env, ctx=context())
    body = {"tools": [{"type": "function", "function": {"name": n}} for n in offered]}
    sink.on_pre_api_request(request={"body": body}, tool_count=len(offered), api_call_count=1, session_id="s")
    sink.on_post_api_request(provider="custom", model="qwen3-4b-instruct-64k", api_mode="chat_completions",
                             finish_reason="tool_calls", api_duration=2.5, started_at=1.0, ended_at=3.5,
                             response={"assistant_message": {"tool_calls": [{"name": n} for n in requested]}},
                             usage={"input_tokens": 100, "output_tokens": 20}, session_id="s", api_call_count=1)
    for name in executed:
        sink.on_post_tool_call(tool_name=name, status="ok", duration_ms=15, session_id="s", tool_call_id="t")
    assert sink.failures == 0


def test_review_and_view_from_a_synthetic_capture(profile, tmp_path, monkeypatch):
    """SYNTHETIC capture written through the real plugin sink; checks the review/view plumbing only."""
    home, data = profile
    monkeypatch.setattr(demo, "verify_profile", lambda **k: {"draft_root": str(data / "drafts")})
    capture_dir = tmp_path / "capture"
    _synthetic_capture(capture_dir, "x-t1", [UPDATE, FINALIZE], [UPDATE], [UPDATE])
    with pytest.raises(demo.DemoError, match="already exists"):
        demo.review(evidence_dir=tmp_path, capture_dir=capture_dir, draft_ids=[])
    result = demo.review(evidence_dir=tmp_path / "evidence", capture_dir=capture_dir, draft_ids=[])
    assert result["tool_isolation_verdict"] == "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS"
    assert result["finalizations"] == 0 and result["mission_validated"] is False
    assert result["models_seen"] == ["qwen3-4b-instruct-64k"] and result["providers_seen"] == ["custom"]
    hcr.verify_manifest(tmp_path / "evidence")
    view = demo.write_view(tmp_path / "evidence")
    page = Path(view["view"]).read_text()
    assert "<script" not in page and "http://" not in page and "https://" not in page
    assert "qwen3-4b-instruct-64k" in page and UPDATE in page
    hcr.verify_manifest(tmp_path / "evidence")


def test_review_flags_tools_outside_the_demo_server(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "verify_profile", lambda **k: {"draft_root": str(tmp_path / "drafts")})
    capture_dir = tmp_path / "capture"
    _synthetic_capture(capture_dir, "x-t1", [UPDATE, "terminal"], [UPDATE], [UPDATE])
    result = demo.review(evidence_dir=tmp_path / "evidence", capture_dir=capture_dir, draft_ids=[])
    assert result["tool_isolation_verdict"] == "ISOLATION_NOT_CONFIRMED"


def test_planning_result_reads_the_backend_records(tmp_path, monkeypatch):
    """Real planning backend (no model): an H1 sector A draft is finalized and reported from its files."""
    import tools.hermes_mission_planning as planning
    from models.mission_plan_draft import MissionPlanDraft
    monkeypatch.setattr(planning, "DRAFT_ROOT", tmp_path)
    draft = MissionPlanDraft.model_validate({
        "mission_id": "agri_demo_001_h1_sector_a", "name": "agri_demo_001 H1 sector A", "vehicle_id": "drone_01",
        "vehicle_type": "multirotor", "autopilot": "ArduPilot", "cruise_speed_kmh": 35, "battery_percent": 100,
        "battery_consumption_percent_per_minute": 0.8, "objective_type": "precision_agriculture",
        "objective_target": "agri_demo_001_sector_a", "wind_speed_kmh": 0, "wind_direction_from_deg": 0,
        "minimum_battery_reserve_percent": 20, "maximum_wind_speed_kmh": 30, "maximum_altitude_m": 120,
        "low_battery_action": "RETURN_TO_HOME", "unsafe_wind_action": "RETURN_TO_HOME",
        "communication_loss_action": "RETURN_TO_HOME",
        "geometry_intent": {"mode": "offsets", "home_latitude": 41.275, "home_longitude": 1.987,
                            "home_altitude_m": 0, "altitude_reference": "relative_to_home", "altitude_m": 5,
                            "return_to_home": True, "close_route": False,
                            "offsets": [{"north_m": 8, "east_m": -4}, {"north_m": 16, "east_m": -4}]}})
    saved = planning.update_mission_draft(draft)
    assert saved["missing_fields"] == [], saved["missing_fields"]
    final = planning.finalize_mission_draft(saved["draft_id"], saved["draft_revision"])
    assert final["status"] == "VALIDATED"
    result = demo.planning_result(tmp_path, [saved["draft_id"]])
    (only,) = result["finalizations"]
    assert only["mission_id"] == "agri_demo_001_h1_sector_a" and only["mission_sha256_verified"]
    assert (only["mission_status"], only["execution_status"]) == ("FEASIBLE", "APPROVED")
    assert only["flight_consent"] == "NOT_GRANTED" and only["qgc_export_status"] == "REFUSED"


def test_review_redacts_the_home_directory_in_turn_records(turns, tmp_path, monkeypatch):
    home, data, calls, runner = turns
    run_dir = tmp_path / "runs" / "r3"
    demo.run_turn(home=home, run_dir=run_dir, turn=1, base_env={}, runner=runner)
    _synthetic_capture(run_dir / "capture", "r3-t1", [UPDATE, FINALIZE], [UPDATE], [UPDATE])
    monkeypatch.setattr(demo, "verify_profile", lambda **k: {"draft_root": str(data / "drafts")})
    monkeypatch.setattr(demo.Path, "home", classmethod(lambda cls: tmp_path))
    demo.review(evidence_dir=tmp_path / "evidence", run_dir=run_dir)
    record = (tmp_path / "evidence" / "turn-1.json").read_text()
    assert str(tmp_path) not in record and "~/runs/r3" in record


@pytest.mark.parametrize("url", ["https://127.0.0.1:11435/v1", "http://inference-api.nousresearch.com/v1",
                                 "http://192.168.1.10:11434/v1"])
def test_ollama_probe_only_talks_to_loopback_http(url):
    with pytest.raises(demo.DemoError, match="loopback"):
        demo.ollama_probe(base_url=url)
