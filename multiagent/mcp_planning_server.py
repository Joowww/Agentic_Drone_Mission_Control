"""Planning-only MCP facade over the agents' tools, for a FUTURE Hermes integration (not wired into any Hermes
home; tools/hermes_mcp_server.py is not modified). Same functions as multiagent.agent_tools, same ToolRunner
checks; stateless calls naming an allow-listed synthetic operating context.

    python -m multiagent.mcp_planning_server      # stdio, only when started explicitly

Exposed: drone_capabilities, validate_route, check_separation, reference_allocation, plan_preview,
rover_capabilities, validate_ground_target, check_dependency. None writes a file, reserves a vehicle or commands anything; operational names are refused by
the ToolRunner. Integration path: add this server to a Hermes planning home next to tfg-mission-control, with
tools.include limited to these names (the existing restrict_mcp_text mechanism), and keep the operational
server's tools excluded as today.
"""
from __future__ import annotations

from pathlib import Path

from mcp.server import MCPServer

from multiagent.agent_tools import ToolRunner, drone_tools, rover_tools
from multiagent.contracts import load_context

FIXTURES = Path(__file__).with_name("fixtures")
CONTEXTS = {"orchard_two_drones_v2", "swarm_1", "swarm_2", "swarm_3", "swarm_3_tight", "swarm_5"}
TOOLS = ("drone_capabilities", "validate_route", "check_separation", "reference_allocation", "plan_preview",
         "rover_capabilities", "validate_ground_target", "check_dependency")

server = MCPServer(name="tfg-multiagent-planning", title="TFG multi-agent planning tools",
                   description="Read-only planning and validation tools of the multi-agent prototype",
                   instructions="Planning and validation only. Nothing here authorizes, uploads, arms or moves a vehicle.")


def _problem(context: str, objectives: list[dict], wind_speed_kmh: float = 0.0):
    from multiagent import scenarios
    from multiagent.swarm import Objective, SwarmProblem
    if context not in CONTEXTS:
        raise ValueError(f"unknown context {context!r}; allowed: {sorted(CONTEXTS)}")
    ctx = load_context(FIXTURES / f"{context}.context.json")
    site, fleet = scenarios._world(ctx)
    objs = [Objective(o["objective_id"], o["point_id"], o.get("required_sensor")) for o in objectives]
    return SwarmProblem(site, fleet, ctx, objs, list(ctx.drones), wind_speed_kmh), ctx, site, fleet


def _drone(name, context, objectives, arguments, wind_speed_kmh=0.0):
    problem, *_ = _problem(context, objectives, wind_speed_kmh)
    entry = ToolRunner("drone_swarm_agent", drone_tools(problem)).call(name, arguments)
    return {"status": entry["status"], "output": entry["output"], "notice": entry["notice"]}


@server.tool(description="Declared drone profiles, objectives with their eligible drones, wind, site points (read-only).")
def drone_capabilities(context: str, objectives: list[dict], wind_speed_kmh: float = 0.0) -> dict:
    return _drone("drone_capabilities", context, objectives, {}, wind_speed_kmh)


@server.tool(description="Site rules + battery/wind validation of one visiting order for one drone (read-only).")
def validate_route(context: str, objectives: list[dict], vehicle_id: str, sequence: list[str],
                   wind_speed_kmh: float = 0.0) -> dict:
    return _drone("validate_route", context, objectives, {"vehicle_id": vehicle_id, "sequence": sequence}, wind_speed_kmh)


@server.tool(description="Spatio-temporal separation of an assignment {drone: [objective ids]} (read-only).")
def check_separation(context: str, objectives: list[dict], assignments: dict[str, list[str]],
                     wind_speed_kmh: float = 0.0) -> dict:
    return _drone("check_separation", context, objectives, {"assignments": assignments}, wind_speed_kmh)


@server.tool(description="Deterministic reference allocation of the objectives (read-only).")
def reference_allocation(context: str, objectives: list[dict], wind_speed_kmh: float = 0.0) -> dict:
    return _drone("reference_allocation", context, objectives, {}, wind_speed_kmh)


@server.tool(description="Build a QGC .plan in memory and return its sha256; nothing is saved or uploaded.")
def plan_preview(context: str, objectives: list[dict], vehicle_id: str, sequence: list[str]) -> dict:
    return _drone("plan_preview", context, objectives, {"vehicle_id": vehicle_id, "sequence": sequence})


@server.tool(description="Declared rover profile, availability, declared start point (no live localization), POIs.")
def rover_capabilities(context: str, rover_id: str | None = None, aerial_points: list[str] | None = None) -> dict:
    _, ctx, site, fleet = _problem(context, [])
    entry = ToolRunner("rover_agent", rover_tools(site=site, context=ctx, fleet=fleet, rover_id=rover_id,
                                                  aerial_points=aerial_points or [])).call("rover_capabilities", {})
    return {"status": entry["status"], "output": entry["output"], "notice": entry["notice"]}


@server.tool(description="Ground route from the rover's declared start to a declared POI (read-only).")
def validate_ground_target(context: str, target_point: str, rover_id: str | None = None) -> dict:
    _, ctx, site, fleet = _problem(context, [])
    entry = ToolRunner("rover_agent", rover_tools(site=site, context=ctx, fleet=fleet, rover_id=rover_id,
                                                  aerial_points=[])).call("validate_ground_target",
                                                                          {"target_point": target_point})
    return {"status": entry["status"], "output": entry["output"], "notice": entry["notice"]}


@server.tool(description="Whether a proposed drone task reaches the point a rover must wait for (read-only).")
def check_dependency(point: str, aerial_points: list[str]) -> dict:
    entry = ToolRunner("rover_agent", rover_tools(site=None, context=None, fleet=None, rover_id=None,
                                                  aerial_points=aerial_points)).call(
        "check_dependency", {"point": point, "aerial_points": aerial_points})
    return {"status": entry["status"], "output": entry["output"], "notice": entry["notice"]}


if __name__ == "__main__":
    server.run(transport="stdio")
