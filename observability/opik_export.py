"""Opik payload builder for local Hermes capture JSONL (tfg.hermes.capture/3). Dry-run by default.

The dry-run never imports an Opik SDK, reads credentials, opens a connection or writes a file.
Only ``--send`` connects: plain HTTPS POSTs (stdlib, no SDK), one per non-empty batch body, no
automatic retry, no redirects, a durable per-batch record and an explicit uncertain state (see
``send``). Validation, provenance and timing rules are the LangSmith exporter's
(``observability.langsmith_export``), reused unchanged.

Payload: the bodies of the Opik REST ``POST /v1/private/traces/batch`` (``{"traces": [...]}``)
and ``POST /v1/private/spans/batch`` (``{"spans": [...]}``) as described by the official OpenAPI
spec (comet-ml/opik ``sdks/code_generation/fern/openapi/openapi.yaml`` at 6ff71e2). Its
``TraceBatch_Write``/``SpanBatch_Write`` take 1-1000 items, so each list is split into bodies of
at most ``BATCH_MAX_ITEMS`` and an empty list yields no body. The shape was validated offline
against opik==2.2.110's REST models and serialization (mock transport, nothing sent); it is
**not verified against an Opik service**, and opik is not imported here.

Mapping:
- one trace per (run_id, session_ref, turn_ref); one ``llm`` span per llm_call/llm_error with a
  Hermes-measured interval; trace interval derived from those spans only;
- tool calls and untimed events have no known start: kept in the trace's
  ``metadata.tfg_point_events`` with their capture time, never as a span or a duration;
- spans carry no top-level ``usage``, ``model``, ``provider``, ``total_estimated_cost`` or
  ``ttft``: Opik estimates cost for ``llm`` spans with provider+model+usage, and Hermes'
  first-chunk offset is not a TTFT when retries happened. All values live in ``metadata``
  under ``tfg_*`` with their provenance;
- ids are deterministic UUIDs with the UUIDv7 layout (start time in ms + hash of destination
  and event), distinct per destination and from any LangSmith id.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from observability import langsmith_export as common
from observability.hermes_capture import capture
from observability.langsmith_export import ExportError

EXPORTER = "tfg-opik-offline"
EXPORTER_VERSION = "1"
PAYLOAD_VERIFICATION = ("UNVERIFIED_AGAINST_OPIK_SERVICE: fields follow the official OpenAPI spec for "
                        "traces/batch and spans/batch (comet-ml/opik@6ff71e2, reviewed 2026-10-21); shape "
                        "validated offline against opik==2.2.110 REST models and a mock transport "
                        "(evaluation/observability/opik_sdk_offline_validation_2026_10_21); opik is not a "
                        "dependency of this exporter")
BATCH_MAX_ITEMS = 1000  # TraceBatch_Write/SpanBatch_Write: minItems 1, maxItems 1000
# OpenAPI comet-ml/opik@6ff71e2: servers[0] and info.description (headers ``Comet-Workspace`` and
# ``authorization`` without "Bearer"); opik 2.2.110 OPIK_URL_CLOUD is the same URL.
OPIK_CLOUD_ENDPOINT = "https://www.comet.com/opik/api"
BATCH_PATHS = {"traces": "/v1/private/traces/batch", "spans": "/v1/private/spans/batch"}
API_KEY_ENV = "OPIK_API_KEY"
SEND_BODY_MAX_BYTES = 5 * 1024 * 1024  # opik 2.2.110 MAX_BATCH_SIZE_MB; no server limit is documented
SEND_TIMEOUT_MAX_S = 120
PROJECT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
WORKSPACE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
_ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def make_destination(project, workspace=None):
    """Opik destination: project name, optional workspace label. ``key`` enters every id."""
    if not isinstance(project, str) or not PROJECT_PATTERN.fullmatch(project):
        raise ExportError("Opik project must be 1-100 letters, digits, '_', '.' or '-', starting alphanumeric")
    if workspace is not None and (not isinstance(workspace, str) or not WORKSPACE_PATTERN.fullmatch(workspace)):
        raise ExportError("Opik workspace must be 1-100 letters, digits, '_' or '-', starting alphanumeric")
    return {"platform": "opik", "project": project, "workspace": workspace,
            "key": f"opik:{workspace or '-'}/{project}"}


def deterministic_uuid7(destination_key, scope, start):
    """UUIDv7 layout: 48-bit unix ms of ``start``, version 7, RFC 4122 variant, rest from a hash.

    Same destination, scope and start always give the same id; other destinations differ.
    """
    digest = hashlib.sha256(f"{EXPORTER}|{destination_key}|{scope}".encode("utf-8")).digest()
    millis = int(start.timestamp() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(digest[:2], "big") & 0x0FFF
    rand_b = int.from_bytes(digest[2:10], "big") & ((1 << 62) - 1)
    value = (millis << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime(_ISO)


@dataclass
class OpikPlan:
    destination: dict
    traces: list[dict] = field(default_factory=list)
    spans: list[dict] = field(default_factory=list)
    trace_kinds: dict = field(default_factory=dict)  # trace id -> provenance kind
    id_scopes: dict = field(default_factory=dict)  # trace/span id -> scope it was derived from (not sent)
    withheld: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    events: int = 0
    provenance_check: dict | None = None


def _event_metadata(event, origin, basis):
    metadata = common._metadata(event, origin, basis)
    metadata.update(tfg_exporter=EXPORTER, tfg_exporter_version=EXPORTER_VERSION)
    return metadata


def build_plan(events, project, *, workspace=None, provenance=None, provenance_check=None, include_untimed=False):
    """Same provenance contract as the LangSmith exporter: unknown unless declared; captured
    needs verified sink provenance records; synthetic markers only make it more conservative."""
    if provenance not in (None, "synthetic", "captured"):
        raise ExportError("provenance must be 'synthetic' or 'captured'")
    if provenance == "captured" and not (provenance_check and provenance_check["ok"]):
        raise ExportError("declared captured, but the capture provenance records do not verify")
    destination = make_destination(project, workspace)
    plan = OpikPlan(destination=destination, events=len(events), provenance_check=provenance_check)
    groups = {}
    for event in events:
        key = (("event", event["event_id"]) if event["turn_ref"] is None
               else ("turn", event["run_id"], event["session_ref"], event["turn_ref"]))
        groups.setdefault(key, []).append(event)
    for key, members in groups.items():
        origin = common._trace_provenance(members, provenance, provenance_check)
        prefix, kind_tag = common.TRACE_LABELS[origin["kind"]]
        tags = ["tfg-hermes-capture", f"schema:{capture.SCHEMA}", kind_tag]
        timed, points = [], []
        for event in sorted(members, key=lambda e: e["recorded_at_utc"]):
            interval = common._measured_interval(event, plan.warnings)
            if interval is None:
                metadata = _event_metadata(event, origin, "capture_recorded_at_point_not_an_interval")
                metadata["tfg_latency_measured"] = False
                common._check_strings(metadata, f"event {event['event_id']}")
                points.append({"name": f"tfg.{event['event_type']}", "time": event["recorded_at_utc"],
                               "metadata": metadata})
                continue
            metadata = _event_metadata(event, origin, "hermes_epochs")
            metadata["tfg_latency_measured"] = True
            common._check_strings(metadata, f"event {event['event_id']}")
            timed.append((event, interval, metadata))
        trace_scope = "trace|" + "|".join(str(part) for part in key)
        trace_meta = {
            "tfg_grouping": "derived_from_turn_ref" if key[0] == "turn" else "single_event_without_turn_ref",
            "tfg_observed_event": False, "tfg_run_id": members[0]["run_id"], "tfg_case_id": members[0]["case_id"],
            "tfg_session_ref": members[0]["session_ref"], "tfg_turn_ref": members[0]["turn_ref"],
            "tfg_data_kind": origin["kind"], "tfg_provenance_basis": origin["basis"],
            "tfg_timed_spans": len(timed), "tfg_point_events": points, "tfg_exporter": EXPORTER,
            "tfg_exporter_version": EXPORTER_VERSION, "tfg_cost": "not_computed",
            "tfg_point_event_time_basis": "capture_recorded_at_not_compared_with_hermes_epochs",
        }
        if timed:
            start = min(i[0] for _, i, _ in timed)
            end = max(i[1] for _, i, _ in timed)
            trace_meta.update(tfg_time_basis="derived_min_max_of_hermes_epochs", tfg_interval_derived=True,
                              tfg_interval_status="derived_from_measured_spans_only", tfg_latency_measured=False)
        elif include_untimed:
            start = end = common._utc(min(e["recorded_at_utc"] for e in members))
            trace_meta.update(tfg_time_basis="capture_recorded_at_marker", tfg_interval_derived=False,
                              tfg_interval_status="unknown_no_measured_interval", tfg_latency_measured=False)
            tags = [*tags, "interval-unknown", "latency-not-measured"]
            prefix = f"{prefix}[interval unknown] "
        else:
            plan.withheld.append({"events": len(members), "kind": origin["kind"], "reason": "no_measured_interval"})
            continue
        common._check_strings(trace_meta, "trace metadata")
        trace_id = deterministic_uuid7(destination["key"], trace_scope, start)
        plan.traces.append({"id": trace_id, "project_name": project, "name": f"{prefix}hermes_turn",
                            "start_time": _iso(start), "end_time": _iso(end), "metadata": trace_meta, "tags": tags})
        plan.trace_kinds[trace_id] = origin["kind"]
        plan.id_scopes[trace_id] = trace_scope
        for event, (span_start, span_end), metadata in timed:
            span_scope = f"span|{event['event_id']}"
            plan.id_scopes[deterministic_uuid7(destination["key"], span_scope, span_start)] = span_scope
            span = {"id": deterministic_uuid7(destination["key"], span_scope, span_start),
                    "trace_id": trace_id, "project_name": project, "type": "llm",
                    "name": f"{prefix}{event['event_type']}:{event.get('model') or 'unknown'}",
                    "start_time": _iso(span_start), "end_time": _iso(span_end), "metadata": metadata, "tags": tags}
            if event["event_type"] == "llm_error":
                span["error_info"] = {"exception_type": event.get("error_type") or "unknown_error",
                                      "message": f"status_code={event.get('status_code')}",
                                      "traceback": "not captured (metadata-only export)"}
            plan.spans.append(span)
    return plan


def check_export_allowed(plan, *, allow_synthetic=False, allow_unknown_provenance=False):
    """Gate any future send must pass: unknown origin and synthetic fixtures need explicit consent.

    Withheld traces count too: an input whose traces were all withheld must not pass as allowed."""
    if plan.errors:
        raise ExportError("input has validation errors")
    withheld = {w["kind"] for w in plan.withheld}
    kinds = set(plan.trace_kinds.values()) | withheld
    where = lambda kind: " (in withheld traces)" if kind in withheld and kind not in plan.trace_kinds.values() else ""
    if "synthetic_fixture" in kinds and not allow_synthetic:
        raise ExportError(f"plan contains synthetic traces{where('synthetic_fixture')}; "
                          "explicit synthetic authorization required")
    if "unknown_provenance" in kinds and not allow_unknown_provenance:
        raise ExportError(f"plan contains traces of unknown provenance{where('unknown_provenance')}; "
                          "declare provenance or authorize explicitly")


def batch_bodies(key, items):
    """Request bodies of 1..BATCH_MAX_ITEMS items each; none for an empty list."""
    return [{key: items[i:i + BATCH_MAX_ITEMS]} for i in range(0, len(items), BATCH_MAX_ITEMS)]


def describe(plan):
    kinds = list(plan.trace_kinds.values())
    blocked = []
    try:
        check_export_allowed(plan)
    except ExportError as exc:
        blocked.append(str(exc))
    return {
        "mode": "dry-run", "sent": False, "verification": PAYLOAD_VERIFICATION,
        "destination": {k: v for k, v in plan.destination.items() if k != "key"},
        "events": plan.events, "traces": len(plan.traces), "spans": len(plan.spans),
        "point_events": sum(len(t["metadata"]["tfg_point_events"]) for t in plan.traces),
        "synthetic_traces": kinds.count("synthetic_fixture"),
        "unknown_provenance_traces": kinds.count("unknown_provenance"),
        "captured_traces": kinds.count("captured_hermes_metadata"),
        "withheld_traces": plan.withheld, "blocked_for_future_send_by_default": blocked,
        "provenance_check": plan.provenance_check, "errors": plan.errors, "warnings": plan.warnings,
        "payload": {"traces_batches": batch_bodies("traces", plan.traces),
                    "spans_batches": batch_bodies("spans", plan.spans)},
        "note": "Nothing was sent. Metadata-only; token counters are Hermes-normalised; no cost, usage, "
                "model/provider or ttft at top level.",
    }


def validate_endpoint(url):
    """Explicit endpoints must be plain https base URLs: no credentials, query or fragment."""
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # raises on a malformed port
    except (ValueError, AttributeError):
        raise ExportError("Opik endpoint is not a valid URL") from None
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment or any(c.isspace() for c in url)):
        raise ExportError("Opik endpoint must be an https URL without credentials, query or fragment")
    return url.rstrip("/")


def send_requests(plan):
    """(kind, path, body bytes) for every non-empty body: traces first, spans after their traces."""
    requests = []
    for kind, items in (("traces", plan.traces), ("spans", plan.spans)):
        for body in batch_bodies(kind, items):
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(data) > SEND_BODY_MAX_BYTES:
                raise ExportError(f"a {kind} body is {len(data)} bytes, over {SEND_BODY_MAX_BYTES}; nothing sent")
            requests.append((kind, BATCH_PATHS[kind], data))
    return requests


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # reported as the HTTP response; never followed (it would carry the key elsewhere)


def urllib_transport(url, headers, body, timeout):
    """One POST, no retry, no redirect, no proxy from the environment. Returns only the HTTP status
    code and the response size (never its reason phrase, headers or body); raises on timeout or a
    lost/absent response."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            return {"status": response.status, "body_bytes": len(response.read())}
    except urllib.error.HTTPError as exc:
        with exc:
            return {"status": exc.code, "body_bytes": len(exc.read() or b"")}


