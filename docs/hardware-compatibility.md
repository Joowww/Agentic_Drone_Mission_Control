# Compatibilidad: arquitectura multiagente, ArduPilot SITL, dron físico y JetRacer

**Estado a 06/11/2026.** Documento de planificación: no se ha cambiado ningún software físico ni se ha conectado ningún vehículo.

Cada afirmación lleva su nivel de evidencia:
- **VERIFICADO:** comprobado en este repositorio o por una ejecución.
- **DECLARADO:** lo afirma la descripción del laboratorio o el código de otro agente, sin comprobación propia.
- **DESCONOCIDO:** no hay evidencia.

## 1. Qué produce la arquitectura multiagente (frontera de salida)

La salida es siempre una **propuesta pendiente de autorización** (`movement_authorized: false`, `commands_sent: 0`). Contiene:

| Elemento | Formato | Consumidor previsto | Evidencia |
| --- | --- | --- | --- |
| Tarea aérea por dron | Misión validada más `.plan` de QGroundControl (protocolo de misión MAVLink), construido por `inputs/qgc_plan_export.build_plan` | QGC o MAVProxy hacia ArduPilot (SITL o CubePilot), con autorización humana | VERIFICADO offline: el `.plan` se genera y se valida en memoria (`plan_preview`). Nunca se ha subido a un vehículo desde este worktree |
| Tarea terrestre | Punto de interés declarado del sitio (`target_point`) en el marco local del sitio (`site.local_frame`, ENU rotado, metros), más el punto de inicio declarado del rover | `RoverVehicleExecutor` (contrato del subsistema rover, `NavigationPlan`) | VERIFICADO offline. La traducción a `NavigationPlan` está pendiente (§4) |
| Dependencias | `POI_REACHED` / `COMPLETED` entre tareas | Coordinador de ejecución (no existe en este worktree) | VERIFICADO offline (`integrated_mission`) |
| Observación dron → rover | `tfg.multiagent.observation/1` y su compuerta (`multiagent/perception.py`) | Nodo de percepción futuro (p. ej. OAK-D) | VERIFICADO solo con fixtures |

## 2. Plataformas

| | ArduPilot SITL actual | Dron físico (laboratorio) | JetRacer (nuestro rover físico) | RB-SUMMIT (TFG de Joan) |
| --- | --- | --- | --- | --- |
| Plataforma | Contenedor `tfg-ardupilot-gazebo` (ArduPilot y Gazebo; trabajo del rover, del subsistema rover) | HEXSOON EDU-450 (DECLARADO) | Waveshare JetRacer Pro: Jetson Nano, cámara, servo de dirección y motor eléctrico (DECLARADO) | Robot antiguo, no es nuestro rover |
| Autopiloto | ArduPilot SITL (VERIFICADO en el repositorio principal) | CubePilot/ArduPilot. El TFG de Joan cita CubePilot Orange (DECLARADO) | **No tiene**: tracción y dirección por la Jetson (DECLARADO). Ninguna versión de firmware acreditada | — |
| Enlace | MAVLink (SITL); el rover con DDS/XRCE (el subsistema rover, en NO_GO) | MAVLink por USB hacia la Raspberry Pi 5, con MAVProxy (DECLARADO, TFG de Joan) | DESCONOCIDO. No hay driver configurado (`JetRacerDryRunAdapter`: `position_sources=()`) | MQTT (DECLARADO, TFG de Joan) |
| Middleware | ROS 2 (rover SITL, el subsistema rover) | Raspberry Pi 5 16 GB. ROS 2 no confirmado en el dron | **No se afirma ROS 2.** DESCONOCIDO | ROS 1 Noetic (DECLARADO) |
| Localización | Verdad del simulador / EKF SITL | GNSS Here3+ en exteriores (DECLARADO). **En interiores no hay sistema de posicionamiento comprobado** | **Ninguna fuente acreditada**: sin GPS, encoders o SLAM confirmados | — |
| Cámaras | Las del modelo Gazebo (si las hay) | Cámaras adicionales; posible Luxonis OAK-D Pro W (DECLARADO, sin integrar) | Cámara (IMX219 según el adaptador del subsistema rover; DECLARADO, «UNVERIFIED») | — |

## 3. Qué se reutiliza tal cual

- **Validación y exportación aérea:**
  - `planning/site_validation` (perímetro, exclusiones, altura);
  - `hermes_mission_validation` (batería y viento, con los perfiles declarados);
  - `inputs/qgc_plan_export`, que genera un `.plan` estándar.

  ArduPilot físico acepta el protocolo de misión MAVLink, igual que SITL. Lo que cambia es la geo-referencia del sitio: `site.geo_reference` está pendiente de medición, y sin ella las coordenadas absolutas no son válidas para un vuelo real.
