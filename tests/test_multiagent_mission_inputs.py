"""Mission inputs -> one common contract: QGC .plan through Hermes' own exporter/importer, a structured
MissionDefinition, and natural language (the supervisor's job; Hermes' deterministic parser for comparison)."""
import json
from pathlib import Path

import pytest

from models.mission_definition import MissionDefinition
from models.qgc_import import QGroundControlImportContext
from planning.site_geometry import local_to_geo
from multiagent import integrated_mission as im, mission_inputs as mi
from multiagent.orchestrator import MissionOrchestrator
from multiagent.tracing import Tracer

CTX = im.load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
G = SITE.geo_reference
IC = QGroundControlImportContext(battery_percent=90, battery_consumption_percent_per_minute=1.0, wind_speed_kmh=0,
                                 wind_direction_from_deg=0, minimum_battery_reserve_percent=20, maximum_wind_speed_kmh=30,
                                 maximum_altitude_m=50)


def geo(pid):
    p = SITE.point(pid)
    return local_to_geo(p.x_m, p.y_m, origin_latitude=G.latitude, origin_longitude=G.longitude, y_axis_bearing_deg=0.0)


def mission(points, vehicle="qgc_vehicle"):
    base = json.loads((Path(mi.__file__).parents[1] / "missions/examples/agri_demo_001_sector_b.json").read_text())
    hl, hn = geo("TAKEOFF_B")
    base["vehicle"]["vehicle_id"] = vehicle
    base["route"] = {"mode": "waypoints", "home": {"latitude": hl, "longitude": hn, "altitude_m": 0.0},
                     "waypoints": [{"waypoint_id": p, "latitude": geo(p)[0], "longitude": geo(p)[1], "altitude_m": 5.0,
                                    "speed_kmh": 10.0, "action": "navigate"} for p in points], "return_to_home": True}
    return MissionDefinition.model_validate(base)


def plan(result):
    return MissionOrchestrator(CTX, mi.StructuredInterpreter(result), tracer=Tracer(mission_id="i"), pipeline="v2",
                               safety_policy="safety/4").run("structured mission input")


def test_a_qgc_plan_round_trips_through_hermes_exporter_and_importer_into_the_multiagent_plan(tmp_path):
    from inputs.qgroundcontrol_exporter import export_qgroundcontrol_plan
    path = export_qgroundcontrol_plan(mission(["POI_1", "POI_3"]), tmp_path / "m.plan", planned_home_amsl_m=584.0)
    r = mi.from_qgc_plan(path, site=SITE, context=CTX, import_context=IC)
    assert r["status"] == "OK" and r["source"]["kind"] == "QGC_PLAN" and len(r["source"]["sha256"]) == 64
    assert [o["coordinates"] for o in r["brief"]["aerial_objectives"]] == [[-4.0, 5.0], [8.0, 4.0]]
    assert r["transit_waypoints"][-1]["role"] == "RETURN_ENDPOINT"     # LAND/RTL is not an objective
    assert {f["kind"] for f in r["findings"]} >= {"SENSOR_NOT_STATED", "VEHICLE_NOT_IN_FLEET"}
    p = plan(r)
    assert p["status"] == "PROPOSED_PENDING_AUTHORIZATION"
    assert sorted(pt for t in p["aerial"]["proposals"] for pt in t["poi_sequence"]) == ["POI_1", "POI_3"]
    assert p["commands_sent"] == 0


def test_a_structured_mission_definition_and_a_declared_drone():
    r = mi.from_mission_definition(mission(["POI_3"], vehicle="drone_02"), site=SITE, context=CTX,
                                   source={"kind": "MISSION_DEFINITION"}, sensor_by_action={"navigate": "multispectral"})
    assert r["brief"]["drones"] == ["drone_02"] and r["provenance"]["drones"]["source"] == "MISSION_DEFINITION"
    assert r["provenance"]["aerial_objectives.A1"]["sensor"] == "DECLARED_MAPPING"
    assert plan(r)["status"] == "PROPOSED_PENDING_AUTHORIZATION"


def test_an_undeclared_point_is_left_to_the_planner_and_asks_for_clarification():
    md = mission(["POI_1"])
    md.route.waypoints[0].latitude += 0.0002  # ~22 m north of POI_1: not a declared point
    r = mi.from_mission_definition(md, site=SITE, context=CTX, source={"kind": "MISSION_DEFINITION"})
    assert r["status"] == "OK"
    p = plan(r)
    assert p["status"] == "NEEDS_CLARIFICATION" and any("COORDINATES_NOT_A_DECLARED_SITE_POINT" in x for x in p["reasons"])


