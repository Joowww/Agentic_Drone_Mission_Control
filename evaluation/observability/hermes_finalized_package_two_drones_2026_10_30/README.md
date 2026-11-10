# Misiones finalizadas por Hermes → paquete con los dos drones, sobre un emplazamiento SINTÉTICO de ensayo (30/10/2026)

**Resultado:** caso positivo, offline y sintético. Las dos misiones finalizadas en la ejecución real r2 se colocan sobre un emplazamiento **nuevo de ensayo** y salen las dos **GENERATED**, con su `.plan` verificado contra la misión.
- **Paquete:** `COMPLETE_OFFLINE`.
- **R1:** `FORMAT_PENDING`.
- **Aprobación y despliegue:** aprobación `ABSENT` y `deployment_ready: false`.

Es un resultado distinto del caso negativo `hermes_finalized_package_2026_10_28` (paquete PARTIAL sobre `synthetic_orchard_v1`, sector B rechazado por TREE_ROW_1). Aquel se conserva intacto y su `verify` sigue dando INTEGRITY_VERIFIED.

No hubo inferencias, QGC, simulación, cargas, controles ni movimiento. **No se afirma compatibilidad con QGC:** estos `.plan` no se han importado.

## Comando (`command.txt`)

```bash
python -m tools.scenario_package package-finalized \
  --store evaluation/observability/planning_container_real_2026_10_28_r2/store \
  --hermes-evidence evaluation/observability/planning_container_real_2026_10_28_r2 \
  --scenario-binding evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json \
  --assign drone_01=e31bd08d-19ed-440e-b815-94f8b9c062d5/0b6af58a-943c-4f06-a631-1a55d4a66d6d@TAKEOFF_A \
  --assign drone_02=c244d68c-819e-4324-b99a-7d299b97081d/dd6055ee-5090-40c9-98b9-d0b8cb85e93a@TAKEOFF_B \
  --rover rover_01@ROVER_START --site missions/sites/synthetic_hermes_rehearsal_v1.site.json \
  --fleet missions/fleets/agri_demo_fleet.json --target sitl --out <directorio nuevo>
```

## Emplazamiento de ensayo `missions/sites/synthetic_hermes_rehearsal_v1.site.json` (`61d47a4e…`)

- **Identificación:** `status`/`provenance` SYNTHETIC. El nombre lo declara «ensayo offline … (no es DroneLab ni un campo real)». `validate-site` lo da VALID, con exportación SITL disponible y exportación de campo bloqueada («SYNTHETIC site: never a proposal for hardware»).
- **Referencias:** las mismas que `synthetic_orchard_v1`: CMAC −35.363262, 149.165237; AMSL 584,0 m; terreno DECLARED_FLAT; límite de 30 m. `synthetic_orchard_v1` no se modificó (hash `0db007e8…` antes y después).

**Geometría** (marco local, +y = norte):

| Elemento | Diseño |
| --- | --- |
| Perímetro | No rectangular: (−22,−12) (22,−12) (22,18) (0,24) (−22,18) |
| Despegues | TAKEOFF_A (−6,−6) en PAD_A y TAKEOFF_B (6,−6) en PAD_B |
| Exclusiones | CENTRAL_HEDGE x −2…2, y 1…14 (aire y suelo), entre los dos sectores; NORTH_ROW y 16…18 (aire y suelo); STORE (solo suelo) |
| Rover | ROVER_BAY y ROVER_START (0,−9,5); área transitable y −11,5…6 |

**Rutas resultantes** (offsets de cada misión desde su despegue):
- **Sector A:** (−10,2) y (−10,10).
- **Sector B:** (10,2) y (10,10).
- **Holguras:** las dos rutas quedan a ≥ 4 m del seto y a ≥ 6 m de NORTH_ROW, y su separación mínima planificada es de 12 m.
- **Diseño:** la geometría se diseñó para admitir estas dos rutas. **No es un resultado sobre un lugar real.**

## Correspondencia de cada derivada (`correspondence.json`, `tools/check_correspondence.py`)

Comprobación independiente: recalcula desde los propios archivos del paquete, el almacén r2 y el emplazamiento. Para las dos misiones pasan las 10 comprobaciones (`CORRESPONDS`):

