# Planificación, revisiones y explicación de estado desde Hermes

Incremento sobre `bad8920`, 17/10/2026. Son tres bloques implementados y probados
offline en orden. No añade vuelos, Docker, dependencias ni un segundo LLM durante
el desarrollo. JSON sigue siendo entrada válida y QGC `.plan` sigue siendo salida.

## 1. Propuestas y revisiones trazables

`propose_mission_revision(run_id, request_key)` lee un informe final mediante el
resolvedor existente de ensayos; no acepta rutas de informes. Comprueba UUID,
identidad de misión, SHA-256 del snapshot y hash admitido si existe, validación
coherente y análisis del executor. Para `PASSED`/`FAILED` vuelve a analizar los
eventos con el analizador existente y exige concordancia con el análisis guardado.
Un informe provisional, contradictorio o con identidad histórica ambigua devuelve
`ERROR`. Para `BLOCKED` exige motivos compatibles con la fase y ausencia de vuelo
si el rechazo fue previo al executor. No puede convertir recuperación LAND en éxito.

Persiste una propuesta v1, sus motivos, condiciones, recomendaciones textuales,
evidencia bruta/diagnóstico disponible y copias exactas de misión e informe fuente.
La propuesta devuelve `proposal_id`, `proposal_sha256` y rutas. Se recupera con
`get_revision_proposal(proposal_id)` tras recarga. Las copias son inmutables para
estas operaciones; no son archivos protegidos contra escritura externa.

| Evidencia fuente | Comportamiento de la propuesta |
| --- | --- |
| Batería bloqueada | Reutiliza las recomendaciones del replanner: intervención física, o revisar/dividir ruta cuando corresponda. No genera una ruta numérica ni garantiza resolver el presupuesto energético. |
| Readiness bloqueada | Infraestructura pendiente, sin parche de misión. No comprueba que ahora esté disponible. |
| Fallo WP3 con LAND | Investigar objetivo, observaciones y entorno; causa desconocida. Conserva la recuperación y cualquier diagnóstico existente. No elimina WP3 ni amplía tiempos. |
| PASSED | `NO_CORRECTION_REQUIRED`, sin corrección innecesaria. Sigue sin consentir otro ensayo. |

`build_mission_revision(proposal_id, expected_proposal_sha256, changes,
operator_statement, request_key, declarations)` exige el hash de la propuesta
revisada y una declaración explícita de los cambios aceptados/aportados. Revalida
las fuentes originales y sus copias. Aplica únicamente `RevisionChanges` mediante
el editor existente; guarda diferencias estructuradas y procedencia en una misión
nueva. Valida y exporta una sola vez mediante los servicios actuales. `REVISED`
indica construcción, no aprobación: consultar `validation.execution_status`.
Puede seguir `BLOCKED` y exportar únicamente un `.plan` candidato.

Cambiar batería, viento o consumo exige `declarations` por cada campo afectado,
con procedencia `operator_declared_not_telemetry`. Una recomendación de carga no
cambia el nivel físico. No se comprueba por telemetría esa declaración. Esta
interfaz conservadora rechaza bajar la reserva o aumentar límites de viento/altitud;
no ajusta tolerancias ni utiliza esos cambios para forzar aprobación.

```text
missions/generated/revisions/proposals/<proposal_id>/proposal.json
missions/generated/revisions/proposals/<proposal_id>/source_mission.json
missions/generated/revisions/proposals/<proposal_id>/source_report.json
missions/generated/revisions/missions/<revision_id>/mission.json
missions/generated/revisions/missions/<revision_id>/revision.json
```

Las claves se registran por separado para propuestas y revisiones, bajo mutex de
archivo entre procesos. Mismos argumentos y clave recuperan el artefacto; otros
argumentos bajo la misma clave producen `CONFLICT`. La fuente modificada produce
error, aunque la clave ya exista. Antes de construir se persiste una intención
`BUILDING`; una interrupción no crea otra revisión al reintentar. Ese caso requiere
reconciliar el artefacto incompleto: no hay reparación automática ni garantía de
transacción durable ante pérdida del host/disco. Guardar una revisión no concede
consentimiento ni reserva/libera `v1`.

LangGraph: la validación y el replanner se reutilizan a través del grafo existente
`waypoint_mission_graph`. La persistencia de propuestas y aplicación de cambios
son servicios deterministas, no un grafo conversacional nuevo. Hermes interpreta
y pregunta; no se invoca `mission_editor` como segundo LLM.

## 2. Geometría relativa en borradores

`planning.relative_routes.generate_relative_route` es un servicio reutilizable.
La entrada MCP `generate_draft_route(draft_id, expected_revision, request,
replace_route=false)` lo integra en el borrador existente. Devuelve ruta efectiva,
waypoints, método, parámetros y campos pendientes. Si faltan decisiones esenciales
guarda la intención estructurada parcial en el propio borrador y devuelve lo
pendiente, sin generar waypoints. Hermes debe preguntar; HOME no basta.

- `mode=offsets`: lista ordenada de `{north_m, east_m}`, en metros. Mantiene el
  orden del operador. La primera posición debe diferir de HOME. No admite puntos
  consecutivos a menos de 1 mm, ni un cierre ya incluido: se pide con `close_route`.
- `mode=rectangle`: `length_m`, `width_m`, `orientation_deg`, `traversal` y
  `home_position`. Orientación en grados [0,360), desde norte hacia este, de la
  arista de longitud. El eje de anchura está a su derecha.
- Esquinas A, B=A+longitud, C=B+anchura, D=A+anchura. `clockwise` recorre A,B,C,D;
  `counterclockwise` recorre A,D,C,B. El nombre del sentido corresponde al plano
  norte/este. `home_position=corner` coloca HOME en A: los waypoints empiezan en
  B o D, para evitar el tramo horizontal nulo que rechaza el validador existente.
  `center` coloca HOME en el centro y A en (-longitud/2,-anchura/2) de esos ejes.
