# Diagnóstico de la secuencia incompleta c6eeb645 — 18/10/2026

Operación `c6eeb645-17d2-4081-9afb-cecfd23af393`, clave `joel-secuencia-sitl-01`.
**No se inicia, reanuda o reconcilia. Las reservas permanecen UNCONFIRMED.**
Se conserva el árbol previo. Este diagnóstico añade evidencia/documentación, sin
corregir funcionalmente executor, workers, reservas o GUI.

## Orden y alcance de las observaciones

Primero se guardan 32 copias locales exactas y manifest_local_initial.json: plan,
operación, snapshots, inputs/jobs/reports/logs de ambos hijos, reservas/índices,
fuentes actuales relevantes, transcripción adjunta y misión/informe PASSED anterior
de v2. Después se realizan únicamente las inspecciones Docker/ROS autorizadas,
con timeouts, y se guardan capturas separadas. No se emiten modos, armado, despegue,
objetivos, LAND, parada/reinicio, prearm, workers nuevos o liberaciones.

El primer acceso al socket Docker fue denegado por permisos; la inspección se
realiza con el acceso aprobado después. Lecturas mediante suscripciones efímeras
best_effort/volatile, sin modificar publishers o configuración, y lectores CLI
exactos del executor. Las herramientas ROS pueden producir sus logs de observación;
no se afirma que la inspección detenga la evolución natural de logs/simulación.

## Hechos persistidos

| Elemento | Estado y evidencia |
| --- | --- |
| Operación | UNCONFIRMED, reconciliation_required, result_status=null |
| Hijo v1 `467f7ec6-b2a6-4b68-9d97-766d85732f8e` | FINISHED/PASSED, executor COMPLETED; tres waypoints, regreso y LANDED/desarmado; once checks recalculados idénticos |
| Hijo v2 `1b69dfc7-0707-4b68-a009-062610418fe4` | Job FINISHED, informe ERROR/execute; executor_result=null, analysis=null; aceptación por coordinador UNCONFIRMED/result_status=null |
| Reservas | v2.json y sequence.json UNCONFIRMED, dueño/orden/hash coherentes, sin modificar |

`next_index=2` significa dos despachos consumidos; `completed_count=1` significa un
hijo aceptado como completado. No prueba dos vuelos terminados. Hashes de ambas
misiones, inputs, snapshots, plan e informes coinciden con sus vínculos. El v2
anterior `7162bce5-3635-4a76-bf02-6a5a22612aab` mantiene PASSED con el mismo hash
de misión; su análisis se verifica sin modificarlo ni usarlo para aprobar este hijo.

El executor de v1 duró 235.144404 s y el intento de executor de v2 18.574868 s.
El worker de v2 duró 26.914309 s; el intervalo de su informe incluye la cola detrás
de v1. Son tiempos de operaciones, no tiempo en vuelo. El proceso 133909 observado
con start_ticks/boot_id coincidentes está en **Z (zombi)**: terminó, no fue recogido;
ese estado de proceso no confirma aterrizaje de un vehículo.

## Estado recibido por telemetría

Dos ventanas de suscripción, a las 23:38 y 23:42 CEST del 18/10/2026. En la última:

| Vehículo | Último status recibido, Europe/Madrid | armed / flying | Modo registrado | Última geopose recibida |
| --- | --- | --- | --- | --- |
| v1 | 23:42:56.473818 +02:00 | false / false | 9 | lat -35.3632621765, lon 149.1652069092, 584.1900024414 m AMSL |
| v2 | 23:42:57.735763 +02:00 | false / false | 0 | lat -35.3632621765, lon 149.1652679443, 584.1900024414 m AMSL |

Tres muestras de status y posición por vehículo/ventana, con sellos crecientes y
posiciones estables al nivel de lanzamiento conservado de v1 y del ensayo individual
anterior de v2; el hijo v2 fallido no conserva launch_position. Es evidencia de mensajes
entrantes durante la consulta, no sólo de un valor retenido o un proceso vivo.
Los clocks AP y Gazebo tienen orígenes distintos y avanzan despacio respecto a la
recepción: aproximadamente 0.16 s del header por segundo de recepción en la última
muestra de status. No restar hora del PC al sello simulado para declarar antigüedad.
Se conserva cada recepción UTC, header y publisher en telemetry_initial/final.json.

Es consistente con vehículos desarmados/no volando y al nivel de salida durante las
ventanas. No hay confirmación visual, sensor independiente de contacto con el suelo,
certificación de todo su historial ni garantía del estado posterior. **No se usa
para liberar las reservas o convertir el hijo v2 en PASSED.**

Los lectores CLI exactos de origen v2, posición v2 y origen v1 devolvieron 0 en
6.74, 2.55 y 6.74 s respectivamente durante el seguimiento. El 124 no se reprodujo.
Cada orden de lectura y timeout queda en followup_readonly.json. No se llama al gate
operativo/check_sim, que incluiría otros controles distintos de esta telemetría.

