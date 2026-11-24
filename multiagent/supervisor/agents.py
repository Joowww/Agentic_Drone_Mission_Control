"""Specialised agents the supervisor delegates to, and the sector decomposition.

DroneAgent (one per ArduCopter: DroneAgent_drone_01, DroneAgent_drone_02): evaluates ONE sector for ITS drone with
the existing Drone Agent code (multiagent.drone_agent.plan_aerial restricted to that drone): site rules, altitude,
distance, speed, battery against the declared consumption model, wind against the declared limit, and the strict
ArduCopter .plan (TAKEOFF, waypoints, return + LAND). It returns a proposal or a structured refusal.

RoverAgent (one per ArduRover): plans the multi-point ground route (multiagent.supervisor.rover_route), never with
aerial commands.

Sectors: the parcel's DECLARED survey points are split into k contiguous groups along the site x axis (then y), with
balanced sizes. Deterministic; it never adds a point.
"""
from __future__ import annotations

from multiagent.contracts import AerialObjective
from multiagent.drone_agent import plan_aerial
from multiagent.integrated_mission import pinned_allocator
from multiagent.supervisor.rover_route import plan_rover_route


def split_sectors(site, points: list[str], k: int) -> list[dict]:
    if k < 1:
        raise ValueError("at least one sector")
    ordered = sorted(points, key=lambda p: (site.point(p).x_m, site.point(p).y_m, p))
    sectors, start = [], 0
    for i in range(k):
        size = len(ordered) // k + (1 if i < len(ordered) % k else 0)
        sectors.append({"sector_id": f"SECTOR_{chr(ord('A') + i)}", "points": ordered[start:start + size]})
        start += size
    return [s for s in sectors if s["points"]]


def _objectives(points: list[str]) -> list[AerialObjective]:
    return [AerialObjective(objective_id=f"A_{p}", point_id=p) for p in points]


class DroneAgent:
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.name = f"DroneAgent_{vehicle_id}"

    def propose(self, sector: dict, *, context, site, fleet, wind_speed_kmh: float, battery_percent: dict,
                altitude_m: float | None, tracer=None) -> dict:
        """One sector for this drone only. Returns {agent, vehicle_id, sector_id, status, proposal | reasons}."""
        objectives = _objectives(sector["points"])
        allocator = pinned_allocator({self.vehicle_id: [o.objective_id for o in objectives]})
        battery = {k: v for k, v in battery_percent.items() if k == self.vehicle_id}
        result, artifacts = plan_aerial(objectives, context=context, site=site, fleet=fleet,
                                        wind_speed_kmh=wind_speed_kmh, battery_percent=battery, altitude_m=altitude_m,
                                        requested_drones=[self.vehicle_id], tracer=None, allocator=allocator)
        d = result.dump()
        proposal = next((p for p in d["proposals"] if p["vehicle_id"] == self.vehicle_id), None)
        covered = set(proposal["objective_ids"]) if proposal else set()
        ok = proposal is not None and covered == {o.objective_id for o in objectives} and \
            proposal["deterministic_validation"]["mission_status"] == "FEASIBLE"
        reasons = [r for i in d["incompatible"] for r in i["reasons"]] + list(d["clarifications"])
        check = (d["evidence"].get("model_proposal_check") or {})
        reasons += [str(v) for v in check.get("violations") or []]
        out = {"agent": self.name, "vehicle_id": self.vehicle_id, "sector_id": sector["sector_id"],
               "points": list(sector["points"]), "status": "FEASIBLE" if ok else "INFEASIBLE",
               "reasons": [] if ok else (reasons or ["NO_FEASIBLE_ROUTE"]),
               "flight_minutes": proposal["flight_minutes"] if proposal else None,
               "length_m": proposal["length_m"] if proposal else None,
               "mission_sha256": proposal["mission_sha256"] if proposal else None,
               "checks": proposal["deterministic_validation"] if proposal else None}
        if tracer is not None:
            tracer.validation(self.name, f"sector:{sector['sector_id']}", out["status"],
                              {"points": sector["points"], "reasons": out["reasons"][:5],
                               "flight_minutes": out["flight_minutes"]})
        return out


class RoverAgent:
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id
        self.name = f"RoverAgent_{vehicle_id}"

    def propose(self, points: list[str], *, context, site, fleet, limits, return_to_start: bool,
                ordering: str = "AS_GIVEN", tracer=None) -> dict:
        route = plan_rover_route(site=site, fleet=fleet, context=context, limits=limits, rover_id=self.vehicle_id,
                                 points=points, return_to_start=return_to_start, ordering=ordering, tracer=tracer)
        route["agent"] = self.name
        if tracer is not None:
            tracer.validation(self.name, f"ground_route:{ordering}", route["status"],
                              {"sequence": route.get("point_sequence"), "length_m": route.get("length_m"),
                               "findings": route["findings"][:5]})
        return route


def joint_aerial_plan(assignment: dict[str, list[str]], *, context, site, fleet, wind_speed_kmh: float,
                      battery_percent: dict, altitude_m: float | None, tracer=None):
    """The supervisor's joint check of the accepted sector assignment: same plan_aerial, all drones together, so
    the existing deconfliction (start delays / alternatives) applies. Returns (dumped result, artifacts, objectives)."""
    objectives = [o for points in assignment.values() for o in _objectives(points)]
    allocator = pinned_allocator({v: [f"A_{p}" for p in pts] for v, pts in assignment.items()})
    result, artifacts = plan_aerial(objectives, context=context, site=site, fleet=fleet, wind_speed_kmh=wind_speed_kmh,
                                    battery_percent=battery_percent, altitude_m=altitude_m,
                                    requested_drones=sorted(assignment), tracer=tracer, allocator=allocator)
    return result.dump(), artifacts, objectives
