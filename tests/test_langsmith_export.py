"""Offline tests for the LangSmith exporter: fixtures and a fake client only, never the network."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from observability import langsmith_export as export
from observability.hermes_capture import capture

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_EVIDENCE = (ROOT / "evaluation" / "observability" / "hermes_loader_hooks_synthetic_2026_10_20"
                      / "capture" / "hermes-events-2026-10-20.jsonl")
SECRET = "sk-ant-THISISAFAKEKEY0123456789abcdef"
ENV = {capture.RUN_ENV: "run-2026-10-20", capture.CASE_ENV: "S1"}


def _summary(**counters):
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "reasoning_tokens": 0, "request_count": 1}
    base.update(counters)
    base["prompt_tokens"] = base["input_tokens"] + base["cache_read_tokens"] + base["cache_write_tokens"]
    base["total_tokens"] = base["prompt_tokens"] + base["output_tokens"]
    return base


def llm_call(**override):
    kwargs = dict(session_id="s-1", task_id="t-1", turn_id="turn-1", api_request_id="turn-1:api:1",
                  provider="custom", model="qwen3:4b", response_model="qwen3:4b", api_mode="chat_completions",
                  finish_reason="stop", api_duration=1.25, started_at=1792246298.0, ended_at=1792246299.25,
                  first_chunk_at=1792246298.4, api_call_count=1, message_count=3, assistant_tool_call_count=0,
                  context_length=65536, usage=_summary(input_tokens=900, output_tokens=40),
                  response={"assistant_message": {"content": "PROMPT-TEXT", "tool_calls": []}})
    kwargs.update(override)
    return capture.llm_call_event(kwargs, ENV)


def tool_call(**override):
    kwargs = dict(session_id="s-1", task_id="t-1", turn_id="turn-1", api_request_id="turn-1:api:1",
                  tool_call_id="call-1", tool_name="mcp_tfg_get_mission_state", duration_ms=742, status="ok",
                  args={"path": "/home/joelm/secret"}, result="RESULT-TEXT")
    kwargs.update(override)
    return capture.tool_call_event(kwargs, ENV)


def llm_error(**override):
    kwargs = dict(session_id="s-1", task_id="t-1", turn_id="turn-1", api_request_id="turn-1:api:2",
                  provider="custom", model="qwen3:4b", api_mode="chat_completions", api_duration=30.0,
                  started_at=1792246300.0, ended_at=1792246330.0, api_call_count=2, status_code=429,
                  retry_count=1, max_retries=3, retryable=True, reason="rate_limited",
                  error={"type": "RateLimitError", "message": f"Bearer {SECRET}"})
    kwargs.update(override)
    return capture.llm_error_event(kwargs, ENV)


def write(tmp_path, *events, name="events.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


def plan_for(tmp_path, *events, project="tfg-test", **options):
    loaded, errors = export.load_events([write(tmp_path, *events)])
    assert errors == []
    return export.build_plan(loaded, project, **options)


class ConflictError(Exception):
    pass


ConflictError.__name__ = "LangSmithConflictError"


class FakeClient:
    def __init__(self, fail_on=None, existing=()):
        self.created, self.fail_on, self.existing = [], fail_on, set(existing)

    def create_run(self, **kwargs):
        if kwargs["id"] == self.fail_on:
            raise RuntimeError(f"HTTP 500 for body containing {SECRET}")
        if kwargs["id"] in self.existing:
            raise ConflictError("409")
        self.existing.add(kwargs["id"])
        self.created.append(kwargs)


# --- validation ----------------------------------------------------------------------------

def test_invalid_lines_are_reported_and_block_sending(tmp_path):
    good = llm_call()
    tampered = {**tool_call(), "args": {"path": "/home/joelm/secret"}}  # not in the schema
    path = tmp_path / "mixed.jsonl"
    path.write_text(json.dumps(good) + "\n{not json\n\n" + json.dumps(tampered) + "\n" + json.dumps(good) + "\n",
                    encoding="utf-8")
    events, errors = export.load_events([path])
    assert len(events) == 1
    assert any(":2: invalid JSON" in e for e in errors) and any(":3: empty line" in e for e in errors)
    assert any(":4: schema" in e for e in errors) and any(":5: duplicate event_id" in e for e in errors)
    plan = export.build_plan(events, "tfg-test")
    plan.errors.extend(errors)
    with pytest.raises(export.ExportError, match="validation errors"):
        export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")


def test_project_is_required(tmp_path):
    with pytest.raises(export.ExportError, match="project"):
        export.build_plan([llm_call()], "")


# --- conversion ----------------------------------------------------------------------------

def test_llm_run_keeps_provenance_and_never_enables_cost_estimation(tmp_path):
    plan = plan_for(tmp_path, llm_call())
    root, run = plan.runs
    meta = run["extra"]["metadata"]
    assert run["run_type"] == "llm" and run["inputs"] == {} and run["outputs"] == {}
    assert (meta["tfg_provider"], meta["tfg_model"]) == ("custom", "qwen3:4b")
    assert meta["tfg_usage"]["input_tokens"] == {"value": 900, "status": "nonzero_normalized"}
    assert meta["tfg_usage"]["reasoning_tokens"] == {"value": 0, "status": "zero_unconfirmed"}
    assert meta["tfg_usage"]["total_tokens"] == {"value": 940, "status": "derived_nonzero"}
    assert "usage.reasoning_tokens" in meta["tfg_ambiguous_zero_fields"]
    assert meta["tfg_usage_semantics"] == "hermes_normalized_summary_not_provider_raw"
    assert meta["tfg_cost"] == "not_computed" and meta["tfg_retry_count"] is None
    serialized = json.dumps(export._jsonable(run))
    for forbidden in ("usage_metadata", "ls_model_name", "ls_provider", "total_cost", "prompt_cost"):
        assert forbidden not in serialized
    # No declaration and no synthetic marker: origin unknown, never presented as a real capture.
    assert meta["tfg_data_kind"] == "unknown_provenance" and "provenance-unknown" in run["tags"]
    assert meta["tfg_provenance_basis"] == "no_provenance_declaration"
    assert run["name"].startswith("UNKNOWN-PROVENANCE · ") and "synthetic" not in run["tags"]


def test_absent_usage_and_fields_stay_absent(tmp_path):
    plan = plan_for(tmp_path, llm_call(usage=None, first_chunk_at=None, context_length=None))
    meta = plan.runs[1]["extra"]["metadata"]
    assert meta["tfg_usage"] is None and meta["tfg_usage_source"] == "absent"
    assert meta["tfg_first_chunk_offset_s"] is None and "context_length" in meta["tfg_absent_fields"]


def test_llm_durations_keep_units_and_mismatches_are_reported_not_fixed(tmp_path):
    plan = plan_for(tmp_path, llm_call(), llm_call(api_duration=2.0))
    llm, mismatched = plan.runs[1], plan.runs[2]
    assert (llm["end_time"] - llm["start_time"]).total_seconds() == pytest.approx(1.25, abs=1e-6)
    meta = llm["extra"]["metadata"]
    assert meta["tfg_time_basis"] == "hermes_epochs" and meta["tfg_latency_measured"] is True
    assert meta["tfg_units"]["api_duration_s"] == "s"
    assert mismatched["extra"]["metadata"]["tfg_api_duration_s"] == 2.0
    assert any("differs from api_duration_s" in w for w in plan.warnings)


def test_tool_without_start_is_a_point_event_never_a_zero_ms_run(tmp_path):
    plan = plan_for(tmp_path, llm_call(), tool_call())
    assert [r["run_type"] for r in plan.runs] == ["chain", "llm"]  # no tool run at all
    (event,) = plan.runs[0]["events"]
    kwargs = event["kwargs"]
    assert event["name"] == "tfg.tool_call" and set(event) == {"name", "time", "kwargs"}
    assert event["time"] == kwargs["tfg_recorded_at_utc"]  # capture time, labelled as such
    assert kwargs["tfg_time_basis"] == "capture_recorded_at_point_not_an_interval"
    assert kwargs["tfg_latency_measured"] is False
    assert (kwargs["tfg_duration_ms_received"], kwargs["tfg_duration_ms_measured"]) == (742, 742)
    assert (kwargs["tfg_duration_source"], kwargs["tfg_units"]["duration_ms_measured"]) == ("hermes_reported_ms", "ms")


def test_zero_and_timeout_tool_durations_are_not_presented_as_measurements(tmp_path):
    plan = plan_for(tmp_path, llm_call(), tool_call(duration_ms=0, status="blocked"),
                    tool_call(duration_ms=30000, status="timeout", tool_call_id="call-2"))
    zero, timeout = (e["kwargs"] for e in plan.runs[0]["events"])
    assert (zero["tfg_duration_ms_received"], zero["tfg_duration_ms_measured"]) == (0, None)
    assert zero["tfg_duration_source"] == "zero_default_or_below_1ms"
    assert "usage" not in zero and "duration_ms" in zero["tfg_ambiguous_zero_fields"]
    assert (timeout["tfg_duration_ms_received"], timeout["tfg_duration_ms_measured"]) == (30000, None)
    assert timeout["tfg_duration_source"] == "timeout_configured_not_measured"


def test_mixed_clocks_root_interval_uses_only_hermes_epochs(tmp_path):
    # Fixture epochs are on 2026-10-17 while the tool's capture time is "now": a mixed min/max
    # would stretch the root over days. The root must follow the measured llm interval only.
    plan = plan_for(tmp_path, llm_call(), tool_call(), llm_error())
    root, llm, error = plan.runs
    assert root["start_time"] == llm["start_time"] and root["end_time"] == error["end_time"]
    assert (root["end_time"] - root["start_time"]).total_seconds() == pytest.approx(32.0, abs=1e-6)
    meta = root["extra"]["metadata"]
    assert meta["tfg_time_basis"] == "derived_min_max_of_hermes_epochs" and meta["tfg_interval_derived"] is True
    assert meta["tfg_latency_measured"] is False and meta["tfg_timed_children"] == 2
    assert meta["tfg_point_events"] == 1
    assert meta["tfg_point_event_time_basis"] == "capture_recorded_at_not_compared_with_hermes_epochs"
    tool_time = export._utc(root["events"][0]["time"])
    assert tool_time > root["end_time"]  # kept as observed, outside the derived interval, not merged


def test_llm_without_epochs_is_untimed_and_alone_is_withheld(tmp_path):
    plan = plan_for(tmp_path, llm_call(started_at=None, ended_at=None, first_chunk_at=None))
    assert plan.runs == [] and plan.traces == []
    assert plan.withheld[0]["reason"] == "no_measured_interval" and plan.withheld[0]["events"] == 1
    mixed = plan_for(tmp_path, llm_call(), llm_call(started_at=None, ended_at=None, first_chunk_at=None))
    assert [r["run_type"] for r in mixed.runs] == ["chain", "llm"]
    assert mixed.runs[0]["events"][0]["name"] == "tfg.llm_call"


def test_trace_without_measured_interval_is_withheld_unless_explicitly_included(tmp_path):
    lone_tool = tool_call(turn_id=None, session_id=None, api_request_id=None)
    withheld = plan_for(tmp_path, lone_tool)
    assert withheld.runs == [] and len(withheld.withheld) == 1
    included = plan_for(tmp_path, lone_tool, include_untimed=True)
    (root,) = included.runs
    meta = root["extra"]["metadata"]
    assert root["start_time"] == root["end_time"] == export._utc(lone_tool["recorded_at_utc"])
    assert meta["tfg_interval_status"] == "unknown_no_measured_interval"
    assert meta["tfg_time_basis"] == "capture_recorded_at_marker" and meta["tfg_latency_measured"] is False
    assert {"interval-unknown", "latency-not-measured"} <= set(root["tags"])
    assert "[interval unknown]" in root["name"] and root["events"][0]["name"] == "tfg.tool_call"


def test_timestamp_that_schema_format_check_misses_is_rejected(tmp_path):
    event = llm_call()
    event["recorded_at_utc"] = "not-a-timestamp"  # FormatChecker skips date-time without rfc3339-validator
    loaded, errors = export.load_events([write(tmp_path, event)])
    assert loaded == [] and "recorded_at_utc is not an ISO 8601 timestamp" in errors[0]
    event["recorded_at_utc"] = "2026-10-20T16:00:00"  # no timezone
    loaded, errors = export.load_events([write(tmp_path, event, name="naive.jsonl")])
    assert loaded == [] and errors


def test_error_run_carries_type_and_status_only(tmp_path):
    plan = plan_for(tmp_path, llm_error())
    run = plan.runs[1]
    assert run["error"] == "RateLimitError (status_code=429)"
    assert run["extra"]["metadata"]["tfg_retry_count"] == 1
    assert SECRET not in json.dumps(export._jsonable(run))


def test_hierarchy_and_dotted_order_invariants(tmp_path):
    plan = plan_for(tmp_path, llm_call(), tool_call(), llm_error(),
                    llm_call(turn_id=None, session_id=None, api_request_id=None))
    assert len(plan.traces) == 2
    root = plan.runs[0]
    assert root["run_type"] == "chain" and root["extra"]["metadata"]["tfg_observed_event"] is False
    for run in plan.runs:
        segments = run["dotted_order"].split(".")
        assert segments[-1][-36:] == run["id"] and segments[0][-36:] == run["trace_id"]
        if "parent_run_id" in run:
            assert segments[-2][-36:] == run["parent_run_id"]
            assert run["dotted_order"].startswith(next(r for r in plan.runs if r["id"] == run["trace_id"])["dotted_order"])
    lone = plan.traces[1]
    assert len(lone["run_ids"]) == 2
    assert next(r for r in plan.runs if r["id"] == lone["root_id"])["extra"]["metadata"]["tfg_grouping"] == \
        "single_event_without_turn_ref"


def test_run_ids_are_deterministic_per_project(tmp_path):
    events = [llm_call(), tool_call()]
    first = plan_for(tmp_path, *events)
    again = plan_for(tmp_path, *events)
    other = plan_for(tmp_path, *events, project="another-project")
    assert [r["id"] for r in first.runs] == [r["id"] for r in again.runs]
    assert not set(r["id"] for r in first.runs) & set(r["id"] for r in other.runs)
    assert all(uuid.UUID(r["id"]).version == 5 for r in first.runs)


def test_no_content_paths_or_secrets_reach_any_prepared_run(tmp_path):
    plan = plan_for(tmp_path, llm_call(), tool_call(), llm_error())
    dumped = json.dumps([export._jsonable(r) for r in plan.runs])
    for sentinel in ("PROMPT-TEXT", "RESULT-TEXT", "/home/joelm", SECRET, "Bearer", "s-1", "turn-1", "call-1"):
        assert sentinel not in dumped


def test_secret_like_value_that_passes_the_schema_is_refused(tmp_path):
    event = llm_call()
    event["model"] = "AKIAABCDEFGHIJKLMNOP"  # matches the schema pattern but looks like an access key
    loaded, errors = export.load_events([write(tmp_path, event)])
    assert errors == []
    with pytest.raises(export.ExportError, match="secret"):
        export.build_plan(loaded, "tfg-test")


# --- synthetic marking ---------------------------------------------------------------------

def test_synthetic_loader_evidence_is_marked_and_needs_explicit_opt_in(tmp_path):
    events, errors = export.load_events([SYNTHETIC_EVIDENCE])
    assert errors == [] and len(events) == 6
    plan = export.build_plan(events, "tfg-synthetic")
    # One turn with measured llm intervals; two lone tool events have no interval and are withheld.
    assert len(plan.traces) == 1 and [r["run_type"] for r in plan.runs] == ["chain", "llm", "llm", "llm"]
    assert len(plan.runs[0]["events"]) == 1 and len(plan.withheld) == 2
    assert all(w["synthetic"] and w["reason"] == "no_measured_interval" for w in plan.withheld)
    assert all(t["synthetic"] for t in plan.traces)
    included = export.build_plan(events, "tfg-synthetic", include_untimed=True)
    assert len(included.traces) == 3 and included.withheld == []
    for run in plan.runs:
        assert run["name"].startswith("SYNTHETIC · ") and "synthetic" in run["tags"]
        assert run["extra"]["metadata"]["tfg_data_kind"] == "synthetic_fixture"
    with pytest.raises(export.ExportError, match="synthetic"):
        export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")
    report = export.send(plan, FakeClient(), tmp_path / "ledger.jsonl", allow_synthetic=True)
    assert report["posted"] == len(plan.runs) and report["failed_trace"] is None

    def factory():
        raise AssertionError("credentials touched before the synthetic refusal")

    with pytest.raises(export.ExportError, match="synthetic"):
        export.main([str(SYNTHETIC_EVIDENCE), "--project", "tfg-synthetic", "--send", "--ledger",
                     str(tmp_path / "l2.jsonl")], client_factory=factory)


def test_real_sdk_client_accepts_prepared_runs_over_a_fake_http_session(tmp_path):
    """langsmith 0.14.1 Client, synchronous path, with a requests-like session that never connects."""
    langsmith = pytest.importorskip("langsmith")

    class Response:
        def __init__(self, status):
            self.status_code, self.text, self.reason = status, "{}", "OK" if status < 400 else "Conflict"
            self.headers = {}

        def json(self):
            return {}

        def raise_for_status(self):
            if self.status_code >= 400:
                import requests
                raise requests.HTTPError(f"{self.status_code}", response=self)

    class Session:
        def __init__(self):
            self.calls, self.seen_ids, self.headers, self.conflicts = [], set(), {}, 0

        def request(self, method, url, **kwargs):
            body = kwargs.get("data") or kwargs.get("json")
            payload = json.loads(body) if isinstance(body, (bytes, str)) else (body or {})
            self.calls.append((method, url.split("/", 3)[-1], payload))
            if payload.get("id") in self.seen_ids:
                self.conflicts += 1
                return Response(409)
            self.seen_ids.add(payload.get("id"))
            return Response(200)

        def mount(self, *args, **kwargs):
            pass

        def close(self):
            pass

    session = Session()
    client = langsmith.Client(api_key="fake-key-for-offline-test", api_url="http://127.0.0.1:9",
                              session=session, auto_batch_tracing=False, omit_traced_runtime_info=True)
    plan = plan_for(tmp_path, llm_call(), tool_call())
    report = export.send(plan, client, tmp_path / "ledger.jsonl", allow_unknown_provenance=True)
    posts = [c for c in session.calls if c[0] == "POST" and c[1].endswith("runs")]
    assert report["posted"] == len(plan.runs) and len(posts) == len(plan.runs)
    sent = {p[2]["id"]: p[2] for p in posts}
    for run in plan.runs:
        body = sent[run["id"]]
        assert body["trace_id"] == run["trace_id"] and body["dotted_order"] == run["dotted_order"]
        assert body["session_name"] == "tfg-test" and body["inputs"] == {} and body["outputs"] == {}
        assert "runtime" not in body.get("extra", {}) and "usage_metadata" not in json.dumps(body)
    root_body = sent[plan.runs[0]["id"]]
    (event,) = root_body["events"]  # the tool call travels as a point event, not as a run
    assert event["name"] == "tfg.tool_call" and "start_time" not in event and "end_time" not in event
    assert event["kwargs"]["tfg_latency_measured"] is False
    assert not any(p[2].get("run_type") == "tool" for p in posts)
    # Ledger lost: same deterministic ids are re-posted; the server answers 409 and the real SDK
    # swallows it, so the exporter cannot tell "already present" from "new" but no id is duplicated.
    again = export.send(plan, client, tmp_path / "fresh-ledger.jsonl", allow_unknown_provenance=True)
    assert again["posted"] == len(plan.runs) and again["conflict_reported"] == 0
    assert session.conflicts == len(plan.runs) and len(session.seen_ids) == len(plan.runs)


# --- dry-run isolation ---------------------------------------------------------------------

def test_dry_run_reads_no_credentials_opens_no_socket_and_never_imports_langsmith(tmp_path):
    path = write(tmp_path, llm_call(), tool_call())
    code = (
        "import socket, sys, os\n"
        "def deny(*a, **k): raise AssertionError('network used in dry-run')\n"
        "socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny\n"
        "class Env(dict):\n"
        "    def get(self, k, d=None):\n"
        "        assert 'LANGSMITH' not in k, 'credential env read in dry-run'\n"
        "        return super().get(k, d)\n"
        "os.environ = Env(os.environ)\n"
        "from observability import langsmith_export as e\n"
        "def no_client(*a, **k): raise AssertionError('client created in dry-run')\n"
        f"rc = e.main([{str(path)!r}, '--project', 'tfg-test'], client_factory=no_client)\n"
        "assert 'langsmith' not in sys.modules, 'langsmith imported in dry-run'\n"
        "sys.exit(rc)\n"
    )
    env = {"PATH": "/usr/bin:/bin", "LANGSMITH_API_KEY": SECRET, "PYTHONPATH": str(ROOT)}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    output = json.loads(done.stdout)
    assert output["mode"] == "dry-run" and output["traces"] == 1
    assert output["runs"] == 2 and output["point_events"] == 1  # root + llm; the tool is a point event
    assert SECRET not in done.stdout + done.stderr


def test_dry_run_with_invalid_input_exits_nonzero_and_lists_errors(tmp_path, capsys):
    path = tmp_path / "bad.jsonl"
    path.write_text("{oops\n", encoding="utf-8")
    assert export.main([str(path), "--project", "tfg-test"], client_factory=None) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["runs"] == 0 and out["errors"]


# --- send path, re-export and partial failures (fake client) -------------------------------

def test_send_requires_flag_ledger_and_reads_the_key_only_then(tmp_path, monkeypatch, capsys, caplog):
    path = write(tmp_path, llm_call(), tool_call())
    calls = []

    def factory():
        calls.append("client")
        return FakeClient()

    assert export.main([str(path), "--project", "tfg-test"], client_factory=factory) == 0
    assert calls == []
    capsys.readouterr()
    with pytest.raises(export.ExportError, match="ledger"):
        export.main([str(path), "--project", "tfg-test", "--send"], client_factory=factory)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(export.ExportError, match="unknown provenance"):
        export.main([str(path), "--project", "tfg-test", "--send", "--ledger", str(ledger)], client_factory=factory)
    assert calls == [] and not ledger.exists()  # refused before any credential access
    assert export.main([str(path), "--project", "tfg-test", "--send", "--ledger", str(ledger),
                        "--allow-unknown-provenance"], client_factory=factory) == 0
    assert calls == ["client"]  # missing ledger and undeclared origin were refused before credentials
    out = capsys.readouterr().out
    assert json.loads(out)["posted"] == 2 and SECRET not in out + caplog.text


def test_make_client_needs_key_and_uses_synchronous_no_runtime_client(monkeypatch):
    with pytest.raises(export.ExportError, match="LANGSMITH_API_KEY"):
        export.make_client({})
    seen = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    import langsmith
    monkeypatch.setattr(langsmith, "Client", RecordingClient)
    export.make_client({export.API_KEY_ENV: SECRET})
    assert seen["auto_batch_tracing"] is False and seen["omit_traced_runtime_info"] is True
    assert seen["api_key"] == SECRET and seen["api_url"] is None
    retry = seen["retry_config"]
    assert (retry.total, retry.connect, retry.read, retry.status, retry.other) == (0, 0, 0, 0, 0)


def test_real_sdk_client_from_make_client_has_no_transport_retries(monkeypatch):
    """The real 0.14.1 Client built by make_client mounts adapters with zero retries (no network)."""
    pytest.importorskip("langsmith")
    client = export.make_client({export.API_KEY_ENV: "fake-key-for-offline-test",
                                 export.ENDPOINT_ENV: "http://127.0.0.1:9"})
    adapters = [client.session.get_adapter(url) for url in ("https://example.invalid", "http://127.0.0.1:9")]
    assert all(a.max_retries.total == 0 and a.max_retries.status == 0 for a in adapters)
    assert client.api_url == "http://127.0.0.1:9"


def test_reexport_is_skipped_by_ledger_and_conflicts_are_not_duplicates(tmp_path):
    plan = plan_for(tmp_path, llm_call(), tool_call(), llm_call(turn_id="turn-2", api_request_id="turn-2:api:1"))
    ledger = tmp_path / "ledger.jsonl"
    client = FakeClient()
    first = export.send(plan, client, ledger, allow_unknown_provenance=True)
    assert first["posted"] == len(plan.runs) and first["completed_traces"] == 2
    second = export.send(plan, client, ledger, allow_unknown_provenance=True)
    assert second["skipped_in_ledger"] == 2 and second["posted"] == 0
    fresh_ledger = tmp_path / "other-ledger.jsonl"
    third = export.send(plan, client, fresh_ledger, allow_unknown_provenance=True)  # ledger lost: server-side id conflicts
    assert third["posted"] == 0 and third["conflict_reported"] == len(plan.runs)
    assert len(client.created) == len(plan.runs)
    outcomes = [json.loads(line)["outcome"] for line in fresh_ledger.read_text().splitlines()]
    assert outcomes == ["conflict_reported_for_all_runs", "conflict_reported_for_all_runs"]
    assert export.describe(plan, ledger)["already_in_ledger"] == sorted(t["root_id"] for t in plan.traces)


def test_partial_failure_stops_reports_type_only_and_resumes_without_duplicates(tmp_path):
    plan = plan_for(tmp_path, llm_call(), llm_error(), tool_call(),
                    llm_call(turn_id="turn-2", api_request_id="turn-2:api:1"))
    ledger = tmp_path / "ledger.jsonl"
    assert len(plan.traces[0]["run_ids"]) == 3  # root, llm_call, llm_error
    failing_run = plan.traces[0]["run_ids"][2]
    client = FakeClient(fail_on=failing_run)
    report = export.send(plan, client, ledger, allow_unknown_provenance=True)
    assert report["failed_trace"] == {"root_id": plan.traces[0]["root_id"], "run_id": failing_run,
                                      "error_type": "RuntimeError"}
    assert report["posted"] == 2 and report["not_attempted_traces"] == 1
    assert SECRET not in json.dumps(report) and not ledger.exists()
    client.fail_on = None
    resumed = export.send(plan, client, ledger, allow_unknown_provenance=True)
    assert resumed["conflict_reported"] == 2 and resumed["posted"] == len(plan.runs) - 2
    assert len({r["id"] for r in client.created}) == len(client.created) == len(plan.runs)


# --- agent/environment addressing (langsmith >= 0.14.9) ------------------------------------

AGENT = {"agent_id": "tfg-synthetic", "agent_environment": "local"}
FIRST_SEND = ROOT / "evaluation" / "observability" / "langsmith_first_synthetic_send_2026_10_20"


@pytest.mark.parametrize("kwargs, message", [
    ({"project": "p", "agent_id": "tfg-synthetic", "agent_environment": "local"}, "not both"),
    ({}, "destination is required"),
    ({"agent_id": "tfg-synthetic"}, "environment"),
    ({"agent_id": "TFG_Synthetic", "agent_environment": "local"}, "DNS label"),
    ({"agent_id": "tfg-synthetic", "agent_environment": "prod"}, "environment"),
    ({"project": "lrn:agents/tfg-synthetic/environments/local"}, "reserved"),
])
def test_destination_is_exactly_one_valid_mode(kwargs, message):
    with pytest.raises(export.ExportError, match=message):
        export.make_destination(**kwargs)


def test_agent_destination_changes_every_id_and_is_recorded(tmp_path):
    events = [llm_call(), tool_call(), llm_error()]
    project_plan = plan_for(tmp_path, *events, project="tfg-synthetic")
    agent_plan = plan_for(tmp_path, *events, project=None, **AGENT)
    assert agent_plan.destination["lrn"] == "lrn:agents/tfg-synthetic/environments/local"
    assert agent_plan.project is None
    assert not {r["id"] for r in agent_plan.runs} & {r["id"] for r in project_plan.runs}
    again = plan_for(tmp_path, *events, project=None, agent_id="tfg-synthetic", agent_environment=" LOCAL ")
    assert [r["id"] for r in again.runs] == [r["id"] for r in agent_plan.runs]  # case/space normalised
    staging = plan_for(tmp_path, *events, project=None, agent_id="tfg-synthetic", agent_environment="staging")
    assert not {r["id"] for r in staging.runs} & {r["id"] for r in agent_plan.runs}


def test_first_project_send_ids_remain_reproducible():
    events, errors = export.load_events([SYNTHETIC_EVIDENCE])
    plan = export.build_plan(events, "tfg-synthetic")
    ledger = [json.loads(l) for l in (FIRST_SEND / "ledger_copy.jsonl").read_text().splitlines()]
    assert [t["run_ids"] for t in plan.traces] == [e["run_ids"] for e in ledger]


def test_ledger_separates_destinations_including_pre_v3_entries(tmp_path):
    plan_project = plan_for(tmp_path, llm_call(), project="tfg-synthetic")
    plan_agent = plan_for(tmp_path, llm_call(), project=None, **AGENT)
    ledger = tmp_path / "ledger.jsonl"
    old_entry = {"project": "tfg-synthetic", "root_id": plan_project.traces[0]["root_id"],
                 "run_ids": plan_project.traces[0]["run_ids"], "outcome": "accepted", "exporter_version": "2"}
    ledger.write_text(json.dumps(old_entry) + "\n", encoding="utf-8")
    assert export.send(plan_project, FakeClient(), ledger, allow_unknown_provenance=True)["skipped_in_ledger"] == 1
    client = FakeClient()
    report = export.send(plan_agent, client, ledger, allow_unknown_provenance=True)
    assert report["skipped_in_ledger"] == 0 and report["posted"] == 2
    assert report["destination"] == {"mode": "agent", "agent_id": "tfg-synthetic", "agent_environment": "local",
                                     "lrn": "lrn:agents/tfg-synthetic/environments/local"}
    entry = json.loads(ledger.read_text().splitlines()[-1])
    assert entry["destination"]["key"] == "lrn:agents/tfg-synthetic/environments/local" and entry["project"] is None
    assert export.send(plan_agent, client, ledger, allow_unknown_provenance=True)["skipped_in_ledger"] == 1
    for call in client.created:
        assert "project_name" not in call and call["address"] == {"kind": "AGENT", "id": "tfg-synthetic",
                                                                  "environment": "LOCAL"}


def test_real_sdk_payload_has_exactly_one_destination_per_run(tmp_path):
    """langsmith >= 0.14.9 Client over a fake HTTP session: effective wire payload, no network."""
    langsmith = pytest.importorskip("langsmith")
    if not hasattr(__import__("langsmith.address", fromlist=["agent_address"]), "agent_address"):
        pytest.skip("installed langsmith has no agent addressing")

    class Response:
        status_code, text, reason, headers = 200, "{}", "OK", {}

        def json(self):
            return {}

        def raise_for_status(self):
            pass

    class Session:
        headers = {}

        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, json.loads(kwargs["data"]), dict(kwargs.get("headers") or {})))
            return Response()

        def mount(self, *args, **kwargs):
            pass

        def close(self):
            pass

    destinations = {}
    for name, options in (("agent", {"project": None, **AGENT}), ("project", {"project": "tfg-synthetic"})):
        session = Session()
        client = langsmith.Client(api_key="fake-key-for-offline-test", api_url="http://127.0.0.1:9",
                                  session=session, auto_batch_tracing=False, omit_traced_runtime_info=True)
        plan = plan_for(tmp_path, llm_call(), tool_call(), **options)
        export.send(plan, client, tmp_path / f"{name}.jsonl", allow_unknown_provenance=True)
        assert len(session.calls) == len(plan.runs)
        destinations[name] = [{k: body[k] for k in ("address", "session_name", "session_id") if k in body}
                              for _, _, body, _ in session.calls]
        for _, url, _, headers in session.calls:
            assert url.endswith("/runs") and "fake-key-for-offline-test" not in json.dumps(destinations[name])
    assert destinations["agent"] == [{"address": "lrn:agents/tfg-synthetic/environments/local"}] * 2
    assert destinations["project"] == [{"session_name": "tfg-synthetic"}] * 2


def test_agent_dry_run_in_subprocess_has_no_network_credentials_or_sdk(tmp_path):
    path = write(tmp_path, llm_call(), tool_call())
    code = (
        "import socket, sys, os\n"
        "def deny(*a, **k): raise AssertionError('network used in dry-run')\n"
        "socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny\n"
        "from observability import langsmith_export as e\n"
        f"rc = e.main([{str(path)!r}, '--agent-id', 'tfg-synthetic', '--agent-environment', 'local'],"
        " client_factory=None)\n"
        "assert 'langsmith' not in sys.modules, 'langsmith imported in dry-run'\n"
        "sys.exit(rc)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT), "LANGSMITH_API_KEY": SECRET})
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout)
    assert out["destination"]["lrn"] == "lrn:agents/tfg-synthetic/environments/local" and out["project"] is None
    assert SECRET not in done.stdout + done.stderr


def test_cli_rejects_mixed_or_incomplete_destinations(tmp_path, capsys):
    path = str(write(tmp_path, llm_call()))
    for argv in ([path, "--project", "p", "--agent-id", "tfg-synthetic", "--agent-environment", "local"],
                 [path, "--agent-id", "tfg-synthetic"], [path, "--agent-environment", "local", "--project", "p"],
                 [path]):
        with pytest.raises(SystemExit):
            export.main(argv, client_factory=None)
    capsys.readouterr()


# --- provenance: not inferred from id names alone ------------------------------------------

def _hermes_like_context():
    """Stand-in whose type *name* matches Hermes' PluginContext; deliberately simulates the one
    signal the sink records. It proves the exporter's rule, not that Hermes ran."""
    cls = type("PluginContext", (), {"register_hook": lambda self, name, cb: None})
    cls.__module__ = "hermes_cli.plugins"
    return cls()


