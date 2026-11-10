# Coordinación agrícola hasta R1 — demostración offline e integración, 25/10/2026

**Estado.** El coordinador recorre todas las etapas de R1 con el ejecutor sustituido por un doble
etiquetado `TEST_DOUBLE`. **Ningún rover se ha movido.** La ruta real sigue bloqueada por el
ejecutor de Codex. El H2 real sigue `AERIAL_COMPLETED_GROUND_NOT_REQUESTED`, sin completar
([informe](ground_report_h2_real.md)).

## Qué se ha implementado

| Pieza | Dónde | Qué hace |
| --- | --- | --- |
| Modelo completo de la misión | `scenario_tasks` (`reporting/agri_scenario_summary.py`) | A1, A2 y R1 con sus vehículos, dependencias, artefactos y hashes, destino y marco, criterios del objetivo, y las etapas de autorización, admisión, ejecución y recuperación, tomados de la vista, la preparación y el registro |
| Transformación obligatoria | `prepare_ground_task` (`frame_transform`) | Sin una transformación `VERIFIED`, con hash y terminada en el marco del objetivo, no hay candidato. POI_A1 nunca se convierte en un objetivo del rover por suposición |
| Elegibilidad con hechos actuales | `prepare_ground_task(executor_facts=…)` | La navegación a posición, la política, la entrada pública con reservas, el perfil del gate y que identidad y *readiness* se hayan comprobado ahora vienen del ejecutor. Una identidad histórica no cuenta |
| Coordinador de R1 | `tools/agri_ground_coordinator.py` | Recorre todas las etapas (detalle abajo), con un único registro por clave de solicitud |
| Ruta real | `CodexGroundExecutor` | Llama a `admit_ground_trial` y `query_ground_trial` sin modificarlas y conserva sus rechazos tal cual |
| Demostración | `tools/agri_ground_demo.py` | Doble del ejecutor y nueve variantes que recorren los componentes reales |
| Informe | `render_ground_report`; `report --view-file … --ground [--r1-record …]` | Por tarea: estado, bloqueos, procedencia, órdenes, llegada, permanencia, parada, incertidumbre y completitud. Cada valor cita su campo |
| Odometría | `odometry_summary` (`tools/rover_passive_journal.py`, `--odometry`) | Estadística descriptiva de las muestras retenidas en `/3`, por GID y por par de marcos |

**Etapas del coordinador:** resultados aéreos verificados → dependencia → candidato → elegibilidad →
autorización → admisión → seguimiento → aceptación (`evaluate_ground_result`) → resultado del
escenario.

**Por qué el coordinador aéreo no se toca.** `tools/preflight_sequences.py` y su worker se cierran
al llegar a `FINISHED`, y H2 depende de ellos. R1 es una etapa posterior, vinculada a la secuencia
por su id y por los hashes de la vista. Persiste con la misma gramática de claves
(`jobs.key_path`), `atomic_json` y `file_mutex`, en un único registro por clave bajo
`missions/generated/agri_ground_tasks`. No hay ninguna máquina de estados aparte de ese registro,
y nunca se ha creado ese directorio real.

**Estados del registro:**
- **En curso:** `ADMISSION_REQUESTED`, `ADMISSION_UNCONFIRMED`, `ADMITTED`, `RUNNING`.
- **Terminales:** `REJECTED_BY_EXECUTOR`, `FAILED`, `UNCERTAIN`, `REJECTED_RESULT`, `VERIFIED`,
  `VERIFIED_SYNTHETIC`.

Solo `VERIFIED` completa el escenario, y exige `origin: EXECUTED`, el ejecutor real de Codex y
entradas sin dobles. Un fixture que diga `EXECUTED` con el doble queda en `VERIFIED_SYNTHETIC`, y
el escenario en `SYNTHETIC_COMPLETE` con `scenario_complete: false`.

## Demostración offline (`demo_output.json`)

```bash
.venv/bin/python -m tools.agri_ground_demo --out <directorio-nuevo>
```

**Cómo está construida:**
- **Parte aérea:** el registro real de H2, leído sin escribir y reidentificado como escenario
  sintético (`sequence_id` propio, sin claves ni registros de H2). Pasa por el `scenario_view` real.
- **Parte terrestre:** las muestras las genera el doble a partir del objetivo del candidato
  (aproximación y permanencia); no hay ningún JSON de éxito escrito de antemano.

