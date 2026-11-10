# Hermes, Ollama, MCP y observabilidad: reconstrucción técnica (08/11/2026)

**Fase de investigación. No se ha cambiado código ni configuración, no se ha arrancado Hermes, no se ha
cargado ningún modelo y no se ha hecho ninguna llamada remota.** Documento sin versionar, en el
worktree `Agentic_Drone_Mission_Control_multiagent` (rama `feature/multiagent-opik-evaluation`,
HEAD `9b30ce49f`, árbol limpio antes y después de esta investigación).

Base para dos documentos posteriores: el manual reproducible para Toni y la explicación de
arquitectura para Joel. Ninguno de los dos se escribe aquí.

## 0. Cómo leer este informe

Cada conclusión lleva una de estas etiquetas:

| Etiqueta | Significado |
| --- | --- |
| **[CÓDIGO]** | Verificada hoy leyendo el código o la configuración instalada |
| **[EVIDENCIA]** | Respaldada por una evidencia histórica (directorio sellado, registro local de Hermes o commit) |
| **[INFERIDO]** | Deducida de la configuración o del código, sin ejecución que la confirme |
| **[PENDIENTE]** | Necesita una ejecución real que todavía no se ha hecho |

Comprobaciones hechas hoy, todas sin efectos:

- lectura de `~/.hermes/config.yaml` (secciones `model`, `custom_providers`, `mcp_servers`; ninguna clave
  impresa), de los logs de Hermes y de `~/.hermes/state.db` **abierta en solo lectura** (`mode=ro`);
- lectura del código instalado de Hermes (`~/.hermes/hermes-agent`, commit `d923a5eb48`, release 0.22.2);
- `ollama --version` (0.34.2), `systemctl is-active ollama` (activo), manifiestos de modelos en disco
  (solo `qwen3:4b`), `nvidia-smi` (RTX 3070 Laptop, 8 GiB) y `free` (15 GiB);
- versiones de paquetes de la `.venv` del repositorio principal leídas con `importlib.metadata`;
- **pruebas offline** de la cadena Hermes/MCP/observabilidad desde este worktree, con la `.venv` del
  repositorio principal, sin caché ni bytecode:
  `test_hermes_mcp_server.py`, `test_hermes_mission_planning.py`, `test_hermes_mission_validation.py`,
  `test_hermes_observability_capture.py`, `test_hermes_capture_run.py`, `test_capture_summary.py`,
  `test_opik_export.py` y `test_planning_profile.py`: **368 pasadas, 3 omitidas** (datos locales no
  versionados).

No se ha tocado el worktree del rover. Lo que se cita de él se ha leído, no ejecutado.

---

## 1. Evolución LangChain → LangGraph → Hermes

### 1.1 Etapa LangChain (17–28/09/2026, repositorio aparte)

Repositorio `/home/joelm/TFG/langchain_agent_basics` (14 commits, `d43a195` → `72b4729`). Leído solo en lectura.

| Script | Qué hace | Modelo | Herramientas |
| --- | --- | --- | --- |
| `01_simple_agent.py` | `langchain.agents.create_agent` con una herramienta | `ChatOllama(model="qwen3:4b")` | `get_weather(city)` |
| `02_multi_agent.py` | Supervisor que usa dos agentes como herramientas | `qwen3:4b` | `ask_weather_agent`, `ask_flight_agent` (envoltorios `@tool` que llaman a `weather_agent.invoke` y `flight_agent.invoke`); `calculate_flight_time(distance_km, speed_kmh)` |
| `03_my_drone_mission_agent.py` | Agente de misión con estado y comprobaciones deterministas | `qwen3:4b`, `temperature=0`, `reasoning=False` | `calculate_flight_time`, `check_wind_safety`, `check_battery` |
| `04_langgraph_drone_mission_agent.py` | La misma lógica como grafo de estados | `qwen3:4b` | Las mismas tres |
| `05_langgraph_autonomous_mission_planner.py` | Grafo con plan versionado, evaluación y replanificación | `qwen3:4b` | Las mismas tres |

**[CÓDIGO]** El `README.md` de ese repositorio explica la instalación con una `OPENAI_API_KEY`, pero todo el
código usa `langchain_ollama.ChatOllama` con `qwen3:4b`; el cambio lo marca el commit `720fbc3` (22/09,
«The files working with Ollama_qwen3:4b»). El README describe el plan inicial, no el estado final.

**Cálculos del script 03 [CÓDIGO]** (`03_my_drone_mission_agent.py:49-300`):

- **Duración del vuelo** (`calculate_flight_time`): triángulo de viento.
  `Δ = wind_direction_from − flight_bearing`; viento de cara `H = W·cos Δ`; viento cruzado `C = W·sin Δ`.
  Si `|C| ≥ V` → `unsafe` («no puede compensar el viento cruzado»). Velocidad sobre el suelo
  `GS = −H + √(V² − C²)`; si `GS ≤ 0` → `unsafe`. Tiempo `t = d / GS · 60` minutos.
- **Viento** (`check_wind_safety`): `wind_speed ≤ max_safe_wind_speed`.
- **Batería** (`check_battery`): `requerida = t × consumo_%/min`; `restante = batería − requerida`;
  segura si `restante ≥ reserva`.

**Quién decide qué [CÓDIGO]:** en el script 03 **el LLM no elige herramientas**. Los parámetros se extraen
con expresiones regulares (`extract_direction`, `update_state`), las tres herramientas se llaman desde el
código con `.invoke({...})` (`analyse_mission`, líneas 648, 736 y 783) y el LLM solo responde preguntas
(`answer_question` → `llm.invoke`, línea 1188).

**Limitaciones de esa etapa [CÓDIGO + INFERIDO]:** un único tramo recto sin waypoints ni coordenadas;
extracción frágil por regex; estado solo en memoria; sin contrato de misión, sin exportación y sin
persistencia; un modelo de 4B local como único motor de lenguaje.

### 1.2 Incorporación de LangGraph

**En el repositorio de aprendizaje [CÓDIGO]:**

- `04_…py`: `DroneMissionState` (TypedDict) con parámetros, resultados de cada comprobación, `trace` e
  intención. Nodos `process_input`, `flight_check`, `wind_check`, `battery_check`, `final_report`,
  `show_trace`, `answer_question`. Rutas condicionales `route_after_input` (flight | wind | battery |
  report | trace | question), `route_after_flight`, `route_after_wind`. `InMemorySaver` con un
  `thread_id` fijo: el estado sobrevive entre turnos de la conversación. `get_changed_fields` y
  `get_missing_fields` permiten **recalcular solo lo afectado** y **pedir aclaraciones** cuando faltan datos.
- `05_…py`: añade `plan_version`, `mission_plan`, `failure_reasons`, `replan_*`; nodos `mission_planner`,
  `evaluate_plan` y `replanner`; `route_after_evaluation` decide entre `replan` y `report`. El replanificador
  es **determinista** (por ejemplo, calcula un límite de viento dinámico a partir del ángulo).

**Qué problema resolvió:** pasar de una función lineal a un flujo con estado explícito, rutas
condicionales y memoria por hilo: validación incremental, aclaraciones y replanificación como etapas
separadas y trazables.

**En el TFG (29–30/09/2026) [EVIDENCIA: commits `240b87c76` → `6e78668d9`]:**

- `36abbe69b` extrae la dinámica de vuelo: `tools/flight_dynamics.py` (`calculate_flight_time`, misma
  fórmula de viento cruzado).
- `fc003b17c` → `graph/mission_graph.py`: `parse_mission → validate_input → (checks | report)`,
  `flight_check → wind_check → battery_check → evaluate_plan → (replanner | final_report)`, con
  `InMemorySaver`.
- `141e9ece0`/`c9852e6ce`: el LLM pasa de no intervenir a **extraer parámetros con salida
  estructurada**: `agents/mission_parser.py:126-136`, `ChatOllama("qwen3:4b").with_structured_output(
  ExtractedMissionParameters, method="json_schema")`.
- `972f2b0da` → `models/mission_definition.py` (`MissionDefinition` v1) y cargador JSON; después
  geometría de waypoints, energía por tramo y `graph/waypoint_mission_graph.py`
  (`evaluate_waypoint_mission → (waypoint_replanner | waypoint_final_report)`).
- `6e78668d9` (30/09): `agents/mission_planner.py` (borrador con `ChatOllama`), adaptador QGroundControl
  y pruebas de regresión.

### 1.3 Evolución hacia Hermes y MCP (15/10/2026 en adelante)

**Hechos [EVIDENCIA]:**

1. 15/10, 09:22 UTC: Hermes Agent se clona de `github.com/NousResearch/hermes-agent` en
   `~/.hermes/hermes-agent` (`~/.hermes/logs/install.log`). Commit instalado hoy: `d923a5eb48`
   (release 0.22.2, 15/10).
