def build_mission_report(
    state: dict,
) -> str:
    output = [
        "MISSION SAFETY REPORT",
        "",
        f"Mission status: {state.get('mission_status', 'UNDETERMINED')}",
        "",
        "FLIGHT DYNAMICS",
    ]

    flight = state.get(
        "flight_result"
    )

    if flight is None:
        output.append(
            "Status: UNDETERMINED"
        )

    elif flight.get("status") == "success":
        output.extend(
            [
                "Status: SAFE",
                (
                    "Estimated flight time: "
                    f"{flight['flight_time_minutes']} minutes"
                ),
                (
                    "Estimated ground speed: "
                    f"{flight['ground_speed_kmh']} km/h"
                ),
                (
                    "Headwind component: "
                    f"{flight['headwind_component_kmh']} km/h"
                ),
                (
                    "Crosswind component: "
                    f"{flight['crosswind_component_kmh']} km/h"
                ),
            ]
        )

    else:
        output.extend(
            [
                f"Status: {flight.get('status', 'unknown').upper()}",
                flight.get(
                    "message",
                    "Unknown flight-dynamics result.",
                ),
            ]
        )

    output.extend(
        [
            "",
            "WIND SAFETY",
        ]
    )

    wind = state.get(
        "wind_result"
    )

    if wind is None:
        output.append(
            "Status: UNDETERMINED"
        )

    elif wind.get("status") in {
        "safe",
        "unsafe",
    }:
        output.extend(
            [
                f"Status: {wind['status'].upper()}",
                (
                    "Wind speed: "
                    f"{wind['wind_speed_kmh']} km/h"
                ),
                (
                    "Maximum safe wind speed: "
                    f"{wind['max_safe_wind_speed_kmh']} km/h"
                ),
            ]
        )

    else:
        output.extend(
            [
                "Status: ERROR",
                wind.get(
                    "message",
                    "Unknown wind-safety result.",
                ),
            ]
        )

    output.extend(
        [
            "",
            "BATTERY SAFETY",
        ]
    )

    battery = state.get(
        "battery_result"
    )

    if battery is None:
        output.append(
            "Status: UNDETERMINED"
        )

    elif battery.get("status") in {
        "safe",
        "unsafe",
    }:
        output.extend(
            [
                f"Status: {battery['status'].upper()}",
                (
                    "Estimated battery consumption: "
                    f"{battery['required_battery_percent']}%"
                ),
                (
                    "Estimated battery after flight: "
                    f"{battery['battery_after_flight_percent']}%"
                ),
                (
                    "Required battery reserve: "
                    f"{battery['required_reserve_percent']}%"
                ),
            ]
        )

    else:
        output.extend(
            [
                "Status: ERROR",
                battery.get(
                    "message",
                    "Unknown battery-safety result.",
                ),
            ]
        )

    failure_reasons = state.get(
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

    replan_actions = state.get(
        "replan_actions",
        [],
    )

    if replan_actions:
        output.extend(
            [
                "",
                "REPLAN PROPOSAL",
                (
                    "Status: "
                    f"{state.get('replan_status', 'UNKNOWN')}"
                ),
            ]
        )

        for index, action in enumerate(
            replan_actions,
            start=1,
        ):
            output.append(
                f"{index}. {action}"
            )

    deferred_actions = state.get(
        "replan_deferred_actions",
        [],
    )

    if deferred_actions:
        output.extend(
            [
                "",
                "DEFERRED ACTIONS",
            ]
        )

        for index, action in enumerate(
            deferred_actions,
            start=1,
        ):
            output.append(
                f"{index}. {action}"
            )

    status = state.get(
        "mission_status"
    )

    output.extend(
        [
            "",
            "FINAL DECISION",
        ]
    )

    if status == "FEASIBLE":
        output.append(
            "Mission can proceed under the current validated conditions."
        )

    elif status == "NOT FEASIBLE":
        output.append(
            "Mission must not proceed under the current conditions."
        )

    elif status == "INVALID":
        output.append(
            "Mission data must be corrected before execution."
        )

    else:
        output.append(
            "Additional mission information is required before execution."
        )

    return "\n".join(
        output
    )