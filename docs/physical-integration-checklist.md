# Lista de comprobación: el día que se conecten el JetRacer y el dron del laboratorio

**Esta lista no autoriza nada.** Cada operación con movimiento necesita su autorización humana específica.

## Antes de encender

- [ ] Responsable de seguridad presente; zona despejada y delimitada; parada de emergencia física al alcance.
- [ ] Versión del software anotada (commit de cada repositorio) y evidencia de los ensayos SITL equivalentes.
- [ ] Hélices **retiradas** para todas las pruebas de dron sin vuelo. JetRacer con las ruedas en el aire o el motor desconectado.
- [ ] Baterías cargadas e inspeccionadas; cableado revisado.

## Dron (sin vuelo)

- [ ] El enlace MAVLink abre en **solo lectura** (heartbeat, `SYS_STATUS`, `ATTITUDE`, `LOCAL_POSITION_NED`/`ODOMETRY`); no se envía ningún comando.
- [ ] Están identificados el SYSID/COMPID y la versión de firmware (CubePilot/ArduPilot).
- [ ] GNSS Here3+ con fix en exterior; origen del EKF registrado; geo-referencia del sitio medida.
- [ ] Cámara: intrínsecos calibrados (tablero), extrínsecos al `base_link` medidos y relojes sincronizados con el EKF.
- [ ] Detector sobre imágenes reales de cartulinas: tasas de acierto y de falsas detecciones registradas con iluminación variada.
- [ ] Geometría: cartulinas en posiciones medidas; error de posición frente a la σ declarada.

## JetRacer (sin movimiento)

- [ ] Identidad, versión de software y lectura de sensores (`observe()`), sin `execute()`.
- [ ] Fuente de posición disponible y acreditada. Si no la hay, el sistema se queda en `WAITING_FOR_ROVER_LOCALIZATION`.
- [ ] Transformación del marco del sitio a la odometría del rover medida y verificada.
- [ ] `stop()` probado con las ruedas en el aire; watchdog con tiempo máximo comprobado.

## Integración (sin movimiento)

- [ ] Observación real (`PHYSICAL_SENSOR` con `evidence_sha256`) → compuerta de percepción → coordinador → Rover Agent → `rover-execution-request/1`, con el estado `AWAITING_HUMAN_AUTHORIZATION`.
- [ ] El coordinador acepta la fuente real solo después de verificarla; los eventos fuera de orden, duplicados y caducados se comportan como en los tests.
- [ ] La autorización humana queda ligada al `scope_sha256` exacto; las precondiciones del ejecutor, todas en verde, quedan registradas.

## Primer movimiento (solo con autorización específica)

- [ ] JetRacer: velocidad mínima, objetivo a menos de 1 m, timeout corto, monitor independiente y stop listo.
- [ ] Dron: vuelo en exterior con piloto de seguridad, geovalla y failsafes comprobados, misión `.plan` validada.
- [ ] Al terminar: precheck final, evidencia sellada y nada se declara completado sin medirlo.
