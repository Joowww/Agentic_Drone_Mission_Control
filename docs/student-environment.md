# Entorno contenedorizado para estudiantes

Estado a 28/10/2026. Esta guía separa lo que ya se distribuye en imágenes de lo que todavía depende del entorno de desarrollo de Joel.

## 0. Entrega para estudiantes: objetivo y procedimiento único

**Objetivo:** una carpeta tipo pendrive con el software, las imágenes, los recursos, los ejemplos y los comandos para usar el proyecto, sin instalar a mano Python, ROS, Gazebo ni ArduPilot. El contenido final, lo que falta, los responsables y la aceptación están en un único mapa: [simulator-distribution-handoff.md](simulator-distribution-handoff.md) §7.

**La entrega parcial vigente** es `/home/joelm/TFG/entregas/tfg-entrega-estudiantes-2026.10.30/`, con `app`, `qgc` y `hermes`, y la IA es solo Hermes. Incluye el recorrido de las finalizaciones de Hermes a los `.plan` (§3 b). **No es la distribución completa: falta el simulador.** Las versiones anteriores, `…2026.10.28-r2/` y `…2026.10.28/`, se conservan intactas y quedan superadas; la segunda aún incluía `planner-menu` y `ollama`.

### Tres cosas distintas

| | Hoy (entrega parcial) | Entrega completa |
| --- | --- | --- |
| **Todo el software en la carpeta** | App, QGC, y Hermes con sus dependencias. **Falta el simulador** | App, QGC, Hermes y simulador |
| **Funciona sin descargar dependencias** | App, QGC y Hermes, una vez cargadas las imágenes (`docker load`) | Lo mismo, más el simulador |
| **Necesita conexión** | Solo Hermes: el proveedor remoto (`nous` / `poolside/laguna-s-2.1:free`) con **la cuenta propia del estudiante** | Igual. **No hay funcionamiento completo sin conexión**: sin proveedor no hay planificación con IA |

La entrega nunca incluye credenciales, tokens ni sesiones de Joel. **Ollama no forma parte de la entrega** (§9).

### Requisitos: anfitrión frente a imágenes

**Plataforma probada, que no es un requisito universal:** solo el equipo de Joel (versiones en §2). Windows x86_64 con WSL2 y Ubuntu 24.04.4, WSLg y Docker Desktop con integración WSL.

**Lo que exigen las imágenes, sea cual sea el sistema:**
- Docker con Compose v2 en x86_64 (imágenes `linux/amd64`);
- una pantalla X11 para QGC (y, en el futuro, quizá para la GUI de Gazebo);
- conexión al proveedor para Hermes.

**Opcional:** VS Code, solo para desarrollar; **no sustituye a Docker**.

**Lo que viene dentro de las imágenes:**
- Python 3.12 y dependencias del proyecto;
- Hermes con su CPython 3.14 y su entorno;
- QGroundControl 5.1.5;
- en el futuro, ArduPilot SITL, ROS 2 Humble con AP_DDS, Gazebo Harmonic, plugins, puentes y modelos.

**Sin medir, pendientes:**
- RAM;
- GPU: hoy el simulador usa `/dev/dxg` de WSLg, y no se sabe si es imprescindible;
- rendimiento;
- disco total con el simulador;
- cualquier otro sistema: Linux nativo, macOS o Windows sin WSLg.

### Recorrido único

Los comandos se ejecutan desde la carpeta de la entrega. **HOY** quiere decir que funciona con la entrega parcial y está comprobado en este equipo. **SIMULADOR** quiere decir que depende de incorporar el simulador: todavía **no hay comando**.

