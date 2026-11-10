# Informe de exportación a03d3b06eb374ca7

- Procedencia: **SITL_HISTORICAL**; destino: SITL_REHEARSAL.
- Estado del paquete: **COMPLETE_OFFLINE**; listo para desplegar: **no**.
- Aprobación del operador: ABSENT

| Tarea | Vehículo | Estado | Misión | .plan | Motivos |
| --- | --- | --- | --- | --- | --- |
| H2_drone_01 | drone_01 | GENERATED | 56ef6d4da7e6 | plans/drone_01.plan | — |
| H2_drone_02 | drone_02 | GENERATED | ede25f88a8d4 | plans/drone_02.plan | — |

## Tareas terrestres

- R1 (rover_01 → POI_A1): línea NOT_CHECKABLE; FORMAT_PENDING: no rover exporter; a .plan is not assumed; transformación NOT_ACCREDITED.

## Coordinación

- Comprobación: PASS 
- Orden SEQUENTIAL: H2_drone_01 → H2_drone_02 → R1
- H2_drone_02 tras H2_drone_01: COMPLETED
- R1 tras H2_drone_01: POI_REACHED POI_A1
- Separación mínima planificada drone_01–drone_02: 5.54 m; simultaneidad NOT_CLEARED

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
