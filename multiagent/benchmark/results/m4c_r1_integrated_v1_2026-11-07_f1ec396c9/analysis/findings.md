# M4c-r1: análisis (07/11/2026)

**Resultado:** `PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION`, con 0 comandos y `physical_effect` falso.

**Por primera vez, el supervisor, el Drone Agent y el Rover Agent han trabajado con Qwen real (local `qwen3:4b`) en una misma misión.** Los tres roles han tenido éxito en la primera ronda, sin ningún fallback ni corrección determinista. Se cumplen todos los criterios: C0, C0b, C1, C2, C3, C4 y C5.

Es una prueba de existencia, no una estadística: un caso, una ejecución.

## Protocolo

- **Manifiesto.** `pilots/m4c_r1_integrated_v1.json` (sha256 `c500cb89…`), registrado en `ac92b087f` antes de cualquier llamada. Es una revisión explícita de M4c, que nunca se ejecutó (`results/m4c_integrated_v1_2026-11-06_NOT_RUN_blocked_2346`). El caso, el modelo, el digest, los parámetros, los *prompts*, la política, el presupuesto y los criterios son los mismos; solo cambia el aislamiento.
- **Ejecución.** En `f1ec396c9`. Entre el registro y la ejecución solo cambiaron tres correcciones del propio chequeo de aislamiento: `622e339ec`, `65db258de` y `f1ec396c9`. Las tres hacían que el chequeo cerrara en el lado seguro por errores de medida nuestros. El manifiesto no se modificó.
- **Aislamiento `resource_isolation/1`.** Todas las comprobaciones salieron en verde (`preconditions.json`):
  - Ollama sin ningún modelo cargado y sin otro piloto en marcha;
  - ninguna sesión de Gazebo ni SITL;
  - GPU libre (1 MiB usado de 8192, 0 %) y 9,3 GiB de RAM disponibles;
  - sin reservas, bloqueos ni procesos operativos;
  - contratos de Codex fijados en `f2fd78ae1`;
  - herramientas de los LLM solo de planificación y executor dry-run;
  - manifiesto íntegro.

  Se observó, sin que bloqueara, que Codex estaba pasando sus pruebas unitarias (un núcleo de CPU) y editando su worktree.
- **Opik.** Se eliminó `OPIK_API_KEY` del entorno y no se publicó nada.

## Por rol

Detalle en `exchanges.jsonl`, que contiene los *prompts* completos y las respuestas crudas.

| # | Rol | Tokens (entrada + salida) | Latencia | Respuesta | Validación determinista |
| --- | --- | --- | --- | --- | --- |
| 1 | Supervisor (`interpret_brief/4`) | 1423 + 331 | 39,8 s (incluye la carga en frío del modelo) | Brief de procedencia: A1 POI_1 rgb y A2 POI_3 multispectral, ambos citados literalmente; G1 con `waits_for: VALIDATED_OBSERVATION` y `rover_01` citado; `stated: []`; `to_look_up` con las 4 consultas | Procedencia `VALID` y limpia, sin correcciones; `safety/4` sin señales. Fase A: `PROPOSED_PENDING_AUTHORIZATION` |
| 2 | Drone Agent (`agent_drone_single/3`) | 1331 + 206 | 18,9 s | drone_01→A1 y drone_02→A2; pide `validate_route` ×2 y `check_separation` | Herramientas: `drone_capabilities`, `validate_route` (FEASIBLE ×2) y `check_separation`, que encontró un conflicto en el ascenso (8,0 m frente a 8,5 m). La compuerta lo aceptó al resolverlo con 45 s de retraso para drone_01 (`DECONFLICTED_BY_START_DELAY`). Asignación del modelo, primera ronda |
| 3 | Rover Agent, fase A (`agent_rover_single/3`) | 1047 + 110 | 11,2 s | `WAIT_FOR_OBSERVATION` para G1, sin punto objetivo | `rover_gate` aceptó. Tarea `CONDITIONAL_AWAITING_OBSERVATION`, no ejecutable |
| 4 | Rover Agent, fase B | 1095 + 123 | 10,3 s | `PLAN_TO_DECLARED_POI` a POI_3; pide `validate_ground_target` | Herramientas: `rover_capabilities` y `validate_ground_target` (PASS). Aceptado y coincidente con el agente determinista (`AGREES`) |

