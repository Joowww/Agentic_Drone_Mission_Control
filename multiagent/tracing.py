"""Local structured trace of a multi-agent run, and its dry-run Opik payload.

Each record is one span: agent responsible, kind (agent | llm | tool | validation), name, model and version,
mission id, redacted inputs/outputs, measured duration (perf_counter, this process) and UTC start, status.
The trace is written as JSON lines and is the source of truth for tests.

Opik: ``opik_plan`` maps a trace onto the REST bodies already used by observability.opik_export
(traces/batch, spans/batch) with that module's destination, deterministic UUIDv7 ids and export gate. It is a
DRY RUN: nothing here sends. A synthetic trace is labelled ``synthetic_fixture`` and the existing gate refuses
it without explicit consent; a model run stays ``unknown_provenance`` until a provenance record exists. Inputs and
outputs in span bodies follow the Opik OpenAPI ``input``/``output`` fields and are UNVERIFIED against a service.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
import uuid

from planning.artifact_store import fingerprint

TRACE_SCHEMA = "tfg.multiagent.trace/1"
SECRET_KEY = re.compile(r"((?:^|[_-])token$|api[_-]?key|secret|password|passwd|authori[sz]ation|bearer|cookie|credential(?!_env))",
                        re.I)
SECRET_VALUE = re.compile(r"(Bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+)")
MAX_STRING = 4000
OPIK_SPAN_TYPES = {"llm": "llm", "tool": "tool", "validation": "general", "agent": "general"}


def redact(value, *, depth=0):
    """Remove secret-looking keys and values; bound size. Applied to every input/output before it is stored."""
    if depth > 12:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if SECRET_KEY.search(str(k)) else redact(v, depth=depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [redact(v, depth=depth + 1) for v in value[:200]]
        return items + ([f"[{len(value) - 200} MORE ITEMS]"] if len(value) > 200 else [])
    if isinstance(value, str):
        cleaned = SECRET_VALUE.sub("[REDACTED]", value)
        return cleaned if len(cleaned) <= MAX_STRING else cleaned[:MAX_STRING] + f"...[{len(cleaned)} chars]"
    if isinstance(value, float) and value != value:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value), depth=depth + 1)


class Tracer:
    def __init__(self, *, mission_id: str, run_id: str | None = None, data_kind: str = "SYNTHETIC",
                 experiment: dict | None = None):
        """``experiment``: {experiment_id, dataset_id, dataset_version, split, case_id}; copied into every span."""
        self.mission_id, self.run_id, self.data_kind = mission_id, run_id or str(uuid.uuid4()), data_kind
        self.experiment = redact(experiment) if experiment else None
        self.records: list[dict] = []
        self._stack: list[str] = []

    @contextmanager
    def span(self, agent: str, kind: str, name: str, *, model: dict | None = None, inputs=None):
        record = {"schema": TRACE_SCHEMA, "span_id": f"{len(self.records) + 1:04d}", "run_id": self.run_id,
                  "mission_id": self.mission_id, "parent_span_id": self._stack[-1] if self._stack else None,
                  "agent": agent, "kind": kind, "name": name, "data_kind": self.data_kind,
                  "experiment": self.experiment,
                  "model": redact(model) if model else None, "input": redact(inputs),
                  "started_utc": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
        self.records.append(record)
        self._stack.append(record["span_id"])
        started = time.perf_counter()
        try:
            yield record
            if record["status"] == "OPEN":
                record["status"] = "OK"
        except Exception as exc:
            record.update(status="ERROR", error=redact(f"{type(exc).__name__}: {exc}"))
            raise
        finally:
            record["duration_s"] = time.perf_counter() - started
            record["duration_clock"] = "PERF_COUNTER_THIS_PROCESS"
            self._stack.pop()

    @staticmethod
    def output(record: dict, value, *, status: str | None = None, **extra) -> None:
        record["output"] = redact(value)
        if status:
            record["status"] = status
        record.update({k: redact(v) for k, v in extra.items()})

    def validation(self, agent: str, name: str, status: str, detail=None) -> None:
        with self.span(agent, "validation", name, inputs=None) as record:
            self.output(record, detail, status=status)

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in self.records),
                        encoding="utf-8")
        return path

    def summary(self) -> dict:
        by_kind = {}
        for record in self.records:
            by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
        return {"run_id": self.run_id, "mission_id": self.mission_id, "spans": len(self.records), "by_kind": by_kind,
                "errors": sum(r["status"] == "ERROR" for r in self.records), "data_kind": self.data_kind,
                "trace_sha256": fingerprint(self.records)}


LIVE_STAGES = {"replanning": ("revision_request:", "gate:drone_proposal:"), "tool_calls": ("tool:",),
               "llm_agent_steps": ("drone_swarm_agent:step", "rover_agent:step"), "rover_review": ("gate:rover_proposal",)}


def execution_kind(record: dict) -> str:
    """What really happened in a span: a real model call, a TEST DOUBLE call, a tool call, a deterministic
    validation or an agent step. Decided from the recorded data_kind, never from the span name."""
    if record["kind"] == "llm":
        kind = (record.get("model_call") or {}).get("data_kind") or (record.get("model") or {}).get("data_kind")
        return "REAL_LLM_CALL" if kind == "MODEL_OUTPUT" else "TEST_DOUBLE_LLM_CALL"
    return {"tool": "TOOL_CALL", "validation": "DETERMINISTIC_VALIDATION", "agent": "AGENT_STEP"}.get(record["kind"],
                                                                                                    record["kind"].upper())


def live_stages(name: str) -> list[str]:
    from multiagent.opik_bridge import _stage
    return sorted(set(_stage(name)) | {s for s, prefixes in LIVE_STAGES.items() if name.startswith(prefixes)})


def opik_plan(records: list[dict], project: str, *, workspace: str | None = None, metrics: dict | None = None,
              native_fields: bool = False):
    """Dry-run OpikPlan for one trace (existing exporter types and gate). Never sends.

    ``native_fields`` (opt-in, representation v2, same as opik_bridge.historical_plan): a REAL LLM span also carries
    Opik's native model, provider and usage (service-reported counts only). Test doubles and deterministic spans never
    do, and no cost is ever set here."""
    from observability import opik_export as opik
    destination = opik.make_destination(project, workspace)
    plan = opik.OpikPlan(destination=destination, events=len(records))
    if not records:
        plan.errors.append("empty trace")
        return plan
    kinds = {r["data_kind"] for r in records}
    kind = "synthetic_fixture" if kinds == {"SYNTHETIC"} else "unknown_provenance"
    start = datetime.fromisoformat(records[0]["started_utc"])
    ends = [datetime.fromisoformat(r["started_utc"]) + timedelta(seconds=r.get("duration_s", 0.0)) for r in records]
    trace_scope = f"multiagent|{records[0]['run_id']}"
    trace_id = opik.deterministic_uuid7(destination["key"], trace_scope, start)
    root = records[0]
    tags = ["tfg-multiagent", f"schema:{TRACE_SCHEMA}", "synthetic" if kind == "synthetic_fixture" else "model-run"]
    experiment = root.get("experiment") or {}
    llm = next((r for r in records if r["kind"] == "llm"), None)
    call = (llm or {}).get("model_call") or {}
    if experiment.get("experiment_id"):
        tags.append(f"experiment:{experiment['experiment_id']}")
    if experiment.get("dataset_id"):
        tags.append(f"dataset:{experiment['dataset_id']}@{experiment.get('dataset_version')}")
    metadata = {"tfg_mission_id": root["mission_id"], "tfg_run_id": root["run_id"], "tfg_data_kind": kind,
                "tfg_experiment": experiment or None, "tfg_experiment_id": experiment.get("experiment_id"),
                "tfg_model": root.get("model"),  # flat id: the key the dashboard breaks down by
                "tfg_generation": call.get("generation"), "tfg_prompt": {k: (call.get("prompt") or {}).get(k)
                                                                        for k in ("template_id", "sha256")},
                "tfg_validators": [{"agent": r["agent"], "name": r["name"], "status": r["status"]}
                                   for r in records if r["kind"] == "validation"],
                "tfg_resources": {"gpu_memory": "NOT_MEASURED"},
                "tfg_spans": len(records), "tfg_cost": "UNKNOWN", "tfg_send_status": "DRY_RUN_NOT_SENT",
                "tfg_payload_verification": "UNVERIFIED_AGAINST_OPIK_SERVICE"}
    if metrics is not None:
        metadata["tfg_metrics"] = redact(metrics)
    from multiagent.opik_bridge import STAGES  # observability stages; a stage without a span did not run
    executed = {r["name"] for r in records}
    from multiagent.llm_agents import agent_metrics
    metadata["tfg_agent_metrics"] = agent_metrics(records)
    metadata["tfg_stages_not_executed"] = sorted(
        stage for stage, names in STAGES.items()
        if not any(n in executed or (n.endswith("*") and any(e.startswith(n[:-1]) for e in executed)) for n in names))
    plan.traces.append({"id": trace_id, "project_name": project, "name": f"multiagent:{root['name']}",
                        "start_time": opik._iso(start), "end_time": opik._iso(max(ends)),
                        "input": root.get("input"), "output": root.get("output"), "metadata": metadata, "tags": tags})
    plan.trace_kinds[trace_id] = kind
    plan.id_scopes[trace_id] = trace_scope
    ids = {}
    for record, end in zip(records, ends):
        span_start = datetime.fromisoformat(record["started_utc"])
        scope = f"multiagent-span|{record['run_id']}|{record['span_id']}"
        span_id = opik.deterministic_uuid7(destination["key"], scope, span_start)
        ids[record["span_id"]] = span_id
        plan.id_scopes[span_id] = scope
        execution = execution_kind(record)
        span = {"id": span_id, "trace_id": trace_id, "project_name": project,
                # only a REAL model call is an Opik "llm" span; a test double never looks like one
                "type": "llm" if execution == "REAL_LLM_CALL" else
                ("general" if record["kind"] == "llm" else OPIK_SPAN_TYPES.get(record["kind"], "general")),
                "name": f"{record['agent']}:{record['kind']}:{record['name']}",
                "start_time": opik._iso(span_start), "end_time": opik._iso(end),
                "input": record.get("input"), "output": record.get("output"),
                "metadata": {"tfg_agent": record["agent"], "tfg_kind": record["kind"], "tfg_status": record["status"],
                             "tfg_execution": execution, "tfg_stage": live_stages(record["name"]),
                             "tfg_model": record.get("model"), "tfg_duration_s": record.get("duration_s"),
                             "tfg_duration_clock": record.get("duration_clock"),
                             **({"tfg_usage": (record.get("model_call") or {}).get("usage")}
                                if execution == "REAL_LLM_CALL" else {})},
                "tags": tags + (["test-double-llm"] if execution == "TEST_DOUBLE_LLM_CALL" else [])}
        if record.get("parent_span_id") in ids:
            span["parent_span_id"] = ids[record["parent_span_id"]]
        if native_fields and execution == "REAL_LLM_CALL":
            from multiagent.opik_bridge import native_usage
            call = record.get("model_call") or {}
            span.update({k: v for k, v in (("model", call.get("model")), ("provider", call.get("provider"))) if v})
            if native_usage(call):
                span["usage"] = native_usage(call)
        if record["status"] == "ERROR":
            span["error_info"] = {"exception_type": "error", "message": str(record.get("error"))[:500],
                                  "traceback": "not captured"}
        plan.spans.append(span)
    return plan


def opik_dry_run(records: list[dict], project: str = "tfg-multiagent", **kw) -> dict:
    """The exact request bodies a later, separately authorized send would POST; status DRY_RUN_NOT_SENT."""
    from observability import opik_export as opik
    plan = opik_plan(records, project, **kw)
    return {"status": "DRY_RUN_NOT_SENT", "destination": plan.destination, "errors": plan.errors,
            "bodies": {"traces": opik.batch_bodies("traces", plan.traces), "spans": opik.batch_bodies("spans", plan.spans)},
            "paths": opik.BATCH_PATHS, "trace_kinds": sorted(set(plan.trace_kinds.values())),
            "send": "not implemented here: use observability.opik_export.send with its gate, after authorization"}
