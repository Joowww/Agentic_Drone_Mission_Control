# Informe de exportación 9a4c1823960be7ed

- Procedencia: **SYNTHETIC**; destino: SITL_REHEARSAL.
- Estado del paquete: **COMPLETE_OFFLINE**; listo para desplegar: **no**.
- Aprobación del operador: STALE (instance_id, inputs, missions)

Emplazamiento `synthetic_orchard` v2 (SYNTHETIC), validación VALID, sha256 `7b27b00719dd…`.

| Tarea | Vehículo | Estado | Misión | .plan | Motivos |
| --- | --- | --- | --- | --- | --- |
| A1 | drone_01 | GENERATED | 5847127dc98a | plans/drone_01.plan | — |
| A2 | drone_02 | GENERATED | 0e0ec73d27af | plans/drone_02.plan | — |

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
