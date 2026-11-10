# Preparación de la integración del TFG: lado multiagente (07/11/2026)

**Para el subsistema rover**, que prepara el worktree candidato (`codex/tfg-integration-candidate`). Este documento no crea otra rama candidata, no fusiona nada y no toca `main`.

Las relaciones de git son de hoy (`rev-parse`, `merge-base`, `rev-list`). Las comprobaciones repetidas en otra fecha no heredan este resultado.

## 1. Relaciones de git comprobadas

| Ref | HEAD | Commits sobre `main` | Notas |
| --- | --- | ---: | --- |
| `main` | `6e78668d9` | — | Base común. `codex/tfg-integration-candidate` apunta exactamente aquí |
| `feature/multiagent-opik-evaluation` (esta rama) | ver el informe final | 285 en `e1204b4a3` | Contiene `main` |
| `feature/rover-sitl-first-motion` (subsistema rover) | `2e206f1fa` | 141 | Contiene `main` |
| `feature/hermes-integration` | `83a147dda` | — | Ancestro de **las dos** ramas de desarrollo |
| `feature/natural-language-qgc-plan` | `da70f5f07` | — | Ancestro de **las dos** ramas de desarrollo |
| `feature/ardupilot-ros2` | `7e8855f6a` | 2 | No es ancestro de ninguna de las dos (16 rutas) |

**Base común de esta rama y la del subsistema rover:** `4d92f9813`, 118 commits sobre `main` que comparten las dos. Desde esa base, el subsistema rover tiene 23 commits propios y esta rama 167 en `e1204b4a3`.

**Conflictos de archivos desde la base común:** solo `docs/INDEX.md`, que han cambiado los dos lados. Se resuelve a mano, solo añadiendo líneas. El trabajo del subsistema rover sin commitear también toca `docs/INDEX.md`.

**`feature/ardupilot-ros2`:** esta rama ya contiene 11 de sus 16 rutas, que llegaron por la historia compartida:
- 5 tienen el mismo *blob*: `VERSIONS.md`, `launch/tfg_demo.launch.py`, `results/performance_tests.md`, `results/validation_3_vehicles.md` y `tfg_demo_vs_multiagent.patch`;
- 6 difieren: `README_SIMULATION.md`, `launch/tfg_demo_2drones.launch.py` y los scripts `check_sim`, `run_demo`, `start_sim` y `stop_sim`.

Es el área de simulación del subsistema rover: decide él qué versión se queda. Sus scripts arman vehículos y los ponen en GUIDED, así que no se incorporan como procedimiento.

## 2. Inventario multiagente

Son 62 módulos en `multiagent/`, unas 12 900 líneas.

| Grupo | Módulos |
| --- | --- |
| Agentes y prompts | `orchestrator`, `interpreters`*, `prompts`*, `supervisor_prompts`, `supervisor_policy`, `brief_provenance`, `model_interpretation`*, `risk_signals`*, `availability`*, `drone_agent`, `rover_agent`, `rover_gate`, `llm_agents`, `agent_prompts`, `agent_tools`, `model_allocator`, `simulated_llm` |
| Contratos | `contracts` (*brief* `/2`), `mission_inputs` (`mission-input/1`), `plan_semantics` (`plan-semantics/1`), `rover_executor_bridge` (`rover-execution-request/1`), `human_authorization` (`human-authorization/1`), `rover_v2_bridge`, `rover_goal_contract` (`rover-goal-handoff/1`), `rover_mission_payload_bridge` |
| Coordinación | `mission_coordinator`, `deconfliction`, `swarm`, `execution_handoff`, `sitl_events`, `rover_sitl_interfaces` |
| Geometría y percepción | `frames2d`, `geometry`, `perception`, `card_detector`, `vision_image`, `synthetic_scenes`, `site_points` |
| Traspaso al subsistema rover | `rover_handoff`, `rover_handoff_fixtures`, `rover_snapshot_runner`, `integration_battery` |
| Demo y CLI | `demo`, `precision_demo`, `integrated_mission`, `scenarios`, `replay`, `integration_smoke`, `mcp_planning_server` |
| Evaluación y Opik | `evaluation`, `tracing`, `references`, `opik_*` (sin publicación desde aquí) |
| *Benchmark* | `multiagent/benchmark/*` (pilotos, comparaciones y generadores de evidencia) |

\* Congelados para `eval_v3`: no se editan.

## 3. Dependencias Python