| Paso | Estado | Cómo |
| --- | --- | --- |
| 1. Requisitos del anfitrión | HOY | `uname -m` (x86_64), `docker version`, `docker compose version`, `ls /tmp/.X11-unix/X0` (WSLg) |
| 2. Hashes de la entrega | HOY | `sha256sum -c SHA256SUMS` |
| 3. Cargar imágenes | HOY: app, qgc y planner · SIMULADOR: su imagen | `docker load -i imagenes/<archivo>.tar` |
| 4. Elegir directorios de resultados | HOY | `mkdir -p $HOME/tfg-resultados $HOME/tfg-planificacion` y `export TFG_WORK_DIR=$HOME/tfg-resultados TFG_PLANNING_STORE=$HOME/tfg-planificacion TFG_UID=$(id -u) TFG_GID=$(id -g)` |
| 5a. App offline | HOY | `docker compose -f compose.yaml run --rm app` (menú, opción 5) y los comandos de su `LEEME.md` §4 |
| 5b. Hermes | HOY, con cuenta y conexión propias | `docker compose -f compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py check` (`PLANNING_SAFE`, sin conexión), luego `… hermes_home.py login` y `docker compose -f compose.yaml run --rm hermes` |
| 5c. QGC (importación offline de un paquete generado por la app) | HOY | Ver `LEEME.md` §4 (`QGC_PLAN_DIR` y `QGC_SAVE_DIR`) |
| 5d. Simulación | SIMULADOR | Sin comando todavía. Usará el lifecycle existente y sus gates. **Arrancar no autoriza movimiento** |
| 6. Localizar resultados | HOY | `$TFG_WORK_DIR/<salida>`, `$TFG_PLANNING_STORE/drafts/…`; las sesiones de Hermes, en el volumen `tfg-estudiante_hermes-home` |
| 7. Cerrar y volver a abrir | HOY | `docker compose -f compose.yaml down`; los directorios y el volumen se conservan, y `hermes_home.py status` vuelve a leer el almacén. Nunca `down -v` ni `prune` |

Es el mismo Compose y las mismas herramientas; no hay otro orquestador.

## 1. Qué se puede usar hoy

| Parte | Servicios (`deploy/compose.yaml`) | Estado |
| --- | --- | --- |
| **A. Distribución offline** | `app` (perfil `app`), `app-dev` (perfil `dev`), `qgc` (perfil `qgc`) | **Probada**: recorrido de estudiante 15/15 sin red ni LLM (§8). QGC usado en la primera importación |
| **B. Planificación con IA** | `hermes` (perfil `planning`); dobles en el perfil `planning-test`. `planner-menu` y `ollama` son solo de desarrollo | **Preparada**: imagen `tfg/planner:2026.10.28`, con 24/24 comprobaciones con dobles (§9) |
| **C. Inferencia real** | `hermes` con la cuenta del operador | **Una ejecución completada** el 28/10/2026 con la imagen **anterior** `tfg/planner:2026.10.27` (`651cc6e2…`), no con la actual ([planning-first-real-test.md](planning-first-real-test.md)) |
| **D. Simulador** | `sim` (no definido) | **Pendiente de distribución**: solo existe en un contenedor mutable ([simulator-distribution-handoff.md](simulator-distribution-handoff.md)) |

Todo va en el proyecto Compose `tfg-dist`, que no crea, arranca ni para los contenedores de desarrollo `tfg-ardupilot-gazebo` y `tfg-ardupilot-ros2`.

La imagen `app` funciona **sin proveedor LLM y sin red** y **no es una distribución de la planificación con IA**. La imagen fija `TFG_PROFILE=offline`, y en ese perfil el menú principal marca como `[NOT AVAILABLE: …]` las opciones que no pueden funcionar y no las ejecuta si se eligen:
- **1 y 3** (lenguaje natural y planificador con IA): desde `tfg/app:2026.10.28`, «not part of the student distribution; AI planning there is the separate Hermes service». En `-r2` el texto decía que necesitaban Ollama.
- **2 y 4** (misión JSON e importación `.plan`): guardan la sesión en `missions/generated`, que la imagen de solo lectura no proporciona.

El menú de desarrollo (`python main.py` en el anfitrión, sin esa variable) no cambia. El recorrido para estudiantes usa la **opción 5** (escenario) y los comandos de §4.

## 2. Requisitos del anfitrión

