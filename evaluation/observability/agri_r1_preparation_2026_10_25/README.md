# R1 de `agri_demo_001`: contrato y preparación sin control — 25/10/2026

**Resultado de `r1-dry-run` sobre el H2 histórico** ([`r1_dry_run_h2.json`](r1_dry_run_h2.json)):

| Etapa | Estado |
| --- | --- |
| Dependencia | `MET` |
| Elegibilidad | `NOT_ELIGIBLE` |
| Autorización | `ABSENT` |
| Admisión | `NOT_REQUESTED` |
| Ejecución | `NOT_STARTED` |

No se produce ningún candidato de tarea, porque faltan los cuatro datos que lo definen.
`movement_authorized` y `commands_sent` siguen en `false`, y no se ha creado ninguna admisión,
reserva, proceso, socket ni orden. Dos ejecuciones dan una salida idéntica byte a byte.

```bash
.venv/bin/python -m reporting.agri_scenario_summary r1-dry-run
```

## Qué es R1 hoy (lo que existe en el repositorio)

| Aspecto | Contenido | Fuente |
| --- | --- | --- |
| Objetivo | «Ground verification at a declared point of interest». No se define qué observación constituye esa verificación | `GROUND_TASK` en `reporting/agri_scenario_summary.py` |
| Vehículo previsto | `rover_01` (el ejecutor terrestre exige `rover_01`/`v3`, `ugv`, ArduPilot) | `GROUND_TASK`; `tools/rover_ground_executor.py` (Codex, solo lectura) |
| Punto | `POI_A1`, declarado como desplazamiento respecto al lanzamiento de **drone_01** | `missions/examples/agri_demo_001_sector_a.json` |
| Dependencia completa | Vista verificada (hashes del binding) **y** secuencia `FINISHED`/`PASSED` con escenario `AERIAL_COMPLETED_GROUND_PENDING` **y** `POI_A1` `REACHED` por `drone_01` | `summarize_scenario` / `prepare_ground_task` |
| Resultado esperado | **No definido**: no hay observación de posición del rover ni tolerancia terrestre | — |
| Errores y recuperación | Escenario: `NOT_MET` o `UNKNOWN` dejan R1 en `BLOCKED_PENDING`. Ejecutor (Codex): `BLOCKED`, `ADMITTED`, `RUNNING`, `FINISHED`, `UNCONFIRMED` y `NOT_FOUND`; si no se confirma la parada, se conserva `UNCONFIRMED`. **No existe** una política de recuperación de R1 ante un fallo terrestre | `tools/rover_ground_executor.py` |
| Evidencia de completitud | **No representable**: `query_ground_trial` informa del estado del trabajo y de su informe, pero no de si se alcanzó una posición o un POI | `R1_EXECUTOR_FACTS` |

## Cinco etapas que no se mezclan

1. **Dependencia.** Se recalcula a partir de los hechos de la vista y se contrasta con el
   `dependency` que declara la propia vista. Si no coinciden, queda `UNKNOWN`.
2. **Elegibilidad.** Requiere a la vez:
   - dependencia `MET`;
   - identidad del rover acreditada;
   - navegación a una posición soportada (hoy solo existe `ROVER_BOUNDED_CONTROL`);
   - `OPERATIONAL_ROVER_ENABLED` (hoy `False`);
   - los datos requeridos;
   - una entrada pública con reservas;
   - un gate de ejecución que cubra el perfil del rover.
3. **Autorización.** Corresponde al operador. El dry-run **nunca** la acepta ni la registra:
   siempre `ABSENT`.
4. **Admisión.** Es la de `admit_ground_trial` (Codex). El dry-run **no** la llama.
5. **Ejecución.** Necesita un resultado terrestre atribuido. Un resultado de `query_ground_trial`,
   aunque sea `PASSED`, se marca `counts_as_r1_completion: false`
   (`GROUND_TRIAL_RESULT_HAS_NO_POSITION_OUTCOME`).

`MET` es solo la precondición: no cambia `movement_authorized` ni `commands_sent`.

## Datos que faltan para concretar R1

No se ha inventado ninguno. Las tolerancias aéreas de 1,0/0,75 m **no** son tolerancias terrestres.

| Dato | Por qué falta |
| --- | --- |
| `target_in_rover_frame` | `POI_A1` está expresado respecto al lanzamiento de drone_01, y `common_frame.validated` es `false` |
| `ground_tolerance_m` | No hay ninguna tolerancia terrestre declarada |
| `rover_mission` | No existe ninguna misión `rover_01`/`v3` validada |
| `completion_evidence` | No se ha definido qué observación atribuida (fuente, marco, momento) prueba la verificación |
| Identidad del rover | La cadena XRCE → instancia SITL/SYSID → puente/modelo no está establecida (trabajo de Codex) |

