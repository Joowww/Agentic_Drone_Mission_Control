from __future__ import annotations

from mcp.server import MCPServer

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
        output_directory=output_directory,
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