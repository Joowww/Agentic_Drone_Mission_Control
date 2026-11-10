# Mapa del repositorio por directorios

Revisión del 27/10/2026. Para cada ruta se han buscado referencias en código, documentación, manifiestos, inventarios de distribución (`tools/agri_scenario_distribution.py`) y recetas de contenedores (`deploy/*/Dockerfile.dockerignore`). No es una auditoría de cada log. El punto de entrada es [INDEX.md](INDEX.md).

Columnas: **ruta → finalidad → consumidores conocidos → estado → acción**.
- «el subsistema rover»: trabajo activo del subsistema rover, que no se toca.
- «Ocultar»: solo en el explorador de VS Code (ver al final); la ruta no cambia.

| Ruta | Finalidad | Consumidores conocidos | Estado | Acción |
| --- | --- | --- | --- | --- |
| `main.py` | Menú principal | Usuarios; imágenes `app` y `planner` | Vigente | Conservar |
| `agents/` | Extracción con LangChain `ChatOllama` (menú, opciones 1 y 3) | `main.py`; imagen `planner` | Vigente | Conservar |
| `models/`, `planning/`, `inputs/`, `editing/`, `replanning/`, `safety/`, `sessions/`, `graph/`, `reporting/` | Código de misión, validación, exportación, flujo e informes | Importados entre sí; listas de contexto de las imágenes | Vigente | Conservar |
| `observability/` | Ejecutor de capturas de Hermes, exportadores y plugin | `hermes_capture_run`; imagen `planner`; documentos de observabilidad | Vigente | Conservar |
| `tools/` (salvo los de abajo) | Servidor MCP, escenario, paquetes, comparador, inventarios y utilidades de misión | Imágenes, tests y documentos | Vigente | Conservar |
| `tools/rover_*`, `tools/rover_xrce_trace/`, `tools/rover_identity_probe/`, `tools/rover_passive_rclcpp/`, `tools/simulation_lifecycle.py`, `tools/simulation_control.py` | Rover, identidad, transporte, lifecycle y recuperación | El subsistema rover; algunos módulos están en el cierre de imports del servidor MCP | El subsistema rover | No tocar |
| `simulator/`, `telemetry/` | Paquetes con solo `__init__.py` | `simulator`: solo en material del subsistema rover; `telemetry`: ninguno | Andamiaje con seguimiento en Git | Conservar: no es histórico ni temporal |
| `tests/` | Pruebas mantenidas y fixtures (`tests/fixtures`, `conftest.py`) | `pytest.ini` | Vigente | Conservar. Los `test_rover_*` son del subsistema rover |
| `missions/examples`, `sites`, `fleets`, `templates` | Entradas de ejemplo y escenario | `scenario_package`, imágenes e inventarios | Vigente | Conservar |
| `missions/edited`, `missions/qgroundcontrol_examples` | Ejemplos de sesión e importación | `sessions/structured_mission_session.py`, `tests/conftest.py` | Vigente | Conservar |
| `missions/generated/` | Almacenes de ejecución (borradores, secuencias, locks, reservas, tareas R1) | Código operativo y del subsistema rover; ignorado por Git | Local de Joel | Conservar; ocultar |
| `deploy/` | Recetas de imágenes, Compose, scripts de prueba y plantillas de VS Code | Usuarios e inventarios | Vigente | Conservar |
| `deploy/planner/vendor/` | Tar congelado de Hermes (entrada del build) | `deploy/planner/Dockerfile` | Generado, ignorado por Git | Conservar; ocultar |
| `docs/` | Documentación vigente e histórica | Todos los `.md` tienen consumidores: otros documentos, evidencias, resultados del subsistema rover o inventarios | Mixto (ver [INDEX.md](INDEX.md) §3) | Conservar todos. Mover uno rompería enlaces de evidencias selladas |
| `docs/checkpoints/` | Checkpoints del subsistema rover | El subsistema rover | El subsistema rover | No tocar |
| `documentation/development_log.md` | Bitácora antigua | Referenciada por `docs/` | Histórico; no se sigue usando | Conservar; ocultar |
| `documentation/verification/` | Verificaciones del 18/10 | `docs/hermes-domain-evaluation.md` y otros | Histórico | Conservar |
| `.hermes/skills/tfg-mission-control` | Skill de Hermes del proyecto | Documentación de Hermes y verificaciones | Con seguimiento en Git | Conservar |
| `evaluation/observability/<vigentes>` | Evidencias principales ([INDEX.md](INDEX.md) §5) | Documentos, inventarios e imágenes | Selladas | Conservar; visibles |
| `evaluation/observability/hermes_*`, `opik_*`, `langsmith_*`, `mission_report_*`, `agri_site_fleet_export_2026_10_27` | Ensayos previos, envíos, diagnósticos y paquetes V1 superados | Documentos de observabilidad; casos del ejecutor (`hermes_capture_run.py` cita `hermes_native_usage`) | Selladas · históricas | Conservar; ocultar |
| `evaluation/hermes_conversation/`, `evaluation/hermes_native_usage_2026_10_21/` | Conversaciones e inventario CLI de Hermes antiguos | 27 y 2 referencias (documentos y ejecutor) | Histórico | Conservar; ocultar |
| `evaluation/operations/` | Operaciones del rover | El subsistema rover | El subsistema rover | No tocar |
| `simulation/ros2_gazebo/` | Scripts del simulador y resultados (incluida H2) | El subsistema rover; inventarios (H2 y capturas opcionales) | El subsistema rover | No tocar; visible |
| `constraints-verified.txt`, `requirements*.txt`, `pytest.ini` | Dependencias y pruebas | Imágenes y venvs | Vigente | Conservar |
| `.coverage`, `.pytest_cache/`, `__pycache__/` | Cachés de herramientas (`.coverage` está en Git) | pytest y coverage | Temporal de herramienta | Conservar (no es material del TFG); ocultar |
| `work/` | Resultados de los contenedores (`TFG_WORK_DIR`) | Compose | Ignorado por Git; no existe hasta crearlo | Conservar |

