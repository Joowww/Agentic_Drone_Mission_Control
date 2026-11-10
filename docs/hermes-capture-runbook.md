# Captura real de Hermes y preparación para Opik (guía breve)

Utilidad: [observability/hermes_capture_run.py](../observability/hermes_capture_run.py) ·
tests: [test_hermes_capture_run.py](../tests/test_hermes_capture_run.py) ·
contexto: [captura de Hermes](hermes-observability-capture.md), [exportador Opik](opik-export.md),
[dashboard y hoja de ruta](observability-dashboard-roadmap.md).

Sustituye a los scripts de un solo uso de la scratchpad que se usaron el 21/10/2026. La cadena
Hermes real → plugin → exportador → Opik está demostrada por
[hermes_real_capture_nous_2026_10_21](../evaluation/observability/hermes_real_capture_nous_2026_10_21/README.md)
y [opik_hermes_real_send_2026_10_21](../evaluation/observability/opik_hermes_real_send_2026_10_21/README.md),
con la traza y el span confirmados visualmente por Joel.

## Qué está acreditado y qué no

- **Cubre sólo el turno principal** de Hermes. La generación auxiliar del título usa
  `pre/post_auxiliary_call` y el plugin no la captura. Sus contadores sólo aparecen en el informe
  nativo y se presentan aparte.
- **Los costes facturados son desconocidos.** Hermes da un coste *estimado* y el exportador no
  calcula ninguno.
- Los contadores de tokens son los normalizados por Hermes. Los ceros pueden estar sin confirmar
  (`zero_unconfirmed`) y los totales son derivados.
- Una sola captura no es una muestra representativa.

## Recorrido 1: preparar y ejecutar una captura

Perfil habitual `default`, proveedor `nous`, modelo `poolside/laguna-s-2.1:free`. **No usar Ollama.**

### 1.a Comprobación previa (offline; no crea nada ni ejecuta Hermes)

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control
.venv/bin/python -m observability.hermes_capture_run capture
```

Salida esperada, resumida (real, 22/10/2026):

```text
"mode": "preflight", "ok": true
checks: hermes_binary, tool_selection_sources_verified, config_present, config_parses,
        no_plugins_allow_list, plugin_not_disabled, no_mcp_named_like_selection,
        no_shell_hooks, config_edit_isolated, user_plugins_dir_empty,
        plugin_source_present, no_other_hermes_process   -> all "ok": true
"facts": {"config_sha256": "c99d1a88…08f4fb", "model": "poolside/laguna-s-2.1:free", "provider": "nous", …}
"note": "Offline preflight only: nothing was created and Hermes was not run."
```

rc=0 si todo está bien y rc=1 si falla alguna comprobación. Las comprobaciones son:

- **Herramientas y MCP a cero:** los 6 archivos fuente del Hermes instalado deben tener los hashes
  de la versión en la que se verificó que `--toolsets catalog` no selecciona ninguna herramienta ni
  servidor MCP (commit `d923a5eb…`, evidencia `cli_contract.json` del subsistema rover). Si Hermes se
  actualiza, la utilidad **se niega a ejecutar** hasta volver a verificarlo; no lo deduce.
- **Configuración:** ningún servidor MCP se llama `catalog`, no hay `hooks` ni `plugins.enabled`,
  y `~/.hermes/plugins/` está vacío.
- **Edición prevista:** se simula la edición del config y se comprueba que sólo añade
  `plugins.enabled`.
- **Procesos:** no hay ningún otro proceso Hermes visible en `/proc`.

### 1.b Ejecución real (una sola vez y con autorización explícita)

Requiere red y escribir en `~/.hermes`, así que la ejecuta Joel en su terminal.

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control
.venv/bin/python -m observability.hermes_capture_run capture --execute --run-id real-hermes-AAAAMMDD --case-id oneshot-ok --timeout 120
```

Salida esperada si todo va bien (rc=0):

```text
"return_code": 0, "timed_out": false, "hermes_invocations": 1, "automatic_retry": false,
"restore": {"config": "restored", "plugin": "removed", "error_type": null, "ok": true},
"capture_files": ["capture-provenance-<uuid>.json", "hermes-events-AAAA-MM-DD.jsonl"],
"private_dir": "/home/joelm/tfg-hermes-capture-private/<UTC>"
```

Qué hace:

1. Repite la comprobación previa y se detiene si falla.
2. Crea `~/tfg-hermes-capture-private/<UTC>/` (0700, **fuera de Git**) con una copia del config,
   el informe nativo, stdout/stderr, la captura y `run.json`.
3. Instala la copia del plugin y escribe de forma atómica el config con
   `plugins.enabled: [tfg-observability-capture]`.
4. Lanza **una** vez `hermes -z "<prompt>" --toolsets catalog --usage-file <privado>`, con la
   autenticación habitual (la utilidad no lee credenciales) y `HERMES_DISABLE_LAZY_INSTALLS=1`.
   El plazo está acotado (120 s por defecto, como mucho 600); al vencer se envía TERM y luego KILL
   al grupo de procesos. **No hay reintentos.**
5. Restaura **comparando antes de reemplazar**:
   - si el config sigue siendo exactamente el que escribió la utilidad, escribe la copia y comprueba
     el hash → `restored`;
   - si alguien lo cambió → `concurrent_edit_not_overwritten`: no lo pisa, conserva la copia y
     termina con rc=2;
   - si falla la escritura → `restore_failed` con el tipo de error y rc=2.
   - La copia del plugin sólo se borra si su contenido es el instalado; si no,
     `changed_not_removed`.

**Límite de exclusión entre procesos:** Hermes protege el config con un bloqueo que sólo vale
dentro de su propio proceso (`threading.RLock`), así que no existe un bloqueo compartido. La
utilidad detecta otros procesos Hermes al empezar y nunca pisa una edición ajena que detecte, pero
una escritura que ocurra entre la comparación final y el reemplazo se puede perder. Un proceso que
arranque durante la ventana cargaría el plugin, aunque inerte: sin `TFG_OBSERVABILITY_CAPTURE=1` no
registra nada.

Si sale `concurrent_edit_not_overwritten`, `restore_failed` o `changed_not_removed`, hay que
reconciliar a mano usando `config.yaml.backup` del directorio privado. **No se repite la
ejecución.**

## Recorrido 2: validar y preparar la exportación a Opik

### 2.a Revisión y evidencia nueva

```bash
.venv/bin/python -m observability.hermes_capture_run review --private-dir /home/joelm/tfg-hermes-capture-private/<UTC> --evidence-dir evaluation/observability/hermes_real_capture_<etiqueta>
```

Salida esperada (real, sobre una **copia temporal** de la captura del 21/10):

```text
{"events": 1, "provenance_ok": true, "correlation_verdict": "all_compared_values_equal", "manifest": "SHA256SUMS"}
```

Qué hace:

- Valida el JSONL contra el esquema y comprueba los registros de procedencia.
- Rechaza la captura si contiene el prompt, la respuesta (buscada como valor JSON), URLs o rutas
  de `/home`.
- Crea un directorio de evidencia **nuevo**, que nunca reutiliza, con:
  - `capture/`, copiado byte a byte;
  - `native_usage_reviewed.json`, con la lista permitida, sin `session_id`;
  - `run.json`, sin la ruta privada;
  - `capture_summary.json`;
  - `SHA256SUMS`.

`capture_summary.json`:

- reutiliza `observability.capture_summary`, que conserva los estados de los tokens y las
  ausencias, y no compara datos sintéticos ni desconocidos;
- compara **sólo el turno principal** con el informe nativo, cuando hay exactamente una llamada;
- pone el título auxiliar en `auxiliary_native_only` con `captured_by_plugin: false`;
- **no convierte el informe nativo en eventos del plugin**;
- no infiere ni peticiones HTTP, ni reintentos internos, ni coste facturado.

### 2.b Dry-run de Opik para un destino explícito (nunca envía ni lee la clave)

```bash
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_real_capture_<etiqueta> --project <proyecto-real> --workspace joowww
```

Salida esperada (real, copia temporal de la captura del 21/10 y destino `tfg-opik-hermes-real-20261021`):

```text
"sent": false, "traces": 1, "spans": 1,
"trace_ids": ["01a16002-9b28-75bc-abca-6942ca6d1c95"], "span_ids": ["01a16002-9b28-7291-bce7-d68337bb58f2"],
"body_sha256": {"traces_batches": ["881bb615…ea15"], "spans_batches": ["a2b96e37…5fda"]},
"blocked_for_future_send_by_default": [],
"prepared_send_command_NOT_EXECUTED": ".venv/bin/python -m observability.opik_export … --send …"
```

- Antes de nada verifica `SHA256SUMS`, y vuelve a escribirlo después de añadir `opik_dry_run.json`.
- Los bodies coinciden exactamente con los que se enviaron y confirmaron el 21/10, así que el
  dry-run es reproducible.
- Usa un proyecto **distinto** de los sintéticos. Para otro destino hay que crear otra evidencia.

**Serialización del archivo guardado (corregida el 22/10/2026).** `opik_dry_run.json` se escribe
conservando el orden de inserción de las claves, sin `sort_keys`. Si se carga y se serializa cada
body con `opik_export.body_bytes`, salen los mismos bytes y SHA-256 que enviaría `--send`, y que
`body_sha256`. `body_bytes` es la misma función que usa el exportador al enviar: separadores
compactos, orden de inserción y UTF-8. El formato de envío no ha cambiado.

Límite de las preparaciones anteriores: las evidencias creadas antes de la corrección se guardaron
con claves ordenadas y **no se han regenerado ni modificado**, así que sus manifiestos y hashes
siguen siendo los originales. Afecta a `hermes_real_capture_nous_2026_10_22/opik_dry_run.json`.

- Si se recalculan desde esos archivos, los hashes no coinciden con los enviados (para el 22/10,
  `496bbd50…` y `11ea18bc…` frente a `ab2dd88d…` y `455477f9…`).
- El contenido es equivalente: solo cambia el orden de las claves.
- Los hashes de referencia son el `body_sha256` impreso por la utilidad, y el de `batch_intent` en
  el registro de envío. También se pueden obtener regenerando el dry-run con el CLI, como se hizo
  antes del envío del 22/10.

### 2.c Envío: acción separada, con su propia autorización

La utilidad no envía nada. El envío es el comando `observability.opik_export --send` impreso en
`prepared_send_command_NOT_EXECUTED`. Antes de lanzarlo hay que:

- confirmar que el proyecto existe en la interfaz;
- tener una autorización que nombre el destino y los hashes de los bodies;
- usar un `--record` nuevo y un `--error-body-file` fuera del repo;
- introducir la clave con `read -rs` en la propia terminal.