| Variante | Solicitud | Estado final | Llamadas a `admit` | Escenario |
| --- | --- | --- | ---: | --- |
| completa | `CREATED` | `VERIFIED_SYNTHETIC` | 1 | `SYNTHETIC_COMPLETE` |
| primer dron fallido | `BLOCKED` (dependencia `NOT_MET`) | — | 0 | `FAILED` |
| POI no alcanzado (variante de vista) | `BLOCKED` | — | 0 | `AERIAL_COMPLETED_R1_DEPENDENCY_NOT_MET` |
| transformación ausente | `BLOCKED` (`NO_CANDIDATE`) | — | 0 | `…_GROUND_NOT_REQUESTED` |
| autorización ausente | `BLOCKED` | — | 0 | `…_GROUND_NOT_REQUESTED` |
| el ejecutor rechaza | `CREATED` | `REJECTED_BY_EXECUTOR` | 1 | `…_GROUND_REJECTED_BY_EXECUTOR` |
| permanencia insuficiente | `CREATED` | `FAILED` (`PASSED_THROUGH_NO_DWELL`) | 1 | `…_GROUND_FAILED` |
| parada incierta | `CREATED` | `UNCERTAIN` (`STOP_UNCONFIRMED`) | 1 | `…_GROUND_UNCERTAIN` |
| respuesta de admisión perdida | `UNCONFIRMED` | `VERIFIED_SYNTHETIC` (recuperada por consulta) | **1** | `SYNTHETIC_COMPLETE` |

En todas las variantes, `scenario_complete` es `false`. Material relacionado:
[`ground_report_synthetic_complete.md`](ground_report_synthetic_complete.md) es el informe de la
variante completa, marcado como sintético, y [`r1_record_synthetic_complete.json`](r1_record_synthetic_complete.json)
su registro.

## Fallos y recuperación (`tests/test_agri_ground_coordinator.py`, 16 tests)

- **Preparar y consultar** no admiten ni escriben.
- **Repetir una solicitud** devuelve `EXISTING`. Otra solicitud con la misma clave da `REQUEST_CONFLICT`.
- **Respuesta de admisión perdida:**
  - El intento queda escrito antes de llamar al ejecutor (`ADMISSION_REQUESTED`).
  - Si se pierde la respuesta, el registro queda en `ADMISSION_UNCONFIRMED` y **nunca se vuelve a
    admitir**.
  - Se recupera solo con una consulta de solo lectura por clave. Sin esa consulta, queda
    `ADMISSION_UNCONFIRMED` indefinidamente.
- **Coordinador reiniciado tras el intento:** se recupera desde el registro.
- **Resultados de otra sesión, misión, vehículo o trabajo:** `REJECTED_RESULT`
  (`BINDING_MISMATCH`).
- **Trabajo `PASSED` sin `r1_ground_result`:** `REJECTED_RESULT`.
- **Registro alterado:** cualquier hash que no coincida da `RECORD_INTEGRITY_ERROR`, sin llamar al
  ejecutor.
- **Estado incierto:** `UNCONFIRMED` del ejecutor pasa a `UNCERTAIN`, que es terminal y no se vuelve
  a consultar.
- **Reservas:** la interfaz no tiene ninguna operación de liberación; las reservas son del ejecutor.
- **Ruta real:** el coordinador ni siquiera llama al ejecutor (`NOT_ELIGIBLE`). Llamado
  directamente, el ejecutor responde `BLOCKED` / `OPERATIONAL_ROVER_POLICY_DISABLED` antes de
  escribir nada.

## Contrato exacto que necesita el coordinador del ejecutor de Codex

> **Superado (25/10/2026, tarde).** El ejecutor de Codex ya ofrece navegación (`ROVER_NAVIGATE_V1`), `executor_facts()`, `coordination_context`, sesión y `lookup_ground_trial`, y el adaptador final usa ese contrato. La matriz vigente y los bloqueos reales están en [la evidencia del recorrido conjunto](../agri_r1_joint_offline_2026_10_25/README.md). Esta sección se conserva como registro.

Interfaz `GroundExecutor` (sustituible):

