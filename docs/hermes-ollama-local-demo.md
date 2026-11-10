# Demo local Hermes + Ollama + observabilidad: estado, evidencias y procedimiento manual (08/11/2026)

Anexo técnico para Joel. El texto para Toni es [manual-demo-hermes-ollama.md](manual-demo-hermes-ollama.md); la
investigación previa, [hermes-ollama-observability-investigation-2026-11-08.md](hermes-ollama-observability-investigation-2026-11-08.md).
**La validación final de la entrega queda abierta hasta que Joel ejecute y revise la demostración.**

## 1. Estado

- **La cadena funciona con un modelo local** (piloto r02, REAL): Operador → Hermes `d923a5eb` (perfil
  `tfg-demo-local`) → Ollama 0.34.2 en `127.0.0.1:11435` → `qwen3-4b-instruct-64k` → servidor MCP
  `tfg-demo-planning` → `MissionDefinition` → `waypoint_mission_graph` → `finalization.json` → captura →
  `review` → dry-run de Opik → `view.html`.
- El primer piloto, r01, **falló** por interpretación del modelo; el segundo, r02, con guía en las
  descripciones del servidor de demo, completó la misión con desviaciones documentadas.
- Rama `feature/multiagent-opik-evaluation`, commits `c41c723e6` → `6982d4dd9` (más este documento). Sin push.

## 2. Archivos nuevos

| Archivo | Función |
| --- | --- |
| `tools/hermes_demo_planning_server.py` | Servidor MCP de demo (C4): solo `update_mission_draft` y `finalize_mission_draft`, mismo esquema y backend que el servidor completo; guía añadida a las descripciones; borradores solo en `TFG_DEMO_DRAFT_ROOT` |
| `observability/local_planning_demo.py` | `prepare-profile`, `verify-profile [--offered-tools]`, `turn`, `review`, `view`, `ollama-probe` |
| `observability/hermes_capture_run.py` (modificado) | Caso `local-planning-demo` (C3) con los dos prompts registrados; `registry_name(tool, server)`; el caso no puede ejecutarse por el flujo de edición temporal |
| `deploy/hermes_local_demo/Modelfile.qwen3-4b-instruct-64k` | Modelo derivado con `num_ctx 65536` |
| `deploy/hermes_local_demo/ollama_demo_instance.sh` | Instancia propia de Ollama (loopback 11435, flash attention, KV q4_0) |
| `tests/test_hermes_demo_planning_server.py`, `tests/test_local_planning_demo.py` | 37 pruebas sin modelo |
| `evaluation/observability/ollama_context_memory_2026_11_08/` | Mediciones (REAL) |
| `evaluation/observability/hermes_ollama_local_pilot_2026_11_08_r01/` | Piloto r01 (FALLIDO) |
| `evaluation/observability/hermes_ollama_local_pilot_2026_11_08_r02/` | Piloto r02 (REAL) |
| `docs/manual-demo-hermes-ollama.md`, este documento | Manual y anexo |

Fuera del repositorio (privado, 0700): perfil `~/.hermes/profiles/tfg-demo-local`, datos `~/tfg-local-demo/`
(`drafts/`, `runs/`, `ollama/`, `drafts-archivo-20261108-pilotos/` con los borradores de r01 y r02), material de
preparación `~/tfg-local-demo-prep/2026-11-08/`. Modelos nuevos en Ollama: `qwen3:4b-instruct-2507-q4_K_M`
(descarga autorizada), `qwen3-4b-instruct-64k` y `qwen3-4b-64k` (derivados, sin descarga). El perfil `default` de
Hermes y el servicio de Ollama del sistema no se modificaron.

## 3. Mediciones (resumen de `ollama_context_memory_2026_11_08`)

| Configuración | GPU | Generación | Resultado |
| --- | --- | --- | --- |
| `qwen3:4b` *Thinking*, 64 k, KV f16 (servicio del sistema) | 17/37 capas, 12 GB 52 % CPU | ~4 tokens/s | Llamada con herramientas cortada a 600 s |
| Igual, KV q8_0 (instancia propia) | 28/37 | 12 tokens/s | Insuficiente |
| Igual, KV q4_0 | 37/37, 5,6 GB | 29,8 tokens/s | `tool_calls` correcta en 430 s (7 657 tokens de razonamiento) |
| **`qwen3-4b-instruct-64k`, KV q4_0** | **37/37, 5,6 GB** | — | **`tool_calls` correcta en 9,2 s**; carga 5–6 s |

Contexto efectivo 65 536 en todos los casos; ningún error por falta de memoria.

## 4. Pilotos

