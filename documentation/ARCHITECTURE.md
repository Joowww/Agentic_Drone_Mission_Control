# TFG Architecture

## High-level architecture

The project is divided into two major layers.

```text
┌─────────────────────────────────────┐
│          AGENTIC AI LAYER           │
│                                     │
│  Natural language                   │
│        ↓                            │
│  LangGraph orchestration            │
│        ↓                            │
│  Mission planning                   │
│        ↓                            │
│  Deterministic tools                │
│        ↓                            │
│  Safety Engine                      │
└─────────────────┬───────────────────┘
                  │
             Future ROS 2
              integration
                  │
┌─────────────────▼───────────────────┐
│         SIMULATION LAYER            │
│                                     │
│  ROS 2 Humble                       │
│        ↓                            │
│  AP_DDS / DDS                       │
│        ↓                            │
│  ArduPilot SITL                     │
│        ↓                            │
│  Gazebo Harmonic                    │
│                                     │
│  Drone 1 / Drone 2 / Rover          │
└─────────────────────────────────────┘
```

## Agentic AI layer

Responsibilities:

- interpret the mission requested by the user;
- maintain structured mission state;
- calculate mission parameters through deterministic tools;
- evaluate constraints;
- detect unsafe or infeasible missions;
- replan when required;
- produce a final mission decision.

## Simulation layer

Responsibilities:

- simulate vehicle dynamics;
- execute ArduPilot autopilot software through SITL;
- expose vehicle control and telemetry through DDS;
- provide ROS 2 interfaces;
- simulate multiple vehicles simultaneously;
- provide a controlled environment for integration tests.

## Current vehicle addressing

| Vehicle | SYSID | ROS 2 namespace |
|---|---:|---|
| Drone 1 | 1 | `/ap/v1` |
| Drone 2 | 2 | `/ap/v2` |
| Rover | 3 | `/ap/v3` |

## Development strategy

```text
Phase 1
Agentic AI validated independently

Phase 2
Simulation validated independently

Phase 3
Agentic AI
     ↓
ROS 2 mission interface
     ↓
Simulation

Phase 4
Autonomous multi-vehicle mission scenario
```

## Final scenario direction

The intended scenario is precision agriculture involving:

- multiple UAVs;
- area inspection;
- target detection;
- georeferenced mission information;
- coordination with an autonomous ground vehicle.