| | Requisito | Probado en |
| --- | --- | --- |
| Sistema | Windows con WSL2 y, para QGC, WSLg; x86_64 | Windows 10.0.26300.9711, WSL 2.7.14.0, WSLg 1.0.73.2, kernel 6.18.33.2 |
| Distribución WSL | Ubuntu, con el repositorio **dentro** de WSL y no en `/mnt/c` | Ubuntu 24.04.4 LTS |
| Docker | Docker Desktop con integración WSL activada para esa distribución, BuildKit y Compose v2 | Docker Engine 29.8.0, Compose v5.5.1 |
| Pantalla (solo `qgc`) | Socket X11 de WSLg en `/tmp/.X11-unix/X0` y `DISPLAY=:0` | Presente |
| Disco | `app` 345 MB; `qgc` 1,2 GB; `planner` 2,13 GB; más la caché de build. Archivos de la entrega parcial: 851 MB | Medido. Con el simulador: por medir |
| VS Code (opcional, para desarrollo) | Con acceso a WSL; usa las plantillas de `deploy/vscode/` | Usado; versión no registrada |
| RAM, GPU y rendimiento | — | **No medidos** |

Solo se ha probado en el equipo de Joel (WSL2/WSLg). Eso no demuestra que funcione en Linux nativo, macOS ni Windows sin WSLg.

## 3. Obtener las imágenes

**a) Construir desde las fuentes distribuidas** (probado), desde la raíz del repositorio:

```bash
docker compose -f deploy/compose.yaml --profile app build app
docker compose -f deploy/compose.yaml --profile qgc build qgc
```

- **`app`**: base `ubuntu:24.04` fijada por digest, Python 3.12.3 y paquetes de sistema del snapshot de Ubuntu del 24/10/2026, y dependencias Python exactamente las de `constraints-verified.txt`. El código entra solo a través de la lista generada `deploy/app/Dockerfile.dockerignore`, que no admite `.venv`, `missions/generated`, tests, cachés ni credenciales.
- **`qgc`**: el AppImage de la release oficial v5.1.5, comprobado por sha256.
- Ambos *builds* necesitan red; la ejecución, no.
- Si `snapshot.ubuntu.com` no responde (el 27/10 dio 503 durante unos minutos), el build falla de forma explícita y basta con repetirlo.

**b) Imagen preconstruida:** **todavía no hay registro ni imagen publicada**, así que no hay comando `pull`.

**Entrega parcial vigente para estudiantes** `tfg-entrega-estudiantes-2026.10.30` (no publicada; **sin simulador**; solo Hermes), en `/home/joelm/TFG/entregas/`, fuera del repositorio:
- **Contenido:** las tres imágenes exportadas con `docker save` (`app` `2026.10.30`, `qgc` y `planner` `2026.10.28`, las dos últimas reutilizadas de las versiones anteriores), 851 MB en total, servicios `app`, `qgc` y `hermes`. `app` monta `TFG_PLANNING_STORE` en solo lectura para empaquetar las finalizaciones de Hermes (`package-finalized`, §6 de su `LEEME.md`), más un Compose sin rutas del repositorio (proyecto `tfg-estudiante`, con directorios elegidos por el estudiante), el script del recorrido, entradas de ejemplo extraídas de la imagen `app`, `VERSIONES.json` y `SHA256SUMS`.
- **Uso:** está en su `LEEME.md`, que es lo que necesita quien solo recibe la carpeta: `sha256sum -c SHA256SUMS`, `docker load -i imagenes/…`, `export TFG_WORK_DIR=…` y los comandos de la tabla de §4 con `-f compose.yaml`.
- **Verificación:** de lo afectado, 12/12 **solo en este equipo**, desde un directorio aislado y con finalizaciones de prueba SINTÉTICAS (`evaluation/observability/student_bundle_2026_10_30/`). Se apoya en las de las versiones anteriores: 10/10 en `-r2` y 13/13 en la primera. **La prueba en otro ordenador está pendiente.**
- **Versiones anteriores** `…2026.10.28-r2` y `…2026.10.28`: conservadas intactas y superadas.

## 4. Uso

Crea primero, una sola vez, el directorio de resultados. Es el único lugar donde escribe la aplicación (`/work` dentro del contenedor):

```bash
mkdir -p work
```

