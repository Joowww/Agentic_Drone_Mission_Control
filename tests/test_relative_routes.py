"""Offline geometry references use great-circle distance/bearing, not the mapper inverse."""
import importlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from models.mission_plan_draft import MissionPlanDraft
from planning.relative_routes import RelativeRouteRequest, generate_relative_route
import tools.hermes_mission_planning as planning
from tools.route_geometry import haversine_distance_km, calculate_initial_bearing_deg


def rectangle(**changes):
    values = dict(mode="rectangle", home_latitude=41, home_longitude=2,
                  home_altitude_m=0, altitude_reference="relative_to_home", altitude_m=10,
                  return_to_home=True, close_route=False, length_m=100, width_m=50,
                  orientation_deg=0, traversal="clockwise", home_position="corner")
    values.update(changes)
    return RelativeRouteRequest(**values)


def offsets(points, **changes):
    values = rectangle().model_dump(exclude_none=True)
    for key in ("length_m", "width_m", "orientation_deg", "traversal", "home_position"):
        values.pop(key)
    values.update(mode="offsets", offsets=points, **changes)
    return RelativeRouteRequest(**values)


@pytest.mark.parametrize("latitude,heading", [(0, 0), (41, 90), (-41, 180), (74, 270)])
def test_rectangle_edges_against_spherical_reference(latitude, heading):
    result = generate_relative_route(rectangle(home_latitude=latitude, orientation_deg=heading))
    points = [{"latitude": latitude, "longitude": 2}] + result["waypoints"]
    # 111320 m/degree is an approximation to a sphere/ellipsoid. At <=1 km,
    # <=75 degrees, 0.5% distance and 0.05 degrees heading cover this local model.
    for i, expected in enumerate((100, 50, 100)):
        a, b = points[i:i + 2]
        distance = 1000 * haversine_distance_km(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
        assert distance == pytest.approx(expected, rel=0.005)
        bearing = calculate_initial_bearing_deg(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
        target = (heading + 90 * i) % 360
        assert abs((bearing - target + 180) % 360 - 180) < 0.05


def test_order_center_closure_and_offsets():
    cw = generate_relative_route(rectangle(home_position="center", close_route=True))
    ccw = generate_relative_route(rectangle(home_position="center", traversal="counterclockwise"))
    assert len(cw["waypoints"]) == 5
    assert cw["effective_offsets"][0] == {"north_m": -50, "east_m": -25}
    assert cw["effective_offsets"][1] == {"north_m": 50, "east_m": -25}
    assert ccw["effective_offsets"][1] == {"north_m": -50, "east_m": 25}
    assert cw["effective_offsets"][0] == cw["effective_offsets"][-1]
    sequence = [dict(north_m=100, east_m=0), dict(north_m=100, east_m=100), dict(north_m=0, east_m=100)]
    result = generate_relative_route(offsets(sequence, close_route=True, return_to_home=False))
    assert result["effective_offsets"] == sequence + [sequence[0]]
    assert all(w["altitude_m"] == 10 and w["action"] == "navigate" for w in result["waypoints"])
    diagonal = result["waypoints"][1]
    distance = 1000 * haversine_distance_km(41, 2, diagonal["latitude"], diagonal["longitude"])
    assert distance == pytest.approx(2 ** .5 * 100, rel=.005)


def test_offset_at_local_domain_edge_against_independent_distance_bearing():
    result = generate_relative_route(offsets([dict(north_m=600, east_m=800)], home_latitude=74))
    point = result["waypoints"][0]
    distance = 1000 * haversine_distance_km(74, 2, point["latitude"], point["longitude"])
    assert distance == pytest.approx(1000, rel=.005)
    heading = calculate_initial_bearing_deg(74, 2, point["latitude"], point["longitude"])
    assert heading == pytest.approx(53.130102, abs=.05)


def test_clockwise_corner_starts_on_length_edge_without_home_duplicate():
    open_route = generate_relative_route(rectangle())
    assert len(open_route["waypoints"]) == 3
    assert open_route["effective_offsets"] == [
        dict(north_m=100, east_m=0), dict(north_m=100, east_m=50), dict(north_m=0, east_m=50)]
    closed = generate_relative_route(rectangle(close_route=True))
    assert closed["effective_offsets"][-1] == dict(north_m=0, east_m=0)


def test_missing_decisions_are_pending_without_defaults():
    result = generate_relative_route(RelativeRouteRequest(mode="rectangle", length_m=20, width_m=10))
    assert result["status"] == "INCOMPLETE"
    assert {"orientation_deg", "home_position", "traversal", "close_route", "return_to_home",
            "altitude_reference"}.issubset(result["missing_fields"])
    assert "waypoints" not in result


@pytest.mark.parametrize("changes", [
    {"length_m": 0}, {"width_m": -1}, {"altitude_m": float("inf")},
    {"orientation_deg": float("nan")}, {"orientation_deg": 360}, {"home_latitude": 91},
    {"altitude_reference": "AMSL"}, {"unexpected": True},
])
def test_invalid_typed_parameters(changes):
    with pytest.raises(ValidationError):
        rectangle(**changes)


@pytest.mark.parametrize("changes", [
    {"home_latitude": 76}, {"home_altitude_m": 10}, {"length_m": .001},
    {"length_m": 1001}, {"home_latitude": 75},
    {"home_longitude": 179.9999, "orientation_deg": 90},
    {"offsets": [dict(north_m=1, east_m=0)]},
])
def test_unsupported_domains_and_degenerate_rectangle(changes):
    with pytest.raises(ValueError):
        generate_relative_route(rectangle(**changes))


@pytest.mark.parametrize("points", [
    [dict(north_m=0, east_m=0)],
    [dict(north_m=10, east_m=0)] * 2,
    [dict(north_m=1000, east_m=1)],
    [dict(north_m=10, east_m=0), dict(north_m=20, east_m=0), dict(north_m=10, east_m=0)],
])
def test_invalid_offsets(points):
    with pytest.raises(ValueError):
        generate_relative_route(offsets(points))


@pytest.fixture
def drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(planning, "DRAFT_ROOT", tmp_path)
    return tmp_path


def test_generate_replace_preserve_version_finalize(drafts):
    values = MissionPlanDraft(name="Rectangle", vehicle_type="multirotor", autopilot="ArduPilot",
        cruise_speed_kmh=20, battery_percent=95, battery_consumption_percent_per_minute=.8,
        objective_type="transit", objective_target="field", wind_speed_kmh=0,
        wind_direction_from="north", minimum_battery_reserve_percent=20,
        maximum_wind_speed_kmh=30, maximum_altitude_m=50)
    first = planning.update_mission_draft(values)
    draft_id = first["draft_id"]
    pending = planning.generate_draft_route(draft_id, first["draft_revision"], RelativeRouteRequest(mode="rectangle"))
    assert pending["geometry_intent"]["mode"] == "rectangle"
    assert pending["draft_revision"] == first["draft_revision"] + 1
    assert pending["draft"]["waypoints"] == []
    result = planning.generate_draft_route(draft_id, pending["draft_revision"], rectangle(close_route=True))
    assert result["status"] == "COMPLETE" and len(result["draft"]["waypoints"]) == 4
    assert result["draft"]["battery_percent"] == 95 and result["draft"]["name"] == "Rectangle"
    version = result["draft_revision"]
    assert planning.generate_draft_route(draft_id, first["draft_revision"], rectangle(), True)["status"] == "CONFLICT"
    assert planning.generate_draft_route(draft_id, version, rectangle())["status"] == "CONFLICT"
    replaced = planning.generate_draft_route(draft_id, version, rectangle(), True)
    assert len(replaced["draft"]["waypoints"]) == 3  # Closing corner removed, not left by merge
    final = planning.finalize_mission_draft(draft_id, replaced["draft_revision"])
    assert final["validation"]["execution_status"] == "APPROVED"
    assert final["validation"]["qgc_plan_path"].endswith(".plan")
    sidecar = json.loads(next(drafts.rglob("finalization.json")).read_text())
    assert sidecar["draft_sha256"] == replaced["draft_sha256"]
    assert sidecar["route_provenance"]["parameters"]["close_route"] is False
    assert sidecar["flight_consent"] == "NOT_GRANTED"
    assert planning.update_mission_draft(MissionPlanDraft(name="stale"), draft_id, version)["status"] == "CONFLICT"
    assert planning.finalize_mission_draft(draft_id, version)["status"] == "CONFLICT"


def test_serialized_legacy_merges_and_metadata_integrity(drafts, monkeypatch):
    first = planning.update_mission_draft(MissionPlanDraft(name="Keep"))
    draft_id = first["draft_id"]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda update: planning.update_mission_draft(update, draft_id), [
            MissionPlanDraft(battery_percent=80), MissionPlanDraft(wind_speed_kmh=5)]))
    assert all(result["status"] != "ERROR" for result in results)
    # Reload is process-independent disk recovery, without recreating the draft.
    importlib.reload(planning)
    monkeypatch.setattr(planning, "DRAFT_ROOT", drafts)
    saved = planning.update_mission_draft(MissionPlanDraft(), draft_id)
    assert saved["draft"]["battery_percent"] == 80 and saved["draft"]["wind_speed_kmh"] == 5
    assert saved["draft_revision"] == 3
    path = drafts / draft_id / "draft.json"
    path.write_text(path.read_text().replace('"Keep"', '"Changed"'))
    assert planning.update_mission_draft(MissionPlanDraft(), draft_id)["status"] == "ERROR"
