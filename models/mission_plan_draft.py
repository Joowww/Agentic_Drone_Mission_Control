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


VehicleType = Literal[
    "multirotor",
    "fixed_wing",
    "vtol",
    "ugv",
]


AutopilotType = Literal[
    "PX4",
    "ArduPilot",
    "unknown",
]


ObjectiveType = Literal[
    "transit",
    "inspection",
    "survey",
    "precision_agriculture",
    "custom",
]


WaypointAction = Literal[
    "navigate",
    "survey",
    "inspect",
    "take_photo",
    "loiter",
]


FailsafeAction = Literal[
    "RETURN_TO_HOME",
    "HOLD_POSITION",
    "LAND",
    "ABORT_MISSION",
]


class PlannedWaypointDraft(BaseModel):
    waypoint_id: str

    latitude: float | None = None

    longitude: float | None = None

    altitude_m: float | None = None

    speed_kmh: float | None = None

    action: WaypointAction | None = None


class MissionPlanDraft(BaseModel):
    mission_id: str | None = None

    name: str | None = None

    vehicle_id: str | None = None

    vehicle_type: VehicleType | None = None

    autopilot: AutopilotType | None = None

    cruise_speed_kmh: float | None = None

    battery_percent: float | None = None

    battery_consumption_percent_per_minute: (
        float | None
    ) = None

    objective_type: ObjectiveType | None = None

    objective_target: str | None = None

    objective_description: str | None = None

    home_latitude: float | None = None

    home_longitude: float | None = None

    home_altitude_m: float | None = None

    waypoints: list[
        PlannedWaypointDraft
    ] = Field(
        default_factory=list,
    )

    return_to_home: bool | None = None

    wind_speed_kmh: float | None = None

    wind_direction_from: Direction | None = None

    wind_direction_from_deg: float | None = None

    minimum_battery_reserve_percent: (
        float | None
    ) = None

    maximum_wind_speed_kmh: float | None = None

    maximum_altitude_m: float | None = None

    low_battery_action: FailsafeAction | None = None

    unsafe_wind_action: FailsafeAction | None = None

    communication_loss_action: (
        FailsafeAction | None
    ) = None