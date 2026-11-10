"""Dashboard "TFG — Multiagent & LLM Evaluation": widget specification and Opik dashboard configs (offline).

Opik facts (multiagent.opik_contract, pinned commit df61dd21c66e): a dashboard is POST /v1/private/dashboards
with type multi_project or experiments and config = DashboardState v4 (sections -> widgets + layout on a
6-column grid). Widget types: project_metrics, project_stats_card, text_markdown (project data) and
experiments_feedback_scores, experiment_leaderboard (experiment data); ollie_chart needs a saved query only
Opik's assistant can create, so it is never generated here. Hence two dashboards:
- "TFG — Multiagent & LLM Evaluation" (multi_project, project tfg-multiagent-benchmarks): sections A-E and G;
- "TFG — Multiagent & LLM Evaluation · Experiments" (experiments): section F.
Every widget has a full specification; widgets Opik cannot draw (scatter plots, per-case tables, coverage
tables) are marked LOCAL_PREVIEW and produced offline by multiagent.opik_phase2.local_preview from the sealed
evidence. Filter/breakdown field names come from the frontend types and are UNVERIFIED against the service until
the dashboard is opened once in the UI.
"""
from __future__ import annotations

import hashlib

from multiagent import opik_contract as contract
from multiagent.opik_bridge import PROJECT

# project id read back from Opik on 04/11/2026 (GET projects/{id} -> tfg-multiagent-benchmarks); a multi_project
# widget without projectId/projectIds counts as "not configured" in the frontend
PROJECT_ID = "01a1a77c-fb97-72f1-b2d7-376183ac994b"
NAME = "TFG — Multiagent & LLM Evaluation"
NAME_EXPERIMENTS = "TFG — Multiagent & LLM Evaluation · Experiments"
LAST_MODIFIED = 1793750400000  # fixed (2026-11-04T00:00:00Z) so the config is reproducible byte for byte


def _fid(*parts):
    return "f-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]


def tag(value, op="contains"):
    return {"id": _fid("tag", value, op), "field": "tags", "type": "list", "operator": op, "value": value}


def span_type(value):
    return {"id": _fid("type", value), "field": "type", "type": "category", "operator": "=", "value": value}


def span_name(fragment):
    return {"id": _fid("name", fragment), "field": "name", "type": "string", "operator": "contains", "value": fragment}


def score_present(name):
    return {"id": _fid("score", name), "field": "feedback_scores", "type": "feedback_scores_number",
            "operator": "is_not_empty", "key": name, "value": ""}


PROJECT_TAG = tag("tfg-multiagent")


def W(section, wid, title, wtype, config, *, metric, source, filters, grouping, unit, visualization, sufficiency,
      limitations, ui=True, automation="API_CONFIG"):
    text = wtype == "text_markdown"  # every field is stated explicitly; "not applicable" is said, never left blank
    return {"section": section, "id": wid, "title": title, "type": wtype, "config": config,
            "metric": metric or ("none (explanatory text)" if text else "see title"), "source": source,
            "filters": filters, "grouping": grouping or "none (single value over the filtered set)",
            "unit": unit or ("not applicable (text)" if text else "not applicable (table of mixed values)"),
            "visualization": visualization,
            "sufficiency": sufficiency, "limitations": limitations, "ui_supported": ui, "automation": automation}


def stats(source, metric, filters=None, span_filters=None):
    c = {"source": source, "metric": metric, "traceFilters": [PROJECT_TAG, *(filters or [])]}
    if span_filters is not None:
        c = {"source": source, "metric": metric, "spanFilters": span_filters}
    return c


def chart(metric_type, chart_type="line", *, trace_filters=None, span_filters=None, breakdown=None, **extra):
    c = {"metricType": metric_type, "chartType": chart_type}
    if trace_filters is not None:
        c["traceFilters"] = trace_filters
    if span_filters is not None:
        c["spanFilters"] = span_filters
    if breakdown:
        c["breakdown"] = breakdown
    c.update(extra)
    return c


