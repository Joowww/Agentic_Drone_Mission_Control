# Rover: unified protected review package - 07/11/2026

## Decision and scope

Package the current passive-session vertical work for one protected review. This is not approval to promote, start a simulator, or authorize a rover session. `PASSIVE_SCOPE_POLICY_ENABLED` remains `False`. No protected patch has been applied, no audit evidence changed, and no rover/SITL/Gazebo operation was run.

Protected patch base: `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1`, branch `feature/rover-sitl-first-motion`.
Unified code/schema/test patch: `2026-11-07-rover-protected-review.patch`, SHA-256 `361e0c9be3950fad9e7239c7ed70a3dcde4190f703d8d2567f5d7135ecef4208`.
Per-file baseline/proposed/current SHA-256 values for 27 patched files: `2026-11-07-rover-protected-review-hashes.json`. Checkpoints and index remain review sidecars, outside the source patch to avoid self-referential hashes.
The prior process-only patch is included in the unified patch and preserved separately at `2026-11-06-rover-passive-process-integration-review.patch`, SHA-256 `f54138c3222ccbcfbd4843ff9f5c9037c2ea35aad56454138cc961dfa13eed79`.

The unified patch was applied only to a temporary copy of HEAD to calculate proposed file hashes and verify that it applies cleanly to the stated base. It was not applied to the repository. The source worktree retains its local changes.

## Change classification

- **Protected runtime/source:** `tools/simulation_lifecycle.py`, `tools/rover_control.py`, `tools/rover_passive_scope.py`, `tools/rover_passive_phases.py`, `tools/rover_pipe_session.py`, `tools/rover_pipe_worker.py`, `schemas/rover-passive-session-v1.schema.json`.
- **Protected/source-coupled tests:** passive scope/start/phases/vertical integration, pipe worker/latency/watchdog, lifecycle stop, native review, reader-pin revision and the pinned Claude bridge contract. These test or constrain the protected runtime and travel with the same review.
- **Process ownership patch:** `sim_processes.py`, `start_sim_backend.sh`, `stop_sim_backend.sh`; preserved as an unapplied component of the unified review.
- **Documentation:** INDEX, scope/lifecycle checkpoint, SIGALRM follow-up and this package. These describe dated work; evidence directories and manifests remain untouched.
- **Evidence:** no new real evidence was generated. Existing `SHA256SUMS` entries in operations and simulation results were checked read-only.
- **Redundant changes:** none removed. All pre-existing local changes remain in the worktree.

Nothing is staged. No commit is made yet: the current code changes form one protected runtime change set, while the only independent new test reads a specifically pinned sibling worktree. Committing only fragments would make the review less coherent. The documentation and contract test can be committed separately after the package is accepted; protected runtime remains in the patch.

## Authorization mechanism assessment

| Option | Real guarantee | Cost / risk | Decision |
|---|---|---|---|
| Boolean or caller-supplied text | Indicates only what the caller asserted. No human identity, integrity, one-use consumption or revocation. | Minimal, but unsafe to call authenticated. | Reject as runtime proof; current static gate stays closed. |
| UID/GID, file mode 0600, process identity | Identifies the local account/process and limits other UIDs. It does not distinguish the LLM from Joel when both run under the same WSL UID. The same UID can edit its own approval file. | Low cost; strong only against different local accounts, not same-account automation or root. | Useful audit metadata, insufficient alone. |
| Separate executable plus TTY confirmation | A separately started prompt can require a human to inspect and approve the exact scope hash. TTY presence alone does not prove a human; a same-UID agent can launch or automate it. | Low-to-medium; needs careful handoff and exact displayed fields. | Good human-presence step, not a security boundary without protected ownership. |
| Persistent approval registry | Can enforce expiry, replay prevention, revocation and audit if writes are owned by a different principal and atomic. A user-writable JSON file can be forged or reset by that same user. | Medium; requires durable schema, locking, backup/restore rules and a separate writer identity. | Required capability, but only useful with an independent owner. |
| Dedicated approver account/service with narrow IPC and root-owned executable/store | Separates the LLM's UID from approval creation/consumption; can bind operator UID, exact scope hash, vehicle, expiry and nonce, and atomically revoke/consume records. Root can still override; it is a local administrative trust boundary, not cryptographic proof against root. | Medium-to-high; WSL account/sudo configuration, permissions, daemon or setuid helper, IPC protocol and recovery procedure. | Recommended minimum for this single-user research host, subject to confirming a non-sudo approver boundary. Do not implement its runtime until that boundary is present and reviewed. |
| TPM/Windows Hello backed signature | Can prove possession and, with user-presence signing, tie approval to a key and exact scope; revocation/key lifecycle are still needed. | High; hardware/API integration and WSL boundary are uncertain. | Stronger option, not assumed available or required for this TFG. |

