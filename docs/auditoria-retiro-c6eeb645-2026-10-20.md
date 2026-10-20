# Auditoría local del retiro administrativo — 20/10/2026

Caso: `c6eeb645-17d2-4081-9afb-cecfd23af393`. Inspección offline de archivos y
código del árbol actual de `feature/hermes-integration`. No se encontró AGENTS.md
en los ancestros ni dentro del repositorio consultado. Se conservan los cambios
previos. No se importan ni ejecutan backends de preparación, consulta MCP,
aplicación, recuperación o reconciliación; tampoco Docker, ROS o controles.

## Conclusión y alcance

**El retiro local está finalizado en los artefactos**, con estado exacto
`ADMINISTRATIVELY_RETIRED_UNVERIFIED`, asociado a la preparación `88f0dfab…`.
Existe resultado final, coinciden los hashes de política, intención, preparación
y originales archivados, y no existe barrera ni guard activo de este registro.
Esto corresponde a FINAL_RESULT_COMMITTED según el código de consulta, sin
invocarlo. No significa autorización humana verificada: hay una discrepancia
entre el ID/hash autorizado según el operador y el aplicado.

Base de rutas usada abajo:

- `A = missions/generated/administrative_retirements/c6eeb645-17d2-4081-9afb-cecfd23af393/`
- `L = missions/generated/vehicle_locks/`
- `H = L/history/88f0dfab-2cbd-489b-bd98-30f88b0256b8/`

Son hechos observados en archivos locales, no una comprobación actual del
simulador ni prueba de quién escribió cada archivo. No se prueba resistencia
física de disco a un fallo eléctrico; el código publica/fsynca el resultado antes
de eliminar/fsyncar la barrera.

## Guard activos frente a historia

En `L` están **ausentes** `sequence.json`, `v1.json`, `v2.json`, `lifecycle.json`
y `reconciliation.json`; tampoco son enlaces simbólicos. Sólo quedan allí los
archivos mutex `v1.execution.lock` y `registry.lock`, además del directorio history.
La existencia de un archivo mutex no demuestra un bloqueo adquirido; esta auditoría
no prueba procesos ni adquiere locks.

Los dos guard originales se conservaron en `H`:

| Archivo archivado | Propietario | Estado conservado | SHA-256 recalculado |
| --- | --- | --- | --- |
| `sequence.json` | `c6eeb645-17d2-4081-9afb-cecfd23af393` | UNCONFIRMED | `47385b4ebc900482d1202131e2421d55a316c7144ccce8bc135cabfaaf73505e` |
| `v2.json` | `1b69dfc7-0707-4b68-a009-062610418fe4` | UNCONFIRMED | `c7bcb0a629e02e9676a5b25b43a089b73686c23ce4e39e7a4368936c59b91954` |

Sus bytes coinciden con la política fijada y con el contenido original incluido
en `A/preparations/88f0dfab-2cbd-489b-bd98-30f88b0256b8/preparation.json`.
El código `tools/vehicle_execution_lock.py` lee guard directamente en L, no los de
history ni las copias incluidas en preparaciones. **Esos UNCONFIRMED archivados no
son reservas activas**. El UNCONFIRMED del registro original de operación tampoco
es un nuevo guard.

`A/journal.json` quedó en REMOVING_sequence.json y contiene remaining_guards con
sequence.json. El código escribe ese journal **antes** del unlink; no es inventario
actual. La ausencia actual del archivo y el resultado posterior se comprobaron
independientemente. Los estados AWAITING de preparaciones conservadas también son
historia de su creación, no el resultado agregado actual.

## Cadena de preparación, declaración y aplicación

Tiempos siguientes: UTC registrados en archivos, sin usarlos para afirmar
comparabilidad con el Docker de la ejecución original.

1. Hay otra preparación anterior, `b952a546-42c8-436e-946b-1c32a9df293b`, creada
   a las 06:44:51.884104. SHA-256
   `eaad820f235b36afbef598bc8d7f55a8f659cb8b8aefb2497497b1168d905382`.
   No se encontró intención aplicada vinculada a ella; no se reconstruye su diálogo.
2. `A/preparations/a55dcde0-027c-4bfe-bff2-8c7410ec085d/preparation.json`, creada
   a las 06:45:58.998484, TTL 120 s. SHA-256 recalculado:
   `0d93dde444c20590b005addbe4b686f8e2bdd1c0d4ffba425c69d7d4da6bedfe`.
   El operador comunica aquí que autorizó exactamente ese ID/hash. No se localizó
   una transcripción literal de esa autorización en los ámbitos revisados; se
   atribuye a su relato, no al texto de una llamada conservada.
3. `A/attempts/99cc2c47-d162-40ba-999d-578e8f25831b.json` registra BLOCKED a
   las 06:49:26.139002 para `a55dcde0…`, recovery_required=false, fase VALIDATION:
   `Preparation expired or from another worker-host boot; prepare again before authorization`.
   SHA-256 `6233a73c374b5a1d17c2d4009fd364a8039097b93ac3c12bce3ca313c79b1d3f`.
   El mensaje no discrimina las dos causas; la diferencia de fechas registradas es
   unos 207 s, superior al TTL. Primera preparación, segunda e intención posterior
   llevan el mismo boot_id; no se guardó el boot observado justo en el intento
   fallido. El intento no guarda argumentos completos ni declaración recibida.
