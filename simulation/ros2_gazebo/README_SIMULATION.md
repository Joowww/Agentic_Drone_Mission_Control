# ROS 2 / ArduPilot / Gazebo Simulation

## Purpose

This directory contains the multi-vehicle simulation infrastructure used in the TFG.

The simulation is developed as an independent layer from the agentic AI system.

The current stack is:

```text
ROS 2 Humble
     ↓
AP_DDS / DDS
     ↓
ArduPilot SITL
     ↓
Gazebo Harmonic
     ↓
Simulated vehicles
```

## Current stable configuration

The stable baseline contains:

- Drone 1: ArduCopter
- Drone 2: ArduCopter
- Rover 1: ArduRover

Vehicle mapping:

| Vehicle | SYSID | ROS 2 namespace |
|---|---:|---|
| Drone 1 | 1 | `/ap/v1` |
| Drone 2 | 2 | `/ap/v2` |
| Rover 1 | 3 | `/ap/v3` |

## Stable launch file

```text
launch/tfg_demo.launch.py
```

This file represents the first validated multi-vehicle baseline.

It contains:

```text
drone1
drone2
rover1
```

The ArduPlane from the upstream ArduPilot multiagent example was removed because it is not required for the current TFG scenario.

RViz is disabled during the current performance tests.

## Validated capabilities

The following functionality has been experimentally validated:

- simultaneous ArduPilot SITL instances;
- independent DDS namespaces;
- pre-arm validation;
- ArduCopter GUIDED mode;
- independent arming;
- independent drone takeoff;
- different target altitudes for both drones;
- drone state feedback;
- drone position feedback;
- LAND mode;
- automatic drone disarming after landing;
- ArduRover GUIDED mode;
- Rover arming;
- Rover `/cmd_vel` interface;
- Rover disarming.

## Validated flight

Drone 1:

```text
Target altitude: 5.0 m
Observed altitude: 4.99 m
```

Drone 2:

```text
Target altitude: 7.0 m
Observed altitude: 7.03 m
```

Both vehicles reported:

```text
armed: true
flying: true
mode: 4
```

during flight.

After LAND, both eventually reported:

```text
armed: false
flying: false
mode: 9
```

## Current limitation

The simulation is computationally expensive.

Observed baseline performance with:

```text
2 drones
1 rover
Gazebo GUI ON
RViz OFF
```

was approximately:

```text
Docker CPU: 448 %
RAM: 3.05 GiB
Real Time Factor: approximately 0.03–0.04
```

The architecture works correctly, but performance optimization is required before the final demo.

## Next experiment

The next configuration will contain:

```text
2 drones
0 rover
Gazebo GUI ON
RViz OFF
```

The objective is to quantify the performance cost of the Rover and determine the minimum configuration required for a fluid demonstration.

## Design principle

The simulation must remain usable without the agentic AI layer.

This allows:

1. independent validation of the vehicle platform;
2. easier debugging;
3. future reuse of the simulator for teaching;
4. later integration with the high-level agentic mission planner.
