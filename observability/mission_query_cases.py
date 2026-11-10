"""Small catalog of REAL historical preflight records and a deterministic evaluator for Hermes'
structured answers about them. Offline only; never writes or alters a record.

Expected answers come from the raw report files (``expected_answer_from_report``), independently
of the MCP tool's own projection. A value the report does not record is ``UNKNOWN``; it is never
deduced from PASSED, from acceptance checks or from other fields. Current simulator availability is
never part of a historical record, so it is always ``UNKNOWN``.

This is a handful of cases, not a reliability measurement.
"""
from __future__ import annotations

import json
import re

UNKNOWN = "UNKNOWN"
# Answer contract: key -> (python type of a recorded value, extra accepted spellings of UNKNOWN).
ANSWER_FIELDS = {
    "run_id": (str, ()),
    "historical_status": (str, ()),
    "mission_id": (str, ()),
    "vehicle_id": (str, ()),
    "simulated_vehicle": (str, ()),
    "planned_waypoint_ids": (list, ()),
    "reached_waypoint_ids": (list, ()),
    "return_to_home": (bool, ()),
    "mission_landed_event_recorded": (bool, ()),
    "recovery_landing_completed": (bool, ()),
    "current_availability": (str, ("UNKNOWN_NOT_CHECKED",)),
}

# Answer contract v2: where each key comes from in the external view (schema 2), its kind, and how a
# null/absent source is answered. Executor facts, acceptance criteria and recovery are separate
# groups of the view; no key reads acceptance_criteria.
ANSWER_CONTRACT = {
    "run_id": ("/preflights/0/identity/run_id", "text", "null/absent -> UNKNOWN"),
    "historical_status": ("/preflights/0/record/result_status", "text", "null/absent -> UNKNOWN"),
    "mission_id": ("/preflights/0/identity/mission_id", "text", "null/absent -> UNKNOWN"),
    "vehicle_id": ("/preflights/0/identity/vehicle_id", "text", "null/absent -> UNKNOWN"),
    "simulated_vehicle": ("/preflights/0/identity/simulated_vehicle", "text", "null/absent -> UNKNOWN"),
    "planned_waypoint_ids": ("/preflights/0/plan/planned_waypoint_ids", "list of text", "null/absent -> UNKNOWN"),
    "reached_waypoint_ids": ("/preflights/0/executor_facts/reached_waypoint_ids", "list of text",
                             "null/absent -> UNKNOWN"),
    "return_to_home": ("/preflights/0/executor_facts/return_to_home", "boolean",
                       "null/absent -> UNKNOWN; never taken from acceptance_criteria"),
    "mission_landed_event_recorded": ("/preflights/0/executor_facts/mission_landing_events", "boolean",
                                      "true if an event has landed=true; false if the list is empty; "
                                      "null/absent -> UNKNOWN; never taken from recovery_after_failure"),
    "recovery_landing_completed": ("/preflights/0/recovery_after_failure/landing_completed", "boolean",
                                   "null/absent -> UNKNOWN"),
    "current_availability": ("/readiness_now", "text",
                             "UNKNOWN unless the result holds a current check; UNKNOWN_NOT_CHECKED -> UNKNOWN"),
}


# Contract v3 (2026-10-23 design decision): return_to_home is true, false or null (null = not recorded,
# shown to people as "Desconocido"). The key must still be present: an absent key fails. Every other
# key keeps its v2 rule. v2 stays defined so the v1/v2 trial evidence is reviewed exactly as before.
ANSWER_CONTRACT_V3 = {
    **ANSWER_CONTRACT,
    "return_to_home": ("/preflights/0/executor_facts/return_to_home", "boolean or null",
                       "copy true/false; null when not recorded (never the text UNKNOWN); key always present; "
                       "never taken from acceptance_criteria"),
}
CONTRACTS = {"v2": ANSWER_CONTRACT, "v3": ANSWER_CONTRACT_V3}
NULLABLE_KEYS = {"v2": frozenset(), "v3": frozenset({"return_to_home"})}


def answer_json_schema(contract: str = "v3") -> dict:
    """JSON Schema of a valid answer shape (types only; values are checked by evaluate_answer)."""
    kinds = {str: {"type": "string"}, bool: {"type": "boolean"},
             list: {"type": "array", "items": {"type": "string"}}}
    properties = {}
    for key, (kind, aliases) in ANSWER_FIELDS.items():
        if key in NULLABLE_KEYS[contract]:
            properties[key] = {"type": [kinds[kind]["type"], "null"]}
        else:
            unknown = [UNKNOWN, *aliases]
            properties[key] = {"anyOf": [kinds[kind], {"enum": unknown}]} if kind is not str else {"type": "string"}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"tfg.mission-answer/{contract}", "type": "object", "additionalProperties": False,
            "required": list(ANSWER_FIELDS), "properties": properties}