The Claude worktree's `human_authorization.py` also labels its accepted source `TEST_FIXTURE`; its record digest is not a signature. It binds plan/scope/vehicle/validity well for offline tests but is not an operational identity provider. The bridge's `preconditions()` refuses missing/expired/mismatched records and the dry-run executor cannot act. This is a useful test contract, not runtime authentication.

**Recommended implementation boundary:** first establish a separately owned approver account/helper and protected approval ledger on the host; have an operator explicitly confirm the displayed scope SHA-256, vehicle, allowed operations and expiry outside the LLM process. Store one-use approval records with created/consumed/revoked states. Runtime verifies UID/owner, scope and vehicle hashes, expiry, boot/session binding and atomic consumption. A revoke command invalidates any unconsumed record. Keep the fixture as test-only. If the host cannot enforce a distinct approver principal, do not claim authentication; keep the gate closed and use a human-approved external signing/UI mechanism instead.

An offline reference provider is now included in the follow-up package; it deliberately cannot issue helper-backed production approvals because the host boundary has not been established. Offline fixtures already test ACTIVE/REVOKED, exact-scope and wrong-vehicle cases. The human decision needed is whether to provision a separate approver identity with no agent-accessible sudo and accept this local-admin threat model, or require a hardware-backed/external approver. This decision is separate from authorization to run SITL.

## Runtime event-to-receipt map and residual gaps

| Phase | Runtime source / effect | Test and status | Unresolved risk |
|---|---|---|---|
| START | `run_lifecycle(start)` performs protected recheck, claims the scope, records OPENING/STARTED and appends START after backend success. The test injects precheck, identity, inventory and backend. | Positive and uncertain-start tests; offline only. | Gate disabled; auth provider absent. |
| READY | Injected `ready` callback; runtime receipt accepts only armed=false, armable=true. No production callback is connected. | Synthetic phase callback. | Real READY/Armable evidence not acquired. |
| MotionBinding /2 | Injected `motion_binding`; identity, verdict, lifecycle, host/container boot, vehicle and GIDs checked. | Synthetic binding fixture. | No live reader call in this orchestrator. |
| Parameters | Injected read callback; required ROS/MAVLink values must be present/equal; writes=0. | Synthetic dictionaries; negative incomplete/mismatch cases. | Read provenance/transport callback is not wired to the session route. |
| Worker reservation/open | Lifecycle reserves one slot; `open_passive_session` consumes its token before spawn; owner/container/boot/deadline and GIDs checked. | Duplicate reservation and single-consumption tests; process spawn injected. | Actual worker process and token propagation are in protected review; backend marker patch unpromoted. |
| 100 observations | Injected capture returns records; count, no-command flags and digest are checked. | 100 synthetic rows; 99 rejected. | No live ROS capture. |
| Stationarity | Runtime calls existing `rover_stationarity.analyze` on exact capture and MotionBinding GIDs. | Synthetic stationary/invalid GID, stale odometry and drift. | No real stationarity measurement. |
| Worker close | Injected close callback; matching worker ID and confirmed close required; stationarity rerun. | Synthetic close; unknown closure remains incomplete. | Real worker close transport is not driven by this orchestrator. |
| STOP | Supervisor requests same-owner `run_lifecycle(stop)` in an independent thread; wait is capped at 15 s. Backend success is distinct from request; no reply is returned as UNCONFIRMED, without retry. | Delayed response test confirms unknown/no retry; success path uses fake backend. | No hard stop guarantee. A lock/backend/host hang can outlive the waiter; physical stop is not proven. |
| Final inventory | Existing protected lifecycle reads inventory and a fresh post-stop precheck; journal closes only after both succeed. | Injected inventory/precheck. | No current operational inventory/precheck. |

