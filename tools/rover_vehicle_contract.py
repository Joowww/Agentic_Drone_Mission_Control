from __future__ import annotations
"""Transport-neutral high-level rover contract. Contains no motor/servo APIs."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Optional


class SteeringModel(str, Enum):
    ACKERMANN='ACKERMANN'
    DIFFERENTIAL='DIFFERENTIAL'
    SKID_STEER='SKID_STEER'
    UNKNOWN='UNKNOWN'


@dataclass(frozen=True)
class VehicleIdentity:
    vehicle_id: str
    platform: str
    firmware: Optional[str] = None
    hardware_revision: Optional[str] = None


@dataclass(frozen=True)
class VehicleCapabilities:
    steering_model: SteeringModel
    max_speed_mps: Optional[float]
    sensors: tuple[str,...] = ()
    position_sources: tuple[str,...] = ()


@dataclass(frozen=True)
class VehicleState:
    x_m: Optional[float] = None
    y_m: Optional[float] = None
    z_m: Optional[float] = None
    frame: Optional[str] = None
    speed_mps: Optional[float] = None
    heading_rad: Optional[float] = None
    armed: Optional[bool] = None
    mode: Optional[str] = None


@dataclass(frozen=True)
class VehicleHealth:
    healthy: Optional[bool]
    sensors: tuple[tuple[str,Optional[bool]],...] = ()
    failsafes: tuple[str,...] = ()
    detail: Optional[str] = None


@dataclass(frozen=True)
class NavigationPlan:
    plan_id: str
    frame: str
    target_x_m: float
    target_y_m: float
    max_speed_mps: float
    timeout_s: float


@dataclass(frozen=True)
class ExecutionAuthorization:
    scope_sha256: str
    human_authorized: bool


@dataclass(frozen=True)
class ExecutionFeedback:
    status: str
    state: Optional[VehicleState]
    error: Optional[str] = None
    physical_effect: bool = False
    stop_semantics: Optional[StopSemantics] = None
    failure_semantics: Optional[FailureSemantics] = None


class RoverVehicleExecutor(Protocol):
    def identity(self) -> VehicleIdentity: ...
    def capabilities(self) -> VehicleCapabilities: ...
    def observe(self) -> tuple[VehicleState,VehicleHealth]: ...
    def localization(self) -> VehicleLocalization: ...
    def telemetry(self) -> VehicleTelemetry: ...
    def execute(self, plan: NavigationPlan, authorization: ExecutionAuthorization) -> ExecutionFeedback: ...
    def stop(self) -> ExecutionFeedback: ...


@dataclass(frozen=True)
class VehicleLocalization:
    x_m: Optional[float]
    y_m: Optional[float]
    z_m: Optional[float]
    frame: Optional[str]
    observed_monotonic_s: Optional[float]
    source: Optional[str]
    source_sha256: Optional[str]
    validated: bool = False


@dataclass(frozen=True)
class VehicleTelemetry:
    lifecycle_id: Optional[str]
    host_boot_id: Optional[str]
    status_gid: Optional[str]
    motion_gid: Optional[str]
    status_age_s: Optional[float]
    motion_age_s: Optional[float]


@dataclass(frozen=True)
class MissionProposal:
    mission_id: str
    mission_sha256: str
    rover_id: str
    frame: str
    target_x_m: float
    target_y_m: float
    conditional: bool
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class StopSemantics:
    method: str
    acknowledgement_required: bool = True
    confirmed_by_observation: bool = True
    residual_risk: Optional[str] = None


@dataclass(frozen=True)
class FailureSemantics:
    status: str
    retry_allowed: bool = False
    state_known: bool = False
    reservation_retained_until_resolved: bool = True
