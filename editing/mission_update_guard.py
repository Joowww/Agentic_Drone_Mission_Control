import re

from models.mission_update import (
    MissionUpdate,
)


def _has_value(
    value,
) -> bool:
    return value not in (
        None,
        [],
        {},
    )


def _explicit_waypoint_ids(
    user_input: str,
    mission,
) -> set[str]:
    explicit_ids = set()
    for waypoint in mission.route.waypoints:
        waypoint_id = waypoint.waypoint_id
        if re.search(
            r"\b" + re.escape(waypoint_id) + r"\b",
            user_input,
            flags=re.IGNORECASE,
        ):
            explicit_ids.add(waypoint_id.upper())

    explicit_ids.update(
        match.upper()
        for match in re.findall(
            r"\bWP\d+\b",
            user_input,
            flags=re.IGNORECASE,
        )
    )
    return explicit_ids


def validate_update_grounding(
    user_input: str,
    update: MissionUpdate,
    mission,
) -> None:
    text = user_input.lower()

    violations = []

    field_checks = {
        "mission_name": (
            "mission name" in text
            or "rename" in text
        ),

        "vehicle_id": (
            "vehicle id" in text
            or "drone id" in text
        ),

        "cruise_speed_kmh": (
            "cruise speed" in text
            or "drone speed" in text
            or "vehicle speed" in text
            or "airspeed" in text
        ),

        "battery_percent": (
            "battery" in text
            and "reserve" not in text
            and "consumption" not in text
        ),

        "battery_consumption_percent_per_minute": (
            "battery" in text
            and "consumption" in text
        ),

        "objective_type": (
            "objective" in text
            or "mission type" in text
        ),

        "objective_target": (
            "objective" in text
            or "target" in text
        ),

        "objective_description": (
            "description" in text
        ),

        "wind_speed_kmh": (
            "wind" in text
            and "maximum" not in text
            and "max wind" not in text
        ),

        "wind_direction_from": (
            "wind" in text
        ),

        "wind_direction_from_deg": (
            "wind" in text
        ),

        "minimum_battery_reserve_percent": (
            "reserve" in text
        ),

        "maximum_wind_speed_kmh": (
            "wind" in text
            and (
                "maximum" in text
                or "max " in text
            )
        ),

        "maximum_altitude_m": (
            "altitude" in text
            and (
                "maximum" in text
                or "max " in text
            )
        ),

        "return_to_home": (
            "return to home" in text
            or "rtl" in text
        ),

        "home_latitude": (
            "home" in text
            and "latitude" in text
        ),

        "home_longitude": (
            "home" in text
            and "longitude" in text
        ),

        "home_altitude_m": (
            "home" in text
            and "altitude" in text
        ),
    }

    data = update.model_dump(
        exclude_none=True
    )

    for field_name, is_grounded in (
        field_checks.items()
    ):
        value = data.get(
            field_name
        )

        if (
            _has_value(value)
            and not is_grounded
        ):
            violations.append(
                field_name
            )

    explicit_ids = _explicit_waypoint_ids(
        user_input,
        mission,
    )

    waypoint_context = bool(explicit_ids) or bool(
        re.search(
            r"\bWP\d+\b|\bwaypoint\b",
            user_input,
            flags=re.IGNORECASE,
        )
    )

    if (
        update.waypoint_updates
        and not waypoint_context
    ):
        violations.append(
            "waypoint_updates"
        )

    if (
        update.waypoint_additions
        and not waypoint_context
    ):
        violations.append(
            "waypoint_additions"
        )

    if (
        update.waypoint_removals
        and not waypoint_context
    ):
        violations.append(
            "waypoint_removals"
        )

    if explicit_ids:
        proposed_ids = set()

        for waypoint in (
            update.waypoint_updates
        ):
            proposed_ids.add(
                waypoint.waypoint_id.upper()
            )

        for waypoint in (
            update.waypoint_additions
        ):
            proposed_ids.add(
                waypoint.waypoint_id.upper()
            )

        proposed_ids.update(
            waypoint.upper()
            for waypoint
            in update.waypoint_removals
        )

        unrelated_ids = (
            proposed_ids
            - explicit_ids
        )

        if unrelated_ids:
            violations.append(
                "unrequested waypoint(s): "
                + ", ".join(
                    sorted(
                        unrelated_ids
                    )
                )
            )

    if violations:
        raise ValueError(
            "The LLM proposed mission changes "
            "that are not grounded in the user's "
            "instruction: "
            + ", ".join(
                violations
            )
        )