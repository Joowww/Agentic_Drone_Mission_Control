"""State shared by the bounded virtual-preflight workflow."""
from typing import TypedDict

from models.mission_definition import MissionDefinition


class VirtualPreflightState(TypedDict, total=False):
    expected_sha256: str | None
    persist_progress: bool
    source_path: str
    source_artifact: dict | None
    run_id: str
    run_directory: str
    snapshot_path: str
    report_path: str
    mission_sha256: str | None
    mission: MissionDefinition
    mission_identity: dict | None
    vehicle_selection: dict | None
    expected_vehicle_selection: dict | None
    status: str
    stage: str
    reasons: list[str]
    validation: dict | None
    readiness: dict | None
    compatibility_errors: list[str]
    executor_result: object
    execution_attempted: bool
    analysis: dict | None
    started_at: str
    finished_at: str
    execution_started_at: str
    execution_finished_at: str
    transitions: list[dict]
    report: dict
