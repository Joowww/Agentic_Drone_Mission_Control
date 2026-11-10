"""Instantiate a scenario template over an explicit site and fleet, re-express the historical H2 missions, or
associate finalized Hermes missions with an explicitly selected site, fleet and takeoff points.

An instance is identified by the hashes of everything that fixed its coordinates: template, site, fleet and
each generated mission. Changing any of them yields a different instance id, new mission hashes and a new
validation; an approval recorded for another instance is reported as STALE, never carried over.

Historical H1/H2 missions stay bound to their own references (offsets from each drone's OBSERVED launch
position in the H2 SITL session). ``historical_h2_instance`` re-expresses them explicitly on the launch
positions recorded in that session, with the SITL executor's own mapping function, and records the chain;
it never resolves them against a site.json.

``finalized_instance`` takes finalized draft snapshots (verified by ``load_finalization``) and, only for the takeoff
point the operator names for each vehicle, places each mission's own north/east offsets on that point in the site
frame. The result is a NEW derived mission (new id, hash and deterministic validation); the original stays untouched
and its approval is never inherited. Missing site data blocks the derivation with the site's own reasons.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from models.fleet import QGC_PROFILE, Fleet
from models.mission_definition import MissionDefinition
from models.scenario_template import Dependency, ScenarioTemplate
from models.site import Site
from planning.mission_artifacts import load_finalization
from planning.site_geometry import FRAME_METHOD, geo_to_local, local_to_geo, north_east_to_local
from planning.site_validation import (
    route_separation, validate_aerial_local_route, validate_aerial_route, validate_ground_local_target,
    validate_ground_route, validate_site,
)
from tools.hermes_mission_validation import validate_mission
from tools.simulation_mission_executor import _execution_compatibility_errors
from tools.simulation_mission_mapper import _calculate_local_offset_metres, map_mission_route_to_simulation
from tools.simulation_profiles import PROFILES

INSTANCE_SCHEMA = "tfg.scenario-instance/1"
APPROVAL_SCHEMA = "tfg.instance-approval/1"
H2_ROOT = Path(__file__).resolve().parent.parent / "simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24"
H2_CHILDREN = {"drone_01": "child_1_2f7db1f6", "drone_02": "child_2_febf7c4f"}
H2_SPAWNS = {  # simulation/ros2_gazebo/launch/tfg_demo.launch.py: Gazebo x, y, z, R, P, Y
    "drone_01": ["-2.0", "0.0", "0.195", "0", "0", "1.5708"], "drone_02": ["2.0", "0.0", "0.195", "0", "0", "1.5708"],
    "rover_01": ["0.0", "-3.0", "0.195", "0", "0", "1.5708"]}
# agri_demo_001 order (H1/H2 and the R1 coordinator): (vehicle, after vehicle, condition, scenario point).
AGRI_DEMO_001_SEQUENCE = (("drone_02", "drone_01", "COMPLETED", None), ("rover_01", "drone_01", "POI_REACHED", "POI_A1"))
AGRI_DEMO_001_ORDER = ("drone_01", "drone_02", "rover_01")
FINALIZED_FILES = ("finalization.json", "mission.json", "source_draft.json", "source_draft_state.json")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def load(model, path: Path):
    content = Path(path).read_bytes()
    return model.model_validate_json(content), content


def mission_bytes(mission: MissionDefinition) -> bytes:
    return (mission.model_dump_json(indent=2) + "\n").encode("utf-8")


def _sim_vehicle_ids() -> set[str]:
    return {v.vehicle_id for profile in PROFILES.values() for v in profile.vehicles}


def coordination_checks(template: ScenarioTemplate, fleet: Fleet) -> dict:
    """Unique tasks and vehicles, coherent assignments, existing dependencies, no cycles, a consistent order."""
    errors = []
    tasks = {t.task_id: ("air", t) for t in template.aerial_tasks}
    tasks.update({t.task_id: ("ground", t) for t in template.ground_tasks})
    if len(tasks) != len(template.aerial_tasks) + len(template.ground_tasks):
        errors.append("duplicate task ids")
    assigned = [t.vehicle_id for _, t in tasks.values()]
    for vehicle_id in sorted({v for v in assigned if assigned.count(v) > 1}):
        errors.append(f"vehicle {vehicle_id} assigned to more than one task")
    for task_id, (domain, task) in tasks.items():
        vehicle = fleet.vehicle(task.vehicle_id)
        if vehicle is None:
            errors.append(f"{task_id}: vehicle {task.vehicle_id} is not in fleet {fleet.fleet_id}")
        elif (domain == "ground") != (vehicle.category == "rover"):
            errors.append(f"{task_id}: {domain} task assigned to {vehicle.category} {vehicle.vehicle_id}")
        elif vehicle.sim_binding is not None and vehicle.sim_binding not in _sim_vehicle_ids():
            errors.append(f"{task.vehicle_id}: sim_binding {vehicle.sim_binding} is not in tools.simulation_profiles")
    graph = {t: set() for t in tasks}
    for dep in template.dependencies:
        if dep.task_id not in tasks or dep.after not in tasks:
            errors.append(f"dependency {dep.task_id} after {dep.after}: unknown task")
            continue
        if dep.condition == "POI_REACHED":
            domain, before = tasks[dep.after]
            if domain != "air" or dep.point not in before.poi_sequence:
                errors.append(f"dependency {dep.task_id}: {dep.point} is not visited by {dep.after}")
        graph[dep.task_id].add(dep.after)
    state, cycle = {}, []

    def visit(node, stack):
        state[node] = "open"
        for parent in sorted(graph[node]):
            if state.get(parent) == "open":
                cycle.append(" -> ".join([*stack, node, parent]))
            elif parent not in state:
                visit(parent, [*stack, node])
        state[node] = "done"
    for node in sorted(graph):
        if node not in state:
            visit(node, [])
    errors.extend(f"dependency cycle: {c}" for c in cycle)
    order = template.execution_order
    if sorted(order) != sorted(tasks):
        errors.append(f"execution_order must list every task exactly once: {sorted(tasks)}")
    else:
        position = {t: i for i, t in enumerate(order)}
        errors.extend(f"execution_order runs {d.task_id} before {d.after}" for d in template.dependencies
                      if d.task_id in position and d.after in position and position[d.task_id] < position[d.after])
    return {"status": "FAIL" if errors else "PASS", "errors": errors, "mode": "SEQUENTIAL", "order": order,
            "dependencies": [d.model_dump() for d in template.dependencies],
            "note": "dependencies are conditions on OBSERVED outcomes held by the coordinator; never a time wait. "
                    "Individual .plan files do not coordinate vehicles."}


def _mission(template, task, vehicle, site, home, waypoints) -> MissionDefinition:
    d = template.mission_defaults
    return MissionDefinition.model_validate({
        "mission_id": f"{template.template_id}_v{template.version}_{site.site_id}_v{site.version}_{task.task_id}",
        "name": f"{template.template_id} {task.task_id} over {site.site_id} v{site.version}",
        "source": "json",
        "vehicle": {"vehicle_id": vehicle.vehicle_id, "vehicle_type": vehicle.vehicle_type,
                    "autopilot": vehicle.autopilot, "cruise_speed_kmh": d.cruise_speed_kmh,
                    "battery_percent": d.battery_percent,
                    "battery_consumption_percent_per_minute": d.battery_consumption_percent_per_minute},
        "objective": {"objective_type": "precision_agriculture", "target": f"{site.site_id}:{task.task_id}",
                      "description": "Navigate over site-declared points of interest. No imagery or crop detection."},
        "route": {"mode": "waypoints", "home": {"latitude": home[0], "longitude": home[1], "altitude_m": 0.0},
                  "waypoints": waypoints, "return_to_home": True},
        "environment": {"wind_speed_kmh": d.wind_speed_kmh, "wind_direction_from_deg": d.wind_direction_from_deg},
        "constraints": {"minimum_battery_reserve_percent": d.minimum_battery_reserve_percent,
                        "maximum_wind_speed_kmh": d.maximum_wind_speed_kmh, "maximum_altitude_m": d.maximum_altitude_m},
        "failsafe": d.failsafe.model_dump(),
    })


def _deterministic(mission: MissionDefinition) -> dict:
    result = validate_mission(mission)
    return {"mission_status": result.get("mission_status"), "execution_status": result.get("execution_status"),
            "errors": result.get("errors"), "failure_reasons": result.get("failure_reasons"),
            "sitl_executor_compatibility_errors": _execution_compatibility_errors(mission)}


def instantiate(template_path: Path, site_path: Path, fleet_path: Path) -> dict:
    """Instance record plus generated mission bytes (``missions``: {task_id: bytes}). No file is written."""
    template, template_bytes = load(ScenarioTemplate, template_path)
    site, site_bytes = load(Site, site_path)
    fleet, fleet_bytes = load(Fleet, fleet_path)
    site_report = validate_site(site)
    geographic = site_report["capabilities"]["sitl_geographic_export"]
    geo, frame = site.geo_reference, site.local_frame
    missions, aerial, ground = {}, [], []
    for task in template.aerial_tasks:
        vehicle = fleet.vehicle(task.vehicle_id)
        entry = {"task_id": task.task_id, "vehicle_id": task.vehicle_id, "mission_sha256": None, "blocks": []}
        spatial = validate_aerial_route(site, task.takeoff_point, task.poi_sequence, task.altitude_m,
                                        template.planning_margin_m, vehicle)
        entry["spatial_validation"] = spatial
        if vehicle is None:
            entry["blocks"].append(("BLOCKED_MISSING_DATA", f"vehicle {task.vehicle_id} is not in the fleet"))
        elif vehicle.compatibility == "UNRESOLVED_COMPATIBILITY":
            entry["blocks"].append(("COMPATIBILITY_PENDING", f"{vehicle.vehicle_id}: {vehicle.platform}"))
        elif vehicle.export_profile != QGC_PROFILE:
            entry["blocks"].append(("UNSUPPORTED_FORMAT", f"{vehicle.vehicle_id} has no documented export profile"))
        if not geographic:
            entry["blocks"].append(("BLOCKED_MISSING_DATA", "; ".join(site_report["export_blocks"]["sitl"])))
        if spatial["route_local"] is not None:
            names = [task.takeoff_point, *task.poi_sequence]
            entry["derivation"] = [{"site_point": name, "local_xy_m": spatial["route_local"][i], "frame": frame.frame_id,
                                    "method": FRAME_METHOD} for i, name in enumerate(names)]
        if not entry["blocks"] and spatial["route_local"] is not None:
            convert = lambda xy: local_to_geo(*xy, origin_latitude=geo.latitude, origin_longitude=geo.longitude,  # noqa: E731
                                              y_axis_bearing_deg=frame.y_axis_bearing_deg)
            home = convert(spatial["route_local"][0])
            waypoints = []
            for poi, xy, record in zip(task.poi_sequence, spatial["route_local"][1:-1], entry["derivation"][1:]):
                latitude, longitude = convert(xy)
                record.update(latitude=latitude, longitude=longitude)
                waypoints.append({"waypoint_id": poi, "latitude": latitude, "longitude": longitude,
                                  "altitude_m": task.altitude_m, "speed_kmh": task.requested_speed_kmh,
                                  "action": "navigate"})
            entry["derivation"][0].update(latitude=home[0], longitude=home[1])
            mission = _mission(template, task, vehicle, site, home, waypoints)
            content = mission_bytes(mission)
            missions[task.task_id] = content
            entry.update(mission_id=mission.mission_id, mission_sha256=sha256(content),
                         deterministic_validation=_deterministic(mission),
                         planned_home={"latitude": home[0], "longitude": home[1],
                                       "amsl_m": site.vertical_reference.origin_ground_amsl_m,
                                       "amsl_source": "site vertical_reference.origin_ground_amsl_m "
                                                      f"({site.vertical_reference.terrain}); not the effective home"})
        aerial.append(entry)
    for task in template.ground_tasks:
        vehicle = fleet.vehicle(task.vehicle_id)
        ground.append({"task_id": task.task_id, "vehicle_id": task.vehicle_id, "kind": task.kind,
                       "start_point": task.start_point, "target_point": task.target_point,
                       "spatial_validation": validate_ground_route(site, task.start_point, task.target_point,
                                                                   template.planning_margin_m, vehicle),
                       "export": "FORMAT_PENDING: no rover exporter; a .plan is not assumed",
                       "frame_transform_to_rover": "NOT_ACCREDITED (site frame -> rover odometry frame)",
                       "execution": "outside this package: R1 coordinator gates unchanged"})
    routes = {e["task_id"]: e["spatial_validation"]["route_local"] for e in aerial
              if e["spatial_validation"].get("route_local")}
    inputs = {"template": {"id": template.template_id, "version": template.version, "sha256": sha256(template_bytes)},
              "site": {"id": site.site_id, "version": site.version, "status": site.status, "sha256": sha256(site_bytes)},
              "fleet": {"id": fleet.fleet_id, "version": fleet.version, "sha256": sha256(fleet_bytes)}}
    identity = {"inputs": inputs, "missions": {e["task_id"]: e["mission_sha256"] for e in aerial}}
    instance = {"schema": INSTANCE_SCHEMA, "instance_id": sha256(canonical(identity))[:16], "inputs": inputs,
                "provenance": {"SYNTHETIC": "SYNTHETIC", "TEMPLATE_PENDING_MEASUREMENT": "TEMPLATE"}.get(
                    site.status, "REAL_SITE_DECLARED"),
                "site_validation": site_report, "aerial": aerial, "ground": ground,
                "coordination": coordination_checks(template, fleet),
                "joint_spatial": {"frame": frame.frame_id, "pairs": route_separation(routes)},
                "references": {"site_origin": frame.origin_point_id, "planned_takeoff": "site points of kind "
                               "planned_takeoff", "effective_home": "NOT_OBSERVED (ArduPilot sets it at arming)",
                               "estimator_origin": "NOT_OBSERVED", "gazebo_spawn": "not related to the site frame "
                               "(no accredited transform)", "rover_start": "site points of kind rover_start"}}
    return {"instance": instance, "missions": missions,
            "sources": {"template.json": template_bytes, "site.json": site_bytes, "fleet.json": fleet_bytes},
            "fleet": fleet, "site": site, "template": template}


def agri_demo_001_sequence(task_of: dict[str, str]) -> tuple[list[str], list[dict]]:
    """Order and dependencies of agri_demo_001 for the vehicles present in ``task_of`` (vehicle -> task id)."""
    dependencies = [{"task_id": task_of[v], "after": task_of[a], "condition": c, **({"point": p} if p else {})}
                    for v, a, c, p in AGRI_DEMO_001_SEQUENCE if v in task_of and a in task_of]
    return [task_of[v] for v in AGRI_DEMO_001_ORDER if v in task_of], dependencies


def _sums(root: Path) -> dict[str, str]:
    lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    return {name: digest for digest, name in (line.split("  ", 1) for line in lines if line.strip())}


def _display(path: Path) -> str:
    repository = H2_ROOT.parents[3]
    path = Path(path).resolve()
    return str(path.relative_to(repository)) if path.is_relative_to(repository) else path.name


def historical_h2_instance(root: Path = H2_ROOT, fleet_path: Path | None = None) -> dict:
    """The two missions that ran in H2, re-expressed on that session's recorded launch positions."""
    sums = _sums(root)
    used = ["scenario_summary.json", *[f"{c}/{n}" for c in H2_CHILDREN.values() for n in ("mission.json", "report.json")]]
    altered = [name for name in used if sha256((root / name).read_bytes()) != sums.get(name)]
    if altered:
        raise ValueError(f"H2 evidence does not match its SHA256SUMS: {altered}")
    summary = json.loads((root / "scenario_summary.json").read_bytes())
    fleet = fleet_bytes = None
    if fleet_path is not None:
        fleet, fleet_bytes = load(Fleet, fleet_path)
    missions, aerial, routes, origin = {}, [], {}, None
    for vehicle_id, child in H2_CHILDREN.items():
        content = (root / child / "mission.json").read_bytes()
        original = MissionDefinition.model_validate_json(content)
        report = json.loads((root / child / "report.json").read_bytes())
        result = report["executor_result"]
        launch, origin = result["launch_position"], result["simulation_origin"]
        if sha256(content) != summary["binding"][vehicle_id]["mission_sha256"]:
            raise ValueError(f"{vehicle_id}: executed snapshot is not the bound mission")
        mapped = map_mission_route_to_simulation(original, simulation_home_latitude=launch["latitude"],
                                                 simulation_home_longitude=launch["longitude"])
        rebased = original.model_copy(deep=True, update={"mission_id": f"{original.mission_id}_h2_sitl_rebased"})
        rebased.route.home = rebased.route.home.model_copy(update={"latitude": launch["latitude"],
                                                                   "longitude": launch["longitude"]})
        rebased.route.waypoints = [w.model_copy(update={"latitude": m["latitude"], "longitude": m["longitude"]})
                                   for w, m in zip(original.route.waypoints, mapped)]
        rebased = MissionDefinition.model_validate(rebased.model_dump())
        data = mission_bytes(rebased)
        missions[vehicle_id] = data
        reached = {e["waypoint_id"]: e for e in result["events"] if e.get("event") == "WAYPOINT_REACHED"}
        consistency = []
        for waypoint in rebased.route.waypoints:
            event = reached.get(waypoint.waypoint_id)
            if event:
                n, e = _calculate_local_offset_metres(rebased.route.home, event["final_position"]["latitude"],
                                                      event["final_position"]["longitude"])
                tn, te = _calculate_local_offset_metres(rebased.route.home, waypoint.latitude, waypoint.longitude)
                distance = math.hypot(n - tn, e - te)
                consistency.append({"waypoint_id": waypoint.waypoint_id, "recomputed_error_m": round(distance, 3),
                                    "recorded_horizontal_error_m": round(event["horizontal_error_m"], 3)})
        local = [_calculate_local_offset_metres(
            rebased.route.home.model_copy(update={"latitude": origin["latitude"], "longitude": origin["longitude"]}),
            lat, lon) for lat, lon in [(rebased.route.home.latitude, rebased.route.home.longitude),
                                       *[(w.latitude, w.longitude) for w in rebased.route.waypoints],
                                       (rebased.route.home.latitude, rebased.route.home.longitude)]]
        routes[vehicle_id] = [[round(e, 3), round(n, 3)] for n, e in local]  # x=east, y=north from the world origin
        points = summary["binding"][vehicle_id]["waypoint_by_point"]
        aerial.append({
            "task_id": f"H2_{vehicle_id}", "vehicle_id": vehicle_id, "mission_id": rebased.mission_id,
            "mission_sha256": sha256(data), "source_mission_sha256": sha256(content),
            "source": f"{root.name}/{child}/mission.json (executed snapshot, SHA256SUMS verified)",
            "waypoint_by_point": points, "blocks": [],
            "derivation": {"method": "tools.simulation_mission_mapper.map_mission_route_to_simulation (the executor's "
                                     "own mapping): offsets from the mission home placed on the launch position",
                           "launch_position_source": f"{child}/report.json executor_result.launch_position "
                                                     "(observed, float32, historical session)"},
            "consistency_with_h2": consistency,
            "deterministic_validation": _deterministic(rebased),
            "spatial_validation": {"status": "NOT_CHECKABLE", "checks": [],
                                   "detail": "no site: H2 geometry is bound to each drone's own launch position"},
            "planned_home": {"latitude": launch["latitude"], "longitude": launch["longitude"],
                             "amsl_m": launch["altitude_amsl_m"],
                             "amsl_source": "observed launch altitude in H2 (float32); not the effective home",
                             # H2 returned to this same observed launch coordinate before LAND.
                             "return_coordinate_is_observed_launch": True},
            "references": {"declared_home_in_mission": original.route.home.model_dump(),
                           "observed_launch_position": launch, "gazebo_world_origin": origin,
                           "gazebo_spawn_xyzrpy": H2_SPAWNS[vehicle_id],
                           "effective_home": "NOT_RECORDED (set by ArduPilot at arming)",
                           "estimator_origin": "NOT_RECORDED"}})
    identity = {"source": {k: v for k, v in sums.items() if k in used}, "missions": {k: sha256(v) for k, v in missions.items()},
                "fleet": sha256(fleet_bytes) if fleet_bytes else None}
    order, dependencies = agri_demo_001_sequence({"drone_01": "H2_drone_01", "drone_02": "H2_drone_02",
                                                  "rover_01": "R1"})
    instance = {
        "schema": INSTANCE_SCHEMA, "instance_id": sha256(canonical(identity))[:16], "provenance": "SITL_HISTORICAL",
        "inputs": {"h2_record": {"path": _display(root),
                                 "sequence_id": summary["sequence"]["sequence_id"],
                                 "files_sha256": identity["source"]},
                   "fleet": {"id": fleet.fleet_id, "version": fleet.version, "sha256": sha256(fleet_bytes)} if fleet else None},
        "aerial": aerial,
        "ground": [{"task_id": "R1", "vehicle_id": "rover_01", "kind": "VISIT_AND_STOP", "target_point": "POI_A1",
                    "target_definition": "offset of drone_01's mission from ITS observed launch position",
                    "spatial_validation": {"status": "NOT_CHECKABLE", "detail": "no site and no rover drivable area"},
                    "export": "FORMAT_PENDING: no rover exporter; a .plan is not assumed",
                    "frame_transform_to_rover": "NOT_ACCREDITED", "execution": "R1 coordinator: BLOCKED_PENDING "
                    "per its own gates (unchanged)"}],
        "coordination": {"status": "PASS", "errors": [], "mode": "SEQUENTIAL", "order": order,
                         "dependencies": dependencies,
                         "note": "the H1/H2 order is sequential (drone_01 then drone_02); no time waits"},
        "joint_spatial": {"frame": "ENU metres from the recorded Gazebo world origin (local linear model)",
                          "pairs": route_separation(routes)},
        "references": {"site": "NONE (historical missions are not resolved against a site.json)"},
    }
    return {"instance": instance, "missions": missions, "sources": {"fleet.json": fleet_bytes} if fleet_bytes else {},
            "fleet": fleet, "site": None, "template": None}