class _SendRecord:
    """Append-only JSONL, created exclusively (never reused) and fsynced after every entry."""

    def __init__(self, path):
        self._handle = open(path, "x", encoding="utf-8")

    def write(self, entry):
        self._handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self):
        self._handle.close()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


_ERROR_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _response_result(response):
    """Keep only bounded fields from the transport: an int HTTP status and a byte count."""
    status = response.get("status") if isinstance(response, dict) else None
    body_bytes = response.get("body_bytes") if isinstance(response, dict) else None
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        return {"outcome": "invalid_transport_response_delivery_unknown", "http_status": None}
    if isinstance(body_bytes, bool) or not isinstance(body_bytes, int) or body_bytes < 0:
        body_bytes = None
    return {"outcome": "http_accepted" if 200 <= status < 300 else "http_not_accepted",
            "http_status": status, "response_body_bytes": body_bytes}


def _check_payload_matches_destination(plan):
    """The plan must be what build_plan would produce for its own destination."""
    destination = plan.destination
    if not destination.get("workspace"):
        raise ExportError("sending needs an explicit workspace")
    expected = make_destination(destination.get("project"), destination.get("workspace"))
    if destination != expected:
        raise ExportError("plan destination is not a valid Opik destination")
    trace_ids = [t.get("id") for t in plan.traces]
    span_ids = [s.get("id") for s in plan.spans]
    for value in trace_ids + span_ids:
        try:
            if uuid.UUID(value).version != 7 or str(uuid.UUID(value)) != value:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ExportError("plan contains an id that is not a canonical UUIDv7") from None
    if len(set(trace_ids)) != len(trace_ids) or len(set(span_ids)) != len(span_ids):
        raise ExportError("plan contains repeated trace or span ids")
    # Ids must come from the *current* destination: a plan built for another workspace or project
    # and re-pointed afterwards keeps the old ids and is refused.
    for prefix, items in (("trace|", plan.traces), ("span|", plan.spans)):
        for item in items:
            scope = plan.id_scopes.get(item["id"])
            try:
                start = common._utc(item["start_time"].replace("Z", "+00:00"))
                derived = deterministic_uuid7(destination["key"], scope, start) if scope else None
            except (AttributeError, TypeError, ValueError):
                derived = None
            if not (isinstance(scope, str) and scope.startswith(prefix)) or derived != item["id"]:
                raise ExportError("plan ids are not derived from the current destination and events; "
                                  "rebuild the plan for this workspace/project")
    if set(plan.trace_kinds) != set(trace_ids):
        raise ExportError("plan provenance does not cover exactly its traces")
    if any(item.get("project_name") != destination["project"] for item in plan.traces + plan.spans):
        raise ExportError("plan payload names a project other than its destination")
    if any(s.get("trace_id") not in plan.trace_kinds for s in plan.spans):
        raise ExportError("plan contains a span whose trace is not in the plan")


