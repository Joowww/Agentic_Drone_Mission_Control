No he podido verificar en el backend que los siete widgets se guardaron, y tampoco he podido editar ningún título. Todas las lecturas del dashboard `01a1627b-9178-7176-b704-b2cb878de52d` fallan: `read`, `get_dashboard` y `get_dashboard_by_id` devuelven 404 “Dashboard not found”, y los listados salen vacíos. No he intentado reescribir la configuración a ciegas, porque la API sustituye la configuración completa y podría borrar los widgets. No he añadido nada ni he tocado trazas o spans.

## 1. ¿Se guardaron los widgets?

Solo puedo decirte lo que se ve en tu pantalla: los siete widgets aparecen una sola vez cada uno, en sus secciones y con datos. Eso no prueba que estén guardados en el servidor, porque podrían ser solo el estado local del navegador. Para confirmarlo, recarga la página (F5). Si siguen ahí y no salen repetidos, están guardados.

## 2. Las siete consultas SQL

Todas usan el rango de fechas del dashboard (`{{window_start}}`/`{{window_end}}`) y el proyecto `01a16007-0a3b-765f-9b27-e06052060b1b`. Abajo pongo el nombre actual de cada widget y el nuevo en catalán.

**W1. Volumen diario: trazas y spans llm → Volum diari — traces i crides LLM**
```sql
SELECT toJSONString(map('date',toString(d),'series',series,'count',toString(c))) AS result
FROM (
 SELECT toDate(start_time) AS d,'traces' AS series,count() AS c FROM traces FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d
 UNION ALL
 SELECT toDate(start_time) AS d,'llm_spans' AS series,count() AS c FROM spans FINAL
 WHERE type='llm' AND source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d
) ORDER BY d, series
```

**W2. Latencia spans llm P50/P90/P99 (s) — n=1, no representativa → Latència LLM — P50/P90/P99**
```sql
SELECT toJSONString(map('date',toString(toDate(start_time)),
 'p50_s',toString(round(quantile(0.5)(dateDiff('millisecond',start_time,end_time)/1000.0),3)),
 'p90_s',toString(round(quantile(0.9)(dateDiff('millisecond',start_time,end_time)/1000.0),3)),
 'p99_s',toString(round(quantile(0.99)(dateDiff('millisecond',start_time,end_time)/1000.0),3)),
 'n',toString(count()))) AS result
FROM spans FINAL
WHERE type='llm' AND end_time IS NOT NULL AND end_time > toDateTime64(0,6)
 AND source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}}
 AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
GROUP BY toDate(start_time) ORDER BY toDate(start_time)
```

**W3. Errores por fecha y tipo → Errors per data i tipus**
```sql
SELECT toJSONString(map('date',toString(d),'series',lbl,'error_count',toString(n))) AS result
FROM (
 SELECT toDate(start_time) AS d,
        concat('trace: ', if(empty(error_info), '(sin error)', JSONExtractString(error_info,'exception_type'))) AS lbl,
        sum(if(empty(error_info), 0, 1)) AS n
 FROM traces FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d, lbl
 UNION ALL
 SELECT toDate(start_time) AS d,
        concat('span: ', if(empty(error_info), '(sin error)', JSONExtractString(error_info,'exception_type'))) AS lbl,
        sum(if(empty(error_info), 0, 1)) AS n
 FROM spans FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d, lbl
) ORDER BY d, lbl
```