| Paquete | Dónde | Archivo de requisitos |
| --- | --- | --- |
| `pydantic>=2,<3` | `models`, `planning`, `inputs` y contratos | `requirements.txt` |
| `langgraph` | `multiagent/orchestrator.py` y `graph/` | `requirements.txt` |
| `mcp==2.3.0` | `multiagent/mcp_planning_server.py` y `tools/hermes_mcp_server.py` | `requirements.txt` |
| `PyYAML` | `multiagent/models.py` | `requirements.txt` |
| `jsonschema` | `rover_snapshot_runner` (el validador del subsistema rover dentro del *snapshot*) | `requirements-observability.txt` y `constraints-verified.txt` (4.26.0) |
| `numpy` y `opencv-python-headless` | Solo `benchmark/detector_cmp_opencv.py` (comparación opcional) | `multiagent/benchmark/detector_cmp_requirements.txt`. **No** están en el venv compartido, y el detector principal es Python puro |
| `pytest` | Pruebas | `requirements-dev.txt` |

Un entorno de integración que quiera ejecutar el traspaso al subsistema rover necesita `jsonschema`. No hay que instalar nada en el venv compartido del subsistema rover.

## 4. Puntos de entrada

| Comando | Qué hace |
| --- | --- |
| `python -m multiagent.demo --list-scenarios`, `--scenario NAME`, `--all-scenarios` | Demo de precisión offline (17 escenarios, `--safety-policy safety/3\|safety/4`) |
| `python -m multiagent.demo --scenario red_target --rover-snapshot DIR [--rover-reviewed]` | Traspaso por el código real del subsistema rover: la ruta de prueba offline y el contrato final `ROVER_ADAPTER` |
| `python -m multiagent.demo --input-plan PLAN [--plan-manifest JSON]` | Entrada `.plan` por el importador de Hermes |
| `python -m multiagent.demo --replay DIR` | *Replay* de evidencia sellada, sin modelo |
| `python -m multiagent.demo --battery --rover-snapshot DIR [--rover-reviewed]` | Batería de 18 misiones |
| `python -m multiagent.rover_handoff --evidence NEW --snapshot DIR` | Trazas selladas del traspaso |
| `python -m multiagent.benchmark.integration_v2_evidence --out NEW --scratch DIR` | Carpeta de evidencia de la integración |
| `python -m multiagent.integration_smoke [--area A]` | *Smoke tests* de la integración (ver §7) |
| `python -m multiagent.mcp_planning_server` | Servidor MCP de planificación multiagente |
| `multiagent/benchmark/{pilot,m4_pilot,agents_pilot,experiments,run}.py` | Pilotos con LLM real. **Requieren autorización expresa**; no forman parte de ninguna verificación de integración |

## 5. Imports fuera de `multiagent/`

| Desde | Qué |
| --- | --- |
| `models` | `MissionDefinition` y `qgc_import` |
| `planning` | `site_geometry` y `deterministic_plan_parser` |
| `inputs` | El exportador y el importador QGC (Hermes) |
| `observability` | Exportación de Opik |
| `tools` | Solo `swarm.py`, que usa `tools.hermes_mission_validation` y `tools.route_flight_analysis` |

`rover_snapshot_runner.py` importa `tools.rover_*` **solo dentro del *snapshot*** del subsistema rover, en un proceso aparte (`python -I -B`), nunca desde un árbol de trabajo.

## 6. Contratos compartidos

| Contrato | Lado que lo posee | Uso |
| --- | --- | --- |
| `tfg.rover.mission-execution/2` y su esquema | El subsistema rover | Validado siempre por su código (*snapshot*); este lado no lo reimplementa |
| `ROVER_NAVIGATE_V1`, `admit_ground_trial` | El subsistema rover | Solo en la ruta de prueba offline (`MULTIAGENT_FRAMES2D`) |
| `tfg.multiagent.rover-goal-handoff/1` | Este lado, para el adaptador del subsistema rover | El objetivo queda en el marco del sitio, con la transformación `REQUIRED_NOT_APPLIED`. La convierte una sola vez `ROVER_ADAPTER` |
| `tfg.multiagent.rover-submission/1` | Este lado | Sobre `READY_TO_SUBMIT_NOT_EXECUTED`; nunca es un comando |
| `tfg.multiagent.rover-execution-request/1` y `human-authorization/1` | Este lado | El subsistema rover fija los hashes de tres módulos en `9a5de915f` (`test_rover_bridge_contract.py`, en su parche). `rover_v2_bridge.py` y `rover_executor_bridge.py` no han cambiado. `human_authorization.py` cambió en `3431e129a` de forma compatible: `check(..., mode="OFFLINE_TEST")` conserva el comportamiento anterior y `OPERATIONAL` rechaza los *fixtures*. Su prueba lee el commit fijado, así que sigue siendo válida; al re-fijarla verá el hash nuevo |
| `tfg.multiagent.mission-input/1` y `plan-semantics/1` | Este lado | Las tres entradas (lenguaje natural, `.plan` y misión estructurada) acaban en el *brief* `/2` |
| `.plan` de QGC (perfil `inputs/qgc_plan_export.py`) | Hermes | Exportador e importador sin cambios |
| Eventos SITL (`sitl_events`) | Este lado; la ingestión acreditada es del subsistema rover | Solo se ingieren *topics* `ACCREDITED_BY_INGESTION` |

