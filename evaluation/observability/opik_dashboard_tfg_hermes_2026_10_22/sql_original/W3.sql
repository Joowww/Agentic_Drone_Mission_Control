SELECT toJSONString(map('date',toString(d),'series',lbl,'error_count',toString(n))) AS result
FROM (
 SELECT toDate(start_time) AS d,
        concat('trace: ', if(empty(error_info), '(sin error)', JSONExtractString(error_info,'exception_type'))) AS lbl,
        sum(if(empty(error_info), 0, 1)) AS n
 FROM traces FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d, lbl
 UNION ALL
 SELECT toDate(start_time) AS d,
        concat('span: ', if(empty(error_info), '(sin error)', JSONExtractString(error_info,'exception_type'))) AS lbl,
        sum(if(empty(error_info), 0, 1)) AS n
 FROM spans FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY d, lbl
) ORDER BY d, lbl
