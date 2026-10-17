# Planificación conversacional mediante Hermes

Hermes interpreta el lenguaje natural y elige las herramientas según la petición
y sus resultados. No necesita limitarse a una llamada. Esta integración no llama
al extractor Ollama de `agents/mission_planner.py`: reutiliza `MissionPlanDraft`,
la fusión y construcción de `planning/mission_plan_service.py`, y el workflow
con estado de validación existente. La entrada JSON sigue disponible.

## Herramientas y persistencia

- `update_mission_draft(updates, draft_id=None)` crea un borrador. Su esquema MCP
  describe los campos aceptados. Devuelve `draft_id`, `draft`, `missing_fields`
  y estado `INCOMPLETE` o `COMPLETE`. Hermes debe preguntar por los datos pendientes
  y enviar únicamente hechos aportados por el operador, sin inventarlos.
- La misma herramienta con `draft_id` continúa el borrador. `updates={}` lo
  recupera, incluso después de reiniciar el servidor. Cada misión usa su propio ID.
  Los valores nulos conservan los anteriores; los waypoints se fusionan por ID,
  sin distinguir mayúsculas. No se admiten eliminaciones en este incremento.
- Los campos desconocidos, valores fuera del esquema y números no finitos se
  rechazan. Los errores de esquema MCP se presentan como errores de herramienta;
  errores de carga/construcción devuelven `status=ERROR`. Un error no sustituye
  el borrador guardado. Los valores físicamente válidos pero inseguros deben llegar
  al evaluador determinista, que decide su viabilidad.
- `finalize_mission_draft(draft_id)` devuelve los campos pendientes si faltan datos.
  Cuando está completo construye `MissionDefinition`, guarda un JSON y llama a la
  validación/exportación existentes. `status=VALIDATED` significa que se evaluó:
  hay que leer `validation.mission_status` y `validation.execution_status`.
  Una misión bloqueada puede producir un `.plan` candidato, nunca permiso de vuelo.

Los borradores se guardan en `missions/generated/drafts/<UUID>/draft.json`.
Cada finalización genera un directorio UUID propio con `mission.json` y `.plan`;
no sobrescribe las misiones ya revisadas. El ID de misión admite letras ASCII,
dígitos, guiones y guiones bajos para evitar rutas en el nombre de exportación.
No hay control de concurrencia para ediciones simultáneas del mismo borrador.

El constructor existente aplica por defecto `drone_01`, acción `navigate`, regreso
al lanzamiento y failsafes `RETURN_TO_HOME` cuando se omiten. Hermes debe mostrar
el borrador y los valores efectivos antes de pedir autorización de ejecución.
`mission_path` permite continuar con `check_mission_execution_ready` y, tras la
petición explícita del usuario, `execute_approved_mission`. El executor vuelve a
comprobar el gate. La autorización conversacional no está respaldada por un token
de consentimiento: esa garantía técnica queda pendiente.

## Prueba desde Hermes

Reiniciar la conexión MCP de Hermes para descubrir las dos herramientas nuevas.
El servidor se ejecuta desde la raíz del repositorio con:

```bash
.venv/bin/python -m tools.hermes_mcp_server
```

Prompts sugeridos, cada uno en un turno:

```text
Quiero crear una misión nueva llamada Prueba Hermes para un multirrotor ArduPilot, objetivo tránsito hacia la parcela de prueba. Guarda un borrador, pregúntame por los datos que falten y no arranques simulación ni ejecutes vuelos.
```

```text
Continúa el mismo borrador: velocidad de crucero 20 km/h, batería 95 %, consumo 0.8 % por minuto, home latitud 41 y longitud 2 a altitud 0 m, viento 0 km/h desde el norte, reserva mínima 20 %, viento máximo 30 km/h y altitud máxima 50 m; añade WP1 en latitud 41.0001 y longitud 2, altitud 10 m, acción navigate, y regreso al lanzamiento.
```

```text
Muéstrame los valores efectivos, construye el JSON, valida la misión y genera su QGC .plan; informa de los resultados y las rutas sin arrancar simulación ni ejecutar vuelos.
```

Estas coordenadas son un ejemplo de planificación, no una prueba de vuelo.
Para recuperar el borrador tras reiniciar, proporcionar a Hermes su `draft_id`.

## Verificación y límites

```bash
.venv/bin/python -m pytest -q
```

Los tests cubren borradores incompletos, recuperación desde disco, fusión de
waypoints, valores inválidos, IDs no válidos, cambio de dirección del viento,
construcción, exportación real aprobada y bloqueada, y conservación del JSON
anterior tras una edición. No requieren Ollama, Docker ni vuelos.

Pendiente: evaluación conversacional real con Hermes, borrado de campos/waypoints,
control de concurrencia y autorización vinculada a una versión de misión.
La validación y exportación por sí solas no realizan un ensayo. El primer
[virtual preflight explícito](virtual-preflight.md) permite ensayar la misión
con LangGraph y un informe asociado a su contenido; no aplica replanning ni
repite vuelos automáticamente. Sólo está implementada la ejecución `navigate`; no están
verificadas acciones agrícolas ni seguimiento de velocidad. Volver al lanzamiento
y aterrizar no equivale a activar RTL. Exportar `.plan` no demuestra que ArduPilot
cargue ese archivo. No se ha probado hardware real.
