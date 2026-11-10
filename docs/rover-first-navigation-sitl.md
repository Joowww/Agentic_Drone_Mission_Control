# Primera navegación del rover en SITL (≈ 1 m): preparación para revisión con el subsistema rover

**Estado (03/11/2026): preparado y probado OFFLINE. No ejecutado.**
**04/11/2026:** el presupuesto host/worker está corregido, el worker tiene una parada propia y los límites se derivan de la cadencia medida (§7). Todo sigue OFFLINE; el rover no se ha movido.

**Revisión posterior del subsistema rover:** [preparación pasiva y protocolo exacto](checkpoints/2026-11-04-rover-passive-session-preparation.md).
Corrige la admisión con frenada efectiva, el binding a la ejecución completa y los rechazos antes del spawn.
El lector `tools/rover_passive_parameters.py` ya está preparado y probado offline; no se ha usado en vivo.
La latencia de un sentido descrita en §11 se ha eliminado: encajar sellos no demuestra un reloj compartido.
Status y odometría se miden por separado con el sampler de suscripciones. El borrador XRCE sigue pendiente;
no bloquea directamente el perfil ordinario `rover_only`. GO solo para solicitar autorización pasiva; movimiento NO_GO.

- `OPERATIONAL_ROVER_ENABLED=False`
- `SITL_TRIAL_POLICY_ENABLED=False`

Código:

- [`tools/rover_first_navigation.py`](../tools/rover_first_navigation.py): constructor y revisión en seco.
- [`missions/examples/rover_first_navigation_sitl.json`](../missions/examples/rover_first_navigation_sitl.json): misión de validación determinista.
- [`tests/test_rover_first_navigation.py`](../tests/test_rover_first_navigation.py): pruebas.

## 1. Solicitud

`build_trial(evidence, lifecycle_id, environment_execution, host_boot_id, mission_bytes)` toma todo lo que depende de la sesión de un `MotionBinding` **vigente**. Si `require_current` falla, no construye nada.

- **Identidad:** `rover_01` / v3, perfil `rover_only`, `ROVER_NAVIGATE_V1`.
- **Objetivo** (`goal_from_start_offset`):
  - 1,0 m hacia delante desde la pose acreditada (`forward_m`), 0 m lateral;
  - rumbo final igual al de salida;
  - frame `odom`, transformación `IDENTITY_SAME_ACCREDITED_FRAME`;
  - límite `MAX_DISTANCE_M = 1,5`.
- **`RoverLimits`:**

  | Campo | Valor |
  | --- | --- |
  | Velocidad máxima | 0,3 m/s |
  | Giro máximo | 0,5 rad/s |
  | Duración máxima (`max_duration_s`) | 60 s. Acota `goal.timeout_s`, no el ensayo entero: el peor caso es 87 s (§5.4) |
  | Timeout por llamada | 2 s |
  | Timeout de parada | 8 s |
  | Edad máxima de observación | 1,0 s de base. En el ensayo se deriva de la cadencia medida en el mismo lifecycle: 1,35 s a 1,2 Hz (§7.3) |
  | Umbral de parado | 0,03 m/s y 0,03 rad/s |

- **`NavigationGoal`:**

  | Campo | Valor |
  | --- | --- |
  | Tolerancia de llegada | 0,25 m |
  | Rumbo | libre (π) |
  | Permanencia | 1 s |
  | Frecuencia de órdenes | 2 Hz |
  | Timeout | 45 s |
  | Sin progreso | 15 s, con progreso mínimo de 0,05 m o 0,05 rad |
  | Muestras máximas | 256 |

- **Preparación:** `GUIDED_ARM_AFTER_STATIONARY_V1`, 20 s.
  - Envolvente: `binding_sha256` = huella del binding, `pose_frame=odom`, pendiente máxima 0,2 rad (observada: 0,55°).
  - También va declarada en el candidato (`preparation_policy`).
- **Final:** `DISARM_AFTER_OBSERVED_STOP_V1`, 10 s.
- **Correspondencia de frames:** `candidate.frame_transform.sha256` = `binding.pose_reference_sha256`, que es lo que compara el executor. La derivación y el objetivo tienen digests propios.
- **Textos del operador:** nunca se generan. `with_operator_statements()` exige los textos de Joel literalmente y una autorización SITL que nombre **ese** alcance.

## 2. Secuencia GUIDED → ARM → navegación → parada (`prepare_guided_armed`, `navigate`, `stop`, `finalize_disarmed`)

1. Lectura actual del estado y del grafo, con dos observaciones que avanzan, el rover parado y los mismos GID.
2. Petición de GUIDED (15). Se confirma con dos observaciones nuevas en `mode 15` y `external_control`.
3. Petición de ARM. Se confirma con dos observaciones nuevas armado y parado.
4. Navegación. Cada orden exige una observación fresca, GUIDED, armado, sin failsafe, la misma identidad y frame, y progreso.
5. Parada: velocidad cero, HOLD (4) y dos observaciones posteriores en HOLD y paradas (`STATIONARY_OBSERVED`).
6. Desarmado observado (`DISARMED_STATIONARY_OBSERVED`). Solo después se libera la reserva v3.