**W4. Tokens entrada/salida/caché por ejecución (zero_unconfirmed sin barra) → Tokens d’entrada, sortida i memòria cau per execució**
```sql
WITH sel AS (
  SELECT id, start_time, JSONExtractString(metadata,'tfg_run_id') AS run_id, JSONExtractRaw(metadata, 'tfg_usage') AS tfg
  FROM spans FINAL
  WHERE type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
)
SELECT toJSONString(map(
  'execution', concat(run_id, ' / ', substring(toString(id), 25, 12)),
  'token_field', f,
  'status', st,
  'series_label', concat(f, ' (', st, ')'),
  'value', if(st IN ('absent','zero_unconfirmed'), NULL, JSONExtractRaw(JSONExtractRaw(tfg, f), 'value')),
  'n_spans', toString((SELECT uniqExact(id) FROM sel))
)) AS result
FROM (
  SELECT *, f, if(JSONHas(JSONExtractRaw(tfg, f), 'status'), JSONExtractString(JSONExtractRaw(tfg, f), 'status'), 'absent') AS st
  FROM sel
  ARRAY JOIN ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens'] AS f
)
ORDER BY start_time, id, f
LIMIT 400
```

**W5. Detalle tokens tfg_usage (valor + estado) → Detall dels tokens — valor i estat** (tabla)
```sql
WITH sel AS (
  SELECT id, start_time, JSONExtractString(metadata,'tfg_run_id') AS run_id, JSONExtractRaw(metadata, 'tfg_usage') AS tfg
  FROM spans FINAL
  WHERE type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
)
SELECT toJSONString(map(
  'execution', run_id,
  'span_id', toString(id),
  'start_time', toString(start_time),
  'token_field', f,
  'value', if(JSONHas(JSONExtractRaw(tfg, f), 'value'), JSONExtractRaw(JSONExtractRaw(tfg, f), 'value'), NULL),
  'status', if(JSONHas(JSONExtractRaw(tfg, f), 'status'), JSONExtractString(JSONExtractRaw(tfg, f), 'status'), 'absent'),
  'n_spans', toString((SELECT uniqExact(id) FROM sel))
)) AS result
FROM sel
ARRAY JOIN ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens'] AS f
ORDER BY start_time DESC, id, f
LIMIT 200
```

**W6. Recuento por tfg_data_kind → Procedència de les dades**
```sql
SELECT toJSONString(map('entity',entity,'tfg_data_kind',if(v='','(absent)',v),'count',toString(c))) AS result
FROM (
 SELECT 'trace' AS entity, JSONExtractString(metadata,'tfg_data_kind') AS v, count() AS c FROM traces FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY v
 UNION ALL
 SELECT 'span' AS entity, JSONExtractString(metadata,'tfg_data_kind') AS v, count() AS c FROM spans FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY v
) ORDER BY entity, v
```

**W7. Cobertura por tfg_usage_source → Cobertura dels comptadors d’ús** (tabla)
```sql
WITH sel AS (
  SELECT JSONExtractString(metadata,'tfg_usage_source') AS v
  FROM spans FINAL
  WHERE type='llm' AND source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
)
SELECT toJSONString(map(
  'tfg_usage_source', if(v='','(absent)',v),
  'count', toString(count()),
  'total_llm_spans', toString((SELECT count() FROM sel)),
  'coverage', toString(round(count() / (SELECT count() FROM sel), 4))
)) AS result
FROM sel GROUP BY v ORDER BY count() DESC
```

Los cuatro indicadores del Resumen son widgets nativos de métricas del proyecto, no consultas SQL. No he podido leer sus filtros.

## 3. Comprobaciones

**Tamaño de muestra dinámico: se cumple en las consultas, falla en un título.**
- Las consultas lo calculan siempre: `n` en W2, `n_spans` en W4 y W5, y `total_llm_spans` en W7.
- El fallo está en el título de W2, que lleva “n=1” fijo. Se corrige con el nuevo nombre, “Latència LLM — P50/P90/P99”.
- No he podido confirmar que el gráfico de líneas W2 muestre `n` en pantalla. La tabla W5 sí lo muestra.

**“Sin datos” frente a “cero errores”: solo se distingue en parte.**
- W3 sin muestras en el rango devuelve 0 filas y el widget aparece vacío.
- W3 con muestras pero sin errores devuelve una serie “(sin error)” con valor 0. Una barra de altura 0 casi no se ve, así que visualmente se parecen.
- El indicador nativo “Errors LLM” muestra 0 en ambos casos, así que no los distingue.
- Para resolverlo de verdad habría que cambiar la consulta de W3 para añadir el número de trazas y spans evaluados. Eso es un cambio de consulta y no lo he hecho.