class _OtherContext:
    def register_hook(self, name, callback):
        pass


def _capture_dir(tmp_path, name, ctx, **env):
    directory = tmp_path / name
    sink = capture.register(ctx, environ={capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory), **env})
    return directory, sink


def _offline_usage_fixture(tmp_path):
    """The 37-in / 2-out preview fixture from 2026-10-21, built with the capture functions directly."""
    env = {capture.RUN_ENV: "OFFLINE-FIXTURE-usage-preview", capture.CASE_ENV: "ollama-shape"}
    summary = {"input_tokens": 37, "output_tokens": 2, "cache_read_tokens": 0, "cache_write_tokens": 0,
               "reasoning_tokens": 0, "request_count": 1, "prompt_tokens": 37, "total_tokens": 39}
    event = capture.llm_call_event(dict(
        session_id="s", task_id="t", turn_id="turn-1", api_request_id="turn-1:api:1", provider="custom",
        model="qwen3:4b", response_model="qwen3:4b", api_mode="chat_completions", finish_reason="stop",
        api_duration=0.9, started_at=1792500000.0, ended_at=1792500000.9, first_chunk_at=1792500000.3,
        api_call_count=1, message_count=2, assistant_tool_call_count=0, context_length=65536, usage=summary,
        response={"assistant_message": {"content": "OK", "tool_calls": []}}), env)
    return write(tmp_path, event, name="fixture.jsonl")


