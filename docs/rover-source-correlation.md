# Correlación histórica del rover — 22 de octubre de 2026

Estado: **BLOCKED**. Análisis offline; no hubo apertura, recepción, consultas ni cambios de gates. Los hashes prueban consistencia de las copias, no autenticación criptográfica. No se añade un requisito de autenticación al contrato existente.

Ensayo: `40e8c751-6d70-4280-b94b-b1512e1e2802`. El analizador verificó las **170 entradas** del manifiesto original sin modificarlas. Informe reproducible: [report.json](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/report.json); comando y retorno en [execution.json](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/execution.json). El retorno 2 significa cadena parcial bloqueada; 1 indica evidencia inválida.

```bash
.venv/bin/python -m tools.rover_passive_journal --correlate-capture simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802
```

## Matriz de enlaces

### MessageInfo/GID -> DDS publisher endpoint

Estado: `HISTORICALLY_CORRELATED`.

Relación respaldada: el GID de MessageInfo coincide con el único candidato DDS de tipo correcto observado en el grafo de cada muestra. El nombre anunciado no identifica un proceso.

- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/capture/journal.jsonl](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/capture/journal.jsonl) — SHA-256 `e73a5e4bb679a12d9ce85036c0c36f8e03ace4cd21db0e774af7f25aece43391`. Selector: sample.MessageInfo and separate graph candidates.

Pendiente: Advertised node name is not an OS process identity or cryptographic authentication.

### DDS publisher endpoint -> XRCE client/session

Estado: `MISSING`.

Relación respaldada: el log del agente acredita clientes y objetos XRCE, pero no contiene el join con el GUID/GID DDS.

- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_readonly_report.json](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_readonly_report.json) — SHA-256 `c72b5bd93768017eecaf53d8861cc1aee09cc623349f1122bb01473e54e20f8e`. Selector: processes: exact micro_ros_agent argv/exe hash.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/003/tfg_demo.log](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/003/tfg_demo.log) — SHA-256 `b8fccf8636cb5018940f37d3b50819691cfbd22c10dd570cbe161231a2312e4f`. Selector: /tmp/tfg_demo.log.

Pendiente: No retained record joins native DDS GUID/GID to client_key and XRCE writer object. Session 0x81 and object IDs are scoped per client and recur across clients. The GID byte suffix is not decoded as an XRCE object number.

### XRCE client/session -> SYSID and SITL instance

Estado: `CONFIGURATION_ONLY`.

Relación respaldada: argv de `ardurover`, instancia 2 y SYSID 3; su rol de launch registra MAV_SYSID=3. Los clientes XRCE tienen claves y sesiones registradas; la asociación entre ambos no está acreditada.

- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_readonly_report.json](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_readonly_report.json) — SHA-256 `c72b5bd93768017eecaf53d8861cc1aee09cc623349f1122bb01473e54e20f8e`. Selector: ardurover argv --instance 2 --sysid 3, start_ticks/exe hash.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/003/tfg_demo.log](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/003/tfg_demo.log) — SHA-256 `b8fccf8636cb5018940f37d3b50819691cfbd22c10dd570cbe161231a2312e4f`. Selector: /tmp/tfg_demo.log.

Pendiente: No retained socket/process/client-key mapping or exact runtime parameter readback. Reference key-base/name construction needs executable provenance; numeric similarity alone is not binding.

### SITL instance -> bridge/configuration

Estado: `SAME_START_CONFIGURATION`.

Relación respaldada: procesos del mismo arranque protegido, con PID/start_ticks y boot contrastados; argv del bridge selecciona params, que selecciona el YAML efectivo.

- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/capture/execution.json](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/capture/execution.json) — SHA-256 `92109457e2aa788dc4de1a9ca72a2822b3101c4b7ae2f8db28f28eb40caa953d`. Selector: context and protected start.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/container_processes_before_close.stdout](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/container_processes_before_close.stdout) — SHA-256 `62f00bfc1ab349b3c285c071ba1efa5a38fe12d0ff7e3ef5a06ab9f431404b07`. Selector: process identities in one container boot.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/054/launch_params_otj8p3aa](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/054/launch_params_otj8p3aa) — SHA-256 `fab23f3c4f41f2f369c6d0ac0befa01f865623f5d8d2d6b07d9d174377c3d771`. Selector: /tmp/launch_params_otj8p3aa.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/055/tmp7g9w6hpu.yaml](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/055/tmp7g9w6hpu.yaml) — SHA-256 `db97010c73c389d1d8e3fbb4712d4e565f94442a478f15429895b35cfe77b093`. Selector: /tmp/tmp7g9w6hpu.yaml.

Pendiente: Same protected launch is not proof that a DDS Status endpoint originates in this SITL process.

### bridge/configuration -> Gazebo model

Estado: `CONFIGURATION_MAPPING_OBSERVED`.

Relación respaldada: el YAML mapea /model/rover1/odometry a odometry en /rover1, GZ_TO_ROS, nav_msgs/msg/Odometry. Es configuración observada, no prueba de la instancia/plugin productor.

- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/055/tmp7g9w6hpu.yaml](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/055/tmp7g9w6hpu.yaml) — SHA-256 `db97010c73c389d1d8e3fbb4712d4e565f94442a478f15429895b35cfe77b093`. Selector: /tmp/tmp7g9w6hpu.yaml.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/058/tfg_demo.launch.py](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/effective_files/058/tfg_demo.launch.py) — SHA-256 `69bf4c278295625841ab1bd1578f4cdde2fc4d1512c7eaaafe5a63e876070ba4`. Selector: /root/ardu_ws/install/ardupilot_gz_bringup/share/ardupilot_gz_bringup/launch/tfg_demo.launch.py.
- [simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/operator_visual_confirmation.json](../simulation/ros2_gazebo/results/rover_passive_quota_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/operator_visual_confirmation.json) — SHA-256 `fbc95aafc97e6200241e54ddce2342fd6a990a4ff4cd5b85b6d9e42b63e67d04`. Selector: operator observation only.

Pendiente: Configuration maps the Gazebo topic name; no model-instance/plugin/UDP association was captured. Human visual confirmation does not bind GID or SYSID to the rendered rover.

## Fuentes locales y alcance

Copias exactas y hashes: [reference_sources.json](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources.json). Se preservan separadamente de la evidencia operacional original; no se ha demostrado que esos árboles sean la procedencia exacta de los ejecutables históricos.

- `/home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot/libraries/AP_DDS/AP_DDS_Client.cpp` — SHA-256 `f512901b5c3617aa46861a967ef1cddb2515878523b1fbf240bbb54333ceaef4`; [copia](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources/0/AP_DDS_Client.cpp).
- `/home/joelm/TFG/ardupilot_ros2_ws/src/ardupilot/libraries/AP_DDS/AP_DDS_Client.h` — SHA-256 `24f8f0689b14ec8c04ebf10b9f7499e6d58b05c561ff97a760de346f8c9796de`; [copia](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources/1/AP_DDS_Client.h).
- `/home/joelm/TFG/ardupilot_ros2_ws/src/micro_ros_agent/micro_ros_agent/src/agent/Agent.cpp` — SHA-256 `bf26791ec2d215502e3b94e485edcd83eb2b875f705355257650306c7545553b`; [copia](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources/2/Agent.cpp).
- `/home/joelm/TFG/ardupilot_ros2_ws/src/micro_ros_agent/micro_ros_agent/src/agent/graph_manager/graph_manager.cpp` — SHA-256 `f155776956a99b8d2cb53904f262e59ef15378a7458208c1ef55fc95bc5e626b`; [copia](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources/3/graph_manager.cpp).
- `/home/joelm/TFG/ardupilot_ros2_ws/build/micro_ros_agent/agent/src/xrceagent/src/cpp/client/ProxyClient.cpp` — SHA-256 `b4cdcc4ff92f263a399bc93ffe9f7b2df8301a81cc43ef5a97624545c19b904c`; [copia](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources/4/ProxyClient.cpp).
- `/home/joelm/TFG/ardupilot_ros2_ws/build/micro_ros_agent/agent/src/xrceagent/src/cpp/middleware/fastdds/FastDDSMiddleware.cpp` — SHA-256 `213a0760077df770f565d26fc3975298adafcea8fb8a9bc409321a2b1d6a178f`; [copia](../simulation/ros2_gazebo/results/rover_source_correlation_2026_10_22/40e8c751-6d70-4280-b94b-b1512e1e2802/reference_sources/5/FastDDSMiddleware.cpp).

AP_DDS_Client.cpp/h construye client_key con key_base 0xAD000000 OR SYSID, participante ap_vN y topic rt/ap/vN/status cuando DDS_USE_NS está activo. Esto explica la configuración esperada: no prueba por sí solo el origen del endpoint recibido.

Agent.cpp registra CREATE_DATAWRITER con participante y DataWriter: puede obtener el GUID nativo, pero ese callback no recibe ClientKey. GraphManager convierte GUID a rmw_gid con rmw_fastrtps_shared_cpp::create_rmw_gid. ProxyClient registra ClientKey y object ID al crear un writer, sin su GUID DDS. FastDDSMiddleware dispone del writer nativo; su callback actual tampoco aporta el ClientKey. No se ha encontrado un registro conservado que una ambos contextos.

## Primer enlace faltante en la revisión del 22/10 y comprobación mínima preparada

Falta **DDS publisher endpoint → cliente/sesión XRCE** para Status. No se deben decodificar el sufijo del GID o el número 3 como prueba. Los session_id y object_id se reutilizan entre clientes. La rama de odometría procede del bridge DDS/Gazebo y no debe forzarse artificialmente por XRCE.

Dato mínimo: una fila del mismo proceso/agente y sesión que contenga `{ClientKey, session_id, XRCE writer object_id, native DDS writer GUID, conversión RMW/GID, topic/type/domain}`. El GID convertido debe coincidir exactamente con MessageInfo de Status, manteniendo contexto temporal y de proceso y ausencia de contradicciones. Eso permitiría correlación operativa del endpoint con el cliente, sin autenticación criptográfica ni verificación automática de toda la cadena.

Los logs actuales y las consultas públicas del grafo no entregan esa fila. No hay un comando de lectura existente demostrado que la recupere; subir verbosidad o repetir una apertura no garantiza resolverlo. El siguiente trabajo mínimo es revisar y compilar offline una traza diagnóstica del agente que conecte los dos contextos anteriores, preservando los callbacks de grafo. Sólo después, y con autorización separada, una observación pasiva acotada podría recogerla. En la correlación inicial no se implementó ni ejecutó esa instrumentación; la preparación posterior se describe al final. La asociación cliente ↔ proceso SITL requerirá además el vínculo de transporte/sesión y procedencia de configuración efectiva; hoy queda configuración parcial, no una conclusión.

