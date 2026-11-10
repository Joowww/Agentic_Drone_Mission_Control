# Capítulo 4 (BORRADOR): Arquitectura del sistema

> Borrador inicial. **Marcas:**
> - **[BIB]**: la afirmación necesita bibliografía.
> - **[HISTÓRICO dd/mm]**: resultado de una sesión concreta, que no describe el estado actual.
> - **[PENDIENTE]**: resultado aún no obtenido.
> - **[FUENTE]**: documento o código del repositorio que respalda el párrafo.
>
> Los objetivos citados pertenecen a una propuesta cuyo alcance está pendiente de consolidar con Toni.

## 4.1 Visión general

El sistema separa **cuatro responsabilidades**, y ninguna concede autoridad operativa a otra:
1. **Planificación asistida por un agente:** un agente LLM, Hermes, propone y finaliza misiones con un conjunto de herramientas restringido.
2. **Validación determinista:** código sin LLM determina la **viabilidad** (`mission_status`) y el estado **APPROVED** del software (`execution_status`) de una misión, e intenta su exportación. APPROVED significa que el validador la acepta según sus reglas; **no concede permiso operativo**.
3. **Ejecución y ciclo de vida en simulación:** un ejecutor y un coordinador operan vehículos simulados bajo autorizaciones explícitas, reservas y exclusión.
4. **Evidencia y datos:** cada operación deja registros sellados que se analizan offline y alimentan un dataset de telemetría.

**Principio de diseño:** las salidas del agente son **propuestas**. Un efecto exige que la validación determinista lo admita **y además** una **autorización explícita del operador**, por operación y con alcance concreto. La aprobación del software nunca sustituye esa autorización [FUENTE: `docs/reconciliation-and-lifecycle.md`; `docs/INDEX.md`]. Este principio responde a riesgos conocidos de los agentes LLM con herramientas, como las acciones no deseadas o las afirmaciones no sustentadas [BIB].

## 4.2 Pila de simulación

| Capa | Componente | Notas |
| --- | --- | --- |
| Autopiloto | ArduPilot SITL (ArduCopter y ArduRover) [BIB] | Fuente local en el commit `755258db`. La versión que informa SITL (`V4.8.0-dev`) está registrada en sesiones del 20 al 26/10; no en todas las ejecuciones [FUENTE: `docs/site-fleet-export.md` §8] |
| Middleware | ROS 2 Humble con AP_DDS sobre micro-ROS/XRCE-DDS [BIB] | Espacios de nombres por vehículo `/ap/v1`, `/ap/v2`, `/ap/v3` (`DDS_USE_NS`) [FUENTE: `simulation/ros2_gazebo/README_SIMULATION.md`, `docs/simulation-profiles.md`] |
| Simulador físico | Gazebo Harmonic con `ardupilot_gazebo` y `ros_gz` [BIB] | Modelos IRIS (drones) y WILD_THUMPER (rover) |
| Perfiles | `two_drones` (por defecto) y `two_drones_rover` | Seleccionados por el lifecycle a partir de un catálogo fijo, no de datos del solicitante [FUENTE: `tools/simulation_profiles.py`, `docs/simulation-profiles.md`] |

**Vehículos lógicos:**

| Vehículo | Interfaz | `MAV_SYSID` | Notas |
| --- | --- | --- | --- |
| `drone_01` | v1 | 1 | — |
| `drone_02` | v2 | 2 | — |
| `rover_01` | v3 | 3 | Solo en `two_drones_rover` |

La flota lógica (`missions/fleets/agri_demo_fleet.json`) vincula cada vehículo con su perfil de exportación y su enlace a la simulación.

[PENDIENTE] **Receta reproducible del simulador.** Hoy vive en un contenedor mutable [FUENTE: `docs/simulator-distribution-handoff.md`].

## 4.3 Planificación: Hermes y servidor MCP

