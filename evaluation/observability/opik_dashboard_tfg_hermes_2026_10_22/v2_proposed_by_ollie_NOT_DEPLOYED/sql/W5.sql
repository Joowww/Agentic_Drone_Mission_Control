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
