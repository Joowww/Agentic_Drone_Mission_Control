# Resumen local de capturas de Hermes para comparar modelos

Fecha: 21/10/2026. **Herramienta offline preparada; todavía no hay capturas reales que resumir.**
Los únicos números que ha producido proceden de fixtures sintéticos de los tests y **no son
resultados de rendimiento**.

Código: [observability/capture_summary.py](../observability/capture_summary.py) ·
tests: [test_capture_summary.py](../tests/test_capture_summary.py). Reutiliza la validación y la
procedencia del [exportador LangSmith](langsmith-export.md) sin modificarlo.

```bash
.venv/bin/python -m observability.capture_summary CAPTURE.jsonl [...] \
    [--provenance captured|synthetic] [--include-noncomparative]
```

## Reglas

- **Agrupación** por experimento (`run_id`), `case_id` y modelo (`provider/model`). Sólo se usan
  metadatos de la captura: no hace falta ni se lee ningún prompt o respuesta.
- **Procedencia:**
  - la sección `comparative` sólo incluye trazas `captured_hermes_metadata`, es decir, declaradas
    con `--provenance captured` y con registros del sink que verifican;
  - los datos sintéticos y los de procedencia desconocida se cuentan en `excluded_from_comparison`;
  - con `--include-noncomparative` aparecen en una sección aparte marcada
    `NOT PERFORMANCE RESULTS`;
  - los nombres de `run_id`/`case_id` nunca convierten una captura en real.
- **Tokens:** para cada contador normalizado (`input`, `output`, `cache_read`, `cache_write`,
  `reasoning`), el resumen da:
  - el número de cada estado (`nonzero_normalized`, `zero_unconfirmed`, `absent`, `redacted` y
    `usage_absent` cuando la llamada no trae uso);
  - estadísticas de los valores distintos de cero;
  - aparte, una cota que incluye los ceros recibidos sin confirmar.

  Una ausencia nunca se convierte en 0. `prompt_tokens` y `total_tokens` son sumas que calcula
  Hermes: se informan aparte y no se suman a los contadores. La semántica es la de un resumen
  normalizado por Hermes, no el uso bruto del proveedor.
- **Latencia:** sólo intervalos medidos por Hermes, con los dos epochs, `fin ≥ inicio` y
  coherentes con `api_duration_s` (±1 ms). Las exclusiones se cuentan por motivo. El ámbito incluye
  los reintentos. `first_chunk_offset_s` se resume aparte, con su salvedad: sólo es TTFT si no hubo
  reintentos.
- **Fallos y muestras:** por grupo se informa del número de llamadas, errores, llamadas con y sin
  uso, y llamadas con y sin latencia medida. Los errores se desglosan por tipo y `status_code`, y
  se cuentan las llamadas que comparten `api_request_ref` con un error.
- **Herramientas:** recuento por estado y procedencia de la duración. Sólo `hermes_reported_ms`
  cuenta como duración medida; los 0 y los timeouts configurados no.
- **Coste:** no se calcula (`cost.computed=false`, «no declared tariffs»).

## Pruebas

9 tests con fixtures sintéticos. Cubren:
- **procedencia:** puerta de procedencia, exclusión por defecto y sección no comparativa, registros
  que no verifican y marca sintética;
- **agrupación:** grupos, tamaños de muestra y fallos;
- **tokens:** ausente frente a cero, y derivados separados;
- **tiempos:** latencia con exclusiones y duraciones de herramientas;
- **salida:** sin contenido en el informe y CLI con errores.

Se comprobaron 6 mutaciones: ausencia como cero, derivados sumados, latencia incoherente incluida,
desconocidos o sintéticos en la comparación y timeout como medida. Todas se detectan.

## Pendiente

Faltan capturas reales con procedencia verificada (plugin 0.3.0) de al menos dos modelos y
varias repeticiones por caso. Mientras tanto no hay ninguna comparación de modelos.