def _hermes_run(evidence: Path) -> tuple[dict, dict[str, str], dict[str, bytes]]:
    """A Hermes run evidence directory: every file must match its SHA256SUMS before anything is read from it."""
    sums = _sums(evidence)
    altered = sorted(n for n, d in sums.items() if not (evidence / n).is_file() or sha256((evidence / n).read_bytes()) != d)
    if altered:
        raise ValueError(f"Hermes run evidence does not match its SHA256SUMS: {altered}")
    try:
        files = {n: (evidence / n).read_bytes() for n in ("execute_result.json", "review_result.json")}
        run, review = (json.loads(files[n]) for n in ("execute_result.json", "review_result.json"))
        record = {"evidence": _display(evidence), "manifest_sha256": sha256((evidence / "SHA256SUMS").read_bytes()),
                  "run_id": run["run_id"], "return_code": run["return_code"],
                  "hermes_invocations": run["hermes_invocations"], "provider": run["provider_configured"],
                  "model": run["model_configured"], "hermes_commit": run["verified_hermes_commit"],
                  "review_verdict": review["mcp_tool_trial_verdict"],
                  "files_sha256": {n: sums[n] for n in files}}
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise ValueError(f"Hermes run evidence lacks execute_result/review_result fields: {exc}") from exc
    return record, sums, files


