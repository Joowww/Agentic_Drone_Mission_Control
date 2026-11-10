# Escenario agri_demo_001 integrado en la orquestación — 26/10/2026

Evidencia de la entrada `tools/agri_scenario_flow.py` (grafo `graph/agri_scenario_graph.py`), generada
offline:
- sin Docker, simulación ni procesos;
- sin admisiones operativas ni inferencias;
- sin Opik.

Hay dos orígenes, que nunca se combinan:

| Directorio | Origen | Qué contiene |
| --- | --- | --- |
| [`real_query_h2/`](real_query_h2/) | **REAL HISTÓRICO** | Consulta de solo lectura sobre las copias conservadas de H1/H2, verificadas por manifiesto, con los hechos medidos de la recepción `/3` real |
| [`synthetic_demo/<variante>/`](synthetic_demo/) | **SINTÉTICO** | Demostración con identidad propia (secuencia reidentificada y claves `synthetic-r1-*`), almacenamiento propio y ejecutor R1 `TEST_DOUBLE` |

Cada directorio guarda:
- `terminal.txt`: la salida por etapas: qué trabaja, qué espera, el resultado y el motivo;
- `flow_record.json`: identificadores, hashes y transiciones;
- `scenario_report.md`: el informe determinista, que empieza con su origen.

En la demostración están además `r1/`, el registro del coordinador, y
`executor_test_double.json`, el estado del doble.

## Resultados

| Recorrido | Origen | Flujo | Escenario | R1 | Admisiones | Motivo |
| --- | --- | --- | --- | --- | --- | --- |
| `real_query_h2` | REAL | `COMPLETED_FLOW` | `AERIAL_COMPLETED_GROUND_NOT_REQUESTED` | `NOT_REQUESTED` | 0 | sin registro R1; una solicitud necesita autorización y la entrada del coordinador con el adaptador real |
| `complete` | SINT. | `COMPLETED_FLOW` | `SYNTHETIC_COMPLETE` | `VERIFIED_SYNTHETIC` | 1 | — |
| `lost_admission_response` | SINT. | `COMPLETED_FLOW` | `SYNTHETIC_COMPLETE` | `VERIFIED_SYNTHETIC` | 1 | respuesta de admisión perdida, recuperada con `lookup` sin readmitir |
| `first_drone_failed` | SINT. | `COMPLETED_FLOW` | `FAILED` | `NOT_REQUESTED` | 0 | `DEPENDENCY_NOT_MET` |
| `poi_not_reached` | SINT. | `COMPLETED_FLOW` | `AERIAL_COMPLETED_R1_DEPENDENCY_NOT_MET` | `NOT_REQUESTED` | 0 | `DEPENDENCY_NOT_MET` |
| `sequence_pending` | SINT. | `COMPLETED_FLOW` | `UNKNOWN` | `NOT_REQUESTED` | 0 | `DEPENDENCY_UNKNOWN` |
| `transform_absent` | SINT. | `COMPLETED_FLOW` | `AERIAL_COMPLETED_GROUND_NOT_REQUESTED` | `NOT_REQUESTED` | 0 | `NO_CANDIDATE` (falta `frame_transform`) |
| `authorization_absent` | SINT. | `COMPLETED_FLOW` | `AERIAL_COMPLETED_GROUND_NOT_REQUESTED` | `NOT_REQUESTED` | 0 | dependencia `MET` pero `AUTHORIZATION_ABSENT_OR_MALFORMED` |
| `executor_refuses` | SINT. | `COMPLETED_FLOW` | `…_REJECTED_BY_EXECUTOR` | `REJECTED_BY_EXECUTOR` | 1 | rechazo del ejecutor |
| `insufficient_dwell` | SINT. | `COMPLETED_FLOW` | `AERIAL_COMPLETED_GROUND_FAILED` | `FAILED` | 1 | `PASSED_THROUGH_NO_DWELL` |
| `stop_uncertain` | SINT. | `COMPLETED_FLOW` | `AERIAL_COMPLETED_GROUND_UNCERTAIN` | `UNCERTAIN` | 1 | `STOP_UNCONFIRMED` |
| `invalid_mission` | SINT. | `REJECTED` en `bind_and_validate` | — | — | 0 | misión sin waypoints rechazada por el modelo validado |
| `artifact_modified` | SINT. | `REJECTED` en `bind_and_validate` | — | — | 0 | `Artifact content differs from the recorded hash` (geometría intacta) |

**Reejecución.** `complete` se repitió con `--resume`
([`terminal_resume.txt`](synthetic_demo/complete/terminal_resume.txt)): la solicitud quedó
`EXISTING` y siguió habiendo una sola admisión. Las pruebas comprueban también:
- `FAILED`, `UNCERTAIN` y el rechazo no se reintentan, y el doble no recibe ninguna llamada nueva;
- un flujo interrumpido después de la admisión se reanuda sin una segunda.

