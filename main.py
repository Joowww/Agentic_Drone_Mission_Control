from graph.waypoint_mission_graph import (
    waypoint_mission_graph,
)
from inputs.json_loader import (
    load_mission_json,
)


def main() -> None:
    mission = load_mission_json(
        "missions/examples/"
        "precision_agriculture_demo.json"
    )

    print(
        "\nAGENTIC DRONE MISSION CONTROL"
    )

    print(
        "\n[JSON] Mission loaded successfully."
    )

    print(
        "\n[LANGGRAPH] Running waypoint "
        "mission graph..."
    )

    final_state = (
        waypoint_mission_graph.invoke(
            {
                "mission": mission,
            }
        )
    )

    print(
        "\nAGENT:"
    )

    print(
        final_state[
            "final_report"
        ]
    )


if __name__ == "__main__":
    main()