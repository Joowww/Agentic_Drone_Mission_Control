# Dashboard de Opik para Hermes y hoja de ruta de visualización

Fecha: 22/10/2026. El sistema multiagente no ha creado ni modificado ningún dashboard remoto, no ha usado
credenciales y no ha instalado nada. El dashboard «TFG — Hermes» **existe en Opik**: lo crearon
Joel y Ollie. Su estado se describe en [Estado actual](#estado-actual-del-dashboard-22102026),
separando lo reportado por Ollie de lo comprobado localmente. Guía operativa de captura y
exportación: [hermes-capture-runbook.md](hermes-capture-runbook.md).

## Punto de partida (hechos)

- **Datos reales en Opik:** una traza y un span `llm` de una captura real en el proyecto
  `tfg-opik-hermes-real-20261021` (workspace `joowww`), confirmados visualmente por Joel. Los datos
  sintéticos están en **otros proyectos** (`tfg-opik-synthetic-20261021`).
- **Formato del exportador:**
  - cada span `llm` lleva el intervalo medido por Hermes (`start_time` y `end_time`);
  - las etiquetas incluyen `captured-metadata`, `synthetic` o `provenance-unknown` según la
    procedencia;
  - `metadata.tfg_data_kind` y `metadata.tfg_provenance_basis` registran el origen;
  - `metadata.tfg_model`, `tfg_provider` y `tfg_usage_source` son cadenas;
  - los tokens van en `metadata.tfg_usage`, un objeto anidado `{valor, estado}`;
  - un `llm_error` lleva `error_info`.
- **Lo que el exportador no rellena a propósito:** `usage`, `model`, `provider` y
  `total_estimated_cost` de primer nivel. No se cambia esa representación para rellenar gráficas.

## Qué permite Opik (documentación y especificación oficiales)

Según [Dashboards](https://www.comet.com/docs/opik/production/dashboards) y su
[changelog](https://www.comet.com/docs/opik/changelog/2025/12/18):

- **Tipos de dashboard:**
  - **de proyecto:** la vista *Project overview* integrada, de sólo lectura, y vistas propias;
  - **de workspace**, de tipo *Multi-project* o *Experiments*.
- **Widgets:** *Time series*, *Single metric* y *Markdown*. Los dashboards *Experiments* tienen
  además *Metrics* y *Leaderboard*.
- **Time series:**
  - métricas: Number of traces/spans, Trace/Span duration con P50/P90/P99, Token usage,
    Span token usage y Estimated cost;
  - filtros «por ejemplo por tag, metadata o feedback score»;
  - agrupación por Tags, **Metadata (con una clave)**, Name, Has error o Error type, y en spans
    además Model, Provider y Span type;
  - agregación por intervalos de tiempo o Total.
- **Single metric:** Total trace/span count, duración P50/P90/P99, Total error count y medias de
  tokens de entrada, salida y total.
- **Rango de fechas:** 24 h, 3, 7, 30 o 60 días, o personalizado.
- **No documentado para los widgets nativos:** que se puedan **agregar valores numéricos de
  metadata**, y cualquier forma de importar o exportar la configuración de un dashboard.
- **Gráficos personalizados de Ollie:** según la documentación, un *Ollie chart* se añade «from a
  custom chart that Ollie builds» y requiere Opik Cloud con Ollie y los gráficos personalizados
  activados. La especificación `6ff71e2` incluye además un endpoint interno
  `/v1/internal/dashboard-saved-queries` con un campo `sql`.
  - Ollie ha generado siete widgets personalizados con SQL, entre ellos los que consultan
    `metadata.tfg_usage.<campo>.value` y `.status`. Ya están **incorporados al repo y revisados
    localmente**; ver [Estado actual](#estado-actual-del-dashboard-22102026).
- **API (especificación `6ff71e2`):** existe `POST /v1/private/dashboards`, pero su `config` es un
  `JsonNode` libre **sin esquema de widgets publicado**. Por eso **no se entrega un JSON
  reproducible**: inventarlo sería suponer un contrato. Se entregan instrucciones exactas de
  interfaz.
- **Coste** ([Cost tracking](https://www.comet.com/docs/opik/tracing/cost_tracking)): se estima a
  partir de `provider`, `model` y `usage` en spans `llm`. La página usa `total_estimated_cost=0`
  para localizar spans «que no tienen coste estimado», así que **un widget de coste mostraría 0 para
  nuestros spans**.

## Estado actual del dashboard (22/10/2026)

Evidencia: [opik_dashboard_tfg_hermes_2026_10_22](../evaluation/observability/opik_dashboard_tfg_hermes_2026_10_22/README.md),
con la respuesta original de Ollie, las siete SQL sin alterar, la revisión y las correcciones
propuestas.

### 1. Configuración guardada, según la lectura reportada por Ollie (no verificada de forma independiente)

- **Estado actual: 11 widgets**, sin duplicados. Según la última actualización de Ollie (transcripción
  trasladada por Joel, no comprobada por el sistema multiagente), releyó la vista tras retirar los cinco widgets de
  validación; el cambio quedó guardado el 22/10/2026 a las 08:14:53 UTC. Los 11 restantes son
  idénticos a la copia previa (`lastModified` 1792656566505): títulos, filtros, consultas y
  posiciones.
- **Dashboard** `01a1627b-9178-7176-b704-b2cb878de52d`, vista del proyecto real. Ollie la leyó
  mediante `insights_views` y confirmó los **siete widgets SQL guardados** en el proyecto correcto,
  con sus consultas originales `01a16289-…`.
  Es la lectura posterior: la primera respuesta registraba lecturas con 404.
- **Títulos y secciones en catalán**, guardados y releídos por Ollie: «1. Resum», «2. Evolució»,
  «3. Tokens» y «4. Procedència i cobertura».
- **Cuatro indicadores nativos del resumen** (Execucions registrades, Crides LLM registrades,
  Latència LLM — mediana (P50) y Errors LLM): **tienen ya filtros** `captured-metadata`, exclusión
  de `synthetic` y `provenance-unknown`, y `type=llm` en los tres de spans. Ollie los comprobó con
  estadísticas y controles negativos. Son widgets nativos, no SQL, y su configuración no está en
  el repo.
- **Proyecto de las consultas:** Ollie informa de `01a16007-0a3b-765f-9b27-e06052060b1b`. **No está
  verificado** que ese `project_id` externo sea el aplicado a las consultas guardadas.

### 2. SQL revisado localmente (el sistema multiagente, offline, sin ejecutar y sin ClickHouse)

| Widget (título en catalán) | Qué hace | Resultado de la revisión |
| --- | --- | --- |
| W1 Volum diari — traces i crides LLM | Trazas y spans `llm` por día | Correcto |
| W2 Latència LLM — P50/P90/P99 | Cuantiles de spans `llm` por día, con `n` | **Mejorable:** no exige `end_time >= start_time`. Incluir los spans con error es válido si se declara esa población, y el `quantile` aproximado es una característica del cálculo, no un defecto |
| W3 Errors per data i tipus | Errores de trazas y spans por tipo | **Defecto:** sin tamaño de muestra, no distingue «sin datos» de «cero errores», y la serie de trazas es siempre 0 porque el exportador no pone `error_info` en trazas |
| W4 Tokens d’entrada, sortida i memòria cau per execució | Gráfico de 4 contadores con su estado | Conserva estados (`zero_unconfirmed`/`absent` → sin barra). **Límite:** `LIMIT 400` recorta por encima de 100 spans quitando los **recientes** sin aviso, y `redacted` no queda sin barra |
| W5 Detall dels tokens — valor i estat | Tabla de 5 contadores con `value` y `status` | Correcto. **Límite:** `LIMIT 200` recorta por encima de 40 spans sin aviso |
| W6 Procedència de les dades | Recuento por `tfg_data_kind` | Correcto, pero por diseño no detecta contaminación (filtra `captured-metadata`) |
| W7 Cobertura dels comptadors d’ús | Cobertura de `tfg_usage_source` | Correcto |

**Comunes a las siete:**

- todas filtran la procedencia en cada subconsulta;
- **ninguna lleva `project_id`**: depende del alcance externo del widget, sin verificar;
- ninguna usa los derivados `prompt_tokens`/`total_tokens`, así que no hay doble conteo;
- **dependencia:** el exportador no envía `source`, y el filtro `source IN ('sdk','unknown')`
  depende del valor que asigne el servidor.

**Correcciones propuestas, NO desplegadas:** P-W2, P-W3, P-W4, P-W5 y un control nuevo sin filtro de
etiquetas (P-C1) en `proposed_corrections_NOT_DEPLOYED.sql`. **No se han ejecutado ni validado
contra ClickHouse.** Los widgets en Opik siguen siendo los originales.

### 2b. Versión 2 de W2–W5 propuesta por Ollie — NO desplegada

Evidencia: [v2_proposed_by_ollie_NOT_DEPLOYED](../evaluation/observability/opik_dashboard_tfg_hermes_2026_10_22/v2_proposed_by_ollie_NOT_DEPLOYED/README.md).

- **Estado:** Ollie no pudo guardarla porque `create_dashboard_saved_query` devolvió **403**
  (nginx). **Los widgets W2–W5 siguen con sus consultas originales.**
- **SQL propuesta**, revisada localmente de forma estática:
  - lleva `project_id = '01a16007-0a3b-765f-9b27-e06052060b1b'` **escrito en cada consulta**;
  - W2 exige intervalos válidos;
  - W3 sólo usa spans `llm`, distingue «sense dades» de «sense errors (n>0)» y da `n` por día;
  - W4 y W5 indican el recorte con `retall` (20 y 40 ejecuciones más recientes);
  - W4 sólo pone barra a `nonzero_normalized`.
  - W2 incluye los spans con error, lo cual es válido porque declara la población en `poblacio`, y
    usa `quantile` aproximado, que es una característica y no un defecto.
- **Resultados de lectura reportados por Ollie** (no verificados de forma independiente): coinciden con la captura
  del 21/10 (2,665 s; 538 / 2 / 256; ceros `zero_unconfirmed`), y el **control con un `project_id`
  falso devuelve 0 filas**.
- **Qué no acredita:** el `project_id` explícito y el control negativo sólo se refieren a **estas
  consultas v2**. **No acreditan el alcance de las W1–W7 desplegadas**, que no llevan `project_id`.
  Tampoco está verificado localmente que ese UUID corresponda a `tfg-opik-hermes-real-20261021`.
- *Histórico, ya resuelto:* la vista llegó a tener **16 widgets** al añadirse cinco de validación
  el 22/10 a las 08:09:26 UTC, entre ellos «Prova negativa — project_id fals». Ollie los retiró y,
  según su relectura, la vista vuelve a tener **11**. Sus cinco consultas guardadas `01a162a8-…`
  siguen existiendo, pero ningún widget las usa, y nunca se consideraron la v2 desplegada.
- Desplegar la v2 sigue siendo decisión de Joel: habría que pegar cada SQL en el editor del widget
  original, recargando antes la vista.

### 3. Alcance efectivo y comprobación visual (pendientes)

- Verificar el `project_id` externo de las consultas guardadas.
- Decidir si se despliega la v2 de Ollie (que recoge en gran parte P-W2 a P-W5) o las propuestas de
  el sistema multiagente. Si se despliega, compararla con las originales en el mismo rango.
- **Confirmación visual de Joel** de los once widgets (cuatro indicadores y siete SQL) frente a la
  captura del 21/10: 1 traza, 1 span `llm`, tokens 538 / 2 / 256 / 0 `zero_unconfirmed` /
  0 `zero_unconfirmed`.
- Con los datos actuales ningún `LIMIT` recorta. El riesgo aparece al acumular capturas.

## Dashboard «TFG — Hermes»: diseño de referencia (propuesto antes de su creación)

El dashboard real difiere de este diseño: tiene cuatro indicadores nativos y siete widgets SQL de
Ollie, y su estado está en la sección anterior. El diseño se conserva como **criterio de
revisión**, sobre todo por el control de contaminación 6c, que no está entre los siete widgets.

**Ámbito:** un único dashboard, **vista propia del proyecto** `tfg-opik-hermes-real-20261021` del
workspace `joowww`. Según la documentación, los widgets de un dashboard de proyecto «siempre leen el
proyecto actual», así que los proyectos sintéticos (`tfg-opik-synthetic-20261021`) quedan fuera por
construcción. Además, cada widget filtra por la etiqueta `captured-metadata`.

**Datos que contiene hoy el proyecto:** la captura real del 21/10/2026, con **1 traza y 1 span
`llm`** (traza `01a16002-9b28-75bc-abca-6942ca6d1c95`, span `01a16002-9b28-7291-bce7-d68337bb58f2`).
Las capturas que no se envíen a Opik, como la de la utilidad del 22/10 mientras no se autorice su
envío, **no aparecen** en el dashboard.

**Pasos de referencia (anteriores a la creación real):** en `joowww` abrir el proyecto
`tfg-opik-hermes-real-20261021`, ir a sus dashboards o vistas, crear una vista nueva llamada
**`TFG — Hermes`** y fijar el rango de fechas en *Past 60 days* o en uno personalizado que empiece
el 21/10/2026. Después añadir los widgets en este orden. Los nombres de métricas y opciones son los
de la documentación oficial; si la interfaz usa una etiqueta ligeramente distinta, se elige la
equivalente y **no se sustituye por otra métrica**.

Filtro común **F** de todos los widgets, salvo el 6c: `Tags` contiene `captured-metadata`.

| # | Nombre del widget | Tipo | Fuente | Métrica / opciones | Filtros | Agrupación |
| --- | --- | --- | --- | --- | --- | --- |
| 1a | `Muestra — trazas` | Single metric | Traces | Total trace count | F | — |
| 1b | `Muestra — spans` | Single metric | Spans | Total span count | F | — |
| 2a | `Volumen — trazas por día` | Time series (barras) | Traces | Number of traces; agregación por intervalo de tiempo (diaria) | F | — |
| 2b | `Volumen — spans por día` | Time series (barras) | Spans | Number of spans; agregación diaria | F | — |
| 3a | `Latencia span llm (P50/P90/P99)` | Time series (línea) | Spans | Span duration; submétricas P50, P90, P99 | F + `Type = llm` | — |
| 3b | `Latencia span llm — P50` | Single metric | Spans | P50 duration | F + `Type = llm` | — |
| 4a | `Errores — spans con error` | Single metric | Spans | Total error count | F | — |
| 4b | `Errores — por estado` | Time series (barras), agregación **Total** | Spans | Number of spans | F | Has error |
| 4c | `Errores — por tipo` | Time series (barras), agregación **Total** | Spans | Number of spans | F | Error type |
| 5 | `Tokens — tabla manual (no serie)` | Markdown | — | Texto de abajo. Alternativa a confirmar: los widgets SQL de Ollie (ver «Tokens con consultas SQL de Ollie») | — | — |
| 6a | `Procedencia — tipo de dato` | Time series (barras), agregación **Total** | Spans | Number of spans | F | Metadata, clave `tfg_data_kind` |
| 6b | `Cobertura — fuente de uso` | Time series (barras), agregación **Total** | Spans | Number of spans | F | Metadata, clave `tfg_usage_source` |
| 6c | `Control — etiquetas sin filtro` | Time series (barras), agregación **Total** | Traces | Number of traces | **ninguno** (a propósito) | Tags |
| 7 | `Alcance y límites` | Markdown | — | Texto de abajo | — | — |

**Cómo se lee:**

- **1a/1b:** tamaño de muestra, siempre a la vista. Hoy da 1 y 1.
- **3a/3b:** intervalo de la llamada medido por Hermes, desde el primer intento e incluyendo
  reintentos internos. **Con n=1, P50 = P90 = P99 = 2,66 s: no es una distribución ni una
  conclusión de rendimiento.**
- **4a/4b/4c:** errores siempre junto al total de spans (1b). Hoy no hay ningún `llm_error`.
- **6a:** debe mostrar sólo `captured_hermes_metadata`.
- **6b:** distingue los spans con contadores normalizados por Hermes (`hermes_normalized_summary`)
  de los que no tienen uso (`absent`).
- **6c:** es el único widget **sin filtro**. Sirve para detectar contaminación: si alguna vez
  aparece `synthetic` o `provenance-unknown` en este proyecto, hay que investigarlo y no se
  incluye en las comparaciones.

**No añadir los widgets nativos:** *Token usage*, *Span token usage*, medias de tokens,
*Estimated cost* ni *Span estimated cost*. Leen `usage` y coste nativos, que el exportador no
rellena a propósito. Con nuestros datos saldrían vacíos o a **0**, y un coste desconocido no se
muestra como 0. Tampoco se agrupa por *Model* o *Provider* nativos, que están vacíos; si hace falta,
se usa la metadata `tfg_model`.

**Tokens con consultas SQL de Ollie:** los tokens **se representan automáticamente** con W4 y W5,
que leen `metadata.tfg_usage.<campo>.value` y `.status` sin cambiar la representación del
exportador. Ya están incorporados y revisados localmente; ver
[Estado actual](#estado-actual-del-dashboard-22102026).

- **La revisión confirma:**
  - conservan los estados;
  - no tratan `zero_unconfirmed` ni `absent` como 0;
  - no suman derivados;
  - informan `n_spans`.
- **Señala:**
  - los recortes por `LIMIT` sin aviso;
  - que no se muestran los derivados `prompt_tokens`/`total_tokens` (ni bien ni mal: simplemente
    no aparecen).
- **No representan** el título auxiliar, que el plugin no captura, ni ningún coste.
- **La comprobación visual sigue pendiente**; hasta entonces, la tabla manual del widget 5 sirve de
  contraste.

**Texto del widget 5 (tabla manual de una captura, no se actualiza sola):**

```markdown
**Tokens del turno principal — tabla manual, NO es una serie automática**
Captura real del 21/10/2026 (proyecto tfg-opik-hermes-real-20261021), n = 1 span `llm`.
Modelo poolside/laguna-s-2.1:free vía nous. Fuente: metadata.tfg_usage (contadores normalizados por Hermes).

| Contador | Valor | Estado |
| --- | --- | --- |
| input_tokens | 538 | nonzero_normalized |
| output_tokens | 2 | nonzero_normalized |
| cache_read_tokens | 256 | nonzero_normalized |
| cache_write_tokens | 0 | zero_unconfirmed (no prueba que el proveedor enviara 0) |
| reasoning_tokens | 0 | zero_unconfirmed |
| prompt_tokens | 794 | derived_nonzero (input + caché) |
| total_tokens | 796 | derived_nonzero (prompt + output) |

Alcance: sólo el turno principal. El título auxiliar (informe nativo: 38 / 14 / caché 224) no
está en Opik. Coste facturado: desconocido. Actualizar a mano sólo con capturas enviadas a este proyecto.
```

**Texto del widget 7:**

```markdown
**Alcance**: capturas reales de Hermes (plugin tfg-observability-capture 0.3.0) con procedencia
verificada; sólo el turno principal. **No incluye**: la generación auxiliar del título, el coste
(desconocido, no calculado), ni datos sintéticos o de origen desconocido. Tokens: contadores
normalizados por Hermes, no los brutos del proveedor. Con n pequeña, ningún panel es representativo
del rendimiento. Evidencia: evaluation/observability/opik_hermes_real_send_2026_10_21/.
```

**Al actualizar con nuevas capturas enviadas:** volver a generar la tabla con
`hermes_capture_run review`, a partir de `capture_summary.json`, y sustituir el texto del widget 5
indicando la fecha y la n. Los widgets 1–4 y 6 se actualizan solos. Los widgets SQL de Ollie también
se actualizarían solos una vez incorporados y confirmados; hasta entonces, la tabla manual sirve de
contraste.

**Reproducibilidad:** las siete SQL están archivadas en la evidencia del 22/10. El `config` completo
del dashboard no lo está: su esquema no está publicado, y archivarlo exigiría un
`GET /v1/private/dashboards/{id}` con credenciales, que esta tarea no autoriza. Tampoco están en el
repo los filtros de los cuatro indicadores nativos.

## Hoja de ruta por etapas

### A. Opik: observabilidad de Hermes y evaluación de ejecuciones (en curso)

- **Hecho:**
  - plugin de captura;
  - exportador con procedencia;
  - utilidad reproducible (`capture`, `review`, `opik-dry-run`);
  - envío real confirmado en la interfaz.
- **Siguiente:**
  - dashboard «TFG — Hermes»: **creado**, con siete widgets SQL y cuatro indicadores filtrados según
    Ollie. Las SQL están archivadas y revisadas localmente. **Pendiente:** verificar el `project_id`
    externo, decidir las correcciones P-W2 a P-W5 y P-C1 (no desplegadas) y la confirmación visual
    de Joel;
  - varias capturas reales con un protocolo (número de turnos, prompts fijos sin contenido
    sensible, mismo modelo) antes de comparar latencias o tokens;
  - **evaluación de ejecuciones** con *datasets/experiments* de Opik (dashboards *Experiments*),
    con métricas definidas sobre resultados de misión.
- **Dependencias abiertas:**
  - decidir si se capturan las llamadas auxiliares (`pre/post_auxiliary_call`);
  - turnos con herramientas MCP de sólo lectura;
  - tarifa declarada o `usage` nativo si algún día se quiere coste. Es una decisión explícita y no
    un efecto de la gráfica.

### B. Grafana OSS local: recursos y simulación (cuando existan colectores acreditados)

- **Datos que existen hoy:**
  - mediciones puntuales y manuales de CPU, RAM y RTF aproximado en
    [rover-performance-test-protocol.md](rover-performance-test-protocol.md), por ejemplo CPU
    448 %, RAM 3,05 GiB y RTF ~0,03–0,04, **sin colector ni serie temporal**;
  - estado y readiness de la simulación (`tools/simulation_status.py` y las herramientas MCP
    `check_simulation_ready`);
  - el paquete `telemetry/` está vacío.
- **Falta:**
  - colectores de CPU, RAM y GPU (la GPU es una RTX 3070 de 8 GiB vista por WSL), Docker y RTF
    con el método acreditado del protocolo (estadísticas de Gazebo y contadores sim/real);
  - telemetría de vehículos;
  - un almacén de series temporales;
  - una decisión de retención.
- **Coste:** es software gratuito, pero consume CPU y RAM en el mismo portátil que ya va justo con
  Gazebo, y requiere mantenimiento. **No se instala ahora.**

### C. Web propia como interfaz de misión (objetivo aceptado, no implementado)

- **Datos y APIs que existen** (hoy sólo por MCP stdio para Hermes; `tools/hermes_mcp_server.py`):
  - misión: `get_mission_state`, `validate_mission`, `validate_and_export_qgc`;
  - preflight virtual: `start_virtual_preflight`, `get_virtual_preflight`, `run_virtual_preflight`;
  - simulación: `check_simulation_ready`, `start_simulation`, `stop_simulation`, `restart_simulation`;
  - ejecución: `check_mission_execution_ready`, `execute_approved_mission`;
  - reconciliación: `inspect_execution_reconciliation`, `get_execution_reconciliation`,
    `apply_execution_reconciliation`;
  - además, misiones en `missions/`, informes en `reporting/` y evidencias en `evaluation/` y
    `simulation/ros2_gazebo/results/`.
- **Falta:**
  - una API HTTP de sólo lectura sobre esos servicios;
  - un flujo de posición y estado en vivo para el mapa (drones; el rover sigue en modo pasivo y
    bloqueado);
  - eventos de progreso de misión;
  - un modelo de usuarios y permisos para quien consulta;
  - un índice de evidencias.
- **Regla:** cualquier control futuro pasa por las autorizaciones, reservas y lifecycle del
  proyecto. **Una pantalla nunca concede autoridad operativa.** La primera versión sería de sólo
  lectura.
- No se genera frontend, mockups ni dependencias en esta etapa.
