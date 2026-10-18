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
  sin distinguir mayúsculas. La intención geométrica parcial se guarda en
  `geometry_intent`: conserva parámetros entre turnos, sin generar hasta completar
  las decisiones. El reemplazo explícito sustituye la ruta completa; no deja puntos
  sobrantes. Véase el contrato actualizado en la guía enlazada abajo.
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
Las escrituras usan exclusión de archivo y versión `draft_revision`. Las
ediciones geométricas/reemplazos de un borrador existente exigen
`expected_revision`; clientes antiguos de merge ordinario pueden omitirla, con
semántica de última escritura por campo. Hashes de borrador/metadatos detectan
escrituras incompletas sin reparación silenciosa.

El constructor existente aplica por defecto `drone_01`, acción `navigate`, regreso
al lanzamiento y failsafes `RETURN_TO_HOME` cuando se omiten. Hermes debe mostrar
el borrador, los valores efectivos y `compatibility_defaults` antes de pedir
autorización de ejecución. Esos defaults no son decisiones del operador; no se
usan para completar decisiones geométricas pendientes. No existen nuevos defaults
para límites, viento, batería u objetivo. La atribución de entrada MCP es una
declaración de Hermes, no autenticación de fidelidad al diálogo.
`mission_path` permite continuar con `check_mission_execution_ready` y, tras la
petición explícita del usuario, `execute_approved_mission`. El executor vuelve a
comprobar el gate. La autorización conversacional no está respaldada por un token
de consentimiento: esa garantía técnica queda pendiente.

## Prueba desde Hermes

