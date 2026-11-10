# Primera capa de control del rover — 2026-10-20

Estado actual (2026-10-21): IMPLEMENTADO_OFFLINE el núcleo, adaptador ROS 2 tipado y executor interno protegido. **Política operativa cerrada; sin herramienta MCP, CLI, armado ni autorización de movimiento.** La integración y los bloqueos restantes se detallan al final. La infraestructura `two_drones_rover` y su READY no validan movimiento. `two_drones` continúa siendo el perfil predeterminado; este incremento no modifica perfiles, gate, reservas, executor de drones ni tolerancias.

## Contratos respaldados por fuentes

El launch versionado [tfg_demo.launch.py](../simulation/ros2_gazebo/launch/tfg_demo.launch.py) incluye `rover1`/Wild Thumper, instancia SITL 2, SYSID 3. La correspondencia de infraestructura es `rover_01` → `v3`; no se añade al resolver de misiones de drones.

Las siguientes fuentes locales estaban disponibles para lectura en `/home/joelm/TFG/ardupilot_ros2_ws/src/`. Son fuentes externas al repositorio, no garantía de coincidencia binaria con un contenedor futuro:

| Fuente relativa a ese directorio | Contrato inspeccionado |
|---|---|
| `ardupilot/Rover/mode.h` | Rover HOLD=4, GUIDED=15; los números de ArduCopter no son intercambiables. |
| `ardupilot/Rover/AP_ExternalControl_Rover.cpp` | Velocidad longitudinal del cuerpo y tasa de giro; acepta control externo en GUIDED y armado. La implementación depende de las capacidades compiladas. |
| `ardupilot/libraries/AP_DDS/AP_DDS_ExternalControl.cpp` y `AP_DDS_Frames.h` | `TwistStamped`, frame `base_link` o `map`; conversión ROS FLU/ENU a convenciones internas. El núcleo usa exclusivamente `base_link`: x hacia delante en m/s, angular.z en rad/s según ROS. No realiza una segunda inversión del giro. |
| `ardupilot/libraries/AP_DDS/AP_DDS_Topic_Table.h` | `cmd_vel` lector BEST_EFFORT; no ofrece respuesta de aceptación/aplicación del autopiloto. |
| `ardupilot/libraries/AP_DDS/Idl/ardupilot_msgs/srv/ModeSwitch.idl` y `AP_DDS_Client.cpp` | Petición `uint8 mode`; respuesta `bool status`, `uint8 curr_mode`. Se comprueban ambos campos y su coherencia. |
| `ardupilot/libraries/AP_DDS/Idl/ardupilot_msgs/msg/Status.idl` | APM_ROVER=1, ARDUCOPTER=2; `armed`, `mode`, `flying` (incluye driving), `external_control`, secuencia de failsafes. `flying=false` no prueba contacto con suelo. |
| `ardupilot_gz/ardupilot_gz_bringup/config/wildthumper_bridge.yaml` | Puente GZ_TO_ROS `/model/{{ robot_name }}/odometry`, `gz.msgs.Odometry` → `nav_msgs/msg/Odometry`. |
| `ardupilot_sitl_models/Gazebo/models/wildthumper_with_lidar/model.sdf` | OdometryPublisher, `odom`/`base_link`, dimensiones 3. |

Los endpoints DDS esperados son `/ap/v3/status`, `/ap/v3/mode_switch` (`ardupilot_msgs/srv/ModeSwitch`) y `/ap/v3/cmd_vel` (`geometry_msgs/msg/TwistStamped`). El servicio de armado existente no se expone aquí. No se implementan TAKEOFF, LAND, navegación global, marcha atrás ni misiones rover.

La evidencia histórica de infraestructura se conserva en [prearm_diagnostic_gui_2026_10_20](../simulation/ros2_gazebo/results/prearm_diagnostic_gui_2026_10_20/808af58a-4831-48ce-a083-8772df3620d8/) y [two_drones_progress_gui_2026_10_20](../simulation/ros2_gazebo/results/two_drones_progress_gui_2026_10_20/f7f8c84f-1187-4c9f-939d-48931f8b548c/). La primera contiene respuestas Trigger de armabilidad; no demuestra aceptación de ModeSwitch ni cmd_vel. La segunda documenta la identidad/tipo de v3. Ninguna constituye una observación actual. El intervalo previo de 854,6 s no se introduce como espera fija ni como solución.