BY_KIND = {"field": "metadata", "metadataKey": "tfg_data_kind"}
BY_EXPERIMENT = {"field": "metadata", "metadataKey": "tfg_experiment_id"}
N1 = "with 1 trace P50 = P99: no variability can be read; meaningful from ~10 traces per group"
LOCAL = "LOCAL_PREVIEW"


def widgets() -> list[dict]:
    S = "traces"
    w = []
    # ------------------------------------------------------------------ A. overview
    w += [
        W("A", "a-missions", "Missions (traces)", "project_stats_card", stats(S, "trace_count"), metric="trace count",
          source="traces tagged tfg-multiagent", filters=["tags contains tfg-multiagent"], grouping=None, unit="traces",
          visualization="stat card", sufficiency=">= 1 trace", limitations="counts imports and new runs alike"),
        W("A", "a-real-llm", "Runs with a real LLM", "project_stats_card", stats(S, "trace_count", [tag("real-llm-call")]),
          metric="trace count", source="traces", filters=["tags contains real-llm-call"], grouping=None, unit="traces",
          visualization="stat card", sufficiency=">= 1", limitations="test-double runs carry test-double-llm instead"),
        W("A", "a-deterministic", "Deterministic runs", "project_stats_card",
          stats(S, "trace_count", [tag("DETERMINISTIC_BASELINE")]), metric="trace count", source="traces",
          filters=["tags contains DETERMINISTIC_BASELINE"], grouping=None, unit="traces", visualization="stat card",
          sufficiency=">= 1", limitations="only after the rules baseline is imported"),
        W("A", "a-synthetic", "Simulated (test-double) runs", "project_stats_card",
          stats(S, "trace_count", [tag("test-double-llm")]), metric="trace count", source="traces",
          filters=["tags contains test-double-llm"], grouping=None, unit="traces", visualization="stat card",
          sufficiency="0 expected today", limitations="simulated runs are never uploaded without authorization"),
        W("A", "a-llm-calls", "Real LLM calls", "project_stats_card", stats("spans", "span_count",
          span_filters=[span_type("llm")]), metric="span count (type llm)", source="spans", filters=["type = llm"],
          grouping=None, unit="calls", visualization="stat card", sufficiency=">= 1",
          limitations="only real calls are llm spans; test doubles are general spans"),
        W("A", "a-tool-calls", "Tool calls", "project_stats_card", stats("spans", "span_count",
          span_filters=[span_type("tool")]), metric="span count (type tool)", source="spans", filters=["type = tool"],
          grouping=None, unit="calls", visualization="stat card", sufficiency=">= 1",
          limitations="historical rules interpreter steps are tool spans; LLM-agent tools appear with live runs"),
        W("A", "a-pass", "Cases passed (mean case_pass)", "project_stats_card", stats(S, "feedback_scores.case_pass"),
          metric="case_pass", source="trace feedback scores", filters=["tags contains tfg-multiagent"], grouping=None,
          unit="fraction", visualization="stat card", sufficiency="scores uploaded",
          limitations="needs the score upload; a mean over different datasets mixes difficulties"),
        W("A", "a-blocked-ok", "Unsafe requests refused (mean)", "project_stats_card",
          stats(S, "feedback_scores.unsafe_request_detected"), metric="unsafe_request_detected",
          source="trace feedback scores (only refusal cases carry it)", filters=["score present"], grouping=None,
          unit="fraction", visualization="stat card", sufficiency=">= 5 refusal cases",
          limitations="a refusal is not proof of correct interpretation (see section D)"),
        W("A", "a-errors", "Errors", "project_stats_card", stats(S, "error_count"), metric="error_count",
          source="traces", filters=["tags contains tfg-multiagent"], grouping=None, unit="traces",
          visualization="stat card", sufficiency=">= 1", limitations="infrastructure errors only; failed cases are not errors"),
        W("A", "a-p50", "Mission latency P50", "project_stats_card", stats(S, "duration.p50"), metric="mission_latency_s",
          source="trace duration (recorded)", filters=["tags contains tfg-multiagent"], grouping=None, unit="s",
          visualization="stat card", sufficiency=N1, limitations="historical imports keep their original times"),
        W("A", "a-legend", "How to read this dashboard", "text_markdown", {"content": LEGEND}, metric=None,
          source="static", filters=[], grouping=None, unit=None, visualization="markdown", sufficiency="always",
          limitations="none"),
    ]
    # ------------------------------------------------------------------ B. model performance
    w += [
        W("B", "b-llm-latency", "LLM latency P50/P90/P99 by model", "project_metrics",
          chart("SPAN_DURATION", span_filters=[span_type("llm")], breakdown={"field": "model"},
                durationMetrics=["p50", "p90", "p99"]), metric="llm_latency_s", source="llm spans (native model)",
          filters=["type = llm"], grouping="model", unit="s", visualization="line", sufficiency=N1,
          limitations="needs native model (E07 needs the prepared PATCH)"),
        W("B", "b-agent-latency", "Average latency by agent", "project_metrics",
          chart("SPAN_AVERAGE_DURATION", "bar", span_filters=[span_name(":agent:")], breakdown={"field": "name"}),
          metric="agent_latency_s", source="agent spans", filters=["name contains :agent:"], grouping="span name",
          unit="s", visualization="bar", sufficiency=">= 5 runs per agent",
          limitations="historical agents were deterministic (milliseconds)"),
        W("B", "b-tokens", "Tokens by model (input/output)", "project_metrics",
          chart("SPAN_TOKEN_USAGE", span_filters=[span_type("llm")], breakdown={"field": "model"},
                usageMetrics=["prompt_tokens", "completion_tokens"]), metric="input_tokens, output_tokens",
          source="llm span native usage", filters=["type = llm"], grouping="model", unit="tokens",
          visualization="line", sufficiency="native usage present",
          limitations="needs native usage; E07 only after the PATCH; never estimated"),
        W("B", "b-tokens-mission", "Tokens per mission (avg)", "project_stats_card", stats(S, "usage.total_tokens"),
          metric="total_tokens", source="trace usage (sum of spans)", filters=["tags contains tfg-multiagent"],
          grouping=None, unit="tokens", visualization="stat card", sufficiency="native usage present",
          limitations="deterministic traces have no tokens and are excluded, not counted as 0"),
        W("B", "b-time-by-type", "Time in LLM vs validators vs agents", "project_metrics",
          chart("SPAN_DURATION", "bar", span_filters=[], breakdown={"field": "type"}, durationMetrics=["p50"]),
          metric="span duration by type", source="spans", filters=[], grouping="span type", unit="s",
          visualization="bar", sufficiency=">= 5 traces", limitations="validations are general spans like agent steps"),
        W("B", "b-calls-model", "LLM calls by model", "project_metrics",
          chart("SPAN_COUNT", "bar", span_filters=[span_type("llm")], breakdown={"field": "model"}), metric="llm_calls",
          source="llm spans", filters=["type = llm"], grouping="model", unit="calls", visualization="bar",
          sufficiency=">= 1", limitations="needs native model"),
        W("B", "b-gpu", "GPU memory around calls", None, None, metric="gpu_memory_mib",
          source="pilot resource probes (metadata only)", filters=[], grouping="run", unit="MiB",
          visualization="table", sufficiency="probes recorded", limitations="whole-GPU reading, not per process",
          ui=False, automation=LOCAL),
        W("B", "b-cost", "Estimated cost", "project_metrics", chart("COST", trace_filters=[PROJECT_TAG]),
          metric="estimated_cost", source="native total_estimated_cost", filters=["tags contains tfg-multiagent"],
          grouping=None, unit="USD", visualization="line", sufficiency="a remote model with a price",
          limitations="local runs have no cost: an empty chart is correct, not 0"),
        W("B", "b-volume", "Runs per day by data kind", "project_metrics",
          chart("TRACE_COUNT", "bar", trace_filters=[PROJECT_TAG], breakdown=BY_KIND), metric="trace count",
          source="traces", filters=["tags contains tfg-multiagent"], grouping="metadata tfg_data_kind", unit="traces",
          visualization="bar", sufficiency=">= 2 days of runs", limitations="historical imports keep their original dates"),
    ]
    # ------------------------------------------------------------------ C. interpretation and planning quality
    for wid, score, title, lim in [
            ("c-pass-exp", "case_pass", "Case pass by experiment", "compare only experiments over the same dataset"),
            ("c-extraction", "extraction_accuracy", "Extraction accuracy by experiment",
             "absent when the reply was rejected (not 0)"),
            ("c-schema", "schema_valid", "Valid model replies (schema_valid)", "LLM runs only"),
            ("c-clarify", "clarification_correct", "Clarifications asked when expected", "only where applicable"),
            ("c-constraints", "constraints_satisfied", "Constraints satisfied", "only cases with tasks"),
            ("c-status", "expected_status_match", "Feasible/infeasible correctly identified", "per decision class"),
            ("c-assignment", "assignment_quality", "Allocation quality vs reference", "only cases with aerial plans"),
            ("c-plan", "plan_valid", "Valid individual plans (.plan built)", "only cases with aerial plans")]:
        w.append(W("C", wid, title, "project_metrics",
                   chart("FEEDBACK_SCORES", trace_filters=[PROJECT_TAG, score_present(score)], breakdown=BY_EXPERIMENT,
                         feedbackScores=[score]), metric=score, source="trace feedback scores",
                   filters=["tags contains tfg-multiagent", f"score {score} present"],
                   grouping="metadata tfg_experiment_id", unit="mean", visualization="line",
                   sufficiency=">= 10 cases per experiment", limitations=lim))
    w.append(W("C", "c-failure-origin", "Failures by origin (interpreter / planner / infrastructure)", None, None,
               metric="failure taxonomy", source="analysis_v2 failures + benchmark rows", filters=[],
               grouping="primary label", unit="cases", visualization="stacked table", sufficiency=">= 1 failure",
               limitations="not a native Opik field", ui=False, automation=LOCAL))
    # ------------------------------------------------------------------ D. safety
    for wid, score, title, lim in [
            ("d-detected", "unsafe_request_detected", "Unsafe requests detected", "refusal cases only"),
            ("d-false-refusals", "safe_refused", "False refusals of safe requests", "non-refusal cases only"),
            ("d-authority", "authorization_not_granted", "Authority never granted", "must stay 1"),
            ("d-excluded", "prohibited_vehicle_excluded", "Forbidden vehicles kept out", "v3 availability cases"),
            ("d-geofence", "geofence_respected", "Routes inside perimeter and clear of exclusions", "planning check"),
            ("d-safety", "safety_ok", "Safety outcome", "a block is not a correct interpretation")]:
        w.append(W("D", wid, title, "project_metrics",
                   chart("FEEDBACK_SCORES", "bar", trace_filters=[PROJECT_TAG, score_present(score)],
                         breakdown=BY_EXPERIMENT, feedbackScores=[score]), metric=score, source="trace feedback scores",
                   filters=[f"score {score} present"], grouping="metadata tfg_experiment_id", unit="mean",
                   visualization="bar", sufficiency=">= 5 applicable cases", limitations=lim))
    w += [W("D", "d-missed", "Unsafe requests missed", None, None, metric="unsafe_request_missed (derived)",
            source="1 - unsafe_request_detected", filters=[], grouping="experiment", unit="cases", visualization="table",
            sufficiency="refusal cases", limitations="a miss is not an execution: nothing was authorized", ui=False,
            automation=LOCAL),
          W("D", "d-constraints-kind", "Rejections by constraint (battery, wind, geofence, availability, self-authorization)",
            None, None, metric="reasons", source="sealed rows (reasons) + v3 criteria", filters=[], grouping="constraint",
            unit="cases", visualization="table", sufficiency=">= 1", limitations="parsed from recorded reasons", ui=False,
            automation=LOCAL),
          W("D", "d-gates", "Proposals discarded by validation (gates)", "project_metrics",
            chart("SPAN_COUNT", "bar", span_filters=[span_name("gate:")], breakdown={"field": "name"}),
            metric="gate spans", source="validation spans named gate:*", filters=["name contains gate:"],
            grouping="span name", unit="spans", visualization="bar", sufficiency="LLM-agent runs",
            limitations="status ACCEPTED/REJECTED is in metadata; historical pilot has no gates")]
    # ------------------------------------------------------------------ E. multi-agent coordination
    for wid, title, filt, metric_type, lim in [
            ("e-agent-spans", "Agent steps by agent", ":agent:", "SPAN_COUNT", "planned tasks, not vehicle executions"),
            ("e-validations", "Validations by agent", ":validation:", "SPAN_COUNT", "includes deconfliction attempts"),
            ("e-revisions", "Revision requests", "revision_request", "SPAN_COUNT", "LLM-agent runs only"),
            ("e-errors", "Error rate by agent", ":", "SPAN_ERROR_RATE", "infrastructure and tool errors")]:
        w.append(W("E", wid, title, "project_metrics", chart(metric_type, "bar", span_filters=[span_name(filt)],
                   breakdown={"field": "name"}), metric=metric_type.lower(), source="spans",
                   filters=[f"name contains {filt}"], grouping="span name", unit="spans", visualization="bar",
                   sufficiency=">= 1 run", limitations=lim))
    w.append(W("E", "e-llm-by-agent", "LLM calls by agent", "project_metrics",
               chart("SPAN_COUNT", "bar", span_filters=[span_type("llm")], breakdown={"field": "name"}),
               metric="llm_calls", source="llm spans", filters=["type = llm"], grouping="span name (agent:llm:step)",
               unit="calls", visualization="bar", sufficiency=">= 1", limitations="real calls only"))
    w.append(W("E", "e-tools-by-agent", "Tool calls by agent", "project_metrics",
               chart("SPAN_COUNT", "bar", span_filters=[span_type("tool")], breakdown={"field": "name"}),
               metric="tool_calls", source="tool spans", filters=["type = tool"], grouping="span name", unit="calls",
               visualization="bar", sufficiency=">= 1", limitations="agent tools appear only with LLM-agent runs"))
    for wid, score, title in [("e-conflicts", "conflicts_detected", "Spatio-temporal conflicts detected"),
                              ("e-resolved", "conflicts_resolved", "Conflicts resolved"),
                              ("e-replan", "replanning_required", "Replanning required"),
                              ("e-replan-ok", "replanning_success", "Replanning success"),
                              ("e-fallback", "fallback_used", "Deterministic fallback used"),
                              ("e-dependency", "dependency_valid", "Drone-rover dependencies valid")]:
        w.append(W("E", wid, title, "project_metrics",
                   chart("FEEDBACK_SCORES", "bar", trace_filters=[PROJECT_TAG, score_present(score)],
                         breakdown=BY_EXPERIMENT, feedbackScores=[score]), metric=score, source="trace feedback scores",
                   filters=[f"score {score} present"], grouping="metadata tfg_experiment_id", unit="mean / count",
                   visualization="bar", sufficiency=">= 5 applicable cases",
                   limitations="planning-time coordination; no vehicle moved"))
    w.append(W("E", "e-note", "Planning, not execution", "text_markdown", {"content": NOT_EXECUTION}, metric=None,
               source="static", filters=[], grouping=None, unit=None, visualization="markdown", sufficiency="always",
               limitations="none"))
    # ------------------------------------------------------------------ G. provenance and reproducibility
    w += [W("G", "g-kinds", "Real vs deterministic vs simulated", "project_metrics",
            chart("TRACE_COUNT", "bar", trace_filters=[PROJECT_TAG], breakdown=BY_KIND), metric="trace count",
            source="traces", filters=["tags contains tfg-multiagent"], grouping="metadata tfg_data_kind", unit="traces",
            visualization="bar", sufficiency=">= 1", limitations="kind is the recorded provenance label"),
          W("G", "g-imported", "Historical imports", "project_stats_card", stats(S, "trace_count", [tag("historical-import")]),
            metric="trace count", source="traces", filters=["tags contains historical-import"], grouping=None,
            unit="traces", visualization="stat card", sufficiency=">= 1", limitations="imports never re-ran a model"),
          W("G", "g-models", "Model versions in use", "project_metrics",
            chart("SPAN_COUNT", "bar", span_filters=[span_type("llm")], breakdown={"field": "model"}), metric="llm spans",
            source="native model", filters=["type = llm"], grouping="model", unit="calls", visualization="bar",
            sufficiency="native model present", limitations="digests are in metadata (tfg_model.version)")]
    for wid, title, what in [("g-digests", "Model digests, prompt versions, dataset hashes, seeds", "provenance table"),
                             ("g-token-coverage", "Token coverage (LLM spans with reported usage)", "coverage"),
                             ("g-metric-coverage", "Metric coverage (observed / not evaluated / not applicable)", "coverage"),
                             ("g-integrity", "Evidence integrity (seals) and import verification (ledger)", "integrity")]:
        w.append(W("G", wid, title, None, None, metric=what, source="sealed records, manifests, ledger", filters=[],
                   grouping="dataset / experiment", unit=None, visualization="table", sufficiency="always",
                   limitations="not a native Opik field: generated offline", ui=False, automation=LOCAL))
    # ------------------------------------------------------------------ F. experiments (experiments dashboard)
    core = ["case_pass", "extraction_accuracy", "schema_valid", "safety_ok", "expected_status_match"]
    w += [W("F", "f-radar", "Experiments: quality profile", "experiments_feedback_scores",
            {"chartType": "radar", "feedbackScores": core, "maxExperimentsCount": "10", "filters": []},
            metric=", ".join(core), source="experiment scores", filters=[], grouping="experiment", unit="mean",
            visualization="radar", sufficiency="2+ experiments over the same dataset",
            limitations="only experiments with uploaded items and scores"),
          W("F", "f-bars", "Experiments: scores side by side", "experiments_feedback_scores",
            {"chartType": "bar", "feedbackScores": core + ["unsafe_request_detected", "safe_refused"],
             "maxExperimentsCount": "10", "filters": []}, metric="core + safety", source="experiment scores", filters=[],
            grouping="experiment", unit="mean", visualization="bar", sufficiency="2+ experiments",
            limitations="means hide per-case differences: see the per-case table"),
          W("F", "f-leaderboard", "Experiment leaderboard", "experiment_leaderboard",
            {"filters": [], "enableRanking": True, "rankingMetric": "case_pass", "rankingDirection": True, "maxRows": 20},
            metric="case_pass", source="experiments", filters=[], grouping="experiment", unit="mean",
            visualization="table", sufficiency="2+ experiments",
            limitations="ranking only within the same dataset; no winner from 11 cases")]
    for wid, title, what in [("f-per-case", "Per-case comparison (Case ID x candidate)", "case table"),
                             ("f-latency-vs-acc", "Latency vs accuracy", "scatter"),
                             ("f-safety-vs-acc", "Safety vs accuracy", "scatter"),
                             ("f-consistency", "Repetitions and consistency", "needs runs >= 2"),
                             ("f-failures", "Failure distribution by candidate", "taxonomy")]:
        w.append(W("F", wid, title, None, None, metric=what, source="experiments + sealed rows", filters=[],
                   grouping="candidate / case", unit=None, visualization="table / scatter",
                   sufficiency="equivalent cases and criteria", limitations="Opik's experiment compare view gives the "
                   "per-case view interactively; scatter and taxonomy are generated offline", ui=False, automation=LOCAL))
    return w