| Para | Comando (desde la raíz del repositorio) |
| --- | --- |
| Abrir el menú | `docker compose -f deploy/compose.yaml run --rm app` (opción 5 → escenario) |
| Consultar el escenario histórico | `docker compose -f deploy/compose.yaml run --rm app -m tools.agri_scenario_flow query --out /work/consulta_1` |
| Lanzar la demo sintética | `docker compose -f deploy/compose.yaml run --rm app -m tools.agri_scenario_flow demo --variant complete --out /work/demo_1` |
| Reanudar una demo interrumpida | añadir `--resume` con el mismo `--out` (no readmite) |
| Validar un emplazamiento | `docker compose -f deploy/compose.yaml run --rm app -m tools.scenario_package validate-site missions/sites/synthetic_orchard_v1.site.json` |
| Exportar un paquete SITL | `docker compose -f deploy/compose.yaml run --rm app -m tools.scenario_package package --template missions/templates/agri_poi_visit_v1.json --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json --target sitl --out /work/paquete_1` |
| Verificar el paquete | `docker compose -f deploy/compose.yaml run --rm app -m tools.scenario_package verify /work/paquete_1` |
| Comparar planes | `docker compose -f deploy/compose.yaml run --rm app -m tools.qgc_plan_compare /work/paquete_1/plans/drone_01.plan /work/qgc_guardado/drone_01.qgc_resaved.plan --out /work/comparacion_1` |
| Abrir QGC con un paquete | `mkdir -p work/qgc_guardado && QGC_PLAN_DIR=$PWD/work/paquete_1/plans QGC_SAVE_DIR=$PWD/work/qgc_guardado docker compose -f deploy/compose.yaml run --rm --name tfg-qgc qgc` |
| Todo el recorrido, comprobado | `deploy/app/student_walkthrough.sh work/recorrido_1` |

**Rutas.** Las entradas incluidas en la imagen (`missions/...` y `evaluation/...`) se escriben como en el repositorio. Las salidas siempre van a `/work/<nombre nuevo>`, que en el anfitrión es `work/<nombre nuevo>`.

**Lo que se ve en pantalla.** Cada etapa indica qué hace, el origen de los datos (`REAL_HISTORICAL` para copias conservadas, `SYNTHETIC` para la demo, `TEMPLATE` para DroneLab), dónde queda el informe y el motivo de cualquier rechazo (`BLOCKED_MISSING_DATA`, `INCOMPLETE`, `REFUSED: … exists`…).

**Cancelar y salir.**
- `Ctrl+C` interrumpe. Si llega mientras el programa aún se está cargando, termina con un mensaje y el código 130, sin traceback. Si llega durante la demo, se conservan sus registros y se reanuda con `--resume` sin volver a admitir.
- En el menú, `exit` cierra y `menu` vuelve atrás.
- Los directorios de salida que ya existen **nunca se sobrescriben**: el comando se niega.

**Si no se puede escribir** (disco lleno, directorio de solo lectura o sin permisos), el flujo termina con código 4 y lo explica. Las salidas **no** quedan marcadas como terminadas (`outputs_manifest.json` sigue en `IN_PROGRESS`). Puede quedar algún `*.tmp`:
- nunca se lee ni cuenta como registro;
- se sustituye en la siguiente escritura correcta;
- puede permanecer si el almacenamiento no permite borrarlo.

Cuando vuelva a poder escribirse, reanuda la demo con `--resume` sobre el mismo directorio, o repite la consulta en uno nuevo.

**VS Code.** La plantilla versionada [`deploy/vscode/tasks.json`](../deploy/vscode/tasks.json) contiene las tareas «TFG App: …» y «TFG QGC: …» con estos comandos, y pide en cada ejecución el nombre del directorio nuevo y la variante.
- **Si no tienes `.vscode/tasks.json`:** `mkdir -p .vscode && cp -n deploy/vscode/tasks.json .vscode/tasks.json`. `-n` no sobrescribe un archivo existente.
- **Si ya lo tienes:** copia a mano los objetos de `tasks` y de `inputs` de la plantilla a tu archivo.

Después, ejecútalas con *Terminal → Run Task…*. `.vscode/` sigue siendo configuración personal e ignorada por Git.

## 5. Resultados y permisos

