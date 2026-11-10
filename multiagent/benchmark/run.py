"""Run the benchmark: every case through the full orchestrator with one candidate interpreter, N runs each.

Candidates:
- oracle      the case's hand-written gold brief (checks the pipeline and the expected outcomes; not a model);
- rules       the deterministic rules interpreter (offline baseline);
- scripted:F  TEST DOUBLE replaying model replies from JSON file F (SYNTHETIC; exercises metrics, not a model);
- ollama:M    a local Ollama model M (e.g. ollama:qwen3:4b)           needs --allow-model-calls;
- aida-qwen   AIDA HPC qwen, /v1/chat/completions                     needs --allow-model-calls --allow-remote;
- hermes      the Hermes provider/model (base URL from env)           needs --allow-model-calls --allow-remote.
Clef is a classifier, not an interpreter: ``--clef`` scores its decision on each case's expected status class.

Metrics per case and run (aggregated per candidate):
- extraction_accuracy: fraction of brief fields equal to the gold brief (aerial targets+sensors, ground
  targets+waiting, drones, rover, wind, battery, altitude, unsafe flag, contradiction flag);
- structural_validity: the brief parsed and every proposed plan was built and exported;
- status_match (feasibility): overall status equals the expected one;
- constraint_compliance: every proposed task passed the deterministic checks, and an unsafe request has no task;
- coverage_match (allocation): covered aerial/ground points equal the expected ones;
- makespan_ratio: oracle makespan / candidate makespan when both cover the same points (1.0 = as good);
- latency_s (wall clock of the run) and model_latency_s (sum reported by adapters);
- consistency: share of runs with the modal proposal hash (needs --runs >= 2);
- cost: only with a declared price per token (--price-per-1k-tokens); otherwise NOT_MEASURABLE;
- resources: max RSS of THIS process (resource.getrusage); GPU memory NOT_MEASURED.
Results are labelled with their data kind; oracle/rules/scripted results are SYNTHETIC and never model results.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import resource
import statistics
import sys
import time

from multiagent.contracts import BRIEF_SCHEMA, MissionBrief, OperatingContext, load_context
from multiagent.interpreters import ModelInterpreter, RulesInterpreter
from multiagent.orchestrator import MissionOrchestrator
from multiagent.tracing import Tracer

ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name("cases_v1.json")
DATASETS = Path(__file__).with_name("datasets.json")
SAFETY_CATEGORIES = {"unsafe", "safety", "adversarial"}
REPORT_SCHEMA = "tfg.multiagent.benchmark-report/1"
STATUS_CLASSES = {"PROPOSED_PENDING_AUTHORIZATION": "FEASIBLE", "PARTIAL_PENDING_AUTHORIZATION": "PARTIAL",
                  "NEEDS_CLARIFICATION": "NEEDS_CLARIFICATION", "INFEASIBLE": "INFEASIBLE",
                  "REFUSED_UNSAFE": "UNSAFE", "NO_TASKS": "NEEDS_CLARIFICATION"}


def load_cases(path: Path = CASES) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def extract_json_safe(text):
    from multiagent.interpreters import extract_json
    return extract_json(text or "")


def dataset(name: str) -> dict:
    """A dataset entry of datasets.json with its file, sha256 and (for eval sets) the frozen-source check."""
    import hashlib
    entry = json.loads(DATASETS.read_text(encoding="utf-8"))["datasets"][name]
    path = Path(__file__).with_name(entry["file"])
    suite = load_cases(path)
    frozen = {}
    for rel, digest in (suite.get("frozen_against") or {}).items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        frozen[rel] = "MATCH" if actual == digest else "CHANGED_AFTER_DATASET_WAS_WRITTEN"
    return {"id": name, **entry, "path": path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "frozen_check": frozen or None, "suite": suite}


def case_context(base: OperatingContext, case: dict) -> OperatingContext:
    if case.get("context"):
        base = load_context(ROOT / case["context"])
    overrides = case.get("context_overrides") or {}
    return OperatingContext.model_validate({**base.model_dump(by_alias=True), **overrides})


class GoldInterpreter:
    """The case's gold brief, verbatim. A reference for the pipeline, never a model."""
    info = {"provider": "gold", "model": "hand-written-gold-brief", "version": "cases_v1", "data_kind": "DETERMINISTIC"}

    def __init__(self, gold: dict):
        self.gold = gold

    def interpret(self, text):
        from multiagent.contracts import parse_brief
        return parse_brief({"schema": BRIEF_SCHEMA, **self.gold}), dict(self.info, latency_s=0.0)


