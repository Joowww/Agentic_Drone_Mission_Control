# Development log

Registro de avances, pruebas, incidencias, decisiones y próximos pasos.
Los resultados deben estar respaldados por código, tests o evidencias.

## 2026-10-17 — Planificación conversacional mediante Hermes y MCP

### Objetivo y punto de partida

Conectar la conversación de Hermes con la creación de misiones,
la validación determinista, la exportación QGC y la ejecución simulada.

- Rama: feature/hermes-integration.
- Commit inicial: fcb13a1.
- Estado inicial limpio y sincronizado.
- Ya funcionaba la ejecución de un dron con tres waypoints.
- El servidor MCP recibía mission_path y ejecutaba únicamente v1.

### Implementación

- update_mission_draft crea, recupera y completa borradores persistentes.
- draft_id permite continuar la misión entre turnos y reinicios.
- finalize_mission_draft construye MissionDefinition, guarda un JSON
  y reutiliza la validación y exportación QGC.
- Cada finalización utiliza un directorio UUID independiente.
- Hermes interpreta el lenguaje natural y selecciona herramientas.
- Esta integración reutiliza los modelos y servicios de planificación
  sin invocar un segundo LLM de Ollama.
- Se corrigió un parámetro de validate_and_export_qgc.
- Se añadieron tests y docs/hermes-planning.md.
- La entrada JSON continúa disponible.

### Verificación automatizada

- Compilación de los tres módulos modificados/nuevos: correcta.
- Suite ejecutada por Joel: 65 passed in 7.38s.
- git diff --check: sin errores.

### Caso aprobado

- Nombre: Prueba Hermes.
- Mission ID: prueba_hermes_001.
- Draft ID: ca4ab5d2-24e1-4845-8142-b214740e7f9d.
- Finalización: a709aaba-d25b-451c-a6f0-e2ff6ace018f.
- Vehículo: drone_01, ejecutado como v1.
- Batería declarada: 95 %; consumo configurado: 0.8 %/min.
- Reserva mínima: 20 %; viento configurado: 0 km/h.
- Tres waypoints navigate a 5 m, con regreso al lanzamiento.
- El operador proporcionó coordenadas y parámetros en lenguaje natural.
- Hermes creó el borrador, solicitó datos, lo completó y lo finalizó.
- Validación: FEASIBLE y APPROVED, sin errores.
- Se generaron JSON y QGC .plan.

### Ejecución simulada

Tras la autorización explícita del usuario, Hermes seleccionó
execute_approved_mission. El executor aplica internamente el execution gate.

- Resultado: COMPLETED.
- Waypoints completados: 3/3.
- Regreso y aterrizaje completados.
- Estado final: landed=true, armed=false, flying=false.
- Duración de la llamada MCP: 228.7 s.
  No constituye una medición independiente del tiempo de vuelo.

| Evento | Error horizontal (m) | Error vertical (m) |
|---|---:|---:|
| WP1 | 0.02740448 | 0.00000000 |
| WP2 | 0.22777375 | 0.04003906 |
| WP3 | 0.22611909 | 0.01000977 |
| Regreso | 0.00000000 | 0.00000000 |

Error vertical al aceptar el despegue: 0.65002441 m.
Son valores reportados por el executor; cero no implica precisión física absoluta.

### Caso bloqueado por batería

- Nombre: Prueba Hermes bateria insuficiente.
- Draft ID: d25acd5a-fd61-453c-a3ad-ea236c5c1f6b.
- Mission ID: prueba_hermes_001_bateria_baja.
- Misma ruta; batería inicial 10 % y reserva mínima 20 %.
- Resultado: NOT FEASIBLE y BLOCKED.
- Motivo: batería final prevista inferior a la reserva.
- Recomendación: iniciar con al menos 20.1 %, según el modelo actual.
- No se llamó a herramientas de arranque, parada ni ejecución de vuelo.

Hermes creó un borrador independiente y leyó posteriormente el JSON original.
No se realizó una comparación independiente de hashes de todos los originales.

### Evidencias conservadas

Directorio relativo a la raíz del repositorio:

simulation/ros2_gazebo/results/hermes_conversational_2026_10_17/

- approved_mission.json
- approved_mission.plan
- blocked_battery_mission.json
- blocked_battery_candidate.plan

Las cuatro copias se comprobaron mediante ls y tienen contenido.
El candidato bloqueado procede de la segunda exportación solicitada por Hermes.

Los originales permanecen en missions/generated/, ignorado por Git.
Las transcripciones se revisaron durante la sesión; no están incluidas
en estas cuatro evidencias. Este registro conserva los resultados principales.

### Incidencias y mejoras

- Readiness comprueba el backend, no la visibilidad de la GUI.
- Inicialmente solo estaba activo el servidor de Gazebo.
- Abrir la GUI por separado produjo una pantalla negra.
- Se realizó parada y arranque completos mediante MCP.
- El arranque posterior informó GUI activada y backend preparado.
- La causa exacta de la pantalla negra no quedó aislada.
- Hermes exploró archivos y recursos para entender operaciones habituales.
  Mejorar las descripciones MCP, incluido el comportamiento de la GUI.
- Hermes repitió validación/exportación después de finalize_mission_draft.
  Aclarar que la finalización ya realiza ambas operaciones.
- Algunas respuestas resumieron resultados en vez de mostrar el JSON pedido.
- cp -n emitió un aviso de portabilidad. Las copias existen.
  Para próximas copias se utilizará cp --update=none.

### Límites de la demostración

- La ruta fue aportada por el operador; no se generó desde un objetivo agrícola.
- Solo se ejecutó navigate; no se verificó seguimiento de speed_kmh.
- El executor consumió el JSON mediante ROS2/AP_DDS, no cargó el .plan.
- El regreso navega al lanzamiento y aterriza; no activa el modo RTL.
- La etiqueta candidate no impide cargar el archivo en otra aplicación.
- La autorización es conversacional, sin token ligado a una versión.
- No hay preflight formal con análisis y replanning.
- No se demostró replanning durante el vuelo ni coordinación de dos drones.
- No se probaron acciones agrícolas ni hardware real.
- Faltan eliminación de campos/waypoints y control de concurrencia.

### Próximos pasos

1. Guardar este incremento y sus evidencias en Git.
2. Mejorar instrucciones y descripciones MCP a partir de las incidencias.
3. Definir el primer workflow de preflight, análisis y replanning con estado.
4. Mantener trazabilidad entre misión validada, simulada y autorizada.
5. Incorporar evaluación y documentación durante cada incremento.

## 2026-10-17 — Virtual preflight asíncrono, consulta y exclusión de v1

### Punto de partida y evidencia preservada

Se continúa sobre el árbol sin commit basado en 47547f8, conservando planificación,
virtual preflight LangGraph, limpieza de simulación, diagnóstico y evidencias.
El ensayo d4519cab-ebd1-4359-b547-44be38294a6a superó la espera MCP de 300 s;
el backend continuó y guardó FAILED por WP3, con recuperación LAND completada.
Se conservaron los originales y se comprobaron por SHA-256 los 15 artefactos
presentes bajo simulation/ros2_gazebo/results, sin cambios.

Joel confirma que la limpieza nueva ya se probó operativamente: parada sin
procesos restantes y arranque con un supervisor ROS2, dos ArduCopter y
servidor/GUI Gazebo. Es una comprobación comunicada por el operador; no se repitió
durante esta implementación. La causa del fallo WP3 sigue sin demostrarse.

### Implementación

- start_virtual_preflight persiste admisión, request_key, run_id, copia y hash de
  entrada, reserva v1 y devuelve sin esperar a la validación ni al vuelo.
- get_virtual_preflight consulta sólo por UUID canónico o clave recuperable;
  no inicia, reanuda ni repite trabajo y no abre rutas aportadas por el cliente.
- Worker de proceso separado, sesión independiente, stdin desconectado de MCP y
  stdout/stderr en worker.log. Identidad por PID, ticks de creación y boot ID.
- Reclamación única con token de lanzamiento, índice de claves y locks de archivo.
  La misma clave nunca crea un segundo ensayo, ni siquiera después de finalizar.
- Reutilización del workflow y análisis existentes; progreso persistido por fase.
  Se mantiene snapshot, SHA-256, gate interno, tolerancias, AP_DDS, diagnóstico de
  waypoint, recuperación, propuestas del replanner y semántica de aceptación.
- Reserva persistente y mutex de v1 compartidos por worker, executor síncrono y
  demo interactivo. La reserva no desaparece porque muera un proceso o venza un
  timeout. Sin confirmación de no vuelo o aterrizaje/desarmado no se libera.
- Estados separados de admisión, trabajo y resultado. Un worker desaparecido sin
  final se muestra como INTERRUPTED/UNCONFIRMED; no se inventa aterrizaje ni PASSED.
- Consulta de informes históricos, incluido el ensayo WP3, sin ejecutar procesos.
- Instrucciones MCP para recordar clave/ID, consultar cada 15–30 s y recuperar
  una respuesta perdida mediante consulta, sin repetir start.
- run_virtual_preflight y execute_approved_mission siguen siendo síncronos y
  pueden superar la espera del cliente. El timeout no cancela el backend.

### Verificación real de este incremento

- Suite completa: 188 passed in 8.39s.
- Pruebas offline: admisión sin vuelo/espera al workflow, stdio separado, consulta
  sin escrituras, finales, idempotencia, carreras concurrentes, recarga, PID
  reciclado, worker desaparecido, reservas no confirmadas y exclusión con
  entradas síncronas/demo. Se comprueba también el gate interno a través del
  workflow real y la lectura del informe histórico.
- Sintaxis Bash de run_demo.sh, start_sim.sh y stop_sim.sh: correcta.
- git diff --check: sin errores.
- Sin Docker real, simulación, vuelos, llamadas MCP operativas, commit ni push.

### Documentación y límites pendientes

Guía: docs/async-virtual-preflight.md. Se enlaza desde las guías previas,
conservando su contenido como historia de los incrementos.

Falta probar operativamente el worker independiente y la reconexión MCP. No se
implementan cancelación, reanudación, streaming de telemetría, limpieza automática
de jobs ni interfaz de reconciliación de reservas. La exclusión coordina este
checkout, no órdenes ROS externas ni otros checkouts; sólo cubre v1.
La muerte del worker o del host no demuestra aterrizaje. PASSED no autoriza
hardware real ni aporta consentimiento para otro ensayo o ejecución.


## 2026-10-17 — Verificación operativa del ensayo asíncrono y revisión

### Evidencia guardada comprobada offline

