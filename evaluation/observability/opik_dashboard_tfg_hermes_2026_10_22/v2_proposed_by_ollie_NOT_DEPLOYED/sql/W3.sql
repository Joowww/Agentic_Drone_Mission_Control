WITH
 pop AS (
  SELECT toDate(start_time) AS d, error_info FROM spans FINAL
  WHERE project_id = '01a16007-0a3b-765f-9b27-e06052060b1b' AND type = 'llm' AND source IN ('sdk','unknown')
    AND start_time >= {{window_start}} AND start_time < {{window_end}}
    AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 ),
 days AS (
  SELECT arrayJoin(arrayMap(i -> toDate({{window_start}}) + i, range(toUInt32(dateDiff('day', toDate({{window_start}}), toDate({{window_end}})) + 1)))) AS d
 ),
 agg AS (SELECT d, count() AS n, countIf(error_info != '') AS errs FROM pop GROUP BY d),
 per_day AS (
  SELECT days.d AS d, ifNull(agg.n, 0) AS n, ifNull(agg.errs, 0) AS errs
  FROM days LEFT JOIN agg ON days.d = agg.d
 ),
 by_type AS (
  SELECT d, if(JSONExtractString(error_info,'exception_type') = '', '(tipus desconegut)', JSONExtractString(error_info,'exception_type')) AS et, count() AS c
  FROM pop WHERE error_info != '' GROUP BY d, et
 ),
 rows AS (
  SELECT d, 'mostres avaluades (n)' AS series, toNullable(toFloat64(n)) AS value, n, errs FROM per_day WHERE n > 0
  UNION ALL
  SELECT p.d AS d, concat('errors: ', b.et) AS series, toNullable(toFloat64(b.c)) AS value, p.n AS n, p.errs AS errs FROM by_type AS b INNER JOIN per_day AS p ON b.d = p.d
  UNION ALL
  SELECT d, 'errors: cap' AS series, toNullable(0.0) AS value, n, errs FROM per_day WHERE n > 0 AND errs = 0
  UNION ALL
  SELECT d, 'sense dades' AS series, CAST(NULL, 'Nullable(Float64)') AS value, n, errs FROM per_day WHERE n = 0
 )
SELECT toJSONString(map(
 'date', toString(d),
 'series', series,
 'value', if(isNull(value), NULL, toString(value)),
 'n', toString(n),
 'estat', multiIf(n = 0, 'sense dades', errs = 0, 'sense errors (n>0)', 'amb errors')
)) AS result
FROM rows
ORDER BY d, series
