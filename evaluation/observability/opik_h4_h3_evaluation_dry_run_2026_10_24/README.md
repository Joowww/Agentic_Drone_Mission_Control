# H4: vista previa de H3 con su evaluación `NOT_VALIDATED`, NO enviada — 24/10/2026

**Estado: solo dry-run.** No se ha enviado nada, no se ha usado ninguna clave y no se ha
contactado con Opik. Destino previsto: workspace `joowww`, proyecto
`tfg-opik-hermes-real-20261021`, `--provenance captured`. Es el mismo destino que el envío de H1.

## Qué cambia respecto a la vista previa sin etiqueta

La vista previa anterior es
[opik_h4_dry_run_agri_2026_10_24/h3_opik_dry_run.json](../opik_h4_dry_run_agri_2026_10_24/README.md),
que se conserva sin cambios. Esta añade la entrada opcional `--evaluation-file` de
`observability.opik_export`, a partir de la aceptación determinista real de H3
([accept_h3.json](../agri_scenario_h3_nous_2026_10_24/README.md)).

La traza (y solo la traza) recibe:
- `metadata.tfg_evaluation`:
  `{"acceptance": "NOT_VALIDATED", "failed_keys": ["r1_movement_authorized"], "evidence_ref": "sha256:80858822326bcadd", "evidence_kind": "local_deterministic_acceptance_result", "answer_exported": false}`;
- la etiqueta `acceptance:NOT_VALIDATED`, junto a las tres que ya tenía.

| | Sin evaluación | Con evaluación |
| --- | --- | --- |
| Id de la traza | `01a16e0d-eb87-71c9-a8b6-626d08ba0e23` | igual |
| Body de trazas (SHA-256) | `38d0af127d10bf3c5d3d49d8cfd772a7ff3897e0c96dc1ad8b20c26e98109103` | **`130430933fc1a984d4bef77b64a59d6ae112dfc434e9a370a58b7438caa04058`** |
| Body de spans (SHA-256) | `5ed58da0ae92abd31ba3454f5ba85fee42ff8b224abb4477518c5d1a8b229748` | igual (2 spans `llm_call`) |
| Tamaño del payload | 9130 bytes | 9379 bytes |

- **Referencia a la evidencia:** `evidence_ref` lleva los primeros 16 hexadecimales del SHA-256 de
  `accept_h3.json` (`80858822326bcaddeafc671b70248f90722c002bfd9decc2599f2b92ca9af4c9`). Usa la misma
  convención `sha256:` que las referencias del plugin.
- **Por qué no el hash completo:** el detector de secretos del exportador rechaza las cadenas
  hexadecimales de 32 o más caracteres, y no se ha debilitado.
- **H1:** sin evaluación, conserva exactamente los hashes enviados (`bb8019dd…`, `17429090…`). Hay un
  test que lo comprueba.

## Revisión del payload

| Riesgo | Resultado |
| --- | --- |
| Respuesta de H3, su explicación o el texto erróneo («autoriza mover») | No hay. `answer_exported: false` |
| Valores esperados, POI, vehículos, estado de `R1` | No hay |
| Rutas locales, nombre del archivo de evidencia, `session_id` | No hay |
| Secretos, credenciales o hashes completos | No hay |
| Feedback scores de Opik | No se usan: no están implementadas ni verificadas en el repositorio |

La respuesta completa de H3 se conserva en la evidencia local (`hermes_stdout.txt` y
`accept_h3.json`), que no se ha modificado. En Opik, la etiqueta y el metadato indican que la
evaluación determinista **rechazó** la respuesta, sin reproducir la afirmación errónea.

## Comando soportado para un futuro dry-run (no envía nada)

```bash
.venv/bin/python -m observability.opik_export evaluation/observability/agri_scenario_h3_nous_2026_10_24/capture/hermes-events-2026-10-24.jsonl --project tfg-opik-hermes-real-20261021 --workspace joowww --provenance captured --evaluation-file evaluation/observability/agri_scenario_h3_nous_2026_10_24/accept_h3.json
```

Cualquier envío de H3 necesita una autorización aparte que nombre el destino y estos dos hashes.
Se haría con el mismo procedimiento que el envío de H1, añadiendo `--evaluation-file`, y nunca de
forma automática.

`SHA256SUMS` cubre todo salvo este README.
