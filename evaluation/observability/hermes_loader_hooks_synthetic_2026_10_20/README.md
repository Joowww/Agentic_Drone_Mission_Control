# Integración real loader/hooks con fixtures SINTÉTICOS (20/10/2026)

**Resultado: PASS de integración del loader y los hooks de Hermes. Sin llamadas a ningún
modelo.** No demuestra inferencia, tokens reales de un proveedor ni latencias reales. Todos
los valores de los eventos son sintéticos (`run_id=SYNTHETIC-loader-hooks-20261020`,
`case_id=SYNTHETIC-fixtures`). Se guarda aparte de
[la prueba bloqueada antes de inferencia](../hermes_capture_blocked_2026_10_20/) y de cualquier
captura futura de proveedor. Contexto y límites en
[docs/hermes-observability-capture.md](../../../docs/hermes-observability-capture.md).

## Qué es real y qué es sintético

| Real (Hermes `d923a5eb48` instalado) | Sintético |
| --- | --- |
| Intérprete y bootstrap de Hermes (`import hermes_bootstrap`, como su lanzador), con `HERMES_DISABLE_LAZY_INSTALLS=1` | Valores de los fixtures (modelo, uso, tiempos, ids, contenido centinela, clave falsa `sk-ant-SYNTHETIC…`) |
| `hermes_cli.plugins.discover_plugins(force=True)`: descubrimiento, gate `plugins.enabled`, carga del paquete y `register(ctx)` con `PluginContext` | `SyntheticAgentStub`: objeto mínimo con los atributos que leen los emisores (sin `AIAgent`, sin cliente LLM) |
| Emisores `agent.turn_response_intake._fire_post_api_request_hook`, `ApiRequestHooksMixin._invoke_api_request_error_hook`, `model_tools._emit_post_tool_call_hook` | Objetos `response`/`usage`/`tool_calls` con `SimpleNamespace` |
| Dispatch `hermes_cli.lifecycle.invoke_hook` y `ainvoke_hook` | — |

`ainvoke_hook` **no forma parte del dispatch de estos tres hooks** en Hermes, que sólo los
despacha por la vía síncrona; se ejercitó como comprobación adicional.

## Resultados

- **Carga:** módulo `hermes_plugins.tfg_observability_capture` desde
  `~/.hermes/profiles/tfg-capture-test/plugins/tfg-observability-capture/`, `source=user`,
  `enabled=true`, sin error.
- **Registro:** `hooks_registered = [post_api_request, api_request_error, post_tool_call]`,
  igual que `provides_hooks`. `has_hook` es verdadero para los tres y falso para `pre_tool_call` y `pre_api_request`.
- **Dispatch:** 6 eventos (2 `llm_call`, 1 `llm_error`, 3 `tool_call`). `invoke_hook` y
  `ainvoke_hook` devuelven `[]`, así que no se devuelve nada que altere el flujo. `failures=0`.
- **JSONL:** 1 archivo con permisos 0600, válido contra `event.schema.json` (`tfg.hermes.capture/3`).
- **Exclusión:** ningún centinela de contenido, ruta, coordenada, id en claro, `base_url`
  ni clave falsa en el JSONL (`evidence/validation_report.txt`).
- **Normalización real de Hermes:** `prompt_tokens=1200` sintético en forma Chat llega como
  `input_tokens` 1200 `nonzero_normalized`, con las sumas `derived_nonzero`. `completion_tokens=0`
  llega como `output_tokens` 0 `zero_unconfirmed`, y la respuesta sin `usage` llega como `usage=null`,
  `usage_source=absent`.
- **Duraciones de herramienta:** 742 → `hermes_reported_ms`; 0 bloqueada → `zero_default_or_below_1ms`;
  30000 con timeout → `timeout_configured_not_measured`.
- **`llm_error.api_duration_s` ≈ 266 359 s:** artefacto del fixture, no del capturador. El emisor
  real calcula `time.time() − api_start_time` y el inicio sintético era una fecha fija pasada.
- **Red:** el bloqueo de sockets no-loopback no interceptó ningún intento (`network_guard.json`).
- **Estado:** plugin desactivado al terminar (config del perfil restaurada byte a byte); perfil
  habitual sin cambios (`stat`). Sin `.pyc` nuevos (`-B`). Hermes actualizó el directorio
  `.leases` de su entorno (alquiler de generación de cualquier arranque) y
  `cache/scratch/.last_prune` del perfil temporal.

## Archivos

`scripts/` (`run.sh`, `harness.py`) reproduce la prueba; `evidence/` y `capture/` son copias
exactas del directorio de trabajo `/tmp/tfg-loader-hooks-20261020T161004Z/`, verificadas
contra `source_tmp.sha256`. `manifest.json` lista SHA-256 y tamaño de todo salvo él mismo.
Revisión previa: sin credenciales reales; la única clave es la falsa y sintética del arnés.
