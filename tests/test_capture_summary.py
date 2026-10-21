"""Offline tests for the capture summary tool.

Every number here comes from SYNTHETIC fixtures built with the capture functions; they verify the
summary's rules and are not performance results of any model.
"""
import json
from pathlib import Path

import pytest

from observability import capture_summary as summary
from observability import langsmith_export as ls_export
from observability.hermes_capture import capture

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_EVIDENCE = (ROOT / "evaluation" / "observability" / "hermes_loader_hooks_synthetic_2026_10_20"
                      / "capture" / "hermes-events-2026-10-20.jsonl")
CONTENT = "PROMPT-TEXT HOME 41.27531, 1.98712"


def hermes_like_context():
    """Type name matches Hermes' PluginContext: simulates the sink's only origin signal."""
    cls = type("PluginContext", (), {"register_hook": lambda self, name, cb: None})
    cls.__module__ = "hermes_cli.plugins"
    return cls()


def usage(**counters):
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "reasoning_tokens": 0, "request_count": 1}
    base.update(counters)
    base["prompt_tokens"] = base["input_tokens"] + base["cache_read_tokens"] + base["cache_write_tokens"]
    base["total_tokens"] = base["prompt_tokens"] + base["output_tokens"]
    return base


def call(turn, start, duration, *, model="qwen3:4b", usage_summary=None, **override):
    kwargs = dict(session_id="s", task_id="t", turn_id=turn, api_request_id=f"{turn}:api:1", provider="custom",
                  model=model, response_model=model, api_mode="chat_completions", finish_reason="stop",
                  api_duration=duration, started_at=start, ended_at=start + duration, first_chunk_at=None,
                  api_call_count=1, message_count=2, assistant_tool_call_count=0, context_length=65536,
                  usage=usage_summary, response={"assistant_message": {"content": CONTENT, "tool_calls": []}})
    kwargs.update(override)
    return kwargs


def write_capture(tmp_path, run_id, case_id, emit, *, ctx=None, name="capture"):
    directory = tmp_path / name
    sink = capture.register(ctx or hermes_like_context(), environ={
        capture.ENABLE_ENV: "1", capture.DIR_ENV: str(directory), capture.RUN_ENV: run_id, capture.CASE_ENV: case_id})
    emit(sink)
    (path,) = directory.glob("hermes-events-*.jsonl")
    return path


def run_summary(paths, provenance=None, **options):
    events, errors = ls_export.load_events(paths)
    assert errors == []
    check = ls_export.verify_capture_provenance(paths) if provenance == "captured" else None
    kinds = summary.classify(events, provenance, check)
    return summary.summarize(events, kinds, **options)


def two_model_capture(tmp_path):
    def emit(sink):
        sink.on_post_api_request(**call("turn-1", 1792500000.0, 1.0, usage_summary=usage(input_tokens=40, output_tokens=5)))
        sink.on_post_api_request(**call("turn-2", 1792500010.0, 3.0, usage_summary=usage(input_tokens=60, output_tokens=0)))
        sink.on_post_api_request(**call("turn-3", 1792500020.0, 2.0, usage_summary=None))
        sink.on_post_api_request(**call("turn-4", 1792500030.0, 5.0, model="llama3:8b",
                                        usage_summary=usage(input_tokens=50, output_tokens=7, reasoning_tokens=3)))
        sink.on_api_request_error(session_id="s", task_id="t", turn_id="turn-5", api_request_id="turn-5:api:1",
                                  provider="custom", model="llama3:8b", api_mode="chat_completions", api_duration=2.0,
                                  started_at=1792500040.0, ended_at=1792500042.0, api_call_count=1, status_code=429,
                                  retry_count=1, max_retries=3, retryable=True, reason="rate_limited",
                                  error={"type": "RateLimitError", "message": CONTENT})
        sink.on_post_tool_call(tool_name="terminal", duration_ms=742, status="ok", session_id="s", turn_id="turn-1")
        sink.on_post_tool_call(tool_name="terminal", duration_ms=0, status="blocked", session_id="s", turn_id="turn-1")
        sink.on_post_tool_call(tool_name="terminal", duration_ms=30000, status="timeout", session_id="s", turn_id="turn-2")
    return write_capture(tmp_path, "exp-a", "case-1", emit)


# --- provenance gate -----------------------------------------------------------------------

def test_comparative_results_only_include_declared_and_verified_captures(tmp_path):
    path = two_model_capture(tmp_path)
    undeclared = run_summary([path])
    assert undeclared["comparative"]["groups"] == [] and undeclared["excluded_from_comparison"] == {
        "unknown_provenance": 8}
    assert "nothing to compare" in undeclared["comparative"]["warning"]
    declared = run_summary([path], provenance="captured")
    assert declared["excluded_from_comparison"] == {} and len(declared["comparative"]["groups"]) == 2


def test_synthetic_and_unknown_are_excluded_by_default_and_shown_apart_on_request(tmp_path):
    events, _ = ls_export.load_events([SYNTHETIC_EVIDENCE])
    kinds = summary.classify(events)
    report = summary.summarize(events, kinds)
    assert report["comparative"]["groups"] == [] and report["excluded_from_comparison"] == {"synthetic_fixture": 6}
    shown = summary.summarize(events, kinds, include_noncomparative=True)
    section = shown["non_comparative_synthetic_or_unknown"]
    assert section["warning"].startswith("NOT PERFORMANCE RESULTS") and section["groups"]
    assert shown["comparative"]["groups"] == []


