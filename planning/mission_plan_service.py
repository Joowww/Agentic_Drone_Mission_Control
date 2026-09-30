import re

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
from models.mission_plan_draft import (
    MissionPlanDraft,
    PlannedWaypointDraft,
)

DIRECTION_BEARINGS = {
    "north": 0.0,
    "northeast": 45.0,
    "east": 90.0,
    "southeast": 135.0,
    "south": 180.0,
    "southwest": 225.0,
    "west": 270.0,
    "northwest": 315.0,
}


def merge_mission_plan_drafts(
    current: MissionPlanDraft,
    new: MissionPlanDraft,
) -> MissionPlanDraft:
    current_data = current.model_dump(
        mode="python"
    )

    new_data = new.model_dump(
        mode="python"
    )

    for key, value in new_data.items():
        if key == "waypoints":
            continue

        if value is not None:
            current_data[
                key
            ] = value

    waypoint_map = {
        waypoint[
            "waypoint_id"
        ].upper(): waypoint
        for waypoint
        in current_data.get(
            "waypoints",
            [],
        )
    }

    for waypoint in new_data.get(
        "waypoints",
        [],
    ):
        waypoint_id = (
            waypoint[
                "waypoint_id"
            ].upper()
        )

        if waypoint_id not in waypoint_map:
            waypoint_map[
                waypoint_id
            ] = waypoint

        else:
            existing = waypoint_map[
                waypoint_id
            ]

            for key, value in waypoint.items():
                if value is not None:
                    existing[
                        key
                    ] = value

    current_data[
        "waypoints"
    ] = list(
        waypoint_map.values()
    )

    return MissionPlanDraft.model_validate(
        current_data
    )


def get_missing_planning_fields(
    draft: MissionPlanDraft,
) -> list[str]:
    missing = []

    required_fields = {
        "name":
            "mission name",
        "vehicle_type":
            "vehicle type",
        "autopilot":
            "autopilot",
        "cruise_speed_kmh":
            "vehicle cruise speed",
        "battery_percent":
            "current battery percentage",
        "battery_consumption_percent_per_minute":
            "battery consumption percentage per minute",
        "objective_type":
            "objective type",
        "objective_target":
            "objective target",
        "home_latitude":
            "home latitude",
        "home_longitude":
            "home longitude",
        "home_altitude_m":
            "home altitude",
        "wind_speed_kmh":
            "wind speed",
        "minimum_battery_reserve_percent":
            "minimum battery reserve",
        "maximum_wind_speed_kmh":
            "maximum safe wind speed",
        "maximum_altitude_m":
            "maximum altitude",
    }

    for field_name, label in (
        required_fields.items()
    ):
        if getattr(
            draft,
            field_name,
        ) is None:
            missing.append(
                label
            )

    if (
        draft.wind_direction_from_deg is None
        and draft.wind_direction_from is None
    ):
        missing.append(
            "wind direction"
        )

    if not draft.waypoints:
        missing.append(
            "at least one waypoint"
        )

    for waypoint in draft.waypoints:
        if waypoint.latitude is None:
            missing.append(
                f"{waypoint.waypoint_id} latitude"
            )

        if waypoint.longitude is None:
            missing.append(
                f"{waypoint.waypoint_id} longitude"
            )

        if waypoint.altitude_m is None:
            missing.append(
                f"{waypoint.waypoint_id} altitude"
            )

    return missing


def _generate_mission_id(
    name: str,
) -> str:
    slug = re.sub(
        r"[^a-z0-9]+",
        "_",
        name.lower(),
    ).strip(
        "_"
    )

    if not slug:
        slug = "mission"

    return (
        f"{slug}_001"
    )


def _build_waypoint(
    draft: PlannedWaypointDraft,
) -> Waypoint:
    return Waypoint(
        waypoint_id=(
            draft.waypoint_id.upper()
        ),
        latitude=draft.latitude,
        longitude=draft.longitude,
        altitude_m=draft.altitude_m,
        speed_kmh=draft.speed_kmh,
        action=(
            draft.action
            or "navigate"
        ),
    )


def build_mission_from_draft(
    draft: MissionPlanDraft,
) -> MissionDefinition:
    missing = get_missing_planning_fields(
        draft
    )

    if missing:
        raise ValueError(
            "Mission planning information is incomplete:\n"
            + "\n".join(
                f"- {field}"
                for field in missing
            )
        )

    if (
        draft.wind_direction_from_deg
        is not None
    ):
        wind_direction = (
            draft.wind_direction_from_deg
        )

    else:
        wind_direction = (
            DIRECTION_BEARINGS[
                draft.wind_direction_from
            ]
        )

    mission_id = (
        draft.mission_id
        or _generate_mission_id(
            draft.name
        )
    )

    vehicle_id = (
        draft.vehicle_id
        or "drone_01"
    )

    return_to_home = (
        True
        if draft.return_to_home is None
        else draft.return_to_home
    )

    mission = MissionDefinition(
        mission_id=mission_id,
        name=draft.name,
        source="natural_language",

        vehicle=VehicleDefinition(
            vehicle_id=vehicle_id,
            vehicle_type=draft.vehicle_type,
            autopilot=draft.autopilot,
            cruise_speed_kmh=(
                draft.cruise_speed_kmh
            ),
            battery_percent=(
                draft.battery_percent
            ),
            battery_consumption_percent_per_minute=(
                draft
                .battery_consumption_percent_per_minute
            ),
        ),

        objective=ObjectiveDefinition(
            objective_type=(
                draft.objective_type
            ),
            target=(
                draft.objective_target
            ),
            description=(
                draft.objective_description
            ),
        ),

        route=RouteDefinition(
            mode="waypoints",

            home=GeoPoint(
                latitude=(
                    draft.home_latitude
                ),
                longitude=(
                    draft.home_longitude
                ),
                altitude_m=(
                    draft.home_altitude_m
                ),
            ),

            waypoints=[
                _build_waypoint(
                    waypoint
                )
                for waypoint
                in draft.waypoints
            ],

            return_to_home=(
                return_to_home
            ),
        ),

        environment=EnvironmentDefinition(
            wind_speed_kmh=(
                draft.wind_speed_kmh
            ),
            wind_direction_from_deg=(
                wind_direction
            ),
        ),

        constraints=ConstraintDefinition(
            minimum_battery_reserve_percent=(
                draft
                .minimum_battery_reserve_percent
            ),
            maximum_wind_speed_kmh=(
                draft.maximum_wind_speed_kmh
            ),
            maximum_altitude_m=(
                draft.maximum_altitude_m
            ),
        ),

        failsafe=FailsafeDefinition(
            low_battery_action=(
                draft.low_battery_action
                or "RETURN_TO_HOME"
            ),
            unsafe_wind_action=(
                draft.unsafe_wind_action
                or "RETURN_TO_HOME"
            ),
            communication_loss_action=(
                draft.communication_loss_action
                or "RETURN_TO_HOME"
            ),
        ),
    )

    return mission