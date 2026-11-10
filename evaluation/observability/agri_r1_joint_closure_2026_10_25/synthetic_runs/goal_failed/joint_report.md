<!-- SYNTHETIC JOINT RUN: real coordinator/adapter/executor/worker, kinematic session; no rover moved -->
## Tareas del escenario y R1

Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. Cada valor cita su campo entre corchetes.

| Tarea | Vehículo | Depende de | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | — | COMPLETED/PASSED [scenario.runs] | misión `321ad647ab9c…`, informe `183a68b92db7…` [scenario.runs] |
| A2 | drone_02 | A1 PASSED (coordinator dispatches child 2 only after it) | COMPLETED/PASSED [scenario.runs] | misión `079e25a30242…`, informe `f7884a1c5234…` [scenario.runs] |
| R1 | rover_01 | Sequence COMPLETED and POI_A1 REACHED by drone_01 | FAILED [record.state] | candidato `a1edc9020bcf` [preparation.candidate_sha256] |

### R1

- Dependencia: **MET**; elegibilidad: **ELIGIBLE** [preparation.stages].
- Bloqueos: ninguno [preparation.blockers].
- Destino: {"x_m": 0.8, "y_m": 0.4, "frame": "odom"} [candidate.target_in_rover_frame].
- Transformación: {"status": "VERIFIED", "sha256": "4444444444444444444444444444444444444444444444444444444444444444", "from_frame": "SYNTHETIC_POI_FRAME", "to_frame": "odom"} [candidate.frame_transform].
- Autorización: {"source": "OPERATOR_DECLARED", "authorization_sha256": "a13b597b25510e0760900e6bfd5ce7eed6fdf83482d162455209eea4f48d6ff4"} [record.authorization].
- Admisión: {"state": "FAILED", "run_id": "253dd56b-3925-4975-8a80-b5482c65116a", "executor_session_id": "00000000-0000-4000-8000-00000000c0de", "authorized_session_id": "00000000-0000-4000-8000-00000000c0de", "executor_kind": "ROVER_GROUND_EXECUTOR"} [record].
- Órdenes intentadas/enviadas: True/100 [acceptance.commands_*].
- Llegada observada: False (error mínimo 0.894 m, tolerancia 0.05 m) [acceptance].
- Permanencia: 0.0 s de 5.0 s (reloj de simulación) [acceptance.dwell_observed_s].
- Parada confirmada: True; pérdida de observación: False [acceptance].
- Evaluación del contrato sobre las muestras: FAILED; motivos que impiden aceptar: ['NO_PROGRESS', 'NOT_REACHED_OUT_OF_TOLERANCE'] [record.acceptance].
- Estado del trabajo en el ejecutor: FINISHED; estado R1: **FAILED** [record.state].
- Procedencia: EXECUTOR_LOCAL_RECORDS_MATCHED; origen declarado por el ejecutor: SYNTHETIC_TEST_DOUBLE; contrato sin resolver: [] [acceptance.provenance].
- Marco: CANDIDATE_TRANSFORM_VERIFIED_INPUT+EXECUTOR_BOUND_POSE_REFERENCE_DIGEST; etiqueta del ejecutor: DECLARED_ADAPTER_BINDING_NOT_INDEPENDENTLY_VERIFIED [acceptance.frame_basis].
- La autorización es una declaración vinculada al candidato y a la sesión; no es autenticación humana.
- Etapas registradas: ADMISSION_REQUESTED → ADMITTED → START_REQUESTED → FAILED [record.history].
- Parámetros autorizados: {"target": {"x_m": 0.8, "y_m": 0.4, "frame": "odom"}, "transform_sha256": "4444444444444444444444444444444444444444444444444444444444444444", "arrival_tolerance_m": 0.05, "dwell_s": 5.0, "global_timeout_s": 120.0} [acceptance.authorized_parameters].
- Armado observado en la parada: [True, True]; política de cierre autorizada: {"kind": "DISARM_AFTER_OBSERVED_STOP_V1", "timeout_s": 5.0}; aplicada: {"policy": "DISARM_AFTER_OBSERVED_STOP_V1", "status": "DISARMED_STATIONARY_OBSERVED", "disarm_attempted": true, "disarm_acknowledged": true, "disarmed_observed": true} [acceptance.finalization].
- Cierre según el ejecutor: {"goal_outcome": "GOAL_FAILED", "stop_observed": true, "armed_observed": false, "job_close": "COMMIT_ELIGIBLE", "vehicle_close": "DISARMED_STATIONARY_OBSERVED", "reservation_release": "ELIGIBLE_AFTER_DURABLE_RESULT"}; trabajo: FINISHED [acceptance.closure].
- Motivo: aceptación FAILED: ['NO_PROGRESS', 'NOT_REACHED_OUT_OF_TOLERANCE'].
- Dobles de prueba en las entradas: ['completion_evidence', 'execution_limits', 'frame_transform', 'ground_tolerance_m', 'rover_mission', 'target_in_rover_frame'] [preparation.inputs_include_test_doubles].
- Recuperación: executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator.

**Escenario:** `AERIAL_COMPLETED_GROUND_FAILED`; completo: **no** [scenario_with_r1].

