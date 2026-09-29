from graph.nodes import (
    battery_check_node,
    flight_check_node,
    wind_check_node,
)
from graph.state import MissionState


def main() -> None:
    mission_state: MissionState = {
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

    print("\nINITIAL MISSION STATE")
    print(mission_state)

    mission_state.update(
        flight_check_node(
            mission_state
        )
    )

    mission_state.update(
        wind_check_node(
            mission_state
        )
    )

    mission_state.update(
        battery_check_node(
            mission_state
        )
    )

    print("\nFINAL MISSION STATE")
    print(mission_state)


if __name__ == "__main__":
    main()