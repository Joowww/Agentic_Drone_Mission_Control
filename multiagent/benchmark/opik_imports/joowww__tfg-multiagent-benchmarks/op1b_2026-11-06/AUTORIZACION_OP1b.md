# Autorización OP-1b (plantilla; NO firmada, NO ejecutada)

La autorización de OP-1 (hashes `0ce48bc0…`/`5399a701…`) **no** cubre OP-1b: los cuerpos son distintos.

## Paso 1 — autorizar el contenido (ya calculable, no caduca)

> Autorizo OP-1b: importación histórica (no una nueva ejecución del modelo) de las 10 trazas del piloto
> `pilot_qwen3_4b_v1_2026-11-04_c00b737d3` (E01 E04 E11 E12 E18 E19 E20 E21 E22 E27; E07 excluida), 62 spans
> (10 llamadas LLM reales), a `joowww` / `tfg-multiagent-benchmarks`, con contenido canónico
> traces `15fa84cc592a05f4dfeb61905cc6443f995b866bf70f64c7845f97863b0dcb9f` y
> spans `1dfc76cb921ef2e671d435254f85039d589834d84ebf0dbfc1dbf289029bcd7a`
> (independiente de los ids; regla de ids en `manifest.json`), reemplazando los ids rechazados en OP-1.

## Paso 2 — en el momento de importar (los ids caducan en 24 h)

```bash
python -m multiagent.opik_op1 prepare --id-epoch <ahora, ISO UTC> --out <dir nuevo>
```
comprueba el contenido contra este manifiesto e imprime los SHA-256 exactos de `traces/batch` y `spans/batch`.

> Autorizo el envío único de OP-1b con id_epoch `<…>`, traces/batch `<sha256 completo>`, spans/batch
> `<sha256 completo>`, sin reintentos, con verificación individual posterior.

```bash
python -m multiagent.opik_op1 send --i-authorize-op1b --id-epoch <mismo> --traces-sha <…> --spans-sha <…>
python -m multiagent.opik_op1 verify --id-epoch <mismo> --out <archivo>
```
