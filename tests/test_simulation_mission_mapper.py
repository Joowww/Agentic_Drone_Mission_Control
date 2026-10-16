from __future__ import annotations

import pytest

from models.mission_definition import (
    GeoPoint,
    Waypoint,
)
from tools.simulation_mission_mapper import (
    map_waypoint_to_simulation,
)


def test_home_waypoint_maps_to_simulation_home():
    home = GeoPoint(
        latitude=41.275,
        longitude=1.987,
        altitude_m=0.0,
    )

    waypoint = Waypoint(
        waypoint_id="WP0",
        latitude=41.275,
        longitude=1.987,
        altitude_m=5.0,
        speed_kmh=10.0,
        action="navigate",
    )

    result = map_waypoint_to_simulation(
        home,
        waypoint,
        simulation_home_latitude=-35.363262,
        simulation_home_longitude=149.165237,
    )

    assert result["latitude"] == pytest.approx(
        -35.363262
    )

    assert result["longitude"] == pytest.approx(
        149.165237
    )


def test_north_offset_is_preserved():
    home = GeoPoint(
        latitude=41.275,
        longitude=1.987,
        altitude_m=0.0,
    )

    waypoint = Waypoint(
        waypoint_id="WP1",
        latitude=41.276,
        longitude=1.987,
        altitude_m=30.0,
        speed_kmh=25.0,
        action="navigate",
    )

    result = map_waypoint_to_simulation(
        home,
        waypoint,
        simulation_home_latitude=-35.363262,
        simulation_home_longitude=149.165237,
    )

    assert result["north_offset_m"] == pytest.approx(
        111.32,
        abs=0.2,
    )

    assert result["east_offset_m"] == pytest.approx(
        0.0,
        abs=0.1,
    )


def test_altitude_and_action_are_preserved():
    home = GeoPoint(
        latitude=41.275,
        longitude=1.987,
        altitude_m=0.0,
    )

    waypoint = Waypoint(
        waypoint_id="WP2",
        latitude=41.276,
        longitude=1.989,
        altitude_m=30.0,
        speed_kmh=25.0,
        action="survey",
    )

    result = map_waypoint_to_simulation(
        home,
        waypoint,
        simulation_home_latitude=-35.363262,
        simulation_home_longitude=149.165237,
    )

    assert result["altitude_m"] == 30.0
    assert result["speed_kmh"] == 25.0
    assert result["action"] == "survey"