# Revisión de pines XRCE de la preparación clock-path del 31/10 (04/11/2026)

**Estado: PREPARADA PARA REVISIÓN. NO autorizada y NO aplicada.** Es una revisión nueva. La preparación histórica (`evaluation/operations/rover_clock_path_preparation_2026_10_31/54b7adc8-…`) no se ha tocado: la revisión registra sus hashes y su `SHA256SUMS`.

Sustituye al borrador de Codex `xrce-pin-review-proposal.json`, que tomaba como base `8067f8b03`. Desde entonces, `rover_ground_executor.py` ha vuelto a cambiar.

## Por qué

El selector de la sesión pasiva diagnóstica (`passive_trial.selection_dry_run`) fija los hashes de 36 fuentes. Cuatro han cambiado desde el 31/10, así que el lector histórico queda **BLOCKED** («Receiver/helper source differs»). Eso hace fallar `test_derived_closure_reader_pins_are_consumed_without_binary_changes`: el test supone que solo cambian dos pines.

| Archivo | Líneas cambiadas | Commits desde el 31/10 |
| --- | --- | --- |
| `tools/rover_ground_executor.py` | 175 | 076a56798, 15ded906f, f3af4cd5c (y el que creó la versión del repo) |
| `tools/rover_ros2_adapter.py` | 52 | 076a56798, 1ad8435fc |
| `tools/rover_xrce_trace/session_precheck.py` | 254 | e1135281c (el pin histórico era una versión sin commit; su copia está en `frozen-host-sources/`) |
| `tools/simulation_lifecycle.py` | 251 | 05c91efd3 |

Los diffs están en `<uuid>/diffs/` y van de la copia congelada del 31/10 a la versión actual.

## Qué contiene `<uuid>/` (4732a0bc-…)

- `preparation/reader.prepared.json`: el lector histórico con **solo** esos 4 `source_hashes` actualizados. El binario, las dependencias nativas, las revisiones y la procedencia se copian sin cambios; el generador lo comprueba.
- `revision.json`: el descriptor. Recoge:
  - el HEAD de preparación (`85d0bdcc9`);
  - los hashes de la predecesora;
  - cada pin cambiado, con su diff y sus commits;
  - el resultado de `selection_dry_run`.
- `host-source-review.pending.json`: **plantilla, no una revisión**. Hay que rellenar `reviewer` y `scope`.
- `diffs/`, `SHA256SUMS`.

`prepare_revision.py` reconstruye todo desde los archivos del host, sin ejecutar nada.

## Resultado de `selection_dry_run` (offline; ninguno ejecuta nada)

| Lector | `selection_files_valid` | Motivo |
| --- | --- | --- |
| Histórico | false | Receiver/helper source differs |
| Revisado (este) | **false** | Host lifecycle helper review missing/contradictory |
| Revisado + revisión de host aceptada (calculado en un directorio temporal, **no guardado**) | true | Runtime artifacts/dependencies and fresh authorization not checked (sigue BLOCKED) |

`simulation_lifecycle.py` es un helper de host. El selector exige que la revisión de helpers embebida en el lector (`helper_review.host_source_review`) nombre su hash nuevo. Escribirlo equivaldría a **afirmar una revisión que nadie ha hecho**, así que se deja pendiente.

## Pendiente

1. **ACCIÓN NECESARIA DE JOEL (con Codex, propietario de estos archivos):** revisar los 4 diffs.
2. Si se aceptan:
   - completar `host-source-review.pending.json` con revisor y alcance;
   - incorporarla al lector en un directorio nuevo;
   - volver a ejecutar `prepare_revision.py` o el `selection_dry_run`.
3. Tu autorización exacta, que nombre el digest del descriptor resultante. La escribes tú; aquí no se ha generado ninguna.
4. Hechos actuales del host, el contenedor y el lifecycle, más el precheck en el momento de usarla, por un procedimiento autorizado aparte.

**Vigencia:** solo mientras las fuentes coincidan con `revision.json`. Cualquier cambio posterior en un archivo fijado vuelve a bloquear la selección (falla cerrado). `tests/test_rover_xrce_pin_revision.py` lo comprueba en ambos sentidos.

La sucesión de la disposición diagnóstica que usa el precheck (`missions/generated/historical_dispositions/891dab60…/revisions/ba52eb7…`, 03/11) **no se ve afectada**: sus 10 pines coinciden con las fuentes actuales (comprobado el 04/11 en solo lectura).
