"""Hermes profile wired to the supervisor's MCP server, and recorded Hermes sessions with proof of the tool calls.

  python -m multiagent.supervisor.hermes_profile prepare --out <private dir> [--provider ollama-local|eetac|aida-qwen]
  python -m multiagent.supervisor.hermes_profile verify
  python -m multiagent.supervisor.hermes_profile session --out <private dir> --run-dir <new dir> --text "<request>"

``prepare`` writes the config of an EXISTING profile (``hermes profile create tfg-supervisor --no-skills
--no-alias``): the model block of the selected provider (providers.hermes_model_block: base URL, model and only the
NAME of the key variable), ONE MCP server (tfg-supervisor, the four planning/status tools), the metadata-only
capture plugin (observability/hermes_capture) and nothing else: no built-in toolsets, no skills, no memory.

``session`` runs ONE ``hermes -z`` turn with that profile and then proves what happened from three independent
sources, never from the model's text: (1) the capture plugin's post_tool_call events (tool names Hermes executed),
(2) the MCP server's own call log <out>/mcp_calls.jsonl filtered by this run id, (3) the mission directories the
supervisor wrote, re-checked with check_manifest. The verdict is HERMES_USED_SUPERVISOR only if the server log shows
supervisor_plan_mission for this run and the mission it returned exists with an intact manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time

import yaml

from multiagent.supervisor import mcp_server, providers
from multiagent.supervisor.plans import check_manifest

ROOT = Path(__file__).resolve().parents[2]
PROFILE = "tfg-supervisor"
HOME = Path.home() / ".hermes" / "profiles" / PROFILE
HERMES_BIN = Path(shutil.which("hermes") or Path.home() / ".local/bin/hermes")
PLUGIN_SOURCE = ROOT / "observability" / "hermes_capture"
PLUGIN_NAME = "tfg-observability-capture"
PLUGIN_FILES = ("plugin.yaml", "__init__.py", "capture.py", "event.schema.json", "tool-offer.schema.json",
                "tool-result-check.schema.json")
SECRET_ENV = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|^OPIK_|^NOUS_|^OPENROUTER|^OPENAI|^ANTHROPIC)", re.I)
SESSION_SCHEMA = "tfg.multiagent.hermes-session/1"


def supervisor_model_env(supervisor_provider: str | None, environ=None) -> dict:
    """Env block of the MCP server for the SUPERVISOR's interpretation model (distinct from Hermes' own model).
    Only names, paths and the operator's transport opt-in: never a credential value."""
    if not supervisor_provider:
        return {}
    env = os.environ if environ is None else environ
    spec = providers.specs(env)[supervisor_provider]
    block = {"TFG_LLM_PROVIDER": supervisor_provider, "TFG_LLM_FALLBACK": ""}
    if spec.key_env:
        key_file = env.get(spec.key_env + "_FILE")
        if not key_file:
            raise SystemExit(f"{spec.key_env}_FILE must name the private key file (the key itself is never written)")
        block[spec.key_env + "_FILE"] = key_file
    if spec.insecure_optin_env and env.get(spec.insecure_optin_env):
        block[spec.insecure_optin_env] = env[spec.insecure_optin_env]
    check = providers.transport_check(spec, block)
    if not check["ok"]:
        raise SystemExit("supervisor model refused: " + "; ".join(check["problems"]))
    return block


def config(*, out: Path, python: Path, provider: str, scenario: str | None = None,
           supervisor_provider: str | None = None, environ=None) -> dict:
    entry = mcp_server.hermes_profile_entry(str(python), str(out), scenario)
    entry[mcp_server.SERVER]["env"].update(supervisor_model_env(supervisor_provider, environ))
    return {
        "model": providers.hermes_model_block(provider),
        "fallback_providers": [],
        "platform_toolsets": {"cli": [mcp_server.SERVER]},
        "tools": {"tool_search": {"enabled": "off"}},
        "mcp_servers": entry,
        "plugins": {"enabled": [PLUGIN_NAME]},
        "auxiliary": {"title_generation": {"enabled": False}},
        "skills": {"project_discovery": False, "auto_load": [], "inline_shell": False},
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "curator": {"enabled": False},
        "updates": {"check": False},
        "security": {"allow_lazy_installs": False},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
    }


