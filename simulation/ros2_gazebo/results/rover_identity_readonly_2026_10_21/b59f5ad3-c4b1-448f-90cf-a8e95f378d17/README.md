# Rover identity inspection — BLOCKED

Read-only inspection on 2026-10-21. Current engine/container identity and state were collected with bounded Docker metadata calls. The container reported `exited`, `Running=false`, `Pid=0`. Collection stopped before any docker exec, ROS subscription, service call, worker creation, lifecycle action or control. No runtime reservation was modified.

`metadata_authorized-summary.json` and raw per-command stdout/stderr contain the successful current observations. `metadata_sandbox-*` retain the earlier permission failure; that failure is not termination evidence. `summary.json` lists uncollected evidence explicitly. Exit code 255 is metadata, not a root-cause explanation or proof about landing. The worker, GIDs, messages, frames, units, active bridge configuration and effective DDS/XRCE association were not checked because the prerequisite failed.

`session.json` records HEAD, source hashes and host guard presence at the start of this inspection. Any guard-original copies retain their exact bytes; they are evidence copies, not active guard files. `collector_metadata.py` preserves the read-only collection source. Paths in its temporary launcher are historical context, not a recommended rerun interface.

The manifest covers every evidence file except itself, with SHA-256 and byte size. No original source, runtime report or prior evidence was overwritten. A separate future authorization would be required for any start; this inspection authorizes none.
