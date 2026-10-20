# Captura local de observabilidad de Hermes (prototipo)

Fecha: 20/10/2026. **Prototipo offline. No instalado ni activado en ningún perfil; no cargado
en un proceso Hermes real.** Esquema de eventos: `tfg.hermes.capture/3`.

Plugin opcional que convierte tres hooks de observación de Hermes en eventos JSONL
locales con sólo metadatos: uso de tokens si el proveedor lo entrega, modelo/proveedor,
tiempos que Hermes mide y nombres de herramientas. Es la capa de captura común prevista
para comparar después LangSmith y Opik sobre los mismos registros; **no incluye SDK de
ninguna plataforma ni exporta datos**.

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

- **Carga real dentro de Hermes.** No se ha ejecutado discovery, `register(ctx)` con un
  `PluginContext` auténtico ni un dispatch real: el `FakeContext` de los tests sólo registra
  llamadas y **no es una prueba de carga**.
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

## Prueba manual mínima (preparada, no ejecutada; requiere autorización)

Objetivo: comprobar la carga real y qué campos entrega el proveedor, sin simulación ni control.

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

- Falta la prueba manual anterior para demostrar la carga y el dispatch reales.
- Si una versión de Hermes renombra kwargs, los campos afectados aparecerán como ausentes,
  no inventados; el contrato estático debería detectarlo.
- La rotación es diaria por UTC; no hay borrado ni límite de tamaño automáticos.
- Exportadores a LangSmith u Opik, contexto de experimento ampliado (commit, prompt, dataset)
  y una nueva versión de `run.schema.json` quedan para incrementos separados.
