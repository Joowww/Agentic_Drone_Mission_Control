# Rover: instrumentación y preparación de ensayos — 06/11/2026

## Alcance y estado

Trabajo offline sobre feature/rover-sitl-first-motion, partiendo de 277c8e136. No se inició worker, SITL ni Gazebo, y no se enviaron controles. La evidencia del 04/11 está preservada en evaluation/operations/rover_passive_validation_2026_11_04_ae364130/; su precheck final BLOCKED y sus limitaciones forman parte del registro.

El protocolo de captura ahora es tfg.rover.pipe/2. Cada observación incluye mensajes originales, stamps simulados, timestamps de recepción monotónica del worker, recepción monotónica del host, lifecycle, boot, GIDs, frames, pose, orientación, velocidades y edad de telemetría. Los relojes siguen separados. tools/rover_stationarity.py sólo analiza registros existentes; falta una nueva captura pasiva para medir estacionariedad real. Los umbrales conservadores iniciales son configurables: ventana 30 s, frescura 1 s, hueco máximo 2 s, desplazamiento horizontal/vertical 5 cm, deriva acumulada 10 cm, velocidad lineal/angular 0.03 m/s y 0.03 rad/s, cambio de orientación 0.02 rad, 100% de observaciones válidas. No constituyen tolerancias aprobadas para movimiento.

## TCP 5780

La evidencia registró /proc/net/tcp state 06, que es TIME_WAIT: una conexión cerrada que permanece en enfriamiento TCP. El inventario original trataba cualquier fila como ocupación genérica. Se añadió nombre de estado y motivo RELEVANT_TCP_TIME_WAIT_COOLDOWN; la reserva continúa bloqueada porque no se ha demostrado el comportamiento de reutilización de ambos sockets y no se conoce propietario. LISTEN, ESTABLISHED, estados desconocidos, filas incompletas y propietario incierto permanecen fail-closed. Esto corrige diagnóstico, no convierte 5780 en recurso libre ni demuestra que la siguiente sesión vaya a enlazar correctamente.

## Parámetros y procedencia

El servicio ROS anterior declaró READ_DIAGNOSTIC_SERVER_INSTANCE_UNVERIFIED. tools/rover_passive_validation.py documenta que el rmw_request_id_t legado no trae aquí identidad SampleInfo de la respuesta; el GUID/sequence no acredita qué proceso devolvió esos valores. tools/rover_parameter_correlation.py define un verificador offline para futuras capturas: respuesta DDS con identidad nativa por respuesta y vínculo al proceso, lectura MAVLink con socket propietario/proceso y SYSID/COMPID, mismo lifecycle/boot/proceso/firmware y valores exactos coincidentes. El verificador no consulta endpoints y rechaza los resultados actuales.

Los logs/config .parm pueden explicar configuración cargada, pero sin vínculo a proceso/instancia y momento de arranque no acreditan valores efectivos. Heartbeat más PARAM_VALUE identifica el SYSID/COMPID que responde, no por sí solo el binario o proceso propietario. Sin autenticación, hashes y asociación de socket/proceso tampoco se acredita firmware. Se requiere procedencia independiente y correspondencia explícita; cualquier campo ausente deja UNVERIFIED.

## Fuente local de ArduRover y límites

Checkout externo leído en /home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot, commit 755258dbb452f46dc7e1e47a36591f3b62e8830d (AION-Orca-Alpha2-29048-g755258dbb4). No hay evidencia suficiente de que el binario SITL de la captura se construyera desde ese checkout.

En ese código, AR_AttitudeControl::get_decel_max() retorna ATC_DECEL_MAX si positivo y, si no, ATC_ACCEL_MAX. El limitador de velocidad usa explícitamente el decel configurado positivo al reducir la velocidad; si es cero, cae al límite de aceleración. Por tanto, para ese código, ATC_DECEL_MAX=0 no significa “frenado ausente”; el límite de desaceleración viene de ATC_ACCEL_MAX. Con valores diagnósticos 1.0/0.0, el cálculo ideal de distancia a 1 m/s sería v²/(2a)=0.5 m; a 0.2 m/s, 0.02 m. Esos números excluyen latencia, pendiente, adherencia, saturación, controlador, error de estimación y RTF, y no son distancias medidas ni garantía de frenado.

mode_guided.cpp borra el target de HeadingAndSpeed y TurnRateAndSpeed después de GUID_TIMEOUT y llama a la ruta de parada. GUID_TIMEOUT=3 es un valor diagnóstico no acreditado. FS_GCS_ENABLE=0, si se confirma, desactiva el failsafe GCS basado en ausencia de heartbeats MAVLink; no equivale al timeout del worker ni a pérdida de mensajes cmd_vel. El failsafe de throttle supervisa entrada RC (canal bajo o pérdida de frames), con FS_TIMEOUT, y puede usar FS_ACTION; no es detector de pérdida DDS. El worker watchdog PASSIVE no publica controles. El watchdog OPERATIONAL del worker tiene semántica distinta y no acredita que el autopiloto reciba la parada. No se ha medido frenada simulada ni física.

## Diseño pendiente: ensayo de pérdida de actualizaciones

No autorizado ni ejecutado. Sigue NO_GO. Se requerirá scope y autorización humana propios, distintos de la sesión pasiva y del primer metro.

