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
