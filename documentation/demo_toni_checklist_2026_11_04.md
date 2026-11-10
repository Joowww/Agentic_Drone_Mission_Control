# Checklist operativo — demo para Toni, 04/11/2026

Para Joel. Cada comando está comprobado contra el código de `feature/rover-sitl-first-motion` del 03/11/2026. **Ninguno se ha ejecutado al preparar este documento**, salvo las lecturas marcadas «(leído el 03/11)».

**Regla:** un resultado de ayer no acredita el estado de hoy. Lo que vale es lo que salga mañana.

Todo se ejecuta desde la raíz del repositorio, en la terminal de VS Code (WSL):

```bash
cd ~/TFG/Agentic_Drone_Mission_Control
```

## 0. Antes de abrir VS Code (5 min)

- [ ] **Decide esta noche si quieres simulación en directo.**
  - Si **apagas el PC, reinicias Windows o haces `wsl --shutdown`**, cambia el arranque del host (`boot_id`). La comprobación previa saldrá **BLOCKED**, y recuperarla exige:
    1. `docker start` del contenedor exacto;
    2. una revisión en seco del sucesor;
    3. **tu** autorización `AUTHORIZE_DIAGNOSTIC_DISPOSITION …`;
    4. su aplicación.
  - Hoy eso llevó bastante tiempo. **No lo hagas antes de la demo.** Usa la demo de respaldo (§9 del guion).
  - Tampoco detengas ni reinicies el contenedor `tfg-ardupilot-gazebo` ni Docker Desktop: el `StartedAt` forma parte del alcance revisado.
  - Aunque no reinicies nada, **no se garantiza** que la revisión siga valiendo mañana. Compruébalo con §4.
- [ ] El portátil enchufado y sin suspensión durante la demo.
- [ ] Ollama, solo si vas a enseñar la opción 1 del menú: `curl -s localhost:11434/api/tags | head -c 200` debe listar `qwen3:4b`. Funcionaba el 03/11 (leído el 03/11).

## 1. Docker y WSL (1 min)

```bash
docker info --format '{{.ServerVersion}}' && echo DOCKER_OK
docker inspect -f '{{.State.Status}} {{.State.StartedAt}}' tfg-ardupilot-gazebo
cut -c1-8 /proc/sys/kernel/random/boot_id
docker exec tfg-ardupilot-gazebo ps -eo pid,comm
```

**Esperado**, valores del 03/11 (leído el 03/11):
- `running 2026-11-03T09:44:02.9887145Z`;
- arranque `fd538729`;
- en el contenedor, solo `bash` (PID 1).

**Si no es así:**
- **`StartedAt` o arranque distintos:** la simulación en directo queda descartada para mañana. **No** intentes recuperarla antes de la demo; usa el respaldo.
- **Contenedor `exited`:** **no** lo arranques por tu cuenta antes de la demo. Arrancarlo crea otra ejecución, que necesita revisión y autorización nuevas.
- **Procesos de simulación dentro del contenedor** (`gz`, `ardurover`, `arducopter`): hay una simulación viva que no has arrancado tú. No la pares a mano; ve a §7.

## 2. Estado de Git (30 s)

```bash
git status --short
git rev-parse --short HEAD
git log --oneline -1
git branch --show-current
```

**Esperado:**
- rama `feature/rover-sitl-first-motion`;
- árbol limpio;
- HEAD obtenido dinámicamente con `git rev-parse --short HEAD`; comprobar su descripción en la línea de `git log`, sin fijar un commit antiguo.

**Si hay cambios sin commit** que no reconoces, no los descartes: enséñalos como están o déjalos fuera.

## 3. Lifecycle, reservas y políticas (30 s, solo lectura)