The sequence uses one durable lifecycle owner and an append-only-in-process receipt chain with scope digest, host/container identity, vehicle, monotonic timestamp, evidence and predecessor hash. It is not a signed audit log; a same-UID writer can alter local state. Missing phases produce `CLOSED_INCOMPLETE`; an uncertain START is retained and not replayed. The deadline limits new operations and requests protected STOP before expiry, but the 15-second wait is not a guarantee of process or physical termination.

## Reader pins and process patch

The active `tools/rover_control.py` SHA-256 is `5bb1238ee0f6e9b80f08e6bbdcb2f8e9484fd119d69b07cdbfd1022083cf3682`; its HEAD baseline and proposed digest are in the hash manifest. SIGALRM changes the tracked source and the reader revision test now detects the updated digest. No historical manifest was edited. A reader successor must explicitly carry the new source hash and retain the old sealed snapshot.

The process patch adds passive-session process markers, boot/session fencing at STOP, and a read-only `verify-empty` before `rover_only` START so that this profile does not run the historical broad cleanup. These changes are needed for exact ownership; they can signal container processes and therefore require dedicated unit tests for marker propagation, exact selection, foreign process refusal, boot mismatch, late child creation, rollback and container stop. They are not production-verified and are not applied. The unified patch is mechanically applicable to the declared base, but its effects still need protected review.

## Test/evidence record

- Latest Claude bridge contract is pinned to committed HEAD `8fed7dc39770c70eb599c9e41d17c9ede7bb52e8`; its bridge, authorization and frame-transform source hashes are checked. The combined focused run for vertical lifecycle, authorization, payload/executor handoff and Claude replay passed 36 tests, including helper-transport-unknown rejection, deadline races and per-case clocks.
- That contract test exposed that the Claude v2 adapter carries `authorization.bridge_scope_sha256`, while the local mission v2 schema rejected it. The unified review patch adds this optional SHA-256 field; the fixture test now verifies preservation and schema validity. This is a schema compatibility fix, not an operational authorization provider.
- Lifecycle, scope, phase, stop/start-close and recent-review targeted suites after the seven-failure fix: 111 passed.
- Earlier broad run before the latest tests: 2402 passed, 4 skipped, 0 failed in 572.33s. A subsequent targeted run exposed one more test-time freshness coupling within multi-case Claude tests; localization and transform timestamps are now tied to an explicit per-adaptation clock. Final broad rerun after these changes: **2424 passed, 4 skipped, 0 failed in 602.90s**.
- SHA256SUMS under `evaluation/operations` and `simulation/ros2_gazebo/results`: 112840 entries, zero mismatches, zero missing.
- JSON Schema parsing, Python AST validation, Bash syntax checks for the backend scripts, and `git diff --check -- tools schemas tests simulation` pass. The unified patch applies cleanly to an extracted copy of base `2e206f1`; no patch was applied to the source worktree. The legacy process component is preserved separately by hash and included in the review patch. Its process-marker/foreign-process behavior still needs dedicated tests before promotion.

No build, SITL, Gazebo, ROS transport, vehicle command or live precheck ran.

