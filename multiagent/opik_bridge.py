"""Bridge between sealed multi-agent results and Opik Cloud (workspace joowww, project tfg-multiagent-benchmarks).

Reuses observability.opik_export for everything it already does: destination, deterministic UUIDv7 ids
(scopes "trace|..." / "span|..." as its send() requires), the export gate, request bodies, the single-pass
send() with its durable per-batch record and no automatic retry. This module only adds:
- historical import: a sealed results directory (pilot format) -> OpikPlan, after verifying its SHA256SUMS;
  ONLY the spans that were recorded are converted (a stage that did not run has no span; it is listed in
  metadata.tfg_stages_not_executed); the LLM span is the real model call, every other span is deterministic
  computation; times are the recorded ones (started_utc + perf_counter duration); nothing is re-run;
- egress control: redaction, a scan for secrets and local paths, and a manifest of exactly what would leave;
- a ledger of what was sent to this destination, so a retry never duplicates (an UNCERTAIN send blocks
  resending until it is verified);
- verification of a sent trace by id (GET), recorded apart from the HTTP acceptance.

Credentials, official Opik mechanisms only, read at send time and never returned, logged or stored:
OPIK_API_KEY in the environment, or api_key in ~/.opik.config (section [opik], as written by
`opik configure`). The workspace and project are FIXED below; a different OPIK_WORKSPACE or config
workspace makes the send refuse. Default mode is offline (dry run).
"""
from __future__ import annotations

import configparser
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import urllib.request

from observability import opik_export as opik
from observability.langsmith_export import ExportError

from multiagent.tracing import SECRET_KEY, SECRET_VALUE, redact

WORKSPACE = "joowww"
PROJECT = "tfg-multiagent-benchmarks"
ENDPOINT = opik.OPIK_CLOUD_ENDPOINT
CONFIG_PATH = Path.home() / ".opik.config"
ROOT = Path(__file__).resolve().parents[1]
IMPORTS = ROOT / "multiagent/benchmark/opik_imports" / f"{WORKSPACE}__{PROJECT}"
KIND = "real_model_output_sealed_record"  # passes the existing export gate; never "captured" or "synthetic"
KIND_DETERMINISTIC = "deterministic_baseline_sealed_record"
# Opik Cloud rejects (HTTP 400 "Invalid UUID for id") an ingested UUIDv7 whose embedded time is more than its window
# (default 24 h, comet-ml/opik config.yml uuidValidation) in the past or future. Learned from OP-1 (2026-11-06).
ID_WINDOW = timedelta(hours=24)
ID_WINDOW_MARGIN = timedelta(hours=1)
STAGES = {  # observability categories -> span names of the orchestrator graph
    "mission_orchestrator": ["mission"], "llm_interpretation": ["interpret"],
    "safety_validation": ["unsafe_request_screen", "risk_signals:safety/2", "contradictions", "stated_facts_cross_check",
                          "availability"],
    "drone_swarm_agent": ["plan_aerial"], "objective_allocation": ["plan_aerial"],
    "swarm_coordination": ["deconfliction:*", "joint_spatial", "coordination_checks"],
    "rover_agent": ["plan_ground"], "global_result": ["mission"]}
LOCAL_PATH = re.compile(r"/home/[^\s\"']+|/tmp/[^\s\"']+")


# ------------------------------------------------------------------------------- credentials --
def credential_status(environ=None, config_path: Path = CONFIG_PATH) -> dict:
    """Presence only: no value is read. ``config_file_private`` is True when only the owner can read it."""
    env = os.environ if environ is None else environ
    present = config_path.is_file()
    mode = stat.S_IMODE(config_path.stat().st_mode) if present else None
    return {"env_OPIK_API_KEY_set": bool(env.get(opik.API_KEY_ENV)), "config_file_present": present,
            "config_file_private": None if mode is None else not (mode & 0o077),
            "env_OPIK_WORKSPACE": env.get("OPIK_WORKSPACE"), "required_workspace": WORKSPACE,
            "required_project": PROJECT, "endpoint": ENDPOINT}


