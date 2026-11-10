# Comparación `.plan`: NO_SEMANTIC_DIFFERENCES

- Original sha256 `692c8075133ef62bdb4a051892387ce62213fb2c8ae3a905904d2f157d142c8d`; guardado sha256 `256f5a5229aeb7633ee5138e1b95239b94714e0a312f9046d06f970bf6f8748e`.
- Alcance: comparison of two files only; not a QGroundControl or vehicle compatibility verdict.

| Categoría | Número |
| --- | --- |
| PRESENTATION | 4 |
| QGC_METADATA | 3 |
| SEMANTIC_CHANGE | 0 |
| ADDED | 0 |
| REMOVED | 0 |
| UNDETERMINED | 0 |

| Categoría | Ruta | Original | Guardado | Detalle |
| --- | --- | --- | --- | --- |
| PRESENTATION | `/mission/plannedHomePosition/2` | `584.0` | `584` | planned home AMSL altitude: same number, different literal |
| PRESENTATION | `/mission/items/0/params/6` | `5.0` | `5` | NAV_TAKEOFF param7 (altitude): same number, different literal |
| QGC_METADATA | `/mission/items/1/Altitude` | `0` | `null` | Altitude not written by QGC for this item |
| QGC_METADATA | `/mission/items/1/AltitudeMode` | `1` | `null` | AltitudeMode not written by QGC for this item |
| QGC_METADATA | `/mission/items/1/AMSLAltAboveTerrain` | `null` | `null` | field removed |
| PRESENTATION | `/mission/items/2/params/6` | `5.0` | `5` | NAV_WAYPOINT param7 (altitude): same number, different literal |
| PRESENTATION | `/mission/items/3/params/6` | `5.0` | `5` | NAV_WAYPOINT param7 (altitude): same number, different literal |
