from __future__ import annotations

from mcp.server import MCPServer

from models.mission_plan_draft import MissionPlanDraft
from tools.virtual_preflight import run_virtual_preflight as preflight_backend
from tools.virtual_preflight_jobs import (
    start_virtual_preflight as start_preflight_backend,
    get_virtual_preflight as get_preflight_backend,
)
from tools.hermes_mission_planning import (
    update_mission_draft as update_draft_backend,
    finalize_mission_draft as finalize_draft_backend,
)

from tools.hermes_mission_validation import (
    validate_mission_file,
)
from tools.mission_execution_gate import (
    check_mission_execution_ready as check_execution_ready,
)
from tools.simulation_control import (
    start_simulation as start_simulation_backend,
    stop_simulation as stop_simulation_backend,
)
from tools.simulation_mission_executor import (
    execute_approved_mission as execute_mission_backend,
)
from tools.simulation_status import (
    check_simulation_ready as check_simulation_backend,
)


mcp = MCPServer(
    name="tfg-mission-control",
    title="TFG Mission Control",
    description=(
        "Deterministic mission validation and simulation-control "
        "tools for the Agentic Drone Mission Control TFG."
    ),
    instructions=(
        "Interpret operator language into explicit draft fields without inventing facts. "
        "Use update_mission_draft, retain draft_id across turns, ask for missing fields, "
        "then finalize_mission_draft to build, validate and export. Choose tools "
        "according to requests and results without a fixed tool count. Obtain explicit "
        "user authorization before starting simulation or executing the reviewed "
        "mission_path. APPROVED is not user consent or formal virtual preflight. "
        "For an explicitly requested rehearsal prefer start_virtual_preflight with a "
        "request_key chosen and recorded BEFORE starting. Preserve run_id and request_key. "
        "Poll get_virtual_preflight on the SAME run about every 15-30 seconds; never "
        "restart a run on timeout, lost response or reconnection. Recover a lost ID by "
        "querying request_key. ACCEPTED/STARTING is admission, not validation or PASSED. "
        "INTERRUPTED/UNCONFIRMED requires operator reconciliation; do not infer landing, "
        "release a restriction or repeat flight. Synchronous tools can exceed MCP timeouts. "
        "Use run_virtual_preflight only when the user requests a synchronous rehearsal: "
        "it arms, takes off and moves simulated v1, never starts simulation. "
        "PASSED is not consent for another execution or permission for real hardware. "
        "Only navigate execution is supported; speed tracking is not verified. "
        "Use these tools to validate drone missions and interact "
        "with the ROS2, Gazebo and ArduPilot simulation stack. "
        "Mission safety decisions are deterministic and must never "
        "be invented or overridden by the language model. "
        "A mission must pass the execution gate before flight "
        "commands can be issued."
    ),
    version="0.2.0",
)


@mcp.tool(
    description=(
        "Admit ONE asynchronous virtual preflight and quickly return run_id and paths. "
        "Requires an explicit user rehearsal request: the detached worker may ARM, TAKE OFF "
        "and MOVE exclusively simulated v1, then land. Choose and record request_key before "
        "calling; it permanently identifies this admission. Validation/acceptance are pending. "
        "Never starts simulation. A lost response is recovered with get_virtual_preflight, "
        "not another start. PASSED grants neither hardware permission nor another flight."
    ), structured_output=True,
)
def start_virtual_preflight(mission_path: str, request_key: str) -> dict[str, object]:
    return start_preflight_backend(mission_path, request_key)


@mcp.tool(
    description=(
        "Read-only preflight lookup by exactly one of run_id or request_key, including "
        "historical reports. Returns job state, current/last phase, final result if available, "
        "report and paths. Never spawns, resumes, clears v1 ownership or commands flight. "
        "Poll the same run every 15-30 seconds. INTERRUPTED/UNCONFIRMED never implies landing."
    ), structured_output=True,
)
def get_virtual_preflight(run_id: str | None = None, request_key: str | None = None) -> dict[str, object]:
    return get_preflight_backend(run_id=run_id, request_key=request_key)