def test_offline_usage_fixture_is_unknown_provenance_and_blocked_by_default(tmp_path):
    path = _offline_usage_fixture(tmp_path)
    events, errors = export.load_events([path])
    plan = export.build_plan(events, agent_id="tfg-synthetic", agent_environment="local")
    assert [t["kind"] for t in plan.traces] == ["unknown_provenance"]
    llm = plan.runs[1]["extra"]["metadata"]
    assert llm["tfg_data_kind"] == "unknown_provenance" and llm["tfg_usage"]["input_tokens"]["value"] == 37
    with pytest.raises(export.ExportError, match="unknown provenance"):
        export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")
    assert export.verify_capture_provenance([path])["ok"] is False  # no sink record next to it
    with pytest.raises(export.ExportError, match="do not verify"):
        export.build_plan(events, agent_id="tfg-synthetic", agent_environment="local", provenance="captured",
                          provenance_check=export.verify_capture_provenance([path]))
    declared = export.build_plan(events, agent_id="tfg-synthetic", agent_environment="local", provenance="synthetic")
    assert declared.traces[0]["kind"] == "synthetic_fixture"
    assert declared.runs[1]["extra"]["metadata"]["tfg_provenance_basis"] == "declared_synthetic"
    assert declared.runs[0]["name"].startswith("SYNTHETIC · ") and "synthetic" in declared.runs[0]["tags"]
    with pytest.raises(export.ExportError, match="synthetic"):
        export.send(declared, FakeClient(), tmp_path / "ledger.jsonl")


