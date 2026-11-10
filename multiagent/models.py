"""Adapters for the models to compare. OFFLINE BY DEFAULT: no adapter opens a connection unless it was built with
``enabled=True`` and the caller passes the network check of ``require_enabled``; tests inject a transport.

Adapters:
- ScriptedAdapter: TEST DOUBLE, replays fixed replies (SYNTHETIC); never a model result.
- OllamaChatAdapter: a local model served by Ollama (``POST /api/chat``), e.g. ``qwen3:4b``. Optional: Ollama is an
  evaluation option, not a dependency of the architecture.
- OpenAICompatibleChatAdapter: ``POST {base}/v1/chat/completions``. Presets:
  * ``aida_qwen()``: AIDA HPC (https://aida-hpc.widening.eu), model ``qwen``;
  * ``hermes_provider()``: the provider and model in deploy/planner/hermes-config.base.yaml. Hermes keeps its own
    login inside HERMES_HOME; this adapter needs an explicit base URL and key variable, and its compatibility
    with the Hermes client is NOT assumed.
- AidaClefAdapter: AIDA HPC ``POST /v1/systemone``, model ``clef``. Clef returns structured decisions with
  probabilities, it is not a chat model: its reply is normalised to {"decisions": [{"label", "probability"}]}.
  The request and reply shapes are NOT VERIFIED (no call has been made); the default builder/parser are
  assumptions to confirm against AIDA's documentation, and are injectable.

Credentials: only the NAME of an environment variable is stored; its value is read at call time, sent in the
Authorization header and never logged, returned or kept in metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

import yaml

AIDA_BASE_URL = "https://aida-hpc.widening.eu"
AIDA_KEY_ENV = "AIDA_HPC_API_KEY"
HERMES_CONFIG = Path(__file__).resolve().parents[1] / "deploy/planner/hermes-config.base.yaml"
CLEF_SCHEMA_STATUS = "ASSUMED_UNVERIFIED: request/response shape of /v1/systemone not yet confirmed with AIDA"


class AdapterDisabled(RuntimeError):
    """The adapter would open a connection but was not explicitly enabled."""


class AdapterSchemaError(ValueError):
    """The service replied with a shape this adapter does not understand (nothing is guessed)."""


class AdapterUnavailable(RuntimeError):
    """INFRASTRUCTURE error: connection refused, timeout, HTTP error. Never scored as a model error."""


@dataclass
class ModelResponse:
    text: str
    latency_s: float  # measured by this process (perf_counter), request to parsed reply
    provider: str
    model: str
    data_kind: str  # SYNTHETIC (double) or MODEL_OUTPUT
    usage: dict | None = None  # token counts as reported by the service, if any
    server_timing: dict | None = None  # as reported by the service (e.g. Ollama durations), never mixed with latency_s
    structured: dict | None = None  # normalised structured reply (Clef)
    finish_reason: str | None = None  # e.g. Ollama done_reason "stop" / "length" (truncated)
    reasoning: str | None = None  # separate reasoning text if the service returns one; kept, never parsed

    def metadata(self) -> dict:
        return {"provider": self.provider, "model": self.model, "data_kind": self.data_kind,
                "latency_s": self.latency_s, "usage": self.usage, "server_timing": self.server_timing,
                "finish_reason": self.finish_reason}


def urllib_get(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - local Ollama status only
        return json.loads(response.read())


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit, enabled adapters only
        return response.status, response.read()


@dataclass
class _HttpAdapter:
    base_url: str
    model: str
    enabled: bool = False
    api_key_env: str | None = None
    timeout_s: float = 120.0
    transport: object = None
    provider: str = "unknown"
    version: str | None = None  # model version/tag when known; recorded in traces

    @property
    def info(self) -> dict:
        return {"provider": self.provider, "model": self.model, "version": self.version, "base_url": self.base_url,
                "data_kind": "MODEL_OUTPUT", "credential_env": self.api_key_env}

    def _post(self, path: str, payload: dict) -> tuple[dict, float]:
        if not self.enabled:
            raise AdapterDisabled(f"{self.provider}/{self.model}: model calls are disabled (enabled=False)")
        headers = {"Content-Type": "application/json"}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise AdapterDisabled(f"credential variable {self.api_key_env} is not set")
            headers["Authorization"] = f"Bearer {key}"
        transport = self.transport or urllib_transport
        started = time.perf_counter()
        try:
            status, raw = transport(self.base_url.rstrip("/") + path, headers, json.dumps(payload).encode("utf-8"),
                                    self.timeout_s)
        except urllib.error.HTTPError as exc:
            raise AdapterUnavailable(f"{self.provider}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise AdapterUnavailable(f"{self.provider}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        elapsed = time.perf_counter() - started
        if status != 200:
            raise AdapterUnavailable(f"{self.provider}: HTTP {status}")
        try:
            return json.loads(raw), elapsed
        except json.JSONDecodeError as exc:
            raise AdapterSchemaError(f"{self.provider}: reply is not JSON") from exc


@dataclass
class OllamaChatAdapter(_HttpAdapter):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:4b"
    provider: str = "ollama"
    temperature: float = 0.0
    seed: int | None = 7
    num_predict: int | None = 1024  # max generated tokens; a reply cut at this limit is TRUNCATED, never parsed
    think: bool | None = False  # qwen3 reasoning mode; False keeps latency bounded (recorded with the results)
    num_ctx: int | None = 8192

    @property
    def generation(self) -> dict:
        return {"temperature": self.temperature, "seed": self.seed, "num_predict": self.num_predict,
                "think": self.think, "num_ctx": self.num_ctx, "format": "json", "stream": False,
                "timeout_s": self.timeout_s}

    def local_model(self, get=None) -> dict | None:
        """Installed model entry (digest, size, details) from GET /api/tags; None if not installed. Local only."""
        if not self.enabled:
            raise AdapterDisabled("ollama: disabled")
        try:
            tags = (get or urllib_get)(self.base_url.rstrip("/") + "/api/tags")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise AdapterUnavailable(f"ollama: {type(exc).__name__}") from exc
        return next((m for m in tags.get("models", []) if m.get("name") == self.model), None)

    def complete(self, messages: list[dict], *, json_output: bool = False) -> ModelResponse:
        options = {"temperature": self.temperature, **({"seed": self.seed} if self.seed is not None else {}),
                   **({"num_predict": self.num_predict} if self.num_predict else {}),
                   **({"num_ctx": self.num_ctx} if self.num_ctx else {})}
        payload = {"model": self.model, "messages": messages, "stream": False, "options": options}
        if self.think is not None:
            payload["think"] = self.think
        if json_output:
            payload["format"] = "json"
        reply, elapsed = self._post("/api/chat", payload)
        message = reply.get("message") if isinstance(reply, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise AdapterSchemaError("ollama: no message.content")
        usage = {"prompt_tokens": reply.get("prompt_eval_count"), "completion_tokens": reply.get("eval_count")}
        timing = {k: reply.get(k) for k in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
                  if reply.get(k) is not None}
        return ModelResponse(message["content"], elapsed, self.provider, reply.get("model", self.model),
                             "MODEL_OUTPUT", usage, {"unit": "ns", **timing} if timing else None,
                             finish_reason=reply.get("done_reason"),
                             reasoning=message.get("thinking") if isinstance(message.get("thinking"), str) else None)


@dataclass
class OpenAICompatibleChatAdapter(_HttpAdapter):
    path: str = "/v1/chat/completions"
    temperature: float = 0.0
    json_mode: bool = False  # response_format json_object; only if the service is known to support it

    @property
    def generation(self) -> dict:
        return {"temperature": self.temperature, "json_mode": self.json_mode, "stream": False}

    def complete(self, messages: list[dict], *, json_output: bool = False) -> ModelResponse:
        payload = {"model": self.model, "messages": messages, "temperature": self.temperature, "stream": False}
        if json_output and self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        reply, elapsed = self._post(self.path, payload)
        try:
            text = reply["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdapterSchemaError(f"{self.provider}: no choices[0].message.content") from exc
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else None
        return ModelResponse(text or "", elapsed, self.provider, reply.get("model", self.model), "MODEL_OUTPUT", usage)


AIDA_ENV = {"base_url": "AIDA_HPC_BASE_URL", "qwen_model": "AIDA_QWEN_MODEL", "clef_model": "AIDA_CLEF_MODEL",
            "api_key": AIDA_KEY_ENV}


def aida_config(environ=None) -> dict:
    """Endpoint and model names from the environment (defaults: the documented service). Never the key's value:
    only whether the key variable is set. Needs VPN + key to be USED; reading it calls nothing."""
    env = os.environ if environ is None else environ
    return {"base_url": env.get(AIDA_ENV["base_url"], AIDA_BASE_URL), "qwen_model": env.get(AIDA_ENV["qwen_model"], "qwen"),
            "clef_model": env.get(AIDA_ENV["clef_model"], "clef"), "api_key_env": AIDA_KEY_ENV,
            "api_key_present": bool(env.get(AIDA_KEY_ENV)), "requires": ["VPN to aida-hpc.widening.eu", AIDA_KEY_ENV]}


def aida_qwen(**kw) -> OpenAICompatibleChatAdapter:
    config = aida_config()
    return OpenAICompatibleChatAdapter(**{"base_url": config["base_url"], "model": config["qwen_model"],
                                          "provider": "aida-hpc", "api_key_env": AIDA_KEY_ENV, **kw})


def aida_clef(**kw) -> "AidaClefAdapter":
    config = aida_config()
    return AidaClefAdapter(**{"base_url": config["base_url"], "model": config["clef_model"], **kw})


def hermes_provider(*, base_url: str | None = None, api_key_env: str | None = None, **kw) -> OpenAICompatibleChatAdapter:
    """Same provider/model as the Hermes planning profile; endpoint and key variable must be given explicitly."""
    config = yaml.safe_load(HERMES_CONFIG.read_text(encoding="utf-8"))["model"]
    base_url = base_url or os.environ.get("TFG_HERMES_PROVIDER_BASE_URL")
    if not base_url:
        raise AdapterDisabled(f"Hermes provider {config['provider']!r}: base URL not configured "
                              "(TFG_HERMES_PROVIDER_BASE_URL); Hermes keeps its own login in HERMES_HOME")
    return OpenAICompatibleChatAdapter(**{"base_url": base_url, "model": config["default"],
                                          "provider": f"hermes:{config['provider']}", "api_key_env": api_key_env, **kw})


def clef_request(model: str, text: str, labels: list[str] | None) -> dict:
    """ASSUMED request body (unverified)."""
    return {"model": model, "input": text, **({"labels": labels} if labels else {})}


def clef_parse(reply: dict) -> dict:
    """Normalise a Clef reply to {"decisions": [{"label", "probability"}]}; refuse anything else (ASSUMED shapes)."""
    decisions = None
    if isinstance(reply.get("decisions"), list):
        decisions = [{"label": d.get("label") or d.get("decision"), "probability": d.get("probability")}
                     for d in reply["decisions"] if isinstance(d, dict)]
    elif isinstance(reply.get("probabilities"), dict):
        decisions = [{"label": k, "probability": v} for k, v in reply["probabilities"].items()]
    if not decisions or any(not isinstance(d["label"], str) or isinstance(d["probability"], bool)
                            or not isinstance(d["probability"], (int, float)) or not 0 <= d["probability"] <= 1
                            for d in decisions):
        raise AdapterSchemaError("clef: reply has no decisions with probabilities in [0, 1] (" + CLEF_SCHEMA_STATUS + ")")
    total = sum(d["probability"] for d in decisions)
    decisions.sort(key=lambda d: (-d["probability"], d["label"]))
    return {"decisions": decisions, "top": decisions[0]["label"], "probability_sum": total,
            "schema_status": CLEF_SCHEMA_STATUS}


@dataclass
class AidaClefAdapter(_HttpAdapter):
    base_url: str = AIDA_BASE_URL
    model: str = "clef"
    provider: str = "aida-hpc"
    api_key_env: str | None = AIDA_KEY_ENV
    path: str = "/v1/systemone"
    build_request: object = clef_request
    parse_reply: object = clef_parse

    def classify(self, text: str, labels: list[str] | None = None) -> ModelResponse:
        reply, elapsed = self._post(self.path, self.build_request(self.model, text, labels))
        structured = self.parse_reply(reply)
        return ModelResponse(json.dumps(structured), elapsed, self.provider, self.model, "MODEL_OUTPUT",
                             reply.get("usage") if isinstance(reply.get("usage"), dict) else None,
                             structured=structured)


@dataclass
class ScriptedAdapter:
    """TEST DOUBLE: answers from a fixed table (key = a substring of the prompt) or a callable. SYNTHETIC."""
    replies: dict = field(default_factory=dict)
    responder: object = None
    model: str = "scripted-double"
    calls: list = field(default_factory=list)

    @property
    def info(self) -> dict:
        return {"provider": "test-double", "model": self.model, "version": "fixture", "data_kind": "SYNTHETIC"}

    generation = {"deterministic": True}

    def complete(self, messages: list[dict], *, json_output: bool = False) -> ModelResponse:
        started = time.perf_counter()
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        if self.responder is not None:
            text = self.responder(prompt)
        else:
            text = next((v for k, v in self.replies.items() if k in prompt), "")
        return ModelResponse(text, time.perf_counter() - started, "test-double", self.model, "SYNTHETIC",
                             {"prompt_tokens": None, "completion_tokens": None})

    def classify(self, text: str, labels: list[str] | None = None) -> ModelResponse:
        response = self.complete([{"role": "user", "content": text}])
        structured = clef_parse(json.loads(response.text))
        response.structured, response.text = structured, json.dumps(structured)
        return response
