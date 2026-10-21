"""Offline tests for the Opik dry-run exporter: fixtures only, no SDK, network or credentials."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from observability import langsmith_export as ls_export
from observability import opik_export as export
from observability.hermes_capture import capture

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_EVIDENCE = (ROOT / "evaluation" / "observability" / "hermes_loader_hooks_synthetic_2026_10_20"
                      / "capture" / "hermes-events-2026-10-20.jsonl")
SECRET = "sk-ant-THISISAFAKEKEY0123456789abcdef"
CONTENT = "PROMPT-TEXT Parcela HOME 41.27531, 1.98712"
PATH = "/home/joelm/TFG/Agentic_Drone_Mission_Control/missions/generated/drafts/x/draft.json"


def _summary(**counters):
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "reasoning_tokens": 0, "request_count": 1}
    base.update(counters)
    base["prompt_tokens"] = base["input_tokens"] + base["cache_read_tokens"] + base["cache_write_tokens"]
    base["total_tokens"] = base["prompt_tokens"] + base["output_tokens"]
    return base


def llm_kwargs(**override):
    kwargs = dict(session_id="raw-session-1", task_id="raw-task-1", turn_id="raw-turn-1",
                  api_request_id="raw-turn-1:api:1", provider="custom", model="qwen3:4b", response_model="qwen3:4b",
                  base_url=f"http://127.0.0.1:11434/v1?key={SECRET}", api_mode="chat_completions",
                  finish_reason="tool_calls", api_duration=1.25, started_at=1792500000.0, ended_at=1792500001.25,
                  first_chunk_at=1792500000.4, api_call_count=1, message_count=3, assistant_tool_call_count=1,
                  context_length=65536, usage=_summary(input_tokens=37, output_tokens=2),
                  response={"assistant_message": {"content": CONTENT, "tool_calls": [
                      {"function": {"name": "mcp_tfg_get_mission_state",
                                    "arguments": json.dumps({"path": PATH})}}]}})
    kwargs.update(override)
    return kwargs


def tool_kwargs(**override):
    kwargs = dict(tool_name="mcp_tfg_get_mission_state", args={"path": PATH, "home": CONTENT},
                  result=json.dumps({"draft": CONTENT, "secret": SECRET}), session_id="raw-session-1",
                  task_id="raw-task-1", tool_call_id="raw-call-1", turn_id="raw-turn-1",
                  api_request_id="raw-turn-1:api:1", duration_ms=742, status="ok")
    kwargs.update(override)
    return kwargs


def error_kwargs(**override):
    kwargs = dict(session_id="raw-session-1", task_id="raw-task-1", turn_id="raw-turn-1",
                  api_request_id="raw-turn-1:api:2", provider="custom", model="qwen3:4b",
                  api_mode="chat_completions", api_duration=3.0, started_at=1792500002.0, ended_at=1792500005.0,
                  api_call_count=2, status_code=429, retry_count=1, max_retries=3, retryable=True,
                  reason="rate_limited", error={"type": "RateLimitError", "message": f"Bearer {SECRET} {CONTENT}"},
                  request={"body": {"messages": [{"content": CONTENT}], "api_key": SECRET}})
    kwargs.update(override)
    return kwargs


def hermes_like_context():
    """Type name matches Hermes' PluginContext: simulates the sink's only origin signal."""
    cls = type("PluginContext", (), {"register_hook": lambda self, name, cb: None})
    cls.__module__ = "hermes_cli.plugins"
    return cls()


class OtherContext:
    def register_hook(self, name, callback):
        pass


def capture_with(tmp_path, ctx, *, run_id="run-2026-10-21", case_id="smoke", tool=True, error=False):
    directory = tmp_path / "capture"
    sink = capture.register(ctx, environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory),
                                          capture.RUN_ENV: run_id, capture.CASE_ENV: case_id})
    sink.on_post_api_request(**llm_kwargs())
    if tool:
        sink.on_post_tool_call(**tool_kwargs())
    if error:
        sink.on_api_request_error(**error_kwargs())
    (path,) = directory.glob("hermes-events-*.jsonl")
    return path


def plan_from(path, project="tfg-opik", **options):
    events, errors = ls_export.load_events([path])
    assert errors == []
    if options.get("provenance") == "captured":
        options["provenance_check"] = ls_export.verify_capture_provenance([path])
    return export.build_plan(events, project, **options)


def dumped(plan):
    return json.dumps(export.describe(plan)["payload"])


# --- provenance ----------------------------------------------------------------------------

def test_validated_real_capture_is_captured_and_exportable(tmp_path):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    plan = plan_from(path, provenance="captured")
    assert list(plan.trace_kinds.values()) == ["captured_hermes_metadata"]
    export.check_export_allowed(plan)  # no override needed
    trace = plan.traces[0]
    assert trace["metadata"]["tfg_provenance_basis"] == "declared_captured_with_hermes_sink_provenance_record"
    assert "captured-metadata" in trace["tags"] and not trace["name"].startswith(("SYNTHETIC", "UNKNOWN"))
    assert export.describe(plan)["blocked_for_future_send_by_default"] == []


def test_undeclared_capture_is_unknown_and_blocked_even_with_valid_records(tmp_path):
    path = capture_with(tmp_path, hermes_like_context())
    plan = plan_from(path)
    assert list(plan.trace_kinds.values()) == ["unknown_provenance"]
    assert plan.traces[0]["name"].startswith("UNKNOWN-PROVENANCE · ")
    with pytest.raises(ls_export.ExportError, match="unknown provenance"):
        export.check_export_allowed(plan)
    export.check_export_allowed(plan, allow_unknown_provenance=True)
    assert export.describe(plan)["blocked_for_future_send_by_default"]


def test_synthetic_fixtures_need_explicit_authorization(tmp_path):
    events, errors = ls_export.load_events([SYNTHETIC_EVIDENCE])
    assert errors == []
    plan = export.build_plan(events, "tfg-opik")
    assert set(plan.trace_kinds.values()) == {"synthetic_fixture"}
    assert all(t["name"].startswith("SYNTHETIC · ") and "synthetic" in t["tags"] for t in plan.traces)
    with pytest.raises(ls_export.ExportError, match="synthetic"):
        export.check_export_allowed(plan)
    export.check_export_allowed(plan, allow_synthetic=True)
    path = capture_with(tmp_path, hermes_like_context())
    declared = plan_from(path, provenance="synthetic")
    assert declared.traces[0]["metadata"]["tfg_provenance_basis"] == "declared_synthetic"


def test_names_are_not_trusted_and_synthetic_marker_conflicts_with_captured(tmp_path):
    path = capture_with(tmp_path, hermes_like_context(), run_id="SYNTHETIC-loader", case_id="x")
    assert set(plan_from(path).trace_kinds.values()) == {"synthetic_fixture"}
    with pytest.raises(ls_export.ExportError, match="synthetic marker"):
        plan_from(path, provenance="captured")


@pytest.mark.parametrize("case", ["no_record", "non_hermes_context", "record_after_events"])
def test_invalid_provenance_records_refuse_a_captured_declaration(tmp_path, case):
    if case == "no_record":
        path = tmp_path / "events.jsonl"
        path.write_text(json.dumps(capture.llm_call_event(llm_kwargs(), {})) + "\n", encoding="utf-8")
    else:
        path = capture_with(tmp_path, OtherContext() if case == "non_hermes_context" else hermes_like_context())
        if case == "record_after_events":
            (record,) = path.parent.glob("capture-provenance-*.json")
            data = json.loads(record.read_text())
            data["created_at_utc"] = "2099-01-01T00:00:00+00:00"
            record.write_text(json.dumps(data))
    with pytest.raises(ls_export.ExportError, match="do not verify"):
        plan_from(path, provenance="captured")


# --- content, timing, ids -----------------------------------------------------------------

def test_payload_excludes_content_arguments_secrets_paths_and_raw_ids(tmp_path):
    plan = plan_from(capture_with(tmp_path, hermes_like_context(), error=True), provenance="captured")
    blob = dumped(plan)
    for sentinel in (CONTENT, "PROMPT-TEXT", "Parcela", "41.27531", PATH, "/home/", SECRET, "Bearer", "api_key",
                     "127.0.0.1", "raw-session-1", "raw-turn-1", "raw-call-1", "raw-task-1"):
        assert sentinel not in blob
    for span in plan.spans + plan.traces:
        assert "input" not in span and "output" not in span


def test_secret_like_value_accepted_by_schema_is_refused(tmp_path):
    event = capture.llm_call_event(llm_kwargs(), {})
    event["model"] = "AKIAABCDEFGHIJKLMNOP"
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    events, errors = ls_export.load_events([path])
    assert errors == []
    with pytest.raises(ls_export.ExportError, match="secret"):
        export.build_plan(events, "tfg-opik")


def test_no_top_level_usage_model_provider_cost_or_ttft_and_tokens_keep_status(tmp_path):
    plan = plan_from(capture_with(tmp_path, hermes_like_context(), tool=False), provenance="captured")
    (span,) = plan.spans
    for key in ("usage", "model", "provider", "total_estimated_cost", "total_estimated_cost_version", "ttft"):
        assert key not in span
    meta = span["metadata"]
    assert meta["tfg_usage"]["input_tokens"] == {"value": 37, "status": "nonzero_normalized"}
    assert meta["tfg_usage"]["reasoning_tokens"] == {"value": 0, "status": "zero_unconfirmed"}
    assert meta["tfg_usage"]["total_tokens"] == {"value": 39, "status": "derived_nonzero"}
    assert meta["tfg_cost"] == "not_computed" and meta["tfg_exporter"] == "tfg-opik-offline"
    assert (meta["tfg_provider"], meta["tfg_model"]) == ("custom", "qwen3:4b")


def test_usage_absent_stays_null(tmp_path):
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_api_request(**llm_kwargs(usage=None))
    (path,) = directory.glob("hermes-events-*.jsonl")
    (span,) = plan_from(path, provenance="captured").spans
    assert span["metadata"]["tfg_usage"] is None and span["metadata"]["tfg_usage_source"] == "absent"


def test_spans_use_hermes_epochs_and_tools_are_point_events_without_duration(tmp_path):
    plan = plan_from(capture_with(tmp_path, hermes_like_context(), error=True), provenance="captured")
    (trace,) = plan.traces
    assert [s["type"] for s in plan.spans] == ["llm", "llm"]  # no tool span
    llm, error = plan.spans
    from datetime import datetime, timezone
    hermes_iso = lambda epoch: datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert (llm["start_time"], llm["end_time"]) == (hermes_iso(1792500000.0), hermes_iso(1792500001.25))
    assert (error["start_time"], error["end_time"]) == (hermes_iso(1792500002.0), hermes_iso(1792500005.0))
    assert trace["start_time"] == llm["start_time"] and trace["end_time"] == error["end_time"]
    assert trace["metadata"]["tfg_time_basis"] == "derived_min_max_of_hermes_epochs"
    (point,) = trace["metadata"]["tfg_point_events"]
    assert point["name"] == "tfg.tool_call" and set(point) == {"name", "time", "metadata"}
    assert point["metadata"]["tfg_latency_measured"] is False
    assert point["metadata"]["tfg_time_basis"] == "capture_recorded_at_point_not_an_interval"
    assert point["metadata"]["tfg_duration_ms_received"] == 742 and point["metadata"]["tfg_units"]["duration_ms_measured"] == "ms"
    assert error["error_info"] == {"exception_type": "RateLimitError", "message": "status_code=429",
                                   "traceback": "not captured (metadata-only export)"}
    assert llm["metadata"]["tfg_first_chunk_offset_s"] is not None and "ttft" not in llm


def test_trace_without_measured_interval_is_withheld_unless_included(tmp_path):
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (path,) = directory.glob("hermes-events-*.jsonl")
    plan = plan_from(path, provenance="captured")
    assert plan.traces == [] and plan.withheld[0]["reason"] == "no_measured_interval"
    included = plan_from(path, provenance="captured", include_untimed=True)
    (trace,) = included.traces
    assert trace["start_time"] == trace["end_time"] and "interval-unknown" in trace["tags"]
    assert trace["metadata"]["tfg_interval_status"] == "unknown_no_measured_interval"


@pytest.mark.parametrize("declared, kind, match", [(None, "unknown_provenance", "unknown provenance"),
                                                   ("synthetic", "synthetic_fixture", "synthetic")])
def test_withheld_only_plan_is_not_allowed_and_summary_says_why(tmp_path, declared, kind, match):
    # Every trace withheld (no measured interval): the gate must still see the input's provenance.
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (path,) = directory.glob("hermes-events-*.jsonl")
    plan = plan_from(path, provenance=declared)
    assert plan.traces == [] and plan.withheld[0]["kind"] == kind
    with pytest.raises(ls_export.ExportError, match=f"{match}.*in withheld traces"):
        export.check_export_allowed(plan)
    export.check_export_allowed(plan, allow_synthetic=True, allow_unknown_provenance=True)
    out = export.describe(plan)
    assert out["traces"] == 0 and out["withheld_traces"][0]["kind"] == kind
    assert any("in withheld traces" in reason for reason in out["blocked_for_future_send_by_default"])


def test_withheld_captured_plan_stays_allowed(tmp_path):
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (path,) = directory.glob("hermes-events-*.jsonl")
    plan = plan_from(path, provenance="captured")
    assert plan.traces == [] and plan.withheld[0]["kind"] == "captured_hermes_metadata"
    export.check_export_allowed(plan)
    assert export.describe(plan)["blocked_for_future_send_by_default"] == []


def test_batch_bodies_respect_opik_min_and_max_items(tmp_path):
    # OpenAPI comet-ml/opik@6ff71e2: TraceBatch_Write.traces and SpanBatch_Write.spans are
    # minItems 1, maxItems 1000. An empty list must yield no body, a long one several bodies.
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (path,) = directory.glob("hermes-events-*.jsonl")
    withheld = export.describe(plan_from(path, provenance="captured"))["payload"]
    assert withheld == {"traces_batches": [], "spans_batches": []}
    untimed = export.describe(plan_from(path, provenance="captured", include_untimed=True))["payload"]
    assert [len(b["traces"]) for b in untimed["traces_batches"]] == [1] and untimed["spans_batches"] == []
    spans = [{"id": str(i)} for i in range(export.BATCH_MAX_ITEMS + 1)]
    bodies = export.batch_bodies("spans", spans)
    assert [len(b["spans"]) for b in bodies] == [1000, 1]
    assert [s for b in bodies for s in b["spans"]] == spans


def test_invalid_or_naive_timestamps_are_rejected(tmp_path):
    event = capture.llm_call_event(llm_kwargs(), {})
    for value in ("not-a-timestamp", "2026-10-21T08:00:00"):
        event["recorded_at_utc"] = value
        path = tmp_path / "events.jsonl"
        path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        events, errors = ls_export.load_events([path])
        assert events == [] and "recorded_at_utc" in errors[0]


def test_ids_are_deterministic_uuid7_layout_and_separated_by_destination(tmp_path):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    plan = plan_from(path, provenance="captured")
    again = plan_from(path, provenance="captured")
    other_project = plan_from(path, project="tfg-opik-2", provenance="captured")
    other_workspace = plan_from(path, provenance="captured", workspace="team-b")
    ids = [x["id"] for x in plan.traces + plan.spans]
    assert ids == [x["id"] for x in again.traces + again.spans]
    for other in (other_project, other_workspace):
        assert not set(ids) & {x["id"] for x in other.traces + other.spans}
    for record in plan.traces + plan.spans:
        value = uuid.UUID(record["id"])
        assert value.version == 7 and value.variant == uuid.RFC_4122
        start_ms = int(ls_export._utc(record["start_time"].replace("Z", "+00:00")).timestamp() * 1000)
        assert value.int >> 80 == start_ms
    langsmith_ids = {r["id"] for r in ls_export.build_plan(ls_export.load_events([path])[0], project="tfg-opik",
                                                         provenance="captured",
                                                         provenance_check=ls_export.verify_capture_provenance([path])).runs}
    assert not set(ids) & langsmith_ids
    assert all(s["trace_id"] == plan.traces[0]["id"] for s in plan.spans)


@pytest.mark.parametrize("project, workspace", [("", None), ("bad project", None), ("../x", None), ("ok", "a/b")])
def test_destination_is_validated(project, workspace):
    with pytest.raises(ls_export.ExportError):
        export.make_destination(project, workspace)


# --- dry-run isolation ---------------------------------------------------------------------

def test_dry_run_has_no_network_credentials_sdk_or_ledger(tmp_path):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    code = (
        "import os, socket, sys\n"
        "def deny(*a, **k): raise AssertionError('network used in dry-run')\n"
        "socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny\n"
        "class Env(dict):\n"
        "    def get(self, k, d=None):\n"
        "        assert not k.startswith(('OPIK', 'COMET', 'LANGSMITH')), 'credential env read: ' + k\n"
        "        return super().get(k, d)\n"
        "    def __getitem__(self, k):\n"
        "        assert not k.startswith(('OPIK', 'COMET', 'LANGSMITH')), 'credential env read: ' + k\n"
        "        return super().__getitem__(k)\n"
        "os.environ = Env(os.environ)\n"
        "from observability import opik_export as e\n"
        f"rc = e.main([{str(path)!r}, '--project', 'tfg-opik', '--provenance', 'captured'])\n"
        "assert not any(m == 'opik' or m.startswith('opik.') for m in sys.modules), 'opik imported'\n"
        "assert 'langsmith' not in sys.modules, 'langsmith imported'\n"
        "sys.exit(rc)\n"
    )
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT), "OPIK_API_KEY": SECRET, "COMET_API_KEY": SECRET}
    before = sorted(p.name for p in tmp_path.rglob("*"))
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    assert sorted(p.name for p in tmp_path.rglob("*")) == before  # no ledger or other file written
    out = json.loads(done.stdout)
    assert out["sent"] is False and out["verification"].startswith("UNVERIFIED_AGAINST_OPIK_SERVICE")
    assert out["captured_traces"] == 1 and out["spans"] == 2 and out["point_events"] == 1
    assert SECRET not in done.stdout + done.stderr


def test_cli_reports_invalid_input_and_send_needs_explicit_destination(tmp_path, capsys):
    path = tmp_path / "bad.jsonl"
    path.write_text("{oops\n", encoding="utf-8")
    assert export.main([str(path), "--project", "tfg-opik"]) == 1
    assert json.loads(capsys.readouterr().out)["errors"]
    with pytest.raises(SystemExit):
        export.main([str(path), "--project", "tfg-opik", "--send"])
    capsys.readouterr()


# --- explicit send path (fake transport only: never the network) ----------------------------

KEY = "opik-test-key-NOT-REAL-0123456789"


class FakeTransport:
    """Scripted responses: an int is an HTTP status, an exception class is raised as is."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        step = self.script.pop(0) if self.script else 204
        if isinstance(step, type) and issubclass(step, BaseException):
            raise step("simulated")
        return {"status": step, "reason": "scripted", "body_bytes": 0}


