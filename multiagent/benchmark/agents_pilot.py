"""First real-LLM pilot of the three agent roles (M1 supervisor, M2 drone/swarm agent, M3 rover agent), each against
M0 under the same delegation. Registered in pilots/agents_m1_m3_v1.json BEFORE any call.

    python -m multiagent.benchmark.agents_pilot --check                       # preconditions only, no model call
    python -m multiagent.benchmark.agents_pilot --run --allow-model-calls --out <new dir>

Hard limits: at most 9 real model calls in the whole pilot (CallBudget, enforced in code: a 10th call raises before
any request), one per role and case, no retry. Everything else runs deterministically. Nothing is sent anywhere
but the local Ollama; no vehicle, simulator or Opik write is involved. Results: a new sealed directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from multiagent import models
from multiagent.benchmark import pilot as base_pilot, run as bench
from multiagent.llm_agents import MultiAgentConfig

HERE = Path(__file__).parent
MANIFEST = HERE / "pilots/agents_m1_m3_v1.json"
GPU_USED_LIMIT_MIB = 1500
LOCK_QUIET = timedelta(hours=2)
MAIN_CHECKOUT_QUIET = timedelta(minutes=20)  # no file of the main checkout's working dirs changed for this long
MAIN_CHECKOUT_DIRS = ("tools", "tests", "simulation", "evaluation", "docs", "missions/generated")
PROCESS_SAMPLES = 10  # sampled 0.5 s apart: a short-lived simulator, worker or timing test is caught


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def config(manifest: dict, agents: dict, config_id: str, data_kind: str) -> MultiAgentConfig:
    roles = {}
    for role, cfg in agents.items():
        cfg = dict(cfg)
        if cfg.get("generation") == "$generation":
            cfg["generation"] = dict(manifest["generation"])
        roles[role] = cfg
    return MultiAgentConfig.model_validate({"schema": "tfg.multiagent.agents-config/1", "config_id": config_id,
                                            "data_kind": data_kind, **roles})


class CallBudget:
    """Pilot-wide limit on REAL model calls. A call beyond the limit raises before any request is made."""

    def __init__(self, limit: int):
        self.limit, self.used, self.log = limit, 0, []
        # full prompt and raw reply of every real call (traces cap long strings at MAX_STRING; this does not).
        # Only secret-looking values are redacted.
        self.exchanges = []

    def wrap(self, role, adapter):
        budget = self

        class Budgeted:
            info = adapter.info
            generation = getattr(adapter, "generation", {})

            def complete(self, messages, *, json_output=False):
                real = adapter.info.get("data_kind") != "SYNTHETIC"
                if real and budget.used >= budget.limit:
                    budget.log.append({"role": role, "refused": True})
                    raise models.AdapterDisabled(f"PILOT_CALL_BUDGET_EXHAUSTED: {budget.limit} real calls used")
                if real:
                    budget.used += 1
                started = datetime.now(timezone.utc).isoformat()
                try:
                    response = adapter.complete(messages, json_output=json_output)
                    budget.log.append({"role": role, "real": real, "n": budget.used, "at_utc": started,
                                       "latency_s": response.latency_s, "usage": response.usage})
                    if real:
                        from multiagent.tracing import SECRET_VALUE
                        prompt, raw = messages[-1]["content"], response.text or ""
                        budget.exchanges.append({
                            "n": budget.used, "role": role, "at_utc": started,
                            "prompt": SECRET_VALUE.sub("[REDACTED]", prompt),
                            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                            "raw_reply": SECRET_VALUE.sub("[REDACTED]", raw),
                            "raw_reply_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                            "finish_reason": response.finish_reason, "usage": response.usage})
                    return response
                except Exception as exc:
                    budget.log.append({"role": role, "real": real, "n": budget.used, "at_utc": started,
                                       "error": type(exc).__name__})
                    raise

            def __getattr__(self, name):
                return getattr(adapter, name)
        return Budgeted()


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=bench.ROOT, capture_output=True, text=True, check=True).stdout


def _walk_files(base: Path):
    """Every non-directory entry under ``base`` (links not followed); any read error is raised, never skipped."""
    def fail(exc):
        raise exc
    for directory, _, files in os.walk(base, onerror=fail, followlinks=False):
        for name in files:
            yield Path(directory) / name


def recent_locks(sources: dict | None = None, now: datetime | None = None) -> list[str]:
    """Lock-root entries modified in the last LOCK_QUIET in every worktree ('<worktree>:<file>'), with the same
    policy as base_pilot.reservations: an unverifiable source, a root changed since verification or a read error is
    an UNKNOWN finding, never no activity."""
    now = now or datetime.now(timezone.utc)
    sources = sources or base_pilot.lock_sources()
    if sources.get("status") != "VERIFIED":
        return [f"UNKNOWN: {r}" for r in sources.get("reasons") or ["LOCK_SOURCE_UNVERIFIED"]]
    found, unknown = [], []
    for root in sources["roots"]:
        try:
            lock_root = base_pilot.present_lock_root(sources, root)
            if lock_root is None:
                continue
            found += [f"{root}:{p.relative_to(lock_root)}" for p in _walk_files(lock_root)
                      if now - datetime.fromtimestamp(os.lstat(p).st_mtime, timezone.utc) < LOCK_QUIET]
        except OSError as exc:
            unknown.append(f"UNKNOWN: {exc}" if "LOCK_ROOT_CHANGED" in str(exc)
                           else f"UNKNOWN: LOCK_ROOT_UNREADABLE:{root}:{type(exc).__name__}")
    return sorted(found) + unknown


def recent_checkout_activity(sources: dict | None = None, now: datetime | None = None) -> list[str]:
    """Files of the OTHER worktrees of this repository (the rover's working directories) modified in the last
    MAIN_CHECKOUT_QUIET ('<worktree>:<file>'; read-only lstat, at most 20). Same policy as the lock scan: an
    unverifiable worktree set or a read error is an UNKNOWN finding, never quiet."""
    now = now or datetime.now(timezone.utc)
    sources = sources or base_pilot.lock_sources()
    if sources.get("status") != "VERIFIED":
        return [f"UNKNOWN: {r}" for r in sources.get("reasons") or ["LOCK_SOURCE_UNVERIFIED"]]
    own = base_pilot.REPO_ROOT.resolve()
    found = []
    for root in (Path(r) for r in sources["roots"] if Path(r).resolve() != own):
        for d in MAIN_CHECKOUT_DIRS:
            base = root / d
            try:
                if not stat.S_ISDIR(os.lstat(base).st_mode):
                    continue
                for path in _walk_files(base):
                    if "__pycache__" in path.parts:
                        continue
                    if now - datetime.fromtimestamp(os.lstat(path).st_mtime, timezone.utc) < MAIN_CHECKOUT_QUIET:
                        found.append(f"{root}:{path.relative_to(root)}")
                        if len(found) >= 20:
                            return found
            except FileNotFoundError:
                continue
            except OSError as exc:
                return found + [f"UNKNOWN: CHECKOUT_UNREADABLE:{base}:{type(exc).__name__}"]
    return found


def sampled_processes(samples: int = PROCESS_SAMPLES, interval_s: float = 0.5) -> list[str]:
    import time
    seen = []
    for i in range(samples):
        for line in base_pilot.host_processes():
            if line not in seen:
                seen.append(line)
        if i < samples - 1:
            time.sleep(interval_s)
    return seen


def gpu_apps() -> list[str]:
    code, out = base_pilot._run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                                 "--format=csv,noheader"])
    return [line for line in out.splitlines() if line.strip()] if code == 0 else ["NOT_MEASURED"]


def preconditions(manifest: dict, *, probes=None) -> dict:
    """Passive checks only (ps, docker top, nvidia-smi, file mtimes, Ollama tags). Nothing is stopped or started."""
    p = probes or {}
    model = {"expected_model": {"name": manifest["model"]["candidate"].split(":", 1)[1],
                                "digest": manifest["model"]["digest"]}}
    result = base_pilot.check_preconditions(model, probes=p)
    checks, facts = result["checks"], result["facts"]
    facts["gpu_compute_apps"] = p["gpu_apps"]() if "gpu_apps" in p else gpu_apps()
    checks["no_other_gpu_process"] = facts["gpu_compute_apps"] == []
    checks["gpu_nearly_idle"] = facts["gpu"].get("status") == "MEASURED" and \
        facts["gpu"]["memory_used_mib"] < GPU_USED_LIMIT_MIB
    facts["recent_vehicle_locks"] = p["locks"]() if "locks" in p else recent_locks()
    checks["no_recent_vehicle_lock_activity"] = not facts["recent_vehicle_locks"]
    facts["git_status"] = p["git"]() if "git" in p else _git("status", "--porcelain")
    checks["worktree_clean"] = not facts["git_status"].strip()
    facts["sampled_sim_processes"] = p["sampled"]() if "sampled" in p else sampled_processes()
    checks["no_simulation_process_over_5s"] = not facts["sampled_sim_processes"]
    facts["main_checkout_recent_files"] = p["activity"]() if "activity" in p else recent_checkout_activity()
    checks["main_checkout_quiet_20min"] = not facts["main_checkout_recent_files"]
    return {**result, "schema": "tfg.multiagent.agents-pilot-preconditions/1", "ok": all(checks.values())}


# ------------------------------------------------------------------------------------- metrics --
def _llm_records(records, role):
    return [r for r in records if r["agent"] == role and r["kind"] == "llm"]


def _tools(records, role):
    return [{"tool": r["name"].split(":", 1)[1], "status": r["status"],
             "requested_by": (r.get("input") or {}).get("requested_by", "model")}
            for r in records if r["agent"] == role and r["kind"] == "tool" and r["name"].startswith("tool:")]


def failure_kind(row, llm, tools, *, agent_success: bool) -> str | None:
    """Of the AGENT, not of the case: INFRASTRUCTURE (adapter/transport), TOOL (a tool crashed or timed out), PARSER
    (the reply holds a valid object our extraction missed), MODEL (the reply or the proposal was wrong), or None.
    A case rescued by the deterministic fallback still counts its agent as failed."""
    calls = [r.get("model_call") or {} for r in llm]
    if any(c.get("error_kind") == "INFRASTRUCTURE" for c in calls) or row.get("outcome") == "BLOCKED":
        return "INFRASTRUCTURE"
    if any(t["status"] in ("TOOL_ERROR", "TOOL_TIMEOUT") for t in tools):
        return "TOOL"
    for c in calls:
        if c.get("parse_error") and c.get("raw_text"):
            decoder, text = json.JSONDecoder(), c["raw_text"]
            for i, ch in enumerate(text):
                if ch == "{":
                    try:
                        obj, _ = decoder.raw_decode(text[i:])
                    except ValueError:
                        continue
                    if isinstance(obj, dict) and "proposal" in obj and "INVALID_STEP: the reply holds no JSON" in c["parse_error"]:
                        return "PARSER"
                    break
            return "MODEL"
    return None if agent_success else "MODEL"


def rover_tasks_proposed(review: dict) -> set:
    """The rover agent's tasks as (objective, target, wait point): v3 normalized decisions, else its raw tasks."""
    src = review.get("normalized_proposal") if review.get("contract") == "v3" else review.get("proposal")
    return {(t.get("objective_id"), t.get("target_point"), t.get("after_aerial_point"))
            for t in (src or {}).get("tasks") or [] if isinstance(t, dict)}


def rover_final_agreement(review: dict, proposal: dict) -> bool:
    """Second, labelled measure: the agent's tasks equal the FINAL deterministic ground tasks (after the supervisor's
    dependency check). The original agent_success compares with the rover agent's pre-dependency proposal, which
    counts a correct 'cannot plan, no drone reaches the wait point' (D12) as a disagreement."""
    final = {(t["objective_ids"][0], t["target_point"], t["after_aerial_point"])
             for t in (proposal.get("ground") or {}).get("proposals") or []}
    return review.get("status") == "FINAL" and rover_tasks_proposed(review) == final


def phases(rounds: list[dict] | None) -> dict:
    """First proposal / first validation / errors returned / second proposal / final validation, as recorded."""
    rounds = rounds or []
    first, second = (rounds + [None, None])[:2]
    pick = lambda r: None if r is None else {k: r.get(k) for k in ("status", "reason", "proposal", "accepted",  # noqa: E731
                                                                    "findings", "parse_error")}
    accepted = next((i for i, r in enumerate(rounds) if r.get("accepted")), None)
    return {"first": pick(first), "second": pick(second), "llm_rounds": len(rounds),
            "success": "FIRST_ROUND" if accepted == 0 else ("AFTER_REVISION" if accepted else "NOT_ACCEPTED"),
            "incomplete": bool(rounds) and rounds[-1].get("reason") in ("LLM_CALL_BUDGET_EXHAUSTED",
                                                                       "AGENT_TOKEN_BUDGET_EXHAUSTED",
                                                                       "TIME_BUDGET_EXHAUSTED")}


def role_row(role: str, row: dict, internals: dict) -> dict:
    records, proposal = internals["_records"], internals["_proposal"]
    llm = _llm_records(records, role)
    calls = [r.get("model_call") or {} for r in llm]
    tools = _tools(records, role)
    out = {"case_id": row["case_id"], "status": row["status"], "expected_status": row["expected_status"],
           "case_pass": row["case_pass"], "criteria": row["criteria"], "safety_ok": row["safety_ok"],
           "llm_calls": len(llm), "llm_calls_real": sum(c.get("data_kind") == "MODEL_OUTPUT" for c in calls),
           "llm_latency_s": sum(c.get("latency_s") or 0.0 for c in calls) if calls else None,
           "tokens": [c.get("usage") for c in calls], "finish_reason": [c.get("finish_reason") for c in calls],
           "parse_error": [c.get("parse_error") for c in calls if c.get("parse_error")],
           "tools": tools, "tool_calls_runtime": sum(t["requested_by"] == "runtime" for t in tools),
           "tool_calls_model": sum(t["requested_by"] == "model" for t in tools),
           "validations": [{"name": r["name"], "status": r["status"]} for r in records if r["kind"] == "validation"],
           "mission_latency_s": row["latency_s"],
           "authorization": proposal.get("authorization"), "movement_authorized": proposal.get("movement_authorized"),
           "commands_sent": proposal.get("commands_sent"), "vehicles_contacted": proposal.get("vehicles_contacted"),
           "proposal_sha256": proposal.get("proposal_sha256")}
    if role == "mission_orchestrator":
        meta = proposal.get("interpreter") or {}
        out.update(brief_valid=proposal.get("brief") is not None, extraction_accuracy=row["extraction_accuracy"],
                   json_valid=meta.get("json_valid"), interpretation=proposal.get("interpretation"))
    if role == "drone_swarm_agent":
        ev = ((proposal.get("aerial") or {}).get("evidence") or {})
        check = ev.get("model_proposal_check") or {}
        alloc = check.get("allocator") or {}
        # which allocation the final plan really uses: the model's only if it was checked AND survived deconfliction
        final_from = "DETERMINISTIC_ALTERNATIVE" if ev.get("replanned_for_coordination") else (
            "MODEL" if ev.get("allocation_source") == "MODEL_PROPOSAL_CHECKED" else "DETERMINISTIC_REFERENCE")
        out.update(allocation_source=ev.get("allocation_source"), agent_proposal_valid=check.get("valid"),
                   agent_violations=check.get("violations"), accepted_by_gate=alloc.get("accepted_by_gate"),
                   same_as_reference=check.get("same_assignment_as_reference"), rounds=alloc.get("rounds"),
                   coordination_attempts=[a["candidate"] + ":" + a["status"] for a in ev.get("coordination_attempts") or []],
                   final_allocation_from=final_from, fallback_to_reference=final_from != "MODEL",
                   phases=phases(alloc.get("rounds")),
                   decision_record=alloc.get("decision_record"),
                   deterministic_corrections=[a["candidate"] + ":" + a["status"] for a in ev.get("coordination_attempts") or []
                                              if a["candidate"] != "CHOSEN"] + (["REFERENCE_REPLACED_REJECTED_PROPOSAL"]
                                                                                if final_from == "DETERMINISTIC_REFERENCE" else []))
    if role == "rover_agent":
        review = ((proposal.get("ground") or {}).get("evidence") or {}).get("llm_review") or {}
        out.update(agreement=review.get("agreement"), agent_status=review.get("status"),
                   agent_proposal=review.get("proposal"), agent_reason=review.get("reason"),
                   verifications=review.get("verifications"), rover_gate_accepted=review.get("accepted_by_gate"),
                   contract=review.get("contract"), phases=phases(review.get("rounds")),
                   agent_success_final_outcome=rover_final_agreement(review, proposal) if review else None,
                   rover_gate_findings=[f for r in review.get("rounds") or [] for f in r.get("findings") or []],
                   decision_record=review.get("decision_record"))
    if role == "mission_orchestrator":
        out["agent_success"] = bool(out["brief_valid"]) and row["status"] == row["expected_status"]
    elif role == "drone_swarm_agent":
        out["agent_success"] = out["accepted_by_gate"] is True
    else:
        out["agent_success"] = out["agreement"] == "AGREES"  # same definition in v1, v2 and M0 comparisons
    out["failure_kind"] = failure_kind(row, llm, tools, agent_success=out["agent_success"])
    return out


# ------------------------------------------------------------------------------------- running --
def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def run_experiment(manifest, exp, *, budget, allow_model_calls, transport=None, baseline=False, simulated=None):
    spec = exp["baseline"] if baseline else exp
    kind = "DETERMINISTIC" if baseline else ("SIMULATED_MODELS" if simulated else "REAL_MODELS")
    cfg = config(manifest, spec["agents"], spec["id"] if baseline else exp["id"], kind)
    wrapper = None
    if not baseline:
        def wrapper(role, adapter):
            if transport is not None and hasattr(adapter, "transport"):
                adapter.transport = transport
            return budget.wrap(role, adapter)
    report = bench.run("rules", dataset_name=manifest["dataset"]["id"], agents_config=cfg, only=set(exp["cases"]),
                       allow_calls=allow_model_calls and not baseline, keep_internals=True, adapter_wrapper=wrapper,
                       simulated=simulated, experiment_id=f"{manifest['pilot_id']}:{spec['id'] if baseline else exp['id']}")
    internals = {i["case_id"]: i for i in report.pop("_internals")}
    rows = [role_row(exp["role"], r, internals[r["case_id"]]) for r in report["rows"]]
    return {"report": report, "internals": internals, "role_rows": rows, "config": cfg.model_dump(by_alias=True)}


def compare(llm_rows, base_rows) -> dict:
    base = {r["case_id"]: r for r in base_rows}
    per = [{"case_id": r["case_id"], "expected": r["expected_status"],
            "llm": {"status": r["status"], "pass": r["case_pass"], "agent_success": r["agent_success"],
                    "failure_kind": r["failure_kind"]},
            "m0": {"status": base[r["case_id"]]["status"], "pass": base[r["case_id"]]["case_pass"]},
            "same_status": r["status"] == base[r["case_id"]]["status"]} for r in llm_rows]
    return {"cases": per, "llm_pass": sum(p["llm"]["pass"] for p in per), "m0_pass": sum(p["m0"]["pass"] for p in per),
            "llm_agent_success": sum(bool(p["llm"]["agent_success"]) for p in per),
            "n": len(per), "note": "same cases, delegation, criteria and information; n=3: preliminary, no statistics"}


def observations(role: str, row: dict, role_row_: dict, case: dict, records: list[dict]) -> dict:
    """opik_metrics observations of one pilot row, with the agent metrics this pilot can observe. Under oracle
    delegation the brief is not the model's: brief metrics are NOT_APPLICABLE, never measured on another reply."""
    from multiagent import opik_metrics as om
    obs = om.observe(row, case, records)
    ok = lambda value, reason: {"status": om.OBSERVED, "value": value, "reason": reason}  # noqa: E731
    na = lambda reason: {"status": om.NOT_APPLICABLE, "value": None, "reason": reason}  # noqa: E731
    obs["agent_success"] = ok(int(bool(role_row_["agent_success"])), f"{role}: " + {
        "mission_orchestrator": "valid brief and expected status", "drone_swarm_agent": "proposal accepted by the gate",
        "rover_agent": "proposal agrees with the deterministic rover agent"}[role])
    model_tools = [t for t in role_row_["tools"] if t["requested_by"] == "model"]
    obs["tool_call_success"] = ok(sum(t["status"] == "OK" for t in model_tools) / len(model_tools),
                                  "OK model-requested tool calls / model-requested tool calls") if model_tools else         na("no tool call requested by the model")
    obs["iterations_used"] = ok(role_row_["llm_calls"], "model calls of the agent")
    obs["fallback_used"] = ok(int(bool(role_row_.get("fallback_to_reference"))), "deterministic reference used") \
        if role == "drone_swarm_agent" else na("no fallback in this role")
    if role != "mission_orchestrator":
        for name in ("schema_valid", "extraction_accuracy"):
            obs[name] = na("oracle delegation: the brief is the gold reference, not a model reply")
    return obs


def opik_dry_run(manifest: dict, results: dict) -> dict:
    """Traces (native fields), observed feedback scores and one Experiment_Write per pilot experiment. NOT sent.
    Ids embed the run time: a send must happen within Opik's 24 h window or be re-stamped."""
    from multiagent import opik_bridge as bridge, opik_contract as contract, opik_datasets, opik_metrics as om
    from multiagent.tracing import opik_plan
    from observability import opik_export as opik
    cases = {c["case_id"]: c for c in bench.dataset(manifest["dataset"]["id"])["suite"]["cases"]}
    version = bench.dataset(manifest["dataset"]["id"])["version"]
    out = {"status": "DRY_RUN_NOT_SENT", "destination": f"{bridge.WORKSPACE}/{bridge.PROJECT}",
           "distinct_from": "OP-1 historical import (experiment eval_v2@2 ... pilot_v1); never mixed", "experiments": {}}
    for exp_id, res in results.items():
        traces, spans, scores, items = [], [], [], []
        exp_name = f"{manifest['dataset']['id']}@{version} | {exp_id} | {manifest['pilot_id']}"
        eid = opik_datasets.experiment_id(exp_name)
        for row, rr in zip(res["report"]["rows"], res["role_rows"]):
            records = res["internals"][row["case_id"]]["_records"]
            plan = opik_plan(records, bridge.PROJECT, workspace=bridge.WORKSPACE, native_fields=True)
            traces += plan.traces
            spans += plan.spans
            trace_id = plan.traces[0]["id"]
            scores += om.score_items(trace_id, observations(res["role"], row, rr, cases[row["case_id"]], records),
                                     project=bridge.PROJECT, origin="run record")
            items.append({"experiment_id": eid, "trace_id": trace_id, "project_name": bridge.PROJECT,
                          "dataset_item_id": opik_datasets.item_id(manifest["dataset"]["id"], version, row["case_id"])})
        write = {"id": eid, "name": exp_name, "dataset_name": opik_datasets.dataset_name(manifest["dataset"]["id"]),
                 "project_name": bridge.PROJECT, "type": "regular", "status": "completed",
                 "tags": ["tfg-multiagent", "agents-pilot", f"role:{res['role']}"],
                 "metadata": {"pilot_id": manifest["pilot_id"], "role": res["role"], "model": manifest["model"],
                              "generation": manifest["generation"], "cases": [r["case_id"] for r in res["role_rows"]]}}
        contract.experiment_write(write)
        contract.experiment_items({"experiment_items": items})
        contract.feedback_score_batch({"scores": scores})
        bodies = {"traces": opik.batch_bodies("traces", traces), "spans": opik.batch_bodies("spans", spans)}
        out["experiments"][exp_id] = {
            "bodies": bodies, "experiment": write, "experiment_items": {"experiment_items": items},
            "feedback_scores": {"scores": scores},
            "body_sha256": {k: [hashlib.sha256(opik.body_bytes(b)).hexdigest() for b in v] for k, v in bodies.items()},
            "real_llm_spans": sum(s["metadata"].get("tfg_execution") == "REAL_LLM_CALL" for s in spans)}
    return out


def results_markdown(manifest: dict, summary: dict, rows: dict) -> str:
    """Readable per-role tables (what the agent did, what the gate said, the M0 comparison). n=3 per role."""
    lines = [f"# {manifest['pilot_id']}: results", "",
             f"Model {manifest['model']['candidate']} ({manifest['model']['digest'][:12]}), generation "
             f"{manifest['generation']}; dataset {manifest['dataset']['id']}; commit {summary['commit']}.",
             f"Real model calls: {summary['budget']['real_calls_used']} of {summary['budget']['limit']}. "
             f"Data kind: {summary['data_kind']}. Three cases per role: preliminary evidence, no statistics.", ""]
    for exp in manifest["experiments"]:
        llm, m0 = rows[exp["id"]]["llm"], {r["case_id"]: r for r in rows[exp["id"]]["m0"]}
        lines += [f"## {exp['id']} ({exp['role']})", "", exp["what_the_llm_decides"], "",
                  "| case | expected | LLM status | pass | agent success | failure | M0 status | M0 pass | LLM s | tokens in/out | tools runtime/model |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in llm:
            tok = r["tokens"][0] if r["tokens"] else None
            lines.append(f"| {r['case_id']} | {r['expected_status']} | {r['status']} | {r['case_pass']} | {r['agent_success']} | "
                         f"{r['failure_kind'] or '-'} | {m0[r['case_id']]['status']} | {m0[r['case_id']]['case_pass']} | "
                         f"{r['llm_latency_s'] if r['llm_latency_s'] is None else round(r['llm_latency_s'], 2)} | "
                         f"{(tok or {}).get('prompt_tokens')}/{(tok or {}).get('completion_tokens')} | "
                         f"{r['tool_calls_runtime']}/{r['tool_calls_model']} |")
        lines.append("")
        for r in llm:
            extra = {k: r.get(k) for k in ("final_allocation_from", "coordination_attempts", "agent_violations",
                                           "agreement", "rover_gate_findings", "agent_reason", "parse_error") if r.get(k)}
            if extra:
                lines.append(f"- {r['case_id']}: " + "; ".join(f"{k}={v}" for k, v in extra.items()))
        lines.append("")
    return "\n".join(lines) + "\n"


def run_pilot(out: Path, *, manifest_path: Path = MANIFEST, allow_model_calls=False, probes=None, transport=None,
              simulated=None, authorized_manifest: bool = False) -> dict:
    manifest = load_manifest(manifest_path)
    if manifest.get("status") == "PREPARED_NOT_AUTHORIZED" and not authorized_manifest:
        raise SystemExit(f"{manifest['pilot_id']} is prepared but not authorized: no model call")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    pre = preconditions(manifest, probes=probes)
    if not pre["ok"]:
        out.mkdir(parents=True, exist_ok=True)
        _write(out / "preconditions.json", pre)
        return {"status": "NOT_RUN_PRECONDITIONS", "failed": [k for k, v in pre["checks"].items() if not v]}
    if not allow_model_calls and simulated is None:
        raise SystemExit("real model calls need --allow-model-calls")
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "preconditions.json", pre)
    (out / "manifest.json").write_bytes(Path(manifest_path).read_bytes())
    budget = CallBudget(manifest["budget"]["max_real_llm_calls"])
    summary = {"pilot_id": manifest["pilot_id"], "started_utc": datetime.now(timezone.utc).isoformat(),
               "commit": probes.get("commit", lambda: "TEST")() if probes else _git("rev-parse", "HEAD").strip(),
               "data_kind": "SIMULATED_TEST_DOUBLES" if simulated else "MODEL_OUTPUT_OVER_SYNTHETIC_CASES",
               "manifest": str(Path(manifest_path).relative_to(bench.ROOT)) if Path(manifest_path).is_relative_to(bench.ROOT)
               else Path(manifest_path).name,
               "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
               "experiments": {}}
    llm_results, table = {}, {}
    for exp in manifest["experiments"]:
        llm = run_experiment(manifest, exp, budget=budget, allow_model_calls=allow_model_calls, transport=transport,
                             simulated=simulated)
        llm_results[exp["id"]] = {**llm, "role": exp["role"]}
        m0 = run_experiment(manifest, exp, budget=budget, allow_model_calls=False, baseline=True)
        for label, result in (("llm", llm), ("m0", m0)):
            d = out / exp["id"] / label
            _write(d / "report.json", result["report"])
            _write(d / "role_rows.json", result["role_rows"])
            _write(d / "config.json", result["config"])
            for case_id, i in result["internals"].items():
                (d / "traces").mkdir(parents=True, exist_ok=True)
                (d / "traces" / f"{case_id}.jsonl").write_text(
                    "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in i["_records"]))
                _write(d / "proposals" / f"{case_id}.json", i["_proposal"])
        comparison = compare(llm["role_rows"], m0["role_rows"])
        table[exp["id"]] = {"llm": llm["role_rows"], "m0": m0["role_rows"]}
        _write(out / exp["id"] / "comparison.json", comparison)
        summary["experiments"][exp["id"]] = {"role": exp["role"], "cases": exp["cases"], "comparison": comparison,
                                              "failure_kinds": {r["case_id"]: r["failure_kind"] for r in llm["role_rows"]}}
    summary["budget"] = {"limit": budget.limit, "real_calls_used": budget.used, "log": budget.log}
    (out / "exchanges.jsonl").write_text("".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n"
                                                 for e in budget.exchanges))
    _write(out / "opik" / "dry_run.json", opik_dry_run(manifest, llm_results))
    summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
    summary["physical_execution"] = {"commands_sent": 0, "vehicles_contacted": 0, "simulator_started": False,
                                     "basis": "every proposal records commands_sent 0, vehicles_contacted 0, "
                                              "movement_authorized false; no process was launched"}
    _write(out / "summary.json", summary)
    (out / "results.md").write_text(results_markdown(manifest, summary, table))
    with (out / "SHA256SUMS").open("w") as sums:
        for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
            sums.write(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.relative_to(out)}\n")
    return {"status": "RUN", **{k: summary[k] for k in ("budget", "experiments")}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--allow-model-calls", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--manifest-authorized", action="store_true",
                    help="only for a manifest marked PREPARED_NOT_AUTHORIZED, once Joel has authorized it")
    a = ap.parse_args(argv)
    if a.check:
        pre = preconditions(load_manifest(a.manifest))
        print(json.dumps({"ok": pre["ok"], "checks": pre["checks"]}, indent=1))
        return 0 if pre["ok"] else 1
    if not (a.run and a.out):
        ap.error("--run needs --out")
    result = run_pilot(a.out, manifest_path=a.manifest, allow_model_calls=a.allow_model_calls,
                       authorized_manifest=a.manifest_authorized)
    print(json.dumps(result, indent=1, default=str)[:6000])
    return 0 if result["status"] == "RUN" else 1


if __name__ == "__main__":
    sys.exit(main())


def replay_supervisor(results_dir: Path, policies=("safety/2", "safety/3")) -> dict:
    """REPLAY (no model call) of the sealed M1 replies of a pilot through each safety policy. The replies are the
    recorded raw texts (sha256-checked); only the deterministic supervisor runs again."""
    from multiagent.model_interpretation import ModelInterpreterV2
    from multiagent.orchestrator import MissionOrchestrator
    from multiagent.tracing import Tracer
    root = Path(results_dir) / "M1-supervisor-qwen-pilot/llm"
    manifest = json.loads((Path(results_dir) / "manifest.json").read_text())
    exp = next(e for e in manifest["experiments"] if e["id"] == "M1-supervisor-qwen-pilot")
    info = bench.dataset(manifest["dataset"]["id"])
    ctx = bench.load_context(bench.ROOT / info["suite"]["context"])
    cases = {c["case_id"]: c for c in info["suite"]["cases"]}
    sealed = {r["case_id"]: r["status"] for r in json.loads((root / "role_rows.json").read_text())}
    rows = []
    for cid in exp["cases"]:
        records = [json.loads(l) for l in (root / "traces" / f"{cid}.jsonl").read_text().splitlines()]
        call = next(r for r in records if r["kind"] == "llm")["model_call"]
        raw = call["raw_text"]
        if hashlib.sha256(raw.encode()).hexdigest() != call["raw_sha256"]:
            raise SystemExit(f"{cid}: the recorded reply does not match its sha256")
        row = {"case_id": cid, "expected": cases[cid]["expected"]["status"], "sealed_status": sealed[cid]}
        for policy in policies:
            context = bench.case_context(ctx, cases[cid])
            interp = ModelInterpreterV2(models.ScriptedAdapter(responder=lambda p, raw=raw: raw, model="replay:sealed-reply"),
                                        site_points=bench.site_points_of(context),
                                        prompt_id=exp["agents"]["mission_orchestrator"]["prompt_id"])
            proposal = MissionOrchestrator(context, interp, tracer=Tracer(mission_id="replay"), pipeline="v2",
                                           safety_policy=policy).run(cases[cid]["text"])
            row[policy] = {"status": proposal["status"], "reasons": proposal["reasons"][:3],
                           "pass_status": proposal["status"] == row["expected"]}
        rows.append(row)
    return {"schema": "tfg.multiagent.supervisor-replay/1", "kind": "REPLAY_OF_SEALED_REPLIES_NO_MODEL_CALL",
            "source": str(Path(results_dir).relative_to(bench.ROOT)), "rows": rows,
            "replay_reproduces_sealed": all(r["safety/2"]["status"] == r["sealed_status"] for r in rows)}


def compare_runs(v1_dir: Path, v2_dir: Path) -> dict:
    """Case by case, same definitions (case_pass, agent_success, safety_ok, failure_kind) read from each sealed run's
    role_rows; experiments matched by role. M0 is taken from the v2 run (same delegation and cases as v1's M0)."""
    def load(d):
        out = {}
        for exp in json.loads((Path(d) / "manifest.json").read_text())["experiments"]:
            rows = {lab: {r["case_id"]: r for r in json.loads((Path(d) / exp["id"] / lab / "role_rows.json").read_text())}
                    for lab in ("llm", "m0")}
            out[exp["role"]] = rows
        return out
    a, b = load(v1_dir), load(v2_dir)
    table = {}
    for role in sorted(set(a) & set(b)):
        cases = []
        for cid in b[role]["llm"]:
            v1, v2, m0 = a[role]["llm"].get(cid), b[role]["llm"][cid], b[role]["m0"][cid]
            v1m0 = (a[role]["m0"].get(cid) or {}).get("status")
            cases.append({"case_id": cid, "expected": v2["expected_status"],
                          "v1": {k: (v1 or {}).get(k) for k in ("status", "case_pass", "agent_success", "safety_ok", "failure_kind")},
                          "v2": {k: v2.get(k) for k in ("status", "case_pass", "agent_success", "safety_ok", "failure_kind")},
                          "m0": {k: m0.get(k) for k in ("status", "case_pass", "safety_ok")},
                          "m0_identical_in_both_runs": v1m0 == m0["status"]})
        count = lambda run, key: sum(bool((c[run] or {}).get(key)) for c in cases)  # noqa: E731
        table[role] = {"cases": cases, "n": len(cases),
                       "agent_success": {"v1": count("v1", "agent_success"), "v2": count("v2", "agent_success")},
                       "case_pass": {"v1": count("v1", "case_pass"), "v2": count("v2", "case_pass"), "m0": count("m0", "case_pass")},
                       "safety_ok": {"v1": count("v1", "safety_ok"), "v2": count("v2", "safety_ok"), "m0": count("m0", "safety_ok")}}
    return {"schema": "tfg.multiagent.agents-pilot-comparison/1", "v1": str(v1_dir), "v2": str(v2_dir), "roles": table,
            "note": "n=3 per role and one run per version: preliminary; v2 changed prompts and tools (see manifest)"}


# ------------------------------------------------------------------- resource isolation profile (M4c-r1) --
ISOLATION_PROFILE = "resource_isolation/1"
CONCURRENT_LLM = re.compile(r"multiagent\.benchmark\.(m4_pilot|agents_pilot|pilot|run)\b|qwen_pilot|ollama run")
OPERATIONAL = re.compile(r"\b(rover_pipe_worker|rover_ground_executor|rover_control|rover_passive_driver|"
                         r"rover_first_navigation|simulation_lifecycle)\.py\b|-m tools\.(rover_|simulation_lifecycle)")
TEST_RUNNER = re.compile(r"\b(pytest|py\.test)\b")
GPU_FREE_MIN_MIB = 4000      # qwen3:4b Q4_K_M (~2.5 GB) + an 8192-token context, with margin
HOST_AVAILABLE_MIN_MIB = 2048


def _ps_lines() -> list[str]:
    return base_pilot.process_table("pid,args") or [base_pilot.UNREADABLE_PROCESS_TABLE]


def _not_a_test(line: str) -> bool:
    """A test runner's command line names test files (e.g. test_simulation_lifecycle.py); it is CPU load (case B),
    not a simulation session (case D). A simulation a test really started is its own process and is still seen."""
    return not TEST_RUNNER.search(line)


def resource_isolation(manifest: dict, *, probes=None) -> dict:
    """Isolation by the resources the experiment actually uses, replacing the 'other checkout quiet for 20 min'
    rule (file edits in another worktree are not a GPU, model or vehicle conflict). Passive: ps, docker top,
    nvidia-smi, Ollama /api/ps and tags, git. Nothing is stopped, started, reserved or released."""
    import os
    import time
    from multiagent import agent_tools, rover_executor_bridge as rb
    p = probes or {}
    base = base_pilot.check_preconditions({"expected_model": {"name": manifest["model"]["candidate"].split(":", 1)[1],
                                                              "digest": manifest["model"]["digest"]}}, probes=p)
    facts = dict(base["facts"])
    checks = {k: base["checks"][k] for k in ("ollama_answers_locally", "model_installed_with_expected_digest",
                                             "no_external_endpoint")}
    # 1. no concurrent LLM experiment
    try:
        loaded = p["ollama_ps"]() if "ollama_ps" in p else ollama_loaded_models()
    except Exception as exc:  # noqa: BLE001
        loaded = [f"NOT_MEASURED: {type(exc).__name__}"]
    pilots = p["pilot_processes"]() if "pilot_processes" in p else \
        concurrent_pilots(_ps_ppid_lines(), own_lineage())  # an unreadable table is an UNKNOWN finding
    facts.update(ollama_loaded_models=loaded, concurrent_llm_processes=pilots)
    checks["1_no_concurrent_llm_experiment"] = loaded == [] and pilots == []
    # 2. no Gazebo/SITL session (host, sampled; container)
    sampled = p["sampled"]() if "sampled" in p else sampled_processes()
    container = p["container"]() if "container" in p else base_pilot.container_processes()
    facts["sim_processes_sampled"] = sampled
    facts["sim_processes_ignored_test_runners"] = [l[:160] for l in sampled if not _not_a_test(l)]
    sim = [l for l in sampled if _not_a_test(l)] + [l for l in container.get("matches", []) if _not_a_test(l)]
    facts["container"] = container
    checks["2_no_gazebo_or_sitl_session"] = base_pilot.container_clear(container) and not sim
    # 3-4. GPU memory and load
    g = facts["gpu"]
    apps = p["gpu_apps"]() if "gpu_apps" in p else gpu_apps()
    facts["gpu_compute_apps"] = apps
    free = (g["memory_total_mib"] - g["memory_used_mib"]) if g.get("status") == "MEASURED" else None
    checks["3_gpu_memory_sufficient"] = free is not None and free >= GPU_FREE_MIN_MIB
    checks["4_no_incompatible_gpu_load"] = apps == [] and g.get("status") == "MEASURED" and g["utilization_pct"] < 10
    mem = p["meminfo"]() if "meminfo" in p else _meminfo()
    facts["host_memory"] = mem
    checks["3b_host_memory_sufficient"] = (mem.get("available_mib") or 0) >= HOST_AVAILABLE_MIN_MIB
    # 5. no protected operation on shared resources
    locks = p["locks"]() if "locks" in p else recent_locks()
    operational = p["operational"]() if "operational" in p else \
        [l for l in _ps_lines() if (OPERATIONAL.search(l) or l == base_pilot.UNREADABLE_PROCESS_TABLE)
         and _not_a_test(l)]
    facts.update(recent_vehicle_locks=locks, operational_processes=operational)
    checks["5_no_protected_operation"] = not facts["reservations_original_checkout"] and not locks and not operational
    # 6. contracts read by the multi-agent side identified by an immutable commit; our tree clean
    status = p["git"]() if "git" in p else _git("status", "--porcelain")
    pinned = p["contract_pinned"]() if "contract_pinned" in p else _commit_has(
        "f2fd78ae1", ("tools/rover_mission_payload.py", "schemas/rover-mission-execution-v1.schema.json"))
    facts.update(git_status=status, rover_contract_commit="f2fd78ae1", rover_contract_pinned=pinned)
    checks["6_contracts_pinned_and_tree_clean"] = not status.strip() and pinned
    # 7-9. no command path; LLM tools planning-only; executor dry-run
    import inspect
    offered = set(re.findall(r'Tool\(\s*"([a-z_]+)"', inspect.getsource(agent_tools)))  # every tool an LLM can get
    facts["llm_tool_names"] = sorted(offered)
    actuation = {n for n in offered if n in agent_tools.OPERATIONAL_NAMES or
                 re.search(r"execute|arm|upload|command|takeoff|drive|motor", n)}
    checks["7_no_vehicle_command_path"] = not hasattr(rb, "send_command") and not any(
        re.search(r"mavproxy|sim_vehicle|MicroXRCEAgent", l, re.I) for l in sim + operational)
    checks["8_llm_tools_planning_only"] = not actuation
    checks["9_executor_dry_run"] = rb.DryRunRoverExecutor.physical_effect is False
    # 10. manifest and criteria integrity (the committed manifest is the one used)
    integrity = p["manifest_integrity"]() if "manifest_integrity" in p else _manifest_integrity(manifest)
    facts["manifest_integrity"] = integrity
    checks["10_manifest_and_criteria_intact"] = integrity.get("ok") is True
    # observed, not gates: CPU load and the other checkout's activity (not a resource conflict by themselves)
    facts["cpu"] = p["cpu"]() if "cpu" in p else {"cpus": os.cpu_count(), "loadavg": os.getloadavg()}
    facts["other_checkout_recent_files_INFORMATIONAL"] = p["activity"]() if "activity" in p else recent_checkout_activity()
    facts["checked_at_epoch"] = time.time()
    return {"schema": "tfg.multiagent.resource-isolation/1", "profile": ISOLATION_PROFILE, "checks": checks,
            "facts": facts, "ok": all(checks.values())}


def own_lineage(pid: int | None = None) -> set[str]:
    """This process and its ancestors up to (and including) the first 'bash -c' that launched this command (timeout,
    env...). Never a concurrent experiment. Ancestors above it (terminals, agents) are NOT included, so a pilot
    started from another shell, or another command of the same agent, is still seen."""
    import os
    pid, seen = pid or os.getpid(), set()
    while pid and pid > 1 and str(pid) not in seen:
        seen.add(str(pid))
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if re.match(r"(/usr)?(/bin/)?(ba)?sh -c ", cmd) and str(pid) != str(os.getpid()):
                break
            status = Path(f"/proc/{pid}/status").read_text()
            pid = int(next(l.split()[1] for l in status.splitlines() if l.startswith("PPid:")))
        except (OSError, StopIteration, ValueError):
            break
    return seen


def _ps_ppid_lines() -> list[str] | None:
    return base_pilot.process_table("pid,ppid,args")


def concurrent_pilots(lines: list[str], lineage: set[str]) -> list[str]:
    """``lines``: 'pid ppid args'. Excludes this command's own processes: its short lineage and the pipeline
    subshells forked from it (parent in the lineage). ``None`` (table not read) is an UNKNOWN finding."""
    if lines is None:
        return [base_pilot.UNREADABLE_PROCESS_TABLE]
    out = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) < 3 or not CONCURRENT_LLM.search(parts[2]):
            continue
        if parts[0] in lineage or parts[1] in lineage:
            continue
        out.append(line)
    return out


