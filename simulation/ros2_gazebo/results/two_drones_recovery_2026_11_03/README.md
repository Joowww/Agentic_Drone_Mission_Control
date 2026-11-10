# Arranque `two_drones` tras la recuperación: BLOCKED antes del backend (03/11/2026)

| Clase | Estado |
| --- | --- |
| Arranque | **BLOCKED** por la comprobación previa interna del lifecycle, antes de crear el lease, la operación o el backend. Retorno 1 ([`start.stdout`](start.stdout)) |
| Gazebo / SITL / ROS 2 | **NOT_EXECUTED.** No se lanzó ningún proceso de simulación |
| Parada | No procede: no hay lease, operación ni procesos que parar. No se usó `docker stop` |
| Estado | Sin cambios: ningún archivo de `missions/generated` modificado. El contenedor sigue `running` desde `2026-11-03T09:44:02.9887145Z` con solo `bash` ([`state-after-blocked-start.txt`](state-after-blocked-start.txt)) |

**Mensaje del bloqueo:** `Historical diagnostic precheck blocked: Present review failed: fresh_observation, no_host_processes`.

## Causas

- **`no_host_processes`: error de invocación del agente.**
  - La comprobación busca en el host procesos con el argumento `tools.simulation_lifecycle` y excluye solo su propio PID.
  - El comando se ejecutó como `timeout 420 .venv/bin/python -m tools.simulation_lifecycle …`, no exactamente como estaba autorizado.
  - El proceso padre `timeout` llevaba ese argumento y se detectó, correctamente, como otro lifecycle.
  - **Corrección:** invocar el comando autorizado tal cual, sin envoltorio.
- **`fresh_observation`: la ventana superó 3 s en ese intento. Causa no establecida.**
  - Medida aislada de solo lectura justo después ([`precheck-timing.json`](precheck-timing.json)): `SATISFIED`, ventana de 1,79 s.
  - Puede repetirse de forma intermitente.

## Comprobaciones previas ([`initial-state.txt`](initial-state.txt), [`precheck-before-start.stdout`](precheck-before-start.stdout))

- **Rama:** `feature/rover-sitl-first-motion` en `7047b77a1`, solo con carpetas de evidencia sin seguimiento.
- **Host y contenedor:** arranque `fd538729…`; contenedor `0274e4fd…` `running` con solo `bash`.
- **Reservas y operaciones:** sin reservas, lease ni secuencia, y sin procesos de rol en el host.
- **Bloqueo de control:** libre.
- **Comprobación previa:** `SATISFIED`, con la disposición consumida.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
