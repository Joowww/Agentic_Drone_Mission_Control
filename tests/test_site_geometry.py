import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.fleet import Fleet, FleetVehicle
from models.site import Site
from planning.relative_routes import RelativeRouteRequest, generate_relative_route
from planning.site_geometry import (
    BOUNDARY, INSIDE, OUTSIDE, geo_to_local, local_to_geo, local_to_north_east, point_location, polygon_problems,
    segment_clearance, segment_within,
)
from planning.site_validation import validate_aerial_route, validate_ground_route, validate_site

SITES = Path("missions/sites")
SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]
U_SHAPE = [[0, 0], [10, 0], [10, 10], [7, 10], [7, 3], [3, 3], [3, 10], [0, 10]]


def _site(name="synthetic_orchard_v1.site.json") -> dict:
    return json.loads((SITES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("polygon, fragment", [
    ([[0, 0], [1, 0]], "at least 3"),
    ([[0, 0], [10, 10], [10, 0], [0, 10]], "self-intersection"),
    ([[0, 0], [5, 0], [10, 0]], "degenerate"),
    ([[0, 0], [10, 0], [10, 10], [0, 0]], "open ring"),
    ([[0, 0], [10, 0], [5, 0], [5, 5]], "overlap"),
    ([[0, 0], [float("nan"), 0], [1, 1]], "finite"),
])
def test_polygon_problems_reject_unsupported_shapes(polygon, fragment):
    assert any(fragment in p for p in polygon_problems(polygon))


def test_simple_polygons_have_no_problems():
    assert polygon_problems(SQUARE) == [] and polygon_problems(U_SHAPE) == []


def test_point_location_and_boundary():
    assert point_location((5, 5), SQUARE) == INSIDE
    assert point_location((10, 5), SQUARE) == BOUNDARY
    assert point_location((11, 5), SQUARE) == OUTSIDE
    assert point_location((5, 5), U_SHAPE) == OUTSIDE  # the notch


def test_segment_with_inside_endpoints_can_leave_a_concave_polygon():
    assert point_location((1, 8), U_SHAPE) == INSIDE and point_location((9, 8), U_SHAPE) == INSIDE
    assert segment_within((1, 8), (9, 8), U_SHAPE) == OUTSIDE
    assert segment_within((1, 1), (9, 1), U_SHAPE) == INSIDE
    assert segment_within((0, 1), (9, 1), U_SHAPE) == BOUNDARY


def test_segment_crossing_an_exclusion_with_both_endpoints_outside():
    exclusion = [[4, -1], [6, -1], [6, 1], [4, 1]]
    assert segment_clearance((0, 0), (10, 0), exclusion) == 0
    assert segment_clearance((0, 3), (10, 3), exclusion) == pytest.approx(2.0)


def test_frame_axes_and_round_trip():
    assert local_to_north_east(0, 1, 0) == pytest.approx((1, 0))      # +y = north
    assert local_to_north_east(1, 0, 0) == pytest.approx((0, 1))      # +x = east
    assert local_to_north_east(0, 1, 90) == pytest.approx((0, 1))     # +y = east when rotated 90
    assert local_to_north_east(1, 0, 90) == pytest.approx((-1, 0))   # +x then points south
    reference = {"origin_latitude": 41.275, "origin_longitude": 1.987, "y_axis_bearing_deg": 30.0}
    for xy in [(0, 0), (12.5, -7.25), (-300, 450)]:
        lat, lon = local_to_geo(*xy, **reference)
        assert geo_to_local(lat, lon, **reference) == pytest.approx(xy, abs=1e-6)


def test_frame_conversion_matches_the_existing_relative_route_method():
    request = RelativeRouteRequest(mode="offsets", home_latitude=41.275, home_longitude=1.987, home_altitude_m=0,
                                   altitude_reference="relative_to_home", altitude_m=5, return_to_home=True,
                                   close_route=False, offsets=[{"north_m": 8, "east_m": -4}])
    expected = generate_relative_route(request)["waypoints"][0]
    assert local_to_geo(-4, 8, origin_latitude=41.275, origin_longitude=1.987, y_axis_bearing_deg=0) == (
        pytest.approx(expected["latitude"], abs=1e-12), pytest.approx(expected["longitude"], abs=1e-12))


def test_conversion_refuses_points_outside_the_local_model():
    with pytest.raises(ValueError, match="radius"):
        local_to_geo(900, 900, origin_latitude=0, origin_longitude=0, y_axis_bearing_deg=0)
    with pytest.raises(ValueError, match="domain"):
        local_to_geo(0, 0, origin_latitude=80, origin_longitude=0, y_axis_bearing_deg=0)


def test_synthetic_site_is_valid_but_never_a_field_site():
    report = validate_site(Site.model_validate(_site()))
    assert report["status"] == "VALID" and report["capabilities"]["sitl_geographic_export"]
    assert not report["capabilities"]["field_export"]
    assert "SYNTHETIC site: never a proposal for hardware" in report["export_blocks"]["field"]


def test_dronelab_template_lists_missing_data_and_enables_nothing():
    site = Site.model_validate(_site("dronelab.template.site.json"))
    report = validate_site(site)
    assert report["status"] == "INCOMPLETE" and not any(report["capabilities"].values())
    assert "zone PERIMETER.polygon" in report["missing"] and "point POI_1.x_m/y_m" in report["missing"]
    assert set(report["geographic_references"]["missing"]) == {
        "geo_reference.latitude/longitude", "local_frame.y_axis_bearing_deg", "vertical_reference.origin_ground_amsl_m"}
    assert "PLANTILLA" in site.name and site.status == "TEMPLATE_PENDING_MEASUREMENT"


def test_filled_template_still_cannot_export_while_its_status_is_template():
    data = _site()
    data.update(status="TEMPLATE_PENDING_MEASUREMENT", provenance={"kind": "TEMPLATE"})
    report = validate_site(Site.model_validate(data))
    assert not report["capabilities"]["sitl_geographic_export"]


@pytest.mark.parametrize("key", ["holes", "radius_m"])
def test_unsupported_geometry_is_rejected_explicitly(key):
    data = _site()
    data["exclusions"][0][key] = [[1, 1], [2, 1], [2, 2]] if key == "holes" else 3.0
    with pytest.raises(ValidationError, match="UNSUPPORTED_GEOMETRY"):
        Site.model_validate(data)


def test_site_errors_are_reported():
    data = _site()
    next(p for p in data["points"] if p["point_id"] == "TAKEOFF_A")["x_m"] = 30.0  # outside PAD_A
    next(p for p in data["points"] if p["point_id"] == "POI_2")["x_m"] = 100.0     # outside the perimeter
    data["exclusions"][1]["polygon"] = [[0, 0], [10, 10], [10, 0], [0, 10]]
    data["provenance"]["kind"] = "MEASURED"
    errors = validate_site(Site.model_validate(data))["errors"]
    assert any("TAKEOFF_A: not strictly inside zone PAD_A" in e for e in errors)
    assert any("POI_2: not strictly inside the operation perimeter" in e for e in errors)
    assert any("SHED: self-intersection" in e for e in errors)
    assert any("requires provenance.kind SYNTHETIC" in e for e in errors)


def test_unknown_references_fail_the_route():
    site = Site.model_validate(_site())
    result = validate_aerial_route(site, "TAKEOFF_A", ["POI_404"], 5, 1.0)
    assert result["status"] == "FAIL" and "POI_404" in result["checks"][0]["detail"]


def test_route_with_valid_endpoints_through_an_exclusion_fails():
    site = Site.model_validate(_site())
    result = validate_aerial_route(site, "TAKEOFF_B", ["POI_3", "POI_5"], 5, 1.0)
    assert result["status"] == "FAIL"
    failed = [c["check"] for c in result["checks"] if c["status"] == "FAIL"]
    assert "exclusion TREE_ROW_1 POI_3 -> POI_5" in failed


def test_declared_margin_is_applied_and_never_accredited_without_inputs():
    site = Site.model_validate(_site())
    assert validate_aerial_route(site, "TAKEOFF_A", ["POI_1", "POI_2"], 5, 1.0)["status"] == "PASS"
    tight = validate_aerial_route(site, "TAKEOFF_A", ["POI_1", "POI_2"], 5, 7.0)  # POI_2 is ~6.3 m from SHED
    assert tight["status"] == "FAIL" and tight["margin"]["status"] == "NOT_ACCREDITED"


def test_margin_is_compared_only_with_declared_values():
    data = _site()
    for group in ("exclusions", "takeoff_landing_zones", "points"):
        for element in data[group]:
            element["uncertainty_m"] = 0.5
    data["operation_perimeter"]["uncertainty_m"] = 0.5
    vehicle = FleetVehicle(vehicle_id="drone_01", category="sitl_multirotor", vehicle_type="multirotor",
                           autopilot="ArduPilot", platform="t", provenance="SITL", export_profile="NONE",
                           compatibility="DOCUMENTED_SITL", max_horizontal_extent_m=0.6,
                           horizontal_position_uncertainty_m=0.3)
    margin = validate_aerial_route(Site.model_validate(data), "TAKEOFF_A", ["POI_1"], 5, 1.0, vehicle)["margin"]
    # extent/2 + position uncertainty + largest element uncertainty = 0.3 + 0.3 + 0.5 > 1.0 declared
    assert margin["status"] == "BELOW_DECLARED_VALUES"
    assert margin["required_from_declared_values_m"] == pytest.approx(1.1)
    assert "not a physical guarantee" in margin["note"]


def test_vertical_limit_needs_comparable_references():
    data = _site()
    assert validate_aerial_route(Site.model_validate(data), "TAKEOFF_A", ["POI_1"], 35, 1.0)["status"] == "FAIL"
    data["vertical_reference"]["terrain"] = "UNKNOWN"
    result = validate_aerial_route(Site.model_validate(data), "TAKEOFF_A", ["POI_1"], 35, 1.0)
    assert result["status"] == "PASS" and "vertical limit" in result["unchecked"]


def test_rover_uses_its_own_area_and_exclusions():
    site = Site.model_validate(_site())
    assert validate_ground_route(site, "ROVER_START", "POI_1", 0.5)["status"] == "PASS"
    crossing = validate_ground_route(site, "ROVER_START", "POI_4", 0.5)  # across the ground-only DITCH
    assert crossing["status"] == "REQUIRES_PLANNING"
    # POI_2 lies inside the aerial perimeter but outside the drivable strip.
    assert validate_ground_route(site, "ROVER_START", "POI_2", 0.5)["status"] == "FAIL"


def test_fleet_rules():
    fleet = Fleet.model_validate_json(Path("missions/fleets/agri_demo_fleet.json").read_bytes())
    assert fleet.vehicle("mini_drone_01").compatibility == "UNRESOLVED_COMPATIBILITY"
    assert all(v.physical_identity == "NOT_ESTABLISHED" for v in fleet.vehicles)
    base = fleet.vehicle("mini_drone_01").model_dump()
    with pytest.raises(ValidationError, match="mini drones"):
        FleetVehicle.model_validate({**base, "compatibility": "DOCUMENTED_SITL"})
    with pytest.raises(ValidationError, match="QGC_PLAN"):
        FleetVehicle.model_validate({**fleet.vehicle("drone_01").model_dump(), "autopilot": "unknown"})
    with pytest.raises(ValidationError, match="rover exporter"):
        FleetVehicle.model_validate({**fleet.vehicle("rover_01").model_dump(), "export_profile": "QGC_PLAN_ARDUCOPTER"})
    data = json.loads(Path("missions/fleets/agri_demo_fleet.json").read_text())
    data["vehicles"].append(copy.deepcopy(data["vehicles"][0]))
    with pytest.raises(ValidationError, match="Duplicate"):
        Fleet.model_validate(data)


def test_local_route_checks_match_the_poi_route_for_the_same_points():
    from models.site import Site
    from planning.site_validation import validate_aerial_local_route, validate_aerial_route
    site = Site.model_validate_json(Path("missions/sites/synthetic_orchard_v1.site.json").read_bytes())
    by_poi = validate_aerial_route(site, "TAKEOFF_A", ["POI_1", "POI_2"], 5.0, 1.0)
    local = validate_aerial_local_route(site, "TAKEOFF_A", [("POI_1", (-4.0, 4.0)), ("POI_2", (-4.0, 18.0))], 5.0, 1.0)
    assert local["route_local"] == by_poi["route_local"] and local["checks"] == by_poi["checks"]
    assert validate_aerial_local_route(site, "POI_1", [("WP1", (0.0, 0.0))], 5.0, 1.0)["status"] == "FAIL"
