# agri_demo_001: evaluación, demostración y defensa del TFG

Preparado el 26/10/2026, offline:
- sin inferencias, simulación, Opik ni operaciones;
- no toca interfaces del rover, del coordinador terrestre, del lector ni del ejecutor.

Complementa la
[sección técnica para la memoria](hermes-planning.md#26102026--escenario-agrícola-integrado-en-la-orquestación-texto-técnico-para-la-memoria).

## 1. Comparación experimental (generada)

[`comparison.md`](../evaluation/observability/agri_experiment_comparison_2026_10_26/comparison.md),
y en JSON
[`comparison.json`](../evaluation/observability/agri_experiment_comparison_2026_10_26/comparison.json).
Los genera `reporting/agri_experiment_comparison.py`, que **solo lee** las evidencias y reutiliza los
análisis existentes:
- `run.json`, `capture_summary.json` y `native_usage_reviewed.json` de cada turno;
- `accept_h3` y `accept_h3b` tal como se registraron;
- `pilot_report` para el piloto;
- la vista de H2.

```bash
.venv/bin/python -m reporting.agri_experiment_comparison comparison --out <archivo-nuevo.md> --json <archivo-nuevo.json>
```

**Separaciones:**
- uso de herramientas;
- respuesta o fallo técnico;
- formato;
- exactitud estructurada (con el denominador y las claves fallidas);
- errores críticos;
- estado de revisión de la explicación;
- tiempos y tokens.

**Unidades distintas:**
- *invocaciones* de Hermes;
- *peticiones al modelo*, principales y auxiliares;
- *intentos internos*: intentos de una petición registrados por Hermes, fallidos o completados (solo los registra el piloto). Que sean reintentos de un mismo ciclo depende de su contador `retry_count`.

**Lo que no hace:**
- No agrega H3, H3b y el piloto en una tasa: prompts, herramientas y protocolos de aceptación son
  distintos.
- No mezcla el piloto antes y después de su enmienda: van en filas separadas.

**Resultados principales**, con su fuente en la tabla:

| Caso | Hecho medido | Denominador y claves |
| --- | --- | --- |
| H1 | Generación y validación de artefactos de misión a partir de una especificación completa: `BOUND` | 2/2 artefactos, validación `APPROVED` y geometría igual a H0. El operador dio todos los valores, las herramientas y su orden. Hermes trasladó la especificación a los argumentos estructurados y encadenó las 4 llamadas. El código calculó las coordenadas, validó, finalizó y vinculó |
| H3 | `NOT_VALIDATED` | **22/23** claves comparadas con su valor esperado; falla `r1_movement_authorized` (Hermes respondió `true`). La evidencia de H3 dice **24/25** porque suma 2 comprobaciones de **presencia** (`evidence_source`, `explanation`) que no comparan valores. Son dos denominadores distintos y no se mezclan |
| H3b | `STRUCTURED_VALIDATED_EXPLANATION_UNREVIEWED` | 23/23 factuales y 12/12 críticas; explicación sin revisión humana |
| Piloto, protocolo original | 1/2 validadas | `r02` sin respuesta: en su única petición registrada hubo 4 intentos fallidos (un timeout y tres 429) y un quinto que pidió la herramienta. `retry_count` vuelve a 0 en el cuarto fallo, así que no se afirman «4 reintentos». La respuesta final no llegó antes del timeout de 300 s |
| Piloto, tras la enmienda 01 | 5/8 validadas | `r03` sin herramienta ni JSON. `r06` rechazada por la **forma** de `reached_points`: objetos en vez de una lista de cadenas, con contenido equivalente a la vista; el rechazo se conserva. `r08` con 5 claves críticas (`claims.*`) |

No hay figuras: matplotlib no está instalado y no se ha instalado nada. Las tablas se regeneran con
el comando de arriba.

## 2. Rúbrica de explicaciones y revisión humana pendiente

[`explanation_rubric_review_sheet.md`](../evaluation/observability/agri_experiment_comparison_2026_10_26/explanation_rubric_review_sheet.md).
Lo genera `review-sheet`:

```bash
.venv/bin/python -m reporting.agri_experiment_comparison review-sheet --out <archivo-nuevo.md>
```

**Contenido.** Siete criterios, cada uno con lo que cuenta como correcto y cómo tratar la
ambigüedad:
- autorización;
- completitud;
- orden y fundamento temporal;
- significado completo de MET;
- capacidades inventadas;
- contradicciones con la respuesta estructurada;
- atribución y límites.

Cada criterio se relaciona con su equivalente de la hoja del piloto del 25/10, que se conserva.

**Textos.** Están literales para H3, H3b y las 8 claves del piloto con explicación analizable, cada
uno con su archivo, el SHA-256 del archivo y el SHA-256 del texto.

**Reglas de la hoja:**
- **Retrospectiva:** la rúbrica es posterior a los ensayos y no cambia ninguna aceptación.
- **Revisión humana pendiente:** las columnas de Joel están vacías. Las observaciones asistidas (la
  de ChatGPT sobre H3b y las del sistema multiagente sobre el piloto) se citan por referencia y no cuentan como
  revisión humana.
- **Ambigüedad:** una frase con dos lecturas se marca `AMBIGUO`, con la cita literal; no se resuelve
  a favor del modelo.

## 3. Guion de demostración (≈ 10 min, sin LLM ni simulador)

**Preparación, una vez:**

```bash
cd ~/TFG/Agentic_Drone_Mission_Control
OUT=$(mktemp -d)
```

Cada orden escribe en un directorio **nuevo** bajo `$OUT`. Todos los comandos se comprobaron el
26/10/2026 con directorios nuevos.

**Si un paso falla,** se usa el resultado **conservado** que indica su fila y se dice en voz alta que
es un resultado histórico, con su fecha; no se presenta como una ejecución en directo. Un caso
probable: el flujo importa `tools/rover_ground_executor.py` y `tools/rover_control.py`, que el subsistema rover
puede estar modificando.

| # | Min | Comando o archivo | Qué debe verse | Qué demuestra | Qué no demuestra | Respaldo conservado |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1,5 | El diagrama de la [sección técnica](hermes-planning.md#arquitectura-y-responsabilidades) y `missions/examples/agri_demo_001_sector_a.json` | Grafo del escenario, coordinadores y ejecutores; la misión H0 con sus POI | La separación entre LLM, código determinista y ejecutores | Que haya percepción agrícola: los POI son datos declarados | — (archivos estáticos) |
| 2 | 1 | `.venv/bin/python -c "from pathlib import Path; from observability.hermes_capture_run import verify_manifest; verify_manifest(Path('evaluation/observability/agri_planning_h1_nous_2026_10_24')); import json; b=json.load(open('evaluation/observability/agri_planning_h1_nous_2026_10_24/h1_binding.json')); print('H1', b['status'], {v: a['mission_sha256'][:12] for v, a in b['artifacts'].items()}, b['flight_authorization'])"` | `H1 BOUND {'drone_01': '321ad647ab9c', 'drone_02': '079e25a30242'} NOT_GRANTED` | Generación y validación de artefactos de misión a partir de una especificación completa. Hermes llevó los datos del operador a los argumentos de las herramientas y encadenó las 4 llamadas; el código validó y ligó por hash a H0 | Planificación independiente: valores, herramientas y orden venían dados. Tampoco autorizó ningún vuelo | [`agri_planning_h1_nous_2026_10_24/README.md`](../evaluation/observability/agri_planning_h1_nous_2026_10_24/README.md) |
| 3 | 1,5 | `.venv/bin/python -m tools.agri_scenario_flow query --out $OUT/query`; después, abrir `$OUT/query/scenario_report.md`, apartado «Resultado de cada ejecución» | Las 8 etapas con lo que espera cada una; `FINISHED/PASSED`; escenario `AERIAL_COMPLETED_GROUND_PENDING`, completo: no | La secuencia H2 real, reconstruida desde copias verificadas: dos drones en orden, 4 POI, regreso y aterrizaje | Validación física, marco común o vuelo simultáneo | [`real_query_h2.terminal.txt`](../evaluation/observability/agri_scenario_flow_closure_2026_10_26/real_query_h2.terminal.txt) y su `scenario_report.md` (26/10/2026); [informe H2](../simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/README.md) |
| 4 | 1,5 | `.venv/bin/python -m reporting.agri_experiment_comparison comparison --out $OUT/comparison.md` y abrir sus secciones 2 y 6 | H3 `NOT_VALIDATED` con `r1_movement_authorized`; H3b 23/23 y 12/12; piloto 1/2 y 5/8 por separado | La aceptación determinista rechazó una declaración errónea de autorización; la variabilidad del piloto | Que se detuviera una orden: no se había enviado ningún movimiento. Tampoco una tasa de fiabilidad | [`comparison.md`](../evaluation/observability/agri_experiment_comparison_2026_10_26/comparison.md) (26/10/2026) |
| 5 | 1 | `.venv/bin/python main.py`, después `5` y `1`; salir con `exit` | El mismo resultado que el paso 3, desde el menú principal | Que el escenario está integrado en la entrada principal, en modo consulta | Ninguna operación: el menú no puede admitir ni ordenar | Igual que el paso 3 |
| 6 | 1,5 | `.venv/bin/python -m tools.agri_scenario_flow demo --variant complete --out $OUT/demo`; `.venv/bin/python -m tools.agri_scenario_flow demo --variant stop_uncertain --out $OUT/stop`; `.venv/bin/python -m tools.agri_scenario_flow demo --variant complete --out $OUT/demo --resume` | `VERIFIED_SYNTHETIC` y «completo solo como demostración sintética»; `UNCERTAIN` (`STOP_UNCONFIRMED`); la reanudación da `VERIFIED_SYNTHETIC` sin una segunda admisión | Etapas, idempotencia y conservación de la incertidumbre del coordinador | El ejecutor real (aquí es `TEST_DOUBLE`) y cualquier movimiento | [`synthetic_demo/*.terminal.txt`](../evaluation/observability/agri_scenario_flow_closure_2026_10_26/README.md) (26/10/2026) |
| 7 | 1 | `.venv/bin/python -m tools.rover_passive_journal --trial-root simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728 --capture-dir container-copies/tmp/tfg_rover_xrce_capture/4ac58516-8fad-457e-918e-253483a2d728 --markdown` | Footer `null` frente al recibo `true`; y ≈ −3,0004 m con dispersión de µm; cabeceo 0,55°; 0,36 s según los sellos frente a 18,6 s de recepción | Una recepción real de odometría del rover, en reposo y verificada por manifiesto | Movimiento, llegada, identidad, transformación o aprobación de umbrales | [`real_capture_4ac58516_report.md`](../evaluation/observability/agri_r1_recovery_correction_2026_10_26/real_capture_4ac58516_report.md) (26/10/2026) |
| 8 | 1 | Las líneas `R1 ·` del paso 3 y la [matriz de preparación](../evaluation/observability/agri_r1_recovery_correction_2026_10_26/README.md#5-matriz-de-preparación-del-primer-r1-en-sitl) | Dependencia MET; `BLOCKED_PENDING`; `NOT_ELIGIBLE`; autorización `ABSENT`; `NOT_STARTED` | Qué falta, separado por dimensiones | Que R1 esté cerca de completarse: faltan transformación, identidad, interfaz física y autorización | Igual |

**Cierre (30 s).** Lo real:
- un ensayo aéreo SITL;
- un turno de planificación de Hermes;
- un turno de interpretación de H3, uno de H3b y un piloto de 10;
- una recepción del rover sin movimiento.

Lo sintético: la navegación terrestre.

## 4. Preguntas de defensa

| Pregunta | Respuesta breve | Respaldo en el código o la evidencia |
| --- | --- | --- |
| ¿Por qué LangGraph? | Para recorridos con etapas explícitas, rutas condicionales y un estado que se persiste: validación de misión, preflight por misión y flujo del escenario. Cada transición queda registrada y todo camino termina en un informe. Los ejecutores y coordinadores no usan LangGraph porque ya tienen persistencia y exclusión propias | `graph/waypoint_mission_graph.py` (determinista); `graph/virtual_preflight_graph.py`; `graph/agri_scenario_graph.py`. `graph/mission_graph.py` es el grafo antiguo, con un LLM local para analizar texto |
| ¿Qué aporta Hermes frente al código determinista? | Lenguaje natural → llamadas a herramientas y explicaciones legibles. En H1, generación de artefactos a partir de una especificación completa: convirtió la petición en español en los argumentos estructurados de las herramientas sin inventar campos y encadenó borradores y finalizaciones. En H3, H3b y el piloto redactó interpretaciones. Todo lo que decide (validación, autorización, orden, aceptación) es código. Y Hermes se equivoca: H3 y 3 de 8 respuestas del piloto tras la enmienda fueron rechazadas (r06 por forma, no por contenido) | Prompt de H1 en `run.json`; `accept_h3*`; `comparison.md` |
| ¿Qué significa aquí «autónomo»? | Cada dron ejecuta su misión sin intervención durante el vuelo: el ejecutor envía objetivos de posición en GUIDED y ArduPilot vuela. **No** hay decisiones de un LLM en el bucle de control, ni replanificación en vuelo, ni vuelo sin autorización del operador. El nombre del repositorio anterior («autonomous mission planner») no describe este sistema | `tools/ros2_flight_control.py` (GUIDED, `POSITION_ONLY_TYPE_MASK`); autorización en `sequence/plan.json` |
| ¿Hay un enjambre o coordinación de varios vehículos? | No hay enjambre. Hay **coordinación secuencial**: un coordinador ejecuta dos misiones de un vehículo cada una, y el segundo dron solo despega si el primero dio PASSED. No vuelan a la vez, no se comunican entre sí y no se reparten tareas. El rover es una tarea dependiente que no se ha ejecutado | `tools/preflight_sequence_worker.py` (`run_coordinator`); `simultaneous_flight: false`; `MissionDefinition` admite un vehículo |
| ¿Qué parte es agricultura de precisión? | El **escenario**: sectores, POI y `objective_type precision_agriculture` son datos declarados por el operador. No hay cámara, imágenes, detecciones ni análisis de cultivo. El dron pasa por los POI dentro de la tolerancia; no los inspecciona | `LIMITATIONS.perception` en `reporting/agri_scenario_summary.py`; prompt de H1 |
| ¿Qué aporta Opik? | Observabilidad de dos turnos de Hermes (H1 y H3): metadatos de tiempos, uso y herramientas, y en H3 la etiqueta `acceptance:NOT_VALIDATED`. No evalúa nada, no recibe prompts ni respuestas, y no cubre H2, H3b, el piloto ni el rover. Un 204 indica aceptación de la petición, no almacenamiento | `docs/opik-export.md`; evidencias `opik_h4_*`; tabla de cobertura de la sección técnica |
| ¿Qué demuestran los ensayos? | Que el recorrido ejecuta exactamente los artefactos aprobados y en orden (H2), y que la aceptación determinista detecta errores críticos del modelo (H3, piloto `r08`). **No** demuestran fiabilidad del modelo ni rendimiento físico: son un ensayo SITL y unos pocos turnos con un modelo gratuito | `comparison.md`; [informe H2](../simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/README.md) |
| ¿Por qué miles de tests no equivalen a fiabilidad física? | Los tests comprueban que el código hace lo especificado ante casos construidos, muchos con dobles sintéticos. No miden sensores, dinámica, viento, latencias reales ni el comportamiento del modelo en producción. Su número mide cobertura, no probabilidad de éxito | `tests/test_agri_ground_joint.py` (sesión física sintética); suite completa |
| ¿Qué falta para completar R1? | Transformación de marcos acreditada; identidad del publicador y SYSID; transporte real con `probe().session_id`; interfaz física de `start_ground_trial`; geometría del rumbo con inclinación ya corregida (`projected_ground_heading`) y probada offline con la muestra real de 0,55°, pero pendientes la acreditación de marcos y la definición de un límite operativo de inclinación (un cálculo geométrico correcto no autoriza ningún movimiento); parámetros y política aprobados, autorización explícita y un único ensayo SITL | [Matriz de preparación](../evaluation/observability/agri_r1_recovery_correction_2026_10_26/README.md#5-matriz-de-preparación-del-primer-r1-en-sitl); dimensiones `R1 ·` del paso 3 |

## 5. Afirmaciones que deben corregirse o matizarse

| Dónde | Afirmación | Problema | Corrección propuesta |
| --- | --- | --- | --- |
| `README.md` (raíz) | Remite a `05_langgraph_autonomous_mission_planner.py` del repositorio anterior | «autonomous» sugiere planificación o vuelo decididos por la IA | En la memoria: «planificador de misiones con LangGraph», y la definición de autonomía de la sección 4. El README es de Joel y no lo he cambiado |
| Etiqueta `objective_type precision_agriculture` (misiones H0/H1) | Puede leerse como capacidad agrícola | Es un tipo de objetivo declarado, sin sensor | Llamarlo «escenario agrícola declarado» |
| «4 POI `REACHED`» (H2) | Puede sugerir una inspección | Significa pasar por el waypoint dentro de 1,0 m horizontal y 0,75 m vertical | Añadir «paso por el punto dentro de la tolerancia; sin inspección» |
| «H1: planificación» | Puede sugerir planificación independiente | El prompt daba los valores, las herramientas y su orden | «Generación y validación de artefactos de misión a partir de una especificación completa». Explicar qué hizo Hermes (argumentos estructurados, encadenar las llamadas) y qué estaba dado |
| Cualquier tasa global con H3, H3b y piloto | — | Protocolos distintos; n pequeño y no independiente | Usar las tablas separadas de `comparison.md` |
| H3 | «el evaluador detuvo una orden» (no aparece en la documentación, pero conviene evitarlo en la defensa) | No había orden | «La aceptación rechazó una declaración errónea de autorización» |

En la documentación revisada no se han encontrado otras afirmaciones de enjambre, percepción,
colaboración distribuida, optimización ni garantías.

## Pendiente

- **Joel:** la revisión humana de las explicaciones, con la hoja de la sección 2.
- **El subsistema rover:** cuando entregue su resultado final verificado (sesión pasiva de identidad y marcos), se
  actualizará el paso 8 y la matriz. No se incorporan archivos en curso.
