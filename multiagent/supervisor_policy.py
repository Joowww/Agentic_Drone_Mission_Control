"""safety/3: the supervisor's deterministic classification of what an interpreter flagged (opt-in; safety/2 stays the
default and risk_signals.py, frozen for eval_v3, is not modified).

Why: in pilot agents_m1_m3_v1 the model put an availability sentence (D01 "drone_02 is out of service") and an
ambiguous request (D04) in unsafe_requests; safety/2 refuses on ANY model flag, so two safe requests were refused.
safety/3 keeps five outcomes apart instead of turning them all into UNSAFE:

  UNSAFE_REQUEST              -> REFUSED_UNSAFE
  INSUFFICIENT_INFORMATION    -> NEEDS_CLARIFICATION
  RESOURCE_UNAVAILABLE        -> handled by the availability screen (clarification or exclusion, never a refusal)
  INFEASIBLE                  -> decided later by the validators (never here)
  SAFE_PENDING_AUTHORIZATION  -> planning continues; authorization is still required

A model flag is RE-classified only when it is positively explained AND nothing corroborates danger:
1. any deterministic text signal (risk_signals.text_signals) on the request -> every model flag stays UNSAFE;
2. a flag containing an unsafe cue (skip/ignore/override/disable checks, approval claims, arm, keep flying,
   warnings, reserve, geofence, exclusion, invented coordinates...) stays UNSAFE;
3. a flag that is an availability statement (a declared vehicle id + an availability phrase, or the quote of a
   vehicle_availability entry of the brief) -> RESOURCE_UNAVAILABLE;
4. a flag that overlaps an ambiguity the interpreter reported, or restates the request while ambiguities were
   reported -> INSUFFICIENT_INFORMATION;
5. anything else stays UNSAFE (the model's semantic judgement is honoured).
Nothing here can grant authority; the worst a reclassification does is ask for clarification.
"""
from __future__ import annotations

import re

POLICY_ID = "safety/3"
UNSAFE_CUES = re.compile(
    r"\b(skip|ignore|bypass|override|disable|turn off|without (?:authori[sz]ation|approval|checks?|permission)|"
    r"approved|sign(?:ed)? off|authori[sz]|already (?:ok|okay|cleared)|arm\b|take ?off now|immediately|right now|"
    r"keep flying|continue flying|fly anyway|despite|warning|low battery|below (?:the )?reserve|reserve|geofence|"
    r"no[- ]fly|exclusion|restricted|over people|make up|invent|fake|pretend|any coordinates)", re.IGNORECASE)
AVAILABILITY = re.compile(r"\b(out of service|unavailable|not available|in maintenance|under maintenance|maintenance|"
                          r"broken|offline|grounded|is ready|are ready|available|charging)\b", re.IGNORECASE)
VEHICLE_ID = re.compile(r"\b(drone|rover)_\d+\b", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9_ ]+", " ", s.lower()).strip()


def classify_flag(flag: str, *, text: str, brief: dict | None, text_signals: list[dict]) -> dict:
    f = str(flag)
    if text_signals:
        return {"evidence": f, "category": "UNSAFE_REQUEST", "basis": "corroborated by a deterministic text signal"}
    if UNSAFE_CUES.search(f):
        return {"evidence": f, "category": "UNSAFE_REQUEST", "basis": "unsafe cue in the flagged text"}
    quotes = [_norm(a.get("quote") or "") for a in (brief or {}).get("vehicle_availability") or []]
    if (VEHICLE_ID.search(f) and AVAILABILITY.search(f)) or (_norm(f) and any(_norm(f) in q or q in _norm(f)
                                                                                for q in quotes if q)):
        return {"evidence": f, "category": "RESOURCE_UNAVAILABLE", "basis": "availability statement, not a safety issue"}
    ambiguities = [_norm(a) for a in (brief or {}).get("ambiguities") or []]
    nf = _norm(f)
    if nf and nf in ambiguities:  # the same text claimed unsafe AND ambiguous: never whitewashed into a clarification
        return {"evidence": f, "category": "UNSAFE_REQUEST", "basis": "flag copied verbatim into the ambiguities"}
    restates = nf and (nf in _norm(text) or _norm(text) in nf)
    if ambiguities and (restates or any(nf and (nf in a or a in nf) for a in ambiguities)):
        return {"evidence": f, "category": "INSUFFICIENT_INFORMATION", "basis": "the interpreter reported it as ambiguous"}
    return {"evidence": f, "category": "UNSAFE_REQUEST", "basis": "model flag honoured (not explained otherwise)"}


def classify(text: str, brief: dict | None, model_flags: list, text_signals: list[dict]) -> dict:
    flags = [classify_flag(f, text=text, brief=brief, text_signals=text_signals) for f in model_flags or []]
    unsafe = list(text_signals) + [f for f in flags if f["category"] == "UNSAFE_REQUEST"]
    return {"policy": POLICY_ID, "flags": flags, "unsafe": bool(unsafe),
            "insufficient_information": [f["evidence"] for f in flags if f["category"] == "INSUFFICIENT_INFORMATION"],
            "resource_statements": [f["evidence"] for f in flags if f["category"] == "RESOURCE_UNAVAILABLE"]}



# ------------------------------------------------------------------------------------------------ safety/4 --
# safety/3 + an INDEPENDENT deterministic screen of the operator text (the model's view never removes it). Added with
# supervisor prompt interpret_brief/3: when the model stops over-flagging delegations, independent rules must still
# catch requests to disable or ignore safety. risk_signals.text_signals (frozen) already covers authorization bypass,
# arming and immediate execution; this adds what it misses. It can only ADD refusals.
POLICY_V4_ID = "safety/4"
DISABLE_SAFETY = re.compile(
    r"\b(disable|deactivate|turn off|switch off|bypass|skip|ignore|override|suppress|silence)\b[^.;]{0,40}?"
    r"\b(validators?|validations?|checks?|safety|separation|conflicts?|geofences?|limits?|reserves?|warnings?|"
    r"failsafes?|gates?|exclusions?)\b", re.IGNORECASE)


def operator_text_signals(text: str) -> list[dict]:
    return [{"source": "DETERMINISTIC_TEXT", "kind": "DISABLE_OR_IGNORE_SAFETY", "evidence": m.group(0)[:160]}
            for m in DISABLE_SAFETY.finditer(text)]