def test_valid_capture_keeps_its_explicit_captured_path(tmp_path):
    directory, sink = _capture_dir(tmp_path, "real", _hermes_like_context(),
                                   **{capture.RUN_ENV: "run-2026-10-21", capture.CASE_ENV: "smoke"})
    sink.on_post_api_request(**post_api_kwargs_for_export())
    (path,) = directory.glob("hermes-events-*.jsonl")
    check = export.verify_capture_provenance([path])
    assert check["ok"] and check["files"][0]["records"] == 1
    events, errors = export.load_events([path])
    undeclared = export.build_plan(events, project="tfg-real")
    assert undeclared.traces[0]["kind"] == "unknown_provenance"  # the record alone is not a declaration
    plan = export.build_plan(events, project="tfg-real", provenance="captured", provenance_check=check)
    meta = plan.runs[1]["extra"]["metadata"]
    assert plan.traces[0]["kind"] == "captured_hermes_metadata" and "captured-metadata" in plan.runs[0]["tags"]
    assert meta["tfg_provenance_basis"] == "declared_captured_with_hermes_sink_provenance_record"
    assert not plan.runs[0]["name"].startswith(("SYNTHETIC", "UNKNOWN"))
    report = export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")  # no override flags needed
    assert report["posted"] == len(plan.runs)
    assert undeclared.runs[1]["id"] == plan.runs[1]["id"]  # provenance never changes run ids


