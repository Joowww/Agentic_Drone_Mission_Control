# Demo offline en un comando: guía rápida (04/11/2026)

Complementa a [demo_toni_2026_11_04.md](demo_toni_2026_11_04.md) y sirve de respaldo, porque no necesita nada externo:
- Gazebo, Docker, ROS 2;
- un LLM, red o credenciales.

Usa el código real del proyecto. Tarda unos 2 segundos.

## Comando

Desde la raíz del repositorio, en la terminal de VS Code (WSL):

```bash
cd ~/TFG/Agentic_Drone_Mission_Control
.venv/bin/python -m tools.demo_toni_offline
```

**Salida:**
- Las evidencias de la ejecución se escriben en un directorio temporal nuevo, cuya ruta aparece al final.
- Con `--out <directorio nuevo>` se elige dónde. Si el directorio ya tiene contenido, se niega (retorno 2).

**Retorno:**
- `0`: cada comprobación dio lo esperado.
- `1`: algo falló, y la línea afectada lo dice.

## Qué aparece y qué explicar

Cada línea dice `PASS`, `BLOCKED` o `FAILED`. **`BLOCKED` aquí es bueno**: es el sistema rechazando lo que debe rechazar. El resumen final debe decir `PASS 9 · BLOCKED 9 · FAILED 0` y `DEMO COMPLETA, todo según lo esperado`.

| Etapa | Qué se ve | Qué explicar |
| --- | --- | --- |
| **1. Validación de misión** | La misión de 3 waypoints sale `FEASIBLE`. La misma con 45 km/h de viento sale `NOT FEASIBLE` y pasa por `waypoint_replanner` («retrasar hasta viento ≤ 30 km/h») | LangGraph ordena etapas con rutas condicionales. Las comprobaciones (batería, viento, altitud, tramos) son funciones deterministas, no el LLM |
| **2. QGC `.plan`** | Sin altitud AMSL del home, el exportador se niega. Con AMSL declarada (584 m), 6 ítems verificados. El `.plan` se reimporta con los mismos 3 waypoints. Aparte, el `.plan` de Hermes re-guardado por QGC 5.1.5 el 30/10 sale `NO_SEMANTIC_DIFFERENCES` | Nunca se rellena un valor que falta. La comparación con QGC es una evidencia histórica, leída sin tocarla. La misión **no** se carga en ningún autopiloto |
| **3. Observación** | Cartulina roja del `drone_01`, confianza 0,9, en el marco de lanzamiento del dron, fuente `SYNTHETIC_TEST` | Es un contrato de datos. **No hay cámara**: la observación está escrita a mano |
| **4. Validación** | La del ejemplo, aceptada. Rechazadas: coordenadas en píxeles, confianza 0,5, fuente «cámara del dron» (no implementada) y sin transformación acreditada | El color solo no localiza ni autoriza nada. Las coordenadas de cámara nunca son de navegación |
| **5. Propuesta R1** | Objetivo (1,0; 0,0) en `odom` del rover, origen `SYNTHETIC`, autorización `ABSENT`. La preparación R1 existente genera el mismo candidato. Con los hechos del executor real, `NOT_ELIGIBLE` (política desactivada) | El sistema convierte la observación en una tarea validable, reutilizando la coordinación terrestre que ya existía |
| **6. Decisión** | Petición al coordinador sin autorización: `BLOCKED`, 0 admisiones. Resultado `ROVER_TASK_PENDING_AUTHORIZATION` | La IA o la observación proponen; el sistema determinista valida; **nada se mueve sin una autorización humana exacta** |
| **7. Resumen** | Recuento y lo que **no** se demuestra | Leer en voz alta la línea «No se demuestra» |

**Encadenamiento:**
- Las etapas 1 → 2 usan la misma misión.
- Las etapas 3 → 6 están encadenadas entre sí.
- **3–6 no dependen de 1–2**: el dron de la observación es el de la secuencia aérea H2 conservada, re-identificada como demo SINTÉTICA.

## Real, offline y no implementado

| Tipo | Qué |
| --- | --- |
| **Código real ejecutado aquí** | Carga y validación de `MissionDefinition`, grafo LangGraph de waypoints, exportador e importador `.plan`, comparador QGC, validación de observaciones, preparación R1 y coordinador terrestre |
| **Real, histórico (en evidencias)** | Hermes con MCP (H1 del 24/10, contenedor del 28/10); QGC 5.1.5 abriendo los `.plan` (30/10); vuelos SITL de 3 waypoints y secuencia de dos drones; `rover_only` READY con `MotionBinding` acreditado y el worker en modo pasivo (03/11). Ver la demo principal, §14 |
| **Solo offline** | Navegación del rover de 1 m, timeouts, watchdog y parada segura (con dobles); el flujo dron → rover; el executor del rover en esta demo es un `TEST_DOUBLE` |
| **No implementado** | Cámara y detección de la cartulina; transformación acreditada dron → `odom` del rover; ejecución conjunta dron-rover |
| **No ejecutado** | Ningún movimiento del rover en simulación ni real |

## Si algo falla

Si la línea dice `FAILED`, el detalle indica qué falta, por ejemplo `FileNotFoundError` y la ruta. Las etapas que no dependen de ella se ejecutan igual. En ese caso, se usan las evidencias guardadas de la demo principal (§14).

**Pruebas:** `.venv/bin/python -m pytest -q tests/test_demo_toni_offline.py` (11 passed).