- Quedan en `work/` (o en `TFG_WORK_DIR`) y sobreviven al contenedor, que se elimina con `--rm`.
- El contenedor se ejecuta con tu uid/gid (`TFG_UID`/`TFG_GID`, por defecto 1000), así que los archivos son tuyos y editables. Si tu uid no es 1000, exporta `TFG_UID=$(id -u) TFG_GID=$(id -g)`.
- Solo se monta el directorio de trabajo. Ni credenciales, ni SSH, ni HOME, ni el socket de Docker. Las evidencias originales están dentro de la imagen, en solo lectura.
- Para entregar resultados, comprime el directorio de `work/` o cópialo a `evaluation/observability/<nuevo>/` con su `SHA256SUMS`.

## 6. Cerrar sin borrar datos

- Cada `run --rm` termina solo. Si QGC no responde: `docker stop tfg-qgc`.
- `docker compose -f deploy/compose.yaml down` solo afecta al proyecto `tfg-dist`.
- No uses `docker system prune`, `docker volume prune`, `down -v` ni borres `work/` para «repetir». Usa un nombre de salida nuevo.

## 7. Simulador

Pendiente: no se ha reconstruido y lo construye el subsistema rover. El mapa de la entrega completa y el traspaso están en [simulator-distribution-handoff.md](simulator-distribution-handoff.md) §7–§8.

## 8. Registro de builds y pruebas

**`app` 2026.10.28, la imagen actual de Compose** (evidencia en `evaluation/observability/student_bundle_2026_10_28_r2/app_build/`)
- Imagen `tfg/app:2026.10.28`, ID `sha256:7ae59021978f3656f63cb7366819f7b8ac19aff0a5a0f38615f919f69ec0d988`. Solo existe en local.
- **Contexto congelado:** los 401 archivos de r2 con solo `main.py` cambiado, que son los textos del menú offline para usar solo Hermes. No incorpora los otros cambios del árbol posteriores a r2.
- **Dependencias:** `pip freeze` idéntico al de r2, con base y deps desde caché.

**`app` r2, conservada con su etiqueta** (evidencia en `evaluation/observability/app_container_build_2026_10_27_r2/`)
- Imagen `tfg/app:2026.10.27-r2`, ID `sha256:a86dae081f3fb3013abec5198e319ef82b38fea4ff5d54f3dbfbfed0a77d307b`. Solo existe en local.
- Cambios respecto a la primera imagen:
  - menú offline con opciones no disponibles y su motivo;
  - entrada `deploy/app/entry.py`, para que un Ctrl+C durante la carga no muestre un traceback;
  - errores de escritura del flujo con código 4 y explicación.
- Sus 401 archivos de `/opt/tfg` son idénticos al árbol.
- Recorrido de estudiante repetido: 15/15.
- Probados en contenedor: el menú offline, el Ctrl+C temprano (rc 130 sin traceback), un directorio sin escritura y un tmpfs lleno (rc 4; `IN_PROGRESS`; el `.tmp` no se consume).

**`app` 2026.10.27, la primera imagen, conservada con su etiqueta** (evidencia en `evaluation/observability/app_container_build_2026_10_27/`)
- Imagen `tfg/app:2026.10.27`, ID `sha256:67bc37afc8be27da0ba7e7717b6a788e9cc0d3b39e8873947db5cd768d0d7085`. Solo existe en local.
- Los 400 archivos de `/opt/tfg` son idénticos al árbol inventariado, y las 60 versiones Python coinciden con `constraints-verified.txt`.
- Recorrido de estudiante 15/15, desde un directorio nuevo con solo `deploy/compose.yaml` y el script: sin repositorio, sin `.venv`, con `env -i` y HOME vacío, y sin red.
- Probados también: el menú, el rechazo de directorios existentes, la cancelación con reanudación sin readmitir, y los errores de escritura (directorio sin permisos y almacenamiento lleno).

**`qgc`** (evidencia en `evaluation/observability/qgc_container_build_2026_10_27/`)
- Imagen `tfg/qgroundcontrol:5.1.5`, ID `sha256:c6a5c57a…f314`.
- Usada por Joel para la primera importación (`qgc_first_import_2026_10_27`). Solo cubre ese uso.

