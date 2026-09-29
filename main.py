from graph.mission_graph import mission_graph
from graph.state import MissionState


def main() -> None:
    initial_state: MissionState = {
        "distance_km": 15.0,
        "drone_speed_kmh": 40.0,
        "wind_speed_kmh": 12.0,
        "flight_bearing_deg": 90.0,
        "wind_direction_from_deg": 0.0,
        "battery_percent": 10.0,
        "consumption_percent_per_minute": 1.0,
        "reserve_percent": 10.0,
        "max_safe_wind_speed_kmh": 30.0,
    }

    print(
        "\nAGENTIC DRONE MISSION CONTROL"
    )

    print(
        "\nINITIAL MISSION STATE"
    )
    print(
        initial_state
    )

    print(
        "\n[LANGGRAPH] Running mission graph..."
    )

    final_state = mission_graph.invoke(
        initial_state
    )

    print(
        "\nFINAL MISSION STATE"
    )
    print(
        final_state
    )


if __name__ == "__main__":
    main()