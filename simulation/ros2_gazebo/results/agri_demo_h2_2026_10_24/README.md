# H2 de agri_demo_001: ensayo SITL de los artefactos de H1 — 24/10/2026

**Resultado: secuencia `FINISHED / PASSED`. Escenario `AERIAL_COMPLETED_GROUND_PENDING`
(`scenario_complete: false`).** Es un ensayo en Gazebo/ArduPilot SITL con el perfil `two_drones`.
No se usó hardware ni rover. Este resultado no autoriza ninguna operación posterior.

## Alcance autorizado por Joel en el chat

- Una apertura protegida del perfil `two_drones` y una única secuencia con la clave
  `agri-demo-001-h2-r01`.
- Primero `drone_01→v1` (`321ad647ab9c2af536905d541675580df20e0e7a5e9be129841c8f894166b30d`);
  después `drone_02→v2` (`079e25a302423996f168b65c8b2e03157fda0c9ad9b743fb64e8ea7b8c955472`).
- Parada protegida al terminar.
- Sin reintentos, hardware, rover, H3 ni Opik.

La declaración enviada a `start_preflight_sequence` reproduce ese alcance y queda en
`sequence/plan.json` como `OPERATOR_DECLARED_VIA_AGENT`. **No está autenticada.**

## Cronología (UTC)

| Hora | Paso | Resultado |
| --- | --- | --- |
| 12:48–12:49 | Precheck | Sin restricciones y sesión diagnóstica de Codex `CLOSED`. Codex sin procesos hijo; su última operación (parada protegida de `two_drones_rover`) terminó a las 11:03. Sin procesos de simulación en el contenedor. |
| 12:49 | `check-h2` | `READY_FOR_OPERATOR_DECISION`. Hashes, vinculación y orden correctos; la clave no estaba usada. |
| 12:49:30–12:49:50 | `simulation_lifecycle start` | `ea573287…`, `SUCCESS`, con GUI. |
| 12:50:25 | Observación visual | Joel: «se ve bien con los 2». Está en `operator_visual_observation.json`, separada del resultado. |
| 12:50:57 | Readiness | `READY`. Los dos vehículos pasaron a *Armable* en el tercer intento del checker; antes daban *Not Armable*. |
| 12:51:16 | Precheck repetido y admisión | Admisión única: secuencia `6628bc51-e232-45f5-901e-f5fdeb05c6f4`, `ACCEPTED`. |
| 12:51:28–12:55:42 | Hijo 1, `2f7db1f6…` (drone_01/v1) | `PASSED` |
| 12:55:50–12:59:50 | Hijo 2, `febf7c4f…` (drone_02/v2) | `PASSED` |
| 12:59:54 | Secuencia | `FINISHED / PASSED`. Sin restricciones y con el coordinador terminado. |
| 13:00:22–13:00:40 | `simulation_lifecycle stop` | `87afe526…`, `SUCCESS`. |

## Resultados del ejecutor (`analyze_executor_result`; todas las comprobaciones son `true`)

| Hijo | Despegue (error de altura) | WP1 (horizontal / altura) | WP2 | Regreso | Aterrizaje |
| --- | --- | --- | --- | --- | --- |
| drone_01/v1 | 0,07 m | 0,17 / 0,00 m | 0,21 / 0,03 m | 0,00 / 0,01 m | `landed=true`, `armed=false` |
| drone_02/v2 | 0,55 m | 0,39 / 0,03 m | 0,21 / 0,00 m | 0,85 / 0,03 m | `landed=true`, `armed=false` |

Las tolerancias son 1,0 m en horizontal y 0,75 m en altura. Los datos son observaciones del
ejecutor por AP_DDS, no una telemetría independiente. La velocidad no se comandó ni se midió.

**Lanzamientos registrados en esta sesión.** v1 en (−35.36326218, 149.16520691) y v2 en
(−35.36326218, 149.16526794), con la misma latitud. La diferencia es de unos 5,5 m en longitud,
con valores de precisión float32 (pasos de unos 1,4 m). Es una medición de la misma sesión,
pero no de un marco común validado.

## Resumen del escenario (`scenario_summary.json`)

- POI_A1, POI_A2, POI_B1 y POI_B2: `REACHED`.
- Regreso `CONFIRMED` y aterrizaje `MISSION_LANDING_CONFIRMED` en los dos drones.
- `R1` (rover): `BLOCKED_PENDING`, con la dependencia `MET` y `commands_sent: false`.

Los POI son datos declarados del escenario. No se capturaron imágenes ni hubo percepción agrícola.

## Observación tras la parada

Después del `stop` con `SUCCESS` y sin restricciones, el contenedor mantenía un proceso `[ruby]`
(PID 11666, estado `R`, un hilo, sin línea de órdenes, iniciado con el arranque). Es compatible
con el lanzador de la GUI `gz sim -g`; véase [simulation-lifecycle-diagnostics.md](../../../../docs/simulation-lifecycle-diagnostics.md).
Se registra como residuo observado. **No se ha terminado a mano.**

**Comprobación posterior (13:06:38 UTC, solo lectura).** Joel indicó que la ventana de Gazebo
estaba cerrada. El PID 11666 ya no existía. En el contenedor solo quedaban `bash` (PID 1) y el
daemon de `ros2` (PID 9333), que ya estaba antes del arranque. El proceso terminó solo, en algún
momento entre las 13:00:53 y las 13:06:38. No hay restricción ni concesión
(`lifecycle.json`) de lifecycle, y la sesión diagnóstica sigue `CLOSED`. El lifecycle protegido no
requiere ninguna acción adicional.

## Archivos

- `sequence/`, `child_*/` y `lifecycle_*/operation.json`: copias byte a byte de los originales
  en `missions/generated/`.
- `operator_steps/`: salidas originales de `check-h2`, `start`, readiness, admisión y `stop`.
- `manifest.json`: original, copia, bytes y SHA-256 de cada copia. Los `backend.log` del
  lifecycle se identifican solo por su hash.
- `SHA256SUMS` cubre todo salvo este README.
- Las finalizaciones de H1 y las evidencias anteriores no se han modificado.
