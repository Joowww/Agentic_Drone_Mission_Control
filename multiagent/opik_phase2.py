"""Opik phase 2: every remote operation PREPARED as an exact, validated, sealed dry run. Nothing is sent.

    python -m multiagent.opik_phase2 --out multiagent/benchmark/opik_imports/joowww__tfg-multiagent-benchmarks/phase2_<date>

Writes (each body validated against multiagent.opik_contract, scanned for secrets/local paths, hashed):
- qwen_pending_10.dry_run.json   the 10 real qwen3:4b pilot traces not yet sent (E07 excluded), representation v2
                                 (native model/provider/usage on the one real LLM span of each trace);
- rules_baseline_11.dry_run.json the 11 rules traces of the same cases, DETERMINISTIC_BASELINE, no tokens or cost;
- e07_native_patch.dry_run.json  PATCH of E07's LLM span to representation v2 (remote change: needs authorization);
- feedback_scores.dry_run.json   scores of the 22 traces (only OBSERVED values) + every observation with its status;
- datasets.dry_run.json          eval_v2, dev_v3, eval_v3, adversarial_v3 (Dataset_Write + items);
- experiments.dry_run.json       registry of comparisons A-F and the Opik bodies of the two executed experiments;
- dashboards.dry_run.json        the two Dashboard_Write bodies; widgets_spec.md: every widget;
- local_preview.json / .md       what the evidence shows today (tables the dashboard cannot draw);
- pending_operations.json        every remote operation, its body hashes and the authorization it needs;
- SHA256SUMS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

from observability import opik_export as opik

from multiagent import opik_bridge as bridge, opik_contract as contract, opik_dashboard, opik_datasets, opik_metrics
from multiagent.benchmark import run as bench
from multiagent.benchmark.pilot import wilson

PILOT = bridge.ROOT / "multiagent/benchmark/results/pilot_qwen3_4b_v1_2026-11-04_c00b737d3"
E07 = "01a1a76e-e360-7b24-9ca0-f4088fe20e36"
SENSITIVE = {"local path": re.compile(r"/home/|/tmp/|/root/"), "user name": re.compile(r"joelm"),
             "bearer": re.compile(r"Bearer\s+\S"), "sk- key": re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
             "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "loopback host": re.compile(r"127\.0\.0\.1|localhost")}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact(value) -> bytes:
    """Canonical bytes of a prepared body (compact, sorted keys, UTF-8): the hash a future sender must reproduce.
    Trace/span batches are hashed instead on the exact bytes observability.opik_export.send_requests produces."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8")


def scan(blob: bytes, api_key: str | None = None) -> dict:
    text = blob.decode("utf-8", "replace")
    found = {k: bool(p.search(text)) for k, p in SENSITIVE.items()}
    if api_key:
        found["api key value"] = api_key in text
    return found


def _rows(candidate):
    return {r["case_id"]: r for r in json.loads((PILOT / candidate / "report.json").read_text())["rows"]}


def _trace_records(candidate, case_id):
    return [json.loads(l) for l in (PILOT / candidate / "traces" / f"{case_id}.jsonl").read_text().splitlines()]


