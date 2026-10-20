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
