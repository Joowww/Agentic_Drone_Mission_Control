"""Offline tests for the optional Hermes capture plugin.

Synthetic payloads follow the kwargs Hermes passes to post_api_request,
api_request_error and post_tool_call. The contract tests parse the installed
Hermes source with ``ast`` (read-only, never imported or executed); they skip
when that checkout is not present. No Hermes process, model, MCP or network.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat

from jsonschema import Draft202012Validator, FormatChecker
import pytest

import observability.hermes_capture as plugin
from observability.hermes_capture import capture

PACKAGE = Path(capture.__file__).parent
VALIDATOR = Draft202012Validator(json.loads((PACKAGE / "event.schema.json").read_text(encoding="utf-8")),
                                 format_checker=FormatChecker())
HERMES = Path(os.environ.get("TFG_HERMES_AGENT_ROOT", Path.home() / ".hermes" / "hermes-agent"))

SECRET = "sk-ant-THISISAFAKEKEY0123456789abcdef"
PROMPT = "Parcela Loma: HOME 41.27531, 1.98712 altitud 30 m"
PATH = "/home/joelm/TFG/Agentic_Drone_Mission_Control/missions/generated/drafts/x/draft.json"
SENTINELS = (SECRET, PROMPT, PATH, "41.27531", "1.98712", "Parcela", "draft.json", "localhost:11434",
             "raw-session-1", "raw-turn-1", "raw-call-1", "Authorization")


class FakeContext:
    """Records register_hook(hook_name, callback) calls; not a Hermes PluginContext."""

    def __init__(self):
        self.hooks = []

    def register_hook(self, hook_name, callback):
        self.hooks.append((hook_name, callback))


def enabled_env(tmp_path, **extra):
    return {capture.ENABLE_ENV: "1", capture.DIR_ENV: str(tmp_path / "capture"), **extra}


def post_api_kwargs(**override):
    # Shape of agent/turn_response_intake.py:_fire_post_api_request_hook; usage as built by
    # _usage_summary_for_api_request_hook (asdict(CanonicalUsage) without raw_usage + totals).
    kwargs = dict(
        task_id="raw-task-1", turn_id="raw-turn-1", api_request_id="raw-turn-1:api:2", session_id="raw-session-1",
        platform="cli", model="anthropic/claude-sonnet-5-5", provider="openrouter",
        base_url=f"http://localhost:11434/v1?key={SECRET}", api_mode="chat_completions",
        api_call_count=2, api_duration=1.25, started_at=1792246298.0, ended_at=1792246299.25,
        first_chunk_at=1792246298.4, finish_reason="tool_calls", message_count=7,
        response_model="anthropic/claude-sonnet-5-5",
        response={"model": "anthropic/claude-sonnet-5-5", "upstream_provider": "Anthropic",
                  "finish_reason": "tool_calls",
                  "assistant_message": {"role": "assistant", "content": PROMPT, "tool_calls": [
                      {"id": "raw-call-1", "function": {"name": "mcp_tfg_update_mission_draft",
                                                        "arguments": json.dumps({"home": PROMPT, "path": PATH})}}]},
                  "usage": {"input_tokens": 1200}},
        usage={"input_tokens": 1200, "output_tokens": 85, "cache_read_tokens": 0, "cache_write_tokens": 0,
               "reasoning_tokens": 0, "request_count": 1, "prompt_tokens": 1200, "total_tokens": 1285},
        context_length=200000, assistant_message=object(), assistant_content_chars=len(PROMPT),
        assistant_tool_call_count=1, moa_references=[{"text": PROMPT}],
    )
    kwargs.update(override)
    return kwargs


def read_events(tmp_path):
    files = sorted((tmp_path / "capture").glob("hermes-events-*.jsonl"))
    lines = [line for f in files for line in f.read_text(encoding="utf-8").splitlines()]
    return [json.loads(line) for line in lines], "\n".join(lines)


# --- activation -----------------------------------------------------------------------------

@pytest.mark.parametrize("env", [
    {},
    {capture.ENABLE_ENV: "1"},
    {capture.ENABLE_ENV: "true", capture.DIR_ENV: "/tmp/x"},
    {capture.ENABLE_ENV: "1", capture.DIR_ENV: "relative/dir"},
    {capture.DIR_ENV: "/tmp/x"},
])
def test_disabled_unless_explicit_flag_and_absolute_directory(env):
    ctx = FakeContext()
    assert capture.register(ctx, environ=env) is None
    assert ctx.hooks == []


def test_default_process_environment_registers_nothing(monkeypatch):
    monkeypatch.delenv(capture.ENABLE_ENV, raising=False)
    monkeypatch.delenv(capture.DIR_ENV, raising=False)
    ctx = FakeContext()
    plugin.register(ctx)
    assert ctx.hooks == []


def test_enabled_registers_only_observer_hooks_declared_in_manifest(tmp_path):
    ctx = FakeContext()
    capture.register(ctx, environ=enabled_env(tmp_path))
    names = [name for name, _ in ctx.hooks]
    assert names == list(capture.HOOKS)
    assert not any(name.startswith("pre_") or name.startswith("transform_") for name in names)
    manifest = (PACKAGE / "plugin.yaml").read_text(encoding="utf-8")
    declared = [line.strip()[2:] for line in manifest.split("provides_hooks:")[1].splitlines() if line.strip()]
    assert declared == names
    assert not (tmp_path / "capture").exists()  # nothing written until a hook fires


# --- llm_call -------------------------------------------------------------------------------

def test_llm_call_records_provider_usage_latency_and_tool_names_only(tmp_path):
    env = enabled_env(tmp_path, **{capture.RUN_ENV: "run-2026-10-20", capture.CASE_ENV: "S1"})
    sink = capture.register(FakeContext(), environ=env)
    assert sink.on_post_api_request(**post_api_kwargs()) is None
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["event_type"] == "llm_call" and event["schema"] == capture.SCHEMA
    assert (event["provider"], event["model"], event["upstream_provider"]) == (
        "openrouter", "anthropic/claude-sonnet-5-5", "Anthropic")
    assert event["usage_source"] == "hermes_normalized_summary"
    assert event["usage"]["input_tokens"] == {"value": 1200, "status": "nonzero_normalized"}
    assert event["usage"]["output_tokens"] == {"value": 85, "status": "nonzero_normalized"}
    assert event["usage"]["total_tokens"] == {"value": 1285, "status": "derived_nonzero"}
    assert "request_count" not in event["usage"]
    assert (event["timing_source"], event["timing_scope"]) == ("hermes_hook_wall_clock", "api_call_from_first_attempt")
    assert event["api_duration_s"] == 1.25
    assert event["first_chunk_offset_s"] == pytest.approx(0.4, abs=1e-6)
    assert event["requested_tool_names"] == ["mcp_tfg_update_mission_draft"]
    assert event["retry_count"] is None and "retry_count" in event["absent_fields"]
    assert (event["run_id"], event["case_id"]) == ("run-2026-10-20", "S1")
    assert event["session_ref"].startswith("sha256:")
    for sentinel in SENTINELS:
        assert sentinel not in raw
    assert "base_url" not in event and "assistant_message" not in event


def _summary(**counters):
    """A post_api_request usage summary as Hermes builds it: every canonical field present."""
    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "reasoning_tokens": 0, "request_count": 1}
    base.update(counters)
    base["prompt_tokens"] = base["input_tokens"] + base["cache_read_tokens"] + base["cache_write_tokens"]
    base["total_tokens"] = base["prompt_tokens"] + base["output_tokens"]
    return base


def test_legitimate_provider_zero_is_kept_but_not_claimed_confirmed(tmp_path):
    # e.g. provider reported reasoning_tokens=0 and cache_read_tokens=0 explicitly
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage=_summary(input_tokens=900, output_tokens=40)))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["usage"]["reasoning_tokens"] == {"value": 0, "status": "zero_unconfirmed"}
    assert event["usage"]["cache_read_tokens"] == {"value": 0, "status": "zero_unconfirmed"}
    assert event["usage"]["prompt_tokens"] == {"value": 900, "status": "derived_nonzero"}
    assert "usage.reasoning_tokens" in event["ambiguous_zero_fields"]
    assert "usage.reasoning_tokens" not in event["absent_fields"]


def test_default_zero_summary_is_kept_as_received_not_turned_into_absence(tmp_path):
    # usage object present but no recognised field: CanonicalUsage defaults, identical on the wire
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage=_summary()))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["usage_source"] == "hermes_normalized_summary" and event["usage"] is not None
    for name in capture.NORMALIZED_USAGE_FIELDS:
        assert event["usage"][name] == {"value": 0, "status": "zero_unconfirmed"}
    for name in capture.DERIVED_USAGE_FIELDS:
        assert event["usage"][name] == {"value": 0, "status": "derived_zero"}
    assert set(event["ambiguous_zero_fields"]) == {f"usage.{name}" for name in capture.USAGE_FIELDS}
    assert not any(field.startswith("usage") for field in event["absent_fields"])


def test_usage_absent_from_the_hook_is_null_never_zero(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage=None, first_chunk_at=None, response=None))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["usage"] is None and event["usage_source"] == "absent"
    assert "usage" in event["absent_fields"] and event["ambiguous_zero_fields"] == []
    assert event["first_chunk_offset_s"] is None and "first_chunk_offset_s" in event["absent_fields"]
    assert event["requested_tool_names"] is None


def test_invalid_or_missing_usage_counters_are_flagged_individually(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(usage={"input_tokens": -1, "output_tokens": True,
                                                      "total_tokens": "85", "prompt_tokens": 1.5}))
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    for name in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens"):
        assert event["usage"][name] == {"value": None, "status": "redacted"}
        assert f"usage.{name}" in event["redacted_fields"]
    for name in ("cache_read_tokens", "cache_write_tokens", "reasoning_tokens"):
        assert event["usage"][name] == {"value": None, "status": "absent"}
        assert f"usage.{name}" in event["absent_fields"]


def test_inconsistent_first_chunk_offset_is_redacted(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs(first_chunk_at=1792246300.0))  # after ended_at
    sink.on_post_api_request(**post_api_kwargs(first_chunk_at=1792246297.0))  # before started_at
    events, _ = read_events(tmp_path)
    for event in events:
        VALIDATOR.validate(event)
        assert event["first_chunk_offset_s"] is None and "first_chunk_offset_s" in event["redacted_fields"]


def test_secret_like_or_malformed_identifiers_are_redacted(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path, **{capture.CASE_ENV: PROMPT}))
    sink.on_post_api_request(**post_api_kwargs(model=SECRET, provider="http://evil/key", api_mode="a b",
                                               api_duration=float("nan"), message_count=-3))
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert {"model", "provider", "api_mode", "api_duration_s", "message_count"} <= set(event["redacted_fields"])
    assert event["case_id"] is None
    assert SECRET not in raw and "evil" not in raw and PROMPT not in raw


# --- llm_error ------------------------------------------------------------------------------

def test_api_error_keeps_retry_evidence_and_status_but_drops_message_and_request(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_api_request_error(
        task_id="t", turn_id="raw-turn-1", api_request_id="raw-turn-1:api:2", session_id="raw-session-1",
        platform="cli", model="qwen3:4b", provider="ollama", base_url="http://localhost:11434",
        api_mode="chat_completions", api_call_count=1, api_duration=30.0, started_at=1.0, ended_at=31.0,
        status_code=429, retry_count=1, max_retries=3, retryable=True, reason="rate_limited",
        error={"type": "RateLimitError", "message": f"Authorization: Bearer {SECRET} for {PROMPT}"},
        request={"method": "POST", "body": {"messages": [{"content": PROMPT}], "api_key": SECRET}},
    )
    sink.on_post_api_request(**post_api_kwargs())
    (error, call), raw = read_events(tmp_path)
    VALIDATOR.validate(error)
    assert (error["status_code"], error["retry_count"], error["max_retries"], error["retryable"]) == (429, 1, 3, True)
    assert (error["error_type"], error["model"], error["provider"]) == ("RateLimitError", "qwen3:4b", "ollama")
    assert error["api_request_ref"] == call["api_request_ref"]  # same API call across its retries
    assert call["retry_count"] is None
    for sentinel in SENTINELS:
        assert sentinel not in raw


# --- tool_call ------------------------------------------------------------------------------

def test_tool_call_keeps_name_duration_status_and_drops_args_and_result(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_tool_call(
        tool_name="mcp_tfg_update_mission_draft", args={"updates": {"home_latitude": 41.27531}, "path": PATH},
        result=json.dumps({"draft": PROMPT, "error": f"bad {SECRET}"}), task_id="t", session_id="raw-session-1",
        tool_call_id="raw-call-1", turn_id="raw-turn-1", api_request_id="r", duration_ms=742, status="error",
        error_type="tool_error", error_message=f"{PROMPT} {PATH}", middleware_trace=[{"note": PROMPT}],
    )
    (event,), raw = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert (event["tool_name"], event["duration_ms_received"], event["duration_ms_measured"],
            event["duration_source"], event["status"], event["error_type"]) == (
        "mcp_tfg_update_mission_draft", 742, 742, "hermes_reported_ms", "error", "tool_error")
    for sentinel in SENTINELS:
        assert sentinel not in raw


@pytest.mark.parametrize("kwargs, received, source, listed", [
    ({"duration_ms": 0, "status": "blocked"}, 0, "zero_default_or_below_1ms", "ambiguous_zero_fields"),
    ({"duration_ms": 0, "status": "ok"}, 0, "zero_default_or_below_1ms", "ambiguous_zero_fields"),
    ({"duration_ms": 30000, "status": "timeout"}, 30000, "timeout_configured_not_measured", None),
    ({"status": "ok"}, None, "absent", "absent_fields"),
    ({"duration_ms": -5, "status": "ok"}, None, "redacted", "redacted_fields"),
])
def test_tool_durations_that_are_not_measurements_are_never_measured(tmp_path, kwargs, received, source, listed):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_tool_call(tool_name="terminal", **kwargs)
    (event,), _ = read_events(tmp_path)
    VALIDATOR.validate(event)
    assert event["duration_ms_received"] == received
    assert event["duration_ms_measured"] is None and event["duration_source"] == source
    if listed:
        assert "duration_ms" in event[listed]


# --- containment ----------------------------------------------------------------------------

def test_write_failures_never_raise_or_print(tmp_path, capfd):
    blocker = tmp_path / "capture"
    blocker.write_text("not a directory", encoding="utf-8")
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    assert sink.on_post_api_request(**post_api_kwargs()) is None
    assert sink.on_post_tool_call(tool_name="x", args={"secret": SECRET}) is None
    assert sink.on_api_request_error(error={"message": SECRET}) is None
    assert sink.failures == 3
    assert blocker.read_text(encoding="utf-8") == "not a directory"
    out, err = capfd.readouterr()
    assert out == "" and err == ""


def test_successful_capture_writes_nothing_to_stdout_or_stderr(tmp_path, capfd):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(**post_api_kwargs())
    sink.on_post_tool_call(tool_name="x", duration_ms=3, status="ok")
    assert capfd.readouterr() == ("", "")


def test_unexpected_payload_types_never_raise(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    sink.on_post_api_request(response=["not", "a", "dict"], usage=["x"], started_at="soon", first_chunk_at=2)
    sink.on_api_request_error(error="plain string", status_code="500")
    (llm, error), _ = read_events(tmp_path)
    VALIDATOR.validate(llm)
    VALIDATOR.validate(error)
    assert sink.failures == 0 and error["status_code"] is None and "status_code" in error["redacted_fields"]


def test_files_are_private_append_only_and_lines_stay_whole_under_threads(tmp_path):
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: sink.on_post_tool_call(tool_name=f"tool_{i}", duration_ms=i + 1, status="ok"),
                      range(64)))
    events, _ = read_events(tmp_path)
    assert len(events) == 64 and {e["duration_ms_measured"] for e in events} == set(range(1, 65))
    (path,) = (tmp_path / "capture").glob("*.jsonl")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "capture").stat().st_mode) == 0o700


def test_symlinked_event_file_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep", encoding="utf-8")
    directory = tmp_path / "capture"
    directory.mkdir(mode=0o700)
    sink = capture.register(FakeContext(), environ=enabled_env(tmp_path))
    day = capture.datetime.now(capture.timezone.utc).isoformat()[:10]
    (directory / f"hermes-events-{day}.jsonl").symlink_to(target)
    sink.on_post_tool_call(tool_name="x")
    assert target.read_text(encoding="utf-8") == "keep"
    assert sink.failures == 1


# --- static contract with the installed Hermes source (read-only, never imported) -----------

requires_hermes = pytest.mark.skipif(not (HERMES / "hermes_cli" / "plugins.py").is_file(),
                                     reason=f"Hermes source not found at {HERMES}")


def _tree(relative):
    return ast.parse((HERMES / relative).read_text(encoding="utf-8"))


def _function(tree, name):
    return next(node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def _hook_call_keywords(relative, function, hook):
    calls = [node for node in ast.walk(_function(_tree(relative), function)) if isinstance(node, ast.Call)
             and ast.unparse(node.func).split(".")[-1] in {"invoke_hook", "_invoke_hook"}  # not has_hook()
             and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == hook]
    assert len(calls) == 1, f"{relative}:{function} must dispatch {hook} exactly once"
    return {kw.arg for kw in calls[0].keywords if kw.arg}, [kw.value for kw in calls[0].keywords if kw.arg is None]


def _class_fields(relative, name):
    node = next(n for n in ast.walk(_tree(relative)) if isinstance(n, ast.ClassDef) and n.name == name)
    return {s.target.id: s.value for s in node.body if isinstance(s, ast.AnnAssign)}


@requires_hermes
def test_hermes_commit_matches_the_reviewed_contract_or_is_reported():
    head = (HERMES / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        head = (HERMES / ".git" / head[5:]).read_text(encoding="utf-8").strip()
    if head != capture.VERIFIED_HERMES_COMMIT:
        pytest.skip(f"Hermes {head[:10]} differs from reviewed {capture.VERIFIED_HERMES_COMMIT[:10]}; "
                    "structural contract tests below still run")


@requires_hermes
def test_hermes_declares_our_hooks_and_plugin_registration_api():
    tree = _tree("hermes_cli/plugins.py")
    valid = next(node.value for node in ast.walk(tree) if isinstance(node, ast.AnnAssign)
                 and getattr(node.target, "id", None) == "VALID_HOOKS")
    names = {elt.value for elt in valid.elts if isinstance(elt, ast.Constant)}
    assert set(capture.HOOKS) <= names
    register_hook = _function(tree, "register_hook")
    assert [a.arg for a in register_hook.args.args] == ["self", "hook_name", "callback"]
    loader = (HERMES / "hermes_cli" / "plugins_loader.py").read_text(encoding="utf-8")
    assert 'getattr(module, "register", None)' in loader and "register_fn(ctx)" in loader
    assert "submodule_search_locations=[str(plugin_dir)]" in loader  # relative ``from .capture`` import
    discovery = (HERMES / "hermes_cli" / "plugins_discovery.py").read_text(encoding="utf-8")
    assert 'get_hermes_home() / "plugins"' in discovery and "not in plugins.enabled" in discovery
    manifest = (HERMES / "hermes_cli" / "plugins_manifest.py").read_text(encoding="utf-8")
    assert 'data.get("name", plugin_dir.name)' in manifest and 'data.get("provides_hooks"' in manifest


@requires_hermes
def test_post_api_request_payload_provides_every_field_we_read():
    keywords, spread = _hook_call_keywords("agent/turn_response_intake.py", "_fire_post_api_request_hook",
                                           "post_api_request")
    read = {"session_id", "task_id", "turn_id", "api_request_id", "provider", "model", "response_model",
            "api_mode", "finish_reason", "api_duration", "started_at", "ended_at", "first_chunk_at",
            "api_call_count", "message_count", "assistant_tool_call_count", "context_length", "usage", "response"}
    assert read <= keywords and not spread and "retry_count" not in keywords
    payload = _function(_tree("agent/api_request_hooks.py"), "_api_response_payload_for_hook")
    keys = {k.value for d in ast.walk(payload) if isinstance(d, ast.Dict) for k in d.keys if isinstance(k, ast.Constant)}
    assert {"upstream_provider", "assistant_message", "tool_calls"} <= keys
    usage = _class_fields("agent/usage_pricing.py", "CanonicalUsage")
    derived = ast.unparse(_function(_tree("agent/api_request_hooks.py"), "_usage_summary_for_api_request_hook"))
    assert set(capture.USAGE_FIELDS) <= set(usage) | {"prompt_tokens", "total_tokens"}
    assert "summary['prompt_tokens']" in derived and "summary['total_tokens']" in derived  # ast.unparse quoting
    assert set(capture.NORMALIZED_USAGE_FIELDS) <= set(usage)
    assert all(isinstance(usage[f], ast.Constant) and usage[f].value == 0 for f in capture.NORMALIZED_USAGE_FIELDS)
    # Why a received 0 stays unconfirmed: provider zero and missing field both fall back to 0,
    # and the raw provider usage is removed before the hook sees the summary.
    pricing = _tree("agent/usage_pricing.py")
    assert ast.unparse(_function(pricing, "_first_nonzero")).rstrip().endswith("if v), 0)")
    assert 'summary.pop("raw_usage", None)' in (HERMES / "agent" / "api_request_hooks.py").read_text(encoding="utf-8")
    canonical = next(n for n in ast.walk(pricing) if isinstance(n, ast.ClassDef) and n.name == "CanonicalUsage")
    properties = {f.name for f in canonical.body if isinstance(f, ast.FunctionDef)
                  and any(ast.unparse(d) == "property" for d in f.decorator_list)}
    assert set(capture.DERIVED_USAGE_FIELDS) <= properties  # sums computed by Hermes, not provider fields


@requires_hermes
def test_api_request_error_payload_provides_retry_evidence():
    keywords, spread = _hook_call_keywords("agent/api_request_hooks.py", "_invoke_api_request_error_hook",
                                           "api_request_error")
    assert {"provider", "model", "api_mode", "api_duration", "started_at", "ended_at", "api_call_count",
            "status_code", "retry_count", "max_retries", "retryable", "reason", "error", "api_request_id"} <= keywords
    assert not spread


@requires_hermes
def test_post_tool_call_payload_and_zero_default_duration():
    keywords, spread = _hook_call_keywords("model_tools.py", "_emit_post_tool_call_hook", "post_tool_call")
    assert {"tool_name", "duration_ms", "status", "error_type"} <= keywords
    assert len(spread) == 1 and "_CallIds" in ast.unparse(spread[0])
    assert {"task_id", "session_id", "tool_call_id", "turn_id", "api_request_id"} <= set(
        _class_fields("model_tools.py", "_CallIds"))
    emit = _function(_tree("model_tools.py"), "_emit_post_tool_call_hook")
    defaults = dict(zip((a.arg for a in emit.args.kwonlyargs), emit.args.kw_defaults))
    assert isinstance(defaults["duration_ms"], ast.Constant) and defaults["duration_ms"].value == 0
    executor = (HERMES / "agent" / "tool_executor.py").read_text(encoding="utf-8")
    assert 'duration_ms=int(timeout_s * 1000), status="timeout"' in executor


@requires_hermes
def test_api_call_identity_and_start_are_shared_by_retries():
    loop = (HERMES / "agent" / "conversation_loop.py").read_text(encoding="utf-8")
    assert "s.api_start_time, s.retry_count, s.max_retries = time.time(), 0" in loop
    assert 'f"{s.turn_id}:api:{s.api_call_count}"' in loop
    request = (HERMES / "agent" / "turn_api_request.py").read_text(encoding="utf-8")
    assert "agent._last_api_first_chunk_at = None" in request  # reset per attempt, start is not
