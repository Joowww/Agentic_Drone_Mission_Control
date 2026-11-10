"""Local Hermes + Ollama planning demo: isolated profile, recorded turns, review and a static local view.

Chain: operator -> Hermes (profile tfg-demo-local) -> Ollama on loopback -> planning-only MCP server
(tools.hermes_demo_planning_server) -> MissionDefinition -> LangGraph validation -> finalization ->
capture plugin -> review (capture_summary) -> Opik dry-run (hermes_capture_run opik-dry-run) -> view.html.

Subcommands (every one prints JSON; none sends anything off the machine):

- ``prepare-profile``: writes the demo config into an EXISTING profile created by ``hermes profile create``
  (backing up the previous config.yaml) and installs the capture plugin there. Nothing else is touched.
- ``verify-profile``: read-only static checks of the effective config, plugin files, Hermes sources and the
  provenance of the server module; ``--offered-tools`` also asks Hermes offline (``prompt-size``, no model
  call) which tool schemas it would send.
- ``turn``: ONE recorded operator turn (``hermes -z``) of the pre-registered ``local-planning-demo`` case;
  turn 2 resumes turn 1's session. One invocation, no retry, a hard timeout.
- ``review``: validates the capture, assesses tool isolation, reads this run's finalization and writes a NEW
  evidence directory with SHA256SUMS.
- ``view``: writes ``view.html`` (static, no scripts, no network) into an evidence directory.

The same profile also serves manual sessions (``hermes -p tfg-demo-local``): with the TFG_OBSERVABILITY_*
variables set, ``review --capture-dir`` reviews such a capture without run records.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlparse

import yaml

from observability import capture_summary
from observability import hermes_capture_run as hcr
from observability import langsmith_export as common

PROFILE_NAME = "tfg-demo-local"
CASE = hcr.LOCAL_DEMO_CASE
SERVER = hcr.LOCAL_DEMO_SERVER
SERVER_MODULE = "tools.hermes_demo_planning_server"
DRAFT_ROOT_ENV = "TFG_DEMO_DRAFT_ROOT"
DEFAULT_MODEL = "qwen3-4b-instruct-64k"
DEFAULT_BASE_URL = "http://127.0.0.1:11435/v1"
CONTEXT_LENGTH = 65536
HERMES_MINIMUM_CONTEXT = 64000  # agent/model_metadata.py MINIMUM_CONTEXT_LENGTH at d923a5eb
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
DEFAULT_HOME = hcr.DEFAULT_HOME / "profiles" / PROFILE_NAME
DEFAULT_DATA_ROOT = Path.home() / "tfg-local-demo"
REPO_ROOT = hcr.REPO_ROOT
# Removed from the environment of every recorded turn: no remote provider can be reached by fallback.
_SECRET_ENV = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|^OPIK_|^NOUS_|^OPENROUTER|^OPENAI|^ANTHROPIC|"
                         r"^GOOGLE_|^GEMINI|^HF_|^LANGSMITH|^LANGCHAIN)", re.I)
TURN_TIMEOUT_S = 600


class DemoError(Exception):
    pass


def registry_names():
    return sorted(hcr.registry_name(t, SERVER) for t in hcr.case_tools(CASE))


# --- profile ------------------------------------------------------------------------------

def render_config(*, repo: Path, python: Path, draft_root: Path, base_url: str = DEFAULT_BASE_URL,
                  model: str = DEFAULT_MODEL) -> dict:
    """The complete demo config. Everything not set here is Hermes' default (deep-merged)."""
    return {
        "model": {"provider": "custom", "base_url": base_url, "default": model,
                  "context_length": CONTEXT_LENGTH, "ollama_num_ctx": CONTEXT_LENGTH},
        "fallback_providers": [],
        "platform_toolsets": {"cli": [SERVER]},
        "tools": {"tool_search": {"enabled": "off"}},
        "mcp_servers": {SERVER: {
            "command": str(python), "args": ["-m", SERVER_MODULE],
            "env": {"PYTHONPATH": str(repo), DRAFT_ROOT_ENV: str(draft_root)}, "enabled": True,
            "tools": {"include": list(hcr.case_tools(CASE)), "resources": False, "prompts": False}}},
        "plugins": {"enabled": [hcr.PLUGIN_NAME]},
        "auxiliary": {"title_generation": {"enabled": False}},
        "skills": {"project_discovery": False, "auto_load": [], "inline_shell": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "curator": {"enabled": False},
        "updates": {"check": False},
        "security": {"allow_lazy_installs": False},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
    }


def config_text(config: dict) -> bytes:
    header = ("# Hermes profile tfg-demo-local, written by observability.local_planning_demo prepare-profile.\n"
              "# Local Ollama on loopback, planning-only MCP server, capture plugin. No remote provider,\n"
              "# no credentials. Re-run prepare-profile instead of editing by hand; verify-profile checks it.\n")
    return (header + yaml.safe_dump(config, sort_keys=False, allow_unicode=True)).encode("utf-8")


def _env_assignments(path: Path):
    if not path.is_file():
        return []
    return [line.split("=", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line]


def prepare_profile(*, home: Path, repo: Path = REPO_ROOT, python: Path | None = None,
                    data_root: Path = DEFAULT_DATA_ROOT, base_url: str = DEFAULT_BASE_URL,
                    model: str = DEFAULT_MODEL) -> dict:
    python = python or repo / ".venv" / "bin" / "python"
    if not (home / "config.yaml").is_file() or not (home / "profile.yaml").is_file():
        raise DemoError(f"{home} is not a Hermes profile; create it first with "
                        f"`hermes profile create {PROFILE_NAME} --no-skills --no-alias`")
    if home.resolve() == hcr.DEFAULT_HOME.resolve():
        raise DemoError("refusing to write the default Hermes home")
    if _env_assignments(home / ".env"):
        raise DemoError(f"{home / '.env'} defines variables; the demo profile must hold no credentials")
    if not data_root.is_absolute():
        raise DemoError("--data-root must be absolute")
    for directory in (data_root, data_root / "drafts", data_root / "runs"):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    new = config_text(render_config(repo=repo, python=python, draft_root=data_root / "drafts",
                                    base_url=base_url, model=model))
    config = home / "config.yaml"
    old = config.read_bytes()
    backup = None
    if old != new:
        backups = home / "backups"
        backups.mkdir(mode=0o700, exist_ok=True)
        backup = backups / ("config.yaml." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        hcr._write_new(backup, old)
        hcr._atomic_write(config, new, 0o600)
    plugin_dir = home / "plugins" / hcr.PLUGIN_NAME
    plugin_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    installed = {}
    for name in hcr.PLUGIN_FILES:
        data = (hcr.PLUGIN_SOURCE / name).read_bytes()
        hcr._atomic_write(plugin_dir / name, data, 0o644)
        installed[name] = hcr._sha(data)
    return {"profile_home": str(home), "config_sha256": hcr._sha(new), "config_changed": old != new,
            "previous_config_backup": str(backup) if backup else None, "plugin_installed_sha256": installed,
            "drafts": str(data_root / "drafts"), "runs": str(data_root / "runs")}


def _profile_python_import(entry: dict, timeout: float = 60) -> dict:
    """Which file the configured interpreter really imports for the server module (no server start)."""
    code = ("import json, tools.hermes_demo_planning_server as m, tools.hermes_mission_planning as p; "
            "print(json.dumps({'server': m.__file__, 'planning': p.__file__}))")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", **entry.get("env", {})}
    out = subprocess.run([entry["command"], "-B", "-c", code], env=env, capture_output=True, text=True,
                         timeout=timeout, cwd="/")
    if out.returncode:
        return {"ok": False, "error": out.stderr.strip().splitlines()[-1:] }
    return {"ok": True, **json.loads(out.stdout)}


def verify_profile(*, home: Path = DEFAULT_HOME, repo: Path = REPO_ROOT, agent: Path | None = None) -> dict:
    """Read-only static checks; ``ok`` only if every check passes."""
    agent = agent or hcr.DEFAULT_HOME / "hermes-agent"
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    raw = (home / "config.yaml").read_bytes() if (home / "config.yaml").is_file() else None
    check("profile_config_present", raw is not None, str(home / "config.yaml"))
    check("not_default_home", home.resolve() != hcr.DEFAULT_HOME.resolve(), "the habitual home is never used")
    config = yaml.safe_load(raw) if raw else {}
    config = config if isinstance(config, dict) else {}
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    url = urlparse(str(model.get("base_url", "")))
    check("provider_local_custom", model.get("provider") == "custom", f"model.provider={model.get('provider')!r}")
    check("base_url_loopback_http", url.scheme == "http" and url.hostname in LOOPBACK,
          f"{url.scheme}://{url.hostname}:{url.port}")
    check("model_named", isinstance(model.get("default"), str) and model["default"], f"{model.get('default')!r}")
    check("context_meets_hermes_minimum",
          all(isinstance(model.get(k), int) and model[k] >= HERMES_MINIMUM_CONTEXT
              for k in ("context_length", "ollama_num_ctx")),
          f"context_length={model.get('context_length')}, ollama_num_ctx={model.get('ollama_num_ctx')}; "
          f"minimum {HERMES_MINIMUM_CONTEXT}")
    check("no_fallback_or_custom_providers",
          not config.get("fallback_providers") and not config.get("custom_providers") and not config.get("providers"),
          "fallback_providers/custom_providers/providers empty")
    check("only_planning_toolset", (config.get("platform_toolsets") or {}).get("cli") == [SERVER],
          f"platform_toolsets.cli={((config.get('platform_toolsets') or {}).get('cli'))}")
    search = ((config.get("tools") or {}).get("tool_search") or {}).get("enabled")
    check("tool_search_off", search == "off", f"tools.tool_search.enabled={search!r} (string 'off')")
    servers = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}
    check("only_demo_mcp_server", list(servers) == [SERVER], f"mcp_servers={sorted(servers)}")
    entry = servers.get(SERVER) if isinstance(servers.get(SERVER), dict) else {}
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    check("server_module_planning_only", entry.get("args") == ["-m", SERVER_MODULE] and "url" not in entry
          and entry.get("enabled") is True and not entry.get("lazy"), f"args={entry.get('args')}")
    check("server_tools_filter", entry.get("tools") == hcr.tools_filter(hcr.case_tools(CASE)),
          f"tools={entry.get('tools')}")
    check("server_code_is_this_checkout", env.get("PYTHONPATH") == str(repo)
          and Path(str(entry.get("command", ""))).is_file(), f"PYTHONPATH={env.get('PYTHONPATH')}")
    draft_root = Path(str(env.get(DRAFT_ROOT_ENV, "")))
    private = (draft_root.is_absolute() and draft_root.is_dir()
               and not (draft_root.stat().st_mode & 0o077) and repo not in draft_root.resolve().parents)
    check("draft_root_private_outside_repo", private, f"{DRAFT_ROOT_ENV}={draft_root}")
    check("capture_plugin_enabled_only", (config.get("plugins") or {}).get("enabled") == [hcr.PLUGIN_NAME],
          f"plugins.enabled={(config.get('plugins') or {}).get('enabled')}")
    plugins = home / "plugins"
    names = sorted(p.name for p in plugins.iterdir()) if plugins.is_dir() else []
    mismatched = [f for f in hcr.PLUGIN_FILES
                  if hcr._file_sha(plugins / hcr.PLUGIN_NAME / f) != hcr._file_sha(hcr.PLUGIN_SOURCE / f)]
    check("plugin_files_match_repository", names == [hcr.PLUGIN_NAME] and not mismatched,
          f"plugins={names}; mismatched={mismatched}")
    check("no_shell_hooks", not config.get("hooks"), "hooks absent")
    check("title_generation_off",
          ((config.get("auxiliary") or {}).get("title_generation") or {}).get("enabled") is False,
          "no auxiliary model call")
    check("no_credentials_in_profile", not _env_assignments(home / ".env") and not (home / "auth.json").exists(),
          ".env without assignments, no auth.json")
    mismatched = sorted(rel for rel, d in hcr.TRIAL_SOURCES.items() if hcr._file_sha(agent / rel) != d)
    check("hermes_sources_verified", not mismatched,
          f"Hermes {hcr.VERIFIED_HERMES_COMMIT[:10]}" if not mismatched else f"changed: {mismatched}")
    provenance = _profile_python_import(entry) if entry.get("command") else {"ok": False}
    check("server_module_provenance", provenance.get("ok") and provenance.get("server") == str(
        repo / "tools" / "hermes_demo_planning_server.py") and provenance.get("planning") == str(
        repo / "tools" / "hermes_mission_planning.py"), provenance)
    return {"mode": "verify-profile", "profile_home": str(home), "ok": all(c["ok"] for c in checks),
            "checks": checks, "config_sha256": hcr._sha(raw) if raw else None,
            "model": model.get("default"), "base_url": model.get("base_url"), "draft_root": str(draft_root),
            "expected_offered_tools": registry_names()}


def offered_tools(*, home: Path, hermes_bin: Path = hcr.DEFAULT_BIN, timeout: float = 120) -> dict:
    """Offline view of what a session of this profile would offer, without any model call:
    ``prompt-size --json`` counts the built-in tool schemas (terminal, files, web...; must be 0) and
    ``mcp test`` connects to the demo server and lists the tools it discovers (must be the two planning
    tools). The definitive per-request check is the capture's tool_offer records."""
    env = _clean_env(home)
    run = lambda *args: subprocess.run([str(hermes_bin), *args], env=env, capture_output=True, text=True,
                                       timeout=timeout, cwd=str(home), stdin=subprocess.DEVNULL)
    size = run("prompt-size", "--json")
    builtin = json.loads(size.stdout)["tools"]["count"] if size.returncode == 0 else None
    test = run("mcp", "test", SERVER)
    discovered = re.search(r"Tools discovered:\s*(\d+)", test.stdout)
    names = sorted(set(re.findall(r"^\s{2,}(" + "|".join(hcr.case_tools(CASE)) + r")\s", test.stdout, re.M)))
    expected = sorted(hcr.case_tools(CASE))
    return {"ok": builtin == 0 and discovered is not None and int(discovered.group(1)) == len(expected)
                  and names == expected,
            "builtin_tool_schemas": builtin, "mcp_tools_discovered": int(discovered.group(1)) if discovered else None,
            "mcp_tool_names": names, "expected_mcp_tool_names": expected,
            "registry_names_in_requests": registry_names(), "model_called": False}


# --- recorded turns --------------------------------------------------------------------

def _clean_env(home: Path, base=None) -> dict:
    env = {k: v for k, v in (os.environ if base is None else base).items() if not _SECRET_ENV.search(k)}
    for key in [k for k in env if k.startswith("TFG_OBSERVABILITY_") or k == "HERMES_INFERENCE_MODEL"]:
        env.pop(key)
    env.update({"HERMES_HOME": str(home), "HERMES_DISABLE_LAZY_INSTALLS": "1"})
    return env


def _latest_session(home: Path, since_epoch: float):
    db = home / "state.db"
    if not db.is_file():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, started_at, model, billing_provider, billing_base_url FROM sessions "
                           "WHERE started_at >= ? ORDER BY started_at", (since_epoch - 1,)).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "started_at": r[1], "model": r[2], "provider": r[3], "base_url": r[4]} for r in rows]