@mcp.tool(
    description=(
        "SYNCHRONOUS legacy operation: holds the request throughout the rehearsal and may "
        "exceed the MCP client timeout without cancelling the backend. Prefer "
        "start_virtual_preflight plus get_virtual_preflight for tracking. "
        "Run one explicitly requested virtual preflight in Gazebo/ArduPilot SITL. "
        "WARNING: this tool ARMS, TAKES OFF and MOVES exclusively simulated vehicle v1, "
        "then lands and waits for disarm via the existing executor. It snapshots and "
        "hashes the mission, validates safety, checks readiness and compatibility, "
        "and persists an evidence report. Never starts/restarts simulation or retries "
        "a flight. Use only when the user requests the rehearsal. PASSED does not "
        "authorize hardware or grant consent for any subsequent execution."
    ),
    structured_output=True,
)
def run_virtual_preflight(mission_path: str) -> dict[str, object]:
    return preflight_backend(mission_path)


@mcp.tool(
    description="Create or continue a persistent draft from explicit operator facts. Retain draft_id to continue; empty updates retrieve it. Returns missing fields. Null preserves values and waypoint IDs merge. No flight commands.",
    structured_output=True,
)
def update_mission_draft(
    updates: MissionPlanDraft, draft_id: str | None = None,
) -> dict[str, object]:
    return update_draft_backend(updates, draft_id)


@mcp.tool(
    description="Build MissionDefinition JSON from a complete draft, deterministically validate and export QGC .plan. Returns mission_path for readiness/execution tools or missing fields. Does not start simulation or grant user flight authorization.",
    structured_output=True,
)
def finalize_mission_draft(draft_id: str) -> dict[str, object]:
    return finalize_draft_backend(draft_id)


@mcp.tool(
    name="validate_mission",
    description=(
        "Validate a drone mission using the deterministic TFG "
        "mission-safety pipeline. No LLM is used for the safety "
        "decision."
    ),
    structured_output=True,
)
def validate_mission(
    mission_path: str,
) -> dict[str, object]:
    return validate_mission_file(
        mission_path
    )


@mcp.tool(
    name="validate_and_export_qgc",
    description=(
        "Validate a drone mission deterministically and export a "
        "QGroundControl .plan file. Unsafe missions remain blocked "
        "and are exported only as candidate plans."
    ),
    structured_output=True,
)
def validate_and_export_qgc(
    mission_path: str,
    output_directory: str | None = None,
) -> dict[str, object]:
    return validate_mission_file(
        mission_path,
        export_qgc=True,
        output_dir=output_directory,
    )


@mcp.tool(
    name="check_simulation_ready",
    description=(
        "Check whether the ROS2, Gazebo and ArduPilot simulation "
        "stack is healthy and ready. This is a read-only check and "
        "does not issue flight commands."
    ),
    structured_output=True,
)
def check_simulation_ready() -> dict[str, object]:
    return check_simulation_backend()


@mcp.tool(
    name="start_simulation",
    description=(
        "Start the deterministic ROS2, Gazebo and ArduPilot "
        "simulation stack. This starts the simulation environment "
        "only and does not arm, take off or command a vehicle."
    ),
    structured_output=True,
)
def start_simulation() -> dict[str, object]:
    return start_simulation_backend()


@mcp.tool(
    name="stop_simulation",
    description=(
        "Stop the ROS2, Gazebo and ArduPilot simulation processes. "
        "This tool is intended for simulation lifecycle management "
        "and does not represent a normal in-flight landing command."
    ),
    structured_output=True,
)
def stop_simulation() -> dict[str, object]:
    return stop_simulation_backend()


@mcp.tool(
    name="check_mission_execution_ready",
    description=(
        "Check whether a mission is authorized for execution. "
        "The deterministic mission-safety pipeline must approve "
        "the mission and the simulation must be healthy before "
        "execution is authorized."
    ),
    structured_output=True,
)
def check_mission_execution_ready(
    mission_path: str,
) -> dict[str, object]:
    return check_execution_ready(
        mission_path
    )


@mcp.tool(
    name="execute_approved_mission",
    description=(
        "SYNCHRONOUS: may exceed the MCP client timeout; timeout does not cancel flight. "
        "Shares v1 exclusion with asynchronous preflight. "
        "Execute an approved waypoint mission on Drone 1 in the "
        "Gazebo/ArduPilot simulation. The executor re-runs the "
        "deterministic execution gate internally before issuing "
        "any flight command. Unsupported or unsafe missions are "
        "blocked. The current executor supports ArduPilot "
        "multirotor missions with navigate actions."
    ),
    structured_output=True,
)
def execute_approved_mission(
    mission_path: str,
) -> dict[str, object]:
    return execute_mission_backend(
        mission_path,
        vehicle="v1",
        progress=False,
    )


if __name__ == "__main__":
    mcp.run(
        transport="stdio"
    )