# Versión 2 de W2–W5 propuesta por Ollie — NO DESPLEGADA (22/10/2026)

**Estado:** propuesta contrastada **según el informe de Ollie**. **No está desplegada.** La escritura
de consultas guardadas (`create_dashboard_saved_query`) recibió **403 Forbidden** del proxy nginx.
Los widgets W2–W5 de la vista **siguen usando sus consultas originales**: las de
`../sql_original/`, con las consultas guardadas `01a16289-0ef0…`, `-1802…`, `-2296…` y `-2c58…`
según Ollie.

Claude **no ha hecho pruebas ni cambios remotos**. Esta carpeta separa tres cosas:

- las SQL propuestas (`sql/`);
- los resultados de lectura **reportados** por Ollie (en `ollie_response_v2_original.md`, sin
  verificar aquí);
- la revisión local estática (abajo).

## Archivos

- **`ollie_response_v2_original.md`:** la respuesta tal como Joel la pegó en la conversación, sin
  editar. Como viene del chat, no se garantiza que sea idéntica byte a byte a la interfaz de Ollie.
- **`sql/W2.sql`…`W5.sql`:** extraídas mecánicamente de ese archivo e idénticas a sus bloques.
  `sql_index.json` recoge los hashes, el estado `PROPOSED_BY_OLLIE_NOT_DEPLOYED` y las
  comprobaciones textuales.

## Resultados de lectura reportados por Ollie (no verificados por Claude)

Ventana del 23/08 al 22/10/2026, sólo lectura:

- **W2:** 1 fila del 21/10, con P50 = P90 = P99 = 2,665 s, n=1 y 0 intervalos inválidos.
- **W3:** 62 filas. El 21/10 tiene n=1 y «errors: cap» = 0; los otros 60 días aparecen como
  «sense dades».
- **W3 en una ventana vacía** (del 01 al 03/09): 3 filas «sense dades».
- **W4:** input 538, output 2 y cache_read 256. `cache_write` sale sin valor y con
  `zero_unconfirmed`. «sense retall».
- **W5:** 5 filas con valor y estado originales. «sense retall».
- **Control con un `project_id` falso:** 0 filas.
- **Estados observados:** `nonzero_normalized`, `zero_unconfirmed` y `derived_nonzero`.

Estos valores son coherentes con la captura local del 21/10 (538 / 2 / 256, ceros
`zero_unconfirmed` y 2,665 s). Pero son lecturas de Ollie, no ejecuciones de Claude.

## Revisión local (estática; sin ejecutar y sin ClickHouse)

- **`project_id` explícito:** cada consulta v2 lee su tabla base una vez y siempre con
  `project_id = '01a16007-0a3b-765f-9b27-e06052060b1b'` escrito en el SQL, así que el alcance se puede
  comprobar leyéndolo. Mantienen `captured-metadata` y las exclusiones de `synthetic` y
  `provenance-unknown`, y no usan coste, `usage` nativo ni los derivados `prompt_tokens`/`total_tokens`.
- **Respecto a la revisión de las originales** (`../sql_review.md`):

  | Widget | Qué resuelve | Qué queda |
  | --- | --- | --- |
  | W2 | Exige `end_time >= start_time`, da `n_invalid_interval` y explica la población | Nada que corregir. Incluye los spans con error, lo cual es válido si la población se declara (la etiqueta `poblacio` la describe), y usa `quantile` aproximado, que es una característica del cálculo y no un defecto |
  | W3 | Sólo spans `llm`, sin la serie de trazas; distingue «sense dades» (n=0) de «sense errors (n>0)» con `n` por día | Con ventanas largas genera una fila por día, lo cual es aceptable |
  | W4 | Las 20 ejecuciones **más recientes**, con `retall`/`n_spans_total` explícitos; sólo hay barra para `nonzero_normalized` numérico ≥0, así que `redacted`, `absent`, `zero_unconfirmed` y los estados desconocidos quedan sin barra pero conservan su estado | Si el exportador llega a emitir un cero confirmado, habría que admitir ese estado |
  | W5 | Recorte por ejecución (40), sin partir ninguna, con `retall` explícito | — |

- **Límites de esta revisión:** no se ha validado la sintaxis ni la semántica de las funciones de
  ventana, `arrayJoin`/`range` ni `JSONType` contra ClickHouse u Opik.

## Qué NO acreditan el `project_id` explícito ni el control negativo

- El `project_id` explícito y el control con un `project_id` falso (0 filas) muestran, **según
  Ollie**, que **estas consultas v2** discriminan por proyecto. **No acreditan el alcance de las
  consultas originales W1–W7 desplegadas**, que no llevan `project_id` y siguen dependiendo de un
  alcance externo sin verificar.
- Tampoco está verificado aquí que `01a16007-0a3b-765f-9b27-e06052060b1b` sea el identificador de
  `tfg-opik-hermes-real-20261021`. Que la vista pertenezca al proyecto correcto lo informa Ollie.

## Situación de la vista: histórico de los 16 widgets (resuelto después)

> **Actualización posterior reportada por Ollie** (transcripción trasladada por Joel, en
> `../ollie_update_view_11_widgets_transcription.md`): retiró los cinco widgets de validación y,
> tras releer la vista, **quedan 11**, guardados el 22/10/2026 a las 08:14:53 UTC. Las cinco
> consultas guardadas `01a162a8-…` siguen existiendo, pero ya ningún widget las usa. Lo que sigue
> se conserva como **histórico**.

- **La vista tiene 16 widgets en lugar de 11.** Una modificación del 22/10/2026 a las 08:09:26 UTC,
  hecha como `joowww`, añadió al final de «1. Resum» cinco widgets de validación, probablemente con
  «Add to dashboard»:
  - Latència LLM — P50/P90/P99;
  - Tokens d’entrada, sortida i memòria cau per execució;
  - Detall dels tokens — valor i estat;
  - **Prova negativa — project_id fals**;
  - Errors per data i tipus.
- Sus consultas guardadas (`01a162a8-…`) devuelven **404 al leerlas**, así que **su SQL y su
  `project_id` no están verificados**. Por eso **no se consideran la v2 desplegada**, aunque tengan los
  mismos títulos.
- *(Histórico)* Entonces quedaba pendiente quitar los duplicados. **Ya está resuelto**, según la
  actualización posterior.
- **Sigue pendiente:** si se quiere desplegar la v2, pegar cada SQL en el editor del widget
  original, recargando antes la vista. Hasta entonces, la v2 sigue **NO DESPLEGADA** y las
  comparaciones usan los W2–W5 originales, con sus límites documentados.
