# TFG unificado: entradas, Hermes, ramas y contrato común (07/11/2026)

**Rama de trabajo:** `feature/multiagent-opik-evaluation`.
- No se ha hecho ningún *merge*.
- `main` no se ha tocado.
- Los hechos de ramas se comprobaron con `git` (`rev-parse` y `merge-base --is-ancestor`) el 07/11/2026.

## Ramas

| Rama | HEAD | ¿Ya está en esta rama? | Qué aporta |
| --- | --- | --- | --- |
| `main` | `6e78668d9` | Sí (ancestro) | Base común |
| `feature/natural-language-qgc-plan` | `da70f5f07` | Sí (ancestro) | Sesión estructurada en `main.py`, entrada QGC `.plan` y exportador |
| `feature/hermes-integration` | `83a147dda` | Sí (ancestro) | Servidor MCP de Hermes, planificación determinista, observabilidad y ciclo de misión |
| `feature/ardupilot-ros2` | `7e8855f6a` | **No** | Línea base ROS 2/Gazebo multivehículo, validada en su fecha. Detalle más abajo |
| `feature/rover-sitl-first-motion` (subsistema rover) | `2e206f1fa` | No | Contratos v1/v2 del rover, executor protegido, ciclo de vida, *scopes* y recuperación. Este lado lo consume solo desde *snapshots* |

### Qué aporta `feature/ardupilot-ros2`

- `launch/tfg_demo.launch.py` y `tfg_demo_2drones.launch.py`;
- los scripts `start_sim`, `check_sim`, `run_demo` y `stop_sim`;
- el informe `validation_3_vehicles.md`, con estos vehículos:
  - `/ap/v1`: dron 1, ArduCopter, SYSID 1;
  - `/ap/v2`: dron 2, ArduCopter, SYSID 2;
  - `/ap/v3`: rover, ArduRover, SYSID 3;
- `tfg_demo_vs_multiagent.patch`.

Sus scripts arman vehículos y los ponen en GUIDED. **No se ejecutan desde aquí.**

El subsistema rover propone en su worktree (sin commitear) un orden de integración. Lo comparto:
1. natural-QGC;
2. Hermes/MCP;
3. ROS 2/Gazebo, solo como código y sin los *runners* de movimiento;
4. El rover desde sucesores protegidos aprobados;
5. El sistema multiagente en commits pequeños, con M4c-r1 inmutable;
6. publicación solo tras revisión humana.

## Tres entradas, un contrato

Las tres entradas acaban en el mismo contrato `tfg.multiagent.mission-input/1`, que contiene:
- el *brief* `/2`;
- la procedencia de cada campo;
- los hallazgos.

Las consumen sin cambios el supervisor, los agentes, los validadores, el generador QGC y el puente al executor. Código: `multiagent/mission_inputs.py`.

| Entrada | Ruta | Qué se reutiliza |
| --- | --- | --- |
| Lenguaje natural | `from_natural_language(text)` → `TO_INTERPRET`, y lo interpreta el Mission Orchestrator (`interpret_brief/4`, contrato de procedencia) | Se registra lo que extrae el parser determinista de Hermes (`planning.deterministic_plan_parser`), solo para comparar |
| QGroundControl `.plan` | `from_qgc_plan(path, …)` → `MissionDefinition` → `from_mission_definition` | El importador de Hermes (`inputs.qgroundcontrol_adapter.load_qgroundcontrol_plan`), sin cambios |
| Misión estructurada | `from_mission_definition(md, …)` | `models.mission_definition.MissionDefinition` y `planning.site_geometry.geo_to_local` |
| Cualquiera de las tres → plan | `StructuredInterpreter(result)` dentro de `MissionOrchestrator` | Corren los mismos validadores y agentes. La etiqueta de proveedor es `structured-input`, `DETERMINISTIC`, y nunca se presenta como un modelo |

### Reglas que impiden inventar datos

- **Coordenadas:** cada *waypoint* pasa de geográfico a local con la georreferencia **declarada** del sitio. La asignación a un punto declarado la hace el *planner* con su propia regla: hay una sola regla en el sistema.
- **Fuera del sitio:** un punto a más de `MAX_RADIUS_M` del origen da `OUTSIDE_SITE_GEOREFERENCE`. Por ejemplo, una misión de otro sitio quedaría a 13 000 km.
- **Retorno:** un *waypoint* final a menos de 1 m de *home* es `RETURN_ENDPOINT`, no un objetivo. El importador convierte LAND/RTL en ese punto.
- **Sensor:** solo existe si el llamante declara una correspondencia acción → sensor; si no, `SENSOR_NOT_STATED`. El exportador de Hermes rechaza las acciones que no son de navegación, así que un `.plan` importado solo lleva *waypoints*.
- **Vehículo:** el del `.plan` se usa solo si es un dron declarado; si no, `VEHICLE_NOT_IN_FLEET` y el Drone Agent propone la asignación.
- **Contexto de importación:** la batería y el viento que trae no son declaraciones del operador. Se registran y no se usan.

### Evidencia

`multiagent/benchmark/results/codex_integration_v2_2026-11-07_0dab97317/mission_inputs/`:
- un `.plan` exportado e importado por Hermes produce un plan multiagente `PROPOSED_PENDING_AUTHORIZATION` sobre POI_1 y POI_3, con 0 comandos;
- una misión de otro sitio se rechaza;
- el lenguaje natural queda `TO_INTERPRET`.

