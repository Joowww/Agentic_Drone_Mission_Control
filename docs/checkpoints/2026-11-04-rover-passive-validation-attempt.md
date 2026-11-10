# Validación pasiva autorizada: intento detenido antes de leer parámetros

**Resultado: INCOMPLETE. No se autoriza repetir la sesión. Movimiento: NO_GO.**

Se ejecutó una única sesión real `rover_only` headless el 04/11/2026, de 11:00:43 a 11:02:21 UTC, sobre `feature/rover-sitl-first-motion`, código `4d92f9813b0e8860ae2ee35c2a76a120151a02b8`.

Protocolo: [preparación de sesión pasiva](2026-11-04-rover-passive-session-preparation.md).
Autorización: respuesta real de Joel, conservada literalmente fuera del repositorio, para el alcance SHA-256 `e5a1ca01ef382e06eae36bf6b8ea349699ae73bbecfdd398c8fb4af4ead9e95e`. Joel confirmó exclusividad del simulador y de sus componentes compartidos. No se generó ninguna declaración humana ni se aplicó una autorización histórica.

## Ejecución y causa de detención

| Paso | Resultado REAL |
| --- | --- |
| Git y fuentes del alcance | HEAD esperado, workspace limpio, hashes coincidentes |
| Flags | `OPERATIONAL_ROVER_ENABLED=False`, `SITL_TRIAL_POLICY_ENABLED=False` |
| Precheck inmediatamente anterior a START | **SATISFIED**; ejecución igual a la autorizada |
| Único START protegido `rover_only` | **SUCCESS / FINISHED**; owner `467bb89d-6d5c-4563-bfb8-27b926e0c7c5` |
| Readiness | **READY**; rover_01/v3 con status PASS y prearm PASS, Armable |
| MotionBinding nuevo | **BLOCKED** por edad de recepción de odometría al terminar la captura |
| Parámetros efectivos | **NO CONSULTADOS**; el protocolo se detuvo antes de GetParameters |
| Worker y 100 observaciones | **NO INICIADOS** |
| Latencias y sampler de métricas | **NO EJECUTADOS** |
| STOP protegido tras START confirmado | **SUCCESS / FINISHED**; owner `3e358874-a1c6-4892-89bd-c4605aecd320` |
| Precheck final | **BLOCKED**, `Present resources: RELEVANT_LOCAL_ENDPOINT_OCCUPIED` |

La resolución de ambos publicadores concluyó correctamente: `/ap/v3/status` y `/rover1/odometry`, sin entradas pendientes. El colector terminó con rc 0, stderr vacío y cinco odometrías con sellos crecientes. No produjo un binding acreditado: la última recepción tenía **2.726745415 s** al finalizar, por encima de `MAX_SAMPLE_AGE_S=2.0`.

Los cinco tiempos de recepción estaban ordenados y el comando de pose de Gazebo terminó con rc 0. Las cinco posiciones XY coinciden, pero esto no acredita una ventana estacionaria de 100 observaciones ni aporta un estado armado por muestra: el colector de binding no captura el payload de Status ni velocidades. **No se acreditó desarmado/estacionario durante toda la prueba.** Sí se conservó la evidencia de que esta ejecución no envió ningún comando de control.

En el productor actual, el muestreo ROS termina y se destruye el nodo antes del inventario del bridge y de la consulta de pose Gazebo; `collected_wall_unix_ns` se toma después. Ese orden puede consumir el margen de frescura. El registro no descompone los 2.727 s entre esas operaciones, por lo que no se atribuye todo el retraso a Gazebo ni se interpreta como prueba de que dejó de publicarse odometría. No se cambió el productor, el límite ni el binding fallido para continuar.

## Cierre y bloqueo de recursos

El backend del STOP informó `success=true`, `remaining=[]`, `errors=[]`, `unattributed_auxiliaries=[]` y `diagnostic_coordination_errors=[]`.

El precheck final observó:

- `no_container_processes`, `no_host_processes`, `no_restrictions`, `no_guards`, `no_other_sessions`: **true**.
- Lectura completa, contexto, duración, versión de lectores y alcance de recursos: **válidos**.
- `resources_free`: **false**.
- Socket TCP IPv4 local `127.0.0.1:5780`, estado de kernel `06` (**TIME_WAIT**), inode `0`, sin propietarios atribuidos. El extremo remoto era un puerto efímero local.