## Contrato y límites

Se conserva el contrato de tools/rover_environment_identity.py: entorno/worker y proceso, tipos y frames, fuentes únicas, frescura y progreso, asociación XRCE/SYSID/DDS y bridge/modelo. Este archivo histórico no satisface frescura actual; una sola muestra Status no demuestra progreso. El worker Python sigue sin GID por muestra y el colector C++ no se integra en el guard. Identidad completa y movimiento siguen BLOCKED.

El binario ejecutado fue `43d5b5eb4d13d78ef83d60f4b9eb6fa9868111d8efefe2d6c8fe373866f7c58c`. El posterior `94c0a9dd4a454c41561b0355803a7232ae001cf842336124341163ff5cf90d93` incorpora validación adicional del cap y no se ejecutó en ese ensayo. El campo executed=false del registro de build original describe el momento de compilación; command/receipt y hashes antes/después acreditan la ejecución posterior.

Las pruebas usan copias temporales del formato real, incluyendo las 170 entradas; dependen de ese fixture local preservado. No son nuevas capturas ni validación operacional. El parser YAML seguro ya instalado se usa sólo offline; si no está disponible, falla cerrado.

## Traza diagnóstica preparada — 2026-10-22

El [parche y receta nativos](../tools/rover_xrce_trace/README.md) añaden contexto explícito de creación XRCE y conversión RMW/GID, con salida desactivada por defecto. La biblioteca y el wrapper han compilado y enlazado contra dependencias reales, sin ejecutar el agente. El selector explícito del overlay diagnóstico ya está integrado y probado offline en el lifecycle protegido; el arranque ordinario sigue seleccionando el agente instalado. Falta su primer ensayo autorizado, descrito en la receta enlazada. No se ha obtenido una nueva asociación ni se han alterado gates o evidencias anteriores.


## Matriz actualizada — ensayo único del 24/10/2026

Se conserva arriba la matriz **histórica del 22/10**: no se reinterpreta como si
hubiera recibido la traza nueva. El ensayo `eb113b19-4923-4983-bed4-2e99db1aa512`
terminó con recepción y cierre válidos; sus **119 archivos y manifiesto se
mantienen intactos**. Manifiesto SHA-256
`42ab6eb1046f4f0983441b1c4949d4ade27444a015301b0829acdd39082a7a86`.

| Enlace | Estado y alcance del 24/10 |
|---|---|
| Muestra Status → writer DDS → cliente/sesión/objeto XRCE | **OBSERVADO** por igualdad exacta GID/RMW, proceso y creación XRCE confirmada; no por nombres ni candidatos del grafo |
| Cliente XRCE → peer UDP | **OBSERVACIÓN DEL LOG, GENERACIÓN NO VINCULADA**: ClientKey 0xAD000003 y peer 127.0.0.1:35242 en el mismo log de arranque. El registro de peer no contiene client_instance ni intento; no se promueve a enlace inequívoco de generación |
| Peer → socket inode → FD → proceso SITL | **PENDIENTE**: no se recogió ese inventario durante el ensayo cerrado; no se reconstruye ahora con sockets de otra sesión |
| argv --sysid 3 → SYSID efectivo | **CONFIGURACIÓN OBSERVADA / EFECTIVO PENDIENTE**. Ardurover PID 6944, start_ticks 14171708, instancia 2 y argumento --sysid 3; no lectura del valor efectivo |
| Odometry → publicador DDS / bridge / modelo | **RAMA INDEPENDIENTE DE XRCE**. 19 muestras, GID por muestra y candidatos de grafo; el candidato ros_gz_bridge no autentica su proceso/plugin/modelo. El YAML de bridge de este ensayo no quedó acreditado |

La muestra Status tiene GID
`010feb7d041b6b870000000000000f030000000000000000`, RMW
`rmw_fastrtps_cpp`; el GUID nativo es
`010feb7d041b6b870000000000000f03`. El agente identificado es PID 6916,
start_ticks 14171706, boot `51f3835d-91d2-4044-a115-2dcb8c14768a`.
El registro 27 declara `client_instance=1`, `attempt=15`,
`client_key=2902458371`, `session_id=129`, `writer_id=14`; el 28 confirma
`committed=true` en ese mismo contexto. Topic/tipo nativos exactos:
`rt/ap/v3/status`, `ardupilot_msgs::msg::dds_::Status_`, dominio nativo **0**.
La recepción no guardó una observación independiente de ROS_DOMAIN_ID del
receptor; no se sustituye ese dato por un default. Esto no invalida el join exacto
del endpoint ni convierte su dominio observado en una lectura del receptor.

Referencias de **esta sesión**, sin mezclar la captura del 22/10:

- [journal.jsonl](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512/container_after/container_copies/tmp/tfg_rover_xrce_capture/eb113b19-4923-4983-bed4-2e99db1aa512/journal.jsonl) — SHA-256 `949ccef9f204e433ff8d79e1d47f6fe6041e298b96df1c88b1093abde74b25ca`
- [trace.log](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512/container_after/container_copies/tmp/tfg_diagnostic_agents/18a9a8f0-17a3-488e-8083-da38bbe4c00a/capture/trace.log) — SHA-256 `21baffb78ac523dd9b2063c206e8a22efff10869a5cd3a1b32af01f3373a6b50`
- [monitor.json](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512/container_after/container_copies/tmp/tfg_diagnostic_agents/18a9a8f0-17a3-488e-8083-da38bbe4c00a/capture/monitor.json) — SHA-256 `db742abf6d3a0b48b0973dec79396f4ccc6c3a3826ef6586103fd9c0bbc0f211`
- [correlation_analysis.json](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512/correlation_analysis.json) — SHA-256 `5575748013034186b28fff1f4f14425084d1efd64cc31ead7efa7c7ed83cec31`
- [tfg_demo.log](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512/container_after/container_copies/tmp/tfg_demo.log) — SHA-256 `f7e4e20bfc3f6cee1a5bbbaa1fcae917cf97fe04f7d606e0a80daa8edcd4f2f1`
- [container_during_report.json](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/eb113b19-4923-4983-bed4-2e99db1aa512/container_during_report.json) — SHA-256 `ebfb00043d074dedc7c0aca989ea8a5fe6d821f3b090667ec76b87d853087c2d`

### Por qué el log anterior no cierra el enlace de generación

`SessionManager::establish_session` imprime ClientKey y dirección, pero no la
identidad del objeto ProxyClient. `Root::create_client` puede reemplazar el objeto
al cambiar session_id; para el mismo session_id puede resetear la sesión del
mismo objeto. También pueden borrarse y recrearse clientes con las mismas cifras.
Que sólo aparezca un peer para esa clave en el log guardado no demuestra que esa
línea pertenezca a la generación del writer. Se conoce la generación **1 del
writer**, no una generación explícita en la línea del peer. No se unen ambos
por cercanía temporal, sufijos numéricos ni orden de callbacks.

Fuentes contrastadas (referencias y hashes completos en
[peer-source-preparation.json](../tools/rover_xrce_trace/peer-source-preparation.json)):
`transport/SessionManager.hpp`, `Root.cpp`, `processor/Processor.cpp`,
`client/session/Session.hpp`, `stream/InputStream.hpp`, `message/Packet.hpp`,
`message/InputMessage.hpp` y el endpoint IPv4 público. La instrumentación mínima
preparada adjunta metadatos de transporte al InputMessage antes de mover su
`unique_ptr` a la cola de sesión. Al extraerlo se contrasta la instancia, clave y
sesión con la referencia exacta de ProxyClient que procesa el mensaje y crea el
writer. El peer viaja con ese objeto aunque la cola se desbloquee por otro
paquete; no se hace una segunda búsqueda por clave ni se atribuye por orden.
Un getter diagnóstico devuelve el mismo client_instance de writer/commit.
Los metadatos incompletos o una generación distinta producen peer=null.
La adición del miembro cambia la disposición de InputMessage: exige recompilar
y enlazar el agente nativo y su wrapper compatibles, sin mezclar bibliotecas.

El endpoint usa getters públicos `IPv4EndPoint.get_addr()/get_port()` y el orden
de octetos de su formatter revisado. Otros transportes permanecen UNKNOWN.
No hay búsquedas posteriores por clave, acceso a payloads ni cambios en callbacks,
órdenes o gates. Los mensajes antiguos liberados de la cola no se atribuyen al peer del paquete
que los desbloqueó: se conserva el metadato de su propia recepción, contrastado con el cliente actual. Un mensaje
reensamblado no conserva fuente acreditada de todos sus fragmentos; el ámbito
de fragmentos fuerza peer=null en vez de heredar el último. La observación
disponible describe el paquete **de creación del writer**, no todos los paquetes
Status posteriores ni continuidad del peer.
Client_instance representa la vida del objeto ProxyClient, no un contador de
resets de la sesión; attempt distingue la invocación de creación. No se afirma
una continuidad de sesión o transporte que esos campos no prueban.

La variante fuente está preparada en una copia disjunta; parche adicional
[peer-agent.patch](../tools/rover_xrce_trace/peer-agent.patch), helper
[peer_endpoint.hpp](../tools/rover_xrce_trace/peer_endpoint.hpp) y receta actualizada
[prepare.py](../tools/rover_xrce_trace/prepare.py). El parche/binary históricos
permanecen intactos: los binarios fijados del ensayo completado **no contienen**
esta nueva instrumentación. El analizador mantiene compatibilidad con esa traza
sin inventarle un peer. Falta compilar/enlazar la variante y el wrapper reales,
revisar compatibilidad y fijar explícitamente los nuevos hashes en selector y
manifest. **No se propone una apertura ejecutable antes de cerrar ese requisito.**

### Inventario pasivo de sockets preparado, NO ejecutado

[socket_inventory.py](../tools/rover_xrce_trace/socket_inventory.py) se despliega
con el mismo conjunto de helpers de selección. Lo invoca únicamente el monitor
diagnóstico existente, tras observar al agente; no hay integración con control,
worker de movimiento, misión ni MCP. El arranque ordinario no crea ese monitor.
El contexto declarado procede del descriptor protegido y de la identidad de
launch/agente; el colector no finge consultar Docker ni autenticar esos IDs.
Contrasta boot, PID/start_ticks y namespaces net/pid de self, launch y agente
antes/después, incluido el ejecutable esperado del agente. Un /proc montado
o proceso en namespace incompatible falla cerrado.

Lee `/proc/self/net/udp` y `udp6`; conserva endpoints originales y normalizados,
familia, estado e inode, y cruza inode con enlaces `/proc/PID/fd/N`. Hace dos
barridos de FD/procesos, tablas antes/después y contexto antes/después. Cada
lectura tiene fuente, UTC de recepción e intervalo monotónico propio. No compara
estos relojes con timestamps simulados. No captura payloads ni environment; argv
sólo conserva basenames/opciones numéricas permitidas (no comandos shell, tokens,
passwords ni defaults arbitrarios).

