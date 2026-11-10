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
