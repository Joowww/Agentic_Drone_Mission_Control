from models.mission_definition import (
    MissionDefinition,
)
from safety.altitude_guard import (
    check_altitude_safety,
)
from safety.wind_guard import (
    check_wind_safety,
)
from tools.mission_energy_analysis import (
    analyze_mission_energy,
)


def evaluate_mission_safety(
    mission: MissionDefinition,
) -> dict:
    print(
        "\n[MISSION SAFETY] Evaluating mission..."
    )

    energy_analysis = analyze_mission_energy(
        mission
    )

    flight_analysis = energy_analysis[
        "flight_analysis"
    ]

    battery_result = energy_analysis[
        "battery_result"
    ]

    wind_result = check_wind_safety(
        wind_speed_kmh=(
            mission.environment.wind_speed_kmh
        ),
        max_safe_wind_speed_kmh=(
            mission.constraints
            .maximum_wind_speed_kmh
        ),
    )

    waypoint_altitudes = [
        waypoint.altitude_m
        for waypoint in mission.route.waypoints
    ]

    if mission.route.home is not None:
        waypoint_altitudes.append(
            mission.route.home.altitude_m
        )

    altitude_result = check_altitude_safety(
        waypoint_altitudes_m=(
            waypoint_altitudes
        ),
        maximum_altitude_m=(
            mission.constraints
            .maximum_altitude_m
        ),
    )

    failure_reasons = []

    flight_status = flight_analysis.get(
        "status"
    )

    if flight_status != "success":
        failure_reasons.append(
            "One or more route legs cannot be flown "
            "under the current conditions."
        )

    if wind_result.get(
        "status"
    ) == "unsafe":
        failure_reasons.append(
            "Current wind speed exceeds the "
            "mission safety limit."
        )

    if altitude_result.get(
        "status"
    ) == "unsafe":
        failure_reasons.append(
            "The planned route exceeds the "
            "maximum allowed altitude."
        )

    if (
        battery_result is not None
        and battery_result.get("status")
        == "unsafe"
    ):
        failure_reasons.append(
            "The vehicle would finish the mission "
            "below the required battery reserve."
        )

    errors = []

    for result_name, result in [
        (
            "wind",
            wind_result,
        ),
        (
            "altitude",
            altitude_result,
        ),
    ]:
        if result.get(
            "status"
        ) == "error":
            errors.append(
                f"{result_name}: "
                f"{result.get('message')}"
            )

    if (
        battery_result is not None
        and battery_result.get("status")
        == "error"
    ):
        errors.append(
            "battery: "
            f"{battery_result.get('message')}"
        )

    if errors:
        mission_status = "INVALID"

    elif failure_reasons:
        mission_status = "NOT FEASIBLE"

    else:
        mission_status = "FEASIBLE"

    print(
        "[MISSION SAFETY] "
        f"Mission status: {mission_status}"
    )

    return {
        "mission_status":
            mission_status,
        "flight_analysis":
            flight_analysis,
        "wind_result":
            wind_result,
        "altitude_result":
            altitude_result,
        "battery_result":
            battery_result,
        "failure_reasons":
            failure_reasons,
        "errors":
            errors,
    }