def _binding_points(binding_path: Path | None) -> tuple[dict | None, bytes | None, dict]:
    """Scenario point -> waypoint links of a scenario binding (e.g. H1's), checked against its own SHA256SUMS."""
    if binding_path is None:
        return None, None, {}
    binding_path = Path(binding_path)
    content = binding_path.read_bytes()
    sums_path = binding_path.parent / "SHA256SUMS"
    if sums_path.is_file() and _sums(binding_path.parent).get(binding_path.name) != sha256(content):
        raise ValueError(f"{binding_path.name} does not match {sums_path}")
    binding = json.loads(content)
    if binding.get("status") != "BOUND":
        raise ValueError(f"scenario binding status is {binding.get('status')!r}, not BOUND")
    record = {"path": _display(binding_path), "sha256": sha256(content), "scenario_id": binding.get("scenario_id"),
              "association_basis": binding.get("association_basis")}
    return record, content, binding.get("artifacts") or {}


def finalized_instance(store: Path, assignments: list[dict], site_path: Path, fleet_path: Path, *,
                       rover: dict | None = None, scenario_binding: Path | None = None,
                       hermes_evidence: Path | None = None, planning_margin_m: float = 1.0) -> dict:
    """Finalized Hermes missions associated with a site, a fleet and one operator-selected takeoff point each.

    ``assignments``: [{"vehicle_id", "draft_id", "finalization_id", "takeoff_point"}]; ``rover``: {"vehicle_id",
    "start_point"}. Integrity, identity or assignment problems are refused (ValueError); missing site data and
    failed checks are recorded as blocked artifacts, never filled in."""
    store = Path(store)
    site, site_bytes = load(Site, site_path)
    fleet, fleet_bytes = load(Fleet, fleet_path)
    site_report = validate_site(site)
    geographic = site_report["capabilities"]["sitl_geographic_export"]
    geo, frame = site.geo_reference, site.local_frame
    run, run_sums, run_files = _hermes_run(Path(hermes_evidence)) if hermes_evidence else (None, {}, {})
    binding, binding_bytes, bound = _binding_points(scenario_binding)
    for key in ("vehicle_id", "finalization_id"):
        values = [a[key] for a in assignments]
        if len(values) != len(set(values)):
            raise ValueError(f"each {key} may be assigned once: {values}")
    sources = {"site.json": site_bytes, "fleet.json": fleet_bytes}
    if binding_bytes is not None:
        sources["scenario_binding.json"] = binding_bytes
    sources.update({f"hermes/run/{n}": data for n, data in run_files.items()})
    missions, aerial, local_points = {}, [], {}
    for assignment in assignments:
        vehicle_id, takeoff_id = assignment["vehicle_id"], assignment["takeoff_point"]
        draft_id, finalization_id = assignment["draft_id"], assignment["finalization_id"]
        record = load_finalization(draft_id, finalization_id, drafts_root=store / "drafts")
        directory = store / "drafts" / draft_id / finalization_id
        files = {n: (directory / n).read_bytes() for n in FINALIZED_FILES if (directory / n).is_file()}
        state = json.loads(files["source_draft_state.json"]) if "source_draft_state.json" in files else None
        if state is not None and state.get("draft_revision") != record["draft_revision"]:
            raise ValueError(f"{finalization_id}: finalized revision {record['draft_revision']} differs from its source "
                             f"draft state {state.get('draft_revision')}")
        if run is not None:
            try:
                relative = directory.resolve().relative_to(Path(hermes_evidence).resolve())
            except ValueError:
                raise ValueError(f"{finalization_id} is not inside the Hermes run evidence") from None
            unlisted = [n for n, data in files.items() if run_sums.get(f"{relative.as_posix()}/{n}") != sha256(data)]
            if unlisted:
                raise ValueError(f"{finalization_id}: {unlisted} not listed with these hashes in the run evidence")
        original = MissionDefinition.model_validate_json(files["mission.json"])
        if original.vehicle.vehicle_id != vehicle_id:
            raise ValueError(f"assignment refused: finalization {finalization_id} is a mission for "
                             f"{original.vehicle.vehicle_id}, not {vehicle_id}")
        sources.update({f"hermes/{vehicle_id}/{n}": data for n, data in files.items()})
        vehicle = fleet.vehicle(vehicle_id)
        task_id = f"HERMES_{vehicle_id}"
        validation = record["validation"]
        answer = run_files and (Path(hermes_evidence) / "private/stdout.txt")
        entry = {"task_id": task_id, "vehicle_id": vehicle_id, "mission_id": None, "mission_sha256": None, "blocks": [],
                 "source": {"kind": "HERMES_FINALIZATION", "store": _display(store), "draft_id": draft_id,
                            "finalization_id": finalization_id, "draft_revision": record["draft_revision"],
                            "geometry_revision": record.get("geometry_revision"), "mission_id": original.mission_id,
                            "mission_sha256": record["mission_sha256"], "record_sha256": record["record_sha256"],
                            "files_sha256": {n: sha256(d) for n, d in files.items()}, "integrity": record["integrity"],
                            "relocated_from": record.get("relocated_from"),
                            "provenance_status": record.get("provenance_status"),
                            "flight_consent": record.get("flight_consent"),
                            "validation_at_finalization": {
                                "mission_status": validation.get("mission_status"),
                                "execution_status": validation.get("execution_status"),
                                "qgc_export": (validation.get("qgc_export") or {}).get("status")},
                            "hermes_run_id": run["run_id"] if run else None,
                            "in_hermes_final_answer": (finalization_id in answer.read_text(encoding="utf-8"))
                            if answer and answer.is_file() else "NOT_CHECKED"},
                 "approval_inherited": False,
                 "association": {"site": f"{site.site_id} v{site.version}", "takeoff_point": takeoff_id,
                                 "selected_by": "operator (explicit assignment)"},
                 "waypoint_by_point": None}
        link = bound.get(vehicle_id) or {}
        if binding is not None and link.get("mission_sha256") == record["mission_sha256"]:
            entry["waypoint_by_point"] = link.get("waypoint_by_point")
        elif binding is not None:
            entry["scenario_binding_mismatch"] = f"binding names {link.get('mission_sha256')} for {vehicle_id}"
        if vehicle is None:
            entry["blocks"].append(("BLOCKED_MISSING_DATA", f"vehicle {vehicle_id} is not in the fleet"))
        elif vehicle.compatibility == "UNRESOLVED_COMPATIBILITY":
            entry["blocks"].append(("COMPATIBILITY_PENDING", f"{vehicle.vehicle_id}: {vehicle.platform}"))
        elif vehicle.export_profile != QGC_PROFILE:
            entry["blocks"].append(("UNSUPPORTED_FORMAT", f"{vehicle.vehicle_id} has no documented export profile"))
        if not geographic:
            missing = [*site_report["missing"], *site_report["geographic_references"]["missing"]]
            entry["blocks"].append(("BLOCKED_MISSING_DATA", "; ".join(site_report["export_blocks"]["sitl"])
                                    + (f" (missing: {', '.join(missing)})" if missing else "")))
        home, waypoints = original.route.home, original.route.waypoints
        if original.route.mode != "waypoints" or home is None or not waypoints:
            entry["blocks"].append(("BLOCKED_MISSING_DATA", "the finalized mission has no waypoint route with a home"))
            entry["spatial_validation"] = {"status": "NOT_CHECKABLE", "checks": [], "detail": "no waypoint route"}
            aerial.append(entry)
            continue
        offsets = [_calculate_local_offset_metres(home, w.latitude, w.longitude) for w in waypoints]  # north, east
        declared = (record.get("geometry_intent") or {}).get("offsets") or []
        takeoff = site.point(takeoff_id)
        origin = (takeoff.x_m, takeoff.y_m) if takeoff is not None and None not in (takeoff.x_m, takeoff.y_m) else None
        route = [(w.waypoint_id, None if origin is None else
                  tuple(o + d for o, d in zip(origin, north_east_to_local(n, e, frame.y_axis_bearing_deg))))
                 for w, (n, e) in zip(waypoints, offsets)]
        altitude = max(w.altitude_m for w in waypoints)
        spatial = (validate_aerial_local_route(site, takeoff_id, route, altitude, planning_margin_m, vehicle)
                   if origin is not None or takeoff is None or takeoff.kind != "planned_takeoff" else
                   {"status": "FAIL", "checks": [{"check": "coordinates", "status": "FAIL",
                                                  "detail": f"{takeoff_id} has no measured local coordinates"}],
                    "route_local": None})
        entry["spatial_validation"] = spatial
        entry["derivation"] = {
            "method": "north/east offsets of each waypoint from the finalized mission's own home "
                      "(tools.simulation_mission_mapper._calculate_local_offset_metres) placed on the selected "
                      f"planned_takeoff point of the site frame ({FRAME_METHOD})",
            "frame": frame.frame_id, "takeoff_point": takeoff_id, "takeoff_local_xy_m": origin,
            "declared_home_of_finalized_mission": home.model_dump(),
            "waypoints": [{"waypoint_id": w.waypoint_id, "offset_north_m": round(n, 6), "offset_east_m": round(e, 6),
                           "local_xy_m": None if xy is None else [round(v, 6) for v in xy],
                           "altitude_m_relative_to_home": w.altitude_m}
                          for w, (n, e), (_, xy) in zip(waypoints, offsets, route)],
            "offsets_vs_finalized_geometry_max_diff_m": round(max(
                (math.hypot(n - d["north_m"], e - d["east_m"]) for (n, e), d in zip(offsets, declared)),
                default=0.0), 6) if len(declared) == len(offsets) else "NOT_COMPARABLE"}
        if not entry["blocks"] and spatial["route_local"] is not None:
            convert = lambda xy: local_to_geo(*xy, origin_latitude=geo.latitude, origin_longitude=geo.longitude,  # noqa: E731
                                              y_axis_bearing_deg=frame.y_axis_bearing_deg)
            new_home = convert(origin)
            derived = original.model_copy(deep=True, update={
                "mission_id": f"{original.mission_id}_on_{site.site_id}_v{site.version}_{takeoff_id}",
                "name": f"{original.name} (re-based on {site.site_id} v{site.version} {takeoff_id})"})
            derived.route.home = derived.route.home.model_copy(update={"latitude": new_home[0],
                                                                       "longitude": new_home[1]})
            geo_points = [convert(xy) for _, xy in route]
            derived.route.waypoints = [w.model_copy(update={"latitude": lat, "longitude": lon})
                                       for w, (lat, lon) in zip(derived.route.waypoints, geo_points)]
            derived = MissionDefinition.model_validate(derived.model_dump())
            content = mission_bytes(derived)
            missions[task_id] = content
            for record_wp, (lat, lon) in zip(entry["derivation"]["waypoints"], geo_points):
                record_wp.update(latitude=lat, longitude=lon)
            entry.update(mission_id=derived.mission_id, mission_sha256=sha256(content),
                         deterministic_validation=_deterministic(derived),
                         planned_home={"latitude": new_home[0], "longitude": new_home[1],
                                       "amsl_m": site.vertical_reference.origin_ground_amsl_m,
                                       "amsl_source": "site vertical_reference.origin_ground_amsl_m "
                                                      f"({site.vertical_reference.terrain}); not the effective home"})
        local_points[vehicle_id] = {label: xy for label, xy in route if xy is not None}
        aerial.append(entry)
    task_of = {e["vehicle_id"]: e["task_id"] for e in aerial}
    ground = []
    if rover is not None:
        rover_vehicle = fleet.vehicle(rover["vehicle_id"])
        _, after, _, point = AGRI_DEMO_001_SEQUENCE[1]
        before = next((e for e in aerial if e["vehicle_id"] == after), None)
        waypoint = ((before or {}).get("waypoint_by_point") or {}).get(point)
        target_xy = local_points.get(after, {}).get(waypoint) if waypoint else None
        ground.append({"task_id": "R1", "vehicle_id": rover["vehicle_id"], "kind": "VISIT_AND_STOP",
                       "start_point": rover["start_point"], "target_point": point,
                       "target_definition": (f"{point} = {waypoint} of {task_of.get(after)} (scenario binding), "
                                             "re-based on the site" if waypoint else
                                             f"{point} NOT RESOLVED: no scenario binding for {after}'s finalized mission"),
                       "spatial_validation": validate_ground_local_target(site, rover["start_point"], target_xy,
                                                                          planning_margin_m, rover_vehicle),
                       "export": "FORMAT_PENDING: no rover exporter; a .plan is not assumed",
                       "frame_transform_to_rover": "NOT_ACCREDITED (site frame -> rover odometry frame)",
                       "execution": "outside this package: R1 coordinator gates unchanged"})
        task_of[rover["vehicle_id"]] = "R1"
    order, dependencies = agri_demo_001_sequence(task_of)
    plan = SimpleNamespace(
        aerial_tasks=[SimpleNamespace(task_id=e["task_id"], vehicle_id=e["vehicle_id"],
                                      poi_sequence=list(e["waypoint_by_point"] or {})) for e in aerial],
        ground_tasks=[SimpleNamespace(task_id=g["task_id"], vehicle_id=g["vehicle_id"]) for g in ground],
        dependencies=[Dependency.model_validate(d) for d in dependencies], execution_order=order)
    coordination = coordination_checks(plan, fleet)
    routes = {e["task_id"]: e["spatial_validation"]["route_local"] for e in aerial
              if (e.get("spatial_validation") or {}).get("route_local")}
    inputs = {"site": {"id": site.site_id, "version": site.version, "status": site.status, "sha256": sha256(site_bytes)},
              "fleet": {"id": fleet.fleet_id, "version": fleet.version, "sha256": sha256(fleet_bytes)},
              "finalized_missions": {e["vehicle_id"]: {k: e["source"][k] for k in
                                                       ("draft_id", "finalization_id", "mission_sha256", "record_sha256")}
                                     for e in aerial},
              "assignments": [{"vehicle_id": a["vehicle_id"], "takeoff_point": a["takeoff_point"]} for a in assignments],
              "rover": rover, "planning_margin_m": planning_margin_m, "scenario_binding": binding, "hermes_run": run}
    identity = {"inputs": inputs, "missions": {e["task_id"]: e["mission_sha256"] for e in aerial}}
    instance = {"schema": INSTANCE_SCHEMA, "instance_id": sha256(canonical(identity))[:16], "inputs": inputs,
                "provenance": "HERMES_FINALIZED_ON_" + {"SYNTHETIC": "SYNTHETIC",
                                                        "TEMPLATE_PENDING_MEASUREMENT": "TEMPLATE"}.get(
                    site.status, "REAL_SITE_DECLARED"),
                "site_validation": site_report, "aerial": aerial, "ground": ground, "coordination": coordination,
                "joint_spatial": {"frame": frame.frame_id, "pairs": route_separation(routes)},
                "references": {"site_origin": frame.origin_point_id,
                               "planned_takeoff": "the planned_takeoff point the operator assigned to each vehicle",
                               "finalized_mission_home": "declared in each finalized mission; kept in its source "
                                                         "copy and replaced by the takeoff point in the derived one",
                               "effective_home": "NOT_OBSERVED (ArduPilot sets it at arming)",
                               "estimator_origin": "NOT_OBSERVED", "gazebo_spawn": "not related to the site frame "
                               "(no accredited transform)", "rover_start": "the rover_start point the operator named"}}
    return {"instance": instance, "missions": missions, "sources": sources, "fleet": fleet, "site": site,
            "template": None}


