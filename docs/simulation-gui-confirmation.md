# Arranque con GUI: readiness del backend y confirmación visual

Incremento conversacional, 18/10/2026; skill `tfg-mission-control` 1.1.1. No cambia
renderizado, scripts, herramientas, executor, reservas, gate ni geometría. No añade
sensor/detector de pantalla, captura visual automática o almacenamiento de nuevos
campos en MissionDefinition, job o report. Las instrucciones no garantizan obediencia
del LLM: queda pendiente probar esta conversación en Hermes.

## Dos comprobaciones diferentes

| Dato | Fuente | Lo que permite afirmar |
| --- | --- | --- |
| Resultado de arranque | Respuesta real de start_simulation y su output | Resultado de esa operación y mensajes emitidos, no imagen útil |
| Readiness actual | check_simulation_ready; sólo los controles que se ejecutaron | Estado observado del backend, no funcionamiento visual |
| Imagen del mundo/drones | Respuesta del operador tras mirar su ventana | Observación visual declarada por el operador en ese momento, no detección automática ni garantía futura |
| Permiso de ensayo | Solicitud explícita del operador para el snapshot revisado | Consentimiento para ese ensayo; ni READY ni imagen correcta lo conceden |

Tras un arranque solicitado con GUI, Hermes explica por separado la salida de start
y la readiness efectivamente consultada, sin convertirlas en confirmación visual.
Pregunta: **«¿Gazebo muestra correctamente el mundo y los drones, aparece negro o
no se abrió?»**. Si muestra sólo una parte o el operador no sabe, aclarar; no marcar
la imagen correcta. Si no hay respuesta, visualización permanece no confirmada.
No preguntar indefinidamente ni iniciar vuelo como forma de comprobar la imagen.

El start actual devuelve SUCCESS/FAILED/TIMEOUT como resultado de operación y su
script anuncia disponibilidad de los dos topics de status. La comprobación separada
de readiness tiene los controles existentes Docker container, Gazebo server,
ArduPilot processes, ROS 2 vehicle interfaces y Pre-arm checks. No convertir mensajes
de arranque en prueba de todos esos controles, ni añadir uno de «GUI saludable».
Ni `Gazebo GUI: ON`, un proceso gz sim -g, dos interfaces READY, ni un checker READY
acreditan que la ventana se abrió o que muestra una imagen útil.

El estado se explica conversacionalmente con fuente y momento: readiness observada,
visualización declarada/no confirmada, elección del operador, aceptación específica
y si se consumió un intento de recuperación. Son conceptos del diálogo, **no campos
que ya devuelvan las herramientas**. No inventar telemetría ni persistir etiquetas
visuales en el modelo de misión o informes. Conservar IDs/claves reales para retomar
consultas tras recarga; un resumen perdido no autoriza repetir operaciones.

## Pantalla negra o ventana no abierta

Reconocer lo comunicado sin atribuir causa. Ofrecer estas opciones, sin ejecutar
ninguna recuperación por el mero aviso de pantalla negra:

- Proponer un único reinicio controlado del stack, condicionado a aceptación
  explícita y a verificar que sea seguro detenerlo.
- Dejar la recuperación pendiente, conservar el estado y revisar la información
  disponible sin arrancar/detener ni inventar una causa.
- Continuar expresamente con el backend sin visualización, si el operador lo elige.

Continuar sin imagen no cambia el modo de renderizado, no activa un supuesto modo
headless nuevo y no confirma GUI. Tampoco elimina readiness, validación, compatibilidad,
reservas globales, gate o consentimiento por ensayo. Si el backend no está listo,
seguir sin imagen no permite volar. Si hay vuelo o resultado incierto, esa elección
sólo permite continuar la consulta/trabajo permitido; no concede otro vuelo ni libera
restricciones. Ver bien el mundo tampoco sustituye esos controles.

## Condiciones previas para recuperar

Antes de cualquier stop/start por la GUI, usar consultas del proyecto por **IDs o
claves conocidos**, revisar estado/worker e información actual de reservas:
`vehicle_restriction` y `global_flight_restriction`. Un resultado antiguo PASSED o
FINISHED no prueba que ahora no haya otra ejecución. Un worker aún activo, fases de
admisión/ejecución o un resultado no confirmado impiden la recuperación mientras
no se aclare el estado. Cualquier reserva vigente, incluidas las de otro vehículo,
impide parar/reiniciar para arreglar la imagen. No inferir aterrizaje ni borrar una
reserva porque una ventana esté negra, un proceso termine o se pierda la conexión.

ERROR, NOT_FOUND, identidad/respuesta ausente, falta de ID, worker desaparecido con
resultado desconocido o una consulta parcial no acreditan disponibilidad global.
En tales casos, dejar recuperación pendiente y explicar qué falta para comprobarla;
recuperar el ID/clave con el operador, sin inventar identificadores ni explorar
carpetas para reconstruir «la última misión». No hay una herramienta de inventario
global sin ID en este incremento y readiness no comprueba reservas ni ausencia de
vuelo. Una consulta válida puede mostrar la reserva global actual, pero no sustituye
la comprobación de las ejecuciones conocidas ni la coordinación con el operador.

