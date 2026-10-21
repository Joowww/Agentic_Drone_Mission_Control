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

## 18/10/2026 — Selección drone_01/v1 y drone_02/v2 con exclusión global

### Inspección y alcance

Árbol inicial limpio en feature/hermes-integration, HEAD 041d266 (el incremento
conversacional anterior ya estaba committed por el operador). No se encontraron
AGENTS.md aplicables en la raíz/ancestros ni dentro del proyecto. Se conservaron
los cambios y evidencias recibidos; no se ejecutó infraestructura.

Inspección de mapper, control ROS2, executor completo, workflow LangGraph síncrono,
admisión/worker asíncronos, reservas, análisis, fuente verificada/revisiones y
wrappers/esquemas MCP reales. Mapper y ROS ya recibían interfaz; v1 seguía fijado
en MCP/graph/análisis y exclusión. El decorador antiguo dejaba pasar v2 sin lock.
Además run_demo.sh arma/despega ambos drones y su wrapper sólo esperaba aterrizaje
de v1: una reserva única no volvía seguro ese vuelo paralelo bajo el nuevo alcance.

Incremento exclusivamente SITL, una misión/un vehículo seleccionado por solicitud,
una sola ejecución de vuelo activa global. No agricultura, asignación, coordinación,
separación entre drones, nuevo modo RTL ni garantía operativa de v2.

### Resolución, ejecución y garantías

Nuevo resolver puro tools/simulated_vehicle.py: correspondencia exacta drone_01→v1,
drone_02→v2; sin aliases, fallback o sustitución de IDs desconocidos. Public executor
conserva keyword vehicle como comprobación opcional de correspondencia (None deriva
de MissionDefinition). La selección ocurre antes de reservar/gate y se comprueba
otra vez con la carga que usa el executor. Desconocidos/discrepancias bloqueados antes
de ROS. El gate añade identidad antes de su validación/readiness; mantiene reglas
deterministas y no depende del preflight. Compatibilidad real sigue comprobada por
executor/workflow antes de comandos (no se amplían multirrotor/ArduPilot/navigate).

Se reutiliza el cuerpo del executor con un wrapper de selección, sin copiar la lógica
de vuelo. Origen, geopose de lanzamiento, status, GUIDED, ARM, despegue, objetivos,
regreso, waits, LAND, recuperación y diagnóstico usan la interfaz resuelta. Mapper
permanece intacto: copia geometría relativa alrededor del lanzamiento real de ese
dron, no gps_global_origin. Control ROS valida namespace y exige autoridad viva del
mismo vehículo para emitir órdenes. Constantes AP_DDS 6/3576, QoS best_effort,
tolerancias 1 m/0.75 m, polling, timeouts y recuperación no cambiados.

Reservas por namespace v1.json/v2.json con vehículo lógico/interfaz en registros
nuevos; registry.lock serializa cambios y la presencia de cualquiera bloquea ambos.
El fichero OS existente v1.execution.lock se conserva como mutex GLOBAL compartido,
no uno por dron. Autoridad revocable/contexto, PID+start ticks+boot ID, token worker,
clave idempotente, snapshot/hash y logs separados de stdio MCP se conservan. El alias
Python serialized_v1 permanece, protegiendo también v2 en vez de saltárselo.
Reservas malformadas/conflictivas fallan cerrado; consultas no las reparan o liberan.

Safe release requiere no vuelo o aterrizaje/desarmado del seleccionado y coherencia
de identidad. Worker desaparecido/reciclado, recuperación fallida, resultado o
binding no confirmado conservan reserva y bloqueo global. Una identidad contradictoria
no autoriza liberar aunque el resultado diga COMPLETED o incluya LAND. No se añaden
reintentos, arranque automático, desbloqueo ni recuperación automática de workers.
La demo paralela queda explícitamente deshabilitada antes de subprocess tanto en
wrapper como verificación de hijo del script existente; no se sustituye por una
falsa demo monovehículo ni se habilitan dos vuelos. Es una restricción intencional
de esa entrada histórica para cumplir una sola ejecución, no soporte de coordinación.

### Informes, consulta y compatibilidad

Jobs nuevos schema_version=2 e informes 1.1 incluyen vehicle_selection con vehicle_id
lógico y simulated_vehicle. Admission/get y summary/detail lo conservan; raw executor
mantiene vehicle como interfaz y añade vehicle_id. Analyzer estricto comprueba ambos,
además de los once checks reales existentes. Worker y consultas contrastan input/hash,
selección, snapshot, misión e identidad del resultado; errores no desencadenan efectos.
vehicle_restriction describe el elegido; global_flight_restriction puede pertenecer
al otro y bloquearlo. Resultado, motivos, incertidumbres, consentimiento, rutas y
vínculos se mantienen. No hay selector nuevo MCP independiente que pueda contradecir
la misión; el wrapper execute ya no fija v1 y sigue usando progress=False.

Históricos 1.0 conservan contenido/hash/criterios v1. Respuestas indican
LEGACY_RECORDED_V1, sin convertir antiguos ensayos en v2 ni rellenar lógico desconocido
con drone_01. Fuente verificada mantiene análisis legacy para no invalidar hashes ni
revisiones previas. No se reescriben informes. Nuevos casos con identidad incompleta
o contradictoria no heredan esa excepción legacy. Readiness sigue comprobando el
stack y ambos vehículos con sus controles actuales, sin inventar probes por namespace.

Ejemplo nuevo missions/examples/simulation_navigation_drone02.json: tres waypoints
del ejemplo existente, vehículo explícito drone_02, valores de escenario SITL. Validación
pura real sin exportar → FEASIBLE/APPROVED, sin errores, binding drone_02/v2; no es
PASSED ni vuelo. Skill de dominio 1.1.0 sólo actualiza alcance factual/binding/exclusión
y exige evidencia operativa específica, sin afirmar una mejora de fidelidad del LLM.
Las evaluaciones/skills archivados 1.0.x no se modifican. Nueva guía
 docs/simulated-vehicle-selection.md y avisos de estado actual en guías de preflight,
con historia v1 conservada y prompts de una línea para revisión/ensayo/consulta posterior.

### Pruebas offline y límites

Se adaptan dobles antiguos a la identidad requerida, sin relajar criterios de vuelo:
SimpleNamespace declara drone_01, resultados completos incluyen lógico, informes
sintéticos de worker tienen binding/snapshot/hash coherentes y primitivas ROS se
prueban dentro del ámbito autorizado. El test de input de admisión alterado ahora
exige rechazo antes de ejecutar y reserva conservada, no una limpieza insegura.
Tests de la demo reflejan su bloqueo intencional incluso sin otro propietario.

41 casos nuevos en tests/test_simulated_vehicle_selection.py: ejecución real de código
con control/telemetría doblados para v1/v2, mapping desde lanzamientos distintos,
objetivos/regreso/LAND, rechazo de IDs/discrepancias/capacidades sin comandos, graph y
worker completos v2, recuperación correcta/fallida y diagnóstico, análisis de identidad,
consultas SDK summary/detail sin efectos, históricos/hash intactos, inicios concurrentes,
idempotencia/cambio de dron con misma clave, recarga sin replay, worker perdido,
reserva global cruzada, OS mutex común, autoridad caducada/equivocada, registros
malformados y corrupción de selección/misión/resultado. Builders ROS comprobados
con namespaces/constantes reales y runner doblado. No se infiere evidencia de un
vuelo a partir de estos tests.

Resultados reales: primera revisión afectada 25 failed/96 passed por contratos de
los dobles y selección; se corrigieron sus entradas/expectativas y las validaciones,
sin ocultar fallos. Grupo original después 121 passed in 3.34s; 34 nuevos iniciales
34 passed in 2.28s; primera suite completa 380 passed in 9.20s. Tras refuerzos de
identidad, recarga/corrupción y reserva JSON malformada, comprobación final:
.venv/bin/python -m pytest -q tests/test_simulated_vehicle_selection.py tests/test_simulation_mission_executor.py tests/test_virtual_preflight.py tests/test_virtual_preflight_jobs.py tests/test_vehicle_execution_lock.py tests/test_ros2_flight_control.py tests/test_mission_execution_gate.py tests/test_hermes_mcp_server.py
→ **162 passed in 4.10s**.
.venv/bin/python -m pytest -q → **387 passed in 9.40s**.
No se repite la suite tras cambios exclusivamente documentales/de evidencia.

Pendiente prueba operativa autorizada de drone_02/v2 en Gazebo/AP_DDS. No se demuestra
separación, prevención de colisiones, seguimiento de velocidad, carga/ejecución del
.plan, agricultura, hardware o solución causal del fallo antiguo WP3. El control es
cooperativo entre entradas del proyecto, no contra ROS/QGC manual o versiones antiguas
aún ejecutándose; no se acredita actualización en caliente ni resistencia a reinicio
host. Se mantienen límites TOCTOU y consentimiento explícito por ensayo/hash.
No se ejecutaron Docker, simulación, vuelos, proveedor LLM o llamadas MCP operativas;
el registro SDK se prueba en proceso con dobles. Sin commit ni push.

Revisión final adicional: se impide rebajar un informe nuevo a schema 1.0 para evitar
la comprobación estricta de identidad de v1. Jobs schema 2 exigen informe 1.1 y un
informe con vehicle_selection no puede clasificarse como legacy. Se añade regresión
con un resultado nuevo v1 alterado (se elimina lógico y cambia versión): consulta y
fuente verificada rechazan sin reparar o repetir ejecución. Los históricos genuinos
no cambian ni se invalidan. Esta corrección funcional justifica repetir pruebas;
no es una ronda de tests tras documentación sola.

Resultados definitivos: **42 casos nuevos**, grupo **163 passed in 4.20s**, suite
completa **388 passed in 11.70s**. Sustituyen las cifras de cierre provisional 162/387
anteriores, que se conservan como historia real. git diff --check limpio y cinco
archivos nuevos comprobados individualmente sin errores de whitespace. Inventario de
192 archivos de misiones generadas/evidencias, incluido el raw histórico y las 37
copias anteriores: mismos archivos y SHA-256, sin nuevas escrituras en esos árboles.
Comandos, resultados, inventario completo del diff y límites en
 documentation/verification/simulated_vehicle_selection_2026_10_18.json.
No commit/push ni prueba operativa nueva; sigue pendiente el ensayo autorizado de v2.

## 18/10/2026 — Backend listo y confirmación visual de Gazebo

Incremento exclusivamente conversacional sobre el árbol anterior de selección v1/v2,
sin descartar sus cambios ni modificar sus evidencias. No aparece un AGENTS.md
aplicable en el repositorio o sus ancestros inspeccionados. Se revisan el skill de
dominio, inicialización/descripciones MCP, wrappers de lifecycle/readiness, scripts
de arranque/parada/check y contratos de consulta antes de editar.

### Observación comunicada y alcance de la evidencia

El operador comunica en este chat que el último arranque devolvió READY para ambas
interfaces pero Gazebo apareció negro. No se aporta aquí la transcripción de su otro
chat: argumentos, salida bruta, secuencia, imagen y momento exacto de cada comprobación
no están capturados. Se registra como observación del operador, sin afirmar causa,
cinco checks verificados o relación causal con incidentes antiguos/WP3. No se ejecuta
un arranque, recuperación o prueba conversacional nueva para corroborarla.

### Inspección y cambios

El script de start limpia procesos previos antes de lanzar el stack; repetir start
puede reiniciarlo y no es una consulta visual. Su anuncio de topics disponibles y
GUI ON no demuestra renderizado. El checker separado observa Docker container,
Gazebo server, ArduPilot processes, ROS 2 vehicle interfaces y Pre-arm checks; no
comprueba imagen ni ausencia de vuelos/reservas. No se añade un control ficticio.