def prepare(*, out: Path, provider: str = "ollama-local", home: Path = HOME, python: Path | None = None,
            scenario: str | None = None, supervisor_provider: str | None = None) -> dict:
    if not (home / "config.yaml").exists():
        raise SystemExit(f"profile {home} does not exist: run `hermes profile create {PROFILE} --no-skills --no-alias`")
    python = python or Path(sys.executable)
    mcp_server.out_root({"TFG_SUPERVISOR_OUT": str(out)})        # same checks as the server (private, outside repo)
    cfg = config(out=out, python=python, provider=provider, scenario=scenario, supervisor_provider=supervisor_provider)
    header = (f"# Hermes profile {PROFILE}, written by multiagent.supervisor.hermes_profile prepare.\n"
              f"# Hermes model: {provider}; supervisor interpretation model: {supervisor_provider or 'none'}.\n"
              f"# MCP server {mcp_server.SERVER} only (planning/status, no approval or "
              "execution); capture plugin. No credential value is stored here (key_env names a variable).\n")
    text = header + yaml.safe_dump(cfg, sort_keys=False)
    (home / "config.yaml").write_text(text, encoding="utf-8")
    plugin_dir = home / "plugins" / PLUGIN_NAME
    plugin_dir.mkdir(parents=True, exist_ok=True)
    for name in PLUGIN_FILES:
        shutil.copyfile(PLUGIN_SOURCE / name, plugin_dir / name)
    return {"profile": str(home), "provider": provider, "model": cfg["model"],
            "supervisor_model_env": {k: v for k, v in cfg["mcp_servers"][mcp_server.SERVER]["env"].items()
                                     if k not in ("PYTHONPATH", "TFG_SUPERVISOR_OUT")},
            "config_sha256": hashlib.sha256(text.encode()).hexdigest(), "mcp_tools": list(mcp_server.TOOLS)}


def clean_env(home: Path = HOME, base=None, keep: tuple = ()) -> dict:
    """The environment of a Hermes run: secrets removed EXCEPT the key variable of the configured provider."""
    src = os.environ if base is None else base
    env = {k: v for k, v in src.items() if not SECRET_ENV.search(k) or k in keep}
    env.update({"HERMES_HOME": str(home), "HERMES_DISABLE_LAZY_INSTALLS": "1"})
    return env


def verify(*, home: Path = HOME, timeout: float = 180) -> dict:
    env = clean_env(home)
    p = subprocess.run([str(HERMES_BIN), "mcp", "test", mcp_server.SERVER], env=env, capture_output=True, text=True,
                       timeout=timeout, stdin=subprocess.DEVNULL, cwd=str(home))
    names = sorted(set(re.findall(r"^\s{2,}(" + "|".join(mcp_server.TOOLS) + r")\b", p.stdout, re.M)))
    forbidden = [n for n in re.findall(r"^\s{2,}([a-z_]+)\s", p.stdout, re.M) if re.search(r"approv|execut", n)]
    return {"ok": p.returncode == 0 and names == sorted(mcp_server.TOOLS) and not forbidden,
            "return_code": p.returncode, "tools": names, "forbidden_tools": forbidden,
            "stdout_tail": p.stdout[-1500:]}


PROMPT_TEMPLATE = (
    "You are the mission supervisor interface. Use the tfg-supervisor tools; do not plan the mission yourself.\n"
    "1. Call supervisor_registry to see the available vehicles.\n"
    "2. Call supervisor_plan_mission with the operator request below as 'text', copied verbatim.\n"
    "3. Call supervisor_get_manifest with the mission_id it returns.\n"
    "Then answer with: the mission status, each vehicle's plan file, sha256 and route, the decisions and any "
    "blocking reason, and the manifest sha256. Do not claim anything was approved or executed.\n\n"
    "Operator request: {text}")


