# Arranque diagnóstico del contenedor y revisión en seco del sucesor (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | `docker start` del contenedor exacto `0274e4fd…fcd30f`, autorizado por Joel. Solo el shell inactivo |
| Revisión en seco | **`DRY_RUN_ELIGIBLE`**, `scope_sha256` = `8815a1f4ba2440f97cd31b2087a123568f1d06974b90bf4ab179fc7784261d1b` |
| Aplicación | **NOT_EXECUTED.** No se ejecutó `apply-successor-reviewed` ni se generó ninguna declaración de autorización |
| Simulador | **NOT_EXECUTED.** Sin Gazebo, sin SITL, sin `simulation_lifecycle` y sin comandos |

- **Rama:** `feature/rover-sitl-first-motion`, en `7047b77a1`, desde el checkout principal con el almacén de reservas real.
- **Agente:** Claude.

## Secuencia

1. **Identidad y configuración antes de arrancar** ([`inspect-before-start.json`](inspect-before-start.json)):
   - todo coincide;
   - el entrypoint tiene el mismo hash (`32c3f279…`) que la copia del 03/11.
2. **`docker start`:** retorno 0 ([`docker-start.*`](docker-start.command.json)). `StartedAt` = `2026-11-03T09:44:02.9887145Z`.
3. **Procesos** ([`processes-after-start.json`](processes-after-start.json)):
   - **justo después:** el entrypoint cargando ROS;
   - **una vez asentado** ([`processes-settled.json`](processes-settled.json)): solo `bash` como PID 1;
   - ningún puerto TCP en escucha ni UDP ligado.
4. **`dry-run-successor --owner 891dab60-…`:**
   - retorno 0, ventana del host de 1,94 s;
   - las 16 condiciones en `true`;
   - recursos `FREE` (26 lecturas, `occupied: []`);
   - inventario sin procesos propios, ambiguos ni agentes;
   - sin restricciones, guardas, otras sesiones ni procesos de rol en el host.
5. **Después de la revisión:**
   - el contenedor sigue con solo `bash` ([`processes-after-dry-run.json`](processes-after-dry-run.json));
   - ningún archivo de `missions/generated` ha cambiado;
   - el almacén `891dab60` sigue sin `revisions/`.

## El contenedor queda ARRANCADO

El alcance revisado incluye el `StartedAt` de esta ejecución. Detener el contenedor lo invalidaría, porque un arranque posterior produciría otro alcance. Por eso, y porque la revisión no quedó `BLOCKED`, el contenedor se deja en marcha con solo el shell inactivo, hasta que Joel decida.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