def approval_draft(instance: dict, scope: str) -> dict:
    """What an operator approval must bind; ``approved_by`` stays null until a person fills it."""
    return {"schema": APPROVAL_SCHEMA, "scope": scope, "kind": "OPERATOR_DECLARATION", "approved_by": None,
            "binds": {"instance_id": instance["instance_id"], "inputs": instance["inputs"],
                      "missions": {e["task_id"]: e["mission_sha256"] for e in instance["aerial"]}},
            "note": "a declaration bound to hashes; it does not authenticate the person"}


def check_approval(approval: dict | None, instance: dict, scope: str) -> dict:
    if approval is None:
        return {"status": "ABSENT", "mismatches": []}
    expected = approval_draft(instance, scope)["binds"]
    binds = approval.get("binds") or {}
    mismatches = [k for k in ("instance_id", "inputs", "missions") if binds.get(k) != expected[k]]
    if approval.get("scope") != scope:
        mismatches.append("scope")
    if not approval.get("approved_by"):
        mismatches.append("approved_by empty")
    status = "STALE" if mismatches else "BOUND"
    return {"status": status, "mismatches": mismatches, "kind": approval.get("kind"),
            "approved_by": approval.get("approved_by"),
            "note": "BOUND means the hashes match; it is not an authentication"}
