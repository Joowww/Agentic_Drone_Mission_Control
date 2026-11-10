# Entrega local para estudiantes — 2026.10.28

Entrega **local, no publicada**. Contiene tres imágenes exportadas con `docker save`, el Compose para usarlas, el script del recorrido, entradas de ejemplo y la identificación de versiones (`VERSIONES.json`). No incluye credenciales, sesiones, cachés, código fuente del repositorio ni el simulador.

## Qué se puede usar

| Parte | Estado |
| --- | --- |
| **App offline** (`app`) | Utilizable sin red ni LLM: consulta del escenario conservado, demo sintética, validación de emplazamientos, exportación y verificación de paquetes, comparación de `.plan` e informes |
| **QGroundControl** (`qgc`) | Utilizable sin red ni dispositivos para abrir un paquete generado por `app` y guardar una copia. Necesita WSLg (X11) |
| **Planificación con Hermes** (`hermes`) | Necesita **tu propia cuenta** del proveedor (Nous) y conexión a él. La imagen no trae ninguna credencial |
| **Ollama** (`planner-menu`, `ollama`) | **Opcional y no incluido**: la imagen y el modelo `qwen3:4b` se descargarían de Internet si lo arrancas. No se ha probado |
| **Simulador** | **Pendiente de distribución**. No está en esta entrega |

**La demo es sintética (`TEST_DOUBLE`): no ejecuta ni simula vehículos.** La consulta del escenario lee copias conservadas de una ejecución histórica; no es una ejecución nueva.

## Requisitos

- Windows con WSL2 (Ubuntu) y, para QGC, WSLg; x86_64.
- Docker Desktop con la integración WSL activada y Compose v2.
- Disco: 0,9 GB los archivos de imagen y unos 3,7 GB las imágenes cargadas.
- Copia esta carpeta **dentro** de WSL (por ejemplo en `$HOME`), no en `/mnt/c`.

Todos los comandos se ejecutan **desde esta carpeta**.

## 1. Verificar los hashes

```bash
sha256sum -c SHA256SUMS
```

Todas las líneas deben terminar en `OK`. Si alguna dice `FAILED`, la copia está dañada: vuelve a copiarla.

## 2. Cargar las imágenes

```bash
docker load -i imagenes/tfg-app-2026.10.27-r2.tar
docker load -i imagenes/tfg-qgroundcontrol-5.1.5.tar
docker load -i imagenes/tfg-planner-2026.10.28.tar
docker image inspect --format '{{.Id}} {{.RepoTags}}' tfg/app:2026.10.27-r2 tfg/qgroundcontrol:5.1.5 tfg/planner:2026.10.28
```

Los ID deben coincidir con `image_id` de `VERSIONES.json` (`a86dae08…`, `c6a5c57a…` y `e2c4513e…`). Si solo vas a usar la app y QGC, puedes no cargar el planificador.

## 3. Elegir el directorio de resultados

Elige un directorio tuyo, con ruta absoluta y fuera de esta carpeta. Es el único sitio donde escribe la app (`/work` dentro del contenedor):

```bash
mkdir -p $HOME/tfg-resultados
export TFG_WORK_DIR=$HOME/tfg-resultados TFG_UID=$(id -u) TFG_GID=$(id -g)
```

Repite el `export` en cada terminal nueva. Si `TFG_WORK_DIR` no está definida, el contenedor no arranca (`TFG_WORK_DIR_not_set`).

## 4. Iniciar el recorrido

| Para | Comando |
| --- | --- |
| Menú (opción 5: escenario) | `docker compose -f compose.yaml run --rm app` |
| Consultar el escenario conservado | `docker compose -f compose.yaml run --rm app -m tools.agri_scenario_flow query --out /work/consulta_1` |
| Demo sintética | `docker compose -f compose.yaml run --rm app -m tools.agri_scenario_flow demo --variant complete --out /work/demo_1` |
| Exportar un paquete SITL de ejemplo | `docker compose -f compose.yaml run --rm app -m tools.scenario_package package --template missions/templates/agri_poi_visit_v1.json --site missions/sites/synthetic_orchard_v1.site.json --fleet missions/fleets/agri_demo_fleet.json --target sitl --out /work/paquete_1` |
| Verificar el paquete | `docker compose -f compose.yaml run --rm app -m tools.scenario_package verify /work/paquete_1` |
| Recorrido completo comprobado (el directorio no debe existir) | `scripts/student_walkthrough.sh $HOME/tfg-recorrido-1` |