def _pointer(document, pointer):
    node = document
    for part in pointer.split("/")[1:]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def answer_from_external_view(view: dict, contract: str = "v2") -> dict:
    """Apply the answer contract mechanically to one external-view result (schema 2)."""
    answer = {}
    for key, (pointer, _, _) in CONTRACTS[contract].items():
        value = _pointer(view, pointer)
        if key in NULLABLE_KEYS[contract]:
            answer[key] = value if isinstance(value, ANSWER_FIELDS[key][0]) else None
        elif key == "mission_landed_event_recorded":
            answer[key] = (UNKNOWN if not isinstance(value, list)
                           else any(isinstance(e, dict) and e.get("landed") is True for e in value))
        elif key == "current_availability":
            answer[key] = UNKNOWN if value in (None, "UNKNOWN_NOT_CHECKED") else value
        else:
            answer[key] = _recorded(value, ANSWER_FIELDS[key][0])
    return answer


# The three outcome categories the catalog distinguishes (status + stage of the report).
CATEGORIES = {
    ("PASSED", "analyze"): "MISSION_PASSED",
    ("FAILED", "analyze"): "MISSION_FAILURE",
    ("BLOCKED", "validate"): "ADMISSION_BLOCK",
    ("BLOCKED", "check_readiness"): "INFRASTRUCTURE_NOT_READY",
    ("ERROR", "execute"): "INFRASTRUCTURE_OR_EXECUTOR_ERROR",
}

# Real records (2026-10-17/18). ``tracked`` = byte-identical copy versioned in Git; local run
# directories under missions/generated/ are git-ignored. Hashes pin the exact files.
CASES = {
    "passed-467f7ec6": {"run_id": "467f7ec6-b2a6-4b68-9d97-766d85732f8e", "category": "MISSION_PASSED",
                        "report_sha256": "d967bc138c2c9a9834ba0a845417139a491c01953bd9690b610a10ac7b155451",
                        "tracked": None, "note": "already queried by Hermes on 2026-10-22 17:22 UTC (summary view)"},
    "failed-d4519cab": {"run_id": "d4519cab-ebd1-4359-b547-44be38294a6a", "category": "MISSION_FAILURE",
                        "report_sha256": "f265cf77fef275c4f0cc600a546dc6a4e339b80116dc3ba97caf0e25c92777a2",
                        "tracked": "simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/failed_wp3_report.json",
                        "note": "WP3 not reached; recorded recovery landing; no mission LANDED event"},
    "blocked-validate-0844c190": {"run_id": "0844c190-59c8-40cf-991e-93cebbd3cf02", "category": "ADMISSION_BLOCK",
                                  "report_sha256": "63e5c46c7abd2f0bbb75780e0c3cc25f490de6f4864971022f5a2b5fe090c8c1",
                                  "tracked": "simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/blocked_battery_report.json",
                                  "note": "battery reserve; never executed"},
    "blocked-readiness-d7717942": {"run_id": "d7717942-9b43-45c7-bf3a-65b02bb1155a",
                                   "category": "INFRASTRUCTURE_NOT_READY",
                                   "report_sha256": "2cdb2b9a8baa9dffe543aab67f61b89c7aaed49a0dba37a20972edcafcc00c02",
                                   "tracked": "simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/blocked_readiness_report.json",
                                   "note": "simulation not ready at the time; never executed"},
    "error-execute-1b69dfc7": {"run_id": "1b69dfc7-0707-4b68-a009-062610418fe4",
                               "category": "INFRASTRUCTURE_OR_EXECUTOR_ERROR",
                               "report_sha256": "2ab1614fbec51fc827dc108d6cc863c212d0f5595a21c5ff91526791ec259a61",
                               "tracked": None,
                               "note": "ROS 2 command timeout during execution; flight outcome recorded as unknown"},
    "not-found": {"run_id": "00000000-0000-4000-8000-000000000000", "category": "NOT_FOUND",
                  "report_sha256": None, "tracked": None, "note": "no such run; checked unused before each trial"},
}


def _recorded(value, kind):
    """The value if the report records it with the contract's type, else UNKNOWN."""
    if kind is list:
        return list(value) if isinstance(value, list) and all(isinstance(v, str) for v in value) else UNKNOWN
    if kind is bool:
        return value if isinstance(value, bool) else UNKNOWN
    return value if isinstance(value, str) and value else UNKNOWN


