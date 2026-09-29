from models.mission_definition import (
    MissionDefinition,
)


def build_waypoint_mission_report(
    mission: MissionDefinition,
    safety_result: dict,
    replan_status: str = "",
    replan_actions: list[str] | None = None,
) -> str:
    if replan_actions is None:
        replan_actions = []

    output = [
        "WAYPOINT MISSION SAFETY REPORT",
        "",
        f"Mission ID: {mission.mission_id}",
        f"Mission name: {mission.name}",
        (
            "Mission status: "
            f"{safety_result['mission_status']}"
        ),
    ]

    flight = safety_result[
        "flight_analysis"
    ]

    output.extend(
        [
            "",
            "ROUTE",
            (
                "Total horizontal distance: "
                f"{flight['total_horizontal_distance_km']} km"
            ),
            (
                "Estimated flight time: "
                f"{flight['total_flight_time_minutes']} minutes"
            ),
            (
                "Route legs: "
                f"{len(flight.get('leg_results', []))}"
            ),
            (
                "Total climb: "
                f"{flight['total_climb_m']} m"
            ),
            (
                "Total descent: "
                f"{flight['total_descent_m']} m"
            ),
        ]
    )

    wind = safety_result[
        "wind_result"
    ]

    output.extend(
        [
            "",
            "WIND SAFETY",
            (
                "Status: "
                f"{wind['status'].upper()}"
            ),
            (
                "Current wind: "
                f"{wind['wind_speed_kmh']} km/h"
            ),
            (
                "Maximum safe wind: "
                f"{wind['max_safe_wind_speed_kmh']} km/h"
            ),
        ]
    )

    altitude = safety_result[
        "altitude_result"
    ]

    output.extend(
        [
            "",
            "ALTITUDE SAFETY",
            (
                "Status: "
                f"{altitude['status'].upper()}"
            ),
            (
                "Highest planned altitude: "
                f"{altitude['highest_altitude_m']} m"
            ),
            (
                "Maximum allowed altitude: "
                f"{altitude['maximum_altitude_m']} m"
            ),
        ]
    )

    battery = safety_result.get(
        "battery_result"
    )

    output.extend(
        [
            "",
            "BATTERY SAFETY",
        ]
    )

    if battery is None:
        output.append(
            "Status: UNDETERMINED"
        )

    else:
        output.extend(
            [
                (
                    "Status: "
                    f"{battery['status'].upper()}"
                ),
                (
                    "Estimated consumption: "
                    f"{battery['required_battery_percent']}%"
                ),
                (
                    "Battery after mission: "
                    f"{battery['battery_after_flight_percent']}%"
                ),
                (
                    "Required reserve: "
                    f"{battery['required_reserve_percent']}%"
                ),
            ]
        )

    failure_reasons = safety_result.get(
        "failure_reasons",
        [],
    )

    if failure_reasons:
        output.extend(
            [
                "",
                "FAILURE REASONS",
            ]
        )

        for reason in failure_reasons:
            output.append(
                f"- {reason}"
            )

    errors = safety_result.get(
        "errors",
        [],
    )

    if errors:
        output.extend(
            [
                "",
                "ERRORS",
            ]
        )

        for error in errors:
            output.append(
                f"- {error}"
            )

    if replan_actions:
        output.extend(
            [
                "",
                "REPLAN PROPOSAL",
                f"Status: {replan_status}",
            ]
        )

        for index, action in enumerate(
            replan_actions,
            start=1,
        ):
            output.append(
                f"{index}. {action}"
            )

    output.extend(
        [
            "",
            "FINAL DECISION",
        ]
    )

    mission_status = safety_result[
        "mission_status"
    ]

    if mission_status == "FEASIBLE":
        output.append(
            "Mission can proceed under the "
            "current validated conditions."
        )

    elif mission_status == "NOT FEASIBLE":
        output.append(
            "Mission must not proceed under "
            "the current conditions."
        )

    else:
        output.append(
            "Mission definition or analysis "
            "must be corrected before execution."
        )

    return "\n".join(
        output
    )