## Pruebas con dobles (`tests/test_agri_scenario.py`)

Escenarios cubiertos con secuencias sintéticas o con dobles de la vista, etiquetados como tales:
- ambos drones pasan y R1 sigue bloqueado;
- el primer dron falla y el segundo no empieza;
- `POI_A1` no alcanzado;
- secuencia sin terminar;
- vista contradictoria;
- registro alterado;
- dependencia `MET` sin identidad;
- datos e identidad dobles, pero sin capacidad, sin política y sin autorización;
- resultado terrestre simulado `FAILED` o `PASSED`: ninguno completa R1.

También se comprueba que repetir el dry-run da el mismo resultado y no escribe archivos ni abre
procesos o sockets. **Ningún resultado simulado se presenta como ejecución del rover, y el
escenario real de H2 sigue incompleto.**

## Especificación propuesta: R1 como visita y parada en POI_A1 (25/10/2026, NO aprobada)

**Qué acreditaría:** que `rover_01` navegó hasta POI_A1 y permaneció detenido dentro de una
tolerancia, según una observación de posición atribuida. **No** acredita una inspección agrícola:
no hay ningún sensor implicado.

### 1. Parámetros propuestos

> **Sustituido por la [revisión 2](#revisión-2-cierre-de-la-especificación-25102026-no-aprobada)** (timeout, permanencia, marco y tolerancias). Se conserva como registro.

Están en `R1_VISIT_PROPOSAL` (`PROPOSED_NOT_APPROVED`). Ninguno hereda las tolerancias aéreas.

| Parámetro | Valor propuesto | Justificación | Validación real necesaria |
| --- | --- | --- | --- |
| Tolerancia de llegada (horizontal) | 2,0 m | Valor por defecto de `WP_RADIUS` en ArduRover, según la documentación de ArduPilot; no se ha leído en este repositorio ni en el SITL | Leer el `WP_RADIUS` efectivo del SITL v3 y medir la dispersión de la odometría en reposo |
| Permanencia | 5,0 s continuos, al menos 3 muestras | Varias muestras consecutivas, no una coincidencia al pasar | Frecuencia real de `/rover1/odometry` |
| Vehículo detenido | ≤ 0,05 m/s y ≤ 0,05 rad/s | Mismo significado que `RoverLimits.stopped_*` de Codex (que no tiene valores por defecto) | Ruido de la odometría con el rover en HOLD |
| Pérdida de observación | hueco de recepción > 1,0 s | Detectable con la frecuencia esperada | Frecuencia real y jitter |
| Datos antiguos | sellos de fuente que no avanzan, o última muestra con más de 1,0 s al decidir | Mismo criterio de progreso que `RoverControlCore._progress` | — |
| Timeout | distancia / velocidad máxima × 2 + 30 s, sin pasar del `max_duration_s` explícito | La distancia y la velocidad dependen del marco verificado y de los límites que elija Joel | Distancia real tras verificar los marcos |
| Resultado de fallo | `FAILED` (no llegó, o pasó sin permanecer), `UNCERTAIN` (datos antiguos, pérdida o parada sin confirmar) o `REJECTED` (vínculo, marco o falta de evidencia) | `UNCERTAIN` conserva la incertidumbre, igual que `UNCONFIRMED` en el ejecutor | — |

**Evidencia mínima de completitud:**
1. Muestras de posición atribuidas, en el marco del objetivo y con una transformación `VERIFIED`.
2. Un tramo continuo dentro de la tolerancia y detenido durante al menos la permanencia.
3. Una parada confirmada (`STATIONARY_OBSERVED`).
4. Ninguna pérdida ni dato antiguo.
5. Un vínculo exacto con el candidato, la misión, la autorización, el vehículo, la sesión y el
   trabajo.

### 2. Marco y destino

> **Sustituido por la [revisión 2](#revisión-2-cierre-de-la-especificación-25102026-no-aprobada)** (timeout, permanencia, marco y tolerancias). Se conserva como registro.

| Tipo | Contenido | Estado |
| --- | --- | --- |
| Definición de POI_A1 | 8,0 m al norte y 4,0 m al oeste del *home* de la misión de drone_01 (`_calculate_local_offset_metres`, `tools/simulation_mission_mapper.py`). El ejecutor aéreo lo aplica respecto al lanzamiento de cada vehículo | Hecho del código |
| Configuración de spawn | drone1 en `(-2, 0, 0.195)` y rover1 en `(0, -3, 0.195)`, ambos con yaw 1,5708, en el mundo `runway` (`simulation/ros2_gazebo/launch/tfg_demo.launch.py`) | Configuración **declarada**, no observada |
| Posiciones observadas | H2 registra los errores de posición de los drones respecto a sus propios objetivos, según las observaciones del ejecutor vía AP_DDS (`limitations.telemetry_source`); el marco de origen no está acreditado. No hay ninguna pose del rover registrada | No hay observación que ligue los marcos |
| Transformación declarada (hipótesis) | **Si** el mundo de Gazebo es ENU, el *home* de drone_01 coincide con su spawn y la odometría del rover está en el marco del mundo: POI_A1 ≈ (−6, 8) en el mundo, es decir (−6, 11) desde el spawn del rover (unos 12,5 m) | **Sin verificar**; no se usa como objetivo |
| Transformación verificada | — | **No existe** |

**Precondiciones de la transformación:**
- orientación de los ejes del mundo `runway`;
- origen del EKF/*home* de drone1 frente a su spawn;
- `header.frame_id` y origen de `/model/rover1/odometry`; hoy el adaptador solo comprueba el
  `child_frame_id` y descarta la pose;
- que el spawn efectivo coincida con el declarado.

**Comprobación mínima** (en una futura sesión protegida, solo lectura):
1. Leer a la vez la pose del modelo `rover1` en Gazebo, la pose de `/rover1/odometry` con su
   `frame_id` y la posición local AP_DDS de drone1.
2. Comparar con los spawns declarados.
3. Registrar la transformación resultante con su hash y su tolerancia.

Hasta entonces, `target_in_rover_frame` queda vacío.

### 3. Capacidad del ejecutor frente a la especificación

Archivos de Codex, leídos sin modificar.

| Necesidad | Lo que existe | Lo que falta |
| --- | --- | --- |
| Observar la posición atribuida | `Observation` (`tools/rover_control.py`) solo lleva velocidades. `Ros2RoverAdapter.observe` (`tools/rover_ros2_adapter.py`) lee `nav_msgs/Odometry` pero descarta `pose` y no comprueba el `frame_id` padre | Posición, marco padre y GID de cada muestra en `Observation`; la cadena de identidad (matriz de Codex, puntos 3 y 4) |
| Calcular el error al destino | — | Un objetivo en un marco verificado (sección 2) |
| Navegar hasta el punto | `ROVER_BOUNDED_CONTROL` (velocidad, giro y duración); `move_for` envía una sola orden; `route_execution: NOT_SUPPORTED` | Navegación a una posición (GUIDED con objetivo de posición, o un bucle de control acotado). Es una decisión de Codex |
| Confirmar llegada y parada | `stop()` confirma HOLD y velocidad por debajo del umbral (`STATIONARY_OBSERVED`) | Llegada y permanencia con posición |
| Detectar pérdida de datos | `_progress` exige sellos y recepción crecientes; `observation_max_age_s` | Registrar los huecos dentro del resultado |
| Parar y conservar la incertidumbre | `stop()` devuelve `UNCONFIRMED`; `run_ground_worker` conserva `UNCONFIRMED` | — (ya existe) |

**Contrato mínimo de integración coordinador ⇄ ejecutor:**
- **El coordinador entrega:** el candidato R1 y su `candidate_sha256`, la misión del rover y su hash,
  la autorización y su hash, y la sesión y el vehículo esperados.
- **El ejecutor devuelve:** un resultado `tfg.agri-r1-ground-result/1` con sus muestras crudas.
- **La aceptación** se hace en el coordinador con `evaluate_ground_result`. No se confía en las
  banderas ni en el estado del trabajo.

### 4. Contrato de resultado (`tfg.agri-r1-ground-result/1`)

| Campo | Contenido |
| --- | --- |
| `binding` | `candidate_sha256`, `mission_sha256`, `authorization_sha256`, `vehicle_id`, `simulated_vehicle`, `session_id` y `ground_run_id`. Cualquier diferencia da `REJECTED` |
| `commands` | `attempted` y `sent`, por separado |
| `frame` | Nombre y `transform_status`. Solo `VERIFIED` es aceptable |
| `samples[]` | `received_monotonic_s`, `source_stamp_ns`, `frame`, `x_m`, `y_m`, `linear_mps` y `angular_rad_s` |
| `decision_monotonic_s`, `observation_lost` | Antigüedad de los datos al decidir y pérdida declarada |
| `stop.status` | `STATIONARY_OBSERVED` o `UNCONFIRMED` |
| `job_status`, `origin` | Solo informativos: un `PASSED` sin evidencia del objetivo da `REJECTED` (`NO_TARGET_EVIDENCE`) |

La evaluación deriva de las muestras:
- llegada (`min_error_m`, `arrival_observed`);
- permanencia (`dwell_observed_s`);
- parada;
- pérdida;
- antigüedad de los datos.

En el dry-run, `counts_as_r1_completion` es **siempre** `false`, porque no hay etapa de
autorización ni de ejecución. Solo `would_satisfy_r1_contract` indica la coherencia del contrato.

### 5. Validación offline y ejemplos sintéticos

En [`synthetic_contract_examples.json`](synthetic_contract_examples.json) hay cuatro ejemplos
**sintéticos**: ningún rover se movió, el marco es `TEST_FRAME` y el hash de misión es todo ceros.

| Ejemplo | Evaluación |
| --- | --- |
| Llegada, permanencia y parada | `VERIFIED` (contrato satisfecho; no completa R1) |
| Paso por el punto sin permanecer | `FAILED`: `PASSED_THROUGH_NO_DWELL` |
| Parada sin confirmar | `UNCERTAIN`: `STOP_UNCONFIRMED` |
| Resultado de otra sesión | `REJECTED`: `BINDING_MISMATCH:session_id` |

**Casos cubiertos por los tests:**
- Fuera de tolerancia: `NOT_REACHED`.
- Permanencia corta: `PASSED_THROUGH_NO_DWELL`.
- Datos antiguos: sellos repetidos o decisión tardía.
- Hueco de recepción: `OBSERVATION_LOST`.
- Marco de muestra distinto, y transformación solo declarada.
- `PASSED` sin muestras: `NO_TARGET_EVIDENCE`.
- Otra misión, sesión, candidato, trabajo o vehículo.
- H2 real sin candidato: `NO_R1_CANDIDATE`.

**El H2 histórico sigue incompleto.** Salida actual del dry-run:
[`r1_dry_run_h2_with_result_contract.json`](r1_dry_run_h2_with_result_contract.json), que solo
añade `candidate_sha256: null` a la salida anterior.

### 6. Secuencia mínima de implementación

**Imprescindible para completar R1, en orden:**
1. **Joel y el tutor** aprueban o ajustan los parámetros de la sección 1 y el alcance «visita y
   parada».
2. **Codex** resuelve la identidad del rover y el lector con GID por muestra (matriz, puntos 1–4) y
   añade la pose y el marco padre a la observación atribuida.
3. **Una sesión protegida de solo lectura** verifica la transformación de marcos (sección 2); de
   ahí sale `target_in_rover_frame`.
4. **Codex** añade la navegación a una posición con parada en el ejecutor, que devuelva el resultado
   de la sección 4.
5. Se escribe una misión `rover_01` validada, se fija la autorización explícita y se hace un único
   ensayo autorizado.
6. El coordinador acepta el resultado con `evaluate_ground_result`. Solo entonces podría cambiar la
   completitud del escenario.

**Mejoras posteriores (no imprescindibles):**
- tolerancia vertical o de orientación;
- varios puntos;
- inspección con sensores;
- exportar el resultado a Opik;
- usar R1 en la vista de Hermes.

## Revisión 2: cierre de la especificación (25/10/2026, NO aprobada)

Sustituye los parámetros y el marco de las secciones 1 y 2. Todo sigue en `PROPOSED_NOT_APPROVED`
(`R1_VISIT_PROPOSAL`, comprobado por `_visit_params`). No habilita admisión ni ejecución.

### Dos relojes que no se mezclan

| Reloj | Campo | Para qué se usa |
| --- | --- | --- |
| Simulación | `source_stamp_ns` (sello del mensaje, tiempo simulado) | Duración de la permanencia y huecos dentro de ella |
| Observación | `received_monotonic_s` (monotónico del host al recibir) | Orden de las muestras, pérdida de observación, antigüedad al decidir, timeout global y ausencia de progreso |

Nunca se resta un reloj del otro.
- **Si la simulación va más lenta que el tiempo real:** 8 s de pared pueden ser 4 s simulados, y la
  permanencia no se cumple. Está probado.
- **Si las muestras llegan agrupadas:** la duración se mide igualmente en tiempo simulado.

### 1. Timeout

La fórmula anterior (distancia / velocidad × 2 + 30 s) **se retira**: no era una cota conservadora
demostrada. Se sustituye por tres límites explícitos, configurables y experimentales, medidos en el
reloj de observación:

| Límite | Propuesta | Qué detecta | Resultado |
| --- | --- | --- | --- |
| Timeout global | 120 s, desde `commands.started_monotonic_s` hasta completar la permanencia | Exposición máxima del ensayo. No se deriva de ningún rendimiento medido: es un tope de duración que Joel debe aprobar y que no puede superar el `max_duration_s` explícito del ejecutor | `FAILED`: `GLOBAL_TIMEOUT` |
| Ausencia de progreso | Antes de la primera llegada, en cada ventana de 10 s la distancia al objetivo debe reducirse al menos 0,5 m | Rover parado, bloqueado o desviado | `FAILED`: `NO_PROGRESS` |
| Pérdida de observación | Ningún hueco de recepción mayor de 1,0 s | Falta de datos, no fallo del rover | `UNCERTAIN`: `OBSERVATION_LOST` |

Los tiempos nunca se alargan automáticamente para conseguir un `PASSED`. Si cambian, es una nueva
versión de la propuesta, revisada antes del ensayo.

### 2. Permanencia coherente

Parámetros: 5,0 s, huecos de hasta 1,0 s y **al menos 6 muestras**. Antes eran 3, lo que resultaba
incoherente: 5 s con huecos de 1 s exigen ⌈5/1⌉ + 1 = 6. `_visit_params` rechaza cualquier
combinación que no cumpla esa relación.

**Reglas que aplica el evaluador:**
- Las muestras se evalúan **en el orden recibido, sin reordenarlas**.
- Una hora de recepción repetida o invertida da `REJECTED` (`TIMELINE_NOT_ORDERED`).
- Un sello de simulación repetido o invertido da `UNCERTAIN` (`STALE_OR_NON_PROGRESSING_DATA`).
- La permanencia es un tramo de muestras consecutivas que están a la vez **dentro** de la
  tolerancia, **detenidas** y **válidas** (posición y velocidades finitas).
- Cada hueco del tramo debe ser de 1,0 s o menos **en los dos relojes**.
- La duración se mide entre los sellos de simulación de la primera y la última muestra del tramo.
- Una sola muestra fuera de tolerancia, en movimiento o no válida, o un hueco mayor, **interrumpe**
  el tramo.

**Límites exactos probados:**

| Caso | Resultado |
| --- | --- |
| Exactamente 5,0 s (11 muestras cada 0,5 s) | Cumple |
| Huecos de exactamente 1,0 s (6 muestras) | Cumple |
| 4,5 s | `PASSED_THROUGH_NO_DWELL` |
| Muestra sobre el radio de 2,0 m | Cuenta como dentro |
| Hueco de 2 s solo en el reloj de simulación | Interrumpe la permanencia sin ser pérdida de observación |

### 3. Transformación: qué la acreditaría

**Fuentes disponibles y qué acredita cada una:**

| Fuente | Tipo | Qué acredita | Qué no acredita |
| --- | --- | --- | --- |
| Spawns en `tfg_demo.launch.py`: drone1 (−2, 0), drone2 (2, 0), rover1 (0, −3), yaw 1,5708 | Configuración declarada | La intención de la configuración | Que el mundo sea ENU, o la pose efectiva |
| Ejecutor aéreo (`simulation_mission_executor`, `simulation_mission_mapper`) | Código | POI_A1 = *geopose* de lanzamiento observado de drone_01 + 8 m N / 4 m O (equirrectangular, 111 320 m/°), enviado como objetivo global (`cmd_gps_pose`) | Nada sobre el rover |
| H2: `gps_global_origin/filtered` de v1 y v2 | Observación histórica | Los dos drones compartieron el mismo origen EKF (−35,36326218, 149,16523743) | Que el rover (v3) lo comparta |
| H2: *geopose* de lanzamiento de v1 y v2 | Observación histórica, float32 | Misma latitud; longitud a −2 y +2 ulp del origen (≈ −2,77 y +2,77 m al este). El signo coincide con x del spawn | La magnitud exacta. Un ulp de longitud son ≈ 1,39 m, y los ±2,0 m declarados solo encajan con ≈ 0,15 m de error de estimación además del redondeo. Los dos puntos son colineales: no prueban el eje norte |
| H2: objetivo y llegada de POI_A1 | Observación histórica | Objetivo (−35,3631903, 149,1651628), a 6,77 m al oeste y 8,0 m al norte del origen compartido; drone_01 llegó a 0,17 m | Su expresión en un marco del rover |

**Comprobación mínima propuesta.** Es de solo lectura y no ordena ningún movimiento. No supone ENU
ni que el *home* coincida con el spawn.

1. **Correspondencias de tres vehículos parados.** drone1, drone2 y rover1 no son colineales
   ((−2,0), (2,0) y (0,−3)). En la misma sesión protegida se leen, de los tres:
   - pose de modelo en Gazebo;
   - `gps_global_origin/filtered`;
   - *geopose*;
   - odometría del rover con su `header.frame_id` y su `child_frame_id`.

   Tres correspondencias no colineales determinan la traslación, la rotación de ejes (y su signo) y
   la escala entre el mundo de Gazebo y el marco geodésico local. Una sola correspondencia solo da
   una traslación.
2. **No basta con una captura aislada.** Se repite N veces a lo largo de al menos 30 s para medir la
   dispersión, y en un segundo arranque para comprobar que se reproduce.
3. **Criterios:**
   - el rover comparte el origen EKF de los drones;
   - los residuos son ≤ 0,5 m, una cota provisional por encima de la cuantización de float32;
   - la escala es igual a 1 dentro de la incertidumbre;
   - el `frame_id` de la odometría y sus unidades (m, m/s, rad/s) son los declarados.
4. **Si se cumplen:** `target_in_rover_frame` se registra con la transformación y su hash
   (`transform_status: VERIFIED`).
5. **Si no se cumplen:** sigue vacío, y R1 sigue sin candidato.

**Advertencia de precisión.** Si el marco de R1 fuera geodésico (*geopose* del rover), la
cuantización de float32 en longitud (≈ 1,39 m por ulp aquí) consume buena parte de una tolerancia
de 2,0 m. Una odometría local en metros, una vez verificada su transformación, no tiene ese
problema.

### 4. Tolerancias: dos magnitudes distintas

| Magnitud | Qué mide | Quién la aplica |
| --- | --- | --- |
| `WP_RADIUS` efectivo de ArduRover | Cuándo el piloto automático **considera** alcanzado un waypoint y pasa al siguiente o se detiene. Es un criterio de control, sin observación independiente | ArduPilot |
| `arrival_tolerance_m` de R1 | Distancia, medida con muestras atribuidas en el marco verificado, a la que el **coordinador acepta** la llegada | `evaluate_ground_result` |

**2,0 m sigue siendo una propuesta experimental** pendiente de comprobación.
- **Por qué no se toma de `WP_RADIUS`:** que el valor por defecto de ArduRover sea 2 m no garantiza
  ninguna precisión.
- **Qué falta medir:**
  - leer el `WP_RADIUS` efectivo de v3;
  - medir la dispersión de la posición en reposo;
  - sumar la incertidumbre de la transformación verificada.

  La tolerancia de aceptación no debería ser menor que esa suma.

### 5. Ficha de integración para Codex

**Observation.** Campos que tendría que añadir; hoy solo lleva velocidades:
- `position_m` = (x, y);
- `position_frame` (el `header.frame_id` padre);
- `child_frame`;
- `position_source` (tópico) y `publisher_gid` de esa muestra;
- `source_stamp_ns`, el sello del mensaje en tiempo simulado. Ya existe `velocity_source_ns`, pero
  hay que conservarlo **para cada muestra**.

Alternativa geodésica: `latitude`, `longitude`, `global_origin` y su precisión.

**Marcos y unidades:**
- posiciones en metros, en un marco con nombre;
- velocidades en m/s y rad/s;
- el `frame_id` padre **comprobado**, no solo el hijo;
- sin conversiones implícitas.

**Muestras que debe conservar.** **Todas**, en el orden recibido:
- desde la observación previa a la orden, durante la aproximación y la permanencia, hasta la parada;
- con `received_monotonic_s` y `source_stamp_ns` cada una;
- sin reordenarlas, sin deduplicarlas y sin descartar las no válidas.

**Relojes y antigüedad:**
- `received_monotonic_s` es el monotónico del host;
- `source_stamp_ns` es el tiempo simulado;
- `decision_monotonic_s` registra el momento de la decisión;
- `commands.started_monotonic_s`, el de la primera orden.

**Llegada, permanencia y parada.** Las calcula el coordinador a partir de las muestras, según las
secciones 1, 2 y 4. Del ejecutor se espera además el resultado de `stop()` (`STATIONARY_OBSERVED`).

**Incertidumbre:**
- `stop()` en `UNCONFIRMED`, una pérdida, datos antiguos o `observation_lost` dan `UNCERTAIN`, nunca
  `PASSED`;
- un `job_status` `PASSED` sin muestras da `REJECTED`;
- `commands.attempted` y `commands.sent` se informan por separado.

**Vínculo.** `candidate_sha256`, `mission_sha256`, `authorization_sha256`, `vehicle_id`,
`simulated_vehicle`, `session_id` y `ground_run_id`.

**Ejemplos sintéticos:** [`synthetic_contract_examples_v2.json`](synthetic_contract_examples_v2.json).
Ningún rover se movió en ellos. La versión anterior, `synthetic_contract_examples.json`, se conserva
como registro de la revisión 1.

| Ejemplo | Resultado |
| --- | --- |
| Aproximación con progreso, llegada, 6 s detenido y parada | `VERIFIED` |
| Horas de recepción duplicadas | `REJECTED`: `TIMELINE_NOT_ORDERED` |
| Transformación solo declarada | `REJECTED`: `FRAME_NOT_VERIFIED_OR_DIFFERENT` |
| Resultado de otra sesión | `REJECTED`: `BINDING_MISMATCH:session_id` |
| Trabajo `PASSED` sin muestras | `REJECTED`: `NO_TARGET_EVIDENCE` |
| Sellos de simulación repetidos | `UNCERTAIN`: `STALE_OR_NON_PROGRESSING_DATA` |
| Parada sin confirmar | `UNCERTAIN`: `STOP_UNCONFIRMED` |
| Simulación a mitad de velocidad (4 s simulados en 8 s de pared) | `FAILED`: `PASSED_THROUGH_NO_DWELL` |
| Aproximación de 2 cm por muestra | `FAILED`: `NO_PROGRESS` |
| Permanencia completada 135 s después de la orden | `FAILED`: `GLOBAL_TIMEOUT` |

**El H2 histórico sigue incompleto**: la salida de `r1-dry-run` no cambia con esta revisión. Los
resultados del piloto tampoco cambian.

### Precisiones al contrato (traspaso a Codex, 25/10/2026)

La revisión 2 sigue siendo **una propuesta**. Estas precisiones no la amplían:

1. **Residuos de 0,5 m: provisional.** Hay que contrastarlo con la resolución y la incertidumbre de
   cada fuente.
   - Con posiciones geodésicas en float32 del ejecutor aéreo, un ulp de longitud son ≈ 1,39 m y uno
     de latitud ≈ 0,43 m. Una diferencia entre dos posiciones redondeadas puede llevar ya ≈ 1,39 m
     de error en el eje este.
   - **No se afirma que 0,5 m sea alcanzable con esas fuentes.** El umbral solo tiene sentido con
     posiciones de más resolución (pose de Gazebo u odometría local en metros) o promediando, y eso
     está por demostrar.
2. **Los límites del host (120 s, 10 s / 0,5 m, 1 s) hay que validarlos frente al rendimiento real
   del simulador** (factor de tiempo real y frecuencia de los tópicos).

   El resultado separa tres cosas:
   - **fallo del objetivo:** `NOT_REACHED_OUT_OF_TOLERANCE`, `PASSED_THROUGH_NO_DWELL` o `NO_PROGRESS`;
   - **tiempo disponible agotado:** `GLOBAL_TIMEOUT`;
   - **parada:** `stop_confirmed` y `STOP_UNCONFIRMED`, que se informa siempre, aunque el objetivo
     haya fallado o se haya agotado el tiempo.

   Un `GLOBAL_TIMEOUT` no dice si el rover habría llegado. Una parada incierta deja el resultado
   en `UNCERTAIN`, aunque las muestras parezcan correctas.
3. **Coincidencia de orígenes EKF.** Que en H2 coincidan numéricamente los de v1 y v2 **no basta
   para declarar validado un marco común**. Es un solo valor por vehículo, en float32, y no dice nada
   de la orientación de los ejes, ni de la escala, ni del rover. Sigue haciendo falta la comprobación
   de tres vehículos no colineales con varias repeticiones.

### Ficha de medición para una futura sesión de solo lectura

**No autoriza ni programa ninguna apertura.** Las dos aperturas de la comprobación de marcos (la
sesión y su repetición en un segundo arranque) **no están autorizadas ni programadas**. Cualquier
ensayo real necesita su propia preparación (precheck, identidad, presupuesto) y una autorización
operativa aparte.

**Lo que no se puede medir sin movimiento.** La permanencia y el progreso dependen de un
desplazamiento del rover, que una sesión de solo lectura no produce. En ella solo se miden sus
**entradas**: frecuencia, huecos, ruido en reposo, resolución y la relación entre relojes.

**Abreviaturas de la tabla:**
- **Colector C++ pasivo:** `tools/rover_passive_rclcpp`, de Codex.
- **Lectores aéreos:** `get_vehicle_geopose` y `get_vehicle_global_origin`, en `tools/ros2_flight_control.py`.

| Dato necesario | Fuente existente | Reloj / marco / unidad | Incertidumbre conocida | Qué permitiría decidir |
| --- | --- | --- | --- | --- |
| Frecuencia de `/rover1/odometry` y de `/ap/v3/status` | Colector C++ pasivo: `header.stamp` y recepción por muestra | `header.stamp`: tiempo simulado (ns). Recepción: `steady_ns` del proceso y `system_unix_ns` | Limitado a 20 muestras y 120 s por captura; QoS reservada | Si 6 muestras por cada 5 s y huecos de 1 s son razonables, o hay que ajustar `min_dwell_samples` y `max_sample_gap_s` |
| Huecos de recepción y su distribución | El mismo colector (`steady_ns` consecutivos) | Reloj de observación, s | La planificación del host y la captura acotada pueden añadir huecos | Valor de `max_sample_gap_s` y distinción entre pérdida y jitter |
| Relación entre el tiempo simulado y el de pared (rendimiento real) | El mismo colector: avance de `header.stamp` frente al de `steady_ns` | Simulado frente a observación | Solo en reposo; puede cambiar bajo carga o con la GUI | Si los límites del host (120 s, ventana de 10 s) dejan margen; también el riesgo de permanencia corta si la simulación va lenta |
| Marcos de la odometría (`header.frame_id` y `child_frame_id`) | El mismo colector, que serializa los dos | Nombres | Una sola sesión; la asociación con el bridge y el modelo sigue pendiente (matriz de Codex, punto 3) | Qué marco tendría que transformarse; si coincide con el `base_link` que espera `MotionBinding` |
| Posición del rover en reposo (valores) y su dispersión | **No disponible**: el colector C++ no guarda la pose, `NativeRos2Session` y `Ros2RoverAdapter.observe` la descartan y no hay lector de pose de Gazebo en el repositorio | — | — | Sin ella no se pueden fijar ni la tolerancia ni los residuos. Requiere el cambio de `Observation` de la ficha anterior (Codex) |
| Velocidad en reposo (ruido) | **No disponible en el colector pasivo** (no guarda el twist). `Ros2RoverAdapter.observe` sí lo lee, pero exige una `MotionBinding` acreditada y hoy está bloqueado | — | — | Umbrales `stopped_linear_mps` y `stopped_angular_rad_s` |
| *Geopose* y origen EKF de v3 | **No disponible**: los lectores aéreos solo aceptan v1 y v2 (`tools/simulated_vehicle.validate_interface`), y el tópico de v3 no se ha observado | — | — | Si el rover comparte el origen de los drones; alternativa geodésica, limitada por float32 |
| *Geopose* y origen EKF de v1 y v2 | Lectores aéreos (lectura en H2) | WGS84 grados, float32; reloj del host al leer | ulp ≈ 1,39 m en longitud y ≈ 0,43 m en latitud; estimación del EKF | Dos de las tres correspondencias; repetidas, la dispersión |
| Pose de los modelos en el mundo de Gazebo | **No disponible**: ninguna herramienta del repositorio la lee | — | — | La tercera fuente de la transformación (traslación, ejes y escala). Sin ella, la transformación no puede verificarse |
| Spawns y yaw declarados | `simulation/ros2_gazebo/launch/tfg_demo.launch.py` | Mundo `runway`, m y rad | Declarado, no observado | Valor esperado con el que se comparan las observaciones |
| `WP_RADIUS` efectivo de v3 | **No disponible**: `rover_identity_inventory` busca un `GetParameters` público, pero `RosGraphInventoryReader.get_parameters` devuelve `UNKNOWN` (no hay cliente) | — | — | Comparación entre el criterio del piloto automático y la tolerancia de aceptación de R1 |
| Unidades de la odometría | `nav_msgs/Odometry` (m, m/s, rad/s por definición del mensaje), más los marcos del colector | — | El contenido no se ha observado | Que no haga falta conversión |
| Permanencia y progreso reales | **No medibles en solo lectura**: exigen movimiento | — | — | Solo un ensayo terrestre autorizado aparte, con el contrato de resultado |

**Lo único que una sesión de solo lectura podría medir hoy con fuentes existentes** son la
frecuencia, los huecos, la relación entre relojes y los nombres de los marcos de la odometría del
rover, más el *geopose* y el origen de los drones. La posición del rover, su velocidad, su *geopose*,
la pose de Gazebo y `WP_RADIUS` dependen de cambios o lectores que aún no existen. **La
transformación y la tolerancia no pueden validarse hasta disponer de ellos.**

**Aclaraciones (25/10/2026):**
- **Cuando existan lectores de pose y velocidad del rover**, una sesión con el rover en reposo
  permitirá medir la dispersión de la posición, la velocidad residual, la frecuencia, los huecos y
  la estabilidad temporal.
- **La llegada y el progreso** se validarían después, con una prueba de movimiento distinta,
  preparada y autorizada aparte.
- **Las dos aperturas propuestas para los marcos** (la sesión y su repetición en un segundo
  arranque) son un **diseño experimental pendiente de revisión**. No son un requisito aprobado y
  no deben añadirse automáticamente como condición a ningún gate.

### Estado: en pausa

Esta línea queda **en pausa** hasta que haya una de estas dos cosas:
1. mediciones de una sesión de solo lectura preparada y autorizada aparte;
2. el resultado de Codex sobre identidad, `Observation` con pose y lectores pendientes.

No se ejecuta nada más por iniciativa propia.

## Siguiente paso mínimo para integrar la tarea terrestre

Antes de cualquier código de control:
- **Joel y el tutor** deciden el alcance de R1: qué observación cuenta como verificación, la
  tolerancia y el marco común.
- **Codex** resuelve la identidad del rover y la capacidad de ir a una posición, o declara que no
  forma parte del alcance.

Con esos datos, el mismo `prepare_ground_task` producirá un candidato. La autorización y la admisión
seguirán siendo pasos separados del operador y del ejecutor existente.
