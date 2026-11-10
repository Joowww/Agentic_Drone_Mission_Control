# Revisión para el subsistema rover: camino operativo del rover y primer movimiento SITL de 1 m

Preparado por el sistema multiagente el 03/11/2026 para la tarea del subsistema rover del 04/11/2026 o posterior. Rama `feature/rover-sitl-first-motion`.

**Estado de partida, comprobado por el sistema multiagente el 03/11/2026 a última hora** (no vale como estado de mañana):
- `OPERATIONAL_ROVER_ENABLED=False` y `SITL_TRIAL_POLICY_ENABLED=False`;
- reservas `v1`, `v2` y `v3` libres, sin lease ni secuencia;
- contenedor `0274e4fd…` en marcha desde `2026-11-03T09:44:02.9887145Z`, arranque del host `fd538729…`.

**El rover no se ha movido nunca.** Nada de este documento autoriza armar, mover, arrancar el simulador ni aplicar disposiciones.

**Lo que se pide:** revisar y corregir lo de abajo en tus archivos y decidir (tarea 10) si se puede pedir a Joel la autorización del primer movimiento. Cada tarea tiene un criterio de aceptación comprobable offline.

## Actualización 04/11/2026: lo que cambió en la sesión del sistema multiagente (OFFLINE)

**Commits** (rama `feature/rover-sitl-first-motion`, sin push):

| Commit | Qué |
| --- | --- |
| `92e6803b4` | Presupuesto host/worker (tarea 2) |
| `9d0c99a67` | Política propia del worker (tareas 1 y 5) |
| `f91b47561` | Límites derivados de la cadencia (tareas 4 y 7) |
| `0ba024874` | Observación del dron → tarea del rover |
| `e7846ce03` | Ejemplo reproducible |
| — | Documentación de esta sesión |

Detalle técnico: [`docs/rover-first-navigation-sitl.md` §7](../docs/rover-first-navigation-sitl.md) y [`docs/agri-observation-to-rover-task.md`](../docs/agri-observation-to-rover-task.md).

**Sin tocar:**
- `rover_control.py`, `rover_ros2_adapter.py` y los pines sellados;
- `OPERATIONAL_ROVER_ENABLED` y `SITL_TRIAL_POLICY_ENABLED`, que siguen en `False`;
- las reservas.

### Errores corregidos (pendientes de tu revisión)

| Tema | Antes | Ahora | Dónde |
| --- | --- | --- | --- |
| Timeout host/worker | El worker recibía todo `timeout_s`; la alarma rompía la sesión y no había HOLD | Un deadline por operación (`timeout_s` o el SIGALRM restante). Worker `min(0,7·T, T − 0,3)`, lectura hasta `T − 0,05`, `NOT_SENT` por debajo de 0,1 s; tras un efecto incierto, solo paradas | `tools/rover_pipe_session.py` (`call_budget`) |
| `close()` | Hasta 2 + 2 s dentro de un deadline de 2 s | 0,5 + 0,6 s | Ídem |
| Límites del worker | El ensayo no los declaraba | `worker_limits` derivados de `RoverLimits`, exactos y con `HARD_LIMITS` | `tools/rover_pipe_worker.py`, `tools/rover_first_navigation.py` |
| Host muerto o pipe perdido | Al fallar la escritura de una respuesta, el worker salía **sin** parada | `safe_stop` (`HOST_PIPE_LOST`, salida 7); también ante cualquier excepción | `rover_pipe_worker.main` |
| Llamada ROS bloqueada | El watchdog no podía ejecutarse | Un hilo monitor publica velocidad cero (solo topic, con lock) al pasar el deadline de la operación + 0,5 s | `WorkerCore.monitor_tick` |
| stdin con buffer | `select()` podía no ver una línea en el buffer de Python | Lector por fd | `LineReader` |
| `close` sin parada previa | Salía sin más | Confirma el cierre y después `safe_stop` si había movimiento posible | `main` |
| Antigüedad de 1,0 s | 0,17 s de margen sobre el periodo del estado | Se deriva de la cadencia del mismo lifecycle (1,35 s a 1,2 Hz), con tope de 1,5 s y la cota de distancia; NOT_VIABLE por debajo de RTF 0,53 | `control_timing`, `cadence_from_metrics` |
| Observación con NaN (flujo agrícola) | Excepción al calcular el digest | `OBSERVATION_NOT_SERIALIZABLE` | `tools/agri_observation_task.py` |

