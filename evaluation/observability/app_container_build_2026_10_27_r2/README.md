# Imagen de la aplicación r2: menú offline, Ctrl+C temprano y errores de escritura (27/10/2026)

**Resultado:** `tfg/app:2026.10.27-r2` construida, con los cambios comprobados en contenedor. El recorrido de estudiante se repitió completo, **15/15 PASS**, porque la entrada nueva afecta a todos los pasos. No se ha publicado nada. La imagen probada antes, `tfg/app:2026.10.27` (`67bc37af…`), se conserva con su etiqueta y su evidencia (`app_container_build_2026_10_27/`, sin modificar).

| Dato | Valor |
| --- | --- |
| Imagen | `tfg/app:2026.10.27-r2`, ID `sha256:a86dae081f3fb3013abec5198e319ef82b38fea4ff5d54f3dbfbfed0a77d307b`, 344 697 164 bytes (`image_id.txt`, `image_inspect.json`, `build.log`) |
| Contenido | 401 archivos de `/opt/tfg`, idénticos al árbol (`image_files.sha256`). El nuevo es `deploy/app/entry.py`. La base y las dependencias no cambian (capas en caché) |
| Compose | `deploy/compose.yaml` apunta ahora a `-r2` |

## Cambios

1. **Menú coherente** (`main.py`). Con `TFG_PROFILE=offline`, que fija la imagen, el menú anuncia que el perfil no es una distribución de la planificación con IA. Marca las opciones 1 y 3 (necesitan Ollama) y 2 y 4 (guardan en `missions/generated`, ausente en la imagen de solo lectura) como `[NOT AVAILABLE: motivo]`. Si se eligen, muestra el motivo y vuelve al menú sin ejecutarlas. Sin la variable, el menú de desarrollo es el mismo de antes y no se elimina ninguna funcionalidad.
2. **Ctrl+C durante la carga** (`deploy/app/entry.py`, nuevo ENTRYPOINT). Ejecuta `-m`/`-c`/script como `python3` y convierte un `KeyboardInterrupt` que el programa aún no trata en un mensaje y código 130. Los programas que tratan Ctrl+C conservan su comportamiento, y sus códigos de salida pasan sin cambios.
3. **Errores de escritura** (`tools/agri_scenario_flow.py`). Un `OSError` al persistir (disco lleno, solo lectura, permisos) ya no sale como traceback: código 4 en la CLI y mensaje en el menú. El mensaje dice que las salidas **no** están terminadas y que los `*.tmp` no son registros: no se leen, la siguiente escritura correcta los sustituye y pueden quedar si el almacenamiento no permite borrarlos. Indica cómo reanudar.
   - **Revisión de `flow_record.tmp`:** ningún lector lo consume. La reanudación decide con `outputs_manifest.json`, cuyo recuento de archivos excluye `.tmp`, y con los registros del coordinador. Todas las escrituras son `tmp` + `replace` atómico, así que un `.tmp` truncado no puede sustituir a un registro válido ni bloquear `--resume`.
4. **Plantilla de VS Code** (`deploy/vscode/tasks.json`). Contiene las 7 tareas «TFG App/TFG QGC» con sus entradas. El `.vscode/tasks.json` personal se conserva y `.gitignore` no cambia.

## Pruebas

- **`pytest_test_agri_scenario_flow.txt`:** 47 passed. Incluye tres pruebas nuevas:
  - menú offline frente a menú de desarrollo;
  - entrada de la imagen (130 con mensaje y paso de los códigos de salida);
  - disco lleno con un `flow_record.tmp` truncado: código 4, `IN_PROGRESS`, el `.tmp` no se consume y `--resume` termina `FINISHED` sin `.tmp` y sin una segunda admisión.
- **En contenedor (`tests/`):**
  - `menu_offline.log`: opciones 1–4 → «not available here» con su motivo; la opción 5 funciona; salida limpia.
  - `early_0_9.log`, `early_1_2.log` y `mid_1_9`…`mid_2_08`: SIGINT durante la carga → rc 130, mensaje, sin traceback y sin escribir nada.
  - `mid_2_14`/`mid_2_2`: la señal llegó cuando la demo ya había terminado (`FINISHED`; rc 130 al cerrar).
  - `mid_2_26`…`mid_2_9`: la señal llegó tarde (rc 0). La demo cargada dura unos 0,1 s, así que por tiempo no se acertó a mitad del flujo. Ese caso lo cubre la regresión `test_interrupted_cli_run_resumes_once_with_the_same_admission`, y en contenedor se observó con la primera imagen (`app_container_build_2026_10_27/tests/cancel_1_9.log`).
  - `ro_demo.log`: directorio sin escritura → rc 4 y mensaje, sin traceback.
  - `full16k.log`: tmpfs de 16 KiB → rc 4. Quedan `flow_record.json` válido y `flow_record.tmp`, con el manifiesto en `IN_PROGRESS`. No se pudo probar la reanudación en ese mismo tmpfs, porque no se puede liberar; está cubierta por la prueba unitaria.
- **`walkthrough/`:** recorrido completo desde un directorio nuevo (`env -i`, HOME vacío, solo `compose.yaml` y el script): 15/15 PASS. Los 72 archivos pertenecen al usuario del anfitrión y no queda ningún contenedor.

No se reconstruyó QGC, no se repitió toda la suite y no hubo simulación, inferencias, publicación, staging, commit ni push.

## Inventario

`distribution_inventory_app_image.json`: conjunto `app_image` con `deploy/app/entry.py` y `deploy/vscode/tasks.json` añadidos. Sigue sin ser un clon de HEAD: hay archivos sin seguimiento y modificados que habría que versionar.
