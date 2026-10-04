# TFG Demo Guide

## Part 1 — Agentic AI

Show the LangGraph-based mission planner.

Explain:

1. natural-language mission input;
2. mission parameter extraction;
3. deterministic calculations;
4. safety checks;
5. replanning;
6. final mission feasibility report.

Key concept:

> The LLM interprets and orchestrates. Deterministic Python performs calculations and safety validation.

## Part 2 — Multi-Vehicle Simulation

Architecture:

```text
ROS 2
 ↓
AP_DDS
 ↓
ArduPilot SITL
 ↓
Gazebo
```

Current vehicles:

```text
Drone 1 -> /ap/v1
Drone 2 -> /ap/v2
Rover   -> /ap/v3
```

Validated:

- Drone 1 takeoff to approximately 5 m;
- Drone 2 takeoff to approximately 7 m;
- independent drone control;
- Rover ROS 2 control interface;
- independent drone landing;
- final vehicle disarming.

## Current limitation

Simulation Real Time Factor is approximately:

```text
0.03-0.04
```

Current work:

> Simulation performance optimization.

## Future integration

```text
Agentic AI
    ↓
Mission planner
    ↓
Safety Engine
    ↓
ROS 2
    ↓
ArduPilot
    ↓
Drone swarm / Rover
```
