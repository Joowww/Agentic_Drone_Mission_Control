# R1: corrección del progreso tras perturbación y primera captura /3 real — 26/10/2026

Evidencia derivada nueva. La del 25/10
([`agri_r1_joint_closure_2026_10_25`](../agri_r1_joint_closure_2026_10_25/README.md)) no cambia.

## 1. Defecto antiguo y su corrección: dos cosas distintas

**Reproducción del defecto antiguo (registro histórico, 25/10).** En la versión de `GoalController`
de ese día, tras una llegada, la recuperación de un rover desplazado solo contaba como progreso si
mejoraba en `progress_m` la mejor distancia histórica. Con `progress_m = 0,5 m`, una recuperación
lenta terminaba en `NO_PROGRESS`. La reproducción
(`test_codex_goal_controller_no_progress_after_disturbance`) queda descrita en la evidencia del
25/10. Contra el código corregido falla con `DID NOT RAISE`, como era de esperar, y **se ha
sustituido**: ya no reproduce el comportamiento antiguo.

**Comprobación de la corrección (26/10).** La nueva `GoalController` de Codex funciona así:
- usa `min(progress_m, tolerance_m)` como histéresis en la recuperación tras una llegada;
- reinicia la referencia sin conceder crédito por el desplazamiento ni por la reentrada;
- solo cuenta marcas nuevas dentro de cada episodio;
- los cambios de fase nunca amplían el plazo global.

Las regresiones de `tests/test_agri_ground_joint.py` usan la meta **exactamente como la construye el
coordinador** desde el candidato autorizado (tolerancia 0,05 m, `progress_m` 0,5 m, `no_progress`
10 s, permanencia 5 s, timeout 120 s):

| Prueba | Qué verifica |
| --- | --- |
| `test_corrected_controller_recovers_after_disturbance_with_the_authorized_r1_parameters` | La perturbación interrumpe la permanencia (fase `RECOVERY`, sin `reached`); la distancia vuelve a disminuir sin `NO_PROGRESS`; recupera el radio y **cumple una permanencia nueva completa** (4,9 s tras la reentrada no bastan, 5,0 s sí); `started` no cambia |
| `test_phase_changes_never_extend_the_global_timeout` | Ciclos reales de desplazamiento y recuperación terminan en `GOAL_TIMEOUT`; el inicio global no se mueve |
| `test_immobile_after_disturbance_still_ends_in_no_progress` | Negativa: rover desplazado e inmóvil → `NO_PROGRESS` |
| `test_repeated_disturbances_without_net_recovery_end_in_no_progress` | Negativa: perturbaciones repetidas sin recuperación neta → `NO_PROGRESS` |
| `test_slow_recovery_crosses_coordinator_executor_and_acceptance` | Recorrido conjunto real (coordinador → arranque → worker → cierre autorizado → aceptación) con recuperación lenta a 0,02 m/s durante más de 10 s: `GOAL_REACHED` en el ejecutor y `VERIFIED_SYNTHETIC` en la aceptación, con la permanencia nueva medida en reloj de simulación |

Las pruebas unitarias del controlador de Codex (`tests/test_rover_goal_progress.py`: oscilación,
parpadeo en el borde, inmovilidad, aproximación) no se duplican; se ejecutan junto a las mías.
Resultado en los suites afectados por este cambio y por los de las secciones 2 y 3: 441 pasan.
Son el escenario, el coordinador, el recorrido conjunto, el lector pasivo y los de Codex
(`test_rover_goal_progress.py`, `test_rover_navigation.py`, `test_rover_ground_executor.py` y
`test_rover_control.py`). El estado de la suite completa está en la sección 7.

**Recorrido regenerado con el controlador corregido** (`synthetic_runs/`, sintético):

| Variante | Trabajo | R1 |
| --- | --- | --- |
| `finalized` | `FINISHED` | `VERIFIED_SYNTHETIC` |
| `slow_recovery` | `FINISHED` | `VERIFIED_SYNTHETIC`; fases `DWELL` (39) → `RECOVERY` (126) → `DWELL` (51) en `controller_decisions.json` |
| `armed_hold` | `UNCONFIRMED` | `CLOSURE_PENDING` |
| `stop_uncertain` | `UNCONFIRMED` | `CLOSURE_PENDING`, parada no confirmada |
| `goal_failed` | `FINISHED` | `FAILED` (`NO_PROGRESS`) |

