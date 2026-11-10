# Primera importación offline en QGroundControl, 27/10/2026

**Resultado automático:** `NO_SEMANTIC_DIFFERENCES` (PRESENTATION 4, QGC_METADATA 3, SEMANTIC_CHANGE 0, ADDED 0, REMOVED 0, UNDETERMINED 0).

**Afirmación acreditada:** QGroundControl 5.1.5, en contenedor sin red y sin vehículos, abrió este `.plan` y guardó una copia. Esa copia no tiene diferencias semánticas con el original según las reglas de `tools/qgc_plan_compare.py`.

**No acreditado:** la carga en un autopiloto, la lectura de vuelta desde el vehículo, la ejecución en SITL o hardware, la compatibilidad con el vehículo y la equivalencia dinámica. Tampoco otras versiones de QGC ni otros archivos.

La revisión visual de Joel está aparte, en [joel_visual_review.md](joel_visual_review.md). No forma parte del resultado automático.

## Archivos

| Archivo | sha256 | Origen |
| --- | --- | --- |
| `comparison/original.plan` | `692c8075133ef62bdb4a051892387ce62213fb2c8ae3a905904d2f157d142c8d` | Copia hecha por el comparador. Igual a `agri_export_semantics_2026_10_27/packages/b_synthetic_orchard_v1_sitl_v2/plans/drone_01.plan` (`instance_id` `b9cff3e6b6950110`) |
| `qgc_saved/drone_01.qgc_resaved.plan` | `256f5a5229aeb7633ee5138e1b95239b94714e0a312f9046d06f970bf6f8748e` | Guardado por QGC en `/data/saved/` a las 16:38:09 UTC, 3160 bytes |
| `comparison/saved.plan` | `256f5a52…f8748e` | Copia hecha por el comparador. **Igual byte a byte** al archivo anterior |
| `comparison/` (json, md, text.diff, SHA256SUMS) | ver `SHA256SUMS` | Generados a las 16:39:09 UTC. Su `SHA256SUMS` verifica 5/5 |

**Rutas de entrada.** El comparador registra los hashes de entrada, no las rutas. La orden pegada por Joel mostraba el segundo argumento terminado en `drone_01`. En `qgc_saved/` no existe ningún archivo con ese nombre, solo `drone_01.qgc_resaved.plan`, y el comparador falla si no puede leer un archivo. Lo acreditado es el contenido: el archivo comparado como «guardado» tiene exactamente los bytes de `qgc_saved/drone_01.qgc_resaved.plan`. Que la orden pegada estuviera cortada es probable pero no se ha verificado. No se ha renombrado ni sobrescrito nada.

**Imagen.** La única imagen etiquetada es `tfg/qgroundcontrol:5.1.5`, ID `c6a5c57a1552…f314` (evidencia en `qgc_container_build_2026_10_27`), y no se ha reconstruido después. No se ha podido confirmar con el registro de eventos de Docker que el contenedor de la importación usara esa imagen: la consulta no terminó en este entorno.

## Las siete diferencias informadas

| # | Categoría | Ruta | Original → guardado | Lectura |
| --- | --- | --- | --- | --- |
| 1 | PRESENTATION | `/mission/plannedHomePosition/2` | `584.0` → `584` | Altitud AMSL del home planificado: mismo número, otro literal |
| 2 | PRESENTATION | `/mission/items/0/params/6` | `5.0` → `5` | NAV_TAKEOFF param7, altitud de 5 m: mismo número |
| 3 | QGC_METADATA | `/mission/items/1/Altitude` | `0` → ausente | Ítem DO_CHANGE_SPEED: QGC no escribe `Altitude` en ítems sin altitud (`SimpleMissionItem::save`). No es un campo MAVLink |
| 4 | QGC_METADATA | `/mission/items/1/AltitudeMode` | `1` → ausente | Igual que la 3 |
| 5 | QGC_METADATA | `/mission/items/1/AMSLAltAboveTerrain` | `null` → ausente | Igual que la 3. El informe muestra «`null` → `null`» porque representa la ausencia como `null`; el detalle dice «field removed» |
| 6 | PRESENTATION | `/mission/items/2/params/6` | `5.0` → `5` | NAV_WAYPOINT POI_1 param7: mismo número |
| 7 | PRESENTATION | `/mission/items/3/params/6` | `5.0` → `5` | NAV_WAYPOINT POI_2 param7: mismo número |

Sin cambios en ningún comando, frame, coordenada, `param1`–`param6`, `autoContinue`, `doJumpId`, home, cabecera, geovalla ni puntos de rally. En particular:
- el yaw sigue siendo `null`, no `0`;
- el ítem 5 sigue siendo NAV_LAND, no RTL;
- DO_CHANGE_SPEED conserva 1 / 2,778.

## Cambios de texto que el recuento no detalla

`text.diff` contiene además cambios de solo presentación que el comparador no informa como filas:
- `Altitude` `5.0` → `5` en los ítems 0, 2 y 3. Es el mismo valor. El comparador solo informa de `Altitude` si el valor cambia, no si cambia el literal.
- `geoFence.circles`, `geoFence.polygons` y `rallyPoints.points` se escriben como `[` + salto de línea + `]` en lugar de `[]`. Es el mismo valor, vacío, con otro espaciado.

No cambian el estado ni ninguna categoría semántica. Sí significan que PRESENTATION=4 cuenta las filas informadas, no todos los cambios de texto. No se ha modificado el comparador.

## Pendiente

1. Cargar el plan en SITL y leerlo de vuelta del autopiloto. Requiere una autorización propia ([integrated-trial-protocol.md](../../../docs/integrated-trial-protocol.md), paso 3b).
2. Ejecutarlo en AUTO en SITL. Después, en hardware: firmware físico y vehículo todavía desconocidos.
3. Revisión visual: añadidas 12 capturas (`screenshots/`) y las observaciones de `joel_visual_review.md`. Siguen sin confirmar AutoConnect, la ausencia de avisos y las coordenadas en pantalla.