Ensayo `f5f55084-5af6-4e58-ab1a-ce30a13832b3`, asociado por el operador a la clave
`joel-preflight-async-01`. Archivos conservados:

- `simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/passed_async_mission.json`
- `simulation/ros2_gazebo/results/virtual_preflight_2026_10_17/passed_async_report.json`

El SHA-256 calculado de los bytes de la misión coincide con `mission_sha256` y
`expected_sha256` del informe:

```text
2366d5a2c38f092e7ce5b01220f49463001dbf8164db6706899ff26beb9d56d1
```

El informe registra `PASSED`, persistencia confirmada, validación `FEASIBLE` /
`APPROVED`, executor `COMPLETED`, tres waypoints completados, regreso solicitado
y alcanzado y `LANDED` con `landed=true`, `armed=false`, `flying=false`.
Todos los checks del análisis son verdaderos y la lista de motivos está vacía.

| Evento alcanzado | Error horizontal (m) | Error vertical (m) |
| --- | ---: | ---: |
| WP1 | 0.451579 | 0.030029 |
| WP2 | 0.227774 | 0.000000 |
| WP3 | 0.480681 | 0.039978 |
| Regreso al lanzamiento | 0.000000 | 0.000000 |

Son valores del executor, no medidas independientes de precisión física.
El despegue registra error vertical 0.070007 m. El informe abarca desde
20:20:20.241103 hasta 20:24:17.155436 UTC del 17/10/2026: 236.914333 s.
La sección de ejecución abarca 227.265168 s. No son mediciones de latencia de la
llamada de admisión. Este ensayo concreto no excedió 300 s.

### Verificaciones operativas según la transcripción del operador

El operador comunica admisión rápida y recepción de `run_id`/rutas; consultas
del mismo ensayo antes y después de `/reload-mcp`, sin repetir el inicio; y
consulta final con resultado persistido y restricción de `v1` liberada.
Después de finalizar, la parada devolvió `remaining=[]`; una comprobación
posterior, ejecutada secuencialmente, devolvió `NOT READY`.

Estos pasos de interacción, recarga, liberación de reserva y parada se registran
según la transcripción del operador. Los dos JSON conservados respaldan el
contenido, vuelo y resultado del ensayo, pero no contienen por sí solos una
transcripción de todas las llamadas ni el estado de la reserva tras la consulta.
No se volvieron a ejecutar operaciones Docker, simulación, vuelos ni MCP durante
esta revisión. La indicación anterior de prueba operativa pendiente queda
actualizada para este escenario de worker y `/reload-mcp`.

La prueba no demuestra resistencia a reinicios del host, pérdida de disco o
muerte del worker. Tampoco demuestra haber resuelto la causa del fallo anterior
de WP3 en `d4519cab-ebd1-4359-b547-44be38294a6a`. Se mantienen los límites de
hardware, velocidad, acciones agrícolas, RTL y asociación por hash ya descritos.

### Revisión offline de concurrencia y persistencia

La revisión incluyó el diff seguido y los archivos nuevos del incremento.
Se reprodujeron con dobles y corrigieron estos defectos:

- Un `Context` copiado podía conservar la identidad del propietario después de
  salir del ámbito y saltarse la exclusión; dos contextos del mismo propietario
  también podían invocar executors simultáneamente. La autoridad ahora se revoca
  al cerrar el ámbito, revalida propietario/proceso y admite sólo una llamada
  simultánea. El mutex de ejecución no se libera mientras una llamada prestada
  siga activa. No se añade una cola de vuelos ni un reintento.
- Un índice de solicitud `{}` se trataba como ausencia de clave y podía admitir
  otro ensayo cuando la reserva previa ya había terminado. Registros vacíos o
  JSON que no sean objetos ahora producen `ERROR`, sin spawn ni liberación.
  Se distingue un archivo ausente de un registro persistente inválido; los
  originales dañados no se sobrescriben al consultar.
- La admisión leía todo el archivo antes de aplicar el límite de 5 MB y podía
  bloquearse al abrir una FIFO bajo el lock de admisión. Ahora exige archivo
  regular, comprueba el tamaño y acota la lectura; rechaza FIFOs y dispositivos.

Las correcciones mantienen gate, tolerancias, recuperación, análisis y evidencias.
Los tests nuevos son offline: contextos e hilos con comandos dobles, registros
corruptos, FIFO sin lectura bloqueante, límite de entrada y comprobación del
informe PASSED mediante el analizador existente, sin reproducir su vuelo.

Siguen pendientes cancelación, reconciliación explícita de reservas no
confirmadas, limpieza de almacenamiento y evaluación ante fallos del host.
La exclusión sigue siendo cooperativa entre entradas de este checkout; no
controla órdenes ROS externas ni resuelve todas las carreras TOCTOU de archivos.


### Resultado de verificación de esta revisión

- Suite completa offline: 198 passed in 6.44s.
- Los tests de regresión reprodujeron primero los defectos de contexto copiado,
  registros dañados y lectura de FIFO; pasan después de las correcciones.
- Sintaxis Bash de los tres scripts: correcta. git diff --check: sin errores.
- Se verificaron por SHA-256 los 17 artefactos de evidencia, sin modificaciones.
- El contenido anterior de este documento se conserva íntegro como prefijo.
- Sin Docker real, simulación, vuelos, llamadas MCP operativas, commit ni push.


## 2026-10-17 — Propuestas, geometría relativa y estado conversacional

Base comprobada: `feature/hermes-integration`, HEAD `bad8920` sincronizado con
origin y árbol limpio al empezar este incremento. Se buscaron instrucciones
`AGENTS.md` en ancestros y proyecto, sin archivos aplicables. No se descartaron
cambios ni evidencias; los bloques se implementaron y probaron secuencialmente.
Guía, contratos, límites, prompts y tabla de evaluación:
[`docs/mission-lifecycle-demo.md`](../docs/mission-lifecycle-demo.md).

### Bloque 1: propuestas y revisiones

Se inspeccionaron replanner, grafos, modelos, editor, validación/exportación y
resolvedor de ensayos. El replanner actual propone texto; no produce una ruta
numérica ni mide batería/viento. Las nuevas operaciones MCP crean una propuesta
persistente desde un informe final verificado y una revisión en directorio nuevo
sólo con cambios explícitos. Guardan fuentes exactas, SHA-256 de misión/informe y
propuesta revisada, diferencias, procedencia y condiciones pendientes. Batería,
viento y consumo requieren declaración del operador, etiquetada sin telemetría.
No se reduce automáticamente ninguna reserva, límite o tolerancia.

Se reutilizan editor, MissionDefinition y validación/exportación reales. Una
revisión puede seguir BLOCKED. Readiness pendiente no altera el plan; FAILED WP3
sólo propone investigación de causa desconocida conservando recuperación y
cualquier diagnóstico disponible; PASSED no necesita corrección. No hay vuelo,
repetición ni liberación de v1. Claves persistentes y mutex evitan duplicados;
argumentos diferentes producen CONFLICT y una intención BUILDING incompleta exige
reconciliación sin recrear la misión. Informes provisionales, análisis incoherentes,
fuentes cambiadas o identidad histórica ambigua se rechazan.

LangGraph sigue evaluando y llamando al replanner mediante el workflow existente.
La persistencia/aplicación de cambios es un servicio determinista, sin nuevo grafo
conversacional ni segundo LLM. Hermes interpreta y presenta los cambios al usuario.

### Bloque 2: geometría relativa y versiones

Servicio reutilizable de offsets norte/este y rectángulos con orientación,
sentido, HOME, cierre, altitud y regreso explícitos; devuelve decisiones pendientes
sin inventarlas. Reutiliza la escala local del mapper (111320 m/grado y cos HOME),
con radio <=1 km, |latitud| <=75° y sin cruce del antimeridiano. Sólo altitudes
relativas a HOME con referencia cero. Valida finitud, degeneración y dominio.
No es cobertura agrícola, evitación de obstáculos ni autorización del espacio aéreo.

Las pruebas revelaron que el validador existente rechaza el tramo horizontal nulo
HOME→WP1 cuando ambos coinciden. Con HOME en esquina se representa A como inicio
HOME y se empieza en B/D; el cierre termina en A. Se conservó el gate. El control
versionado exige revisión actual para generar/reemplazar rutas y reemplazo
explícito; elimina los waypoints anteriores y conserva los demás campos. Los
clientes antiguos pueden seguir haciendo merge sin versión, serializado pero sin
detectar intención obsoleta; la nueva documentación explica este límite.

Finalizar usa la construcción/validación/exportación actuales y guarda vínculo a
la versión exacta del borrador, copia de ésta y hashes de JSON/plan. Las escrituras
del borrador y metadatos no son una transacción global: inconsistencias de hash
bloquean futuras ediciones sin reparación silenciosa. LangGraph sólo participa
en la validación final existente; la geometría es un servicio sin LLM.

### Bloque 3: consulta y orquestación

Consulta de sólo lectura por identificadores retenidos: borrador, versión final,
validación/plan, propuestas, revisiones y ensayos vinculados mediante IDs y hashes.
Sidecars locales y source_artifact en admisión/estado/informe conservan procedencia;
no se crea almacén paralelo ni se infiere por nombre, fecha, último archivo o
igualdad de bytes sin vínculo. Los informes anteriores siguen consultables por
run_id, con relación a borrador desconocida cuando no fue guardada.

Se distingue borrador actual de snapshot validado, readiness histórica de
actualidad desconocida y PASSED simulado de consentimiento. La consulta no ejecuta
validación, exportación, readiness, spawn, vuelo ni cambio de exclusión. LangGraph
mantiene el mismo workflow del ensayo; esta consulta sólo lee sus registros.
Instrucciones MCP actualizadas: pedir datos necesarios, retener versiones/IDs y
claves, no repetir validación/exportación al finalizar, no pedir otra autorización
para guardar/validar lo ya solicitado, exigir petición explícita del ensayo y
consultar el mismo run cada 15–30 s incluso tras /reload-mcp. El worker no inicia
simulación. Los timeouts de las variantes síncronas no se han cambiado.

### Verificación y límites de este incremento

Las primeras comprobaciones secuenciales pasaron: bloque 1 con regresiones
60 tests; bloque 2 con planificación/revisiones/MCP 59 tests; bloque 3 con los
workflows/regresiones 164 tests. Tras revisar integridad y concurrencia, las
comprobaciones por área pasaron 18 tests de revisiones, 43 de geometría/planificación
y 109 de estado/preflight/MCP. Estos grupos comparten regresiones y no se suman
como número de tests únicos. Todos son offline con infraestructura/ejecución dobles;
se usa evaluación/editor/exportación reales y copias de informes conservados.

