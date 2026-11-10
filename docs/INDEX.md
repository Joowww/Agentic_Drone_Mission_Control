# Índice del repositorio (punto de entrada)

Estado a 28/10/2026, ampliado el 09/11/2026 con la rama de integración y revisado el 10/11/2026 tras la auditoría independiente (arquitectura unificada y matriz de alcance: [integrated-architecture.md](integrated-architecture.md)). Es un mapa, no un informe: el detalle está en los documentos enlazados. El reparto por directorios, con consumidores y estado, está en [repository-map.md](repository-map.md).

**Regla:** un resultado guardado describe el momento en que se obtuvo. **No sustituye una comprobación actual**, aunque sea reciente.

**Evidencias:** las de `evaluation/observability/`, `evaluation/operations/`, `simulation/ros2_gazebo/results/` y `multiagent/benchmark/results/` son registros sellados de su fecha, cada una con su README y su manifiesto (`SHA256SUMS` o `manifest.json`). No se modifican, no se regeneran y no se mueven; una evidencia nueva va en un directorio nuevo.

Etiquetas de esta página:

| Etiqueta | Qué significa |
| --- | --- |
| REAL | Ejecución real: inferencia, SITL o aplicación |
| SINTÉTICO | Dobles, fixtures o demo |
| FALLIDO | Resultado negativo conservado |
| SUPERADO | Sustituido por una versión posterior |
| HISTÓRICO | Válido para su fecha, no para hoy |

## 1. Entradas actuales

| Qué | Entrada |
| --- | --- |
| Menú principal (opción 5 = escenario agrícola) | `main.py` |
| Escenario: consulta y demo sintética | `python -m tools.agri_scenario_flow query\|demo` |
| Emplazamientos, flota y paquetes `.plan` | `python -m tools.scenario_package` (exportador estricto `inputs/qgc_plan_export.py`) |
| Misiones finalizadas por Hermes → paquete, con emplazamiento, flota y despegue explícitos | `python -m tools.scenario_package package-finalized` (menú 5 → 3 → `f`; [site-fleet-export.md](site-fleet-export.md) §17) |
| Comparar el `.plan` original con el guardado por QGC | `python -m tools.qgc_plan_compare` |
| Informes y comparación experimental | `python -m reporting.agri_scenario_summary`, `python -m reporting.agri_experiment_comparison` |
| Servidor MCP del proyecto, el que usa Hermes | `python -m tools.hermes_mcp_server` |
| Ejecución de Hermes con captura de evidencia | `python -m observability.hermes_capture_run` |
| Demo local Hermes + Ollama (perfil `tfg-demo-local`, servidor MCP solo de planificación, captura, revisión, vista HTML) | `python -m observability.local_planning_demo` y `python -m tools.hermes_demo_planning_server` ([hermes-ollama-local-demo.md](hermes-ollama-local-demo.md); manual para Toni: [manual-demo-hermes-ollama.md](manual-demo-hermes-ollama.md)) |
| Prototipo multiagente offline (orquestador, dron/enjambre, rover), benchmark de modelos y traza Opik en dry-run | `python -m multiagent.demo`, `python -m multiagent.benchmark.run` ([multiagent-architecture.md](multiagent-architecture.md)) |
| Traspaso multiagente -> contrato v2, adaptador final payload -> ejecutor y admisión del ejecutor del rover de este repositorio (en proceso, sin snapshot; políticas cerradas; cero comandos) | `python -m multiagent.demo --battery`, `python -m multiagent.demo --scenario red_target --rover-handoff`, `python -m multiagent.integration_battery` ([integrated-architecture.md](integrated-architecture.md) §5) |
| Inventarios distribuibles y listas de contexto de las imágenes | `python -m tools.agri_scenario_distribution` |

## 2. Configuración y contenedores

