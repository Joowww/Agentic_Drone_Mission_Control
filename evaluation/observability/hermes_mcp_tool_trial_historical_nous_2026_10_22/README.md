# Ensayo real: consulta de una misión histórica con Hermes y MCP — 22/10/2026, 17:22 UTC

**Veredicto de la revisión: `TOOL_CALL_OBSERVED_AS_EXPECTED`**, con la comprobación del resultado
real `ALL_EXPECTED_FIELDS_MATCH` (23/23).

Una única invocación de Hermes, autorizada por Joel. Sin reintentos.

Antes de ejecutar, Joel aceptó de forma explícita que el resultado de la herramienta llegara al
proveedor tal como es. Ese resultado incluye:
- rutas absolutas con su usuario del sistema;
- el pid y el `boot_id` del worker;
- el texto del chequeo de simulación de entonces.

No incluye coordenadas, credenciales ni IPs.

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case historical-passed --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --trial-case historical-passed --private-dir ~/tfg-hermes-capture-private/20261022T172218Z --evidence-dir evaluation/observability/hermes_mcp_tool_trial_historical_nous_2026_10_22
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_tool_trial_historical_nous_2026_10_22 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Caso consultado: estado histórico, no estado actual

**Ejecución consultada:** `467f7ec6-b2a6-4b68-9d97-766d85732f8e`, preflight virtual del 18/10/2026.
- Fue el primer miembro de la secuencia `c6eeb645-…`, con `request_key` `sequence-…-1`, sin nombre
  personal.
- **Registro:** trabajo `FINISHED` (fase `analyze`) e informe `PASSED`, terminado a las
  2026-10-18T21:18:42 UTC.
- **Misión:** `simulation_navigation_3waypoint_001`, en `drone_01` → `v1`; validación
  `FEASIBLE`/`APPROVED`.
- **Ejecución:** el ejecutor dio `COMPLETED`, con 3/3 waypoints y regreso a casa; análisis `passed`.

**Archivos fijados por el preflight:** `job.json` `5a7bb17f…`, `report.json` `d967bc13…`,
`mission.json`/`input.json` `b9fb6ce5…`.
- Están en `missions/generated/`, que Git ignora. Son datos locales y no se versionan.
- No se modificaron: sus hashes se comprobaron otra vez después del turno.

**Estado actual frente a estado histórico:**
- El resultado es un registro de hace cuatro días. No dice nada del simulador actual, que no se
  arrancó ni se consultó.
- La propia herramienta lo declara, y forma parte de la comprobación: `readiness_now` y
  `preflights/0/readiness_now` = `UNKNOWN_NOT_CHECKED`, `worker_alive` = `false`,
  `consent` = `NOT_GRANTED_BY_THIS_QUERY` y `hardware_authorized` = `false`.

