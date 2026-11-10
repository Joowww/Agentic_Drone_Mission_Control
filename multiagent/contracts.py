"""Messages between the three agents. Strict models: an unknown field or a non-finite number is refused.

Coordinates are never trusted from text: the site (models.site) is the authority for WHERE things are. An
objective names a site point; a raw coordinate is only accepted when it coincides with a declared point of the
right kind, otherwise the objective is returned as needing a site point (it is never invented).

Every agent result carries ``movement_authorized: False`` and ``pending_authorization: True`` as constants: an
agent can propose, never authorize.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

BRIEF_SCHEMA = "tfg.multiagent.mission-brief/1"
CONTEXT_SCHEMA = "tfg.multiagent.operating-context/1"
RESULT_SCHEMA = "tfg.multiagent.agent-result/1"
PROPOSAL_SCHEMA = "tfg.multiagent.global-proposal/1"

Sensor = Literal["rgb", "multispectral", "thermal"]
AgentName = Literal["mission_orchestrator", "drone_swarm_agent", "rover_agent"]
# Outcome of an agent or of the whole proposal. None of them is a permission to move.
# COORDINATION_PENDING: several drones planned, but their separation could not be evaluated (missing data).
Status = Literal["PROPOSED_PENDING_AUTHORIZATION", "PARTIAL_PENDING_AUTHORIZATION", "NEEDS_CLARIFICATION",
                 "INFEASIBLE", "REFUSED_UNSAFE", "NO_TASKS", "COORDINATION_PENDING"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AerialObjective(_Strict):
    objective_id: str
    point_id: str | None = None
    coordinates: tuple[float, float] | None = None  # site local frame (x_m, y_m), only to match a declared point
    required_sensor: Sensor | None = None
    description: str | None = None


class GroundObjective(_Strict):
    objective_id: str
    point_id: str | None = None
    coordinates: tuple[float, float] | None = None
    after_aerial: bool = False  # the rover goes there only once a drone has reached that point (observed)
    description: str | None = None


class MissionBrief(_Strict):
    """What the orchestrator understood. Produced by an interpreter; nothing here is validated yet."""
    schema_: Literal["tfg.multiagent.mission-brief/1"] = Field(BRIEF_SCHEMA, alias="schema")
    site_id: str | None = None
    aerial_objectives: list[AerialObjective] = Field(default_factory=list)
    ground_objectives: list[GroundObjective] = Field(default_factory=list)
    drones: list[str] = Field(default_factory=list)  # requested drones; empty = any declared and available
    rover: str | None = None
    wind_speed_kmh: float | None = Field(None, ge=0)
    # declared in the request, per vehicle; bounded here so an out-of-range value is rejected as a bad brief
    battery_percent: dict[str, Annotated[float, Field(ge=0, le=100)]] = Field(default_factory=dict)
    altitude_m: float | None = Field(None, gt=0)
    unsafe_requests: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


class DroneProfile(_Strict):
    """Declared capabilities of one logical drone for allocation. SYNTHETIC unless measured: never a physical fact."""
    vehicle_id: str
    takeoff_point: str
    sensors: list[Sensor] = Field(default_factory=list)
    battery_percent: float = Field(ge=0, le=100)
    consumption_percent_per_minute: float = Field(gt=0)
    cruise_speed_kmh: float = Field(gt=0)
    max_wind_kmh: float = Field(gt=0)
    survey_speed_kmh: float | None = Field(None, gt=0)  # waypoint speed; None = the context's requested speed
    available: bool = True
    provenance: Literal["SYNTHETIC", "DECLARED_BY_OPERATOR"] = "SYNTHETIC"


class RoverProfile(_Strict):
    vehicle_id: str
    start_point: str
    available: bool = True  # DECLARED availability; the R1 coordinator and executor re-check their own
    provenance: Literal["SYNTHETIC", "DECLARED_BY_OPERATOR"] = "SYNTHETIC"


class SeparationPolicy(_Strict):
    """DECLARED inputs of the temporal deconfliction (multiagent.deconfliction). Every field is required: with any
    of them unknown the separation cannot be evaluated and a multi-drone plan stays COORDINATION_PENDING.
    Values are planning declarations, never measured performance."""
    min_separation_m: float = Field(gt=0)          # wanted clearance between vehicle envelopes
    position_uncertainty_m: float = Field(ge=0)    # per vehicle, horizontal
    vehicle_extent_m: float = Field(ge=0)          # max horizontal extent of one vehicle
    timing_uncertainty_s: float = Field(ge=0)      # absolute schedule uncertainty
    timing_uncertainty_fraction: float = Field(ge=0, le=1)  # grows with elapsed flight time
    takeoff_climb_s: float = Field(ge=0)           # spent above the pad before the first leg (not modelled in detail)
    landing_s: float = Field(ge=0)                 # spent above the pad after the last leg
    start_delay_step_s: float = Field(gt=0)
    max_start_delay_s: float = Field(ge=0)
    max_mission_duration_s: float = Field(gt=0)
    provenance: Literal["SYNTHETIC", "DECLARED_BY_OPERATOR"] = "SYNTHETIC"

    def required_distance_m(self) -> float:
        return self.min_separation_m + 2 * self.position_uncertainty_m + self.vehicle_extent_m


class OperatingContext(_Strict):
    """Where (site), with what (fleet + declared profiles) and with which planning defaults."""
    schema_: Literal["tfg.multiagent.operating-context/1"] = Field(CONTEXT_SCHEMA, alias="schema")
    context_id: str
    provenance: Literal["SYNTHETIC"] = "SYNTHETIC"
    site_path: str
    fleet_path: str
    drones: list[DroneProfile] = Field(min_length=1)
    rovers: list[RoverProfile] = Field(default_factory=list)
    altitude_m: float = Field(gt=0)
    requested_speed_kmh: float = Field(gt=0)
    minimum_battery_reserve_percent: float = Field(ge=0, le=100)
    planning_margin_m: float = Field(ge=0)
    wind_speed_kmh: float = Field(ge=0)  # declared default when the request does not state it
    coordinate_match_tolerance_m: float = Field(0.5, ge=0)
    separation_policy: SeparationPolicy | None = None  # None: multi-drone separation cannot be evaluated
    # FLEET_PROFILE_REQUIRED: only drones with a fleet export profile are planned (default).
    # SYNTHETIC_PLANNING_ONLY: synthetic placeholders without export profile may be planned; no .plan is produced.
    export_policy: Literal["FLEET_PROFILE_REQUIRED", "SYNTHETIC_PLANNING_ONLY"] = "FLEET_PROFILE_REQUIRED"

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    def resolve(self, path: str) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else Path(__file__).resolve().parents[1] / candidate


def load_context(path: Path | str) -> OperatingContext:
    return OperatingContext.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


class Incompatibility(_Strict):
    objective_id: str
    reasons: list[str] = Field(min_length=1)


class AgentResult(_Strict):
    """What a specialised agent returns to the orchestrator."""
    schema_: Literal["tfg.multiagent.agent-result/1"] = Field(RESULT_SCHEMA, alias="schema")
    agent: AgentName
    status: Status
    proposals: list[dict] = Field(default_factory=list)
    incompatible: list[Incompatibility] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    pending_authorization: Literal[True] = True
    movement_authorized: Literal[False] = False

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    def dump(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


# ----------------------------------------------------------------------------- brief /2 --
BRIEF_SCHEMA_V2 = "tfg.multiagent.mission-brief/2"
DeclaredAvailability = Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]


class AvailabilityStatement(_Strict):
    """What the OPERATOR'S TEXT says about one vehicle. Level 1 of three:
    1. declared in natural language (this statement, extracted by an interpreter);
    2. validated against the inventory (operating context + fleet: multiagent.availability);
    3. operational availability: NEVER established here; only the executor's own gates establish it.
    An interpreter can only report text; it cannot make a vehicle available, let alone operational."""
    vehicle_id: str
    declared: DeclaredAvailability
    quote: str | None = None  # the operator's words, verbatim when possible
    source: Literal["OPERATOR_TEXT"] = "OPERATOR_TEXT"


class MissionBriefV2(MissionBrief):
    """Brief /2 = brief /1 + availability statements + explicit ambiguities. Absent and unknown differ:
    a key not stated by the operator is null (or an empty list/map); a stated "unknown" is UNKNOWN."""
    schema_: Literal["tfg.multiagent.mission-brief/2"] = Field(BRIEF_SCHEMA_V2, alias="schema")
    vehicle_availability: list[AvailabilityStatement] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)  # what the interpreter could not resolve; asks for clarification


def parse_brief(value: dict) -> MissionBrief:
    """Validate a brief of either version by its declared schema (strict: unknown keys are refused)."""
    schema = (value or {}).get("schema")
    model = MissionBriefV2 if schema == BRIEF_SCHEMA_V2 else MissionBrief
    return model.model_validate(value)
