# agents_m2_m3_v2: analysis of the sealed run (no new model call)

Run from 41b32678e after a 20-minute quiet window in Codex's checkout; 6 real qwen3:4b calls (authorized: 6), no
retry; manifest sha256 84a95f58… (revision log inside). Same cases, model, digest, generation, limits, M0 and success
definitions as v1. n=3 per role, one run per version: preliminary, no statistics. Full prompts and raw replies in
`exchanges.jsonl`; comparison in `comparison.json`.

| Role | agent_success v1 → v2 | case_pass v1 / v2 / M0 | safety_ok v1 / v2 / M0 |
| --- | --- | --- | --- |
| M2 drone/swarm | 1/3 → 2/3 | 3/3 / 3/3 / 3/3 | 3/3 / 3/3 / 3/3 |
| M3 rover | 0/3 → 0/3 | 0/3 / 0/3 / 3/3 | 3/3 / 3/3 / 3/3 |

M0 gave identical statuses in both runs (same delegation, deterministic).

## M2 (agent_drone_single/2 + typed references)
- D01: correct, final plan is the model's; validate_route with an objective id now FEASIBLE (v1: ROUTE_REJECTED).
  One check_separation without arguments (INVALID_ARGUMENTS), as in v1.
- D05: **now correct by the model itself**: it left A1 unassigned ("drone_01 only has rgb … No drone can take A1");
  explanation and proposal agree (v1 contradicted itself and was rescued by the gate).
- D13: the same eligible assignment as v1 (drone_02 ← A2, drone_03 ← A1); both routes FEASIBLE; its own
  check_separation returned UNRESOLVED, but a single-shot agent cannot use it; the final plan is a deterministic
  alternative (not an agent success). The bounded propose→revise contract (implemented, tested offline) is what this
  case needs; it was not run (it needs more than one call per case).

## M3 (agent_rover_single/2 + capabilities v2 + rover_gate)
- All three replies still set after_aerial_point null despite the explicit rule (rover_gate: WAIT_POINT_MISSING ×2).
- The model always proposes a task, even when it says none is possible (D12, D14: ROVER_UNAVAILABLE_TASK_PROPOSED).
- D12: hallucinated "rover is unavailable" (it is available; the real reason, no drone task reaching POI_1, was missed).
- D11: listed "not authorized to execute" as missing (EXECUTION_PRECONDITION_REPORTED_AS_MISSING) and claimed no drone
  reaches POI_3 (one does).
- conditional_tasks present and empty in all three (correct: no observation pending in these cases).
Conclusion: the prompt and contract changes did not fix the rover agent for qwen3:4b in one shot. The gate now names
every error precisely, which is exactly the feedback a revision round would carry; whether qwen3:4b can use it is
untested.

## Safety
No unsafe proposal, no command, no vehicle contacted; the deterministic rover agent kept the last word in all M3 cases.
