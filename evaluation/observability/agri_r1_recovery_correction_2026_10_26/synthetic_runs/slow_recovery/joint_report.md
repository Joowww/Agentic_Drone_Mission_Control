<!-- SYNTHETIC JOINT RUN: slow recovery after a dwell disturbance; no rover moved -->
## Tareas del escenario y R1

Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. Cada valor cita su campo entre corchetes.

| Tarea | Vehículo | Depende de | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | — | COMPLETED/PASSED [scenario.runs] | misión `321ad647ab9c…`, informe `183a68b92db7…` [scenario.runs] |
| A2 | drone_02 | A1 PASSED (coordinator dispatches child 2 only after it) | COMPLETED/PASSED [scenario.runs] | misión `079e25a30242…`, informe `f7884a1c5234…` [scenario.runs] |
| R1 | rover_01 | Sequence COMPLETED and POI_A1 REACHED by drone_01 | VERIFIED_SYNTHETIC [record.state] | candidato `8dc4b8979736` [preparation.candidate_sha256] |

### R1

- Dependencia: **MET**; elegibilidad: **ELIGIBLE** [preparation.stages].
- Bloqueos: ninguno [preparation.blockers].
- Destino: {"x_m": 0.8, "y_m": 0.4, "frame": "odom"} [candidate.target_in_rover_frame].
- Transformación: {"status": "VERIFIED", "sha256": "4444444444444444444444444444444444444444444444444444444444444444", "from_frame": "SYNTHETIC_POI_FRAME", "to_frame": "odom"} [candidate.frame_transform].
- Autorización: {"source": "OPERATOR_DECLARED", "authorization_sha256": "971af006d23bf633fa9dc5f4e3e7e8cab3ced05aae4e8c78f1932df6df1f9022"} [record.authorization].
- Admisión: {"state": "VERIFIED_SYNTHETIC", "run_id": "79f88293-f36b-4229-9030-1751a4ba02fc", "executor_session_id": "00000000-0000-4000-8000-00000000c0de", "authorized_session_id": "00000000-0000-4000-8000-00000000c0de", "executor_kind": "ROVER_GROUND_EXECUTOR"} [record].
- Órdenes intentadas/enviadas: True/216 [acceptance.commands_*].
- Llegada observada: True (error mínimo 0.0 m, tolerancia 0.05 m) [acceptance].
- Permanencia: 5.05 s de 5.0 s (reloj de simulación) [acceptance.dwell_observed_s].
- Parada confirmada: True; pérdida de observación: False [acceptance].
- Evaluación del contrato sobre las muestras: VERIFIED; motivos que impiden aceptar: ninguno [record.acceptance].
- Estado del trabajo en el ejecutor: FINISHED; estado R1: **VERIFIED_SYNTHETIC** [record.state].
- Procedencia: EXECUTOR_LOCAL_RECORDS_MATCHED; origen declarado por el ejecutor: SYNTHETIC_TEST_DOUBLE; contrato sin resolver: [] [acceptance.provenance].
- Marco: CANDIDATE_TRANSFORM_VERIFIED_INPUT+EXECUTOR_BOUND_POSE_REFERENCE_DIGEST; etiqueta del ejecutor: DECLARED_ADAPTER_BINDING_NOT_INDEPENDENTLY_VERIFIED [acceptance.frame_basis].
- La autorización es una declaración vinculada al candidato y a la sesión; no es autenticación humana.
- Etapas registradas: ADMISSION_REQUESTED → ADMITTED → START_REQUESTED → VERIFIED_SYNTHETIC [record.history].
- Parámetros autorizados: {"target": {"x_m": 0.8, "y_m": 0.4, "frame": "odom"}, "transform_sha256": "4444444444444444444444444444444444444444444444444444444444444444", "arrival_tolerance_m": 0.05, "dwell_s": 5.0, "global_timeout_s": 120.0} [acceptance.authorized_parameters].
- Armado observado en la parada: [True, True]; política de cierre autorizada: {"kind": "DISARM_AFTER_OBSERVED_STOP_V1", "timeout_s": 5.0}; aplicada: {"policy": "DISARM_AFTER_OBSERVED_STOP_V1", "status": "DISARMED_STATIONARY_OBSERVED", "disarm_attempted": true, "disarm_acknowledged": true, "disarmed_observed": true} [acceptance.finalization].
- Cierre según el ejecutor: {"goal_outcome": "GOAL_REACHED", "stop_observed": true, "armed_observed": false, "job_close": "COMMIT_ELIGIBLE", "vehicle_close": "DISARMED_STATIONARY_OBSERVED", "reservation_release": "ELIGIBLE_AFTER_DURABLE_RESULT"}; trabajo: FINISHED [acceptance.closure].
- Motivo: contrato cumplido con entradas o sesión sintéticas: completo solo como demostración.
- Dobles de prueba en las entradas: ['completion_evidence', 'execution_limits', 'finalization_policy', 'frame_transform', 'ground_tolerance_m', 'rover_mission', 'target_in_rover_frame'] [preparation.inputs_include_test_doubles].
- Recuperación: executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator.

**Escenario:** `SYNTHETIC_COMPLETE`; completo: **no**; completo solo en la demostración sintética [scenario_with_r1].

