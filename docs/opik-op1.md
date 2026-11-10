# Opik después de OP-1 (06/11/2026)

## Qué se envió y qué está verificado

| Operación | Estado | Evidencia |
| --- | --- | --- |
| E07 (04/11) | **Enviada y verificada**: HTTP 204/204, lectura 200, 12 spans; `VERIFIED_PRESENT` | `ledger.json`, `send_E07_20261104T183637Z.jsonl` |
| OP-1 (06/11): las 10 trazas Qwen pendientes | **Intentada una vez y rechazada.** `traces/batch` devolvió HTTP 400; `spans/batch` no se intentó. Lectura posterior: 404 en las diez. **No se almacenó nada y no se reenvió** | `op1_2026-11-06/` (preflight 13/13 PASS, `send_result.json`, README, SHA256SUMS) y `send_OP1_20261106T103041Z.jsonl` |

Las diez entradas del ledger quedan en `UNCERTAIN`, con `post_failure_readback` (404) y `diagnosis`, tal como pediste («marca el estado como incierto»). Ese estado bloquea cualquier reenvío automático.

**Causa inferida (no confirmada: el cuerpo del error no se guardó).** El código público de Opik (`comet-ml/opik@df61dd21c66e`) rechaza con `400 "Invalid UUID for id"` los UUIDv7 cuya marca de tiempo embebida queda fuera de una ventana de ingesta, de 24 h por defecto (`uuidValidation` en `config.yml`, `IdGenerator.validateId`).
- **Los diez:** sus ids llevan la hora original del piloto, del 04/11 a las 16:39–16:42 UTC. El lote salió el 06/11 a las 10:30 UTC, unas 42 h después.
- **E07:** su id lleva las 16:40 y se envió a las 18:36 del mismo día, unas 2 h después, y fue aceptado.

## Corrección del exportador (offline)

- **`send_import`** rechaza, antes de conectar, cualquier id fuera de la ventana (24 h, con 1 h de margen).
- **`historical_plan(id_epoch=…)`** cambia solo la componente temporal de los ids y conserva el orden relativo. `start_time` y `end_time` siguen siendo las históricas, y el desplazamiento se declara en `metadata.tfg_id_epoch`. `OpikPlan.id_shifts` permite que la propia guarda de derivación de ids del exportador compruebe los ids reestampados, sin relajarla.
- **Un caso ya presente en el ledger con otro id** solo puede reemplazarse si ese id leyó 404 y se nombra en `supersedes`.
- **El cuerpo de error del próximo envío fallido** se guarda en un archivo con permisos 0600.

## OP-1b: lo que necesitaría una autorización nueva

Mismas diez trazas, con ids reestampados. Cambian los cuerpos y, por tanto, los hashes; la autorización de OP-1 **no** cubre OP-1b.

```bash
python -m multiagent.opik_op1 prepare --id-epoch <ISO UTC> --out <dir nuevo>     # imprime los dos hashes
# autorización de Joel con esos hashes; después, dentro de la ventana (±23 h del epoch):
python -m multiagent.opik_op1 send --i-authorize-op1b --id-epoch <mismo ISO> --traces-sha <h> --spans-sha <h>
python -m multiagent.opik_op1 verify --id-epoch <mismo ISO> --out <archivo>
```

## Operaciones remotas pendientes, todas sin ejecutar

| Id | Qué | Nota tras OP-1 |
| --- | --- | --- |
| OP-1b | Las 10 trazas Qwen, con ids reestampados | Nueva autorización y nuevos hashes |
| OP-2 | Las 11 trazas de reglas | **El mismo problema:** sus ids son del 04/11. Hay que reestamparlas (`id_epoch`) y volver a autorizar |
| OP-3 | PATCH nativo de E07 | Una actualización admite ids antiguos (`validateIdNotInFuture`), así que el reestampado no aplica. Sigue sin autorizar |
| OP-4 | *Feedback scores* | Solo de trazas presentes. La traza de E07 es la única hoy |
| OP-5 | 4 datasets | Sin cambios |
| OP-6 | Experimentos | Requieren que existan sus trazas |
| OP-7 | Dashboards | Sin cambios |
| Pilotos M1/M2/M3 | Trazas, *scores* y experimentos propios (`<resultados>/opik/dry_run.json`) | Experimentos distintos de OP-1. Sus ids llevan la hora de la ejecución, así que hay que enviarlos en menos de 24 h o reestamparlos |