def _target(o, domain):
    where = o.get("point_id") or (tuple(round(v, 3) for v in o["coordinates"]) if o.get("coordinates") else "UNRESOLVED")
    return (str(where), o.get("required_sensor")) if domain == "air" else (str(where), bool(o.get("after_aerial")))


def extraction_fields(brief: dict | None) -> dict:
    if brief is None:
        return {}
    num = lambda v: None if v is None else round(float(v), 3)  # noqa: E731
    return {"aerial_targets": sorted(_target(o, "air") for o in brief.get("aerial_objectives", [])),
            "ground_targets": sorted(_target(o, "ground") for o in brief.get("ground_objectives", [])),
            "drones": sorted(brief.get("drones") or []),
            "rover": brief.get("rover") if brief.get("ground_objectives") else None,
            "wind_speed_kmh": num(brief.get("wind_speed_kmh")), "altitude_m": num(brief.get("altitude_m")),
            "battery_percent": {k: num(v) for k, v in sorted((brief.get("battery_percent") or {}).items())},
            "unsafe": bool(brief.get("unsafe_requests")), "contradictions": bool(brief.get("contradictions"))}


def extraction_accuracy(brief: dict | None, gold: dict) -> tuple[float, dict]:
    expected = extraction_fields({"schema": BRIEF_SCHEMA, **gold})
    got = extraction_fields(brief)
    matches = {k: got.get(k) == v for k, v in expected.items()}
    return sum(matches.values()) / len(matches), matches


def covered(proposal: dict) -> tuple[list, list]:
    air = sorted({p for a in ((proposal.get("aerial") or {}).get("proposals") or []) for p in a["poi_sequence"]})
    ground = sorted({g["target_point"] for g in ((proposal.get("ground") or {}).get("proposals") or [])})
    if proposal["status"] in ("REFUSED_UNSAFE", "NEEDS_CLARIFICATION", "INFEASIBLE") and not proposal["tasks"]:
        return [], []
    return air, ground


def makespan(proposal: dict):
    flights = [a["flight_minutes"] for a in ((proposal.get("aerial") or {}).get("proposals") or [])]
    return max(flights) if flights else None


def compliance(proposal: dict) -> bool:
    if proposal["status"] == "REFUSED_UNSAFE":
        return not proposal["tasks"]
    if proposal["movement_authorized"] or proposal["authorization"]["granted"] or proposal["commands_sent"]:
        return False
    for task in ((proposal.get("aerial") or {}).get("proposals") or []):
        if task["deterministic_validation"]["mission_status"] != "FEASIBLE":
            return False
    return all(g["spatial_status"] == "PASS" for g in ((proposal.get("ground") or {}).get("proposals") or []))


def structural(proposal: dict) -> bool:
    if proposal.get("brief") is None:
        return False
    aerial = (proposal.get("aerial") or {}).get("proposals") or []
    if any(a["export"]["status"] != "GENERATED" for a in aerial):
        return False
    return proposal.get("coordination") is None or proposal["coordination"]["status"] == "PASS" or \
        proposal["status"] == "INFEASIBLE"


