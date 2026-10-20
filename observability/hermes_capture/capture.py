"""Metadata-only capture of Hermes LLM and tool hook events into local JSONL.

Allowlist design: each event is rebuilt from a fixed set of scalar fields.
Prompts, responses, tool arguments/results, error messages, request bodies,
base URLs and mission content are never read into an event. A field the hook
does not provide is written as null and listed in ``absent_fields``; a value
that fails validation or looks like a secret is null and listed in
``redacted_fields``; a received zero is kept but, when Hermes cannot tell it
apart from its own default, it is labelled and listed in
``ambiguous_zero_fields``. Nothing is estimated. Callbacks never raise into
Hermes and never write to stdout/stderr (MCP stdio safety).

Hook contract: hermes-agent d923a5eb48 (see docs/hermes-observability-capture.md).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid

SCHEMA = "tfg.hermes.capture/3"
VERIFIED_HERMES_COMMIT = "d923a5eb487a17c0a68801bba9ef0f56c81040a8"
ENABLE_ENV = "TFG_OBSERVABILITY_CAPTURE"
DIR_ENV = "TFG_OBSERVABILITY_DIR"
RUN_ENV = "TFG_OBSERVABILITY_RUN_ID"
CASE_ENV = "TFG_OBSERVABILITY_CASE_ID"
HOOKS = ("post_api_request", "api_request_error", "post_tool_call")

# Hermes CanonicalUsage fields: each is the first non-zero provider path or 0, so a provider
# zero and a missing field arrive identically (input_tokens may also be prompt minus cache,
# clamped at 0). prompt_tokens/total_tokens are sums Hermes computes from those fields.
NORMALIZED_USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                           "reasoning_tokens")
DERIVED_USAGE_FIELDS = ("prompt_tokens", "total_tokens")
USAGE_FIELDS = NORMALIZED_USAGE_FIELDS + DERIVED_USAGE_FIELDS
# api_start_time/api_request_id are set once per API call before Hermes' retry loop;
# time.time() supplies the epochs, so durations are wall-clock and span all attempts.
TIMING = {"timing_source": "hermes_hook_wall_clock", "timing_scope": "api_call_from_first_attempt"}

_TOKEN = re.compile(r"[A-Za-z0-9_.:@+-]{1,128}")
_MODEL = re.compile(r"[A-Za-z0-9_.:@+/-]{1,160}")  # provider/model ids may contain '/'
_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_SECRET = re.compile(
    r"(?i)(sk-|pk-|ghp_|gho_|xox[abp]-|AKIA|AIza|eyJ[A-Za-z0-9_-]{8,}|bearer|api[_-]?key|token=|secret|password)"
    r"|[A-Fa-f0-9]{32,}|[A-Za-z0-9+=]{32,}"  # long unseparated runs; model ids keep '-', '/', ':'
)


def _enabled_directory(environ=os.environ):
    """Return the capture directory only for an explicit opt-in with an absolute path."""
    if environ.get(ENABLE_ENV) != "1":
        return None
    raw = environ.get(DIR_ENV, "")
    if not raw or not os.path.isabs(raw):
        return None
    return Path(raw)


def _ref(value):
    """Pseudonymous correlation id (unsalted); the original id is not stored."""
    if not isinstance(value, str) or not value:
        return None
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_seconds(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


class _Builder:
    def __init__(self):
        self.event = {}
        self.absent = []
        self.redacted = []
        self.ambiguous = []

    def _put(self, name, value, valid):
        if value is None or value == "":
            self.event[name] = None
            self.absent.append(name)
        elif valid:
            self.event[name] = value
        else:
            self.event[name] = None
            self.redacted.append(name)

    def text(self, name, value, pattern=_TOKEN):
        valid = (isinstance(value, str) and pattern.fullmatch(value) is not None
                 and "://" not in value and _SECRET.search(value) is None)
        self._put(name, value, valid)

    def integer(self, name, value):
        self._put(name, value, _is_count(value))

    def seconds(self, name, value):
        valid = _is_seconds(value)
        self._put(name, float(value) if valid else value, valid)

    def boolean(self, name, value):
        self._put(name, value, isinstance(value, bool))

    def finish(self, event_type, environ):
        run = environ.get(RUN_ENV)
        case = environ.get(CASE_ENV)
        return {
            "schema": SCHEMA,
            "event_type": event_type,
            "event_id": str(uuid.uuid4()),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run if isinstance(run, str) and _LABEL.fullmatch(run) else None,
            "case_id": case if isinstance(case, str) and _LABEL.fullmatch(case) else None,
            **self.event,
            "absent_fields": sorted(self.absent),
            "redacted_fields": sorted(self.redacted),
            "ambiguous_zero_fields": sorted(self.ambiguous),
        }


def _identity(builder, kwargs):
    for name in ("session_id", "task_id", "turn_id", "api_request_id"):
        builder.event[name.replace("_id", "_ref")] = _ref(kwargs.get(name))


def _timing(builder, kwargs):
    builder.event.update(TIMING)
    builder.seconds("api_duration_s", kwargs.get("api_duration"))
    builder.seconds("started_at_epoch_s", kwargs.get("started_at"))
    builder.seconds("ended_at_epoch_s", kwargs.get("ended_at"))


def _usage(builder, usage):
    """Keep every received counter with a status saying what Hermes still lets us know.

    ``usage=None`` from the hook means the response carried no usage. Inside a
    summary, a positive normalised counter came from a provider field; a 0 may be
    a provider zero or the CanonicalUsage default (raw_usage is not passed to
    hooks), so it is kept as ``zero_unconfirmed``. Derived sums are labelled as such.
    """
    if not isinstance(usage, dict):
        builder.event["usage_source"] = "absent"
        builder.event["usage"] = None
        builder.absent.append("usage")
        return
    tokens = {}
    for name in USAGE_FIELDS:
        value = usage.get(name)
        derived = name in DERIVED_USAGE_FIELDS
        if name not in usage or value is None:
            tokens[name] = {"value": None, "status": "absent"}
            builder.absent.append(f"usage.{name}")
        elif not _is_count(value):
            tokens[name] = {"value": None, "status": "redacted"}
            builder.redacted.append(f"usage.{name}")
        elif value == 0:
            tokens[name] = {"value": 0, "status": "derived_zero" if derived else "zero_unconfirmed"}
            builder.ambiguous.append(f"usage.{name}")
        else:
            tokens[name] = {"value": value, "status": "derived_nonzero" if derived else "nonzero_normalized"}
    builder.event["usage_source"] = "hermes_normalized_summary"
    builder.event["usage"] = tokens


def _requested_tool_names(response):
    calls = (((response or {}).get("assistant_message") or {}).get("tool_calls")
             if isinstance(response, dict) else None)
    if not isinstance(calls, list):
        return None
    names = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        ok = isinstance(name, str) and _TOKEN.fullmatch(name) and _SECRET.search(name) is None
        names.append(name if ok else None)
    return names


def llm_call_event(kwargs, environ=os.environ):
    b = _Builder()
    _identity(b, kwargs)
    response = kwargs.get("response") if isinstance(kwargs.get("response"), dict) else {}
    b.text("provider", kwargs.get("provider"), _MODEL)
    b.text("upstream_provider", response.get("upstream_provider"), _MODEL)
    b.text("model", kwargs.get("model"), _MODEL)
    b.text("response_model", kwargs.get("response_model"), _MODEL)
    b.text("api_mode", kwargs.get("api_mode"))
    b.text("finish_reason", kwargs.get("finish_reason"))
    _timing(b, kwargs)
    # Hermes resets first_chunk_at per attempt but keeps started_at from the first one:
    # this offset equals time-to-first-chunk only when the call had no retry.
    first, start, duration = kwargs.get("first_chunk_at"), kwargs.get("started_at"), kwargs.get("api_duration")
    offset = first - start if _is_seconds(first) and _is_seconds(start) else first
    consistent = _is_seconds(offset) and (not _is_seconds(duration) or offset <= duration)
    b._put("first_chunk_offset_s", float(offset) if consistent else offset, consistent)
    for name in ("api_call_count", "message_count", "assistant_tool_call_count", "context_length"):
        b.integer(name, kwargs.get(name))
    b.event["requested_tool_names"] = _requested_tool_names(response)
    if b.event["requested_tool_names"] is None:
        b.absent.append("requested_tool_names")
    _usage(b, kwargs.get("usage"))
    b.event["retry_count"] = None  # post_api_request carries no retry evidence
    b.absent.append("retry_count")
    return b.finish("llm_call", environ)


def llm_error_event(kwargs, environ=os.environ):
    b = _Builder()
    _identity(b, kwargs)
    b.text("provider", kwargs.get("provider"), _MODEL)
    b.text("model", kwargs.get("model"), _MODEL)
    b.text("api_mode", kwargs.get("api_mode"))
    _timing(b, kwargs)
    for name in ("api_call_count", "status_code", "retry_count", "max_retries"):
        b.integer(name, kwargs.get(name))
    b.boolean("retryable", kwargs.get("retryable"))
    b.text("reason", kwargs.get("reason"))
    error = kwargs.get("error") if isinstance(kwargs.get("error"), dict) else {}
    b.text("error_type", error.get("type"))
    return b.finish("llm_error", environ)


def tool_call_event(kwargs, environ=os.environ):
    b = _Builder()
    _identity(b, kwargs)
    b.event["tool_call_ref"] = _ref(kwargs.get("tool_call_id"))
    b.text("tool_name", kwargs.get("tool_name"))
    b.text("status", kwargs.get("status"))
    b.text("error_type", kwargs.get("error_type"))
    # Received value and confirmed measurement are separate fields.
    duration = kwargs.get("duration_ms")
    b.event["duration_ms_received"] = duration if _is_count(duration) else None
    b.event["duration_ms_measured"] = None
    if duration is None:
        b.event["duration_source"] = "absent"
        b.absent.append("duration_ms")
    elif not _is_count(duration):
        b.event["duration_source"] = "redacted"
        b.redacted.append("duration_ms")
    elif b.event["status"] == "timeout":
        b.event["duration_source"] = "timeout_configured_not_measured"  # Hermes sends the timeout setting
    elif duration == 0:
        b.event["duration_source"] = "zero_default_or_below_1ms"  # 0 is also the hook default
        b.ambiguous.append("duration_ms")
    else:
        b.event["duration_ms_measured"] = duration
        b.event["duration_source"] = "hermes_reported_ms"
    return b.finish("tool_call", environ)


class JsonlSink:
    """Append-only, one event per line; directory 0700, files 0600, no symlinks."""

    def __init__(self, directory: Path, environ=os.environ):
        self.directory = directory
        self.environ = environ
        self.failures = 0
        self._lock = threading.Lock()

    def _write(self, event):
        line = json.dumps(event, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / f"hermes-events-{event['recorded_at_utc'][:10]}.jsonl"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        with self._lock:
            descriptor = os.open(path, flags, 0o600)
            try:
                os.write(descriptor, line.encode("utf-8"))
            finally:
                os.close(descriptor)

    def _capture(self, build, kwargs):
        # Count only: no logging or printing, since a payload could surface in the message
        # and stdout may be an MCP stdio channel.
        try:
            self._write(build(kwargs, self.environ))
        except Exception:
            self.failures += 1
        return None

    def on_post_api_request(self, **kwargs):
        return self._capture(llm_call_event, kwargs)

    def on_api_request_error(self, **kwargs):
        return self._capture(llm_error_event, kwargs)

    def on_post_tool_call(self, **kwargs):
        return self._capture(tool_call_event, kwargs)


def register(ctx, environ=os.environ):
    """Hermes plugin entry point. Registers nothing unless explicitly enabled."""
    directory = _enabled_directory(environ)
    if directory is None:
        return None
    sink = JsonlSink(directory, environ)
    ctx.register_hook("post_api_request", sink.on_post_api_request)
    ctx.register_hook("api_request_error", sink.on_api_request_error)
    ctx.register_hook("post_tool_call", sink.on_post_tool_call)
    return sink
