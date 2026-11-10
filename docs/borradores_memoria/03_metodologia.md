# Metodología (BORRADOR)

> Las marcas son las mismas que en [`02_arquitectura.md`](02_arquitectura.md). Los objetivos citados pertenecen a una propuesta cuyo alcance está pendiente de consolidar con Toni.

## M.1 Desarrollo y verificación

- **Pruebas offline del código.** Usan dobles de prueba explícitos (`TEST_DOUBLE`) y fixtures. Una suite aprobada demuestra el comportamiento del código en esas condiciones, **no** una demostración operacional.
- **Operaciones reales autorizadas una a una.** Cada ejecución de Hermes, apertura de simulación, ejecución de misión o carga necesita una autorización explícita del operador, con un alcance concreto.
  - Esa autorización es distinta de la viabilidad (`mission_status`) y del estado APPROVED del software (`execution_status`). Ninguno de los dos la sustituye.
  - **Sin relanzamientos, en los procedimientos citados:** en las ejecuciones reales de Hermes con el ejecutor de capturas (`observability/hermes_capture_run.py`) se hizo una sola invocación sin relanzamiento automático (`hermes_invocations: 1`, `automatic_retry: false`). La secuencia H2 se autorizó «sin reintentos». Un fallo se conserva como resultado.
  - **Esto no cubre los intentos internos del proveedor** dentro de una petición al modelo (ver M.3).
- **Tres dominios de datos que nunca se mezclan:**
  - **sintético**, con dobles;
  - **simulación (SITL)**;
  - **hardware**, fuera del alcance propuesto.

  Toda tabla de resultados indica a qué dominio pertenece cada fila.

## M.2 Evidencia y reproducibilidad

- **Directorio por evidencia:** cada resultado se guarda en un directorio nuevo, con README y originales. El manifiesto sha256 se **genera al cerrar** el directorio.
  - **Integridad, no veracidad:** el manifiesto acredita que los bytes no cambiaron después. **No** acredita que la medición sea verdadera ni completa.
  - **Correcciones:** los resultados posteriores **no** reescriben los anteriores; una corrección es una revisión nueva y trazable.
- **Registros con límites:** el registro de operaciones del ejecutor tiene **retención limitada** (16 primeras y 96 últimas operaciones, con recuento de omitidas) y **puede tener pérdidas** (avisos de mensajes perdidos de la CLI de ROS, lecturas fallidas). Las capturas pasivas del subsistema rover también registran series incompletas. Lo ausente se informa; no se rellena.
- **Etiquetas de estado:** las evidencias se clasifican como REAL, SINTÉTICO, FALLIDO, SUPERADO o HISTÓRICO [FUENTE: `docs/INDEX.md`].
- **Historia frente a estado actual:** un resultado describe el momento de su sesión. Estados, PID, frescura o disponibilidad de otra fecha no acreditan el presente.
- **Comprobaciones reproducibles:** se repiten desde copias aisladas cuando es pertinente; por ejemplo, la entrega de estudiantes y el dataset reconstruido desde las copias.
- [PENDIENTE] **Versionado:** la mayor parte del código y de las evidencias no tiene seguimiento en Git. Hay que versionarlas antes de citar commits en la memoria.

## M.3 Evaluación de la planificación con LLM (OA1)

- **Separaciones en la medida:**
  - el uso de herramientas;
  - la respuesta o el fallo técnico;
  - el formato;
  - la exactitud estructurada, con su denominador y las claves que fallan;
  - los errores críticos (p. ej. afirmar que hay autorización de movimiento);
  - la revisión de la explicación.

  Esto se hace con `reporting/agri_experiment_comparison.py` [FUENTE: `docs/agri-demo-defense.md` §1].
- **Unidades distintas,** que no se convierten en tasas comunes cuando los protocolos difieren:
  - **ejecución de Hermes:** una invocación del proceso;
  - **llamadas normales al modelo:** las del ciclo de herramientas. [HISTÓRICO 28/10] En r2 fueron 3 principales más 1 auxiliar de título;
  - **intentos internos:** los que registra Hermes dentro de una llamada. [HISTÓRICO 24/10] En el piloto, `r02` tuvo 4 intentos fallidos y 1 completado. `retry_count` no siempre se informa, así que no se afirma un número de «reintentos» si el registro no lo dice.
