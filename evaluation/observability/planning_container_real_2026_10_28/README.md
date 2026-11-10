# Ejecución real de Hermes en `tfg/planner`, 28/10/2026: FALLIDA antes del modelo

**Resultado:** la única ejecución autorizada de Hermes terminó con retorno 1 a los 12,4 s, sin timeout, con el mensaje `Hermes is not logged into Nous Portal`. **No hubo ninguna petición al modelo**, ninguna herramienta llamada y ninguna misión generada. No se relanzó.

| Dato | Valor |
| --- | --- |
| Imagen | `tfg/planner:2026.10.27`, `sha256:651cc6e22be53ad5296a44af9659f0b6205464209f852bab9a150555161c8455` |
| Caso | `agri-planning-container`: prompt de H1 (sha256 `068d17ea…`), herramientas `update_mission_draft` y `finalize_mission_draft`, Tool Search desactivado, `--toolsets tfg-mission-control` |
| Proveedor y modelo configurados | `nous` / `poolside/laguna-s-2.1:free`, en el home de ensayo `/hermes/trial` del volumen `hermes-home` |
| Ejecución | `real-hermes-planning-container-20261028`, de 07:38:19,9 a 07:38:32,3 UTC; `hermes_invocations` 1, `automatic_retry` false, `timed_out` false, retorno de Hermes 1, retorno del ejecutor 2 (`execute_result.json`, `execute_rc.txt`) |
| Uso nativo | `private/native-usage.json`: `failed` true y `failure` «Hermes is not logged into Nous Portal». Sin `api_calls`, tokens, modelo ni sesión |
| Captura | Sin archivos de captura (`capture_files` vacío). La revisión offline se negó: `review_result.txt`, «nothing to review» |
| Restauración | Configuración del home de ensayo restaurada y plugin retirado (`restore.ok` true) |
| Almacén | `work/planning_store` sin ninguna escritura |
| Opik | No usado |

## Comprobaciones previas

`precheck_before_login.json` y `precheck_after_login.json` dan `ok: true` en todas las verificaciones. La configuración del home de ensayo no cambió con el inicio de sesión (mismo sha256).

## Causa

`observability/hermes_capture_run.py` recibía `--hermes-home /hermes/trial` y comprobaba y editaba ese home, pero **no pasaba `HERMES_HOME` al proceso de Hermes**. En el anfitrión no hacía falta, porque Hermes usa `~/.hermes` por defecto. La imagen, en cambio, fija `HERMES_HOME=/hermes/planning`, así que Hermes leyó el home de planificación, que no tiene sesión.

Apoyo (`auth_and_home_diagnosis.json`, solo presencia de campos y diagnóstico, ningún valor):
- **Home de ensayo:** `auth.json` presente (0600, uid 1000), con `providers.nous` y 1 credencial `device_code` con `request_count` 0, es decir, sin usar.
- **Home de planificación:** no tiene `auth.json` y aparecen en él los archivos de estado que Hermes creó durante la ejecución.

El inicio de sesión del operador se hizo con `hermes auth add nous --no-browser` en `/hermes/trial`. Antes, `hermes_home.py login` se había negado en ese home porque exigía un filtro que el home de ensayo no lleva a propósito, otro defecto del lanzador. Su salida no se conserva aquí: contiene el correo de la cuenta y el código de dispositivo.

## Correcciones (fuentes; la imagen `651cc6e2…` no se ha reconstruido)

- El ejecutor fija `HERMES_HOME` al home comprobado. Prueba: `test_DOUBLE_hermes_gets_the_checked_home_even_with_another_inherited_HERMES_HOME`.
- `hermes_home.py login` usa el proveedor del propio home sin exigir el filtro. Prueba: `test_login_uses_the_homes_own_provider_including_the_unfiltered_trial_home`.
- `test_planning_profile.py` y `test_hermes_capture_run.py`: 137 passed.
- `docs/planning-first-real-test.md` pasa `-e HERMES_HOME=/hermes/trial`, lo que sirve también con la imagen actual.

## Pendiente

Repetir la ejecución requiere **una nueva autorización**. La credencial caduca a las 08:37 UTC del 28/10; puede renovarse sola o requerir otro inicio de sesión.
