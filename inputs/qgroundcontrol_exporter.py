import json
from pathlib import Path

from models.mission_definition import MissionDefinition


MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_NAV_TAKEOFF = 22


VEHICLE_TYPE_TO_MAVLINK = {
    "fixed_wing": 1,
    "multirotor": 2,
    "vtol": 19,
    "ugv": 10,
}


AUTOPILOT_TO_MAVLINK = {
    "PX4": 12,
    "ArduPilot": 3,
    "unknown": 0,
}


def _navigation_item(
    *,
    command: int,
    do_jump_id: int,
    latitude: float,
    longitude: float,
    altitude_m: float,
) -> dict:
    return {
        "AMSLAltAboveTerrain": None,
        "Altitude": altitude_m,
        "AltitudeMode": 1,
        "autoContinue": True,
        "command": command,
        "doJumpId": do_jump_id,
        "frame": 3,
        "params": [
            0,
            0,
            0,
            None,
            latitude,
            longitude,
            altitude_m,
        ],
        "type": "SimpleItem",
    }


def _rtl_item(
    do_jump_id: int,
) -> dict:
    return {
        "AMSLAltAboveTerrain": None,
        "Altitude": 0,
        "AltitudeMode": 1,
        "autoContinue": True,
        "command": MAV_CMD_NAV_RETURN_TO_LAUNCH,
        "doJumpId": do_jump_id,
        "frame": 2,
        "params": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        "type": "SimpleItem",
    }


def build_qgroundcontrol_plan(
    mission: MissionDefinition,
) -> dict:
    if mission.route.mode != "waypoints":
        raise ValueError(
            "QGroundControl export currently requires "
            "a waypoint mission."
        )

    if mission.route.home is None:
        raise ValueError(
            "QGroundControl export requires a HOME position."
        )

    if not mission.route.waypoints:
        raise ValueError(
            "QGroundControl export requires at least one waypoint."
        )

    if mission.vehicle.vehicle_type == "ugv":
        raise ValueError(
            "QGroundControl export currently supports "
            "aerial missions only."
        )

    home = mission.route.home
    waypoints = mission.route.waypoints

    speed_mps = (
        mission.vehicle.cruise_speed_kmh
        / 3.6
    )

    items = []

    first_altitude = (
        waypoints[0].altitude_m
    )

    items.append(
        _navigation_item(
            command=MAV_CMD_NAV_TAKEOFF,
            do_jump_id=1,
            latitude=home.latitude,
            longitude=home.longitude,
            altitude_m=first_altitude,
        )
    )

    for waypoint in waypoints:
        items.append(
            _navigation_item(
                command=MAV_CMD_NAV_WAYPOINT,
                do_jump_id=len(items) + 1,
                latitude=waypoint.latitude,
                longitude=waypoint.longitude,
                altitude_m=waypoint.altitude_m,
            )
        )

    if mission.route.return_to_home:
        items.append(
            _rtl_item(
                do_jump_id=len(items) + 1
            )
        )

    vehicle_type = (
        VEHICLE_TYPE_TO_MAVLINK[
            mission.vehicle.vehicle_type
        ]
    )

    firmware_type = (
        AUTOPILOT_TO_MAVLINK[
            mission.vehicle.autopilot
        ]
    )

    return {
        "fileType": "Plan",
        "geoFence": {
            "circles": [],
            "polygons": [],
            "version": 2,
        },
        "groundStation": "QGroundControl",
        "mission": {
            "cruiseSpeed": speed_mps,
            "firmwareType": firmware_type,
            "globalPlanAltitudeMode": 1,
            "hoverSpeed": speed_mps,
            "items": items,
            "plannedHomePosition": [
                home.latitude,
                home.longitude,
                home.altitude_m,
            ],
            "vehicleType": vehicle_type,
            "version": 2,
        },
        "rallyPoints": {
            "points": [],
            "version": 2,
        },
        "version": 1,
    }


def export_qgroundcontrol_plan(
    mission: MissionDefinition,
    file_path: str | Path,
) -> Path:
    path = Path(file_path)

    if path.suffix.lower() != ".plan":
        raise ValueError(
            "QGroundControl export path must "
            "use the .plan extension."
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    plan = build_qgroundcontrol_plan(
        mission
    )

    path.write_text(
        json.dumps(
            plan,
            indent=4,
        )
        + "\n",
        encoding="utf-8",
    )

    return path