## Núcleo implementado

[rover_control.py](../tools/rover_control.py) fija la identidad `rover_01/v3`, verifica tipo Rover en cada observación y exige límites numéricos explícitos finitos. No hay valores de seguridad predeterminados. Una interfaz, tipo o unidad incorrectos se rechazan antes de construir controles efectivos.

- `request_mode(RoverMode...)`: lee identidad antes del servicio. Una respuesta positiva coherente confirma la petición, no la observación del modo ni la parada.
- `move_for(...)`: exige dos muestras de estado con marcas de fuente y recepción que progresen, GUIDED, armado, control externo y ausencia de failsafes. Publica una sola orden longitudinal/giro dentro de límites y duración de pared explícitos; no reintenta una publicación incierta. Tras cualquier intento de publicación, llama al procedimiento terrestre de parada. No arma ni cambia automáticamente a GUIDED.
- `stop()`: verifica identidad, intenta cero cuando consta GUIDED/armado y solicita HOLD. Si falla el envío de cero, todavía intenta HOLD dentro del presupuesto restante; conserva el fallo. HOLD rechazado, respuesta ausente, plazo agotado u observación insuficiente producen UNCONFIRMED. Un fallo de lectura anterior a cualquier control en `move_for` no provoca una recuperación innecesaria.

Cada operación conserva identidad, endpoint/tipo y payload cuando existe, timestamps UTC, duración monotónica de pared, timeout, retorno, respuesta cruda del adaptador, stdout/stderr y cadena de excepciones; los timeouts conservan streams parciales disponibles. Los resultados distinguen intento, confirmación de transporte, respuesta del servicio y observación. No representan tiempo simulado como duración de pared ni inventan muestras.

El adaptador debe imponer plazos reales en sus llamadas. El núcleo transmite presupuestos finitos y detecta una devolución tardía, pero **no puede interrumpir un adaptador Python que no retorna**. La duración solicitada tampoco garantiza duración física de movimiento ante pérdida del proceso. La parametrización efectiva de expiración de comandos de Rover no se ha verificado; no se asume como watchdog de seguridad. El futuro executor debe persistir la incertidumbre y conservar las reservas si desaparece.

## Qué significa «parada observada»

Cero publicado y HOLD aceptado no bastan. Para `STATIONARY_OBSERVED` se requieren dos muestras posteriores al comando, HOLD, no-driving, sin failsafes y velocidades lineal/angular bajo umbrales explícitos. El contrato del adaptador exige odometría independiente del simulador de `/model/rover1/odometry`, velocidades del cuerpo `base_link`, unidades m/s y rad/s, marcas de fuente progresivas y recepción monotónica reciente. Ese contrato se prueba con dobles; su disponibilidad, frames y asociación real al modelo deben verificarse antes de usar operativamente el adaptador. No es prueba de contacto con suelo ni de posición segura; no libera reservas.

**Limitación DDS comprobada en fuente:** en `AP_DDS_Client.cpp`, la marca de `twist/filtered` se actualiza aunque `get_velocity_NED` no renueve la velocidad; además, los componentes lineales se asignan ENU pese al header `base_link`. Por ello no se acepta ese topic como sustituto de odometría independiente. Recepción reciente y marcas crecientes tampoco autentican por sí solas la generación: el futuro adaptador debe suscribirse antes de ordenar, evitar datos retenidos, registrar recepción y fuente separadas y rechazar resets/rewinds o procedencia ambigua. No se comparan relojes simulados con UTC para fabricar antigüedad.

## Verificación y siguiente incremento

Los tests de [test_rover_control.py](../tests/test_rover_control.py) usan reloj y transporte dobles: identidad/interfaz/tipo incorrectos, unidades/tipos/límites, precondiciones, negativas/contradicciones/timeout, salida parcial, cero incierto, HOLD, observación ausente o insuficiente y bloqueo de misiones rover en executor/admisión existentes. La regresión de selección de drones se ejecuta por separado. Estos tests no validan un movimiento operativo ni autentican los campos de un adaptador real.

