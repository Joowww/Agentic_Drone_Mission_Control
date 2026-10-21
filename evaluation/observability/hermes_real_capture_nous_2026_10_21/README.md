# Captura real del plugin con Hermes (nous / laguna) — 21/10/2026

**Primera captura real** del plugin `tfg-observability-capture` 0.3.0: una inferencia de Hermes con
el perfil habitual `default` y su autenticación normal. Es metadata-only. Esta carpeta contiene la
captura y su dry-run.

> **Actualización (21/10/2026):** después se envió una vez a Opik (HTTP 204 + 204) y Joel confirmó
> visualmente la traza y el span. Ver
> [opik_hermes_real_send_2026_10_21](../opik_hermes_real_send_2026_10_21/README.md). Los archivos y
> el `SHA256SUMS` de esta carpeta no han cambiado; sólo este README.

## Ejecución (una sola, autorizada por Joel)

- **Lanzamiento:** la lanzó Joel en su terminal con `real_capture_once.sh`; la ejecución fuera del
  sandbox de Claude fue denegada y no se intentó por otra vía. Ventana: 2026-10-21T19:49:01Z →
  19:49:09Z (`run.json`), rc=0, sin timeout y sin reintento.
- **Comando:** el mismo que la evidencia nativa de Codex
  ([a8fe21d9…](../../hermes_native_usage_2026_10_21/a8fe21d9-55a7-4a27-be3b-bf89638dae7c/README.md)):
  `hermes -z "Responde únicamente con la palabra OK." --toolsets catalog --usage-file <privado>`,
  con `HERMES_DISABLE_LAZY_INSTALLS=1`. Herramientas y MCP quedaron desactivados con la misma
  selección `catalog` que comprobó Codex.
- **Modelo:** `poolside/laguna-s-2.1:free`, proveedor `nous`, sin sustituciones.
- **Variables de captura:** `TFG_OBSERVABILITY_CAPTURE=1`, un directorio privado fuera del repo,
  `run_id=real-hermes-nous-20261021` y `case_id=oneshot-ok`.
- **Activación temporal del plugin.** Hermes no ofrece una opción temporal: el único interruptor es
  `plugins.enabled` en `config.yaml`.
  - Antes: copia privada del config (sha256 `c99d1a88cb3cf578973d50e84b12d605b7b2ec28225ff55a034282d6fe08f4fb`)
    y comprobación de que no había plugins de usuario ni otro Hermes en marcha.
  - Durante: copia del plugin en `~/.hermes/plugins/tfg-observability-capture/` y una única edición
    del YAML que añadía `plugins.enabled: [tfg-observability-capture]`, validada como la única
    diferencia.
  - Al salir (`trap EXIT`): el config **se restauró byte a byte** (el hash coincide) y la copia del
    plugin se retiró. Ambas cosas se comprobaron después.
  - La copia cargada es idéntica a `observability/hermes_capture/` del repo (4 archivos, en
    `plugin_copy.sha256`, en el directorio privado).
- **Respuesta:** stdout fue exactamente `OK` y stderr estuvo vacío. **No se conserva** el texto de
  la respuesta ni el prompt.

## Hechos de la captura

- **Carga y registro:** `capture/capture-provenance-…json` con `origin=hermes_plugin_context`,
  `context_type=hermes_cli.plugins.PluginContext` y `verified_hermes_commit=d923a5eb…`.
  `verify_capture_provenance` da `ok: true`. Es evidencia de cómo se creó el sink, no una
  certificación criptográfica.
- **Emisión de hooks:** **1** evento `llm_call` de `post_api_request`, válido contra el esquema
  `tfg.hermes.capture/3`. No hubo `api_request_error` ni `post_tool_call`, como corresponde a un
  turno sin herramientas.
- **Contenido:** el JSONL no contiene ni el prompt, ni `OK` como respuesta, ni URLs, rutas o
  secretos. Los ids de sesión, tarea, turno y petición están en hash.

## Comparación con el informe nativo (`native_usage_reviewed.json`)

| Campo (turno principal) | Captura (plugin) | Informe nativo | Coinciden |
| --- | --- | --- | --- |
| model / provider | `poolside/laguna-s-2.1:free` / `nous` | igual | sí |
| input_tokens | 538 (`nonzero_normalized`) | 538 | sí |
| output_tokens | 2 (`nonzero_normalized`) | 2 | sí |
| cache_read_tokens | 256 (`nonzero_normalized`) | 256 | sí |
| cache_write_tokens | 0 (`zero_unconfirmed`) | 0 | valor sí; ninguno prueba que el proveedor enviara 0 |
| reasoning_tokens | 0 (`zero_unconfirmed`) | 0 | igual que el anterior |
| total_tokens | 796 (`derived_nonzero`) | 796 | sí; ambos suman input + cache + output |
| api calls | `api_call_count` 1 | `api_calls` 1 | sí; **no** es un recuento de peticiones HTTP |
| finish | `finish_reason=stop` | `text_response(finish_reason=stop)` | sí |

**Sólo en la captura:**
- `api_duration_s` 2,665 s, con los epochs de Hermes de 19:49:05,960 a 19:49:08,625 UTC;
- `first_chunk_offset_s` 2,662, que sólo equivale a TTFT si no hubo reintento interno y no está
  verificado;
- `context_length` 65 536, `message_count` 2, `requested_tool_names: []` y `api_mode=chat_completions`;
- `prompt_tokens` 794, derivado.

**Sólo en el informe nativo:**
- **Generación auxiliar del título** (`title_generation`): 38 de entrada, 14 de salida, 224 de
  caché leída y `api_calls` 1. Su total nativo de 52 no suma la caché.
