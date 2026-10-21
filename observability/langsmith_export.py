"""Export local Hermes capture JSONL (tfg.hermes.capture/3) to LangSmith runs. Dry-run by default.

Dry-run reads and validates the JSONL, builds the runs that would be sent and prints them.
It never imports the LangSmith SDK, reads credentials or opens a connection. Sending needs
``--send`` plus an explicit destination; the API key is read from ``LANGSMITH_API_KEY`` only
then and is never printed.

Destination: exactly one of a tracing project (``--project``) or an agent environment
(``--agent-id`` + ``--agent-environment``, beta, agent-based workspaces, langsmith >= 0.14.9).

Mapping (contract checked against langsmith 0.14.11 and the official run data format):
- one ``chain`` root per (run_id, session_ref, turn_ref): a grouping derived here, not an
  observed Hermes event; ``dotted_order`` = ``<start %Y%m%dT%H%M%S%fZ><uuid>`` segments joined by '.';
- only events with a Hermes-measured interval (llm_call/llm_error with both epochs) become
  timed ``llm`` child runs. Tool calls and untimed events have no known start: LangSmith
  requires ``start_time`` (the SDK fills ``now()`` when missing) and a run without
  ``end_time`` stays "in progress", so they become point-in-time ``events`` on the root with
  their capture time, never a 0 ms run. The root interval is derived only from Hermes epochs,
  never mixed with capture ``recorded_at``; a trace without any measured interval is withheld
  unless explicitly included as ``interval-unknown``;
- run ids are uuid5 of (destination key, event_id): a re-export to the same destination
  targets the same ids, a different destination gets different ids;
- every exported value comes from a field allowlist and lives in ``extra.metadata`` under
  ``tfg_*`` keys with its provenance. ``inputs``/``outputs`` stay empty. Token counters are
  NOT put in ``usage_metadata`` and ``ls_model_name`` is NOT set, so LangSmith does not
  estimate costs from Hermes-normalised (or synthetic) counters.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

from observability.hermes_capture import capture

SCHEMA_PATH = Path(capture.__file__).with_name("event.schema.json")
EXPORT_NAMESPACE = uuid.UUID("6f1f6f3e-6c2b-5b8e-9a51-2a4c1d0e7b10")
EXPORTER_VERSION = "4"
API_KEY_ENV = "LANGSMITH_API_KEY"
# langsmith >= 0.14.9 (verified 0.14.11): an AgentAddress travels as this LRN in the run's
# "address" field and cannot be combined with a project. Same id rule as the SDK.
AGENT_ID_PATTERN = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
AGENT_ENVIRONMENTS = ("local", "development", "staging", "production")
ENDPOINT_ENV = "LANGSMITH_ENDPOINT"
SYNTHETIC_MARK = re.compile(r"synthetic", re.IGNORECASE)
_DOTTED_TIME = "%Y%m%dT%H%M%S%fZ"
# Hermes reports wall-clock epochs and durations separately; tolerate float rounding only.
DURATION_TOLERANCE_S = 0.001

COMMON_FIELDS = ("event_type", "event_id", "recorded_at_utc", "run_id", "case_id", "session_ref", "task_ref",
                 "turn_ref", "api_request_ref", "absent_fields", "redacted_fields", "ambiguous_zero_fields")
EVENT_FIELDS = {
    "llm_call": ("provider", "upstream_provider", "model", "response_model", "api_mode", "finish_reason",
                 "timing_source", "timing_scope", "api_duration_s", "started_at_epoch_s", "ended_at_epoch_s",
                 "first_chunk_offset_s", "api_call_count", "message_count", "assistant_tool_call_count",
                 "context_length", "requested_tool_names", "usage_source", "usage", "retry_count"),
    "llm_error": ("provider", "model", "api_mode", "timing_source", "timing_scope", "api_duration_s",
                  "started_at_epoch_s", "ended_at_epoch_s", "api_call_count", "status_code", "retry_count",
                  "max_retries", "retryable", "reason", "error_type"),
    "tool_call": ("tool_call_ref", "tool_name", "status", "error_type", "duration_ms_received",
                  "duration_ms_measured", "duration_source"),
}
UNITS = {"api_duration_s": "s", "started_at_epoch_s": "s_since_epoch", "ended_at_epoch_s": "s_since_epoch",
         "first_chunk_offset_s": "s", "duration_ms_received": "ms", "duration_ms_measured": "ms"}


class ExportError(Exception):
    pass


def make_destination(project=None, agent_id=None, agent_environment=None):
    """Exactly one destination: a project name, or an agent id plus environment.

    ``key`` enters every deterministic run id and the ledger. A project keeps the bare name
    (ids of earlier project exports stay reproducible); an agent uses its LRN, so the same
    capture sent to an agent gets ids different from any project send.
    """
    if project is not None and (agent_id is not None or agent_environment is not None):
        raise ExportError("give either a project or an agent address, not both")
    if project is not None:
        if not isinstance(project, str) or not project.strip():
            raise ExportError("project name must be a non-empty string")
        if project.startswith("lrn:"):
            raise ExportError("project names starting with 'lrn:' are reserved for agent destinations")
        return {"mode": "project", "project": project, "key": project}
    if agent_id is None and agent_environment is None:
        raise ExportError("a destination is required: --project, or --agent-id with --agent-environment")
    if not isinstance(agent_id, str) or not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise ExportError("agent id must be a DNS label: 1-63 lowercase letters, digits or hyphens, "
                          "starting with a letter and ending with a letter or digit")
    environment = agent_environment.strip().lower() if isinstance(agent_environment, str) else None
    if environment not in AGENT_ENVIRONMENTS:
        raise ExportError(f"agent environment must be one of {', '.join(AGENT_ENVIRONMENTS)}")
    lrn = f"lrn:agents/{agent_id}/environments/{environment}"
    return {"mode": "agent", "agent_id": agent_id, "agent_environment": environment, "lrn": lrn, "key": lrn}


def _destination_label(destination):
    return destination["project"] if destination["mode"] == "project" else destination["lrn"]


@dataclass
class Plan:
    project: str | None
    destination: dict = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)  # root first, then its children
    traces: list[dict] = field(default_factory=list)
    withheld: list[dict] = field(default_factory=list)  # traces without any measured interval
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events: int = 0
    provenance_check: dict | None = None


def _run_id(project, key):
    return str(uuid.uuid5(EXPORT_NAMESPACE, f"{project}|{key}"))


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return parsed.astimezone(timezone.utc)


def _epoch(value):
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _check_strings(value, where):
    """Defence in depth: schema patterns already restrict strings; refuse anything secret-like."""
    if isinstance(value, str):
        if "://" in value or capture._SECRET.search(value):
            raise ExportError(f"{where}: value looks like a URL or secret; refusing to export")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_strings(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_strings(item, f"{where}[{index}]")


def load_events(paths):
    """Return (events, errors). Every line must parse and validate; nothing is repaired."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # installed transitively today, not pinned in requirements
        raise ExportError("jsonschema is required to validate capture files") from exc
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
                                     format_checker=FormatChecker())
    events, errors, seen = [], [], set()
    for path in map(Path, paths):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            where = f"{path.name}:{number}"
            if not line.strip():
                errors.append(f"{where}: empty line")
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{where}: invalid JSON ({exc.msg})")
                continue
            problems = sorted(e.message[:160] for e in validator.iter_errors(event))
            if problems:
                errors.append(f"{where}: schema: {problems[0]}")
                continue
            # FormatChecker only checks "date-time" when rfc3339-validator is installed; check it here.
            try:
                _utc(event["recorded_at_utc"])
            except (TypeError, ValueError):
                errors.append(f"{where}: recorded_at_utc is not an ISO 8601 timestamp with timezone")
                continue
            if event["event_id"] in seen:
                errors.append(f"{where}: duplicate event_id within input")
                continue
            seen.add(event["event_id"])
            events.append(event)
    return events, errors


