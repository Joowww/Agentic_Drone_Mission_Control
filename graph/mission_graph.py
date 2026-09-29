from langgraph.graph import END, START, StateGraph

from graph.nodes import (
    battery_check_node,
    evaluate_plan_node,
    flight_check_node,
    wind_check_node,
)
from graph.state import MissionState

builder = StateGraph(
    MissionState
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

builder.add_edge(
    START,
    "flight_check",
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

builder.add_edge(
    "evaluate_plan",
    END,
)


mission_graph = builder.compile()