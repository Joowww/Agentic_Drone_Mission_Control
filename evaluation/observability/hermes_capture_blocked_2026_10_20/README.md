# Prueba real del capturador Hermes — BLOQUEADA ANTES DE INFERENCIA (20/10/2026)

Intento único de validar la carga y captura reales del plugin
[observability/hermes_capture](../../../observability/hermes_capture/) en un perfil temporal
de Hermes (`tfg-capture-test`) con Ollama local (`qwen3:4b`). Se cierra sin repetir la conversación,
sin aumentar el contexto y sin reiniciar Ollama. Descripción completa y límites en
[docs/hermes-observability-capture.md](../../../docs/hermes-observability-capture.md).

`evidence/` contiene copias byte a byte de `/tmp/tfg-capture-20261020T155401Z/evidence/`,
verificadas contra su `manifest.sha256` original. `manifest.json` lista SHA-256 y tamaño de
cada archivo de esta carpeta, salvo él mismo.

| Hecho | Evidencia |
| --- | --- |
| Perfil creado sin clonar, sin `auth.json` ni valores en `.env`, sin preparación de dependencias | `profile_create.out`, `profile_create.err` (vacío), `profile_boot_bootstrap_record.json` |
| Config usada en la conversación | `profile_config.yaml` |
| Plugin descubierto y habilitado (`source user`) | `pre_plugins_list.txt` |
| Módulo del plugin importado por el intérprete de Hermes (CPython 3.14) durante la introspección previa, antes del turno; indicio de `register(ctx)`, no prueba de registro | `posthoc_plugin_bytecode_stat.txt` (observación posterior, fuera de `evidence/`) |
| Toolsets `cli` desactivadas, sin MCP | `pre_tools_list___platform_cli.txt`, `pre_mcp_list.txt` |
| Rechazo por contexto (mínimo 64 000) antes de cualquier llamada API | `oneshot.err`, `oneshot.rc`, `hermes_usage.json` (`failed: true`, `api_calls: null`) |
| Perfil habitual y almacenes de credenciales sin cambios (sólo metadatos `stat`) | `habitual_profile_stat_before.txt`, `habitual_profile_stat_after.txt` |
| Copia del plugin usada | `plugin_files.sha256`, `plugin_source_commit.txt` |
| Prompt sólo como hash; respuesta vacía | `prompt.sha256`, `response.txt` |

Notas sobre las copias:

- Las salidas `pre_*` se generaron con una entrada `skills.disabled: [hermes-agent]` que no
  tenía efecto (skill esencial no desactivable) y se retiró antes de la conversación;
  `profile_config.yaml` es la versión final usada en el turno.
- `pre_plugins_list.clean.txt` es idéntico byte a byte a `pre_plugins_list.txt`; se conserva
  porque forma parte del manifiesto original.
- `/tmp/tfg-capture-20261020T155401Z/capture/` estaba vacío y no se copia (git no conserva
  directorios vacíos). Es el resultado esperado de un turno rechazado antes de inferencia.
- No se incorporan `state.db`, logs ni cachés del perfil temporal.
- Revisión previa: sin credenciales, correos, tokens ni asignaciones de claves. Contiene
  rutas locales con el usuario del equipo y nombres de variables `*_API_KEY` presentes en las
  descripciones de plugins bundled de Hermes, sin valores.