- Las rutas `missions/...` son las entradas incluidas en la imagen. Sus copias están en `ejemplos/missions/`.
- Para usar una entrada modificada, cópiala a tu directorio de resultados y pásala como `/work/...`. Por ejemplo, `cp -r ejemplos/missions $TFG_WORK_DIR/entradas` y luego `--site /work/entradas/sites/synthetic_orchard_v1.site.json`.
- Cada salida va a un `/work/<nombre nuevo>`. Un directorio que ya existe nunca se sobrescribe: el comando se niega.

**Abrir el paquete en QGC** (sin red, sin vehículos; el paquete se monta de solo lectura):

```bash
mkdir -p $TFG_WORK_DIR/qgc_guardado
QGC_PLAN_DIR=$TFG_WORK_DIR/paquete_1/plans QGC_SAVE_DIR=$TFG_WORK_DIR/qgc_guardado docker compose -f compose.yaml run --rm --name tfg-qgc qgc
```

En QGC, abre el plan desde `/data/plan` y guarda tu copia en `/data/saved`. Después puedes compararlos:

```bash
docker compose -f compose.yaml run --rm app -m tools.qgc_plan_compare /work/paquete_1/plans/drone_01.plan /work/qgc_guardado/drone_01.plan --out /work/comparacion_1
```

Ajusta el segundo nombre de archivo al que hayas usado al guardar.

## 5. Planificación con Hermes (requiere tu cuenta)

```bash
mkdir -p $HOME/tfg-planificacion
export TFG_PLANNING_STORE=$HOME/tfg-planificacion
docker compose -f compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py login
docker compose -f compose.yaml run --rm hermes
docker compose -f compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py status
```

- `login` abre el flujo de tu cuenta de Nous: abre en el navegador la URL que muestre. Tu sesión queda en el volumen Docker `tfg-estudiante_hermes-home` de tu equipo, nunca en esta carpeta.
- Hermes solo tiene dos herramientas: guardar el borrador (`update_mission_draft`) y finalizarlo (`finalize_mission_draft`). No hay simulación ni vehículos.
- Borradores, finalizaciones y misiones quedan en `TFG_PLANNING_STORE`. `status` los vuelve a leer.
- Probado con uid 1000. Con otro uid, el volumen de Hermes puede no ser escribible.

## 6. Localizar los resultados

- **App y QGC:** `$TFG_WORK_DIR/<nombre>` (`consulta_1/`, `demo_1/`, `paquete_1/`, `qgc_guardado/`…). Cada salida trae su informe y su manifiesto.
- **Recorrido completo:** el directorio que le diste, con `walkthrough.tsv` como resumen.
- **Planificación:** `$TFG_PLANNING_STORE/drafts/…`. Tu sesión y tu login de Hermes están en el volumen `tfg-estudiante_hermes-home`.

Los archivos son tuyos (uid/gid de `TFG_UID`/`TFG_GID`). Para entregarlos, comprime ese directorio. No incluyas el volumen de Hermes: contiene tu login.

## 7. Cerrar sin perder nada

- Cada `run --rm` termina solo y borra únicamente el contenedor. Tus directorios de resultados se quedan.
- `Ctrl+C` interrumpe. La demo conserva sus registros y se reanuda con `--resume` y el mismo `--out`.
- Si QGC no responde: `docker stop tfg-qgc`.
- `docker compose -f compose.yaml down` solo afecta al proyecto `tfg-estudiante` y no borra ni tus directorios ni el volumen de Hermes.
- **No uses** `down -v`, `docker volume prune` ni `docker system prune`: borrarían tu login y tus sesiones de Hermes. Para repetir algo, usa un nombre de salida nuevo.

## Límites de esta entrega

- **Probada solo en el equipo donde se preparó.** Allí las imágenes ya existían, así que `docker load` no ha tenido que crearlas desde cero. **La prueba en un segundo ordenador está pendiente.**
- **Hermes no se ha ejecutado con el proveedor real desde esta entrega.** La única ejecución real se hizo con la imagen anterior, `tfg/planner:2026.10.27`.
- **Antes de una distribución pública faltan** la licencia del proyecto, el versionado del conjunto distribuible y la publicación en un registro. Esta entrega **no tiene licencia elegida**: no la publiques ni la redistribuyas. La imagen de QGC incluye QGroundControl y Qt, con sus propias licencias.