def _draft_listing(root: Path):
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def run_turn(*, home: Path = DEFAULT_HOME, hermes_bin: Path = hcr.DEFAULT_BIN, run_dir: Path, turn: int,
             timeout: float = TURN_TIMEOUT_S, label: str | None = None, base_env=None, runner=None) -> dict:
    """ONE recorded operator turn. Turn 1 creates ``run_dir``; turn 2 resumes turn 1's session."""
    runner = runner or hcr._run_hermes
    if turn not in (1, 2):
        raise DemoError("turn must be 1 or 2")
    if not (0 < timeout <= hcr.MAX_TIMEOUT_S):
        raise DemoError(f"timeout must be in (0, {hcr.MAX_TIMEOUT_S}] seconds")
    report = verify_profile(home=home)
    if not report["ok"]:
        raise DemoError("verify-profile failed: " + ", ".join(c["check"] for c in report["checks"] if not c["ok"]))
    if turn == 1:
        if run_dir.exists():
            raise DemoError("run directory already exists; every run uses a new one")
        run_dir.mkdir(mode=0o700, parents=True)
        (run_dir / "workspace").mkdir(mode=0o700)
        previous = None
    else:
        first = run_dir / "turn-1.json"
        if not first.is_file() or (run_dir / "turn-2.json").exists():
            raise DemoError("turn 2 needs this run's turn-1.json and no turn-2.json")
        previous = json.loads(first.read_text())
        if previous.get("return_code") != 0 or not previous.get("session_id"):
            raise DemoError("turn 1 did not finish with a single identifiable session; not resuming")
    label = label or (previous or {}).get("label") or run_dir.name
    if not hcr._LABEL.fullmatch(label):
        raise DemoError("label must be a short token")
    prompt = hcr.TRIAL_CASES[CASE]["prompts"][turn - 1]
    draft_root = Path(report["draft_root"])
    env = _clean_env(home, base_env)
    env.update({"TFG_OBSERVABILITY_CAPTURE": "1", "TFG_OBSERVABILITY_DIR": str(run_dir / "capture"),
                "TFG_OBSERVABILITY_RUN_ID": f"{label}-t{turn}",
                "TFG_OBSERVABILITY_CASE_ID": hcr.TRIAL_CASES[CASE]["case_id"]})
    argv = [str(hermes_bin), "-z", prompt, "--toolsets", SERVER, "--ignore-rules",
            "--usage-file", str(run_dir / f"native-usage-turn-{turn}.json")]
    if previous:
        argv += ["--resume", previous["session_id"]]
    record = {"case": CASE, "turn": turn, "label": label, "prompt_sha256": hcr._sha(prompt.encode()),
              "model_configured": report["model"], "base_url_configured": report["base_url"],
              "profile_config_sha256": report["config_sha256"], "verified_hermes_commit": hcr.VERIFIED_HERMES_COMMIT,
              "argv_without_prompt": [a for a in argv if a != prompt], "timeout_s": timeout,
              "server_source_sha256": hcr._file_sha(REPO_ROOT / "tools" / "hermes_demo_planning_server.py"),
              "hermes_invocations": 1, "automatic_retry": False,
              "drafts_before": _draft_listing(draft_root)}
    record["started_at_utc"] = hcr._utc_now()
    started_epoch, started = time.time(), time.monotonic()
    rc, timed_out = runner(argv, env=env, cwd=str(run_dir / "workspace"),
                           stdout_path=run_dir / f"stdout-turn-{turn}.txt",
                           stderr_path=run_dir / f"stderr-turn-{turn}.txt", timeout=timeout)
    record.update(finished_at_utc=hcr._utc_now(), elapsed_wall_s=round(time.monotonic() - started, 3),
                  return_code=rc, timed_out=timed_out, drafts_after=_draft_listing(draft_root))
    sessions = _latest_session(home, started_epoch) if turn == 1 else None
    if turn == 1:
        record["sessions_started"] = sessions
        record["session_id"] = sessions[0]["id"] if sessions and len(sessions) == 1 else None
    else:
        record["session_id"] = previous["session_id"]
    hcr._write_new(run_dir / f"turn-{turn}.json", hcr._json_bytes(record))
    return record


