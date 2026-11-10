# Traspaso del rover a través del código real de Codex (offline, dry-run): 07/11/2026, `0c886b624`

**Cómo se genera:** `python -m multiagent.rover_handoff --evidence <dir> --snapshot <dir>`.

**Qué código se ejecuta.**
- El nuestro: puente, coordinador, autorización y marcos.
- El de **Codex**, sin copiarlo ni imitarlo:
  - el adaptador y el validador v2;
  - la comprobación de la solicitud `ROVER_NAVIGATE_V1` de su executor;
  - la admisión de su executor.

  Se lee de un *snapshot* inmutable (`git archive`) del commit `57a0e303a`, cuyos archivos de contrato son idénticos a los de `1514053da` (los sha256 están en `summary.json`), y se ejecuta en un proceso aislado. Su worktree no se usa.

**Qué se sustituye.** Solo la operación protegida: la admisión se llama con la política tal como está confirmada (`OPERATIONAL_ROVER_ENABLED = False`) y sin declaración de SITL, así que devuelve `BLOCKED` antes de tocar ningún archivo. Después, nuestro adaptador dry-run rechaza la ejecución.

## Resultados

Los 18 casos clasifican como se esperaba, y **ningún caso produce un comando**.

**Plan histórico de M4c-r1** (sellado, solo lectura): `BLOCKED_BEFORE_SUBMISSION`, por estos motivos:
- ningún humano ha fijado velocidad ni tiempo máximo;
- no hay registro de autorización;
- no hay localización acreditada ni grafo de marcos;
- la política del executor está desactivada.

**Caso sintético completo** (todo `TEST_FIXTURE`: rover, pose, transformación acreditada solo dentro del *fixture*, límites, autorización y recibo): supera todas nuestras etapas y el v2 de Codex (`READY_TO_SUBMIT`).
- El executor de Codex **valida** la solicitud de navegación: objetivo en `odom` en (5,5, −7,0), comprobado en forma cerrada, con `IDENTITY_SAME_ACCREDITED_FRAME`.
- Después se detiene en `OPERATIONAL_ROVER_POLICY_DISABLED`.
- La discrepancia de esquema de Codex queda registrada en `schema_errors`.

**16 casos negativos**, cada uno con su causa: scope incorrecto, otro vehículo, sin autorización, autorización caducada, objetivo caducado, dependencia aérea perdida, observación rechazada, misión cancelada, rover sin posición, marco incompatible, sin transformación, transformación caducada, sin velocidad ni duración, sin recibo de operador, sin parámetros del executor y *fixture* en modo operativo.

**Qué no demuestra.** Esto prueba conexiones de software, no una aprobación humana ni una ejecución. Ningún *fixture* sirve en modo `OPERATIONAL`.
