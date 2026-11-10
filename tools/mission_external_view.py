"""Reduced, allow-listed projection of get_mission_state for external LLM providers.

Built only from the already-checked summary response (whose reached waypoints and LANDED
evidence the project derives from the recorded events); never reads files or changes reports.
Every field has an explicit type. A value that is absent stays null ("not recorded"), never
inferred; a value of the wrong type, or a string that could carry a path, a log line or free
text, is dropped to null and its field name listed in ``rejected_fields``. Absolute paths,
worker pid/start_ticks/boot_id, request keys, reasons, messages, readiness output, error texts
and raw event payloads are never copied.

Schema 2 (2026-10-23) groups each preflight so that kinds of evidence cannot be confused:
``executor_facts`` (what the executor recorded), ``acceptance_criteria`` (pass/fail of the
analysis rules: a false criterion is NOT a recorded fact such as "did not return"), and
``recovery_after_failure`` (a separate landing after a failure, not the mission's own landing).
Schema 1 placed them side by side; the 2026-10-22 17:40 trial showed a model reading
``return_home_reached=false`` as ``return_to_home=false``.
"""
import re

EXTERNAL_SCHEMA_VERSION = 2
_TEXT = re.compile(r"[A-Za-z0-9 _.:+-]{1,160}")  # identifiers, names, ISO times; no '/', no newline

# group -> ((output field, path in one summary preflight view, type), ...)
_GROUPS = {
    "identity": (
        ("run_id", ("run_id",), str),
        ("mission_id", ("report", "mission_identity", "mission_id"), str),
        ("mission_name", ("report", "mission_identity", "name"), str),
        ("vehicle_id", ("vehicle_selection", "vehicle_id"), str),
        ("simulated_vehicle", ("vehicle_selection", "simulated_vehicle"), str),
    ),
    "record": (
        ("result_status", ("result_status",), str),
        ("report_stage", ("report", "stage"), str),
        ("job_state", ("job_state",), str),
        ("execution_attempted", ("report", "execution_attempted"), bool),
        ("started_at", ("report", "started_at"), str),
        ("finished_at", ("report", "finished_at"), str),
        ("snapshot_integrity", ("snapshot_integrity",), str),
        ("worker_alive", ("worker_alive",), bool),
    ),
    "admission_at_run": (
        ("validation_mission_status", ("report", "validation", "mission_status"), str),
        ("validation_execution_status", ("report", "validation", "execution_status"), str),
        ("readiness_ready", ("report", "readiness", "ready"), bool),
        ("readiness_status", ("report", "readiness", "status"), str),
    ),
    "plan": (
        ("planned_waypoint_ids", ("report", "analysis", "expected_waypoint_ids"), list),
    ),
    "executor_facts": (
        ("status", ("report", "executor_result", "status"), str),
        ("success", ("report", "executor_result", "success"), bool),
        ("stage", ("report", "executor_result", "stage"), str),
        ("waypoints_completed", ("report", "executor_result", "waypoints_completed"), int),
        ("return_to_home", ("report", "executor_result", "return_to_home"), bool),
        ("reached_waypoint_ids", ("report", "executor_result", "reached_waypoint_ids"), list),
        ("mission_landing_events", ("report", "executor_result", "landing_evidence"), "landing"),
    ),
    "acceptance_criteria": (
        ("passed", ("report", "analysis", "passed"), bool),
        ("checks", ("report", "analysis", "checks"), "checks"),
    ),
    "recovery_after_failure": (
        ("landing_attempted", ("report", "executor_result", "recovery", "landing_attempted"), bool),
        ("landing_completed", ("report", "executor_result", "recovery", "landing_completed"), bool),
        ("landed", ("report", "executor_result", "recovery", "landing", "landed"), bool),
        ("armed", ("report", "executor_result", "recovery", "landing", "armed"), bool),
        ("flying", ("report", "executor_result", "recovery", "landing", "flying"), bool),
    ),
}
OMITTED = ("absolute paths", "worker pid/start_ticks/boot_id", "request_key", "reasons and messages",
           "readiness output", "error texts and error evidence", "event payloads", "recovery final position",
           "links to drafts/artifacts")
