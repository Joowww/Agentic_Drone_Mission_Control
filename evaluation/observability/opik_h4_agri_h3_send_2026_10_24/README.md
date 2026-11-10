# H4: envío a Opik de la captura H3 de agri_demo_001, etiquetada `NOT_VALIDATED` — HTTP 204 + 204 (24/10/2026)

Joel autorizó un único envío de **H3**, con la evaluación revisada (`acceptance:NOT_VALIDATED`,
`failed_keys: ["r1_movement_authorized"]`), y lo ejecutó en su terminal. La orden encadenada hizo
estas comprobaciones **antes** de pedir la clave:
- verificó el `SHA256SUMS` de la evidencia de H3;
- regeneró el dry-run desde la captura original con `--evaluation-file accept_h3.json`;
- comprobó el destino, una sola traza, la evaluación exacta, `answer_exported: false`, la ausencia
  de la explicación de Hermes en el payload y los dos hashes autorizados;
- rechazó un directorio de salida que ya existiera.

Después envió una sola vez, sin `--allow-*` y sin reintentos, y borró la variable con la clave.
**H1 no se reenvió.**

- **Captura enviada:** [agri_scenario_h3_nous_2026_10_24](../agri_scenario_h3_nous_2026_10_24/README.md),
  `capture/hermes-events-2026-10-24.jsonl`, con `accept_h3.json` como evaluación. No se ha
  modificado.
- **Vista previa autorizada:** [opik_h4_h3_evaluation_dry_run_2026_10_24](../opik_h4_h3_evaluation_dry_run_2026_10_24/README.md).

## Hechos del exportador

Proceden de `send_record.jsonl` y `send_summary.json`.

| Dato | Valor |
| --- | --- |
| Destino | workspace `joowww`, proyecto `tfg-opik-hermes-real-20261021`, `https://www.comet.com/opik/api` |
| Procedencia | `--provenance captured` (`captured_hermes_metadata`) |
| Hora | de 15:38:05.892 a 15:38:07.172 UTC |
| Traza | `01a16e0d-eb87-71c9-a8b6-626d08ba0e23`, con la etiqueta `acceptance:NOT_VALIDATED` y `metadata.tfg_evaluation` = `{acceptance: NOT_VALIDATED, failed_keys: [r1_movement_authorized], evidence_ref: sha256:80858822326bcadd, answer_exported: false}` |
| Lote 0 | `POST /v1/private/traces/batch`: 1 traza, 3690 bytes, body `130430933fc1a984d4bef77b64a59d6ae112dfc434e9a370a58b7438caa04058` → **204**, 0,675 s |
| Lote 1 | `POST /v1/private/spans/batch`: 2 spans (`01a16e0d-eb87-7acb-894b-4d469181981f` … `01a16e0e-1617-7c21-8f7e-f083b890e853`), 5164 bytes, body `5ed58da0ae92abd31ba3454f5ba85fee42ff8b224abb4477518c5d1a8b229748` → **204**, 0,593 s |
| Resultado del recibo | `ALL_BATCHES_HTTP_ACCEPTED`, `record_complete: true`, 0 lotes sin intentar, sin motivo de incertidumbre, rc 0 y `send.stderr` vacío |
| Cuerpo de error | `not_needed_no_non_2xx_response` |

- Los dos `body_sha256` del recibo son exactamente los autorizados.
- **Un 204 indica que Opik aceptó la petición.** No demuestra que la almacenara ni que la entrega
  fuera única.
- **La etiqueta no es un hecho sobre el rover.** Indica que la aceptación determinista **rechazó**
  la respuesta de Hermes. El texto erróneo («la dependencia MET autoriza mover el rover») no
  viajó: queda solo en la evidencia local de H3.

## Verificación visual en Opik: **CONFIRMADA por Joel el 24/10/2026**

Su declaración está en `operator_visual_confirmation.json`, separada de los hechos del exportador.
Literalmente:

> Confirmo que en Opik veo la traza H3 hermes_turn con los 2 spans
> llm_call:poolside/laguna-s-2.1:free y la etiqueta acceptance:NOT_VALIDATED.

Además revisó estos metadatos de la traza: `tfg_case_id: mcp-agri-scenario-h3`,
`tfg_evaluation.acceptance: NOT_VALIDATED`, `failed_keys: [r1_movement_authorized]`,
`evidence_ref: sha256:80858822326bcadd` y `answer_exported: false`.

Es una observación del operador, no una comprobación automática del almacenamiento en Opik. La
declaración no cita el id de la traza.

## Archivos

- `send_record.jsonl`: copia byte a byte del recibo del exportador. No contiene rutas ni clave.
- `operator_visual_confirmation.json`: la declaración visual de Joel, añadida después. El recibo y
  el resumen no se han modificado.
- `send_summary.json`: resumen derivado del informe y del recibo. Lleva destino, hora, id de la
  traza, evaluación exportada, lotes con hashes y tamaños, códigos HTTP, estado, rc y bytes de
  stderr, más el SHA-256 de los cuatro originales.
- Los originales (`send_report.json`, `send_record.jsonl`, `send.rc`, `send.stderr`) se quedan fuera
  del repositorio, en el directorio privado del envío (0700). `send_report.json` no se copia porque
  contiene rutas absolutas locales.
- **No se guardan** la clave (el exportador nunca la escribe), un cuerpo de error (no lo hubo) ni
  la respuesta de Hermes.
- `SHA256SUMS` cubre todo salvo este README.