**Ningún escenario queda completo.** `SYNTHETIC_COMPLETE` solo vale como demostración; el informe
sintético lo dice en su primera línea y advierte que la parte aérea es el H2 real reidentificado.

## Copia sin `missions/generated` (corregido el 26/10/2026)

> **Corrección.** Esta sección decía «copia limpia (comprobada)». No lo era: la copia se hizo con
> `git ls-files -co --exclude-standard`, que **incluye archivos sin versionar**, y se ejecutó con el
> `.venv` compartido. Por tanto no representa lo que distribuye un clon. Las tres comprobaciones
> separadas (HEAD versionado, conjunto propuesto, instalación con dependencias declaradas) están en
> [la evidencia de cierre](../agri_scenario_flow_closure_2026_10_26/README.md).

**Resultado y alcance, sin cambios.** En una copia de los archivos versionados y no versionados no
ignorados (3716), es decir, sin `missions/generated/` y sin copiar `.venv/`, pero con fuentes sin
versionar y con las dependencias del entorno existente:
- `query` dio `COMPLETED_FLOW`, con un `scenario_report.md` idéntico byte a byte;
- `demo` dio `VERIFIED_SYNTHETIC`;
- `--source local` dio `BLOCKED` (`LOCAL_STORE_UNAVAILABLE`);
- `tests/test_agri_scenario_flow.py` y `tests/test_agri_scenario.py` pasaron: 174.

Demuestra que el flujo no necesita `missions/generated`. No demuestra que un clon funcione.

> **Estados (superado).** Los registros de este directorio muestran
> `AERIAL_COMPLETED_GROUND_NOT_REQUESTED` cuando no había registro R1. Desde la evidencia de cierre,
> sin registro R1 el escenario conserva su estado histórico `AERIAL_COMPLETED_GROUND_PENDING`, y la
> ausencia de solicitud se informa como una dimensión aparte (`NOT_REQUESTED_VIA_THIS_COORDINATOR`).
> Los archivos de este directorio no se han regenerado.

**Dependencias ocultas encontradas:**

| Dependencia | Situación | Solución |
| --- | --- | --- |
| `missions/generated/` (ignorado): secuencia H2, borradores H1 y registros R1 | Solo existe en la máquina de Joel | Fuente `archive`: reconstruye la secuencia desde las copias conservadas con las comprobaciones de identidad del cargador (digest del plan, misiones, admisiones de los hijos e informes finales). Es la fuente por defecto |
| `get_scenario_view` y `r1-dry-run` | Leen `missions/generated` | Sin `missions/generated` devuelven `UNKNOWN`. Para reproducir se usa `agri_scenario_flow query` |
| Sesiones privadas de Hermes | No se necesitan | La etapa Hermes solo lee la evidencia distribuida (`tool_result_as_received.json`, `accept_h3b.json`), sin reevaluar |
| Rutas personales y temporales del contenedor | Ninguna en las salidas | Las rutas son relativas al repositorio. El origen de la captura `/3` contiene rutas del contenedor (`/tmp/tfg_rover_xrce_capture/...`) solo como nombres de copia |
| `pydantic` y `PyYAML` | Se importaban directamente sin figurar en `requirements.txt` | **Resuelto en el cierre**: declarados, con versiones verificadas en una instalación aislada |
| Versiones sin fijar (`langgraph`) | Esta copia usó el entorno existente | **Resuelto en el cierre**: `constraints-verified.txt` |

## Reproducción

```bash
.venv/bin/python -m tools.agri_scenario_flow query --out <dir-nuevo>
.venv/bin/python -m tools.agri_scenario_flow query --out <dir-nuevo> --capture-trial-root simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728 --capture-dir container-copies/tmp/tfg_rover_xrce_capture/4ac58516-8fad-457e-918e-253483a2d728
.venv/bin/python -m tools.agri_scenario_flow variants
.venv/bin/python -m tools.agri_scenario_flow demo --variant complete --out <dir-nuevo>
.venv/bin/python -m tools.agri_scenario_flow demo --variant complete --out <mismo-dir> --resume
.venv/bin/python main.py
.venv/bin/python -m pytest -q tests/test_agri_scenario_flow.py
```

En `main.py`, la opción 5 abre el menú del escenario:
- `1` hace la consulta real;
- `2` lanza la demostración y pide la variante y un directorio nuevo;
- `3` o `menu` vuelve al menú principal;
- `exit`, Ctrl+C o Ctrl+D cierran el programa.
