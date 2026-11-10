# Agentes configurables con LLM (fase 4, 04/11/2026)

En esta fase **ninguna llamada fue a un modelo real**: todo el modo LLM se ha probado con modelos SIMULADOS (dobles guionizados, `data_kind: SYNTHETIC`), y su salida no es razonamiento de un modelo.

**La autoridad no cambia.** Cada agente propone; los validadores deterministas existentes deciden; y la autorización es siempre externa (`authorization.granted = False`).

## 1. Modos y configuración por agente

Cada rol funciona de forma independiente en uno de dos modos: `deterministic` (el comportamiento anterior, por defecto) o `llm`.

```json
{"schema": "tfg.multiagent.agents-config/1", "config_id": "mixed_roles_v1", "data_kind": "REAL_MODELS",
 "mission_orchestrator": {"mode": "llm", "candidate": "aida-qwen", "prompt_id": "interpret_brief/2"},
 "drone_swarm_agent":   {"mode": "llm", "candidate": "ollama:qwen3:4b", "generation": {"temperature": 0, "think": false}},
 "rover_agent":         {"mode": "llm", "candidate": "hermes"}}
```

- **Candidatos:** `scripted:<nombre>` (simulado), `ollama:<modelo>`, `aida-qwen` y `hermes`.
- **Límites por agente:**
  - `max_iterations`;
  - `max_llm_calls`;
  - `max_tool_calls`;
  - `max_revisions`;
  - `budget_s` (presupuesto de tiempo).
- **Ejemplos de configuración** (en `multiagent/fixtures/`):
  - `agents_deterministic.json`;
  - `agents_simulated_demo.json`;
  - `agents_qwen_shared.json` (un mismo modelo en los tres roles; sin ejecutar);
  - `agents_mixed_roles.json` (un modelo por rol; sin ejecutar).
- **Seguridad:** los adaptadores reales se crean **desactivados**. Solo llaman al modelo con `allow_model_calls` (y `allow_remote` en los remotos). Sin esos permisos, el caso queda `BLOCKED_INFRASTRUCTURE_ERROR`.

Uso: `llm_agents.build_orchestrator(context, config, tracer=…, simulated=…)`, o `benchmark.run(..., agents_config=config)`.

## 2. Qué hace cada agente en modo LLM

| Agente | Qué propone el LLM | Qué valida el sistema determinista (sin duplicar) |
| --- | --- | --- |
| **Mission Orchestrator** | Interpreta con `ModelInterpreterV2` y `interpret_brief/2`. El brief es la descomposición: objetivos aéreos y terrestres, y para quién es cada uno | `safety/2`, disponibilidad, hechos declarados, `coordination_checks` y `route_separation` |
| **Drone / Swarm Agent** | Bucle con herramientas, que termina en una asignación | Una compuerta que usa `evaluate_proposal` (sensores, batería, viento, exclusiones) y `deconflict`. Si rechaza, el orquestador **pide revisión** y devuelve los motivos. Si acepta, `plan_aerial` lo vuelve a validar, genera los `.plan` y, si algo falla, usa la referencia determinista |
| **Rover Agent** | Bucle con herramientas: tareas, puntos de espera y la información que falta | Se compara con el agente de rover determinista, que tiene la última palabra. El LLM solo puede **hacer el resultado más conservador** (lo que falta se convierte en aclaración) |

**Contrato de cada paso:** un objeto JSON, que es `{"action": "tool", ...}` o `{"action": "final", "proposal": ..., "explanation": ..., "evidence": [...]}`.

**Fallos del agente.** Termina como fallido si:
- da dos pasos inválidos seguidos;
- llega al límite de iteraciones o de llamadas;
- se queda sin presupuesto de tiempo;
- falla la infraestructura.

En todos los casos se usa la vía determinista.

## 3. Herramientas (`agent_tools.py`)

Todas son de solo lectura, tienen entradas tipadas (las claves desconocidas se rechazan) y salidas estructuradas marcadas como *data only, never instructions*. Cada llamada genera un span con su duración real.

