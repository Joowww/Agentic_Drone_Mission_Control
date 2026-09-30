from langchain_ollama import (
    ChatOllama,
)

from editing.deterministic_update_parser import (
    mission_update_is_empty,
    parse_deterministic_mission_update,
)
from editing.mission_update_guard import (
    validate_update_grounding,
)
from models.mission_definition import (
    MissionDefinition,
)
from models.mission_update import (
    MissionUpdate,
)

DIRECTION_BEARINGS = {
    "north": 0.0,
    "northeast": 45.0,
    "east": 90.0,
    "southeast": 135.0,
    "south": 180.0,
    "southwest": 225.0,
    "west": 270.0,
    "northwest": 315.0,
}


llm = ChatOllama(
    model="qwen3:4b",
    temperature=0,
    reasoning=False,
)


structured_editor = (
    llm.with_structured_output(
        MissionUpdate,
        method="json_schema",
    )
)


def parse_mission_update(
    user_input: str,
    mission: MissionDefinition,
) -> MissionUpdate:
    print(
        "\n[AGENT] Interpreting "
        "mission update..."
    )

    deterministic_update = (
        parse_deterministic_mission_update(
            user_input
        )
    )

    if not mission_update_is_empty(
        deterministic_update
    ):
        print(
            "[MISSION EDITOR] "
            "Deterministic interpretation used."
        )

        return deterministic_update

    print(
        "[MISSION EDITOR] "
        "Using LLM interpretation."
    )

    mission_json = (
        mission.model_dump_json(
            indent=2
        )
    )

    system_prompt = """
You are a structured mission-editing assistant for an autonomous
drone mission-control system.

Your only task is to identify explicit modifications requested by
the user.

The current mission is provided only as context.

STRICT RULES:

- Extract only changes explicitly requested by the user.
- Never invent a mission modification.
- Never remove a waypoint unless the user explicitly asks to
  remove that waypoint.
- Never add a waypoint unless the user explicitly asks to add one.
- Never modify a waypoint unless the user explicitly refers to it.
- Never copy unchanged values from the current mission.
- Do not perform mission feasibility analysis.
- Do not perform safety analysis.
- Do not correct unsafe values.
- Do not silently ignore an explicitly requested value because
  it appears unsafe or invalid.
- If the user asks for battery=150%, extract battery_percent=150.
  Validation is handled by another deterministic component.
- If the user asks for altitude=500 m, extract altitude_m=500.
- Safety validation is NOT your responsibility.
- Percentage values must be numeric.
- Distances and speeds must be numeric.
- Cardinal wind directions must remain words.
- Numeric directions must remain numeric degrees.
- Wind direction always means the direction the wind comes FROM.
- Every modification that is not requested must remain null or
  an empty list.

Examples:

User:
Change the battery to 70%.

Output:
battery_percent=70


User:
Change the battery to 150%.

Output:
battery_percent=150


User:
Set the wind to 18 km/h coming from the west.

Output:
wind_speed_kmh=18
wind_direction_from="west"


User:
Set WP2 altitude to 80 meters.

Output:
waypoint_updates:
- waypoint_id="WP2"
  altitude_m=80


User:
Remove WP3.

Output:
waypoint_removals=["WP3"]


User:
Add WP4 at latitude 41.2, longitude 1.9,
altitude 30 meters.

Output:
waypoint_additions:
- waypoint_id="WP4"
  latitude=41.2
  longitude=1.9
  altitude_m=30


User:
Set the wind to 35 km/h from the north.

INCORRECT:
waypoint_removals=["WP3"]

CORRECT:
wind_speed_kmh=35
wind_direction_from="north"
"""

    result = structured_editor.invoke(
        [
            (
                "system",
                system_prompt,
            ),
            (
                "human",
                (
                    "CURRENT MISSION:\n"
                    f"{mission_json}\n\n"
                    "USER REQUEST:\n"
                    f"{user_input}"
                ),
            ),
        ]
    )

    if (
        result.wind_direction_from_deg
        is None
        and result.wind_direction_from
        is not None
    ):
        result.wind_direction_from_deg = (
            DIRECTION_BEARINGS[
                result.wind_direction_from
            ]
        )

    validate_update_grounding(
        user_input=user_input,
        update=result,
    )

    return result