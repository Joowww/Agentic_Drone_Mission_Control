# Integración multiagente → Hermes → dos drones (H2), evaluación offline: evidencia del 07/11/2026

**Tipo: SINTÉTICO.** Los materiales son de cuatro clases:
- el plan sellado de M4c-r1, cuyos agentes eran Qwen real (`REAL_LOCAL_LLM`), **leído sin modificarlo**;
- planes de agentes programados (`OFFLINE_DETERMINISTIC`);
- imágenes `SYNTHETIC_TEST`;
- eventos y declaraciones `TEST_FIXTURE`.

**Lo que no se hizo:**
- no se llamó a ningún modelo;
- no se arrancó SITL, Gazebo ni ROS 2;
- no se envió ninguna petición a un ejecutor (0 enviadas);
- **0 comandos**;
- nada se publicó en Opik.

**Procedencia:**
- **Código:** `42e788de9`, rama `feature/multiagent-opik-evaluation`, árbol limpio.
- **Codex:** *snapshot* inmutable `2e206f1fa` más su parche de revisión (`551eb1fe…`), aplicado solo en el *snapshot*.
- **Generación:**
  ```
  python -m multiagent.benchmark.two_drone_eval --out <dir> --codex-snapshot <dir> --codex-reviewed
  ```
  A ese directorio se copiaron después el JUnit y el resultado de `integration_smoke`.

## Métricas (`summary.json`)

| Métrica | Valor |
| --- | --- |
| Misiones transformadas al contrato Hermes, con reconstrucción idéntica a la validada | 33 (17 planes válidos) |
| Planes rechazados o pendientes | 10. Los 9 negativos declarados, más el escenario en que el supervisor se niega |
| Motivos de rechazo | `PLAN_MODIFIED_AFTER_VALIDATION` 3, `SENSOR_NOT_AVAILABLE` 2, `UNMET_DEPENDENCY` 2, `PROPOSAL_NOT_PLANNED` 2, `DUPLICATE_OBJECTIVE`/`POINT` 1, `ROUTE_NOT_FEASIBLE` 1, `SCHEDULE_INCONSISTENT` 1, `GEOREFERENCE_MISSING` 1 (pendiente de parámetros), `MISSION_CANCELLED` 1 |
| Objetivos sin dron | 1 (`UNASSIGNED_OBJECTIVE`): informado, no descartado |
| Planes de dos drones / con conflictos iniciales | 16 / 16 |
| Retrasos introducidos | 45 s, siempre a drone_01. **Es el mismo** con la geometría efectiva de SITL (los *spawn* del *launch*) |
| Peticiones H2 | 17 `PENDING_AUTHORIZATION` sin declaración; con una declaración `TEST_FIXTURE`, `READY_TO_REQUEST_EXECUTION` en orden secuencial. **0 enviadas** |
| Observaciones de cámara | 1 válida (POI_3 en el marco del sitio) y 10 rechazadas, cada una con su motivo |
| Rover (demo de extremo a extremo, programada y con *replay* de M4c-r1) | 2 objetivos asignados y 2 peticiones bloqueadas sin límites humanos. En el *snapshot* de Codex: contrato final `V2_READY_AWAITING_CODEX_ADAPTER`; ruta de prueba offline `BLOCKED` por `OPERATIONAL_ROVER_POLICY_DISABLED` |
| Comandos | **0** |

Los planes de los 17 escenarios se evalúan en la fase A, la planificación aérea. Por eso `scenario_mission_cancelled` aparece válido: la cancelación de ese escenario ocurre después, en la demo de precisión. La cancelación del plan se cubre con el caso negativo `cancelled`.

## Archivos

| Archivo | Contenido |
| --- | --- |
| `plans.json` | Un caso por fila |
| `camera.json` | Los casos de cámara |
| `demo.json` | La demo de extremo a extremo: programada y con *replay* |
| `pytest_multiagent.xml` | 1026 pruebas: 1024 superadas, 2 omitidas, 0 fallos |
| `integration_smoke.json` | 14 áreas en PASS. 4 pruebas de LangGraph `NOT_RUN_DATA_ABSENT`: necesitan una captura REAL que excluye `.gitignore` |
| `SHA256SUMS` | Hashes de todo |

Registro sellado de su fecha: no se modifica ni se regenera.
