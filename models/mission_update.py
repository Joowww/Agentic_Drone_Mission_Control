from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)

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


WaypointAction = Literal[
    "navigate",
    "survey",
    "inspect",
    "take_photo",
    "loiter",
]


ObjectiveType = Literal[
    "transit",
    "inspection",
    "survey",
    "precision_agriculture",
    "custom",
]


class WaypointUpdate(BaseModel):
    waypoint_id: str

    latitude: float | None = Field(
        default=None,
    )

    longitude: float | None = Field(
        default=None,
    )

    altitude_m: float | None = Field(
        default=None,
    )

    speed_kmh: float | None = Field(
        default=None,
    )

    action: WaypointAction | None = Field(
        default=None,
    )


class WaypointAddition(BaseModel):
    waypoint_id: str

    latitude: float

    longitude: float

    altitude_m: float

    speed_kmh: float | None = None

    action: WaypointAction = "navigate"


class MissionUpdate(BaseModel):
    mission_name: str | None = None

    vehicle_id: str | None = None

    cruise_speed_kmh: float | None = None

    battery_percent: float | None = None

    battery_consumption_percent_per_minute: float | None = None

    objective_type: ObjectiveType | None = None

    objective_target: str | None = None

    objective_description: str | None = None

    wind_speed_kmh: float | None = None

    wind_direction_from: Direction | None = None

    wind_direction_from_deg: float | None = None

    minimum_battery_reserve_percent: float | None = None

    maximum_wind_speed_kmh: float | None = None

    maximum_altitude_m: float | None = None

    return_to_home: bool | None = None

    home_latitude: float | None = None

    home_longitude: float | None = None

    home_altitude_m: float | None = None

    waypoint_updates: list[WaypointUpdate] = Field(
        default_factory=list,
    )

    waypoint_additions: list[WaypointAddition] = Field(
        default_factory=list,
    )

    waypoint_removals: list[str] = Field(
        default_factory=list,
    )