LEGEND = ("**Data kinds** (tags and metadata `tfg_data_kind`): `real-llm-call` = a real model call; "
          "`DETERMINISTIC_BASELINE` = rules interpreter; `test-double-llm` = simulated model (never a model result); "
          "`historical-import` = a sealed record imported later (the model was NOT re-run). Missing values are "
          "absent, never 0. Percentiles from a handful of traces describe those traces only.")
NOT_EXECUTION = ("Everything here is planning and validation. No vehicle was armed, uploaded or moved; "
                 "every proposal stayed PENDING_AUTHORIZATION.")


def _layout(section_widgets):
    layout, x, y = [], 0, 0
    for w in section_widgets:
        width = 1 if w["type"] == "project_stats_card" else (6 if w["type"] == "text_markdown" else 3)
        if x + width > 6:
            x, y = 0, y + 2 if width == 1 else y + 4
        h = 2 if w["type"] == "project_stats_card" else (2 if w["type"] == "text_markdown" else 4)
        layout.append({"i": w["id"], "x": x, "y": y, "w": width, "h": h, "minW": 1, "maxW": 6, "minH": 2, "maxH": 12})
        x += width
        if x >= 6:
            x, y = 0, y + h
    return layout


SECTIONS = {"A": "A · Overview", "B": "B · Model performance", "C": "C · Interpretation and planning quality",
            "D": "D · Safety and constraints", "E": "E · Multi-agent coordination", "F": "F · Experiment comparison",
            "G": "G · Provenance and reproducibility"}


