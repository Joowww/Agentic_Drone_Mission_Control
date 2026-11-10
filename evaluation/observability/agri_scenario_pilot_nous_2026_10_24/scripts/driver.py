"""Sequential pilot driver: one invocation per key, no retries, stop on infrastructure failure."""
import hashlib, json, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path("<repo>")
E = REPO / "evaluation/observability/agri_scenario_pilot_nous_2026_10_24"
PY = str(REPO / ".venv/bin/python")
CONFIG = Path.home() / ".hermes/config.yaml"
PLUGINS = Path.home() / ".hermes/plugins"
CONFIG_SHA = "c99d1a88cb3cf578973d50e84b12d605b7b2ec28225ff55a034282d6fe08f4fb"
CASE = "agri-scenario-pilot-real"
LOG = E / "driver_log.jsonl"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(argv, **kw):
    return subprocess.run(argv, cwd=REPO, capture_output=True, text=True, **kw)


def own_processes():
    out = run(["pgrep", "-af", "hermes|tools.hermes_mcp_server"]).stdout.splitlines()
    return [l for l in out if "pgrep" not in l and "driver.py" not in l]


def log(rec):
    with LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def one(key):
    rec = {"key": key}
    d = E / key
    if d.exists():
        rec["skipped"] = "evidence already exists; not re-invoked"
        return rec, None
    pre = run([PY, "-m", "observability.hermes_capture_run", "capture", "--mcp-tool-trial", "--trial-case", CASE])
    rec["preflight_rc"] = pre.returncode
    prej = json.loads(pre.stdout) if pre.stdout.strip() else {}
    rec["preflight_ok"] = prej.get("ok")
    if pre.returncode or not prej.get("ok"):
        rec["preflight_failed"] = [c for c in prej.get("checks", []) if not c.get("ok")]
        return rec, "preflight not ok"
    cap = run([PY, "-m", "observability.hermes_capture_run", "capture", "--mcp-tool-trial", "--trial-case", CASE,
               "--execute", "--timeout", "300", "--run-id", key])
    rec["capture_rc"] = cap.returncode
    capj = json.loads(cap.stdout) if cap.stdout.strip() else {}
    rec["capture_stderr_tail"] = cap.stderr[-800:]
    for k in ("private_dir", "started_at_utc", "finished_at_utc", "elapsed_wall_s", "return_code", "timed_out", "restore"):
        rec[k] = capj.get(k)
    rec["config_sha_after"] = sha(CONFIG)
    rec["plugins_after"] = sorted(p.name for p in PLUGINS.iterdir()) if PLUGINS.exists() else []
    rec["processes_after"] = own_processes()
    waited = 0
    while rec["processes_after"] and waited < 15:
        time.sleep(1); waited += 1
        rec["processes_after"] = own_processes()
    rec["process_exit_wait_s"] = waited
    infra = None
    if not capj.get("restore", {}).get("ok") or rec["config_sha_after"] != CONFIG_SHA or rec["plugins_after"]:
        infra = "config/plugin restore not ok"
    if rec["processes_after"]:
        infra = "own Hermes/MCP process remaining"
    P = Path(capj["private_dir"]) if capj.get("private_dir") else None
    if P is None:
        return rec, infra or "capture produced no private dir"
    rev = run([PY, "-m", "observability.hermes_capture_run", "review", "--mcp-tool-trial", "--trial-case", CASE,
               "--private-dir", str(P), "--evidence-dir", str(d)])
    rec["review_rc"] = rev.returncode
    rec["review_stderr_tail"] = rev.stderr[-800:]
    d.mkdir(parents=True, exist_ok=True)
    (d / "preflight.json").write_text(pre.stdout)
    (d / "capture_output.json").write_text(cap.stdout)
    for f in ("stdout", "stderr"):
        if (P / f"{f}.txt").exists() and not (d / f"hermes_{f}.txt").exists():
            shutil.copy(P / f"{f}.txt", d / f"hermes_{f}.txt")
    usage = P / "native-usage.json"
    if usage.exists():
        acc = run([PY, "-m", "reporting.agri_scenario_summary", "accept-h3b", "--usage-file", str(usage)])
        rec["accept_rc"] = acc.returncode
        (d / "accept_h3b.json").write_text(acc.stdout if acc.stdout.strip() else json.dumps({"error": acc.stderr[-2000:]}))
        tr = run([PY, "-c", (
            "import json,sys\nfrom pathlib import Path\n"
            "from observability.mission_report_acceptance import _result_document\n"
            "from tools.mission_report_query import export_session, session_id_from_usage, turn_from_session\n"
            "calls,_,_=turn_from_session(export_session(session_id_from_usage(Path(sys.argv[1]))))\n"
            "out=[{'tool_name':c['tool_name'],'arguments':c['args'],'status':c.get('status'),'result':_result_document(c['result'])} for c in calls]\n"
            "t=json.dumps(out,indent=2,ensure_ascii=False); assert '/home/' not in t; print(t)"), str(usage)])
        rec["tool_result_rc"] = tr.returncode
        if tr.returncode == 0:
            (d / "tool_result_as_received.json").write_text(tr.stdout)
        else:
            rec["tool_result_error"] = tr.stderr[-800:]
    else:
        rec["accept_rc"] = None
        rec["no_usage_file"] = True
    try:
        acc = json.loads((d / "accept_h3b.json").read_text())
        rec["status"] = acc.get("status")
        rec["failed_keys"] = acc.get("failed_keys")
    except Exception as exc:  # recorded, not repaired
        rec["status"] = None
        rec["accept_parse_error"] = repr(exc)
    try:
        t = json.loads((d / "capture_summary.json").read_text())["mcp_tool_trial"]
        rec["review_verdict"] = t.get("verdict")
        rec["llm_calls"] = t.get("llm_calls")
        rec["llm_errors"] = t.get("llm_errors")
    except Exception as exc:
        rec["review_parse_error"] = repr(exc)
    return rec, infra


def main():
    keys = [f"pilot-real-r{i:02d}" for i in range(1, 11)]
    if len(sys.argv) > 1:
        keys = sys.argv[1:]
    no_response_streak = 0
    for i, key in enumerate(keys):
        rec, stop = one(key)
        no_response = rec.get("status") is None and bool(rec.get("llm_errors") or rec.get("timed_out"))
        no_response_streak = no_response_streak + 1 if no_response and "skipped" not in rec else 0
        if no_response_streak >= 2:
            stop = stop or "two consecutive invocations without a final answer due to provider errors/timeouts"
        rec["stop_reason"] = stop
        log(rec)
        print(json.dumps({k: rec.get(k) for k in ("key", "capture_rc", "timed_out", "elapsed_wall_s", "review_verdict",
                                                     "status", "failed_keys", "stop_reason", "skipped")}), flush=True)
        if stop:
            log({"stopped_after": key, "reason": stop, "not_executed": keys[i + 1:]})
            print("STOPPED", stop, "not executed:", keys[i + 1:], flush=True)
            return 1
        if i + 1 < len(keys):
            time.sleep(60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