```bash
.venv/bin/python -c "
from tools import vehicle_execution_lock as l, rover_ground_executor as g, rover_sitl_trial_policy as p
print('reservations', {v: l.restriction(v) for v in ('v1','v2','v3')}, 'infra', l.infrastructure_restriction(), 'sequence', l.sequence_restriction())
print('OPERATIONAL_ROVER_ENABLED', g.OPERATIONAL_ROVER_ENABLED, 'SITL_TRIAL_POLICY_ENABLED', p.SITL_TRIAL_POLICY_ENABLED)"
```

**Esperado** (leído el 03/11):

```text
reservations {'v1': None, 'v2': None, 'v3': None} infra None sequence None
OPERATIONAL_ROVER_ENABLED False SITL_TRIAL_POLICY_ENABLED False
```

**Si hay una reserva, un lease (`infra`) o una secuencia:**
- **no** la borres ni la liberes;
- **no** arranques nada;
- anota el `owner_id` y usa el respaldo.

Las reservas no se limpian a mano ni con scripts.

## 4. Comprobación previa (precheck) (30 s)

Solo lee el estado; no arranca nada:

```bash
.venv/bin/python -m tools.rover_xrce_trace.historical_disposition diagnostic-precheck | head -12
```

**Esperado para poder arrancar:** `"status": "SATISFIED"` y `"precheck_satisfied": true`. `historical_classification` seguirá diciendo `BLOCKED` / `HISTORY_INCOMPLETE_PRESENT_REVIEW`; eso es lo normal y no impide el arranque.

**Si sale BLOCKED:**
- Mira `reason` y `conditions` (la primera que esté en `false`).
- **`RELEVANT_LOCAL_ENDPOINT_OCCUPIED` justo después de una parada:** suele ser `TIME_WAIT` de TCP en el puerto 5780. Espera unos 65 s y repítelo **una vez**.
- **`fresh_observation`, `host_identity_known` o una identidad que no coincide:** el arranque del host o el contenedor han cambiado. Usa el respaldo. La recuperación es un procedimiento aparte, con tu autorización y con el subsistema rover.
- **`no_host_processes`:** hay un proceso de rol en el host. No lo mates sin saber de dónde sale.

**Lo que no hay que hacer:** «forzar» el precheck, borrar archivos de `vehicle_locks/` o aplicar una disposición durante la demo.

## 5. Arranque real (solo si §1–§4 están bien y decides hacerlo en directo)

**Un único intento.** El comando, **exactamente así**, sin `timeout`, `env`, `nohup` ni otro envoltorio (un envoltorio hace fallar `no_host_processes`):

```bash
.venv/bin/python -m tools.simulation_lifecycle start --headless --profile rover_only
```

**Esperado:** retorno 0 y lifecycle `FINISHED`. Tardó 16–25 s el 03/11.

**Alternativa con drones** (perfil `two_drones`):

```bash
.venv/bin/python -m tools.simulation_lifecycle start --headless --profile two_drones
```

- **Esperado:** retorno 0. Tardó 44 s el 03/11.
- Enseña uno de los dos perfiles, no los dos seguidos: cada parada deja ~60 s de `TIME_WAIT`.

## 6. Readiness (30–60 s)

```bash
.venv/bin/python -c 'from tools.simulation_status import check_simulation_ready; check_simulation_ready(profile="rover_only")'
```

(`profile="two_drones"` si arrancaste ese perfil.)

**Esperado:** `[PASS]` en los 5 pasos y `Simulation infrastructure checks passed; no movement authorized.`
- **`rover_only`:** el 03/11 dio `Vehicle is Armable` al primer intento.
- **`two_drones`:** los primeros intentos de pre-arm pueden dar `Not Armable` y luego `Armable`.

**Opcional, métricas** (20 s, solo lectura):

```bash
.venv/bin/python -m tools.rover_sim_metrics 0274e4fd856ab21e888a1820ea3867f2e2ec8641e0cb39c4658d8f01f9fcd30f --window-s 20
```

**Esperado:** RTF ≈ 0,6 y estado a ≈ 1,2 Hz real. Ese ID de contenedor es el del 03/11. Si §1 da otro, la simulación en directo ya estaba descartada.