| | r01 (FALLIDO) | r02 (REAL) |
| --- | --- | --- |
| Servidor | `1048fd00c` | `5ad919ea9` (guía en descripciones) |
| Turnos | 16 s y 11 s | 29 s y 40 s |
| Llamadas LLM / herramientas | 4 / 2 | 7 / 5 |
| Herramientas ofrecidas | Solo las 2 de planificación | Solo las 2 de planificación |
| Resultado | Viento actual en `maximum_wind_speed_kmh`, `draft_id` inventado; nada guardado | `VALIDATED`, `FEASIBLE`/`APPROVED`, QGC `REFUSED`, `NOT_GRANTED` |
| Desviaciones | — | Nuevos borradores en el turno 2 (uno huérfano), `mission_id` por defecto `…_001`, procedencia de la ruta perdida, ruta de archivo inventada en la respuesta |

## 5. Comandos y estado de verificación

Directorio `<REPO>` salvo indicación. «Verificado» = ejecutado hoy con el resultado indicado.

| Comando | Efecto | Estado |
| --- | --- | --- |
| `python3 -m venv .venv` + `pip install -r requirements.txt -r requirements-observability.txt -c constraints-verified.txt` (+ `requirements-dev.txt`) | Crea `.venv` | Verificado (18 s) |
| `ollama pull qwen3:4b-instruct-2507-q4_K_M` | Red, 2,5 GB | Verificado (4 min 24 s) |
| `ollama create qwen3-4b-instruct-64k -f deploy/hermes_local_demo/Modelfile.qwen3-4b-instruct-64k` | Nombre nuevo, sin descarga | Verificado |
| `deploy/hermes_local_demo/ollama_demo_instance.sh start\|status\|stop` | Proceso `ollama serve` propio | Verificado |
| `curl … 127.0.0.1:11435/api/generate …` y `OLLAMA_HOST=127.0.0.1:11435 ollama ps` | Carga el modelo | Verificado (100 % GPU, 65 536) |
| `hermes profile create tfg-demo-local --no-skills --no-alias` | Crea el perfil | Verificado (con `--description`) |
| `.venv/bin/python -m observability.local_planning_demo prepare-profile` | Escribe config y plugin del perfil | Verificado |
| `… verify-profile --offered-tools` | Sin modelo; arranca el servidor MCP para listarlo | Verificado (`ok: true`, 0 integradas, 2 MCP) |
| `hermes -p tfg-demo-local mcp test tfg-demo-planning` | Arranca el servidor MCP | Verificado |
| `… turn --run-dir <nuevo> --turn 1` y `--turn 2` | Una invocación de Hermes, llamadas a Ollama local, escrituras en `~/tfg-local-demo/drafts` | Verificado (r01, r02) |
| `… review --run-dir <run> --evidence-dir <nuevo>` | Escribe evidencia | Verificado |
| `… review --capture-dir <dir> --evidence-dir <nuevo> [--draft-id …]` | Sesión manual | Solo con captura SINTÉTICA (pruebas) |
| `.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir <ev> --project tfg-hermes-local-demo --workspace local-dry-run` | Sin red, sin clave | Verificado |
| `… view --evidence-dir <ev>` | Escribe `view.html` | Verificado |
| `… ollama-probe` | Una llamada directa a Ollama local, sin ejecutar herramientas | Verificado (5,4 s) |
| `.venv/bin/python -m tools.hermes_mission_validation --mission <mission.json>` | Validación determinista, sin escrituras | Verificado |
| `hermes -p tfg-demo-local` (sesión interactiva con `TFG_OBSERVABILITY_*`) | Conversación manual | **Pendiente** (Joel) |
| Instalador oficial de Hermes y de Ollama en un equipo limpio | — | **Pendiente** |

## 6. Procedimiento manual para Joel (VS Code + terminal)

Abrir `Agentic_Drone_Mission_Control_multiagent` en VS Code y una terminal integrada en la raíz.

1. `deploy/hermes_local_demo/ollama_demo_instance.sh start` → `started (pid …)`.
2. Comprobación de carga (manual §6) → `"response":"OK"`; `ollama ps` con `100% GPU` y `65536`.
3. `.venv/bin/python -m observability.local_planning_demo verify-profile --offered-tools` → `"ok": true`.
4. `RUN=~/tfg-local-demo/runs/joel-$(date +%Y%m%d-%H%M%S)` y los dos `turn` (manual §11). Tras cada uno,
   `cat "$RUN/stdout-turn-N.txt"`: el turno 1 debe preguntar por los límites; el turno 2, informar del
   resultado.
5. `review`, `opik-dry-run` y `view` (manual §13). Abrir `view.html` desde el explorador de VS Code o con
   `explorer.exe`. Comprobar: veredicto `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`, `mission_validated: true`,
   `NOT_GRANTED`.
