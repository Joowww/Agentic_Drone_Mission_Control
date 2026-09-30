import json
from pathlib import Path

from models.mission_definition import (
    ConstraintDefinition,
    EnvironmentDefinition,
    FailsafeDefinition,
    GeoPoint,
    MissionDefinition,
    ObjectiveDefinition,
    RouteDefinition,
    VehicleDefinition,
    Waypoint,
)
from models.qgc_import import (
    QGroundControlImportContext,
    QGroundControlImportResult,
)

MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_LOITER_TIME = 19
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_NAV_LAND = 21
MAV_CMD_NAV_TAKEOFF = 22
MAV_CMD_DO_CHANGE_SPEED = 178


MULTIROTOR_TYPES = {
    2,
    3,
    4,
    13,
    14,
    15,
    29,
    35,
    43,
}


VTOL_TYPES = {
    19,
    20,
    21,
    22,
    23,
    24,
}


def _vehicle_type_from_mavlink(
    vehicle_type: int,
) -> str:
    if vehicle_type == 1:
        return "fixed_wing"

    if vehicle_type in MULTIROTOR_TYPES:
        return "multirotor"

    if vehicle_type in VTOL_TYPES:
        return "vtol"

    if vehicle_type == 10:
        return "ugv"

    raise ValueError(
        "Unsupported QGroundControl MAV_TYPE: "
        f"{vehicle_type}"
    )


def _autopilot_from_mavlink(
    firmware_type: int,
) -> str:
    if firmware_type == 12:
        return "PX4"

    if firmware_type == 3:
        return "ArduPilot"

    return "unknown"


def _get_default_speed_kmh(
    mission_data: dict,
    vehicle_type: str,
) -> float:
    if vehicle_type == "multirotor":
        speed_mps = mission_data.get(
            "hoverSpeed"
        )

    else:
        speed_mps = mission_data.get(
            "cruiseSpeed"
        )

    if (
        speed_mps is None
        or speed_mps <= 0
    ):
        raise ValueError(
            "QGroundControl plan does not contain "
            "a valid vehicle speed."
        )

    return round(
        float(speed_mps) * 3.6,
        2,
    )


def _relative_altitude_m(
    altitude: float,
    frame: int,
    home_amsl_m: float,
) -> float:
    if frame in {
        3,
        6,
    }:
        return float(
            altitude
        )

    if frame in {
        0,
        5,
    }:
        return float(
            altitude
        ) - home_amsl_m

    if frame in {
        10,
        11,
    }:
        raise ValueError(
            "Terrain-relative QGroundControl "
            "altitude frames are not supported yet."
        )

    raise ValueError(
        "Unsupported MAVLink coordinate frame: "
        f"{frame}"
    )


def _extract_coordinate(
    item: dict,
    home_amsl_m: float,
) -> tuple[
    float,
    float,
    float,
]:
    params = item.get(
        "params"
    )

    if (
        not isinstance(
            params,
            list,
        )
        or len(params) < 7
    ):
        raise ValueError(
            "QGroundControl SimpleItem "
            "contains invalid params."
        )

    latitude = params[4]
    longitude = params[5]
    altitude = params[6]

    if (
        latitude is None
        or longitude is None
        or altitude is None
    ):
        raise ValueError(
            "QGroundControl navigation item "
            "does not contain a complete position."
        )

    frame = int(
        item.get(
            "frame",
            3,
        )
    )

    relative_altitude = (
        _relative_altitude_m(
            altitude=float(
                altitude
            ),
            frame=frame,
            home_amsl_m=home_amsl_m,
        )
    )

    return (
        float(
            latitude
        ),
        float(
            longitude
        ),
        relative_altitude,
    )