def _measured_interval(event, warnings):
    """(start, end) from Hermes' own epochs, or None. Never derives a start from a duration."""
    if event["event_type"] == "tool_call":
        return None  # Hermes reports a duration but no start for tools
    start, end = event.get("started_at_epoch_s"), event.get("ended_at_epoch_s")
    if start is None or end is None or end < start:
        return None
    duration = event.get("api_duration_s")
    if duration is not None and abs((end - start) - duration) > DURATION_TOLERANCE_S:
        warnings.append(f"{event['event_id']}: ended-started differs from api_duration_s by "
                        f"{abs((end - start) - duration):.6f} s; both kept unchanged")
    return _epoch(start), _epoch(end)


def _metadata(event, provenance, basis):
    allowed = COMMON_FIELDS + EVENT_FIELDS[event["event_type"]]
    metadata = {f"tfg_{name}": event.get(name) for name in allowed if name != "event_type"}
    metadata.update({
        "tfg_event_type": event["event_type"],
        "tfg_schema": event["schema"],
        "tfg_exporter_version": EXPORTER_VERSION,
        "tfg_data_kind": provenance["kind"],
        "tfg_provenance_basis": provenance["basis"],
        "tfg_time_basis": basis,
        "tfg_units": {k: v for k, v in UNITS.items() if k in allowed},
        "tfg_cost": "not_computed",
    })
    if event["event_type"] == "llm_call":
        metadata["tfg_usage_semantics"] = "hermes_normalized_summary_not_provider_raw"
    return metadata


