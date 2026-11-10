# Revisión offline de tiempos de la primera navegación de 1 m y comprobación de los comandos de la demo (03/11/2026)

**Tipo: OFFLINE_ONLY.**
- Sin simulador, sin Docker operativo, sin armar ni mover nada y sin cambios de políticas ni de reservas.
- Solo se leyó el estado del contenedor con `docker inspect` (`state.txt`).
- **Agente:** Claude.
- **Base de código:** [`code-base-commit.txt`](code-base-commit.txt) (`549ae37e1`), más los cambios de `tests/test_rover_first_navigation.py` y `tests/test_rover_first_navigation_timing.py`, que van en el commit de pruebas anterior a esta evidencia. Los hashes de los archivos ejecutados están en [`source-files.sha256`](source-files.sha256).

## Resultados

| Qué | Resultado | Archivo |
| --- | --- | --- |
| Navegación de 1 m + tiempos | **35 passed, 3 xfailed** (retorno 0) | [`timing-tests.stdout`](timing-tests.stdout) |
| Los 2 `xfail` nuevos ejecutados con `--runxfail` | Fallan por el motivo previsto: `1.0 < 1.0` (el worker recibe el mismo plazo que el host) y `host_alarms == 1` (sesión rota, sin HOLD) | [`xfail-current-failures.stdout`](xfail-current-failures.stdout) |
| Regresión `tests/test_rover_*.py` | 1859 passed, 4 skipped, 3 xfailed, **6 failed** (los conocidos: `test_rover_clock_path_preparation`, por los pines sellados, y 5 de `test_rover_passive_odometry_fields`, que dependen de diarios del disco ignorados por Git). Sin fallos nuevos | [`rover-regression.stdout`](rover-regression.stdout) |
| Comandos de `documentation/demo_toni_2026_11_04.md` | Los 10 bloques, en orden, con retorno 0 | [`demo-commands.sh`](demo-commands.sh), [`demo-commands.stdout`](demo-commands.stdout) |
| Estado al terminar | Reservas `v1`, `v2` y `v3` libres; sin lease ni secuencia; `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False`; contenedor `running` con `StartedAt` `2026-11-03T09:44:02.9887145Z`; arranque del host `fd538729…` | [`state.txt`](state.txt) |

## Hallazgos (detalle en `docs/rover-first-navigation-sitl.md` §5.4)

1. **60 s no es un límite global.** Para `ROVER_NAVIGATE_V1`, `max_duration_s` solo acota la navegación (45 s). El peor caso es **87 s** de reloj real, el mismo que ya usa la comprobación de batería.
2. **La parada y el desarmado tienen reserva propia.** Empiezan plazos nuevos (8 s y 10 s) después de la navegación.
3. **El ritmo efectivo es ≤ 1,2 Hz**, no los 2 Hz declarados: cada orden espera un estado nuevo.
4. **El límite de antigüedad de 1,0 s** exige un estado al menos cada segundo, es decir, RTF ≳ 0,5. A 0,9 Hz la preparación falla por caducidad antes de armar (fail-closed).
5. **El margen host/worker (defecto).** Un hueco de estado mayor que el plazo de una llamada rompe la sesión por la alarma del host, y el host ya no envía cero ni HOLD: el doble queda armado en GUIDED. Con el worker a ×0,7 (aplicado solo en la prueba) se observan HOLD y el desarmado.
6. **Límites del worker no declarados por el ensayo** (`watchdog_s`, `max_linear_mps`, `max_angular_rad_s`).

## Modelos y límites

- **Cadencia:** la medida en vivo en `rover_only_binding_final_2026_11_03`, con estado a ≈ 1,2 Hz real, odometría a 50 Hz simulados y RTF ≈ 0,6.
- **Alarma del host:** `TimeoutError` dentro de la lectura del pipe cuando la respuesta llegaría después del plazo. La latencia de 50 ms del pipe es una **suposición**, no una medida.
- **No modelados:**
  - la parada propia del worker por EOF o watchdog;
  - el timeout de GUIDED de ArduRover.
- **Alcance:** las pruebas acreditan aritmética y lógica del host con un doble. **No** el comportamiento de ArduRover SITL.

**Tarea para Codex:** [`documentation/codex_review_rover_2026_11_04.md`](../../../../documentation/codex_review_rover_2026_11_04.md).

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
