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

Las suscripciones son nuevas, BEST_EFFORT y VOLATILE. Cada lectura requiere mensajes recibidos después de comenzar esa lectura y fuentes que progresen; un reloj congelado o rebobinado bloquea. Se conservan separados el timestamp de origen y la recepción monotónica del host. El contrato del adaptador exige contrastar el GID por muestra con el esperado en cada observación. La ruta nativa actual sólo recibe el mensaje y almacena ese GID como `None`, por lo que no puede satisfacer el contrato y mantiene el bloqueo; los GID descubiertos en el grafo no sustituyen esa atribución. Un timeout de lectura conserva las muestras parciales realmente recibidas, sin fabricar el stream ausente. La respuesta de ModeSwitch se interpreta por sus campos; la publicación de velocidad no tiene respuesta de aplicación. En rclpy no hay proceso CLI ni código de salida: `return_code=null` y `native_api_completed=true` sólo indican devolución local de la API, sin inventar un retorno de proceso igual a cero. Cancelar un future local tras timeout no cancela los efectos posibles de una petición enviada.

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

[rover_identity_worker.py](../tools/rover_identity_worker.py) sólo crea suscripciones VOLATILE/BEST_EFFORT a `/ap/v3/status` y `/rover1/odometry` y consulta información de publicadores. No crea clientes de servicios, publishers ni órdenes. Conserva mensajes, recepción monotónica y progresión de sus timestamps de cabecera. Los callbacks actuales reciben sólo el mensaje: `publisher_gid`, `publisher_namespace` y `publisher_name` por muestra quedan como `None`; `source_progressing` permanece falso. El descubrimiento conserva por separado la cantidad de publicadores y los candidatos del grafo con sus GID/namespaces/nombres, sin atribuirles una muestra concreta, aunque haya un único candidato. La ausencia de un stream queda ausente; no se rellena. Un timestamp de cabecera congelado o rebobinado invalida su progresión durante esa ejecución; sin GID por muestra no se detectan cambios de publicador. La verificación de identidad permanece bloqueada. La salida o fallo del proceso deja un registro bloqueado; no hay respawn ni recuperación automática.

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


### Metadatos por muestra en la versión local de rclpy — 2026-10-21

Revisión offline posterior al fallo de firma del worker. Las fuentes preservadas
[subscription.py](../simulation/ros2_gazebo/results/rover_identity_opening_2026_10_21/5a61e26f-6aea-4164-bac7-73cec5ab3d41/deployed-sources/03-subscription.py),
[executors.py](../simulation/ros2_gazebo/results/rover_identity_opening_2026_10_21/5a61e26f-6aea-4164-bac7-73cec5ab3d41/deployed-sources/04-executors.py)
y [node.py](../simulation/ros2_gazebo/results/rover_identity_opening_2026_10_21/5a61e26f-6aea-4164-bac7-73cec5ab3d41/deployed-sources/05-node.py)
son copias del entorno inspeccionado, no una consulta actual al contenedor.
`Node.create_subscription` declara `Callable[[MsgType], None]` (línea 1326).
`Executor._take_subscription` llama a `sub.handle.take_message(sub.msg_type,
sub.raw)` y devuelve únicamente `msg_info[0]` (líneas 398–403);
`_execute_subscription` llama a `await_or_execute(sub.callback, msg)`
(líneas 405–407). `raw=True` cambia la representación a bytes; no añade
MessageInfo al callback. SubscriptionEventCallbacks se entrega a los manejadores
de eventos QoS, no al callback de cada muestra.

El handle nativo expone `take_message`, pero su implementación compilada/fuente
no está disponible en las copias locales revisadas. No se ha acreditado el
contenido de los demás elementos de su retorno, un campo publisher_gid ni un
contrato seguro para consumirlo directamente con un executor alternativo.
La existencia de `msg_info` no demuestra ninguna de esas capacidades. No se
concluye que todas las versiones de Humble o todas las APIs ROS 2 carezcan de
metadatos: la conclusión se limita a esta implementación conservada y su camino
público de callback. No se ejecutó ROS ni se consultaron versiones remotas.

Los callbacks actuales de Status y odometría del worker pasivo y de
`NativeRos2Session` reciben sólo el mensaje y conservan GID por muestra como
`None`. En el worker, los endpoints del grafo son candidatos separados, incluso
si sólo hay uno; la progresión de cabecera no acredita progresión de una fuente
identificada. La sección del worker y el contrato del adaptador describen ahora este mismo
límite: no se conserva un GID recibido ni se detectan cambios de GID por muestra. La
regresión con módulos ROS simulados comprueba ambos callbacks del adaptador;
no acredita transporte real. Las barreras de identidad y movimiento permanecen
cerradas.

Para avanzar hace falta una fuente comprobable de atribución por muestra: por
ejemplo, inspeccionar en una futura recogida autorizada de sólo lectura el
código/contrato nativo exacto de `take_message` y sus metadatos; si no ofrece GID,
será necesario un receptor compatible cuya API documentada y versión instalada
entreguen mensaje y metadatos juntos, con pruebas propias antes de integrarlo.
No se propone cambiar dependencias ni implementar ese receptor en este paso.
El GID por sí solo tampoco resuelve la cadena: siguen pendientes la correlación
actual de participant/publicador con sesión XRCE, SYSID efectivo y DDS_USE_NS,
proceso/instancia SITL v3, y proceso/configuración YAML activa del bridge con el
modelo rover1. Status no aporta SYSID ni identidad XRCE; nombres de topic,
namespace, unicidad del grafo y hashes bien formados no sustituyen esa evidencia.


### Contraste con fuentes oficiales Humble — 2026-10-21

El backend carga `/opt/ros/humble/setup.bash`; el índice de fuentes preservadas
identifica módulos instalados bajo `/opt/ros/humble/.../python3.10/`. Esto acredita
la distribución usada, no la versión Debian/commit exacto de rclpy ni su RMW
activo. No se encontró un inventario local que fije esos últimos valores.

