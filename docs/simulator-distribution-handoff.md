# Entrega completa para estudiantes: lo que falta y traspaso del simulador al subsistema rover

**Mapa único** de lo que le falta a la entrega completa (§7) y **traspaso** de la construcción reproducible del simulador al subsistema rover (§8). §1–§6 son las lecturas del 27/10/2026. El procedimiento del estudiante está en [student-environment.md](student-environment.md) §0.

## 0. Objetivo

Una carpeta tipo pendrive. El estudiante la copia o la descarga y tiene dentro el software, las imágenes, los recursos, los ejemplos y los comandos para usar el proyecto, sin instalar a mano Python, ROS, Gazebo ni ArduPilot y sin depender del entorno de Joel.

- Puede contener varias imágenes y servicios con el Compose y la arquitectura actuales; no tiene que ser un único contenedor.
- La referencia es **nuestra arquitectura**: ArduPilot SITL, ROS 2 Humble con AP_DDS, Gazebo Harmonic y Hermes. No se cambian autopiloto, middleware ni interfaces.
- **La IA es solo Hermes**, con el proveedor y el modelo fijados (`nous` / `poolside/laguna-s-2.1:free`). Ollama y sus modelos no forman parte de la entrega.

**Entrega parcial vigente:** `/home/joelm/TFG/entregas/tfg-entrega-estudiantes-2026.10.30/` (851 MB; evidencia `student_bundle_2026_10_30`).
- **Contenido:** `app`, `qgc` y `hermes`, con la IA solo en Hermes, y el recorrido de finalizaciones de Hermes a `.plan` con el almacén en solo lectura.
- **Versión r2:** `…2026.10.28-r2/` se conserva intacta y queda superada.
- **No es la distribución completa del proyecto: falta el simulador.**
- **Versión anterior:** `…2026.10.28/` se conserva intacta y queda superada; todavía citaba Ollama.

## Lecturas del 27/10/2026 (§1–§6)

Se hicieron con lecturas de solo lectura (`docker inspect`, `docker diff`, `docker history`, `git rev-parse`), sin arrancar, parar ni modificar contenedores. No se reconstruyó nada. La imagen `app` **no** incluye ROS, ArduPilot ni Gazebo y no los sustituye. El 28/10 no se volvió a leer el contenedor operativo.

## 1. Imagen base actual

| | |
| --- | --- |
| Imagen | `ardupilot/ardupilot-dev-ros:tfg`, ID `sha256:5d5de3c69e2af0a4d565e74e4637b26880f574c7db5d8f3f8b90f479983e3d66`, creada el 30/09/2026 |
| Origen | Construida en local a partir del Dockerfile *dev-ros* de ArduPilot: Ubuntu 22.04, ROS Humble `ros-core` y `ros-base` 0.10.0-1, toolchain `gcc-arm-none-eabi-10-2020-q4-major`, pip (pymavlink, empy 3.3.4…). Sin digest de registro y sin el Dockerfile ni el commit de ArduPilot usados registrados en este repositorio |
| Contenedores | `tfg-ardupilot-gazebo` (creado a mano el 02/10/2026) y `tfg-ardupilot-ros2` (30/09/2026). El comando de creación no está registrado |

## 2. Lo que solo existe en la capa mutable de `tfg-ardupilot-gazebo` (5,19 GB)

- **917 paquetes dpkg** añadidos sobre la imagen. Entre ellos, 121 de Gazebo y sdformat (`gz-harmonic`, `gz-sim8`, `gz-transport13`, `libgz-*`, `libsdformat14`…), procedentes de `/etc/apt/sources.list.d/gazebo-stable.list`. También hay 47 `ros-humble-*`: rviz2, rqt, cv-bridge, image-transport, `micro-ros-msgs`, `geographic-msgs`, `actuator-msgs`, `gps-msgs`, `vision-msgs`, `xacro`, `topic-tools`, `ignition-*-vendor`…
- **pip en `/usr/local`:** mavproxy 1.8.75, numpy 2.2.6, opencv_python 5.0.0.93, matplotlib 3.10.9, contourpy 1.3.2, vtk 9.7.1, shapely 2.1.2, pynmeagps 1.1.7, quantized_mesh_tile 0.7.0, defusedxml 0.7.1, pyparsing 3.3.3.
- Hay caché de ccache y logs (`/root/.cache/ccache`, `/root/.ros/log`) y temporales en `/tmp` (`tfg_demo.*.log`, `launch_params_*`). No deben pasar a ninguna receta.

