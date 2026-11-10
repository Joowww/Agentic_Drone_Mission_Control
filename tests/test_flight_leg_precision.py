"""Leg distances and times keep full precision; rounding is presentation only.

Regression for the premature rounding reproduced on 31/10/2026 (after H2): a
horizontal leg shorter than 0.5 m was rounded to 0 km and the mission was
rejected as if the leg could not be flown.
"""
import pytest

import tools.mission_energy_analysis as energy
from models.mission_definition import MissionDefinition
from safety.mission_safety_analysis import evaluate_mission_safety
from tools.flight_dynamics import calculate_flight_time
from tools.hermes_mission_validation import validate_mission
from tools.route_flight_analysis import analyze_mission_flight

M_PER_DEG = 111_320.0
HOME = {"latitude": 41.275, "longitude": 1.987, "altitude_m": 0.0}


def _mission(points: list[tuple[float, float]], *, altitude_m: float = 5.0) -> MissionDefinition:
    """Same shape as the H2 sector A mission; points are (north_m, altitude_m)."""
    return MissionDefinition.model_validate({
        "schema_version": "1.0", "mission_id": "leg_precision", "name": "leg precision",
        "source": "natural_language",
        "vehicle": {"vehicle_id": "drone_01", "vehicle_type": "multirotor", "autopilot": "ArduPilot",
                    "cruise_speed_kmh": 35.0, "battery_percent": 100.0,
                    "battery_consumption_percent_per_minute": 0.8},
        "objective": {"objective_type": "precision_agriculture", "target": "test", "description": None},
        "route": {"mode": "waypoints", "distance_km": None, "bearing_deg": None, "home": HOME,
                  "waypoints": [{"waypoint_id": f"WP{i}", "latitude": HOME["latitude"] + north / M_PER_DEG,
                                 "longitude": HOME["longitude"], "altitude_m": altitude, "speed_kmh": None,
                                 "action": "navigate"}
                                for i, (north, altitude) in enumerate(points, 1)],
                  "return_to_home": True},
        "environment": {"wind_speed_kmh": 0.0, "wind_direction_from_deg": 0.0},
        "constraints": {"minimum_battery_reserve_percent": 20.0, "maximum_wind_speed_kmh": 30.0,
                        "maximum_altitude_m": 120.0},
        "failsafe": {"low_battery_action": "RETURN_TO_HOME", "unsafe_wind_action": "RETURN_TO_HOME",
                     "communication_loss_action": "RETURN_TO_HOME"},
    })


@pytest.mark.parametrize("north_m", [0.4, 0.49, 0.5, 0.51, 0.6, 1.4])
def test_short_positive_leg_keeps_its_distance_and_time(north_m):
    mission = _mission([(north_m, 5.0), (8.0, 5.0)])
    first = analyze_mission_flight(mission)["leg_results"][0]

    # Haversine (R = 6371.0088 km) of a point generated with 111 320 m/deg: ratio 0.998878.
    assert first["distance_km_exact"] * 1000 == pytest.approx(north_m * 0.998878, rel=1e-5)
    assert first["flight_result"]["status"] == "success"
    assert first["flight_result"]["flight_time_minutes_exact"] == pytest.approx(
        first["distance_km_exact"] / 35.0 * 60)
    assert first["flight_result"]["flight_time_minutes_exact"] > 0

    result = validate_mission(mission)
    assert (result["mission_status"], result["execution_status"]) == ("FEASIBLE", "APPROVED")
    assert result["failure_reasons"] == [] and result["errors"] == []


def test_several_short_legs_sum_exact_times():
    mission = _mission([(0.3, 5.0), (0.6, 5.0), (0.9, 5.0), (1.2, 5.0)])
    flight = analyze_mission_flight(mission)
    times = [leg["flight_result"]["flight_time_minutes_exact"] for leg in flight["leg_results"]]

    assert all(t > 0 for t in times)
    assert all(leg["distance_km"] == 0.0 for leg in flight["leg_results"][1:4])  # shown rounded only
    assert flight["total_flight_time_minutes_exact"] == pytest.approx(sum(times))
    assert flight["total_flight_time_minutes"] == round(sum(times), 2)
    assert validate_mission(mission)["mission_status"] == "FEASIBLE"


def test_battery_uses_the_exact_total_not_the_displayed_one(monkeypatch):
    seen = []
    original = energy.check_battery_safety

    def spy(**kwargs):
        seen.append(kwargs["flight_time_minutes"])
        return original(**kwargs)

    monkeypatch.setattr(energy, "check_battery_safety", spy)
    mission = _mission([(8.0, 5.0), (16.0, 5.0)])
    result = energy.analyze_mission_energy(mission)
    flight = result["flight_analysis"]

    assert seen == [flight["total_flight_time_minutes_exact"]]
    assert seen[0] != flight["total_flight_time_minutes"]


def test_vertical_leg_is_rejected_with_a_specific_reason():
    mission = _mission([(0.0, 5.0), (8.0, 5.0)])
    first = analyze_mission_flight(mission)["leg_results"][0]
    assert first["flight_result"]["status"] == "not_modelled"
    assert first["flight_result"]["reason"] == "VERTICAL_LEG_NOT_MODELLED"

    result = validate_mission(mission)
    assert (result["mission_status"], result["execution_status"]) == ("NOT FEASIBLE", "BLOCKED")
    assert len(result["failure_reasons"]) == 1
    assert "Vertical-only route legs (HOME -> WP1)" in result["failure_reasons"][0]
    assert "horizontal motion only" in result["failure_reasons"][0]
    assert not any("cannot be flown" in r for r in result["failure_reasons"])
    assert any("vertical-only" in a and "HOME -> WP1" in a for a in result["replan_actions"])
    assert not any("unflyable" in a for a in result["replan_actions"])


def test_leg_without_displacement_is_distinguished():
    mission = _mission([(8.0, 5.0), (8.0, 5.0)])
    second = analyze_mission_flight(mission)["leg_results"][1]
    assert second["flight_result"]["status"] == "no_displacement"
    assert second["flight_result"]["reason"] == "NO_DISPLACEMENT"

    result = validate_mission(mission)
    assert (result["mission_status"], result["execution_status"]) == ("NOT FEASIBLE", "BLOCKED")
    assert result["failure_reasons"] == [
        "Route legs without displacement (WP1 -> WP2) repeat the previous point's position and altitude."]
    assert any("repeated point" in a and "WP1 -> WP2" in a for a in result["replan_actions"])


def test_unsafe_wind_leg_keeps_the_generic_reason():
    mission = _mission([(8.0, 5.0)]).model_copy(deep=True)
    mission.environment.wind_speed_kmh = 40.0  # headwind > cruise speed on the northbound leg
    mission.constraints.maximum_wind_speed_kmh = 50.0
    result = evaluate_mission_safety(mission)
    assert result["mission_status"] == "NOT FEASIBLE"
    assert result["failure_reasons"] == ["One or more route legs cannot be flown under the current conditions."]


def test_calculate_flight_time_exposes_exact_and_rounded_time():
    result = calculate_flight_time(0.0004, 35.0, 0.0, 0.0, 0.0)
    assert result["flight_time_minutes_exact"] == pytest.approx(0.0004 / 35.0 * 60)
    assert result["flight_time_minutes"] == 0.0  # presentation only