- `close_route=true` termina en A a altitud de vuelo; si HOME está en el centro,
  repite A como último waypoint. Es independiente de `return_to_home`, que se
  debe declarar también. Con HOME en esquina, ruta abierta tiene tres waypoints
  y cerrada cuatro; con HOME central son cuatro o cinco.
- HOME latitud/longitud explícitos, `home_altitude_m=0`,
  `altitude_reference=relative_to_home` y `altitude_m>0` para todos los puntos.
  No admite AMSL ni mezcla referencias. No decide regreso, cierre, sentido,
  orientación o ubicación de HOME silenciosamente.

Método `local_linear_111320_cos_home_v1`: reutiliza la escala del mapper existente,
111320 m/grado de latitud y esa escala multiplicada por cos(latitud HOME) para
longitud. Es aproximación local, no geodesia exacta. Radio máximo de cada punto
1000 m, |latitud| de HOME y puntos <=75°, sin cruce de antimeridiano; rectángulos
con dimensiones >=1 cm, offsets con máximo 200 puntos de entrada. Se rechazan
NaN/infinito, dimensiones inválidas, degeneración y dominios no soportados. Los
tests contrastan distancias y rumbos con haversine/bearing esféricos independientes:
0.5% de distancia y 0.05° de rumbo para las referencias ensayadas, incluido radio
1 km y latitud 74°. Es tolerancia de estos tests, no garantía universal de precisión.
No comprueba cobertura agrícola, obstáculos ni espacio aéreo.

`draft_revision` y `draft_sha256` se guardan junto a `draft.json`, en
`draft_state.json`. La operación geométrica exige versión vigente y
`replace_route=true` para reemplazar una ruta existente: elimina todos los
waypoints anteriores, conserva batería, viento, límites y demás campos. HOME y
regreso se actualizan con los parámetros explícitos. Mientras exista intención
geométrica, una lista manual requiere reemplazo explícito y desvincula esa
intención; no se mezclan listas manuales y parámetros geométricos en una llamada.

Los clientes previos de `update_mission_draft` y `finalize_mission_draft` pueden
omitir `expected_revision`; las actualizaciones se serializan, pero sin ese
argumento mantienen semántica de última escritura por campo y no detectan una
intención obsoleta. Nuevos clientes deben aportar la versión. Borradores antiguos
sin metadatos se leen como v0 con procedencia desconocida; no se migran al consultar.
Un fallo entre escrituras de borrador/sidecar se detecta por hash y bloquea edición,
sin restaurar ni sobrescribir archivos silenciosamente. La consulta sin mutex
puede devolver error transitorio al coincidir con una escritura: repetir sólo la
consulta. No se promete una transacción de varios archivos ante caída del host.

Finalizar construye `MissionDefinition`, valida y exporta por los mismos servicios.
Guarda `source_draft.json`, copia del sidecar existente en `source_draft_state.json`
y `finalization.json` con versión/hash de borrador/metadatos, hash JSON final,
hash `.plan`, defaults efectivos y atribución no autenticada. Se genera snapshot nuevo cada vez;
retener `finalization_id` y consultar el estado si se pierde una respuesta, sin
repetir finalización a ciegas. La ruta resultante se puede entregar al preflight
existente sólo tras la petición explícita de ensayo. No se inicia automáticamente.
LangGraph interviene en la validación final existente; la geometría no usa LLM ni
un workflow adicional.

## 3. Consulta de estado y conversación

`get_mission_state` recibe exactamente uno de `draft_id`, `revision_id`, `run_id`.
Opcionalmente `finalization_id` selecciona un snapshot de `draft_id`. Es de sólo
lectura: sin mkdir, escritura, revalidación, exportación, readiness, reserva,
liberación, spawn, inicio ni reanudación. Devuelve lo conocido de borrador actual,
artefactos, validación guardada/plan, propuestas, revisiones, ensayos y siguientes
acciones. `KNOWN_WITH_WARNINGS` conserva incertidumbres; `ERROR` de integridad no
repara archivos; `NOT_FOUND` no inicia nada.

Reutiliza los sidecars junto a cada artefacto. La admisión asíncrona nueva captura
`source_artifact` con identificador, tipo y hashes del contenido y sidecar; el
worker lo conserva en el estado/informe del mismo LangGraph. El preflight síncrono
captura ese vínculo al hacer snapshot si existe un sidecar verificable. Una misión
JSON ordinaria sigue siendo válida sin él. Sólo se asocian ensayos por ese vínculo
más hash; propuestas por ID de ensayo y hashes de informe/snapshot; revisiones por
ID/hash de la propuesta revisada. También recorre los descendientes con vínculos
explícitos. No crea otro almacén de estados ni elige por nombre, fecha, similitud,
archivo más reciente o incluso igualdad de bytes sin vínculo de procedencia.

Los informes históricos se pueden explicar por `run_id`. Si no guardan vínculo a
borrador/finalización, la relación es `UNKNOWN`; no se inventa retrospectivamente.
`PASSED` se muestra para su snapshot simulado, no para el borrador actual. Cambiar
un borrador deja `matches_current_draft=false` en la versión anterior y exige nueva
evaluación. El hash no firma archivos ni evita cambios externos entre lecturas;
no se resuelve todo TOCTOU. Los archivos se verifican localmente, no se autentican.
La consulta no ofrece una instantánea transaccional global de todos los directorios.
Un artefacto creado durante ella puede aparecer en la consulta siguiente.

Admisión, ejecución, resultado y consentimiento están separados. Readiness
guardada es histórica: `readiness_now=UNKNOWN_NOT_CHECKED` siempre. `APPROVED`,
`PASSED` y esta consulta no conceden consentimiento. `INTERRUPTED`/`UNCONFIRMED`
no confirman aterrizaje ni autorizan liberar `v1`. El siguiente paso propuesto no
se ejecuta por el hecho de figurar en la respuesta.