Skill tfg-mission-control 1.1.1, instrucciones de inicialización y descripciones
registradas de check_simulation_ready/start_simulation/stop_simulation separan backend
de imagen declarada por el operador. Tras arranque con GUI se pregunta si aparecen
correctamente mundo y drones, pantalla negra o ninguna ventana. Ante negro/ausencia,
se ofrece un reinicio controlado, dejar pendiente o continuar expresamente sin imagen.
El aviso de fallo no concede permiso de reinicio; continuar sin imagen no autoriza
vuelo ni elimina readiness, gate, reservas o consentimiento explícito por ensayo.

Antes de recuperar se comprueban ejecuciones conocidas y restricciones actuales por
IDs/claves reales con las consultas del proyecto. Worker activo, cualquier reserva
global/por vehículo o resultado no confirmado impiden stop/start por la GUI incluso
con aceptación. ERROR/NOT_FOUND, falta de ID o respuesta perdida no prueban estado
libre: se deja pendiente, sin inventar IDs, explorar carpetas ni liberar restricciones.
FINISHED/PASSED histórico no acredita ausencia global de otra ejecución. No hay una
consulta de inventario global sin ID en este incremento.

Con aceptación específica y estado libre verificado se revalida antes de actuar:
un stop, esperar parada confirmada, un start, esperar resultado, consultar readiness
y volver a preguntar por la imagen. Sin paralelismo, avance tras fallo/timeout,
reintento por respuesta perdida o bucle automático; si sigue negro, no se extiende
el permiso anterior. Se documentan sólo evidencias reales de parada (remaining=[]
cuando esté en la salida), sin inventar campos devueltos por los wrappers.

Las consultas no adquieren un cerrojo atómico entre lifecycle y vuelo; start/stop
comparten su propio lock, no el mutex de ejecución. Se exige establecer con el
operador un intervalo sin otros inicios y dejar pendiente si no puede comprobarse.
Es guía conversacional, no un nuevo interlock ni garantía frente a una carrera
concurrente. No se modifican scripts, renderizado, executor, gate, reservas,
geometría, selección de vehículo, esquemas de entrada ni cuerpos de las herramientas.

Nueva guía docs/simulation-gui-confirmation.md y enlace en docs/hermes-planning.md:
fuentes/tiempos del estado visual, límites y siete escenarios manuales preparados,
todavía no ejecutados. No se inventan campos de imagen en MissionDefinition/report.
El contenido anterior de las guías/registro se conserva. La recarga de catálogo MCP
no demuestra carga del skill revisado: debe comprobarse su contexto en Hermes.

### Comprobaciones offline

.venv/bin/python -m pytest -q tests/test_hermes_conversation_contracts.py tests/test_hermes_mcp_server.py tests/test_simulation_lifecycle.py tests/test_simulated_vehicle_selection.py
→ **77 passed in 7.12s**. Son contratos SDK registrados y lifecycle/selección con
dobles, no llamadas MCP operativas ni verificación de obediencia del LLM. No se
añaden tests de presencia de frases. La suite completa de 388 del incremento anterior
queda como resultado histórico; no se repite tras cambios sólo de instrucciones,
descripciones y documentación. La conducta conversacional nueva sigue pendiente de
evaluación con argumentos/resultados y consentimiento capturados.

No se ejecutan Docker, simulación, vuelos, proveedor LLM ni MCP operativo. Sin commit
ni push. Se preservan los cambios de selección v1/v2 y las evidencias anteriores.

Cierre offline: 17 herramientas registradas, mismos esquemas de entrada SHA-256
a7102e858c349855ed8143cdbf3359976950f2cbe08cd99f9a2d20b52404d980 que en la
verificación anterior. Inventario al inicio de este turno: 339 archivos; sólo cambian
skill, servidor (instrucciones/descripciones), guía Hermes y este registro, más la
guía GUI nueva. Los 192 archivos de misiones generadas/evidencias mantienen sus
SHA-256; todos los demás cambios anteriores permanecen intactos. Prefijos completos
anteriores de guía/registro conservados. git diff --check limpio; los seis archivos
nuevos del árbol acumulado comprobados individualmente sin errores de whitespace.

## 18/10/2026 — Primer ensayo operativo del incremento en drone_02/v2

Se verifica offline el ensayo 7162bce5-3635-4a76-bf02-6a5a22612aab, clave
joel-drone02-preflight-01, ya ejecutado por el operador. No aparece AGENTS.md aplicable
en los ancestros/repositorio inspeccionados. Se conservan todos los cambios anteriores
de selección v1/v2 y GUI, borradores, logs brutos y evidencias; no se añade funcionalidad
ni se ajusta el skill. El estado inicial sigue en feature/hermes-integration sobre
041d266afe95b7c8e32de06467510d1b3be3d09f, con cambios sin commit.

### Archivo exacto e integridad

Nueva carpeta simulation/ros2_gazebo/results/simulated_vehicle_v2_2026_10_18:
ocho copias exactas (74292 bytes) de mission.json, input.json, job.json, report.json,
worker.log, índice de request_key, ejemplo fuente y adjunto completo de Hermes.
Manifiesto con rutas originales/copias, bytes y SHA-256; README y offline_checks.json
son documentos derivados. Copia binaria, sin normalizar transcripción ni worker.log.
No se sobrescriben originales, otras copias o manifiestos anteriores, incluidas las
37 copias del archivo conversacional del día.

Snapshot, input y missions/examples/simulation_navigation_drone02.json son idénticos:
1717 bytes, SHA-256 ce94effedb4c977b0db3c64e41d4a2b86bba9a78c494cfeda4305d069d54bebb.
Coincide con job.input_sha256, report.expected_sha256 y report.mission_sha256. Índice
de clave, run_id y rutas pertinentes coherentes; source_artifact=null: procede del
ejemplo JSON autónomo, no de una finalización de borrador. Job schema 2, report 1.1,
selection/expected_selection, mission_identity y executor coinciden en drone_02/v2.
PID/start_ticks/boot_id del worker conservados; no se consulta vida actual ni se
autentica qué árbol de código estaba desplegado en aquel proceso.

### Resultado persistido y reanálisis real

Job FINISHED, phase=analyze; informe PASSED, execution_attempted=true. Executor
success=true/COMPLETED con 14 eventos en orden: GUIDED/ARM, despegue a 5 m, tres
waypoints WP1/WP2/WP3, regreso a SIMULATION_HOME, LAND y LANDED. Final:
landed=true/armed=false/flying=false; no error o recuperación registrados. Regreso
por navegación al lanzamiento y LAND, no modo RTL. simulation_origin y launch_position
son distintos y se conservan: el reanálisis usa el lanzamiento para el mapper.

Errores horizontales WP1/WP2/WP3 0.396770505/0.227773753/0.480681034 m; verticales
0/0/0.010009766 m. Regreso 0/0 m; despegue error 0.230041504 m. Tolerancias actuales
1 m horizontal y 0.75 m vertical, sin cambios. analyze_executor_result con identidad
estricta reproduce exactamente el análisis guardado: once criterios true, sin motivos.
validate_mission sin exportar reproduce exactamente FEASIBLE/APPROVED sin errores.
Readiness guardada: Docker container, Gazebo server, ArduPilot processes, ROS 2
vehicle interfaces y Pre-arm checks, ambos topics/status y armables; histórica, no
una comprobación actual o evidencia de renderizado. worker.log sólo conserva dos
líneas (claim y final PASSED), no telemetría/comandos independientes.

Duraciones calculadas con timestamps UTC del informe: started_at 17:34:26.794699 a
finished_at 17:39:26.637756 → **299.843057 s**, incluida la admisión anterior al graph;
execution_started_at 17:34:40.657446 a execution_finished_at 17:39:26.629183 →
**285.971737 s**. Admisión a job.finished_at 17:39:26.640580 → 299.845881 s;
worker.started_at a job.finished_at → 299.301760 s. Son intervalos de operaciones,
no tiempo en vuelo: faltan timestamps individuales de eventos. Este ensayo no
superó 300 s en esos intervalos ni elimina el límite de las herramientas síncronas.

### Conversación, reservas y alcance operativo

Ahora sí existe un adjunto accesible, conservado completo con su hash. Muestra
activación del skill sin acreditar versión cargada, readiness inicial bloqueada,
petición de arranque, aviso de pantalla negra y petición explícita de un reinicio
único secuencial. Se ven stop/start/check, pregunta visual posterior, confirmación
del operador de que ve mundo/drones y autorización explícita de un solo ensayo v2.
No se ve comprobación de reservas previa al reinicio ni pregunta visual tras el
primer arranque. No se transforma este tramo en PASS completo del skill o solución
causal del negro. No se ajustan instrucciones en esta revisión.

Se ve un inicio y dos consultas del mismo ensayo, por clave y run_id. Hermes comunica
reserva vehicle/global EXECUTING en la consulta intermedia y ambas null al finalizar.
Se atribuyen a esos resúmenes de consulta del operador: no hay respuestas MCP
estructuradas brutas, historial de reserva o auditoría de liberación en los cinco
archivos. El fin/log es coherente con salida normal, sin usar FINISHED/PASSED para
inferir por sí solos reserva libre actual. No se consulta/borra ahora ninguna reserva.
La política revisada mantiene ejecución serializada con reserva global; tests
offline verifican rechazo entre v1/v2, no se hace prueba operativa de contención.
No hay posición/status independiente de v1 durante el ensayo: no se afirma que
permaneció inmóvil, coordinación simultánea, separación o prevención de colisiones.

El adjunto anuncia 21 herramientas y luego «Agent updated — 0 tool(s) available»;
la verificación offline previa del registro del repositorio tenía 17. Queda
desacuerdo de catálogo/contexto sin causa demostrada, no prueba de inexistencia de
herramientas ni motivo para cambiar configuración personal. También se ven lecturas
de archivos/esquemas y resúmenes, pero no argumentos completos de todas las llamadas.
No se acredita fidelidad global, mejora estadística, configuración/modelo reales o
versión desplegada; la etiqueta visible laguna-s-2.1:free es sólo dato de la transcripción.

Se actualiza docs/simulated-vehicle-selection.md con el primer ensayo operativo de
este incremento; sus cifras offline iniciales se conservan como historia. El
precision_agriculture del JSON es metadato del ejemplo: sólo se ejecutan navigate,
sin acción agrícola verificable, velocidad seguida, .plan cargado o hardware.
qgc_plan_path=null no acredita ausencia de exportaciones previas. PASSED no autoriza
otro vuelo ni resuelve la causa antigua de WP3. Persisten límites de hash/TOCTOU,
control cooperativo frente a ROS/QGC externo/versiones antiguas, ausencia de interlock
atómico lifecycle/vuelo y falta de evidencia de resistencia a reinicios del host.

### Revisión y comprobaciones

Se revisa el diff acumulado de selección/identidad, executor, ROS, graph, análisis,
worker, reservas globales/por vehículo, consultas, MCP y tests, incluidos archivos
nuevos. Sin cambios de código en este cierre. Los límites anteriores siguen abiertos;
un único vuelo no valida interleavings concurrentes o todo el comportamiento del LLM.
.venv/bin/python -m pytest -q → **388 passed in 10.11s**, suite completa offline con
dobles. Se comprueban además hashes/copia exacta, índice, rutas, identidad, validación
y análisis sobre los artefactos operativos, sin ejecutar graph/executor ni MCP.
No se repiten tests tras documentación/copias solamente. No Docker, simulación,
vuelos o proveedor LLM durante este cierre. No commit ni push.

Cierre de conservación: inventario inicial de 346 archivos; sólo se modifican esta
entrada del registro y docs/simulated-vehicle-selection.md. Los otros 344 conservan
SHA-256, incluidos los 198 archivos originales de misiones generadas/evidencias.
Las 37 copias del archivo hermes_conversational_2026_10_18 también se verifican
contra su manifiesto previo, sin modificarlo. Únicos archivos añadidos en este turno:
11 del nuevo archivo (ocho copias, README, offline_checks.json y manifest.json).