# --- review ----------------------------------------------------------------------------------

def _redact(text: str) -> str:
    return text.replace(str(Path.home()), "~")


def _finalizations(draft_root: Path, draft_ids):
    found = []
    for draft_id in draft_ids:
        for record in sorted((draft_root / draft_id).glob("*/finalization.json")):
            found.append((record, json.loads(record.read_text())))
    return found


def planning_result(draft_root: Path, draft_ids) -> dict:
    """What the deterministic backend recorded for this run's drafts (never the model's text)."""
    drafts = []
    for draft_id in draft_ids:
        state_path = draft_root / draft_id / "draft_state.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        drafts.append({"draft_id": draft_id, "draft_revision": state.get("draft_revision")})
    finals = []
    for path, record in _finalizations(draft_root, draft_ids):
        validation = record.get("validation") or {}
        qgc = validation.get("qgc_export") or {}
        mission = json.loads(Path(record["mission_path"]).read_text())
        finals.append({
            "finalization_id": record.get("finalization_id"), "draft_id": record.get("draft_id"),
            "draft_revision": record.get("draft_revision"), "mission_id": mission.get("mission_id"),
            "mission_sha256": record.get("mission_sha256"),
            "mission_sha256_verified": hcr._file_sha(Path(record["mission_path"])) == record.get("mission_sha256"),
            "mission_status": validation.get("mission_status"),
            "execution_status": validation.get("execution_status"),
            "failure_reasons": validation.get("failure_reasons"),
            "qgc_export_status": qgc.get("status"), "qgc_export_reasons": qgc.get("reasons") or qgc.get("refusal_reasons"),
            "flight_consent": record.get("flight_consent"),
            "compatibility_defaults": record.get("compatibility_defaults"),
            "_mission_path": record["mission_path"], "_finalization_path": str(path)})
    return {"drafts": drafts, "finalizations": finals,
            "source": "draft_state.json and finalization.json written by tools.hermes_mission_planning"}


