# Primera prueba real del perfil de planificación (ejecutada el 28/10/2026)

> **Este documento es el registro de la prueba real**, con los comandos tal como se ejecutaron con la imagen `tfg/planner:2026.10.27` (`651cc6e2…`), incluido el arreglo manual `-e HERMES_HOME=/hermes/trial`. El **procedimiento vigente** para la imagen actual `tfg/planner:2026.10.28`, que ya no necesita ese arreglo, está en [student-environment.md](student-environment.md) §9. El resultado de abajo acredita **solo** la imagen `651cc6e2…`.

**Resultado (segunda autorización, 28/10/2026): COMPLETADA.** Retorno 0 en 87,8 s, 3 llamadas al modelo en el ciclo de herramientas y solo las 2 herramientas permitidas. Las dos misiones quedaron finalizadas con validación FEASIBLE/APPROVED y `qgc_export` REFUSED por falta de AMSL; su `mission.json` es idéntico al de H1 (`321ad647…` y `079e25a3…`). Reintentos internos: no informados (`retry_count` null). Evidencia: `evaluation/observability/planning_container_real_2026_10_28_r2/`. El primer intento del mismo día falló antes del modelo (ver más abajo).

**Qué acredita, si sale bien:** que el recorrido de planificación de H1 funciona dentro del contenedor (`tfg/planner`) con un proveedor real: entrada del operador → Hermes → herramientas MCP del proyecto → validación determinista → borrador, finalización y misión persistentes.
**Qué no acredita:** vuelo, simulación, carga en un vehículo, otros modelos ni otras entradas. Es **una ejecución de Hermes** y no se relanza.

Una ejecución de Hermes no equivale a una petición al proveedor. Dentro de ella hay tres cosas distintas:
- **Peticiones normales del ciclo de herramientas.** Hermes pide al modelo, ejecuta las herramientas que este solicita y vuelve a pedir con sus resultados. En H1 hubo varias en una misma ejecución (cuatro llamadas a herramientas). Con el doble hubo dos del agente más una llamada auxiliar de Hermes sin herramientas. Su número depende del modelo y no se fija aquí.
- **Reintentos al proveedor.** Los hace Hermes por su cuenta cuando una petición falla. Su política se describe en el apartado «Reintentos internos de Hermes».
- **Relanzamientos del proceso.** No hay ninguno: el ejecutor arranca Hermes una vez y no lo vuelve a lanzar.

## Datos fijados

| | |
| --- | --- |
| Mecanismo | El ejecutor existente `observability.hermes_capture_run`, caso `agri-planning-container` (preparado el 27/10/2026, no ejecutado) |
| Hermes | `NousResearch/hermes-agent` en `d923a5eb487a17c0a68801bba9ef0f56c81040a8`, el mismo de H1, dentro de la imagen `tfg/planner` |
| Proveedor y modelo | `nous` / `poolside/laguna-s-2.1:free`, los de H1 (plantilla `deploy/planner/hermes-config.base.yaml`). Requiere una cuenta propia de Nous Portal |
| Entrada | El prompt de H1 (`AGRI_PLANNING_PROMPT`): dos misiones de agri_demo_001 con todos los datos aportados por el operador |
| Herramientas permitidas | Solo `update_mission_draft` y `finalize_mission_draft` del servidor `tfg-mission-control`. El ejecutor añade `tools.include`, desactiva Tool Search y lanza Hermes con `--toolsets tfg-mission-control`: no hay terminal, web ni otras herramientas |
| Límites | Una ejecución de Hermes (`hermes_invocations` 1), un timeout de 300 s para toda la ejecución y ningún relanzamiento automático (`automatic_retry` false), como en H1. No se fija un número de peticiones al proveedor (ver arriba). Tras un fallo no se relanza nada |
| Fuentes fijadas | El caso fija el sha256 de `hermes_mcp_server.py`, `hermes_mission_planning.py`, `relative_routes.py`, `mission_plan_service.py` y `hermes_mission_validation.py`. Si alguno cambia, la comprobación previa rechaza la ejecución hasta revisarlo y volver a fijarlo |
| Opik | Desactivado. No se envía nada |

## Reintentos internos de Hermes (comprobados solo con el doble)

El 27/10/2026, con el proveedor falso (`planner_container_build_2026_10_27/checks/`), se observó lo siguiente:
- con una respuesta que no es JSON válido, Hermes informó «didn't answer after 3 attempts»;
- sin proveedor accesible, informó «didn't respond in time on any of 3 attempts».

Eso es lo observado en esos dos fallos con esa versión (`d923a5eb`) y esa configuración. **No es un máximo global de peticiones** de una ejecución, ni se ha comprobado con otros tipos de error del proveedor real. Si en la prueba real hay reintentos, se registran como tales: no son una segunda ejecución.

## Comandos ejecutados (imagen `651cc6e2…`; registro)

Imagen: `tfg/planner:2026.10.27`, ID `sha256:651cc6e22be53ad5296a44af9659f0b6205464209f852bab9a150555161c8455`. Para reconstruirla:

```bash
python3 deploy/planner/hermes_source.py fetch --out deploy/planner/vendor/hermes-agent-d923a5eb.tar
docker compose -f deploy/compose.yaml --profile planning build hermes
```

El primer comando verifica el árbol del commit; con un clon que ya lo tenga, sirve `export --repo <clon>`. El build vuelve a verificar el sha256 y el árbol.

Prepara los directorios, una sola vez:

```bash
mkdir -p work/planning_store work/hermes-private
```

