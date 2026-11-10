# Revisión de seis commits y preparación de sesión pasiva (04/11/2026)

**GO exclusivamente para SOLICITAR autorización de una prueba pasiva sin movimiento.**
**NO_GO para armar, cambiar modos o navegar.** El protocolo de abajo NO se ha ejecutado.

Base comprobada: `feature/rover-sitl-first-motion`, `51c8a91f5cbf033fa69f9a4f8fbdc015f24afd25`, árbol limpio.
Alcance: `f3af4cd5c`, `6873ded97`, `0fa510456`, `85d0bdcc9`, `f69764ee8`, `51c8a91f5` y sus consumidores inmediatos.
No se ha repetido la auditoría general. No había escritores del proyecto ni Claude visibles en `/proc` al comenzar.

## Resultado y correcciones confirmadas

1. **Frenada efectiva.** `assess()` calculaba el límite de `GUID_TIMEOUT` con `ATC_*` por defecto, aunque mostraba una envolvente calculada con los valores leídos. Con `ATC_DECEL_MAX=0.01`, aceptaba una envolvente fuera del margen. Ahora revalida el hecho, deriva el límite con los valores efectivos y exige que todos los escenarios entren en el margen. Sin límite de frenada rechaza con `RoverControlError`, antes de intentar serializar infinito.
2. **Ejecución completa.** El hecho de parámetros solo guardaba el ID del contenedor, que sobrevive a un reinicio. Ahora congela y compara también `environment_execution`, incluido `container_started_at`, además del boot y lifecycle. Un hecho anterior sin esa ejecución completa falla cerrado.
3. **Preparación cerrada tras fallo.** Ya se rechazaban GUIDED/ARM con telemetría vieja y después de un timeout de observación, HOLD/desarmado aceptados o un fallo enclavado. Faltaba cerrar la preparación al rechazar por telemetría caducada y al recibir una respuesta negativa de GUIDED/ARM. Ahora una recuperación posterior no permite rearmar en esa sesión. Las órdenes de parada conservan su vía.
4. **Identidad antes de crear procesos.** La factoría comparaba el cableado con el scope admitido, pero `require_current` y el fence real llegaban después del spawn. Ahora ambos se comprueban antes, tanto en OPERATIONAL como en PASSIVE, y se mantienen las comprobaciones posteriores. Un binding inválido no crea worker.
5. **Relojes y contabilidad.** Se eliminó la estimación de latencia de un sentido: encajar los sellos del worker entre los del host no demuestra un origen común. Se conservan RTT host, duración interna worker y su diferencia de duraciones; esta última presupone igual escala de segundos, no igual origen. La captura cuenta observaciones exitosas de esta invocación, declara INCOMPLETE ante errores/pérdidas y conserva el estado armado de cada muestra; si no acredita desarmado, interrumpe sin enviar controles. Al alcanzar el límite de timings, las observaciones descartadas ya no sobrescriben el sello de la última muestra conservada.

Las primeras siete regresiones nuevas fallaron antes de corregir; otras dos reprodujeron la repetición de preparación después de una respuesta negativa. No se han cambiado `rover_ground_executor.py`, `rover_ros2_adapter.py`, `session_precheck.py` ni `simulation_lifecycle.py` en esta revisión.

**Scope /2:** el arnés positivo nuevo recorre `policy_gate` y `admit_ground_trial` reales hasta el único rechazo `SITL_TRIAL_POLICY_DISABLED`, sin activar ninguna política ni reservar. También rechaza cambios de objetivo, pose, cadencia, velocidad, watchdog, lifecycle, ejecución, reutilización y reserva perdida. Esto NO prueba una admisión/ejecución completa con la política abierta ni comportamiento real del rover.

## Parámetros: nombres y tipos comprobados, valores aún desconocidos

Se leyó exclusivamente el sistema de archivos del contenedor existente; no se inicializó ROS ni se ejecutó el binario Rover.

