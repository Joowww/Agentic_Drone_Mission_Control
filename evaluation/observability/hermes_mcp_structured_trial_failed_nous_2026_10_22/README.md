# Ensayo real de interpretación estructurada (`failed-structured`) — 22/10/2026, 17:40 UTC

**Veredicto de la revisión: `FINAL_RESPONSE_NOT_AS_EXPECTED`.**
- Aislamiento, petición, ejecución, consulta ejecutada y resultado real: todo correcto.
- La respuesta estructurada acertó **10 de 11** claves.
- Falló `return_to_home`: el modelo dio un booleano donde el registro no consta (`invented_value`).

Según los criterios fijados antes de ejecutar ([preparación](../hermes_mcp_structured_trial_prepared_2026_10_22/README.md)),
**no es un éxito**. No se repite.

Joel ejecutó el turno una sola vez en su terminal. Después Claude comprobó la restauración, revisó la
captura y preparó el dry-run:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --trial-case failed-structured --private-dir ~/tfg-hermes-capture-private/20261022T174045Z --evidence-dir evaluation/observability/hermes_mcp_structured_trial_failed_nous_2026_10_22
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_structured_trial_failed_nous_2026_10_22 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Ejecución y restauración

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free` |
| Caso | `d4519cab-ebd1-4359-b547-44be38294a6a` (17/10/2026), `FAILED`, **fallo de misión**; registro histórico, no estado actual |
| Herramienta / vista | solo `get_mission_state`, `view="external"`, Tool Search desactivado |
| Fuentes del servidor | `tools/hermes_mcp_server.py` `24068e72…`, `tools/mission_state.py` `e66dd901…` (con la vista externa) |
| Plugin | 0.6.0 (`capture.py` `36f368f6…`) |
| Turno | 17:40:46.778–17:41:11.907 UTC (25,1 s de pared); rc=0, sin timeout, stderr vacío |
| Restauración | config `c99d1a88…`, permisos 0600, sin restos de las tres ediciones; plugin retirado; 0 procesos MCP o Hermes (comprobado también con `ps`) |
| Registro consultado | `report.json` `f265cf77…` y `mission.json` `2366d5a2…`: sin cambios después del turno |
| Caché de esquemas MCP | `b354400a…` → `a977ceba…`; Hermes la reescribió y no se ha restaurado |

## Lo observado, por separado

| Pregunta | Resultado |
| --- | --- |
| ¿Qué se ofreció? | `ONLY_TRIAL_TOOL_OFFERED`: las 2 peticiones ofrecieron solo `mcp__tfg_mission_control__get_mission_state` |
| ¿Qué pidió el modelo? | `TRIAL_TOOL_REQUESTED`: la llamada 1 pidió esa herramienta una vez |
| ¿Se ejecutó? | un `tool_call`, `status=ok`, 112 ms informados por Hermes |
| ¿Fue la consulta prevista? | argumentos `run_id` = **match** y `view` = **match** (comparados por el plugin, no guardados) |
| ¿Qué devolvió realmente? | `ALL_EXPECTED_FIELDS_MATCH`: 26/26 punteros de la vista externa, envoltorio `result_json_text` |
| ¿Qué respondió el modelo? | `STRUCTURED_FIELDS_INCORRECT` (JSON dentro de un bloque ```json, admitido) |

**Respuesta, clave a clave** (solo clasificaciones; la respuesta no se guarda):

| Clave | Resultado |
| --- | --- |
| `run_id`, `historical_status`, `mission_id`, `vehicle_id`, `simulated_vehicle` | match |
| `planned_waypoint_ids` (`WP1`–`WP3`), `reached_waypoint_ids` (`WP1`,`WP2`) | match |
| `mission_landed_event_recorded` (`false`: no hubo `LANDED`) | match |
| `recovery_landing_completed` (`true`) | match |
| `current_availability` (`UNKNOWN`) | match |
| **`return_to_home`** | **`invented_value`**: esperado `UNKNOWN` porque el informe tiene `null` |

## Interpretación del fallo

- **Lo observado:** en una revisión local de la respuesta privada, hecha solo para este análisis,
  el valor fue un booleano. Ni el valor ni la respuesta se copian aquí.
- **Hipótesis no verificada:** el modelo lo tomó de `analysis_checks.return_home_reached = false`,
  que estaba en el resultado.
- **Lo que dice el contrato:** el prompt pedía `UNKNOWN` cuando el dato es `null` y no deducirlo de
  otros campos, así que la respuesta no cumple el criterio fijado.
- **Ambigüedad propia del contrato:** el prompt no nombraba qué campo del resultado corresponde a
  `return_to_home`, y la vista externa expone ese criterio de aceptación con un nombre muy parecido.
  Leer `return_home_reached=false` como "no volvió" es una interpretación razonable, aunque no es el
  dato `return_to_home` del ejecutor.
- **Qué queda demostrado:** el ensayo prueba el mecanismo de detección. **No** permite atribuir el
  fallo solo al modelo.
- **Posible ajuste futuro, no aplicado:** nombrar en el prompt el campo de origen, o separar en la
  vista los criterios de aceptación de los hechos registrados. Exige una nueva preparación y
  autorización; este resultado no se reinterpreta.

## Llamadas al modelo y tokens

Hubo 2 `llm_call` y ningún `llm_error`. No equivalen a peticiones HTTP.

| Llamada | `finish_reason` | entrada | salida | caché leída | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | tool_calls | 2401 | 78 | 224 | 2703 | 6,041 |
| 2 | stop | 3511 | 176 | 224 | 3911 | 8,094 |

- La caché escrita y el razonamiento valen 0 `zero_unconfirmed`; el total es derivado.
- Comparación con el informe nativo, `all_compared_values_equal`: entrada 5912, salida 254, caché
  leída 448, total 6614, y 2 llamadas = 2 `api_calls`.
- El título auxiliar va aparte, solo nativo: entrada 511, salida 98.

## Dry-run de Opik (NO enviado)

Destino `joowww` / `tfg-opik-hermes-real-20261021`. Procedencia verificada; sin retenidas, errores
ni avisos.

| Recurso | Id / hash |
| --- | --- |
| Traza `hermes_turn` (17:40:55.776–17:41:11.302 UTC, `case_id` `mcp-mission-failed-structured`) | `01a164b3-9f60-7bc9-a5ee-93e69ec8d2bb` |
| Span llm 1 | `01a164b3-9f60-7113-90cb-4a4d77a6fe39` |
| Span llm 2 | `01a164b3-bc67-7c76-bd77-75eba54aa577` |
| Body de trazas | `103d4f693ff433edb3ece5c2b9086728953f17ac1de6d2df83b1ae561f555194` |
| Body de spans | `8c1ab73a53a17c39ae4d73195cafd29fb4049d1c1013c52a1c80e81ff98f9685` |

- La herramienta va como un `tfg_point_event`, no como span.
- La evaluación de la respuesta y la comprobación de resultado **no** van a Opik.
- **El envío requiere una autorización aparte.**

## Límites

- Un turno no mide fiabilidad, ni la tasa de deducciones indebidas, ni sirve para comparar modelos.
- `status=ok` no se usa como prueba. La coincidencia del resultado cubre 26 punteros, no todo el
  resultado.
- Los registros son históricos: la disponibilidad actual no se consultó.

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README.
- `run.json` y `result-expectation.json` contienen el plan público (prompt, `run_id`, respuesta y
  campos esperados). Ninguno contiene rutas privadas.
- Los archivos de captura, `capture_summary.json` y `opik_dry_run.json` no contienen el `run_id`,
  valores del resultado ni la respuesta del modelo.
