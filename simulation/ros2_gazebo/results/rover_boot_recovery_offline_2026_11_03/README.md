# Recuperación de la disposición 891dab60 tras reiniciar el host: OFFLINE_TEST (03/11/2026)

| Clase | Estado |
| --- | --- |
| `OFFLINE_TEST` | Ejecutado con fixtures aisladas en `tmp_path`, copiadas de evidencia sellada |
| `SIMULATED_REAL_EXECUTION` | **NOT_EXECUTED.** No hubo `docker start`/`stop`/`restart`, ni Gazebo, ni SITL, ni comandos |
| Disposición real | **No aplicada.** `missions/generated` queda idéntico byte a byte ([`verify_protections.stdout`](verify_protections.stdout), `generated_state_unchanged: true`) |

- **Rama:** `feature/rover-sitl-first-motion`.
- **Agente:** Claude, con autorización de Joel para cambiar código y tests.

## Cambio

**Archivo modificado:** solo `tools/rover_xrce_trace/historical_disposition.py`. Es el único pin de lectura que un sucesor puede cambiar. El pin nuevo es `6d3bfbf9…c5d4`.

**1. Protocolo nuevo `HOST_BOOT_RECOVERY_SUCCESSOR_V1`**
- **Lo que puede cambiar** (y nada más):
  - `host_boot_id`, que tiene que ser distinto;
  - `environment_execution.container_started_at` y `container_boot_id`, este último igual al boot nuevo;
  - `resource_context`, con `boot_id` igual al boot nuevo y los espacios de nombres no vacíos;
  - el pin de `historical_disposition.py`, que puede no cambiar.
- **Lo que debe quedar exacto:**
  - `persistent_identity`;
  - `historical`, `proof` y `historical_limitations`;
  - `effects` y `preserved`;
  - `host_time_namespace`;
  - el resto de pines;
  - las banderas `false`.
- **Enlace:** registra el `boot_transition` (de/a boot y de/a `StartedAt`) dentro del alcance, así que queda incluido en el hash autorizado.

**2. Cadena de sucesores**
- Ya no se admite un solo sucesor: cada uno se encadena sobre el último.
- **`query()` reconstruye la cadena** desde el original intacto y reverifica cada enlace contra los bytes de su predecesor.
- **Un fork, un huérfano, un registro parcial o un byte alterado** dan `APPLYING_UNCONFIRMED`, sin volver a un estado anterior.
- **Nada se borra:** las revisiones previas se conservan.

**3. Aplicación (`apply_successor`)**
- Se aplica solo sobre el último eslabón.
- Repetir el último hash es una consulta: no observa ni escribe.
- Un hash ya superado se rechaza (`Superseded`).

**4. Comprobación previa y revisión en seco**
- **Precheck:** consume el último sucesor, comparándolo con su predecesor exacto.
- **`dry-run-successor`:** propone el siguiente eslabón en lugar de negarse cuando ya existe un sucesor.

**El comportamiento V1 no cambia:** en el mismo arranque solo puede cambiar el pin, y el enlace tiene la misma forma.

**Test existente ajustado:** `test_different_second_successor_cannot_reuse_existing_authorization`. Afirmaba que solo podía existir un sucesor; ahora exige revalidación nueva y el hash exacto, y comprueba que no se escribe nada.

## Pruebas ([`regression.command.json`](regression.command.json))

32 archivos: disposición, consumo, precheck, recuperación, reconciliación y lifecycle. Incluyen el nuevo `tests/test_rover_boot_recovery_successor.py`.

- **Ejecución 1:** 1 failed, 1000 passed, 4 skipped. Retorno 1.
  - Falló `test_rover_failed_close_classification.py::test_explicit_proof_file_is_usable_by_existing_locked_precheck` con `KeyError: 'start_outcome'`.
  - No se reprodujo ni aislado, ni en el mismo orden con y sin el módulo nuevo, ni en la ejecución 2.
  - Su ruta (`dry_run` sin `recovery_basis`) no pasa por el código modificado.
  - **Causa no establecida.** Se trata como intermitente.
- **Ejecución 2:** **1001 passed, 0 failed, 4 skipped**. Retorno 0.

## Para el ensayo diagnóstico futuro

**Contenedor** ([`container-config.json`](container-config.json), [`ros_entrypoint.sh.copy`](ros_entrypoint.sh.copy), [`shell-startup-scan.txt`](shell-startup-scan.txt), leídos sin arrancarlo):
- **Configuración:** `Entrypoint /ros_entrypoint.sh`, `Cmd bash`, `Tty` y `OpenStdin` a `true`, `RestartPolicy no`, sin healthcheck.
- **Qué arrancaría `docker start`:** el entrypoint solo carga ROS y hace `exec bash`. Ningún archivo de arranque de shell lanza procesos.
- **Quién lanza Gazebo/SITL:** únicamente `start_sim_backend.sh`, mediante `sim_processes.py start`.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
