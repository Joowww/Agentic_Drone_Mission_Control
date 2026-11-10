# Restauración de las evidencias externas

La normalización conserva los originales en sus rutas. El archivo externo contiene las unidades completas del
catálogo `evidence-archive-2026-11-02.json`, incluidos archivos previamente ignorados, fuentes anidadas, dependencias,
permisos y enlaces. No se modificó ningún manifiesto histórico. El archivo es privado; no se publica con los fuentes.

## Material necesario

- Este clon y su catálogo versionado.
- `evidencias-2026-11-02.tar.zst` y su `.sha256`, disponibles en el directorio externo de normalización.
- `tar`, `zstd` y `sha256sum`. No hace falta arrancar servicios.

La ubicación inicial es `~/TFG/archivo_TFG/normalizacion-2026-11-02.*/`. El rescate completo anterior permanece
separado en `~/TFG/archivo_TFG/rescate-2026-11-02.kl4ohz2x/`; conserva también `.git`, estados y reservas originales.
No se restauran estados operativos de `missions/generated/` como parte de este procedimiento.

## Verificación previa

1. Leer el nombre, tamaño y SHA-256 del archivo en el catálogo.
2. Desde el directorio que contiene el archivo, ejecutar:

```bash
sha256sum --check evidencias-2026-11-02.tar.zst.sha256
zstd --test evidencias-2026-11-02.tar.zst
```

Comprobar también que el SHA-256 calculado del archivo tar coincide con el valor del catálogo versionado;
el archivo lateral `.sha256` por sí solo no es una referencia independiente. Si difiere, detenerse.

## Restaurar en un clon nuevo

Las rutas de destino del catálogo deben estar ausentes. Si ya existen, no sobrescribirlas ni mezclar registros:
comparar primero o usar otro clon limpio. Examinar el listado del tar; solo debe contener las rutas relativas del
catálogo y sus descendientes, sin rutas absolutas ni componentes `..`.

```bash
# Situarse en la raíz del clon nuevo. Sustituir la ruta externa por la ubicación real.
tar --extract --keep-old-files --no-same-owner --acls --xattrs \
  -I zstd -f /ruta/externa/evidencias-2026-11-02.tar.zst
```

Si `tar` informa de un error, detenerse. No usar `--overwrite`, `--unlink-first`, `--strip-components` ni
`--exclude-vcs`: el repositorio ArduPilot anidado forma parte del registro. Los enlaces se conservan, no se siguen
para copiar objetivos externos. La asignación de propietarios puede variar al restaurar con otro usuario.

## Alcance de la validación

La fase de normalización comprobó los bytes de cada miembro del tar contra los SHA-256 del rescate, el flujo zstd,
la correspondencia del tar con el árbol del rescate y el SHA-256 del archivo final. No regeneró registros, no
reselló informes y no reinterpretó un fallo histórico como éxito.

Las pruebas de rover que leen fuentes o sesiones históricas necesitan esta restauración. Por ejemplo,
`test_rover_clock_path.py` consume `source/ardupilot/libraries/SITL/SIM_JSON.cpp`, y las pruebas de cierre/checksum
consumen sesiones conservadas. La exportación del archivo no sustituye las pruebas funcionales en el clon limpio.

No deduplicar los registros ni ejecutar scripts contenidos en evidencias para validar una restauración.
Los tres `.pyc` del piloto agrícola incluidos en su SHA256SUMS están versionados y no deben recompilarse.
