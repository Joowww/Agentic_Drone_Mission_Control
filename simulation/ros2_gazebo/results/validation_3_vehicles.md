# Three-Vehicle Simulation Validation

Date: 2026-10-04

## Objective

Validate simultaneous simulation and independent ROS 2 control of:

- two ArduCopter vehicles;
- one ArduRover vehicle.

## Environment

- ROS 2 Humble
- Gazebo Harmonic
- ArduPilot SITL
- AP_DDS
- micro-ROS Agent
- Docker
- WSL2
- Gazebo GUI enabled
- RViz disabled

## Vehicle mapping

| Vehicle | Autopilot | SYSID | ROS 2 namespace |
|---|---|---:|---|
| Drone 1 | ArduCopter | 1 | `/ap/v1` |
| Drone 2 | ArduCopter | 2 | `/ap/v2` |
| Rover 1 | ArduRover | 3 | `/ap/v3` |

## DDS validation

The following namespaces were detected:

```text
/ap/v1
/ap/v2
/ap/v3
```

Each vehicle exposed independent ROS 2 status topics and ArduPilot services.

Result:

**PASS**

## Pre-arm

Drone 1:

```text
success=True
Vehicle is Armable
```

Drone 2:

```text
success=True
Vehicle is Armable
```

Rover:

```text
success=True
Vehicle is Armable
```

Result:

**PASS**

## Drone 1

Mode:

```text
GUIDED = 4
```

Operations:

- pre-arm: PASS
- GUIDED mode: PASS
- arm: PASS
- takeoff request: PASS
- flying state: PASS
- landing: PASS
- automatic disarm after landing: PASS

Target altitude:

```text
5.0 m
```

Observed filtered altitude:

```text
4.989999771118164 m
```

## Drone 2

Mode:

```text
GUIDED = 4
```

Operations:

- pre-arm: PASS
- GUIDED mode: PASS
- arm: PASS
- takeoff request: PASS
- flying state: PASS
- landing: PASS
- automatic disarm after landing: PASS

Target altitude:

```text
7.0 m
```

Observed filtered altitude:

```text
7.029999732971191 m
```

## Independent drone control

The two drones were controlled through separate namespaces:

```text
Drone 1 -> /ap/v1
Drone 2 -> /ap/v2
```

Different target altitudes were commanded independently.

Observed:

```text
Drone 1 -> approximately 5 m
Drone 2 -> approximately 7 m
```

This demonstrates independent multi-vehicle control.

Result:

**PASS**

## Rover

Mode:

```text
GUIDED = 15
```

Validated:

- pre-arm: PASS
- mode switch: PASS
- arm: PASS
- `/ap/v3/cmd_vel` subscription: PASS
- disarm: PASS

The ROS 2 movement interface was detected and commands were published.

A quantitative before/after Rover displacement measurement will be included in a future validation test.

## Landing validation

Final Drone 1 state:

```text
armed: false
mode: 9
flying: false
```

Final Drone 2 state:

```text
armed: false
mode: 9
flying: false
```

Final Rover state:

```text
armed: false
mode: 15
flying: false
```

Result:

**PASS**

## Validated end-to-end chain

```text
ROS 2 command
      ↓
AP_DDS
      ↓
ArduPilot SITL
      ↓
Gazebo simulation
      ↓
Vehicle dynamics
      ↓
ROS 2 state feedback
```

Result:

**PASS**

## Conclusion

Two simulated ArduCopter vehicles and one ArduRover vehicle can coexist and be independently addressed through ROS 2 and ArduPilot DDS interfaces.

The functional architecture is therefore validated.

The main unresolved issue is simulation performance.
