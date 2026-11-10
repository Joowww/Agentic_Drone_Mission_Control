<!-- SYNTHETIC JOINT RUN: real coordinator/adapter/executor, kinematic session double; no rover moved -->
## Tareas del escenario y R1

Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. Cada valor cita su campo entre corchetes.

| Tarea | Vehículo | Depende de | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | — | COMPLETED/PASSED [scenario.runs] | misión `321ad647ab9c…`, informe `183a68b92db7…` [scenario.runs] |
| A2 | drone_02 | A1 PASSED (coordinator dispatches child 2 only after it) | COMPLETED/PASSED [scenario.runs] | misión `079e25a30242…`, informe `f7884a1c5234…` [scenario.runs] |
| R1 | rover_01 | Sequence COMPLETED and POI_A1 REACHED by drone_01 | UNCERTAIN [record.state] | candidato `e94d79267c83` [preparation.candidate_sha256] |

### R1

- Dependencia: **MET**; elegibilidad: **ELIGIBLE** [preparation.stages].
- Bloqueos: ninguno [preparation.blockers].
- Destino: {"x_m": 0.8, "y_m": 0.4, "frame": "odom"} [candidate.target_in_rover_frame].
- Transformación: {"status": "VERIFIED", "sha256": "4444444444444444444444444444444444444444444444444444444444444444", "from_frame": "SYNTHETIC_POI_FRAME", "to_frame": "odom"} [candidate.frame_transform].
- Autorización: {"source": "OPERATOR_DECLARED", "authorization_sha256": "c63a9c75c931b4b354351ac4629dc66db23057c9cab6ff9a3b35c44261d42411"} [record.authorization].
- Admisión: {"state": "UNCERTAIN", "run_id": "414b7f15-a6ce-476c-97ce-1b5b117d6789", "executor_session_id": "00000000-0000-4000-8000-00000000c0de", "authorized_session_id": "00000000-0000-4000-8000-00000000c0de", "executor_kind": "ROVER_GROUND_EXECUTOR"} [record].
- Órdenes intentadas/enviadas: True/87 [acceptance.commands_*].
- Llegada observada: True (error mínimo 0.048 m, tolerancia 0.05 m) [acceptance].
- Permanencia: 5.05 s de 5.0 s (reloj de simulación) [acceptance.dwell_observed_s].
- Parada confirmada: True; pérdida de observación: False [acceptance].
- Evaluación del contrato sobre las muestras: VERIFIED; motivos que impiden aceptar: ['EXECUTOR_JOB_UNCONFIRMED'] [record.acceptance].
- Estado del trabajo en el ejecutor: UNCONFIRMED; estado R1: **UNCERTAIN** [record.state].
- Procedencia: EXECUTOR_LOCAL_RECORDS_MATCHED; origen declarado por el ejecutor: SYNTHETIC_TEST_DOUBLE; contrato sin resolver: [] [acceptance.provenance].
- Marco: CANDIDATE_TRANSFORM_VERIFIED_INPUT+EXECUTOR_BOUND_POSE_REFERENCE_DIGEST; etiqueta del ejecutor: DECLARED_ADAPTER_BINDING_NOT_INDEPENDENTLY_VERIFIED [acceptance.frame_basis].
- La autorización es una declaración vinculada al candidato y a la sesión; no es autenticación humana.
- Dobles de prueba en las entradas: ['completion_evidence', 'execution_limits', 'frame_transform', 'ground_tolerance_m', 'rover_mission', 'target_in_rover_frame'] [preparation.inputs_include_test_doubles].
- Recuperación: executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator.

**Escenario:** `AERIAL_COMPLETED_GROUND_UNCERTAIN`; completo: **no** [scenario_with_r1].

