"""Synthetic swarm scenarios with 1, 2, 3 and 5 drones, and their comparison (offline, planning only).

    python -m multiagent.scenarios                 # comparison table for 1, 2, 3, 5 drones
    python -m multiagent.scenarios --out DIR       # also writes scalability.json
    python -m multiagent.scenarios --write-fixtures  # regenerates multiagent/fixtures/swarm_*.context.json

Site multiagent/fixtures/swarm_field_v1.site.json (five pads, nine POIs, a full-height tree row and a no-fly pond)
and fleet swarm_fleet_v1.json (drone_01/02 as in the project fleet, drone_03..05 SYNTHETIC placeholders without
export profile: planned, never exported). The drone profiles below differ in autonomy (battery and consumption),
survey speed, sensors, wind limit and availability. Every value is SYNTHETIC.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import statistics
import sys
import time

from models.fleet import Fleet
from models.site import Site

from multiagent.contracts import AerialObjective, OperatingContext, load_context
from multiagent.drone_agent import plan_aerial

FIXTURES = Path(__file__).with_name("fixtures")
SITE = "multiagent/fixtures/swarm_field_v1.site.json"
FLEET = "multiagent/fixtures/swarm_fleet_v1.json"
SIZES = (1, 2, 3, 5)
PROFILES = [
    {"vehicle_id": "drone_01", "takeoff_point": "TAKEOFF_1", "sensors": ["rgb"], "battery_percent": 100.0,
     "consumption_percent_per_minute": 0.8, "cruise_speed_kmh": 35.0, "max_wind_kmh": 30.0, "survey_speed_kmh": 12.0},
    {"vehicle_id": "drone_02", "takeoff_point": "TAKEOFF_2", "sensors": ["multispectral"], "battery_percent": 60.0,
     "consumption_percent_per_minute": 1.2, "cruise_speed_kmh": 30.0, "max_wind_kmh": 20.0, "survey_speed_kmh": 10.0},
    {"vehicle_id": "drone_03", "takeoff_point": "TAKEOFF_3", "sensors": ["rgb", "thermal"], "battery_percent": 21.5,
     "consumption_percent_per_minute": 1.0, "cruise_speed_kmh": 40.0, "max_wind_kmh": 25.0, "survey_speed_kmh": 15.0},
    {"vehicle_id": "drone_04", "takeoff_point": "TAKEOFF_4", "sensors": ["rgb", "multispectral"], "battery_percent": 80.0,
     "consumption_percent_per_minute": 1.5, "cruise_speed_kmh": 25.0, "max_wind_kmh": 15.0, "survey_speed_kmh": 8.0},
    {"vehicle_id": "drone_05", "takeoff_point": "TAKEOFF_5", "sensors": ["thermal"], "battery_percent": 90.0,
     "consumption_percent_per_minute": 0.9, "cruise_speed_kmh": 30.0, "max_wind_kmh": 35.0, "survey_speed_kmh": 10.0,
     "available": False},
]
POLICY = {"min_separation_m": 5.0, "position_uncertainty_m": 1.5, "vehicle_extent_m": 0.5, "timing_uncertainty_s": 3.0,
          "timing_uncertainty_fraction": 0.2, "takeoff_climb_s": 10.0, "landing_s": 15.0, "start_delay_step_s": 5.0,
          "max_start_delay_s": 300.0, "max_mission_duration_s": 900.0, "provenance": "SYNTHETIC"}
# Same as POLICY but a drone may wait at most 20 s and the mission must end within 4 minutes.
TIGHT_POLICY = {**POLICY, "max_start_delay_s": 20.0, "max_mission_duration_s": 240.0}
OBJECTIVES = [("POI_1", "rgb"), ("POI_2", "multispectral"), ("POI_3", "thermal"), ("POI_4", "rgb"), ("POI_5", None),
              ("POI_6", "multispectral"), ("POI_7", None), ("POI_8", None)]


def context_dict(n: int, *, policy: dict | None = POLICY, context_id: str | None = None) -> dict:
    return {"schema": "tfg.multiagent.operating-context/1", "context_id": context_id or f"swarm_{n}_drones_v1",
            "provenance": "SYNTHETIC", "site_path": SITE, "fleet_path": FLEET,
            "drones": [{**p, "provenance": "SYNTHETIC"} for p in PROFILES[:n]],
            "rovers": [{"vehicle_id": "rover_01", "start_point": "ROVER_START", "available": True, "provenance": "SYNTHETIC"}],
            "altitude_m": 5.0, "requested_speed_kmh": 10.0, "minimum_battery_reserve_percent": 20.0,
            "planning_margin_m": 1.0, "wind_speed_kmh": 0.0, "coordinate_match_tolerance_m": 0.5,
            "separation_policy": policy, "export_policy": "SYNTHETIC_PLANNING_ONLY"}


def fixture_contexts() -> dict[str, dict]:
    contexts = {f"swarm_{n}.context.json": context_dict(n) for n in SIZES}
    contexts["swarm_3_tight.context.json"] = context_dict(3, policy=TIGHT_POLICY, context_id="swarm_3_drones_tight_v1")
    contexts["swarm_2_no_policy.context.json"] = context_dict(2, policy=None, context_id="swarm_2_drones_no_policy_v1")
    return contexts


def write_fixtures() -> list[Path]:
    written = []
    for name, value in fixture_contexts().items():
        path = FIXTURES / name
        path.write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")
        written.append(path)
    return written


def _world(context: OperatingContext):
    site = Site.model_validate_json(Path(context.resolve(context.site_path)).read_text(encoding="utf-8"))
    fleet = Fleet.model_validate_json(Path(context.resolve(context.fleet_path)).read_text(encoding="utf-8"))
    return site, fleet


def objectives(points=OBJECTIVES) -> list[AerialObjective]:
    return [AerialObjective(objective_id=f"O{i + 1}", point_id=p, required_sensor=s) for i, (p, s) in enumerate(points)]


def jain(values: list[float]) -> float | None:
    """Jain's fairness index of the load (1 = perfectly even); None without load."""
    values = [v for v in values if v is not None]
    return (sum(values) ** 2) / (len(values) * sum(v * v for v in values)) if values and any(values) else None