git diff --check de archivos versionados limpio. Se comprueban individualmente los
17 archivos no versionados del árbol acumulado: 16 limpios; la copia binaria
transcripts/hermes_raw.txt emite avisos de trailing whitespace por sus CRLF/espacios
originales. Se conserva byte a byte por ser evidencia; no se normaliza, no se cambia
configuración Git para ocultar avisos ni se presenta ese fichero como limpio.
Los hashes del manifiesto y de las dos comprobaciones derivadas quedan verificados.

### 18/10/2026 — Ampliación del operador: parada y readiness posterior

Para el cierre del ensayo 7162bce5-3635-4a76-bf02-6a5a22612aab, el operador comunica
en un mensaje posterior: stop_simulation devolvió SUCCESS y ausencia de procesos
atribuibles restantes; después check_simulation_ready devolvió NOT READY, con
Docker aún activo y fallo en Gazebo. Es una declaración del operador sobre una
secuencia ya realizada, no una llamada operativa ni nueva observación de este agente.
El mensaje no aporta respuesta estructurada bruta o tiempos de las operaciones.

Se contrasta la semántica leyendo check_sim.sh, sin ejecutarlo: Docker container
se comprueba primero; el fallo de Gazebo server provoca exit 1 antes de ArduPilot
processes, ROS 2 vehicle interfaces y Pre-arm checks. Por tanto esos tres controles
se registran como NO EJECUTADOS, no FAIL/PASS ni ausencia demostrada de interfaces.
Docker activo y procesos del proyecto detenidos son compatibles: stop no implica
parar el contenedor. El NOT READY posterior no contradice ni modifica PASSED o los
cinco controles históricos guardados durante el ensayo. Tampoco acredita por sí
solo reserva libre, inmovilidad de v1 o causa del negro.

Se añade closure_operator_followup bajo el archivo de evidencias v2 del día:
operator_statement.txt conserva el texto recibido (UTF-8 con salto de línea final),
verification.json registra la atribución, secuencia y controles no ejecutados;
manifest.json da hashes de esos dos archivos y referencia el SHA-256 del manifiesto
previo. No se reescriben las ocho copias, transcripción bruta, metadatos, informe,
offline_checks.json o manifiesto anterior. La guía de selección incorpora este
cierre distinguiendo relato del operador de hechos persistidos.

Verificación offline: hashes de originales/copias y manifiestos, análisis estricto
y validación determinista del ensayo. No se repite la suite por este cambio sólo
documental/de evidencia; **388 passed in 10.11s** sigue siendo el resultado real de
la revisión anterior, no una ejecución nueva. Sin cambios de código/skill ni
Docker, simulación, vuelos, proveedor LLM o MCP operativo. Sin commit ni push.

## 18/10/2026 — Orquestación persistente de dos ensayos SITL secuenciales

Base real feature/hermes-integration, 7b6e34977a865ce031482f9bf3358fc8960c917b,
árbol limpio al iniciar; instrucciones AGENTS.md no presentes en repositorio/ancestros
inspeccionados. Se conservan los incrementos y evidencias anteriores. No se ejecuta
Docker, simulación, vuelos, proveedor LLM o MCP operativo en este desarrollo.

### Decisión de exclusión y reutilización

Inspección previa de jobs, worker, authority, reservas, mutex, análisis/verificación,
gate y contratos MCP: dos starts independientes liberarían el slot entre hijos.
Se explica ese hueco antes de implementar. Se introduce sequence.json en el registro
de reservas, bajo el registry.lock común. Dura toda la operación y bloquea tanto
admisiones independientes como executor síncrono, incluso entre hijos cuando no
hay v1.json/v2.json activo. Cada slot exacto run_id/vehículo/hash se consume una vez,
en orden, sin permitir el siguiente hasta la aceptación explícita del resultado
del anterior por el coordinador. Esa aceptación es determinista, no un segundo
consentimiento del LLM ni nueva autorización de otro ensayo.

La operación es un único coordinador separado de stdio MCP: stdin DEVNULL,
stdout/stderr coordinator.log, nueva sesión, close_fds; identidad con PID/start_ticks/
boot_id y token de lanzamiento de un uso. Ejecuta inline, en serie, el worker
existente para dos jobs persistidos con sus propias claves, inputs y worker.log.
No duplica workflow, análisis, executor, mapper o recuperación. Los hijos comparten
PID del coordinador; worker_alive=true de un hijo finalizado no significa que
continúe volando. Job/informe/reservas determinan la transición.

Se mantiene el mutex OS global por ejecución hija. Su authority se vincula además,
sólo para hijos de secuencia, al hash y a una única llamada al executor: se consume
antes de llamar, se rechaza otro contenido, se revoca al salir y no permite emitir
órdenes desde ese ámbito después del retorno del executor. No se hereda una
autoridad de vuelo de la operación ni se puede reutilizar un Context copiado.
El comportamiento de las entradas individuales permanece y la demo paralela
continúa bloqueada. No se cambia gate, tolerancias, AP_DDS, geometría o LAND.

### Admisión, estados y continuación

Nuevas herramientas registradas start_preflight_sequence y get_preflight_sequence.
La primera recibe exactamente dos mission_paths ordenados, request_key y declaración
no vacía authorization_statement. Exige una misión drone_01/v1 y otra drone_02/v2,
en cualquiera de los dos órdenes. Archivos regulares acotados dentro de missions/,
sin escapes/FIFO o IDs desconocidos. La atribución del consentimiento se registra
como declaración del agente, no como autenticación de diálogo.

Antes de separar el proceso se persisten plan/hash, snapshots exactos de ambas
misiones, orden, consentimiento declarado y vínculos/IDs/claves de los hijos en el
almacén de jobs existente. Se extrae únicamente su escritura de admisión común,
sin refactorizar la lógica de vuelo. Misma clave y hashes/declaración recuperan
EXISTING, otra solicitud REQUEST_CONFLICT, sin spawn adicional. Si un duplicado ya
no puede leer sus fuentes, request_comparison=UNAVAILABLE expresa esa incertidumbre;
no repite trabajo. ACCEPTED/STARTING no significan validación o PASSED.

El coordinador valida ambas misiones y compatibilidad antes del primer hijo. Si
alguna no pasa, resultado global BLOCKED y ambas NOT_STARTED (jobs QUEUED, sin
informe de vuelo inventado). Cada hijo conserva la validación/readiness del workflow
y gate interno justo antes de las órdenes. No hay arranque/reinicio de simulación.
Después del primero se exige worker retornado, job FINISHED, informe íntegro
persistido y hash/identidad correctos, análisis estricto recalculado idéntico,
PASSED, LANDED/desarmado confirmado y liberación coherente de reserva hija con la
reserva exterior aún presente. Se comprueba de nuevo ese informe antes del segundo
y ambos antes del PASSED global. Un FAILED recuperado con LAND puede cerrar FAILED
y liberar normalmente tras prueba positiva; nunca inicia el segundo por ese hecho.

Estados de operación ADMITTED/STARTING/RUNNING/FINALIZING; FINISHED con PASSED,
FAILED, BLOCKED o ERROR cuando el cierre es conocido. Hijo NOT_STARTED se distingue
de STARTING/RUNNING/VERIFYING, FINISHED y UNCONFIRMED; observed_result_status no
equivale a aceptación por el coordinador. Ante identidad/archivo incoherente, worker
perdido, despacho ambiguo o falta de evidencia, queda UNCONFIRMED, resultado global
null y restricciones conservadas. No se reanuda al reconectar/reiniciar ni se supone
aterrizaje por muerte del proceso. Un hijo QUEUED con informe previo es contradicción,
no una invitación a sobrescribir/repetirlo.

Consulta por UUID canónico o clave (exactamente uno), sin rutas arbitrarias, lecturas
con raíces fijas y verificación de integridad. Summary muestra vínculos, hashes,
estado, motivos, consentimiento e incertidumbres/reservas; detail añade informes
existentes. No crea archivos, workers, vuelos o libera restricciones. Los contratos
anteriores siguen; las vistas de hijos conservan sequence_id/sequence_index. Informes
históricos y evidencias operativas de v1/v2 no se migran ni reescriben.

### Tests y límites

40 casos nuevos offline en tests/test_preflight_sequences.py: ambos órdenes, doble
prevalidación, segundo inválido/acción no soportada, readiness por hijo, FAILED con
recuperación sin segundo, landing incompleto, identidad/hash/análisis/job corruptos,
worker perdido, hueco entre hijos ocupado por guard, entradas sync/async concurrentes,
duplicados, conflictos, recarga sin efectos, pérdida entre hijos, tokens/autoridad
no reutilizables y ligados al snapshot, rutas/FIFO/IDs inválidos, consultas en vuelo,
registro/esquemas MCP y paso real por wrappers summary/detail. Se usa también el
executor y su gate reales con control/telemetría doblados para ambos vehículos.

Resultados reales: primera suite intermedia 413 passed in 11.80s (25 casos nuevos);
tras ampliar contratos de integridad/autoridad, grupo final
.venv/bin/python -m pytest -q tests/test_preflight_sequences.py tests/test_virtual_preflight_jobs.py tests/test_vehicle_execution_lock.py tests/test_simulated_vehicle_selection.py tests/test_hermes_mcp_server.py
→ **139 passed in 6.65s**. Suite completa .venv/bin/python -m pytest -q
→ **428 passed in 12.91s**. Son pruebas deterministas con dobles, no vuelos ni
evaluación de obediencia del LLM. No se repiten después de documentación solamente.

Guía nueva docs/sequential-preflight.md y enlace desde async-virtual-preflight.md:
activación mediante catálogo MCP recargado, contratos, estados, almacenamiento,
límites y prompts de una línea. No se cambia configuración personal ni skill.
La carga efectiva de instrucciones en Hermes queda por comprobar conversacionalmente.

Control cooperativo entre entradas actualizadas: ROS/QGC manual y servidores viejos
que ignoren sequence.json quedan fuera. No desplegar con workers antiguos activos.
Lifecycle no comparte interlock atómico con vuelo; no reiniciar GUI con reserva o
incertidumbre. No hay watchdog que aterrice al perder coordinador, resistencia
demostrada a reinicio host/corte eléctrico ni solución total de TOCTOU/autenticidad.
No se demuestra inmovilidad del otro dron, coordinación simultánea, separación,
agricultura, velocidad seguida, carga del .plan o hardware. Prueba operativa de la
pareja pendiente; PASSED individuales anteriores no validan esta orquestación.
Sin commit ni push.

Cierre: inventario inicial de 360 archivos; los 212 de runtime/evidencias anteriores
conservan SHA-256, sin nuevos trabajos reales. El prefijo completo anterior de este
registro permanece intacto. Siete archivos existentes modificados y cuatro nuevos
(dos módulos de secuencia, tests y guía). git diff --check limpio y cuatro nuevos
comprobados individualmente sin errores de whitespace. Registro SDK: 19 herramientas;
los esquemas de entrada de las 17 anteriores mantienen SHA-256
a7102e858c349855ed8143cdbf3359976950f2cbe08cd99f9a2d20b52404d980.
Sin cambios posteriores de código ni repetición innecesaria de tests tras documentación.

## 18/10/2026 — Diagnóstico de la primera pareja SITL incompleta

