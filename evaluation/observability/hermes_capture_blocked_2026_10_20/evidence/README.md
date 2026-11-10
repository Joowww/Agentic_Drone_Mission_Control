# Prueba real del capturador Hermes con Ollama local — 20/10/2026

Resultado: **BLOCKED antes de la primera llamada al modelo.** No se generaron eventos.

- Perfil temporal: ~/.hermes/profiles/tfg-capture-test (creado con --no-skills --no-alias, sin clonar; sin auth.json; .env sin valores).
- Plugin: copia de observability/hermes_capture en el commit de plugin_source_commit.txt (hashes en plugin_files.sha256).
- Config del perfil: profile_config.yaml (custom/Ollama 127.0.0.1:11434, qwen3:4b, cli toolsets [], sin MCP, memoria/curator/updates off, lazy installs off).
- Introspección previa (sin modelo): pre_*.txt. Plugin "tfg-observability-capture" enabled (source user); 24 toolsets built-in + a2a disabled; sin MCP; skill esencial hermes-agent no desactivable.
- Conversación: hermes -z (un turno, --reasoning none). rc=1, ver oneshot.err: Hermes exige contexto mínimo 64,000 (MINIMUM_CONTEXT_LENGTH, sin override) y el perfil declaraba 8,192.
- capture/: vacío (ningún hook disparado; el fallo ocurre en la inicialización del agente).
- Perfil habitual y almacenes de credenciales: metadatos idénticos antes/después (habitual_profile_stat_*.txt). Sin modelo cargado en Ollama tras el intento.
- Prompt: sólo su SHA-256 (prompt.sha256); response.txt vacío.
- profile_boot_bootstrap_record.json: registro de arranque del perfil escrito por Hermes en installs/<key>/bootstrap/; todos los pasos ok/skipped, sin instalación.
