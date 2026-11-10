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
