"""SYNTHETIC loader/hook integration check for the TFG capture plugin. No model is called.

Run inside Hermes' own interpreter after its real bootstrap (see run.sh). Real: plugin
discovery/loading, PluginContext.register_hook, lifecycle.invoke_hook/ainvoke_hook and the
Hermes payload emitters. Synthetic: the fixture values and the minimal agent object the
post_api_request / api_request_error emitters read attributes from (no AIAgent, no client).
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

report = {"kind": "SYNTHETIC_LOADER_HOOK_CHECK", "model_called": False}

from hermes_constants import get_hermes_home
from hermes_cli import plugins
from hermes_cli import lifecycle

report["hermes_home"] = str(get_hermes_home())
plugins.discover_plugins(force=True)
manager = plugins.get_plugin_manager()
ours = [(key, p) for key, p in manager._plugins.items() if p.manifest.name == "tfg-observability-capture"]
report["plugin_entries"] = [{
    "key": key, "source": p.manifest.source, "path": p.manifest.path, "enabled": p.enabled,
    "error": p.error, "hooks_registered": list(p.hooks_registered),
    "module": getattr(p.module, "__name__", None), "module_file": getattr(p.module, "__file__", None),
    "provides_hooks": list(p.manifest.provides_hooks or []),
} for key, p in ours]
report["has_hook"] = {h: lifecycle.has_hook(h) for h in
                      ("post_api_request", "api_request_error", "post_tool_call", "pre_tool_call", "pre_api_request")}

SECRET = "sk-ant-SYNTHETICFAKEKEY0123456789abcdef"
CONTENT = "SYNTHETIC-CONTENT Parcela Prueba HOME 41.27531, 1.98712"
PATH = "/home/joelm/TFG/Agentic_Drone_Mission_Control/missions/generated/drafts/SYNTHETIC/draft.json"
results = {}

# post_api_request through Hermes' real emitter; agent object is a synthetic attribute holder.
from agent.api_request_hooks import ApiRequestHooksMixin
from agent.turn_response_intake import _fire_post_api_request_hook
import model_tools


class SyntheticAgentStub(ApiRequestHooksMixin):
    session_id = "SYNTHETIC-session-1"
    platform = "cli"
    model = "SYNTHETIC-model"
    provider = "custom"
    base_url = f"http://127.0.0.1:11434/v1?key={SECRET}"
    api_mode = "chat_completions"
    context_compressor = None
    _last_api_first_chunk_at = 1792246298.4


agent = SyntheticAgentStub()
call = SimpleNamespace(id="SYNTHETIC-call-1", type="function",
                       function=SimpleNamespace(name="mcp_tfg_get_mission_state",
                                                arguments=json.dumps({"home": CONTENT, "path": PATH})))
message = SimpleNamespace(role="assistant", content=CONTENT, tool_calls=[call])
usage = SimpleNamespace(prompt_tokens=1200, completion_tokens=0, total_tokens=1200)  # synthetic counters
response = SimpleNamespace(model="SYNTHETIC-response-model", provider="SYNTHETIC-upstream", usage=usage)
_fire_post_api_request_hook(agent, response, message, "tool_calls", api_messages=[{"content": CONTENT}],
                            api_call_count=1, api_duration=1.25, api_start_time=1792246298.0,
                            api_request_id="SYNTHETIC-turn-1:api:1", effective_task_id="SYNTHETIC-task-1",
                            turn_id="SYNTHETIC-turn-1")
agent._last_api_first_chunk_at = None
_fire_post_api_request_hook(agent, SimpleNamespace(model="SYNTHETIC-response-model", usage=None), message, "stop",
                            api_messages=[], api_call_count=2, api_duration=0.5, api_start_time=1792246300.0,
                            api_request_id="SYNTHETIC-turn-1:api:2", effective_task_id="SYNTHETIC-task-1",
                            turn_id="SYNTHETIC-turn-1")
agent._invoke_api_request_error_hook(
    task_id="SYNTHETIC-task-1", turn_id="SYNTHETIC-turn-1", api_request_id="SYNTHETIC-turn-1:api:3",
    api_call_count=3, api_start_time=1792246301.0,
    api_kwargs={"messages": [{"content": CONTENT}], "api_key": SECRET},
    error_type="SyntheticRateLimitError", error_message=f"Bearer {SECRET} {CONTENT}", status_code=429,
    retry_count=1, max_retries=3, retryable=True, reason="rate_limited")
model_tools._emit_post_tool_call_hook(function_name="mcp_tfg_get_mission_state",
                                      function_args={"draft_id": "SYNTHETIC", "home": CONTENT, "path": PATH},
                                      result=json.dumps({"draft": CONTENT, "secret": SECRET}),
                                      task_id="SYNTHETIC-task-1", session_id="SYNTHETIC-session-1",
                                      tool_call_id="SYNTHETIC-call-1", turn_id="SYNTHETIC-turn-1",
                                      api_request_id="SYNTHETIC-turn-1:api:1", duration_ms=742, status="ok")

# Direct dispatch through the real lifecycle entry points, to observe return values.
results["sync_invoke_return"] = lifecycle.invoke_hook(
    "post_tool_call", tool_name="SYNTHETIC_terminal", args={"cmd": SECRET}, result=CONTENT, duration_ms=0,
    status="blocked", task_id="", session_id="", tool_call_id="", turn_id="", api_request_id="")
results["async_invoke_return"] = asyncio.run(lifecycle.ainvoke_hook(
    "post_tool_call", tool_name="SYNTHETIC_async_extra", args={}, result="", duration_ms=30000,
    status="timeout", task_id="", session_id="", tool_call_id="", turn_id="", api_request_id=""))
report["dispatch_results"] = {k: repr(v) for k, v in results.items()}

try:
    entries = manager._hooks.get("post_tool_call", [])
    callbacks = [getattr(e, "callback", e) for e in entries]
    sinks = [getattr(cb, "__self__", None) for cb in callbacks]
    report["sink_failures"] = [s.failures for s in sinks if s is not None and hasattr(s, "failures")]
except Exception as exc:  # registry internals are not a public contract
    report["sink_failures"] = f"unavailable: {type(exc).__name__}"
print(json.dumps(report))