**Si GUIDED o ARM fallan**, no hay `cmd_vel`: se intenta la parada.

**Si no se puede confirmar la parada**, el resultado es `UNCONFIRMED` y la reserva se conserva.

## 3. Condiciones para admitir y arrancar (comprobadas offline)

- **Autorizaciones humanas exactas:**
  - admisión: `mission_sha256`, `request_fingerprint` y texto;
  - coordinación: `OPERATOR_DECLARED`, con el `session_id` del lifecycle;
  - arranque;
  - `AUTHORIZE_ROVER_SITL_TRIAL <scope_sha256>`.
- **`policy_gate`:**
  - SITL ligado a misión, objetivo, perfil y preparación, y a hechos reales actuales (ejecución del contenedor, arranque del host, último start `FINISHED` del lifecycle, `require_current` del binding);
  - `max_trials = 1`: un ensayo consumido bloquea el mismo alcance;
  - otro objetivo u otra sesión producen otro alcance, y la autorización no sirve.
- **Reserva v3 viva:** el executor la exige; la sesión operativa exige autoridad al abrirse; las órdenes que no son de parada pasan por `motion_policy_allows_current_owner()`.
- **Readiness `rover_only`** con `rover_01/v3` en `PASS` y armable.
- **Capacidad de parada:** sondeo de `mode_available` y `disarm_available`, y suscriptor de `cmd_vel`.

## 4. Verificable solo en SITL real

- Que ArduRover acepta GUIDED sin RC y arma con estos parámetros (en SITL `prearm_check` dio «Armable»).
- **Ritmo de control:** `/ap/v3/status` llega a unos 1,2 Hz de reloj real con RTF ≈ 0,6. Cada observación espera un estado nuevo, así que el control efectivo será de 1–2 Hz. El timeout de GUIDED de ArduRover para órdenes de velocidad debe tolerarlo.
- Distancia real recorrida frente a la odometría y la pose de Gazebo, y sobrepaso al frenar.
- Tiempos reales de respuesta de `mode_switch` y `arm_motors` frente al timeout por llamada de 2 s (ver 5.2).
- Que HOLD detiene el rover y la odometría lo confirma dentro de `stop_timeout_s`.

## 5. Riesgos pendientes para revisión independiente (subsistema rover)

### 5.1 Carrera en `NativeRos2Session._exchange` (`tools/rover_ros2_adapter.py`, protegido y fijado)

- **El problema:** `exchange()` arma `synchronous_deadline(timeout_s)` (SIGALRM) y `_exchange()` calcula un deadline interno con **el mismo** `timeout_s`.
- **La ventana:** si el bucle termina por su deadline y la alarma se entrega después del `try` (línea 494) pero antes de `future.cancel()` (línea 496), el `TimeoutError` de la alarma salta la cancelación local.
- **Lo que se mantiene:** el efecto sigue siendo `UNCONFIRMED` (el diagnóstico lo añade `exchange()`) y no hay reintento.
- **Lo que se pierde:**
  - el future local queda vivo y una respuesta tardía no se consume;
  - el registro no indica que la cancelación local se intentó.
- **Reproducción:** determinista en `test_native_exchange_alarm_between_loop_and_cancel_still_cancels_the_future` (`xfail strict`).
- **Afecta al primer ensayo:** **no directamente**. El camino del worker usa `PipeRos2Session`, no `NativeRos2Session`.
- **Corrección mínima propuesta:**
  1. un deadline interno estrictamente menor que el de la alarma (`timeout_s - margen`);
  2. la cancelación en un `finally` con indicador (`if not completed and not future.done(): future.cancel()`), para que cualquier excepción, incluida la de la alarma, intente cancelar una sola vez.

  Al aplicarlo, el test pasará a XPASS y deberá dejar de ser `xfail`. El archivo está fijado en la preparación diagnóstica sellada; hace falta una revisión nueva.

### 5.2 Margen de timeout en el canal del worker (`tools/rover_pipe_session.py`)

- **El problema:** `RoverControlCore._operation` envuelve cada llamada en `synchronous_deadline(timeout)`. La sesión pasa al worker el mismo `timeout_s` y espera `timeout + 2 s`.
- **La consecuencia:** si ArduPilot tarda casi todo el timeout, la alarma del host llega antes que la respuesta, la sesión se rompe y la orden queda `UNCONFIRMED`. Es fail-closed pero frágil.
- **Corrección propuesta:** enviar al worker `timeout_s × 0,7` (o `timeout_s − 0,5 s`), para que el worker conteste `TIMEOUT_EFFECT_UNCONFIRMED` dentro del presupuesto del host.
- **Corregido el 04/11/2026** con un presupuesto explícito (§7.1).

### 5.3 Atribución de mensajes

Se atribuyen al único publicador observado en el grafo, no mensaje a mensaje (limitación de `rclpy` en Humble). Cada respuesta del worker revalida los GID del grafo.

### 5.4 Presupuesto temporal y ritmo (03/11/2026, offline)

Pruebas en [`tests/test_rover_first_navigation_timing.py`](../tests/test_rover_first_navigation_timing.py): 7 passed y 2 `xfail strict`. Modelan el estado a la cadencia medida en vivo (≈ 1,2 Hz real, RTF ≈ 0,6) y la alarma del host como un `TimeoutError` dentro de la lectura del pipe, con una latencia supuesta de 50 ms.

