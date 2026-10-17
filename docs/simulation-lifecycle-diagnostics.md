# Limpieza de simulación y diagnóstico de espera de waypoint

## Evidencia disponible y límites

Se conserva sin modificar el ensayo `d4519cab-ebd1-4359-b547-44be38294a6a`
en `simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/`:

- `failed_wp3_report.json`: WP1 y WP2 alcanzados, comando para WP3 emitido,
  espera de WP3 agotada a los 180 s, recuperación con aterrizaje y desarmado
  confirmados. El resultado persistido es `FAILED`, no un ensayo aprobado.
- El backend registró inicio de ejecución a las 14:13:39 UTC y fin a las
  14:20:15 UTC del 17/10/2026: aproximadamente 396 s. Según la observación de
  Joel, Hermes agotó su timeout MCP de 300 s mientras el backend continuó.
  Este cambio no modifica ese timeout ni implementa cancelación o tareas asíncronas.
- `failed_wp3_simulation.log` es la copia disponible del log actual
  `/tmp/tfg_demo.log` del contenedor `tfg-ardupilot-gazebo`. No se usa
  `/tmp/tfg_2drones.log`, que pertenece al 6 de octubre.
- El log actual registra retrocesos de tiempo en ambos `robot_state_publisher`
  (líneas 792–825) y la caída de la GUI `ruby /usr/bin/gz sim -v1 -g
  --force-version 8` con exit 139 (línea 2369), con stack OGRE/OpenGL y
  `libd3d12core.so` de WSL. Esto no demuestra que cayese el servidor de física
  ni que la caída o los retrocesos causasen el fallo de WP3.
- Joel observó cuatro `ros2 launch` del proyecto, un servidor Gazebo y dos
  ArduCopter. No hay una tabla histórica completa de procesos que permita
  reconstruir todos sus padres y tiempos de creación. El informe antiguo no
  contiene las muestras de WP3: el diagnóstico nuevo no se añade retroactivamente.

No se ha ejecutado Docker, simulación ni vuelos para este cambio. Las
conclusiones de configuración se basan en los archivos locales y el log guardado;
no se ha inspeccionado de nuevo la instalación efectiva dentro del contenedor.

## Qué lanza realmente el demo

El `start_sim.sh` actual usa `launch/tfg_demo_2drones.launch.py`. El demo incluye
una instancia de `gz_sim.launch.py` para el servidor `runway.sdf` y otra para la
GUI. Cada dron incluye `robots/iris.launch.py`, que a su vez incluye
`robots/robot.launch.py`. En las fuentes upstream locales este último crea:

- `robot_state_publisher` y `ros_gz_bridge/parameter_bridge` por dron;
- un `topic_tools/relay` de `gz/tf` a `tf`, lanzado al iniciarse cada bridge;
- `ros_gz_sim/create` para insertar cada modelo;
- SITL y MAVProxy, y un único micro-ROS agent para el primer dron;
- RViz por dron si se habilita; los scripts actuales lo deshabilitan.

Los `IncludeLaunchDescription` componen el mismo supervisor ROS, no explican
cuatro procesos independientes `ros2 launch`. También hay wrappers Ruby/shell y
posibles descendientes de MAVProxy. Contar sólo ArduCopter y Gazebo no basta para
verificar una parada. Se revisó también `tfg_demo.launch.py`, el demo anterior
con rover: ambos nombres exactos se reconocen para limpiar supervisores antiguos.

## Limpieza y arranque acotados

Antes, `stop_sim.sh` enviaba SIGINT sólo al PID de `/tmp/tfg_demo.pid`; no validaba
su identidad y la verificación final no contaba launch, bridges, relays ni RSP.
El arranque enviaba señales con patrones globales y no esperaba a los launch.
Además, el chequeo de puertos enviaba un heredoc a `docker exec` sin `-i`, por lo
que no aseguraba que el Python del contenedor recibiese ese código.

Ahora ambos scripts despliegan y usan el mismo helper estándar Python
`scripts/sim_processes.py` en `/tmp/tfg_sim_processes.py` dentro del contenedor:

1. Un `flock` no bloqueante en el host serializa start/stop; una segunda operación
   falla sin tocar los procesos. El arranque se detiene si falla la limpieza.
2. Se seleccionan supervisores con tokens argv exactos de `ros2 launch
   ardupilot_gz_bringup tfg_demo.launch.py` o `tfg_demo_2drones.launch.py`, tanto
   ejecutados directamente como mediante Python. Un texto dentro de `bash -c`
   no coincide. No se usan `pkill` ni expresiones globales por nombre.
3. Se descubre todo el árbol descendiente, incluidos supervisores y auxiliares,
   y se conserva su identidad `(pid, start_ticks)` al salir o cambiar de padre.
   Los arranques nuevos heredan `TFG_SIM_PROJECT=Agentic_Drone_Mission_Control`,
   lo que permite reconocer sus huérfanos incluso en una parada posterior.
4. Se envía SIGINT a todos los supervisores/raíces propios y se esperan hasta
   12 s para el cierre ordenado. Después SIGTERM a los supervivientes y hasta
   5 s; finalmente SIGKILL y hasta 3 s. Se vuelve a descubrir el árbol durante
   las esperas y al finalizar. Un superviviente produce fallo, no éxito.
5. Antes de cada señal se vuelve a comprobar PID y tiempo de creación, evitando
   señalar un PID reciclado. El propio helper, su shell, sus ancestros y PID 1
   están protegidos. El PID antiguo de `tfg_demo.pid` no selecciona víctimas.
6. La verificación final abarca todos los procesos atribuibles, incluidos los
   auxiliares. Los zombies no se consideran procesos ejecutándose. Los errores
   de permisos o lectura no se convierten en una parada correcta.
7. Para huérfanos anteriores sin marca, padre ni identidad guardada no se inventa
   propiedad. Si un ejecutable ROS de la instalación conocida usa exactamente
   `/drone1`, `/drone2` o `/rover1`, o un SITL referencia los defaults Gazebo de
   esa instalación, se informa como `unattributed_auxiliaries` y se bloquea el
   éxito/arranque sin enviarle señales. Un nombre de ejecutable aislado no basta.
   Otros huérfanos antiguos sin esos indicios no pueden atribuirse con seguridad;
   esto no es una certificación de ausencia de cualquier proceso del contenedor.
8. El lanzamiento nuevo usa una sesión separada y SIGINT restaurado, sin heredar
   el SIGINT ignorado de un shell en background/nohup. Antes de abrir el log nuevo
   se archiva el anterior como `/tmp/tfg_demo.<UTC>.<sufijo>.log`; no se borra.
   El sondeo de puertos usa ahora `docker exec -i`.

El helper conserva identidades en `/tmp/tfg_demo.processes.json` durante la
limpieza y las elimina tras una parada limpia. Devuelve JSON con señales enviadas,
errores y supervivientes. No selecciona el daemon ROS global ni procesos de otros
demos únicamente por su nombre. La identificación y comprobación por `/proc` reducen carreras
por PID pero no son una primitiva atómica de kernel; la marca tampoco es una
frontera de seguridad frente a procesos que la falsifiquen.

## Clock y bridges: duplicación demostrada y lo que falta

Las fuentes upstream locales inspeccionadas son
`ardupilot_ros2_ws/src/ardupilot_gz/ardupilot_gz_bringup/launch/robots/iris.launch.py`,
`robots/robot.launch.py` y `config/iris_bridge.yaml`. Cada dron crea un bridge
con el mismo bloque `gz_topic_name: /clock`, `ros_topic_name: clock`, dirección
`GZ_TO_ROS`. El log del ensayo confirma dos creaciones de ese bridge (líneas
183 y 187), en los nodos `drone1.ros_gz_bridge` y `drone2.ros_gz_bridge`.

Está demostrada la duplicación de la conexión al origen Gazebo `/clock`. El
nombre ROS configurado es relativo (`clock`), y los nodos llevan namespaces
distintos: no se afirma que el log pruebe dos publicadores sobre un mismo topic
ROS global. Resolver nombres efectivos/remapeos y contar publicadores requiere
una inspección operativa posterior. Ambos SITL registran uso de clock para DDS;
la opción `synthetic_clock` figura en el launch y el log indica que el binario
actual considera `--synthetic-clock` obsoleto porque ese modo está siempre activo.
Esto tampoco demuestra la causa de los saltos de tiempo.