def trace_set(candidate: str, *, exclude=(), native_fields=True) -> dict:
    """Exact batch bodies of a set of sealed traces + a per-case table with per-case body hashes."""
    plan = bridge.historical_plan(PILOT, candidate_dir=candidate, exclude=set(exclude), native_fields=native_fields)
    if plan.errors:
        raise SystemExit(f"plan errors: {plan.errors}")
    opik._check_payload_matches_destination(plan)
    opik.check_export_allowed(plan)
    ledger = bridge.load_ledger()
    rows = _rows(candidate)
    batches = [{"kind": k, "path": p, "bytes": len(d), "body_sha256": sha(d), "body": json.loads(d)}
               for k, p, d in opik.send_requests(plan)]
    table = []
    for t in plan.traces:
        case = t["metadata"]["tfg_case_id"]
        single = bridge.subset(plan, {t["id"]})
        reqs = {k: sha(d) for k, _, d in opik.send_requests(single)}
        spans = [s for s in plan.spans if s["trace_id"] == t["id"]]
        llm = [s for s in spans if s["metadata"].get("tfg_execution") == "REAL_LLM_CALL"]
        row, m = rows[case], t["metadata"]
        table.append({"case_id": case, "trace_id": t["id"], "name": t["name"],
                      "model": (m["tfg_model"] or {}).get("model"), "digest": (m["tfg_model"] or {}).get("version"),
                      "dataset": f"{m['tfg_dataset']['id']}@{m['tfg_dataset']['version']}",
                      "dataset_sha256": m["tfg_dataset"]["sha256"], "prompt": (m["tfg_prompt"] or {}).get("template_id"),
                      "spans": len(spans), "real_llm_spans": len(llm), "deterministic_spans": len(spans) - len(llm),
                      "case_pass": row["case_pass"], "outcome": row.get("outcome"), "status": row["status"],
                      "expected": row["expected_status"], "safety_ok": row["safety_ok"],
                      "safety_class": (m.get("tfg_safety") or {}).get("classification"),
                      "extraction_accuracy": row["extraction_accuracy"],
                      "mission_latency_s": m["tfg_latency"]["mission_s"], "llm_latency_s": m["tfg_latency"]["model_call_s"],
                      "tokens": m.get("tfg_tokens"), "traces_body_sha256": reqs.get("traces"),
                      "spans_body_sha256": reqs.get("spans"),
                      "ledger": (ledger["traces"].get(t["id"]) or {}).get("status", "NOT_IN_LEDGER"),
                      "sensitive_scan": scan(compact({"t": t, "s": spans}))})
    return {"plan": plan, "batches": batches, "cases": table, "representation": "v2_native_fields" if native_fields else "v1"}


def scores(trace_sets: dict) -> dict:
    """Observations for every prepared/sent trace and the score batch of OBSERVED values only."""
    cases = {c["case_id"]: c for c in bench.dataset("eval_v2")["suite"]["cases"]}
    items, table = [], []
    for candidate, ts in trace_sets.items():
        rows = _rows(candidate)
        for entry in ts["cases"]:
            obs = opik_metrics.observe(rows[entry["case_id"]], cases[entry["case_id"]],
                                       _trace_records(candidate, entry["case_id"]))
            items += opik_metrics.score_items(entry["trace_id"], obs, project=bridge.PROJECT)
            table.append({"candidate": candidate, "case_id": entry["case_id"], "trace_id": entry["trace_id"],
                          "observations": obs})
    body = {"scores": items}
    contract.feedback_score_batch(body)
    data = compact(body)
    return {"endpoint": contract.ENDPOINTS["trace_feedback_scores"], "body": body, "bytes": len(data),
            "body_sha256": sha(data), "items": len(items), "observations": table,
            "status_counts": _status_counts(table),
            "note": "only OBSERVED SCORE metrics become items; NOT_EVALUATED / NOT_APPLICABLE / ABSENT stay out (never 0). "
                    "E07's scores are included: they attach to the existing trace without modifying it."}


def _status_counts(table):
    out = {}
    for t in table:
        for name, o in t["observations"].items():
            out.setdefault(name, {}).setdefault(o["status"], 0)
            out[name][o["status"]] += 1
    return out


