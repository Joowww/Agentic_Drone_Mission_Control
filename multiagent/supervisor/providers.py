"""Model providers for the supervisor and for Hermes: local Ollama, UPC EETAC (eetac-llm), AIDA HPC Qwen, AIDA Clef.

Built on the existing adapters of multiagent/models.py (OpenAICompatibleChatAdapter, AidaClefAdapter), which are not
modified. This module adds what the supervisor needs around them:

  selection   TFG_LLM_PROVIDER = ollama-local | eetac | aida-qwen  (default ollama-local). A fallback happens ONLY
              if TFG_LLM_FALLBACK lists providers explicitly (comma separated); every attempt is recorded, so the
              provider that produced an answer is always known. Retries: TFG_LLM_RETRIES (default 0).
  credentials only the NAME of the variable is configured (EETAC_API_KEY, AIDA_TOKEN); the value is read at call time
              by the adapter, sent in the Authorization header and never logged, returned or written.
  transport   a credential is never sent over plain HTTP to a non-loopback host. EETAC (raonador.upc.edu:4000)
              answers HTTP only (probe 24/11/2026: TLS on :4000 fails, :443 does not answer): its key is REFUSED
              unless the operator sets EETAC_ALLOW_HTTP_OVER_VPN=raonador.upc.edu, stating that the UPCLink VPN
              is the accepted protection. That opt-in is recorded in every call record.
  records     tfg.multiagent.model-call/1 per attempt: run id, provider, model, endpoint host, latency, status,
              error class, HTTP status, retries, prompt/response sha256 (never their text), fallback position.
  uses        (1) Hermes profile ``model`` block (hermes_model_block); (2) supervisor intent from a model
              (model_intent), which the LangGraph supervisor reconciles against the deterministic reading;
              (3) a LangChain chat model (langchain_chat_model); (4) Clef as an ADVISORY classifier
              (ClefAdvisor): its probabilities never replace deterministic validators or approvals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse
import uuid

from multiagent import models as m

CALL_SCHEMA = "tfg.multiagent.model-call/1"
EETAC_HOST = "raonador.upc.edu"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str          # WITHOUT the /v1 suffix (the adapter appends /v1/chat/completions)
    model: str
    key_env: str | None
    context_length: int | None = None
    insecure_optin_env: str | None = None
    note: str = ""


def specs(environ=None) -> dict[str, ProviderSpec]:
    env = os.environ if environ is None else environ
    return {
        "ollama-local": ProviderSpec("ollama-local", env.get("TFG_OLLAMA_BASE_URL", "http://127.0.0.1:11435"),
                                     env.get("TFG_OLLAMA_MODEL", "qwen3-4b-instruct-64k"), None, 65536,
                                     note="loopback Ollama (deploy/hermes_local_demo/ollama_demo_instance.sh)"),
        "eetac": ProviderSpec("eetac", env.get("EETAC_BASE_URL", f"http://{EETAC_HOST}:4000"),
                              env.get("EETAC_MODEL", "eetac-llm"), "EETAC_API_KEY",
                              insecure_optin_env="EETAC_ALLOW_HTTP_OVER_VPN",
                              note="UPC network or UPCLink only; HTTP endpoint (no TLS observed)"),
        "aida-qwen": ProviderSpec("aida-qwen", env.get("AIDA_BASE_URL", m.AIDA_BASE_URL),
                                  env.get("AIDA_QWEN_MODEL", "qwen"), "AIDA_TOKEN",
                                  note="AIDA HPC; token must be a NEW one (the previously shared one is exposed)"),
    }


class ProviderRefused(RuntimeError):
    """The call is not made: configuration or transport policy. Never an inference result."""


def _loopback(host: str | None) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def transport_check(spec: ProviderSpec, environ=None) -> dict:
    """Whether a call to ``spec`` may carry its credential. Reads no secret value, only whether it is set."""
    env = os.environ if environ is None else environ
    url = urlparse(spec.base_url)
    problems, optin = [], None
    if url.scheme not in ("http", "https"):
        problems.append(f"UNSUPPORTED_SCHEME: {url.scheme!r}")
    if spec.key_env:
        if not env.get(spec.key_env):
            problems.append(f"CREDENTIAL_NOT_SET: {spec.key_env}")
        if url.scheme == "http" and not _loopback(url.hostname):
            allowed = env.get(spec.insecure_optin_env or "", "")
            if spec.insecure_optin_env and allowed == url.hostname:
                optin = f"{spec.insecure_optin_env}={allowed} (operator accepts the VPN as transport protection)"
            else:
                problems.append(f"INSECURE_TRANSPORT_REFUSED: {spec.key_env} would travel in clear over HTTP to "
                                f"{url.hostname}; no HTTPS endpoint is known"
                                + (f" (opt-in: {spec.insecure_optin_env}={url.hostname})"
                                   if spec.insecure_optin_env else ""))
    return {"provider": spec.name, "scheme": url.scheme, "host": url.hostname, "port": url.port,
            "credential_env": spec.key_env, "credential_present": bool(spec.key_env and env.get(spec.key_env)),
            "plaintext_optin": optin, "ok": not problems, "problems": problems}


def _sha(text: str | bytes | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


def _classify(exc: Exception) -> tuple[str, int | None]:
    msg = str(exc)
    code = re.search(r"HTTP (\d{3})", msg)
    if isinstance(exc, m.AdapterSchemaError):
        return "INVALID_RESPONSE", None
    if isinstance(exc, (m.AdapterDisabled, ProviderRefused)):
        return "REFUSED_BY_POLICY", None
    if code:
        c = int(code.group(1))
        return ("AUTHENTICATION" if c in (401, 403) else "RATE_LIMIT" if c == 429 else
                "SERVER_ERROR" if c >= 500 else "HTTP_ERROR"), c
    if re.search(r"timed? ?out|TimeoutError", msg, re.I):
        return "TIMEOUT", None
    return "CONNECTION", None


RETRYABLE = ("TIMEOUT", "CONNECTION", "SERVER_ERROR", "RATE_LIMIT")


@dataclass
class ProviderClient:
    """Chat completions with an explicit provider chain [primary, *fallback]; every attempt is recorded."""
    chain: list[ProviderSpec]
    retries: int = 0
    timeout_s: float = 120.0
    transport: object = None                  # injected in tests; None = urllib (real network)
    environ: dict | None = None
    log_path: Path | None = None
    records: list[dict] = field(default_factory=list)

    @classmethod
    def from_env(cls, environ=None, **kw) -> "ProviderClient":
        env = os.environ if environ is None else environ
        table = specs(env)
        primary = env.get("TFG_LLM_PROVIDER", "ollama-local")
        names = [primary] + [n.strip() for n in env.get("TFG_LLM_FALLBACK", "").split(",") if n.strip()]
        unknown = [n for n in names if n not in table]
        if unknown:
            raise ProviderRefused(f"UNKNOWN_PROVIDER: {unknown}; known: {sorted(table)}")
        if len(set(names)) != len(names):
            raise ProviderRefused("DUPLICATE_PROVIDER_IN_CHAIN")
        retries = int(env.get("TFG_LLM_RETRIES", "0"))
        if not 0 <= retries <= 3:
            raise ProviderRefused("TFG_LLM_RETRIES must be 0..3")
        return cls(chain=[table[n] for n in names], retries=retries,
                   timeout_s=float(env.get("TFG_LLM_TIMEOUT_S", "120")), environ=env, **kw)

    def _adapter(self, spec: ProviderSpec) -> m.OpenAICompatibleChatAdapter:
        return m.OpenAICompatibleChatAdapter(base_url=spec.base_url, model=spec.model, enabled=True,
                                             api_key_env=spec.key_env, timeout_s=self.timeout_s,
                                             transport=self.transport, provider=spec.name)

    def _record(self, rec: dict) -> None:
        self.records.append(rec)
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")

    def complete(self, messages: list[dict], *, run_id: str | None = None, purpose: str = "chat") -> tuple:
        """(ModelResponse, record of the attempt that answered). Raises the LAST error when every attempt fails."""
        run_id = run_id or str(uuid.uuid4())
        prompt_sha = _sha(json.dumps(messages, sort_keys=True))
        last = None
        env = os.environ if self.environ is None else self.environ
        for position, spec in enumerate(self.chain):
            check = transport_check(spec, env)
            for attempt in range(self.retries + 1):
                rec = {"schema": CALL_SCHEMA, "run_id": run_id, "purpose": purpose, "provider": spec.name,
                       "model": spec.model, "endpoint_host": check["host"], "scheme": check["scheme"],
                       "chain_position": position, "fallback": position > 0, "attempt": attempt,
                       "plaintext_optin": check["plaintext_optin"], "prompt_sha256": prompt_sha,
                       "at": datetime.now(timezone.utc).isoformat()}
                if not check["ok"]:
                    rec.update(status="REFUSED", error_class="REFUSED_BY_POLICY", http_status=None,
                               error="; ".join(check["problems"]), latency_s=0.0)
                    self._record(rec)
                    last = ProviderRefused(rec["error"])
                    break
                started = time.perf_counter()
                old = os.environ.get(spec.key_env) if spec.key_env and self.environ is not None else None
                try:
                    if spec.key_env and self.environ is not None and env.get(spec.key_env):
                        os.environ[spec.key_env] = env[spec.key_env]   # the adapter reads os.environ at call time
                    response = self._adapter(spec).complete(messages)
                    rec.update(status="OK", error_class=None, http_status=200,
                               latency_s=round(response.latency_s, 4), response_model=response.model,
                               response_sha256=_sha(response.text), usage=response.usage, data_kind="MODEL_OUTPUT")
                    self._record(rec)
                    return response, rec
                except Exception as exc:  # noqa: BLE001 - classified, recorded, re-raised at the end
                    cls, code = _classify(exc)
                    rec.update(status="ERROR", error_class=cls, http_status=code,
                               error=str(exc)[:200], latency_s=round(time.perf_counter() - started, 4))
                    self._record(rec)
                    last = exc
                    if cls not in RETRYABLE:
                        break
                finally:
                    if spec.key_env and self.environ is not None:
                        if old is None:
                            os.environ.pop(spec.key_env, None)
                        else:
                            os.environ[spec.key_env] = old
        raise last if last else ProviderRefused("EMPTY_PROVIDER_CHAIN")


# ------------------------------------------------------------------------------------------- Hermes profile block
def hermes_model_block(name: str, environ=None) -> dict:
    """The ``model`` block of a Hermes profile for this provider. Only the key VARIABLE name (key_env) is written."""
    spec = specs(environ)[name]
    block = {"provider": "custom", "base_url": spec.base_url.rstrip("/") + "/v1", "default": spec.model}
    if spec.context_length:
        block.update(context_length=spec.context_length, ollama_num_ctx=spec.context_length)
    if spec.key_env:
        block["key_env"] = spec.key_env
    return block


# ------------------------------------------------------------------------------------------- supervisor intent
INTENT_PROMPT = """Extract a structured reading of a multi-vehicle mission request. Reply with ONE JSON object only.
Keys (omit a key when the request does not say it; never invent values):
 "drones_requested": integer, "rovers_requested": integer, "aerial_sectors": integer,
 "ground_point_count": integer, "return_to_start": boolean.
