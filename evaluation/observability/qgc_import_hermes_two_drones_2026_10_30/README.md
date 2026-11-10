# Importación y guardado offline en QGroundControl de los dos `.plan` derivados de Hermes (30/10/2026)

**Resultado:** los dos archivos se importaron en QGroundControl, contenedorizado, sin red, sin vehículo y sin *Upload*, y se guardó una copia de cada uno. Las dos comparaciones con el comparador existente dan **NO_SEMANTIC_DIFFERENCES**:

| Archivo | Original (solo lectura) | Copia guardada por QGC | Comparación | Diferencias |
| --- | --- | --- | --- | --- |
| `drone_01.plan` | `e5815ac0a03f8f40d804d49e194d77877bbdd058ced1da5b2f0252c8ecd94095` | `qgc_saved/drone_01.qgc_resaved.plan`, `a9a0eda8347c6fe110634f3ceb725a525ada7228fa7d669a2e688a216abacbde` | **NO_SEMANTIC_DIFFERENCES** (rc 0), `comparison_drone_01/` | 4 PRESENTATION; 0 QGC_METADATA, SEMANTIC_CHANGE, ADDED, REMOVED y UNDETERMINED |
| `drone_02.plan` | `df2e0d6681c8695fc23bc7bda18ae45214c2403c625fcd934a90e38447853740` | `qgc_saved/drone_02.qgc_resaved.plan`, `62522bb557ca2360e1aeded852c3580b74ea62c16cda6f026c82c2d2e5208171` | **NO_SEMANTIC_DIFFERENCES** (rc 0), `comparison_drone_02/` | Las mismas 4 PRESENTATION; 0 de las demás categorías |

Las 4 PRESENTATION de cada archivo son el mismo número escrito de otra forma:
- `plannedHomePosition[2]`: `584.0` → `584`;
- `param7` de NAV_TAKEOFF y de los dos NAV_WAYPOINT: `5.0` → `5`.

A diferencia de la primera importación del 27/10, en la que hubo 3, no aparece ninguna fila QGC_METADATA. Cada comparación conserva `original.plan`, `saved.plan`, `text.diff`, `comparison.md`, `comparison.json` y su propio `SHA256SUMS`; la salida del comparador está en `comparison_<dron>.stdout` y `.rc`.

## Procedimiento y condiciones

- **Procedimiento:** el de [qgc-first-import-procedure.md](../../../docs/qgc-first-import-procedure.md), sin cambios, con `QGC_PLAN_DIR` apuntando a `plans/` del paquete `hermes_finalized_package_two_drones_2026_10_30`.
- **Montajes:** originales en solo lectura en `/data/plan`; la única carpeta escribible es `qgc_saved/` (`compose_qgc_config.yaml`).
- **Servicio:** `network_mode: none` y `cap_drop: ALL`.
- **Imagen:** `tfg/qgroundcontrol:5.1.5`, `sha256:c6a5c57a…f314` (`preregistration.txt`).
- **Paquete:** verificado antes (`SHA256SUMS` y `verify` INTEGRITY_VERIFIED) y después de la importación (`SHA256SUMS` OK). Los dos originales tienen los mismos hashes antes y después.
- **Visualización:** los dos primeros arranques de QGC no mostraron ninguna ventana por un fallo de WSLg, no de QGC. El cliente RDP de Windows (`msrdc.exe`) llevaba caído desde el 29/10 a las 14:36. Se relanzó una vez, con autorización, y después Joel abrió y guardó los dos planes. Detalle y logs en `diagnostics_wslg/diagnosis.md`.

## Observación visual (declarada por Joel; las capturas no están en este directorio)

- **Observado:** las capturas de los dos planes muestran **cuatro ítems: Takeoff, dos Waypoints y Land**.
- **No comprobado visualmente:** coordenadas, alturas, modo de altura, *Planned Home*, firmware o vehículo supuesto, avisos al abrir, AutoConnect, geovalla, puntos de rally y la versión que muestra la aplicación. Esos valores solo están acreditados por el comparador sobre los archivos.

**Desconocidos:** la versión literal mostrada por QGC, los avisos al abrir y el estado de AutoConnect en pantalla. Las capturas se pueden añadir después a `screenshots/` con su propio registro, sin modificar esta evidencia.

## Qué acredita y qué no

- **Acreditado:** QGroundControl 5.1.5, según la imagen, abrió y volvió a guardar cada uno de estos dos archivos sin cambios semánticos, según las reglas del comparador.
- **No acreditado:**
  - la carga en SITL o en un vehículo;
  - la lectura de vuelta desde el autopiloto;
  - la ejecución;
  - el hardware;
  - otras versiones de QGC u otros archivos.
- **Geometría:** las holguras del emplazamiento sintético `synthetic_hermes_rehearsal_v1` (≥ 4 m del seto y 12 m de separación planificada) no acreditan una separación operativa segura ni la ausencia de conflictos en vuelo.
- **Pendiente para una ejecución posterior,** no exigido para esta importación: observación del spawn, parámetros efectivos del autopiloto, aprobación del operador vinculada a los hashes, y carga y lectura de vuelta en SITL con Codex y con autorización propia.

`SHA256SUMS` de este directorio lo genera `write_manifest`, que omite los archivos llamados `SHA256SUMS` y `README.md`. Los `SHA256SUMS` de cada `comparison_<dron>/` se verifican con `sha256sum -c` dentro de su directorio.

## Adenda (30/10/2026): capturas incorporadas

En `screenshots/` hay 4 capturas de QGC, de las 8 que seleccionó Joel; las otras 4 no son de QGC y no se incorporan. Lo que se lee en ellas está en `screenshots/visual_review.md`: plan **drone_01** (dos capturas) y **drone_02**, cada uno con **4 items**: Takeoff, Waypoint, Waypoint y Land; además, el diálogo inicial de preferencias. Siguen sin confirmar la versión mostrada, AutoConnect y la ausencia de avisos. Ni los originales ni las comparaciones ni las copias guardadas se modificaron. `SHA256SUMS.before_screenshots.txt` conserva el manifiesto anterior.
