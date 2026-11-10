# Entrega local para estudiantes `tfg-entrega-estudiantes-2026.10.28`: preparación y verificación aislada (28/10/2026)

**Resultado:** entrega preparada con las imágenes ya construidas, sin construir ninguna nueva y sin publicar nada. Verificada **en este mismo equipo**, desde un directorio aislado: 13/13 PASS. **La prueba en un segundo ordenador sigue pendiente.** No hubo inferencias, inicio de sesión real, Opik, simulación ni vehículos, y no se abrió QGC.

## La entrega

Ruta: `/home/joelm/TFG/entregas/tfg-entrega-estudiantes-2026.10.28/`, **fuera del repositorio**. Ocupa 851 MB en 16 archivos más su `SHA256SUMS`:

| Archivo | Contenido |
| --- | --- |
| `imagenes/tfg-app-2026.10.27-r2.tar` (80 MB) | `docker save` de `tfg/app:2026.10.27-r2`, ID `a86dae08…` |
| `imagenes/tfg-qgroundcontrol-5.1.5.tar` (329 MB) | `docker save` de `tfg/qgroundcontrol:5.1.5`, ID `c6a5c57a…` |
| `imagenes/tfg-planner-2026.10.28.tar` (483 MB) | `docker save` de `tfg/planner:2026.10.28`, ID `e2c4513e…` |
| `compose.yaml` | Compose de distribución (abajo) |
| `scripts/student_walkthrough.sh` | Copia **sin cambios** de `deploy/app/student_walkthrough.sh` |
| `ejemplos/missions/…` (9 JSON) | Extraídos con `docker create`/`docker cp` de `/opt/tfg/missions` de la imagen `app`, sin arrancarla. Iguales a su `files.sha256` y al árbol (`inputs_vs_app_image.txt`) |
| `LEEME.md` | Guía breve: hashes, carga, recorrido, resultados, cierre y límites |
| `VERSIONES.json` | Etiqueta, ID, manifiesto de plataforma, config, etiquetas OCI, tamaño y sha256 de cada archivo; qué no se incluye; pendientes |
| `SHA256SUMS` | sha256 de todos los archivos anteriores (`sha256sum -c`) |

Copias de los archivos pequeños en `bundle_small_files/`; `bundle_SHA256SUMS.txt` es el `SHA256SUMS` de la entrega.

**No incluye** HOME, credenciales, sesiones, `work/`, cachés, código fuente del repositorio, la imagen o el modelo de Ollama, ni el contenedor mutable del simulador.

### Exportación de las imágenes (`oci_archive_check.json`)

- **Espacio comprobado antes:** 920 GB libres (`bundle_location_and_space.txt`).
- **Capas ya comprimidas:** el almacén de imágenes de Docker es containerd, así que `docker save` exporta las capas comprimidas. Por eso no se añadió otra compresión.
- **Un archivo por imagen:** se podría no cargar el planificador. Las tres solo comparten la capa base de Ubuntu.
- **Primer intento descartado:** fue con `--platform linux/amd64`. El archivo resultante contenía el manifiesto de plataforma, pero no el índice, así que la imagen cargada habría tenido otro ID (`d2f4db45…` en lugar de `a86dae08…`).
- **Exportación definitiva:** se repitió sin `--platform`. Cada archivo lleva el índice, cuyo digest es el ID documentado, con el manifiesto amd64 y la atestación de procedencia de BuildKit (SLSA, modo mínimo, unos 1,8 KB).
- **Atestaciones revisadas:** no contienen rutas ni datos personales.
  - `app` y `qgc` registran el remoto de GitHub y el commit HEAD `83a147d`. Ese commit no basta para reproducirlas, porque se construyeron con archivos sin versionar (`VERSIONES.json` → `provenance_caveat`).
  - `planner` no registra VCS, porque se construyó desde el contexto congelado.
- **Comprobación sin daemon** (`tools/oci_tar_check.py`): el sha256 de cada blob coincide con su nombre, y todo lo alcanzable desde `index.json` está presente. Resultado OK en los tres.

### Compose de distribución (`compose_diff_vs_deploy.txt`)

Son los mismos servicios, imágenes y restricciones que `deploy/compose.yaml` para las imágenes entregadas: sin red en `app` y `qgc`, raíz de solo lectura, `cap_drop: ALL`, `no-new-privileges` y el usuario `TFG_UID`/`TFG_GID`. Se quitan:
- las secciones `build`;
- el perfil `dev`, que monta las fuentes;
- el perfil `planning-test`, con los dobles.

Las diferencias necesarias para funcionar sin el repositorio:
- **Directorios del estudiante.** `TFG_WORK_DIR`, `QGC_PLAN_DIR`, `QGC_SAVE_DIR` y `TFG_PLANNING_STORE` los elige el estudiante. Sin valor, apuntan a un `*_not_set` inexistente y el servicio no arranca, el mismo mecanismo que ya usaba `QGC_SAVE_DIR`. Antes, `QGC_PLAN_DIR` apuntaba por defecto al paquete sellado del repositorio.
- **Proyecto `tfg-estudiante`, no `tfg-dist`.** Así su volumen `hermes-home` es uno nuevo de quien use la entrega, y nunca el de `tfg-dist`, que en este equipo contiene el login de Joel.

## Verificación aislada en este equipo (`isolated_check/`, `tools/isolated_check.sh`)

