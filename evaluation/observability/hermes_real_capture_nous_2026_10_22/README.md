# Verificación real de la utilidad `hermes_capture_run` (22/10/2026)

**Propósito:** comprobar con una ejecución real que la utilidad versionada
[observability/hermes_capture_run.py](../../../observability/hermes_capture_run.py) reproduce la
cadena captura → revisión → dry-run sin scripts de un solo uso. **No es una comparación de
rendimiento ni entre modelos**, y no se compara con la captura del 21/10. **No se ha enviado a
Opik.**

## Ejecución (una sola, autorizada; lanzada por Joel en su terminal)

```bash
.venv/bin/python -m observability.hermes_capture_run capture --execute --run-id real-hermes-20261022 --case-id oneshot-ok --timeout 120
```

- **Antes:** la comprobación previa offline pasó 12 de 12 controles, incluidas las fuentes de Hermes
  que fijan cero herramientas/MCP con `--toolsets catalog` (commit `d923a5eb`).
- **Resultado (`run.json`):**
  - rc=0, sin timeout, `hermes_invocations: 1` y `automatic_retry: false`;
  - de 08:24:22.573 a 08:24:32.404 UTC, unos 9,96 s de pared;
  - perfil `default`, `poolside/laguna-s-2.1:free` vía `nous`, con la autenticación habitual (la
    utilidad no lee credenciales).
- **Restauración:** `restore = {config: restored, plugin: removed, ok: true}`. Claude lo comprobó
  después:
  - el config tiene sha256 `c99d1a88…08f4fb` (el original) y permisos 0600;
  - `~/.hermes/plugins/` está vacío y la copia del plugin no existe;
  - la copia privada del config es idéntica al original;
  - no hay ningún otro proceso Hermes en marcha.
- **Material bruto:** queda en `~/tfg-hermes-capture-private/20261022T082422Z/` (0700, **fuera de
  Git**): copia del config, informe nativo con `session_id`, stdout (`OK`), stderr (vacío) y la
  captura. Joel puede borrarlo cuando quiera.

## Revisión (`review`) y validación

`review --private-dir … --evidence-dir evaluation/observability/hermes_real_capture_nous_2026_10_22`
devolvió `events: 1`, `provenance_ok: true` y `correlation_verdict: all_compared_values_equal`.
Comprobado además por separado:

- **Esquema:** 1 evento `llm_call` válido (`tfg.hermes.capture/3`), sin errores.
- **Procedencia:** registro `origin=hermes_plugin_context`,
  `context_type=hermes_cli.plugins.PluginContext`, plugin 0.3.0 y commit `d923a5eb…`;
  `verify_capture_provenance` da `ok: true`.
- **Copia de la captura:** idéntica byte a byte a la privada. `SHA256SUMS` verifica e incluye
  `opik_dry_run.json`.
- **Privacidad:** la evidencia no contiene `session_id`, salvo como nombre de campo omitido en
  `native_usage_review.json`; tampoco la ruta privada, el prompt ni cadenas con aspecto de secreto.
  La captura no contiene la respuesta.

## Turno principal: captura frente a informe nativo

| Contador | Plugin (estado) | Nativo | Igual |
| --- | --- | --- | --- |
| input_tokens | 570 (`nonzero_normalized`) | 570 | sí |
| output_tokens | 2 (`nonzero_normalized`) | 2 | sí |
| cache_read_tokens | 224 (`nonzero_normalized`) | 224 | sí |
| cache_write_tokens | 0 (`zero_unconfirmed`) | 0 | valor sí; no prueba que el proveedor enviara 0 |
| reasoning_tokens | 0 (`zero_unconfirmed`) | 0 | igual que el anterior |
| total_tokens | 796 (`derived_nonzero`) | 796 | sí; ambos son sumas |

- **Llamadas:** `api_call_count` 1 en el plugin y `api_calls` 1 en el turno principal nativo. **No**
  es un recuento de peticiones HTTP.
- **Sólo en la captura:** el intervalo medido por Hermes, 3,067 s de 08:24:29.115 a 08:24:32.182 UTC,
  y `first_chunk_offset_s` de 2,724 s. Éste último **no es un TTFT verificado**: sólo lo sería si no
  hubo reintentos.
- **Sólo en el informe nativo** (`auxiliary_native_only`, nunca mezclado con el turno principal):
  - la generación auxiliar del título, `title_generation`: 38 de entrada, 6 de salida, 224 de
    caché leída y 1 llamada;
  - el total agregado de 840 y `api_calls` 2;
  - un coste **estimado** de 0,0 USD (`cost_status: estimated`). **El coste facturado es
    desconocido.**
- **El plugin no captura el título**, porque Hermes usa `pre/post_auxiliary_call` para las llamadas
  auxiliares.

## Dry-run de Opik (NO enviado)

`opik-dry-run`, ejecutado con el entorno vacío y los sockets bloqueados, para el destino
`joowww` / `tfg-opik-hermes-real-20261021` (el proyecto real; los sintéticos están en otros):

- procedencia `captured_hermes_metadata`, sin bloqueos y sin necesidad de `--allow-*`;
- traza `01a162b6-2ebb-7ed9-9cb4-921cef200602`, «hermes_turn», con las etiquetas
  `tfg-hermes-capture`, `schema:tfg.hermes.capture/3` y `captured-metadata`;
- span `llm` `01a162b6-2ebb-7922-baa1-6ffc9bea022d`, «llm_call:poolside/laguna-s-2.1:free», con el
  mismo intervalo y sin `usage`, `model`, `provider` ni coste a primer nivel;
- bodies: trazas `ab2dd88d0d18f6cc478908e17a1e87346b738aedcf430ac374e38b16b8d5b017` y spans
  `455477f96ae4f2cf565ce0977b505668e992895e244ee2e1264eb87fb5685b47`.

**Envío:** es una acción aparte que requiere su propia autorización, con un `--record` nuevo y un
`--error-body-file` fuera del repo. El comando está en `opik_dry_run.json`. Si se envía, el
dashboard «TFG — Hermes» pasaría a tener n=2 en ese proyecto.

## Archivos

`capture/` (JSONL y registro de procedencia), `native_usage_reviewed.json`,
`native_usage_review.json`, `run.json` (sin la ruta privada), `capture_summary.json`,
`opik_dry_run.json` y `SHA256SUMS`. `SHA256SUMS` cubre todo salvo este README.