def _session_rows(home: Path, since: float) -> list[dict]:
    db = home / "state.db"
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, started_at, model, billing_provider, billing_base_url FROM sessions "
                           "WHERE started_at >= ? ORDER BY started_at", (since - 1,)).fetchall()
    finally:
        con.close()
    return [{"id": r[0], "started_at": r[1], "model": r[2], "provider": r[3], "base_url": r[4]} for r in rows]


def _capture_events(capture_dir: Path) -> list[dict]:
    events = []
    for path in sorted(capture_dir.glob("hermes-events-*.jsonl")) if capture_dir.is_dir() else []:
        events += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return events


def _capture_tools(capture_dir: Path) -> list[dict]:
    """Tools Hermes EXECUTED (capture event_type tool_call): name, status, Hermes-reported duration."""
    return [{"tool_name": e.get("tool_name"), "status": e.get("status"),
             "duration_ms": e.get("duration_ms_received"), "recorded_at_utc": e.get("recorded_at_utc")}
            for e in _capture_events(capture_dir) if e.get("event_type") == "tool_call"]


def _capture_api_calls(capture_dir: Path) -> list[dict]:
    """Model requests (capture event_type llm_call): tools the model REQUESTED, finish reason, timing, tokens."""
    out = []
    for e in _capture_events(capture_dir):
        if e.get("event_type") in ("llm_call", "llm_error"):
            usage = e.get("usage") or {}
            out.append({"event_type": e["event_type"], "model": e.get("model"), "provider": e.get("provider"),
                        "requested_tool_names": e.get("requested_tool_names"), "finish_reason": e.get("finish_reason"),
                        "api_duration_s": e.get("api_duration_s"),
                        "input_tokens": (usage.get("input_tokens") or {}).get("value"),
                        "output_tokens": (usage.get("output_tokens") or {}).get("value")})
    return out


REFUSALS = ("REFUSED_UNSAFE", "NEEDS_CLARIFICATION", "INFEASIBLE", "BLOCKED")


def mission_check(out: Path, mid: str) -> dict:
    manifest, problems = check_manifest(out / mid)
    glob = out / mid / "results/global_result.json"
    return {"manifest_sha256": (manifest or {}).get("manifest_sha256"), "problems": problems if manifest else [],
            "manifest_present": manifest is not None,
            "plans": {v["plan"]["path"]: v["plan"]["sha256"] for v in (manifest or {}).get("vehicles", [])},
            "status": json.loads(glob.read_bytes())["status"] if glob.exists() else None}


def verdict_of(server_calls: list[dict], capture_tools: list[dict], missions: dict) -> str:
    """From evidence only. PLANNED: Hermes executed supervisor_plan_mission (capture), the server logged it with a
    PLANNED mission, and that mission's manifest and plan files are intact on disk. REFUSED: same proof of the call,
    and the supervisor's own refusal is recorded in the mission directory (no manifest, nothing approvable)."""
    executed = {t["tool_name"].split("__")[-1] for t in capture_tools if t["status"] == "ok"}
    plans = [c for c in server_calls if c["tool"] == "supervisor_plan_mission" and c["status"] == "OK"]
    if "supervisor_plan_mission" not in executed or not plans:
        return "SUPERVISOR_NOT_USED_OR_INCOMPLETE"
    checks = [missions.get(c.get("mission_id")) for c in plans]
    if any(m is None for m in checks):
        return "SUPERVISOR_NOT_USED_OR_INCOMPLETE"
    if all(c.get("result_status") == "PLANNED" and m["manifest_present"] and not m["problems"] and len(m["plans"]) > 0
           for c, m in zip(plans, checks)):
        return "HERMES_USED_SUPERVISOR_PLANNED"
    if all(c.get("result_status") in REFUSALS and not m["manifest_present"] and m["status"] in REFUSALS
           for c, m in zip(plans, checks)):
        return "HERMES_USED_SUPERVISOR_REFUSED"
    return "SUPERVISOR_NOT_USED_OR_INCOMPLETE"


HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
MISSION_REF = re.compile(r"\bSUP-\d{8}T\d{6}Z-[0-9a-f]{10}\b")
MAX_ATTEMPTS = 2
# a small model sometimes WRITES a tool call as text instead of emitting a structured call (observed 24/11, r06):
# it looks like a call, but Hermes executed nothing
TEXT_TOOL_CALL = re.compile(r'"(?:function|name|tool)"\s*:\s*"(?:mcp__tfg_supervisor__)?supervisor_[a-z_]+"')


def answer_check(answer: str, missions: dict, verdict: str) -> dict:
    """Separates the model's TEXT from what was really produced. Every sha256 and mission id the answer mentions
    must belong to a mission written in this session; a planning claim without a plan call is PLANNING_INCOMPLETE."""
    known_hashes = {h for m in missions.values() for h in [*m["plans"].values(), m.get("manifest_sha256")] if h}
    hashes, refs = set(HEX64.findall(answer)), set(MISSION_REF.findall(answer))
    unbacked = sorted((hashes - known_hashes) | (refs - set(missions)))
    if verdict == "HERMES_USED_SUPERVISOR_PLANNED":
        planning = "PLAN_GENERATED"
    elif verdict == "HERMES_USED_SUPERVISOR_REFUSED":
        planning = "REFUSED_BY_SUPERVISOR"
    else:
        planning = "PLANNING_INCOMPLETE"
    status = "CLAIMS_NOT_BACKED_BY_FILES" if unbacked else (
        "TEXT_ONLY_NOT_A_PLAN" if planning == "PLANNING_INCOMPLETE" else "CONSISTENT_WITH_FILES")
    message = {"PLAN_GENERATED": "Plan generated by the supervisor; files and hashes verified on disk.",
               "REFUSED_BY_SUPERVISOR": "The supervisor refused the request; no plan exists.",
               "PLANNING_INCOMPLETE": "PLANNING INCOMPLETE: the model did not call supervisor_plan_mission (or its "
                                      "mission is missing). Its text is not a plan and nothing was generated."}[planning]
    imitation = bool(TEXT_TOOL_CALL.search(answer)) and planning == "PLANNING_INCOMPLETE"
    if imitation:
        status = "TOOL_CALL_WRITTEN_AS_TEXT"
    return {"planning": planning, "answer_status": status, "unbacked_references": unbacked,
            "hashes_mentioned": len(hashes), "text_imitates_tool_call": imitation, "operator_message": message}


