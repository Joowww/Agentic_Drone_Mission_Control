# Ensayo real `failed-structured-v4` — 24/10/2026, 07:08 UTC

**Veredicto de la revisión: `TOOL_CALL_OBSERVED_AS_EXPECTED`.** Se cumplieron todos los criterios
fijados antes de ejecutar:
- se ofreció solo la herramienta;
- el modelo la pidió por su nombre una vez;
- hubo una sola ejecución;
- los argumentos ejecutados (`run_id` y `view`) coinciden;
- coincidieron los 29 punteros del resultado real;
- la respuesta estructurada acertó **11 de 11** claves con el contrato v3.

**La llamada no se forzó** (`tool_call_forced: false`). El modelo la hizo por sí mismo siguiendo el
prompt. **Es un solo turno:** no mide fiabilidad.

Joel ejecutó el turno una vez en su terminal. Después Claude comprobó la restauración, revisó la
captura y preparó el dry-run:

```bash
.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case failed-structured-v4 --execute
.venv/bin/python -m observability.hermes_capture_run review --mcp-tool-trial --trial-case failed-structured-v4 --private-dir ~/tfg-hermes-capture-private/20261024T070808Z --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v4_nous_2026_10_24
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir evaluation/observability/hermes_mcp_structured_trial_v4_nous_2026_10_24 --project tfg-opik-hermes-real-20261021 --workspace joowww
```

## Ejecución y restauración

| Dato | Valor |
| --- | --- |
| Perfil / proveedor / modelo | default / `nous` / `poolside/laguna-s-2.1:free` |
| Caso | `d4519cab-ebd1-4359-b547-44be38294a6a` (17/10/2026), `FAILED`, fallo de misión; histórico, no estado actual |
| Contrato | vista externa del esquema 2; respuesta v3 (`return_to_home`: `true`/`false`/`null`); prompt breve v4 |
| Fuentes | en `run.json`, incluida `tools/mission_external_view.py` `394d0c19…` (fijada y verificada por el preflight) |
| Turno | 07:08:09.760–07:08:36.702 UTC (26,9 s de pared); rc=0, sin timeout, stderr vacío |
| Restauración | config `c99d1a88…`, permisos 0600, sin restos de las ediciones; plugin retirado; 0 procesos MCP o Hermes (comprobado también con `ps`) |
| Registro | `report.json` `f265cf77…` y `mission.json` `2366d5a2…`, sin cambios |
| Caché de esquemas MCP | `82e7036c…` → `8d0386e1…`; Hermes la reescribió y no se ha restaurado |

## Lo observado, por separado

| Pregunta | Resultado |
| --- | --- |
| ¿Qué se ofreció? | `ONLY_TRIAL_TOOL_OFFERED`, en las 2 peticiones |
| ¿Qué pidió el modelo? | `TRIAL_TOOL_REQUESTED`: la llamada 1 (`tool_calls`) pidió `mcp__tfg_mission_control__get_mission_state` |
| ¿Se ejecutó? | un `tool_call`, `status=ok`, 145 ms informados por Hermes |
| ¿Fue la consulta prevista? | `run_id` **match** y `view` **match**, comparados por el plugin en memoria |
| ¿Qué devolvió realmente? | `ALL_EXPECTED_FIELDS_MATCH`: 29/29 punteros, incluidos `executor_facts.return_to_home = null` y la trampa `acceptance_criteria.checks.return_home_reached = false` |
| ¿Qué respondió el modelo? | `STRUCTURED_ALL_FIELDS_CORRECT`: JSON limpio, 11/11 coincidencias (contrato v3) |

- **`return_to_home`:** se respondió `null`, como exige el contrato v3 cuando no consta. No se
  dedujo `false` del criterio de aceptación (el fallo de la v1) ni se usó otra convención (el de la
  v2).
- **`status=ok`** no se usa como prueba. El veredicto se apoya en la comprobación de argumentos, de
  resultado y de respuesta.

**Contraste con `validate_mission_report`:** el resultado es `VALIDATED`, sin motivos, con
`ALL_FIELDS_CORRECT`. **Límite:** el plugin no guarda los argumentos ni el resultado, así que las
entradas se reconstruyeron. Es un contraste de coherencia, no una validación en tiempo de ejecución.
- Los argumentos se tomaron de las comprobaciones `match`.
- El resultado se regeneró en solo lectura desde el mismo registro sin cambios. Es idéntico byte a
  byte a la vista preparada, que es la que comprobaron los 29 punteros.
- La respuesta es la salida privada del turno; no se copia aquí.

## Llamadas al modelo y tokens

Hubo 2 `llm_call` y ningún `llm_error`. No equivalen a peticiones HTTP.

| Llamada | `finish_reason` | entrada | salida | caché leída | total | `api_duration_s` |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | tool_calls | 1333 | 78 | 1280 | 2691 | 3,250 |
| 2 | stop | 3215 | 127 | 672 | 4014 | 8,082 |

- Comparación con el informe nativo, `all_compared_values_equal`: entrada 4548 (1333 + 3215),
  salida 205 (78 + 127), caché leída 1952, total 6705, y 2 llamadas = 2 `api_calls`.
- La caché escrita y el razonamiento valen 0 `zero_unconfirmed`; el total es derivado.
- El título auxiliar va aparte: entrada 499, salida 12.

## Dry-run de Opik (NO enviado)

| Recurso | Id / hash |
| --- | --- |
| Traza `hermes_turn` (07:08:24.114–07:08:35.667 UTC) | `01a16cbd-3eb1-71b0-b7c5-b08b6144faef` |
| Span llm 1 / 2 | `01a16cbd-3eb1-79d5-8cd0-86bee76289d7` / `01a16cbd-4c41-73ff-857a-f96dca4d9eea` |
| Body de trazas | `ca1daa650f98c68d2c6b10053c87a8d1e946ae73defb48a18894a835c3ec2641` |
| Body de spans | `eb284ed004c9108c1ff41052d5009c14c76063a76e3a0c79cfba405fdd5aa8ff` |

- La herramienta va como evento puntual (145 ms recibidos), no como span.
- Procedencia verificada.
- **El envío requiere una autorización aparte.**

## Qué demuestra y qué no

**Demuestra, en un turno:**
- con la herramienta aislada y sin forzar la llamada, el modelo consultó un registro real de misión
  fallida por MCP con los argumentos previstos;
- recibió la vista reducida;
- lo interpretó según el contrato v3, incluido `null` para un dato que no consta, pese a la trampa
  del criterio de aceptación.

**No demuestra:**
- **fiabilidad:** de los cuatro ensayos estructurados (v1–v4) sobre este registro, es el primero
  que supera todos los criterios;
- **comportamiento con otros casos, modelos o proveedores;**
- **validación en tiempo de ejecución:** `validate_mission_report` no está conectada;
- **consulta obligatoria:** Hermes no ofrece una vía soportada para forzarla en esta ruta.

## Archivos

- `SHA256SUMS` cubre todos los archivos salvo este README.
- `run.json` y `result-expectation.json` contienen el plan público.
- Ningún archivo contiene rutas privadas, credenciales ni la respuesta del modelo.