## Evidencia real suficiente e insuficiente

- **Suficiente para mostrar, no para concluir:**
  - el piloto Qwen de interpretación (11 casos, 1 ejecución);
  - los pilotos M1, M2 y M3 (3 casos por rol, 1 ejecución).
- **Insuficiente:**
  - cualquier percentil de latencia (n = 1 por caso);
  - la consistencia entre repeticiones (no hay repeticiones);
  - el coste (local: no aplica);
  - las métricas multiagente con más de tres casos;
  - todo lo de AIDA, Clef y el proveedor Hermes (no ejecutados).

## OP-1b preparada (06/11/2026, tarde) — sin autorizar y sin enviar

**Revisión del importador oficial** (`comet-ml/opik@df61dd21c66e`: `sdks/python/src/opik/cli/imports/project.py` y `api_objects/trace/migration.py`):
- `opik import` crea ids nuevos con la hora actual, con lo que queda dentro de la ventana UUIDv7.
- Conserva `start_time` y `end_time`.
- Guarda el id de origen en `metadata._import_id`.
- Remapea `trace_id` y `parent_span_id`, y persiste el mapeo en su manifiesto.

Sus ids son **aleatorios**, así que el cuerpo exacto no puede autorizarse por hash antes del envío. Por eso mantenemos el reestampado determinista (`id_epoch`), adoptando la misma convención:

| Requisito | Cómo se cumple |
| --- | --- |
| Resultados originales intactos | El piloto sellado no se toca; el plan se reconstruye desde él |
| Ids de importación nuevos | Componente temporal desplazada a `id_epoch`; mismo *scope*, así que el resultado es reproducible |
| `start_time` y `end_time` históricos | No cambian (`tfg_id_epoch` declara el desplazamiento) |
| Jerarquía padre-hijo | `trace_id` y `parent_span_id` remapeados (test) |
| Correspondencia con los ids originales | `metadata._import_id` en trazas y spans, más `id_mapping`: 72 filas (10 trazas y 62 spans) |
| Proyecto, E07 excluida, 10 casos y sus spans | Verificado en el manifiesto y en la comprobación previa |
| Redacción de secretos | La misma ruta de egreso (`egress_findings` y el escaneo) |
| Sin reintentos de envíos inciertos | `send_import` y el ledger, sin cambios |
| Hashes canónicos reproducibles | `content_sha256`, independiente de los ids: traces `15fa84cc592a05f4dfeb61905cc6443f995b866bf70f64c7845f97863b0dcb9f`, spans `1dfc76cb921ef2e671d435254f85039d589834d84ebf0dbfc1dbf289029bcd7a`. Los hashes exactos del cuerpo solo se generan al importar |
| Pruebas con UUID antiguos, nuevos e inválidos | `import_id_findings`: ids que no son UUIDv7 canónicos, referencias colgantes y ids fuera de ventana |
| No es una ejecución nueva | `tfg_import: HISTORICAL_SEALED_RECORD` se mantiene; no se llama a ningún modelo |
| Ledger diferenciado | Las 10 entradas de OP-1 tienen `import_generation: 1` y `attempt_outcome: REJECTED_HTTP_400_READ_BACK_404`. OP-1b escribirá `import_generation: 2` y `supersedes` |

Ficheros en `opik_imports/joowww__tfg-multiagent-benchmarks/op1b_2026-11-06/`: `manifest.json` y `AUTORIZACION_OP1b.md` (autorización en dos pasos), con su `SHA256SUMS`. No he preparado ningún cuerpo con ids definitivos, porque caducaría.
