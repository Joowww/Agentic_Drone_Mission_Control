# Entrega parcial `tfg-entrega-estudiantes-2026.10.28-r2`: solo Hermes (28/10/2026)

**Resultado:** nueva versión de la entrega **parcial**: app, QGC y Hermes, **todavía sin simulador**. Para los estudiantes, la IA es solo Hermes.

- **Verificación:** de los elementos afectados, en este mismo equipo y desde un directorio aislado: 10/10 PASS.
- **Entrega anterior:** se conserva intacta, con su evidencia (`student_bundle_2026_10_28`).
- **Operaciones no realizadas:** inferencias, login, Opik, simulación, vehículos, apertura de QGC y cambios en archivos de Codex.

Ruta: `/home/joelm/TFG/entregas/tfg-entrega-estudiantes-2026.10.28-r2/` (851 MB, 16 archivos más su `SHA256SUMS`).

## ¿Hacía falta cambiar alguna imagen?

| Imagen | Presentación al usuario | Decisión |
| --- | --- | --- |
| `app` | El menú offline mostraba «needs a local LLM (Ollama)» en las opciones 1 y 3, y decía «It is not a distribution of the AI planning» | **Sí:** se modificó solo esa presentación y se construyó la etiqueta nueva `tfg/app:2026.10.28` |
| `planner` | Su `main.py` conserva el menú de desarrollo (perfil `planning`). Solo lo abría el servicio `planner-menu`, que ya no está en el Compose distribuido. `hermes` arranca `hermes_home.py`, que no menciona Ollama | **No:** se reutiliza `tfg/planner:2026.10.28` y su exportación |
| `qgc` | Sin relación | **No:** se reutiliza |

## Imagen `tfg/app:2026.10.28` (`app_build/`)

- **ID:** `sha256:7ae59021978f3656f63cb7366819f7b8ac19aff0a5a0f38615f919f69ec0d988`.
- **Contexto congelado** (`frozen_at_utc.txt`): el `/opt/tfg` de `tfg/app:2026.10.27-r2`, 401 archivos extraídos con `docker create`/`docker cp` sin arrancar la imagen e iguales a su `files.sha256`. Solo se sustituyó `main.py`.
  - Diferencia con r2: exactamente `main.py` (`diff_vs_r2.txt`, `main_py_diff_vs_r2.txt`).
  - El árbol tiene otros dos cambios posteriores a r2, ambos de Claude (`hermes_capture_run.py` y `agri_scenario_distribution.py`), que **no** se incorporan.
- **Cambio de `main.py`:** solo los textos del perfil `TFG_PROFILE=offline`.
  - Las opciones 1 y 3 se marcan como fuera de la entrega para estudiantes, y la IA es el servicio Hermes.
  - La cabecera indica que el simulador aún no se distribuye.
  - El menú de desarrollo y el código antiguo no cambian.
- **Build:** `docker build -f app_build/Dockerfile <contexto congelado>` (`build.log`). Etapas base y deps en caché, sin descargas.
- **Contenido verificado:** `files.sha256` de la imagen = `frozen_context.sha256`; `pip freeze` idéntico al de r2.
- **Repositorio:** la etiqueta de `deploy/app/Dockerfile` y la imagen de `app` en `deploy/compose.yaml` pasan a `2026.10.28`. Un build desde el árbol actual incorporaría también los dos cambios citados; la imagen sellada es la de este contexto.
- **Prueba afectada:** `test_main_menu_marks_llm_and_store_options_unavailable_only_in_the_offline_profile`, 2 passed (`pytest_affected.txt`). Ahora comprueba además que el menú offline no menciona Ollama.
- **`tfg/app:2026.10.27-r2`** se conserva (`a86dae08…`).

## Cambios respecto a la entrega anterior

