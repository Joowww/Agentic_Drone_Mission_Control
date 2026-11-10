# Observación del dron → tarea del rover pendiente de autorización (04/11/2026, OFFLINE y SINTÉTICO)

Primer tramo de coordinación dron → rover del escenario agrícola. Módulo: [`tools/agri_observation_task.py`](../tools/agri_observation_task.py). Pruebas: [`tests/test_agri_observation_task.py`](../tests/test_agri_observation_task.py) (44 passed).

**Lo que NO existe y no se afirma:**
- percepción visual: no hay cámara ni detector;
- transformación cámara → suelo;
- transformación acreditada del marco del dron al `odom` del rover;
- GNSS en interiores;
- una ejecución conjunta dron-rover;
- ningún movimiento del rover.

## Recorrido

```
DRONE_01 → observación SINTÉTICA (cartulina roja/amarilla)
  → validación: identidad, procedencia, antigüedad, coherencia, confianza, frame,
    transformación, misión, rover disponible, área, cota del rover, duplicados
  → propuesta de tarea R1 (PROPOSED_PENDING_VALIDATION, autorización ABSENT)
  → preparación R1 existente (reporting.agri_scenario_summary.prepare_ground_task)
  → coordinador existente (tools.agri_ground_coordinator.request) SIN autorización
  → BLOCKED: ROVER_TASK_PENDING_AUTHORIZATION, sin llamar al executor
```

Se reutilizan sin cambios:
- el contrato de datos de R1 (`R1_REQUIRED_DATA`);
- `prepare_ground_task`;
- el coordinador terrestre;
- `rover_target_frame.goal_from_declared_odom`, la cota de distancia desde la pose acreditada del rover;
- el executor, que además rechaza la ejecución directa sin autorización.

## Contrato de la observación (`tfg.agri.drone-observation/1`)

| Campo | Significado |
| --- | --- |
| `observation_id`, `drone_id`, `mission_id`, `sequence_id` | Identidad. Deben coincidir con la misión aérea de la vista del escenario |
| `detection` | `type` = `COLOUR_CARD`, `colour` en {`red`, `yellow`}, `confidence` en [0, 1] (mínimo 0,8) |
| `observed_at_utc` | ISO 8601 con zona. Como máximo 300 s de antigüedad y 2 s hacia el futuro |
| `source.kind` | `SYNTHETIC_TEST` (solo con `allow_synthetic`) o `DRONE_CAMERA_PIPELINE`, que se rechaza por `NOT_IMPLEMENTED` |
| `target` | `{frame, x, y}`, o nada. El color solo no localiza nada |
| `evidence` | `{kind, sha256}` de la evidencia; no se puede reutilizar en otra observación |

**Frames:**
- `drone_launch_enu` y `wgs84` necesitan una transformación acreditada a `odom`;
- `camera_image_px` no es navegable nunca;
- cualquier otro se rechaza.

**Transformación (`tfg.agri.frame-transform/1`):**
- SE(2) a `odom`, `VERIFIED`, con digest que recompone;
- del **mismo lifecycle** y ligada al `pose_reference_sha256` de la pose acreditada del rover.
- Solo existe la versión `SYNTHETIC_TEST`. Cualquier otro productor es `TRANSFORM_PRODUCER_NOT_IMPLEMENTED`.

## Decisiones

- **Rechazo:** una observación rechazada no se registra.
- **Aceptación:** una aceptada queda en un ledger persistente. Repetirla da `DUPLICATE_OBSERVATION`, cambiarla después `OBSERVATION_CHANGED_AFTER_RECORD`, y reutilizar su evidencia `EVIDENCE_REUSED_BY_ANOTHER_OBSERVATION`.
- **Propuesta:**
  - lleva el objetivo en `odom`, la fuente y su digest, los límites de la primera navegación y las dependencias (transformación, referencia de pose, lifecycle);
  - lleva `authorization: ABSENT`;
  - sus entradas R1 van marcadas `TEST_DOUBLE`, y la preparación lo indica (`inputs_include_test_doubles`).
- **Executor real:** con su adaptador, la tarea sale `NOT_ELIGIBLE` porque `OPERATIONAL_ROVER_ENABLED` es `False`.
- **LLM:** puede proponer la tarea, pero `check_proposed_task` solo la acepta si coincide con la derivación determinista.
- **Fallos de coordinación:** si los hechos del executor fallan o la dependencia aérea no se cumple, no se crea ninguna tarea.

## Ejemplo reproducible

```bash
.venv/bin/python -m tools.agri_observation_task example --out "$(mktemp -d)/red-card"
```

**Datos:** todo SINTÉTICO: su propia pose de origen (0, 0, 0), su transformación y una cartulina roja en (2, 4) del marco del dron. No se reutiliza ninguna coordenada de una simulación anterior.

**Salida:** `DECISION: ROVER_TASK_PENDING_AUTHORIZATION · movement_authorized: False`, con el objetivo (1,0; 0,0) en `odom`.

**Archivos que escribe:** `input_observation.json`, `input_context.json`, `validation.json`, `proposal.json`, `preparation_test_double.json`, `preparation_real_executor_facts.json`, `request.json`, `decision.json` (traza) y `SHA256SUMS`. Se niega a escribir en un directorio que no esté vacío.

## Hallazgo pendiente

- **El problema:** la propuesta de visita de R1 (`R1_VISIT_PROPOSAL.global_timeout_s` = 120 s) supera el `max_duration_s` (60 s) de la primera navegación. El executor rechaza esa petición por esquema antes incluso de mirar la autorización.
- **Qué hay que hacer:** alinear los parámetros de visita de R1 con los límites del ensayo real, en revisión con el subsistema rover.

## Qué falta para una coordinación real

1. Percepción real con su evidencia.
2. Una transformación acreditada dron → `odom`, de calibración común y del mismo lifecycle.
3. La alineación de R1 con la primera navegación.
4. El primer movimiento SITL del rover autorizado.
5. Una autorización humana exacta por tarea.
