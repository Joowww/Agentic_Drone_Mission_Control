# Detector v2 sobre el conjunto sellado `detector_cmp/1` (06/11/2026, `8c009e764`)

**Por qué se ha medido otra vez.** El detector cambió a la v2: el área mínima ahora se deriva de la geometría (profundidad y fx) y de un presupuesto declarado de error de tamaño, en lugar de ser un valor fijo. Solo se ha ejecutado el lado en Python puro. El port de OpenCV no ha cambiado y no se ha vuelto a ejecutar; la comparación v1 frente a OpenCV sigue siendo la de `detector_cmp_v1_2026-11-06_6281ad4aa/`.

**Entrada.** Las 37 imágenes PNG y su verdad, leídas del directorio sellado sin modificarlo (sus SHA256SUMS siguen verificando). Son escenas `SYNTHETIC_TEST`.

| | v1 (sellado) | v2 |
| --- | --- | --- |
| Casos correctos | 34 / 37 | 35 / 37 |
| TP / FP / FN | 27 / 0 / 3 | 28 / 0 / 2 |

**El cambio.** `small_red` (0,2 m a 10 m = 6 px de lado) es ahora observable y se detecta. No aparece ningún falso positivo nuevo.

**Siguen fallando, por diseño o por un límite conocido.** `cast_yellow_green`: un tinte verde fuerte saca el amarillo de su banda. `border_yellow`: una cartulina que toca el borde se marca ambigua.

**Lo que no queda resuelto.** Con estos parámetros, entre 0,15 y 0,2 m a 10 m **no es observable**, y el detector lo informa en `observability.unobservable_configured_range_m`. El suelo de 6 px es un supuesto declarado (±1 px por borde y un error relativo ≤ 1/3) para una cámara virtual. No demuestra que la detección física sea viable a 10 m: eso exige una cámara real calibrada y pruebas con imágenes reales.
