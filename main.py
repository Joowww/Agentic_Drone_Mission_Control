from inputs.json_loader import (
    load_mission_json,
)
from tools.route_geometry import (
    analyze_waypoint_route,
)


def main() -> None:
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    route_analysis = analyze_waypoint_route(
        mission.route
    )

    print(
        "\nMISSION"
    )

    print(
        f"{mission.name}"
    )

    print(
        "\nROUTE ANALYSIS"
    )

    print(
        "Total horizontal distance: "
        f"{route_analysis['total_horizontal_distance_km']} km"
    )

    print(
        "Total climb: "
        f"{route_analysis['total_climb_m']} m"
    )

    print(
        "Total descent: "
        f"{route_analysis['total_descent_m']} m"
    )

    print(
        "Route legs: "
        f"{route_analysis['leg_count']}"
    )

    print(
        "\nLEGS"
    )

    for leg in route_analysis[
        "legs"
    ]:
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
            "Altitude: "
            f"{leg['start_altitude_m']} m -> "
            f"{leg['end_altitude_m']} m"
        )

        print(
            "Action: "
            f"{leg['destination_action']}"
        )


if __name__ == "__main__":
    main()