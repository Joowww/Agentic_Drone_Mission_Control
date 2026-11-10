# Diagnóstico Opik de un solo batch — PREPARADO, NO ENVIADO (21/10/2026)

Preparación offline tras el HTTP 400 del
[primer intento](../opik_first_synthetic_send_2026_10_21/), cuyo cuerpo de respuesta se descartó.
No se ha contactado con Opik, no se ha leído ninguna clave y no existe ningún registro de envío.

## Condición previa (sin cumplir todavía)

**Joel debe confirmar en la interfaz que el proyecto `tfg-opik-synthetic-20261021` existe en el
workspace `joowww`** (URL `comet.com/opik/joowww/…`). Si no existe, este diagnóstico **no se usa**:
primero hay que crear o confirmar el proyecto en la interfaz, sin enviar nada.

Se mantiene el mismo workspace y proyecto que en el primer intento y **sólo cambia el contenido**.
Así un resultado distinto se puede atribuir a la entrada y no al destino.

## Contenido

| Archivo | Qué es | SHA-256 |
| --- | --- | --- |
| `input.jsonl` | 1 evento `tool_call` sintético nuevo, sin turno (`run_id`/`case_id` con marca `SYNTHETIC`), generado con `capture.tool_call_event` y un entorno explícito | `2edb5048fb16968f7876922c54d80bb1f780a32e33d773b08d9e125d66d21eb5` |
| `dry_run.json` | Dry-run offline con `--include-untimed`, entorno vacío y sockets bloqueados | (no se envía) |

Resultado del dry-run:

- destino `joowww` / `tfg-opik-synthetic-20261021`;
- **1 traza y 0 spans**, es decir, un único body en `traces_batches` y ninguno en `spans_batches`;
- body de 2112 bytes, SHA-256 `0782b93d3d98b7c1a39067d3a7a462429b658fdd3db7104250c83156b11a99c0`
  (JSON compacto, el mismo cálculo que `--record`);
- traza `01a15fe1-153f-75cb-9eee-0bea00feb2b1`, distinta de la del primer intento;
- nombre «SYNTHETIC · [interval unknown] hermes_turn»;
- `start_time = end_time = 2026-10-21T19:12:28.991015Z`, sin el artefacto de 74 h;
- etiquetas `synthetic`, `interval-unknown` y `latency-not-measured`;
- bloqueo por defecto: sintético, así que hace falta `--allow-synthetic`.

## Comando futuro — NO EJECUTADO

Sólo tras cumplirse la condición previa y con una **autorización aparte y de un solo uso** que
nombre el destino, los dos SHA-256 de arriba, `--allow-synthetic` y las dos rutas. Se ejecuta en la
terminal de Joel. El cuerpo de error queda **fuera del repo**.

Antes de este bloque, Joel tiene que haber confirmado **en la interfaz** que el proyecto existe en
`joowww`. El comando no puede comprobarlo. Si no está confirmado, no se ejecuta nada y no se
prepara ningún otro POST.

```bash
cd /home/joelm/TFG/Agentic_Drone_Mission_Control || exit 1
D=evaluation/observability/opik_diag_single_batch_2026_10_21
echo "2edb5048fb16968f7876922c54d80bb1f780a32e33d773b08d9e125d66d21eb5  $D/input.jsonl" | sha256sum -c - || exit 1
.venv/bin/python -m observability.opik_export "$D/input.jsonl" --project tfg-opik-synthetic-20261021 \
  --workspace joowww --provenance synthetic --include-untimed \
  | .venv/bin/python -I -c "import hashlib,json,sys; p=json.load(sys.stdin)['payload']; h=[hashlib.sha256(json.dumps(b,ensure_ascii=False,separators=(',',':')).encode()).hexdigest() for b in p['traces_batches']]; ok=(h==['0782b93d3d98b7c1a39067d3a7a462429b658fdd3db7104250c83156b11a99c0'] and not p['spans_batches']); print('body check:', 'OK' if ok else 'MISMATCH'); sys.exit(0 if ok else 1)" \
  || exit 1
[ ! -e "$D/send_record.jsonl" ] || { echo "STOP: record exists"; exit 1; }
mkdir -m 700 ~/opik-diag-private-20261021 || exit 1   # falla si ya existe
read -rs -p "OPIK_API_KEY (hidden): " OPIK_API_KEY; echo; export OPIK_API_KEY
.venv/bin/python -m observability.opik_export "$D/input.jsonl" \
  --project tfg-opik-synthetic-20261021 --workspace joowww \
  --provenance synthetic --include-untimed --allow-synthetic \
  --send --record "$D/send_record.jsonl" --timeout 30 \
  --error-body-file ~/opik-diag-private-20261021/error-body.bin \
  > "$D/send_report.json" 2> "$D/send.stderr"; echo "$?" > "$D/send.rc"
unset OPIK_API_KEY
```

El bloque comprueba el SHA-256 de la entrada y, con un dry-run, que el body es exactamente el de
arriba y que no hay spans. Lo hace antes de crear nada o leer la clave, y si algo no coincide se
detiene. Usa `exit 1`, así que debe pegarse en una shell nueva o guardarse como script, para que
un fallo no cierre la sesión actual. No hay reintento: con cualquier resultado distinto de 2xx, el
análisis es offline.

Si el servidor responde sin 2xx, el exportador hace **una única lectura acotada** del cuerpo (como
mucho 4097 bytes) y guarda como mucho 4096 en `error-body.bin`. El informe dice cuántos bytes se
capturaron y si se truncó. Sólo da el tamaño total cuando la lectura terminó antes del límite; si
no, `response_body_bytes` es `null`.

## Qué se puede concluir

- **2xx (`ALL_BATCHES_HTTP_ACCEPTED`):**
  - el endpoint, las cabeceras, la clave y el workspace aceptan una traza de este exportador;
  - el 400 anterior apunta a algo del **contenido** de aquella traza, como el intervalo de 74 h, el
    inicio unas 100 h antes del envío o la metadata, pero no identifica cuál;
  - un 2xx **no** prueba que se haya almacenado: hay que verla en la interfaz;
  - tampoco valida el envío de spans, que este diagnóstico no incluye.
- **400 otra vez:**
  - con el destino igual y un contenido mínimo distinto, gana fuerza una causa de **destino o
    petición** (workspace, proyecto, clave o cabeceras) o una regla que afecte a cualquier traza;
  - el cuerpo guardado en `error-body.bin`, revisado localmente, debería concretarlo;
  - sin ese cuerpo, la causa sigue sin conocerse.
- **Otro código, timeout o fallo de transporte:** el resultado es incierto y no aporta información
  sobre el 400.

En la interfaz, tras un 2xx, debe aparecer en `joowww` → `tfg-opik-synthetic-20261021` una traza
con el id de arriba, fechada el 21/10/2026 a las 19:12:28 UTC, con las etiquetas `synthetic` e
`interval-unknown` y sin spans. Tras un 400, no debe aparecer nada nuevo. El archivo
`error-body.bin` contiene texto arbitrario del servidor: hay que revisarlo localmente, no añadirlo a
Git y no compartirlo sin inspección.
