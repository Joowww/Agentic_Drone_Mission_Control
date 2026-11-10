"""Opik REST/dashboard contract facts, PINNED to the public sources read on 04/11/2026, and offline validators.

Sources (read-only GETs, nothing written anywhere):
- OpenAPI: comet-ml/opik@df61dd21c66e sdks/code_generation/fern/openapi/openapi.yaml (sha256 4fb9c28ad1d1b456...)
- Dashboard types: apps/opik-frontend/src/types/dashboard.ts (sha256 91c661339b6bc5bd...), widget schemas under
  apps/opik-frontend/src/v2/pages-shared/dashboards/widgets/*, templates lib/dashboard/templates.ts (665b803c9bd2...),
  DASHBOARD_VERSION = 4 (lib/dashboard/utils.ts), METRIC_NAME_TYPE (api/projects/useProjectMetric.ts).
Status: VERIFIED_AGAINST_PUBLIC_SOURCE_AT_COMMIT, NOT verified against the service except what a real call
proved (traces/batch, spans/batch: 204; GET traces/{id}, projects/{id}, spans: 200, on 04/11/2026). The dashboard
`config` is free JSON in the API: its shape comes from the frontend types, so a created dashboard must still be
opened once in the UI. These validators are a guard for OUR bodies, not a client; sending stays in
observability.opik_export / multiagent.opik_bridge.
"""
from __future__ import annotations

import re
import uuid

SOURCE = {"repository": "comet-ml/opik", "commit": "df61dd21c66e", "read_on": "2026-11-04",
          "openapi_sha256_prefix": "4fb9c28ad1d1b456", "dashboard_types_sha256_prefix": "91c661339b6bc5bd",
          "templates_sha256_prefix": "665b803c9bd2672a",
          "status": "VERIFIED_AGAINST_PUBLIC_SOURCE_AT_COMMIT; service-verified only for traces/spans batch and GETs"}
ENDPOINTS = {
    "traces_batch": ("POST", "/v1/private/traces/batch", "SERVICE_VERIFIED_204"),
    "spans_batch": ("POST", "/v1/private/spans/batch", "SERVICE_VERIFIED_204"),
    "trace_get": ("GET", "/v1/private/traces/{id}", "SERVICE_VERIFIED_200"),
    "span_update": ("PATCH", "/v1/private/spans/{id}", "SPEC_ONLY (SpanUpdate)"),
    "trace_feedback_scores": ("PUT", "/v1/private/traces/feedback-scores", "SPEC_ONLY (FeedbackScoreBatch)"),
    "span_feedback_scores": ("PUT", "/v1/private/spans/feedback-scores", "SPEC_ONLY (FeedbackScoreBatch)"),
    "dataset_create": ("POST", "/v1/private/datasets", "SPEC_ONLY (Dataset_Write)"),
    "dataset_items": ("PUT", "/v1/private/datasets/items", "SPEC_ONLY (DatasetItemBatch_Write)"),
    "experiment_create": ("POST", "/v1/private/experiments", "SPEC_ONLY (Experiment_Write)"),
    "experiment_items": ("POST", "/v1/private/experiments/items", "SPEC_ONLY (ExperimentItemsBatch)"),
    "dashboard_create": ("POST", "/v1/private/dashboards", "SPEC_ONLY (Dashboard_Write; config shape from frontend)"),
}
SPAN_TYPES = ("general", "tool", "llm", "guardrail")
SCORE_SOURCES = ("ui", "sdk", "online_scoring")
DATASET_ITEM_SOURCES = ("manual", "trace", "span", "sdk")
DASHBOARD_TYPES = ("multi_project", "experiments")
DASHBOARD_VERSION = 4
WIDGET_TYPES = ("project_metrics", "project_stats_card", "text_markdown", "experiments_feedback_scores",
                "experiment_leaderboard", "ollie_chart")
METRIC_TYPES = ("FEEDBACK_SCORES", "TRACE_COUNT", "DURATION", "TOKEN_USAGE", "COST", "GUARDRAILS_FAILED_COUNT",
                "THREAD_COUNT", "THREAD_COST", "THREAD_DURATION", "THREAD_FEEDBACK_SCORES", "SPAN_COUNT", "SPAN_COST",
                "SPAN_DURATION", "SPAN_FEEDBACK_SCORES", "SPAN_TOKEN_USAGE", "TRACE_AVERAGE_DURATION",
                "SPAN_AVERAGE_DURATION", "THREAD_AVERAGE_DURATION", "TRACE_ERROR_RATE", "SPAN_ERROR_RATE")
STATS_METRICS_COMMON = ("duration.p50", "duration.p90", "duration.p99", "input", "output", "metadata", "tags",
                        "total_estimated_cost_sum", "usage.completion_tokens", "usage.prompt_tokens",
                        "usage.total_tokens", "error_count")