## 2. Recepción /3 real sin movimiento (Codex, cerrada)

**Origen:** `simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-…`.
- Una apertura headless protegida, un colector `/3` (20/120/reserva/`--odometry-fields`) y un
  cierre protegido.
- Ningún servicio de control ni movimiento.
- Archivos de Codex leídos y no modificados.

**Verificación con el mecanismo existente** (`analyze_capture`):
- **Manifiesto:** `a88a09f9…bdf8a5`, 119 archivos, tamaño y SHA-256 de cada uno.
- **Diario:** `13811afd…3f18`. `analysis-input-journal-copy.jsonl` es idéntico byte a byte al
  `journal.jsonl` de la captura.
- **Recibo, retorno (`return_code.json`) y `stderr.txt`:** listados en el manifiesto y comprobados.

**Completitud: tres evidencias distintas, ninguna suficiente por sí sola:**

| Evidencia | Valor | Significado |
| --- | --- | --- |
| Footer del colector `capture_complete` | `null` | El colector nunca se autocertifica; el lector exige `null` |
| Recibo externo de la misma invocación `capture_complete` | `true` | Confirmación externa de la captura |
| Retorno y streams | rc `0` (`timeout_uncertain: false`), datos en ambos streams, `SAMPLE_LIMIT`, stderr de 0 bytes | Finalización del proceso y presencia de datos |

El lector acepta esta combinación por sus evidencias, no por una excepción para esta captura.
`test_completion_needs_every_separate_evidence_not_a_capture_specific_exception` lo comprueba. Parte
de una captura sintética aceptada, cambia una sola evidencia cada vez y vuelve a listar el
manifiesto. Cualquiera de estos cambios produce `REFUSED`:
- el footer se autocertifica;
- el recibo dice `false` o no tiene la bandera;
- el rc no es cero;
- falta uno de los streams;
- `stderr` no está listado.

**Informe reproducible:** [`real_capture_4ac58516_report.md`](real_capture_4ac58516_report.md), y
en JSON [`real_capture_4ac58516_analysis.json`](real_capture_4ac58516_analysis.json). Resumen de
observaciones:
- **Muestras retenidas por topic:** `/rover1/odometry` 19 y `/ap/v3/status` 1. La odometría viene de
  un solo GID (`rmw_fastrtps_cpp`), marcos `odom` → `base_link`; ninguna incompleta ni con no
  finitos.
- **Posición en `odom`:**

  | Eje | Rango | Desviación típica |
  | --- | --- | --- |
  | x | −0,0012414 a −0,0012346 m | 2,1 µm |
  | y | −3,0004240 a −3,0004044 m | 6,1 µm |
  | z | 0,094915 a 0,094928 m | 4,2 µm |
- **Orientación** (conversión del cuaternión recibido): roll ≈ 0,00001°, cabeceo 0,5454–0,5462°, yaw
  89,769–89,770°. Los máximos de `|q.x|` y `|q.y|` son ≈ 0,0034.
- **Velocidades:** norma lineal máxima de 0,000156 m/s; angular 0.
- **Covarianzas:** 38 matrices declaradas, todas cero.
- **Duración:** los sellos de cabecera, cada 20 ms, cubren **0,36 s**. La recepción (reloj
  monotónico) cubre 18,64 s, con una mediana de 107 ms y un máximo de 4,5 s entre muestras
  retenidas.
- **Selección:** suscripción best-effort KeepLast(5) sin contar descartes, un callback por ciclo,
  límite de 20 muestras con reserva por stream. Los huecos entre muestras retenidas no son pérdida
  del flujo.

**Lo que estas cifras no son:**
- Cero en la covarianza declarada no es precisión perfecta.
- Las velocidades pequeñas salen de la misma odometría: no son una prueba independiente de reposo
  físico.
- De los dos relojes no se deriva un factor de tiempo real, y su diferencia no se atribuye a cola ni
  a lentitud.
