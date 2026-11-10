# Integración con `CODEX_ADAPTER`, Hermes y `.plan`: evidencia del 07/11/2026 (tarde)

**Tipo: SINTÉTICO** (`TEST_FIXTURE` y `SYNTHETIC_SENSOR`), con dos materiales más: la petición sellada de M4c-r1, leída sin modificarla, y el exportador/importador `.plan` de Hermes.
- No se llamó a ningún modelo.
- No se arrancó SITL, Gazebo ni ROS 2.
- No se envió MAVLink.
- No existe ningún vehículo.
- No se publicó nada en Opik.
- **Comandos producidos: 0 en todos los casos.**

## Procedencia

- **Código multiagente:** `32c19517d`, con el árbol limpio (`provenance.json`, `git_relations.json`).
- **Codex:** dos *snapshots* inmutables (`contract_comparison.json`):
  - **committed:** `57a0e303a`;
  - **reviewed:** `2e206f1fa` más el parche de revisión protegida, con su sha256 `551eb1fe…` verificado y aplicado solo dentro del *snapshot*.
  - Difieren en `schemas/rover-mission-execution-v2.schema.json` y `tools/rover_control.py`.
  - **Ninguno de los dos contiene `tools/rover_payload_executor_adapter.py`.**
- **Árbol de trabajo de Codex:** no se leyó para ejecutar nada y no se escribió.
- **Comando de generación:**
  ```
  python -m multiagent.benchmark.codex_adapter_evidence --out <este directorio> --scratch <dir> --junit <xml> --smoke <json>
  ```

## Contenido y resultados

| Archivo | Resultado |
| --- | --- |
| `codex_adapter/`, `codex_adapter_summary.json` | **Contrato final `CODEX_ADAPTER`** (ver el detalle más abajo) |
| `handoff_committed/`, `handoff_reviewed/` | Ruta de prueba offline (`CLAUDE_FRAMES2D`): 18/18 casos según lo esperado en cada *snapshot* |
| `mission_inputs/` | Ida y vuelta de un `.plan` por Hermes → `PROPOSED_PENDING_AUTHORIZATION` sobre POI_1 y POI_3; otro sitio → `REJECTED`; lenguaje natural → `TO_INTERPRET` |
| `plan_semantics/` | `.plan` y manifiesto de ejemplo. Hay 6 elementos que un `.plan` no puede representar: 2 acciones, 2 sensores y 2 identificadores. Con el manifiesto se pierden **0**; sin él, **6**, todos detectados uno a uno |
| `sitl_topics.json` | *Namespaces* `/ap/v1`, `/ap/v2` y `/ap/v3` confirmados por el *baseline*. Los *topics* tienen estado y evidencia; **ninguno se puede ingerir** sin una acreditación de ingestión |
| `battery_committed.json`, `battery_reviewed.json` | 18/18 misiones en cada *snapshot*; 0 comandos |
| `scenarios_safety3.json`, `scenarios_safety4.json` | 17/17 escenarios con cada política; 0 comandos |
| `integration_smoke.json` | 13/13 áreas PASS. En `langgraph`, 4 pruebas son `NOT_RUN_DATA_ABSENT`: necesitan una captura REAL que excluye `.gitignore`. Con esa captura pasan 151/151 sobre un `git archive` |
| `pytest_multiagent.xml` | 969 pruebas: 967 superadas, 2 omitidas (el *ledger* solo existe en el *snapshot* revisado), 0 fallos |
| `git_relations.json` | `main` = `6e78668d9`; base común con Codex `4d92f9813`; el único archivo cambiado en los dos lados es `docs/INDEX.md`; Hermes y natural-QGC son ancestros; `feature/ardupilot-ros2` no lo es |

### Detalle del contrato final `CODEX_ADAPTER`

- **Caso sintético:** `V2_READY_AWAITING_CODEX_ADAPTER`.
  - El objetivo se queda en el marco del sitio.
  - La transformación queda `REQUIRED_NOT_APPLIED`.
  - Este lado aplica 0 conversiones.
- **13 negativos en los dos modos:** todos `BLOCKED_BEFORE_SUBMISSION`, con errores estructurados y sin ninguno `UNCLASSIFIED`. Los casos son:
  - transformación no acreditada;
  - pose de otro rover;
  - cambio de *boot*;
  - incertidumbre excesiva;
  - localización caducada o perdida;
  - observación caducada o retirada;
  - dependencia aérea fallida;
  - autorización revocada;
  - *scope* de otro plan;
  - objetivo ya en el marco del rover (doble conversión);
  - propietario de la conversión no declarado.
- **M4c-r1:** `BLOCKED_BEFORE_SUBMISSION`, con las categorías PLAN, AUTHORIZATION, LOCALIZATION y FRAMES. Conserva su procedencia (`REAL_LOCAL_LLM` registrado, 0 llamadas nuevas), las asignaciones de los drones, los *gates*, las dependencias y el objetivo.

## Lo que esta evidencia no demuestra

- Que nada se mueva.
- Que el adaptador de Codex exista en un commit: no existe.
- Que haya una autorización humana real o un recibo `AUTHENTICATED`.
- Que haya una ingestión SITL acreditada.
- La calidad de un LLM: no hubo llamadas.

Esta carpeta es un registro sellado de su fecha. No se modifica ni se regenera.
