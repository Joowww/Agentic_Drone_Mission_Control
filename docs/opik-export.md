# Exportador a Opik (dry-run por defecto, envío explícito)

Fecha: 21/10/2026. **Implementado y probado offline.** La ruta `--send` se ha ejecutado **tres
veces**, cada una con autorización explícita y lanzada por Joel. El detalle está en
[Evidencia existente](#evidencia-existente-y-lo-que-falta).

1. Fixture sintético: **HTTP 400** en el batch de trazas.
2. Diagnóstico sintético de un batch: **204**, y Joel ve la traza en la interfaz.
3. **Captura real de Hermes** (nous / laguna): **204 + 204**, y Joel ve la traza y el span con los
   datos esperados.

No es un baseline de rendimiento ni de gasto.

Código: [observability/opik_export.py](../observability/opik_export.py) ·
tests: [test_opik_export.py](../tests/test_opik_export.py) ·
datos de origen: [captura local de Hermes](hermes-observability-capture.md) ·
reglas compartidas con el [exportador LangSmith](langsmith-export.md).

## Contrato y verificación

- **SDK:** `opik` no está en la `.venv` ni es dependencia del exportador. El 21/10/2026 el payload
  se validó offline contra **`opik==2.2.110`**, instalado en un venv desechable fuera del repo:
  modelos REST `TraceWrite`/`SpanWrite`/`ErrorInfoWrite`, claves desconocidas, ids v7, lotes de
  1-1000, cliente REST con `httpx.MockTransport` y la ruta propia del SDK (mensajes → batchers).
  Sin discrepancias; la única diferencia es el `source: "sdk"` opcional que añade el SDK. Evidencia,
  límites y cómo reproducirlo en [opik_sdk_offline_validation_2026_10_21](../evaluation/observability/opik_sdk_offline_validation_2026_10_21/README.md).
  **No está verificado contra un servicio de Opik**: cada salida del dry-run lo declara en
  `verification` (`UNVERIFIED_AGAINST_OPIK_SERVICE…`).
- **Forma del payload:** sigue la especificación OpenAPI oficial de la que se genera la referencia
  REST: `sdks/code_generation/fern/openapi/openapi.yaml` de `comet-ml/opik`, commit
  `6ff71e236532d122f7fb657fae7131ac337f9478` (20/10/2026, sha256 del fichero `ea2f109f…0422`),
  revisada el 21/10/2026. `POST /v1/private/traces/batch` recibe `TraceBatch_Write`
  (`{"traces": [Trace_Write]}`) y `POST /v1/private/spans/batch` recibe `SpanBatch_Write`
  (`{"spans": [Span_Write]}`). Sólo `start_time` es obligatorio. El `type` del span es `general`,
  `tool`, `llm` o `guardrail`, y `error_info` exige `exception_type` y `traceback` (ambos `minLength: 1`).
- **Tamaño de lote:** `TraceBatch_Write.traces` y `SpanBatch_Write.spans` tienen `minItems: 1` y
  `maxItems: 1000`. El dry-run devuelve `payload.traces_batches` y `payload.spans_batches` como
  listas de bodies de 1 a 1000 elementos; sin trazas o sin spans la lista queda vacía en lugar de
  emitir un body vacío. Antes (21/10/2026) se emitía siempre un único body, vacío cuando todas las
  trazas se retenían o sólo había trazas `interval-unknown`, y sin trocear por encima de 1000.
- **Coste:** según la página *Cost tracking*, Opik calcula el coste automáticamente para spans
  `llm` con `provider`, `model` y `usage`. Por eso los spans **no** llevan `usage`, `model`,
  `provider`, `total_estimated_cost` ni `ttft` de primer nivel. Todo va en `metadata` como `tfg_*`.
- **Formato de ids:** la especificación revisada sólo declara `format: uuid`, sin fijar versión. Por
  prudencia, los ids usan la disposición UUIDv7: los 48 bits de tiempo son el inicio en ms y el
  resto procede de un SHA-256 del exportador, el destino y el evento. Son deterministas, distintos
  por proyecto y workspace, y distintos de los ids de LangSmith. El SDK 2.2.110 sí documenta que
  un id dado por el usuario "Must be a valid UUIDv7 ID" (`Opik.trace()`/`Opik.span()`). No se ha
  verificado que el servidor acepte ids v7 con bits derivados de un hash.

## Reglas reutilizadas (exportador LangSmith v4)

- **Validación:** se reutilizan `load_events` (JSON, esquema `tfg.hermes.capture/3`, `recorded_at_utc`
  con zona horaria y sin duplicados) y la defensa contra textos con aspecto de URL o secreto.
- **Procedencia:** `--provenance captured` sólo se acepta con registros del sink que verifican,
  `--provenance synthetic` marca los datos como sintéticos, y sin declaración la procedencia es
  desconocida. Las marcas `synthetic` en los ids sólo hacen más conservadora la clasificación y
  contradicen una declaración `captured`. Los nombres de `run_id`/`case_id` nunca hacen real una captura.
- **Bloqueos de envío:** `check_export_allowed` exige autorización explícita
  (`--allow-synthetic`, `--allow-unknown-provenance`) para trazas `synthetic_fixture` y
  `unknown_provenance`. Con `--send`, `main()` la aplica antes de leer la API key. `send()` recibe
  la clave ya leída como argumento y vuelve a aplicar la puerta antes de crear el registro o
  conectar. El dry-run informa del
  bloqueo en `blocked_for_future_send_by_default` y no envía nada. También cuentan las trazas retenidas por
  no tener intervalo medido. Si todas se retienen, el plan no queda permitido y el motivo dice
  `(in withheld traces)`. Hasta el 21/10/2026 la puerta sólo miraba las trazas emitidas, y una
  entrada sintética o desconocida con todas sus trazas retenidas salía como permitida y sin bloqueo
  en el resumen. Los contadores `synthetic_traces`/`unknown_provenance_traces` siguen contando sólo
  las trazas emitidas; la procedencia de las retenidas está en `withheld_traces[].kind`.
- **Tiempos:**
  - spans `llm` sólo con los epochs de Hermes;
  - intervalo de la traza derivado únicamente de esos spans, nunca mezclado con `recorded_at`;
  - herramientas y eventos sin intervalo en `metadata.tfg_point_events` (nombre, hora de captura
    y metadatos), sin span ni duración;
  - trazas sin ningún intervalo medido retenidas, salvo `--include-untimed` (marcador `interval-unknown`).
- **Contenido:** sin `input`/`output`, prompts, respuestas, argumentos, resultados, rutas, ids en
  claro ni secretos. Los tokens conservan `{value, status}`: ceros sin confirmar, valores derivados
  y `usage=null` cuando no hay uso.

## Uso

```bash
# Dry-run (predeterminado): offline, sin variables de entorno ni archivos.
.venv/bin/python -m observability.opik_export CAPTURE.jsonl --project NOMBRE \
    [--workspace ETIQUETA] [--provenance synthetic|captured] [--include-untimed]

# Envío explícito (NO ejecutado hasta ahora). OPIK_API_KEY sólo se lee aquí.
.venv/bin/python -m observability.opik_export CAPTURE.jsonl --project NOMBRE \
    --workspace WORKSPACE --send --record NUEVO-registro.jsonl \
    [--provenance captured] [--endpoint https://…/api] [--timeout 30] \
    [--allow-synthetic] [--allow-unknown-provenance] [--error-body-file NUEVO-cuerpo-error.bin]
```

El dry-run no importa ningún SDK, no lee variables de entorno, no abre conexiones ni escribe ningún
archivo. Devuelve rc=1 si hay líneas inválidas. `--record`, `--endpoint`, `--timeout` y los
`--allow-*` sin `--send` son un error de argumentos.

Los ids incluyen el workspace. Para ver exactamente lo que se enviaría, el dry-run debe usar el
mismo `--workspace` que el envío.

## Envío explícito (`--send`)

**Contrato de conexión.** Las fuentes son la especificación OpenAPI fijada arriba (`servers[0]` e
`info.description`) y el código de `opik==2.2.110` (`OPIK_URL_CLOUD`, `client_wrapper.get_headers`):

- Endpoint Cloud por defecto: `https://www.comet.com/opik/api`. Se le añade
  `/v1/private/traces/batch` o `/v1/private/spans/batch`.
- Cabeceras: `Comet-Workspace: <workspace>` y `authorization: <api-key>` **sin** `Bearer`.
- Otro despliegue se indica con `--endpoint`, que tiene que ser `https`, sin credenciales, query ni
  fragmento.
- El SDK puede deducir la URL del despliegue a partir de una API key en formato extendido (con
  `*` y base64). El exportador **no** decodifica claves: con una clave así exige `--endpoint`
  explícito.

**Orden de las comprobaciones.** Si alguna falla, no hay conexión ni se crea el registro.

`main()` comprueba, **antes de leer `OPIK_API_KEY`**:

1. `--workspace` explícito, `--record` presente y `--timeout` en (0, 120] s (por defecto 30 s);
2. endpoint válido;
3. entrada sin errores de validación;
4. puerta de procedencia, que incluye las trazas retenidas;
5. bodies de 1-1000 elementos y como mucho 5 MB serializados. 5 MB es el `MAX_BATCH_SIZE_MB` del
   SDK; el límite del servidor no está documentado. Si no hay ningún body, el resultado es
   `NOTHING_TO_SEND` y no se lee la clave ni se conecta;
6. `--record` no existe todavía.

Después lee la clave y llama a `send()`.

`send()` no depende de esas comprobaciones de `main()`. Recibe la clave ya proporcionada y, antes
de crear el registro o conectar, vuelve a comprobar:

- la puerta de procedencia;
- la coherencia entre destino y payload: workspace explícito, destino reconstruible con
  `make_destination`, `project_name` igual al del destino en todas las trazas y spans, ids UUIDv7
  canónicos y sin repetir, procedencia registrada exactamente para las trazas del plan, y spans
  cuya traza está en el plan;
- que cada id se derive del destino **actual**. `build_plan` guarda en `plan.id_scopes` (no se
  envía) el ámbito de cada id: `trace|…` con run/session/turn o el evento, y `span|<event_id>`.
  `send()` recalcula `deterministic_uuid7(clave del destino, ámbito, start_time)` y exige que
  coincida. Un plan construido para un workspace o proyecto y redirigido después a otro destino
  válido conserva los ids antiguos y se rechaza; hay que reconstruirlo. También se rechazan un
  ámbito ausente o de otro tipo y un `start_time` alterado;
- el endpoint (`validate_endpoint`);
- el timeout: número finito en (0, 120];
- la clave: presente, en una sola línea y, si tiene formato extendido, acompañada de un endpoint
  distinto del de Cloud;
- los bodies.

Si el registro ya existe o no se puede crear, no se envía nada.

**Envío.**

- Un POST por body, primero todas las trazas y después los spans, con `urllib` de la biblioteca
  estándar (sin SDK).
- Sin reintentos y sin seguir redirecciones, que podrían llevar la cabecera con la clave a otro
  host; un 3xx se registra como respuesta.
- Sin proxies de entorno y con la verificación TLS por defecto.
- Se detiene en el primer batch que no recibe un 2xx.

**Registro (`--record`).** Es un JSONL creado en exclusiva (si ya existe, el envío se rechaza) y
con `fsync` tras cada línea:

- `send_started`;
- `batch_intent` **antes** de cada POST: índice, tipo, ruta, número de elementos, primer y último
  id, bytes y SHA-256 del body;
- `batch_result` después: clasificación fija (`http_accepted`, `http_not_accepted`,
  `no_response_delivery_unknown` o `invalid_transport_response_delivery_unknown`), código HTTP,
  bytes de la respuesta y duración de pared. Si hubo excepción, sólo su tipo, y únicamente si es un
  identificador de 1-64 caracteres; si no, `unrecognized`;
- `send_finished`.

**Nada del texto que envía el servidor se registra ni se muestra**: ni la razón HTTP, ni cabeceras,
ni cuerpo, ni mensajes de excepción. Sólo se aceptan un código entero entre 100 y 599 y un recuento
de bytes; cualquier otra respuesta del transporte se clasifica como inválida. La clave no aparece
en el registro ni en la salida. La salida JSON repite el resultado de cada batch. La única excepción
es la opción explícita `--error-body-file` (siguiente apartado), y ni siquiera ella lleva texto del
servidor a la salida o al registro.

**Cuerpo de error opcional (`--error-body-file PATH`).** Por defecto no está activo y el
comportamiento no cambia. Sólo es válido con `--send`.

- **Antes de leer la clave**, `main()` exige que `PATH` no exista, que su directorio exista y que no
  coincida con `--record`. `send()` repite la misma comprobación antes de crear el registro.
- Ante la **primera** respuesta HTTP no 2xx (el envío se detiene ahí), se guardan como mucho los
  primeros **4096 bytes** del cuerpo en un archivo **nuevo**: `O_CREAT|O_EXCL|O_NOFOLLOW`, permisos
  **0600** y `fsync`. Nunca se sobrescribe un archivo existente ni se sigue un symlink, aunque
  aparezca entre la comprobación y la escritura.
- **Lectura acotada:** ante una respuesta no 2xx, el transporte urllib hace **una sola lectura de
  como mucho 4097 bytes** (nunca `read()` sin límite). Conserva los primeros 4096 e informa
  `response_body_bytes_captured` y `response_body_truncated`. `response_body_bytes` (el total)
  sólo se da cuando la lectura terminó antes del límite; si se truncó, el total es desconocido y
  queda `null`. Un fallo de lectura o de cierre del flujo conserva el código HTTP (el batch sigue
  `http_not_accepted` y el envío `UNCERTAIN`) y deja sólo el tipo de error
  (`response_body_read_error`, `response_body_close_error`), nunca su mensaje. De las respuestas
  2xx no se conserva el cuerpo, pero sus bytes se cuentan con una lectura **sin límite**. Es un
  límite conocido; la especificación documenta 204, que no lleva cuerpo. Sin redirecciones y sin
  reintentos.
- La salida y el `batch_result` del registro reciben sólo metadatos en `error_body_file`: estado,
  bytes guardados, tamaño de la respuesta, `truncated`, SHA-256 del prefijo guardado y, si falló, el
  tipo de error. **Nunca el texto**, que tampoco va a stderr.
- Estados posibles:
  - `saved`;
  - `no_body_received`: respuesta no 2xx sin cuerpo; no se crea archivo;
  - `not_needed_no_non_2xx_response`;
  - `failed_not_created`: por ejemplo, el archivo apareció entretanto;
  - `failed_partial_file_may_exist`: fallo de `write`, `fsync` o `close`, o una escritura que no
    avanza (0 bytes), con el archivo ya creado. Ninguno de esos fallos escapa como excepción ni
    deja el envío colgado.

  Un fallo al guardar el cuerpo no cambia el estado del envío (sigue `UNCERTAIN` por el no-2xx) ni
  el registro.

**Advertencia:** el archivo contiene **texto arbitrario del servidor**. Puede repetir partes del
payload o incluir datos de la cuenta o el workspace. Hay que revisarlo localmente antes de citarlo,
**no añadirlo a Git** y no compartirlo sin inspección. Si se convierte en evidencia, conviene
conservar sólo un extracto revisado junto con el SHA-256 del informe.

**Fallos del propio registro** (escritura o `fsync`). Nunca escapan como excepción y la salida los
indica con `record_complete: false` y `record_failure` (etapa y tipo de error):

- **al registrar `send_started` o un `batch_intent`:** ese batch **no se envía** y el envío se
  detiene. Si no se había enviado nada, el estado es `NOT_SENT`; si había batches anteriores
  aceptados, `UNCERTAIN` (envío parcial);
- **al registrar `batch_result` tras un POST:** el estado es `UNCERTAIN`
  (`record_unwritable_after_post`), el envío se detiene y no hay reintento. El resultado de ese
  batch sólo figura en la salida, con `recorded: false`; el registro no lo contiene, o puede tener
  una línea sin `fsync` confirmado;
- **al registrar `send_finished` o al cerrar el registro:** si todos los POST habían recibido 2xx,
  el estado agregado pasa a `UNCERTAIN`, con `record_send_finished_failed_after_all_batches_http_accepted`
  o `record_close_failed_after_all_batches_http_accepted`, y rc=2. Nunca queda como
  `ALL_BATCHES_HTTP_ACCEPTED`, porque el registro durable no confirma ese cierre. Si el estado ya
  era más débil (por ejemplo `http_status_500`), se conserva tal cual. No se reintenta nada.

Los códigos HTTP realmente recibidos se conservan aparte del estado agregado, en
`batches[].http_status`, `http_statuses_received` y `http_accepted_batches`. Un fallo del registro
no los borra ni los convierte en más fuertes. Tras un fallo del registro no se escriben más
entradas en él.

**Estados.**

| Estado | Significado y límite |
|---|---|
| `ALL_BATCHES_HTTP_ACCEPTED` (rc=0) | Todos los POST recibieron 2xx (la especificación documenta 204) **y** el registro se completó y cerró sin error. No prueba que Opik los haya almacenado ni que la entrega haya sido exactamente una vez. |
| `UNCERTAIN`, `record_{send_finished,close}_failed_after_all_batches_http_accepted` | Todos los POST recibieron 2xx, pero el registro durable no pudo finalizarse o cerrarse. |
| `NOT_SENT` (rc=2) | El registro no pudo escribirse antes del primer POST; no se envió nada. |
| `UNCERTAIN`, `record_unwritable_after_post` | El POST se hizo, pero su resultado no pudo registrarse de forma durable. |
| `UNCERTAIN`, `record_unwritable_batch_not_sent_after_earlier_accepted_batches` | Ese batch no se envió; los anteriores sí. |
| `UNCERTAIN` (rc=2), `no_response_after_sending` | Timeout, conexión cortada o respuesta perdida: el batch pudo aplicarse o no (`no_response_delivery_unknown`). |
| `UNCERTAIN`, `http_status_<código>` | El servidor respondió sin 2xx. Puede haber procesado parte del batch; no se sabe. |
| `…_after_earlier_accepted_batches` | Envío parcial: los batches anteriores recibieron 2xx y siguen enviados (por ejemplo, trazas sin sus spans). |
| `NOTHING_TO_SEND` (rc=0) | Sin bodies. No hubo conexión ni se leyó la clave. |

**Nada se reenvía automáticamente.** Tras un `UNCERTAIN`, el registro indica qué batch se intentó y
cuáles no. Reenviar es una decisión manual y requiere un registro nuevo. Los ids son deterministas,
pero no se ha verificado cómo trata Opik un id repetido (rechazo, sobrescritura o duplicado). No hay
ledger entre ejecuciones: otra ejecución con otro `--record` volvería a enviar todo.

**Sin comprobar contra el servicio:**

- que Opik Cloud acepte estas peticiones y cabeceras;
- que cree el proyecto automáticamente;
- los códigos de respuesta reales, salvo el 204 documentado;
- cuotas, límites de tamaño y comportamiento ante ids repetidos;
- si una petición rechazada puede quedar aplicada en parte.

El campo `tfg_exporter` sigue siendo `tfg-opik-offline`, porque forma parte de la semilla de los
ids; cambiarlo cambiaría todos los ids.

## Pruebas offline

`tests/test_opik_export.py` (123 tests). Cubren:
- **lectura acotada del cuerpo de error:** un flujo falso que falla ante cualquier `read()` sin
  límite o de más de 4097 bytes. Casos: cuerpo vacío, 57 bytes, exactamente 4096, 4097 y 1 MiB,
  con una sola lectura y el flujo cerrado, y el total sólo cuando se conoce. Además, fallo de
  lectura (se conserva el código HTTP) y fallo de cierre. De extremo a extremo con `main()` y el
  transporte urllib real sobre un opener falso: `UNCERTAIN`, un solo POST, sin reintentos, y el
  cuerpo ausente de stdout, stderr, informe y registro;
- **texto del servidor:** un transporte que devuelve un centinela sensible en la razón, las
  cabeceras, el cuerpo, el mensaje de excepción y un estado no entero. El centinela no aparece en
  la salida ni en el registro, y cada batch sólo tiene campos acotados. El transporte urllib real,
  con un opener falso, devuelve código y tamaño, y sólo ante un `HTTPError` un prefijo del cuerpo de
  como mucho 4096 bytes; nunca la razón ni las cabeceras;
- **`--error-body-file`**, con transporte falso:
  - cuerpo guardado en un archivo 0600 y ausente de stdout, stderr, informe y registro;
  - truncado a 4096 bytes;
  - sin cuerpo o con todos los batches aceptados, no se crea archivo;
  - sin la opción, el cuerpo no se escribe ni se informa;
  - un archivo preexistente se rechaza antes de leer la clave o crear el registro;
  - un archivo que aparece entretanto o un symlink no se sobrescriben ni se siguen;
  - fallos de escritura, `fsync` y `close`, y una escritura de 0 bytes, conservan `UNCERTAIN`
    sin mostrar el cuerpo ni colgarse. El de `close` y el de 0 bytes eran defectos reales:
    antes escapaba un `OSError` o el bucle no terminaba;
  - permisos 0600 también con `umask 0`;
  - opción rechazada sin `--send`, y ruta validada por el propio `send()`;
  - una única llamada al transporte, sin reintentos;
- **fallos del registro:** `fsync` fallando en cada una de las 6 escrituras, `write` fallando tras
  un POST y `close()` fallando tras todos los POST:
  - ninguna excepción escapa;
  - no se envía el batch sin intención registrada;
  - tras un POST, el estado es `UNCERTAIN`, incluidos los envíos parciales;
  - si fallan `send_finished` o `close()` tras todos los 2xx, el estado es `UNCERTAIN` con rc=2;
  - un `close()` que falla tras un HTTP 500 no cambia ese estado más débil;
  - los códigos HTTP recibidos se conservan aparte, no hay reintentos y el registro no contiene un
    resultado que no pudo escribir;
- **`send()` directo:** endpoint, timeout (0, NaN, booleano, texto, >120) y clave inválidos;
  destino sin workspace o alterado; span de otro proyecto, huérfano, repetido o con id no v7;
  procedencia que no cubre las trazas; y la puerta de procedencia. En todos los casos sin
  transporte ni registro;
- **destino cambiado:** un plan redirigido a otro workspace válido, o a otro proyecto con el
  payload reetiquetado, se rechaza antes de crear el registro o llamar al transporte; el plan
  reconstruido para ese destino sí se envía. También se rechazan un ámbito de id ausente o de otro
  tipo y un `start_time` alterado;
- **envío con transporte falso** (sin red, credenciales reales ni llamadas a Opik):
  - URL, cabeceras y timeout de cada POST, y bodies idénticos al dry-run con el mismo workspace;
  - registro completo, sin la clave ni en el registro ni en la salida;
  - timeout, conexión cortada, HTTP 500 y envíos parciales (204 seguido de timeout o de 409):
    `UNCERTAIN`, sin reintentos y sin batches posteriores;
  - sintético o desconocido rechazados sin `--allow-*`, sin leer ninguna variable ni crear el
    registro, y aceptados con la autorización explícita;
  - entradas con todo retenido bloqueadas, y `NOTHING_TO_SEND` sin leer la clave;
  - clave ausente, multilínea o extendida sin `--endpoint`; endpoints `http`, con credenciales o
    con query;
  - registro existente intacto y nunca reutilizado;
  - opciones de envío rechazadas sin `--send`; workspace, registro y timeout obligatorios;
  - redirecciones no seguidas;
  - el transporte urllib real con sockets bloqueados queda `UNCERTAIN` tras un único intento;
- **dry-run en proceso:** con entorno y transporte vigilados, no lee ninguna variable, no usa el
  transporte y no crea archivos;
- **trazas retenidas:** una entrada desconocida o sintética con todas sus trazas retenidas queda
  bloqueada y el resumen lo explica; una captura declarada y retenida sigue permitida;
- **lotes:** sin bodies vacíos (traza retenida, traza sólo `interval-unknown`) y troceo 1000+1;
- **procedencia:** captura válida con registros (contexto con nombre de tipo Hermes simulado a
  propósito), origen desconocido bloqueado aunque haya registros, fixtures sintéticos que necesitan
  autorización, nombres que no se aceptan como prueba, registros inválidos (ninguno, otro origen,
  posterior a los eventos);
- **contenido:** contenido prohibido y valor con aspecto de clave;
- **tokens y coste:** sin campos de coste o uso de primer nivel, y tokens con estado, también ausentes;
- **tiempos:** epochs, herramientas como eventos puntuales, trazas retenidas o `interval-unknown`,
  relojes mezclados (epochs posteriores a la captura) y timestamps inválidos o sin zona;
- **ids:** deterministas, con disposición v7, separados por destino y distintos de LangSmith; validación del destino;
- **dry-run:** en subproceso con red bloqueada, entorno vigilado, sin importar `opik` ni `langsmith`
  y sin escribir archivos.

Mutaciones comprobadas: uso o modelo de primer nivel, bloqueo de sintéticos o desconocidos
eliminado (en el envío, 8 tests fallan), ids sin destino, herramientas como spans de 0 ms,
intervalo mezclado con `recorded_at`, un único body sin trocear (vacío incluido), una puerta que
ignora las trazas retenidas, un reintento automático tras una excepción (3 tests fallan), copiar la
razón HTTP al resultado (4 tests fallan), quitar las validaciones propias de `send()` (20 tests
fallan), dejar escapar la excepción del registro (6 tests fallan), mantener
`ALL_BATCHES_HTTP_ACCEPTED` tras un fallo de `send_finished` o `close()` (2 tests fallan) y quitar
la comprobación de derivación de ids (5 tests fallan). Para `--error-body-file`: llevar el cuerpo al
informe (2 tests fallan), permisos 0644 (1 test falla), apertura sin `O_EXCL`/`O_NOFOLLOW` y con
truncado (2 tests fallan) y quitar el límite de 4096 bytes (1 test falla). En la lectura acotada:
`read()` sin límite o de más de 4097 bytes (10 tests fallan) y afirmar el total tras truncar
(3 tests fallan). Todas se detectan.

Dry-run real sobre la [evidencia sintética del loader](../evaluation/observability/hermes_loader_hooks_synthetic_2026_10_20/):
rc=0, 6 eventos, 1 traza `SYNTHETIC` con 3 spans `llm` (uno con `error_info`) y 1 evento puntual,
2 trazas sin intervalo retenidas y bloqueo por defecto por ser sintética. Nada enviado.

## Evidencia existente y lo que falta

- **Existe:** evidencia sintética del loader real de Hermes, sintética por sus marcas y sin
  registros de procedencia, porque es anterior al plugin 0.3.0, y los tests offline anteriores.
- **Primer intento de envío (21/10/2026, autorizado):** está en
  `evaluation/observability/opik_first_synthetic_send_2026_10_21/` (`send_report.json`,
  `send_record.jsonl`, `send.stderr` vacío y `send.rc`=2), sin versionar.
  - Destino: workspace `joowww`, proyecto `tfg-opik-synthetic-20261021`, `--allow-synthetic`.
  - Se intentó sólo el batch de trazas (1 traza, body sha256 `5a27aa64…59b96`, idéntico al
    preparado). Respuesta **HTTP 400** con 177 bytes de cuerpo, **descartado** por diseño.
  - El batch de spans no se intentó. Estado `UNCERTAIN` (`http_status_400`), registro completo.
  - Según Joel, la interfaz no muestra trazas ni logs en los últimos 60 días.
  - **La causa del 400 no se conoce.** El body cumple la especificación y los modelos del SDK
    2.2.110. Ese cuerpo perdido motivó `--error-body-file`.
- **Diagnóstico de un solo batch:**
  - Preparación: [opik_diag_single_batch_2026_10_21](../evaluation/observability/opik_diag_single_batch_2026_10_21/README.md).
  - Envío: [opik_diag_single_batch_send_2026_10_21](../evaluation/observability/opik_diag_single_batch_send_2026_10_21/README.md).
  - Mismo destino que el primer intento y una entrada sintética nueva (1 traza sin spans):
    **HTTP 204**, y Joel ve la traza en la interfaz.
  - Como el destino y la autenticación funcionan, la hipótesis principal del 400 apunta a los
    valores temporales de la traza original (intervalo de unas 74 h o inicio de hace unas 100 h).
    No está confirmada.
- **Captura real de Hermes y su envío:**
  - Captura: [hermes_real_capture_nous_2026_10_21](../evaluation/observability/hermes_real_capture_nous_2026_10_21/README.md),
    plugin 0.3.0, perfil `default`, `poolside/laguna-s-2.1:free` vía `nous`, registro de
    procedencia verificado.
  - Envío: [opik_hermes_real_send_2026_10_21](../evaluation/observability/opik_hermes_real_send_2026_10_21/README.md),
    workspace `joowww`, proyecto `tfg-opik-hermes-real-20261021`, `--provenance captured`.
  - Resultado: **204 + 204** (1 traza y 1 span `llm`), y Joel confirma visualmente la traza y el span
    con los datos esperados.
  - La captura cubre **sólo el turno principal**: la generación auxiliar del título usa otros hooks.
- **Sigue sin comprobar:** cómo trata Opik los ids repetidos, los límites de tamaño del backend,
  la causa exacta del primer 400 y el coste (no se calcula). No hay ledger entre ejecuciones:
  **no reenviar** los envíos ya hechos.
