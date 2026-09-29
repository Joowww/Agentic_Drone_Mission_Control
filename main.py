from inputs.json_loader import (
    load_mission_json,
)
from safety.mission_safety_analysis import (
    evaluate_mission_safety,
)


def main() -> None:
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    result = evaluate_mission_safety(
        mission
    )

    print(
        "\nMISSION"
    )

    print(
        mission.name
    )

    print(
        "\nFINAL MISSION STATUS"
    )

    print(
        result["mission_status"]
    )

    flight = result[
        "flight_analysis"
    ]

    print(
        "\nFLIGHT"
    )

    print(
        "Distance: "
        f"{flight['total_horizontal_distance_km']} km"
    )

    print(
        "Estimated flight time: "
        f"{flight['total_flight_time_minutes']} minutes"
    )

    wind = result[
        "wind_result"
    ]

    print(
        "\nWIND"
    )

    print(
        f"Status: {wind['status'].upper()}"
    )

    print(
        f"Current wind: "
        f"{wind['wind_speed_kmh']} km/h"
    )

    print(
        "Maximum safe wind: "
        f"{wind['max_safe_wind_speed_kmh']} km/h"
    )

    altitude = result[
        "altitude_result"
    ]

    print(
        "\nALTITUDE"
    )

    print(
        f"Status: {altitude['status'].upper()}"
    )

    print(
        "Highest planned altitude: "
        f"{altitude['highest_altitude_m']} m"
    )

    print(
        "Maximum allowed altitude: "
        f"{altitude['maximum_altitude_m']} m"
    )

    battery = result[
        "battery_result"
    ]

    print(
        "\nBATTERY"
    )

    if battery is None:
        print(
            "Status: UNDETERMINED"
        )

    else:
        print(
            f"Status: {battery['status'].upper()}"
        )

        print(
            "Battery after mission: "
            f"{battery['battery_after_flight_percent']}%"
        )

        print(
            "Required reserve: "
            f"{battery['required_reserve_percent']}%"
        )

    failure_reasons = result[
        "failure_reasons"
    ]

    if failure_reasons:
        print(
            "\nFAILURE REASONS"
        )

        for reason in failure_reasons:
            print(
                f"- {reason}"
            )


if __name__ == "__main__":
    main()