# Comparación `.plan`: SEMANTIC_DIFFERENCES

- Original sha256 `692c8075133ef62bdb4a051892387ce62213fb2c8ae3a905904d2f157d142c8d`; guardado sha256 `ce2caaddd5008717c4fe6860928f1f65439a69254ecaa1f471a2c00c5f8496ce`.
- Alcance: comparison of two files only; not a QGroundControl or vehicle compatibility verdict.

| Categoría | Número |
| --- | --- |
| PRESENTATION | 0 |
| QGC_METADATA | 0 |
| SEMANTIC_CHANGE | 1 |
| ADDED | 0 |
| REMOVED | 0 |
| UNDETERMINED | 0 |

| Categoría | Ruta | Original | Guardado | Detalle |
| --- | --- | --- | --- | --- |
| SEMANTIC_CHANGE | `/mission/items/2/params/3` | `null` | `0` | NAV_WAYPOINT param4 (yaw): null (read as NaN by QGC) vs number; not equivalent |
