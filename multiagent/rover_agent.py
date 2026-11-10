"""Rover Agent: ground objectives -> ground task proposals pending authorization. No ROS 2, no command.

Checks (deterministic, offline): the target resolves to a declared site POI; the rover is in the fleet as a rover
and in the context with a DECLARED availability; the straight line from its declared start point stays in the
drivable area, clear of exclusions (planning.site_validation.validate_ground_route); one task per rover (the
existing coordination contract). The proposal is the existing scenario-template GroundTask shape.

What it never does: import or call the rover controller, read reservations or locks, transform the site frame into
the rover's odometry frame (not accredited), or authorize anything. Execution stays with the R1 coordinator
(tools.agri_ground_coordinator), the operator authorization and the executor's own gates.
"""
from __future__ import annotations

from multiagent.contracts import AgentResult, GroundObjective, OperatingContext
from multiagent.site_points import resolve_point
from planning.site_validation import validate_ground_route

AGENT = "rover_agent"


def plan_ground(objectives: list[GroundObjective], *, context: OperatingContext, site, fleet, rover_id: str | None,
                tracer=None) -> AgentResult:
    proposals, incompatible, clarifications = [], [], []
    if not objectives:
        return AgentResult(agent=AGENT, status="NO_TASKS")
    profile = next((r for r in context.rovers if r.vehicle_id == rover_id), None) if rover_id else \
        (context.rovers[0] if context.rovers else None)
    vehicle = fleet.vehicle(profile.vehicle_id) if profile else None
    blocking = []
    if profile is None:
        blocking.append(f"ROVER_NOT_DECLARED: {rover_id or '(none in context)'}")
    elif vehicle is None or vehicle.category != "rover":
        blocking.append(f"NOT_A_FLEET_ROVER: {profile.vehicle_id}")
    elif not profile.available:
        blocking.append(f"NOT_AVAILABLE: {profile.vehicle_id} declared unavailable")
    for index, objective in enumerate(objectives):
        point, reasons = resolve_point(site, point_id=objective.point_id, coordinates=objective.coordinates, kind="poi",
                                       tolerance_m=context.coordinate_match_tolerance_m)
        if reasons:
            clarifications.extend(f"{objective.objective_id}: {r}" for r in reasons)
            continue
        if blocking:
            incompatible.append({"objective_id": objective.objective_id, "reasons": blocking})
            continue
        if proposals:
            incompatible.append({"objective_id": objective.objective_id, "reasons": [
                f"ONE_TASK_PER_VEHICLE: {profile.vehicle_id} already has {proposals[0]['task_id']} "
                "(planning.scenario_instance.coordination_checks)"]})
            continue
        spatial = validate_ground_route(site, profile.start_point, point, context.planning_margin_m, vehicle)
        if tracer is not None:
            tracer.validation(AGENT, f"ground_route:{profile.vehicle_id}->{point}", spatial["status"],
                              [c for c in spatial.get("checks", []) if c["status"] != "PASS"])
        if spatial["status"] != "PASS":
            incompatible.append({"objective_id": objective.objective_id, "reasons": [
                f"{c['check']}: {c['detail']}" for c in spatial["checks"] if c["status"] == "FAIL"] or ["ROUTE_REJECTED"]})
            continue
        proposals.append({"task_id": f"GROUND_{profile.vehicle_id}", "vehicle_id": profile.vehicle_id,
                          "objective_ids": [objective.objective_id], "kind": "VISIT_AND_STOP",
                          "start_point": profile.start_point, "target_point": point,
                          "after_aerial_point": point if objective.after_aerial else None,
                          "spatial_status": spatial["status"], "availability": "DECLARED_" + profile.provenance,
                          "frame_transform_to_rover": "NOT_ACCREDITED (site frame -> rover odometry)",
                          "export": "FORMAT_PENDING: no rover exporter",
                          "execution": "NOT_EXECUTED: R1 coordinator + operator authorization + executor gates",
                          "ros2_commands_sent": 0, "state": "PENDING_AUTHORIZATION"})
    if clarifications and not proposals:
        status = "NEEDS_CLARIFICATION"
    elif not proposals:
        status = "INFEASIBLE"
    elif incompatible or clarifications:
        status = "PARTIAL_PENDING_AUTHORIZATION"
    else:
        status = "PROPOSED_PENDING_AUTHORIZATION"
    return AgentResult(agent=AGENT, status=status, proposals=proposals, incompatible=incompatible,
                       clarifications=clarifications,
                       evidence={"rover": profile.vehicle_id if profile else None,
                                 "availability_basis": "declared in the operating context; not a readiness check"})