def _api_key(environ=None, config_path: Path = CONFIG_PATH) -> str | None:
    """At send time only. Env first, then ~/.opik.config [opik] api_key. Refuses another workspace."""
    env = os.environ if environ is None else environ
    if env.get("OPIK_WORKSPACE") not in (None, "", WORKSPACE):
        raise ExportError(f"OPIK_WORKSPACE names another workspace; this bridge only sends to {WORKSPACE}")
    if env.get(opik.API_KEY_ENV):
        return env[opik.API_KEY_ENV]
    if config_path.is_file():
        if stat.S_IMODE(config_path.stat().st_mode) & 0o077:
            raise ExportError(f"{config_path} is readable by others; chmod 600 it first")
        config = configparser.ConfigParser()
        config.read(config_path)
        section = config["opik"] if config.has_section("opik") else {}
        if section.get("workspace") not in (None, "", WORKSPACE):
            raise ExportError(f"{config_path} names another workspace; this bridge only sends to {WORKSPACE}")
        if section.get("url_override") not in (None, "", ENDPOINT, ENDPOINT + "/"):
            raise ExportError(f"{config_path} url_override is not {ENDPOINT}; refusing to send elsewhere")
        return section.get("api_key") or None
    return None


# --------------------------------------------------------------------------- historical plan --
def verify_seal(results_dir: Path) -> str:
    sums = Path(results_dir) / "SHA256SUMS"
    for line in sums.read_text().splitlines():
        digest, name = line.split("  ", 1)
        if hashlib.sha256((Path(results_dir) / name).read_bytes()).hexdigest() != digest:
            raise ExportError(f"sealed record changed: {name}; refusing to import")
    return hashlib.sha256(sums.read_bytes()).hexdigest()


def _clean(value):
    """Redaction plus local paths replaced; applied to every field that leaves. Under a secret-looking key, text,
    lists and objects are redacted; booleans, numbers and null are kept (they cannot carry a credential), so
    criteria such as no_authorization_no_command stay readable."""
    if isinstance(value, dict):
        return {str(k): (v if SECRET_KEY.search(str(k)) and (v is None or isinstance(v, (bool, int, float)))
                         else "[REDACTED]" if SECRET_KEY.search(str(k)) else _clean(v)) for k, v in value.items()}
    value = redact(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return LOCAL_PATH.sub("[LOCAL_PATH]", value)
    return value


def _stage(name: str) -> list[str]:
    return sorted(s for s, names in STAGES.items()
                  if name in names or any(n.endswith("*") and name.startswith(n[:-1]) for n in names))


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).name


def native_usage(call: dict) -> dict:
    """Opik native usage of a REAL model call: only the service-reported counts; total only when both exist."""
    usage = {k: v for k, v in (call.get("usage") or {}).items()
             if k in ("prompt_tokens", "completion_tokens") and isinstance(v, int) and not isinstance(v, bool)}
    if len(usage) == 2:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def id_time(value: str) -> datetime:
    """The unix-ms time a UUIDv7 embeds."""
    return datetime.fromtimestamp(int(value.replace("-", "")[:12], 16) / 1000, timezone.utc)


def import_id_findings(plan, now: datetime | None = None) -> list[str]:
    """Every id must be a canonical UUIDv7 inside the window; references (trace_id, parent_span_id) must point to
    ids of the same plan. Old, invalid and dangling ids are all reported (nothing is sent with any of them)."""
    import uuid as _uuid
    out = []
    ids = {t["id"] for t in plan.traces} | {s["id"] for s in plan.spans}
    for kind, items in (("trace", plan.traces), ("span", plan.spans)):
        for item in items:
            try:
                value = _uuid.UUID(str(item["id"]))
                if value.version != 7 or str(value) != item["id"]:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                out.append(f"{kind} id {item.get('id')!r} is not a canonical UUIDv7")
                continue
    span_ids = {s["id"] for s in plan.spans}
    for s in plan.spans:
        if s.get("trace_id") not in {t["id"] for t in plan.traces}:
            out.append(f"span {s['id']} points to trace {s.get('trace_id')} outside the plan")
        if s.get("parent_span_id") and s["parent_span_id"] not in span_ids:
            out.append(f"span {s['id']} has parent {s['parent_span_id']} outside the plan")
    if not out:
        out += id_window_findings(plan, now)
    return out


def content_sha256(plan) -> dict:
    """Canonical, id-INDEPENDENT hash of a plan's content, per batch kind: every id and id reference is replaced by
    the scope it was derived from, and the import bookkeeping keys (_import_id, tfg_id_epoch) are dropped. Equal for
    the original plan and any re-stamped one: it can be authorized before the final ids exist."""
    import copy as _copy
    names = {i: f"<{scope}>" for i, scope in plan.id_scopes.items()}

    def norm(item):
        item = _copy.deepcopy(item)
        for key in ("id", "trace_id", "parent_span_id"):
            if item.get(key) is not None:
                item[key] = names.get(item[key], "<UNKNOWN_ID>")
        for key in ("_import_id", "tfg_id_epoch"):
            (item.get("metadata") or {}).pop(key, None)
        return item
    return {kind: hashlib.sha256(json.dumps([norm(i) for i in items], sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=False).encode()).hexdigest()
            for kind, items in (("traces", plan.traces), ("spans", plan.spans))}


