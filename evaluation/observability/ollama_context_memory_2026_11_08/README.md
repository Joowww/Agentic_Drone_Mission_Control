# Ollama: contexto de 64 k, memoria y latencia en RTX 3070 Laptop (08/11/2026) — REAL

**Tipo: REAL (mediciones).** Prueba local y controlada autorizada por Joel (fase P3 de la demo Hermes + Ollama).
Ollama 0.34.2; GPU NVIDIA RTX 3070 Laptop (8 192 MiB); WSL2 con 15,5 GiB de RAM. Todas las peticiones fueron a
`127.0.0.1` (11434 = servicio del sistema; 11435 = instancia propia de la prueba). Límite por petición: 600 s
(`curl --max-time`). No se detuvo ningún servicio ni sesión ajena; el servicio del sistema no se reconfiguró.

## Por qué

Hermes Agent `d923a5eb` rechaza modelos con menos de 64 000 tokens de contexto
(`agent/model_metadata.py: MINIMUM_CONTEXT_LENGTH`). Ollama sirve 4 096 por defecto.

## Mediciones

| # | Modelo / configuración | Dónde | Capas en GPU | Caché KV | Memoria | Carga | Generación | Resultado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `qwen3-4b-64k` (qwen3:4b *Thinking* 2507 + `num_ctx 65536`), KV f16 | 11434 | 17/37 | 9 216 MiB (5 120 CPU + 4 096 GPU) | 12 GB, 52 %/48 % CPU/GPU; RAM disponible mínima 3,3 GiB | 57,1 s | ~4 tokens/s | «OK» tras 101 tokens de razonamiento |
| 2 | Igual, llamada con las 2 herramientas reales (`/v1`) | 11434 | 17/37 | f16 | igual | — | ~4 tokens/s | **Cortada a 600 s**: 2 556 tokens de prompt leídos en ~4 s (590 tokens/s); >2 350 tokens de razonamiento sin llamada |
| 3 | Variante con el bloque `<think>` cerrado en la plantilla | 11434 | 17/37 | f16 | igual | — | ~4 tokens/s | **Cortada a 600 s**; 300 tokens en *streaming*: todo razonamiento, Ollama lo clasifica como `reasoning`. Variante descartada y borrada |
| 4 | `qwen3:4b` con contexto por defecto (4 096) | 11434 | 37/37 | — | 3,2 GB, 100 % GPU | 5,5 s | **101,6 tokens/s** | Referencia de velocidad con todo en GPU |
| 5 | `qwen3-4b-64k`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` | 11435 | 28/37 | 4 896 MiB (1 224 CPU + 3 672 GPU) | 8,3 GB, 23 %/77 % | 50,5 s | 12,0 tokens/s | Insuficiente |
| 6 | `qwen3-4b-64k`, flash attention + KV **q4_0** | 11435 | **37/37** | 2 592 MiB | **5,6 GB, 100 % GPU**; RAM disponible mínima 8,6 GiB | 5,0 s | 29,8 tokens/s | Cabe entero |
| 7 | Igual que 6, llamada con las 2 herramientas | 11435 | 37/37 | q4_0 | 5,6 GB | — | ~17,8 tokens/s | `tool_calls` correcta tras **430 s** y 7 657 tokens generados (razonamiento) |
| 8 | **`qwen3-4b-instruct-64k`** (Qwen3 4B *Instruct* 2507 Q4_K_M + `num_ctx 65536`), KV q4_0 | 11435 | 37/37 | 2 592 MiB | 5,6 GB, 100 % GPU; RAM disponible mínima 9,0 GiB | ~5 s | — | `tool_calls` correcta en **9,2 s** (carga incluida), 179 tokens generados, 3 231 de prompt |

Errores por falta de memoria: ninguno; con KV f16, Ollama repartió capas entre CPU y GPU en lugar de fallar.
Contexto efectivo: 65 536 en todos los casos (`ollama ps` y `n_ctx_seq` en el log del servidor).

## Decisiones tomadas con estos datos (autorizadas por Joel)

- Descargar **un** modelo sin fase de razonamiento: `qwen3:4b-instruct-2507-q4_K_M` (2,5 GB, 4 min 24 s).
- Servir la demo desde una **instancia propia** de Ollama en `127.0.0.1:11435` con
  `OLLAMA_FLASH_ATTENTION=1` y `OLLAMA_KV_CACHE_TYPE=q4_0`, que lee el almacén de modelos del sistema sin
  poder escribir en él. El servicio del sistema (11434) y sus usos (pilotos multiagente) no cambian.
- La caché KV q4_0 reduce la precisión respecto a f16; es el precio de que 64 k quepan en 8 GiB.

## Contenido

`raw/`: estados de memoria antes y después, muestras de VRAM/RAM por segundo, respuestas de Ollama,
extractos del log del servidor (`--flash-attn`, capas descargadas, tamaño de la caché), peticiones usadas,
resúmenes de los *streams*, Modelfiles (incluida la variante descartada) y el resumen de la descarga. El
*stream* completo de 1,7 MB de la medición 7 se conserva solo en local. Rutas personales sustituidas por `~`.
Manifiesto: `SHA256SUMS`. Registro sellado.
