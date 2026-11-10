# Para el subsistema rover: compatibilidad entre el puente multiagente y el contrato y el executor del rover (07/11/2026, actualizado por la tarde)

## Decisión vigente: la conversión sitio → `odom`/`map` la hace `ROVER_ADAPTER`

Desde el 07/11, por la tarde, el Rover Agent mantiene el objetivo en el marco del sitio. Este lado entrega `tfg.multiagent.rover-goal-handoff/1` (`multiagent/rover_goal_contract.py`, dentro del sobre como `goal_handoff`), que contiene:
- el objetivo en el sitio y la identidad de los marcos;
- la observación, con su fuente, *timestamp*, pose original e incertidumbre;
- las dependencias;
- la referencia a la transformación requerida, con su cadena, sha, acreditación, vigencia, sigma y matriz en la forma del subsistema rover, en estado `REQUIRED_NOT_APPLIED`;
- el estado de la localización, el vehículo y el *boot*;
- las restricciones;
- `applied_conversions: []`;
- las comprobaciones delegadas: hoy, la distancia al rover.

Antes del envío, este lado ejecuta las mismas comprobaciones que antes (`frames2d.goal_for_rover(apply=False)`), **sin convertir**.

**Modos:**
- **Sin modo por defecto:** si no se declara, el resultado es `CONVERSION_OWNER_NOT_DECLARED`.
- **`MULTIAGENT_FRAMES2D`:** queda como modo de prueba offline, para llegar a la admisión del executor actual. En `OPERATIONAL` se rechaza.

**Protección contra la doble conversión:**
- como mucho, una conversión registrada;
- `record_conversion` rechaza una segunda conversión, o la de un componente que no es el propietario;
- un objetivo que ya está en el marco del rover se rechaza (`GOAL_ALREADY_IN_ROVER_FRAME`);
- el executor debe recibir `IDENTITY_SAME_ACCREDITED_FRAME` y el mismo punto que se registró.

**Estado:** ninguno de los dos *snapshots* contiene `tools/rover_payload_executor_adapter.py`. Con `ROVER_ADAPTER`, la clasificación es `V2_READY_AWAITING_ROVER_ADAPTER` y el motivo `ROVER_ADAPTER_NOT_IN_SNAPSHOT`. **No se declara operativa una integración que solo existe sin promover.**

**Errores estructurados:** cada traza lleva `errors` con `{stage, code, detail, category}` y `error_categories`. La categoría `LOCALIZATION` llega al coordinador como `NO_POSITION`, y la tarea pasa a `WAITING_FOR_ROVER_LOCALIZATION`: nunca queda como una autorización válida.

Evidencia: `multiagent/benchmark/results/codex_adapter_integration_2026-11-07_32c19517d/`.

## Revisiones comprobadas

Se probaron dos *snapshots* inmutables (`git archive`), cada uno en un proceso aislado (`multiagent/rover_snapshot_runner.py`):
- **committed:** `57a0e303a`. El contrato es idéntico en `1514053da` y `2e206f1fa` (sha256 en `rover_handoff.contract_digest`).
- **reviewed:** `2e206f1fa` más su `docs/checkpoints/2026-11-07-rover-protected-review.patch`.
  - Antes de aplicarlo se verificó su sha256: `551eb1fefebcaf31ee635472859d8dee3809755d635dd98a717919996eb3a594`.
  - Se aplicó **solo dentro del *snapshot*** (`ensure_snapshot(reviewed=True)`).

Su worktree no se ha escrito nunca. Para ejecutar no se lee: se lee solo para este informe (ver «Lo que declara el subsistema rover»).

## Evidencia vigente

`multiagent/benchmark/results/codex_integration_v2_2026-11-07_0dab97317/` (SINTÉTICO, sellada). Contiene:
- 18 casos de traspaso por *snapshot*;
- los casos del *ledger* del subsistema rover y de la conversión delegada;
- la batería de 18 misiones en los dos *snapshots*;
- los 17 escenarios con `safety/3` y `safety/4`;
- el JUnit de la suite: 871 superadas, 2 omitidas.

En todos los casos, **0 comandos**. La evidencia anterior (`rover_handoff_offline_2026-11-07_0c886b624/`) se conserva sin cambios.

