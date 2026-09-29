from inputs.json_loader import (
    load_mission_json,
)
from tools.route_flight_analysis import (
    analyze_mission_flight,
)


def main() -> None:
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    analysis = analyze_mission_flight(
        mission
    )

    print(
        "\nMISSION"
    )

    print(
        mission.name
    )

    print(
        "\nMISSION FLIGHT ANALYSIS"
    )

    print(
        "Total horizontal distance: "
        f"{analysis['total_horizontal_distance_km']} km"
    )

    print(
        "Total estimated flight time: "
        f"{analysis['total_flight_time_minutes']} minutes"
    )

    print(
        "Total climb: "
        f"{analysis['total_climb_m']} m"
    )

    print(
        "Total descent: "
        f"{analysis['total_descent_m']} m"
    )

    print(
        "\nLEG ANALYSIS"
    )

    for leg in analysis[
        "leg_results"
    ]:
        result = leg[
            "flight_result"
        ]

        print(
            "\n"
            f"Leg {leg['leg_number']}: "
            f"{leg['from']} -> {leg['to']}"
        )

        print(
            f"Distance: {leg['distance_km']} km"
        )

        print(
            f"Bearing: {leg['bearing_deg']}°"
        )

        print(
            f"Airspeed: {leg['airspeed_kmh']} km/h"
        )

        print(
            f"Status: {result['status'].upper()}"
        )

        if result[
            "status"
        ] == "success":
            print(
                "Ground speed: "
                f"{result['ground_speed_kmh']} km/h"
            )

            print(
                "Headwind: "
                f"{result['headwind_component_kmh']} km/h"
            )

            print(
                "Crosswind: "
                f"{result['crosswind_component_kmh']} km/h"
            )

            print(
                "Flight time: "
                f"{result['flight_time_minutes']} minutes"
            )

        else:
            print(
                "Reason: "
                f"{result.get('message')}"
            )


if __name__ == "__main__":
    main()