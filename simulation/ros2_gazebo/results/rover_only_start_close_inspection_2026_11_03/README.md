# Inspección real del cierre protegido del arranque `8eefc494…` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Intento 1 | `inspect-start-close` → **BLOCKED**: «launch root did not start inside this operation window». Era un defecto de la comprobación, corregido antes de confiar en ella (ver abajo) ([`attempt1-inspect.stdout`](attempt1-inspect.stdout)) |
| Intento 2 | **ELIGIBLE**, `scope_sha256` = `9944d917fd6a01c3e91f7a56e5f66379b50466bc28a4d3635a1e157348b9783f` ([`attempt2-inspect.stdout`](attempt2-inspect.stdout)) |
| Efectos | Ninguno: `lifecycle.json` y la operación original son idénticos byte a byte antes y después de cada intento (`attempt*-locks-*.sha256`) |
| Cierre real | **NOT_EXECUTED** |

## Corrección entre los dos intentos

- **El defecto:** en este host WSL, convertir `start_ticks` a hora real con `btime` deriva, y la deriva no es constante.
  - PID 1: +29 min frente al `StartedAt` de Docker.
  - Lanzamiento: +13 min frente al `mtime` de su archivo de estado.
- **La sustitución:**
  - `mtime` (reloj real) de `/tmp/tfg_demo.processes.json` dentro de la ventana de la operación (`sim_processes.start` lo escribe nada más lanzar);
  - `start_ticks` de la raíz posterior a los del PID 1 del contenedor (orden en el mismo reloj monótono);
  - archivo PID de compatibilidad igual a la raíz.

## Alcance elegible

- **Raíz:** `[5737, 6448039]`, con argv exacto del perfil `rover_only` (`ros2 launch ardupilot_gz_bringup tfg_rover_only.launch.py rviz:=false gui:=false`).
- **Descendientes:** 8, todos etiquetados `TFG_SIM_PROJECT` y `TFG_SIM_PROFILE=rover_only`:
  - `gz sim -s`;
  - `robot_state_publisher`;
  - `parameter_bridge`;
  - `micro_ros_agent`;
  - `ardurover`;
  - `mavproxy`;
  - `relay`.
- **Fuera del alcance:** el `ros2-daemon` residual (PID 237, PPID 1, sin etiqueta).
- **Descartado:** ningún proceso ambiguo, agente fuera del árbol, reserva, otra guarda ni rol en el host.

## Regresión ([`regression.stdout`](regression.stdout))

**1212 passed, 2 failed, 4 skipped.**

- **`test_rover_clock_path_preparation::test_derived_closure_reader_pins…`: determinista, causada por este cambio.** El lector preparado por Codex el 31/10 para sesiones diagnósticas XRCE fija el hash de `tools/simulation_lifecycle.py`. Esa preparación queda obsoleta para un arranque diagnóstico con agente; no afecta a arranques ordinarios ni a la comprobación previa. No se ha debilitado el test.
- **`test_rover_ground_executor::test_native_service_timeout…`: intermitente y preexistente.** El mismo par de tests falló 1 de 4 veces también en `HEAD` sin el cambio.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
