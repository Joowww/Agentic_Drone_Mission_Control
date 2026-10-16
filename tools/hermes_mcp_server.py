from __future__ import annotations

from tools.simulation_status import (
    check_simulation_ready as get_simulation_status,
)

from tools.simulation_control import (
    start_simulation as start_simulation_environment,
    stop_simulation as stop_simulation_environment,
)

from mcp.server import MCPServer

from tools.hermes_mission_validation import validate_mission_file


mcp = MCPServer(
    name="tfg-mission-control",
    title="TFG Mission Control",
    description=(
        "MCP interface for deterministic drone mission validation "
        "and QGroundControl plan export."
    ),
    instructions=(
        "Mission safety decisions must always come from the deterministic "
        "TFG validation pipeline. The LLM must not override FEASIBLE, "
        "NOT FEASIBLE, APPROVED, or BLOCKED results."
    ),
    version="0.1.0",
)


@mcp.tool(
    name="validate_mission",
    description=(
        "Validate a drone mission using the deterministic TFG mission "
        "safety pipeline. Does not export a QGroundControl plan."
    ),
    structured_output=True,
)
def validate_mission(
    mission_path: str,
) -> dict[str, object]:
    """Validate a mission JSON without exporting a QGC plan."""
    return validate_mission_file(
        mission_path,
        export_qgc=False,
    )


@mcp.tool(
    name="validate_and_export_qgc",
    description=(
        "Validate a drone mission deterministically and export its "
        "QGroundControl .plan file. FEASIBLE missions are APPROVED and "
        "produce <mission_id>.plan. NOT FEASIBLE missions are BLOCKED "
        "and produce <mission_id>_candidate.plan."
    ),
    structured_output=True,
)
def validate_and_export_qgc(
    mission_path: str,
    output_dir: str | None = None,
) -> dict[str, object]:
    """Validate a mission and export the corresponding QGC plan."""
    return validate_mission_file(
        mission_path,
        export_qgc=True,
        output_dir=output_dir,
    )

@mcp.tool(
    name="check_simulation_ready",
    description=(
        "Check whether the ROS2, Gazebo and ArduPilot simulation is ready. "
        "This is a read-only health check: it does not arm, take off, "
        "or command any vehicle."
    ),
    structured_output=True,
)
def check_simulation_ready() -> dict[str, object]:
    """Return the current readiness state of the drone simulation."""
    return get_simulation_status()

@mcp.tool(
    name="start_simulation",
    description=(
        "Start the ROS2, Gazebo and ArduPilot simulation environment. "
        "This starts simulation infrastructure only. "
        "It does not arm, take off, or command any vehicle."
    ),
    structured_output=True,
)
def start_simulation() -> dict[str, object]:
    """Start the drone simulation environment without commanding vehicles."""
    return start_simulation_environment()


@mcp.tool(
    name="stop_simulation",
    description=(
        "Stop the ROS2, Gazebo and ArduPilot simulation environment. "
        "This stops simulation processes only and does not issue "
        "flight commands to any vehicle."
    ),
    structured_output=True,
)
def stop_simulation() -> dict[str, object]:
    """Stop the drone simulation environment."""
    return stop_simulation_environment()

if __name__ == "__main__":
    mcp.run(transport="stdio")