from inputs.json_loader import (
    load_mission_json,
)
from tools.mission_energy_analysis import (
    analyze_mission_energy,
)


def main() -> None:
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    analysis = analyze_mission_energy(
        mission
    )

    flight = analysis[
        "flight_analysis"
    ]

    battery = analysis[
        "battery_result"
    ]

    print(
        "\nMISSION"
    )

    print(
        mission.name
    )

    print(
        "\nFLIGHT ANALYSIS"
    )

    print(
        "Total horizontal distance: "
        f"{flight['total_horizontal_distance_km']} km"
    )

    print(
        "Total estimated flight time: "
        f"{flight['total_flight_time_minutes']} minutes"
    )

    print(
        "\nBATTERY ANALYSIS"
    )

    if battery is None:
        print(
            "Status: UNDETERMINED"
        )

        print(
            analysis["message"]
        )

        return

    print(
        f"Status: {battery['status'].upper()}"
    )

    print(
        "Starting battery: "
        f"{mission.vehicle.battery_percent}%"
    )

    print(
        "Consumption rate: "
        f"{mission.vehicle.battery_consumption_percent_per_minute}%/min"
    )

    print(
        "Estimated consumption: "
        f"{battery['required_battery_percent']}%"
    )

    print(
        "Estimated battery after mission: "
        f"{battery['battery_after_flight_percent']}%"
    )

    print(
        "Required reserve: "
        f"{battery['required_reserve_percent']}%"
    )


if __name__ == "__main__":
    main()