def experiments(trace_sets: dict) -> dict:
    digest = "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
    gen0 = {"temperature": 0.0, "seed": 7, "num_predict": 1024, "think": False, "num_ctx": 8192, "timeout_s": 120.0}
    ds = lambda n: {"id": n, **{k: bench.dataset(n)[k] for k in ("version", "sha256", "split")}}  # noqa: E731
    core = ["case_pass", "extraction_accuracy", "schema_valid", "safety_ok", "expected_status_match",
            "unsafe_request_detected", "safe_refused", "constraints_satisfied"]

    def entry(comparison, eid, name, *, dataset, model, role, prompt, generation, repetitions, cases, status, traces=None,
              provenance, task="INTERPRET_BRIEF", metrics=core, note=None):
        return {"comparison": comparison, "id": eid, "name": name, "task": task, "dataset": dataset, "model": model,
                "agent_role": role, "prompt": prompt, "generation": generation, "seed": (generation or {}).get("seed"),
                "repetitions": repetitions, "metrics": metrics, "cases": cases, "status": status,
                "traces": traces or [], "provenance": provenance, "note": note}

    pilot_cases = sorted({c["case_id"] for c in trace_sets["rules"]["cases"]})
    qwen_traces = {c["case_id"]: c["trace_id"] for c in trace_sets["qwen"]["cases"]}
    qwen_traces["E07"] = E07
    rules_traces = {c["case_id"]: c["trace_id"] for c in trace_sets["rules"]["cases"]}
    registry = [
        entry("A", "A1-qwen-local-pilot", opik_datasets.experiment_name("eval_v2", "2", "ollama:qwen3:4b",
              "interpret_brief/1", "v1", "pilot_v1"), dataset=ds("eval_v2"),
              model={"name": "qwen3:4b", "provider": "ollama", "digest": digest}, role="mission_orchestrator (interpreter)",
              prompt="interpret_brief/1", generation=gen0, repetitions=1, cases=pilot_cases,
              status="EXECUTED_HISTORICAL", traces=[qwen_traces[c] for c in pilot_cases],
              provenance="pilot_qwen3_4b_v1_2026-11-04_c00b737d3 (sealed); E07 sent and verified, 10 prepared"),
        entry("A", "A2-rules-pilot", opik_datasets.experiment_name("eval_v2", "2", "rules", None, "v1", "pilot_v1"),
              dataset=ds("eval_v2"), model={"name": "rules-interpreter", "provider": "deterministic", "digest": None},
              role="mission_orchestrator (interpreter)", prompt=None, generation={}, repetitions=1, cases=pilot_cases,
              status="EXECUTED_HISTORICAL", traces=[rules_traces[c] for c in pilot_cases],
              provenance="same sealed pilot (rules ran on the same 11 cases); DETERMINISTIC_BASELINE, not an LLM",
              note="compared case by case with A1; never ranked as a model"),
        entry("A", "A3-aida-qwen", "eval_v3@3 | aida-qwen | interpret_brief/2 | pipeline v2", dataset=ds("eval_v3"),
              model={"name": "AIDA_QWEN_MODEL", "provider": "aida-hpc", "digest": "UNKNOWN"}, role="mission_orchestrator",
              prompt="interpret_brief/2", generation={"temperature": 0.0}, repetitions=1, cases="ALL",
              status="BLOCKED_NEEDS_VPN_AND_CREDENTIAL", provenance="plan_v1 EXP-05"),
        entry("A", "A4-hermes-provider", "eval_v3@3 | hermes | interpret_brief/2 | pipeline v2", dataset=ds("eval_v3"),
              model={"name": "poolside/laguna-s-2.1:free", "provider": "nous (Hermes)", "digest": "UNKNOWN"},
              role="mission_orchestrator", prompt="interpret_brief/2", generation={"temperature": 0.0}, repetitions=1,
              cases="ALL", status="BLOCKED_NEEDS_ENDPOINT_AND_CREDENTIAL", provenance="plan_v1 EXP-07"),
        entry("B", "B1-think-off-full", "eval_v2@2 | ollama:qwen3:4b | interpret_brief/1 | pipeline v1 | think off",
              dataset=ds("eval_v2"), model={"name": "qwen3:4b", "provider": "ollama", "digest": digest},
              role="mission_orchestrator", prompt="interpret_brief/1", generation=gen0, repetitions=1, cases="ALL",
              status="CONFIGURED_NOT_RUN", provenance="plan_v1 EXP-01 (the pilot covers 11 of 33 cases only)"),
        entry("B", "B2-think-on-full", "eval_v2@2 | ollama:qwen3:4b | interpret_brief/1 | pipeline v1 | think on",
              dataset=ds("eval_v2"), model={"name": "qwen3:4b", "provider": "ollama", "digest": digest},
              role="mission_orchestrator", prompt="interpret_brief/1",
              generation={**gen0, "think": True, "num_predict": 4096, "timeout_s": 300.0}, repetitions=1, cases="ALL",
              status="CONFIGURED_NOT_RUN", provenance="plan_v1 EXP-02"),
        entry("C", "C1-prompt-v2", "eval_v3@3 | ollama:qwen3:4b | interpret_brief/2 | pipeline v2", dataset=ds("eval_v3"),
              model={"name": "qwen3:4b", "provider": "ollama", "digest": digest}, role="mission_orchestrator",
              prompt="interpret_brief/2", generation=gen0, repetitions=1, cases="ALL", status="CONFIGURED_NOT_RUN",
              provenance="plan_v1 EXP-04 (+ adversarial_v3)"),
        entry("C", "C2-prompt-v1", "eval_v3@3 | ollama:qwen3:4b | interpret_brief/1 | pipeline v2", dataset=ds("eval_v3"),
              model={"name": "qwen3:4b", "provider": "ollama", "digest": digest}, role="mission_orchestrator",
              prompt="interpret_brief/1", generation=gen0, repetitions=1, cases="ALL", status="CONFIGURED_NOT_RUN",
              provenance="plan_v1 EXP-04b"),
    ]
    matrix = json.loads((bridge.ROOT / "multiagent/benchmark/experiments/multiagent_matrix_v1.json").read_text())
    for cfg in matrix["configurations"]:
        if cfg["id"] in ("M7-hermes-provider", "M8-supervisor-qwen-prompt-v1"):
            continue
        registry.append(entry("D", cfg["id"], f"eval_v3@3 | {cfg['id']} | pipeline v2", dataset=ds("eval_v3"),
                              model={r: a.get("candidate") or "deterministic" for r, a in cfg["agents"].items()},
                              role="per-role configuration", prompt="interpret_brief/2 (supervisor in llm mode)",
                              generation={r: a.get("generation", {}) for r, a in cfg["agents"].items()}, repetitions=1,
                              cases="ALL", status=cfg["status"].replace("RUNNABLE_OFFLINE", "RUNNABLE_OFFLINE_NOT_RUN"),
                              provenance="experiments/multiagent_matrix_v1.json",
                              metrics=core + ["agent_success", "fallback_used", "replanning_required", "conflicts_resolved",
                                              "dependency_valid", "iterations_used"], task="MULTI_AGENT"))
    registry += [
        entry("E", "E1-coordination-scenarios", "scenarios 1/2/3/5 drones | deterministic",
              dataset={"id": "swarm scenarios", "version": "v1", "sha256": None, "split": "dev"},
              model={"name": "deterministic allocator + deconfliction"}, role="drone_swarm_agent", prompt=None, generation={},
              repetitions=1, cases=["1 drone", "2 drones", "3 drones", "5 drones"], status="EXECUTED_OFFLINE_NO_TRACES",
              provenance="results/v2_2026-11-04_452e89a2f/scalability (sealed); no Opik traces were kept",
              metrics=["coordination_valid", "conflicts_detected", "conflicts_resolved", "replanning_required"],
              task="COORDINATION", note="to appear in Opik it must be re-run with traces (new run, labelled as such)"),
        entry("E", "E2-multiagent-demo-simulated", "swarm_3_tight | simulated agents | demo",
              dataset={"id": "demo", "version": "1", "sha256": None, "split": "demo"},
              model={"name": "scripted test doubles"}, role="all three", prompt="agent_drone/1, agent_rover/1",
              generation={}, repetitions=1, cases=["demo"], status="SIMULATED_ONLY_NOT_UPLOADED",
              provenance="multiagent.demo --multiagent-simulated", task="COORDINATION",
              metrics=["replanning_required", "replanning_success", "dependency_valid"],
              note="never a model result; only uploadable with its test-double labels and a separate authorization"),
        entry("F", "F1-clef-classify", "eval_v3@3 | aida-clef | CLASSIFY_REQUEST", dataset=ds("eval_v3"),
              model={"name": "clef", "provider": "aida-hpc", "digest": "UNKNOWN"}, role="advisory classifier", prompt=None,
              generation={}, repetitions=1, cases="ALL", status="BLOCKED_NEEDS_AIDA", provenance="plan_v1 EXP-06",
              task="CLASSIFY_REQUEST", metrics=["top-label accuracy", "Brier score"]),
        entry("F", "F2-clef-select-allocation", "swarm scenarios | aida-clef | SELECT_ALLOCATION",
              dataset={"id": "swarm scenarios", "version": "v1", "sha256": None, "split": "eval"},
              model={"name": "clef", "provider": "aida-hpc", "digest": "UNKNOWN"}, role="advisory decision", prompt=None,
              generation={}, repetitions=1, cases=["swarm_3", "swarm_5"], status="BLOCKED_NEEDS_AIDA",
              provenance="pilots/aida_pilot_v1.json", task="SELECT_ALLOCATION",
              metrics=["chosen option rank", "Brier score"], note="never evaluated as a plan generator")]
    bodies = []
    for exp in registry:
        if exp["status"] != "EXECUTED_HISTORICAL":
            continue
        cand = "qwen" if exp["id"].startswith("A1") else "rules"
        p = opik_datasets.experiment_payload(PILOT, candidate_dir=cand, label="pilot_v1",
                                             tags=[f"comparison:{exp['comparison']}"],
                                             metadata={"registry_id": exp["id"], "agent_role": exp["agent_role"],
                                                       "generation": exp["generation"], "task": exp["task"]})
        if p["experiment"]["name"] != exp["name"] or sorted(p["cases"]) != exp["cases"]:
            raise SystemExit(f"experiment registry and sealed run disagree: {exp['id']}")
        trace_of = {i["trace_id"] for i in p["items"]["experiment_items"]}
        if trace_of != set(exp["traces"]):
            raise SystemExit(f"experiment items do not point to the prepared traces: {exp['id']}")
        bodies.append({**p, "experiment_sha256": sha(compact(p["experiment"])), "items_sha256": sha(compact(p["items"]))})
    return {"registry": registry, "opik_bodies": bodies,
            "rule": "comparisons only over the same dataset version and task; dev, eval and adversarial never pooled"}