2. 15/10, mismo día, en el repositorio: `2a45d083a` (envoltorio de validación determinista para Hermes),
   `fe808b39c` (exportación QGC), `c29065365`/`4eb8eb757` (herramientas MCP nativas).
3. **15/10, hora local del equipo 11:50–17:06: Hermes se usó primero con Ollama local (`qwen3:4b`).**
   Ver §2.2: las llamadas a herramientas fallaron.
4. **15/10, 17:20: cambio a `nous` / `poolside/laguna-s-2.1:free`.** Desde entonces todas las sesiones
   de Hermes usan ese proveedor (79 sesiones hasta el 31/10).
5. 16–20/10: herramientas MCP de simulación, gate de ejecución, executor, preflight virtual asíncrono,
   secuencias, reconciliación y retiro administrativo. El servidor crece hasta 27 herramientas.
6. 20–24/10: plugin de observabilidad, capturas reales, exportación a LangSmith y a Opik, y la línea
   H1 → H3b del escenario agrícola.

**Por qué Hermes y MCP.** No hay un registro escrito de la decisión de elegir Hermes frente a seguir con
un agente propio. Lo que sí consta:

- `documentation/development_log.md` (17/10): «Hermes interpreta el lenguaje natural y selecciona
  herramientas. Esta integración reutiliza los modelos y servicios de planificación **sin invocar un
  segundo LLM de Ollama**.» **[EVIDENCIA]**
- Las instrucciones del servidor (`tools/hermes_mcp_server.py:55-176`): «Mission safety decisions are
  deterministic and must never be invented or overridden by the language model.» **[CÓDIGO]**
- **[INFERIDO]** La decisión técnica fue separar dos capas: un agente conversacional genérico (Hermes:
  bucle de conversación, sesiones, cliente MCP, perfiles, plugins) y el código determinista del proyecto
  expuesto como herramientas por un protocolo estándar (MCP, stdio). Así el modelo puede cambiar sin
  tocar validación, exportación ni ejecución, y el LLM nunca toma la decisión de seguridad.

---

## 2. Papel histórico y actual de Ollama

### 2.1 Dónde se ha usado Ollama

| Uso | Dónde | Estado | Etiqueta |
| --- | --- | --- | --- |
| Scripts de aprendizaje | `langchain_agent_basics/0*.py` (`ChatOllama`) | Histórico | [CÓDIGO] |
| Menú opciones 1 y 3 (extracción y edición) | `agents/mission_parser.py`, `mission_planner.py`, `mission_editor.py` con `ChatOllama("qwen3:4b")` desde `main.py` | Vigente, solo desarrollo; excluido de las entregas a estudiantes | [CÓDIGO] |
| Hermes + Ollama (15/10) | Perfil `default`, proveedor `custom` → `http://localhost:11434/v1` | **Fallido en herramientas** (§2.2) | [EVIDENCIA, registro local] |
| Captura de observabilidad con Ollama (20–21/10) | Perfil `tfg-capture-test`, `custom` → `127.0.0.1:11434/v1`, contexto 8192 | **Bloqueada antes de inferencia**: Hermes exige 64 000 tokens | [EVIDENCIA] `evaluation/observability/hermes_capture_blocked_2026_10_20/` |
| Agentes multiagente con LLM real (04–07/11) | `multiagent/models.py` (`OllamaChatAdapter`, `POST /api/chat` nativo con `urllib`, `num_ctx=8192`, `format=json`) | Pilotos reales M1–M3, v2, v3, M4, M4b, M4c-r1 | [EVIDENCIA] `docs/multiagent-real-agents.md` |

### 2.2 Lo que ocurrió con Hermes + `qwen3:4b` el 15/10 [EVIDENCIA, `~/.hermes/state.db`]

Registro local de Hermes, consultado en solo lectura. **No es una evidencia sellada del repositorio.**

| Sesión (hora local) | Petición | Resultado |
| --- | --- | --- |
| 11:50 | «Reply exactly with: HERMES_OK» y después `pwd; git status` con el terminal | Chat correcto (`HERMES_OK`). Tres llamadas a herramientas, **todas fallidas**: el modelo llamó al puente `tool_call` con `{"command": …}` en lugar de `{"calls": [{name, arguments}]}`, y luego intentó `web_search` a través del puente |
| 16:00 | `pwd; git status` | Dos fallos iguales; termina escribiendo la llamada como texto |
| 16:28 | Igual | Dos fallos y «Operation interrupted: waiting for model response (105.3s elapsed)» |
| 17:00 | `pwd` | Turno no completado |
| 17:06 | `pwd` | Fallo del puente; el contenido muestra el razonamiento del modelo |

Consecuencias:

- **El transporte funcionó [EVIDENCIA]:** Ollama devolvió `tool_calls` con `finish_reason: tool_calls`
  por su endpoint compatible con OpenAI. No hay incompatibilidad de protocolo.
- **El modelo no supo usar el puente de herramientas diferidas de Hermes [EVIDENCIA + CÓDIGO]:** en Hermes
  0.22.x `tools.tool_search.enabled` vale `"auto"` por defecto (`hermes_cli/config_defaults.py:1991-2000`);
  las herramientas MCP y de plugins se sustituyen por tres puentes `tool_search` / `tool_describe` /
  `tool_call` (`tools/tool_search.py`, docstring). La configuración `default` no lo desactiva.
- **Nunca se llamó a una herramienta MCP del proyecto con `qwen3:4b`** [EVIDENCIA]: las peticiones eran
  de terminal y búsqueda web.
- Los avisos de `~/.hermes/logs/errors.log` muestran que el contexto fijado pasó de 32 768 (17:00) a
  65 536 (17:06) [EVIDENCIA]. **[INFERIDO]** El timeout de 105 s es coherente con un contexto grande que no
  cabe en la VRAM (§4.3), pero no se midió.

### 2.3 Estado actual de Ollama en el equipo de Joel [CÓDIGO]