- Total agregado de 848 y `api_calls` 2.
- Coste **estimado** de 0,0 USD (`provider_models_api`), que no es un coste facturado.

**El título no está en la captura**, como se esperaba. Hermes emite `pre/post_auxiliary_call` para
las llamadas auxiliares, no `post_api_request` (test `tests/agent/test_auxiliary_hooks.py` del
commit instalado), y el plugin no registra esos hooks. **La captura cubre sólo el turno principal.**
No se infieren ni el número de peticiones HTTP, ni los reintentos internos, ni un coste.

La correlación entre captura e informe se basa en la ventana temporal y en que fue una única
ejecución, no en un identificador común. El `session_id` nativo no se conserva y la captura guarda
sólo su hash.

## Opik: dry-run preparado, NO ENVIADO

**Destino propuesto, separado de los datos sintéticos:** workspace `joowww`, proyecto
**`tfg-opik-hermes-real-20261021`**. No consta que exista; Joel debe crearlo o confirmarlo en la
interfaz antes de cualquier envío.

`opik_dry_run.json`, generado con `--provenance captured`, el entorno vacío y los sockets
bloqueados:

- **Procedencia:** `captured_hermes_metadata`, con base
  `declared_captured_with_hermes_sink_provenance_record`. Sin bloqueos por defecto: no hace falta
  ningún `--allow-*`.
- **Traza** `01a16002-9b28-75bc-abca-6942ca6d1c95`, «hermes_turn», de 19:49:05.960428Z a
  19:49:08.625207Z, con etiquetas `tfg-hermes-capture`, `schema:tfg.hermes.capture/3` y
  `captured-metadata`.
- **Span `llm`** `01a16002-9b28-7291-bce7-d68337bb58f2`, «llm_call:poolside/laguna-s-2.1:free», con
  el mismo intervalo.
  - Tokens sólo en `metadata.tfg_usage`, con su estado.
  - Sin `usage`, `model`, `provider`, coste ni `ttft` a primer nivel.
  - Sin input ni output.
- **Bodies:**
  - trazas: 1 elemento, 1021 bytes, sha256 `881bb615907fddec8e6e56b2bd98c600e297d4a5bcded5d9059e95f0ed9fea15`;
  - spans: 1 elemento, 2541 bytes, sha256 `a2b96e370d81fa1f7d92d29308aef0c362df2fbcd3bb6c0ebac83f5b3ca95fda`.

### Comando futuro — NO EJECUTADO

Requiere que el proyecto esté confirmado en la interfaz y una autorización aparte que nombre el
destino y los dos hashes. Es una sola ejecución y la lanza Joel en su terminal. El cuerpo de error,
si lo hay, va fuera del repo.

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control || exit 1
E=evaluation/observability/hermes_real_capture_nous_2026_10_21
R=evaluation/observability/opik_hermes_real_send_2026_10_21
(cd "$E" && sha256sum -c --quiet SHA256SUMS) || exit 1
.venv/bin/python -m observability.opik_export "$E/capture/hermes-events-2026-10-21.jsonl" \
  --project tfg-opik-hermes-real-20261021 --workspace joowww --provenance captured \
  | .venv/bin/python -I -c "import hashlib,json,sys; p=json.load(sys.stdin)['payload']; h=lambda k: [hashlib.sha256(json.dumps(b,ensure_ascii=False,separators=(',',':')).encode()).hexdigest() for b in p[k]]; ok=(h('traces_batches')==['881bb615907fddec8e6e56b2bd98c600e297d4a5bcded5d9059e95f0ed9fea15'] and h('spans_batches')==['a2b96e370d81fa1f7d92d29308aef0c362df2fbcd3bb6c0ebac83f5b3ca95fda']); print('body check:', 'OK' if ok else 'MISMATCH'); sys.exit(0 if ok else 1)" \
  || exit 1
mkdir "$R" || exit 1
mkdir -m 700 ~/opik-hermes-real-private-20261021 || exit 1
read -rs -p "OPIK_API_KEY (hidden): " OPIK_API_KEY; echo; export OPIK_API_KEY
.venv/bin/python -m observability.opik_export "$E/capture/hermes-events-2026-10-21.jsonl" \
  --project tfg-opik-hermes-real-20261021 --workspace joowww --provenance captured \
  --send --record "$R/send_record.jsonl" --timeout 30 \
  --error-body-file ~/opik-hermes-real-private-20261021/error-body.bin \
  > "$R/send_report.json" 2> "$R/send.stderr"; echo "$?" > "$R/send.rc"
unset OPIK_API_KEY
```

Se pega en una shell nueva o se guarda como script, porque usa `exit 1`. Sin reintentos. El
exportador envía primero las trazas y después los spans, y se detiene en el primer batch sin 2xx.

## Archivos

- `capture/`: el JSONL y el registro de procedencia, copiados byte a byte del directorio privado
  (hashes comprobados).
- `native_usage_reviewed.json` y `native_usage_review.json`: el informe nativo filtrado y su
  revisión. El original (sha256 `7a94ac23…e068`, con `session_id`) se queda en el directorio
  privado.
- `run.json`: tiempos, rc y timeout.
- `opik_dry_run.json`: el payload preparado; no se ha enviado.
- `SHA256SUMS`: hashes de todo lo anterior, salvo este README.

Fuera del repo, en el directorio privado `~/tfg-real-capture-20261021T194901Z/` (0700): copia del
config, informe nativo bruto, stdout y stderr, y hashes de la copia del plugin. **No debe
añadirse a Git.** Joel puede borrarlo cuando ya no lo necesite.