def _withheld_only_capture(tmp_path):
    """A real sink capture (with provenance record) holding one untimed tool event: withheld by default."""
    directory, sink = _capture_dir(tmp_path, "withheld", _hermes_like_context())
    sink.on_post_tool_call(tool_name="mcp_tfg_get_mission_state", args={}, result="RESULT-TEXT", session_id="",
                           task_id="", tool_call_id="", turn_id="", api_request_id="", duration_ms=742, status="ok")
    (path,) = directory.glob("hermes-events-*.jsonl")
    return path


@pytest.mark.parametrize("declared, kind, match, allow", [
    (None, "unknown_provenance", "unknown provenance", {"allow_unknown_provenance": True}),
    ("synthetic", "synthetic_fixture", "synthetic traces", {"allow_synthetic": True})])
def test_withheld_only_input_is_blocked_by_default_and_summary_says_why(tmp_path, monkeypatch, capsys,
                                                                       declared, kind, match, allow):
    path = _withheld_only_capture(tmp_path)
    events, errors = export.load_events([path])
    plan = export.build_plan(events, "tfg-test", provenance=declared)
    assert plan.traces == [] and plan.runs == [] and plan.withheld[0]["kind"] == kind
    out = export.describe(plan)
    assert out["traces"] == 0 and out["withheld_traces"][0]["kind"] == kind
    (reason,) = out["blocked_for_send_by_default"]
    assert match in reason and "(in withheld traces)" in reason
    with pytest.raises(export.ExportError, match=f"{match}.*in withheld traces"):
        export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")
    assert not (tmp_path / "ledger.jsonl").exists()
    assert export.send(plan, FakeClient(), tmp_path / "ledger.jsonl", **allow)["posted"] == 0
    # CLI: blocked before the credential is read or a client is built.
    monkeypatch.setenv(export.API_KEY_ENV, SECRET)
    factory_calls = []
    argv = [str(path), "--project", "tfg-test", "--send", "--ledger", str(tmp_path / "cli.jsonl")]
    if declared:
        argv += ["--provenance", declared]
    with pytest.raises(export.ExportError, match="in withheld traces"):
        export.main(argv, client_factory=lambda: factory_calls.append(1))
    assert factory_calls == [] and SECRET not in capsys.readouterr().out