Hermes conserva IDs, revisiones, hashes revisados y claves; pregunta por campos
pendientes. Guardar/validar lo ya solicitado no necesita otra confirmación.
Finalizar/revisar ya valida y exporta: explicar el resultado sin repetir ambas
operaciones. Para un ensayo explícitamente solicitado registra clave ANTES del
inicio y consulta el mismo `run_id` cada 15–30 s. Tras perder respuesta o
`/reload-mcp`, recupera por clave; nunca repite inicio. El worker no arranca la
simulación. Las variantes síncronas siguen sujetas al timeout del cliente y una
respuesta perdida no cancela su backend. No se cambió la configuración MCP.
LangGraph mantiene el workflow de ensayo; esta consulta sólo lee sus registros.

## Demo conversacional pendiente

Cada bloque siguiente es un prompt de una sola línea, sin nombres de herramientas.
Son instrucciones para pruebas posteriores: no se ejecutaron en este incremento.
Conservar la transcripción y los identificadores que devuelva Hermes.

Petición incompleta:

```text
Quiero preparar una misión llamada Parcela Norte con un recorrido rectangular de 40 por 20 metros; guarda lo que ya sabemos y pregúntame los datos que faltan, sin iniciar simulación ni vuelo.
```

Petición completa, en una conversación nueva:

```text
Prepara y valida la misión Rectángulo Demo para drone_01, multirrotor ArduPilot, objetivo tránsito en parcela de prueba, velocidad 20 km/h, batería declarada 95% y consumo declarado 0.8% por minuto, viento declarado 0 km/h procedente del norte, reserva mínima 20%, viento máximo 30 km/h y altitud máxima 50 m; genera un rectángulo de 40 m de longitud y 20 m de anchura con HOME en su centro a latitud 41 y longitud 2, HOME a 0 m como referencia relativa, vuelo a 10 m sobre HOME, arista de longitud orientada a 0 grados desde el norte hacia el este, recorrido horario, cierre en el primer vértice y regreso posterior a HOME; guarda el JSON y el plan QGC y explícame el resultado, sin ensayar ni arrancar simulación.
```

Aclaración de orientación sobre el primer borrador:

```text
Para el borrador que acabamos de guardar, la arista de longitud apunta a 90 grados medidos desde el norte hacia el este, HOME está en el centro, el recorrido es antihorario, quiero cierre en el primer vértice y regreso a HOME, y la altitud es 10 m sobre HOME con referencia de HOME a 0 m; conserva los demás datos y dime qué falta todavía.
```

Misión insegura, después de preparar la completa:

```text
En ese mismo borrador cambia únicamente la batería declarada a 1%, guarda una nueva versión, valida y genera el plan candidato si queda bloqueada; explica los motivos sin reducir reservas o límites y sin ejecutar un ensayo.
```

Revisión tras intervención explícitamente declarada, usando la evidencia histórica:

```text
Revisa el informe final 0844c190-59c8-40cf-991e-93cebbd3cf02 y guarda una propuesta con clave joel-propuesta-bateria-01; he sustituido físicamente la batería y declaro un nivel nuevo del 95%, acepto cambiar sólo ese nivel en una misión nueva con clave joel-revision-bateria-01, registra que es mi declaración y no una medida de telemetría, valida y exporta sin modificar el original ni ejecutar vuelos.
```

Recarga MCP, comando separado y de una línea:

```text
/reload-mcp
```

Recuperación, manteniendo las claves de la conversación anterior:

```text
Recupera el ensayo ya existente de la clave joel-preflight-async-01, conserva su identificador y explícame su estado y los artefactos que estén vinculados de forma verificable; si falta algún vínculo dilo, sin iniciar, repetir ni reanudar vuelos.
```

Explicación de un resultado conocido por ID:

```text
Explica el ensayo f5f55084-5af6-4e58-ab1a-ce30a13832b3 usando su informe persistido: waypoints, regreso, aterrizaje, desarmado, alcance exacto del PASSED y qué sigue desconocido sobre disponibilidad actual y consentimiento para otro vuelo.
```

## Evaluación y evidencias necesarias

| Escenario | Criterio de aceptación | Implementado / comprobado offline | Pendiente conversacional u operativo |
| --- | --- | --- | --- |
| Batería bloqueada | Propuesta no altera porcentaje; declaración explícita crea copia, diff y `.plan`; puede seguir BLOCKED | Sí: informes conservados, validación/editor/exportador reales; 95% aprobado y 11% aún bloqueado | Transcripción Hermes con declaración y claves |
| Readiness bloqueada | Infraestructura pendiente sin parche ni arranque | Sí: informe histórico y workflow con readiness doble | Estado real se comprueba sólo en ensayo autorizado posterior |
| FAILED WP3 | Diagnóstico disponible y LAND conservados, causa desconocida, sin arreglo inventado | Sí: informe histórico y propuesta de investigación | Investigación causal sigue abierta |
| PASSED histórico | No corrección innecesaria; snapshot/hash y alcance exactos | Sí: informe f5f55084 y analizador real | No se repitió su vuelo; interacción histórica ya documentada aparte |
| Integridad y concurrencia | Fuentes intactas, provisional/incoherente rechazado, clave repetida única, argumentos distintos CONFLICT, recarga recupera | Sí: hashes, hilos, corrupción y fallo de persistencia inyectados | Fallos de host/disco y reconciliación manual no evaluados |
| Geometría | Decisiones explícitas, norte/este y sentido correctos, dominio acotado | Sí: referencias esféricas independientes y valores inválidos | Conversación de aclaración y revisión visual de ruta |
| Reemplazo/versiones | Sin waypoints sobrantes, otros campos conservados, versión obsoleta rechazada | Sí: merge, reemplazo y finalización reales | Experiencia de dos conversaciones editando el mismo borrador |
| Estado y vínculos | Sólo IDs/hashes persistidos; consulta sin efectos ni revalidación | Sí: cadena borrador→ensayo→propuesta→revisión→ensayo con dobles, recarga e igualdad de bytes sin vínculo | Demo Hermes del nuevo resumen y recuperación |
| Ensayo geométrico/revisado | Gate, readiness, compatibilidad y aceptación originales; consentimiento nuevo | Pipeline conservado; infraestructura/executor sólo dobles | Nuevo vuelo explícitamente autorizado, no realizado aquí |