def send_argv(path, tmp_path, *extra, provenance="captured"):
    argv = [str(path), "--project", "tfg-opik", "--workspace", "tfg-ws", "--send",
            "--record", str(tmp_path / "send-record.jsonl")]
    return argv + (["--provenance", provenance] if provenance else []) + list(extra)


def records(tmp_path):
    return [json.loads(line) for line in (tmp_path / "send-record.jsonl").read_text().splitlines()]


def test_send_posts_each_non_empty_batch_once_with_documented_headers(tmp_path, capsys):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    transport = FakeTransport()
    rc = export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY})
    out = capsys.readouterr().out
    report = json.loads(out)
    assert rc == 0 and report["status"] == "ALL_BATCHES_HTTP_ACCEPTED"
    assert [c["url"] for c in transport.calls] == ["https://www.comet.com/opik/api/v1/private/traces/batch",
                                                   "https://www.comet.com/opik/api/v1/private/spans/batch"]
    for call in transport.calls:
        assert call["headers"]["authorization"] == KEY and call["headers"]["Comet-Workspace"] == "tfg-ws"
        assert call["timeout"] == 30.0
    dry = export.describe(plan_from(path, provenance="captured", workspace="tfg-ws"))["payload"]
    assert [c["body"] for c in transport.calls] == dry["traces_batches"] + dry["spans_batches"]
    assert [b["http_status"] for b in report["batches"]] == [204, 204]
    entries = records(tmp_path)
    assert [e["entry"] for e in entries] == ["send_started", "batch_intent", "batch_result",
                                             "batch_intent", "batch_result", "send_finished"]
    assert KEY not in out and KEY not in (tmp_path / "send-record.jsonl").read_text()


