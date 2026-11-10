# Procedimiento: primera misión multiagente con dos drones en SITL/Gazebo (preparado el 07/11/2026; **no ejecutado**)

Este documento prepara la validación. **No autoriza** ninguna apertura del simulador, armado, despegue ni movimiento: cada paso operativo necesita la autorización expresa de Joel en ese momento. El ciclo de vida del simulador es del subsistema rover (`tools/simulation_lifecycle.py`) y no se toca desde aquí.

**Etiquetas de cada dato:**
- **VERIFICADO-CÓDIGO:** se lee en el código commiteado de esta rama.
- **VERIFICADO-H2:** funcionó en H2, el 24/10/2026, en SITL histórico.
- **REGISTRADO-18/10:** aparece en la evidencia sellada `sequential_preflight_diagnostic_2026_10_18/c6eeb645…`.
- **INFERIDO:** se deduce de lo anterior y hay que confirmarlo en la sesión.
- **PENDIENTE:** no existe todavía.

## 1. Lo que ya está listo, sin ejecutar nada

```bash
python -m multiagent.demo --two-drones --replay-plan --rover-snapshot <dir> --rover-reviewed --out <nuevo dir>
```

| Pieza | Qué produce |
| --- | --- |
| `multiagent/hermes_mission_adapter.py` | Las dos `MissionDefinition`, idénticas byte a byte a las validadas por el Drone Agent; Hermes `FEASIBLE/APPROVED`; `.plan` generado; *binding* `drone_01→v1` y `drone_02→v2` |
| `multiagent/drone_schedule.py` | La agenda: 45 s para drone_01, reproducido. También con la geometría SITL efectiva (los *spawn* del *launch*) sale 45 s |
| `multiagent/drone_execution_bridge.py` + `tools/multiagent_drone_sequence.py` | Las comprobaciones reales de admisión de H2 (`preflight_sequences._inputs`, la compatibilidad del ejecutor y la validación Hermes del archivo escrito). Nombra la llamada exacta `start_preflight_sequence(mission_paths, request_key, authorization_statement)` **sin hacerla** |
| `multiagent/camera_observation.py` | La entrada de cámara (Image, CameraInfo y Pose) hasta la observación en el marco del sitio. Hoy solo con imágenes SINTÉTICAS |

## 2. Configuración comprobada

| Elemento | Valor | Etiqueta / fuente |
| --- | --- | --- |
| Perfil de simulación | `two_drones` → `ardupilot_gz_bringup/tfg_demo_2drones.launch.py`, `rviz:=false` | VERIFICADO-CÓDIGO (`tools/simulation_profiles.py`) |
| Perfil con rover | `two_drones_rover` → `tfg_demo.launch.py` | VERIFICADO-CÓDIGO |
| Modelos y *spawn* | `drone1` en (−2, 0, 0,195) y `drone2` en (2, 0, 0,195), con yaw 1,5708 | VERIFICADO-CÓDIGO (el *launch*) |
| Lógico → interfaz | `drone_01→v1` y `drone_02→v2`, por el orden del *launch* | VERIFICADO-CÓDIGO (`tools/simulated_vehicle.py`, `simulation_profiles.py`) |
| *Namespaces* DDS | `/ap/v1` y `/ap/v2` (SYSID 1 y 2) | VERIFICADO-H2 y *baseline* del 04/10 |
| Estado | *topic* `/ap/{v}/status` | VERIFICADO-CÓDIGO (`tools/ros2_flight_control.py`) y VERIFICADO-H2 |
| Pose | *topics* `/ap/{v}/geopose/filtered` y `/ap/{v}/gps_global_origin/filtered` | VERIFICADO-CÓDIGO y VERIFICADO-H2 |
| Modo, armado, despegue | servicios `/ap/{v}/mode_switch`, `/ap/{v}/arm_motors` y `/ap/{v}/experimental/takeoff` | VERIFICADO-CÓDIGO y VERIFICADO-H2 (**efectos**: solo dentro del ejecutor y con autorización) |
| Objetivo | *topic* `/ap/{v}/cmd_gps_pose` (publicación) | VERIFICADO-CÓDIGO y VERIFICADO-H2 (**efecto**) |
| Aterrizaje | `mode_switch` a LAND | VERIFICADO-CÓDIGO |
| Cámaras | `iris` con `gimbal_small_3d`: un sensor `camera` en `pitch_link`. *Bridge* GZ→ROS `camera/image` (`sensor_msgs/Image`) y `camera/camera_info` (`sensor_msgs/CameraInfo`) en el mundo `runway`. Nodos con `__ns:=/drone1` y `__ns:=/drone2` | REGISTRADO-18/10 |
| *Topics* de cámara | `/drone1/camera/image`, `/drone1/camera/camera_info` y los de `/drone2` | **INFERIDO** (relativo + *namespace*): confirmar con `ros2 topic list` en la sesión |
| Orientación de la cámara | La del gimbal. El nadir exige *pitch* −90°, y eso sería un comando de montura | **PENDIENTE**: no se ha comprobado la orientación por defecto. Mandar el gimbal es un efecto y necesita autorización |
| Transformaciones | `base_link → gimbal_link → pitch_link → óptica`. El `robot_state_publisher` las publica, aunque avisa de que URDF no admite el `<sensor>` | REGISTRADO-18/10; la cadena debe verificarse |
| Marco del sitio | `synthetic_orchard_local`, georreferencia en la ubicación por defecto de SITL (CMAC) redondeada, de tipo **SYNTHETIC** | VERIFICADO-CÓDIGO (`missions/sites/synthetic_orchard_v2.site.json`) |

