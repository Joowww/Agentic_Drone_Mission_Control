# Entrega parcial `tfg-entrega-estudiantes-2026.10.30`: de las finalizaciones de Hermes a los `.plan` (30/10/2026)

**Resultado:** nueva entrega **parcial**, que incorpora el recorrido finalizaciones de Hermes → paquete → `.plan`. La IA sigue siendo solo Hermes, sin Ollama, y el **simulador sigue sin incluirse**.
- **Verificación:** 12/12 de lo afectado, **solo en este equipo** y desde un directorio aislado, con finalizaciones de prueba **SINTÉTICAS**.
- **Pendiente:** la prueba en un segundo ordenador.
- **Entrega anterior:** `tfg-entrega-estudiantes-2026.10.28-r2` se conserva intacta, con su `SHA256SUMS` verificado.
- **Operaciones no realizadas:** inferencias, login, QGC, simulación, carga en vehículos, movimiento y cambios en archivos o contenedores de Codex.

Ruta: `/home/joelm/TFG/entregas/tfg-entrega-estudiantes-2026.10.30/` (851 MB, 18 archivos más `SHA256SUMS`).

## Qué necesitaba realmente la distribución

Entre `tfg/app:2026.10.28` y el árbol solo diferían 7 archivos, todos de Claude:

| Archivo | ¿Entra? | Motivo |
| --- | --- | --- |
| `planning/mission_artifacts.py` | Sí | Lectura de las finalizaciones de un almacén montado en otra ruta |
| `planning/site_validation.py` | Sí | Validación geométrica de rutas en coordenadas locales |
| `planning/scenario_instance.py` | Sí | `finalized_instance` y la secuencia de agri_demo_001 |
| `tools/scenario_package.py` | Sí | `package-finalized` y bloqueos de despliegue por tarea |
| `tools/agri_scenario_flow.py` | Sí | Acción `f` del submenú de paquetes |
| `missions/sites/synthetic_hermes_rehearsal_v1.site.json` | Sí, añadido | Emplazamiento SINTÉTICO de ensayo |
| `observability/hermes_capture_run.py` | No | Propagación de `HERMES_HOME`: solo la usa el planificador |
| `tools/agri_scenario_distribution.py` | No | Herramienta de inventario de desarrollo |

Las demás imágenes no se reconstruyen:
- **`planner`:** ya escribe el almacén, y la lectura reubicada solo la usa la app.
- **`qgc`:** no le afecta.

No entra ningún archivo de Codex: los módulos de su ámbito que contiene la imagen son iguales a los de la anterior.

## Imagen `tfg/app:2026.10.30` (`app_build/`)

- **ID:** `sha256:a2a49112131c43b3ae19231bc02a690b6eabb640fcedbb446df2d32e5df9afc7`.
- **Contexto congelado:** el `/opt/tfg` de `tfg/app:2026.10.28` (401 archivos, iguales a su `files.sha256`), con los 5 módulos tomados del árbol (`taken_from_tree.sha256`) y el emplazamiento añadido. `diff_vs_2026_10_28.txt` muestra exactamente esos 6 cambios.
- **Contenido verificado:** el `files.sha256` de la imagen es igual a `frozen_context.sha256`; el `pip freeze` es idéntico al de `2026.10.28`.
- **Build:** etapas base y deps en caché, sin descargas (`build.log`).
- **Atestación:** su archivo de `docker save` está íntegro, con el índice igual al ID (`oci_check_app.json`).
- **Repositorio:**
  - `deploy/compose.yaml` usa ahora `tfg/app:2026.10.30`;
  - el inventario `tools/agri_scenario_distribution.py` incluye el emplazamiento de ensayo y las listas `deploy/app/Dockerfile.dockerignore` y `deploy/planner/Dockerfile.dockerignore` están regeneradas (`allowlists_check.txt`: OK). La imagen `planner` no se reconstruyó y no lleva el emplazamiento.

## Cambios respecto a la entrega `-r2`

| | `-r2` | `2026.10.30` |
| --- | --- | --- |
| Imagen `app` | `2026.10.28` | `2026.10.30` (archivo nuevo, `ba1bae30…`) |
| Servicio `app` | Solo `/work` (lectura y escritura) | Además `/planning_store` **de solo lectura**, que es `TFG_PLANNING_STORE`. Sin definir, monta `./almacen_vacio` (`compose_diff_vs_r2_bundle.txt`) |
| `LEEME.md` | §1–§7 | Nueva §6, de las finalizaciones a los `.plan`, con los comandos `package-finalized` y `verify`; límites ampliados (`leeme_diff_vs_r2_bundle.txt`) |
| Ejemplos | 9 JSON | Más `synthetic_hermes_rehearsal_v1.site.json`, extraído de la imagen |
| `qgc`, `planner`, script y resto de ejemplos | — | Mismos bytes, por enlaces duros (`reused_archives_hardlinks.txt`) |
| `VERSIONES.json` | — | `changes_vs_previous` y archivos reutilizados |

