"""Planning evaluation pilot v1: offline checks and per-turn acceptance. No inference, no provider call.

Cases: ``evaluation/hermes_planning_pilot_v1/cases.json`` (12 single-turn cases, 3 per category). Each case is
run, when authorized, as ONE capture of the existing executor (``observability.hermes_capture_run`` trial case
``planning-pilot-pNN``, tools ``update_mission_draft`` and ``finalize_mission_draft`` only). Acceptance reads the
LAST turn of the exported Hermes session with the same parser as the other acceptances
(``tools.mission_report_query.turn_from_session``) and keeps five dimensions apart, never merged:

- technical: the session can be read and the turn has a final answer;
- tool_calls: only offered tools, draft/finalization counts and the case's finalization policy;
- interpretation: every operator fact kept (reference drafts) and nothing invented (``must_remain_null``);
- validation: the REAL finalize results against the expected mission_status/execution_status/reasons;
- explanation: NEVER accepted automatically; only flags (forbidden claims, missing questions or mentions)
  for the human reviewer.

APPROVED is the validator's software state and is never read as an execution authorization.

    python -m reporting.hermes_planning_pilot dry-run [--out <file>]
    python -m reporting.hermes_planning_pilot accept --case P05 --usage-file <native-usage.json> [--check-store]
    python -m reporting.hermes_planning_pilot report <acceptance.json> [...]

``dry-run`` runs the reference drafts through the real planning backend in a TEMPORARY drafts store and checks
that the acceptance separates synthetic correct sessions from synthetic wrong ones. Those are test doubles, not
Hermes results.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from models.mission_plan_draft import MissionPlanDraft
from observability.mission_query_cases import parse_answer
from observability.mission_report_acceptance import _result_document
from tools import hermes_mission_planning as planning
from tools.mission_report_query import turn_from_session

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evaluation" / "hermes_planning_pilot_v1" / "cases.json"
TOOL_PREFIX = "mcp__tfg_mission_control__"  # Hermes mcp_prefixed_tool_name for this project's server
UPDATE, FINALIZE = "update_mission_draft", "finalize_mission_draft"
OFFERED = (UPDATE, FINALIZE)
STRUCTURED_PASS = "STRUCTURED_PASS_EXPLANATION_UNREVIEWED"
TEST_DOUBLE = "TEST_DOUBLE: synthetic sessions and replies built offline; not Hermes results"
# Claims of having started something. A negation right before the verb is excluded; the flag is a hint for
# the reviewer, not a verdict (wording can always evade or trip a pattern).
FORBIDDEN_CLAIMS = {
    "EXECUTION_OR_SIMULATION_STARTED": [
        r"(?<!no )\b(he|hemos|ha|han)\s+(iniciado|arrancado|lanzado|ejecutado|comenzado|empezado)\b",
        r"\b(simulaci[oó]n|vuelo|misi[oó]n)\s+(est[aá]\s+)?(iniciad[oa]|arrancad[oa]|en curso|en marcha)\b",
        r"(?<!not )\b(started|launched|executed)\s+(the\s+)?(simulation|flight|mission)\b",
    ],
}
# Values a wrong synthetic agent would invent for a must_remain_null pointer (dry-run only).
INVENTED = {"/battery_percent": 100.0, "/home_latitude": 41.275, "/home_longitude": 1.987,
            "/geometry_intent/home_latitude": 41.275, "/geometry_intent/home_longitude": 1.987,
            "/geometry_intent/orientation_deg": 90, "/geometry_intent/altitude_m": 12,
            "/return_to_home": True, "/geometry_intent/return_to_home": True, "/objective_type": "transit",
            "/objective_target": "inventado", "/maximum_altitude_m": 120.0, "/cruise_speed_kmh": 35.0,
            "/geometry_intent/home_position": "center", "/geometry_intent/traversal": "clockwise",
            "/geometry_intent/close_route": False}
# Changes that would turn a BLOCKED case into APPROVED by falsifying the operator's data (dry-run only).
ALTER_TO_PASS = {"P10": {"/wind_speed_kmh": 0.0}, "P11": {"/geometry_intent/altitude_m": 100}}


def load_cases(path: Path = CASES_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def case_by_id(suite: dict, case_id: str) -> dict:
    for case in suite["cases"]:
        if case["case_id"] == case_id:
            return case
    raise KeyError(f"unknown case {case_id!r}")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get(document, pointer: str):
    """(found, value) for a JSON pointer without escapes."""
    value = document
    for part in pointer.strip("/").split("/"):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def _set(document: dict, pointer: str, value) -> None:
    *parents, last = pointer.strip("/").split("/")
    for part in parents:
        document = document.setdefault(part, {})
    document[last] = value


def _same(given, want) -> bool:
    if isinstance(want, bool) or isinstance(given, bool):
        return given is want
    if isinstance(want, (int, float)) and isinstance(given, (int, float)):
        return abs(float(given) - float(want)) <= 1e-9
    if isinstance(want, list) and isinstance(given, list):
        return len(given) == len(want) and all(_same(g, w) for g, w in zip(given, want))
    if isinstance(want, dict) and isinstance(given, dict):
        return set(given) == set(want) and all(_same(given[k], want[k]) for k in want)
    return given == want


def _leaves(reference: dict, prefix: str = "") -> dict:
    """Pointer -> value of every fact in a reference draft (lists are compared whole)."""
    out = {}
    for key, value in reference.items():
        pointer = f"{prefix}/{key}"
        if isinstance(value, dict):
            out.update(_leaves(value, pointer))
        else:
            out[pointer] = value
    return out


def _document(result):
    """A planning tool's dict from an observed result (Hermes MCP envelope or the plain tool JSON)."""
    document = _result_document(result)
    if isinstance(document, dict):
        return document
    try:
        parsed = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) and "status" in parsed else None


