# R1: arranque recuperable, cierre y aceptación con las interfaces definitivas — 25/10/2026

**Resultado.** El recorrido conjunto usa componentes reales en todas las etapas: coordinador →
adaptador → `admit_ground_trial` → `start_ground_trial` → worker → `RoverControlCore.navigate` →
finalización `DISARM_AFTER_OBSERVED_STOP_V1` → `query_ground_trial` / `lookup_ground_trial` →
aceptación.

- **Sintético:** solo la sesión física, la cinemática de Codex ampliada, que integra las órdenes de
  velocidad del controlador y responde al servicio de desarme.
- **Ningún rover se ha movido** y no hay ejecución real.
- **H2 real:** intacto e incompleto.
- **Demostración:** puede llegar a `SYNTHETIC_COMPLETE`, siempre con `scenario_complete: false`.

**Reproducción** (almacenes temporales; no usa el almacén operativo ni H2):

```bash
.venv/bin/python -m pytest -q tests/test_agri_ground_joint.py tests/test_agri_ground_coordinator.py
AGRI_JOINT_EVIDENCE_DIR=<directorio-nuevo> .venv/bin/python -m pytest -q tests/test_agri_ground_joint.py -k deterministic_report
```

**Evidencia sintética** (`synthetic_runs/<variante>/`): informe determinista, registro del
coordinador e informe del ejecutor. Las rutas temporales de pytest están sustituidas por
`<pytest-tmp>`.

| Variante | Trabajo en el ejecutor | R1 | Motivo derivado de los registros |
| --- | --- | --- | --- |
| `finalized` (cierre autorizado) | `FINISHED` | `VERIFIED_SYNTHETIC` → escenario `SYNTHETIC_COMPLETE` | Contrato cumplido con entradas y sesión sintéticas |
| `armed_hold` (sin política de cierre) | `UNCONFIRMED` | `CLOSURE_PENDING` | Llegada y permanencia observadas, parada confirmada; cierre no confirmado y reserva retenida |
| `stop_uncertain` | `UNCONFIRMED` | `CLOSURE_PENDING` | Llegada y permanencia observadas; parada **no** confirmada |
| `goal_failed` (atascado) | `FINISHED` | `FAILED` | `NO_PROGRESS`, `NOT_REACHED_OUT_OF_TOLERANCE`, con parada confirmada |

**Dato real** (separado de lo sintético): [`real_capture_eb113_analysis.json`](real_capture_eb113_analysis.json)
es la entrada de captura terminada aplicada a la captura real histórica `eb113b19`.
- **Esquema:** `/2`, con el manifiesto completo verificado.
- **Contenido:** 19 muestras de odometría de un solo GID, con marcos `odom`/`base_link`.
- **Relojes:** los sellos abarcan 0,36 s y la recepción 22,8 s; la diferencia no se atribuye.
- **Pose:** no la hay, así que no hay métricas de R1.
- **Captura `/3` terminada:** **ninguna**. La medición en reposo sigue pendiente.

## Estados del coordinador y transiciones

Hay un único registro por clave (`tfg.agri-r1-task/2`). Los estados vivos se vuelven a consultar
en solo lectura; ninguno se «arregla» readmitiendo o rearrancando.

| Estado | Significado | Sale hacia |
| --- | --- | --- |
| `ADMISSION_REQUESTED` | Intención persistida antes de llamar | `ADMITTED`, `ADMISSION_UNCONFIRMED`, `REJECTED_BY_EXECUTOR` |
| `ADMISSION_UNCONFIRMED` | Respuesta perdida o desconocida | `ADMITTED` (solo por `lookup_ground_trial`); nunca se readmite |
| `ADMITTED` / `ADMITTED_NO_WORKER` | Admisión acreditada; el ejecutor no registra worker (`ADMITTED_NOT_STARTED`) | `START_REQUESTED` |
| `START_REQUESTED` | Intención de arranque persistida bajo la exclusión del coordinador; el arranque síncrono se ejecuta fuera de ella | `START_UNCONFIRMED`, `WORKER_OBSERVED`, `CLOSURE_PENDING`, terminal |
| `START_UNCONFIRMED` | Respuesta de arranque perdida, o fase `START_INTENT_WITHOUT_CONFIRMED_WORKER` / `STARTING_WORKER_LOST_OR_UNKNOWN`. La falta de worker **no** prueba que no arrancara | Solo por consulta; nunca se rearranca |
| `WORKER_OBSERVED` | `STARTING`, `RUNNING` o `FINALIZING` con dueño vivo (incluye el worker pendiente de identidad) | `CLOSURE_PENDING`, terminal |
| `WORKER_UNCONFIRMED` | `WORKER_LOST_OR_UNKNOWN` | Solo por consulta |
| `CLOSURE_PENDING` | El informe tiene `r1_ground_result`, pero el trabajo no está confirmado: hechos del objetivo y de la parada guardados | Terminal cuando el ejecutor confirme el cierre |
| Terminales | `VERIFIED`, `VERIFIED_SYNTHETIC`, `FAILED`, `UNCERTAIN`, `EXECUTION_FAILED` (con `failure.json`), `REJECTED_RESULT`, `REJECTED_BY_EXECUTOR` | — |