def _has_synthetic_marker(events):
    return any(SYNTHETIC_MARK.search(e.get("run_id") or "") or SYNTHETIC_MARK.search(e.get("case_id") or "")
               for e in events)


def verify_capture_provenance(paths):
    """Check the sink provenance records next to each capture file (offline, read-only).

    A file qualifies only if its directory holds at least one ``capture-provenance-*.json``,
    every such record is a regular file written by a sink created with Hermes' PluginContext for
    this capture schema, and the earliest record predates the file's first event. A record is
    evidence of how the sink was created, not a cryptographic attestation: it can be copied.
    """
    files, ok = [], True
    for path in map(Path, paths):
        times = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                times.append(_utc(json.loads(line)["recorded_at_utc"]))
            except (ValueError, TypeError, KeyError):
                continue
        records, problems = [], []
        for record_path in sorted(path.parent.glob("capture-provenance-*.json")):
            if record_path.is_symlink() or not record_path.is_file():
                problems.append(f"{record_path.name}: not a regular file")
                continue
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                created = _utc(record["created_at_utc"])
            except (ValueError, TypeError, KeyError):
                problems.append(f"{record_path.name}: unreadable")
                continue
            if record.get("schema") != capture.PROVENANCE_SCHEMA or record.get("capture_schema") != capture.SCHEMA:
                problems.append(f"{record_path.name}: unexpected schema")
            elif record.get("origin") != "hermes_plugin_context":
                problems.append(f"{record_path.name}: origin {record.get('origin')!r}")
            records.append(created)
        if not records and not problems:
            problems.append("no capture provenance record next to the file")
        elif records and times and min(records) > min(times):
            problems.append("provenance record is newer than the first event")
        files.append({"file": path.name, "records": len(records), "problems": problems})
        ok = ok and not problems
    return {"ok": ok, "files": files}


def _trace_provenance(members, declared, provenance_check):
    """Origin of one trace. Markers in run_id/case_id can only make it more conservative."""
    if _has_synthetic_marker(members):
        if declared == "captured":
            raise ExportError("events carry a synthetic marker in run_id/case_id but were declared captured")
        return {"kind": "synthetic_fixture", "basis": "synthetic_marker_in_ids"}
    if declared == "synthetic":
        return {"kind": "synthetic_fixture", "basis": "declared_synthetic"}
    if declared == "captured":
        return {"kind": "captured_hermes_metadata", "basis": "declared_captured_with_hermes_sink_provenance_record"}
    return {"kind": "unknown_provenance", "basis": "no_provenance_declaration"}


