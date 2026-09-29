from typing import TypedDict

from models.mission_definition import (
    MissionDefinition,
)


class WaypointMissionState(
    TypedDict,
    total=False,
):
    mission: MissionDefinition

    mission_status: str

    safety_result: dict

    failure_reasons: list[str]

    errors: list[str]

    replan_status: str

    replan_actions: list[str]

    final_report: str