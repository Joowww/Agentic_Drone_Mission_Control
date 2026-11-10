"""Natural language -> MissionBrief. Two interchangeable interpreters with the same output contract.

- RulesInterpreter: deterministic, controlled English/Spanish vocabulary. It is the offline BASELINE (and what the
  demo uses); it is not presented as language understanding.
- ModelInterpreter: asks a model adapter (multiagent.models) for the same JSON; the reply is parsed and validated
  with the strict MissionBrief model. Nothing the model says is trusted beyond that: the agents re-check
  points, capabilities and constraints deterministically.

``unsafe_phrases`` is also applied by the orchestrator to the raw text whatever the interpreter, so a model that
misses an unsafe request cannot turn it into tasks.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from pydantic import ValidationError

from multiagent.contracts import BRIEF_SCHEMA, MissionBrief

UNSAFE_PATTERNS = {
    "BYPASS_AUTHORIZATION": r"without (?:waiting for |any |an? )?(?:human |operator )?(?:authori[sz]ation|approval)|"
                            r"sin (?:esperar (?:a )?)?(?:la )?(?:autorizaci[oó]n|aprobaci[oó]n)|skip (?:the )?(?:authori[sz]ation|approval|validation)|"
                            r"no (?:need|hace falta) (?:for |de )?(?:authori[sz]ation|autorizaci[oó]n)",
    "IMMEDIATE_EXECUTION": r"\b(?:launch|take ?off|fly|execute|start|drive|go)\b[^.;]{0,40}\b(?:immediately|right now|now)\b|"
                           r"\b(?:despega|vuela|ejecuta|arranca|conduce)\b[^.;]{0,40}\b(?:ya|ahora mismo|inmediatamente)\b",
    "ARM_VEHICLE": r"\b(?:arm|arma)\b (?:the |el )?(?:drone|dron|rover|vehicle|veh[ií]culo)",
    "DISABLE_SAFETY": r"\b(?:disable|turn off|ignore|desactiva|ignora)\b[^.;]{0,30}\b(?:geofence|failsafe|fail-safe|"
                      r"limits?|l[ií]mites?|safety|seguridad|battery reserve|reserva)",
    "ENTER_EXCLUSION": r"\b(?:fly|flying|vuela|sobrevuela|over)\b[^.;]{0,25}\b(?:over )?(?:the )?(?:shed|tree row|no-fly|"
                       r"cobertizo|hilera|zona prohibida)\b",
}
SENSORS = {"multispectral": r"multi-?spectral|multiespectral", "thermal": r"thermal|t[eé]rmic[ao]",
           "rgb": r"\brgb\b|photo|foto|colou?r camera"}
OBJECTIVE_VERBS = r"\b(?:inspect|survey|visit|check|image|photograph|map|inspecciona|revisa|visita|fotograf[ií]a|mapea)\b"
NUMBER = r"(-?\d+(?:[.,]\d+)?)"


def unsafe_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [f"{label}: {m.group(0)!r}" for label, pattern in UNSAFE_PATTERNS.items()
            for m in [re.search(pattern, lowered)] if m]


def _num(value: str) -> float:
    return float(value.replace(",", "."))


def _clauses(text: str) -> list[str]:
    """Sentences, semicolons and commas outside parentheses (coordinates keep their comma)."""
    parts = re.split(r"\.(?=\s|$)|[;\n]|,(?![^()]*\))|\bthen\b|\bluego\b|\bdespu[eé]s\b", text)
    return [c.strip() for c in parts if c and c.strip()]


def _sensor(text: str):
    return next((s for s, p in SENSORS.items() if re.search(p, text)), None)


POI = r"\bpoi[_ ]?(\d+)\b"
NEEDS = r"\s+(?:needs?|requires?|with|con|necesita)\b"
TAIL = r"(?:(?!poi[_ ]?\d)[^()]){0,30}"  # stops at the next point
COORDS = rf"\(\s*{NUMBER}\s*[,;]\s*{NUMBER}\s*\)"


class RulesInterpreter:
    """Deterministic baseline over a controlled vocabulary (POI_n, drone_0n, rover_0n, (x, y), km/h, %, m).

    Sensor attribution: a parenthesis right after a point, or "POI_n needs/requires/with <sensor>", applies to
    that point only; otherwise a sensor named in a clause applies to every point of that clause.
    A condition clause ("once POI_3 has been inspected") makes the NEXT rover clause wait for that point."""
    info = {"provider": "deterministic", "model": "rules-interpreter", "version": "1", "data_kind": "DETERMINISTIC"}

    def interpret(self, text: str) -> tuple[MissionBrief, dict]:
        started = time.perf_counter()
        lowered = text.lower()
        aerial, ground, contradictions = [], [], []
        pending_after = False
        for clause in _clauses(lowered):
            own = {f"POI_{n}": _sensor(inner) for n, inner in re.findall(POI + r"\s*\(([^)]*)\)", clause)}
            own.update({f"POI_{n}": _sensor(tail) for n, tail in re.findall(
                POI + NEEDS + "(" + TAIL + ")", clause) if _sensor(tail)})
            general = _sensor(re.sub(r"\([^)]*\)", "", re.sub(POI + NEEDS + TAIL,
                                                               "", clause)))
            is_ground = bool(re.search(r"\brover", clause))
            after = pending_after or bool(re.search(r"\b(?:once|after|when|cuando|una vez|tras)\b", clause))
            points = [f"POI_{n}" for n in re.findall(POI, clause)]
            coords = [(_num(x), _num(y)) for x, y in re.findall(COORDS, clause)]
            if is_ground:
                pending_after = False
                # "once the drone has reached POI_1, rover_01 drives to POI_1": the destination is the last point.
                targets = points[-1:]
                for point in targets:
                    ground.append({"point_id": point, "coordinates": coords[0] if coords else None, "after_aerial": after})
                if not targets and coords:
                    ground.append({"point_id": None, "coordinates": coords[0], "after_aerial": after})
                if not targets and not coords:
                    ground.append({"point_id": None, "coordinates": None, "after_aerial": after, "description": clause})
                continue
            if after and not re.search(OBJECTIVE_VERBS, clause):
                pending_after = True  # a condition clause, not a new objective
                continue
            if len(points) == 1 and len(coords) == 1:
                aerial.append({"point_id": points[0], "coordinates": coords[0],
                               "required_sensor": own.get(points[0]) or general})
                continue
            for point in points:
                aerial.append({"point_id": point, "coordinates": None, "required_sensor": own.get(point) or general})
            for xy in coords if not points else []:
                aerial.append({"point_id": None, "coordinates": xy, "required_sensor": general})
            if not points and not coords and re.search(OBJECTIVE_VERBS, clause):
                aerial.append({"point_id": None, "coordinates": None, "required_sensor": general, "description": clause})
        merged = {}
        for item in aerial:
            key = (item["point_id"], item["coordinates"]) if item["point_id"] or item["coordinates"] else id(item)
            previous = merged.get(key)
            if previous and previous["required_sensor"] and item["required_sensor"] and \
                    previous["required_sensor"] != item["required_sensor"]:
                contradictions.append(f"SENSOR: {item['point_id']} asked with {previous['required_sensor']} and "
                                      f"{item['required_sensor']}")
            if previous is None or (item["required_sensor"] and not previous["required_sensor"]):
                merged[key] = item
        aerial = list(merged.values())
        winds = sorted({_num(v) for v in re.findall(rf"(?:wind|viento)[^\d.;]{{0,25}}{NUMBER}\s*km/?h", lowered)})
        if len(winds) > 1:
            contradictions.append(f"WIND: {winds} km/h")
        altitudes = sorted({_num(v) for v in re.findall(rf"{NUMBER}\s*m(?:etres|eters|etros)?\b\s*(?:of )?(?:altitude|altura|high|alto|agl)", lowered)}
                           | {_num(v) for v in re.findall(rf"(?:altitude|altura)(?: of| de)?\s*{NUMBER}\s*m\b", lowered)})
        if len(altitudes) > 1:
            contradictions.append(f"ALTITUDE: {altitudes} m")
        battery = {}
        for clause in re.split(r"\.(?=\s|$)|[;\n]", lowered):
            if re.search(r"batter|bater[ií]a", clause):
                ids = [f"drone_{int(n):02d}" for n in re.findall(r"\bdrone[_ ]?0*(\d+)\b", clause)]
                values = [_num(v) for v in re.findall(rf"{NUMBER}\s*%", clause)]
                for drone, value in zip(ids, values):
                    if drone in battery and battery[drone] != value:
                        contradictions.append(f"BATTERY: {drone} {battery[drone]}% and {value}%")
                    battery[drone] = value
        # requested drones: named outside battery statements (a battery fact names a drone without requesting it)
        drones = sorted({f"drone_{int(n):02d}" for clause in re.split(r"\.(?=\s|$)|[;\n]", lowered)
                         if not re.search(r"batter|bater[ií]a", clause)
                         for n in re.findall(r"\bdrone[_ ]?0*(\d+)\b", clause)})
        rovers = sorted({f"rover_{int(n):02d}" for n in re.findall(r"\brover[_ ]?0*(\d+)\b", lowered)})
        brief = {"schema": BRIEF_SCHEMA,
                 "aerial_objectives": [{"objective_id": f"A{i + 1}", **item} for i, item in enumerate(aerial)],
                 "ground_objectives": [{"objective_id": f"G{i + 1}", **item} for i, item in enumerate(ground)],
                 "drones": drones, "rover": rovers[0] if rovers else ("rover_01" if ground else None),
                 "wind_speed_kmh": winds[0] if len(winds) == 1 else None, "battery_percent": battery,
                 "altitude_m": altitudes[0] if len(altitudes) == 1 else None,
                 "unsafe_requests": unsafe_phrases(text), "contradictions": contradictions}
        if len(rovers) > 1:
            brief["contradictions"].append(f"ROVER: several rovers named {rovers}; one ground task per rover")
        return MissionBrief.model_validate(brief), {"latency_s": time.perf_counter() - started, **self.info}


PROMPT_ID = "interpret_brief/1"
PROMPT = """You extract a drone/rover mission brief from an operator request. Reply with ONE JSON object only, no prose.
Schema (all keys required; use null or [] when the request does not say it; never invent coordinates or ids):
{"schema": "tfg.multiagent.mission-brief/1",
 "aerial_objectives": [{"objective_id": "A1", "point_id": "POI_n" or null, "coordinates": [x, y] or null,
                        "required_sensor": "rgb" | "multispectral" | "thermal" | null, "description": null}],
 "ground_objectives": [{"objective_id": "G1", "point_id": "POI_n" or null, "coordinates": [x, y] or null,
                        "after_aerial": true if the rover must wait until a drone reached that point, "description": null}],
 "drones": ["drone_01", ...] only if the request names drones, "rover": "rover_01" or null,
 "wind_speed_kmh": number or null, "battery_percent": {"drone_0n": number}, "altitude_m": number or null,
 "unsafe_requests": [quoted phrases asking to skip authorization, act immediately, arm, disable safety or enter exclusions],
 "contradictions": [descriptions of contradictory values]}
