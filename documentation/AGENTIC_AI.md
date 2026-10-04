# Agentic AI Layer

## Purpose

The agentic AI layer converts high-level natural-language mission requests into structured, evaluated mission decisions.

It is developed and validated independently from the ROS 2 / ArduPilot simulation layer.

## Core design principle

The system follows the principle:

```text
LLM interprets and proposes
Deterministic Python computes
Safety Engine validates
```

The LLM is therefore not responsible for unrestricted safety-critical calculations.

## Current flow

```text
User mission
     ↓
Mission interpretation
     ↓
LangGraph orchestration
     ↓
Deterministic mission tools
     ↓
Safety checks
     ↓
Mission evaluation
     ↓
Replanning if required
     ↓
Final mission report
```

## Current implemented work

Work developed so far includes:

- LangChain agent experiments;
- LangGraph-based mission workflows;
- drone flight-time calculations;
- wind-safety evaluation;
- battery evaluation;
- structured mission state;
- autonomous mission planning;
- mission feasibility evaluation;
- mission replanning;
- conversational mission updates;
- QGroundControl mission adapter;
- regression tests.

The stable Git baseline before ROS 2 simulation development is:

```text
phase-7-complete
```

Commit:

```text
6e78668
```

## Separation from simulation

```text
AGENTIC AI                       SIMULATION

Natural language                ROS 2
      ↓                           ↓
LangGraph                       AP_DDS
      ↓                           ↓
Mission planner                 ArduPilot SITL
      ↓                           ↓
Safety Engine                   Gazebo
      │                           │
      └──── future integration ───┘
```

This separation allows both subsystems to be validated independently before integration.

## Future integration

```text
User
 ↓
Agentic AI
 ↓
MissionDefinition
 ↓
Mission planner
 ↓
Safety Engine
 ↓
ROS 2 mission interface
 ↓
ArduPilot
 ↓
Drones / ground vehicles
```
