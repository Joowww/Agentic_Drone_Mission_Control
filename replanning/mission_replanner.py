import math


def generate_replan(
    state: dict,
) -> dict:
    actions = []
    deferred_actions = []

    requires_redesign = False
    requires_reevaluation = False

    flight_result = state.get(
        "flight_result"
    )

    wind_result = state.get(
        "wind_result"
    )

    battery_result = state.get(
        "battery_result"
    )

    flight_unsafe = (
        flight_result is not None
        and flight_result.get("status") == "unsafe"
    )

    wind_unsafe = (
        wind_result is not None
        and wind_result.get("status") == "unsafe"
    )

    battery_unsafe = (
        battery_result is not None
        and battery_result.get("status") == "unsafe"
    )

    if flight_unsafe:
        relative_angle = math.radians(
            state["wind_direction_from_deg"]
            - state["flight_bearing_deg"]
        )

        crosswind_factor = abs(
            math.sin(relative_angle)
        )

        drone_speed = state.get(
            "drone_speed_kmh"
        )

        dynamic_wind_limit = None

        if (
            drone_speed is not None
            and drone_speed > 0
            and crosswind_factor > 1e-9
        ):
            dynamic_wind_limit = (
                drone_speed
                / crosswind_factor
            )

        if (
            wind_unsafe
            and dynamic_wind_limit is not None
        ):
            effective_limit = min(
                state["max_safe_wind_speed_kmh"],
                dynamic_wind_limit,
            )

            actions.append(
                "Delay execution until wind speed is below "
                f"{effective_limit:.1f} km/h for the current "
                "route and wind direction, or redesign the route."
            )

        elif dynamic_wind_limit is not None:
            actions.append(
                "Reduce the crosswind conditions so wind speed "
                f"is below {dynamic_wind_limit:.1f} km/h for "
                "the current wind direction, or redesign the route."
            )

        else:
            actions.append(
                "Change the route or wait for wind conditions "
                "that produce safe flight dynamics."
            )

        deferred_actions.append(
            "Recalculate flight time and battery requirements "
            "after the route or wind conditions are updated."
        )

        requires_redesign = True
        requires_reevaluation = True

    elif wind_unsafe:
        actions.append(
            "Delay execution until wind speed is at or below "
            f"{state.get('max_safe_wind_speed_kmh')} km/h."
        )

        deferred_actions.append(
            "Recalculate flight dynamics and battery requirements "
            "after the wind speed is updated."
        )

        requires_reevaluation = True

    elif battery_unsafe:
        required_start = (
            battery_result[
                "required_battery_percent"
            ]
            + state["reserve_percent"]
        )

        minimum_start = (
            math.ceil(
                required_start * 10
            )
            / 10
        )

        if minimum_start <= 100:
            actions.append(
                "Recharge or replace the battery so the mission "
                f"starts with at least {minimum_start}% battery."
            )

        else:
            actions.append(
                "The mission requires more than 100% battery "
                "under the current conditions. Split the mission "
                "into multiple stages, add a recharge or battery "
                "swap stop, or redesign the route."
            )

            requires_redesign = True

    if not actions:
        actions.append(
            "No deterministic corrective action could be generated."
        )

    if requires_redesign:
        replan_status = (
            "MISSION REDESIGN OR ENVIRONMENTAL UPDATE REQUIRED"
        )

    elif requires_reevaluation:
        replan_status = (
            "ENVIRONMENTAL UPDATE AND RE-EVALUATION REQUIRED"
        )

    else:
        replan_status = "ACTION REQUIRED"

    return {
        "replan_status": replan_status,
        "replan_actions": actions,
        "replan_deferred_actions": deferred_actions,
        "replan_requires_reevaluation":
            requires_reevaluation,
    }