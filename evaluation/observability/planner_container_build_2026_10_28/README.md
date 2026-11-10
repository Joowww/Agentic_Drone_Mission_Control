# Imagen de planificación `tfg/planner:2026.10.28`: correcciones incorporadas, comprobada con dobles (28/10/2026)

**Resultado:** imagen nueva construida con las dos correcciones (propagación de `--hermes-home` al proceso hijo y `login` en el home de ensayo) y **24/24 comprobaciones con DOBLES**. No hubo ninguna inferencia real, inicio de sesión real ni uso de Opik. La imagen anterior, `tfg/planner:2026.10.27` (`651cc6e2…`), y sus evidencias se conservan. **La ejecución real del 28/10 (`planning_container_real_2026_10_28_r2`) acredita solo aquella imagen, no esta.**

| Dato | Valor |
| --- | --- |
| Imagen | `tfg/planner:2026.10.28`, `sha256:e2c4513e4ca6982c5d7c88811d4df647d6d7c35055f284104f3aa0f0077e2112` (`image_id.txt`, `image_inspect.json`) |
| Contexto de build | **Congelado** al empezar (`frozen_at_utc.txt`) en una copia aparte. Contiene los archivos de la lista `planner_image` del árbol, salvo los dos módulos de Codex, extraídos de la imagen anterior. `frozen_context.sha256` es igual a `new_image_files.sha256` (432 archivos) |
| Diferencias con `2026.10.27` | Exactamente 3 archivos (`diff_vs_2026_10_27.txt`): `deploy/planner/hermes_home.py` (`login`), `observability/hermes_capture_run.py` (`HERMES_HOME` del hijo) y `tools/agri_scenario_distribution.py` (deduplicación) |
| Módulos de Codex | `tools/rover_xrce_trace/historical_disposition.py` (`660fbb60…`) y `session_precheck.py` (`36686b1a…`), **iguales que en la imagen anterior**. Los cambios posteriores de Codex en el árbol (`db882cc5…`, `a3e47661…`) no se incorporan |
| Hermes y dependencias | La misma fuente congelada (`deploy/planner/vendor/hermes-agent-d923a5eb.tar`, `5b668df1…`) y las mismas dependencias fijadas. Etapas `deps` y `hermes` en caché; los `ADD` de uv y CPython se validaron por checksum sin descargar (`build.log`). El checkout de Hermes es idéntico al de la imagen anterior |
| Compose | `deploy/compose.yaml` usa ahora `tfg/planner:2026.10.28`. `-e HERMES_HOME=…` sigue disponible para elegir el home |

## Comprobaciones (`checks/`, `deploy/planner/planning_checks.sh`)

Las 19 anteriores siguen en PASS. Las nuevas, del 20 al 24, son las que pedían las correcciones:

| # | Comprobación | Resultado |
| --- | --- | --- |
| 20 | El hijo usa el home pedido aunque el contenedor tenga otro `HERMES_HOME`: se ejecutó con `-e HERMES_HOME=/hermes/planning` (vacío y de solo lectura) y `--hermes-home /work/trial_double` | PASS. Retorno 0, configuración restaurada, 4 peticiones al doble y estado de Hermes en `/work/trial_double` (`20_21_analysis.txt`) |
| 21 | El ejecutor ofrece solo las 2 herramientas de planificación | PASS |
| 22 | Persistencia leída desde otro contenedor; `qgc_export` REFUSED sin AMSL y ningún `.plan` | PASS |
| 23 | Revisión del ejecutor | PASS: `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS` (`runner_review/`) |
| 24 | `hermes_home.py login` en un home de ensayo sin filtro, contra un portal **falso** (`HERMES_PORTAL_BASE_URL=http://fake-provider:8000`) | PASS. No se niega; inicia el flujo de Nous (`POST /api/oauth/device/code` al doble). Hermes falla allí porque el doble no implementa ese endpoint, y no se guarda ninguna credencial |

Todas usan el proveedor falso (`deploy/planner/doubles/fake_provider.py`) en una red interna sin salida.

## Pruebas (`pytest_affected.txt`)

- `test_planning_profile.py` y `test_hermes_capture_run.py`: 137 passed.
- `test_agri_scenario_flow.py -k "distribution or app_image"`: 4 passed.

No se repitieron la ejecución real, el recorrido offline ni la suite general.

## Inventario

`distribution_inventory_planner_image.json` (conjunto `planner_image`) describe el **árbol**. En él, los dos módulos de Codex figuran con sus versiones nuevas, mientras que la imagen lleva las anteriores. El contenido exacto de la imagen está en `frozen_context.sha256` y `new_image_files.sha256`.