Los 198 tests de la base eran offline. La prueba operativa anterior del worker y
`/reload-mcp`, con tres puntos, regreso y LAND/desarmado PASSED, sigue siendo la
registrada en `docs/async-virtual-preflight.md`. No valida operativamente estos
bloques nuevos ni las correcciones posteriores de exclusión. La parada posterior
`remaining=[]` y comprobación secuencial `NOT READY` siguen atribuidas a la
transcripción del operador. No se resolvió la causa del fallo anterior WP3 ni se
probó resistencia a reinicios del host.

Comprobación offline de este incremento (un comando por línea):

```bash
.venv/bin/python -m pytest -q tests/test_mission_revisions.py
```

```bash
.venv/bin/python -m pytest -q tests/test_relative_routes.py tests/test_hermes_mission_planning.py
```

```bash
.venv/bin/python -m pytest -q tests/test_mission_state.py tests/test_virtual_preflight_jobs.py tests/test_virtual_preflight.py tests/test_hermes_mcp_server.py
```

```bash
.venv/bin/python -m pytest -q
```

```bash
git diff --check
```

Resultado del incremento inicial, antes de la corrección conversacional siguiente: **259 tests passed in 7.08s** en la suite
completa offline. `git diff --check` y revisión de whitespace de los archivos nuevos
sin errores nuevos. Se conservaron por SHA-256 las 17 evidencias y los documentos
históricos como prefijo; no se normalizaron los espacios finales del log antiguo.

Archivos de este incremento, incluidos los nuevos:

| Área | Archivos |
| --- | --- |
| Propuestas/revisiones y utilidades | `planning/artifact_store.py`, `planning/verified_preflight.py`, `planning/mission_revisions.py`, `tests/test_mission_revisions.py` |
| Geometría/borradores | `planning/relative_routes.py`, `tools/hermes_mission_planning.py`, `tests/test_relative_routes.py` |
| Estado y vínculos | `planning/mission_artifacts.py`, `tools/mission_state.py`, `tests/test_mission_state.py`, `graph/virtual_preflight_state.py`, `graph/virtual_preflight_graph.py`, `tools/virtual_preflight.py`, `tools/virtual_preflight_jobs.py`, `tools/virtual_preflight_worker.py` |
| MCP y documentación | `tools/hermes_mcp_server.py`, `docs/mission-lifecycle-demo.md`, `docs/async-virtual-preflight.md`, `documentation/development_log.md` |

## Corrección tras la primera prueba conversacional

El operador comunicó que Hermes añadió objetivo `survey`, contenido agrícola,
`maximum_altitude_m=20` y `return_to_home=true` a una petición que sólo aportaba
nombre y dimensiones. También interpretó una consulta sin identificador como
inventario vacío. La inspección local confirmó el borrador
`08de7c26-99fc-41b6-8e7f-65722e309152`, revisión 2 y SHA-256
`00a5119906c2ff177ff23e38d907a6c0d4d297a2cf6bf6148e5eb921b28f2a19`, con esos
valores, waypoints vacíos, `route_provenance=null` y etiqueta `OPERATOR_INPUT`.
Las dimensiones estaban en texto libre, sin intención geométrica estructurada.
La secuencia y atribución al diálogo proceden de la transcripción comunicada:
no disponemos de los argumentos exactos de todas las llamadas. Los archivos
locales corroboran el estado persistido, no quién aportó cada valor.
Ese borrador, metadatos y archivo de lock se conservan sin edición ni migración.

### Contrato de intención parcial

Se reutiliza `RelativeRouteRequest` dentro de `MissionPlanDraft.geometry_intent`.
Por ejemplo, nombre y `{mode: rectangle, length_m: 40, width_m: 20}` se pueden guardar
juntos con una única actualización de borrador. No se insertan objetivos, límites,
alturas, condiciones físicas ni regreso que no estén en los argumentos aportados.
Las instrucciones de Hermes prohíben deducirlos del nombre o de la forma.
El backend no analiza lenguaje natural ni puede detectar por sí solo si Hermes
inventó un argumento que es válido según el esquema.

- Un valor omitido o `null` conserva el conocido. `false` y cero válidos se
  conservan como valores explícitos. Una lista de offsets sustituye la lista
  completa; no se añaden segmentos por merge.
- Seleccionar un modo antes desconocido conserva sus parámetros compatibles.
  Cambiar entre modos explícitos elimina todos los antiguos parámetros de forma
  (dimensiones, orientación, sentido, ubicación relativa de HOME u offsets) y
  conserva HOME, altitud/referencia, cierre y regreso. Los parámetros explícitos
  nuevos se validan; no se descartan silenciosamente si son incompatibles.
- HOME y regreso se pueden aportar en misión o intención. Se sincronizan por copia
  determinista; valores contradictorios en la misma petición producen error.
- Una intención parcial persiste en `draft.json`; `draft_state.json` guarda
  `geometry_revision`, hash de intención y procedencia junto a `draft_revision`.
  No hay otro almacén. Las ediciones geométricas de borradores existentes exigen
  la revisión actual; los conflictos y entradas inválidas no sustituyen el estado
  válido anterior.
- Mientras no exista ruta, se pueden completar los parámetros sin reemplazo.
  Cambiar una intención con waypoints existentes exige `replace_route=true`.
  Si queda incompleta, retira todos los waypoints y la procedencia de la ruta
  anterior. Cuando se completa, genera la lista nueva entera. La validación de
  dominio y generación usan el mismo servicio geométrico, también para datos
  conocidos de peticiones incompletas.
- Reemplazar explícitamente por una lista manual desvincula la intención
  geométrica y sustituye todos los waypoints. El merge manual anterior sigue
  disponible para borradores sin intención. No se mezcla una lista manual con
  un parche geométrico en la misma petición.

Las respuestas de guardado/generación, finalización y consulta exponen
`mission_missing_fields`, `geometry_missing_fields` y `pending`:
`route_generation` enumera las decisiones geométricas y `mission_finalization`
combina ambas clases de impedimentos. `geometry` devuelve estado y ruta calculada
sólo si es completa. Dar HOME deja pendientes orientación, sentido, altura y
referencia, posición del HOME, cierre y regreso si no fueron aportados. La
construcción compartida rechaza también una geometría incompleta o divergente
cuando se invoca fuera de MCP. Finalizar valida/exporta una sola vez cuando lo
solicita el operador y hay datos; no ensaya ni arranca infraestructura.

