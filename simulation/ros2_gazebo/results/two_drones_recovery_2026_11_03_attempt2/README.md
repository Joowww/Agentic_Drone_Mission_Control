# Arranque, readiness y parada de `two_drones` tras la recuperación: segundo intento (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **SUCCESS**, retorno 0. Lifecycle `e80a2200…` `FINISHED` en 44 s ([`start.stdout`](start.stdout), [`start-backend.log`](start-backend.log)) |
| Ejecución | `SIMULATED_REAL_EXECUTION` de infraestructura: Gazebo Harmonic en modo servidor y 2 instancias de ArduCopter SITL con AP_DDS |
| Readiness | **READY**, `SIMULATION HEALTHY` ([`readiness.json`](readiness.json)) |
| Parada | **SUCCESS**, retorno 0. Lifecycle `03cc2594…` `FINISHED` en 18,5 s. Limpieza: 3 señales, `remaining: []`, sin errores ni ambiguos ([`stop-backend.log`](stop-backend.log)) |
| Vehículos | Sin ARM, TAKEOFF, modos, misiones ni comandos. El rover no forma parte de este perfil |

- **Comando ejecutado:** exactamente `.venv/bin/python -m tools.simulation_lifecycle start --headless --profile two_drones`, sin envoltorio.
- **Agente:** Claude, con autorización explícita de Joel para un único intento.

## Antes del arranque ([`initial-state.txt`](initial-state.txt), [`precheck-before-start.stdout`](precheck-before-start.stdout))

- **Comprobación previa:** `SATISFIED`, con la disposición consumida.
- **Reservas y procesos:** sin reservas, lease ni secuencia, y sin procesos de rol en el host.
- **Host y contenedor:** arranque `fd538729…`; contenedor `0274e4fd…` `running` con solo `bash`.

## Con la simulación en marcha

- **Procesos** ([`processes-running.txt`](processes-running.txt)):
  - `gz sim -s -r … runway.sdf`;
  - 2 `arducopter`, instancias 0 y 1;
  - `micro_ros_agent udp4 2019`;
  - `parameter_bridge` y `robot_state_publisher` para `drone1` y `drone2`.
- **ROS 2** ([`ros2-topics.txt`](ros2-topics.txt), [`ros2-services.txt`](ros2-services.txt), [`ros2-nodes.txt`](ros2-nodes.txt)):
  - 18 topics y 6 servicios por vehículo bajo `/ap/v1` y `/ap/v2`;
  - nodos `/ap_v1` y `/ap_v2`;
  - sin `/ap/v3`.
- **Telemetría de solo lectura** ([`telemetry-samples.txt`](telemetry-samples.txt), [`telemetry-v1-recheck.txt`](telemetry-v1-recheck.txt)):
  - `status`: `vehicle_type 2`, `armed false`, `mode 0`, `flying false`, `failsafe []` en ambos;
  - batería: 12,6 V, 100 %;
  - `navsat`: v2 en -35,363262 / 149,165268; v1 en -35,363262 / 149,165207, a 584,19 m;
  - la primera lectura de `/ap/v1/navsat` no llegó en 15 s; la segunda, con 30 s, sí;
  - `pose/filtered` de v1 en el origen.
- **Pre-arm:** el primer intento de cada dron devolvió `Not Armable`; el segundo, `Armable`.

## Después de la parada ([`final-state.txt`](final-state.txt))

- **Reservas:** `v1`, `v2` y `v3` libres; sin lease, secuencia ni procesos de rol; ambas operaciones `FINISHED`.
- **Contenedor:** sigue `running` con el mismo `StartedAt` (`2026-11-03T09:44:02.9887145Z`). No se usó `docker stop`.
- **Proceso residual: `ros2-daemon` (PID 237)** ([`ros2-daemon.txt`](ros2-daemon.txt), [`ros2-daemon-sockets.json`](ros2-daemon-sockets.json)).
  - **Origen:** arrancó a las 10:22:53, 3 s después del inicio del lifecycle y antes de la primera consulta ROS 2 del agente. Lo crea el bucle `ros2 topic list` del backend.
  - **Por qué sigue:** está desacoplado (PPID 1) y `stop` no lo gestiona.
  - **Puertos:** 7400, 7426, 7427, 11511 y dos efímeros. Ninguno está en el alcance protegido. **No se ha tocado.**
- **Comprobación previa justo después de la parada:** `BLOCKED` por `RELEVANT_LOCAL_ENDPOINT_OCCUPIED` ([`precheck-after-stop.stdout`](precheck-after-stop.stdout)).
  - A las 10:27:25 ningún socket tocaba los puertos protegidos ([`protected-ports-after-stop.json`](protected-ports-after-stop.json)).
  - Es compatible con `TIME_WAIT` de TCP tras cerrar SITL (60 s), pero esto es una inferencia: no se observó el socket concreto.
- **Comprobación previa final:** **`SATISFIED`** ([`precheck-final.stdout`](precheck-final.stdout)).

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