STATS_METRICS = {"traces": STATS_METRICS_COMMON + ("trace_count", "thread_count", "llm_span_count", "span_count",
                                                   "total_estimated_cost", "guardrails_failed_count"),
                 "spans": STATS_METRICS_COMMON + ("span_count", "total_estimated_cost")}
CHART_TYPES = ("line", "bar", "radar")
BREAKDOWN_FIELDS = ("none", "tags", "metadata", "name", "error_info", "error_type", "model", "provider", "type",
                    "guardrail_name")
COLUMN_TYPES = ("string", "number", "list", "date_time", "duration", "dictionary", "feedback_scores_number", "cost",
                "category", "errors")
FILTER_OPERATORS = ("contains", "not_contains", "starts_with", "ends_with", "is_empty", "is_not_empty", "in",
                    "not_in", "=", "!=", ">", ">=", "<", "<=")
UUID_FIELDS = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ContractError(ValueError):
    pass


def _uuid(value, where):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise ContractError(f"{where}: not a canonical UUID") from None


def _only(obj, allowed, required, where):
    if not isinstance(obj, dict):
        raise ContractError(f"{where}: not an object")
    unknown = set(obj) - set(allowed)
    missing = set(required) - set(obj)
    if unknown or missing:
        raise ContractError(f"{where}: unknown {sorted(unknown)} missing {sorted(missing)}")