- **Agente:** Hermes (NousResearch, commit `d923a5eb`) [BIB], conectado por stdio al **servidor MCP del proyecto** (`tools/hermes_mcp_server.py`) [BIB: Model Context Protocol]. En las ejecuciones citadas se usó `nous` / `poolside/laguna-s-2.1:free`.
- **Restricción de herramientas:** el servidor publica 27 herramientas, entre ellas operativas. El perfil de planificación las restringe a `update_mission_draft` y `finalize_mission_draft`, con el filtro de herramientas de Hermes y su búsqueda de herramientas desactivada [FUENTE: `docs/student-environment.md` §9].
- **Borradores y finalizaciones** (`tools/hermes_mission_planning.py`): el borrador es versionado. La finalización es una instantánea inmutable con hashes de la misión, del borrador de origen y de su estado. El modelo de misión es `MissionDefinition` (`models/mission_definition.py`), con rutas por waypoints, home declarado y altitudes relativas al home.
- **Validación** (`tools/hermes_mission_validation.py`): viabilidad (`mission_status`) y estado del software (`execution_status`, p. ej. APPROVED), deterministas, más un intento de exportación estricta, que se **rechaza** si falta el AMSL del home [FUENTE: `docs/site-fleet-export.md` §8.1]. Ninguno de esos estados autoriza ejecutar: la ejecución exige una autorización explícita aparte.
- **Captura y observabilidad** (`observability/hermes_capture_run.py`, `observability/opik_export.py`):
  - cada ejecución autorizada de Hermes queda en un directorio sellado: comprobación previa, eventos, uso nativo y revisión;
  - el envío a Opik es opcional.

## 4.4 Ejecución y ciclo de vida

- **Lifecycle** (`tools/simulation_lifecycle.py`):
  - abre y cierra la simulación con un perfil;
  - registra cada operación;
  - impone una **exclusión global** entre lifecycle, admisión y ejecución.
- **Preflight virtual:** el grafo LangGraph `graph/virtual_preflight_graph.py` [BIB: LangGraph] recorre `snapshot → validate → check_readiness → compatibility → execute → analyze → write_report`. Cada transición queda registrada con su hora [FUENTE: `transitions` de los informes de ejecución].
- **Ejecutor** (`tools/simulation_mission_executor.py`, `tools/ros2_flight_control.py`):
  - órdenes GUIDED, armado, despegue, `cmd_gps_pose`, regreso y aterrizaje por AP_DDS;
  - **intervalo de sondeo configurado:** 2 s de espera entre sondeos (`POLL_INTERVAL_SECONDS`);
  - **frecuencia efectiva observada:** menor, porque cada lectura es un proceso `docker exec … ros2 topic echo --once`. [HISTÓRICO 24/10] En H2, cada lectura tardó una mediana de 2,9 s (máx. 8,6 s) y la separación entre lecturas consecutivas fue de 4,6 s de mediana (máx. 13 s), alternando estado y posición [FUENTE: originales de H2, analizados en `docs/TELEMETRY_HANDOFF.md` del repositorio del dataset];
  - tolerancias de aceptación: 1,0 m en horizontal y 0,75 m en altura.
- **Registro de operaciones** (`tools/execution_diagnostics.py`), solo en el formato de informe del 24/10 en adelante:
  - guarda cada lectura u orden con su hora UTC del anfitrión y el texto de la respuesta;
  - **retención limitada:** las 16 primeras operaciones y las 96 últimas, con un recuento de las omitidas;
  - **puede haber pérdidas:** la CLI de ROS puede avisar de mensajes perdidos; una lectura puede fallar sin observación.
- **Secuencias:** `tools/preflight_sequences.py` y `tools/preflight_sequence_worker.py` ordenan los runs de varios vehículos con dependencias por resultado observado, nunca por tiempo.
- **Reconciliación** (`tools/execution_reconciliation.py`): inspección y aplicación auditada de restricciones inciertas [FUENTE: `docs/reconciliation-and-lifecycle.md`].
- **Rover:** `tools/rover_ground_executor.py` y `tools/rover_control.py` (subsistema rover), más el coordinador R1 `tools/agri_ground_coordinator.py`.
  - El movimiento del rover sigue bloqueado por sus compuertas [FUENTE: informes del subsistema rover en `evaluation/operations/`, no verificados de forma independiente].
  - [PENDIENTE] navegación del rover y coordinación aire–suelo real.

