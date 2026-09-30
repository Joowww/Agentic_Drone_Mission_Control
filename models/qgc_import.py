from pydantic import (
    BaseModel,
    Field,
)

from models.mission_definition import (
    MissionDefinition,
)


class QGroundControlImportContext(
    BaseModel
):
    battery_percent: float = Field(
        ge=0,
        le=100,
    )

    battery_consumption_percent_per_minute: float = Field(
        gt=0,
    )

    wind_speed_kmh: float = Field(
        ge=0,
    )

    wind_direction_from_deg: float = Field(
        ge=0,
        lt=360,
    )

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

    vehicle_id: str = "qgc_vehicle"


class QGroundControlImportResult(
    BaseModel
):
    mission: MissionDefinition

    warnings: list[str] = Field(
        default_factory=list,
    )

    planned_home_amsl_m: float

    source_item_count: int

    imported_waypoint_count: int