Las **versiones exactas** de los paquetes dpkg no se han extraído, para no leer dentro del contenedor operativo. El subsistema rover puede obtenerlas sin modificarlo con `docker exec tfg-ardupilot-gazebo dpkg-query -W` cuando lo considere seguro.

## 3. Fuentes y versiones del workspace (montado desde el anfitrión)

`/home/joelm/TFG/ardupilot_ros2_ws` → `/root/ardu_ws`, propiedad de root. `build/` ocupa 1,2 GB y `install/` 980 MB.

| Repositorio | Commit | Estado |
| --- | --- | --- |
| ArduPilot/ardupilot | `755258dbb452f46dc7e1e47a36591f3b62e8830d` (4.6.0-beta1-8901; SITL informa V4.8.0-dev) | limpio |
| ArduPilot/ardupilot_gz | `8df4dc1726e37504e6fc8b952d02e554cfa3176f` | **3 cambios locales**: los launch que copian los scripts del repositorio |
| ArduPilot/ardupilot_gazebo | `cc0290d964dfa373531963a8fc39093a0836af0a` | limpio |
| ArduPilot/SITL_Models | `d5d6017367a509b77886379c91207edc66f77652` | limpio |
| micro-ROS/micro-ROS-Agent | `c93ee764e0d2ef4907aeb29233c68cb5f4b56976` | limpio |
| gazebosim/ros_gz | `28e586a3d41f80f4a91e81902b8618c9d506022c` | limpio |
| ros/sdformat_urdf | `7b73ddb8af07b8dd5cee5fa8231e982f4ad8c217` | limpio |

## 4. Montajes y acceso que usa hoy

- `/home/joelm/TFG/ardupilot_ros2_ws` → `/root/ardu_ws` (lectura y escritura) y `/home/joelm/TFG/Agentic_Drone_Mission_Control` → `/workspace/tfg` (lectura y escritura).
- GUI de WSLg: `/tmp/.X11-unix` (lectura y escritura), `/usr/lib/wsl` (solo lectura), dispositivo `/dev/dxg`, `DISPLAY=:0`, `LD_LIBRARY_PATH=/usr/lib/wsl/lib`.
- Red `bridge`, sin puertos publicados.

## 5. Dependencias personales y temporales que deben pasar a la receta

| Hoy | Debe pasar a |
| --- | --- |
| Rutas `/home/joelm/...` en los montajes | Volúmenes declarados en Compose, con rutas parametrizadas |
| `docker cp` en cada arranque de `simulation_profiles.py`, `sim_processes.py`, `rover_environment_identity.py`, `rover_identity_worker.py` a `/tmp` del contenedor, y de los launch a los árboles source e install de ardupilot_gz | Archivos de la imagen o montajes de solo lectura |
| Lock `/tmp/tfg_simulation_control.lock` del anfitrión y `.venv` del anfitrión en `start/stop_sim_backend.sh` | Parámetros explícitos |
| Nombre fijo `tfg-ardupilot-gazebo` | Nombre de servicio Compose o variable |
| Builds del subsistema rover en `/tmp/tfg-receiver-build-…` y `/tmp/tfg-rpc-agent-build-…` | Etapas de build con sus fuentes y hashes |
| `build/` e `install/` del workspace hechos a mano | `colcon build` dentro de la imagen sobre los commits de §3, con los 3 cambios de ardupilot_gz como parche |

## 6. Receta propuesta, sin implementar

Un Dockerfile en el repositorio con la base fijada por digest, que puede ser la propia receta *dev-ros* de ArduPilot con su commit. Además:
- Gazebo Harmonic y los `ros-humble-*` de §2 con versiones fijadas;
- pip con versiones fijadas;
- el workspace en los commits de §3, compilado en la imagen;
- un servicio `sim` en `deploy/compose.yaml`, separado de `app` y `qgc`.

No se propone `docker commit` del contenedor actual como sustituto: no deja receta, arrastra temporales y cachés, y no permite reconstruir ni auditar.

Una prueba que conecte QGC o `app` con el simulador necesitará red compartida y su propia autorización. La importación offline y la imagen `app` no la necesitan.

## 7. Mapa de la entrega completa (28/10/2026)

«Hoy» se refiere a la entrega parcial. Tamaños: imagen cargada / archivo de `docker save`.

