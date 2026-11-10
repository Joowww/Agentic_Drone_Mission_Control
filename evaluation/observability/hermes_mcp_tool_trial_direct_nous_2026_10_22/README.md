# Ensayo real de herramienta MCP con aislamiento directo — 22/10/2026, 16:50 UTC

**Veredicto de la revisión: `TOOL_CALL_OBSERVED_AS_EXPECTED`.**

Cada petición al modelo ofreció exclusivamente `mcp__tfg_mission_control__get_mission_state`. El
modelo la pidió por su nombre, se observó una sola ejecución y la respuesta final fue `NOT_FOUND`.

Es un ensayo distinto del de las 16:40 UTC
([hermes_mcp_tool_trial_nous_2026_10_22](../hermes_mcp_tool_trial_nous_2026_10_22/README.md),
veredicto `ISOLATION_NOT_CONFIRMED`):
- aquél pasó por el puente Tool Search;
- conserva sus `requested_tool_names: [null]` del plugin 0.4.0;
- no se ha modificado.

Una única invocación de Hermes, autorizada por Joel. Sin reintentos:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --private-dir ~/tfg-hermes-capture-private/20261022T165014Z --evidence-dir evaluation/observability/hermes_mcp_tool_trial_direct_nous_2026_10_22
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_tool_trial_direct_nous_2026_10_22 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Configuración del turno

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free`, autenticación habitual |
| Hermes | `d923a5eb48`; `TRIAL_SOURCES` verificadas, ahora también `tools/tool_search.py`, `hermes_cli/config.py` y `hermes_cli/config_defaults.py` |
| Ediciones temporales del config | Tres, cada una validada al parsear: `mcp_servers.tfg-mission-control.tools` (`include: [get_mission_state]`, `resources: false`, `prompts: false`), `tools.tool_search.enabled: "off"` (cadena entre comillas) y `plugins.enabled` |
| Config | `c99d1a88…` → `82bfe207…` durante el turno → `c99d1a88…` |
| Selección | `--toolsets tfg-mission-control` |
| Prompt | fijo, sha256 `f0c45b0a…6015b`; `run_id` neutro `00000000-0000-4000-8000-000000000000`, revalidado sin uso por el preflight |
| Plugin | 0.4.1 (en el registro de procedencia), con la corrección de `requested_tool_names` |
| Ejecución | 16:50:14.985–16:50:32.077 UTC (17,1 s de pared del proceso, arranque MCP incluido); rc=0, sin timeout, stderr vacío |

## Restauración y efectos

Comprobado por la utilidad y de nuevo por separado.

| Comprobación | Resultado |
| --- | --- |
| `config.yaml` | `restored`: `c99d1a88…`, permisos 0600, sin restos de las tres ediciones |
| Plugin | `removed`; `~/.hermes/plugins` vacío |
| Procesos residuales | `mcp_server_processes_after: 0`; un `ps` posterior no muestra procesos `hermes` ni `tools.hermes_mcp_server` |
| Caché de esquemas MCP | Cambió de `b642aa39…` a `fef5a2b0…`, es decir, Hermes la reescribió. No se ha restaurado; no se lee con `lazy` desactivado |
| Material bruto | `~/tfg-hermes-capture-private/20261022T165014Z/` (0700, fuera de Git) |

## Lo observado, por separado

### Herramientas ofrecidas (`hermes-tool-offers-*.jsonl`)

Hubo 2 registros, uno por petición. Ambos tienen `offered_tool_names =
[mcp__tfg_mission_control__get_mission_state]`, `tool_count` 1 y origen `request_body_tools`. No
aparece ningún puente de Tool Search, herramienta integrada ni otro servidor.

### Petición del modelo

La llamada 1 tiene `finish_reason=tool_calls`, `assistant_tool_call_count` 1 y
`requested_tool_names = [mcp__tfg_mission_control__get_mission_state]`. La llamada 2 tiene `stop`
y ninguna herramienta.

### Ejecución observada

Hubo un único `tool_call`: `mcp__tfg_mission_control__get_mission_state`, `status=ok`, sin
`error_type`, con 224 ms informados por Hermes (`hermes_reported_ms`).
- `status=ok` solo significa que Hermes no detectó error.
- **El resultado de la herramienta no se captura,** así que este evento no prueba su contenido.

### Respuesta final

`EQUALS_EXPECTED_STATUS`: exactamente `NOT_FOUND` (stdout privado de 10 bytes; solo se conservan su
hash y su clasificación). Es coherente con el resultado esperado, pero **no lo demuestra**.

### Llamadas al modelo y tokens

Hubo 2 `llm_call` y ningún `llm_error`. El número se observó, no se presupuso.
- Las llamadas **no** son peticiones HTTP. `api_call_count` (1, 2) es un índice acumulado y no se
  suma.
- No hay evidencia de reintentos internos en ningún sentido.

| Llamada | `finish_reason` | entrada | salida | caché leída | caché escrita | razonamiento | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | tool_calls | 1899 | 85 | 512 | 0 `zero_unconfirmed` | 0 `zero_unconfirmed` | 2496 (derivado) | 4,408 |
| 2 | stop | 1991 | 3 | 672 | 0 `zero_unconfirmed` | 0 `zero_unconfirmed` | 2666 (derivado) | 2,057 |

**Comparación automática con el informe nativo** (`capture_summary.json` →
`correlation_with_native`), con alcance `main_turn_sum_of_llm_calls`:
- Suma solo los contadores de cada llamada, que son incrementales, frente a los totales del turno
  principal del informe nativo.
- Resultado: entrada 3890 = 3890, salida 88 = 88, caché leída 1184 = 1184, caché escrita 0 = 0,
  razonamiento 0 = 0 y total 5162 = 5162.
- Número de llamadas: 2 `llm_call` = 2 `api_calls`.
- Veredicto: `all_compared_values_equal`.
- Marcado como **no comparable:** `api_call_count`, `prompt_tokens` (no está en el informe nativo
  filtrado), el coste estimado y la tarea auxiliar.
- La generación auxiliar del título va aparte, solo nativa: entrada 115, salida 12, caché leída
  224. El plugin no la captura.

`first_chunk_offset_s` (3,154 y 1,847 s) no es un TTFT verificado.

## Dry-run de Opik (NO enviado)

Destino `joowww` / `tfg-opik-hermes-real-20261021`, `--provenance captured`. Procedencia verificada;
sin retenidas, errores ni avisos.

| Recurso | Id / hash |
| --- | --- |
| Traza `hermes_turn` (16:50:24.486–16:50:31.307 UTC) | `01a16485-5e65-7966-a4b8-3df00e69d9b1` |
| Span llm 1 (`tfg_requested_tool_names` con la herramienta) | `01a16485-5e65-722e-a2d3-acf60c4be263` |
| Span llm 2 | `01a16485-7101-7baa-bc0b-17ffb4e48f7a` |
| Body de trazas | `41110bb79d8a613572921f54ccd9e94cc375605ceb3311bff3d7b34d234b8b10` |
| Body de spans | `f6e989fc681416cca78c54ed3dd60b4938063a7253c7dbb8d9a78d56324469c6` |

- **`tool_call`:** va como un `tfg_point_event` en la metadata de la traza, según el contrato actual.
  Conserva 224 ms recibidos y `tfg_latency_measured: false`; no es un span ni un intervalo
  inventado.
- **Hashes:** cargar `opik_dry_run.json` y serializar con `opik_export.body_bytes` reproduce los dos
  hashes (comprobado).
- **Si se enviara** solo este ensayo, el proyecto pasaría de 2 trazas y 2 spans LLM a 3 y 4.
- **El envío y cualquier cambio en el dashboard requieren otra autorización.**

## Límites

- Un ensayo no mide fiabilidad, tasa de uso de herramientas ni rendimiento. No es comparable con
  los turnos "OK" ni con el ensayo de las 16:40, que tiene otra superficie de herramientas.
- Que se ofrecieran solo esos nombres prueba qué contenía el body de la petición, no lo que el
  proveedor hizo con él.
- Los tokens son los normalizados de Hermes, no el uso bruto del proveedor. No hay coste facturado
  conocido.

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README. Se regeneró al añadir
  `opik_dry_run.json`.
- `run.json` contiene, en `mcp_tool_trial`, el plan público del ensayo: prompt fijo, `run_id`
  neutro y filtros. No contiene rutas privadas.
- Los archivos de captura, `capture_summary.json` y `opik_dry_run.json` no contienen el prompt, el
  `run_id`, la respuesta ni argumentos o resultados de herramientas.
- Ningún archivo contiene credenciales.
