from pydantic import ValidationError

from models.mission_definition import (
    MissionDefinition,
)
from models.mission_update import (
    MissionUpdate,
)


def _format_change(
    label: str,
    old_value,
    new_value,
) -> str:
    return (
        f"{label}: "
        f"{old_value} -> {new_value}"
    )


def apply_mission_update(
    mission: MissionDefinition,
    update: MissionUpdate,
) -> tuple[
    MissionDefinition,
    list[str],
]:
    data = mission.model_dump(
        mode="python"
    )

    changes = []

    def update_value(
        container: dict,
        key: str,
        value,
        label: str,
    ) -> None:
        if value is None:
            return

        old_value = container.get(
            key
        )

        if old_value == value:
            return

        container[key] = value

        changes.append(
            _format_change(
                label,
                old_value,
                value,
            )
        )

    update_value(
        data,
        "name",
        update.mission_name,
        "Mission name",
    )

    vehicle = data[
        "vehicle"
    ]

    update_value(
        vehicle,
        "vehicle_id",
        update.vehicle_id,
        "Vehicle ID",
    )

    update_value(
        vehicle,
        "cruise_speed_kmh",
        update.cruise_speed_kmh,
        "Cruise speed",
    )

    update_value(
        vehicle,
        "battery_percent",
        update.battery_percent,
        "Battery",
    )

    update_value(
        vehicle,
        "battery_consumption_percent_per_minute",
        update.battery_consumption_percent_per_minute,
        "Battery consumption",
    )

    objective = data[
        "objective"
    ]

    update_value(
        objective,
        "objective_type",
        update.objective_type,
        "Objective type",
    )

    update_value(
        objective,
        "target",
        update.objective_target,
        "Objective target",
    )

    update_value(
        objective,
        "description",
        update.objective_description,
        "Objective description",
    )

    environment = data[
        "environment"
    ]

    update_value(
        environment,
        "wind_speed_kmh",
        update.wind_speed_kmh,
        "Wind speed",
    )

    update_value(
        environment,
        "wind_direction_from_deg",
        update.wind_direction_from_deg,
        "Wind direction",
    )

    constraints = data[
        "constraints"
    ]

    update_value(
        constraints,
        "minimum_battery_reserve_percent",
        update.minimum_battery_reserve_percent,
        "Minimum battery reserve",
    )

    update_value(
        constraints,
        "maximum_wind_speed_kmh",
        update.maximum_wind_speed_kmh,
        "Maximum wind speed",
    )

    update_value(
        constraints,
        "maximum_altitude_m",
        update.maximum_altitude_m,
        "Maximum altitude",
    )

    route = data[
        "route"
    ]

    update_value(
        route,
        "return_to_home",
        update.return_to_home,
        "Return to home",
    )

    home = route.get(
        "home"
    )

    home_update_requested = any(
        value is not None
        for value in [
            update.home_latitude,
            update.home_longitude,
            update.home_altitude_m,
        ]
    )

    if (
        home_update_requested
        and home is None
    ):
        raise ValueError(
            "The mission has no home position to update."
        )

    if home is not None:
        update_value(
            home,
            "latitude",
            update.home_latitude,
            "Home latitude",
        )

        update_value(
            home,
            "longitude",
            update.home_longitude,
            "Home longitude",
        )

        update_value(
            home,
            "altitude_m",
            update.home_altitude_m,
            "Home altitude",
        )

    waypoints = route[
        "waypoints"
    ]

    waypoint_lookup = {
        waypoint[
            "waypoint_id"
        ].lower(): waypoint
        for waypoint in waypoints
    }

    for waypoint_update in (
        update.waypoint_updates
    ):
        waypoint_key = (
            waypoint_update
            .waypoint_id
            .lower()
        )

        if waypoint_key not in waypoint_lookup:
            raise ValueError(
                "Waypoint not found: "
                f"{waypoint_update.waypoint_id}"
            )

        waypoint = waypoint_lookup[
            waypoint_key
        ]

        prefix = (
            waypoint[
                "waypoint_id"
            ]
        )

        update_value(
            waypoint,
            "latitude",
            waypoint_update.latitude,
            f"{prefix} latitude",
        )

        update_value(
            waypoint,
            "longitude",
            waypoint_update.longitude,
            f"{prefix} longitude",
        )

        update_value(
            waypoint,
            "altitude_m",
            waypoint_update.altitude_m,
            f"{prefix} altitude",
        )

        update_value(
            waypoint,
            "speed_kmh",
            waypoint_update.speed_kmh,
            f"{prefix} speed",
        )

        update_value(
            waypoint,
            "action",
            waypoint_update.action,
            f"{prefix} action",
        )

    removal_ids = {
        waypoint_id.lower()
        for waypoint_id
        in update.waypoint_removals
    }

    if removal_ids:
        existing_ids = {
            waypoint[
                "waypoint_id"
            ].lower()
            for waypoint in waypoints
        }

        missing_removals = (
            removal_ids
            - existing_ids
        )

        if missing_removals:
            missing_text = ", ".join(
                sorted(
                    missing_removals
                )
            )

            raise ValueError(
                "Cannot remove unknown waypoint(s): "
                f"{missing_text}"
            )

        remaining_waypoints = []

        for waypoint in waypoints:
            if (
                waypoint[
                    "waypoint_id"
                ].lower()
                in removal_ids
            ):
                changes.append(
                    "Removed waypoint: "
                    f"{waypoint['waypoint_id']}"
                )

            else:
                remaining_waypoints.append(
                    waypoint
                )

        route[
            "waypoints"
        ] = remaining_waypoints

        waypoints = remaining_waypoints

    existing_ids = {
        waypoint[
            "waypoint_id"
        ].lower()
        for waypoint in waypoints
    }

    for addition in (
        update.waypoint_additions
    ):
        waypoint_key = (
            addition
            .waypoint_id
            .lower()
        )

        if waypoint_key in existing_ids:
            raise ValueError(
                "Waypoint already exists: "
                f"{addition.waypoint_id}"
            )

        waypoint_data = (
            addition.model_dump()
        )

        waypoints.append(
            waypoint_data
        )

        existing_ids.add(
            waypoint_key
        )

        changes.append(
            "Added waypoint: "
            f"{addition.waypoint_id}"
        )

    route[
        "waypoints"
    ] = waypoints

    try:
        updated_mission = (
            MissionDefinition
            .model_validate(
                data
            )
        )

    except ValidationError as error:
        raise ValueError(
            "The requested update would create "
            "an invalid mission:\n"
            f"{error}"
        ) from error

    return (
        updated_mission,
        changes,
    )