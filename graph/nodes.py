from graph.state import MissionState
from replanning.mission_replanner import generate_replan
from reporting.mission_report import build_mission_report
from safety.battery_guard import check_battery_safety
from safety.mission_validator import validate_mission
from safety.wind_guard import check_wind_safety
from tools.flight_dynamics import calculate_flight_time


def flight_check_node(
    state: MissionState,
) -> dict:
    print("\n[NODE] flight_check")

    result = calculate_flight_time(
        distance_km=state["distance_km"],
        drone_speed_kmh=state["drone_speed_kmh"],
        wind_speed_kmh=state["wind_speed_kmh"],
        flight_bearing_deg=state["flight_bearing_deg"],
        wind_direction_from_deg=state[
            "wind_direction_from_deg"
        ],
    )

    return {
        "flight_result": result,
    }


def wind_check_node(
    state: MissionState,
) -> dict:
    print("\n[NODE] wind_check")

    result = check_wind_safety(
        wind_speed_kmh=state["wind_speed_kmh"],
        max_safe_wind_speed_kmh=state[
            "max_safe_wind_speed_kmh"
        ],
    )

    return {
        "wind_result": result,
    }


def battery_check_node(
    state: MissionState,
) -> dict:
    print("\n[NODE] battery_check")

    flight_result = state.get(
        "flight_result"
    )

    if (
        flight_result is None
        or flight_result.get("status") != "success"
    ):
        return {
            "battery_result": {
                "status": "error",
                "message": (
                    "Battery safety requires a valid "
                    "flight-time result."
                ),
            }
        }

    result = check_battery_safety(
        flight_time_minutes=flight_result[
            "flight_time_minutes"
        ],
        battery_percent=state["battery_percent"],
        consumption_percent_per_minute=state[
            "consumption_percent_per_minute"
        ],
        reserve_percent=state["reserve_percent"],
    )

    return {
        "battery_result": result,
    }

def evaluate_plan_node(
    state: MissionState,
) -> dict:
    print("\n[NODE] evaluate_plan")

    result = validate_mission(
        state
    )

    print(
        "[SAFETY VALIDATOR] Mission status: "
        f"{result['mission_status']}"
    )

    return result

def replanner_node(
    state: MissionState,
) -> dict:
    print("\n[NODE] replanner")

    result = generate_replan(
        state
    )

    print(
        "[REPLANNER] "
        f"{result['replan_status']}"
    )

    return result

def final_report_node(
    state: MissionState,
) -> dict:
    print("\n[NODE] final_report")

    report = build_mission_report(
        state
    )

    return {
        "final_report": report,
        "response": report,
    }