def datasets() -> dict:
    out = {}
    for name in opik_datasets.DATASETS:
        p = opik_datasets.dataset_payload(name)
        out[name] = {**p, "dataset_sha256": sha(compact(p["dataset"])), "items_sha256": sha(compact(p["items"])),
                     "items_count": len(p["items"]["items"])}
    return out


def _pct(values, q):
    data = sorted(v for v in values if isinstance(v, (int, float)))
    return data[max(0, math.ceil(q / 100 * len(data)) - 1)] if data else None


def local_preview(trace_sets: dict, score_set: dict) -> dict:
    """What the sealed evidence shows today: one table per LOCAL_PREVIEW widget and the key numbers."""
    by = {}
    for t in score_set["observations"]:
        by.setdefault(t["candidate"], []).append(t)
    summary = {}
    for candidate, rows in by.items():
        entry = {"n_cases": len(rows)}
        for name in opik_metrics.SCORE_NAMES:
            vals = [r["observations"][name]["value"] for r in rows if r["observations"][name]["status"] == "OBSERVED"]
            if not vals:
                entry[name] = {"n": 0, "status": "NO_OBSERVATION"}
                continue
            binary = opik_metrics.METRICS[name]["type"] == "binary"
            entry[name] = {"n": len(vals), "mean": statistics.fmean(vals),
                           **({"wilson95": wilson(int(sum(vals)), len(vals))} if binary else {})}
        cases = trace_sets[candidate]["cases"]
        entry["mission_latency_s"] = {"n": len(cases), "p50": _pct([c["mission_latency_s"] for c in cases], 50),
                                      "p90": _pct([c["mission_latency_s"] for c in cases], 90)}
        llm = [c["llm_latency_s"] for c in cases if c["llm_latency_s"] is not None]
        entry["llm_latency_s"] = {"n": len(llm), "p50": _pct(llm, 50), "p90": _pct(llm, 90)} if llm else {"n": 0}
        tokens = [c["tokens"] for c in cases if c["tokens"]]
        entry["tokens"] = {"llm_spans_with_usage": len(tokens), "llm_spans": sum(c["real_llm_spans"] for c in cases),
                           "prompt_total": sum(t["prompt_tokens"] for t in tokens) if tokens else None,
                           "completion_total": sum(t["completion_tokens"] for t in tokens) if tokens else None}
        summary[candidate] = entry
    failures = json.loads((PILOT / "analysis_v2/failures.json").read_text())
    per_case = []
    q = {c["case_id"]: c for c in trace_sets["qwen"]["cases"]}
    for c in trace_sets["rules"]["cases"]:
        qq = q.get(c["case_id"]) or {"case_pass": None, "status": "SENT_E07 (see ledger)", "safety_ok": None,
                                     "extraction_accuracy": None, "mission_latency_s": None}
        per_case.append({"case_id": c["case_id"], "expected": c["expected"],
                         "rules": {k: c[k] for k in ("status", "case_pass", "safety_ok", "extraction_accuracy")},
                         "qwen": {k: qq.get(k) for k in ("status", "case_pass", "safety_ok", "extraction_accuracy")},
                         "qwen_failure": (failures["qwen"]["cases"].get(c["case_id"]) or {}).get("primary"),
                         "rules_failure": (failures["rules"]["cases"].get(c["case_id"]) or {}).get("primary")})
    e07 = {"case_id": "E07", "trace_id": E07, "status": "VERIFIED_PRESENT (remote)"}
    seals = {}
    for d in ("pilot_qwen3_4b_v1_2026-11-04_c00b737d3", "v1_2026-11-04_70a8778eb", "v2_2026-11-04_452e89a2f",
              "v3_baseline_2026-11-04_d62216495"):
        root = bridge.ROOT / "multiagent/benchmark/results" / d
        seals[d] = all(sha((root / name).read_bytes()) == digest for digest, name in
                       (l.split("  ", 1) for l in (root / "SHA256SUMS").read_text().splitlines()))
    return {"schema": "tfg.multiagent.opik-local-preview/1", "data": "sealed pilot (11 cases, 1 run each)",
            "warnings": ["11 cases and 1 run per candidate: wide intervals; P90 of 11 values is a single observation",
                         "rules and qwen are different technologies: compared case by case, never ranked together",
                         "remote Opik holds only E07 today; everything else is prepared, not uploaded"],
            "summary": summary, "per_case": per_case, "e07_note": e07,
            "failure_distribution": {k: failures[k]["summary"] for k in ("rules", "qwen")},
            "metric_coverage": score_set["status_counts"], "gpu": _gpu(), "seals_intact": seals,
            "provenance": {"model_digest": "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7",
                           "prompt": "interpret_brief/1", "seed": 7, "temperature": 0.0, "think": False,
                           "dataset": {"id": "eval_v2", "sha256": bench.dataset("eval_v2")["sha256"]}},
            "latency_vs_accuracy": [{"case_id": c["case_id"], "qwen_llm_latency_s": c["llm_latency_s"],
                                     "qwen_case_pass": c["case_pass"]} for c in trace_sets["qwen"]["cases"]]}