def test_captured_declaration_needs_verified_records_and_ids_are_not_trusted(tmp_path):
    other = type("Other", (), {"register_hook": lambda self, n, c: None})()
    path = write_capture(tmp_path, "exp-a", "case-1",
                         lambda s: s.on_post_api_request(**call("t", 1792500000.0, 1.0)), ctx=other)
    with pytest.raises(ls_export.ExportError, match="do not verify"):
        run_summary([path], provenance="captured")
    marked = write_capture(tmp_path, "SYNTHETIC-exp", "case-1",
                           lambda s: s.on_post_api_request(**call("t", 1792500000.0, 1.0)), name="marked")
    with pytest.raises(ls_export.ExportError, match="synthetic marker"):
        run_summary([marked], provenance="captured")


# --- grouping, sample sizes and failures --------------------------------------------------

def test_groups_by_experiment_case_and_model_with_sample_sizes_and_failures(tmp_path):
    first = two_model_capture(tmp_path)
    second = write_capture(tmp_path, "exp-b", "case-2",
                           lambda s: s.on_post_api_request(**call("t", 1792500100.0, 1.5,
                                                                  usage_summary=usage(input_tokens=10, output_tokens=1))),
                           name="other")
    report = run_summary([first, second], provenance="captured")
    keys = [(g["experiment"], g["case_id"], g["model"]) for g in report["comparative"]["groups"]]
    assert keys == [("exp-a", "case-1", "custom/llama3:8b"), ("exp-a", "case-1", "custom/qwen3:4b"),
                    ("exp-b", "case-2", "custom/qwen3:4b")]
    qwen = report["comparative"]["groups"][1]  # exp-a / case-1 / custom/qwen3:4b
    assert qwen["sample_size"] == {"llm_calls": 3, "llm_errors": 0, "calls_with_usage": 2, "calls_without_usage": 1,
                                   "calls_with_measured_latency": 3, "calls_without_measured_latency": 0}
    llama = report["comparative"]["groups"][0]
    assert llama["failures"]["llm_error_count"] == 1 and llama["failures"]["error_types"] == {"RateLimitError": 1}
    assert llama["failures"]["status_codes"] == {"429": 1}
    assert llama["cost"] == {"computed": False, "reason": "no declared tariffs"}


# --- token rules ---------------------------------------------------------------------------

def test_absent_usage_is_never_zero_and_unconfirmed_zeros_are_separate(tmp_path):
    report = run_summary([two_model_capture(tmp_path)], provenance="captured")
    qwen = report["comparative"]["groups"][1]["tokens"]["normalized_counters"]
    output = qwen["output_tokens"]
    assert output["status_counts"] == {"nonzero_normalized": 1, "usage_absent": 1, "zero_unconfirmed": 1}
    assert output["nonzero_values"]["n"] == 1 and output["nonzero_values"]["sum"] == 5
    assert output["received_values_including_unconfirmed_zeros"]["n"] == 2  # the absent call is not a 0
    assert output["absent_or_redacted"] == 1
    assert qwen["input_tokens"]["nonzero_values"]["sum"] == 100
    assert qwen["reasoning_tokens"]["nonzero_values"] is None  # only unconfirmed zeros and one absence


def test_derived_sums_are_reported_apart_and_never_added_to_counters(tmp_path):
    report = run_summary([two_model_capture(tmp_path)], provenance="captured")
    tokens = report["comparative"]["groups"][1]["tokens"]
    derived = tokens["derived_sums_not_additive_with_counters"]
    assert derived["total_tokens"]["kind"] == "derived_sum_computed_by_hermes"
    assert derived["total_tokens"]["nonzero_values"]["sum"] == 105  # Hermes' own sums: 45 + 60
    counters = tokens["normalized_counters"]
    assert set(counters) == set(capture.NORMALIZED_USAGE_FIELDS)
    assert "total_tokens" not in counters and "prompt_tokens" not in counters
    assert all(v["kind"] == "hermes_normalized_provider_counter" for v in counters.values())


# --- latency -------------------------------------------------------------------------------

def test_latency_uses_only_valid_hermes_intervals(tmp_path):
    def emit(sink):
        sink.on_post_api_request(**call("t1", 1792500000.0, 1.0))
        sink.on_post_api_request(**call("t2", 1792500010.0, 3.0))
        sink.on_post_api_request(**call("t3", 1792500020.0, 2.0, started_at=None, ended_at=None))
        sink.on_post_api_request(**call("t4", 1792500030.0, 9.0, ended_at=1792500031.0))  # inconsistent duration
    path = write_capture(tmp_path, "exp", "case", emit)
    qwen = run_summary([path], provenance="captured")["comparative"]["groups"][0]
    latency = qwen["latency_s"]
    assert latency["stats"]["n"] == 2 and latency["stats"]["median"] == pytest.approx(2.0)
    assert latency["excluded"] == {"epochs_absent": 1, "inconsistent_with_api_duration": 1}
    assert qwen["sample_size"]["calls_without_measured_latency"] == 2
    assert "includes retries" in latency["scope"]


def test_tool_durations_count_only_measured_values(tmp_path):
    report = run_summary([two_model_capture(tmp_path)], provenance="captured")
    (tools,) = report["comparative"]["tools"]
    assert tools["tool_calls"] == 3 and tools["measured_duration_ms"]["n"] == 1
    assert tools["measured_duration_ms"]["sum"] == 742
    assert tools["duration_source_counts"] == {"hermes_reported_ms": 1, "timeout_configured_not_measured": 1,
                                               "zero_default_or_below_1ms": 1}


# --- no content, CLI -----------------------------------------------------------------------

def test_report_contains_no_content_and_cli_reports_errors(tmp_path, capsys):
    path = two_model_capture(tmp_path)
    assert summary.main([str(path), "--provenance", "captured"]) == 0
    out = capsys.readouterr().out
    assert CONTENT not in out and "PROMPT-TEXT" not in out and json.loads(out)["comparative"]["groups"]
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{oops\n", encoding="utf-8")
    assert summary.main([str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["errors"]