Recargar la conexión MCP de Hermes para actualizar esquemas e instrucciones.
La [demo de varios turnos](mission-lifecycle-demo.md#corrección-tras-la-primera-prueba-conversacional)
empieza sólo por nombre y dimensiones y conserva el identificador para recuperar
el mismo borrador. Una consulta sin identificador es error de argumentos, no un
inventario vacío. Si la respuesta del proyecto ya contiene los datos necesarios,
no hace falta explorar recursos ni leer archivos directamente.
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

Pendiente: repetir la evaluación conversacional real con Hermes después de la
incidencia documentada, borrado arbitrario de campos y autorización técnica
vinculada a una versión de misión. La concurrencia geométrica ya está comprobada
offline; omitir versión en clientes antiguos de merge sigue teniendo límites.
La validación y exportación por sí solas no realizan un ensayo. El primer
[virtual preflight explícito](virtual-preflight.md) permite ensayar la misión
con LangGraph y un informe asociado a su contenido; no aplica replanning ni
repite vuelos automáticamente. Sólo está implementada la ejecución `navigate`; no están
verificadas acciones agrícolas ni seguimiento de velocidad. Volver al lanzamiento
y aterrizar no equivale a activar RTL. Exportar `.plan` no demuestra que ArduPilot
cargue ese archivo. No se ha probado hardware real.

## 18/10/2026 — Consultas concisas

MCP 0.3.0 devuelve resumen por defecto en las consultas de estado, propuesta y
preflight. `view=detail` recupera el formato completo anterior, con las mismas
verificaciones; los backends Python conservan sus defaults previos. Es un cambio
explícito del default MCP para evitar árboles repetidos; no modifica escrituras.
El resumen agrupa hechos del borrador en `draft.mission_facts`, intención en
`draft.geometry.intent`, procedencia en recuentos y pendientes en la raíz.
`detail_access` proporciona consultas con IDs existentes para acceder al detalle.
Véanse [contrato, mediciones y prompts](mission-lifecycle-demo.md).

No repetir escrituras para recuperar respuestas perdidas ni sustituir consultas
por exploración de directorios. Un ensayo SITL no necesita permiso de hardware
real; sí la solicitud explícita del ensayo y los controles deterministas existentes.
Las recomendaciones no son nuevos bloqueos técnicos y un informe sin exportación
registrada no invalida exportaciones previas. La fidelidad de Hermes requiere
prueba conversacional; estos contratos no la autentican.

## 18/10/2026 — Estado verificado de las consultas y del ensayo geométrico

La [evaluación actualizada](mission-lifecycle-demo.md#18102026--evaluación-actualizada-tras-el-ensayo-geométrico)
registra el ensayo geométrico PASSED 4bb6a20e y sus evidencias verificadas offline.
También corrige el alcance de la sección anterior: el árbol actual conserva el
módulo de proyecciones, pero las entradas MCP siguen en 0.2.0, sin `view` y sin
conexión del resumen. No está comprobada la compatibilidad anunciada de esas
vistas; hay fallos de contrato reproducidos. Las medidas anteriores de payload
se conservan como historia, sin prometer una reducción en el transporte actual.
La fidelidad del agente y el efecto sobre compacciones siguen sin evaluación
controlada, aun existiendo un ensayo aprobado de la misión geométrica persistida.

## 18/10/2026 — Vistas conectadas y verificadas posteriormente offline

Se corrige la desconexión registrada en el apartado anterior. Las tres consultas
MCP registradas exponen ahora `view=summary/detail` y default summary en servidor
0.3.0; detail conserva el formato completo previo. Los backends Python mantienen
detalle por defecto. El registro SDK, esquemas y respuestas se prueban en proceso,
sin transporte ni operaciones de simulación: 45 tests afectados/compatibilidad y
318 de suite completa pasados. No se modifican las evidencias ni se repite el vuelo.

El [contrato actualizado y mediciones](mission-lifecycle-demo.md#18102026--corrección-posterior-offline-de-las-vistas-registradas)
define `error_evidence` como lista `{path, value}` sin truncar, con rutas a la
respuesta completa original. El borrador local actual mide 62.485 bytes de detalle
y 12.798 de resumen en JSON UTF-8 indentado: reducción del 79,52%. La propuesta WP3
crece un 5,93%; no se garantiza reducción para toda respuesta. No son medidas de
tokens ni de compacciones. La validación del registro SDK no prueba fidelidad del
LLM ni transporte/reconexión de Hermes con estos wrappers corregidos.

## 18/10/2026 — Contexto de dominio versionado y evaluación preparada

Se añade el skill del proyecto `.hermes/skills/tfg-mission-control/SKILL.md`, versión
1.0.0, distinto de `hermes-agent`. La instalación local admite confianza de raíz y
precarga explícita; no basta con editar este Markdown o las instructions del MCP.
Se comprobó la carga completa con código instalado y perfil temporal, sin LLM ni
conexión operativa. No se activó en la configuración personal.

La [guía de activación, diagnóstico y evaluación](hermes-domain-evaluation.md)
explica los cambios externos revisables y contiene diez prompts naturales para
ocho escenarios, hechos/desconocidos, llamadas permitidas, efectos prohibidos y
registro de transcripciones/trazas estructuradas. No implementa un juez automático
del LLM ni presenta las incidencias como corregidas. Las pruebas deterministas
no garantizan obediencia, fidelidad o menos compacciones; falta ejecutar y registrar
las conversaciones reales. El PASSED operativo previo no evalúa estas instrucciones
posteriores. Gate, executor, geometría, tolerancias, workers y locks se conservan.

## 18/10/2026 — Transcripción con skill y revisión offline posterior

Se recibió la transcripción del operador y se contrastó con los artefactos de
Parcela Loma y la consulta histórica del rectángulo. La [evaluación parcial](hermes-domain-evaluation.md#revisión-parcial-de-transcripción-recibida-18102026)
registra orientación prematura, atribuciones/resúmenes imprecisos, exportación y
lectura de archivo redundantes, y confusión de duración. Reconoce la selección
correcta de la consulta por run_id y la distinción de misión fuente. Sin argumentos/
resultados completos no hay PASS de efectos ni fidelidad global. Los originales y
las 37 copias anteriores permanecen intactos; el archivo nuevo conserva copias con
hashes y extractos seleccionados, no una falsa traza estructurada completa.

Skill actual 1.0.1 y esquemas/descripciones clarificados, sin cambiar geometría ni
validación: statement requerido para atribución declarada ya era contrato Python;
se publica también su condición en el esquema MCP. Se conserva UNKNOWN cuando no
hay respaldo. La dirección de desplazamiento no elige por sí sola el eje; una altura
explícita sí se conserva mientras se pregunta el resto. La finalización devuelta
ya satisface construir/validar/exportar. Readiness histórica y duración de operaciones
no equivalen a disponibilidad actual ni tiempo en vuelo. Repetición conversacional
pendiente; no se cambió configuración personal ni se ejecutó una sesión LLM nueva.

## 18/10/2026 — Confirmación visual tras arranque con GUI

El skill 1.1.1 incorpora la [distinción backend/visualización](simulation-gui-confirmation.md):
después de un arranque con GUI pregunta al operador si ve mundo y drones, pantalla
negra o ninguna ventana. READY/proceso/GUI ON no verifican imagen. Una recuperación
necesita aceptación explícita, comprobar ausencia de ejecución/reserva global y una
única secuencia stop confirmado→start→readiness→pregunta visual, sin bucles ni
reintentos por timeout. Si no se puede verificar estado libre, queda pendiente.
Start también limpia procesos previos y no es un sondeo visual inocuo.

Continuar sin visualización es una elección explícita separada de consentimiento
de vuelo; mantiene gates y reservas. No hay detector de GUI ni interlock nuevo;
las consultas no cierran atómicamente la carrera entre lifecycle y un nuevo vuelo.
El último READY con pantalla negra es relato del operador, sin transcripción del
otro chat ni causa demostrada. Este cambio de instrucciones no acredita obediencia
del LLM; no se ejecuta recuperación ni conversación real durante el desarrollo.