- No acreditan la identidad del publicador, el modelo, el SYSID ni la transformación de marcos.
- Que la posición (≈ (0, −3)) y el yaw (≈ 90°) coincidan con el spawn declarado es una coincidencia
  numérica, no una verificación de que `odom` sea el marco del mundo.

## 3. Preparación de R1: hechos medidos, separados de los parámetros propuestos

`prepare_ground_task(..., capture=...)` acepta ahora el resultado etiquetado de `analyze_capture`.
Sus observaciones van a una sección propia, `measured_facts`. **No entran** en el candidato (su hash
no cambia), en `proposed_parameters` (= `R1_VISIT_PROPOSAL`, `PROPOSED_NOT_APPROVED`) ni en los
bloqueos, y no hay gates nuevos. Una captura rechazada o anterior a `/3` da `NOT_AVAILABLE`.

**Dry-run real** (vista H2 histórica, hechos actuales del ejecutor y esta captura), en
[`r1_dry_run_with_measured_facts.json`](r1_dry_run_with_measured_facts.json) y
[`r1_preparation_report.md`](r1_preparation_report.md):
- **Estado:** dependencia `MET`, `NOT_ELIGIBLE`, sin candidato, `BLOCKED_PENDING`.
- **Bloqueos:** `required_data_present` y `operational_rover_policy_enabled`, los mismos que sin la
  captura.
- **Con datos observados** (todos `accredited: false`):
  - `ground_tolerance_m` y `arrival_tolerance_m`: dispersión en reposo;
  - `stopped_linear_mps` y `stopped_angular_rad_s`: velocidades residuales;
  - `max_sample_gap_s`: solo intervalos de muestras retenidas;
  - `completion_evidence`: fuente de odometría observada, sin identidad acreditada;
  - `frame_transform`: solo nombres de marco;
  - `execution_limits`: velocidad residual e inclinación en reposo.
- **Sin datos en esta captura:** `target_in_rover_frame`, `rover_mission`, `dwell_s`,
  `min_dwell_samples`, `max_decision_age_s`, `global_timeout_s`, `no_progress_window_s` y
  `min_progress_m`.

**Qué no aporta.**
- No acredita por sí sola la transformación.
- No valida llegada, progreso ni permanencia: no hubo movimiento ni objetivo, y el tiempo simulado
  observado es solo de 0,36 s.
- No basta para aprobar umbrales.

## 4. Informe conjunto: tres evidencias que no se combinan

| Evidencia | Origen | Sesión | Qué demuestra | Qué no |
| --- | --- | --- | --- | --- |
| **Ejecución aérea histórica (H2)** | Real ([vista](../agri_scenario_view_h2_2026_10_24/README.md)) | Secuencia H2, 24/10 | A1 y A2 `COMPLETED/PASSED`; dependencia de R1 `MET` | Nada terrestre; el escenario H2 nunca está completo |
| **Navegación terrestre** | **Sintética** (`synthetic_runs/`, sesión física sustituida) | Sesiones de prueba de pytest | Contrato coordinador ↔ ejecutor, cierre, recuperación tras perturbación → `VERIFIED_SYNTHETIC` | Ningún rover se ha movido |
| **Recepción terrestre /3** | Real, sin movimiento (sección 2) | Apertura headless 4ac58516 | Observaciones en reposo de una fuente de odometría | Llegada, permanencia, transformación, identidad y umbrales |

Las tres sesiones son distintas. Ningún informe las une como una ejecución real completa. En
[`r1_preparation_report.md`](r1_preparation_report.md) la vista real y la captura real aparecen
juntas solo como **preparación**: R1 sigue en `NOT_REQUESTED` y el escenario
`AERIAL_COMPLETED_GROUND_NOT_REQUESTED`, completo: **no**.

## 5. Matriz de preparación del primer R1 en SITL

> **Superada (27/10/2026).** La matriz vigente, con los hechos de la sesión de identidad `1cb9d86a` y la separación entre pulso local y POI_A1, está en [la revisión del 27/10](../agri_r1_identity_review_2026_10_27/README.md). Esta se conserva como registro.