TRACE_LABELS = {"synthetic_fixture": ("SYNTHETIC · ", "synthetic"),
                "unknown_provenance": ("UNKNOWN-PROVENANCE · ", "provenance-unknown"),
                "captured_hermes_metadata": ("", "captured-metadata")}


def build_plan(events, project=None, *, agent_id=None, agent_environment=None, include_untimed=False,
               provenance=None, provenance_check=None):
    """``provenance``: None (unknown unless marked synthetic), "synthetic" or "captured".

    "captured" is an explicit operator declaration and needs ``provenance_check`` from
    :func:`verify_capture_provenance` to be ok; otherwise the plan is refused.
    """
    if provenance not in (None, "synthetic", "captured"):
        raise ExportError("provenance must be 'synthetic' or 'captured'")
    if provenance == "captured" and not (provenance_check and provenance_check["ok"]):
        raise ExportError("declared captured, but the capture provenance records do not verify")
    destination = make_destination(project, agent_id, agent_environment)
    plan = Plan(project=destination.get("project"), destination=destination, events=len(events))
    plan.provenance_check = provenance_check
    key_prefix = destination["key"]
    groups = {}
    for event in events:
        if event["turn_ref"] is None:
            key = ("event", event["event_id"])
        else:
            key = ("turn", event["run_id"], event["session_ref"], event["turn_ref"])
        groups.setdefault(key, []).append(event)
    for key, members in groups.items():
        origin = _trace_provenance(members, provenance, provenance_check)
        synthetic = origin["kind"] == "synthetic_fixture"
        prefix, kind_tag = TRACE_LABELS[origin["kind"]]
        tags = ["tfg-hermes-capture", f"schema:{capture.SCHEMA}", kind_tag]
        children, point_events = [], []
        for event in sorted(members, key=lambda e: e["recorded_at_utc"]):
            interval = _measured_interval(event, plan.warnings)
            if interval is None:
                # No measured start: a point-in-time event at capture time, not a timed run.
                metadata = _metadata(event, origin, "capture_recorded_at_point_not_an_interval")
                metadata["tfg_latency_measured"] = False
                _check_strings(metadata, f"event {event['event_id']}")
                point_events.append({"name": f"tfg.{event['event_type']}", "time": event["recorded_at_utc"],
                                     "kwargs": metadata})
                continue
            metadata = _metadata(event, origin, "hermes_epochs")
            metadata["tfg_latency_measured"] = True
            _check_strings(metadata, f"event {event['event_id']}")
            child = {
                "id": _run_id(key_prefix, f"event|{event['event_id']}"),
                "name": f"{prefix}{event['event_type']}:{event.get('model') or 'unknown'}",
                "run_type": "llm", "start_time": interval[0], "end_time": interval[1],
                "inputs": {}, "outputs": {}, "extra": {"metadata": metadata}, "tags": tags,
            }
            if event["event_type"] == "llm_error":
                child["error"] = f"{event.get('error_type') or 'unknown_error'} (status_code={event.get('status_code')})"
            children.append(child)
        root_id = _run_id(key_prefix, "root|" + "|".join(str(part) for part in key))
        first = members[0]
        root_meta = {
            "tfg_grouping": "derived_from_turn_ref" if key[0] == "turn" else "single_event_without_turn_ref",
            "tfg_observed_event": False, "tfg_run_id": first["run_id"], "tfg_case_id": first["case_id"],
            "tfg_session_ref": first["session_ref"], "tfg_turn_ref": first["turn_ref"],
            "tfg_data_kind": origin["kind"], "tfg_provenance_basis": origin["basis"],
            "tfg_timed_children": len(children), "tfg_point_events": len(point_events),
            "tfg_exporter_version": EXPORTER_VERSION, "tfg_cost": "not_computed",
            # Point events carry capture time; their comparability with Hermes epochs is not shown.
            "tfg_point_event_time_basis": "capture_recorded_at_not_compared_with_hermes_epochs",
        }
        if children:
            root_start = min(c["start_time"] for c in children)
            root_end = max(c["end_time"] for c in children)
            root_meta.update(tfg_time_basis="derived_min_max_of_hermes_epochs", tfg_interval_derived=True,
                             tfg_interval_status="derived_from_measured_children_only", tfg_latency_measured=False)
        elif include_untimed:
            # SDK requires start_time: use the first capture time as a marker and say so.
            root_start = root_end = _utc(min(e["recorded_at_utc"] for e in members))
            root_meta.update(tfg_time_basis="capture_recorded_at_marker", tfg_interval_derived=False,
                             tfg_interval_status="unknown_no_measured_interval", tfg_latency_measured=False)
            tags = [*tags, "interval-unknown", "latency-not-measured"]
            prefix = f"{prefix}[interval unknown] "
        else:
            plan.withheld.append({"root_id": root_id, "events": len(members), "synthetic": synthetic,
                                  "kind": origin["kind"], "reason": "no_measured_interval"})
            continue
        _check_strings(root_meta, f"root {root_id}")
        root_segment = f"{root_start.strftime(_DOTTED_TIME)}{root_id}"
        root = {"id": root_id, "trace_id": root_id, "dotted_order": root_segment,
                "name": f"{prefix}hermes_turn", "run_type": "chain", "start_time": root_start,
                "end_time": root_end, "inputs": {}, "outputs": {}, "extra": {"metadata": root_meta}, "tags": tags}
        if point_events:
            root["events"] = point_events
        for child in children:
            child.update(trace_id=root_id, parent_run_id=root_id,
                         dotted_order=f"{root_segment}.{child['start_time'].strftime(_DOTTED_TIME)}{child['id']}")
        plan.runs.extend([root, *children])
        plan.traces.append({"root_id": root_id, "synthetic": synthetic, "kind": origin["kind"],
                            "run_ids": [root_id, *(c["id"] for c in children)]})
    return plan