Secuencia c6eeb645-17d2-4081-9afb-cecfd23af393, clave joel-secuencia-sitl-01. El
operador aporta transcripción y autoriza inspección Docker/telemetría/logs estrictamente
de lectura con timeout, sin modo/armado/despegue/navegación/LAND, parada/reinicio,
workers/ensayos, liberaciones o reanudación. Comunica además GUI negra repetida y
recuperaciones irregulares tras reinicios previos; no confirma visualmente suelo/aire.
No se presupone causa común con ROS2. AGENTS.md no presente en repositorio/ancestros
inspeccionados. Se mantiene feature/hermes-integration sobre 7b6e349 con todos los
cambios pendientes anteriores; no se implementa ninguna corrección funcional.

### Preservación previa e identidad

Antes de inspeccionar el contenedor se conservan 32 copias locales exactas con
manifest_local_initial.json en
simulation/ros2_gazebo/results/sequential_preflight_diagnostic_2026_10_18/c6eeb645-17d2-4081-9afb-cecfd23af393:
plan/op/snapshots, ambos jobs e informes/logs, reservas e índices, fuentes relevantes,
adjunto bruto y misión/informe PASSED anterior de v2. Baseline de 384 archivos del
árbol/runtime/evidencias para comprobar que no se alteran originales. Las capturas
posteriores Docker/ROS se separan del material inicial y conservan recepción UTC,
límites, retornos, fuente y hashes. Los logs vivos pueden crecer durante su lectura;
el hash identifica los bytes capturados, no una congelación atómica del contenedor.

El plan SHA-256 49340c69cb0466ee832d273c6003cc0e03f02b733a0336641b926ce6a3f4c436
coincide con op y reserva exterior. Snapshots parentales, inputs, misiones hijas y
hashes esperados de job/report coinciden. Vehículos correctos en cada vínculo.
v1 467f7ec6-b2a6-4b68-9d97-766d85732f8e: informe PASSED, executor COMPLETED, tres WP,
regreso y LANDED con landed=true/armed=false/flying=false, análisis estricto
recalculado idéntico (once checks true). Su hash de informe coincide con el retenido
por la operación. v2 1b69dfc7-0707-4b68-a009-062610418fe4: job FINISHED, report ERROR
en execute con retorno 124 y output vacío; executor_result=null, analysis=null.
Su estado aceptado por coordinador es UNCONFIRMED/result_status=null, aunque el
informe observado diga ERROR. La operación queda UNCONFIRMED/result_status=null;
next_index=2 significa dos despachos consumidos, completed_count=1 sólo un hijo
verificado completo. Reservas v2.json y sequence.json siguen UNCONFIRMED, intactas.

El PASSED individual anterior v2 7162bce5-3635-4a76-bf02-6a5a22612aab se vuelve a
verificar sin cambios; tiene el mismo hash de misión ce94effedb4c977b0db3c64e41d4a2b86bba9a78c494cfeda4305d069d54bebb,
sin resolver ni aprobar retrospectivamente este intento. Intervalos reales de
executor: v1 235.144404 s, v2 18.574868 s; worker v2 26.914309 s. El started_at del
report v2 incluye la cola, no sólo su worker. Ningún intervalo se llama tiempo en vuelo.

### Telemetría autorizada y actualidad

El primer acceso Docker sin elevación se deniega por permisos del socket; las
lecturas posteriores se realizan con aprobación. Contenedor running, no paused ni
restarting. Se usan suscripciones de lectura best_effort/volatile, sin cambiar QoS
de publishers/configuración, más lectores CLI exactos del executor. Sólo se crean
observadores/logs ROS inherentes a la consulta, sin órdenes a los vehículos. Ventanas
de hasta 22 s incluyendo arranque del proceso; otras lecturas limitadas a 8–25 s.

Dos ventanas guardadas, a las 23:38 y 23:42 Europe/Madrid (UTC+02:00). En la última,
v1 status recibido 23:42:56.473818, armed=false/flying=false/mode=9; v2 a
23:42:57.735763, armed=false/flying=false/mode=0. Tres muestras de status/posición
por vehículo en cada ventana, con stamps crecientes. Geopose estable: ambos lat
-35.36326217651367, v1 lon 149.1652069091797, v2 lon 149.16526794433594, ambos
584.1900024414062 m AMSL, al nivel registrado de salida en v1 y en el ensayo individual
previo de v2; el hijo v2 fallido no conserva launch_position. Es evidencia de telemetría
entrante durante esas ventanas y consistente con desarmados/no volando/en nivel
de salida; no es contacto con el suelo observado independientemente, imagen
confirmada o garantía de estado posterior. No se reconcilia/libera por ello.

Clocks AP y Gazebo observados por separado, con distintos orígenes; en la ventana
final el sello status avanza aproximadamente 0.16 s por segundo de recepción.
No restar el reloj PC al sello simulado para declarar edad. Cada dato conserva
header y momento de recepción. /ap/v1/clock y /ap/v2/clock tienen un publisher
observado cada uno; los bridges actuales publican /drone1/clock y /drone2/clock,
también uno cada uno. No se demuestra duplicación de publicadores sobre /clock
global; la suscripción diagnóstica inicial no descubrió publisher de ese tópico.

Lectores exactos de origen v2, geopose v2 y origen v1 devuelven 0 durante seguimiento
(6.74, 2.55 y 6.74 s), sin reproducir el 124. El proceso coordinador 133909 mantiene
start_ticks=8003617 y boot_id registrados, pero está Z (zombi, terminado/no recogido).
No se mata/recoge ni se equipara su fin con aterrizaje. Lectura guardada de /proc,
sin ejecutar una consulta MCP operativa, gate/readiness con prearm o control alguno.

### Límite de captura del executor

En las fuentes conservadas, get_vehicle_global_origin y get_vehicle_geopose están
fuera del try principal y antes de GUIDED/ARM/eventos. Sus lectores llevan timeout
10 ros2 topic echo --once; el helper FlightControlError conserva retorno/output
pero no comando/topic/etapa. progress=False elimina los mensajes de etapa. Al
fallar una de esas lecturas, el error sale sin devolver el contexto parcial, el
graph lo convierte en ERROR/null y omite análisis. execution_attempted=true acredita
intención/entrada al executor, no prueba de armado o vuelo. El código actual acota
dos lecturas candidatas; faltan datos para elegir cuál o asegurar la versión cargada
en aquel proceso. El 124 no demuestra causa raíz, QoS, congelación o interferencia.

Tres probes offline con mocks y temporales verifican el límite real: ambos errores
de lectura inicial propagan ERROR/null, mientras que el mismo error de modo dentro
del try produce FAILED estructurado. No hay órdenes reales; resultados en
offline_exception_probes.json. La versión instalada de ros2topic echo usa sensor_data
y adaptación a publishers; no se demuestra desajuste QoS ni se altera. Es diagnóstico,
no una corrección funcional del problema de observabilidad.

### GUI y servidor: evidencias distintas

Arranque actual 21:12:11 UTC: supervisor ROS2 46687, un servidor Gazebo, una GUI y
dos ArduCopter observados vivos. /tmp/tfg_demo.log se identifica con ese supervisor;
se conservan launch.log y server_console.log de ese arranque, aparte de auto_default.log
GUI y ogre2.log. No se usa /tmp/tfg_2drones.log histórico. Variables gráficas sólo
seleccionadas, sin leer credenciales ni volcar el entorno completo: DISPLAY=:0,
QT_QPA_PLATFORM=xcb; GUI engine ogre2. Log OGRE: GL 4.1/Mesa 23.2.1, vendor Microsoft,
renderer D3D12 (Intel UHD Graphics); no se confunde la exploración EGL software
con el renderer declarado. /dev/dxg, biblioteca WSL d3d12 y X0 presentes.

GUI: errores URI package://ardupilot_gazebo y geometrías iris/gimbal no resueltas,
aunque las mallas consultadas existen instaladas. Se registra pista de recursos,
sin atribuir toda la pantalla negra a esa causa. No aparece cierre con exit 139 ni
process has died en el main log capturado de este arranque; no se importa la causa
del crash OGRE antiguo. Servidor/SITL: avisos controller reset y No JSON sensor
message en sus contextos, sin demostrar relación causal con el fallo ROS2 o GUI.
Capturas adicionales de launch_params históricos quedan identificadas como tales;
sólo los dos YAML referidos por argumentos de bridges activos se consideran actuales.

### Recuperación propuesta y comprobaciones

Se entrega como secuencia INCOMPLETA, sin PASSED global. Opciones no ejecutadas:
mantener restricciones y sólo actualizar lecturas; autorizar por separado una futura
reconciliación revisable con telemetría fresca, identidad, hashes y propiedad de
reservas, preservando ERROR/historia; después de reconciliación segura y permiso
específico, investigar recursos/renderizado o preparar recuperación GUI independiente.
No reiniciar, repetir hijos, reanudar o borrar reservas para salir de este estado.
No se implementa reconciliación, parche de executor, QoS o renderizado.

Se actualiza la guía secuencial con el intento incompleto y vínculo al diagnóstico.
Tres probes offline pasados y verificaciones reales de hashes/identidad/reanálisis;
no se ejecuta una suite nueva por documentación/evidencias solamente. Los 428 tests
anteriores siguen como resultado histórico, no prueba de que este fallo esté resuelto.
Las comprobaciones de whitespace distinguen texto bruto con CRLF/ANSI/espacios de
documentos derivados; nunca se normalizan originales para ocultar avisos. Sin commit
ni push, sin acciones operativas adicionales de control.

Cierre de conservación: baseline 384 archivos; sólo cambian este registro y la guía
secuencial, con prefijo histórico del registro conservado. Los otros 382, incluidos
232 de runtime/evidencias anteriores y todos los registros de reserva, mantienen
SHA-256. Las 32 copias locales iniciales siguen idénticas a originales. Se añade
manifest_final.json con inventario/hash de las 320 piezas capturadas/derivadas
(321 archivos contando ese manifiesto), diferenciando originales locales, fuentes
del contenedor, capturas temporales y análisis. git diff --check versionado limpio;
siete piezas brutas/fuentes conservan avisos de whitespace, sin normalizarlas.
README, assessment y resultados de probes derivados están limpios. No se ejecuta
ninguna acción de recuperación ni prueba operativa adicional.


## 2026-10-19 — Cierre offline de los pasos 3–11: diagnóstico, reconciliación y lifecycle

Se parte de feature/hermes-integration y del árbol sucio existente, incluyendo
secuencia persistente, diagnósticos/evidencias del 18/10 y guion de reunión. No se
encuentra AGENTS.md aplicable en el checkout ni sus ancestros/subdirectorios revisados.
Se conserva todo el trabajo anterior. Sin Docker/ROS/LLM/MCP operativo, vuelo,
reconciliación real, liberación de reservas, staging, commit, push o cambio de rama.

### Implementación y garantías comprobables offline

- Origen global/geopose inicial entran en el manejo de errores del executor: futuro
  fallo produce resultado explicativo con contexto parcial y análisis/informe,
  sin inventar posición ni ordenar LAND antes de cualquier control. No identifica
  retrospectivamente cuál lectura falló ni la causa del 124 del 18/10.
- Diagnóstico por vehículo lógico/interfaz, etapa, endpoint/operación, UTC/duración
  monotónica de pared, timeout, retorno y error/cadena original. Primeras 16 y últimas
  96 operaciones; controles diferencian intento y confirmación. ARM se considera
  posiblemente efectivo antes de la llamada: un timeout conserva recuperación LAND.
  Se mantienen gate, hashes, geometría, tolerancias, AP_DDS, QoS y plazos del executor.
- Inspect/apply/get de reconciliación: versiones de archivos, identidades PID/start/
  boot, mutex libre, nueva ventana de status/geopose de ambos vehículos, TTL de 120 s
  monotónicos en el mismo boot y revalidación bajo exclusión. No inferir edad absoluta
  de mensajes comparando clocks simulados con pared; headers crecientes no la prueban.
