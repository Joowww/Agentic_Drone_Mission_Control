# Informe de exportación b9cff3e6b6950110

- Procedencia: **SYNTHETIC**; destino: SITL_REHEARSAL.
- Estado del paquete: **COMPLETE_OFFLINE**; listo para desplegar: **no**.
- Aprobación del operador: ABSENT (vincula hashes; no autentica).
- Comprobación de archivos: FILE_MATCHES_EXPECTATIONS; importer readback REDUCED.

Emplazamiento `synthetic_orchard` v1 (declarado SYNTHETIC), validación VALID, sha256 `0db007e872c8…`.

| Tarea | Vehículo | Estado | Misión | .plan | Motivos |
| --- | --- | --- | --- | --- | --- |
| A1 | drone_01 | GENERATED | 4f4eef794cb6 | plans/drone_01.plan | — |
| A2 | drone_02 | GENERATED | c7a9d6b409b6 | plans/drone_02.plan | — |

## Semántica A1 (QGC_PLAN_ARDUCOPTER_V2)

Alcance de las etiquetas: EXACT: the named element of the file equals the corresponding element of the mission (or of the H2 record where stated). It does not claim dynamic equivalence with H2, QGroundControl or vehicle compatibility, or any flight guarantee. CONDITIONED: the element is present but its effect depends on something outside the file (autopilot parameters, arming position). NOT_IN_PLAN: not expressed.

| Elemento | Estado | Detalle |
| --- | --- | --- |
| takeoff | CONDITIONED | NAV_TAKEOFF to the first waypoint altitude, relative to the EFFECTIVE home (set at arming); equals the executor's launch-relative target only if armed at the planned takeoff position |
| waypoint coordinate values | EXACT | item lat/lon/alt equal the mission waypoint values (8 decimals; degE7 transport quantization reported); says nothing about the flown path |
| waypoint acceptance | CONDITIONED | ArduCopter accepts within WP_RADIUS_M and does not stop at a waypoint followed by another navigation item (hold 0); the H2 executor sent targets one by one and accepted at 1.0 m horizontal / 0.75 m vertical |
| hold parameter | EXACT | param1 = 0, matching the mission model, which has no hold field; the vehicle's dwell is not implied (see waypoint acceptance) |
| yaw | CONDITIONED | not specified by the mission (param4 NaN): WP_YAW_BEHAVIOR decides; the executor commanded no yaw either |
| speed | CONDITIONED | requested [10.0] km/h as DO_CHANGE_SPEED (maximum horizontal speed, bounded by the autopilot); the GUIDED executor did not apply speed_kmh |
| return coordinate | CONDITIONED | NAV_LAND coordinate = the planned home coordinate; the executor returned to the OBSERVED launch position, equal only if the vehicle launches at the planned coordinate. The motion differs: H2 sent a GUIDED target and waited within 1.0 m before LAND; ArduCopter flies the NAV_LAND leg at the current altitude, then descends (not RTL, not the effective home) |
| landing command | EXACT | an explicit NAV_LAND item is present, as H2 always commanded LAND; it does not depend on RTL_ALT_FINAL_M. Descent and touchdown behaviour depend on LAND_* parameters |
| failsafe actions | NOT_IN_PLAN | low battery / wind / link loss actions are autopilot parameters (FS_*), not mission items; the mission's failsafe block is not expressed |
| planning inputs | NOT_IN_PLAN | battery, wind and constraints are validation inputs only |

Lectura con nuestro importador: REDUCED; pérdidas: MAV_CMD_NAV_TAKEOFF was not converted into a horizontal waypoint. Vertical takeoff dynamics are not modelled yet.; MAV_CMD_NAV_LAND was converted to a navigation endpoint. Landing dynamics are not modelled yet.; NAV_LAND represented as an extra navigation waypoint; landing and return meaning lost.

## Semántica A2 (QGC_PLAN_ARDUCOPTER_V2)

Alcance de las etiquetas: EXACT: the named element of the file equals the corresponding element of the mission (or of the H2 record where stated). It does not claim dynamic equivalence with H2, QGroundControl or vehicle compatibility, or any flight guarantee. CONDITIONED: the element is present but its effect depends on something outside the file (autopilot parameters, arming position). NOT_IN_PLAN: not expressed.