## 4.5 Escenario agrícola y misiones geográficas

- **Modelos del escenario:**
  - emplazamiento (`models/site.py`): marco local `ENU_ROTATED`, referencia geográfica y vertical, perímetro, exclusiones y zonas;
  - flota (`models/fleet.py`);
  - plantilla (`models/scenario_template.py`).
- **Instanciación** (`planning/scenario_instance.py`): resuelve las plantillas sobre el emplazamiento, vuelve a expresar las misiones históricas o **cambia de base** las misiones finalizadas por Hermes sobre un despegue elegido. Siempre genera derivados con hash nuevo y sin heredar la aprobación.
- **Validación espacial** (`planning/site_validation.py`): líneas planificadas frente al perímetro y las exclusiones, más los márgenes declarados [FUENTE: `docs/site-fleet-export.md` §3–§5, §17].
- **Exportación** (`inputs/qgc_plan_export.py`, perfil `QGC_PLAN_ARDUCOPTER_V2`):
  - `NAV_TAKEOFF`, `NAV_WAYPOINT`, `DO_CHANGE_SPEED` opcional y `NAV_LAND`, en `MAV_FRAME_GLOBAL_RELATIVE_ALT`, sin RTL [BIB: formato `.plan` de QGC y comandos MAVLink];
  - empaquetado y verificación con `tools/scenario_package.py`.
  - [HISTÓRICO 27/10 y 30/10] QGroundControl 5.1.5 abrió y guardó planes sin diferencias semánticas (`tools/qgc_plan_compare.py`).
  - [PENDIENTE] carga y lectura de vuelta en SITL, y ejecución en AUTO.
- **Orquestación del escenario** (`graph/agri_scenario_graph.py`, `tools/agri_scenario_flow.py`): consulta del escenario conservado y demostración **sintética** con un ejecutor de prueba.

## 4.6 Evidencia, telemetría y dataset

- **Evidencia sellada:** cada operación o análisis deja un directorio nuevo con un README y un manifiesto (`SHA256SUMS`).
  - El manifiesto se **genera después**, al cerrar el directorio, sobre los bytes que hay en ese momento.
  - Un hash acredita **integridad respecto al manifiesto**, es decir que los bytes no cambiaron después. **No** acredita que la medición sea verdadera ni completa.
  - Las evidencias no se modifican ni se regeneran [FUENTE: `docs/INDEX.md`, regla de evidencias].
- **Dataset** (repositorio aparte `Agentic_Drone_Mission_Control_Datasets`):
  - importa de forma reproducible ejecuciones selladas;
  - separa medición, orden enviada, evento del ejecutor, objetivo planificado y métrica calculada;
  - mantiene relojes separados y procedencia hasta el campo.
  - [HISTÓRICO 30/10] Piloto con 5 ejecuciones SITL; revisiones 0.2 y 0.2.1.
  - [PENDIENTE] ejecuciones nuevas con el registro mejorado (traspaso al subsistema rover).

## 4.7 Distribución

Hay imágenes de contenedor para la app offline, QGC y Hermes, y un Compose de entrega [FUENTE: `docs/student-environment.md`].
- [HISTÓRICO 30/10] Entrega parcial verificada solo en el equipo de origen.
- [PENDIENTE] simulador, segundo ordenador y licencia.

## Figuras propuestas [PENDIENTE]

1. Diagrama de capas: agente → validación → lifecycle y ejecución → SITL, con la evidencia transversal.
2. Secuencia de una ejecución: transiciones del preflight y operaciones del ejecutor.
3. Escenario agri_demo_001: drones, POI y dependencia de R1.