UDP **UNCONNECTED** con rem_address cero puede transmitir con sendto(): no
significa que no haya comunicación. El peer se contrasta con el endpoint **local**
del socket cliente, no con su remoto cero. Un bind wildcard queda candidato; no
se convierte en IP local exacta. Varios inodes para el mismo endpoint o varios
propietarios/FD compartidos se conservan como ambigüedad, sin elegir por nombre
ardurover. Sin propietario visible es UNKNOWN, nunca prueba de ausencia.

Permisos, desaparición, cambio de PID/start_ticks, ejecutable, namespace, tabla o
FD entre barridos conservan datos parciales e impiden asociación utilizable. Se
excluye únicamente el FD de directorio abierto por scandir del propio lector,
no sus sockets ni FDs desaparecidos de otros procesos. Incluso dos lecturas
iguales no son una instantánea atómica ni detectan todos los casos ABA,
transferencias de FD o exec del mismo binario entre lecturas. El resultado es
siempre BLOCKED; una coincidencia da **candidato de proceso visible**, no origen
demostrado de un paquete, identidad completa ni SYSID efectivo.

Límites: 250 ms cooperativos, 128 PID, 2048 FD por barrido, 1024 lecturas y 128 KiB
por resultado. El monitor limita cada hijo de consulta a 750 ms; si una lectura
kernel no devuelve, sólo termina ese hijo propio, nunca un proceso descubierto.
El impacto de muestreo en el entorno real todavía no está medido. La salida se guarda 0600 en `capture/sockets.jsonl`, máximo 64 lecturas programadas
cada 5 s (hasta 8 MiB). No aumenta los 600 s/512 registros/2 MiB existentes de la
traza ni los límites Status 20/120. Al agotarse el canal de sockets, el resumen lo
indica; no afirma cobertura de todo el intervalo posterior. Un timeout/error de
consulta o persistencia deshabilita nuevas consultas; un registro parcial por
carrera se conserva y las siguientes lecturas **ya programadas** siguen siendo
observaciones distintas, no reparación ni repetición de una captura fallida.

`analyze_series` rechaza líneas truncadas, recuentos contradictorios, sesiones o
procesos mezclados, registros parciales y propietarios cambiantes; no selecciona
sólo una línea favorable. `match_peer` exige proceso de agente y lifecycle exactos
y un peer ligado explícitamente a generación. Los candidatos de un archivo de
otra sesión no pueden completar la cadena. No se infiere autenticación de ninguno.

### Un futuro ensayo protegido, pendiente de preparación y autorización

Después del build/link real y revisión de hashes, el mismo selector protegido
será la única entrada; no lanzar un segundo agente ni el colector de sockets
manualmente. Prechequeo nuevo: identidad, restricciones, procesos y todos los
helpers/artefactos; una apertura con traza desde inicio y socket journal separado;
confirmación visual real; una recepción Status/odometría 20 muestras/120 s con
reserve-streams; parada protegida. Guardar traza, sockets, journal, recibos, código
de retorno, monitor, identidades y hashes en directorio nuevo. No ejecutar nada de
esto como parte de esta preparación.

Analizar GID → writer → contexto/peer **de esa misma creación**, y después peer
→ endpoint/inode/FD/proceso usando las lecturas con sus límites y contradicciones.
Un cambio de peer posterior, reset o falta de contexto explícito impide extender
la asociación a todo el flujo Status. Sin sockets o con ambigüedad, conservar
BLOCKED; no pedir una apertura repetida para ocultarlo. La obtención del SYSID
efectivo requiere una fuente de configuración/lectura pública realmente disponible
(o queda pendiente); no se inventa un servicio. La rama bridge/modelo se revisa
por sus propias fuentes y no se hereda de XRCE.

### Explicación breve para defender

**El GID por muestra identifica el endpoint DDS que entregó esa muestra.** La
traza nativa permite relacionarlo con la creación de un writer XRCE concreto,
no autentica criptográficamente al vehículo. **El socket relaciona un endpoint
de red e inode con FDs de procesos observados**; puede ser compartido, transferido
o cambiar durante la lectura, y UDP puede no estar conectado. **Ninguno lee el
SYSID efectivo del autopiloto**: un nombre v3, una clave terminada en 3 o argv
`--sysid 3` no sustituyen esa comprobación. Identidad completa y movimiento siguen
**BLOCKED**.

### Actualización de preparación: build nativo y wrapper — 24/10/2026

El requisito de compilación/enlace pendiente indicado arriba ya se comprobó,
sin ejecutar ningún binario del agente. El [registro de build](../tools/rover_xrce_trace/peer-build-2026-10-24/verification.json)
vincula los siete originales verificados, headers diagnósticos, parche, receta,
fuentes del wrapper y dependencias reales con los nuevos hashes. La comprobación
ELF y de dependencias de compilador evita mezclar el ABI de InputMessage con los
headers instalados anteriores. Es una comprobación estática; falta observar las
bibliotecas cargadas y los nuevos metadatos durante un ensayo autorizado.

