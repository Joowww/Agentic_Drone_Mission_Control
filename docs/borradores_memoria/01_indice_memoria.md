# Índice razonado de la memoria (BORRADOR)

**Marcas:**
- **[LISTO]**: puede redactarse ya con evidencia existente.
- **[PARCIAL]**: falta algún resultado.
- **[PENDIENTE]**: depende de hitos no hechos.
- **[BIB]**: necesita bibliografía.

Los objetivos citados (OA*, OD*) son los de la propuesta [`00_propuesta_objetivos.md`](00_propuesta_objetivos.md). Su alcance está **pendiente de consolidar** con Toni; el dataset (OA6) es el único con confirmación explícita reciente.

| Cap. | Título | Contenido y razón de ser | Evidencia o fuente principal | Estado |
| --- | --- | --- | --- | --- |
| 1 | Introducción | Motivación (agricultura de precisión con varios vehículos), problema, objetivos (tras validarlos con Toni) y alcance: simulación, sin hardware | Propuesta de objetivos | [PARCIAL]: depende de las decisiones de Toni; [BIB] |
| 2 | Estado del arte | Agentes LLM con herramientas y riesgos de alucinación; protocolos de herramientas (MCP); robótica aérea y terrestre en agricultura de precisión; ArduPilot, ROS 2 y DDS, Gazebo; misiones MAVLink y QGroundControl; reproducibilidad y datasets de telemetría | — | [PENDIENTE]: todo [BIB] |
| 3 | Requisitos y principios de diseño | Requisitos funcionales y de seguridad: el agente nunca concede autoridad operativa; autorizaciones explícitas; validación determinista; evidencia sellada; separación entre sintético, SITL y hardware | `docs/reconciliation-and-lifecycle.md`, `docs/simulation-profiles.md`, `docs/INDEX.md` | [LISTO] |
| 4 | Arquitectura | Capas y componentes, perfiles de simulación, interfaces y flujos | Borrador [`02_arquitectura.md`](02_arquitectura.md) | [LISTO] como borrador |
| 5 | Planificación con Hermes y validación (OA1, OA2) | Servidor MCP restringido, borradores y finalizaciones, validador; línea H1 → H3b y piloto; transcripción frente a planificación | `docs/hermes-planning.md` (secciones «texto para la memoria»), `docs/agri-demo-defense.md` | [PARCIAL]: falta la evaluación con protocolo y la revisión humana |
| 6 | Ejecución en simulación por el ejecutor (OA3-G) | Ejecutor, secuencias, lifecycle y exclusión, criterios de aceptación; H2 y runs con fallos | `simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24`, `docs/simulation-profiles.md` | [LISTO] para H2 (histórico) |
| 7 | Emplazamientos, exportación `.plan` y misión importada (OA5, OA3-M) | Emplazamiento, flota y plantillas; exportador estricto V2; `package-finalized`; importación en QGC; carga y lectura de vuelta en SITL; ejecución en AUTO | `docs/site-fleet-export.md`, `docs/qgc-first-import-procedure.md`, `docs/sitl-plan-transfer-handoff.md` | [PARCIAL]: carga y ejecución en AUTO [PENDIENTE] |
| 8 | Escenario agrícola y coordinación aire–suelo (OA4) | Escenario agri_demo_001, dependencias, coordinador R1, hitos del rover (identidad, pulso, navegación) y por qué un hito no demuestra el objetivo final | `docs/integrated-trial-protocol.md`, `docs/rover-control.md`, informes del subsistema rover | [PENDIENTE] el resultado; diseño [LISTO] |
| 9 | Telemetría y dataset (OA6) | Esquema, procedencia, relojes, clases de dato, duraciones; piloto y revisiones; traspaso del registro | Repositorio `Agentic_Drone_Mission_Control_Datasets` (`docs/DATA_DICTIONARY.md`, `docs/TELEMETRY_HANDOFF.md`) | [PARCIAL]: falta importar ejecuciones nuevas |
| 10 | Evaluación experimental (OA7) | Resultados de Hermes, de la ejecución y del dataset, con denominadores y limitaciones | `evaluation/observability/agri_experiment_comparison_2026_10_26`, consultas del dataset | [PARCIAL] |
| 11 | Distribución para estudiantes (OD1–OD4) | Contenedores, entrega parcial y requisitos; o como anexo | `docs/student-environment.md`, `docs/simulator-distribution-handoff.md` | [PARCIAL]; ubicación según decisión 6 |
| 12 | Conclusiones y trabajo futuro | Qué se demostró y con qué evidencia, qué queda, ampliaciones | Todo lo anterior | [PENDIENTE] |
| Anexos | Reproducibilidad (comandos y hashes), procedimientos (QGC, transferencia SITL), inventario de evidencias, diccionario del dataset | Documentos existentes citados | [LISTO] en gran parte |

**Orden de redacción propuesto:**
1. Caps. 3, 4 y 6, y la metodología (con evidencia).
2. Caps. 5 y 7 (parciales, marcando lo pendiente).
3. Caps. 9 y 11.
4. Caps. 8 y 10, cuando existan los resultados.
5. Caps. 1, 2 y 12 al final.
