# Capítulo 2 (BORRADOR): Estado del arte

> **Estado:** primer borrador, 31/10/2026, para revisarlo con Toni. **No está listo para entregar.** No es una revisión sistemática: las fuentes son pocas y se eligieron por su relación con las preguntas del capítulo.
>
> **Verificación de cada fuente** (la tabla final dice cuál tiene cada una):
> - **VERIFICADA:** se leyó la fuente primaria y se confirmó el pasaje citado.
> - **COMPLETA:** se leyó el cuerpo completo de la versión indicada (y sus materiales oficiales cuando se dice). Se citan sección y tabla.
> - **RESUMEN:** se leyó el resumen en la página oficial (arXiv, editorial o repositorio institucional). Solo respalda lo que dice ese resumen; los detalles del cuerpo del artículo **no** se citan.
> - **METADATOS:** solo autoría, sede e identificador. **No respalda ninguna afirmación de contenido.**
> - **PENDIENTE:** sin verificar; no se usa.
>
> **Estado del arte frente a nuestro proyecto:** las frases sobre este TFG van marcadas **[PROYECTO]** y remiten a los borradores [`02_arquitectura.md`](02_arquitectura.md), [`03_metodologia.md`](03_metodologia.md) y [`05_fundamentos_matematicos.md`](05_fundamentos_matematicos.md). Las referencias [B#n] son las de [`04_bibliografia_comentada.md`](04_bibliografia_comentada.md), y las [E#n] las de la tabla final de este capítulo.

## 2.1 ¿Qué aportan los agentes LLM con herramientas a las misiones robóticas?

**El patrón general.** Los modelos de lenguaje pueden alternar razonamiento y acciones sobre fuentes externas:
- en ReAct, el razonamiento sirve para planificar y revisar el plan, y las acciones obtienen información de una API externa [B#1, RESUMEN];
- en robótica, ese paso de la instrucción en lenguaje natural a acciones se ha planteado de varias maneras, que difieren sobre todo en **qué limita lo que el modelo puede proponer**.

**Anclaje en capacidades.** SayCan combina el conocimiento de alto nivel del modelo con habilidades preentrenadas del robot [E#1, RESUMEN]:
- las funciones de valor de esas habilidades restringen las propuestas a acciones factibles en el entorno;
- se evaluó con manipulación móvil en el mundo real.

**Biblioteca de funciones.** Vemprala et al. estudian experimentalmente ChatGPT en robótica [E#2, RESUMEN]:
- combinan principios de diseño de *prompts* con una biblioteca de funciones de alto nivel;
- las tareas incluyen navegación aérea y manipulación;
- concluyen que el modelo puede resolver varias de esas tareas.

**Drones.** Varios trabajos recientes aplican el patrón a UAV:
- **TypeFly** [E#3, COMPLETA; ficha en §2.5.1]: identifica la latencia como problema, porque el modelo genera el plan *token* a *token* (§1–2).
  - GPT-4 escribe planes en MiniSpec, un lenguaje compacto que solo puede llamar a habilidades del sistema y con bucles acotados.
  - El plan se interpreta mientras se genera, y el modelo vuelve a intervenir durante la ejecución con `probe` y `replan` (§5–6).
  - Con un Tello en una oficina, el tiempo de respuesta baja hasta un 62 % (§7.3.1).
- **Lim et al.** [E#4, RESUMEN]:
  - marco abierto con PX4, ROS 2 y modelos locales servidos con Ollama;
  - comparan cuatro familias de LLM para generar órdenes y tres de modelos de visión y lenguaje para entender la escena;
  - lo evalúan en simulación y en un cuadricóptero propio.
- **PEACE** [E#5, RESUMEN]: el modelo planifica en **una sola pasada**, fuera del lazo de control.
  - Las acciones pasan por una interfaz de herramientas en ROS 2 conectada a MAVLink.
  - Una capa de restricciones impone límites de altitud y una geovalla horizontal.
  - Un mecanismo de replanificación acotada atiende los fallos de ejecución.
  - Se evaluó en PX4 SITL con Gazebo.

**Herramientas estandarizadas.** La forma de exponer herramientas al modelo empieza a normalizarse. El Model Context Protocol define servidores que ofrecen *tools*, *resources* y *prompts* a los clientes mediante JSON-RPC [B#4, VERIFICADA].

**Síntesis:**
- El modelo aporta **interpretación del lenguaje y descomposición de tareas**, y ejecuta acciones a través de interfaces definidas por los desarrolladores.
- Los trabajos difieren en dónde colocan el modelo respecto al control: en el lazo o en un único plan previo. Difieren también en cómo acotan sus propuestas: por capacidades, por funciones expuestas o por una capa de restricciones.

**[PROYECTO]** Hermes propone y finaliza misiones con solo dos herramientas MCP, de borrador y de finalización, y nunca está en el lazo de vuelo (§4.3). Con MCP, la lista de herramientas la publica el servidor, y restringirla es una decisión de la aplicación, no del protocolo.

## 2.2 ¿Qué problemas de fiabilidad, autorización y validación plantean?

**Fiabilidad.** La generación de lenguaje con modelos profundos tiende a «alucinar» texto no buscado, lo que degrada el rendimiento y defrauda las expectativas del usuario [B#3, RESUMEN].
- Usar fuentes externas lo reduce en las tareas de pregunta y respuesta evaluadas en ReAct [B#1, RESUMEN].
- **No** hay en estas fuentes una garantía de que lo elimine.
- PEACE motiva su diseño precisamente con el riesgo de alucinación y de latencia que tiene mantener el modelo en un lazo estrecho de control [E#5, RESUMEN].

**Seguridad frente a instrucciones maliciosas.** Robey et al. muestran que los robots controlados por LLM pueden ser inducidos a ejecutar acciones físicas dañinas [E#6, RESUMEN]:
- probaron un sistema de conducción, un robot terrestre Jackal con planificador GPT-4o y un cuadrúpedo Go2;
- sus ataques tuvieron éxito con frecuencia, a menudo en el 100 % de los casos.
- **Consecuencia para el diseño:** la decisión de actuar no puede depender solo del modelo.

**Autorización.** La especificación de MCP establece que el *host* debe obtener el consentimiento explícito del usuario antes de invocar cualquier herramienta, y que el protocolo **no puede imponerlo**: corresponde a la aplicación [B#4, VERIFICADA].

**Validación.** En las fuentes leídas aparecen tres mecanismos:
1. restringir las propuestas a acciones factibles (SayCan [E#1]);
2. exponer solo funciones de alto nivel definidas por el desarrollador [E#2];
3. comprobar cada plan con una capa de restricciones antes de enviarlo (PEACE [E#5], que impone altitud y geovalla).

[PENDIENTE] Las propuestas de verificación formal de planes generados por LLM (por ejemplo, con lógica temporal) no se han leído y no se citan.

**[PROYECTO]** El TFG combina dos de esos mecanismos y separa tres conceptos (§4.1 y M.1):
- **restricción de herramientas;**
- **validación determinista**, que da la viabilidad y el estado APPROVED;
- **autorización explícita del operador**, por operación. APPROVED no la sustituye.

## 2.3 ¿Cómo se coordinan vehículos aéreos y terrestres en agricultura?

**Contexto.** Una revisión de robótica cooperativa en agricultura constata que [E#9, RESUMEN]:
- abundan los robots individuales para monitorizar, pulverizar, cosechar o transportar;
- los equipos cooperativos están menos extendidos y son una tendencia emergente.

[PENDIENTE] No se han leído las categorías ni los retos del cuerpo de esa revisión.

**Reparto de papeles.** Los dos sistemas leídos reparten los papeles según las capacidades de cada vehículo:
- **Flourish** [E#7, COMPLETA; ficha en §2.5.1]:
  - un DJI Matrice 100 cartografía el campo y estima la presión de malas hierbas, y envía las áreas de mayor presión a un Bosch BoniRob, que las trata con estampado o pulverización (§II, §VI);
  - intercambian por Wi-Fi solo poses, áreas de interés, peticiones y estados, porque la comunicación tiene pérdidas, y las misiones se organizan con un planificador de tareas de ROS (§V-C);
  - la canalización completa se probó en una demostración pública en campo en 2018, sin resultados cuantitativos en el texto (§VI).
- **Tokekar et al.** [E#8, RESUMEN]:
  - el UGV transporta al UAV hasta puntos de despliegue para ahorrar su batería;
  - el UAV visita, dentro de su presupuesto de energía, los puntos con más probabilidad de clasificarse mal en el mapa de nitrógeno;
  - el UGV mide en un disco alrededor de cada punto visitado;
  - dan algoritmos de aproximación con garantías de factor constante y los evalúan en simulación con mediciones de suelo reales.

**Síntesis.** En estos trabajos la coordinación se resuelve con planificación y cartografía compartida.
- En Flourish, la IA está en la percepción (bosques aleatorios y redes convolucionales para distinguir cultivo y maleza) y la planificación usa procesos gaussianos y CMA-ES. No hay modelos de lenguaje (§III, §V-A).
- En Tokekar et al. el resumen no menciona modelos de lenguaje.

[PENDIENTE] Faltan fuentes sobre coordinación de equipos heterogéneos con LLM y revisiones recientes de cooperación UAV–UGV.

**[PROYECTO]** El escenario agri_demo_001 es mucho más sencillo y no es un sistema agrícola (§4.5):
- dos drones visitan puntos de interés declarados;
- el rover debe visitar un punto ya alcanzado por un dron;
- la dependencia se cumple por **resultado observado**, nunca por tiempo de espera;
- no hay percepción agrícola.

## 2.4 ¿Qué permiten evaluar SITL y los datasets de telemetría, y qué limitaciones tienen frente a hardware?

**Qué permite SITL.** El simulador *software in the loop* de ArduPilot ejecuta el código de Plane, Copter o Rover como ejecutable nativo, sin hardware, y puede conectarse a simuladores externos como Gazebo mediante su interfaz JSON [B#7, B#11, VERIFICADAS]. Permite evaluar la cadena de software completa, desde la orden hasta la respuesta del autopiloto y del modelo físico, sin riesgo y de forma repetible.
- **[PROYECTO]** Así el TFG puede probar su cadena contra el código real del autopiloto sin hardware ni controlador propio.
- Los trabajos de drones con LLM citados también evalúan en SITL con Gazebo (PEACE [E#5]) o en simulación y en un cuadricóptero propio [E#4].

**Limitaciones frente a hardware:**
- Zhao et al. resumen el problema en aprendizaje por refuerzo: la diferencia entre el mundo simulado y el real degrada las políticas al transferirlas a robots físicos [B#28, RESUMEN]. Es una encuesta sobre políticas aprendidas; extenderla a un autopiloto convencional en SITL es una **inferencia nuestra**, no una conclusión de la fuente.
- **[PROYECTO]** En nuestro caso, las limitaciones concretas se han documentado en la configuración y la evidencia propias, no en la literatura (§5.4–5.6 del borrador 05):
  - según la lectura de las fuentes de la configuración, la batería y el viento no se aplicarían en ninguna capa (no acreditado en ejecución);
  - las posiciones pasan por float32;
  - los tiempos simulado y del anfitrión no tienen correspondencia acreditada.

**Datasets de telemetría:**
- **ALFA** [E#10, COMPLETA; ficha en §2.5.1] reúne 47 secuencias de vuelo autónomo real de un avión de ala fija con ArduPlane modificado para inyectar fallos súbitos de motor y de superficies de control (§2, Tabla 1).
  - Documenta la frecuencia de cada tema registrado (Tabla 2) y declara que la verdad de referencia puede llegar hasta 0,2 s después del fallo.
  - Ofrece varios formatos y propone métricas de detección (§3–4).
  - Sus autores señalan que la mayoría de métodos de detección de fallos se prueban solo en simulación (§1).
- **Documentación:** las *datasheets for datasets* proponen documentar la motivación, la composición, la recogida y los usos recomendados de cada dataset [B#25, RESUMEN].

**Síntesis.** SITL permite evaluar la lógica de decisión y la integración con el autopiloto real. No permite afirmar comportamiento físico, consumo ni rendimiento en campo. Un dataset de SITL es útil para estudiar la cadena de software y su registro, pero no sustituye a datos de vuelo real como los de ALFA.

**[PROYECTO]** El dataset del TFG es solo de simulación y lo declara en cada registro (M.5).

## 2.5 Trabajos relacionados

TypeFly, Flourish y ALFA se resumen a partir del texto completo. Los demás, **solo a partir de sus resúmenes**: en ellos, «No consta» significa que el resumen no lo dice, no que el trabajo carezca de ello.

| Trabajo | Objetivo | Vehículos | Papel de la IA | Validación de las acciones | Entorno de evaluación | Limitaciones declaradas |
| --- | --- | --- | --- | --- | --- | --- |
| SayCan [E#1] | Ejecutar instrucciones largas y abstractas | Robot manipulador móvil | El LLM aporta conocimiento de la tarea | Las funciones de valor de las habilidades limitan las acciones a las factibles | Mundo real | No consta |
| ChatGPT for Robotics [E#2] | Estudiar ChatGPT en tareas robóticas | Varios, incluida navegación aérea | Genera soluciones con una biblioteca de funciones | Funciones de alto nivel definidas por el desarrollador | Simuladores; diálogo con el usuario | No consta |
| TypeFly [E#3] | Controlar drones con un LLM con menos latencia | Ryze Tello, en interior | GPT-4 escribe planes MiniSpec en *streaming*; `probe` y `replan` durante la ejecución; YOLOv8 describe la escena | Lenguaje restringido a habilidades del sistema y con bucles acotados; `replan` ante errores; el usuario puede detener la ejecución (§4–5) | Hardware real en una oficina; 11 tareas × 10 ejecuciones (§7) | Sin memoria de observaciones ni modelo del entorno; mala estimación del tamaño de obstáculos; no entiende cambios de escena implícitos; coste de los *prompts* (§7–8) |
| Lim et al. [E#4] | Control de drones en lenguaje natural con modelos abiertos | Dron PX4 | LLM para órdenes, VLM para la escena | No consta | Simulación y cuadricóptero propio | No consta |
| PEACE [E#5] | Agente planificador–ejecutor con restricciones | Drones PX4 | Planificación en una pasada | Capa de restricciones (altitud, geovalla) y replanificación acotada | PX4 SITL con Gazebo | No consta; solo afirma viabilidad en simulación |
| Flourish [E#7] | Reconocimiento aéreo e intervención terrestre selectiva | DJI Matrice 100 y Bosch BoniRob | Bosques aleatorios y redes convolucionales para cultivo y maleza; procesos gaussianos y CMA-ES en la planificación; sin LLM | Un clasificador bayesiano confirma la detección antes de tratar (§VI-B) | Campo (remolacha, Italia); simulación para la planificación del UAV; demostración pública en 2018 (§V-A, §VI) | No hay sección de limitaciones. Indica que el GPS solo no basta para la cartografía y que los RTK comerciales son poco robustos (§IV) |
| Tokekar et al. [E#8] | Muestreo de nitrógeno con UAV y UGV | UAV transportado por un UGV | Planificación con algoritmos de aproximación (sin LLM) | Garantías de aproximación de factor constante | Simulación con mediciones de suelo reales | No consta |
| ALFA [E#10] | Datos reales para la detección de fallos y anomalías | Carbon Z T-28 con ArduPlane modificado | No aplica (dataset) | Verdad de referencia por tema, con un retraso de hasta 0,2 s | Vuelos reales cerca de Pittsburgh (§3) | Dataset incompleto: faltan fallos de sensores y graduales, y se excluyen los que podrían causar la pérdida del avión (§5) |

### 2.5.1 Fichas de lectura completa

En cada ficha, **Declarada** recoge lo que dicen los autores y **Observación propia**, una lectura nuestra que no se presenta como defecto del trabajo.

#### TypeFly [E#3]

*Leído:* arXiv:2312.14950v2, texto completo (§1–8 y referencias), y la página oficial del proyecto (código y vídeos). La versión de IEEE TMC (2025) no se ha leído.

1. **Problema y contribución.**
   - **Problema:** la latencia de controlar un dron con un LLM, porque el plan se genera *token* a *token* (§1–2).
   - **Contribución:** el sistema TypeFly; el lenguaje MiniSpec, con la habilidad `probe` y la palabra clave `replan`; y la interpretación del plan mientras se genera (*Stream Interpreting*) (§1).
2. **Arquitectura y papel de la IA** (§4–6):
   - el generador de *prompts* envía la sintaxis de MiniSpec, la tarea, una descripción textual de la escena (producida por YOLOv8 en un servidor local) y ejemplos;
   - GPT-4, por API, devuelve un plan MiniSpec en *streaming*, y el *runtime* lo interpreta llamando a habilidades del sistema;
   - `probe` consulta al LLM durante la ejecución, y `replan` regenera el plan ante errores de sintaxis o fallos mecánicos;
   - el usuario da la tarea, ve el registro y el vídeo, y puede detener la ejecución.
3. **Vehículo y entorno:** un Ryze Tello con cámara frontal y un servidor local con una RTX 4090. Las pruebas son en una oficina real; no se describe simulación (§6, §7.1).
4. **Experimentos** (§7, Tablas 1–3). Once tareas en cinco categorías, diez ejecuciones cada una. Métricas: éxito, tiempo de respuesta, tiempo de compleción y *tokens*.
   - **Tabla 2:** éxito 10/10 salvo en la tarea 9 (7/10), y tiempos de respuesta de 1,10 a 1,60 s.
   - **MiniSpec** reduce el tiempo de respuesta hasta un 32 %, y hasta un 62 % con interpretación en *streaming*; los *tokens* de salida bajan un 34 % de media (§7.3.1).
   - **Tabla 3:** sin `replan`, la tarea 9 pasa de 7/10 a 0/10 y la tarea 10, de 10/10 a 8/10.
   - La categoría «seguridad» (tarea 11) evalúa que los planes terminen, gracias a los bucles acotados; no evalúa seguridad física (Tabla 1, §5.1.2).
   - Hay ablaciones, pero no una comparación con otros sistemas: usan otras plataformas o simuladores y otro hardware, y sus habilidades y *prompts* son específicos (§7).
5. **Declarada:**
   - no tiene memoria de observaciones ni modelo del entorno (§8);
   - no estima bien el tamaño de los obstáculos (§7.2);
   - el LLM no entiende los cambios de escena implícitos (§7.3.3);
   - los *prompts* largos tienen coste (§6, §8);
   - la usabilidad queda fuera de alcance (§1);
   - depende de GPT-4 (§1).

   **Observación propia:** el texto define el éxito como la corrección semántica del plan más la viabilidad de la tarea, pero no indica quién lo evaluó. Habría que saberlo antes de comparar tasas de éxito.
6. **Para el TFG.**
   - **Referencia:** un lenguaje de planes restringido a habilidades del sistema y con terminación garantizada, y la medida de éxito y latencia por tarea con repeticiones.
   - **Por qué no es comparable directamente:**
     - TypeFly controla un dron de interior de forma reactiva con visión, y el LLM interviene durante la ejecución;
     - nuestro agente produce una misión georreferenciada que se valida y se autoriza antes de ejecutarse, y no interviene durante el vuelo;
     - ellos usan hardware real y nosotros SITL;
     - las métricas difieren: latencia frente a exactitud por claves.

#### Flourish [E#7]

*Leído:* arXiv:1911.03098v4, texto completo (§I–VIII y referencias). La versión de IEEE RAM (2021) no se ha leído.

1. **Problema y contribución.**
   - **Problema:** combinar el reconocimiento aéreo de un UAV con la intervención localizada de un UGV para reducir los productos químicos sin perder rendimiento (§I).
   - **Contribución:** una visión general del proyecto, que incluye (§I, §IV–VI):
     - la cartografía conjunta (AgriColMap);
     - el posicionamiento del UGV (MCAPS);
     - la planificación informativa del UAV;
     - un módulo de tratamiento de malas hierbas.
2. **Arquitectura y papel de la IA:**
   - el UAV genera mapas multiespectrales y de presión de malas hierbas, y envía las áreas de mayor presión al UGV, que navega entre hileras y trata de forma selectiva (§IV–VI);
   - por Wi-Fi intercambian solo poses, áreas de interés, peticiones y estados. Usan peticiones y estados porque la comunicación tiene pérdidas, y las misiones se organizan con `ros_task_manager` (§V-C);
   - **IA:** bosques aleatorios y redes totalmente convolucionales ligeras para distinguir cultivo y maleza, adaptación semisupervisada y datos sintéticos (§III); un clasificador bayesiano confirma la detección antes de tratar (§VI-B); procesos gaussianos y CMA-ES en la planificación (§V-A). No usa LLM.
3. **Vehículos y entorno:**
   - un DJI Matrice 100 (NUC i7, TX2, cámara multiespectral) y un Bosch BoniRob (RTK-GPS, lidar, cámaras) con estampadores y boquillas (§II);
   - campo de remolacha azucarera y otros cultivos, en Italia; la planificación del UAV se evaluó también en simulación (§V-A).
4. **Experimentos:**
   - figuras de precisión de localización, del error del grafo de poses del UGV, de comparación de planificadores y de tasas de tratamiento (Figs. 7, 10, 13 y 17), sin cifras en el texto;
   - **Tabla I:** campaña de tres años en parcelas A–D. Con tratamientos posemergencia en el 30 % de la parcela, la producción de sacarosa fue un 3,9 % menor de media que con tratamiento completo, según el texto (§VI-C). Ese ensayo **simula** la intervención selectiva con un sistema químico: no lo hicieron los robots;
   - en la demostración pública de Ancona (mayo de 2018) se probó la canalización completa, sin resultados cuantitativos (§VI);
   - evaluación cualitativa con 17 partes interesadas (§VI-C).
5. **Declarada:** no hay sección de limitaciones. Sí indica que:
   - el GPS solo no basta para construir mapas que definan rutas (§IV-A);
   - los RTK-GPS comerciales no son robustos ante la pérdida de la señal de la base o el multitrayecto (§IV-B);
   - el tratamiento selectivo da una producción «comparable», no igual (§VI-C).

   **Observación propia:** el resultado agronómico (Tabla I) y la demostración integrada son evidencias distintas, y la segunda no tiene cifras en el texto. Las conclusiones (§VIII) no enumeran trabajo futuro.
6. **Para el TFG.**
   - **Referencia:** el reparto de papeles por capacidades (el UAV detecta, el UGV interviene) y la coordinación por mensajes mínimos de estado y petición, pensada para comunicaciones con pérdidas. Es afín a coordinar por resultado observado.
   - **Por qué no es comparable directamente:**
     - Flourish es un sistema de campo con percepción agrícola real;
     - nuestro escenario es SITL, con puntos declarados, sin percepción y con un LLM solo en la planificación.

#### ALFA [E#10]

*Leído:* arXiv:1907.06268v2, texto completo (§1–5 y referencias), y la página oficial del dataset.
- El texto se leyó en la versión HTML de ar5iv, que no muestra el número de versión. Se identifica como v2 porque es la última que lista arXiv (octubre de 2020).
- La versión publicada en IJRR (doi:10.1177/0278364920966642) no se ha leído.

1. **Problema y contribución.**
   - **Problema:** faltan datos reales para detectar y aislar fallos y anomalías en UAV, y la mayoría de métodos se prueban en simulación (§1).
   - **Contribución:** vuelos autónomos reales con fallos súbitos, con verdad de referencia, código de apoyo y métricas propuestas.
2. **Cadena de datos:**
   - un Carbon Z T-28 modificado (2 m de envergadura) con el autopiloto que §2.1 identifica como «Holybro PX4 2.4.6» y ArduPlane 3.9.0beta1, al que se añadieron cuatro parámetros para desactivar motor, timón de profundidad, timón de dirección o alerones;
   - los fallos se activan desde la estación de tierra, solo en modo autónomo, y un piloto de seguridad puede tomar el control (§2.1–2.2);
   - una Jetson TX2 con ROS y MAVROS graba los datos, con el firmware y MAVROS modificados para publicar valores ordenados y medidos;
   - la **Tabla 2** da la frecuencia de cada tema: posición global 4–5 Hz, desviación de trayectoria 50 Hz, estado 1 Hz;
   - formatos: CSV, `.mat` y `bag`, más los registros crudos (§3.1);
   - la verdad de referencia (`failure_status`) puede llegar hasta 0,2 s después del fallo.
3. **Entorno:** vuelos reales en un aeropuerto cerca de Pittsburgh (§3); no hay simulación.
4. **Contenido y métricas:**
   - **Tabla 1:** 47 casos (23 de pérdida total de motor, 14 de superficies de control en siete tipos y 10 sin fallo), con un total de 3935 s antes del fallo y 777 s con fallo;
   - **métricas propuestas** (§4): tiempo máximo y medio de detección, exactitud, precisión y exhaustividad, más una base de evaluación en C++ (§3.4);
   - no publica resultados de ningún método.
5. **Declarada** (§5):
   - «by no means a complete dataset»;
   - faltan fallos de sensores y errores graduales;
   - se excluyen los fallos que podrían causar la pérdida total del avión.

   **Notas de lectura pendientes de confirmar.** Son de la versión de arXiv leída y no se presentan como errores del trabajo ni de su versión publicada. No afectan al uso de ALFA en este capítulo:
   - en la Tabla 1, la suma de las filas (4040 s y 903 s) no coincide con los totales indicados (3935 s y 777 s);
   - el resumen habla de «24 escenarios» de otros siete tipos de fallo, y la Tabla 1 lista 14 casos con fallo y 10 sin fallo.

   Se contrastarán con la versión publicada y el historial de versiones del dataset en la revisión bibliográfica final.
6. **Para el TFG.**
   - **Referencia de documentación de un dataset de telemetría:** verdad de referencia con su retraso declarado, frecuencia por tema, varios formatos, código de carga y métricas propuestas.
   - **Por qué no es comparable como dataset:** ALFA son vuelos reales de ala fija con fallos inyectados, registrados a 1–50 Hz. Nuestro dataset es SITL de multirrotores sin fallos inyectados, con lecturas separadas por segundos **[PROYECTO]**, y su fin es la trazabilidad de la misión hasta la ejecución, no la detección de fallos.

**[PROYECTO]** Este TFG no entra en la tabla, porque no es estado del arte. Resumido con el mismo esquema:
- **Vehículos:** dos drones y un rover.
- **Papel de la IA:** un LLM propone misiones con herramientas restringidas.
- **Validación:** determinista, más la autorización explícita del operador.
- **Entorno:** ArduPilot SITL con Gazebo, sin hardware.

## 2.6 Encaje del TFG y preguntas de evaluación

**Encaje.** Nuestro diseño combina cuatro elementos, cada uno relacionado con trabajos de §2.1–2.4. No hemos comprobado si otros trabajos los combinan del mismo modo, y esta descripción no lo presupone:
- un agente LLM fuera del lazo de control, con herramientas restringidas (como PEACE o los de §2.1);
- validación determinista antes de cualquier efecto, y una autorización del operador que el protocolo no impone (§2.2);
- un escenario aéreo–terrestre con dependencias observadas, muy simplificado respecto a los sistemas agrícolas (§2.3);
- ejecución en SITL con evidencia sellada y un dataset de telemetría documentado (§2.4).

**No se afirma novedad ni superioridad:** no se ha hecho una revisión sistemática ni ninguna comparación experimental con esos trabajos, que usan otros vehículos, autopilotos, modelos y entornos.

**Preguntas de evaluación.** Se derivan de los objetivos propuestos (OA1–OA7 de [`00_propuesta_objetivos.md`](00_propuesta_objetivos.md)), pendientes de consolidar con Toni. No añaden alcance:

| Pregunta | Qué se mediría | Objetivo |
| --- | --- | --- |
| PE1. ¿Con qué exactitud transforma el agente una petición en una misión estructurada, y en qué falla? | Exactitud por claves con su denominador, uso de herramientas y errores críticos; transcripción separada de planificación | OA1 |
| PE2. ¿Qué propuestas bloquea la validación determinista, y por qué motivo? | Casos rechazados y sus motivos; ninguna ejecución sin autorización explícita | OA2 |
| PE3. ¿Ejecuta SITL la misión validada dentro de las tolerancias, y qué acredita esa medida? | Errores de llegada con su fuente de posición y su resolución | OA3 |
| PE4. ¿Se respetan en ejecución las dependencias aire–suelo? | Dependencias cumplidas por resultado observado | OA4 [PENDIENTE: depende de los hitos del rover] |
| PE5. ¿Qué permite reconstruir el dataset de una ejecución, y con qué límites? | Procedencia, relojes, clases de dato y valores ausentes | OA6 |

Comparar con los trabajos de la tabla sería **cualitativo**: qué mecanismos de validación y autorización usa cada uno. No sería una comparación de rendimiento.

## Fuentes de este capítulo

**Reutilizadas de 04:**

| Fuente | Estado en 04 | Estado tras esta tanda |
| --- | --- | --- |
| B#1 (ReAct) | METADATOS | RESUMEN |
| B#3 (encuesta de alucinación) | METADATOS | RESUMEN. La página de arXiv indica *ACM Computing Surveys* y el DOI 10.1145/3571730, que queda confirmado |
| B#4 (MCP) | VERIFICADA | VERIFICADA |
| B#7 (SITL) | VERIFICADA | VERIFICADA |
| B#11 (ardupilot_gazebo) | VERIFICADA | VERIFICADA |
| B#25 (Datasheets) | METADATOS | RESUMEN; arXiv indica la publicación en CACM, diciembre de 2021 |
| B#28 (sim-to-real) | METADATOS | RESUMEN |

**Nuevas:**

| # | Referencia | Enlace | Estado |
| --- | --- | --- | --- |
| E#1 | M. Ahn et al. *Do As I Can, Not As I Say: Grounding Language in Robotic Affordances*. arXiv:2204.01691 (2022) | https://arxiv.org/abs/2204.01691 | RESUMEN |
| E#2 | S. Vemprala, R. Bonatti, A. Bucker, A. Kapoor. *ChatGPT for Robotics: Design Principles and Model Abilities*. arXiv:2306.17582 (2023) | https://arxiv.org/abs/2306.17582 | RESUMEN; la sede de publicación no consta en arXiv |
| E#3 | G. Chen, X. Yu, N. Ling, L. Zhong. *TypeFly: Flying Drones with Large Language Model*. **Leída: arXiv:2312.14950v2** (26/09/2024; v1 de 08/12/2023) | https://arxiv.org/abs/2312.14950 (página oficial: https://typefly.github.io/) | COMPLETA (v2 de arXiv). La versión de IEEE TMC 24(9), pp. 9068–9079 (2025), solo por metadatos de la página oficial |
| E#4 | S. K. Lim, M. J. Y. Chong, J. H. Khor, T. Y. Ling. *Taking Flight with Dialogue: Enabling Natural Language Control for PX4-based Drone Agent*. arXiv:2506.07509 (2025) | https://arxiv.org/abs/2506.07509 | RESUMEN; sin sede |
| E#5 | E. Uysal, T. Kehrer, S. Panichella. *PEACE: A Planner-Executor Agent with Constraint Enforcement for UAVs*. arXiv:2606.00104 (2026); ICRA 2026 Workshop on Semantics for Reliable Robot Autonomy | https://arxiv.org/abs/2606.00104 | RESUMEN |
| E#6 | A. Robey, Z. Ravichandran, V. Kumar, H. Hassani, G. J. Pappas. *Jailbreaking LLM-Controlled Robots*. arXiv:2410.13691 (2024) | https://arxiv.org/abs/2410.13691 | RESUMEN; sin sede en arXiv |
| E#7 | A. Pretto et al. *Building an Aerial–Ground Robotics System for Precision Farming: An Adaptable Solution*. IEEE Robotics & Automation Magazine 28(3), pp. 29–49 (2021). doi:10.1109/MRA.2020.3012492. **Leída: arXiv:1911.03098v4** (07/06/2022) | https://arxiv.org/abs/1911.03098 | COMPLETA (v4 de arXiv); la versión de la revista no se ha leído |
| E#8 | P. Tokekar, J. Vander Hook, D. Mulla, V. Isler. *Sensor planning for a symbiotic UAV and UGV system for precision agriculture*. IEEE/RSJ IROS 2013, pp. 5321–5326. doi:10.1109/IROS.2013.6697126 | https://experts.umn.edu/en/publications/sensor-planning-for-a-symbiotic-uav-and-ugv-system-for-precision- | RESUMEN (portal de la Universidad de Minnesota). Existe una versión de revista (IEEE T-RO, 2016), solo vista en un listado: METADATOS, no se cita |
| E#9 | C. Lytridis et al. *An Overview of Cooperative Robotics in Agriculture*. Agronomy 11(9), 1818 (2021). doi:10.3390/agronomy11091818 | https://www.mdpi.com/2073-4395/11/9/1818 | RESUMEN; el cuerpo no se pudo leer |
| E#10 | A. Keipour, M. Mousaei, S. Scherer. *ALFA: A Dataset for UAV Fault and Anomaly Detection*. The International Journal of Robotics Research 40(2–3), pp. 515–520 (2021). **Leída: arXiv:1907.06268v2** (octubre de 2020; leída en ar5iv, que no muestra la versión) | https://arxiv.org/abs/1907.06268 (dataset: https://theairlab.org/alfa-dataset/) | COMPLETA (arXiv en ar5iv) y página del dataset. La versión publicada (doi:10.1177/0278364920966642) no se ha leído |

## Pendientes del capítulo

**Para la revisión bibliográfica final**, ninguno bloquea la lectura del borrador:
1. **Versiones publicadas.** E#3, E#7 y E#10 se leyeron en las versiones de arXiv indicadas en las referencias. Antes de citar las versiones publicadas (IEEE TMC 2025, IEEE RAM 2021 e IJRR), hay que contrastarlas.
2. **Notas de ALFA.** Las dos notas de §2.5.1 se confirmarán en ese contraste. No son una conclusión del capítulo.
3. **Fuentes leídas solo por resumen** (E#1, E#2, E#4–E#6, E#8, E#9, y B#1, B#3, B#25, B#28). Solo respaldan lo que dicen sus resúmenes. Antes de citar detalles, en particular las limitaciones declaradas, hay que leer el cuerpo.
4. **Bibliografía comentada.** Incorporar estas fuentes y estados a [`04_bibliografia_comentada.md`](04_bibliografia_comentada.md), que no se ha modificado.
5. **FAIR (B#26).** La página no se pudo abrir y no se usa en este capítulo.

**Marcados [PENDIENTE] en el texto,** sin búsqueda en esta tanda y sin añadir requisitos al proyecto:
- verificación formal de planes generados por LLM (§2.2);
- el cuerpo de la revisión de Lytridis et al. (§2.3);
- coordinación UAV–UGV con LLM y revisiones recientes (§2.3);
- datasets de telemetría de SITL comparables (§2.4);
- la pregunta de evaluación PE4, que depende de los hitos del rover (§2.6).