La revisión completa incluye archivos nuevos y cubre índices dañados que no se
pueden tratar como ausencia, replay de revisión cuyo artefacto cambió, un UUID
histórico duplicado, análisis contradictorio, edición obsoleta y asociación
falsa entre misiones del mismo nombre o incluso bytes idénticos. Se comprobaron
los 17 archivos de evidencia contra HEAD por SHA-256, sin diferencias. El hash de
passed_async_mission.json sigue siendo
`2366d5a2c38f092e7ce5b01220f49463001dbf8164db6706899ff26beb9d56d1`.

No se ejecutaron Docker real, simulación, vuelos ni MCP operativo; no se hizo
commit/push. No se modificaron scripts, executor, AP_DDS, gate, tolerancias,
diagnóstico, recuperación ni exclusión de v1. El informe anterior de PASSED y las
observaciones del operador (parada remaining=[] y comprobación secuencial NOT
READY) se conservan y no se presentan como verificaciones nuevas. No se resolvió
la causa del fallo anterior WP3 ni se probó resistencia a reinicios del host.

Quedan pendientes demos conversacionales de los tres bloques, un eventual ensayo
operativo autorizado de una misión geométrica/revisada, reconciliación de artefactos
BUILDING y reservas no confirmadas, retención/limpieza y evaluación de fallos de
host/disco. Los hashes son controles locales de integridad, no firmas ni solución
total TOCTOU. Las lecturas no son una instantánea transaccional global. Persisten
los límites de velocidad, navigate, RTL, hardware y acciones agrícolas ya descritos.

Verificación final: **259 passed in 7.08s** en la suite completa offline (61 tests
más que la base de 198). La cobertura adicional final incluye recuperación de
identidad BUILDING de una propuesta interrumpida, vínculo del preflight síncrono
y rechazo de un sidecar/plan dañado antes de reservar o lanzar un worker.
`git diff --check` y comprobación equivalente de los diez archivos nuevos: sin
defectos de whitespace. Los 21 renglones con espacios/tabuladores finales del log
histórico `failed_wp3_simulation.log` se conservan exactamente, no son cambios
nuevos. Los dos documentos históricos permanecen íntegros como prefijo.


## 2026-10-17 — Incidencia conversacional y persistencia geométrica parcial

Se continúa sobre el árbol sin commit del incremento anterior, conservando
revisiones trazables, geometría, estado y evidencias. Se comprobaron rama
feature/hermes-integration e instrucciones AGENTS.md en ancestros/proyecto, sin
archivos aplicables. No se ejecutaron operaciones Docker, simulación, vuelo ni
MCP operativo; no hubo commit ni push.

### Evidencia disponible y alcance de la inspección

Según la transcripción comunicada por el operador, una petición limitada a nombre
Parcela Norte y rectángulo 40x20 m acabó con objetivo survey, descripción agrícola,
maximum_altitude_m=20 y return_to_home=true; además, Hermes interpretó un error de
consulta sin identificador como ausencia de borradores. No conocemos los argumentos
exactos de todas las llamadas y no se atribuyen retrospectivamente valores al
operador. La inspección local, sin modificación, encontró tres archivos en el
borrador 08de7c26-99fc-41b6-8e7f-65722e309152: draft.json, draft_state.json y draft.lock.
Corroboran revisión 2, SHA-256 de draft.json
`00a5119906c2ff177ff23e38d907a6c0d4d297a2cf6bf6148e5eb921b28f2a19`, los valores
anteriores, waypoints vacíos, route_provenance=null, etiqueta OPERATOR_INPUT y
40x20 sólo en texto libre. Es evidencia del estado guardado, no del origen
conversacional de cada campo ni de la secuencia exacta de peticiones.

Se guardó un manifiesto temporal de hashes antes de editar. Los tres archivos
reales de la incidencia se conservan sin edición, migración, arreglo o nueva
finalización; las pruebas usan temporales y fixtures sintéticos, independientes
de ese directorio ignorado por Git. Se mantienen las 17 evidencias anteriores,
incluido el log bruto y sus espacios finales.

### Corrección implementada

MissionPlanDraft incorpora geometry_intent con el mismo RelativeRouteRequest y
almacenamiento existente: no hay otro almacén. Guardar nombre y dimensiones puede
ser una sola actualización. Los parches conservan hechos no nulos entre turnos;
seleccionar un modo desconocido conserva sus parámetros compatibles y cambiar
entre modos explícitos elimina los antiguos de forma, conservando los comunes.
Los offsets se reemplazan completos. HOME y regreso se sincronizan por copia
determinista; contradicciones de una misma petición son errores, sin precedencia
silenciosa. No se rellenan objetivos, límites ni otros hechos ausentes.

La intención incompleta se persiste sin waypoints. El mismo generador valida
hechos conocidos, calcula pendientes y genera sólo al completar las decisiones;
HOME por sí solo no basta. Una edición geométrica de un borrador existente exige
revisión vigente. Si ya había ruta, exige reemplazo explícito; cuando la intención
resultante queda incompleta retira la ruta anterior. Una sustitución manual
explícita desvincula la intención y no deja waypoints sobrantes. Se mantiene el
merge ordinario previo para rutas sin intención y su límite de clientes sin
versión. La construcción compartida rechaza intención incompleta o ruta divergente
también fuera de la frontera MCP.

El sidecar versiona intención y borrador, hashes y atribuciones. Incoherencias
borrador/metadatos/ruta/procedencia bloquean lectura o edición sin reparación
automática. Las respuestas combinan mission_missing_fields y
geometry_missing_fields, además de pending.route_generation y
pending.mission_finalization. Finalizar conserva copia/hash del sidecar junto al
snapshot, valida y exporta mediante los servicios existentes, sin ensayar.

La etiqueta nueva es UNVERIFIED_AGENT_INPUT. attributions permite registrar por
campo una declaración de Hermes apoyada en una frase del operador, con
OPERATOR_DECLARED_VIA_AGENT y authenticated=false; también se distinguen UNKNOWN,
generación/copia determinista y COMPATIBILITY_DEFAULT. Los registros antiguos se
presentan como UNKNOWN_LEGACY_INPUT, con etiqueta original explícitamente histórica,
sin fabricar atribuciones ni extraer geometría del texto. Los defaults anteriores
se exponen aparte, sin nuevos límites de seguridad ni convertirlos en decisiones
del operador. El regreso por defecto no completa la decisión geométrica pendiente.

Las instrucciones/descripciones MCP exigen conservar sólo hechos aportados,
preguntar lo pendiente y no inferir survey, agricultura, altura, regreso ni límites
de un nombre o forma. Un ERROR/INVALID_ARGUMENTS no acredita inventario vacío:
sin ID la consulta devuelve lookup_performed=false e inventory_status=UNKNOWN.
Se pide usar la respuesta del proyecto sin exploración redundante. Guardar/validar
lo ya solicitado no requiere otra confirmación; el ensayo sigue necesitando
petición explícita tras revisar valores, defaults y límites de procedencia.

### Verificación y límites

Las primeras regresiones seleccionadas pasaron 65 tests; los 27 casos iniciales
específicos pasaron; después, el grupo ampliado pasó 87 tests. Las comprobaciones
finales se registran a continuación. Los escenarios incluyen persistencia parcial,
recarga, combinación, dimensiones conservadas, HOME insuficiente, exportación real
al solicitarla, entradas inválidas sin pérdida, cambios de modo/reemplazo,
concurrencia/versiones, consultas sin efectos, atribución no autenticada y legado
sin migración. No se usa el borrador real para edición en los tests.

LangGraph conserva su función de evaluación/replanner determinista y workflow de
ensayo; esta corrección afecta a almacenamiento/servicios/MCP, sin nuevo LLM ni
grafo conversacional. Se mantienen JSON, QGC .plan, gate, tolerancias, AP_DDS,
diagnóstico, recuperación, preflight asíncrono y exclusión v1.

Queda pendiente repetir la conversación en Hermes con peticiones equivalentes,
recarga y revisión de argumentos reales. La garantía offline es que el backend no
rellena hechos ausentes en su entrada; no prueba que el LLM no invente argumentos.
Una atribución del agente no autentica al operador ni el diálogo, y el esquema no
demuestra fidelidad. No hay fuente conversacional verificable, token de consentimiento
ni nuevos ensayos operativos. Siguen las limitaciones de transacciones de varios
archivos, TOCTOU y fallos del host; no se resuelve la causa previa de WP3 ni se
cambia el timeout de herramientas síncronas.

Guías actualizadas: docs/hermes-planning.md y docs/mission-lifecycle-demo.md,
incluida conversación de varios turnos que empieza sólo por nombre y dimensiones,
recupera tras recarga, completa decisiones y finaliza al solicitarlo.

Resultado final: **290 passed in 7.84s** en la suite completa offline, con 31
casos nuevos específicos respecto a los 259 anteriores. El último grupo seleccionado
pasó 90 tests antes de añadir el caso adicional de radio imposible con posición
HOME pendiente, incluido en la suite final. Sintaxis Python comprobada; no se
modificaron scripts. git diff --check sin errores; los 12 archivos sin seguimiento
(incluidos los previos) también se comprobaron individualmente sin defectos de
whitespace. Los tres archivos de la incidencia y las 17 evidencias anteriores
siguen idénticos por SHA-256. El contenido anterior de este registro se conserva
íntegro como prefijo; el log bruto histórico no fue normalizado.

Archivos cambiados en esta corrección, sobre el árbol anterior:
models/mission_plan_draft.py; planning/mission_plan_service.py;
planning/relative_routes.py; planning/draft_provenance.py (nuevo);
planning/mission_artifacts.py; tools/hermes_mission_planning.py;
tools/hermes_mcp_server.py; tools/mission_state.py;
tests/test_relative_routes.py; tests/test_partial_geometry_planning.py (nuevo);
docs/hermes-planning.md; docs/mission-lifecycle-demo.md;
documentation/development_log.md. Los restantes cambios previos se conservaron.


## 2026-10-18 — Archivo conversacional y vistas MCP concisas

Se continúa sobre el árbol sin commit de feature/hermes-integration, conservando
los incrementos anteriores. Se comprobaron estado e instrucciones AGENTS.md en
ancestros/proyecto, sin archivos aplicables. No se ejecutaron Docker real,
simulación, vuelos ni MCP operativo; las consultas de comprobación fueron funciones
Python de lectura y verificadores deterministas, sin transporte MCP. Sin commit/push.

### Artefactos y observaciones del operador

El operador comunica pruebas conversacionales que generaron:

- Finalización 8be78baa-4cf4-4f65-8531-9388d030c3ed del borrador
  1f84f808-c688-48c9-b7da-1b1c4b29c094.
