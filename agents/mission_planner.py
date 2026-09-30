from langchain_ollama import (
    ChatOllama,
)

from models.mission_plan_draft import (
    MissionPlanDraft,
)
from planning.deterministic_plan_parser import (
    parse_deterministic_plan_fields,
)

llm = ChatOllama(
    model="qwen3:4b",
    temperature=0,
    reasoning=False,
)


structured_planner = (
    llm.with_structured_output(
        MissionPlanDraft,
        method="json_schema",
    )
)


def _merge_draft_sources(
    llm_draft: MissionPlanDraft,
    deterministic_draft: MissionPlanDraft,
) -> MissionPlanDraft:
    llm_data = llm_draft.model_dump(
        mode="python"
    )

    deterministic_data = (
        deterministic_draft.model_dump(
            mode="python"
        )
    )

    for key, value in (
        deterministic_data.items()
    ):
        if key == "waypoints":
            continue

        if value is not None:
            llm_data[
                key
            ] = value

    return MissionPlanDraft.model_validate(
        llm_data
    )


def extract_mission_plan_draft(
    user_input: str,
    current_draft: MissionPlanDraft | None = None,
) -> MissionPlanDraft:
    print(
        "\n[AGENT] Planning mission..."
    )

    deterministic_draft = (
        parse_deterministic_plan_fields(
            user_input
        )
    )

    if current_draft is None:
        current_context = "{}"

    else:
        current_context = (
            current_draft.model_dump_json(
                indent=2
            )
        )

    system_prompt = """
You are a structured mission-planning assistant for an autonomous
drone mission-control system.

Your ONLY responsibility is information extraction.

You receive:
1. The current mission draft.
2. New information from the operator.

Return only mission information explicitly stated in the CURRENT
operator message.

STRICT RULES:

- Never invent coordinates.
- Never invent waypoints.
- Never invent battery values.
- Never invent wind conditions.
- Never invent vehicle performance.
- Never invent safety limits.
- Never invent an objective.
- Never invent a mission name.
- Never invent an autopilot.
- Never invent an action.
- Never perform mission feasibility analysis.
- Never perform safety calculations.
- Never calculate distances.
- Never silently correct unsafe values.
- Missing information must remain null.
- Do not repeat information from the current draft unless the
  operator explicitly states it again.

IMPORTANT TERMINOLOGY:

"precision agriculture"
-> objective_type="precision_agriculture"

"precision farming"
-> objective_type="precision_agriculture"

"inspection"
-> objective_type="inspection"

"survey"
-> objective_type="survey"

"transit"
-> objective_type="transit"

"multirotor"
-> vehicle_type="multirotor"

"quadcopter"
-> vehicle_type="multirotor"

"PX4"
-> autopilot="PX4"

"ArduPilot"
-> autopilot="ArduPilot"

COORDINATES:

Latitude and longitude are decimal degrees.

WAYPOINTS:

Preserve explicitly provided waypoint IDs.

Example:

WP2 is latitude 41.278, longitude 1.992,
altitude 30 meters, speed 25 km/h, action survey.

-> waypoint_id="WP2"
-> latitude=41.278
-> longitude=1.992
-> altitude_m=30
-> speed_kmh=25
-> action="survey"

WIND:

Wind direction is the direction the wind comes FROM.

"The wind is 12 km/h from the north."

-> wind_speed_kmh=12
-> wind_direction_from="north"

Do not convert cardinal wind directions into degrees.
Deterministic Python code handles that later.

BATTERY:

"Battery is 82%."
-> battery_percent=82

"Consumption is 0.8% per minute."
-> battery_consumption_percent_per_minute=0.8

If something is not explicitly present in the CURRENT message,
leave it null.
"""

    llm_draft = (
        structured_planner.invoke(
            [
                (
                    "system",
                    system_prompt,
                ),
                (
                    "human",
                    (
                        "CURRENT DRAFT:\n"
                        f"{current_context}\n\n"
                        "CURRENT OPERATOR INPUT:\n"
                        f"{user_input}"
                    ),
                ),
            ]
        )
    )

    result = _merge_draft_sources(
        llm_draft=llm_draft,
        deterministic_draft=(
            deterministic_draft
        ),
    )

    deterministic_values = (
        deterministic_draft.model_dump(
            exclude_none=True
        )
    )

    deterministic_values.pop(
        "waypoints",
        None,
    )

    if deterministic_values:
        fields = ", ".join(
            deterministic_values.keys()
        )

        print(
            "[MISSION PLANNER] "
            "Deterministic grounding: "
            f"{fields}"
        )

    return result