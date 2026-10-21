# Captura local de observabilidad de Hermes (prototipo)

Fecha: 20/10/2026. **Prototipo. Carga, registro y dispatch reales demostrados con el loader
de Hermes y fixtures sintéticos**
([integración loader/hooks](#integración-real-loaderhooks-con-fixtures-sintéticos-20102026)).
**Inferencia y tokens reales de un proveedor no demostrados:** la única conversación quedó
[bloqueada antes de inferencia](#prueba-real-con-ollama-local-bloqueada-antes-de-inferencia-20102026).
Esquema de eventos: `tfg.hermes.capture/3`.

Plugin opcional que convierte tres hooks de observación de Hermes en eventos JSONL
locales con sólo metadatos: uso de tokens si el proveedor lo entrega, modelo/proveedor,
tiempos que Hermes mide y nombres de herramientas. Es la capa de captura común prevista
para comparar después LangSmith y Opik sobre los mismos registros; **el plugin no incluye
SDK de ninguna plataforma ni exporta datos**. La exportación es un paso aparte y explícito:
[exportador a LangSmith](langsmith-export.md), en dry-run por defecto y con envíos históricos
autorizados de fixtures sintéticos documentados por separado. Para Opik hay un
[exportador](opik-export.md) en dry-run por defecto, con envío explícito probado mediante
transporte falso y payload contrastado offline con el SDK; sin envío a Opik.

Código: [observability/hermes_capture/](../observability/hermes_capture/) ·
esquema: [event.schema.json](../observability/hermes_capture/event.schema.json) ·
tests: [test_hermes_observability_capture.py](../tests/test_hermes_observability_capture.py).

## Contrato de Hermes verificado (hermes-agent `d923a5eb48`)

Comprobado leyendo el código fuente y, en los tests, analizándolo con `ast` sin importarlo
ni ejecutarlo. `VERIFIED_HERMES_COMMIT` fija el commit revisado; si el instalado cambia,
el test de commit se marca *skip* con aviso y los tests estructurales siguen ejecutándose.

| Aspecto | Origen en Hermes | Qué se comprueba |
| --- | --- | --- |
| Descubrimiento | `hermes_cli/plugins_discovery.py` | Plugins de usuario en `get_hermes_home()/plugins/<dir>/`; **opt-in**: sólo cargan si su nombre está en `plugins.enabled` del `config.yaml` de ese home |
| Manifiesto | `hermes_cli/plugins_manifest.py:parse_manifest_file` | Usa `name` (o el directorio) y `provides_hooks`; nuestro `plugin.yaml` declara exactamente los 3 hooks |
| Carga | `hermes_cli/plugins_loader.py:_load_directory_module` / `_load_plugin_scoped` | Importa `__init__.py` como paquete (admite `from .capture import register`) y llama `register(ctx)` |
| Registro | `hermes_cli/plugins.py:PluginContext.register_hook(hook_name, callback)` | Nombres dentro de `VALID_HOOKS` |
| `post_api_request` | `agent/turn_response_intake.py:_fire_post_api_request_hook` | Están todos los kwargs que leemos; no hay `retry_count` |
| `api_request_error` | `agent/api_request_hooks.py:_invoke_api_request_error_hook` | Incluye `status_code`, `retry_count`, `max_retries`, `retryable`, `reason`, `error` |
| `post_tool_call` | `model_tools.py:_emit_post_tool_call_hook` | `tool_name`, `duration_ms` (por defecto 0), `status`, `error_type` e ids de `_CallIds` |
| Uso | `agent/api_request_hooks.py:_usage_summary_for_api_request_hook` + `agent/usage_pricing.py:CanonicalUsage`, `normalize_usage`, `_first_nonzero` | `None` si la respuesta no trae `usage`; si la trae, contadores con default 0, `_first_nonzero` que devuelve 0 tanto para un cero del proveedor como para un campo ausente, `raw_usage` eliminado antes del hook, y `prompt_tokens`/`total_tokens` como sumas calculadas |

Sólo se registran hooks de observación. No se usan `pre_*` ni `transform_*`: `pre_tool_call`
es un hook de política que, si tarda, falla cerrado y bloquea la herramienta. Los callbacks
devuelven siempre `None`, no lanzan excepciones y no escriben en stdout/stderr (stdout puede
ser el canal stdio de MCP).

### Qué no queda demostrado

- **Eventos de una inferencia real.** Carga, `register(ctx)` con `PluginContext` auténtico y
  dispatch real están demostrados sólo con fixtures sintéticos
  ([integración loader/hooks](#integración-real-loaderhooks-con-fixtures-sintéticos-20102026)).
  Siguen sin observar los kwargs que produce un turno real: tokens de un proveedor, tiempos
  medidos, `first_chunk_at` y `context_length`. El `FakeContext` de los tests unitarios
  sólo registra llamadas y no es una prueba de carga.
- Modo `plugins.isolation: host`, en el que los plugins no bundled corren en otro proceso
  y los kwargs viajan serializados.
- Ruta asíncrona `ainvoke_hook`, límites de timeout de hooks y su efecto en la latencia de la sesión.
- Qué emite en la práctica cada proveedor: qué contadores llegan, si hay `first_chunk_at`
  y si cada reintento dispara `api_request_error`.

### Intento de carga aislada abandonado (incidencia, 20/10/2026 ~09:39–09:40 UTC)

Se intentó una prueba de carga con el intérprete y el código de Hermes en un `HERMES_HOME`
temporal del scratchpad de la sesión, con la red bloqueada a nivel de socket dentro del script.
Al importar `hermes_cli` con ese home nuevo, Hermes ejecutó su preparación de dependencias
para un *data root* prestado («preparing dependencies for this data root»), creó un entorno
de unos 400 MB en ese home temporal y relanzó el proceso. Esa preparación ocurrió antes del
bloqueo de red. La caché `uv` temporal contiene metadatos `simple-v24/pypi`
(`packaging`, `setuptools`, `wheel`) y su marcador `.seeded` no indica una copia semilla local,
así que **es muy probable que se descargaran paquetes públicos de PyPI**. No se enviaron datos
del proyecto ni de conversaciones. No se ejecutaron modelos, MCP ni herramientas. En
`~/.hermes` no se detectaron archivos modificados en ese intervalo. El intento se abandonó y
no se ha repetido. Conclusión: un `HERMES_HOME` suelto no se puede aislar sin red con
garantías; por eso la verificación es el contrato estático anterior.

### Prueba real con Ollama local: bloqueada antes de inferencia (20/10/2026)

**Resultado: PRUEBA BLOQUEADA ANTES DE INFERENCIA.** Intento único, autorizado, cerrado sin
repetir la conversación, sin aumentar el contexto y sin reiniciar Ollama. Evidencia con
manifiesto SHA-256: [evaluation/observability/hermes_capture_blocked_2026_10_20/](../evaluation/observability/hermes_capture_blocked_2026_10_20/).

Preparación (hechos):

- Ollama 0.34.2 ya en marcha y `qwen3:4b` instalado; no se arrancaron servicios ni se
  descargaron modelos. Hermes admite el endpoint con el proveedor `custom` y clave
  `no-key-required` en loopback.
- Perfil `~/.hermes/profiles/tfg-capture-test` creado con
  `hermes profile create --no-skills --no-alias`, sin clonar, bajo `env -i` y
  `HERMES_DISABLE_LAZY_INSTALLS=1`. Un perfil bajo `~/.hermes` usa el estado de dependencias
  del root propietario: no hubo preparación de dependencias; el registro de arranque del
  perfil sólo muestra pasos `ok`/`skipped`. Sin `auth.json`; `.env` sin valores.
- Config del perfil: `custom` → `127.0.0.1:11434/v1`, `qwen3:4b`, `platform_toolsets.cli: []`,
  `mcp_servers: {}`, memoria, curator y comprobación de actualizaciones desactivados,
  `security.allow_lazy_installs: false` y `plugins.enabled: [tfg-observability-capture]`.
- Introspección previa, sin modelo: las 24 toolsets integradas y `a2a` desactivadas para `cli`;
  sin MCP. La skill `hermes-agent` es esencial y Hermes no permite desactivarla, pero sin el
  toolset `skills` no puede abrirse. Los plugins bundled de backend y plataforma se cargan
  por diseño; sólo sirven a toolsets desactivadas o al modo gateway.
- Perfil habitual y almacenes de credenciales: tamaño y mtime idénticos antes y después
  (sólo `stat`, sin leer su contenido).

Qué quedó demostrado y qué no:

- **Descubrimiento del plugin: demostrado.** `hermes plugins list` del perfil muestra
  `tfg-observability-capture` como `enabled` con origen `user`, es decir, encontrado en
  `plugins/` y aceptado por el filtro `plugins.enabled`.
- **Importación del módulo: observada.** La copia del plugin tiene bytecode de CPython 3.14
  (el intérprete de Hermes) creado durante la introspección previa, antes del turno. Es un
  indicio de que el loader ejecutó el paquete y llamó a `register(ctx)`, no una prueba.
- **Registro y dispatch de hooks: no demostrados.** Ningún hook llegó a dispararse.
- **Rechazo por contexto antes de cualquier llamada API.** `hermes -z` (un turno,
  `--reasoning none`) terminó con rc=1 en la inicialización del agente: Hermes exige
  `MINIMUM_CONTEXT_LENGTH = 64_000` (`agent/model_metadata.py:273`, sin override) y el perfil
  declaraba 8 192. El `--usage-file` de Hermes registra `failed: true` y `api_calls: null`;
  Ollama no cargó el modelo y la respuesta está vacía.
- **Directorio de captura vacío.** Es el resultado esperado cuando no hay ninguna llamada a
  la API ni a herramientas, porque no se disparan `post_api_request`, `api_request_error` ni
  `post_tool_call`. No es una prueba de fallo del capturador, y tampoco de que funcione.
- **Memoria: estimación, no medición.** Con `ollama_num_ctx ≥ 64k`, qwen3-4B (36 capas, 8 cabezas
  KV, dim 128) necesitaría del orden de 9 GiB de caché KV en fp16 más unos 2,5 GiB de pesos,
  frente a unos 7,2 GiB disponibles en ese momento según `free`. Depende de la configuración
  de Ollama (tipo y cuantización de la caché KV, flash attention, reparto CPU/GPU) y no se ha
  medido.

Estado residual: el perfil `tfg-capture-test` se conserva para una prueba posterior, con el
plugin desactivado (`plugins.enabled: []`; una lista vacía explícita evita que una migración
de config vuelva a habilitar plugins de usuario) y la copia del plugin intacta. Se conservan
también `/tmp/tfg-capture-20261020T155401Z/` y el temporal de la incidencia anterior.

### Integración real loader/hooks con fixtures sintéticos (20/10/2026)

**Resultado: PASS de integración loader/hooks, sin ninguna llamada a un modelo.** Evidencia,
scripts y manifiesto SHA-256:
[evaluation/observability/hermes_loader_hooks_synthetic_2026_10_20/](../evaluation/observability/hermes_loader_hooks_synthetic_2026_10_20/),
separada de la prueba bloqueada y de cualquier captura futura de proveedor.

Vía sin agente LLM (leída en el código antes de ejecutar): `hermes_cli.plugins.discover_plugins()`
hace descubrimiento, gate y `_load_plugin` → `register(ctx)` con `PluginContext`, y
`hermes_cli.lifecycle.invoke_hook` / `ainvoke_hook` hace el dispatch. Ninguna de las dos
construye `AIAgent`. Se ejecutó en el intérprete de Hermes tras su bootstrap real (como su
lanzador), con `HERMES_HOME` apuntando al perfil `tfg-capture-test`, `HERMES_DISABLE_LAZY_INSTALLS=1`,
`-I -B`, entorno limpio y un bloqueo de sockets no-loopback instalado antes de importar Hermes.
Los payloads los construyeron los emisores reales de Hermes; sólo el objeto «agente» del que leen
atributos es un stub sintético sin cliente LLM. El plugin se activó en ese perfil únicamente
durante la ejecución y un `trap` restauró la config byte a byte, con `plugins.enabled: []`.

- **Carga:** `hermes_plugins.tfg_observability_capture` desde el perfil, `source=user`,
  sin error, con hashes iguales a los de `HEAD`.
- **Registro:** `hooks_registered` igual a `provides_hooks` (los tres hooks); `has_hook` falso
  para `pre_tool_call` y `pre_api_request`.
- **Dispatch síncrono real** (el que Hermes usa para estos hooks) y **`ainvoke_hook`** como
  comprobación adicional, ya que Hermes no despacha estos hooks por la vía asíncrona.
  Ambos devuelven `[]`; `failures=0`.
- **JSONL:** 6 eventos válidos contra el esquema, permisos 0600, sin contenido, rutas,
  coordenadas, ids en claro, `base_url` ni la clave falsa. `run_id` y `case_id` los marcan como `SYNTHETIC`.
- **Normalización real de Hermes** sobre contadores sintéticos: `prompt_tokens` llega como `input_tokens`
  `nonzero_normalized`; un 0 llega como `zero_unconfirmed`; una respuesta sin `usage` llega como `usage=null`.
- **`api_request_error`:** Hermes calcula la duración como `time.time() − api_start_time`. Con un
  inicio sintético pasado da unas 266 359 s, que es un artefacto del fixture.
- **Red:** ningún intento no-loopback interceptado. Perfil habitual sin cambios (`stat`),
  sin telemetría nueva y sin `.pyc` nuevos.

Esto demuestra la integración con el loader y los hooks, **no** inferencia, tokens reales ni latencias reales.

### Viabilidad revisada de una captura real (21/10/2026, sólo lectura)

Inspección offline sin cargar modelos, sin tocar configuraciones, sin leer `.env` ni
`auth.json`, sin llamar al proveedor y sin ejecutar Hermes.

**Hechos:**

- **Perfil `tfg-capture-test`, igual que el 20/10:** `custom` → `127.0.0.1:11434/v1`, modelo
  `qwen3:4b`, `context_length: 8192`, `ollama_num_ctx: 8192` y `plugins.enabled: []`.
- **Mínimo de Hermes**, en el código instalado de `~/.hermes/hermes-agent`:
  - `MINIMUM_CONTEXT_LENGTH = 64_000` (`agent/model_metadata.py:273`), aplicado en
    `agent_init._enforce_minimum_context`;
  - con un endpoint local, la ventana efectiva es `max(context_length, model.ollama_num_ctx)`;
  - la única excepción por debajo del mínimo es el proveedor `lmstudio` con un `context_length`
    explícito.
- **`num_ctx` por petición:** el proveedor `custom` envía `extra_body.options.num_ctx = ollama_num_ctx`
  en cada petición (`plugins/model-providers/custom/__init__.py:61-62`).
- **Único modelo local:** `qwen3:4b`, «Qwen3 4B Thinking 2507», Q4_K_M, pesos de 2,50 GB
  (2,33 GiB), según el manifiesto y la cabecera GGUF del blob, leídos sin cargarlo.
  - Ventana nativa: `qwen3.context_length = 262144`. **El modelo no limita.**
  - 36 capas, 8 cabezas KV de dimensión 128, es decir, 147 456 bytes por token de caché KV en fp16.
  - Los parámetros del Modelfile no fijan `num_ctx`.
- **Ollama 0.34.2 (servicio systemd, log de arranque del 21/10):**
  - GPU CUDA **RTX 3070 Laptop, 8,0 GiB, 6,9 GiB disponibles** al arrancar;
  - `OLLAMA_FLASH_ATTENTION:false`, `OLLAMA_KV_CACHE_TYPE` vacío (f16),
    `OLLAMA_CONTEXT_LENGTH:0` (contexto por defecto 4096) y `OLLAMA_NUM_PARALLEL:1`.
- **Memoria del sistema (WSL):** 15,5 GiB de RAM, 8,4 GiB disponibles en el momento de la
  inspección y 4 GiB de swap. No hay `.wslconfig`.

**Estimación, sin medir (no incluye buffers de cómputo):**

| Contexto | Caché KV f16 | KV q8_0 | KV q4_0 | Total con pesos (f16 / q8_0 / q4_0) |
| --- | --- | --- | --- | --- |
| 64 000 | 8,79 GiB | 4,67 GiB | 2,47 GiB | 11,1 / 7,0 / 4,8 GiB |
| 65 536 | 9,00 GiB | 4,78 GiB | 2,53 GiB | 11,3 / 7,1 / 4,9 GiB |

La estimación del 20/10 sólo comparaba con la RAM libre y no tenía en cuenta la GPU.

**Conclusión:** con la configuración actual **no hay vía de captura real**. La condición que falta
es una ventana servida de **64 000 tokens o más**: el perfil declara 8192, así que Hermes rechaza
el turno antes de llamar al modelo, y Ollama sirve 4096 por defecto. El modelo admite esa ventana,
pero no se ha medido que quepa:

- con KV f16, unos 11,1 GiB superan los 6,9 GiB de VRAM, así que obligaría a repartir capas entre
  GPU y RAM, más lento y sin medir;
- con flash attention y KV q8_0, unos 7,0 GiB más buffers quedan **al límite** de la VRAM.

**Alternativas seguras a evaluar, cada una con su propia autorización:**

1. **Sólo cambiar el perfil temporal** a `ollama_num_ctx` y `context_length` de 65 536, sin tocar
   el servicio.
   - Antes, una carga controlada de `qwen3:4b` con ese `num_ctx`, con la simulación parada, para
     **medir** el reparto GPU/CPU y la memoria.
   - Falta confirmar que el endpoint `/v1` de Ollama respeta `options.num_ctx` (hipótesis).
2. **Ajustar el servicio Ollama** con un drop-in de systemd (`OLLAMA_FLASH_ATTENTION=1`,
   `OLLAMA_KV_CACHE_TYPE=q8_0`) y reiniciarlo. Afecta a todo el uso de Ollama en el equipo.
3. **Un proveedor alojado** con contexto suficiente: necesita credenciales, tiene coste y envía el
   contenido fuera del equipo.

**Descartado:** declarar `provider: lmstudio` para aprovechar la excepción. Sería falsear el
proveedor para saltarse el mínimo de seguridad de Hermes. También se descarta cualquier ventana
inferior a 64 000.

### Captura real con el proveedor habitual (21/10/2026)

La conclusión anterior se refiere sólo a Ollama local. Con el perfil habitual `default`
(`poolside/laguna-s-2.1:free` vía `nous`, autenticación normal) **sí se obtuvo una captura real**:
[hermes_real_capture_nous_2026_10_21](../evaluation/observability/hermes_real_capture_nous_2026_10_21/README.md).

- **Activación temporal:** el plugin se activó para una sola ejecución con
  `plugins.enabled: [tfg-observability-capture]`. Hermes no ofrece una opción temporal, así que el
  config se restauró byte a byte y la copia del plugin se retiró al terminar; ambas cosas se
  comprobaron.
- **Comprobado:** carga y registro (registro de procedencia `hermes_plugin_context`, verificado) y
  la emisión real de **un** `llm_call` por `post_api_request`, válido contra el esquema.
- **Coincidencia con el informe nativo** `--usage-file` en el turno principal: 538 / 2 / 256 /
  total 796.
- **No cubierto:** la generación auxiliar del título, porque Hermes emite `pre/post_auxiliary_call`
  y el plugin no registra esos hooks.
- **Exportación:** se exportó a Opik una vez, con 204 + 204 y la confirmación visual de Joel; ver
  [opik-export.md](opik-export.md#evidencia-existente-y-lo-que-falta).

## Activación (desactivado por defecto)

Doble condición; en cualquier otro caso `register(ctx)` no registra ningún hook:

- `TFG_OBSERVABILITY_CAPTURE=1` (exactamente `1`);
- `TFG_OBSERVABILITY_DIR=<ruta absoluta>` (relativa o vacía se rechaza).

Opcionales: `TFG_OBSERVABILITY_RUN_ID` y `TFG_OBSERVABILITY_CASE_ID`, sólo si cumplen
`[A-Za-z0-9_.:-]{1,64}`; un valor libre se guarda como `null`. Además, en Hermes el plugin
también tiene que estar en `plugins.enabled`. El paquete vive fuera de `.hermes/plugins/`,
así que Hermes no lo descubre desde el repositorio ni con `HERMES_ENABLE_PROJECT_PLUGINS`.

## Qué se captura

Un evento por línea en `hermes-events-YYYY-MM-DD.jsonl` (UTC; al crear directorio y
archivo se solicitan permisos 0700/0600; `O_APPEND` y `O_NOFOLLOW` en el archivo final).
Los permisos de rutas preexistentes no se corrigen y los componentes padre pueden
ser enlaces simbólicos: usar una carpeta privada nueva bajo un padre confiable,
no una ruta compartida o controlada por terceros. No es un aislamiento del filesystem.

**Registro de procedencia del sink** (plugin 0.3.0, 21/10/2026). Antes de construir su primer
evento, cada sink escribe una sola vez (`O_EXCL`, 0600) `capture-provenance-<sink_id>.json` con
`schema`, `origin`, `context_type`, `plugin`, `plugin_version`, `capture_schema`,
`verified_hermes_commit`, `sink_id` y `created_at_utc`. Sólo son metadatos: sin rutas, contenido
ni credenciales. `origin` puede ser:
- `hermes_plugin_context`: `register(ctx)` con un contexto cuyo tipo es `hermes_cli.plugins.PluginContext`;
- `non_hermes_context`: cualquier otro contexto, por ejemplo el de los tests;
- `direct_jsonl_sink`: un sink creado directamente.

Es evidencia de cómo se creó el sink, no una certificación, porque un nombre de tipo se puede
imitar. El [exportador](langsmith-export.md) sólo acepta `--provenance captured` si estos registros
verifican. Las capturas anteriores a esta versión no tienen registro: sin declaración se tratan
como de procedencia desconocida, y las sintéticas siguen identificadas por sus marcas.

- **Comunes:** `event_type` (`llm_call`, `llm_error`, `tool_call`), `event_id`, `recorded_at_utc`,
  `run_id`, `case_id`, referencias `session_ref`, `task_ref`, `turn_ref`, `api_request_ref`,
  y las listas `absent_fields`, `redacted_fields` y `ambiguous_zero_fields`.
- **`llm_call`:** provider, upstream_provider, model, response_model, api_mode, finish_reason,
  `timing_source`, `timing_scope`, `api_duration_s`, epoch de inicio y fin, `first_chunk_offset_s`,
  api_call_count, message_count, assistant_tool_call_count, context_length, `requested_tool_names`,
  `usage` y `usage_source`; `retry_count` siempre `null`.
- **`llm_error`:** provider, model, api_mode, tiempos con su procedencia, status_code,
  retry_count, max_retries, retryable, reason, error_type.
- **`tool_call`:** `tool_call_ref`, tool_name, status, error_type, `duration_ms_received`,
  `duration_ms_measured` y `duration_source`.

### Procedencia y honestidad de datos

- **Tokens.** Lo único que el hook permite distinguir de verdad es si hubo uso o no:
  `usage=None` (la respuesta no traía `usage`) se registra como `usage=null`,
  `usage_source=absent`. Si llega un resumen, `usage_source=hermes_normalized_summary` y
  **cada contador conserva el valor recibido** como `{value, status}`:
  - `nonzero_normalized`: entero positivo que salió de un campo del proveedor tras la
    normalización de Hermes. En Chat/Codex, `input_tokens` es `prompt − cache_read − cache_write`
    recortado a 0, así que no es necesariamente un campo literal del proveedor.
  - `zero_unconfirmed`: se recibió 0, que puede ser un cero legítimo del proveedor, un campo
    ausente o el recorte de `input_tokens`. Hermes ya ha perdido esa diferencia (`_first_nonzero`
    y `raw_usage` eliminado), así que el 0 se conserva, se lista en `ambiguous_zero_fields` y
    **no se presenta ni como ausencia ni como cero confirmado**.
  - `derived_nonzero` / `derived_zero`: `prompt_tokens` y `total_tokens` son sumas que calcula
    Hermes, no valores del proveedor. Un `derived_zero` también se lista como ambiguo.
  - `absent` / `redacted`: falta el campo en el resumen o no es un entero ≥0; `value=null`.

  Un resumen con todo a 0 (respuesta con objeto `usage` pero sin campos reconocidos) se
  conserva como ceros sin confirmar, no como uso ausente. Nunca se estima ni se rellena.
- **Tiempos de API.** `timing_source=hermes_hook_wall_clock` (Hermes usa `time.time()`).
  `timing_scope=api_call_from_first_attempt`: `api_start_time` y `api_request_id` se fijan una
  vez por llamada antes del bucle de reintentos, así que `api_duration_s` incluye intentos
  fallidos y esperas.
- **Primer chunk.** Hermes reinicia `first_chunk_at` en cada intento pero conserva el inicio
  del primero, de modo que `first_chunk_offset_s` sólo equivale a TTFB si no hubo reintento.
  Un valor negativo o mayor que `api_duration_s` se marca como redactado.
- **Reintentos.** Sólo hay evidencia en `api_request_error` (`retry_count`, `max_retries`,
  `retryable`). `post_api_request` no la trae, así que `retry_count` es `null` en `llm_call`.
  `api_call_count` cuenta llamadas del turno, no reintentos.
- **Duración de herramientas.** Se separan el valor recibido (`duration_ms_received`) y la
  medición confirmada (`duration_ms_measured`). `duration_source` puede valer:
  - `hermes_reported_ms`: entero positivo que entrega Hermes (en general medido con
    `monotonic` y truncado a ms); es el único caso con `duration_ms_measured`;
  - `zero_default_or_below_1ms`: se recibió 0, que es también el valor por defecto en ramas
    bloqueadas o de error temprano; se conserva `received=0` y `measured=null`, y se lista como ambiguo;
  - `timeout_configured_not_measured`: con `status=timeout` Hermes envía el timeout
    configurado; se conserva como recibido y `measured=null`;
  - `absent` o `redacted`: los dos valores son `null`.

### Correlación y sus límites

- `api_request_ref` = SHA-256 truncado de `"<turn_id>:api:<n>"`. Lo comparten el `llm_call`
  y los `llm_error` de los reintentos de esa misma llamada. Contar los `llm_error` que
  comparten referencia sólo es evidencia de reintentos si Hermes dispara el hook en cada uno,
  algo que no se ha verificado en ejecución.
- `tool_call` incluye `api_request_ref` cuando Hermes lo propaga (puede llegar vacío y queda
  `null`) y su propio `tool_call_ref`. `requested_tool_names` de `llm_call` no lleva ids, así
  que la relación entre petición y ejecución se hace por nombre y orden, no por id.
- Las referencias no llevan salt: son seudónimas, no anónimas. Quien conozca el id original
  puede recalcularlas, y son estables entre corridas.
- `recorded_at_utc` es la hora de escritura, no la del evento. El orden entre hilos no está
  garantizado; para ordenar, usar los epochs de Hermes.

## Qué se descarta siempre

Prompts, mensajes, historial, system prompt, contenido y `tool_calls` completos de la
respuesta, argumentos y resultados de herramientas, `error.message`, `error_message`,
`request`, `middleware_trace`, `moa_references`, `assistant_message`, `base_url`, `platform`,
ids en claro y cualquier campo no listado. Los eventos se construyen por lista blanca, así que
un campo nuevo de Hermes no se copia por accidente.

Redacción defensiva de los textos que sí se guardan: patrón corto de identificador, sin `://`
y sin aspecto de secreto (`sk-`, `ghp_`, `AKIA`, JWT, `bearer`, `api_key`, `token=`, `secret`,
`password`, hex ≥32 o rachas largas sin separadores). Los números sólo entran en campos de
contadores y duraciones, así que coordenadas u otros valores de misión no tienen campo donde
aparecer. Un fallo de escritura sólo incrementa `failures`: no se registra ni se imprime.

## Pruebas offline realizadas

- Tests sintéticos con centinelas (clave falsa, coordenadas, ruta, nombre de misión,
  base_url, ids en claro). Cubren:
  - desactivación por defecto y hooks iguales al manifiesto;
  - ausencia de los centinelas en el JSONL;
  - uso ausente (`null`), cero legítimo del proveedor y resumen con ceros por defecto
    (ambos conservados como `zero_unconfirmed`), sumas derivadas y contadores inválidos o ausentes;
  - offset de primer chunk incoherente;
  - reintentos sólo desde `api_request_error`;
  - duraciones 0, timeout, ausentes e inválidas;
  - silencio en stdout/stderr y fallos de escritura contenidos;
  - tipos inesperados, permisos, concurrencia y symlink.

  Cada evento se valida contra el esquema.
- Contrato estático con el código de Hermes instalado (ver tabla).
- Mutaciones del módulo (fugas, ceros como medida, timeout como medida, offset sin validar,
  impresión en fallo, reintento inventado): todas detectadas en la versión `/2`; no se han
  repetido tras el cambio a `/3`.

## Prueba manual mínima (ejecutada una vez y bloqueada; requiere nueva autorización)

Objetivo: comprobar la carga real y qué campos entrega el proveedor, sin simulación ni control.
Los pasos 1–4 ya se ejecutaron con el perfil `tfg-capture-test` (ver la sección de la prueba
bloqueada). Para repetir el 5 hace falta un modelo y una configuración de Ollama que sirvan
al menos 64 000 tokens de contexto con la memoria disponible, y volver a habilitar el plugin
en `plugins.enabled`. Ambas cosas requieren autorización aparte.

1. **Perfil temporal de Hermes**, no el personal y no un `HERMES_HOME` suelto (este dispara
   la preparación de dependencias descrita arriba). Los perfiles viven en
   `~/.hermes/profiles/<nombre>` y comparten el estado de dependencias del root propietario.
   Crear, por ejemplo, `tfg-capture-test` **sin `--clone`** para no copiar `.env` ni
   credenciales (sintaxis por verificar con `hermes profile --help`). Este paso crea un
   directorio en `~/.hermes` y requiere autorización explícita.
2. Copiar `observability/hermes_capture/` a `~/.hermes/profiles/tfg-capture-test/plugins/tfg-observability-capture/`
   y añadir `tfg-observability-capture` a `plugins.enabled` del `config.yaml` **de ese perfil**.
   No cambiar `plugins.isolation`.
3. En esa shell, fijar `TFG_OBSERVABILITY_CAPTURE=1`, `TFG_OBSERVABILITY_DIR=/tmp/tfg-capture-<fecha>`
   (fuera del repo y de las carpetas de evidencias), `TFG_OBSERVABILITY_RUN_ID` y `TFG_OBSERVABILITY_CASE_ID`.
4. Comprobar con el listado de plugins del perfil que aparece habilitado, antes de conversar.
5. Conversación mínima en ese perfil **sin el servidor MCP del proyecto o con sólo consultas
   de lectura**: sin `start_simulation`, `restart_simulation`, `stop_simulation`, preflight,
   secuencias, reconciliación, retiro ni `execute_approved_mission`. Por ejemplo, un turno de
   texto y una herramienta de sólo lectura. Esto consume el proveedor LLM configurado en el perfil.
6. Revisar los JSONL:
   - validarlos contra `event.schema.json`;
   - buscar que no aparezcan el texto de la conversación, rutas, coordenadas ni claves;
   - anotar `absent_fields` y `ambiguous_zero_fields`;
   - conservar el SHA-256 de los archivos si se usan como evidencia.
7. Retirar el plugin de `plugins.enabled`, borrar la copia del plugin y, si se desea, eliminar
   el perfil temporal.

## Límites y pendientes

- El registro y el dispatch reales están demostrados sólo con fixtures sintéticos. Falta un turno
  de inferencia real: la única conversación quedó bloqueada antes de inferencia por el contexto
  mínimo de 64 000 tokens de Hermes.
- Si una versión de Hermes renombra kwargs, los campos afectados aparecerán como ausentes,
  no inventados; el contrato estático debería detectarlo.
- La rotación es diaria por UTC; no hay borrado ni límite de tamaño automáticos.
- Exportadores a LangSmith u Opik, contexto de experimento ampliado (commit, prompt, dataset)
  y una nueva versión de `run.schema.json` quedan para incrementos separados.
