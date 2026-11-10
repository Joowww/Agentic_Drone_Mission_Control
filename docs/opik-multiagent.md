# Opik Cloud y el benchmark multiagente

**Destino fijo:**
- workspace `joowww`;
- proyecto `tfg-multiagent-benchmarks`;
- endpoint `https://www.comet.com/opik/api`.

El código rechaza cualquier otro workspace o proyecto y no toca los demás proyectos de Joel.

**Estado a 04/11/2026:**
- **Sin enviar:** nada.
- **Dry run:** verificable, en `multiagent/benchmark/opik_imports/joowww__tfg-multiagent-benchmarks/`.
- **Credenciales:** no configuradas en esta máquina (no hay `OPIK_API_KEY` ni `~/.opik.config`).
- **SDK de Opik:** no está instalado y no hace falta.

## 1. Qué se reutiliza y qué se añade

`observability.opik_export` sigue siendo el único cliente. Aporta:
- el destino;
- los ids deterministas UUIDv7;
- la puerta de exportación;
- los cuerpos `traces/batch` y `spans/batch`, compatibles con la OpenAPI de Opik y validados offline contra los modelos REST de `opik==2.2.110`;
- `send()`, que hace un único intento, sin reintentos automáticos y con un registro JSONL duradero por lote.

Joel ya lo usó con `joowww` el 24/10, con respuestas HTTP 204 (`evaluation/observability/opik_h4_agri_h1_send_2026_10_24`).

`multiagent/opik_bridge.py` añade lo que faltaba:
- **Importación histórica:**
  - convierte un directorio de resultados sellado (formato piloto) en un `OpikPlan`, después de verificar su `SHA256SUMS`;
  - **solo convierte los spans registrados**; las etapas que no se ejecutaron no tienen span y aparecen en `metadata.tfg_stages_not_executed`;
  - el span de tipo `llm` es la llamada real al modelo (`tfg_execution: REAL_LLM_CALL`); el resto son `DETERMINISTIC_COMPUTATION`;
  - los tiempos son los originales (`started_utc` más las duraciones de `perf_counter`).
- **Control de salida:** redacción de secretos, sustitución de rutas locales y búsqueda de secretos y rutas en todo lo que saldría. Un hallazgo bloquea el envío.
- **Manifiesto:** ids, spans, tamaños y sha256 de cada petición, y la lista de lo que sale del ordenador.
- **Ledger** (`ledger.json`): registra la intención antes del POST.
  - Un id que ya está en el ledger **nunca se reenvía**.
  - Un envío `UNCERTAIN` bloquea el reenvío hasta verificarlo.
  - Solo una traza verificada como ausente (`VERIFIED_ABSENT`) admite reenvío, y solo con `--retry-verified-absent`.
- **Verificación:** `GET /v1/private/traces/{id}` comprueba el id, el proyecto, los metadatos de importación y que no aparezca ningún secreto en la respuesta. Si el servicio da `project_id`, se registra el enlace. La ruta del GET sigue la API REST y **no estará verificada hasta su primer uso real**.

`multiagent/opik_datasets.py` prepara los datasets y experimentos de Opik, solo como dry run (§5).

## 2. Configurar las credenciales en WSL

Se usa el mecanismo oficial de Opik: la variable `OPIK_API_KEY` o el archivo `~/.opik.config` (sección `[opik]`, el formato que escribe `opik configure`). La clave se lee solo en el momento de enviar; nunca se imprime ni se guarda en trazas, ledger o registros.

**Opción A, archivo** (recomendada; la clave no pasa por el historial):

```bash
umask 077
read -rsp "Opik API key: " OPIK_KEY; echo
printf '[opik]\nurl_override = https://www.comet.com/opik/api\nworkspace = joowww\napi_key = %s\n' "$OPIK_KEY" > ~/.opik.config
unset OPIK_KEY
chmod 600 ~/.opik.config
```

**Opción B, solo durante la sesión:**

```bash
read -rsp "Opik API key: " OPIK_API_KEY; echo; export OPIK_API_KEY
# ... comandos de envío y verificación ...
unset OPIK_API_KEY
```

**Comprobación** (solo informa de si están presentes, nunca de los valores):

```bash
.venv/bin/python -m multiagent.opik_bridge status
```

El envío se niega en estos casos:
- `OPIK_WORKSPACE` o el `workspace` del archivo apuntan a otro workspace;
- el archivo es legible por otros usuarios;
- `url_override` apunta a otro servicio.

## 3. Importar el piloto real (qwen3:4b, 11 llamadas, sin repetirlas)

Fuente: `multiagent/benchmark/results/pilot_qwen3_4b_v1_2026-11-04_c00b737d3` (sello verificado).

Cada traza lleva:
- el caso, el modelo y su *digest*;
- el dataset con versión y sha256;
- el *prompt* (id y sha256) y los parámetros de generación;
- el texto del operador, el *prompt* completo y la respuesta original;
- las validaciones, el resultado y los criterios;
- la seguridad y la clase de fallo;
- la latencia y los tokens observados;
- el coste (`NOT_APPLICABLE_LOCAL_MODEL`);
- las etapas no ejecutadas;
- las referencias a los archivos originales (rutas relativas al repositorio y sha256).

Las trazas de las reglas sobre los mismos 11 casos se importan aparte (`--candidate-dir rules`) y se etiquetan como `deterministic_baseline_sealed_record`.

**Dry run verificable** (determinista; los hashes deben coincidir con los del repositorio):

```bash
.venv/bin/python -m multiagent.opik_bridge dry-run multiagent/benchmark/results/pilot_qwen3_4b_v1_2026-11-04_c00b737d3 --cases E07 --out /tmp/check_E07.json
```

