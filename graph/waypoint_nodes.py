from graph.waypoint_state import (
    WaypointMissionState,
)
from replanning.waypoint_mission_replanner import (
    generate_waypoint_replan,
)
from reporting.waypoint_mission_report import (
    build_waypoint_mission_report,
)
from safety.mission_safety_analysis import (
    evaluate_mission_safety,
)


def evaluate_waypoint_mission_node(
    state: WaypointMissionState,
) -> dict:
    print(
        "\n[NODE] evaluate_waypoint_mission"
    )

    mission = state[
        "mission"
    ]

    result = evaluate_mission_safety(
        mission
    )

    return {
        "mission_status":
            result["mission_status"],
        "safety_result":
            result,
        "failure_reasons":
            result["failure_reasons"],
        "errors":
            result["errors"],
        "replan_status": "",
        "replan_actions": [],
    }


def waypoint_replanner_node(
    state: WaypointMissionState,
) -> dict:
    print(
        "\n[NODE] waypoint_replanner"
    )

    result = generate_waypoint_replan(
        mission=state["mission"],
        safety_result=state[
            "safety_result"
        ],
    )

    print(
        "[WAYPOINT REPLANNER] "
        f"{result['replan_status']}"
    )

    return result


def waypoint_final_report_node(
    state: WaypointMissionState,
) -> dict:
    print(
        "\n[NODE] waypoint_final_report"
    )

    report = build_waypoint_mission_report(
        mission=state["mission"],
        safety_result=state[
            "safety_result"
        ],
        replan_status=state.get(
            "replan_status",
            "",
        ),
        replan_actions=state.get(
            "replan_actions",
            [],
        ),
    )

    return {
        "final_report":
            report,
    }