def _jsonable(run):
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in run.items()}


def _public_destination(destination):
    return {k: v for k, v in destination.items() if k != "key"}


def describe(plan, ledger=None):
    done = _ledger_roots(ledger, plan.destination) if ledger else set()
    return {
        "mode": "dry-run", "destination": _public_destination(plan.destination), "project": plan.project,
        "events": plan.events, "traces": len(plan.traces),
        "runs": len(plan.runs), "synthetic_traces": sum(t["synthetic"] for t in plan.traces),
        "unknown_provenance_traces": sum(t["kind"] == "unknown_provenance" for t in plan.traces),
        "captured_traces": sum(t["kind"] == "captured_hermes_metadata" for t in plan.traces),
        "provenance_check": plan.provenance_check,
        "point_events": sum(len(r.get("events", [])) for r in plan.runs),
        "withheld_traces": plan.withheld, "blocked_for_send_by_default": provenance_blocks(plan),
        "already_in_ledger": sorted(t["root_id"] for t in plan.traces if t["root_id"] in done),
        "errors": plan.errors, "warnings": plan.warnings, "prepared_runs": [_jsonable(r) for r in plan.runs],
        "note": "Nothing was sent. Metadata-only runs; token counters are Hermes-normalised and no cost is computed.",
    }


def _entry_destination_key(entry):
    # Ledger entries before exporter version 3 recorded only "project".
    if isinstance(entry.get("destination"), dict):
        return entry["destination"].get("key")
    return entry.get("project")


def _ledger_roots(path, destination):
    path = Path(path)
    if not path.exists():
        return set()
    roots = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if _entry_destination_key(entry) == destination["key"]:
            roots.add(entry["root_id"])
    return roots