El núcleo inicial del 20 de octubre dejaba pendiente integrar executor/adaptador con reserva global y rover, identidad del worker, snapshots y resultados persistidos. La ampliación del 21 de octubre implementa ese recorrido offline, con los límites siguientes. Debe verificar los contratos efectivos del servicio/modo y la odometría, integrar parada con presupuesto independiente y demostrar offline exclusión con drones/lifecycle, pérdida de proceso y análisis de resultados. Mantener bloqueados los puntos públicos hasta completar ese conjunto; no basta añadir `v3` al resolver de drones.

La futura prueba requerirá autorización separada y límites de velocidad, giro, duración y zona explícitos; inspección actual/readiness, observación independiente disponible y un procedimiento de parada/reacción a pérdida de confirmación. Primero validar las lecturas y contratos sin armar ni mover. Ninguna operación de ese tipo está autorizada ni ejecutada por este incremento.

## Integración protegida offline — 2026-10-21

Se conservó el trabajo anterior. Se añadieron [rover_ros2_adapter.py](../tools/rover_ros2_adapter.py), [rover_ground_executor.py](../tools/rover_ground_executor.py) y [test_rover_ground_executor.py](../tests/test_rover_ground_executor.py). No se ejecutó ROS/Docker, ni se crearon jobs o reservas reales. El adjunto de la conversación anterior fue legible; se usó como contexto, no como prueba de ejecución de comandos ni disponibilidad de odometría.

### Adaptador y contrato de parada

`NativeRos2Session` usa imports ROS diferidos, mensajes `ardupilot_msgs/msg/Status`, `nav_msgs/msg/Odometry`, `geometry_msgs/msg/TwistStamped` y servicio `ardupilot_msgs/srv/ModeSwitch`. No ejecuta shells, Docker ni CLI ROS. No se instancia automáticamente: requerirá un proceso en un entorno ROS compatible, cuyo despliegue no se incorpora aquí.

`Ros2RoverAdapter` exige autoridad vigente `v3` en lecturas y controles. Verifica tipos descubiertos, servicio ModeSwitch disponible, suscriptor de velocidad, publicador único de Status y GID exacto del publicador de odometría. Una lista cerrada admite sólo las peticiones Rover HOLD/GUIDED y velocidad `base_link` en los ejes previstos; rechaza endpoints de drones, LAND y campos adicionales. La sesión nativa vuelve a validar la lista y autoridad antes del envío. No ofrece armado ni desarmado.

Las suscripciones son nuevas, BEST_EFFORT y VOLATILE. Cada lectura requiere mensajes recibidos después de comenzar esa lectura y fuentes que progresen; un reloj congelado o rebobinado bloquea. Se conservan separados el timestamp de origen y la recepción monotónica del host. El GID recibido se contrasta con el esperado en cada observación. Un timeout de lectura conserva las muestras parciales realmente recibidas, sin fabricar el stream ausente. La respuesta de ModeSwitch se interpreta por sus campos; la publicación de velocidad no tiene respuesta de aplicación. En rclpy no hay proceso CLI ni código de salida: `return_code=null` y `native_api_completed=true` sólo indican devolución local de la API, sin inventar un retorno de proceso igual a cero. Cancelar un future local tras timeout no cancela los efectos posibles de una petición enviada.

**Fuente independiente esperada, todavía no acreditada operativamente:**

1. `tfg_demo.launch.py` pasa namespace y robot_name `rover1` al launch Wild Thumper.
2. `wildthumper.launch.py` proporciona `wildthumper_bridge.yaml`; `robot.launch.py` sustituye robot/world en un YAML temporal y pasa ese archivo como `config_file` a `ros_gz_bridge/parameter_bridge` en el namespace del robot.
3. El YAML declara GZ `/model/{{ robot_name }}/odometry` → ROS relativo `odometry`, tipo `nav_msgs/msg/Odometry`. Por ello `/rover1/odometry` es **esperado**, no observado en este trabajo.
4. El SDF declara OdometryPublisher con `odom`, `base_link` y dimensiones 3. Se exige `child_frame_id=base_link` y velocidades de ese cuerpo, en m/s y rad/s. No se sustituye con el topic DDS `twist/filtered`.

