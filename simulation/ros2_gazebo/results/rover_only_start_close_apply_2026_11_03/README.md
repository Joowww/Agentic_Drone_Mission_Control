# Cierre protegido del arranque `rover_only` UNCONFIRMED `8eefc494…` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Autorización | Texto exacto de Joel ([`operator-authorization.txt`](operator-authorization.txt)). Es una declaración registrada, no una identidad autenticada |
| Reinspección | **ELIGIBLE** con el mismo `9944d917…`; el lease es idéntico byte a byte ([`pre-apply-inspect.stdout`](pre-apply-inspect.stdout), [`pre-apply-state.txt`](pre-apply-state.txt)) |
| Cierre | **SUCCESS**, retorno 0, una sola vez. Operación de cierre `b504e498…` `FINISHED` ([`close-lifecycle-artifacts/`](close-lifecycle-artifacts/operation.json)) |
| Vehículos | Sin ARM, modo ni comandos. Sin `docker stop` |

## Resultado

- **Señales del backend existente:**
  - SIGINT a la raíz `[5737, 6448039]` (`ros2 launch … tfg_rover_only.launch.py`);
  - SIGTERM a `gz sim` (5784, reasignado a PPID 1, etiquetado y observado).
- **Limpieza:** `remaining: []`, `errors: []`, `unattributed_auxiliaries: []`.
- **Inventario posterior:** `owned`, `ambiguous` y `agents` vacíos ([`cleanup-receipt.json`](close-lifecycle-artifacts/cleanup-receipt.json)).
- **Lease:** `lifecycle.json` liberado solo después del recibo. La operación original `8eefc494…` se conserva sin cambios (`f50eb99c…`).
- **Estado final** ([`final-state.txt`](final-state.txt)):
  - reservas `v1`, `v2` y `v3` libres; sin lease ni secuencia;
  - `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`;
  - contenedor en marcha con el mismo `StartedAt`; quedan `bash` y el `ros2-daemon` residual (PID 237, ajeno a esta ejecución).
- **Sockets:**
  - un `TIME_WAIT` en TCP 5780 justo después de la parada ([`sockets-immediately.txt`](sockets-immediately.txt));
  - ninguno 65 s después ([`sockets-65s.txt`](sockets-65s.txt)).
- **Comprobación previa final:** **SATISFIED** ([`precheck-final.stdout`](precheck-final.stdout)).

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