## Qué identifica el código y qué falta

El error guardado es FlightControlError con retorno 124 y output vacío. En las
fuentes inspeccionadas, las lecturas get_vehicle_global_origin y get_vehicle_geopose
ocurren antes de GUIDED/ARM y **fuera del try principal** del executor. Ambas llevan
`timeout 10 ros2 topic echo ... --once`. El helper conserva código/output, pero
omite comando/topic/etapa. progress=False suprime mensajes de etapa; todavía no
hay lista de eventos inicializada en ese punto. Una excepción allí escapa al graph,
que registra ERROR con executor_result=null y omite el análisis.

Tres probes offline con dobles y temporales reproducen las dos lecturas como
ERROR/null, mientras que un error de modo dentro del try retorna un FAILED
estructurado. No se emite ninguna orden real. Esto acota el defecto de observabilidad
y el límite de captura en el código actual; **no demuestra cuál lectura falló,
por qué falló o qué versión estaba cargada históricamente**. execution_attempted=true
significa intención/entrada al executor, no prueba de que v2 haya armado/despegado.
No hay evidencia de LAND de v2 en ese ensayo ni base para inferir interferencia entre
drones. El QoS del echo instalado parte de sensor_data y adapta según publishers;
no se demuestra un desajuste de QoS ni se cambia nada.

## GUI/renderizado, separado del servidor y ROS2

Arranque actual identificado: supervisor 46687, 21:12:11 UTC; un servidor Gazebo,
una GUI y dos ArduCopter vivos en la inspección. `/tmp/tfg_demo.log` y launch.log
mezclan salidas con prefijos; server_console.log es del servidor. Se conservan
además los logs específicos `/root/.gz/auto_default.log` (GUI) y
`/root/.gz/rendering/ogre2.log`, mtime del arranque, no el log antiguo del 6 de octubre.

Configuración observada: DISPLAY=:0, QT_QPA_PLATFORM=xcb, GUI engine ogre2,
OpenGL 4.1/Mesa 23.2.1, GL_VENDOR Microsoft Corporation y GL_RENDERER
**D3D12 (Intel(R) UHD Graphics)**. La prueba EGL de un dispositivo software en el
log no se presenta como renderer activo: el renderer declarado es D3D12/Intel.
Existen /dev/dxg, biblioteca WSL d3d12 y socket X0. Ningún dato acredita imagen útil.

La GUI registra fallos al resolver URIs package://ardupilot_gazebo y cargar geometrías
iris/gimbal; las mallas consultadas existen en las rutas instaladas. Es una pista
concreta de resolución de recursos, no demostración de la causa de toda la pantalla
negra. Los logs capturados no muestran process has died/exit code 139 de esta GUI;
no se traslada el crash antiguo OGRE a este arranque. El servidor/SITL registra
controller reset y No JSON sensor message en su propio contexto, sin demostrar
causalidad con el fallo ROS de v2 o la imagen negra.

Los bridges activos se identifican por argumentos de proceso y sus dos YAML.
Publican clocks distintos `/drone1/clock` y `/drone2/clock`, cada uno con un publisher
observado; AP publica `/ap/v1/clock` y `/ap/v2/clock`. No se demuestra duplicación
de publishers en un único /clock global. Otros launch_params históricos recuperados
se conservan como tales, sin usarlos como configuración del arranque actual.

La observación del operador sobre negro repetido y recuperación irregular tras
reinicios está en operator_gui_observation.txt; no es una captura de imagen ni una
prueba de causa común. No se ha reiniciado para diagnosticar.

## Opciones de recuperación: propuestas, no ejecutadas

1. Mantener las restricciones y el estado incompleto, con este diagnóstico para
   revisar el fallo y repetir sólo lecturas acotadas si se necesita actualizar estado.
2. Autorizar por separado una futura reconciliación revisable: contrastar telemetría
   fresca, identidad de procesos, hashes/informes y propietarios de reservas; registrar
   evidencia nueva sin reescribir ERROR/PASSED ni repetir vuelos. No hay desbloqueo
   automático o reconciliación implementada aquí.
3. Tras reconciliación segura y permiso específico, preparar una recuperación de GUI
   o investigación de rutas/renderizado, separada de ROS. No parar/reiniciar con estas
   reservas no confirmadas; no repetir la secuencia por pérdida de respuesta.

`assessment.json` contiene resultados derivados y límites. El manifiesto final da
hashes de todas las capturas, incluido el manifiesto inicial inalterado. Logs vivos
pueden crecer: su hash identifica los bytes capturados y el momento/offset, no una
congelación atómica del contenedor. Los datos brutos conservan CRLF/ANSI/espacios.
