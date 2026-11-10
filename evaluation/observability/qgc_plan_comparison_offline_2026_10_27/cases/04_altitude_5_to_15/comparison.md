# Comparación `.plan`: SEMANTIC_DIFFERENCES

- Original sha256 `692c8075133ef62bdb4a051892387ce62213fb2c8ae3a905904d2f157d142c8d`; guardado sha256 `99c9ed2baa63bbd227bd122017f6ba00bfc7b0b0ba3596744de34133adb0a276`.
- Alcance: comparison of two files only; not a QGroundControl or vehicle compatibility verdict.

| Categoría | Número |
| --- | --- |
| PRESENTATION | 0 |
| QGC_METADATA | 0 |
| SEMANTIC_CHANGE | 1 |
| ADDED | 0 |
| REMOVED | 0 |
| UNDETERMINED | 1 |

| Categoría | Ruta | Original | Guardado | Detalle |
| --- | --- | --- | --- | --- |
| SEMANTIC_CHANGE | `/mission/items/2/params/6` | `5.0` | `15.0` | NAV_WAYPOINT param7 (altitude): value changed (Δ=10) |
| UNDETERMINED | `/mission/items/2/Altitude` | `null` | `5.0` | QGC Altitude disagrees with param7 |