- La fuente independiente de suelo admitida es OPERATOR_VISUAL: declaración reciente
  por ambos modelos identificados y apoyados en la pista, con hora y statement.
  No se acepta sólo armed=false/flying=false. Si la GUI sigue negra sin otra vista
  actual, aplicar queda BLOCKED; no hay sensor de contacto añadido ni force-unlock.
  Esta limitación operativa se documenta, sin fingir que queda resuelta.
- Historial exacto de reservas, autorización y transición; barrera duradera antes
  de retirarlas, sin tocar ERROR/PASSED/jobs ni reanudar. Repetición exacta idempotente;
  auditoría consultable sin nueva telemetría. Una transacción interrumpida queda
  bloqueada, no se continúa automáticamente. Job/identidad faltante no se reconstruye.
- Lifecycle usa el mismo orden mutex global→registro y mantiene exclusión durante
  start/stop/restart, incluidos MCP/Python/scripts y backend con lease heredado.
  Aunque falte una reserva, un mutex de executor todavía tomado impide lifecycle.
  Timeout/crash deja restricción durable y logs separados de stdio MCP. Restart es
  una sola transacción stop/start; no hay intercalado entre hijos de secuencia.
- GUI/headless reutiliza el argumento existente; se elimina gui=true hardcodeado
  en el supervisor y se aclara su descripción. No se parchea OGRE ni se atribuye
  GUI negra a 124. Logs de GUI/render, servidor y ROS se interpretan por separado.
- Plan nuevo versionable de v1→v2 con paths/hashes y clave no usada al prepararlo,
  joel-secuencia-sitl-20261019-r02; authorization_statement=null. No se admite ni
  se reanuda la secuencia fallida. Readiness/gate actuales se mantienen por hijo.

La secuencia c6eeb645-17d2-4081-9afb-cecfd23af393 continúa incompleta: v1 PASSED,
v2 ERROR/null/null; sequence.json y v2.json siguen UNCONFIRMED y byte-idénticos a
las copias preservadas. Las observaciones armed=false/flying=false del 18/10 son
históricas. Se distinguen worker terminado y vehículo aterrizado.

### Demo aportada y material para observabilidad futura

El TXT Texto pegado(20261019-153307).txt no estaba accesible. El operador pegó el
contenido en este chat; se conserva ese string UTF-8 literal, no se afirma copia
byte-a-byte de un TXT no disponible. 74834 bytes, hash
7e361bcc9074274650f0e45ad9d9accd7a3b9cb98fadb4dc91ece1acf81af0eb.
Se guardan además siete copias exactas del borrador 7f2e3345-a62e-4060-a0c0-9b034714b49e
y finalización 17764ef0-5114-4447-87d5-de6f00455bf3. Originales intactos.
Geometría verificada 40×20 m/90°/horario/HOME central/8 m/cierre/regreso; validación
FEASIBLE/APPROVED, .plan con [22,16,16,16,16,16,20], flight_consent=NOT_GRANTED.

El texto empieza a mitad de interacción y faltan argumentos/resultados completos:
se observan errores JSON/clarify, razonamiento repetido, valores persistidos sin
confirmación visible suficiente (consumo 1.5, viento desde norte, objetivo custom),
UUID mal copiado y afirmación equivocada de exportación ausente, luego rectificada;
el resumen mezcla LAND y retorno. No se reconstruye el inicio ni se prueba ausencia
global de llamadas. Bytes/longitud/indicador de UI no son tokens facturados.
No se integra LangSmith/Opik ni se refactoriza fidelidad de Hermes ni otro LLM.

### Comprobaciones reales y alcance pendiente

Selección ampliada: 248 passed in 9.97s. Suite completa final: 477 passed in 15.65s.
Sintaxis: 23 Python, 5 scripts con bash -n y observador embebido correctos. Primera
suite verificable: 457 passed y 2 failed in 14.98s, por tests de scripts que usaban
el checkout real y quedaron bloqueados antes del Docker falso. Se corrigió el
entorno de tests a un proyecto temporal que ejercita wrappers/backend reales y
preserva la comprobación de abortar al fallar cleanup. Un test nuevo de job ausente
también reveló un defecto y quedó corregido. Los 428 anteriores son resultado
histórico; no se inventa una comparación de baseline no registrada.

Tests de carreras con Events/mutex y dobles: lifecycle/admisión, mutex sin registro,
intervalo entre hijos, primer hijo fallido/incierto, PID reciclado/worker perdido,
evidencia ausente/caducada, cambios durante inspección/aplicación, interrupción,
repetición y consulta de auditoría sin efectos. Esquemas y dispatch SDK MCP probados
sin llamadas operativas. No hay tests de frases para asegurar obediencia del LLM.

git diff --check tracked y nuevos de código/documentación limpios. Nueve piezas de
evidencia bruta/fuentes conservan avisos de whitespace: siete del archivo diagnóstico
anterior, el texto recién pegado y el primer log pytest fallido. Se informan y preservan sus bytes/hashes.
Se verifican manifiestos históricos, incluidas las 37 copias del archivo conversacional,
y los originales runtime seleccionados; resultados en roadmap_offline_2026_10_19.

Tabla por paso, estados IMPLEMENTADO_OFFLINE/PENDIENTE_OPERATIVO, límites, propuesta
de commits en inglés y guía concreta con prompts en docs/roadmap-3-11-offline.md y
docs/reconciliation-and-lifecycle.md. Los pasos 6, 8 y 9 siguen pendientes operativos;
ningún ensayo ni recuperación real se declara completado. Primer paso de Joel:
inspección de sólo lectura; autorizaciones separadas para aplicar, recuperar GUI y
ensayar después. Sin fuente visual actual suficiente, la reconciliación no es
operativamente aplicable en esta versión y se mantienen restricciones.


## 2026-10-19 — Inspección BLOCKED con SITL detenido y cierre administrativo offline

### Evidencia operativa aportada y contraste local

El operador comunica la primera inspección de la secuencia
`c6eeb645-17d2-4081-9afb-cecfd23af393`: `1a977374-4df9-42a6-9409-d0e0c3a991e2`,
SHA-256 `ce2fc0ec49d29a617f81a8236329308c80bf4b91c19dd7ac6f24525765db61b8`.
Se leyó el JSON local y se conservó copia exacta (452 bytes) con ruta original y
hash. Registra BLOCKED, error del colector porque el contenedor completo
`0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f` no se ejecutaba,
`reservations_changed=false`; no hay telemetría, captura de propietarios/versiones
ni aplicación. El archivo original no se modificó. El error no prueba por sí solo
terminación, aterrizaje ni causa del 124. No se consultó el contenedor en este trabajo.

### Implementación offline y criterios

Se incorpora lectura acotada de metadatos Docker seleccionados, sin exec ni lectura
de credenciales/configuración personal: identidad de motor, resolución exacta de
nombre, inspect por ID completo, imagen/creación/estado/inicio/fin y comprobación
final de nombre y motor. Máximo cinco llamadas de sólo lectura, timeout de 3 s cada
una. Distingue DOCKER_UNAVAILABLE, CONTAINER_ABSENT, UNKNOWN, ACTIVE y STOPPED;
la valoración de referencia añade REPLACED_OR_RESTARTED. Retornos, errores,
campos desconocidos y contexto parcial se conservan. Sólo ACTIVE intenta ROS.

La inspección conservada aporta una referencia débil de identidad, no evidencia
suficiente de terminación: ID completo del contenedor al que Docker dirigió la
inspección del mismo propietario. No conocemos su motor/incarnación históricos;
se declara `historical_engine_identity_known=false`. Sólo se admite combinada con
metadatos nuevos concordantes de ese ID/nombre y terminación verificable, más
propietarios/versiones y procesos consistentes. Las futuras auditorías ACTIVE
conservan una referencia completa de motor/contenedor/imagen/creación/inicio y
reservas. No se reciben rutas/IDs de contenedor arbitrarios; referencias
contradictorias, enlaces externos y IDs de inspección incoherentes bloquean.
Una mera inspección STOPPED sin vínculo previo no se convierte en su propia prueba
repitiéndola. Sin vínculo suficiente se conserva BLOCKED y se identifica lo faltante.

La vía ENVIRONMENT_TERMINATED exige contenedor exacto `exited`, Running=false,
Pid=0, sin paused/restarting/dead y tiempos Docker válidos Created <= StartedAt <
FinishedAt. No son tiempos ROS ni se restan del reloj de pared del host para fingir
edad de generación. Un contenedor exacto ahora detenido termina sus encarnaciones
anteriores: no se exige telemetría imposible del entorno ya terminado. La identidad
actual, estado e inicio/fin se congelan para revalidarlos al aplicar.

Devuelve AWAITING_TERMINATION_RECONCILIATION_AUTHORIZATION, inspection_id/hash,
base/aplicabilidad y datos pendientes, sin cambiar restricciones. Aplicar exige
ese hash y autorización explícita separada de cierre administrativo; se omiten
confirmaciones de suelo que no aplican. El parámetro MCP de confirmaciones pasa a
opcional para ese caso, con contrato anterior activo conservado: nueva telemetría
de ambas interfaces y declaraciones visuales OPERATOR_VISUAL posteriores a inspección.
GUI negra bloquea la vía activa sin fuente visual, no obliga a arrancar un entorno
detenido para demostrar que el anterior terminó. No se promete reparar GUI.

Bajo los mutex global de ejecución/registro se revalidan procesos mediante
PID/start_ticks/boot, propietarios/versiones/hashes, referencia y nuevos metadatos.
Coordinador/workers/ejecutores deben estar ausentes y el mutex global libre;
un PID reciclado también bloquea. Se mantienen TTL 120 s/mismo boot, barrera durable,
archivo exacto/fsync, idempotencia y retención ante interrupción. No se debilita
exclusión de admisión/lifecycle/ejecución ni se crean autorizaciones heredadas.
APPLIED administrativo registra ADMINISTRATIVE_CLOSURE_ENVIRONMENT_TERMINATED y
NOT_ASSERTED para suelo: no significa aterrizaje ni PASSED; operación, jobs e informes
ERROR/UNCONFIRMED/PASSED históricos no se editan ni reanudan. No hay force-unlock.
Los clientes externos/checkout antiguo no participan en esta exclusión.

La inspección nueva retiene contexto conocido aunque falle colector/sonda. Consulta
histórica del BLOCKED original comprobada offline: NOT_COLLECTED,
evidence_expired=null, remaining_seconds=null, application=null; no se presenta
evidencia nunca obtenida como caducada. Metadatos parciales tienen su propio estado
de recogida y desconocidos; no se inventan observaciones.

### Comprobaciones reales y siguiente acción

Selección final: **97 passed in 5.59s**. Suite completa: **532 passed in 19.64s**.
Sintaxis: **27 Python**, **5 scripts bash -n**, observador embebido compilado.
Diff versionado sin avisos; nuevos de código/docs limpios. Nueve piezas brutas
anteriores mantienen avisos de whitespace, sin normalizar. **472 archivos previos**
y runtime seleccionados mantienen hashes, incluidas las reservas reales. La copia
nueva del BLOCKED coincide con el SHA-256 comunicado y su original.

Durante la edición hubo un error de sintaxis nuevo (paréntesis faltante), detectado
durante la colección y corregido antes de las ejecuciones verdes; las dos primeras invocaciones terminaron con
2 y 4 errores de colección del mismo defecto. No se atribuye al árbol previo.
Después se registran tandas verdes de 76, 93, 94, 96 y 97 afectados y una suite
intermedia de 528; los resultados finales son los indicados arriba y sus logs
exactos están conservados. No se inventan logs brutos de las dos invocaciones que
sólo se observaron en la salida de herramientas.