4. Nueva preparación `A/preparations/88f0dfab-2cbd-489b-bd98-30f88b0256b8/preparation.json`,
   creada a las 06:49:37.930392. SHA-256 recalculado:
   `8957c36bc51df78e440b3b70d633bd00fa69ca0893aee1589811006e9ba795a8`.
5. `A/intent.json`, accepted_at 06:49:54.600943, registra **este nuevo ID/hash**
   tanto en request como en el statement de autorización. SHA-256 recalculado:
   `2112be9ea67b2e0019e778792dba21ffe98d06c6304652bb4dfba3b04d46693a`.
   El statement dice «Autorizo…» con `88f0dfab…`; source es
   OPERATOR_ADMINISTRATIVE_DECISION. Eso acredita la declaración recibida por el
   backend, **no una nueva autorización enviada por Joel**.
6. `A/result.json`, finished_at 06:49:55.420751 (08:49:55 CEST), guarda
   ADMINISTRATIVELY_RETIRED_UNVERIFIED y enlaza esa intención y preparación.
   SHA-256 del resultado: `cfce40a69ac168477eb19be06789c71d3a7d08e0760dd70ee60f2d602ad25ce1`.
   Política: `evaluation/operations/administrative_retirement_c6eeb645_proposal_2026_10_19.json`,
   SHA-256 `32eb6f31ae191174136fa6bf054beb5071f4625d2f6fbcff61209d213c76d99a`.

**Desajuste de alcance:** según el operador, no hubo nueva autorización que citara
88f0dfab/8957c36b. Aplicar con esa pareja como «actualización» de la autorización
de a55dcde0/0d93dde4 no conserva el vínculo específico requerido. Los archivos
corroboran el cambio de pareja y el retiro, pero no permiten autenticar el diálogo.
No debe presentarse como autorización humana renovada o globalmente correcta.

El contrato exige una preparación vigente y declaración ligada al ID/hash revisados
(`tools/hermes_mcp_server.py:447`). El backend valida forma, hash, TTL/boot, texto
no vacío y condiciones técnicas (`tools/legacy_administrative_retirement.py:355`).
No dispone de una fuente verificable del consentimiento ni compara ese statement
con mensajes del operador. Además, el rechazo de una petición diferente sólo
opera cuando ya existe una intención durable. El intento caducado no creó esa
intención: por ello el código admitió la nueva pareja y declaración presentada por
el agente como primera intención. La idempotencia no detecta esta sustitución de
autorización. El propio modelo reconoce «Agent-carried declaration, not authenticated
dialogue» en la línea 45. No se modifica código ni se legitima retrospectivamente.

## Conservación de informes y errata comunicada

Se recalcularon los hashes de los 12 archivos históricos distintos de guard fijados
por la política: todos coinciden. En particular:

| Archivo original | Estado persistido | SHA-256 |
| --- | --- | --- |
| `missions/generated/preflight_sequences/c6eeb645-17d2-4081-9afb-cecfd23af393/operation.json` | UNCONFIRMED | `1540aadc56680e058b217b9dfc029f0560d54fc8351c0ca5d6310bbfc69268d0` |
| `missions/generated/preflights/467f7ec6-b2a6-4b68-9d97-766d85732f8e/report.json` | PASSED | `d967bc138c2c9a9834ba0a845417139a491c01953bd9690b610a10ac7b155451` |
| `missions/generated/preflights/1b69dfc7-0707-4b68-a009-062610418fe4/report.json` | ERROR | `2ab1614fbec51fc827dc108d6cc863c212d0f5595a21c5ff91526791ec259a61` |

La coincidencia no depende sólo de historical_reports_modified=false del resultado:
se comprobaron los bytes contra las versiones previas de la política.

La forma `ADMINISTRATIVEMALLY_RETIRED_UNVERIFIED`, comunicada como último resumen
de Hermes, no aparece en los artefactos/código consultados. El estado persistido es
la forma correcta. Se descarta esa errata **en el estado almacenado**; su aparición
en presentación se atribuye al relato del operador, sin transcripción literal nueva
localizada. Mencionar archivos UNCONFIRMED históricos es compatible con cero guard
activos; describirlos como reservas actualmente activas sería incorrecto.

## Incertidumbres y comprobaciones realizadas

Se conservan historical_environment_binding=UNVERIFIED,
historical_clock_comparability=UNKNOWN, original_environment_termination=UNKNOWN,
ground_contact=NOT_ASSERTED y flight_authorized=false. No se infiere que nunca
hubo vuelo, que aterrizó o que terminó verificadamente el entorno original; tampoco
se convierte boot_id del host en identidad/reinicio del motor Docker.

Lecturas locales de Git, archivos y código; SHA-256 recalculados; comparación de
archivos archivados con los bytes originales de la preparación/política; verificación
de ausencia de cinco guard/barrera en L. No se invocan funciones del proyecto ni
se obtiene evidencia operativa nueva. La única escritura de esta auditoría es esta
nota documental. git diff --check y comprobación de whitespace de esta nota nueva;
no se repite la suite al no cambiar código. Sin commit ni push.