| Método | Contrato |
| --- | --- |
| `facts()` | Hechos **actuales**: `kind`, `request_kinds`, `route_execution` (distinto de `NOT_SUPPORTED`), `result_has_position_outcome: true`, `public_entry_point_with_reservations`, `execution_gate_profiles` (que incluya `two_drones_rover`), `identity_checked_now`, `readiness_checked_now` y `policy_enabled` |
| `admit(task)` | Recibe `request_key`, `candidate` y `candidate_sha256`, `mission_path`/`mission_sha256`, `authorization` y `authorization_sha256`, y `result_schema: tfg.agri-r1-ground-result/1`. Responde `{"status": "ADMITTED", "run_id", "session_id"}`, o `BLOCKED`/`REJECTED` con `reason`. Debe ser idempotente por `request_key`. **Sin `session_id`, la admisión queda sin confirmar** |
| `lookup(request_key)` | **Nuevo:** solo lectura; devuelve `{run_id, session_id}` si la clave se admitió, o nada. Hoy no existe, por eso la ruta real queda en `ADMISSION_UNCONFIRMED` si se pierde una respuesta |
| `query(run_id)` | Solo lectura: `ADMITTED`, `RUNNING`, `FINISHED`, `UNCONFIRMED`, `BLOCKED` o `NOT_FOUND`. Si es `FINISHED`, `report.r1_ground_result` contiene el documento `tfg.agri-r1-ground-result/1`, con la ficha de la revisión 2 (muestras crudas en orden, dos relojes, `stop.status`), `origin: EXECUTED` y un `binding` cuyos `session_id`/`ground_run_id` coinciden con la admisión |

**Hoy, `admit_ground_trial` solo acepta `ROVER_BOUNDED_CONTROL`, no expone `session_id` ni
`lookup`, y su informe no lleva `r1_ground_result`.** Lo que falta en el ejecutor es eso; el
coordinador ya está preparado para consumirlo.

## Análisis de la odometría

**No existe ninguna captura `/3` real.** El ensayo de Codex del 25/10 (`rover_xrce_trial_2026_10_25`,
`0f678646…`) terminó sin colector porque la GUI se vio en negro.

**Qué está probado y con qué:**
- `odometry_summary` está probado con la salida **sintética** del serializador real.
- Sobre las cinco capturas históricas `/1` y `/2` solo informa de los intervalos y los marcos, porque
  no tienen campos de pose.

**Un hecho histórico que no se atribuye a ninguna causa.** En las capturas `/1`, los sellos de las
muestras retenidas van cada 20 ms y su recepción cada unos 120 ms. Puede deberse a la velocidad de
la simulación o a una cola de mensajes.

**Lo que informa ya:**
- dispersión de posición y orientación por grupo;
- velocidad residual;
- intervalos de sellos y de recepción, por separado;
- estabilidad de los marcos;
- covarianzas declaradas (una covarianza cero se cuenta, nunca se lee como certeza).

**Lo pendiente:**
- aprobar la tolerancia y los umbrales;
- verificar la transformación;
- asociar publicador, modelo y SYSID;
- la frecuencia y la pérdida del flujo completo (la captura siempre es selectiva);
- llegada, permanencia y progreso, que necesitan una prueba de movimiento.

## Pasos pendientes para el primer R1 en SITL

> **Superado.** Una GUI visible no es un requisito universal de una captura pasiva: la vía headless solo valdría si Codex la soporta y la ejecuta con su procedimiento protegido. La lista vigente está en [la evidencia del recorrido conjunto](../agri_r1_joint_offline_2026_10_25/README.md#bloqueos-reales-para-el-primer-r1-en-sitl).

1. **Codex:** que la GUI se vea y hacer una captura pasiva `/3` en reposo. Con ella se miden la
   dispersión, la velocidad residual y los intervalos.
2. **Codex:** cadena de identidad del rover y `Observation` con pose y marco padre (matriz de
   identidad, puntos 1–4).
3. **Transformación verificada** mediante la comprobación de tres vehículos (diseño pendiente de
   revisión). Con ella se rellenan `target_in_rover_frame` y `frame_transform`.
4. **Codex:** un ejecutor con navegación a posición, más `session_id`, `lookup` y `r1_ground_result`.
   Su `facts()` tendrá que declarar el perfil y las comprobaciones actuales.
5. **Joel y el tutor:** aprobar los parámetros de R1. Después, misión `rover_01` validada,
   autorización explícita y un único ensayo autorizado. El coordinador lo acepta con este mismo
   código.
