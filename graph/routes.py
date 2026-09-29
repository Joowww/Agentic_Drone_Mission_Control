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

def route_after_input_validation(
    state: MissionState,
) -> Literal[
    "checks",
    "report",
]:
    if state.get(
        "missing_fields"
    ):
        print(
            "[ROUTER] Mission information incomplete."
        )

        return "report"

    print(
        "[ROUTER] Mission information complete."
    )

    return "checks"