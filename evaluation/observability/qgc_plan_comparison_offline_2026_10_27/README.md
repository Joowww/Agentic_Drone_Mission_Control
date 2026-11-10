# Comparador `.plan` original frente a guardado por QGC: verificación offline (27/10/2026)

**Sin QGroundControl, simulación, conexiones, cargas ni inferencias.** Los archivos «guardados» de esta evidencia son modificaciones **sintéticas**: ninguno procede de QGroundControl.

**Archivo original:** `agri_export_semantics_2026_10_27/packages/b_synthetic_orchard_v1_sitl_v2/plans/drone_01.plan`, sha256 `692c8075…`. Es el propuesto para la primera importación. Esta tanda no cambia sus bytes: solo cambian el manifiesto y el informe del paquete.

Cada caso está en `cases/<nombre>/` con:
- `original.plan` y `saved.plan` (copias byte a byte);
- `text.diff`;
- `comparison.json` y `comparison.md`;
- su propio `SHA256SUMS`.

La salida de terminal está en `terminal.txt`.

| Caso | Cambio sintético | Resultado |
| --- | --- | --- |
| 01 | Reindentado y claves de `mission` en otro orden | `NO_SEMANTIC_DIFFERENCES` (1 PRESENTATION) |
| 02 | `groundStation` distinto; sin `Altitude`/`AltitudeMode` en `DO_CHANGE_SPEED` | `NO_SEMANTIC_DIFFERENCES` (3 QGC_METADATA) |
| 03 | `NAV_LAND` → `NAV_RETURN_TO_LAUNCH` (y frame 2) | `SEMANTIC_DIFFERENCES` (comando y frame) |
| 04 | Altura de un waypoint 5 → 15 m (param7) | `SEMANTIC_DIFFERENCES`, más UNDETERMINED porque `Altitude` ya no coincide con param7 |
| 05 | Frame 3 → 0 | `SEMANTIC_DIFFERENCES` |
| 06 | Yaw `null` → 0 | `SEMANTIC_DIFFERENCES`: `null` (NaN para QGC) no equivale a 0 |
| 07 | Velocidad 2,778 → 5 m/s | `SEMANTIC_DIFFERENCES` |
| 08 | `NAV_LAND` eliminado | `SEMANTIC_DIFFERENCES` (1 REMOVED) |
| 09 | Campo desconocido en un ítem | `UNDETERMINED`: no se da por inocuo |
| 10 | `null` → `NaN` literal | `UNDETERMINED`: no es JSON estándar |
| 11 | Archivo truncado | `UNREADABLE_SAVED`: sin normalizar; copias y diff conservados |

**Fuentes de las reglas:**
- QGroundControl master `98ee79c1`: `MissionItem::load`, `JsonParsing::possibleNaNJsonValue`, `SimpleMissionItem::save`, `AltitudeFrame`.
- ArduPilot `755258db`: `AP_Mission::sanity_check_params`.
- Documentación: [`docs/site-fleet-export.md` §8.4](../../../docs/site-fleet-export.md). Procedimiento: [`docs/qgc-first-import-procedure.md`](../../../docs/qgc-first-import-procedure.md).

**Límites:**
- Las reglas de metadatos se basan en la fuente de QGC *master*, no en la versión que se usará. Si esa versión escribe campos distintos, aparecerán como `UNDETERMINED` hasta revisarlos con su propia fuente.
- El resultado se limita a comparar dos archivos: no establece compatibilidad.