| Componente | Incluido hoy | Falta | Responsable | Fuente reproducible | Tamaño | Aceptación |
| --- | --- | --- | --- | --- | --- | --- |
| App y validación determinista | Sí, `tfg/app:2026.10.30`: menú offline orientado a Hermes, `package-finalized` y almacén de planificación en solo lectura | Nada para el uso offline | El sistema multiagente | `deploy/app/Dockerfile` + lista generada; la `2026.10.28` sale de un contexto congelado. Requiere versionado | 344 MB / 80 MB | Recorrido 15/15 con r2; aislada 13/13 (anterior) y 10/10 de lo afectado (`-r2`), en este equipo |
| Hermes y servidor MCP | Sí, `tfg/planner:2026.10.28`; en `-r2`, sin `planner-menu` ni `ollama` | Nada para la entrega solo con Hermes. Su menú de desarrollo sigue en la imagen, pero no lo abre ningún servicio distribuido | El sistema multiagente | `deploy/planner/Dockerfile` + `hermes_source.py` (commit `d923a5eb`) | 2,13 GB / 483 MB | 24/24 con dobles. Ejecución real solo con `2026.10.27` |
| QGroundControl 5.1.5 | Sí | Nada para la importación offline | El sistema multiagente | `deploy/qgc/` (AppImage oficial por sha256) | 1,2 GB / 329 MB | Primera importación 27/10 |
| ArduPilot SITL | No | Receta y compilación en imagen | **El subsistema rover** | `ardupilot` `755258db` (§3) | Por medir | §8.3 |
| ROS 2 Humble, AP_DDS y micro-ROS Agent | No | Base fijada por digest, Dockerfile y commit de *dev-ros*, y `ros-humble-*` con versiones fijadas | **El subsistema rover** | Base *dev-ros* sin Dockerfile ni commit registrados (§1); `micro-ROS-Agent` `c93ee764` | Por medir | §8.3 |
| Gazebo Harmonic, plugins y puentes | No | 121 paquetes `gz`/sdformat fijados (hoy solo en la capa mutable, §2) y `colcon build` | **El subsistema rover** | `ardupilot_gazebo` `cc0290d9`, `ros_gz` `28e586a3`, `sdformat_urdf` `7b73ddb8` | Por medir | §8.3 |
| Modelos, mundos y launch del TFG | No | Empaquetarlos en la imagen; los 3 cambios de `ardupilot_gz` como parche | **El subsistema rover** | `SITL_Models` `d5d60173`, `ardupilot_gz` `8df4dc17` + parche, `simulation/ros2_gazebo/launch/` | Por medir | §8.3 |
| Control operativo (lifecycle, readiness, preflight, executor, adaptador del rover) | No: hoy corre en el anfitrión con `.venv` y `docker exec` contra `tfg-ardupilot-gazebo` | Decidir dónde corre en la entrega sin depender del anfitrión de Joel y conservando sus gates | **El subsistema rover** | `tools/simulation_lifecycle.py`, `simulation/ros2_gazebo/scripts/` | — | §8.3 |
| Arranque y parada | Parcial: `docker compose run`/`down` para `app`, `qgc` y `hermes` | `start/stop_sim_backend.sh` sin `.venv` del anfitrión ni lock en su `/tmp` (§5) | **El subsistema rover** | `simulation/ros2_gazebo/scripts/` | — | §8.3 |
| Persistencia de misiones, sesiones e informes | Sí para app y planificación (`TFG_WORK_DIR`, `TFG_PLANNING_STORE`, volumen `hermes-home`) | Resultados de lifecycle, preflight y simulación en directorios elegidos por el estudiante | **El subsistema rover** (simulación); el sistema multiagente (Compose de entrega) | Compose | — | Sobreviven a `down` y a un nuevo arranque |
| Configuración y ejemplos | Sí: 9 entradas JSON | Perfiles de simulación (`two_drones`, `two_drones_rover`) dentro de la imagen | **El subsistema rover** | `tools/simulation_profiles.py` | — | Seleccionables sin rutas personales |
| Ollama y modelos | No | **No se incluirán** | — | — | — | No aparecen en la entrega final |

## 8. Traspaso al subsistema rover: construcción reproducible del simulador

El sistema multiagente no ha inspeccionado, arrancado, detenido ni copiado el contenedor operativo para preparar este traspaso. Todo sale de §1–§6 y del código del repositorio.

### 8.1 Qué hay que construir

