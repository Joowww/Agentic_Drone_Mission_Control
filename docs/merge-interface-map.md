# Mapa de interfaces para el futuro *merge* (07/11/2026)

**Ramas implicadas:**
- `feature/multiagent-opik-evaluation` (esta rama);
- `feature/rover-sitl-first-motion` (subsistema rover), comprobada en `2e206f1fa`. Sus archivos de contrato son idénticos a los de `57a0e303a` y `1514053da`.

Base común: `4d92f9813`.

## Qué toca esta rama fuera de su propio código

| Archivo | Cambio | Riesgo de conflicto |
| --- | --- | --- |
| `docs/INDEX.md` | Entradas nuevas en las secciones multiagente | **Alto**: el subsistema rover también lo modifica. Hay que fusionarlo a mano, solo añadiendo líneas |
| `observability/opik_export.py` | Campo opcional `id_shifts` en `OpikPlan` y su uso al comprobar ids (reestampado de importaciones históricas). Por defecto vacío, así que el comportamiento anterior es idéntico | Bajo: el subsistema rover no lo toca desde la base |
| `docs/*.md` y `documentation/*.md` nuevos | Solo archivos añadidos | Ninguno |
| `multiagent/`, `tests/test_multiagent_*` y las evidencias en `multiagent/benchmark/` | Solo de esta rama | Ninguno |

## Cómo se consume el código del subsistema rover

En tiempo de ejecución, esta rama **no importa** `tools.*` del subsistema rover. Lo usa de tres maneras:
1. **Contratos v1 y v2.** Se leen con `git show <commit>:…` en las pruebas (`test_multiagent_rover_contract_v1.py`, `test_multiagent_rover_v2_contract.py`).
2. **Código del executor y del adaptador.** Se ejecutan desde un *snapshot* `git archive` en un proceso aislado (`rover_handoff.py`, `rover_snapshot_runner.py`), fijado en `ROVER_CONTRACT_COMMIT` y con `contract_digest()` para detectar derivas.
3. **Reglas de transformación.** Se reimplementan en `rover_sitl_interfaces.transform_problems` y una prueba las compara caso a caso con las del subsistema rover. La validación v2 **no** se reimplementa: siempre se llama a la del subsistema rover dentro del *snapshot*.

## Interfaces entre los dos desarrollos

| De → a | Contrato | Dónde |
| --- | --- | --- |
| Rover Agent → puente | Decisión tipada → tarea terrestre → `rover-execution-request/1` | `rover_executor_bridge.py` |
| Humano → puente | `human-authorization/1`, ligado al plan; en modo `OPERATIONAL` se rechazan los *fixtures* | `human_authorization.py` |
| Puente → adaptador del subsistema rover | Vista con `{scope_sha256, human_authorized}` derivada de un registro comprobado | `rover_v2_bridge.bridge_view` |
| Puente → contrato v2 | Argumentos de `adapt_request` y el recibo autenticado (servicio pendiente) | `rover_v2_bridge.adapter_inputs` |
| Marcos | Sitio → `odom` → `base_link`, con transformación rígida acreditada | `frames2d.py` |
| Executor del subsistema rover | `ROVER_NAVIGATE_V1` con el objetivo en el marco acreditado del rover (`IDENTITY_SAME_ACCREDITED_FRAME`) | `rover_handoff._navigate_request` |
| Executor → coordinador | Estado y *feedback*; lo no reconocido pasa a `UNKNOWN` | `rover_sitl_interfaces.feedback_type` |
| SITL → coordinador | Eventos tipados; la acreditación la da el componente de ingestión | `sitl_events.py` |
| Puente → executor (envío) | Sobre `tfg.multiagent.rover-submission/1` (`READY_TO_SUBMIT_NOT_EXECUTED`): *payload* v2, objetivo original y objetivo transformado, conversión, autorización y límites. Nunca es un comando | `rover_handoff.submission_envelope` |
| Conversión sitio → rover | Un único propietario: `MULTIAGENT_FRAMES2D` (convierte aquí y lo registra) o `ROVER_ADAPTER` (aquí no se convierte) | `HandoffInputs.conversion_owner` |
| *Ledger* de autorización del subsistema rover | Solo en el *snapshot* revisado: concesión *fixture* → `DECLARED` → el v2 la rechaza | `rover_ledger_receipt_provider` |
| Entradas de misión | Lenguaje natural, `.plan` QGC (importador de Hermes) o `MissionDefinition` → `mission-input/1` → *brief* `/2` | `mission_inputs.py`; ver `tfg-unified-integration-map-2026-11-07.md` |

Hay dos *snapshots*:
- **committed:** `57a0e303a`;
- **reviewed:** `2e206f1fa` más su parche de revisión protegida, con el sha256 verificado y aplicado solo en el *snapshot*.

El subsistema rover fija en su worktree, sin commitear, los hashes de cuatro módulos de este lado en `8fed7dc39`. Desde entonces solo `frames2d.py` ha cambiado, y de forma aditiva.

## Antes de fusionar

1. Resolver con el subsistema rover los puntos pendientes de `rover-handoff-report-2026-11-07.md`:
   - promover el parche y el adaptador de entrada v2;
   - el recibo `AUTHENTICATED`.
2. Fusionar `docs/INDEX.md` a mano.
3. Pasar las dos suites, la del subsistema rover y la multiagente, sobre el resultado.
4. No mover ni regenerar ninguna evidencia sellada.