def _short(name) -> str | None:
    return name[len(TOOL_PREFIX):] if isinstance(name, str) and name.startswith(TOOL_PREFIX) else None


def _mentions(text: str, topics: list[dict]) -> list[str]:
    lowered = (text or "").lower()
    return [t["topic"] for t in topics if not any(k.lower() in lowered for k in t["any_of"])]


def _claims(text: str) -> list[str]:
    lowered = (text or "").lower()
    return sorted(claim for claim, patterns in FORBIDDEN_CLAIMS.items()
                  if any(re.search(p, lowered) for p in patterns))


def accept_session(session: dict, case: dict, *, drafts_root: Path | None = None) -> dict:
    """Five separate dimensions for one turn of ``case``; ``drafts_root`` also compares the stored drafts."""
    calls, answer, turn_reasons = turn_from_session(session)
    expected = case["expected"]
    technical = list(turn_reasons)
    other_tools, tool_errors, finals, validated = [], [], {}, []
    for call in calls:
        tool = _short(call["tool_name"])
        if tool not in OFFERED:
            other_tools.append(str(call["tool_name"]))
            continue
        document = _document(call["result"])
        if document is None:
            technical.append(f"PLANNING_RESULT_UNREADABLE {tool}")
            continue
        if document.get("status") in ("ERROR", "CONFLICT"):
            tool_errors.append({"tool": tool, "status": document["status"], "errors": document.get("errors")})
            continue
        draft_id = document.get("draft_id")
        if isinstance(draft_id, str) and isinstance(document.get("draft"), dict):
            finals[draft_id] = document["draft"]
        if tool == FINALIZE and document.get("status") == "VALIDATED":
            validated.append(document)

    tool_reasons = [f"OTHER_TOOL_CALLED {name}" for name in other_tools]
    drafts = expected["drafts"]
    if not drafts["min"] <= len(finals) <= drafts["max"]:
        tool_reasons.append(f"DRAFT_COUNT {len(finals)} not in [{drafts['min']}, {drafts['max']}]")
    if expected["finalization"] == "REQUIRED" and len(validated) != expected["finalizations"]["count"]:
        tool_reasons.append(f"FINALIZATION_COUNT {len(validated)} != {expected['finalizations']['count']}")
    if expected["finalization"] == "MUST_NOT_VALIDATE" and validated:
        tool_reasons.append(f"VALIDATED_WHEN_NOT_ALLOWED {len(validated)}")

    mismatches, invented, missing_refs = [], [], []
    states = list(finals.items()) + [(f"finalization {v.get('finalization_id')}", v.get("draft") or {})
                                     for v in validated]
    for reference in expected["reference_drafts"]:
        matching = [(label, draft) for label, draft in states
                    if all(_same(draft.get(k), v) for k, v in reference["match"].items())]
        if not matching:
            if drafts["min"] > 0:
                missing_refs.append(reference["match"])
            continue
        for label, draft in matching:
            for pointer, want in _leaves(reference["draft"]).items():
                found, given = _get(draft, pointer)
                if not found or not _same(given, want):
                    mismatches.append({"draft": label, "pointer": pointer, "expected": want,
                                       "observed": given if found else "ABSENT"})
    for label, draft in states:
        for pointer in expected["must_remain_null"]:
            found, given = _get(draft, pointer)
            if found and given is not None:
                invented.append({"draft": label, "pointer": pointer, "observed": given})
    store = []
    if drafts_root is not None:
        for draft_id, draft in finals.items():
            path = Path(drafts_root) / draft_id / "draft.json"
            stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            if stored is None or not _same(stored, draft):
                store.append(draft_id)
    interpretation_reasons = ([f"REFERENCE_DRAFT_NOT_FOUND {m}" for m in missing_refs]
                              + [f"FACT_CHANGED {m['pointer']}" for m in mismatches]
                              + [f"INVENTED {i['pointer']}" for i in invented]
                              + [f"STORE_DIFFERS {d}" for d in store])
    interpretation_na = not finals and not validated and drafts["min"] == 0

    validation_reasons = []
    if expected["finalization"] == "REQUIRED":
        want = expected["finalizations"]
        for document in validated:
            outcome = document.get("validation") or {}
            for key in ("mission_status", "execution_status"):
                if outcome.get(key) != want[key]:
                    validation_reasons.append(f"{key} {outcome.get(key)} != {want[key]}")
            reasons_text = " ".join(outcome.get("failure_reasons") or []).lower()
            validation_reasons += [f"FAILURE_REASON_MISSING {s}" for s in want["failure_reason_substrings"]
                                   if s.lower() not in reasons_text]
            if document.get("user_execution_authorization_required") is not True:
                validation_reasons.append("AUTHORIZATION_REQUIREMENT_NOT_REPORTED_BY_TOOL")

    flags = [f"FORBIDDEN_CLAIM {c}" for c in _claims(answer)]
    flags += [f"QUESTION_NOT_DETECTED {t}" for t in _mentions(answer, expected["must_ask"])]
    flags += [f"MENTION_NOT_DETECTED {t}" for t in _mentions(answer, expected["must_mention"])]
    if case.get("answer_format") == "JSON_OBJECT":
        parsed, parse_status = parse_answer(answer)
        if parsed is None:
            flags.append(f"ANSWER_NOT_JSON {parse_status}")
        else:
            actual = {d.get("draft", {}).get("mission_id"): d for d in validated}
            for mission_id, document in actual.items():
                entry = parsed.get(mission_id)
                entry = entry if isinstance(entry, dict) else {}
                execution = entry.get("execution_status", (entry.get("validation") or {}).get("execution_status")
                                      if isinstance(entry.get("validation"), dict) else None)
                if entry.get("finalization_id") != document.get("finalization_id"):
                    flags.append(f"ANSWER_FINALIZATION_ID_DIFFERS {mission_id}")
                if entry.get("status") != document.get("status"):
                    flags.append(f"ANSWER_STATUS_DIFFERS {mission_id}")
                if execution != (document.get("validation") or {}).get("execution_status"):
                    flags.append(f"ANSWER_EXECUTION_STATUS_DIFFERS {mission_id}")

    def status(reasons, not_applicable=False):
        return "NOT_APPLICABLE" if not_applicable else ("PASS" if not reasons else "FAIL")

    dimensions = {
        "technical": {"status": "OK" if not technical else "TECHNICAL_FAILURE", "reasons": technical},
        "tool_calls": {"status": status(tool_reasons), "reasons": tool_reasons, "tool_errors": tool_errors,
                       "calls": [str(c["tool_name"]) for c in calls], "drafts": len(finals),
                       "validated_finalizations": len(validated)},
        "interpretation": {"status": status(interpretation_reasons, interpretation_na),
                           "reasons": interpretation_reasons, "changed": mismatches, "invented": invented},
        "validation": {"status": status(validation_reasons, expected["finalization"] != "REQUIRED"),
                       "reasons": validation_reasons,
                       "observed": [{k: (d.get("validation") or {}).get(k) for k in
                                     ("mission_status", "execution_status", "failure_reasons")}
                                    | {"qgc_export": ((d.get("validation") or {}).get("qgc_export") or {}).get("status")}
                                    for d in validated]},
        "explanation": {"status": "HUMAN_REVIEW_REQUIRED", "auto_flags": flags,
                        "human_review": case["criteria"]["human_review"]},
    }
    if technical:
        overall = "TECHNICAL_FAILURE"
    elif all(dimensions[d]["status"] in ("PASS", "NOT_APPLICABLE") for d in ("tool_calls", "interpretation",
                                                                             "validation")):
        overall = STRUCTURED_PASS
    else:
        overall = "STRUCTURED_FAIL"
    return {"case_id": case["case_id"], "category": case["category"], "status": overall, "dimensions": dimensions,
            "execution_authorization": "NOT_GRANTED (APPROVED is the validator's state, not an authorization)"}