- **60 s no es un límite global.** Para `ROVER_NAVIGATE_V1` solo acota la navegación (45 s). El peor caso de reloj real es 2 + 20 + 45 + 8 + 10 + 2 = **87 s**, el mismo que ya usa la comprobación de batería de la admisión.
- **Reserva de parada:** `stop` (8 s) y el desarmado (10 s) empiezan plazos nuevos después de la navegación. Un fallo o timeout de navegación no los consume (comprobado con un rover atascado).
- **Ritmo efectivo ≤ 1,2 Hz**, no 2 Hz: cada orden espera un estado nuevo. El objetivo de 1 m se alcanza igualmente dentro de 45 s en el doble.
- **Antigüedad de 1,0 s frente al periodo del estado.**
  - Dos observaciones nuevas consecutivas se validan juntas, así que la más antigua tiene un periodo de edad.
  - Con estado a 2 Hz simulados, el límite de 1,0 s exige RTF ≳ 0,5. El margen frente al 0,6 medido es de ~17 %.
  - A 0,9 Hz la preparación falla por caducidad antes de armar (fail-closed).
  - Propuesta para el subsistema rover: subir el límite a 1,5 s, exigir métricas en el mismo lifecycle, o ambas cosas.
  - **04/11:** se aplican las dos, derivadas y con tope (§7.3).
- **Margen host/worker (amplía 5.2).**
  - Un hueco de estado mayor que el plazo de una llamada, a mitad de navegación, hace que salte la alarma del host. La sesión queda `broken` y el host **no envía ni cero ni HOLD**: en el doble, el rover queda armado en GUIDED.
  - Reproducido de forma determinista (`xfail strict`).
  - Con la corrección propuesta (worker a ×0,7, aplicada solo en la prueba), se observan HOLD y el desarmado.
  - En SITL quedarían la parada por EOF o watchdog del worker y el timeout de GUIDED de ArduRover, que no están modelados.
  - **Corregido el 04/11** (§7.1). La prueba con el presupuesto antiguo sigue reproduciendo el defecto.
- **Límites del worker:** el ensayo no declara `watchdog_s`, `max_linear_mps` ni `max_angular_rad_s` del `hello`, y las pruebas usan `watchdog_s=10`. Hay que fijarlos (≤ 3 s).
  - **04/11:** el ensayo declara `worker_limits` (§7.2).

Tarea completa para el subsistema rover: [`documentation/rover_review_2026_11_04.md`](../documentation/rover_review_2026_11_04.md).

### 5.5 Lo que el subsistema rover debe revisar

- 5.1, 5.2 y 5.4.
- La integración en `rover_ground_executor.py`: `policy_gate`, `request_profile`, `NavigationPreparationSafety` y `motion_policy_allows_current_owner`.
- La generalización de `_assert_preparation_scope`.
- La nueva preparación sellada de las sesiones diagnósticas XRCE, cuyos pines quedan obsoletos.
- El cambio que habilitaría `SITL_TRIAL_POLICY_ENABLED`, solo después de esta revisión.

## 6. Revisión en seco: requisitos y procedimiento

El alcance exige datos de una **sesión viva nueva**. El lifecycle `44a7c57e…` y su binding ya han terminado y **no** se reutilizan.

1. Joel autoriza un `start --headless --profile rover_only`.
2. Readiness `READY`.
3. `rover_motion_binding.collect()` → `ACCREDITED_FOR_SESSION` para ese lifecycle.
4. `rover_first_navigation.build_trial(...)` con esa evidencia.
5. `rover_first_navigation.dry_run(trial)` con los hechos reales. Solo es apto si el único motivo de bloqueo es `SITL_TRIAL_POLICY_DISABLED` (`DRY_RUN_ELIGIBLE_EXCEPT_POLICY_FLAG`). Da `scope_sha256` y la autorización exacta requerida.
6. Joel revisa el alcance y responde con `AUTHORIZE_ROVER_SITL_TRIAL <scope_sha256>`, más los textos de admisión, coordinación y arranque.

Habilitar la política sigue siendo un cambio de código aparte, revisado con el subsistema rover.

**Importante:** parar el simulador termina el lifecycle e invalida el alcance. El ensayo tiene que hacerse dentro del mismo lifecycle que se revisó en seco.

## 7. Sesión del 04/11/2026: canal, parada propia del worker y frescura (OFFLINE)

Commits:
- `92e6803b4`: presupuesto del canal;
- `9d0c99a67`: política propia del worker;
- `f91b47561`: límites derivados de la cadencia.

Nada de esto se ha ejecutado contra Gazebo ni SITL.

### 7.1 Presupuesto temporal host/worker (`tools/rover_pipe_session.py`)

Una operación de `T` segundos tiene **un único deadline monotónico**. `T` es `timeout_s`, o lo que quede del SIGALRM ya armado, si es menos. Ese deadline se reparte así:

