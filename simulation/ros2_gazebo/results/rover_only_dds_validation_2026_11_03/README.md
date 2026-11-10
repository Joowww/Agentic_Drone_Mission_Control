# Validación real de `rover_only` tras la corrección DDS (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **SUCCESS**, retorno 0, en 16 s. Lifecycle `23286a63…` `FINISHED` ([`start-lifecycle-artifacts/`](start-lifecycle-artifacts/operation.json)). Comando exacto, un único intento |
| Ejecución | `SIMULATED_REAL_EXECUTION` de infraestructura: Gazebo Harmonic en modo servidor y 1 ArduRover SITL |
| Readiness | **READY**, `SIMULATION HEALTHY`; `prearm_check` → `Vehicle is Armable` en el primer intento (2,0 s) ([`readiness.json`](readiness.json)) |
| MotionBinding | **BLOCKED** por un defecto del colector (ver abajo), no por la identidad |
| Parada | **SUCCESS**, retorno 0. Lifecycle `10df8836…` `FINISHED` en 13,5 s. Limpieza: 2 señales, `remaining: []`, sin errores ni ambiguos |
| Vehículos | Sin ARM, modo, `cmd_vel` ni navegación |

- **Versión probada:** rama `feature/rover-sitl-first-motion`, `5348295ec` (corrección `847e6a1d4`, tests `c334be526`).
- **Agente:** Claude, con autorización de Joel.

## DDS y ROS 2 ([`processes-running.txt`](processes-running.txt), [`sockets-running.txt`](sockets-running.txt), [`ros2-graph.txt`](ros2-graph.txt), [`publisher-info.txt`](publisher-info.txt))

- **Agente DDS:**
  - un solo `micro_ros_agent udp4 --port 2019 __ns:=/rover1`;
  - UDP 2019 ligado; el cliente DDS de ArduRover tiene destino 2019;
  - nada en 2039.
- **SITL:**
  - `ardurover --instance 2 … --sysid 3`;
  - TCP 5780 en escucha y conectado a `mavproxy`;
  - UDP 5521 y 9022 ligados.
- **Grafo ROS 2:**
  - nodos `/ap_v3`, `/rover1/ros_gz_bridge`, `/rover1/robot_state_publisher` y `/rover1/relay`;
  - `/ap/v3`: 18 topics y 6 servicios;
  - `/ap/v3/status`: 1 publicador (`ap_v3`, `/`);
  - `/rover1/odometry`: 1 publicador (`ros_gz_bridge`, `/rover1`).

## Mensajes y rendimiento ([`metrics.stdout`](metrics.stdout))

Ventana de 20 s de reloj real.

| Medida | Valor |
| --- | --- |
| RTF (avance de `/ap/v3/clock`) | **0,639**: 12,77 s simulados en 19,98 s reales |
| Comprobación cruzada por odometría | 637 mensajes, 50 Hz en tiempo simulado y 31,8 Hz en tiempo real → 0,637 |
| `/ap/v3/status` | 25 mensajes: `vehicle_type 1`, `armed false`, `mode 0`, `flying false`, `external_control true`, `failsafe []` |
| GPS (`/ap/v3/navsat`) | 63 mensajes, `status 2` (fix), -35,3632889 / 149,1652374 / 584,09 m |
| Odometría | Sellos estrictamente crecientes; antigüedad real del último mensaje: 0,05 ms |
| Contenedor | CPU 281 %, RAM 870 MiB (5,5 %), 136 PIDs |

- **Comparación con `two_drones_rover`** (0,017, el 03/11): unas **38 veces** más rápido. No es una medida equivalente: allí había tres vehículos y LiDAR GPU; aquí, un rover sin LiDAR.
- **Defecto de la herramienta de métricas:** `last_age_sim_s` no es válido. Compara el sello de Gazebo de la odometría con `/ap/v3/clock`, que usa la base de tiempo de ArduPilot (época Unix). Son bases distintas; hay que corregirlo.

## MotionBinding ([`motion-binding.stdout`](motion-binding.stdout))

- **Resultado:** `BLOCKED`: «status before: exactly one publisher from ('ap_v3', '/') required».
- **Lo que muestra el grafo** ([`publisher-info.txt`](publisher-info.txt)): exactamente un publicador `ap_v3` en `/`, con GID `01.0f.eb.7d.fd.21.33.64…`.
- **Causa:** en `tools/rover_motion_binding.py`, la espera de descubrimiento solo aguarda al publicador de odometría. La instantánea del publicador de estado se toma en ese momento, antes de descubrir el participante micro-ROS de `ap_v3`.
- **Otro defecto:** `collect()` lanza la excepción antes de devolver los datos brutos, así que no se conservaron.
- **No se modificó el código durante el ensayo.**

## Final ([`final-state.txt`](final-state.txt), [`precheck-final.stdout`](precheck-final.stdout))

- **Reservas:** `v1`, `v2` y `v3` libres; sin lease ni secuencia.
- **Políticas:** `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`.
- **Contenedor:** en marcha con el mismo `StartedAt`; quedan `bash` y el `ros2-daemon` residual.
- **Sockets:** un `TIME_WAIT` en TCP 5780 desapareció en 65 s.
- **Comprobación previa final:** **SATISFIED**.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