**Aceptación final.** R1 queda `VERIFIED` solo cuando se cumplen a la vez:
- trabajo `FINISHED` (la confirmación del ejecutor);
- `closure.job_close` `COMMIT_ELIGIBLE`;
- `closure.vehicle_close` distinto de `UNCONFIRMED`;
- objetivo `VERIFIED` (llegada y permanencia con los parámetros del candidato);
- parada observada;
- procedencia contrastada con los registros del ejecutor;
- entradas sin dobles.

**Hechos que se conservan por separado:**
- llegada, permanencia e incumplimiento o timeout;
- parada;
- armado observado en la parada;
- política de cierre autorizada y la aplicada;
- `closure` del ejecutor y estado de su trabajo;
- incertidumbre.

## Compatibilidad con la última interfaz de Codex (20:09)

| Interfaz | Estado | Cómo la usa el coordinador |
| --- | --- | --- |
| `executor_facts()`: política, `ROVER_NAVIGATE_V1`, `recoverable_start`, `finalization_policies` | Existe y probada | Elegibilidad del intento; la política de cierre pedida debe estar soportada |
| `admit_ground_trial(…, coordination_context)` | Existe y probada | Rechazos conservados; el ejecutor rechaza por sí mismo un candidato y una autorización mezclados |
| `lookup_ground_trial(key)` | Existe y probada | Recuperación de una admisión perdida |
| `start_ground_trial(run_id, declaración, adapter_factory, readiness, cancelled)` | Existe y probada | La declaración se reconstruye desde registros durables, sin token ni memoria; el ejecutor la contrasta con su `coordination_binding` |
| `query_ground_trial(run_id)` + `worker_phase` | Existe y probada | Clasificación sin inferencias (tabla de estados) |
| `request.finalization` + `candidate.finalization_policy` | Existe y probada | La política forma parte del candidato autorizado (hash) y de la petición |
| `report.closure` (`job_close`, `vehicle_close`, `armed_observed`) y `report.finalization` | Existe y probada | Hechos de cierre en la aceptación |
| Interfaz física real (fábrica del adaptador ROS y *readiness*) | Fuera del coordinador | El adaptador la recibe inyectada; sin ella `start_ground_trial` responde `BLOCKED` (probado) |

## Defectos corregidos en esta tanda

- **La consulta de seguimiento congelaba el registro.** Con el ejecutor anterior, un `UNCONFIRMED`
  sin worker se volvía terminal. Ahora `ADMITTED_NO_WORKER` y `START_UNCONFIRMED` son estados
  explícitos y vivos.
- **El arranque dependía de memoria.** Antes hacía falta el token en el mismo proceso. Ahora se
  reconstruye desde los registros: tras perder la respuesta de admisión, o tras reiniciar el
  coordinador, se arranca una sola vez.
- **El arranque síncrono bloqueaba el seguimiento.** Ahora la intención se persiste bajo la
  exclusión y la llamada se hace fuera de ella. La exclusión y el `O_EXCL` del ejecutor impiden un
  segundo arranque.
- **La aceptación esperaba un literal de cierre** (`CONFIRMED`) que el ejecutor ya no emite. Ahora
  usa la confirmación del trabajo (`FINISHED`) más `job_close` y `vehicle_close`.