**La geometría efectiva difiere de la del sitio.** El ejecutor reubica cada misión en la posición de lanzamiento real de su dron (`planning/scenario_instance.py` y el *mapper*), y los *spawn* están a 4 m, no a los 8 m de TAKEOFF_A–TAKEOFF_B. Ya se ha comprobado que la desconflictación da el mismo retraso, 45 s, con esa geometría. Queda por **verificar en la sesión** que Gazebo usa x=este e y=norte, como se supone.

## 3. Cómo se ejecutaría

H2 ejecuta **en secuencia**: el segundo dron solo despega después de que el primero termine con PASSED (aterrizado, desarmado y con su evidencia verificada).

La agenda multiagente encaja en ese modelo: drone_02 termina en el segundo 30,16 y drone_01 sale en el 45, así que el plan ya es secuencial. El modo `SEQUENTIAL_H2` del coordinador lo representa.

La ejecución **concurrente**, con los dos drones en el aire, no la soporta el ejecutor H2. Necesitaría un *backend* nuevo, que no se ha construido.

## 4. Lista de comprobación para el día de la ejecución

**Antes de pedir autorización** (todo sin efectos):
1. `git status` limpio en la rama y el commit anotado.
2. `python -m multiagent.integration_smoke --area two_drones --area plan_input` en PASS.
3. Generar las misiones y la petición en un directorio nuevo **dentro de `missions/`**, en modo `OPERATIONAL` del *boundary*, sin declaración: debe salir `PENDING_AUTHORIZATION`.
4. Revisar a mano los dos `.json` y sus `.plan`: altitudes de 5 m, POI_1 y POI_3, velocidades y retorno.
5. Confirmar con el subsistema rover que no hay ninguna sesión del rover abierta ni ninguna restricción activa (`tools/simulation_lifecycle.py`, del subsistema rover).

**Con autorización expresa de Joel para abrir el perfil `two_drones`:**
6. Apertura protegida por el ciclo de vida del subsistema rover, sin *scripts* antiguos que armen o despeguen (`run_demo.sh` arma y despega: **no se usa**).
7. Lectura sin efectos:
   - `ros2 topic list`: anotar los *topics* reales de `/ap/v1`, `/ap/v2` y de las cámaras;
   - `ros2 topic echo --once` de `/ap/v*/status` y `geopose`;
   - la `CameraInfo` de cada cámara, para ver K y la orientación por defecto.
8. *Readiness* con `check_simulation_ready(profile="two_drones")`: debe salir `READY`.
   - Ejecuta `check_sim.sh` dentro del contenedor: lista *topics* y llama a los servicios `…/prearm_check`.
   - Es una comprobación previa al armado y **no arma**; aun así es una llamada a servicios del vehículo y va dentro de la autorización de apertura.

**Con autorización expresa de Joel para las dos misiones:**
9. La declaración del operador va en `authorization_statement`; es el modelo de H2, declarada y no autenticada. Se llama **una vez** a `start_preflight_sequence` con los dos caminos en el orden de la agenda (`drone_02`, `drone_01`) y una `request_key` nueva.
10. El seguimiento es solo con `get_preflight_sequence`. **Nunca se reintenta un vuelo.**

**Condiciones de aborto** (las aplica el ejecutor H2 y hay que respetarlas):
- un *failsafe* activo;
- un *timeout* de despegue, de *waypoint* o de aterrizaje: 180 s cada uno;
- que el primer hijo no sea PASSED: entonces el segundo no se inicia;
- evidencia o reserva inconsistente: la secuencia pasa a `UNCONFIRMED` y requiere reconciliación;
- cualquier estado `UNKNOWN` en el coordinador temporal.

**Evidencias de llegada:** la tolerancia es 1,0 m horizontal y 0,75 m vertical (`HORIZONTAL_TOLERANCE_M` y `ALTITUDE_TOLERANCE_M`), con el muestreo del ejecutor cada 2 s.

**Evidencias de aterrizaje:** `landed=true` y `armed=false` en el informe del hijo, y el `report.json` verificado por la secuencia.

**Apagado y limpieza:** parada protegida del ciclo de vida del subsistema rover. No se borran *leases* ni se fuerza la limpieza.

## 5. Lo que falta para cerrar la demo con dos drones y un rover

| Falta | Dueño |
| --- | --- |
| Confirmar los *topics* de cámara y su orientación; decidir cómo se acredita la `CameraInfo` del simulador. Hoy el adaptador acepta `CALIBRATED` o `DECLARED_VIRTUAL` solo en `OFFLINE_TEST` | Joel y este lado |
| Una ingestión acreditada (`ACCREDITED_BY_INGESTION`) que lleve la pose y la imagen del dron a `camera_observation` | El subsistema rover o este lado, por acordar |
| Un puerto de eventos del ejecutor H2 hacia `DroneScheduler`. El ejecutor emite progreso (`_emit_progress`) cada 2 s, así que `telemetry_max_age_s` debe ajustarse a ese ritmo | Este lado (diseño) |
| Promover el adaptador del subsistema rover (`ROVER_ADAPTER`) y su gate del rover | El subsistema rover |
| La propuesta mínima para H2: separar `start_preflight_sequence` en `build_sequence_plan` (puro) y la admisión con efectos | Por decidir (no aplicada) |
