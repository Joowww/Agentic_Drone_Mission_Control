"""What a .plan can carry, the semantics manifest for what it cannot, and loss detection on the round trip through
Hermes' own exporter and importer (unchanged). Nothing is invented; nothing is lost silently."""
import json
from pathlib import Path

import pytest

from models.mission_definition import MissionDefinition
from models.qgc_import import QGroundControlImportContext
from planning.site_geometry import MAX_RADIUS_M, geo_to_local, local_to_geo
from multiagent import integrated_mission as im, mission_inputs as mi, plan_semantics as ps
from multiagent.orchestrator import MissionOrchestrator
from multiagent.tracing import Tracer

CTX = im.load_context(im.CONTEXT)
SITE, _ = im._site_fleet(CTX)
G = SITE.geo_reference
IC = QGroundControlImportContext(battery_percent=90, battery_consumption_percent_per_minute=1.0, wind_speed_kmh=0,
                                 wind_direction_from_deg=0, minimum_battery_reserve_percent=20, maximum_wind_speed_kmh=30,
                                 maximum_altitude_m=50)
SENSORS = {"POI_1": "rgb", "POI_3": "multispectral"}


def geo(pid):
    p = SITE.point(pid)
    return local_to_geo(p.x_m, p.y_m, origin_latitude=G.latitude, origin_longitude=G.longitude, y_axis_bearing_deg=0.0)


def mission(actions):
    base = json.loads((Path(mi.__file__).parents[1] / "missions/examples/agri_demo_001_sector_b.json").read_text())
    hl, hn = geo("TAKEOFF_B")
    base["vehicle"]["vehicle_id"] = "qgc_vehicle"
    base["route"] = {"mode": "waypoints", "home": {"latitude": hl, "longitude": hn, "altitude_m": 0.0},
                     "waypoints": [{"waypoint_id": p, "latitude": geo(p)[0], "longitude": geo(p)[1], "altitude_m": 5.0,
                                    "speed_kmh": 10.0, "action": a} for p, a in actions], "return_to_home": True}
    return MissionDefinition.model_validate(base)


MD = mission([("POI_1", "take_photo"), ("POI_3", "navigate")])


def test_what_cannot_be_represented_is_listed_and_nothing_is_written_without_consent(tmp_path):
    r = ps.export_with_manifest(MD, tmp_path / "m.plan", planned_home_amsl_m=584.0, sensors=SENSORS)
    assert r["status"] == "REFUSED_SEMANTIC_LOSS" and list(tmp_path.iterdir()) == []
    rows = {(x["waypoint_id"], x["field"], x["value"]) for x in r["not_representable"]}
    assert rows == {("POI_1", "action", "take_photo"), ("POI_1", "sensor", "rgb"), ("POI_3", "sensor", "multispectral")}
    assert "camera instance" in next(x["why"] for x in r["not_representable"] if x["field"] == "action")


def test_round_trip_with_the_manifest_restores_every_field_and_plans(tmp_path):
    r = ps.export_with_manifest(MD, tmp_path / "m.plan", planned_home_amsl_m=584.0, sensors=SENSORS,
                                accept_navigation_only=True)
    assert r["status"] == "EXPORTED_WITH_MANIFEST" and Path(r["manifest"]).is_file()
    back = ps.import_with_manifest(Path(r["plan"]), Path(r["manifest"]), site=SITE, context=CTX, import_context=IC)
    assert back["semantics"]["status"] == "MANIFEST_APPLIED" and back["status"] == "OK"
    assert ps.semantic_loss(MD, SENSORS, back) == []
    assert [o["required_sensor"] for o in back["brief"]["aerial_objectives"]] == ["rgb", "multispectral"]
    assert back["provenance"]["aerial_objectives.A1"]["sensor"] == "SEMANTICS_MANIFEST"
    p = MissionOrchestrator(CTX, mi.StructuredInterpreter(back), tracer=Tracer(mission_id="s"), pipeline="v2",
                            safety_policy="safety/4").run("structured mission input")
    assert p["status"] == "PROPOSED_PENDING_AUTHORIZATION" and p["commands_sent"] == 0