## Archivo físico

**No se ha movido nada.** Ninguna ruta reunía las tres condiciones: material histórico o temporal, sin dependencias comprobadas y fuera de las zonas del subsistema rover.
- **Documentos:** todos tienen consumidores.
- **Evidencias:** están selladas y documentos, inventarios o recetas las referencian.
- **Temporales:** el único fuera de cachés, `tools/rover_xrce_trace/peer-build-2026-10-24/build.log`, es del subsistema rover.

Si más adelante algo cumple esas condiciones, debe ir a una carpeta de archivo identificada, con un registro origen → destino y sus sha256.

## Pendiente para una futura imagen o inventario

Comprobado el 27/10/2026 con `agri_scenario_distribution check`. Los inventarios y las imágenes ya construidas no se han regenerado.

- **`tfg/app:2026.10.27-r2`** (inventario en `app_container_build_2026_10_27_r2`): después cambiaron `observability/hermes_capture_run.py` (caso `agri-planning-container`), `tools/agri_scenario_distribution.py` (conjunto `planner_image` y deduplicación), `deploy/compose.yaml` y `docs/student-environment.md`.
- **`tfg/planner:2026.10.27`** (inventario en `planner_container_build_2026_10_27`):
  - El subsistema rover cambió después dos módulos que entran en el cierre **estático** de imports del servidor MCP. La imagen tiene las versiones anteriores:

    | Módulo | sha256 en la imagen | sha256 en el árbol (28/10) |
    | --- | --- | --- |
    | `tools/rover_xrce_trace/historical_disposition.py` | `660fbb603f4b…` | `db882cc52391…` |
    | `tools/rover_xrce_trace/session_precheck.py` | `36686b1acdcd…` | `a3e476612e76…` |

  - **Efecto en el recorrido preparado de Hermes: ninguno.** Comprobado el 28/10:
    - importar `tools.hermes_mcp_server` no carga ninguno de los dos, ni en el anfitrión ni en la imagen;
    - `historical_disposition` solo se importa dentro del camino start/restart del simulador de `simulation_lifecycle.py`, y `session_precheck` solo desde `rover_xrce_trace`;
    - ninguno está en el camino de `update_mission_draft` ni de `finalize_mission_draft`.
  - **Efecto en las comprobaciones de fuentes: ninguno.**
    - no están entre los 5 pines del caso `agri-planning-container`, que siguen coincidiendo;
    - tampoco entre las fuentes del servidor que registra el ejecutor (`TRIAL_SERVER_SOURCES`);
    - la verificación de fuentes de Hermes se refiere a su checkout.

    Solo cambian el inventario (`CHANGED`) y la copia operativa dentro de la imagen. Que una futura imagen los incorpore no exige reconstruir ni cambiar pines ahora.
  - También cambiaron `docs/student-environment.md` y `docs/planning-first-real-test.md`, que no van en la imagen.
  - En ese inventario `docs/student-environment.md` figura dos veces; la herramienta ya deduplica para los siguientes.
- **Archivos nuevos** (`docs/INDEX.md`, `docs/repository-map.md` y `deploy/vscode/settings.json`): no están en ningún inventario. Ninguno hace falta dentro de las imágenes.

## Vista en VS Code

La plantilla [`deploy/vscode/settings.json`](../deploy/vscode/settings.json) oculta en el **explorador**, mediante `files.exclude`, solo directorios concretos: los marcados «ocultar» en la tabla. No oculta `tests/`, `docs/`, las evidencias principales ni nada del subsistema rover.

**Cómo usarla sin perder tu configuración:**
- **Si no tienes `.vscode/settings.json`:** `cp -n deploy/vscode/settings.json .vscode/settings.json`. `-n` no sobrescribe.
- **Si ya lo tienes:** añade las entradas de `files.exclude` de la plantilla dentro de tu bloque `files.exclude`, y las de `search.exclude` dentro de tu bloque `search.exclude` (créalo si no existe). No sustituyas tus bloques: añade claves. Si una misma clave ya está en tu configuración, decide tú qué valor conservar.
- `.vscode/` sigue ignorado por Git.

**Búsqueda.** VS Code aplica a la búsqueda también los patrones de `files.exclude`. Por eso la plantilla repite en `search.exclude` cada patrón histórico con valor `false`:
- **Históricos** (`evaluation/…`, `development_log.md` y `missions/generated`): ocultos en el explorador, pero **siguen apareciendo en las búsquedas normales**.
- **Cachés** (`__pycache__`, `.pytest_cache`, `.coverage`) **y el tar de Hermes** (`deploy/planner/vendor`): siguen excluidos también de la búsqueda.
- **`tests/` y las evidencias principales:** no se excluyen ni de la vista ni de la búsqueda.

Es el mecanismo documentado de `search.exclude` (`false` desactiva un patrón), pero **no se ha comprobado en tu VS Code**. Si alguna carpeta no aparece, el interruptor «Use Exclude Settings and Ignore Files» del panel de búsqueda las incluye igualmente.

**Herramientas.** Ocultar una carpeta en VS Code solo afecta al explorador del editor: las búsquedas y cualquier herramienta que lea el disco siguen viéndola. La orientación sobre qué consultar está en [INDEX.md](INDEX.md).
