# GUI negra de Gazebo: diagnóstico offline — 20/10/2026

**Causa no identificada.** Esta revisión sólo lee código y evidencias guardadas.
No ejecuta Docker, ROS, Gazebo, MCP, controles ni consultas operativas. No modifica
renderizado, modelos, drivers, configuración personal, reservas o logs originales.
Las comprobaciones siguientes quedan preparadas para otra autorización.

## Hechos y límites de las fuentes

Base de evidencia: [diagnóstico del 18/10](../simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393/README.md).
Se verificaron las **320 entradas** de su [manifiesto final](../simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393/manifest_final.json), sin discrepancias de tamaño/SHA-256.
Las rutas de la tabla son relativas a esa carpeta, no archivos vivos del contenedor.

| Fuente | Hecho respaldado | Lo que no demuestra |
| --- | --- | --- |
| `read_only_observations/container_logs_capture.json` | Captura del 18/10: supervisor, servidor y GUI separados; GUI `gz sim -v1 -g`, DISPLAY=:0, QT_QPA_PLATFORM=xcb; GZ_SIM_RESOURCE_PATH incluye los modelos instalados de ardupilot_gazebo. | Que la ventana presentara una escena correcta o que el entorno actual sea igual. |
| `read_only_observations/graphics_and_sources/root/.gz/auto_default.log` | A las 21:12 UTC crea ventana, recibe rutas, solicita GUI/estado de `runway`, carga MinimalScene y registra errores de URI/malla y geometría de visuales. | Que haya presentado frames visibles; tampoco que las mallas expliquen todo el negro. |
| `read_only_observations/graphics_and_sources/root/.gz/rendering/ogre2.log` | Inicializa GL 4.1; declara Mesa 23.2.1, vendor Microsoft y renderer D3D12 (Intel UHD Graphics). La enumeración EGL menciona un dispositivo software. | La enumeración EGL no identifica por sí sola el renderer final ni prueba un fallo de WSLg/GPU. Inicializar un contexto no acredita presentación correcta. |
| `read_only_observations/graphics_and_sources/root/.gz/sim/8/gui.config` | MinimalScene/ogre2, fondo gris `0.8 0.8 0.8`, luz ambiental y cámara `-6 0 6 0 0.5 0`. | Que se aplicara cada parámetro sin cambios del mundo/plugins o que se mostrara ese fondo. |
| `read_only_observations/final_metadata.json` | Metadatos de tres mallas consultadas: iris.dae, iris_prop_cw.dae y base_plate.dae existían en instalación y tenían tamaño positivo. | Resolución correcta de `package://`, lectura completa, validez de todas las mallas, permisos efectivos del renderer o texturas presentes. |
| `read_only_observations/container_files/tmp/tfg_demo.log` y `read_only_observations/container_files/root/.gz/sim/log/2026-10-18T21:12:11.979078160/server_console.log` | Arranque servidor de las 21:12 UTC; errores de recursos también en el log agregado. No aparece `process has died` ni `exit code 139` en la copia del main log examinada. | Ausencia de crash posterior o en otro proceso/log. El log agregado no atribuye cada mensaje automáticamente a la GUI. |

El operador comunicó pantalla negra y recuperaciones irregulares en varios arranques.
No hay en este archivo una pareja de capturas de ventana y logs equivalentes,
una negra y otra correcta, que permita comparar ambas condiciones de forma controlada.
La [caída anterior con 139](simulation-lifecycle-diagnostics.md) pertenece a otro
arranque; no se traslada al del 18/10. No se demuestra relación causal con WP3,
el timeout ROS 2 de v2/124, los relojes simulados ni las reservas retenidas.

Referencias SHA-256 recalculadas de las copias principales:

| Archivo | SHA-256 |
| --- | --- |
| `auto_default.log` | `0ffdf59e8836e7634ecb32112a838e5f6bd924eb8a2a7178871be9fca8715eab` |
| `ogre2.log` | `a985865ead1274ef7014cae43c5b2f35bd2f94a97c170147d2f170a5a3348419` |
| `gui.config` | `2b2502d7826d50762b96cda492c8d884b9aa578b9a1365f9a9a8dd887b9c35de` |

## Qué está implementado ya

- [Lifecycle](../tools/simulation_lifecycle.py) y wrappers start/stop/restart comparten
  exclusión global con vuelos/admisiones. Una restricción activa o incierta impide
  la recuperación ordinaria. Restart hace stop→start secuencial una sola vez;
  un timeout/fallo conserva UNCONFIRMED. No eludirlo con Docker o señales manuales.