- Contenedor observado: `0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f`, iniciado `2026-11-03T09:44:02.9887145Z`.
- Fuente instalada: `/root/ardu_ws/src/ardupilot`, Git `755258dbb452f46dc7e1e47a36591f3b62e8830d`.
- Binario instalado leído: `/root/ardu_ws/install/ardupilot_sitl/bin/ardurover`, SHA-256 `95f4b5a5efddbe2723496d0febebd4bb0b2b7019ce228b91da422fbcb19a76fb`.
- `Rover/Parameters.cpp`: `c9a8d99cdf8d0e3f37dacce6880821e8b10ccc1eab5d02d48a1c5fda5de8a96c`.
- `Rover/Parameters.h`: `be0de40dcea05f126a108e24a70305bd5d5a195a055d2be480f5ab7f9d8d0ff7`.
- `AR_AttitudeControl.cpp`: `1344a09c0883f303849c0ca9c6720b54ffbf80ef9f223ed27569a4414fed7543`.
- `AR_AttitudeControl.h`: `569996342ddf67d5671bd2ac4d73413efe66ea5389bd595953b56f6ad898a175`.
- `AP_DDS_Client.cpp` instalado: `f512901b5c3617aa46861a967ef1cddb2515878523b1fbf240bbb54333ceaef4`. Difiere de la copia diagnóstica sellada; se inspeccionó su rama GET_PARAMETERS instalada. No se afirma que el binario esté reproduciblemente compilado de ese árbol.

| Parámetro existente en las fuentes instaladas | Tipo AP / respuesta ROS |
| --- | --- |
| `GUID_TIMEOUT` | AP_Float / DOUBLE (3) |
| `ATC_ACCEL_MAX`, `ATC_DECEL_MAX` | AP_Float / DOUBLE (3) |
| `FS_TIMEOUT`, `FS_GCS_TIMEOUT`, `FS_EKF_THRESH` | AP_Float / DOUBLE (3) |
| `FS_ACTION`, `FS_GCS_ENABLE`, `FS_CRASH_CHECK`, `FS_THR_ENABLE`, `FS_EKF_ACTION` | AP_Int8 / INTEGER (2) |
| `FS_THR_VALUE` | AP_Int16 / INTEGER (2) |
| `FS_OPTIONS` | AP_Int32 / INTEGER (2) |
| `MAV_SYSID`, `DDS_USE_NS` | Identidad: INTEGER (2) |

`tools/rover_passive_parameters.py` prepara una vía independiente y fija de lectura. No amplía el scope del lector histórico de identidad ni cambia binarios/preparaciones selladas. Usa únicamente `/ap/v3/get_parameters`, `rcl_interfaces/srv/GetParameters`. El firmware admite como máximo ocho nombres por petición: son tres lotes, con `MAV_SYSID` y `DDS_USE_NS` repetidos. Exige sysid 3 y namespace habilitado, como declara el launch `rover_only`.

Conserva valor efectivo y tipo de cada respuesta, UTC inicial/final por lote, duración monotónica del lector, rover/sysid, boot, ejecución completa del contenedor, lifecycle, hash del binding y origen. Valores ausentes/NOT_SET, tipos inesperados, cambio de identidad, descubrimiento ambiguo, boot/fence distinto o timeout bloquean la lectura; no hay relleno con defaults ni reintentos. Los lotes no constituyen una instantánea atómica.

**Límite de atribución:** un future público `rclpy` no identifica el GID del servidor que respondió. El resultado queda `READ_DIAGNOSTIC_SERVER_INSTANCE_UNVERIFIED` y `eligible_for_motion_admission=False`. Sirve para observar parámetros con procedencia y scope declarados; no acredita por sí solo el servidor AP de un ensayo operativo. No se convierte automáticamente en `autopilot_fact`. La atribución correlacionada de RPC/servidor sigue pendiente para movimiento.

No se ha leído ningún valor efectivo en esta tarea. `GUID_TIMEOUT=3.0` sigue siendo solo un default compilado conocido. Tampoco se autoriza cambiarlo a 1.0 ni a otro valor.

## Latencias y cadencia

`measure_passive(session, observations=100, timeout_s=2.0)` usa un `probe` y hasta 100 `observe`; no llama `exchange`. Para completar exige exactamente 100 observaciones exitosas, cero errores/pérdidas y desarmado en todas. Guarda por separado los estados observados y los timings originales.