`MotionBinding` es un contrato para un futuro colector de sólo lectura: hashes de identidad del entorno y configuración activa del bridge, GID del publicador y topics/child frame exactos. Su comprobación actual valida estructura/coherencia; **no obtiene esos artefactos, no acredita su vigencia ni autentica su origen**. El descubrimiento ROS por sí solo no demuestra la asociación con el modelo Gazebo. No se ha implementado un productor/verificador operativo de esa acreditación. Los tests suministran una binding sintética explícita, sin valor como evidencia real.

Por ese motivo `OPERATIONAL_ROVER_ENABLED=False` cierra admisión y worker antes de crear estado o inicializar un backend. No existe variable de entorno, opción MCP/CLI ni booleano de llamada para habilitarlo. Los tests cambian esa constante únicamente en memoria y en proyectos temporales. No debe cambiarse para probar movimiento hasta resolver los requisitos finales.

### Executor interno, persistencia y exclusión

Este incremento ejecuta un **ensayo acotado de velocidad/giro/duración**, no una ruta ni las misiones de waypoints del rover. Exige `MissionDefinition` con identidad `rover_01`, tipo `ugv`, autopiloto `ArduPilot` y un request `ROVER_BOUNDED_CONTROL` con todos los límites explícitos. Reutiliza la validación determinista existente, sin exportar QGC ni modificarla; además verifica límites del ensayo, velocidad frente al crucero declarado y presupuesto declarado de batería. La validación de la misión no sustituye las comprobaciones terrestres ni configura los failsafes del autopiloto.

La admisión interna conserva bytes exactos de `mission.json`, `request.json`, SHA-256, alcance de autorización declarado y `job.json` mediante escritura durable. La autorización liga hash de misión y fingerprint del request; se registra como `UNVERIFIED_CALLER_DECLARATION`, **no confirmación humana autenticada**. El hash combinado de la reserva incluye misión, request y declaración. Cambios de snapshots o declaración bloquean al worker. El token de lanzamiento sólo se devuelve en la primera admisión; una respuesta perdida o clave repetida no emite otro token ni reanuda nada.

No hay herramienta MCP, CLI, Popen ni worker detached nuevo. `run_ground_worker` es la función interna de una sola ejecución: reclama el token una vez, persiste PID/start_ticks/boot_id antes del backend y toma el `execution_scope` global existente. Revalida snapshots y validación determinista, y exige readiness actual de `two_drones_rover`. Sólo entonces comprueba transporte y observación independiente. El núcleo exige **antes de publicar** dos muestras recientes, progresivas, de identidad correcta, sin failsafes, inicialmente inmóviles, y disponibilidad de la odometría necesaria para comprobar parada. No arma ni pone automáticamente GUIDED; un rover desarmado queda sin movimiento.

El registro [vehicle_execution_lock.py](../tools/vehicle_execution_lock.py) incluye `v3.json`/`rover_01` en la misma exclusión global, conservando `v1.execution.lock`, `registry.lock` y comprobación de identidad del propietario. Las entradas de drones conservan su resolver y rechazo de rover. Las secuencias siguen limitadas a v1/v2, pero detectan v3 durante admisión e intervalos entre hijos. Lifecycle no puede actuar con una reserva rover activa o incierta. La reconciliación de drones reconoce `v3.json` y bloquea explícitamente sin aplicar criterios de LAND/aterrizaje ni retirarla. La ausencia de v3 conserva los contratos de snapshots legacy; su aparición posterior bloquea la recaptura. No se añade un desbloqueo rover ni se modifican informes históricos.

Se persiste intención antes de cada control y respuesta después; al terminar, informe y hashes antes de considerar una retirada normal de reserva. La consulta interna es de sólo lectura, no crea mutex/job ni reanuda. Worker desaparecido/PID reciclado, informe sin cierre coherente de reserva, fallo de persistencia o parada incierta mantienen incertidumbre y restricciones. Una consulta no escribe `UNCONFIRMED` sobre los originales: lo deriva cuando corresponde.

