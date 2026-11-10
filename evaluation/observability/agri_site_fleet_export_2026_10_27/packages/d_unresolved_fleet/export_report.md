# Informe de exportación b39bcceac2e07385

- Procedencia: **SYNTHETIC**; destino: SITL_REHEARSAL.
- Estado del paquete: **PARTIAL**; listo para desplegar: **no**.
- Aprobación del operador: ABSENT

Emplazamiento `synthetic_orchard` v1 (SYNTHETIC), validación VALID, sha256 `0db007e872c8…`.

| Tarea | Vehículo | Estado | Misión | .plan | Motivos |
| --- | --- | --- | --- | --- | --- |
| A1 | drone_01 | GENERATED | 00629d388b5f | plans/drone_01.plan | — |
| A2 | mini_drone_01 | COMPATIBILITY_PENDING | — | — | mini_drone_01: future mini drone (unknown) |
| A3 | drone_99 | BLOCKED_MISSING_DATA | — | — | vehicle drone_99 is not in the fleet |

## Tareas terrestres

- R1 (rover_01 → POI_1): línea PASS; FORMAT_PENDING: no rover exporter; a .plan is not assumed; transformación NOT_ACCREDITED (site frame -> rover odometry frame).

## Coordinación

- Comprobación: FAIL ['A3: vehicle drone_99 is not in fleet agri_demo_fleet']
- Orden SEQUENTIAL: A1 → A2 → A3 → R1
- A2 tras A1: COMPLETED
- R1 tras A1: POI_REACHED POI_1
- R1 tras A2: COMPLETED
- A3 tras A2: COMPLETED
- Separación mínima planificada A1–A2: 8.0 m; simultaneidad NOT_CLEARED
- Separación mínima planificada A1–A3: 8.0 m; simultaneidad NOT_CLEARED
- Separación mínima planificada A2–A3: 0.0 m; simultaneidad NOT_CLEARED

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
