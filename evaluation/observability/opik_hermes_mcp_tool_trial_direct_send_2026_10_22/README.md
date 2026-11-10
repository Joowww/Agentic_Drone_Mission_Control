# Envío a Opik del ensayo MCP con aislamiento directo — HTTP 204 + 204 (22/10/2026)

Un único envío autorizado por Joel y ejecutado por él en su terminal. Antes de pedir la clave
oculta, el bloque encadenado hizo estas comprobaciones:
- verificó `SHA256SUMS` de la evidencia;
- regeneró el dry-run con el exportador y comprobó los dos hashes autorizados, el ID de la traza,
  la procedencia, que hubiera 2 spans y que no hubiera nada retenido;
- rechazó rutas de salida ya existentes.

Después envió una sola vez, sin `--allow-*` y sin reintentos, y borró la variable con la clave.

- **Captura enviada:**
  [hermes_mcp_tool_trial_direct_nous_2026_10_22](../hermes_mcp_tool_trial_direct_nous_2026_10_22/README.md)
  (veredicto `TOOL_CALL_OBSERVED_AS_EXPECTED`). No se ha modificado.
- **No enviado:** el ensayo anterior,
  [hermes_mcp_tool_trial_nous_2026_10_22](../hermes_mcp_tool_trial_nous_2026_10_22/README.md)
  (`ISOLATION_NOT_CONFIRMED`).
- **El dashboard no se ha modificado.**

## 1. Hechos del exportador (`send_report.json` y `send_record.jsonl`)

| Dato | Valor |
| --- | --- |
| Destino | workspace `joowww`, proyecto `tfg-opik-hermes-real-20261021`, `https://www.comet.com/opik/api` |
| Procedencia | `--provenance captured` (`captured_hermes_metadata`, registro de procedencia del plugin 0.4.1 verificado) |
| Entrada | `capture/hermes-events-2026-10-22.jsonl`, sha256 `264d4beb1698335f666190c51d312d312a58ebc6aaedc59726828c11f956bf76` |
| Batch 0 | `POST /v1/private/traces/batch`, 1 traza (`01a16485-5e65-7966-a4b8-3df00e69d9b1`), 2242 bytes, body `41110bb79d8a613572921f54ccd9e94cc375605ceb3311bff3d7b34d234b8b10` → **204**, 0,990 s |
| Batch 1 | `POST /v1/private/spans/batch`, 2 spans (`01a16485-5e65-722e-a2d3-acf60c4be263` … `01a16485-7101-7baa-bc0b-17ffb4e48f7a`), 5140 bytes, body `f6e989fc681416cca78c54ed3dd60b4938063a7253c7dbb8d9a78d56324469c6` → **204**, 0,965 s |
| Estado | `ALL_BATCHES_HTTP_ACCEPTED`, `record_complete: true`, 0 batches sin intentar, rc=0, `send.stderr` vacío; enviado entre 16:58:05.006 y 16:58:06.991 UTC |
| Cuerpo de error | No hizo falta (`not_needed_no_non_2xx_response`); `~/opik-hermes-mcp-trial-private-20261022/` (0700) quedó vacío |

- Los dos `body_sha256` registrados son exactamente los autorizados.
- **Un 204 acredita que Opik aceptó la petición,** no que la almacenara ni que la entrega fuera
  exactamente una vez.

## 2. Declaración del operador (separada de lo anterior)

Declaración de Joel, el 22/10/2026, tras el envío, citada literalmente:

> Confirmo visualmente en Opik la traza hermes_turn de 6,8 s con dos spans LLM, de aproximadamente
> 4,4 y 2,1 s, etiqueta captured-metadata e input/output vacíos.
>
> En la metadata confirmo un único tfg_point_event de mcp__tfg_mission_control__get_mission_state,
> status=ok, duración recibida de Hermes 224 ms y tfg_latency_measured=false. No aparece un tercer
> span de herramienta.
>
> No doy por comprobados todavía el recuento global del proyecto ni los tokens de cada span.

