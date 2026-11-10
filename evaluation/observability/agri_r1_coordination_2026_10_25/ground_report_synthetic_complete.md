<!-- SYNTHETIC DEMO: TEST_DOUBLE executor, no rover moved -->
## Tareas del escenario y R1

Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. Cada valor cita su campo entre corchetes.

| Tarea | Vehículo | Depende de | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | — | COMPLETED/PASSED [scenario.runs] | misión `321ad647ab9c…`, informe `183a68b92db7…` [scenario.runs] |
| A2 | drone_02 | A1 PASSED (coordinator dispatches child 2 only after it) | COMPLETED/PASSED [scenario.runs] | misión `079e25a30242…`, informe `f7884a1c5234…` [scenario.runs] |
| R1 | rover_01 | Sequence COMPLETED and POI_A1 REACHED by drone_01 | VERIFIED_SYNTHETIC [record.state] | candidato `6430807ece31` [preparation.candidate_sha256] |

### R1

- Dependencia: **MET**; elegibilidad: **ELIGIBLE** [preparation.stages].
- Bloqueos: ninguno [preparation.blockers].
- Destino: {"x_m": 0.0, "y_m": 0.0, "frame": "SYNTHETIC_DEMO_FRAME"} [candidate.target_in_rover_frame].
- Transformación: {"status": "VERIFIED", "sha256": "95e6e1d4cdedebf0b61e4bf13765737949960c9ea1a0bea94d4271482252d46b", "from_frame": "SYNTHETIC_POI_FRAME", "to_frame": "SYNTHETIC_DEMO_FRAME"} [candidate.frame_transform].
- Autorización: {"source": "OPERATOR_DECLARED", "authorization_sha256": "f09cbf9e849a9307bc01ba107225f4b53448f2309c0235368a8e77bc83e83ce4"} [record.authorization].
- Admisión: {"state": "VERIFIED_SYNTHETIC", "run_id": "7876d70e-0080-5e72-b2be-5d9316329a52", "session_id": "TEST-DOUBLE-SESSION-1", "executor_kind": "TEST_DOUBLE"} [record].
- Órdenes intentadas/enviadas: True/True [acceptance.commands_*].
- Llegada observada: True (error mínimo 0.361 m, tolerancia 2.0 m) [acceptance].
- Permanencia: 6.0 s de 5.0 s (reloj de simulación) [acceptance.dwell_observed_s].
- Parada confirmada: True; pérdida de observación: False [acceptance].
- Resultado de la aceptación: VERIFIED  [record.acceptance].
- Dobles de prueba en las entradas: ['completion_evidence', 'frame_transform', 'ground_tolerance_m', 'rover_identity', 'rover_mission', 'target_in_rover_frame'] [preparation.inputs_include_test_doubles].
- Recuperación: executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator.

**Escenario:** `SYNTHETIC_COMPLETE`; completo: **no**; completo solo en la demostración sintética [scenario_with_r1].

