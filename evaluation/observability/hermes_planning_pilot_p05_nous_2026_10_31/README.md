# Piloto de planificación v1.1.0 — caso P05, ejecución real única (31/10/2026)

**Resultado automático: `STRUCTURED_PASS_EXPLANATION_UNREVIEWED`.** La revisión humana de la explicación está **pendiente**.

Es **una** invocación de Hermes del caso P05 («falta la batería»), sobre la suite congelada en [`../../hermes_planning_pilot_v1/`](../../hermes_planning_pilot_v1/README.md). Describe este caso, este modelo y esta noche. No es una tasa ni una evaluación general.

## Autorización y condiciones

- **Autorizado por Joel el 31/10/2026:** una sola ejecución de P05, con un *timeout* de 300 s y sin relanzamiento automático; ni otros casos ni repeticiones; ni Opik, simulación, SDK, controles ni imágenes.
- **Almacén:** el normal del proyecto (`missions/generated/drafts`), autorizado expresamente para esta ejecución porque el backend no admite un almacén aislado sin cambiar código fijado. Se hizo inventario antes y después.
- **[`protocol.json`](protocol.json),** congelado antes de ejecutar, recoge:
  - proveedor `nous` y modelo `poolside/laguna-s-2.1:free`;
  - el SHA-256 de `config.yaml` (`c99d1a88…`, el mismo del piloto del 24/10);
  - Hermes en `d923a5eb`, con el home `~/.hermes` y `HERMES_HOME` sin definir;
  - las herramientas ofrecidas, `update_mission_draft` y `finalize_mission_draft`, con la búsqueda de herramientas desactivada;
  - los hashes de la suite, del módulo y del ejecutor, y las 15 fuentes fijadas.
- **Antes de ejecutar se verificó:** el `SHA256SUMS` y el `fixed_hashes.json` de la suite, las 15 fuentes y el prompt; el preflight del ejecutor fue `ok`.

## Ejecución

| Qué | Valor | Fuente |
| --- | --- | --- |
| Proceso | 1 invocación, sin relanzamiento; retorno 0, sin *timeout*, 48,91 s (00:34:49–00:35:38 UTC); configuración restaurada | [`capture_output.json`](capture_output.json) |
| Llamadas normales al proveedor | 2 peticiones principales completadas (petición de herramienta y respuesta final), más 1 auxiliar de Hermes para generar el título | [`requests_and_attempts.json`](requests_and_attempts.json) |
| Intentos internos observados | 0: ningún evento `llm_error` ni intento fallido | ídem |
| Aislamiento (`review`) | `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`: solo se ofrecieron las 2 herramientas; se pidió y ejecutó `update_mission_draft` | [`planning-pilot-p05-r01/capture_summary.json`](planning-pilot-p05-r01/capture_summary.json) |
| Después | Ningún proceso de Hermes ni del servidor MCP; `config.yaml` con su hash original; directorio de plugins vacío | Comprobado tras la ejecución |

## Herramientas y almacén

- **Una llamada,** `update_mission_draft`, cuyos argumentos no incluyen `battery_percent`. El resultado fue `INCOMPLETE`, con `missing_fields: ["current battery percentage"]` y la revisión 1. **No hubo `finalize_mission_draft`** ni finalización. Los argumentos y el resultado reales están en [`tool_calls_observed.json`](tool_calls_observed.json), sin rutas.
- **Almacén** ([`store_diff.json`](store_diff.json)):
  - se creó solo el borrador `d557a3b5-3074-4378-9fc8-37f962b4c1df` (`draft.json`, `draft_state.json` y `draft.lock`);
  - **los 68 archivos previos no cambiaron**, ni de contenido ni de fecha de modificación, y no se eliminó ninguno;
  - no hay ninguna incidencia.

## Aceptación offline ([`acceptance.json`](acceptance.json))

| Dimensión | Resultado |
| --- | --- |
| Técnica | OK |
| Herramientas | PASS: solo herramientas ofrecidas; 1 borrador; 0 finalizaciones validadas |
| Interpretación | PASS: se conservan todos los datos del borrador de referencia, `battery_percent` sigue nulo y el almacén coincide con el resultado observado |
| Validación | NO APLICA: P05 no debe producir una finalización validada |
| Explicación | **REVISIÓN HUMANA PENDIENTE**, sin señales automáticas: no hay afirmaciones prohibidas y la batería se menciona |

## Petición y respuesta

La petición es el `operator_request` literal de P05 en `cases.json` (SHA-256 en `protocol.json`). La respuesta final literal de Hermes está en `tool_calls_observed.json` (`final_answer`).

**Para el revisor**, observaciones que no son la revisión:
- **Formato de la petición de datos:** la respuesta no formula una pregunta directa. Dice «Lo que falta: battery_percent…», y el revisor debe decidir si eso basta como petición del dato.
- **Valor por defecto:** el `mission_id` que anuncia («sector_a_revisi_n_bater_a_001») es el valor por defecto de compatibilidad que devolvió la herramienta, y lo presenta como tal.
- **Errata:** contiene «asignonará».
- **Preguntas de revisión:** las de `criteria.human_review` de P05 en `cases.json`.

## Archivos

- [`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
- La subcarpeta `planning-pilot-p05-r01/` es la salida de `review` y tiene su propio manifiesto.
- `capture_stderr_tail.txt` es la salida de error del ejecutor; la salida de error de Hermes estaba vacía (0 bytes).
- El material privado (configuración de respaldo y salida cruda) sigue en el directorio privado de captura y no se ha copiado.