El selector conserva separadas la pareja histórica y la nueva, rechaza mezclas y
dispone de [manifest peer explícito](../tools/rover_xrce_trace/diagnostic-agent.peer.json).
Los binarios y las 119 entradas del ensayo anterior no se han sustituido. El
[procedimiento actualizado](../tools/rover_xrce_trace/README.md#peer-variant-real-compilelink-verified--2026-10-24)
prepara el siguiente ensayo único, que **no se ha ejecutado ni autorizado aquí**.
El build no completa ningún enlace de identidad adicional: peer de generación,
socket/proceso, SYSID efectivo y bridge/modelo conservan los límites de la matriz.

### Estado posterior a f338 y corrección del inventario — 24/10/2026

La sesión `f3380567-b48a-4e47-b4c5-c3be066a76d1` cerró por lifecycle SUCCESS,
con recibo de monitor cerrado y 84 registros nativos. No hubo colector Status:
no se añade un enlace MessageInfo de esa sesión a la matriz. Sus 64 inventarios
siguen incompletos por OUTPUT_BUDGET_DATA_INCOMPLETE. La GUI abortó (134) con
excepción OGRE; el backend continuó hasta su parada. No se relaciona ese aborto
con XRCE ni se atribuye a VRAM sin contadores.

El [procedimiento existente actualizado](../tools/rover_xrce_trace/README.md#socket-budget-gui-exit-observation-and-next-peer-trial--2026-10-24)
explica la representación compacta con referencias explícitas, validación de
procedencia en ambos barridos, observación separada de salida GUI, pruebas
offline y la única sesión futura propuesta. Las fuentes/binarios nativos son
los mismos; sólo cambian helpers diagnósticos. Ninguna corrección reconstituye
las observaciones históricas perdidas ni acredita identidad completa/movimiento.

### Búsqueda dirigida por peer y límites medidos — 24/10/2026

El [procedimiento vigente](../tools/rover_xrce_trace/README.md#peer-first-search-and-measured-budget-diagnosis--2026-10-24)
incorpora el diagnóstico y la comparación con el algoritmo exacto del ensayo de
110 entradas. La composición histórica previa al descarte no se conserva; sus
37 fallbacks tampoco conservan el motivo anterior. No se reconstruyen como
inventarios completos. La búsqueda preparada parte del peer de una creación
nativa validada, acota sockets y conserva la búsqueda global de todos sus
propietarios. Las métricas y regresiones de estrés están etiquetadas como
sintéticas, con límites de lectura y bytes explícitos. No ha habido nueva
apertura, monitor o recepción; la matriz de enlaces observados no cambia.

### Ensayo b9ee — recepción y límites observados, 24/10/2026

[La misma sesión](../simulation/ros2_gazebo/results/rover_xrce_trial_2026_10_24/b9ee5ec5-049d-47cc-b22f-26535b972b5f/session_analysis.json)
recibió 1 Status y 19 odometrías con cierre de diario/recibo válido y confirmación
visual nueva de Joel. Status/GID → writer DDS → contexto XRCE se observó por
coincidencia exacta. La traza nativa conserva el peer como entero crudo de
sin_port; la interpretación como puerto host era defectuosa y quedó corregida
offline con fuente y ELF, sin reescribir los originales. Los 64 inventarios
seleccionaron cero inodes con el puerto erróneo y no cubren temporalmente la
recepción Status. **No se acredita peer→socket→SITL ni SYSID efectivo**.

Parada lifecycle SUCCESS y lecturas posteriores sin procesos/guardas; recibo de
monitor INCOMPLETE por su plazo, no equivalente a cierre de captura completo.
El [procedimiento existente](../tools/rover_xrce_trace/README.md#protected-scoped-trial-b9ee-reception-port-contract-and-coverage--2026-10-24)
separa ambos hechos, explica la corrección y exige presupuesto diagnóstico fresco
antes de una recepción futura. No hubo segunda apertura ni reintentos.

## Camino mínimo hasta R1 — revisión de código offline, 25/10/2026

No se cambian gates. El presupuesto diagnóstico preparado es 2048 eventos/256 KiB,
64 filas/16 MiB con admisión condicional hasta captura+cierre; no es un resultado
operativo ni una autorización de ensayo. Contenedor documentado actualmente detenido;
no se inició. Se conservan las matrices históricas anteriores por sesión.

| Prioridad / requisito | Evidencia disponible | Pieza pendiente, archivo/función | Comprobación mínima |
| --- | --- | --- | --- |
| 1. Peer→socket→SITL | Traza nativa valida writer/XRCE/peer; 8076 retiene propietario parcial pero agotó búsqueda; no unicidad completa | `socket_inventory._owners`, `match_peer`, `analyze_series`; contrato de presupuesto preparado sin despliegue | Una futura sesión autorizada con todas las barridas/referencias completas, propietarios no ambiguos y Status dentro de cobertura. Socket es candidato visible, no origen probado de cada paquete |
| 2. SYSID efectivo | argv --sysid 3 y código AP_DDS explican configuración; no respuesta de parámetro efectivo | `rover_identity_inventory.collect_inventory` busca servicio público GetParameters único; `RosGraphInventoryReader.get_parameters` devuelve UNKNOWN, no cliente implementado | Descubrir una interfaz pública compatible y leer su valor en el proceso/instancia ya vinculados; si no existe, preparar otra fuente efectiva documentada. No derivar desde ClientKey/argv ni inventar un servicio |
| 3. Odometría→bridge/modelo | C++ acredita GID por muestra y candidatos aparte; existen YAML históricos, no vínculo completo en cada sesión | `MotionBinding` en `rover_ros2_adapter`, `rover_identity_inventory.correlate_capture` | Vincular GID observado a proceso bridge, YAML efectivo/hash, dirección/tipos/frame/unidades y plugin/modelo de ESA sesión. Rama independiente de XRCE |
| 4. Lector requerido por adaptador | `NativeRos2Session` callbacks guardan GID por muestra=None; guard devuelve BLOCKED incluso con snapshot coherente | `NativeRos2Session.observe`, `Ros2RoverAdapter.observe`, `RoverEnvironmentGuard.require_motion_source` | Hace falta un lector actual público que suministre el contrato guard+binding y GID por muestra. Colector C++ es pasivo/aislado y NO está integrado. Grafo no sustituye metadatos por mensaje |
| 5. Entrada pública de ejecución | `simulation_mission_executor` admite sólo multirotor; `admit_ground_trial` devuelve OPERATIONAL_ROVER_POLICY_DISABLED | `rover_ground_executor.admit_ground_trial/run_ground_worker`; MCP fuera de este incremento | Revisar integración pública separadamente después de identidad/transporte/parada; no habilitar cambiando una bandera ni añadir MCP de movimiento aquí |
| 6. Autorización y recuperación | Admisión interna enlaza hashes/alcance, token de uso único, reservas global/v3, persistencia; pérdida worker/parada no confirmada conserva UNCONFIRMED | `rover_ground_executor.query_ground_trial/run_ground_worker`, exclusión y reconciliación existentes | Contrato local de autorización explícita y prueba protegida independiente; recuperación específica auditada ante incertidumbre. Declaración no autentica identidad humana; diagnóstico/disposición histórica no autoriza R1 |

Los cuatro primeros bloqueos se observan en contratos actuales, no se añade una
exigencia de autenticación criptográfica del publicador. Ni socket ni GID prueban
SYSID efectivo. Offline se puede verificar bloqueo/contratos con dobles; no puede
obtenerse una observación actual de parámetros/bridge desde ficheros históricos.
La prioridad inmediata es validar el nuevo presupuesto y cobertura en una futura
prueba autorizada, no ampliar instrumentos o habilitar movimiento por rutina.

### Recepción /3 headless a4e77c9e — cierre de análisis 2026-10-26

Evidencia de la misma sesión, sin mezclar las capturas anteriores:
[4ac58516](../simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728/README.md).
Sus archivos originales y tiempos UTC 25/10 se mantienen. Matriz actual:

| Enlace | Evidencia/resultado | Límite |
|---|---|---|
| Status MessageInfo/GID → writer DDS | 1 muestra, GID010feb7d220601550000000000000f030000000000000000, rmw_fastrtps_cpp; igualdad exacta con traza nativa | Correlación operativa, no autenticación criptográfica |
| Writer → cliente/generación/sesión/objeto | GUID010feb7d220601550000000000000f03; agent PID1570/start1007466; client_instance1, key2902458371, session129, writer14, attempt15, creación confirmada | No se interpreta ClientKey como SYSID; dominio nativo0, contexto consumidor no incluye campo de dominio explícito |
| XRCE → peer UDP | raw127.0.0.1:61852 → normalizado127.0.0.1:40177, contrato fuente UDP/ELF fijado | Números no bastan sin contexto nativo de esa generación |
| Peer → inode/FD/proceso | 6 inventarios repetidos: inode1209928/FD16/PID1598/start1007467, exe ardupilot_sitl/bin/ardurover, net/pid namespace y boot coherentes | 7ª fila incompleta por salida del agente; serie global incierta, no asociación atómica/continua certificada |
| Instancia → SYSID efectivo | argv --instance2/--sysid3 observado en metadatos permitidos | Es configuración, NO parámetro efectivo ni identidad desde similitud numérica |
| Odometry/GID → bridge/modelo | 19 muestras GID010feb7d3c06f84c00000000000014030000000000000000, frames odom/base_link; candidatos del grafo separados | Falta acreditar proceso bridge/YAML/modelo efectivo y transformación, rama independiente de XRCE |

Status cae dentro del span de inventarios; los instantes entre lecturas no son una
instantánea atómica. Se analiza toda la serie, incluidos ENOENT y contexto faltante.
La normalización/match no se cambió para encontrar este socket. El match actual
no explica retroactivamente los cero inodes de 0f678646 (tablas completas no retenidas).

Siguiente eslabón mínimo para SYSID: lectura efectiva en el proceso ya asociado,
con interfaz pública/procedencia comprobadas. El código local GCS::init/update_send
asigna mavlink_system.sysid desde su parámetro runtime, por lo que un header de
telemetría MAVLink pasiva sería una vía a revisar SI se acredita también su socket
al mismo PID y el contrato del binario. No se conectó receptor nuevo, no se pidió
parámetro ni se ejecutó servicio para ello. No es todavía una interfaz implementada.
Para la rama odometría, primero debe acreditarse el GID como publisher del proceso
bridge y su configuración/modelo activos, no sólo nombre de nodo/topic ni parecido
con un spawn. No se añade instrumentación nueva en esta tanda.

La odometría conserva pose/quaternion/twist/covarianzas/relojes sin campos no finitos;
no prueba reposo, frame físico ni transformación. Covarianzas cero significan datos
declarados, no certeza. Identidad completa y movimiento siguen BLOCKED.

## Lectores, fuentes y marcos — implementación offline 2026-10-26

Esta ampliación sustituye el estado de preparación de los lectores descrito más
arriba, no los resultados históricos. No hubo otra disposición/apertura/captura.
Las 119 entradas de 4ac58516 se mantienen intactas. Se verificó actualmente el
mismo EngineID/contenedor/imagen, running y StartedAt 2026-10-25T17:13:38.169790336Z;
eso no es un precheck de procesos/reservas ni consentimiento de arranque.
Las consultas fueron archivos concretos, sin nodos ni servicios ROS.
[Rutas, hashes y momentos de cada lectura](../simulation/ros2_gazebo/results/rover_identity_preparation_2026_10_26/c45ae0d8-5515-40ae-a359-244ac1323822/source-readings.json).

| Rama | Contrato/source comprobado | Observación y límite |
|---|---|---|
| Status | AP_DDS_Client.cpp, update_topic(ardupilot_msgs_msg_Status&): vehicle_type del firmware; DDS_USE_NS selecciona v3, AP_DDS_Topic_Table registra status | El GID real se enlazó al writer y al contexto XRCE y hay seis candidatos /proc repetidos de ardurover. /3 conserva metadatos de Status, no su payload completo; no inventar armed/vehicle_type de esa muestra |
| Odometry | robots/wildthumper.launch.py selecciona models/wildthumper_with_lidar/model.sdf; éste declara OdometryPublisher, odom/base_link, dimensions=3 | Es el modelo configurado por esta fuente, no r1_rover. No demuestra que el publisher recibido fuera ese proceso/plugin/modelo en el ensayo anterior |
| Bridge | wildthumper_bridge.yaml: /model/{{ robot_name }}/odometry → odometry, nav_msgs/msg/Odometry, gz.msgs.Odometry, GZ_TO_ROS; robot.launch renderiza/selecciona configuración | El YAML instalado es plantilla, no el temporal efectivo. No se conservó ese temporal de 4ac58516; los de 40e8c751 son de OTRA sesión |
| Conversión bridge | ros_gz_bridge/src/convert/nav_msgs.cpp copia header/pose/twist y child_frame_id; la sobrecarga gz.msgs.Odometry no asigna covarianzas | No rota vectores ni convierte coordenadas. Covarianzas ROS cero son compatibles con campos no suministrados por esa sobrecarga; no son incertidumbre física cero |
| Órdenes | NativeRos2Session usa TwistStamped /ap/v3/cmd_vel y ModeSwitch/ArmMotors tipados. AP_DDS_Client despacha a AP_DDS_External_Control; Rover/AP_ExternalControl_Rover consume velocidad y giro | Un publish sólo confirma retorno local. Una respuesta de servicio positiva no confirma estado físico. El enlace de Status no atribuye el suscriptor ni el servidor de servicios |

### SYSID efectivo: lector preparado, valor no consultado

Defecto confirmado del lector previo: pedía SYSID_THISMAV. En esta versión
Rover/Parameters.cpp conserva el comentario «SYSID_THISMAV was here» y migra el
parámetro antiguo a MAV_SYSID. GOBJECT(_gcs,"MAV",GCS) y GCS.cpp _SYSID registran
MAV_SYSID. GET_PARAMETERS en AP_DDS_Client.cpp usa AP_Param::find/get(), no set().
Por tanto el conjunto mínimo corregido es **MAV_SYSID y DDS_USE_NS**; NOT_SET queda
desconocido, sin fallback al argv, ClientKey o valores por defecto.

`rover_identity_inventory.read_identity_parameters` usa GetParameters público,
una única petición, forma/tipos/rangos estrictos, deadline POSIX y timeout del
future, cancelación local y destrucción del cliente. No lo ejecutamos ahora.
`RosGraphInventoryReader(...,parameter_transport=...)` es opt-in; el lector de
grafo por defecto sigue sin crear clientes ni hacer spin. Revalida el nombre/tipo
descubierto antes y después. Un nombre único NO prueba un único servidor.

Uso futuro en un nodo de lectura ya poseído, ocioso y autorizado, sin spin
concurrente ni creación de otra ruta CLI/MCP:

```python
from functools import partial
from tools.rover_identity_inventory import (
    RosGraphInventoryReader, read_identity_parameters, collect_inventory,
)
reader = RosGraphInventoryReader(node,
    parameter_transport=partial(read_identity_parameters, node))
report = collect_inventory(reader, timeout_s=2.)
```

El valor sería una lectura efectiva del **servidor que respondió**, no aún de la
instancia PID1598 histórica. El future público de rclpy no entrega su GID ni PID.
Falta ligar el replier GetParameters al mismo cliente/generación XRCE y registrar
el request/reply correspondiente. No exigir a rclpy un dato inexistente ni usar
el nombre v3 como sustituto. La instrumentación nativa de repliers/request-reply
necesita revisión y build antes de prometer ese enlace; no se ha implementado ni
ejecutado en esta tanda. La petición preparada sólo lee, nunca cambia parámetros.

### Verificador de configuración y observación mínima del bridge

`verify_bridge_observations` reutiliza el inventario: compara el GID de la muestra
con el endpoint de descubrimiento, exige contexto de sesión/entorno y procedencia
en todas las lecturas, PID/start_ticks/boot/argv estables, params file seleccionado
por argv, YAML efectivo, dirección/tipos/topic y plugin/frames del SDF. Rechaza
mezclas de sesión, plantillas, PID cambiado, GID ausente, duplicados y contradicciones.
Devuelve cadenas de **configuración observada**, siempre BLOCKED. No crea un
MotionBinding acreditado ni convierte un candidato del grafo en PID.

El siguiente dato mínimo para GID→proceso sería un registro emitido por el propio
bridge desde su objeto publisher (contrastar get_gid público de rclcpp con los
headers instalados antes de instrumentarlo), asociado a su
PID/start_ticks/boot y a la ruta GZ→ROS que crea. No inferir PID del GUID ni añadir
una bandera manual verified. No existe todavía ese emisor en el bridge instalado:
es una pieza pendiente concreta, no algo que una lectura del grafo pueda resolver.
Para modelo falta la identidad de la entidad/plugin instanciados y su configuración
efectiva, ligada al publisher de Gazebo; TopicInfo/configuración/nombre solos no
constituyen ese enlace. La recepción de odometría sigue siendo una rama distinta
de XRCE, aunque ambas transcurran en el mismo contenedor.

### Marcos y prueba independiente del integrador

Odometry.msg instalado especifica pose en header.frame_id y twist en
child_frame_id. Así, nominalmente, la posición recibida es de odom y las
velocidades de base_link. El texto del mensaje es contrato; no acredita que el
plugin instalado lo cumpla. No se encontró su implementación/header en la ruta
inspeccionada. Origen efectivo de odom y marco calculado de twist por ese plugin
quedan pendientes de revisar contra su fuente/versión exacta; no se usan spawns.

AP_DDS_ExternalControl.cpp acepta base_link: x adelante, z arriba y giro ROS CCW;
transforma la velocidad a NED por AHRS y niega angular.z. Rover convierte NED de
vuelta a cuerpo y rad/s a centigrados/s. En este incremento sólo se permiten
linear.x y angular.z; no se extrapola la rama lateral ni se habilita reversa.
Para orientación plana ROS, yaw es CCW desde x; compass NED = pi/2 - yaw.

Las 16 pruebas de orientaciones/objetivos usan el método C++ real de AP_DDS,
hash 69fdcd83…, compilado localmente con tipos/AHRS sustituidos, y expectativas
ENU/NED independientes del integrador Session/Clock. **No es build/link del
firmware ni ejecución ROS**. Otras pruebas validan quaternion/yaw y rechazan
map↔odom implícito y cm/s. La comprobación de quaternion 3D pertenecía al rechazo
antiguo; la revisión geométrica posterior de este mismo día sustituye esa
simplificación por proyección longitudinal, bajo el gate de marco existente.
No acredita pendiente, modelo o transformación por coincidir y≈−3 con el spawn.

La [única medición futura propuesta](../tools/rover_xrce_trace/README.md#medición-futura-conjunta-fuentes-y-transporte--2026-10-26)
separa estos datos resolubles de las piezas nativas pendientes. No está autorizada.

## Dos ramas y su relación física — actualización geométrica 2026-10-26

La actualización del sistema multiagente se contrastó con la primera muestra original, sin
cambiar sus informes. Véase [la corrección de rumbo y sus pruebas](rover-control.md#rumbo-con-inclinación-corrección-posterior--2026-10-26).
Una quaternion válida inclinada no necesita satisfacer qx=qy=0 para tener rumbo
horizontal. Esa corrección matemática no resuelve el modelo ni el origen de odom.

```text
AP_DDS de SITL → cliente XRCE → writer DDS Status → MessageInfo(Status)
Modelo Gazebo/OdometryPublisher → topic GZ → bridge → MessageInfo(Odometry)
                       ↑                  (rama DDS distinta de XRCE)
SITL JSON/FDM ↔ UDP ↔ ArduPilotPlugin del modelo

Control/probe/servicios → AP_DDS de la instancia SITL correcta (vínculo propio)
Objetivo en marco origen → transformación acreditada → marco de observación
```

SYSID identifica la instancia del autopiloto, no el publisher de odometría. No se
debe forzar GID→modelo→SYSID como una cadena única. Las ramas se relacionan por
el enlace FDM del modelo con SITL, además del marco común que use el objetivo.
El enlace de Status no acredita automáticamente el destino de cmd_vel o de un
servicio; la fuente de odometría tampoco acredita el servidor de parámetros.

Avance concreto en la rama modelo: `read_rover_model_description` prepara una
consulta pública **sólo de lectura**, descubierta por nombre/tipo, a
/rover1/robot_state_publisher/get_parameters para robot_description. No se ejecutó.
Reutiliza el transporte tipado de lectura de parámetros: una petición, deadline,
destrucción del cliente y rechazo de forma/tipo/XML/presupuesto. Requiere SDF,
conserva bytes/hash/procedencia/recepción, y deja runtime_instantiation_verified=False.
Su máximo de datos reutiliza los 256 KiB del presupuesto de registro existente.

Esto importa porque la fuente disponible robots/robot.launch.py usa:

1. SDF seleccionado → robot_desc, con sustitución de fdm_port_in para la instancia.
2. robot_state_publisher recibe robot_description=robot_desc.
3. ros_gz_sim create recibe `-topic robot_description -name <robot_name>`.
4. El bridge recibe su propio YAML renderizado mediante config_file.

Por tanto el SDF instalado no basta para conocer los bytes publicados al spawn.
Leer el parámetro contemporáneo ayuda; no demuestra que una creación anterior
usara esos mismos bytes ni identifica por sí solo la entidad. No se debe sustituir
el lector por una búsqueda retrospectiva de ficheros temporales de otra sesión.

La fuente calcula fdm_port_in=9002+10*instance: 9022 para instance2. En el log
original de 4ac58516 figura JSON control interface 127.0.0.1:9022. Son configuración
y salida del proceso observadas; la igualdad de puertos NO acredita la asociación
de sockets/plugin/modelo. Harían falta la descripción efectiva usada por el spawn,
la entidad/plugin instanciados y las lecturas FDM correspondientes en la misma
sesión/net namespace con propietarios completos. Ninguna de ellas se inventó.

Primeras piezas todavía pendientes, con puntos concretos:

- **Odometry GID→bridge:** el hook factible está en
  ros_gz_bridge/src/bridge_handle_gz_to_ros.cpp, StartPublisher, después de asignar
  ros_publisher_. Debe obtener el GID del publisher real y su ruta/configuración,
  junto a identidad del proceso; requiere contrastar la API y preparar/revisar su
  emisor nativo. El grafo no expone esa relación con PID y no se ha creado tal emisor.
- **SYSID efectivo de esa instancia:** lector MAV_SYSID/DDS_USE_NS ya preparado.
  Falta ligar el replier/request-reply a la generación XRCE correlacionada; no
  aceptar un valor desde un alias público como prueba de la instancia.
- **Objetivo→odom:** cálculo SE(2) implementado y probado; traslación/rotación
  reales siguen sin medirse/acreditarse. No hay nueva bandera VERIFIED.
- **Transporte físico:** factory preparado y probe().session_id probado con
  dobles; falta guard de fuentes satisfecho y metadatos por muestra en el
  transporte vivo. El callback rclpy sigue sin GID. start_ground_trial físico
  continúa BLOCKED antes de crear la sesión; no se añade otra API al coordinador.
- **Geometría operativa:** rumbo proyectado calculable; todavía falta justificar
  referencia XY horizontal, unidades/origen/modelo y límites de pendiente. Un
  resultado geométrico válido no constituye una autorización para conducir.

## Preparación pasiva de identidad y marcos — 2026-10-26

**Preparado, no autorizado ni ejecutado.** La geometría aceptada no se vuelve a
modificar. La captura /3 `4ac58516-8fad-457e-918e-253483a2d728` sigue siendo
histórica e intacta. Este incremento no cambia MotionBinding, el coordinador ni
los gates. Las ramas de Status y odometría son distintas:

| Afirmación pendiente | Fuente / lector preparado | Asociación y aceptación | Si falta |
|---|---|---|---|
| SYSID efectivo del SITL correlacionado | Único GetParameters público `/ap/v3/get_parameters`, nombres `MAV_SYSID`, `DDS_USE_NS`; `rover_identity_probe` | Criterio inicial revisado el 2026-10-27: hacen falta identidades nativas de petición y respuesta recibida; la igualdad del campo legacy GUID/secuencia no basta. Véase la revisión de RPC al final | UNKNOWN. `--sysid 3` y ClientKey no sustituyen la lectura |
| Muestra odom → publicador → proceso bridge | MessageInfo de cada muestra; instrumentación `PublisherBase.get_gid()` y creación de su suscripción Gazebo en copia de ros_gz_bridge | GID/RMW exactos, mismo PID/start_ticks/boot; maps y ejecutable del overlay comprobados por monitor; ruta/tipos/config selector efectivos | UNKNOWN ante candidatos, mezcla de biblioteca, recreación o contradicción |
| Bridge → entidad/modelo vivo | Catálogo `/world/runway/scene/info` y poses `/world/runway/pose/info`; respuesta `robot_description` separada | Conservar ID/nombre/pose de entidad y ruta efectiva del bridge. Contrastar datos contemporáneos. Ni nombre coincidente ni descripción servida prueban qué instancia de plugin publicó la muestra | **Sigue UNKNOWN para atribución completa** si no hay prueba del plugin/entidad |
| Marco de objetivo POI_A1 ↔ observación | NavSatFix y GeoPoseStamped de v1/v2/v3, odom y poses Gazebo posteriores a Status | Coordenadas, unidades, reloj/origen respaldados; correspondencias separadas de ajuste y validación; incertidumbre y cuantización explícitas; evaluación offline | UNKNOWN si faltan origen común, precisión, clocks comparables o baseline; REJECTED ante contradicción |
| Destino previsto de comandos/servicios | Descubrimiento público de cmd_vel, arm_motors, mode_switch; creación/commit de reader/repliers nativos | Entidades del mismo contexto XRCE de Status y tipos exactos. El grafo es candidato, no atribución por muestra | UNKNOWN si falta contexto. Nunca acredita entrega/efecto de una orden no emitida |
| Sesión y observación pasiva | Descriptor/selection/launch/monitor y PID/start/boot del lector; MessageInfo | `probe_session_id` exacto del lifecycle, root vivo, selección inmutable, monitor fresco OBSERVING y bridge acreditado. Comprobación periódica y al cierre | Fallo/incompleto sin reanudar |

### Fuentes y límites del contrato

AP_DDS_Client.cpp local, `update_topic(GeoPoseStamped)` líneas 653 y siguientes,
lee `loc.lat/lng * 1E-7`, convierte centímetros a metros y documenta su conversión
NED/ENU de orientación. **Mantiene un TODO del marco de altitud**. No inferimos
un origen geodésico compartido por instancias ni usamos altitude para ajustar XY.
Su GetParameters público (líneas 1233–1304) usa AP_Param y devuelve NOT_SET cuando
no encuentra un nombre: no se improvisa una conexión MAVLink ni se modifica ningún
parámetro. El nombre moderno es MAV_SYSID; no se cambia a SYSID_THISMAV por tanteo.
La correspondencia fuente/binario del firmware debe mantenerse diferenciada de
una respuesta efectiva futura.

La copia diagnóstica añade registros `TFG_IDENTITY_TRACE` sin payloads, apagados
por defecto. Scope de ProxyClient, objeto FastDDSReplier concreto y SampleIdentity
unen creación, request y reply sin aproximaciones numéricas ni temporales.
`rmw_request_id_t.writer_guid` **no es una identidad de servidor**. Se conserva
como metadato público recibido; **la revisión del 2026-10-27 invalida la unión
inicial por igualdad con el campo legacy de la traza**. No identifica por sí solo
al servidor ni la respuesta nativa. Si faltan las identidades por respuesta, el
resultado permanece UNKNOWN; véase el contrato y la limitación al final.

Humble instalado permite `Client<GetParameters>::take_response(Response&,rmw_request_id_t&)`
y `PublisherBase.get_gid()`. El cliente se crea en un callback group público con
`automatically_add_to_executor_with_node=false`: el executor no consume esa
respuesta antes de la lectura explícita. Cada consulta se envía como máximo una
vez, únicamente tras descubrir el servicio y tipo exactos, con deadline de 2 s;
se elimina el pending request al terminar/caducar. Los tres únicos clientes son
GetParameters. No se construyen clientes de modo/armado ni publishers de velocidad.
Crear/cerrar este lector no llama al adaptador de control.

El header público **gz-transport 13 MessageInfo** inspeccionado sólo ofrece
Topic, Type, Partition e IntraProcess: no un identificador del publicador por
muestra. Por ello un catálogo Scene, un topic y `robot_description` **no cierran
por sí solos** plugin→entidad. Los IDs del catálogo y las poses permiten comprobar
correspondencias y contradicciones; si falta una atribución pública compatible,
se necesitará instrumentación pasiva del plugin/servidor acreditado. No se añade
una bandera que salte esa carencia. La propuesta actual puede resolver GID→bridge
y SYSID efectivo; no promete resolver todos los enlaces en una sesión inmóvil.

### Prueba numérica de transformación

`tools/rover_passive_validation.py` implementa ECEF WGS84→ENU horizontal,
cuantización conservadora de media celda y ajuste SE(2) con **dos anclas** y al
menos una observación independiente retenida para validación. Exige referencias
para fuentes, precisión, resolución y comparabilidad de clocks; no sólo igualdad
de recepción. Propaga también incertidumbre de las anclas y del ángulo hasta cada
punto de validación. Un residuo de ajuste cero no valida nada por sí solo.

Sin baseline distinguible del error no se observa yaw/escala; repetir una posición
quieta o su jitter cuantizado no crea ese baseline. Varias referencias aéreas sólo
sirven si se demuestra su relación con el mismo marco/origen: sus spawns no son
calibración. GeoPose con resolución 1e-7° tiene una celda de orden centimétrico,
pero eso **no es exactitud**; NavSatFix COVARIANCE_TYPE_UNKNOWN o covarianzas cero
no suministran una cota de error. POI_A1 necesita además fuente/resolución propia.
No se fija 0,5 m: el error exigido se declara en el dataset y se rechaza si la
cuantización/incertidumbre lo impide. Cero o valor desconocido sin respaldo no
pueden justificarse como precisión certificada.

El resultado máximo es NUMERICALLY_SUPPORTED_ONLY; `frame_transform_verified`
siempre sigue false. Vertical, datum de altitud y extrínsecas 3D quedan fuera de
esta comprobación. No alimenta automáticamente MotionBinding ni el executor.

### Lectura del resultado futuro

El nuevo formato `tfg.rover-passive-validation/1` es separado del diario histórico
/3. `read_journal` exige header, footer, recibo durable, conteos y misma sesión.
`analyze_reader` exige además monitor CLOSED/capture_complete, mismo boot y ventana
del lector dentro de la del monitor. Une ramas con identidades exactas, nunca con
candidatos del grafo. `transport_routes` informa destinos nativos previstos, sin
atribuir efectos. Sus fixtures son sintéticos y no acreditan disponibilidad real.

Las muestras son **retenidas con cuotas**, no una medición de frecuencia/pérdida
del flujo. Tras el primer Status: 3 odom, 2 NavSatFix por instancia, 2 GeoPose por
instancia y 4 mensajes Pose_V (cada uno puede incluir los tres modelos); con Status
suman 20. Antes de ese Status se cuentan omisiones, sin consumir almacenamiento.
Faltas de streams, timeout de una lectura o metadatos no finitos quedan visibles;
un footer/recibo de cierre no equivale a cobertura de todas las pruebas.

Verificación de esta preparación: **195 tests offline pasados en 7.02 s**,
sintaxis Python/Bash correcta y diff --check sin avisos en código/documentación
nuevos. Los 119 originales verifican tamaño, modo y SHA-256. Build y enlace
reales no incluyen ejecución de nodos. La correlación propuesta es operativa,
no autenticación criptográfica de identidades.

## Ensayo autorizado de identidad — 2026-10-26, f206c00d

Evidencia: [5379b30c-ac91-4cc8-808b-a7c28bb41801](../simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/5379b30c-ac91-4cc8-808b-a7c28bb41801/).
Una apertura **headless** `two_drones_rover`, agente y bridge /2 con hashes exactos.
No hubo reactivación: el contenedor ya estaba activo. No se solicitó ni atribuyó
observación visual. La apertura `f206c00d-b5fd-4ea9-87cf-53f4bbcf872b` terminó
SUCCESS. El capture-window fresco bloqueó **antes del lector**: el monitor había
registrado PermissionError en `/proc/5418/exe` y `/proc/5617/exe`. No se repitió
apertura ni se ejecutó el binario aprobado. No hubo GetParameters ni Scene request.

La parada `6422ae53-3d68-4990-9b7f-4bb927a0a0ed` terminó FINISHED/SUCCESS a
**19:52:58.758186 UTC**. Destino CLOSED. A las 19:52:59 UTC, inventario del
contenedor: owned=[], ambiguous=[], agents=[]; guardas JSON vacías. El monitor
observó la petición de cierre y terminó **INCOMPLETE, rc=1**; su supervisor conservó
`monitor_exit.json` con retorno real. Duró 59,125 s: **no agotó 600 s**, ni presupuesto
de bytes o lecturas. Captura de monitor incompleta y cierre de infraestructura son
resultados diferentes. El campo gui=true de la operación stop es su valor CLI por
defecto; no describe ni abrió una GUI en este ensayo headless.

| Enlace / dato | Resultado de ESTA sesión |
|---|---|
| MessageInfo de Status o odom del lector nuevo | **No observado**: lector omitido, cero muestras retenidas por él, sin journal/footer/recibo suyo |
| Writer DDS de Status → XRCE | **Observado**: agente PID4541/start4241583, generación1, key2902458371, sesión129, writer14, intento16, dominio0, creación confirmada |
| XRCE → peer | **Observado**: 127.0.0.1, puerto crudo12960; normalización respaldada por fuente/ELF a41010. No se cambia para buscar una coincidencia |
| Peer → socket/proceso SITL | **No observado**: dos barridas completas no encontraron inodes relevantes; eso no prueba inexistencia. Tercera lectura perdió `/proc/4541/stat` durante la parada |
| Objeto publicador odom → proceso bridge | **Observado**: get_gid del objeto, PID4567/start4241584, biblioteca exacta, ruta `/model/rover1/odometry` → `/rover1/odometry`, tipos y selector YAML. No es una muestra atribuida |
| Odometría recibida por worker Python existente | **Observada como candidato**: último header2.1s, odom/base_link, pose/twist/covarianzas. GID por muestra=None; no se sustituye con candidato de grafo |
| SYSID efectivo | **No observado**. `Setting MAV_SYSID=3` y argv siguen siendo configuración |
| Destinos previstos del transporte | **Observados en contexto XRCE** reader cmd_vel y repliers arm_motors/mode_switch. No se invocaron ni se observaron sus efectos |
| Modelos/pose Gazebo y referencias aéreas del lector | **No observados**; sin transformación medible ni validación independiente |

Se conservan 152 registros: 84 writer/XRCE y 68 de identidad (incluidos los dos
registros bridge). Sus prefijos pasan el análisis estructural; no se promueven a
captura completa. Sockets: **22.204 bytes**, filas de 9.542/9.546/3.116 bytes y
26/26/8 lecturas respectivamente; dos completas, una incompleta terminal, cero
propietarios candidatos. No se infiere cobertura de Status sin una muestra.
El YAML seleccionado todavía existía tras cerrar y se leyó con SHA-256
`db97010c73c389d1d8e3fbb4712d4e565f94442a478f15429895b35cfe77b093`;
es lectura post-cierre, no una entidad viva reconstruida.

La comprobación fresca bajo exclusión de las **20:14:06 UTC** confirmó ausencia
actual de restricciones, guardas y procesos relevantes, pero el **precheck quedó
BLOCKED** por el historial de este descriptor: “Monitor closure
absent/incomplete/contradictory”. La auditoría anterior pertenece a otro alcance
y no se consume para f206c00d. No se aplicó ninguna disposición ni se alteró el
descriptor. Una futura apertura exige revisar este caso exacto y su soporte de
política; corregir helpers no resuelve administrativamente el historial.

### Corrección acotada posterior y límites causales

`monitor.agents` relee stat cuando exe falla por PermissionError. Sólo ignora la
carrera si obtiene **dos estados Z con el mismo start_ticks de la primera
lectura**. Un proceso vivo ilegible, desaparición sin prueba, PID reciclado o
error de lectura siguen UNKNOWN y bloquean. Los UNKNOWN guardan estados antes y
después para diagnosticar la próxima vez. Es una carrera demostrada con fixture;
**no sabemos si los PID5418/5617 históricos estaban convirtiéndose en zombis**:
el helper ejecutado no conservó esas relecturas. No se reinterpreta su error como
inocuo ni su INCOMPLETE como CLOSED. Tampoco se corrige a ciegas el puerto: las
filas guardaron hash/conteo global y tablas filtradas, no la tabla completa que
permitiría explicar la ausencia de coincidencias retrospectivamente.

### Plugin → entidad sin exigir un identificador inexistente

El contrato público instalado `gz/sim/components/SystemPluginInfo.hh` documenta
que registra los plugins **adjuntos a la entidad al instanciarlos**. Se preparó
`tools/rover_xrce_trace/prepare_model.py` y `model_probe/model_trace.hpp`: copia de
ArduPilotPlugin con hooks en Configure, lectura real de WorldPose de imuLink en
CreateStateJSON y resultado del único sendto JSON existente. No se añade una
segunda conexión, comandos ni publishers. El socket observado es el verdadero
FD de ese plugin; fstat/getsockname dan inode/endpoint y se conserva el destino
que realmente usa sendto. El getter añadido sólo existe en la copia temporal.

Los registros atan generación de instancia, entidad del modelo, cadena de padres
del link, pose/velocidad leídas, transformaciones efectivas al FDM, plugins
instanciados y SDF seleccionado, y generación de estado enviada. No conservan
payload JSON/PWM. Son hasta 32 registros de 4096 bytes, apagados salvo
TFG_MODEL_TRACE=1. El drenaje comparte los 512 registros/2 MiB existentes; no se
amplió ningún presupuesto. Dos estados por instancia son prefijo diagnóstico,
no cobertura de toda la física. Logging puede añadir latencia; no se afirma
igual rendimiento. Las funciones de control y argumentos de sendto se conservan.

La copia **compiló y enlazó**, pero no se instaló, seleccionó, cargó ni ejecutó:
`/tmp/tfg-model-build-20261026-5379-b/libTFGArduPilotIdentity.so`, SHA-256
`b4be39e9daf2cc8927b64bc1356c2eaace1ae5d927b23dce10701100fe1129a4`.
La primera configuración no encontró tinyxml2Config; se usó pkg-config de la
biblioteca ya instalada, sin instalar paquetes. El lector y los cuatro binarios
autorizados conservan sus hashes; este plugin NO se sustituyó por ellos.

Modelo de confianza: namespace/procesos de SITL controlados y artefactos fijados;
se busca **correlación operativa**, no autenticación criptográfica contra un
publicador malicioso. La vía aceptable combina instanciación ECM única, pose real,
configuración/ruta, GID del bridge, sockets/procesos y clocks contemporáneos.
Requiere rechazar plugins duplicados, FD/inode cambiantes y generaciones distintas.
No necesita un GID de Gazebo por muestra. Cuando el topic depende de un default
que no se ha acreditado, sigue UNKNOWN: no se inventa el default ni basta el nombre.

`model_records` y `assess_model_source` verifican ese contexto sin conceder identidad
completa ni alimentar gates. Todavía falta observarlo en ejecución, acreditar el
mapeo de biblioteca del servidor y relacionar el endpoint FDM con el SITL de la
rama XRCE. La configuración del OdometryPublisher y su relación con la muestra
bridge requieren contraste contemporáneo y prueba de marcos. Antes de usar esta
copia deberá integrarse su selección explícita en una revisión posterior; no hay
una ruta manual que pueda cargar un segundo plugin/agente en paralelo.


### Integración posterior a 5379b30c — 2026-10-26

La selección del plugin ya está implementada en el manifest explícito /3 y en
la supervisión de maps/entidades; dejó de ser una pieza pendiente de código.
[Procedimiento actual, cuotas y resultados](../tools/rover_xrce_trace/README.md#integración-offline-revisada--2026-10-26-posterior-a-5379b30c).
No se ejecutó. Los originales5379b30c (84) y4ac58516 (119) conservan su manifest.

| Rama | Lo preparado ahora | Prueba todavía ausente |
|---|---|---|
| Status→DDS→XRCE | Supervisor sólo de identidades conocidas; lector con MessageInfo | Nueva muestra contemporánea y contexto completo de esta selección |
| XRCE→SITL | Inventario global de propietarios independiente; incertidumbre se conserva | Endpoint/inode/FD/PID sin ambigüedad; antes hubo cero coincidencias |
| SYSID efectivo | GetParameters de lectura y unión requester/replier nativa preparada | Respuesta atribuida a la misma generación que Status |
| Odom→bridge | GID por muestra + publisher/subscription en bridge fijado | Nueva muestra y configuración contemporánea del bridge |
| Plugin→entidad→FDM | Selector /3, maps y hooks de la copia compilada/enlazada | Instanciación, pose real y sendto contemporáneos; plugin no cargado hoy |
| Modelo/odom/objetivo | 20slots repartidos con espaciado y trigger tras Status | Clocks, origen, precisión, extrínsecos y holdout independiente resolubles |

El dry-run de disposición para f206c00d dio DRY_RUN_ELIGIBLE a21:19:58UTC,
scope c2fc99db11decea614d00e6936c7eee0e1556c5d4399c3b56c0c9dfd7825160e.
No se aplicó y el historial sigue bloqueando otra apertura. La disposición
propuesta archiva alcance/evidencia de cierre independiente; no altera el
INCOMPLETE ni exige inventar que los PID históricos fueron zombis. Tampoco
concede identidad ni consentimiento de movimiento.

La próxima medición pasiva puede **intentar** resolver esas ramas juntas. La
regla de unión es contexto y fuente exactos, nunca similitud de IDs. No se exige
un GID inexistente en Gazebo: la ruta aceptable combina instanciación ECM,
plugin real, configuración, socket de FDM y bridge atribuido. Falta observarla;
los tests de header/selector/driver no son evidencia de disponibilidad real.


### Medición pasiva e837942d y consumo verificable — 2026-10-26

[Matriz de esta sesión](../simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/requirement-matrix.json),
[análisis reproducible](../simulation/ros2_gazebo/results/rover_identity_trial_2026_10_26/1cb9d86a-659b-4aa8-b7b1-214d2202210f/reader-analysis.json).
Una sesión headless, sin movimiento; no se mezclan GID/PID ni lecturas de5379b30c.
La disposición de f206c00d se aplicó al scope exacto y el precheck dio SATISFIED;
el historial incompleto nuevo no está dispuesto.

| Enlace | Resultado real | Límite |
|---|---|---|
| Status/GID→DDS→XRCE | GID010feb7d231c2ca70000000000000f030000000000000000, agente7203/ticks4988254, generación1, ClientKey2902458371, sesión129, writer14 | Contexto operativo histórico, no identidad criptográfica ni credencial actual |
| XRCE→peer | Raw127.0.0.1:65185; normalizado41470 por contrato native/ELF fijado | Endpoint no identifica proceso por sí solo |
| Peer→inode/FD→SITL | No observado; cero filas relevantes | Helper antiguo no probó EOF, sólo fragmentos; tail desconocido |
| SYSID efectivo | Respuesta MAV_SYSID=3, DDS_USE_NS=1 | RequesterGUID nulo; GUID de request/reply nativos distintos. AtribuciónUNKNOWN |
| OdomGID→bridge | Tres muestras con GID010feb7d3d1c6d3700000000000014030000000000000000, bridge7229/ticks4988256 y SO fijado | No completa modelo/default ni confirma reposo |
| Plugin→entidad→pose/FDM | Proceso7200/ticks4988254; instancia2, entidad67 y catálogo/Pose_V concordantes | Verificador consume IDs exactos; no nombres parecidos |
| JSON/FDM | FD35/inode4441065,127.0.0.1:9022→127.0.0.1:60575 y tres sendto completos | Falta inode/FD/PID receptor del SITL, no inferirlo porpuerto |
| Odom→modelo | ECM muestra OdometryPublisher adjunto al mismo modelo67 | odom_topic omitido: su default efectivo todavía no está acreditado |
| Marcos/objetivo | Dos geopose porvehículo,4Pose_V y poses reales del plugin | Candidato numérico sin origen/precisión/clocks acreditados; no aprobado |

El candidato SE(2) usa dos anclas aéreas y rover de holdout. Sus baselines son
5,547m geodésicos frente a4,000m de mundo; cada ancla deja0,774m de residuo. El
holdout pequeño0,0376m **no valida** ese ajuste. No se inventó tolerancia ni
precisión, ni se usó el spawn como origen. El pulso corporal no usa el objetivo
agrícola: requiere su propio marco/fuentes locales, no la transformación POI_A1.

Las incorporaciones a `analyze_reader`/`correlate_model_entities` están probadas
con esta entrada real e incompatibilidades sintéticas. Mantienen monitorINCOMPLETE,
identity_verified=false y movement_authorized=false. El arreglo EOF de
socket_inventory.Reader es posterior y no se ejecutó en esta sesión. Los motivos
y estados originales quedan intactos, incluido el retorno1 observado del monitor.

### Revisión offline de enlaces e837942d — 2026-10-27

Esta revisión sustituye los pendientes de default y la regla RPC anteriores,
conservados como historial. No hubo disposición, apertura, captura ni órdenes.
[Informes, fuentes y reproducción](../simulation/ros2_gazebo/results/rover_identity_links_offline_2026_10_27/6d8a775a-7ce5-4a6a-bd08-ba8918fdcdba/README.md).
Los 164 originales de e837942d permanecen intactos.

**RPC: funciones diferentes.** Petición nativa, evento67: writer
`010feb7d6220b32d0000000000000503`, secuencia1. Replier confirmado: objeto5,
intento26, cliente2902458371/sesión129/generación1, agente7203/ticks4988254.
Su reader de peticiones es `010feb7d231c2ca70000000000001f04`; su writer de
respuestas es `010feb7d231c2ca70000000000001e03`. El evento68 conserva este último
GUID en el campo legacy llamado `request_writer_guid`, leído **después** de write.
No debe exigirse igualdad entre el writer de petición y el writer de respuesta.

FastDDSReplier::read entrega `SampleInfo.sample_identity` al payload XRCE; AP_DDS
devuelve esa identidad delante del resultado GetParameters. FastDDSReplier::write
la deserializa en `WriteParams.related_sample_identity` antes de escribir.
La identidad propia de la respuesta es otra: writer de respuesta + su secuencia.
La identidad relacionada vincula la petición. Secuencia1 no es única globalmente.
`MessageInfo.publisher_gid` identifica al writer de una muestra de topic, no al
reader del servicio ni a la pareja de identidades RPC.

Se contrastaron fuentes fijadas XRCE/AP_DDS, headers y ELF instalados:
rclcpp16.0.19, rcl5.3.13, rmw_fastrtps6.2.10, Fast DDS2.6.12; sus versiones Debian,
hashes y extractos están en `native-source-bundle.json`/`local-source-excerpts.json`.
El take_response público recibió GUID nulo/secuencia1. El desensamblado de
__rmw_take_response copia secuencia/timestamps sin copiar writer_guid. El nulo
**no demuestra ausencia de emisor**. No se encontró el .cpp del cliente RMW en las
fuentes locales inspeccionadas; no se extrapola otra versión para sustituirlo.

`inspect_rpc_exchange` recupera creación/commit/request/reply del contexto nativo
real, sin atribuir los valores al lector. `correlate_parameter` ya no acepta la
unión legacy, ni siquiera con GUID no nulo coincidente. MAV_SYSID=3/DDS_USE_NS=1
son valores recibidos con atribución UNKNOWN. Esa atribución no es recuperable
de los campos conservados; tampoco basta que sólo hubiera un servidor.

La instrumentación nueva `rpc_metadata`, apagada por defecto, copia por valor la
identidad relacionada **antes** de write y conserva ambas identidades de salida
después de write, con los GUID del replier. La receta se aplicó a una copia nueva
de fuentes fijadas; el template compiló con headers Fast DDS reales, `-S`, sin
enlace/ejecución. No se reconstruyó ni desplegó el agente. `correlate_rpc_v2`
comprueba esas identidades contra metadatos nativos **sintéticos** del cliente.
Falta todavía localizar/preparar el punto nativo compatible que capture
SampleInfo por respuesta y lo vincule al cliente/petición. La API pública actual
del lector no lo ofrece. Repetir el lector actual no resolvería ese bloqueo.

**Default de odometría resuelto.** `odom_topic=null` significa configuración
omitida. El log original, actor gz sim-1/PID7196, padre del servidor7200, conserva
a línea431 `/model/rover1/odometry` y a línea434 OdometryPublisher cargado en67.
ECM confirma una instancia; catálogo/Pose_V acreditan el ID; bridge7229 conserva
suscripción y GID exactos de las tres muestras. `correlate_odometry_model` consume
esas pruebas: `ODOMETRY_BRIDGE_TO_INSTANTIATED_MODEL_ROUTE_OBSERVED`. No se une por
orden temporal ni por coincidencia con el spawn. El ELF actual de Gazebo8.15.0
respalda la construcción del default; su hash actual no se atribuye a maps
históricos que no lo registraron. No hace falta otra captura para ese default.

Pose en `odom`, twist en `base_link`, dimensions3, quaternion xyzw: contrato ROS
Odometry y frames/configuración recibidos. La orientación describe el cuerpo en
el marco de pose; unidades declaradas metros, segundos, radianes. Frecuencia
omitida es otro asunto: la cuota retenida no mide la cadencia del flujo completo.
Las velocidades retenidas cero no validan signos de twist no nulo, extrínsecos,
precisión, pendiente ni reposo físico.

**FDM es otro transporte.** Plugin67 envió realmente desde FD35/inode4441065,
127.0.0.1:9022 a127.0.0.1:60575. SIM_JSON configura un socket no bloqueante sin
bind explícito, envía controles al plugin y recibe FDM por ese socket, cuyo
puerto efímero puede asignar el kernel. SocketUDP usa htons/ntohs: no se aplica
la corrección XRCE raw65185→41470 a ese puerto FDM. El inventario histórico sólo
buscó XRCE y no probó EOF. Receptor FDM y peer→SITL siguen sin observarse.

SocketRecorder añade ahora destinos de `fdm_send` exitosos al mismo scope y ata
el proceso del modelo al contexto antes/después. Se buscan **todos** los posibles
propietarios, sin filtro por nombre, en dos barridas. `match_fdm_receiver` exige
EOF, localidad acreditada, socket único, filtro remoto compatible y el mismo
SITL identificado por XRCE en **esa fila**, con PID/ticks/boot/ns. Remoto no
acreditado, compartido, dual-stack, desaparición o cambios quedan UNKNOWN.
`analyze_reader --sockets` lo consume a través de `analyze_series`, manteniendo
ventanas locales y pérdida terminal separadas. Incluso una coincidencia futura
observaría propiedad de socket, no recepción de payload ni SYSID efectivo.

**EOF y coste medido.** Cada archivo se consume hasta read=0, contando cada
llamada. Un fragmento corto terminado en newline no es EOF. Truncamiento, errores
y agotamiento impiden acreditar asociación. Del fixture ejecutado se conservaron
1182eventos lógicos, **1292llamadas físicas** con EOF y146972B: margen756lecturas
y115172B frente a2048/256KiB. No es medición de topología ni latencia real.
Los1182eventos/142890B anteriores no contaban así las llamadas físicas. La
propuesta antigua1280/160KiB ya no cubre1292lecturas; además64×160KiB=10MiB no
cabían en8MiB (51filas completas). Actualmente64×256KiB=16MiB; la admisión sigue
reservando trace/lector/cierre dentro del agregado. No se cambiaron límites.

**Cierre.** Monitor INCOMPLETE/rc1 a21:59:41UTC; cleanup SUCCESS a21:59:52,959991UTC.
El monitor duró183,946s: no agotó600s. SIGINT también alcanzó al monitor e inició
su plazo10s, mientras cleanup podía escalar durante20s. La corrección mantiene
observadores conocidos sin señalarlos junto a las raíces: cleanup publica
petición scoped y resultado de infraestructura; el monitor drena hasta ese
resultado y comprueba salidas; su padre conserva el wait real. Todo usa los20s
**totales** existentes. Fallos, pérdida de owner/observación, reemplazo o servidor
persistente siguen incompletos. Los errores diagnósticos se informan separados
del cierre físico. Copias antiguas conservan el protocolo antiguo; no se retocó
la sesión terminada ni su recibo. Tests recorren supervisor/monitor/cleanup con
procesos simulados; falta comprobar esa coordinación en ejecución real.

Primer bloqueo antes de otra medición: preparar el hook nativo exacto del cliente
RPC. Luego harían falta propiedad contemporánea de FDM/peer con EOF y cierre
coordinado observado, sin repetir el default resuelto. No hay apertura preparada
automática ni autorizada. Identidad completa y movimiento siguen **BLOCKED**.

### Contraste de puerto y revisión independiente — 2026-10-27

Se incorporó la [revisión del sistema multiagente](../evaluation/observability/agri_r1_identity_review_2026_10_27/README.md)
sin modificar sus archivos. Su revisión actual ya rectifica la geometría plana y
la distinción bruto/derivado; se contrastó con el código de las versiones citadas.

| Dato de e837942d | Procedencia | Resultado y alcance |
|---|---|---|
| Bruto | `container-capture/trace.log`, writer/commit Status, agente7203/ticks4988254 | `127.0.0.1:65185` es el entero nativo registrado, no una lectura host-order del endpoint kernel |
| Representación | UDPv4AgentLinux.cpp, SHA-256 `0d3d11252c58b65c85762390b5c79f72a2b9f4efdae6547b09da43a611a96217`, recv_message líneas197–198; IPv4EndPoint.hpp constructor/get_port | sin_port se copia sin ntohs y el getter devuelve ese uint16_t sin transformación; el helper de traza conserva ese entero |
| Ejecución concreta | `start-operation/operation.json`, `artifacts-result.json`, `known-process-observation.stdout` | Wrapper `eedd3756864cbc26fd30f14a0fcf7c46e21a9f5b3712b17a9826ced7d373c099`, biblioteca mapeada `2b18ce9acc46305c48b2708de52218efc688cfa3a927e37ac9c8e7a752b40828`; ELF observado little-endian en la misma sesión |
| Conversión | `normalized_udp_peer`, contrato de fuente fijado y orden del ELF |65185=0xFEA1; sus bytes little-endian son A1 FE; interpretados como puerto en orden de red dan41470=0xA1FE. No se ensayan dos interpretaciones para escoger una coincidencia |
| Normalizado derivado | El `declared_peer` de `socket-metrics.json` y scope del helper ejecutado | `127.0.0.1:41470`, **derivado acreditado por ese contrato**, no observación directa de socket |
| Endpoint kernel concordante | `container-capture/sockets.jsonl` completo como archivo | Cero filas/inodes relevantes retenidos;25etiquetas históricas de repetición y2pérdidas terminales. No hubo prueba de EOF; no se concluye ausencia de ese endpoint ni se acredita peer→SITL |

La fuente preparada que produjo esa variante conserva el mismo SHA de transporte;
se contrastó con la copia conservada y el header del endpoint. Son contratos de
implementación reutilizables, no muestras/GID de otra sesión. La procedencia de
build y las observaciones ELF/maps son correlación operativa, no una atestación
criptográfica del proceso compilador. No se reconstruyeron ni ejecutaron binarios.

`match_peer` separa ahora `peer_interpretation.raw_recorded`, transformation,
native_elf_byte_order, transport_source_sha256, normalized_derived y
kernel_table_matches. La derivación nunca modifica el registro bruto. Una
coincidencia en un prefijo de tabla puede informarse como tal, pero ya no recibe
EXACT_ENDPOINT_UNIQUE_VISIBLE_PROCESS_CANDIDATE sin EOF de ambas tablas:
TABLE_COMPLETENESS_NOT_ESTABLISHED. La ausencia de filas sigue sin probar ausencia.
Este cambio es del analizador; no se reetiquetaron los informes históricos.

**Traspaso para la matriz del sistema multiagente:**

- Odometry→modelo ya está observado por ruta efectiva e instancia67, consumido por
  `correlate_odometry_model`; no queda pendiente del default ni exige movimiento.
  Las tres muestras de esta sesión no se transfieren al diario /3 del25/10.
- El control acotado **no exige HOLD antes de emitir**: `move_for` pide GUIDED,
  armado/external_control, sin failsafe, dos observaciones progresivas/frescas y
  velocidades iniciales bajo umbral. HOLD pertenece a `stop` y su observación.
  Tampoco el núcleo solo acredita una fuente correcta por estabilidad de una
  tupla; el guard/transporte físico actual permanece bloqueado. Véase el contrato
  mínimo, el objetivo del pulso y la ausencia de circularidad en
  [rover-control](rover-control.md#contraste-con-la-revisión-independiente-de-multiagent--2026-10-27).
- `rover_control.py` actual SHA-256
  `da6527368b6c16d6d2d6f9442d7cb5a0abd14745902e7f6c88a72cdf1c9140bb`
  coincide con la versión corregida que cita el sistema multiagente. `_navigation_observation`
  usa projected_ground_heading; move_for no usa yaw mundial ni gate plano.
  1e-3 es tolerancia de norma al cuadrado, no qx/qy ni pendiente. Dos frases de
  esta documentación antigua se actualizaron; no se cambió el algoritmo.
- FDM receptor y peer→SITL siguen pendientes, usando los lectores EOF existentes.
  No se añade instrumentación paralela. RPC conserva el valor3 sin atribución:
  falta el mecanismo nativo por respuesta del cliente, no «un único servidor».
  El cierre histórico sigue INCOMPLETE; la coordinación nueva permanece probada
  offline, sin modificar recibos ni ejecutar otra apertura.

Datos realmente futuros: metadatos nativos RPC por respuesta tras preparar el
hook compatible; ambas búsquedas EOF del peer/FDM con propietarios y contexto
contemporáneos; resultados del cierre coordinado. Después, para el transporte de
control, un suministro actual de GID por muestra y asociación acreditada local;
el lector C++ histórico no rellena el None del callback Python. La respuesta
dinámica y parada del pulso serían resultados de un ensayo de movimiento
independiente, no pruebas que se exijan haber obtenido de ese mismo pulso antes
de autorizarlo. No se habilitó ni se preparó una apertura automática.
