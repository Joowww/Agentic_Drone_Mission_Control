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
