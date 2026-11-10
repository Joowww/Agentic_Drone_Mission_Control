# Envío a Opik de la segunda captura real de Hermes — HTTP 204 + 204 (22/10/2026)

Un único envío autorizado por Joel. Lo ejecutó Joel en su terminal, con un bloque encadenado que
primero verificaba el manifiesto de la captura y luego regeneraba el dry-run offline, comprobando
los hashes de los bodies autorizados, la procedencia y la ausencia de trazas retenidas o errores.
También rechazaba rutas de salida ya existentes. Solo después de todo eso pedía la clave por TTY,
sin eco, y ejecutaba el exportador una sola vez. La clave no se guardó y la variable se borró al
terminar.

La captura y su dry-run están en
[hermes_real_capture_nous_2026_10_22](../hermes_real_capture_nous_2026_10_22/README.md) y no se han
modificado. El primer envío real, del 21/10, está en
[opik_hermes_real_send_2026_10_21](../opik_hermes_real_send_2026_10_21/README.md).

## Hechos del exportador (`send_report.json` y `send_record.jsonl`)

| Dato | Valor |
| --- | --- |
| Destino | workspace `joowww`, proyecto `tfg-opik-hermes-real-20261021`, `https://www.comet.com/opik/api` |
| Procedencia | `--provenance captured` (`captured_hermes_metadata`, registro de procedencia verificado); sin `--allow-synthetic` ni `--allow-unknown-provenance` |
| Entrada | `capture/hermes-events-2026-10-22.jsonl`, sha256 `b416c50e66bb15e2c912768619301d105cb23a1d464146e5751ce2f74ba02eac` |
| Registro de procedencia | `capture-provenance-dc554d25-e73a-41e6-adc6-2ee0ee60fe35.json`, sha256 `b15ceb7d87fd9d0587f2a14cb671e533b8e6e33a115183dd2aa58795926fff7e` |
| Batch 0 | `POST /v1/private/traces/batch`, 1 traza, 1016 bytes, body `ab2dd88d0d18f6cc478908e17a1e87346b738aedcf430ac374e38b16b8d5b017` → **204**, 0,805 s |
| Batch 1 | `POST /v1/private/spans/batch`, 1 span, 2535 bytes, body `455477f96ae4f2cf565ce0977b505668e992895e244ee2e1264eb87fb5685b47` → **204**, 0,687 s |
| Estado | `ALL_BATCHES_HTTP_ACCEPTED`, `record_complete: true`, rc=0, `send.stderr` vacío; enviado entre 08:45:09 y 08:45:10 UTC |
| Cuerpo de error | No hizo falta (`not_needed_no_non_2xx_response`); el directorio privado `~/opik-hermes-real-private-20261022/` (0700) quedó vacío |

- Los dos `body_sha256` registrados son los autorizados en la preparación.
- Corresponden al orden real de serialización del exportador: `separators=(",", ":")` y claves en
  orden de inserción.
- Si se recalculan desde `opik_dry_run.json`, guardado con claves ordenadas, salen otros hashes:
  `496bbd50…` y `11ea18bc…`, comprobado el 22/10. Es una diferencia de serialización, no de
  contenido: el dry-run regenerado con el CLI justo antes del envío reprodujo `ab2dd88d…` y
  `455477f9…`. El README de la captura todavía no documenta esta diferencia. Queda pendiente una
  corrección futura que unifique la serialización y tenga su regresión.
- No hubo reintentos ni batches sin intentar.

| Recurso | Id |
| --- | --- |
| Traza | `01a162b6-2ebb-7ed9-9cb4-921cef200602` («hermes_turn», 08:24:29.115–08:24:32.182 UTC, ~3,07 s) |
| Span | `01a162b6-2ebb-7922-baa1-6ffc9bea022d` (tipo `llm`, «llm_call:poolside/laguna-s-2.1:free», mismo intervalo) |

**Los 204 acreditan que Opik aceptó las peticiones, no que las almacenara.**

## Declaración del operador — separada de las respuestas HTTP

Declaración de Joel, el 22/10/2026, después del envío, citada literalmente:

> Confirmo visualmente que aparecen las dos trazas con sus spans y que el dashboard incorpora la
> nueva ejecución con 570 tokens de entrada, 2 de salida y 224 de caché leída.

| Evidencia | Fuente | Qué acredita |
| --- | --- | --- |
| HTTP 204 + 204 | `send_report.json` y `send_record.jsonl`, generados por el exportador (08:45:09–08:45:10 UTC) | Que Opik aceptó las dos peticiones |
| Dos trazas con sus spans visibles | Declaración de Joel | Que en el proyecto se ven la traza del 21/10 (`01a16002-…`) y esta nueva, cada una con su span |
| Valores en el dashboard | Declaración de Joel | Que la vista «TFG - Hermes» incorpora la nueva ejecución con entrada 570, salida 2 y caché leída 224, que coinciden con `metadata.tfg_usage` del span |

Límites de esta declaración:

- Es una observación humana. No hay captura de pantalla, exportación de la interfaz ni lectura
  remota hecha por Claude, así que no tiene hash.
- No consta qué widgets concretos se miraron ni el rango de tiempo aplicado.
- La declaración no menciona el resto de campos esperados, así que no quedan acreditados por ella:
  etiquetas, `tfg_data_kind`, `tfg_provenance_basis`, la ausencia de input/output/usage/coste en
  el primer nivel y los ceros `zero_unconfirmed`.
- Que haya dos trazas es un recuento del proyecto. No es una comparación representativa de
  rendimiento: son dos turnos sueltos con el mismo modelo.

## Límites

- 204 significa petición aceptada. No prueba el almacenamiento ni que la entrega fuera exactamente
  una vez.
- Los ids son deterministas. No se ha verificado cómo trata Opik un id repetido. **No reenviar.**
- Los contadores son de Hermes (normalizados), no los del proveedor en bruto. `prompt_tokens` y
  `total_tokens` son derivados. `api_call_count` no es un recuento de peticiones HTTP. No hay coste
  facturado conocido.
- La generación auxiliar del título (entrada 38, salida 6 según el informe nativo) no está en
  Opik: el plugin no la captura.

## Archivos

`SHA256SUMS` cubre `send.rc`, `send.stderr`, `send_record.jsonl`, `send_report.json` y este
README.

- Los cuatro archivos del envío son los generados en la terminal de Joel y no se han modificado.
- `send.rc` y `send.stderr` los escribió la redirección del bloque; los JSON, el exportador.
- Ninguno contiene la clave.