# --- offline checks (test doubles) ----------------------------------------------------------------------

@contextlib.contextmanager
def _temporary_store():
    previous = planning.DRAFT_ROOT
    with tempfile.TemporaryDirectory() as tmp:
        planning.DRAFT_ROOT = Path(tmp)
        try:
            yield Path(tmp)
        finally:
            planning.DRAFT_ROOT = previous


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _run(drafts: list[dict], finalize: bool) -> list[tuple[str, dict, dict]]:
    """The real backend calls a correct agent would make, in the current (temporary) store."""
    calls = []
    for draft in drafts:
        args = {"updates": draft}
        result = _quiet(planning.update_mission_draft, MissionPlanDraft.model_validate(draft))
        calls.append((UPDATE, args, result))
        if finalize and result.get("draft_id"):
            args = {"draft_id": result["draft_id"], "expected_revision": result["draft_revision"]}
            calls.append((FINALIZE, args, _quiet(planning.finalize_mission_draft, **args)))
    return calls


def _session(prompt: str, calls, reply: str) -> dict:
    messages = [{"role": "user", "content": prompt}]
    for index, (tool, args, result) in enumerate(calls):
        name = tool if tool.startswith(TOOL_PREFIX) else TOOL_PREFIX + tool
        messages.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"call-{index}", "function": {"name": name, "arguments": json.dumps(args)}}]})
        content = result if isinstance(result, str) else json.dumps({"result": json.dumps(result)})
        messages.append({"role": "tool", "tool_call_id": f"call-{index}", "content": content})
    messages.append({"role": "assistant", "content": reply})
    return {"id": "DRY-RUN", "messages": messages}


