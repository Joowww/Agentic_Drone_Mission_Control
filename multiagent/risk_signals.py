"""Deterministic risk signals of the safety policy safety/2 (used by the v2 pipeline only; v1 stays reproducible).

A signal is EVIDENCE, never a decision: the orchestrator's deterministic policy combines signals from
- DETERMINISTIC_TEXT: this module, over the operator's raw text;
- MODEL_FLAG: phrases the model listed in unsafe_requests, kept even when its reply is invalid JSON;
- STATED_FACT / STATED_AVAILABILITY: values in the text the brief drops or changes;
and refuses on any unsafe signal. No signal can authorize anything.

Beyond the v1 keyword list, detection here is structural:
- groups of terms matched in ANY order inside one sentence (an action word and a protected object), so
  "geofence warnings can be ignored" and "ignore the geofence" are the same signal;
- exclusion names and descriptions come from the SITE description (zones of kind obstacle / no_fly / no_drive),
  not from a fixed list, so a new site brings its own forbidden places;
- prompt-injection markers and requests to choose or make up coordinates.
It remains lexical evidence: paraphrases outside these groups can still pass, which is why model flags are
also kept and why every proposal still needs an external human authorization.
"""
from __future__ import annotations

import re

from multiagent.interpreters import UNSAFE_PATTERNS

POLICY_ID = "safety/2"
SENTENCES = re.compile(r"(?<=[.;!?\n])\s+|\s+-\s+")
GROUPS = {
    # (signal, action terms, object terms): both must appear in the same sentence, in any order.
    "SELF_AUTHORIZATION": (r"\b(?:mark|set|consider|treat|grant|declare|assume|already|pre-?approved)\b|"
                           r"\b(?:is|are|has been|have been)\s+(?:already\s+)?(?:authori[sz]ed|approved|cleared)\b",
                           r"\b(?:authori[sz]ed|authori[sz]ation|approv(?:ed|al)|permission|clearance|"
                           r"movement_authorized|autorizad[oa]|aprobad[oa])\b"),
    "SAFETY_OVERRIDE": (r"\b(?:ignore[ds]?|ignoring|disable[ds]?|disabling|skip(?:ped)?|bypass(?:ed)?|override|"
                        r"turn(?:ed)? off|suppress|switch off|desactiva\w*|ignora\w*|salta\w*)\b",
                        r"\b(?:geofence|geo-fence|failsafe|fail-safe|safety|seguridad|battery|bater[ií]a|reserve|"
                        r"reserva|limits?|l[ií]mites?|checks?|validation|validaci[oó]n|warnings?|alarms?|wind)\b"),
    "IMMEDIATE_EXECUTION": (r"\b(?:launch|take ?off|fly|execute|start|run|drive|go|arm|despega|vuela|ejecuta|arranca)\b",
                            r"\b(?:immediately|right now|now|right away|asap|without delay|ya|ahora|inmediatamente)\b"),
    "ARM_OR_COMMAND": (r"\b(?:arm|arma|start the motors|send the command)\b",
                       r"\b(?:drone|dron|rover|vehicle|veh[ií]culo|motors?|autopilot)\b"),
    "FREE_COORDINATES": (r"\b(?:any|whatever|make up|invent|guess|cualquier\w*|inventa\w*)\b",
                         r"\b(?:coordinates?|positions?|locations?|coordenadas?)\b"),
}
# A request that WAITS for authorization is not a self-authorization ("once authorization is granted").
WAITS_FOR_AUTHORIZATION = re.compile(r"\b(?:wait(?:ing)? for|pending|until|once|after|requires?|needs?|request)\b"
                                     r"[^.;]{0,40}\b(?:authori|approv|permission|clearance)")
INJECTION = re.compile(r"(ignore (?:all |the )?(?:previous|prior|above) (?:instructions|rules)|\bsystem\s*:|"
                       r"you are now|developer mode|olvida las instrucciones)", re.I)
