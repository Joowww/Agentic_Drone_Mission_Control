# Estrategia de integración física: dron CubePilot y Waveshare JetRacer (preparación, sin conexión)

Este documento está separado de la demo sintética. No se ha conectado nada ni se ha enviado ningún comando.

**Datos declarados:**
- **Dron:** HEXSOON EDU-450; CubePilot (Orange, según el TFG de Joan); Raspberry Pi 5 de 16 GB; MAVLink y MAVProxy; GNSS Here3+; cámaras, con posible Luxonis OAK-D Pro W.
- **Rover:** Waveshare JetRacer Pro con Jetson Nano, motor y servo de dirección, cámara del kit y electrónica experimental.

**No se presupone:**
- en el JetRacer: ROS 2, GNSS, SLAM, odometría fiable, cámara calibrada, API de actuadores ni failsafe;
- en el dron: vuelo autónomo en interiores sin un sistema de posicionamiento comprobado.

## 1. Qué tenemos y qué se reutiliza directamente

| Módulo | Uso físico | Reutilización |
| --- | --- | --- |
| Supervisor, Drone Agent y validadores aéreos | Plan `.plan` (MAVLink mission) por dron | Directa. La subida pasa por la entrada autorizada existente |
| Deconflicción | Separación entre drones | Directa, con la política real declarada (separación e incertidumbre) |
| `card_detector.py` | Detección roja y amarilla en imágenes de la cámara | Directa como primera versión. Hay que validarla con imágenes reales |
| `geometry.py` y `perception.py` | Píxel a marco del sitio | Directa, con intrínsecos y extrínsecos **calibrados** y la pose del EKF |
| `mission_coordinator.py` | Estados, dependencias y bloqueos | Directa. Hoy solo acepta eventos `TEST_FIXTURE` y necesita una fuente real verificada |
| `rover_executor_bridge.py` | Solicitud versionada para el ejecutor | Directa contra el contrato del subsistema rover (`NavigationPlan`, `ExecutionAuthorization`) |

## 2. Adaptadores que faltan

1. **Fuente de pose del dron:** EKF de ArduPilot (MAVLink `LOCAL_POSITION_NED`/`ATTITUDE` o `ODOMETRY`) → `DronePose` en el marco del sitio. Requiere la geo-referencia medida del sitio.
2. **Nodo de cámara:** captura (IMX219 u OAK-D) → `card_detector` → `geometry.build_observation` → `observation/1`. Con un `evidence_sha256` del fotograma y `source.kind = PHYSICAL_SENSOR`.
3. **Profundidad:** el estéreo de la OAK-D Pro W (`depth.source = STEREO`) en lugar de la hipótesis de suelo plano.
4. **Fuente de eventos para el coordinador:** informes del dron (punto alcanzado, heartbeat) desde MAVLink, autenticados. Hoy el coordinador rechaza cualquier fuente que no sea fixture.
5. **JetRacer:**
   - localización acreditada (marcadores visuales, captura de movimiento, o SLAM con la cámara y la IMU);
   - transformación del marco del sitio a su odometría;
   - driver con stop y watchdog;
   - todo ello lo prepara el subsistema rover.
6. **Registro de autorizaciones** por `scope_sha256`, firmado por una persona.

## 3. Qué hay que medir o conocer

- **Cámaras:** intrínsecos y distorsión calibrados con tablero, por cámara y resolución.
- **Montaje:** extrínsecos cámara → `base_link` (CAD más verificación).
- **Sitio:** geo-referencia y orientación del eje y medidas (hoy `PENDING_MEASUREMENT`).
- **Dron:** latencias y sincronización de relojes entre cámara, EKF y Pi 5.
- **JetRacer:** velocidad máxima segura, distancia de frenado y radio de giro (Ackermann), además de la fuente de posición disponible.

## 4. Pruebas sin movimiento (se pueden hacer ya en el laboratorio)

- Capturar imágenes reales de cartulinas en el suelo y pasarles el detector, en distintas iluminaciones.
- Calibrar las cámaras y validar la geometría con cartulinas en posiciones medidas, con el dron en el suelo o sujeto, apagado.
- Registrar la telemetría MAVLink solo de lectura (EKF y actitud) con los motores desarmados.
- JetRacer con ruedas en el aire o motores desconectados: lectura de sensores y del contrato `observe()`, nunca `execute()`.

## 5. Pruebas que necesitan laboratorio y autorización

- **Vuelo en exterior con GNSS:** misión `.plan` subida por la entrada autorizada, con piloto de seguridad y geovalla.
- **Primer movimiento del JetRacer:** a velocidad mínima, en un área despejada, con stop probado.
- **Ciclo completo:** detección real que dispare una tarea del rover pendiente de autorización y, después, una ejecución autorizada.

## 6. Posicionamiento

- **Dron:** el GNSS Here3+ solo sirve en exterior. En interior hace falta flujo óptico, captura de movimiento o VIO comprobados.
- **Rover:** no puede ir a una coordenada sin una fuente de posición acreditada. Hasta entonces el sistema solo **planifica** (contrato `/3` del rover y `WAITING_FOR_ROVER_LOCALIZATION` en el coordinador).

## 7. Funciones aprovechables de la Jetson Nano

- **Visión a bordo:** el detector por color es ligero. Una red de detección (TensorRT) sería una mejora futura y habría que validarla aparte.
- **Odometría visual o SLAM con la cámara:** sería una posible fuente de localización, que hay que acreditar.
- **Ejecutor local** con watchdog que implemente `RoverVehicleExecutor` (subsistema rover).

## 8. Condiciones que faltan para la misión física completa

1. Sitio medido y geo-referenciado.
2. Cámaras calibradas y extrínsecos medidos.
3. Pose del dron fiable en el marco del sitio.
4. Localización del JetRacer acreditada.
5. Driver del JetRacer con stop probado.
6. Fuente de eventos real y autenticada para el coordinador.
7. Autorización humana registrada por alcance.
8. Ensayos en SITL equivalentes superados (primer movimiento del rover, hoy en NO_GO).

La lista de comprobación del día de conexión está en [physical-integration-checklist.md](physical-integration-checklist.md).