### Pruebas nuevas

**Regresión** `tests/test_rover_*.py` + `tests/test_agri_*.py`: **2252 passed, 4 skipped, 1 xfailed y 7 failed**.
- 6 son los conocidos: `clock_path_preparation` y 5 de `passive_odometry_fields`.
- El séptimo, la allowlist de la imagen `app`, fue una regresión del 03/11 (`076a56798`), corregida en `807aa1269`.

**Después:** las pruebas afectadas dan 298 passed y 1 xfail.

**Evidencia:** `simulation/ros2_gazebo/results/rover_worker_safety_offline_2026_11_04/`.

| Archivo | Resultado |
| --- | --- |
| `tests/test_rover_pipe_budget.py` | 23 passed. Worker real en proceso hijo, pipe real y SIGALRM real |
| `tests/test_rover_pipe_watchdog.py` | 33 passed. Incluye proceso real: host muerto, host callado, pipe perdido y ROS bloqueado |
| `tests/test_rover_first_navigation_control.py` | 21 passed. Derivación por RTF y anomalías de telemetría de extremo a extremo |
| `tests/test_rover_first_navigation_timing.py` | 9 passed. Antes eran 2 xfail; el presupuesto antiguo sigue reproduciendo el defecto |
| `tests/test_agri_observation_task.py` | 44 passed, flujo dron → rover |

### Cambios que requieren tu revisión

- **El contrato `tfg.rover.pipe/1`:** `hello` OPERATIONAL con 7 límites exactos; `timeout_s` ≤ `watchdog_s`; los códigos `TELEMETRY_STALE`, `BACKEND_ERROR` y `BACKEND_ERROR_EFFECT_UNCONFIRMED`.
- **Los valores:** `IPC_RESERVE_S = 0,25`, que es una **suposición**: mídela en SITL.
- **El tope:** `AGE_HARD_CAP_S = 1,5`.
- **La firma:** `build_trial(..., cadence=...)` ahora es obligatorio.
- **El hilo monitor:** publica desde otro hilo con `rclpy` mientras el principal está en un servicio. Revísalo con rclpy Humble.
- **El adaptador** (`rover_ros2_adapter._assert_disarm_scope`): sin reserva lanza `TypeError` en vez de un rechazo explícito. Es fail-closed pero opaco (archivo tuyo y fijado).

### Riesgos residuales

- Si se pierde ROS 2 (DDS o suscriptor de `cmd_vel`), ninguna parada del worker llega al vehículo; quedan los failsafes de ArduRover, no verificados.
- Si el cliente `docker exec` muere sin cerrar el stdin del proceso, solo queda el watchdog (3 s).
- El margen de RTF real (0,61–0,66) sobre el mínimo viable (0,53) es pequeño.
- La propuesta de visita de R1 (120 s) no cabe en los 60 s de la primera navegación (ver el documento del flujo agrícola).

### Problemas históricos que siguen pendientes

- **Tarea 3:** `NativeRos2Session._exchange`, todavía `xfail strict`.
- **Tarea 9:** los pines diagnósticos sellados, con `test_rover_clock_path_preparation` en rojo.
- **Diarios del disco:** los 5 `test_rover_passive_odometry_fields`, que dependen de diarios ignorados por Git.

### Validación SITL todavía necesaria

[`docs/rover-first-navigation-sitl.md` §4 y §7.5](../docs/rover-first-navigation-sitl.md).