Request: """
INTENT_KEYS = {"drones_requested": int, "rovers_requested": int, "aerial_sectors": int, "ground_point_count": int,
               "return_to_start": bool}


def parse_intent_reply(text: str) -> dict:
    payload = m_extract(text)
    if not isinstance(payload, dict):
        raise m.AdapterSchemaError("intent reply is not a JSON object")
    out = {}
    for key, typ in INTENT_KEYS.items():
        if key in payload and payload[key] is not None:
            value = payload[key]
            if typ is int and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10):
                raise m.AdapterSchemaError(f"intent field {key} is not a small integer")
            if typ is bool and not isinstance(value, bool):
                raise m.AdapterSchemaError(f"intent field {key} is not a boolean")
            out[key] = value
    return out


def m_extract(text: str):
    from multiagent.interpreters import extract_json
    return extract_json(text)


def model_intent(client: ProviderClient, text: str, *, run_id: str | None = None) -> tuple[dict | None, dict]:
    """(intent or None, provenance). A failed or invalid reply gives None: the deterministic reading alone is
    used and the failure is recorded. The supervisor reconciles any intent against the text anyway."""
    try:
        response, rec = client.complete([{"role": "user", "content": INTENT_PROMPT + text}], run_id=run_id,
                                        purpose="supervisor_intent")
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "NO_MODEL_INTENT", "error_class": _classify(exc)[0], "records": client.records}
    try:
        intent = parse_intent_reply(response.text)
    except m.AdapterSchemaError as exc:
        return None, {"status": "MODEL_INTENT_INVALID", "error": str(exc), "records": client.records}
    return intent, {"status": "MODEL_INTENT", "provider": rec["provider"], "model": rec["model"],
                    "records": client.records}


# ------------------------------------------------------------------------------------------- LangChain
def langchain_chat_model(client: ProviderClient):
    """A LangChain chat model over the same client (langchain_core only; langchain_openai is not required)."""
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    roles = {"human": "user", "ai": "assistant", "system": "system"}

    class SupervisorChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "tfg-supervisor-provider"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            payload = [{"role": roles.get(x.type, "user"), "content": x.content} for x in messages]
            response, rec = client.complete(payload, purpose="langchain")
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content=response.text, response_metadata={"provider": rec["provider"], "model": rec["model"],
                                                          "run_id": rec["run_id"]}))])

    return SupervisorChatModel()


# ------------------------------------------------------------------------------------------- Clef (advisory)
CLEF_STATUS = ("ASSUMED_UNVERIFIED: /v1/systemone shape taken from the project description (state + questions "
               "with allowed options -> probabilities); no authenticated call has been made")


def clef_state_request(model: str, state: dict, questions: list[dict]) -> dict:
    for q in questions:
        if not q.get("id") or not q.get("question") or not isinstance(q.get("options"), list) or len(q["options"]) < 2:
            raise ValueError("each Clef question needs id, question and at least two options")
    return {"model": model, "state": state, "questions": questions}


def clef_state_parse(reply: dict, questions: list[dict]) -> dict:
    """{question_id: {"probabilities": {option: p}, "top": option}}; options outside the allowed set, missing
    questions or probabilities outside [0, 1] are refused."""
    answers = reply.get("answers") if isinstance(reply.get("answers"), list) else reply.get("decisions")
    if not isinstance(answers, list):
        raise m.AdapterSchemaError("clef: no answers list (" + CLEF_STATUS + ")")
    allowed = {q["id"]: set(q["options"]) for q in questions}
    out = {}
    for a in answers:
        qid, probs = (a or {}).get("id") or (a or {}).get("question_id"), (a or {}).get("probabilities")
        if qid not in allowed or not isinstance(probs, dict) or not probs:
            raise m.AdapterSchemaError(f"clef: answer for unknown question or without probabilities: {qid!r}")
        if set(probs) - allowed[qid]:
            raise m.AdapterSchemaError(f"clef: options outside the allowed set for {qid}: {sorted(set(probs) - allowed[qid])}")
        if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1 for p in probs.values()):
            raise m.AdapterSchemaError(f"clef: probability outside [0, 1] for {qid}")
        out[qid] = {"probabilities": probs, "top": max(sorted(probs), key=lambda k: probs[k])}
    if set(out) != set(allowed):
        raise m.AdapterSchemaError(f"clef: missing answers for {sorted(set(allowed) - set(out))}")
    return out


@dataclass
class ClefAdvisor:
    """AIDA Clef as an advisory classifier. ``advise`` returns a record labelled ADVISORY_ONLY: the supervisor may
    show it next to its own deterministic decision, never act on it."""
    transport: object = None
    environ: dict | None = None
    timeout_s: float = 60.0
    log_path: Path | None = None

    def spec(self) -> ProviderSpec:
        env = os.environ if self.environ is None else self.environ
        return ProviderSpec("aida-clef", env.get("AIDA_BASE_URL", m.AIDA_BASE_URL), env.get("AIDA_CLEF_MODEL", "clef"),
                            "AIDA_TOKEN")

    def advise(self, state: dict, questions: list[dict], *, run_id: str | None = None) -> dict:
        spec, env = self.spec(), (os.environ if self.environ is None else self.environ)
        check = transport_check(spec, env)
        rec = {"schema": CALL_SCHEMA, "run_id": run_id or str(uuid.uuid4()), "purpose": "clef_advice",
               "provider": spec.name, "model": spec.model, "endpoint_host": check["host"], "scheme": check["scheme"],
               "prompt_sha256": _sha(json.dumps({"state": state, "questions": questions}, sort_keys=True)),
               "schema_status": CLEF_STATUS, "authority": "ADVISORY_ONLY: never replaces validators or approvals",
               "at": datetime.now(timezone.utc).isoformat()}
        if not check["ok"]:
            rec.update(status="REFUSED", error_class="REFUSED_BY_POLICY", error="; ".join(check["problems"]))
            return self._done(rec)
        adapter = m.AidaClefAdapter(base_url=spec.base_url, model=spec.model, enabled=True, api_key_env=spec.key_env,
                                    timeout_s=self.timeout_s, transport=self.transport, provider="aida-clef")
        old = os.environ.get(spec.key_env)
        try:
            if self.environ is not None and env.get(spec.key_env):
                os.environ[spec.key_env] = env[spec.key_env]
            reply, elapsed = adapter._post(adapter.path, clef_state_request(spec.model, state, questions))
            rec.update(status="OK", latency_s=round(elapsed, 4), advice=clef_state_parse(reply, questions),
                       data_kind="MODEL_OUTPUT")
        except Exception as exc:  # noqa: BLE001
            cls, code = _classify(exc)
            rec.update(status="ERROR", error_class=cls, http_status=code, error=str(exc)[:200])
        finally:
            if self.environ is not None:
                if old is None:
                    os.environ.pop(spec.key_env, None)
                else:
                    os.environ[spec.key_env] = old
        return self._done(rec)

    def _done(self, rec: dict) -> dict:
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec


def status_report(environ=None) -> dict:
    """What each provider needs and whether its call would be allowed now (no network, no secret value)."""
    env = os.environ if environ is None else environ
    out = {name: {**transport_check(spec, env), "model": spec.model, "base_url": spec.base_url, "note": spec.note}
           for name, spec in specs(env).items()}
    clef = ClefAdvisor(environ=env).spec()
    out["aida-clef"] = {**transport_check(clef, env), "model": clef.model, "base_url": clef.base_url,
                        "note": CLEF_STATUS}
    out["selection"] = {"TFG_LLM_PROVIDER": env.get("TFG_LLM_PROVIDER", "ollama-local"),
                        "TFG_LLM_FALLBACK": env.get("TFG_LLM_FALLBACK", ""),
                        "TFG_LLM_RETRIES": env.get("TFG_LLM_RETRIES", "0")}
    return out