- Revisión aprobada b880d6c3-4557-42c7-ada4-5a04db5e9237 y revisión bloqueada al
  11% 89c3da7d-bc20-42ae-baeb-21d4e839355a.
- Propuestas de batería 727082c5-4008-4bf2-a61e-87b48eed35a8, investigación WP3
  e44903a2-0405-4ea5-99c7-7233ce0ea333, PASSED
  ae3bf4c2-3a56-4402-89b9-020e6232d5cf e infraestructura
  4bff56e2-48c9-421f-b8b6-1969aa5ddf74.

Se verificaron los registros locales con los servicios existentes: identidad,
hashes de misión y sidecar, copia de borrador/metadatos y plan, enlaces de revisión
con propuesta, hashes de las fuentes y reanálisis determinista de informes finales.
La finalización figura FEASIBLE/APPROVED en revisión de borrador 4/geometría 3; el
JSON tiene rectángulo 40x20 m, HOME central, cinco puntos por cierre, altitud relativa
5 m y regreso. Esto acredita planificación/exportación guardada, no vuelo de esa
ruta. La revisión al 95% conserva declaración explícita de condición simulada,
sin telemetría ni sustitución física; la del 11% sigue BLOCKED por reserva.

Se conservaron 31 copias exactas bajo
simulation/ros2_gazebo/results/hermes_conversational_2026_10_18, con manifest.json
(ruta original absoluta, ruta de copia relativa, SHA-256 y bytes), README y
response_sizes.json. Se incluyeron los índices de solicitud vinculados; no locks.
No se modificaron los originales, el borrador anterior de la incidencia ni las
evidencias previas. Las rutas incrustadas de los JSON se conservaron: las copias
son evidencia, no un registro operativo reubicado; el manifiesto no firma datos.

El operador observa respuestas de unos 49 kB y compacciones de Hermes; se solicita
aclarar alcance SITL/hardware, recomendaciones frente a gate, significado de un
qgc_plan_path nulo y controles readiness registrados. Estas son observaciones y
objetivos de interpretación comunicados por el operador, sin transcripción completa
autenticada de todos los argumentos. Los archivos corroboran contenido persistido,
no fidelidad del LLM al diálogo ni todas las frases de sus respuestas.

### Cambio de respuesta y compatibilidad

Se añade tools/mission_response_views.py con proyecciones puras. Los verificadores
y consulta completos se ejecutan primero; después se elige vista, sin caché, nuevos
estados, escrituras ni reducción de comprobaciones. MCP 0.3.0 usa por defecto
view=summary en get_mission_state, get_revision_proposal y get_virtual_preflight.
Clientes que necesiten el formato completo previo deben enviar view=detail; los
backends Python mantienen sus defaults completos, incluido get_mission_state.
Los resultados de escritura/validación/exportación/ejecución no cambian.

El resumen evita repetir borradores, atribuciones por campo, muestras y el mismo
registro de revisión en dos árboles. Mantiene IDs, hashes principales/integridad,
validación, errores/motivos, recomendaciones, vínculos, declaraciones, defaults,
pendientes e incertidumbres. Conserva análisis, recuperación, diagnóstico y salida
readiness exacta. Errores explícitos de payloads omitidos se conservan sin truncar
en error_evidence con ubicaciones de origen. No hay un límite duro de bytes ni
promesa de reducción para listas arbitrariamente grandes de errores o controles.
detail_access devuelve consultas de sólo lectura con los IDs reales y view=detail.

Instrucciones MCP actualizadas: usar consultas por IDs/claves retenidos, no inventar
rutas/IDs ni recorrer directorios para reconstruir estado. Tras respuesta perdida,
consultar el borrador/ensayo fuente o clave de preflight; no repetir escrituras para
recuperar salida. Si no queda identificador verificable, informar de incertidumbre
y reconciliar con el operador. Guardar/validar lo solicitado no requiere otra
confirmación. Una solicitud SITL sí autoriza ese ensayo simulado; no requiere
permiso de hardware real ni intervención física de batería. Declaraciones de
escenario simulado no se presentan como mediciones físicas. La bandera
hardware_authorized=false limita alcance, no bloquea SITL por sí misma.

Las recomendaciones no son nuevos bloqueos técnicos; el gate conserva sus propios
criterios. Un PASSED posterior no demuestra la causa ni la solución de WP3.
qgc_plan_path=null indica que esa operación no registró exportación; no demuestra
ausencia de exportaciones anteriores ni permite inventar enlaces por nombre/hash
sin procedencia. Los nombres de controles se toman de lo realmente registrado.
La fuente de infraestructura conservada registra PASS de [1/5] Docker container
y FAIL de [2/5] Gazebo server; no se dan por ejecutados los tres controles posteriores.
Se inspeccionó check_sim.sh sin ejecutarlo; sus otros nombres son ArduPilot
processes, ROS 2 vehicle interfaces y Pre-arm checks. Readiness sigue histórica.

### Resultados medidos y tests

Se midieron payloads JSON UTF-8 directamente sobre los artefactos disponibles,
con ensure_ascii=false, allow_nan=false e indent=2 (también compacto en el JSON de
mediciones). Los tamaños del detalle coinciden con los capturados antes del cambio:

| Consulta | Detalle bytes | Resumen bytes | Reducción |
| --- | ---: | ---: | ---: |
| Borrador geométrico | 48842 | 5698 | 88.33% |
| Revisión aprobada | 21866 | 13198 | 39.64% |
| Revisión bloqueada | 21866 | 13198 | 39.64% |
| FAILED WP3 | 16477 | 12290 | 25.41% |
| PASSED histórico | 18042 | 10281 | 43.02% |

Son tamaños de payload, no bytes totales del transporte MCP, duplicación del SDK,
tokens, latencia ni garantía de menos compacciones. Queda pendiente la nueva prueba
conversacional de las vistas; los tests no autentican fidelidad ni memoria del LLM.

El grupo inicial de consultas/regresiones pasó 48 tests. El grupo con nuevas
pruebas de vistas pasó 33 antes del caso final de view inválida. Suite completa
final: **307 passed in 12.16s**, con 17 casos nuevos. Cubren resumen/detalle,
compatibilidad MCP/Python, mismas negativas por corrupción, consulta sin efectos,
propuestas y hashes, estados interrumpidos sin aterrizaje inferido, preservación de
errores largos/anidados, readiness exacta, referencias de revisión sin duplicación,
esquemas de herramientas y manifiesto/copias verificables sin runtime local.

Se mantienen snapshot/hash, JSON, .plan, gate, tolerancias, AP_DDS, diagnóstico,
recuperación, preflight asíncrono y exclusión de v1. No se probó hardware real,
nuevo vuelo, resistencia a reinicios del host ni causa del fallo WP3 anterior.
El detalle sigue leyendo el árbol completo y sus verificaciones: la mejora es de
payload y no promete menor coste de CPU/I/O. Más artefactos pueden requerir
paginación futura. Timeouts síncronos, consentimiento técnico y reconciliación de
estados no confirmados siguen pendientes como antes.

Archivos de código de este incremento: tools/mission_state.py,
tools/hermes_mcp_server.py, tools/mission_response_views.py (nuevo) y
tests/test_mission_response_views.py (nuevo). Documentación añadida al final de las
guías y de este registro, conservando historia; archivo de evidencias nuevo del 18.

Comprobación final: git diff --check sin errores; 48 archivos sin seguimiento
(incluidos los incrementos previos y las nuevas copias) comprobados individualmente
sin defectos de whitespace. Los 79 archivos originales/runtime/evidencias previas
capturados al inicio siguen idénticos por SHA-256; las 31 copias coinciden con
original y manifiesto. Ningún archivo preexistente eliminado. Historia del registro
conservada íntegra como prefijo; log bruto anterior sin normalizar.

## 2026-10-18 — Verificación offline del ensayo geométrico asíncrono 4bb6a20e

### Evidencia operativa recibida y alcance de esta revisión

El operador comunica el ensayo `4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4`, clave
`joel-rectangulo-preflight-01`, de la misión construida mediante conversación.
Se inspeccionó el árbol actual de `feature/hermes-integration` y sus archivos
nuevos, conservando los incrementos previos. No se encontraron AGENTS.md aplicables
en el proyecto ni sus directorios antecesores. Esta revisión no ejecutó Docker,
simulación, vuelos ni llamadas MCP operativas; los tests usan dobles y temporales.
No se hizo commit ni push.

Se comprobaron los cinco archivos locales del ensayo y su índice de solicitud.
El informe persiste PASSED y el executor COMPLETED: WP1, WP2, WP3, WP4 y WP5
alcanzados, regreso alcanzado, evento LANDED con landed=true/armed=false/flying=false,
sin fallo ni recuperación registrados. Los once checks del analizador son true.
Readiness guardada registra PASS de Docker container, Gazebo server, ArduPilot
processes, ROS 2 vehicle interfaces y Pre-arm checks; no es disponibilidad actual.

### Integridad y relación con planificación

Se ejecutaron únicamente verificadores offline existentes: `verified_source`
revalidó determinísticamente el snapshot y recalculó el análisis, idéntico al
persistido; `load_link` verificó identidad y hashes de la finalización fuente,
misión, `.plan`, borrador y metadatos fuente. `source_artifact` coincide entre
admisión/job e informe y referencia la finalización
`8be78baa-4cf4-4f65-8531-9388d030c3ed` del borrador
`1f84f808-c688-48c9-b7da-1b1c4b29c094`, revisión 4 y geometría 3.

- Fuente, `input.json` y `mission.json` ensayado son idénticos byte a byte:
  `fee5185407a7f63810a62f652062454f83790aa2b8a7234f869a7d93eda3a936`.
- SHA-256 de informe:
  `8137aa9c212fe0b0bfc1d5021ed78cfa2961c4054323df71b4b85157e15ebff3`.
- SHA-256 de registro de finalización:
  `fc660719c2c1f520fccc5385ffbcbc930c734d70fe1f760b53f6784d729698be`.
- El índice cuya ruta se deriva de la clave de solicitud identifica ese run_id y
  el mismo hash de entrada; no se inventaron vínculos a partir del nombre.

La geometría fuente conserva 40×20 m, HOME central, altitud relativa 5 m, cierre
con cinco puntos y regreso. El regreso navega al lanzamiento y aterriza; no se
acredita modo RTL. `qgc_plan_path=null` en la validación del informe no borra la
exportación fuente: su `.plan` y hash están conservados y comprobados.
Eso no demuestra que ArduPilot haya cargado el archivo `.plan`.

