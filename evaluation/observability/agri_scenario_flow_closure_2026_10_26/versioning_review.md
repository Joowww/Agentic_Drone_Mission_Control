# Lista de revisión para versionar el escenario agri_demo_001

Lista preparada para que Joel la revise. No se ha hecho staging, commit ni push. El estado en Git
es el del árbol de trabajo del 26/10/2026.

**Dos conjuntos distintos:**
- **Ejecución mínima:** lo que necesita un clon de HEAD para la consulta histórica, la demostración
  sintética, la comprobación de integridad y el informe. Es exactamente
  [`distribution_inventory.json`](distribution_inventory.json): 22 entradas obligatorias (0,97 MB)
  más 2 opcionales (actualizado el 27/10/2026).
- **Mantenimiento y pruebas:** lo anterior más los tests, sus dependencias y la documentación
  necesarios para modificar y volver a probar la implementación.

**Responsable:** «Claude» es código de esta línea; «Codex» son cambios de Codex pendientes de su
propia revisión. Donde el historial no permite atribuirlo con seguridad pone «mixto».

## 1. Código nuevo y modificado

| Archivo | Git | Responsable | Ejecución mínima | Mantenimiento |
| --- | --- | --- | --- | --- |
| `main.py` | modificado | Claude (opción 5) | sí | sí |
| `tools/agri_scenario_flow.py` | nuevo | Claude | sí | sí |
| `graph/agri_scenario_graph.py` | nuevo | Claude | sí | sí |
| `tools/agri_scenario_distribution.py` | nuevo | Claude | sí | sí |
| `reporting/agri_scenario_summary.py` | nuevo | Claude | sí | sí |
| `tools/agri_ground_coordinator.py` | nuevo | Claude | sí | sí |
| `tools/agri_ground_demo.py` | nuevo | Claude | sí | sí |
| `tools/rover_passive_journal.py` | nuevo | mixto (lector; Claude añadió `analyze_capture` y el informe) | sí | sí |
| `observability/hermes_capture_run.py` | nuevo | mixto | sí (verifica manifiestos) | sí |
| `reporting/rover_identity_facts.py` | nuevo (27/10) | Claude | sí (`--identity-trial-root`) | sí |
| `observability/mission_query_cases.py` | nuevo | mixto | sí (lo importa el resumen) | sí |
| `tools/rover_ground_executor.py` | modificado | **Codex** | **sí**: la versión de HEAD añade el bloqueo `executor_accepts_navigation_request` | sí |
| `tools/rover_control.py` | modificado | **Codex** | **sí**: la versión de HEAD es incompatible (20 tests fallan) | sí |
| `tools/rover_ros2_adapter.py` | modificado | **Codex** | no (basta HEAD) | sí (recorrido conjunto) |
| `tools/hermes_mcp_server.py` | modificado | mixto (`get_scenario_view`) | no | sí (vista H3b) |
| `observability/opik_export.py` | modificado | mixto | no (basta HEAD) | sí (hashes H1/H3) |

## 2. Tests y fixtures

| Archivo | Git | Responsable | Necesita además |
| --- | --- | --- | --- |
| `tests/test_agri_scenario_flow.py` | nuevo | Claude | Inventario mínimo. Con la captura `/3` ausente, un test se salta con un motivo explícito |
| `tests/test_agri_scenario.py` | nuevo | Claude | Evidencias H3 y piloto (sección 5) |
| `tests/test_agri_ground_coordinator.py` | nuevo | Claude | — |
| `tests/test_rover_identity_facts.py` | nuevo (27/10) | Claude | La sesión de identidad de Codex (se salta si no está) |
| `tests/test_agri_ground_joint.py` | nuevo | Claude | **Codex:** `tests/test_rover_ground_executor.py` (fixture `setup`, modificado) y `tests/test_rover_navigation.py` (nuevo) |
| `tests/test_rover_passive_odometry_fields.py`, `tests/test_rover_passive_journal.py` | nuevos | mixto | **Codex:** fuentes del colector `tools/rover_passive_rclcpp/*` (modificadas; el fixture compila el colector), la captura `/3` y el ensayo `eb113b19` |
| `tests/test_rover_goal_progress.py` | nuevo | **Codex** | — (se ejecuta junto a las regresiones de R1) |
| `tests/test_opik_export.py`, `tests/test_hermes_capture_run.py` | modificado / nuevo | mixto | Capturas H1/H3 |