### Procedencia y defaults

`OPERATOR_INPUT` era una etiqueta demasiado fuerte para datos procedentes de un
agente. Las respuestas nuevas usan `UNVERIFIED_AGENT_INPUT`; los registros antiguos
sin atribución por campo se presentan como `UNKNOWN_LEGACY_INPUT`, exponiendo la
etiqueta antigua en `stored_provenance_status` sin reescribirla. No se interpreta
texto libre para inventar intención geométrica ni procedencia retrospectiva.

`attributions` es un argumento opcional con rutas JSON-pointer de hechos que
realmente figuran en la actualización, como `/name` o
`/geometry_intent/length_m`. Cada entrada puede declarar:

| Origen expuesto | Significado |
| --- | --- |
| `OPERATOR_DECLARED_VIA_AGENT` | Hermes afirma que el operador declaró ese valor y aporta una frase de apoyo. Sigue con `authenticated=false`. |
| `UNKNOWN` | Valor recibido del agente sin atribución por campo suficiente o heredado de un registro que no la guardaba. |
| `DETERMINISTIC_GENERATION` | Coordenadas/waypoints calculados por el generador a partir de parámetros; no acredita el origen de esos parámetros. |
| `DETERMINISTIC_DERIVATION` | Copia entre campos compartidos de misión/intención; conserva referencia al campo de origen, sin autenticarlo. |
| `COMPATIBILITY_DEFAULT` | Valor efectivo del constructor anterior, expuesto aparte en `compatibility_defaults`; no es declaración del operador. |

No se puede usar `attributions` para declarar defaults ni atribuir campos que no
se enviaron. Se conservan hashes de valor y se detectan incoherencias con los
metadatos; un hash no firma el diálogo. No existe fuente conversacional autenticada
ni se verifican por telemetría estas declaraciones. Un esquema sólo comprueba
estructura/dominio, no fidelidad de la extracción del LLM. La conducta de Hermes
exige nueva prueba conversacional y conservar su transcripción/argumentos.

Se mantienen los defaults anteriores de ID generado, `drone_01`, `navigate`,
regreso y failsafes; aparecen identificados sin rellenar silenciosamente el
borrador. El regreso predeterminado no se aplica mientras la geometría espera una
decisión explícita (`applies_on_finalization=false`). No se crean defaults de
seguridad. Antes de autorizar un ensayo, Hermes debe mostrar valores efectivos,
defaults aplicables y límites de procedencia. Guardar o validar lo solicitado no
necesita otra confirmación. No se incorpora un token de consentimiento ni un
requisito nuevo al gate. El snapshot final conserva también los metadatos fuente
y su hash para poder explicar la atribución de esa versión.

`get_mission_state` requiere un identificador retenido: sin él devuelve
`ERROR`, `error_code=INVALID_ARGUMENTS`, `lookup_performed=false` e inventario
`UNKNOWN`. No establece que falten borradores ni inicia exploraciones para elegir
el más reciente. La consulta es de sólo lectura y muestra intención, versiones,
ruta, procedencia y pendientes sin migrar datos. Las instrucciones piden usar esa
respuesta directamente, sin descubrimiento redundante de recursos o archivos.

### Conversación de prueba con un borrador nuevo

Usar un nombre nuevo y conservar el UUID devuelto; nunca continuar el borrador de
la incidencia. Cada bloque siguiente corresponde a un turno. No se ha ejecutado
esta conversación durante el desarrollo.

```text
Quiero preparar una misión nueva llamada Circuito Relativo Nuevo con un recorrido rectangular de 40 por 20 metros; guarda lo conocido y pregúntame las decisiones y datos pendientes, sin iniciar simulación ni vuelo.
```

Recargar la conexión después de que Hermes comunique el UUID; comando separado:

```text
/reload-mcp
```

```text
Recupera el mismo borrador nuevo por el identificador que conservamos y muéstrame nombre, dimensiones estructuradas, versión, procedencia y qué falta para generar la ruta y para finalizar, sin editarlo ni buscar otro por nombre o fecha.
```

```text
En ese borrador, HOME está en latitud 41 y longitud 2 y su referencia relativa es 0 metros; conserva las dimensiones y los demás datos y dime qué decisiones faltan todavía, sin asumir orientación, altura de vuelo, sentido, cierre ni regreso.
```

```text
Para esa ruta quiero la arista de longitud a 0 grados medidos desde el norte hacia el este, recorrido horario, HOME en el centro del rectángulo, vuelo a 10 metros relativos a HOME, cierre en el primer vértice y regreso después a HOME; conserva los 40 por 20 metros y guarda la ruta, sin validar ni ensayar todavía.
```

```text
El objetivo es tránsito de prueba al circuito de ensayo; el vehículo es drone_01, multirrotor con ArduPilot, crucero 20 km/h, y declaro batería 95%, consumo 0.8% por minuto y viento 0 km/h procedente del norte; para esta misión fijo reserva mínima 20%, viento máximo 30 km/h y altitud máxima 50 m, guarda estos datos sin iniciar simulación ni vuelo.
```

```text
Ahora finaliza ese borrador, valida y exporta su JSON y plan QGC; explícame el resultado, rutas, valores efectivos, defaults y límites de procedencia, sin pedir otra confirmación para guardar o validar y sin autorizar ni ejecutar un ensayo.
```

Si el identificador ya no está en el contexto, el operador debe aportar el UUID
retenido. Un error de argumentos o ID desconocido no permite elegir otro borrador.

