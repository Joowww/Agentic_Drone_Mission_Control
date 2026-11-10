# Comparación `.plan`: SEMANTIC_DIFFERENCES

- Original sha256 `692c8075133ef62bdb4a051892387ce62213fb2c8ae3a905904d2f157d142c8d`; guardado sha256 `7e6dd481186aa7930654ecf91fee554a97015642b36d09c691667b5ac143edec`.
- Alcance: comparison of two files only; not a QGroundControl or vehicle compatibility verdict.

| Categoría | Número |
| --- | --- |
| PRESENTATION | 0 |
| QGC_METADATA | 0 |
| SEMANTIC_CHANGE | 0 |
| ADDED | 0 |
| REMOVED | 1 |
| UNDETERMINED | 0 |

| Categoría | Ruta | Original | Guardado | Detalle |
| --- | --- | --- | --- | --- |
| REMOVED | `/mission/items/4` | `{"AMSLAltAboveTerrain": null, "Altitude": 0, "AltitudeMode": 1, "autoContinue": true, "command": 21, "doJumpId": 5, "frame": 3, "params": [0, 0, 0, null, -35.3633159, 149.16519294, 0], "type": "SimpleItem"}` | `null` | item NAV_LAND absent from the saved file |
