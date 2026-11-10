SELECT toJSONString(map('entity',entity,'tfg_data_kind',if(v='','(absent)',v),'count',toString(c))) AS result
FROM (
 SELECT 'trace' AS entity, JSONExtractString(metadata,'tfg_data_kind') AS v, count() AS c FROM traces FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY v
 UNION ALL
 SELECT 'span' AS entity, JSONExtractString(metadata,'tfg_data_kind') AS v, count() AS c FROM spans FINAL
 WHERE source IN ('sdk','unknown') AND start_time >= {{window_start}} AND start_time < {{window_end}} AND has(tags,'captured-metadata') AND NOT has(tags,'synthetic') AND NOT has(tags,'provenance-unknown')
 GROUP BY v
) ORDER BY entity, v