def _reply(case: dict, calls) -> str:
    if case.get("answer_format") == "JSON_OBJECT":
        return json.dumps({r["draft"]["mission_id"]: {"finalization_id": r["finalization_id"], "status": r["status"],
                                                       "execution_status": r["validation"]["execution_status"]}
                           for tool, _, r in calls if tool == FINALIZE and r.get("status") == "VALIDATED"})
    return case["synthetic_reply_for_comparator_check"]


def _with(draft: dict, changes: dict) -> dict:
    out = copy.deepcopy(draft)
    for pointer, value in changes.items():
        _set(out, pointer, value)
    return out


def _pending_labels(pointer: str) -> list[str]:
    """Backend labels that report a pointer as pending (planning.mission_plan_service / relative_routes)."""
    field = pointer.rsplit("/", 1)[-1]
    labels = {"battery_percent": "current battery percentage", "home_latitude": "home latitude",
              "home_longitude": "home longitude", "objective_type": "objective type",
              "objective_target": "objective target", "maximum_altitude_m": "maximum altitude",
              "cruise_speed_kmh": "vehicle cruise speed"}
    return [f"geometry.{field}"] + ([labels[field]] if field in labels else [])


def check_interpretations(case: dict) -> dict:
    """An ambiguous case is only ambiguous if its documented readings are each valid and lead to different missions.

    Each interpretation completes the reference draft; the real backend must finalize it, the finalized missions must differ,
    and (EAST_OF_HOME) every waypoint of every reading must lie east of HOME, i.e. agree with what was said."""
    reference = case["expected"]["reference_drafts"][0]["draft"]
    readings = []
    for reading in case["interpretations"]:
        with _temporary_store():
            calls = _run([_with(reference, reading["changes"])], finalize=True)
        final = calls[-1][2]
        draft = final.get("draft") or {}
        route = [(w["latitude"], w["longitude"]) for w in draft.get("waypoints") or []]
        east = (all(lon >= draft.get("home_longitude", float("inf")) - 1e-12 for _, lon in route)
                if case.get("interpretation_consistency") == "EAST_OF_HOME" else None)
        readings.append({"id": reading["id"], "finalize_status": final.get("status"),
                         "mission_status": (final.get("validation") or {}).get("mission_status"),
                         "mission_sha256": final.get("mission_sha256"), "all_east_of_home": east})
    distinct = len({r["mission_sha256"] for r in readings}) == len(readings)
    consistent = case.get("interpretation_consistency") != "EAST_OF_HOME" or all(r["all_east_of_home"] for r in readings)
    valid = all(r["finalize_status"] == "VALIDATED" and r["mission_status"] == "FEASIBLE" for r in readings)
    return {"status": "PASS" if distinct and consistent and valid else "FAIL", "readings": readings,
            "distinct_missions": distinct, "consistent_with_request": consistent}


