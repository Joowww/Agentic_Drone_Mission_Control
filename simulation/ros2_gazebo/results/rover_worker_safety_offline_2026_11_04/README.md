# Seguridad del worker, presupuesto temporal, frescura derivada y flujo dron → rover (04/11/2026, OFFLINE)

**Tipo: OFFLINE_ONLY / SINTÉTICO.**
- Sin Gazebo, sin SITL, sin Docker y sin armar ni mover nada.
- Sin cambios de políticas (`OPERATIONAL_ROVER_ENABLED=False`, `SITL_TRIAL_POLICY_ENABLED=False`) ni de reservas ([`state.txt`](state.txt)).
- **Agente:** Claude.
- **Base de código:** [`code-base-commit.txt`](code-base-commit.txt), tras los commits de código `92e6803b4`, `9d0c99a67`, `f91b47561`, `0ba024874` y `e7846ce03`.

## Contenido

| Archivo | Qué es |
| --- | --- |
| [`targeted-tests.stdout`](targeted-tests.stdout) | Pruebas nuevas y afectadas de esta sesión, con su resultado |
| [`regression.stdout`](regression.stdout) | Regresión `tests/test_rover_*.py` + `tests/test_agri_*.py`, secuencial y con `nice` |
| [`control-timing-by-rtf.json`](control-timing-by-rtf.json) | `control_timing` para cadencias SINTÉTICAS de RTF 1,0 a 0,3, con estado a 2 Hz simulados |
| [`agri-red-card-example/`](agri-red-card-example/) y [`.stdout`](agri-red-card-example.stdout) | Ejecución del ejemplo `python -m tools.agri_observation_task example`: entrada, validación, propuesta, preparaciones, petición, decisión y su propio `SHA256SUMS` |

## Resultados

**Pruebas nuevas y afectadas** ([`targeted-tests.stdout`](targeted-tests.stdout), después de `807aa1269`): **298 passed, 1 xfailed** (el conocido de `NativeRos2Session._exchange`).

**Regresión ampliada** ([`regression.stdout`](regression.stdout), antes de `807aa1269`): `tests/test_rover_*.py` + `tests/test_agri_*.py`, **2252 passed, 4 skipped, 1 xfailed y 7 failed**.

| Fallo | Clase |
| --- | --- |
| `test_rover_clock_path_preparation` (1) | Conocido: pines diagnósticos sellados de Codex |
| `test_rover_passive_odometry_fields` (5) | Ambiental: diarios ignorados por Git en el disco |
| `test_agri_scenario_flow::test_app_image_set_is_the_import_closure_and_matches_the_build_allowlist` (1) | **Regresión del 03/11** (`076a56798`), no vista entonces porque aquella regresión solo cubría `test_rover_*` |

La última se corrigió en `807aa1269`: allowlists regeneradas con la herramienta. `test_agri_scenario_flow.py` pasa entero en `targeted-tests.stdout`.

**Ejemplo agrícola** (retorno 0): `DECISION: ROVER_TASK_PENDING_AUTHORIZATION · movement_authorized: False`, objetivo (1,0; 0,0) en `odom`, `NOT_ELIGIBLE` con el adaptador real (`operational_rover_policy_enabled`).

**Rango viable de `control_timing`:** RTF ≥ 0,53 con estado a 2 Hz simulados.

Detalle técnico:
- [`docs/rover-first-navigation-sitl.md` §7](../../../../docs/rover-first-navigation-sitl.md);
- [`docs/agri-observation-to-rover-task.md`](../../../../docs/agri-observation-to-rover-task.md).

Revisión pendiente: [`documentation/codex_review_rover_2026_11_04.md`](../../../../documentation/codex_review_rover_2026_11_04.md).

## Límites

- Los procesos worker de las pruebas ejecutan el `main()` real, pero con un backend con guion: no hay ROS.
- `IPC_RESERVE_S` (0,25 s) es una suposición.
- Las cadencias y el rover son dobles.
- **Nada de esto acredita aptitud para mover el rover.**

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