def feedback_score_batch(body: dict) -> None:
    _only(body, {"scores"}, {"scores"}, "FeedbackScoreBatch")
    if not body["scores"]:
        raise ContractError("FeedbackScoreBatch: empty")
    for i, s in enumerate(body["scores"]):
        where = f"score[{i}]"
        _only(s, {"project_name", "project_id", "name", "category_name", "value", "reason", "source", "author",
                  "source_queue_id", "id"}, {"id", "name", "source", "value"}, where)
        _uuid(s["id"], where)
        if s["source"] not in SCORE_SOURCES:
            raise ContractError(f"{where}: source")
        v = s["value"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not -1e9 <= v <= 1e9 or v != v:
            raise ContractError(f"{where}: value must be a finite number (never a status string)")


def span_update(body: dict) -> None:
    _only(body, {"project_name", "project_id", "trace_id", "parent_span_id", "name", "type", "end_time", "input",
                 "output", "metadata", "model", "provider", "tags", "tags_to_add", "tags_to_remove", "usage",
                 "total_estimated_cost", "error_info", "ttft", "source", "environment"}, {"trace_id"}, "SpanUpdate")
    _uuid(body["trace_id"], "SpanUpdate.trace_id")
    for k, v in (body.get("usage") or {}).items():
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 2 ** 31:
            raise ContractError(f"SpanUpdate.usage.{k}: int32")
    if "total_estimated_cost" in body and not body["total_estimated_cost"] >= 0:
        raise ContractError("SpanUpdate.total_estimated_cost")


def dataset_write(body: dict) -> None:
    _only(body, {"id", "name", "project_id", "project_name", "type", "visibility", "tags", "description"}, {"name"},
          "Dataset_Write")
    if len(body.get("description") or "") > 255:
        raise ContractError("Dataset_Write.description > 255")
    if body.get("visibility") not in (None, "private"):
        raise ContractError("Dataset_Write.visibility must stay private")


def dataset_items(body: dict) -> None:
    _only(body, {"dataset_name", "dataset_id", "project_name", "project_id", "items", "batch_group_id",
                 "copy_from_dataset_id", "copy_from_version_id"}, {"items"}, "DatasetItemBatch_Write")
    if not (body.get("dataset_name") or body.get("dataset_id")):
        raise ContractError("DatasetItemBatch_Write: dataset_name or dataset_id")
    for i, item in enumerate(body["items"]):
        _only(item, {"id", "trace_id", "span_id", "source", "data", "description", "tags", "evaluators",
                     "execution_policy"}, {"data", "source"}, f"item[{i}]")
        if item["source"] not in DATASET_ITEM_SOURCES or not isinstance(item["data"], dict):
            raise ContractError(f"item[{i}]: source/data")
        if "id" in item:
            _uuid(item["id"], f"item[{i}].id")


def experiment_write(body: dict) -> None:
    _only(body, {"id", "dataset_name", "project_id", "project_name", "name", "metadata", "tags", "type",
                 "evaluation_method", "optimization_id", "status", "experiment_scores", "prompt_version",
                 "prompt_versions", "dataset_version_id"}, {"dataset_name"}, "Experiment_Write")
    if "id" in body:
        _uuid(body["id"], "Experiment_Write.id")
    if body.get("status") not in (None, "running", "completed", "cancelled", "failed"):
        raise ContractError("Experiment_Write.status")
    if any(len(t) > 100 for t in body.get("tags") or []):
        raise ContractError("Experiment_Write.tags > 100 chars")


def experiment_items(body: dict) -> None:
    _only(body, {"experiment_items"}, {"experiment_items"}, "ExperimentItemsBatch")
    for i, item in enumerate(body["experiment_items"]):
        _only(item, {"id", "experiment_id", "dataset_item_id", "trace_id", "project_id", "project_name"},
              {"experiment_id", "dataset_item_id", "trace_id"}, f"experiment_item[{i}]")
        for k in ("experiment_id", "dataset_item_id", "trace_id"):
            _uuid(item[k], f"experiment_item[{i}].{k}")


def _filters(filters, where):
    for i, f in enumerate(filters or []):
        _only(f, {"id", "field", "type", "operator", "key", "value", "error"}, {"id", "field", "type", "operator", "value"},
              f"{where}.filter[{i}]")
        if f["type"] not in COLUMN_TYPES + ("",) or f["operator"] not in FILTER_OPERATORS + ("",):
            raise ContractError(f"{where}.filter[{i}]: type/operator")


def widget(w: dict, where: str, dashboard_type: str) -> None:
    if not {"id", "title", "type", "config"} <= set(w):
        raise ContractError(f"{where}: id/title/type/config required")
    t, c = w["type"], w["config"]
    if t not in WIDGET_TYPES:
        raise ContractError(f"{where}: unknown widget type {t}")
    if t == "ollie_chart":
        raise ContractError(f"{where}: ollie_chart needs a saved query only Ollie can create; not automatable")
    if t in ("project_metrics", "project_stats_card") and dashboard_type == "multi_project" and not (
            c.get("projectId") or c.get("projectIds") or c.get("allProjects")):
        raise ContractError(f"{where}: a multi_project widget needs projectId/projectIds/allProjects")
    if t == "project_metrics":
        if c.get("metricType") not in METRIC_TYPES or c.get("chartType") not in ("line", "bar"):
            raise ContractError(f"{where}: metricType/chartType")
        b = c.get("breakdown")
        if b and (b.get("field") not in BREAKDOWN_FIELDS or (b["field"] == "metadata" and not b.get("metadataKey"))):
            raise ContractError(f"{where}: breakdown")
        for k in ("traceFilters", "spanFilters", "threadFilters"):
            _filters(c.get(k), where)
    elif t == "project_stats_card":
        if c.get("source") not in STATS_METRICS:
            raise ContractError(f"{where}: source")
        metric = c.get("metric", "")
        if metric not in STATS_METRICS[c["source"]] and not metric.startswith("feedback_scores."):
            raise ContractError(f"{where}: stats metric {metric!r}")
        for k in ("traceFilters", "spanFilters"):
            _filters(c.get(k), where)
    elif t == "experiments_feedback_scores":
        if dashboard_type != "experiments":
            raise ContractError(f"{where}: experiment widgets go on an experiments dashboard")
        n = c.get("maxExperimentsCount")
        if not (isinstance(n, str) and n.isdigit() and 1 <= int(n) <= 100) or c.get("chartType", "bar") not in CHART_TYPES:
            raise ContractError(f"{where}: maxExperimentsCount (string 1-100) / chartType")
        _filters(c.get("filters"), where)
    elif t == "experiment_leaderboard":
        if dashboard_type != "experiments":
            raise ContractError(f"{where}: experiment widgets go on an experiments dashboard")
        _filters(c.get("filters"), where)
    elif t == "text_markdown" and not isinstance(c.get("content"), str):
        raise ContractError(f"{where}: content")


def dashboard_write(body: dict) -> None:
    _only(body, {"project_id", "project_name", "name", "type", "description", "config"}, {"config", "name"},
          "Dashboard_Write")
    if len(body["name"]) > 120 or len(body.get("description") or "") > 1000:
        raise ContractError("Dashboard_Write: name/description too long")
    if body.get("type") not in DASHBOARD_TYPES:
        raise ContractError("Dashboard_Write.type")
    state = body["config"]
    _only(state, {"version", "sections", "lastModified"}, {"version", "sections", "lastModified"}, "DashboardState")
    if state["version"] != DASHBOARD_VERSION:
        raise ContractError("DashboardState.version")
    ids = set()
    for s in state["sections"]:
        _only(s, {"id", "title", "widgets", "layout"}, {"id", "title", "widgets", "layout"}, f"section {s.get('id')}")
        widget_ids = {w["id"] for w in s["widgets"]}
        if {l["i"] for l in s["layout"]} != widget_ids:
            raise ContractError(f"section {s['id']}: layout does not match widgets")
        for w in s["widgets"]:
            if w["id"] in ids:
                raise ContractError(f"duplicate widget id {w['id']}")
            ids.add(w["id"])
            widget(w, f"section {s['id']} widget {w['id']}", body["type"])
        for l in s["layout"]:
            if not all(isinstance(l.get(k), int) and l[k] >= 0 for k in ("x", "y", "w", "h")) or l["x"] + l["w"] > 6:
                raise ContractError(f"section {s['id']}: layout item {l.get('i')} outside the 6-column grid")