**Montaje de la prueba:**
- **Copia:** se hizo con `cp -al` (enlaces duros, sin duplicar bytes) en un directorio nuevo del scratchpad, **fuera del repositorio**.
- **Entorno:** se ejecutó con `env -i`, HOME vacío, `PATH=/usr/local/bin:/usr/bin:/bin` y uid 1000.
- **Directorios del estudiante:** los resultados y el almacén de planificación eran directorios nuevos de la prueba.
- **Sin acceso al repositorio:** ningún bind apunta a él ni a HOME (`04_compose_paths.log`), y los resultados no contienen ninguna ruta del repositorio.

| # | Comprobación | Resultado |
| --- | --- | --- |
| 00 | El directorio de trabajo está fuera del repositorio | PASS |
| 01 | `sha256sum -c SHA256SUMS` | PASS, 16 OK |
| 02 | `docker load` de los tres archivos | PASS: «Loaded image» ×3 |
| 03 | ID tras la carga = `image_id` de `VERSIONES.json` | PASS ×3 (`a86dae08…`, `c6a5c57a…`, `e2c4513e…`) |
| 04 | `docker compose config` con los perfiles `app`, `qgc` y `planning` | PASS: proyecto `tfg-estudiante`, sin `build`, binds solo a los directorios de la prueba, `/tmp/.X11-unix` y los `*_not_set` |
| 05 | Consulta offline del escenario conservado | PASS: `AERIAL_COMPLETED_GROUND_PENDING` |
| 06 | Paquete SITL de ejemplo con las **entradas extraídas**, copiadas al directorio de resultados (`/work/entradas/...`) | PASS: `A2 drone_02: GENERATED` |
| 07 | `scenario_package verify` | PASS: `INTEGRITY_VERIFIED` |
| 08 | El Compose de `qgc` montaría `paquete_1/plans` en `/data/plan` de solo lectura, y los `.plan` son legibles | PASS. **No se abrió QGC** |
| 09 | `status` del planificador sobre el volumen nuevo | PASS: `auth.json` ABSENT, 0 borradores (rc 1 por `config.yaml absent`, lo esperado en un home sin estrenar) |
| 10 | Escritura en el almacén de planificación llamando **directamente** a `update_mission_draft` y `finalize_mission_draft` con los datos del sector A de H1, en la red interna `local-llm`, **sin Hermes ni modelo** | PASS: borrador COMPLETE; finalización VALIDATED, FEASIBLE/APPROVED, `qgc_export` REFUSED sin AMSL |
| 11 | Un contenedor nuevo relee el almacén | PASS: 1 borrador con su finalización completa |
| 14 | `down` del proyecto `tfg-estudiante` conserva los resultados | PASS |

### Qué acredita y qué no

- **Carga de imágenes.** `docker load` se probó en el mismo equipo, donde las imágenes ya existían y no se borraron. La comprobación sin daemon acredita que cada archivo está completo e íntegro. **No acredita** una carga desde cero en otro ordenador, que sigue pendiente.
- **QGC.** El `drone_01.plan` generado en la prueba es **idéntico byte a byte** (`692c8075…`) al `original.plan` que Joel importó en QGC el 27/10 (`qgc_first_import_2026_10_27`, NO_SEMANTIC_DIFFERENCES); ver `plan_identity.txt`. `drone_02.plan` es igual al del paquete V2 sellado, pero ese archivo no se importó en QGC. **QGC no se abrió en esta prueba.**
- **Planificación.** Se acredita que el almacén elegido por el estudiante recibe y conserva borradores y finalizaciones, y que el volumen de Hermes de la entrega empieza sin login. **No se ejecutó Hermes**, ni con el proveedor real ni con el doble. La única ejecución real sigue siendo la del 28/10 con la imagen `2026.10.27` (`planning_container_real_2026_10_28_r2`).
- **Recorrido completo.** No se repitió `student_walkthrough.sh`, ni ninguna suite general.

### Restos en Docker tras la prueba (`docker_leftovers_after_check.txt`)

- **Queda el volumen `tfg-estudiante_hermes-home`.** Lo creó la prueba y solo contiene el home vacío de la imagen, sin `config.yaml` ni `auth.json`.
- **No quedan contenedores ni redes:** todos los contenedores fueron `--rm` y `down` eliminó la red.
- **No se tocaron** las imágenes originales, los volúmenes de `tfg-dist` ni los contenedores de Codex.

## Archivos de esta evidencia

- `isolated_check/logs/`: un log por paso y `summary.tsv`.
  - `12_result_files.sha256` lista los hashes de todos los resultados de la prueba, incluido `paquete_1/SHA256SUMS`, que `SHA256SUMS` de esta evidencia excluye por nombre (`write_manifest`). Ese paquete se comprueba además con su propio `verify`.
- `isolated_check/results/` e `isolated_check/planning_store/`: los resultados de la prueba (consulta, entradas copiadas, paquete, borrador y finalización).
- `tools/`: los dos scripts usados.

## Pendiente antes de una distribución pública

1. **Licencia del proyecto**, sin elegir. La imagen de QGC incluye QGroundControl y Qt, con sus avisos de licencia.
2. **Versionado** del conjunto distribuible, en gran parte sin seguimiento en Git.
3. **Prueba en un segundo ordenador**: `sha256sum -c`, `docker load` desde cero y el recorrido de `LEEME.md`.
4. **Publicación** en un registro. No se ha publicado nada.