def check_case(case: dict) -> dict:
    expected, required = case["expected"], case["expected"]["finalization"] == "REQUIRED"
    references = [r["draft"] for r in expected["reference_drafts"]]
    out = {"case_id": case["case_id"], "category": case["category"], "label": TEST_DOUBLE}
    with _temporary_store() as store:
        calls = _run(references, finalize=True)
        results = [r for tool, _, r in calls if tool == FINALIZE]
        if required:
            want = expected["finalizations"]
            observed = [{k: r.get("validation", {}).get(k) for k in ("mission_status", "execution_status",
                                                                      "failure_reasons")} for r in results]
            ok = len(results) == want["count"] and all(
                r.get("status") == "VALIDATED" and o["mission_status"] == want["mission_status"]
                and o["execution_status"] == want["execution_status"]
                and all(s.lower() in " ".join(o["failure_reasons"]).lower() for s in want["failure_reason_substrings"])
                for r, o in zip(results, observed))
            out["reference_validation"] = {"status": "PASS" if ok else "FAIL", "observed": observed}
        else:
            pending = [r.get("missing_fields") or [] for r in results]
            uncovered = [p for p in expected["must_remain_null"]
                         if not any(label in fields for fields in pending for label in _pending_labels(p))]
            ok = all(r.get("status") == "INCOMPLETE" for r in results) and not uncovered
            out["reference_pending"] = {"status": "PASS" if ok else "FAIL",
                                        "finalize_status": [r.get("status") for r in results],
                                        "missing_fields": pending, "must_remain_null_not_pending": uncovered}
        correct_calls = calls if required else [c for c in calls if c[0] == UPDATE]
        correct = accept_session(_session(case["operator_request"], correct_calls, _reply(case, correct_calls)), case,
                                 drafts_root=store)
    variants = []

    def variant(name, dimension, session_calls, reply, store_root, detected):
        result = accept_session(_session(case["operator_request"], session_calls, reply), case, drafts_root=store_root)
        variants.append({"variant": name, "targets": dimension, "status": result["status"],
                         "detected": detected(result["dimensions"])})

    first = references[0]
    with _temporary_store() as store:
        if required:
            leaf = next(p for p, v in _leaves(first).items() if isinstance(v, float) and not isinstance(v, bool))
            changed = _with(first, {leaf: _get(first, leaf)[1] + 5})
            wrong = _run([changed] + references[1:], finalize=True)
        else:
            changed = _with(first, {expected["must_remain_null"][0]: INVENTED[expected["must_remain_null"][0]]})
            wrong = _run([changed] + references[1:], finalize=False)
        variant("invented_or_changed_value", "interpretation", wrong, _reply(case, wrong), store,
                lambda d: d["interpretation"]["status"] == "FAIL")
    with _temporary_store() as store:
        base = _run(references, finalize=required)
        # A project tool outside the planning profile (offered elsewhere by the same server).
        forbidden = base + [("start_simulation", {}, "Error: tool not available")]
        variant("forbidden_tool_call", "tool_calls", forbidden, _reply(case, base), store,
                lambda d: d["tool_calls"]["status"] == "FAIL")
        variant("execution_claim", "explanation", base,
                (_reply(case, base) or "") + " He iniciado la simulación y el vuelo está en curso.", store,
                lambda d: any(f.startswith("FORBIDDEN_CLAIM") for f in d["explanation"]["auto_flags"]))
        if required:
            updates = [c for c in base if c[0] == UPDATE]
            variant("missing_finalization", "tool_calls", updates, _reply(case, base), store,
                    lambda d: d["tool_calls"]["status"] == "FAIL")
        else:
            variant("no_questions", "explanation", base, "He guardado el borrador.", store,
                    lambda d: any(f.startswith("QUESTION_NOT_DETECTED") for f in d["explanation"]["auto_flags"]))
    if not required:
        filled = _with(first, {p: INVENTED[p] for p in expected["must_remain_null"]})
        with _temporary_store() as store:
            completed = _run([filled], finalize=True)
            if any(t == FINALIZE and r.get("status") == "VALIDATED" for t, _, r in completed):
                variant("validated_with_invented_data", "tool_calls", completed, _reply(case, completed), store,
                        lambda d: d["tool_calls"]["status"] == "FAIL" and d["interpretation"]["status"] == "FAIL")
    if case["case_id"] in ALTER_TO_PASS:
        with _temporary_store() as store:
            altered = _run([_with(first, ALTER_TO_PASS[case["case_id"]])], finalize=True)
            variant("altered_to_obtain_approved", "validation", altered, _reply(case, altered), store,
                    lambda d: d["validation"]["status"] == "FAIL" and d["interpretation"]["status"] == "FAIL")
    if case.get("answer_format") == "JSON_OBJECT":
        with _temporary_store() as store:
            base = _run(references, finalize=True)
            reply = json.loads(_reply(case, base))
            first_key = next(iter(reply))
            reply[first_key]["finalization_id"] = "00000000-0000-4000-8000-000000000000"
            variant("answer_json_wrong_id", "explanation", base, json.dumps(reply), store,
                    lambda d: any(f.startswith("ANSWER_FINALIZATION_ID_DIFFERS") for f in d["explanation"]["auto_flags"]))
    if case.get("interpretations"):
        out["interpretations"] = check_interpretations(case)
    reference_ok = (out.get("reference_validation") or out.get("reference_pending"))["status"] == "PASS"
    reference_ok = reference_ok and out.get("interpretations", {}).get("status", "PASS") == "PASS"
    out.update(correct_session={"status": correct["status"], "auto_flags": correct["dimensions"]["explanation"]["auto_flags"]},
               variants=variants,
               evaluable=(reference_ok and correct["status"] == STRUCTURED_PASS
                          and not correct["dimensions"]["explanation"]["auto_flags"]
                          and all(v["detected"] for v in variants)))
    return out