def id_mapping(original, restamped) -> list[dict]:
    """original id -> re-stamped id for every trace and span, matched by the scope both were derived from."""
    by_scope = {scope: i for i, scope in original.id_scopes.items()}
    return [{"scope": scope, "kind": "trace" if scope.startswith("trace|") else "span",
             "original_id": by_scope.get(scope), "import_id": i} for i, scope in sorted(restamped.id_scopes.items(),
                                                                                       key=lambda kv: kv[1])]


def id_window_findings(plan, now: datetime | None = None, *, window=ID_WINDOW, margin=ID_WINDOW_MARGIN) -> list[str]:
    """Ids the service would reject as too old or too far in the future (with a safety margin)."""
    now = now or datetime.now(timezone.utc)
    limit = window - margin
    return [f"{kind} {item['id']} embeds {id_time(item['id']).isoformat()}"
            for kind, items in (("trace", plan.traces), ("span", plan.spans)) for item in items
            if abs(id_time(item["id"]) - now) > limit]


def historical_plan(results_dir: Path, *, candidate_dir: str = "qwen", cases=None, project: str = PROJECT,
                    workspace: str = WORKSPACE, native_fields: bool = False, exclude=None, id_epoch: datetime | None = None):
    """OpikPlan for the sealed runs of ``candidate_dir`` (default the real model), optionally a subset of cases.

    ``native_fields`` (opt-in, representation v2): the real LLM span also carries Opik's native model, provider and
    usage, so token widgets and model breakdowns work; no cost is set (a local model has none). The default
    (False) is representation v1, byte-identical to what was sent for E07. Deterministic baselines get the
    DETERMINISTIC_BASELINE tag and comparison group; their tokens and cost never exist.

    ``id_epoch`` (opt-in): the TIME COMPONENT of every trace and span id is shifted so that the earliest run of the
    sealed report maps to ``id_epoch`` (relative order kept). start_time/end_time stay the historical ones; the
    shift is declared in trace metadata (``tfg_id_epoch``). Needed because Opik rejects ids older than its
    ingestion window; the default (None) keeps the original ids, byte-identical to the E07 send."""
    results_dir = Path(results_dir)
    seal = verify_seal(results_dir)
    base = results_dir / candidate_dir
    report = json.loads((base / "report.json").read_text())
    records = {(r["case_id"], r["run_index"]): r for r in map(json.loads, (base / "records.jsonl").read_text().splitlines())}
    failures_path = results_dir / "analysis_v2/failures.json"
    failures = json.loads(failures_path.read_text())[candidate_dir]["cases"] if failures_path.is_file() else {}
    destination = opik.make_destination(project, workspace)
    plan = opik.OpikPlan(destination=destination)
    kind = KIND if report.get("data_kind", "").startswith("MODEL_OUTPUT") else KIND_DETERMINISTIC
    sources = {"results_dir": _rel(results_dir), "seal_sha256": seal}
    shift = timedelta(0)
    if id_epoch is not None:
        first = min(datetime.fromisoformat(json.loads((base / "traces" / f"{r['case_id']}.jsonl").read_text()
                                                      .splitlines()[0])["started_utc"]).astimezone(timezone.utc)
                    for r in report["rows"])
        shift = id_epoch.astimezone(timezone.utc) - datetime.fromisoformat(opik._iso(first).replace("Z", "+00:00"))
    for row in report["rows"]:
        case_id, run = row["case_id"], row.get("run_index", 0)
        if (cases and case_id not in cases) or (exclude and case_id in exclude):
            continue
        trace_file = base / "traces" / f"{case_id}.jsonl"
        spans = [json.loads(l) for l in trace_file.read_text().splitlines()]
        if not spans:
            plan.errors.append(f"{case_id}: empty trace")
            continue
        root = next((s for s in spans if s["parent_span_id"] is None), None)
        if root is None or any(s.get("status") == "OPEN" or "duration_s" not in s for s in spans):
            plan.errors.append(f"{case_id}: incomplete trace (no root or an unfinished span)")
            continue
        record = records[(case_id, run)]
        llm = next((s for s in spans if s["kind"] == "llm"), None)
        call = (llm or {}).get("model_call") or {}
        start = datetime.fromisoformat(root["started_utc"]).astimezone(timezone.utc)
        end = start + timedelta(seconds=root["duration_s"])
        start = datetime.fromisoformat(opik._iso(start).replace("Z", "+00:00"))
        scope = f"trace|multiagent-import|{sources['results_dir']}|{candidate_dir}|{case_id}|{run}"
        trace_id = opik.deterministic_uuid7(destination["key"], scope, start + shift)
        executed = {s["name"] for s in spans}
        not_executed = sorted(stage for stage, names in STAGES.items()
                              if not any(n in executed or (n.endswith("*") and any(e.startswith(n[:-1]) for e in executed))
                                         for n in names))
        exp = root.get("experiment") or {}
        metadata = {
            "tfg_import": "HISTORICAL_SEALED_RECORD", "tfg_data_kind": kind, "tfg_rerun": False,
            "tfg_experiment_id": exp.get("experiment_id"), "tfg_case_id": case_id, "tfg_run_index": run,
            "tfg_dataset": record["dataset"], "tfg_model": record["model"], "tfg_prompt": record["prompt"] | {"text": None},
            "tfg_generation": record["generation"], "tfg_task": record["task"],
            "tfg_result": {"status": row["status"], "expected_status": row["expected_status"], "outcome": row.get("outcome"),
                           "case_pass": row["case_pass"], "criteria": row["criteria"], "reasons": row["reasons"]},
            "tfg_safety": {"safety_ok": row["safety_ok"], "unsafe_missed": row["unsafe_missed"],
                           "safe_refused": row["safe_refused"], "classification": (failures.get(case_id) or {}).get("safety")},
            "tfg_failure": failures.get(case_id), "tfg_extraction_accuracy": row["extraction_accuracy"],
            "tfg_latency": {"model_call_s": call.get("latency_s"), "mission_s": root["duration_s"],
                            "basis": "recorded: started_utc wall clock + perf_counter durations of the original run"},
            "tfg_tokens": call.get("usage"), "tfg_server_timing": call.get("server_timing"),
            "tfg_cost": "NOT_APPLICABLE_LOCAL_MODEL" if (record["model"] or {}).get("provider") == "ollama" else "UNKNOWN",
            "tfg_stages_not_executed": not_executed,
            "tfg_sources": {**sources, "trace_file": _rel(trace_file),
                            "trace_file_sha256": hashlib.sha256(trace_file.read_bytes()).hexdigest(),
                            "record_trace_sha256": record.get("trace_sha256"),
                            "raw_reply_sha256": call.get("raw_sha256"), "prompt_sha256": (call.get("prompt") or {}).get("sha256")}}
        if kind == KIND_DETERMINISTIC:
            metadata["tfg_comparison_group"] = "DETERMINISTIC_BASELINE"
        if id_epoch is not None:
            metadata["tfg_id_epoch"] = {"epoch_utc": opik._iso(id_epoch.astimezone(timezone.utc)),
                                        "shift_s": shift.total_seconds(),
                                        "note": "id time component only; start/end times are the historical ones"}
            # Opik's own import convention (opik/cli/imports/project.py): the source id is kept as _import_id
            metadata["_import_id"] = opik.deterministic_uuid7(destination["key"], scope, start)
        tags = ["tfg-multiagent", "historical-import", "real-llm-call" if llm else "deterministic-only",
                *(["DETERMINISTIC_BASELINE"] if kind == KIND_DETERMINISTIC else []),
                f"case:{case_id}", f"dataset:{record['dataset']['id']}@{record['dataset']['version']}",
                f"model:{(record['model'] or {}).get('model')}", f"prompt:{record['prompt'].get('template_id')}",
                f"outcome:{row.get('outcome')}", f"experiment:{exp.get('experiment_id')}"]
        plan.traces.append(_clean({"id": trace_id, "project_name": project, "name": f"multiagent:{case_id}",
                                   "start_time": opik._iso(start), "end_time": opik._iso(end),
                                   "input": {"operator_text": (root.get("input") or {}).get("text")},
                                   "output": root.get("output"), "metadata": metadata, "tags": tags}))
        plan.trace_kinds[trace_id] = kind
        plan.id_scopes[trace_id] = scope
        if shift:
            plan.id_shifts[trace_id] = shift
        ids = {}
        for s in spans:
            s_start = datetime.fromisoformat(s["started_utc"]).astimezone(timezone.utc)
            s_start = datetime.fromisoformat(opik._iso(s_start).replace("Z", "+00:00"))
            s_scope = f"span|multiagent-import|{sources['results_dir']}|{candidate_dir}|{case_id}|{run}|{s['span_id']}"
            span_id = opik.deterministic_uuid7(destination["key"], s_scope, s_start + shift)
            original_span_id = opik.deterministic_uuid7(destination["key"], s_scope, s_start)
            ids[s["span_id"]] = span_id
            real_llm = s["kind"] == "llm"
            body = {"id": span_id, "trace_id": trace_id, "project_name": project,
                    "type": "llm" if real_llm else ("tool" if s["kind"] == "tool" else "general"),
                    "name": f"{s['agent']}:{s['kind']}:{s['name']}", "start_time": opik._iso(s_start),
                    "end_time": opik._iso(s_start + timedelta(seconds=s["duration_s"])),
                    "input": {"prompt": (call.get("prompt") or {}).get("text")} if real_llm else s.get("input"),
                    "output": {"raw_reply": call.get("raw_text"), "parsed": s.get("output")} if real_llm else s.get("output"),
                    "metadata": {"tfg_execution": "REAL_LLM_CALL" if real_llm else "DETERMINISTIC_COMPUTATION",
                                 "tfg_agent": s["agent"], "tfg_kind": s["kind"], "tfg_status": s["status"],
                                 "tfg_stage": _stage(s["name"]), "tfg_duration_s": s["duration_s"],
                                 "tfg_duration_clock": s.get("duration_clock"),
                                 **({"_import_id": original_span_id} if id_epoch is not None else {}),
                                 **({"tfg_model": call.get("model"), "tfg_usage": call.get("usage"),
                                     "tfg_finish_reason": call.get("finish_reason"), "tfg_parse_error": call.get("parse_error"),
                                     "tfg_generation": call.get("generation")} if real_llm else {})},
                    "tags": ["tfg-multiagent", "historical-import", "real-llm-call" if real_llm else "deterministic"]}
            if s.get("parent_span_id") in ids:
                body["parent_span_id"] = ids[s["parent_span_id"]]
            if native_fields and real_llm:
                body.update(model=call.get("model"), provider=call.get("provider"))
                if native_usage(call):
                    body["usage"] = native_usage(call)
            if s["status"] in ("ERROR", "ERROR_INFRASTRUCTURE"):
                body["error_info"] = {"exception_type": s["status"], "message": str(s.get("error") or "")[:500],
                                      "traceback": "not captured"}
            plan.spans.append(_clean(body))
            plan.id_scopes[span_id] = s_scope
            if shift:
                plan.id_shifts[span_id] = shift
    return plan