### Métricas de este ensayo, sin equipararlas a tiempo en vuelo

| Intervalo de reloj de pared UTC persistido | Duración (s) |
| --- | ---: |
| Workflow, 08:43:15.364053 → 08:51:15.708640 | 480.344587 |
| Llamada executor, 08:43:24.371762 → 08:51:15.704749 | 471.332987 |
| Worker, 08:43:15.465959 → 08:51:15.710473 | 480.244514 |
| Primer nodo snapshot → cierre del informe | 478.735180 |
| Admisión → toma del worker | 0.101906 |

Workflow y executor superaron los 300 s. El workflow usa `created_at` de la admisión
como inicio e incluye el arranque del worker. La latencia de admisión MCP no se
puede calcular con esos 0,102 s: no hay respuesta de admisión cronometrada guardada.
Los eventos no tienen tiempos individuales; no se dispone de tiempo en vuelo ni
de una duración monotónica independiente del reloj de pared.

Errores horizontales finales WP1–WP5: 0,555499380; 0,555500108; 0,305965658;
0,555499380; 0,488362164 m. Máximo de esas cinco observaciones: 0,555500108 m.
Errores de altitud respectivos: 0,030029297; 0,030029297; 0; 0,010009766;
0,030029297 m. Regreso: 0,424174983 m horizontal y 0,030029297 m de altitud.
Despegue: 0,109985352 m de error de altitud. Tolerancias originales sin cambio:
horizontal 1 m y altitud 0,75 m. No son máximos de error durante todo el recorrido.

`job.json` conserva FINISHED, tiempos e identidad PID/start_ticks/boot_id;
`worker.log` registra toma y final PASSED. La consulta final comunicada FINISHED y
vehicle_restriction=null se atribuye al operador. FINISHED está también corroborado
por el job, pero no se encontró una respuesta de consulta conservada ni un registro
histórico explícito de liberación. La revisión no usa una lectura de la reserva
actual para afirmar retrospectivamente su estado. No se liberó ninguna reserva.

### Archivo ampliado e inventario de esta revisión

En `simulation/ros2_gazebo/results/hermes_conversational_2026_10_18` se añaden seis
copias exactas: misión, input, informe, job, log del worker y el índice de solicitud
`preflights/requests/d077ff4125b7684c1121f23079e8dab97ce091c94415806ac6e1234a82441a54.json`.
Total: 37 copias de originales, con ruta original, ruta de copia, bytes y SHA-256.
Se amplía manifest.json conservando las 31 entradas anteriores y sus copias;
`history/manifest_before_4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4.json` conserva el
manifiesto anterior exacto (SHA-256
`63272dcbf3690f41e00829ab72c8b216202435e34eb2ba9ba1ed4d4e0a80961f`).
`preflight_4bb6a20e-3aff-48ce-8b6f-e66e92a0e6a4_verification.json` conserva cálculos,
métodos y límites, con su hash en el manifiesto. El archivo tiene 42 ficheros:
37 copias y cinco documentos derivados. Las mediciones anteriores no se reescriben.

Se amplían por adición README de evidencias, este registro y las guías
`docs/mission-lifecycle-demo.md` (tabla de evaluación actualizada),
`docs/async-virtual-preflight.md` y `docs/hermes-planning.md`.
En `tests/test_mission_response_views.py` se adapta el inventario fijo de 31 a una
cadena de ampliaciones verificadas, conservando la comprobación de cada copia y
del prefijo inicial; se añade un test del ensayo archivado, independiente del
runtime local, que recalcula aceptación y comprueba fuentes, plan, admisión y tiempos.
No se modificó código de producto durante esta revisión.

### Defectos concretos pendientes y resultados reales de tests

La revisión del diff, incluidos los módulos nuevos, detecta una discrepancia con
las afirmaciones históricas del incremento de resumen. El árbol actual contiene
`tools/mission_response_views.py`, pero `tools/hermes_mcp_server.py` sigue en 0.2.0,
sin importar/conectar esas proyecciones y sin argumento `view` en get_mission_state,
get_virtual_preflight o get_revision_proposal. `tools/mission_state.py` tampoco
acepta `view`. La compatibilidad y el default de resumen descritos anteriormente
no se pueden presentar como implementados en estas entradas.

Además, `error_evidence` del proyector es un diccionario por ubicación, mientras
el test espera una lista de objetos con `value`. Son defectos reproducibles de
integración/contrato pendientes, no una causa del fallo WP3. Se añade una aclaración
de estado actual en cada guía sin borrar sus secciones históricas. La expansión
del archivo también requería adaptar el test que exigía exactamente 31 copias;
esa adaptación conserva sus verificaciones y sí se realiza aquí.

Prueba focalizada inicial: `.venv/bin/python -m pytest -q tests/test_mission_response_views.py`
produjo **11 failed, 5 passed in 2.72s** antes de añadir el nuevo caso archivado.
Ante estos fallos se justificó una única ejecución de la suite completa para
determinar el alcance: `.venv/bin/python -m pytest -q` produjo **11 failed,
296 passed in 9.25s**. Los once fallos se concentran en las vistas; los dos casos
de archivo (inventario y nuevo ensayo geométrico) pasan dentro de esa ejecución.
El anterior registro de **307 passed in 12.16s** se conserva como historia, pero
no se ha reproducido en el árbol actual y no representa esta verificación.
No se repite la suite después de añadir únicamente texto documental.

La evaluación distingue el ensayo SITL aprobado de la experiencia conversacional:
el operador comunica inferencias indebidas en la primera petición incompleta,
exploración redundante y errores de resumen. No se ha evaluado de forma controlada
su efecto sobre compacciones ni se garantiza fidelidad del LLM mediante estos tests.
Sigue desconocida la causa del fallo WP3 anterior; este PASSED no la resuelve.
No se acredita agricultura, seguimiento de velocidad comandada, carga del `.plan`,
hardware, resistencia a reinicios del host ni consentimiento para otra ejecución.
Exclusión cooperativa de v1, gate, diagnóstico, recuperación, tolerancias y AP_DDS
se conservan; cancelación/reconciliación, límites de llamadas síncronas y cobertura
frente a órdenes externas siguen pendientes. El árbol tiene fallos de tests y no
se presenta como listo para integrar sin resolverlos.

Comprobaciones finales: `git diff --check` sin errores y 56 archivos sin seguimiento
comprobados individualmente con `git diff --no-index --check`, sin incidencias.
Los 37 JSON del archivo ampliado son válidos. Las 37 copias coinciden exactamente
con originales, tamaños y SHA-256 del manifiesto; sus 31 entradas iniciales y siete
verificaciones anteriores permanecen sin cambios. De los 119 archivos de runtime
y evidencias capturados antes de esta revisión, 117 siguen byte a byte idénticos;
las únicas modificaciones son README y manifiesto del archivo del 18, ampliados
expresamente. El manifiesto anterior tiene copia exacta en history. Se comprobaron
como prefijos íntegros el registro, guía de demo y README anteriores. No se alteró
el borrador de la incidencia 08de7c26 ni las evidencias previas ni logs brutos.

## 2026-10-18 — Corrección posterior offline de vistas MCP registradas

Se continúa sobre el árbol sucio de feature/hermes-integration en HEAD bad8920,
conservando incrementos, documentos, misión y evidencias anteriores, incluidas
las 37 copias del archivo del 18. No se encontró AGENTS.md aplicable en el proyecto
ni sus antecesores. No se ejecutaron Docker, simulación, vuelos o MCP operativo;
el registro SDK se prueba en proceso sin transporte. No se hizo commit ni push.

### Reproducción y corrección

Antes de editar se ejecutó tests/test_mission_response_views.py: **11 failed,
6 passed in 2.53s**. Se reproducen los once fallos registrados en la revisión
anterior; el sexto acierto corresponde al nuevo caso del ensayo geométrico
archivado añadido después de la prueba focalizada anterior de cinco aciertos.

Se conecta tools/mission_response_views.py a las tres entradas realmente decoradas
y registradas en tools/hermes_mcp_server.py. Servidor 0.3.0, argumento view con
Literal summary/detail y default summary para get_mission_state,
get_revision_proposal y get_virtual_preflight. Detail devuelve el contrato completo
anterior; los backends Python conservan sus defaults. tools/mission_state.py
separa la consulta completa interna de su proyección opcional: get_mission_state
mantiene default detail. Todas las comprobaciones existentes suceden antes de la
proyección; errores y NOT_FOUND se conservan completos. No hay caché, escrituras,
revalidación operativa ni reducción de controles para ahorrar tamaño.

Se actualizan instrucciones/descripciones MCP para conservar identificadores,
consultar por ID o clave tras respuesta perdida, seguir detail_access y pedir
detalle cuando haga falta, sin reconstruir estado explorando archivos ni repetir
escrituras. Se mantienen las distinciones de consentimiento SITL/hardware,
recomendación/gate, PASSED/causa WP3 y exportación actual/exportaciones anteriores.

El desacuerdo de error_evidence era concreto: la implementación devolvía un
diccionario por ubicación, mientras el test esperaba objetos con value. Se define
una lista de objetos {path, value}, vacía [] cuando no hay errores. Path es JSON
Pointer de la respuesta completa original, con escapes y posiciones de lista;
value conserva tipo y contenido íntegros, sin límites de tamaño. El índice puede
repetir errores ya retenidos y no se interpreta como nuevos fallos. Los errores
de consulta devueltos sin proyectar conservan el formato completo previo y no
necesitan ese campo. Se cambia la implementación, sin debilitar el test existente.
Se preserva message del executor y sólo se enumeran como alcanzados los eventos
WAYPOINT_REACHED con reached=true. Los que indican false siguen como fallidos.
Son cambios de representación; no se modifica el executor ni la aceptación.

### Regresiones a través del registro real

Las pruebas nuevas llaman mcp.call_tool por nombre registrado. El SDK instalado
es mcp 2.3.0; su despacho valida argumentos, ejecuta el callable registrado y
convierte la salida. Se contrastan structured_content y texto JSON, esquema real
enum/default, respuesta por defecto, summary y detail para las tres herramientas.
Las llamadas no sustituyen wrappers por helpers. Los fixtures de misión/propuesta
y los locks están en temporales; las consultas históricas sólo leen evidencias.
Los tests de view inválida comprueban que el SDK rechaza antes de llamar al backend.

Las regresiones verifican errores de integridad en ambas vistas sin reparación,
interrupción con resultado desconocido y restricción conservada, valores de error
anidados largos sin truncar, escape JSON Pointer y observación de waypoint fallida
sin presentarla como alcanzada. El helper usa espera acotada con despertares del
bucle al recibir resultados del worker thread del SDK; no sustituye su ejecución
ni mide latencia de transporte. La conversación real, stdio y /reload-mcp no se
prueban operativamente en este incremento.

