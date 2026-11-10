# Diagnóstico del arranque gráfico de QGC/WSLg (30/10/2026)

Solo lecturas. No se arrancó QGC ni ningún otro programa gráfico, ni se reinició WSL, Docker, Windows o algún servicio. Copias de los logs de WSLg, tomadas a las 08:33 UTC: `weston.log`, `stderr.log`, `wlog.log`, `pulseaudio.log` y `versions.txt` (WSLg 1.0.73.2). `stat_at_copy.txt` guarda sus fechas.

## Secuencia (hora local CET, de `weston.log` y `stderr.log`)

| Hora | Evento | Fuente |
| --- | --- | --- |
| 29/10 12:18:33 | Arranque de WSLg: Weston con backend RDP y Xwayland. Se conecta el cliente RDP de Windows (`rdp_peer 0x…d420`) con una pantalla de 1920×1080 | weston.log 6–291 |
| 29/10 12:54:38 → 12:56:18 | Desconexión del cliente RDP; `msrdc.exe` sale con estado 0 y se vuelve a conectar (`rdp_peer 0x…12e0`) | weston.log 318–423; stderr.log |
| 29/10 14:36:16 | Nueva desconexión. `msrdc.exe` sale con estado **4**; los relanzamientos fallan con estado **107** diez veces en menos de 1 s y WSLGd deja de intentarlo: «exited more than 10 times in 60 seconds, not starting it again» | weston.log 487; stderr.log |
| 30/10 09:22 | Registro previo de la importación: socket X0 del 29/10 12:18 | preregistration.txt |
| 30/10 09:26:31 | Primer intento de QGC: `CreateWndow(): rdp_peer is not initalized` y `set_window_icon(): …` | weston.log 509–514 |
| 30/10 09:26:32 | **Weston muere por la señal 11** (SIGSEGV). Xwayland pierde la conexión Wayland («failed to read Wayland events: Connection reset by peer»). Esto encaja con el «XIO fatal» de QGC | stderr.log |
| 30/10 09:26:32 | WSLGd vuelve a arrancar Weston, con la pantalla a **0×0** porque no hay cliente RDP. Sockets X0 y wayland-0 nuevos | weston.log 520–604; mtime de los sockets |
| 30/10 09:29:19–21 | Segundo intento: Xwayland arranca (pid 12618) y QGC crea **dos ventanas y su icono**. Las tres veces `rdp_peer is not initalized` | weston.log 675–681 |
| 30/10 08:33 UTC | `tasklist.exe`: **ningún `msrdc.exe` ni `mstsc.exe`** en ejecución en Windows | tasklist_msrdc.txt |

## Conclusión

**Es un fallo de visualización de WSLg, no de QGC.**
- **La causa:** desde el 29/10 a las 14:36 no hay cliente RDP de Windows conectado a Weston. Sin él, ninguna ventana de WSLg puede aparecer en el escritorio de Windows, sea cual sea el programa.
- **Hasta dónde llegó QGC:** en el segundo intento, QGC llegó a crear su ventana en el servidor X, y Weston la registró.
- **Lo que no se puede comprobar:** el contenedor era `--rm` y ya no existe, así que no se ve si QGC siguió en marcha después.
- **El primer intento:** el XIO fatal se explica por el SIGSEGV de Weston, que ocurrió al crear la ventana sin cliente RDP. Es un fallo de WSLg y no aporta nada sobre QGC.
- **No se ha importado ni guardado ningún plan:** `qgc_saved/` está vacío. Los originales siguen montados en solo lectura y sin cambios.

## Opciones (ninguna ejecutada)

| Opción | Efecto | Impacto |
| --- | --- | --- |
| A. Relanzar solo el cliente RDP de WSLg, con el mismo comando que usa WSLGd (`msrdc.exe /wslg /silent /v:648AB821-… C:\Program Files\WSL\wslg.rdp`, copiado de stderr.log) | Vuelve a conectar la visualización de las ventanas de WSLg | Solo afecta al canal de visualización: WSL, Docker, contenedores y el SDK de Codex siguen igual. Las ventanas de WSLg que existan ahora pasarían a verse. No es un procedimiento documentado de WSL; puede volver a fallar con el estado 107 si persiste la causa en Windows |
| B. `wsl --shutdown` | Reinicia WSL entero y con él WSLg | **Para todas las distribuciones, incluida la de Docker Desktop: se paran todos los contenedores, incluido el SDK de Codex**, y se cierra esta sesión. Desaconsejado |
| C. `wsl --terminate <distribución>` | Reinicia la distribución y su WSLg | Cierra esta sesión, el servidor de VS Code y cualquier proceso de Codex en esa distribución. Desaconsejado |

Antes de volver a arrancar QGC conviene comprobar, solo con lecturas, que hay un cliente RDP: `msrdc.exe` en `tasklist`, un `rdp_peer` nuevo y una pantalla distinta de 0×0 en `weston.log`.

## Opción A ejecutada (autorizada por Joel, un único intento)

- **Antes (08:40:26 UTC):** sin `msrdc.exe` ni `mstsc.exe` en Windows, y sin líneas nuevas en `weston.log` (681 líneas, igual que la copia).
- **Comando:** el ejecutable y los argumentos originales que WSLGd registró en sus 12 lanzamientos idénticos de `stderr.log`.
  - Un primer análisis encontró 2 líneas «distintas» porque la segunda era el mensaje de abandono de WSLGd. Se detuvo **antes de lanzar nada**.
  - Con el análisis limitado a los registros `Run:108`, se lanzó **una sola vez** a las 08:41:12 UTC, en su propia sesión.
  - En `msrdc_relaunch.json` el comando figura con los GUID enmascarados, más el sha256 del argv exacto (`ff107d58…`). La salida del proceso está en `msrdc_relaunch.out`, que quedó vacío.
- **Después:**
  - 09:41:14 CET: *handshake* del cliente (build 26300), `rdpMonitor[0]` de 1920×1080 primario, `Head mode change:rdp-0 NEW width:1920, height:1080` y `rdp_peer 0x613b07848730` (`weston.after_relaunch.log`).
  - 08:41:51 UTC: `msrdc.exe` sigue activo en la sesión de consola 1 y el proceso de enlace en Linux continúa (`tasklist_after_relaunch.txt`).
- **Sin tocar:** WSL, Docker, las distribuciones, Weston, los procesos de Codex y otros clientes RDP (no había ninguno). QGC no se arrancó.

## Desconocidos (registrados como tales)

- Si llegó a aparecer alguna ventana en los intentos de las 09:26 y las 09:29, y si Joel cerró alguna.
- Cómo terminó el segundo intento: si volvió solo, en cuánto tiempo, o si se interrumpió.
- Si Windows se suspendió, se bloqueó o cambió de sesión o de pantalla el 29/10 hacia las 14:36.
- Si hay otras ventanas WSLg abiertas. La captura de Codex está autorizada en modo headless, pero eso no acredita que no tenga otras ventanas.