## Configuración y restauración

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free`, autenticación habitual |
| Aislamiento | `--toolsets tfg-mission-control`; temporalmente `include: [get_mission_state]`, `resources`/`prompts` desactivados y `tools.tool_search.enabled: "off"` |
| Plugin | 0.5.0 (registro de procedencia), con la comprobación opcional de resultado |
| Expectativa | `result-expectation.json`, sha256 `94c205cf…3524f`: 23 punteros JSON con valores escalares (uno de ellos: `/preflights/1` ausente) |
| Ejecución | 17:22:18.718–17:22:38.492 UTC (19,6 s de pared, arranque MCP incluido); rc=0, sin timeout, stderr vacío |
| Config | `c99d1a88…` → `82bfe207…` durante el turno → `c99d1a88…` restaurado, permisos 0600, sin restos de las ediciones |
| Plugin / procesos | `removed`; `~/.hermes/plugins` vacío; `mcp_server_processes_after: 0` y un `ps` posterior sin procesos `hermes` ni `tools.hermes_mcp_server` |
| Caché de esquemas MCP | Hermes la reescribió (`fef5a2b0…` → `b354400a…`); no se ha restaurado |

## Lo observado, por separado

| Pregunta | Evidencia | Resultado |
| --- | --- | --- |
| ¿Qué se ofreció? | 2 registros `tool_offer` | solo `mcp__tfg_mission_control__get_mission_state`, `tool_count` 1 en ambas peticiones |
| ¿Qué pidió el modelo? | `llm_call` 1: `tool_calls`, `requested_tool_names` | esa herramienta, por su nombre, una vez; la llamada 2 no pide nada (`stop`) |
| ¿Se ejecutó? | un `tool_call` | una ejecución, `status=ok`, 224 ms informados por Hermes |
| ¿Qué devolvió realmente? | `tool_result_check` (plugin, dentro de Hermes) | envoltorio `result_json_text`; **23 coincidencias, 0 discrepancias, 0 ausencias** |
| ¿Qué respondió el modelo? | stdout privado (solo su clasificación) | exactamente `PASSED` (`EQUALS_EXPECTED_STATUS`) |

- **Qué demuestra la comprobación del resultado:** que lo que la herramienta devolvió a Hermes
  coincidía en esos 23 campos con el registro local.
- **Qué no se guarda:** ningún valor observado. El registro solo lleva el puntero y el resultado de
  cada comparación.
- **Qué queda sin comprobar:** el resto del resultado de unos 6,9 KB.
- **`status=ok` y la respuesta `PASSED` no se usan como prueba;** se clasifican aparte.

### Llamadas al modelo y tokens

Hubo 2 `llm_call`, contadas y no presupuestas, y ningún `llm_error`. No equivalen a peticiones
HTTP, y `api_call_count` es un índice que no se suma.

| Llamada | `finish_reason` | entrada | salida | caché leída | caché escrita | razonamiento | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | tool_calls | 1742 | 83 | 672 | 0 `zero_unconfirmed` | 0 `zero_unconfirmed` | 2497 (derivado) | 4,269 |
| 2 | stop | 4884 | 3 | 672 | 0 `zero_unconfirmed` | 0 `zero_unconfirmed` | 5559 (derivado) | 2,557 |

**Comparación automática con el informe nativo** (`main_turn_sum_of_llm_calls`), veredicto
`all_compared_values_equal`:
- entrada 6626, salida 86, caché leída 1344, caché escrita 0, razonamiento 0 y total 8056;
- 2 llamadas = 2 `api_calls`.

El título auxiliar va aparte y solo es nativo: entrada 342, salida 19. Son no comparables
`api_call_count`, `prompt_tokens`, el coste y lo auxiliar.

**Observación, no prueba:** la entrada de la llamada 2 (4884) es mayor que en el ensayo `NOT_FOUND`
(1991), lo que es coherente con que el resultado entrara en el contexto. Los 224 ms coinciden por
casualidad con los del ensayo de las 16:50; es el valor que informa Hermes.

## Dry-run de Opik (NO enviado)

Destino `joowww` / `tfg-opik-hermes-real-20261021`, `--provenance captured`. Procedencia verificada;
sin retenidas, errores ni avisos.

| Recurso | Id / hash |
| --- | --- |
| Traza `hermes_turn` (17:22:29.570–17:22:37.617 UTC, `case_id` `mcp-get-mission-state-historical`) | `01a164a2-be42-7da8-896e-edb43c45ad0a` |
| Span llm 1 (pide la herramienta) | `01a164a2-be42-7abe-9fa3-e74c201dbcd1` |
| Span llm 2 | `01a164a2-d3b3-7748-9ae5-5f328b655a68` |
| Body de trazas | `48ec8d84cd713f2bbbbbe5f36a5edfcd0a30047db689163dfb20e112c45fcbe0` |
| Body de spans | `fbe81fb70a2f530d313e43741afc625e71a9a21f73d0a71958e8d1ae119a4e9a` |

- **Evento de herramienta:** va como un `tfg_point_event` (224 ms recibidos,
  `tfg_latency_measured: false`). No es un span.
- **Lo que no va a Opik:** la comprobación de resultado y la oferta de herramientas, porque el
  exportador lee solo los eventos. Tampoco el `run_id` ni valores del resultado (comprobado con
  búsqueda).
- **Hashes:** cargar `opik_dry_run.json` y serializar con `opik_export.body_bytes` reproduce los dos
  hashes.
- **Si se enviara,** el proyecto pasaría de 3 trazas y 4 spans LLM a 4 trazas y 6.
- **El envío requiere una autorización aparte.**

## Qué demuestra este ensayo y qué no

**Demuestra, en un turno:**
- Hermes, con una superficie de herramientas aislada y verificada, hizo que el modelo consultara
  por su nombre una misión histórica real mediante MCP.
- Una sola ejecución.
- La herramienta devolvió a Hermes un resultado coherente en 23 campos con el registro local,
  verificado dentro del proceso sin guardar el contenido.
- El modelo informó el `result_status` correcto.

**No demuestra:**
- **Fiabilidad:** una ejecución no es una tasa.
- **Comprensión del resto del resultado:** solo se comprobaron 23 campos; el modelo tuvo que
  responder un único valor.
- **Estado actual del simulador o de los vehículos:** no se consultó.
- **Autenticidad criptográfica de los registros.**
- **Ausencia de reintentos internos.**
- **Comportamiento con otros modelos o proveedores.**

## Pendiente

- Decidir si se envía este dry-run a Opik.
- Ensayos con preguntas que requieran combinar varios campos, o con ejecuciones `FAILED`/`BLOCKED`.
- Valorar si `get_mission_state` debería omitir rutas absolutas y datos del worker en la vista
  `summary` antes de usarla con proveedores externos. Es un cambio de la herramienta del proyecto,
  fuera de este ensayo.

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README.
- `result-expectation.json` y `run.json` contienen el `run_id` consultado y la expectativa pública.
  `run.json` contiene además el prompt fijo. No contienen rutas privadas.
- Los archivos de captura, `capture_summary.json` y `opik_dry_run.json` no contienen el `run_id`,
  valores del resultado, la respuesta ni argumentos de herramientas.
- Ningún archivo contiene credenciales.