**zero_unconfirmed: se conserva con su estado.**
- La tabla W5 incluye los cinco componentes con su `value` y `status` reales. `cache_write_tokens` y `reasoning_tokens` aparecen como 0 con `zero_unconfirmed`, y un campo que falte saldría como `absent`.
- En W4 esos valores pasan a NULL, sin barra, pero el estado sigue en `series_label`.
- W4 no incluye `reasoning_tokens`; solo aparece en W5.

## 4. Traducción al catalán: hay que hacerla desde la interfaz

No he podido editar ningún título. Para cambiarlos:
- **Secciones:** haz clic en el título de la sección, o en su menú, y renómbrala.
- **Widgets:** abre el menú del widget (⋯), elige “Editar”, cambia solo el título y guarda.
- Si el dashboard tiene un botón de guardar, pulsa “Guardar” al terminar y recarga la página para comprobarlo.

| Actual | Nuevo |
|---|---|
| Overview (sección) | 1. Resum |
| Indicador “Total trace count” | Execucions registrades |
| Trucades registrades al LLM | Crides LLM registrades |
| Latència LLM - mitjana | Latència LLM — mediana (P50) |
| Errors LLM | Errors LLM (sin cambios) |
| 2. Evolución (sección) | 2. Evolució |
| Volumen diario: trazas y spans llm | Volum diari — traces i crides LLM |
| Latencia spans llm P50/P90/P99 (s) — n=1, no representativa | Latència LLM — P50/P90/P99 |
| Errores por fecha y tipo | Errors per data i tipus |
| 3. Tokens (metadata.tfg_usage) (sección) | 3. Tokens |
| Tokens entrada/salida/caché por ejecución (zero_unconfirmed sin barra) | Tokens d’entrada, sortida i memòria cau per execució |
| Detalle tokens tfg_usage (valor + estado) | Detall dels tokens — valor i estat |
| 4. Procedencia (sección) | 4. Procedència i cobertura |
| Recuento por tfg_data_kind | Procedència de les dades |
| Cobertura por tfg_usage_source | Cobertura dels comptadors d’ús |

Algunas etiquetas visibles no se pueden traducir sin cambiar algo que me pediste conservar:
- **“(sin error)” en W3:** lo genera la propia consulta SQL, así que lo he dejado en castellano. Traducirlo a “(sense errors)” supondría cambiar la consulta.
- **Subtítulos de los indicadores** (“Total trace count”, “P50 duration”…): parecen etiquetas nativas de la métrica y probablemente no se pueden editar.
- **Nombres de columnas y series** (`execution`, `token_field`, `status`, `p50_s`…): vienen de las claves de las consultas y se quedan sin traducir.

No veo en tu pantalla el widget de texto con la nota de límites que te propuse. Si lo añades tú, esta es la versión en catalán:

> **Límits de la captura.** Una sola traça real d’Hermes (proveïdor nous, model poolside/laguna-s-2.1:free, 21/10/2026). La mostra és massa petita per ser una distribució representativa: P50, P90 i P99 hi coincideixen. Només cobreix el torn principal, sense la generació auxiliar del títol. Els tokens són el resum normalitzat d’Hermes (`hermes_normalized_summary`), no l’ús en brut del proveïdor. `prompt_tokens` i `total_tokens` són derivats. `cache_write_tokens` i `reasoning_tokens` tenen l’estat `zero_unconfirmed`: no són zeros confirmats. Cost: `not_computed`. `retry_count` i `upstream_provider` són absents. La durada de la traça es deriva del span (`tfg_latency_measured=false` a la traça).

Antes de cambiar el título de “Crides LLM registrades”, comprueba en su editor que filtra por span type = llm. En “Latència LLM — mediana (P50)”, comprueba que mide la duración de los spans y no la de las trazas. No he podido leer esa configuración.
