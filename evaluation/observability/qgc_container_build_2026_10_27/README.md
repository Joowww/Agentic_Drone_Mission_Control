# Build de la imagen QGroundControl (27/10/2026)

Resultado: **IMAGE_BUILT_CHECKS_PASSED_GUI_NOT_OBSERVED**. La imagen está construida y se han hecho comprobaciones de versión, dependencias y procedencia. No se ha abierto la interfaz gráfica ni se ha arrancado el servicio `qgc`. No se ha importado ningún `.plan`.

| Dato | Valor |
| --- | --- |
| Imagen | `tfg/qgroundcontrol:5.1.5`, ID `sha256:c6a5c57a1552b9e92b741e6ffc15d2d0754d80b47e9a657727f9b467f738f314`, 1 196 821 033 bytes, creada 2026-10-27T16:24:11Z. Solo local, sin publicar y sin digest de registro |
| Fuente | `deploy/qgc/` (hashes en `deploy_files.sha256`; copia del Dockerfile en `Dockerfile.snapshot`) |
| Artefacto | `QGroundControl-x86_64.AppImage` de la release v5.1.5 (inmutable, «V5.1 - Stable», 2026-10-01). sha256 `9a47e4cf269d9e4f897f582f6b19aa7ebf1e9e67c9d68a532a45b541354bc344`, igual al digest que publica GitHub y al `ADD --checksum`. Bytes exactos exportados desde la caché del build (`artifact_sha256.txt`) |
| Procedencia | Tag `v5.1.5` → commit `3a67d31f0c36bf3fe38ec52970d250a89d0aaf67`; el tag **no está firmado**. Hay tres atestaciones de GitHub: SLSA v1 (workflow `.github/workflows/linux.yml@refs/tags/v5.1.5`, mismo commit y sujeto), SBOM SPDX (mismo sujeto) y release v0.2. Contenido **inspeccionado, sin verificación criptográfica de firma**: el `gh` 2.45.0 local no tiene `attestation verify` y no se instaló nada |
| Base | `ubuntu:24.04@sha256:24737cef…573c`, la plataforma soportada por el AppImage según la documentación oficial |
| Paquetes apt | Solo desde `snapshot.ubuntu.com/ubuntu/20261024T000000Z` (fuentes reescritas, sin recurso al archivo vivo). 163 paquetes en `dpkg_list.txt`. Los `ca-certificates` del archivo vivo solo se montan durante ese paso y no quedan en la imagen |
| Versión | `QGroundControl v5.1.5`, obtenida con `--version` (Qt `offscreen`, sin red, raíz de solo lectura, sin capacidades): `version_check.txt` |
| Dependencias | `ldd` del binario, los plugins Qt y GStreamer. Solo faltan, a propósito, el tema GTK3 (`libqgtk3`) y la voz speech-dispatcher, ambos opcionales (`deps_check.txt`). El aviso de pipewire es de Qt Multimedia y opcional |
| Autosuficiencia | `history.txt` e `image_inspect.json` no contienen rutas personales ni del scratchpad. Sin volúmenes ni puertos declarados. Nada se lee del anfitrión al construir, salvo el contexto `deploy/qgc` |

## Intentos

1. `build_attempt1_failed.log`: falló. Sin certificados, apt no pudo abrir el snapshot HTTPS y la instalación terminó con código 100, sin usar el archivo vivo en silencio. Corregido con la etapa `certs` y fuentes que solo apuntan al snapshot.
2. `build_attempt2_superseded.log` (imagen `5e87a4ee…`): `/opt/tfg` quedó sin permiso de acceso por un `COPY --chmod`, de modo que el entrypoint no se habría podido ejecutar. Además faltaban bibliotecas de `libgstlibav`. Corregido.
3. `build_attempt3_superseded.log` (imagen `2c336965…`): faltaba `libXrandr` para el plugin multimedia de ffmpeg y no había locale UTF-8. Corregido.
4. `build.log`: la imagen final.

Las imágenes `5e87a4ee…` y `2c336965…` quedan sin etiqueta en Docker. No se han borrado (no se hacen podas).

## Límites

- No se ha comprobado que el build sea reproducible bit a bit: el ID cambia con las marcas de tiempo de cada build.
- La interfaz gráfica sobre WSLg no está validada: el servicio no se ha arrancado ni se ha observado.
- `compose_config_qgc.yaml` resolvió `QGC_SAVE_DIR` con un directorio temporal de prueba, ya eliminado.