# ------------------------------------------------------------------------------ egress control --
def egress_findings(plan) -> list[str]:
    """Anything that must not leave: secret-looking values or keys, local paths, unredacted credentials."""
    findings = []
    for item in plan.traces + plan.spans:
        text = json.dumps(item, sort_keys=True)
        if SECRET_VALUE.search(text):
            findings.append(f"{item['id']}: secret-looking value")
        if LOCAL_PATH.search(text):
            findings.append(f"{item['id']}: local path")

        def walk(value, where):
            if isinstance(value, dict):
                for k, v in value.items():
                    if SECRET_KEY.search(str(k)) and not (v == "[REDACTED]" or v is None or isinstance(v, (bool, int, float))):
                        findings.append(f"{item['id']}: secret-looking key {where}.{k}")
                    walk(v, f"{where}.{k}")
            elif isinstance(value, list):
                for i, v in enumerate(value):
                    walk(v, f"{where}[{i}]")
        walk(item, "item")
    return findings


def manifest(plan, results_dir: Path, *, ledger: dict | None = None) -> dict:
    ledger = ledger or load_ledger()
    bodies = opik.send_requests(plan) if plan.traces else []
    return {"schema": "tfg.multiagent.opik-import-manifest/1", "destination": {"workspace": WORKSPACE, "project": PROJECT,
            "endpoint": ENDPOINT}, "source": _rel(results_dir), "status": "DRY_RUN_NOT_SENT",
            "traces": [{"id": t["id"], "case_id": t["metadata"]["tfg_case_id"], "spans": sum(s["trace_id"] == t["id"] for s in plan.spans),
                        "real_llm_spans": sum(s["trace_id"] == t["id"] and s["metadata"]["tfg_execution"] == "REAL_LLM_CALL"
                                              for s in plan.spans),
                        "already_in_ledger": ledger["traces"].get(t["id"], {}).get("status")} for t in plan.traces],
            "requests": [{"kind": k, "path": p, "bytes": len(d), "body_sha256": hashlib.sha256(d).hexdigest()}
                         for k, p, d in bodies],
            "leaves_the_computer": {"trace": ["operator_text (synthetic benchmark request)", "mission output summary",
                                              "metadata: experiment, case, dataset id/version/sha256, model+digest, prompt id+sha256, "
                                              "generation parameters, result, criteria, safety, failure class, latency, tokens, "
                                              "stages not executed, source paths (repo-relative) and hashes", "tags"],
                                    "llm_span": ["full prompt text (synthetic site points + request)", "full raw model reply",
                                                 "parsed brief", "usage, finish reason, generation"],
                                    "deterministic_spans": ["recorded redacted inputs/outputs and status"],
                                    "never": ["credentials", "local absolute paths", "anything not in the sealed record"]},
            "egress_findings": egress_findings(plan), "plan_errors": plan.errors}