def review(*, evidence_dir: Path, run_dir: Path | None = None, capture_dir: Path | None = None,
           draft_ids=None, home: Path = DEFAULT_HOME) -> dict:
    """Validate a capture of this case and write NEW reviewed evidence (SHA256SUMS)."""
    if evidence_dir.exists():
        raise DemoError("evidence directory already exists; it is never reused")
    capture_dir = capture_dir or (run_dir / "capture" if run_dir else None)
    if capture_dir is None or not capture_dir.is_dir():
        raise DemoError("no capture directory")
    captures = sorted(capture_dir.glob("hermes-events-*.jsonl"))
    records = sorted(capture_dir.glob("capture-provenance-*.json"))
    if not captures or not records:
        raise DemoError("no capture JSONL or provenance record: nothing to review")
    events, errors = common.load_events(captures)
    if errors:
        raise DemoError(f"capture does not validate: {len(errors)} error(s)")
    check = common.verify_capture_provenance(captures)
    if not check["ok"]:
        raise DemoError("capture provenance records do not verify")
    offer_files = sorted(capture_dir.glob("hermes-tool-offers-*.jsonl"))
    offers, offer_errors = hcr.load_tool_offers(offer_files)
    if offer_errors:
        raise DemoError(f"tool offer records do not validate: {len(offer_errors)} error(s)")
    texts = [p.read_text(encoding="utf-8") for p in captures + offer_files]
    case = hcr.TRIAL_CASES[CASE]
    leaks = [label for label, needle in (("prompt_turn_1", case["prompts"][0][:80]),
                                         ("prompt_turn_2", case["prompts"][1][:80]), ("url", "://"),
                                         ("home_path", str(Path.home())))
             if any(needle in t for t in texts)]
    if leaks:
        raise DemoError(f"capture contains content it must not: {leaks}")
    turns = [json.loads((run_dir / f"turn-{n}.json").read_text()) for n in (1, 2)
             if run_dir and (run_dir / f"turn-{n}.json").is_file()]
    if draft_ids is None:
        draft_ids = sorted({d for t in turns for d in t["drafts_after"]} - set(turns[0]["drafts_before"])) if turns else []
    profile = verify_profile(home=home)
    result = planning_result(Path(profile["draft_root"]), draft_ids)
    assessment = hcr.assess_tool_trial(events, offers, "", CASE)
    per_turn = {}
    for event in events:
        per_turn.setdefault(event.get("run_id") or "unlabelled", []).append(event)
    kinds = capture_summary.classify(events, "captured", check)
    summary = {
        "case": CASE, "summary": capture_summary.summarize(events, kinds), "provenance_check": check,
        "tool_isolation": assessment,
        "per_turn": {run: capture_summary.summarize(evs, capture_summary.classify(evs, "captured", check))
                     for run, evs in sorted(per_turn.items())},
        "tool_offers": {"records": len(offers), "offered_tool_names": [o["offered_tool_names"] for o in offers]},
        "limits": ["one run is not a reliability or performance measurement",
                   "token counters are Hermes-normalized; zeros may be unconfirmed",
                   "offered = tool names in each request body, not a provider-side check",
                   "the mission verdict comes from finalization.json, never from the model's text"]}
    finals = result["finalizations"]
    outcome = {
        "tool_isolation_verdict": assessment["verdict"],
        "llm_calls": assessment["llm_calls"], "llm_errors": assessment["llm_errors"],
        "tool_calls": assessment["tool_calls"],
        "finalizations": len(finals),
        "mission_validated": len(finals) == 1 and finals[0]["mission_sha256_verified"],
        "flight_consent": finals[0]["flight_consent"] if len(finals) == 1 else None,
        "models_seen": sorted({e.get("model") for e in events if e["event_type"] == "llm_call"} - {None}),
        "providers_seen": sorted({e.get("provider") for e in events if e["event_type"] == "llm_call"} - {None}),
    }
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "capture").mkdir()
    for path in captures + records + offer_files:
        hcr._write_new(evidence_dir / "capture" / path.name, path.read_bytes(), 0o644)
    for turn in turns:
        n = turn["turn"]
        public = json.loads(_redact(json.dumps({k: v for k, v in turn.items() if k not in ("sessions_started",)})))
        public["stdout_sha256"] = hcr._file_sha(run_dir / f"stdout-turn-{n}.txt")
        hcr._write_new(evidence_dir / f"turn-{n}.json", hcr._json_bytes(public), 0o644)
        stdout = (run_dir / f"stdout-turn-{n}.txt").read_text(encoding="utf-8")
        hcr._write_new(evidence_dir / f"answer-turn-{n}.txt", _redact(stdout).encode("utf-8"), 0o644)
        native = run_dir / f"native-usage-turn-{n}.json"
        if native.is_file():
            reviewed, note = hcr._review_native(native)
            hcr._write_new(evidence_dir / f"native-usage-turn-{n}.json",
                           hcr._json_bytes({"reviewed": reviewed, "review": note}), 0o644)
    for final in finals:
        hcr._write_new(evidence_dir / f"mission-{final['finalization_id']}.json",
                       Path(final["_mission_path"]).read_bytes(), 0o644)
    public_result = {**result, "finalizations": [{k: v for k, v in f.items() if not k.startswith("_")}
                                                 for f in finals]}
    hcr._write_new(evidence_dir / "planning_result.json", hcr._json_bytes(public_result), 0o644)
    hcr._write_new(evidence_dir / "capture_summary.json", hcr._json_bytes(summary), 0o644)
    hcr._write_new(evidence_dir / "outcome.json", hcr._json_bytes(outcome), 0o644)
    hcr.write_manifest(evidence_dir)
    return {"evidence_dir": str(evidence_dir), "events": len(events), **outcome}