- **Fuentes y versiones registradas:** los commits de §3, la imagen base de §1 y las versiones pip de §2.
- **Qué falta extraer del contenedor mutable:** las versiones exactas de los 917 paquetes dpkg (§2).
- **Dependencias que hoy solo existen en el contenedor mutable:** todo §2, es decir Gazebo y sdformat, 47 `ros-humble-*` y pip en `/usr/local`, más el `build/` y el `install/` hechos a mano del workspace (§3).
- **Rutas personales y temporales que deben desaparecer:** las de §5, más los montajes de `/home/joelm/...` de §4.
- **Modelos, plugins y recursos que hay que empaquetar:**
  - mundo `runway.sdf` (`ardupilot_gz_gazebo`);
  - IRIS para `drone1` y `drone2`, y WILD_THUMPER para `rover1` (`ardupilot_gz_bringup/launch/robots/`, `SITL_Models`);
  - el plugin de `ardupilot_gazebo` y los puentes `ros_gz`;
  - los `.parm` de rover y DDS (`rover.parm`, `rover-skid.parm`, `dds_udp.parm`, `dds_use_ns.parm`);
  - `tfg_demo.launch.py` y `tfg_demo_2drones.launch.py`.
- **No vale `docker commit`** como receta (§6).

### 8.2 Interfaces que hay que conservar

Las que consume hoy el código del repositorio ([simulation-profiles.md](simulation-profiles.md)). **Las rutas y los nombres actuales quedan sujetos a la revisión del subsistema rover.** Si cambian, hay que mantener la compatibilidad donde corresponda, o actualizar a la vez a todos sus consumidores:
- **AP_DDS:** `DDS_USE_NS 1` con espacios de nombres `/ap/v1`, `/ap/v2` y `/ap/v3` (`MAV_SYSID` 1–3); tópicos `/ap/vN/status` y servicios `/ap/vN/prearm_check`. El agente XRCE está en UDP 2019.
- **SITL:** puertos 5760, 5770 y 5780 (base 5760 + 10 × instancia).
- **Gazebo:** mundo `runway` y odometría del rover en `/model/rover1/odometry`.
- **Perfiles:** `two_drones` (por defecto) y `two_drones_rover`.
- **Variables:** `TFG_SIM_PROFILE`, `TFG_SIM_GUI`, `TFG_SIM_START_CONTEXT`, `TFG_SIM_PORTS` y `TFG_SIM_PROJECT`.
- **Rutas dentro del contenedor** que cita el código: `/root/ardu_ws` y `/workspace/tfg`. Se conservan o se parametrizan de forma coordinada.
- **Nombre del contenedor.** `tfg-ardupilot-gazebo` lo usan `ros2_flight_control.py`, `prearm_diagnostics.py`, `rover_environment_identity.py` y los scripts de arranque, parada y comprobación. Hay que fijarlo en Compose o hacerlo variable.
- **GUI por WSLg** como hoy (`/tmp/.X11-unix`, `/dev/dxg`, `/usr/lib/wsl`), o modo headless documentado.
- **Gates operativos intactos.** Las herramientas MCP `check_simulation_ready`, `start_simulation` y `restart_simulation` siguen pasando por lifecycle y por su autorización. **Arrancar un servicio no autoriza movimiento.**

### 8.3 Aceptación: independencia del equipo de Joel

1. **Build desde un clon versionado:** base y paquetes fijados, commits de §3 y sin acceso a `/home/joelm`, a la `.venv` del anfitrión ni al contenedor actual.
2. **`docker compose config` del servicio de simulación:** ningún bind a `/home/joelm/...` ni a `/tmp/tfg_*`; directorios de resultados elegidos por el usuario.
3. **Imagen limpia:** sin ccache, `/root/.ros/log`, logs de `/tmp` ni builds temporales del subsistema rover.
4. **Ciclo arranque → readiness → parada** con el lifecycle existente, bajo autorización propia:
   - `/ap/v1..v3/status` y `prearm_check` como espera el perfil;
   - sin procesos huérfanos;
   - resultados conservados tras `down` y un nuevo arranque.
5. **Exportación** con `docker save` y sha256, y carga desde cero **en un segundo ordenador**.

Una carga y lectura de vuelta de un `.plan` en SITL sigue pendiente, coordinada con el subsistema rover y con su propia autorización. La importación en QGC no acredita carga, ejecución ni hardware.
