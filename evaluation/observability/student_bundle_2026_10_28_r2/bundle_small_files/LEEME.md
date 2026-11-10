# Entrega PARCIAL para estudiantes — 2026.10.28-r2

Entrega **local, no publicada y parcial**: **todavía falta el simulador**. Contiene tres imágenes exportadas con `docker save`, el Compose para usarlas, el script del recorrido, entradas de ejemplo y la identificación de versiones (`VERSIONES.json`). No incluye credenciales, sesiones, cachés ni código fuente del repositorio.

## Qué se puede usar

| Parte | Estado |
| --- | --- |
| **App offline** (`app`) | Utilizable sin red: consulta del escenario conservado, demo sintética, validación de emplazamientos, exportación y verificación de paquetes, comparación de `.plan` e informes |
| **QGroundControl** (`qgc`) | Utilizable sin red ni dispositivos para abrir un paquete generado por `app` y guardar una copia. Necesita una pantalla X11 (WSLg en Windows) |
| **Planificación con IA: Hermes** (`hermes`) | Necesita **tu propia cuenta** del proveedor (`nous`, modelo `poolside/laguna-s-2.1:free`) y conexión a él. Solo tiene dos herramientas: guardar el borrador (`update_mission_draft`) y finalizarlo (`finalize_mission_draft`). La imagen no trae ninguna credencial |
| **Simulador** (ArduPilot SITL, ROS 2, Gazebo) | **Todavía no incluido**. Se añadirá en una versión posterior |

- **La demo es sintética (`TEST_DOUBLE`):** no ejecuta ni simula vehículos.
- **La consulta del escenario** lee copias conservadas de una ejecución histórica; no es una ejecución nueva.
- **En el menú de la app,** las opciones 1–4 aparecen como no disponibles. El escenario es la opción 5, y la planificación con IA es el servicio `hermes` (§5).

## Requisitos

**Plataforma probada** (la única en la que se ha comprobado esta entrega, el equipo donde se preparó):
- Windows 10.0.26300 con WSL 2.7.14 y WSLg 1.0.73;
- Ubuntu 24.04.4 en WSL;
- Docker Desktop (Engine 29.8.0, Compose v5.5.1) con la integración WSL activada;
- x86_64.

**Lo que exigen las imágenes, sea cual sea el sistema:**
- Docker con Compose v2 en una máquina x86_64 (imágenes `linux/amd64`);
- una pantalla X11 para QGC;
- conexión al proveedor para Hermes;
- unos 0,9 GB de archivos y unos 3,7 GB de imágenes cargadas.

**Sin probar:** que funcione en otros sistemas (Linux nativo, macOS, Windows sin WSLg). La RAM y el rendimiento no se han medido.

Copia esta carpeta **dentro** de WSL (por ejemplo en `$HOME`), no en `/mnt/c`. Todos los comandos se ejecutan **desde esta carpeta**.

## 1. Verificar los hashes

```bash
sha256sum -c SHA256SUMS
```

Todas las líneas deben terminar en `OK`. Si alguna dice `FAILED`, la copia está dañada: vuelve a copiarla.

## 2. Cargar las imágenes

```bash
docker load -i imagenes/tfg-app-2026.10.28.tar
docker load -i imagenes/tfg-qgroundcontrol-5.1.5.tar
docker load -i imagenes/tfg-planner-2026.10.28.tar
docker image inspect --format '{{.Id}} {{.RepoTags}}' tfg/app:2026.10.28 tfg/qgroundcontrol:5.1.5 tfg/planner:2026.10.28
```

Los ID deben coincidir con `image_id` de `VERSIONES.json` (`7ae59021…`, `c6a5c57a…` y `e2c4513e…`).

## 3. Elegir los directorios de resultados

Elige directorios tuyos, con ruta absoluta y fuera de esta carpeta:

```bash
mkdir -p $HOME/tfg-resultados $HOME/tfg-planificacion
export TFG_WORK_DIR=$HOME/tfg-resultados TFG_PLANNING_STORE=$HOME/tfg-planificacion TFG_UID=$(id -u) TFG_GID=$(id -g)
```

Repite el `export` en cada terminal nueva. Sin él, los contenedores no arrancan (`*_not_set`).

## 4. App offline y QGC

