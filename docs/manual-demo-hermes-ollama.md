# Manual de la demostración local: Hermes, Ollama y observabilidad

**Borrador del 08/11/2026.** Este manual describe cómo reproducir, en un ordenador propio y sin servicios
externos, la planificación de una misión de dron mediante un agente conversacional que usa un modelo de
lenguaje local. No intervienen simuladores, vehículos ni cuentas en la nube.

Cada comando lleva una marca:

- **[verificado]**: ejecutado con el resultado indicado en un equipo con Ubuntu 24.04 sobre WSL2, GPU NVIDIA
  RTX 3070 Laptop de 8 GiB y 15,5 GiB de RAM;
- **[pendiente]**: todavía no comprobado en un equipo limpio; se indica la fuente oficial que hay que seguir.

## 1. Qué se demuestra

```text
Operador → Hermes Agent → Ollama (Qwen3 4B, local) → servidor MCP de planificación
        → MissionDefinition → validación determinista (LangGraph) → finalización
        → captura de observabilidad → resumen local, vista HTML y simulacro de envío a Opik
```

- **Hermes Agent** es el agente conversacional: recibe la petición, ofrece herramientas al modelo y
  ejecuta las que este solicita.
- **Ollama** sirve el modelo de lenguaje en el propio ordenador.
- El **servidor MCP de planificación** del proyecto solo contiene dos herramientas: guardar un borrador de
  misión (`update_mission_draft`) y finalizarlo (`finalize_mission_draft`). No contiene ninguna operación de
  simulación ni de vuelo.
- La decisión de seguridad no la toma el modelo: la toma el código determinista del proyecto (energía,
  viento y altitud), organizado como un grafo de LangGraph.
- La **observabilidad** registra qué modelo respondió, qué herramientas se ofrecieron y se usaron, y
  cuánto tardó cada paso, sin guardar los textos de la conversación.

## 2. Requisitos del ordenador

| Elemento | Configuración verificada | Notas |
| --- | --- | --- |
| Sistema | Ubuntu 24.04 sobre WSL2 (Windows) | Linux nativo debería comportarse igual [pendiente]. macOS y equipos sin GPU NVIDIA: [pendiente] |
| GPU | NVIDIA de 8 GiB de VRAM | Con 8 GiB el modelo cabe entero en la GPU solo con la configuración del apartado 6 |
| RAM | 16 GB | Durante la demostración quedaron más de 8 GiB libres |
| Disco | 3 GB libres para el modelo, más el repositorio y su entorno de Python | |
| Programas | `git`, `curl`, Python 3.12 con `venv` | |

## 3. Obtener el repositorio

Directorio: el que se prefiera para el código.

```bash
git clone https://github.com/Joowww/Agentic_Drone_Mission_Control.git
cd Agentic_Drone_Mission_Control
```

**[pendiente]**: el acceso al repositorio y la versión exacta que se entrega para esta demostración. En el
resto del manual, `<REPO>` es la carpeta clonada; todos los comandos de Python se ejecutan desde ella.

## 4. Python y dependencias

Directorio: `<REPO>`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-observability.txt -c constraints-verified.txt
.venv/bin/python -m pip install -r requirements-dev.txt -c constraints-verified.txt
```

**[verificado]** La instalación tarda unos 20 s con conexión y fija las versiones comprobadas
(`mcp` 2.3.0, `pydantic` 2.13.5, `langgraph` 1.2.12, `PyYAML` 6.0.3, `jsonschema` 4.26.0).

Comprobación, sin modelo ni red:

```bash
.venv/bin/python -m pytest -q tests/test_hermes_demo_planning_server.py tests/test_local_planning_demo.py
```

**[verificado]** Debe terminar con todas las pruebas superadas. Incluye la planificación real de la misión
de ejemplo sin modelo de lenguaje: el resultado esperado es `FEASIBLE` y `APPROVED`.

## 5. Ollama y el modelo

### 5.1 Instalación

**[pendiente]** Instalar Ollama siguiendo las instrucciones oficiales de <https://ollama.com/download> para
el sistema correspondiente. Versión verificada: 0.34.2.

```bash
ollama --version
```

**[verificado]** Debe mostrar `ollama version is 0.34.2` (o la versión instalada).

### 5.2 Modelo

Directorio: `<REPO>`.

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama create qwen3-4b-instruct-64k -f deploy/hermes_local_demo/Modelfile.qwen3-4b-instruct-64k
ollama list
```

