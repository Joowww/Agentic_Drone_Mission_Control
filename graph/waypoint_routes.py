from typing import Literal

from graph.waypoint_state import (
    WaypointMissionState,
)


def route_after_waypoint_evaluation(
    state: WaypointMissionState,
) -> Literal[
    "replan",
    "report",
]:
    if (
        state.get("mission_status")
        == "NOT FEASIBLE"
    ):
        print(
            "[ROUTER] Waypoint mission "
            "requires replanning."
        )

        return "replan"

    print(
        "[ROUTER] Waypoint mission "
        "does not require replanning."
    )

    return "report"