@pytest.mark.parametrize("script, reason, results", [
    ((TimeoutError,), "no_response_after_sending", ["no_response_delivery_unknown"]),
    ((ConnectionResetError,), "no_response_after_sending", ["no_response_delivery_unknown"]),
    ((500,), "http_status_500", ["http_not_accepted"]),
    ((204, TimeoutError), "no_response_after_sending_after_earlier_accepted_batches",
     ["http_accepted", "no_response_delivery_unknown"]),
    ((204, 409), "http_status_409_after_earlier_accepted_batches", ["http_accepted", "http_not_accepted"]),
])
def test_timeout_lost_response_or_partial_send_is_uncertain_and_never_retried(tmp_path, capsys, script, reason,
                                                                              results):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    transport = FakeTransport(*script)
    rc = export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY})
    report = json.loads(capsys.readouterr().out)
    assert rc == 2 and report["status"] == "UNCERTAIN" and report["uncertain_reason"] == reason
    assert len(transport.calls) == len(script)  # stopped at the failure, nothing repeated
    assert [b["outcome"] for b in report["batches"]] == results
    assert report["not_attempted_batches"] == 2 - len(script)
    assert "simulated" not in json.dumps(report)  # exception text is never echoed
    assert records(tmp_path)[-1] == {**records(tmp_path)[-1], "entry": "send_finished", "status": "UNCERTAIN"}


@pytest.mark.parametrize("provenance, extra, match", [
    (None, (), "unknown provenance"),
    ("synthetic", (), "synthetic"),
])
def test_send_refuses_synthetic_or_unknown_without_explicit_authorization(tmp_path, provenance, extra, match):
    path = capture_with(tmp_path, hermes_like_context())
    transport, reads = FakeTransport(), []

    class Env(dict):
        def get(self, key, default=None):
            reads.append(key)
            return super().get(key, default)

    with pytest.raises(ls_export.ExportError, match=match):
        export.main(send_argv(path, tmp_path, *extra, provenance=provenance), transport=transport,
                    environ=Env({export.API_KEY_ENV: KEY}))
    assert transport.calls == [] and reads == [] and not (tmp_path / "send-record.jsonl").exists()