## 9. Planificación con IA

**Para estudiantes, solo Hermes.** Las entradas antiguas del menú que necesitan Ollama son la **1** («Natural language mission») y la **3** («AI Mission Planner»), en `main.py`.
- **Entrega parcial `-r2` (hecho):**
  - su Compose solo tiene `app`, `qgc` y `hermes`, sin `planner-menu` ni `ollama`;
  - el menú de `tfg/app:2026.10.28` marca las opciones 1 y 3 como fuera de la entrega y remite a Hermes;
  - su `LEEME.md` no menciona Ollama.
- **Imagen `planner`:** no se reconstruyó. Su `main.py` conserva el menú de desarrollo (`TFG_PROFILE=planning`), pero ningún servicio distribuido lo abre: `hermes` arranca `hermes_home.py`.
- **Entrega anterior** `…2026.10.28`: se conserva intacta y todavía cita Ollama como opcional; está superada.
- **Desarrollo:** el código y los servicios de Ollama se quedan como están.

Lo que sigue sobre Ollama describe **el entorno de desarrollo**.

### Dos recorridos distintos

| | Hermes (recorrido de H1) | Menú opciones 1 y 3 (solo desarrollo) |
| --- | --- | --- |
| Agente | Hermes `d923a5eb` + el servidor MCP del proyecto (`tools.hermes_mcp_server`) por stdio | `agents/mission_planner.py` y `mission_editor.py` (LangChain `ChatOllama`) dentro de `main.py` |
| Proveedor y modelo | `nous` / `poolside/laguna-s-2.1:free`, los de H1: remoto, con la cuenta propia del operador | Ollama local, `qwen3:4b` (digest `359d7dd4…`, 2,5 GB, Q4_K_M), el mismo que hay en el equipo de Joel con Ollama 0.34.2 |
| Servicio | `hermes` (red `provider`, con salida solo para el proveedor) | `planner-menu` (red interna `local-llm`) + `ollama` (`ollama/ollama:0.34.2@sha256:da6e0dc5…`) |
| Herramientas | Solo `update_mission_draft` y `finalize_mission_draft` | Las del menú: validación y exportación deterministas, sin MCP |

### Obtener y preparar

```bash
python3 deploy/planner/hermes_source.py fetch --out deploy/planner/vendor/hermes-agent-d923a5eb.tar
docker compose -f deploy/compose.yaml --profile planning build hermes
mkdir -p work/planning_store
```

- **Fuente de Hermes.** `hermes_source.py` toma exactamente el commit `d923a5eb` y comprueba que su árbol es `5a064077…`. Desde un clon que ya lo tenga, se usa `export --repo <clon>`. El build vuelve a verificar el sha256 (`5b668df1…`) y el árbol, y no hace `fetch` de git.
- **Dependencias.** uv 0.12.3 y CPython 3.14.7 vienen fijados en el `pm/lock.json` de Hermes, y el resto sale de su `uv.lock` con el extra `all`, todo desde PyPI.
- **Credenciales.** No hay ninguna en la imagen. Cada operador inicia sesión una vez y su acceso queda en el volumen `hermes-home`:

  ```bash
  docker compose -f deploy/compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py login
  ```

- **Modelo de Ollama (solo desarrollo, no forma parte de la entrega).** Solo hace falta para las opciones 1 y 3. Se descarga al volumen `ollama-models`:

  ```bash
  docker compose -f deploy/compose.yaml --profile planning up -d ollama
  docker compose -f deploy/compose.yaml exec ollama ollama pull qwen3:4b
  ```

  **Nada de esto se ha ejecutado aún.** La imagen de Ollama (3,7 GB comprimidos) y el modelo no se han descargado, y su arranque no se ha observado.

### Uso

| Para | Comando |
| --- | --- |
| Sesión interactiva de planificación con Hermes | `docker compose -f deploy/compose.yaml run --rm hermes` |
| Una sola petición | `docker compose -f deploy/compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py run -z "…"` |
| Estado: configuración, sesión iniciada, borradores y finalizaciones | `docker compose -f deploy/compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py status` |
| Menú completo con Ollama (solo desarrollo) | `docker compose -f deploy/compose.yaml --profile planning run --rm planner-menu` |

