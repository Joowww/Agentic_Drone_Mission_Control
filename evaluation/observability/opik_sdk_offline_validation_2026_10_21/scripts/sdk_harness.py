"""Runs with the THROWAWAY opik venv. Validates dry-run payloads against opik's REST models and
compares serialization through httpx.MockTransport. Network is denied before opik is imported."""
import socket


def _deny(*args, **kwargs):
    raise AssertionError("network attempted")


socket.socket.connect = _deny
socket.socket.connect_ex = _deny
socket.create_connection = _deny
socket.getaddrinfo = _deny

import datetime as dt  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
import sys  # noqa: E402
import typing  # noqa: E402
import uuid  # noqa: E402

assert not any(k.startswith(("OPIK_API_KEY", "COMET_API_KEY")) for k in os.environ), "credentials in env"

import httpx  # noqa: E402
import opik  # noqa: E402
from opik.message_processing import messages  # noqa: E402
from opik.message_processing.batching import batchers, batch_manager_constuctors as bmc  # noqa: E402
from opik.rest_api import OpikApi  # noqa: E402
from opik.rest_api.types import error_info_write, span_write, span_write_type, trace_write  # noqa: E402

BASE = "http://opik.invalid/api"
report = {"opik_version": opik.__version__, "cases": {}}
captured = []


def handler(request):
    assert request.url.host == "opik.invalid"
    assert "authorization" not in request.headers and "comet-workspace" not in request.headers
    captured.append({"method": request.method, "path": request.url.path, "json": json.loads(request.content)})
    return httpx.Response(204)


api = OpikApi(base_url=BASE, httpx_client=httpx.Client(transport=httpx.MockTransport(handler)))


