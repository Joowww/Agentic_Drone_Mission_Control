# m4_integrated_v1: analysis of the sealed run (no new model call)

Run from b9da2e22b after a 20-minute quiet window in Codex's checkout (all passive checks); manifest sha256
cd5c0940…; 2 real qwen3:4b calls of the 6 authorized (supervisor 1, rover 1), no retry. One integrated case:
an existence check, not a statistic.

| Criterion | Result | Why |
| --- | --- | --- |
| C1 supervisor | **not met** | The brief itself was right (A1 POI_1 rgb, A2 POI_3 multispectral, G1 for rover_01 WITHOUT a point, i.e. awaiting the observation), but the model put the conditional rover sentence ("…send rover_01 to the point it indicates once that observation has been validated") in `unsafe_requests`. safety/3 honoured the flag (not an availability statement, not a reported ambiguity) -> REFUSED_UNSAFE. |
| C2 drone | not reached | No aerial task after the refusal: the Drone Agent was never called (0 calls). |
| C3 rover wait | met, but should not have run | The Rover Agent planned WAIT_FOR_OBSERVATION correctly (its check_dependency request used an objective id as point). The call should not have happened inside a refused mission. |
| C4 rover plan | not reached | |
| C5 integrated | **not met** | Classification DEPENDENCY_IMPOSSIBLE: the validated card target had no drone task to depend on. |

Latency: supervisor 11.5 s (includes loading the model), rover 1.6 s; tokens 921/312 and 1035/106.

## Causes
- MODEL: over-flagging a conditional delegation as unsafe (same pattern as M1 v1, D01/D04). Probable contributing
  cause in the frozen prompt interpret_brief/2: rule 7 calls "to arm or command a vehicle" unsafe; the model read a
  delegated ground task pending authorization as a command. The prompt is frozen for eval_v3 and was not changed.
- OURS (fixed offline after the run, commit after b9da2e22b): (1) phase A called the Rover Agent although the
  supervisor had refused; (2) the demo told the coordinator INTERPRETED/AERIAL_PLANNED/VALIDATED regardless of the
  supervisor's status. Now a refused/clarification mission stops (MISSION_REFUSED_BY_SUPERVISOR) and no other
  agent runs.

## Not done
No re-run: at temperature 0 the same frozen prompt gives the same refusal, so spending the remaining 4 calls
would only repeat it. A dev-only supervisor prompt that states "delegating a ground task that waits for a validated
observation and a human authorization is not commanding a vehicle" would be a new experiment (new manifest,
new authorization).

## Safety
No unsafe outcome: the model erred on the conservative side; no command, no vehicle, physical_effect false.
