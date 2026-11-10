# Detector de cartulinas: Python puro frente a OpenCV (06/11/2026, `6281ad4aa`)

**Qué se compara.** El detector del proyecto (`multiagent/card_detector.py`, en Python puro) frente a un port a OpenCV **del mismo algoritmo**, con los mismos umbrales leídos de `detector_config.json`. Se ejecutan sobre las mismas 37 imágenes PNG, con la misma métrica y en la misma máquina.

**Las imágenes.** Son escenas `SYNTHETIC_TEST` cenitales, de una cámara virtual a 10 m. **No hay fotografías reales.** El conjunto `detector_cmp/1` (sha256 `fef481ed…`) se fijó antes de medir y no se ha ajustado a ninguno de los dos detectores.

**El entorno de OpenCV.** Es un venv aislado fuera del repositorio, con `numpy==2.1.3` y `opencv-python-headless==4.10.0.84` (`detector_cmp_requirements.txt`). El venv compartido no se ha tocado y el detector del proyecto no se ha sustituido.

## Reproducir

```bash
python -m multiagent.benchmark.detector_cmp export --out <dir>
python -m multiagent.benchmark.detector_cmp run-python --images <dir> --out <dir>/python.json
python3 -m venv <venv> && <venv>/bin/pip install -r multiagent/benchmark/detector_cmp_requirements.txt
<venv>/bin/python -I multiagent/benchmark/detector_cmp_opencv.py --images <dir> --out <dir>/opencv.json
python -m multiagent.benchmark.detector_cmp score --images <dir> --runs <dir>/python.json <dir>/opencv.json
```

## Resultado

| | Python puro | OpenCV (port) |
| --- | --- | --- |
| Casos correctos | 34 / 37 | 34 / 37 |
| TP / FP / FN | 27 / 0 / 3 | 27 / 0 / 3 |
| Naranja marcado como ambiguo | 2 / 2 | 2 / 2 |
| Tiempo por imagen (mediana, solo `detect`) | 235 ms | 4,4 ms (unas 53 veces menos) |
| Memoria máxima del proceso (aprox.) | 26,6 MiB | 47,6 MiB |
| Líneas del detector (sin vacías ni comentarios) | 167 (con morfología y componentes propias) | unas 70 (las delega en OpenCV) |

**Las salidas coinciden escena a escena:** el mismo estado, las mismas detecciones y una diferencia de centroide de 0,000 px.

**Los tres fallos son los mismos en los dos detectores, porque son del algoritmo y no de la implementación:**
1. **`cast_yellow_green`.** Un tinte verde fuerte saca el amarillo de su banda de tono. Es un límite ya documentado y nunca lo convierte en rojo.
2. **`small_red`.** Una cartulina de 0,2 × 0,2 m a 10 m ocupa 6 × 6 = 36 px, por debajo de `min_area_px = 60`. **Hay una incoherencia de configuración:** `card_min_m = 0.15` admite tamaños que el filtro de área nunca deja pasar a esa altura (0,15 m son unos 20 px). No se ha reajustado: hay que decidir el umbral con imágenes reales.
3. **`border_yellow`.** Una cartulina que toca el borde de la imagen se marca `AMBIGUOUS` a propósito, porque puede estar cortada. La métrica lo cuenta como FN, pero es el comportamiento conservador previsto.

## Conclusión (limitada)

En estas imágenes sintéticas, OpenCV **no es más preciso**: es el mismo algoritmo y da el mismo resultado. Es mucho más rápido y usa algo más de memoria por las bibliotecas. Con 235 ms por imagen, el detector en Python basta para la demo offline; para vídeo en tiempo real, o para imágenes más grandes, haría falta OpenCV u otra implementación vectorizada.

Nada de esto valida el detector con fotografías reales: iluminación natural, sombras, desenfoque, balance de blancos. Esa sigue siendo la prueba pendiente (`docs/physical-integration-checklist.md`).
