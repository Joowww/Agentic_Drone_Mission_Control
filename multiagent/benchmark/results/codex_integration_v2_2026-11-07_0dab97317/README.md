# Integración Rover Agent ↔ Codex (contrato v2): evidencia del 07/11/2026

**Tipo: SINTÉTICO** (`TEST_FIXTURE` + `SYNTHETIC_SENSOR`), con dos materiales más: la petición sellada de M4c-r1, leída sin modificarla, y el exportador/importador `.plan` de Hermes.
- No se llamó a ningún modelo.
- No se arrancó SITL ni Gazebo.
- No existe ningún vehículo.
- No se envió MAVLink.
- No se publicó nada en Opik.
- **Comandos producidos: 0 en todos los casos.**

## Procedencia

- **Código multiagente:** `0dab97317`, árbol limpio en `multiagent/` y `tests/`. Rama `feature/multiagent-opik-evaluation`.
- **Codex, *snapshot* «committed»:** `git archive 57a0e303a`. El contrato es idéntico en `1514053da` y `2e206f1fa`.
- **Codex, *snapshot* «reviewed»:** `git archive 2e206f1fa` más su parche de revisión protegida `docs/checkpoints/2026-11-07-rover-protected-review.patch`.
  - Antes de aplicarlo se verificó su sha256: `551eb1fefebcaf31ee635472859d8dee3809755d635dd98a717919996eb3a594`.
  - El parche se aplicó **solo dentro del *snapshot***.
- **Árbol de trabajo de Codex:** no se leyó para ejecutar nada y no se escribió.
- **Comando de generación:**
  ```
  python -m multiagent.benchmark.integration_v2_evidence --out <este directorio> --scratch <scratch> --junit <xml>
  ```
- **`provenance.json`:** commits, *digests* del contrato y versión de Python.

## Contenido y resultados

| Archivo | Qué es | Resultado |
| --- | --- | --- |
| `handoff_committed/`, `handoff_reviewed/` | 18 casos por *snapshot*, cada uno con su traza de 9 etapas: el histórico, el sintético completo y 16 negativos | 18/18 según lo esperado en ambos; 0 comandos |
| `handoff_extra.json` | *Ledger* de Codex (concesión *fixture* y concesión revocada) y conversión delegada al adaptador de Codex | Ver más abajo |
| `mission_inputs/` | Ida y vuelta de un `.plan` QGC por el exportador/importador de Hermes hasta el plan multiagente, una misión de otro sitio y una entrada en lenguaje natural | QGC → `PROPOSED_PENDING_AUTHORIZATION` sobre POI_1 y POI_3; otro sitio → `REJECTED OUTSIDE_SITE_GEOREFERENCE`; lenguaje natural → `TO_INTERPRET` |
| `battery_committed.json`, `battery_reviewed.json` | Batería de integración de 18 misiones | 18/18 en cada *snapshot*; 0 comandos |
| `scenarios_safety3.json`, `scenarios_safety4.json` | Los 17 escenarios de la demo | 17/17 con cada política; 0 comandos |
| `pytest_multiagent.xml` | Suite multiagente ejecutada en `0dab97317` | 873 pruebas: 871 superadas, 2 omitidas (el *ledger* solo existe en el *snapshot* revisado), 0 fallos |
| `summary.json`, `SHA256SUMS` | Resumen y hashes de todos los archivos (recursivo) | — |

### Caso sintético completo

Snapshot reviewed:

| Etapa | Estado |
| --- | --- |
| request | PASS |
| coordinator | PASS |
| authorization | PASS |
| codex_bridge | PASS |
| frames | PASS |
| codex_v2 | PASS, 0 errores de esquema |
| executor_request | PASS |
| executor_admit | **BLOCKED** `OPERATIONAL_ROVER_POLICY_DISABLED` |
| dry_run | REFUSED |

