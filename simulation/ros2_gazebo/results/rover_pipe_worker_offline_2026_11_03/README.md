# Worker ROS 2 host-contenedor del rover: OFFLINE_TEST (03/11/2026)

| Clase | Estado |
| --- | --- |
| `OFFLINE_TEST` | Tests nuevos: **70 passed** ([`new-tests.stdout`](new-tests.stdout)) |
| Regresión rover/simulación | **2152 passed, 6 failed, 4 skipped** ([`regression.stdout`](regression.stdout)). Los 6 fallos son conocidos y ajenos a este cambio (ver abajo) |
| `SIMULATED_REAL_EXECUTION` | **NOT_EXECUTED.** Sin contenedor, ROS, SITL, ARM ni movimiento |
| Políticas | `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False` ([`defaults.json`](defaults.json)) |
| Estado operativo | `missions/generated/vehicle_locks` sin reservas ([`vehicle-locks-listing.txt`](vehicle-locks-listing.txt)) |

- **Agente:** Claude, con autorización de Joel para código y pruebas offline.

## Fallos de la regresión

- **`test_rover_clock_path_preparation::test_derived_closure_reader_pins…`:**
  - pin de `simulation_lifecycle.py` en la preparación diagnóstica sellada de Codex;
  - este cambio deja obsoletos además los pines de `rover_ground_executor.py` y `rover_ros2_adapter.py` en esa misma preparación;
  - solo afecta a sesiones diagnósticas XRCE y requiere una preparación revisada nueva.
- **Los 5 de `test_rover_passive_odometry_fields`:** recorren los `journal.jsonl` del disco y fallan con 4 archivos ignorados por Git que solo existen en este checkout. Es un fallo ambiental, presente desde la primera regresión del día.
- **`test_native_service_timeout…`:** carrera intermitente preexistente; en esta ejecución pasó.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