@pytest.mark.parametrize("provenance, flag", [(None, "--allow-unknown-provenance"), ("synthetic", "--allow-synthetic")])
def test_send_with_explicit_provenance_authorization_proceeds(tmp_path, capsys, provenance, flag):
    path = capture_with(tmp_path, hermes_like_context())
    transport = FakeTransport()
    assert export.main(send_argv(path, tmp_path, flag, provenance=provenance), transport=transport,
                       environ={export.API_KEY_ENV: KEY}) == 0
    assert len(transport.calls) == 2
    capsys.readouterr()


@pytest.mark.parametrize("provenance", [None, "synthetic"])
def test_withheld_only_input_cannot_be_sent_without_authorization(tmp_path, provenance):
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (path,) = directory.glob("hermes-events-*.jsonl")
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match="in withheld traces"):
        export.main(send_argv(path, tmp_path, provenance=provenance), transport=transport,
                    environ={export.API_KEY_ENV: KEY})
    assert transport.calls == []


def test_nothing_to_send_never_reads_the_key_or_connects(tmp_path, capsys):
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs(turn_id="", session_id="", api_request_id="", tool_call_id=""))
    (path,) = directory.glob("hermes-events-*.jsonl")
    transport = FakeTransport()
    assert export.main(send_argv(path, tmp_path), transport=transport, environ={}) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NOTHING_TO_SEND"
    assert transport.calls == [] and not (tmp_path / "send-record.jsonl").exists()


@pytest.mark.parametrize("argv_extra, environ, match", [
    ((), {}, "OPIK_API_KEY is not set"),
    ((), {export.API_KEY_ENV: "two\nlines"}, "single-line"),
    ((), {export.API_KEY_ENV: "abc*ZW5jb2RlZA=="}, "pass --endpoint explicitly"),
    (("--endpoint", "http://opik.example.org/api"), {export.API_KEY_ENV: KEY}, "https URL"),
    (("--endpoint", "https://user:pw@opik.example.org/api"), {export.API_KEY_ENV: KEY}, "https URL"),
    (("--endpoint", "https://opik.example.org/api?x=1"), {export.API_KEY_ENV: KEY}, "https URL"),
])
def test_send_preconditions_fail_before_any_connection(tmp_path, argv_extra, environ, match):
    path = capture_with(tmp_path, hermes_like_context())
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match=match):
        export.main(send_argv(path, tmp_path, *argv_extra), transport=transport, environ=environ)
    assert transport.calls == [] and not (tmp_path / "send-record.jsonl").exists()


def test_explicit_https_endpoint_is_used(tmp_path, capsys):
    path = capture_with(tmp_path, hermes_like_context())
    transport = FakeTransport()
    assert export.main(send_argv(path, tmp_path, "--endpoint", "https://opik.example.org/api/", "--timeout", "5"),
                       transport=transport, environ={export.API_KEY_ENV: "abc*ZW5jb2RlZA=="}) == 0
    assert transport.calls[0]["url"] == "https://opik.example.org/api/v1/private/traces/batch"
    assert transport.calls[0]["timeout"] == 5.0
    capsys.readouterr()


def test_existing_record_is_never_reused(tmp_path):
    path = capture_with(tmp_path, hermes_like_context())
    (tmp_path / "send-record.jsonl").write_text("earlier\n")
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match="never reused"):
        export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY})
    assert transport.calls == [] and (tmp_path / "send-record.jsonl").read_text() == "earlier\n"


@pytest.mark.parametrize("argv_extra", [("--record", "r.jsonl"), ("--endpoint", "https://x.org/api"),
                                        ("--timeout", "5"), ("--allow-synthetic",), ("--allow-unknown-provenance",)])
def test_send_options_are_rejected_without_send(tmp_path, argv_extra, capsys):
    path = capture_with(tmp_path, hermes_like_context())
    with pytest.raises(SystemExit):
        export.main([str(path), "--project", "tfg-opik", *argv_extra], transport=FakeTransport())
    assert "only valid with --send" in capsys.readouterr().err


@pytest.mark.parametrize("argv_extra, message", [((), "--workspace"), (("--workspace", "w"), "--record"),
                                                 (("--workspace", "w", "--record", "r", "--timeout", "0"), "--timeout")])
def test_send_requires_workspace_record_and_bounded_timeout(tmp_path, argv_extra, message, capsys):
    path = capture_with(tmp_path, hermes_like_context())
    with pytest.raises(SystemExit):
        export.main([str(path), "--project", "tfg-opik", "--send", *argv_extra], transport=FakeTransport())
    assert message in capsys.readouterr().err


def test_dry_run_reads_no_variable_calls_no_transport_and_writes_nothing(tmp_path, capsys):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    reads = []

    class Env(dict):
        def get(self, key, default=None):
            reads.append(key)
            return super().get(key, default)

        def __getitem__(self, key):
            reads.append(key)
            return super().__getitem__(key)

    def transport(*args):
        raise AssertionError("dry-run used the transport")

    before = sorted(p.name for p in tmp_path.rglob("*"))
    assert export.main([str(path), "--project", "tfg-opik", "--workspace", "tfg-ws", "--provenance", "captured"],
                       transport=transport, environ=Env({export.API_KEY_ENV: KEY})) == 0
    out = capsys.readouterr().out
    assert reads == [] and KEY not in out and json.loads(out)["sent"] is False
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_default_transport_failure_is_uncertain_with_sockets_blocked(tmp_path, capsys, monkeypatch):
    import socket
    attempts = []

    def deny(*args, **kwargs):
        attempts.append(1)
        raise OSError("network blocked in tests")

    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    path = capture_with(tmp_path, hermes_like_context())
    rc = export.main(send_argv(path, tmp_path), environ={export.API_KEY_ENV: KEY})  # real urllib transport
    report = json.loads(capsys.readouterr().out)
    assert rc == 2 and report["status"] == "UNCERTAIN" and len(report["batches"]) == 1
    assert report["batches"][0]["outcome"] == "no_response_delivery_unknown" and len(attempts) == 1


SERVER_SENTINEL = "SRV-SENTINEL-reason-7f3a sk-ant-LEAKED-0000 /home/joelm/x"


class EchoingTransport:
    """Returns server-controlled text everywhere it could hide, then raises with it in the message."""

    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    def __call__(self, url, headers, body, timeout):
        self.calls += 1
        step = self.script.pop(0)
        if step == "raise":
            raise ConnectionResetError(SERVER_SENTINEL)
        return {"status": step, "reason": SERVER_SENTINEL, "body": SERVER_SENTINEL, "headers": {"x": SERVER_SENTINEL},
                "body_bytes": 17}


@pytest.mark.parametrize("script, outcomes", [
    ((204, 400), ["http_accepted", "http_not_accepted"]),
    ((204, "raise"), ["http_accepted", "no_response_delivery_unknown"]),
    ((f"204 {SERVER_SENTINEL}",), ["invalid_transport_response_delivery_unknown"]),
    ((True,), ["invalid_transport_response_delivery_unknown"]),
])
def test_server_text_never_reaches_output_or_record(tmp_path, capsys, script, outcomes):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    transport = EchoingTransport(*script)
    export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY})
    out = capsys.readouterr().out
    record_text = (tmp_path / "send-record.jsonl").read_text()
    for text in (out, record_text):
        assert "SRV-SENTINEL" not in text and "LEAKED" not in text and "/home/joelm" not in text
        assert "http_reason" not in text
    report = json.loads(out)
    assert [b["outcome"] for b in report["batches"]] == outcomes and report["status"] == "UNCERTAIN"
    for batch in report["batches"]:
        assert set(batch) <= {"outcome", "http_status", "response_body_bytes", "error_type", "index", "kind",
                              "items", "elapsed_wall_s", "recorded"}


