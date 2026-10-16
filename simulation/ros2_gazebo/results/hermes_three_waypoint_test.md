# Hermes Three-Waypoint Simulation Test

## Objective and scope

This test verifies that Hermes can initiate a mission with three navigation
waypoints through the `tfg-mission-control` MCP server and that the mission is
executed by ArduPilot SITL in Gazebo.

This is a simulation navigation test. It does not demonstrate agricultural
inspection, image capture, or crop analysis.

## Simulation environment

The test used:

- Hermes Agent
- MCP server: `tfg-mission-control`
- ROS 2 Humble
- AP_DDS
- ArduPilot SITL
- Gazebo Harmonic
- Executed vehicle: `v1` through `/ap/v1`
- Mission file: `missions/examples/simulation_navigation_3waypoint.json`

Before execution, the readiness check returned `READY_FOR_EXECUTION` with
`execution_authorized=true`. The simulation check reported the Docker
container, Gazebo runway world, both ArduCopter processes, both ROS 2 vehicle
interfaces, and both pre-arm checks as ready.

## Mission

The mission ID was `simulation_navigation_3waypoint_001`. It contained three
waypoints, all with action `navigate`, at a target altitude of 5 m.

The route used zero wind and enabled return to home. Its three waypoints form
a short route around the mission home position. The simulation mission mapper
preserved the route geometry around the vehicle's launch position in Gazebo.

## Execution method

Hermes was instructed to make exactly one MCP tool call to
`execute_approved_mission` using the mission file. The deterministic safety
gate was not bypassed. No manual ROS 2 flight commands were issued during the
Hermes-driven execution.

## Execution result

The MCP call took 209.5 seconds and returned:

- `success`: `true`
- `status`: `COMPLETED`
- `stage`: `MISSION_EXECUTION`
- `mission_id`: `simulation_navigation_3waypoint_001`
- `vehicle`: `v1`
- `waypoints_completed`: 3
- `return_to_home`: `true`

### Flight observations

| Stage | Observed result |
|---|---|
| Launch position | Lat `-35.36326217651367`, lon `149.1652069091797`, altitude `584.1900024414062` m AMSL |
| Takeoff | Target 5.0 m; observed altitude `588.9400024414062` m AMSL; altitude error `0.25` m |
| WP1 | Reached; horizontal error `0.8757544431862665` m; altitude error `0.030029296875` m |
| WP2 | Reached; horizontal error `0.5050285972530544` m; altitude error `0.0` m |
| WP3 | Reached; horizontal error `0.48068103430828996` m; altitude error `0.03997802734375` m |
| Return to launch | Reached; horizontal error `0.0` m; altitude error `0.0` m |
| Landing | Landed; `armed=false`; `flying=false` |
| Final position | Equal to the recorded launch position |

The executor reported this event sequence: `GUIDED_MODE`, `ARM`,
`TAKEOFF_COMMAND`, `TAKEOFF_REACHED`, `WAYPOINT_COMMAND` and
`WAYPOINT_REACHED` for WP1, WP2, and WP3, followed by
`RETURN_HOME_COMMAND`, `RETURN_HOME_REACHED`, `LAND_COMMAND`, and `LANDED`.

The maximum horizontal waypoint error was approximately 0.876 m, below the
executor's 1.0 m horizontal tolerance. The largest waypoint altitude error
was approximately 0.040 m, below its 0.75 m altitude tolerance. The takeoff
altitude error was 0.25 m, also within tolerance.

## What this test demonstrates

The recorded run demonstrates that Hermes can initiate a multi-waypoint
simulation mission through MCP, pass the deterministic execution gate, and
complete the route through ROS 2 / AP_DDS, ArduPilot SITL, and Gazebo.

Unlike a single-waypoint smoke test, this run confirms that the executor
issued commands for and verified three sequential waypoints before returning
to launch and landing.

## Scope and limitations

- The test used one simulated drone, `v1`, and one mission with three
  waypoints.
- The mission used zero wind; this run does not establish performance under
  changing or adverse wind.
- All waypoint actions were `navigate`. No camera, image capture, crop
  inspection, or agricultural analysis was performed.
- The mission includes `speed_kmh`, but the current executor does not command
  that speed explicitly to ArduPilot. This result does not verify speed
  tracking.
- `return_to_home` means navigating back to the recorded launch position and
  then landing. It does not mean switching to ArduPilot's RTL mode.
- This test validates simulation execution. It does not authorize or
  demonstrate flight with a physical drone.