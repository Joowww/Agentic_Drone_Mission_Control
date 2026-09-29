from langgraph.graph import END, START, StateGraph

from graph.nodes import (
    battery_check_node,
    evaluate_plan_node,
    final_report_node,
    flight_check_node,
    parse_mission_node,
    replanner_node,
    validate_input_node,
    wind_check_node,
)
from graph.routes import (
    route_after_evaluation,
    route_after_input_validation,
)
from graph.state import MissionState

builder = StateGraph(
    MissionState
)

builder.add_node(
    "parse_mission",
    parse_mission_node,
)

builder.add_node(
    "validate_input",
    validate_input_node,
)

builder.add_node(
    "flight_check",
    flight_check_node,
)

builder.add_node(
    "wind_check",
    wind_check_node,
)

builder.add_node(
    "battery_check",
    battery_check_node,
)

builder.add_node(
    "evaluate_plan",
    evaluate_plan_node,
)

builder.add_node(
    "replanner",
    replanner_node,
)

builder.add_node(
    "final_report",
    final_report_node,
)


builder.add_edge(
    START,
    "parse_mission",
)

builder.add_edge(
    "parse_mission",
    "validate_input",
)

builder.add_conditional_edges(
    "validate_input",
    route_after_input_validation,
    {
        "checks": "flight_check",
        "report": "final_report",
    },
)

builder.add_edge(
    "flight_check",
    "wind_check",
)

builder.add_edge(
    "wind_check",
    "battery_check",
)

builder.add_edge(
    "battery_check",
    "evaluate_plan",
)

builder.add_conditional_edges(
    "evaluate_plan",
    route_after_evaluation,
    {
        "replan": "replanner",
        "report": "final_report",
    },
)

builder.add_edge(
    "replanner",
    "final_report",
)

builder.add_edge(
    "final_report",
    END,
)


mission_graph = builder.compile()