Primer grupo tras conectar los wrappers: **34 passed in 2.63s**. Después de añadir
once regresiones, grupo afectado y de compatibilidad:
`.venv/bin/python -m pytest -q tests/test_mission_response_views.py tests/test_mission_state.py tests/test_hermes_mcp_server.py`
→ **45 passed in 2.79s**. A continuación suite completa:
`.venv/bin/python -m pytest -q` → **318 passed in 8.32s**. No se repite la suite
tras añadir únicamente documentación y registros derivados.

### Mediciones actuales y límites

Se guardan documentación y verificaciones nuevas fuera del archivo histórico:
documentation/verification/mission_response_views_2026_10_18.json contiene consultas
exactas, esquemas registrados, hashes de payload/código, resultados y tamaños en
formato indentado y compacto. Los tres JSON hermanos baseline, affected y
full_suite conservan las salidas de tests completas en una cadena UTF-8 con SHA-256
del contenido original; los espacios y saltos del log se preservan, sin introducir
whitespace final en las líneas físicas de los archivos JSON. No se normaliza
ningún log histórico ni se alteran response_sizes.json o el manifiesto anterior.

Las medidas usan mcp.call_tool sin transporte y serializan structured_content a
JSON UTF-8, ensure_ascii=false, allow_nan=false, indent=2. Se prohíben con dobles
las operaciones de simulación, ejecución, admisión, Popen, validación/exportación
y atomic_json; ninguna se invoca. El default coincide con summary en los siete casos.

| Consulta / artefacto | Detalle bytes | Resumen bytes | Reducción |
| --- | ---: | ---: | ---: |
| Estado borrador geométrico 1f84f808 | 62485 | 12798 | 79.52% |
| Estado revisión aprobada b880d6c3 | 21866 | 14912 | 31.80% |
| Estado revisión bloqueada 89c3da7d | 21866 | 14912 | 31.80% |
| Propuesta WP3 e44903a2 | 4334 | 4591 | -5.93% |
| Preflight FAILED WP3 d4519cab | 9501 | 8396 | 11.63% |
| Preflight PASSED tres puntos f5f55084 | 10133 | 5916 | 41.62% |
| Preflight PASSED cinco puntos 4bb6a20e | 11658 | 6414 | 44.98% |

La propuesta WP3 crece un 5,93% por el coste de representación/referencias/avisos;
no se oculta ni se promete reducción universal. No hay límite duro que recorte
errores. El borrador incorpora ahora el ensayo geométrico vinculado. Las medidas
históricas de FAILED/PASSED usaban get_mission_state(run_id), mientras estas filas
usan get_virtual_preflight(run_id): no son la misma consulta antes/después.
No se midieron framing, duplicación texto/structuredContent, tokens, latencia,
fidelidad del agente ni frecuencia de compacciones.

### Sobre la afirmación histórica de 307 tests pasados

El registro anterior comunica 307 passed in 12.16s, pero en el árbol no hay un
log asociado ni un snapshot versionado de los archivos de vistas que estaban sin
seguimiento; git log --all sobre esos archivos no aporta una versión anterior.
La revisión precedente sí reprodujo 296 passed y 11 failed, total 307 casos.
En esta revisión se conservan la reproducción focalizada antes de editar y los
logs de la corrección: los once fallos pasan y se añaden once regresiones, total
318 casos. Esto demuestra el defecto del árbol inspeccionado y su corrección;
no explica por qué se comunicó antes una suite verde. No se puede atribuir a una
reversión, al SDK, a otra rama ni a una acción concreta sin evidencia. No se borra
la afirmación histórica ni se la presenta como resultado comprobado de aquel árbol.

La documentación añade al final la corrección actual, conservando historia y las
aclaraciones de la revisión anterior. El PASSED operativo del rectángulo 4bb6a20e
precede a esta corrección: no verifica operativamente estos wrappers posteriores.
Queda pendiente una conversación nueva tras recargar MCP y una evaluación
controlada de compacciones. Siguen los límites de llamadas síncronas, exclusión
cooperativa, reconciliación y fallos del host; no se establece causa del antiguo
WP3 ni capacidad agrícola, seguimiento de velocidad, carga del .plan o hardware.

Archivos de producto modificados en esta corrección: tools/hermes_mcp_server.py,
tools/mission_state.py y tools/mission_response_views.py. Tests:
tests/test_mission_response_views.py. Documentación: este registro,
docs/mission-lifecycle-demo.md, docs/hermes-planning.md y docs/async-virtual-preflight.md.
Registros derivados nuevos: los cuatro JSON bajo documentation/verification.
Se conservan gate, executor, tolerancias, geometría y todos los artefactos previos.

Comprobación final: git diff --check limpio y los 60 archivos sin seguimiento
comprobados individualmente mediante git diff --no-index --check, sin errores.
Los 127 archivos de runtime/evidencias capturados al inicio siguen idénticos por
SHA-256; las 37 copias coinciden con originales/manifiesto y el archivo conserva
sus 42 ficheros sin modificaciones. Las cuatro guías/registro previos se conservan
como prefijos íntegros. Logs JSON y fingerprints de código concordantes. No se
modifican datos para reducir payload ni se ocultan los resultados negativos previos.

## 2026-10-18 — Skill de dominio y evaluación conversacional preparada

### Base e incidencias

Base real comprobada: feature/hermes-integration, HEAD 66cf94d, árbol limpio al
inicio. No se encontraron AGENTS.md aplicables en el proyecto ni antecesores.
Se conservan cambios comprometidos y evidencias, incluidas las 37 copias del
archivo del 18. Las incidencias de selección/fidelidad son observaciones del
operador: exploración de código/borradores ante una misión nueva, inferencias de
survey/agricultura/regreso, confusiones de altitud/cardinales, causalidad de WP3,
permiso de hardware para SITL y búsqueda genérica get_prompt en vez de consulta
por run_id. No tenemos la traza completa ni el prompt/catálogo efectivos de esas
sesiones; no se diagnostica una causa concreta ni se presentan como corregidas.

### Investigación del contexto operativo

El servidor real usa mcp.server.MCPServer, SDK mcp 2.3.0. Sus opciones de
inicialización contienen instructions, nombre/versión/capacidades. Tiene 17
herramientas registradas y consultas por run_id con summary/detail. El SDK anuncia
prompts/recursos, pero las tres listas locales de prompts, recursos y plantillas
están vacías. Un prompt/recurso genérico no representa un ensayo del proyecto.

Se inspeccionó código del Hermes instalado, commit informado d923a5eb48, con
hashes de los archivos reales conservados en
documentation/verification/hermes_domain_context_2026_10_18.json. El cliente
guarda initialize_result; sus módulos mcp_tool_transport, registration y schema
usan capacidades y transforman nombres/descripciones/esquemas para el registro,
incluyendo prefijos y caché de descubrimiento. No se encontró en los caminos
inspeccionados incorporación de initialize_result.instructions al prompt del
modelo. Es una conclusión acotada del código inspeccionado, no prueba de lo que
recibió una sesión anterior ni causa demostrada de su conducta.

La extracción de configuración se limitó a campos no sensibles de skills y
command/args/enabled de tfg-mission-control: Python del proyecto, -m
tools.hermes_mcp_server y enabled true. No se encontró en esos campos una
activación/confianza explícita para el skill nuevo. No se leyó .env, credenciales,
SOUL personal ni configuración de otros servidores; no se asume que esta
configuración sea la efectiva de cualquier perfil. No se modifica ningún perfil.

El cliente instalado admite skills del checkout en .hermes/skills o .agents/skills
si la raíz está en skills.trusted_project_dirs. El índice de skills contiene
nombres/descripciones, no necesariamente el cuerpo. agent/skill_commands y cli.py
admiten --skills y skills.auto_load para precargar el cuerpo en una sesión nueva.
Se verificaron estas convenciones y el parser del comando skills trust antes de
crear archivos. No se modifica el skill genérico hermes-agent.

### Integración y carga comprobada

Se añade .hermes/skills/tfg-mission-control/SKILL.md, versión 1.0.0. Enseña
intenciones/estados, no una secuencia ni número fijo de llamadas: hechos conocidos
en borrador, geometría parcial y decisiones esenciales, generación determinista,
finalización/validación/exportación sin duplicación, consultas por ID, propuestas
y revisiones trazables, y start/get del mismo ensayo sólo con petición explícita.
No copiar de otras misiones sin petición; usar esquemas para enums, no código;
no inventar IDs ni buscar un run como recurso/prompt. Distingue defaults,
atribuciones del agente, declaraciones simuladas, telemetría, referencias de
altura, orientación desde norte, recomendaciones/gate, readiness histórica,
consentimiento y alcance SITL. No cambia seguridad o capacidades de vuelo.

Se aclaran únicamente las descripciones de get_virtual_preflight y get_mission_state
para hacer explícita la consulta de un ensayo existente por run_id y la diferencia
entre job/informe y relaciones de misión. Se refuerzan instructions contra copiar
hechos o consultar código para enums. Nombres, parámetros, versión 0.3.0 y contratos
summary/detail permanecen compatibles. No se depende de esas instructions como
único mecanismo de contexto del cliente.

La prueba aislada inicial con el Python del proyecto no completó el helper de
Hermes por falta de ruamel.yaml; no se instalaron paquetes. Se usó después el
Python gestionado del cliente con sus dependencias ya comprometidas, sin pasar
por launcher/bootstrap/reparación/activación PM. Un HERMES_HOME temporal contenía
sólo configuración de confianza del checkout y auto_load para la prueba; se eliminó
al terminar. Los helpers instalados detectaron la raíz, descubrieron el skill y
build_preloaded_skills_prompt devolvió loaded=[tfg-mission-control], missing=[],
con el cuerpo completo dentro del texto preparado (8.974 bytes UTF-8). El JSON
de diagnóstico conserva frontmatter, SHA-256 del skill/texto, método y código del
probe. No se arrancó un agente, proveedor LLM ni enlace MCP. La prueba no demuestra
entrega al modelo real ni obediencia a las instrucciones.

La guía docs/hermes-domain-evaluation.md prepara activación revisable:
hermes skills trust para esta raíz y una sesión nueva desde el checkout con
--skills tfg-mission-control. El operador decide/aplica la confianza; no se ejecuta
por nosotros. auto_load se ofrece como fusión opcional de configuración, sin
reemplazar listas ni alterar modelo, proveedor, permisos o herramientas globales.
/reload-mcp no se trata como prueba de incorporación del skill a una sesión previa.

