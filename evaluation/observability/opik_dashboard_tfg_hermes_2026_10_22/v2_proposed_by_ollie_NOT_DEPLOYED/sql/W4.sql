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