def ollama_loaded_models(get=None) -> list:
    """Models the local Ollama server has loaded right now (/api/ps; urllib_get already returns the parsed JSON)."""
    get = get or models.urllib_get
    return list((get("http://127.0.0.1:11434/api/ps") or {}).get("models", []))


def _meminfo() -> dict:
    try:
        rows = dict(l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines() if ":" in l)
        return {"available_mib": int(rows["MemAvailable"].split()[0]) // 1024,
                "total_mib": int(rows["MemTotal"].split()[0]) // 1024}
    except Exception as exc:  # noqa: BLE001
        return {"available_mib": None, "error": type(exc).__name__}


def _commit_has(commit: str, paths) -> bool:
    try:
        return all(subprocess.run(["git", "cat-file", "-e", f"{commit}:{p}"], cwd=bench.ROOT,
                                  capture_output=True).returncode == 0 for p in paths)
    except OSError:
        return False


def _manifest_integrity(manifest: dict) -> dict:
    """The manifest file equals its committed version, its prompt hashes match the code and the frozen datasets
    are unchanged."""
    import hashlib
    path = manifest.get("_path")
    out = {"ok": False}
    if not path:
        out["error"] = "manifest path unknown"
        return out
    rel = str(Path(path).resolve().relative_to(bench.ROOT))
    committed = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=bench.ROOT, capture_output=True).stdout
    current = Path(path).read_bytes()
    out.update(manifest=rel, sha256=hashlib.sha256(current).hexdigest(), equals_committed=committed == current)
    from multiagent import brief_provenance, supervisor_prompts
    code = {"interpret_brief/3": supervisor_prompts.TEMPLATE_SHA256, "interpret_brief/4": brief_provenance.TEMPLATE_SHA256}
    out["prompt_hashes_match"] = all(code.get(k) == v for k, v in (manifest.get("prompt_hashes") or {}).items())
    out["criteria_present"] = all(k in manifest.get("criteria", {}) for k in
                                  ("C0_safety", "C1_supervisor", "C2_drone", "C3_rover_wait", "C4_rover_plan", "C5_integrated"))
    frozen = {d: set((bench.dataset(d)["frozen_check"] or {}).values()) for d in ("eval_v3", "adversarial_v3")}
    out["frozen_datasets"] = {d: sorted(v) for d, v in frozen.items()}
    out["ok"] = out["equals_committed"] and out["prompt_hashes_match"] and out["criteria_present"] and \
        all(v <= {"MATCH"} for v in frozen.values())
    return out
