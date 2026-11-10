# M4c: no ejecutado por precondiciones (06/11/2026, 23:46)

Manifiesto: `pilots/m4c_integrated_v1.json`, registrado en `3bdf1ff38`. Se ha usado **0 de 6** llamadas a Qwen.

**Qué precondición falló.** Una sola: `main_checkout_quiet_20min`. Codex estaba trabajando en su checkout; entre otros, cambió `tools/rover_pipe_session.py`, `tools/simulation_lifecycle.py` y las pruebas de `rover_passive_*`. Todas las demás comprobaciones salieron en verde: Ollama local con el digest registrado, GPU libre, ningún proceso de simulación ni vehículo, sin bloqueos de vehículo y worktree limpio (ver `preconditions.json`).

**Intentos de espera.** Se vigiló el checkout dos veces, durante unos 28 minutos cada vez (de 22:50 a 23:18 y de 23:18 a 23:46). En ninguna hubo 20 minutos seguidos sin cambios: el último cambio observado fue a las 23:44:15.

**Decisión.** No se ha forzado el experimento. Este directorio solo registra el bloqueo. Una ejecución posterior irá en un directorio nuevo, con el mismo manifiesto y sin cambiar los criterios.