## Cadena comprobada

Rover Agent → coordinador → puente → *payload* v2 → validación del subsistema rover → admisión protegida → *dry-run*.

Con el caso sintético completo y el *snapshot* reviewed:

| Etapa | Estado |
| --- | --- |
| request | PASS |
| coordinator | PASS |
| authorization | PASS |
| rover_bridge (`validate_bridge_request`) | PASS |
| frames | PASS |
| rover_v2 (`adapt_request` + `validate`) | `READY_TO_SUBMIT`, 0 errores de esquema |
| executor_request (`_request` de `ROVER_NAVIGATE_V1`) | PASS |
| executor_admit (`admit_ground_trial`) | **BLOCKED** `OPERATIONAL_ROVER_POLICY_DISABLED` |
| dry_run | REFUSED |

El resultado es el sobre `tfg.multiagent.rover-submission/1` en estado `READY_TO_SUBMIT_NOT_EXECUTED`. **No es un comando**: `commands: []` y `movement_authorized: false`.

## Responsabilidades (sin duplicar el validador del subsistema rover)

| El subsistema rover | Este lado |
| --- | --- |
| Esquema JSON canónico | Rover Agent |
| Validador v2 | Coordinador (dependencias aéreas, caducidad, cancelación) |
| Adaptador de entrada del executor | Integridad de la observación |
| Comprobación de *scope* | Transformación geométrica, cuando el propietario es `MULTIAGENT_FRAMES2D` |
| Admisión operativa | Construcción del *payload* |
| Política protegida | Validación previa al envío e interpretación de los errores |

Este lado no reimplementa el validador v2: llama al del subsistema rover en su *snapshot* y solo interpreta sus motivos.

## Estado de cada punto

| # | Punto | Estado |
| --- | --- | --- |
| 1 | `bridge_scope_sha256` en `payload.authorization` frente al esquema | **Resuelto en el *snapshot* reviewed.** El esquema committed lo rechaza y el reviewed lo acepta (`schema_errors == []`), sin ningún cambio en nuestro puente. Prueba: `test_multiagent_rover_integration_v2.py::test_the_bridge_scope_field_is_rejected_by_the_committed_schema_and_accepted_by_the_reviewed_one`. Falta que el parche se promueva a un commit |
| 2 | El executor no consume el v2 | **Pendiente en el código commiteado.** Nuestro lado entrega el sobre de envío con todo lo que pide su ruta: el *payload* v2, el objetivo original y el transformado, la autorización y los límites. El subsistema rover declara tener una entrada nueva en su worktree (ver más abajo). No está en ningún commit y no la he ejecutado |
| 3 | Quién convierte sitio → `odom` | **Decidido: `ROVER_ADAPTER`** (ver arriba). **Un único límite de conversión, con un propietario explícito y sin valor por defecto** (`HandoffInputs.conversion_owner`). Con `MULTIAGENT_FRAMES2D` (solo prueba offline), `frames2d.goal_for_rover` convierte una vez y lo registra (`converted_by`, cadena, `chain_source_sha256`, validez). El executor recibe `IDENTITY_SAME_ACCREDITED_FRAME`. Con `ROVER_ADAPTER`, este lado **no convierte**: entrega el objetivo original y la transformación, y el v2 sigue en el marco del sitio. Pruebas: `test_multiagent_frames2d_converts_once_and_records_it` y `test_if_rover_owns_the_conversion_this_side_does_not_convert` |
| 4 | Validez de la observación y dependencias aéreas | Se quedan en este lado (etapa `coordinator`) |
| 5 | Autorización autenticada | Con el *ledger* de referencia del subsistema rover (*snapshot* reviewed), una concesión *fixture* sale `DECLARED`, y su validador v2 la rechaza con `OPERATOR_NOT_AUTHENTICATED`. Es lo correcto. Una concesión revocada da `RECEIPT_REFUSED_BY_LEDGER: AUTHORIZATION_NOT_ACTIVE`. Este lado **no fabrica** un recibo `AUTHENTICATED` a partir del *ledger*: convertir una concesión autenticada en un recibo v2 es tarea del subsistema rover |

### Detalles adicionales