def test_default_transport_returns_status_size_and_only_a_bounded_error_body(monkeypatch):
    import io

    class Response(io.BytesIO):
        status, reason, headers = 204, SERVER_SENTINEL, {"x": SERVER_SENTINEL}

    class Opener:
        def __init__(self, behaviour, body):
            self.behaviour, self.body = behaviour, body

        def open(self, request, timeout):
            if self.behaviour == "error":
                raise export.urllib.error.HTTPError(request.full_url, 418, SERVER_SENTINEL,
                                                    {"x": SERVER_SENTINEL}, io.BytesIO(self.body))
            return Response(self.body)

    small = SERVER_SENTINEL.encode()
    url = "https://opik.invalid/api/v1/private/traces/batch"
    monkeypatch.setattr(export.urllib.request, "build_opener", lambda *handlers: Opener("ok", small))
    assert export.urllib_transport(url, {}, b"{}", 1) == {"status": 204, "body_bytes": len(small)}  # 2xx: no body
    monkeypatch.setattr(export.urllib.request, "build_opener", lambda *handlers: Opener("error", small))
    result = export.urllib_transport(url, {}, b"{}", 1)
    assert result["status"] == 418 and result["error_body"] == small and result["body_bytes"] == len(small)
    assert "reason" not in result and "headers" not in result


LIMIT = export.ERROR_BODY_MAX_BYTES + 1  # 4097: the most the transport may ever request


class BoundedStream:
    """Fake error-response stream that fails any unbounded or over-limit read."""

    def __init__(self, data=b"", read_error=None, close_error=None):
        self.data, self.read_error, self.close_error = data, read_error, close_error
        self.reads, self.closed = [], False

    def read(self, amt=None):
        assert amt is not None and amt >= 0, "unbounded read of an error body"
        assert amt <= LIMIT, f"read of {amt} bytes exceeds {LIMIT}"
        self.reads.append(amt)
        if self.read_error:
            raise self.read_error("reset while reading " + SERVER_SENTINEL)
        chunk, self.data = self.data[:amt], self.data[amt:]
        return chunk

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error("close failed " + SERVER_SENTINEL)


def _error_opener(monkeypatch, stream, status=400):
    opens = []

    class Opener:
        def open(self, request, timeout):
            opens.append(request.full_url)
            raise export.urllib.error.HTTPError(request.full_url, status, SERVER_SENTINEL, {"x": SERVER_SENTINEL},
                                                stream)

    monkeypatch.setattr(export.urllib.request, "build_opener", lambda *handlers: Opener())
    return opens


@pytest.mark.parametrize("size, captured, truncated, total", [
    (0, 0, False, 0),
    (57, 57, False, 57),
    (export.ERROR_BODY_MAX_BYTES, export.ERROR_BODY_MAX_BYTES, False, export.ERROR_BODY_MAX_BYTES),
    (export.ERROR_BODY_MAX_BYTES + 1, export.ERROR_BODY_MAX_BYTES, True, None),
    (1024 * 1024, export.ERROR_BODY_MAX_BYTES, True, None),  # never read beyond the limit
])
def test_error_body_read_is_bounded_and_size_claims_are_exact(monkeypatch, size, captured, truncated, total):
    stream = BoundedStream(b"E" * size)
    _error_opener(monkeypatch, stream)
    result = export.urllib_transport("https://opik.invalid/api/v1/private/traces/batch", {}, b"{}", 1)
    assert stream.reads == [LIMIT] and stream.closed  # one bounded read, stream closed
    assert result["status"] == 400 and result["body_bytes_captured"] == captured
    assert result["body_truncated"] is truncated and result["body_bytes"] == total  # total only when known
    assert result["error_body"] == b"E" * captured
    assert result["body_read_error"] is None and result["body_close_error"] is None


def test_error_body_read_failure_keeps_the_status_and_no_body(monkeypatch):
    stream = BoundedStream(b"E" * 100, read_error=ConnectionResetError)
    _error_opener(monkeypatch, stream)
    result = export.urllib_transport("https://opik.invalid/api/v1/private/traces/batch", {}, b"{}", 1)
    assert result["status"] == 400 and result["body_read_error"] == "ConnectionResetError"
    assert result["error_body"] == b"" and result["body_bytes"] is None and result["body_truncated"] is None
    assert stream.closed and "SRV-SENTINEL" not in json.dumps({k: v for k, v in result.items() if k != "error_body"})


def test_error_body_close_failure_keeps_what_was_read(monkeypatch):
    stream = BoundedStream(b"E" * 10, close_error=OSError)
    _error_opener(monkeypatch, stream)
    result = export.urllib_transport("https://opik.invalid/api/v1/private/traces/batch", {}, b"{}", 1)
    assert result["status"] == 400 and result["error_body"] == b"E" * 10
    assert result["body_close_error"] == "OSError" and result["body_read_error"] is None


@pytest.mark.parametrize("stream_kwargs, file_status, extra", [
    ({"data": b"ERRBODY-SENTINEL" * 1000}, "saved", {"response_body_truncated": True,
                                                    "response_body_bytes_captured": 4096}),
    ({"data": b"ERRBODY-SENTINEL", "read_error": ConnectionResetError}, "no_body_received",
     {"response_body_read_error": "ConnectionResetError"}),
    ({"data": b"ERRBODY-SENTINEL", "close_error": OSError}, "saved", {"response_body_close_error": "OSError"}),
])
def test_real_transport_error_body_end_to_end_is_uncertain_and_private(tmp_path, capsys, monkeypatch,
                                                                       stream_kwargs, file_status, extra):
    stream = BoundedStream(**stream_kwargs)
    opens = _error_opener(monkeypatch, stream)
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    rc = export.main(send_argv(path, tmp_path) + ["--error-body-file", str(tmp_path / "error-body.bin")],
                     environ={export.API_KEY_ENV: KEY})  # real urllib_transport, fake opener
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 2 and report["status"] == "UNCERTAIN" and report["uncertain_reason"] == "http_status_400"
    assert len(opens) == 1 and stream.reads == [LIMIT]  # one POST, one bounded read, no retry
    batch = report["batches"][0]
    assert batch["http_status"] == 400 and all(batch[k] == v for k, v in extra.items())
    assert report["error_body_file"]["status"] == file_status
    if "data" in stream_kwargs and file_status == "saved" and len(stream_kwargs["data"]) > 4096:
        assert len((tmp_path / "error-body.bin").read_bytes()) == 4096
        assert report["error_body_file"]["truncated"] is True
        assert report["error_body_file"]["response_body_bytes"] is None  # total unknown, not invented
    record_text = (tmp_path / "send-record.jsonl").read_text()
    for text in (captured.out, captured.err, record_text):
        assert "ERRBODY-SENTINEL" not in text and "SRV-SENTINEL" not in text


def _fail_on_fsync(monkeypatch, failing_call):
    calls = []
    real = export.os.fsync

    def fsync(fd):
        calls.append(fd)
        if len(calls) == failing_call:
            raise OSError(28, "No space left on device")
        return real(fd)

    monkeypatch.setattr(export.os, "fsync", fsync)


