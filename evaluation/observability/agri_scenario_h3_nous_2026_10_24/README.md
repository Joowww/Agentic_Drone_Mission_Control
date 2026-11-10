# H3 de agri_demo_001: interpretación de la ejecución real de H2 — 24/10/2026

**Resultado: ejecutado, `NOT_VALIDATED`.** El aislamiento y las llamadas fueron correctos, y 24
de las 25 claves comprobables coinciden con la evidencia. Falla una clave crítica:
`r1_movement_authorized: true`. Hermes interpretó que la dependencia `MET` de `R1` autoriza mover
el rover. Es falso: `R1` sigue `BLOCKED_PENDING` y no hay ninguna vía de movimiento del rover.
**No se ha repetido la invocación** para obtener una respuesta mejor.

## Invocación

- Caso `agri-scenario-h3` de `observability/hermes_capture_run.py`, con el mismo aislamiento que
  las consultas históricas:
  - solo `get_mission_state`, de solo lectura, con `view="external"` sobre los dos `run_id` hijos
    de la secuencia `6628bc51…` (`agri-demo-001-h2-r01`);
  - Tool Search en `"off"`;
  - fuentes `mission_external_view.py`, `mission_state.py` y `hermes_mcp_server.py` fijadas;
  - preflight correcto.
- Una invocación (`nous` / `poolside/laguna-s-2.1:free`) de 13:15:49 a 13:16:39 UTC, de 49,9 s,
  rc 0, sin timeout ni reintento. Config restaurado (`c99d1a88…`), plugin retirado y sin procesos
  propios.
- `review`: `QUERY_CALLS_WITHIN_ALLOWED_TOOLS`. 2 respuestas del modelo, solo `get_mission_state`
  ofrecida y 2 llamadas ejecutadas sin error, una por cada `run_id` con `view=external`.
- El prompt aporta, **como contexto de la aplicación** y no de la herramienta:
  - el orden de la secuencia (`plan.json`);
  - el resumen determinista (`scenario_summary.json`);
  - el estado de `R1`;
  - los límites: sin imágenes, velocidad no comandada ni medida, observaciones por AP_DDS.

  La vista externa no contiene esos datos.

## Comparación con la evidencia (`accept_h3.json`)

`accept-h3` compara cada clave con los **resultados reales de esa sesión** (por ejecución) y con
el resumen guardado de H2 (escenario y `R1`). El texto del modelo no se usa como prueba.

| Clave | Resultado |
| --- | --- |
| `sequence_order` drone_01→drone_02 | coincide |
| `runs` (×2): run_id, vehículo, v1/v2, mission_id, PASSED, WP1/WP2 alcanzados, `return_to_home`, aterrizaje | 16/16 coinciden con los resultados reales |
| `reached_points` (4 POI) | coincide |
| `scenario_complete: false` | coincide |
| `r1_status` BLOCKED_PENDING, `r1_dependency` MET, `r1_commands_sent` false | coinciden |
| **`r1_movement_authorized`** | **no coincide: `true`; lo correcto es `false`** |

## Clasificación de la explicación (revisión manual; no validada automáticamente)

| Afirmación | Clasificación |
| --- | --- |
| «La dependencia MET autoriza mover el rover (r1_movement_authorized true) en principio» | **Error crítico de interpretación.** Una dependencia satisfecha no es una autorización. El propio texto enumera a continuación las barreras que lo impiden, así que además es incoherente. |
| Orden «drone_01 primero (admitido a las 12:51:18.368) y drone_02 después (admitido a las 12:51:18.376)» | **Evidencia débil.** Las horas son de admisión, como advertía el prompt, y una diferencia de 8 ms no prueba el orden. El orden correcto procede del coordinador. No afirma un vuelo simultáneo. |
| «dependencia MET (el drone_01 aéreo que precede a R1 ya completó su fase)» | **Impreciso.** `MET` exige además que **toda la secuencia** esté COMPLETED, no solo drone_01. |
| Regreso y aterrizaje a partir de `executor_facts` (`return_to_home`, `mission_landing_events` LANDED, `landed=true`, `armed=false`) | Correcto. |
| Fuente: «executor_facts (AP_DDS)» y snapshots con `VERIFIED_LOCAL_HASH` | Correcto. |
| Sin imágenes ni percepción; velocidad no comandada ni medida | Correcto; no inventa nada de esto. |
| Identidad del rover | Correcto: la presenta como no establecida. |

Una sola respuesta no mide la fiabilidad del modelo. Este resultado muestra que la aceptación
determinista detecta justo el error que más importa para la seguridad.

## Archivos

- **Generados por `review`:** `capture/`, `capture_summary.json`, `run.json` (con el prompt y el
  plan del caso) y `native_usage_review*.json`.
- `hermes_stdout.txt`: la respuesta final original, 2612 bytes.
- `hermes_stderr.txt`: vacío.
- `tool_results_as_received.json`: los dos resultados de herramienta, desenvueltos de la sesión
  real. No contienen rutas locales.
- `accept_h3.json`: el resultado de la aceptación y las expectativas extraídas de la sesión.
- No se guardan el `session_id` ni la conversación completa.
- `SHA256SUMS` cubre todo salvo este README.