Código/docs y manifiesto en `docs/stopped-sitl-reconciliation.md` y
`simulation/ros2_gazebo/results/stopped_sitl_reconciliation_2026_10_19/`.
Se actualizan enlaces de las guías conservando las conclusiones anteriores como
historia del cierre previo. Este incremento implementa la vía administrativa
**offline**; aplicación real, recuperación GUI y nueva secuencia siguen pendientes
y requieren decisiones/autorizaciones separadas. La siguiente prueba es sólo
inspección de c6eeb645 con metadatos actuales: no se aplica ni libera nada en este
trabajo. Sin Docker/ROS/MCP operativo, simulación, vuelo, proveedor LLM, commit/push.


## 2026-10-19 — Revisión crítica del vínculo legacy de ad234044

### Lectura offline, conservación y conclusión

Se revisó el JSON persistido de la inspección
`ad234044-4e5d-4785-b8c4-43f05b89a54a` de la secuencia c6eeb645:
53 756 bytes, SHA-256
`60a17c81680ea58864cd98c92f3d1102acfc8907d9d7ad89393f7d04b0eab844`.
Copia exacta, referencia previa 1a977374 y código anterior conservados bajo
`simulation/ros2_gazebo/results/legacy_binding_review_2026_10_19/`.
No se encontró otro JSON adjunto independiente accesible; se contrastaron el archivo
local y los datos comunicados. Snapshot.files coincide en hashes y bytes con los
originales presentes. Consulta local, no MCP operativo: EXPIRED,
application_eligible=false, application=null. No se intentó aplicar la inspección.

Había una laguna real. La referencia LEGACY_FAILED_INSPECTION_CONTAINER_ID sólo
vinculaba el ID completo del contenedor consultado por una inspección posterior
al fallo. `_environment_reasons` comparaba ese único campo y exigía estado detenido
actual; `_process_reasons` y capture verificaban procesos y archivos locales, no
el endpoint Docker original. El flag historical_engine_identity_known=false no
se traducía en revisión o restricción adicional. Por eso no había razones técnicas
de bloqueo y se devolvía ENVIRONMENT_TERMINATED elegible para autorización genérica.
Un cambio de contexto A→B posterior al vuelo podía producir una referencia de B
coincidente con su inspect, sin demostrar terminación de A; incluso un B creado
después del ensayo no quedaba rechazado por cronología. No es una colisión de IDs.

Los datos reales son compatibles: contenedor creado el 2/10, StartedAt 16/10,
secuencia 18/10 y FinishedAt 19/10 18:01:24 UTC. El diagnóstico de sólo lectura del
18/10 registra exactamente el mismo StartedAt, pero sin ID completo ni engine_id.
Es corroboración bajo continuidad/rutina de relojes, no autenticación del vínculo.
ExitCode=255 no explica 124 ni GUI, y no se infiere ausencia de vuelo del segundo.
PASSED del primer hijo, ERROR del segundo, operación y reservas UNCONFIRMED intactos.

### Corrección y límites explícitos

Se añade binding_review: recoge fuentes/hashes y tiempos de inicio de jobs/report,
metadatos y fecha de referencia; detecta ausencia/fechas inválidas, creación posterior
a la actividad original, salida anterior al inicio y referencia anterior a los
intentos registrados. La comparación es condicional a una base de relojes UTC de
pared comparables; no ROS ni edad absoluta de simulación. Un ERROR puede escribirse
tras salir el contenedor; no se exige que el contenedor viva hasta terminar el informe.

Sin contradicciones, devuelve AWAITING_LEGACY_ENVIRONMENT_REVIEW,
application_eligible=false, original_execution_environment_bound=false y supuestos
pendientes. ENVIRONMENT_TERMINATED describe lo observado físicamente, no prueba el
endpoint original. Una referencia ACTIVE_ENVIRONMENT_AUDIT posterior conoce el
motor en esa auditoría y tampoco evita la revisión; no se presenta su campo histórico
compatible como identidad del motor durante el vuelo original.

La aplicación existente exige además legacy_environment_confirmation tipada:
source=OPERATOR_ENVIRONMENT_REVIEW, IDs de motor/contenedor coincidentes,
continuous_project_environment=true, wall_clock_comparison_supported=true y statement
con base real. La continuidad incluye selector/despliegue, ausencia conocida de
sustituciones/clones/restauraciones y ausencia de traslado a otro host con workers
anteriores potencialmente activos. Se valida bajo exclusión con la cronología y
las comprobaciones anteriores, ligada a ID/hash y autorización de la solicitud.
Sin declaración explícita, contradicción o caducidad no se aplica. La consulta de
auditoría expone la declaración y que el vínculo técnico original sigue sin registrarse.
Aplicaciones previas ya persistidas se conservan y su replay no repite transiciones.

No se pide inventar IDs históricos ni una prueba de suelo imposible. El procedimiento
legacy viable es revisar con Joel su continuidad de instalación/contexto/WSL y
registros/comandos, y la base de relojes disponible; si puede sostenerlo, se registra
como declaración administrativa vía agente. Si no puede, conservar restricciones
y revisar los endpoints/hosts originales de sólo lectura con autorización separada;
esta versión no implementa descarte de múltiples entornos desconocidos ni force-unlock.
El esquema no prueba verdad de la declaración ni fidelidad semántica de Hermes.

Se distingue boot_id del host del worker (cbb1fa33 en el intento, f4b6327f en la
inspección), identidad actual del motor Docker (2c4ad774) y StartedAt del contenedor.
/proc sólo inspecciona el host/namespace local; no demuestra ausencia en otro host
si se trasladó el workspace. Boot distinto no acredita un reinicio de Docker; ID
motor tampoco es contador de reinicios. No hay identidad del motor original guardada.

Guía actual: `docs/legacy-environment-binding-review.md`; se añade aviso en la guía
anterior conservando su historia. Próximo paso: revisión de continuidad/relojes y
nueva inspección de sólo lectura, sin aplicar ad234044 ni liberar restricciones.
No Docker/ROS real, operaciones MCP, arranque, simulación, vuelo, reconciliación,
liberación, commit ni push en este trabajo.

### Verificación offline de esta revisión

Tests afectados finales: **114 passed in 6.04s**. Suite completa final:
**549 passed in 21.36s**. Sintaxis: **28 archivos Python**, **5 Bash** y observador
Python embebido. `git diff --check` sin avisos; código/docs nuevos limpios. Nueve
piezas brutas anteriores mantienen avisos de whitespace y no se normalizan.
**502 archivos previos** conservan hashes, incluidas inspecciones, reservas,
PASSED/ERROR y archivos de evidencia anteriores. La aplicación real de ad234044
sigue ausente. Regresiones: cambio de contexto/creación posterior, cronología
incompleta/contradictoria, revisión ausente/incoherente, boot de host distinto sin
prueba de motor, referencia ACTIVE posterior, ERROR registrado tras la salida,
caducidad, reserva e informes intactos, esquema/dispatch MCP y auditoría de la
atribución administrativa no autenticada. También se mantienen las carreras de
admisión/lifecycle con barreras. No se ejecutó LLM ni se probó obediencia por frases.
Logs/manifiesto en `simulation/ros2_gazebo/results/legacy_binding_review_2026_10_19/`.


## 2026-10-19 — Joel aporta contexto actual; continuidad histórica no confirmable

Joel aporta comprobaciones de lectura a las 21:36:28 CEST / 19:36:28 UTC: MSI,
Ubuntu 24.04.4, contexto default con unix:///var/run/docker.sock, sin salida de
DOCKER_HOST/DOCKER_CONTEXT, engine 2c4ad774 y container 0274e4fd completos. La comparación
offline confirma coincidencia exacta con ad234044 en IDs, nombre, creación, imagen
y State (incluidos StartedAt/FinishedAt, exited/Running=false/Pid=0). Se conserva
transcripción del mensaje y manifiesto bajo legacy_evidence_followup_2026_10_19;
no se presenta como un TXT terminal original ni como comandos ejecutados por Codex.

Joel sólo sabe que WSL se cerró y reabrió: no puede sostener continuidad histórica
del contexto ni comparabilidad histórica de relojes. No se le vuelve a pedir que
confirme esos hechos ni se rellena la declaración true por inferencia. El cambio
de boot del host y la hora actual local/UTC no son prueba histórica sobre Docker.

Se revisaron 336 archivos del diagnóstico del 18/10 y originales de secuencia/hijos.
No contienen campos de engine/container ID ni los IDs actuales. El capturador
conservó docker exec por nombre; final_metadata el mismo StartedAt sin esos IDs.
Es corroboración, no vínculo suficiente con el daemon original. No se descarta
que existan logs externos de Docker Desktop/eventos/journal no archivados.
Falta una traza contemporánea que correlacione la ejecución concreta y su endpoint/
contenedor, y una base para relacionar clocks si se usa cronología cruzada. No se
puede fabricar esa evidencia desde otra consulta actual ni activar logging ahora
para reconstruir el pasado.

Decisión: conservar bloqueo técnico. LegacyEnvironmentConfirmation actual exige
los dos true y _confirm_legacy_environment los valida; el caso de hechos desconocidos
ya se rechaza. No se modifica ni relaja código ni se vuelve a generar inspección
operativa. Se preparan cuatro comandos de lectura acotados (eventos del intervalo,
inventario Windows Docker/log, búsqueda de IDs en un archivo realmente listado y
journal histórico de timesyncd), comprobados sólo con bash -n, sin ejecutarlos.
Una respuesta vacía/no retenida no prueba ausencia de vuelo o de sincronización.
La búsqueda tiene cierre: una pasada por fuentes existentes; si no hay vínculo,
registrar no recuperado en esas fuentes y no entrar en bucle de inspecciones MCP.

Alternativa explícita si el vínculo no es recuperable: retiro administrativo no
verificado, sin afirmar hechos desconocidos. Se documenta el protocolo exclusivo
de c6eeb645 y v2/1b69dfc7, con hashes exactos de sus dos reservas y 16 versiones/
ausencias de artefactos en una propuesta JSON de evaluation/operations. Estado:
DOCUMENTED_ONLY_NOT_IMPLEMENTED_NOT_AUTHORIZED_NOT_EXECUTABLE. No es un nuevo modo
de apply_execution_reconciliation ni un force-unlock genérico. Materializarlo
requiere encargo/implementación puntual revisable y autorización explícita del
riesgo administrativo, no una declaración ficticia de continuidad.

La propuesta exige exclusión común, nuevos controles del motor/contenedor actual
fijado detenido, procesos locales/propietarios/versiones sin cambios ni otras
reservas; auditoría y barrera durable antes de archivar exactamente las dos reservas
con fsync, ninguna operación ajena. Auditar como ADMINISTRATIVELY_RETIRED_UNVERIFIED,
no PASSED/reconciliación técnica; mantener secuencia UNCONFIRMED, v1 PASSED y v2 ERROR
y sus evidencias. Reconocer original_environment_termination=UNKNOWN y el límite
frente a posibles entornos/hosts antiguos desconocidos. Sin arranque ni vuelo ni
consentimiento heredado. Una interrupción conserva barrera, sin reanudación automática.

Guía concreta: docs/legacy-administrative-retirement-c6eeb645.md; propuesta:
evaluation/operations/administrative_retirement_c6eeb645_proposal_2026_10_19.json.
Pruebas de política existentes: **16 passed in 1.53s** sobre temporales/dobles.
101 archivos de código funcional y 518 archivos previos seleccionados mantienen
hashes; reservas reales e inspección ad234044 intactas y sin application.json.
No se repite la suite completa porque sólo se añaden documentación/evidencia/propuesta;
549 anteriores son resultado histórico, no nueva ejecución completa de este turno.
Sin Docker/ROS, MCP operativo, controles, inspección operativa, liberación, arranque,
vuelo, commit ni push. El próximo paso es una consulta acotada de eventos históricos;
si no cierra el vínculo, la opción honesta es revisar el retiro administrativo
preparado, sin pedir a Joel certificar lo desconocido.