| Tramo | Valor | Para qué |
| --- | --- | --- |
| Espera del worker | `min(0,7·T, T − 0,25 − 0,05)` | Su propio deadline: contesta `TIMEOUT_EFFECT_UNCONFIRMED` a tiempo |
| Reserva de IPC (`IPC_RESERVE_S`) | 0,25 s, **supuesta** | Serialización, pipe de `docker exec` en los dos sentidos, parseo. Hay que medirla en SITL |
| Guarda del host (`HOST_GUARD_S`) | 0,05 s | La alarma se arma antes de entrar en la sesión; comprobaciones posteriores |
| Lectura de la respuesta | Hasta `T − 0,05` | El host detecta la respuesta perdida él mismo, antes que la alarma |

**Valores resultantes:**
- `T` = 2 s → 1,4 s para el worker;
- `T` = 1,33 s (primera observación de la parada) → 0,93 s;
- `T` = 0,4 s → 0,1 s.

Por debajo de 0,1 s **no se envía nada** (`BudgetExhausted`, `NOT_SENT`) y la sesión sigue íntegra.

**Semántica que se conserva:**
- Un TIMEOUT nunca prueba que la orden no se ejecutó: el efecto queda `UNCONFIRMED` y no se reenvía.
- Después de un efecto incierto, la sesión **solo admite órdenes de parada**.
- Una respuesta perdida o tardía rompe la sesión. La cancelación de la petición no deshace nada.
- `close()` cabe en el deadline de 2 s del executor: 0,5 s para la confirmación y 0,6 s para la salida.

### 7.2 Política propia del worker (`tools/rover_pipe_worker.py`)

**Límites del `hello` OPERATIONAL**, exactos y con tope en `HARD_LIMITS`:
- velocidad lineal y angular;
- `watchdog_s`;
- `telemetry_max_age_s`;
- `max_session_s`;
- umbrales de parado.

El ensayo los deriva de su `RoverLimits` (`worker_limits`): 0,3 m/s, 0,5 rad/s, watchdog 3 s, 1,35 s de antigüedad, sesión de 120 s y 0,03.

**Acciones propias**, sin esperar otro mensaje del host:

| Disparador | Acción |
| --- | --- |
| EOF, host callado > `watchdog_s`, sesión > `max_session_s` | `safe_stop` |
| Violación de protocolo, segundo `hello`, excepción del backend o del worker | `safe_stop` |
| No poder escribir la respuesta (el host ya no escucha) | `safe_stop`, salida 7 |
| Hilo principal bloqueado más allá del deadline de una operación + 0,5 s | El hilo monitor publica **velocidad cero** (solo topic, bajo un lock que impide que la adelante otra orden) y bloquea el movimiento |
| `close` con movimiento posible (GUIDED, armado o en marcha, sin HOLD ni desarme después) | Confirma el cierre y después `safe_stop` |
| Telemetría propia más antigua que `telemetry_max_age_s` | Rechaza velocidades no nulas |

**`safe_stop`:**
1. velocidad cero;
2. HOLD una vez;
3. una mirada acotada (≤ 2 s) al estado y la velocidad siguientes;
4. un informe: `HOLD_AND_STOPPED_OBSERVED_BY_WORKER`, `HOLD_OBSERVED_STILL_MOVING`, `HOLD_NOT_OBSERVED` o `NO_NEW_TELEMETRY_AFTER_HOLD`.

El worker nunca declara una parada confirmada y nunca reintenta.

**El host:**
- Si el canal falla, conserva la reserva y devuelve `UNCONFIRMED`.
- Un desarmado sin respuesta deja la reserva v3 puesta.

**Riesgo residual:**
- Si se pierde ROS 2 por completo (sin DDS ni suscriptor de `cmd_vel`), nada de esto detiene el vehículo. Quedan los failsafes del propio ArduRover, no verificados.
- Que `rclpy` publique desde el hilo monitor mientras el principal está en un servicio no se ha comprobado en ROS 2 real.
- Si el cliente `docker exec` muere sin cerrar el stdin del proceso del contenedor, solo queda el watchdog.

### 7.3 Frecuencias y frescura (`control_timing`, `cadence_from_metrics` en `tools/rover_first_navigation.py`)

**Cuatro ritmos distintos:**
- estado simulado (≈ 2 Hz);
- estado real (= simulado × RTF; 1,2 Hz medido);
- órdenes pedidas (`command_hz` = 2, una cota superior);
- órdenes efectivas (≤ estado real, porque cada orden espera un par nuevo).

**`build_trial` exige la cadencia de este mismo lifecycle**: misma ejecución del contenedor y medida hace menos de 600 s en el reloj monotónico de este host. Un archivo histórico no sirve.

**Lo que se deriva:**
- **Antigüedad:** un periodo con holgura del 25 % + 0,3 s de pipe, con tope de 1,5 s y con que la distancia recorrible en ese tiempo (velocidad × RTF × antigüedad) no supere la tolerancia de 0,25 m. Si la supera, se baja la velocidad.
- **Parada:** un `stop_timeout_s` cuyo peor caso todavía observe dos estados nuevos.
- **NOT_VIABLE** si:
  - un estado nuevo no cabe en una llamada;
  - se supera el tope de antigüedad;
  - la parada no puede observarse;
  - la ventana del objetivo o de progreso es demasiado corta.

