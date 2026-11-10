# Diagnóstico Opik de un solo batch — HTTP 204 (21/10/2026)

Un único POST autorizado por Joel, ejecutado por Joel en su terminal con
`opik_diag_send_once.sh`. La clave se leyó por TTY y no se guardó en ningún sitio. Preparación,
entrada y comando: [opik_diag_single_batch_2026_10_21](../opik_diag_single_batch_2026_10_21/README.md).
Es el segundo y último POST a Opik hasta la fecha; el primero está en
[opik_first_synthetic_send_2026_10_21](../opik_first_synthetic_send_2026_10_21/) y no se ha modificado.

## Hechos (de `send_report.json` y `send_record.jsonl`)

| Dato | Valor |
| --- | --- |
| Destino | workspace `joowww`, proyecto `tfg-opik-synthetic-20261021`, `https://www.comet.com/opik/api` |
| Autorización de procedencia | `--allow-synthetic` (sin `--allow-unknown-provenance`) |
| Entrada | `input.jsonl` de la preparación, SHA-256 `2edb5048fb16968f7876922c54d80bb1f780a32e33d773b08d9e125d66d21eb5` |
| Batch | 1 de 1: `POST /v1/private/traces/batch`, 1 traza, 0 spans |
| Body | 2112 bytes, SHA-256 `0782b93d3d98b7c1a39067d3a7a462429b658fdd3db7104250c83156b11a99c0`, idéntico al autorizado |
| Traza | `01a15fe1-153f-75cb-9eee-0bea00feb2b1`, «SYNTHETIC · [interval unknown] hermes_turn», 2026-10-21T19:12:28.991015Z (inicio = fin) |
| Respuesta | **HTTP 204**, 0 bytes de cuerpo, 1,077 s; enviado a las 19:36:43 UTC |
| Estado | `ALL_BATCHES_HTTP_ACCEPTED`, `record_complete: true`, rc=0, `send.stderr` vacío |
| Cuerpo de error | No hacía falta (`not_needed_no_non_2xx_response`); el directorio privado quedó vacío |

**El 204 por sí solo no confirmaba que Opik hubiera almacenado la traza.** La confirmación viene
aparte, de la comprobación del operador en la interfaz (sección siguiente).

## Qué se puede concluir

- **Hecho:** con el mismo endpoint, workspace, proyecto, mecanismo de clave, cabeceras y código de
  construcción de peticiones, una traza mínima recibió 204. Por tanto, el destino y la autenticación
  aceptan peticiones de este exportador.
- **Hecho:** la traza rechazada el 21/10 (HTTP 400) y esta tienen **la misma estructura**: las
  mismas claves de primer nivel y las mismas 18 claves de `metadata`. Difieren en los valores:

  | | Rechazada (400) | Aceptada (204) |
  | --- | --- | --- |
  | Intervalo | 73,99 h | 0 |
  | Antigüedad del inicio al enviar | unas 100,6 h | unas 0,4 h |
  | Spans | 3 (sin enviar) | 0 |
  | Etiquetas | 3 | 5 |
  | Nombre | `hermes_turn` | `[interval unknown] hermes_turn` |

- **Hipótesis principal, sin confirmar:** el 400 se debió a los **valores temporales** de la traza
  original, es decir, el intervalo de unas 74 h (el artefacto conocido del fixture) o el inicio de
  hace más de 4 días. El servidor no dio ninguna explicación que podamos consultar: el cuerpo de
  aquel 400 se descartó. Este diagnóstico no distingue entre duración y antigüedad, ni descarta
  otros valores.
- **No se ha encontrado ningún defecto del exportador.** No se cambia código.

## Comprobación en la interfaz — CONFIRMADA por el operador

Hay dos evidencias distintas, y ninguna sustituye a la otra:

| Evidencia | Fuente | Qué acredita |
| --- | --- | --- |
| HTTP 204 | `send_report.json` y `send_record.jsonl`, generados por el exportador en el momento del envío (19:36:44 UTC) | Que Opik aceptó la petición. No acredita que la almacenara |
| Traza visible en la interfaz | **Declaración de Joel como operador**, comunicada el 21/10/2026 hacia las 19:41 UTC | Que la traza del diagnóstico aparece en la interfaz de Opik |

- Lo confirmado por el operador es literalmente que **la traza del diagnóstico aparece en la
  interfaz** del proyecto `tfg-opik-synthetic-20261021`.
- **No se registró** qué campos concretos comprobó: nombre, etiquetas, ausencia de spans o metadata.
  Los puntos de la lista siguiente quedan como guía, no como verificados uno a uno.
- **No hay captura de pantalla ni exportación** de la interfaz en esta carpeta. La confirmación es
  una declaración humana, no un artefacto con hash, y no la ha comprobado ningún otro proceso.
- No se ha confirmado aquí si aparece o no la traza del 400 (`01a14a34-…`).

Guía usada para la comprobación:

1. Abrir el workspace `joowww` → proyecto `tfg-opik-synthetic-20261021` → Traces.
2. Ampliar el filtro de tiempo para incluir el 21/10/2026 sobre las 19:12 UTC (21:12, hora local
   CEST), o buscar por el id `01a15fe1-153f-75cb-9eee-0bea00feb2b1`.
3. Debe aparecer **una** traza:
   - nombre «SYNTHETIC · [interval unknown] hermes_turn»;
   - etiquetas `tfg-hermes-capture`, `schema:tfg.hermes.capture/3`, `synthetic`, `interval-unknown`
     y `latency-not-measured`;
   - sin spans, sin input ni output, y con duración 0 o vacía;
   - en metadata, `tfg_data_kind=synthetic_fixture` y un `tfg_point_events` con `tfg.tool_call`.
4. Comprobar que **no** aparece ninguna traza `01a14a34-…`, la del 400. No consta como comprobado.
5. Resultado anotado arriba: traza visible, según el operador.

## Archivos

`SHA256SUMS` contiene los hashes de los cuatro archivos del envío. No incluye este README, que se
actualizó después para anotar la confirmación del operador; los cuatro archivos originales no han
cambiado y el manifiesto sigue verificando.

- `send_report.json`: `6dc92df284401e1633ee77840f859b259e9eab85673e60d66b315f7033dda0d5`
- `send_record.jsonl`: `0b9c864ce9a860df4d248503320a91c02d30d70bfc3902b5d8bb6427f20a575b`
- `send.stderr`, vacío: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `send.rc` (`0`): `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa`

Ninguno contiene la clave. No se generó cuerpo de error. El directorio privado
`~/opik-diag-private-20261021/` está fuera del repo, vacío, y no forma parte de la evidencia.

## Siguiente paso posible (no autorizado)

Para separar las dos hipótesis haría falta otro POST, que requeriría autorización aparte. Por
ejemplo: una traza con el mismo inicio antiguo pero sin el intervalo de 74 h, o al revés, cada una
con `--error-body-file`. No se prepara ni se ejecuta aquí.