def _gpu():
    recs = [json.loads(l) for l in (PILOT / "qwen/records.jsonl").read_text().splitlines()]
    vals = [r["resources"]["after"]["gpu"]["memory_used_mib"] for r in recs
            if (r.get("resources") or {}).get("after", {}).get("gpu", {}).get("status") == "MEASURED"]
    return {"n": len(vals), "max_mib": max(vals) if vals else None, "basis": "whole-GPU nvidia-smi after each call"}


def preview_markdown(p: dict) -> str:
    lines = ["# Opik local preview (sealed evidence, no upload)", ""] + [f"- {w}" for w in p["warnings"]]
    lines += ["", "| metric | rules (n) | qwen3:4b (n) |", "| --- | --- | --- |"]
    for name in opik_metrics.SCORE_NAMES:
        cells = []
        for cand in ("rules", "qwen"):
            m = p["summary"][cand][name]
            cells.append("—" if m["n"] == 0 else f"{m['mean']:.3f} ({m['n']})" +
                         (f" [{m['wilson95'][0]:.2f}, {m['wilson95'][1]:.2f}]" if "wilson95" in m else ""))
        lines.append(f"| {name} | {cells[0]} | {cells[1]} |")
    lines += ["", "| case | expected | rules | qwen3:4b | qwen failure |", "| --- | --- | --- | --- | --- |"]
    for c in p["per_case"]:
        lines.append(f"| {c['case_id']} | {c['expected']} | {c['rules']['status']} ({'PASS' if c['rules']['case_pass'] else 'FAIL'}) | "
                     f"{c['qwen']['status']} ({'PASS' if c['qwen']['case_pass'] else ('FAIL' if c['qwen']['case_pass'] is False else 'see E07')}) | "
                     f"{c['qwen_failure'] or '—'} |")
    return "\n".join(lines) + "\n"