- **Qué se ve al arrancar.** Hermes muestra el proveedor y el modelo, las dos herramientas permitidas y dónde quedan los resultados.
- **Persistencia.** Borradores, finalizaciones, misiones e informes van a `work/planning_store` (`TFG_PLANNING_STORE`). Las sesiones de Hermes se guardan en el volumen `hermes-home`. Todo sobrevive al contenedor y `status` lo vuelve a leer.
- **Finalizaciones.** Una finalización sin `finalization.json` aparece como INCOMPLETA y no es un resultado.
- **Cancelar.** `Ctrl+C` envía SIGINT a Hermes. La cancelación probada (con el doble) fue SIGINT seguido, 5 s después, de terminación forzada del contenedor. **No se ha comprobado un cierre limpio por Ctrl+C.** Lo acreditado es que no apareció ninguna finalización nueva. Después de cancelar, revisa el estado con `status`.
- **Exportación estricta.** Si faltan referencias o la AMSL del home, `qgc_export` sale `REFUSED` con sus motivos, y no se escribe ningún `.plan`.

### Separado de la operación

- Hermes solo recibe `--toolsets tfg-mission-control`, y el home lleva el filtro `tools.include` de las dos herramientas con Tool Search desactivado, que es el mecanismo existente y verificado en H1. Antes de cada arranque, el lanzador comprueba esa configuración y se niega a ejecutar si ha cambiado o si se intenta pasar otro `--toolsets`.
- El servidor MCP publica 27 herramientas, entre ellas las operativas. En la imagen están, pero Hermes no las ofrece.
- Ningún servicio de planificación tiene socket de Docker, ROS, dispositivos ni acceso a la red del simulador.
- Opik está desactivado.

### Imagen vigente: `tfg/planner:2026.10.28`

- ID `sha256:e2c4513e4ca6982c5d7c88811d4df647d6d7c35055f284104f3aa0f0077e2112`, que es la que usa Compose. Evidencia: `evaluation/observability/planner_container_build_2026_10_28/`.
- **Cambios respecto a `2026.10.27`:**
  - el ejecutor de capturas pasa `HERMES_HOME=--hermes-home` al proceso de Hermes;
  - `hermes_home.py login` funciona en el home de ensayo;
  - deduplicación en la herramienta de inventario.
- **Módulos del subsistema rover:** los dos de `rover_xrce_trace` son los de la imagen anterior, para no incorporar cambios concurrentes.
- **Sin descargas nuevas:** la misma fuente congelada de Hermes y las mismas dependencias, salidas de la caché.
- **Ejecución real:** la del 28/10 (`planning_container_real_2026_10_28_r2`) acredita **solo** la imagen `2026.10.27` (`651cc6e2…`), que es la que usó. Con la `2026.10.28` no se ha hecho ninguna ejecución real.

### Comprobado con dobles (24/24 con `2026.10.28`, `deploy/planner/planning_checks.sh`)

Con un proveedor falso, compatible con OpenAI y con Ollama y **sin modelo**, sobre una red interna sin salida:
- Hermes ofrece exactamente las 2 herramientas;
- el servidor MCP real guarda el borrador y la finalización;
- la validación es FEASIBLE/APPROVED y `qgc_export` sale `REFUSED` por falta de AMSL;
- un contenedor nuevo vuelve a leer el resultado;
- una respuesta inválida, el proveedor ausente o un almacén de solo lectura no producen ninguna finalización;
- con el proveedor sin responder, SIGINT seguido de terminación forzada tampoco produce ninguna (no es una prueba de cierre limpio);
- el recorrido `ChatOllama` del menú funciona contra el doble y rechaza la respuesta inválida;
- en los logs de las comprobaciones no aparecieron los patrones de credenciales buscados (`Bearer …`, `sk-…`, `api_key`/`token` con valor);
- en `/hermes`, `/opt/tfg`, `/tmp` y `/root` de la imagen no hay archivos `auth.json`, `.env`, `id_rsa*` ni `.netrc`, y el home de planificación de la imagen está vacío.