- **Sobre:** `READY_TO_SUBMIT_NOT_EXECUTED`.
- **Clasificación:** `READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED`.
- **Snapshot committed:** misma clasificación, pero el esquema v2 rechaza `authorization.bridge_scope_sha256`. El parche de revisión de Codex resuelve exactamente eso.

### Casos negativos

Primera causa de bloqueo de cada caso, idéntica en ambos *snapshots*:

| Caso | Bloquea en | Motivo |
| --- | --- | --- |
| historical_m4c_r1 | request | `NO_NAVIGATION_PLAN` (ningún humano fijó velocidad ni duración) |
| wrong_scope | authorization | `PLAN_ID_MISMATCH` |
| other_vehicle | authorization | `ROVER_ID_MISMATCH` |
| no_authorization | authorization | `NO_HUMAN_AUTHORIZATION_RECORD` |
| expired_authorization | authorization | `OUTSIDE_VALIDITY_WINDOW` |
| operational_mode_refuses_fixtures | authorization | `FIXTURE_AUTHORIZATION_NOT_ACCEPTED_IN_OPERATIONAL_MODE` |
| target_expired | coordinator | `BLOCKED_OBSERVATION_EXPIRED` |
| aerial_dependency_lost | coordinator | `BLOCKED_DEPENDENCY_LOST` |
| observation_refused_still_waiting | coordinator | `CONDITIONAL_AWAITING_OBSERVATION` |
| mission_cancelled | coordinator | `CANCELLED` |
| rover_without_position | frames | `ROVER_LOCALIZATION_NOT_ACCREDITED` |
| incompatible_frame | frames | `ROVER_LOCALIZATION_FRAME_MISMATCH` |
| no_transform | frames | `UNKNOWN_FRAME` |
| expired_transform | frames | `CHAIN_NOT_USABLE … EXPIRED_OR_NOT_YET_VALID` |
| speed_and_duration_not_set | request | `NO_NAVIGATION_PLAN` |
| no_operator_receipt | codex_v2 | `AUTHENTICATED_OPERATOR_RECEIPT_UNAVAILABLE` |
| executor_parameters_not_declared | executor_request | `EXECUTOR_PARAMETERS_NOT_DECLARED` (se clasifica `V2_READY_EXECUTOR_REQUEST_INCOMPLETE`) |

La suite (`pytest_multiagent.xml`, `test_multiagent_codex_integration_v2.py`) cubre además estos casos:
- *hash* de plan manipulado;
- payload v1 presentado como v2;
- campo desconocido;
- STOP incierto;
- un Rover Agent que se declara autorizado (`AGENT_CLAIMS_AUTHORITY`).

### Casos adicionales (`handoff_extra.json`)

- **Concesión *fixture* del *ledger* de Codex** (snapshot reviewed): `BLOCKED_BEFORE_SUBMISSION`, motivo `OPERATOR_NOT_AUTHENTICATED`. El *ledger* la emite como `DECLARED`, no `AUTHENTICATED`, y el validador v2 de Codex la rechaza. Es el comportamiento correcto: un *fixture* no es un operador autenticado.
- **Concesión revocada:** `RECEIPT_REFUSED_BY_LEDGER: AUTHORIZATION_NOT_ACTIVE`.
- **Conversión delegada a `CODEX_ADAPTER`:** este lado no convierte. El v2 queda listo y la petición al executor llega como `NOT_REACHED` con `CONVERSION_DELEGATED_TO_CODEX_ADAPTER`, porque el executor actual exige el objetivo ya en el marco del rover.

## Lo que esta evidencia no demuestra

- Que nada se mueva en SITL, en Gazebo o en un vehículo real.
- Que exista una autorización humana real: todas son *fixtures*, y en modo `OPERATIONAL` se rechazan.
- Que el executor de Codex consuma el v2: hoy no tiene entrada v2.
- La calidad de un LLM: no hubo llamadas.

Esta carpeta es un registro sellado de su fecha: no se modifica ni se regenera. Una evidencia nueva va en un directorio nuevo.
