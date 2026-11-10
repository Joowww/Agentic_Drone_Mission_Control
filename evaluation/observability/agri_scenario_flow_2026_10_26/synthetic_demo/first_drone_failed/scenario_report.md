> **Origen: SINTÉTICO (demostración offline).** La parte aérea es una copia REIDENTIFICADA del registro H2 conservado: sus horas, hashes y errores son los del ensayo real del 24/10, no de una ejecución nueva. R1 usa un ejecutor TEST_DOUBLE. No es una ejecución real y no completa ningún escenario.

# Informe determinista del escenario agri_demo_001

Generado por código a partir de la vista `tfg.agri-scenario-view/1`; no lo redacta un modelo. Cada hecho cita su campo de la vista entre corchetes.

- Estado de la vista: **OK** [status].
- Escenario: **FAILED**; completo: **no** [scenario.status, scenario.scenario_complete].
- Registro histórico de la secuencia `0df8dec9-6b2f-5a18-be4a-4a5221389a82`: FINISHED / FAILED, creada 2026-10-24T12:51:18.386453+00:00, terminada 2026-10-24T12:59:51.127955+00:00 [scenario.sequence].

## Resultado de cada ejecución

### Hijo 1: drone_01 → v1

- Misión `agri_demo_001_h1_sector_a` (snapshot `321ad647ab9c2af536905d541675580df20e0e7a5e9be129841c8f894166b30d`), informe `183a68b92db7c03543066f0ddbb6de5524870866a854ca237b69ed92d4088864` [scenario.runs[0].mission_id, mission_sha256, report_sha256].
- Estado: **FAILED**; resultado: FAILED [scenario.runs[0].status, result_status].
- Puntos de interés: POI_A1 NOT_CONFIRMED, POI_A2 NOT_CONFIRMED [scenario.runs[0].points].
- Regreso: NOT_CONFIRMED; aterrizaje: RECOVERY_LANDING_CONFIRMED [scenario.runs[0].return_home, landing].
- Cronología registrada (reloj de pared UTC) [scenario.runs[0].timeline]:
  - admisión del trabajo: 2026-10-24T12:51:18.368178+00:00 (no es evidencia de orden ni un despegue);
  - despacho del coordinador: 2026-10-24T12:51:20.085388+00:00;
  - inicio del ejecutor: 2026-10-24T12:51:28.380152+00:00;
  - inicio de la orden de modo GUIDED: 2026-10-24T12:51:43.282975+00:00;
  - inicio de la orden de armado: 2026-10-24T12:51:46.399698+00:00;
  - inicio de la orden de despegue: 2026-10-24T12:51:48.210970+00:00;
  - inicio de la orden de regreso al lanzamiento: 2026-10-24T12:53:36.872824+00:00;
  - inicio de la orden de aterrizaje: 2026-10-24T12:54:22.338276+00:00;
  - base de las órdenes: COMPLETE_OPERATION_RECORD;
  - fin del ejecutor: 2026-10-24T12:55:42.138208+00:00;
  - aceptación del resultado por el coordinador: 2026-10-24T12:55:42.177521+00:00.

### Hijo 2: drone_02 → v2

- Misión `agri_demo_001_h1_sector_b` (snapshot `079e25a302423996f168b65c8b2e03157fda0c9ad9b743fb64e8ea7b8c955472`), informe `f7884a1c52341d5cb5c7e9cda62695bbbf3e3e7fc1d7e9d68bc4ee92b2785850` [scenario.runs[1].mission_id, mission_sha256, report_sha256].
- Estado: **NOT_EXECUTED**; resultado: desconocido [scenario.runs[1].status, result_status].
- Puntos de interés: POI_B1 NOT_EXECUTED, POI_B2 NOT_EXECUTED [scenario.runs[1].points].
- Regreso: NOT_EXECUTED; aterrizaje: NOT_EXECUTED [scenario.runs[1].return_home, landing].
- Cronología registrada (reloj de pared UTC) [scenario.runs[1].timeline]:
  - admisión del trabajo: desconocido (no es evidencia de orden ni un despegue);
  - despacho del coordinador: desconocido;
  - inicio del ejecutor: desconocido;
  - inicio de la orden de modo GUIDED: desconocido;
  - inicio de la orden de armado: desconocido;
  - inicio de la orden de despegue: desconocido;
  - inicio de la orden de regreso al lanzamiento: desconocido;
  - inicio de la orden de aterrizaje: desconocido;
  - base de las órdenes: UNAVAILABLE_OR_TRUNCATED;
  - fin del ejecutor: desconocido;
  - aceptación del resultado por el coordinador: desconocido.

## Orden

- Estado: **NOT_ACCREDITED** [scenario.order.status]. Las horas de admisión no se usan como evidencia de orden [scenario.order.admission_times_are_order_evidence = false].
- Orden no acreditado: missing execution or coordinator timestamps [scenario.order.reason].
- Comprobaciones temporales observadas [scenario.order.checks]:
- Regla documentada del coordinador, distinta de la observación temporal: tools/preflight_sequence_worker.run_coordinator dispatches child 2 only after verifying child 1's final PASSED report [scenario.order.rule].

## Tarea terrestre R1