def _check_send_arguments(endpoint, api_key, timeout):
    endpoint = validate_endpoint(endpoint)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout)
            or not 0 < timeout <= SEND_TIMEOUT_MAX_S):
        raise ExportError(f"timeout must be a number in (0, {SEND_TIMEOUT_MAX_S}] seconds")
    if not isinstance(api_key, str) or not api_key or any(c.isspace() or not c.isprintable() for c in api_key):
        raise ExportError(f"{API_KEY_ENV} is not set or not a single-line value; nothing sent")
    if "*" in api_key and endpoint == OPIK_CLOUD_ENDPOINT:
        raise ExportError("this API key carries its own deployment URL (enhanced format), which this exporter "
                          "does not decode; pass --endpoint explicitly")
    return endpoint


def send(plan, *, endpoint, api_key, record_path, timeout, transport=urllib_transport,
         allow_synthetic=False, allow_unknown_provenance=False):
    """Send the plan's bodies once, in order, stopping at the first batch without a 2xx response.

    The caller supplies the key; ``send`` itself re-checks provenance, endpoint, timeout, key
    format and that the payload matches the plan's destination before creating the record or
    connecting. ``ALL_BATCHES_HTTP_ACCEPTED`` means every request got a 2xx: it does not prove
    storage or exactly-once delivery. ``UNCERTAIN`` covers a timeout or lost response, a non-2xx
    (possibly after partial processing), a partial send, and a record that could not be written
    after a POST. A batch whose intent could not be recorded is not sent. Nothing is resent
    automatically. Only the HTTP status code and response size are kept from the server."""
    check_export_allowed(plan, allow_synthetic=allow_synthetic, allow_unknown_provenance=allow_unknown_provenance)
    _check_payload_matches_destination(plan)
    endpoint = _check_send_arguments(endpoint, api_key, timeout)
    requests = send_requests(plan)
    if not requests:
        raise ExportError("nothing to send")
    headers = {"authorization": api_key, "Comet-Workspace": plan.destination["workspace"],
               "content-type": "application/json", "accept": "application/json"}
    try:
        record = _SendRecord(record_path)
    except FileExistsError:
        raise ExportError("record already exists; a send record is never reused or appended") from None
    except OSError as exc:
        raise ExportError(f"record cannot be created ({type(exc).__name__}); nothing sent") from None
    report = {"mode": "send", "endpoint": endpoint, "record": str(record_path),
              "destination": {k: v for k, v in plan.destination.items() if k != "key"},
              "traces": len(plan.traces), "spans": len(plan.spans), "batches_planned": len(requests),
              "batches": [], "status": None, "uncertain_reason": None, "not_attempted_batches": 0,
              "record_complete": True, "record_failure": None,
              "note": "No automatic retry. HTTP 2xx is not proof of storage or of exactly-once delivery; "
                      "ids are deterministic, and how Opik treats a repeated id is not verified."}

    def write(entry, stage):
        """False when the record could not be written durably; the report says where."""
        try:
            record.write(entry)
            return True
        except (OSError, ValueError) as exc:
            if report["record_complete"]:
                report.update(record_complete=False,
                              record_failure={"stage": stage, "error_type": type(exc).__name__})
            return False

    def stop(index, reason, attempted):
        report["status"] = "UNCERTAIN" if attempted or index else "NOT_SENT"
        report["uncertain_reason"] = reason + ("_after_earlier_accepted_batches" if index else "")
        report["not_attempted_batches"] = len(requests) - index - (1 if attempted else 0)

    try:
        if not write({"entry": "send_started", "at_utc": _utc_now(), "exporter": EXPORTER,
                      "exporter_version": EXPORTER_VERSION, "endpoint": endpoint,
                      "destination": report["destination"], "batches_planned": len(requests),
                      "trace_kinds": sorted(set(plan.trace_kinds.values()))}, "send_started"):
            stop(0, "record_unwritable_before_first_post", attempted=False)
            return report
        for index, (kind, path, data) in enumerate(requests):
            item_ids = [i["id"] for i in json.loads(data)[kind]]
            if not write({"entry": "batch_intent", "index": index, "kind": kind, "path": path,
                          "items": len(item_ids), "first_id": item_ids[0], "last_id": item_ids[-1],
                          "body_bytes": len(data), "body_sha256": hashlib.sha256(data).hexdigest(),
                          "at_utc": _utc_now()}, f"batch_intent_{index}"):
                stop(index, "record_unwritable_batch_not_sent", attempted=False)
                break
            started = time.monotonic()
            try:
                result = _response_result(transport(endpoint + path, dict(headers), data, timeout))
            except Exception as exc:  # timeout, reset, lost response: delivery unknown
                name = type(exc).__name__  # type only: messages may echo request or server details
                result = {"outcome": "no_response_delivery_unknown", "http_status": None,
                          "error_type": name if _ERROR_TYPE.fullmatch(name) else "unrecognized"}
            result.update(index=index, kind=kind, items=len(item_ids),
                          elapsed_wall_s=round(time.monotonic() - started, 3))
            result["recorded"] = write({"entry": "batch_result", "at_utc": _utc_now(), **result},
                                       f"batch_result_{index}")
            report["batches"].append(result)
            if not result["recorded"]:
                stop(index, "record_unwritable_after_post", attempted=True)
                break
            if result["outcome"] != "http_accepted":
                stop(index, "no_response_after_sending" if result["http_status"] is None
                     else f"http_status_{result['http_status']}", attempted=True)
                break
        else:
            report["status"] = "ALL_BATCHES_HTTP_ACCEPTED"
        if report["record_complete"]:
            write({"entry": "send_finished", "at_utc": _utc_now(), "status": report["status"],
                   "uncertain_reason": report["uncertain_reason"],
                   "not_attempted_batches": report["not_attempted_batches"]}, "send_finished")
    finally:
        try:
            record.close()
        except (OSError, ValueError) as exc:
            if report["record_complete"]:
                report.update(record_complete=False, record_failure={"stage": "close",
                                                                     "error_type": type(exc).__name__})
        # HTTP facts stay separate from the aggregate, which never claims more than the record holds.
        report["http_statuses_received"] = [b["http_status"] for b in report["batches"]
                                            if b["http_status"] is not None]
        report["http_accepted_batches"] = sum(b["outcome"] == "http_accepted" for b in report["batches"])
        if report["status"] == "ALL_BATCHES_HTTP_ACCEPTED" and not report["record_complete"]:
            report["status"] = "UNCERTAIN"
            report["uncertain_reason"] = (f"record_{report['record_failure']['stage']}_failed_"
                                          "after_all_batches_http_accepted")
    return report