def _append_ledger(path, destination, trace, outcome):
    entry = {"destination": destination, "project": destination.get("project"), "root_id": trace["root_id"],
             "run_ids": trace["run_ids"], "outcome": outcome,
             "exported_at_utc": datetime.now(timezone.utc).isoformat(), "exporter_version": EXPORTER_VERSION}
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _is_conflict(exc):
    try:
        from langsmith.utils import LangSmithConflictError
        if isinstance(exc, LangSmithConflictError):
            return True
    except ImportError:
        pass
    return type(exc).__name__ == "LangSmithConflictError"


def make_client(environ=os.environ):
    """Only called on an authorised send. Synchronous POSTs so failures raise (batch ingest
    in langsmith 0.14.x logs failures instead), no runtime/environment info is attached and
    the SDK's transport retries (default Retry(total=3) on 429/5xx, POST included) are off:
    a failure is reported once and never retried automatically."""
    key = environ.get(API_KEY_ENV)
    if not key:
        raise ExportError(f"{API_KEY_ENV} is not set; refusing to send")
    from langsmith import Client
    from urllib3.util.retry import Retry
    no_retries = Retry(total=0, connect=0, read=0, redirect=0, status=0, other=0, raise_on_status=False)
    return Client(api_key=key, api_url=environ.get(ENDPOINT_ENV) or None, retry_config=no_retries,
                  auto_batch_tracing=False, omit_traced_runtime_info=True)


def provenance_blocks(plan, *, allow_synthetic=False, allow_unknown_provenance=False):
    """Provenance reasons that block a send without explicit authorization.

    Withheld traces count too: an input whose traces were all withheld must not pass as allowed."""
    emitted = {t["kind"] for t in plan.traces}
    kinds = emitted | {w["kind"] for w in plan.withheld}
    where = lambda kind: "" if kind in emitted else " (in withheld traces)"
    blocks = []
    if "synthetic_fixture" in kinds and not allow_synthetic:
        blocks.append(f"plan contains synthetic traces{where('synthetic_fixture')}; "
                      "pass --allow-synthetic to send them as synthetic")
    if "unknown_provenance" in kinds and not allow_unknown_provenance:
        blocks.append(f"plan contains traces of unknown provenance{where('unknown_provenance')}; declare "
                      "--provenance (captured needs verified capture records) or pass --allow-unknown-provenance")
    return blocks


def check_send_allowed(plan, ledger, *, allow_synthetic=False, allow_unknown_provenance=False):
    """Local preconditions, checked before any credential is touched."""
    if plan.errors:
        raise ExportError("input has validation errors; nothing sent")
    if not ledger:
        raise ExportError("a ledger path is required to send")
    blocks = provenance_blocks(plan, allow_synthetic=allow_synthetic, allow_unknown_provenance=allow_unknown_provenance)
    if blocks:
        raise ExportError(blocks[0])


