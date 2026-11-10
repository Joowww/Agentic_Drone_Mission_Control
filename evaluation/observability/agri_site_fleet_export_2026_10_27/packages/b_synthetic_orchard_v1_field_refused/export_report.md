# Informe de exportación 4ffa1d92f0c7bc21

- Procedencia: **SYNTHETIC**; destino: FIELD.
- Estado del paquete: **PARTIAL**; listo para desplegar: **no**.
- Aprobación del operador: ABSENT

Emplazamiento `synthetic_orchard` v1 (SYNTHETIC), validación VALID, sha256 `0db007e872c8…`.

| Tarea | Vehículo | Estado | Misión | .plan | Motivos |
| --- | --- | --- | --- | --- | --- |
| A1 | drone_01 | BLOCKED_MISSING_DATA | 4f4eef794cb6 | — | SYNTHETIC site: never a proposal for hardware |
| A2 | drone_02 | BLOCKED_MISSING_DATA | c7a9d6b409b6 | — | SYNTHETIC site: never a proposal for hardware |

## Tareas terrestres

- R1 (rover_01 → POI_1): línea PASS; FORMAT_PENDING: no rover exporter; a .plan is not assumed; transformación NOT_ACCREDITED (site frame -> rover odometry frame).

## Coordinación

- Comprobación: PASS 
- Orden SEQUENTIAL: A1 → A2 → R1
- A2 tras A1: COMPLETED
- R1 tras A1: POI_REACHED POI_1
- R1 tras A2: COMPLETED
- Separación mínima planificada A1–A2: 8.0 m; simultaneidad NOT_CLEARED

## Ciclo de vida

- exported: NOT_DONE
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
