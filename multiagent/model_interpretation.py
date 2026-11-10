"""Model interpreter v2: same prompt and brief contract as interpreters.ModelInterpreter (interpret_brief/1), with
explicit failure classes. Lives in its own module because interpreters.py is the file eval_v2 is frozen against.

Classification of a model call (never repaired, never completed):
- INFRASTRUCTURE      the call did not complete (connection, timeout, HTTP, adapter disabled): the case is
                      BLOCKED and is not scored as a model result;
- MODEL_REPLY_EMPTY   no text;
- MODEL_REPLY_TRUNCATED  the service stopped at the token limit (done_reason "length"): not parsed even if the
                      prefix happens to be JSON;
- MODEL_REPLY_NOT_JSON   no JSON object in the reply;
- MODEL_REPLY_NOT_A_BRIEF the JSON does not validate (unknown fields such as an "authorization" key, wrong
                      types, out-of-range values): rejected, the orchestrator asks for clarification.
Text around the JSON object is tolerated but recorded (extra_text). Missing optional values stay null: the
agents then apply only the DECLARED context defaults, and the stated-fact cross-check refuses a brief that drops
a stated battery, wind or altitude. Nothing is invented here.
The raw reply (and any separate reasoning text) is kept in full for later analysis.
"""
from __future__ import annotations

import hashlib
import re

from pydantic import ValidationError

from multiagent.contracts import MissionBrief, MissionBriefV2
from multiagent.interpreters import PROMPT_ID, BriefRejected, extract_json
from multiagent.prompts import PROMPTS, render
from multiagent.risk_signals import salvage_model_flags
from multiagent.models import AdapterDisabled, AdapterSchemaError, AdapterUnavailable

VERSION = "model-interpretation/2"


class InterpretationBlocked(RuntimeError):
    """INFRASTRUCTURE: no model reply to evaluate. args = (reason, meta)."""


class ModelInterpreterV2:
    def __init__(self, adapter, *, site_points: list[str], prompt_id: str = PROMPT_ID):
        self.adapter, self.site_points, self.prompt_id = adapter, site_points, prompt_id
        self.brief_schema = PROMPTS[prompt_id]["brief_schema"]
        self.info = {**adapter.info, "interpreter": VERSION, "prompt_id": prompt_id}

    def interpret(self, text: str) -> tuple[MissionBrief, dict]:
        prompt = render(self.prompt_id, points=self.site_points, text=text)
        meta = {**self.info, "generation": dict(getattr(self.adapter, "generation", {}) or {}),
                "prompt": {"template_id": self.prompt_id, "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                           "text": prompt}}
        try:
            response = self.adapter.complete([{"role": "user", "content": prompt}], json_output=True)
        except (AdapterUnavailable, AdapterDisabled, AdapterSchemaError) as exc:
            meta.update(error_kind="INFRASTRUCTURE", error=f"{type(exc).__name__}: {exc}")
            raise InterpretationBlocked(f"INFRASTRUCTURE: {type(exc).__name__}: {exc}", meta) from exc
        raw = response.text or ""
        meta.update(response.metadata(), raw_text=raw, raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                    reasoning_text=response.reasoning, error_kind=None, json_valid=None, contract_valid=None,
                    model_risk_flags=salvage_model_flags(raw))  # signals survive an invalid reply

        def reject(reason, detail=None):
            meta.update(error_kind="MODEL_OUTPUT", parse_error=reason, parse_detail=detail)
            return BriefRejected(reason, meta)

        if not raw.strip():
            raise reject("MODEL_REPLY_EMPTY")
        if response.finish_reason == "length":
            raise reject("MODEL_REPLY_TRUNCATED", f"stopped at the token limit ({meta['generation'].get('num_predict')})")
        value = extract_json(raw)
        meta["json_valid"] = value is not None
        if value is None:
            raise reject("MODEL_REPLY_NOT_JSON")
        stripped = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
        meta["extra_text"] = not (stripped.startswith("{") and stripped.endswith("}"))
        value.setdefault("schema", self.brief_schema)
        model = MissionBriefV2 if self.brief_schema == "tfg.multiagent.mission-brief/2" else MissionBrief
        if self.prompt_id != PROMPT_ID and value.get("schema") != self.brief_schema:  # v1 path unchanged
            meta["contract_valid"] = False
            raise reject("MODEL_REPLY_NOT_A_BRIEF: wrong schema", [f"schema: {value.get('schema')!r}"])
        try:
            brief = model.model_validate(value)
            meta["contract_valid"] = True
            return brief, meta
        except ValidationError as exc:
            meta["contract_valid"] = False
            errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()][:10]
            raise reject(f"MODEL_REPLY_NOT_A_BRIEF: {exc.error_count()} errors", errors) from exc