def test_a_mission_of_another_site_is_rejected_with_a_structured_finding():
    md = MissionDefinition.model_validate(json.loads((Path(mi.__file__).parents[1] /
                                                      "missions/examples/agri_demo_001_sector_b.json").read_text()))
    r = mi.from_mission_definition(md, site=SITE, context=CTX, source={"kind": "MISSION_DEFINITION"})
    assert r["status"] == "REJECTED" and r["findings"][0]["kind"] == "OUTSIDE_SITE_GEOREFERENCE" and r["brief"] is None


def test_the_import_context_is_not_an_operator_statement(tmp_path):
    r = mi.from_mission_definition(mission(["POI_1"]), site=SITE, context=CTX, source={"kind": "MISSION_DEFINITION"})
    assert r["brief"]["battery_percent"] == {} and r["brief"]["wind_speed_kmh"] is None
    assert "not an operator statement" in r["provenance"]["import_context"]["source"]


def test_natural_language_goes_to_the_supervisor_and_hermes_parser_is_recorded_for_comparison():
    r = mi.from_natural_language("Survey POI_3 with drone_02 and return home.")
    assert r["status"] == "TO_INTERPRET" and r["brief"] is None and r["source"]["kind"] == "NATURAL_LANGUAGE"
    assert isinstance(r["hermes_deterministic_fields"], dict)


def test_hermes_exporter_refuses_non_navigation_actions(tmp_path):
    from inputs.qgc_plan_export import ExportRefused
    from inputs.qgroundcontrol_exporter import export_qgroundcontrol_plan
    md = mission(["POI_1"])
    md.route.waypoints[0].action = "take_photo"
    with pytest.raises(ExportRefused):
        export_qgroundcontrol_plan(md, tmp_path / "x.plan", planned_home_amsl_m=584.0)


def _exported(tmp_path):
    from inputs.qgroundcontrol_exporter import export_qgroundcontrol_plan
    path = export_qgroundcontrol_plan(mission(["POI_1", "POI_3"]), tmp_path / "ok.plan", planned_home_amsl_m=584.0)
    return json.loads(path.read_text())


def _nav_item(plan):  # the first navigation waypoint (command 16)
    return next(i for i in plan["mission"]["items"] if i.get("command") == 16)


@pytest.mark.parametrize("case", ["not_json", "empty", "wrong_file_type", "no_items", "null_latitude",
                                  "latitude_out_of_range", "latitude_string", "missing_file"])
def test_a_structurally_invalid_plan_is_a_structured_rejection_not_an_exception(tmp_path, case):
    plan = _exported(tmp_path)
    if case == "wrong_file_type":
        plan["fileType"] = "GeoFence"
    elif case == "no_items":
        plan["mission"]["items"] = []
    elif case == "null_latitude":
        _nav_item(plan)["params"][4] = None
    elif case == "latitude_out_of_range":
        _nav_item(plan)["params"][4] = 95.0
    elif case == "latitude_string":
        _nav_item(plan)["params"][4] = "NaN"
    path = tmp_path / f"{case}.plan"
    if case != "missing_file":
        raw = {"not_json": "{nope", "empty": ""}
        path.write_text(raw[case] if case in raw else json.dumps(plan))
    r = mi.from_qgc_plan(path, site=SITE, context=CTX, import_context=IC)
    assert r["status"] == "REJECTED" and r["brief"] is None
    assert r["findings"][0]["kind"] == "QGC_PLAN_INVALID" and r["findings"][0]["detail"]


def test_an_item_the_importer_skips_makes_the_operator_confirm_the_mission(tmp_path):
    plan = _exported(tmp_path)
    _nav_item(plan)["command"] = 31000           # unknown to the importer: it drops the item with a warning
    path = tmp_path / "skipped.plan"
    path.write_text(json.dumps(plan))
    r = mi.from_qgc_plan(path, site=SITE, context=CTX, import_context=IC)
    assert r["status"] == "NEEDS_CLARIFICATION"
    assert any(f["kind"] == "QGC_ITEM_SKIPPED_BY_IMPORTER" and "31000" in f["detail"] for f in r["findings"])
    assert len(r["brief"]["aerial_objectives"]) == 1   # what remains is kept, nothing is invented in its place