**Entre las fases A y B** no hubo llamadas al modelo. Se usó la imagen `SYNTHETIC_TEST`, en la que el detector v2 encontró `red_card`. La geometría situó el objetivo en el marco del sitio, en (8,0, 4,0) con σ = 0,12 m. La compuerta aceptó la observación y la emparejó con POI_3, y el coordinador pasó a `READY_FOR_AUTHORIZATION` y después a `AUTHORIZATION_REQUESTED`.

**La solicitud final** es `rover-execution-request/1`, en estado `AWAITING_HUMAN_AUTHORIZATION`. No es ejecutable porque ningún humano ha fijado velocidad ni tiempo máximo (`NO_NAVIGATION_PLAN`).

**Llamadas.** Se usaron 4 de las 6 autorizadas: supervisor 1/2, Drone Agent 1/2, Rover Agent 2/2. No hubo revisiones ni repeticiones.

## Observaciones

1. **Verificación poco pertinente del Rover Agent en la fase A.** Pidió `check_dependency(ROVER_START)`, que no es un punto de espera; la decisión era correcta igualmente. Su resultado no quedó escrito en la evidencia, por un defecto nuestro ya corregido en `a516dfc77`. Se ha repetido offline la herramienta determinista y está etiquetada como repetición en `replay.json`: devuelve `OK`, `reached_by_a_proposed_drone_task: false` y los puntos aéreos POI_1 y POI_3.
2. **Latencia de la primera llamada.** Fueron 39,8 s, frente a 9,6 s en M4b. La causa es la carga en frío: Ollama no tenía el modelo cargado, que es precisamente una de las condiciones del aislamiento. Es infraestructura, no un fallo.
3. **Repetición sin llamada del supervisor** (`replay.json`). El *prompt* coincide con el sellado, y la decisión es `PROPOSED_PENDING_AUTHORIZATION` con `safety/2`, `/3` y `/4`. En esa repetición, el Drone Agent es un guardián sin modelo y la planificación aérea la completa el fallback determinista; no es el resultado del piloto.

## M4, M4b y M4c-r1 (mismo texto, modelo, digest y parámetros)

| | M4 | M4b | M4c-r1 |
| --- | --- | --- | --- |
| Supervisor | `interpret_brief/2`, `safety/3` | `/3`, `safety/4` | `/4` (procedencia), `safety/4` |
| Fallo del supervisor | Marcó como insegura la delegación condicional | Inventó 3 campos (batería nula, disponibilidad `UNKNOWN`, `drones`) | Ninguno |
| Llamadas usadas / autorizadas | 2 / 6 | 1 / 6 | 4 / 6 |
| Agentes que participaron | Supervisor y Rover Agent (este por un defecto ya corregido) | Supervisor | **Supervisor, Drone Agent y Rover Agent (×2)** |
| Clasificación final | `DEPENDENCY_IMPOSSIBLE` | `MISSION_NEEDS_CLARIFICATION` | **`PLANNING_COMPLETED_EXECUTION_PENDING_AUTHORIZATION`** |
| Criterios C0–C5 | Ninguno (C3 en una llamada que no debía ocurrir) | Ninguno | Todos |

**Por qué cambió.** Pasar de M4 a M4b corrigió la confusión entre planificar y ejecutar (*prompt* `/3`). Pasar de M4b a M4c-r1 corrigió la invención de campos: el contrato de procedencia exige una cita para cada hecho, no deja escribir datos no dichos, y un validador determinista lo comprueba. El aislamiento se cambió entre M4c y M4c-r1, pero eso no afecta al modelo, solo a si el piloto podía ejecutarse.

**Lo que no demuestra.**
- Generalización: el *prompt* `/4` se escribió después de ver M4b, aunque sus ejemplos negativos usan otra petición.
- Robustez estadística: es una sola ejecución a temperatura 0.
- Nada físico: no hubo SITL, ni vehículo, ni cámara real. La imagen y los eventos eran sintéticos.