def pending(qwen, rules, patch, score_set, ds, exps, dashboards) -> list[dict]:
    def op(oid, what, endpoint, hashes, prerequisites, authorization, risk):
        return {"id": oid, "what": what, "endpoint": endpoint, "body_sha256": hashes, "prerequisites": prerequisites,
                "authorization_needed": authorization, "status": "PREPARED_NOT_SENT", "notes": risk}
    return [
        op("OP-1", "send the 10 pending qwen3:4b traces (E07 excluded)", contract.ENDPOINTS["traces_batch"][1:] +
           contract.ENDPOINTS["spans_batch"][1:], {b["kind"]: b["body_sha256"] for b in qwen["batches"]}, [],
           "explicit: the 10 case ids, the two hashes, joowww/tfg-multiagent-benchmarks",
           "opik_bridge.send_import(max_traces=10); then verify each trace id"),
        op("OP-2", "send the 11 rules traces (DETERMINISTIC_BASELINE)", contract.ENDPOINTS["traces_batch"][1:] +
           contract.ENDPOINTS["spans_batch"][1:], {b["kind"]: b["body_sha256"] for b in rules["batches"]}, [],
           "explicit: the 11 rules trace ids and hashes", "no tokens or cost; type tool for the interpreter step"),
        op("OP-3", "PATCH E07's LLM span to native model/provider/usage", patch["path"],
           {"body": sha(compact(patch["body"]))}, [], "explicit: modifies a remote span already sent",
           "endpoint SPEC_ONLY; Opik may attempt cost estimation from provider+model: verify no cost appears"),
        op("OP-4", "upload feedback scores of the traces present", contract.ENDPOINTS["trace_feedback_scores"][1],
           {"body": score_set["body_sha256"]}, ["OP-1", "OP-2 (for their traces)"],
           "explicit: score names and count", "SPEC_ONLY; scores for unsent traces must be filtered out before sending"),
        op("OP-5", "create the 4 datasets and their items", "POST /v1/private/datasets + PUT /v1/private/datasets/items",
           {n: {"dataset": d["dataset_sha256"], "items": d["items_sha256"]} for n, d in ds.items()}, [],
           "explicit: dataset names", "SPEC_ONLY; try one dataset with one item first and read it back"),
        op("OP-6", "create the 2 executed experiments and link items to traces",
           "POST /v1/private/experiments + POST /v1/private/experiments/items",
           {b["experiment"]["name"]: {"experiment": b["experiment_sha256"], "items": b["items_sha256"]}
            for b in exps["opik_bodies"]}, ["OP-1", "OP-2", "OP-5"], "explicit", "SPEC_ONLY"),
        op("OP-7", "create the 2 dashboards", contract.ENDPOINTS["dashboard_create"][1],
           {b["name"]: sha(compact(b)) for b in dashboards}, ["OP-1..OP-6 for data to show"],
           "explicit", "config shape from the frontend; open once in the UI; manual creation is the fallback")]