def test_withheld_only_verified_capture_keeps_current_behaviour(tmp_path):
    path = _withheld_only_capture(tmp_path)
    events, errors = export.load_events([path])
    plan = export.build_plan(events, "tfg-test", provenance="captured",
                             provenance_check=export.verify_capture_provenance([path]))
    assert plan.traces == [] and plan.withheld[0]["kind"] == "captured_hermes_metadata"
    assert export.describe(plan)["blocked_for_send_by_default"] == []
    report = export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")  # no override flags needed
    assert report["posted"] == 0 and report["withheld_untimed_traces"] == 1


def test_emitted_traces_keep_their_blocking_messages(tmp_path):
    events, errors = export.load_events([SYNTHETIC_EVIDENCE])
    plan = export.build_plan(events, "tfg-test")  # emitted synthetic trace plus withheld synthetic ones
    assert plan.traces and plan.withheld
    expected = "plan contains synthetic traces; pass --allow-synthetic to send them as synthetic"
    assert export.describe(plan)["blocked_for_send_by_default"] == [expected]
    with pytest.raises(export.ExportError) as caught:
        export.send(plan, FakeClient(), tmp_path / "ledger.jsonl")
    assert str(caught.value) == expected
    unknown = plan_for(tmp_path, llm_call())
    assert [t["kind"] for t in unknown.traces] == ["unknown_provenance"]
    (reason,) = export.describe(unknown)["blocked_for_send_by_default"]
    assert reason.startswith("plan contains traces of unknown provenance; declare --provenance")