**[verificado]** La descarga ocupa 2,5 GB. `ollama create` no descarga nada: crea un nombre nuevo,
`qwen3-4b-instruct-64k`, con los mismos pesos y un contexto de 65 536 tokens. `ollama list` debe mostrar
ambos nombres.

**Por qué este modelo y este contexto.** Hermes Agent se niega a trabajar con menos de 64 000 tokens de
contexto. Se usa la variante *Instruct* de Qwen3 4B porque responde sin una fase previa de razonamiento:
en las mediciones, la variante con razonamiento tardó más de siete minutos en preparar una sola llamada a
una herramienta.

## 6. Servidor de Ollama para la demostración

Con 8 GiB de VRAM, 64 000 tokens de contexto solo caben en la GPU si la memoria de contexto del modelo se
comprime (`OLLAMA_KV_CACHE_TYPE=q4_0`, con `OLLAMA_FLASH_ATTENTION=1`). Sin ese ajuste, la mitad del modelo se
ejecuta en la CPU y la generación cae a unos 4 tokens por segundo. El ajuste se aplica a un servidor de Ollama
aparte, en `127.0.0.1:11435`, para no modificar el servicio habitual del sistema.

Directorio: `<REPO>`.

```bash
deploy/hermes_local_demo/ollama_demo_instance.sh start
deploy/hermes_local_demo/ollama_demo_instance.sh status
```

**[verificado]** `start` responde `started (pid …) at http://127.0.0.1:11435`. El script usa los modelos del
Ollama instalado (en Linux, `/usr/share/ollama/.ollama/models`); el usuario debe poder leer esa carpeta. En
el equipo verificado, el usuario pertenecía al grupo `ollama`. **[pendiente]** el procedimiento en una
instalación nueva.

Comprobación de carga:

```bash
curl -s http://127.0.0.1:11435/api/generate -d '{"model":"qwen3-4b-instruct-64k","prompt":"Responde solo: OK","stream":false,"options":{"num_predict":5}}'
OLLAMA_HOST=127.0.0.1:11435 ollama ps
```

**[verificado]** La respuesta contiene `"response":"OK"` en unos 6 s. `ollama ps` debe mostrar
`qwen3-4b-instruct-64k`, unos 5,6 GB, `100% GPU` y `65536` de contexto. Si aparece un reparto CPU/GPU, la
generación será mucho más lenta (apartado 13).

## 7. Hermes Agent

**[pendiente]** Instalar Hermes Agent con el procedimiento oficial de Nous Research. La demostración se ha
verificado con la versión 0.22.2 (revisión `d923a5eb`); el complemento de observabilidad del proyecto está
comprobado contra esa revisión.

```bash
hermes --version
```

**[verificado]** Muestra `Hermes Agent v0.22.2 (2026.9.24) · stable · local d923a5eb487a`.

No hace falta iniciar sesión en ningún proveedor: la demostración no usa modelos remotos.

## 8. Perfil seguro de Hermes

Hermes guarda su configuración por perfiles. La demostración usa uno propio, `tfg-demo-local`, que no
modifica el perfil habitual.

```bash
hermes profile create tfg-demo-local --no-skills --no-alias
```

Después, desde `<REPO>`:

```bash
.venv/bin/python -m observability.local_planning_demo prepare-profile
.venv/bin/python -m observability.local_planning_demo verify-profile --offered-tools
```

**[verificado]** `prepare-profile` escribe la configuración del perfil (guardando una copia de la anterior)
e instala el complemento de captura. Los borradores de misión se guardan en `~/tfg-local-demo/drafts` y las
ejecuciones en `~/tfg-local-demo/runs`, ambas carpetas privadas y fuera del repositorio.

`verify-profile` no llama al modelo. Debe terminar con `"ok": true`. Comprueba, entre otras cosas, que:

- el proveedor es Ollama en `127.0.0.1` con 65 536 tokens de contexto y sin proveedores de respaldo;
- la búsqueda diferida de herramientas está desactivada y solo existe el servidor `tfg-demo-planning`;
- se ofrecen solo `update_mission_draft` y `finalize_mission_draft`, sin recursos ni prompts MCP;
- no hay herramientas de terminal, archivos ni web (`"builtin_tool_schemas": 0`);
- el perfil no contiene credenciales y el complemento instalado coincide con el del repositorio;
- el servidor MCP que se ejecuta es el de este repositorio.

## 9. Servidor MCP de planificación

Hermes arranca el servidor por sí mismo; no hay que lanzarlo a mano. Para comprobarlo:

```bash
hermes -p tfg-demo-local mcp test tfg-demo-planning
```

**[verificado]** Debe indicar `✓ Connected` y `✓ Tools discovered: 2`, con `update_mission_draft` y
`finalize_mission_draft`.

El servidor reutiliza exactamente la lógica de planificación del proyecto y no importa ningún módulo de
simulación, ensayo, reservas o ejecución. Si se arranca sin la carpeta privada de borradores, se niega a
funcionar.

## 10. Observabilidad

El complemento de captura está habilitado en el perfil, pero solo registra datos cuando se definen estas
variables:

| Variable | Valor |
| --- | --- |
| `TFG_OBSERVABILITY_CAPTURE` | `1` |
| `TFG_OBSERVABILITY_DIR` | carpeta nueva y privada para esa ejecución |
| `TFG_OBSERVABILITY_RUN_ID`, `TFG_OBSERVABILITY_CASE_ID` | etiquetas cortas (opcionales) |

El comando del apartado 11 las define automáticamente. Se registran metadatos: proveedor, modelo,
duraciones, contadores de tokens, nombres de las herramientas ofrecidas y usadas, y su estado. No se guardan
los mensajes, los argumentos ni los resultados de las herramientas.

## 11. Ejecución de la misión

Directorio: `<REPO>`. Con el servidor del apartado 6 en marcha.

La misión de ejemplo es la del sector A del escenario agrícola de demostración, ya validada en el proyecto:
multirrotor ArduPilot a 35 km/h, batería al 100 %, consumo del 0,8 % por minuto, viento de referencia 0 km/h
y dos puntos a 5 m de altura relativos a un punto de inicio. Se ejecuta en dos turnos del operador:

1. **Turno 1:** se dan todos los datos excepto los tres límites de seguridad (reserva mínima de batería,
   viento máximo y altitud máxima). El agente debe guardar el borrador y preguntar por lo que falta.
2. **Turno 2:** se dan los tres límites (20 %, 30 km/h y 120 m) y se pide finalizar la misión.

```bash
RUN=~/tfg-local-demo/runs/demo-$(date +%Y%m%d-%H%M%S)
.venv/bin/python -m observability.local_planning_demo turn --run-dir "$RUN" --turn 1
cat "$RUN/stdout-turn-1.txt"
.venv/bin/python -m observability.local_planning_demo turn --run-dir "$RUN" --turn 2
cat "$RUN/stdout-turn-2.txt"
```

**[verificado]** Cada turno es una sola invocación de Hermes, con un límite de 600 s y sin reintentos. En el
equipo verificado tardaron unos 30 y 40 s. El segundo turno continúa la misma sesión de Hermes que el primero.
El texto de los prompts está en `observability/hermes_capture_run.py` (`LOCAL_DEMO_TURN_1` y
`LOCAL_DEMO_TURN_2`).

También es posible conversar con el agente directamente **[pendiente]**, desde una carpeta vacía para que
Hermes no cargue instrucciones de otros proyectos:

```bash
mkdir -p ~/tfg-local-demo/work && cd ~/tfg-local-demo/work
TFG_OBSERVABILITY_CAPTURE=1 TFG_OBSERVABILITY_DIR=$HOME/tfg-local-demo/manual-$(date +%Y%m%d-%H%M%S)/capture hermes -p tfg-demo-local
```

## 12. Resultado esperado

En la respuesta del turno 2 y en los archivos de la finalización:

| Campo | Valor esperado | Significado |
| --- | --- | --- |
| `status` | `VALIDATED` | La misión se construyó y pasó por la validación determinista |
| `validation.mission_status` | `FEASIBLE` | Energía, viento y altitud dentro de los límites |
| `validation.execution_status` | `APPROVED` | Compatible con el ejecutor del proyecto (no autoriza a volar) |
| `validation.qgc_export.status` | `REFUSED` | Ver más abajo |
| `flight_consent` | `NOT_GRANTED` | Ninguna parte de la demostración concede permiso de vuelo |

`REFUSED` en la exportación a QGroundControl es el comportamiento correcto. El formato `.plan` necesita la
altitud real sobre el nivel del mar del punto de inicio, y el borrador solo contiene altitudes relativas. El
exportador no inventa ese dato, así que rechaza la exportación y explica el motivo. No afecta a la validación
de la misión.

