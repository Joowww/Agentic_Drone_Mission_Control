# Validación offline del exportador Opik contra el SDK 2.2.110 (21/10/2026). Nada enviado

Validación de los payloads de [`observability/opik_export.py`](../../../observability/opik_export.py)
contra los modelos REST y la ruta de serialización del SDK oficial `opik==2.2.110`. No se ha
contactado con ningún servidor de Opik, no se han usado credenciales y no se ha enviado nada.

## Entorno

- **SDK:** `opik==2.2.110`, la última versión en PyPI al empezar (subida el 21/10/2026 a las
  07:21 UTC). Está instalada en un venv desechable de la scratchpad de la sesión, fuera del repo y
  de la `.venv` del proyecto, con Python 3.12.3 del sistema. Las versiones resueltas están en
  `opik_venv_pip_freeze.txt`. La `.venv` y `requirements-observability.txt` no cambian.
- **Payloads:** `scripts/generate_payloads.py` se ejecuta con la `.venv` del proyecto y no
  necesita el SDK. Genera el dry-run de 4 casos en `payloads/`, a partir de fixtures de
  `tests/test_opik_export.py` y de la [evidencia sintética del loader](../hermes_loader_hooks_synthetic_2026_10_20/),
  que sólo se lee.
- **Aislamiento del arnés:** `scripts/sdk_harness.py` se ejecuta con el venv de Opik y con
  `env -i PATH=/usr/bin:/bin HOME=<directorio vacío> OPIK_SENTRY_ENABLE=false`:
  - `socket.connect`, `connect_ex`, `create_connection` y `getaddrinfo` fallan antes de importar `opik`;
  - las peticiones van a un `httpx.MockTransport` sobre `http://opik.invalid/api`, que responde
    204 y comprueba que no viajan las cabeceras `authorization` ni `Comet-Workspace`;
  - el `HOME` vacío impide leer `~/.opik.config`.

## Qué se validó

Resultado (`sdk_validation_report.json`): **0 problemas en los 4 casos** (captura declarada con
LLM, herramienta y error; procedencia desconocida; `--include-untimed`; evidencia sintética).

1. **Modelos REST:** cada traza y cada span pasan `TraceWrite.model_validate` /
   `SpanWrite.model_validate`, y `error_info` pasa `ErrorInfoWrite`. Los modelos tienen
   `extra="allow"`, así que el arnés también comprueba que cada clave está en `model_fields`.
   `SpanWriteType` es `Union[Literal["general","tool","llm","guardrail"], Any]`, por lo que el
   `type` se compara con esos literales y no se deja en manos de pydantic.
2. **Ids:** UUIDv7. En el SDK, `Opik.trace()`/`Opik.span()` documentan que un id dado por el
   usuario "Must be a valid UUIDv7 ID" (`opik/api_objects/opik_client.py`), y `id_helpers.generate_id`
   genera v7. La especificación REST sólo dice `format: uuid`.
3. **Lotes:** cada body tiene 1-1000 elementos. El batcher del SDK
   (`CREATE_{TRACES,SPANS}_MESSAGE_BATCHER_MAX_BATCH_SIZE = 1000`) trocea 1001 spans en `[1000, 1]`,
   igual que `batch_bodies`.
4. **Cliente REST con transporte falso:** `OpikApi.traces.create_traces` / `spans.create_spans`
   hacen `POST /api/v1/private/{traces,spans}/batch` y el JSON enviado coincide con el body del
   exportador. Las fechas son el mismo instante. Sólo cambia el texto: el SDK usa `isoformat()`,
   que omite `.000000` cuando los microsegundos son 0, y el exportador usa `%f` fijo; ambas formas
   son RFC 3339.
5. **Ruta propia del SDK** (`CreateTraceMessage`/`CreateSpanMessage` → batchers →
   `encode_and_anonymize` → cliente REST): mismos campos y valores. La única diferencia es que el
   SDK añade `source: "sdk"`. Es opcional en `Trace_Write`/`Span_Write` y el exportador no lo
   emite a propósito, porque no es el SDK.
6. **Controles negativos** (`negative_controls.txt`): el arnés rechaza, con rc=1, una clave
   desconocida, un id UUIDv4, `type="agent"`, un body vacío y un `error_info` sin `traceback`.

No se encontró ninguna discrepancia y no se cambió la lógica del exportador.

## Qué no se comprobó (servicio)

- Que el servidor de Opik (Cloud o self-hosted) acepte los payloads. Respuestas 4xx, cuotas y
  límites de tamaño en MB del backend sin comprobar.
- Qué hace el servidor con ids repetidos o con trazas reenviadas (idempotencia).
- Que un id con disposición v7 pero bits aleatorios derivados de un hash se comporte igual que uno
  generado por el SDK al ordenar o filtrar por tiempo.
- La estimación de coste en el servidor para spans `llm` sin `usage`/`model`/`provider`, y cómo
  muestra la UI `metadata.tfg_*`.
- La compatibilidad con versiones del SDK distintas de 2.2.110.

## Reproducir

```bash
V=<directorio temporal fuera del repo>
python3 -m venv $V/opik-venv && $V/opik-venv/bin/pip install 'opik==2.2.110'
.venv/bin/python -I evaluation/observability/opik_sdk_offline_validation_2026_10_21/scripts/generate_payloads.py "$PWD" $V/payloads
env -i PATH=/usr/bin:/bin HOME=$V/home OPIK_SENTRY_ENABLE=false $V/opik-venv/bin/python -I \
    evaluation/observability/opik_sdk_offline_validation_2026_10_21/scripts/sdk_harness.py $V/payloads
```

Los ids y las horas de los casos con fixtures de captura dependen del momento en que se ejecutan.
Los de la evidencia sintética son estables: una segunda generación dio un payload idéntico.

Los JSON de `payloads/` se generaron antes de actualizar la etiqueta `verification` del exportador
y conservan la anterior (`UNVERIFIED_AGAINST_OPIK_SDK…`). El campo `payload` validado no cambia.