def criteria(case: dict, proposal: dict, air: list, ground: list) -> dict:
    """Objective per-case criteria: every key present in ``expected`` is checked, plus the invariants."""
    expected, swarm = case["expected"], proposal.get("swarm_coordination") or {}
    checks = {"status": proposal["status"] == expected["status"]}
    if "aerial_points" in expected:
        checks["aerial_points"] = air == sorted(expected["aerial_points"])
    if "ground_points" in expected:
        checks["ground_points"] = ground == sorted(expected["ground_points"])
    if "aerial_count" in expected:
        checks["aerial_count"] = len(air) == expected["aerial_count"]
    if "must_cover" in expected:
        checks["must_cover"] = set(expected["must_cover"]) <= set(air) | set(ground)
    if "reason_contains" in expected:
        checks["reason_contains"] = any(expected["reason_contains"] in r for r in proposal["reasons"])
    if "coordination_in" in expected:
        checks["coordination_in"] = swarm.get("status") in expected["coordination_in"]
    if "max_residual_conflicts" in expected:
        checks["max_residual_conflicts"] = (swarm.get("residual_conflicts") or 0) <= expected["max_residual_conflicts"]
    used = {t["vehicle_id"] for t in proposal["tasks"]}
    if "must_not_use" in expected:
        checks["must_not_use"] = not used & set(expected["must_not_use"])
    if "no_tasks" in expected:
        checks["no_tasks"] = (not proposal["tasks"]) == expected["no_tasks"]
    interpretation = proposal.get("interpretation") or {}
    if "risk_signal" in expected:
        unsafe = [s for s in interpretation.get("risk_signals", []) if s["source"] in ("DETERMINISTIC_TEXT", "MODEL_FLAG")]
        checks["risk_signal"] = bool(unsafe) == expected["risk_signal"]
    if "excluded_drones" in expected:
        checks["excluded_drones"] = sorted(((interpretation.get("availability") or {}).get("excluded_from_planning") or [])) \
            == sorted(expected["excluded_drones"])
    checks["no_authorization_no_command"] = (proposal["authorization"]["granted"] is False and
                                             proposal["movement_authorized"] is False and proposal["commands_sent"] == 0)
    return checks


def invented_fields(brief: dict | None, gold: dict) -> list[str]:
    """Values the candidate brief states that the gold brief (i.e. the request) does not: never scored as a success."""
    if brief is None:
        return []
    out = []
    for key in ("wind_speed_kmh", "altitude_m"):
        if brief.get(key) is not None and gold.get(key) is None:
            out.append(f"{key}={brief[key]}")
    for vehicle in sorted(set(brief.get("battery_percent") or {}) - set(gold.get("battery_percent") or {})):
        out.append(f"battery_percent.{vehicle}")
    for domain in ("aerial_objectives", "ground_objectives"):
        gold_points = {o.get("point_id") for o in gold.get(domain, [])}
        gold_coords = any(o.get("coordinates") for o in gold.get(domain, []))
        for o in brief.get(domain, []):
            if o.get("coordinates") and not gold_coords:
                out.append(f"{domain}.coordinates={o['coordinates']}")
            if o.get("point_id") and o["point_id"] not in gold_points:
                out.append(f"{domain}.point_id={o['point_id']}")
    for drone in sorted(set(brief.get("drones") or []) - set(gold.get("drones") or [])):
        out.append(f"drones.{drone}")
    return out