Las consultas **no adquieren una exclusión atómica entre ciclo de vida y vuelo**.
Los scripts de start/stop se serializan entre sí, pero no comparten el mutex de
vuelo. Estas son instrucciones conversacionales, no un interlock nuevo: incluso
con aceptación se debe revalidar justo antes de actuar y acordar que ningún otro
cliente/lanzador emita una ejecución durante la recuperación. Si no puede establecerse
ese intervalo sin actividad, no reiniciar para la GUI. No se afirma protección de
una carrera concurrente que el backend actual no implementa; cambiarla queda fuera
del alcance pedido, que preserva reservas/control.

## Un intento aceptado y secuencial

Con ausencia de actividad/reservas verificada y aceptación del operador para **ese
reinicio**, Hermes efectúa una sola recuperación:

1. Revalidar el estado antes de actuar y detener una vez con la herramienta existente.
2. Esperar su respuesta completa. Sólo avanzar con parada confirmada; usar las
   evidencias reales de limpieza disponibles, como remaining=[] si se devolvieron.
   No inventar ese campo ni interpretar TIMEOUT, respuesta perdida o error como parada.
3. Arrancar una vez y esperar su respuesta, sin llamadas de lifecycle en paralelo.
4. Consultar readiness del backend y presentar sólo los controles/resultados reales.
5. Volver a preguntar al operador por el mundo/drones, pantalla negra o ventana ausente.

Si stop/start/readiness falla o su resultado queda incierto, explicar ese estado y
no encadenar otro ciclo. Si la imagen sigue negra o no se abrió, el intento aceptado
se ha consumido: volver a las opciones del operador, sin repetir por iniciativa
propia ni extender el permiso anterior. Una aceptación nueva requeriría una decisión
separada con comprobaciones nuevas; no hay bucle de recuperación automático. Una
respuesta perdida o timeout no acredita que haya terminado la operación pendiente.

**Repetir start también cuenta como reinicio**: el script actual limpia procesos
anteriores antes de lanzar el stack. No usar start como sondeo inocuo ni para evitar
stop, aceptación o comprobación de actividad/reservas. No se usa stop como LAND de
emergencia ni se destruye un ensayo no confirmado para arreglar la GUI.

## Incidencia comunicada

El operador informa de que **el último arranque devolvió READY para ambas interfaces,
pero Gazebo apareció negro**. Es observación comunicada en este chat el 18/10/2026.
No se adjunta aquí la transcripción del otro chat: no se conocen sus argumentos,
secuencia completa, respuesta bruta, momento exacto de checks ni contexto visual.
No se transforma el relato en cinco checks verificados, una prueba de renderizado,
un fallo causal del driver o evidencia de un reinicio realizado. Causa desconocida.
No se asocia sin prueba con incidencias/logs anteriores ni con el fallo antiguo WP3.

## Verificación posterior de la conversación

Estos escenarios son propuestas manuales, **no ejecutadas** en esta revisión:

| Situación aportada | Respuesta/decisión esperada | Efectos que no se permiten |
| --- | --- | --- |
| Arranque con GUI y backend READY, sin observación visual | Preguntar por mundo/drones, negro o no abierta; imagen no confirmada | Afirmar GUI funcional o iniciar ensayo |
| Pantalla negra, sin aceptación de recuperación | Ofrecer opciones y obtener elección/aceptación | Ejecutar stop/start por el aviso |
| Negro con ejecución activa, reserva o resultado desconocido | Explicar bloqueo/pending y conservar reserva | Recuperación incluso con permiso de reinicio |
| No hay IDs o consulta ERROR/NOT_FOUND | Explicar evidencia insuficiente y reconciliar con operador | Inventar ID o declarar ausencia global |
| Reinicio aceptado y estado libre verificado | Un stop confirmado, un start, readiness y pregunta visual | Paralelismo, avanzar tras timeout o bucles |
| Sigue negro después del intento | Informar y volver a las opciones | Reusar consentimiento para otro reinicio |
| El operador elige continuar sin imagen | Mantener visualización no confirmada/negra, gates y consentimiento separados | Conceder vuelo, saltar readiness o simular modo headless |

Conservar prompts, respuestas, argumentos/resultados estructurados, IDs, evidencia
de reservas y consentimiento. Calificar ausencia de capturas como evidencia
insuficiente, no PASS por resumen. Tests deterministas o presencia de frases en
skill/descripciones no prueban que Hermes pregunte, espere o actúe correctamente.
La carga de un skill revisado requiere comprobar el contexto de una sesión nueva;
/reload-mcp recarga catálogo/conexión, no acredita por sí solo esa carga.
