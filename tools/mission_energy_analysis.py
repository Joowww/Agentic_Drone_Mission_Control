from models.mission_definition import (
    MissionDefinition,
)
from safety.battery_guard import (
    check_battery_safety,
)
from tools.route_flight_analysis import (
    analyze_mission_flight,
)


def analyze_mission_energy(
    mission: MissionDefinition,
) -> dict:
    flight_analysis = analyze_mission_flight(
        mission
    )

    if flight_analysis["status"] != "success":
        return {
            "status": "undetermined",
            "flight_analysis": flight_analysis,
            "battery_result": None,
            "message": (
                "Battery requirements cannot be evaluated "
                "because the route contains an unsafe "
                "or invalid flight leg."
            ),
        }

    total_flight_time_minutes = (
        flight_analysis[
            "total_flight_time_minutes"
        ]
    )

    battery_result = check_battery_safety(
        flight_time_minutes=(
            total_flight_time_minutes
        ),
        battery_percent=(
            mission.vehicle.battery_percent
        ),
        consumption_percent_per_minute=(
            mission.vehicle
            .battery_consumption_percent_per_minute
        ),
        reserve_percent=(
            mission.constraints
            .minimum_battery_reserve_percent
        ),
    )

    return {
        "status": battery_result[
            "status"
        ],
        "flight_analysis": flight_analysis,
        "battery_result": battery_result,
    }