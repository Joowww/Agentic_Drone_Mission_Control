import math

from models.mission_definition import (
    MissionDefinition,
)


def generate_waypoint_replan(
    mission: MissionDefinition,
    safety_result: dict,
) -> dict:
    actions = []

    wind_result = safety_result.get(
        "wind_result",
        {},
    )

    altitude_result = safety_result.get(
        "altitude_result",
        {},
    )

    battery_result = safety_result.get(
        "battery_result"
    )

    flight_analysis = safety_result.get(
        "flight_analysis",
        {},
    )

    if wind_result.get(
        "status"
    ) == "unsafe":
        maximum_wind = (
            mission.constraints
            .maximum_wind_speed_kmh
        )

        actions.append(
            "Delay mission execution until wind speed "
            f"is at or below {maximum_wind} km/h."
        )

    if altitude_result.get(
        "status"
    ) == "unsafe":
        maximum_altitude = (
            mission.constraints
            .maximum_altitude_m
        )

        unsafe_waypoints = [
            waypoint.waypoint_id
            for waypoint
            in mission.route.waypoints
            if waypoint.altitude_m
            > maximum_altitude
        ]

        if unsafe_waypoints:
            waypoint_names = ", ".join(
                unsafe_waypoints
            )

            actions.append(
                "Reduce the planned altitude of "
                f"{waypoint_names} to "
                f"{maximum_altitude} m or below."
            )

        else:
            actions.append(
                "Redesign the route so all planned "
                f"altitudes remain at or below "
                f"{maximum_altitude} m."
            )

    if (
        battery_result is not None
        and battery_result.get("status")
        == "unsafe"
    ):
        required_battery = (
            battery_result[
                "required_battery_percent"
            ]
            + battery_result[
                "required_reserve_percent"
            ]
        )

        required_battery = (
            math.ceil(
                required_battery * 10
            )
            / 10
        )

        if required_battery <= 100:
            actions.append(
                "Recharge or replace the battery so "
                "the mission starts with at least "
                f"{required_battery}% battery."
            )

        else:
            actions.append(
                "The mission requires more battery "
                "than a single full charge can provide. "
                "Split the mission into shorter segments "
                "or redesign the route."
            )

    if flight_analysis.get(
        "status"
    ) == "unsafe":
        unsafe_legs = []

        for leg in flight_analysis.get(
            "leg_results",
            [],
        ):
            result = leg.get(
                "flight_result",
                {},
            )

            if result.get(
                "status"
            ) != "success":
                unsafe_legs.append(
                    f"{leg['from']} -> {leg['to']}"
                )

        if unsafe_legs:
            actions.append(
                "Review or redesign the following "
                "unflyable route legs: "
                + ", ".join(
                    unsafe_legs
                )
                + "."
            )

    if not actions:
        return {
            "replan_status":
                "NO REPLAN REQUIRED",
            "replan_actions": [],
        }

    if len(actions) == 1:
        replan_status = (
            "ACTION REQUIRED"
        )

    else:
        replan_status = (
            "MULTIPLE ACTIONS REQUIRED"
        )

    return {
        "replan_status":
            replan_status,
        "replan_actions":
            actions,
    }