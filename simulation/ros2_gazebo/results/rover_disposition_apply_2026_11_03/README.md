# Aplicación del sucesor de arranque de la disposición 891dab60 (03/11/2026)

| Clase | Estado |
| --- | --- |
| Aplicación | `apply-successor-reviewed`, una sola vez, retorno 0. Registro `tfg.diagnostic-disposition/4`, protocolo `HOST_BOOT_RECOVERY_SUCCESSOR_V1` |
| Autorización | Texto exacto enviado por Joel en su propio mensaje ([`operator-authorization.txt`](operator-authorization.txt)). Es una declaración registrada, no una identidad autenticada |
| Comprobación previa | **`SATISFIED`**, `disposition_consumed: true`, `scope_changed_fields: []` |
| Simulador | **NOT_EXECUTED.** Sin Gazebo, sin SITL, sin `simulation_lifecycle` y sin vehículos |

## Antes de aplicar ([`pre-apply-state.txt`](pre-apply-state.txt), [`pre-apply-dry-run.stdout`](pre-apply-dry-run.stdout))

- **Host:** arranque `fd538729…`.
- **Contenedor:** `0274e4fd…`, `running` desde `2026-11-03T09:44:02.9887145Z`, con solo `bash` (PID 1).
- **Reservas:** ninguna.
- **Predecessor:** hashes `1b179867…` y `16e5a5ee…`.
- **Revisión en seco:** `DRY_RUN_ELIGIBLE` con el mismo `8815a1f4…`.

## Aplicación ([`apply.stdout`](apply.stdout))

- **Revalidaciones:** dos, de 1,79 s y 1,59 s.
- **Banderas de autorización:** `opening`, `movement` y `source_association` siguen en `false`.
- **Lo que se ha escrito:** solo `revisions/8815a1f4…/`. El predecesor no ha cambiado ni un byte ([`store-hashes-after.txt`](store-hashes-after.txt)).

## Después ([`diagnostic-precheck.stdout`](diagnostic-precheck.stdout), [`query-after.stdout`](query-after.stdout), [`post-apply-guards.txt`](post-apply-guards.txt))

- **Comprobación previa:** `SATISFIED`; las 8 comprobaciones de la disposición y todas las condiciones actuales en `true`.
  - El motivo indica: «separate start authorization required».
- **Cadena:** el original `92f270fe…` va seguido del sucesor `8815a1f4…`.
- **Reservas:** `v1`, `v2` y `v3` libres; sin lease ni secuencia.
- **Política:** `OPERATIONAL_ROVER_ENABLED=False`.
- **Contenedor:** sigue en marcha con la misma ejecución.

**Validez:** el resultado vale para esta ejecución del contenedor y este arranque del host. Detener el contenedor o reiniciar el host requeriría una nueva revisión y una nueva autorización.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
