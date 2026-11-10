## Tareas del escenario y R1

Generado por código a partir de la vista, la preparación de R1 y el registro de coordinación. Cada valor cita su campo entre corchetes.

| Tarea | Vehículo | Depende de | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| A1 | drone_01 | — | COMPLETED/PASSED [scenario.runs] | misión `321ad647ab9c…`, informe `183a68b92db7…` [scenario.runs] |
| A2 | drone_02 | A1 PASSED (coordinator dispatches child 2 only after it) | COMPLETED/PASSED [scenario.runs] | misión `079e25a30242…`, informe `f7884a1c5234…` [scenario.runs] |
| R1 | rover_01 | Sequence COMPLETED and POI_A1 REACHED by drone_01 | NOT_REQUESTED [record.state] | candidato `ninguno` [preparation.candidate_sha256] |

### R1

- Dependencia: **MET**; elegibilidad: **NOT_ELIGIBLE** [preparation.stages].
- Bloqueos: rover_identity_accredited, position_navigation_supported, operational_rover_policy_enabled, required_data_present, rover_identity_checked_now, readiness_checked_now, public_entry_point_with_reservations, execution_gate_covers_rover_profile [preparation.blockers].
- Destino: {"status": "NOT_AVAILABLE", "missing": ["completion_evidence", "frame_transform", "ground_tolerance_m", "rover_mission", "target_in_rover_frame"]} [candidate.target_in_rover_frame].
- Transformación: null [candidate.frame_transform].
- Autorización: "ABSENT" [record.authorization].
- Admisión: {"state": "NOT_REQUESTED", "run_id": null, "session_id": null, "executor_kind": null} [record].
- Órdenes intentadas/enviadas: sin dato/sin dato [acceptance.commands_*].
- Llegada observada: sin dato (error mínimo sin dato m, tolerancia sin dato m) [acceptance].
- Permanencia: sin dato s de sin dato s (reloj de simulación) [acceptance.dwell_observed_s].
- Parada confirmada: sin dato; pérdida de observación: sin dato [acceptance].
- Resultado de la aceptación: sin resultado  [record.acceptance].
- Dobles de prueba en las entradas: ninguno [preparation.inputs_include_test_doubles].
- Recuperación: executor stop(); UNCERTAIN/UNCONFIRMED kept, never released by the coordinator.

**Escenario:** `AERIAL_COMPLETED_GROUND_NOT_REQUESTED`; completo: **no** [scenario_with_r1].

