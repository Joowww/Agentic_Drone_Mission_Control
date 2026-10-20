# Perfil de simulación consumido por runtime — 20/10/2026

Implementación y verificación **offline**; sin nueva prueba operativa. Sólo existe
`two_drones`. No se habilitan rover, v3, el launch histórico de tres vehículos ni
vuelos simultáneos. Este documento no autoriza operaciones.

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
limpieza conserva el de tres vehículos por compatibilidad de identificación: eso
no habilita su selección. El formato de readiness sólo contempla el tipo único
de SITL del perfil actual; añadir una segunda clase de proceso exige revisión.
No se prueban versiones/copias instaladas, puertos efectivos o renderizado real.

Las pruebas usan Bash en proyectos temporales, Docker/ROS/Popen doblados y muestras
sintéticas. Cubren parámetros efectivos, mutaciones, perfil desconocido antes de
operar, CLI/helper standalone, defaults, GUI/headless y exclusión con los mutex del
proyecto. No autentican consentimiento ni constituyen validación operativa.

## Siguiente incremento para el rover

Preparar por separado un perfil de dos drones más rover y su integración completa:
selección protegida del launch, world/modelos, cantidad y tipo de SITL, puertos,
interfaces/prearm del rover, identificación/limpieza de procesos y alcance de
reservas/reconciliación de todas las interfaces presentes. Revisar qué partes de
los controles actuales sólo contemplan v1/v2 antes de habilitarlo. No basta añadir
una entrada a `PROFILES` ni cambiar el nombre del launch.
Después corresponderán tests offline y una autorización operativa independiente
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
