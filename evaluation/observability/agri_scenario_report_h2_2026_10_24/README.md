# Informe determinista del escenario agri_demo_001 sobre la ejecución real de H2 — 24/10/2026

`scenario_report.md` lo **genera código**, no un modelo. Se obtuvo con:

```bash
.venv/bin/python -m reporting.agri_scenario_summary report --view-file evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json
```

- **Entrada:** la vista real guardada en
  [agri_scenario_view_h2_2026_10_24](../agri_scenario_view_h2_2026_10_24/README.md), con SHA-256
  `ee088b6e4ad4b36e5542d4f8757bc31f5da93171003d83389ff1ab5ce740ca94`.
- **Código:** `render_scenario_report` en `reporting/agri_scenario_summary.py`, SHA-256
  `1550b6a17dad8cd5fac5b2187290889abdf5d53e93198c3046f7c239fb76a1df` en el momento de generarlo.
- **Sin efectos:** no hubo inferencia, simulación, consulta a Opik ni lectura de estado actual.
- **Determinista:** dos generaciones dieron bytes idénticos.

## Reglas del informe

- Cada afirmación cita entre corchetes el campo de la vista del que procede.
- Las órdenes del ejecutor se listan **por su hora registrada**. Una hora ausente se escribe
  «desconocido».
- El orden observado (las tres comprobaciones temporales, con sus horas exactas) se presenta
  **separado** de la regla documentada del coordinador. El informe no narra causas.
- La admisión del trabajo se marca como «no es evidencia de orden ni un despegue».
- La dependencia de `R1` muestra **las dos** condiciones y si constan, además del estado, las
  órdenes enviadas y la ausencia de autorización de movimiento.
- Se describe un registro histórico único: el informe no contiene frases de repetición como
  «volvieron a ejecutarse».

## Diferencias con la explicación de H3b (salida del modelo)

La explicación original sigue intacta en
[agri_scenario_h3b_nous_2026_10_24](../agri_scenario_h3b_nous_2026_10_24/README.md), con su
revisión asistida.

| Explicación de H3b | Informe determinista |
| --- | --- |
| «el despegue de drone_02 precedió al arm de drone_02» | drone_02: armado a las 12:56:14.114, despegue a las 12:56:17.245, en el orden en que se registraron |
| Cita esa supuesta comprobación como parte de la acreditación del orden | Las tres comprobaciones reales: ventanas del ejecutor, despacho tras el resultado y `land`→`arm`, con sus horas |
| «la dependencia lógica está MET (POI_A1 REACHED por drone_01)» | Dos condiciones: secuencia aérea completada **y** POI_A1 alcanzado |
| «Los drones volvieron a ejecutarse» | «Registro histórico de la secuencia `6628bc51…`», sin repetición |
| «sin validación de … superposición de vuelos» | Orden acreditado con ventanas disjuntas; vuelo simultáneo: no. Lo no validado es el **marco común** |
| «lo que provocó que el coordinador despachara drone_02» | La regla del coordinador figura como regla documentada, separada de la observación temporal |

`SHA256SUMS` cubre todo salvo este README.
