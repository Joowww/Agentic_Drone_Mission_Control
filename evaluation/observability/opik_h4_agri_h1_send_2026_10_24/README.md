# H4: envío a Opik de la captura H1 de agri_demo_001 — HTTP 204 + 204 (24/10/2026)

Joel autorizó un único envío de la captura de **H1** (y no de H3) y lo ejecutó en su terminal. La
orden encadenada hizo estas comprobaciones **antes** de pedir la clave:
- verificó el `SHA256SUMS` de la evidencia de H1;
- regeneró el dry-run desde la captura original y comprobó el destino y los dos hashes de body
  completos;
- comprobó que no había nada retenido ni bloqueado;
- rechazó un directorio de salida que ya existiera.

Después envió una sola vez, sin `--allow-*` y sin reintentos, y borró la variable con la clave.

- **Captura enviada:** [agri_planning_h1_nous_2026_10_24](../agri_planning_h1_nous_2026_10_24/README.md),
  `capture/hermes-events-2026-10-24.jsonl`. No se ha modificado.
- **Vista previa autorizada:** [opik_h4_dry_run_agri_2026_10_24](../opik_h4_dry_run_agri_2026_10_24/README.md).
- **No enviado:** H3 ([agri_scenario_h3_nous_2026_10_24](../agri_scenario_h3_nous_2026_10_24/README.md)).

## Hechos del exportador

Proceden de `send_record.jsonl` y `send_summary.json`.

| Dato | Valor |
| --- | --- |
| Destino | workspace `joowww`, proyecto `tfg-opik-hermes-real-20261021`, `https://www.comet.com/opik/api` |
| Procedencia | `--provenance captured` (`captured_hermes_metadata`) |
| Hora | de 15:17:18.014 a 15:17:19.320 UTC |
| Lote 0 | `POST /v1/private/traces/batch`: 1 traza (`01a16de0-bd58-73f0-bf2f-bd45f0b557fc`), 5895 bytes, body `bb8019dd4ba4e3255e8cf535b8aa57141d19a98c73d43a0a30d23cf6e7951ce8` → **204**, 0,675 s |
| Lote 1 | `POST /v1/private/spans/batch`: 3 spans (`01a16de0-bd58-7de5-a710-713db5a489c2` … `01a16de1-5964-765f-bfce-a433761c4ad5`), 7810 bytes, body `174290900f77c2f21893fc01c2186b78b248f7bd4b22454fb546b84d931a867e` → **204**, 0,62 s |
| Resultado del recibo | `ALL_BATCHES_HTTP_ACCEPTED`, `record_complete: true`, 0 lotes sin intentar, sin motivo de incertidumbre, rc 0 y `send.stderr` vacío |
| Cuerpo de error | `not_needed_no_non_2xx_response` |

- Los dos `body_sha256` del recibo son exactamente los autorizados.
- **Un 204 indica que Opik aceptó la petición.** No demuestra que la almacenara ni que la entrega
  fuera única.
- El payload contiene solo metadatos: sin prompts, respuestas, argumentos, resultados ni
  contenido de misiones.

## Verificación visual en Opik: **CONFIRMADA por Joel el 24/10/2026**

Su declaración está en `operator_visual_confirmation.json`, separada de los hechos del exportador.
Literalmente:

> Confirmo que en Opik veo la traza hermes_turn del 24/10/2026 con los 3 spans
> llm_call:poolside/laguna-s-2.1:free. La comprobación visual está hecha.

Es una observación del operador, no una comprobación automática del almacenamiento en Opik. La
declaración no cita el id de la traza.

## Archivos

- `send_record.jsonl`: copia byte a byte del recibo del exportador. No contiene rutas ni clave.
- `operator_visual_confirmation.json`: la declaración visual de Joel, añadida después. El recibo
  no se ha modificado.
- `send_summary.json`: resumen derivado de `send_report.json`. Lleva destino, lotes, códigos HTTP,
  estado, rc y bytes de stderr, más el SHA-256 de los cuatro originales.
- Los originales (`send_report.json`, `send_record.jsonl`, `send.rc`, `send.stderr`) se quedan fuera
  del repositorio, en el directorio privado del envío (0700). `send_report.json` no se copia porque
  contiene rutas absolutas locales.
- **No se guardan** la clave (el exportador nunca la escribe) ni un cuerpo de error (no lo hubo).
- `SHA256SUMS` cubre todo salvo este README.
