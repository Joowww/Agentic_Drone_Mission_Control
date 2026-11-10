# Dashboard «TFG — Hermes» en Opik: consultas SQL de Ollie y revisión local (22/10/2026)

Registro del dashboard creado en Opik con la ayuda de Ollie, el asistente de Opik Cloud, sobre el
proyecto real `tfg-opik-hermes-real-20261021` (workspace `joowww`). **Claude no ha accedido al
workspace remoto ni ha cambiado ningún widget.** Todo lo remoto que figura aquí es **lo que Ollie
reportó y Joel transmitió**.

## 1. Lo reportado por Ollie (no verificado localmente)

**Primera respuesta** (`ollie_response_original.md`):

- las lecturas del dashboard `01a1627b-9178-7176-b704-b2cb878de52d` (`read`, `get_dashboard`,
  `get_dashboard_by_id`) devolvían 404, así que no podía confirmar el guardado ni editar títulos;
- aun así entregó las **siete consultas SQL** y la correspondencia con cada widget;
- informó de que todas usan el proyecto `01a16007-0a3b-765f-9b27-e06052060b1b` y el rango del
  dashboard;
- informó de que los cuatro indicadores del resumen son widgets nativos, no SQL.

**Actualización posterior** (transmitida por Joel; **sustituye a la anterior como estado actual
reportado**):

- leyó la vista mediante `insights_views` y **confirmó los siete widgets guardados**, en el proyecto
  correcto;
- **guardó títulos y secciones en catalán** y volvió a leerlos;
- **los cuatro indicadores iniciales ya tienen filtros**: `captured-metadata`, exclusión de
  `synthetic` y `provenance-unknown`, y `type=llm` en los tres de spans. Los comprobó con
  estadísticas y controles negativos;
- **sigue pendiente** verificar el `project_id` externo de las consultas guardadas;
- **W3 sigue distinguiendo mal** «sin datos» de «cero errores».

**Nota de transcripción:** `ollie_response_original.md` es el texto de la primera respuesta tal
como Joel lo pegó en la conversación. No se ha corregido ni reformateado nada. No se puede
garantizar que sea idéntico byte a byte a lo que mostró la interfaz de Ollie. Las SQL de
`sql_original/` se extrajeron **mecánicamente** de ese archivo.

## 2. Lo comprobado localmente (offline)

- `sql_original/W1.sql`…`W7.sql` son las siete consultas, sin alterar; los hashes y la
  correspondencia de títulos (antes → catalán) están en `sql_index.json`.
- **Revisión** en `sql_review.md`, contrastada con el payload real que envía el exportador:
  - las 7 filtran la procedencia en todas sus subconsultas;
  - **ninguna lleva `project_id`**;
  - ninguna cuenta dos veces los derivados;
  - W4 y W5 conservan los estados (`zero_unconfirmed` y `absent` no se tratan como 0).
- **Defectos y límites encontrados:**
  - W3: no tiene tamaño de muestra, no distingue «sin datos», y su serie de trazas es
    estructuralmente 0;
  - W2: no exige un intervalo válido. Que incluya spans con error es válido si se declara la
    población, y su `quantile` aproximado es una característica, no un defecto;
  - W4 y W5: `LIMIT` puede recortar sin aviso por encima de 100 y 40 spans; W4 quita los más
    recientes;
  - W4: el estado `redacted` no se trata como sin barra;
  - W6: no detecta contaminación por diseño.
- **Correcciones propuestas** en `proposed_corrections_NOT_DEPLOYED.sql`: **no desplegadas, no
  ejecutadas y no validadas contra ClickHouse**. Los widgets en Opik siguen siendo los originales.
- **Dependencia sin verificar:** el exportador no envía `source`. Los filtros
  `source IN ('sdk','unknown')` dependen del valor que asigne el servidor.

## 3. Pendiente

- Verificar el `project_id` externo de las consultas guardadas frente al proyecto real.
- Decidir si se aplican las correcciones propuestas. Si se aplican, compararlas con las originales
  en el mismo rango y tener la confirmación visual de Joel.
- **Confirmación visual de Joel** de los siete widgets, y de los cuatro indicadores con sus
  filtros, frente a la captura del 21/10 (1 traza, 1 span, tokens 538 / 2 / 256 /
  0 sin confirmar / 0 sin confirmar).

## 4. Versión 2 propuesta por Ollie — NO desplegada (posterior)

En [v2_proposed_by_ollie_NOT_DEPLOYED/](v2_proposed_by_ollie_NOT_DEPLOYED/README.md):

- SQL revisadas de W2–W5 **con el `project_id` escrito en la consulta**;
- los resultados de lectura que reporta Ollie, entre ellos un control con un `project_id` falso que
  devuelve 0 filas;
- una revisión local.

**Ollie recibió 403 al guardar.** Los widgets siguen con las consultas originales de `sql_original/`.

*Histórico:* Ollie informó entonces de que la vista tenía **16 widgets en vez de 11**: cinco
duplicados de validación se añadieron el 22/10 a las 08:09:26 UTC, entre ellos «Prova negativa —
project_id fals», con consultas guardadas ilegibles (404).

## 5. Actualización posterior reportada por Ollie: vista con 11 widgets

`ollie_update_view_11_widgets_transcription.md` es una transcripción trasladada por Joel, no una
exportación de la API ni una comprobación de Claude. Según Ollie:

- Antes de modificar nada guardó una copia completa de la configuración (`lastModified`
  1792656566505) y comprobó que la vista no había cambiado desde esa copia.
- Retiró los **cinco widgets de validación**: identificadores, con sus consultas `01a162a8-…`, en la
  transcripción. El cambio quedó guardado el 22/10/2026 a las 08:14:53 UTC.
- Tras releer la vista, **quedan 11 widgets sin duplicados**:
  - en «1. Resum», los cuatro indicadores: el de trazas, con los tres filtros de etiquetas; los
    tres de spans, además con `type = llm`;
  - los siete SQL originales, con sus consultas `01a16289-…`;
  - títulos, filtros, consultas y posiciones idénticos a la copia previa.
- Las cinco consultas guardadas `01a162a8-…` siguen existiendo, pero ningún widget las usa.
- No tocó permisos, consultas, trazas ni spans. **Las correcciones de W2–W5 siguen sin desplegar.**

Nada de esto acredita el alcance efectivo (`project_id`) de las consultas originales, que sigue
pendiente de verificar.

## Archivos

Archivos de la versión desplegada (v1): `ollie_response_original.md`, `sql_original/` y
`sql_index.json`. Actualización posterior de la vista: `ollie_update_view_11_widgets_transcription.md`. Revisión de Claude: `sql_review.md` y `proposed_corrections_NOT_DEPLOYED.sql`.
Propuesta de Ollie: `v2_proposed_by_ollie_NOT_DEPLOYED/`. `SHA256SUMS` cubre todo salvo los README y
él mismo; las entradas de la v1 no cambiaron al añadir la v2.
