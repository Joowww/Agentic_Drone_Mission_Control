# Ensayo real de una herramienta MCP con Hermes — 22/10/2026

**Veredicto de la revisión: `ISOLATION_NOT_CONFIRMED`.**
- La herramienta `get_mission_state` **sí se ejecutó** una vez, a través del puente Tool Search de
  Hermes.
- La respuesta final fue `NOT_FOUND`.
- Pero el aislamiento previsto (que el modelo viera solo esa herramienta) **no se cumplió tal como
  se definió**.
- Según los criterios fijados antes de ejecutar, esto no es un éxito.

Una única invocación de Hermes, autorizada por Joel. Sin reintentos. Comando:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --private-dir ~/tfg-hermes-capture-private/20261022T164008Z --evidence-dir evaluation/observability/hermes_mcp_tool_trial_nous_2026_10_22
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_tool_trial_nous_2026_10_22 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Ejecución y entorno (`run.json`)

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free`, autenticación habitual |
| Hermes | `d923a5eb48`; fuentes fijadas en `TRIAL_SOURCES` verificadas por el preflight |
| Selección | `--toolsets tfg-mission-control` y filtro temporal `include: [get_mission_state]`, `resources: false`, `prompts: false` |
| Prompt | fijo, sha256 `f0c45b0a…6015b`; `run_id` neutro `00000000-0000-4000-8000-000000000000`, comprobado sin uso antes del turno |
| Tiempo | 16:40:08.765–16:40:36.009 UTC (27,2 s de pared del proceso, arranque MCP incluido); rc=0, sin timeout, stderr vacío |
| Plugin | 0.4.0 (la versión instalada en el turno; hashes en `run.json`) |

## Restauración y efectos

Comprobado por la utilidad y de nuevo por separado tras el turno.

| Comprobación | Resultado |
| --- | --- |
| `config.yaml` | `restored`: sha256 `c99d1a88…` y permisos 0600, como antes; sin filtro `tools` en `mcp_servers` |
| Plugin | `removed`; `~/.hermes/plugins` vacío |
| Procesos residuales | `mcp_server_processes_after: 0`; un `ps` posterior no muestra procesos `hermes` ni `tools.hermes_mcp_server` |
| Caché de esquemas MCP | Cambió de `d2168860…` a `b642aa39…`, como estaba previsto (entrada de Hermes para la huella filtrada). No se ha restaurado; no se lee con `lazy` desactivado |
| Otros | Sesión guardada por Hermes como en cualquier turno; material bruto en `~/tfg-hermes-capture-private/20261022T164008Z/` (0700, fuera de Git) |

## Lo observado, por separado

Fuentes: `capture/hermes-tool-offers-2026-10-22.jsonl`, `capture/hermes-events-2026-10-22.jsonl` y
la evaluación en `capture_summary.json` → `mcp_tool_trial`.

### Herramientas ofrecidas

Las tres peticiones al modelo ofrecieron `[tool_search, tool_describe, tool_call]` (`tool_count` 3),
no `mcp__tfg_mission_control__get_mission_state`.

**Causa (fuentes de Hermes):** Tool Search está en `auto` por defecto y en esta versión se activa
siempre que haya alguna herramienta diferible (`tools/tool_search.py:should_activate`). Las
herramientas MCP siempre lo son. Por eso Hermes sustituyó la herramienta por los tres puentes. La
preparación suponía que con una sola herramienta no se activaría, y **era un supuesto erróneo**.

Ni herramientas integradas ni otros servidores se ofrecieron directamente. Según las fuentes, el
catálogo del puente se limita a los toolsets de la sesión, es decir, a la única herramienta
registrada. **Esto es una inferencia de las fuentes, no algo observado:** el resultado de
`tool_describe` no se captura.

### Petición del modelo

`assistant_tool_call_count` fue 1, 1 y 0 en las tres llamadas. Los nombres pedidos quedaron
como `[null]` por un **defecto del plugin 0.4.0**: Hermes entrega al hook su dataclass `ToolCall`
serializado con `name` en primer nivel, y el plugin solo leía `function.name`.

Ya está corregido para capturas futuras (plugin 0.4.1, con test de regresión y de contrato).
**Esta captura no se ha modificado.** Así que lo que pidió el modelo, nombre a nombre, **no consta**
en ella.

### Ejecución observada (`post_tool_call`)

| # | `tool_name` | `status` | duración informada por Hermes |
| --- | --- | --- | --- |
| 1 | `tool_describe` (lectura del catálogo del puente, en línea) | `ok` | 28 ms |
| 2 | `mcp__tfg_mission_control__get_mission_state` | `ok` | 17 ms |

- El puente `tool_call` despacha la herramienta real, y los hooks ven su nombre verdadero. El
  propio puente no genera un evento aparte.
- `status=ok` significa que Hermes no detectó error en el resultado. **El contenido que devolvió la
  herramienta no se captura** y no queda probado por este evento.

### Respuesta final

`EQUALS_EXPECTED_STATUS`: el texto fue exactamente `NOT_FOUND` (stdout privado de 10 bytes; solo se
conserva su hash y su clasificación). Que coincida con el `status` esperado es coherente con el
resultado de la herramienta, pero **no lo demuestra**.

### Llamadas al modelo

Hubo 3 `llm_call`, sin `llm_error`. El informe nativo da `api_calls: 3` en el turno principal, más
1 llamada auxiliar del título (entrada 115, salida 14, caché leída 224), que el plugin no captura.
Ni `api_calls` ni los `llm_call` equivalen a peticiones HTTP: no se infieren reintentos internos.

| Llamada | `finish_reason` | entrada | salida | caché leída | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | tool_calls | 2095 | 34 | 512 | 2641 | 6,588 |
| 2 | tool_calls | 2331 | 90 | 672 | 3093 | 5,272 |
| 3 | stop | 2588 | 3 | 672 | 3263 | 3,821 |
| Suma plugin | | 7014 | 127 | 1856 | 8997 | |
| Informe nativo (turno principal) | | 7014 | 127 | 1856 | 8997 | |

- Las sumas coinciden campo a campo. La comparación automática de la revisión
  (`not_compared_more_than_one_call_or_errors`) solo compara turnos de una llamada; esta
  comparación de sumas está hecha a mano.
- `cache_write_tokens` y `reasoning_tokens` valen 0 con estado `zero_unconfirmed`.
- `prompt_tokens` y `total_tokens` son derivados.

## Dry-run de Opik (no enviado)

Destino `joowww` / `tfg-opik-hermes-real-20261021`, con `--provenance captured`. Procedencia
verificada; sin trazas retenidas, errores ni avisos.

| Recurso | Id |
| --- | --- |
| Traza `hermes_turn` (16:40:19.435–16:40:35.379 UTC) | `01a1647c-22eb-74be-aeec-12dca778100a` |
| Span llm 1 | `01a1647c-22eb-7011-a260-5dbe8a00904e` |
| Span llm 2 | `01a1647c-3d45-7e20-a204-c4eac5f50317` |
| Span llm 3 | `01a1647c-5245-7600-b143-e806b5745bf2` |
| Body de trazas | sha256 `992fecd1ac0ac9fa187d7667c91cc748f5c503a00fd1ad3d68fb72e3e530409e` |
| Body de spans | sha256 `de46b3d60c2e4d97f573aa4d596e5184b93e8351ffd5d7a590562f7467c08f21` |

- **`tool_call`:** los dos eventos van como `tfg_point_events` en la metadata de la traza, según el
  contrato actual del exportador. No son spans, porque no tienen intervalo medido
  (`tfg_latency_measured: false`). Su duración es el valor informado por Hermes, sin convertirlo
  en intervalo.
- **Nombres pedidos:** los spans llevan `tfg_requested_tool_names: [null]` tal como se capturaron.
- **Hashes:** cargar `opik_dry_run.json` y serializar cada body con `opik_export.body_bytes`
  reproduce estos dos hashes (comprobado). El archivo ya se guarda con la serialización corregida.
- **Si se envía,** el proyecto pasaría de 2 trazas y 2 spans LLM a 3 trazas y 5 spans LLM. Este
  turno, con herramienta y tres llamadas, no es comparable en rendimiento con los turnos "OK".
- **El envío requiere una autorización aparte.**

## Siguiente paso propuesto (no implementado ni ejecutado)

Para un nuevo ensayo de aislamiento directo, Hermes ofrece una opción soportada: añadir de forma
temporal `tools.tool_search.enabled: off` (leída por `tools/tool_search.py:_config_from_loader`)
junto al filtro MCP. Eso requiere:
- ampliar la edición validada y las fuentes fijadas;
- tests;
- una nueva autorización de ejecución.

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README. La utilidad lo regeneró al añadir
  `opik_dry_run.json`, y los hashes de la captura no cambian.
- `run.json` no incluye la ruta privada.
- `run.json` sí incluye, dentro de `mcp_tool_trial`, el prompt fijo y el `run_id` neutro. Es el
  plan público del ensayo, el mismo texto que figura en el runbook.
- Los archivos de captura, `capture_summary.json` y `opik_dry_run.json` no contienen el prompt, el
  `run_id`, la respuesta ni argumentos o resultados de herramientas (comprobado con búsqueda).
- Ningún archivo contiene credenciales.
