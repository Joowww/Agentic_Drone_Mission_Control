No he guardado ninguna corrección. El proxy bloquea la creación de consultas guardadas: `create_dashboard_saved_query` devuelve 403 Forbidden de nginx. El script se detuvo antes de tocar la vista, y no he intentado sortear el bloqueo. Hay además un problema nuevo: la vista tiene ahora 16 widgets en lugar de 11, y yo no los he añadido.

## Qué ha pasado con la vista

En la última lectura, la vista tiene una modificación del 22/10/2026 a las 08:09:26 UTC, hecha como `joowww`. Esa modificación añadió cinco widgets nuevos al final de **1. Resum**. Son los cinco gráficos de validación que dibujé en el chat. Lo más probable es que se añadieran desde el botón “Add to dashboard” de sus tarjetas, porque yo no llamé a la herramienta para añadir widgets.

| Widget añadido (id) | Consulta guardada |
|---|---|
| Latència LLM — P50/P90/P99 (`…3f566dcc673c`) | `01a162a8-4b42-74b5-8570-2da6df06b937` |
| Tokens d’entrada, sortida i memòria cau per execució (`…ae44f05074c4`) | `01a162a8-537d-7476-b389-a865c3a1371a` |
| Detall dels tokens — valor i estat (`…7ef7f4f89cbe`) | `01a162a8-5bc1-7235-8346-581df5af43ea` |
| **Prova negativa — project_id fals** (`…ba39d76ca361`) | `01a162a8-60d1-7366-ad3d-57b0a723c645` |
| Errors per data i tipus (`…6ebbdbde2cac`) | `01a162a8-68d0-700b-8c29-bc40d6f57b6b` |

Los W2–W5 originales siguen como estaban, con sus consultas, posiciones y tamaños: `01a16289-0ef0…`, `-1802…`, `-2296…` y `-2c58…`. Los cuatro indicadores y los títulos en catalán también se mantienen.

No he quitado los widgets duplicados ni he reapuntado W2–W5 a esas consultas nuevas, por dos razones:
- No autorizaste eliminar widgets.
- No puedo leer el SQL ni el `project_id` de esas consultas guardadas, porque su lectura devuelve 404. Lo más probable es que contengan las SQL revisadas, pero no lo puedo verificar.

## Comprobaciones previas al despliegue (solo lectura, ventana 23/08–22/10/2026)

| Consulta | Resultado |
|---|---|
| W2 | 1 fila del 21/10: P50 = P90 = P99 = 2,665 s, n=1, 0 intervalos inválidos, 1 crida LLM en el proyecto. Etiqueta: “totes les crides LLM del projecte a la finestra (1)” |
| W3 | 62 filas. El 21/10 tiene “mostres avaluades (n)” = 1 y “errors: cap” = 0, con estado “sense errors (n>0)”. Los otros 60 días salen como “sense dades”, con n=0 y sin valor |
| W3 en ventana vacía (01–03/09) | 3 filas, todas “sense dades” con n=0 |
| W4 | 4 filas: input 538, output 2, cache_read 256. cache_write sale sin valor y conserva `zero_unconfirmed`. Columna “sense retall”, 1 de 1 ejecuciones |
| W5 | 5 filas con el valor y el estado originales. cache_write y reasoning salen como 0 con `zero_unconfirmed`. “sense retall”, 1 de 1 |
| Control con `project_id` falso | 0 filas |
| Estados observados en el proyecto | `nonzero_normalized`, `zero_unconfirmed`, `derived_nonzero` |

## SQL final (no desplegado)

En todas, el filtro de proyecto va escrito en el propio SQL, así que se puede comprobar leyéndolo. Los filtros de procedencia se mantienen, y no se usan costes ni `usage` nativo.

