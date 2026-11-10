"""Sequential driver for the 11 remaining cases of hermes-planning-pilot 1.1.0 (authorized by Joel, 31/10/2026).

One capture per key, in the frozen order, no relaunch; the stop conditions of
evaluation/hermes_planning_pilot_v1_followup_2026_10_31/README.md plus: stop if a tool outside the two authorized ones
is offered or executed. A failed acceptance inside the permitted environment is a RESULT and the batch continues.
Run from the repository root with the project venv: .venv/bin/python -B <this file>
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
os.chdir(ROOT)
E = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evaluation/hermes_planning_pilot_v1"
FOLLOW = ROOT / "evaluation/hermes_planning_pilot_v1_followup_2026_10_31"
INVENTORY = FOLLOW / "store_inventory.py"
PY = [str(ROOT / ".venv/bin/python"), "-B"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
CONFIG = Path.home() / ".hermes/config.yaml"
PLUGINS = Path.home() / ".hermes/plugins"
PLAN = json.loads((FOLLOW / "remaining_cases_plan.json").read_text())
FIXED = PLAN["fixed_configuration"]
PAUSE_S = FIXED["pause_between_invocations_s"]
ALLOWED = {"mcp__tfg_mission_control__update_mission_draft", "mcp__tfg_mission_control__finalize_mission_draft"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def log(record):
    with (E / "driver_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, env=ENV, cwd=ROOT, **kwargs)


def frozen_ok():
    """Suite manifest, fixed hashes and frozen configuration; returns a list of problems."""
    problems = []
    check = subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=SUITE, capture_output=True, text=True)
    if check.returncode:
        problems.append("suite SHA256SUMS")
    fixed = json.loads((SUITE / "fixed_hashes.json").read_text())
    problems += [f"fixed hash {rel}" for rel, digest in fixed["files"].items() if sha(ROOT / rel) != digest]
    if sha(CONFIG) != FIXED["config_sha256"]:
        problems.append("config.yaml hash")
    if os.environ.get("HERMES_HOME"):
        problems.append("HERMES_HOME is set")
    return problems


def own_processes():
    out = subprocess.run(["pgrep", "-fa", r"\.local/bin/hermes|hermes-agent/|tools\.hermes_mcp_server"],
                         capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if "driver.py" not in line and "pgrep" not in line]


def observed_calls(usage_file):
    from reporting.hermes_planning_pilot import _document
    from tools.mission_report_query import export_session, session_id_from_usage, turn_from_session
    calls, answer, reasons = turn_from_session(export_session(session_id_from_usage(usage_file)))
    text = json.dumps({"turn_reasons": reasons, "final_answer": answer,
                       "calls": [{"tool_name": c["tool_name"], "args": c["args"], "status": c.get("status"),
                                  "result": _document(c["result"])} for c in calls]}, indent=2, ensure_ascii=False)
    text = text.replace(str(ROOT), "<repo>")  # finalize results carry absolute mission paths
    assert "/home/" not in text, "personal path in tool data"
    return text, answer, reasons


def one(item):
    case, key = item["case_id"], item["run_id"]
    trial = item["trial_case"]
    run_dir = E / key
    rec = {"key": key, "case_id": case, "order": item["order"], "started_at_utc": now()}
    if run_dir.exists() or (E / f"{key}.capture_output.json").exists():
        return rec, "evidence for the key already exists"
    problems = frozen_ok()
    if problems:
        rec["frozen_problems"] = problems
        return rec, "frozen hashes/configuration differ: " + ", ".join(problems)
    pre = run(PY + ["-m", "observability.hermes_capture_run", "capture", "--mcp-tool-trial", "--trial-case", trial])
    (E / f"{key}.preflight.json").write_text(pre.stdout)
    pre_json = json.loads(pre.stdout) if pre.stdout.strip() else {}
    rec["preflight_ok"] = pre_json.get("ok")
    facts = pre_json.get("facts") or {}
    if pre.returncode or not pre_json.get("ok"):
        rec["preflight_failed"] = [c["check"] for c in pre_json.get("checks", []) if not c.get("ok")]
        return rec, "preflight not ok"
    if (facts.get("provider"), facts.get("model")) != (FIXED["provider"], FIXED["model"]):
        return rec, f"provider/model differ: {facts.get('provider')}/{facts.get('model')}"
    tools = (pre_json.get("mcp_tool_trial") or {}).get("registry_names") or []
    if set(tools) != ALLOWED:
        return rec, f"preflight would offer other tools: {tools}"
    subprocess.run(["python3", "-I", str(INVENTORY), "snapshot", str(E / f"{key}.store_before.json")], check=True)
    cap = run(PY + ["-m", "observability.hermes_capture_run", "capture", "--mcp-tool-trial", "--trial-case", trial,
                    "--execute", "--timeout", str(FIXED["timeout_s"]), "--run-id", key])
    (E / f"{key}.capture_output.json").write_text(cap.stdout)
    (E / f"{key}.capture_stderr_tail.txt").write_text(cap.stderr[-4000:])
    cap_json = json.loads(cap.stdout) if cap.stdout.strip() else {}
    for k in ("return_code", "timed_out", "elapsed_wall_s", "started_at_utc", "finished_at_utc"):
        rec[k] = cap_json.get(k)
    rec["capture_rc"] = cap.returncode
    rec["restore_ok"] = (cap_json.get("restore") or {}).get("ok")
    waited, procs = 0, own_processes()
    while procs and waited < 15:
        time.sleep(1)
        waited += 1
        procs = own_processes()
    rec["processes_after"], rec["process_exit_wait_s"] = len(procs), waited
    rec["config_sha_after_ok"] = sha(CONFIG) == FIXED["config_sha256"]
    rec["plugins_after"] = sorted(p.name for p in PLUGINS.iterdir()) if PLUGINS.exists() else []
    infra = None
    if not rec["restore_ok"] or not rec["config_sha_after_ok"] or rec["plugins_after"]:
        infra = "config/plugin restore not ok"
    if procs:
        infra = "own Hermes/MCP process remaining after 15 s"
    private = Path(cap_json["private_dir"]) if cap_json.get("private_dir") else None
    if private is None:
        return rec, infra or "capture produced no private dir"
    stderr = (private / "stderr.txt").read_text(errors="replace") if (private / "stderr.txt").exists() else ""
    if rec["return_code"] not in (0, None) and any(w in stderr.lower() for w in ("login", "unauthorized", "401",
                                                                                 "re-auth", "not authenticated")):
        infra = infra or "provider authentication appears to be required"
    rev = run(PY + ["-m", "observability.hermes_capture_run", "review", "--mcp-tool-trial", "--trial-case", trial,
                    "--private-dir", str(private), "--evidence-dir", str(run_dir)])
    (E / f"{key}.review_output.json").write_text(rev.stdout)
    rec["review_rc"] = rev.returncode
    subprocess.run(["python3", "-I", str(INVENTORY), "snapshot", str(E / f"{key}.store_after.json")], check=True)
    diff = subprocess.run(["python3", "-I", str(INVENTORY), "compare", str(E / f"{key}.store_before.json"),
                           str(E / f"{key}.store_after.json"), str(E / f"{key}.store_diff.json")],
                          capture_output=True, text=True, check=True)
    store = json.loads(diff.stdout)
    rec["store_created"], rec["store_incident"] = len(store["created"]), store["incident"]
    if store["incident"]:
        infra = infra or "store incident: a previous file changed or disappeared"
    trial_summary = {}
    if (run_dir / "capture_summary.json").exists():
        trial_summary = json.loads((run_dir / "capture_summary.json").read_text()).get("mcp_tool_trial") or {}
    rec["isolation_verdict"] = trial_summary.get("verdict")
    rec["offered"], rec["executed"] = trial_summary.get("offered"), trial_summary.get("executed")
    rec["requested_tool_names"] = trial_summary.get("requested_tool_names")
    executed_names = [c.get("tool_name") for c in trial_summary.get("tool_calls") or []]
    outside = (trial_summary.get("offered") not in ("ONLY_TRIAL_TOOL_OFFERED", None)
               or any(n not in ALLOWED for n in executed_names))
    usage = private / "native-usage.json"
    answer, reasons = "", ["NO_USAGE_FILE"]
    if usage.exists():
        acc = run(PY + ["-m", "reporting.hermes_planning_pilot", "accept", "--case", case, "--usage-file", str(usage),
                        "--check-store"])
        (E / f"{key}.acceptance.json").write_text(acc.stdout)
        acceptance = json.loads(acc.stdout) if acc.stdout.strip() else {}
        rec["acceptance_status"] = acceptance.get("status")
        rec["dimensions"] = {d: v.get("status") for d, v in (acceptance.get("dimensions") or {}).items()}
        tool_reasons = ((acceptance.get("dimensions") or {}).get("tool_calls") or {}).get("reasons") or []
        outside = outside or any(r.startswith("OTHER_TOOL_CALLED") for r in tool_reasons)
        try:
            text, answer, reasons = observed_calls(usage)
            (E / f"{key}.tool_calls_observed.json").write_text(text + "\n")
        except Exception as exc:  # conserved as a result, never retried
            rec["observed_calls_error"] = f"{type(exc).__name__}: {exc}"
    from reporting.agri_scenario_summary import _model_requests
    requests = _model_requests(run_dir) if run_dir.exists() else None
    native = (json.loads((run_dir / "native_usage_reviewed.json").read_text())
              if (run_dir / "native_usage_reviewed.json").exists() else {})
    rec["accounting"] = {
        "process_execution": {"hermes_invocations": 1, "automatic_relaunch": False, "return_code": rec["return_code"],
                              "timed_out": rec["timed_out"], "elapsed_wall_s": rec["elapsed_wall_s"]},
        "normal_provider_calls": {"main_logical_requests_completed": (requests or {}).get("completed_requests"),
                                  "main_api_calls_native_usage": native.get("api_calls"),
                                  "auxiliary_api_calls_native_usage": (native.get("auxiliary") or {}).get("api_calls")},
        "internal_attempts_observed": {"llm_error_events": trial_summary.get("llm_errors"),
                                       "failed_attempts": (requests or {}).get("failed_attempts"),
                                       "client_retries": (requests or {}).get("client_retries")}}
    rec["final_answer_present"] = bool(answer.strip())
    rec["provider_failure_without_answer"] = (not answer.strip()) and bool(rec["timed_out"] or trial_summary.get("llm_errors"))
    if outside:
        infra = infra or "a tool outside the two authorized ones was offered or executed"
    rec["finished_at_utc"] = now()
    return rec, infra


def main():
    order = PLAN["runs"]
    log({"event": "batch_start", "at_utc": now(), "keys": [r["run_id"] for r in order]})
    consecutive, results, stop = 0, [], None
    for index, item in enumerate(order):
        rec, stop = one(item)
        consecutive = consecutive + 1 if rec.get("provider_failure_without_answer") else 0
        if consecutive >= 2 and not stop:
            stop = "two consecutive invocations without a final answer due to provider errors/timeouts"
        rec["stop_reason"] = stop
        log(rec)
        results.append(rec)
        print(json.dumps({k: rec.get(k) for k in ("key", "return_code", "timed_out", "elapsed_wall_s",
                                                   "isolation_verdict", "acceptance_status", "store_incident",
                                                   "stop_reason")}), flush=True)
        if stop:
            break
        if index + 1 < len(order):
            time.sleep(PAUSE_S)
    executed = [r["key"] for r in results if r.get("return_code") is not None or r.get("capture_rc") is not None]
    summary = {"finished_at_utc": now(), "stop_reason": stop,
               "executed": executed,
               "attempted_but_not_invoked": [r["key"] for r in results if r["key"] not in executed],
               "not_executed": [r["run_id"] for r in order[len(results):]],
               "technical_failures": [r["key"] for r in results if r.get("acceptance_status") == "TECHNICAL_FAILURE"
                                      or r.get("return_code") not in (0, None) or r.get("timed_out")]}
    (E / "batch_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    log({"event": "batch_end", **summary})
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
