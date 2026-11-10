# agri_demo_001: cierre funcional y reproducible de la entrada — 26/10/2026

Continúa [la integración](../agri_scenario_flow_2026_10_26/README.md). Todo se hizo offline:
- sin Docker, simulación, operaciones reales, inferencias ni Opik;
- sin instalar nada en el entorno compartido: las instalaciones fueron en venvs aislados del
  directorio temporal de la sesión.

## 1. Tres comprobaciones de reproducibilidad, separadas

| Comprobación | Qué se copió | Entorno | Resultado |
| --- | --- | --- | --- |
| **A. Lo versionado hoy** | `git archive HEAD` | venv aislado, `env -i`, `HOME` vacío | **Falla**: `No module named tools.agri_scenario_flow`. Tampoco existen las copias H2 ni la referencia H0. Un clon de HEAD **no** reproduce el flujo |
| **B. HEAD + conjunto propuesto** | `git archive HEAD` más las entradas de [`distribution_inventory.json`](distribution_inventory.json): las 21 obligatorias, con y sin la opcional | venv aislado con `requirements-dev.txt` + `constraints-verified.txt`, `env -i`, `HOME` vacío, sin `missions/generated` | **Pasa en los dos casos**: `query` rc 0, con un informe idéntico byte a byte al del árbol de trabajo; `demo` rc 0; `agri_scenario_distribution check` OK dentro de la copia. `tests/test_agri_scenario_flow.py`: 42 pasan con la captura `/3`; sin ella, 41 pasan y 1 se salta con el motivo «optional evidence» |
| **C. Dependencias declaradas** | — | venv aislado nuevo: `pip install -r requirements-dev.txt -c constraints-verified.txt` | **Pasa**: la resolución es idéntica a la del primer venv aislado (`pip freeze` igual). Con ese venv pasan 331 tests de los suites del escenario, coordinador, recorrido conjunto y lector pasivo |

**Límites.**
- B usa la versión del árbol de trabajo de dos archivos de Codex con cambios sin versionar
  (`tools/rover_ground_executor.py` y `tools/rover_control.py`). Con sus versiones de HEAD:
  - el informe cambia, porque aparece el bloqueo `executor_accepts_navigation_request`;
  - `rover_control` de HEAD es incompatible y 20 tests fallan.
- Los demás archivos modificados del árbol no son necesarios: lo comprobé quitándolos uno a uno.
- No se ha verificado la suite completa con el venv aislado.
- **Plataforma verificada:** Python 3.12.3 en Linux x86_64 (WSL2). No se han probado otras. Eso no
  las hace incompatibles: quedan sin verificar.

## 2. Dependencias

Los imports del recorrido y de la demostración se auditaron cargando los módulos reales y
comparándolos con los imports directos del código del proyecto.

| Archivo | Contenido |
| --- | --- |
| `requirements.txt` (modificado) | Dependencias **directas** con rangos y la versión verificada en comentario, como ya hacía `requirements-observability.txt`. Se añaden `pydantic>=2,<3` (modelos y validación) y `PyYAML>=6,<7` (`observability/hermes_capture_run.py`, usado por el flujo para verificar manifiestos) |
| `constraints-verified.txt` (nuevo, **incluido en el inventario mínimo**) | Versiones **exactas** de la instalación aislada que superó las pruebas citadas en su cabecera, con Python 3.12.3 en Linux x86_64. Son las verificadas, no las únicas compatibles. Generado con `pip freeze` del venv aislado, **no** del entorno personal. Son restricciones (`-c`): no piden paquetes |
| `requirements-dev.txt` (sin cambios) | Desarrollo: `pytest` y `pytest-cov`, más los requisitos de observabilidad |

En la instalación aislada se resolvieron versiones transitivas **más recientes** que las del
entorno compartido; por ejemplo `langchain-core` 1.7.0 frente a 1.6.5. Las verificadas son las del
archivo de restricciones. No se atribuye compatibilidad a otras.

## 3. Conjunto mínimo distribuible

[`distribution_inventory.json`](distribution_inventory.json) lo genera
`tools/agri_scenario_distribution.py` y se comprueba con `check`.
- **Archivos:** ruta, tamaño, SHA-256, finalidad y estado en Git.
- **Directorios de evidencia:** se listan por **su propio manifiesto**, que el `check` vuelve a
  verificar:
  - `SHA256SUMS`;
  - `manifest.json` de copias;
  - `manifest.json` de ensayo.