SEMANTICS = {
    "null": "not recorded in the historical report; never inferred from other fields",
    "readiness_now": "current availability; this historical query does not check it",
    "executor_facts": "what the executor recorded during that run",
    "executor_facts.mission_landing_events": "the mission's own LANDED events: [] = events recorded but no "
                                             "LANDED event; null = no event log",
    "acceptance_criteria": "pass/fail of the analysis rules for that run; a false criterion is not a recorded "
                           "fact and must not be read as one (e.g. not as return_to_home=false)",
    "recovery_after_failure": "a separate landing performed after a failure; not the mission's own landing",
}


def _get(value, path):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _typed(value, kind):
    """(accepted value, rejected?) for one allow-listed field; None is 'not recorded'."""
    if value is None:
        return None, False
    if kind is bool:
        return (value, False) if isinstance(value, bool) else (None, True)
    if kind is int:
        return (value, False) if isinstance(value, int) and not isinstance(value, bool) else (None, True)
    if kind is str:
        return (value, False) if isinstance(value, str) and _TEXT.fullmatch(value) else (None, True)
    if kind is list:
        ok = isinstance(value, list) and len(value) <= 64 and all(isinstance(v, str) and _TEXT.fullmatch(v) for v in value)
        return (list(value), False) if ok else (None, True)
    if kind == "checks":
        ok = (isinstance(value, dict) and len(value) <= 32
              and all(isinstance(k, str) and _TEXT.fullmatch(k) and isinstance(v, bool) for k, v in value.items()))
        return (dict(value), False) if ok else (None, True)
    if kind == "landing":
        if not isinstance(value, list) or len(value) > 16:
            return None, True
        out = []
        for item in value:
            if not isinstance(item, dict):
                return None, True
            entry = {}
            for key, sub in (("event", str), ("landed", bool), ("armed", bool), ("flying", bool)):
                accepted, rejected = _typed(item.get(key), sub)
                if rejected:
                    return None, True
                entry[key] = accepted
            out.append(entry)
        return out, False
    raise ValueError(kind)


def external_mission_state(summary, anchor):
    """Project a summary ``get_mission_state`` response; ``anchor`` is the caller's identifier set."""
    rejected = []

    def take(name, value, kind):
        accepted, bad = _typed(value, kind)
        if bad:
            rejected.append(name)
        return accepted

    result = {"view": "external", "external_schema_version": EXTERNAL_SCHEMA_VERSION,
              "status": take("status", summary.get("status"), str),
              "queried": {k: v for k, v in anchor.items() if k in ("run_id", "draft_id", "revision_id")
                          and isinstance(v, str) and _TEXT.fullmatch(v)}}
    for key in ("error_code", "readiness_now", "consent"):
        result[key] = take(key, summary.get(key), str)
    result["hardware_authorized"] = take("hardware_authorized", summary.get("hardware_authorized"), bool)
    result["warning_count"] = len(summary.get("warnings") or [])
    preflights = []
    for index, view in enumerate(summary.get("preflights") or []):
        entry = {}
        for group, fields in _GROUPS.items():
            entry[group] = {name: take(f"preflights/{index}/{group}/{name}", _get(view, path), kind)
                            for name, path, kind in fields}
        events = entry["executor_facts"]["mission_landing_events"]
        # A count keeps [] and null distinguishable for scalar checks.
        entry["executor_facts"]["mission_landing_event_count"] = len(events) if events is not None else None
        entry["reason_count"] = len(_get(view, ("report", "reasons")) or [])
        preflights.append(entry)
    result["preflights"] = preflights
    result["other_linked_records"] = {k: len(summary.get(k) or []) for k in ("artifacts", "proposals", "revisions",
                                                                             "linked_drafts")}
    result["rejected_fields"] = rejected
    result["omitted"] = list(OMITTED)
    result["semantics"] = dict(SEMANTICS)
    return result
