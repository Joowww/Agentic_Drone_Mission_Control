"""Executor adapters of the supervisor. The supervisor never arms, uploads or moves anything: it hands an approved,
gated plan to an adapter, and an adapter either PREPARES a request for an existing protected entry or (offline only)
runs a labelled test double. Observations come back as tfg.multiagent.vehicle-observation/1.

Adapters:
  OfflineTestDouble        OFFLINE_TEST only. Scripted outcome per vehicle; data_kind TEST_DOUBLE; no measurements.
  DroneH2RequestAdapter    ArduCopter. Reuses multiagent.hermes_mission_adapter.adapt_proposal (Hermes validation,
                           strict .plan, SITL binding) and multiagent.drone_execution_bridge.request_execution (the
                           side-effect-free boundary tools/multiagent_drone_sequence.py in a separate process). The
                           result is at most READY_TO_REQUEST_EXECUTION with the exact protected call the operator
                           makes (tools.preflight_sequences.start_preflight_sequence / virtual_preflight). That path
                           is the one that flew H2 (24/10/2026): GUIDED, ARM, TAKEOFF, waypoints, return, LAND.
  RoverPlanAdapter         ArduRover. No executor accepts a multi-waypoint .plan today: the request is prepared in
                           the contract ROVER_PLAN_EXECUTOR_CONTRACT below and the vehicle stays BLOCKED with
                           EXECUTOR_NOT_AVAILABLE. A ONE-goal route (no return) is ALSO mapped to the existing
                           single-goal rover request (multiagent.rover_executor_bridge, GUIDED one-goal controller),
                           which is PENDING_CONTROLLER. A single-goal GUIDED trial never stands for a .plan mission.

Observations from real runs: ``observe_preflight_report`` reads a protected-entry report (schema 1.1, as written by
the virtual preflight graph) and binds it to the approved mission bytes (mission_sha256), or refuses it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

OBSERVATION_SCHEMA = "tfg.multiagent.vehicle-observation/1"
EXECUTED_STATES = ("COMPLETED", "FAILED", "ABORTED", "TIMEOUT")

ROVER_PLAN_EXECUTOR_CONTRACT = {
    "schema": "tfg.rover.plan-mission-execution/1",
    "status": "SPECIFIED_BY_ROVER_CONTROLLER_NO_HANDLER",
    "fields_and_admission": "multiagent/supervisor/rover_contract.py (build_request, check_request)",
    "executor_obligations": [
        "re-check plan sha256, identity, limits, frame evidence and every authority reference at admission",
        "upload with the MAVLink mission protocol, read back, compare item by item; reject aerial or skipped items",
        "run through the existing safe core/ARM/stop path (never a second MAVLink or arming path)",
        "write safeflight.sitl-result v1 with original/executed hashes, per-waypoint evidence, stop/disarm",
        "return tfg.multiagent.vehicle-observation/1 with data_kind REAL_SITL and evidence paths/hashes"],
    "distinct_from": "the one-metre GUIDED trial: one bounded motion, not a waypoint mission",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def observation(vehicle_id: str, task_id: str, *, data_kind: str, status: str, plan_sha256: str | None,
                executed_artifact_sha256: str | None = None, transformed: bool = False, transformations=None,
                started_at=None, finished_at=None, criteria=None, metrics=None, evidence=None, failure_reason=None,
                executor: str, request=None) -> dict:
    return {"schema": OBSERVATION_SCHEMA, "vehicle_id": vehicle_id, "task_id": task_id, "data_kind": data_kind,
            "executor": executor, "execution_status": status, "plan_sha256": plan_sha256,
            "executed_artifact_sha256": executed_artifact_sha256, "transformed": transformed,
            "transformations": transformations or [], "started_at": started_at, "finished_at": finished_at,
            "criteria": criteria or [], "metrics": metrics or {}, "evidence": evidence or [],
            "failure_reason": failure_reason, "request": request,
            "physical_effect": data_kind == "REAL_SITL" and status in EXECUTED_STATES}


class OfflineTestDouble:
    """Scripted executor for offline flows. ``outcomes``: {vehicle_id: COMPLETED | FAILED | ABORTED | TIMEOUT}."""
    kind = "OFFLINE_TEST_DOUBLE"
    modes = ("OFFLINE_TEST",)

    def __init__(self, outcomes: dict[str, str] | None = None, default: str = "COMPLETED"):
        self.outcomes, self.default, self.calls = dict(outcomes or {}), default, []

    def execute(self, vehicle: dict, *, plan_bytes: bytes, plan_sha256: str, mode: str, **_):
        if mode not in self.modes:
            raise PermissionError("the test double is never used outside OFFLINE_TEST")
        self.calls.append(vehicle["vehicle_id"])
        status = self.outcomes.get(vehicle["vehicle_id"], self.default)
        items = json.loads(plan_bytes)["mission"]["items"]
        nav = sum(1 for i in items if i["command"] == 16)
        reached = nav if status == "COMPLETED" else max(nav - 1, 0)
        started = now_utc()
        return observation(
            vehicle["vehicle_id"], vehicle["task_id"], data_kind="TEST_DOUBLE", status=status, plan_sha256=plan_sha256,
            executed_artifact_sha256=plan_sha256, started_at=started, finished_at=now_utc(),
            criteria=[{"id": "mission_readback_match", "result": "pass", "description": "TEST DOUBLE: not a readback"},
                      {"id": "all_waypoints_reached", "result": "pass" if status == "COMPLETED" else "fail",
                       "measured": reached, "threshold": nav, "unit": "wp"},
                      {"id": "mission_end_reached", "result": "pass" if status == "COMPLETED" else "fail"}],
            failure_reason=None if status == "COMPLETED" else f"TEST_DOUBLE scripted outcome {status}",
            executor=self.kind)


class DroneH2RequestAdapter:
    """Prepares the H2 protected request for the approved drones (one or two). Never submits it."""
    kind = "ARDUCOPTER_H2_GUIDED_REQUEST"
    modes = ("OFFLINE_TEST", "OPERATIONAL")

    def prepare(self, drones: list[dict], *, orchestrator_proposal: dict, context, site, fleet, request_dir: Path,
                request_key: str, statement: str, mode: str) -> dict:
        from multiagent.drone_execution_bridge import request_execution
        from multiagent.hermes_mission_adapter import adapt_proposal
        wanted = {d["vehicle_id"] for d in drones}
        proposal = json.loads(json.dumps(orchestrator_proposal))
        proposal["aerial"]["proposals"] = [p for p in proposal["aerial"]["proposals"] if p["vehicle_id"] in wanted]
        if len(proposal["aerial"]["proposals"]) == 1:  # a single drone flies alone: no start offset to keep
            proposal["swarm_coordination"] = None
        adapted = adapt_proposal(proposal, context=context, site=site, fleet=fleet,
                                 source={"kind": "SUPERVISOR_MANIFEST", "mission_id": proposal["mission_id"]})
        out = {"adapter": self.kind, "adapted_status": adapted["status"],
               "findings": adapted["findings"], "drones": {}}
        for rec in adapted["drones"]:
            out["drones"][rec["vehicle_id"]] = {"mission_sha256": rec.get("mission_sha256"),
                                                "hermes_validation": rec.get("hermes_validation"),
                                                "sitl_binding": rec.get("sitl_binding"), "state": rec["state"]}
        if adapted["status"] != "PLANNING_VALID":
            out["status"] = "REJECTED"
            return out
        req = request_execution(adapted, mission_dir=Path(request_dir), request_key=request_key, mode=mode,
                                authorization_statement=statement)
        out.update(status=req.get("status"), boundary=req, submitted=False)
        return out


def observe_preflight_report(report_path: Path, *, vehicle_id: str, task_id: str, approved_mission_sha256: str,
                             plan_sha256: str) -> dict:
    """A protected-entry preflight report (schema 1.1) -> REAL_SITL observation, bound to the approved mission bytes.
    The executor ran the MissionDefinition in GUIDED: the .plan was NOT uploaded, so the result is ``transformed``."""
    data = Path(report_path).read_bytes()
    report = json.loads(data)
    import hashlib
    report_sha = hashlib.sha256(data).hexdigest()
    problems = []
    if report.get("mission_sha256") != approved_mission_sha256:
        problems.append("EVIDENCE_NOT_FOR_THIS_PLAN: report mission_sha256 differs from the approved mission")
    if (report.get("vehicle_selection") or {}).get("vehicle_id") != vehicle_id:
        problems.append("EVIDENCE_VEHICLE_MISMATCH")
    if problems:
        return observation(vehicle_id, task_id, data_kind="REJECTED_EVIDENCE", status="NOT_EXECUTED",
                           plan_sha256=plan_sha256, failure_reason="; ".join(problems),
                           executor="tools.virtual_preflight (report)")
    ex, analysis = report.get("executor_result") or {}, report.get("analysis") or {}
    checks = analysis.get("checks") or {}
    expected = len(analysis.get("expected_waypoint_ids") or [])
    observed = len(analysis.get("observed_waypoint_ids") or [])
    status = "COMPLETED" if report.get("status") == "PASSED" and ex.get("status") == "COMPLETED" else \
        ("ABORTED" if ex.get("status") in ("ABORTED", "CANCELLED") else "FAILED")
    criteria = [
        {"id": "mission_readback_match", "result": "not_evaluated",
         "description": "GUIDED executor: no MAVLink mission upload, nothing to read back"},
        {"id": "all_waypoints_reached", "result": "pass" if checks.get("all_waypoints_reached") else "fail",
         "measured": observed, "threshold": expected, "unit": "wp"},
        {"id": "mission_end_reached", "result": "pass" if checks.get("landed_and_disarmed") and
         checks.get("return_home_reached") else "fail", "description": "returned, landed and disarmed"},
        {"id": "no_failsafe", "result": "pass" if checks.get("no_failure_or_recovery") else "fail"}]
    metrics = {}
    try:
        t0 = datetime.fromisoformat(report["execution_started_at"])
        t1 = datetime.fromisoformat(report["execution_finished_at"])
        metrics["duration_s"] = {"value": round((t1 - t0).total_seconds(), 3), "unit": "s"}
    except (KeyError, TypeError, ValueError):
        pass
    tol = analysis.get("tolerances") or {}
    if tol:
        metrics["acceptance_tolerance_horizontal_m"] = {"value": tol.get("horizontal_m"), "unit": "m"}
    iso = lambda v: v.replace("+00:00", "Z") if isinstance(v, str) else v  # noqa: E731
    return observation(
        vehicle_id, task_id, data_kind="REAL_SITL", status=status, plan_sha256=plan_sha256,
        executed_artifact_sha256=approved_mission_sha256, transformed=True,
        transformations=[{"kind": "guided_mission_execution",
                          "description": "the executor flew the MissionDefinition bound to this .plan by mission_sha256 "
                                         "in GUIDED; the .plan itself was not uploaded"}],
        started_at=iso(report.get("execution_started_at")), finished_at=iso(report.get("execution_finished_at")),
        criteria=criteria, metrics={k: v for k, v in metrics.items() if v.get("value") is not None},
        evidence=[{"source_path": str(report_path), "kind": "executor_log", "sha256": report_sha,
                   "description": "protected-entry preflight report (schema 1.1)"}],
        failure_reason=None if status == "COMPLETED" else "; ".join(analysis.get("reasons") or ["executor did not pass"]),
        executor="tools.virtual_preflight (report)")


class RoverPlanAdapter:
    kind = "ARDUROVER_PLAN_MISSION"
    modes = ("OFFLINE_TEST", "OPERATIONAL")

    def prepare(self, vehicle: dict, *, ground: dict, site, plan_bytes: bytes, plan_sha256: str, manifest: dict,
                approval: dict, session_id: str, plan_path: Path | None = None) -> dict:
        from multiagent.supervisor import rover_contract as rc
        request = rc.build_request(vehicle=vehicle, plan_path=vehicle["plan"]["path"], plan_bytes=plan_bytes,
                                   ground=ground, manifest=manifest)
        request["supervisor_context"]["approval_id"] = (approval or {}).get("approval_id")
        request["supervisor_context"]["session_id"] = session_id
        admission = rc.check_request(request, plan_bytes, plan_path=plan_path)
        out = {"adapter": self.kind, "status": "BLOCKED", "submitted": False,
               "reasons": ["EXECUTOR_NOT_AVAILABLE: no handler accepts tfg.rover.plan-mission-execution/1 yet "
                           "(EXECUTE_PLAN_MISSION_SITL is NOT_IMPLEMENTED)"] + admission["formal"] + admission["pending"],
               "plan_request": request, "admission_check": admission, "contract": ROVER_PLAN_EXECUTOR_CONTRACT}
        seq = ground.get("point_sequence") or []
        if len(seq) == 1 and not ground.get("return_to_start"):
            from multiagent import rover_executor_bridge as rb
            task = {"task_id": vehicle["task_id"], "vehicle_id": vehicle["vehicle_id"], "target_point": seq[0],
                    "start_point": ground.get("start_point")}
            out["single_goal_request"] = rb.execution_request(
                task, site, proposal={"proposal_sha256": manifest["manifest_sha256"]},
                dependencies=request["supervisor_context"]["dependencies"],
                human_limits={"max_speed_mps": ground.get("speed_limit_mps"), "timeout_s": ground.get("timeout_s")})
            out["single_goal_status"] = "PENDING_CONTROLLER: EXECUTE_GUIDED_SINGLE_GOAL_SITL not demonstrated"
        else:
            out["single_goal_status"] = (f"NOT_APPLICABLE: {len(seq)} waypoint(s)"
                                         + (" + return" if ground.get("return_to_start") else "")
                                         + "; the one-goal GUIDED controller takes exactly one goal")
        return out