La referencia upstream identificable revisada es **rclpy 3.3.21**, de la línea
Humble, sin atribuir esa versión al binario instalado:
[subscription.cpp, tag 3.3.21](https://github.com/ros2/rclpy/blob/3.3.21/rclpy/src/rclpy/subscription.cpp)
recibe `rmw_message_info_t` mediante `rcl_take` (o la variante serializada), pero
su retorno Python sólo contiene mensaje y diccionario con `source_timestamp` y
`received_timestamp`. No exporta `publisher_gid`.
[Executor, mismo tag](https://github.com/ros2/rclpy/blob/3.3.21/rclpy/rclpy/executors.py)
selecciona el primer elemento y llama al callback con el mensaje. Ese camino
coincide con las fuentes Python conservadas. No hay aquí una API pública
MessageInfo con GID por muestra demostrada para el runtime del proyecto; no se
extrapolan contratos de Rolling, Iron u otra distribución.

Debajo de Python, [rcl Humble](https://github.com/ros2/rcl/blob/humble/rcl/src/rcl/subscription.c)
delega `rcl_take` en `rmw_take_with_info`, pasando la estructura de información;
la recepción serializada tiene su variante correspondiente.
[rmw Humble, types.h](https://github.com/ros2/rmw/blob/humble/rmw/include/rmw/types.h)
define `publisher_gid` en `rmw_message_info_t`: la generación, posible reutilización
y colisiones dependen del RMW concreto. Esas referencias de rama son móviles,
no inventarios del entorno ni garantía de unicidad histórica. No se ha
identificado el RMW efectivo, sus versiones ni su implementación de take/GID.

La laguna local nativa sigue siendo el `subscription.cpp` y artefacto compilado
correspondientes exactamente al paquete instalado (incluidos parches), además
del inventario rcl/rmw/RMW. La fuente oficial ahora revisada demuestra que en
3.3.21 ni siquiera consumir privadamente el segundo elemento recuperaría un GID.
Se mantienen los callbacks de un argumento, GID `None`, identidad no verificada
y movimiento bloqueado. Una futura alternativa exige acreditar un receptor con
API pública por muestra y contrato de GID en la versión concreta; después probar
atribución con varios publicadores, ausencia/ambigüedad y caducidad, sin sustituir
la correlación XRCE/SYSID/SITL/bridge/modelo pendiente. No se propone adaptar el
handle privado, cambiar dependencias o activar controles en esta investigación.


### Colector de inventario offline — 2026-10-21

`tools/rover_identity_inventory.py` prepara el informe mediante un contrato
`InventoryReader` de sólo lectura inyectado explícitamente. No selecciona un
transporte real, no añade CLI/MCP/shell ni crea workers. Reutiliza la separación
entre recogida y evaluación: no modifica `RoverEnvironmentGuard` ni produce un
MotionBinding. Las interfaces existentes de lifecycle inspeccionan el entorno,
pero no reúnen el inventario ROS/DDS/bridge; el adaptador de control está bloqueado
y no se utiliza como atajo de inspección.

El lector futuro debe aportar entorno, versiones ROS/rclpy/rcl/rmw/RMW efectivo,
procesos con identidad/argv, candidatos DDS con procedencia, configuración efectiva
del bridge y descubrimiento de servicios. Cada Reading incluye fuente y momento
de observación; el informe agrega recepción UTC/monotónica, duración y presupuesto
por lectura. Los valores anidados de inventario comparten la procedencia de su
Reading: si se obtienen en observaciones distintas, el lector debe conservar sus
fuentes/tiempos individuales dentro del valor. Datos ausentes/no atribuibles deben
entregarse como None, no como expectativas. El hash SHA-256 del bridge se calcula
sobre los bytes aportados con su ruta absoluta; no prueba por sí mismo que el
proceso los esté usando. Esa asociación debe figurar en la procedencia recogida.

Sólo tras descubrir un único servicio `/ap/v3/` de tipo exacto
`rcl_interfaces/srv/GetParameters` se permite solicitar SYSID_THISMAV y DDS_USE_NS;
no se supone un nombre de servicio ni se usa SetParameters. El lector debe
interpretar el contrato público, marcar parámetros ausentes como UNKNOWN y
respetar el timeout finito. El colector detecta devoluciones tardías, pero no
puede interrumpir un lector síncrono que incumpla el presupuesto. No hay lector
operativo acreditado aún: los tests usan dobles y no prueban acceso real.

Errores de una fuente conservan las demás observaciones; no se reintenta. La
salida permanece BLOCKED, GID por muestra None, source_association_verified=false
y movement_authorized=false, incluso con inventario completo. Candidatos del
grafo, recepción reciente e inventario coherente no acreditan la cadena de la
muestra hacia publicador, XRCE/SYSID, SITL v3 y bridge/modelo. No se guarda ningún
artefacto automáticamente ni se alteran reservas. Una ejecución futura del lector
real requiere autorización independiente; este incremento no la concede.


### Conexión pública limitada al grafo — 2026-10-21

`collect_node_inventory(node)` conecta el colector con
`RosGraphInventoryReader` sobre un nodo **ya existente**, usando únicamente
`get_publishers_info_by_topic` y `get_service_names_and_types`, APIs públicas ya
utilizadas por el worker/adaptador. No crea nodo/contexto, no hace spin, no llama
a servicios, no publica ni persiste. Tampoco se invoca automáticamente desde el
worker; usarlo en el entorno real exige una ejecución autorizada posterior.

Conserva candidatos por topic con fuente y momento de observación y servicios
con sus tipos. El tiempo de consulta del grafo no acredita cuándo se generó una
muestra ni si el descubrimiento refleja un proceso todavía vivo. Los candidatos
no son atribución por mensaje: el GID por muestra continúa None y la salida
BLOCKED. Entorno, versiones, procesos/argv, archivo efectivo del bridge y valores
de parámetros permanecen UNKNOWN en este lector. Aunque descubra GetParameters,
no existe un cliente de lectura de parámetros en esta ruta; no se reutiliza el
cliente ModeSwitch del adaptador. El inspector de entorno existente usa Docker
CLI y no se conecta por esta vía. No se añaden shell, exec, CLI ROS ni MCP.

Las llamadas síncronas de descubrimiento conservan la limitación del colector:
se rechaza una devolución fuera del presupuesto, pero no se puede interrumpir la
API si se bloquea. Las pruebas usan nodos falsos sin APIs de control y no prueban
la disponibilidad de ningún dato real. La conexión no modifica la barrera ni
resuelve la asociación pendiente XRCE/SYSID/SITL v3/bridge/modelo.


### Alternativa rclcpp: evidencia local y bloqueo de compatibilidad — 2026-10-21

Inspección offline, sin ROS, Docker, builds ni red. En el workspace hermano
`/home/joelm/TFG/ardupilot_ros2_ws` existen estas fuentes de consumidor:

- `src/ros_gz/ros_gz_bridge/src/factory.hpp:115–136` declara un callback
  `std::function<void(std::shared_ptr<const ROS_T>, const rclcpp::MessageInfo &)>`
  para `Node::create_subscription`. Obtiene el GID de **esa recepción** mediante
  `msg_info.get_rmw_message_info().publisher_gid`; después lo compara con los
  candidatos del grafo para filtrar bucles. La atribución no procede del grafo.
  SHA-256: `da15f04887c2393c69851b1e9579c3231e8a2d084cb8505e18a0ec66f46c4d31`.
- `src/ros_gz/ros_gz_bridge/test/test_gid_filtering.cpp:139–160` usa ese contrato
  con dos publicadores. Es código de test disponible, **no un test ejecutado en
  esta revisión ni prueba de funcionamiento del rover**.
  SHA-256: `ed019ff4eda1959ed614890db14ea407b2ab1baff67860f6582b1acfeb71c5c4`.
- `build/ros_gz_bridge/CMakeCache.txt:566–608` referencia rcl/rclcpp/rmw en
  `/opt/ros/humble` y paquetes Fast RTPS. SHA-256:
  `efa603ebfd996df38358b4f5b55f8e539e43629ba960bed4793877a08d554f53`.
  `CMakeFiles/ros_gz_bridge.dir/flags.make:5` contiene
  `DEFAULT_RMW_IMPLEMENTATION=rmw_fastrtps_cpp`. Es una configuración de build
  conservada, no el identificador RMW del proceso actual. No demuestra que esas
  fuentes sean los bytes compilados/desplegados ni que un override no cambie RMW.

A diferencia del callback de rclpy conservado, rclcpp ofrece así una vía pública
candidata con mensaje y metadatos juntos. La alternativa inferior rcl/rmw requiere
contrastar `rcl_take`/`rmw_take_with_info` y `rmw_message_info_t` con los headers y
la implementación exactos; no se adapta el handle privado de rclpy. En los árboles
locales inspeccionados (`/opt`, `/usr/include` y el workspace hermano) no están los
headers nativos `rclcpp/message_info.hpp`, suscripción y rmw/types.h correspondientes
al entorno. `/opt/ros/humble` no está disponible en este host. El repositorio hermano
rechazó consultas Git por ownership dudoso; no se cambió safe.directory ni ninguna
configuración. Los hashes anteriores identifican los archivos leídos, no su commit
upstream o la revisión instalada.

**Resultado: BLOCKED; no se implementa prototipo conectado ni se declara
compatibilidad instalada.** El mínimo para resolver este bloqueo es obtener, en una
recogida futura autorizada de sólo lectura, versiones/paquetes y headers nativos
exactos de rclcpp/rcl/rmw/RMW del entorno, identidad del RMW cargado y procedencia
del bridge instalado. Debe comprobarse el contrato MessageInfo, GID/tamaño e
identificador de implementación y el comportamiento inter/intra-proceso aplicable.
Sólo después procede preparar un suscriptor C++ pasivo aislado, sin controles ni
cambios de gates, con pruebas de dos publicadores sobre el mismo topic, metadatos
ausentes/no válidos, recepción y frescura separadas y ausencia de atribución por
unicidad del grafo. Un doble sin esos headers no demostraría ABI ni compatibilidad.
Incluso un GID válido por muestra no acredita por sí solo XRCE/SYSID/SITL v3 ni
bridge/modelo: esas correlaciones siguen pendientes. Los colectores Python actuales
conservan GID None, identidad no verificada y movimiento bloqueado.


### Prototipo rclcpp pasivo aislado — 2026-10-21

[Observer C++](../tools/rover_passive_rclcpp/observer.hpp) y
[método/límites](../tools/rover_passive_rclcpp/README.md): componente sin ejecutable,
CLI/MCP ni conexión a lifecycle o control. Usa el callback público con MessageInfo
respaldado por los headers instalados observados (rclcpp 16.0.19, rmw 6.1.3).
Copia GID e identificador RMW por muestra, conservando aparte candidatos del grafo,
recepción system/steady y mensaje tipado con timestamp/frame originales. Un GID
cero, identificador ausente o recepción intra-proceso no se acredita. La atribución
final permanece ausente incluso con GID observado, sin comparación temporal entre
dominios ni inferencia de procedencia por nombre/unicidad del topic.

Siempre devuelve registros BLOCKED, sin identidad verificada ni autoridad de
movimiento. El worker/adaptador Python no se modifican y su GID sigue None.
Las pruebas C++17 compilan únicamente contra dobles de headers/nodo; no son un
build ROS ni una prueba de ABI/DDS. Falta prueba pasiva autorizada con múltiples
publicadores y RMW efectivo identificado, además de procedencia binaria/YAML del
bridge y correlación XRCE/SYSID/SITL v3/bridge/modelo. No se creó ningún receptor
operativo ni se modificaron gates o reservas.


### Comprobación real de compilación, sin ejecución — 2026-10-21

El [probe compile_contract.cpp](../tools/rover_passive_rclcpp/compile_contract.cpp)
y el observador completo pasaron `c++ -std=c++17 -Wall -Wextra -Wpedantic -Werror
-fsyntax-only` contra los headers y mensajes realmente instalados en el contenedor
ya activo e identificado. Resultado 0, stdout/stderr vacíos; fuente por stdin,
sin binario, link, nodo, spin, servicios o ejecución del observador. El
[README del prototipo](../tools/rover_passive_rclcpp/README.md) conserva la receta
exacta de compilación y sus límites. Se comprobaron las dos suscripciones públicas,
MessageInfo/get_rmw_message_info/publisher_gid/from_intra_process y los tipos
Status/Odometry. Esto supera el bloqueo de compatibilidad de headers descrito en
la investigación previa, pero no acredita ABI, RMW cargado, recepción de muestras
ni asociación XRCE/SITL/bridge/modelo. Identidad y movimiento permanecen BLOCKED.


### Fuente del colector rclcpp aislado — 2026-10-21

Preparados [collector.cpp y contrato](../tools/rover_passive_rclcpp/COLLECTOR.md),
sin ejecutar el programa ni integrarlo en lifecycle, worker Python, control,
misiones o MCP. Límites explícitos de muestras/duración, output nuevo absoluto
0600 en padre privado, JSONL con recepción/header/GID de MessageInfo y candidatos
del grafo separados. No se serializa identidad atribuida; todos los registros
siguen BLOCKED. Errores de datos/escritura/fsync/cierre o ausencia de confirmación
final no permiten declarar captura completa ni repetir automáticamente.

El límite de duración cubre atascos mediante un watchdog que sólo termina el
proceso del propio colector, sin controlar vehículos ni otros procesos. Un corte
puede dejar datos parciales sin footer; deben conservarse como UNCERTAIN. El
estado de completitud del archivo es null hasta confirmación externa de cierre,
recibo stdout y rc=0; incluso esa completitud de datos no acredita asociación.

Tests offline con dobles compilan helpers y comprueban límites, datos incompletos,
persistencia/permisos y sintaxis del programa con declaraciones ROS falsas. El
colector no se ejecuta en ellos. No se compiló contra headers ROS reales en este
turno: no están disponibles en el host y no se usa Docker bajo su restricción.
La compilación real previa del Observer no acredita las nuevas APIs Context,
NodeOptions ni executor del colector. Falta ese contraste/link autorizado y,
separadamente, una futura captura pasiva y la cadena XRCE/SITL/bridge/modelo.
No se habilitó movimiento ni se cambiaron gates o reservas.


### Cierre posterior de compilación y robustez del colector — 2026-10-21

Tras la preparación anterior se autorizó una comprobación distinta: se confirmó
que el contenedor ya estaba activo y coincidían ID completo, imagen y motor;
el colector completo y sus headers pasaron `c++ -std=c++17 -pthread -Wall -Wextra
-Wpedantic -Werror -fsyntax-only` contra los headers instalados. Resultado 0,
stdout/stderr vacíos. No se enlazó ni ejecutó el programa ni se crearon nodos,
servicios, publicaciones o simulaciones. El bloqueo previo por falta de headers
para este nuevo programa queda superado **sólo en sintaxis/tipos**, no en enlace,
ABI, comportamiento de recepción ni acreditación de fuentes.

Las nuevas regresiones offline ejercitan fronteras temporales/metadatos y el
código real del journal con inyección POSIX de escritura parcial, errores de
write/fsync/cierre, además de creación exclusiva, permisos y symlinks. El módulo
del colector pasó 27 tests y la tanda combinada 79 (incluye esos 27, no se suman).
[COLLECTOR.md](../tools/rover_passive_rclcpp/COLLECTOR.md) distingue compilación
real de dobles y deja el procedimiento futuro acotado con autorización separada,
inspección inicial de sólo lectura y condiciones de parada. Se conservan salida
BLOCKED y la falta de vínculo publicador/XRCE/SYSID/SITL v3/bridge/modelo; no se
autoriza recepción ni movimiento con estas comprobaciones.

### Build enlazado y análisis offline — 2026-10-22

El colector independiente tiene ahora objetivo CMake reproducible, sin instalación
ni integración operativa. En el contenedor ya activo, con ID/imagen/motor
coincidentes, configure y compilación/enlace finalizaron con rc=0 contra ROS
Humble instalado. El primer configure falló por PYTHONPATH de ament; se corrigió
el entorno de build usando paquetes existentes, sin instalar. El binario no se
ha ejecutado: enlace real no valida recepción, RMW cargado ni identidad.

[COLLECTOR.md](../tools/rover_passive_rclcpp/COLLECTOR.md) conserva comandos,
versiones, hash del binario temporal y un procedimiento futuro exacto de recepción
pasiva (20 muestras/10 s, archivo nuevo 0600, recibo/retorno/hashes), con
inspección previa y autorización separada. El nuevo lector offline
[rover_passive_journal.py](../tools/rover_passive_journal.py) valida versión,
estructura, límites, metadatos y cierre; requiere recibo externo y rc=0 para
DATA_RECORDED. Resume cada topic, recepción monotónica, stamps y GID por muestra,
separado del grafo, e informa cambios/retrocesos sin causa inferida. Diarios
truncados o contradictorios quedan UNCERTAIN; incluso DATA_RECORDED conserva
BLOCKED. Falta recepción real y cadena publicador/XRCE/SYSID/SITL v3/bridge/modelo.
No se conecta a control, executor, lifecycle, MCP o misiones ni habilita movimiento.

### Primera recepción real parcial — 2026-10-22

Evidencia [bd6e2715](../simulation/ros2_gazebo/results/rover_passive_reception_2026_10_22/bd6e2715-878a-4d6f-8dde-b90438276b88/README.md):
un único arranque protegido, una recepción de 20 muestras/10 s y parada protegida
SUCCESS. El C++ recibió 10 muestras de odometría con GID por mensaje y
`rmw_fastrtps_cpp`, sin Status; rc=2 sin footer/recibo: UNCERTAIN. La coincidencia
con el candidato ros_gz_bridge /rover1 y el YAML efectivo hacia /model/rover1
aporta configuración observada, no una cadena de identidad completa. El snapshot
posterior del worker Python contiene Status sin GID por mensaje y no rellena esa
ausencia del colector. Siguiente eslabón: GID de Status y enlace acreditado de ese
publicador con sesión XRCE/SYSID/SITL v3; no basta el nombre ni client_key similar.
Joel informó «No hay ventana»; se conserva la excepción gráfica sin atribuirla a
la falta de Status. Después del cierre no quedan procesos relevantes ni guardas;
contenedor activo. No se invocó readiness/prearm para evitar servicios.

Tras cerrar se corrige **offline** el desfase de presupuestos watchdog/recogida,
reservando cierre dentro del mismo límite total, sin ampliarlo. Regresión y tanda
pertinente: 73 tests pasados. La fuente corregida no se ha enlazado ni ejecutado
contra ROS real; el binario del intento y sus fuentes originales están separados.
No se repite captura, ni se cambia QoS, renderer, modelos, gates o movimiento.

### Seguimiento de Status y enlace de la corrección — 2026-10-22

La corrección de plazo compartido pasó compilación/enlace con ROS real; no se
ha ejecutado. [Seguimiento acotado](rover-passive-status-followup.md) separa el
nuevo binario/fuentes del intento histórico intacto, la cadencia por defecto de
Status gobernada por AP_HAL (no temporizador de pared garantizado), el último
snapshot Python recibido después de la ventana, y el riesgo del cap global.
El cap no se alcanzó en el intento de 10 muestras. Regresiones offline de cap
unilateral y cierre explícito sin Status: tanda pertinente 73 tests pasados.
Se propone conservar 20 muestras/10 s para una prueba mínima con el binario
corregido, sin ejecutarla ni ampliar límites; no garantiza recibir Status ni
acredita identidad. Una cuota reservada para Status es alternativa no implementada.
No se infiere causa gráfica/CPU, ni se desbloquea movimiento.

### Status recibido con MessageInfo; modalidad reservada — 2026-10-22

Una modalidad opcional `--reserve-streams` reserva la última plaza para el stream
que falte, registra omisiones por cuota en footer/recibo y conserva descubrimiento
público de tipos/QoS separado de las muestras. Journal v2 convive con v1; no se
cambia el QoS solicitado ni se añade control, executor, lifecycle o MCP.
Pruebas offline: 79 pasadas; compilación/enlace real exitosos. En un único ensayo
separadamente autorizado de máximo 20 muestras/120 s se guardaron **1 Status +
19 odometría**, con GID por mensaje, rmw_fastrtps_cpp y cierre coherente rc=0 en
aproximadamente 16,872 s. Omisiones por cuota: cero; no se atribuye el éxito a esa
reserva ni se infiere la causa de las ausencias anteriores. Tipos y QoS ofrecidos
se conservan tal como los informa el grafo: history UNKNOWN/depth 0 no prueba una
configuración efectiva de cola. Inicio/parada protegidos SUCCESS; sin procesos o
guardas posteriores, contenedor activo. Identidad completa y movimiento BLOCKED.
[Evidencia](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/README.md).

### Correlación histórica de fuentes — 2026-10-22

La captura 40e8c751 recibió ambos streams y cerró, pero la cadena de identidad sigue BLOCKED. La [matriz reproducible de fuentes](rover-source-correlation.md) contrasta las 170 entradas originales, separa MessageInfo de candidatos del grafo y localiza el primer enlace ausente: endpoint DDS de Status → cliente/sesión XRCE. No se ejecutaron nuevas observaciones ni se modificó el contrato de movimiento.

## Navegación terrestre experimental v1 — 2026-10-25

IMPLEMENTADO_OFFLINE: objetivo local con realimentación dentro del executor existente.
No hay herramienta MCP nueva, lanzador paralelo ni política de movimiento habilitada:
`OPERATIONAL_ROVER_ENABLED` sigue False. La recepción pasiva autorizada de esta tanda
NO se ejecutó: el precheck actual bloqueó el historial del monitor FAILED de
104e100b-6614-49d5-85ea-2f070350cc67, aunque destino CLOSED y lecturas actuales sin
procesos/guardas. No se aplicó disposición de otro descriptor ni se abrió sesión.
La GUI negra no está corregida. Evidencia nueva separada de capturas históricas:
[ingeniería y demostración sintética](../simulation/ros2_gazebo/results/rover_navigation_offline_2026_10_25/71c84a57-51fb-4c47-9b6f-874e8a295adf/README.md).

### Observation y procedencia

`Observation` añade campos opcionales y compatibles: position_m, quaternion XYZW,
pose_frame, pose_unit, pose_reference_validated, covarianzas pose/twist (36), GID de
la muestra de odometría y digest de procedencia. `Ros2RoverAdapter.observe` conserva
pose/twist/header/recepciones del mensaje tipado; son los mismos campos ROS que
conserva el colector /3. No modifica ni reinterpreta su formato. `MotionBinding`
admite un marco de pose y un digest de acreditación explícitos; por defecto no
existen. La navegación rechaza muestras viejas/futuras, marcas sin progreso,
componentes no finitos, cuaternión no unitario/proyección degenerada, GID/digest ausentes,
marco distinto y cambios de identidad. No convierte valores cero en validez o reposo.

Esto NO conecta un diario pasivo al transporte de control: /3 no contiene todos
los campos Status (modo, failsafes, external_control) requeridos para navegar.
El NativeRos2Session Python sigue sin GID por muestra, y su guard de identidad
sigue bloqueando. Candidatos del grafo no rellenan el GID. El binding de pruebas
es explícitamente sintético; la acreditación real de marco/unidades/bridge/modelo
sigue pendiente. Las unidades nominales ROS no prueban la física del modelo.

### Objetivo, controlador y parada

El request nuevo es exactamente `{'kind':'ROVER_NAVIGATE_V1','limits':...,'goal':...}`.
`NavigationGoal` exige destino x/y/yaw, marco y unidad m, transformación
IDENTITY_SAME_ACCREDITED_FRAME, tolerancias, permanencia, frecuencia <=20 Hz,
timeout, ventana/umbrales de progreso y máximo 2–256 muestras. No hay transformación
geográfica implícita ni destino deducido de spawns. GoalController.step es puro:
calcula acercamiento sin reversa, giro acotado, orientación final y cero en tolerancia.
Dwell exige posición/orientación dentro y velocidades observadas bajo los umbrales;
salir de tolerancia o seguir moviéndose reinicia la permanencia. El dwell del control
usa recepción monotónica, no un avance por tiempo ni el reloj simulado.

`RoverControlCore.navigate` exige dos observaciones progresivas antes de publicar,
GUIDED ya armado/control externo listo y ningún failsafe. No arma ni entra
automáticamente en GUIDED. Calcula, publica y vuelve a observar con plazos y cuotas
finitas. Contempla cancelación, pérdida/obsolescencia, cambio de marco/origen,
no-progreso, timeout, cuota agotada, error de envío y parada fallida. Tras posible
efecto solicita el stop terrestre existente (cero/HOLD); nunca TAKEOFF/LAND.
La parada requiere observación progresiva y fuente consistente; si cambia de
identidad o sale del objetivo durante el stop no se declara visita completada.
Enviar cero no acredita detenerse. No se desarma automáticamente.

El worker reutiliza snapshot/hash, validación determinista, identidad PID/boot,
reserva global y v3, execution_scope, diagnóstico y persistencia. Consulta de un
worker desaparecido sigue UNCONFIRMED; no hay reanudación o liberación automática.
Un rover aún armado conserva reservas incluso con objetivo y parada observados.
Máximo 256 muestras de navegación más la evidencia acotada de stop; no se guardan
flujos ilimitados. No hay validación operativa de estas ganancias/umbrales.

### Contrato para el sistema multiagente — sin editar coordinador/reporting

Interfaces existentes: admit_ground_trial(mission_path, request_key, request,
authorization), run_ground_worker(run_id, token, adapter_factory=..., readiness=...,
cancelled=...), query_ground_trial(run_id). Las dos primeras siguen bloqueadas
operativamente por la política. No se añadió spawn público. Pruebas habilitan la
política sólo en proyectos temporales con adaptador sintético.

El informe conserva `r1` (`tfg.rover.navigation-result/1`): hashes de misión/request/
entrada/goal/muestras, worker, muestras completas, límite, órdenes enviadas y stop.
Además expone `r1_ground_result` con esquema `tfg.agri-r1-ground-result/1`, muestras
x_m/y_m/frame/velocidades/source_stamp_ns/received_monotonic_s/GID, comandos con
instante inicial, decision_monotonic_s y stop.status/observed/requested.

No fabrica las asociaciones que el coordinador exige: candidate_sha256 y session_id
quedan None; el digest de autorización es el del executor y NO se asume idéntico al
canonical del coordinador. `binding_unresolved` los enumera. frame.transform_status
es DECLARED_ADAPTER_BINDING_NOT_INDEPENDENTLY_VERIFIED, no VERIFIED. Origen sintético
se etiqueta SYNTHETIC_TEST_DOUBLE, nunca EXECUTED. Por ello la aceptación actual de
El sistema multiagente debe rechazar esta vista como prueba real de R1. Su wrapper puede reutilizar
la forma del request y leer el resultado, pero necesita transportar candidato/sesión/
consentimiento con una procedencia verificable y contrato de digest acordado. No debe
rellenar estos campos desde el nombre del proceso o del fichero.

La permanencia de su evaluador es de reloj simulado y sus parámetros propuestos
son distintos: no hay equivalencia automática con el dwell monotónico del control.
Las muestras exponen ambos relojes para evaluarlos separadamente. Un resultado del
objetivo no resuelve identidad, reservas, autorización ni el escenario agrícola.

### Preparación y requisitos antes de movimiento

[Preparación v1](../evaluation/operations/rover_navigation_v1_preparation_2026_10_25/manifest.json)
contiene MissionDefinition compatible, request y estado/hash por archivo. Parámetros
experimentales: objetivo local (0.8,0.4)m, yaw 0.2 rad en marco odom PROPUESTO,
0.4 m/s, 1 rad/s, 10 Hz, tolerancias 0.05 m/0.05 rad, dwell 0.3 s, timeout 25 s,
no-progreso 4 s y máximo 256 muestras. Son fixtures reproducibles, NO límites
validados ni consentimiento. Las coordenadas geográficas del envelope se copiaron
del ejemplo de tests: NO acreditan un anchor o transformación y no son destino
operativo. Ningún job real se admitió con estos ficheros.

Antes de una prueba terrestre: resolver la atribución por muestra y cadena
XRCE/SITL/bridge/modelo; acreditar marco/unidades/transformación y recepción fresca;
revisar umbrales de parada y parámetros experimentales; integrar un worker operativo
supervisado con política aprobada y autorización exacta de misión/request; conservar
reservas ante pérdida del worker o stop incierto. Esa autorización no existe aquí.
Para una recepción PASIVA futura ya existe --headless en lifecycle; no necesita
inventar confirmación visual. Sigue exigiendo precheck válido, agente/helpers,
capture_window fresco, límites 20/120/reserve-streams/odometry-fields y cierre
protegido. El bloqueo histórico actual debe resolverse por un mecanismo revisado
para ESTE descriptor; no con override ni disposición de 51790d37.

## Continuación: contrato explícito y worker interrumpible — 2026-10-25

Esta sección sustituye el contrato incompleto de la tanda anterior; sus evidencias
se conservan. No se habilita la política, no hay nueva apertura/reactivación ni
movimiento. Resultados y dry-run actual:
[revisión acotada](../simulation/ros2_gazebo/results/rover_failed_review_2026_10_25/31c8d4bd-50b1-44c7-b36a-81e9900e2e0c/README.md).

### Recorrido público e integración para el sistema multiagente

Se usa el mismo recorrido: admit_ground_trial -> snapshots/reservas ->
run_ground_worker -> RoverControlCore.navigate -> Ros2RoverAdapter -> observaciones
-> stop -> report/job -> query_ground_trial. Las pruebas llaman esas APIs, nunca
sólo GoalController. OPERATIONAL_ROVER_ENABLED permanece False; únicamente el
fixture temporal habilita su doble. Query/restart no relanzan un worker consumido.
No se añade un launcher, CLI de control ni thread emisor.

Interfaces exactas nuevas o ampliadas (el sistema multiagente cambia su adaptador, no este código):

```python
executor_facts()  # puro, sin filesystem: política, soporte y contrato de deadline
lookup_ground_trial(request_key)  # read-only: found/run_id/scope/session_id/coordination_sha256
admit_ground_trial(mission_path, request_key, request, executor_authorization,
    coordination_context={"candidate": candidate, "authorization": coordinator_authorization})
run_ground_worker(run_id, launch_token, *, adapter_factory=None,
    readiness=check_simulation_ready, cancelled=lambda: False)
query_ground_trial(run_id)  # incluye session_id, coordination_binding y report
```

Para ROVER_NAVIGATE_V1 el contexto explícito es obligatorio cuando se intenta
admitir con la política de pruebas habilitada; sin él falla antes de reservar.
El contexto tiene exactamente candidate y authorization. La segunda conserva
exactamente source/statement/candidate_sha256/mission_sha256/session_id, con fuente
OPERATOR_DECLARED y sesión UUID canónica. Se comprueban candidato, misión real,
destino/marco y declaración de transformación frente al request; no se extrae nada
del texto concatenado del statement. La autorización del executor conserva su
esquema anterior mission_sha256/request_fingerprint/statement. No se presume que
ambas autorizaciones sean el mismo objeto ni autenticación de persona alguna.

El coordinador actual conserva candidate y authorization en su record, pero su
RoverGroundExecutorAdapter.admit todavía no transmite coordination_context. Debe
pasar esos objetos originales explícitamente (y conservarlos en el task hash), usar
executor_facts en lugar de interpretar un mensaje de error privado y usar
lookup_ground_trial en lugar de reconstruir un session_id ausente desde el índice.
No se ha modificado tools/agri_ground_coordinator.py ni reporting. Mientras no lo
haga, la admisión operacional futura rechaza el vínculo ausente; la política
cerrada actual rechaza antes incluso de llegar ahí.

Serialización: fingerprint(obj) = SHA-256 de
json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')
(con separadores por defecto, incluidos espacios). El digest del candidato se
calcula sobre el candidato COMPLETO; el de autorización coordinador sobre su
objeto COMPLETO de cinco campos. Son iguales a los canonical simples del
coordinador sólo si los objetos son iguales y finitos; no se asume igualdad entre
esquemas distintos. mission_sha256/request_sha256/coordination_sha256 son hashes
sobre bytes exactos de sus snapshots. input_sha256 en navegación añade
coordination_sha256 a los tres hashes previos; los jobs bounded anteriores
conservan su fórmula. admission_scope_sha256 enlaza misión, fingerprint del request,
autorización del executor y contexto explícito; lookup compara índice/job/snapshots.
El sistema multiagente debe leer esa scope de los registros, no suponer la fórmula antigua.

El job guarda coordination.json, digest/binding y session_id; _checked los revalida
en worker, query y lookup. Antes de controlar, capabilities.session_id debe igualar
la sesión ligada y adapter.binding.pose_reference_sha256 debe igualar el digest del
frame en el candidato. El transporte nativo aún no acredita esta fuente: no se
inventa ese dato. En pruebas sólo lo aporta un transporte explícitamente sintético.

report.r1_ground_result ya conserva candidate_sha256, session_id y hash de la
AUTORIZACIÓN DEL COORDINADOR desde esos snapshots, junto al run_id, misión, fuente
por muestra, frames/relojes, comandos y stop.status. report.r1 conserva el hash de
AUTORIZACIÓN DEL EXECUTOR dentro del input_sha256. binding_unresolved queda vacío
para el enlace documental; esto NO acredita identidad ni frame físico. El campo
transform_status sigue declarado/no independientemente verificado y el origen no
se promueve a EXECUTED. La aceptación real continúa bloqueada por procedencia,
frame y reservas; no se ha fabricado un VERIFIED para completar R1.

### Deadline de llamadas: no basta comprobar al volver

RoverControlCore._operation y el probe del worker ahora instalan un deadline
síncrono POSIX (SIGALRM/setitimer) en el mismo main thread del worker. Interrumpe
las llamadas Python/bloqueos interrumpibles y restaura el temporizador/handler;
rechaza workers en threads secundarios y timers activos de otro propietario antes
del backend. No crea hilos/futuros/procesos que puedan publicar después de cancelar.
Las APIs nativas conservan además sus propios plazos finitos. Python no garantiza
interrumpir código C opaco que no entregue control o suprimiera señales: no se
promete ese límite y la política nativa permanece cerrada hasta comprobar su
contrato de cancelación. Tests introducen sleep real bloqueado en observe y send,
verifican retorno acotado, reservas retenidas y ninguna orden tardía tras esperar.
El test de exclusión concurrente usa un deadline doble sólo para aislar el lock;
no demuestra que un worker real soporte control desde un thread secundario.

### Estado operativo y siguiente recepción

Dry-run actual del caso FAILED: elegible para revisión separada; NO aplicado.
Clasificación histórica conserva diagnóstico INCOMPLETE y recibo FAILED, identidad
y movimiento BLOCKED. Ver el procedimiento XRCE para digest/autorización exactos.
Resolver esa disposición no autoriza abrir. Esta tanda no consume una apertura.

La recepción pasiva headless existente puede recoger Status y odometría /3 sin
confirmación visual inventada. Necesita autorización NUEVA de apertura tras la
aplicación revisada y precheck fresco, binarios/helpers verificados, monitor y
capture_window que cubran captura+cierre. GID/peer/socket/proceso puede avanzar si
existen filas/propietarios únicos coherentes; no prueba paquetes ni SYSID efectivo.
Pose/velocidad/marcos/covarianzas serán descripciones de muestras retenidas, no todo
el flujo. Modelo/bridge requiere configuración/proceso/modelo efectivo acreditado;
SYSID requiere estado efectivo mediante interfaz pública autorizada, no argv ni
ClientKey. Ninguna de las cuatro conclusiones se deduce automáticamente de recibir.

## Cierre explícito y arranque recuperable — cierre de tanda 2026-10-26

El código operativo sigue deshabilitado. Se completó una sesión PASIVA headless
sin controles; véanse resultados y manifiesto de
[4ac58516](../simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728/README.md).
Sus tiempos operativos originales son UTC del 25/10; el directorio se conserva.
No se ejecutó navegación, armado, desarmado, cambio de modo ni readiness/prearm.

### Política elegida: desarmar sólo después de parada observada

Nueva política opt-in de navegación:
`finalization={"kind":"DISARM_AFTER_OBSERVED_STOP_V1","timeout_s":3.0}`
(el timeout es explícito/experimental). Debe aparecer exactamente igual en
candidate.finalization_policy.value y en el request, y por tanto en sus hashes y
las declaraciones autorizadas. No se aplica a requests antiguos que no la declaran.
No se inicia stop global de simulación desde el controlador.

Fuente: ArmMotors.srv local contiene bool arm -> bool result; AP_DDS_Client.cpp
on_request despacha arm=false a AP_DDS_External_Control::disarm(...,do_checks=true).
Esto acredita el contrato, no su disponibilidad actual. La capacidad tipada
/ap/v3/arm_motors debe descubrirse antes de mover; si falta, se bloquea. El whitelist
acepta sólo False, nunca True, y _assert_disarm_scope exige el input_sha256/worker
propietario y el job FINALIZING con esa política explícita. Una autoridad v3 de un
job anterior no presta permiso de desarme a esta ruta.

Secuencia: objetivo/stop -> stop-evidence.json durable -> FINALIZING -> lectura
fresca HOLD/no conducción/movimiento bajo umbrales y misma fuente -> petición
ArmMotors(False) una sola vez -> respuesta bool positiva -> dos observaciones
progresivas posteriores, desarmadas y estacionarias, misma fuente. Una respuesta
positiva sola no basta. Rechazo, respuesta perdida, datos antiguos, pérdida de
fuente o interrupción conservan UNCONFIRMED/reserva, sin reintento de desarme.
La política y las pruebas no acreditan que el rover real esté listo para ello.

Report conserva por separado result.goal_outcome, observaciones/órdenes de
navegación, result.stop y finalization (intentado/ack/observado). closure indica
estado armado observado, vehicle_close y job_close=COMMIT_ELIGIBLE; no promete que
ya se escribió el job ni se liberó la reserva. query_ground_trial devuelve
job_closure_confirmed sólo con job FINISHED y reserva de ese job ausente. Un fallo
de persistencia/liberación permanece incierto. Objetivo fallido + stop/desarme
confirmados puede cerrar FINISHED con reporte GOAL_FAILED_CLOSURE_OBSERVED, sin
convertirlo en objetivo cumplido. Objetivo cumplido + cierre incierto NO termina.
El HOLD armado de trabajos sin nueva política conserva el comportamiento anterior.

### Ficha de integración definitiva para el sistema multiagente

```python
executor_facts()  # puro; policy_enabled=False, soporte, start/finalization/deadlines
admit_ground_trial(mission_path, request_key, request, executor_authorization,
    coordination_context={"candidate": candidate, "authorization": coordinator_authorization})
lookup_ground_trial(request_key)  # sólo lectura; found/run_id/session_id/input_sha256/status/worker_phase
query_ground_trial(run_id)       # sólo lectura; binding/fases/report/reserva/job_closure_confirmed
start_ground_trial(run_id, start_authorization, *, adapter_factory=None,
    readiness=check_simulation_ready, cancelled=lambda: False)
```

La admisión nueva ROVER_NAVIGATE_V1 NO devuelve launch_token. Bounded legacy
conserva su entrada de token anterior; no se inventa candidato/sesión de un job
legacy para hacerlo recuperable. La consulta no devuelve secretos de ejecución.
request_key es localizador, NO credencial ni una orden de arranque.

start_authorization tiene exactamente run_id, input_sha256, candidate_sha256,
session_id, authorization_sha256 (del COORDINADOR) y statement no vacío. Todos
salvo statement deben igualar los snapshots existentes. Es declaración local
registrada, no autenticación humana. Una nueva consulta no crea permiso, token o
worker; la operación start es explícita. El coordinador puede reconstruir esa
DECLARACIÓN desde su consentimiento/records durables; no puede inventar sus vínculos.

Arranque síncrono: el caller main thread es el worker; no hay fork/Popen, token
regenerado ni proceso emisor huérfano. Bajo admission+registry: validar snapshots,
scope/reserva -> start-intent.json exclusivo y fsync -> STARTING durable ->
validar identidad del mismo proceso -> RUNNING durable -> workflow existente y
su exclusión global. Luego FINALIZING si se autorizó, FINISHED o UNCONFIRMED.
Consulta muestra worker_phase=ADMITTED_NOT_STARTED para una reserva íntegra sin
claim/worker; status sigue ADMITTED por compatibilidad. Claim sin fase confirmada,
STARTING con requester muerto/PID reutilizado o worker perdido son inciertos.
Cualquier claim consumido impide arrancar otra vez. Pérdida de respuesta se recupera
por lookup/query, no por regenerar token ni repetir. Una respuesta perdida después
de FINISHED también se resuelve consultando el resultado persistido.

La entrada no soporta ejecución desde un thread secundario: los deadlines POSIX
requieren main thread. La prueba concurrente sustituye sólo el consumo del claim
para comprobar exclusión; el recorrido funcional usa el worker real con sesión
cinemática sintética. No se ha añadido lanzador operativo ni MCP. La política
False y la ausencia de adaptador vivo siguen bloqueando por defecto.

Pruebas propias: 155 pasadas en la tanda afectada; cuatro regresiones adicionales
de pérdida/identidad/cierre y dos de diagnóstico de servicios pasaron aparte. No se
suman como suite independiente. Integración conjunta del sistema multiagente: 30 tests pasados,
con fuentes iguales antes/después de esa tanda; toda trayectoria física es sintética.
Ver logs acotados en la evidencia. Se demostraron respuesta perdida, un solo claim,
interrupciones antes/después de STARTING e identidad, PID reutilizado, cancelación
en aproximación/permanencia, stop/desarme rechazados y reservas retenidas.

### Qué aportó la recepción real, y qué sigue bloqueando movimiento

20 muestras: un Status y 19 odometrías /3, rc=0, diario/footer/recibo coherentes.
Status enlazó exactamente GID/RMW con writer nativo y contexto XRCE. Seis inventarios
repitieron peer 127.0.0.1:40177 -> inode1209928 -> FD16 -> ardurover PID1598,
start_ticks1007467, en el contexto/boot de la sesión. La séptima lectura perdió
/proc/1570/stat (agente) durante la parada: queda INCOMPLETE. El análisis de TODA
la serie es UNCERTAIN_OR_INCOMPLETE; no se descarta esa fila ni se afirma origen
atómico de paquetes. Monitor CLOSED/capture_complete=true no completa esos sockets;
rc del proceso monitor sigue UNKNOWN. Lifecycle stop SUCCESS y guardas/procesos vacíos.

Odometría: GID propio, odom/base_link, 19 muestras finitas, sin regresiones observadas;
0.36 s de sellos frente a 18.64 s de recepciones. Son relojes/selecciones distintos:
no se deducen RTF, frecuencia real, pérdida, jitter total o causa de lentitud.
Covarianzas declaradas cero no prueban certeza y velocidades pequeñas no acreditan
reposo. No se valida modelo, transformación ni unidades físicas sólo por el topic.
En aquella versión, el roll/pitch recibido no satisfacía la hipótesis planar
estricta del prototipo (qx/qy superan 1e-3). Ese rechazo histórico fue sustituido
por projected_ground_heading en la corrección geométrica del 26/10 descrita abajo;
no es una precondición planar vigente ni una aprobación de pendiente.

Antes del primer movimiento faltan: atribución/modelo/bridge efectiva y SYSID
efectivo (no argv/ClientKey), un transporte vivo que entregue identidad por muestra
(el callback Python sigue con GID None), acreditación de marco/unidades/relojes y
proyección de orientación, revisión de límites/umbrales y capacidad real de
finalización, worker operativo revisado y consentimiento verificable exacto. Los
resultados sintéticos no habilitan ninguno de esos gates.

Lecturas o hashes contradictorios de snapshots/índice pueden lanzar ValueError/
OSError; eso significa integridad/desconocido, nunca permiso para readmitir o
arrancar. Los estados inciertos se consultan y revisan, no se reparan desde query.

El adaptador actual del sistema multiagente ya transmite coordination_context y utiliza las APIs
de facts/lookup/start; sus 30 tests conjuntos pasaron sobre hashes estables. La
ficha anterior describe las firmas de nuestros componentes; el uso real de su
coordinador pertenece a su implementación y no se ha editado desde esta tarea.

Datos concretos del experimento: máximos de norma lineal0.0001561 y angular0 en
muestras retenidas, posiciones x[-0.0012414,-0.0012346], y[-3.000424,-3.000404],
z[0.0949147,0.0949282], covarianzas declaradas todas cero. Son descripciones de
mensajes, no prueba de reposo o precisión. No se infieren destinos del parecido
con los spawns. El span completo de lecturas incluye la muestra Status, pero no
elimina el hueco entre snapshots ni el fallo terminal de contexto.

### Progreso por fase tras perturbaciones — 2026-10-26

La reproducción aportada por el sistema multiagente está en
`tests/test_agri_ground_joint.py::test_rover_goal_controller_no_progress_after_disturbance`.
Se confirmó también ejecutando únicamente la clase pura de la fuente archivada:
tras llegar, su mínimo histórico quedaba en cero; una recuperación de 0.30 a
0.11 m fallaba con NO_PROGRESS a los 12.5 s. No se ejecutó otra recepción ni se
repitió la disposición para investigar este defecto.

`GoalController.step` distingue ahora estas fases:

- **APPROACH:** exige mejorar los mínimos de distancia/orientación con los
  umbrales explícitos `progress_m` / `progress_rad`. Cada mínimo se actualiza sólo
  por progreso en su propia magnitud. Una mejora angular no consume avance lineal.
- **DWELL:** posición/orientación válidas y velocidades observadas bajo los
  umbrales. Mantiene cero como orden y exige permanencia continua. Dos observaciones
  consecutivas válidas pausan la vigilancia de avance, porque permanecer es aquí
  el objetivo; no pausan el timeout global. Estar dentro mientras se mueve no
  acumula permanencia ni pausa esa vigilancia.
- **RECOVERY:** al salir tras una entrada válida, fija una referencia espacial
  local, sin conceder tiempo adicional. La resolución de progreso es explícitamente
  `min(progress_m, tolerance_m)`: con los parámetros de la reproducción es 0.05 m.
  Exigir 0.5 m de mejora después de un desplazamiento de 0.3 m sería imposible.
  Sólo nuevos mínimos de ese episodio cuentan; oscilar sobre distancias ya
  recuperadas no renueva el reloj. Cambiar entre orientación de trayectoria y
  orientación final tampoco concede progreso por sí mismo.

Esto cambia el contrato de progreso **por fase**; no cambia el valor declarado
`progress_m=0.5`, tolerancias, velocidades, permanencia, cuotas ni plazos. No se
presenta la elección experimental de 0.5 m como un error: en aproximación sigue
siendo el umbral exigido y puede rechazar avances menores. En recuperación una
mejora diminuta por debajo de la resolución también puede terminar en NO_PROGRESS.
La resolución se registra como `progress_quantum_m`, junto a `phase` y
`progress_age_s`, para que esta diferencia sea visible en cada decisión.

Salir, entrar o cambiar de fase no reinicia el tiempo sin progreso. Los intervalos
de transición se cargan completos; el tiempo de aproximación/recuperación sin una
mejora suficiente se conserva a través de entradas fugaces. Cada salida puede
establecer un mínimo local, pero sólo un avance real suficiente renueva esa
vigilancia. Perturbaciones repetidas con recuperaciones reales pueden renovarla;
el timeout global, anclado a la primera decisión, termina igualmente el trabajo.
El deadline exterior de `navigate`, la cuota de observaciones y la parada tras
posible efecto siguen vigentes. No hay reanudación ni nueva autorización implícita.

Regresiones propias en `tests/test_rover_goal_progress.py`: recuperación lenta,
resolución insuficiente, oscilación, inmovilidad, entradas/salidas fugaces,
perturbaciones repetidas, permanencia frente a ambos relojes y recorrido completo
worker/adaptador/parada/cierre autorizado en proyecto temporal. La sesión física
es una doble cinemática; no acredita disponibilidad ni movimiento del rover real.
La reproducción original del sistema multiagente conserva una aserción que **espera el fallo
antiguo**: ahora obtiene DID NOT RAISE. No se ha editado ese archivo ajeno; debe
actualizarse esa expectativa por su responsable, sin presentar la suite conjunta
completa como verde mientras siga así. El resto se comprueba separadamente.

En VS Code, seguir `GoalController.step` para fases, mínimos y relojes;
`RoverControlCore.navigate` para observaciones, cuota, deadline y parada; y
`start_ground_trial` para exclusión, identidad del worker y cierre persistido.
Estos componentes pertenecen al camino de control todavía deshabilitado por
defecto. El colector pasivo y la instrumentación XRCE/socket son diagnóstico
independiente: no se ejecutaron ni cambiaron en esta corrección. Identidad completa
y movimiento real permanecen BLOCKED.

Resultados de esta corrección: 42 pasadas y una deseleccionada (29 pruebas de
integración sin editar y 13 propias). Después se reforzó sólo la regresión de
oscilación para que una mejora inicial de 6 cm cuente una vez y no vuelva a contar
al revisitarla: 18 pasadas en la tanda focal final, que incluye las 13 propias y
cinco existentes de permanencia/plazos. Las tandas se solapan; no sumarlas como
una suite independiente. Sintaxis y whitespace sin incidencias, índice vacío.
Se conservaron el fallo de expectativa del sistema multiagente y la reproducción sobre la clase
archivada, junto con fuentes y hashes en la
[evidencia offline de progreso](../simulation/ros2_gazebo/results/rover_goal_progress_2026_10_26/ff11914f-7236-457d-bc6d-45d8cee9efd3/README.md).
El manifiesto anterior de 119 entradas fue verificado íntegro, sin reescribirlo.

### Preparación física, identidad y recursos — 2026-10-26

Sin disposición, sesión o captura adicional. El mapa exacto, consultas actuales,
parámetro MAV_SYSID corregido, límites de atribución y pruebas de marcos están en
[la matriz de fuentes ampliada](rover-source-correlation.md#lectores-fuentes-y-marcos--implementación-offline-2026-10-26).
Sus hashes/recepciones quedan separados de los 119 originales históricos.

Nueva conexión explícita al contrato del worker existente:

```python
from tools.rover_ros2_adapter import physical_adapter_factory
factory = physical_adapter_factory(expected, read_current, motion_binding,
    call_timeout_s=limits.call_timeout_s, cancelled=cancelled)
# Sería adapter_factory del start_ground_trial existente, no otro coordinador.
# NO ejecutar ahora: OPERATIONAL_ROVER_ENABLED sigue False y el guard bloquea.
```

Crear factory no importa ROS ni crea nodos. Bajo su deadline, build(journal)
consulta RoverEnvironmentGuard antes de construir NativeRos2Session. El guard
real sigue bloqueado: ni la forma de MotionBinding ni un hash son prueba de
fuentes. No hay flag verified/manual que lo sustituya. La sesión informaría el
lifecycle_id de ese guard, no un identificador de sesión inventado por discovery.
No se cambió la admisión, snapshots, reservas, executor_facts, start/query ni API
del sistema multiagente; el executor no selecciona por defecto este factory ni habilita operación.

NativeRos2Session conserva las interfaces tipadas existentes y añade procedencia
explícita de recibos/ausencia de GID. Los callbacks de Humble siguen recibiendo
un argumento; GID por muestra sigue None, para Status y odometría. Un transporte
compatible con MessageInfo en vivo sigue pendiente; el colector C++ aislado no
se convirtió en sesión de control ni se lee un diario histórico como dato fresco.

Probe/observe/exchange usan deadlines POSIX en el mismo worker, sin emisor en
background. La espera de servicio comprueba cancelación entre spins acotados;
timeout o cancelación cancela sólo el future local, no revierte una petición.
Se conserva endpoint/tipo/request y efectos UNCONFIRMED. Publish sigue sin respuesta
de aplicación. El guard y la exclusión se comprueban antes de emitir órdenes.

Construcción parcial limpia nodo/contexto. El factory proporciona presupuesto
finito para liberar recursos; close es idempotente tras éxito, y una excepción o
agotamiento queda uncertain sin fingir cierre ni reintentar. Se intenta cerrar el
otro recurso si queda presupuesto. El constructor directo sin presupuesto sólo
se conserva para compatibilidad de pruebas; la ruta física preparada usa factory.
Los deadlines se demostraron para bloqueos Python interrumpibles con dobles.
No prometen interrumpir una llamada C opaca que retenga/suprima señales; esa
capacidad del transporte real aún requiere verificación. Ninguna de estas pruebas
autoriza armado, desarme o movimiento real.

También se implementaron el lector público de parámetros opt-in y el verificador
de configuración bridge, ambos separados del permiso de movimiento. Una lectura
MAV_SYSID sin vínculo al servidor no acredita la instancia. Candidatos del grafo,
configuración y atribución por muestra siguen siendo hechos diferentes.

Inventarios: analyze_series admite closure_evidence y devuelve usable_windows
localmente verificadas y terminal_context_loss. Reanalizar 4ac58516 en memoria
conserva seis ventanas y explica la pérdida /proc/1570/stat durante el cierre
protegido. La muestra Status está entre las ventanas extremas válidas, pero no
dentro de una de sus breves barridas. La serie permanece UNCERTAIN_OR_INCOMPLETE;
no se reescribió el informe original ni se afirmó cobertura continua/atómica.

Verificación conjunta final de las ocho suites afectadas: **289 passed en 14.05 s**.
Incluye transporte sustituido, cancelación/bloqueos, construcción/cierre parcial,
lectura tipada/timeout/NOT_SET, sesiones/archivos contradictorios, marcos/signos,
supervisor y análisis terminal. No es una suite completa ni validación operativa.
Logs, lectura de fuentes y nuevo análisis separado están en
[la evidencia de preparación](../simulation/ros2_gazebo/results/rover_identity_preparation_2026_10_26/c45ae0d8-5515-40ae-a359-244ac1323822/affected-tests.log).
Tras precisar que el retorno de un supervisor fallido tampoco es el del hijo,
la tanda focal monitor/selector pasó 83 pruebas en 3.79 s. Se solapa con la de
289; no sumar ambos recuentos. La prueba nueva exige que un padre fallido escriba
sólo monitor_supervisor_exit.json si no hay wait del hijo.
La comprobación focal de lector/transporte tras rechazar la destrucción fallida del
cliente de parámetros pasó 31 pruebas (tanda solapada). Un destroy_client=False
impide devolver una lectura aceptada; tampoco se oculta un fallo de cleanup.
El verificador reutiliza además el loader YAML histórico que rechaza claves
duplicadas: sólo inspecciona valores parseados, no bloquea por un comentario que
mencione una plantilla. Conserva fuentes/recepciones en su resultado. La tanda
focal de contratos/inventario/correlación pasó 57 pruebas en 3.42 s tras esa revisión;
también se solapa con la anterior y no es validación operativa.

### Rumbo con inclinación: corrección posterior — 2026-10-26

Esta sección sustituye las menciones anteriores al rechazo por qx/qy como política
actual. El código antiguo permanece archivado; no se modificaron las 119 entradas,
la evidencia del sistema multiagente ni se hizo otra operación. La captura /3 ya está finalizada.

Primera odometría original: q=(-0.003358797339562485, 0.0033726141339645637,
0.7056744662334027, 0.7085202125984391), norma=1.0. Roll ≈0.0000219881°,
pitch=0.5454391704°, rumbo proyectado=89.7694108673°. El rechazo antiguo era
`abs(qx)>1e-3 or abs(qy)>1e-3`: compara componentes adimensionales que mezclan
roll/pitch/yaw, NO un ángulo de pendiente. La fórmula anterior de yaw suponía
qx=qy=0 y daba 89.7681126481°. El quaternion recibido no está mal normalizado.

La regresión carga el diario original por su SHA-256 y reproduce Non-planar
orientation con la clase pura archivada. El envoltorio Status/marco del test es
explícitamente sintético: /3 no contiene el payload Status completo. El test no
inventa modo/armado/frescura real ni atribuye el marco para llegar al fallo.
Se separa la reproducción con crédito de marco TEST-ONLY del rechazo actual sin
ese crédito: Navigation frame/provenance contract not accredited.

`projected_ground_heading` calcula la primera columna de R(q), el eje longitudinal
body +X expresado en el marco de referencia:

```text
forward = (1 - 2(y²+z²), 2(xy+wz), 2(xz-wy))
heading = atan2(forward_y, forward_x)
```

Supone quaternion child→reference y reference XY horizontal, +Z normal hacia arriba.
Son supuestos geométricos nominales ROS, no una acreditación del publisher/modelo.
Se comprueba forma/valores finitos y se conserva la tolerancia anterior de 1e-3
para **norma al cuadrado**. Sólo tras pasarla se normaliza para eliminar redondeo;
no se acepta un quaternion arbitrariamente escalado o cero. q y −q son equivalentes.
Se rechaza un eje longitudinal vertical o numéricamente degenerado: longitud de
su proyección <=sqrt(ulp(1)) ≈1.49e-8. Es condicionamiento numérico adimensional,
NO un máximo de pendiente aprobado ni una garantía sobre ruido del sensor.

Una orientación perfectamente paralela al plano no es necesaria para definir ese
rumbo. Incluso una orientación invertida puede tener una proyección definida;
ello NO significa que el rover pueda operar así. El resultado conserva
body_up_inclination_rad y operational_slope_approved=False. Antes del primer
movimiento falta una política explícita de inclinación/superficie, revisada y
ligada al alcance; no se deduce de los 0.55° de esta captura.

`_navigation_observation` conserva el gate previo de marco/unidades/procedencia y
su tupla (x,y,yaw); sólo sustituye el cálculo geométrico después del gate. navigate
añade heading_geometry a sus decisiones, sin cambiar NavigationGoal, límites,
progreso, plazos, parada ni APIs del coordinador. No hace pasar un marco desconocido.
OPERATIONAL_ROVER_ENABLED sigue False y el guard físico sigue bloqueando antes de
crear ROS o emitir órdenes. La utilización operativa de la proyección sigue cerrada.

`transform_ground_point` prepara el cálculo SE(2) de un objetivo:
p_destino=t+R(theta)p_origen, metros/radianes, CCW. Valida entradas y resultado,
pero no acredita t/theta, no genera MotionBinding ni un status VERIFIED. La
transformación entre el objetivo real y odom sigue sin medirse; nunca usa spawns.

Pruebas: combinaciones roll/pitch/yaw mediante producto Hamilton y matriz de
rotación independiente; inválidos, escalas, q/−q, verticales, cruce ±pi, signos de
giro, objetivos en cuatro direcciones y transformaciones/inversa. Se extendió el
doble AHRS 3D que ejecuta el método C++ real AP_DDS con tipos sustituidos, sin
compartir el integrador Session/Clock. No es firmware ni ROS real. También pasa
el worker protegido con inclinación sintética, velocidad horizontal proyectada,
finalización explícita y FINISHED; conserva origen SYNTHETIC_TEST_DOUBLE.

Tanda focal final: **175 passed en 4.71 s**. Controlador/navegación/progreso/core/
executor y recorrido conjunto del sistema multiagente: **182 passed en 155.31 s**, con sus fuentes
estables y sin editarlas. No se ejecutó la suite completa. Las interfaces de
admisión/start/consulta permanecen iguales; se comprobó con dobles el session_id
exacto que probe devuelve del guard y el bloqueo de start físico antes de factory.
[Muestra y geometría reproducibles](../simulation/ros2_gazebo/results/rover_heading_geometry_2026_10_26/3869b253-e59e-4e30-8169-31453d622dbc/real-sample-geometry.json).

### Lector pasivo separado y política de inclinación — 2026-10-26

La siguiente preparación se describe en
[la matriz de fuentes](rover-source-correlation.md#preparación-pasiva-de-identidad-y-marcos--2026-10-26)
y en [el procedimiento XRCE](../tools/rover_xrce_trace/README.md).
`tools/rover_identity_probe` es un lector diagnóstico independiente; no crea la
sesión física del executor ni clientes de control. `probe_session_id` documenta
la sesión protegida observada, sin cambiar las APIs que usa el sistema multiagente. El adaptador
físico existente sigue exigiendo guard/identidad/marco antes de construir ROS y
OPERATIONAL_ROVER_ENABLED continúa false.

**No existe todavía un gate efectivo de pendiente aprobado.**
`operational_slope_approved:false` es información geométrica, no lo implementa.
La recepción pasiva no necesita un límite operativo arbitrario: conserva toda
orientación finita recibida y no emite órdenes. Antes de movimiento deberá
establecerse un límite explícito dentro del alcance de la prueba y validarse en
la admisión y antes de cada orden, con observación fresca y marco acreditado.
Esta tanda no elige un valor, no habilita ese camino ni convierte los 0,55°
observados en aprobación de pendiente.

### Primer movimiento: propuesta separada de R1 — 2026-10-26

**PROPUESTO, NO AUTORIZADO, NO EJECUTADO.** El ensayo pasivo f206c00d cerró la
infraestructura, pero omitió el lector por supervisión incompleta. No aportó SYSID
efectivo, MessageInfo de muestras nuevas, referencias aéreas ni transformación.
El worker dejó un candidato odom sin GID por muestra: no acredita reposo, origen,
modelo o precisión. No se recalibran marcos con el spawn ni con y≈−3.

Antes de cualquier movimiento faltan: fuentes atribuidas y frescas; rama SYSID;
plugin/entidad y FDM; transformación de objetivo/observación con incertidumbre;
política de inclinación efectiva; tratamiento protegido de armado y cierre. El
executor sigue OPERATIONAL_ROVER_ENABLED=False. El transporte preparado conoce
TwistStamped y ModeSwitch, pero publicar no ofrece un ack de velocidad/efecto.
El disarm protegido es opt-in tras parada observada, no armado ni desarme libre.
La creación del adaptador físico continúa bloqueada por su guard; no se prueba
su disponibilidad operacional a partir de un objeto o un endpoint descubierto.

**a) Ensayo corto de transporte y respuesta física.** Propuesta inicial para
revisar una vez satisfechos esos requisitos:

| Parámetro | Propuesta / condición pendiente |
|---|---|
| Velocidad pedida | 0,05 m/s hacia +X corporal, como excitación pequeña; no afirma superar deadband. Si no hay respuesta física, NO_RESPONSE y cierre; no subir automáticamente |
| Giro pedido | 0 rad/s; primera prueba recta. Un giro físico/signo de yaw requiere alcance separado. El límite angular técnico de RoverLimits debe aprobarse positivo; no construir un límite cero inválido |
| Duración de comando | Máximo 3 s: recorrido ideal 0,15 m; no es distancia medida ni garantía física |
| Umbral de aborto por desplazamiento | Propuesta 0,25 m desde posición inicial **observada y atribuida**. Es un disparador observado, **no una cota física máxima**: hasta detectar y detenerse puede recorrer más. Su valor no está aprobado |
| Zona libre | Huella real del vehículo + recorrido máximo + error/localización + distancia durante latencia de parada. No se inventa huella ni margen de suelo a partir de una sola pose |
| Plazo global | Propuesta 20 s para la maniobra/confirmaciones, dentro del límite autorizado del trabajo; si no cabe el cierre, no iniciar. No es sleep ni amplía límites existentes |
| Pérdida/frescura de observación | Umbral pendiente de una serie atribuida con cadencia y latencias medidas. Las muestras seleccionadas no justifican 0,5 s ni una frecuencia del flujo |
| Inclinación | Valor pendiente de revisión de superficie/vehículo. Debe ser un parámetro operativo finito y comprobado antes de emitir y durante cada paso; no usar la etiqueta informativa ni deducir seguridad de 0,55° |
| Armado/modo inicial | Actor y autorización exacta pendientes. No existe permiso implícito ni auto-arm aprobado. Modo/armed deben observarse, no reconstruirse del plan |
| Cierre | HOLD/parada **observada** y, sólo con alcance explícito, DISARM_AFTER_OBSERVED_STOP_V1 con respuesta y observaciones frescas. Cero enviado no basta; incertidumbre conserva reservas, sin reintento automático |

Estos son valores experimentales para revisar, no parámetros ya aprobados ni
una prueba de seguridad. No crean una reserva ni un trabajo ejecutable. Ante una
llamada opaca sin confirmación, conservar UNCONFIRMED; no prometer que un timeout
Python detiene por sí solo el vehículo.

Para sostener una **cota física**, hacen falta cotas justificadas de velocidad
real, antigüedad de observación, intervalo hasta la siguiente comprobación,
latencia del transporte y tiempo/distancia de parada, además del error de
localización. Una expresión conservadora condicionada a esas pruebas sería
`d_fisica <= vmax_real * (3 s + antigüedad + intervalo + latencia + parada)
+ 2 * error_posición`. No sustituir vmax_real por 0,05 m/s pedido. Hoy esos datos
dinámicos no están medidos: la cota física de 0,25 m queda **UNKNOWN** y bloquea
la admisión del pulso, aunque 0,05 × 3 = 0,15 m nominales.

Política preparada para revisar, sin habilitarla: antes de emitir, rechazar
identidad/marco/pendiente/cota desconocidos; durante el pulso, abortar ante
observación caducada, inversión de reloj, pérdida del worker, salida del alcance
o discrepancia de respuesta. Emitir la parada acotada sólo por el transporte
protegido y exigir observación fresca de cese. Una respuesta ausente o parada no
confirmada conserva UNCONFIRMED y reservas; no reanudar, no auto-armar, no ampliar
duración/velocidad ni liberar. Un timeout de llamada opaca sólo acredita falta
de respuesta. Se conservan por separado pulso, navegación realimentada y R1.

**b) Navegación que completaría R1.** Es otro ensayo: objetivo POI_A1 transformado
al marco acreditado, llegada y permanencia dentro de tolerancia resoluble,
recuperación acotada, parada y cierre verificados. El ejemplo
`missions/examples/agri_demo_001_sector_a.json` declara POI_A1 en
41.275071864893995 / 1.9869521890102217 y un home 41.275 / 1.987. Son datos del
plan; no son el origen efectivo del rover. Su altura de 5 m corresponde al plan
aéreo y **no debe convertirse en una orden terrestre**.

La navegación necesita determinar el contrato de origen/desplazamiento de ese
objetivo y medir su transformación, con ajuste y validación independientes.
Distancia, velocidad de crucero, giro máximo, tolerancia y timeout sólo podrán
cerrarse al conocer la ruta y su incertidumbre. Si la cota de error no permite
resolver la tolerancia propuesta, REJECTED; si no hay precisión/origen, UNKNOWN.
No completar con un umbral de 0,5 m por conveniencia. Un pequeño movimiento
observado en (a) no acredita llegada a POI_A1 ni cumplimiento de R1.


### Resultado pasivo revisado y preparación del desplazamiento — 2026-10-26

Sesión headless `e837942d-61b0-428e-8505-ef6ddca38037`, evidencia
[1cb9d86a](../simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/analysis-summary.json).
Una apertura, un lector, una parada; sin armado, modo, escritura de parámetros,
órdenes ni movimiento. No hubo GUI ni confirmación visual solicitada.

Quedaron observados Status/GID→DDS/XRCE→peer, las tres muestras de odometría→
bridge diagnóstico y el plugin real→entidad67 (etiqueta de catálogo rover1)→
pose/JSON-FDM. La biblioteca seleccionada es la única ArduPilotPlugin observada
por maps y hay una instancia configurada por entidad11/67/181. El lector recibió
MAV_SYSID=3 y DDS_USE_NS=1, **pero sin atribución acreditada**: su requesterGUID
es nulo y los GUID nativos de petición/respuesta difieren. No sustituirlos por
ClientKey, endpoint o sequence1. Las tablas de sockets no encontraron el peer y
el lector antiguo no comprobaba EOF; no hay vínculo peer→socket→SITL. El destino
FDM127.0.0.1:60575 sí fue observado desde el socket real del plugin67, pero no su
propietario receptor. La ruta por defecto del OdometryPublisher todavía requiere
su contrato efectivo; la asociación GID→bridge no la completa automáticamente.

| Requisito | Pulso corporal corto, todavía NO autorizado | Navegación a POI_A1/R1 |
|---|---|---|
| Transporte | TwistStamped corporal base_link; entidades DDS de destino vistas, sin orden ni ack/efecto probado; probe físico continúa bloqueado | Mismo transporte más executor/trabajo y cierre autorizados |
| Identidad | Fuentes frescas de ESA futura sesión, SYSID atribuido, bridge/modelo y observación de parada acreditados | Igual; esta captura cerrada no es credencial de una ejecución nueva |
| Marcos | Convenciones +X longitudinal, yaw/giros, pose/velocidad, extrínsecos y observación local del desplazamiento; deben acreditarse | Además, objetivo agrícola y transformación de POI_A1 al marco observado |
| Transformación agrícola | **No se exige** para un pulso corporal que no usa POI_A1; no elimina los requisitos locales anteriores | Obligatoria con origen, incertidumbre, clocks y holdout independientes |
| Límites | Propuestas 0,05m/s y3s=0,15m nominales; umbral observado0,25m no es cota física; latencias/cotas dinámicas pendientes | Distancia, progreso, llegada, permanencia, recuperación y tolerancia resolubles; no importar los límites del pulso |
| Inclinación | Quaternion recibido y rumbo proyectable no constituyen un límite de pendiente aprobado; falta fijarlo y comprobarlo antes/durante órdenes | Igual, para toda la ruta |
| Frescura | La selección retenida a sellos2,36/2,86/3,36s no estima frecuencia, jitter ni edad máxima del flujo completo | Necesita serie actual acreditada y plazos del recorrido |
| Aborto | Fallo de fuente, reloj, identidad, plazo, inclinación o límite observado: parada acotada protegida; confirmación ausente→UNCONFIRMED, sin reanudar/liberar | Igual, más objetivos y recuperación acotados por el plazo global |
| Parada/cierre | Cero enviado no basta; parada observada y cierre protegido; armado/desarmado requieren autorización propia | Parada, resultado del trabajo y aceptación R1 separados |

Se retuvieron pose, quaternion, covarianzas36+36 y velocidades finitas en las
3odometrías; las velocidades retenidas son cero. Eso **no acredita reposo físico**,
modelo completo, precisión ni condiciones dinámicas. La transformación descriptiva
con dos referencias aéreas y holdout rover dio0,0376m de residuo en holdout, pero
cada ancla tiene unos0,774m de residuo y sus baselines difieren1,547m. No está
aceptada: faltan origen, precisión y comparabilidad de relojes. No elegir una
tolerancia para hacerla pasar ni convertir ese ajuste en requisito del pulso.

La infraestructura cerró SUCCESS a21:59:52,959991UTC. El monitor terminó antes,
a21:59:41UTC, INCOMPLETE/rc1 porque aún veía vivo el servidor; el cleanup protegido
lo terminó después con SIGTERM/SIGKILL. El historial nuevo sigue bloqueando otra
apertura y no recibió disposición automática. OPERATIONAL_ROVER_ENABLED=False y
los gates/interfaces que usa el sistema multiagente se conservan. Siguiente trabajo concreto:
validar offline el contrato de correlación RPC y el default del publicador de
odometría; revisar los helpers con lectura EOF antes de pedir otra medición.

### Estado posterior de esos enlaces — 2026-10-27, sin operaciones

La [revisión de e837942d](rover-source-correlation.md#revisión-offline-de-enlaces-e837942d--2026-10-27)
resuelve el default `/model/rover1/odometry` con launch/ECM/bridge originales y lo
consume en `correlate_odometry_model`. La ruta está observada bajo el modelo de
confianza del namespace controlado; no queda pendiente por omisión de odom_topic.
Pose está declarada en odom y twist en base_link; la frecuencia omitida y los
ceros retenidos no prueban comportamiento dinámico, precisión o reposo.

El valor recibido SYSID3 sigue sin atribución. El GUID nulo del cliente no prueba
ausencia de emisor; los GUID del reader del servicio, writer de petición y writer
de respuesta cumplen funciones distintas. Se retiró la unión legacy y se preparó
un registro nativo pre/post-write; falta aún una fuente nativa compatible de
SampleInfo por respuesta del cliente. El contrato probado con fixtures no está
disponible por el take_response público actual. No basta repetir esa consulta.

El inventario nuevo busca destinos FDM reales además del peer XRCE; atribuye
socket sólo con doble búsqueda completa, EOF y contexto. Receptor FDM/SITL y
peer/SITL **no** se recuperaron del ensayo cerrado. Se corrigió offline la
coordinación para que el monitor observe cleanup dentro de sus20s totales,
conservando captura y retorno separados del cierre físico. No se modifica el
INCOMPLETE histórico ni se dispone el descriptor. La validación real de las
correcciones sigue pendiente; no se ejecutó otra sesión ni se habilitó movimiento.

Para un pulso local en base_link se mantienen: destino de comandos atribuido a la
misma instancia, relación acreditada entre observación y modelo, observaciones
actuales/frescas, convención corporal +X/yaw y twist, transformaciones locales
necesarias, límite de inclinación revisado, límites/plazos/aborto y parada
observada con cierre protegido. El quaternion proyectable no aprueba una pendiente.
Una orden enviada o cero aceptado no acredita efecto ni parada. El transporte
físico sigue bloqueado y no hay autorización para armar, cambiar modo o moverse.

La transformación agrícola de POI_A1 **no es requisito** de un pulso que no usa
ese punto. Sí lo son sus propias convenciones/fuentes locales y evidencia dinámica
de frescura, latencia y parada; tres muestras seleccionadas y quietas no las
sustituyen. POI_A1/R1 necesita además origen, transformación e incertidumbre
resoluble del objetivo. No se modificaron el controlador, sus límites, el
coordinador del sistema multiagente ni las interfaces/gates de movimiento en esta revisión.

### Contraste con la revisión independiente del sistema multiagente — 2026-10-27

Revisión leída sin modificarla:
[agri_r1_identity_review](../evaluation/observability/agri_r1_identity_review_2026_10_27/README.md).
Ya incorpora la corrección del rumbo y separa bruto/derivado; no se atribuye a su
versión actual el texto de la primera versión que ella misma rectifica. La
atribución odometría→modelo de su matriz procede de la matriz histórica anterior:
queda resuelta por el consumo de launch/ECM/bridge descrito en la revisión e837942d.
No se cambian sus informes ni los originales de las dos sesiones.

**Contrato mínimo del pulso.** Antes de emitir una orden hace falta atribuir,
en la misma ejecución vigente, la entrada Status y los destinos de cmd_vel y
mode_switch al contexto XRCE/SITL, y la odometría al bridge/modelo correspondiente.
El vínculo FDM/receptor/SITL enlaza las dos ramas; no se deduce de sus nombres,
de un GID estable ni de números SYSID/ClientKey parecidos. Si la política exige
SYSID efectivo, el valor debe estar atribuido por RPC, no sólo recibido. También
se necesitan unidades/convenciones locales +X/yaw/twist, asociación local entre
observación y cuerpo, fuentes actuales/frescas y posibilidad de observar parada.
Ningún diario cerrado concede esas credenciales actuales por sí solo.

No es circular atribuir la fuente **pasivamente**: el default del publisher ya
se cerró mediante la instancia y el log original. Peer y receptor FDM pueden
atribuirse con los inventarios EOF preparados, sin mover el vehículo; RPC necesita
los metadatos nativos exactos pendientes. No se pretende demostrar identidad
mirando si un rover parecido se mueve al enviarle una orden.

El pulso mediría respuesta al comando corporal, dirección/signo, magnitud,
latencia y observación de parada de **ese ensayo**. Esos resultados posteriores
no son precondiciones que ya debieran haberse obtenido del mismo pulso. Sí son
precondiciones la capacidad de mandar parada por el destino correcto, una fuente
capaz de observarla, límites/plazos/autorización y una envolvente de ensayo
revisados. Una cota física garantizada necesita justificación independiente
(fuentes/límites del control, entorno y márgenes conservadores); no se acredita
con velocidad nominal×duración ni se exige como prueba previa el resultado aún
no realizado. La propuesta0,25m no queda aprobada por esta distinción. Si no se
puede justificar la envolvente sin una medida todavía ausente, se revisa el
diseño antes de autorizarlo; no se elimina el bloqueo por conveniencia.

**Qué comprueba realmente el recorrido actual:**

- `admit_ground_trial` y `run_ground_worker` mantienen
  OPERATIONAL_ROVER_ENABLED=False. La admisión rechaza antes de persistir o reservar;
  no hay MCP de movimiento. `start_ground_trial` soporta sólo navegación, no pulso.
- `physical_adapter_factory.build` llama a
  `RoverEnvironmentGuard.require_motion_source` antes de construir NativeRos2Session.
  Ese guard siempre rechaza mientras falte una atribución consumible actual.
  Un MotionBinding bien formado o un grafo estable no permiten saltarlo.
- `Ros2RoverAdapter.probe/observe` contrastan tipos, capacidades y el GID con el
  binding; el transporte Python actual conserva el GID **por muestra como None**.
  Los GID reales del lector C++ son históricos y no están conectados a ese transporte.
- `RoverControlCore.move_for` valida dos observaciones progresivas/frescas y
  velocidades iniciales bajo umbral; exige **GUIDED, armado, external_control y
  sin failsafe**, no HOLD previo. No arma ni cambia modo para lograrlo.
  HOLD se solicita/verifica durante stop. La afirmación «sólo estabilidad de
  GID/procedencia/marco y HOLD» no describe este recorrido completo.
- El núcleo con un doble no autentica la fuente ni acredita por sí solo una
  identidad estable. La tupla de GID/digest/marco se contrasta en navigate y
  finalización; no debe presentarse como un verificador general dentro de move_for.
  La atribución física pertenece al guard/adaptador y actualmente está bloqueada.

Carencias concretas antes de cambiar esa política: consumo actual de identidad
por muestra, unión RPC/FDM/SITL, contrato de convenciones locales y política revisada
de inclinación/envolvente/aborto/parada. Se conservan los bloqueos, sin una bandera
manual verified=True ni un requisito de transformación agrícola para el pulso.

**Versión del controlador.** `_navigation_observation` llama al helper
projected_ground_heading después del gate de marco/procedencia; navigate usa esa
salida. move_for, al recibir velocidades corporales, no calcula rumbo mundial ni
aplica un gate de quaternion plano. El1e-3 actual comprueba norma al cuadrado;
no qx/qy ni ángulo. El rechazo de inclinación sólo se conserva en la clase
archivada que reproduce el test histórico. La muestra del25/10 da89,7694108673°
con el helper actual; sigue sin acreditar por ello su marco o pendiente operativa.
Se corrigieron arriba dos descripciones antiguas que podían confundirse con el
estado actual; la geometría y las interfaces utilizadas por el sistema multiagente no cambiaron.