El significado de `06` se comprobó contra el enum TCP instalado en `/usr/include/netinet/tcp.h`. El socket observado no acredita un proceso vivo del proyecto. El lector conservador lo considera ocupado y su decisión **se conserva como BLOCKED**. No se repitió el precheck para buscar un resultado favorable, no se esperó activamente a su desaparición y no se enviaron señales, limpiaron puertos/locks, reiniciaron servicios o modificaron reservas. Tampoco se arrancó una segunda sesión.

Estado final observado: ambas operaciones lifecycle **FINISHED**, sin lease ni reserva viva; cierre de infraestructura confirmado por su backend, pero **cierre del protocolo de validación incompleto por precheck final bloqueado**. El contenedor no se detuvo ni reinició. Esto no demuestra capacidad de parada de un rover en movimiento.

## Datos que no pueden concluirse

| Magnitud solicitada | Resultado |
| --- | --- |
| `GUID_TIMEOUT`, `ATC_ACCEL_MAX`, `ATC_DECEL_MAX`, `FS_*` efectivos | Desconocidos; no se enviaron las tres consultas previstas |
| Coherencia efectiva con el modelo de frenado | No evaluada; no se sustituyen lecturas por defaults |
| RTT host-worker, procesamiento, jitter y p50/p95/p99 | No medidos; no se abrió el worker |
| Margen IPC de 0.25 s | No evaluado |
| Cadencia real/simulada y RTF | No medidos por el sampler previsto; cinco odometrías no sustituyen esa medición |
| Desarmado y estado estacionario durante 100 observaciones | No acreditados; no se alcanzó esa fase |
| Parada física, sobrevelocidad, frenada y failsafe con movimiento | No ensayados |

## Evidencias e integridad

Directorio nuevo y sellado, fuera del repositorio:

`/home/joelm/TFG/archivo_TFG/rover-passive-2026-11-04.jcpinj4s/`

Contiene el alcance autorizado, respuesta original del usuario, driver, eventos con UTC y reloj host, prechecks anterior/posterior, operaciones y logs originales de START/STOP, readiness, originales y rechazo del MotionBinding, stdout/stderr del colector, resultado e integridad. No contiene parámetros ni observaciones de worker fabricados.

- `SHA256SUMS`: **21 archivos verificados**, cero discrepancias.
- SHA-256 del propio `SHA256SUMS`: `5597e409a44ff0427676c93de081974e562aad3b72853aed2bee8e7d9cf21869`.
- Tamaño del directorio al sellarse: **368137 bytes**, incluido el manifiesto.
- **787 archivos preexistentes protegidos** —runtime y manifiestos históricos— con hashes intactos. Las operaciones nuevas del lifecycle se añadieron en sus directorios nuevos.
- Fuentes del alcance y referencias `main` y Hermes intactas. Ningún cambio de flags, parámetros, manifiestos sellados o código operacional.
- Antes de registrar este informe documental, Git seguía limpio en `4d92f9813`.

El driver se comprobó previamente con **8 pruebas de dobles**, sin ROS/Docker ni flags habilitados: éxito, precheck bloqueado, START UNCONFIRMED sin STOP, readiness fallida, lectura fallida sin reintento, STOP UNCONFIRMED sin reintento, cambio de ejecución sin retargeting de limpieza y ausencia de métodos de control. Estos positivos sintéticos no se presentan como resultados reales. No se repitió la batería general de regresión; el código del proyecto no se modificó.

## Decisiones separadas

1. **Siguiente ensayo pasivo: NO_GO ahora.** Revisar offline el orden y los tiempos del productor de binding; conservar los 2 s hasta justificar cualquier cambio. Antes de proponer otra ejecución, deberá acreditarse un precheck nuevo SATISFIED y requerirse otra autorización: este alcance de una sola sesión ya se consumió. No se afirma que el TIME_WAIT continúe ni que se haya liberado después del registro.
2. **Ensayo específico de failsafe: NO_GO.** Faltan parámetros efectivos, atribución adecuada de su servidor y una captura pasiva completa. Probar pérdida de consignas con el rover moviéndose requiere un alcance operativo propio y autorización nueva; la presente no lo permite.
3. **Navegación de un metro: NO_GO.** No hay evidencia nueva de frenada real, sobrevelocidad, actuación de `GUID_TIMEOUT`, latencias operativas o parada con movimiento. Las hipótesis previas no se convierten en mediciones.