**Por RTF**, con 2 Hz simulados:

| RTF | Estado real | Velocidad | Antigüedad | Parada | Órdenes efectivas | Resultado |
| --- | --- | --- | --- | --- | --- | --- |
| 1,0 | 2,0 Hz | 0,15 m/s (antes 0,25; ver §8.3) | 0,95 s | 8 s | ≤ 2 Hz | VIABLE |
| 0,6 | 1,2 Hz | 0,15 m/s (el subsistema rover, 04/11: sin crédito por RTF bajo) | 1,35 s | 8 s | ≤ 1,2 Hz | VIABLE |
| 0,5 | 1,0 Hz | — | 1,55 s | — | ≤ 1 Hz | NOT_VIABLE (tope de antigüedad) |
| 0,4 | 0,8 Hz | — | 1,90 s | — | — | NOT_VIABLE (además, ningún estado cabe en una llamada) |
| 0,3 | 0,6 Hz | — | 2,40 s | — | — | NOT_VIABLE |

**Rango viable con estos topes: RTF ≥ 0,53** (estado real ≥ 1,06 Hz). La evidencia real que tenemos (03/11) es RTF 0,606–0,659 con estado a 1,20 Hz. El margen es pequeño, así que la cadencia se mide justo antes del ensayo.

**Comportamiento si el RTF cae durante el ensayo** (probado con dobles): falla cerrado.
- Antes de armar: no hay movimiento.
- Durante la navegación: `GOAL_FAILED` y parada.
- Si además se pierde la telemetría: HOLD enviado, parada `UNCONFIRMED`, sin desarmado y con la reserva conservada.

**Nunca** se autoriza una orden con una observación caducada.

### 7.4 Pruebas nuevas (todas OFFLINE)

| Archivo | Qué |
| --- | --- |
| `tests/test_rover_pipe_budget.py` | Presupuesto con un worker **real en un proceso hijo**, pipe real y SIGALRM real (`tests/rover_pipe_fake_worker.py`). Casos: rápido, justo antes del límite, en la reserva, tarde, perdido, EOF, worker muerto, orden ejecutada con respuesta perdida, timeouts repetidos, orden tras fallo, parada observada y no observada. El presupuesto antiguo reproduce el defecto |
| `tests/test_rover_pipe_watchdog.py` | Límites, telemetría, caducidad, watchdog en GUIDED, ARM y navegación, HOLD aceptado, rechazado o sin telemetría, monitor, segundo `hello`, `close` con movimiento, excepción del backend, cierre repetido. Con proceso real: host muerto, host callado, pipe perdido al responder y llamada ROS bloqueada. Con el executor real: desarmado observado y desarmado sin respuesta |
| `tests/test_rover_first_navigation_control.py` | Derivación por RTF y rango viable; cadencia de otro lifecycle o antigua. De extremo a extremo: RTF 1,0 y 0,6, estado irregular, un flujo caducado (estado u odometría), observación duplicada, pérdida permanente, rover que se para antes, sobrepaso, timeout con parada observada y con parada incierta |
| `tests/test_rover_first_navigation_timing.py` | Ahora comprueba la corrección; el presupuesto antiguo, parametrizado, sigue reproduciendo el defecto |

### 7.5 Solo verificable en Gazebo / SITL

- La latencia real del pipe frente a la reserva de 0,25 s.
- Las latencias de `mode_switch` y `arm_motors` frente a 1,4 s (antes 2 s).
- La publicación desde el hilo monitor con `rclpy` real.
- Que la parada propia del worker detiene de verdad el rover.
- El timeout de GUIDED de ArduRover.
- La cadencia y el RTF durante el ensayo.
- El sobrepaso real.
- Todo lo de §4.

## 8. Capa de parada independiente: `GUID_TIMEOUT` de ArduRover (04/11/2026, OFFLINE)

Responde al bloqueo NO_GO n.º 3 de la revisión del subsistema rover del 04/11 (`archivo_TFG/revision-rover-2026-11-04.9xrdqdvx/results/report.md`). Módulo: `tools/rover_autopilot_failsafe.py`. Pruebas: `tests/test_rover_autopilot_failsafe.py`.

### 8.1 Qué hace ArduRover cuando dejan de llegar órdenes (código, no suposición)

Fuente: el árbol ArduPilot `755258dbb` sellado en `evaluation/operations/rover_status_diagnostic_build_2026_10_31/…/source/ardupilot`. Según su README, es la copia de las fuentes del contenedor; **no he verificado** que el binario `ardurover` instalado se compilase exactamente de él. Las pruebas vuelven a calcular el hash de cada archivo citado y lo comparan con el `SHA256SUMS` sellado.