| Escenario añadido | Aceptación offline | Pendiente |
| --- | --- | --- |
| Nombre y dimensiones | Sólo hechos enviados, intención parcial persistida, sin objetivo/límites/regreso inventados por el backend | Fidelidad de Hermes ante peticiones equivalentes |
| HOME y recarga | Dimensiones conservadas; todas las decisiones restantes visibles; consulta sin escrituras | Transcripción real antes/después de recarga |
| Ediciones entre turnos | Merge, modos, reemplazo, versión y coherencia de archivos comprobados con temporales | Experiencia conversacional de aclaración/reemplazo |
| Procedencia/defaults | Declaración del agente, desconocido, generación y defaults separados; legado no migrado ni autenticado | Fuente conversacional verificable y consentimiento técnico |

Test específico, sin Docker ni vuelos:

```bash
.venv/bin/python -m pytest -q tests/test_partial_geometry_planning.py
```

Verificación final de la corrección: **290 passed in 7.84s**, suite completa offline
(con 31 casos nuevos específicos). Sin defectos nuevos en `git diff --check` ni en
los archivos nuevos. Se conservaron por hash los tres archivos de la incidencia y
las 17 evidencias anteriores; la nueva conversación queda pendiente de ejecución
por el operador. Sin Docker, simulación, vuelos, MCP operativo, commit ni push.

## 18/10/2026 — Evidencias conversacionales y respuestas resumidas

El operador comunica nuevas conversaciones que produjeron la finalización
`8be78baa-4cf4-4f65-8531-9388d030c3ed`, las revisiones aprobada
`b880d6c3-4557-42c7-ada4-5a04db5e9237` y bloqueada al 11%
`89c3da7d-bc20-42ae-baeb-21d4e839355a`, y cuatro propuestas de batería, WP3, PASSED
e infraestructura. Se verificaron los artefactos locales y se conservaron
[31 copias y un manifiesto](../simulation/ros2_gazebo/results/hermes_conversational_2026_10_18/README.md)
con rutas originales y SHA-256. Las conversaciones/compacciones son observaciones
del operador; no se dispone de una transcripción autenticada de todos los argumentos.
Los ficheros corroboran estado, vínculos y contenido guardados, no fidelidad del LLM.

### Compatibilidad de vistas

Las tres consultas MCP `get_mission_state`, `get_revision_proposal` y
`get_virtual_preflight` pasan a versión de servidor **0.3.0**:

- Sin argumento nuevo devuelven `view="summary"`, con `summary_schema_version=1`.
  Es un cambio del formato predeterminado MCP: clientes que necesiten el árbol
  anterior deben enviar **`view="detail"` explícitamente**.
- `view="detail"` devuelve el formato completo previo. Los backends Python
  conservan sus defaults anteriores; `tools.mission_state.get_mission_state`
  añade `view` con default `detail`. No cambian los resultados de operaciones
  de escritura, validación, exportación o ejecución.
- Las mismas comprobaciones de lectura/identidad/hash se ejecutan antes de elegir
  vista. No se crea caché, almacén o resultado sintético y no se reduce el alcance
  de verificación para ahorrar tamaño.
- El resumen mantiene estado, IDs, hashes de misión/registros, integridad,
  validación y sus errores/motivos/recomendaciones, vínculos, defaults, incertidumbres
  y siguientes acciones. El borrador presenta hechos principales, intención
  geométrica, número de puntos y recuentos de origen, sin repetir coordenadas ni
  atribuciones completas. Las revisiones se almacenan una vez en `artifacts`;
  `revisions` contiene referencias por ID.
- Los informes resumen eventos, puntos alcanzados y evidencia de aterrizaje,
  conservan análisis, recuperación, diagnóstico disponible y readiness tal como
  fue registrado. Los errores de payloads omitidos se conservan en `error_evidence`
  con ubicaciones de origen; no se recortan mensajes ni se cambia FAILED a PASSED.
  Los errores de consulta y estados desconocidos se conservan completos.
- `detail_access` devuelve herramienta y argumentos de consulta con identificadores
  reales y `view=detail`. Se solicita detalle cuando haga falta evidencia concreta,
  no para reconstruir reiteradamente todo el árbol. No hay límite duro de bytes:
  una lista grande de errores o readiness extensa se conserva aunque reduzca menos.

Hermes debe conservar IDs y claves y usar las herramientas del proyecto. No inventar
identificadores/rutas, elegir el último fichero ni explorar directorios para rehacer
el estado. Si se pierde respuesta de una escritura, consultar por el borrador o
ensayo fuente retenidos; no repetir finalización, edición o construcción. Para
el ensayo asíncrono se recupera por su clave mediante la consulta de preflight.
Si no se dispone de identificador/clave verificable, se informa de incertidumbre
y se reconcilia con el operador: no se crea otro artefacto para adivinar el anterior.

### Interpretación de resultados

SITL requiere una petición/autorización explícita del ensayo simulado, **no permiso
para hardware real ni una intervención física de batería**. Se puede declarar
explícitamente un escenario simulado; no se presenta como telemetría ni trabajo
físico realizado. `hardware_authorized=false` limita el alcance del informe, no es
un prerrequisito pendiente para SITL. El gate, compatibilidad, readiness, exclusión
y consentimiento del ensayo siguen vigentes.

Las recomendaciones y la investigación pendiente son propuestas: no añaden por sí
solas bloqueos técnicos al gate. La validación sí bloquea la revisión al 11% por
reserva insuficiente. El PASSED de otro ensayo no demuestra la causa ni la solución
del WP3 anterior. `qgc_plan_path=null` en un informe significa que esa operación no
registró exportación; no demuestra ausencia de planes anteriores. Sólo se relacionan
exportaciones mediante vínculos verificables, sin inventar relaciones por nombre.

Los nombres implementados en `check_sim.sh` son `Docker container`, `Gazebo server`,
`ArduPilot processes`, `ROS 2 vehicle interfaces` y `Pre-arm checks`. Esta enumeración
identifica el código, no cinco pruebas ejecutadas en cada informe. La fuente de
infraestructura conservada sólo registra PASS del primer control y FAIL del segundo;
no acredita ejecución del resto ni readiness actual. No se renombra a controles
no registrados ni se deducen comprobaciones de vuelo/obstáculos/espacio aéreo.

### Medición sobre los artefactos disponibles