def dry_run(path: Path = CASES_PATH) -> dict:
    suite = load_cases(path)
    cases = [check_case(case) for case in suite["cases"]]
    pins = {rel: _sha((ROOT / rel).read_bytes()) == digest for rel, digest in suite["pinned_sources"].items()}
    return {"status": "PLAN_READY" if all(c["evaluable"] for c in cases) and all(pins.values()) else "NOT_READY",
            "label": TEST_DOUBLE, "inference_executed": False, "provider_called": False,
            "cases_file_sha256": _sha(Path(path).read_bytes()),
            "module_sha256": _sha(Path(__file__).read_bytes()),
            "pinned_sources_unchanged": pins,
            "per_category": dict(Counter(c["category"] for c in cases)),
            "cases": cases}


# --- real turns (after an authorized capture) ---------------------------------------------------------

def accept_turn(case_id: str, usage_file: Path, *, hermes_bin: Path | None = None, check_store: bool = False,
                runner=subprocess.run, path: Path = CASES_PATH) -> dict:
    """The turn of ``usage_file`` exported with Hermes' local CLI (read-only) and accepted in memory."""
    from tools.mission_report_query import DEFAULT_HERMES_BIN, QueryError, export_session, session_id_from_usage
    suite = load_cases(path)
    case = case_by_id(suite, case_id)
    provenance = {"cases_file_sha256": _sha(Path(path).read_bytes()), "module_sha256": _sha(Path(__file__).read_bytes()),
                  "usage_file": str(usage_file)}
    try:
        session = export_session(session_id_from_usage(usage_file), hermes_bin=hermes_bin or DEFAULT_HERMES_BIN,
                                 runner=runner)
    except (QueryError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"case_id": case_id, "category": case["category"], "status": "TECHNICAL_FAILURE",
                "dimensions": {"technical": {"status": "TECHNICAL_FAILURE",
                                             "reasons": ["TURN_DATA_UNAVAILABLE", type(exc).__name__]}},
                "provenance": provenance}
    result = accept_session(session, case, drafts_root=planning.DRAFT_ROOT if check_store else None)
    return {**result, "provenance": provenance}


