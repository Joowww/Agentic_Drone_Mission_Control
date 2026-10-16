# Hermes End-to-End Simulation Smoke Test

## Objective and scope

This test verifies that Hermes can initiate a deterministic mission execution
through the `tfg-mission-control` MCP server and that the mission is carried
out in the ArduPilot SITL and Gazebo simulation.

This is a navigation smoke test. It does not demonstrate agricultural
inspection, image capture, or crop analysis. Although the mission objective
mentions collecting aerial imagery, its only waypoint action is `navigate`.

## Simulation environment

The test used:

- Hermes Agent
- MCP server: `tfg-mission-control`
- ROS 2 Humble
- AP_DDS
- ArduPilot SITL
- Gazebo Harmonic
- Vehicle interface: `/ap/v1`
- Mission file: `missions/examples/simulation_navigation_smoke.json`

## Mission

The mission has ID `simulation_navigation_smoke_001` and contains one
navigation waypoint.

The mission file specifies:

- Home: latitude `41.275`, longitude `1.987`
- Waypoint WP1: approximately 3 m north of home
- Target altitude: 5 m
- Waypoint action: `navigate`
- Wind speed: 0 km/h
- Return to home: enabled

The SITL vehicle starts at a different geographic location from the mission's
home coordinates. The simulation mission mapper preserves the route's relative
geometry and maps it around the vehicle's actual launch position in Gazebo.

## Execution path

Hermes -> `tfg-mission-control` MCP -> `execute_approved_mission` ->
deterministic execution gate -> `MissionDefinition` -> simulation mission
mapper -> ROS 2 / AP_DDS -> ArduPilot SITL -> Gazebo

The execution gate performs mission safety validation and checks simulation
readiness before authorizing execution.

Hermes was instructed to make exactly one MCP tool call to
`execute_approved_mission` using the smoke mission file. No manual ROS 2 flight
commands were issued during this Hermes-driven execution.

## Validation result

The mission validation command returned:

- `mission_status`: `FEASIBLE`
- `execution_status`: `APPROVED`
- `failure_reasons`: empty
- `errors`: empty

The mission passed deterministic validation and the execution gate before
flight commands were issued.

## Hermes execution result

The Hermes-driven execution took 211.3 seconds and returned:

- `success`: `true`
- `status`: `COMPLETED`
- `stage`: `MISSION_EXECUTION`
- `mission_id`: `simulation_navigation_smoke_001`
- `vehicle`: `v1`
- `waypoints_completed`: 1
- `return_to_home`: `true`

### Flight observations

| Stage | Observed result |
|---|---|
| Launch position | Lat `-35.36323547363281`, lon `149.1652069091797`, altitude `584.1900024414062` m AMSL |
| Takeoff | Target 5.0 m; observed altitude `589.1400146484375` m AMSL; reported altitude error `0.04998779296875` m |
| WP1 | Reached; horizontal error `0.8757544431862665` m; altitude error `0.030029296875` m |
| Return to launch | Reached; horizontal error `0.4241749826223707` m; altitude error `0.010009765625` m |
| Landing | Landed; `armed=false`; `flying=false` |
| Final position | Equal to the recorded launch position |

The executor reported this event sequence: `GUIDED_MODE`, `ARM`,
`TAKEOFF_COMMAND`, `TAKEOFF_REACHED`, `WAYPOINT_COMMAND`, `WAYPOINT_REACHED`,
`RETURN_HOME_COMMAND`, `RETURN_HOME_REACHED`, `LAND_COMMAND`, `LANDED`.

## What this test demonstrates

The recorded run demonstrates this end-to-end path:

Hermes -> MCP tool -> deterministic execution gate -> `MissionDefinition` ->
simulation mission mapper -> ROS 2 / AP_DDS -> ArduPilot SITL -> Gazebo ->
mission completion

Hermes initiated the mission through the MCP tool. Deterministic software
validated and executed it, while ArduPilot SITL controlled the simulated
vehicle in Gazebo.

The repository test suite was also run after the mission and report files were
present in the working tree: **51 passed in 6.47 seconds**.

## Scope and limitations

- The test used one simulated drone and one waypoint.
- The mission used zero wind; this run does not establish performance under
  changing or adverse wind.
- The waypoint action was `navigate`. No camera, image capture, crop
  inspection, or agricultural analysis was performed.
- The mission includes `speed_kmh`, but the current executor does not command
  that speed explicitly to ArduPilot. This result does not verify speed
  tracking.
- `return_to_home` means navigating back to the recorded launch position and
  then landing. It does not mean switching to ArduPilot's RTL mode.
- This test validates simulation execution. It does not authorize or
  demonstrate flight with a physical drone.