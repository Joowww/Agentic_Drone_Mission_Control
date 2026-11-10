# Auditoría offline del piloto `agri-scenario-pilot-real` — 25/10/2026

Sin inferencias, Opik ni simulación. Las evidencias del piloto
([`agri_scenario_pilot_nous_2026_10_24`](../agri_scenario_pilot_nous_2026_10_24/README.md)) conservan
sus evaluaciones originales.

| Archivo | Contenido |
| --- | --- |
| [`pilot_report.md`](pilot_report.md) / `pilot_report.json` | Informe generado por `pilot-report`: denominadores, recuentos con sus claves, peticiones lógicas, intentos fallidos y reintentos del cliente, aceptación original y posterior, tokens y datos desconocidos |
| `*.accept_h3b_reeval.json`, [`reeval_summary.json`](reeval_summary.json) | H3b y las nueve sesiones del piloto con sesión exportada, reevaluadas con el evaluador endurecido. Las diez coinciden con su evaluación vigente (r06, con la posterior a la corrección); r02 no tiene sesión que evaluar |
| [`protocol_v2_proposal.json`](protocol_v2_proposal.json) | Propuesta **no implementada ni autorizada**: asignación explícita de los `claims`, regla de `null` sin ambigüedad y desactivación de los reintentos de Hermes |

## Evaluador endurecido

Se probó con respuestas malformadas sobre la vista real. Seis casos lanzaban una excepción o se
aceptaban en silencio; ahora se rechazan de forma explícita:

| Entrada | Antes | Ahora |
| --- | --- | --- |
| `runs` como número o booleano | excepción `TypeError` | `runs.not_a_list` |
| `run_id` como lista u objeto | excepción `TypeError` | `runs.malformed_entries` |
| Elemento de `runs` que no es un objeto | ignorado | `runs.malformed_entries` |
| Ejecución duplicada | aceptada (la última sustituía a la primera) | `runs.duplicate_run_ids` |
| `0` o `1` en una clave booleana | `0 == False` contaba como acierto | discrepancia (tipo estricto) |
| Clave JSON repetida (`true` … `false`) | aceptada con el último valor | `answer.duplicate_json_keys` y clasificación `DUPLICATE_JSON_KEYS:<clave>` |
| Anidamiento patológico | excepción `RecursionError` en `parse_answer` | `NOT_JSON` |

**Lo que ya se rechazaba bien:** texto no JSON, vacío, `null`, lista JSON, dos objetos seguidos,
claves ausentes, tipos incorrectos, listas anidadas o duplicadas en `reached_points`, valores
críticos contradictorios, argumentos de la herramienta malformados y resultados ilegibles de la
herramienta.

**Claves adicionales:** se registran como clasificación `EXTRA_TOP_LEVEL_KEYS`, sin rechazar, porque
el contrato enumera las claves pero no prohíbe otras.

**Límite de tamaño:** **no existe** ninguno en el evaluador ni en `parse_answer`. Una explicación de
2 MB se evalúa entera; añadir un límite cambiaría el contrato y queda como decisión de un protocolo
futuro.

```bash
.venv/bin/python -m reporting.agri_scenario_summary pilot-report --evidence-dir evaluation/observability/agri_scenario_pilot_nous_2026_10_24 --reeval-dir evaluation/observability/agri_scenario_pilot_audit_2026_10_25
```

```bash
.venv/bin/python -m reporting.agri_scenario_summary pilot-review-sheet --evidence-dir evaluation/observability/agri_scenario_pilot_nous_2026_10_24 --observations evaluation/observability/agri_scenario_pilot_nous_2026_10_24/explanation_observations_by_criterion.json
```
