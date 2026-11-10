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