# --- comparison: the same request straight to Ollama -------------------------------------

def ollama_probe(*, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL, timeout: float = 300) -> dict:
    """ONE chat request to the local model with the demo server's two tool schemas and the case's turn-1
    prompt, without Hermes: shows what the model alone would call. No tool is executed, nothing is saved."""
    import asyncio
    import urllib.request
    url = urlparse(base_url)
    if url.scheme != "http" or url.hostname not in LOOPBACK:
        raise DemoError("ollama-probe only talks to a loopback http endpoint")
    from tools import hermes_demo_planning_server as server
    tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                "parameters": t.input_schema}}
             for t in asyncio.run(server.mcp.list_tools())]
    body = {"model": model, "stream": False, "tools": tools,
            "messages": [{"role": "system", "content": server.INSTRUCTIONS},
                         {"role": "user", "content": hcr.TRIAL_CASES[CASE]["prompts"][0]}]}
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read())
    choice = data["choices"][0]
    calls = []
    for call in choice["message"].get("tool_calls") or []:
        try:
            arguments = json.loads(call["function"]["arguments"])
        except (TypeError, ValueError):
            arguments = call["function"]["arguments"]
        calls.append({"name": call["function"]["name"], "arguments": arguments})
    return {"mode": "ollama-probe", "llm": "REAL (local)", "hermes": False, "tool_executed": False,
            "model": data.get("model"), "endpoint": f"{url.hostname}:{url.port}",
            "elapsed_s": round(time.monotonic() - started, 2), "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage"), "tool_calls": calls, "content": choice["message"].get("content")}


