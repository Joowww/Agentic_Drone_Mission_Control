# Perfil de simulación consumido por runtime — 20/10/2026

Implementación y verificación **offline**. `two_drones` permanece predeterminado;
`two_drones_rover` añade infraestructura y readiness, sin executor de rover ni
autorización de movimiento. La nueva topología no se ha probado operativamente.
Este documento no autoriza operaciones ni vuelos simultáneos.

## Qué cambia

[simulation_profiles.py](../tools/simulation_profiles.py) deja de ser únicamente
un catálogo para tests. Es la fuente local de valores confiables que consumen:

- [Lifecycle](../tools/simulation_lifecycle.py): valida el nombre antes de crear
  mutex/operación o ejecutar procesos, lo registra en el lease y la operación y lo
  pasa al backend por `TFG_SIM_PROFILE`. El verificador del backend exige que coincida
  con el perfil del lease protegido, además de sus comprobaciones previas de
  identidad del proceso, descriptor y mutex.
- [Backend de arranque](../simulation/ros2_gazebo/scripts/start_sim_backend.sh):
  obtiene paquete y archivo launch, puertos a esperar y tópicos status mediante un
  CLI local de campos de datos. Conserva la copia del launch a source/install y
  copia también el módulo de perfiles junto al helper dentro del contenedor.
- [Supervisor](../simulation/ros2_gazebo/scripts/sim_processes.py): resuelve el
  perfil antes de inspeccionar/iniciar procesos; construye la lista de argumentos
  de `Popen` con su paquete, launch y argumentos fijos. En el contenedor puede
  importar la copia standalone, sin necesitar el paquete `tools` instalado allí.
- [Readiness](../tools/simulation_status.py) y [su script](../simulation/ros2_gazebo/scripts/check_sim.sh):
  resuelven el perfil antes de llamadas operativas y utilizan mundo, proceso y
  cantidad esperada, tópicos y servicios prearm derivados del perfil.

El CLI sólo devuelve campos del perfil incorporado en el código. No acepta rutas,
comandos ni definiciones de vehículos del solicitante. No se usa `eval` ni se
interpolan datos del solicitante en código shell; los argumentos variables de las
lecturas se pasan como parámetros posicionales a fragmentos shell constantes.
Un nombre vacío, desconocido o con sintaxis shell no selecciona otro launch.

## Compatibilidad por defecto

| Parámetro | Valor conservado |
| --- | --- |
| Perfil | `two_drones` |
| Paquete / launch | `ardupilot_gz_bringup` / `tfg_demo_2drones.launch.py` |
| Mundo | `runway` |
| Vehículos/interfaces | drone_01→v1, drone_02→v2; modelos drone1 y drone2 |
| RViz | `false` |
| GUI | Activada por defecto; `--headless`/`gui=False` conserva la selección existente |
| Puertos aguardados | 5760, 5770 |
| Procesos de SITL esperados | Dos `arducopter` |
| Disponibilidad | Docker container, Gazebo server, ArduPilot processes, ROS 2 vehicle interfaces, Pre-arm checks |

Se mantienen los bucles/plazos existentes: espera de puertos, espera de status al
arrancar, 15 intentos de descubrimiento en readiness y 18 de prearm con timeout de
30 s por servicio. Readiness sigue sin armar ni despegar, pero llama a servicios
prearm; no es sólo lectura de logs. READY no confirma imagen de la GUI.
El mensaje del backend ahora describe el modo GUI **solicitado**, no una imagen
observada. La confirmación visual del operador sigue separada.

La API existente, sin perfil explícito, sigue usando dos drones. Python permite
`run_lifecycle(action, gui=..., profile="two_drones")` y
`check_simulation_ready(profile="two_drones")`; el CLI lifecycle añade
`--profile two_drones`. No se amplía el esquema MCP ni se instala un selector global.
Los nombres desconocidos devuelven bloqueo/error antes de operaciones. No se migra
ninguna operación o reserva histórica: un lease viejo/incoherente no se convierte
en permiso válido por atribuirle silenciosamente el nuevo perfil.

## Exclusión y límites

No cambia el orden mutex global→registro, la reserva lifecycle durante stop/start,
la barrera UNCONFIRMED ante fallo ni la exclusión de admisiones entre hijos de una
secuencia. No se cambia executor, gate, tolerancias, geometría o reconciliación.
El módulo de perfiles no es autoridad de vuelo ni sustituye las reservas.

Este incremento **no genera la topología del launch desde el perfil**. Modelos,
posiciones, construcción del mundo y detalles de bridges/sensores siguen en el
launch y dependencias upstream; se contrastan offline para detectar divergencias.
Los bindings de control/flight siguen en `simulated_vehicle.py` y se contrastan,
no se amplían desde el perfil. La lista histórica de launches reconocidos para
limpieza conserva ambos launches. Readiness ahora recorre todos los tipos y
cantidades de SITL declarados por el perfil (dos tipos para la topología con rover).
No se prueban versiones/copias instaladas, puertos efectivos o renderizado real.