**Sin cambios:** `hermes` y `qgc`, ningún servicio de Ollama, ninguna ruta personal, ninguna credencial y ningún socket de Docker en ningún servicio.

## Verificación aislada (`isolated_check/`, `tools/isolated_check_2026_10_30.sh`)

**Montaje de la prueba:**
- **Copia:** `cp -al` de la entrega en un directorio nuevo **fuera del repositorio**.
- **Entorno:** `env -i`, HOME vacío y uid 1000.
- **Proyecto Compose:** `tfg-entrega-2030-prueba`.
- **Finalizaciones sintéticas:** las dos de prueba se crearon llamando **directamente** a `update_mission_draft` y `finalize_mission_draft` desde `tfg/planner:2026.10.28`, con `--network none`, raíz de solo lectura, sin Hermes ni modelo. El almacén lleva `SYNTHETIC_TEST_FINALIZATIONS.txt` y sus misiones se llaman `synthetic_test_sector_a/b`.

| # | Comprobación | Resultado |
| --- | --- | --- |
| 00 | Directorio fuera del repositorio | PASS |
| 01 | `sha256sum -c SHA256SUMS` | PASS |
| 02 | `docker load` del archivo `app` nuevo e ID de las 3 imágenes = `VERSIONES.json` | PASS |
| 03 | Compose: solo `app`, `hermes` y `qgc`; `app` sin red; `/planning_store` de solo lectura y `/work` de escritura; sin `build`, sin socket de Docker, sin rutas del repositorio y sin Ollama | PASS |
| 04 | Finalizaciones sintéticas | PASS: 2 `VALIDATED`, `qgc_export` REFUSED en la finalización (sin AMSL), como es de esperar |
| 05 | Lectura del almacén desde `app` | PASS: ve `drafts/`; escribir en él falla con EROFS (errno 30); no hay `/var/run/docker.sock` |
| 06 | `package-finalized` sobre `synthetic_hermes_rehearsal_v1` | PASS: los dos drones GENERATED, `plans/drone_01.plan` y `drone_02.plan`, COMPLETE_OFFLINE, `deployment_ready=False` y aprobación ABSENT |
| 07 | `verify` | PASS: INTEGRITY_VERIFIED |
| 08 | Entrada alterada (`mission.json` de una copia del almacén) | PASS: `[REFUSED] … does not match its snapshot`, rc 2 y nada escrito |
| 09 | Almacén sin cambios tras las ejecuciones de `app` | PASS (sha256 de todos sus archivos antes y después) |
| 10 | Persistencia: `down` y un contenedor nuevo vuelve a verificar el paquete | PASS |
| 11 | Sin `TFG_PLANNING_STORE`, `app` arranca con `almacen_vacio` | PASS |

`isolated_check/results/` e `isolated_check/planning_store_SYNTHETIC/` conservan el paquete generado y el almacén sintético. No contienen ninguna ruta del repositorio. No quedan contenedores ni volúmenes del proyecto de prueba (`13_leftovers.log`).

**Pruebas afectadas** (`pytest_affected.txt`): `test_agri_scenario_flow.py -k "distribution or app_image"`, 4 passed. El código del recorrido no cambió en esta tanda: lo cubren las pruebas ya registradas en `hermes_finalized_package_two_drones_2026_10_30`. No se repitieron suites generales ni la importación en QGC.

## Limitaciones

- **Simulador:** no incluido. Nada de la entrega carga misiones en SITL o en un vehículo, ni las ejecuta.
- **Pruebas:** solo en este equipo, donde las imágenes ya existían. **La prueba en un segundo ordenador sigue pendiente.**
- **Hermes:** no se ejecutó desde esta entrega. Las finalizaciones de la prueba son sintéticas.
- **Compatibilidad QGC:** no se volvió a comprobar con estos `.plan`. Lo acreditado el 30/10 corresponde a los archivos del paquete `hermes_finalized_package_two_drones_2026_10_30`, no a estos.
- **R1:** la tarea del rover y su dependencia solo se añaden con `--rover` y el binding de H1, y solo resuelven el punto si las misiones son exactamente las de la demo.
- **Antes de una distribución pública:** licencia, versionado y publicación.
