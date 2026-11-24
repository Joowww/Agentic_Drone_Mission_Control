"""Supervisor scenario (declared world for one exercise) and the global mission intent.

A scenario (tfg.multiagent.supervisor-scenario/1) names the operating context, the capability evidence, the parcel's
DECLARED aerial survey points and ground visit points, the rover's declared limits and availability overrides. Every
value is a planning declaration (SYNTHETIC unless stated); nothing is measured here.

The intent (tfg.multiagent.supervisor-intent/1) is what the supervisor understood from the operator's text:
vehicle counts, sector count, ground point count, explicit points, return, stated wind/battery/altitude and unsafe
phrases. Two sources:
  - DETERMINISTIC: ``parse_intent`` over a controlled Spanish/English vocabulary (always computed);
  - HERMES_MODEL: a structured intent produced by the Hermes model and passed with the request. It is accepted only
    where it agrees with the deterministic reading of the same text; a value the text does not state is kept only
    if it names declared scenario elements and is recorded as MODEL_INFERRED (shown at approval). A disagreement with
    a stated fact is a clarification, never an override.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from multiagent.interpreters import RulesInterpreter, unsafe_phrases

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_SCHEMA = "tfg.multiagent.supervisor-scenario/1"
INTENT_SCHEMA = "tfg.multiagent.supervisor-intent/1"

NUMBER_WORDS = {"un": 1, "una": 1, "uno": 1, "one": 1, "a": 1, "an": 1, "single": 1, "dos": 2, "two": 2, "both": 2,
                "ambos": 2, "tres": 3, "three": 3, "cuatro": 4, "four": 4, "cinco": 5, "five": 5}
_N = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RoverLimits(_Strict):
    max_speed_mps: float | None = Field(None, gt=0)
    max_leg_length_m: float | None = Field(None, gt=0)
    max_route_length_m: float | None = Field(None, gt=0)
    timeout_margin_factor: float = Field(2.0, ge=1)
    battery_percent: float | None = Field(None, ge=0, le=100)
    consumption_percent_per_km: float | None = Field(None, gt=0)
    minimum_battery_reserve_percent: float | None = Field(None, ge=0, le=100)
    provenance: str = "SYNTHETIC"


class Parcel(_Strict):
    parcel_id: str
    aerial_survey_points: list[str] = Field(default_factory=list)
    ground_visit_points: list[str] = Field(default_factory=list)


class Availability(_Strict):
    available: bool
    reason: str


class Scenario(_Strict):
    schema_: str = Field(SCENARIO_SCHEMA, alias="schema")
    scenario_id: str
    provenance: str
    description: str | None = None
    context_path: str
    evidence_path: str
    parcel: Parcel
    rover_limits: RoverLimits = Field(default_factory=RoverLimits)
    availability_overrides: dict[str, Availability] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


def load_scenario(path: Path | str) -> Scenario:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCENARIO_SCHEMA:
        raise ValueError(f"not a supervisor scenario: {data.get('schema')!r}")
    return Scenario.model_validate(data)


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


class Intent(_Strict):
    schema_: str = Field(INTENT_SCHEMA, alias="schema")
    source: str = "DETERMINISTIC"
    drones_requested: int | None = Field(None, ge=0)
    rovers_requested: int | None = Field(None, ge=0)
    named_vehicles: list[str] = Field(default_factory=list)
    aerial_scope: str | None = None            # PARCEL (declared survey points) | POINTS (explicit) | None
    aerial_points: list[str] = Field(default_factory=list)
    aerial_sectors: int | None = Field(None, ge=1)
    ground_point_count: int | None = Field(None, ge=0)
    ground_points: list[str] = Field(default_factory=list)
    return_to_start: bool | None = None
    wind_speed_kmh: float | None = Field(None, ge=0)
    battery_percent: dict[str, float] = Field(default_factory=dict)
    altitude_m: float | None = Field(None, gt=0)
    unsafe_requests: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


def _count(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


def _first_count(pattern: str, text: str) -> int | None:
    m = re.search(_N + r"\s+" + pattern, text)
    return _count(m.group(1)) if m else None


def parse_intent(text: str) -> Intent:
    """Deterministic reading over a controlled vocabulary. Unknown wording leaves a field None (never guessed)."""
    lowered = text.lower()
    rules, _ = RulesInterpreter().interpret(text)  # stated wind / battery / altitude / explicit POIs
    contradictions = list(rules.contradictions)
    drones = _first_count(r"(?:drones?|drons?|multirrotores|multirotors?|uavs?)\b", lowered)
    rovers = _first_count(r"(?:rovers?|veh[ií]culos? terrestres?|ugvs?)\b", lowered)
    # a vehicle named only in a battery statement is described, not requested (same rule as RulesInterpreter)
    named = sorted({n for sentence in re.split(r"\.(?=\s|$)|[;\n]", lowered)
                    if not re.search(r"batter|bater[ií]a", sentence)
                    for n in re.findall(r"\b(drone_\d{2}|rover_\d{2})\b", sentence)})
    if drones is None and any(n.startswith("drone_") for n in named):
        drones = len({n for n in named if n.startswith("drone_")})
    if rovers is None and any(n.startswith("rover_") for n in named):
        rovers = len({n for n in named if n.startswith("rover_")})
    sectors = _first_count(r"sector(?:es|s)?\b", lowered)
    ground_count = _first_count(r"(?:puntos? terrestres?|ground points?|waypoints? terrestres?|puntos? (?:de|en) tierra)",
                                lowered)
    # explicit points per SENTENCE: a sentence naming the rover gives ground points (all of them, in order), any
    # other sentence gives aerial points. Coordinates are never accepted here: only declared point ids.
    explicit_ground, explicit_aerial = [], []
    for sentence in re.split(r"\.(?=\s|$)|[;\n]", lowered):
        points = [f"POI_{n}" for n in re.findall(r"\bpoi[_ ]?(\d+)\b", sentence)]
        target = explicit_ground if re.search(r"\brover", sentence) else explicit_aerial
        target.extend(p for p in points if p not in target)
    parcel = bool(re.search(r"\b(?:parcela|parcel|field|campo|zona|area|área)\b", lowered))
    scope = "POINTS" if explicit_aerial else ("PARCEL" if parcel and (drones or sectors) else None)
    ret = True if re.search(r"regres\w*|vuelv\w*|retorn\w*|return\w*|come back|back to (?:their|its) (?:start|initial)"
                            r"|posici[oó]n(?:es)? inicial(?:es)?", lowered) else None
    if re.search(r"(?:no|sin|without|do not|don't)\s+(?:\w+\s+){0,2}(?:regres|volver|return)", lowered):
        ret = False
    return Intent(source="DETERMINISTIC", drones_requested=drones, rovers_requested=rovers, named_vehicles=named,
                  aerial_scope=scope, aerial_points=explicit_aerial, aerial_sectors=sectors,
                  ground_point_count=ground_count if ground_count is not None else (len(explicit_ground) or None),
                  ground_points=explicit_ground, return_to_start=ret, wind_speed_kmh=rules.wind_speed_kmh,
                  battery_percent=dict(rules.battery_percent), altitude_m=rules.altitude_m,
                  unsafe_requests=unsafe_phrases(text), contradictions=contradictions)


GROUNDED_FIELDS = ("drones_requested", "rovers_requested", "aerial_sectors", "ground_point_count", "return_to_start",
                   "wind_speed_kmh", "altitude_m", "aerial_scope")


def reconcile(text: str, model_intent: dict | None, scenario: Scenario) -> tuple[Intent, list[dict], list[str]]:
    """(final intent, decisions, clarifications). The deterministic reading is the authority for stated facts."""
    det = parse_intent(text)
    decisions = [{"decision": "INTENT_DETERMINISTIC", "detail": det.model_dump(by_alias=True)}]
    if model_intent is None:
        return det, decisions, []
    try:
        model = Intent.model_validate({**model_intent, "schema": INTENT_SCHEMA, "source": "HERMES_MODEL"})
    except Exception as exc:  # noqa: BLE001 - an invalid model intent is a clarification, never an override
        return det, decisions + [{"decision": "MODEL_INTENT_REJECTED", "detail": str(exc)[:300]}], \
            [f"MODEL_INTENT_INVALID: {str(exc)[:200]}"]
    clarifications, merged = [], det.model_dump(by_alias=True)
    declared = set(scenario.parcel.aerial_survey_points) | set(scenario.parcel.ground_visit_points)
    for field in GROUNDED_FIELDS:
        stated, proposed = getattr(det, field), getattr(model, field)
        if proposed is None or proposed == stated:
            continue
        if stated is not None:
            clarifications.append(f"MODEL_DISAGREES_WITH_STATED_FACT: {field} text={stated!r} model={proposed!r}")
        else:
            merged[field] = proposed
            decisions.append({"decision": "MODEL_INFERRED", "field": field, "value": proposed,
                              "note": "not stated in the text; shown to the operator at approval"})
    for field in ("aerial_points", "ground_points"):
        proposed, stated = getattr(model, field), getattr(det, field)
        if proposed and proposed != stated:
            unknown = sorted(set(proposed) - declared)
            if stated:
                clarifications.append(f"MODEL_DISAGREES_WITH_STATED_FACT: {field} text={stated} model={proposed}")
            elif unknown:
                clarifications.append(f"MODEL_POINTS_NOT_DECLARED: {unknown}")
            else:
                merged[field] = list(proposed)
                decisions.append({"decision": "MODEL_INFERRED", "field": field, "value": proposed})
    # the model can add unsafe flags (only more conservative), never remove the deterministic ones
    merged["unsafe_requests"] = sorted(set(det.unsafe_requests) | set(model.unsafe_requests))
    merged["source"] = "DETERMINISTIC+HERMES_MODEL"
    return Intent.model_validate(merged), decisions, clarifications