- [Supervisor](../simulation/ros2_gazebo/scripts/sim_processes.py) evita otro lanzamiento
  atribuible y rota `/tmp/tfg_demo.log` antes del nuevo. Esto no archiva por sí solo
  todos los logs GUI/OGRE ni confirma la imagen.
- GUI/headless ya llega del wrapper al [launch de dos drones](../simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py).
  El servidor usa `-v4 -s -r runway.sdf`; la GUI separada `-v1 -g` es condicional.
  No hay que volver a implementar ese parámetro ni usar el antiguo launch de tres vehículos.
- El [backend de arranque](../simulation/ros2_gazebo/scripts/start_sim_backend.sh)
  ya sustituye dos prefijos `package://` por `file://` en `iris_with_gimbal/model.sdf`
  instalado, condicionado a encontrar el primer prefijo. No recorre todos los SDF
  anidados ni demuestra qué contenido cargó un arranque histórico. Repetir ese mismo
  parche o añadir rutas indiscriminadamente no es un diagnóstico.
- El final del arranque espera **dos nombres de tópicos status**. Su literal
  `Gazebo GUI: ON` es fijo, incluso para headless: no es una medición ni prueba
  de que se haya abierto una ventana. Es una limitación de presentación pendiente;
  esta revisión no cambia ese script ni pretende arreglar el renderizado.
- [Readiness](../simulation/ros2_gazebo/scripts/check_sim.sh) verifica Docker container,
  Gazebo server, ArduPilot processes, ROS 2 vehicle interfaces y Pre-arm checks.
  No inspecciona píxeles, escena ni GUI. No llamar a ese script como un simple
  lector de logs: incluye llamadas de servicio prearm. Lifecycle devuelve por
  separado `visual_confirmation=OPERATOR_REQUIRED` cuando corresponde.

## Comprobación futura: una apertura y, como máximo, una comparación autorizada

Procedimiento manual **no ejecutado ni autorizado por este documento**. No hay
vuelos, generación de misiones, cambios de modo ni ajustes de renderer/driver.

1. **Primero, sólo inspección local y lectura acotada autorizada.** Revisar guard
   activos de `missions/generated/vehicle_locks/`, operación lifecycle y propietarios
   de workers/coordinador/executor. Archivos en `history/` no son guard activos;
   ausencia de guard por sí sola no demuestra mutex libre. Los puntos lifecycle
   deben volver a comprobarlo atómicamente al actuar. No retirar restricciones ni
   inferir estado actual desde informes históricos. Si hay vuelo, propietario
   desconocido o resultado no confirmado: sólo preservar observaciones; no reiniciar.
2. **Identificar el intento A antes de cambiar nada.** Si el entorno está detenido,
   registrar ese hecho; no puede diagnosticarse su imagen actual ni se arranca para
   demostrar cómo terminó otro ensayo. Un futuro arranque necesitará autorización
   separada por la entrada protegida. Si ya está abierto, observarlo sin control.
   Crear una carpeta nueva de evidencia, sin sobrescribir otra, con HEAD, hora UTC
   de pared, contexto/endpoint e ID del motor y contenedor, imagen/Created/StartedAt,
   ID y rutas de `simulation_lifecycle/<id>/operation.json` y `backend.log` si existen.
   Si no se conserva ese ID, marcarlo desconocido, no inventarlo. Etiqueta `A`, nunca
   llamar «fallido» o «correcto» sólo por el retorno del proceso.
3. **Observar y capturar A antes de cerrar o reiniciar.** Anotar hora de la primera
   ventana y observaciones a +15 y +60 s de pared, sin esperar en bucle. Preguntar:
   «¿No hay ventana, está toda negra, sólo el panel 3D está negro, falta algún modelo,
   o ves pista y ambos drones correctamente? ¿Los menús responden?». Guardar una
   captura de pantalla completa con consentimiento y respuesta literal del operador;
   distinguir captura del sistema de una imagen producida por un plugin. Si aparece
   después, registrar la transición sin convertirla retrospectivamente en éxito inicial.
