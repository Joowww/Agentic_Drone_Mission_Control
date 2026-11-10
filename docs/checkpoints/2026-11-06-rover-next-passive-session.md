# Siguiente sesión pasiva rover: estado actual y procedimiento preparado

Fecha de comprobación: 06/11/2026 UTC. Repositorio: feature/rover-sitl-first-motion, base comunicada 880a7dd9f. Este documento registra comprobaciones de lectura y prepara el procedimiento. No es evidencia sellada, scope operativo, autorización ni token de admisión.

## Precheck y entorno observados ahora

Se ejecutó el precheck oficial de solo lectura:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m tools.rover_xrce_trace.historical_disposition diagnostic-precheck

Resultado a las 11:33:05 UTC: BLOCKED, precheck_satisfied=false, opening_authorized=false, movement_authorized=false. No produce SHA de scope (scope=null, scope_sha256=null). El resultado no autoriza START.

Motivo preciso: Incompatible successor reader versions/pins. El histórico está durablemente en DISPOSED_DIAGNOSTICALLY_INCOMPLETE; los dos sucesores guardados se leen, pero la revisión del consumidor deriva un cambio en reader_hashes para tools/rover_xrce_trace/present_resources.py. La política actual de sucesores permite revisar el pin de historical_disposition.py y simulation_profiles.py, no el lector de recursos. No se amplió esa lista, no se aplicó disposición, no se modificó el journal y no se fabricó un resultado SATISFIED. Hace falta una revisión/autorización separada para aceptar esa revisión del lector o restaurar una implementación que coincida exactamente con el pin existente sin perder la corrección de TIME_WAIT. El precheck bloqueado es el impedimento para generar ahora un scope operativo.

Identidad actual observada: host MSI, boot fd538729-f4ea-4193-a6a3-f5f000fdd14b; Docker Engine ID 2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99; contenedor esperado 0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f, imagen sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66, inicio actual 2026-11-03T09:44:02.9887145Z. El boot del contenedor coincide con el host. Contenedor activo tfg-ardupilot-gazebo (Up 3 days al comprobarlo).

Lectura pasiva de procesos: no se observaron ArduPilot, ArduRover, Gazebo, ROS 2, bridge, worker ni lifecycles; dentro del contenedor solo se observó su shell PID 1 y los procesos breves de la propia consulta. No había listener/conexión TCP host en 5780; las tablas TCP y TCP6 del contenedor estaban vacías. El inventario oficial de recursos informó FREE, occupied=[], cero propietarios y resources_free=true, incluyendo TCP 5780. Esto describe la adquisición de las 11:33 UTC, no garantiza disponibilidad futura.

El precheck informó no_restrictions, no_guards, no_other_sessions, no_host_processes, no_container_processes, resource_context, resource_duration, resource_complete, resources_free, reader_version y resource_scope como true. Los archivos persistentes de coordinación son los locks; el inventario no encontró reserva/lease de rover ni otra sesión. Estado histórico distinto: lifecycle de infraestructura start/stop del 31/10, perfil two_drones_rover, quedó FINISHED/CLOSED, pero su monitor diagnóstico fue incompleto. La disposición actual no reescribe ni completa ese cierre.

## Captura pasiva candidata, solo tras desbloqueo y nueva autorización

No se generó scope declarativo ni hash: al estar el precheck BLOCKED, sus recursos no forman una base admisible y cualquier digest de ejemplo se podría confundir con una autorización. Una vez resuelta la revisión del pin, repetir el precheck oficial inmediatamente antes de preparar scope; exigir resultado SATISFIED, fresco, con opening_authorized=false y recursos libres. La admisión protegida debe repetir sus propios fences. Si cambia host/boot/container/image/start time, lifecycle, proceso, reserva, GID, endpoint o hash de lector, cancelar el scope y preparar uno nuevo.

Operaciones de la futura sesión, una sola vez y ligadas a un SHA nuevo:

1. START protegido headless del perfil exacto rover_only; guardar lifecycle START, identidad persistente/ejecución y recibos completos.
2. READY/Armable y MotionBinding /2 fresco para ese lifecycle, bridge, topics, frames y GIDs esperados.
3. Lecturas diagnósticas solo de GetParameters ROS y PARAM_REQUEST_READ/PARAM_VALUE MAVLink. No escribir parámetros. Correlacionar cada lote con lifecycle/boot, SYSID/COMPID, proceso propietario del socket, hash del ejecutable y firmware. Registrar por separado valor observado, correlación y atribución; si falta asociación nativa de respuesta o ejecutable, el resultado permanece no acreditado.
4. Un único worker PASSIVE, sin publisher ni cliente de servicios de control; un probe y exactamente 100 observe, timeout individual máximo 2 s. No reabrir worker ni completar una captura parcial bajo esta autorización.
5. Conservar el JSON bruto de captura /2, el informe de latencia/RTF y la salida del analizador. Esperar al cierre confirmado del mismo worker; después ejecutar STOP protegido y el inventario/precheck final. La sesión no incluye ARM, DISARM, GUIDED, HOLD, cmd_vel, movimiento, escritura de parámetros, activación de políticas ni limpieza forzada.

