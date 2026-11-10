# Exportación `.plan`: semántica cerrada, una sola ruta e inventario nuevo (27/10/2026)

Todo offline:
- No hay Docker, simulación, conexiones, cargas, inferencias ni Opik.
- No se ha abierto QGroundControl. Ningún paquete está listo para desplegar.
- La compatibilidad del `.plan` con QGroundControl o con un vehículo **no** está establecida.

La documentación está en:
- [`docs/site-fleet-export.md`](../../../docs/site-fleet-export.md): §8, §15 y §16;
- [`docs/qgc-first-import-procedure.md`](../../../docs/qgc-first-import-procedure.md);
- [`docs/integrated-trial-protocol.md`](../../../docs/integrated-trial-protocol.md).

## Contenido

| Archivo | Qué es |
| --- | --- |
| `legacy_exporter_reproduction.txt` | El exportador de HEAD (`83a147d`, sha256 `1e3fa8fb…`), ejecutado sobre una copia temporal. Convierte `survey` y `take_photo` en `NAV_WAYPOINT`, escribe `plannedHomePosition` con 0,0 m como AMSL, descarta las velocidades (30/25/10 km/h) y termina en RTL |
| `terminal.txt` | Paquetes V2, `verify`, verificación de un paquete V1 (`PROFILE_SUPERSEDED`), determinismo y rechazo de la entrada de sesión y Hermes (`--export-qgc`: 0 archivos) |
| `packages/a_historical_h2_sitl_v2` | Misiones ejecutadas en H2 expresadas sobre su lanzamiento observado (instancia `da8fe142547421af`). `.plan`: drone_01 `7b07b731…`, drone_02 `cb2148b5…` |
| `packages/b_synthetic_orchard_v1_sitl_v2` | Escenario sobre el huerto SINTÉTICO (instancia `b9cff3e6b6950110`). `.plan`: drone_01 `692c8075…`, drone_02 `d190e055…`. Es el archivo propuesto para la primera importación en QGC |
| `distribution_inventory_site_export.json` | Inventario nuevo (conjunto `agri_flow_site_export`, 50 entradas, 47 obligatorias, 1,2 MB). El del 26/10 no se toca |
| `clean_copy_check.txt` | Copia = `git archive HEAD` + las 50 entradas, con `env -i`, HOME vacío y venv aislado (`requirements-dev.txt` + `constraints-verified.txt`, Python 3.12.3) |

## Resultados

**Una sola ruta:** menú 1–4, finalización y revisión de Hermes, `validate_and_export_qgc` y `--export-qgc` delegan en el exportador estricto. Sin AMSL del home planificado devuelven `qgc_export.status = REFUSED` con motivos y no escriben archivo. Los `.plan` anteriores se listan, no se borran.

**Semántica (perfil V2):**
- Cada paquete trae en `export_report.md` una tabla con cada elemento clasificado como EXACT, CONDITIONED o NOT_IN_PLAN.
- El regreso y el aterrizaje de H2 se expresan con `NAV_LAND` en la coordenada (no con RTL).
- En el paquete histórico el regreso es EXACT; en el sintético, CONDITIONED.

**Comprobación independiente:**
- `FILE_MATCHES_EXPECTATIONS` cubre las expectativas MAVLink y la correspondencia con la misión.
- La lectura con nuestro importador sale **`REDUCED`**: descarta `TAKEOFF` y reduce `LAND` a un waypoint. Se declara como tal.
- `compatibility` = `NOT_ESTABLISHED`.

**Determinismo y copia limpia:**
- Una segunda construcción da los mismos bytes.
- La copia limpia produce paquetes **idénticos byte a byte** a los de este directorio.
- En la copia limpia pasan 111 tests: `test_scenario_package`, `test_site_geometry`, `test_qgroundcontrol_exporter`, `test_hermes_mission_validation` y `test_agri_scenario_flow`.

**Versiones:**

| Tipo | Valor |
| --- | --- |
| Ejecutada acreditada | ArduCopter V4.8.0-dev (755258db), según los registros SITL del 20–26/10. **No** consta en el registro H2 |
| Fuente consultada | Árbol local limpio en `755258dbb452` |
| Documentación | QGC y ArduPilot, rama *master*, consultadas el 27/10 |
| QGroundControl | Desconocida |
| Equipos físicos | Desconocidos |

**Paquetes V1** (`agri_site_fleet_export_2026_10_27`): intactos. `verify` comprueba su integridad e informa `PROFILE_SUPERSEDED`.

**Inventario histórico** (`agri_scenario_flow_closure_2026_10_26/distribution_inventory.json`, sha256 `df4d6d42…`): intacto, y su directorio verifica contra su `SHA256SUMS`. Que ya no describa el árbol actual no significa que su evidencia esté alterada.