JSON UTF-8 con `ensure_ascii=false`, `allow_nan=false` e indentación de dos espacios;
consultas Python de sólo lectura, sin llamadas MCP operativas. El formato compacto,
consultas exactas y hashes de respuestas están en
[`response_sizes.json`](../simulation/ros2_gazebo/results/hermes_conversational_2026_10_18/response_sizes.json).
El detalle mantuvo los tamaños medidos antes de introducir la proyección.

| Consulta por ID retenido | Detalle (bytes) | Resumen (bytes) | Reducción |
| --- | ---: | ---: | ---: |
| Borrador geométrico 1f84f808… | 48.842 | 5.698 | 88,33% |
| Revisión aprobada b880d6c3… | 21.866 | 13.198 | 39,64% |
| Revisión bloqueada 89c3da7d… | 21.866 | 13.198 | 39,64% |
| Ensayo FAILED d4519cab… | 16.477 | 12.290 | 25,41% |
| Ensayo PASSED f5f55084… | 18.042 | 10.281 | 43,02% |

Estas medidas dependen de las rutas y artefactos locales; no representan el framing
MCP, duplicación posible entre texto/structuredContent, tokens ni compacciones.
Falta repetir el uso conversacional de estas vistas para evaluar su efecto real.
Los tests offline validan contrato/semántica, no fidelidad o memoria del LLM.

Tras recargar MCP, prompts de consulta sin escrituras (una línea cada uno):

```text
Consulta el resumen del borrador 1f84f808-c688-48c9-b7da-1b1c4b29c094 y su finalización 8be78baa-4cf4-4f65-8531-9388d030c3ed por sus identificadores, explica validación, vínculos e incertidumbres y no leas archivos ni repitas escrituras o ensayos.
```

```text
Ahora solicita el detalle completo de esa misma finalización para revisar los waypoints y su procedencia, sin modificar nada ni iniciar simulación.
```

```text
Compara por sus identificadores las revisiones b880d6c3-4557-42c7-ada4-5a04db5e9237 y 89c3da7d-bc20-42ae-baeb-21d4e839355a, resume por qué una está aprobada y otra bloqueada y distingue el escenario simulado de una medida física.
```

```text
Consulta el resumen de la propuesta e44903a2-0405-4ea5-99c7-7233ce0ea333 y explica la evidencia del fallo WP3 y su recuperación, sin atribuir una causa demostrada al PASSED posterior ni repetir vuelos.
```

## 18/10/2026 — Evaluación actualizada tras el ensayo geométrico

Esta actualización conserva las tablas anteriores como registro de sus respectivas
etapas. El ensayo operativo ya fue realizado por el operador; aquí sólo se leen,
copian y verifican sus artefactos. Las
[evidencias ampliadas](../simulation/ros2_gazebo/results/hermes_conversational_2026_10_18/README.md)
incluyen manifiesto e informe bruto.

| Escenario | Comprobación actual y fuente | Límites pendientes |
| --- | --- | --- |
| Flujo geométrico construido por conversación | Operador comunica la conversación; finalización 8be78baa del borrador 1f84f808 conserva rectángulo 40×20 m, HOME central, altitud relativa 5 m, cierre con cinco puntos y regreso | Los artefactos no autentican la conversación ni todos los argumentos MCP |
| Primera petición incompleta | Operador comunica inferencias indebidas de objetivo/agricultura, límites y regreso; estado local de la incidencia ya documentado y conservado | No presentar la sesión completa como libre de errores del agente |
| Ensayo geométrico SITL | Run 4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4: PASSED/COMPLETED; once checks true, WP1–WP5 y regreso alcanzados; LANDED true, armed false, flying false | Resultado del snapshot concreto, sin consentimiento para otro vuelo |
| Integridad y vínculo fuente | Fuente, input y snapshot idénticos: SHA-256 fee5185407a7f63810a62f652062454f83790aa2b8a7234f869a7d93eda3a936; source_artifact coincide en job/informe y con el hash de finalización | Hash local, sin firma ni solución completa de TOCTOU |
| Duración y asincronía | Workflow 480,344587 s; executor 471,332987 s; job FINISHED y log PASSED persistidos; ambos intervalos exceden 300 s | No son tiempo en vuelo; no se mide aquí latencia MCP ni resistencia a reinicios del host |
| Consulta final y exclusión de v1 | Operador comunica FINISHED y vehicle_restriction=null; FINISHED corroborado por job.json | Respuesta de consulta/liberación histórica no conservada como artefacto verificable |
| Readiness | Informe registra PASS de Docker container, Gazebo server, ArduPilot processes, ROS 2 vehicle interfaces y Pre-arm checks | Disponibilidad histórica; no se comprueba la actual |
| Respuestas y compacciones | Operador comunica exploración redundante y errores de resumen; mediciones anteriores de bytes conservadas | Efecto sobre compacciones sin evaluación controlada; conexión de vistas pendiente en este árbol |
| Alcance | Ensayo de navigate en v1 simulado, regreso por navegación y LAND | Sin prueba de causa del WP3 anterior, agricultura, seguimiento de velocidad, carga del .plan, RTL ni hardware |

### Defectos reproducidos en la revisión offline del árbol actual

Los apartados anteriores que anuncian MCP 0.3.0 y `view=summary/detail` describen
el contrato previsto y las mediciones históricas, **no una integración operativa
confirmada en este árbol**. `tools/hermes_mcp_server.py` declara versión 0.2.0,
no importa las proyecciones y sus tres consultas no aceptan `view`;
`tools/mission_state.py` tampoco lo acepta. El módulo de proyecciones existe,
pero no está conectado a esas entradas. En consecuencia, no debe prometerse que
los prompts de resumen anteriores ya reducen la respuesta MCP.

Además, `error_evidence` devuelve un diccionario por ubicación y el test del
contrato espera una lista de objetos con `value`: hay una discrepancia concreta
de formato. La prueba focalizada previa a esta ampliación produjo **11 failed,
5 passed in 2.72s**. La suite completa posterior produjo **11 failed, 296 passed
in 9.25s**. El resultado histórico de 307 tests del registro no se ha reproducido
en este árbol; se conserva como historia, sin atribuirle vigencia. Estos defectos
quedan pendientes de corrección; esta revisión documental no modifica la
integración MCP ni redefine el formato para hacer pasar las pruebas.