La duración esperada de 100 parejas se estima en torno a 80–100 s según la sesión anterior, no es garantía. El scope futuro debe fijar como máximo 300 s de worker, timeout de observación 2 s, un START, un STOP y un precheck final. Si el procedimiento oficial requiere otros límites, volver a calcular y reautorizar el hash; no se estira en ejecución.

Cualquier MotionBinding no acreditado, timeout/observación perdida, contador distinto de 100, estado armado, GID cambiado, endpoint ocupado, parámetro incompleto, error de atribución o cierre incierto hace fallar la sesión. No iniciar otro worker. Usar únicamente el cierre protegido permitido para el estado confirmado; si STOP/close resulta incierto, conservar reserva/restricción y no forzar limpieza.

## Criterios congelados antes de observar

tools/rover_stationarity.py usará los umbrales predeterminados congelados antes de START:

- 100/100 observaciones válidas; captura completa, sin timings descartados y worker cerrado confirmado.
- Cobertura de recepción host monotónica ≥30 s; ningún hueco entre observaciones >2 s; 100% de muestras válidas.
- Frescura de status y odometría en recepción del worker ≤1.0 s por muestra.
- GID de status y odometría constantes e iguales al MotionBinding del lifecycle; boot y lifecycle constantes; source stamps y receipts monotónicos estrictamente crecientes.
- Frame odom y child frame base_link constantes; posición, cuaternión, velocidad lineal y angular presentes y finitos. No rellenar campos ausentes.
- Desplazamiento 3D máximo desde la pose inicial ≤0.05 m; desplazamiento horizontal máximo ≤0.05 m; variación vertical máxima ≤0.05 m; deriva acumulada ≤0.10 m.
- Velocidad lineal máxima ≤0.03 m/s; velocidad angular máxima ≤0.03 rad/s; cambio de orientación y deriva de yaw máximos ≤0.02 rad.
- Pose inicial/final reportadas; estado armed=false, flying=false, failsafe vacío; commands_sent=0, movement_authorized=false.

Los límites de posición/yaw siguen los márgenes de MotionBinding y los límites de parada ya usados por el núcleo de navegación; los límites de velocidad vienen de RoverLimits. Son tolerancias de observación pasiva, no autorización para movimiento. No se ajustan después de ver los datos. Cualquier dato ausente, fresco insuficiente o identidad distinta da UNCONFIRMED, nunca cero ni PASS.

## Correlación de parámetros y firmware

rover_passive_parameters.collect implementa la lectura ROS por lotes, pero el future público no revela GID/instancia del servidor: por sí solo da READ_DIAGNOSTIC_SERVER_INSTANCE_UNVERIFIED. No existe todavía un colector MAVLink operativo de solo lectura ni una fuente que provea SampleInfo nativo por respuesta ROS para rellenar el contrato del nuevo correlador. El verificador offline tools/rover_parameter_correlation.py no hace I/O y exige ambas fuentes, igualdad exacta de valores incluyendo MAV_SYSID/DDS_USE_NS, proceso/lifecycle/boot/firmware comunes, socket dueño y SYSID/COMPID coherentes.

Por tanto la lectura cruzada aún necesita implementar y revisar un capturador pasivo MAVLink acotado y la asociación nativa del servidor o una fuente independiente de parámetros que pueda atribuirse concluyentemente al binario. Un .parm, EEPROM, heartbeat o nombre de namespace aislados no prueban por sí solos el proceso que responde ni su firmware. Sin ambas fuentes atribuibles, conservar valor observado como diagnóstico y no promoverlo a hecho operativo.

## Failsafe y primer metro

El ensayo de pérdida controlada de actualizaciones y el primer metro son scopes y autorizaciones diferentes. Continúan NO_GO: el failsafe del GCS, el timeout GUIDED, la distancia real de frenada y la parada independiente no se han medido con identidad binaria acreditada. El diseño completo y las envolventes teóricas están en 2026-11-06-rover-offline-safety-preparation.md; no se ejecuta un ensayo de movimiento en esta tarea.