No se modifica esta configuración, AP_DDS, QoS ni publicación de objetivos.
No se añaden reenvíos: su semántica GUIDED/AP_DDS debe revisarse frente al
autopiloto antes de cambiarla, con evidencia de por qué serían necesarios.

## Diagnóstico nuevo de waypoint

Si `_wait_for_waypoint` falla, lanza `WaypointWaitError`, subclase de
`MissionExecutionError`, con diagnóstico estructurado. El executor lo conserva
en `waypoint_diagnostic`, además del error y los eventos anteriores, y sigue
su recuperación LAND habitual. También cubre la espera del regreso al lanzamiento.
El informe del preflight lo conserva en `executor_result.waypoint_diagnostic`.

Incluye:

- vehículo, ID, objetivo latitud/longitud, altura relativa y AMSL;
- tolerancias existentes (1 m horizontal, 0,75 m vertical), sin cambios;
- inicio/fin UTC, tiempo transcurrido monotónico, timeout y exceso de plazo;
- intentos, observaciones de posición obtenidas, último estado y última
  posición con errores horizontal/vertical y edad de esa observación;
- hasta 12 muestras recientes con estado, observación, duración de lecturas y
  errores de adquisición; el total de observaciones se conserva aunque se
  recorte la lista;
- `failure_kind=TIMEOUT` o `WAIT_ERROR`, fase del fallo y tipo/mensaje del error.

`position_outcome=NO_POSITION_OBSERVATION` significa que no se obtuvo ninguna
posición durante esa espera. `POSITION_NOT_REACHED` significa que existe al menos
una observación; la fase y el error indican si terminó por timeout o por un fallo
posterior de telemetría/estado. No se sigue esperando ni se reintenta una lectura
que antes abortaba el vuelo. Un estado desarmado o failsafe sigue abortando.

Las marcas de tiempo son del lector/backend, no timestamps originales del sensor
ni prueba de frescura de ROS. Una llamada ROS puede tardar más que el tiempo
restante del wait: el diagnóstico registra esa duración y el exceso de plazo,
pero no modifica los timeouts internos ni introduce cancelación.

## Validación offline y problemas abiertos

```bash
.venv/bin/python -m pytest -q
```

Se prueban tablas de procesos y señales dobles, cuatro supervisores, auxiliares,
huérfanos, PID reciclado, shell protegido, supervivientes, escalado, conservación
del log y rechazo de arranque tras limpieza fallida. Las pruebas shell usan un
binario Docker falso; no se invoca Docker real. Las pruebas del executor simulan
el reloj y la telemetría, y comprueban diagnóstico, recuperación y persistencia
en el report.

Quedan pendientes la comprobación operativa de esta limpieza, la causa de WP3,
la estabilidad de la GUI WSL/OGRE, los retrocesos de tiempo y la topología efectiva
de clock. El timeout MCP de 300 s es un trabajo separado: perder la respuesta
no demuestra que el backend se haya detenido ni que sea seguro solicitar otro
vuelo. Debe revisarse el informe persistente del ensayo antes de decidir cómo
continuar; este incremento no implementa polling de trabajos ni cancelación MCP.


## Actualización comunicada por Joel y seguimiento asíncrono

Joel confirma la prueba operativa de la limpieza: parada sin procesos restantes
y arranque con un único supervisor ROS2, dos ArduCopter y servidor/GUI Gazebo.
Es información aportada por el operador; durante el incremento asíncrono no se
repitió esa prueba ni se ejecutaron vuelos. La causa del fallo WP3 sigue abierta.

El [seguimiento asíncrono](async-virtual-preflight.md) aborda por separado la
espera MCP: inicio persistente y consulta del mismo ensayo. Las herramientas
síncronas y el timeout observado no se modifican. Se conservan el diagnóstico de
waypoint y las evidencias, sin reconstruir observaciones que no se registraron.
