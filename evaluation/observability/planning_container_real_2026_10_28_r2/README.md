# Ejecución real de Hermes en `tfg/planner`, 28/10/2026 (segunda autorización): COMPLETADA

**Resultado:** la única ejecución autorizada de Hermes, con `nous` / `poolside/laguna-s-2.1:free`, el prompt de H1 y solo `update_mission_draft` y `finalize_mission_draft`, terminó con retorno 0 en 87,8 s, sin timeout. Generó, validó y finalizó las dos misiones. Su contenido es idéntico byte a byte al de H1. La exportación `.plan` salió REFUSED por falta de AMSL. No se relanzó. El intento fallido anterior se conserva aparte, sin cambios (`planning_container_real_2026_10_28/`).

## Condiciones

| Dato | Valor |
| --- | --- |
| Imagen | `tfg/planner:2026.10.27`, `sha256:651cc6e22be53ad5296a44af9659f0b6205464209f852bab9a150555161c8455`. Sin reconstruir y sin montar fuentes |
| Home | `HERMES_HOME=/hermes/trial` pasado al contenedor, más `--hermes-home /hermes/trial`. El proceso hijo resuelve ese mismo home (`child_home_check.txt`, comprobado sin red ni petición al modelo). Sesión de Nous del operador presente y sin caducar |
| Comprobación previa | `precheck.json`: `ok: true` en las 18 verificaciones (fuentes de Hermes verificadas, 5 pines del caso, filtro de herramientas y Tool Search desactivado) |
| Ejecución | `real-hermes-planning-container-20261028-r2`, de 07:46:49,6 a 07:48:16,8 UTC; `hermes_invocations` 1, `automatic_retry` false, `timed_out` false, `return_code` 0. Configuración restaurada y plugin retirado (`execute_result.json`) |
| Almacén nuevo | `store/` (montado como `TFG_PLANNING_STORE=work/planning_store_r2`) |
| Opik | No usado |

## Peticiones, reintentos y relanzamientos (separados)

| Concepto | Valor | Fuente |
| --- | --- | --- |
| Peticiones del ciclo de herramientas (turno principal) | **3** llamadas al modelo. La 1 pide `update` ×2 (55,2 s); la 2 pide `finalize` ×2 (10,2 s); la 3 termina con `stop` (4,3 s). Plugin y uso nativo coinciden (3 = 3) | `reviewed/capture`, `reviewed/capture_summary.json` |
| Llamada auxiliar | 1 de generación de título, solo en el uso nativo y fuera del turno principal | `capture_summary.json` (`auxiliary_native_only`) |
| Reintentos internos al proveedor | **No informados**: `retry_count` es `null` en las 3 llamadas y el resumen los declara `not_inferred`. Se detectaron 0 errores de llamada. No se afirma que hubiera cero reintentos | eventos `llm_call` |
| Relanzamientos del proceso | **0** (`hermes_invocations` 1) | `execute_result.json` |
| Tokens (normalizados por Hermes) | 42 740 de entrada y 3 113 de salida; coste estimado 0,0 (modelo `:free`) | `reviewed/native_usage_reviewed.json` |

## Herramientas

- **Ofrecidas:** en las 3 peticiones, exactamente `mcp__tfg_mission_control__update_mission_draft` y `…finalize_mission_draft` (`ONLY_TRIAL_TOOL_OFFERED`).
- **Llamadas:** `update_mission_draft` ×2 y `finalize_mission_draft` ×2, todas con estado `ok` según Hermes. Veredicto de la revisión: `PLANNING_CALLS_WITHIN_ALLOWED_TOOLS`.

## Misiones (`store/drafts/…`)

| mission_id | Borrador | Finalización | Validación | `qgc_export` | `mission.json` sha256 |
| --- | --- | --- | --- | --- | --- |
| `agri_demo_001_h1_sector_a` (drone_01) | `e31bd08d-…` | `0b6af58a-…` (`finalization.json` presente) | FEASIBLE / APPROVED | **REFUSED**: «planned home AMSL altitude is required…»; ningún `.plan` | `321ad647ab9c2af536905d541675580df20e0e7a5e9be129841c8f894166b30d` |
| `agri_demo_001_h1_sector_b` (drone_02) | `c244d68c-…` | `dd6055ee-…` (`finalization.json` presente) | FEASIBLE / APPROVED | **REFUSED** (mismo motivo); ningún `.plan` | `079e25a302423996f168b65c8b2e03157fda0c9ad9b743fb64e8ea7b8c955472` |

**Datos del operador.** Cada borrador coincide campo a campo con el prompt: datos comunes, nombre, vehículo, objetivo, `geometry_intent` y offsets en orden. No hay campos no nulos que el prompt no aportara; las rutas y el home las deriva el código.

**Comparación con H1.** Los dos `mission.json` tienen el mismo contenido que los de H1 en el almacén local de Joel, y sus sha256 son los que fija `agri_planning_h1_nous_2026_10_24/h1_binding.json` (`321ad647…` y `079e25a3…`).

## Respuesta final de Hermes (`private/stdout.txt`)

Un objeto JSON con, para cada misión, `finalization_id`, `status` y `validation.execution_status`, como pide el prompt.
- Los dos `finalization_id` coinciden con los registrados.
- `execution_status: APPROVED` coincide.
- `status: VALIDATED` es el valor que devuelve `finalize_mission_draft` (`tools/hermes_mission_planning.py`). `finalization.json` no guarda ese campo.

La respuesta no menciona la exportación REFUSED, pero el prompt no lo pedía. No afirma nada que no esté registrado.

## Persistencia

`status_new_container.txt` es la lectura desde otro contenedor, sin red: 2 borradores y 2 finalizaciones completas con validación y REFUSED. El «config.yaml absent» de esa salida se debe a que el servicio de prueba usado no monta el volumen `hermes-home`; no afecta al almacén.

## Qué se acredita y qué no

- **Acreditado:** ejecución del proceso (retorno 0), herramientas (solo las 2 permitidas, sin errores), validación de las misiones (FEASIBLE/APPROVED y exportación estricta REFUSED) y una respuesta final coherente con los registros.
- **No acreditado:** planificación autónoma (el prompt aporta todos los datos, como en H1), vuelo, simulación, carga en un vehículo, otros modelos ni otras entradas. Una sola ejecución no es una tasa de éxito.