| Qué | Dónde | Documento |
| --- | --- | --- |
| Compose `tfg-dist`, perfiles `app`, `dev`, `qgc`, `planning`, `planning-test` | `deploy/compose.yaml` | [student-environment.md](student-environment.md) |
| Imagen offline | `deploy/app/` | §3 a §8 de la guía |
| Imagen de planificación `tfg/planner:2026.10.28` (Hermes `d923a5eb` + MCP) | `deploy/planner/` | §9 de la guía, [planning-first-real-test.md](planning-first-real-test.md) |
| QGroundControl 5.1.5 | `deploy/qgc/` | [qgc-first-import-procedure.md](qgc-first-import-procedure.md) |
| **Entrega PARCIAL vigente** para estudiantes, **no publicada**: `app`, `qgc` y `hermes` con `docker save`, Compose `tfg-estudiante` y `LEEME.md`; IA solo Hermes; recorrido de finalizaciones de Hermes a `.plan` con el almacén en solo lectura; **sin simulador** | Fuera del repositorio: `/home/joelm/TFG/entregas/tfg-entrega-estudiantes-2026.10.30/`. Las anteriores, `…2026.10.28-r2/` y `…2026.10.28/`, están superadas y se conservan | §0 y §3 b) de la guía; evidencia `student_bundle_2026_10_30` |
| Entrega completa: objetivo, mapa de lo que falta y traspaso del simulador al subsistema rover | — | [simulator-distribution-handoff.md](simulator-distribution-handoff.md) §7–§8 |
| Plantillas de VS Code (tareas y vista del explorador) | `deploy/vscode/` | [repository-map.md](repository-map.md#vista-en-vs-code) |
| Dependencias | `requirements*.txt` y `constraints-verified.txt` (versiones verificadas) | — |
| Simulador (contenedor mutable, propiedad del subsistema rover) | `simulation/ros2_gazebo/` | [simulator-distribution-handoff.md](simulator-distribution-handoff.md) |

## 3. Documentación vigente

- **Historial de desarrollo y revisiones fijadas:** etiqueta local `archive/integration-history-2026-11-10` ([integrated-architecture.md](integrated-architecture.md) §5.1); `main` es un commit consolidado.
- **Arquitectura unificada (09/11/2026, revisada el 10/11):** [integrated-architecture.md](integrated-architecture.md): cadenas de la integración, matriz de alcance (integrado y probado offline; simulación disponible sin verificar; pendiente con Gazebo, SITL, drones y rover; políticas cerradas; limitaciones para una ejecución física segura), pruebas e insumos de la suite. Las pruebas offline no son una validación operativa.
- **Paquete del rover pendiente de revisión:** [rover-package-review-2026-11-09.md](rover-package-review-2026-11-09.md): estado, causas de las incidencias que provocaba y cambios exactos para una revisión formal nueva.

- **Uso y distribución:** [student-environment.md](student-environment.md).
- **Planificación con Hermes:**
  - [hermes-planning.md](hermes-planning.md): línea H1 a H3b, piloto y texto para la memoria;
  - [planning-first-real-test.md](planning-first-real-test.md): la próxima ejecución real.
- **Exportación:** [site-fleet-export.md](site-fleet-export.md), [qgc-first-import-procedure.md](qgc-first-import-procedure.md) y [integrated-trial-protocol.md](integrated-trial-protocol.md) (protocolo no ejecutado).
- **Defensa del TFG:** [agri-demo-defense.md](agri-demo-defense.md). Una línea, «revisión del supuesto plano», está desactualizada.
- **Arquitectura multiagente (prototipo SINTÉTICO, rama `feature/multiagent-opik-evaluation`):** [multiagent-architecture.md](multiagent-architecture.md); resumen en inglés para Toni en `documentation/multiagent_overview_for_toni_en.md`.
- **Observabilidad:**
  - [hermes-observability-capture.md](hermes-observability-capture.md) y [hermes-capture-runbook.md](hermes-capture-runbook.md);
  - [opik-export.md](opik-export.md) (Opik desactivado por defecto);
  - [opik-multiagent.md](opik-multiagent.md) (importación del piloto; E07 enviada y verificada) y [opik-fase2.md](opik-fase2.md) (fase 2: métricas, *feedback scores*, experimentos y dashboard, todo preparado y sin enviar).
  - [opik-op1.md](opik-op1.md) (OP-1 rechazada con HTTP 400 por la ventana UUIDv7 de Opik; nada almacenado; OP-1b pendiente) y [hardware-compatibility.md](hardware-compatibility.md) (SITL, dron físico, JetRacer).
- **Demo integrada de agricultura de precisión (offline):** [precision-demo.md](precision-demo.md) (`python -m multiagent.demo --scenario …`, 17 escenarios, `--safety-policy safety/3|safety/4`; comparación del detector con OpenCV), [physical-integration-strategy.md](physical-integration-strategy.md) y [physical-integration-checklist.md](physical-integration-checklist.md); resumen para Toni en `documentation/precision_demo_summary_for_toni_en.md`. Estado del TFG para Toni: `documentation/tfg_status_for_toni_en.md`. Hito M4c-r1 verificable: [milestones/m4c_r1_2026-11-07/MILESTONE.md](milestones/m4c_r1_2026-11-07/MILESTONE.md) (`python -m multiagent.demo --replay <dir>` reproduce lo registrado sin modelo). Plan hacia Gazebo: [gazebo-integration-plan.md](gazebo-integration-plan.md). Traspaso real al contrato y al executor del subsistema rover: `python -m multiagent.rover_handoff`; batería de integración: `python -m multiagent.integration_battery` (o `demo --battery --rover-snapshot <dir>`); informe para el subsistema rover: [rover-handoff-report-2026-11-07.md](rover-handoff-report-2026-11-07.md); material para la memoria: [tfg-technical-sections.md](tfg-technical-sections.md); guion de demo: `documentation/demo_script_5min_en.md` y el técnico de 13 pasos `documentation/demo_technical_script_2026-11-07_en.md`. Integración v2 con el subsistema rover (dos *snapshots*, sobre de envío, propietario único de la conversión): evidencia SINTÉTICA `multiagent/benchmark/results/codex_integration_v2_2026-11-07_0dab97317/` (`python -m multiagent.benchmark.integration_v2_evidence`). Entradas de misión (lenguaje natural, `.plan` QGC, estructurada), Hermes y ramas: [tfg-unified-integration-map-2026-11-07.md](tfg-unified-integration-map-2026-11-07.md); interfaces para el *merge*: [merge-interface-map.md](merge-interface-map.md). Preparación de la integración para el candidato del subsistema rover (inventario, relaciones de git, *smoke tests*): [tfg-integration-preparation-2026-11-07.md](tfg-integration-preparation-2026-11-07.md) y `python -m multiagent.integration_smoke`. Ronda `ROVER_ADAPTER` (conversión final en el adaptador del subsistema rover, semántica de `.plan`, *topics* SITL): evidencia SINTÉTICA `multiagent/benchmark/results/codex_adapter_integration_2026-11-07_32c19517d/`. Dos drones (plan multiagente → misiones Hermes → petición H2 sin efectos, agenda temporal, cámara, demo `python -m multiagent.demo --two-drones [--replay-plan]`): procedimiento SITL preparado y **no ejecutado** [two-drone-sitl-procedure-2026-11-07.md](two-drone-sitl-procedure-2026-11-07.md); evaluación SINTÉTICA `multiagent/benchmark/results/two_drone_integration_2026-11-07_42e788de9/`.
- **Agentes con LLM real:** [multiagent-real-agents.md](multiagent-real-agents.md) (contrato de un solo turno, piloto real M1/M2/M3 de 9 llamadas a qwen3:4b, contrato de observación dron → rover, misión integrada offline y pilotos integrados M4 y M4b, que fallaron, y M4c-r1, la primera misión con Qwen real en los tres roles; perfil de aislamiento por recursos `resource_isolation/1`) y [rover-executor-integration.md](rover-executor-integration.md) (incluye las pruebas contra el contrato `tfg.rover.mission-execution/1` del subsistema rover).
- **Rover:** [rover-control.md](rover-control.md), [rover-source-correlation.md](rover-source-correlation.md) y checkpoints. [Preparación rover 06/11/2026](checkpoints/2026-11-06-rover-offline-safety-preparation.md) recoge instrumentación y experimentos aún no autorizados. [Precheck y siguiente captura pasiva](checkpoints/2026-11-06-rover-next-passive-session.md) documenta el bloqueo actual y el procedimiento preparado. [Compatibilidad de reader pins y capturador MAVLink](checkpoints/2026-11-06-reader-pin-block-and-mavlink-capture.md) documenta el protocolo versionado implementado, sus pruebas y la promoción protegida aún pendiente. [Continuación offline del rover](checkpoints/2026-11-06-rover-offline-autonomy-continuation.md) recoge el análisis de estacionariedad, captura/correlación MAVLink, métricas de failsafe y contratos de misión. [Integración offline del scope pasivo con START](checkpoints/2026-11-06-rover-passive-scope-start-integration.md) documenta el consumidor preparado, las pruebas y los bloqueos de promoción pendientes. [Seguimiento offline de SIGALRM y validación](checkpoints/2026-11-06-rover-sigalrm-followup.md) registra la corrección del warning y el bloqueo que aún impide un scope pasivo oficial. [Seguimiento de integración pasiva](checkpoints/2026-11-06-rover-passive-integration-followup.md) describe el cierre vertical offline, las diez fases vinculadas al lifecycle, el supervisor de STOP y los bloqueos protegidos restantes. [Paquete único de revisión protegida 07/11/2026](checkpoints/2026-11-07-rover-protected-review.md) incluye alcance, hashes, riesgos, opciones de autorización y procedimiento para una sesión pasiva futura. [Seguimiento de desarrollo offline 07/11/2026](checkpoints/2026-11-07-rover-autonomous-development.md) documenta el proveedor fixture, el protocolo futuro del helper, el replay M4c-r1, el baseline antiguo y las conexiones pendientes. [Contrato v2 Rover Agent → executor y mapa de ramas](checkpoints/2026-11-07-rover-claude-branch-integration.md) recoge la prueba contractual con snapshot el sistema multiagente fijo, el adaptador de payload y la preparación sin merge de la rama candidata. [Resumen en inglés para Toni](../documentation/rover_update_for_toni_en.md).
- **Documentación histórica de la base de simulación (04–06/10/2026), no operativa:** `documentation/AGENTIC_AI.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `COMMANDS_CHEATSHEET.md` y `DEMO_GUIDE.md`, recuperados de `feature/ardupilot-ros2`. Son registros de su fecha; `COMMANDS_CHEATSHEET.md` y `DEMO_GUIDE.md` arrancan Gazebo/SITL y arman vehículos directamente y **no deben ejecutarse**: el simulador solo se arranca y detiene con `tools/simulation_lifecycle.py` y autorización explícita.
- **Material histórico** (sigue enlazado por evidencias, así que no se mueve): retiradas administrativas `c6eeb645` (20/10), [demo-reunion-2026-10-19.md](demo-reunion-2026-10-19.md), [roadmap-3-11-offline.md](roadmap-3-11-offline.md) y `documentation/development_log.md`.

- **Demo local Hermes + Ollama + observabilidad (08/11/2026):** estado, comandos verificados, pilotos y casos de comparación en [hermes-ollama-local-demo.md](hermes-ollama-local-demo.md); manual para Toni (borrador) en [manual-demo-hermes-ollama.md](manual-demo-hermes-ollama.md); investigación previa en [hermes-ollama-observability-investigation-2026-11-08.md](hermes-ollama-observability-investigation-2026-11-08.md).

## 4. Pruebas mantenidas

`pytest.ini` en la raíz y `tests/`.
- **De la línea agrícola, exportación y distribución:** `test_agri_scenario_flow.py`, `test_agri_scenario.py`, `test_agri_ground_*.py`, `test_scenario_package.py`, `test_site_geometry.py`, `test_qgc_plan_compare.py`, `test_qgroundcontrol_exporter.py`, `test_hermes_capture_run.py` y `test_planning_profile.py`.
- **Con dobles en contenedor:** `deploy/app/student_walkthrough.sh` y `deploy/planner/planning_checks.sh`.
- **Del rover (`test_rover_*`):** son del subsistema rover.
- **De la integración (10/11/2026):** `test_stop_backend_boundary.py` (frontera shell–proceso del STOP), `test_stop_close_modes.py` (modos de cierre excluyentes en la entrada pública y el lector fijo), `test_stop_protected_state.py` (criterio central: matriz de lecturas de sesiones protegidas), `test_rover_final_adapter_handoff.py` (traspaso por el adaptador final y límites inmutables), `test_rover_sim_metrics_binding.py` (métricas ligadas a la ejecución y al ciclo de vida) y `test_multiagent_pilot_preflight.py` (comprobación previa de pilotos en cerrado).

## 5. Evidencias principales (`evaluation/observability/` salvo indicación)

| Evidencia | Tipo | Qué demuestra y qué no |
| --- | --- | --- |
| `hermes_ollama_local_pilot_2026_11_08_r02` | REAL | Hermes + Ollama local (`qwen3-4b-instruct-64k`) + MCP de solo planificación: misión `VALIDATED`, FEASIBLE/APPROVED, QGC REFUSED, NOT_GRANTED; solo 2 herramientas ofrecidas. Desviaciones del modelo documentadas (borradores nuevos, `mission_id` por defecto). Un piloto, no una tasa |
| `hermes_ollama_local_pilot_2026_11_08_r01` | REAL · FALLIDO | El modelo puso el viento actual en el viento máximo e inventó `draft_id`; nada guardado |
| `ollama_context_memory_2026_11_08` | REAL (mediciones) | 64 k en 8 GiB: solo con flash attention y KV q4_0 (5,6 GB, 100 % GPU); la variante *Thinking* tarda 430 s por llamada |
| `agri_planning_h1_nous_2026_10_24` | REAL · HISTÓRICO | Hermes generó y validó dos misiones **a partir de una especificación completa** (BOUND). No es planificación autónoma |
| `simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24` (subsistema rover) | REAL · HISTÓRICO | Secuencia aérea SITL `6628bc51` PASSED. El rover no se ejecutó |
| `agri_scenario_h3_nous_2026_10_24` | REAL · FALLIDO | NOT_VALIDATED: afirmó `r1_movement_authorized=true` |
| `agri_scenario_h3b_nous_2026_10_24` | REAL | STRUCTURED_VALIDATED. La explicación sigue **sin revisión humana** |
| `agri_scenario_pilot_nous_2026_10_24` y `…pilot_audit_2026_10_25` | REAL + reevaluación offline | 6 STRUCTURED_VALIDATED, 3 NOT_VALIDATED y 1 timeout del proveedor. No es una tasa general |
| `agri_scenario_view_h2_…`, `agri_scenario_report_h2_…`, `agri_experiment_comparison_2026_10_26` | Derivado determinista | Vistas e informes a partir de lo anterior, sin inferencia |
| `agri_scenario_flow_2026_10_26` y `…_closure_2026_10_26` | SINTÉTICO | Flujo integrado y demo con un ejecutor de prueba. Nunca una ejecución física |
| `agri_r1_*_2026_10_25` y `…_26`, `agri_r1_identity_review_2026_10_27` | SINTÉTICO / revisión | Coordinación R1 offline. R1 **no se ha ejecutado** |
| `agri_site_fleet_export_2026_10_27` | SUPERADO | Paquetes V1 (PROFILE_SUPERSEDED) |
| `agri_export_semantics_2026_10_27` | SINTÉTICO, vigente | Paquetes V2 del exportador estricto |
| `qgc_plan_comparison_offline_2026_10_27` | SINTÉTICO | Casos del comparador |
| `qgc_import_hermes_two_drones_2026_10_30` | REAL (importación offline) | QGC 5.1.5 abrió y guardó los 2 `.plan` derivados de Hermes (`e5815ac0…`, `df2e0d66…`). Cada uno sale NO_SEMANTIC_DIFFERENCES con 4 PRESENTATION. Joel observó 4 ítems por plan; coordenadas y alturas no se comprobaron visualmente. Incluye el diagnóstico de WSLg (cliente RDP caído y relanzado una vez). Sin carga, SITL ni vuelo |
| `qgc_first_import_2026_10_27` | REAL | QGC 5.1.5 abrió y guardó un `.plan` sin diferencias semánticas. No incluye carga en vehículo ni vuelo |
| `planner_container_build_2026_10_28` | Build + pruebas con dobles | Imagen vigente `2026.10.28` con las correcciones de `HERMES_HOME` y `login`: 24/24 con dobles. Sin ejecución real con esta imagen |
| `hermes_finalized_package_two_drones_2026_10_30` | SINTÉTICO (emplazamiento de ensayo `synthetic_hermes_rehearsal_v1`) sobre misiones REALES | Caso positivo: los 2 drones GENERATED con 2 `.plan` verificados contra la misión y correspondencia de cada derivada comprobada aparte. COMPLETE_OFFLINE, R1 FORMAT_PENDING, aprobación ABSENT y `deployment_ready` false. Sin importar en QGC ni cargar |
| `hermes_finalized_package_2026_10_28` | SINTÉTICO (emplazamiento) sobre misiones REALES · caso negativo | Las 2 misiones finalizadas en r2, cambiadas de base sobre `synthetic_orchard_v1`: drone_01 GENERATED con `.plan` verificado; drone_02 BLOCKED_VALIDATION_FAILED (TREE_ROW_1). Paquete PARTIAL y `deployment_ready` false, más 4 rechazos. Nada cargado ni ejecutado |
| `student_bundle_2026_10_30` | Entrega PARCIAL vigente + build de `tfg/app:2026.10.30` | Finalizaciones de Hermes → paquete → 2 `.plan` desde la app, con el almacén en solo lectura. 12/12 aislada **en este mismo equipo** con finalizaciones SINTÉTICAS: rechazo de entrada alterada y persistencia. Sin simulador; segundo ordenador pendiente |
| `student_bundle_2026_10_28_r2` | Entrega PARCIAL SUPERADA + build de `tfg/app:2026.10.28` | Solo Hermes: Compose sin `planner-menu` ni `ollama` y menú offline orientado a Hermes. Verificación aislada de lo afectado 10/10 en este mismo equipo. Sin ejecutar Hermes ni abrir QGC |
| `student_bundle_2026_10_28` | Entrega PARCIAL SUPERADA + verificación aislada | Entrega local con las tres imágenes, sin simulador: 13/13 **en este mismo equipo** (hashes, carga, Compose, consulta offline, paquete y su verificación, almacén de planificación). Sin Hermes ni QGC abiertos. Segundo ordenador pendiente |
| `planning_container_real_2026_10_28_r2` | REAL | Una ejecución de Hermes en contenedor (**imagen `2026.10.27`, `651cc6e2…`**) con `nous` / `poolside/laguna-s-2.1:free`: 2 misiones con los datos del operador, validadas, exportación REFUSED sin AMSL e idénticas a H1. No es planificación autónoma ni una tasa |
| `planning_container_real_2026_10_28` | REAL · FALLIDO | Falló antes del modelo: Hermes leyó otro `HERMES_HOME` |
| `qgc_container_build_…`, `app_container_build_…` (+`_r2`) y `planner_container_build_2026_10_27` | Build + pruebas | Imágenes y recorridos. La planificación solo con **dobles**: no hubo inferencia real |
| `opik_*` | REAL · HISTÓRICO | Envíos de metadatos de H1 y H3 confirmados visualmente; el resto son diagnósticos |
| `hermes_mcp_structured_trial_*`, `hermes_mcp_tool_trial_*`, `hermes_real_capture_*`, `langsmith_*`, `mission_report_*` | HISTÓRICO, con FALLIDOS y SUPERADOS | Ensayos previos a H1. Su estado está en el README de cada uno |
| `evaluation/operations/*` y `simulation/ros2_gazebo/results/rover_*` (subsistema rover) | Según sus informes | Identidad, transporte, recuperación y cierre del rover. **no verificado de forma independiente** |

## 6. Siguiente tarea

- **El sistema multiagente:** la entrega parcial `-r2` (solo Hermes) está preparada y el objetivo de la entrega completa está concretado ([student-environment.md](student-environment.md) §0; mapa y traspaso en [simulator-distribution-handoff.md](simulator-distribution-handoff.md) §7–§8). **El trabajo del sistema multiagente queda en espera hasta recibir el simulador reproducible del subsistema rover.** Entonces tendrá que:
  - incorporar el servicio de simulación al Compose de entrega;
  - mantener la entrega solo con Hermes, ya aplicada en `-r2`;
  - incorporar a la imagen `app` el recorrido `package-finalized` y un montaje de solo lectura del almacén de planificación (ver `hermes_finalized_package_2026_10_28`);
  - exportar y verificar la entrega completa.
- **Pendientes de distribución y validación** (§10 de la guía):
  - prueba en un segundo ordenador;
  - simulador reproducible;
  - versionado;
  - licencia;
  - publicación eventual.
- **El subsistema rover**, según su informe del 28/10/2026 y **sin verificación independiente del sistema multiagente** (`simulation/ros2_gazebo/results/rover_authorized_capture_2026_10_28/f15f176e-…`):
  - captura **REAL PARCIAL** de la sesión `46c26a0c-9fc6-4226-a986-f2da8a1b83a2`: 4 Status y 4 odometrías con GID hasta Python;
  - correlación RPC hasta el contexto XRCE, y odometría → bridge → modelo;
  - cierre de infraestructura SUCCESS;
  - canal socket fallido por timeout (`TimeoutExpired:SOCKET_QUERY_OR_PERSISTENCE_UNCERTAIN`), sin uniones completas peer/socket/SITL ni propietario receptor de FDM;
  - después (`evaluation/operations/rover_socket_timeout_offline_2026_10_28/f4b0ab66-…`), instrumentación del canal socket corregida offline, **sin demostrar que la latencia real haya desaparecido**;
  - siguiente trabajo: preparar la revisión actual y la siguiente captura, con su propia autorización;
  - **identidad completa y movimiento siguen BLOCKED**.

  Los GID, PID y la frescura de esa sesión no valen para una sesión futura.
- **El subsistema rover, carga y lectura de vuelta en SITL de los dos `.plan` derivados de Hermes** (transferencia, separada de la ejecución): [sitl-plan-transfer-handoff.md](sitl-plan-transfer-handoff.md). Preparado, no ejecutado.
- **El subsistema rover, simulador para la entrega:** construcción reproducible según el traspaso de [simulator-distribution-handoff.md](simulator-distribution-handoff.md) §8. **No se usa `docker commit`.**

