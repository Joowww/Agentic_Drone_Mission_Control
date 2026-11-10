# Bibliografía comentada (BORRADOR) — arquitectura y metodología

Verificada el 30/10/2026. **Estado de verificación:**
- **VERIFICADA:** se leyó la fuente primaria, o su fuente oficial en GitHub, y se confirmó la afirmación citada.
- **METADATOS:** autoría, sede, año e identificador confirmados en registros fiables (arXiv, editorial, repositorio institucional), sin leer el texto completo. Hay que leer el pasaje antes de citarlo literalmente.
- **PENDIENTE:** no se pudo verificar; no se cita hasta confirmarla.

La sección A es literatura y documentación técnica externa. La sección B es **evidencia de nuestro proyecto**, que no es bibliografía y se cita como fuente propia. Las secciones del borrador se refieren a [`02_arquitectura.md`](02_arquitectura.md) (§4.x) y [`03_metodologia.md`](03_metodologia.md) (M.x).

## A. Fuentes externas

### A.1 Agentes LLM con herramientas y protocolo MCP

| # | Referencia | Enlace | Verificación | Qué respalda | Encaja en |
| --- | --- | --- | --- | --- | --- |
| 1 | S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, Y. Cao. *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR 2023. arXiv:2210.03629 | https://arxiv.org/abs/2210.03629 | METADATOS | Los LLM pueden alternar razonamiento y acciones sobre fuentes externas: el paradigma de agente con herramientas que usa Hermes | §4.1, §4.3 |
| 2 | T. Schick, J. Dwivedi-Yu, R. Dessì, R. Raileanu, M. Lomeli, E. Hambro, L. Zettlemoyer, N. Cancedda, T. Scialom. *Toolformer: Language Models Can Teach Themselves to Use Tools*. NeurIPS 36 (2023), pp. 68539–68551 | https://proceedings.neurips.cc/paper/2023/hash/d842425e4bf79ba039352da0f658a906-Abstract.html | METADATOS | Un LM puede decidir qué API llamar, cuándo y con qué argumentos: antecedente del uso de herramientas por el modelo | §4.3 |
| 3 | Z. Ji et al. *Survey of Hallucination in Natural Language Generation*. ACM Computing Surveys 55(12), art. 248 (2023). arXiv:2202.03629 | https://arxiv.org/abs/2202.03629 | METADATOS. El DOI `10.1145/3571730` solo aparece en fuentes secundarias: **confirmarlo en la ACM DL** | Los modelos generan contenido no sustentado por la fuente. Justifica que la salida del agente sea una propuesta, que valida código determinista, y la evaluación por claves de M.3 | §4.1, M.3 |
| 4 | Model Context Protocol. *Specification*, versión 2025-06-18 | https://modelcontextprotocol.io/specification/2025-06-18 | VERIFICADA | MCP usa mensajes JSON-RPC 2.0 entre *hosts*, *clients* y *servers*; los servidores exponen *tools*, *resources* y *prompts*. «Hosts must obtain explicit user consent before invoking any tool», y el protocolo **no puede imponerlo**: lo deben implementar las aplicaciones. Respalda que las autorizaciones estén en nuestra aplicación (lifecycle, compuertas) y no en el protocolo. **[PENDIENTE]** fijar qué versión de MCP implementan nuestro servidor y Hermes | §4.1, §4.3 |
| 5 | Nous Research. *Hermes Agent* (repositorio, licencia MIT) | https://github.com/NousResearch/hermes-agent | VERIFICADA (descripción y README) | Hermes es un agente de Nous Research que puede conectarse a servidores MCP. Es documentación de la tecnología; nuestro commit (`d923a5eb`) se cita como evidencia propia (B) | §4.3 |
| 6 | LangChain. *LangGraph — Graph API* (documentación oficial) | https://docs.langchain.com/oss/python/langgraph/graph-api | METADATOS (dominio oficial, en búsqueda; página no leída) | Los flujos se modelan como grafos de nodos y aristas sobre un estado (`StateGraph`): el grafo de preflight y el del escenario | §4.4 |

### A.2 ArduPilot, AP_DDS, ROS 2, DDS y Gazebo