- **Identidad del vehículo:** `goal_for_rover(..., rover_identity=)` rechaza una pose de otro vehículo (`ROVER_IDENTITY_MISMATCH`) o de otro arranque (`ROVER_BOOT_CHANGED`).
- **Agente que se declara autorizado:** `rover_gate.check_v3` rechaza un Rover Agent que se declara autorizado o emite comandos (`AGENT_CLAIMS_AUTHORITY`).

## Lo que declara el subsistema rover

Leído de su worktree **sin commitear** (`docs/checkpoints/2026-11-07-rover-claude-branch-integration.md`). No se ha comprobado ejecutándolo:
- **`bridge_scope_sha256`:** sigue siendo opcional. Si aparece, debe coincidir con el *scope* que calcula el adaptador. El recibo cubre `plan_sha256` y `bridge_scope_sha256`; si cambia uno sin un recibo nuevo, el resultado es `AUTHORIZATION_PLAN_SCOPE_MISMATCH`.
- **Entrada nueva:** `tools/rover_payload_executor_adapter.py`, con la ruta *payload* v2 → `validate` → proveedor de transformación → `ROVER_NAVIGATE_V1` → `_request` → `admit_ground_trial`. Llega a `REQUEST_VALID / BLOCKED_POLICY_DISABLED`.
- **Conversión:** el propietario acordado es **su adaptador de entrada**, que usa `frames2d.goal_for_rover` desde nuestro commit fijado `8fed7dc39`.
- **Pines:** fija los hashes de `rover_v2_bridge.py`, `rover_executor_bridge.py`, `human_authorization.py` y `frames2d.py` de ese commit.

### Compatibilidad con esos pines

| Archivo | Cambio desde `8fed7dc39` | Efecto en sus pines |
| --- | --- | --- |
| `rover_v2_bridge.py`, `rover_executor_bridge.py`, `human_authorization.py` | Ninguno | Siguen válidos |
| `frames2d.py` | Solo aditivo: los argumentos opcionales `rover_identity=None` y `apply=True`, y las claves de salida `conversion`, `transform_reference` y `delegated_checks` | Siguen válidos (fijan un commit). Si los mueve a un commit posterior, ganará la comprobación de identidad y arranque, y el registro de conversión |

**Su prueba commiteada en el parche** (`test_rover_bridge_contract.py`) fija `9a5de915f`:
- `rover_v2_bridge.py` y `rover_executor_bridge.py` no han cambiado.
- `human_authorization.py` cambió de forma compatible en `3431e129a`: `mode="OFFLINE_TEST"` conserva el comportamiento anterior y `OPERATIONAL` rechaza los *fixtures*. Al re-fijar verá el hash nuevo.

Cuando su adaptador esté en un commit:
1. El runner añadirá una operación que llame a su adaptador desde el *snapshot*, con `goal_handoff` como entrada.
2. Se comprobará que convierte una sola vez, con la referencia entregada.

Hasta entonces, `ROVER_ADAPTER` se detiene en `V2_READY_AWAITING_ROVER_ADAPTER`, y `MULTIAGENT_FRAMES2D` solo sirve para probar la admisión offline.

## Incompatibilidades pendientes del lado del subsistema rover

1. El parche de revisión (punto 1) y el adaptador de entrada v2 (punto 2) no están en ningún commit.
2. No hay un servicio que emita un recibo `AUTHENTICATED` (punto 5).
3. No hay una localización acreditada real del rover ni una transformación sitio → `odom` medida.
4. `admit_ground_trial` sigue usando una autorización de «alcance declarado». Hay que ligarla al recibo autenticado.

## Incompatibilidades corregidas en este lado

| Problema | Corrección |
| --- | --- |
| El reloj de su adaptador es el real | Los *fixtures* se sellan justo antes de cada caso |
| La conversión podía hacerse dos veces | Ahora hay un único propietario |
| El sobre no incluía la identidad de la observación | Ahora la incluye (`observation_id`, `data_kind`, sha) |
| Faltaba la comprobación de vehículo y arranque en la pose | Añadida |
| Un payload v1 presentado como v2, un campo desconocido o un *hash* de plan manipulado no estaban cubiertos | Rechazados por su validador; con pruebas |
