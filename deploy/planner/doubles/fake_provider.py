"""TEST DOUBLE of an OpenAI-compatible chat-completions provider for the planning profile checks.

NOT a model: every answer is scripted. It exists to exercise Hermes, the project's MCP server, validation and
persistence without any real inference. Each request is recorded (path, model, stream flag, offered tool names,
message roles, HEADER NAMES ONLY - never values) to FAKE_RECORDS as JSON lines.

FAKE_SCENARIO:
  planning  1st call: update_mission_draft with the operator data of the H1 prompt (sector A); 2nd call:
            finalize_mission_draft with the returned draft_id/draft_revision; 3rd: a final text answer.
  invalid   200 with a body that is not JSON.
  timeout   waits FAKE_DELAY_S seconds before answering.

Also answers the Ollama API shape (GET /api/version, POST /api/chat) used by the menu's LangChain ChatOllama
path: the same scenarios, with the H1 sector A facts as the extracted draft in the planning scenario.

    python fake_provider.py            (listens on 0.0.0.0:8000)
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import time
import uuid

SCENARIO = os.environ.get("FAKE_SCENARIO", "planning")
RECORDS = os.environ.get("FAKE_RECORDS", "/tmp/fake_provider_requests.jsonl")
DELAY_S = float(os.environ.get("FAKE_DELAY_S", "60"))
MODEL = "tfg-test-double"
# Operator data of the H1 planning prompt (observability.hermes_capture_run.AGRI_PLANNING_PROMPT), mission 1.
H1_SECTOR_A = {
    "mission_id": "agri_demo_001_h1_sector_a", "name": "agri_demo_001 H1 sector A", "vehicle_id": "drone_01",
    "vehicle_type": "multirotor", "autopilot": "ArduPilot", "cruise_speed_kmh": 35.0, "battery_percent": 100.0,
    "battery_consumption_percent_per_minute": 0.8, "objective_type": "precision_agriculture",
    "objective_target": "agri_demo_001_sector_a", "return_to_home": True, "wind_speed_kmh": 0.0,
    "wind_direction_from_deg": 0.0, "minimum_battery_reserve_percent": 20.0, "maximum_wind_speed_kmh": 30.0,
    "maximum_altitude_m": 120.0, "low_battery_action": "RETURN_TO_HOME", "unsafe_wind_action": "RETURN_TO_HOME",
    "communication_loss_action": "RETURN_TO_HOME",
    "geometry_intent": {"mode": "offsets", "home_latitude": 41.275, "home_longitude": 1.987, "home_altitude_m": 0.0,
                        "altitude_reference": "relative_to_home", "altitude_m": 5.0, "return_to_home": True,
                        "close_route": False,
                        "offsets": [{"north_m": 8.0, "east_m": -4.0}, {"north_m": 16.0, "east_m": -4.0}]},
}


def _offered(body: dict) -> list[str]:
    return [t.get("function", {}).get("name", "") for t in body.get("tools") or [] if isinstance(t, dict)]


def _tool_texts(messages: list) -> list[str]:
    texts = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "tool":
            content = message.get("content")
            texts.append(content if isinstance(content, str) else json.dumps(content))
    return texts


def _planning_reply(body: dict) -> dict:
    offered = _offered(body)
    update = next((n for n in offered if n.endswith("update_mission_draft")), None)
    finalize = next((n for n in offered if n.endswith("finalize_mission_draft")), None)
    results = _tool_texts(body.get("messages") or [])
    if update is None or finalize is None:
        return {"content": "TEST DOUBLE: the planning tools were not offered; nothing called."}
    if not results:
        return {"tool": update, "arguments": {"updates": H1_SECTOR_A}}
    last = results[-1]
    # Tool results may arrive as a JSON-serialized list of content parts, i.e. with escaped quotes.
    draft = re.search(r'\\*"draft_id\\*"\s*:\s*\\*"([0-9a-f-]{36})', last)
    revision = re.search(r'\\*"draft_revision\\*"\s*:\s*(\d+)', last)
    if len(results) == 1 and draft:
        return {"tool": finalize, "arguments": {"draft_id": draft.group(1),
                                                "expected_revision": int(revision.group(1)) if revision else None}}
    if len(results) == 1:  # the update returned no draft_id: report it, never claim a saved draft
        return {"content": "TEST DOUBLE (no model): update_mission_draft returned no draft_id (tool error or "
                           "refusal); nothing was finalized. Tool result begins: " + last[:200]}
    export = re.search(r'\\*"qgc_export\\*"\s*:\s*\{[^{}]*?\\*"status\\*"\s*:\s*\\*"([A-Z_]+)', last)
    return {"content": "TEST DOUBLE (no model): draft saved and finalization attempted; qgc_export status "
                       f"{export.group(1) if export else 'not found in the tool result'}."}


def _message(reply: dict) -> dict:
    if "tool" in reply:
        call = {"id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                "function": {"name": reply["tool"], "arguments": json.dumps(reply["arguments"])}}
        return {"role": "assistant", "content": None, "tool_calls": [call]}
    return {"role": "assistant", "content": reply["content"]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep stdout for the records summary only
        pass

    def _record(self, body: dict | None) -> None:
        entry = {"path": self.path, "method": self.command, "header_names": sorted(self.headers.keys()),
                 "model": (body or {}).get("model"), "stream": bool((body or {}).get("stream")),
                 "offered_tools": _offered(body or {}),
                 "message_roles": [m.get("role") for m in (body or {}).get("messages") or [] if isinstance(m, dict)]}
        with open(RECORDS, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _json(self, status: int, payload) -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._record(None)
        if self.path.rstrip("/") == "/api/version":  # Ollama API shape
            self._json(200, {"version": "TEST-DOUBLE"})
        elif self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "test-double"}]})
        else:
            self._json(404, {"error": {"message": "TEST DOUBLE: not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        self._record(body)
        if self.path.rstrip("/") == "/api/chat":  # Ollama API shape (langchain_ollama ChatOllama)
            if SCENARIO == "timeout":
                time.sleep(DELAY_S)
            content = ("TEST DOUBLE: this is not JSON {" if SCENARIO == "invalid"
                       else json.dumps({k: v for k, v in H1_SECTOR_A.items() if k != "geometry_intent"}))
            lines = [{"model": MODEL, "message": {"role": "assistant", "content": content}, "done": False},
                     {"model": MODEL, "message": {"role": "assistant", "content": ""}, "done": True,
                      "done_reason": "stop"}]
            data = b"".join(json.dumps(line).encode() + b"\n" for line in lines)
            if body.get("stream") is False:
                data = json.dumps({**lines[0], "done": True, "done_reason": "stop"}).encode()
            self._json(200, data)
            return
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": {"message": "TEST DOUBLE: not found"}})
            return
        if SCENARIO == "timeout":
            time.sleep(DELAY_S)
        if SCENARIO == "invalid":
            self._json(200, b"TEST DOUBLE: this is not JSON {")
            return
        message = _message(_planning_reply(body))
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        created, ident = int(time.time()), "chatcmpl-" + uuid.uuid4().hex[:12]
        if not body.get("stream"):
            self._json(200, {"id": ident, "object": "chat.completion", "created": created, "model": MODEL,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
            return
        delta = {"role": "assistant", "content": message.get("content")}
        if message.get("tool_calls"):
            delta["tool_calls"] = [{"index": 0, **message["tool_calls"][0]}]
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                   "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in chunks:
            payload = {"id": ident, "object": "chat.completion.chunk", "created": created, "model": MODEL, **chunk}
            self.wfile.write(b"data: " + json.dumps(payload).encode() + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    print(f"TEST DOUBLE provider (scenario {SCENARIO}) on :8000; records {RECORDS}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
