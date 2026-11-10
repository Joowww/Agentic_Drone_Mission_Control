-- PROPOSED CORRECTIONS — NOT DEPLOYED, NOT EXECUTED, NOT VALIDATED AGAINST CLICKHOUSE (2026-10-22).
-- Written offline from the review in sql_review.md. The deployed widgets are still the originals
-- in sql_original/. Apply only through the Opik interface, compare the result with the originals
-- on the same date range, and have Joel confirm it visually. Project scope still comes from the
-- widget (external project_id), exactly as in the originals.

-- P-W2: valid intervals only, successful llm calls only, exact quantiles, sample size kept.
SELECT toJSONString(map('date',toString(toDate(start_time)),
 'p50_s',toString(round(quantileExact(0.5)(dateDiff('millisecond',start_time,end_time)/1000.0),3)),
 'p90_s',toString(round(quantileExact(0.9)(dateDiff('millisecond',start_time,end_time)/1000.0),3)),
 'p99_s',toString(round(quantileExact(0.99)(dateDiff('millisecond',start_time,end_time)/1000.0),3)),
 'n',toString(count()))) AS result
FROM spans FINAL
WHERE type='llm' AND end_time IS NOT NULL AND end_time > toDateTime64(0,6) AND end_time >= start_time
 AND empty(error_info)
 AND source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}}
 AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
GROUP BY toDate(start_time) ORDER BY toDate(start_time);

-- P-W3: evaluated llm spans and errors per day (no rows = no data; evaluated>0 with errors=0 = zero
-- errors). The trace series is dropped: the exporter never sets error_info on traces.
SELECT toJSONString(map('date',toString(d),'evaluated_llm_spans',toString(evaluated),'llm_spans_with_error',toString(with_error))) AS result
FROM (
 SELECT toDate(start_time) AS d, count() AS evaluated, countIf(NOT empty(error_info)) AS with_error
 FROM spans FINAL
 WHERE type='llm' AND source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}}
   AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d
) ORDER BY d;
-- (Error types, if wanted, as a separate breakdown restricted to spans WITH error_info.)

-- P-W4: newest spans first, explicit truncation flag, 'redacted' also without a bar.
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
  'value', if(st IN ('absent','zero_unconfirmed','redacted'), NULL, JSONExtractRaw(JSONExtractRaw(tfg, f), 'value')),
  'n_spans', toString((SELECT uniqExact(id) FROM sel)),
  'spans_shown_max', '100',
  'truncated', toString((SELECT uniqExact(id) FROM sel) > 100)
)) AS result
FROM (
  SELECT *, f, if(JSONHas(JSONExtractRaw(tfg, f), 'status'), JSONExtractString(JSONExtractRaw(tfg, f), 'status'), 'absent') AS st
  FROM sel
  ARRAY JOIN ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens'] AS f
)
ORDER BY start_time DESC, id, f
LIMIT 400;

-- P-W5: same as the original plus an explicit truncation flag (40 spans x 5 fields).
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
  'n_spans', toString((SELECT uniqExact(id) FROM sel)),
  'truncated', toString((SELECT uniqExact(id) FROM sel) > 40)
)) AS result
FROM sel
ARRAY JOIN ['input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens'] AS f
ORDER BY start_time DESC, id, f
LIMIT 200;

-- P-C1 (new, contamination control): NO tag or source filter on purpose; only the widget's
-- project scope and date range. Anything but 'captured-metadata' must be investigated and kept
-- out of comparisons.
SELECT toJSONString(map('entity',e,'tag_class',cls,'count',toString(c))) AS result
FROM (
 SELECT 'trace' AS e, multiIf(has(tags,'synthetic'),'synthetic', has(tags,'provenance-unknown'),'provenance-unknown',
        has(tags,'captured-metadata'),'captured-metadata','(none of the provenance tags)') AS cls, count() AS c
 FROM traces FINAL WHERE start_time >= {{window_start}} AND start_time < {{window_end}} GROUP BY cls
 UNION ALL
 SELECT 'span' AS e, multiIf(has(tags,'synthetic'),'synthetic', has(tags,'provenance-unknown'),'provenance-unknown',
        has(tags,'captured-metadata'),'captured-metadata','(none of the provenance tags)') AS cls, count() AS c
 FROM spans FINAL WHERE start_time >= {{window_start}} AND start_time < {{window_end}} GROUP BY cls
) ORDER BY e, cls;