- `/ap/v3/cmd_vel` (TwistStamped, `base_link`) → `AP_ExternalControl_Rover` → `ModeGuided::set_desired_turn_rate_and_speed`. Submodo `TurnRateAndSpeed`; reinicia el temporizador. Solo se acepta en GUIDED y armado.
- En ese submodo, **sin consigna nueva durante `GUID_TIMEOUT`** → mensaje «target not received last X secs, stopping» y `stop_vehicle()`: acelerador a parada, dirección 0. **No cambia de modo ni desarma.**
- El reloj es `AP_HAL::millis()`: en SITL es **tiempo simulado**. `GUID_TIMEOUT × velocidad` es una distancia simulada, sea cual sea el RTF.
- `GUID_TIMEOUT`: por defecto **3,0 s**, rango 0,1–5 s.
- **Nada convierte una pérdida de DDS o del agente en un failsafe.**
  - `DDS_TIMEOUT_MS` y `DDS_MAX_RETRY` solo rigen el ping de conexión.
  - `FS_GCS_ENABLE` (por defecto 0) vigila latidos MAVLink de una GCS, no DDS.
  - `FS_THR_*` es la radio.
  - Ninguno cubre nuestro transporte.

**¿Está habilitada en nuestro perfil?** El mecanismo existe siempre en el código, pero **el valor efectivo no está acreditado**:
- Nuestros `.parm` (`rover.parm`, `rover-skid.parm`, `dds_udp.parm`, `dds_use_ns.parm`) no fijan `GUID_TIMEOUT`, `ATC_ACCEL_MAX` ni `ATC_DECEL_MAX`.
- SITL guarda `eeprom.bin` en el directorio de instancia (`use_instance_dir` True, `wipe` False). Un valor guardado antes prevalece sobre el compilado.
- Nunca se ha leído en una sesión. Hay que leerlo en vivo.

### 8.2 Escenarios A–G y capas

`runaway_envelope()` calcula el recorrido tras la última orden aceptada. Supone:
- velocidad × 1,25 (holgura de sobrevelocidad, **supuesto** a medir);
- frenado con `ATC_DECEL_MAX`, o `ATC_ACCEL_MAX` si es 0, con un crédito máximo de 1 m/s².

| Escenario | Capas que siguen actuando | Cota garantizada |
| --- | --- | --- |
| A. Pérdida host-worker | EOF → parada propia del worker; watchdog del worker; `GUID_TIMEOUT` | `GUID_TIMEOUT` |
| B. Hilo principal del worker bloqueado | cero desde el monitor (si el publicador está libre); `GUID_TIMEOUT` | `GUID_TIMEOUT` |
| C. Pérdida de DDS | solo `GUID_TIMEOUT` | `GUID_TIMEOUT` |
| D. `cmd_vel` bloqueado | solo `GUID_TIMEOUT` | `GUID_TIMEOUT` |
| E. Caída del worker | solo `GUID_TIMEOUT` | `GUID_TIMEOUT` |
| F. Sin telemetría | el worker rechaza velocidad no nula; watchdog; `GUID_TIMEOUT` | `GUID_TIMEOUT` |
| G. HOLD inaccesible | cero por topic; `GUID_TIMEOUT` | `GUID_TIMEOUT`; además, el rover queda **armado en GUIDED**, así que la reserva debe conservarse |

Las capas del worker necesitan el worker y DDS vivos. La única capa independiente de host, worker, pipe y DDS es `GUID_TIMEOUT`.

**El watchdog del worker no puede ser la cota:**
- `worker_limits` exige que no sea menor que una llamada del host (2 s).
- A 0,15 m/s eso ya son 0,39 m, por encima del margen.
- Se mantiene en 3 s como capa secundaria; acortarlo no resolvería nada.

### 8.3 Valor requerido, derivado

- **Margen de deriva:** `MAX_DISTANCE_M − (avance + tolerancia) = 1,5 − 1,25 = 0,25 m`. El host no ordena avanzar con una observación dentro de la tolerancia, y la antigüedad ya acota el avance durante esa observación.
- **Máximo:** `(0,25 − frenado) / (0,15 × 1,25) = 1,24 s` → **`GUID_TIMEOUT` ≤ 1,2 s** simulados.
- **Mínimo:** el intervalo nominal entre consignas. Es la antigüedad necesaria (1,34 s reales a 1,2 Hz) × RTF 0,6 = **0,81 s simulados**. Con un valor menor, el rover se pararía entre dos órdenes legítimas.
- **Ventana a RTF 0,6:** (0,81 s, 1,2 s]. Por ejemplo, 1,0 s.
- **Con el valor por defecto de 3,0 s:** 0,58 m de deriva en el peor caso, más del doble del margen. **Bloquea.**
- **`control_timing` baja ahora la velocidad hasta que exista esa ventana.** A RTF 1,0, 0,25 m/s ya no tenía ventana (exigía ≤ 0,6 s con un intervalo de 0,93 s), así que pasa a 0,15 m/s.

### 8.4 Qué exige ahora el ensayo

- `build_trial(…, autopilot_failsafe=…)` exige un hecho `autopilot_fact()` leído en **este** lifecycle, con la misma ejecución del contenedor y el mismo arranque:
  - `GUID_TIMEOUT`, `ATC_ACCEL_MAX`, `ATC_DECEL_MAX`, `FS_GCS_ENABLE`, `FS_ACTION` y `FS_CRASH_CHECK`;
  - leídos solo con `GetParameters` en `/ap/v3/get_parameters`.
- **Lo rechaza** si:
  - falta el hecho;
  - es de otra sesión;
  - está incompleto o fuera de rango;
  - el `GUID_TIMEOUT` cae fuera de la ventana.
