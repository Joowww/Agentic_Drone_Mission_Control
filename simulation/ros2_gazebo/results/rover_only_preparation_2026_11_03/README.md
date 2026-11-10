# Preparación del perfil `rover_only` y de la navegación SITL: OFFLINE_TEST + revisión en seco (03/11/2026)

| Clase | Estado |
| --- | --- |
| `OFFLINE_TEST` | 1166 passed, 0 failed, 4 skipped ([`regression.stdout`](regression.stdout)) |
| Simulación ligera | **NOT_EXECUTED.** Bloqueada por diseño hasta una nueva autorización (ver abajo) |
| Comprobación previa actual | **BLOCKED** ([`precheck.stdout`](precheck.stdout)): `scope_digest_matches`, `scope_matches` y `authorization_matches` en `false`, porque cambiaron dos pines de lectura |
| Revisión en seco del sucesor | **DRY_RUN_ELIGIBLE**, `scope_sha256` = `ba52eb7ecb3a2f1b3aef89be409d340cb28320228ba267f01211fd6f9d740e98` ([`dry-run-successor.stdout`](dry-run-successor.stdout)). Sin escrituras |
| Vehículos | Sin arranque, ARM, modo ni comandos |

- **Rama:** `feature/rover-sitl-first-motion` en `12bc1b473`.
- **Agente:** Claude.

## Por qué no hubo ensayo

- **El pin cambió:** el perfil `rover_only` exige cambiar `tools/simulation_profiles.py`. Su hash está fijado en el sucesor aplicado `8815a1f4…`.
- **Consecuencia:** la comprobación previa rechaza cualquier arranque hasta aplicar un sucesor revisado.
- **El enlace propuesto:** mismo arranque, `EXACT_CONSUMER_SUCCESSOR_V1`, con `reader_revision` de solo dos archivos:
  - `historical_disposition.py`: `6d3bfbf9…` → `38d2fead…`;
  - `simulation_profiles.py`: `4d7f0eba…` → `792c2d0b…`.
- **Lo demás no cambia:** el resto del alcance (historial, prueba, identidad persistente, ejecución del contenedor, recursos y banderas) es idéntico.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