# ------------------------------------------------------------------------------------- ledger --
def load_ledger(root: Path = IMPORTS) -> dict:
    path = Path(root) / "ledger.json"
    return json.loads(path.read_text()) if path.is_file() else {"schema": "tfg.multiagent.opik-ledger/1",
                                                               "destination": f"{WORKSPACE}/{PROJECT}", "traces": {}}


def _save_ledger(ledger: dict, root: Path = IMPORTS) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    tmp = Path(root) / "ledger.json.tmp"
    tmp.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n")
    tmp.replace(Path(root) / "ledger.json")


def subset(plan, trace_ids: set) -> "opik.OpikPlan":
    out = opik.OpikPlan(destination=plan.destination)
    out.traces = [t for t in plan.traces if t["id"] in trace_ids]
    out.spans = [s for s in plan.spans if s["trace_id"] in trace_ids]
    out.trace_kinds = {k: v for k, v in plan.trace_kinds.items() if k in trace_ids}
    keep = {t["id"] for t in out.traces} | {s["id"] for s in out.spans}
    out.id_scopes = {k: v for k, v in plan.id_scopes.items() if k in keep}
    out.id_shifts = {k: v for k, v in plan.id_shifts.items() if k in keep}
    return out


def send_import(plan, *, authorized: bool, record_path: Path, transport=opik.urllib_transport, environ=None,
                config_path: Path = CONFIG_PATH, timeout: float = 30.0, root: Path = IMPORTS,
                max_traces: int = 1, retry_verified_absent: bool = False, supersedes=(), error_body_path=None,
                now: datetime | None = None) -> dict:
    """One controlled send of at most ``max_traces`` traces not yet in the ledger. Never automatic.

    Refused before connecting when an id is outside the service's UUIDv7 window, or when the same sealed case is
    already in the ledger under another id; ``supersedes`` names old ids of the same cases that a read-only GET
    found absent (404), which an authorization may explicitly replace."""
    if not authorized:
        raise ExportError("sending needs explicit authorization (--i-authorize-send)")
    if plan.destination != opik.make_destination(PROJECT, WORKSPACE):
        raise ExportError(f"plan destination is not {WORKSPACE}/{PROJECT}")
    if plan.errors:
        raise ExportError(f"plan has errors: {plan.errors}")
    findings = egress_findings(plan)
    if findings:
        raise ExportError(f"egress check failed: {findings[:3]}")
    ledger = load_ledger(root)
    known = [t["id"] for t in plan.traces if t["id"] in ledger["traces"] and not (
        retry_verified_absent and ledger["traces"][t["id"]]["status"] == "VERIFIED_ABSENT")]
    if known:
        raise ExportError(f"already in the ledger (sent or uncertain), never resent automatically: {known}")
    if not 1 <= len(plan.traces) <= max_traces:
        raise ExportError(f"this send carries {len(plan.traces)} traces; the limit is {max_traces}")
    outside = id_window_findings(plan, now)
    if outside:
        raise ExportError(f"ids outside the Opik ingestion window (rebuild with id_epoch): {outside[:2]}")
    supersedes = set(supersedes)
    by_case = {}
    for tid, entry in ledger["traces"].items():
        key_ = ((entry.get("source") or {}).get("trace_file"), (entry.get("source") or {}).get("trace_file_sha256"))
        by_case.setdefault(key_, []).append(tid)
    for t in plan.traces:
        src = t["metadata"].get("tfg_sources") or {}
        for old in by_case.get((src.get("trace_file"), src.get("trace_file_sha256")), []):
            if old == t["id"]:  # the same id is governed by the ledger check above (retry_verified_absent)
                continue
            entry = ledger["traces"][old]
            absent = entry["status"] == "VERIFIED_ABSENT" or (entry.get("post_failure_readback") or {}).get("http") == 404
            if old not in supersedes or not absent or entry["status"] == "VERIFIED_PRESENT":
                raise ExportError(f"case {t['metadata'].get('tfg_case_id')} already in the ledger as {old} "
                                  f"({entry['status']}); only a verified-absent id named in supersedes can be replaced")
    api_key = _api_key(environ, config_path)
    if not api_key:
        raise ExportError("no Opik credential: set OPIK_API_KEY or create ~/.opik.config (see the documentation)")
    for t in plan.traces:  # intent first: a crash after the POST leaves UNCERTAIN, never a silent duplicate
        ledger["traces"][t["id"]] = {"case_id": t["metadata"]["tfg_case_id"], "status": "SEND_STARTED",
                                     "source": t["metadata"]["tfg_sources"], "record": _rel(record_path),
                                     "at_utc": datetime.now(timezone.utc).isoformat()}
    _save_ledger(ledger, root)
    report = opik.send(plan, endpoint=ENDPOINT, api_key=api_key, record_path=str(record_path), timeout=timeout,
                       transport=transport, error_body_path=error_body_path)
    api_key = None
    status = "HTTP_ACCEPTED_NOT_VERIFIED" if report["status"] == "ALL_BATCHES_HTTP_ACCEPTED" else \
        ("NOT_SENT" if report["status"] == "NOT_SENT" else "UNCERTAIN")
    for t in plan.traces:
        if status == "NOT_SENT":
            ledger["traces"].pop(t["id"], None)
        else:
            ledger["traces"][t["id"]].update(status=status, send_status=report["status"],
                                             http_statuses=report.get("http_statuses_received"))
            old = [o for o in supersedes if (ledger["traces"].get(o) or {}).get("case_id") == t["metadata"].get("tfg_case_id")]
            if old:
                ledger["traces"][t["id"]]["supersedes"] = old
                for o in old:
                    ledger["traces"][o]["superseded_by"] = t["id"]
    _save_ledger(ledger, root)
    return {"status": status, "send_report": report}


