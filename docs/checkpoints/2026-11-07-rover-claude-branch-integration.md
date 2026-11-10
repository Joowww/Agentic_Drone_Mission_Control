# Rover Agent ↔ executor v2 y preparación de ramas — 07/11/2026

## Base, revisión y seguridad

Branch de desarrollo `feature/rover-sitl-first-motion`, HEAD `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1`. Los cambios previos y los de esta integración siguen en el worktree, sin staging ni commit. Gate `PASSIVE_SCOPE_POLICY_ENABLED=False`.

Claude fue probado desde el snapshot fijo `8fed7dc39770c70eb599c9e41d17c9ede7bb52e8`; sus hashes de `codex_v2_bridge.py`, `rover_executor_bridge.py`, `human_authorization.py` y `frames2d.py` están fijados en los tests. El worktree de Claude está actualmente en `1d3f954ed7b74540db23cbde0e722aecb239a043`; no se importó su HEAD móvil ni se modificó ese worktree.

## V2 y `bridge_scope_sha256`

Semántica elegida: el campo sigue opcional en `/2`. El adapter fuente Claude calcula el digest del scope sobre su request canónico `{plan, vehicle_id, proposal_sha256}`; Codex no puede recalcular ese digest solo desde el payload porque no recibe el request original. La cadena local valida el formato SHA-256 lowercase y añade el valor presente al `authorization_scope_sha256` de Codex, junto con plan/vehículo. Así un cambio exige un nuevo receipt de scope. La ausencia conserva exactamente el digest histórico de autorización `/2`. El JSON Schema acepta el campo opcional; ni schema ni declaración del caller acreditan autorización humana.

## Entrada al executor

Nueva ruta `tools/rover_payload_executor_adapter.py`:

`Payload v2 → rover_mission_payload.validate → comprobación de evidencia de localización → transformación site→odom en Codex → ROVER_NAVIGATE_V1 interno → rover_ground_executor._request → admit_ground_trial`.

El adaptador no ejecuta ni crea otro controlador. El proveedor offline solo aporta identidad, boots y localización fresca idéntica a la ya vinculada al payload; sus coordenadas pretransformadas se rechazan. Codex invierte una vez la transformación declarada en el payload y conserva objetivo original/site y objetivo rover con frames, procedencia y hash. `_request()` real valida límites/tipos. Se ejercita `admit_ground_trial()` real con el gate cerrado: devuelve `BLOCKED / OPERATIONAL_ROVER_POLICY_DISABLED`. La admisión y la ejecución siguen separadas: `READY_TO_SUBMIT` es propuesta validada, `REQUEST_VALID` es una solicitud interna válida y la presentación a admisión es una llamada aparte. La ruta solo acepta `OFFLINE_TEST`; `OPERATIONAL` devuelve `OPERATIONAL_RUNTIME_NOT_WIRED`.

No hay proveedor operativo de localización, autorización ni telemetría. El modo `OPERATIONAL` se rechaza con `OPERATIONAL_RUNTIME_NOT_WIRED`; por tanto, el adaptador no presenta solicitudes en modo operativo ni acredita autorización.

## Site → rover

El propietario es el adaptador de entrada de Codex antes de `_request`, sin cambiar el plan site-frame de Claude. El proveedor entrega solo la evidencia de localización que debe coincidir exactamente con la ya ligada al payload. Codex aplica la inversa de la transformación validada site→odom una vez; rechaza endpoints incompatibles, incertidumbre excesiva, objetivos fuera de límite y cualquier salida pretransformada. No importa ni depende en runtime de `frames2d.py` del worktree de Claude. El test usa `TEST_FIXTURE`; modo operativo se rechaza porque no existe proveedor operativo. Sin evidencia de localización coincidente, el handoff se bloquea.

## Pruebas conjuntas

`tests/test_rover_payload_executor_adapter.py` conecta el payload del bridge fijado con el validador v2 local, la transformación de Codex, `_request()` y `admit_ground_trial()` del executor real. El replay histórico M4c-r1 queda rechazado por sus datos/restricciones reales. La propuesta sintética completa llega a `REQUEST_VALID`, luego a `BLOCKED / OPERATIONAL_ROVER_POLICY_DISABLED`; cero comandos y movimiento falso.

Casos fail-closed probados en los contratos focalizados: scope/plan distinto, bridge hash alterado/malformado, vehículo distinto, autorización ausente/caducada/revocada, localización ausente/caducada, transformación caducada, proveedor transformado en frame incorrecto, dependencia no satisfecha, STOP incierto, gate cerrado y provider/telemetría operativos ausentes, fixture presentado en modo operativo. Los fixtures no son evidencia operativa.

El grupo focalizado de payload/bridge/executor pasó 32 tests; el grupo autorización/STOP/reader-pin/adaptador pasó 41 tests. La última suite amplia ejecutada en esta iteración pasó **2429 tests, 4 skips y 0 fallos** en 551.71 s. Los providers son fixtures y no prueban ROS ni parada real.

## Preparación de ramas (lectura Git)

Todas las refs listadas parten de `main` `6e78668d962fd9dec86e3fbda9ebd6b80858b397`; diferencias de árbol aproximadas en paths frente a `main`:

| Rama | HEAD | commits sobre main | paths | Función comprobada en árbol |
|---|---|---:|---:|---|
| `feature/hermes-integration` | `83a147dda9065c812e0ff3b931cb22948fe52346` | 40 | 1057 | Hermes/MCP, observabilidad y flujo de misión; rama contiene extensa simulación/evidencia heredada |
| `feature/natural-language-qgc-plan` | `da70f5f07ac95e20d3da67926e7c681706d029b7` | 1 | 5 | `main.py`, sesión estructurada, entrada QGC `.plan`, exportador y test |
| `feature/ardupilot-ros2` | `7e8855f6a288dd5c5354b7201329b561da89f024` | 2 | 16 | launch ROS2/Gazebo, scripts multi-vehículo e informes históricos |
| `feature/rover-sitl-first-motion` | `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1` | 141 | 3534 | contratos, executor, lifecycle, scopes, recuperación, reader pins y evidencias Rover |
| `feature/multiagent-opik-evaluation` | `1d3f954ed7b74540db23cbde0e722aecb239a043` | 280 | 4415 | Claude multiagente, evaluación Opik y M4c-r1; comparte 3461 paths cambiados con Rover. Tests contractuales fijados aparte al snapshot `8fed7dc39770c70eb599c9e41d17c9ede7bb52e8` |
| `main` | `6e78668d962fd9dec86e3fbda9ebd6b80858b397` | — | — | línea base común disponible |

Overlap que exige integración por commits revisados: Hermes ↔ ArduPilot comparten 11 paths del simulador; Hermes ↔ natural-QGC comparten 5 paths; Rover ↔ Opik comparten 3461 paths. Los diffs de `feature/hermes-integration` y `feature/rover-sitl-first-motion` contienen muchos resultados históricos/sellados; no aplicar sus árboles completos de una vez.

El tag anotado `sim-v0.1-working` sí existe localmente. Su tag object apunta al commit `78d0d3c7030e55184120124890eb98a079c0f890`, cuyo padre es `main`; no se recreó. La falta previa se debió a buscar solo ramas, no tags.

### Ensayo aislado de merges (solo commits confirmados)

- `main + natural-QGC + Hermes`: merge limpio. Añadir ArduPilot después de Hermes produce conflictos en `README_SIMULATION.md`, `tfg_demo_2drones.launch.py`, `check_sim.sh`, `run_demo.sh`, `start_sim.sh` y `stop_sim.sh`.
- `main + Rover` (HEAD confirmado, sin cambios protegidos): merge limpio. Añadir Opik produce conflicto en `docs/INDEX.md`.
- `main + Hermes + Opik`: merge limpio; `main + ArduPilot`: merge limpio.
- Ensayos realizados en clon/copia temporal aislada. Los conflictos se abortaron allí; no se alteraron refs originales, main ni worktrees compartidos.
- Pruebas seleccionadas: QGC exporter 2 passed; Hermes+Opik 168 passed; Rover payload/agent/control 81 passed; QGC adapter 4 passed. Bash syntax checks de los cuatro scripts ArduPilot y AST parsing de los launch files pasaron. Los scripts no se ejecutaron.

Se creó un worktree nuevo y limpio `/tmp/tfg-integration-candidate` en rama `codex/tfg-integration-candidate`, basado exactamente en `main`. No contiene cambios protegidos y no altera los worktrees de desarrollo. No se hizo merge.

### Orden de integración propuesto

1. Revisar/integrar el commit pequeño natural-QGC sobre `main`; correr sus cinco tests y toda la batería exporter/session.
2. Reconciliar Hermes/MCP sobre esa base, eligiendo commits funcionales y excluyendo evidencia sellada/builds; pruebas de import/entrypoint y MCP.
3. Incorporar el baseline ROS2/Gazebo solo como código; revisar primero los 11 solapamientos y retirar del procedimiento cualquier runner con ARM/GUIDED/movimiento. Bash/launch static checks.
4. Incorporar Rover desde sucesores protegidos aprobados, nunca su dirty worktree; validar pins, schema, lifecycle/exclusión, STOP y suites offline antes de revisión operativa.
5. Incorporar Opik/multiagent desde commits pequeños sobre la base integrada; conservar M4c-r1 como evidencia inmutable. Revalidar `main.py`, Hermes, graph/agents, providers y contratos v2.
6. Publicar solo después de revisión humana; no push/merge en esta preparación.

## Camino a Gazebo y estado

La configuración histórica ArduRover está en `feature/ardupilot-ros2` y tag `sim-v0.1-working`, con `/ap/v3`. El perfil actual `rover_only` está definido por `tools/simulation_profiles.py`; arranque/parada pasan por `simulation_lifecycle.py`. Antes de sesión faltan promoción del paquete y reader successor, provider real de aprobación/revocación, providers frescos de MotionBinding/telemetría/parámetros/captura, inventario actual y precheck `SATISFIED`. Estacionariedad requiere 100 muestras y análisis del mismo binding/GIDs; parámetros solo lectura. STOP es por owner/lifecycle y puede ser `UNCONFIRMED`.

Antes del primer metro faltan sesión pasiva real, failsafe autorizado y medido, objetivo limitado y una autorización física distinta. Ninguno de los resultados offline da GO.