Pruebas: `tests/test_multiagent_mission_inputs.py`.

## Hermes: qué se reutiliza y qué no

| Herramienta MCP de Hermes (`tools/hermes_mcp_server.py`) | Uso desde el sistema multiagente |
| --- | --- |
| `update_mission_draft`, `generate_draft_route`, `finalize_mission_draft`, `validate_mission`, `validate_and_export_qgc` | Generan un `MissionDefinition` o un `.plan`, que entran por `from_mission_definition` o `from_qgc_plan`. Es la vía recomendada para que Hermes alimente al supervisor |
| `start_preflight_sequence`, `run_virtual_preflight`, `propose_mission_revision`, `build_mission_revision` y sus `get_*` | Compatibles como etapas previas. No se llaman desde aquí |
| `check_simulation_ready`, `start_simulation`, `restart_simulation`, `stop_simulation`, `execute_approved_mission` y las reconciliaciones | **No se usan.** Son operaciones protegidas: SITL, ejecución y ciclo de vida. El control del rover es solo el executor del subsistema rover |

## Hallazgos de integración (sin cambiar el código de Hermes)

1. **`planning.site_geometry.geo_to_local` no comprueba el radio**, aunque `local_to_geo` sí lo hace. El adaptador aplica la misma regla (`MAX_RADIUS_M`). Propuesta: añadirla en `site_geometry`, tras revisarlo con quien mantiene Hermes.
2. **El exportador QGC rechaza `take_photo`, `survey` y otras acciones.** Investigación (`multiagent/plan_semantics.py`), hecha contra `common.xml` de MAVLink en pymavlink 2.4.50:
   - **`take_photo`:** existen `IMAGE_START_CAPTURE` (2000) y `DO_DIGICAM_CONTROL` (203), pero identifican una *instancia* de cámara, no un tipo de sensor. No hay inventario de cámaras, así que habría que inventar un id. Además, el importador los descarta.
   - **`loiter`:** `NAV_LOITER_TIME` (19) necesita una duración que el modelo no tiene.
   - **`survey` e `inspect`:** no hay ningún comando de punto.
   - **Tipo de sensor e identificador del *waypoint*:** no tienen campo en un `.plan`.

   **Solución sin ocultar nada:**
   - `export_with_manifest` devuelve `REFUSED_SEMANTIC_LOSS`, con cada fila que no se puede representar, salvo que se acepte un `.plan` solo de navegación.
   - En ese caso escribe el `.plan` (con el exportador de Hermes) y un manifiesto ligado por sha256.
   - `import_with_manifest` solo restaura la semántica si el `.plan` es idéntico byte a byte y cada *waypoint* coincide.
   - `semantic_loss` lista cada campo perdido.
   - Ejemplo: `multiagent/fixtures/plans/`.
3. **El importador convierte LAND/RTL en un *waypoint* de navegación sobre *home*.** El adaptador lo reconoce como `RETURN_ENDPOINT`.
4. **Los errores estructurales del importador son excepciones**: JSON inválido, tipo de archivo distinto, sin *items*, posición incompleta o fuera de rango. El adaptador los convierte en `REJECTED QGC_PLAN_INVALID` (commit `ae01c5bdc`, posterior a la evidencia sellada).
5. **El importador omite con un aviso los comandos que no admite.** Ese *item* podía ser un objetivo, así que el adaptador marca la entrada `NEEDS_CLARIFICATION QGC_ITEM_SKIPPED_BY_IMPORTER`.

## Eventos de SITL

Contrato en `multiagent/sitl_events.py`. Cada evento tiene:
- mensaje y fuente;
- procedencia acreditada por el componente de ingestión, nunca por el mensaje;
- identidad del vehículo según el *topic* declarado;
- *timestamp*, marco y validación;
- el evento del coordinador que genera.

La línea base de `feature/ardupilot-ros2` usa los espacios de nombres `/ap/v1`, `/ap/v2` y `/ap/v3`, pero su informe no registra los nombres de los *topics* de pose. Los *topics* de odometría de `DEFAULT_TOPICS` son de configuración y deben confirmarse cuando exista una ingestión acreditada.

Si el rover pierde la localización, se emite una sola vez `EXECUTOR_PRECONDITIONS NO_POSITION`, y la autorización queda bloqueada.

**Separación de *namespaces* y *topics* (`KNOWN_NAMESPACES` y `KNOWN_TOPICS`):**

| *Topic* | Estado |
| --- | --- |
| `/ap/v1`, `/ap/v2`, `/ap/v3` | *Namespaces* confirmados por el *baseline* |
| `/ap/v1/status`, `/ap/v2/status` | `BASELINE_CONFIRMED`, con el tipo sin confirmar |
| `/ap/v3/cmd_vel` | Es de **comando**: nunca se ingiere |
| `/ap/v3/status`, `/rover1/odometry` | `REFERENCED_BY_ROVER_CODE` (`2e206f1fa`) |

- No hay ningún *topic* de pose de los drones.
- **Nada de lo conocido se puede ingerir:** solo `ACCREDITED_BY_INGESTION` (la futura ingestión del subsistema rover) y `DECLARED_BY_TEST`.
- La ingestión pasa por un puerto inyectado (`SubscriptionPort`), sin importar ROS 2. Los *topics* rechazados se informan; nunca se descartan en silencio.