No hay fixtures en archivos aparte: los tests construyen los suyos (copias en `tmp_path`, dobles
etiquetados).

## 3. Dependencias

| Archivo | Git | Contenido |
| --- | --- | --- |
| `requirements.txt` | modificado | Dependencias directas, con `pydantic` y `PyYAML` añadidas |
| `constraints-verified.txt` | nuevo | Versiones exactas de una instalación aislada. **Incluido en el inventario mínimo** |
| `requirements-dev.txt`, `requirements-observability.txt` | sin cambios | Desarrollo y observabilidad |

**Versiones verificadas:**
- Python 3.12.3 en Linux x86_64 (WSL2), con las pruebas citadas en la cabecera de las restricciones.
- No se han probado otras versiones ni plataformas. Eso no significa que sean incompatibles: queda
  sin verificar.

## 4. Documentación

| Archivo | Git |
| --- | --- |
| `docs/hermes-planning.md`: sección técnica para la memoria y notas del 26/10 | modificado (contiene también cambios anteriores) |
| `evaluation/observability/agri_scenario_flow_closure_2026_10_26/README.md` y esta lista | nuevos |
| `evaluation/observability/agri_scenario_flow_2026_10_26/README.md` (con la corrección de reproducibilidad) | nuevo |
| `evaluation/observability/agri_r1_recovery_correction_2026_10_26/README.md` | nuevo |

## 5. Evidencias

| Directorio o archivo | Manifiesto | Obligatoria para |
| --- | --- | --- |
| `simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/` | `SHA256SUMS` y `manifest.json` | **Ejecución** (fuente `archive`) |
| `evaluation/observability/agri_planning_h1_nous_2026_10_24/` | `SHA256SUMS` | **Ejecución** (registro de vinculación) |
| `evaluation/observability/agri_scenario_h3b_nous_2026_10_24/` | `SHA256SUMS` | **Ejecución** (vista recibida por H3b) |
| `evaluation/observability/agri_scenario_view_h2_2026_10_24/` | `SHA256SUMS` | **Ejecución** (regresión de la vista) |
| `missions/examples/agri_demo_001_sector_{a,b}.json` | hash en el código (`REFERENCE`) | **Ejecución** (H0) |
| `simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-…/` (6,2 MB, Codex) | `manifest.json` | **Opcional**: hechos medidos. Sin ella, `NOT_AVAILABLE` y los mismos bloqueos |
| `simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-…/` (2,6 MB, Codex) | `manifest.json` | **Opcional**: hechos de identidad. Sin ella, `NOT_AVAILABLE` y nada más cambia |
| `evaluation/observability/agri_scenario_h3_nous_2026_10_24/`, `agri_scenario_pilot_nous_2026_10_24/` | `SHA256SUMS` | Mantenimiento (`test_agri_scenario.py`) |
| `simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-…/` (Codex) | `manifest.json` | Mantenimiento (lector pasivo, captura `/2`) |
| `evaluation/observability/agri_r1_*`, `agri_scenario_flow*_2026_10_26/`, `agri_scenario_pilot_audit_2026_10_25/` | `SHA256SUMS` | Evidencia derivada para la memoria. No la necesita ninguna ejecución |

## 6. Excluido

No hace falta ni debe versionarse:
- `missions/generated/` (almacenes operativos, ignorado);
- `.venv/` y cualquier venv;
- sesiones de Hermes (`~/.hermes`);
- `.env` y claves (`OPIK_API_KEY`, `LANGSMITH_API_KEY`);
- temporales del contenedor y directorios temporales de pruebas.

`agri_scenario_distribution check` rechaza rutas bajo `missions/generated`, `.venv` y `.env`, y
busca patrones de credenciales en el conjunto.