**W2: Latència LLM — P50/P90/P99**
```sql
WITH
 base AS (
  SELECT id, start_time, end_time, tags FROM spans FINAL
  WHERE project_id = '01a16007-0a3b-765f-9b27-e06052060b1b' AND type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
 ),
 pop AS (
  SELECT *, (end_time IS NOT NULL AND end_time > toDateTime64(0,6) AND end_time >= start_time) AS valid
  FROM base
  WHERE has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 ),
 tot AS (
  SELECT (SELECT count() FROM base) AS n_all, (SELECT countIf(valid) FROM pop) AS n_valid, (SELECT countIf(NOT valid) FROM pop) AS n_invalid
 )
SELECT toJSONString(map(
 'date', toString(toDate(start_time)),
 'p50_s', toString(round(quantile(0.5)(dateDiff('millisecond', start_time, end_time) / 1000.0), 3)),
 'p90_s', toString(round(quantile(0.9)(dateDiff('millisecond', start_time, end_time) / 1000.0), 3)),
 'p99_s', toString(round(quantile(0.99)(dateDiff('millisecond', start_time, end_time) / 1000.0), 3)),
 'n', toString(count()),
 'n_invalid_interval', toString(any(tot.n_invalid)),
 'n_all_llm_spans', toString(any(tot.n_all)),
 'poblacio', if(any(tot.n_valid) = any(tot.n_all),
   concat('totes les crides LLM del projecte a la finestra (', toString(any(tot.n_all)), ')'),
   concat('població filtrada: ', toString(any(tot.n_valid)), ' de ', toString(any(tot.n_all)), ' crides LLM (captured-metadata, sense synthetic/provenance-unknown, interval vàlid)'))
)) AS result
FROM pop CROSS JOIN tot
WHERE valid
GROUP BY toDate(start_time)
ORDER BY toDate(start_time)
```

**W3: Errors per data i tipus** (solo spans LLM; ya no incluye la serie de errores de trazas)
```sql
WITH
 pop AS (
  SELECT toDate(start_time) AS d, error_info FROM spans FINAL
  WHERE project_id = '01a16007-0a3b-765f-9b27-e06052060b1b' AND type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 ),
 days AS (
  SELECT arrayJoin(arrayMap(i -> toDate({{window_start}}) + i, range(toUInt32(dateDiff('day', toDate({{window_start}}), toDate({{window_end}})) + 1)))) AS d
 ),
 agg AS (SELECT d, count() AS n, countIf(error_info != '') AS errs FROM pop GROUP BY d),
 per_day AS (
  SELECT days.d AS d, ifNull(agg.n, 0) AS n, ifNull(agg.errs, 0) AS errs
  FROM days LEFT JOIN agg ON days.d = agg.d
 ),
 by_type AS (
  SELECT d, if(JSONExtractString(error_info,'exception_type') = '', '(tipus desconegut)', JSONExtractString(error_info,'exception_type')) AS et, count() AS c
  FROM pop WHERE error_info != '' GROUP BY d, et
 ),
 rows AS (
  SELECT d, 'mostres avaluades (n)' AS series, toNullable(toFloat64(n)) AS value, n, errs FROM per_day WHERE n > 0
  UNION ALL
  SELECT p.d AS d, concat('errors: ', b.et) AS series, toNullable(toFloat64(b.c)) AS value, p.n AS n, p.errs AS errs FROM by_type AS b INNER JOIN per_day AS p ON b.d = p.d
  UNION ALL
  SELECT d, 'errors: cap' AS series, toNullable(0.0) AS value, n, errs FROM per_day WHERE n > 0 AND errs = 0
  UNION ALL
  SELECT d, 'sense dades' AS series, CAST(NULL, 'Nullable(Float64)') AS value, n, errs FROM per_day WHERE n = 0
 )
SELECT toJSONString(map(
 'date', toString(d),
 'series', series,
 'value', if(isNull(value), NULL, toString(value)),
 'n', toString(n),
 'estat', multiIf(n = 0, 'sense dades', errs = 0, 'sense errors (n>0)', 'amb errors')
)) AS result
FROM rows
ORDER BY d, series
```

