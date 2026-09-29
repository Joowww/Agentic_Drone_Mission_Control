from inputs.json_loader import (
    load_mission_json,
)


def main() -> None:
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    print(
        "\nMISSION LOADED SUCCESSFULLY"
    )

    print(
        f"\nMission ID: {mission.mission_id}"
    )

    print(
        f"Name: {mission.name}"
    )

    print(
        f"Vehicle: {mission.vehicle.vehicle_id}"
    )

    print(
        f"Vehicle type: {mission.vehicle.vehicle_type}"
    )

    print(
        f"Autopilot: {mission.vehicle.autopilot}"
    )

    print(
        f"Objective: {mission.objective.objective_type}"
    )

    print(
        f"Target: {mission.objective.target}"
    )

    print(
        f"Route mode: {mission.route.mode}"
    )

    print(
        f"Waypoints: {len(mission.route.waypoints)}"
    )

    print(
        "Battery: "
        f"{mission.vehicle.battery_percent}%"
    )

    print(
        "Maximum wind: "
        f"{mission.constraints.maximum_wind_speed_kmh} km/h"
    )

    print(
        "Failsafe: "
        f"{mission.failsafe.low_battery_action}"
    )


if __name__ == "__main__":
    main()