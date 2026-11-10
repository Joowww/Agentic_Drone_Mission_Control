# MotionBinding: cierre de investigación offline (04/11/2026)

## Alcance y resultado

Se recuperaron y completaron los cambios pendientes de tools/rover_motion_binding.py, tests/test_rover_binding_metrics.py y tests/test_rover_binding_freshness.py en feature/rover-sitl-first-motion, desde HEAD fe1493b8b. No se ejecutó ROS, Docker exec, Gazebo, SITL ni ningún comando de control del rover. No se cambiaron parámetros, políticas, autorizaciones ni evidencias selladas.

**Resultado offline: PASS.** Las pruebas cubren el colector generado con dobles; no acreditan el comportamiento de ROS/Gazebo/SITL en ejecución real.

## Causa del rechazo original

La evidencia real del 04/11 registra cinco muestras crecientes y publicadores/GIDs resueltos. La última recepción de odometría queda a **2.726745415 s** del cierre del recolector, por encima del límite existente de **2.0 s**; por eso MotionBinding se rechazó. El descubrimiento de publicadores tardó **2.719 s**, una medición distinta de la edad de la última muestra. El recolector anterior recibía odometría y después consultaba información de bridge/Gazebo y cerraba ROS antes de fijar el timestamp final.

La evidencia no reparte los 2.726745415 s fallidos entre bridge, Gazebo y cleanup. Una sesión acreditada del 03/11 registró **1.24 s** entre la última recepción y el final. Es evidencia de que el trabajo posterior a la recepción consume margen; no demuestra qué fase causó cada parte del retraso del 04/11.

## Cambios del protocolo /2

- Descubre ambos publicadores y conserva snapshots de grafo y GID.
- Inspecciona el bridge y consulta la pose de Gazebo antes de crear la suscripción VOLATILE de odometría.
- Registra cada recepción dentro del callback con reloj monotónico del contenedor y conserva también la hora Unix para trazabilidad.
- Guarda gazebo_pose_received_monotonic_ns; exige que la primera recepción nueva de odometría ocurra dentro de MAX_SAMPLE_AGE_S = 2.0 s de esa consulta de pose.
- Comprueba que los GIDs antes/después no cambien, que haya exactamente un publicador de cada flujo, que los frames sean odom -> base_link, que los sellos de origen y recepciones sean crecientes y que pose/yaw estén dentro de las tolerancias existentes.
- Destruye el nodo y llama a shutdown antes de fijar collected_monotonic_ns. La edad acreditada es collected_monotonic_ns menos la última received_monotonic_ns; debe estar entre 0 y 2 s.
- La adquisición host usa únicamente monotónico del host (started_monotonic_ns, received_monotonic_ns, now_monotonic_ns) y conserva el límite superior de 60 s. No resta relojes del host y contenedor.
- Conserva errores de colección, cleanup y metadata en collector_error/collector_errors. Los errores secundarios no sustituyen al primero; assess() bloquea antes de acreditar. Se intenta emitir JSON parcial incluso si falla una lectura final de metadatos.
- collect() conserva el JSON parseado como raw y solo colas diagnósticas acotadas: 8192 caracteres de stdout y 2048 de stderr. Ya no duplica ambas salidas completas dentro del resultado.

El límite de frescura sigue en 2 s. No se amplió ningún timeout para hacer pasar el caso. El límite entre pose de Gazebo y primera odometría nueva también usa esos 2 s, de modo que una pausa temporal grande después de la consulta bloquea el binding.

## Riesgos y límites

La lectura de pose de Gazebo y el grafo DDS no forman una instantánea atómica. El binding exige proximidad temporal, GID único/estable y concordancia de pose dentro de tolerancias; una comprobación de grafo no autentica cada mensaje de odometría. Las pruebas no caracterizan la latencia del CLI gz, las API ROS, el scheduler ni el cleanup reales. Tampoco prueban que una sesión real obtenga suficientes muestras frescas, que el reloj simulado avance o que se pueda detener físicamente un rover. No otorgan autorización de movimiento.

## Pruebas offline

Comandos ejecutados con timeout de 120 s:

- tests/test_rover_binding_metrics.py + tests/test_rover_binding_freshness.py: **63 passed**.
- Regresiones de colector pasivo, preparación, identidad, lifecycle, fences, scope, historiales y journal: **309 passed**.
- Total final: **372 passed**.

La primera ejecución de la nueva aserción temporal falló porque el doble asigna duración cero al inventario de bridge. Se corrigió la aserción para exigir orden no decreciente, que admite una fase instantánea; la ejecución final quedó verde.

Entre los casos cubiertos están consulta Gazebo sintética de 2.726745415 s, muestras frescas, cleanup lento/caducado, primera odometría tardía respecto de pose, DDS sin identidad resuelta hasta después, GID que cambia, publicadores duplicados, clock de fuente detenido, ausencia de muestras, scope extranjero, fallo de destroy_node, fallo de rclpy.shutdown, fallo de lectura de boot ID, fences antes/después y frames inválidos.

El replay del registro real fallido del 04/11 conserva el rechazo por 2.726745415 s. El replay de la evidencia real acreditada del 03/11 conserva la evidencia calculada idéntica. No se editaron esos registros.

## Estado pasivo consultado

Durante esta revisión no se encontraron archivos de reserva v1, v2, v3, sequence ni lease lifecycle, locks abiertos bajo vehicle_locks, procesos host rover/Gazebo/ArduPilot/bridge/agente, ni socket local 5780. El contenedor tfg-ardupilot-gazebo permanece iniciado; docker top mostró únicamente un bash, sin procesos de simulación. Esta observación no equivale a un precheck operativo nuevo ni a permiso para arrancar otra sesión.

## Propuesta para una futura prueba pasiva

**GO únicamente para solicitar una autorización humana nueva. NO_GO para iniciar ahora.** La autorización de una sesión del 04/11 ya está consumida. Antes de cualquier START se requiere un precheck actual SATISFIED, exclusividad confirmada, una declaración nueva de alcance y autorización humana exacta. Si el precheck queda bloqueado, se detiene el plan; no se altera ni limpia ninguna reserva para conseguir SATISFIED.

La sesión futura sería solo lectura y sin movimiento. Debe conservar, en un directorio nuevo con manifiesto propio:

1. Git/sha de fuentes, boot, identidad completa de ejecución del contenedor y lifecycle nuevo.
2. Precheck previo/posterior, operaciones START/STOP protegidas y logs originales.
3. JSON bruto del colector /2, incluidos errores parciales, GIDs/snapshots, configuración de bridge, pose Gazebo, timestamps por fase, host window, recepciones monotónicas, edades y digest de evidencia.
4. Resultado de readiness y métricas pasivas autorizadas, sin parámetros modificados, ARM, cambios de modo, cmd_vel ni navegación.
5. STOP protegido, precheck final y hashes/manifiesto de cada archivo.

La evidencia nueva debe mostrar explícitamente que bridge/Gazebo preceden la ventana de odometría; gazebo_pose_received_monotonic_ns no posterior a first_sample_received_monotonic_ns; pose a primera muestra dentro de 2 s; última recepción a fin tras cleanup dentro de 2 s; GIDs y frames esperados; fences coincidentes antes y después; errores ausentes; y status ACCREDITED_FOR_SESSION. Cualquier carencia deja MotionBinding BLOCKED y se conserva la captura fallida. La acreditación seguirá limitada a ese lifecycle/ejecución/boot.