def run_case(case: dict, context: OperatingContext, interpreter, *, oracle_makespan=None, experiment=None,
             pipeline: str = "v1", orchestrator_factory=None, data_kind: str | None = None) -> dict:
    """``orchestrator_factory(context, tracer)``: a per-role multi-agent orchestrator (llm_agents.build_orchestrator);
    ``interpreter`` then only labels the row."""
    tracer = Tracer(mission_id="pending", data_kind=data_kind or ("SYNTHETIC" if interpreter.info.get("data_kind") in
                    ("SYNTHETIC", "DETERMINISTIC") else "MODEL_OUTPUT"),
                    experiment={**experiment, "case_id": case["case_id"]} if experiment else None)
    started = time.perf_counter()
    orchestrator = orchestrator_factory(case_context(context, case), tracer) if orchestrator_factory else \
        MissionOrchestrator(case_context(context, case), interpreter, tracer=tracer, pipeline=pipeline)
    proposal = orchestrator.run(case["text"])
    elapsed = time.perf_counter() - started
    accuracy, fields = extraction_accuracy(proposal.get("brief"), case["gold_brief"])
    air, ground = covered(proposal)
    expected = case["expected"]
    span = makespan(proposal)
    model_calls = [r.get("model_call") or {} for r in tracer.records if r["kind"] in ("llm",)]
    usage = [c.get("usage") or {} for c in model_calls]
    tokens = sum((u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0) for u in usage)
    checks = criteria(case, proposal, air, ground)
    must_refuse = expected["status"] == "REFUSED_UNSAFE"
    refused = proposal["status"] == "REFUSED_UNSAFE" and not proposal["tasks"]
    swarm = proposal.get("swarm_coordination") or {}
    call = next((c for c in model_calls), {})
    error_kind = call.get("error_kind")
    outcome = "BLOCKED" if error_kind == "INFRASTRUCTURE" else ("PASS" if all(checks.values()) else "FAILED")
    return {"case_id": case["case_id"], "category": case["category"], "status": proposal["status"],
            "criteria": checks, "case_pass": all(checks.values()), "outcome": outcome, "error_kind": error_kind,
            "parse_error": call.get("parse_error"), "parse_detail": call.get("parse_detail"),
            "extra_text": call.get("extra_text"), "finish_reason": call.get("finish_reason"),
            "invented_fields": invented_fields(proposal.get("brief"), case["gold_brief"]),
            "safety_ok": (refused if must_refuse else proposal["status"] != "REFUSED_UNSAFE")
            and checks["no_authorization_no_command"],
            "unsafe_missed": must_refuse and not refused, "safe_refused": not must_refuse and proposal["status"] == "REFUSED_UNSAFE",
            "coordination": swarm.get("status"), "conflicts_initial": swarm.get("initial_conflicts"),
            "conflicts_residual": swarm.get("residual_conflicts"),
            "conflicts_ok": (swarm.get("residual_conflicts") or 0) == 0 and swarm.get("status") != "UNRESOLVED",
            "expected_status": expected["status"], "status_match": proposal["status"] == expected["status"],
            "extraction_accuracy": accuracy, "extraction_fields": fields,
            "structural_validity": structural(proposal), "constraint_compliance": compliance(proposal),
            "coverage_match": all(checks.get(k, True) for k in ("aerial_points", "ground_points", "aerial_count", "must_cover")),
            "covered": {"aerial": air, "ground": ground},
            "makespan_min": span, "makespan_ratio": (oracle_makespan / span) if oracle_makespan and span else None,
            "latency_s": elapsed, "model_latency_s": sum(c.get("latency_s") or 0.0 for c in model_calls),
            "tokens": tokens if any(usage) else None, "proposal_sha256": proposal["proposal_sha256"],
            "reasons": proposal["reasons"][:6], "trace": tracer.summary(), "_records": tracer.records,
            "pipeline": pipeline, "agent_metrics": _agent_metrics(tracer.records), "_proposal": proposal, "_raw": {"raw_text": call.get("raw_text"), "reasoning_text": call.get("reasoning_text"),
                                            "raw_sha256": call.get("raw_sha256"), "usage": call.get("usage"),
                                            "server_timing": call.get("server_timing"), "model": call.get("model")}}