# --- static view -----------------------------------------------------------------------------

def _row(cells, tag="td"):
    return "<tr>" + "".join(f"<{tag}>{html.escape(str(c))}</{tag}>" for c in cells) + "</tr>"


def _usage(event, name):
    value = ((event.get("usage") or {}).get(name) or {}).get("value")
    return "—" if value is None else value


def render_view(evidence_dir: Path) -> str:
    hcr.verify_manifest(evidence_dir)
    outcome = json.loads((evidence_dir / "outcome.json").read_text())
    result = json.loads((evidence_dir / "planning_result.json").read_text())
    events, _ = common.load_events(sorted((evidence_dir / "capture").glob("hermes-events-*.jsonl")))
    offers, _ = hcr.load_tool_offers(sorted((evidence_dir / "capture").glob("hermes-tool-offers-*.jsonl")))
    turns = [json.loads((evidence_dir / f"turn-{n}.json").read_text()) for n in (1, 2)
             if (evidence_dir / f"turn-{n}.json").is_file()]
    dry = evidence_dir / "opik_dry_run.json"
    dry_data = json.loads(dry.read_text()) if dry.is_file() else None
    llm = [e for e in events if e["event_type"] == "llm_call"]
    tools = [e for e in events if e["event_type"] == "tool_call"]
    parts = ["<!doctype html><html lang='es'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>Demo local Hermes</title><style>",
             ":root{--bg:#fff;--fg:#1d1d1f;--mut:#5f6368;--line:#d9dce1;--ok:#137333;--bad:#b3261e}",
             "@media (prefers-color-scheme: dark){:root{--bg:#141517;--fg:#e8eaed;--mut:#9aa0a6;--line:#3c4043;"
             "--ok:#81c995;--bad:#f28b82}}",
             "body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;"
             "max-width:960px;padding:16px}h1{font-size:1.4em}h2{font-size:1.1em;margin-top:1.6em}",
             "table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}td,th{border-bottom:1px "
             "solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}.mut{color:var(--mut)}",
             ".ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}",
             "pre{white-space:pre-wrap;border:1px solid var(--line);padding:8px}</style></head><body>",
             "<h1>Demo local: Hermes + Ollama + MCP de planificación</h1>",
             f"<p class='mut'>Evidencia: {html.escape(evidence_dir.name)}. Página estática generada sin red a "
             "partir de la captura revisada; no contiene prompts ni argumentos de herramientas.</p>"]
    verdict = outcome["tool_isolation_verdict"]
    good = verdict == "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS" and outcome["mission_validated"]
    parts += ["<h2>Resultado</h2><table>",
              _row(["Aislamiento de herramientas", verdict]),
              _row(["Modelo(s) que respondieron", ", ".join(outcome["models_seen"]) or "—"]),
              _row(["Proveedor (Hermes)", ", ".join(outcome["providers_seen"]) or "—"]),
              _row(["Llamadas al LLM / errores", f"{outcome['llm_calls']} / {outcome['llm_errors']}"]),
              _row(["Finalizaciones de esta ejecución", outcome["finalizations"]]),
              _row(["Autorización de vuelo", outcome["flight_consent"] or "—"]), "</table>",
              f"<p class='{'ok' if good else 'bad'}'>"
              + ("Cadena completa: herramientas permitidas, misión finalizada y validada por el código determinista."
                 if good else "La cadena no se completó; ver detalles.") + "</p>"]
    if turns:
        parts += ["<h2>Turnos del operador</h2><table>",
                  _row(["Turno", "Duración (s)", "Código", "Timeout", "Modelo configurado", "Endpoint"], "th")]
        parts += [_row([t["turn"], t["elapsed_wall_s"], t["return_code"], t["timed_out"], t["model_configured"],
                        t["base_url_configured"]]) for t in turns]
        parts.append("</table>")
    parts += ["<h2>Llamadas al modelo</h2><table>",
              _row(["Ejecución", "#", "Modelo", "Duración (s)", "1.er fragmento (s)", "Tokens entrada",
                    "Tokens salida", "Fin", "Herramientas pedidas"], "th")]
    parts += [_row([e.get("run_id"), e.get("api_call_count"), e.get("model"), e.get("api_duration_s"),
                    e.get("first_chunk_offset_s"), _usage(e, "input_tokens"), _usage(e, "output_tokens"),
                    e.get("finish_reason"), ", ".join(n or "?" for n in e.get("requested_tool_names") or []) or "—"])
              for e in llm]
    parts += ["</table>", "<h2>Llamadas a herramientas MCP</h2><table>",
              _row(["Ejecución", "Herramienta", "Estado", "Duración (ms)"], "th")]
    parts += [_row([e.get("run_id"), e.get("tool_name"), e.get("status"), e.get("duration_ms_measured")])
              for e in tools]
    offered = sorted({n for o in offers for n in (o["offered_tool_names"] or [])})
    parts += ["</table>", f"<p>Herramientas ofrecidas al modelo en {len(offers)} peticiones: "
              f"{html.escape(', '.join(offered) or '—')}</p>", "<h2>Misión</h2><table>",
              _row(["Misión", "Estado de misión", "Estado de ejecución", "Exportación QGC", "Motivos QGC",
                    "Consentimiento"], "th")]
    parts += [_row([f["mission_id"], f["mission_status"], f["execution_status"], f["qgc_export_status"],
                    "; ".join(map(str, f["qgc_export_reasons"] or [])) or "—", f["flight_consent"]])
              for f in result["finalizations"]]
    parts.append("</table>")
    if any(f["qgc_export_status"] == "REFUSED" for f in result["finalizations"]):
        parts.append("<p class='mut'>REFUSED en la exportación QGC es el comportamiento esperado: el borrador no "
                     "lleva la altitud AMSL real del punto de inicio, y el exportador estricto no la inventa. No "
                     "afecta a la validación de la misión.</p>")
    if dry_data:
        parts += ["<h2>Opik (dry-run, no enviado)</h2><table>",
                  _row(["Destino", json.dumps(dry_data.get("destination"), ensure_ascii=False)]),
                  _row(["Trazas / spans", f"{dry_data.get('traces')} / {dry_data.get('spans')}"]), "</table>"]
    for t in turns:
        answer = evidence_dir / f"answer-turn-{t['turn']}.txt"
        if answer.is_file():
            parts += [f"<h2>Respuesta final de Hermes, turno {t['turn']}</h2>",
                      f"<pre>{html.escape(answer.read_text(encoding='utf-8'))}</pre>"]
    parts.append("</body></html>\n")
    return "".join(parts)