Las pruebas usan Bash en proyectos temporales, Docker/ROS/Popen doblados y muestras
sintéticas. Cubren parámetros efectivos, mutaciones, perfil desconocido antes de
operar, CLI/helper standalone, defaults, GUI/headless y exclusión con los mutex del
proyecto. No autentican consentimiento ni constituyen validación operativa.

## Límite de integración de movimiento del rover

El perfil de infraestructura descrito al final permite preparar la topología.
Un futuro executor para rover exigiría otra revisión: comandos y diagnóstico,
admisión/reservas/reconciliación de v3 y consentimiento específico. Los controles
de vuelo y reconciliación técnica actuales sólo contemplan v1/v2; no se amplían
desde un catálogo de infraestructura. No basta añadir una entrada a `PROFILES`.
La nueva infraestructura requiere una autorización operativa independiente;
después correspondería otra autorización
para la campaña propuesta de rendimiento (`docs/rover-performance-test-protocol.md`,
documento separado de este incremento),
que continúa propuesta, no autorizada y no ejecutada.

## Regresión operativa futura de `two_drones` — preparada, no ejecutada

**NO AUTORIZADA por este documento.** Son dos pruebas independientes, GUI y
headless, cada una con un único arranque y una parada protegidos. No son una
campaña de rendimiento ni incluyen misiones, preflight, reconciliación o vuelos.
No ejecutar los bloques juntos, en paralelo o como un script que avance sin revisar
los resultados. No se han ejecutado al documentarlos ni se ha repetido la suite.

Antes de cada prueba: autorización específica, identidad actual del entorno
comprobada, sin ejecución activa, procesos ambiguos ni reservas activas/inciertas
de vehículo, secuencia, lifecycle o reconciliación. Los registros en `history/`
son historia, no guard activos. El arranque debe volver a comprobar la exclusión
atómicamente: no borrar reservas ni utilizar Docker o el backend privado para
eludir un bloqueo. Si el entorno ya está arrancado, no usar `start` como reinicio
implícito; detener la preparación y revisar/autorizar su cierre por separado.