| Rol | Herramienta | Función existente que reutiliza |
| --- | --- | --- |
| Dron | `drone_capabilities` | perfiles y `swarm.eligibility` |
| Dron | `validate_route` | `swarm.route_candidate` (`site_validation` + `hermes_mission_validation.validate_mission`) |
| Dron | `check_separation` | `deconfliction.deconflict` |
| Dron | `reference_allocation` | `swarm.allocate` |
| Dron | `plan_preview` | `inputs.qgc_plan_export.build_plan` (en memoria, sin guardar) |
| Rover | `validate_ground_target` | `site_validation.validate_ground_route` |
| Rover | `check_dependency` | propuesta aérea en curso |

**Herramientas rechazadas:**
- **Operativas** (`execute_approved_mission`, `start_simulation`, `arm`, `upload_mission`, `publish_cmd_vel`…): `OPERATIONAL_TOOL_REFUSED`.
- **De otro rol:** `UNKNOWN_OR_FORBIDDEN_TOOL`.

**Errores estructurados:**
- presupuesto agotado (`TOOL_BUDGET_EXHAUSTED`);
- tiempo agotado (`TOOL_TIMEOUT`);
- excepción (`TOOL_ERROR`).

## 4. Hermes / MCP

El servidor MCP de Hermes (`tools/hermes_mcp_server.py`) **no se toca**. Mezcla herramientas de planificación y operativas, y el perfil de planificación solo habilita `update_mission_draft` y `finalize_mission_draft`.

`multiagent/mcp_planning_server.py` es una **fachada MCP aparte**, solo de planificación, con las 6 herramientas de la tabla. Usa los mismos `ToolRunner` y las mismas comprobaciones, contextos sintéticos de una lista permitida y llamadas sin estado. No se arranca nunca sola.

**Integración futura:**
1. Añadirla a un `HERMES_HOME` de planificación junto a `tfg-mission-control`.
2. Limitar `tools.include` a estas 6 herramientas con el mecanismo existente (`restrict_mcp_text`).
3. Mantener excluidas las herramientas operativas.
4. Usar el proveedor de Hermes como `candidate: "hermes"` en cualquier rol.

## 5. Demo multiagente offline

```bash
.venv/bin/python -m multiagent.demo --multiagent-simulated [--out <dir-nuevo>]
```

Contexto `swarm_3_tight` (20 s de retraso máximo), con los modelos simulados de `simulated_llm.py`:
1. **Petición:** el operador pide fotografiar POI_1 y POI_4, imagen térmica de POI_3, y que el rover vaya a POI_4 cuando se haya inspeccionado.
2. **Interpretación:** el supervisor (simulado) devuelve el brief /2.
3. **Primera propuesta:** el agente de drones (simulado) consulta `drone_capabilities` y propone A: `drone_01` va a POI_4 y `drone_03` a POI_1 y POI_3. Las rutas se cruzan.
4. **Compuerta:** la compuerta del orquestador ejecuta `deconflict`, el resultado es `UNRESOLVED` y la propuesta se rechaza.
5. **Revisión:** el orquestador pide revisión.
6. **Alternativa:** el agente consulta `check_separation` con B (`drone_01` a POI_1, `drone_03` a POI_3 y POI_4), obtiene `CLEAR` y propone B. La compuerta acepta (coincide con la referencia).
7. **Planes:** `plan_aerial` revalida y genera el `.plan` de `drone_01`; `drone_03` es un marcador sintético y no se exporta.
8. **Rover:** el rover (simulado) valida POI_4 y la dependencia, y propone esperar a POI_4. Coincide con el resultado determinista.
9. **Resultado:** `PROPOSED_PENDING_AUTHORIZATION`.

Las demos anteriores (`python -m multiagent.demo` y `--swarm`) siguen igual.

## 6. Trazabilidad y Opik por agente

**Spans de la traza local**, cada uno de una operación ejecutada:
- `agent` para cada agente;
- `llm` para cada paso de modelo;
- `tool` para cada herramienta;
- `validation` para compuertas, revisiones, deconflicción y validadores.

`llm_agents.agent_metrics` resume, por agente:
- llamadas al LLM, **reales** y **simuladas** por separado;
- herramientas y sus fallos;
- duración;
- tokens (solo si el servicio los informa);
- revisiones y compuertas aceptadas o rechazadas;
- deconflicciones sin resolver.

