from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from graph.waypoint_nodes import (
    evaluate_waypoint_mission_node,
    waypoint_final_report_node,
    waypoint_replanner_node,
)
from graph.waypoint_routes import (
    route_after_waypoint_evaluation,
)
from graph.waypoint_state import (
    WaypointMissionState,
)

builder = StateGraph(
    WaypointMissionState
)

builder.add_node(
    "evaluate_waypoint_mission",
    evaluate_waypoint_mission_node,
)

builder.add_node(
    "waypoint_replanner",
    waypoint_replanner_node,
)

builder.add_node(
    "waypoint_final_report",
    waypoint_final_report_node,
)

builder.add_edge(
    START,
    "evaluate_waypoint_mission",
)

builder.add_conditional_edges(
    "evaluate_waypoint_mission",
    route_after_waypoint_evaluation,
    {
        "replan":
            "waypoint_replanner",
        "report":
            "waypoint_final_report",
    },
)

builder.add_edge(
    "waypoint_replanner",
    "waypoint_final_report",
)

builder.add_edge(
    "waypoint_final_report",
    END,
)

waypoint_mission_graph = (
    builder.compile()
)