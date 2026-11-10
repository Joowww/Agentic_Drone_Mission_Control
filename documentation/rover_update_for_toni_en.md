# Rover integration update — 7 November 2026

## Status

The passive Rover lifecycle has a complete offline vertical test with ten phases, one PASSIVE worker, 100 synthetic observations, zero commands, a simulated protected STOP, and a CLOSED result. The final Rover/lifecycle offline suite passed **2,424 tests, skipped 4, and failed 0** in 602.90 s. Historical evidence manifests were rechecked: 112,840 entries, with no missing files or hash mismatches.

## Authorization boundary

An offline reference provider models exact-scope approval, expiry, revocation, single use, replay rejection, concurrent consumption, process restart, and ledger corruption/loss. It now rejects any non-fixture principal and all consumption/revocation when configured outside fixture mode, including a caller-constructed identity claiming `LOCAL_HELPER_PEERCRED`. Its ledger is atomically written and hash-chained, but not signed; it cannot authenticate an approver against another process sharing the same UID. No separate approver account, helper service, or operational provider exists. The passive policy remains disabled.

## The multi-agent subsystem contract

The adapter contract is pinned to the multi-agent subsystem commit `8fed7dc39770c70eb599c9e41d17c9ede7bb52e8`, with source hashes checked for the bridge and frame transform. A replay of the sealed M4c-r1 Rover request stays WAITING because human limits and authorization are absent. A separate synthetic fixture case passes v2 validation and frame transformation into the existing executor request validator, then remains blocked by `OPERATIONAL_ROVER_POLICY_DISABLED`; it produces zero commands and does not authorize execution. The focused lifecycle/auth/adapter/the multi-agent subsystem group passed 36 tests, including a synthetic helper transport failure.

## What remains

Runtime event sources for READY, MotionBinding `/2`, parameter provenance, observation capture, worker-close confirmation, and final inventory are not wired into the vertical lifecycle. Deadline tests now cover interruption, a blocked observation provider, a lost STOP response, and a late worker-close result. STOP request and uncertainty handling are still tested offline; no hard process or physical-stop guarantee has been demonstrated. The unified code/schema/test patch is based on `2e206f1fa4c0c6db056adac4a3fcaaa0835e47f1`, has SHA-256 `361e0c9be3950fad9e7239c7ed70a3dcde4190f703d8d2567f5d7135ecef4208`, and applies to a temporary copy of that base. Protected code remains uncommitted and the patch has not been applied to the source tree. The gate remains disabled. No SITL, Gazebo, ROS transport, MAVLink, vehicle command, or physical operation was run.

## Next steps

1. Review the protected patch and add dedicated tests for its passive process-marker, foreign-process refusal, boot mismatch, descendant selection, and STOP ownership behavior before promotion.
2. Obtain separate human approval for host configuration of a separately owned approver helper/ledger, then implement and review the authenticated IPC provider. Do not enable the policy before this trust boundary exists.
3. Wire and test read-only runtime providers behind the closed policy.
4. Promote via the repository's protected successor/pin process, then obtain a fresh SATISFIED precheck and new authorization for one passive session.
5. Treat failsafe and the first one-metre movement as separate later trials with separate approvals; the offline suite gives no operational GO.
