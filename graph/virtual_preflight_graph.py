"""One rehearsal, no automatic mutation/retry and no dependency from the gate.

Every terminal path reaches report. Unexpected infrastructure exceptions become
ERROR; deterministic rejection becomes BLOCKED. The executor retains its gate
and its existing recovery behavior.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import math
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from graph.virtual_preflight_state import VirtualPreflightState
from inputs.json_loader import load_mission_json
from reporting.virtual_preflight_analysis import analyze_executor_result
from tools.hermes_mission_validation import validate_mission_file
from tools.simulation_mission_executor import (
    _execution_compatibility_errors,
    execute_approved_mission,
)
from tools.simulation_status import check_simulation_ready


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_evidence(value):
    # Non-finite floats cannot occur in standard JSON. Preserve their identity
    # as a tagged value if a malformed executor result contains one.
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite_float": repr(value)}
    if isinstance(value, dict):
        return {key: _json_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_evidence(item) for item in value]
    return value


def make_report(state: VirtualPreflightState) -> dict:
    return _json_evidence({
        "schema_version": "1.0",
        "report_persisted": True,
        **{key: value for key, value in state.items() if key not in {"mission", "report"}},
        "scope": "Gazebo/ArduPilot SITL, simulated v1 only",
        "hardware_authorized": False,
        "subsequent_execution_authorized": False,
        "replan_proposals": (state.get("validation") or {}).get("replan_actions", []),
    })


def persist_report(state: VirtualPreflightState) -> dict:
    report = make_report(state)
    path = Path(state["report_path"])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
    return report


def step(name):
    """Record transitions and route unexpected failures to the report node."""
    def decorate(fn):
        @wraps(fn)
        def run(state):
            started = utc_now()
            try:
                if state.get("persist_progress"):
                    persist_report({**state, "stage": name})
                update = fn(state)
            except Exception as exc:
                update = {"status": "ERROR", "reasons": [f"{name}: {type(exc).__name__}: {exc}"]}
            return {
                **update, "stage": name,
                "transitions": [*state.get("transitions", []), {
                    "node": name, "started_at": started, "finished_at": utc_now(),
                    "status": update.get("status", state["status"]),
                }],
            }
        return run
    return decorate


@step("snapshot")
def snapshot_node(state: VirtualPreflightState) -> dict:
    content = Path(state["source_path"]).read_bytes()
    snapshot = Path(state["snapshot_path"])
    snapshot.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    if state.get("expected_sha256") and digest != state["expected_sha256"]:
        return {"mission_sha256": digest, "status": "ERROR",
                "reasons": ["Admission snapshot hash changed; execution refused."]}
    try:
        mission = load_mission_json(str(snapshot))
    except ValueError as exc:
        return {"mission_sha256": digest, "status": "BLOCKED",
                "reasons": [f"Invalid mission: {exc}"]}
    return {
        "mission_sha256": digest, "mission": mission,
        "mission_identity": {"mission_id": mission.mission_id, "name": mission.name,
                             "vehicle_id": mission.vehicle.vehicle_id, "simulated_vehicle": "v1"},
    }


@step("validate")
def validate_node(state: VirtualPreflightState) -> dict:
    validation = validate_mission_file(state["snapshot_path"])
    if (validation.get("mission_status") != "FEASIBLE"
            or validation.get("execution_status") != "APPROVED" or validation.get("errors")):
        return {"validation": validation, "status": "BLOCKED", "reasons": [
            "Deterministic validation did not approve the mission.",
            *validation.get("failure_reasons", []), *validation.get("errors", []),
        ]}
    return {"validation": validation}


@step("check_readiness")
def readiness_node(state: VirtualPreflightState) -> dict:
    readiness = check_simulation_ready()
    if readiness.get("ready") is not True:
        return {"readiness": readiness, "status": "BLOCKED", "reasons": [
            "Simulation is not ready; no automatic start or restart.",
            str(readiness.get("message", "No readiness evidence.")),
        ]}
    return {"readiness": readiness}


@step("compatibility")
def compatibility_node(state: VirtualPreflightState) -> dict:
    mission = state["mission"]
    errors = _execution_compatibility_errors(mission)
    # The mapper requires home, although the executor's compatibility helper
    # currently leaves this check to the mapper (before arming).
    if mission.route.home is None:
        errors.append("Simulation mapping requires a mission home.")
    if errors:
        return {"compatibility_errors": errors, "status": "BLOCKED", "reasons": errors}
    return {"compatibility_errors": []}


def _snapshot_matches(state: VirtualPreflightState) -> bool:
    return hashlib.sha256(Path(state["snapshot_path"]).read_bytes()).hexdigest() == state["mission_sha256"]


@step("execute")
def execute_node(state: VirtualPreflightState) -> dict:
    if not _snapshot_matches(state):
        return {"status": "ERROR", "reasons": ["Mission snapshot changed before execution."]}
    execution = {"execution_attempted": True, "execution_started_at": utc_now()}
    # Persist intent before calling a potentially long-running executor. If the
    # process dies, RUNNING is evidence of an unfinished run, never PASSED.
    persist_report({**state, **execution, "stage": "execute"})
    try:
        raw = execute_approved_mission(state["snapshot_path"], vehicle="v1", progress=False)
    except Exception as exc:
        return {**execution, "execution_finished_at": utc_now(), "status": "ERROR",
                "reasons": [f"Executor raised {type(exc).__name__}: {exc}; outcome unknown."]}
    return {**execution, "execution_finished_at": utc_now(), "executor_result": raw}


@step("analyze")
def analyze_node(state: VirtualPreflightState) -> dict:
    raw = state.get("executor_result")
    analysis = analyze_executor_result(state["mission"], raw)
    if not _snapshot_matches(state):
        return {"analysis": analysis, "status": "ERROR",
                "reasons": ["Mission snapshot changed during execution; hash association is invalid."]}
    # An internal recheck can reject a mission between outer readiness and flight.
    # Preserve that as BLOCKED only if there is no indication of flight/recovery.
    if (isinstance(raw, dict) and raw.get("status") == "BLOCKED"
            and raw.get("success") is False and not raw.get("events") and not raw.get("recovery")
            and raw.get("stage") in {"EXECUTION_GATE", "EXECUTION_COMPATIBILITY", "VEHICLE_EXCLUSION"}):
        return {"analysis": analysis, "status": "BLOCKED", "reasons": [
            str(raw.get("message", "Executor internal gate or compatibility check blocked execution.")),
            *raw.get("errors", []),
        ]}
    return {"analysis": analysis, "status": "PASSED" if analysis["passed"] else "FAILED",
            "reasons": analysis["reasons"]}


def report_node(state: VirtualPreflightState) -> dict:
    finished = utc_now()
    final = {**state, "finished_at": finished, "transitions": [*state.get("transitions", []), {
        "node": "write_report", "started_at": finished, "finished_at": finished, "status": state["status"],
    }]}
    try:
        report = persist_report(final)
    except Exception as exc:
        final.update(status="ERROR", reasons=[*state.get("reasons", []), f"Cannot persist report: {exc}"])
        final["transitions"][-1]["status"] = "ERROR"
        report = make_report(final)
        report["report_persisted"] = False
    return {"status": final["status"], "finished_at": finished,
            "transitions": final["transitions"], "report": report}


def route_next(state: VirtualPreflightState) -> str:
    return "write_report" if state["status"] in {"BLOCKED", "ERROR"} else "continue"


builder = StateGraph(VirtualPreflightState)
for name, node in (
    ("snapshot", snapshot_node), ("validate", validate_node),
    ("check_readiness", readiness_node), ("compatibility", compatibility_node),
    ("execute", execute_node), ("analyze", analyze_node), ("write_report", report_node),
):
    builder.add_node(name, node)
builder.add_edge(START, "snapshot")
for current, following in (
    ("snapshot", "validate"), ("validate", "check_readiness"),
    ("check_readiness", "compatibility"), ("compatibility", "execute"), ("execute", "analyze"),
):
    builder.add_conditional_edges(current, route_next, {"write_report": "write_report", "continue": following})
builder.add_edge("analyze", "write_report")
builder.add_edge("write_report", END)
virtual_preflight_graph = builder.compile()
