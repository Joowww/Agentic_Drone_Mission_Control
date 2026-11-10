# Ensayo real `failed-structured-v2` — 23/10/2026, 08:42 UTC

**Veredicto de la revisión: `FINAL_RESPONSE_NOT_AS_EXPECTED`.**
- Aislamiento, petición, ejecución, consulta ejecutada y resultado real (29/29): correctos.
- Respuesta: 10/11 claves. Falló de nuevo `return_to_home`, pero **por una causa distinta a la de
  la v1**: el modelo copió el `null` del campo designado en lugar de escribir `"UNKNOWN"`.
- **Ya no dedujo `false`** del criterio de aceptación.
- No es un éxito según los criterios fijados en la
  [preparación](../hermes_mcp_structured_trial_v2_prepared_2026_10_23/README.md). No se repite.

Joel ejecutó el turno una vez en su terminal. Después Claude comprobó la restauración, revisó la
captura y preparó el dry-run:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v2 --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --trial-case failed-structured-v2 --private-dir ~/tfg-hermes-capture-private/20261023T084206Z --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v2_nous_2026_10_23
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v2_nous_2026_10_23 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Ejecución y restauración

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free` |
| Caso | `d4519cab-ebd1-4359-b547-44be38294a6a` (17/10/2026), `FAILED`, fallo de misión; histórico, no estado actual |
| Herramienta / vista | solo `get_mission_state`, `view="external"` (esquema 2), Tool Search desactivado |
| Fuentes ejecutadas | `tools/hermes_mcp_server.py` `24068e72…` y `tools/mission_state.py` `e66dd901…` (en `run.json`); `tools/mission_external_view.py` `394d0c19…`, que **no** está en `run.json` porque `TRIAL_SERVER_SOURCES` no lo incluye (se modificó por última vez a las 08:34 UTC, antes del turno) |
| Turno | 08:42:06.791–08:42:27.846 UTC (21,0 s de pared); rc=0, sin timeout, stderr vacío |
| Restauración | config `c99d1a88…`, permisos 0600, sin restos de las tres ediciones; plugin retirado; 0 procesos MCP o Hermes (comprobado también con `ps`) |
| Registro consultado | `report.json` `f265cf77…` y `mission.json` `2366d5a2…`, sin cambios |
| Caché de esquemas MCP | `a977ceba…` → `33daca44…`; Hermes la reescribió y no se ha restaurado |

## Lo observado, por separado

| Pregunta | Resultado |
| --- | --- |
| ¿Qué se ofreció? | `ONLY_TRIAL_TOOL_OFFERED`, en las 2 peticiones |
| ¿Qué pidió el modelo? | `TRIAL_TOOL_REQUESTED`, una vez, por su nombre |
| ¿Se ejecutó? | un `tool_call`, `status=ok`, 76 ms informados por Hermes |
| ¿Fue la consulta prevista? | `run_id` **match** y `view` **match** |
| ¿Qué devolvió realmente? | `ALL_EXPECTED_FIELDS_MATCH`: 29/29 punteros, incluida la trampa `acceptance_criteria.checks.return_home_reached = false` y `executor_facts.return_to_home = null` |
| ¿Qué respondió el modelo? | `STRUCTURED_FIELDS_INCORRECT`: JSON limpio, sin bloque de código; 10 coincidencias y 1 fallo |

**Clave fallida: `return_to_home`.** Lo esperado era `"UNKNOWN"`, porque el campo designado es
`null`.

- **Lo que respondió el modelo:** `null`, según una revisión local de la respuesta privada que solo
  leyó esa clave. La respuesta no se copia aquí.
- **Etiqueta registrada:** `capture_summary.json` dice `invented_value`. **Esa etiqueta es
  inexacta:** se generó antes de que el evaluador distinguiera este caso, y el modelo no inventó
  ningún valor, sino que copió el `null` de origen.
- **Corrección posterior:** el evaluador clasifica ahora este caso como `null_instead_of_unknown`,
  con su test de regresión. Esta evidencia **no se ha regenerado** y su veredicto no cambia, porque
  `null` no es ni un booleano ni `"UNKNOWN"` y el contrato exigía `"UNKNOWN"`.

**Comparación con la v1:**

| Ensayo | `return_to_home` | Lectura |
| --- | --- | --- |
| v1 (22/10, 17:40) | `false` | deducción a partir de un criterio de aceptación |
| v2 (23/10, 08:42) | `null` | lectura del campo correcto sin aplicar la regla `null` → `"UNKNOWN"` |

La separación de grupos y la designación de campos de origen eliminaron la deducción indebida en
este turno. Queda pendiente que el modelo respete la convención de formato. Son dos turnos: **no
es una medida de fiabilidad.**

## Llamadas al modelo y tokens

Hubo 2 `llm_call` y ningún `llm_error`. No equivalen a peticiones HTTP.

| Llamada | `finish_reason` | entrada | salida | caché leída | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | tool_calls | 2539 | 78 | 224 | 2841 | 6,072 |
| 2 | stop | 3365 | 174 | 672 | 4211 | 4,764 |

- Comparación con el informe nativo, `all_compared_values_equal`: entrada 5904, salida 252 (78 + 174),
  caché leída 896, total 7052, y 2 llamadas = 2 `api_calls`. Corregido el 23/10: esta línea decía
  "254", un valor copiado por error del ensayo v1 (78 + 176). Los archivos de captura y el informe
  nativo siempre dijeron 252.
- La caché escrita y el razonamiento valen 0 `zero_unconfirmed`.
- El título auxiliar va aparte, solo nativo: entrada 335, salida 12.

## Dry-run de Opik (NO enviado)

| Recurso | Id / hash |
| --- | --- |
| Traza `hermes_turn` (08:42:16.215–08:42:27.189 UTC) | `01a167ec-d317-7b4c-8a6b-db32f6612006` |
| Span llm 1 / 2 | `01a167ec-d317-70a8-970e-2c588930d48d` / `01a167ec-eb58-71b1-834e-03ca94f93aac` |
| Body de trazas | `65e8c7b38e24a6962f6945145e9f455f8bba8c62eee9da3eac77455638b13237` |
| Body de spans | `0c0cd1ff13b442531fdbac17566751209f2c08e06df34bdc448bb11b29be0652` |

- Procedencia verificada; sin retenidas, errores ni avisos.
- La herramienta va como evento puntual, no como span.
- La evaluación de la respuesta no se envía.
- **El envío requiere una autorización aparte.**

## Posibles ajustes (no aplicados; requieren nueva preparación y autorización)

- Hacer más explícito el formato en el prompt, por ejemplo con "nunca escribas null".
- Cambiar el contrato para aceptar `null` como sinónimo de desconocido. Es una decisión de diseño,
  porque en JSON `null` es el valor nativo para "no consta".

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README.
- `run.json` y `result-expectation.json` contienen el plan público.
- Ningún archivo contiene rutas privadas, credenciales ni la respuesta del modelo.
