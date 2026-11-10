from typing import Literal

from planning.relative_routes import RelativeRouteRequest

from pydantic import (
    BaseModel,
    ConfigDict,
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
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    waypoint_id: str

    latitude: float | None = Field(default=None, ge=-90, le=90)

    longitude: float | None = Field(default=None, ge=-180, le=180)

    altitude_m: float | None = Field(default=None, ge=0)

    speed_kmh: float | None = Field(default=None, gt=0)

    action: WaypointAction | None = None


class MissionPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    geometry_intent: RelativeRouteRequest | None = None

    mission_id: str | None = None

    name: str | None = None

    vehicle_id: str | None = None

    vehicle_type: VehicleType | None = None

    autopilot: AutopilotType | None = None

    cruise_speed_kmh: float | None = Field(default=None, gt=0)

    battery_percent: float | None = Field(default=None, ge=0, le=100)

    battery_consumption_percent_per_minute: (
        float | None
    ) = Field(default=None, gt=0)

    objective_type: ObjectiveType | None = None

    objective_target: str | None = None

    objective_description: str | None = None

    home_latitude: float | None = Field(default=None, ge=-90, le=90)

    home_longitude: float | None = Field(default=None, ge=-180, le=180)

    home_altitude_m: float | None = Field(default=None, ge=0)

    waypoints: list[
        PlannedWaypointDraft
    ] = Field(
        default_factory=list,
    )

    return_to_home: bool | None = None

    wind_speed_kmh: float | None = Field(default=None, ge=0)

    wind_direction_from: Direction | None = None

    wind_direction_from_deg: float | None = Field(default=None, ge=0, lt=360)

    minimum_battery_reserve_percent: (
        float | None
    ) = Field(default=None, ge=0, le=100)

    maximum_wind_speed_kmh: float | None = Field(default=None, gt=0)

    maximum_altitude_m: float | None = Field(default=None, gt=0)

    low_battery_action: FailsafeAction | None = None

    unsafe_wind_action: FailsafeAction | None = None

    communication_loss_action: (
        FailsafeAction | None
    ) = None
