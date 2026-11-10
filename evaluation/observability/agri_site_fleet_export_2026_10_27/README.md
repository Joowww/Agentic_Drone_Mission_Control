# Emplazamiento, flota y paquetes de escenario: demostraciones offline (27/10/2026)

Generadas con `tools/scenario_package.py`. La salida completa de la terminal está en [`terminal.txt`](terminal.txt). La documentación técnica está en [`docs/site-fleet-export.md`](../../../docs/site-fleet-export.md) y el protocolo del ensayo integrado (no ejecutado) en [`docs/integrated-trial-protocol.md`](../../../docs/integrated-trial-protocol.md).

**Sin efectos:**
- No se ha usado Docker ni la simulación.
- No se ha importado nada en QGroundControl ni subido nada a un vehículo.
- No hay inferencias ni Opik.
- Ningún paquete está listo para desplegar (`deployment_ready: false` en todos).
- `verify` = `VERIFIED` significa integridad del paquete y de sus `.plan`; no significa que el paquete esté completo ni aprobado.

## Entradas

| Archivo | sha256 |
| --- | --- |
| `missions/sites/synthetic_orchard_v1.site.json` (SINTÉTICO) | `0db007e872c8c9d04ae4cc24b733d7753dfbd7e814fe3ab725ee580785e3eb05` |
| `missions/sites/synthetic_orchard_v2.site.json` (SINTÉTICO, POI_1 movido) | `7b27b00719dd1e6a7c309dff3b4b1b129a9a8b699e21e7b0d94e059e35356d14` |
| `missions/sites/dronelab.template.site.json` (PLANTILLA pendiente de medición) | `10c6ee168ab4fe6473d01101f9494b97bd934ba6da85776b0996e0117800d8a7` |
| `missions/fleets/agri_demo_fleet.json` | `45b09915aa95e48726e27bd5e3fb33c3018bb40e42593712f34a4068655a296c` |
| `missions/templates/agri_poi_visit_v1.json` | `62dd9c06a8520d76d9e6d0bc16c75f1fbb635a97fbef5454fdb0540ab827d314` |
| `missions/templates/agri_poi_visit_unresolved_fleet_v1.json` (variante de prueba) | `6435f1a2cf905d471297f8bfe5058e21a6069f08a40cd8dadc888c05db9bd659` |
| `missions/templates/agri_poi_visit_crossing_v1.json` (variante de prueba) | `84f2e4ce6bddbeda386ba13c137173e0d8247fe991c0d1c922cfca9ec3740c79` |
| Registro H2 `simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/` | comprobado contra su `SHA256SUMS`; no modificado |

## Resultados

| Demo | Paquete | Instancia | Estado | Artefactos |
| --- | --- | --- | --- | --- |
| a | `packages/a_historical_h2_sitl` | `a03d3b06eb374ca7` | COMPLETE_OFFLINE, SITL_HISTORICAL | drone_01 y drone_02 `GENERATED`, `.plan` verificados. R1 `FORMAT_PENDING` |
| b | `packages/b_synthetic_orchard_v1_sitl` | `4ffa1d92f0c7bc21` | COMPLETE_OFFLINE, SYNTHETIC | A1 y A2 `GENERATED`. Línea R1 `PASS` en su área |
| b′ | `packages/b_synthetic_orchard_v1_field_refused` | `4ffa1d92f0c7bc21` | PARTIAL | `BLOCKED_MISSING_DATA`: «SYNTHETIC site: never a proposal for hardware» |
| c | `packages/c_dronelab_template_field` | `5c73dd4dbb413cab` | PARTIAL, TEMPLATE | `BLOCKED_MISSING_DATA` (emplazamiento INCOMPLETE). Ningún `.plan` |
| d | `packages/d_unresolved_fleet` | `b39bcceac2e07385` | PARTIAL | A1 `GENERATED`; mini_drone_01 `COMPATIBILITY_PENDING`; drone_99 `BLOCKED_MISSING_DATA`. Coordinación `FAIL` |
| e | `packages/e_exclusion_crossing` | `1b81d43e7232e4a4` | PARTIAL | A2 `BLOCKED_VALIDATION_FAILED`: POI_3 → POI_5 corta TREE_ROW_1 con extremos válidos. R1 `REQUIRES_PLANNING` (cruza la acequia, exclusión solo terrestre) |
| f | `packages/f1_site_v1_approval` / `packages/f2_site_v2_same_approval` | `4ffa1d92…` / `9a4c1823…` | aprobación `BOUND` / `STALE` | La misma aprobación sintética: en v2 cambian la instancia, las misiones y los `.plan` de A1 (`4aa76b29…` → `422f35de…`) |

El último `package` de `terminal.txt` intenta escribir otra vez sobre `b` y se rechaza (`FileExistsError`, rc 2).

**Observaciones:**
- **(a) El rebase reproduce H2:** sobre la posición de lanzamiento registrada, se reproduce el error horizontal registrado de cada waypoint, con una diferencia máxima de 1 mm.
  - Las referencias se guardan por separado: home declarado (41,275 / 1,987), lanzamiento observado (float32, 584,19 m), origen del mundo Gazebo (584,0 m) y spawn. Home efectivo y origen del estimador: `NOT_RECORDED`.
  - Separación mínima planificada entre ambas rutas: 5,54 m. La simultaneidad queda `NOT_CLEARED`.
- **(f) Aprobación:** `approval_synthetic_fixture_b.json` está etiquetado `SYNTHETIC_TEST_FIXTURE (not a person)`. Es un artefacto de prueba, no una aprobación de Joel.
  - `approval_draft_b.json` muestra el borrador real: `approved_by` vacío.
- **Identidad de misión:** el `.plan` no la contiene. Dos misiones con distinto `mission_id` y la misma geometría producen el mismo `.plan` (A1 en b, d y e: `4aa76b29…`). La identidad vive en el manifiesto.
- **Márgenes:** todos `NOT_ACCREDITED`, porque faltan la geometría del vehículo y las incertidumbres. El margen de 1 m es declarado.

## Reproducción

Desde la raíz del repositorio. Los mismos comandos con un `--out` nuevo producen bytes idénticos (comprobado en `tests/test_scenario_package.py`).

```bash
python -m tools.scenario_package package-historical --fleet missions/fleets/agri_demo_fleet.json --out /tmp/a
python -m tools.scenario_package package --template missions/templates/agri_poi_visit_v1.json --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json --target sitl --out /tmp/b
diff -r /tmp/b evaluation/observability/agri_site_fleet_export_2026_10_27/packages/b_synthetic_orchard_v1_sitl
python -m tools.scenario_package verify evaluation/observability/agri_site_fleet_export_2026_10_27/packages/a_historical_h2_sitl
```

Los tests pertinentes son `tests/test_site_geometry.py` y `tests/test_scenario_package.py`.