| # | Referencia | Enlace | Verificación | Qué respalda | Encaja en |
| --- | --- | --- | --- | --- | --- |
| 7 | ArduPilot Dev Team. *SITL Simulator (Software in the Loop)*. Wiki de ArduPilot | https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html (fuente leída: `ArduPilot/ardupilot_wiki`, `dev/source/docs/sitl-simulator-software-in-the-loop.rst`) | VERIFICADA (fuente de la wiki, rama master) | SITL ejecuta Plane, Copter o Rover sin hardware, compilado como ejecutable nativo, y puede usar simuladores externos como Gazebo mediante el interfaz JSON | §4.2 |
| 8 | ArduPilot. *AP_DDS — Testing with DDS/micro-ROS* (README), en el commit `755258db` | https://github.com/ArduPilot/ardupilot/blob/755258dbb452f46dc7e1e47a36591f3b62e8830d/libraries/AP_DDS/README.md | VERIFICADA **localmente**: árbol limpio en ese commit, con origen `github.com/ArduPilot/ardupilot` (enlace formado con el commit) | ArduPilot contiene un cliente DDS que en SITL se comunica con el agente Micro XRCE-DDS por UDP o serie; `DDS_USE_NS=1` incluye `v<MAV_SYSID>` en los nombres; el agente se lanza en UDP 2019 | §4.2 |
| 9 | ArduPilot. `libraries/AP_DDS/AP_DDS_Client.cpp`, en el commit `755258db` | https://github.com/ArduPilot/ardupilot/blob/755258dbb452f46dc7e1e47a36591f3b62e8830d/libraries/AP_DDS/AP_DDS_Client.cpp | VERIFICADA localmente | `geopose/filtered` publica `loc.alt` (cm → m) como altitud, con un `TODO` que **supone** el marco absoluto WGS-84. La orientación y la velocidad se convierten de NED a ENU (REP 103) | §4.5, M.5 |
| 10 | ArduPilot Dev Team. *Copter Mission Command List*. Wiki de ArduPilot | https://ardupilot.org/copter/docs/mission-command-list.html (fuente leída: `copter/source/docs/mission-command-list.rst`) | VERIFICADA (rama master, no la versión ejecutada) | Semántica de TAKEOFF (sube en vertical hasta la altitud), WAYPOINT (retención y `WP_RADIUS_M`), LAND (en la posición actual o en lat/lon dadas) y DO_CHANGE_SPEED | §4.5 |
| 11 | ArduPilot. *ardupilot_gazebo* (README) | https://github.com/ArduPilot/ardupilot_gazebo | VERIFICADA (rama main; nuestro commit `cc0290d9` es evidencia propia) | Plugin oficial de ArduPilot para Gazebo (Garden, Harmonic LTS, Ionic, Jetty; Harmonic recomendada), con intercambio JSON con SITL | §4.2 |
| 12 | S. Macenski, T. Foote, B. Gerkey, C. Lalancette, W. Woodall. *Robot Operating System 2: Design, architecture, and uses in the wild*. Science Robotics 7(66), eabm6074 (2022). doi:10.1126/scirobotics.abm6074 | https://doi.org/10.1126/scirobotics.abm6074 | METADATOS (es la cita oficial de ROS 2 según Open Robotics) | Diseño y arquitectura de ROS 2 sobre DDS | §4.2 |
| 13 | Object Management Group. *Data Distribution Service (DDS)*, v1.4, formal/15-04-10 (2015) | https://www.omg.org/spec/DDS/1.4 | METADATOS | DDS define un modelo publicación–suscripción centrado en datos, con calidad de servicio | §4.2 |
| 14 | Object Management Group. *DDS For Extremely Resource Constrained Environments (DDS-XRCE)*, v1.0, formal/20-02-01 (2020) | https://www.omg.org/spec/DDS-XRCE/1.0 | METADATOS | Un dispositivo con pocos recursos accede a una red DDS a través de un agente XRCE: la relación entre AP_DDS y el agente micro-ROS | §4.2 |
| 15 | N. Koenig, A. Howard. *Design and use paradigms for Gazebo, an open-source multi-robot simulator*. IEEE/RSJ IROS 2004, pp. 2149–2154. doi:10.1109/IROS.2004.1389727 | https://doi.org/10.1109/IROS.2004.1389727 | METADATOS (registro IEEE 1389727) | Origen de Gazebo como simulador 3D para varios robots | §4.2 |
| 16 | Open Robotics. *Gazebo Harmonic* (documentación) | https://gazebosim.org/docs/harmonic | METADATOS (sitio oficial, en búsqueda) | Harmonic es una versión LTS, con soporte de septiembre de 2023 a septiembre de 2028 | §4.2 |

