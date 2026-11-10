# Captura pasiva: observaciones descriptivas

Estado: `ANALYZED` (`movement_authorized: false`, `source_association_verified: false`).

## Verificación

- Manifiesto del ensayo: `a88a09f9cfcce654709a6524eb30da3867408e8c48b8e7631dd7b8c7d9bdf8a5` (todos los archivos listados: tamaño y SHA-256)
- Diario: `13811afdfe8b20b71e3b5f1ff595c546ebdc5ff5c4919ef77424216d679a3f18`, esquema `tfg.rover.passive-capture/3`
- Footer del colector `capture_complete`: `null` (el colector nunca se autocertifica)
- Recibo externo `capture_complete`: `true`
- Retorno: `0`; datos en ambos streams: `true`; terminación `SAMPLE_LIMIT`
- stderr: 0 bytes (`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`)

- Muestras por topic: `/ap/v3/status` 1, `/rover1/odometry` 19

## Selección

- best_effort KeepLast(5) subscription; dropped messages are not counted
- one callback handled per spin, with a graph query per sample
- termination SAMPLE_LIMIT
- máximo de muestras 20, política `RESERVE_BOTH_STREAMS`

## Fuente 1

- GID `010feb7d3c06f84c00000000000014030000000000000000`, rmw `rmw_fastrtps_cpp`
- Marcos: `odom` → `base_link`
- Muestras retenidas 19; completas con campos 19; incompletas 0; con no finitos 0
- Posición x (m): -0.0012413615 a -0.0012346256 (media -0.001238382; desv. típ. 2.1042054e-06; n=19)
- Posición y (m): -3.000424 a -3.0004044 (media -3.0004141; desv. típ. 6.0850763e-06; n=19)
- Posición z (m): 0.094914698 a 0.094928177 (media 0.094920519; desv. típ. 4.1699812e-06; n=19)
- Cuaternión x: -0.00336347 a -0.0033588 (media -0.00336155; desv. típ. 1.42545e-06; n=19)
- Cuaternión y: 0.00337261 a 0.00337714 (media 0.00337528; desv. típ. 1.383e-06; n=19)
- Cuaternión z: 0.705674 a 0.705675 (media 0.705675; desv. típ. 1.99538e-07; n=19)
- Cuaternión w: 0.70852 a 0.70852 (media 0.70852; desv. típ. 2.11779e-07; n=19)
- roll (°, conversión del cuaternión recibido): 9.0788e-06 a 2.1988e-05 (media 1.4172e-05; desv. típ. 3.7476e-06; n=19)
- pitch (°, conversión del cuaternión recibido): 0.54544 a 0.54618 (media 0.54588; desv. típ. 0.00022756; n=19)
- yaw (°, conversión del cuaternión recibido): 89.769 a 89.77 (media 89.769; desv. típ. 3.3309e-05; n=19)
- Norma de velocidad lineal (m/s): 0 a 0.0001561 (media 9.673e-05; desv. típ. 5.913e-05; n=19)
- Norma de velocidad angular (rad/s): 0 a 0 (media 0; desv. típ. 0; n=19)
- Covarianzas declaradas todas cero: 38 matrices; diagonal 0 a 0 (media 0; desv. típ. 0; n=228) (cero declarado **no** es certeza)
- Sellos de cabecera (reloj del mensaje): intervalo mediano 20 ms, cubren 0.36 s; repeticiones o regresiones 0
- Recepción (reloj monotónico): intervalo mediano 107.1 ms, máximo 4504.9 ms, cubre 18.64 s

## Límites

- retained samples only; the complete stream's rate, loss and jitter are NOT inferable
- header-stamp and receipt intervals differ in meaning (message clock vs steady receipt); their difference is not attributed to any cause and yields no real-time factor
- positions/velocities in the message's own frames; frames and units NOT validated
- declared covariance zero is not certainty
- small reported speeds come from the same source and are not independent proof of physical rest
- no identity, model, transformation, stop or arrival

## Contrastable con la propuesta de R1 (no aprueba nada)

- `arrival_tolerance_m`: position dispersion at rest per group (compare with the proposed tolerance)
- `stopped_linear_mps / stopped_angular_rad_s`: residual speeds at rest (compare with the stop thresholds)
- `max_sample_gap_s`: receipt intervals of RETAINED samples (a lower bound on gaps, not the stream's loss)

## Requiere un diseño más amplio

- complete-stream rate, loss and jitter (the collector is selective and capped at 20 samples in reserve mode)
- dispersion during motion and at the target, progress and dwell (need a movement trial)
- frame transformation and physical identity (need the three-vehicle check and the identity chain)
- any threshold approval: 20 samples of one session are not a basis for approving R1 parameters
