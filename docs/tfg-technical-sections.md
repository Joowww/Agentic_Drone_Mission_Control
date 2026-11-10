# Material técnico para la memoria del TFG (07/11/2026)

Borrador para integrar en la memoria. Cada resultado cita la evidencia sellada de la que sale. Lo que no está acreditado no aparece como resultado.

## 1. Arquitectura

**Principio.** Los agentes LLM **proponen**, los validadores deterministas **deciden**, un humano **autoriza** y solo un executor protegido podría **actuar**. Ningún componente con LLM tiene una herramienta de actuación; una prueba lo comprueba sobre la lista real de herramientas.

| Componente | Papel | Implementación |
| --- | --- | --- |
| Mission Orchestrator (supervisor) | Interpreta la petición. Desde la versión `/4`, cada hecho lleva cita y procedencia (`mission-brief-provenance/1`) | `brief_provenance.py`; el grafo del orquestador está hecho con LangGraph (`orchestrator.py`) |
| Drone/Swarm Agent | Asigna objetivos aéreos y verifica rutas y separación con herramientas | `llm_agents.py`, contrato `agent_drone_single/3` |
| Rover Agent | Decide si espera una observación o planifica hacia un POI declarado | `llm_agents.py`, `rover_gate.py`, contrato `agent_rover_single/3` |
| Herramientas | Solo de planificación y validación: capacidades, rutas, separación, objetivo terrestre, dependencias | `agent_tools.py` |
| Validadores deterministas | Procedencia del brief, política `safety/4`, disponibilidad, sensores, batería y viento, desconflictación temporal, compuerta del rover, compuerta de percepción | Varios módulos; ninguno lo decide un LLM |
| Percepción | Detector de cartulinas por umbrales HSV (sin aprendizaje), y píxel → marco del sitio con incertidumbre | `card_detector.py`, `geometry.py`, `perception.py` |
| Geometría del rover | Sitio → `map`/`odom` → `base_link` con transformaciones rígidas acreditadas | `frames2d.py` |
| Coordinador | Máquina de estados por eventos: dependencias dron → rover, caducidades, cancelación, autorización como registro | `mission_coordinator.py` |
| Puente y executor protegido | Solicitud versionada, recibo y contrato v2 del subsistema rover; el executor real es del subsistema rover. Aquí solo hay dry-run | `rover_executor_bridge.py`, `rover_v2_bridge.py`, `rover_handoff.py` |
| Entrada de SITL | Eventos tipados → coordinador; la procedencia la da el componente de ingestión | `sitl_events.py`; sin conexión real |
| Opik | Trazas y experimentos. Una traza histórica publicada; el resto, en dry-run | `opik_bridge.py`, `opik_pilots.py` |

## 2. Metodología

- **Versionado de *prompts*.** `interpret_brief/1` a `/4` y `agent_*_single/1` a `/3`. Un identificador nunca se reutiliza. Los archivos de los que dependen los conjuntos congelados no se editan: `/3` y `/4` se registran desde módulos nuevos, y una prueba comprueba que sus hashes no cambian.
- **Versionado de contratos.** `mission-brief/2`, `mission-brief-provenance/1`, `observation/1`, `rover-execution-request/1` y `human-authorization/1`. Del lado del subsistema rover, los contratos v1 y v2, fijados por commit.
- **Datos.** `cases_v1` (34), `eval_v2` (33), `dev_v3` (14), `eval_v3` (26, congelado) y `adversarial_v3` (13). No se ajusta nada sobre los conjuntos congelados; solo se usan como comprobación de no regresión (por ejemplo, los 53 briefs gold de v3 por el camino de procedencia).
- **Pilotos.** Antes de cada piloto se registra y confirma en git un manifiesto con el caso, los criterios y un presupuesto de llamadas, sin reintentos. Las precondiciones de aislamiento se comprueban antes de la primera llamada y todo resultado se sella (`SHA256SUMS`), también los fallos. Un piloto fallido nunca se repite para mejorar el resultado; se cambia la causa y se registra un piloto nuevo (M4 → M4b → M4c → M4c-r1).
- **Evaluación de errores.**
  - Clases: infraestructura, modelo, *parser* y herramienta.
  - Por rol: éxito en la primera ronda, éxito tras revisión, fallback, corrección determinista, rechazo correcto o incorrecto, y no alcanzado.
  - **Un fallback o una corrección determinista nunca cuentan como éxito del LLM.**
- **Comparación.** Cada rol se compara con su agente determinista (M0) bajo la misma delegación.
- **Trazabilidad y reproducción.**
  - Las respuestas originales se guardan íntegras, con el hash de *prompt* y respuesta.
  - Una repetición sin modelo reproduce la parte determinista (`replay_supervisor`).
  - `python -m multiagent.demo --replay` muestra un piloto sellado tras verificar sus hashes.
  - `python -m multiagent.benchmark.milestone` genera el registro del hito.
- **Tamaño muestral.** Tres casos por rol en M1–M3 y una sola ejecución integrada completada. Los resultados son indicativos y **no se generalizan estadísticamente**.

## 3. Resultados acreditados

**Pilotos por rol (tres casos cada uno; `docs/multiagent-real-agents.md`):**
- Supervisor M1: 1/3.
- Drone Agent M2: 1/3, 2/3 y 2/3 con los contratos v1, v2 y v3; los planes finales fueron seguros en 3/3.
- Rover Agent M3: 0/3, 0/3 y 2/3 con el contrato v3; uno de los casos se resolvió con una segunda llamada.

**Pilotos integrados:**

| Piloto | Llamadas | Resultado |
| --- | --- | --- |
| M4 | 2 | El supervisor tomó la delegación condicional por una orden insegura y rechazó la misión |
| M4b | 1 | El supervisor inventó tres datos de entrada y la misión acabó en aclaración |
| M4c | 0 | No se ejecutó: la regla de aislamiento no se cumplió |
| **M4c-r1** | **4** | **El supervisor, el Drone Agent y el Rover Agent con Qwen real (`qwen3:4b`, local, temperatura 0), todos en la primera ronda y sin fallback** |

**Detalle de M4c-r1** (`results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9/`; registro verificable en `docs/milestones/m4c_r1_2026-11-07/`):
- La planificación se completó y la ejecución quedó pendiente de autorización humana, con **cero comandos**.
- El conflicto de separación en el ascenso lo resolvió el **validador determinista**, no el modelo, con un retraso de 45 s. Una repetición determinista comprueba que es el menor de la rejilla.
- La detección fue **sintética**.

**Integración offline** (agentes programados, no Qwen):
- 17 escenarios de la demo;
- una batería de 18 misiones que recorre toda la cadena y el código real del subsistema rover desde un *snapshot*;
- 18 casos de traspaso.

En todos los casos se obtuvo la clasificación esperada y ningún comando (`results/integration_battery_offline_2026-11-07_4311c7481/`, `results/rover_handoff_offline_2026-11-07_0c886b624/`).

**Detector** (imágenes sintéticas):
- La versión 1 y su equivalente en OpenCV aciertan los mismos 34/37; OpenCV es unas 53 veces más rápido.
- La versión 2, con el umbral de área derivado de la geometría, acierta 35/37.

## 4. Limitaciones

- Solo hay **una** ejecución integrada con LLM real completada, y el *prompt* `/4` se escribió después del fallo anterior.
- No hay detección con cámara real ni calibración medida.
- No hay localización física del rover ni ejecución del rover en SITL.
- No ha habido navegación ni vuelo de ningún vehículo.
- Se ha usado un único modelo pequeño (4B), que necesitó contratos estrictos y validación determinista.