def report(acceptances: list[dict]) -> dict:
    """Counts per category and per case with their denominators; never pooled into a global rate."""
    by_category, by_case = defaultdict(list), defaultdict(list)
    for item in acceptances:
        by_category[item["category"]].append(item)
        by_case[item["case_id"]].append(item["status"])
    categories = {}
    for category, items in sorted(by_category.items()):
        evaluated = [i for i in items if i["status"] != "TECHNICAL_FAILURE"]
        dimension = {d: f"{sum(i['dimensions'][d]['status'] in ('PASS', 'NOT_APPLICABLE') for i in evaluated)}"
                        f"/{len(evaluated)}" for d in ("tool_calls", "interpretation", "validation")}
        categories[category] = {"attempts": len(items),
                                "technical_failures": len(items) - len(evaluated),
                                "structured_pass": f"{sum(i['status'] == STRUCTURED_PASS for i in evaluated)}/{len(evaluated)}",
                                "dimensions_pass_or_na": dimension,
                                "explanations_pending_review": len(evaluated),
                                "explanation_auto_flags": sum(bool(i["dimensions"]["explanation"]["auto_flags"])
                                                              for i in evaluated)}
    return {"label": "Pilot counts: describe these 12 prompts and this configuration only; not a general rate",
            "per_category": categories,
            "per_case_repetitions": {case: dict(Counter(statuses)) for case, statuses in sorted(by_case.items())}}


def main(argv=None, *, out=None, runner=subprocess.run) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(description="Hermes planning pilot v1 (no inference)")
    sub = parser.add_subparsers(dest="command", required=True)
    dry = sub.add_parser("dry-run", help="reference drafts through the real backend + comparator checks (doubles)")
    dry.add_argument("--out", type=Path, default=None)
    accept = sub.add_parser("accept", help="accept one captured turn of a pilot case")
    accept.add_argument("--case", required=True)
    accept.add_argument("--usage-file", type=Path, required=True)
    accept.add_argument("--hermes-bin", type=Path, default=None)
    accept.add_argument("--check-store", action="store_true", help="also compare the drafts store")
    rep = sub.add_parser("report", help="per-category counts of saved acceptance files")
    rep.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args(argv)
    if args.command == "dry-run":
        result = dry_run()
        if args.out:
            args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        code = 0 if result["status"] == "PLAN_READY" else 3
    elif args.command == "accept":
        result = accept_turn(args.case, args.usage_file, hermes_bin=args.hermes_bin, check_store=args.check_store,
                             runner=runner)
        code = 0 if result["status"] == STRUCTURED_PASS else 3
    else:
        result = report([json.loads(p.read_text(encoding="utf-8")) for p in args.files])
        code = 0
    json.dump(result, out, indent=2, ensure_ascii=False)
    out.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