Todos los comandos siguientes se ejecutarán desde la raíz, en una terminal con
acceso autorizado al entorno. No usar `sudo`, cambiar permisos o cambiar el
contexto Docker automáticamente si falla el acceso.

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control
```

### Prueba G: GUI, un único ciclo

**G1. Arranque protegido**, esperar a su resultado final antes de G2:

```bash
.venv/bin/python -u -m tools.simulation_lifecycle start --profile two_drones
```

Esperado: JSON `success=true`, `status=SUCCESS`, `operation.state=FINISHED`,
`operation.action=start`, `operation.profile=two_drones`, `operation.gui=true` y
`visual_confirmation=OPERATOR_REQUIRED`. Conservar el JSON, owner_id, tiempos y
`operation.log_path`; el retorno del arranque y su espera de tópicos no sustituyen
readiness. No dar por buena la GUI por el texto del log ni por el PID.

**G2. Readiness posterior al arranque**, una sola invocación:

```bash
.venv/bin/python -u -c 'import json,sys; from tools.simulation_status import check_simulation_ready; r=check_simulation_ready(profile="two_drones"); print(json.dumps(r,ensure_ascii=False)); sys.exit(0 if r.get("ready") else 1)'
```

Esperado: JSON `profile=two_drones`, `status=READY`, `ready=true`, `return_code=0`
y salida de los cinco controles: Docker container, Gazebo server, ArduPilot
processes (dos ArduCopter), ROS 2 vehicle interfaces (v1/v2) y Pre-arm checks de
ambos. La llamada incluye servicios prearm y sus reintentos internos existentes;
no arma ni despega. No añadir un bucle externo de reintentos.

**G3. Confirmación visual independiente**, respuesta literal del operador con hora:

```text
¿Ves la pista y ambos drones correctamente en Gazebo, está negra toda la ventana o sólo el panel 3D, faltan modelos o no se abrió ninguna ventana?
```

Esperado para completar la rama GUI nominal: el operador confirma pista y ambos
drones visibles. Guardar hora de recepción y, si se conoce, de observación;
captura sólo con su autorización. READY y confirmación visual se registran por
separado. Una ventana negra, ausente o incompleta es incidencia: preservar sus
logs antes de otra apertura, sin concluir que cambió la seguridad de vuelo.

**G4. Parada protegida**, sólo cuando corresponda al cierre autorizado y no haya
aparecido actividad/restricción incierta:

```bash
.venv/bin/python -u -m tools.simulation_lifecycle stop --profile two_drones
```

Esperado: `success=true`, `status=SUCCESS`, `operation.state=FINISHED`,
`operation.action=stop`, `operation.profile=two_drones` y
`visual_confirmation=NOT_REQUESTED`. Revisar su `backend.log`: limpieza con
`remaining=[]`, sin errores ni auxiliares sin atribución. La mera finalización de
un proceso o desaparición de una ventana no sustituye ese resultado.

**G5. Readiness posterior a la parada**, sólo después de terminar G4:

```bash
.venv/bin/python -u -c 'import json,sys; from tools.simulation_status import check_simulation_ready; r=check_simulation_ready(profile="two_drones"); print(json.dumps(r,ensure_ascii=False)); sys.exit(0 if r.get("ready") else 1)'
```

Esperado: JSON `status=NOT READY`, `ready=false`, `return_code=1`; **el código 1 de
este comando es esperado tras la parada**, siempre que exista ese JSON y el motivo
sea coherente. La parada ordinaria deja el contenedor activo: normalmente pasa
Docker container y falla Gazebo server por ausencia del mundo runway; los controles
posteriores no se ejecutan. Un traceback, timeout o Docker inaccesible no demuestra
la parada correcta. Si continúa READY o quedan procesos atribuibles, no empezar
otra prueba ni repetir la parada automáticamente.

### Prueba H: headless, otro ciclo autorizado

Empezar sólo después del cierre confirmado de G, o desde un entorno detenido
comprobado por separado. No es un fallback automático para una GUI negra. Requiere
autorización propia y las mismas precondiciones de exclusión.

**H1. Arranque protegido headless**:

```bash
.venv/bin/python -u -m tools.simulation_lifecycle start --profile two_drones --headless
```

Esperado: `SUCCESS`, `operation.state=FINISHED`, `operation.profile=two_drones`,
`operation.gui=false` y `visual_confirmation=NOT_REQUESTED`. Conservar sus propios
owner_id y logs. El backend debe registrar GUI solicitada `false`; no atribuirle
el log o ventana del caso G. El flag y la ausencia de ventana no prueban por sí
solos el inventario completo de procesos o ausencia de renderizado de sensores.

**H2. Readiness**, después de terminar H1:

```bash
.venv/bin/python -u -c 'import json,sys; from tools.simulation_status import check_simulation_ready; r=check_simulation_ready(profile="two_drones"); print(json.dumps(r,ensure_ascii=False)); sys.exit(0 if r.get("ready") else 1)'
```

Esperado: el mismo READY y los mismos cinco controles que en G2. No se reduce el
criterio por carecer de ventana.

**H3. Observación del operador**, separada de los controles del backend:

```text
Esta prueba solicita headless: ¿ha aparecido inesperadamente alguna ventana de Gazebo o sigue abierta una de un intento anterior?
```

Esperado: ninguna ventana nueva; confirmación de escena renderizada **NO APLICA**.
No pedir al operador que certifique imágenes o contacto con suelo que no puede
ver. Una ventana inesperada exige revisar atribución y logs; no cerrarla mediante
señales ni convertir la prueba en GUI sobre la marcha.

**H4. Parada protegida**, una vez revisado el caso:

```bash
.venv/bin/python -u -m tools.simulation_lifecycle stop --profile two_drones --headless
```

Esperado: SUCCESS/FINISHED, perfil correcto y limpieza confirmada como en G4.
`--headless` conserva `operation.gui=false` en este cierre; la parada no necesita
ni solicita una confirmación visual de escena.

**H5. Readiness posterior**, únicamente al terminar H4:

```bash
.venv/bin/python -u -c 'import json,sys; from tools.simulation_status import check_simulation_ready; r=check_simulation_ready(profile="two_drones"); print(json.dumps(r,ensure_ascii=False)); sys.exit(0 if r.get("ready") else 1)'
```

Esperado: NOT READY por Gazebo ausente, con los mismos matices y código de salida
esperado que en G5. No ejecutar otro arranque para «confirmar» el cierre.

### Evidencia y condiciones para detener la prueba

Separar carpetas/identificadores G y H. Conservar sin sobrescribir JSON de cada
operación y readiness, UTC de pared, perfil/GUI efectivos, `owner_id`, rutas
`missions/generated/simulation_lifecycle/<owner_id>/operation.json` y `backend.log`,
respuesta del operador y logs GUI/OGRE/servidor asociados al arranque, con tamaños
y hashes. Esos paths se obtienen de las respuestas, no de UUID inventados.
Los logs del arranque no acreditan por sí solos ausencia posterior de procesos;
conservar también el resultado de limpieza y el readiness posterior.

Detener el avance nominal ante BLOCKED, ERROR, UNCONFIRMED, timeout, respuesta
perdida, perfil/modo discordante, guard incierto, proceso ambiguo, readiness inicial
no READY, imagen incorrecta en G, ventana inesperada en H o cierre no confirmado.
No avanzar al siguiente caso ni reintentar, reiniciar, reconciliar o liberar reservas
automáticamente. Preservar la evidencia y revisar el estado. Una parada de limpieza
tras una incidencia sólo procede si está incluida en la autorización y lifecycle
la permite; no eludir una restricción ni usar esta guía como parada de emergencia.
Ningún resultado de estas pruebas concede consentimiento para vuelo o para rover.

## Comparación offline de las aperturas del 20/10 y diagnóstico de readiness

Se conservan los originales sin modificaciones. Fuentes: apertura
[A, imagen correcta según Joel](../simulation/ros2_gazebo/results/gui_diagnostic_2026_10_20/2d62a398-be5e-42fb-9718-6c2d2316ba75/)
y [B, regresión no superada](../simulation/ros2_gazebo/results/profile_two_drones_gui_2026_10_20/ce739b85-c011-46fe-900d-d0da74925424/).
Manifiestos recalculados: A 25/25 y B 28/28 entradas coinciden en tamaño/SHA-256.
En A se usan `after/0,1,2,3,4,6`; en B `opening_logs/0,1,2,3,4,6`.
Los candidatos 5 y 7 de B son de la apertura anterior y se excluyen del contraste.

| Aspecto | Contraste demostrado |
| --- | --- |
| Resultado | A: readiness READY en unos 94 s y respuesta «Veo la pista y ambos drones correctamente». B: timeout a 180 s y respuesta «Ventana negra o escena incompleta». No hay screenshots ni hora exacta de observación. |
| Comando efectivo conservado | Ambos `capture.json` registran `/usr/bin/python3 /opt/ros/humble/bin/ros2 launch ardupilot_gz_bringup tfg_demo_2drones.launch.py rviz:=false gui:=true`. |
| Mundo/configuración | Ambos `6/server_console.log` cargan la misma ruta instalada de `runway.sdf`. `3/gui.config` es idéntico byte a byte: SHA-256 `2b2502d7826d50762b96cda492c8d884b9aa578b9a1365f9a9a8dd887b9c35de`. |
| Gráficos | Ambos `2/ogre2.log` declaran D3D12/Intel UHD y contienen seis excepciones OGRE de materiales/shaders; ambos `1/auto_default.log` tienen 18 mensajes de URI no resuelta. Su presencia no explica por sí sola el resultado diferente. A también registra «Texture memory budget exceeded. Stalling GPU», ausente en esa copia de B. |
| Diferencia del servidor | B `6/server_console.log:448–449`: a las 15:49:17 UTC (17:49:17 CEST) registra `Rewinding simulation back to initial time` y `Resetting Physics`; siguen 20 avisos `Failed to find link` y 18 `Failed to find joint`. Estos mensajes no aparecen en las copias correspondientes de A. |
| Enlace SITL | En `0/tfg_demo.log`, A tiene 10 mensajes `No JSON sensor message received` al principio, y después GPS/batería; B tiene 738 y 264 `no link`, persistentes hasta el final capturado. Son conteos de copias con ventanas de duración distintas, no tasas comparables ni una medición de rendimiento. |

El rewind precede al inicio de readiness de B (15:49:30 UTC) y ofrece una pista
concreta de reset/pérdida de progreso de simulación/enlace. **No consta quién o qué
lo solicitó**, ni prueba que causara la imagen incorrecta o el timeout. Los dos
servidores registran conexión inicial a ambos controladores; eso no confirma su
continuidad posterior. Tampoco hay crash confirmado por `process has died`/`exit
code` en esas copias; un inventario filtrado que omite un ejecutable no demuestra
su muerte. No se infiere suelo ni estado de vuelo a partir de estos logs.

A corresponde a HEAD ff0afab, antes de perfiles; B a 26c594b. La revisión de Git
no muestra cambios al launch de dos drones en ese intervalo. El cambio de perfiles
añade resolución/lease, copia del módulo standalone y parametriza comandos antes
literales: se resuelven al mismo launch, mundo, procesos, interfaces y servicios.
Prearm sigue consultando v1/v2 secuencialmente, con 30 s por servicio y el plazo
exterior de 180 s ya existente. No se añade una orden de reset en ese incremento.
El mismo motor y contenedor figuran en los prechequeos; no garantiza estado
idéntico entre aperturas. Faltan hashes pareados de todos los modelos/mundo
instalados, estadísticas de progreso/pausa, recursos y origen del reset. No hay
base para culpar al perfil, renderer o URI concreta ni para cambiar configuración.

### Corrección acotada de pérdida de salida al agotar el plazo

`check_simulation_ready` captura ahora `subprocess.TimeoutExpired` y devuelve
`ready=false`, `status=ERROR`, `return_code=null`, `timed_out=true` y
`partial_output=true`. Conserva `stdout`/`stderr` separados y el `output` combinado,
excepción, perfil, comando/cwd, timeout configurado, UTC de inicio/fin y duración
monotónica de pared. Los bytes que entrega Python en el timeout se decodifican
UTF-8 con sustitución de secuencias inválidas para permitir serialización JSON;
no es una copia binaria del pipe. Salida ausente queda vacía, no se reconstruye.
No se deducen controles completados del último encabezado, ni siquiera de un texto
aparentemente exitoso cuando no hay retorno final. El plazo sigue en **180 s**;
no hay reenvío ni intento adicional. El retorno normal mantiene su contrato.
La corrección no recupera retrospectivamente la salida perdida de B, no arregla
su GUI y no cambia la gestión existente de subprocesos al vencer el plazo.

Verificación nueva: `tests/test_simulation_status.py` usa un script temporal que
emite en ambos streams y después se bloquea hasta un timeout real local; además
comprueba bytes, texto, ausencia, texto de éxito sin retorno y contrato normal.
Con `tests/test_simulation_profiles.py`: **53 passed in 49.38s**. Sin Docker, ROS,
Gazebo ni carga de Hermes. No se repite la suite completa para este cambio acotado.

### Siguiente comprobación mínima pendiente de nueva autorización

El entorno se dejó parado. Una lectura ahora no puede medir el progreso de la
simulación anterior; no arrancar sólo para reconstruirlo. En una futura apertura
única autorizada, con prechequeo/lifecycle protegido y sin pulsar controles de
reset/pausa, conservar en paralelo: salida de readiness corregida, logs de ese
arranque y dos muestras acotadas de estadísticas del mundo runway (iteraciones,
tiempo simulado y estado de pausa) separadas por un intervalo de pared monotónica.
Verificar antes el stream disponible mediante introspección de lectura, sin
inventar un topic o llamar a servicios de control. Registrar la observación visual
literal con hora. Si ocurre rewind, preservar timestamp y actividad conocida de
clientes sin atribuir autoría ausente. Progreso detenido/rewind y enlace perdido
apuntarían al camino servidor/SITL; progreso y readiness correctos con imagen mala
acotarían el problema visual. El último encabezado de readiness sólo localiza un
tramo pendiente, no su causa ni su terminación. Si falla: capturar, cerrar sólo por
parada autorizada/protegida, sin bucle ni reinicio. Esta propuesta no autoriza nada.

## Perfil `two_drones_rover`: infraestructura implementada offline

Seleccionable explícitamente en lifecycle y readiness; `two_drones` sigue siendo
el default de Python, scripts y CLI. No se amplía el esquema MCP ni se habilita
un executor de rover. `rover_01` es un identificador **local del catálogo de
infraestructura**, no un nuevo MissionDefinition.vehicle_id admitido.

| Componente | Configuración respaldada / expectativa |
| --- | --- |
| Launch | `ardupilot_gz_bringup/tfg_demo.launch.py`, histórico del repositorio, sin modificarlo. `rviz:=false`; GUI elegida por lifecycle. |
| Modelos y spawn | drone1/drone2: IRIS, (-2,0,0.195)/(2,0,0.195); rover1: WILD_THUMPER, (0,-3,0.195). Roll/pitch 0, yaw 1.5708, según launch. Son posiciones declaradas, no medidas. |
| Instancias/sysid | 0/1, 1/2 y 2/3, por enumerate del launch; sólo la primera instancia solicita agente DDS. |
| SITL | Esperados dos `arducopter` y un `ardurover`; el hijo local `wildthumper.launch.py` declara command=ardurover y modelo JSON. Readiness cuenta ambos tipos exactamente. |
| Defaults de rover | El hijo local carga `rover.parm`, `rover-skid.parm`, `dds_udp.parm`, `dds_use_ns.parm`; reloj sintético True. No se inspecciona ni cambia la copia del contenedor. |
| Interfaces | Esperadas v1/v2/v3: `DDS_USE_NS 1` y AP_DDS construye `v<MAV_SYSID>`. Se requieren los tres `/ap/vN/status` y servicios `/ap/vN/prearm_check`. Es expectativa hasta la futura comprobación operativa. |
| Puertos | Se aguarda liberación de 5760/5770/5780 antes del arranque; derivados del base 5760 + 10×instance del SITL local. No son sockets observados ni un inventario exhaustivo de puertos DDS/Gazebo. |

Fuentes upstream **locales de sólo lectura**, bajo
`/home/joelm/TFG/ardupilot_ros2_ws/src/`, no garantía de la instalación:

- `ardupilot_gz/ardupilot_gz_bringup/launch/robots/wildthumper.launch.py`:
  SHA-256 `ede33db7bd6217f42eaac0c44fcd1fd7dd0b8e201c2ed854e6ef6361c4c947f1`.
- `ardupilot/Tools/ros2/ardupilot_sitl/config/default_params/dds_use_ns.parm`:
  `c477789f5a7a02d466d261a87d2bf7d9e0cabed5c0b9728b2e20e0ae14f9956e`.
- `ardupilot/libraries/AP_DDS/AP_DDS_Client.cpp`: `dds_format_name` y `use_ns`;
  SHA-256 `f512901b5c3617aa46861a967ef1cddb2515878523b1fbf240bbb54333ceaef4`.
- `ardupilot/libraries/AP_HAL_SITL/SITL_cmdline.cpp`: base 5760 e incremento por
  instancia (líneas 253–256 y 453–454 de la copia revisada).

El supervisor ya reconoce ambos launches y todos sus descendientes/identidades
recordadas. Se añade la detección de `ardurover` huérfano que refiere defaults de
rover en ardupilot_sitl: bloquea como propietario ambiguo, **nunca** se convierte
en objetivo de señales sólo por sus argumentos. Se mantienen comparación de
start_ticks antes de señales, protección de ancestros y retención de incertidumbre.
La misma exclusión global bloquea start/stop/restart si existe reserva incierta,
sea cual sea el perfil solicitado. No se cambia ni se libera ninguna reserva.

Readiness recorre todos los procesos/tópicos/servicios del perfil. Su respuesta
Python añade `vehicles`: identificadores, interfaces, servicios, capacidad de
executor y última observación explícita `PASS/FAIL/NOT_OBSERVED` de status/prearm.
Un FAIL de prearm puede ser un intento intermedio; sólo el resultado global final
confirma readiness. En timeout se conserva lo observado sin inventar el resto.
`movement_authorized=false` y el scope lifecycle es exclusivamente infraestructura.
El conteo de procesos y un topic presente no autentican identidad o contacto con
suelo. Prearm es una consulta de servicio; no arma ni mueve.

`resolve_vehicle`/executor siguen rechazando rover_01 y v3 antes de reservar o
controlar. Reconciliación técnica, telemetría de vuelo y locks por vehículo siguen
limitados a v1/v2; una restricción global no se sortea con el nuevo perfil. Si un
cliente externo moviera el rover, este incremento no aporta su reconciliación ni
una recuperación de movimiento: detener la prueba y conservar incertidumbre.
No se afirma separación física, coordinación, movimiento validado o rendimiento.
Faltan dependencias instaladas, parámetros efectivos y validación operativa; si
faltan el hijo/modelo/DDS, start/readiness falla y se conserva UNCONFIRMED cuando
corresponda, sin fallback a dos drones ni reintentos automáticos.

Pruebas nuevas con dobles: launch de tres robots, GUI/headless, copias y puertos,
dos tipos de proceso, ausencia/exceso de rover, v3 ausente/prearm fallido, respuesta
por vehículo, timeout parcial, exclusión e imposibilidad de ejecutar misiones de
rover, limpieza de árbol y huérfano ambiguo. **93 passed in 66.81s** en los cinco
módulos pertinentes; tras añadir tres regresiones finales, **3 passed, 56 deselected
in 1.58s**. No se ejecuta suite completa ni operaciones de simulación.

### Prueba mínima futura, no autorizada ni ejecutada por este documento

1. Autorizar explícitamente infraestructura de tres vehículos; prechequeo actual
   de motor/contenedor, procesos y reservas. Si hay incertidumbre, no iniciar.
2. Una sola vez: `.venv/bin/python -u -m tools.simulation_lifecycle start --profile two_drones_rover`.
   Exigir SUCCESS/FINISHED y perfil correcto. No seleccionar este perfil mediante
   una misión ni llamar a start/restart para superar un fallo.
3. `.venv/bin/python -u -c 'import json; from tools.simulation_status import check_simulation_ready; print(json.dumps(check_simulation_ready(profile="two_drones_rover"),ensure_ascii=False))'`.
   Exigir READY y observaciones PASS de status/prearm de v1/v2/v3. Confirmar
   visualmente pista, dos drones y rover; guardar respuesta y logs por separado.
4. Con autorización de lectura, obtener muestras actuales de status de las tres
   interfaces usando la CLI ROS instalada, verificando tipo/campos, sin comandos
   de modo/armado. El proyecto no ofrece una consulta de vuelo v3 compatible: no
   pasar v3 a los helpers v1/v2 ni inventar un resultado. Si no puede verificarse
   estado no armado/sin movimiento, cerrar como prueba incompleta; no avanzar a
   misiones ni tomar prearm como confirmación de suelo o de desarmado.
5. Cierre por `.venv/bin/python -u -m tools.simulation_lifecycle stop --profile two_drones_rover`,
   sólo si la exclusión lo permite. Después, readiness con el mismo perfil debe
   indicar NOT READY por Gazebo ausente; confirmar limpieza/guards y conservar
   manifiesto. Ante fallo, no repetir ni desbloquear. GUI negra se conserva, no se
   cambia renderer ni se reinicia. Rendimiento requiere otra campaña/autorización.

## Diagnóstico prearm por intento y análisis de progreso — 20/10/2026

Corrección **offline**, sin ejecutar servicios ni modificar las evidencias de
[f7f8c84f](../simulation/ros2_gazebo/results/two_drones_progress_gui_2026_10_20/f7f8c84f-1187-4c9f-939d-48931f8b548c/).
Sus marcadores FAIL históricos no contienen las respuestas originales: no permiten
afirmar retrospectivamente negativa del autopiloto, error de cliente o timeout.

### Contrato interpretado y registro incremental

La fuente local `AP_DDS/Idl/std_srvs/srv/Trigger.idl` confirma request vacío y
response con boolean `success` y string `message` (SHA-256
`04ccce8b09a4f790806ff337df3b3bb3ecd9beead2a9ee9bda2fcda1863d7fcb`).
En `AP_DDS_Client.cpp:1095–1120`, prearm asigna
`success=AP::arming().pre_arm_checks(false)` y message `Vehicle is Armable` o
`Vehicle is Not Armable`. La respuesta negativa es genérica, no identifica por sí
sola GPS, EKF, batería o motivo físico. Es fuente upstream local ya identificada
arriba, no una nueva consulta al contenedor ni garantía del binario instalado.

[prearm_diagnostics.py](../tools/prearm_diagnostics.py) es un helper interno del
script; no añade herramienta MCP ni autoridad de movimiento. Usa el mismo servicio
y tipo, conserva el timeout de cliente **30 s**, 18 rondas, intervalo de 5 s y plazo
exterior **180 s**. Añade diagnóstico verbose del wrapper timeout y un plazo local
de 30 s al cliente Docker de lectura; no se amplían las esperas. No cambia AP_DDS,
request, comprobaciones, renderer o física. Ante el plazo local sólo se termina
el cliente de lectura; no se envían señales a procesos de vehículos. La consulta
remota sigue acotada por su wrapper; no se certifica su terminación desde la falta
de respuesta exterior.

Cada llamada emite inmediatamente eventos `TFG_PREARM_EVENT` de inicio, chunks
stdout/stderr y finalización en JSON, sin guardarlos primero en una sustitución
de comando Bash. Se conservan por interfaz/intento: servicio/tipo, comando/request,
timestamps UTC/monotónicos, timeout, streams separados, retorno, duración de pared,
respuesta interpretada y base del resultado. `simulation_status.py` devuelve el
historial `vehicles[].prearm_attempts`, incluso cuando vence el plazo exterior.
Si falta el evento final, se conservan los chunks disponibles con
`INCOMPLETE_AT_CAPTURE`: retorno, duración final y expiración del cliente son
desconocidos, no una negativa inventada. Se conserva la hora monotónica del último
chunk. Sólo se puede capturar lo que el cliente haya emitido; buffers no enviados
o bytes posteriores a la captura exterior no se reconstruyen. La decodificación
UTF-8 usa sustitución para secuencias inválidas; no se promete un archivo binario
de los pipes.

| Clase | Evidencia necesaria |
| --- | --- |
| ACCEPTED | Cliente termina con código 0, streams cerrados y respuesta Trigger íntegra con `success=True`. |
| NEGATIVE_RESPONSE | Mismas condiciones de respuesta/retorno, con `success=False`; message literal, incluso vacío. |
| SERVICE_UNAVAILABLE | Cliente falla y declara explícitamente servicio no disponible en sus streams; es diagnóstico del cliente, no respuesta del autopiloto. |
| TIMEOUT | Vence el plazo local, o retorno 124 acompañado del diagnóstico inequívoco del wrapper timeout. Un 124 aislado es error de ejecución, no prueba de causa. |
| EXECUTION_ERROR | Fallo de arranque del cliente o retorno no cero sin evidencia suficiente de las clases anteriores. |
| UNINTERPRETABLE_RESPONSE | Retorno 0, pero sin respuesta Trigger válida; `success=True` en texto suelto/request no basta. |
| INCOMPLETE_CAPTURE / INCOMPLETE_AT_CAPTURE | Streams no cerrados o evento final ausente; nunca habilitan READY. |

La respuesta de la CLI se interpreta con AST restringido, sin `eval`: envoltura
`response:`, tipo Trigger_Response y campos boolean/string comprobados. Un formato
de CLI desconocido queda no interpretable y preservado para revisión. Mensajes de
espera por disponibilidad no prueban ausencia durante todo el intento. La llegada
de una respuesta final válida tras una espera prevalece sobre ese texto anterior.
READY sigue requiriendo que todos los servicios sean aceptados en la misma ronda
y que el script termine satisfactoriamente; cualquier incertidumbre falla cerrado.

El parser admite `.TFG_READINESS_VEHICLE` y prefijos de varios puntos; el script
añade salto de línea al progreso para no producir esa concatenación nueva.
Esto corrige visibilidad, no reinterpreta los FAIL históricos como otra cosa.

### Evolución medida en las series ya conservadas

Fuentes: `stats_received.jsonl` de f7f8c84f (tres vehículos, 336 muestras) y
[bc11ff6e](../simulation/ros2_gazebo/results/two_drones_progress_gui_2026_10_20/bc11ff6e-67d0-4bef-a225-1911c016bfe4/)
(dos drones, 1.536). Ventanas relativas a **la primera recepción de cada corrida**;
se muestran primera→última muestra realmente recibida, sin interpolar los bordes.
Los intervalos son de reloj monotónico del receptor; las cifras interiores son
tiempo simulado del mensaje, no tiempo en vuelo ni RTF del publicador.

| Ventana recepción (s) | Tres vehículos: n / sim (s) | Dos drones: n / sim (s) |
| --- | --- | --- |
| [0,30) | 117 / 0,004→1,764 | 251 / 0,290→4,801 |
| [30,60) | 53 / 1,781→2,387 | 236 / 4,819→9,122 |
| [60,90) | 26 / 2,401→2,690 | 221 / 9,145→12,897 |
| [90,120) | 41 / 2,701→3,187 | 210 / 12,901→16,290 |
| [120,150) | 29 / 3,201→3,491 | 217 / 16,301→20,167 |
| [150,180) | 37 / 3,501→3,900 | 197 / 20,187→23,191 |
| [180,210) | 33 / 3,901→4,299 | 204 / 23,201→26,562 |

Cobertura entre primera y última recepción: 203,427 s frente a 209,892 s. Mayor
hueco entre recepciones: **8,900 s frente a 0,790 s**. Por ejemplo, en la ventana
rover [60,90) las recepciones abarcan sólo 68,47–85,76 s; en [180,210),
180,05–203,43 s. No completar los huecos suponiendo pausa o progreso uniforme.
No se observa retroceso entre las muestras, sin demostrar ausencia entre ellas.
Frecuencia del publicador, transporte, buffers y planificación del lector pueden
afectar esa densidad; recibir ahora no acredita generación reciente.

Las curvas muestran progresión distinta en estas dos aperturas, **no una causa**:
son una corrida por configuración, con fases iniciales y cargas no controladas.
Faltan repeticiones comparables, warm-up, series simultáneas CPU/RAM por servidor,
GUI, SITL y DDS, cuotas/carga externa, frecuencia de publicación/transporte y
RTF/pausas del publicador correlacionados. Para separar CPU de renderizado faltaría
comparación GUI/headless autorizada con el resto fijo; para atribuir al rover,
comparación repetida de topologías bajo iguales condiciones. No se ejecuta aquí
esa campaña ni se atribuye lentitud a rover, CPU, GPU u OGRE. La causa de los
fallos prearm de f7f8c84f sigue abierta.

### Verificación offline y siguiente prueba mínima

Tests con clientes locales sintéticos y Docker doblado: respuesta positiva/negativa,
servicio no disponible, timeout con streams parciales, fallo de ejecución, 124 sin
prueba, formato inválido, campos escapados, prefijo de progreso y reconstrucción de
un intento sin evento final. Tanda afectada: **86 passed in 72.82s**; se comprueban
además dos casos finales de disponibilidad por stdout y espera previa seguida de
respuesta válida: módulo de diagnóstico repetido, **22 passed in 0.75s** (no se
suman a 86 como tests distintos). Sin servicios ROS, Docker real, Gazebo, instalaciones o cambios
de observabilidad. Las evidencias originales de f7f8c84f siguen íntegras.

El entorno está parado. Próxima prueba, **pendiente de autorización nueva**:
prechequeo actual, un arranque protegido `two_drones_rover` y **una** invocación de
readiness corregido, guardando stdout/stderr y `vehicles[].prearm_attempts` desde
el inicio. Exigir para cada servicio al menos un evento final con retorno y cuerpo
de respuesta; si no llega, registrar intento incompleto sin repetirlo. Una negativa
genérica confirma sólo no-armable, no su causa detallada. Mantener 180 s; finalizar
con parada protegida y readiness posterior sólo si la exclusión lo permite.
No pedir un ensayo, armar, ajustar parámetros ni aumentar el tiempo para conseguir
PASS. Esto bastaría para distinguir las clases de fallo que la captura anterior
perdió, sin una campaña de rendimiento o reinicio automático.
