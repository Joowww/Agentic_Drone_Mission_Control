from typing import Literal

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

Direction = Literal[
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
]


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


class ExtractedMissionParameters(BaseModel):
    distance_km: float | None = Field(
        ...,
        description=(
            "Requested flight distance in kilometres. "
            "A value expressed in km, but not km/h."
        ),
    )

    drone_speed_kmh: float | None = Field(
        ...,
        description=(
            "Current or newly requested drone airspeed "
            "in kilometres per hour."
        ),
    )

    wind_speed_kmh: float | None = Field(
        ...,
        description=(
            "Current or newly requested wind speed "
            "in kilometres per hour. "
            "Do not confuse it with the maximum safe wind speed."
        ),
    )

    flight_direction: Direction | None = Field(
        ...,
        description=(
            "Cardinal flight direction explicitly stated by the user. "
            "This includes commands that change the flight direction. "
            "Do not convert it to degrees."
        ),
    )

    flight_bearing_deg: float | None = Field(
        ...,
        description=(
            "Numeric flight bearing in degrees only when the user "
            "explicitly provides a numeric bearing. "
            "Do not derive it from a cardinal direction."
        ),
    )

    wind_direction_from: Direction | None = Field(
        ...,
        description=(
            "Cardinal direction the wind is explicitly said to "
            "come FROM. This includes commands that update the wind "
            "direction. Do not convert it to degrees."
        ),
    )

    wind_direction_from_deg: float | None = Field(
        ...,
        description=(
            "Numeric direction in degrees that the wind comes FROM, "
            "only when explicitly given numerically by the user. "
            "Do not derive it from a cardinal direction."
        ),
    )

    battery_percent: float | None = Field(
        ...,
        description=(
            "Current or newly requested drone battery percentage. "
            "This includes update commands such as "
            "'change the battery to 40%'."
        ),
    )

    consumption_percent_per_minute: float | None = Field(
        ...,
        description=(
            "Current or newly requested battery consumption "
            "percentage per minute."
        ),
    )

    reserve_percent: float | None = Field(
        ...,
        description=(
            "Current or newly requested required battery reserve "
            "percentage."
        ),
    )

    max_safe_wind_speed_kmh: float | None = Field(
        ...,
        description=(
            "Current or newly requested maximum safe wind speed "
            "in kilometres per hour."
        ),
    )


llm = ChatOllama(
    model="qwen3:4b",
    temperature=0,
    reasoning=False,
)


structured_llm = llm.with_structured_output(
    ExtractedMissionParameters,
    method="json_schema",
)


def parse_mission(
    user_input: str,
) -> dict:
    print(
        "\n[AGENT] Parsing mission..."
    )

    system_prompt = """
You extract structured parameters and parameter updates from drone mission requests.

Your only job is information extraction.

The user may provide:
1. A complete new mission.
2. A partial mission.
3. An update to one or more parameters of an existing mission.

IMPORTANT:
Commands that change, set or update a value count as explicit information.

Examples:

"Change the battery to 40%."
-> battery_percent=40

"Set the battery to 75%."
-> battery_percent=75

"Update the wind speed to 20 km/h."
-> wind_speed_kmh=20

"Change the drone speed to 45 km/h."
-> drone_speed_kmh=45

"Set the reserve to 20%."
-> reserve_percent=20

"Change the maximum safe wind speed to 25 km/h."
-> max_safe_wind_speed_kmh=25

"Change the flight direction to west."
-> flight_direction="west"

"Set the heading to 180 degrees."
-> flight_bearing_deg=180

"Change the wind direction to south."
-> wind_direction_from="south"

"Set the wind direction to 270 degrees."
-> wind_direction_from_deg=270

"Change the distance to 20 km."
-> distance_km=20

"Change the battery consumption to 1.2% per minute."
-> consumption_percent_per_minute=1.2


Rules:
- Extract only values explicitly stated by the user.
- Never invent missing values.
- Every output field must be present.
- Use null for fields that are not mentioned in the CURRENT user message.
- Do not repeat values from previous messages.
- Do not calculate anything.
- Do not evaluate safety.
- Do not decide mission feasibility.

Important distinctions:
- km means distance.
- km/h associated with the drone means drone speed.
- km/h associated with wind means current wind speed.
- maximum safe wind speed is a separate value.
- "% battery" refers to current battery.
- "% per minute" refers to battery consumption.
- "% reserve" refers to required battery reserve.

Directions:
- Extract cardinal directions as words.
- Do NOT convert cardinal directions into degrees.
- "east" must be extracted as "east".
- "wind coming from the north" means wind_direction_from="north".
- "wind from north" means wind_direction_from="north".
- "wind from north" does NOT mean northwest.
- Only populate a numeric direction field when the user explicitly
  gives that direction numerically in degrees.
"""

    result = structured_llm.invoke(
        [
            (
                "system",
                system_prompt,
            ),
            (
                "human",
                user_input,
            ),
        ]
    )

    extracted = result.model_dump()

    flight_bearing = extracted.get(
        "flight_bearing_deg"
    )

    flight_direction = extracted.get(
        "flight_direction"
    )

    if (
        flight_bearing is None
        and flight_direction is not None
    ):
        extracted["flight_bearing_deg"] = (
            DIRECTION_BEARINGS[
                flight_direction
            ]
        )

    wind_bearing = extracted.get(
        "wind_direction_from_deg"
    )

    wind_direction = extracted.get(
        "wind_direction_from"
    )

    if (
        wind_bearing is None
        and wind_direction is not None
    ):
        extracted["wind_direction_from_deg"] = (
            DIRECTION_BEARINGS[
                wind_direction
            ]
        )

    extracted.pop(
        "flight_direction"
    )

    extracted.pop(
        "wind_direction_from"
    )

    return {
        key: value
        for key, value in extracted.items()
        if value is not None
    }