| | Anterior (`…2026.10.28`) | Nueva (`…2026.10.28-r2`) |
| --- | --- | --- |
| Servicios del Compose | `app`, `qgc`, `hermes`, `planner-menu`, `ollama` | **`app`, `qgc` y `hermes`** (`compose_diff_vs_previous_bundle.txt`) |
| Volúmenes y redes | `hermes-home`, `ollama-models`; `provider`, `local-llm` | `hermes-home`; `provider` |
| Imagen `app` | `2026.10.27-r2` (archivo de 80,0 MB) | `2026.10.28` (79,6 MB, `f4a42d7e…`) |
| `qgc`, `planner`, script y ejemplos | — | **Mismos bytes**, por enlaces duros a la entrega anterior (`reused_archives_hardlinks.txt`) |
| `LEEME.md` | Ollama opcional; requisitos mezclados | Sin Ollama. Plataforma probada separada de lo que exigen las imágenes, paso `check` de Hermes y simulador marcado como ausente |
| `VERSIONES.json` | — | `changes_vs_previous`, `previous_bundle` y las imágenes reutilizadas con `reused_archive_from` |

## Verificación aislada (`isolated_check/`, `tools/isolated_check_r2.sh`)

**Montaje de la prueba:**
- **Copia:** `cp -al` en un directorio nuevo del scratchpad, **fuera del repositorio**.
- **Entorno:** `env -i`, HOME vacío y uid 1000.
- **Proyecto Compose:** `tfg-entrega-r2-prueba`, para no usar el volumen de ningún otro proyecto.
- **Solo lo afectado:** no se repitieron el recorrido completo ni las suites generales.

| # | Comprobación | Resultado |
| --- | --- | --- |
| 00 | El directorio de trabajo está fuera del repositorio | PASS |
| 01 | `sha256sum -c SHA256SUMS` | PASS, 16 OK |
| 02 | `docker load` de `tfg-app-2026.10.28.tar` e ID de las tres imágenes = `VERSIONES.json` | PASS |
| 03 | `docker compose config` con los perfiles `app`, `qgc` y `planning` | PASS: solo `app`, `hermes` y `qgc`; volumen `hermes-home`; red `provider`; sin `build` ni binds al repositorio |
| 04 | Ninguna referencia a `ollama` o `planner-menu` en `compose.yaml`, `LEEME.md` ni la configuración resuelta | PASS |
| 05 | Menú offline de la app | PASS: 4 opciones NOT AVAILABLE, la opción 5 (escenario) disponible, Hermes nombrado y ninguna mención a Ollama |
| 06 | Consulta offline del escenario | PASS: `AERIAL_COMPLETED_GROUND_PENDING` |
| 07 | `hermes_home.py check` en un volumen nuevo | PASS: `PLANNING_SAFE` |
| 08 | Configuración de Hermes resultante | PASS: `nous` / `poolside/laguna-s-2.1:free`; servidor stdio `tools.hermes_mcp_server` con `include: [update_mission_draft, finalize_mission_draft]`, recursos y prompts desactivados, `tool_search` off y ningún otro servidor MCP |
| 10 | Tras `down`, un contenedor nuevo | PASS: la configuración sigue en el volumen, `auth.json` ABSENT y los resultados de la app se conservan |

### Qué acredita y qué no

- **Hermes no se ejecutó.** No hubo ni proveedor real ni doble: solo se comprobó la configuración que ve. La escritura del almacén de planificación ya se acreditó con la misma imagen `planner` y la misma definición de volúmenes en `student_bundle_2026_10_28`; no se repitió.
- **QGC no se abrió**, y su imagen no ha cambiado.
- **La prueba fue en el mismo equipo.** `docker load` encontró las imágenes ya presentes. **La prueba en un segundo ordenador sigue pendiente.**
- **Restos en Docker:** queda el volumen `tfg-entrega-r2-prueba_hermes-home`, con un `config.yaml` de planificación y sin `auth.json`. No quedan contenedores (`12_leftovers.log`).

## Pendiente

Simulador (Codex; [simulator-distribution-handoff.md](../../../docs/simulator-distribution-handoff.md) §8), prueba en un segundo ordenador, versionado, licencia y publicación eventual.