# fsync order: 1 send_started, 2 intent 0, 3 result 0, 4 intent 1, 5 result 1, 6 send_finished
@pytest.mark.parametrize("failing_call, posts, status, reason, stage, not_attempted", [
    (1, 0, "NOT_SENT", "record_unwritable_before_first_post", "send_started", 2),
    (2, 0, "NOT_SENT", "record_unwritable_batch_not_sent", "batch_intent_0", 2),
    (3, 1, "UNCERTAIN", "record_unwritable_after_post", "batch_result_0", 1),
    (4, 1, "UNCERTAIN", "record_unwritable_batch_not_sent_after_earlier_accepted_batches", "batch_intent_1", 1),
    (5, 2, "UNCERTAIN", "record_unwritable_after_post_after_earlier_accepted_batches", "batch_result_1", 0),
    (6, 2, "UNCERTAIN", "record_send_finished_failed_after_all_batches_http_accepted", "send_finished", 0),
])
def test_record_failures_never_escape_and_never_claim_a_recorded_result(tmp_path, capsys, monkeypatch, failing_call,
                                                                        posts, status, reason, stage, not_attempted):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    _fail_on_fsync(monkeypatch, failing_call)
    transport = FakeTransport()
    rc = export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY})
    report = json.loads(capsys.readouterr().out)
    assert rc == 2 and len(transport.calls) == posts  # nothing retried, nothing sent after the failure
    assert report["status"] == status and report["uncertain_reason"] == reason
    assert report["record_complete"] is False and report["record_failure"]["stage"] == stage
    assert report["not_attempted_batches"] == not_attempted
    if failing_call in (3, 5):
        assert report["batches"][-1]["recorded"] is False
    assert all(b["recorded"] for b in report["batches"][:-1])
    assert report["http_statuses_received"] == [204] * posts  # HTTP facts kept apart from the aggregate


def test_close_failure_after_all_posts_is_uncertain_and_keeps_http_codes(tmp_path, capsys, monkeypatch):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    real_close = export._SendRecord.close

    def close(self):
        real_close(self)
        raise OSError(5, "Input/output error on close")

    monkeypatch.setattr(export._SendRecord, "close", close)
    transport = FakeTransport()
    rc = export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY})
    report = json.loads(capsys.readouterr().out)
    assert rc == 2 and len(transport.calls) == 2  # both POSTs once, nothing retried
    assert report["status"] == "UNCERTAIN"
    assert report["uncertain_reason"] == "record_close_failed_after_all_batches_http_accepted"
    assert report["record_complete"] is False and report["record_failure"]["stage"] == "close"
    assert report["http_statuses_received"] == [204, 204] and report["http_accepted_batches"] == 2
    assert all(b["recorded"] for b in report["batches"])
    assert [e["entry"] for e in records(tmp_path)][-1] == "send_finished"


def test_close_failure_does_not_upgrade_a_weaker_state(tmp_path, capsys, monkeypatch):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    real_close = export._SendRecord.close

    def close(self):
        real_close(self)
        raise OSError(5, "Input/output error on close")

    monkeypatch.setattr(export._SendRecord, "close", close)
    transport = FakeTransport(500)
    assert export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY}) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "UNCERTAIN" and report["uncertain_reason"] == "http_status_500"
    assert report["record_failure"]["stage"] == "close" and report["http_statuses_received"] == [500]


@pytest.mark.parametrize("change", ["workspace", "project"])
def test_plan_repointed_to_another_valid_destination_is_refused(tmp_path, change):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    plan = plan_from(path, provenance="captured", workspace="tfg-ws")
    if change == "workspace":
        plan.destination = export.make_destination("tfg-opik", "team-b")  # valid, but ids are from tfg-ws
    else:
        plan.destination = export.make_destination("tfg-opik-2", "tfg-ws")
        for item in plan.traces + plan.spans:
            item["project_name"] = "tfg-opik-2"  # payload re-labelled, ids still from tfg-opik
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match="not derived from the current destination"):
        export.send(plan, transport=transport, **_send_kwargs(tmp_path))
    assert transport.calls == [] and not (tmp_path / "direct.jsonl").exists()
    rebuilt = plan_from(path, provenance="captured", workspace="team-b")  # rebuilding is the way
    report = export.send(rebuilt, transport=transport, **_send_kwargs(tmp_path))
    assert report["status"] == "ALL_BATCHES_HTTP_ACCEPTED"


def test_plan_rebuilt_for_another_project_is_accepted_but_reused_ids_are_not(tmp_path):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    original = plan_from(path, project="tfg-opik", provenance="captured", workspace="tfg-ws")
    rebuilt = plan_from(path, project="tfg-opik-2", provenance="captured", workspace="tfg-ws")
    old_ids = {item["id"] for item in original.traces + original.spans}
    assert old_ids.isdisjoint(item["id"] for item in rebuilt.traces + rebuilt.spans)

    reused = plan_from(path, project="tfg-opik", provenance="captured", workspace="tfg-ws")
    reused.destination = rebuilt.destination  # new project, ids still derived from tfg-opik
    for item in reused.traces + reused.spans:
        item["project_name"] = "tfg-opik-2"
    refused_transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match="not derived from the current destination"):
        export.send(reused, transport=refused_transport, **_send_kwargs(tmp_path, record_path=tmp_path / "reused.jsonl"))
    assert refused_transport.calls == [] and not (tmp_path / "reused.jsonl").exists()

    transport = FakeTransport()
    report = export.send(rebuilt, transport=transport, **_send_kwargs(tmp_path, record_path=tmp_path / "rebuilt.jsonl"))
    assert report["status"] == "ALL_BATCHES_HTTP_ACCEPTED" and report["record_complete"] is True
    assert report["destination"]["project"] == "tfg-opik-2"
    sent = [item for call in transport.calls for item in next(iter(call["body"].values()))]
    assert {item["project_name"] for item in sent} == {"tfg-opik-2"}
    assert {item["id"] for item in sent} == {item["id"] for item in rebuilt.traces + rebuilt.spans}
    assert old_ids.isdisjoint(item["id"] for item in sent)


@pytest.mark.parametrize("how", ["missing_scope", "wrong_scope_kind", "start_time_changed"])
def test_ids_must_match_their_recorded_derivation(tmp_path, how):
    plan = plan_from(capture_with(tmp_path, hermes_like_context(), error=True), provenance="captured",
                     workspace="tfg-ws")
    span = plan.spans[0]
    if how == "missing_scope":
        del plan.id_scopes[span["id"]]
    elif how == "wrong_scope_kind":
        plan.id_scopes[span["id"]] = "trace|" + plan.id_scopes[span["id"]]
    else:
        span["start_time"] = plan.spans[1]["start_time"]
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match="not derived"):
        export.send(plan, transport=transport, **_send_kwargs(tmp_path))
    assert transport.calls == [] and not (tmp_path / "direct.jsonl").exists()


def test_record_write_failure_after_post_is_uncertain(tmp_path, capsys, monkeypatch):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    real_write = export._SendRecord.write

    def write(self, entry):
        if entry["entry"] == "batch_result":
            raise OSError(5, "Input/output error")
        return real_write(self, entry)

    monkeypatch.setattr(export._SendRecord, "write", write)
    transport = FakeTransport()
    assert export.main(send_argv(path, tmp_path), transport=transport, environ={export.API_KEY_ENV: KEY}) == 2
    report = json.loads(capsys.readouterr().out)
    assert len(transport.calls) == 1 and report["status"] == "UNCERTAIN"
    assert report["uncertain_reason"] == "record_unwritable_after_post" and report["batches"][0]["recorded"] is False
    entries = records(tmp_path)
    assert [e["entry"] for e in entries] == ["send_started", "batch_intent"]  # no claimed result or finish