Esto **no es una prueba de ausencia universal de credenciales**: solo cubre esos patrones, esos nombres y esos directorios.

Añadido con la `2026.10.28`, siempre con el doble:
- **Home pedido:** el ejecutor ejecuta Hermes en el home de `--hermes-home` aunque el contenedor tenga otro `HERMES_HOME`.
- **Recorrido completo por el ejecutor:** Hermes → MCP → finalización, con solo las 2 herramientas, persistencia leída desde otro contenedor, REFUSED sin AMSL y veredicto `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`.
- **Login:** `login` inicia el flujo de Nous en el home de ensayo contra un portal falso, sin guardar ninguna credencial.

**Reintentos y peticiones.** Una ejecución de Hermes incluye varias peticiones normales del ciclo de herramientas. Ante los dos fallos simulados (respuesta inválida y proveedor ausente), Hermes informó de 3 intentos antes de rendirse. Es lo observado con el doble en esos casos, no un máximo global de peticiones. Ninguna ejecución se relanzó.

### Ejecución con captura de evidencia (la usada en la prueba real)

Con la imagen vigente no hace falta ningún arreglo manual; `-e HERMES_HOME=…` sigue disponible para elegir el home explícitamente.

```bash
mkdir -p work/planning_store work/hermes-private
docker compose -f deploy/compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py prepare-trial /hermes/trial
docker compose -f deploy/compose.yaml run --rm -e HERMES_HOME=/hermes/trial hermes /opt/tfg/deploy/planner/hermes_home.py login
docker compose -f deploy/compose.yaml run --rm hermes -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case agri-planning-container --hermes-home /hermes/trial --hermes-bin /opt/hermes/agent/.venv/bin/hermes --private-root /work/hermes-private
```

1. El primer comando crea el home de ensayo.
2. El segundo inicia sesión en él con tu propia cuenta de Nous: abre la URL que muestra en el navegador.
3. El tercero es la comprobación previa, sin llamar al proveedor. Debe dar `"ok": true`.

La ejecución en sí añade `--timeout 300 --run-id <nuevo> --execute` y lanza **una** ejecución de Hermes, que no se relanza; necesita autorización. Después, `review … --evidence-dir /work/<nuevo>`. El registro de la prueba real y su criterio está en [planning-first-real-test.md](planning-first-real-test.md).

### Pendiente

- **Hermes con la imagen vigente:** ninguna ejecución real con la `2026.10.28`, solo con dobles.
- **Recursos:** imagen `planner` de 2,1 GB. La memoria necesaria no se ha medido.
- **Ollama (solo desarrollo):** su arranque y la descarga de `qwen3:4b` no se han hecho.

## 10. Pendientes de distribución y validación

1. **Prueba en un segundo ordenador.** La entrega parcial no se ha probado fuera del equipo de Joel: `sha256sum -c`, `docker load` desde cero y el recorrido de su `LEEME.md`.
2. **Simulador reproducible.** Lo construye el subsistema rover; el traspaso y la aceptación están en [simulator-distribution-handoff.md](simulator-distribution-handoff.md) §8.
3. **Entradas para estudiantes solo con Hermes:** hecho en la entrega parcial `-r2`. La entrega completa debe mantenerlo (§9).
4. **Versionado.** Gran parte del conjunto distribuible no tiene seguimiento en Git: código nuevo, `deploy/`, documentos y evidencias. Hay que versionarlo para que un clon reproduzca las imágenes (ver los inventarios de cada build).
5. **Licencia.** El proyecto no tiene archivo de licencia y hay que decidirla antes de publicar. Las dependencias tienen licencias permisivas; si se distribuye QGC, hay que revisar sus avisos y los de Qt.
6. **Publicación eventual.** No hay registro ni ninguna imagen publicada, así que todavía no hay comando `pull`. Hasta entonces: construir desde las fuentes (§3) o usar la entrega parcial de §3 b).

**Carga en SITL.** La carga y lectura de vuelta de un `.plan` en SITL sigue pendiente, coordinada con el subsistema rover y con autorización aparte. La importación en QGC no acredita carga, ejecución ni hardware.
