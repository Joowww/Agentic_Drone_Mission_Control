# Imagen de la aplicación: build y prueba de estudiante (27/10/2026)

**Resultado:** imagen construida; recorrido offline de estudiante **15/15 PASS**, sin red y sin proveedor LLM. No se ha publicado en ningún registro.

## Imagen

| Dato | Valor |
| --- | --- |
| Etiqueta | `tfg/app:2026.10.27` |
| ID (digest local del índice OCI, almacén containerd de Docker Desktop) | `sha256:67bc37afc8be27da0ba7e7717b6a788e9cc0d3b39e8873947db5cd768d0d7085`, 344 674 733 bytes, creada 2026-10-27T17:30:02Z (`image_id.txt`, `image_inspect.json`) |
| Receta | `deploy/app/Dockerfile`, con el contexto en la raíz del repositorio y la lista `deploy/app/Dockerfile.dockerignore` generada por `tools.agri_scenario_distribution dockerignore` |
| Base | `ubuntu:24.04@sha256:24737cef…573c`. Python 3.12.3 (`python3`, `python3-venv`) del snapshot `20261024T000000Z`; las fuentes de apt solo apuntan al snapshot y `update` falla ante cualquier índice no descargado |
| Python | Versiones de `requirements.txt` + `requirements-observability.txt` con `-c constraints-verified.txt`: 60 instaladas, todas iguales a las verificadas (`pip-freeze.txt`). Las 59 ruedas tienen sha256 y URL de `files.pythonhosted.org` en `pip-install-report.json` |
| Contenido | 400 archivos en `/opt/tfg`, idénticos al árbol inventariado (`image_files.sha256`, comprobado con `sha256sum -c`). No contiene `tests/`, `.venv`, `missions/generated`, `.pyc`, `.env`, claves ni el socket de Docker. Las rutas `/home/joelm` solo aparecen en 11 registros históricos de H2 (evidencia original), no en el código |
| Ejecución | Usuario 1000, raíz de solo lectura, `/tmp` en tmpfs, sin capacidades, `no-new-privileges`, `network_mode: none`, `init`. Solo `/work` es escribible |
| Exportación local | `docker save`: 80 014 848 bytes, sha256 `a1e0d625…4c34` (`save_sha256.txt`). `docker load` del mismo archivo, en el mismo equipo, devolvió el mismo ID (probado con el build anterior `79d969ba…`). No se ha probado en otro equipo |

## Builds

1. `build_attempt1_503.log`: falló porque snapshot.ubuntu.com respondió 503. Se esperó a que volviera, sin recurrir al archivo vivo.
2. `build_attempt2_superseded.log`: imagen `79d969ba…`, válida, sustituida porque después cambió `tools/agri_scenario_distribution.py`, que va dentro de la imagen. Con ella se hicieron las pruebas de `tests/` y una primera pasada completa del recorrido, también 15/15.
3. `build.log`: la imagen final.

## Recorrido de estudiante (`walkthrough/`)

Directorio nuevo con solo `deploy/compose.yaml` y `deploy/app/student_walkthrough.sh`. Ejecutado con `env -i PATH=… HOME=<vacío>`: sin repositorio, sin `.venv`, sin `missions/generated` y sin montaje del código. Cada paso corre en un contenedor desechable.

