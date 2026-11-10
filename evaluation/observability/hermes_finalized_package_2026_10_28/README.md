# Misiones finalizadas por Hermes → paquete de escenario (28/10/2026): demostración offline

**Resultado:** las dos misiones finalizadas en la ejecución real r2 se asocian de forma explícita a un emplazamiento sintético y a una flota, se derivan, se validan y se empaquetan con `tools.scenario_package` y el exportador estricto V2.
- **drone_01:** **GENERATED** (`plans/drone_01.plan`).
- **drone_02:** **BLOCKED_VALIDATION_FAILED** por geometría.
- **Paquete:** `PARTIAL`, `deployment_ready: false` y aprobación `ABSENT`.

No hubo inferencias, Opik, QGC, simulación, vehículos, cargas, controles ni movimiento. Las misiones originales y las evidencias de entrada no se modificaron (`inputs_before.sha256` = `inputs_after.sha256`).

## Comando (`command.txt`)

```bash
python -m tools.scenario_package package-finalized \
  --store evaluation/observability/planning_container_real_2026_10_28_r2/store \
  --hermes-evidence evaluation/observability/planning_container_real_2026_10_28_r2 \
  --scenario-binding evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json \
  --assign drone_01=e31bd08d-19ed-440e-b815-94f8b9c062d5/0b6af58a-943c-4f06-a631-1a55d4a66d6d@TAKEOFF_A \
  --assign drone_02=c244d68c-819e-4324-b99a-7d299b97081d/dd6055ee-5090-40c9-98b9-d0b8cb85e93a@TAKEOFF_B \
  --rover rover_01@ROVER_START --site missions/sites/synthetic_orchard_v1.site.json \
  --fleet missions/fleets/agri_demo_fleet.json --target sitl --out <directorio nuevo>
```

También desde el menú: `python main.py` → 5 → 3 → `f`, que llama al mismo CLI. Documentación: [site-fleet-export.md](../../../docs/site-fleet-export.md) §17.

## Qué recibe de Hermes y qué se conserva (`package/instance.json`, `package/manifest.json`)

| Elemento | Valor |
| --- | --- |
| Ejecución de Hermes | `real-hermes-planning-container-20261028-r2`: `nous` / `poolside/laguna-s-2.1:free`, retorno 0, 1 invocación, commit `d923a5eb`, revisión `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`. Todo el directorio de la evidencia coincide con su `SHA256SUMS` (`7e952d76…`). Copias en `package/hermes/run/` |
| drone_01 | Borrador `e31bd08d-…` (revisión 1) y finalización `0b6af58a-…`. Misión `agri_demo_001_h1_sector_a`, `321ad647…`. FEASIBLE/APPROVED y `qgc_export` REFUSED en la finalización. Citada en la respuesta final de Hermes |
| drone_02 | Borrador `c244d68c-…` (revisión 1) y finalización `dd6055ee-…`. Misión `agri_demo_001_h1_sector_b`, `079e25a3…`. Mismo estado de validación |
| Integridad | `load_finalization` con el almacén reubicado (`relocated_from: /opt/tfg/missions/generated/…`). Hashes de misión, borrador y estado de origen; revisión igual a la del estado de origen. Los archivos de la finalización figuran en el `SHA256SUMS` de la ejecución |
| Originales | Copia byte a byte en `package/hermes/<vehículo>/` (`mission.json`, `finalization.json`, `source_draft.json`, `source_draft_state.json`) |
| Vehículo lógico | El de la misión, que debe ser igual al asignado: drone_01 y drone_02 de `agri_demo_fleet` |
| Emplazamiento, flota y perfil | `synthetic_orchard` v1 (SYNTHETIC), `agri_demo_fleet` y `QGC_PLAN_ARDUCOPTER_V2`; copias y hashes en el paquete |
| Puntos del escenario | Binding de H1 (`scenario_binding.json`): POI_A1→WP1 y POI_A2→WP2 de drone_01, aplicados solo porque el hash de la misión coincide |

## Asociación y derivados

El operador elige el emplazamiento, la flota y el punto de despegue de cada vehículo.
- **Cómo se derivan:** los desplazamientos norte/este de cada waypoint respecto al home declarado en la misión (41.275, 1.987) se colocan sobre ese punto en el marco del emplazamiento. Coinciden con los offsets de `geometry_intent`, con una diferencia de 0,0 m.
- **Qué cambia:** la misión derivada tiene un id nuevo, un hash nuevo y su propia validación determinista. La aprobación original **no se hereda**.
- **AMSL del home planificado:** 584,0 m, el del emplazamiento (terreno declarado plano).