**Variabilidad del modelo.** Con un modelo de 4B, el agente puede no reutilizar el mismo borrador en el
segundo turno, olvidar algún identificador o citar rutas de archivo que no existen. El veredicto de seguridad
no depende de ello: lo calcula el código determinista y queda en `finalization.json`. Cuando el modelo omite
el identificador de la misión, el sistema aplica un valor por defecto y lo declara como tal.

## 13. Consulta de trazas

Directorio: `<REPO>`. `EVID` es una carpeta nueva de evidencia; nunca se reutiliza.

```bash
EVID=~/tfg-local-demo/evidence/$(basename "$RUN")
.venv/bin/python -m observability.local_planning_demo review --run-dir "$RUN" --evidence-dir "$EVID"
.venv/bin/python -m observability.hermes_capture_run opik-dry-run --evidence-dir "$EVID" --project tfg-hermes-local-demo --workspace local-dry-run
.venv/bin/python -m observability.local_planning_demo view --evidence-dir "$EVID"
```

**[verificado]**

- `review` comprueba la captura y escribe la evidencia con su manifiesto `SHA256SUMS`. El resultado esperado
  incluye `"tool_isolation_verdict": "PLANNING_CALLS_WITHIN_ALLOWED_TOOLS"`, `"mission_validated": true` y
  `"flight_consent": "NOT_GRANTED"`.
- `opik-dry-run` construye exactamente lo que se enviaría a Opik (trazas y *spans*), **sin enviarlo** y sin
  leer ninguna clave. Demuestra que la captura local se puede convertir al formato de Opik.
- `view` genera `view.html`, una página estática sin conexión a Internet. Muestra el modelo, las llamadas al
  modelo con su duración y sus tokens, las herramientas usadas y el resultado de la misión.

Para abrir la página desde WSL: `explorer.exe "$(wslpath -w "$EVID/view.html")"` **[pendiente]**. En Linux
nativo, `xdg-open "$EVID/view.html"` **[pendiente]**.

Validación determinista de la misión, sin modelo de lenguaje:

```bash
.venv/bin/python -m tools.hermes_mission_validation --mission "$EVID"/mission-*.json
```

**[verificado]** Debe devolver `"mission_status": "FEASIBLE"` y `"execution_status": "APPROVED"`.

## 14. Resolución de problemas

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| `verify-profile` no devuelve `"ok": true` | El perfil se modificó a mano o el repositorio se movió | Repetir `prepare-profile` y revisar el campo `detail` de la comprobación fallida |
| Hermes indica que el contexto es inferior a 64 000 | Se usa `qwen3:4b-instruct-2507-q4_K_M` en lugar de `qwen3-4b-instruct-64k` | Repetir `ollama create` (apartado 5.2) |
| `ollama ps` muestra un reparto CPU/GPU | El servidor de la demo no está en marcha o la GPU está ocupada | `ollama_demo_instance.sh status`; cerrar otros programas que usen la GPU |
| `could not connect to ollama server` en 11435 | Servidor de la demo detenido | `deploy/hermes_local_demo/ollama_demo_instance.sh start` |
| El turno supera 600 s | Modelo en CPU o variante con razonamiento | Comprobar `ollama ps` y el nombre del modelo |
| `tool_error` con `greater_than` o `Draft not found` | El modelo colocó un dato en el campo equivocado o inventó un identificador | Es un fallo del modelo, no del sistema: el dato no se guarda. Repetir la ejecución en una carpeta nueva |
| `status: INCOMPLETE` | Faltan datos de la misión | El campo `missing_fields` indica cuáles |
| `qgc_export: REFUSED` | Falta la altitud sobre el nivel del mar del punto de inicio | Comportamiento esperado (apartado 12) |
| `review`: `evidence directory already exists` | La carpeta de evidencia ya existe | Usar otra carpeta |

## 15. Repetir la demostración y cerrar la sesión

Cada ejecución usa una carpeta `RUN` nueva y una carpeta `EVID` nueva. Para empezar también con el almacén de
borradores vacío, sin borrar los anteriores:

```bash
mv ~/tfg-local-demo/drafts ~/tfg-local-demo/drafts-archivo-$(date +%Y%m%d-%H%M%S)
.venv/bin/python -m observability.local_planning_demo prepare-profile
```

**[verificado]**

Cierre:

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama stop qwen3-4b-instruct-64k
deploy/hermes_local_demo/ollama_demo_instance.sh stop
```

**[verificado]** El segundo comando responde `stopped (pid …)` y libera la memoria de la GPU. El servicio
habitual de Ollama no se ve afectado.