Ver [opik-export.md](opik-export.md#envío-explícito---send).

## Recorrido 3: ensayo de UNA llamada real a una herramienta MCP (preparado, no ejecutado)

**Estado:** se ejecutó una sola vez, autorizado, el 22/10/2026 a las 16:40 UTC. Evidencia en
[hermes_mcp_tool_trial_nous_2026_10_22](../evaluation/observability/hermes_mcp_tool_trial_nous_2026_10_22/README.md).

**Veredicto: `ISOLATION_NOT_CONFIRMED`.**
- La herramienta se ejecutó una vez (`status=ok`) y la respuesta fue `NOT_FOUND`.
- Pero Hermes activó **Tool Search**. Está en `auto` por defecto y se activa con cualquier
  herramienta MCP. En lugar de la herramienta, ofreció los puentes `tool_search`, `tool_describe` y
  `tool_call`, y el modelo usó `tool_describe` antes de llamarla.
- **Corrección del texto siguiente:** el apartado "Aislamiento" suponía que con una sola
  herramienta Tool Search no se activaría. **Era incorrecto.**
- **Corregido y repetido con autorización (16:50 UTC).** La edición del ensayo añade también
  `tools.tool_search.enabled: "off"`:
  - la cadena va entre comillas, porque `off` sin comillas es un booleano en YAML 1.1;
  - si ya hay un valor previo, se rechaza en lugar de sobrescribirlo;
  - se conservan las claves vecinas;
  - las fuentes de Tool Search y de carga del config están fijadas.
- **Veredicto del segundo ensayo: `TOOL_CALL_OBSERVED_AS_EXPECTED`.** Hubo 2 peticiones, cada una
  ofreciendo solo la herramienta; una petición del modelo con su nombre; una ejecución `ok`; y la
  respuesta `NOT_FOUND`. Ver
  [hermes_mcp_tool_trial_direct_nous_2026_10_22](../evaluation/observability/hermes_mcp_tool_trial_direct_nous_2026_10_22/README.md).
- **Revisión de turnos con varias llamadas.** La revisión compara ahora la suma de los contadores
  incrementales de cada llamada con los totales nativos del turno principal. Marca como no
  comparables `api_call_count`, `prompt_tokens`, el coste y el título auxiliar.

**Defecto del plugin encontrado en el ensayo.** El plugin 0.4.0 escribía `requested_tool_names:
[null]` con el `ToolCall` normalizado de Hermes, que lleva `name` en primer nivel. Está corregido en
0.4.1, con test de regresión y de contrato. La captura del ensayo conserva los `null`.

Lo que sigue es la preparación original, sin cambios salvo esta nota.

### Herramienta elegida: `get_mission_state`, consulta por `run_id` neutro

- **Herramienta:** `tools/hermes_mcp_server.py` → `tools/mission_state.py`. Ya existe; no se ha
  creado ninguna nueva.
- **Camino que recorre:** con un `run_id` UUID canónico que no existe, `_view` solo lee
  `job.json` y `report.json` en `missions/generated/preflights/<run_id>/` y busca en los informes
  históricos `simulation/ros2_gazebo/results/virtual_preflight_*/*_report.json`. Después devuelve
  `{"status": "NOT_FOUND", "run_id": …, "consent": "NOT_GRANTED_BY_THIS_QUERY"}`.
- **Escrituras:** las de esos módulos están en otras funciones (crear borradores, propuestas y
  revisiones), no en este camino.
- **Comprobado con un audit hook,** en un subproceso, importando el módulo y llamando a la función
  directamente, sin stdio MCP ni Hermes:
  - la llamada no hace ninguna escritura, `mkdir`, proceso ni socket;
  - al importar solo aparece la sonda IPv6 de `urllib3`: un `bind` a `::1`, puerto 0, sin
    `connect`;
  - el resultado no contiene `"error"`, que es la cadena que haría que Hermes marcase la
    llamada como `status=error`.
- **Caso neutro:** `run_id = 00000000-0000-4000-8000-000000000000`. El preflight comprueba que no
  corresponde a ningún trabajo ni informe. El caso no contiene datos personales, misiones ni
  órdenes de simulación.

### Aislamiento: solo esa herramienta

Usa mecanismos soportados por Hermes `d923a5eb48`, comprobados en las fuentes instaladas y fijados
por hash en `TRIAL_SOURCES`:

1. **`--toolsets tfg-mission-control`.** En `-z` es una entrada válida porque nombra un servidor
   MCP configurado. Resuelve al alias del toolset `mcp-tfg-mission-control`, que solo contiene
   herramientas registradas de ese servidor. Ninguna herramienta integrada entra en la selección.
   La memoria y el context engine solo añaden herramientas si se piden sus toolsets.
2. **Filtro temporal `mcp_servers.tfg-mission-control.tools`:** `include: [get_mission_state]`,
   `resources: false` y `prompts: false`. Hace que solo se registre esa herramienta, sin las
   utilities de recursos ni de prompts. Se añade junto a `plugins.enabled`, se valida al parsear
   (no cambia nada más) y se restaura byte a byte con el resto del config.

El modelo ve la herramienta como `mcp__tfg_mission_control__get_mission_state`.

- **El modo `catalog` no cambia:** sigue siendo el predeterminado de `capture` y su edición solo
  añade `plugins.enabled`.
- **Lo que no se modifica:** la autenticación Nous, el modelo `poolside/laguna-s-2.1:free` y el
  proveedor. No se copian credenciales.

**Verificación en ejecución (plugin 0.4.0).** El hook `pre_api_request` escribe en
`hermes-tool-offers-*.jsonl` (esquema `tfg.hermes.tool-offer/1`), para cada petición:
- los **nombres** de las herramientas que lleva el body;
- el `tool_count` de Hermes.

No guarda descripciones, parámetros ni mensajes. Es un archivo aparte, así que el esquema de
eventos `/3` y los exportadores no cambian. Hermes descarta el valor de retorno de ese hook (hay un
test de contrato).

### Preflight offline (no crea nada)

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial
```

Resultado real del 22/10/2026: `ok: true`, con las 17 comprobaciones superadas. Además de las del
modo `catalog`, comprueba:
- las fuentes MCP fijadas;
- el servidor configurado como stdio de este repositorio, sin `lazy` y sin otro servidor MCP
  habilitado;
- que no hay ningún `tools.hermes_mcp_server` vivo;
- que el `run_id` neutro no se usa.

Datos del preflight:
- config `c99d1a88…`, que quedaría como `b7c9e418…` durante el turno;
- caché de esquemas MCP `d2168860…`.

### Ejecución (UNA vez, solo con autorización explícita)

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --private-dir <private_dir> --evidence-dir evaluation/observability/hermes_mcp_tool_trial_<etiqueta>
```

**Prompt fijo.** No se acepta otro:

> Llama una sola vez a la herramienta mcp__tfg_mission_control__get_mission_state con
> run_id="00000000-0000-4000-8000-000000000000" y view="summary". Después responde únicamente con
> el valor del campo status del resultado.

**Efectos esperados fuera del repositorio:**
- el directorio privado de captura;
- la sesión que Hermes guarda normalmente;
- Hermes arranca el servidor MCP por stdio, que importa los módulos del proyecto;
- Hermes reescribe su caché `~/.hermes/cache/mcp_schema_cache.json` con una entrada para la huella
  filtrada. Se registra su hash antes y después y no se restaura: con `lazy` desactivado no se lee.

Si al terminar queda vivo algún `tools.hermes_mcp_server`, se informa en
`mcp_server_processes_after` y nunca se le envía una señal.

### Criterios: cuatro preguntas separadas (`capture_summary.json` → `mcp_tool_trial`)

| Pregunta | Evidencia | Valor esperado |
| --- | --- | --- |
| ¿Qué se ofreció? | `tool_offer` (`pre_api_request`): nombres del body de cada petición | `ONLY_TRIAL_TOOL_OFFERED` (`[mcp__…get_mission_state]`, `tool_count` 1, en las dos peticiones) |
| ¿Qué pidió el modelo? | `llm_call.requested_tool_names` (`post_api_request`) | `TRIAL_TOOL_REQUESTED`, una sola vez |
| ¿Se ejecutó? | `tool_call` (`post_tool_call`, emitido tras despachar la llamada) | `EXECUTED_NO_ERROR_DETECTED_BY_HERMES`, un evento con `status=ok` |
| ¿Qué respondió? | stdout privado; solo se guarda su clasificación | `EQUALS_EXPECTED_STATUS` (`NOT_FOUND`) o `CONTAINS_EXPECTED_STATUS` |

**Veredicto esperado:** `TOOL_CALL_OBSERVED_AS_EXPECTED`, con dos `llm_call`: una pide la
herramienta y la otra da la respuesta final.

**Veredictos de fallo,** que no se convierten en éxito:

| Veredicto | Qué significa |
| --- | --- |
| `ISOLATION_NOT_CONFIRMED` | Se ofrecieron otras herramientas, ninguna (por ejemplo, si el descubrimiento MCP falló o superó sus 15 s) o no hay registro de oferta |
| `TOOL_NOT_REQUESTED` | El modelo respondió sin usar la herramienta, aunque diga `NOT_FOUND` |
| `REQUESTED_BUT_NOT_EXECUTED` | El modelo pidió la herramienta, pero no consta su ejecución |
| `TOOL_EXECUTION_FAILED_OR_BLOCKED` | La herramienta se ejecutó con error o fue bloqueada |
| `MORE_THAN_ONE_TOOL_CALL` | Hubo más de una llamada a la herramienta |
| `FINAL_RESPONSE_NOT_AS_EXPECTED` | La respuesta final no es la esperada |

**Límites:**
- `status=ok` solo significa que Hermes no detectó error. El resultado de la herramienta no se
  captura, por privacidad.
- Que la respuesta contenga `NOT_FOUND` es coherente con el resultado, pero no lo demuestra.
- La comparación con el informe nativo solo se hace con una llamada, así que aquí quedará como
  `not_compared…`.
- Un ensayo no mide fiabilidad ni rendimiento.
- El envío a Opik de esta captura sería otra acción con su propia autorización. El exportador
  ignora los archivos `hermes-tool-offers-*`.

## Recorrido 4: consulta de una misión histórica real (`--trial-case historical-passed`)

Usa el mismo aislamiento directo. `--trial-case not-found` sigue siendo el predeterminado y se
conserva como regresión.

- **Caso:** el preflight `467f7ec6-b2a6-4b68-9d97-766d85732f8e` del 18/10/2026, con trabajo
  `FINISHED`, informe `PASSED`, `v1` y 3/3 waypoints.
- **Archivos fijados:** el preflight bloquea si cambian `job.json`, `report.json`, `mission.json` o
  `input.json`, o si no registran `FINISHED`/`PASSED`. Son datos locales que Git ignora.
- **Expectativa:** `HISTORICAL_EXPECTED` es una lista explícita de 23 punteros del `summary` con sus
  valores registrados. Un test la contrasta con la salida real de la herramienta en local.
- **Comprobación del resultado:** la utilidad escribe la expectativa (0600) en el directorio privado
  y se la pasa al plugin, que compara el resultado real dentro de Hermes. La revisión la copia a la
  evidencia y exige que coincidan todos los punteros.
  - Si algún puntero no coincide: `TOOL_RESULT_CONTRADICTS_EXPECTATION`.
  - Si no hay registro, faltan campos o la expectativa no cargó: `TOOL_RESULT_NOT_VERIFIED`.
- **Privacidad:** el resultado que llega al proveedor contiene rutas absolutas con el usuario del
  sistema, y el pid y `boot_id` del worker. Joel aceptó ese envío de forma explícita antes del
  ensayo.
- **Ensayo real (17:22 UTC):** `TOOL_CALL_OBSERVED_AS_EXPECTED`, con comprobación del resultado
  23/23. Ver
  [hermes_mcp_tool_trial_historical_nous_2026_10_22](../evaluation/observability/hermes_mcp_tool_trial_historical_nous_2026_10_22/README.md).

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case historical-passed
```

## Recorrido 5: interpretación estructurada de varios campos (`--trial-case failed-structured`) — PREPARADO

- **Conjunto de casos:** `observability/mission_query_cases.py` recoge seis casos reales: misión
  superada, fallo de misión, bloqueo de admisión, infraestructura no lista, error de
  infraestructura o del ejecutor, e identificador inexistente. Las respuestas esperadas salen de
  los informes brutos; lo que no consta queda como `UNKNOWN`. `evaluate_answer` clasifica cada clave
  de la respuesta JSON de Hermes sin guardar sus valores.
- **Nueva vista `external` de `get_mission_state`:** es opcional (`view="external"`); la vista
  predeterminada sigue siendo `summary` por MCP y `detail` en Python. Es una lista explícita de
  campos con su tipo, sin rutas, pid, `boot_id`, `request_key`, motivos, logs ni coordenadas. Se
  construye sobre el `summary` sin modificar ningún informe.
- **Plugin 0.6.0:** compara además los argumentos de la llamada ejecutada (`run_id`, `view`), para
  verificar que la consulta que se ejecutó es la prevista.
- **Preparación:** en
  [hermes_mcp_structured_trial_prepared_2026_10_22](../evaluation/observability/hermes_mcp_structured_trial_prepared_2026_10_22/README.md)
  están el resultado exacto que recibirá el modelo, el prompt, la respuesta esperada y la
  expectativa. El preflight offline está en verde.
- **Ensayo real (17:40 UTC, una ejecución):** `FINAL_RESPONSE_NOT_AS_EXPECTED`.
  - Aislamiento, consulta ejecutada (argumentos) y resultado real (26/26): correctos.
  - Respuesta: 10/11 claves. `return_to_home` salió `invented_value`, con un valor concreto donde el
    registro tiene `null`.
  - La ambigüedad del contrato (el criterio `return_home_reached`) está documentada en
    [hermes_mcp_structured_trial_failed_nous_2026_10_22](../evaluation/observability/hermes_mcp_structured_trial_failed_nous_2026_10_22/README.md).
  - No se repite.

## Recorrido 6: contrato v2 y ensayo `failed-structured-v2` — PREPARADO (23/10/2026)

### Por qué falló el ensayo anterior y qué cambia

- **El fallo:** en la vista externa del esquema 1, `return_to_home: null` (dato del ejecutor) y
  `analysis_checks.return_home_reached: false` (criterio de aceptación) estaban al mismo nivel y con
  nombres casi iguales. El prompt no decía de qué campo salía cada clave, y el modelo respondió
  `return_to_home: false`.
- **El veredicto de aquel ensayo se mantiene:** `FINAL_RESPONSE_NOT_AS_EXPECTED`.
- **El caso `failed-structured` queda sustituido:** el preflight lo rechaza (`trial_case_current`),
  pero su expectativa conserva los mismos bytes (`ecb64f14…`) para poder revisar de nuevo su evidencia.

**Qué resuelve la v2:**

1. **Vista externa, esquema 2.** Cada preflight se divide en grupos:
   - `identity`, `record`, `admission_at_run` y `plan`;
   - **`executor_facts`**: lo que registró el ejecutor;
   - **`acceptance_criteria`**: aprobado o suspendido de las reglas de análisis, que **no** son hechos;
   - **`recovery_after_failure`**: el aterrizaje posterior a un fallo, separado del aterrizaje de la
     misión.

   `semantics` lo explica dentro del propio resultado. Sigue sin incluir rutas, pid, `boot_id`, logs
   ni la posición de recuperación.
2. **Contrato de respuesta.** `mission_query_cases.ANSWER_CONTRACT` asigna a cada una de las 11
   claves un único campo de origen, un tipo y una regla para `null`/ausente. Ninguna clave lee
   `acceptance_criteria`. Copia en
   [answer_contract.json](../evaluation/observability/hermes_mcp_structured_trial_v2_prepared_2026_10_23/answer_contract.json).
3. **Prompt v2.** Se genera desde el contrato: nombra el campo de origen de cada clave
   (`return_to_home` ← `preflights[0].executor_facts.return_to_home`) y prohíbe usar
   `acceptance_criteria`. **No contiene ningún valor esperado:** solo el `run_id` necesario para la
   consulta.
4. **Expectativa sobre el resultado real.** Son 29 punteros (`b48aa035…`). Comprueban que
   `executor_facts.return_to_home` es `null` y que la trampa sigue presente
   (`acceptance_criteria.checks.return_home_reached = false`). Con eso, si el modelo acierta, no será
   porque la trampa haya desaparecido.

**Respuesta esperada:** igual que en la v1, porque los datos no han cambiado. Sale del informe
bruto y se recalcula desde la copia versionada en Git. Aplicar el contrato a la vista real produce
lo mismo en los cinco casos reales.

**Preparación:**
[hermes_mcp_structured_trial_v2_prepared_2026_10_23](../evaluation/observability/hermes_mcp_structured_trial_v2_prepared_2026_10_23/README.md).
Preflight offline del 23/10 en verde; ejecutado una vez a las 08:42 UTC (resultado más abajo). Comando usado:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v2 --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --trial-case failed-structured-v2 --private-dir <private_dir> --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v2_nous_<fecha>
```

**Resultado real (23/10, 08:42 UTC, una ejecución):** `FINAL_RESPONSE_NOT_AS_EXPECTED`.
- Aislamiento, argumentos y resultado real (29/29): correctos.
- Respuesta: 10/11 claves. En `return_to_home` el modelo ya no dedujo `false`, pero copió el `null`
  de origen en lugar de `"UNKNOWN"`.
- La evidencia registra la etiqueta `invented_value`, que es inexacta. El evaluador distingue ahora
  `null_instead_of_unknown` para revisiones futuras.
- Ver
  [hermes_mcp_structured_trial_v2_nous_2026_10_23](../evaluation/observability/hermes_mcp_structured_trial_v2_nous_2026_10_23/README.md).
- No se repite.

### Evolución del contrato y ensayo final `failed-structured-v3` — PREPARADO (23/10/2026)

| Versión | Ensayo | `return_to_home` | Diagnóstico | Veredicto (no se modifica) |
| --- | --- | --- | --- | --- |
| v1 | 22/10, 17:40 | `false` | **confusión semántica**: lo tomó del criterio de aceptación `return_home_reached` | `FINAL_RESPONSE_NOT_AS_EXPECTED` |
| v2 | 23/10, 08:42 | `null` | **incumplimiento del formato exigido**: leyó el campo correcto, pero no escribió `"UNKNOWN"` | `FINAL_RESPONSE_NOT_AS_EXPECTED` |
| v3 | 23/10, 08:53 | no se probó | **contrato nullable** (decisión de Joel); el modelo **no llamó a la herramienta** y respondió sin consultar | `TOOL_NOT_REQUESTED` ([evidencia](../evaluation/observability/hermes_mcp_structured_trial_v3_nous_2026_10_23/README.md)) |
| v4 | 24/10, 07:08 | `null` (correcto) | mismo contrato v3, prompt breve con la llamada como paso 1, **sin forzarla**: llamada, argumentos, resultado (29/29) y respuesta (11/11) correctos | `TOOL_CALL_OBSERVED_AS_EXPECTED` ([evidencia](../evaluation/observability/hermes_mcp_structured_trial_v4_nous_2026_10_24/README.md)) |

**Contrato v3** (`mission_query_cases.ANSWER_CONTRACT_V3`, `NULLABLE_KEYS["v3"]`):
- `return_to_home` admite **solo** `true`, `false` o `null`. `null` significa "no consta" y una
  interfaz puede mostrarlo como «Desconocido».
- La clave debe estar presente: si falta, se clasifica como `missing`.
- `"UNKNOWN"`, `"false"`, `0` o `1` se clasifican como `wrong_type`. No se normaliza nada.
- El campo de origen sigue siendo solo `executor_facts.return_to_home`, nunca `acceptance_criteria`.
- **Las otras 10 claves conservan su regla v2** (`"UNKNOWN"`).
- El esquema JSON de la respuesta lo genera `answer_json_schema("v3")`.
- La v1 y la v2 se siguen evaluando con su propio contrato, así que sus veredictos no cambian.

**Fuentes del servidor:**
- `tools/mission_external_view.py` está ahora en `TRIAL_SERVER_SOURCES`: los próximos `run.json`
  registrarán su hash. Los anteriores no se modifican.
- El caso v3 además lo **fija** (`pinned_sources`, `EXTERNAL_VIEW_SHA256` = `394d0c19…`): si cambia,
  el preflight bloquea (`trial_server_sources_pinned`) antes de crear nada.
- `failed-structured-v2` queda sustituido (`trial_case_current`).

**Preparación:** en
[hermes_mcp_structured_trial_v3_prepared_2026_10_23](../evaluation/observability/hermes_mcp_structured_trial_v3_prepared_2026_10_23/SHA256SUMS)
están el prompt, la respuesta esperada (`return_to_home: null`), el contrato y el esquema.
- El resultado que recibirá el modelo y la expectativa (29 punteros más `run_id`/`view`,
  `b48aa035…`) son **idénticos byte a byte** a los de la
  [preparación v2](../evaluation/observability/hermes_mcp_structured_trial_v2_prepared_2026_10_23/README.md).
  Se comprobó al generarla y no se duplican.
- El prompt v3 cambia la línea de `return_to_home` ("true, false o null; escribe null, no el texto
  `UNKNOWN`; la clave debe aparecer siempre") y la excepción en la regla general. No contiene ningún
  valor esperado.
- Preflight offline del 23/10 en verde; ejecutado una vez a las 08:53 UTC (`TOOL_NOT_REQUESTED`, ver tabla). Comando usado:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v3 --execute
```

### Aceptación de un informe de misión y ensayo `failed-structured-v4` — PREPARADO (24/10/2026)

**Regla:** un informe solo se acepta si se observó **una** llamada correcta a la herramienta
prevista, con los argumentos previstos, si se tiene su resultado real y si la respuesta coincide
con ese resultado según el contrato. Lo siguiente **nunca** se acepta, aunque coincidan campos:

| Situación | Veredicto o motivo |
| --- | --- |
| Sin llamada a la herramienta | `TOOL_NOT_REQUESTED` / `NO_TOOL_EXECUTED` |
| Herramienta equivocada | `ISOLATION_NOT_CONFIRMED`, `TOOL_EXECUTION_FAILED_OR_BLOCKED` / `WRONG_TOOL` |
| Argumentos distintos de los previstos | `EXECUTED_QUERY_NOT_VERIFIED_AS_INTENDED` / `ARGUMENTS_NOT_AS_INTENDED` |
| Resultado no comprobado | `TOOL_RESULT_NOT_VERIFIED` / `RESULT_NOT_AVAILABLE` |
| Salida estructurada inválida | `FINAL_RESPONSE_NOT_AS_EXPECTED` / `ANSWER_NOT_VALID`, `ANSWER_NOT_PARSEABLE` |

**Dónde se aplica:**
- **Revisión del ensayo, offline:** `observability/hermes_capture_run.py:assess_tool_trial()`, sobre
  metadatos capturados. Es lo único que se ha aplicado hasta ahora.
- **Aplicación:** hasta ahora ningún componente del proyecto consumía la respuesta final de Hermes
  como informe, así que no había protección en esa ruta. Se ha preparado la función reutilizable
  `observability/mission_report_acceptance.py:validate_mission_report()`, que devuelve `VALIDATED`
  o `NOT_VALIDATED` con motivos. **No está conectada** a nada ni a controles de vehículos.
  - La alimentan llamadas **observadas por el entorno de ejecución**, nunca el texto del modelo.
  - Sin consulta válida, la respuesta solo se analiza (`NOT_COMPARED_NO_VALID_QUERY`), así que no
    puede validarse por coincidencia.
- **Punto de integración pendiente:** un plugin de Hermes en el mismo proceso.
  - Guardaría por `turn_id` lo que recibe `post_tool_call` (`tool_name`, `args`, `status`,
    `result`).
  - En `post_llm_call` (`assistant_response`, en `agent/turn_finalizer.py`) llamaría a
    `validate_mission_report`.
  - La futura interfaz mostraría la etiqueta. No está implementado.

**¿Se puede exigir la herramienta en Hermes `d923a5eb48`?** Hay que distinguir tres cosas:

1. **Qué herramientas están disponibles:** sí está soportado y se usa. Lo hacen
   `--toolsets tfg-mission-control`, `tools.include` y `tools.tool_search.enabled: "off"`.
2. **Obligar a llamar a una herramienta:** **no hay ninguna vía soportada** en esta ruta (oneshot,
   nous, `api_mode=chat_completions`).
   - `agent/transports/chat_completions.py` nunca fija `tool_choice`.
   - `hermes -z` no tiene opción para ello y la configuración no tiene clave para el agente principal.
   - `request_overrides`, que se fusiona en el nivel superior de la petición, solo procede de
     `custom_providers` (`hermes_cli/runtime_provider_custom.py`) o de `delegation`.
   - El transporte del subsistema rover fija `"auto"`.
   - Además, no está verificado que nous y el modelo admitan `tool_choice=required`.
   - Lo fijan un test de contrato y `TRIAL_SOURCES`: si esas fuentes cambian, el preflight bloquea.
3. **Validación posterior de la ejecución:** sí. La hacen el plugin (ofertas, argumentos y
   resultado) y `assess_tool_trial` / `validate_mission_report`.

**Cambio mínimo propuesto, sin implementar:** en la aplicación, que sea **ella** quien consulte
`get_mission_state` con el `run_id` y pase ese resultado al modelo, en lugar de depender de que el
modelo decida llamar.
- Eso hace la consulta obligatoria por diseño, sin `tool_choice` y sin reintentos.
- `validate_mission_report` seguiría comprobando la respuesta contra ese resultado.
- La alternativa sería una opción soportada en Hermes para fijar `tool_choice`, es decir, un cambio
  aguas arriba.
- No se ha monkeypatcheado nada ni se ha creado ningún proveedor.

**Ensayo v4, sin ejecutar** (`TRIAL_CASES["failed-structured-v4"]`, `tool_call_forced: False`):
- Mismo registro, la misma vista y la misma expectativa (`b48aa035…`, 29 punteros más los
  argumentos), contrato nullable v3 y fuente de la vista fijada.
- **No se fuerza la llamada:** si sale bien, demuestra la llamada autónoma más la interpretación;
  si el modelo no llama, el resultado es `TOOL_NOT_REQUESTED` y no se acepta.
- `failed-structured-v3` queda sustituido (`trial_case_current`), con sus bytes y su veredicto
  intactos.
- Preflight offline del 24/10 en verde; ejecutado una vez a las 07:08 UTC: `TOOL_CALL_OBSERVED_AS_EXPECTED` (ver la tabla de evolución). Contraste offline con `validate_mission_report` usando entradas reconstruidas: `VALIDATED`.
- Prompt breve (`FAILED_V4_PROMPT`, 885 caracteres frente a 1552 de la v3), sin ningún valor
  esperado:

```text
Paso 1: llama a mcp__tfg_mission_control__get_mission_state con run_id="d4519cab-ebd1-4359-b547-44be38294a6a" y view="external". No respondas antes de tener su resultado.
Paso 2: responde solo un objeto JSON con estas 11 claves, leídas de preflights[0] del resultado:
run_id, mission_id, vehicle_id, simulated_vehicle <- identity; historical_status <- record.result_status; planned_waypoint_ids <- plan.planned_waypoint_ids; reached_waypoint_ids, return_to_home <- executor_facts; mission_landed_event_recorded <- executor_facts.mission_landing_events (true si algún landed=true, false si está vacía); recovery_landing_completed <- recovery_after_failure.landing_completed; current_availability <- readiness_now ("UNKNOWN" si es UNKNOWN_NOT_CHECKED).
return_to_home es true, false o null (null si no consta). En las demás claves, "UNKNOWN" si no consta. Nunca uses acceptance_criteria.
```

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v4 --execute
```

**Funciones que controlan la aceptación, para seguirlas en VS Code:**
- **Ensayo:** `observability/hermes_capture_run.py`.
  - `assess_tool_trial()`: orden de los veredictos. Solo da `TOOL_CALL_OBSERVED_AS_EXPECTED` si se
    cumplen todas las condiciones.
  - `assess_result_checks()`: argumentos y resultado.
- **Respuesta:** `observability/mission_query_cases.py:evaluate_answer()` → `_field_outcome()`.
- **Aplicación:** `observability/mission_report_acceptance.py:validate_mission_report()` y
  `_result_document()`.
- **Tests:**
  - `tests/test_mission_report_acceptance.py`;
  - `tests/test_hermes_capture_run.py::test_no_accidental_field_match_turns_a_failed_check_into_success`;
  - `tests/test_hermes_capture_run.py::test_installed_hermes_offers_no_supported_forced_tool_call_on_this_route`.

### Ruta de aceptación de la aplicación (`tools/mission_report_query.py`) — 24/10/2026

La aplicación acepta un informe **solo con los datos reales de ese turno**, obtenidos por vías
soportadas de Hermes `d923a5eb48`, sin monkeypatches:

1. `hermes -z … --usage-file F` deja en `F` el `session_id` del turno.
2. `hermes sessions export - --session-id ID` devuelve los mensajes persistidos. El formato es JSONL
   y no se redacta salvo que se pida `--redact`. Contiene:
   - los `tool_calls` del asistente con sus **argumentos reales**;
   - cada mensaje `tool` con el contenido que Hermes añadió a la conversación (`api_content` cuando
     los bytes enviados a la API difieren);
   - la respuesta final.
3. `turn_from_session()` toma **solo el último turno de usuario**. Un resultado de una consulta
   anterior, o uno sin llamada asociada en este turno, no cuenta y se rechaza
   (`TOOL_RESULT_WITHOUT_CALL_IN_THIS_TURN`, `CONTRADICTORY_TOOL_RESULTS`).
4. `accept_session()` llama a `validate_mission_report()` con esas llamadas y esa respuesta.
   - Si es `VALIDATED`, devuelve el informe.
   - Si es `NOT_VALIDATED`, devuelve los motivos y `report: null`.
   - Siempre añade `scope`: registro histórico, `current_availability: NOT_CHECKED`,
     `operational_authorization: false`.

No se reconstruye nada desde expectativas ni se vuelve a consultar el registro. **El plugin sigue
siendo solo un observador:** sus hooks no deciden nada y la aceptación ocurre después del turno, en
la aplicación. Sin reintentos.

**Uso, en dos pasos** (el turno se ejecuta con el aislamiento ya versionado):

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case <caso> --execute
.venv/bin/python -m tools.mission_report_query accept --usage-file <private_dir>/native-usage.json --run-id <uuid>
```

- El segundo comando termina con rc 0 si el informe es `VALIDATED` y con rc 3 si no lo es. Una
  exportación imposible o ambigua da `TURN_DATA_UNAVAILABLE`.
- **Verificada sobre la sesión real de la v4 (24/10)**, sin nueva inferencia:
  - el primer intento dio `NOT_VALIDATED` (`RESULT_NOT_AVAILABLE`), porque Hermes envuelve los
    resultados MCP en `<untrusted_tool_result source=…>`;
  - se corrigió con `unwrap_untrusted()`, que solo acepta ese formato exacto y la misma fuente;
  - el segundo intento dio `VALIDATED` (11/11), coherente con el veredicto de la v4.
  - Ver [mission_report_acceptance_v4_session_2026_10_24](../evaluation/observability/mission_report_acceptance_v4_session_2026_10_24/README.md).
  - Esto acredita la aceptación de una sesión real **ya terminada**, no una consulta genérica integrada.

**Consulta histórica genérica (una sola orden):**

```bash
.venv/bin/python -m tools.mission_report_query ask --run-id <uuid>            # solo preflight offline
.venv/bin/python -m tools.mission_report_query ask --run-id <uuid> --execute  # UNA invocación real + aceptación
```

- **Comprobaciones previas:** `run_id` canónico y existente (`trial_run_exists`).
- **Aislamiento reutilizado sin duplicar:** `hermes_capture_run.register_query_case()` y `execute_capture()`:
  - solo `get_mission_state`, con `view="external"` en el prompt (`query_prompt()`, la redacción de la v4);
  - Tool Search desactivado y fuente de la vista fijada;
  - autenticación y modelo habituales;
  - una sola invocación y config restaurado.
- **Aceptación:** `mission_report_query.accept_turn()` usa el `native-usage.json` de **esa misma**
  invocación.
- **Resultados de rechazo, sin reintentos:**
  - turno fallido o con timeout: `HERMES_TURN_FAILED`;
  - restauración incompleta: `CONFIG_OR_PLUGIN_RESTORE_INCOMPLETE`, sin exportar nada;
  - preflight rechazado: `PREFLIGHT_REFUSED`.
- No hay expectativa fija del resultado: la respuesta se compara con el resultado real de ese turno.
- **No debe ejecutarse `hermes -z` sin este aislamiento**, porque ofrecería también las herramientas de control.

**Ejecución real del 24/10 a las 07:35 UTC** (una vez, autorizada): **la orden falló sin emitir
veredicto** (rc=1).
- **Recorrido:** `main()` → `ask()` → `register_query_case()` → `execute_capture()`, con una
  invocación aislada y la restauración correcta → `accept_turn()` → `export_session()` →
  `turn_from_session()`. Esta última tomó la sesión de **esta** invocación, con un único turno, la
  llamada correcta, `run_id` y `view` reales correctos y el resultado presente →
  `validate_mission_report()`.
- **Dónde falló:** en `accept_session()`, la construcción del informe con `json.loads` lanzó
  `JSONDecodeError`, porque la respuesta venía en un bloque ```json. `parse_answer()` sí admite ese
  bloque, y la validación ya había llegado a `VALIDATED` (inferido del código, no emitido).
- **Estado:** ese resultado se conserva sin cambios. Evidencia:
  [mission_report_ask_integrated_2026_10_24](../evaluation/observability/mission_report_ask_integrated_2026_10_24/README.md).
- **Corrección, autorizada después:**
  - `accept_session()` lee la respuesta **una sola vez** con `parse_answer()` y usa ese mismo
    objeto para validar y como informe;
  - `validate_mission_report(parsed_answer=…)` y `mission_query_cases.evaluate_parsed()` reciben
    ya interpretada la respuesta;
  - regresiones por la entrada pública (JSON limpio y en bloque dan el mismo informe; una respuesta
    ilegible da `NOT_VALIDATED`, `report: null` y `ANSWER_NOT_PARSEABLE`) y un recorrido `ask`
    completo con dobles.
- **`accept` sobre la sesión real de ese `ask`, sin inferencia: `VALIDATED`** (11/11, respuesta en
  bloque). Ver
  [mission_report_accept_recheck_2026_10_24](../evaluation/observability/mission_report_accept_recheck_2026_10_24/README.md).
  **El `ask` corregido todavía no se ha ejecutado con una nueva inferencia real.**
- **Qué significa `VALIDATED` cuando se emita:** hubo una única llamada observada a la herramienta
  prevista, con los argumentos previstos y un resultado utilizable de ese mismo turno, y la
  respuesta coincide con ese resultado según el contrato v3. Se refiere solo al registro histórico:
  **no** acredita la disponibilidad actual ni concede autorización operativa.

**Para entender cómo se acepta o rechaza una respuesta, por este orden:**
1. `tools/mission_report_query.py`:
   - `main()`: subcomandos `accept` y `ask`;
   - `ask()`: una invocación aislada y luego `accept_turn()` sobre esa misma sesión;
   - `session_id_from_usage()` y `export_session()`;
   - `turn_from_session()`: qué llamadas y qué respuesta cuentan;
   - `unwrap_untrusted()`: el envoltorio `untrusted_tool_result` de Hermes;
   - `accept_session()`.
2. `observability/mission_report_acceptance.py:validate_mission_report()`: motivos de rechazo de
   la llamada, de los argumentos y del resultado; `_result_document()`.
3. `observability/mission_query_cases.py`:
   - `answer_from_external_view()`: qué debe decir la respuesta según el resultado real;
   - `evaluate_answer()` y `_field_outcome()`: clasificación por clave y `null` frente a `false`.
4. `tools/mission_external_view.py:external_mission_state()`: qué recibe el modelo.
5. Tests: `tests/test_mission_report_query.py` (ruta completa con un doble de la CLI) y
   `tests/test_mission_report_acceptance.py`.

### Cómo seguir el código en VS Code

**1. Preparación del turno**
- `observability/hermes_capture_run.py`:
  - `preflight()` hace todas las comprobaciones de solo lectura.
  - `tool_trial_config_text()` combina tres ediciones temporales del config:
    - `restrict_mcp_text()`: `include: [get_mission_state]`;
    - `disable_tool_search_text()`: `tools.tool_search.enabled: "off"`;
    - `enable_plugin_text()`: activa el plugin.
  - `execute_capture()` escribe `result-expectation.json` (generado por `expectation_bytes()`),
    lanza **una vez** `hermes -z <prompt> --toolsets tfg-mission-control` y restaura el config con
    `restore()`.
- Los casos están en `TRIAL_CASES`. El actual es `failed-structured-v3`: prompt `FAILED_V3_PROMPT`,
  respuesta `FAILED_ANSWER_V3`, `answer_contract: "v3"`, expectativa `FAILED_V2_EXPECTED` (la misma
  vista) y `pinned_sources`. En `preflight()`, las comprobaciones `trial_case_current` y
  `trial_server_sources_pinned` bloquean antes de crear nada.

**2. Hermes → MCP**
- Hermes registra solo la herramienta incluida, como `mcp__tfg_mission_control__get_mission_state`,
  y la ofrece sin el puente Tool Search.
- Cuando el modelo la pide, Hermes la despacha por stdio al servidor del proyecto.

**3. Servidor MCP → herramienta**
- `tools/hermes_mcp_server.py`: `get_mission_state()`, alrededor de la línea 294; `view` acepta
  `summary` (predeterminada), `detail` y `external`.
- La llamada pasa a `tools/mission_state.py:get_mission_state()`, alrededor de la línea 189.
- `_get_mission_state_detail()` lee y verifica los archivos de la ejecución en solo lectura.

**4. Dónde se reduce el resultado para el proveedor**
- `tools/mission_state.py`: con `view == "external"`, alrededor de la línea 203.
- Primero pasa por `tools/mission_response_views.py:summarize_mission_state()` y
  `summarize_preflight()`, que derivan de los eventos los waypoints alcanzados y los `LANDED`.
- Después, `tools/mission_external_view.py:external_mission_state()` aplica la lista `_GROUPS`, con
  un tipo por campo. Lo rechazado va a `null` y se anota en `rejected_fields`.
- Los informes originales no se modifican.

**5. Dónde se comprueban argumentos, resultado y respuesta**
- **Dentro de Hermes**, `observability/hermes_capture/capture.py`:
  - `on_pre_api_request` / `tool_offer_event()` registran las herramientas ofrecidas en cada
    petición;
  - `_requested_tool_names()` registra lo que pidió el modelo;
  - `on_post_tool_call`, con `tool_call_event()` y `result_check_event()`, registra la ejecución y
    compara **en memoria** los argumentos reales (`run_id`, `view`) y los punteros del resultado
    real. Solo guarda `match`, `mismatch` o `absent`.
- **En la revisión**, `observability/hermes_capture_run.py`:
  - `review()` valida y copia la evidencia;
  - `assess_result_checks()` clasifica los argumentos y el resultado;
  - `assess_tool_trial()` da el veredicto y exige que coincidan todos. `status=ok` nunca basta.
- **Respuesta final**, `observability/mission_query_cases.py`:
  - `parse_answer()` y `evaluate_answer(text, expected, contract)` clasifican cada clave sin guardar
    valores; `_field_outcome()` aplica la regla de la clave (`nullable` para `return_to_home` en
    v3);
  - lo esperado sale de `expected_answer_from_report(report, contract)`, aplicada al informe bruto;
  - `answer_from_external_view(view, contract)` aplica el contrato a la vista (para los tests);
  - `answer_json_schema(contract)` genera el esquema JSON de la respuesta;
  - `hermes_capture_run.assess_tool_trial()` pasa el `answer_contract` del caso a
    `evaluate_answer`.

## Pruebas

`tests/test_hermes_capture_run.py` tiene 73 tests offline (los del caso histórico usan un DOBLE de Hermes y archivos de ejecución sustitutos; uno contrasta la expectativa con la salida real local). Tras el ensayo de las 16:40 se
añadieron:
- Tool Search desactivado como cadena;
- conservación de claves `tools` y `tool_search` existentes;
- rechazo de valores previos, formas inline o duplicadas;
- composición exacta de las tres ediciones;
- restauración tras error y timeout;
- edición concurrente no sobrescrita;
- comparación de varias llamadas con el informe nativo.

Los del ensayo MCP usan un DOBLE de
Hermes y un repositorio temporal:
- argv con `--toolsets tfg-mission-control` y prompt fijo;
- filtro presente solo durante el turno y restauración byte a byte;
- 7 bloqueos de preflight: otro servidor, `lazy`, filtro previo, servidor deshabilitado o
  distinto, `run_id` usado en un trabajo y `run_id` usado en un informe;
- proceso MCP vivo, prompt distinto y fuentes no fijadas;
- 10 veredictos de evaluación sobre eventos SINTÉTICOS;
- la clasificación de solo lectura con audit hook;
- que el modo `catalog` no cambia.

`tests/test_hermes_observability_capture.py` comprueba que el registro `tool_offer` guarda solo
nombres y número de herramientas. También distingue "sin herramientas" de "desconocido", redacta
nombres sospechosos y verifica el contrato de `pre_api_request` contra las fuentes instaladas.

**Con un DOBLE de Hermes** (tests `test_DOUBLE_*`, un ejecutable Python falso, nunca Hermes real):

- éxito, comprobando que el plugin estaba habilitado e instalado durante el turno, con una sola
  invocación y restauración byte a byte;
- timeout que mata el grupo de procesos;
- error de Hermes;
- edición concurrente del config (no se pisa y se conserva la copia);
- fallo de restauración (se informa y no se lanza excepción);
- 5 comprobaciones previas que fallan sin crear nada;
- otro proceso Hermes visible;
- `capture` sin `--execute`, que no ejecuta nada.

**Con copias temporales de la captura real:** revisión, privacidad (`session_id` y rutas fuera),
filtración de contenido, procedencia ausente y dry-run reproducible sin red ni clave. Una
regresión recorre captura → dry-run → `opik_dry_run.json` → lectura → `body_bytes` y comprueba
que los bytes de los batches de trazas y spans son idénticos a los que recibe un transporte falso
del exportador. Comprueba también que el orden de claves anidadas importa. Los originales y sus
manifiestos se comprueban intactos.

Mutaciones detectadas:

- restauración que pisa una edición concurrente: 1 test falla;
- reintento añadido: 3 tests fallan;
- guardar `opik_dry_run.json` con `sort_keys` (el formato anterior al 22/10): falla la regresión
  de bytes;
- informe nativo sin lista permitida: 1 test falla.

## Pendiente

- Volver a verificar la selección de herramientas y MCP si Hermes se actualiza; la utilidad lo
  bloquea hasta entonces.
- Capturar el título auxiliar exigiría registrar `pre/post_auxiliary_call`. Es una decisión
  aparte, con su propio análisis de privacidad.
- No hay ledger entre envíos a Opik: **no reenviar** capturas ya enviadas.