**Ninguno de estos comandos** arma, cambia de modo ni mueve nada.

## 7. Parada

```bash
.venv/bin/python -m tools.simulation_lifecycle stop --profile rover_only
```

(`--profile two_drones` si es ese.)

**Esperado:** retorno 0, `remaining: []`. Después:
- espera ~65 s;
- repite §3 (reservas libres);
- repite §4 (`SATISFIED`).

## 8. Si algo devuelve BLOCKED

- **Qué significa:** el sistema **no** ha hecho nada. Es un rechazo antes de actuar.
- **Qué hacer:**
  - lee el motivo en voz alta: es una buena demostración de que los controles funcionan;
  - **no repitas** el mismo comando con cambios para «hacerlo pasar»;
  - **no** borres reservas ni edites archivos de estado.
- **En la demo:** pasa a la evidencia de respaldo equivalente (§10).

## 9. Si algo devuelve UNCONFIRMED

- **Qué significa:** **no se sabe** si el efecto ocurrió. Ejemplo: un arranque o una parada sin confirmación.
- **Qué hace el sistema:** conserva una restricción (lease o reserva) a propósito.
- **Qué no hay que hacer:**
  - **no reintentar**;
  - **no** usar `docker stop` ni `docker restart`;
  - **no** limpiar la reserva.
- **Qué hacer:**
  - anota el `owner_id` de la operación y la hora;
  - termina la demo con el respaldo;
  - después, el cierre protegido (`inspect-start-close`), con tu autorización y con el subsistema rover. Lo usaste el 03/11: `rover_only_start_close_inspection_2026_11_03` y `…_apply_2026_11_03`.

## 10. Evidencias que abrir si falla la demo

Todas son registros sellados: se abren y se leen, no se modifican.

| Qué enseñar | Carpeta (`README.md`) | Verificar el manifiesto |
| --- | --- | --- |
| Dos drones en Gazebo, arranque, readiness y parada (03/11) | `simulation/ros2_gazebo/results/two_drones_recovery_2026_11_03_attempt2/` | `(cd <carpeta> && sha256sum -c --quiet SHA256SUMS) && echo OK` |
| Secuencia SITL de dos drones con 4 POI (24/10) | `simulation/ros2_gazebo/results/agri_demo_h2_2026_10_24/` | Igual |
| `rover_only` READY y RTF 0,64 (03/11) | `simulation/ros2_gazebo/results/rover_only_dds_validation_2026_11_03/` | Igual |
| `MotionBinding ACCREDITED_FOR_SESSION` y RTF 0,61 (03/11) | `simulation/ros2_gazebo/results/rover_only_binding_final_2026_11_03/` | Igual |
| Worker PASSIVE contra ROS 2 real (03/11) | `simulation/ros2_gazebo/results/rover_pipe_worker_passive_validation_2026_11_03/` | Igual |
| Navegación de 1 m, offline (03/11) | `simulation/ros2_gazebo/results/rover_first_navigation_offline_2026_11_03/` y `…_timing_offline_2026_11_03/` | Igual |
| Hermes + MCP real (H1, 24/10) | `evaluation/observability/agri_planning_h1_nous_2026_10_24/` | Comando del paso 2 del guion |
| Hermes en contenedor (28/10) | `evaluation/observability/planning_container_real_2026_10_28_r2/` | `sha256sum -c` |
| QGC 5.1.5 abre y guarda los 2 `.plan` (30/10) | `evaluation/observability/qgc_import_hermes_two_drones_2026_10_30/` | `sha256sum -c` |

Todas dieron `OK` al comprobarse el 03/11/2026.

## 11. Al terminar

- [ ] Si arrancaste algo: §7, y después §3 y §4.
- [ ] `git status --short`: los directorios de salida de la demo van a `$OUT` (fuera del repositorio), así que no debe aparecer nada nuevo.