- El hecho y su evaluación quedan en el scope /2.
- `policy_gate` **recalcula** la evaluación y no se fía del veredicto guardado.

### 8.5 Pendiente (no se ha hecho)

1. **Sesión PASIVA autorizada:**
   - Leer esos parámetros con `GetParameters`, solo lectura.
   - El lector actual (`rover_identity_inventory`) solo admite `MAV_SYSID` y `DDS_USE_NS`. Ampliarlo es un cambio en código del subsistema rover que necesita revisión.
2. **Decisión de Joel:** cambiar `GUID_TIMEOUT` a un valor dentro de la ventana (por ejemplo, 1,0 s).
   - Es un cambio de parámetro operativo de ArduPilot.
   - **No se ha hecho.** Necesita autorización, y después hay que volver a leerlo en vivo.
3. **Comisionado OPERATIVO autorizado:**
   - Ordenar una velocidad baja y dejar de enviar sin enviar cero.
   - Observar el STATUSTEXT y la odometría hasta la parada.
   - Medir la sobrevelocidad y el frenado reales, y sustituir los supuestos de 1,25 y 1 m/s².

Sin los pasos 1–3, **la capacidad de parada independiente no está demostrada y el NO_GO se mantiene.**

## 9. Contrato de parada y autoridad (04/11/2026, OFFLINE)

Pruebas: `tests/test_rover_stop_contract.py`, cada una reproducida antes de corregir.

| Cláusula | Estado | Dónde se comprueba |
| --- | --- | --- |
| STOP no depende de una orden siguiente del host | Se cumple: EOF, watchdog o caducidad → `safe_stop` del worker; monitor → cero | `test_rover_pipe_watchdog.py` (con un proceso hijo real) |
| El watchdog conserva los límites | Se cumple: los límites se fijan en el `hello`; un segundo `hello` es una violación | `test_rover_pipe_watchdog.py`, `test_rover_stop_contract.py` |
| Ninguna transición PASSIVE → OPERATIONAL | Se cumple: `mode` es de solo lectura en el host y fijo en el worker | `test_rover_stop_contract.py` |
| Ningún rearmado tras un fallo de comunicación sin autoridad nueva | **Defecto corregido.** El worker aceptaba GUIDED/ARM con telemetría caducada, y un segundo GUIDED/ARM en la misma sesión tras perder la telemetría (y recuperarla) o tras una parada confirmada. Ahora GUIDED/ARM exigen telemetría fresca y quedan cerrados para el resto de la sesión | `test_rover_stop_contract.py` |
| La reserva sigue protegida si la parada no se confirma | Se cumple: `UNCONFIRMED`, `mark_uncertain` | `test_rover_first_navigation.py` y `test_rover_first_navigation_control.py` (activan la política **solo dentro del test**) |
| Las órdenes inciertas no se reenvían | Se cumple: tras un efecto incierto, solo paradas; un pipe roto no se reutiliza ni para parar | `test_rover_pipe_budget.py`, `test_rover_stop_contract.py` |
| Un timeout no equivale a parada | Se cumple: `TIMEOUT_EFFECT_UNCONFIRMED` / `UNCONFIRMED`, nunca `STOPPED` | `test_rover_pipe_*`, `test_rover_stop_contract.py` |
| La factoría crea el worker de la sesión admitida | **Defecto corregido.** `TypeError` si la reserva desaparecía; además, con base `SITL_TRIAL`, solo comparaba los límites. Ahora rechaza antes de crear el worker si el lifecycle, el arranque, la ejecución o el binding difieren del scope admitido | `test_rover_stop_contract.py` |

## 10. Scope /2: recorrido positivo aislado (04/11/2026, OFFLINE)

`tests/test_rover_scope_v2_positive.py`. Ambas políticas siguen en False y se comprueba antes y después. Los almacenes están en `tmp_path`.

**Sin activar una política, «aceptado» significa:** la puerta real rechaza **solo** por `SITL_TRIAL_POLICY_DISABLED`.

| # | Caso | Motivos de la puerta real (además de `SITL_TRIAL_POLICY_DISABLED`) |
| --- | --- | --- |
| 1 | Request exacto | ninguno; `admit_ground_trial` llega a la puerta y no escribe ni reserva nada |
| 2 | Objetivo | `SCOPE_DIFFERS_FROM_REQUEST`, `AUTOPILOT_FAILSAFE_INPUTS_DIFFER` |
| 3 | Pose inicial | `CONTROL_CONTEXT_DIFFERS`, `AUTOPILOT_FAILSAFE_INPUTS_DIFFER`, `EXACT_OPERATOR_AUTHORIZATION_ABSENT` |
| 4 | Cadencia | `CONTROL_CONTEXT_DIFFERS`, `EXACT_OPERATOR_AUTHORIZATION_ABSENT` |
| 5 | Velocidad | `SCOPE_DIFFERS_FROM_REQUEST`, `CONTROL_CONTEXT_DIFFERS`, `AUTOPILOT_FAILSAFE_ASSESSMENT_DIFFERS` |
| 6 | Watchdog del worker | `AUTOPILOT_FAILSAFE_ASSESSMENT_DIFFERS`, `EXACT_OPERATOR_AUTHORIZATION_ABSENT` |
| 7 | Lifecycle | `CURRENT_LIFECYCLE_ID_DIFFERS` (y más) |
| 8 | Contenedor | `CURRENT_ENVIRONMENT_EXECUTION_DIFFERS`, `EXACT_OPERATOR_AUTHORIZATION_ABSENT` |
| 9 | Reutilización | `TRIAL_ALREADY_CONSUMED`; `max_trials` ≠ 1 → `EXACTLY_ONE_TRIAL_REQUIRED` |
| 10 | Reserva perdida | el adaptador (preparación y desarmado) y la factoría rechazan antes de leer el scope |