Para E07 (traza `01a1a76e-e360-7b24-9ca0-f4088fe20e36`, 12 spans, 1 LLM):

| Petición | Bytes | sha256 |
| --- | --- | --- |
| `traces/batch` | 3283 | `56a8d3a661091cfc49500d948f058bde36ecae37c72becdbed448e32174d9461` |
| `spans/batch` | 11995 | `09af3bc214bae06bc78098ad8593ae86a8959bc4ff840b86e3e710af72b6776e` |

Hallazgos de salida: ninguno.

**Primer envío.** Solo con autorización expresa, de una sola traza:

```bash
R=multiagent/benchmark/results/pilot_qwen3_4b_v1_2026-11-04_c00b737d3
O=multiagent/benchmark/opik_imports/joowww__tfg-multiagent-benchmarks
.venv/bin/python -m multiagent.opik_bridge send $R --cases E07 --i-authorize-send --record $O/send_E07_$(date -u +%Y%m%dT%H%M%SZ).jsonl
.venv/bin/python -m multiagent.opik_bridge verify 01a1a76e-e360-7b24-9ca0-f4088fe20e36
```

`HTTP_ACCEPTED_NOT_VERIFIED` (dos 204) **no es todavía éxito**: el éxito es `VERIFIED_PRESENT` tras el `verify`. Si algo falla, se para; no hay envío masivo.

**Las otras diez trazas** (después de verificar E07):
1. Repetir dry run, envío y verificación caso a caso, o en grupos con `--max-traces N` una vez validado el formato.
2. Cada envío requiere su propia autorización. El ledger impide reenviar lo ya enviado.
3. Las trazas de reglas, con `--candidate-dir rules`.

## 4. Lo que sale del ordenador

Está detallado en `manifest_pilot_all.json` → `leaves_the_computer`:
- **Traza:**
  - el texto del operador (sintético);
  - el resumen de la salida;
  - los metadatos listados en §3;
  - etiquetas `case:`, `dataset:`, `model:`, `prompt:`, `outcome:` y `experiment:`.
- **Span LLM:** el *prompt* completo (puntos sintéticos y petición), la respuesta en bruto, el brief interpretado, el uso de tokens y el motivo de fin.
- **Spans deterministas:** las entradas y salidas registradas (ya redactadas) y su estado.
- **Nunca:** credenciales, rutas absolutas ni nada que no esté en el registro sellado.

## 5. Datasets y experimentos de Opik (preparados, no subidos)

`datasets_experiments.dry_run.json` contiene tres cosas distintas:
- **Trazas:** lo que hizo cada ejecución (§3).
- **Datasets:** `multiagent-eval_v2` (33 casos), `multiagent-dev_v3` (14), `multiagent-eval_v3` (26) y `multiagent-adversarial_v3` (13). Cada caso lleva su texto, los criterios esperados y el brief de referencia, con ids de ítem deterministas.
- **Experimentos:** un candidato sobre un dataset, enlazando cada ítem con su traza. Hoy solo existen los que tienen ejecución real y trazas:
  - `eval_v2@2 | ollama:qwen3:4b | interpret_brief/1 | pipeline v1 | pilot_v1` (11 ítems);
  - `eval_v2@2 | rules | no-prompt | pipeline v1 | pilot_v1` (11 ítems).

**Comparación prevista.** Experimentos con el mismo nombre de dataset y versión, para cada:
- Qwen local;
- reglas;
- Qwen de AIDA;
- proveedor de Hermes;
- versión de *prompt* (/1 frente a /2) y de pipeline.

Clef solo entra en sus propias tareas (clasificar y elegir reparto), en experimentos etiquetados con esa tarea.

**Pendiente:**
- **Líneas base v2 y v3 de las reglas:** no guardan trazas. Para convertirlas en experimentos hay que repetirlas con el ejecutor del piloto.
- **Formas REST** de datasets y experimentos: sin verificar. Antes de subirlas hay que crear y leer un dataset de un solo ítem, con autorización aparte.
- ***Feedback scores*:** las métricas viajan en `metadata`. La fase 2 ([opik-fase2.md](opik-fase2.md)) añade el mapeo a *scores*, los campos nativos y las formas validadas de datasets y experimentos, todo sin enviar. `datasets_experiments.dry_run.json` es el diseño anterior y queda como registro.

## 6. Ejecuciones futuras

- **Por defecto:** `TFG_OPIK_MODE=off`.
- **`TFG_OPIK_MODE=dry_run`, o `opik_mode="dry_run"` en `pilot.run_pilot`:** cuando termina una ejecución, escribe en `<run>/opik/` los planes de las reglas y del modelo, con su propio `SHA256SUMS`.
- **El envío nunca es automático:** cualquier otro valor se rechaza, y enviar sigue siendo `opik_bridge send`, con autorización.
- **Cobertura:** las categorías de observabilidad (orquestador, interpretación LLM, validación de seguridad, reparto, coordinación de enjambre, rover y resultado global) se asignan a los spans en `tfg_stage`. Las etapas no ejecutadas se listan en `tfg_stages_not_executed`, también en las trazas en vivo (`tracing.opik_plan`).

## 7. Reproducir

| Qué | Cómo |
| --- | --- |
| Los resultados originales | No se tocan; `sha256sum -c` en cada directorio de `results/` |
| El dry run | Es determinista: mismo directorio sellado, mismos ids y mismos cuerpos |
| Los tests | `.venv/bin/python -m pytest -q tests/test_multiagent_opik_bridge.py` (servicio Opik simulado: destino, redacción, duplicados, reintentos, fallos de red, trazas incompletas e integridad del piloto) |
