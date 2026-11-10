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