- Vehículo: sólo instancia SITL rover_only identificada por host, container, proceso, boot, firmware, namespace, lifecycle y GIDs de status/odometría; modelo rover1 y frame de odometría validados en sesión.
- Precondiciones: recuperación acreditada; precheck SATISFIED vigente; TCP/resource inventory libre; estaciónariedad pasiva demostrada; parámetros efectivos atribuidos; zona vacía y límites de mundo/modelo inspeccionados; stops/STOP ensayados offline; monitor separado del controller.
- Estado inicial: desarmado hasta autorización específica de armado, luego READY y posición fija; autoridad separada para ARM/GUIDED. Ninguna autorización existente incluye esos controles.
- Propuesta para revisión posterior, no comando actual: velocidad ≤0.20 m/s en línea recta, sin giro; una sola orden de velocidad de duración acotada; detener el refresco en un instante registrado y medir el comportamiento de GUID_TIMEOUT; límite espacial del vehículo ≤1.0 m desde origen y área despejada ≥3 m en la dirección de marcha. El límite de desplazamiento es una barrera del monitor independiente, no un freno garantizado.
- Monitor independiente: odometría fresca ≤0.2 s y status ≤1 s, stamps progresivos, misma identidad/GID/frames, watchdog host 100 ms, parada protegida ante ≥0.25 m/s, desplazamiento ≥0.5 m, giro, failsafe inesperado, pérdida de fuente, binding o reserva cambiados. La ruta y capacidad de parada de esa acción deben demostrarse previamente; sin ello no se inicia.
- Inyección: cesar sólo refrescos de movimiento desde el cliente identificado; no matar procesos, cortar ROS/DDS o apagar el host. Heartbeat GCS debe registrarse y no confundirse con GUID timeout.
- Tiempo: ventana máxima desde última orden 5 s para reacción observada y 10 s total, sujeta a revisión de temporización de captura. Si no se demuestra detención dentro del límite, el monitor ejecuta sólo el stop previamente autorizado, y la sesión termina en incertidumbre si no se confirma.
- Evidencia: scope/hash, identidad y versiones, parámetros correlacionados, orden y tiempo de última actualización, muestras brutas, recepción/edad, distancia/velocidad, modo/failsafe, intervención del monitor, stop, worker close, STOP y precheck final. Cualquier discontinuidad invalida la conclusión.

Con GUID_TIMEOUT=3 s no acreditado y posible retraso de detección de hasta el timeout, una hipótesis ideal a 0.2 m/s ya permite recorrer aproximadamente 0.6 m antes de contar desaceleración (v*t) y 0.02 m adicionales con 1 m/s² ideal. Esta hipótesis no es límite de seguridad. La distancia máxima real permanece desconocida; si no hay zona/monitor/parada suficientes, no debe autorizarse el ensayo.

## Diseño pendiente: primer metro

Ensayo separado y autorización nueva. Objetivo candidato: avanzar 1.00 m en línea recta sobre odom sólo si MotionBinding confirma asociación vigente odom → base_link, mismo lifecycle y GID. Plan de un único segmento, sin waypoints adicionales; velocidad configurada ≤0.10 m/s; tolerancia de llegada ±0.05 m; límite absoluto 1.20 m desde origen; timeout 15 s. El monitor externo evalúa posición, velocidad ≤0.03 m/s al finalizar, yaw/frames, antigüedad y progresión. Pérdida de odometría/status, GID, boot, lifecycle, binding, exceso de velocidad/desplazamiento, deadline o status armado/flying inesperado dispara abort y stop protegido; si el stop no se acredita, conserva incertidumbre/reserva. No reintentar comandos ni reutilizar autorización. Cerrar worker, STOP protegido y validar estado desarmado/estacionario posterior.

Los límites anteriores son una propuesta de scope, no GO: antes hacen falta parámetro/failsafe atribuidos, estaciónariedad real, política y precheck vigentes, revisión de la ruta de stop, recuperación completa y autorización humana propia para ARM/GUIDED/movimiento. Prueba offline con dobles no habilita una sesión real.

## Contrato JetRacer

tools/rover_vehicle_contract.py separa agente/plan de ejecutores por plataforma: identidad, capacidades, tipo de dirección, observación/estado, salud, plan, autorización, feedback, stop. tools/jetracer_dry_run_adapter.py sólo declara dirección ACKERMANN y cámara IMX219 pendiente de confirmar; no inventa GPS, ROS, SLAM, encoders, velocidad máxima, localización ni salud. Execute/stop no tienen API física y reportan physical_effect=false. Integración propuesta entre worktrees: consumir contrato como dependencia estable acordada en revisión; el worktree de Claude conserva agente/misión, este repo mantiene adaptadores rover. No copiar/modificar su worktree ni conectar un controlador real hasta confirmar sensores, drivers, watchdog y autorización.

## Validación

Las pruebas son sintéticas/offline; verifican geometrías, telemetría, frescura, identidad, captura incompleta, atribución y ausencia de salidas físicas. No se ha ejecutado prueba SITL/Gazebo. El análisis de estacionariedad sobre la sesión del 04/11 sigue UNCONFIRMED porque faltan posiciones y velocidades por muestra; no se reconstruyen valores ausentes.