| Elemento | Estado | Detalle |
| --- | --- | --- |
| takeoff | CONDITIONED | NAV_TAKEOFF to the first waypoint altitude, relative to the EFFECTIVE home (set at arming); equals the executor's launch-relative target only if armed at the planned takeoff position |
| waypoint coordinate values | EXACT | item lat/lon/alt equal the mission waypoint values (8 decimals; degE7 transport quantization reported); says nothing about the flown path |
| waypoint acceptance | CONDITIONED | ArduCopter accepts within WP_RADIUS_M and does not stop at a waypoint followed by another navigation item (hold 0); the H2 executor sent targets one by one and accepted at 1.0 m horizontal / 0.75 m vertical |
| hold parameter | EXACT | param1 = 0, matching the mission model, which has no hold field; the vehicle's dwell is not implied (see waypoint acceptance) |
| yaw | CONDITIONED | not specified by the mission (param4 NaN): WP_YAW_BEHAVIOR decides; the executor commanded no yaw either |
| speed | CONDITIONED | requested [10.0] km/h as DO_CHANGE_SPEED (maximum horizontal speed, bounded by the autopilot); the GUIDED executor did not apply speed_kmh |
| return coordinate | CONDITIONED | NAV_LAND coordinate = the planned home coordinate; the executor returned to the OBSERVED launch position, equal only if the vehicle launches at the planned coordinate. The motion differs: H2 sent a GUIDED target and waited within 1.0 m before LAND; ArduCopter flies the NAV_LAND leg at the current altitude, then descends (not RTL, not the effective home) |
| landing command | EXACT | an explicit NAV_LAND item is present, as H2 always commanded LAND; it does not depend on RTL_ALT_FINAL_M. Descent and touchdown behaviour depend on LAND_* parameters |
| failsafe actions | NOT_IN_PLAN | low battery / wind / link loss actions are autopilot parameters (FS_*), not mission items; the mission's failsafe block is not expressed |
| planning inputs | NOT_IN_PLAN | battery, wind and constraints are validation inputs only |

Lectura con nuestro importador: REDUCED; pérdidas: MAV_CMD_NAV_TAKEOFF was not converted into a horizontal waypoint. Vertical takeoff dynamics are not modelled yet.; MAV_CMD_NAV_LAND was converted to a navigation endpoint. Landing dynamics are not modelled yet.; NAV_LAND represented as an extra navigation waypoint; landing and return meaning lost.

## Tareas terrestres

- R1 (rover_01 → POI_1): línea PASS; FORMAT_PENDING: no rover exporter; a .plan is not assumed; transformación NOT_ACCREDITED (site frame -> rover odometry frame).

## Coordinación

- Comprobación: PASS 
- Orden SEQUENTIAL: A1 → A2 → R1
- A2 tras A1: COMPLETED
- R1 tras A1: POI_REACHED POI_1
- R1 tras A2: COMPLETED
- Separación mínima planificada A1–A2: 8.0 m; simultaneidad NOT_CLEARED

## Pendiente o condicionado

- operator approval ABSENT
- A1: margin NOT_ACCREDITED (DECLARED_PLANNING_MARGIN 1.0 m)
- A2: margin NOT_ACCREDITED (DECLARED_PLANNING_MARGIN 1.0 m)
- conditioned or not in the .plan: failsafe actions, planning inputs, return coordinate, speed, takeoff, waypoint acceptance, yaw
- autopilot parameters not read: WP_RADIUS_M (waypoint acceptance), WP_YAW_BEHAVIOR (yaw), WP_SPD (default speed), FS_* (failsafe actions), LAND_SPD_MS / descent (landing rate)
- QGroundControl version unknown; imported_in_qgroundcontrol: NOT_DONE, uploaded_to_vehicle: NOT_DONE, read_back_from_vehicle: NOT_DONE, executed: NOT_DONE

## Versiones

- ardupilot_executed: ArduCopter/ArduRover V4.8.0-dev (755258db) as reported by SITL in logs of 20-26/10/2026 (e.g. results/gui_control_two_drones_2026_10_25, rover_identity_trial_2026_10_26; image sha256:5d5de3c6...); the H2 record of 24/10 keeps no firmware version or image id
- ardupilot_source_consulted: local clean tree at 755258dbb452 (~/TFG/ardupilot_ros2_ws/src/ardupilot)
- qgroundcontrol: UNKNOWN: no installation found; plan format from the QGC master documentation (27/10/2026)
- physical_vehicles: UNKNOWN

## Ciclo de vida

- exported: DONE
- file_checks: FILE_MATCHES_EXPECTATIONS; importer readback REDUCED
- imported_in_qgroundcontrol: NOT_DONE
- uploaded_to_vehicle: NOT_DONE
- read_back_from_vehicle: NOT_DONE
- executed: NOT_DONE

## Limitaciones

- checks cover planned straight lines, not flown trajectories, unknown obstacles or collisions
- relative altitudes refer to the EFFECTIVE home set at arming, not to plannedHomePosition
- requested speeds are DO_CHANGE_SPEED requests, not validated speeds
- the .plan returns to a planned COORDINATE and lands (NAV_LAND); it does not use RTL
- no geofence exported
- individual .plan files do not coordinate vehicles; order and dependencies live in the coordinator
- our importer reads the file back with losses (TAKEOFF dropped, LAND reduced to a waypoint)
