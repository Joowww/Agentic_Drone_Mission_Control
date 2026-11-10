"""Logical fleet description (``fleet.json``): which vehicles a scenario may assign and how each one can be exported.

Authorities, so the same fact is not kept in two places:
- logical vehicle -> SITL interface: ``tools.simulation_profiles`` (``sim_binding`` only names a vehicle_id
  there and is checked against it);
- vehicle type/autopilot used by a mission: ``models.mission_definition.VehicleDefinition`` (an instantiated
  mission must agree with its fleet entry);
- capabilities, export profile and compatibility: this file.

A logical id (``drone_01``) never identifies a physical airframe: ``physical_identity`` stays
``NOT_ESTABLISHED`` and no serial number or real SYSID is recorded here.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FLEET_SCHEMA = "tfg.fleet/1"
QGC_PROFILE = "QGC_PLAN_ARDUCOPTER"  # family; the exporter states its own profile version


class FleetVehicle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    vehicle_id: str
    category: Literal["sitl_multirotor", "large_drone", "mini_drone", "rover"]
    vehicle_type: Literal["multirotor", "fixed_wing", "vtol", "ugv", "unknown"]
    autopilot: Literal["ArduPilot", "PX4", "unknown"]
    platform: str
    provenance: Literal["SITL", "AVAILABILITY_REFERENCE", "SYNTHETIC_PLACEHOLDER"]
    export_profile: Literal["QGC_PLAN_ARDUCOPTER", "NONE"]
    compatibility: Literal["DOCUMENTED_SITL", "UNRESOLVED_COMPATIBILITY", "NOT_APPLICABLE"]
    sim_binding: str | None = None
    start_zone_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    physical_identity: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    # Needed for an accredited spatial margin; null means no margin can be accredited.
    max_horizontal_extent_m: float | None = Field(None, gt=0)
    horizontal_position_uncertainty_m: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _consistent(self):
        if self.category == "mini_drone" and (self.compatibility != "UNRESOLVED_COMPATIBILITY"
                                               or self.export_profile != "NONE"):
            raise ValueError(f"{self.vehicle_id}: mini drones are UNRESOLVED_COMPATIBILITY with no export profile "
                             "until their platform is documented")
        if self.category == "rover" and self.export_profile != "NONE":
            raise ValueError(f"{self.vehicle_id}: no rover exporter exists; a .plan is not assumed for the rover")
        if self.export_profile == QGC_PROFILE and not (
                self.autopilot == "ArduPilot" and self.vehicle_type == "multirotor"
                and self.compatibility == "DOCUMENTED_SITL"):
            raise ValueError(f"{self.vehicle_id}: {QGC_PROFILE} needs an ArduPilot multirotor documented in SITL")
        return self


class Fleet(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    schema_: Literal["tfg.fleet/1"] = Field(alias="schema")
    fleet_id: str
    version: int = Field(ge=1)
    provenance: str
    vehicles: list[FleetVehicle] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self):
        ids = [v.vehicle_id for v in self.vehicles]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate vehicle_id in fleet")
        return self

    def vehicle(self, vehicle_id: str) -> FleetVehicle | None:
        return next((v for v in self.vehicles if v.vehicle_id == vehicle_id), None)