**Identidad, política SITL y autorizaciones:** sin cambios de comportamiento. `policy_gate`, `max_trials = 1`, `require_current` y las autorizaciones exactas siguen igual. El ensayo añade `control_timing` y `cadence` a su contenido, sin entrar en el alcance SITL. Revisa si la cadencia debería formar parte del `scope`.

## Contexto mínimo

| Pieza | Archivo | Propietario |
| --- | --- | --- |
| Constructor y revisión en seco del ensayo de 1 m | `tools/rover_first_navigation.py` | El sistema multiagente (no protegido) |
| Executor: admisión, `policy_gate`, preparación, navegación, parada y cierre | `tools/rover_ground_executor.py` | El subsistema rover (fijado en la preparación diagnóstica sellada) |
| Núcleo de control: `prepare_guided_armed`, `navigate`, `stop`, `finalize_disarmed` | `tools/rover_control.py` | El subsistema rover |
| Adaptador ROS 2 y `NativeRos2Session` | `tools/rover_ros2_adapter.py` | El subsistema rover (protegido y fijado) |
| Sesión host del worker | `tools/rover_pipe_session.py` | El sistema multiagente, con coordinación |
| Worker en el contenedor (`tfg.rover.pipe/1`) | `tools/rover_pipe_worker.py` | El sistema multiagente, con coordinación |
| Política SITL (inactiva) | `tools/rover_sitl_trial_policy.py` | El sistema multiagente, con coordinación |

**Documentación previa:** [`docs/rover-first-navigation-sitl.md`](../docs/rover-first-navigation-sitl.md).

**Pruebas:**
- [`tests/test_rover_first_navigation.py`](../tests/test_rover_first_navigation.py): 28 passed y 1 xfail;
- [`tests/test_rover_first_navigation_timing.py`](../tests/test_rover_first_navigation_timing.py), nueva: 7 passed y 2 xfail.

**Evidencia offline:** `simulation/ros2_gazebo/results/rover_first_navigation_offline_2026_11_03/` y `…/rover_first_navigation_timing_offline_2026_11_03/`.

**Qué es real y qué no:**
- **Real (03/11):** `rover_only` READY con RTF ≈ 0,6; `MotionBinding ACCREDITED_FOR_SESSION`; worker en `PASSIVE` contra ROS 2 sin publicar nada.
- **Solo offline:** GUIDED, ARM, `cmd_vel`, HOLD y desarmado. Están probados con un doble cinemático; ArduRover no los ha recibido nunca.

## Tarea 1 — Revisar el camino operativo de comandos

**Recorrido:**

1. `admit_ground_trial`: misión, autorización exacta, `_coordination`, `policy_gate`, reserva `v3`.
2. `start_ground_trial`, con validación, readiness `rover_only` armable, `probe` y comprobación de sesión y frame.
3. `prepare_guided_armed`.
4. `navigate`.
5. `stop`.
6. `finalize_disarmed`.
7. Cierre.

**Por debajo:** `Ros2RoverAdapter` → `PipeRos2Session` → `docker exec -i` → `WorkerCore` → `RclpyBackend` → AP_DDS (`/ap/v3/mode_switch`, `/ap/v3/arm_motors`, `/ap/v3/cmd_vel`).

**Comprobar:**
- que ninguna orden distinta de la parada sale sin `motion_policy_allows_current_owner()`;
- que el worker valida de nuevo la lista exacta de comandos (`validate_command`);
- que un efecto sin respuesta queda `UNCONFIRMED` y nunca se reenvía.

**Hueco detectado:** `build_trial` **no define los límites propios del worker**: `max_linear_mps`, `max_angular_rad_s` y `watchdog_s` del `hello`.
- En las pruebas se usó `watchdog_s=10`, y con el rover a 0,3 m/s eso es demasiado.
- **Propuesta:**
  - que el ensayo los declare (`max_linear_mps=0.3`, `max_angular_rad_s=0.5`, `watchdog_s` ≤ 3 s);
  - que `pipe_adapter_factory` los reciba del ensayo y no de un valor suelto.