def build(out: Path, *, source_commit: str = "UNRECORDED") -> dict:
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    bridge.verify_seal(PILOT)
    qwen = trace_set("qwen", exclude={"E07"})
    rules = trace_set("rules")
    patch = bridge.native_patch(PILOT, "E07")
    contract.span_update(patch["body"])
    score_set = scores({"qwen": trace_set("qwen", native_fields=True), "rules": rules})
    ds, exps = datasets(), experiments({"qwen": qwen, "rules": rules})
    dashboards = opik_dashboard.dashboard_bodies()
    spec = opik_dashboard.widgets()
    preview = local_preview({"qwen": trace_set("qwen", native_fields=True), "rules": rules}, score_set)
    ops = pending(qwen, rules, patch, score_set, ds, exps, dashboards)
    strip = lambda ts: {"representation": ts["representation"], "batches": ts["batches"], "cases": ts["cases"]}  # noqa: E731
    files = {"qwen_pending_10.dry_run.json": strip(qwen), "rules_baseline_11.dry_run.json": strip(rules),
             "e07_native_patch.dry_run.json": patch, "feedback_scores.dry_run.json": score_set,
             "datasets.dry_run.json": ds, "experiments.dry_run.json": exps,
             "dashboards.dry_run.json": {"bodies": dashboards, "spec": spec, "contract": contract.SOURCE},
             "local_preview.json": preview, "pending_operations.json": {"status": "NOTHING_SENT", "operations": ops},
             "metrics_dictionary.json": opik_metrics.METRICS}
    try:  # only to prove the key value is in no file; never printed or stored
        key = bridge._api_key(config_path=bridge.CONFIG_PATH)
    except opik.ExportError:
        key = None
    findings = {}
    for name, value in files.items():
        data = json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False).encode()
        found = scan(data, key)
        if any(found.values()):
            findings[name] = {k: v for k, v in found.items() if v}
        (out / name).write_bytes(data + b"\n")
    key = None
    (out / "widgets_spec.md").write_text(opik_dashboard.spec_markdown(spec))
    (out / "local_preview.md").write_text(preview_markdown(preview))
    (out / "README.md").write_text(
        "# Opik phase 2: prepared, NOT sent\n\nEvery file is a dry run built from sealed evidence. No trace, score, "
        "dataset, experiment or dashboard was sent. E07 stays VERIFIED_PRESENT in the ledger and is not re-sent. "
        f"Built {datetime.now(timezone.utc).date()} from commit {source_commit} against the Opik contract pinned in "
        "multiagent/opik_contract.py. Hashes: trace/span batches over the exact bytes the sender produces; every other "
        "body over its canonical form (compact JSON, sorted keys, UTF-8).\n")
    with (out / "SHA256SUMS").open("w") as sums:
        for path in sorted(p for p in out.iterdir() if p.name != "SHA256SUMS"):
            sums.write(f"{sha(path.read_bytes())}  ./{path.name}\n")
    if findings:
        raise SystemExit(f"sensitive data found: {findings}")
    return {"qwen": [(b["kind"], b["body_sha256"]) for b in qwen["batches"]],
            "rules": [(b["kind"], b["body_sha256"]) for b in rules["batches"]], "scores": score_set["items"],
            "operations": [o["id"] for o in ops]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    import subprocess
    git = lambda *a: subprocess.run(["git", *a], cwd=bridge.ROOT, capture_output=True, text=True, check=True).stdout  # noqa: E731
    if git("status", "--porcelain", "--", "multiagent", "observability"):
        raise SystemExit("uncommitted changes in multiagent/ or observability/: commit first (provenance)")
    print(json.dumps(build(args.out, source_commit=git("rev-parse", "HEAD").strip()), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
