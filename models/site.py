"""Versioned site description (``site.json``): a DroneLab, a plot or an orchard.

The site is the authority for WHERE things are: its local frame, perimeter, exclusions, allowed zones and
named points. It does not hold missions, vehicles or approvals. Measurements may be absent (``null``):
a template still parses, so a validator can list what is missing, and it can never enable an export.

Distinct references (never treated as equivalent):
- site reference point: the local origin (0, 0), a named point of kind ``reference``;
- planned takeoff position: a named point of kind ``planned_takeoff`` inside a takeoff/landing zone;
- rover start: a named point of kind ``rover_start`` inside a rover start zone.
Observed initial positions, the autopilot's effective home (set at arming), the estimator origin and
Gazebo spawn poses are runtime observations or simulator settings: they do not belong in this file.

Supported geometry: simple polygons without holes, as open rings of [x_m, y_m] in the local frame.
Holes, circles and other shapes are rejected explicitly; describe a hole as a separate exclusion.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SITE_SCHEMA = "tfg.site/1"
Verification = Literal["SYNTHETIC", "PENDING_MEASUREMENT", "MEASURED_UNVERIFIED", "VERIFIED_DECLARED"]
UNSUPPORTED_GEOMETRY_KEYS = ("holes", "interiors", "radius_m", "circle", "center", "multipolygon", "type")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Provenance(_Strict):
    kind: Literal["SYNTHETIC", "TEMPLATE", "MEASURED"]
    source: str | None = None
    measured_by: str | None = None
    measured_on: str | None = None  # ISO date of the measurement campaign
    method: str | None = None
    notes: str | None = None


class Units(_Strict):
    length: Literal["m"] = "m"
    angle: Literal["deg"] = "deg"


class LocalFrame(_Strict):
    frame_id: str
    convention: Literal["ENU_ROTATED"] = "ENU_ROTATED"
    origin_point_id: str
    # Bearing of +y, clockwise from TRUE north; 0 means x=east, y=north. Null until measured.
    y_axis_bearing_deg: float | None = Field(None, ge=0, lt=360)
    orientation_verification: Verification = "PENDING_MEASUREMENT"
    orientation_source: str | None = None


class GeoReference(_Strict):
    """WGS84 position of the local origin."""
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    horizontal_datum: Literal["WGS84"] = "WGS84"
    source: str | None = None
    uncertainty_m: float | None = Field(None, ge=0)
    verification: Verification = "PENDING_MEASUREMENT"


class VerticalReference(_Strict):
    origin_ground_amsl_m: float | None = None
    vertical_datum: str | None = None  # e.g. "EGM96 geoid (MSL)", as reported by the source
    terrain: Literal["DECLARED_FLAT", "UNKNOWN"] = "UNKNOWN"
    source: str | None = None
    uncertainty_m: float | None = Field(None, ge=0)
    verification: Verification = "PENDING_MEASUREMENT"


class VerticalLimits(_Strict):
    max_altitude_m: float | None = Field(None, gt=0)
    reference: Literal["above_site_origin_ground"] = "above_site_origin_ground"
    source: str | None = None


class Zone(_Strict):
    zone_id: str
    polygon: list[tuple[float, float]] | None = None
    verification: Verification = "PENDING_MEASUREMENT"
    uncertainty_m: float | None = Field(None, ge=0)
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_unsupported_geometry(cls, data):
        if isinstance(data, dict):
            found = [k for k in UNSUPPORTED_GEOMETRY_KEYS if k in data]
            if found:
                raise ValueError(f"UNSUPPORTED_GEOMETRY ({', '.join(found)}): only simple polygons without "
                                 "holes are supported; describe holes or obstacles as separate exclusions")
        return data


class Exclusion(Zone):
    kind: Literal["obstacle", "no_fly", "no_drive", "keep_out"]
    # Exclusions are FULL HEIGHT in this version: vertical clearance over an obstacle is not modelled.
    applies_to: list[Literal["air", "ground"]] = Field(min_length=1)


class NamedPoint(_Strict):
    point_id: str
    kind: Literal["reference", "poi", "planned_takeoff", "rover_start"]
    x_m: float | None = None
    y_m: float | None = None
    zone_id: str | None = None  # required for planned_takeoff / rover_start: the zone that must contain it
    verification: Verification = "PENDING_MEASUREMENT"
    uncertainty_m: float | None = Field(None, ge=0)
    description: str | None = None

    @model_validator(mode="after")
    def _zone_required(self):
        if self.kind in ("planned_takeoff", "rover_start") and not self.zone_id:
            raise ValueError(f"{self.point_id}: a {self.kind} point must name its zone")
        return self


class Site(_Strict):
    schema_: Literal["tfg.site/1"] = Field(alias="schema")
    site_id: str
    version: int = Field(ge=1)
    name: str
    status: Literal["SYNTHETIC", "TEMPLATE_PENDING_MEASUREMENT", "MEASURED_UNVERIFIED", "VERIFIED_DECLARED"]
    provenance: Provenance
    units: Units = Units()
    local_frame: LocalFrame
    geo_reference: GeoReference | None = None
    vertical_reference: VerticalReference | None = None
    vertical_limits: VerticalLimits = VerticalLimits()
    operation_perimeter: Zone
    exclusions: list[Exclusion] = Field(default_factory=list)
    takeoff_landing_zones: list[Zone] = Field(default_factory=list)
    rover_start_zones: list[Zone] = Field(default_factory=list)
    rover_drivable_area: Zone | None = None
    points: list[NamedPoint] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    def zones(self) -> dict[str, Zone]:
        found = [self.operation_perimeter, *self.exclusions, *self.takeoff_landing_zones, *self.rover_start_zones]
        if self.rover_drivable_area is not None:
            found.append(self.rover_drivable_area)
        return {z.zone_id: z for z in found}

    def point(self, point_id: str) -> NamedPoint | None:
        return next((p for p in self.points if p.point_id == point_id), None)