def post_api_kwargs_for_export():
    return dict(session_id="s-1", task_id="t-1", turn_id="turn-1", api_request_id="turn-1:api:1",
                provider="custom", model="qwen3:4b", response_model="qwen3:4b", api_mode="chat_completions",
                finish_reason="stop", api_duration=0.5, started_at=1792500000.0, ended_at=1792500000.5,
                first_chunk_at=None, api_call_count=1, message_count=2, assistant_tool_call_count=0,
                context_length=65536, usage=None, response={})


@pytest.mark.parametrize("case", ["no_record", "non_hermes_context", "direct_sink", "mixed", "record_after_events",
                                  "symlinked_record"])
def test_captured_declaration_is_refused_without_verifiable_records(tmp_path, case):
    if case == "no_record":
        path = write(tmp_path, llm_call(), name="events.jsonl")
    elif case in ("non_hermes_context", "mixed", "record_after_events", "symlinked_record"):
        ctx = _OtherContext() if case == "non_hermes_context" else _hermes_like_context()
        directory, sink = _capture_dir(tmp_path, case, ctx)
        sink.on_post_api_request(**post_api_kwargs_for_export())
        (path,) = directory.glob("hermes-events-*.jsonl")
        (record,) = directory.glob("capture-provenance-*.json")
        if case == "mixed":
            capture.JsonlSink(directory)._write(capture.llm_call_event(post_api_kwargs_for_export(), {}))
        elif case == "record_after_events":
            data = json.loads(record.read_text())
            data["created_at_utc"] = "2099-01-01T00:00:00+00:00"
            record.write_text(json.dumps(data))
        elif case == "symlinked_record":
            target = tmp_path / "elsewhere.json"
            record.rename(target)
            record.symlink_to(target)
    else:  # direct_sink
        directory = tmp_path / "direct"
        capture.JsonlSink(directory)._write(capture.llm_call_event(post_api_kwargs_for_export(), {}))
        (path,) = directory.glob("hermes-events-*.jsonl")
    check = export.verify_capture_provenance([path])
    assert check["ok"] is False and check["files"][0]["problems"]
    events, _ = export.load_events([path])
    with pytest.raises(export.ExportError, match="do not verify"):
        export.build_plan(events, project="tfg-real", provenance="captured", provenance_check=check)