Declared site points: {points}
Request: {text}"""


def extract_json(text: str):
    """The JSON object of a model reply: strips <think> blocks and code fences; None when there is none."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.S)
    candidate = fenced.group(1) if fenced else cleaned[cleaned.find("{"): cleaned.rfind("}") + 1]
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class BriefRejected(ValueError):
    """The model reply is not a valid MissionBrief; the orchestrator asks for clarification instead."""


class ModelInterpreter:
    def __init__(self, adapter, *, site_points: list[str]):
        self.adapter, self.site_points = adapter, site_points
        self.info = dict(adapter.info)

    def interpret(self, text: str) -> tuple[MissionBrief, dict]:
        prompt = PROMPT.replace("{points}", ", ".join(self.site_points)).replace("{text}", text)
        response = self.adapter.complete([{"role": "user", "content": prompt}], json_output=True)
        meta = {**self.info, **response.metadata(), "generation": dict(getattr(self.adapter, "generation", {}) or {}),
                "prompt": {"template_id": PROMPT_ID, "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                           "text": prompt},
                "raw_sha256": hashlib.sha256((response.text or "").encode()).hexdigest()}
        value = extract_json(response.text)
        if value is None:
            raise BriefRejected("MODEL_REPLY_NOT_JSON", meta)
        value.setdefault("schema", BRIEF_SCHEMA)
        try:
            return MissionBrief.model_validate(value), meta
        except ValidationError as exc:
            raise BriefRejected(f"MODEL_REPLY_NOT_A_BRIEF: {exc.error_count()} errors", meta) from exc
