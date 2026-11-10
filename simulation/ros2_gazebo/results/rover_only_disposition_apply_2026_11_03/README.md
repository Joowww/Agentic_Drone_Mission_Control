# Aplicación de la revisión de pines `ba52eb7e…` para `rover_only` (03/11/2026)

| Clase | Estado |
| --- | --- |
| Aplicación | `apply-successor-reviewed`, una sola vez, retorno 0. Mismo arranque, `EXACT_CONSUMER_SUCCESSOR_V1` con `reader_revision` de `historical_disposition.py` y `simulation_profiles.py` |
| Autorización | Texto exacto enviado por Joel en su propio mensaje ([`operator-authorization.txt`](operator-authorization.txt)). Es una declaración registrada, no una identidad autenticada |
| Comprobación previa | **SATISFIED**, `disposition_consumed: true`, sin campos cambiados ([`diagnostic-precheck.stdout`](diagnostic-precheck.stdout)) |
| Simulador y vehículos | **NOT_EXECUTED.** Sin Gazebo, SITL, lifecycle, ARM ni comandos |

## Comprobaciones previas

- **Protocolo** ([`protocol-check.json`](protocol-check.json)):
  - frente al último eslabón `8815a1f4…` solo cambia `reader_hashes`, exactamente en los dos pines revisables;
  - arranque, ejecución del contenedor y contexto de recursos son idénticos, sin `boot_transition`;
  - el enlace y el hash recalculados coinciden con los revisados.
- **Estado y revisión en seco** ([`pre-apply-state.txt`](pre-apply-state.txt), [`pre-apply-dry-run.stdout`](pre-apply-dry-run.stdout)):
  - el original y `8815a1f4…` son idénticos byte a byte a su evidencia confirmada;
  - contenedor `0274e4fd…` `running` desde `2026-11-03T09:44:02.9887145Z`;
  - arranque del host `fd538729…`;
  - sin reservas, lease, secuencia ni procesos de rol;
  - revisión en seco nueva: `DRY_RUN_ELIGIBLE` con el mismo hash.

## Después ([`query-after.stdout`](query-after.stdout), [`store-hashes-after.txt`](store-hashes-after.txt), [`post-apply-guards.txt`](post-apply-guards.txt))

- **Revalidaciones:** dos, de 1,55 s y 1,50 s.
- **Cadena:** original `92f270fe…` → `8815a1f4…` → `ba52eb7e…`. Los registros anteriores no cambian.
- **Reservas y políticas:** `v1`, `v2` y `v3` libres; `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`.
- **Contenedor:** sigue en marcha con la misma ejecución.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
