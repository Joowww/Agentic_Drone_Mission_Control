"""Scenario template: the tasks, separated from where they happen.

Tasks name site points (POIs, planned takeoff, rover start) and fleet vehicles by id; the site resolves the
coordinates at instantiation. Only explicit POI visits are expressed: no coverage pattern, no route between
trees and no crop detection. Dependencies are logical conditions on observed outcomes, never time waits.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from models.mission_definition import FailsafeDefinition

TEMPLATE_SCHEMA = "tfg.scenario-template/1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MissionDefaults(_Strict):
    """Declared planning inputs copied into each MissionDefinition (not measurements)."""
    cruise_speed_kmh: float = Field(gt=0)
    battery_percent: float = Field(ge=0, le=100)
    battery_consumption_percent_per_minute: float = Field(gt=0)
    wind_speed_kmh: float = Field(ge=0)
    wind_direction_from_deg: float = Field(ge=0, lt=360)
    minimum_battery_reserve_percent: float = Field(ge=0, le=100)
    maximum_wind_speed_kmh: float = Field(gt=0)
    maximum_altitude_m: float = Field(gt=0)
    failsafe: FailsafeDefinition
    source: str


class AerialTask(_Strict):
    task_id: str
    vehicle_id: str
    takeoff_point: str
    poi_sequence: list[str] = Field(min_length=1)
    altitude_m: float = Field(gt=0)
    altitude_reference: Literal["relative_to_effective_home"] = "relative_to_effective_home"
    requested_speed_kmh: float | None = Field(None, gt=0)
    end: Literal["RETURN_TO_LAUNCH"] = "RETURN_TO_LAUNCH"


class GroundTask(_Strict):
    task_id: str
    vehicle_id: str
    start_point: str
    target_point: str
    kind: Literal["VISIT_AND_STOP"] = "VISIT_AND_STOP"


class Dependency(_Strict):
    task_id: str
    after: str
    condition: Literal["COMPLETED", "POI_REACHED"]
    point: str | None = None


class ScenarioTemplate(_Strict):
    schema_: Literal["tfg.scenario-template/1"] = Field(alias="schema")
    template_id: str
    version: int = Field(ge=1)
    description: str
    provenance: str
    planning_margin_m: float = Field(ge=0)  # declared, NOT an accredited safety margin
    mission_defaults: MissionDefaults
    aerial_tasks: list[AerialTask] = Field(default_factory=list)
    ground_tasks: list[GroundTask] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)