- RTT host, envío host, procesamiento worker y overhead pipe/serialización, con p50/p95/p99, máximo y desviación estándar (jitter).
- Intervalos entre respuestas de observación y tasa efectiva de parejas, sin confundirla con frecuencia de publicación de status ni odometría.
- Edad de cada flujo en el worker al responder. Es edad desde recepción local, no latencia extremo a extremo desde generación.
- RTF de status: incrementos de su sello AP frente a incrementos de recepción en el worker. No se resta un sello simulado a un monotónico ni se cruza el reloj AP con el de Gazebo.
- **Cadencia real independiente:** `rover_sim_metrics.collect(..., window_s=20.0)` cuenta callbacks de status y odometría por separado y mide RTF de Gazebo y AP con sus propios `/clock`. Se conserva su raw y summary; no se deriva la frecuencia de odometría de los 100 pares. Sigue siendo tasa recibida, no prueba de ausencia de pérdida DDS.
- El sampler devuelve tiempos monotónicos del contenedor. El sobre host registra inicio/fin por separado. En este protocolo NO se llama `cadence_from_metrics`, que exigiría acreditar la comparabilidad host/contenedor para su comprobación de edad. No se usa esta captura para admitir movimiento.

`IPC_RESERVE_S=0.25` permanece como supuesto. Un p99 favorable en esta sesión apoya el presupuesto solo para esta medición; no garantiza el máximo bajo fallos ni mide la latencia operativa de ModeSwitch/ArmMotors. El procesamiento de `observe` incluye la espera de telemetría. No se pueden descomponer las dos direcciones del pipe sin demostrar una correspondencia de relojes.

## XRCE: revisión técnica del borrador, sin aprobación humana

Directorio sellado revisado: `evaluation/operations/rover_xrce_pin_revision_2026_11_04/4732a0bc-897e-4b55-bd7b-ea99b0b9f9b3/`.

Los siete SHA-256 verifican. Los cuatro parches pasan `git apply --reverse --check` contra las fuentes actuales (solo comprobación, nada aplicado). Lector derivado: únicamente cuatro pines cambiados; binario, dependencias y demás campos permanecen iguales. Esta revisión no cambia esos cuatro archivos, por lo que sus pines siguen coincidiendo.

| Diff revisado | Efecto y límite |
| --- | --- |
| `rover_ground_executor.py` | Preparación y readiness por perfil, gate scope /2, reevaluación del failsafe, autoridad y pose antes de preparar. Políticas cerradas; no es autorización. Los defectos en sus módulos nuevos llamados se corrigen arriba sin editar este pin. |
| `rover_ros2_adapter.py` | Reserva explícita antes de leer scope; preparación pulse/navigation; cancelación en finally y margen de deadline. No reintenta efectos inciertos. |
| `session_precheck.py` | Consume el layout SHA256SUMS de resultados de función con rutas exactas, procedencia, hashes, cronología, inventario y espera causal del monitor. Conserva la distinción entre cierre histórico y recursos actuales. |
| `simulation_lifecycle.py` | Cierre protegido de un start ordinario UNCONFIRMED: mismo owner/scope/boot/ejecución, restricciones y árbol registrados, declaración exacta y recibo posterior. No es limpieza automática; inspeccionar elegibilidad no ejecuta cierre. |

**Preparado correctamente como borrador pendiente; no seleccionable ni autorizado.** El lector nuevo continúa bloqueado por `Host lifecycle helper review missing/contradictory`. No se ha rellenado la plantilla, cambiado el lector, firmado, emitido una declaración humana ni aplicado autorizaciones. Una revisión técnica de Codex no equivale a la revisión humana pendiente de Joel. Cualquier aceptación requiere un derivado nuevo y su propio digest; no se modifica el histórico.

| Uso | ¿Lo bloquea este borrador pendiente? |
| --- | --- |
| A. Diagnóstico XRCE con esa preparación | **Sí.** Revisión de helper y autorización exacta pendientes, además de precheck y hechos runtime actuales. |
| B. Start ordinario `rover_only`, sin manifiesto diagnóstico | **No directamente.** No selecciona ese reader. Consume el precheck de disposición histórica existente si hay target; sus diez pines coinciden hoy. Eso no acredita SATISFIED actual. |
| C. Lectura pasiva ordinaria propuesta | **No directamente.** Usa GetParameters y worker PASSIVE ordinarios, no el receptor XRCE del borrador. Requiere autorización nueva, precheck, start confirmado, readiness y binding nuevos. Atribución de servidor limitada como se indicó. |
| D. Movimiento operativo | **NO_GO.** La ruta XRCE diagnóstica estaría bloqueada si se eligiera; prescindir de ella no resuelve los gates de movimiento, parámetros efectivos/atribución, pruebas de parada ni políticas cerradas. |