def test_without_the_manifest_the_loss_is_detected_field_by_field(tmp_path):
    r = ps.export_with_manifest(MD, tmp_path / "m.plan", planned_home_amsl_m=584.0, sensors=SENSORS,
                                accept_navigation_only=True)
    back = ps.import_with_manifest(Path(r["plan"]), None, site=SITE, context=CTX, import_context=IC)
    assert back["semantics"]["status"] == "NO_MANIFEST"
    loss = {(x["waypoint_id"], x["field"], x["intended"], x["arrived"]) for x in ps.semantic_loss(MD, SENSORS, back)}
    assert loss == {("POI_1", "waypoint_id", "POI_1", "QGC_WP1"), ("POI_1", "action", "take_photo", "navigate"),
                    ("POI_1", "sensor", "rgb", None), ("POI_3", "waypoint_id", "POI_3", "QGC_WP2"),
                    ("POI_3", "sensor", "multispectral", None)}


def test_a_changed_plan_or_a_mismatched_manifest_is_refused_and_asks_the_operator(tmp_path):
    r = ps.export_with_manifest(MD, tmp_path / "m.plan", planned_home_amsl_m=584.0, sensors=SENSORS,
                                accept_navigation_only=True)
    plan, manifest = Path(r["plan"]), Path(r["manifest"])
    m = json.loads(manifest.read_text())
    m["waypoints"][1]["latitude"] += 0.001                    # the manifest describes another point
    bad = tmp_path / "bad.semantics.json"
    bad.write_text(json.dumps(m))
    out = ps.import_with_manifest(plan, bad, site=SITE, context=CTX, import_context=IC)
    assert out["semantics"]["status"] == "MANIFEST_REFUSED" and out["status"] == "NEEDS_CLARIFICATION"
    assert any(p.startswith("MANIFEST_WAYPOINT_MISMATCH: POI_3") for p in out["semantics"]["problems"])
    data = json.loads(plan.read_text())
    data["mission"]["cruiseSpeed"] += 0.5                     # the .plan changed after the manifest was written
    plan.write_text(json.dumps(data))
    out = ps.import_with_manifest(plan, manifest, site=SITE, context=CTX, import_context=IC)
    assert out["semantics"]["problems"] == ["MANIFEST_PLAN_MISMATCH: the .plan is not the file this manifest describes"]
    assert all(o["required_sensor"] is None for o in out["brief"]["aerial_objectives"])   # nothing re-attached


def test_a_navigation_only_mission_loses_only_the_waypoint_names(tmp_path):
    md = mission([("POI_1", "navigate"), ("POI_3", "navigate")])
    r = ps.export_with_manifest(md, tmp_path / "n.plan", planned_home_amsl_m=584.0)
    assert {x["field"] for x in r["not_representable_in_plan"]} == {"waypoint_id"}
    back = ps.import_with_manifest(Path(r["plan"]), Path(r["manifest"]), site=SITE, context=CTX, import_context=IC)
    assert ps.semantic_loss(md, None, back) == []


@pytest.mark.parametrize("action", ["take_photo", "loiter", "survey", "inspect"])
def test_every_non_navigation_action_has_a_stated_reason_and_hermes_still_refuses_it(tmp_path, action):
    from inputs.qgc_plan_export import ExportRefused
    from inputs.qgroundcontrol_exporter import export_qgroundcontrol_plan
    md = mission([("POI_1", action)])
    assert ps.representability(md)[0]["why"] == ps.WHY[action]
    with pytest.raises(ExportRefused):
        export_qgroundcontrol_plan(md, tmp_path / "x.plan", planned_home_amsl_m=584.0)


def test_geo_to_local_alone_has_no_radius_check_and_the_adapter_does_not_hide_it():
    far_lat = G.latitude + 0.05                                # ~5.5 km north of the site origin
    x, y = geo_to_local(far_lat, G.longitude, origin_latitude=G.latitude, origin_longitude=G.longitude,
                        y_axis_bearing_deg=0.0)
    assert (x * x + y * y) ** 0.5 > MAX_RADIUS_M               # the limitation, as it is today in planning/
    md = mission([("POI_1", "navigate")])
    md.route.waypoints[0].latitude = far_lat
    r = mi.from_mission_definition(md, site=SITE, context=CTX, source={"kind": "MISSION_DEFINITION"})
    assert r["status"] == "REJECTED" and r["findings"][0]["kind"] == "OUTSIDE_SITE_GEOREFERENCE"