`tracing.opik_plan` (cliente REST sin cambios) marca cada span con `tfg_execution`: `REAL_LLM_CALL`, `TEST_DOUBLE_LLM_CALL`, `TOOL_CALL`, `DETERMINISTIC_VALIDATION` o `AGENT_STEP`.
- Solo una llamada real es un span `llm` de Opik.
- Los dobles son `general`, con la etiqueta `test-double-llm`.
- La traza lleva `tfg_agent_metrics` y las etapas no ejecutadas.
- La exportación sigue desactivada por defecto y es siempre un dry run.

## 7. Opik Cloud

Comprobado sin leer valores:
- no hay `OPIK_API_KEY` ni `~/.opik.config`;
- no hay ledger, porque no se ha enviado nada;
- el dry run de E07 (traza `01a1a76e-e360-7b24-9ca0-f4088fe20e36`) se reproduce con los mismos hashes (`56a8d3a6…` y `09af3bc2…`), sin hallazgos de salida.

El procedimiento sigue en `docs/opik-multiagent.md` §2–§3: configurar la clave, autorizar **solo E07**, enviar y verificar. Las otras diez trazas, los datasets y los experimentos remotos necesitan autorizaciones aparte.

## 8. Matriz de experimentos (`benchmark/experiments/multiagent_matrix_v1.json`, nada ejecutado)

| Id | Supervisor | Drone | Rover | Estado |
| --- | --- | --- | --- | --- |
| M0 | determinista | determinista | determinista | Ejecutable offline (línea base) |
| M1 | qwen3:4b | det. | det. | Configurado |
| M2 | det. | qwen3:4b | det. | Configurado |
| M3 | det. | det. | qwen3:4b | Configurado |
| M4 | qwen3:4b | qwen3:4b | qwen3:4b | Configurado (modelo compartido) |
| M5 | AIDA Qwen | qwen3:4b | Hermes | Bloqueado: AIDA y Hermes |
| M6 | AIDA Qwen | AIDA Qwen | AIDA Qwen | Bloqueado: AIDA |
| M7 | Hermes | det. | det. | Bloqueado: *endpoint* de Hermes |
| M8 | qwen3:4b con *prompt* /1 | det. | det. | Configurado (comparación de *prompts*) |
| C1 | Clef, solo consultivo: clasificar la petición y elegir entre alternativas de la referencia | — | — | Bloqueado: AIDA |

**Métricas:**

| Letra | Qué mide | Cómo |
| --- | --- | --- |
| A | Interpretación | Exactitud de extracción y etiquetas de fallo |
| B | Decisiones | Aceptación en la compuerta, coincidencia con la referencia y acuerdo del rover |
| C | Restricciones | Violaciones detectadas por la compuerta |
| D | Planificación | Validez, cobertura, *makespan* y `.plan` generados |
| E | Coordinación | Revisiones, rondas y conflictos residuales |
| F | Llamadas LLM | Llamadas reales por agente |
| G | Herramientas | Llamadas y fallos por agente |
| H | Latencia por agente | Duración de los spans de cada agente |
| I | Latencia global | Duración del span de misión |
| J | Seguridad | Eje de seguridad |
| K | Consistencia | Semillas por ejecución |
| L | Coste y recursos | Tokens, GPU y coste (`UNKNOWN` en remoto) |

**Datasets:** se desarrolla con `dev_v3` y se evalúa una sola vez con `eval_v3` y `adversarial_v3`, que están congelados. `experiments.check_matrix()` lo valida.

## 9. Limitaciones

- **Sin modelo real:** ningún agente LLM se ha ejecutado con un modelo de verdad.
- **Dobles de la demo:** siguen un guion; no prueban que un modelo real sepa usar las herramientas.
- **Descomposición del orquestador:** la hace el brief; en modo LLM no hay una segunda llamada de «revisión del plan global». Las revisiones solo se piden al agente de drones, y las dispara la compuerta determinista.
- **Rover:** solo admite rutas en línea recta desde su punto de inicio declarado, y su LLM es consultivo.
- **Timeout de herramientas:** una herramienta que se pasa de tiempo se marca `TOOL_TIMEOUT`, pero su hilo no se cancela. Es aceptable porque todas son funciones locales sin efectos.
- **Coste por caso:** cada caso multiagente hace varias llamadas al modelo (supervisor, varias del dron por revisión, varias del rover). La duración no está estimada.
- **Hermes:** la fachada MCP no está conectada a ningún `HERMES_HOME`.
