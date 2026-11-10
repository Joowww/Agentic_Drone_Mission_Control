# agents_m2_m3_v3_multiturn: analysis of the sealed run (no new model call)

Run from 4021a867e (manifest sha256 364d78f9…, revision log inside) after Codex's checkout had been quiet for 26 min;
8 real qwen3:4b calls of the 12 authorized (a second call only where the gate rejected), no retry, no case over budget.
n=3 per role, one run per version: preliminary. Comparison in `comparison.json`; full prompts/replies in
`exchanges.jsonl`.

| Role | agent_success v1 / v2 / v3 | of which after revision (v3) | case_pass v1 / v2 / v3 / M0 | safety_ok v3 / M0 | real calls v3 |
| --- | --- | --- | --- | --- | --- |
| M2 drone | 1 / 2 / 2 | 0 | 3 / 3 / 3 / 3 | 3 / 3 | 4 |
| M3 rover | 0 / 0 / 2 | 0 (D12's revision is not counted by this definition) | 0 / 0 / 3 / 3 | 3 / 3 | 4 |
| M3 rover, final-outcome measure (labelled; posterior for v1/v2) | 0 / 0 / 3 | 1 (D12) | | | |

`agent_success` keeps its v1 definition (agreement with the deterministic rover agent BEFORE the supervisor's
dependency check). For D12 that reference still proposes the task the supervisor later removes, so a correct
"cannot plan: no drone reaches the wait point" counts as disagreement; the final-outcome measure compares with the
FINAL ground tasks instead. Both are reported.

## What each round shows
- M2 D01, D05: accepted in round 1. Round 1 is the v2 prompt again (identical prompt and completion tokens to v2 at
  temperature 0): no new information.
- M2 D13: rejected in round 1 (separation UNRESOLVED). Round 2 received the gate's findings, the conflicting segments,
  the legal options and its own check_separation result — and returned **the identical assignment**. The second call
  did not help; the plan is a deterministic alternative (not an agent success).
- M3 D11 (PLAN), D14 (CANNOT_PLAN / ROVER_UNAVAILABLE): correct in round 1 with contract v3 (v2: wrong in all three).
- M3 D12: round 1 planned to POI_1 although its context said `wait_point_reached_by_proposed_drone_task: false`; round 2,
  told `DEPENDENCY_UNSATISFIED_TASK_PROPOSED at decisions[0].decision`, answered CANNOT_PLAN /
  NO_DRONE_TASK_REACHES_WAIT_POINT: **fixed by the second call**.

## Attribution
- Fixed by the contract (round 1, v3 vs v2): rover D11 and D14. Not isolated further: contract v3 changed the
  response schema, the context (per-objective facts) and the gate together.
- Fixed by the second call: 1 (rover D12). Not fixed by it: 1 (drone D13, ignored its own separation result).
- Remaining model errors: drone D13 (revision ignored); rover D12 round 1 (misread an explicit fact, self-corrected).
- Errors that were ours (found and fixed across v1–v3): validate_route ids (v1), rover localization wording (v1),
  rover schema asking for a derivable wait point / always showing a task / free-text reasons (v2), an objective
  silently dropped when an accepted proposal leaves it out (found before v3), the rover agent_success reference being
  pre-dependency (kept, second measure added).

## Safety
No unsafe proposal, no command, no vehicle contacted; no LLM reply disabled a validation (the gates run in code
whatever the reply says); the deterministic rover agent kept the last word.