## Review, promotion, rollback and abort

Review all source/test files in the unified patch as one change, plus the hash manifest and the original process-only patch digest. Require reviewer decisions on: separate approver identity/revocation; receipt log integrity; event-provider wiring; reader successor for `rover_control.py`; process ownership and STOP; and the exact policy change that may enable the scope consumer. Do not change the gate in this worktree.

Promotion must use the repository's protected review/successor process, create a new versioned reader snapshot (never edit sealed evidence), run the full offline suite and integrity checks, then preserve the promotion record. If approval/auth design is rejected, leave the runtime changes unpromoted and the gate closed. If promotion fails partway, stop before START, retain the lifecycle restriction/evidence, and use the protected inspection/close route only when state is confirmed; never delete leases or force cleanup. Rollback after promotion requires an approved reverse successor and the same reader/hash review; do not reset or overwrite historical files.

Abort review/promotion if base/patch/hash differs, any pin or source snapshot is unknown, any test/schema/evidence check fails, approval is not independently attributable or revocable, precheck/resource/exclusivity becomes uncertain, or any worker/STOP result is UNKNOWN. No promotion decision authorizes a session.

## Next passive session proposal (not authorized)

1. Complete and approve the protected review above; keep gate false until the approved changes are installed and verified.
2. Verify all patch/source hashes, reader successor and unchanged historical manifests.
3. Run a new protected read-only precheck; require SATISFIED and current host/container/boot/resource/exclusivity identities.
4. Build a new `rover_only` scope from that precheck and calculate its canonical SHA-256.
5. Obtain a distinct human approval record for that exact scope hash, vehicle, operation list and expiry through the reviewed approver.
6. Immediately rerun protected precheck under the existing locks. Abort on any difference or uncertainty.
7. One protected START. Stop on UNCONFIRMED; never replay.
8. Acquire fresh MotionBinding /2; abort if identity/GID/phase timing fails.
9. Read parameters only; no writes; require provenance and matching values.
10. Open the one reserved PASSIVE worker; collect exactly 100 observations.
11. Validate stationarity from those same observations and GIDs.
12. Close worker and retain its actual close receipt.
13. Request same-owner protected STOP; record request, response and uncertainty separately.
14. Require final inventory and fresh precheck; otherwise preserve UNKNOWN/lease.
15. Preserve a new evidence directory and manifest. Do not overwrite 04/11 evidence.
16. This approval and session remain separate from any failsafe trial, ARM/GUIDED authorization or first-meter movement.

## Required human decisions

Before implementing an operational authorizer, decide whether a separate approver UID/helper without agent-accessible sudo is acceptable for this local TFG, or require external/hardware-backed signing. That decision authorizes only the authorizer design/protected review, not START.

Before any future SITL session, issue a separate explicit authorization for the new scope SHA-256 after receiving a fresh SATISFIED precheck, exact resources, allowed/prohibited operations, stop/abort conditions and remaining risks. No current hash has such authorization.

## Addendum — Codex v2 executor handoff, 07/11/2026

- `bridge_scope_sha256` is optional for backward-compatible `/2` payloads. The Claude source adapter verifies it from the canonical bridge request; Codex cannot recompute it without that original request, so it validates the digest form and binds any present value into the Codex authorization scope. Omitting it preserves the legacy digest.
- Codex is the sole site→navigation transform owner in `tools/rover_payload_executor_adapter.py`. The offline provider must match the payload's localization and identity; pretransformed coordinates and operational mode are refused. `_request()` validates the internal request; explicit admission remains separate and the operational gate is false.
- The current offline suite passed 2429 tests, 4 skipped, 0 failed. QGC adapter passed 4 tests; ArduPilot shell syntax and launch AST checks passed in the isolated rehearsal copy.
- The 27-file package remains unchanged at SHA-256 `361e0c9be3950fad9e7239c7ed70a3dcde4190f703d8d2567f5d7135ecef4208`, based on `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1`. No staging, commit, promotion, merge or push occurred. `git diff --check` is clean outside the preserved patch artifact, which has three trailing-whitespace lines; changing it would change its required hash.
- Protected review and runtime provider wiring are still prerequisites; this offline handoff does not authorize a passive or operational rover session.