| Lo que acredita la declaración | Coincide con lo enviado |
| --- | --- |
| Traza `hermes_turn` de unos 6,8 s, etiqueta `captured-metadata` | 16:50:24.486–16:50:31.307 UTC (6,821 s) |
| Dos spans LLM de unos 4,4 y 2,1 s | 4,408 s y 2,057 s (`api_duration_s` de Hermes) |
| input/output vacíos | El exportador no envía input ni output |
| Un único `tfg_point_event` de la herramienta, `status=ok`, 224 ms recibidos, `tfg_latency_measured=false` | Igual al payload |
| No hay un tercer span de herramienta | La herramienta no se presenta como span medido |

**Fuera de la declaración (NO comprobado por el operador):**
- el recuento global del proyecto (se esperaban 3 trazas y 4 spans LLM);
- los tokens de cada span;
- el resto de campos de metadata;
- el reflejo en el dashboard.

La declaración es una observación humana.

## 3. Captura de pantalla del operador (incorporada después)

| Dato | Valor |
| --- | --- |
| Archivo | `operator_screenshot_opik_2026_10_22.png` (PNG 831×625) |
| SHA-256 | `9a077e5d9ba1694ad76828d182305c9715e5d92eb3920c1570bd0c13f12f76e1` |
| Origen | Imagen que Joel adjuntó en un mensaje posterior a su declaración. Se copió sin modificar el 22/10/2026 a las 17:06:52 UTC; el hash es idéntico al del adjunto |
| Naturaleza | Captura tomada por el operador. No es una exportación de Opik y no lleva metadatos que acrediten la hora de la toma |

Lo que **se ve** en la imagen, comparado con el payload enviado:

| Visible | Payload | ¿Coincide? |
| --- | --- | --- |
| Traza `hermes_turn`, 6.8s, `Spans (2)` | traza de 6,821 s | sí |
| Dos hijos `llm_call:poolside/laguna-s-2.1:free`, de 4.4s y 2.1s | spans de 4,408 s y 2,057 s | sí |
| Etiquetas `captured-metadata`, `schema:tfg.hermes…` (truncada), `tfg-hermes-capture` | las mismas tres | sí |
| Input y Output vacíos | no se envían | sí |
| `tfg_grouping: derived_from_turn_ref`, `tfg_observed_event: false`, `tfg_run_id: real-hermes-20261022`, `tfg_case_id: mcp-get-mission-state` | iguales | sí |
| `tfg_session_ref: sha256:483a3a8b43a4d17d`, `tfg_turn_ref: sha256:618c2c8968a17718` | iguales | sí |
| `tfg_data_kind: captured_hermes_metadata`, `tfg_provenance_basis: declared_captured_with_hermes_sink_provenance_record`, `tfg_timed_spans: 2` | iguales | sí |
| `tfg_point_events:` | un evento | **plegado**: su contenido no se ve en la imagen |

**Observaciones:**
- **Contenido del evento puntual:** que `tfg_point_events` contiene la herramienta con `status=ok`,
  224 ms y `tfg_latency_measured=false` lo acredita **la declaración** de la sección 2, no esta
  imagen.
- **Ausencia de un span de herramienta:** la imagen sí lo muestra. El árbol solo tiene la traza y
  dos `llm_call`.
- **Hora de la cabecera:** muestra «22 Oct 2026, 6:58 PM». Coincide con la hora del envío
  (16:58 UTC, 18:58 CEST), no con el inicio de la traza en el payload (16:50:24 UTC, 18:50 CEST).
  No se ha verificado qué campo muestra Opik ahí. Las duraciones sí coinciden con los intervalos
  enviados.
- **Lo que no aparece en la imagen:** el recuento del proyecto, los tokens de los spans y el
  dashboard. Siguen sin comprobar.

## Límites

- Una traza no es una muestra representativa. La duración de los spans es el intervalo de Hermes
  para cada llamada, no un TTFT. La herramienta tiene una duración informada, no un intervalo
  medido.
- Los IDs son deterministas. No se ha verificado cómo trata Opik un ID repetido. **No reenviar.**
- Los tokens son los normalizados de Hermes. Coste facturado desconocido.

## Archivos

- `SHA256SUMS` cubre `send.rc`, `send.stderr`, `send_record.jsonl`, `send_report.json`,
  `operator_screenshot_opik_2026_10_22.png` y este README. Se regeneró al incorporar la captura;
  los cuatro archivos del envío conservan sus hashes anteriores.
- Los cuatro archivos del envío son los generados en la terminal de Joel y no se han modificado.
- Ninguno contiene la clave.
