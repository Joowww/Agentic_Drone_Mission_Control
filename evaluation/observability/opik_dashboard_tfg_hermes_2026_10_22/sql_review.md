# Revisión local de las siete consultas SQL de Ollie (22/10/2026)

**Alcance:** revisión estática de los archivos `sql_original/W1.sql`…`W7.sql`, extraídos
mecánicamente de `ollie_response_original.md`, contra el formato real que envía el exportador
(`hermes_real_capture_nous_2026_10_21/opik_dry_run.json` y `observability/opik_export.py`).

- **No se ha ejecutado** ninguna consulta y **no hay validación contra ClickHouse**: no hay
  ClickHouse local ni acceso remoto.
- Las comprobaciones textuales están en `sql_index.json`.
- Las correcciones propuestas están **aparte**, en `proposed_corrections_NOT_DEPLOYED.sql`.

## Hechos comunes a las siete

| Punto | Resultado local |
| --- | --- |
| Filtro de procedencia | Las 7 incluyen `has(tags,'captured-metadata')`, `NOT has(tags,'synthetic')` y `NOT has(tags,'provenance-unknown')` en **todas** sus subconsultas. Nuestro exportador pone esas etiquetas tanto en trazas como en spans |
| Alcance de proyecto | **Ninguna lleva `project_id`**. Ollie informa de que se aplica fuera, con el proyecto `01a16007-0a3b-765f-9b27-e06052060b1b`, pero **no está verificado**. Aunque fallara, el filtro por etiquetas sigue excluyendo lo sintético y lo desconocido; sólo podrían entrar capturas reales de otros proyectos, y hoy no existen |
| Filtro `source IN ('sdk','unknown')` | El exportador **no envía `source`**. Que nuestras filas cumplan el filtro depende del valor que asigne el servidor. Ver datos en la interfaz es compatible con ello, pero no lo verifica. Si el servidor usara otro valor, las consultas quedarían vacías |
| Rango | Todas usan `{{window_start}}`/`{{window_end}}` sobre `start_time` |
| Campos usados | `metadata.tfg_run_id`, `tfg_data_kind`, `tfg_usage_source` y `tfg_usage.<campo>.value/.status` existen en el payload real. `error_info` sólo existe en spans |
| Totales derivados | Ninguna consulta usa `prompt_tokens` ni `total_tokens`, así que **no hay doble conteo** de derivados (tampoco se muestran) |

## Por consulta

**W1 — volumen diario.** Es correcto para lo que muestra: trazas y spans `llm` por día. Los días
sin datos no generan fila, lo cual es aceptable para un recuento. Sin defectos.

**W2 — latencia P50/P90/P99.**
- *Correcto:*
  - usa `start_time`/`end_time` de spans `llm` (el intervalo medido por Hermes);
  - excluye `end_time` nulo o cero;
  - devuelve `n` por día.
- *Defecto:*
  - **no exige `end_time >= start_time`**: un intervalo inválido entraría con duración negativa.
    Nuestro exportador no los genera, pero la consulta no se protege.
- *Características que hay que declarar (no son defectos en sí):*
  - **incluye los spans con `error_info`** (`llm_error`). Es **válido si se declara la población**
    («todas las llamadas LLM, también las fallidas»). Excluirlos, como hace P-W2, es una opción para
    medir sólo las respuestas correctas, no una corrección obligatoria;
  - `quantile()` de ClickHouse es **aproximado** (muestreo). Es una característica del cálculo, no un
    defecto: conviene indicarlo, y usar uno exacto sólo si se necesita exactitud;
  - `dateDiff('millisecond')` trunca a ms, lo cual es aceptable.
- **Propuesta P-W2** (opcional en sus dos últimos puntos).
- *Aclaración posterior (22/10/2026):* esta sección se reformuló para no presentar como defectos la
  inclusión de errores y el cuantil aproximado. El SQL revisado no cambia.

**W3 — errores.**
- **Defecto (confirmado por el formato):**
  - la serie `trace:` es estructuralmente «(sin error)» con 0, porque el exportador **nunca** pone
    `error_info` en las trazas. Sugiere que se evaluaron errores de traza cuando no existen;
  - **no distingue «sin datos» de «cero errores»** (ya lo señaló Ollie): sin muestras no hay filas,
    y con muestras sin errores aparece una barra de altura 0;
  - **no tiene tamaño de muestra**: falta el número de spans evaluados;
  - en spans no filtra `type='llm'`. Hoy todos nuestros spans son `llm`, así que no es un defecto
    de datos, pero sí de alcance.
- **Propuesta P-W3.**

**W4 — tokens por ejecución (gráfico).**
- *Correcto:*
  - conserva el estado: en `series_label` aparece campo + `status`;
  - `zero_unconfirmed` y `absent` pasan a NULL (sin barra) en lugar de 0;
  - un `tfg_usage` nulo (uso ausente) da `absent` en cada campo;
  - `n_spans` cuenta todos los spans del rango, no sólo los mostrados.
- *Defectos o límites:*
  - **`LIMIT 400` = 100 spans × 4 campos**, con orden **ascendente**: si hay más de 100 spans, se
    muestran los **más antiguos** y se recortan los recientes **sin aviso**. `n_spans` sí da el
    total, pero nada indica que haya recorte;
  - un estado `redacted` (valor nulo en origen) produce `'null'` como texto en lugar de NULL;
  - no incluye `reasoning_tokens` (sólo aparece en W5).
- **Propuesta P-W4.**

**W5 — detalle de tokens (tabla).**
- *Correcto:* cinco componentes con su `value` y `status` reales, `absent` explícito y `n_spans`
  total.
- *Límite:* **`LIMIT 200` = 40 spans × 5 campos**, los más recientes. Con más de 40 spans recorta sin
  indicarlo, aunque `n_spans` muestre el total.
- **Propuesta P-W5.**

**W6 — procedencia.** Es correcto como recuento de lo que pasa el filtro. **Límite de diseño:** al
filtrar `captured-metadata`, sólo puede mostrar `captured_hermes_metadata`, así que no detecta
contaminación. Para eso hace falta un control sin filtro de etiquetas (el «6c» del diseño de
referencia), que no está entre los siete. **Propuesta P-C1.**

**W7 — cobertura de `tfg_usage_source`.** Es correcto: recuento, total y proporción sobre spans `llm`.
Con 0 spans no hay filas, así que no hay división por cero. Sin defectos.

## Tamaño de muestra y límites `LIMIT`

| Widget | Tamaño de muestra mostrado | ¿Puede recortar? |
| --- | --- | --- |
| W1 | Recuento diario | No |
| W2 | `n` por día | No |
| W3 | **Ninguno** | No, pero no distingue «sin datos» |
| W4 | `n_spans` (total) | **Sí**, por encima de 100 spans; quita los recientes sin aviso |
| W5 | `n_spans` (total) | **Sí**, por encima de 40 spans; sin aviso |
| W6 | Recuentos | No |
| W7 | `total_llm_spans` | No |

Con los datos actuales (1 traza, 1 span) **ningún límite recorta**. El riesgo aparece al acumular
capturas.