## Secuencia exacta propuesta: no ejecutada

Solicitar una autorización **nueva** que cubra start/stop ordinarios `rover_only`, readiness de consulta, binding nuevo, tres lecturas GetParameters, 100 observaciones PASSIVE y sampler de suscripciones de 20 s. Excluye modo, armado/desarmado, publicaciones `cmd_vel`, escritura de parámetros, selección diagnóstica XRCE, flags y recuperación de UNCONFIRMED. La autorización y todos los GID proceden de esa futura sesión.

Los siguientes son comandos/API que se ejecutarán solo después de esa autorización. Usar Python del entorno validado con `PYTHONDONTWRITEBYTECODE=1`. Crear con `tempfile.mkdtemp(prefix='rover-passive-2026-11-04-', dir=Path.home()/'TFG/archivo_TFG')` un directorio externo nuevo. Guardar cada resultado/raw con creación exclusiva, JSON `allow_nan=False`, UTC y scope; no sobrescribir archivos.

1. **Precheck actual.** `python -B -m tools.rover_xrce_trace.historical_disposition diagnostic-precheck`. Guardar stdout/rc. Exigir `status == 'SATISFIED'` y `precheck_satisfied is True`. No aplicar ni renovar disposiciones. Si bloquea, terminar sin START.
2. **Start nuevo autorizado.** `python -B -m tools.simulation_lifecycle start --headless --profile rover_only`, sin `--diagnostic-agent-manifest`. Guardar salida y operación original. Exigir `status == 'SUCCESS'`, `operation.state == 'FINISHED'`, `operation.profile == 'rover_only'`. Tomar `lifecycle_id = operation.owner_id` recién emitido. **Si devuelve UNCONFIRMED, terminar aquí conservando la lease; no entrar en ningún finally de STOP ni forzar limpieza.** Una eventual inspección/cierre protegido sería otra tarea autorizada.
3. **Ejecución y readiness.** `env = tools.reconciliation_environment.inspect_active_execution()`; `boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()`; `container_id = env['persistent_identity']['container_id']`. Exigir boot igual a `env['container_boot_id']` y ejecución igual a la del START. `ready = tools.simulation_status.check_simulation_ready(profile='rover_only')`; exigir `ready['status']=='READY'`, `ready['ready'] is True` y rover_01/v3 con status/prearm PASS. No hacer un preflight de vuelo.
4. **MotionBinding nuevo.** `b = tools.rover_motion_binding.collect(container_id, lifecycle_id=lifecycle_id, environment_execution=env, host_boot_id=boot, discovery_s=15.0, sample_s=60.0, samples=5)`. Exigir `b['status']=='ACCREDITED_FOR_SESSION'`; conservar `b['raw']` y `b['evidence']`. Nunca cargar evidencias/GID de una sesión terminada.
5. **Lectura de parámetros.** `p = tools.rover_passive_parameters.collect(container_id, lifecycle_id=lifecycle_id, environment_execution=env, host_boot_id=boot, binding_evidence=b['evidence'], timeout_s=3.0, discovery_s=10.0)`. Conservar el resultado completo, incluida su limitación de servidor. Ausencia/error no se sustituye por defaults; no escribir valores.
6. **100 observaciones.** `s = tools.rover_pipe_session.open_passive_session(container_id, lifecycle_id=lifecycle_id, environment_execution=env, host_boot_id=boot, binding_evidence=b['evidence'], watchdog_s=5.0, stderr_path=directorio_nuevo/'worker.stderr')`. Llamar `lat = tools.rover_pipe_latency.measure_passive(s, observations=100, timeout_s=2.0)`. Guardar `lat` y `s.timings`. En un finally exclusivo de esta captura llamar `s.close()` y conservar cualquier incertidumbre. No hacer otras tareas mientras el pipe queda inactivo: el watchdog no se amplía.
7. **Latencias.** Exigir `lat['measurement_status']=='COMPLETE'`, `lat['observations_completed']==100`, sin errores/timings descartados, y analizar sus p50/p95/p99 y jitter. No inferir latencias unidireccionales. Si `RESERVE_EXCEEDED`, la prueba no valida el presupuesto; no cambia parámetros, constantes o autorizaciones automáticamente.
8. **Cadencia, con el worker ya cerrado.** Entre fences de ejecución guardar tiempos host de inicio/fin y ejecutar `raw, summary = tools.rover_sim_metrics.collect(container_id, window_s=20.0)`. Archivar ambos con `env`, boot y lifecycle. Exigir schema `/2`, RTF disponible, status y odometría frescos, sellos crecientes y ambas tasas independientes; no confundirlas con `observe_rate_host_hz`.
9. **Desarmado y estabilidad de sesión.** Exigir `lat['disarmed_in_all_observations'] is True`, 100 estados conservados y `summary['status']['last']['armed'] is False`, con flujo fresco. Comparar nuevamente ejecución/boot y última operación lifecycle con el START propio, sin operaciones intermedias ni restricciones nuevas. Si falla, registrar captura INCOMPLETE/NO_GO, sin enviar HOLD, desarmado, cero o recuperación. Esos controles no forman parte de esta prueba.
10. **STOP controlado.** Solo después de START confirmado: `python -B -m tools.simulation_lifecycle stop --headless --profile rover_only`. Este STOP de infraestructura forma parte de la autorización solicitada y debe intentarse también si fallan readiness, binding o captura después de START confirmado. Exigir SUCCESS/FINISHED, guardar operación y backend.log propios. BLOCKED/UNCONFIRMED se conserva; no señales manuales, borrado de locks, stop del contenedor ni reintentos forzados. Una excepción al cerrar el pipe no equivale a limpieza confirmada.
11. **Precheck final y sello nuevo.** Repetir el comando de 1 y exigir SATISFIED. Guardar salidas originales, fallos, cierre, hashes de fuentes/herramientas y manifest SHA-256 del nuevo directorio. Un STOP exitoso sin precheck final no completa el protocolo.