### A.3 Coordenadas, marcos y altitudes

| # | Referencia | Enlace | Verificación | Qué respalda | Encaja en |
| --- | --- | --- | --- | --- | --- |
| 17 | T. Foote, M. Purvis. *REP 103: Standard Units of Measure and Coordinate Conventions* (informacional, activa) | https://www.ros.org/reps/rep-0103.html | METADATOS (no se pudo abrir el texto; confirmado por búsqueda y fuentes secundarias) | Unidades SI; ENU para los marcos del mundo; NED solo en marcos con sufijo `_ned`; cuaterniones. **Leer el texto** antes de citar frases | §4.5, M.5 |
| 18 | ROS. `geographic_msgs/msg/GeoPoint.msg` (rama `ros2`) | https://github.com/ros-geographic-info/geographic_info/blob/ros2/geographic_msgs/msg/GeoPoint.msg | VERIFICADA | «Altitude [m]. Positive is above the WGS 84 ellipsoid». Contrasta con #9: AP_DDS rellena ese campo con la altitud absoluta de ArduPilot (*supuesto* marcado como `TODO`). Por eso el dataset no la trata como altura elipsoidal verificada | §4.5, M.5 |
| 19 | National Geospatial-Intelligence Agency. *World Geodetic System 1984*, NGA.STND.0036 | — | **PENDIENTE** (edición y enlace oficial por confirmar) | Definición del datum WGS 84 | §4.5 |
| 20 | Fuente para la aproximación plana local (111 320 m por grado y factor cos φ) que usan el proyecto y el dataset | — | **PENDIENTE**: buscar un texto de geodesia o navegación; no se cita nada hasta tenerlo | Validez de la aproximación en emplazamientos pequeños | §4.5, M.5 |

### A.4 MAVLink y QGroundControl

| # | Referencia | Enlace | Verificación | Qué respalda | Encaja en |
| --- | --- | --- | --- | --- | --- |
| 21 | MAVLink Development Team. *Mission (Plan) Protocol* | https://mavlink.io/en/services/mission.html (fuente leída: `mavlink/mavlink-devguide`, `en/services/mission.md`) | VERIFICADA | Subida: MISSION_COUNT → MISSION_REQUEST_INT → MISSION_ITEM_INT → MISSION_ACK. Descarga: MISSION_REQUEST_LIST. **En ArduPilot, `seq 0` contiene el home.** Base de la prueba de carga y lectura de vuelta | §4.5; cap. 7 (traspaso SITL) |
| 22 | A. Koubaa, A. Allouch, M. Alajlan, Y. Javed, A. Belghith, M. Khalgui. *Micro Air Vehicle Link (MAVLink) in a Nutshell: A Survey*. IEEE Access 7, pp. 87658–87680 (2019). doi:10.1109/ACCESS.2019.2924410 | https://doi.org/10.1109/ACCESS.2019.2924410 | METADATOS | Visión general de MAVLink, usado por ArduPilot y PX4 | §4.5 |
| 23 | QGroundControl. *Plan File Format* (guía de desarrollo) | https://docs.qgroundcontrol.com/master/en/qgc-dev-guide/file_formats/plan.html | METADATOS (resultado de búsqueda; la página no se pudo abrir desde aquí) | `.plan` en JSON (`mission`, `geoFence`, `rallyPoints`). `plannedHomePosition` = latitud, longitud y **altitud AMSL**. `SimpleItem` = un ítem de misión MAVLink. **Hay diferencias entre versiones** (master frente a 4.x): confirmar contra la versión usada (5.1.5) | §4.5 |

### A.5 Evaluación y datasets