def main(argv=None, *, out=None, transport=urllib_transport, environ=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", help="capture JSONL files (tfg.hermes.capture/3)")
    parser.add_argument("--project", required=True, help="target Opik project name")
    parser.add_argument("--workspace", help="Opik workspace label (enters ids; never read from env)")
    parser.add_argument("--provenance", choices=("synthetic", "captured"),
                        help="declare the input's origin; 'captured' also needs verified sink provenance records")
    parser.add_argument("--include-untimed", action="store_true",
                        help="also build traces without any measured interval, tagged interval-unknown")
    send_group = parser.add_argument_group("send (only with --send; the default is an offline dry-run)")
    send_group.add_argument("--send", action="store_true", help="actually POST the batches to Opik")
    send_group.add_argument("--record", help="new JSONL file for the per-batch send record (must not exist)")
    send_group.add_argument("--endpoint", help=f"Opik API base URL (https); default {OPIK_CLOUD_ENDPOINT}")
    send_group.add_argument("--timeout", type=float, help=f"per-request timeout in seconds, 0-{SEND_TIMEOUT_MAX_S}")
    send_group.add_argument("--allow-synthetic", action="store_true", help="authorize sending synthetic traces")
    send_group.add_argument("--allow-unknown-provenance", action="store_true",
                            help="authorize sending traces whose origin is not declared")
    args = parser.parse_args(argv)
    send_only = [name for name in ("record", "endpoint", "timeout", "allow_synthetic", "allow_unknown_provenance")
                 if getattr(args, name) not in (None, False)]
    if send_only and not args.send:
        parser.error(f"--{send_only[0].replace('_', '-')} is only valid with --send")
    if args.send:
        if not args.workspace:
            parser.error("--send requires an explicit --workspace")
        if not args.record:
            parser.error("--send requires --record (a new file for the per-batch record)")
        if args.timeout is not None and not 0 < args.timeout <= SEND_TIMEOUT_MAX_S:
            parser.error(f"--timeout must be in (0, {SEND_TIMEOUT_MAX_S}]")
    events, errors = common.load_events(args.files)
    check = common.verify_capture_provenance(args.files) if args.provenance == "captured" else None
    if events or not errors:
        plan = build_plan(events, args.project, workspace=args.workspace, provenance=args.provenance,
                          provenance_check=check, include_untimed=args.include_untimed)
    else:
        plan = OpikPlan(destination=make_destination(args.project, args.workspace))
    plan.errors.extend(errors)
    if not args.send:
        json.dump(describe(plan), out, indent=2, ensure_ascii=False)
        out.write("\n")
        return 1 if plan.errors else 0
    # main checks endpoint, provenance (withheld traces included), bodies and the record path before
    # reading the key; send() re-checks all of it plus the key format before creating anything.
    endpoint = validate_endpoint(args.endpoint) if args.endpoint else OPIK_CLOUD_ENDPOINT
    check_export_allowed(plan, allow_synthetic=args.allow_synthetic,
                         allow_unknown_provenance=args.allow_unknown_provenance)
    requests = send_requests(plan)
    if not requests:
        json.dump({"mode": "send", "status": "NOTHING_TO_SEND", "connected": False,
                   "withheld_traces": plan.withheld}, out, indent=2)
        out.write("\n")
        return 0
    if os.path.lexists(args.record):
        raise ExportError("--record already exists; a send record is never reused or appended")
    api_key = (os.environ if environ is None else environ).get(API_KEY_ENV)
    report = send(plan, endpoint=endpoint, api_key=api_key, record_path=args.record,
                  timeout=args.timeout or 30.0, transport=transport, allow_synthetic=args.allow_synthetic,
                  allow_unknown_provenance=args.allow_unknown_provenance)
    json.dump(report, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return 0 if report["status"] == "ALL_BATCHES_HTTP_ACCEPTED" and report["record_complete"] else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExportError as exc:
        print(f"opik_export: {exc}", file=sys.stderr)
        sys.exit(2)
