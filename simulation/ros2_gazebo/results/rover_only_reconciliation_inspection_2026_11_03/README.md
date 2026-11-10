# Inspección de reconciliación del arranque `rover_only` UNCONFIRMED `8eefc494…` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Inspección | `inspect_execution_reconciliation('8eefc494-6d81-42b7-ac11-c3d47bceb65d')`, una vez, retorno 0 → **BLOCKED** ([`inspection.stdout`](inspection.stdout), [`inspection-record.json`](inspection-record.json), `inspection_sha256` = `d0a2f13c…f003`) |
| Cambios | Solo el registro de auditoría separado `reconciliation_inspections/356d1cd5…`. `vehicle_locks/*.json` idéntico antes y después ([`locks-before.sha256`](locks-before.sha256), [`locks-after.sha256`](locks-after.sha256)) |
| Aplicación, limpieza, parada | **NOT_EXECUTED** |

- **Agente:** Claude, con autorización de Joel solo para la inspección.

## Lo observado

- **Lease** ([`identity.txt`](identity.txt)): `SIMULATION_LIFECYCLE` `8eefc494-6d81-42b7-ac11-c3d47bceb65d`, `UNCONFIRMED`, `start`/`rover_only`, iniciado a las 11:25:41 UTC.
  - Propietario PID 200479 en el arranque `fd538729…`; ya no vive (`observed: null`).
  - Ninguna reserva de vehículo.
- **Contenedor:** `0274e4fd…` `ACTIVE` con el mismo `StartedAt`.
- **Árbol de lanzamiento** ([`processes.txt`](processes.txt), [`container-state-files.txt`](container-state-files.txt)):
  - registrado por el lifecycle en `/tmp/tfg_demo.processes.json` con la identidad `[5737, 6448039]`;
  - hijos: `gz sim -s`, `robot_state_publisher`, `parameter_bridge`, `micro_ros_agent` (UDP 2039), `ardurover --instance 2`, `mavproxy` y `relay`;
  - además, el `ros2-daemon` residual (PID 237), que no pertenece a este árbol.
- **Sockets** ([`sockets.txt`](sockets.txt)):
  - TCP 5780 en escucha y conectado a `mavproxy`; 5782 y 5783 en escucha;
  - UDP 5521, 9022 y 2039;
  - ArduRover → UDP 2019 sin receptor.

## Por qué la inspección no puede pasar a aplicable

- **Base `ACTIVE_TELEMETRY_AND_GROUND`:** `telemetry_reasons` exige al menos 3 muestras de `v1` y `v2`, y la aplicación exige confirmaciones en tierra exactamente de `{v1, v2}`. El procedimiento está pensado para vuelos de drones; con `rover_only` no existen.
- **Base `ENVIRONMENT_TERMINATED`:** requiere el contenedor parado (`docker stop`, no autorizado). Además, otra ejecución del contenedor en el mismo arranque del host no la admite ningún protocolo de sucesión: dejaría la comprobación previa bloqueada.
- **Efecto de una aplicación:** en ambos casos solo se elimina `lifecycle.json`. No detiene Gazebo ni ArduRover.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