## 2026-10-19 — Retiro administrativo exclusivo del caso legacy c6eeb645 (offline)

Joel comunica que docker events histórico devolvió salida vacía y código 0. Se
conserva como observación del operador, sin argumentos exactos ni log terminal
original aportados aquí. No se repite ni se infiere ausencia de actividad, vuelo,
eventos retenidos o cambios de endpoint. El vínculo con el entorno original y la
comparabilidad histórica de relojes siguen desconocidos.

Se implementa la propuesta puntual sin relajar apply_execution_reconciliation ni
pedir afirmar continuidad/relojes desconocidos. La propuesta JSON original conserva
bytes y estado documental histórico; tools/legacy_administrative_retirement.py fija
su SHA-256 32eb6f31ae191174136fa6bf054beb5071f4625d2f6fbcff61209d213c76d99a.
Sólo admite sequence.json de c6eeb645 (47385b4e...) y v2.json de 1b69dfc7
(c7bcb0a6...), con 16 versiones/ausencias originales exactas. No acepta políticas,
rutas, propietarios alternativos ni force.

MCP expone prepare_legacy_sequence_retirement, get_legacy_sequence_retirement y
apply_legacy_sequence_retirement. Preparar sólo lee estado operativo y guarda una
auditoría separada. Consultar sólo lee archivos: no recoge observaciones, aplica,
reanuda ni libera. La primera aceptación requiere preparación vigente (120 s
monotónicos, mismo boot), ID/hash revisados y declaración tipada de aceptar la
incertidumbre histórica y el alcance local. Es una declaración vía agente, no
conversación autenticada. Un ID no autoriza la aplicación, ni ésta autoriza GUI,
lifecycle o vuelos posteriores.

Bajo el mutex global de ejecución y registry.lock, sin esperar a workers, se
revalidan propietarios/versiones, procesos originales (PID/start_ticks/boot;
PID reciclado bloquea) y metadatos actuales acotados del engine 2c4ad774 y container
0274e4fd fijados: exited, Running=false, Pid=0, sin paused/restarting/dead. Docker
inaccesible, ausente, sustituido o dudoso bloquea. Se repiten controles tras leer
metadatos y tras archivar; no se compara clock host con el Docker antiguo ni se
arranca para demostrar nada. Boot del host no identifica un reinicio de Docker.

Intención/autorización inmutable y durable, luego barrera común de reconciliación;
ambos originales se publican sin sobrescritura y con fsync antes de retirar v2 y
sequence. Cada paso revalida, registra journal y fsync. Resultado final durable
antes de quitar barrera. Esto conserva exclusión de admisiones v1/v2, secuencias,
ejecuciones y lifecycle incluso entre retiradas y tras una interrupción con barrera
en disco. No cambia gate, executor, tolerancias, workers ni geometría.

La consulta muestra RECOVERY_REQUIRED, barrera, archivos restantes, integridad y
accepted_request con argumentos exactos; nunca reanuda. Sólo una nueva llamada
explícita idéntica puede completar la transacción durable bajo comprobaciones
actuales. La caducidad inicial no invalida ese alcance ya fijado, pero no permite
otro ID, hash, autorización, propietario, proceso o entorno. Sin intención durable
se exige preparación vigente. Replay final no toca restricciones posteriores.
Se re-fsyncan publicaciones interrumpidas de intención y resultado. Resultado
escrito con barrera pendiente sigue requiriendo recuperación explícita. Fallos
expuestos no se convierten en liberación confirmada; no se sobrescribe evidencia
dañada o distinta para repararla.

Resultado separado ADMINISTRATIVELY_RETIRED_UNVERIFIED, conservando secuencia
UNCONFIRMED, v1 PASSED, v2 ERROR, snapshots y hashes. Se registran terminación del
entorno original UNKNOWN, suelo NOT_ASSERTED y flight_authorized=false. No se
afirma nunca-vuelo, aterrizaje, éxito ni terminación original verificada. Alcance
local: no descarta un entorno/host antiguo desconocido ni controla ROS/QGC/Docker
externos, clientes antiguos o ediciones manuales. Recuperabilidad bajo garantías
del filesystem local; daño de evidencia, pérdida del dispositivo o errores
permanentes de persistencia bloquean y requieren revisión.

Resultados reales: **112 passed in 15.31s** en tests afectados finales; suite
completa **601 passed in 44.11s**. Copias exactas del caso en temporales y dobles de
entorno, procesos, colector y lanzamiento. Se prueban esquemas/dispatch MCP reales,
propietarios/versiones cambiados, otros casos, PID reciclado, caducidad, autorización
distinta, consultas tras recarga sin efectos, fallos de publicación/fsync/archivo/
retirada y aplicación repetida. Carreras con barreras/Event, sin sleeps; barrera
durable probada también después de devolver error. No prueba de obediencia del LLM
ni operación real.

Sintaxis sin ejecutar: 30 archivos Python, 5 Bash y observador Python embebido.
git diff --check limpio; código/documentación nuevos limpios. Nueve evidencias
brutas previas conservan avisos históricos de whitespace sin normalizar. **529
archivos previos** conservan hashes y las 16 versiones fijadas coinciden. Reservas
reales intactas, sin preparación/intención/barrera administrativa real nueva.
Logs y manifiesto: simulation/ros2_gazebo/results/administrative_retirement_offline_2026_10_19/.
Guía: docs/administrative-retirement-c6eeb645.md; enlaces desde guías anteriores
conservando historia. Sin Docker/ROS reales, MCP operativo, reconciliación, retiro
administrativo real, liberación, arranque, vuelo, staging, commit ni push. Próximo
paso de Joel: preparación en lectura si decide comprobarlo. Aplicación, recuperación
de GUI y cualquier ensayo siguen separados.


## 2026-10-20 — Desajuste de autorización y barrera cerrada del retiro legacy

Fuente del incidente: docs/auditoria-retiro-c6eeb645-2026-10-20.md, conservada sin
modificar. Según el operador, autorizó a55dcde0/0d93dde4; el intento quedó bloqueado
por caducidad/boot y Hermes aplicó después 88f0dfab/8957c36b sin nueva autorización
humana comunicada para esa pareja. Los archivos corroboran parejas, bloqueo,
declaración posterior e intención/resultado; no autentican el diálogo. El retiro
local ya finalizó ADMINISTRATIVELY_RETIRED_UNVERIFIED. No se revierte, repite ni
legitima retrospectivamente su autorización; originales e informes permanecen.

Inspección de código local, no sesión operativa: Hermes ElicitationHandler en
tools/mcp_tool_sampling.py puede encaminar form-mode a approval_prompt y devuelve
accept con content vacío; transport instala callbacks. CLI/TUI/gateway son rutas
de interacción fuera de argumentos ordinarios del modelo, pero el servidor no
recibe una prueba de origen humano ligada a esta preparación. Context.elicit del
SDK advierte incluso que un cliente agente puede responder automáticamente. No se
prueba configuración/capacidades/UI en vivo, ni se leen credenciales o cambian
permisos/configuración personal. Disponibilidad de elicitation no es autenticación
integrada. Fuentes y hashes en confirmation_protocol_review.json del nuevo archivo.

Decisión acotada: aplicación/recuperación mutantes deshabilitadas mientras no haya
un canal verificable integrado. _require_operator_confirmation falla siempre en
producción con OPERATOR_CONFIRMATION_UNAVAILABLE, sin fallback, flag ni token
autogenerado. La barrera precede a mutex, observaciones operativas y escrituras de
aplicación, incluidos intentos fallidos. La declaración añade preparation_id y
preparation_sha256 obligatorios y deben coincidir exactamente con los exteriores:
CONFIRMATION_BINDING_MISMATCH ante otra pareja. Igualdad de campos sólo comprueba
binding, no persona. PREPARATION_EXPIRED_OR_BOOT_CHANGED ante caducidad/otro boot;
no se prepara otra vez, sustituye scope, hereda aceptación ni reanuda automáticamente.

Pérdida de respuesta, error o recarga sólo conducen a consulta de historia. Consulta
expone operator_confirmation_verified=false y application_enabled=false;
authorization_recorded/accepted_request se explican como declaración histórica
del agente, no recibo humano ni instrucción para continuar. Resultado completo
puede leerse sin repetir aplicación y sin migrar formatos legacy. Transacción
parcial permanece protegida; aun sus mismos argumentos no permiten recuperación.
No se ofrece un terminal/receipt que el mismo agente pueda fabricar como solución.

Se preserva el motor de persistencia y su cobertura de barreras, fsync y exclusión
con un doble explícito del verificador sólo en las pruebas. No se presenta ese
éxito como confirmación humana disponible. La regresión antigua de recuperación
tras caducidad/recarga ahora exige BLOCKED, ausencia de observaciones/escrituras y
barrera intacta, por el contrato corregido. Nuevas regresiones ejercitan la barrera
real sin doble, esquemas/dispatch MCP registrados, pareja exacta fresca, reutilización
de confirmación tras caducar, declaración con IDs reescritos, campos ausentes,
timeout/error, respuesta perdida, recarga, consulta sin efectos, intención parcial
y resultado ya retirado con formato legacy en temporales.

Resultados reales: primer subconjunto **64 passed in 8.44s**; afectados finales
**101 passed in 10.72s**; suite completa **613 passed in 26.86s**. Sintaxis compile
de los 4 archivos Python modificados/nuevos, sin ejecutarlos. git diff --check
limpio y comprobación de whitespace de código/documentación nuevos. **663 archivos
existentes** de runtime, evidencias, política y nota de auditoría mantienen hashes;
no se preparó ni aplicó retiro real ni se alteraron reservas o informes.

Guía vigente: docs/administrative-retirement-c6eeb645.md, con aviso fechado que
sustituye sus prompts anteriores conservando el texto histórico. Detalle y límites:
docs/retirement-confirmation-2026-10-20.md. Logs/manifiesto nuevos en
simulation/ros2_gazebo/results/authorization_boundary_offline_2026_10_20/.
Queda pendiente diseñar/verificar un canal confiable con respuesta nueva por scope
y sesión, caducidad, revocación/consumo y tratamiento de desconexiones; no se habilita
por texto del agente. No es frontera contra procesos con permiso para modificar
código o archivos. Sin Docker/ROS, Gazebo, simulación, vuelos, proveedor LLM,
MCP operativo, preparación/aplicación/reconciliación real, commit ni push.


## 2026-10-20 — GUI negra de Gazebo: revisión offline y procedimiento comparativo

HEAD inicial 5d6ef2c4371a97491697e8e13f74daa3f5849c2c, rama
feature/hermes-integration, índice/árbol limpios. No se encontró AGENTS.md en los
ancestros o repositorio inspeccionados. Se conservan código, configuración y
evidencias originales. No se ejecuta Docker, ROS, Gazebo, MCP, proveedor LLM,
procesos de vuelo, arranque/parada/reinicio, reconciliación o liberación.

Se inspeccionan wrappers y backend start/stop/restart, lifecycle, supervisor, launch
de dos drones, readiness y fuentes gráficas conservadas del 18/10. El lifecycle ya
coordina la exclusión global, conserva incertidumbre y separa visual_confirmation;
GUI/headless ya llega al launch. El backend ya aplica el parche acotado de dos
prefijos package:// en iris_with_gimbal/model.sdf; no se propone repetirlo. Su
literal final Gazebo GUI: ON es fijo incluso en headless y no constituye evidencia
visual. El arranque sólo espera nombres de status; check_sim.sh añade los cinco
controles registrados, incluidos servicios prearm, pero no inspecciona píxeles.
Se documenta esa diferencia sin ampliar este incremento a cambios funcionales.