def reanalyze(run_dir: Path, out: Path) -> dict:
    """Recompute the evidence fields of a recorded session from its own files (capture, server calls, missions)."""
    report = json.loads((run_dir / "session.json").read_bytes())
    report["capture_tool_calls"] = _capture_tools(run_dir / "capture")
    report["capture_api_calls"] = _capture_api_calls(run_dir / "capture")
    report["missions_created"] = {mid: mission_check(out, mid) for mid in report["missions_created"]}
    report["verdict"] = verdict_of(report["server_tool_calls"], report["capture_tool_calls"],
                                   report["missions_created"])
    stdout = (run_dir / "stdout.txt").read_text(errors="replace") if (run_dir / "stdout.txt").exists() else ""
    report["answer_check"] = answer_check(stdout, report["missions_created"], report["verdict"])
    (run_dir / "session.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    return report


def upc_model_identity(environ) -> dict:
    """The model behind eetac-llm as the server publishes it (/v1/model/info): upstream id, context window. One
    authenticated GET; the key is read from the private file in memory only."""
    import urllib.request
    spec = providers.specs(environ)["eetac"]
    check = providers.transport_check(spec, environ)
    if not check["ok"]:
        return {"status": "NOT_CHECKED", "problems": check["problems"]}
    key = providers.resolve_secret(spec.key_env, environ)
    req = urllib.request.Request(spec.base_url + "/v1/model/info", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - opt-in, host-bound transport
            data = json.loads(r.read())["data"][0]
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    finally:
        del key
    return {"status": "OK", "model_name": data.get("model_name"),
            "upstream_model": (data.get("litellm_params") or {}).get("model"),
            "serving": (data.get("litellm_params") or {}).get("custom_llm_provider"),
            "max_input_tokens": (data.get("model_info") or {}).get("max_input_tokens")}


def supervisor_model_evidence(configured: str | None, model_calls: list[dict], missions: dict, out: Path,
                              server_env: dict) -> dict:
    """Proof that the supervisor's interpretation came from the configured model in THIS session: an OK call record
    from the MCP server process, no fallback, and every planned mission's request.json carrying that provenance."""
    if not configured:
        return {"required": False, "ok": None, "configured_provider": None}
    ok_calls = [c for c in model_calls if c.get("status") == "OK" and c.get("provider") == configured
                and not c.get("fallback")]
    provenance = {}
    for mid in missions:
        req = out / mid / "request.json"
        data = json.loads(req.read_bytes()) if req.exists() else {}
        p = data.get("intent_provenance") or {}
        provenance[mid] = {"status": p.get("status"), "provider": p.get("provider"), "model": p.get("model"),
                           "model_intent": data.get("model_intent"),
                           "record_run_ids": [r.get("run_id") for r in p.get("records") or []]}
    planned = [m for m, c in missions.items() if c["status"] == "PLANNED_PENDING_APPROVAL"]
    linked = all(provenance[m]["status"] == "MODEL_INTENT" and provenance[m]["provider"] == configured and
                 set(provenance[m]["record_run_ids"]) & {c.get("run_id") for c in ok_calls} for m in planned)
    identity = upc_model_identity({**os.environ, **server_env}) if configured == "eetac" else None
    return {"required": True, "configured_provider": configured, "ok": bool(ok_calls) and bool(planned) and linked,
            "model_calls": [{k: c.get(k) for k in ("run_id", "provider", "model", "response_model", "status",
                                                   "error_class", "http_status", "latency_s", "fallback",
                                                   "plaintext_optin", "prompt_sha256", "response_sha256", "usage")}
                            for c in model_calls],
            "mission_provenance": provenance, "upstream_identity": identity}


def model_transport(cfg: dict, environ) -> dict:
    """The providers' transport policy applied to the Hermes model block: a key is sent over plain HTTP to a
    non-loopback host only with the operator's explicit, host-bound opt-in (e.g. EETAC_ALLOW_HTTP_OVER_VPN)."""
    model = cfg.get("model") or {}
    base = str(model.get("base_url") or "").rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    spec = next((s for s in providers.specs(environ).values() if s.base_url.rstrip("/") == base),
                providers.ProviderSpec("custom", base, str(model.get("default")), model.get("key_env")))
    if spec.key_env != model.get("key_env"):
        spec = providers.ProviderSpec(spec.name, spec.base_url, spec.model, model.get("key_env"),
                                      insecure_optin_env=spec.insecure_optin_env)
    return {**providers.transport_check(spec, environ), "provider": spec.name, "model": model.get("default")}


def session(*, text: str, out: Path, run_dir: Path, home: Path = HOME, timeout: float = 600,
            provider: str | None = None) -> dict:
    run_dir = Path(run_dir)
    if run_dir.exists():
        raise SystemExit("run directory exists: every session uses a new one")
    run_dir.mkdir(mode=0o700, parents=True)
    (run_dir / "workspace").mkdir(mode=0o700)
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    key_env = (cfg.get("model") or {}).get("key_env")
    run_id = "hermes-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    env = clean_env(home, keep=(key_env,) if key_env else ())
    transport = model_transport(cfg, os.environ)
    if not transport["ok"]:
        raise SystemExit("Hermes not started: " + "; ".join(transport["problems"]))
    if key_env:   # the value goes only into the Hermes child environment (from $KEY or the private $KEY_FILE)
        env[key_env] = providers.resolve_secret(key_env, os.environ)
    env.update({"TFG_OBSERVABILITY_CAPTURE": "1", "TFG_OBSERVABILITY_DIR": str(run_dir / "capture"),
                "TFG_OBSERVABILITY_RUN_ID": run_id, "TFG_OBSERVABILITY_CASE_ID": "supervisor-3v"})
    # the MCP server process inherits Hermes' environment for the variables it is given in the profile; the run id
    # reaches it through the profile env block is not possible per run, so it is passed via the parent environment
    env["TFG_SUPERVISOR_RUN_ID"] = run_id
    prompt = PROMPT_TEMPLATE.format(text=text)
    argv = [str(HERMES_BIN), "-z", prompt, "--toolsets", mcp_server.SERVER, "--ignore-rules",
            "--usage-file", str(run_dir / "native-usage.json")]
    calls_log = out / mcp_server.CALL_LOG
    log_before = calls_log.read_text().count("\n") if calls_log.exists() else 0
    model_log = out / mcp_server.MODEL_CALL_LOG
    model_before = model_log.read_text().count("\n") if model_log.exists() else 0
    server_env = ((cfg.get("mcp_servers") or {}).get(mcp_server.SERVER) or {}).get("env") or {}
    missions_before = {p.name for p in out.iterdir() if p.is_dir()} if out.is_dir() else set()
    started_epoch, started = time.time(), time.monotonic()
    with open(run_dir / "stdout.txt", "xb") as so, open(run_dir / "stderr.txt", "xb") as se:
        proc = subprocess.Popen(argv, stdout=so, stderr=se, stdin=subprocess.DEVNULL, env=env,
                                cwd=str(run_dir / "workspace"), start_new_session=True)
        try:
            rc, timed_out = proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 15)
            rc, timed_out = proc.wait(timeout=10), True
    elapsed = round(time.monotonic() - started, 2)
    server_calls = [json.loads(line) for line in (calls_log.read_text().splitlines()[log_before:]
                                                  if calls_log.exists() else [])]
    missions = sorted({p.name for p in out.iterdir() if p.is_dir()} - missions_before)
    mission_checks = {mid: mission_check(out, mid) for mid in missions}
    model_calls = [json.loads(line) for line in (model_log.read_text().splitlines()[model_before:]
                                                 if model_log.exists() else [])]
    supervisor_model = supervisor_model_evidence(server_env.get("TFG_LLM_PROVIDER"), model_calls, mission_checks,
                                                 out, server_env)
    verdict = verdict_of(server_calls, _capture_tools(run_dir / "capture"), mission_checks)
    if supervisor_model["required"] and verdict == "HERMES_USED_SUPERVISOR_PLANNED" and not supervisor_model["ok"]:
        verdict = "SUPERVISOR_MODEL_NOT_PROVEN"
    stdout = (run_dir / "stdout.txt").read_text(errors="replace")
    report = {
        "schema": SESSION_SCHEMA, "run_id": run_id, "profile": str(home), "hermes_bin": str(HERMES_BIN),
        "model": cfg.get("model"), "transport": {k: transport[k] for k in ("provider", "scheme", "host",
                                                                           "credential_env", "credential_present",
                                                                           "plaintext_optin")}, "return_code": rc, "timed_out": timed_out, "elapsed_s": elapsed,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "operator_text": text,
        "hermes_sessions": _session_rows(home, started_epoch),
        "capture_tool_calls": _capture_tools(run_dir / "capture"),
        "capture_api_calls": _capture_api_calls(run_dir / "capture"),
        "server_tool_calls": server_calls, "missions_created": mission_checks,
        "supervisor_model": supervisor_model,
        "verdict": verdict, "answer_check": answer_check(stdout, mission_checks, verdict),
        "final_answer_excerpt": stdout[-3000:],
        "evidence_rule": "tool use is proved by the server's own log and the files on disk, never by the answer"}
    (run_dir / "session.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    return report


def session_with_attempts(*, text: str, out: Path, run_dir: Path, max_attempts: int = 1, home: Path = HOME,
                          timeout: float = 600, runner=None) -> dict:
    """At most ``max_attempts`` (1..2) INDEPENDENT Hermes sessions, each fully recorded under run_dir/attempt-N.
    A new attempt only when the previous one left PLANNING_INCOMPLETE; a supervisor refusal or a generated plan
    ends the loop (a refused request is never retried into acceptance: the supervisor decides again from the same
    text). Planning has no effect on any vehicle, so a retry can never cause one."""
    if not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise SystemExit(f"max attempts must be 1..{MAX_ATTEMPTS}")
    run_dir = Path(run_dir)
    if run_dir.exists():
        raise SystemExit("run directory exists: every session uses a new one")
    run_dir.mkdir(mode=0o700, parents=True)
    runner = runner or session
    attempts = []
    for n in range(1, max_attempts + 1):
        report = runner(text=text, out=out, run_dir=run_dir / f"attempt-{n}", home=home, timeout=timeout)
        attempts.append({"attempt": n, "run_id": report["run_id"], "verdict": report["verdict"],
                         "planning": report["answer_check"]["planning"],
                         "answer_status": report["answer_check"]["answer_status"]})
        if report["answer_check"]["planning"] != "PLANNING_INCOMPLETE":
            break
    final = report["answer_check"]
    summary = {"schema": "tfg.multiagent.hermes-attempts/1", "attempts": attempts, "max_attempts": max_attempts,
               "planning": final["planning"], "operator_message": final["operator_message"],
               "final_run_id": report["run_id"], "missions_created": report["missions_created"]}
    (run_dir / "attempts.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m multiagent.supervisor.hermes_profile")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--out", required=True)
    a.add_argument("--provider", default="ollama-local", choices=sorted(providers.specs()))
    a.add_argument("--scenario")
    a.add_argument("--supervisor-provider", choices=sorted(providers.specs()),
                   help="interpretation model used INSIDE the MCP server (e.g. eetac); its key file path and "
                        "transport opt-in are taken from <KEY>_FILE and the opt-in variable of this shell")
    sub.add_parser("verify")
    s = sub.add_parser("session")
    s.add_argument("--out", required=True); s.add_argument("--run-dir", required=True)  # noqa: E702
    s.add_argument("--text", required=True); s.add_argument("--timeout", type=float, default=600)  # noqa: E702
    s.add_argument("--max-attempts", type=int, default=1, choices=range(1, MAX_ATTEMPTS + 1),
                   help="a new recorded session only if the previous one left PLANNING_INCOMPLETE")
    sub.add_parser("providers")
    r = sub.add_parser("reanalyze")
    r.add_argument("--out", required=True); r.add_argument("--run-dir", required=True)  # noqa: E702
    args = p.parse_args(argv)
    if args.cmd == "prepare":
        print(json.dumps(prepare(out=Path(args.out), provider=args.provider, scenario=args.scenario,
                                 supervisor_provider=args.supervisor_provider), indent=2))
    elif args.cmd == "verify":
        r = verify()
        print(json.dumps(r, indent=2))
        return 0 if r["ok"] else 1
    elif args.cmd == "session":
        r = session_with_attempts(text=args.text, out=Path(args.out), run_dir=Path(args.run_dir),
                                  max_attempts=args.max_attempts, timeout=args.timeout)
        print(json.dumps(r, indent=2, default=str))
        return 0 if r["planning"] != "PLANNING_INCOMPLETE" else 2
    elif args.cmd == "reanalyze":
        r = reanalyze(Path(args.run_dir), Path(args.out))
        print(json.dumps({"run_id": r["run_id"], "verdict": r["verdict"]}, indent=2))
    elif args.cmd == "providers":
        print(json.dumps(providers.status_report(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