| Grupo | Entradas | Estado en Git hoy |
| --- | --- | --- |
| Entrada y código del flujo | `main.py`, `tools/agri_scenario_flow.py`, `graph/agri_scenario_graph.py`, `reporting/agri_scenario_summary.py`, `tools/agri_ground_coordinator.py`, `tools/agri_ground_demo.py`, `observability/hermes_capture_run.py`, `observability/mission_query_cases.py`, `tools/rover_passive_journal.py`, `tools/agri_scenario_distribution.py` | `main.py` modificado; el resto sin versionar |
| Código de Codex con cambios sin versionar | `tools/rover_ground_executor.py`, `tools/rover_control.py` | Modificados (los versiona Codex o Joel) |
| Pruebas | `tests/test_agri_scenario_flow.py` | Sin versionar |
| Dependencias | `requirements.txt`, `constraints-verified.txt` | Modificado y nuevo |
| Referencia H0 | `missions/examples/agri_demo_001_sector_{a,b}.json` | Sin versionar |
| Evidencias | Copias H2 (`agri_demo_h2_2026_10_24`), H1, H3b, vista H2 guardada y captura `/3` de Codex | Sin versionar |

> **Actualización (27/10/2026).** El inventario añade `reporting/rover_identity_facts.py` (obligatoria) y
> la sesión de identidad de Codex `1cb9d86a` (opcional, 2,6 MB): **22 obligatorias (0,97 MB) y 2
> opcionales**. La comprobación B se repitió con este inventario y pasa: informe idéntico, demo rc 0,
> 41 tests pasan y 1 se salta. Sin la sesión, los hechos de identidad salen `NOT_AVAILABLE`. Las cifras
> de abajo son las del 26/10.

**Tamaño:** 0,96 MB obligatorios (21 entradas) y 6,2 MB opcionales: la captura `/3` de Codex,
marcada `optional_evidence`. Sin ella:
- la consulta y la demostración funcionan igual, con el informe idéntico;
- `query --capture-*` informa los hechos medidos como `NOT_AVAILABLE`, sin inventar datos y sin
  cambiar los bloqueos de R1;
- el `check` acepta su ausencia.

La captura original de Codex no se ha movido ni modificado.

Para versionar hay una [lista de revisión](versioning_review.md), que separa el inventario mínimo
de ejecución del conjunto de mantenimiento y pruebas, e identifica los cambios de Codex pendientes.

**No hace falta** (comprobado en B con `HOME` vacío y `env -i`):
- `missions/generated`;
- sesiones privadas de Hermes;
- credenciales;
- temporales del contenedor;
- `.venv`.

El `check` también busca patrones de credenciales en el conjunto y no encontró ninguno.

## 4. Estados: dimensiones separadas

Sin registro R1, el escenario conserva el estado histórico `AERIAL_COMPLETED_GROUND_PENDING`, igual
que la vista guardada de H2. Antes de este cierre el flujo mostraba
`AERIAL_COMPLETED_GROUND_NOT_REQUESTED`. `r1_dimensions` da las dimensiones por separado:

| Recorrido | Flujo | Dependencia | Elegibilidad (preparación) | Autorización | Solicitud | Ejecución | Escenario |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `real_query_h2` (REAL) | `COMPLETED_FLOW` | MET | NOT_ELIGIBLE | ABSENT | NOT_REQUESTED_VIA_THIS_COORDINATOR | NOT_STARTED | `AERIAL_COMPLETED_GROUND_PENDING` |
| `complete` | `COMPLETED_FLOW` | MET | ELIGIBLE | DECLARED_NOT_AUTHENTICATED | VERIFIED_SYNTHETIC | FINISHED / VERIFIED | `SYNTHETIC_COMPLETE` |
| `lost_admission_response` | `COMPLETED_FLOW` | MET | ELIGIBLE | DECLARED_NOT_AUTHENTICATED | VERIFIED_SYNTHETIC | FINISHED / VERIFIED | `SYNTHETIC_COMPLETE` |
| `authorization_absent` | `COMPLETED_FLOW` | MET | ELIGIBLE | ABSENT | NOT_REQUESTED_VIA_THIS_COORDINATOR | NOT_STARTED | `AERIAL_COMPLETED_GROUND_PENDING` |
| `transform_absent` | `COMPLETED_FLOW` | MET | NOT_ELIGIBLE | ABSENT | NOT_REQUESTED_VIA_THIS_COORDINATOR | NOT_STARTED | `AERIAL_COMPLETED_GROUND_PENDING` |
| `executor_refuses` | `COMPLETED_FLOW` | MET | ELIGIBLE | DECLARED_NOT_AUTHENTICATED | REJECTED_BY_EXECUTOR | NOT_STARTED | `…_REJECTED_BY_EXECUTOR` |
| `insufficient_dwell` | `COMPLETED_FLOW` | MET | ELIGIBLE | DECLARED_NOT_AUTHENTICATED | FAILED | FINISHED / FAILED | `AERIAL_COMPLETED_GROUND_FAILED` |
| `stop_uncertain` | `COMPLETED_FLOW` | MET | ELIGIBLE | DECLARED_NOT_AUTHENTICATED | UNCERTAIN | FINISHED / UNCERTAIN | `AERIAL_COMPLETED_GROUND_UNCERTAIN` |
| `first_drone_failed` | `COMPLETED_FLOW` | NOT_MET | NOT_ELIGIBLE | ABSENT | NOT_REQUESTED_VIA_THIS_COORDINATOR | NOT_STARTED | `FAILED` |
| `poi_not_reached` | `COMPLETED_FLOW` | NOT_MET | NOT_ELIGIBLE | ABSENT | NOT_REQUESTED_VIA_THIS_COORDINATOR | NOT_STARTED | `AERIAL_COMPLETED_R1_DEPENDENCY_NOT_MET` |
| `sequence_pending` | `COMPLETED_FLOW` | UNKNOWN | NOT_ELIGIBLE | ABSENT | NOT_REQUESTED_VIA_THIS_COORDINATOR | NOT_STARTED | `UNKNOWN` |
| `invalid_mission` / `artifact_modified` | `REJECTED` en `bind_and_validate` | — | — | — | — | — | — |