4. **Preservar fuentes separadas del mismo arranque mediante lecturas con timeout.**
   Registrar comando, inicio/fin UTC de pared, retorno y stderr; 10–15 s por lectura,
   sin retries automáticos. Una fuente ausente o timeout se registra como tal.
   No volcar todo el entorno ni credenciales. Capturar:
   - PID/start_ticks/boot_id, argumentos y parentesco del supervisor, GUI y servidor;
     son identidades distintas del contenedor/daemon y no garantizan frames.
   - `/tmp/tfg_demo.log`, log launch y `server_console.log` **referidos por ese arranque**;
     no usar `/tmp/tfg_2drones.log` antiguo ni elegir una carpeta sólo por ser «latest».
   - `/root/.gz/auto_default.log`, `/root/.gz/rendering/ogre2.log` y configuración GUI
     realmente indicada en el log; registrar ruta, tamaño, mtime, momento de copia
     y SHA-256. Pueden crecer/rotarse durante captura: el hash identifica los bytes
     obtenidos, no una instantánea atómica de todo el entorno.
   - Variables seleccionadas **de los procesos GUI/servidor**, no sólo del terminal:
     DISPLAY, WAYLAND_DISPLAY, QT_QPA_PLATFORM, GZ_SIM_RESOURCE_PATH y, si existen,
     LIBGL_ALWAYS_SOFTWARE, MESA_D3D12_DEFAULT_ADAPTER_NAME, GZ_PARTITION.
     Registrar presencia/ausencia, configuración y versión WSLg disponible sin editarla;
     `/mnt/wslg` en el host puede no estar montado en el contenedor. No instalar utilidades.
   - URI exacta de cada error, ruta absoluta candidata, SDF/URI anidada cargada y
     existencia/permisos/tamaño de malla/texturas; comparar hashes de esos archivos,
     mundo y configuración entre intentos. Un archivo existente no prueba resolución.
   No llamar a readiness ni a servicios ROS durante esta primera captura de lectura.
5. **Clasificar antes de proponer cambios** usando la tabla siguiente. Si se desea
   comparar una reapertura B, pedir aceptación nueva **antes** de reiniciar, y sólo
   sin actividad/restricción incierta y por restart protegido. No cerrar la GUI con
   botones/señales para saltar el procedimiento. Conservar A antes: los logs GUI/OGRE
   pueden sobrescribirse. B tiene carpeta, identidad y timestamps propios; mismos
   modelos/configuración/renderer, sin ajustes simultáneos. Una sola reapertura;
   si sigue negra, parar la investigación operativa sin otro reinicio automático.
6. **Después del arranque autorizado**, readiness actual por separado si se autorizó
   esa comprobación, guardando sus controles reales y salida. Volver a preguntar por
   la imagen aunque dé READY. El operador puede elegir expresamente headless, pero
   eso no repara la GUI, no aporta confirmación visual de suelo ni autoriza vuelos.
   Autorizaciones de reconciliación, recuperación GUI y ensayo son decisiones distintas.

| Comparación | Interpretación permitida / siguiente dato |
| --- | --- |
| Proceso GUI vivo + ninguna ventana/imagen | Apertura/presentación no confirmada; revisar Qt/WSLg, salida GUI y captura. No afirmar renderizado por PID. |
| Menús/pista visibles pero drones incompletos + errores URI concordantes | Pista concreta de recursos/visuales. Identificar el URI y cadena SDF antes de proponer una corrección mínima; no atribuir automáticamente todo el negro. |
| Errores al crear contexto/ventana, shader, GLX/EGL o crash con stack gráfico del mismo intento | Pista gráfica específica, separada de recursos. GL 4.1/D3D12/Intel como identificación no es en sí un error. No cambiar drivers/renderer sin otro encargo. |
| Ventana negra sin error decisivo, aun con contexto creado | Causa abierta: faltan evidencia de frames/presentación y comparación. Incluir cámara, conexión/partición, UI y contexto como hipótesis; no seleccionar una por descarte informal. |
| A negra y B correcta con logs/configuración comparables | Recuperación observada una vez, no causa resuelta ni garantía de repetibilidad. Comparar errores presentes en ambas; no atribuir causalidad sólo a reiniciar. |
| READY + imagen negra | Backend y visualización discrepan legítimamente: conservar ambos resultados. No convertir READY en «GUI correcta». |

La toma conjunta de captura, respuesta del operador y logs del mismo intento permite
separar las ramas; puede seguir sin bastar para una causa raíz. No se propone aquí
forzar software rendering, cambiar OGRE, borrar gui.config/cachés ni nuevos parches
de modelos. No hay evidencia suficiente para una corrección funcional verificable.

Prompt opcional para una futura **primera inspección**, sin autorización de lifecycle:

```text
Inspecciona sólo en lectura y con plazos acotados la GUI del entorno SITL actual: identifica reservas y procesos, separa logs de GUI, OGRE y servidor del mismo arranque y prepara copias con hashes; pregúntame qué muestra la ventana, no infieras imagen correcta de READY o del PID y no arranques, detengas, reinicies, liberes restricciones ni ejecutes vuelos.
```

## Revisión offline de 8076 y contraste con H2 — 2026-10-24

