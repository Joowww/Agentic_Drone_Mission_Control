# Ensayo real `failed-structured-v3` — 23/10/2026, 08:53 UTC

**Veredicto de la revisión: `TOOL_NOT_REQUESTED`.**
- La herramienta se ofreció correctamente, pero **el modelo no la llamó**: respondió directamente
  en una única llamada.
- No hubo ejecución, comprobación de argumentos ni resultado real.
- No es un éxito; el contrato v3 no llegó a probarse. **No se repite.**

Joel ejecutó el turno una vez en su terminal. Después Claude comprobó la restauración, revisó la
captura y preparó el dry-run:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v3 --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --trial-case failed-structured-v3 --private-dir ~/tfg-hermes-capture-private/20261023T085312Z --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v3_nous_2026_10_23
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v3_nous_2026_10_23 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Ejecución y restauración

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free` |
| Caso | `d4519cab-…`, `FAILED` (histórico); contrato de respuesta **v3** (`return_to_home`: `true`/`false`/`null`) |
| Preparación | [v3](../hermes_mcp_structured_trial_v3_prepared_2026_10_23/SHA256SUMS); resultado y expectativa idénticos a los de la [v2](../hermes_mcp_structured_trial_v2_prepared_2026_10_23/README.md) |
| Fuentes ejecutadas | ya en `run.json`, incluida por primera vez `tools/mission_external_view.py` `394d0c19…` (fijada y verificada por el preflight) |
| Turno | 08:53:13.487–08:53:26.037 UTC (12,5 s de pared); rc=0, sin timeout, stderr vacío, stdout de 340 bytes |
| Restauración | config `c99d1a88…`, permisos 0600, sin restos de las ediciones; plugin retirado; 0 procesos MCP o Hermes (comprobado también con `ps`) |
| Registro | `report.json` `f265cf77…` y `mission.json` `2366d5a2…`, sin cambios |
| Caché de esquemas MCP | `33daca44…` → `82e7036c…`; Hermes la reescribió, aunque la herramienta no se llamó |

## Lo observado, por separado

| Pregunta | Resultado |
| --- | --- |
| ¿Qué se ofreció? | `ONLY_TRIAL_TOOL_OFFERED`: 1 petición, solo `mcp__tfg_mission_control__get_mission_state` |
| ¿Qué pidió el modelo? | `NOT_REQUESTED`: `finish_reason=stop`, `assistant_tool_call_count=0` |
| ¿Se ejecutó? | `NOT_EXECUTED`: ningún `tool_call` |
| ¿Fue la consulta prevista? | sin datos: no hubo llamada |
| ¿Qué devolvió realmente? | `NOT_RECORDED`: no hay registro de comprobación de resultado |
| ¿Qué respondió el modelo? | un objeto JSON con las 11 claves, sin haber consultado nada: 4 coincidencias, 2 discrepancias y 5 `unknown_but_recorded` |

- **Las 4 coincidencias no prueban nada:**
  - `run_id` venía en el prompt;
  - `return_to_home: null`, `mission_landed_event_recorded` y `current_availability` coinciden sin
    ninguna base observada.
- **Cinco datos que sí constan en el registro** aparecieron como `UNKNOWN`: estado, misión, vehículo,
  vehículo simulado y aterrizaje de recuperación.
- Las dos listas de waypoints no coinciden.
- **Por qué el ensayo no da éxito:** el veredicto exige herramienta pedida, ejecutada, argumentos y
  resultado real, además de la respuesta. Esta respuesta, en parte coincidente, no puede dar éxito,
  porque no se basa en ninguna consulta.

**Causa:** no se conoce. La captura no guarda el razonamiento ni el texto del modelo, y no se
deduce ninguna. **Una hipótesis sin verificar** es que el prompt v3, más largo y con más
instrucciones de formato, influyera. Un solo turno no permite atribuirlo.

## Llamadas al modelo y tokens

| Llamada | `finish_reason` | entrada | salida | caché leída | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | stop | 2591 | 99 | 224 | 2914 | 4,046 |

- La comparación con el informe nativo es `all_compared_values_equal`, con una sola llamada y
  alcance `main_turn_only`.
- La caché escrita y el razonamiento valen 0 `zero_unconfirmed`; el total es derivado.
- El título auxiliar va aparte: entrada 559, salida 14.
- Las llamadas no son peticiones HTTP.

## Dry-run de Opik (NO enviado)

| Recurso | Id / hash |
| --- | --- |
| Traza `hermes_turn` (08:53:21.483–08:53:25.529 UTC) | `01a167f6-f9cb-7fd0-ade3-4c76301f0591` |
| Span llm | `01a167f6-f9cb-72a0-8378-130e88502bb4` |
| Body de trazas | `0e79ac3fc494f3d20982a2828d2313ccbce4b83db030bf3d7dab5a960e77e1af` |
| Body de spans | `cb6b007b62ca228377c3936a81db3ae28429227ac29dfe0c5907b4abde2bbc97` |

- Sin eventos puntuales de herramienta.
- Procedencia verificada.
- **El envío requiere una autorización aparte.**

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README.
- `run.json` y `result-expectation.json` contienen el plan público.
- Ningún archivo contiene rutas privadas, credenciales ni la respuesta del modelo.