def _send_kwargs(tmp_path, **override):
    kwargs = dict(endpoint=export.OPIK_CLOUD_ENDPOINT, api_key=KEY, record_path=tmp_path / "direct.jsonl",
                  timeout=30.0)
    kwargs.update(override)
    return kwargs


def _tamper(plan, how):
    if how == "no_workspace":
        plan.destination = export.make_destination(plan.destination["project"])
    elif how == "destination_key":
        plan.destination = {**plan.destination, "key": "opik:other/tfg-opik"}
    elif how == "span_project":
        plan.spans[0]["project_name"] = "other-project"
    elif how == "orphan_span":
        plan.spans[0]["trace_id"] = plan.spans[1]["id"]
    elif how == "duplicate_span_id":
        plan.spans[1]["id"] = plan.spans[0]["id"]
    elif how == "non_v7_id":
        plan.spans[0]["id"] = str(uuid.uuid4())
    elif how == "untracked_trace":
        plan.trace_kinds.clear()


@pytest.mark.parametrize("override, how, match", [
    ({"endpoint": "http://opik.example.org/api"}, None, "https URL"),
    ({"endpoint": None}, None, "valid URL|https URL"),
    ({"timeout": 0}, None, "timeout"),
    ({"timeout": float("nan")}, None, "timeout"),
    ({"timeout": True}, None, "timeout"),
    ({"timeout": "5"}, None, "timeout"),
    ({"timeout": 121}, None, "timeout"),
    ({"api_key": None}, None, "not set"),
    ({"api_key": "a b"}, None, "single-line"),
    ({"api_key": "abc*ZW5j"}, None, "pass --endpoint explicitly"),
    ({}, "no_workspace", "explicit workspace"),
    ({}, "destination_key", "not a valid Opik destination"),
    ({}, "span_project", "project other than its destination"),
    ({}, "orphan_span", "trace is not in the plan"),
    ({}, "duplicate_span_id", "repeated"),
    ({}, "non_v7_id", "UUIDv7"),
    ({}, "untracked_trace", "provenance does not cover"),
])
def test_send_validates_its_own_arguments_and_payload(tmp_path, override, how, match):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    plan = plan_from(path, provenance="captured", workspace="tfg-ws")
    if how:
        _tamper(plan, how)
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match=match):
        export.send(plan, transport=transport, **_send_kwargs(tmp_path, **override))
    assert transport.calls == [] and not (tmp_path / "direct.jsonl").exists()


def test_send_applies_provenance_gate_itself(tmp_path):
    plan = plan_from(capture_with(tmp_path, hermes_like_context()), workspace="tfg-ws")  # unknown provenance
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match="unknown provenance"):
        export.send(plan, transport=transport, **_send_kwargs(tmp_path))
    assert transport.calls == [] and not (tmp_path / "direct.jsonl").exists()
    report = export.send(plan, transport=transport, allow_unknown_provenance=True, **_send_kwargs(tmp_path))
    assert report["status"] == "ALL_BATCHES_HTTP_ACCEPTED" and report["record_complete"] is True


# --- optional --error-body-file (fake transport only) ---------------------------------------

ERROR_BODY_SENTINEL = b'{"code":400,"message":"ERRBODY-SENTINEL-91c2 field rejected","details":"x"}'


class ErrorBodyTransport:
    """Scripted (status, error_body) pairs; records every call so retries would be visible."""

    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    def __call__(self, url, headers, body, timeout):
        self.calls += 1
        status, error_body = self.script.pop(0)
        response = {"status": status, "body_bytes": len(error_body or b"")}
        if error_body is not None:
            response["error_body"] = error_body
        return response


def _error_body_run(tmp_path, capsys, transport, *extra, error_body=True):
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    argv = send_argv(path, tmp_path, *extra)
    if error_body:
        argv += ["--error-body-file", str(tmp_path / "error-body.bin")]
    rc = export.main(argv, transport=transport, environ={export.API_KEY_ENV: KEY})
    captured = capsys.readouterr()
    return rc, captured, json.loads(captured.out)


def _assert_body_nowhere(tmp_path, captured, needle=b"ERRBODY-SENTINEL"):
    text = needle.decode()
    assert text not in captured.out and text not in captured.err
    assert text not in (tmp_path / "send-record.jsonl").read_text()


def test_error_body_is_saved_privately_and_never_reported(tmp_path, capsys):
    transport = ErrorBodyTransport((400, ERROR_BODY_SENTINEL))
    rc, captured, report = _error_body_run(tmp_path, capsys, transport)
    target = tmp_path / "error-body.bin"
    assert rc == 2 and report["status"] == "UNCERTAIN" and transport.calls == 1  # no retry, spans not sent
    assert target.read_bytes() == ERROR_BODY_SENTINEL
    assert (target.stat().st_mode & 0o777) == 0o600
    meta = report["error_body_file"]
    assert meta["status"] == "saved" and meta["bytes_saved"] == len(ERROR_BODY_SENTINEL)
    assert meta["truncated"] is False and meta["sha256"] == hashlib.sha256(ERROR_BODY_SENTINEL).hexdigest()
    assert records(tmp_path)[2]["error_body_file"]["status"] == "saved"
    _assert_body_nowhere(tmp_path, captured)


def test_error_body_is_truncated_to_the_limit(tmp_path, capsys):
    body = b"ERRBODY-SENTINEL" + b"x" * (2 * export.ERROR_BODY_MAX_BYTES)
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((413, body)))
    saved = (tmp_path / "error-body.bin").read_bytes()
    assert saved == body[:export.ERROR_BODY_MAX_BYTES] and len(saved) == 4096
    assert report["error_body_file"]["truncated"] is True
    assert report["error_body_file"]["response_body_bytes"] == len(body)
    _assert_body_nowhere(tmp_path, captured)


@pytest.mark.parametrize("error_body", [None, b""])
def test_absent_error_body_creates_no_file(tmp_path, capsys, error_body):
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, error_body)))
    assert rc == 2 and report["error_body_file"]["status"] == "no_body_received"
    assert not (tmp_path / "error-body.bin").exists()


def test_error_body_file_untouched_when_every_batch_is_accepted(tmp_path, capsys):
    transport = ErrorBodyTransport((204, None), (204, None))
    rc, captured, report = _error_body_run(tmp_path, capsys, transport)
    assert rc == 0 and report["error_body_file"]["status"] == "not_needed_no_non_2xx_response"
    assert not (tmp_path / "error-body.bin").exists()


def test_without_the_option_an_error_body_is_never_written_or_reported(tmp_path, capsys):
    before = sorted(p.name for p in tmp_path.rglob("*"))
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, ERROR_BODY_SENTINEL)),
                                           error_body=False)
    assert rc == 2 and report["error_body_file"] is None and "error_body_file" not in report["batches"][0]
    created = set(p.name for p in tmp_path.rglob("*")) - set(before)
    assert "error-body.bin" not in created
    _assert_body_nowhere(tmp_path, captured)


def test_existing_error_body_file_is_refused_before_anything_is_sent(tmp_path, capsys):
    (tmp_path / "error-body.bin").write_bytes(b"earlier")
    transport = ErrorBodyTransport((400, ERROR_BODY_SENTINEL))
    path = capture_with(tmp_path, hermes_like_context(), error=True)
    reads = []

    class Env(dict):
        def get(self, key, default=None):
            reads.append(key)
            return super().get(key, default)

    with pytest.raises(ls_export.ExportError, match="never overwritten"):
        export.main(send_argv(path, tmp_path) + ["--error-body-file", str(tmp_path / "error-body.bin")],
                    transport=transport, environ=Env({export.API_KEY_ENV: KEY}))
    assert transport.calls == 0 and reads == [] and not (tmp_path / "send-record.jsonl").exists()
    assert (tmp_path / "error-body.bin").read_bytes() == b"earlier"


