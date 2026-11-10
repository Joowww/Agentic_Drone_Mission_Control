# Primer arranque de `two_drones_rover` tras la recuperación: verificación pasiva (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **SUCCESS**, retorno 0. Lifecycle `72f47371…` `FINISHED` en 87 s. Comprobación de adquisición del rover: retorno 0 ([`start-lifecycle-artifacts/`](start-lifecycle-artifacts/operation.json)) |
| Ejecución | `SIMULATED_REAL_EXECUTION` de infraestructura: Gazebo Harmonic en modo servidor, 2 ArduCopter y 1 ArduRover SITL |
| Readiness | **ERROR: timeout.** Estado `PASS` en v1, v2 y v3; pre-arm `Not Armable` en todos los intentos de los tres vehículos ([`readiness.json`](readiness.json)) |
| Parada | **SUCCESS**, retorno 0. Lifecycle `5e3b9aac…` `FINISHED` en 17,9 s. Limpieza: 4 señales, `remaining: []`, sin errores ni ambiguos |
| Vehículos | Sin ARM, TAKEOFF, cambio de modo, navegación ni misión. Sin trabajos del rover (`rover_ground_trials` no existe) |

- **Comando ejecutado:** exactamente `.venv/bin/python -m tools.simulation_lifecycle start --headless --profile two_drones_rover`, en un único intento.
- **Agente:** Claude, con autorización explícita de Joel.

## Vehículos ([`processes-running.txt`](processes-running.txt), [`ros2-topics.txt`](ros2-topics.txt), [`ros2-services.txt`](ros2-services.txt), [`ros2-nodes.txt`](ros2-nodes.txt), [`rover-identity.txt`](rover-identity.txt))

| Vehículo | Proceso SITL | ROS 2 |
| --- | --- | --- |
| drone_01 | `arducopter --instance 0` | `/ap/v1`: 18 topics, 6 servicios, nodo `/ap_v1` |
| drone_02 | `arducopter --instance 1` | `/ap/v2`: 18 topics, 6 servicios, nodo `/ap_v2` |
| rover_01 | `ardurover --instance 2` | `/ap/v3`: 18 topics, 6 servicios, nodo `/ap_v3`; `/rover1/*`: 14 topics |

**El rover en detalle:**
- **Nodos:** `/rover1/ros_gz_bridge`, `/rover1/robot_state_publisher`, `/rover1/relay` y `/rover1/tfg_rover_identity_observer`.
- **En Gazebo:** modelos `runway`, `drone1`, `drone2` y `rover1`; en las advertencias SDF el modelo es `wildthumper_with_lidar`.
- **Pose según `gz model -m rover1 -p`:** x=-0,001244, y=-3,000450, z=0,094909 m; pitch 0,009537 rad, yaw 1,566770 rad.
- **Publicadores:**
  - `/ap/v3/status`: 1, el nodo `ap_v3`;
  - `/rover1/odometry`: 1, el nodo `/rover1/ros_gz_bridge`, con `nav_msgs/Odometry`.

## Telemetría pasiva del rover

Dos muestras con unos 90 s de diferencia ([`rover-telemetry-sample-A.txt`](rover-telemetry-sample-A.txt), [`rover-telemetry-sample-B.txt`](rover-telemetry-sample-B.txt), [`rover-telemetry-analysis.json`](rover-telemetry-analysis.json)).

| Campo | Muestra A | Muestra B |
| --- | --- | --- |
| Estado (`/ap/v3/status`) | `vehicle_type 1`, `armed false`, `mode 0`, `flying false`, `external_control true`, `failsafe []` | Igual |
| Odometría Gazebo (`odom` → `base_link`) | x=-0,0012459, y=-3,0005149, z=0,0949065 m; t_sim 4,72 s | x=-0,0012461, y=-3,0005524, z=0,0949062 m; t_sim 6,22 s |
| Rumbo proyectado / inclinación | 89,7696° / 0,5466° | 89,7696° / 0,5466° |
| Twist de la odometría | 0 | 0 |
| EKF ArduRover (`/ap/v3/pose/filtered`) | Posición 0,0,0 (origen del EKF), mismo cuaternión, `frame_id base_link` | Igual |
| Geopose del EKF | -35,3632889 / 149,1652374 / 584,09 m | Igual |
| `/ap/v3/twist/filtered` | Del orden de 1e-5 | Del orden de 1e-5 |
| `/ap/v3/navsat` | Sin mensaje en 30 s | Sin mensaje en 30 s |

- **Desplazamiento entre muestras:** 3,76e-5 m. El rover permanece detenido.
- **Factor de tiempo real estimado:** **0,0167** (1,5 s simulados en 89,9 s reales). Explica que `navsat` no llegue y que el pre-arm no converja.

## Después de la parada ([`final-state.txt`](final-state.txt), [`precheck-final.stdout`](precheck-final.stdout))

- **Puertos protegidos:** ningún socket, ni justo después ni 65 s más tarde.
- **Reservas:** `v1`, `v2` y `v3` libres; sin lease, secuencia ni procesos de rol; ambas operaciones `FINISHED` con `movement_authorized false`.
- **Política:** `OPERATIONAL_ROVER_ENABLED=False`.
- **Contenedor:** sigue `running` con el mismo `StartedAt`. Solo quedan `bash` y el `ros2-daemon` residual (PID 237, el mismo de la ejecución anterior).
- **Comprobación previa final:** **`SATISFIED`**.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