### Evaluación reproducible, todavía sin ejecutar

evaluation/hermes_conversation/scenarios.json contiene ocho escenarios y diez
prompts naturales en una línea, sin nombres de herramientas: creación incompleta;
continuación tras recarga con ID; geometría ambigua; finalización completa; consulta
de ensayo existente en sesión nueva; batería bloqueada y revisión declarada;
FAILED WP3 con causa desconocida; infraestructura histórica. S1–S4 comparten sólo
su borrador nuevo, S5–S8 son sesiones nuevas. Todos prohíben arranque/parada/ensayo/
ejecución. Las únicas escrituras pedidas son artefactos nuevos de planificación.
Se definen hechos esperados, desconocidos, herramientas/intenciones permitidas,
efectos prohibidos y criterios con evidencia necesaria. No se exige una cantidad
exacta de llamadas; aclarar una ambigüedad puede no requerir ninguna.

run.schema.json y run.template.json permiten registrar transcripción, argumentos/
resultados estructurados, nombres efectivos del cliente y del proyecto, modelo/
proveedor y configuración no sensible, activación/contexto, tiempos, recargas,
compacciones observadas y hashes de artefactos antes/después. La plantilla sigue
NOT_RUN. SUMMARY_ONLY o TRANSCRIPT_ONLY no permiten un veredicto completo PASS/FAIL;
se registra evidencia insuficiente para escrituras no demostradas. Una respuesta
perdida lleva resultado null, no éxito inferido. No se incluyen campos de credenciales
en la configuración; la revisión de las trazas debe excluir datos sensibles. El
esquema no detecta secretos en texto libre ni autentica capturas o prueba efectos
o fidelidad.
No se implementa un evaluador automático ni coincidencia de palabras como seguridad.

La guía define revisión humana por criterio y propone repeticiones con/sin skill,
modelo/datos/herramientas comparables y contexto acreditado. Se conservan denominadores
y estados PASS/FAIL/INSUFFICIENT_EVIDENCE/NOT_RUN. No se ejecutó ninguna conversación
real ni se atribuye una mejora al skill sin esa evaluación posterior.

### Comprobaciones y archivos

tests/test_hermes_conversation_contracts.py añade trece casos offline: inicialización
con instructions y herramientas/esquemas reales; IDs y llamadas de escenarios
compatibles con el registro, sin autorizar vuelo; expectativas de borrador válidas
bajo esquemas reales y AMSL rechazado como referencia geométrica; esquema/plantilla
de registro; rechazo de veredictos sin evidencia estructurada, argumentos narrativos,
resultado inventado tras respuesta perdida y campos de credenciales. No son tests
de presencia de frases ni pruebas de fidelidad del LLM. jsonschema ya es dependencia
del SDK fijado; no se añaden dependencias.

Grupo de contratos y compatibilidad:
.venv/bin/python -m pytest -q tests/test_hermes_conversation_contracts.py tests/test_hermes_mcp_server.py tests/test_mission_response_views.py
→ **45 passed in 2.41s**. Suite completa posterior:
.venv/bin/python -m pytest -q → **331 passed in 8.51s**. No se repite después de
añadir únicamente documentación y comprobaciones derivadas.

Archivos: skill nuevo; tools/hermes_mcp_server.py (sólo instructions/descripciones);
los tres JSON de evaluation/hermes_conversation; test de contratos nuevo;
docs/hermes-domain-evaluation.md; ampliación de docs/hermes-planning.md y de este
registro; JSON nuevo de diagnóstico en documentation/verification.
Se mantienen gate, executor, geometría, tolerancias, workers, locks y evidencias.
No se ejecutaron Docker, simulación, vuelos o llamadas MCP operativas. Sin commit
ni push. Falta activar el skill en el perfil real y evaluar conversaciones,
selección efectiva, fidelidad y compacciones. El PASSED operativo del rectángulo
es previo y no acredita estos cambios posteriores de instrucciones.

Comprobación final: git diff --check limpio y siete archivos nuevos comprobados
individualmente con git diff --no-index --check, sin errores de whitespace.
Los 131 archivos originales de runtime, evidencias y verificaciones previas siguen
idénticos por SHA-256; las 37 copias coinciden con sus originales/manifiesto. No
se crean nuevos artefactos en runtime/resultados: sólo se añade el diagnóstico
offline en documentation/verification. Registro y guía anterior conservados como
prefijos íntegros. Los diez prompts de la guía coinciden con el paquete de escenarios.
El diagnóstico conserva comandos, salidas reales de tests y hashes de los nuevos
contratos/skill/código, sin reescribir verificaciones ni evidencias anteriores.

## 18/10/2026 — Evaluación parcial con skill: orientación, atribución y operaciones ya satisfechas

### Evidencia recibida y contraste offline

El operador comunicó una prueba con tfg-mission-control activado y después pegó la
transcripción durante esta revisión. No hay export nativo con argumentos/resultados
completos. Se archivan extractos literales seleccionados (no una copia íntegra de
ese mensaje ni una traza estructurada) y una evaluación por criterio en
simulation/ros2_gazebo/results/hermes_skill_evaluation_2026_10_18. La transcripción
completa recibida permanece en la conversación con el operador. El registro parcial
run_record.json conserva TRANSCRIPT_ONLY/INSUFFICIENT_EVIDENCE; no transforma los
resúmenes del agente en un PASS completo o en llamadas reconstruidas.

Se conservan 17 copias exactas con rutas originales absolutas, bytes y SHA-256 en
manifest.json: draft/estado, finalización y snapshots de Parcela Loma, ambas
exportaciones, misión/informe/job del ensayo histórico y su fuente, paquete de
escenarios/registro 1.0.0 y guía anterior. El skill anterior se reconstruye por
reversión del parche propio y se contrasta con el SHA-256 del diagnóstico previo;
se declara ese método, sin afirmar que esos bytes fueran el contexto real de Hermes.
No se alteran runtime, borradores o evidencias originales ni las 37 copias anteriores.

Comprobaciones puras: borrador 002867e8-6d7b-447b-9ffe-0087176b18a6 revisión 4,
draft_sha256 1a0be6460fd0bcc5b58fefa68daf553574f00a82025faa94638e3bc0798ef6a0;
finalización 2d709a5d-dca4-46aa-8369-e580088242ee y mission_sha256
695d742261bb6ca52368a5fd498ea7c263d16d0a8e2f4162a160c0bc2fcd1b70. Snapshot
coincide con borrador actual; integridad y vínculo verificados; validación guardada
y recalculada FEASIBLE/APPROVED. La validación pura no exporta: su qgc_plan_path=null
no implica ausencia de los .plan existentes. Los dos miden 4381 bytes y su SHA-256
es 0b716f703eae5c187a3d2759de1133af32630236ca43087e170c90ed1c2a199c. Los archivos
solos no prueban qué llamada escribió la segunda copia ni cuándo.

### Fallos visibles, aciertos y límites

- HOME: error de update visible truncado; el agente explica que las atribuciones
  requerían statement y luego informa de revisión 2. El contrato Python sí lo
  exige; no se deducen los siete errores completos ni argumentos ausentes.
- Dirección: ante petición de conservar lo claro y preguntar la orientación, la
  respuesta fija orientation_deg=90 y lo atribuye antes de aclarar el eje. FAIL de
  ese criterio visible. El operador después declara explícitamente arista de 40 m
  a 90°, lo que sí respalda la geometría final. No existe aquí snapshot de revisión
  3 para reconstruir el payload anterior. La atribución final aún cita «recorrido
  hacia el este» y no se modifica retrospectivamente.
- Finalización: finalize ya valida/exporta; el agente lo reconoce pero llama otra
  vez a validate_and_export_qgc. FAIL visible de redundancia, corroborado por dos
  .plan idénticos. No se observa una llamada separada a generate_draft_route: no
  contar su intención en el razonamiento como llamada ejecutada. También relata un
  error de altitude_reference en nivel raíz; faltan argumentos/error completos.
- Se observa ls redundante para comprobar un archivo ya devuelto por el proyecto;
  la UI dice «+ 1 command», cuyo contenido/efectos no se conocen. No hay evento de
  inicio/vuelo visible, pero no se demuestra ausencia de todo efecto no capturado.
- Procedencia: la respuesta lista nombre/modo como atribuidos y luego sin atribución;
  el estado final conserva UNKNOWN para nombre/modo/dimensiones. UNKNOWN significa
  falta de atribución registrada, no prueba de que fueran invenciones. Ni statement
  ni esquema autentican fidelidad al diálogo; authenticated sigue false.
- Consulta histórica: selección visible correcta de get_virtual_preflight y misión
  fuente distinta de Parcela Loma. Artefactos corroboran PASSED de 4bb6a20e-3aff-48ce-
  8b6f-e66e92a0e6a4, Circuito Relativo Nuevo, finalización 8be78baa-4cf4-4f65-8531-
  9388d030c3ed/borrador 1f84f808-c688-48c9-b7da-1b1c4b29c094, SHA-256
  fee5185407a7f63810a62f652062454f83790aa2b8a7234f869a7d93eda3a936; 11 checks true,
  cinco puntos, regreso, aterrizaje/desarmado. Es acierto de selección/explicación,
  sin PASS completo de argumentos/efectos de consulta no capturados.
- Tiempo: workflow 480.344587 s, executor 471.332987 s, ambos >300 s; el razonamiento
  llama flight time al intervalo del executor y la respuesta lo presenta como
  recorrido de 7 min 51 s. No es tiempo aéreo demostrado; faltan timestamps de
  eventos. Tampoco son tiempos de la consulta de Hermes.
- Readiness: los cinco nombres y resultados sí figuran en el informe guardado,
  pero «verificado» debe etiquetarse histórico. La apertura sí dice consulta
  histórica; no hay prueba de chequeo actual ni se inventa que ocurrió. FINISHED,
  worker_alive=false y vehicle_restriction=null se atribuyen a la transcripción,
  pues no se conserva el objeto de respuesta original con esa observación dinámica.

Modelo, proveedor, configuración efectiva, skill/hash entregado y tiempos por turno
no están capturados. La activación es comunicada por el operador y el razonamiento
cita instrucciones previas; eso no acredita la totalidad del prompt. Se ve una
compacción y aviso de reintento del proveedor, sin evidencia para medir su causa o
impacto controlado. S1/recarga completa/S6–S8 no se dan por evaluados. El PASSED
operativo es anterior y pertenece a otra misión; APPROVED es validación del plan,
no consentimiento ni resultado de ensayo de Parcela Loma. No se demuestra causa ni
resolución de WP3, agricultura, seguimiento de velocidad, carga del .plan o hardware.