def test_error_body_file_created_meanwhile_is_not_overwritten(tmp_path, capsys):
    target = tmp_path / "error-body.bin"

    def transport(url, headers, body, timeout):
        target.write_bytes(b"appeared")  # raced into existence after the pre-checks
        return {"status": 400, "body_bytes": len(ERROR_BODY_SENTINEL), "error_body": ERROR_BODY_SENTINEL}

    path = capture_with(tmp_path, hermes_like_context(), error=True)
    rc = export.main(send_argv(path, tmp_path) + ["--error-body-file", str(target)], transport=transport,
                     environ={export.API_KEY_ENV: KEY})
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert rc == 2 and report["status"] == "UNCERTAIN"
    assert report["error_body_file"]["status"] == "failed_not_created"
    assert report["error_body_file"]["error_type"] == "FileExistsError"
    assert target.read_bytes() == b"appeared"
    _assert_body_nowhere(tmp_path, captured)


def test_error_body_symlink_is_never_followed(tmp_path, capsys):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    target = tmp_path / "error-body.bin"

    def transport(url, headers, body, timeout):
        target.symlink_to(outside)
        return {"status": 400, "body_bytes": len(ERROR_BODY_SENTINEL), "error_body": ERROR_BODY_SENTINEL}

    path = capture_with(tmp_path, hermes_like_context(), error=True)
    export.main(send_argv(path, tmp_path) + ["--error-body-file", str(target)], transport=transport,
                environ={export.API_KEY_ENV: KEY})
    report = json.loads(capsys.readouterr().out)
    assert report["error_body_file"]["status"] == "failed_not_created" and outside.read_bytes() == b"keep"


def test_error_body_write_failure_keeps_uncertain_without_showing_the_body(tmp_path, capsys, monkeypatch):
    real_write = export.os.write

    def failing_write(fd, data):
        if b"ERRBODY-SENTINEL" in bytes(data):
            raise OSError(28, "No space left on device")
        return real_write(fd, data)

    monkeypatch.setattr(export.os, "write", failing_write)
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, ERROR_BODY_SENTINEL)))
    assert rc == 2 and report["status"] == "UNCERTAIN" and report["uncertain_reason"] == "http_status_400"
    meta = report["error_body_file"]
    assert meta["status"] == "failed_partial_file_may_exist" and meta["error_type"] == "OSError"
    assert meta["sha256"] is None and meta["bytes_saved"] == 0
    assert report["record_complete"] is True  # the record itself is unaffected
    _assert_body_nowhere(tmp_path, captured)


def _is_error_body_fd(fd):
    try:
        return os.readlink(f"/proc/self/fd/{fd}").endswith("error-body.bin")
    except OSError:
        return False


def test_error_body_fsync_failure_keeps_uncertain_without_showing_the_body(tmp_path, capsys, monkeypatch):
    real_fsync = export.os.fsync

    def fsync(fd):
        if _is_error_body_fd(fd):
            raise OSError(5, "Input/output error")
        return real_fsync(fd)  # the send record keeps working

    monkeypatch.setattr(export.os, "fsync", fsync)
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, ERROR_BODY_SENTINEL)))
    assert rc == 2 and report["status"] == "UNCERTAIN" and report["record_complete"] is True
    assert report["error_body_file"]["status"] == "failed_partial_file_may_exist"
    assert report["error_body_file"]["sha256"] is None
    _assert_body_nowhere(tmp_path, captured)


def test_error_body_close_failure_never_escapes(tmp_path, capsys, monkeypatch):
    real_close = export.os.close

    def close(fd):
        is_body = _is_error_body_fd(fd)
        real_close(fd)  # really closed; only the reported result fails
        if is_body:
            raise OSError(5, "Input/output error on close")

    monkeypatch.setattr(export.os, "close", close)
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, ERROR_BODY_SENTINEL)))
    assert rc == 2 and report["status"] == "UNCERTAIN" and report["record_complete"] is True
    meta = report["error_body_file"]
    assert meta["status"] == "failed_partial_file_may_exist" and meta["error_type"] == "OSError"
    assert meta["sha256"] is None and meta["bytes_saved"] == 0
    _assert_body_nowhere(tmp_path, captured)


def test_error_body_zero_byte_write_fails_instead_of_looping(tmp_path, capsys, monkeypatch):
    real_write = export.os.write

    def write(fd, data):
        return 0 if _is_error_body_fd(fd) else real_write(fd, data)

    monkeypatch.setattr(export.os, "write", write)
    rc, captured, report = _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, ERROR_BODY_SENTINEL)))
    assert rc == 2 and report["error_body_file"]["status"] == "failed_partial_file_may_exist"
    _assert_body_nowhere(tmp_path, captured)


def test_error_body_file_is_0600_even_with_a_permissive_umask(tmp_path, capsys):
    previous = os.umask(0)
    try:
        _error_body_run(tmp_path, capsys, ErrorBodyTransport((400, ERROR_BODY_SENTINEL)))
    finally:
        os.umask(previous)
    assert ((tmp_path / "error-body.bin").stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize("argv_extra, message", [
    (("--error-body-file", "e.bin"), "only valid with --send"),
])
def test_error_body_option_requires_send(tmp_path, capsys, argv_extra, message):
    path = capture_with(tmp_path, hermes_like_context())
    with pytest.raises(SystemExit):
        export.main([str(path), "--project", "tfg-opik", *argv_extra], transport=FakeTransport())
    assert message in capsys.readouterr().err
    assert not (tmp_path / "e.bin").exists()


@pytest.mark.parametrize("make_path, match", [
    (lambda tmp: tmp / "missing-dir" / "e.bin", "directory does not exist"),
    (lambda tmp: tmp / "send-record.jsonl", "already exists|differ from the record"),
])
def test_error_body_path_is_validated_by_send_itself(tmp_path, make_path, match):
    plan = plan_from(capture_with(tmp_path, hermes_like_context(), error=True), provenance="captured",
                     workspace="tfg-ws")
    transport = FakeTransport()
    with pytest.raises(ls_export.ExportError, match=match):
        export.send(plan, transport=transport, error_body_path=make_path(tmp_path),
                    **_send_kwargs(tmp_path, record_path=tmp_path / "send-record.jsonl"))
    assert transport.calls == [] and not (tmp_path / "send-record.jsonl").exists()


def test_default_transport_never_follows_redirects():
    handler = export._NoRedirect()
    assert handler.redirect_request(None, None, 307, "Temporary Redirect", {}, "https://elsewhere.example/") is None


def test_mixed_clocks_trace_interval_never_uses_capture_time(tmp_path):
    # Hermes epochs after the capture's own recorded_at (year 2100): mixing either bound with
    # recorded_at would move the trace interval; it must equal the measured spans exactly.
    directory = tmp_path / "capture"
    sink = capture.register(hermes_like_context(), environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory)})
    sink.on_post_tool_call(**tool_kwargs())
    sink.on_post_api_request(**llm_kwargs(started_at=4102444800.0, ended_at=4102444801.25, api_duration=1.25,
                                          first_chunk_at=None))
    (path,) = directory.glob("hermes-events-*.jsonl")
    plan = plan_from(path, provenance="captured")
    (trace,), (span,) = plan.traces, plan.spans
    assert (trace["start_time"], trace["end_time"]) == (span["start_time"], span["end_time"])
    assert trace["start_time"].startswith("2100-01-01T00:00:00")
    (point,) = trace["metadata"]["tfg_point_events"]
    assert ls_export._utc(point["time"]) < ls_export._utc(trace["start_time"].replace("Z", "+00:00"))