def test_synthetic_marker_overrides_a_valid_record_and_conflicts_with_captured(tmp_path):
    directory, sink = _capture_dir(tmp_path, "loader", _hermes_like_context(),
                                   **{capture.RUN_ENV: "SYNTHETIC-loader", capture.CASE_ENV: "fixtures"})
    sink.on_post_api_request(**post_api_kwargs_for_export())
    (path,) = directory.glob("hermes-events-*.jsonl")
    check = export.verify_capture_provenance([path])
    assert check["ok"]
    events, _ = export.load_events([path])
    assert export.build_plan(events, project="p").traces[0]["kind"] == "synthetic_fixture"
    with pytest.raises(export.ExportError, match="synthetic marker"):
        export.build_plan(events, project="p", provenance="captured", provenance_check=check)


def test_cli_provenance_flags_and_historical_evidence_stay_synthetic(tmp_path, capsys):
    directory, sink = _capture_dir(tmp_path, "real", _hermes_like_context(),
                                   **{capture.RUN_ENV: "run-2026-10-21", capture.CASE_ENV: "smoke"})
    sink.on_post_api_request(**post_api_kwargs_for_export())
    (path,) = directory.glob("hermes-events-*.jsonl")
    assert export.main([str(path), "--project", "tfg-real", "--provenance", "captured"], client_factory=None) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["captured_traces"] == 1 and out["unknown_provenance_traces"] == 0 and out["provenance_check"]["ok"]
    with pytest.raises(export.ExportError, match="do not verify"):
        export.main([str(_offline_usage_fixture(tmp_path)), "--project", "p", "--provenance", "captured"],
                    client_factory=None)
    assert export.main([str(SYNTHETIC_EVIDENCE), "--agent-id", "tfg-synthetic", "--agent-environment", "local"],
                       client_factory=None) == 0
    hist = json.loads(capsys.readouterr().out)
    assert hist["synthetic_traces"] == 1 and hist["unknown_provenance_traces"] == 0
    assert [r["id"] for r in hist["prepared_runs"]][0] == "a9b215b9-8ea1-52e0-84a4-e8acbacab2e3"