## Addendum — verificación formal del paquete, 07/11/2026

- El paquete original `2026-11-07-rover-protected-review.patch` se conserva byte por byte con SHA-256 `361e0c9be3950fad9e7239c7ed70a3dcde4190f703d8d2567f5d7135ecef4208`, pero ya no representa cuatro archivos actuales: `tools/rover_mission_payload.py`, `tools/rover_payload_executor_adapter.py`, `tests/test_rover_claude_bridge_contract.py` y `tests/test_rover_payload_executor_adapter.py` cambiaron después de su generación. El manifest original registra esos hashes anteriores.
- Para la revisión humana se preparó, sin promoción, el patch actualizado `2026-11-07-rover-protected-review-current.patch`, SHA-256 `8a0d8ee572a4b57d92569266f51c8611b220db53e9f1fabab590ca2b824ed4e8`, y su manifest `2026-11-07-rover-protected-review-current-hashes.json`, SHA-256 `de36542fd3dc1013eea48a9e3fee88ef53b44e8bbe58d9cd337f979a2b6a596a`. Conserva los 27 paths y base `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1`; pasa `git apply --check` en copia limpia y `git apply --check --reverse` contra la copia propuesta.
- Los hashes del manifest actual coinciden para 24 archivos. Los tres cambios planificados de `sim_processes.py`, `start_sim_backend.sh` y `stop_sim_backend.sh` permanecen intencionadamente sin aplicar en el worktree fuente; sus bytes propuestos están incluidos y hasheados en el nuevo paquete.
- La revisión de reader no está completa: el snapshot preparado del 04/11 sigue `PREPARED_FOR_REVIEW_NOT_AUTHORIZED_NOT_APPLIED`; la plantilla de host es `PENDING_HUMAN_REVIEW_NOT_A_REVIEW`. Sus pins no coinciden con el paquete actual para `tools/rover_control.py` (pin `22d74f75e42f8d01964afd8dee5b067e935d75c4abf4be65c306c522cae16002`, propuesto `5bb1238ee0f6e9b80f08e6bbdcb2f8e9484fd119d69b07cdbfd1022083cf3682`) ni `tools/simulation_lifecycle.py` (pin `98e013b1c2f1468ad3023edaff21f2458099513c0bdb70b1fe76271d81190877`, propuesto `be56289a48a643ee3d3e31fb81ffed1152056ca733471497c4f6e76d2af0d36a`). El sucesor `PRESENT_RESOURCE_READER_SUCCESSOR_V1` actual permite únicamente las revisiones de pins documentadas en `historical_disposition.py`; no autoriza por sí mismo una sucesión de software para estos cambios.
- Sobre la copia exacta del paquete, los tests focalizados de lifecycle/perfiles/cleanup/identidad/adquisición/cierre/selección pasaron **231 tests**. Los tests existentes no mencionan `TFG_PASSIVE_SESSION_ID`, `select_passive_session_owned`, `TFG_PASSIVE_SESSION_BOOT_ID` ni `verify_empty`; la selección y el fence nuevos carecen de cobertura directa. La suite amplia previamente ejecutada sobre el worktree fue 2429 passed/4 skipped, pero no contenía esos tres cambios backend planificados y no debe atribuirse al paquete completo.
- No existe un comando del proyecto que promueva este patch de código: `historical_disposition apply-successor-reviewed` solo escribe un sucesor de auditoría diagnóstica y no debe usarse para instalar código. El paquete no se aplicó al worktree principal, no se stageó ni se commiteó. Ambos gates siguen falsos.