- R1: rover_01 hacia POI_A1 [scenario.ground_task].
- Dependencia completa: requiere **las dos** condiciones [scenario.ground_task.depends_on]:
  - secuencia aérea completada: no consta [scenario.status == AERIAL_COMPLETED_GROUND_PENDING].
  - POI_A1 alcanzado por drone_01: no consta [scenario.points.POI_A1.status == REACHED].
- Dependencia: **NOT_MET**; estado: **BLOCKED_PENDING**; órdenes enviadas: **no**; movimiento autorizado: **no** [scenario.ground_task].
- Significado: MET only states that the declared precondition holds in this record; it never authorizes rover movement [scenario.ground_task.dependency_meaning].
- Barreras registradas: Rover identity chain (XRCE client to SITL instance/SYSID and bridge/model) not established; No public rover entry point with authorization and reservations; No navigation to a position: rover control offers bounded velocity/turn only; Execution gate covers the two_drones profile only [scenario.ground_task.barriers].

## Autorización registrada

- OPERATOR_DECLARED_VIA_AGENT, alcance «These two ordered snapshots only; SITL; no further flights or hardware», autenticada: no [scenario.authorization_recorded].

## Alcance y limitaciones

- Registro historical a fecha 2026-10-24T12:59:51.127955+00:00; disponibilidad actual NOT_CHECKED; restricciones actuales NOT_CHECKED; autorización operativa: no [scope].
- Percepción: NONE: points of interest are operator-declared scenario inputs; no imagery, detection or crop analysis [limitations.perception].
- Velocidad: comandada no, medida no; waypoint speed_kmh, or cruise_speed_kmh when null, used only to estimate time/battery [limitations.speed].
- Marco común entre vehículos validado: no [limitations.common_frame].
- Vuelo simultáneo: no [limitations.simultaneous_flight].
- Fuente de los datos de vuelo: executor observations via AP_DDS, not independent telemetry [limitations.telemetry_source].

## Fuentes

- Registro de vinculación `desconocido`, SHA-256 `SYNTHETIC_DEMO` [sources.binding_record].
- Plan de la secuencia, SHA-256 `a1821ce7c0d16620af683759049737ace1096d3a18a2202b571567c3ee245e30` [scenario.sequence.plan_sha256].
- Informes y snapshots de cada ejecución: hashes citados en su apartado.

## Tareas del escenario y R1

Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. Cada valor cita su campo entre corchetes.

| Tarea | Vehículo | Depende de | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | — | FAILED/FAILED [scenario.runs] | misión `321ad647ab9c…`, informe `183a68b92db7…` [scenario.runs] |
| A2 | drone_02 | A1 PASSED (coordinator dispatches child 2 only after it) | NOT_EXECUTED/None [scenario.runs] | misión `079e25a30242…`, informe `f7884a1c5234…` [scenario.runs] |
| R1 | rover_01 | Sequence COMPLETED and POI_A1 REACHED by drone_01 | NOT_REQUESTED [record.state] | candidato `ninguno` [preparation.candidate_sha256] |

### R1

- Dependencia: **NOT_MET**; elegibilidad: **NOT_ELIGIBLE** [preparation.stages].
- Bloqueos: sequence_completed, target_reached_by_drone_01, dependency_met [preparation.blockers].
- Destino: {"status": "NOT_AVAILABLE", "missing": []} [candidate.target_in_rover_frame].
- Transformación: null [candidate.frame_transform].
- Autorización: "ABSENT" [record.authorization].
- Admisión: {"state": "NOT_REQUESTED", "run_id": null, "executor_session_id": null, "authorized_session_id": null, "executor_kind": null} [record].
- Órdenes intentadas/enviadas: sin dato/sin dato [acceptance.commands_*].
- Llegada observada: sin dato (error mínimo sin dato m, tolerancia sin dato m) [acceptance].
- Permanencia: sin dato s de sin dato s (reloj de simulación) [acceptance.dwell_observed_s].
- Parada confirmada: sin dato; pérdida de observación: sin dato [acceptance].
- Evaluación del contrato sobre las muestras: sin resultado; motivos que impiden aceptar: ninguno [record.acceptance].
- Estado del trabajo en el ejecutor: sin dato; estado R1: **NOT_REQUESTED** [record.state].
- Procedencia: sin dato; origen declarado por el ejecutor: sin dato; contrato sin resolver: sin dato [acceptance.provenance].
- Marco: sin dato; etiqueta del ejecutor: sin dato [acceptance.frame_basis].
- La autorización es una declaración vinculada al candidato y a la sesión; no es autenticación humana.
- Etapas registradas: ninguna [record.history].
- Parámetros autorizados: null [acceptance.authorized_parameters].
- Armado observado en la parada: sin dato; política de cierre autorizada: null; aplicada: null [acceptance.finalization].
- Cierre según el ejecutor: null; trabajo: sin dato [acceptance.closure].
- Motivo: R1 en estado NOT_REQUESTED: sin resultado terrestre aceptable.
- Dobles de prueba en las entradas: ['completion_evidence', 'execution_limits', 'frame_transform', 'ground_tolerance_m', 'rover_mission', 'target_in_rover_frame'] [preparation.inputs_include_test_doubles].
- Recuperación: executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator.

#### Hechos medidos

Estado: NOT_PROVIDED [preparation.measured_facts].

**Escenario:** `FAILED`; completo: **no** [scenario_with_r1].