- **Mi sesión cinemática hacía retroceder los sellos** en el cambio de segundo, por redondeo. Eso
  provocaba falsos `non-progressing status_source_ns`, y **retiro mi atribución anterior de un
  `NO_PROGRESS`** en la prueba de interrupción, que venía de este defecto. Ahora el rover desplazado
  durante la permanencia se recupera, reinicia la permanencia y llega.
- **El motivo del informe** mezclaba objetivo y parada. Ahora muestra cada hecho por separado.

## Pruebas relevantes

`tests/test_agri_ground_joint.py`: 30 pruebas.
- **Recorrido:**
  - cierre autorizado;
  - HOLD armado;
  - parada incierta;
  - objetivo fallido con parada confirmada;
  - interrupción de la permanencia;
  - pérdida de observación, cambio de marco y cambio de fuente;
  - cancelación.
- **Autorización y transformación:**
  - autorización incompatible, rechazada por el coordinador y por el ejecutor;
  - transformación ausente o cambiada (el worker rechaza antes de mover);
  - un segundo R1 rechazado mientras la reserva sigue retenida.
- **Solicitudes, respuestas perdidas y reinicios:**
  - solicitudes duplicadas o en conflicto, y duplicados concurrentes de solicitud y de arranque;
  - pérdida de la respuesta de admisión y de la de arranque;
  - reinicio del coordinador.
- **Integridad de la evidencia:**
  - muestras de otro trabajo;
  - referencia a otro informe;
  - sustitución del destino;
  - `PASSED` sin muestras falsificado de forma coherente;
  - permanencia insuficiente oculta tras unas muestras finales correctas;
  - `EXECUTED` añadido a evidencia sintética;
  - el H2 real nunca se completa.

`tests/test_agri_ground_coordinator.py`: 32 pruebas.
- todas las fases de la consulta;
- caídas antes y después de cada escritura relevante (intención, admisión, arranque, consulta,
  aceptación);
- dos procesos concurrentes;
- preparar, consultar e informar con el adaptador real no crea procesos, sockets ni escrituras.

`tests/test_rover_passive_odometry_fields.py`: entrada de captura terminada.
- fixtures sintéticos: verificado frente a manipulado, no listado o rc ≠ 0;
- la captura real histórica `/2`.

Las pruebas de Codex (`test_rover_navigation.py`, `test_rover_ground_executor.py`) pasan sin
cambios. En la última ejecución pasaron los 479 tests de los suites afectados.

**Límite de confianza.** Los hashes detectan diferencias respecto a las referencias conservadas. No
autentican quién escribió todos los registros: un permanente o un `PASSED` falsificados de forma
coherente solo se detectan si contradicen las muestras.

## Para Codex (sin modificar sus archivos)

> **Corregido por Codex (26/10/2026).** La reproducción de abajo describe el comportamiento del 25/10; contra el código corregido ya no se produce. La comprobación de la corrección y la primera captura /3 real están en [la evidencia del 26/10](../agri_r1_recovery_correction_2026_10_26/README.md). Los resultados de esta evidencia no cambian.

**`GoalController`:** tras una llegada, un rover desplazado solo cuenta como progreso si mejora en
`progress_m` la **mejor distancia histórica**. Con `progress_m = 0,5 m`, una recuperación lenta (por
ejemplo, 0,02 m/s desde 0,3 m) termina en `NO_PROGRESS` aunque se acerque. Hay una reproducción
mínima en `test_codex_goal_controller_no_progress_after_disturbance`. Una recuperación rápida, como
la de la prueba conjunta, no se ve afectada.

## Requisitos pendientes para el primer R1 en SITL

1. **Codex:** la interfaz física real (fábrica del adaptador ROS con `session_id` y servicio de
   desarme, *readiness*) para `start_ground_trial`, en su procedimiento protegido.
2. **Medición:** una captura `/3` terminada en reposo. Puede ser headless solo si Codex la soporta y
   la ejecuta con su procedimiento protegido. La entrada `analyze_capture` ya está preparada; veinte
   muestras no bastan para aprobar umbrales.
3. **Medición y decisión:** la transformación real (`frame_transform` `VERIFIED` y
   `pose_reference_sha256` del adaptador).
4. **Joel y el tutor:** aprobar los parámetros de R1 (incluidos `progress_m`, a la vista del
   comportamiento anterior, y la política de cierre `DISARM_AFTER_OBSERVED_STOP_V1`), la misión
   `rover_01` y una autorización explícita; después, un único ensayo autorizado.