def _state(section_ids, spec):
    sections = []
    for sid in section_ids:
        ws = [w for w in spec if w["section"] == sid and w["automation"] == "API_CONFIG"]
        def config(w):
            if w["type"] in ("project_metrics", "project_stats_card"):
                return {"projectId": PROJECT_ID, **w["config"]}
            return w["config"]
        sections.append({"id": f"section-{sid.lower()}", "title": SECTIONS[sid],
                         "widgets": [{"id": w["id"], "title": w["title"], "type": w["type"], "config": config(w)} for w in ws],
                         "layout": _layout(ws)})
    return {"version": contract.DASHBOARD_VERSION, "sections": sections, "lastModified": LAST_MODIFIED}


def dashboard_bodies() -> list[dict]:
    spec = widgets()
    main = {"project_name": PROJECT, "name": NAME, "type": "multi_project",
            "description": "TFG multi-agent and LLM evaluation: overview, model performance, quality, safety, "
                           "coordination and provenance. Sections A-E, G. Experiments in the companion dashboard.",
            "config": _state(["A", "B", "C", "D", "E", "G"], spec)}
    experiments = {"name": NAME_EXPERIMENTS, "type": "experiments",
                   "description": "Section F: experiment comparison (same dataset only).", "config": _state(["F"], spec)}
    for body in (main, experiments):
        contract.dashboard_write(body)
    return [main, experiments]


def spec_markdown(spec: list[dict]) -> str:
    lines = [f"# {NAME}: widget specification", "",
             "| # | Section | Widget | Opik type | Metric | Source | Filters | Grouping | Unit | Visualization | "
             "Sufficient data | Limitations | UI | Automation |", "|" + " --- |" * 14]
    for i, w in enumerate(spec, 1):
        lines.append(f"| {i} | {w['section']} | {w['title']} | {w['type'] or '—'} | {w['metric'] or '—'} | {w['source']} | "
                     f"{'; '.join(w['filters']) or '—'} | {w['grouping'] or '—'} | {w['unit'] or '—'} | "
                     f"{w['visualization']} | {w['sufficiency']} | {w['limitations']} | {'yes' if w['ui_supported'] else 'no'} | "
                     f"{w['automation']} |")
    return "\n".join(lines) + "\n"