def parse_time(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize(item):
    """Datetimes compared as instants: SDK uses isoformat(), exporter a fixed %f."""
    return {k: (parse_time(v).isoformat() if k in ("start_time", "end_time") else v) for k, v in item.items()}


def check_items(kind, items, model):
    problems = []
    fields = set(model.model_fields)
    for item in items:
        unknown = set(item) - fields
        if unknown:
            problems.append(f"{kind} {item.get('id')}: keys not in {model.__name__}: {sorted(unknown)}")
        model.model_validate(item)  # raises on type errors
        if item.get("error_info") is not None:
            error_info_write.ErrorInfoWrite.model_validate(item["error_info"])
            extra = set(item["error_info"]) - set(error_info_write.ErrorInfoWrite.model_fields)
            if extra:
                problems.append(f"{kind} error_info extra keys {sorted(extra)}")
        # Fern enums are Union[Literal[...], Any]: pydantic accepts anything, so check the literal set
        literals = {v for arg in typing.get_args(span_write_type.SpanWriteType) for v in typing.get_args(arg)}
        assert literals == {"general", "tool", "llm", "guardrail"}, literals
        if kind == "span" and item.get("type") not in literals:
            problems.append(f"span type {item.get('type')!r} not in SpanWriteType")
        if uuid.UUID(item["id"]).version != 7:
            problems.append(f"{kind} id not UUIDv7")
        if len(item.get("tags") or []) != len(set(item.get("tags") or [])):
            problems.append(f"{kind} duplicate tags")
    return problems


def via_rest(body_key, bodies, model, send):
    out = []
    for body in bodies:
        captured.clear()
        send([model(**item) for item in body[body_key]])
        (request,) = captured
        assert request["method"] == "POST"
        out.append(request)
    return out


def via_sdk_messages(traces, spans):
    """The SDK's own path: Create*Message -> batcher (as_payload_dict, encode) -> REST client."""
    flushed = []
    tb = batchers.CreateTraceMessageBatcher(flush_callback=flushed.append, flush_interval_seconds=1,
                                            max_batch_size=bmc.CREATE_TRACES_MESSAGE_BATCHER_MAX_BATCH_SIZE)
    sb = batchers.CreateSpanMessageBatcher(flush_callback=flushed.append, flush_interval_seconds=1,
                                           max_batch_size=bmc.CREATE_SPANS_MESSAGE_BATCHER_MAX_BATCH_SIZE)
    for t in traces:
        tb.add(messages.CreateTraceMessage(
            trace_id=t["id"], project_name=t["project_name"], name=t["name"],
            start_time=parse_time(t["start_time"]), end_time=parse_time(t["end_time"]), input=None, output=None,
            metadata=t["metadata"], tags=t["tags"], error_info=t.get("error_info"), thread_id=None,
            last_updated_at=None, source="sdk"))
    for s in spans:
        sb.add(messages.CreateSpanMessage(
            span_id=s["id"], trace_id=s["trace_id"], project_name=s["project_name"], parent_span_id=None,
            name=s["name"], start_time=parse_time(s["start_time"]), end_time=parse_time(s["end_time"]),
            input=None, output=None, metadata=s["metadata"], tags=s["tags"], type=s["type"], usage=None,
            model=None, provider=None, error_info=s.get("error_info"), total_cost=None, last_updated_at=None,
            source="sdk"))
    tb.flush()
    sb.flush()
    requests = []
    for batch in flushed:
        captured.clear()
        if isinstance(batch, messages.CreateTraceBatchMessage):
            api.traces.create_traces(traces=batch.batch)
        else:
            api.spans.create_spans(spans=batch.batch)
        requests.extend(captured)
    return requests


for path in sorted(Path(sys.argv[1]).glob("*.json")):
    out = json.loads(path.read_text())
    payload = out["payload"]
    traces = [t for b in payload["traces_batches"] for t in b["traces"]]
    spans = [s for b in payload["spans_batches"] for s in b["spans"]]
    case = {"traces": len(traces), "spans": len(spans), "problems": []}
    for key, bodies in (("traces", payload["traces_batches"]), ("spans", payload["spans_batches"])):
        for body in bodies:
            if set(body) != {key} or not 1 <= len(body[key]) <= 1000:
                case["problems"].append(f"{key} body shape/size {sorted(body)} {len(body.get(key, []))}")
    case["problems"] += check_items("trace", traces, trace_write.TraceWrite)
    case["problems"] += check_items("span", spans, span_write.SpanWrite)

    rest_t = via_rest("traces", payload["traces_batches"], trace_write.TraceWrite,
                      lambda items: api.traces.create_traces(traces=items))
    rest_s = via_rest("spans", payload["spans_batches"], span_write.SpanWrite,
                      lambda items: api.spans.create_spans(spans=items))
    case["rest_paths"] = sorted({r["path"] for r in rest_t + rest_s})
    rest_bodies = {"traces": [i for r in rest_t for i in r["json"]["traces"]],
                   "spans": [i for r in rest_s for i in r["json"]["spans"]]}
    for key, ours in (("traces", traces), ("spans", spans)):
        if [normalize(i) for i in rest_bodies[key]] != [normalize(i) for i in ours]:
            case["problems"].append(f"REST client serialization of {key} differs from exporter body")
    case["time_strings_differ_only_in_format"] = sorted({
        f"{a[k]} vs {b[k]}" for key, ours in (("traces", traces), ("spans", spans))
        for a, b in zip(ours, rest_bodies[key]) for k in ("start_time", "end_time") if a[k] != b[k]})[:2]

    sdk = via_sdk_messages(traces, spans)
    sdk_items = {"traces": [i for r in sdk if r["path"].endswith("/traces/batch") for i in r["json"]["traces"]],
                 "spans": [i for r in sdk if r["path"].endswith("/spans/batch") for i in r["json"]["spans"]]}
    diffs = []
    for key, ours in (("traces", traces), ("spans", spans)):
        for a, b in zip(ours, sorted(sdk_items[key], key=lambda i: [x["id"] for x in ours].index(i["id"]))):
            na, nb = normalize(a), normalize(b)
            only_sdk = {k: nb[k] for k in set(nb) - set(na)}
            only_ours = sorted(set(na) - set(nb))
            changed = sorted(k for k in set(na) & set(nb) if na[k] != nb[k])
            if only_sdk or only_ours or changed:
                diffs.append({"kind": key, "only_sdk": only_sdk, "only_exporter": only_ours, "changed": changed})
        if len(sdk_items[key]) != len(ours):
            case["problems"].append(f"SDK path produced {len(sdk_items[key])} {key}, exporter {len(ours)}")
    case["sdk_path_requests"] = len(sdk)
    case["sdk_path_differences"] = sorted({json.dumps(d, sort_keys=True) for d in diffs})
    report["cases"][path.stem] = case

json.dump(report, sys.stdout, indent=1)
print()
sys.exit(1 if any(c["problems"] for c in report["cases"].values()) else 0)
