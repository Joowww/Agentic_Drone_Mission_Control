"""Offline tests for observability.hermes_capture_run.

Every test named ``test_DOUBLE_*`` runs a FAKE Hermes executable written below: it is a test
double, never the real Hermes, a provider or the network. Review and Opik dry-run tests use
temporary COPIES of the real capture evidence; the originals and their manifests are checked
unchanged."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys

import pytest
import yaml

from observability import hermes_capture_run as run
from observability.hermes_capture import capture
from observability import mission_query_cases as cases

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "evaluation" / "observability" / "hermes_real_capture_nous_2026_10_21"
SOURCES = ("hermes_cli/_parser.py", "toolsets.py", "agent/agent_init.py")
CONFIG = (b"# habitual profile (test double)\nmodel:\n  default: fake-model\n  provider: fake\n"
          b"plugins:\n  # clone deadline\n  clone_timeout_seconds: 300\n"
          b"mcp_servers:\n  tfg-mission-control: {}\n")

# DOUBLE: a fake `hermes` that records each invocation and acts per FAKE_HERMES_MODE.
FAKE_HERMES = r'''#!{python}
import json, os, sys, time
home, mode = os.environ["FAKE_HERMES_HOME"], os.environ["FAKE_HERMES_MODE"]
with open(os.environ["FAKE_HERMES_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
config = open(os.path.join(home, "config.yaml")).read()
seen = {{"plugin_enabled": "- tfg-observability-capture" in config,
        "trial_filter": "        - get_mission_state" in config,
        "tool_search_off": '    enabled: "off"' in config,
        "expectation_env": os.path.isfile(os.environ.get("TFG_OBSERVABILITY_RESULT_EXPECTATION", "")),
        "plugin_installed": os.path.isfile(os.path.join(home, "plugins", "tfg-observability-capture", "capture.py")),
        "capture_env": os.environ.get("TFG_OBSERVABILITY_CAPTURE") == "1"}}
open(os.environ["FAKE_HERMES_SEEN"], "w").write(json.dumps(seen))
if mode == "timeout":
    time.sleep(60)
if mode == "error":
    sys.exit(3)
if mode == "concurrent":
    open(os.path.join(home, "config.yaml"), "a").write("# edited by another process\n")
usage = sys.argv[sys.argv.index("--usage-file") + 1]
open(usage, "w").write(json.dumps({{"input_tokens": 1, "output_tokens": 1, "api_calls": 1, "session_id": "S"}}))
print("OK")
'''


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fake(tmp_path):
    home = tmp_path / "hermes-home"
    (home / "plugins").mkdir(parents=True)
    (home / "config.yaml").write_bytes(CONFIG)
    os.chmod(home / "config.yaml", 0o600)
    verified = {}
    for rel in SOURCES:
        path = home / "hermes-agent" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rel.encode())
        verified[rel] = _sha(rel.encode())
    binary = tmp_path / "bin" / "hermes"
    binary.parent.mkdir()
    binary.write_text(FAKE_HERMES.format(python=sys.executable))
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    log, seen = tmp_path / "invocations.log", tmp_path / "seen.json"

    def execute(mode, **kwargs):
        env = {"PATH": os.environ["PATH"], "FAKE_HERMES_MODE": mode, "FAKE_HERMES_HOME": str(home),
               "FAKE_HERMES_LOG": str(log), "FAKE_HERMES_SEEN": str(seen)}
        options = dict(home=home, hermes_bin=binary, private_root=tmp_path / "private", run_id="real-test",
                       case_id="oneshot-ok", verified_sources=verified, process_lister=lambda: [], base_env=env)
        options.update(kwargs)
        return run.execute_capture(**options)

    def invocations():
        return log.read_text().splitlines() if log.exists() else []

    return {"home": home, "binary": binary, "verified": verified, "execute": execute, "invocations": invocations,
            "seen": seen, "private_root": tmp_path / "private"}


def _assert_restored(fake, report):
    assert (fake["home"] / "config.yaml").read_bytes() == CONFIG
    assert stat.S_IMODE((fake["home"] / "config.yaml").stat().st_mode) == 0o600
    assert not (fake["home"] / "plugins" / run.PLUGIN_NAME).exists()
    assert report["restore"] == {"config": "restored", "plugin": "removed", "error_type": None, "ok": True}


# --- execution with the DOUBLE ------------------------------------------------------------

def test_DOUBLE_hermes_gets_the_checked_home_even_with_another_inherited_HERMES_HOME(fake, monkeypatch, tmp_path):
    seen = {}

    def record(argv, *, env, **kwargs):
        seen["home"] = env.get("HERMES_HOME")
        for path in (kwargs["stdout_path"], kwargs["stderr_path"]):
            open(path, "xb").close()
        return 1, False
    monkeypatch.setattr(run, "_run_hermes", record)
    env = {"PATH": os.environ["PATH"], "HERMES_HOME": str(tmp_path / "other-home")}
    report = run.execute_capture(home=fake["home"], hermes_bin=fake["binary"], private_root=tmp_path / "p",
                                 run_id="real-test", case_id="oneshot-ok", verified_sources=fake["verified"],
                                 process_lister=lambda: [], base_env=env)
    assert seen["home"] == str(fake["home"]) and report["hermes_invocations"] == 1
    _assert_restored(fake, report)


def test_DOUBLE_success_runs_hermes_once_with_plugin_enabled_then_restores(fake):
    report = fake["execute"]("success")
    assert len(fake["invocations"]()) == 1 and report["hermes_invocations"] == 1 and report["automatic_retry"] is False
    argv = json.loads(fake["invocations"]()[0])
    assert argv[:4] == ["-z", run.DEFAULT_PROMPT, "--toolsets", "catalog"] and "--usage-file" in argv
    assert json.loads(fake["seen"].read_text()) == {"plugin_enabled": True, "trial_filter": False,
                                                    "tool_search_off": False, "expectation_env": False,
                                                    "plugin_installed": True, "capture_env": True}
    assert report["return_code"] == 0 and report["timed_out"] is False
    _assert_restored(fake, report)
    private = Path(report["private_dir"])
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert (private / "config.yaml.backup").read_bytes() == CONFIG
    assert json.loads((private / "run.json").read_text())["config_sha256_original"] == _sha(CONFIG)


def test_DOUBLE_timeout_kills_the_process_group_and_restores(fake):
    report = fake["execute"]("timeout", timeout=1)
    assert report["timed_out"] is True and report["return_code"] != 0
    assert len(fake["invocations"]()) == 1  # no retry after the timeout
    _assert_restored(fake, report)


def test_DOUBLE_hermes_error_restores_and_never_retries(fake):
    report = fake["execute"]("error")
    assert report["return_code"] == 3 and len(fake["invocations"]()) == 1
    _assert_restored(fake, report)
    assert run.main(["capture", "--hermes-home", str(fake["home"])], out=open(os.devnull, "w")) == 1  # preflight only


def test_DOUBLE_concurrent_config_edit_is_never_overwritten(fake):
    report = fake["execute"]("concurrent")
    config = (fake["home"] / "config.yaml").read_bytes()
    assert report["restore"]["config"] == "concurrent_edit_not_overwritten" and report["restore"]["ok"] is False
    assert b"# edited by another process" in config  # the foreign edit survives
    assert (Path(report["private_dir"]) / "config.yaml.backup").read_bytes() == CONFIG  # backup kept for the operator
    assert report["restore"]["plugin"] == "removed"


def test_DOUBLE_restore_failure_is_reported_and_does_not_raise(fake):
    calls = []

    def writer(path, data, mode=0o600):
        calls.append(path)
        if len(calls) == 2:  # the edit succeeds, the restore fails
            raise OSError(5, "Input/output error")
        run._atomic_write(path, data, mode)

    report = fake["execute"]("success", writer=writer)
    assert report["restore"]["config"] == "restore_failed" and report["restore"]["error_type"] == "OSError"
    assert report["restore"]["ok"] is False
    assert (Path(report["private_dir"]) / "config.yaml.backup").read_bytes() == CONFIG
    assert json.loads((Path(report["private_dir"]) / "run.json").read_text())["restore"]["config"] == "restore_failed"


@pytest.mark.parametrize("mutate, failing", [
    (lambda f: (f["home"] / "hermes-agent" / "toolsets.py").write_bytes(b"changed"), "tool_selection_sources_verified"),
    (lambda f: (f["home"] / "config.yaml").write_bytes(CONFIG.replace(b"  clone_timeout_seconds: 300\n",
                                                                       b"  enabled: [other]\n")), "no_plugins_allow_list"),
    (lambda f: (f["home"] / "config.yaml").write_bytes(CONFIG + b"hooks:\n  pre: x\n"), "no_shell_hooks"),
    (lambda f: (f["home"] / "config.yaml").write_bytes(CONFIG.replace(b"tfg-mission-control", b"catalog")),
     "no_mcp_named_like_selection"),
    (lambda f: (f["home"] / "plugins" / "other").mkdir(), "user_plugins_dir_empty"),
])
def test_DOUBLE_preflight_failures_refuse_before_anything_is_created(fake, mutate, failing):
    mutate(fake)
    report = run.preflight(home=fake["home"], hermes_bin=fake["binary"], verified_sources=fake["verified"],
                           process_lister=lambda: [])
    assert report["ok"] is False and failing in [c["check"] for c in report["checks"] if not c["ok"]]
    with pytest.raises(run.CaptureError, match=failing):
        fake["execute"]("success")
    assert fake["invocations"]() == [] and not fake["private_root"].exists()


def test_DOUBLE_another_hermes_process_blocks_the_run(fake):
    with pytest.raises(run.CaptureError, match="no_other_hermes_process"):
        fake["execute"]("success", process_lister=lambda: [4242])
    assert fake["invocations"]() == []


def test_DOUBLE_capture_without_execute_never_runs_hermes(fake, capsys):
    rc = run.main(["capture", "--hermes-home", str(fake["home"]), "--hermes-bin", str(fake["binary"])])
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "preflight" and "nothing was created" in out["note"]
    assert rc == 1  # sources do not match the pinned real Hermes versions
    assert fake["invocations"]() == [] and (fake["home"] / "config.yaml").read_bytes() == CONFIG


def test_capture_labels_must_not_claim_synthetic_and_timeout_is_bounded(fake):
    with pytest.raises(run.CaptureError, match="synthetic"):
        fake["execute"]("success", run_id="SYNTHETIC-x")
    with pytest.raises(run.CaptureError, match="timeout"):
        fake["execute"]("success", timeout=10_000)
    assert fake["invocations"]() == []


# --- single MCP tool trial with the DOUBLE --------------------------------------------------

def trial_config(repo):
    return (CONFIG.split(b"mcp_servers:")[0] + b"mcp_servers:\n  tfg-mission-control:\n"
            b"    command: " + str(repo / ".venv" / "bin" / "python").encode() + b"\n"
            b"    args:\n      - -m\n      - tools.hermes_mcp_server\n"
            b"    env:\n      PYTHONPATH: " + str(repo).encode() + b"\n    enabled: true\n")


@pytest.fixture
def trial(fake, tmp_path):
    """The DOUBLE plus a temporary repository layout (never this repository's mission store)."""
    repo = tmp_path / "repo"
    (repo / "missions" / "generated" / "preflights").mkdir(parents=True)
    (repo / "simulation" / "ros2_gazebo" / "results" / "virtual_preflight_x").mkdir(parents=True)
    config = trial_config(repo)
    (fake["home"] / "config.yaml").write_bytes(config)

    def execute(mode, **kwargs):
        options = dict(trial=True, case_id=run.TRIAL_CASE_ID, repo=repo, mcp_process_lister=lambda: [])
        options.update(kwargs)
        return fake["execute"](mode, **options)

    return {**fake, "repo": repo, "config": config, "execute_trial": execute}


def test_DOUBLE_trial_offers_one_server_with_filter_then_restores_everything(trial):
    report = trial["execute_trial"]("success")
    argv = json.loads(trial["invocations"]()[0])
    assert argv[:4] == ["-z", run.TRIAL_PROMPT, "--toolsets", "tfg-mission-control"] and len(trial["invocations"]()) == 1
    seen = json.loads(trial["seen"].read_text())
    assert seen["trial_filter"] is True and seen["tool_search_off"] is True  # present only during the turn
    assert report["mcp_tool_trial"]["tool_search_enabled"] == "off"
    assert (trial["home"] / "config.yaml").read_bytes() == trial["config"]
    assert report["restore"]["ok"] is True and report["toolset_selection"] == "tfg-mission-control"
    meta = report["mcp_tool_trial"]
    assert meta["registry_name"] == "mcp__tfg_mission_control__get_mission_state"
    assert meta["tools_filter"] == {"include": ["get_mission_state"], "resources": False, "prompts": False}
    assert meta["mcp_server_processes_after"] == 0 and "mcp_schema_cache_sha256_after" in meta
    assert json.loads((Path(report["private_dir"]) / "run.json").read_text())["mcp_tool_trial"]["prompt_sha256"] == \
        _sha(run.TRIAL_PROMPT.encode())


@pytest.mark.parametrize("mutate, failing", [
    (lambda t: (t["home"] / "config.yaml").write_bytes(t["config"] + b"  other:\n    command: x\n"),
     "no_other_mcp_server_enabled"),
    (lambda t: (t["home"] / "config.yaml").write_bytes(t["config"] + b"    lazy: true\n"), "trial_server_not_lazy"),
    (lambda t: (t["home"] / "config.yaml").write_bytes(t["config"] + b"    tools:\n      include: [x]\n"),
     "config_edit_isolated"),
    (lambda t: (t["home"] / "config.yaml").write_bytes(t["config"].replace(b"enabled: true", b"enabled: false")),
     "trial_server_configured"),
    (lambda t: (t["home"] / "config.yaml").write_bytes(t["config"].replace(b"tools.hermes_mcp_server", b"other")),
     "trial_server_configured"),
    (lambda t: (t["repo"] / "missions" / "generated" / "preflights" / run.TRIAL_RUN_ID).mkdir(), "trial_run_id_unused"),
    (lambda t: (t["repo"] / "simulation" / "ros2_gazebo" / "results" / "virtual_preflight_x" / "a_report.json")
     .write_text(json.dumps({"run_id": run.TRIAL_RUN_ID})), "trial_run_id_unused"),
])
def test_DOUBLE_trial_preflight_blocks_before_anything_is_created(trial, mutate, failing):
    mutate(trial)
    with pytest.raises(run.CaptureError, match=failing):
        trial["execute_trial"]("success")
    assert trial["invocations"]() == [] and not trial["private_root"].exists()


def test_DOUBLE_trial_blocks_on_running_server_custom_prompt_and_unpinned_sources(trial):
    with pytest.raises(run.CaptureError, match="no_project_mcp_server_process"):
        trial["execute_trial"]("success", mcp_process_lister=lambda: [4242])
    with pytest.raises(run.CaptureError, match="fixed neutral prompt"):
        trial["execute_trial"]("success", prompt="Arma el dron")
    with pytest.raises(run.CaptureError, match="tool_selection_sources_verified"):
        trial["execute_trial"]("success", verified_sources=None)  # real pinned MCP sources absent in the double
    assert trial["invocations"]() == []


def test_zero_tool_catalog_mode_is_unchanged_by_the_trial():
    assert run.TOOLSET_SELECTION == "catalog" and set(run.VERIFIED_SOURCES) < set(run.TRIAL_SOURCES)
    assert run.preflight.__kwdefaults__["trial"] is False and run.execute_capture.__kwdefaults__["trial"] is False
    edited = run.enable_plugin_text(CONFIG)
    assert b"tools:" not in edited and b"get_mission_state" not in edited


@pytest.mark.parametrize("mode", ["error", "timeout"])
def test_DOUBLE_trial_restores_all_three_edits_after_error_or_timeout(trial, mode):
    report = trial["execute_trial"](mode, timeout=1) if mode == "timeout" else trial["execute_trial"](mode)
    assert len(trial["invocations"]()) == 1 and report["restore"]["ok"] is True
    assert (trial["home"] / "config.yaml").read_bytes() == trial["config"]
    assert stat.S_IMODE((trial["home"] / "config.yaml").stat().st_mode) == 0o600
    assert not (trial["home"] / "plugins" / run.PLUGIN_NAME).exists()


def test_DOUBLE_trial_concurrent_edit_is_never_overwritten(trial):
    report = trial["execute_trial"]("concurrent")
    config = (trial["home"] / "config.yaml").read_bytes()
    assert report["restore"]["config"] == "concurrent_edit_not_overwritten" and report["restore"]["ok"] is False
    assert b"# edited by another process" in config and b'enabled: "off"' in config  # left for the operator
    assert (Path(report["private_dir"]) / "config.yaml.backup").read_bytes() == trial["config"]


@pytest.mark.parametrize("existing", [
    b"",                                                                   # no tools key at all
    b"tools:\n  other_setting: 3\n",                                       # tools without tool_search
    b"tools:\n  # comment\n  tool_search:\n    threshold_pct: 7\n    defer: [a]\n  other_setting: 3\n",
])
def test_disable_tool_search_preserves_existing_keys_and_writes_a_string(existing):
    raw = b"model:\n  default: m\n" + existing + b"zz_last: 1\n"
    edited = run.disable_tool_search_text(raw)
    before, after = yaml.safe_load(raw), yaml.safe_load(edited)
    assert after["tools"]["tool_search"]["enabled"] == "off" and isinstance(after["tools"]["tool_search"]["enabled"], str)
    after["tools"]["tool_search"].pop("enabled")
    for key in ("model", "zz_last"):
        assert after[key] == before[key]
    assert {k: v for k, v in after["tools"].items() if v} == {k: v for k, v in (before.get("tools") or {}).items()}
    assert b'enabled: "off"' in edited and b"enabled: off" not in edited  # quoted: never a YAML boolean


@pytest.mark.parametrize("bad", [
    b"tools:\n  tool_search:\n    enabled: auto\n",     # operator's own value: refused, not overridden
    b"tools:\n  tool_search:\n    enabled: off\n",
    b"tools: {tool_search: {}}\n",                        # inline mapping
    b"tools:\n  tool_search: false\n",                    # legacy scalar form
    b"tools:\n  a: 1\ntools:\n  b: 2\n",                  # duplicate top-level key
    b"tools:\n    a: 1\n",                                # unexpected indentation
])
def test_disable_tool_search_refuses_ambiguous_or_preset_configs(bad):
    with pytest.raises(run.CaptureError):
        run.disable_tool_search_text(b"model: {}\n" + bad)


def test_trial_edit_composes_all_three_changes_and_nothing_else(tmp_path):
    config = trial_config(tmp_path)
    before, after = yaml.safe_load(config), yaml.safe_load(run.tool_trial_config_text(config))
    assert after["plugins"].pop("enabled") == [run.PLUGIN_NAME]
    assert after["mcp_servers"]["tfg-mission-control"].pop("tools") == run.TRIAL_TOOLS_FILTER
    assert after.pop("tools") == {"tool_search": {"enabled": "off"}}
    assert after == before


def test_tool_search_off_is_accepted_by_installed_hermes_as_written():
    source = Path.home() / ".hermes" / "hermes-agent" / "tools" / "tool_search.py"
    if not source.is_file():
        pytest.skip("Hermes checkout not installed")
    text = source.read_text(encoding="utf-8")
    assert 'text = str(value).strip().lower()' in text and '"auto", "on", "off"' in text
    assert 'if config.enabled == "off":\n        return False' in text
    assert 'tools_cfg.get("tool_search")' in text  # read from top-level tools.tool_search


def test_restrict_mcp_text_adds_only_the_tools_filter(tmp_path):
    config = trial_config(tmp_path)
    edited = run.tool_trial_config_text(config)
    assert (b"  tfg-mission-control:\n    tools:\n      include:\n        - get_mission_state\n"
            b"      resources: false\n      prompts: false\n    command:") in edited
    assert b"plugins:\n  enabled:\n    - tfg-observability-capture\n" in edited
    for bad in (CONFIG,                                                   # inline `{}` entry
                config.replace(b"  tfg-mission-control:", b"  other:"),   # server missing
                config + b"mcp_servers:\n  x: {}\n",                      # duplicate top-level key
                config.replace(b"    command:", b"    tools: {}\n    command:")):  # existing filter
        with pytest.raises(run.CaptureError):
            run.restrict_mcp_text(bad)


def test_trial_registry_name_follows_installed_hermes_naming():
    source = (Path.home() / ".hermes" / "hermes-agent" / "tools" / "mcp_tool_schema.py")
    if not source.is_file():
        pytest.skip("Hermes checkout not installed")
    text = source.read_text(encoding="utf-8")
    assert 'MCP_TOOL_NAME_PREFIX = "mcp__"' in text and 're.sub(r"[^A-Za-z0-9_]", "_"' in text
    expected = "mcp__" + "tfg-mission-control".replace("-", "_") + "__" + "get_mission_state"
    assert run.TRIAL_REGISTRY_NAME == expected and len(expected) <= 64


# --- trial assessment on SYNTHETIC events (test doubles, not captures) -----------------------

NAME = "mcp__tfg_mission_control__get_mission_state"


def _llm(requested):
    return {"event_type": "llm_call", "requested_tool_names": requested}


def _tool(name=NAME, status="ok"):
    return {"event_type": "tool_call", "tool_name": name, "status": status, "error_type": None,
            "duration_ms_measured": 12}


def _offer(names, count=None):
    return {"offered_tool_names": names, "tool_count": len(names) if count is None else count}


@pytest.mark.parametrize("events, offers, text, verdict", [
    ([_llm([NAME]), _tool(), _llm([])], [_offer([NAME])] * 2, "NOT_FOUND", "TOOL_CALL_OBSERVED_AS_EXPECTED"),
    ([_llm([NAME]), _tool(), _llm([])], [_offer([NAME])] * 2, "El estado es NOT_FOUND.",
     "TOOL_CALL_OBSERVED_AS_EXPECTED"),
    ([_llm([])], [], "NOT_FOUND", "ISOLATION_NOT_CONFIRMED"),                           # no offer record
    ([_llm([])], [_offer([])], "NOT_FOUND", "ISOLATION_NOT_CONFIRMED"),                  # discovery failed
    ([_llm([NAME]), _tool()], [_offer([NAME, "terminal"])], "NOT_FOUND", "ISOLATION_NOT_CONFIRMED"),
    ([_llm([])], [_offer([NAME])], "NOT_FOUND", "TOOL_NOT_REQUESTED"),                   # answered without the tool
    ([_llm([NAME])], [_offer([NAME])], "", "REQUESTED_BUT_NOT_EXECUTED"),
    ([_llm([NAME]), _tool(status="error"), _llm([])], [_offer([NAME])] * 2, "NOT_FOUND",
     "TOOL_EXECUTION_FAILED_OR_BLOCKED"),
    ([_llm([NAME, NAME]), _tool(), _tool(), _llm([])], [_offer([NAME])] * 2, "NOT_FOUND", "MORE_THAN_ONE_TOOL_CALL"),
    ([_llm([NAME]), _tool(), _llm([])], [_offer([NAME])] * 2, "KNOWN", "FINAL_RESPONSE_NOT_AS_EXPECTED"),
])
def test_trial_assessment_keeps_offered_requested_executed_and_response_apart(events, offers, text, verdict):
    result = run.assess_tool_trial(events, offers, text)
    assert result["verdict"] == verdict
    assert {"offered", "requested", "executed", "final_response", "limits"} <= set(result)
    assert result["final_response"] in {"EMPTY", "EQUALS_EXPECTED_STATUS", "CONTAINS_EXPECTED_STATUS", "DIFFERENT"}
    assert "El estado es" not in json.dumps(result)  # only the classification of the reply is kept


def _usage(i, o, cr, total, zero="zero_unconfirmed"):
    nz = "nonzero_normalized"
    return {"input_tokens": {"value": i, "status": nz}, "output_tokens": {"value": o, "status": nz},
            "cache_read_tokens": {"value": cr, "status": nz}, "cache_write_tokens": {"value": 0, "status": zero},
            "reasoning_tokens": {"value": 0, "status": zero}, "total_tokens": {"value": total, "status": "derived_nonzero"}}


# --- historical case: DOUBLE Hermes + temporary repository with stand-in run files --------------

HIST = "467f7ec6-b2a6-4b68-9d97-766d85732f8e"


@pytest.fixture
def historical(trial, monkeypatch):
    """Stand-in job/report files for the historical run_id inside the temporary repository; the
    pinned hashes are re-pointed at them (the real files stay untouched and unread here)."""
    directory = trial["repo"] / "missions" / "generated" / "preflights" / HIST
    directory.mkdir()
    files = {"job.json": {"run_id": HIST, "job_state": "FINISHED"},
             "report.json": {"run_id": HIST, "status": "PASSED", "finished_at": "2026-10-18T21:18:42.180468+00:00"},
             "mission.json": {"m": 1}, "input.json": {"m": 1}}
    for name, body in files.items():
        (directory / name).write_text(json.dumps(body))
    monkeypatch.setattr(run, "HISTORICAL_FILES", {n: _sha((directory / n).read_bytes()) for n in files})

    def execute(mode, **kwargs):
        options = dict(trial_case="historical-passed", case_id="mcp-get-mission-state-historical")
        options.update(kwargs)
        return trial["execute_trial"](mode, **options)

    return {**trial, "run_dir": directory, "execute_historical": execute}


def test_DOUBLE_historical_case_passes_the_expectation_to_the_plugin_then_restores(historical):
    report = historical["execute_historical"]("success")
    argv = json.loads(historical["invocations"]()[0])
    assert argv[:4] == ["-z", run.TRIAL_CASES["historical-passed"]["prompt"], "--toolsets", "tfg-mission-control"]
    assert HIST in argv[1] and len(historical["invocations"]()) == 1
    seen = json.loads(historical["seen"].read_text())
    assert seen["expectation_env"] is True and seen["tool_search_off"] is True and seen["trial_filter"] is True
    private = Path(report["private_dir"])
    assert (private / "result-expectation.json").read_bytes() == run.expectation_bytes("historical-passed")
    assert stat.S_IMODE((private / "result-expectation.json").stat().st_mode) == 0o600
    assert report["mcp_tool_trial"]["trial_case"] == "historical-passed"
    assert report["mcp_tool_trial"]["result_expectation_sha256"] == _sha(run.expectation_bytes("historical-passed"))
    assert (historical["home"] / "config.yaml").read_bytes() == historical["config"] and report["restore"]["ok"]


@pytest.mark.parametrize("mode", ["error", "timeout"])
def test_DOUBLE_historical_case_restores_after_error_or_timeout(historical, mode):
    report = historical["execute_historical"](mode, **({"timeout": 1} if mode == "timeout" else {}))
    assert report["restore"]["ok"] is True and len(historical["invocations"]()) == 1
    assert (historical["home"] / "config.yaml").read_bytes() == historical["config"]
    assert not (historical["home"] / "plugins" / run.PLUGIN_NAME).exists()


@pytest.mark.parametrize("mutate", [
    lambda d: (d / "report.json").write_text(json.dumps({"run_id": HIST, "status": "FAILED"})),  # hash changes
    lambda d: (d / "job.json").unlink(),
])
def test_DOUBLE_historical_case_blocks_when_the_recorded_run_changed(historical, mutate):
    mutate(historical["run_dir"])
    with pytest.raises(run.CaptureError, match="trial_historical_run_pinned"):
        historical["execute_historical"]("success")
    assert historical["invocations"]() == []


def test_DOUBLE_historical_case_blocks_a_pinned_but_contradictory_state(historical, monkeypatch):
    (historical["run_dir"] / "job.json").write_text(json.dumps({"run_id": HIST, "job_state": "RUNNING"}))
    monkeypatch.setattr(run, "HISTORICAL_FILES", {**run.HISTORICAL_FILES,
                                                  "job.json": _sha((historical["run_dir"] / "job.json").read_bytes())})
    with pytest.raises(run.CaptureError, match="trial_historical_run_pinned"):
        historical["execute_historical"]("success")


def test_not_found_case_is_kept_as_regression():
    case = run.TRIAL_CASES["not-found"]
    assert run.DEFAULT_TRIAL_CASE == "not-found" and case["prompt"] == run.TRIAL_PROMPT
    assert case["expected_answer"] == "NOT_FOUND" and run.expectation_bytes("not-found") is None
    assert run.assess_tool_trial([], [], "")["result_check"] == "NOT_APPLICABLE"


def test_historical_expectation_is_a_valid_plugin_allow_list_of_scalars(tmp_path):
    path = tmp_path / "e.json"
    path.write_bytes(run.expectation_bytes("historical-passed"))
    spec, digest, error = capture.load_expectation({capture.EXPECTATION_ENV: str(path)})
    assert error is None and digest == _sha(path.read_bytes())
    assert [c["pointer"] for c in spec["checks"]] == [p for p, _ in run.HISTORICAL_EXPECTED]
    assert {"pointer": "/preflights/1", "absent": True} in spec["checks"]  # exactly one preflight in the answer


def _check_record(outcomes, sha=None, envelope="result_json_text", tool=NAME):
    checks = [{"pointer": p, "outcome": o} for (p, _), o in zip(run.HISTORICAL_EXPECTED, outcomes)]
    return {"tool_name": tool, "expectation_sha256": sha or _sha(run.expectation_bytes("historical-passed")),
            "result_envelope": envelope, "checks": checks,
            "counts": {k: sum(c["outcome"] == k for c in checks) for k in ("match", "mismatch", "absent")}}


N = len(run.HISTORICAL_EXPECTED)
GOOD = ([_llm([NAME]), _tool(), _llm([])], [_offer([NAME])] * 2)


@pytest.mark.parametrize("checks, text, verdict, result_check", [
    ([_check_record(["match"] * N)], "PASSED", "TOOL_CALL_OBSERVED_AS_EXPECTED", "ALL_EXPECTED_FIELDS_MATCH"),
    ([_check_record(["match"] * 8 + ["mismatch"] + ["match"] * (N - 9))], "PASSED",
     "TOOL_RESULT_CONTRADICTS_EXPECTATION", "CONTRADICTS_EXPECTATION"),          # e.g. result_status not PASSED
    ([], "PASSED", "TOOL_RESULT_NOT_VERIFIED", "NOT_RECORDED"),                     # ok + right reply is not enough
    ([_check_record(["absent"] * N, envelope="absent")], "PASSED", "TOOL_RESULT_NOT_VERIFIED", "EXPECTED_FIELDS_ABSENT"),
    ([{**_check_record([]), "result_envelope": "expectation_invalid", "expectation_sha256": None}], "PASSED",
     "TOOL_RESULT_NOT_VERIFIED", "EXPECTATION_NOT_LOADED"),
    ([_check_record(["match"] * N, sha="0" * 64)], "PASSED", "TOOL_RESULT_NOT_VERIFIED", "EXPECTATION_OR_TOOL_MISMATCH"),
    ([_check_record(["match"] * N)], "FAILED", "FINAL_RESPONSE_NOT_AS_EXPECTED", "ALL_EXPECTED_FIELDS_MATCH"),
])
def test_historical_assessment_requires_the_real_result_to_match(checks, text, verdict, result_check):
    result = run.assess_tool_trial(*GOOD, text, "historical-passed", checks)
    assert (result["verdict"], result["result_check"]) == (verdict, result_check)
    assert all(":" in p for p in result["not_matching_pointers"])  # pointer:outcome, never a value


# --- failed-structured (v1, executed 2026-10-22 17:40, superseded) and v2 (PREPARED) ------------

FAILED = "d4519cab-ebd1-4359-b547-44be38294a6a"


def test_v1_case_is_superseded_but_its_evidence_stays_reviewable():
    # Bytes recorded by the executed v1 trial; changing them would break the re-review of that evidence.
    assert _sha(run.expectation_bytes("failed-structured")) == \
        "ecb64f141145f5fa8eb90a5309083b8e51f8d43be5847837f19b4fff2c5e82ea"
    assert run.TRIAL_CASES["failed-structured"]["superseded_by"] == "failed-structured-v2"
    assert run.TRIAL_CASES["failed-structured-v2"]["superseded_by"] == "failed-structured-v3"


def test_DOUBLE_superseded_v1_case_is_refused_before_anything_runs(trial):
    with pytest.raises(run.CaptureError, match="trial_case_current"):
        trial["execute_trial"]("success", trial_case="failed-structured")
    assert trial["invocations"]() == [] and not trial["private_root"].exists()


def test_v2_prompt_names_sources_but_gives_no_expected_value():
    prompt = run.TRIAL_CASES["failed-structured-v2"]["prompt"]
    for key, (pointer, _, _) in cases.ANSWER_CONTRACT.items():
        assert f"- {key} (" in prompt
    assert "preflights[0].executor_facts.return_to_home" in prompt and "No uses acceptance_criteria" in prompt
    # Only the queried run_id may appear; no recorded value is a hint.
    for value in ("FAILED", "prueba_hermes_001", "drone_01", '"v1"', "WP1", "WP2", "false", "true\"", "UNKNOWN\","):
        assert value not in prompt.replace("landed=true", "").replace("false si la lista", ""), value
    assert prompt.count(FAILED) == 1


def test_v2_expectation_keeps_the_v1_trap_inside_acceptance_criteria():
    expected = dict(run.FAILED_V2_EXPECTED)
    assert expected["/preflights/0/executor_facts/return_to_home"] is None              # null: not recorded
    assert expected["/preflights/0/acceptance_criteria/checks/return_home_reached"] is False  # trap present
    assert expected["/preflights/0/executor_facts/mission_landing_event_count"] == 0
    assert expected["/preflights/0/recovery_after_failure/landing_completed"] is True
    assert run.TRIAL_CASES["failed-structured-v2"]["arguments"] == (("run_id", FAILED), ("view", "external"))
    assert run.TRIAL_CASES["failed-structured-v2"]["answer"]["return_to_home"] == "UNKNOWN"


def test_failed_structured_expectation_distinguishes_null_from_absent_and_checks_arguments(tmp_path):
    path = tmp_path / "e.json"
    path.write_bytes(run.expectation_bytes("failed-structured"))
    spec, _, error = capture.load_expectation({capture.EXPECTATION_ENV: str(path)})
    assert error is None and spec["arguments"] == [{"key": "run_id", "expected": FAILED},
                                                   {"key": "view", "expected": "external"}]
    checks = {c["pointer"]: c for c in spec["checks"]}
    assert checks["/preflights/0/return_to_home"] == {"pointer": "/preflights/0/return_to_home", "expected": None}
    assert checks["/preflights/0/reached_waypoint_ids/2"]["absent"] is True
    assert checks["/preflights/0/landing_evidence_count"]["expected"] == 0  # [] recorded, not null
    case = run.TRIAL_CASES["failed-structured"]
    assert 'view=\\"external\\"' not in case["prompt"] and 'view="external"' in case["prompt"] and FAILED in case["prompt"]
    assert run.trial_plan("failed-structured")["expected_structured_answer"] == run.FAILED_ANSWER


@pytest.fixture
def failed_case(trial, monkeypatch):
    """Stand-in report/mission files (no job.json, as in the real report-only run) in the temporary repo."""
    directory = trial["repo"] / "missions" / "generated" / "preflights" / FAILED
    directory.mkdir()
    (directory / "report.json").write_text(json.dumps({"run_id": FAILED, "status": "FAILED", "finished_at": "t"}))
    (directory / "mission.json").write_text("{}")
    files = {n: _sha((directory / n).read_bytes()) for n in ("report.json", "mission.json")}
    view = trial["repo"] / "tools" / "mission_external_view.py"  # stand-in source, pinned like the real one
    view.parent.mkdir()
    view.write_text("# stand-in external view\n")
    monkeypatch.setitem(run.TRIAL_CASES, "failed-structured-v4", {
        **run.TRIAL_CASES["failed-structured-v4"], "files": files,
        "pinned_sources": {"tools/mission_external_view.py": _sha(view.read_bytes())}})

    def execute(mode, **kwargs):
        options = dict(trial_case="failed-structured-v4", case_id="mcp-mission-failed-structured-v4")
        options.update(kwargs)
        return trial["execute_trial"](mode, **options)

    return {**trial, "run_dir": directory, "view": view, "execute_failed": execute}


def test_DOUBLE_v3_records_the_external_view_hash_in_run_json(failed_case):
    report = failed_case["execute_failed"]("success")
    sources = report["mcp_tool_trial"]["server_sources_sha256"]
    assert sources["tools/mission_external_view.py"] == _sha(failed_case["view"].read_bytes())
    stored = json.loads((Path(report["private_dir"]) / "run.json").read_text())
    assert stored["mcp_tool_trial"]["server_sources_sha256"]["tools/mission_external_view.py"] == \
        _sha(failed_case["view"].read_bytes())


def test_DOUBLE_v3_blocks_before_running_when_the_external_view_changed(failed_case):
    failed_case["view"].write_text("# stand-in external view, edited\n")
    with pytest.raises(run.CaptureError, match="trial_server_sources_pinned"):
        failed_case["execute_failed"]("success")
    failed_case["view"].unlink()
    with pytest.raises(run.CaptureError, match="trial_server_sources_pinned"):
        failed_case["execute_failed"]("success")
    assert failed_case["invocations"]() == [] and not failed_case["private_root"].exists()


def test_real_external_view_matches_the_pinned_hash():
    assert _sha((Path(run.__file__).resolve().parents[1] / "tools" / "mission_external_view.py").read_bytes()) == \
        run.EXTERNAL_VIEW_SHA256
    assert "tools/mission_external_view.py" in run.TRIAL_SERVER_SOURCES


def test_v3_prompt_states_the_nullable_rule_without_expected_values():
    prompt = run.TRIAL_CASES["failed-structured-v3"]["prompt"]
    assert "- return_to_home (true, false o null): preflights[0].executor_facts.return_to_home" in prompt
    assert "salvo en return_to_home" in prompt and "La clave debe aparecer siempre" in prompt
    assert "No uses acceptance_criteria" in prompt and prompt.count(FAILED) == 1
    for value in ("FAILED", "prueba_hermes_001", "drone_01", "WP1"):
        assert value not in prompt
    assert run.TRIAL_CASES["failed-structured-v3"]["answer_contract"] == "v3"
    assert run.FAILED_ANSWER_V3 == {**run.FAILED_ANSWER, "return_to_home": None}


def test_v4_prompt_is_the_generic_query_prompt_for_its_run():
    assert run.FAILED_V4_PROMPT == run.query_prompt(FAILED)
    assert _sha(run.FAILED_V4_PROMPT.encode()) == "a374b18bb26917891e7f8eef9899aa1f6eb93f50dc8e639bf0e6659673e91765"


def test_DOUBLE_generic_query_reuses_the_isolation_once_and_restores(trial, monkeypatch):
    other = "0844c190-59c8-40cf-991e-93cebbd3cf02"
    (trial["repo"] / "missions" / "generated" / "preflights" / other).mkdir()   # the run exists
    view = trial["repo"] / "tools" / "mission_external_view.py"
    view.parent.mkdir()
    view.write_text("# stand-in external view\n")
    monkeypatch.setattr(run, "EXTERNAL_VIEW_SHA256", _sha(view.read_bytes()))
    case = run.register_query_case(other)
    report = trial["execute_trial"]("success", trial_case=case, case_id=run.QUERY_CASE_ID)
    argv = json.loads(trial["invocations"]()[0])
    assert argv[:4] == ["-z", run.query_prompt(other), "--toolsets", "tfg-mission-control"]
    assert len(trial["invocations"]()) == 1 and report["restore"]["ok"]
    seen = json.loads(trial["seen"].read_text())
    assert seen["trial_filter"] and seen["tool_search_off"] and seen["expectation_env"] is False  # no fixed expectation
    assert (trial["home"] / "config.yaml").read_bytes() == trial["config"]
    assert not (Path(report["private_dir"]) / "result-expectation.json").exists()


def test_DOUBLE_generic_query_refuses_a_missing_run_or_a_bad_run_id(trial):
    missing = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(run.CaptureError, match="trial_run_exists"):
        trial["execute_trial"]("success", trial_case=run.register_query_case(missing), case_id=run.QUERY_CASE_ID)
    with pytest.raises(run.CaptureError, match="canonical UUID"):
        run.register_query_case("D4519CAB-not-a-uuid")
    assert trial["invocations"]() == []


def test_installed_hermes_offers_no_supported_forced_tool_call_on_this_route():
    """Source contract behind tool_call_forced=False; skipped where Hermes is not installed."""
    agent = Path.home() / ".hermes" / "hermes-agent"
    if not (agent / "agent" / "transports" / "chat_completions.py").is_file():
        pytest.skip("Hermes checkout not installed")
    for rel in ("agent/transports/chat_completions.py", "hermes_cli/oneshot.py", "hermes_cli/_parser.py"):
        assert "tool_choice" not in (agent / rel).read_text(encoding="utf-8"), rel  # never set, no CLI option
    custom = (agent / "hermes_cli" / "runtime_provider_custom.py").read_text(encoding="utf-8")
    assert "def _custom_provider_request_overrides" in custom  # the only runtime source of request_overrides
    # agent/transports/codex.py is a module of Hermes Agent itself (its OpenAI Responses API transport): third-party name.
    assert 'kwargs["tool_choice"] = "auto"' in (agent / "agent" / "transports" / "codex.py").read_text(encoding="utf-8")
    for rel in ("agent/transports/chat_completions.py", "hermes_cli/runtime_provider_custom.py"):
        assert rel in run.TRIAL_SOURCES  # a change blocks the trial preflight until re-verified


def test_v3_is_superseded_by_v4_which_is_short_unforced_and_hint_free():
    assert run.TRIAL_CASES["failed-structured-v3"]["superseded_by"] == "failed-structured-v4"
    v4 = run.TRIAL_CASES["failed-structured-v4"]
    assert "superseded_by" not in v4 and v4["tool_call_forced"] is False  # the model still decides to call
    assert v4["answer_contract"] == "v3" and v4["answer"] == run.FAILED_ANSWER_V3
    assert v4["expected"] == run.FAILED_V2_EXPECTED and v4["pinned_sources"] == run.TRIAL_CASES["failed-structured-v3"]["pinned_sources"]
    prompt = v4["prompt"]
    assert len(prompt) < len(run.FAILED_V3_PROMPT) and prompt.startswith("Paso 1: llama a " + NAME)
    assert "return_to_home es true, false o null" in prompt and "Nunca uses acceptance_criteria" in prompt
    for key in cases.ANSWER_FIELDS:
        assert key in prompt
    for value in ("FAILED", "prueba_hermes_001", "drone_01", "WP1"):
        assert value not in prompt
    assert prompt.count(FAILED) == 1


def test_v2_evidence_is_still_judged_with_contract_v2():
    # The 08:42 v2 answer had return_to_home=null; under its own contract that stays incorrect.
    answer = json.dumps({**run.FAILED_ANSWER, "return_to_home": None})
    result = run.assess_tool_trial(*GOOD, answer, "failed-structured-v2", [_failed_record()])
    assert result["verdict"] == "FINAL_RESPONSE_NOT_AS_EXPECTED"
    assert result["structured_answer"]["contract"] == "v2"
    assert result["structured_answer"]["fields"]["return_to_home"] == "null_instead_of_unknown"


def test_DOUBLE_failed_structured_case_runs_once_with_expectation_and_restores(failed_case):
    report = failed_case["execute_failed"]("success")
    argv = json.loads(failed_case["invocations"]()[0])
    assert argv[1] == run.TRIAL_CASES["failed-structured-v4"]["prompt"] and len(failed_case["invocations"]()) == 1
    assert json.loads(failed_case["seen"].read_text())["expectation_env"] is True
    assert (Path(report["private_dir"]) / "result-expectation.json").read_bytes() == run.expectation_bytes("failed-structured-v4")
    assert report["restore"]["ok"] and (failed_case["home"] / "config.yaml").read_bytes() == failed_case["config"]


def test_DOUBLE_failed_structured_case_blocks_on_a_changed_or_relabelled_record(failed_case, monkeypatch):
    (failed_case["run_dir"] / "report.json").write_text(json.dumps({"run_id": FAILED, "status": "PASSED",
                                                                   "finished_at": "t"}))
    with pytest.raises(run.CaptureError, match="trial_historical_run_pinned"):
        failed_case["execute_failed"]("success")  # hash changed
    files = {**run.TRIAL_CASES["failed-structured-v4"]["files"],
             "report.json": _sha((failed_case["run_dir"] / "report.json").read_bytes())}
    monkeypatch.setitem(run.TRIAL_CASES, "failed-structured-v4", {**run.TRIAL_CASES["failed-structured-v4"], "files": files})
    with pytest.raises(run.CaptureError, match="trial_historical_run_pinned"):
        failed_case["execute_failed"]("success")  # pinned, but no longer records FAILED
    assert failed_case["invocations"]() == []


NF = len(run.FAILED_V2_EXPECTED)


def _failed_record(outcomes=None, arguments=("match", "match")):
    outcomes = outcomes or ["match"] * NF
    checks = [{"pointer": p, "outcome": o} for (p, _), o in zip(run.FAILED_V2_EXPECTED, outcomes)]
    record = {"tool_name": NAME, "expectation_sha256": _sha(run.expectation_bytes("failed-structured-v4")),
              "result_envelope": "result_json_text", "checks": checks,
              "counts": {k: sum(c["outcome"] == k for c in checks) for k in ("match", "mismatch", "absent")}}
    if arguments is not None:
        record["argument_checks"] = [{"key": k, "outcome": o} for k, o in zip(("run_id", "view"), arguments)]
    return record


GOOD_ANSWER = json.dumps(run.FAILED_ANSWER_V3)


@pytest.mark.parametrize("record, text, verdict", [
    (_failed_record(), GOOD_ANSWER, "TOOL_CALL_OBSERVED_AS_EXPECTED"),
    (_failed_record(arguments=("mismatch", "match")), GOOD_ANSWER, "EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED"),
    (_failed_record(arguments=("match", "absent")), GOOD_ANSWER, "EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED"),
    (_failed_record(arguments=None), GOOD_ANSWER, "EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED"),
    (_failed_record(["match"] * 8 + ["mismatch"] + ["match"] * (NF - 9)), GOOD_ANSWER,
     "TOOL_RESULT_CONTRADICTS_EXPECTATION"),
    (_failed_record(), json.dumps({**run.FAILED_ANSWER_V3, "return_to_home": False}), "FINAL_RESPONSE_NOT_AS_EXPECTED"),
    (_failed_record(), "FAILED", "FINAL_RESPONSE_NOT_AS_EXPECTED"),
])
def test_failed_structured_assessment(record, text, verdict):
    result = run.assess_tool_trial(*GOOD, text, "failed-structured-v4", [record])
    assert result["verdict"] == verdict
    if verdict == "TOOL_CALL_OBSERVED_AS_EXPECTED":
        assert result["final_response"] == "STRUCTURED_ALL_FIELDS_CORRECT"
        assert result["structured_answer"]["fields"]["return_to_home"] == "match"  # null expected and given (contract v3)


V4_ANSWER = json.dumps(run.FAILED_ANSWER_V3)


@pytest.mark.parametrize("events, offers, checks, text, verdict", [
    # The 2026-10-23 08:53 pattern, but with a FULLY correct answer: still not accepted.
    ([_llm([])], [_offer([NAME])], [], V4_ANSWER, "TOOL_NOT_REQUESTED"),
    ([_llm(["terminal"]), _tool("terminal"), _llm([])], [_offer([NAME, "terminal"])] * 2, [], V4_ANSWER,
     "ISOLATION_NOT_CONFIRMED"),                                            # other tool offered and used
    ([_llm([NAME]), _tool("terminal"), _llm([])], [_offer([NAME])] * 2, [], V4_ANSWER,
     "TOOL_EXECUTION_FAILED_OR_BLOCKED"),                                   # wrong tool executed
    (GOOD[0], GOOD[1], [_failed_record(arguments=("mismatch", "match"))], V4_ANSWER,
     "EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED"),                            # another run_id queried
    (GOOD[0], GOOD[1], [], V4_ANSWER, "TOOL_RESULT_NOT_VERIFIED"),          # result not checked
    (GOOD[0], GOOD[1], [_failed_record()], "El estado es FAILED", "FINAL_RESPONSE_NOT_AS_EXPECTED"),  # invalid JSON
])
def test_no_accidental_field_match_turns_a_failed_check_into_success(events, offers, checks, text, verdict):
    result = run.assess_tool_trial(events, offers, text, "failed-structured-v4", checks)
    assert result["verdict"] == verdict != "TOOL_CALL_OBSERVED_AS_EXPECTED"


def test_failed_structured_expectation_matches_the_real_external_view_offline(tmp_path):
    """Real project function (subprocess, audit hook, no MCP stdio, no Hermes) through the plugin's
    comparison, with the intended arguments; skipped where the local run directory is absent."""
    root = Path(run.__file__).resolve().parents[1]
    if not (root / "missions" / "generated" / "preflights" / FAILED / "report.json").is_file():
        pytest.skip("local run directory is git-ignored data")
    script = (f"import sys, json; sys.path.insert(0, {str(root)!r})\n" + AUDIT.split("import tools.hermes_mcp_server")[0]
              + "import tools.hermes_mcp_server as server\n"
              "from observability import hermes_capture_run as run\n"
              "from observability.hermes_capture import capture\n"
              "phase[0] = 'call'\n"
              "args = {'run_id': sys.argv[1], 'view': 'external'}\n"
              "result = server.get_mission_state(**args)\n"
              "spec = json.loads(run.expectation_bytes('failed-structured-v4'))\n"
              "rec = capture.result_check_event({'tool_name': run.TRIAL_REGISTRY_NAME, 'args': args, "
              "'result': json.dumps({'result': json.dumps(result)})}, spec, '0' * 64, {})\n"
              "print(json.dumps({'counts': rec['counts'], 'args': rec['argument_checks'], 'events': events['call'], "
              "'size': len(json.dumps(result))}))\n")
    proc = subprocess.run([sys.executable, "-I", "-c", script, FAILED], capture_output=True, text=True, cwd=tmp_path,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["events"] == [] and out["counts"] == {"match": NF, "mismatch": 0, "absent": 0}
    assert [a["outcome"] for a in out["args"]] == ["match", "match"]


def test_historical_expectation_matches_the_real_tool_output_offline(tmp_path):
    """Real project function (subprocess, audit hook, no MCP stdio, no Hermes) against the plugin's
    own comparison; skipped where the local, git-ignored run directory is absent."""
    root = Path(run.__file__).resolve().parents[1]
    if not (root / "missions" / "generated" / "preflights" / HIST / "report.json").is_file():
        pytest.skip("historical run files are local data, not in Git")
    script = (f"import sys, json; sys.path.insert(0, {str(root)!r})\n" + AUDIT.split("import tools.hermes_mcp_server")[0]
              + "import tools.hermes_mcp_server as server\n"
              "from observability import hermes_capture_run as run\n"
              "from observability.hermes_capture import capture\n"
              "phase[0] = 'call'\n"
              "result = server.get_mission_state(run_id=sys.argv[1], view='summary')\n"
              "spec = json.loads(run.expectation_bytes('historical-passed'))\n"
              "rec = capture.result_check_event({'tool_name': run.TRIAL_REGISTRY_NAME, "
              "'result': json.dumps({'result': json.dumps(result)})}, spec, '0' * 64, {})\n"
              "print(json.dumps({'counts': rec['counts'], 'events': events['call']}))\n")
    proc = subprocess.run([sys.executable, "-I", "-c", script, HIST], capture_output=True, text=True, cwd=tmp_path,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["events"] == [] and out["counts"] == {"match": N, "mismatch": 0, "absent": 0}


def test_multi_call_correlation_sums_only_incremental_counters_and_names_the_rest():
    # SYNTHETIC events with the per-call values of the 22/10 16:40 trial; native = its main-turn totals.
    calls = [{"event_type": "llm_call", "api_call_count": n, "usage": u} for n, u in
             ((1, _usage(2095, 34, 512, 2641)), (2, _usage(2331, 90, 672, 3093)), (3, _usage(2588, 3, 672, 3263)))]
    native = {"input_tokens": 7014, "output_tokens": 127, "cache_read_tokens": 1856, "cache_write_tokens": 0,
              "reasoning_tokens": 0, "total_tokens": 8997, "api_calls": 3,
              "auxiliary": {"by_task": {"title_generation": {"input_tokens": 115}}}}
    result = run.correlate(calls, native)
    assert result["scope"] == "main_turn_sum_of_llm_calls" and result["verdict"] == "all_compared_values_equal"
    assert result["fields"]["input_tokens"]["plugin_sum"] == 7014
    assert result["fields"]["cache_write_tokens"]["plugin_statuses"] == ["zero_unconfirmed"] * 3
    assert "api_call_count" in result["not_comparable"] and "api_call_count" not in result["fields"]  # 1+2+3 never summed
    assert result["call_count"] == {"plugin_llm_calls": 3, "native_api_calls": 3, "values_equal": True,
                                    "meaning": "model calls in Hermes' main turn on both sides; not HTTP requests"}
    assert result["auxiliary_native_only"]["captured_by_plugin"] is False
    native["api_calls"] = 4
    assert run.correlate(calls, native)["verdict"] == "differences_found"
    calls[1]["usage"]["input_tokens"] = {"value": None, "status": "absent"}
    assert run.correlate(calls, native)["verdict"] == "not_computable_absent_values"


def test_trial_review_refuses_a_run_that_was_not_a_trial(tmp_path, real_private_copy):
    run_json = json.loads((real_private_copy / "run.json").read_text())
    run_json.update(prompt_sha256=_sha(run.TRIAL_PROMPT.encode()), toolset_selection="catalog")
    (real_private_copy / "run.json").write_text(json.dumps(run_json))
    with pytest.raises(run.CaptureError, match="not an MCP tool trial"):
        run.review(private_dir=real_private_copy, evidence_dir=tmp_path / "e", trial=True)
    assert not (tmp_path / "e").exists()


# --- read-only classification of the real tool (subprocess, audit hook; no MCP stdio, no Hermes) ---

AUDIT = r'''
import json, sys
sys.dont_write_bytecode = True
events = {"import": [], "call": []}
phase = ["import"]
MUTATING = ("os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.unlink", "os.chmod",
            "os.truncate", "os.symlink", "os.link", "shutil.", "subprocess.", "os.system", "os.exec",
            "os.posix_spawn", "os.fork", "socket.connect", "socket.bind", "socket.sendto")
def hook(name, args):
    if name == "open":
        mode, flags = (args[1] if len(args) > 1 else "r"), (args[2] if len(args) > 2 else 0)
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & 3):
            events[phase[0]].append(["open-write", str(args[0])])
    elif name.startswith(MUTATING):
        events[phase[0]].append([name, repr(args[1]) if name.startswith("socket.") else ""])
sys.addaudithook(hook)
import tools.hermes_mcp_server as server
phase[0] = "call"
result = server.get_mission_state(run_id=sys.argv[1], view="summary")
print(json.dumps({"result": result, "events": events}))
'''


def test_get_mission_state_with_the_neutral_run_id_is_read_only_and_not_an_error(tmp_path):
    root = Path(run.__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(root)!r})\n" + AUDIT,
                           run.TRIAL_RUN_ID], capture_output=True, text=True, cwd=tmp_path, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["events"]["call"] == []  # the tool call: no write, mkdir, process or socket at all
    # Import: only urllib3's import-time IPv6 probe (bind to ::1 port 0, never connect) is tolerated.
    assert all(e == ["socket.bind", "('::1', 0)"] for e in out["events"]["import"]), out["events"]["import"]
    assert out["result"] == {"status": run.TRIAL_EXPECTED_STATUS, "run_id": run.TRIAL_RUN_ID,
                             "consent": "NOT_GRANTED_BY_THIS_QUERY"}
    assert '"error"' not in json.dumps(out["result"])  # Hermes would otherwise mark the call status=error


# --- config edit --------------------------------------------------------------------------

def test_enable_plugin_text_adds_only_the_allow_list():
    edited = run.enable_plugin_text(CONFIG)
    assert b"plugins:\n  enabled:\n    - tfg-observability-capture\n  # clone deadline" in edited
    assert run.enable_plugin_text(b"model: {}\n").endswith(b"plugins:\n  enabled:\n    - tfg-observability-capture\n")
    for bad in (b"plugins:\n    clone: 1\n", b"plugins: {}\nx: 1\nplugins:\n  a: 1\n", b"plugins: {clone: 1}\n",
                b"plugins:\n  a: 1\nplugins:\n  b: 2\n"):
        with pytest.raises(run.CaptureError):
            run.enable_plugin_text(bad)


# --- review and Opik dry-run on COPIES of the real capture --------------------------------

def _tree_hashes(directory):
    return {str(p.relative_to(directory)): _sha(p.read_bytes()) for p in sorted(directory.rglob("*")) if p.is_file()}


@pytest.fixture
def real_private_copy(tmp_path):
    """A private-dir layout rebuilt from COPIES of the real evidence (raw material is not in Git)."""
    before = _tree_hashes(REAL)
    private = tmp_path / "private-copy"
    shutil.copytree(REAL / "capture", private / "capture")
    native = json.loads((REAL / "native_usage_reviewed.json").read_text())
    native["session_id"] = "SESSION-SENTINEL-1234"
    (private / "native-usage.json").write_text(json.dumps(native))
    (private / "stdout.txt").write_text("OK\n")
    (private / "stderr.txt").write_text("")
    (private / "run.json").write_text(json.dumps({"prompt_sha256": _sha(run.DEFAULT_PROMPT.encode()),
                                                  "private_dir": "/home/someone/private", "return_code": 0}))
    yield private
    assert _tree_hashes(REAL) == before  # originals and their manifest untouched


def test_review_validates_real_capture_copy_and_keeps_main_turn_apart(tmp_path, real_private_copy):
    evidence = tmp_path / "evidence"
    result = run.review(private_dir=real_private_copy, evidence_dir=evidence)
    assert result["events"] == 1 and result["provenance_ok"] is True
    assert result["correlation_verdict"] == "all_compared_values_equal"
    summary = json.loads((evidence / "capture_summary.json").read_text())
    corr = summary["correlation_with_native"]
    assert corr["scope"] == "main_turn_only"
    assert corr["fields"]["input_tokens"]["native"] == 538 and corr["fields"]["cache_read_tokens"]["native"] == 256
    assert corr["fields"]["reasoning_tokens"]["plugin"] == {"value": 0, "status": "zero_unconfirmed"}
    assert corr["fields"]["total_tokens"]["plugin"]["status"] == "derived_nonzero"
    assert corr["auxiliary_native_only"]["captured_by_plugin"] is False
    assert "title_generation" in corr["auxiliary_native_only"]["by_task"]
    assert summary["summary"]["comparative"]["groups"][0]["model"] == "nous/poolside/laguna-s-2.1:free"
    run.verify_manifest(evidence)
    blob = "".join(p.read_text() for p in evidence.rglob("*") if p.is_file())
    assert "SESSION-SENTINEL" not in blob and "/home/someone" not in blob
    review_meta = json.loads((evidence / "native_usage_review.json").read_text())
    assert review_meta["omitted_fields"] == ["session_id"]
    with pytest.raises(run.CaptureError, match="never reused"):
        run.review(private_dir=real_private_copy, evidence_dir=evidence)


def test_review_refuses_content_leaks_and_missing_provenance(tmp_path, real_private_copy):
    (real_private_copy / "stdout.txt").write_text("llm_call\n")  # a 'response' that appears in the JSONL
    with pytest.raises(run.CaptureError, match="response"):
        run.review(private_dir=real_private_copy, evidence_dir=tmp_path / "e1")
    (real_private_copy / "stdout.txt").write_text("OK\n")
    for record in (real_private_copy / "capture").glob("capture-provenance-*.json"):
        record.unlink()
    with pytest.raises(run.CaptureError, match="provenance"):
        run.review(private_dir=real_private_copy, evidence_dir=tmp_path / "e2")
    assert not (tmp_path / "e1").exists() and not (tmp_path / "e2").exists()


def test_opik_dry_run_reproduces_the_sent_payload_without_key_or_network(tmp_path, real_private_copy, monkeypatch):
    evidence = tmp_path / "evidence"
    run.review(private_dir=real_private_copy, evidence_dir=evidence)

    class Guarded(dict):
        def get(self, key, default=None):
            assert not key.startswith(("OPIK", "COMET")), "credential read"
            return super().get(key, default)

    def deny(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(os, "environ", Guarded(os.environ))
    monkeypatch.setattr(socket, "create_connection", deny)
    result = run.opik_dry_run(evidence_dir=evidence, project="tfg-opik-hermes-real-20261021", workspace="joowww")
    assert result["sent"] is False and result["blocked_for_future_send_by_default"] == []
    # Same capture + destination => the exact bodies sent and confirmed on 2026-10-21.
    assert result["body_sha256"] == {
        "traces_batches": ["881bb615907fddec8e6e56b2bd98c600e297d4a5bcded5d9059e95f0ed9fea15"],
        "spans_batches": ["a2b96e370d81fa1f7d92d29308aef0c362df2fbcd3bb6c0ebac83f5b3ca95fda"]}
    assert result["trace_ids"] == ["01a16002-9b28-75bc-abca-6942ca6d1c95"]
    assert result["span_ids"] == ["01a16002-9b28-7291-bce7-d68337bb58f2"]
    assert "--send" in result["prepared_send_command_NOT_EXECUTED"]
    run.verify_manifest(evidence)
    with pytest.raises(run.CaptureError, match="already exists"):
        run.opik_dry_run(evidence_dir=evidence, project="other-project", workspace="joowww")


def test_saved_opik_dry_run_rebuilds_the_exact_bytes_the_exporter_posts(tmp_path, real_private_copy, monkeypatch):
    """capture -> dry-run -> saved file -> read -> body bytes == bytes handed to a fake transport."""
    evidence = tmp_path / "evidence"
    run.review(private_dir=real_private_copy, evidence_dir=evidence)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network used"))
    result = run.opik_dry_run(evidence_dir=evidence, project="tfg-opik-hermes-real-20261021", workspace="joowww")
    saved = json.loads((evidence / "opik_dry_run.json").read_text(encoding="utf-8"))["payload"]
    rebuilt = [run.opik_export.body_bytes(b) for b in saved["traces_batches"] + saved["spans_batches"]]

    posted = []

    def transport(url, headers, body, timeout):
        posted.append((url.rsplit("/", 2)[-2], body))
        return {"status": 204, "reason": "fake", "body_bytes": 0}

    capture = sorted((evidence / "capture").glob("hermes-events-*.jsonl"))
    argv = [str(p) for p in capture] + ["--project", "tfg-opik-hermes-real-20261021", "--workspace", "joowww",
                                        "--provenance", "captured", "--send", "--record", str(tmp_path / "rec.jsonl")]
    with open(os.devnull, "w") as sink:
        assert run.opik_export.main(argv, out=sink, transport=transport,
                                    environ={run.opik_export.API_KEY_ENV: "fake-key-NOT-REAL"}) == 0
    assert [kind for kind, _ in posted] == ["traces", "spans"]
    assert rebuilt == [body for _, body in posted]
    assert [_sha(b) for b in rebuilt] == result["body_sha256"]["traces_batches"] + result["body_sha256"]["spans_batches"]
    assert [_sha(b) for b in rebuilt] == ["881bb615907fddec8e6e56b2bd98c600e297d4a5bcded5d9059e95f0ed9fea15",
                                          "a2b96e370d81fa1f7d92d29308aef0c362df2fbcd3bb6c0ebac83f5b3ca95fda"]
    # Nested key order matters: sorting keys (the pre-fix saved format) changes the bytes.
    span = saved["spans_batches"][0]["spans"][0]
    assert list(span["metadata"]) != sorted(span["metadata"])
    assert [json.dumps(b, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
            for b in saved["traces_batches"] + saved["spans_batches"]] != rebuilt


# --- H1 planning isolation (prepared; DOUBLE only, never the real Hermes) ----------------------------

PLAN = "agri-planning-h1"
PLAN_NAMES = ["mcp__tfg_mission_control__finalize_mission_draft", "mcp__tfg_mission_control__update_mission_draft"]


def test_planning_case_registers_exactly_the_two_planning_tools(tmp_path):
    config = trial_config(tmp_path)
    before, after = yaml.safe_load(config), yaml.safe_load(run.tool_trial_config_text(config, run.case_tools(PLAN)))
    assert after["mcp_servers"]["tfg-mission-control"].pop("tools") == {
        "include": ["update_mission_draft", "finalize_mission_draft"], "resources": False, "prompts": False}
    assert after.pop("tools") == {"tool_search": {"enabled": "off"}}
    assert after["plugins"].pop("enabled") == [run.PLUGIN_NAME] and after == before
    assert run.trial_plan(PLAN)["registry_names"] == sorted(PLAN_NAMES, reverse=True)
    for bad in ((), ("get_mission_state; rm",), ("Update",)):
        with pytest.raises(run.CaptureError):
            run.restrict_mcp_text(config, bad)


def test_planning_case_excludes_every_operational_tool_of_the_real_server():
    import asyncio
    import tools.hermes_mcp_server as server
    registered = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    included = set(run.case_tools(PLAN))
    assert included <= registered and "get_mission_state" not in included
    excluded = registered - included
    for name in ("start_simulation", "restart_simulation", "stop_simulation", "check_simulation_ready",
                 "execute_approved_mission", "check_mission_execution_ready", "start_virtual_preflight",
                 "run_virtual_preflight", "start_preflight_sequence", "apply_execution_reconciliation",
                 "apply_legacy_sequence_retirement", "build_mission_revision", "generate_draft_route",
                 "validate_and_export_qgc", "get_scenario_view"):
        assert name in excluded
    # 26 when H1 ran (docs/hermes-planning.md); get_scenario_view was added afterwards for H3b.
    assert len(registered) == 27 and len(excluded) == 25


def _recorded_server_sources(evidence):
    run_json = json.loads((ROOT / "evaluation/observability" / evidence / "run.json").read_text())
    return run_json["mcp_tool_trial"]["server_sources_sha256"]


def test_planning_case_is_closed_and_its_pins_describe_the_sources_of_its_real_run():
    case = run.TRIAL_CASES[PLAN]
    assert case["superseded_by"].startswith("executed 2026-10-24")  # the preflight refuses a second run
    recorded = _recorded_server_sources("agri_planning_h1_nous_2026_10_24")
    assert case["pinned_sources"]["tools/hermes_mcp_server.py"] == recorded["tools/hermes_mcp_server.py"]
    assert case["expected"] is None and case["run_id"] is None and "agri_demo_001_sector_a" in case["prompt"]
    for text in ("no detecciones", "no se toman imágenes", "no lecturas reales", "No arranques simulaciones"):
        assert text in case["prompt"]


@pytest.fixture
def planning_trial(trial, monkeypatch):
    """Stand-in pinned sources in the temporary repo, as for the failed-structured cases."""
    pinned = {}
    for rel in run.TRIAL_CASES[PLAN]["pinned_sources"]:
        path = trial["repo"] / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# stand-in {rel}\n")
        pinned[rel] = _sha(path.read_bytes())
    # The executed case is closed (superseded_by); the mechanism itself is exercised on an open copy.
    open_case = {k: v for k, v in run.TRIAL_CASES[PLAN].items() if k != "superseded_by"}
    monkeypatch.setitem(run.TRIAL_CASES, PLAN, {**open_case, "pinned_sources": pinned})
    return trial


def test_DOUBLE_planning_turn_offers_only_planning_tools_then_restores_everything(planning_trial):
    t = planning_trial
    report = t["execute_trial"]("success", trial_case=PLAN, case_id="mcp-agri-planning-h1", timeout=300)
    argv = json.loads(t["invocations"]()[0])
    assert argv[:4] == ["-z", run.AGRI_PLANNING_PROMPT, "--toolsets", "tfg-mission-control"]
    assert len(t["invocations"]()) == 1 and report["hermes_invocations"] == 1
    seen = json.loads(t["seen"].read_text())
    assert seen["tool_search_off"] is True and seen["trial_filter"] is False  # get_mission_state not registered
    assert seen["expectation_env"] is False  # artifacts are judged by bind_scenario, not by an expectation
    assert report["config_sha256_edited"] == _sha(run.tool_trial_config_text(t["config"], run.PLANNING_TOOLS))
    meta = report["mcp_tool_trial"]
    assert meta["tools"] == list(run.PLANNING_TOOLS) and meta["tool"] is None
    assert meta["tool_classification"].startswith("planning writes only: missions/generated/drafts/")
    assert (t["home"] / "config.yaml").read_bytes() == t["config"] and report["restore"]["ok"] is True
    assert not (t["home"] / "plugins" / run.PLUGIN_NAME).exists()


def test_DOUBLE_planning_turn_blocks_when_a_pinned_source_changed(planning_trial):
    t = planning_trial
    (t["repo"] / "tools" / "hermes_mission_planning.py").write_text("# changed\n")
    with pytest.raises(run.CaptureError, match="trial_server_sources_pinned"):
        t["execute_trial"]("success", trial_case=PLAN, case_id="mcp-agri-planning-h1")
    assert t["invocations"]() == [] and (t["home"] / "config.yaml").read_bytes() == t["config"]


@pytest.mark.parametrize("events, offers, verdict", [
    ([_llm([PLAN_NAMES[1]]), _tool(PLAN_NAMES[1]), _llm([PLAN_NAMES[0]]), _tool(PLAN_NAMES[0]), _llm([])],
     [_offer(PLAN_NAMES)] * 3, "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS"),
    ([_llm([])], [_offer(PLAN_NAMES)], "TOOL_NOT_REQUESTED"),
    ([_llm([PLAN_NAMES[1]]), _tool(PLAN_NAMES[1])], [_offer(PLAN_NAMES + [NAME])], "ISOLATION_NOT_CONFIRMED"),
    ([_llm([PLAN_NAMES[1]]), _tool(PLAN_NAMES[1])], [_offer(PLAN_NAMES[:1])], "ISOLATION_NOT_CONFIRMED"),
    ([_llm([PLAN_NAMES[1]]), _tool(PLAN_NAMES[1], status="error"), _llm([])], [_offer(PLAN_NAMES)] * 2,
     "PLANNING_CALLS_NOT_AS_EXPECTED"),
])
def test_planning_assessment_judges_isolation_only_never_the_text(events, offers, verdict):
    result = run.assess_tool_trial(events, offers, "VALIDATED APPROVED", PLAN)
    assert result["verdict"] == verdict
    assert result["final_response"] == "NOT_EVALUATED_ARTIFACTS_JUDGED_BY_BINDING"


# --- H1: full public review of a SYNTHETIC planning capture written by the REAL plugin sink -----------

def _hermes_named_context():
    """Type name matches Hermes' PluginContext (the sink's only origin signal); a test double."""
    cls = type("PluginContext", (), {"register_hook": lambda self, name, cb: None})
    cls.__module__ = "hermes_cli.plugins"
    return cls()


def planning_private_dir(tmp_path, turns, *, offered=PLAN_NAMES, stdout='{"status": "VALIDATED"}'):
    """A private dir as execute_capture leaves it; ``turns`` = requested names per model response,
    each followed by the executed tool calls ("ok"), the last response without tool calls."""
    private = tmp_path / "private-planning"
    env = {capture.ENABLE_ENV: "1", capture.DIR_ENV: str(private / "capture")}
    sink = capture.register(_hermes_named_context(), environ=env)
    body = {"tools": [{"type": "function", "function": {"name": n}} for n in offered]}
    for index, names in enumerate(turns, 1):
        sink.on_pre_api_request(task_id="t", turn_id="u", api_request_id=f"u:api:{index}", session_id="s",
                                provider="nous", model="m", api_call_count=index, tool_count=len(offered),
                                request={"body": body})
        sink.on_post_api_request(task_id="t", turn_id="u", api_request_id=f"u:api:{index}", session_id="s",
                                 provider="nous", model="m", api_call_count=index, api_duration=1.0,
                                 started_at=1.0, ended_at=2.0, finish_reason="tool_calls" if names else "stop",
                                 response={"assistant_message": {"tool_calls": [{"name": n} for n in names]}},
                                 usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})
        for n in names:
            sink.on_post_tool_call(tool_name=n, tool_call_id=f"c{index}", status="ok", duration_ms=40,
                                   session_id="s", turn_id="u")
    assert sink.failures == 0
    (private / "stdout.txt").write_text(stdout + "\n")
    (private / "stderr.txt").write_text("")
    (private / "native-usage.json").write_text(json.dumps({"api_calls": len(turns), "session_id": "S-SENTINEL"}))
    (private / "run.json").write_text(json.dumps({
        "prompt_sha256": _sha(run.AGRI_PLANNING_PROMPT.encode()), "toolset_selection": "tfg-mission-control",
        "mcp_tool_trial": {"trial_case": PLAN}, "private_dir": "/home/someone/private", "return_code": 0}))
    return private


UPDATE, FINALIZE = PLAN_NAMES[1], PLAN_NAMES[0]
FULL_PLAN = [[UPDATE], [FINALIZE], [UPDATE], [FINALIZE], []]


def test_SYNTHETIC_planning_capture_passes_the_full_public_review(tmp_path):
    private = planning_private_dir(tmp_path, FULL_PLAN)
    evidence = tmp_path / "evidence"
    result = run.review(private_dir=private, evidence_dir=evidence, trial=True, trial_case=PLAN)
    assert result["mcp_tool_trial_verdict"] == "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS"
    assert result["provenance_ok"] is True and result["tool_offer_records"] == 5
    summary = json.loads((evidence / "capture_summary.json").read_text())
    trial = summary["mcp_tool_trial"]
    assert trial["requested_tool_names"] == [UPDATE, FINALIZE, UPDATE, FINALIZE]
    assert [c["tool_name"] for c in trial["tool_calls"]] == [UPDATE, FINALIZE, UPDATE, FINALIZE]
    assert trial["final_response"] == "NOT_EVALUATED_ARTIFACTS_JUDGED_BY_BINDING"
    assert summary["tool_offers"]["offered_tool_names"] == [PLAN_NAMES] * 5
    assert not (evidence / "result-expectation.json").exists()  # judged by bind-h1, not an expectation
    public_run = json.loads((evidence / "run.json").read_text())
    assert "private_dir" not in public_run and "S-SENTINEL" not in (evidence / "native_usage_reviewed.json").read_text()
    run.verify_manifest(evidence)


@pytest.mark.parametrize("turns, offered, verdict", [
    ([[]], PLAN_NAMES, "TOOL_NOT_REQUESTED"),                                # a reply without any call
    (FULL_PLAN, PLAN_NAMES + [NAME], "ISOLATION_NOT_CONFIRMED"),            # a third tool offered
    (FULL_PLAN, [], "ISOLATION_NOT_CONFIRMED"),                             # no tools offered at all
    ([[UPDATE, "mcp__tfg_mission_control__start_simulation"], []], PLAN_NAMES, "PLANNING_CALLS_NOT_AS_EXPECTED"),
])
def test_SYNTHETIC_planning_review_never_passes_by_vacuous_or_foreign_calls(tmp_path, turns, offered, verdict):
    private = planning_private_dir(tmp_path, turns, offered=offered)
    result = run.review(private_dir=private, evidence_dir=tmp_path / "evidence", trial=True, trial_case=PLAN)
    assert result["mcp_tool_trial_verdict"] == verdict


def test_planning_assessment_requires_offer_records_and_an_execution_per_request():
    assert run.assess_tool_trial([], [], "", PLAN)["verdict"] == "ISOLATION_NOT_CONFIRMED"
    requested_not_run = [_llm([UPDATE, FINALIZE]), _tool(UPDATE), _llm([])]
    assert run.assess_tool_trial(requested_not_run, [_offer(PLAN_NAMES)] * 2, "", PLAN)["verdict"] == \
        "PLANNING_CALLS_NOT_AS_EXPECTED"
    with_error = [_llm([UPDATE]), _tool(UPDATE), {"event_type": "llm_error"}, _llm([])]
    assert run.assess_tool_trial(with_error, [_offer(PLAN_NAMES)] * 2, "", PLAN)["verdict"] == \
        "PLANNING_CALLS_NOT_AS_EXPECTED"


def test_empty_planning_capture_is_refused_before_any_verdict(tmp_path):
    private = planning_private_dir(tmp_path, FULL_PLAN)
    for path in (private / "capture").iterdir():
        path.unlink()
    with pytest.raises(run.CaptureError, match="nothing to review"):
        run.review(private_dir=private, evidence_dir=tmp_path / "evidence", trial=True, trial_case=PLAN)
    assert not (tmp_path / "evidence").exists()


# --- H3 scenario query case (prepared; DOUBLE only) -------------------------------------------------

H3 = "agri-scenario-h3"


def test_h3_case_offers_only_the_read_only_query_tool_and_names_both_real_runs(tmp_path):
    config = trial_config(tmp_path)
    after = yaml.safe_load(run.tool_trial_config_text(config, run.case_tools(H3)))
    assert after["mcp_servers"]["tfg-mission-control"]["tools"]["include"] == ["get_mission_state"]
    prompt = run.TRIAL_CASES[H3]["prompt"]
    assert all(r in prompt for r in run.H3_RUN_IDS) and prompt.count('view="external"') == 2
    for text in ("no son detecciones", "commands_sent false", "no la del despegue", "r1_movement_authorized"):
        assert text in prompt
    assert run.TRIAL_CASES[H3]["superseded_by"] == "agri-scenario-h3b"  # executed once; never rerun
    recorded = _recorded_server_sources("agri_scenario_h3_nous_2026_10_24")
    for rel, digest in run.TRIAL_CASES[H3]["pinned_sources"].items():
        assert recorded[rel] == digest, f"{rel}: pin differs from the sources recorded by the H3 run"


def test_DOUBLE_h3_preflight_blocks_until_both_runs_exist_then_runs_once_and_restores(trial, monkeypatch):
    pinned = {}
    for rel in run.TRIAL_CASES[H3]["pinned_sources"]:
        path = trial["repo"] / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# stand-in {rel}\n")
        pinned[rel] = _sha(path.read_bytes())
    open_case = {k: v for k, v in run.TRIAL_CASES[H3].items() if k != "superseded_by"}
    monkeypatch.setitem(run.TRIAL_CASES, H3, {**open_case, "pinned_sources": pinned})
    with pytest.raises(run.CaptureError, match="trial_runs_exist"):
        trial["execute_trial"]("success", trial_case=H3, case_id="mcp-agri-scenario-h3")
    for run_id in run.H3_RUN_IDS:
        (trial["repo"] / "missions" / "generated" / "preflights" / run_id).mkdir()
    report = trial["execute_trial"]("success", trial_case=H3, case_id="mcp-agri-scenario-h3")
    assert len(trial["invocations"]()) == 1 and json.loads(trial["seen"].read_text())["trial_filter"] is True
    assert report["restore"]["ok"] and (trial["home"] / "config.yaml").read_bytes() == trial["config"]


def test_h3_assessment_requires_both_query_calls_and_never_judges_the_text():
    good = [_llm([NAME, NAME]), _tool(), _tool(), _llm([])]
    result = run.assess_tool_trial(good, [_offer([NAME])] * 2, "texto", H3)
    assert result["verdict"] == "QUERY_CALLS_WITHIN_ALLOWED_TOOLS"
    assert result["final_response"] == "NOT_EVALUATED_ANSWER_JUDGED_BY_ACCEPT_H3"
    assert run.assess_tool_trial([_llm([])], [_offer([NAME])], "", H3)["verdict"] == "TOOL_NOT_REQUESTED"
    assert run.assess_tool_trial(good, [], "", H3)["verdict"] == "ISOLATION_NOT_CONFIRMED"


# --- H3b scenario-view case (prepared; DOUBLE only) ------------------------------------------------

H3B = "agri-scenario-h3b"
VIEW_NAME = "mcp__tfg_mission_control__get_scenario_view"


def test_h3b_case_offers_only_the_scenario_view_and_its_prompt_carries_no_observed_values(tmp_path):
    after = yaml.safe_load(run.tool_trial_config_text(trial_config(tmp_path), run.case_tools(H3B)))
    assert after["mcp_servers"]["tfg-mission-control"]["tools"]["include"] == ["get_scenario_view"]
    case = run.TRIAL_CASES[H3B]
    assert case["kind"] == "scenario_query" and case["expected"] is None
    assert case["superseded_by"].startswith("executed 2026-10-24")  # run once; the preflight refuses a rerun
    prompt = case["prompt"]
    assert VIEW_NAME in prompt and 'request_key="agri-demo-001-h2-r01"' in prompt
    for value in ("AERIAL_COMPLETED", "BLOCKED_PENDING", '"MET"', "drone_01", "POI_A1", "2f7db1f6", "12:5", "PASSED"):
        assert value not in prompt, value  # field names and instructions only, never the observed answer
    recorded = _recorded_server_sources("agri_scenario_h3b_nous_2026_10_24")
    for rel in ("tools/hermes_mcp_server.py", "tools/virtual_preflight_jobs.py"):  # recorded by the real run
        assert case["pinned_sources"][rel] == recorded[rel], rel


def test_DOUBLE_h3b_preflight_needs_the_admitted_sequence_then_runs_once_and_restores(trial, monkeypatch):
    pinned = {}
    for rel in run.TRIAL_CASES[H3B]["pinned_sources"]:
        path = trial["repo"] / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# stand-in {rel}\n")
        pinned[rel] = _sha(path.read_bytes())
    open_case = {k: v for k, v in run.TRIAL_CASES[H3B].items() if k != "superseded_by"}
    monkeypatch.setitem(run.TRIAL_CASES, H3B, {**open_case, "pinned_sources": pinned})
    with pytest.raises(run.CaptureError, match="trial_sequence_exists"):
        trial["execute_trial"]("success", trial_case=H3B, case_id="mcp-agri-scenario-h3b")
    index = trial["repo"] / "missions/generated/preflight_sequences/requests"
    index.mkdir(parents=True)
    (index / (_sha(b"agri-demo-001-h2-r01") + ".json")).write_text("{}")
    report = trial["execute_trial"]("success", trial_case=H3B, case_id="mcp-agri-scenario-h3b")
    assert len(trial["invocations"]()) == 1 and report["mcp_tool_trial"]["tools"] == ["get_scenario_view"]
    assert report["restore"]["ok"] and (trial["home"] / "config.yaml").read_bytes() == trial["config"]


def test_h3b_assessment_needs_the_view_call_and_never_judges_the_text():
    good = [_llm([VIEW_NAME]), _tool(VIEW_NAME), _llm([])]
    result = run.assess_tool_trial(good, [_offer([VIEW_NAME])] * 2, "texto", H3B)
    assert result["verdict"] == "QUERY_CALLS_WITHIN_ALLOWED_TOOLS"
    assert result["final_response"] == "NOT_EVALUATED_ANSWER_JUDGED_BY_ACCEPT_H3"
    other = [_llm([NAME]), _tool(NAME), _llm([])]
    assert run.assess_tool_trial(other, [_offer([VIEW_NAME])] * 2, "", H3B)["verdict"] == "QUERY_CALLS_NOT_AS_EXPECTED"


SCENARIO_AUDIT = AUDIT.replace(
    'result = server.get_mission_state(run_id=sys.argv[1], view="summary")',
    'result = server.get_scenario_view("agri_demo_001", request_key=sys.argv[1])')


def test_scenario_view_tool_is_read_only_on_the_real_h2_record(tmp_path):
    root = Path(run.__file__).resolve().parents[1]
    index = root / "missions/generated/preflight_sequences/requests" / (_sha(b"agri-demo-001-h2-r01") + ".json")
    if not index.is_file():
        pytest.skip("local H2 sequence record (missions/generated is not versioned) is not present")
    proc = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(root)!r})\n" + SCENARIO_AUDIT,
                           "agri-demo-001-h2-r01"], capture_output=True, text=True, cwd=tmp_path, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["events"]["call"] == []  # no write, mkdir, process or socket during the tool call
    assert out["result"]["status"] == "OK" and out["result"]["view_schema"] == "tfg.agri-scenario-view/1"