| Paso | Qué | Resultado |
| --- | --- | --- |
| a | Consulta H2 (`REAL_HISTORICAL`, copias conservadas) | `AERIAL_COMPLETED_GROUND_PENDING` |
| b | Demo nominal | `SYNTHETIC_COMPLETE` (TEST_DOUBLE; «completo solo como demostración sintética») |
| c1–c3 | Respuesta de admisión perdida y reanudación | `VERIFIED_SYNTHETIC`; `admit_calls=1 jobs=1` |
| d | Validación de `synthetic_orchard_v1` | `VALID` |
| e1–e2 | Plantilla DroneLab | `INCOMPLETE` (rc 1, con lista de datos ausentes); paquete `PARTIAL` con `BLOCKED_MISSING_DATA` y ningún `.plan` |
| f–g | Paquete SITL de dos drones y su verificación | 2 × `GENERATED`; `INTEGRITY_VERIFIED`. `drone_01.plan` = `692c8075…`, el mismo sellado |
| h | Comparación de la primera importación QGC conservada | `NO_SEMANTIC_DIFFERENCES` |
| i1–i3 | Informe del escenario, comparación experimental y hoja de revisión | Generados |
| n | Red | `NO_NETWORK` (la resolución DNS falla; el contenedor no tiene interfaces) |

Los 72 archivos de resultados pertenecen al usuario del anfitrión, que puede editarlos, y no quedó ningún contenedor de `tfg-dist`.

## Otras pruebas (`tests/`, imagen `79d969ba…`)

- **Menú** (`menu.log`): menú principal → opción 5 → consulta → volver → salir. rc 0.
- **Salidas existentes** (`existing*.log`): la demo, el paquete y la comparación se niegan (rc 2, 2 y 3) y no tocan nada.
- **Cancelación** (`cancel_*.log`): SIGINT al contenedor a 1,3, 1,6, 1,9 y 2,1 s.
  - A 1,9 s, a mitad del flujo, el mensaje dice que se conservan los registros y propone `--resume`. El manifiesto queda en `IN_PROGRESS` y, al reanudar, aparece «no se readmite»: `admit_calls=1`.
  - A 1,3 y 1,6 s, durante la carga de módulos, Python muestra un traceback `KeyboardInterrupt` y no escribe nada. Es poco amigable, pero no deja nada a medias.
- **Directorio sin permiso de escritura** (`ro_*.log`): `PermissionError`, rc 1, nada escrito.
- **Almacenamiento lleno** (tmpfs de 64 y 16 KiB; salidas efímeras y no conservadas):
  - El paquete falla con `ENOSPC`, rc 1, y no queda nada en `/work`, porque usa staging.
  - La demo informa `ERROR · OSError: [Errno 28]`, rc 1, y su manifiesto queda en `IN_PROGRESS`, nunca terminado. Deja un `flow_record.tmp` residual.
- **Pruebas de código:** `tests/test_agri_scenario_flow.py`, 43 passed, incluida la nueva prueba del cierre de imports y la lista del contexto.

## Licencias (`python_licenses.tsv`)

- Paquetes Python: MIT, BSD, Apache-2.0 y PSF. certifi y una parte de orjson son MPL-2.0 y se redistribuyen sin modificar. Cada paquete conserva sus archivos de licencia en `site-packages`.
- Paquetes de Ubuntu: conservan `/usr/share/doc/*/copyright` (112).
- **El proyecto no tiene archivo de licencia propio.** Hay que decidirlo (Joel y el tutor) antes de publicar la imagen.
- Para `qgc`, si se publica, habrá que revisar los avisos de QGroundControl y Qt incluidos en el AppImage; no se ha hecho.

## Conjunto distribuible (`distribution_inventory_app_image.json`)

- Conjunto `app_image`: 131 entradas, de las cuales 95 son módulos del cierre de imports, más `main.py`, entradas, evidencias, la receta, los tests y la documentación. Pesan 3,2 MB requeridos y 12,1 MB con las capturas opcionales, que no entran en la imagen.
- Estado en Git: 65 entradas con seguimiento, **56 sin seguimiento** (código nuevo, entradas, `deploy/`, evidencias) y **10 modificadas** respecto a HEAD. Entre las modificadas están `tools/rover_control.py`, `tools/rover_ground_executor.py` y `tools/rover_identity_inventory.py` de Codex.
- Por eso esto **no es un «clon reproducible»** de HEAD: la imagen se ha construido con el conjunto exacto listado, que habría que versionar.
