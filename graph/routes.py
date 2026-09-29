from typing import Literal

from graph.state import MissionState


def route_after_evaluation(
    state: MissionState,
) -> Literal[
    "replan",
    "report",
]:
    if (
        state.get("mission_status")
        == "NOT FEASIBLE"
    ):
        print(
            "[ROUTER] Mission requires replanning."
        )

        return "replan"

    print(
        "[ROUTER] No replanning required."
    )

    return "report"