## 18/10/2026 — Corrección posterior offline de las vistas registradas

Esta corrección sucede después del PASSED operativo del rectángulo. No se ha
repetido su ensayo ni modificado ninguna de las 37 copias, el manifiesto o los
originales. Las limitaciones de conexión descritas en el apartado anterior quedan
corregidas y verificadas **offline** en este incremento; la historia se conserva.

El servidor declara ahora 0.3.0 y las herramientas realmente registradas
`get_mission_state`, `get_revision_proposal` y `get_virtual_preflight` anuncian
`view` como enum `summary/detail`, default `summary`. `detail` conserva la respuesta
completa anterior sin añadirle metadatos de resumen. Los errores de consulta y
NOT_FOUND se devuelven completos, sin exigirles la etiqueta `view=summary`.
Los backends Python de propuestas/preflight conservan sus contratos completos;
el de estado permite elegir vista y mantiene default `detail`.

La proyección se aplica después de las mismas comprobaciones de cada backend.
No añade validaciones operativas ni reduce las comprobaciones existentes.
Conserva resultados, validación, motivos, incertidumbres, defaults, consentimiento,
restricciones de vehículo y vínculos pertinentes. El detalle de campo/procedencia
y resultado bruto siguen accesibles con los IDs de `detail_access`. Las entradas
inválidas de `view` se rechazan por el SDK antes de llamar al backend.

### Contrato de errores del resumen

`error_evidence` es siempre una **lista de objetos `{path, value}`** cuando la
respuesta está proyectada; sin errores es `[]`. `path` es un JSON Pointer referido
a la respuesta completa original, con escape `~0`/`~1`, incluidos índices de listas.
`value` conserva el valor JSON original completo, ya sea texto, lista u objeto,
sin recortes. Los campos reconocidos son `error`, `errors`, `failure_reasons` y
`reasons`; las demás estructuras expresamente retenidas (por ejemplo readiness,
análisis y diagnóstico) conservan sus propios campos. Este índice puede repetir
errores ya visibles: no representa errores adicionales ni exige recorrer archivos.
Las respuestas ERROR/NOT_FOUND que se pasan completas mantienen su contrato previo
y pueden no incluir `error_evidence`.

Se corrige la implementación, manteniendo el test que exigía valores íntegros; no
se rebajan sus aserciones. Un evento WAYPOINT_REACHED con `reached=false` tampoco
aparece ahora como punto alcanzado en el resumen: queda en los eventos fallidos.
Se conserva además `message` del executor. Esto sólo cambia la representación;
no altera eventos originales, tolerancias, aceptación ni recuperación.

### Verificación y bytes de las respuestas actuales

Los tests invocan `mcp.call_tool` en proceso sobre el registro real: validación de
argumentos, función registrada y conversión de salida SDK. Comprueban las tres
herramientas, default, ambas vistas, esquemas, errores de integridad sin escrituras,
interrupción y restricción de v1. Los argumentos/artefactos de escritura usados
como fixtures están aislados en temporales; no se sirve transporte MCP ni se usa
Docker. El helper de prueba usa espera acotada y despertares periódicos del bucle
para recibir resultados del worker thread del SDK, sin sustituir su ejecución.

[Mediciones, esquemas, hashes y logs nuevos](../documentation/verification/mission_response_views_2026_10_18.json):
JSON UTF-8 de `structured_content`, `ensure_ascii=false`, `allow_nan=false`, indent=2;
también se guarda formato compacto. El default coincide con summary en cada caso.

| Consulta registrada y artefacto | Detalle bytes | Resumen bytes | Reducción |
| --- | ---: | ---: | ---: |
| get_mission_state, borrador 1f84f808 | 62485 | 12798 | 79.52% |
| get_mission_state, revisión aprobada b880d6c3 | 21866 | 14912 | 31.80% |
| get_mission_state, revisión bloqueada 89c3da7d | 21866 | 14912 | 31.80% |
| get_revision_proposal, propuesta WP3 e44903a2 | 4334 | 4591 | -5.93% |
| get_virtual_preflight, FAILED WP3 d4519cab | 9501 | 8396 | 11.63% |
| get_virtual_preflight, PASSED tres puntos f5f55084 | 10133 | 5916 | 41.62% |
| get_virtual_preflight, PASSED cinco puntos 4bb6a20e | 11658 | 6414 | 44.98% |

La propuesta WP3 **crece un 5,93%**: la representación, referencias y avisos tienen
coste en respuestas ya pequeñas. No hay promesa de reducción universal ni límite
duro que pueda recortar errores. El borrador incluye ahora el ensayo geométrico
vinculado. Los perfiles anteriores de FAILED/PASSED medían get_mission_state por
run_id; los nuevos de preflight miden otra consulta, get_virtual_preflight. No son
comparaciones del mismo payload antes/después. No se midieron framing MCP,
duplicación texto/structuredContent, tokens, latencia ni compacciones de Hermes.

Tests afectados y compatibilidad: **45 passed in 2.79s**. Suite completa posterior:
**318 passed in 8.32s**. Hay once nuevos casos de regresión respecto de los 307
casos de la revisión anterior (296 pasados y once fallidos). Los once fallos
originales se reproducen primero y pasan tras la corrección. La afirmación histórica
de 307 pasados carece en el árbol de un log asociado y de un snapshot versionado
de estos archivos antes sin seguimiento: no se puede demostrar por qué se informó
así. No se atribuye a una reversión, cambio de SDK o acción concreta no documentada.

Queda pendiente una nueva comprobación conversacional con Hermes tras recargar MCP
y medir su efecto sobre compacciones. Este incremento no convierte el PASSED
geométrico anterior en prueba operativa de los wrappers corregidos, ni aporta
evidencia de hardware, agricultura, velocidad comandada, carga del .plan o causa
del fallo WP3 anterior.