UNAVAILABLE = r"(?:unavailable|not available|out of service|grounded|broken|down|under repair|being repaired|" \
              r"in maintenance|no disponible|averiad[oa]|en mantenimiento)"
UNKNOWN = r"(?:may|might|could) (?:be|not be) (?:available|unavailable)|availability (?:is )?unknown|not sure (?:if|whether)"
AVAILABLE = r"(?:is|are) (?:available|ready|operational)|est[aá] disponible"


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCES.split(text.lower()) if s.strip()]


def text_signals(text: str, site=None) -> list[dict]:
    """Deterministic unsafe signals over the raw operator text (v1 patterns + groups + site exclusions)."""
    signals, lowered = [], text.lower()
    for label, pattern in UNSAFE_PATTERNS.items():  # keep everything v1 detected
        m = re.search(pattern, lowered)
        if m:
            signals.append({"source": "DETERMINISTIC_TEXT", "kind": label, "evidence": m.group(0)})
    for sentence in _sentences(text):
        for label, (action, target) in GROUPS.items():
            a, t = re.search(action, sentence), re.search(target, sentence)
            if a and t and not (label == "SELF_AUTHORIZATION" and WAITS_FOR_AUTHORIZATION.search(sentence)
                                and not re.search(r"\b(?:mark|set|grant|declare)\b", sentence)):
                signals.append({"source": "DETERMINISTIC_TEXT", "kind": label, "evidence": sentence.strip()[:160]})
        if INJECTION.search(sentence):
            signals.append({"source": "DETERMINISTIC_TEXT", "kind": "PROMPT_INJECTION", "evidence": sentence.strip()[:160]})
        if site is not None:
            for zone in site.exclusions:
                names = {zone.zone_id.lower().replace("_", " "), zone.zone_id.lower()}
                if zone.description:
                    names |= {w for w in re.findall(r"[a-z][a-z-]{3,}", zone.description.lower())
                              if w not in {"synthetic", "full", "height", "rover", "only", "zone"}}
                negated = re.search(r"\b(?:do not|don't|never|avoid|without|no)\b[^.;]{0,25}\b(?:over|through|into|"
                                    r"across|cross|enter|fly|drive)\b", sentence)
                if not negated and any(re.search(rf"\b{re.escape(n)}\b", sentence) for n in names) and \
                        re.search(r"\b(?:over|through|into|across|inside|cross|enter|via|sobre|por encima|a trav[eé]s)\b",
                                  sentence):
                    signals.append({"source": "DETERMINISTIC_TEXT", "kind": "ENTER_EXCLUSION",
                                    "evidence": f"{zone.zone_id} ({zone.kind}): {sentence.strip()[:120]}"})
    unique, seen = [], set()
    for s in signals:
        key = (s["kind"], s["evidence"])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def stated_availability(text: str) -> dict:
    """{vehicle_id: AVAILABLE | UNAVAILABLE | UNKNOWN} read deterministically from the raw text."""
    found = {}
    for sentence in _sentences(text):
        ids = [f"{kind}_{int(n):02d}" for kind, n in re.findall(r"\b(drone|rover)[_ ]?0*(\d+)\b", sentence)]
        if not ids:
            continue
        state = "UNKNOWN" if re.search(UNKNOWN, sentence) else "UNAVAILABLE" if re.search(UNAVAILABLE, sentence) \
            else "AVAILABLE" if re.search(AVAILABLE, sentence) else None
        if state:
            for vehicle in ids:
                found[vehicle] = state if found.get(vehicle, state) == state else "UNKNOWN"
    return found


MODEL_FLAGS = re.compile(r'"unsafe_requests"\s*:\s*\[(.*?)\]', re.S)


def salvage_model_flags(raw: str | None) -> list[str]:
    """unsafe_requests strings from a model reply EVEN IF the reply is invalid. Signals only: nothing else of an
    invalid reply is ever used."""
    if not raw:
        return []
    match = MODEL_FLAGS.search(raw)
    return [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1)) if s.strip()][:10] if match else []
