# Validación pasiva del worker ROS 2 host-contenedor en `rover_only` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Modo pasivo | `db206cbdf`: el modo lo fija el hello. En `PASSIVE` no se crea publicador `cmd_vel` ni clientes de `mode_switch`/`arm_motors`, `exchange` se rechaza sin tocar ROS y EOF/watchdog/errores no realizan acciones de control. Tests: **93 passed** ([`offline-tests.stdout`](offline-tests.stdout)) |
| Arranque | **SUCCESS**, retorno 0, 17,3 s. Lifecycle `44a7c57e…`. Comando exacto, un intento |
| Readiness | **READY**; `prearm_check` → `Vehicle is Armable` ([`readiness.json`](readiness.json)) |
| MotionBinding nuevo | **ACCREDITED_FOR_SESSION** para `44a7c57e…`; `require_current` superado; descubrimiento en 0,20 s ([`passive-session.json`](passive-session.json) → `binding`) |
| Sesión pasiva | **PASSIVE_SESSION_COMPLETED**: hello `PASSIVE`, probe, 3 observes y close confirmado con salida del proceso |
| Comandos al rover | **Ninguno** (ver abajo) |
| Parada | **SUCCESS**, retorno 0. Lifecycle `eeddbb1b…`. Limpieza: 2 señales, `remaining: []` |

- **Código:** rama `feature/rover-sitl-first-motion` en `bf0e241d1`.
- **Agente:** Claude, con autorización de Joel solo para observación pasiva.

## Identidades ROS 2

| Publicador | Nodo | GID |
| --- | --- | --- |
| Odometría (`/rover1/odometry`) | `/rover1/ros_gz_bridge` | `010feb7d082bf5a100000000000014030000000000000000` |
| Estado (`/ap/v3/status`) | `ap_v3` (`/`) | `010feb7d032bfcef0000000000000f030000000000000000` |

**Probe del worker** (coincide con el contrato de `Ros2RoverAdapter`):
- tipos `ardupilot_msgs/msg/Status`, `nav_msgs/msg/Odometry`, `ardupilot_msgs/srv/ModeSwitch` y `geometry_msgs/msg/TwistStamped`;
- `mode_available` y `disarm_available` en `true`, por presencia en el grafo y sin clientes;
- 1 suscriptor de `cmd_vel` (`ap_v3`), 1 publicador de estado y el GID de odometría acreditado;
- `session_id` = lifecycle; `transport` = `PIPE_WORKER_V1`.

## Observaciones reales (3)

- **Estado:** sellos crecientes en el dominio de ArduPilot (época Unix); `mode 0`, `armed false`, `failsafe []`.
- **Odometría:** sellos crecientes en tiempo simulado de Gazebo (46,42 → 47,14 s); `odom → base_link`; posición (−0,0; −3,0; 0,0958); covarianzas de 36 elementos.
- **GID:** en las tres, iguales a los del binding.
- **Tiempo de recepción:** el monotónico del host al llegar la respuesta (`HOST_MONOTONIC_AT_REPLY`).

## Ausencia de comandos ([`ros2-before-session.txt`](ros2-before-session.txt), [`passive-session.json`](passive-session.json) → `graph_during_session`, [`ros2-after-session.txt`](ros2-after-session.txt))

- **`/ap/v3/cmd_vel`:** 0 publicadores antes, durante y después.
- **Nodo `/tfg_rover_pipe_worker` durante la sesión:**
  - suscriptores: solo `/ap/v3/status` y `/rover1/odometry`;
  - publicadores: solo `/parameter_events` y `/rosout`;
  - **ningún cliente de servicio**.
- **El rover:** `armed false`, `mode 0` antes y después.
- **El worker:** el nodo desaparece del grafo tras el cierre, sin procesos restantes; stderr vacío ([`worker.stderr`](worker.stderr)).
- **El host:** no envió ninguna petición `exchange`.

## Final ([`final-state.txt`](final-state.txt), [`precheck-final.stdout`](precheck-final.stdout))

- **Reservas:** `v1`, `v2` y `v3` libres; sin lease.
- **Políticas:** `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`.
- **Contenedor:** el mismo, con `bash` y el `ros2-daemon`.
- **Sockets:** un `TIME_WAIT` en TCP 5780 desapareció en 65 s.
- **Comprobación previa final:** **SATISFIED**.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
