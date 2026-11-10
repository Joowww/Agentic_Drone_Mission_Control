# OP-1 (2026-11-06): attempted once, REJECTED by Opik (HTTP 400), nothing stored

Authorized by Joel on 2026-11-06: only OP-1, the 10 pending qwen3:4b pilot traces (E01 E04 E11 E12 E18 E19 E20 E21
E22 E27, E07 excluded), traces/batch `0ce48bc0…a058b00`, spans/batch `5399a701…1bb1e92a`, one attempt per batch.

| Step | Result |
| --- | --- |
| Preflight (13 checks: seal, exact hashes, destination, cases, E07 excluded, correspondence with the sealed pilot, ledger, egress, privacy, content, remote project, traces absent) | all PASS (`preflight.json`) |
| traces/batch, 10 traces, 33 420 B, sha `0ce48bc0…` | **HTTP 400** (181-byte body, not captured) |
| spans/batch | **not attempted** (the sender stops at the first non-2xx) |
| Read-only GET of each of the 10 trace ids, minutes later | **404 for all ten**: nothing stored |
| Ledger | the 10 ids are `UNCERTAIN` with `post_failure_readback` 404 and `diagnosis`; E07 unchanged, `VERIFIED_PRESENT` |
| Resend | **none** |

Inferred cause (NOT confirmed: the error body was not kept): Opik rejects UUIDv7 ids whose embedded time is more
than its ingestion window (default 24 h) old (`uuidValidation` in comet-ml/opik@df61dd21c66e
`apps/opik-backend/config.yml`, `IdGenerator.validateId`, `InvalidUUIDExceptionMapper` -> 400 "Invalid UUID for
id"). The ids embed the historical start times (2026-11-04T16:39–16:42Z); the batch went out at 10:30Z on
2026-11-06, ~42 h later. E07 (id time 16:40Z) was accepted at 18:36Z the same day (~2 h).

Consequence: these ten ids can never be accepted. The exporter now refuses out-of-window ids before connecting and
can re-stamp only the id time (`id_epoch`, OP-1b); that changes the bodies and needs a NEW authorization.

Files: `preflight.json`, `send_result.json`; send record `../send_OP1_20261106T103041Z.jsonl` (sha256 `759dca9d263dfdfd3b27774240275b02da02d274ae3d8d89ba7954c432621bd8`).

Provenance of the code: the preflight and the send were run from HEAD `21b1f99de` plus a first, uncommitted version
of `multiagent/opik_op1.py` (the same 13 checks, without `id_window`, without error-body capture). The committed
version adds the `id_window` check, OP-1b (`id_epoch`) and error-body capture; the bridge gained the window guard,
`id_epoch`, case-level duplicate protection and `supersedes` after the attempt.