def expected_answer_from_report(report: dict, contract: str = "v2") -> dict:
    """Expected structured answer read directly from one raw report (no tool code involved)."""
    identity = report.get("mission_identity") if isinstance(report.get("mission_identity"), dict) else {}
    executor = report.get("executor_result") if isinstance(report.get("executor_result"), dict) else {}
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    events = executor.get("events")
    recovery = executor.get("recovery") if isinstance(executor.get("recovery"), dict) else {}
    if isinstance(events, list):
        reached = [e.get("waypoint_id") for e in events if isinstance(e, dict)
                   and e.get("event") == "WAYPOINT_REACHED" and e.get("reached") is True]
        landed = any(isinstance(e, dict) and e.get("event") == "LANDED" and e.get("landed") is True for e in events)
    else:
        reached, landed = UNKNOWN, UNKNOWN  # no event log recorded: progress and landing are unknown
    return {
        "run_id": _recorded(report.get("run_id"), str),
        "historical_status": _recorded(report.get("status"), str),
        "mission_id": _recorded(identity.get("mission_id"), str),
        "vehicle_id": _recorded(identity.get("vehicle_id"), str),
        "simulated_vehicle": _recorded(identity.get("simulated_vehicle"), str),
        "planned_waypoint_ids": _recorded(analysis.get("expected_waypoint_ids"), list),
        "reached_waypoint_ids": reached if reached == UNKNOWN else _recorded(reached, list),
        "return_to_home": (executor.get("return_to_home") if isinstance(executor.get("return_to_home"), bool) else None)
                          if "return_to_home" in NULLABLE_KEYS[contract]
                          else _recorded(executor.get("return_to_home"), bool),
        "mission_landed_event_recorded": landed,
        "recovery_landing_completed": _recorded(recovery.get("landing_completed"), bool),
        "current_availability": UNKNOWN,
    }


def parse_answer(text: str):
    """(object or None, parse status). Only a single JSON object, optionally inside one ```json fence."""
    stripped = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.S)
    body, status = (fenced.group(1), "FENCED_JSON_OBJECT") if fenced else (stripped, "JSON_OBJECT")
    try:
        value = json.loads(body)
    except (ValueError, RecursionError):  # pathological nesting is unparseable, not a crash
        return None, "NOT_JSON" if stripped else "EMPTY"
    return (value, status) if isinstance(value, dict) else (None, "NOT_AN_OBJECT")


def _field_outcome(answer, expected, kind, aliases, nullable=False):
    if nullable:  # v3 return_to_home: true / false / null, nothing else
        if answer is None:
            return "match" if expected is None else "unknown_but_recorded"
        if type(answer) is not kind:  # "UNKNOWN", "false", 0 are not accepted spellings
            return "wrong_type"
        if expected is None:
            return "invented_value"  # the record says nothing (e.g. false read from acceptance_criteria)
        return "match" if answer == expected else "mismatch"
    if expected == UNKNOWN:
        if answer == UNKNOWN or answer in aliases:
            return "match"
        if answer is None:
            # Copying the source null breaks the answer format, but invents nothing (2026-10-23 v2 trial;
            # that evidence was reviewed before this distinction and keeps its "invented_value" label).
            return "null_instead_of_unknown"
        return "invented_value"  # the record says nothing; any concrete value is a deduction
    if answer == UNKNOWN or answer in aliases:
        return "unknown_but_recorded"
    if kind is list:
        if not (isinstance(answer, list) and all(isinstance(v, str) for v in answer)):
            return "wrong_type"
    elif type(answer) is not kind:  # True is not 1, "true" is not True
        return "wrong_type"
    return "match" if answer == expected else "mismatch"


def evaluate_answer(text: str, expected: dict, contract: str = "v2") -> dict:
    """Per-field outcomes only; the answer's values are never copied into the result. Nothing is
    normalized: a wrong spelling stays wrong (no UNKNOWN<->null conversion, no string booleans)."""
    answer, parse_status = parse_answer(text)
    return evaluate_parsed(answer, parse_status, expected, contract)


def evaluate_parsed(answer, parse_status: str, expected: dict, contract: str = "v2") -> dict:
    """evaluate_answer for an answer already read by parse_answer (one interpretation, one rule)."""
    if answer is None:
        return {"verdict": "ANSWER_NOT_PARSEABLE", "parse_status": parse_status, "fields": {},
                "extra_keys": 0, "contract": contract}
    fields = {}
    for key, (kind, aliases) in ANSWER_FIELDS.items():
        fields[key] = ("missing" if key not in answer else
                       _field_outcome(answer[key], expected[key], kind, aliases, key in NULLABLE_KEYS[contract]))
    extra = sorted(set(answer) - set(ANSWER_FIELDS))
    verdict = "ALL_FIELDS_CORRECT" if all(o == "match" for o in fields.values()) and not extra else "FIELDS_INCORRECT"
    return {"verdict": verdict, "contract": contract, "parse_status": parse_status, "fields": fields,
            "extra_keys": len(extra),
            "counts": {o: sum(v == o for v in fields.values()) for o in sorted(set(fields.values()))}}
