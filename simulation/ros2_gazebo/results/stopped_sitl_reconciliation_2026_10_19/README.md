# SITL detenido: evidencia y verificación offline (19/10/2026)

`initial_blocked_inspection.json` es copia exacta del original runtime, sin
telemetría ni aplicación. `manifest.json` identifica origen, SHA-256 y bytes.
`identity_reference_offline.json` sólo comprueba el vínculo de identidad del archivo:
no es una observación Docker actual. `legacy_query_offline.json` consulta únicamente
la auditoría local y distingue nunca recogido de caducado.

`preservation_baseline.json` y `preservation_check.json` permiten contrastar 472
archivos previos seleccionados, incluidas reservas. `verification.json` registra
las comprobaciones finales. Los logs de tests usan dobles/temporales; no son ensayos
ni liberaciones reales. Hay logs intermedios verdes y dos errores iniciales de
colección sólo observados en herramientas; se describen sin inventar un TXT bruto.
Nueve evidencias brutas de incrementos anteriores tienen avisos de whitespace y
se conservan. Los archivos de este directorio tienen bytes/hashes independientes
de los originales; el manifiesto se excluye a sí mismo.