Resultados separados:

| Dato | Significado y límite |
|---|---|
| `control_intent` | Intención durable previa al transporte; no prueba recepción. Tras una interrupción puede desconocerse si llegó a enviarse. |
| `Reply.sent`, retorno local | Petición/publicación enviada por el transporte; no prueba aplicación de cmd_vel. |
| Respuesta ModeSwitch | Aceptación/negativa y modo comunicado; no prueba velocidad cero. |
| `motion_application_confirmed=false` | El topic no tiene confirmación de aplicación del autopiloto. |
| `movement_observed=NOT_MEASURED` | Este ensayo no mide movimiento durante el intervalo; no afirma distancia, ruta completada ni que el rover se desplazara. |
| `STATIONARY_OBSERVED` / `STOP_OBSERVED` | Dos observaciones posteriores consistentes bajo los umbrales explícitos; no `PASSED` de una misión ni contacto con suelo. |
| Reserva retenida | Parada no confirmada, efectos inciertos o rover aún armado; requiere revisión separada. |

Sólo se retira normalmente la reserva si no hubo intento de control o si la parada se observó con **ambas muestras desarmadas y no-driving**, además de persistencia final correcta. El executor no desarma: un HOLD correcto con rover todavía armado conserva `UNCONFIRMED` en la restricción, aunque el informe diga parada observada. La destrucción de la sesión no equivale a detener/desarmar el vehículo. Fallos de almacenamiento pueden impedir escribir la explicación final, pero no autorizan liberar ni reiniciar el worker.

La exclusión cubre las entradas actualizadas del proyecto; no controla clientes ROS/QGC externos, publicadores maliciosos ni otra copia antigua del código. Los presupuestos de pared no garantizan parada física tras pérdida del proceso. No se cambian timeouts de infraestructura ni se añade una espera de 854,6 s.

### Requisitos pendientes antes de una prueba terrestre

1. **Primero sólo lectura:** con autorización futura de infraestructura, verificar binarios/contratos efectivos, configuración temporal activa del bridge y su asociación con `rover1`; conservar identidad exacta del entorno, hash de esa configuración y GID. Recoger odometría y Status independientes, headers, child frame, unidades y recepción/progresión sin armar ni mover. Si falta el stream o la asociación es ambigua, detener el procedimiento.
2. Implementar y probar el colector/verificador que produzca esa acreditación, su caducidad y revalidación bajo autoridad vigente. Actualmente la estructura `MotionBinding` no resuelve ese trabajo; no rellenarla con valores supuestos ni históricos.
3. Revisar el despliegue de la sesión en el entorno ROS compatible y la entrada de worker de una sola ejecución. Si debe sobrevivir a desconexión, integrar el lanzamiento detached/token/logs con el mecanismo existente antes de exponerlo; no está incluido en este incremento.
4. Definir autorización explícita verificable para el ensayo exacto, zona terrestre, límites y reacción ante falta de confirmación; resolver el armado/desarmado protegido y su diagnóstico. El executor actual no los ofrece. Establecer el comportamiento efectivo ante pérdida del proceso/control sin asumir un watchdog por analogía con ArduCopter.
5. Añadir reconciliación rover específica y auditada antes de permitir recuperación de una reserva incierta; hoy la vía de drones queda bloqueada. Después, revisar la política cerrada en un incremento explícito. No basta con cambiar la constante.
6. Sólo entonces autorizar por separado un ensayo terrestre acotado, con readiness actual, reservas y origen acreditados, confirmación visual independiente de readiness y parada/desarmado observados. Ni este documento ni los tests autorizan ese ensayo.

### Comprobaciones realizadas en el cierre offline