**Aceptación:** una prueba que construya el `hello` desde el ensayo y compruebe esos tres valores.

## Tarea 2 — Corregir el margen de timeout de `PipeRos2Session` (prioritaria) — IMPLEMENTADA el 04/11 (`92e6803b4`), pendiente de revisión

**Defecto.** `RoverControlCore._operation` envuelve cada llamada en `synchronous_deadline(timeout)`, un SIGALRM. `PipeRos2Session.observe` y `exchange` envían al worker **el mismo** `timeout_s`, y `_op_observe` espera hasta él a un par nuevo de estado y odometría. Si el estado tarda casi todo el plazo:
1. la alarma del host salta antes de que llegue la respuesta;
2. `_receive` marca la sesión `broken`;
3. `require_stop_target` se niega;
4. `stop()` **no puede enviar ni la velocidad cero ni HOLD**.

**Reproducción determinista** ([`tests/test_rover_first_navigation_timing.py`](../tests/test_rover_first_navigation_timing.py)), con estado a 1,2 Hz y un hueco de estado mayor que el plazo a mitad de navegación:
- `test_a_status_gap_mid_navigation_must_not_cost_the_host_its_hold` (`xfail strict`):
  - **hoy:** 1 alarma de host, sesión `broken`, órdenes `[GUIDED, ARM]` y ninguna más;
  - el doble queda armado en GUIDED a 0,3 m/s;
  - el modelo no incluye la parada propia del worker por EOF o watchdog ni el timeout de GUIDED de ArduRover, que en SITL serían la única parada.
- `test_worker_is_given_less_time_than_the_host_deadline` (`xfail strict`): contrato mínimo.
- `test_slow_status_in_the_stop_window_breaks_the_session_without_the_margin`: a 0,7 Hz, la primera observación de `stop()` (8 s / 6 = 1,33 s) pierde HOLD sin el margen y lo conserva con él.

**Corrección mínima propuesta:**
- en `observe` y `exchange`, y también en `probe`, enviar al worker `args.timeout_s = timeout_s × 0,7`, o `min(timeout_s × 0,7, timeout_s − 0,5)`;
- seguir recibiendo con el presupuesto completo;
- así el worker contesta `TIMEOUT_EFFECT_UNCONFIRMED` dentro del plazo del host, la sesión sigue íntegra y `stop()` puede enviar HOLD.

`test_proposed_worker_margin_restores_the_hold_after_the_same_gap` aplica exactamente eso con `monkeypatch`, solo en la prueba, y obtiene `[GUIDED, ARM, HOLD, DISARM]` y `GOAL_FAILED_CLOSURE_OBSERVED`.

**Aceptación:**
- las dos pruebas `xfail` pasan a XPASS y se les quita la marca;
- `test_proposed_worker_margin_…` sigue pasando sin `monkeypatch` (o se elimina por redundante);
- el resto de `test_rover_pipe_*` sigue verde.

**Lo que no se cambia:** el contrato de parada, cuyo resultado sigue `UNCONFIRMED` si no se observa.

## Tarea 3 — Corregir la carrera de `NativeRos2Session._exchange` (`tools/rover_ros2_adapter.py`)

**Defecto.**
- `exchange()` arma `synchronous_deadline(timeout_s)` y `_exchange()` calcula un deadline interno con el mismo `timeout_s`.
- Si la alarma se entrega después del `try` (línea 494) y antes de `future.cancel()` (línea 496), no se cancela el future local.
- El efecto sigue `UNCONFIRMED` y no hay reintento, pero una respuesta tardía queda sin consumir.

**Reproducción:** `tests/test_rover_first_navigation.py::test_native_exchange_alarm_between_loop_and_cancel_still_cancels_the_future` (`xfail strict`, determinista). `test_native_service_timeout` falla de forma intermitente por la misma causa.