Antes y después de cada colector, usar `assert_environment_execution(env)`, leer boot y comprobar por lectura que la última operación lifecycle sigue siendo el START propio FINISHED y que no hay nueva restricción. Estos fences no conceden autoridad y no sustituyen la atribución RPC pendiente. No ejecutar simultáneamente otro agente, lifecycle, demo o prueba operacional sobre el simulador.

No es necesario que el `GUID_TIMEOUT` leído sea apto para navegar para completar esta medición pasiva: cualquier valor efectivo válido se registra, sin modificarlo. Un valor fuera de la ventana mantendrá bloqueado el movimiento.

## Validación offline y límites

- Regresión afectada final: **522 passed, 50 skipped**, cero fallos. Omisiones explícitas antes de fixtures que activarían flags. Incluye lector tipado y cancelación, 100 observaciones sintéticas sin controles, scopes positivos/rechazos, transporte, worker, binding, lifecycle, cierre protegido y precheck histórico.
- Tras corregir la sobrescritura de sellos al alcanzar el límite: **75 passed**, cero fallos/omisiones en instrumentación, parámetros, casos nuevos y presupuesto pipe. Las tandas se solapan; no se suman como pruebas distintas.
- Comprobación adicional de preparación XRCE antigua en la primera tanda ampliada: `test_derived_closure_reader_pins_are_consumed_without_binary_changes` falla como ya estaba documentado. Su derivación solo actualiza dos pines y deja los cuatro cambios recientes sin revisar; no se modificó ni se ocultó ese fallo ni se refrescaron históricos para hacerlo pasar. Esa tanda: **399 passed, 50 skipped, 1 failed**.
- `git diff --check` y sellos/diffs XRCE correctos. Directorio de logs/JUnit y omisiones: `/tmp/tfg-passive-review-20261104-rldp3xae/results/`.
- 797 archivos protegidos comprobados (manifiestos, borrador XRCE y estado runtime); sin cambios ni nuevas entradas de archivo en `missions/generated/` en la comprobación posterior a pruebas. No se cambiaron reservas, autorizaciones reales, históricos o flags. Se usaron dobles y archivos temporales para las pruebas; ninguna simulación ni proceso ROS real.

La envolvente de frenada sigue siendo un **modelo condicional**: ATC_DECEL_MAX/ATC_ACCEL_MAX son máximos configurados, no una garantía física de deceleración mínima. El sobrepaso de velocidad, la frenada real, la entrega DDS y los tiempos operativos de parada siguen sin medirse. También siguen pendientes la acreditación servidor/RPC y las condiciones actuales del futuro arranque. Ninguna aprobación offline convierte estos supuestos en autorización para movimiento.