La comprobación previa del paso 3 ya se observó dentro del contenedor el 27/10/2026, sobre un home de ensayo desechable y sin red: `ok: true` en sus 18 verificaciones, entre ellas `tool_selection_sources_verified` y `trial_server_sources_pinned` (`evaluation/observability/planner_container_build_2026_10_27/runner_preflight/`). Hay que repetirla sobre el home real antes del paso 4.

1. **Home de ensayo.** Usa la configuración base, porque el ejecutor añade y retira el filtro él mismo. Se guarda en el volumen `hermes-home`:

   ```bash
   docker compose -f deploy/compose.yaml run --rm hermes /opt/tfg/deploy/planner/hermes_home.py prepare-trial /hermes/trial
   ```

2. **Inicio de sesión del operador en ese home**, una vez. Usa el flujo con código de Nous: abre la URL que se muestra en el navegador del anfitrión. No se copia ninguna credencial del equipo:

   ```bash
   docker compose -f deploy/compose.yaml run --rm -e HERMES_HOME=/hermes/trial --entrypoint /opt/hermes/agent/.venv/bin/hermes hermes auth add nous --no-browser
   ```

   Con la imagen `651cc6e2…`, `hermes_home.py login` se niega en el home de ensayo («not planning-safe»), porque exigía el filtro que ese home no lleva a propósito. Está corregido en las fuentes, pero no en esa imagen.

3. **Comprobación previa, sin llamar al proveedor.** Debe dar `"ok": true`:

   ```bash
   docker compose -f deploy/compose.yaml run --rm -e HERMES_HOME=/hermes/trial hermes -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case agri-planning-container --hermes-home /hermes/trial --hermes-bin /opt/hermes/agent/.venv/bin/hermes --private-root /work/hermes-private
   ```

4. **La ejecución única de Hermes.** Solo con autorización expresa:

   ```bash
   docker compose -f deploy/compose.yaml run --rm -e HERMES_HOME=/hermes/trial hermes -m observability.hermes_capture_run capture --mcp-tool-trial --trial-case agri-planning-container --hermes-home /hermes/trial --hermes-bin /opt/hermes/agent/.venv/bin/hermes --private-root /work/hermes-private --timeout 300 --run-id real-hermes-planning-container-AAAAMMDD --execute
   ```

5. **Revisión**, offline y en un directorio nuevo:

   ```bash
   docker compose -f deploy/compose.yaml run --rm -e HERMES_HOME=/hermes/trial hermes -m observability.hermes_capture_run review --mcp-tool-trial --trial-case agri-planning-container --private-dir /work/hermes-private/<directorio creado> --evidence-dir /work/planning_container_AAAA_MM_DD
   docker compose -f deploy/compose.yaml run --rm -e HERMES_HOME=/hermes/trial hermes /opt/tfg/deploy/planner/hermes_home.py status
   ```

## Evidencias que se conservan

- `work/hermes-private/<ts>/`: stdout, stderr, `native-usage.json`, eventos de la captura, la copia de la configuración y su restauración (`run.json`).
- `work/planning_container_AAAA_MM_DD/`: la evidencia revisada, con su `SHA256SUMS`.
- `work/planning_store/drafts/…`: `draft.json`, `draft_state.json` y, por cada finalización, `source_draft.json`, `mission.json` y `finalization.json`.

Después se copian a `evaluation/observability/<nuevo>/`. No se modifica la evidencia de H1.

## Intento del 28/10/2026: FALLIDO antes de contactar con el modelo

Evidencia: `evaluation/observability/planning_container_real_2026_10_28/`.

- **Qué pasó.** La ejecución autorizada (`real-hermes-planning-container-20261028`, imagen `651cc6e2…`) terminó con retorno de Hermes 1 a los 12,4 s, sin timeout, con el mensaje `Hermes is not logged into Nous Portal`.
- **Causa.** El ejecutor no pasaba `HERMES_HOME` al proceso de Hermes, y la imagen fija `HERMES_HOME=/hermes/planning`. Hermes leyó el home de planificación, que no tiene sesión, en lugar del home de ensayo comprobado y editado.
- **Hechos:**
  - **0 peticiones al modelo** (`native-usage.json`: `failed`, sin `api_calls` ni tokens);
  - la credencial del home de ensayo sigue sin usar (`request_count` 0);
  - ninguna herramienta llamada y ninguna escritura en el almacén;
  - la configuración del home de ensayo se restauró y el plugin se retiró;
  - la revisión offline se negó (`nothing to review`).
- **Sin relanzamiento.** La ejecución autorizada quedó consumida.
- **Corrección.** En las fuentes, el ejecutor fija ahora `HERMES_HOME=--hermes-home`, con su prueba. Con la imagen actual, los comandos de arriba ya pasan `-e HERMES_HOME=/hermes/trial`.
- **Para repetir** hace falta **una nueva autorización**. La credencial guardada caduca (`expires_at` 08:37 UTC del 28/10), así que puede requerir otro inicio de sesión.

## Criterio

**Éxito**, solo si se cumple todo:
- `return_code` 0 y sin timeout;
- las ofertas de herramientas registradas contienen exactamente las 2 permitidas y no se llama a ninguna otra;
- hay dos borradores con los datos del prompt, sin valores inventados ni cambiados;
- hay dos `finalization.json` completos;
- la validación determinista queda registrada;
- `qgc_export` es **`REFUSED` por falta de AMSL**, porque el prompt no la da: ningún `.plan` inventado;
- la respuesta final de Hermes no afirma más de lo que registran las herramientas.

**Fallo:**
- cualquier otra herramienta ofrecida o llamada;
- datos inventados o cambiados;
- una finalización incompleta presentada como terminada;
- un `.plan` escrito sin AMSL;
- error del proveedor, timeout o más de una ejecución de Hermes.

Un fallo es un resultado y se documenta. No se reintenta en la misma tanda.