def load_qgroundcontrol_plan(
    file_path: str,
    context: QGroundControlImportContext,
) -> QGroundControlImportResult:
    path = Path(
        file_path
    )

    if not path.exists():
        raise FileNotFoundError(
            f"QGroundControl plan not found: {file_path}"
        )

    if not path.is_file():
        raise ValueError(
            "QGroundControl path is not a file."
        )

    if path.suffix.lower() != ".plan":
        raise ValueError(
            "QGroundControl plan must use "
            "the .plan extension."
        )

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(
                file
            )

    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid QGroundControl JSON: {error}"
        ) from error

    if data.get(
        "fileType"
    ) != "Plan":
        raise ValueError(
            "File is not a QGroundControl Plan."
        )

    mission_data = data.get(
        "mission"
    )

    if not isinstance(
        mission_data,
        dict,
    ):
        raise ValueError(  # noqa: TRY004
            "QGroundControl Plan has no "
            "valid mission object."
        )

    home = mission_data.get(
        "plannedHomePosition"
    )

    if (
        not isinstance(
            home,
            list,
        )
        or len(home) < 3
    ):
        raise ValueError(
            "QGroundControl mission has no "
            "valid plannedHomePosition."
        )

    home_latitude = float(
        home[0]
    )

    home_longitude = float(
        home[1]
    )

    home_amsl_m = float(
        home[2]
    )

    items = mission_data.get(
        "items"
    )

    if (
        not isinstance(
            items,
            list,
        )
        or not items
    ):
        raise ValueError(
            "QGroundControl mission "
            "contains no mission items."
        )

    complex_items = [
        item
        for item in items
        if item.get(
            "type"
        ) == "ComplexItem"
    ]

    if complex_items:
        complex_types = sorted(
            {
                str(
                    item.get(
                        "complexItemType",
                        "unknown",
                    )
                )
                for item
                in complex_items
            }
        )

        raise ValueError(
            "This QGroundControl adapter currently "
            "supports SimpleItem missions only. "
            "Unsupported ComplexItem type(s): "
            + ", ".join(
                complex_types
            )
        )

    mav_vehicle_type = int(
        mission_data.get(
            "vehicleType",
            0,
        )
    )

    firmware_type = int(
        mission_data.get(
            "firmwareType",
            0,
        )
    )

    vehicle_type = (
        _vehicle_type_from_mavlink(
            mav_vehicle_type
        )
    )

    autopilot = (
        _autopilot_from_mavlink(
            firmware_type
        )
    )

    default_speed_kmh = (
        _get_default_speed_kmh(
            mission_data,
            vehicle_type,
        )
    )

    current_speed_kmh = (
        default_speed_kmh
    )

    waypoints = []

    warnings = []

    return_to_home = False

    waypoint_counter = 1

    for item in items:
        if item.get(
            "type"
        ) != "SimpleItem":
            raise ValueError(
                "Unsupported QGroundControl "
                "mission item type."
            )

        command = int(
            item.get(
                "command",
                -1,
            )
        )

        if (
            command
            == MAV_CMD_DO_CHANGE_SPEED
        ):
            params = item.get(
                "params",
                [],
            )

            if (
                len(params) >= 2
                and params[1] is not None
                and float(
                    params[1]
                ) > 0
            ):
                current_speed_kmh = round(
                    float(
                        params[1]
                    )
                    * 3.6,
                    2,
                )

            continue

        if (
            command
            == MAV_CMD_NAV_RETURN_TO_LAUNCH
        ):
            return_to_home = True

            continue

        if (
            command
            == MAV_CMD_NAV_TAKEOFF
        ):
            warnings.append(
                "MAV_CMD_NAV_TAKEOFF was not "
                "converted into a horizontal waypoint. "
                "Vertical takeoff dynamics are not "
                "modelled yet."
            )

            continue

        if command in {
            MAV_CMD_NAV_WAYPOINT,
            MAV_CMD_NAV_LOITER_TIME,
            MAV_CMD_NAV_LAND,
        }:
            (
                latitude,
                longitude,
                altitude_m,
            ) = _extract_coordinate(
                item,
                home_amsl_m,
            )

            if (
                command
                == MAV_CMD_NAV_LOITER_TIME
            ):
                action = "loiter"

            else:
                action = "navigate"

            waypoint = Waypoint(
                waypoint_id=(
                    f"QGC_WP{waypoint_counter}"
                ),
                latitude=latitude,
                longitude=longitude,
                altitude_m=altitude_m,
                speed_kmh=(
                    current_speed_kmh
                ),
                action=action,
            )

            waypoints.append(
                waypoint
            )

            waypoint_counter += 1

            if (
                command
                == MAV_CMD_NAV_LAND
            ):
                warnings.append(
                    "MAV_CMD_NAV_LAND was converted "
                    "to a navigation endpoint. "
                    "Landing dynamics are not "
                    "modelled yet."
                )

            continue

        warnings.append(
            "Skipped unsupported MAVLink command: "
            f"{command}"
        )

    if not waypoints:
        raise ValueError(
            "No supported positional mission "
            "items could be imported."
        )

    mission_name = (
        path.stem
        .replace(
            "_",
            " ",
        )
        .title()
    )

    mission_id = (
        "qgc_"
        + path.stem.lower()
    )

    mission = MissionDefinition(
        mission_id=mission_id,

        name=mission_name,

        source="qgroundcontrol",

        vehicle=VehicleDefinition(
            vehicle_id=(
                context.vehicle_id
            ),
            vehicle_type=(
                vehicle_type
            ),
            autopilot=(
                autopilot
            ),
            cruise_speed_kmh=(
                default_speed_kmh
            ),
            battery_percent=(
                context.battery_percent
            ),
            battery_consumption_percent_per_minute=(
                context
                .battery_consumption_percent_per_minute
            ),
        ),

        objective=ObjectiveDefinition(
            objective_type="custom",
            target=path.stem,
            description=(
                "Mission imported from "
                "QGroundControl."
            ),
        ),

        route=RouteDefinition(
            mode="waypoints",

            home=GeoPoint(
                latitude=(
                    home_latitude
                ),
                longitude=(
                    home_longitude
                ),
                altitude_m=0.0,
            ),

            waypoints=waypoints,

            return_to_home=(
                return_to_home
            ),
        ),

        environment=EnvironmentDefinition(
            wind_speed_kmh=(
                context.wind_speed_kmh
            ),
            wind_direction_from_deg=(
                context
                .wind_direction_from_deg
            ),
        ),

        constraints=ConstraintDefinition(
            minimum_battery_reserve_percent=(
                context
                .minimum_battery_reserve_percent
            ),
            maximum_wind_speed_kmh=(
                context
                .maximum_wind_speed_kmh
            ),
            maximum_altitude_m=(
                context.maximum_altitude_m
            ),
        ),

        failsafe=FailsafeDefinition(
            low_battery_action=(
                "RETURN_TO_HOME"
            ),
            unsafe_wind_action=(
                "RETURN_TO_HOME"
            ),
            communication_loss_action=(
                "RETURN_TO_HOME"
            ),
        ),
    )

    return QGroundControlImportResult(
        mission=mission,
        warnings=warnings,
        planned_home_amsl_m=(
            home_amsl_m
        ),
        source_item_count=len(
            items
        ),
        imported_waypoint_count=len(
            waypoints
        ),
    )