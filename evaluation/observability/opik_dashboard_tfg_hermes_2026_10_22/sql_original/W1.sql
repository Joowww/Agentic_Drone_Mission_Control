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