En la consulta real, la elegibilidad de la vista histórica sigue siendo `BLOCKED_PENDING` con sus
cuatro barreras registradas. La de la preparación actual es `NOT_ELIGIBLE` con dos bloqueos. Las
dos aparecen juntas y ninguna sustituye a la otra.

La línea `R1 · …` de cada `*.terminal.txt` y la sección «Dimensiones de R1» de cada
`scenario_report.md` muestran estos valores.

## 5. Qué demuestra cada recorrido de R1

| Recorrido | Componentes reales | Sustituido | Demuestra | No demuestra |
| --- | --- | --- | --- | --- |
| **Demostración** (`agri_scenario_flow demo`) | Flujo, validación, vinculación, vista, preparación, coordinador y aceptación | El ejecutor entero (`TEST_DOUBLE`, que genera las muestras) | Etapas, idempotencia, recuperación de respuestas perdidas, no reintento, estados y dimensiones | Gates del ejecutor real, worker, controlador, cierre y procedencia frente a registros reales |
| **Recorrido conjunto** (`tests/test_agri_ground_joint.py`) | Coordinador, adaptador, `admit_ground_trial`, `start_ground_trial`, worker, `Ros2RoverAdapter`, `RoverControlCore.navigate`, `lookup`/`query` y aceptación | Solo la sesión física, con una cinemática que integra las órdenes del controlador | El contrato coordinador ↔ ejecutor real y el cierre autorizado | Comportamiento físico. Solo existe dentro del fixture aislado de Codex |

**No son equivalentes.** El recorrido conjunto no puede salir de los tests sin activar la política
operativa: `admit_ground_trial` comprueba primero `OPERATIONAL_ROVER_ENABLED`, una variable global
del módulo. No lo he hecho, ni con variables de entorno ni con monkeypatch.

**Propuesta mínima para Codex, no implementada.** Una frontera de simulación construida solo desde
código, por ejemplo `rover_ground_executor.SyntheticSandbox(root)`, pasada a admisión, arranque y
consulta. Debería:
- usar sus propios `RUN_ROOT` y `LOCK_ROOT` bajo `root`, nunca los reales;
- no leer ni cambiar la política global; dentro de la sandbox la política la sustituye la propia
  sandbox;
- aceptar solo adaptadores cuya sesión declare `synthetic_model=True` y rechazar cualquier
  transporte real;
- etiquetar todo resultado como `SYNTHETIC_TEST_DOUBLE`, igual que hoy;
- no ofrecer bandera, variable de entorno ni argumento de CLI que la active fuera del código que la
  construye.

Con eso, `agri_scenario_flow demo` podría usar el ejecutor real con transporte sintético.

## 6. Uso y recuperación desde la entrada pública

Cada caso es una prueba de `tests/test_agri_scenario_flow.py` que llama a `main()` o al menú:

| Caso | Comportamiento |
| --- | --- |
| Directorio de salida existente | `query` y `demo` devuelven rc 2 sin escribir nada. `--resume` sobre un directorio con archivos de otro origen da rc 2 (`NO_OUTPUTS_MANIFEST`) |
| Ejecución interrumpida (Ctrl+C) | rc 130 y el mensaje para reanudar. `outputs_manifest.json` queda `IN_PROGRESS`; `--resume` termina con **una** admisión y lo indica en el resumen |
| `--resume` con otra identidad | rc 2 `IDENTITY_MISMATCH`, sin ninguna llamada al ejecutor ([ejemplo](synthetic_demo/complete.resume_other_identity.terminal.txt)) |
| Archivos derivados alterados (`flow_record.json`, el informe, el estado del doble o el registro R1) | rc 2 `DERIVED_FILES_ALTERED` |
| Fallo al escribir el informe | Flujo `ERROR` con `REPORT_NOT_WRITTEN`, rc 3, y el registro lo refleja. Nunca `COMPLETED_FLOW` |
| Informe anterior distinto | Se conserva como `scenario_report.previous-<sha12>.md`; no se sobrescribe en silencio |
| Consulta sin registros locales | Sin almacén R1: `NOT_REQUESTED_VIA_THIS_COORDINATOR`. Con `--source local` y sin `missions/generated`: `BLOCKED` |
| Cancelación del menú | `exit`, Ctrl+C o Ctrl+D en cualquier pregunta, o Ctrl+C durante una ejecución: se cierra sin reintentar nada |

`--resume` nunca es un permiso para repetir admisiones. Sobre un flujo terminado comprueba la
identidad y los hashes de todas las salidas. Después, la idempotencia del coordinador decide:
`EXISTING`, una admisión ([ejemplo](synthetic_demo/complete.resume.terminal.txt)).

Los `*.terminal.txt` se guardan **fuera** de cada directorio de salida: dentro alterarían las salidas
registradas y `--resume` las rechazaría.

## 7. Reproducción

> **Requisito.** Estos comandos necesitan **HEAD más los cambios del inventario**: código nuevo,
> cambios de Codex en el ejecutor y el controlador, dependencias, referencia H0 y evidencias.
> Mientras no estén versionados, **un clon de HEAD no basta**: falla con
> `No module named tools.agri_scenario_flow` (comprobación A). Hoy solo funcionan en este árbol de
> trabajo o en una copia construida como en la comprobación B.

Desde un árbol que contenga ese conjunto, con dependencias declaradas en un venv aislado propio:

```bash
python3 -m venv /tmp/agri-venv
/tmp/agri-venv/bin/pip install -r requirements-dev.txt -c constraints-verified.txt
/tmp/agri-venv/bin/python -m tools.agri_scenario_flow query --out /tmp/agri-out/query
/tmp/agri-venv/bin/python -m tools.agri_scenario_flow demo --variant complete --out /tmp/agri-out/demo
/tmp/agri-venv/bin/python -m tools.agri_scenario_flow demo --variant complete --out /tmp/agri-out/demo --resume
/tmp/agri-venv/bin/python -m tools.agri_scenario_distribution check evaluation/observability/agri_scenario_flow_closure_2026_10_26/distribution_inventory.json
/tmp/agri-venv/bin/python -m pytest -q tests/test_agri_scenario_flow.py
```

La comprobación B construye esa copia a partir de HEAD y del inventario. Debe ejecutarse desde este
árbol de trabajo, que es donde existen hoy los archivos no versionados:

```bash
mkdir /tmp/agri-copy
git archive HEAD | tar -x -C /tmp/agri-copy
/tmp/agri-venv/bin/python -c "import json; print('\n'.join(e['path'] for e in json.load(open('evaluation/observability/agri_scenario_flow_closure_2026_10_26/distribution_inventory.json'))['entries']))" > /tmp/agri-copy.list
tar -cf - -T /tmp/agri-copy.list | tar -x -C /tmp/agri-copy
mkdir /tmp/agri-home
cd /tmp/agri-copy && env -i HOME=/tmp/agri-home PATH=/usr/bin:/bin /tmp/agri-venv/bin/python -m tools.agri_scenario_flow query --out /tmp/agri-out/copy-query
```

## Pendiente

- **Joel:**
  - revisar y versionar según la [lista de revisión](versioning_review.md); incluye los cambios de
    Codex en el ejecutor y el controlador, que conviene que Codex confirme antes;
  - decidir si la captura `/3` (6,2 MB) entra en el repositorio. Funciona también sin ella.
- **Codex:** la frontera de simulación de la sección 5, para que la demostración pueda usar el
  ejecutor real sin la política operativa.
- **Sin verificar:** la suite completa con el venv aislado, y otras plataformas o versiones de Python.