- **Coordinación de enjambre:** `deconfliction` comprueba la separación con una política declarada. En el laboratorio habrá que declarar la política real: separación, incertidumbre de posición y retardos.
- **Compuerta de observación:**
  - una OAK-D (DepthAI) entrega detecciones con XYZ métrico en el marco de la cámara, que se corresponde con `relative_position_m`, o profundidad estéreo con `depth.source = STEREO`;
  - la pose de la cámara saldría del EKF de ArduPilot (MAVLink `LOCAL_POSITION_NED` y `ATTITUDE`), compuesta con la extrínseca de montaje cámara → dron;
  - la compuerta exige pose en el marco del sitio, sincronía de menos de 0,1 s, incertidumbre conocida y evidencia del fotograma.
- **Contrato de vehículo del subsistema rover** (`tools/rover_vehicle_contract.py`, commit `218697f40` en su rama; DECLARADO por su código, solo se ha leído la interfaz): define `NavigationPlan(frame, target_x_m, target_y_m, max_speed_mps, timeout_s)` y `ExecutionAuthorization(human_authorized)`. El `JetRacerDryRunAdapter` rechaza toda ejecución (`REFUSED_DRY_RUN_ONLY`, `physical_effect=False`).

## 4. Adaptadores pendientes (ninguno implementado aquí)

| Adaptador | Qué hace | Bloqueo actual |
| --- | --- | --- |
| Tarea terrestre → `NavigationPlan` | `target_point` → (x, y) del POI en `site.local_frame`. `frame` = el `frame_id` del sitio. Velocidad y timeout vienen de la autorización, no del LLM | Requiere que el ejecutor del rover conozca la transformación del marco del sitio a su odometría. **No acreditada** para SITL (el subsistema rover, NO_GO) ni para el JetRacer |
| Localización del JetRacer | Fuente de pose para el JetRacer: marcadores visuales, captura de movimiento, odometría y SLAM con la cámara… | **Bloqueante.** Sin pose acreditada, el rover no puede ir a una coordenada. `rover_capabilities` lo declara (`accredited_live_localization: false`) |
| Driver del JetRacer | Servo y motor desde la Jetson, con parada y watchdog | No existe. Lo prepara el subsistema rover. **No afirmar compatibilidad con ROS 2** |
| Nodo de percepción en el dron | OAK-D o cámara → `tfg.multiagent.observation/1`, con pose y evidencia | Cámara no integrada. Faltan la extrínseca, la sincronización de relojes y el `evidence_sha256` del fotograma |
| Pose del dron → marco del sitio | EKF de ArduPilot (origen NED) → `site.local_frame` | Falta la geo-referencia medida del sitio y la orientación del eje y (`orientation_verification: PENDING_MEASUREMENT`) |
| Enlace del dron físico | MAVLink USB → MAVProxy en la RPi 5 → QGC o GCS | Solo planificación. La subida de misión exige autorización humana y las entradas existentes |
| MQTT (Joan) ↔ esta arquitectura | Puente de mensajes, si se reutiliza el RB-SUMMIT | No previsto. ROS 1 Noetic queda fuera de soporte |

## 5. Lo que no debe afirmarse

- Que el JetRacer es compatible con ROS 2, o que tiene localización.
- Que el dron puede volar de forma autónoma en interiores. El GNSS Here3+ no sirve en interiores, y no hay flujo óptico, captura de movimiento ni VIO comprobados.
- Que una detección en píxeles da una coordenada global. La compuerta lo rechaza (`NO_METRIC_DEPTH`).
- Que la planificación multi-dron offline equivale a vuelos simultáneos. No hay ninguna ejecución real simultánea acreditada.
- Que el MCP local de planificación es el proveedor remoto Hermes. El proveedor Hermes no se ha ejecutado.

## 6. Camino hacia una misión completa en Gazebo (dependencias, en orden)

1. Rover SITL con primer movimiento acreditado (el subsistema rover; hoy NO_GO).
2. Transformación del marco del sitio a la odometría del rover SITL, acreditada.
3. Adaptador tarea terrestre → `NavigationPlan` → ejecutor SITL, con autorización humana por tarea.
4. Dron SITL con misión `.plan` subida por la entrada autorizada existente.
5. Cámara simulada en Gazebo con una cartulina roja o amarilla, más un nodo de detección que emita `observation/1` con `source.kind = SITL_SENSOR` y pose del EKF SITL.
6. Coordinador de ejecución que respete las dependencias `POI_REACHED` y `COMPLETED`, con parada y supervisión.
