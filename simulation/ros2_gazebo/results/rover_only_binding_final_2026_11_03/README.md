# Acreditación real de la odometría del rover (MotionBinding) en `rover_only` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **SUCCESS**, retorno 0, 24,6 s. Lifecycle `60e34ff7…` `FINISHED`. Comando exacto, un intento |
| MotionBinding | **ACCREDITED_FOR_SESSION**, y `require_current` superado para este lifecycle, ejecución del contenedor y arranque ([`motion-binding.json`](motion-binding.json)) |
| Readiness | **READY**; `prearm_check` → `Vehicle is Armable` ([`readiness.json`](readiness.json)) |
| Métricas | RTF **0,606** (reloj de Gazebo) / 0,609 (reloj de ArduPilot) ([`metrics.stdout`](metrics.stdout)) |
| Parada | **SUCCESS**, retorno 0. Lifecycle `d814e441…` `FINISHED`. Limpieza: 2 señales, `remaining: []`, sin errores ni ambiguos |
| Vehículos | Sin ARM, modo, `cmd_vel` ni navegación. El rover sigue `armed false`, `mode 0`, `failsafe []` |

- **Código:** `7a4183da8`, con la corrección `3cf222db9`.
- **Agente:** Claude, con autorización de Joel.
- **Equivalencia de estados:** el contrato de MotionBinding no define `VERIFIED`. `ACCREDITED_FOR_SESSION` es su equivalente, limitado a esta sesión.
- **Límite de atribución:** se atribuye al único publicador del grafo, no mensaje a mensaje.

## Evidencia acreditada

- **Descubrimiento:** completo en 1,66 s, sin cambios de GID.

  | Topic | Visto | Resuelto | Estado |
  | --- | --- | --- | --- |
  | `/rover1/odometry` | 0,31 s | 0,52 s | `RESOLVED` |
  | `/ap/v3/status` | 1,45 s | 1,66 s | `RESOLVED` |

- **Publicadores:** idénticos antes y después del muestreo.
  - Odometría: `ros_gz_bridge` en `/rover1`, GID `010feb7d14286c2b00000000000014030000000000000000`.
  - Estado: `ap_v3` en `/`, GID `010feb7d0f288b4a0000000000000f030000000000000000`.
- **Muestras:**
  - 5 muestras, todas `odom → base_link`, con sellos estrictamente crecientes (16,58 → 16,66 s simulados);
  - fin de la recogida 1,24 s después de la última recepción (límite: 2 s).
- **Gazebo:** `rover1` en (−0,0; −3,0; 0,0958) con yaw 1,5708. Error de posición 0 m y de rumbo 0 rad frente a la odometría.
- **Bridge:** un único proceso de `rover1`, cuya configuración mapea `/model/rover1/odometry` → `odometry`.
- **Binding:**
  - `odometry_publisher_gid` = `010feb7d14286c2b…`;
  - `pose_reference_frame` = `odom`;
  - `pose_reference_sha256` = `5a8580d3bc8c…`;
  - `evidence_sha256` = `10b42e723189…`.

## Métricas

Ventana de 20 s de reloj real.

| Flujo | Dominio | Mensajes | Hz real | Hz simulado | Edad en su dominio | Fresco |
| --- | --- | --- | --- | --- | --- | --- |
| Odometría | Gazebo | 550 | 27,5 | 50,0 | 0,008 s | sí |
| Estado | ArduPilot | 24 | 1,20 | 1,98 | 0,453 s | sí |

- **Contenedor:** CPU 291 %, RAM 914 MiB.

## Final ([`final-state.txt`](final-state.txt), [`precheck-final.stdout`](precheck-final.stdout))

- **Reservas:** `v1`, `v2` y `v3` libres; sin lease.
- **Políticas:** `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`.
- **Contenedor:** el mismo, con `bash` y el `ros2-daemon`.
- **Sockets:** un `TIME_WAIT` en TCP 5780 desapareció en 65 s.
- **Comprobación previa final:** **SATISFIED**.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
