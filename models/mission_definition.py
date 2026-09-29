from typing import Literal

from pydantic import (
    BaseModel,
    Field,
    model_validator,
)


class GeoPoint(BaseModel):
    latitude: float = Field(
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ge=-180,
        le=180,
    )

    altitude_m: float = Field(
        ge=0,
    )


class Waypoint(BaseModel):
    waypoint_id: str

    latitude: float = Field(
        ge=-90,
        le=90,
    )

    longitude: float = Field(
        ge=-180,
        le=180,
    )

    altitude_m: float = Field(
        ge=0,
    )

    speed_kmh: float | None = Field(
        default=None,
        gt=0,
    )

    action: Literal[
        "navigate",
        "survey",
        "inspect",
        "take_photo",
        "loiter",
    ] = "navigate"


class VehicleDefinition(BaseModel):
    vehicle_id: str

    vehicle_type: Literal[
        "multirotor",
        "fixed_wing",
        "vtol",
        "ugv",
    ]

    autopilot: Literal[
        "PX4",
        "ArduPilot",
        "unknown",
    ] = "unknown"

    cruise_speed_kmh: float = Field(
        gt=0,
    )

    battery_percent: float = Field(
        ge=0,
        le=100,
    )

    battery_consumption_percent_per_minute: float = Field(
        gt=0,
    )


class ObjectiveDefinition(BaseModel):
    objective_type: Literal[
        "transit",
        "inspection",
        "survey",
        "precision_agriculture",
        "custom",
    ]

    target: str

    description: str | None = None


class RouteDefinition(BaseModel):
    mode: Literal[
        "relative",
        "waypoints",
    ]

    distance_km: float | None = Field(
        default=None,
        gt=0,
    )

    bearing_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
    )

    home: GeoPoint | None = None

    waypoints: list[Waypoint] = Field(
        default_factory=list,
    )

    return_to_home: bool = True

    @model_validator(
        mode="after"
    )
    def validate_route(
        self,
    ):
        if self.mode == "relative":
            if (
                self.distance_km is None
                or self.bearing_deg is None
            ):
                raise ValueError(
                    "A relative route requires "
                    "distance_km and bearing_deg."
                )

        if self.mode == "waypoints":
            if not self.waypoints:
                raise ValueError(
                    "A waypoint route requires at least "
                    "one waypoint."
                )

        return self


class EnvironmentDefinition(BaseModel):
    wind_speed_kmh: float = Field(
        ge=0,
    )

    wind_direction_from_deg: float = Field(
        ge=0,
        lt=360,
    )


class ConstraintDefinition(BaseModel):
    minimum_battery_reserve_percent: float = Field(
        ge=0,
        le=100,
    )

    maximum_wind_speed_kmh: float = Field(
        gt=0,
    )

    maximum_altitude_m: float = Field(
        gt=0,
    )


FailsafeAction = Literal[
    "RETURN_TO_HOME",
    "HOLD_POSITION",
    "LAND",
    "ABORT_MISSION",
]


class FailsafeDefinition(BaseModel):
    low_battery_action: FailsafeAction = (
        "RETURN_TO_HOME"
    )

    unsafe_wind_action: FailsafeAction = (
        "RETURN_TO_HOME"
    )

    communication_loss_action: FailsafeAction = (
        "RETURN_TO_HOME"
    )


class MissionDefinition(BaseModel):
    schema_version: str = "1.0"

    mission_id: str

    name: str

    source: Literal[
        "natural_language",
        "json",
        "qgroundcontrol",
        "api",
        "web_map",
    ] = "json"

    vehicle: VehicleDefinition

    objective: ObjectiveDefinition

    route: RouteDefinition

    environment: EnvironmentDefinition

    constraints: ConstraintDefinition

    failsafe: FailsafeDefinition