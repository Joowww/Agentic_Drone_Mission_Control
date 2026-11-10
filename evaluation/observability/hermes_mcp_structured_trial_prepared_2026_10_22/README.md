# Próximo ensayo de interpretación de varios campos — PREPARADO, NO EJECUTADO (22/10/2026)

No se ha ejecutado Hermes, el servidor MCP por stdio ni ningún proveedor. Ejecutarlo requiere
autorización. Esta carpeta fija **antes** del ensayo:
- qué recibirá el modelo;
- qué debe responder;
- cómo se evaluará.

## Caso: `failed-structured`

Ejecución real `d4519cab-ebd1-4359-b547-44be38294a6a` (17/10/2026), con informe `FAILED` en la etapa
`analyze`. Categoría: **fallo de misión** (WP3 no se alcanzó en 180 s).
- El `report.json` local (`f265cf77…`) es idéntico byte a byte a la copia versionada
  `simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/failed_wp3_report.json`.
- `mission.json` es `2366d5a2…`.
- El preflight bloquea si cambian esos archivos o si dejan de registrar `FAILED`.
- **No es el estado actual:** el simulador no se consulta.

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured --execute   # solo con autorización
```

El preflight offline del 22/10 dio `ok: true`.

## Lo que recibirá el modelo

[tool_result_external_view.json](tool_result_external_view.json) contiene el resultado que devuelve
la función real del proyecto con `view="external"`.
- Lo generó la función en local, en solo lectura; el hash del informe se comprobó antes y después.
- El servidor MCP lo serializará como JSON con otro formato de espacios, pero con el mismo contenido.
- Ocupa unos 2,4 KB, frente a ~15,8 KB de la vista `summary` de esta ejecución.
- No contiene rutas, el usuario del sistema, pid, `boot_id`, `request_key`, motivos, logs,
  textos de error ni coordenadas.

Datos de este caso que obligan a no deducir:
- `return_to_home: null` y `waypoints_completed: null`: no constan.
- `landing_evidence: []`: hay eventos registrados, pero ningún `LANDED` de la misión.
- `recovery_landing_completed: true`: hubo un aterrizaje de recuperación, registrado aparte.
- `analysis_checks.return_home_reached` y `analysis_checks.landed_and_disarmed` valen `false`. Son
  criterios de aceptación no cumplidos, no prueban que el vehículo no volviera o no aterrizara, y
  **no** deben convertirse en `return_to_home: false`.
- `readiness_now: UNKNOWN_NOT_CHECKED`: la disponibilidad actual es desconocida.

## Respuesta esperada (desde el informe, no desde la herramienta)

[expected_answer.json](expected_answer.json). La calcula
`observability.mission_query_cases.expected_answer_from_report` a partir del informe bruto. Un test
la recalcula desde la copia versionada en Git y otro comprueba que la vista externa es coherente con
ella en los cinco casos reales.

| Clave | Esperado | Por qué |
| --- | --- | --- |
| `run_id` | `d4519cab-…` | consultado |
| `historical_status` | `FAILED` | `report.status` |
| `mission_id` / `vehicle_id` / `simulated_vehicle` | `prueba_hermes_001` / `drone_01` / `v1` | `mission_identity` |
| `planned_waypoint_ids` | `["WP1","WP2","WP3"]` | `analysis.expected_waypoint_ids` |
| `reached_waypoint_ids` | `["WP1","WP2"]` | eventos `WAYPOINT_REACHED` |
| `return_to_home` | `UNKNOWN` | no consta (`null`) |
| `mission_landed_event_recorded` | `false` | hay eventos y ninguno es `LANDED` |
| `recovery_landing_completed` | `true` | `recovery.landing_completed` |
| `current_availability` | `UNKNOWN` (se acepta también `UNKNOWN_NOT_CHECKED`) | no se consulta |

El prompt fijo está en [prompt.txt](prompt.txt): una sola llamada con `run_id` y `view="external"` y
una respuesta que sea únicamente un objeto JSON con esas claves.

## Cómo se evaluará

1. **Herramientas ofrecidas:** solo `mcp__tfg_mission_control__get_mission_state`, sin Tool Search,
   en cada petición.
2. **Lo que pide el modelo:** esa herramienta, una vez.
3. **Ejecución:** un único `tool_call`.
4. **Consulta realmente ejecutada:** el plugin 0.6.0 compara en memoria los argumentos de la llamada
   ejecutada con `run_id` y `view="external"`, y registra solo `match`, `mismatch` o `absent`. Si no
   coinciden o no se pueden comprobar, el veredicto es
   `EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED`.
5. **Resultado real:** [result-expectation.json](result-expectation.json) (`ecb64f14…`) lista 26
   punteros sobre la vista externa.
   - Distingue `null` esperado de puntero ausente.
   - Incluye `landing_evidence_count: 0`, que distingue `[]` de `null`.
   - Si algún puntero no coincide: `TOOL_RESULT_CONTRADICTS_EXPECTATION`.
6. **Respuesta estructurada:** `evaluate_answer` analiza la respuesta como JSON (se admite un único
   bloque ```json) y clasifica cada clave por separado:

   | Resultado | Significado |
   | --- | --- |
   | `match` | coincide con lo esperado |
   | `mismatch` | otro valor del mismo tipo |
   | `wrong_type` | tipo distinto (por ejemplo, `"false"` en lugar de `false`) |
   | `missing` | falta la clave |
   | `invented_value` | da un valor cuando lo esperado es `UNKNOWN` |
   | `unknown_but_recorded` | responde `UNKNOWN` cuando el dato consta |

   - Las claves sobrantes hacen la respuesta incorrecta.
   - Solo se guardan las clasificaciones, nunca la respuesta.

**Veredicto positivo:** `TOOL_CALL_OBSERVED_AS_EXPECTED` solo si las seis comprobaciones se
cumplen, incluida `STRUCTURED_ALL_FIELDS_CORRECT`.

## Conjunto de casos (`observability/mission_query_cases.py`)

| Caso | Ejecución | Categoría | Estado |
| --- | --- | --- | --- |
| `passed-467f7ec6` | 18/10, `PASSED` | misión superada | consultado por Hermes el 22/10 (vista `summary`) |
| `failed-d4519cab` | 17/10, `FAILED` en `analyze` | **fallo de misión** | este ensayo preparado |
| `blocked-validate-0844c190` | 17/10, `BLOCKED` en `validate` | **bloqueo de admisión** (reserva de batería, no se ejecutó) | catalogado |
| `blocked-readiness-d7717942` | 17/10, `BLOCKED` en `check_readiness` | **infraestructura no lista** (no se ejecutó) | catalogado |
| `error-execute-1b69dfc7` | 18/10, `ERROR` en `execute` | **error de infraestructura o del ejecutor** (timeout de ROS 2, resultado del vuelo desconocido) | catalogado |
| `not-found` | — | inexistente | consultado por Hermes el 22/10 |

- No falta ninguna categoría.
- Sobre la etiqueta de `1b69dfc7`: el registro no permite separar con certeza un fallo de
  infraestructura de uno del ejecutor, y la etiqueta lo refleja.
- Son seis casos: **no son una medida de fiabilidad.**

## Archivos

- `SHA256SUMS` cubre los cuatro archivos de datos y este README.
- Ningún archivo contiene credenciales, rutas privadas ni datos personales.
