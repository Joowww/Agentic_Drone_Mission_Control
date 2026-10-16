from __future__ import annotations

import math

from models.mission_definition import (
    GeoPoint,
    MissionDefinition,
    Waypoint,
)


METERS_PER_DEGREE_LATITUDE = 111_320.0


def _calculate_local_offset_metres(
    home: GeoPoint,
    latitude: float,
    longitude: float,
) -> tuple[float, float]:
    """Return north/east displacement from mission home in metres."""

    north_m = (
        latitude - home.latitude
    ) * METERS_PER_DEGREE_LATITUDE

    longitude_scale = (
        METERS_PER_DEGREE_LATITUDE
        * math.cos(
            math.radians(home.latitude)
        )
    )

    east_m = (
        longitude - home.longitude
    ) * longitude_scale

    return north_m, east_m


def map_waypoint_to_simulation(
    mission_home: GeoPoint,
    waypoint: Waypoint,
    *,
    simulation_home_latitude: float,
    simulation_home_longitude: float,
) -> dict[str, object]:
    """Map a mission waypoint around the Gazebo/SITL global origin.

    Horizontal geometry relative to the original mission home is
    preserved. Altitude remains relative to home.
    """

    north_m, east_m = (
        _calculate_local_offset_metres(
            mission_home,
            waypoint.latitude,
            waypoint.longitude,
        )
    )

    mapped_latitude = (
        simulation_home_latitude
        + (
            north_m
            / METERS_PER_DEGREE_LATITUDE
        )
    )

    simulation_longitude_scale = (
        METERS_PER_DEGREE_LATITUDE
        * math.cos(
            math.radians(
                simulation_home_latitude
            )
        )
    )

    mapped_longitude = (
        simulation_home_longitude
        + (
            east_m
            / simulation_longitude_scale
        )
    )

    return {
        "waypoint_id": waypoint.waypoint_id,
        "latitude": mapped_latitude,
        "longitude": mapped_longitude,
        "altitude_m": waypoint.altitude_m,
        "speed_kmh": waypoint.speed_kmh,
        "action": waypoint.action,
        "north_offset_m": north_m,
        "east_offset_m": east_m,
    }


def map_mission_route_to_simulation(
    mission: MissionDefinition,
    *,
    simulation_home_latitude: float,
    simulation_home_longitude: float,
) -> list[dict[str, object]]:
    """Map every waypoint in a waypoint mission to the SITL origin."""

    if mission.route.mode != "waypoints":
        raise ValueError(
            "Simulation execution currently requires "
            "a waypoint mission."
        )

    if mission.route.home is None:
        raise ValueError(
            "Simulation execution requires a mission home."
        )

    return [
        map_waypoint_to_simulation(
            mission.route.home,
            waypoint,
            simulation_home_latitude=(
                simulation_home_latitude
            ),
            simulation_home_longitude=(
                simulation_home_longitude
            ),
        )
        for waypoint in mission.route.waypoints
    ]