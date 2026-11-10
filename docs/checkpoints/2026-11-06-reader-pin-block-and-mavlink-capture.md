# Compatibilidad versionada de reader pins y capturador MAVLink — 06/11/2026

## Alcance y límites

Trabajo local en feature/rover-sitl-first-motion sobre el HEAD 88ab41998. Se implementó y probó el protocolo PRESENT_RESOURCE_READER_SUCCESSOR_V1. No se aplicó una disposición, no se escribió ni migró la auditoría persistida, no se alteraron evidencias selladas, no se abrió una conexión MAVLink real y no se inició SITL/Gazebo ni operación del rover.

## Identidad exacta de los lectores

La auditoría original del lifecycle 891dab60-75f4-4008-b63d-2623ca5221a4 conserva scope SHA-256 92f270fe69e3e9cb15b377f07f8bee9131970a0c4e889607d0838692a65b0d19 y el pin histórico de present_resources.py:

23550ccfd411ed14aa7b24fe44cf7e2ac80e7a9751c526a6ff0c4c99b1d721c7

El lector vigente tiene SHA-256:

5f73e030885eb8118b516e00bd97a3ac7c690458a536e733391d5b20677b4d07

La diferencia se introdujo en d53f508ea312c4cd63d916a31890299ae35a4090. Añade interpretación de estados TCP, identifica TIME_WAIT_COOLDOWN y estados desconocidos y reconoce LISTEN por nombre. TIME_WAIT sigue ocupando el recurso y no se trata como FREE. El commit d53 también cambió temporalmente los esquemas; 42d2835de restauró los valores históricos /1 y /2. El código vigente mantiene esos esquemas y el comportamiento TCP conservador.

Se conservó en reader_compat/present_resources_v1.py una copia inerte, byte por byte, del archivo anterior al cambio. No se importa ni ejecuta como fallback. El validador calcula SHA-256 de los bytes de esa copia y del lector vigente, y rechaza la transición si cualquiera difiere de los dos hashes exactos anteriores.

## Protocolo implementado

La sucesión con cambio de present_resources.py usa PRESENT_RESOURCE_READER_SUCCESSOR_V1. Su enlace contiene:

- Pin y hashes SHA-256 completos anterior y nuevo.
- Commit introductor y razón acotada: clasificación de estados TCP con TIME_WAIT aún no disponible.
- Garantía de compatibilidad explícita con el esquema histórico /1 y wire /2.
- Hash y autorización del predecessor y hashes byte por byte de intent.json y originals.json.
- Revisión de los demás pins solo dentro de la lista ya permitida; no se acepta ningún pin desconocido ni se puede añadir o quitar una clave del inventario.
- Si también cambia el boot, la sucesión conserva la forma original de boot_transition y la identidad del reboot. El protocolo nuevo identifica el cambio de lector sin cambiar los bytes de la forma histórica del subenlace.

Las sucesiones viejas se siguen verificando con su protocolo original. La cadena debe seguir siendo lineal, sin forks, replay ni estado parcial; se recalcula el enlace exacto al leer. Los históricos no se reescriben ni se reinterpretan con el lector nuevo. No se cambió la política de apertura o movimiento: todos los flags de autorización siguen false.

El código está en historical_disposition.py y las pruebas de bytes y esquemas en test_rover_reader_pin_compatibility.py. El helper anterior de propuesta offline queda como comprobación de diseño; la ruta productiva usa el protocolo versionado y el verificador exacto.

## Capturador MAVLink y correlador

tools/rover_mavlink_parameters.py consume una conexión ya inyectada; no abre ni cierra transportes. Solo envía PARAM_REQUEST_READ, sin reintentos ni escrituras. Captura heartbeat con SYSID/COMPID y recepción monotónica, lee AUTOPILOT_VERSION solo si ya está disponible, y registra los PARAM_VALUE con origen, nombre, tipo/índice/conteo y timestamps UTC/monotónicos. Guarda lifecycle, boot, proceso, endpoints, hash del firmware proporcionado y ausencias. No produce una instantánea atómica.

La salida directa mantiene live_read=null porque el capturador no puede certificar que una conexión inyectada sea una lectura real. Se añadió una prueba que pasa la salida sintética al correlador y comprueba que queda UNVERIFIED por NOT_BOTH_LIVE_READS; un mock no acredita parámetros.

## Pruebas finales

En la versión final del cambio pasaron las suites dirigidas:

- Sucesor de consumidor: 47 passed.
- Sucesor de reboot y protocolo de pin: 49 passed.
- Inventario y precheck: 117 passed.
- Compatibilidad exacta de lector, capturador MAVLink y propuesta offline: 23 passed.

Total combinado: 236 passed, 0 failed, 0 errors. git diff --check pasó. Los tests de inventario confirman que TIME_WAIT sigue ocupado; los de sucesor verifican cadena, replay, bytes históricos, pins desconocidos, transiciones truncadas y enlaces alterados.

## Precheck y promoción protegida pendientes

El precheck oficial de solo lectura sigue BLOCKED, sin SATISFIED y sin permiso de apertura. El estado del audit vuelve a leerse como DISPOSED_DIAGNOSTICALLY_INCOMPLETE y las condiciones corrientes observadas fueron verdaderas. El bloqueo restante es que el scope de auditoría persistido aún no contiene la transición nueva: se requiere aplicar un sucesor protegido con autorización humana exacta. No se ejecutó esa aplicación.

El dry-run oficial de sucesor del 06/11/2026, tras completar las pruebas, produjo un candidato DRY_RUN_ELIGIBLE con SHA-256 0100eb541731d50b41cb428fe77aeabc0402654a87111659e5a26829fb70f8bc y protocolo PRESENT_RESOURCE_READER_SUCCESSOR_V1. Esa revisión tiene observación acotada y no autoriza START. Si se decide promoverla, debe autorizarse exactamente ese scope y aplicarse una sola vez por apply-successor-reviewed. Después se requiere un precheck protegido fresco. Ninguna autorización de promoción implicaría autorización de START, ARM, GUIDED ni movimiento.