| | drone_01 | drone_02 |
| --- | --- | --- |
| Original (intacta en el almacén y copiada byte a byte en `hermes/<vehículo>/`) | `321ad647…` | `079e25a3…` |
| Derivada (hash nuevo y validación determinista propia APPROVED) | `b215a38b…` | `c8f7c80e…` |
| Vehículo | drone_01 = misión = asignación | drone_02 = misión = asignación |
| Despegue → home de la derivada | TAKEOFF_A (−6,−6) → lat/lon por `local_to_geo` | TAKEOFF_B (6,−6) |
| Offsets recalculados frente a `geometry_intent` | N8/E−4 y N16/E−4; error máx. 4,7·10⁻¹⁰ m | N8/E4 y N16/E4; error máx. 4,7·10⁻¹⁰ m |
| `plannedHomePosition` del `.plan` | [−35.3633159, 149.16517091, 584.0] | [−35.3633159, 149.16530309, 584.0] |
| Resto de campos de la misión | Iguales: vehículo, objetivo, entorno, restricciones, failsafe, altitudes 5 m relativas, acciones y regreso | Iguales |
| Aprobación | No heredada | No heredada |

El `.plan` se compara con la precisión que declara el exportador (8 decimales en lat/lon y 3 en altitud). `verify.json`: INTEGRITY_VERIFIED, con los dos planes `FILE_MATCHES_EXPECTATIONS` (lectura de vuelta con nuestro importador REDUCED).

## Coordinación PASS: qué significa y qué no

El manifiesto ya separa cuatro dimensiones. Desde esta tanda, el resumen y el informe lo dicen expresamente.

| Dimensión | Campo | Aquí |
| --- | --- | --- |
| Estructura de dependencias | `coordination.status` (`coordination_checks`: tareas, vehículos, dependencias existentes, sin ciclos, orden coherente) | PASS: HERMES_drone_01 → HERMES_drone_02 → R1; R1 tras POI_REACHED POI_A1 |
| Artefactos disponibles | `package_status` y el estado de cada artefacto | COMPLETE_OFFLINE: los dos `.plan`. R1 sin exportador |
| Aprobación | `approval.status` | ABSENT |
| Preparación para ejecutar | `deployment_ready` y `deployment_blockers` | false. Bloqueos: **R1 FORMAT_PENDING**, aprobación ABSENT, import en QGC, carga, lectura de vuelta y ejecución NOT_DONE |

**Cambios en `tools/scenario_package.py`:**
- **`deployment_blockers`:** enumera ahora cada tarea no GENERATED y cada tarea terrestre `FORMAT_PENDING`. En el caso negativo incluiría «HERMES_drone_02 BLOCKED_VALIDATION_FAILED».
- **Resumen:** dice «dependency structure PASS (structural only: not artifact availability, approval or execution readiness)» y lista los bloqueos.
- **Informe:** añade «Bloqueos de despliegue».

Los paquetes ya sellados no se regeneraron.

## Pruebas y reproducibilidad

- **Pruebas afectadas** (`pytest_affected.txt`): `test_scenario_package.py` y `test_site_geometry.py`, 58 passed. La positiva es nueva; la negativa comprueba ahora los bloqueos. `test_agri_scenario_flow.py`: 47 passed. No se ejecutó la suite general.
- **Reproducibilidad** (`reproducibility.txt`): la misma entrada produce el mismo paquete byte a byte.
- **Entradas:** sin cambios (`inputs_before.sha256` = `inputs_after.sha256`). Incluyen la evidencia r2, el binding de H1, el caso negativo y `synthetic_orchard_v1`.

## Pendiente antes de cargarlo en SITL

1. **Referencias:**
   - el home efectivo lo fija ArduPilot al armar, en el spawn de Gazebo;
   - no hay ninguna transformación acreditada entre spawn y emplazamiento (TAKEOFF_A/B de este ensayo frente a los spawns −2,0 y 2,0 de `tfg_demo.launch.py`);
   - hay que observar el lanzamiento en la sesión y reinstanciar si difiere.
2. **Aprobación** del operador vinculada a los hashes (`approval-draft`).
3. **Parámetros del autopiloto** sin leer.
4. **R1:** sin exportador de rover y con la transformación al rover NOT_ACCREDITED.
5. **Importación, carga y lectura de vuelta:** importar estos `.plan` en QGC, cargarlos en SITL y leerlos de vuelta. Todo NOT_DONE, con Codex y con autorización aparte.

No se reconstruyeron imágenes ni se volvió a empaquetar la entrega para estudiantes, que sigue siendo solo con Hermes.