- Ollama 0.34.2, servicio systemd activo, sin *drop-in* (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE`
  y `OLLAMA_CONTEXT_LENGTH` sin fijar; según el log del 21/10, contexto por defecto 4096).
- Un solo modelo: `qwen3:4b` (manifiesto del 22/09). Según `docs/hermes-observability-capture.md`, es
  «Qwen3 4B Thinking 2507», Q4_K_M, 2,33 GiB de pesos, ventana nativa 262 144, 36 capas y 8 cabezas KV de
  dimensión 128 [EVIDENCIA].
- GPU RTX 3070 Laptop, 8 GiB; RAM de WSL 15 GiB.
- `opik` **no** está instalado en la `.venv` (no lo necesita el exportador).

---

## 3. Hermes frente a Laguna

| | Hermes | Laguna |
| --- | --- | --- |
| Qué es | **Hermes Agent**, el agente de línea de órdenes de Nous Research: bucle conversacional, sesiones, cliente MCP, perfiles, plugins y hooks. **No es un modelo.** (Nous también publica modelos llamados Hermes; aquí no se usan) | El modelo `poolside/laguna-s-2.1:free` |
| Dónde corre | Local: `~/.hermes/hermes-agent`, lanzador `~/.local/bin/hermes`, su propio CPython 3.14 | Remoto: proveedor `nous`, `https://inference-api.nousresearch.com/v1`, autenticado con `hermes auth add nous` (OAuth, credenciales en `~/.hermes/auth.json`) |
| Cómo se cambia | — | `model.provider`, `model.base_url`, `model.default` del `config.yaml` del perfil, o `--provider/--model` |
| Qué depende de él | El servidor MCP no sabe qué modelo hay detrás | Nada del código del proyecto |

**[CÓDIGO]** `~/.hermes/config.yaml`: `provider: "nous"`, `default: "poolside/laguna-s-2.1:free"`,
`context_length: 65536`, `ollama_num_ctx: 65536`. Además conserva en `custom_providers` la entrada del
15/10 «TFG Ollama - Qwen3 4B» (`http://localhost:11434/v1`, `qwen3:4b`, `api_mode: chat_completions`).

**[EVIDENCIA]** Uso registrado en `session_model_usage`: Laguna/`nous`, 604 + 94 llamadas a la API entre
el 15/10 y el 31/10; `qwen3:4b`/`custom`, 11 + 4 llamadas, todas el 15/10.

**No confundir:** todo lo acreditado de H1, H3, H3b, el piloto de 10 casos, las capturas reales y los
envíos a Opik de Hermes se hizo con **Laguna vía `nous`**, no con Ollama.

---

## 4. Viabilidad de Hermes + Ollama

### 4.1 Lo que Hermes admite [CÓDIGO]

- Proveedor `custom` (alias `ollama`) con `base_url` compatible con OpenAI (comentarios de `model` en
  `config.yaml`, líneas 101-104).
- `ollama_num_ctx`: el proveedor `custom` lo envía como `extra_body.options.num_ctx` en cada petición
  (`plugins/model-providers/custom/__init__.py:61-62`, citado en `docs/hermes-observability-capture.md`).
- **Mínimo obligatorio de contexto:** `MINIMUM_CONTEXT_LENGTH = 64_000` (`agent/model_metadata.py:273`),
  aplicado en `agent_init._enforce_minimum_context`. Con un endpoint local, la ventana efectiva es
  `max(context_length, ollama_num_ctx)`. Solo `lmstudio` tiene excepción, y usarla sería falsear el
  proveedor (descartado en la documentación del 21/10).
- Filtro por servidor MCP: `mcp_servers.<srv>.tools.include` (lista blanca, prevalece), `.exclude`,
  `.resources`, `.prompts` (`tools/mcp_tool_registration.py:155-232`).
- `tools.tool_search.enabled: "off"` desactiva el puente y ofrece las herramientas directamente.
- `--toolsets <servidor>` limita lo que ofrece la sesión (usado por `deploy/planner/hermes_home.py:124`).

### 4.2 Respuestas a las preguntas de la tarea

| # | Pregunta | Respuesta | Etiqueta |
| --- | --- | --- | --- |
| 1 | Instalación y configuración | Clon de `NousResearch/hermes-agent` en `~/.hermes/hermes-agent`; config en `~/.hermes/config.yaml`; perfiles en `~/.hermes/profiles/<n>`. Para la imagen, `deploy/planner/hermes_source.py` fija el commit `d923a5eb` y su árbol. **El comando oficial de instalación no está registrado en el repositorio** | [EVIDENCIA] / [PENDIENTE] |
| 2 | Proveedor actual | `nous` | [CÓDIGO] |
| 3 | Configuración de Laguna | `model.default` + `provider: nous` + `base_url` de Nous; autenticación OAuth guardada por `hermes auth` | [CÓDIGO] |
| 4 | ¿Endpoint local de Ollama? | Sí, `custom` + `base_url: http://127.0.0.1:11434/v1`; ya se usó el 15/10 | [CÓDIGO] + [EVIDENCIA] |
| 5 | Modelos locales con herramientas | Ollama devuelve `tool_calls` para modelos con plantilla de herramientas (Qwen3 lo hizo). La capacidad real depende de la disciplina del modelo con esquemas grandes, no del protocolo | [EVIDENCIA] + [INFERIDO] |
| 6 | ¿`qwen3:4b` sirve? | **No demostrado.** Falló el 15/10 en la configuración más difícil (puente activo, todas las herramientas integradas). **No se ha probado** en la configuración restringida que funcionó con Laguna en H1 (Tool Search off, 2 herramientas, sin integradas) | [EVIDENCIA] / [PENDIENTE] |
| 7 | Contexto y memoria | ≥ 64 000 tokens obligatorios. H1 con Laguna usó 4 971 / 20 324 / 15 916 tokens de entrada en sus 3 llamadas (contexto declarado 65 536). Memoria: §4.3 | [CÓDIGO] + [EVIDENCIA] |
| 8 | Herramientas del servidor | 27 propias (§7). Hermes muestra 31 | [CÓDIGO] / [INFERIDO] |
| 9 | Incompatibilidades de protocolo | Ninguna observada en el transporte. Riesgos: que `/v1` de Ollama ignore `options.num_ctx` (hipótesis abierta desde el 21/10) y que el modelo «thinking» mezcle razonamiento y llamadas | [PENDIENTE] |
| 10 | Cambios mínimos | §17 | — |

### 4.3 Memoria para 64 k de contexto con `qwen3:4b` [EVIDENCIA: estimación, no medición]

Tomada de `docs/hermes-observability-capture.md` (21/10). Caché KV de 147 456 bytes/token en fp16:

| Contexto | KV f16 | KV q8_0 | KV q4_0 | Total con pesos (f16 / q8_0 / q4_0) |
| --- | --- | --- | --- | --- |
| 65 536 | 9,00 GiB | 4,78 GiB | 2,53 GiB | 11,3 / 7,1 / 4,9 GiB |

Con 8 GiB de VRAM: en f16 obliga a repartir capas entre GPU y CPU (lento); con flash attention y KV
q8_0 queda **al límite**. **[PENDIENTE]** medirlo con una carga controlada.

### 4.4 Veredicto

**Hermes + Ollama es técnicamente posible y el camino está identificado, pero no está demostrado para
el uso de herramientas MCP.** Hay que superar dos condiciones independientes, cada una con su prueba:

1. **Servir ≥ 64 k de contexto** en el hardware disponible (configuración de Ollama + medición).
2. **Que el modelo encadene correctamente `update_mission_draft` → `finalize_mission_draft`** con Tool
   Search desactivado y solo esas herramientas ofrecidas.

---

## 5. Modelo local recomendado y justificación

**Recomendación para el primer piloto: mantener `qwen3:4b`** (el instalado, digest `359d7dd4…`).

- Es el único modelo local disponible: no exige descargas en esta fase.
- Es el modelo de los pilotos multiagente reales, así que la comparación tiene continuidad.
- Por arquitectura, es el único de la familia Qwen3 cuyo contexto de 64 k tiene alguna posibilidad de
  caber en 8 GiB de VRAM, con KV q8_0 [INFERIDO de §4.3].
- Su fallo del 15/10 se explica en gran parte por el puente `tool_call` y por las ~25 herramientas
  integradas, que en la configuración propuesta no estarían [INFERIDO].

**Riesgos que el piloto debe medir [PENDIENTE]:** la variante instalada es *Thinking*, que emite
razonamiento (latencia y tokens); el esquema de `MissionPlanDraft` es grande, y las respuestas de
`update_mission_draft` ocupan unos 14 kB cada una.

**Alternativas, solo si el piloto falla, cada una con su descarga autorizada:**

- una variante *instruct* (sin razonamiento) del mismo Qwen3 4B, misma memoria. **El nombre exacto de la
  etiqueta en la biblioteca de Ollama está por verificar** [PENDIENTE];
- en un equipo con ≥ 16 GiB de VRAM, un Qwen3 mayor. Sus necesidades de KV deben comprobarse en su
  ficha antes de recomendarlo [PENDIENTE].

**No se cambia de modelo sin un piloto que lo justifique.**

---

## 6. Instalación y configuración actuales de Hermes

### 6.1 Perfil `default` (`~/.hermes/config.yaml`) [CÓDIGO]

| Clave | Valor | Riesgo para una demo |
| --- | --- | --- |
| `model.provider` / `default` | `nous` / `poolside/laguna-s-2.1:free` | Remoto con cuenta de Joel |
| `context_length`, `ollama_num_ctx` | 65 536 / 65 536 | — |
| `custom_providers` | «TFG Ollama - Qwen3 4B» | Seleccionarlo en este perfil expone **todas** las herramientas al modelo local |
| `mcp_servers.tfg-mission-control.command` | `/home/joelm/TFG/Agentic_Drone_Mission_Control/.venv/bin/python` | Apunta al **worktree del rover** |
| `…args` / `…env` | `-m tools.hermes_mcp_server` / `PYTHONPATH=` ese worktree | Importa el código **sin commit** del subsistema rover (rama `feature/rover-sitl-first-motion`; por ejemplo, `tools/simulation_control.py` usa `tools/simulation_lifecycle.py`, que está modificado) |
| `…tools` (filtro) | **Ausente** | Se ofrecen las 27 herramientas, incluidas `start_simulation`, `run_virtual_preflight`, `start_preflight_sequence` y `execute_approved_mission` |
| `tools.tool_search` | Ausente → `"auto"` | Puente `tool_call`, el que hizo fallar a `qwen3:4b` |
| `platform_toolsets` | Por defecto | Terminal, archivos, web, etc. disponibles |
| `approvals.mcp_reload_confirm` | `false` | — |

**Conclusión: el perfil `default` no sirve para la demo de Toni ni para un piloto con Ollama.**

### 6.2 Perfil `tfg-capture-test` [EVIDENCIA + CÓDIGO]

Creado el 20/10 con `hermes profile create --no-skills --no-alias`: `custom` → `127.0.0.1:11434/v1`,
`qwen3:4b`, `context_length: 8192` (por eso Hermes rechaza el turno), `platform_toolsets.cli: []`,
`mcp_servers: {}`, memoria/curator/actualizaciones desactivados, `plugins.enabled: []`.

### 6.3 Perfil de planificación de la imagen `deploy/planner/` [CÓDIGO + EVIDENCIA]

Es la configuración segura ya existente:

- `deploy/planner/hermes-config.base.yaml`: `nous`/Laguna, `platform_toolsets.cli: [tfg-mission-control]`,
  telemetría desactivada, servidor MCP en `/opt/tfg`.
- `deploy/planner/hermes_home.py`: añade `tools.include` con `PLANNING_TOOLS`
  (`update_mission_draft`, `finalize_mission_draft`; `observability/hermes_capture_run.py:301`), apaga
  recursos y prompts y desactiva Tool Search (`restrict_mcp_text`, `disable_tool_search_text`). Antes de
  cada arranque comprueba la configuración y **se niega** si cambió o si se pasa otro `--toolsets`.
- `prepare-test-home HOME URL` ya sabe convertir el home a `provider: custom` con un `base_url`
  (`hermes_home.py`, función `prepare_test_home`), pero solo para el doble de pruebas.
- Verificado con dobles 24/24 (imagen `2026.10.28`); ejecución real solo con `2026.10.27` y Laguna
  (`planning_container_real_2026_10_28_r2`).

---

## 7. Servidor MCP y herramientas registradas

### 7.1 Ficha [CÓDIGO]

| Aspecto | Valor |
| --- | --- |
| Entrada | `tools/hermes_mcp_server.py` (539 líneas, idéntico en este worktree y en el del subsistema rover; último commit `f258526ca`) |
| Arranque | `<repo>/.venv/bin/python -m tools.hermes_mcp_server`, desde la raíz o con `PYTHONPATH=<repo>` |
| Transporte | `mcp.run(transport="stdio")`: JSON-RPC por stdin/stdout del subproceso que lanza Hermes |
| Biblioteca | `mcp==2.3.0`, clase `mcp.server.MCPServer`, `name="tfg-mission-control"`, `version="0.3.0"`, instrucciones de servidor largas (líneas 55-176) |
| Registro | Decorador `@mcp.tool(..., structured_output=True)`; los argumentos se validan con las anotaciones Pydantic (`MissionPlanDraft`, `RelativeRouteRequest`, `InputAttribution`, `RevisionChanges`…) |
| Dependencias | `requirements.txt`: `langgraph`, `langchain-ollama`, `mcp==2.3.0`, `pydantic>=2,<3`, `PyYAML`; versiones en `constraints-verified.txt`. En la `.venv`: mcp 2.3.0, langgraph 1.2.12, pydantic 2.13.5 |
| Variables de entorno | Ninguna obligatoria para planificar; `PYTHONPATH` en la config de Hermes. `TFG_PLANNING_STORE` existe en el contenedor; localmente los borradores van a `<repo>/missions/generated/drafts/` (`tools/hermes_mission_planning.py:21`) |
| Salida estándar | Es el canal MCP: la validación redirige los `print` de los nodos LangGraph con `contextlib.redirect_stdout` (`tools/hermes_mission_validation.py:96-97`) |
| Errores | Argumentos fuera de esquema → error de herramienta MCP; `ValueError/OSError/KeyError/TypeError` del backend → `{"status": "ERROR"}`; conflicto de revisión → `{"status": "CONFLICT"}` (`planning/artifact_store.py:77-86`, decorador `boundary`) |
| Nombres en Hermes | `mcp__tfg_mission_control__<herramienta>` (`tools/mcp_tool_schema.py:172`); confirmado en la captura de H1 |
| Resultado en Hermes | El modelo recibe `{"result": "<JSON>"}` (descubierto al vincular H1) |

**Las 31 de la terminal [INFERIDO]:** 27 herramientas propias + 4 utilidades que Hermes genera por
servidor si este anuncia recursos y prompts (`list_resources`, `read_resource`, `list_prompts`,
`get_prompt`; `tools/mcp_tool_schema.py:200-204`). Se desactivan con `tools.resources: false` y
`tools.prompts: false`. **[PENDIENTE]** confirmarlo con el listado de Hermes.

### 7.2 Las 27 herramientas, clasificadas por efecto [CÓDIGO]

| Herramienta | Función | Efecto | ¿Demo? |
| --- | --- | --- | --- |
| `update_mission_draft` | Crear, completar o recuperar un borrador; genera la ruta si la geometría está completa | **Escritura** de `draft.json`, `draft_state.json`, `draft.lock` | **Sí** |
| `finalize_mission_draft` | Construir `MissionDefinition`, validar y exportar una vez | **Escritura** del snapshot, `mission.json`, `finalization.json` y `.plan` si hay AMSL | **Sí** |
| `get_mission_state` | Explicar un borrador, finalización, revisión o run | Solo lectura | Opcional |
| `generate_draft_route` | Envoltorio de `update_mission_draft` con `geometry_intent` | Escritura | No (redundante) |
| `validate_mission` | Validación determinista de un `mission.json` | Solo lectura | No (redundante) |
| `validate_and_export_qgc` | Validación + exportación | Escritura (`.plan`) | No (redundante) |
| `get_scenario_view` | Vista histórica de `agri_demo_001` | Solo lectura | No |
| `propose_mission_revision`, `build_mission_revision` | Propuesta y nueva revisión desde un preflight | Escritura | No |
| `get_revision_proposal` | Leer una propuesta | Solo lectura | No |
| `get_virtual_preflight`, `get_preflight_sequence`, `get_execution_reconciliation`, `get_legacy_sequence_retirement` | Consultas operativas | Solo lectura | No |
| `check_simulation_ready` | Readiness del backend | Lectura con **acceso a Docker/procesos** | No |
| `check_mission_execution_ready` | Gate de ejecución | Lectura de estado operativo | No |
| `inspect_execution_reconciliation`, `prepare_legacy_sequence_retirement` | Inspección y auditoría | Escritura de auditorías, lectura de Docker y telemetría | No |
| `start_simulation`, `restart_simulation`, `stop_simulation` | Ciclo de vida del simulador | **Arranque/parada de procesos y contenedores** | **Nunca** |
| `start_virtual_preflight`, `run_virtual_preflight`, `start_preflight_sequence` | Ensayos SITL | **Arman, despegan y mueven vehículos simulados** | **Nunca** |
| `execute_approved_mission` | Ejecución | **Acción sobre vehículos simulados** | **Nunca** |
| `apply_execution_reconciliation`, `apply_legacy_sequence_retirement` | Aplicar reconciliación o retiro | Escritura de reservas y restricciones (el retiro está deshabilitado) | **Nunca** |

Ninguna herramienta hace llamadas de red a Internet ni escribe trazas de observabilidad. La
observabilidad vive en Hermes (plugin), no en el servidor.

**Conjunto para la demo:** `update_mission_draft` + `finalize_mission_draft` (el de H1, verificado), y
como mucho `get_mission_state` (solo lectura).

**Límite importante [CÓDIGO]:** el filtro `tools.include` lo aplica **Hermes**. El proceso del servidor
sigue registrando las 27. Para una defensa en profundidad haría falta otra entrada que solo registre las
de planificación (§17, C4).

### 7.3 Servidor de planificación multiagente (no usado por Hermes) [CÓDIGO]

`multiagent/mcp_planning_server.py` (`tfg-multiagent-planning`): `drone_capabilities`, `validate_route`,
`check_separation`, `reference_allocation`, `plan_preview`, `rover_capabilities`, `validate_ground_target`,
`check_dependency`. Todas sin efectos. **No está configurado en ningún perfil de Hermes.**

---

## 8. Diagrama del recorrido de una petición

Petición de ejemplo: inspeccionar una parcela con un dron a 35 km/h, altura 5 m, viento 0 km/h y viento
máximo 30 km/h.

```mermaid
sequenceDiagram
    actor O as Operador
    participant H as Hermes Agent (bucle propio)
    participant L as LLM (hoy Laguna/nous; propuesto Ollama qwen3:4b)
    participant P as Plugin tfg-observability-capture
    participant S as Servidor MCP tfg-mission-control (stdio)
    participant B as Backend determinista
    participant G as LangGraph waypoint_mission_graph
    participant F as Disco (missions/generated/drafts)

    O->>H: petición en lenguaje natural
    H->>P: pre_api_request (nombres ofrecidos)
    H->>L: chat/completions + tools [update_mission_draft, finalize_mission_draft]
    L-->>H: tool_calls(update_mission_draft, args JSON)
    H->>P: post_api_request (tokens, duración)
    H->>S: tools/call (JSON-RPC por stdin)
    S->>B: validación Pydantic MissionPlanDraft → update_mission_draft()
    B->>F: draft.json + draft_state.json (revisión, procedencia)
    B-->>S: draft_id, status INCOMPLETE/COMPLETE, missing_fields
    S-->>H: structuredContent
    H->>P: post_tool_call (nombre, estado, ms)
    H->>L: resultado {"result": "<JSON>"}
    alt faltan datos
        L-->>H: texto pidiendo los campos pendientes
        H-->>O: pregunta
    else completo
        L-->>H: tool_calls(finalize_mission_draft)
        H->>S: tools/call
        S->>B: finalize_mission_draft()
        B->>B: build_mission_from_draft → MissionDefinition
        B->>F: snapshot/mission.json
        B->>G: validate_mission_file → evaluate_structured_mission → invoke
        G->>G: evaluate → (replanner) → report
        B->>B: export_validated_mission_plan (REFUSED sin AMSL)
        B->>F: finalization.json (flight_consent NOT_GRANTED)
        S-->>H: VALIDATED + validation{mission_status, execution_status, qgc_export}
        H->>L: resultado
        L-->>H: resumen en lenguaje natural
        H-->>O: respuesta
    end
```

---

## 9. Funciones y módulos implicados, paso a paso

| Paso | Qué ocurre | Archivo y función | Etiqueta |
| --- | --- | --- | --- |
| 1 | Hermes recibe la petición en su CLI y ensambla el prompt y la lista de herramientas | `~/.hermes/hermes-agent/agent/conversation_loop.py`; prefijo `mcp__…` en `tools/mcp_tool_schema.py:172`; filtro en `tools/mcp_tool_registration.py:219` | [CÓDIGO] |
| 2 | El modelo configurado interpreta | `model.*` del `config.yaml` del perfil; `api_mode: chat_completions` (captura H1) | [CÓDIGO] + [EVIDENCIA] |
| 3 | El modelo elige herramienta | Respuesta con `tool_calls` (`finish_reason: tool_calls`). Lo guían las descripciones de `@mcp.tool` y las `instructions` del servidor | [EVIDENCIA] |
| 4 | Transporte de argumentos | Hermes `model_tools.handle_function_call` → `tools/mcp_tool_handlers.py` → JSON-RPC por stdio | [CÓDIGO] |
| 5 | Construcción del borrador | `tools/hermes_mcp_server.py:285` `update_mission_draft` → `tools/hermes_mission_planning.py:176` (`_prepare`, `merge_relative_route_intent`, `generate_relative_route` en `planning/relative_routes.py:103`, `record_sources` en `planning/draft_provenance.py`, `_save`) | [CÓDIGO] |
| 6 | Contratos de datos | Entrada: `models/mission_plan_draft.py` (`MissionPlanDraft`, `PlannedWaypointDraft`), `RelativeRouteRequest`, `InputAttribution`. Salida: `models/mission_definition.py` (`MissionDefinition` y sus partes) | [CÓDIGO] |
| 7 | Parámetros que faltan | `planning/mission_plan_service.py:106` `get_missing_planning_fields`: 15 campos obligatorios, dirección del viento, ≥ 1 waypoint y coordenadas de cada uno → `missing_fields` y `INCOMPLETE` | [CÓDIGO] |
| 8 | Generación del plan | `finalize_mission_draft` (`tools/hermes_mission_planning.py:222`) → `build_mission_from_draft` (`planning/mission_plan_service.py:224`), que aplica los *compatibility defaults* (`drone_01`, `navigate`, regreso, failsafes) | [CÓDIGO] |
| 9 | Validación | `tools/hermes_mission_validation.py:142` `validate_mission_file` → `validate_mission` → `sessions/structured_mission_session.py:27` `evaluate_structured_mission` → `waypoint_mission_graph.invoke` | [CÓDIGO] |
| 10 | Viabilidad | `graph/waypoint_nodes.py` `evaluate_waypoint_mission_node` → `safety/mission_safety_analysis.py:15` `evaluate_mission_safety`: `tools/mission_energy_analysis.py:12` (por tramo, con `tools/flight_dynamics.py:4`, la fórmula de §1.1), `safety/wind_guard.py`, `safety/altitude_guard.py`; `NOT FEASIBLE` → `replanning/waypoint_mission_replanner.py`; informe en `reporting/waypoint_mission_report.py` | [CÓDIGO] |
| 11 | Exportación QGC | `sessions/structured_mission_session.py:65` `export_validated_mission_plan` → `inputs/qgc_plan_export.py` (`refusal_reasons`, `build_plan`, `verify_plan`). Sin AMSL del home → `REFUSED`, sin archivo | [CÓDIGO] |
| 12 | Resultado para Hermes | `status: VALIDATED`, `finalization_id`, `mission_path`, `mission_sha256`, `validation` (`mission_status`, `execution_status`, `failure_reasons`, `replan_*`, `qgc_export`, `qgc_plan_path`), `user_execution_authorization_required: true` | [CÓDIGO] |
| 13 | Lo que ve el operador | El texto que redacta el modelo en la TUI de Hermes. Los hechos están en `finalization.json` y `mission.json` | [CÓDIGO] |
| 14 | Observabilidad | Hooks del plugin (§11). El servidor no registra nada | [CÓDIGO] |

**Datos que salen del equipo con un proveedor remoto [EVIDENCIA, `docs/hermes-planning.md`]:** las
respuestas completas de las herramientas (unos 14 kB y 15 kB por par), incluidas **dos rutas absolutas**
(`mission_path`, `qgc_plan_path`) con el usuario local. Con Ollama no salen del equipo.

---

## 10. Relación exacta de LangGraph con Hermes

| Fase | Tecnología que la controla | Dónde |
| --- | --- | --- |
| Bucle conversacional, selección de herramientas, sesiones | **Hermes**, código propio. **No usa LangChain ni LangGraph** (solo aparecen en un script de un *skill* opcional) | `~/.hermes/hermes-agent/agent/` |
| Interpretación del lenguaje | **El LLM** configurado en Hermes | Proveedor |
| Llamadas a herramientas | **MCP** (SDK `mcp` 2.3.0, stdio) | `tools/hermes_mcp_server.py` |
| Borradores, rutas, procedencia, finalización | **Python determinista**, sin grafo | `tools/hermes_mission_planning.py`, `planning/*` |
| Validación de la misión | **LangGraph** `waypoint_mission_graph` (3 nodos, sin checkpointer), dentro de la llamada MCP | `graph/waypoint_mission_graph.py` |
| Cálculos de seguridad | **Python determinista** | `safety/*`, `tools/flight_dynamics.py`, `tools/mission_energy_analysis.py` |
| Exportación QGC | **Python determinista** | `inputs/qgc_plan_export.py` |
| Preflight virtual (no en la demo) | **LangGraph** `virtual_preflight_graph` por misión | `graph/virtual_preflight_graph.py` |
| Flujo del escenario agrícola (no MCP) | **LangGraph** `agri_scenario_graph` (8 nodos) desde `main.py` opción 5 | `graph/agri_scenario_graph.py` |
| Menú 1 y 3 (no Hermes) | **LangChain** `ChatOllama` + LangGraph `mission_graph` | `agents/*`, `graph/mission_graph.py` |
| Orquestador multiagente (no Hermes) | **LangGraph** (`interpret → screen → decompose → drone_agent → rover_agent → assemble → finalize`) con su **propio** adaptador Ollama (`/api/chat` vía `urllib`, sin LangChain) | `multiagent/orchestrator.py`, `multiagent/models.py`, `multiagent/llm_agents.py` |
| Hermes en el multiagente | Solo su **contrato**: `hermes_mission_adapter` reconstruye `MissionDefinition` y llama a la misma validación. **No arranca Hermes** | `multiagent/hermes_mission_adapter.py` |

**Resumen para la memoria:** Hermes es el bucle conversacional; LangGraph aparece **dentro** de una
herramienta MCP, como motor de la validación por etapas. LangGraph nunca orquesta a Hermes y Hermes
nunca ve el grafo.

---

## 11. Arquitectura de observabilidad

### 11.1 Dos líneas separadas

**A. Línea Hermes** (`observability/`):

1. **Captura**: plugin `observability/hermes_capture/` (`plugin.yaml`, `__init__.py`, `capture.py`,
   tres esquemas). Hooks de observación de Hermes [CÓDIGO]:
   - `post_api_request` → evento `llm_call`: proveedor, modelo, `finish_reason`, `api_duration_s` y
     epochs, `first_chunk_offset_s`, `context_length`, `requested_tool_names`, `usage` con
     `{value, status}`;
   - `api_request_error` → `llm_error` (`status_code`, `retry_count`, `retryable`, `reason`);
   - `post_tool_call` → `tool_call`: nombre, estado, `error_type`, `duration_ms_received/measured`;
   - `pre_api_request` → registro aparte `tool_offer` con los **nombres** de las herramientas ofrecidas;
   - opcional (`TFG_OBSERVABILITY_RESULT_EXPECTATION`): comparación de punteros JSON del resultado, sin
     guardar valores.
2. **Activación doble** [CÓDIGO]: el plugin en `<home>/plugins/tfg-observability-capture/` y en
   `plugins.enabled`, **y** `TFG_OBSERVABILITY_CAPTURE=1` + `TFG_OBSERVABILITY_DIR=<ruta absoluta>`
   (opcionales `TFG_OBSERVABILITY_RUN_ID` y `…_CASE_ID`).
3. **Almacenamiento local**: `hermes-events-YYYY-MM-DD.jsonl`, `hermes-tool-offers-…jsonl`,
   `capture-provenance-<sink>.json`; directorio 0700, archivos 0600, `O_APPEND|O_NOFOLLOW`.
4. **Orquestación**: `observability/hermes_capture_run.py` (`capture` = comprobación previa offline;
   `capture --execute` = una ejecución, con activación temporal del plugin y restauración del config por
   comparación de bytes; `review` = valida y copia a una evidencia nueva; `opik-dry-run`).
5. **Resumen local**: `python -m observability.capture_summary <jsonl…> [--provenance captured]`.
6. **Exportación**: `observability/opik_export.py` (y `langsmith_export.py`), **dry-run por defecto**.

**B. Línea multiagente** (`multiagent/`): `tracing.py` escribe una traza local JSONL con un span por paso
(`agent | llm | tool | validation`, modelo, duración `perf_counter`, entradas y salidas redactadas);
`opik_bridge.py` la importa a Opik con ledger y verificación; `opik_phase2.py` genera
`local_preview.md`/`.json` sin subir nada.

### 11.2 Respuestas a las 13 preguntas

| # | Pregunta | Línea Hermes | Etiqueta |
| --- | --- | --- | --- |
| 1 | Dónde se crean las trazas | En los hooks del plugin, dentro del proceso de Hermes | [CÓDIGO] |
| 2 | Eventos | `llm_call`, `llm_error`, `tool_call`, `tool_offer`, `tool-result-check` | [CÓDIGO] |
| 3 | Asociación con una misión | **No directa**, por diseño: solo `run_id`/`case_id` y referencias seudónimas (`session_ref`, `turn_ref`, `api_request_ref`: SHA-256 truncado sin sal). La unión con la misión la hace después `bind-h1`, desde la exportación de la sesión de Hermes | [CÓDIGO] |
| 4 | Llamadas al LLM | `llm_call` por `post_api_request` | [CÓDIGO] + [EVIDENCIA H1] |
| 5 | Llamadas MCP | `tool_call` con el nombre `mcp__…`, estado y ms medidos por Hermes. **Sin argumentos ni resultados** | [CÓDIGO] |
| 6 | Validaciones | **No como eventos.** El veredicto queda en `finalization.json`; la comprobación opcional de resultado solo dice `match/mismatch/absent`. En la línea multiagente sí hay spans `validation` | [CÓDIGO] |
| 7 | Duraciones | Llamada a la API con reloj de pared (incluye reintentos); primer chunk; duración de la herramienta (`monotonic`, ms). No hay duración interna de la validación | [CÓDIGO] |
| 8 | Qué se guarda | Solo metadatos. Se descartan prompts, mensajes, argumentos, resultados, `base_url`, ids en claro | [CÓDIGO] |
| 9 | Credenciales y datos sensibles | Lista blanca de campos; redacción de textos con aspecto de secreto o URL; el exportador solo lee `OPIK_API_KEY` con `--send` y la recibe ya leída; el dry-run no lee el entorno | [CÓDIGO] |
| 10 | Transformación a Opik | `opik_export`: `TraceBatch_Write`/`SpanBatch_Write`, spans `llm` con los epochs de Hermes, herramientas sin intervalo como `metadata.tfg_point_events`, ids UUIDv7 deterministas, todo lo demás en `metadata.tfg_*` | [CÓDIGO] |
| 11 | Envío | `POST /v1/private/traces/batch` y `/spans/batch`, un intento, registro JSONL obligatorio (`--record`) | [CÓDIGO] |
| 12 | Visualización | En Opik Cloud (UI del proyecto). **Localmente no hay visor gráfico:** `capture_summary` (texto/JSON) y el JSON del dry-run | [CÓDIGO] |
| 13 | Experimentos históricos | §12 | [EVIDENCIA] |

**Ejemplo real (H1, 24/10, Laguna) [EVIDENCIA, `evaluation/observability/agri_planning_h1_nous_2026_10_24/capture/`]:**
3 `llm_call` (29,7 s, 9,4 s, 4,4 s; 4 971 / 20 324 / 15 916 tokens de entrada) y 4 `tool_call`
(`update_mission_draft` 383 ms y 26 ms; `finalize_mission_draft` 58 ms y 46 ms), todos `ok`.

---

## 12. Estado real de Opik

| Fecha | Qué | Resultado | Evidencia | Tipo |
| --- | --- | --- | --- | --- |
| 21/10 | Primer envío sintético | **HTTP 400**, causa no conocida (cuerpo descartado) | `opik_first_synthetic_send_2026_10_21` | FALLIDO |
| 21/10 | Diagnóstico de un batch | 204, visible | `opik_diag_single_batch_send_2026_10_21` | Diagnóstico |
| 21/10 | Captura real de Hermes (Laguna) | 204 + 204, traza y span confirmados por Joel | `opik_hermes_real_send_2026_10_21` | **REAL · Hermes** |
| 22/10 | Segunda captura real | 204 + 204 | `opik_hermes_real_send_2026_10_22` | **REAL · Hermes** |
| 22/10 | Ensayo MCP con aislamiento directo | 204 + 204 (2 spans) | `opik_hermes_mcp_tool_trial_direct_send_2026_10_22` | **REAL · Hermes** |
| 22/10 | Dashboard «TFG — Hermes» | Creado con Ollie; **El sistema multiagente no lo ha verificado** | `opik_dashboard_tfg_hermes_2026_10_22` | Declarado |
| 24/10 | H1 y H3 (`acceptance:NOT_VALIDATED`) | 204 + 204 cada uno | `opik_h4_agri_h1_send_2026_10_24`, `…h3…` | **REAL · Hermes** |
| 04/11 | E07 multiagente | 204/204, lectura 200, 12 spans, `VERIFIED_PRESENT` | `docs/opik-op1.md`, ledger | **REAL · multiagente** |
| 06/11 | OP-1 (10 trazas Qwen) | **HTTP 400** («ventana UUIDv7» inferida), nada almacenado | `op1_2026-11-06/` | FALLIDO |
| — | OP-1b, OP-2, OP-3, fase 2 (métricas, experimentos, dashboard de 66 widgets) | **Preparado, no enviado** | `docs/opik-op1.md`, `docs/opik-fase2.md` | Sin enviar |

Todos los envíos reales de Hermes son de **Laguna/`nous`**. **Ninguna traza de Hermes con Ollama existe.**

**Limitaciones para la demo [CÓDIGO]:**

- Opik rechaza ids UUIDv7 cuya marca de tiempo está fuera de una ventana de unas 24 h; el exportador de
  Hermes deriva la marca del inicio del evento, así que **hay que enviar el mismo día** de la captura
  (la protección explícita solo está en la línea multiagente) [INFERIDO a partir de `docs/opik-op1.md`].
- `validate_endpoint` exige `https` (`observability/opik_export.py:295-305`) y `--send` exige clave:
  **no se puede enviar a un Opik autoalojado en `http://localhost`** sin cambiar el exportador.
- `multiagent/opik_bridge.py` solo admite `joowww/tfg-multiagent-benchmarks`.

### Opción A — modelo local + trazas locales (sin credenciales)

**Viable con el código actual**, salvo la condición de contexto y modelo (§4.4) [INFERIDO]:
captura con el plugin → `capture_summary` → `opik_export` en dry-run (muestra exactamente lo que se
enviaría, sin red). **Brecha:** no hay visualización gráfica local (§17, C7).

### Opción B — modelo local + publicación en Opik Cloud

Viable con el exportador actual, cuenta, `OPIK_API_KEY` y **autorización explícita de cada envío**,
enviando dentro de la ventana de 24 h. Opik autoalojado exige el cambio C8.

---

## 13. Dependencias mínimas de la demo

| Componente | Versión verificada | Fuente | Etiqueta |
| --- | --- | --- | --- |
| Python del proyecto | 3.12.3 | `.venv` del repositorio principal | [CÓDIGO] |
| `mcp` | 2.3.0 | `requirements.txt` (fijada) | [CÓDIGO] |
| `pydantic` | 2.13.5 | `constraints-verified.txt` | [CÓDIGO] |
| `langgraph` | 1.2.12 | idem | [CÓDIGO] |
| `PyYAML` | 6.0.3 | idem (para el ejecutor de capturas) | [CÓDIGO] |
| `jsonschema` (+ `rfc3339-validator`) | 4.26.0 | `requirements-observability.txt` (validación de la captura) | [CÓDIGO] |
| `langchain-ollama` | 1.1.0 | Solo menú 1 y 3; **no** en el recorrido Hermes, pero se instala con `requirements.txt` | [CÓDIGO] |
| Hermes Agent | `d923a5eb48` (0.22.2), su propio CPython 3.14 y `uv` | `~/.hermes/hermes-agent`; `VERIFIED_HERMES_COMMIT` | [CÓDIGO] |
| Ollama | 0.34.2 | servicio local | [CÓDIGO] |
| Modelo | `qwen3:4b` (Q4_K_M, 2,5 GB) | único instalado | [CÓDIGO] |
| Opik SDK | **No necesario** | el exportador habla REST | [CÓDIGO] |

**Fijar Hermes es importante:** el plugin, el ejecutor de capturas y sus pruebas de contrato están
verificados contra `d923a5eb`. Una instalación nueva de Toni traería otra versión [PENDIENTE: comprobar
qué cambia].

---

## 14. Propuesta de demo reproducible

Recorrido: `Operador → Hermes → Ollama/qwen3:4b → MCP (2 herramientas) → planificación → validación
LangGraph → resultado → captura local → resumen + dry-run Opik`.

**Diseño propuesto (no implementado):**

1. **Checkout limpio y propio** del repositorio (nunca el worktree del rover), con su `.venv`.
2. **Ollama** sirviendo `qwen3:4b` con ≥ 64 k de contexto. Opciones, por orden de preferencia:
   modelo derivado con `PARAMETER num_ctx 65536` (afecta solo a ese nombre de modelo), o variables del
   servicio (`OLLAMA_CONTEXT_LENGTH`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`), que afectan
   a todo el equipo [PENDIENTE: sintaxis y efecto a verificar en esa versión].
3. **Perfil de Hermes nuevo** (por ejemplo `tfg-demo-local`), creado sin clonar el `default`:
   ```yaml
   # PROPUESTA, no aplicada
   model:
     provider: custom
     base_url: http://127.0.0.1:11434/v1
     default: qwen3:4b            # o el modelo derivado de 64 k
     context_length: 65536
     ollama_num_ctx: 65536
   platform_toolsets:
     cli: [tfg-mission-control]
   tools:
     tool_search:
       enabled: "off"
   mcp_servers:
     tfg-mission-control:
       command: <REPO>/.venv/bin/python
       args: [-m, tools.hermes_mcp_server]
       env: {PYTHONPATH: <REPO>}
       enabled: true
       tools:
         include: [update_mission_draft, finalize_mission_draft]
         resources: false
         prompts: false
   plugins:
     enabled: [tfg-observability-capture]
   telemetry:
     shared_metrics: {enabled: false, send: false}
   ```
4. Plugin copiado a `<perfil>/plugins/tfg-observability-capture/`; variables `TFG_OBSERVABILITY_*`
   apuntando a un directorio privado nuevo fuera del repositorio.
5. Arranque con `--toolsets tfg-mission-control`.
6. Misión de prueba en **dos turnos** (uno incompleto para mostrar la aclaración, otro que completa), con
   los datos explícitos del ejemplo de `docs/hermes-planning.md` («Prueba desde Hermes») o de H0.
7. Consulta de resultados: `finalization.json`, `mission.json`, `validation.mission_status`, y
   `qgc_export: REFUSED` explicado como comportamiento correcto (falta la AMSL). Para obtener un `.plan`,
   el paso posterior existente `python -m tools.scenario_package package-finalized` con emplazamiento y
   flota [EVIDENCIA: `hermes_finalized_package_two_drones_2026_10_30`].
8. Observabilidad: `capture_summary` y `opik_export` en dry-run (opción A).

**¿Lo permite el código actual?** Casi: todo lo anterior es configuración, **salvo** la automatización
de la captura con otro proveedor y otro home (C3) y el visor local (C7). La incógnita principal es el
modelo (§4.4).

---

## 15. Comandos encontrados y estado de verificación

Directorio: `<REPO>` = raíz del checkout. «Efecto» resume lo que cambia.

| Comando | Dir. | Qué hace | Efecto | Estado |
| --- | --- | --- | --- | --- |
| `ollama --version` | cualquiera | Versión | Ninguno | **Ejecutado hoy**: 0.34.2 |
| `ollama list` | cualquiera | Modelos instalados | Consulta al servicio | Documentado, no ejecutado hoy |
| `ollama pull qwen3:4b` | cualquiera | Descarga el modelo | **Red y disco (2,5 GB)** | Ejecutado en el equipo de Joel (22/09); en contenedor **nunca** |
| `docker compose -f deploy/compose.yaml --profile planning up -d ollama` | `<REPO>` | Ollama en contenedor | Arranca un contenedor | **No ejecutado** |
| `hermes profile create <n> --no-skills --no-alias` | cualquiera | Perfil nuevo | Crea `~/.hermes/profiles/<n>` | Ejecutado 20/10 |
| `hermes plugins list` | cualquiera | Plugins del perfil | Ninguno | Ejecutado 20/10 |
| `hermes -z "<prompt>" --toolsets tfg-mission-control` | `<REPO>` | Un turno restringido | Llamada al modelo; escrituras MCP | Formas usadas el 20/10 (`-z`) y en `hermes_home.py` (`--toolsets`); **no con Ollama + MCP** |
| `hermes auth add nous` | cualquiera | Login de Nous | Credenciales en el home | Ejecutado por Joel; para la demo local **no hace falta** |
| `hermes sessions export` | cualquiera | Exporta la sesión | Ninguno | Lo usa `bind-h1` |
| `.venv/bin/python -m tools.hermes_mcp_server` | `<REPO>` | Servidor stdio (lo lanza Hermes; a mano se queda esperando JSON-RPC) | Ninguno hasta recibir llamadas | Documentado y usado por Hermes |
| `.venv/bin/python -m pytest -q tests/test_hermes_*.py tests/test_capture_summary.py tests/test_opik_export.py tests/test_planning_profile.py` | `<REPO>` | Pruebas offline | Ninguno | **Ejecutado hoy: 368 OK, 3 omitidas** |
| `.venv/bin/python -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case agri-planning-h1` | `<REPO>` | Comprobación previa offline | Ninguno | Documentado (`ok: true` antes de H1); el caso está marcado como ejecutado |
| `… capture … --execute --timeout 300` | `<REPO>` | Una ejecución con captura | Llamada al modelo, escrituras, config temporal | Ejecutado 24/10 con Laguna |
| `… review --mcp-tool-trial --trial-case … --private-dir … --evidence-dir …` | `<REPO>` | Revisión y evidencia nueva | Escribe la evidencia | Ejecutado 24/10 |
| `.venv/bin/python -m observability.capture_summary <jsonl> --provenance captured` | `<REPO>` | Resumen local | Ninguno | Probado offline (tests) |
| `.venv/bin/python -m observability.opik_export <jsonl> --project <p> --provenance captured` | `<REPO>` | Dry-run Opik | Ninguno (sin red, sin escrituras) | Probado offline; usado antes de cada envío |
| `… opik_export … --send --record <nuevo>.jsonl --workspace <w>` | `<REPO>` | Envío | **Red; publica** | Ejecutado 21/10, 22/10 y 24/10 con autorización |
| `.venv/bin/python -m reporting.agri_scenario_summary bind-h1 --usage-file …` | `<REPO>` | Vincula H1 | Escribe el registro | Ejecutado 24/10 |
| `python -m tools.scenario_package package-finalized …` | `<REPO>` | Finalizaciones → `.plan` | Escribe paquetes | Verificado 30/10 (sintético sobre misiones reales) |
| `docker compose -f deploy/compose.yaml run --rm hermes` (+ `hermes_home.py login/status/run`) | `<REPO>` | Hermes en contenedor | Contenedor, login | 24/24 con dobles; real solo con `2026.10.27` y Laguna |

**Pendientes de verificar** (no se deben poner en el manual sin probarlos): el instalador oficial de
Hermes para una máquina nueva; `hermes mcp list` o equivalente para contar herramientas; la sintaxis
exacta para crear un modelo derivado de 64 k en Ollama 0.34.2; la cancelación limpia con Ctrl+C.

---

## 16. Obstáculos actuales

| # | Obstáculo | Etiqueta |
| --- | --- | --- |
| O1 | `qwen3:4b` no ha demostrado usar herramientas en Hermes (falló el 15/10) | [EVIDENCIA] |
| O2 | Hermes exige ≥ 64 k de contexto; Ollama sirve 4 096 por defecto; no está verificado que `/v1` respete `options.num_ctx` | [CÓDIGO] + [PENDIENTE] |
| O3 | 64 k con `qwen3:4b` en 8 GiB de VRAM está al límite (estimación) | [EVIDENCIA] |
| O4 | El perfil `default` expone las 27 (+4) herramientas, incluidas las de simulación y ejecución, con el puente activo y las herramientas integradas | [CÓDIGO] |
| O5 | El servidor MCP del perfil `default` ejecuta el worktree del rover, con cambios sin commit | [CÓDIGO] |
| O6 | El filtro de herramientas es del cliente; el servidor no tiene modo «solo planificación» | [CÓDIGO] |
| O7 | El ejecutor de capturas solo tiene casos cerrados y fijados a hashes de fuentes; no hay un caso para la demo | [CÓDIGO] |
| O8 | Sin visor local de trazas | [CÓDIGO] |
| O9 | El exportador Opik no admite `http` ni Opik sin clave (autoalojado) | [CÓDIGO] |
| O10 | Rutas absolutas en `~/.hermes/config.yaml` y en las respuestas de finalización | [CÓDIGO] |
| O11 | La exportación QGC sale `REFUSED` sin AMSL; hay que explicarlo o encadenar `package-finalized` | [CÓDIGO] |
| O12 | El modelo instalado es la variante *Thinking* | [EVIDENCIA] |
| O13 | El registro del 15/10 solo está en `~/.hermes/state.db`, que cambia con el uso | [CÓDIGO] |
| O14 | Imagen `planner`: Hermes solo en la red `provider` y home base fijado a Laguna | [CÓDIGO] |

---

## 17. Cambios mínimos necesarios (propuestos, no implementados)

| Id | Brecha | Cambio mínimo | Tipo |
| --- | --- | --- | --- |
| C1 | O2, O3 | Modelo derivado con `num_ctx 65536` (o variables del servicio) + medición de VRAM con `/api/ps` | Configuración de Ollama; autorización aparte |
| C2 | O4, O5 | Perfil nuevo de Hermes (§14), servidor desde un checkout propio | Solo configuración |
| C3 | O7 | Caso nuevo en `observability/hermes_capture_run.py` (por ejemplo `local-planning-demo`) con `PLANNING_TOOLS`, `--hermes-home` del perfil nuevo, sin fijar proveedor y sin cerrar la versión de fuentes de H1 | Código pequeño, con pruebas |
| C4 | O6 | Entrada `tools/hermes_mcp_planning_server.py` que registre solo `update_mission_draft`, `finalize_mission_draft` y `get_mission_state` reutilizando las mismas funciones (defensa en profundidad) | Código pequeño, con pruebas que comparen esquemas |
| C5 | O1, O12 | Piloto único registrado de antemano: 2 turnos, criterio `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS` + finalización `VALIDATED`; si falla, decidir el modelo con datos | Ejecución autorizada |
| C6 | O13 | Sellar en una evidencia nueva el extracto del 15/10 (metadatos, sin contenido personal) | Evidencia, con autorización |
| C7 | O8 | Visor local estático (HTML o Markdown) generado desde la captura y `capture_summary`, sin red | Código pequeño |
| C8 | O9 | Permitir `http://localhost`/`127.0.0.1` y clave opcional solo para un endpoint de bucle local | Código pequeño; solo si se quiere Opik autoalojado |
| C9 | O14 | `hermes_home.py prepare-local-home HOME URL` (variante real de `prepare-test-home`) y red compartida con `ollama` | Código pequeño; solo para la vía en contenedor |
| C10 | O10 | Plantilla de perfil con `<REPO>` sustituido por el instalador del manual | Documentación |

Lo imprescindible para la **opción A** en el equipo de Joel: C1, C2 y C5 (más C3 si se quiere la captura
automatizada y revisada). C4 y C7 mejoran la defensa y la presentación.

---

## 18. Comprobaciones de seguridad para la demo

Antes de arrancar:

1. El perfil que se usa **no es** `default` (`hermes` muestra el perfil y el modelo al arrancar).
2. Su `config.yaml` tiene `tools.include` con solo las herramientas de planificación,
   `tools.tool_search.enabled: "off"`, `resources/prompts: false` y `platform_toolsets.cli:
   [tfg-mission-control]`.
3. El servidor MCP apunta a un checkout propio y limpio (`git status` vacío), no al del subsistema rover.
4. No hay simulador en marcha ni contenedores del proyecto (comprobación de solo lectura); ninguna
   herramienta ofrecida puede arrancarlos, pero no se depende de eso.
5. Ollama escucha solo en `127.0.0.1:11434`.
6. No hay `OPIK_API_KEY` en el entorno ni `~/.opik.config` si la demo es la opción A.
7. El directorio de captura es nuevo, privado (0700) y está fuera del repositorio.

Después de la primera petición:

8. `hermes-tool-offers-*.jsonl` solo contiene `mcp__tfg_mission_control__update_mission_draft` y
   `…finalize_mission_draft` (lo que `review` llama `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`).
9. `finalization.json` dice `flight_consent: NOT_GRANTED`.

---

## 19. Qué falta para escribir el manual final de Toni

1. **Resultado del piloto C5** con el modelo elegido: sin él, el manual no puede prometer la demo.
2. **Medición de memoria y latencia** (C1) para fijar los requisitos de hardware.
3. **El sistema operativo y el hardware de Toni** (GPU, VRAM, RAM; Windows + WSL2, Linux o macOS).
4. **Instalador oficial de Hermes** y decisión de fijarlo a `d923a5eb` (o de revalidar el plugin contra
   una versión nueva).
5. **Elección de vía:** instalación nativa (más sencilla para la demo) o contenedor `planner` (más
   reproducible, necesita C9).
6. **Visor de trazas** (C7) si la observabilidad tiene que verse en pantalla sin Opik Cloud.
7. **Prueba en un equipo limpio** siguiendo el manual paso a paso.

**Estructura prevista del manual** (cada paso con directorio, propósito, requisitos, efectos, salida
esperada y comprobación): requisitos de hardware → sistemas operativos y WSL2 → Git → Python y `.venv` →
`pip install -r requirements.txt -r requirements-observability.txt -c constraints-verified.txt` →
pruebas offline → instalación de Ollama → modelo y contexto → verificación del modelo → instalación de
Hermes → perfil de demo → servidor MCP → plugin y variables de observabilidad → arranque → misión de
prueba (dos turnos) → validación → resultados en disco → trazas (`capture_summary`, dry-run) → cierre
(Ctrl+C, `ollama stop <modelo>`) → errores habituales (contexto < 64 k, `tool_call requires 'calls'`,
servidor MCP que no arranca por `PYTHONPATH`, `REFUSED` sin AMSL, `CONFLICT` por `expected_revision`).

**Estado de cada paso hoy:** Git, Python, `.venv` y pruebas: verificados en este equipo. Ollama y el
modelo: instalados aquí, sin verificar con 64 k. Hermes: instalado aquí; procedimiento para un equipo
nuevo pendiente. Perfil, arranque, misión y trazas con Ollama: **pendientes del piloto**.

---

## 20. Acciones para una segunda fase

En orden, cada una con su propia autorización cuando tenga efectos:

1. **Sellar** el extracto del 15/10 (C6). Sin efectos externos.
2. **C4**: entrada MCP de solo planificación, con pruebas. Sin efectos externos.
3. **C3**: caso `local-planning-demo` en el ejecutor de capturas, con pruebas. Sin efectos externos.
4. **C7**: visor local de la captura. Sin efectos externos.
5. **Perfil `tfg-demo-local`** (C2). Crea un directorio en `~/.hermes`; autorización.
6. **C1**: configurar el contexto de Ollama y medir VRAM y latencia con una carga controlada.
   Afecta a Ollama; autorización.
7. **C5**: piloto único registrado de antemano, con captura y `review`. Llamadas al modelo local;
   autorización.
8. Según el resultado: escribir el manual, o pilotar un segundo modelo (descarga autorizada).
9. Opcional: C8/C9 y la publicación en Opik (opción B) con autorización explícita de cada envío.

---

## Rutas para revisar las afirmaciones

- Repositorio de aprendizaje: `/home/joelm/TFG/langchain_agent_basics/0[1-5]_*.py`, `README.md`.
- Hermes instalado: `~/.hermes/config.yaml` (secciones `model`, `custom_providers`, `mcp_servers`),
  `~/.hermes/state.db` (tablas `sessions`, `messages`, `session_model_usage`), `~/.hermes/logs/errors.log`,
  `~/.hermes/logs/install.log`, `~/.hermes/hermes-agent/agent/model_metadata.py:273`,
  `…/hermes_cli/config_defaults.py:1987-2023`, `…/tools/tool_search.py`, `…/tools/mcp_tool_registration.py`,
  `…/tools/mcp_tool_schema.py`.
- Proyecto: `tools/hermes_mcp_server.py`, `tools/hermes_mission_planning.py`,
  `tools/hermes_mission_validation.py`, `planning/mission_plan_service.py`, `planning/artifact_store.py`,
  `sessions/structured_mission_session.py`, `graph/waypoint_*.py`, `safety/*.py`,
  `tools/flight_dynamics.py`, `inputs/qgc_plan_export.py`, `observability/hermes_capture/`,
  `observability/hermes_capture_run.py`, `observability/opik_export.py`, `observability/capture_summary.py`,
  `deploy/planner/`, `deploy/compose.yaml`, `multiagent/{orchestrator,models,llm_agents,tracing,opik_bridge,
  mcp_planning_server,hermes_mission_adapter}.py`.
- Documentos: `docs/hermes-planning.md`, `docs/hermes-observability-capture.md`, `docs/opik-export.md`,
  `docs/opik-multiagent.md`, `docs/opik-op1.md`, `docs/student-environment.md` §9,
  `documentation/development_log.md`.
- Evidencias: `evaluation/observability/agri_planning_h1_nous_2026_10_24/`,
  `…/hermes_capture_blocked_2026_10_20/`, `…/opik_*`.