| # | Referencia | Enlace | Verificación | Qué respalda | Encaja en |
| --- | --- | --- | --- | --- | --- |
| 24 | P. Liang et al. *Holistic Evaluation of Language Models*. Transactions on Machine Learning Research (08/2023). arXiv:2211.09110 | https://arxiv.org/abs/2211.09110 | METADATOS | Evaluación con varias métricas, estandarizada y transparente (*prompts* y salidas publicados). Respalda que separemos métricas y denominadores y conservemos las salidas | M.3 |
| 25 | T. Gebru, J. Morgenstern, B. Vecchione, J. Wortman Vaughan, H. Wallach, H. Daumé III, K. Crawford. *Datasheets for Datasets*. Communications of the ACM 64(12), pp. 86–92 (2021). doi:10.1145/3458723 | https://doi.org/10.1145/3458723 | METADATOS | Documentar la motivación, la composición, la recogida y los usos recomendados de un dataset: estructura del README y del diccionario del dataset | M.5 |
| 26 | M. D. Wilkinson et al. *The FAIR Guiding Principles for scientific data management and stewardship*. Scientific Data 3, 160018 (2016). doi:10.1038/sdata.2016.18 | https://doi.org/10.1038/sdata.2016.18 | METADATOS | Datos localizables, accesibles, interoperables y reutilizables, con metadatos legibles por máquina: procedencia, identificadores y formatos abiertos | M.5 |
| 27 | S. Kapoor, A. Narayanan. *Leakage and the reproducibility crisis in machine-learning-based science*. Patterns 4, 100804 (2023). doi:10.1016/j.patter.2023.100804 | https://doi.org/10.1016/j.patter.2023.100804 | METADATOS | La fuga de datos entre entrenamiento y evaluación es frecuente y sobrestima resultados. Justifica la separación por `split_group` y no por registro | M.5 |
| 28 | W. Zhao, J. Peña Queralta, T. Westerlund. *Sim-to-Real Transfer in Deep Reinforcement Learning for Robotics: a Survey*. IEEE SSCI 2020, pp. 737–744. doi:10.1109/SSCI47803.2020.9308468 | https://doi.org/10.1109/SSCI47803.2020.9308468 | METADATOS | Existe una brecha entre simulación y realidad: amenaza a la validez de resultados solo en SITL. Es una encuesta centrada en RL; puede convenir una fuente más general | M.6 |

**Pendiente para estos capítulos:**
- #19 y #20;
- confirmar el DOI de #3 y el texto de #17;
- leer los pasajes de las fuentes con estado METADATOS antes de citarlas literalmente;
- fuentes sobre robótica aérea y terrestre en agricultura de precisión y sobre coordinación de varios robots, para los caps. 1 y 2 (no buscadas en esta tanda).

## B. Evidencia del proyecto (no es bibliografía)

Se cita como fuente propia, con ruta y hash, y con la fecha cuando es un resultado histórico.

| Qué | Dónde | Encaja en |
| --- | --- | --- |
| Commit de Hermes usado (`d923a5eb`) y proveedor y modelo de las ejecuciones | `docs/student-environment.md` §9; `evaluation/observability/planning_container_real_2026_10_28_r2/` | §4.3 |
| Commits del workspace de simulación (ArduPilot `755258db`, `ardupilot_gazebo` `cc0290d9`, `ros_gz`, `micro-ROS-Agent`…) | `docs/simulator-distribution-handoff.md` §3 | §4.2 |
| Intervalo de sondeo configurado (`POLL_INTERVAL_SECONDS = 2.0`) y retención del registro (16 + 96) | `tools/simulation_mission_executor.py`, `tools/execution_diagnostics.py` | §4.4, M.2 |
| Frecuencia efectiva observada en H2 (lecturas de 2,9 s y separación de 4,6 s de mediana) | Originales de H2; `docs/TELEMETRY_HANDOFF.md` del repositorio del dataset | §4.4, M.6 |
| H2 PASSED (24/10) | `simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/` | §4.4, M.4 |
| Línea H1 → H3b y piloto | `docs/hermes-planning.md`, `evaluation/observability/agri_experiment_comparison_2026_10_26/` | M.3 |
| Exportador V2, QGC y `package-finalized` | `docs/site-fleet-export.md`; `evaluation/observability/qgc_import_hermes_two_drones_2026_10_30/` | §4.5 |
| Dataset: piloto y revisiones | Repositorio `Agentic_Drone_Mission_Control_Datasets` (`docs/DATA_DICTIONARY.md`) | §4.6, M.5 |
| Rover (informes del subsistema rover, **no verificados de forma independiente**) | `evaluation/operations/`, `simulation/ros2_gazebo/results/rover_*` | §4.4, M.4 |