## 7. *Smoke tests* de la integración

`python -m multiagent.integration_smoke` ejecuta cada área en un proceso pytest propio, conservando su código de salida real, y además comprueba la CLI y el *replay*. Resultado en esta rama:

| Área | Qué cubre |
| --- | --- |
| `hermes` | MCP, planificación y validación de Hermes, parser determinista, sesión estructurada |
| `plan_input` | Exportar e importar `.plan`, comparación, georreferencia, `mission-input/1` y `plan-semantics/1` |
| `preflight` | Secuencias de *preflight* y *preflight* virtual (procesos sustituidos por *doubles*) |
| `langgraph` | Grafo del escenario agrícola (`main.py` y `graph/`). 4 pruebas necesitan una captura REAL excluida por `.gitignore` que solo existe en el checkout del subsistema rover: aparecen como `NOT_RUN_DATA_ABSENT`, nunca como superadas. Sobre un `git archive` de HEAD con una copia de esa captura pasan 151/151 |
| `supervisor`, `drone_agent`, `rover_agent` | Los tres agentes y sus *gates* |
| `perception` | Detector, geometría y compuerta de observación |
| `coordination` | Coordinador, matriz de coordinación, eventos y *topics* SITL |
| `opik_offline` | Exportación con transportes falsos; nada se publica |
| `simulator` | Selección de vehículo simulado y *mapper* de misión, sin arrancar nada |
| `rover_bridge` | Contratos v1 y v2, traspaso, `ROVER_ADAPTER`, marcos y batería, contra los dos *snapshots* |
| `cli_replay` | Demo, escenarios, entrada `.plan` y *replay* de M4c-r1 |

Las suites propias del subsistema rover (ciclo de vida, executor, *scopes*, recuperación) no están aquí: las pasa su candidato.

## 8. Orden de integración propuesto para el lado multiagente

Se aplica sobre el candidato del subsistema rover, después de sus pasos 1–4 (natural-QGC, Hermes/MCP, ROS 2 solo como código y el rover desde sucesores aprobados):

1. **Base multiagente:** `multiagent/` sin `benchmark/results`, más `tests/test_multiagent_*`. Pasar `integration_smoke`.
2. **`docs/INDEX.md`:** fusionarlo a mano, solo añadiendo líneas.
3. **Evidencias selladas** (`multiagent/benchmark/results/*`, `multiagent/benchmark/opik_imports/*`, `docs/milestones/m4c_r1_2026-11-07/`): copiarlas tal cual, sin regenerar nada, y verificar cada `SHA256SUMS`.
4. **Re-fijar los *hashes*** que el subsistema rover tiene de este lado, cuando revise el commit que se integra.
5. **Pasar `integration_smoke`** y las suites del subsistema rover sobre el resultado. No se publica nada sin revisión humana.

## 9. Lo que hay que conservar sin cambios

- **Evidencias selladas:** las 20 carpetas de `multiagent/benchmark/results/`, `multiagent/benchmark/opik_imports/` (con el *ledger* E07) y `docs/milestones/m4c_r1_2026-11-07/`.
  - No se modifican, no se regeneran y no se mueven.
  - Hay 89 `SHA256SUMS` que verifican.
- **Módulos congelados de `eval_v3`:** `interpreters.py`, `prompts.py`, `risk_signals.py`, `availability.py` y `model_interpretation.py`.
- **Fixtures:** `multiagent/fixtures/plans/` (el `.plan` y su manifiesto ligado por sha256) y `multiagent/fixtures/ros2_like/`.

## 10. Lo que este lado necesita del subsistema rover

1. Promover a un commit su parche de revisión y `tools/rover_payload_executor_adapter.py`. Después, este lado añade la llamada al adaptador desde el *snapshot* para `ROVER_ADAPTER`.
2. Un recibo `AUTHENTICATED` real; el *ledger* de referencia solo declara.
3. Una ingestión acreditada que marque *topics* como `ACCREDITED_BY_INGESTION`. Los *topics* de pose de los drones no están confirmados en el *baseline*.
4. Decidir las 6 rutas de `simulation/ros2_gazebo` que difieren de `feature/ardupilot-ros2`.