def send(plan, client, ledger, *, allow_synthetic=False, allow_unknown_provenance=False):
    """Send trace by trace; a trace is recorded in the ledger only when all its runs were accepted.

    ``posted`` counts calls that returned without error. langsmith 0.14.x ignores HTTP 409 on
    run creation (``to_ignore=LangSmithConflictError``), so a run whose deterministic id already
    exists also counts as posted: the SDK does not let us tell "new" from "already present".
    ``conflict_reported`` counts conflicts a client raises explicitly. The local ledger is what
    distinguishes a re-export, and only for the ledger file and destination it records.

    Every call names exactly one destination in code: ``project_name`` or an explicit
    ``address``. With an explicit address the SDK does not consult LANGSMITH_* env vars, so
    its silent drop of runs with a bad ambient address does not apply.
    """
    check_send_allowed(plan, ledger, allow_synthetic=allow_synthetic, allow_unknown_provenance=allow_unknown_provenance)
    destination = plan.destination
    if destination["mode"] == "project":
        target = {"project_name": destination["project"]}
    else:  # AgentAddress as the SDK defines it; the SDK validates it and sends its LRN
        target = {"address": {"kind": "AGENT", "id": destination["agent_id"],
                              "environment": destination["agent_environment"].upper()}}
    done = _ledger_roots(ledger, destination)
    by_id = {run["id"]: run for run in plan.runs}
    report = {"mode": "send", "destination": _public_destination(destination), "project": plan.project,
              "posted": 0, "conflict_reported": 0,
              "skipped_in_ledger": 0, "completed_traces": 0, "failed_trace": None, "not_attempted_traces": 0,
              "withheld_untimed_traces": len(plan.withheld),
              "note": "posted may include runs already present remotely (SDK ignores HTTP 409)"}
    for index, trace in enumerate(plan.traces):
        if trace["root_id"] in done:
            report["skipped_in_ledger"] += 1
            continue
        conflicts = 0
        for run_id in trace["run_ids"]:
            run = dict(by_id[run_id])
            try:
                client.create_run(**target, **run)
                report["posted"] += 1
            except Exception as exc:
                if _is_conflict(exc):
                    conflicts += 1
                    report["conflict_reported"] += 1
                    continue
                # Exception text may echo request details; report only its type.
                report["failed_trace"] = {"root_id": trace["root_id"], "run_id": run_id,
                                          "error_type": type(exc).__name__}
                report["not_attempted_traces"] = len(plan.traces) - index - 1
                return report
        _append_ledger(ledger, destination, trace,
                       "conflict_reported_for_all_runs" if conflicts == len(trace["run_ids"]) else "accepted")
        report["completed_traces"] += 1
    return report


def main(argv=None, *, client_factory=make_client, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="capture JSONL files (tfg.hermes.capture/3)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project", help="target LangSmith tracing project name")
    target.add_argument("--agent-id", help="target agent id (the agent's ID field, not its display name)")
    parser.add_argument("--agent-environment", choices=AGENT_ENVIRONMENTS,
                        help="agent environment; required with --agent-id")
    parser.add_argument("--ledger", help="local JSONL ledger of exported traces (required with --send)")
    parser.add_argument("--send", action="store_true", help="actually send; default is dry-run")
    parser.add_argument("--allow-synthetic", action="store_true", help="allow sending traces marked synthetic")
    parser.add_argument("--provenance", choices=("synthetic", "captured"),
                        help="declare the input's origin; 'captured' also needs verified sink provenance records")
    parser.add_argument("--allow-unknown-provenance", action="store_true",
                        help="allow sending traces whose origin is not declared (labelled unknown_provenance)")
    parser.add_argument("--include-untimed", action="store_true",
                        help="also export traces without any measured interval, tagged interval-unknown")
    args = parser.parse_args(argv)
    if args.agent_environment and not args.agent_id:
        parser.error("--agent-environment requires --agent-id")
    if args.agent_id and not args.agent_environment:
        parser.error("--agent-id requires --agent-environment")
    destination = make_destination(args.project, args.agent_id, args.agent_environment)
    events, errors = load_events(args.files)
    check = verify_capture_provenance(args.files) if args.provenance == "captured" else None
    plan = (build_plan(events, args.project, agent_id=args.agent_id, agent_environment=args.agent_environment,
                       include_untimed=args.include_untimed, provenance=args.provenance, provenance_check=check)
            if events or not errors else Plan(project=destination.get("project"), destination=destination))
    plan.errors.extend(errors)
    if not args.send:
        json.dump(describe(plan, args.ledger), out, indent=2, ensure_ascii=False)
        out.write("\n")
        return 1 if plan.errors else 0
    check_send_allowed(plan, args.ledger, allow_synthetic=args.allow_synthetic,
                       allow_unknown_provenance=args.allow_unknown_provenance)
    # Credentials are touched only after every local precondition has passed.
    report = send(plan, client_factory(), args.ledger, allow_synthetic=args.allow_synthetic,
                  allow_unknown_provenance=args.allow_unknown_provenance)
    json.dump(report, out, indent=2)
    out.write("\n")
    return 0 if report["failed_trace"] is None else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExportError as exc:
        print(f"langsmith_export: {exc}", file=sys.stderr)
        sys.exit(2)
