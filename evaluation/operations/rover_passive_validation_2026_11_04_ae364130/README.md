# Sesion pasiva rover_only - evidencia conservada

- Origen: copia byte a byte de /tmp/tfg_rover_passive_ae364130_20261104, realizada el 06/11/2026. El original temporal no se modifico ni elimino.
- Fecha de ejecucion: 04/11/2026 UTC; START 19:11:15, STOP 19:21:12-19:21:25.
- Scope autorizado: ae3641305dc508a70ef9be53bc66c2ec2721bfd56ccd4d4a0c3c6a66f521c2f2.
- Lifecycle START: 2c09bd73-865a-4d25-9e8d-b55f1df29d79, SUCCESS/FINISHED.
- Lifecycle STOP: bcdf3cdd-bc51-4d5f-bc2e-9a1d5dea6899, SUCCESS/FINISHED.
- MotionBinding /2: ACCREDITED_FOR_SESSION; 5 muestras, GID estables y edad final de odometria 21.7 ms.
- Sesion PASSIVE: 100/100 observaciones, todas armed=false, commands_sent=0; worker cerrado sin incertidumbre.
- Metricas: p50/p95/p99 de observe 0.809/0.898/0.960 s; p99 de overhead 2.73 ms; RTF independiente 0.5343; odometria 50 Hz simulados y status 1.98 Hz simulados.
- Parametros: lectura READ_DIAGNOSTIC_SERVER_INSTANCE_UNVERIFIED, no operativamente acreditada. Destacan GUID_TIMEOUT=3.0 y ATC_DECEL_MAX=0.0.
- Resultado final: STOP confirmado; precheck final BLOCKED, RELEVANT_LOCAL_ENDPOINT_OCCUPIED. El inventario observo TCP 127.0.0.1:5780 -> 127.0.0.1:34960, estado 0x06, sin propietario identificado.
- Limitaciones: no se conservaron posicion/velocidad por cada observacion; no queda acreditada estacionariedad durante la ventana. Ningun resultado autoriza movimiento ni demuestra frenada fisica.
- Manifiesto original: manifest.json, 24 archivos; SHA-256 c82f52f5baa5e376ec13ad36f428f9e73edb7e4db7dfd04bfdd547783fa5d408. Se verificaron los 24 hashes antes de copiar. SHA256SUMS cubre la copia y este README.

El estado BLOCKED, los datos diagnosticos y las limitaciones son parte de esta evidencia; no se han completado ni reinterpretado datos ausentes.