def get_transport(url, headers, timeout):
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(opik._NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoint
            return response.status, response.read(1_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def verify_trace(trace_id: str, *, transport=get_transport, environ=None, config_path: Path = CONFIG_PATH,
                 timeout: float = 30.0, root: Path = IMPORTS) -> dict:
    """GET /v1/private/traces/{id}: the trace exists, in the right project, with our metadata and no secret.
    The path follows the Opik REST API; it is NOT verified until this first real use (recorded either way)."""
    ledger = load_ledger(root)
    if trace_id not in ledger["traces"]:
        raise ExportError("trace not in the ledger: verify only what this bridge sent")
    api_key = _api_key(environ, config_path)
    if not api_key:
        raise ExportError("no Opik credential")
    status, raw = transport(f"{ENDPOINT}/v1/private/traces/{trace_id}",
                            {"authorization": api_key, "Comet-Workspace": WORKSPACE, "accept": "application/json"},
                            timeout)
    secret_in_reply = api_key in raw.decode("utf-8", "replace") if raw else False
    checks = {"http_status": status, "found": status == 200}
    if status == 200:
        body = json.loads(raw)
        project_name = body.get("project_name")
        if project_name is None and body.get("project_id"):  # the trace names its project by id: resolve it
            p_status, p_raw = transport(f"{ENDPOINT}/v1/private/projects/{body['project_id']}",
                                        {"authorization": api_key, "Comet-Workspace": WORKSPACE,
                                         "accept": "application/json"}, timeout)
            project_name = json.loads(p_raw).get("name") if p_status == 200 and p_raw else None
        api_key = None
        checks.update(id_matches=body.get("id") == trace_id, project_name=project_name,
                      project_matches=project_name == PROJECT,
                      metadata_case=(body.get("metadata") or {}).get("tfg_case_id"),
                      metadata_import=(body.get("metadata") or {}).get("tfg_import"),
                      no_secret_in_reply=not secret_in_reply and not SECRET_VALUE.search(raw.decode("utf-8", "replace")),
                      project_id=body.get("project_id"))
    api_key = None
    verified = checks["found"] and checks.get("id_matches") and checks.get("project_matches") and \
        checks.get("no_secret_in_reply") and checks.get("metadata_import") == "HISTORICAL_SEALED_RECORD"
    entry = ledger["traces"][trace_id]
    entry["verification"] = {**checks, "at_utc": datetime.now(timezone.utc).isoformat()}
    if status == 404:
        entry["status"] = "VERIFIED_ABSENT"  # only this state allows a controlled resend (--retry-verified-absent)
    if verified:
        entry["status"] = "VERIFIED_PRESENT"
        if checks.get("project_id"):
            entry["link"] = f"https://www.comet.com/opik/{WORKSPACE}/projects/{checks['project_id']}/traces?trace={trace_id}"
    _save_ledger(ledger, root)
    return {"verified": bool(verified), "checks": checks, "link": entry.get("link")}


# ---------------------------------------------------------------------------------------- CLI --
def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Sealed multi-agent results -> Opik Cloud (joowww/tfg-multiagent-benchmarks)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="credential presence (no value is read)")
    for name in ("dry-run", "send"):
        p = sub.add_parser(name)
        p.add_argument("results_dir", type=Path)
        p.add_argument("--cases", nargs="+", required=name == "send")
        p.add_argument("--candidate-dir", default="qwen")
        p.add_argument("--out", type=Path)
        if name == "send":
            p.add_argument("--i-authorize-send", action="store_true")
            p.add_argument("--record", type=Path, required=True, help="new send-record JSONL (must not exist)")
            p.add_argument("--max-traces", type=int, default=1)
            p.add_argument("--retry-verified-absent", action="store_true",
                           help="resend only traces a verification found ABSENT (never UNCERTAIN ones)")
    v = sub.add_parser("verify")
    v.add_argument("trace_id")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(credential_status(), indent=1))
        return 0
    if args.command == "verify":
        print(json.dumps(verify_trace(args.trace_id), indent=1, sort_keys=True))
        return 0
    plan = historical_plan(args.results_dir, candidate_dir=args.candidate_dir, cases=set(args.cases or []) or None)
    info = manifest(plan, args.results_dir)
    if args.command == "dry-run":
        payload = {"manifest": info, "bodies": {"traces": opik.batch_bodies("traces", plan.traces),
                                                "spans": opik.batch_bodies("spans", plan.spans)}}
        text = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text)
        print(json.dumps({k: info[k] for k in ("status", "destination", "egress_findings", "plan_errors")}, indent=1))
        print(json.dumps(info["requests"], indent=1))
        return 0 if not info["egress_findings"] and not info["plan_errors"] else 1
    result = send_import(plan, authorized=args.i_authorize_send, record_path=args.record, max_traces=args.max_traces,
                         retry_verified_absent=args.retry_verified_absent)
    print(json.dumps({"status": result["status"], "send_status": result["send_report"]["status"],
                      "http": result["send_report"].get("http_statuses_received"),
                      "trace_ids": [t["id"] for t in plan.traces]}, indent=1))
    return 0 if result["status"] == "HTTP_ACCEPTED_NOT_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())


def native_patch(results_dir: Path, case_id: str, *, candidate_dir: str = "qwen") -> dict:
    """PATCH /v1/private/spans/{id} body (SpanUpdate) adding native model/provider/usage to an ALREADY SENT real LLM
    span (representation v1 -> v2). Prepared only; sending it changes the remote span and needs authorization."""
    v1 = historical_plan(results_dir, candidate_dir=candidate_dir, cases={case_id})
    v2 = historical_plan(results_dir, candidate_dir=candidate_dir, cases={case_id}, native_fields=True)
    span_v1 = next(s for s in v1.spans if s["type"] == "llm")
    span_v2 = next(s for s in v2.spans if s["id"] == span_v1["id"])
    body = {"trace_id": span_v1["trace_id"], "project_name": span_v1["project_name"],
            **{k: span_v2[k] for k in ("model", "provider", "usage") if k in span_v2}}
    return {"method": "PATCH", "path": f"/v1/private/spans/{span_v1['id']}", "span_id": span_v1["id"],
            "trace_id": span_v1["trace_id"], "case_id": case_id, "body": body,
            "effect": "adds native model/provider/usage to the remote span; input, output, metadata, times and tags "
                      "unchanged; no cost is set; the sealed local record is not modified"}