Esta actualización describe el código/evidencia posteriores a las notas históricas
del 20/10: actualmente existe `two_drones_rover` seleccionable. No se ha abierto
nada, consultado el GPU actual, cambiado renderer/driver ni aplicado otro parche
de recursos durante esta revisión. El análisis de barridas está en el
[procedimiento XRCE](../tools/rover_xrce_trace/README.md#offline-cost-correction-after-8076--2026-10-24).

En [8076](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/8076e735-81bb-4542-afda-8db2fe54acef/),
`after_stop/container_copies/tmp/tfg_demo.log` registra `D3D12: Removing Device.`,
fallos de creación de ventana OGRE `RenderingAPIException`, `glGetError 1285`,
`Requested: 67108864 bytes` en `GL3PlusVaoManager::allocateVbo` y salida GUI 139
tras segmentation fault. **La solicitud de esta sesión fue 64 MiB**, no una medida
de capacidad VRAM ni los aproximadamente 128 MB mencionados en otros arranques.
El texto «Out of GPU memory or driver refused» no decide entre sus alternativas.
El OGRE conservado identifica D3D12 (Intel UHD Graphics); su intento de contexto
EGL que menciona software no prueba que la escena final usara software rendering.
No hay medición de memoria libre/presupuesto del dispositivo ni diagnóstico del
host que explique por qué se retiró/rechazó el dispositivo.

Los errores de `package://ardupilot_gazebo/...iris_collision.stl`, `yaw_arm.dae`
y otras mallas aparecen en el servidor; los avisos de construcción de meshes con
dartsim son otra categoría. Se conservan separados del error de ventana de la GUI.
No hay prueba de que provoquen la retirada D3D12, y no procede repetir la sustitución
parcial de prefijos ya implementada ni alterar modelos. La salida 139 demuestra
terminación de ese proceso, no su causa raíz. El backend siguió hasta el cierre
protegido, por lo que tampoco se equipara con fallo completo del servidor.

Contraste disponible con [H2](../simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/):

| Dato | H2 correcto | 8076 fallido |
| --- | --- | --- |
| Perfil registrado | two_drones | two_drones_rover |
| GUI solicitada | true | true |
| Visualización | Joel: «se ve bien con los 2», registrada 12:50:25 UTC | Sin confirmación del operador; supervisión abortada |
| Mundo | runway según readiness histórico | runway en argv real del servidor |
| RViz | OFF según backend local referido por operación | OFF según backend conservado |
| Agente | No selector diagnóstico en operación | Pareja peer explícita, verificada |
| Renderer/OGRE y entorno gráfico de esa apertura | No conservados en H2 | Log OGRE D3D12/Intel y error de ventana conservados |

Se verificaron las 23 copias del manifiesto H2. Su backend local referido por la
operación sigue disponible, pero sólo contiene el resumen lifecycle, no el log
completo GUI/OGRE de H2. No se usa el OGRE actual como si fuera el de H2. El catálogo
y los launch actuales configuran runway/GUI separada en ambos perfiles; no acreditan
retroactivamente todos los bytes efectivos del launch H2. Host boot_id coincidente
no prueba identidad histórica/reinicio del daemon Docker. H2 demuestra una
visualización correcta comunicada y ejecución histórica, no igualdad del estado
GPU, ausencia de errores de meshes, ni que el rover sea responsable del fallo.

**Corrección gráfica funcional: BLOQUEADA por falta de causa demostrada.** Siguen
abiertas la retirada/rechazo intermitente de la ruta gráfica y una diferencia de
carga/escena; no hay mediciones comparables para atribuirlo a rover, CPU o VRAM.
No se presenta el ahorro de lecturas /proc como corrección gráfica.

### Una prueba gráfica futura propuesta, no autorizada ni ejecutada

Hipótesis acotada: ¿el mismo fallo de ventana se reproduce actualmente incluso
sin rover ni instrumentación diagnóstica, con el perfil que se vio correcto en H2?
Cambio temporal único: seleccionar `two_drones` mediante el argumento existente,
con GUI y agente instalado normal como H2. Renderer, drivers, modelos, variables
persistentes y límites permanecen intactos. Esto NO es un experimento que aísle
todas las variables entre perfiles; un éxito no probaría que el rover causó nada.

Tras autorización separada y precheck actual bajo exclusión, una sola apertura:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones
```

Conservar desde el comienzo identidad/configuración efectiva, comando GUI, logs
launch/OGRE del intento con tiempos/copias propias y lecturas de proceso. Esperar
respuesta real de Joel sobre pista y dos drones durante una observación propuesta
de hasta 30 s; no un sleep que convierta el backend en visible. Sin readiness,
prearm, servicios, vuelos, colector ni captura XRCE. Si desaparece la ventana o
hay incertidumbre, conservar y cerrar inmediatamente; ninguna reapertura.

Criterio favorable: Joel confirma escena completa durante el intervalo observado,
sin salida GUI ni nuevo fallo de ventana en los registros. Criterio adverso: reaparece
el error de ventana/dispositivo o salida 139 aun sin rover; impediría atribuir el
fallo exclusivamente al rover. Negro/incompleto sin error decisivo queda incierto.
Una observación favorable sólo establece disponibilidad puntual, no reparación.

Restauración y final del único intento, por la vía protegida:

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile two_drones
```

Guardar logs antes de que otra apertura pueda sobrescribirlos, resultado formal,
procesos y restricciones posteriores. No hay configuración persistente que deshacer,
ni vuelta automática a tres vehículos. Si el cierre bloquea, preservar el estado.
El ensayo peer sigue pendiente de resolver/revisar su presupuesto por separado.

### Lecturas locales adicionales y límites de rutas — 2026-10-24

Continuación offline, sin Docker ni consultas al renderer activo. Fuentes y hashes:
`simulation/ros2_gazebo/results/rover_socket_offline_2026_10_24/budget_comparison/current_sources.json`.
Los launch fuente actuales usan ambos `gz_args="-v1 -g"` para la GUI y
`-v4 -s -r <share>/worlds/runway.sdf` para el servidor. El de tres vehículos añade
WILD_THUMPER/rover1 a los dos IRIS; esto cambia carga/escena, no demuestra causalidad.
No hay selección explícita nueva de renderer en esas líneas. H2 no conserva el
log GUI/OGRE equivalente, por lo que esa comparación de comandos/configuración
fuente no demuestra igualdad histórica del driver, renderer o entorno gráfico.

En el árbol LOCAL `/home/joelm/TFG/ardupilot_ros2_ws` existen las mallas
`iris_with_standoffs/meshes/iris_collision.stl` y
`gimbal_small_3d/meshes/yaw_arm.dae`. El SDF fuente de iris_with_gimbal usa includes
`package://ardupilot_gazebo/models/...`; su copia install local tiene includes
`file:///root/ardu_ws/install/...`. Esas rutas absolutas se refieren al contexto
del contenedor y no acreditan resolución en el host. Los SDF hijos fuente todavía
usan package:// para meshes. `start_sim_backend.sh:134` ya reescribe los dos
INCLUDES de iris_with_gimbal; no reescribe recursivamente los URI de las mallas
hijas. Por tanto, no proponer de nuevo ese mismo arreglo como solución pendiente.

8076 demuestra URI de meshes no resueltos en el servidor; no demuestra ausencia
física de esos ficheros en aquel contenedor ni que corregir los includes solucione
los URI hijos. Las lecturas locales actuales no reemplazan el inventario de recursos
resueltos de aquella apertura. No se parchea el árbol externo, ni se aplica una
reescritura masiva no verificada: queda pendiente comprobar, mediante lectura
acotada y autorizada del contexto real, rutas efectivas de los SDF hijos y su
resolutor antes de proponer un cambio fuente específico. Esto es independiente
del device removal D3D12, petición de 64 MiB, fallo de ventana y salida 139.
No hay evidencia de capacidad libre de VRAM ni un arreglo gráfico demostrado.

Se mantiene UNA sola prueba gráfica futura descrita arriba, no ejecutada ni
autorizada por esta revisión: two_drones/GUI, entorno gráfico intacto, observación
real de Joel <=30 s y parada protegida. No se combina con el ensayo peer ni se
interpreta su resultado como validación de identidad o causalidad del rover.

### Estado del entorno consultado — 25/10/2026

La lectura actual por `reconciliation_environment.inspect_environment` confirmó
engine `2c4ad774-b7c7-4d26-ba0e-690fb9d0ff99`, contenedor
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f`
y la imagen documentada `sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66`.
Estado exited/Running=false/Pid=0, FinishedAt 2026-10-25T07:48:17.5089221Z.
No se arrancó. El primer intento tuvo denegación del socket en sandbox; se conserva
separado del resultado posterior permitido. No se equipara fallo de consulta con
contenedor detenido.

Por ello no pudieron inspeccionarse ahora los SDF efectivos, variables de recursos,
GUI o configuración gráfica DENTRO del contenedor. Las lecturas locales anteriores
y logs históricos siguen siendo sus únicas fuentes respectivas. No se prepara una
reescritura de recursos sin demostrar cuál es el URI/resolutor efectivo defectuoso;
no se repite el arreglo de includes que ya existe. No hay cambio gráfico funcional
ni despliegue en esta tanda. Se mantiene la única prueba gráfica two_drones descrita
arriba, pendiente de autorización y precheck propios; separada del ensayo peer.

### Reactivación autorizada y control gráfico bloqueado — 25/10/2026

Evidencia nueva: [resultado](../simulation/ros2_gazebo/results/gui_control_two_drones_2026_10_25/94081694-c064-4167-ae34-9e92fc6290eb/result.json).
Se verificaron engine, ID completo, imagen, mounts y entrada. El entrypoint carga
ROS y ejecuta bash; no se observaron órdenes de simulación en el inicio revisado.
Se reactivó una sola vez el mismo contenedor. La lectura final confirmó Running=true;
no hubo procesos owned/ambiguous/agentes, guardas JSON ni restricción activa.

**No se abrió Gazebo**. El precheck bajo exclusión devolvió BLOCKED por
`Environment incarnation changed`: `session_precheck.py:121` exige igualdad de
StartedAt con la referencia del lifecycle histórico e2381f94. La referencia
conserva el arranque del 21/10; el contenedor reactivado tiene StartedAt del25/10.
Engine, ID e imagen siguen coincidiendo. No se cambió descriptor, política ni
historial para superar esa condición. El target histórico sigue CLOSED.

Wrapper peer, biblioteca y colector siguen presentes y coinciden con sus hashes.
Los helpers bootstrap son anteriores al contrato nuevo y falta /tmp/budget.py;
se documentó sin sustituirlos. Los dos meshes investigados existen dentro del
contenedor; SDF hijos todavía usan package://. No se probó resolución gráfica.

No hay nueva observación visual, logs de una apertura nueva ni resultado gráfico
comparable con8076. No se solicitó parada lifecycle: ninguna sesión de simulación
fue abierta en esta tanda. El contenedor queda activo, sin simulación observada.
Antes de control gráfico o peer hace falta revisar el bloqueo de encarnación por
la vía soportada, sin borrar metadata ni reutilizar autorizaciones anteriores.
El ensayo peer sigue además sin autorizar y sin los helpers nuevos desplegados.

### Corrección posterior del clasificador — 25/10/2026

La evidencia94081694 y su BLOCKED permanecen intactos. La corrección separa la
identidad persistente del contenedor del StartedAt/boot de cada ejecución: un
historial CLOSED coherente no necesita que sus procesos pertenezcan al boot actual.
Sí conserva descriptor, operaciones y recibos propios, y exige comprobaciones
actuales frescas bajo exclusión. No aplica a sesiones activas ni completa diagnósticos
incompletos. La disposición51790 no se usa para resolver e238.

Revalidación actual: precheck SATISFIED, historial e238 clasificado
HISTORICAL_CLOSED_POINTER, disposición no consumida. No se arrancó simulación.
[Auditoría y fuentes](../simulation/ros2_gazebo/results/rover_xrce_pointer_review_2026_10_25/reactivated_container_review/).
La prueba two_drones autorizada sigue pendiente y no ha consumido ninguna apertura;
se retomaría con precheck nuevo, agente normal, confirmación visual nueva y parada
protegida, según los comandos del procedimiento XRCE y la prueba gráfica descrita
arriba. Los helpers peer antiguos y budget.py ausente son un requisito separado
del futuro ensayo peer, no del control gráfico con agente normal.

### Diagnóstico y corrección de búsqueda preparada para ca4e — 25/10/2026

Estado: **corrección de recursos PREPARADA, NO DESPLEGADA/EJECUTADA**. Causa de toda
la GUI negra/incompleta aún no demostrada. [Índice de firmas y consultas](../simulation/ros2_gazebo/results/gui_resource_review_2026_10_25/ca4e114b/).
Originales ca4e (41 entradas) y8076 (88 entradas) se conservan byte por byte.

| Cadena, log de apertura ca4e | Primera ubicación / cantidad | Interpretación limitada |
| --- | --- | --- |
| Recursos package:// | launch:310;88 líneas de búsqueda | 8 URI de meshes distintos; errores repetidos en servidor/GUI, no88 causas independientes |
| Carga de meshes de escena | launch:313;26 líneas | Fallos posteriores de carga asociados a recursos no resueltos; no se deduce toda la causa visual |
| HLMS | OGRE:446;2 avisos | Directorio Gz existe y contiene subdirectorios; aviso de ausencia de pieces en su raíz, no prueba de instalación ausente |
| Shaders/samplers | OGRE:509;4 mensajes | Validación GLSL: samplers de distinto tipo en la misma unidad de textura |
| Materiales ausentes | OGRE:510;12 mensajes | scene::Material no encontrado; puede haber fallos derivados, origen no acreditado |
| Fixed Function | OGRE:525;6 excepciones | scene::Material(65518) y Default/TransGreen deben usar shaders con OGRE2 |
| Limpieza de buffers | OGRE:546;4 avisos | Deleting mapped buffer; no cuantifica una fuga ni VRAM libre |
| Ventana, asignación, device removal, salida139 | No presentes en logs ca4e conservados | No se equipara este fallo visual a la excepción de asignación de8076 |
| Plugins | OGRE:45;2 cargas correctas | GL3Plus y ParticleFX se cargan; no se observa aquí una biblioteca/plugin ausente |

Las ubicaciones son líneas de `opening-logs/0/tfg_demo.log` y
`opening-logs/1/ogre2.log`, con hash en signature-index.json. El primer error de cada
familia se conserva separado de sus repeticiones. Hay texto intercalado en OGRE
(por ejemplo línea506); sus posiciones no establecen un orden temporal global ni
causalidad entre procesos. Los códigos -15/-2 durante la parada no son la salida
139 espontánea de8076. Allí aparecen device removal en launch:671 y salida139 en
launch:874; petición64 MiB/rechazo de ventana en la cadena de asignación. Ambos
ensayos registran errores de meshes y materiales. H2 conserva perfil two_drones,
GUI solicitada y confirmación del operador, pero no logs OGRE equivalentes: la
configuración fuente compartida no prueba igualdad histórica de GPU/shaders/estado.

#### Defecto concreto de recursos acreditado

Consultas actuales, sin renderer, bajo la misma secuencia de setup ROS/workspace:

- El paquete instalado es `/root/ardu_ws/install/ardupilot_gazebo/share/ardupilot_gazebo`.
  Sus8 meshes referidos existen, son legibles y tienen permisos/hash conservados.
- `GZ_SIM_RESOURCE_PATH` contiene los directorios worlds/models de ese paquete,
  pero no `/root/ardu_ws/install/ardupilot_gazebo/share`.
- La implementación instalada de `ros_gz_sim/launch/gz_sim.launch.py` se inspeccionó;
  su `GazeboRosPaths.get_paths()` devuelve exports de modelos/plugins vacíos. No
  añade por otra vía el padre ausente. package.xml fuente/install de ArduPilot sólo
  exporta build_type. El propio launch documenta `${prefix}/../` para URI con nombre
  de paquete y preserva el GZ_SIM_RESOURCE_PATH heredado al crear servidor y GUI.
- El contrato público instalado `gz/common/SystemPaths.hh:FindFileURI` conserva la
  autoridad URI al buscar cuando es necesario. Para
  `package://ardupilot_gazebo/models/...`, la ruta esperada es
  `<share>/ardupilot_gazebo/models/...`; añadir sólo `<paquete>/models` no proporciona
  ese espacio de nombres. Se contrastó la composición esperada y los archivos,
  NO se ejecutó el resolvedor nativo ni un renderer. No presentar ese test como una
  recepción gráfica real.

Fuente/install coinciden en los SDF hijos. El padre iris_with_gimbal fuente conserva
includes package:// y su install ya tiene file:// por el parche anterior; hashes
son distintos. No hay copias model.sdf en las rutas build consultadas; no se infiere
que no exista ningún otro recurso en build. El parche antiguo sólo reescribía esos
includes y dejaba los URI hijos fallando, como demuestra ca4e.

Preparado en `start_sim_backend.sh`: sustituir esa reescritura in-place por un
**export de búsqueda limitado al proceso del nuevo lanzamiento**, después de setup
y antes del supervisor. Resuelve `ros2 pkg prefix ardupilot_gazebo` dentro del
contenedor, valida models y añade `<prefix>/share` sólo si falta. No hay ruta del
host embebida, cambio de geometría, reescritura recursiva, backup nuevo, limpieza de
caché o modificación persistente. Los SDF instalados de sesiones previas quedan
intactos. Servidor y GUI heredan el entorno a través del mismo Popen/ros_gz_sim.
No se cambian launch, perfiles, exclusión, reservas ni gates. La fuente está visible
en el repo montado, pero el bloque nuevo no se ha ejecutado en el entorno activo.

#### Entorno gráfico y límites

Mesa23.2.1 (paquetes EGL/GLX/DRI), gz-common5.9.0, gz-rendering8.2.3 y
OGRE-next2.3.1 según paquetes instalados; versiones vacías de dpkg no se consideran
instalaciones acreditadas. GL3Plus.so apunta a .2.3.1, gz-rendering8-ogre2.so a
.8.2.3 y d3d12_dri.so existe. Los logs de la apertura identifican D3D12/Intel UHD;
no se creó un contexto nuevo para consultarlo. Los campos relevantes del gui.config
local y el distribuido coinciden en hash: MinimalScene con engine ogre2. No se
conservó configuración personal completa. GUI config usa fragmentos XML: la primera
consulta falló al tratarlo como documento único; la segunda conservó sólo campos
seleccionados tras envolver los fragmentos, sin editar el archivo.

Hipótesis pendientes: (1) recursos sin resolver degradan modelos, defecto de búsqueda
corregido en preparación; (2) errores OGRE2 de materiales/samplers pueden seguir
impidiendo la escena aun tras resolver los meshes, sin parche especulativo; (3)
fallo intermitente de la ruta D3D12, cuya variante device-removal no aparece en ca4e.
No se acredita causa VRAM, culpabilidad del rover ni ausencia de problemas del
renderer por el mero hecho de cargar sus bibliotecas.

#### UNA verificación gráfica futura, requiere autorización aparte

Único cambio frente a ca4e: el entorno heredado del lanzamiento incluye el padre
share del paquete, y ya no se reescriben includes instalados. Se usan el mismo
perfil two_drones, agente normal, mundo, GUI/RViz y renderer. Los archivos preparados
son start_sim_backend.sh y tests/test_gazebo_resource_paths.py; hashes en el índice
nuevo. No hace falta recompilar, instalar ni copiar helpers peer. No se aplicó ahora.

Tras identidad/procesos/reservas y precheck nuevos bajo el lifecycle protegido:

```bash
.venv/bin/python -m tools.simulation_lifecycle start --profile two_drones
```

Conservar desde el inicio logs launch/OGRE separados, comando GUI, entorno de recursos
que hereda el supervisor y hashes de SDF sin modificarlos. Pedir respuesta nueva de
Joel sobre pista y dos drones, observación acotada propuesta <=30 s; backend SUCCESS
no acredita imagen. Evaluar por separado:

1. Recursos: deben desaparecer los errores de las8 URI corregidas. Si persisten,
   conservar la ruta efectiva y el fallo; la resolución operativa no queda validada.
2. Imagen: Joel confirma escena completa y no se observa salida/fallo de GUI. Si los
   meshes resuelven pero sigue negra/incompleta o los shaders fallan, la corrección
   de rutas no basta y NO se declara arreglo gráfico permanente.

Cerrar inmediatamente ante fallo/incertidumbre o al terminar la observación:

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile two_drones
```

Sin readiness/prearm, servicios, misiones ni colector. Verificar cierre/procesos/
guardas. No repetir ni cambiar renderer. Restauración: el entorno añadido muere
con el proceso; no hay caché, recurso, driver o variable personal que revertir.
No revertir SDF antiguos ni borrar sus backups como parte del ensayo.


### Verificación autorizada del recurso — 2026-10-25, completada

La prueba propuesta arriba se ejecutó UNA vez con two_drones y agente normal.
Evidencia: [7074b972](../simulation/ros2_gazebo/results/gui_control_two_drones_2026_10_25/7074b972-8e58-4dad-a953-7d901a1357d2/README.md).
Start a9c6a83c-169a-4098-b398-71ba43d1b252: SUCCESS; parada
4ab52609-3bb3-4ea1-85a7-6ac021ac3e9f: SUCCESS. Joel respondió realmente
«Sí: pista y dos drones completos». La respuesta se conserva aparte de los logs;
no se afirma que llegó dentro de los 30 s propuestos. No hubo otra apertura.

El entorno efectivo del launch incluyó el padre share del paquete. En los logs
conservados, las líneas de error URI pasaron de 88 a 0 y las de meshes de 26 a 0
respecto a ca4e. Persistieron errores OGRE: fixed-function 6, materiales ausentes
162 y samplers 6 (antes 6/12/4). Son recuentos de ventanas de log distintas, no una
comparación de tasas. No se observó device removal ni salida 139 en esta apertura.
La desaparición de errores de recursos respalda la corrección de búsqueda; la
imagen confirmada es disponibilidad puntual, no reparación permanente de shaders,
D3D12 o estabilidad general. Los seis SDF conservaron sus hashes; fuente e install
siguen distintos donde ya lo eran por reescrituras anteriores.

Después del cierre, las lecturas conservaron cero procesos atribuibles, ambiguos
y agentes; restricción nula y guardas vacías. El contenedor permaneció activo.
La evidencia registra una limitación del wrapper de captura: su filtro gráfico no
reconoció argv por escaping; las tablas completas sí conservan PID/start_ticks de
la GUI. Ese filtro vacío no demuestra ausencia de ventana. No se ejecutaron
readiness/prearm, servicios, colectores ni ensayo peer.