**Hallazgo.** Antes del 04/11, un watchdog distinto en `control_context` solo lo detectaba la declaración. `policy_gate` recalculaba los límites del worker con el propio watchdog del contexto. Ahora también lo detecta la reevaluación de `GUID_TIMEOUT` (§8).

**La autorización SITL de las pruebas** la calcula `expected_authorization()` como fixture offline. No se escribe fuera de `tmp_path`.

**No demostrado aquí:**
- la admisión y la ejecución completas con la política activada (eso solo lo cubren los tests que la activan dentro del test);
- la sesión real.

## 11. Medida de latencias en una futura sesión PASIVA

Herramienta: `tools/rover_pipe_latency.py`. Pruebas: `tests/test_rover_pipe_latency.py`.

**Instrumentación** (ya en el código, sin efecto en el control):
- Cada respuesta del worker lleva `timing`, en su reloj monotónico: recibido, respondido, procesado y la edad de la telemetría por flujo.
- `PipeRos2Session.timings` guarda, por llamada, el envío y la recepción en el reloj monotónico del host, más los sellos simulados de cada `observe`. Como máximo 4096 registros.

**Dominios de reloj:** host, worker y tiempo simulado. Nunca se comparan sellos de dominios distintos.
- Solo se calculan duraciones dentro de cada dominio.
- El tiempo de pipe y serialización es `total del host − procesado del worker` (una diferencia de duraciones).
- Las estimaciones de un solo sentido aparecen **solo** si cada muestra encaja el intervalo del worker dentro del del host. Es una condición necesaria, no una prueba.

**Informe:**
- por operación: total, procesado y pipe en p50/p90/p95/p99/máx, con su desviación (jitter);
- edad de la telemetría al responder;
- ritmo efectivo de `observe`;
- RTF (Δ sellos simulados / Δ recepción en el worker);
- veredicto sobre `IPC_RESERVE_S`: `INSUFFICIENT_SAMPLES` por debajo de 50 muestras; `RESERVE_SUPPORTED_BY_THIS_MEASUREMENT`; o `RESERVE_EXCEEDED`.

**Procedimiento propuesto. NO ejecutado. Necesita autorización.**
1. Comprobaciones de la checklist (§1–§4).
2. Arranque autorizado de `rover_only`.
3. Readiness, MotionBinding y `rover_sim_metrics` del mismo lifecycle.
4. `open_passive_session(...)`. El worker no crea ningún publicador ni cliente de servicio.
5. `measure_passive(session, observations=100)`: un `probe` y 100 `observe`. Rechaza una sesión OPERATIONAL. Unos 85 s a 1,2 Hz.
6. `session.close()`.
7. Guardar el informe JSON en un directorio de evidencias **nuevo**.
8. Parada autorizada.

Ninguna orden llega al rover. Si `RESERVE_EXCEEDED`, se sube `IPC_RESERVE_S` y se vuelve a derivar la cadencia (§7.3): no se fuerza el ensayo.

## 12. Pines XRCE y estado NO_GO (04/11/2026)

**Revisión nueva:** `evaluation/operations/rover_xrce_pin_revision_2026_11_04/` (ver su README). La histórica sigue intacta.
- El lector revisado cambia solo 4 pines.
- `selection_dry_run` sigue **BLOCKED**: falta la revisión embebida del helper de host `simulation_lifecycle.py`. Queda como plantilla PENDIENTE y no se ha escrito.
- Con esa revisión aceptada, calculada en un directorio temporal, los archivos de selección serían válidos.

**Bloqueos NO_GO del subsistema rover tras esta sesión:**

| # | Bloqueo | Estado |
| --- | --- | --- |
| 1 | Revisión XRCE + precheck vigente | Preparada y verificable offline. Pendientes: tu revisión de los diffs, la revisión del helper de host, tu autorización exacta y el precheck en el momento de usarla. **Sigue abierto** |
| 2 | Integración positiva del contrato /2 | Recorrido positivo aislado hasta la puerta, con las 10 variaciones rechazadas. No incluye la admisión ni la ejecución con la política activada. **Reducido; sigue abierto para la integración real** |
| 3 | Latencia real y parada independiente | Capa independiente identificada y exigida (§8). Instrumentación de latencia lista (§11). Ningún valor medido. Con `GUID_TIMEOUT` = 3 s el ensayo se rechaza. **Sigue abierto** |
| 4 | Lifecycle nuevo, binding, métricas y scope para ti | Sin cambios: requiere una sesión real. **Sigue abierto** |