El 2026-10-21 pasaron **337 tests seleccionados** de integración/regresión (rover, selección de drones, reservas, jobs, lifecycle, secuencias, reconciliación y retiro legacy). Después se añadieron tres casos sobre la devolución nativa sin código de proceso: el comando `.venv/bin/python -m pytest -q tests/test_rover_control.py tests/test_rover_ground_executor.py` pasó **103 tests**. No son dos conjuntos disjuntos ni la suite global. También se verificaron sintaxis AST de los siete archivos Python del incremento, enlaces locales y whitespace de los ocho archivos, incluidos los nuevos. Estas comprobaciones usan dobles y no acreditan transporte, odometría o movimiento reales.

## Worker pasivo e identidad del entorno — 2026-10-21

Se conecta un **worker de identidad de sólo lectura**, distinto del executor terrestre. La conexión está implementada y probada con dobles; no se ha desplegado ni arrancado en un contenedor real durante este trabajo. La política operativa del rover sigue cerrada y las misiones rover continúan rechazadas.

En un futuro `start` autorizado de `two_drones_rover`, el lifecycle recoge metadatos acotados mediante el inspector existente, bajo los mismos mutex de lifecycle/ejecución. Docker inaccesible o identidad ambigua bloquean antes de llamar al backend. Se guarda `rover_environment_reference.json` junto al log de esa operación con engine/container ID, creación, imagen, estado **previo** al arranque, UUID de lifecycle y hash del launch del host. No se presenta el estado previo como observación posterior al arranque ni como prueba de continuidad histórica. El backend transmite esa referencia sin eval, copia los dos módulos pasivos y el supervisor comprueba que el launch instalado coincide con el hash esperado.

Sólo para ese perfil, después de registrar el proceso launch, el supervisor crea una vez `/tmp/tfg_rover_identity/<lifecycle_id>/context.json` y arranca `python3 /tmp/tfg_rover_identity_worker.py --context <ruta>`. Registra PID/start_ticks del worker junto al launch, con el marcador de propiedad del proyecto, y utiliza la limpieza existente con protección de identidad. El worker tiene log separado `worker.log` y publica `worker.json` durable, como máximo una vez por segundo. Un contexto existente no se sobrescribe ni relanza. `two_drones` conserva su camino de arranque y no carga estos módulos.

[rover_identity_worker.py](../tools/rover_identity_worker.py) sólo crea suscripciones VOLATILE/BEST_EFFORT a `/ap/v3/status` y `/rover1/odometry` y consulta información de publicadores. No crea clientes de servicios, publishers ni órdenes. Conserva mensajes, GID del emisor recibido, namespace/nombre observado del publicador, cantidad de publicadores, recepción monotónica y progresión del timestamp de fuente. La ausencia de un stream queda ausente; no se rellena. Retroceso/congelación de fuente o cambio de GID conservan el bloqueo durante esa ejecución del observador. La salida o fallo del proceso deja un registro bloqueado; no hay respawn ni recuperación automática.

[rover_environment_identity.py](../tools/rover_environment_identity.py) contrasta referencia y captura actual: UUID/hash del contexto, identidad de engine/contenedor, PID/start_ticks/boot_id de launch y worker, interfaz/tipo/frame, fuente única y antigüedad de muestras. Un PID de contenedor nunca se consulta como si fuera un PID del host. El boot_id identifica el dominio de procesos, **no** el engine Docker ni su reinicio. Las edades deben calcularse en el dominio monotónico correspondiente: edad de heartbeat dentro del contenedor, edad del bundle desde su recepción en el host, y edad de muestra calculada por el observador. Se suman esas duraciones de pared para el límite provisional de 3 s; no se comparan timestamps ROS/simulados con reloj del host. Recepción reciente/progresión no prueban por sí solas antigüedad absoluta de generación.

La evaluación puede devolver `identity_consistent=true` con identidad y muestras coherentes, pero mantiene **`status=BLOCKED`, `source_association_verified=false`, `movement_authorized=false`**. No existe un campo `verified=true` que el caller pueda activar para obtener permiso. Las consultas no crean workers, reservas ni ficheros y no liberan restricciones ante ausencia, caducidad o pérdida del worker.