def run_scenario(context: OperatingContext, points=OBJECTIVES, *, wind_speed_kmh: float = 0.0) -> dict:
    site, fleet = _world(context)
    started = time.perf_counter()
    with redirect_stdout(io.StringIO()):
        result, _ = plan_aerial(objectives(points), context=context, site=site, fleet=fleet,
                                wind_speed_kmh=wind_speed_kmh, battery_percent={}, altitude_m=None, requested_drones=[])
    elapsed = time.perf_counter() - started
    evidence = result.evidence
    coordination = evidence.get("coordination") or {}
    reference = evidence.get("reference") or {}
    flights = {p["vehicle_id"]: p["flight_minutes"] for p in result.proposals}
    available = [d.vehicle_id for d in context.drones if d.available]
    return {"context": context.context_id, "drones_declared": len(context.drones), "drones_available": len(available),
            "objectives": len(points), "status": result.status,
            "assigned": sorted(o for p in result.proposals for o in p["objective_ids"]),
            "rejected": {i.objective_id: i.reasons[0] for i in result.incompatible},
            "per_drone": {p["vehicle_id"]: {"sequence": p["poi_sequence"], "flight_min": round(p["flight_minutes"], 3),
                                           "start_delay_s": p["start_delay_s"], "export": p["export"]["status"]}
                          for p in result.proposals},
            "flight_sum_min": round(sum(flights.values()), 3),
            "makespan_s": coordination.get("makespan_s") or (round(max(flights.values()) * 60, 2) if flights else 0.0),
            "load_jain_used": jain(list(flights.values())),
            "load_jain_available": jain([flights.get(v, 0.0) for v in available]),
            "coverage_ratio": len({o for p in result.proposals for o in p["objective_ids"]}) / len(points),
            "conflicts_initial": len(coordination.get("initial_conflicts", [])),
            "conflicts_residual": len(coordination.get("residual_conflicts", [])),
            "coordination": coordination.get("status"), "replanned": evidence.get("replanned_for_coordination"),
            "search_mode": reference.get("mode"), "optimality": reference.get("optimality"),
            "exhaustive_assignments": reference.get("exhaustive_assignments"),
            "assignments_evaluated": reference.get("assignments_evaluated"),
            "routes_validated": reference.get("routes_validated"), "elapsed_s": round(elapsed, 3)}


def optimality_gap(n: int, points) -> dict:
    """Greedy vs exhaustive on a problem small enough for both (same checks, same objective)."""
    from multiagent import swarm
    from multiagent.swarm import Objective, SwarmProblem
    context = OperatingContext.model_validate(context_dict(n))
    site, fleet = _world(context)
    make = lambda: SwarmProblem(site, fleet, context, [Objective(f"O{i + 1}", p, s) for i, (p, s) in enumerate(points)],  # noqa: E731
                                list(context.drones), 0.0)
    with redirect_stdout(io.StringIO()):
        exact = swarm.reference_allocation(make())["evidence"]["chosen"]
        greedy = swarm.greedy_allocation(make())["evidence"]["chosen"]
    return {"drones": n, "objectives": len(points), "exhaustive": exact, "greedy": greedy,
            "coverage_gap": exact["covered"] - greedy["covered"],
            "makespan_ratio_greedy_over_exhaustive": (greedy["makespan_min"] / exact["makespan_min"])
            if exact["makespan_min"] and greedy["covered"] == exact["covered"] else None}


def compare() -> dict:
    rows = [run_scenario(load_context(FIXTURES / f"swarm_{n}.context.json")) for n in SIZES]
    small = OBJECTIVES[:6]
    gaps = [optimality_gap(n, small) for n in (2, 3)]
    return {"schema": "tfg.multiagent.scalability/1", "data_kind": "SYNTHETIC", "rows": rows, "optimality_gap": gaps,
            "note": "planning-time allocation and separation over declared synthetic profiles; no flight, no physical swarm"}


def table(report: dict) -> str:
    head = ("| drones (avail.) | status | assigned | rejected | makespan s | load Jain | conflicts init/resid | "
            "coordination | search | elapsed s |")
    lines = [head, "|" + " --- |" * 10]
    for r in report["rows"]:
        lines.append(f"| {r['drones_declared']} ({r['drones_available']}) | {r['status']} | {len(r['assigned'])} | "
                     f"{len(r['rejected'])} | {r['makespan_s']} | "
                     f"{'-' if r['load_jain_available'] is None else round(r['load_jain_available'], 3)} | "
                     f"{r['conflicts_initial']}/{r['conflicts_residual']} | {r['coordination']} | "
                     f"{r['search_mode']} | {r['elapsed_s']} |")
    for g in report["optimality_gap"]:
        lines.append(f"\nGreedy vs exhaustive, {g['drones']} drones x {g['objectives']} objectives: coverage gap "
                     f"{g['coverage_gap']}, makespan ratio {g['makespan_ratio_greedy_over_exhaustive']}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic swarm scalability comparison")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--write-fixtures", action="store_true")
    args = parser.parse_args(argv)
    if args.write_fixtures:
        for path in write_fixtures():
            print(path)
        return 0
    report = compare()
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "scalability.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    sys.stdout.write(table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