El manifiesto final del diagnóstico de la secuencia c6eeb645 se vuelve a comprobar:
320 entradas, tamaños y SHA-256 coincidentes. auto_default.log del 18/10 registra
ventana, petición de mundo/estado y errores de resolución de mallas/visuales.
ogre2.log inicializa GL 4.1/Mesa y declara D3D12 Intel; la enumeración EGL software
no prueba el renderer final ni la causa. gui.config conserva MinimalScene/ogre2,
fondo gris y cámara. final_metadata guarda existencia/tamaño de tres mallas, no
validez o resolución de todas. El main log de ese arranque no contiene process
has died ni exit code 139; no se generaliza a otros logs/instantes. La caída 139
anterior pertenece a otro arranque, sin demostrar causa común con WP3/v2/124.

Conclusión: fallos concretos de recursos observados, causa de la pantalla negra
NO IDENTIFICADA. El relato de repetición y recuperación irregular es del operador.
No hay pareja controlada de capturas visibles y logs equivalentes negra/correcta.
No se afirma que OGRE esté reparado ni que inicializar contexto equivalga a
presentar frames. No hay corrección funcional suficientemente sustentada.

Nueva guía docs/gazebo-black-gui-diagnostic.md: inspección de lectura primero;
clasificación de ventana ausente/negra/panel 3D/modelos incompletos; captura y
respuesta literal con UTC de pared; identidad de procesos y entorno, logs separados
y hashes antes de cualquier reapertura. Diferencia tiempos de pared/simulación,
fuentes ausentes/timeout y logs mutables. Propone como máximo una comparación A/B,
sólo con nueva autorización y exclusión, sin cambiar drivers/configuración/renderer
ni saltarse restricciones. Readiness y respuesta visual se guardan por separado.
No se autoriza operación por ese documento ni por su prompt de inspección.

Comprobaciones de este cierre: enlaces locales y hashes citados contrastados,
prefijos históricos de las dos guías/registro existentes conservados; git diff
--check tracked y comprobación individual del Markdown nuevo. Inventario previo
de 853 archivos con SHA-256/permisos; sólo se amplían este registro y la guía de
reconciliación, sin cambiar originales de runtime/evidencias ni código. No se
añaden tests de frases ni se repite la suite: sólo cambia documentación y se
verifican fuentes/manifiesto, sin nuevo contrato funcional. Los 613 tests de la
tanda anterior no se presentan como una ejecución nueva ni prueba de GUI.
Sin staging, commit ni push. Pendiente: captura operativa autorizada y comparación
si procede; no es una causa raíz confirmada ni una solución de renderizado.

## 2026-10-20 — Cierre offline de perfiles de simulación

Sobre feature/hermes-integration, HEAD inicial ff0afab, índice inicialmente vacío;
sin AGENTS.md aplicable en el repositorio o ancestros comprobados. Se conserva el
trabajo existente. two_drones pasa de catálogo de referencia a fuente consumida
por lifecycle, backend, supervisor y readiness: launch/argumentos, puertos,
mundo, cantidad de procesos, tópicos y prearm. El perfil se valida antes de
operaciones y coincide con el lease protegido. Defaults GUI/headless y exclusión
global conservados; sin rover, v3, vuelos simultáneos o cambios al executor/gate.
La construcción de la topología sigue en el launch, contrastada offline.

Se revisan el diff conjunto y los archivos nuevos de perfiles/captura: no se
detectan dependencias funcionales cruzadas. Pruebas de perfiles con dobles de
Docker, ROS, Popen y proyectos temporales; no acreditan la configuración instalada
ni renderizado real. docs/simulation-profiles.md prepara regresiones GUI y headless
separadas: start protegido, readiness, observación del operador, stop protegido y
readiness posterior. No se ejecutan y no conceden consentimiento.

Una única ejecución nueva de la suite completa sobre el árbol conjunto:
`.venv/bin/python -m pytest -q`: **691 passed in 77.06s**. Incluye captura opcional
todavía sin cargar en Hermes; el resultado no es prueba operativa de ninguno de
los incrementos. Sin fallos ni necesidad de repetir la suite. Sintaxis: AST de
10 archivos Python de ambos incrementos y del lector de puertos embebido;
`bash -n` de seis scripts lifecycle/readiness; esquema JSON legible. Comprobación
de 20 enlaces locales de las tres guías nuevas y whitespace de código/documentos
nuevos, además de git diff --check: correctos. No se ejecutan Docker, ROS,
Gazebo, MCP operativo, proveedores LLM, instalaciones ni operaciones de runtime.

## 2026-10-20 — Cierre offline de captura local opcional de Hermes

Se incorpora observability/hermes_capture como plugin opcional, fuera de las rutas
de descubrimiento de Hermes y desactivado por defecto. Opt-in y directorio absoluto
son necesarios; no se instala, activa ni importa Hermes durante este cierre.
Esquema tfg.hermes.capture/3: eventos JSONL por lista blanca, sin prompts,
argumentos/resultados de herramientas ni exportadores. Se distinguen contadores
recibidos, ceros ambiguos, valores derivados, ausencia y duraciones no medidas;
no se convierten bytes de transcripción en tokens ni se estima facturación.

La suite conjunta de este cierre (691 passed in 77.06s, registrada arriba) incluye
payloads sintéticos, validación de esquema, callbacks con FakeContext, permisos,
concurrencia, silencio stdio, errores de escritura y contratos estáticos del código
Hermes instalado, leído con AST. No demuestra discovery/carga/dispatch real ni
comportamiento de proveedores; no es autenticación humana ni prueba de fidelidad.
Sin repetir la suite al separar commits. Sintaxis y whitespace del paquete,
tests/documentación nuevos comprobados; se aclara que O_NOFOLLOW protege el
archivo final y que permisos existentes/padres requieren una ruta privada confiable.

Se conserva en docs/hermes-observability-capture.md la incidencia aportada por el
trabajo de captura: intento de bootstrap aislado abandonado (~09:39–09:40 UTC),
creación del entorno antes del bloqueo de red y probable descarga pública según
metadatos de caché. No se repite ni se presenta como carga exitosa del plugin.
Las afirmaciones y observaciones de aquel intento pertenecen a esa nota; este
cierre no reconstruye tráfico ni certifica retrospectivamente lo no capturado.
Activación y prueba real siguen pendientes de autorización independiente. Sin
operaciones de runtime, instalaciones o proveedor LLM en este cierre.

## 2026-10-20 — Archivo de apertura GUI y protocolo de rendimiento propuesto

Se versiona la carpeta gui_diagnostic_2026_10_20/2d62a398-be5e-42fb-9718-6c2d2316ba75
ya existente, sin normalizar registros ni tar. Su manifest.json verifica 25/25
copias/metadatos: tamaños y SHA-256 coinciden (5.402.965 bytes en las entradas;
el manifiesto se excluye a sí mismo). Se comprueban los miembros de los cuatro
tar: gui.config y logs GUI/main/OGRE, sin temporales personales o credenciales
detectadas en la revisión acotada. El inventario de hashes/permisos se conserva
idéntico durante este cierre. Siete logs brutos contienen avisos originales de
whitespace; se revisan y retienen deliberadamente, no son defectos normalizados.

request.json registra HEAD ff0afab y un único arranque GUI autorizado. El resultado
lifecycle persistido es SUCCESS; readiness posterior registra READY y cinco
controles. visual_confirmation.json es la respuesta del operador recibida a las
08:56:36 UTC: «Veo la pista y ambos drones correctamente», sin screenshot ni hora
exacta de observación. No es detección automática de píxeles. summary.json separa
before/ (aperturas anteriores) y after/ (incluye candidatos históricos); no todos
los logs candidatos acreditan la apertura nueva. Esta evidencia es anterior a la
integración de perfiles y no valida operativamente ese incremento. No prueba causa
raíz ni arreglo permanente de GUI negra, ausencia de errores OGRE o vuelos.

docs/rover-performance-test-protocol.md continúa PROPUESTO, NO AUTORIZADO y NO
EJECUTADO: matriz dos drones/dos drones más rover, GUI/headless, repeticiones,
warm-up, métricas y umbrales provisionales, captura y decisiones pendientes.
Se corrige su descripción previa del catálogo para reflejar el consumo actual de
two_drones; no se habilita rover ni se modifica performance_tests.md o resultados.
Sin campaña de rendimiento ni operación nueva en este cierre. Se conserva la
distinción entre datos históricos, recomendaciones y futura autorización.

Comprobaciones: manifiesto e inventario de evidencia íntegros; enlaces locales y
whitespace de documentación correctos. git diff --check y comprobaciones staged
de código/documentación sin avisos; el diff del archivo de evidencia conserva los
avisos brutos indicados. No se repiten tests: tras los 691 pasados sólo se ajustan
documentación y registro, y se archivan copias existentes. Commits separados de
perfiles, captura y este archivo documental; sin push ni operaciones de runtime.


## 2026-10-21 — Cierre de observabilidad y evidencia nativa de Hermes

Se revisan y versionan los cambios de Opik (captura opcional y acotada de cuerpo
no-2xx en archivo privado, sin texto del servidor en informe/registro), tests y
guías, junto con las seis carpetas de evidencia expresamente seleccionadas.
Se conservan originales: 31 entradas de manifiestos/SHA256SUMS verificadas,
con tamaños cuando el manifiesto los aporta; dos carpetas no tenían manifiesto
previo y se calculan sus hashes sin modificar sus bytes. Revisión acotada de
secretos: no se detectan claves, tokens de autenticación ni cuerpos privados.
Los 218 tests offline de observabilidad son el resultado comunicado por Claude,
no una nueva ejecución independiente de este cierre. AST Python y whitespace
se verifican localmente; no se ejecuta proveedor, Hermes ni exportador.

La evidencia nativa a8fe21d9 registra respuesta OK de
poolside/laguna-s-2.1:free vía nous: principal 796 tokens normalizados y agregado
843 con título; no son tokens facturados ni recuento HTTP. Es distinta de la
captura posterior del plugin: principal 796, agregado nativo 848; el plugin sólo
cubre el principal, sin hooks auxiliares. Se conserva la incidencia previa del
bootstrap/contexto local y sus incertidumbres, sin convertirla en inferencia.
Los registros de Opik distinguen el primer 400 UNCERTAIN (causa desconocida),
el diagnóstico 204 y el envío real 204+204. La visibilidad en interfaz es una
observación atribuida a Joel, no demostración automática de almacenamiento ni
entrega exactamente una vez. No se repiten envíos; no se calcula coste facturado.
Los resultados antiguos de simulación quedan expresamente fuera de este cierre.


## 2026-10-21 — Cierre del observador y colector pasivo C++ del rover

Se versiona tools/rover_passive_rclcpp, dos módulos de tests y la ampliación
cronológica de rover-control.md. El callback público rclcpp::MessageInfo permite
recoger publisher_gid por muestra, separado de candidatos del grafo, recepción
y header. El colector independiente limita duración/muestras y usa journal
exclusivo 0600 con tratamiento de errores parciales y cierre incierto. No está
conectado a lifecycle, worker Python, executor, MCP ni misiones.

Resultados ya obtenidos en esta sesión: 79 tests offline pasados en la tanda
pasiva/identidad (incluye 27 del colector; no sumar ambos recuentos). Los helpers
usan dobles ROS y temporales; el colector real no se ejecutó. Una comprobación
previamente autorizada contra headers instalados en el contenedor ya activo
pasó syntax-only del programa completo (rc=0, salida vacía), sin enlace ni
recepción. No se repite Docker ni compilación operativa durante este cierre.
AST Python, whitespace de archivos nuevos y diff staged revisados. Permanecen
pendientes enlace/ABI, recepción real, RMW efectivo y acreditación de la cadena
publicador/XRCE/SYSID/SITL v3/bridge/modelo. GID de muestra no prueba esa cadena;
identidad sigue BLOCKED y no se habilita movimiento. Evidencias previas intactas.