def write_view(evidence_dir: Path) -> dict:
    target = evidence_dir / "view.html"
    if target.exists():
        raise DemoError("view.html already exists")
    hcr._write_new(target, render_view(evidence_dir).encode("utf-8"), 0o644)
    hcr.write_manifest(evidence_dir)
    return {"view": str(target)}


# --- CLI ------------------------------------------------------------------------------------

def main(argv=None, *, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare-profile")
    prep.add_argument("--hermes-home", type=Path, default=DEFAULT_HOME)
    prep.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    prep.add_argument("--base-url", default=DEFAULT_BASE_URL)
    prep.add_argument("--model", default=DEFAULT_MODEL)
    ver = sub.add_parser("verify-profile")
    ver.add_argument("--hermes-home", type=Path, default=DEFAULT_HOME)
    ver.add_argument("--offered-tools", action="store_true", help="also ask Hermes offline (prompt-size)")
    run = sub.add_parser("turn")
    run.add_argument("--hermes-home", type=Path, default=DEFAULT_HOME)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--turn", type=int, choices=(1, 2), required=True)
    run.add_argument("--timeout", type=float, default=TURN_TIMEOUT_S)
    run.add_argument("--label", default=None)
    rev = sub.add_parser("review")
    rev.add_argument("--hermes-home", type=Path, default=DEFAULT_HOME)
    rev.add_argument("--evidence-dir", type=Path, required=True)
    group = rev.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-dir", type=Path)
    group.add_argument("--capture-dir", type=Path, help="a manual session's TFG_OBSERVABILITY_DIR")
    rev.add_argument("--draft-id", action="append", default=None, help="with --capture-dir: drafts to report")
    probe = sub.add_parser("ollama-probe", help="the turn-1 request straight to Ollama (no Hermes, no tool run)")
    probe.add_argument("--base-url", default=DEFAULT_BASE_URL)
    probe.add_argument("--model", default=DEFAULT_MODEL)
    view = sub.add_parser("view")
    view.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-profile":
            result = prepare_profile(home=args.hermes_home, data_root=args.data_root, base_url=args.base_url,
                                     model=args.model)
            code = 0
        elif args.command == "verify-profile":
            result = verify_profile(home=args.hermes_home)
            if args.offered_tools:
                result["offered_tools"] = offered_tools(home=args.hermes_home)
                result["ok"] = result["ok"] and result["offered_tools"]["ok"]
            code = 0 if result["ok"] else 1
        elif args.command == "turn":
            result = run_turn(home=args.hermes_home, run_dir=args.run_dir, turn=args.turn, timeout=args.timeout,
                              label=args.label)
            code = 0 if result["return_code"] == 0 and not result["timed_out"] else 2
        elif args.command == "review":
            result = review(evidence_dir=args.evidence_dir, run_dir=args.run_dir, capture_dir=args.capture_dir,
                            draft_ids=args.draft_id, home=args.hermes_home)
            code = 0
        elif args.command == "ollama-probe":
            result = ollama_probe(base_url=args.base_url, model=args.model)
            code = 0
        else:
            result = write_view(args.evidence_dir)
            code = 0
    except (DemoError, hcr.CaptureError, common.ExportError) as exc:
        print(f"local_planning_demo: {exc}", file=sys.stderr)
        return 2
    json.dump(result, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
