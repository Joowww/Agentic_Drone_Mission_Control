"""Mission inputs -> ONE common contract (brief /2 + provenance) that the supervisor, the Drone and Rover Agents, the
validators, the QGC generator and the executor bridge already use. Existing project code is reused, not rewritten:

  natural language        -> the Mission Orchestrator itself (interpret_brief/4, provenance contract); this module only
                             labels the source. Hermes' deterministic parser (planning.deterministic_plan_parser) is
                             available for comparison of the fields it extracts.
  QGroundControl .plan    -> inputs.qgroundcontrol_adapter.load_qgroundcontrol_plan (Hermes' importer, unchanged)
                             -> MissionDefinition -> from_mission_definition()
  structured (internal)   -> models.mission_definition.MissionDefinition -> from_mission_definition()

from_mission_definition() converts each waypoint geo -> site local frame with the site's DECLARED geographic reference
(planning.site_geometry.geo_to_local) and passes the local coordinates as objective coordinates: matching them to a
declared point is left to the planner's own matching (one matching rule in the system, not two). Nothing is invented:
a sensor the plan does not state stays unstated unless the caller declares an explicit mapping; the plan's vehicle is
used only if it is a declared drone; the import context's battery/wind are not operator statements.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from multiagent.contracts import BRIEF_SCHEMA_V2, parse_brief

SCHEMA = "tfg.multiagent.mission-input/1"
RETURN_TOLERANCE_M = 1.0
# every waypoint is a point to visit (the project's QGC exporter refuses non-navigate actions, so an imported .plan
# carries plain waypoints): its action is recorded and a sensor exists only when the caller declares one


def from_mission_definition(md, *, site, context, source: dict, sensor_by_action: dict | None = None,
                            waypoint_semantics: dict | None = None) -> dict:
    """``waypoint_semantics``: {imported waypoint_id: {action, sensor, original_waypoint_id}} from a VERIFIED
    semantics manifest (multiagent.plan_semantics); it restores what a .plan cannot carry and is recorded as such."""
    from planning.site_geometry import geo_to_local
    findings, objectives, transit = [], [], []
    geo, frame = site.geo_reference, site.local_frame
    if geo is None or geo.latitude is None or geo.longitude is None or frame.y_axis_bearing_deg is None:
        return _result(source, None, [{"kind": "SITE_GEOREFERENCE_MISSING", "detail": "cannot place geographic waypoints",
                                       "action": "REJECTED"}], {})
    try:
        return _from_md(md, site=site, context=context, source=source, sensor_by_action=sensor_by_action,
                        waypoint_semantics=waypoint_semantics or {}, geo=geo,
                        frame=frame, findings=findings, objectives=objectives, transit=transit, geo_to_local=geo_to_local)
    except ValueError as exc:  # e.g. a mission of another site, beyond the local linear model
        return _result(source, None, [{"kind": "OUTSIDE_SITE_GEOREFERENCE", "detail": str(exc)[:200],
                                       "action": "REJECTED"}], {})


def _from_md(md, *, site, context, source, sensor_by_action, waypoint_semantics, geo, frame, findings, objectives, transit,
             geo_to_local):
    from planning.site_geometry import MAX_RADIUS_M
    raw_geo_to_local = geo_to_local

    def geo_to_local(*a, **kw):  # noqa: F811 - the same radius rule local_to_geo enforces (geo_to_local does not)
        x, y = raw_geo_to_local(*a, **kw)
        if (x * x + y * y) ** 0.5 > MAX_RADIUS_M:
            raise ValueError(f"point {x:.0f}, {y:.0f} m from the site origin is beyond the {MAX_RADIUS_M:.0f} m local "
                             "linear model: not this site")
        return x, y
    declared_drones = {d.vehicle_id for d in context.drones}
    fields = {}
    home = md.route.home
    hx = hy = None
    if home is not None:
        hx, hy = geo_to_local(home.latitude, home.longitude, origin_latitude=geo.latitude, origin_longitude=geo.longitude,
                              y_axis_bearing_deg=frame.y_axis_bearing_deg)
    last = len(md.route.waypoints) - 1
    for i, wp in enumerate(md.route.waypoints):
        x, y = geo_to_local(wp.latitude, wp.longitude, origin_latitude=geo.latitude, origin_longitude=geo.longitude,
                            y_axis_bearing_deg=frame.y_axis_bearing_deg)
        if i == last and hx is not None and ((x - hx) ** 2 + (y - hy) ** 2) ** 0.5 <= RETURN_TOLERANCE_M:
            # the importer turns LAND/RTL into a final navigation point over home: a return, not an objective
            transit.append({"waypoint_id": wp.waypoint_id, "role": "RETURN_ENDPOINT", "local": [round(x, 3), round(y, 3)]})
            continue
        oid = f"A{len(objectives) + 1}"
        sem = waypoint_semantics.get(wp.waypoint_id)
        action = sem["action"] if sem else wp.action
        sensor = sem["sensor"] if sem else (sensor_by_action or {}).get(wp.action)
        name = sem["original_waypoint_id"] if sem else wp.waypoint_id
        objectives.append({"objective_id": oid, "point_id": None, "coordinates": [round(x, 3), round(y, 3)],
                           "required_sensor": sensor, "description": f"{action} at waypoint {name}"})
        fields[f"aerial_objectives.{oid}"] = {"source": source["kind"], "objective_id": oid, "waypoint_id": wp.waypoint_id,
                                              "original_waypoint_id": sem["original_waypoint_id"] if sem else None,
                                              "action": action, "geo": [wp.latitude, wp.longitude],
                                              "local": [round(x, 3), round(y, 3)],
                                              "sensor": ("SEMANTICS_MANIFEST" if sem and sensor else
                                                         "DECLARED_MAPPING" if sensor else "NOT_STATED_IN_INPUT"),
                                              "frame": frame.frame_id, "georeference": geo.verification}
        if sensor is None:
            findings.append({"kind": "SENSOR_NOT_STATED", "field": f"aerial_objectives.{oid}",
                             "detail": f"waypoint action {wp.action!r} names no sensor", "action": "KEPT_UNSTATED"})
    drones = []
    vid = md.vehicle.vehicle_id
    if vid in declared_drones:
        drones = [vid]
        fields["drones"] = {"source": source["kind"], "value": vid}
    else:
        fields["drones"] = {"source": "OMITTED", "note": f"plan vehicle {vid!r} is not a declared drone; the drone agent "
                                                         "proposes the assignment"}
        findings.append({"kind": "VEHICLE_NOT_IN_FLEET", "field": "drones", "detail": vid, "action": "NOT_USED"})
    fields["import_context"] = {"source": "IMPORT_CONTEXT (not an operator statement; not used)",
                                "battery_percent": md.vehicle.battery_percent, "wind_speed_kmh": md.environment.wind_speed_kmh}
    if not objectives:
        findings.append({"kind": "NO_OBJECTIVE", "detail": "the input has no waypoint", "action": "ASK_OPERATOR"})
    brief = {"schema": BRIEF_SCHEMA_V2, "aerial_objectives": objectives, "ground_objectives": [], "drones": drones,
             "rover": None, "wind_speed_kmh": None, "battery_percent": {}, "altitude_m": None, "vehicle_availability": [],
             "unsafe_requests": [], "contradictions": [], "ambiguities": []}
    parse_brief(brief)  # the common contract, validated
    out = _result(source, brief, findings, fields)
    out["transit_waypoints"] = transit
    return out


def from_qgc_plan(path: Path, *, site, context, import_context, sensor_by_action: dict | None = None,
                  waypoint_semantics: dict | None = None) -> dict:
    from inputs.qgroundcontrol_adapter import load_qgroundcontrol_plan
    source = {"kind": "QGC_PLAN", "path": str(path), "sha256": None,
              "importer": "inputs.qgroundcontrol_adapter.load_qgroundcontrol_plan (Hermes)"}
    try:
        data = Path(path).read_bytes()
        source["sha256"] = hashlib.sha256(data).hexdigest()
        imported = load_qgroundcontrol_plan(str(path), import_context)
    except (OSError, ValueError) as exc:  # Hermes' structural checks (pydantic's ValidationError is a ValueError)
        detail = " ".join(str(exc).split())[:240]
        return _result(source, None, [{"kind": "QGC_PLAN_INVALID", "detail": f"{type(exc).__name__}: {detail}",
                                       "action": "REJECTED"}], {})
    source.update(importer_warnings=list(imported.warnings), source_item_count=imported.source_item_count)
    out = from_mission_definition(imported.mission, site=site, context=context, source=source,
                                  sensor_by_action=sensor_by_action, waypoint_semantics=waypoint_semantics)
    skipped = [w for w in imported.warnings if w.startswith("Skipped")]
    if skipped and out["status"] != "REJECTED":
        # an item the importer dropped may have been an objective: the operator must confirm the mission
        out["findings"] += [{"kind": "QGC_ITEM_SKIPPED_BY_IMPORTER", "detail": w, "action": "ASK_OPERATOR"} for w in skipped]
        out["status"] = "NEEDS_CLARIFICATION"
    return out


def from_natural_language(text: str) -> dict:
    """Natural language is interpreted by the Mission Orchestrator (provenance contract); this only records the source
    and, for comparison, what Hermes' deterministic parser extracts from the same text."""
    from planning.deterministic_plan_parser import parse_deterministic_plan_fields
    hermes = parse_deterministic_plan_fields(text).model_dump(exclude_none=True)
    return {"schema": SCHEMA, "status": "TO_INTERPRET", "source": {"kind": "NATURAL_LANGUAGE",
            "sha256": hashlib.sha256(text.encode()).hexdigest()}, "text": text, "brief": None,
            "hermes_deterministic_fields": hermes}


def _result(source, brief, findings, fields) -> dict:
    rejected = any(f["action"] == "REJECTED" for f in findings)
    ask = any(f["action"] == "ASK_OPERATOR" for f in findings)
    return {"schema": SCHEMA, "status": "REJECTED" if rejected else ("NEEDS_CLARIFICATION" if ask else "OK"),
            "source": source, "brief": brief, "findings": findings, "provenance": fields}


class StructuredInterpreter:
    """Feeds a brief built from a structured input to the Mission Orchestrator, so the SAME validators and agents run.
    It is labelled with its source; it is not a model and never claims to be one."""

    def __init__(self, mission_input: dict):
        self.mission_input = mission_input
        self.info = {"provider": "structured-input", "model": mission_input["source"]["kind"],
                     "data_kind": "DETERMINISTIC", "source": mission_input["source"]}

    def interpret(self, text):
        return parse_brief(self.mission_input["brief"]), {**self.info, "mission_input": {
            k: self.mission_input[k] for k in ("status", "findings", "provenance")}}