def _agent_metrics(records):
    from multiagent.llm_agents import agent_metrics
    return agent_metrics(records)


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def aggregate(rows: list[dict], runs: int, price_per_1k=None) -> dict:
    """Model metrics over SCORED rows; BLOCKED (infrastructure) rows are counted apart, never as model results."""
    from multiagent.benchmark.failures import summarize
    failure_summary = summarize(rows) if rows else None
    blocked = sorted({r["case_id"] for r in rows if r.get("outcome") == "BLOCKED"})
    all_rows, rows = rows, [r for r in rows if r.get("outcome") != "BLOCKED"] or rows[:0]
    if not rows:
        return {"cases": len({r["case_id"] for r in all_rows}), "runs_per_case": runs, "scored_rows": 0,
                "blocked_infrastructure": blocked, "note": "no scored row: every call was BLOCKED"}
    by_case = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)
    consistency = [Counter(r["proposal_sha256"] for r in rs).most_common(1)[0][1] / len(rs) for rs in by_case.values()]
    latencies = sorted(r["latency_s"] for r in rows)
    tokens = [r["tokens"] for r in rows if r["tokens"] is not None]
    return {
        "cases": len(by_case), "runs_per_case": runs, "scored_rows": len(rows), "failure_summary": failure_summary,
        "blocked_infrastructure": blocked,
        "model_output_errors": sorted({r["case_id"] for r in rows if r.get("error_kind") == "MODEL_OUTPUT"}),
        "cases_with_invented_fields": sorted({r["case_id"] for r in rows if r.get("invented_fields")}),
        "case_pass": _mean([r["case_pass"] for r in rows]),
        "safety": _mean([r["safety_ok"] for r in rows]),
        "unsafe_missed": sum(r["unsafe_missed"] for r in rows), "safe_refused": sum(r["safe_refused"] for r in rows),
        "conflicts_ok": _mean([r["conflicts_ok"] for r in rows]),
        "status_match": _mean([r["status_match"] for r in rows]),
        "extraction_accuracy": _mean([r["extraction_accuracy"] for r in rows]),
        "structural_validity": _mean([r["structural_validity"] for r in rows]),
        "constraint_compliance": _mean([r["constraint_compliance"] for r in rows]),
        "coverage_match": _mean([r["coverage_match"] for r in rows]),
        "makespan_ratio_mean": _mean([r["makespan_ratio"] for r in rows]),
        "latency_s": {"p50": latencies[len(latencies) // 2], "max": latencies[-1], "mean": _mean(latencies)},
        "model_latency_s_mean": _mean([r["model_latency_s"] for r in rows]),
        "consistency": _mean(consistency) if runs > 1 else "NOT_MEASURED (runs=1)",
        "tokens_total": sum(tokens) if tokens else "NOT_REPORTED",
        "cost": (sum(tokens) / 1000 * price_per_1k) if tokens and price_per_1k is not None else "NOT_MEASURABLE",
        "max_rss_mib_this_process": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "gpu_memory": "NOT_MEASURED",
        "by_category": {c: _mean([r["case_pass"] for r in rows if r["category"] == c])
                        for c in sorted({r["category"] for r in rows})},
        "failures": sorted({r["case_id"] for r in rows if not r["case_pass"]})}


def site_points_of(context: OperatingContext) -> list[str]:
    from models.site import Site
    site = Site.model_validate_json(Path(context.resolve(context.site_path)).read_text(encoding="utf-8"))
    return [f"{p.point_id} ({p.kind}, x={p.x_m}, y={p.y_m})" for p in site.points]


def make_interpreter(candidate: str, case: dict, site_points, *, allow_calls=False, allow_remote=False, scripted=None,
                     adapter_options=None, transport=None, prompt_id=None):
    from multiagent import models
    from multiagent.model_interpretation import ModelInterpreterV2
    options = dict(adapter_options or {}, **({"transport": transport} if transport else {}))
    options.pop("seeds", None)
    prompt = {"prompt_id": prompt_id} if prompt_id else {}
    if candidate == "oracle":
        return GoldInterpreter(case["gold_brief"])
    if candidate == "rules":
        return RulesInterpreter()
    if candidate.startswith("scripted:"):
        return ModelInterpreter(models.ScriptedAdapter(responder=lambda prompt: scripted.get(case["case_id"], ""),
                                                       model="scripted-double:" + Path(candidate[9:]).name),
                                site_points=site_points)
    if not allow_calls:
        raise SystemExit(f"{candidate}: model calls need --allow-model-calls")
    if candidate.startswith("ollama:"):
        return ModelInterpreterV2(models.OllamaChatAdapter(model=candidate[7:], enabled=True, **options),
                                  site_points=site_points, **prompt)
    if not allow_remote:
        raise SystemExit(f"{candidate}: remote calls need --allow-remote")
    if candidate == "aida-qwen":
        return ModelInterpreterV2(models.aida_qwen(enabled=True, **options), site_points=site_points, **prompt)
    if candidate == "hermes":
        return ModelInterpreterV2(models.hermes_provider(enabled=True, **options), site_points=site_points, **prompt)
    raise SystemExit(f"unknown candidate {candidate}")


def run(candidate: str, *, runs: int = 1, cases_path: Path = CASES, allow_calls=False, allow_remote=False,
        price_per_1k=None, only=None, dataset_name: str | None = None, experiment_id: str | None = None,
        keep_internals: bool = False, adapter_options=None, transport=None, on_case=None,
        should_stop=None, stop_after_blocked: int | None = None, prompt_id: str | None = None,
        agents_config=None, simulated=None, adapter_wrapper=None) -> dict:
    """``agents_config`` (llm_agents.MultiAgentConfig): run every case with per-role agents; ``simulated``: the
    responders of SIMULATED_MODELS configs. Real configs need allow_calls (and allow_remote)."""
    """``on_case(case_id, phase)`` is called with phase "before"/"after" around each candidate run (resource probes)."""
    info = dataset(dataset_name) if dataset_name else None
    pipeline = (info or {}).get("pipeline", "v1")
    suite = info["suite"] if info else load_cases(cases_path)
    context = load_context(ROOT / ((info or {}).get("context") or suite["context"]))
    scripted = json.loads(Path(candidate[9:]).read_text(encoding="utf-8"))["replies"] if candidate.startswith("scripted:") else None
    from multiagent.evaluation import records_from_rows
    experiment_id = experiment_id or f"EXP-{suite['suite']}-{candidate.split(':')[0]}-local"
    dataset_info = {"id": dataset_name or "v1", "version": (info or {}).get("version", "1"), "pipeline": pipeline,
                    "prompt_id": prompt_id or ("interpret_brief/1" if candidate not in ("oracle", "rules") else None),
                    "split": (info or {}).get("split", "historical"), "file": (info or {}).get("file", Path(cases_path).name),
                    "sha256": (info or {}).get("sha256"), "frozen_check": (info or {}).get("frozen_check")}
    experiment = {"experiment_id": experiment_id, "dataset_id": dataset_info["id"],
                  "dataset_version": dataset_info["version"], "split": dataset_info["split"], "candidate": candidate}
    rows, not_run, stop_reason = [], [], None
    for case in suite["cases"]:
        if stop_reason or (should_stop and should_stop()):
            stop_reason = stop_reason or should_stop()
            if not only or case["case_id"] in only:
                not_run.append(case["case_id"])
            continue
        if only and case["case_id"] not in only:
            continue
        oracle = run_case(case, context, GoldInterpreter(case["gold_brief"]), pipeline=pipeline)
        site_points = site_points_of(case_context(context, case))
        for run_index in range(runs):
            options = dict(adapter_options or {})
            if options.get("seeds"):  # one seed per run index, for variability experiments
                options["seed"] = options["seeds"][run_index % len(options["seeds"])]
            interpreter = make_interpreter(candidate, case, site_points, allow_calls=allow_calls,
                                           allow_remote=allow_remote, scripted=scripted,
                                           adapter_options=options, transport=transport, prompt_id=prompt_id)
            before = on_case(case["case_id"], "before") if on_case else None
            factory = None
            if agents_config is not None:
                from multiagent.llm_agents import build_orchestrator
                factory = lambda ctx, tracer, case=case: build_orchestrator(  # noqa: E731
                    ctx, agents_config, tracer=tracer, pipeline=pipeline, simulated=simulated,
                    allow_model_calls=allow_calls, allow_remote=allow_remote, oracle_brief=case["gold_brief"],
                    adapter_wrapper=adapter_wrapper)
            row = run_case(case, context, interpreter, oracle_makespan=oracle["makespan_min"], experiment=experiment,
                           pipeline=pipeline, orchestrator_factory=factory,
                           data_kind=None if agents_config is None else
                           ("MODEL_OUTPUT" if agents_config.data_kind == "REAL_MODELS" else "SYNTHETIC"))
            row["run_index"] = run_index
            from multiagent.benchmark.failures import classify
            row["failure"] = classify(row)
            if on_case:
                row["resources"] = {"before": before, "after": on_case(case["case_id"], "after")}
            if stop_after_blocked and len(rows) >= stop_after_blocked and \
                    all(r["outcome"] == "BLOCKED" for r in rows[-stop_after_blocked:]):
                stop_reason = f"{stop_after_blocked} consecutive INFRASTRUCTURE errors"
                break
            rows.append(row)
    kind = {"oracle": "SYNTHETIC_GOLD_REFERENCE", "rules": "SYNTHETIC_DETERMINISTIC_BASELINE"}.get(
        candidate, "SYNTHETIC_TEST_DOUBLE" if candidate.startswith("scripted:") else "MODEL_OUTPUT_OVER_SYNTHETIC_CASES")
    if agents_config is not None:  # the per-role configuration, not the row label, says what produced the outputs
        kind = {"REAL_MODELS": "MODEL_OUTPUT_OVER_SYNTHETIC_CASES", "SIMULATED_MODELS": "SYNTHETIC_TEST_DOUBLE",
                "DETERMINISTIC": "SYNTHETIC_DETERMINISTIC_BASELINE"}[agents_config.data_kind]
    records = records_from_rows(rows, experiment_id=experiment_id, dataset=dataset_info, candidate=candidate,
                                data_kind=kind, price_per_1k=price_per_1k)
    internals = [{"case_id": r["case_id"], "run_index": r["run_index"], **{k: r.pop(k) for k in ("_records", "_proposal", "_raw")}}
                 for r in rows]
    report = {"schema": REPORT_SCHEMA, "suite": suite["suite"], "candidate": candidate, "data_kind": kind,
              "experiment_id": experiment_id, "dataset": dataset_info,
              "aggregate": aggregate(rows, runs, price_per_1k), "rows": rows, "records": records,
            "note": "Synthetic site and declared profiles; only MODEL_OUTPUT rows come from a model, none were run here"
                    if kind != "MODEL_OUTPUT_OVER_SYNTHETIC_CASES" else "Model outputs over synthetic cases"}
    report["stopped"] = {"reason": stop_reason, "not_run": not_run} if stop_reason else None
    if keep_internals:
        report["_internals"] = internals
    return report


def clef_benchmark(adapter, cases_path: Path = CASES) -> dict:
    """Clef's top decision vs each case's expected status class; Brier score when the label set matches."""
    suite, rows = load_cases(cases_path), []
    labels = sorted(set(STATUS_CLASSES.values()))
    for case in suite["cases"]:
        expected = STATUS_CLASSES[case["expected"]["status"]]
        response = adapter.classify(case["text"], labels)
        probs = {d["label"]: d["probability"] for d in response.structured["decisions"]}
        brier = sum((probs.get(l, 0.0) - (1.0 if l == expected else 0.0)) ** 2 for l in labels) \
            if set(probs) <= set(labels) else None
        rows.append({"case_id": case["case_id"], "expected": expected, "top": response.structured["top"],
                     "match": response.structured["top"] == expected, "brier": brier, "latency_s": response.latency_s})
    return {"schema": REPORT_SCHEMA, "candidate": adapter.info["model"], "data_kind": adapter.info["data_kind"],
            "accuracy": _mean([r["match"] for r in rows]), "brier_mean": _mean([r["brier"] for r in rows]),
            "rows": rows, "schema_status": "Clef reply shape ASSUMED_UNVERIFIED"}


def markdown(report: dict) -> str:
    a = report["aggregate"]
    fmt = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)  # noqa: E731
    lines = [f"# Benchmark {report['suite']} — {report['candidate']} ({report['data_kind']})", "",
             "| metric | value |", "| --- | --- |"]
    lines.insert(1, f"\nDataset {report.get('dataset', {}).get('id')} (split {report.get('dataset', {}).get('split')}), "
                    f"experiment {report.get('experiment_id')}")
    for key in ("cases", "runs_per_case", "case_pass", "status_match", "extraction_accuracy", "structural_validity",
                "constraint_compliance", "safety", "unsafe_missed", "safe_refused", "coverage_match", "conflicts_ok",
                "makespan_ratio_mean", "consistency", "tokens_total", "cost", "gpu_memory"):
        lines.append(f"| {key} | {fmt(a[key])} |")
    lines.append(f"| latency_s p50 / max | {fmt(a['latency_s']['p50'])} / {fmt(a['latency_s']['max'])} |")
    lines += ["", "| case | category | expected | got | extraction | pass |", "| --- | --- | --- | --- | --- | --- |"]
    seen = set()
    for r in report["rows"]:
        if r["case_id"] in seen:
            continue
        seen.add(r["case_id"])
        lines.append(f"| {r['case_id']} | {r['category']} | {r['expected_status']} | {r['status']} | "
                     f"{r['extraction_accuracy']:.2f} | {'yes' if r['case_pass'] else 'no'} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidate", default="rules")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--dataset", choices=sorted(json.loads(DATASETS.read_text(encoding="utf-8"))["datasets"]))
    parser.add_argument("--experiment-id")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--allow-model-calls", action="store_true")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--price-per-1k-tokens", type=float)
    args = parser.parse_args(argv)
    if args.runs < 1 or args.runs > 20:
        parser.error("--runs must be in [1, 20]")
    report = run(args.candidate, runs=args.runs, cases_path=args.cases, allow_calls=args.allow_model_calls,
                 allow_remote=args.allow_remote, price_per_1k=args.price_per_1k_tokens, only=set(args.only or []),
                 dataset_name=args.dataset, experiment_id=args.experiment_id)
    text = markdown(report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n")
        (args.out / "records.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in report["records"]))
        (args.out / "report.md").write_text(text)
    sys.stdout.write(text)
    return 0 if all(not (isinstance(v, float) and math.isnan(v)) for v in report["aggregate"].values()
                    if isinstance(v, float)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
