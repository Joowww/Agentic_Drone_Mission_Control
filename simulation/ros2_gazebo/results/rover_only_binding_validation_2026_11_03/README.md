# Validación pasiva de MotionBinding y métricas en `rover_only` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **SUCCESS**, retorno 0, 15,6 s. Lifecycle `612a3dcb…` `FINISHED`. Comando exacto, un intento |
| MotionBinding | **BLOCKED**: «odometry before: exactly one publisher from ('ros_gz_bridge', '/rover1') required» ([`motion-binding.json`](motion-binding.json), con los datos brutos conservados) |
| Métricas | RTF **0,659** según el reloj de Gazebo; el de ArduPilot da 0,658. Sin mezcla de dominios ([`metrics.stdout`](metrics.stdout)) |
| Readiness | **READY**; `prearm_check` → `Vehicle is Armable` ([`readiness.json`](readiness.json)) |
| Parada | **SUCCESS**, retorno 0. Lifecycle `0dfc7199…` `FINISHED`. Limpieza: 2 señales, `remaining: []`, sin errores ni ambiguos |
| Vehículos | Sin ARM, modo, `cmd_vel` ni navegación. El rover sigue `armed false`, `mode 0` |

- **Código probado:** `7f8cc355f`, con la corrección `578ab40a4` y sus tests.
- **Agente:** Claude, con autorización de Joel.

## Por qué MotionBinding sigue BLOCKED

Los datos brutos (`raw` en [`motion-binding.json`](motion-binding.json)) lo muestran.

- **Descubrimiento:** `complete: true` en 3 µs. Ambos publicadores ya existían.
- **Antes** del muestreo, rmw_fastrtps aún no tenía la identidad de nodo de los dos publicadores:
  - `/rover1/odometry`: GID `010feb7d5125902700000000000014030000000000000000`, nodo `_NODE_NAME_UNKNOWN_`;
  - `/ap/v3/status`: GID `010feb7d4c2576c00000000000000f030000000000000000`, nodo `_CREATED_BY_BARE_DDS_APP_`.
- **Después** del muestreo, los **mismos GID** se resuelven a `ros_gz_bridge` (`/rover1`) y `ap_v3` (`/`).
- **Segundo defecto del colector:** la espera exige que exista un publicador, pero no que su identidad de nodo esté resuelta.
- **La comprobación estricta de identidad rechazó correctamente.** No se modificó el código durante el ensayo.
- **Lo demás observado:** 5 muestras de odometría y el bridge único de `rover1`.

## Métricas por dominio de reloj

Ventana de 20 s de reloj real.

| Flujo | Dominio | Mensajes | Hz real | Hz simulado | Edad en su dominio | Edad real | Fresco |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/rover1/odometry` | Gazebo | 657 | 32,8 | 50,0 | 0,003 s | 0,003 s | sí |
| `/ap/v3/status` | ArduPilot | 26 | 1,30 | 1,98 | 0,275 s | 0,430 s | sí |
| `/ap/v3/navsat` | ArduPilot | 65 | 3,25 | 5,0 | 0,196 s | 0,312 s | sí |

- **Relojes:** `/rover1/clock` avanzó 13,171 s en 20,000 s reales; `/ap/v3/clock`, 13,168 s.
- **GPS:** fix.
- **Contenedor:** CPU 273 %, RAM 913 MiB, 136 PIDs.

## Final ([`final-state.txt`](final-state.txt), [`precheck-final.stdout`](precheck-final.stdout))

- **Reservas:** `v1`, `v2` y `v3` libres; sin lease.
- **Políticas:** `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`.
- **Contenedor:** en marcha con el mismo `StartedAt`; quedan `bash` y el `ros2-daemon`.
- **Sockets:** un `TIME_WAIT` en TCP 5780 desapareció en 65 s.
- **Comprobación previa final:** **SATISFIED**.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
