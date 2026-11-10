# Perfil de planificación con IA: build y comprobaciones con dobles (27/10/2026)

**Resultado:** imagen `tfg/planner:2026.10.27` construida y **19/19 comprobaciones con DOBLES** superadas. **No ha habido ninguna inferencia real**: ni Nous, ni Ollama, ni ningún otro modelo. Tampoco Opik, simulación, vehículos ni publicación.

## Imagen

| Dato | Valor |
| --- | --- |
| Etiqueta / ID | `tfg/planner:2026.10.27` / `sha256:651cc6e22be53ad5296a44af9659f0b6205464209f852bab9a150555161c8455`, 2 133 433 547 bytes (`image_id.txt`, `image_inspect.json`). Solo existe en local |
| Receta | `deploy/planner/Dockerfile`, con la lista generada `deploy/planner/Dockerfile.dockerignore` (conjunto `planner_image`) y el contexto con nombre `hermes_src=deploy/planner/vendor` |
| Código del proyecto | 432 archivos, idénticos al árbol (`tfg_files.sha256`). Dependencias del proyecto exactamente las de `constraints-verified.txt` (`tfg_pip-freeze.txt`, `tfg_pip-install-report.json`) |
| Hermes | `NousResearch/hermes-agent` en `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, árbol `5a064077e8d1de9fc7a4b27efc04f0caa2cb06c0` |
| Entorno de Hermes | uv 0.12.3 y CPython 3.14.7+20260901, con los sha256 de su `pm/lock.json`, y `uv sync --frozen --no-dev --extra all`: 106 paquetes, todos de PyPI (`hermes_venv_packages.txt`). Las fuentes git de `uv.lock` solo aplican a Android, y misaki y KittenTTS no entran en `all` |

## Obtención de Hermes

1. **`builds/attempt1_git_fetch_failed.log`.** `ADD` del repositorio git de GitHub. Falló tras 56 minutos (`curl 56 GnuTLS recv error … early EOF`). Se conserva.
2. **Fuente congelada.** `deploy/planner/hermes_source.py export` desde el clon local de Hermes, usando solo el almacén de objetos (sin working tree, `.git`, configuración, credenciales ni entorno virtual).
   - Comprobado antes de exportar:
     - el commit existe;
     - su árbol es `5a064077…`, el mismo que publica GitHub para ese commit (API, 27/10/2026; el commit no está firmado);
     - no hay submódulos, LFS, enlaces simbólicos ni `export-ignore`.
   - Se exportan los **blobs crudos**, porque `git archive` aplicaría `*.ps1 eol=crlf` y cambiaría bytes.
   - El tar es determinista: dos exportaciones dieron el mismo sha256 `5b668df1d429ab315e1ba857a9ffa00898b5cf066b6d9304b8698d5d300fa7c0`, con 18 605 archivos.
   - `verify` recalcula el árbol git desde el propio tar (`hermes_source_verify.txt`), y el build lo vuelve a verificar.
   - Para reproducirlo sin el HOME de Joel: `hermes_source.py fetch` (fetch superficial del commit desde GitHub, con límite de tiempo) y la misma verificación.
   - El tar está en `deploy/planner/vendor/`, fuera de Git (`.gitignore` local).
3. **`builds/attempt2_frozen_source_superseded.log`.** Build correcto en 4 minutos (`dfca01db…`), sustituido porque después cambió la salida de `status`.
4. **`builds/final.log`.** La imagen final, que solo cambia en la última capa.

`hermes_agent_files.sha256` lista los archivos del checkout en la imagen: 18 612, porque a los 18 605 del commit se suman los metadatos de la instalación editable que crea uv.

## Comprobaciones con dobles (`checks/`)

Script: `deploy/planner/planning_checks.sh`. Doble: `deploy/planner/doubles/fake_provider.py`, un proveedor falso con guion, compatible con OpenAI y con Ollama y **sin modelo**. Todo corre en la red interna `test`, sin salida.

| # | Comprobación | Resultado |
| --- | --- | --- |
| 01–02 | Hermes en la imagen; el servidor MCP arranca por stdio | PASS. El servidor publica 27 herramientas |
| 03–06 | Home del doble planning-safe; configuración manipulada rechazada; `--toolsets` ajeno rechazado | PASS |
| 07 | Toda petición del agente con herramientas ofrece **exactamente** `update_mission_draft` y `finalize_mission_draft` | PASS. La llamada auxiliar de Hermes no ofrece ninguna (`07_provider_requests.jsonl`, solo nombres de cabeceras) |
| 08–10 | El servidor MCP real guarda 1 borrador y 1 `finalization.json`; validación FEASIBLE/APPROVED; `qgc_export` **REFUSED** por falta de AMSL, sin ningún `.plan`; un contenedor nuevo lo vuelve a leer con `status` | PASS |
| 11–13 | Respuesta inválida, timeout con Ctrl+C y proveedor ausente: Hermes llega al doble, o informa de que no puede, y no hay ninguna finalización nueva | PASS. Hermes hace **hasta 3 intentos** al proveedor dentro de la invocación |
| 14 | Almacén de solo lectura: nada escrito; el error de la herramienta llega al proveedor y nadie afirma un resultado | PASS |
| 15–17 | Recorrido `ChatOllama` contra el doble: extrae `MissionPlanDraft`, rechaza la respuesta inválida (`OutputParserException`) y el menú informa de `[PLANNER ERROR]` sin proveedor | PASS |
| 18–19 | Sin patrones de credenciales en los logs; sin `auth.json`, `.env` ni claves en la imagen; home de planificación vacío | PASS |

Intentos anteriores, conservados en `checks_attempts/`:
- **1:** el home del doble lo había inicializado antes `hermes --version`, así que Hermes usó `nous` sin sesión. Sus PASS de los casos 11–13 **no eran válidos**, y por eso se endurecieron los criterios (peticiones reales al doble).
- **2:** el doble no leía `draft_id` cuando llegaba con comillas escapadas, y el criterio 07 no admitía llamadas auxiliares sin herramientas.
- **3:** fallaba el `grep` de la 09 con JSON multilínea.
- **4:** pasó 19/19, pero el texto final del doble afirmaba «draft saved» cuando la herramienta había fallado; el doble se corrigió.

`checks/` contiene la pasada final.

## Otras observaciones sin inferencia

- **`runner_preflight/preflight.json`.** Comprobación previa del ejecutor de capturas para el caso `agri-planning-container`, dentro del contenedor, sobre un home de ensayo desechable y sin red: `ok: true` en las 18 verificaciones, incluidas `tool_selection_sources_verified` (la fuente congelada coincide con las fuentes verificadas de Hermes) y `trial_server_sources_pinned`. No escribió nada.
- **`services/`.** `hermes check`/`status` con el volumen `hermes-home`: configuración de planificación creada una sola vez, PLANNING_SAFE y sin credenciales. `planner-menu` muestra el menú completo y la opción 5.
- **`pytest_affected.txt`.** `test_planning_profile.py`, `test_hermes_capture_run.py` y `test_agri_scenario_flow.py`: 182 passed.

## No observado o pendiente

- **Inferencia real:** pendiente, según `docs/planning-first-real-test.md`.
- **Ollama:** la imagen `ollama/ollama:0.34.2` (3,7 GB comprimidos) y `qwen3:4b` no se han descargado, y su arranque no se ha observado.
- **Interfaz interactiva de Hermes:** no se ha probado con una persona; solo `-z` con el doble.

## Conjunto distribuible

`distribution_inventory_planner_image.json` tiene 164 entradas: 78 con seguimiento en Git, 71 sin seguimiento y 15 modificadas respecto a HEAD. Hay que versionarlas para distribuir; no es un clon de HEAD.