**Corrección mínima:**
1. deadline interno `timeout_s − margen`;
2. cancelación en `finally` con indicador (`if not completed and not future.done(): future.cancel()`).

**Afecta al primer ensayo:** no directamente, porque el camino del worker no usa `NativeRos2Session`. El archivo está fijado (tarea 9).

**Aceptación:** XPASS → se quita `xfail`; `test_native_service_timeout` estable en 20 repeticiones.

## Tarea 4 — Revisar GUIDED + ARM (`prepare_guided_armed`)

**Comprobar:**
- **antes:** dos observaciones que avanzan, rover parado, mismas identidades y procedencia igual a `binding_sha256`;
- **GUIDED (15):** dos observaciones nuevas posteriores a la orden con `mode 15` y `external_control`;
- **ARM:** dos observaciones nuevas armado y parado;
- **armado previo:** se rechaza si ya estaba armado en otro modo;
- **pendiente:** máximo 0,2 rad (observado 0,55°).

**Solo en SITL real:**
- que ArduRover acepta GUIDED sin RC y arma con estos parámetros (`prearm_check` dio «Armable»);
- latencias reales de `mode_switch` y `arm_motors` frente a 2 s por llamada.

**Límite de antigüedad, hallazgo nuevo:** `observation_max_age_s = 1,0 s` valida juntas dos observaciones nuevas consecutivas, así que la más antigua tiene un periodo de estado de edad.
- El estado llega a unos 1,2 Hz de reloj real (2 Hz simulados con RTF 0,6), lo que da un margen de ~17 %.
- `test_one_second_age_limit_needs_a_status_at_least_every_second`: a 0,9 Hz (RTF ≈ 0,45) la preparación falla por observación caducada antes de armar. Es fail-closed, pero un descenso de RTF durante la parada dejaría la parada `UNCONFIRMED` con el rover armado en HOLD.
- **Propuesta, a elegir** (no aplicada; es un parámetro de seguridad):
  - **(a)** `observation_max_age_s = 1,5 s` en el constructor: tolera RTF ≥ ~0,35 con estado a 2 Hz simulados;
  - **(b)** exigir, en el mismo lifecycle y antes del ensayo, `rover_sim_metrics` con estado ≥ 1,1 Hz real;
  - **(c)** ambas.

## Tarea 5 — Revisar watchdog y STOP — política propia del worker IMPLEMENTADA el 04/11 (`9d0c99a67`), pendiente de revisión

- **`stop()`:** reparte `stop_timeout_s` entre seis plazos (`remaining(6)` … `remaining()`). Con el worker, la observación previa a la parada **espera un estado nuevo** con solo 1,33 s.
  - **Propuesta:** para sesiones de pipe, usar el último par verificado (`session.current()`) como estado previo, igual que el camino `observation_source`, y no esperar uno nuevo antes de enviar cero y HOLD.
  - Revisa si encaja con el contrato; no se ha cambiado.
- **Watchdog del worker:**
  - EOF, silencio del host mayor que `watchdog_s`, cambio de publicador y violación → velocidad cero + HOLD, sin declarar nunca parada confirmada;
  - comprobar en SITL que sale del contenedor cuando el host rompe la sesión: es la única parada que queda en el caso de la tarea 2.
- **Solo en SITL:**
  - que HOLD detiene el rover dentro de 8 s según la odometría;
  - el timeout de GUIDED de ArduRover para órdenes de velocidad frente al ritmo de 1–2 Hz;
  - el sobrepaso al frenar.

## Tarea 6 — Revisar la política SITL (`rover_sitl_trial_policy.py`, `policy_gate`, `sitl_current_facts`)