El adaptador nativo exige ahora esta barrera además de `MotionBinding`: `probe`, lecturas de control y controles no admiten únicamente un binding con hashes bien formados. Sin guard/colector actual bloquean; incluso una captura consistente permanece bloqueada por la asociación todavía no acreditada. Los tests previos de mecánica del transporte nativo aíslan explícitamente esa barrera con un doble: no son pruebas de acreditación. El executor terrestre sigue sin entrada MCP/CLI ni lanzamiento operativo por defecto. El worker pasivo no toma una reserva de movimiento; una reserva terrestre `UNCONFIRMED` conserva las barreras existentes de lifecycle/reconciliación.

### Qué sigue sin poder comprobarse offline

El launch y `AP_DDS_Client.cpp` respaldan una expectativa: instancia 2/sysid 3 para Rover, namespace DDS `v<sysid>` cuando `DDS_USE_NS` está activo, client key XRCE derivada de SYSID y bridge `rover1`. `Status` contiene tipo/modo/armed/flying, **no SYSID ni identificación de la sesión XRCE**. Un topic llamado `/ap/v3/status`, aunque emita tipo Rover, no demuestra por sí solo esa cadena. Tampoco se ha leído el YAML temporal activo del bridge del contenedor ni la relación de su proceso/GID con el modelo. El hash del launch padre no acredita la configuración instalada transitiva ni los parámetros efectivos de SITL.

Por ello falta un colector operativo de sólo lectura que revalide esas relaciones y aporte el bundle actual al guard. No se implementa aquí una aceptación de JSON arbitrario como acreditación ni una vía para habilitar movimiento. Tampoco se da por existente el nuevo worker en una simulación arrancada con una versión anterior.

### Siguiente comprobación operativa, exclusivamente de lectura

En una inspección futura autorizada, sin arrancar/reiniciar, armar ni mover:

1. Consultar identidad/contexto Docker y estado actual, y contrastar engine ID, container ID, imagen y tiempos con la referencia conservada. Si no está ejecutándose o fue sustituido, informar BLOCKED; no arrancarlo para completar la prueba.
2. Buscar el contexto, `worker.json` y `worker.log` de ese UUID; contrastar en el **proc del contenedor** PID/start_ticks/boot_id de launch y worker. Si no existe worker de esta versión, registrar ausencia y detener el paso. Su despliegue requeriría otro arranque expresamente autorizado; no se inicia desde una consulta.
3. Recoger una ventana acotada de ambos streams, sus tipos/GIDs, namespaces y frames; conservar recepción y timestamps de origen separados, procesos propietarios del bridge, parámetros `config_file` de ese bridge y bytes/hash del YAML temporal activo. No basta el YAML del repositorio.
4. Descubrir si el binario ofrece lectura de parámetros `rcl_interfaces/srv/GetParameters`: `AP_DDS_Service_Table.h` la condiciona a `AP_DDS_PARAMETER_SERVER_ENABLED`. Usar sólo el nombre y esquema realmente descubiertos para leer el SYSID efectivo y `DDS_USE_NS`, con timeout; si no existe, no inventar un endpoint ni cambiar la configuración. Contrastar con argv/instancia/proceso ardurover y, si existen, logs actuales del agente XRCE que permitan correlacionar su sesión/participant con esos GIDs. Un retorno vacío o datos insuficientes mantienen la asociación desconocida.

La primera inspección puede terminar legítimamente en BLOCKED. Si esos registros no permiten correlacionar la sesión, hará falta instrumentación de lectura en otro incremento; no se resuelve suponiendo el binding por nombres. Obtener esta evidencia no autoriza controles ni cambia la política del executor.

Comprobaciones offline de este paso: 155 tests de identidad/executor/perfiles/lifecycle pasados; 152 tests de identidad/control/reservas/exclusión pasados; tras reforzar el contraste del hash instalado, 71 tests de identidad y executor pasados. Los conjuntos se solapan y no representan la suite global. Se comprobó sintaxis de los ocho archivos Python afectados, Bash del backend, enlaces locales y whitespace de los diez archivos del incremento, incluidos los nuevos. Los tests de ROS usan módulos/nodos simulados y los de backend ejecutan dobles de Docker en proyectos temporales; no se arrancó ningún proceso operativo.
