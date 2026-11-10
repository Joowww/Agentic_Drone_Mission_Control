# Evidencia visual adicional (capturas de Joel, 30/10/2026)

Joel seleccionó 8 capturas de su carpeta de Windows, tomadas entre las 09:46 y las 10:19 mientras QGC estaba abierto. Solo 4 son de QGroundControl y son las que se incorporan, con su nombre original y copiadas byte a byte. Las otras 4 (10:17:13, 10:17:35, 10:19:35 y 10:19:43) no son de QGC: **no se incorporan** y su contenido no se describe.

## Qué se lee en cada captura

| Captura | Lo que se lee |
| --- | --- |
| `Captura de pantalla 2026-10-30 094611.png` | Ventana «QGroundControl» con el diálogo inicial *Preferences*. **No muestra ningún plan ni ítem** |
| `Captura de pantalla 2026-10-30 094741.png` | Vista Plan. *Plan Info* **drone_01**; *Mission Items* **4 items**; lista **Takeoff, Waypoint, Waypoint, Land** |
| `Captura de pantalla 2026-10-30 100328.png` | Igual que la anterior: *Plan Info* **drone_01**, **4 items** y Takeoff, Waypoint, Waypoint, Land |
| `Captura de pantalla 2026-10-30 100754.png` | Vista Plan. *Plan Info* **drone_02**; *Mission Items* **4 items**; lista **Takeoff, Waypoint, Waypoint, Land** |

## Qué no se acredita con las capturas

- **Valores sin leer:** las coordenadas, alturas, modo de altura, *Planned Home* y velocidades no se leen en ninguna captura. El perfil de altura y los marcadores del mapa no se usan para comprobar valores. Esos datos solo están acreditados por las comparaciones de archivos (`comparison_drone_01/`, `comparison_drone_02/`).
- **Sin confirmar:** la versión que muestra QGC, el estado de AutoConnect y la ausencia de avisos al abrir. Las comparaciones de archivos no informan de nada de la interfaz.
- **Momento del guardado:** las capturas no muestran el guardado. Las copias guardadas y sus hashes están en `qgc_saved/` y en el README.