| Para | Comando |
| --- | --- |
| Menú (opción 5: escenario) | `docker compose -f compose.yaml run --rm app` |
| Consultar el escenario conservado | `docker compose -f compose.yaml run --rm app -m tools.agri_scenario_flow query --out /work/consulta_1` |
| Demo sintética | `docker compose -f compose.yaml run --rm app -m tools.agri_scenario_flow demo --variant complete --out /work/demo_1` |
| Exportar un paquete SITL de ejemplo | `docker compose -f compose.yaml run --rm app -m tools.scenario_package package --template missions/templates/agri_poi_visit_v1.json --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json --target sitl --out /work/paquete_1` |
| Verificar el paquete | `docker compose -f compose.yaml run --rm app -m tools.scenario_package verify /work/paquete_1` |
| Recorrido completo comprobado (el directorio no debe existir) | `scripts/student_walkthrough.sh $HOME/tfg-recorrido-1` |

- Las rutas `missions/...` son las entradas incluidas en la imagen. Sus copias están en `ejemplos/missions/`.
- Para usar una entrada modificada, cópiala a tu directorio de resultados (`cp -r ejemplos/missions $TFG_WORK_DIR/entradas`) y pásala como `/work/entradas/...`.
- Un directorio de salida que ya existe nunca se sobrescribe: el comando se niega.

**Abrir el paquete en QGC** (sin red, sin vehículos; el paquete se monta de solo lectura):

```bash
mkdir -p $TFG_WORK_DIR/qgc_guardado
QGC_PLAN_DIR=$TFG_WORK_DIR/paquete_1/plans QGC_SAVE_DIR=$TFG_WORK_DIR/qgc_guardado docker compose -f compose.yaml run --rm --name tfg-qgc qgc
```

En QGC, abre el plan desde `/data/plan` y guarda tu copia en `/data/saved`. Para comparar ambos planes:

```bash
docker compose -f compose.yaml run --rm app -m tools.qgc_plan_compare /work/paquete_1/plans/drone_01.plan /work/qgc_guardado/drone_01.plan --out /work/comparacion_1
```

Ajusta el segundo nombre al que hayas usado al guardar. La importación en QGC no carga nada en un vehículo ni en el simulador.

## 5. Planificación con Hermes (requiere tu cuenta y conexión)

```bash
docker compose -f compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py check
docker compose -f compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py login
docker compose -f compose.yaml run --rm hermes
docker compose -f compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py status
```

1. `check` prepara tu home de Hermes, sin conectarse a nada. Debe decir `PLANNING_SAFE`, lo que significa que solo están las dos herramientas.
2. `login` abre el flujo de tu cuenta de Nous: abre en el navegador la URL que muestre. Tu sesión queda en el volumen Docker `tfg-estudiante_hermes-home` de tu equipo, nunca en esta carpeta.
3. `run` sin argumentos abre la sesión de planificación. No hay simulación ni vehículos.
4. `status` lista los borradores y finalizaciones guardados en `TFG_PLANNING_STORE`.

Probado con uid 1000. Con otro uid, el volumen de Hermes puede no ser escribible.

## 6. Localizar los resultados

- **App y QGC:** `$TFG_WORK_DIR/<nombre>`. Cada salida trae su informe y su manifiesto.
- **Recorrido completo:** el directorio que le diste, con `walkthrough.tsv` como resumen.
- **Planificación:** `$TFG_PLANNING_STORE/drafts/…`. La sesión y el login de Hermes están en el volumen `tfg-estudiante_hermes-home`.

Para entregar resultados, comprime esos directorios. No incluyas el volumen de Hermes: contiene tu login.

## 7. Cerrar y volver a abrir sin perder nada

- Cada `run --rm` termina solo y borra únicamente el contenedor.
- `Ctrl+C` interrumpe. La demo conserva sus registros y se reanuda con `--resume` y el mismo `--out`.
- Si QGC no responde: `docker stop tfg-qgc`.
- `docker compose -f compose.yaml down` solo afecta al proyecto `tfg-estudiante` y conserva tus directorios y el volumen de Hermes. Al volver, repite el `export` de §3 y `status` lee lo que había.
- **No uses** `down -v`, `docker volume prune` ni `docker system prune`: borrarían tu login y tus sesiones de Hermes.

## Límites de esta entrega

- **Falta el simulador.** Lo construye otro trabajo del proyecto; sus rutas y nombres actuales pueden cambiar.
- **Probada solo en el equipo donde se preparó,** donde las imágenes ya existían. **La prueba en un segundo ordenador está pendiente.**
- **Hermes no se ha ejecutado con el proveedor real desde esta entrega.** La única ejecución real se hizo con la imagen anterior, `tfg/planner:2026.10.27`.
- **Antes de una distribución pública faltan** la licencia, el versionado y la publicación. Esta entrega **no tiene licencia elegida**: no la publiques ni la redistribuyas. La imagen de QGC incluye QGroundControl y Qt, con sus propias licencias.