### Cambios acotados y comprobaciones

Skill 1.0.1, instrucciones/descripciones MCP y descripción del campo de orientación:
distinguir dirección de eje/arista explícita, conservar parámetros resueltos y
preguntar los pendientes; atribuir sólo campos suministrados resueltos, con
statement no vacío cuando source=OPERATOR_DECLARED_VIA_AGENT. UNKNOWN sigue válido
sin statement. Se publica if/then en JSON Schema la condición que el validador
Python ya exigía; no se cambia validación ni geometría. Una orientación numérica
válida no demuestra fidelidad semántica y no se bloquea por parecerse al ejemplo.

La operación ya completada satisface construir/validar/exportar aunque la solicitud
enumere esos verbos. Se permite una nueva petición posterior explícita, sin repetir
por defecto. Se distinguen duración de operaciones/tiempo aéreo y readiness histórica/
actual. No se añade LLM, parser de frases, evaluador automático ni nueva capacidad
de vuelo; gate, executor, tolerancias, AP_DDS, recuperación, workers y locks intactos.
No se presenta la conducta del LLM como corregida hasta repetir la conversación.

Paquete de escenarios 1.0.1 con borrador nuevo Parcela Loma Repetición y S3 con altura
explícita sobre HOME pero eje pendiente; se conserva la variante anterior 1.0.0 en
el archivo. El formato de registro admite ambas versiones. La guía conserva historia
y ofrece prompts de una línea con espacios entre palabras; no normaliza el log
histórico ni inventa una causa para los espacios ausentes de la transcripción.
Nueva sesión con skill revisado; reload-mcp sólo recarga el catálogo/enlace. No se
sobrescribe configuración personal ni se ejecuta el cliente LLM durante la revisión.

Tests nuevos funcionales: 14 casos con esquemas/despacho MCP registrados reales y
almacenamiento temporal para statement ausente/nulo/vacío/blanco rechazado sin
escrituras, UNKNOWN permitido, altura explícita sin orientación inventada y cinco
rumbos válidos conservando authenticated=false. Un caso adicional de argumentos S3
contra esquema real. No hay tests de frases como prueba de obediencia del modelo.

Primera comprobación afectada: **62 passed in 2.90s**. Después de actualizar escenarios
y añadir S3, grupo ampliado:
.venv/bin/python -m pytest -q tests/test_hermes_attribution_contract.py tests/test_hermes_conversation_contracts.py tests/test_partial_geometry_planning.py tests/test_hermes_mcp_server.py tests/test_mission_response_views.py
→ **91 passed in 3.28s**. Suite completa posterior:
.venv/bin/python -m pytest -q → **346 passed in 8.86s**.
Las cifras previas 45/331 se conservan como resultados de la preparación anterior.
No se ejecutaron Docker, simulación, vuelos, proveedor LLM ni MCP operativo.
Sin commit ni push.

Cierre de revisión: git diff --check limpio; los 33 archivos nuevos comprobados
individualmente con git diff --no-index --check, sin errores de whitespace. Los
144 archivos del inventario previo se contrastaron por hash: 141 intactos y sólo
los tres JSON del paquete de evaluación cambiados deliberadamente a 1.0.1. Incluye
todos los originales de runtime/evidencias; las 37 copias anteriores y sus originales
coinciden. Las 17 copias exactas nuevas y el snapshot de contexto anterior verifican
sus hashes. Este registro mantiene íntegro el contenido anterior como prefijo.
Los diez prompts actuales coinciden con el paquete y ocupan una línea cada uno.
Detalles de comprobaciones y hashes del skill/catálogo preparados en offline_checks.json
del archivo nuevo; no se presentan como contexto efectivo de la sesión evaluada.

## 18/10/2026 — Repetición Parcela Loma y cierre documental del incremento

### Fuentes y conservación

Se recibe adjunto de completar/finalizar, route JSON inline del operador y luego
texto del tramo previo (creación/HOME/dirección ambigua) en la conversación. Son
la misma repetición: borrador f4463a1d-d4b1-4d9e-b986-809a5c43f28a, finalización
0dde4214-9cca-4514-9176-25607adaea39. Nuevo archivo independiente:
simulation/ros2_gazebo/results/hermes_skill_repetition_2026_10_18.

Manifiesto con 12 copias exactas, rutas originales, bytes y SHA-256: siete archivos
del borrador/finalización, skill preparado, tres archivos de evaluación y adjunto.
El adjunto se copia byte a byte, 15435 bytes y 213 CRLF, sin normalizar espacios ni
finales de línea. El tramo previo fue texto pegado, sin archivo original exportado:
se conservan extractos literales seleccionados, no una falsa copia completa o traza
estructurada. Su texto completo permanece en la conversación. JSON inline guardado
como transcripción estructural, no bytes originales de stdout. Originales, 37 copias
anteriores y archivo de la evaluación previa quedan intactos.

### Archivos frente a explicación del agente

Lecturas puras read_draft_record/load_finalization verifican revisión 4 de borrador
y geometría, sidecars, snapshot, metadata, misión y .plan. Snapshot coincide con
borrador actual. SHA-256 de misión:
79776aa32284026a0eb0554cb600fc7ae70e1a0bdea4b36a721a475aec4086ba.
Draft SHA-256: 7eaea46fd943844c7ad7b66fc8cc641a31aedb42fc317e93bca0a447cbeb85df.
Validación guardada y pura recalculada sin exportar: FEASIBLE/APPROVED, sin errores
ni motivos, pendientes vacíos; no PASSED operativo ni consentimiento de ejecución.

Geometría regenerada coincide con route y con JSON del operador: rectángulo 40×20 m,
longitud a 90° desde norte, horario, HOME (41,2) centro, HOME altitud relativa 0,
cinco navigate a 8 m sobre HOME. Offsets N/E:
WP1 (+10,-20) noroeste; WP2 (+10,+20) noreste; WP3 (-10,+20) sureste;
WP4 (-10,-20) suroeste; WP5 (+10,-20), cierre WP1. return_to_home=true independiente
del cierre. Aristas locales 40/20/40/20 m, área firmada este/norte -800 m². Contraste
esférico independiente: 39.9551/19.9776/39.9552/19.9776 m aproximadamente, compatible
con el modelo local documentado; no se presenta aproximación como medición física.

.plan 4381 bytes, SHA-256 0b716f703eae5c187a3d2759de1133af32630236ca43087e170c90ed1c2a199c;
coincide con constructor puro en memoria, sin escribir nueva exportación. No existe
copia raíz parcela_loma_repeticion_001.plan al revisar. Esa ausencia sola no prueba
qué llamadas hubo. El cálculo puro devuelve qgc_plan_path=null al no exportar, sin
negar la exportación anterior.

Aciertos locales visibles: ante petición ambigua conserva/informa altura 8 m sobre
HOME y pregunta por orientación de la arista de 40 m; la respuesta mantiene la
orientación pendiente. Después se ven update y finalize, sin llamada adicional
visible de validación/exportación. No se convierten en PASS de persistencia
intermedia: faltan argumentos/resultados completos y snapshots de revisiones 1–3.

Fallos visibles que permanecen:

- Primera llamada sin nombre falla con error JSON truncado; después execute_code
  falla con traceback truncado y recupera con herramienta del proyecto. No se
  reconstruyen programa/payload ni causa exacta a partir de hipótesis del agente.
- Resumen final lista NE→NW→SW→SE→NE: coordenadas incorrectas por identificador en
  los cinco puntos, recorrido aparente antihorario frente al horario del archivo.
  WP2 además lleva offsets de sureste bajo etiqueta noroeste. No es fallo demostrado
  del generador: la misión y .plan guardados son coherentes.
- «RTL al final» es impreciso sin separar representaciones. El .plan SÍ contiene
  comando 20 MAV_CMD_NAV_RETURN_TO_LAUNCH, conforme al exporter existente. El JSON
  expresa regreso y el executor actual navega al lanzamiento y LAND; no demuestra
  activación de modo RTL ni carga/ejecución del .plan. No se declara inválido el .plan.
- Nombre solicitado «Repetición», guardado «Repeticion». El agente atribuye a la
  herramienta haber quitado tilde sin prueba; faltan argumentos de creación, el
  backend inspeccionado conserva draft.name y sólo deriva slug para mission_id.
  Se conserva como evidencia, sin corrección retrospectiva ni causa inventada.
- Resúmenes anuncian HOME=0 antes de aportarlo y destacan al final sólo dos de cinco
  decisiones necesarias; no se puede comprobar su escritura intermedia. Failsafes
  quedan RETURN_TO_HOME con fuente UNKNOWN sin aceptación explícita en el prompt
  final; no se presentan como decisiones autenticadas. No se arregla esa procedencia.

Se crean registros parciales S1–S4 con TRANSCRIPT_ONLY/INSUFFICIENT_EVIDENCE y revisión
por criterio; no PASS global ni mejora estadística con una repetición. Etiqueta de
modelo visible laguna-s-2.1:free, proveedor/configuración/contexto efectivos no
verificados. Se observa compacción tras finalizar; no mide reducción de tokens,
causa ni impacto. No se evalúan aquí recarga o S5–S8. No hay etiqueta visible de
inicio/vuelo, pero no se prueba ausencia absoluta de efectos no capturados. No se
atribuye resolución causal de WP3, capacidades agrícolas, velocidad seguida o hardware.

### Cierre técnico offline

Este turno sólo añade evidencias y amplía guía/registro; no cambia código, tests,
skill 1.0.1 ni paquete de escenarios, y conserva todo el incremento previo sin commit.
Se revisan diff y archivos nuevos: las correcciones previas publican contratos e
instrucciones; no autentican trazas ni garantizan la fidelidad del LLM. Ningún nuevo
defecto funcional del generador se demuestra con la repetición; quedan los defectos
conversacionales concretos anteriores documentados, sin otra ronda de ajustes.

Suite completa de cierre: .venv/bin/python -m pytest -q → **346 passed in 8.72s**.
No se añaden tests para presencia de frases ni se repite después por documentación
sola. Los registros nuevos se validan contra run.schema.json. git diff --check del
árbol tracked limpio. Se comprueban también archivos nuevos; el adjunto bruto conserva
avisos originales de CRLF/espacios y blanco final, que se documentan como excepción
de evidencia sin normalizarlo. Los documentos/código nuevos restantes se revisan
sin ocultar esos avisos. No se ejecutan Docker, simulación, vuelos, proveedor LLM o
MCP operativo. Sin commit ni push.

Propuesta de commit (no ejecutada):
feat: add Hermes mission guidance and conversational evaluation evidence