**Comprobar:**
- el alcance liga ejecución del contenedor, arranque del host, lifecycle, perfil, `mission_sha256`, `goal_sha256` y `binding_evidence_sha256`;
- `max_trials = 1` y el consumo del ensayo;
- otro objetivo u otra sesión producen otro alcance;
- la autorización exacta es `AUTHORIZE_ROVER_SITL_TRIAL <scope_sha256>`;
- `dry_run()` solo da `DRY_RUN_ELIGIBLE_EXCEPT_POLICY_FLAG` cuando el único motivo es `SITL_TRIAL_POLICY_DISABLED`.

**El cambio que habilite `SITL_TRIAL_POLICY_ENABLED`** es un commit aparte, solo después de esta revisión y nunca en el mismo commit que una corrección. `OPERATIONAL_ROVER_ENABLED` no se toca.

## Tarea 7 — Revisar el presupuesto temporal — límites derivados de la cadencia el 04/11 (`f91b47561`)

`test_sixty_seconds_bounds_the_navigation_phase_only_not_the_whole_trial`:

- `max_duration_s = 60 s` **solo** limita `goal.timeout_s` (45 s), en `_request` y `navigate`. Para `ROVER_NAVIGATE_V1` no hay presupuesto total como `PulseSafety.total_timeout_s` en el pulso.
- **Peor caso de reloj real:** 2 (probe) + 20 (preparación) + 45 (navegación) + 8 (parada) + 10 (desarmado) + 2 (cierre) = **87 s**. La comprobación de batería de la admisión ya usa esos 87 s.
- **Ritmo de control** (`test_effective_command_rate_follows_new_status_not_the_declared_2_hz`): cada orden espera un estado nuevo, así que el ritmo real es ≤ 1,2 Hz, no los 2 Hz declarados. Con 1 m a ≤ 0,3 m/s y RTF 0,6 el objetivo se alcanza dentro de 45 s en el doble.
- **Reserva de parada** (`test_stop_and_disarm_get_their_own_reserve_after_a_navigation_failure`): `stop` y `finalize_disarmed` empiezan plazos nuevos después de la navegación, así que el timeout de navegación no los consume.
- **Decidir:** documentar los 60 s como límite de la fase de navegación (ya corregido en `docs/rover-first-navigation-sitl.md`) o añadir un presupuesto total explícito para `ROVER_NAVIGATE_V1`.

## Tarea 8 — Revisar las pruebas que fallan

Regresión `tests/test_rover_*.py` del 03/11/2026 (salida en la evidencia de tiempos):

| Prueba | Causa conocida | Acción |
| --- | --- | --- |
| `test_rover_clock_path_preparation` | La preparación diagnóstica sellada fija `simulation_lifecycle.py`, `rover_ground_executor.py` y `rover_ros2_adapter.py`, que cambiaron con autorización | Tarea 9; no tocar el sello |
| `test_rover_passive_odometry_fields` (5) | Diarios ignorados por Git presentes en el disco | Confirmar que dependen del entorno y aislarlas |
| `test_native_service_timeout` (intermitente) | La carrera de la tarea 3 | Se resuelve con la tarea 3 |

## Tarea 9 — Preparar una revalidación legítima de los pines diagnósticos XRCE

- **El problema:** la preparación diagnóstica sellada fija los hashes de archivos que han cambiado con autorización.
  - Los cambios: el cierre protegido de un arranque fallido, `rover_only`, la preparación de navegación y la puerta SITL.
  - Por eso falla `test_rover_clock_path_preparation`.
- **No se edita el sello** ni las evidencias.
- **Se prepara una revisión nueva**, como `REVISABLE_PINS` del sucesor `ba52eb7e`:
  - lista de archivos y hashes actuales;
  - diferencias revisadas;
  - prueba offline;
  - revisión en seco;
  - autorización exacta de Joel;
  - aplicación en un directorio de evidencia nuevo.
- **Después de las tareas 2 y 3:** hay que hacerla, porque cambiarán otra vez esos archivos.

## Tarea 10 — Decidir si se puede autorizar un primer movimiento SITL de 1 m

**Criterio «listo para pedir autorización»**, todo verificable:

1. Tareas 2 y 3 aplicadas, con sus `xfail` retirados y la regresión de `test_rover_*` sin fallos nuevos.
2. Decisión tomada sobre la antigüedad máxima y el RTF (tarea 4) y sobre los límites del worker (tarea 1).
3. Pines diagnósticos revalidados (tarea 9) y `diagnostic-precheck` `SATISFIED` en el arranque y la ejecución del contenedor vigentes.
4. Commit aparte que habilita solo `SITL_TRIAL_POLICY_ENABLED`, revisado.
5. En **un único lifecycle** nuevo `rover_only`, autorizado por Joel:
   1. arranque;
   2. readiness `READY` y armable;
   3. métricas (RTF y frecuencia de estado);
   4. `MotionBinding` nuevo `ACCREDITED_FOR_SESSION`;
   5. `build_trial`;
   6. `dry_run` → `DRY_RUN_ELIGIBLE_EXCEPT_POLICY_FLAG` (antes de habilitar) o `AUTHORIZED` con la autorización exacta.
6. Joel envía en su propio mensaje:
   - `AUTHORIZE_ROVER_SITL_TRIAL <scope_sha256>`;
   - los textos de admisión, coordinación y arranque.

   Ningún agente los genera.
7. Un único ensayo en ese mismo lifecycle. Parar el simulador invalida el alcance.

**Si falta cualquiera de 1–4:** no se pide la autorización.

**Si el ensayo sale `UNCONFIRMED`:**
- la reserva se conserva;
- no se reintenta;
- no se limpia nada;
- se abre una reconciliación.

**Respuesta esperada del subsistema rover:**
- `GO` o `NO_GO`, con la lista de criterios cumplidos y pendientes;
- los commits de corrección;
- las evidencias nuevas.

## Lo que no hay que hacer

- Arrancar Gazebo o SITL, o mover el rover, sin una autorización nueva y explícita de Joel.
- Cambiar `OPERATIONAL_ROVER_ENABLED`.
- Modificar evidencias selladas, disposiciones históricas o `main`.
- Usar un worktree para operaciones de simulador o rover: `LOCK_ROOT` depende del checkout.
- Envolver comandos del lifecycle con `timeout`, `env` o `nohup`.

## Respuesta al NO_GO del subsistema rover (04/11/2026, tarde; OFFLINE)

Detalle en `docs/rover-first-navigation-sitl.md` §8–§12. Commits sobre `a9296a64f`: `f3af4cd5c`, `6873ded97`, `0fa510456`, `85d0bdcc9`, `f69764ee8` y el de esta documentación.

**Para revisar, el subsistema rover:**
1. **`GUID_TIMEOUT` como capa independiente** (`tools/rover_autopilot_failsafe.py`).
   - Los hechos salen del ArduPilot sellado.
   - La ventana derivada es (0,81 s; 1,2 s] a RTF 0,6.
   - Con el valor por defecto (3 s), `build_trial` se niega.
   - `control_timing` baja la velocidad a RTF 1,0 (de 0,25 a 0,15 m/s).
   - Revisa los supuestos: sobrevelocidad × 1,25, frenado ≤ 1 m/s² y margen de 0,25 m.
2. **Worker:** GUIDED/ARM exigen telemetría fresca y quedan cerrados tras perder la telemetría o tras una parada confirmada.
3. **Factoría:** rechazo explícito si la reserva desaparece, y ligada al scope admitido antes de crear el worker.
4. **Campo `timing` en las respuestas del worker y `timings` en la sesión.** Son diagnósticos; el control no los lee.
5. **Revisión de pines** `evaluation/operations/rover_xrce_pin_revision_2026_11_04/`:
   - revisar los 4 diffs;
   - la revisión del helper de host queda como plantilla PENDIENTE.

**Sigue NO_GO.** Ningún parámetro de ArduPilot se ha leído ni cambiado, y ninguna latencia se ha medido.