- **Transcripción frente a planificación:** cuando el operador aporta todos los datos (H1), el resultado se describe como transcripción a una misión validada, no como planificación autónoma.
- [HISTÓRICO 24–28/10] H1 `BOUND`; H3 `NOT_VALIDATED` (22/23 claves comparadas); H3b con 23/23 factuales y la explicación sin revisar; piloto 1/2 y 5/8 tras la enmienda; ejecución en contenedor idéntica a H1.
- [PENDIENTE]
  - protocolo de evaluación fijado, con casos y número a decidir con Toni;
  - revisión humana de las explicaciones;
  - la comparación con trabajos previos [BIB].

## M.4 Ejecución en simulación (OA3, OA4)

- **Criterios de aceptación del ejecutor** (vía G):
  - eventos de despegue, waypoints, regreso y aterrizaje alcanzados;
  - dentro de 1,0 m en horizontal y 0,75 m en altura;
  - vehículo desarmado al final;
  - coherencia de identidad y de las pruebas de posición.

  Lo aplica el análisis del propio informe.
- **Vía M, aparte:**
  1. importación en QGC con comparación semántica;
  2. carga y lectura de vuelta comparadas ítem a ítem;
  3. ejecución en AUTO con sus propios criterios.

  La vía M no depende de la vía G ni la sustituye [FUENTE: `docs/sitl-plan-transfer-handoff.md`].
- **Coordinación:** las dependencias se cumplen por resultado observado (`COMPLETED`, `POI_REACHED`), nunca por tiempo de espera. Arrancar un servicio no autoriza movimiento.
- **Rover:** los hitos (identidad, pulso, navegación y R1) se informan por separado. Ninguno se presenta como el objetivo final.
- [HISTÓRICO 24/10] H2 PASSED en los dos drones.
- [PENDIENTE] vía M (pasos 2 y 3), navegación del rover, R1 real y ensayo integrado.

## M.5 Telemetría y dataset (OA6)

- **Fuentes:** solo entregas selladas, verificando su hash en el manifiesto antes de copiarlas. El proyecto principal se usa en solo lectura.
- **Esquema:**
  - identificadores de ejecución, run y vehículo;
  - misión y hash;
  - clases de dato separadas;
  - unidades y marcos declarados;
  - relojes separados (UTC del anfitrión, monotónico y `header.stamp` de ROS), sin correspondencia acreditada entre ellos en los registros actuales;
  - valores ausentes como `null` con su motivo.
- **Duraciones:** cada intervalo se descompone en tramos (cola, preparación, nodo `execute`, total del run, total de la secuencia) y dice qué marcas lo sustentan. Si no se puede separar, el valor es desconocido.
- **Indicador `flying`:** solo se da un rango condicionado, con sus hipótesis explícitas; nunca un valor.
- **Separación futura entre entrenamiento y evaluación:** por familia de misión (`split_group`), nunca por registro ni por vehículo.
- **Sin entrenamiento ni afirmaciones de predicción** en esta fase.
- **Batería:** la batería simulada de SITL puede estudiarse como salida del modelo de simulación. **No** acredita consumo físico sin una validación frente a datos reales.
- [PENDIENTE]
  - incorporar ejecuciones nuevas con el registro mejorado (fase 1, el subsistema rover);
  - el tamaño del dataset, a decidir con Toni;
  - la comparación con datasets públicos de UAV y UGV [BIB].

## M.6 Amenazas a la validez [PARCIAL]

- **Una sola sesión por resultado SITL:** no hay repeticiones, así que no hay variabilidad medida.
- **Simulación frente a realidad:** sin validación en hardware [BIB sobre la brecha entre simulación y realidad].
- **Dependencia del proveedor y del modelo del LLM:** se usó un único modelo gratuito.
- **Telemetría dispersa:** el intervalo de sondeo configurado es de 2 s, pero la separación efectiva observada entre lecturas en H2 fue de 4,6 s de mediana (máx. 13 s), porque cada lectura cuesta unos 3 s.
- **Datos de configuración incompletos:** las versiones de ArduPilot y de la imagen no se registran en todas las ejecuciones.