6. Comparar con `evaluation/observability/hermes_ollama_local_pilot_2026_11_08_r02/` (mismos campos en
   `outcome.json` y `planning_result.json`). Las cifras de tiempo y el número de llamadas pueden variar.
7. Sesión interactiva opcional (manual §11, pendiente) y revisión con `review --capture-dir`.
8. Cierre (manual §15).

Para repetir: carpeta `RUN` y `EVID` nuevas en cada ejecución; `mv` del almacén de borradores y
`prepare-profile` para empezar vacío (verificado). Cada evidencia queda separada y con su `SHA256SUMS`.

## 7. Casos de comparación (misma misión: H1 sector A)

| Caso | Qué interviene | Tipo | Comando | Estado |
| --- | --- | --- | --- | --- |
| A. Ollama/Qwen directo | LLM real con los mismos esquemas de herramienta; no se ejecuta nada | LLM real | `… local_planning_demo ollama-probe` | Verificado: `update_mission_draft` con los datos del turno 1 (5,4 s, 308 tokens) |
| B. Hermes + MCP + LangGraph | Agente, LLM real, herramientas reales, validación determinista | LLM real + reglas | `turn` ×2 | Verificado (r02) |
| C. LangGraph determinista | `waypoint_mission_graph` sobre el `mission.json` de B | Reglas, sin LLM | `tools.hermes_mission_validation --mission …` | Verificado: `FEASIBLE`/`APPROVED` |
| D. Planificador sin modelo | Backend real con un borrador escrito en código | Reglas, sin LLM | `pytest tests/test_local_planning_demo.py -k planning_result` | Verificado: `FEASIBLE`/`APPROVED`, `REFUSED`, `NOT_GRANTED` |
| E. LangChain + LangGraph | `ChatOllama("qwen3:4b")` del menú, opción 3 (planificador IA), y grafo de validación | LLM real (servicio 11434, contexto 4 096, variante *Thinking*) | `.venv/bin/python main.py` → 3 | **Pendiente**; contrato distinto del de Hermes (no es una comparación directa) |
| F. Captura sintética | Eventos escritos por el plugin real con datos inventados | SINTÉTICO | `pytest tests/test_local_planning_demo.py -k synthetic` | Verificado; solo prueba la tubería de revisión y vista |

No se debe comparar A con B como si fueran lo mismo: A mide la primera decisión del modelo; B, el recorrido
completo con ejecución. C y D no usan modelo.

## 8. Lo que falla o falta

1. **Fiabilidad del modelo:** un solo piloto correcto; la continuidad del borrador entre turnos y los
   identificadores fallan con Qwen3 4B. Hace falta una serie de repeticiones para medirla.
2. Las `instructions` del servidor MCP no llegan al modelo en Hermes `d923a5eb` (inferido del código); por eso la
   guía va en las descripciones de las herramientas.
3. Sesión interactiva y `review --capture-dir` con datos reales: sin verificar.
4. Instalación de Hermes y Ollama en un equipo limpio, acceso al repositorio y hardware de Toni: pendientes.
5. Caché KV q4_0: menor precisión que f16; es el compromiso para 8 GiB.
6. Los `turn-*.json` de r01 y r02 incluyen la ruta personal en `argv` (las revisiones nuevas ya la sustituyen
   por `~`).
7. El informe de investigación y `docs/INDEX.md` del repositorio principal no se han tocado.

## 9. Para empaquetarlo (el subsistema rover u otro responsable)

- Código: los archivos del §2 y el Modelfile; dependencias, las de `requirements*.txt` con
  `constraints-verified.txt`.
- Host: Ollama ≥ 0.34.2 con `qwen3:4b-instruct-2507-q4_K_M` y el derivado de 64 k; con 8 GiB de VRAM, la
  instancia del script (o las mismas variables en el servicio, decisión del usuario).
- Hermes `d923a5eb` (0.22.2) y el perfil `tfg-demo-local` creado con `hermes profile create` +
  `prepare-profile`. La imagen `deploy/planner` sigue fijada a Laguna y a la red `provider`: para usarla en
  local hace falta C9 (variante real de `prepare-test-home` y red compartida con `ollama`), no implementado.
- Ninguna credencial; Opik solo en dry-run.

## 10. Pruebas

- Suite de referencia (`test_hermes_mcp_server`, `test_hermes_mission_planning`,
  `test_hermes_mission_validation`, `test_hermes_observability_capture`, `test_hermes_capture_run`,
  `test_capture_summary`, `test_opik_export`, `test_planning_profile`): **368 pasadas, 3 omitidas**, igual que
  antes de los cambios.
- Nuevas: `test_hermes_demo_planning_server.py` y `test_local_planning_demo.py`: **37 pasadas**.
- Comandos operativos ejecutados: **cero** (ni simulador, ni preflight, ni misiones, ni vehículos; Opik sin envío).
