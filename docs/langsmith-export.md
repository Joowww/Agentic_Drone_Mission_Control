# Exportador de la captura local a LangSmith (dry-run por defecto)

Fecha: 20/10/2026. **Probado offline y con un único envío autorizado de fixtures sintéticos**
([registro](#primer-envío-sintético-realizado-20102026)). Ningún dato real enviado.
No es una captura real de proveedor ni un baseline de gasto o rendimiento.

Código: [observability/langsmith_export.py](../observability/langsmith_export.py) ·
tests: [test_langsmith_export.py](../tests/test_langsmith_export.py) ·
dependencias: [requirements-observability.txt](../requirements-observability.txt) ·
origen de los datos: [captura local de Hermes](hermes-observability-capture.md).
Opik dispone de un [exportador separado](opik-export.md), probado offline con transporte falso; no se ha enviado a Opik.

## Contrato comprobado

Versión instalada: `langsmith 0.14.11`, actualizada el 20/10/2026 desde 0.14.1 sin cambiar
ningún otro paquete ([evidencia](../evaluation/observability/langsmith_agent_addressing_prep_2026_10_20/)).
El primer envío se hizo con 0.14.1. Se leyó su código y la documentación oficial
(`docs.langchain.com/langsmith/run-data-format`, `.../log-llm-trace` y `.../log-traces-to-agent`).

### Destino: proyecto o agente/entorno

| Hecho (documentación oficial y SDK 0.14.11) | Consecuencia en el exportador |
| --- | --- |
| Una traza va a un agente o a un proyecto, nunca a ambos. El envío por agente está en beta, sólo existe en workspaces basados en agentes y exige `langsmith>=0.14.9` | Exactamente un destino: `--project` o `--agent-id` + `--agent-environment` |
| El agente se identifica por su **ID** (campo ID del Overview, no el nombre visible), una etiqueta DNS de 1 a 63 caracteres en minúsculas; el entorno es `local`, `development`, `staging` o `production` | Se valida con la misma regla antes de construir nada |
| `create_run(address=AgentAddress)` viaja como `address: "lrn:agents/<id>/environments/<entorno>"` sin `session_name`/`session_id`. `project_name` junto a `address` se rechaza | En modo agente se pasa sólo `address`; en modo proyecto, sólo `project_name` |
| Si el destino sale de variables de entorno y es inválido, `create_run` descarta el run sin error | El destino siempre va explícito en código y el envío se ejecuta con `env -i` |
| Con `address`, el SDK emite `LangSmithBetaWarning`: un workspace sin direccionamiento por agente rechaza el run y la traza se pierde | Se espera ese aviso; no hay vuelta automática a un proyecto |
| — | Los ids deterministas y el ledger incluyen el destino completo: el nombre del proyecto (igual que en el primer envío, que sigue siendo reproducible) o el LRN del agente. Los proyectos cuyo nombre empieza por `lrn:` se rechazan |

| Hecho | Consecuencia en el exportador |
| --- | --- |
| `dotted_order` está formado por segmentos `<inicio %Y%m%dT%H%M%S%fZ><uuid>` unidos por `.`: el primer uuid es `trace_id`, el penúltimo `parent_run_id` y el último `id` | Se construye así y lo comprueban los tests |
| `start_time` es obligatorio (`schemas.RunBase`) y, si falta, `_run_transform` lo rellena con `now()` | Nunca se envía un run sin inicio conocido: el SDK inventaría uno |
| `end_time` es opcional, pero un run sin fin queda «en curso» | No se usan runs abiertos para representar duraciones desconocidas |
| Los runs admiten `events` (`{name, time, kwargs}`); el SDK sólo filtra los `new_token` | Las herramientas y los eventos sin intervalo viajan como eventos puntuales de la raíz |
| `Client.batch_ingest_runs` captura los errores HTTP y sólo emite un warning | No se usa: un fallo pasaría desapercibido |
| El `Client` monta por defecto `Retry(total=3)` sobre 429/500/502/503/504/408/425 para todos los métodos, `POST` incluido; `POST /runs` hace un solo intento a nivel de aplicación (`stop_after_attempt=1`) | `make_client` pasa `Retry(total=0, …)`: un fallo se informa una vez y no se reintenta automáticamente |
| `create_run` con `auto_batch_tracing=False` hace un `POST /runs` síncrono que propaga los errores… | Es la vía de envío |
| …salvo HTTP 409, que ignora (`to_ignore=(LangSmithConflictError,)`) | Un id ya existente no se duplica, pero el SDK no deja distinguirlo de uno nuevo |
| `_insert_runtime_env` añade entorno de ejecución y variables `LANGCHAIN_*`/`LANGSMITH_*` a `extra` salvo con `omit_traced_runtime_info=True` | Se pasa `omit_traced_runtime_info=True` |
| La documentación dice que LangSmith estima el coste con `usage_metadata` cuando `ls_model_name` identifica el modelo | No se rellenan `usage_metadata`, `ls_model_name` ni `ls_provider`: no hay coste estimado |
| El `FormatChecker` de `jsonschema` sólo valida `date-time` si está instalado `rfc3339-validator`, que **no** lo está | El exportador analiza `recorded_at_utc` y exige zona horaria; si no puede, la línea se rechaza |

## Uso

```bash
# Dry-run (predeterminado): valida, construye y muestra los runs; sin SDK, credenciales ni red.
.venv/bin/python -m observability.langsmith_export CAPTURE.jsonl \
    (--project NOMBRE | --agent-id ID --agent-environment ENTORNO) [--ledger LEDGER.jsonl] [--include-untimed]

# Envío: requiere todo lo siguiente.
LANGSMITH_API_KEY=... .venv/bin/python -m observability.langsmith_export CAPTURE.jsonl \
    (--project NOMBRE | --agent-id ID --agent-environment ENTORNO) --ledger LEDGER.jsonl --send \
    [--allow-synthetic] [--include-untimed]
```

El dry-run devuelve rc=1 si hay líneas inválidas. Con `--send`, todas las precondiciones
locales (validación, ledger, marca sintética) se comprueban **antes** de leer
`LANGSMITH_API_KEY` o crear el cliente. La clave no se imprime ni se registra; un error de
envío se informa sólo por su tipo.

## Tiempos: qué se mide, qué se deriva y qué queda desconocido

| Origen | Representación en LangSmith | `tfg_time_basis` |
| --- | --- | --- |
| `llm_call`/`llm_error` con `started_at_epoch_s` y `ended_at_epoch_s` de Hermes | Run `llm` con ese inicio y fin (`tfg_latency_measured=true`). Si `fin − inicio` difiere de `api_duration_s` en más de 1 ms, se avisa y se conservan ambos | `hermes_epochs` |
| `tool_call` (Hermes da duración pero no inicio) y `llm_*` sin epochs | **Evento puntual** `tfg.tool_call`/`tfg.llm_*` en la raíz, con `time = recorded_at_utc`, sin run propio y sin latencia (`tfg_latency_measured=false`). La duración recibida, la medida y su procedencia van en `kwargs` | `capture_recorded_at_point_not_an_interval` |
| Raíz de una traza con algún run medido | Intervalo **derivado** como mínimo y máximo de los epochs de Hermes de sus runs medidos (`tfg_interval_derived=true`). No se mezcla con `recorded_at` | `derived_min_max_of_hermes_epochs` |
| Traza sin ningún intervalo medido | **Retenida** por defecto (`withheld_traces`, motivo `no_measured_interval`). Con `--include-untimed`, raíz con `start = end =` primer `recorded_at` como marcador, `tfg_interval_status=unknown_no_measured_interval`, etiquetas `interval-unknown` y `latency-not-measured` y prefijo `[interval unknown]` | `capture_recorded_at_marker` |

`recorded_at_utc` es la hora a la que escribió el capturador, que corre en el mismo proceso que
Hermes. Es probable que comparta reloj con los epochs, pero su semántica es distinta (escritura
frente a llamada a la API) y no se ha demostrado que sean comparables. Por eso la raíz anota
`tfg_point_event_time_basis=capture_recorded_at_not_compared_with_hermes_epochs` y un evento
puntual puede quedar fuera del intervalo derivado. Se conserva como se observó.

### Cómo se verá en LangSmith y qué métricas excluir

No verificado en la interfaz, porque no se ha enviado nada. Según el modelo de datos:

- Los runs `llm` muestran latencia real de Hermes (reloj de pared, incluye reintentos según
  `tfg_timing_scope`). La latencia de la raíz es un intervalo derivado, no una medida.
- No hay runs `tool`: las vistas y estadísticas de herramientas de LangSmith quedan vacías.
  Las duraciones de herramientas sólo están en los `kwargs` de los eventos.
- **Excluir de cualquier comparación de rendimiento:**
  - la latencia de las raíces (`run_type=chain`, `tfg_interval_derived=true`), porque es derivada;
  - toda la traza marcada `interval-unknown` o `latency-not-measured`, cuya latencia 0 es un marcador;
  - las agregaciones de latencia, P50/P99 o tokens del proyecto que mezclen esas raíces, o datos `synthetic`;
  - cualquier cifra de coste, que no se calcula (`tfg_cost=not_computed`).
- **Usar sólo** runs `llm` con `tfg_latency_measured=true` y `tfg_data_kind=captured_hermes_metadata`,
  y leer los tokens de `tfg_usage` respetando su `status`.

## Conversión

- **Validación:** cada línea debe ser JSON válido contra `event.schema.json` (`tfg.hermes.capture/3`)
  y tener un `recorded_at_utc` analizable con zona horaria. Se rechazan las líneas vacías y los
  `event_id` repetidos. No se repara nada, y con errores no se envía.
- **Jerarquía:** un run `chain` raíz por `(run_id, session_ref, turn_ref)`, con
  `tfg_observed_event=false` porque es una agrupación del exportador. Los eventos sin `turn_ref`
  forman su propia traza.
- **Ids:** uuid5 de `(proyecto, event_id)` y de `(proyecto, run_id, session_ref, turn_ref)`.
- **Lista blanca:** `inputs` y `outputs` van vacíos. Los campos permitidos pasan como `tfg_<campo>`
  a `extra.metadata` o a los `kwargs` del evento, y cualquier texto con `://` o aspecto de secreto
  se rechaza. No hay prompts, respuestas, argumentos, resultados, rutas ni ids en claro.
- **Procedencia** que se conserva tal cual:
  - `tfg_usage` con `{value, status}` por contador, de modo que ceros sin confirmar y valores
    derivados siguen distinguidos;
  - `tfg_usage_semantics=hermes_normalized_summary_not_provider_raw`;
  - `tfg_absent_fields`, `tfg_redacted_fields`, `tfg_ambiguous_zero_fields`, `tfg_duration_source`
    y `tfg_units` (s, ms y segundos desde epoch).
- **Procedencia** (exportador v4, 21/10/2026): ya no se deduce sólo del nombre de los ids. Cada
  traza recibe un `tfg_data_kind` y un `tfg_provenance_basis`:

  | Tipo | Cuándo | Envío |
  | --- | --- | --- |
  | `synthetic_fixture` | `synthetic` en `run_id`/`case_id` (base `synthetic_marker_in_ids`) o `--provenance synthetic` (`declared_synthetic`) | Requiere `--allow-synthetic`. Prefijo `SYNTHETIC · `, etiqueta `synthetic` |
  | `unknown_provenance` | **Por defecto**: sin declaración y sin marca sintética (`no_provenance_declaration`) | **Bloqueado** salvo `--allow-unknown-provenance`. Prefijo `UNKNOWN-PROVENANCE · `, etiqueta `provenance-unknown` |
  | `captured_hermes_metadata` | Sólo con `--provenance captured` **y** registros de procedencia del sink que verifican (`declared_captured_with_hermes_sink_provenance_record`) | Ruta normal, sin flags adicionales. Etiqueta `captured-metadata` |

  `--provenance captured` se rechaza si junto al archivo de captura no hay al menos un
  `capture-provenance-*.json`, o si alguno no cumple todo lo siguiente: es un archivo regular,
  tiene el esquema esperado, su origen es `hermes_plugin_context` y es anterior al primer evento.
  También se rechaza si los eventos llevan una marca sintética. Una marca sintética sólo puede
  hacer más conservadora la clasificación. El registro prueba cómo se creó el sink, no lo
  certifica criptográficamente: se puede copiar o falsificar. La procedencia no cambia los ids
  de los runs, así que los envíos históricos siguen siendo reproducibles. La evidencia sintética
  del loader, que no tiene registros, sigue siendo `synthetic_fixture` por sus marcas.
- **Trazas retenidas:** la procedencia de las trazas retenidas por no tener intervalo medido
  también cuenta. Si todas se retienen, una entrada sintética o desconocida sigue necesitando
  `--allow-synthetic` o `--allow-unknown-provenance`; el motivo dice `(in withheld traces)` y se
  bloquea antes de leer credenciales. Una captura declarada y verificada sigue sin necesitar flags.
  El dry-run lista los motivos en `blocked_for_send_by_default`. Hasta el 21/10/2026 la puerta sólo
  miraba las trazas emitidas, y ese caso pasaba como permitido sin ningún bloqueo en el resumen. Con
  trazas emitidas, los mensajes no cambian. `synthetic_traces`/`unknown_provenance_traces` siguen
  contando sólo las emitidas; la procedencia de las retenidas está en `withheld_traces[].kind`.
- **Caso que motivó el cambio:** el fixture offline del 21/10, con 37 tokens de entrada y 2 de
  salida e ids `OFFLINE-FIXTURE-…`, se clasificaba como `captured_hermes_metadata` porque sus ids no
  contenían `synthetic`. Ahora es `unknown_provenance` y su envío queda bloqueado. Nunca llegó a
  enviarse.

## Reexportación y fallos parciales

- **Ledger local** (obligatorio para enviar): registra trazas completas por proyecto, que se
  omiten en reexportaciones (`skipped_in_ledger`). Sólo protege dentro de ese archivo y ese proyecto.
- **Ids deterministas:** sin ledger, el servidor recibiría los mismos ids. Según el SDK responde
  409 y el SDK lo ignora, así que no se duplica, pero el informe cuenta esos runs en `posted`. Que
  el servidor responda 409 es una inferencia a partir del SDK, no verificada contra LangSmith.
- **Fallo parcial:** el envío se detiene en el primer error que no sea un conflicto, informa
  `failed_trace` (raíz, run y tipo de error) y `not_attempted_traces`, y no registra esa traza.
  Al reintentar, los runs ya aceptados se reenvían con el mismo id. Si el contenido cambió entre
  intentos, LangSmith conservaría la primera versión.

## Pruebas offline

`tests/test_langsmith_export.py` (40 funciones de test, 51 casos con los parametrizados, a 21/10/2026),
además de los de la captura. Incluyen que el
`Client` real construido por `make_client` monta adaptadores sin reintentos. Cubren:
- **validación:** JSON inválido, línea vacía, campo fuera del esquema, duplicado y timestamp que el
  `FormatChecker` deja pasar;
- **conversión:** procedencia y ausencia de campos de coste;
- **relojes mezclados:** la raíz sigue sólo los epochs de Hermes;
- **herramientas sin inicio:** son eventos y nunca runs de 0 ms;
- **duraciones:** 0 y timeout no se presentan como medidas;
- **eventos sin intervalo:** un `llm` sin epochs y las trazas retenidas o `interval-unknown`;
- **trazas retenidas y autorización:** entradas sintéticas o desconocidas con todo retenido quedan
  bloqueadas (también por CLI, sin construir el cliente) y el resumen explica el motivo; una
  captura verificada retenida conserva su comportamiento; los mensajes con trazas emitidas no cambian;
- **estructura:** jerarquía, `dotted_order`, ids deterministas, exclusión de contenido y secretos,
  y marca sintética sobre la evidencia del loader;
- **dry-run en subproceso:** sockets bloqueados, `os.environ` vigilado y sin importar `langsmith`;
- **envío:** precondiciones antes de credenciales, reexportación, fallo parcial y reanudación con
  cliente falso, y envío con el `Client` real de 0.14.1 sobre una sesión HTTP falsa sin red
  (cuerpos `POST /runs`, `events` de la raíz, sin runs `tool`, 409 sin ids nuevos).

Dry-run real sobre la [evidencia sintética del loader](../evaluation/observability/hermes_loader_hooks_synthetic_2026_10_20/):
rc=0, 6 eventos, 1 traza temporizada (raíz más 3 runs `llm`) con 1 evento puntual y 2 trazas sólo
de herramientas retenidas; con `--include-untimed`, 3 trazas, 2 de ellas `[interval unknown]`. En
esa evidencia, la raíz derivada abarca unos 3 días porque el `api_start_time` sintético del
`llm_error` es fijo y Hermes lo cierra con la hora actual. Es un artefacto del fixture, no una
mezcla de relojes. Nada enviado.

## Primer envío sintético autorizado: qué tendrá que preparar Joel

No hace falta pegar claves en el chat; todo se configura localmente.

1. Cuenta/workspace de LangSmith y región. Si no es la región por defecto, apuntar su endpoint.
2. Un proyecto dedicado sólo a datos sintéticos (por ejemplo `tfg-synthetic`) y su política de retención.
3. Una API key de alcance mínimo, guardada fuera del repo (gestor de secretos o archivo con
   permisos 0600) y exportada sólo en la shell del envío como `LANGSMITH_API_KEY` (y
   `LANGSMITH_ENDPOINT` si aplica), sin activar `LANGSMITH_TRACING`.
4. Una ruta de ledger fuera del repo (por ejemplo `~/tfg-langsmith/ledger-synthetic.jsonl`).
5. Autorización explícita para un único envío del archivo sintético, con `--allow-synthetic` y,
   si se quieren ver las trazas sin intervalo, `--include-untimed`.
6. Después: conservar el informe JSON y el ledger con su SHA-256, revisar en la interfaz la
   jerarquía, los eventos y la ausencia de coste, y retirar la clave de la shell.

## Primer envío sintético realizado (20/10/2026)

Evidencia y manifiesto: [evaluation/observability/langsmith_first_synthetic_send_2026_10_20/](../evaluation/observability/langsmith_first_synthetic_send_2026_10_20/).

- **Configuración:** destino `https://eu.api.smith.langchain.com`, proyecto `tfg-synthetic` y clave
  *tracing-only* cargada sólo en un `env -i` desde un archivo local 0600. Sin `LANGSMITH_TRACING`;
  la clave no aparece en el informe ni en stderr.
- **Resultado:** rc=0, `posted=4`, `completed_traces=1`, sin conflictos ni fallos, y las 2 trazas
  sin intervalo retenidas. Traza raíz `bec45370-184e-5b66-b211-6ad75481eb5e`.
- **Alcance:** `posted` sólo significa que cada `POST /runs` volvió sin error. No se ha leído de
  vuelta desde LangSmith, porque la clave tracing-only no lo permite, y la interfaz no se ha
  observado. La jerarquía, los eventos y las marcas en la interfaz están pendientes de la
  revisión manual de Joel.
- **Destino real:** el envío usó `project_name` (campo `session_name: tfg-synthetic`), es decir, un
  proyecto de trazas, no el agente `tfg-synthetic`. En la interfaz EU basada en agentes, ese agente
  aparece vacío en Local y Production. No está documentado ni verificado dónde se muestra una traza
  dirigida a un proyecto en ese tipo de workspace. La petición HTTP real no se registró; hay una
  reconstrucción offline posterior, etiquetada como tal, en la
  [preparación del envío por agente](../evaluation/observability/langsmith_agent_addressing_prep_2026_10_20/).

## Siguiente prueba preparada: agente `tfg-synthetic`, entorno `local` (no ejecutada)

Requiere una autorización nueva. Dry-run y vista previa offline del payload en la
[carpeta de preparación](../evaluation/observability/langsmith_agent_addressing_prep_2026_10_20/):
1 traza con 4 runs, ids nuevos, y cada `POST /runs` lleva sólo
`address: lrn:agents/tfg-synthetic/environments/local`. Comando previsto: un único intento, sin
reintentos, con la misma clave local y un ledger nuevo.

```bash
cd ~/TFG/Agentic_Drone_Mission_Control
R=evaluation/observability/langsmith_agent_synthetic_send_<fecha>   # carpeta nueva
mkdir "$R"
env -i PATH=/usr/bin:/bin HOME="$HOME" bash -c '
  set -a; . "$HOME/.config/tfg-langsmith/synthetic.env"; set +a
  exec .venv/bin/python -m observability.langsmith_export \
    evaluation/observability/hermes_loader_hooks_synthetic_2026_10_20/capture/hermes-events-2026-10-20.jsonl \
    --agent-id tfg-synthetic --agent-environment local \
    --ledger "$HOME/tfg-langsmith/ledger-agent-tfg-synthetic-local-20261020.jsonl" \
    --send --allow-synthetic' > "$R/send_report.json" 2> "$R/send.stderr"
```

## Prueba de tokens reales: pendiente

No se ha hecho ninguna llamada a un proveedor real. El 21/10/2026 se descartó la vía con Ollama
local: el perfil temporal declara 8 192 tokens, Hermes exige un mínimo fijo de 64 000 y, según la
estimación, eso requiere unos 12 GiB repartidos entre VRAM y RAM (no medido). Tampoco se usa el
perfil habitual, porque cargar el plugin exigiría cambiar la configuración personal y su prompt
incluye `SOUL.md` y memorias personales. Se retomará cuando haya un modelo o perfil compatible
que no obligue a forzar el contexto ni a copiar credenciales. Esa captura debería exportarse con
`--provenance captured`, de modo que el registro del sink la verifique.

## Límites

- `rfc3339-validator` está declarado pero no instalado: hoy el formato `date-time` lo comprueba el
  exportador, no el esquema.
- El comportamiento del servidor (409, orden de llegada, visualización de `events`, retención) no se
  ha verificado. Sólo se ha comprobado el lado cliente del SDK.
- No se exportan costes ni `usage_metadata`. Contadores nativos de LangSmith requerirían decidir
  cómo representar ceros sin confirmar y valores normalizados sin estimar un coste falso.
- Sin runs `tool` no hay estadísticas de herramientas en LangSmith. Las duraciones sólo están en eventos.
