# Informe de exportación 1b81d43e7232e4a4

- Procedencia: **SYNTHETIC**; destino: SITL_REHEARSAL.
- Estado del paquete: **PARTIAL**; listo para desplegar: **no**.
- Aprobación del operador: ABSENT

Emplazamiento `synthetic_orchard` v1 (SYNTHETIC), validación VALID, sha256 `0db007e872c8…`.

| Tarea | Vehículo | Estado | Misión | .plan | Motivos |
| --- | --- | --- | --- | --- | --- |
| A1 | drone_01 | GENERATED | b976179fa374 | plans/drone_01.plan | — |
| A2 | drone_02 | BLOCKED_VALIDATION_FAILED | ecc22a6072c1 | — | exclusion TREE_ROW_1 POI_3 -> POI_5: crosses or touches exclusion TREE_ROW_1; exclusion TREE_ROW_1 POI_5 -> TAKEOFF_B (RTL): crosses or touches exclusion TREE_ROW_1 |

## Tareas terrestres

- R1 (rover_01 → POI_4): línea REQUIRES_PLANNING; FORMAT_PENDING: no rover exporter; a .plan is not assumed; transformación NOT_ACCREDITED (site frame -> rover odometry frame).

## Coordinación

- Comprobación: PASS 
- Orden SEQUENTIAL: A1 → A2 → R1
- A2 tras A1: COMPLETED
- R1 tras A2: POI_REACHED POI_3
- R1 tras A2: COMPLETED
- Separación mínima planificada A1–A2: 8.0 m; simultaneidad NOT_CLEARED

## Ciclo de vida

- exported: DONE
- verified_offline: PENDING
- imported_in_qgroundcontrol: NOT_DONE
- uploaded_to_vehicle: NOT_DONE
- read_back_from_vehicle: NOT_DONE
- executed: NOT_DONE

## Limitaciones

- checks cover planned straight lines, not flown trajectories, unknown obstacles or collisions
- relative altitudes refer to the EFFECTIVE home set at arming, not to plannedHomePosition
- requested speeds are DO_CHANGE_SPEED requests, not validated speeds
- landing after RTL depends on RTL_ALT_FINAL(_M) = 0; RTL first climbs to RTL_ALT(_M); not verified
- no geofence exported; ArduPilot version of the SITL image not recorded
- individual .plan files do not coordinate vehicles; order and dependencies live in the coordinator
