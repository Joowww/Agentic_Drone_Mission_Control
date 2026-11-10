# Revisión visual en QGroundControl (Joel), separada del resultado automático

Fuente: lo comunicado por Joel el 27/10/2026 y las 12 capturas que aportó (`screenshots/`, copiadas sin modificar). Son **observaciones visuales**: no se derivan del comparador ni lo sustituyen. Ni las capturas ni su orden llevan hora, y no consta si se tomaron antes o después de guardar la copia.

| Dato | Registrado |
| --- | --- |
| Aplicación | Servicio contenedorizado `qgc` (sin red ni vehículos) |
| Vehículos conectados | Ninguno. La barra muestra «Disconnected» (`01`) |
| Archivo abierto | `/data/plan/drone_01.plan` (solo lectura); en Plan Info aparece `drone_01` (`05`) |
| Copia guardada | `qgc_saved/drone_01.qgc_resaved.plan` |

## Observaciones visuales

| Observación | Captura |
| --- | --- |
| La interfaz muestra «QGroundControl Version v5.1.5 64 bit» | `03_menu_version.png` |
| «Mission Items: 5 items». Lista: Takeoff, Change speed, Waypoint, Waypoint, Land. «Initial Camera Settings» es el bloque de ajustes de QGC, no un ítem | `05`, `06` |
| Takeoff: Altitude (Rel) 5.0 m | `06_takeoff.png` |
| Change speed: Type «Ground Speed», Speed 2.778 m/s, Throttle 0.000 % | `07_change_speed.png` |
| Primer Waypoint: Altitude (Rel) 5.0 m; Flight Speed sin marcar | `08_waypoint_1.png` |
| Segundo Waypoint: Altitude (Rel) 5.0 m; Flight Speed sin marcar | `09_waypoint_2.png` |
| Land presente (Altitude (Rel) 0.0 m, Precision Land Disabled). No hay ningún ítem Return To Launch en la lista | `12_land.png`, `06` |
| GeoFence: Polygon Fences «None», Circular Fences «None». Rally Points: «0 points» | `11_geofence_rally.png` |
| Vehicle Info antes de abrir el plan: ArduPilot / Multi-Rotor | `04_plan_view_empty.png` |

## Contexto de las capturas, sin conclusiones

- `01` y `02`: diálogo de preferencias de primer arranque de QGC. En `02` el desplegable *Preferred Vehicle* está abierto con «Multi-Rotor» resaltado. No consta qué preferencias se guardaron. Son ajustes de la aplicación, no del plan.
- `07`: el valor 2.778 aparece seleccionado en el campo Speed. El comparador no registra ningún cambio de ese parámetro.
- `10`: se abrió el selector «Select Mission Command», que muestra la lista de comandos, incluido Return To Launch. Es el selector, no un ítem del plan. No consta si se canceló. El comparador no registra ningún cambio de comando.
- En `05` el mapa no tiene teselas (contenedor sin red), como se esperaba.

## Tabla del paso 3 de [qgc-first-import-procedure.md](../../../docs/qgc-first-import-procedure.md), solo con lo observado

| # | Comprobación | Observación visual |
| --- | --- | --- |
| 1 | Avisos al abrir | **No confirmado** por Joel |
| 2 | Firmware/vehículo | ArduPilot / Multi-Rotor en Vehicle Info, observado **antes** de abrir el plan (`04`). Con el plan cargado no se ve |
| 3 | Planned Home (lat/lon/584 m) | **No observado**: las capturas no muestran coordenadas ni la altitud del home |
| 4 | Ítem 1 Takeoff 5 m Rel | Observado (`06`) |
| 5 | Change Speed 2,778 m/s, velocidad sobre el suelo | Observado (`07`) |
| 6 | Waypoints sobre POI_1/POI_2, 5 m Rel, Hold 0, yaw vacío | 5 m Rel observado en ambos (`08`, `09`). Posición, Hold y yaw **no observados** |
| 7 | Land en el despegue, sin RTL | Land presente y sin RTL (`12`). Que esté en las coordenadas del despegue **no se ha observado** |
| 8 | Modo de altura relativa | Los campos de altitud muestran «(Rel)» en Takeoff, Waypoints y Land. El ajuste global de la misión no se ha observado |
| 9 | Geovalla y rally vacíos | Observado (`11`) |
| 10 | 5 ítems | Observado (`05`) |

**No confirmado:** el estado de AutoConnect (no hay captura de *Comm Links*) y la ausencia de avisos. Las coordenadas no se verifican con estas capturas; su correspondencia con el original la establece solo el comparador.