**W4: Tokens d’entrada, sortida i memòria cau per execució** (máximo las 20 ejecuciones más recientes; el recorte se indica en la columna `retall`)
```sql
WITH
 sel AS (
  SELECT id, start_time, JSONExtractString(metadata,'tfg_run_id') AS run_id, JSONExtractRaw(metadata,'tfg_usage') AS tfg
  FROM spans FINAL
  WHERE project_id = '01a16007-0a3b-765f-9b27-e06052060b1b' AND type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 ),
 ranked AS (
  SELECT *, row_number() OVER (ORDER BY start_time DESC, id DESC) AS rn, count() OVER () AS n_total FROM sel
 ),
 shown AS (SELECT * FROM ranked WHERE rn <= 20),
 expanded AS (
  SELECT id, start_time, run_id, n_total, f, JSONExtractRaw(tfg, f) AS raw,
         if(JSONHas(JSONExtractRaw(tfg, f), 'status'), JSONExtractString(JSONExtractRaw(tfg, f), 'status'), 'absent') AS st
  FROM shown
  ARRAY JOIN ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens'] AS f
 )
SELECT toJSONString(map(
 'execution', concat(run_id, ' / ', substring(toString(id), 25, 12)),
 'start_time', toString(start_time),
 'token_field', f,
 'status', st,
 'series_label', concat(f, ' (', st, ')'),
 'value', if(st IN ('nonzero_normalized')
             AND toString(JSONType(raw, 'value')) IN ('Int64','UInt64','Double')
             AND JSONExtractFloat(raw, 'value') >= 0,
             JSONExtractRaw(raw, 'value'), NULL),
 'n_spans_shown', toString(least(n_total, 20)),
 'n_spans_total', toString(n_total),
 'retall', if(n_total > 20, concat('es mostren les 20 execucions més recents de ', toString(n_total)), 'sense retall')
)) AS result
FROM expanded
ORDER BY start_time, id, f
```
Solo dibuja barra para `nonzero_normalized` con un valor numérico mayor o igual que 0. Cualquier otro estado (`absent`, `redacted`, `zero_unconfirmed` u otro desconocido) queda sin barra pero conserva su estado. Si más adelante el exportador emite un cero confirmado, tendrás que añadir ese estado a la lista de admitidos.

**W5: Detall dels tokens — valor i estat** (máximo 40 ejecuciones × 5 campos; el corte se hace por ejecución, así que ninguna queda partida)
```sql
WITH
 sel AS (
  SELECT id, start_time, JSONExtractString(metadata,'tfg_run_id') AS run_id, JSONExtractRaw(metadata,'tfg_usage') AS tfg
  FROM spans FINAL
  WHERE project_id = '01a16007-0a3b-765f-9b27-e06052060b1b' AND type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 ),
 ranked AS (
  SELECT *, row_number() OVER (ORDER BY start_time DESC, id DESC) AS rn, count() OVER () AS n_total FROM sel
 ),
 shown AS (SELECT * FROM ranked WHERE rn <= 40)
SELECT toJSONString(map(
 'execution', run_id,
 'span_id', toString(id),
 'start_time', toString(start_time),
 'token_field', f,
 'value', if(JSONHas(JSONExtractRaw(tfg, f), 'value'), JSONExtractRaw(JSONExtractRaw(tfg, f), 'value'), NULL),
 'status', if(JSONHas(JSONExtractRaw(tfg, f), 'status'), JSONExtractString(JSONExtractRaw(tfg, f), 'status'), 'absent'),
 'n_spans_shown', toString(least(n_total, 40)),
 'n_spans_total', toString(n_total),
 'retall', if(n_total > 40, concat('es mostren les 40 execucions més recents (', toString(least(n_total,40) * 5), ' files) de ', toString(n_total), '; cap execució no es talla parcialment'), 'sense retall')
)) AS result
FROM shown
ARRAY JOIN ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens'] AS f
ORDER BY start_time DESC, id, f
```

## Pendiente

- **Las correcciones de W2–W5 no están desplegadas.** Desde aquí no puedo crear consultas guardadas ni leerlas. Para desplegarlas tienes estas opciones:
  - pegar cada SQL en el editor del widget original desde la interfaz, si el editor lo permite;
  - darme acceso de escritura a `dashboard_saved_queries` y de lectura a la consulta guardada, para que pueda comprobar su `project_id`.
- **Los cinco widgets añadidos a las 08:09.** Decide si los quitas desde la interfaz (menú ⋯ → eliminar). Como mínimo, quita “Prova negativa — project_id fals”, que solo era un control. Si me autorizas a eliminarlos, lo hago editando la configuración de la vista y dejando el resto intacto. Esos widgets podrían sustituir a W2–W5, pero el `project_id` de sus consultas no está verificado.
- **Antes de editar, recarga la vista.** Si guardas desde una pestaña con una versión anterior, podrías perder cambios.
