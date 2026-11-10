# Fundamentos matemáticos del sistema actual (BORRADOR para revisión matemática)

> **Estado:** borrador de trabajo, revisado el 31/10/2026 para revisarlo con Toni. **No está listo para entregar.**
>
> **Corrección posterior a H2:** el 31/10/2026 se corrigió el redondeo de tramos cortos y se mejoró el diagnóstico de los tramos verticales (§5.3.2). Los módulos afectados de la entrega de estudiantes (imágenes `app` y `planner`) son `tools/route_geometry.py`, `tools/flight_dynamics.py`, `tools/route_flight_analysis.py`, `tools/mission_energy_analysis.py`, `safety/mission_safety_analysis.py` y `replanning/waypoint_mission_replanner.py`. Habrá que incorporarlos en su próxima versión; la entrega actual **no** se ha reconstruido.
>
> **Marcas:**
> - **[CÓDIGO `ruta:función`]**: lo que hace nuestra implementación, leído en el repositorio.
> - **[AP `ruta`]**: código de ArduPilot en el commit `755258db`, leído en `ardupilot_ros2_ws/src/ardupilot` (árbol limpio).
> - **[BIN]**: lectura estática (`objdump`, solo lectura) del ejecutable instalado `ardupilot_ros2_ws/install/ardupilot_sitl/bin/arducopter`.
> - **[GZ `ruta`]**: configuración de `ardupilot_gazebo` `cc0290d9` o de `ardupilot_gz` `8df4dc17` (este último con 3 cambios locales en los launch).
> - **[B#n]**: entrada n de [`04_bibliografia_comentada.md`](04_bibliografia_comentada.md). **[N#n]**: fuente nueva, al final de este documento.
> - **[TEORÍA]**: ecuación general de la literatura. **No** significa que el sistema la use.
> - **[NO ACREDITADO]**: no se ha podido determinar con las fuentes fijadas. No se completa por intuición.
> - **[H2]**: dato de la evidencia sellada [`agri_demo_h2_2026_10_24`](../../simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/README.md) (24/10). No describe el estado actual.
>
> **Cálculos auxiliares:** los números de este documento salen de [`05_calculos/verificar_05.py`](05_calculos/verificar_05.py), y su salida está en [`05_calculos/salida_verificar_05.txt`](05_calculos/salida_verificar_05.txt).
> - El script importa las funciones del proyecto sin modificarlas y lee las evidencias en solo lectura.
> - **No es evidencia operacional:** no ejecuta simulación ni ROS.
>
> **Correspondencia de las fuentes con la ejecución:**
> - Las fuentes de ArduPilot y Gazebo son las del workspace montado en el contenedor según [`docs/simulator-distribution-handoff.md`](../simulator-distribution-handoff.md) §3. El contenedor y los procesos en ejecución **no** se inspeccionaron.
> - **Código del proyecto:** los archivos que intervienen en la llegada y en la duración no tienen cambios en el árbol de trabajo respecto a HEAD, y su último commit es anterior a H2 (20/10 o antes). Es **compatible** con que H2 usara este código. La evidencia no guarda una instantánea del código.

## 5.1 Tres capas y qué parte calcula cada una

| Capa | Quién la implementa | Qué calcula | Qué **no** calcula |
| --- | --- | --- | --- |
| 1. Planificador y validador | Nuestro código | Distancias, rumbos, tiempo estimado con viento, batería porcentual, conversiones entre metros y grados, comprobaciones geométricas, errores de llegada | Ninguna dinámica ni control |
| 2. Autopiloto | ArduPilot SITL (ArduCopter) | Estimación de estado (AHRS/EKF), control de posición en GUIDED, home, armado | La física del vehículo: con el backend JSON la recibe de Gazebo |
| 3. Simulador físico | Gazebo Harmonic con `ArduPilotPlugin` | Dinámica de sólido rígido, fuerzas de los rotores (sistema `LiftDrag`), IMU, pose y velocidad verdaderas | Lo que no esté configurado en el mundo o en el modelo (§5.5) |

Entre las capas 1 y 2 está la **interfaz AP_DDS**. Por ella el ejecutor lee `/ap/vN/geopose/filtered` y envía órdenes `cmd_gps_pose` (§5.3.8).

### 5.1.1 Recorrido vigente de la validación

Una misión finalizada por Hermes se valida siguiendo esta cadena, comprobada por sus importaciones:

1. `tools/hermes_mission_validation.py:validate_mission`
2. `sessions/structured_mission_session.py:evaluate_structured_mission`
3. `graph/waypoint_mission_graph.py` (nodo `graph/waypoint_nodes.py:evaluate_waypoint_mission_node`)
4. `safety/mission_safety_analysis.py:evaluate_mission_safety`, que llama a:
   - `tools/mission_energy_analysis.py:analyze_mission_energy` → `tools/route_flight_analysis.py:analyze_mission_flight` → `tools/route_geometry.py:analyze_waypoint_route` y `tools/flight_dynamics.py:calculate_flight_time` → `safety/battery_guard.py:check_battery_safety`;
   - `safety/wind_guard.py:check_wind_safety`;
   - `safety/altitude_guard.py:check_altitude_safety`.
5. Después, `replanning/waypoint_mission_replanner.py:generate_waypoint_replan` produce las acciones que ve el usuario.

El mismo `validate_mission` lo usan `planning/scenario_instance.py`, `planning/verified_preflight.py`, `tools/preflight_sequence_worker.py` y `reporting/agri_scenario_summary.py`.

**Otra versión, no vigente:** el grafo escalar `graph/mission_graph.py` (`graph/nodes.py`, `safety/mission_validator.py`, `replanning/mission_replanner.py`). En la búsqueda no apareció ningún módulo fuera de las pruebas que lo importe. Usa las mismas `calculate_flight_time` y `check_battery_safety`.

## 5.2 Fundamentos necesarios

### 5.2.1 Marcos de referencia y unidades angulares

**Marcos:**
- **Geográfico.** Latitud φ y longitud λ en grados sobre WGS 84 [B#19, PENDIENTE]. El emplazamiento declara `horizontal_datum: "WGS84"` [CÓDIGO `models/site.py:GeoReference`].
- **ENU local** (este, norte, arriba). Es el convenio de ROS para representaciones cartesianas de corto alcance [B#17]; se ha leído su texto fuente en `ros-infrastructure/rep`, `rep-0103.rst`.
- **NED local** (norte, este, abajo). Es el marco de trabajo de ArduPilot. REP 103 lo admite como marco secundario con sufijo `_ned` [B#17].
- **Cuerpo:**
  - FLU en ROS: x adelante, y izquierda, z arriba [B#17];
  - FRD en ArduPilot: x adelante, y derecha, z abajo. Lo confirma el parámetro `modelXYZToAirplaneXForwardZDown` del plugin [GZ `models/iris_with_gimbal/model.sdf`].
- **Rumbo.** Ángulo horario desde el norte verdadero, en [0°, 360°). Equivale al yaw NED, y yaw_ENU = 90° − yaw_NED (§5.2.3).

**Grados o radianes:**
- **En datos y modelos, siempre grados:** latitud, longitud, rumbos, `wind_direction_from_deg`, `y_axis_bearing_deg` y `orientation_deg`.
- **El código convierte a radianes antes de cualquier función trigonométrica** (`math.radians`) en:
  - `tools/route_geometry.py` (`haversine_distance_km`, `calculate_initial_bearing_deg`);
  - `tools/flight_dynamics.py:calculate_flight_time`;
  - `planning/site_geometry.py` (`local_to_north_east`, `north_east_to_local`, `local_to_geo`);
  - `planning/relative_routes.py:_local_points`;
  - `tools/simulation_mission_mapper.py:_calculate_local_offset_metres`.
- `calculate_initial_bearing_deg` devuelve el rumbo en grados (`math.degrees`).
- **Fuera de nuestro código:**
  - los semiángulos de los cuaterniones (§5.2.3) están en radianes;
  - el yaw del spawn en el launch está en radianes (1,5708);
  - los ángulos de `gazeboXYZToNED` están en grados (`degrees="true"`).

### 5.2.2 Rotación plana del emplazamiento

El marco `ENU_ROTATED` [CÓDIGO `planning/site_geometry.py:local_to_north_east`] tiene:
- +y en el rumbo β;
- +x 90° en sentido horario respecto de +y;
- con β = 0 es ENU puro.

Los vectores unitarios en (E, N) son ŷ = (sin β, cos β) y x̂ = (cos β, −sin β). Por tanto:

  E = x·cos β + y·sin β,  N = −x·sin β + y·cos β

La inversa (`north_east_to_local`) es la transpuesta, porque la matriz es ortogonal.

**Ejemplo (β = 30°):**
- (10, 0) → (N, E) = (−5,000; 8,660);
- (0, 10) → (8,660; 5,000);
- la ida y vuelta de (3, 4) devuelve (3, 4).

### 5.2.3 Cuaterniones y la conversión de AP_DDS

Un cuaternión unitario q = (w, x, y, z) = (cos(θ/2), **u**·sin(θ/2)), con θ en radianes, representa una rotación de ángulo θ alrededor de **u**. Con el convenio de Hamilton [N#3] su matriz es:

  R(q) = [[1−2(y²+z²), 2(xy−wz), 2(xz+wy)], [2(xy+wz), 1−2(x²+z²), 2(yz−wx)], [2(xz−wy), 2(yz+wx), 1−2(x²+y²)]]

Un cambio de marco del mundo (T) y del cuerpo (F) transforma la orientación así: R' = T·R·F.
- Para pasar de NED a ENU, T intercambia x e y y cambia el signo de z.
- Para pasar de FLU a FRD, F = diag(1, −1, −1).

**Qué hace AP_DDS** [AP `libraries/AP_DDS/AP_DDS_Client.cpp`, `update_topic(geographic_msgs_msg_GeoPoseStamped&)`]: forma `aux = (w, y, x, −z)` y lo multiplica por (√2/2, 0, 0, √2/2), una rotación de 90° en z.

**Comprobado numéricamente.** Con 1000 orientaciones aleatorias, R(aux ⊗ q_z90) coincide con T·R(q)·F (diferencia máxima de 1·10⁻¹⁵): es exactamente el cambio NED/FRD → ENU/FLU. Ejemplos: un yaw NED de 0° da un yaw ENU de 90°; uno de 90° da 0°; uno de 30° da 60°.

**Alcance:** es la convención de la interfaz. Nuestro ejecutor no lee la orientación.

### 5.2.4 Velocidad respecto al aire y respecto al suelo

**[TEORÍA]** La velocidad respecto al suelo es la suma vectorial de la velocidad respecto al aire y del viento, expresadas en el mismo marco terrestre (por ejemplo, NED): **v**_g = **v**_a + **w**.

Para seguir un rumbo ψ con una velocidad de aire de módulo V, sale el **triángulo de viento** [N#2, cap. 2.3–2.4]:

  V_g = −W·cos α + √(V² − W²·sin² α),  con α = (procedencia del viento) − ψ

Hay solución si |W·sin α| < V, y avance si además V_g > 0. Los ángulos se convierten a radianes antes de evaluar el coseno y el seno.

### 5.2.5 Fuerzas y momentos

**[TEORÍA]** Modelo de sólido rígido de Newton–Euler [N#1], con los marcos declarados:
- **Mundo:** {n} = NED local, considerado inercial a esta escala.
- **Cuerpo:** {b} = FRD, con el origen en el centro de masas.
- **R = R_nb:** la matriz que lleva componentes del cuerpo al mundo, **v**ⁿ = R·**v**ᵇ.

Entonces:

  m·**v̇**ⁿ = m·(0, 0, g)ⁿ + R·(0, 0, −ΣTᵢ)ᵇ + **F**ⁿ_aero
  J·**ω̇**ᵇ + **ω**ᵇ × J·**ω**ᵇ = **τ**ᵇ

- **v**ⁿ es la velocidad del centro de masas en NED.
- La gravedad tiene signo + porque z apunta hacia abajo en NED.
- El empuje de los rotores actúa hacia arriba del cuerpo, es decir en −z_b en FRD.
- **ω**ᵇ, J y **τ**ᵇ se expresan en el cuerpo.
- **En ENU/FLU** la misma ecuación se escribe m·(0, 0, −g) + R'·(0, 0, +ΣTᵢ), con R' = T·R·F (§5.2.3).

Es habitual aproximar Tᵢ = k_T·ωᵢ² y Qᵢ = k_Q·ωᵢ², con ωᵢ (velocidad angular del rotor) en rad/s.

**Esto no es lo que acredita nuestro sistema:**
- nuestro código no integra estas ecuaciones;
- el modelo de Gazebo usado calcula las fuerzas con `LiftDrag` sobre las palas (§5.5.2), cuyas ecuaciones no se inspeccionaron → **[NO ACREDITADO]**.

**Cifra derivada:** la masa declarada del modelo suma 1,98 kg. **Si** g = 9,8 m/s², en vuelo estacionario el empuje total sería 19,4 N. Es una consecuencia teórica, no un valor medido.

## 5.3 Capa 1: qué calcula nuestro planificador

### 5.3.1 Del metro al grado: el modelo lineal local

  Δφ = N / k,  Δλ = E / (k·cos φ₀),  con k = 111 320 m/° y φ₀ la latitud de referencia

**Dónde se implementa:**
- [CÓDIGO `tools/simulation_mission_mapper.py:_calculate_local_offset_metres`, `map_waypoint_to_simulation`];
- [CÓDIGO `planning/relative_routes.py:generate_relative_route`];
- [CÓDIGO `planning/site_geometry.py:local_to_geo`, `geo_to_local`].

Las cuatro comparten `METERS_PER_DEGREE_LATITUDE`.

**Hipótesis y dominio:** Tierra localmente plana, la longitud escalada con cos φ₀ de la referencia, un radio de 1000 m como máximo y |φ| ≤ 75°.

**Ejemplo [H2]:** la misión de drone_01, con el home nominal en (41,275; 1,987), tiene WP1 en (N, E) = (8,000; −4,000) m y WP2 en (16,000; −4,000) m.

**Metros por grado según cada modelo:**

| Modelo | Latitud 41,275° | Latitud −35,363° | Fuente |
| --- | --- | --- | --- |
| Nuestro k y k·cos φ | 111 320 / 83 662,8 | 111 320 / 90 781,4 | [CÓDIGO] |
| ArduPilot, `LATLON_TO_M`·10⁷ = 111 318,845 | 111 318,8 / 83 661,9 | 111 318,8 / 90 780,4 | [AP `libraries/AP_Math/definitions.h`, `AP_Common/Location.cpp`] |
| Esfera de radio 6 371 008,8 m (nuestro haversine) | 111 195,1 | 111 195,1 | [CÓDIGO `tools/route_geometry.py`] |
| Elipsoide WGS 84 (meridiano / paralelo) | 111 059,2 / 83 784,5 | 110 947,2 / 90 882,9 | [TEORÍA] [B#19, B#20 PENDIENTES] |

**Consecuencias:**
- **Dentro de SITL,** nuestro modelo y el de ArduPilot (`Location::offset_latlng`, también plano) difieren en 1,04·10⁻⁵.
- **Frente al elipsoide,** la escala norte se desvía un 0,24 % a 41°: unos 2,3 m sobre 1 km. Solo importaría en campo.

### 5.3.2 Distancia, rumbo y redondeo de tramos

**Distancia y rumbo** [CÓDIGO `tools/route_geometry.py`]:
- distancia con el haversine de R = 6371,0088 km (`haversine_distance_km`): a = sin²(Δφ/2) + cos φ₁·cos φ₂·sin²(Δλ/2), d = 2R·atan2(√a, √(1−a));
- rumbo inicial (`calculate_initial_bearing_deg`): θ = atan2(sin Δλ·cos φ₂, cos φ₁·sin φ₂ − sin φ₁·cos φ₂·cos Δλ).

**Tramos** (`analyze_waypoint_route`): HOME → WP1 → … → WPn, más → HOME si `return_to_home`. Solo se mide la distancia horizontal. El cambio de altitud se acumula aparte (`total_climb_m`, `total_descent_m`).

**Dos escalas.** Generamos con k = 111 320 m/° y medimos con un haversine que equivale a 111 195 m/°.
- Un tramo de 8,000 m en el modelo lineal se mide como 7,991 m (razón 0,998878).
- El ejecutor usa un tercer radio, 6 371 000 m (`tools/simulation_mission_executor.py:_horizontal_distance_metres`). La diferencia relativa con el anterior es de 1,4·10⁻⁶.

**Redondeo prematuro: defecto reproducible.** Se reprodujo por el punto de entrada vigente, `tools/hermes_mission_validation.py:validate_mission`, sobre la misión de H2 con WP1 desplazado (salida, §5):

| WP1 respecto al home | `distance_km` del tramo | Resultado del tramo | `mission_status` / `execution_status` |
| --- | --- | --- | --- |
| 0,4 m al norte | 0,0 | `error`: «Distance must be greater than 0 km.» | NOT FEASIBLE / BLOCKED |
| 0,49 m | 0,0 | ídem | NOT FEASIBLE / BLOCKED |
| 0,51 m | 0,001 | `success` | FEASIBLE / APPROVED |
| 0,6 m | 0,001 | `success` | FEASIBLE / APPROVED |
| 0 m (solo vertical) | 0,0 | `error` | NOT FEASIBLE / BLOCKED |

**Propagación:**
1. `analyze_waypoint_route` guarda `round(distance_km, 3)`.
2. `analyze_mission_flight` pasa ese valor redondeado a `calculate_flight_time`.
3. `calculate_flight_time` rechaza `distance_km <= 0` con `status: "error"`.
4. `analyze_mission_flight` trata todo resultado distinto de `success` como inseguro.
5. `analyze_mission_energy` devuelve `undetermined`, sin evaluar la batería.
6. `evaluate_mission_safety` añade el motivo «One or more route legs cannot be flown under the current conditions.». No es un error de entrada, así que el estado es NOT FEASIBLE y no INVALID.
7. `generate_waypoint_replan` devuelve «Review or redesign the following unflyable route legs: HOME -> WP1.».

**Clasificación:**
- **Defecto reproducible (0 < d < 0,5 m):** un tramo horizontal real se trata como si midiera 0. El usuario recibe un motivo atribuido a las condiciones de vuelo que no corresponde. Es infrecuente con las misiones actuales, pero es reproducible.
- **Restricción intencional (d = 0 exacto):** `calculate_flight_time` exige una distancia positiva, y `planning/relative_routes.py:_local_points` documenta que «the validator rejects a zero horizontal leg».
- **Ausencia de modelo vertical:** el modelo de tiempo no tiene componente vertical. Un tramo solo vertical no puede cronometrarse, pero el motivo mostrado («cannot be flown») no lo dice.

  Un tramo vertical **no** debe pasar a ser viable sin más: falta el modelo.

**Segundo redondeo.** Antes de la corrección, la suma usaba el tiempo de cada tramo ya redondeado a 0,01 min (0,6 s), y ese total era el que recibía la batería (§5.3.3).

> La tabla y la propagación anteriores describen el validador **antes** de la corrección del 31/10/2026. Su salida se conserva en [`05_calculos/salida_verificar_05_antes_correccion.txt`](05_calculos/salida_verificar_05_antes_correccion.txt).

#### Corrección del 31/10/2026 (posterior a H2)

Autorizada por Joel el 31/10/2026. H2 (24/10) se validó y ejecutó con el comportamiento anterior; su evidencia y su resultado no cambian.

**Cálculo con precisión completa; el redondeo queda solo para mostrar:**
- [CÓDIGO `tools/route_geometry.py:analyze_waypoint_route`] añade `distance_km_exact` a cada tramo. `distance_km` sigue redondeada, para compatibilidad y presentación.
- [CÓDIGO `tools/flight_dynamics.py:calculate_flight_time`] añade `flight_time_minutes_exact`. `flight_time_minutes` sigue redondeado.
- [CÓDIGO `tools/route_flight_analysis.py:analyze_mission_flight`] calcula con `distance_km_exact`, suma los tiempos exactos y expone `total_flight_time_minutes_exact`. `total_flight_time_minutes` es ahora el redondeo de la suma exacta.
- La batería usa el total exacto: [CÓDIGO `tools/mission_energy_analysis.py:analyze_mission_energy`] para el grafo vigente y [CÓDIGO `graph/nodes.py:battery_check_node`] para el grafo escalar heredado.

**Tramos con distancia horizontal exactamente nula** [CÓDIGO `tools/route_flight_analysis.py:_zero_horizontal_leg_result`]. Ya no pasan por `calculate_flight_time`:

| Caso | Estado del tramo | Motivo para el usuario |
| --- | --- | --- |
| Con cambio de altitud | `not_modelled` (`VERTICAL_LEG_NOT_MODELLED`) | «Vertical-only route legs (…) are not evaluated: the current flight-time model covers horizontal motion only.» |
| Sin desplazamiento alguno | `no_displacement` (`NO_DISPLACEMENT`) | «Route legs without displacement (…) repeat the previous point's position and altitude.» |

Ambos se siguen rechazando (NOT FEASIBLE / BLOCKED): no se aprueban automáticamente y no se ha añadido ningún modelo vertical. El motivo lo construye [CÓDIGO `safety/mission_safety_analysis.py:evaluate_mission_safety`] y la acción, [CÓDIGO `replanning/waypoint_mission_replanner.py:generate_waypoint_replan`]. El motivo genérico se conserva para los tramos inseguros por viento.

**Sin cambios:** el viento, la batería, la dinámica, las tolerancias y los parámetros.

**Antes y después** (salidas del script, §5):

| WP1 | Antes | Después |
| --- | --- | --- |
| 0,4 m | NOT FEASIBLE, «cannot be flown» | FEASIBLE / APPROVED |
| 0,49 m | NOT FEASIBLE, «cannot be flown» | FEASIBLE / APPROVED |
| 0,51 m | FEASIBLE | FEASIBLE |
| 0,6 m | FEASIBLE | FEASIBLE |
| Vertical | NOT FEASIBLE, «cannot be flown» | NOT FEASIBLE, motivo de tramo vertical |

**Pruebas** ([`tests/test_flight_leg_precision.py`](../../tests/test_flight_leg_precision.py)):
- 0,4, 0,49, 0,5, 0,51, 0,6 y 1,4 m;
- una ruta de varios tramos de 0,3 m;
- la batería recibe el total exacto;
- el tramo vertical y el tramo sin desplazamiento;
- el viento sigue con su motivo genérico.

**Compatibilidad en la presentación:** el total mostrado es ahora el redondeo de la suma exacta y no la suma de redondeos. Puede variar 0,01 min respecto al cálculo anterior: tres tramos de 0,014 min mostraban 0,03 y ahora muestran 0,04.

### 5.3.3 Tiempo estimado, velocidad y viento

**Fórmula** [CÓDIGO `tools/flight_dynamics.py:calculate_flight_time`]. Por tramo:
- α = `radians(wind_direction_from_deg − rumbo)`;
- H = W·cos α y C = W·sin α;
- V_g = −H + √(V² − C²);
- t = d / V_g · 60, en minutos, redondeado a 0,01.

**Estados:**
- `unsafe` si |C| ≥ V o si V_g ≤ 0;
- `error` si d ≤ 0 o V ≤ 0.

**Qué significa `speed_kmh` para el planificador** [CÓDIGO `tools/route_flight_analysis.py:analyze_mission_flight`]: V es la `speed_kmh` del waypoint **de destino** o, si falta, `vehicle.cruise_speed_kmh`. Se usa como velocidad respecto al **aire** en el triángulo de viento.

**Hipótesis:**
- viento horizontal, uniforme y constante;
- V constante y aceleraciones instantáneas;
- sin despegue, subida, bajada, aterrizaje ni esperas.

**Ejemplos** (1 km, V = 35 km/h, W = 10 km/h del norte):

| Rumbo | V_g | t |
| --- | --- | --- |
| 0° | 25,00 km/h | 2,40 min |
| 90° | 33,54 km/h | 1,79 min |
| 180° | 45,00 km/h | 1,33 min |
| 45° | 27,21 km/h | 2,21 min |

Con V = 10 km/h y W = 12 km/h, el resultado es `unsafe` a 90° (lateral) y también a 0° (V_g = −2 km/h).

**Reproducción con la misión de H2** (`child_1_2f7db1f6/mission.json`; drone_02 da los mismos números). `speed_kmh` es nula en los dos waypoints, así que V = `cruise_speed_kmh` = 35 km/h. El viento es 0.

| Tramo | d exacta | d redondeada | t sin redondeo | t del validador |
| --- | --- | --- | --- | --- |
| HOME → WP1 | 8,9342 m | 0,009 km | 0,919 s | 0,02 min |
| WP1 → WP2 | 7,9910 m | 0,008 km | 0,822 s | 0,01 min |
| WP2 → HOME | 16,4739 m | 0,016 km | 1,694 s | 0,03 min |
| **Total** | 33,40 m | — | **3,435 s** | **0,06 min = 3,6 s** |

- **Fases incluidas:** solo los tres desplazamientos horizontales, a 35 km/h.
- **Fases excluidas:** la subida de 5 m (va dentro de HOME → WP1, pero no cuenta), el despegue, la bajada y el aterrizaje.
- **Origen del 3,6 s:** es el total que calculaba el validador **antes** de la corrección del 31/10: la suma de los tiempos redondeados por tramo. Ese valor **no figura** en la evidencia de H2: el validador solo lo imprime en el informe de texto, que `validate_mission` descarta, y la evidencia guarda `mission_status`.
- **Regresión de H2 tras la corrección:**
  - el estado sigue siendo FEASIBLE / APPROVED;
  - el total mostrado sigue siendo 0,06 min, ahora como redondeo de la suma exacta;
  - internamente se usa el total exacto, 0,0572557 min (3,435 s);
  - la batería requerida mostrada sigue siendo 0,05 pp, y la que decide es la exacta, 0,0458 pp.

  En estas misiones las decisiones no cambian.

**Qué órdenes envió el ejecutor en H2** [H2, `operation_diagnostics` de `report.json`; CÓDIGO `tools/ros2_flight_control.py`]:
- cambio a GUIDED;
- armado;
- `experimental/takeoff` con `alt: 5.0`;
- tres `cmd_gps_pose` con `coordinate_frame: 6` y `type_mask: 3576` (`POSITION_ONLY_TYPE_MASK`);
- LAND.

**Ninguna orden contiene velocidad.** Tampoco hay ninguna en `send_global_position_target`.

**Qué limita la velocidad, según las fuentes fijadas:**
- En GUIDED, sin la opción `WPNavUsedForPosControl`, los objetivos van al controlador de posición en NED, con la velocidad horizontal máxima `wp_nav->get_default_speed_NE_ms()` [AP `ArduCopter/mode_guided.cpp`].
- Valores por defecto [AP `libraries/AC_WPNav/AC_WPNav.cpp`]:
  - `WP_SPD` = 10 m/s;
  - `WP_SPD_UP` = 2,5 m/s;
  - `WP_SPD_DN` = 1,5 m/s.
- `copter.parm` no los cambia.

**Qué se registró en H2:** ningún parámetro y ninguna velocidad. El README de H2 lo dice: «La velocidad no se comandó ni se midió».

**Conclusión:** con viento nulo, las definiciones de velocidad respecto al aire y al suelo coinciden. Eso **no** acredita:
- que el vehículo volara a `speed_kmh` ni a 35 km/h;
- que alcanzara el límite del autopiloto;
- qué valor tenía ese límite.

Velocidades, aceleraciones y parámetros efectivos **[NO ACREDITADO]**.

**Comprobación de viento** [CÓDIGO `safety/wind_guard.py:check_wind_safety`]: se exige W ≤ `maximum_wind_speed_kmh`.

### 5.3.4 Batería

**Fórmula** [CÓDIGO `safety/battery_guard.py:check_battery_safety`]:
- requerida = t·c;
- restante = B − requerida;
- seguro si restante ≥ reserva.

Las variables son t en minutos, c en **puntos porcentuales por minuto** (pp/min, `battery_consumption_percent_per_minute`), y B y la reserva en %. Si algún tramo no es `success`, la batería no se evalúa: `analyze_mission_energy` devuelve `undetermined`.

**Hipótesis:** consumo constante en el tiempo, independiente de la velocidad, el viento, la subida o la carga. Es un porcentaje declarado, no energía.

**Ejemplo H2:** 0,06 min × 0,8 pp/min = 0,048 pp, que se redondea a 0,05 pp. Quedan 99,95 %, por encima de la reserva del 20 % → `safe`.

**Altitud** [CÓDIGO `safety/altitude_guard.py:check_altitude_safety`]: la máxima de los waypoints y el home debe ser ≤ `maximum_altitude_m`.

### 5.3.5 Altitudes relativas y absolutas

En la cadena hay cuatro referencias verticales:

1. **Misión.** Altitudes relativas al home, con el home a 0. Lo exigen `inputs/qgc_plan_export.py:refusal_reasons` y `planning/relative_routes.py:generate_relative_route`.
2. **Emplazamiento** [CÓDIGO `models/site.py:VerticalReference`, `VerticalLimits`]:
   - `origin_ground_amsl_m`, con un datum declarado como texto;
   - un límite sobre el suelo del origen.

   `planning/site_validation.py:_aerial_legs` solo compara con ese límite si el terreno es `DECLARED_FLAT`.
3. **`.plan`.** `plannedHomePosition` lleva una altitud AMSL y los ítems usan `MAV_FRAME_GLOBAL_RELATIVE_ALT` [CÓDIGO `inputs/qgc_plan_export.py:build_plan`].
4. **Ejecución:**
   - `cmd_gps_pose` con `coordinate_frame` 6, que AP_DDS traduce a `ABOVE_HOME` [AP `libraries/AP_DDS/AP_DDS_ExternalControl.cpp:convert_alt_frame`];
   - la llegada compara la altitud de geopose con la altitud del lanzamiento más `altitude_m` [CÓDIGO `tools/simulation_mission_executor.py:_wait_for_waypoint`].

**Hipótesis implícita del ejecutor:** la altitud leída antes de armar coincide con el home. Copter reinicia el home al armar si no está bloqueado [AP `ArduCopter/AP_Arming_Copter.cpp`, bloque de armado]. La deriva entre la lectura y el armado no se ha medido.

**Referencia de la altitud de geopose:**
- AP_DDS escribe `loc.alt`, con un `TODO` que *supone* WGS 84 absoluto [B#9];
- `GeoPoint` la define como altura elipsoidal [B#18];
- nuestro código la llama `altitude_amsl_m`.

Que sea AMSL o elipsoidal **[NO ACREDITADO]**. En la llegada se usa como **diferencia** entre lecturas del mismo campo, así que esa referencia se cancela.

### 5.3.6 Emplazamiento: de metros locales a coordenadas

**Conversión** [CÓDIGO `planning/site_geometry.py:local_to_geo`]: (x, y) → (N, E) por rotación con β, y (N, E) → (φ, λ) con el modelo lineal desde el origen del emplazamiento. La inversa, `geo_to_local`, reutiliza la función del ejecutor.

**Ejemplo** (`synthetic_hermes_rehearsal_v1`, origen en (−35,363262; 149,165237), β = 0):
- TAKEOFF_A (−6, −6) → (−35,363315899; 149,165170907);
- la ida y vuelta da un error de 1,2·10⁻⁹ m. Es error numérico, no fidelidad al terreno.

**Comprobaciones** [CÓDIGO `planning/site_validation.py:_aerial_legs`, `margin_status`]:
- son 2D, sobre las líneas rectas planificadas;
- perímetro, y holgura a las exclusiones ≥ el margen;
- m_req = extensión/2 + incertidumbre de posición + máx(incertidumbre de los elementos), o `NOT_ACCREDITED` si falta algún dato.

### 5.3.7 Misiones finalizadas por Hermes: cambio de base

**Pasos** [CÓDIGO `planning/scenario_instance.py:finalized_instance`]:
1. Desplazamientos (N, E) de cada waypoint respecto al home de la propia misión (`_calculate_local_offset_metres`).
2. Expresión en el marco del emplazamiento (`north_east_to_local` con β).
3. Suma a las coordenadas locales del despegue elegido.
4. Conversión con `local_to_geo`.

Las altitudes siguen relativas al home.

**Qué se conserva y qué no:**
- **Forma y orientación geográfica.** El paso 2 rota con β y `local_to_geo` deshace esa rotación, así que los desplazamientos norte/este se conservan.
  - Comprobado: con β = 0° y con β = 30°, recalcular desde el home nuevo devuelve (8,000; −4,000) m.
  - La ruta **no se gira** para alinearla con el emplazamiento. Una ruta que iba hacia el norte sigue yendo hacia el norte, aunque el eje +y del emplazamiento apunte a otro rumbo.
- **Coordenadas locales.** Las que se validan contra el perímetro y las exclusiones **sí** dependen de β.

  | β | WP1 local |
  | --- | --- |
  | 0° | (−10; 2) |
  | 30° | (−13,464; −1,072) |
- **Posición geográfica absoluta.** El despegue se define en coordenadas locales. Si se cambia β manteniendo esas coordenadas, el despegue cambia de lugar geográfico, y con él toda la ruta.
  - TAKEOFF_A (−6, −6) está en (−35,363315899; 149,165170907) con β = 0° y en (−35,363281728; 149,165146715) con β = 30°: 4,387 m de distancia.
  - Coincide con la cuerda teórica, 2·|r|·sin(15°) = 4,392 m.

**Cosenos de latitudes distintas.** La ida usa el cos φ del origen del emplazamiento; el recálculo, el del home nuevo.
- Con el despegue 1000 m al norte del origen, un desplazamiento de 100 m al este se lee como 99,986 m.
- Con 6 m, el error es de micrómetros.

**El ejecutor hace un cambio análogo** [CÓDIGO `tools/simulation_mission_mapper.py:map_mission_route_to_simulation`]:
- coloca los desplazamientos respecto al home nominal sobre la posición de lanzamiento **observada** de cada dron;
- las coordenadas absolutas de la misión (41,275; 1,987) no se vuelan.

### 5.3.8 Llegada a waypoints: cadena de posición, precisión y tolerancia

**Cadena reconstruida, con el tipo de dato en cada frontera:**

| Paso | Tipo y conversión | Dónde | Cómo se acredita |
| --- | --- | --- | --- |
| 1. Estimación del autopiloto | `Location` con `int32_t lat, lng` en 10⁻⁷ grados y `int32_t alt` en cm, obtenida con `ahrs.get_location()`. Es una **estimación**, no la posición verdadera de Gazebo | [AP `AP_Common/Location.h`; `AP_DDS_Client.cpp:update_topic(GeoPoseStamped&)`] | Fuente |
| 2. Relleno del mensaje | lat y lng: `int32` → `float32` (`cvtdq2ps`), × `float32(1e-7)` = 1,0000000116860974·10⁻⁷ (`mulps`), → `double` (`cvtps2pd`). Alt: `int32` → `float32`, × 0,01f, → `double` | [AP `AP_DDS_Client.cpp`, fuente `loc.lat * 1E-7`]; [BIN `AP_DDS_Client::update_topic(geographic_msgs_msg_GeoPoseStamped&)`, `0x31b801`–`0x31b835`] | Fuente, flags y código máquina del binario instalado |
| 3. Mensaje ROS | `geographic_msgs/GeoPoint`: `double latitude, longitude, altitude` | [AP `libraries/AP_DDS/Idl/geographic_msgs/msg/GeoPoint.idl`] | Fuente |
| 4. Texto | `ros2 topic echo /ap/vN/geopose/filtered --once`, guardado íntegro en `transport.output` | [CÓDIGO `tools/ros2_flight_control.py:get_vehicle_geopose`]; [H2 `report.json`] | 60 operaciones y 0 omitidas (drone_01); 56 y 0 (drone_02) |
| 5. Parser | Expresión regular y `float()`: double de Python | [CÓDIGO `tools/ros2_flight_control.py:_extract_float`] | Reparseado: 38 de 38 lecturas coinciden con `observation` |
| 6. Objetivo | Lanzamiento leído (pasos 1–5) + desplazamiento de la misión, en double | [CÓDIGO `tools/simulation_mission_mapper.py:map_waypoint_to_simulation`] | Recálculo |
| 7. Error | e_h = haversine (R = 6 371 000 m) entre la lectura y el objetivo; e_v = \|alt − (alt_lanzamiento + altitude_m)\| | [CÓDIGO `tools/simulation_mission_executor.py:_horizontal_distance_metres`, `_wait_for_waypoint`] | Recálculo |
| 8. Decisión | Llegada si e_h ≤ 1,0 m y e_v ≤ 0,75 m, con el vehículo armado según la lectura de estado previa | [CÓDIGO `_wait_for_waypoint`] | Recálculo |

**Flags y binario.**
- La base de compilación del build SITL del workspace (`src/ardupilot/build/sitl/compile_commands.json`, 2/10) compila `AP_DDS_Client.cpp` con `-fsingle-precision-constant` y `-O3`.
- `AP_DDS` no figura entre las bibliotecas de doble precisión (`c4che/sitl_cache.py`, `DOUBLE_PRECISION_LIBRARIES`).
- El binario instalado es idéntico al del build (mismo SHA-256).
- **No inspeccionado:** que el proceso de H2 ejecutara exactamente ese archivo. Lo indica el montaje documentado, pero no se ha comprobado sobre el proceso.

**Repetición de la decisión de H2** con las funciones del proyecto sobre el texto archivado (salida, §1):
- reproduce **exactamente** los seis errores registrados: 0,1698, 0,2070 y 0,0000 m en drone_01; 0,3883, 0,2070 y 0,8483 m en drone_02;
- todas las lecturas anteriores a cada llegada estaban fuera de tolerancia.

**Qué está demostrado y qué no:**

| Concepto | Qué es | Valor |
| --- | --- | --- |
| Valores archivados compatibles con float32 | Hecho: los 38 valores de posición de H2 son exactamente representables en float32 | La probabilidad de que un double cualquiera lo sea es de ~2⁻²⁹ por valor |
| Cuantización y dónde ocurre | Demostrada en el binario instalado, en el paso 2: conversión `int32` → `float32` y producto en `float32`. Para el proceso de H2 es la explicación compatible (véase arriba) | — |
| Paso de representación | Separación entre floats consecutivos en la latitud y longitud de H2: 2⁻¹⁸° y 2⁻¹⁶° | 0,4247 m N y 1,3852 m E con 111 320 m/° (0,4232 m y 1,3868 m con WGS 84, B#19 pendiente) |
| Semidiagonal (0,724 m) | Distancia máxima de un punto a la intersección más cercana de la malla float32, **con un solo** redondeo correcto en cada coordenada: √(0,2123² + 0,6926²) | No es la cota de esta cadena |
| Error de representación de la cadena: **cota demostrada** | Con redondeo IEEE al más próximo y la expresión del binario, \|salida − i·10⁻⁷\| ≤ ulp(salida)/2 + \|fl(i) − i\|·c_f + \|i\|·\|c_f − 10⁻⁷\|. Vale mientras \|lat\| ∈ [32°, 64°), \|lon\| ∈ [128°, 256°) y los enteros estén en [2²⁸, 2²⁹) y [2³⁰, 2³¹). El último término depende de \|i\| | Evaluada en la latitud y longitud de H2: 3,920·10⁻⁶° = 0,436 m N y 1,577·10⁻⁵° = 1,432 m E. Sin el sesgo de la constante, que es sistemático y se cancela casi del todo en diferencias: 0,390 m N y 1,273 m E |
| Error de representación: **máximo observado** en la emulación | Emulación exacta de la expresión sobre ±262 144 enteros alrededor de H2 (salida, §3) | Alcanza la cota anterior: 0,436 y 1,432 m. Es un máximo de esa muestra; la cota no se deriva de ella |
| Errores de llegada de H2: **máximos observados** | Valores registrados: 0,848 m como máximo horizontal; ≤ 0,03 m vertical en waypoints y regreso; 0,55 m en el despegue de drone_02 (tolerancia 0,75 m) | Describen una sesión. No son cotas de nada |
| Error en e_h por representación | e_h compara dos lecturas, la actual y la del lanzamiento que fija el objetivo: los errores pueden sumarse o cancelarse | El regreso de drone_01 dio 0,0000 m porque las dos lecturas cayeron en la misma celda float32. Cota de la peor combinación sin estudiar |
| Error total respecto a la posición verdadera | Suma del error del estimador (AHRS frente a Gazebo, no registrado), la resolución `int32` (~1 cm) y la representación | **[NO ACREDITADO]**; ni la semidiagonal ni las cifras anteriores lo acotan |

**Qué acredita el PASSED histórico de H2** (sin cambiar la tolerancia ni el resultado). Para cada waypoint y para el regreso, en una lectura concreta:
- la posición **estimada** por el autopiloto y publicada por AP_DDS, ya cuantizada a float32, estaba a ≤ 1,0 m (haversine) y ≤ 0,75 m en vertical de un objetivo;
- ese objetivo se había calculado a partir de **otra lectura** del mismo canal (el lanzamiento) más los desplazamientos de la misión.

**No acredita:**
- la distancia verdadera entre el vehículo de Gazebo y el punto;
- la llegada a las coordenadas absolutas de la misión;
- la exactitud del estimador;
- que el vehículo permaneciera dentro de la tolerancia.

**Instante de llegada.** El registrado es el de la primera lectura que cumple la condición. Por ejemplo, en WP1 de drone_01 [H2]:
- lectura previa entre 12:53:00,292 y 12:53:04,550, a 1,28 m;
- lectura de llegada entre 12:53:08,574 y 12:53:10,925.

El retraso entre la entrada real en la tolerancia y la detección **no se puede acotar** con el intervalo máximo observado entre lecturas, porque no están acreditadas:
- la **frescura** del mensaje: cuándo lo generó el autopiloto respecto a la ventana de lectura;
- la **entrega**: QoS y posibles mensajes perdidos;
- la **persistencia** de la condición entre lecturas.

Las marcas `header.stamp` del texto archivado, leídas como época UTC, quedan unos 100 s antes de la ventana de lectura del anfitrión (p. ej. 12:49:54,5 frente a 12:51:39,8–12:51:43,3). La fuente de esas marcas puede ser `/clock` externo, el RTC o `micros64` [AP `AP_DDS_Client.cpp:update_topic(builtin_interfaces_msg_Time&)`]. Cuál estuvo activa en H2 **[NO ACREDITADO]**. Sin una correspondencia acreditada entre relojes, esos ~100 s **no** son un retraso ni una antigüedad del mensaje: solo muestran que los dos dominios no coinciden. No se usan para convertir tiempos.

## 5.4 Capa 2: autopiloto (no es código del proyecto)

Solo lo leído en las fuentes fijadas. No se describen las ecuaciones del EKF ni de los controladores.

- **Modelo geográfico.**
  - `Location::offset_latlng` usa `LATLON_TO_M` (R = 6 378 100 m) y escala la longitud con el coseno de la latitud media;
  - `Location::get_distance` usa la norma plana con la misma escala.

  [AP `libraries/AP_Common/Location.cpp`, `libraries/AP_Math/definitions.h`]
- **GUIDED.** Véase §5.3.3. Los valores efectivos de los parámetros **[NO ACREDITADO]**.
- **Estimación.** `geopose/filtered` publica `ahrs.get_location()`, una estimación. La diferencia con la verdad no se registra en nuestras ejecuciones.
- **Batería.** Lectura de las fuentes y de la configuración instalada, no de las ejecuciones:
  - `copter.parm` fija `BATT_MONITOR` = 4;
  - con el backend JSON, SITL toma la tensión y la corriente del mensaje JSON si las trae; si no, usa `SIM_BATT_VOLTAGE` y una corriente de 0 [AP `libraries/SITL/SIM_JSON.cpp`];
  - el `ArduPilotPlugin` fijado no escribe la clave `battery` [GZ `src/ArduPilotPlugin.cc`].

  Si las ejecuciones usaron esos binarios y modelos, la batería que ve ArduPilot no se descargaría con el vuelo. **No es una afirmación sobre todas las ejecuciones efectivas.** Ninguna de nuestras ejecuciones registró la batería (informe de señales del piloto del dataset, `pilot/reports/signals.md`, en el repositorio del dataset). Su comportamiento real **[NO ACREDITADO]**.
- **Viento.** También lectura de fuentes:
  - `SIM_JSON.cpp` dice «wind is not supported yet for JSON sim, assume zero» cuando no recibe velocidad de aire, y solo usa viento si el mensaje trae `velocity_wind`;
  - el plugin fijado no lo envía;
  - el mundo no declara un sistema de viento (§5.5.1).

  Que ninguna ejecución tuviera viento es lo que se espera de esta configuración, pero **[NO ACREDITADO]** en ejecución.

## 5.5 Capa 3: simulador físico (configuración, no ecuaciones)

### 5.5.1 Mundo `runway`

[GZ `ardupilot_gz/ardupilot_gz_gazebo/worlds/runway.sdf`; la copia instalada tiene el mismo hash]:
- paso de 0,001 s y `real_time_factor` 1,0 (objetivo, no medido);
- sistemas de física, sensores, IMU, navsat, presión, velocidad de aire, altímetro y magnetómetro;
- `spherical_coordinates` (−35,3632621; 149,1652374), con elevación de 10,0 m y `EARTH_WGS84`.

No declara viento, gravedad ni un motor de física concreto. El motor y la gravedad efectivos **[NO ACREDITADO]**.

**Launch del repositorio** (`simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py`):
- drone1 en x = −2 m y drone2 en x = +2 m, con un yaw de 1,5708 rad;
- su copia en el contenedor no se inspeccionó.

### 5.5.2 Modelo `iris_with_gimbal`

[GZ `models/iris_with_gimbal/model.sdf`, `iris_with_standoffs/model.sdf`]. La copia instalada difiere solo en dos URI.

| Elemento | Valores declarados |
| --- | --- |
| Masas | 1,98 kg en total: base 1,5; IMU 0,15; rotores 4 × 0,025; cardán 0,23 |
| Inercias de la base | I_xx = 0,008 kg·m², I_zz = 0,017 kg·m² |
| Rotores | 8 instancias de `LiftDrag`: `cla` 4,25, `cda` 0,10, `area` 0,002 m², `air_density` 1,2041 |
| Accionamiento | `ApplyJointForce` |
| Control de giro en `ArduPilotPlugin` | Tipo `VELOCITY`, `multiplier` 838, `p_gain` 0,20 |
| Batería de Gazebo | `LinearBatteryPlugin` (3,5 Ah, `start_draining` false); el plugin de ArduPilot no la envía |

Las ecuaciones de `LiftDrag` (en `gz-sim`, código no inspeccionado) **[NO ACREDITADO]**.

### 5.5.3 Interfaz con SITL y relojes

- **El plugin envía** la pose y la velocidad verdaderas del enlace de la IMU, transformadas con `gazeboXYZToNED` = (0 0 0 180° 0 90°), y las medidas de la IMU de Gazebo [GZ `ArduPilotPlugin.cc`].
  - El propio código deja un `todo` que duda de la inversa usada.
  - La correspondencia entre el spawn y el marco geográfico **[NO ACREDITADO]**.
- **SITL** calcula su posición «verdadera» con `origin.offset(x, y)` y la altitud como `home.alt − z` [AP `libraries/SITL/SIM_Aircraft.cpp:update_position`].
- **Relojes:**
  - el plugin funciona en *lockstep* y el launch de SITL usa `synthetic_clock` True;
  - el tiempo simulado puede apartarse del real, y el factor de tiempo real de H2 no se registró;
  - el ejecutor y el dataset miden con el reloj del anfitrión.
- **Orígenes [H2]:**
  - `simulation_origin` es `/ap/vN/gps_global_origin/filtered`, el origen del estimador [CÓDIGO `tools/ros2_flight_control.py:get_vehicle_global_origin`]. Valía (−35,36326217651367; 149,1652374267578; 584,0).
  - En float32 es indistinguible de las coordenadas del mundo y de CMAC (`Tools/autotest/locations.txt`).
  - La altitud de 584 m no es la elevación de 10 m del mundo.
  - [`docs/site-fleet-export.md`](../site-fleet-export.md) §3 llama a ese valor «origen del mundo Gazebo»: posible imprecisión terminológica, no corregida.

## 5.6 Limitaciones que pueden afectar a nuestros resultados

1. **Aproximación geográfica local.** Es coherente con SITL a 10⁻⁵; frente a WGS 84 hay unos 2,3 m por km. Además, generar y medir usan escalas distintas (0,11 %).
2. **Referencias verticales.** Hay cuatro. La llegada es diferencial, pero supone que la altitud del lanzamiento coincide con el home. La naturaleza AMSL o elipsoidal de la altitud de geopose no está acreditada.
3. **Viento.** El planificador lo modela; según las fuentes, la configuración de simulación no lo aplica (§5.4). Ninguna predicción con viento puede contrastarse hoy.
4. **Consumo lineal en puntos porcentuales por minuto.** No es energía, y la batería simulada no se ha registrado.
5. **Tiempos.** Los intervalos disponibles no miden lo mismo:

| Intervalo | Dominio | Definición | Valor (drone_01) |
| --- | --- | --- | --- |
| Desplazamiento horizontal previsto | Modelo del validador: tiempo físico supuesto | Tres tramos a 35 km/h, sin despegue, subida ni aterrizaje | 3,435 s (exacto; desde el 31/10 es el que usa el validador). 3,6 s con el cálculo anterior |
| Nodo `execute` | UTC del anfitrión | Del inicio al fin del nodo, con lecturas de origen, preparación, órdenes, esperas, sondeos y aterrizaje | 253,76 s [H2 `report.json`, `transitions`] |
| Indicador `flying` | UTC del anfitrión, a partir de las lecturas de estado | Estimación condicionada a las hipótesis H1–H4 del dataset 0.2.1 | 202,5–220,1 s (repositorio del dataset, `docs/DATA_DICTIONARY.md`) |
| De la orden a la lectura de llegada | UTC del anfitrión | Incluye la publicación de la orden (unos 3 s), la ejecución del controlador, los sondeos de 2 s y las lecturas de 2–5 s | WP1: 33,4 s; WP2: 25,9 s; regreso: 45,5 s [H2] |
| Tiempo simulado | Reloj de SITL y Gazebo | No registrado | **[NO ACREDITADO]** |

   Ninguno de los intervalos observados aísla el desplazamiento horizontal ni está en el mismo dominio que la predicción, y no hay correspondencia acreditada entre el tiempo simulado y el del anfitrión. **Por eso todavía no puede calcularse un error válido de predicción** comparando 3,6 s con unos 200 s.

   Hay factores por comprobar (sin atribuirles la diferencia):
   - las fases que el modelo omite;
   - la ejecución real del controlador: velocidades y aceleraciones;
   - la sobrecarga de órdenes y sondeos;
   - el avance del tiempo simulado.

   Tampoco se usa el factor de tiempo real de otra sesión.
6. **Telemetría dispersa y cuantizada.**
   - Hay una lectura de posición cada pocos segundos [H2].
   - La resolución es de 0,42 × 1,39 m. La cota demostrada del error de representación por lectura, sin el sesgo sistemático, es de 0,39 × 1,27 m (§5.3.8). El error total frente a la posición verdadera no está acotado.
   - El instante de llegada no tiene una cota de retraso acreditada.

## 5.7 Hallazgos revisados (31/10)

| Id | Hallazgo | Clasificación |
| --- | --- | --- |
| I1 | Redondeo de la distancia de tramo antes del tiempo: 0 < d < 0,5 m → NOT FEASIBLE con un motivo de condiciones de vuelo | Defecto reproducible, **corregido el 31/10 (posterior a H2)** (§5.3.2) |
| I1b | Tramo exactamente vertical → NOT FEASIBLE con el mismo motivo | Sigue rechazado; **desde el 31/10** con un motivo específico, y se distingue el tramo sin desplazamiento |
| I2 | `speed_kmh` es velocidad de aire para el planificador; el ejecutor no envía velocidad | Hecho de código; la velocidad efectiva no está acreditada (§5.3.3) |
| I3 | Generar con 111 320 m/° y medir con haversine | Hecho de código; −0,11 % |
| I4 | Cosenos de latitudes distintas al cambiar de base | Hecho de código; ≤ 1,4·10⁻⁴ dentro de 1 km |
| I5 | `altitude_amsl_m` para un campo de referencia no acreditada | Nombre más fuerte que la evidencia; sin efecto en la llegada |
| I6 | Representación float32 en geopose frente a la tolerancia de 1 m | Cuantización demostrada en el binario instalado; error total no acreditado (§5.3.8) |
| I7 | Batería planificada frente a la batería SITL | Lectura de fuentes; comportamiento efectivo no acreditado |
| I8 | El regreso planificado baja hasta el home; el ejecutor regresa a la última altitud y aterriza | Solo afecta a `total_descent_m` |
| I9 | «Origen del mundo Gazebo» en `docs/site-fleet-export.md` §3 | Terminológico |

## 5.8 Mejoras candidatas, para después del núcleo funcional

No sustituyen la arquitectura ni añaden controladores. Ninguna se implementa ahora.

| Limitación | Mejora | Datos necesarios | Ensayo | Prioridad |
| --- | --- | --- | --- | --- |
| Parámetros y velocidad del autopiloto desconocidos (I2, I7) | Registrar los parámetros efectivos (`WP_SPD`, `WP_SPD_UP`, `WP_SPD_DN`, `LAND_*`, `SIM_BATT_*`, `BATT_*`) y el tema de batería en cada ejecución | Lectura de parámetros y temas al inicio y al final | Una ejecución SITL | **Alta** |
| Tiempos de dominios distintos (§5.6.5) | Primero, acreditar la correspondencia entre el tiempo simulado, `header.stamp` y la UTC del anfitrión. Después, un modelo por fases con los parámetros registrados | Fuente de reloj activa en AP_DDS, tiempo simulado y marcas por fase (fase 1 del registro, el subsistema rover) | N ejecuciones de la misma misión: error por fase en un único dominio | **Alta** |
| Representación float32 frente a la tolerancia (I6) | Calcular el error de llegada también desde una fuente sin conversión a float32, si AP_DDS la publica, y justificar la tolerancia | Qué temas de pose local publica AP_DDS y con qué tipos | La misma ejecución con los dos errores comparados | **Media** |
| Redondeo prematuro y tramo vertical (I1, I1b) | **Hecho el 31/10** (§5.3.2). Pendiente: incorporarlo a la próxima versión de la entrega de estudiantes | — | Pruebas offline superadas | — |
| Viento modelado pero no simulado | Solo tras comprobar cómo inyectarlo en la configuración fijada | Fuentes de `gz-sim` y del plugin | Vuelo con viento conocido | Baja |

## Fuentes nuevas de este capítulo (propuestas para añadir a 04)

| # | Referencia | Enlace | Estado | Qué respalda | Sección |
| --- | --- | --- | --- | --- | --- |
| N#1 | R. Mahony, V. Kumar y P. Corke, «Multirotor Aerial Vehicles: Modeling, Estimation, and Control of Quadrotor», *IEEE Robotics & Automation Magazine* 19(3), pp. 20–32, 2012 (artículo IEEE 6289431) | https://researchportalplus.anu.edu.au/en/publications/multirotor-aerial-vehicles-modeling-estimation-and-control-of-qua/ | METADATOS; DOI por confirmar | Modelo de sólido rígido como teoría | §5.2.5 |
| N#2 | R. W. Beard y T. W. McLain, *Small Unmanned Aircraft: Theory and Practice*, Princeton University Press, 2012 (ISBN 978-0-691-14921-9), cap. 2.3–2.4 | https://github.com/randybeard/uavbook | METADATOS; pasaje sin leer | Velocidad de aire, de suelo y triángulo de viento | §5.2.4 |
| N#3 | J. Solà, «Quaternion kinematics for the error-state Kalman filter», arXiv:1711.02508, 2017 | https://arxiv.org/abs/1711.02508 | METADATOS; leer la sección 3 | Convenio de Hamilton | §5.2.3 |

**Pendientes:**
- B#19 (WGS 84) y B#20 (aproximación plana y radio del meridiano), sin cita.
- B#17 (REP 103) puede pasar a VERIFICADA. No se ha modificado 04.
