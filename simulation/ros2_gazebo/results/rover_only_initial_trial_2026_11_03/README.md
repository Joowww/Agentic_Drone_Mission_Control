# Primer ensayo de `rover_only`: start UNCONFIRMED por timeout del backend (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **UNCONFIRMED**, retorno 1. El lifecycle `8eefc494…` agotó los 180 s del backend en `[6/6] Waiting for AP_DDS` ([`start-lifecycle-artifacts/`](start-lifecycle-artifacts/operation.json)) |
| Simulación | **En marcha bajo un lease `UNCONFIRMED`:** Gazebo, `ardurover --instance 2`, `mavproxy`, bridge, `robot_state_publisher` y agente ([`processes-after-unconfirmed.txt`](processes-after-unconfirmed.txt)) |
| Rendimiento, readiness, MotionBinding | **NOT_EXECUTED:** no se ejecutaron tras el estado incierto |
| Parada | **NOT_EXECUTED:** el lifecycle rechaza `stop` mientras exista su propia barrera `UNCONFIRMED`, y no se forzó |
| Vehículos | Sin ARM, modo, `cmd_vel` ni navegación |

- **Comando ejecutado:** exactamente `.venv/bin/python -m tools.simulation_lifecycle start --headless --profile rover_only`, una vez.
- **Agente:** Claude, con autorización de Joel.

## Causa (comprobada)

**`micro_ros_agent` escucha en UDP 2039 y ArduRover envía DDS a UDP 2019.**
- `robot.launch.py` calcula `dds_port = 2019 + 10*instance`.
- `tfg_rover_only.launch.py` fija `instance=2` para conservar la identidad y además lanza el agente con `use_dds_agent=True`.
- `dds_udp.parm` fija `DDS_UDP_PORT 2019` ([`dds-udp-sockets.txt`](dds-udp-sockets.txt): agente en local 2039; cliente de ArduRover con destino 2019).
- **Resultado:** `/ap/v3/*` nunca aparece ([`ros2-topics-after-unconfirmed.txt`](ros2-topics-after-unconfirmed.txt)), aunque `/rover1/*` (bridge de Gazebo) sí está.
- **Por qué funciona en `tfg_demo.launch.py`:** el agente lo lanza la instancia 0, en 2019, y lo comparten los tres vehículos.

**Es un error de diseño del archivo de lanzamiento nuevo, no del entorno.**

## Estado tras el ensayo ([`guards-after-unconfirmed.json`](guards-after-unconfirmed.json), [`precheck-after-unconfirmed.stdout`](precheck-after-unconfirmed.stdout))

- **Barrera:** `vehicle_locks/lifecycle.json`, `SIMULATION_LIFECYCLE` `8eefc494…` `UNCONFIRMED`. El proceso propietario (PID 200479) ya no vive; la barrera se conserva por diseño.
- **Reservas:** `v1`, `v2` y `v3` libres.
- **Políticas:** `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`.
- **Comprobación previa:** `BLOCKED`. El inventario del contenedor falla con procesos de simulación activos.
- **Contenedor:** sigue en marcha con el mismo `StartedAt`. No se usó `docker stop`.

## Reconciliación necesaria (no ejecutada)

- **Qué hay que cerrar:** el lease `UNCONFIRMED` `8eefc494…` y los procesos lanzados por esa operación.
- **Vía existente:** `tools.execution_reconciliation`, mediante `inspect_execution_reconciliation('8eefc494-6d81-42b7-ac11-c3d47bceb65d')` y después `apply_execution_reconciliation(...)` con una declaración de autorización humana.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
