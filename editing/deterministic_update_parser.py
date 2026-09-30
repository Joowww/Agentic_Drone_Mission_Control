import re

from models.mission_update import (
    MissionUpdate,
    WaypointAddition,
    WaypointUpdate,
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


DIRECTION_PATTERN = (
    r"northwest|northeast|southeast|southwest|"
    r"north|east|south|west"
)


def _extract_float(
    text: str,
    patterns: list[str],
) -> float | None:
    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return float(
                match.group(1)
            )

    return None


def _get_waypoint_update(
    updates: dict[str, WaypointUpdate],
    waypoint_id: str,
) -> WaypointUpdate:
    waypoint_id = waypoint_id.upper()

    if waypoint_id not in updates:
        updates[
            waypoint_id
        ] = WaypointUpdate(
            waypoint_id=waypoint_id
        )

    return updates[
        waypoint_id
    ]


def parse_deterministic_mission_update(
    user_input: str,
) -> MissionUpdate:
    text = user_input.strip()

    update = MissionUpdate()

    lower_text = text.lower()

    battery_context_is_other = (
        "battery reserve" in lower_text
        or "battery consumption" in lower_text
    )

    if not battery_context_is_other:
        battery = _extract_float(
            text,
            [
                (
                    r"(?:change|set|update)\s+"
                    r"(?:the\s+)?battery"
                    r"(?:\s+(?:level|percentage))?"
                    r"\s+(?:to\s+)?"
                    r"(-?\d+(?:\.\d+)?)\s*%"
                ),
                (
                    r"\bbattery"
                    r"(?:\s+(?:level|percentage))?"
                    r"\s+(?:is|is now|at|to|=)\s*"
                    r"(-?\d+(?:\.\d+)?)\s*%"
                ),
            ],
        )

        if battery is not None:
            update.battery_percent = (
                battery
            )

    consumption = _extract_float(
        text,
        [
            (
                r"(?:change|set|update)\s+"
                r"(?:the\s+)?battery\s+"
                r"consumption"
                r"(?:\s+(?:rate))?"
                r"\s+(?:to\s+)?"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*%\s*(?:/|per\s+)"
                r"(?:min|minute)"
            ),
            (
                r"\bbattery\s+consumption"
                r"(?:\s+(?:rate))?"
                r"\s+(?:is|at|=)\s*"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*%\s*(?:/|per\s+)"
                r"(?:min|minute)"
            ),
        ],
    )

    if consumption is not None:
        update.battery_consumption_percent_per_minute = (
            consumption
        )

    reserve = _extract_float(
        text,
        [
            (
                r"(?:change|set|update)\s+"
                r"(?:the\s+)?"
                r"(?:battery\s+)?reserve"
                r"\s+(?:to\s+)?"
                r"(-?\d+(?:\.\d+)?)\s*%"
            ),
            (
                r"(?:minimum\s+)?"
                r"(?:battery\s+)?reserve"
                r"\s+(?:is|at|=)\s*"
                r"(-?\d+(?:\.\d+)?)\s*%"
            ),
        ],
    )

    if reserve is not None:
        update.minimum_battery_reserve_percent = (
            reserve
        )

    maximum_wind = _extract_float(
        text,
        [
            (
                r"(?:change|set|update)\s+"
                r"(?:the\s+)?"
                r"(?:maximum|max)\s+"
                r"(?:safe\s+)?wind"
                r"(?:\s+speed)?"
                r"\s+(?:to\s+)?"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*km/?h"
            ),
            (
                r"(?:maximum|max)\s+"
                r"(?:safe\s+)?wind"
                r"(?:\s+speed)?"
                r"\s+(?:is|at|=)\s*"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*km/?h"
            ),
        ],
    )

    if maximum_wind is not None:
        update.maximum_wind_speed_kmh = (
            maximum_wind
        )

    maximum_altitude = _extract_float(
        text,
        [
            (
                r"(?:change|set|update)\s+"
                r"(?:the\s+)?"
                r"(?:maximum|max)\s+altitude"
                r"\s+(?:to\s+)?"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*(?:m|meter|meters)"
            ),
            (
                r"(?:maximum|max)\s+altitude"
                r"\s+(?:is|at|=)\s*"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*(?:m|meter|meters)"
            ),
        ],
    )

    if maximum_altitude is not None:
        update.maximum_altitude_m = (
            maximum_altitude
        )

    is_maximum_wind_command = (
        maximum_wind is not None
    )

    if not is_maximum_wind_command:
        wind_speed = _extract_float(
            text,
            [
                (
                    r"(?:change|set|update)\s+"
                    r"(?:the\s+)?wind"
                    r"(?:\s+speed)?"
                    r"\s+(?:to\s+)?"
                    r"(-?\d+(?:\.\d+)?)"
                    r"\s*km/?h"
                ),
                (
                    r"\bwind"
                    r"(?:\s+speed)?"
                    r"\s+(?:is|is now|at|=)\s*"
                    r"(-?\d+(?:\.\d+)?)"
                    r"\s*km/?h"
                ),
            ],
        )

        if wind_speed is not None:
            update.wind_speed_kmh = (
                wind_speed
            )

            direction_match = re.search(
                (
                    r"(?:coming\s+from|from)\s+"
                    rf"(the\s+)?({DIRECTION_PATTERN})"
                ),
                lower_text,
                flags=re.IGNORECASE,
            )

            if direction_match:
                direction = (
                    direction_match
                    .group(2)
                    .lower()
                )

                update.wind_direction_from = (
                    direction
                )

                update.wind_direction_from_deg = (
                    DIRECTION_BEARINGS[
                        direction
                    ]
                )

            else:
                numeric_direction = (
                    _extract_float(
                        text,
                        [
                            (
                                r"(?:wind\s+direction)"
                                r"\s+(?:to|is|at|=)?\s*"
                                r"(-?\d+(?:\.\d+)?)"
                                r"\s*(?:degrees|deg|°)"
                            ),
                        ],
                    )
                )

                if numeric_direction is not None:
                    update.wind_direction_from_deg = (
                        numeric_direction
                    )

    cruise_speed = _extract_float(
        text,
        [
            (
                r"(?:change|set|update)\s+"
                r"(?:the\s+)?"
                r"(?:cruise|drone|vehicle)\s+speed"
                r"\s+(?:to\s+)?"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*km/?h"
            ),
        ],
    )

    if cruise_speed is not None:
        update.cruise_speed_kmh = (
            cruise_speed
        )

    if re.search(
        r"(?:disable|turn\s+off)\s+"
        r"(?:return\s+to\s+home|rtl)",
        lower_text,
    ):
        update.return_to_home = False

    elif re.search(
        r"(?:enable|turn\s+on)\s+"
        r"(?:return\s+to\s+home|rtl)",
        lower_text,
    ):
        update.return_to_home = True

    waypoint_updates: dict[
        str,
        WaypointUpdate,
    ] = {}

    altitude_pattern = re.compile(
        (
            r"\b(WP\d+)\b"
            r"[^.;\n]*?"
            r"(?:altitude|height)"
            r"\s+(?:to\s+)?"
            r"(-?\d+(?:\.\d+)?)"
            r"\s*(?:m|meter|meters)"
        ),
        flags=re.IGNORECASE,
    )

    for match in altitude_pattern.finditer(
        text
    ):
        waypoint = _get_waypoint_update(
            waypoint_updates,
            match.group(1),
        )

        waypoint.altitude_m = float(
            match.group(2)
        )

    speed_pattern = re.compile(
        (
            r"\b(WP\d+)\b"
            r"[^.;\n]*?"
            r"speed"
            r"\s+(?:to\s+)?"
            r"(-?\d+(?:\.\d+)?)"
            r"\s*km/?h"
        ),
        flags=re.IGNORECASE,
    )

    for match in speed_pattern.finditer(
        text
    ):
        waypoint = _get_waypoint_update(
            waypoint_updates,
            match.group(1),
        )

        waypoint.speed_kmh = float(
            match.group(2)
        )

    action_pattern = re.compile(
        (
            r"\b(WP\d+)\b"
            r"[^.;\n]*?"
            r"(?:action\s+(?:to\s+)?|"
            r"make\s+(?:it\s+)?(?:a\s+)?)"
            r"(navigate|survey|inspect|"
            r"take[_\s]photo|loiter)"
        ),
        flags=re.IGNORECASE,
    )

    for match in action_pattern.finditer(
        text
    ):
        waypoint = _get_waypoint_update(
            waypoint_updates,
            match.group(1),
        )

        action = (
            match.group(2)
            .lower()
            .replace(
                " ",
                "_",
            )
        )

        waypoint.action = action

    update.waypoint_updates = list(
        waypoint_updates.values()
    )

    removal_matches = re.findall(
        r"(?:remove|delete)\s+(WP\d+)",
        text,
        flags=re.IGNORECASE,
    )

    if removal_matches:
        update.waypoint_removals = [
            waypoint.upper()
            for waypoint
            in removal_matches
        ]

    addition_pattern = re.compile(
        (
            r"(?:add|create)\s+"
            r"(WP\d+)"
            r"\s+at\s+latitude\s+"
            r"(-?\d+(?:\.\d+)?)"
            r"\s*,?\s*longitude\s+"
            r"(-?\d+(?:\.\d+)?)"
            r"\s*,?\s*altitude\s+"
            r"(-?\d+(?:\.\d+)?)"
            r"\s*(?:m|meter|meters)"
        ),
        flags=re.IGNORECASE,
    )

    for match in addition_pattern.finditer(
        text
    ):
        update.waypoint_additions.append(
            WaypointAddition(
                waypoint_id=(
                    match.group(1)
                    .upper()
                ),
                latitude=float(
                    match.group(2)
                ),
                longitude=float(
                    match.group(3)
                ),
                altitude_m=float(
                    match.group(4)
                ),
            )
        )

    return update


def mission_update_is_empty(
    update: MissionUpdate,
) -> bool:
    data = update.model_dump(
        exclude_none=True
    )

    for value in data.values():
        if value not in (
            [],
            {},
            None,
        ):
            return False

    return True