| Vehículo | Despegue | Misión derivada | Estado | Motivo |
| --- | --- | --- | --- | --- |
| drone_01 | TAKEOFF_A (−4, −6) | `…_on_synthetic_orchard_v1_TAKEOFF_A`, `b264fba5…`; WP1 (−8, 2) y WP2 (−8, 10); validación FEASIBLE/APPROVED | **GENERATED**, `.plan` `FILE_MATCHES_EXPECTATIONS` (lectura de vuelta con nuestro importador REDUCED) | — |
| drone_02 | TAKEOFF_B (4, −6) | `…_TAKEOFF_B`, `4a0eaa63…`; WP1 (8, 2) y WP2 (8, 10) | **BLOCKED_VALIDATION_FAILED** | WP1→WP2 y WP2→regreso tocan la exclusión TREE_ROW_1 (y de 10 a 12). Desde TAKEOFF_A ocurre lo mismo. **El emplazamiento no se modificó para forzarlo** |

**Tareas terrestres y coordinación:**
- **R1** (rover_01, ROVER_START → POI_A1, que es el WP1 derivado de drone_01): línea PASS en el área transitable, `FORMAT_PENDING` y transformación al rover NOT_ACCREDITED.
- **Coordinación PASS:** HERMES_drone_01 → HERMES_drone_02 → R1, con drone_02 tras drone_01 COMPLETED y R1 tras drone_01 POI_REACHED POI_A1, la misma secuencia que H2.

`verify.json`: `INTEGRITY_VERIFIED`. Se ejecutó dos veces con la misma entrada y la salida fue idéntica byte a byte.

## Rechazos (`rejections/`)

| Caso | Resultado |
| --- | --- |
| 1. `mission.json` alterado en una copia del almacén | `[REFUSED] … does not match its snapshot`, rc 2 y nada escrito |
| 2. Finalización del sector B asignada a drone_01 | `[REFUSED] assignment refused: … is a mission for drone_02, not drone_01`, rc 2 |
| 3. Emplazamiento incompleto (plantilla DroneLab) | `BLOCKED_MISSING_DATA` con la lista exacta de geometría y referencias que faltan. Sin misiones derivadas ni `.plan` |
| 4. `POI_1` como punto de despegue | `BLOCKED_VALIDATION_FAILED`: «'POI_1' is not a planned_takeoff point of the site» |

## Pruebas (`pytest_affected.txt`)

- **`test_scenario_package.py` y `test_site_geometry.py`:** 57 passed, de las cuales 6 son nuevas: la positiva, los rechazos, la entrada de menú y la equivalencia de la validación local.
- **Consumidores de `load_finalization` y flujo del escenario:** 758 passed antes del último ajuste de texto del bloqueo; tras él, `test_agri_scenario_flow`, `test_mission_state` y `test_partial_geometry_planning` dieron 91 passed.
- No se ejecutó la suite general.

## Código cambiado

- `planning/mission_artifacts.py`: `drafts_root` opcional en `load_finalization` para un almacén reubicado. El comportamiento por defecto no cambia.
- `planning/site_validation.py`: `validate_aerial_local_route` y `validate_ground_local_target`, con el mismo núcleo de comprobaciones. Las salidas de las funciones existentes no cambian.
- `planning/scenario_instance.py`: `finalized_instance` y la secuencia de agri_demo_001 compartida con el histórico H2, cuya salida no cambia.
- `tools/scenario_package.py`: `package-finalized` y una sección de origen en el informe.
- `tools/agri_scenario_flow.py`: acción `f` del submenú.

## Pendiente antes de cargarlo en SITL

1. **Geometría de drone_02:** el sector B no cabe en este emplazamiento sintético. Hace falta otro emplazamiento cuya geometría lo admita, u otra misión.
2. **Referencias:**
   - en SITL, el home efectivo lo fija ArduPilot al armar en la posición de spawn;
   - no hay ninguna transformación acreditada entre el spawn de Gazebo y el marco del emplazamiento;
   - antes de cargar hay que observar el lanzamiento en esa sesión y comprobar que coincide con TAKEOFF_A, o reinstanciar.
3. **Aprobación** del operador vinculada a los hashes (`approval-draft`). Hoy está `ABSENT`.
4. **Parámetros del autopiloto** sin leer (`WP_RADIUS_M`, `WP_YAW_BEHAVIOR`, `WP_SPD`, `FS_*`, `LAND_SPD_MS`).
5. **Import, carga y lectura de vuelta:** importación en QGC de este `.plan`, carga en SITL y lectura de vuelta comparada. Todo NOT_DONE. Debe coordinarse con Codex y tener su propia autorización. El `.plan` importado el 27/10 era otro archivo.

## Para una futura versión de la imagen `app` (no reconstruida)

- Los 5 módulos cambiados.
  - La imagen actual `tfg/app:2026.10.28` tiene las versiones anteriores.
  - El binding de H1 sí está en la imagen.
  - La evidencia r2 no está.
- Un montaje **de solo lectura** del almacén de planificación del estudiante (`TFG_PLANNING_STORE`) en el servicio `app`, para usar `--store` con sus propias finalizaciones.
