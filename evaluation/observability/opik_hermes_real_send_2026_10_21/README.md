# Envío a Opik de la captura real de Hermes — HTTP 204 + 204 (21/10/2026)

Un único envío autorizado por Joel y ejecutado por Joel en su terminal con
`opik_hermes_real_send_once.sh`. La clave se leyó por TTY y no se guardó. Es la primera exportación
a Opik de una **captura real** del plugin; la captura y su dry-run están en
[hermes_real_capture_nous_2026_10_21](../hermes_real_capture_nous_2026_10_21/README.md), que no se
ha modificado. Joel confirmó antes del envío que el proyecto existía en la interfaz.

## Hechos (de `send_report.json` y `send_record.jsonl`)

| Dato | Valor |
| --- | --- |
| Destino | workspace `joowww`, proyecto `tfg-opik-hermes-real-20261021`, `https://www.comet.com/opik/api` |
| Procedencia | `--provenance captured` (`captured_hermes_metadata`, registro de procedencia verificado); sin `--allow-synthetic` ni `--allow-unknown-provenance` |
| Entrada | `capture/hermes-events-2026-10-21.jsonl`, sha256 `1b649d119040a95f2921d46c0e1c2e3b98fa021ab58d233613775c6021c568d8` |
| Registro de procedencia | sha256 `71e352448debd0e3f2e5722e8a79a0221bee0e9b2087524ec0df055e5563a36d` |
| Batch 0 | `POST /v1/private/traces/batch`, 1 traza, 1021 bytes, body `881bb615907fddec8e6e56b2bd98c600e297d4a5bcded5d9059e95f0ed9fea15` → **204**, 0,793 s |
| Batch 1 | `POST /v1/private/spans/batch`, 1 span, 2541 bytes, body `a2b96e370d81fa1f7d92d29308aef0c362df2fbcd3bb6c0ebac83f5b3ca95fda` → **204**, 0,631 s |
| Estado | `ALL_BATCHES_HTTP_ACCEPTED`, `record_complete: true`, rc=0, `send.stderr` vacío; enviado entre 20:03:09 y 20:03:10 UTC |
| Cuerpo de error | No hizo falta (`not_needed_no_non_2xx_response`); el directorio privado quedó vacío |

Los dos `body_sha256` registrados son los autorizados en la preparación. Sin reintentos.

**El 204 por sí solo no confirmaba el almacenamiento.** La confirmación viene aparte, de la
comprobación visual del operador (sección siguiente).

## Comprobación en la interfaz — CONFIRMADA por el operador

| Evidencia | Fuente | Qué acredita |
| --- | --- | --- |
| HTTP 204 + 204 | `send_report.json` y `send_record.jsonl`, generados por el exportador (20:03:09–20:03:10 UTC) | Que Opik aceptó las dos peticiones. No acredita que las almacenara |
| Traza y span visibles | **Declaración de Joel como operador**, el 21/10/2026, tras el envío | Que la traza real y su span se ven en Opik **con los datos esperados** |

- Lo confirmado por el operador es que **ve la traza real y su span en Opik con los datos
  esperados**, es decir, los de la lista siguiente.
- No se registró campo por campo qué valores se miraron. No hay captura de pantalla ni exportación
  de la interfaz: es una declaración humana, no un artefacto con hash.

Datos esperados, usados como guía de la comprobación. En `joowww` → `tfg-opik-hermes-real-20261021` → Traces, con el filtro de tiempo abarcando el
21/10/2026 sobre las 19:49 UTC (21:49 CEST), o buscando por id:

- **Traza** `01a16002-9b28-75bc-abca-6942ca6d1c95`:
  - nombre «hermes_turn», sin prefijo SYNTHETIC ni UNKNOWN;
  - de 19:49:05.960 a 19:49:08.625 UTC, unos 2,66 s;
  - etiquetas `tfg-hermes-capture`, `schema:tfg.hermes.capture/3` y `captured-metadata`;
  - en metadata, `tfg_data_kind=captured_hermes_metadata` y
    `tfg_provenance_basis=declared_captured_with_hermes_sink_provenance_record`.
- **Span** `01a16002-9b28-7291-bce7-d68337bb58f2`:
  - de tipo `llm`, colgando de esa traza, nombre «llm_call:poolside/laguna-s-2.1:free»;
  - mismo intervalo;
  - en `metadata.tfg_usage`: input 538, output 2, cache_read 256, total 796, con su estado;
  - `tfg_model` y `tfg_provider`: `poolside/laguna-s-2.1:free` y `nous`.
- **No deben aparecer** input ni output, ni coste, usage, modelo o proveedor a primer nivel.
  - Opik no debería estimar el coste, porque falta el `usage` de primer nivel; no está verificado.
  - La generación auxiliar del título no está: el plugin no la capturó.

## Límites

- 204 significa petición aceptada. No prueba el almacenamiento ni que la entrega fuera exactamente
  una vez.
- Los ids son deterministas. No se ha verificado cómo trata Opik un id repetido. **No reenviar.**
- Los contadores son de Hermes (normalizados), no los del proveedor en bruto. `api_call_count` no
  es un recuento de peticiones HTTP, y no hay coste.

## Archivos

`SHA256SUMS` cubre `send.rc`, `send.stderr`, `send_record.jsonl`, `send_report.json` y este
README en su versión final, la que incluye la confirmación del operador. Los cuatro archivos del
envío no han cambiado desde que se generaron. Ninguno contiene la clave.
