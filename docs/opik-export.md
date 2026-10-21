# Exportador a Opik (dry-run por defecto, envío explícito)

Fecha: 21/10/2026. **Implementado y probado offline. La ruta `--send` existe, pero sólo se ha
probado con transportes HTTP falsos: nunca se ha ejecutado y no se ha enviado nada a Opik.** No es
una captura real de proveedor ni un baseline de rendimiento o gasto.

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
    [--allow-synthetic] [--allow-unknown-provenance]
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
en el registro ni en la salida. La salida JSON repite el resultado de cada batch.

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

`tests/test_opik_export.py` (96 tests). Cubren:
- **texto del servidor:** un transporte que devuelve un centinela sensible en la razón, las
  cabeceras, el cuerpo, el mensaje de excepción y un estado no entero. El centinela no aparece en
  la salida ni en el registro, y cada batch sólo tiene campos acotados. El transporte urllib real,
  con un opener falso, sólo devuelve código y tamaño, también ante un `HTTPError`;
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
la comprobación de derivación de ids (5 tests fallan). Todas se detectan.

Dry-run real sobre la [evidencia sintética del loader](../evaluation/observability/hermes_loader_hooks_synthetic_2026_10_20/):
rc=0, 6 eventos, 1 traza `SYNTHETIC` con 3 spans `llm` (uno con `error_info`) y 1 evento puntual,
2 trazas sin intervalo retenidas y bloqueo por defecto por ser sintética. Nada enviado.

## Evidencia existente y lo que falta

- **Existe:** evidencia sintética del loader real de Hermes, sintética por sus marcas y sin
  registros de procedencia, porque es anterior al plugin 0.3.0, y los tests offline anteriores.
- **Falta, para una prueba real futura:**
  1. una captura real de un turno con un proveedor, hecha con el plugin 0.3.0 para que tenga
     registro de procedencia, sin forzar el contexto ni copiar credenciales (pendiente, igual que en
     [LangSmith](langsmith-export.md#prueba-de-tokens-reales-pendiente));
  2. comprobar contra un servicio lo que el SDK no puede confirmar offline: que acepte el payload,
     cómo trata los ids repetidos y los ids v7 derivados de un hash, y los límites de tamaño del
     backend. La forma ya está validada offline contra el SDK 2.2.110;
  3. revisar la ruta `--send` implementada (sin reintentos, con registro por batch y estado
     incierto) y obtener la autorización explícita de Joel para un único envío, preferiblemente de
     una captura verificada. Hoy no hay ledger entre ejecuciones;
  4. una cuenta, workspace y proyecto de Opik dedicados, con su región y retención, y la confirmación
     de que la clave corresponde al endpoint Cloud por defecto o a uno explícito.
