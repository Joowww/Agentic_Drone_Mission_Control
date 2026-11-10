# Primera navegación SITL del rover: preparación OFFLINE (03/11/2026)

| Clase | Estado |
| --- | --- |
| `OFFLINE_TEST` | **28 passed, 1 xfailed** ([`offline-tests.stdout`](offline-tests.stdout)). El xfail reproduce a propósito la carrera conocida de `NativeRos2Session._exchange` |
| `SIMULATED_REAL_EXECUTION` | **NOT_EXECUTED.** Sin simulador, worker real, ARM ni movimiento |
| Políticas | `OPERATIONAL_ROVER_ENABLED=False`; `SITL_TRIAL_POLICY_ENABLED=False` ([`defaults.json`](defaults.json)) |
| Alcance SITL definitivo | **No calculado.** Exige una sesión viva nueva ([`docs/rover-first-navigation-sitl.md`](../../../../docs/rover-first-navigation-sitl.md) §6) |

**Ejemplo** ([`example-trial-synthetic.json`](example-trial-synthetic.json)): construido con el binding sintético de los tests. No es una sesión viva ni una autorización.

- **Agente:** Claude, con autorización de Joel para ejemplos, tests, documentación y evidencia offline.

[`SHA256SUMS`](SHA256SUMS) cubre todo salvo este README.