| Requisito | Evidencia concreta | Estado |
| --- | --- | --- |
| Dependencia aérea | Vista H2 real: `MET` | Satisfecho (histórico) |
| `target_in_rover_frame` | Ninguna | Pendiente (depende de la transformación) |
| `frame_transform` | Nombres `odom` → `base_link`; posición cercana al spawn declarado (coincidencia) | **No acreditado** |
| `ground_tolerance_m` / `arrival_tolerance_m` | Dispersión de µm en reposo (19 muestras reales); propuesta de 2,0 m | Contraste disponible; **no aprobado** |
| Umbrales de parada | Velocidad residual de 0,000156 m/s (misma fuente) | Contraste disponible; **no aprobado** |
| `max_sample_gap_s` | Intervalo máximo de 4,5 s entre muestras retenidas (selección) | Sin datos del flujo completo |
| Llegada, progreso, permanencia y timeout | Solo sintéticos (secciones 1 y 4) | Sin datos reales |
| `completion_evidence` | Una fuente de odometría observada | Identidad no acreditada |
| `rover_mission` | Ninguna | Pendiente |
| Supuesto plano del controlador | Cabeceo de 0,55° en reposo (abs(q.y) ≈ 0,0034, por encima del 1e-3 del controlador) | Revisión de Codex |
| Contrato del ejecutor (arranque, cierre, finalización) | Recorrido conjunto real con física sustituida | Probado de forma sintética; falta la interfaz física real |
| Política operativa del rover | Dry-run real: `NOT_SATISFIED` | Bloqueado |
| Autorización | Ausente | Joel y el tutor |

## 6. Datos pendientes que debe obtener Codex

> **Punto 1 resuelto en código (27/10/2026).** Codex sustituyó el umbral 1e-3 por `projected_ground_heading` (`tools/rover_control.py` `da652736…`; la versión de este documento era `86db5da7…`). La muestra real ya no se rechaza; siguen sin acreditar el marco y cualquier límite de pendiente. Detalle en [la revisión del 27/10](../agri_r1_identity_review_2026_10_27/README.md#fuentes-utilizadas). La lista se conserva como registro.

1. Una decisión sobre el supuesto plano del controlador frente a la inclinación observada en reposo,
   con su justificación. No se relaja ninguna tolerancia por iniciativa propia.
2. La evidencia de la transformación de marcos (la comprobación de tres vehículos), que dé
   `frame_transform` `VERIFIED` y `pose_reference_sha256`.
3. La cadena de identidad del publicador de odometría (GID → modelo → SYSID) y el transporte real con
   `probe().session_id`.
4. La interfaz física real de `start_ground_trial`, dentro de su procedimiento protegido.
5. Para contrastar los umbrales en movimiento y en el objetivo, un ensayo con movimiento. Solo si se
   autoriza y con su procedimiento.
6. Si se necesitan la frecuencia o la pérdida del flujo completo, una medición no selectiva. Si no,
   se mantiene el límite declarado.

## 7. Reproducción

```bash
R=simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/4ac58516-8fad-457e-918e-253483a2d728
C=container-copies/tmp/tfg_rover_xrce_capture/4ac58516-8fad-457e-918e-253483a2d728
.venv/bin/python -m tools.rover_passive_journal --trial-root $R --capture-dir $C --markdown
.venv/bin/python -m reporting.agri_scenario_summary r1-dry-run --capture-trial-root $R --capture-dir $C
.venv/bin/python -m reporting.agri_scenario_summary report --view-file evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json --capture-trial-root $R --capture-dir $C
.venv/bin/python -m pytest -q tests/test_agri_scenario.py tests/test_agri_ground_coordinator.py tests/test_agri_ground_joint.py tests/test_rover_passive_odometry_fields.py tests/test_rover_passive_journal.py tests/test_rover_goal_progress.py tests/test_rover_navigation.py tests/test_rover_ground_executor.py tests/test_rover_control.py
```

**Suite completa (`pytest tests/`, 26/10):** 2118 pasan y ninguna falla, con 1 aviso. No hay incompatibilidades pendientes en el estado actual del árbol de trabajo, que incluye cambios de Codex sin commit.
