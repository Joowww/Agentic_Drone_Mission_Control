# Multi-agent precision-agriculture demo: short summary for Toni (6 Nov 2026)

## Architecture

A Mission Orchestrator (supervisor) interprets the operator's request and delegates aerial work to a Drone/Swarm
Agent and ground work to a Rover Agent. A perception step turns a camera detection into a position, and a
coordinator tracks the mission state and the drone→rover dependencies. Every proposal ends PENDING human
authorization: no agent can arm, upload, drive or command a vehicle.

## Agents vs validators

The agents propose. Deterministic validators decide:
- site and geofence rules;
- battery and wind checks;
- sensor eligibility;
- spatio-temporal separation;
- ground-route checks;
- the perception gate;
- the coordinator.

A model's proposal that a validator rejects falls back to a deterministic plan. That fallback is recorded and never
counted as the model's success.

## Real use of Qwen (local qwen3:4b)

These are small, pre-registered pilots:
- **v1/v2/v3:** 3 cases per role. With contract v3 the rover agent went from 0/3 to 2/3, and one case was fixed by
  a second call. The drone agent reached 2/3: in one case it did not use the conflict feedback.
- **M4:** one integrated mission with Qwen in all three roles, run once with 2 of 6 calls. The supervisor's
  brief was right, but it flagged the conditional "send the rover once the observation is validated" as unsafe,
  so the mission was refused. Conservative, but a failure. It also exposed two defects of ours, now fixed: after
  a refusal the demo still called the rover agent and told the coordinator the plan existed.
- **M4b:** a new run with a revised supervisor prompt (planning or delegating a conditional rover task is not an
  order) and a stricter safety policy, which adds an independent rule-based check of the operator's text. It used
  1 of 6 calls. The model no longer flagged the rover task, but it invented three fields: a null battery value, an
  "unknown" rover availability and a drone nobody asked for. The deterministic checks rejected the brief and asked
  for clarification, so the drone and rover agents were never reached. **The full mission with three real agents
  has not been shown yet.**
- **After M4b, data provenance:**
  - The supervisor now has to quote the operator's words for every objective and every vehicle fact. Facts nobody
    stated are simply absent, and the model can only list what should be looked up. It cannot declare a source.
  - A rule-based check compares the reply with the request and with the declared inventory. An unsupported vehicle
    fact is dropped and recorded; it is never counted as the model's success. An unsupported objective rejects the
    brief.
  - Inventory values are kept as "from the inventory", never as if the operator had said them.
  - All 53 reference briefs of our test sets pass this check and lead to the same decisions as before.
- **M4c-r1 (7 Nov): the first mission with real Qwen in all three roles.** It used the same request, model and
  criteria as before, and 4 of the 6 authorized calls.
  - The supervisor's brief invented nothing.
  - The drone agent assigned both zones in its first answer. It checked routes and separation with its tools, and
    the validator resolved the conflict those tools found by delaying one take-off.
  - The rover agent first planned to wait for the observation. After the synthetic card was detected and located,
    it planned the trip to the validated point, agreeing with the rule-based rover agent.
  - No fallback was needed. The result is a plan waiting for human authorization, with zero commands.
  - It is one run on synthetic data: an existence proof, not a statistic.
  - The earlier attempt (M4c) never ran because its isolation rule waited for the rover subsystem's checkout to be idle for
    20 minutes. The rule was replaced by checks of the resources the run actually uses (GPU, model server,
    simulations, vehicle locks), under a new manifest.

The offline demo itself uses scripted agents that go through the same contracts.

## Card detection

The detector finds red and yellow cards with colour thresholds, not learning: HSV, an adaptive brightness
threshold, morphology, connected components and geometric filters. It returns detected, ambiguous or none. Its
score is a heuristic, not a calibrated probability. So far it has been tested only on synthetic images.

## UAV-UGV coordination

The pixel goes through the camera intrinsics and extrinsics and the drone pose into the site frame, using metric
depth or an explicit flat-ground assumption. It must match a declared point the rover can reach.

The coordinator moves the rover task from waiting for an observation, to target validated, to ready for
authorization. It blocks on expired observations, stale drone reports, lost dependencies, cancellations, identity
changes and missing localization.

`python -m multiagent.demo --all-scenarios` runs 17 scenarios: 4 end with planning completed and execution waiting for
human authorization, and 13 are blocked, waiting, refused or cancelled. All end as expected under both safety policies,
with zero commands.

Defects of ours found and fixed while hardening the chain:
- a drone proposal that the contract had rejected could still become the plan;
- the drone agent's reason for leaving an objective out was believed, not checked. It is now re-derived with the
  same tools, and a confirmed reason reaches the final plan;
- an authorization was accepted even if the drone telemetry had gone stale after it was requested;
- a human authorization could be a bare yes/no flag. It is now a record bound to the exact plan, rover, proposal
  and limits, with an operator and a validity window;
- an offline test observation could claim to come from a real or SITL sensor and still validate a target.

## Detector vs OpenCV

An OpenCV port of the same algorithm was run on the same 37 synthetic images. Both got 34/37 right, with identical
outputs. OpenCV is about 50 times faster (4 ms vs 235 ms per image), but no more accurate.

The minimum detectable card size is now derived from the camera geometry instead of a fixed pixel count. At 10 m
with the virtual camera, cards from 0.2 m are measurable, and the detector reports that 0.15-0.2 m cards are not.
This is a declared assumption; a real camera still has to be calibrated and tested.

## Pending

- **SITL:** the rover first-motion work (subsistema rover) and an executor wired to the coordinator. Our ground-task requests
  are now tested against the rover subsystem's own mission-payload validator. Today they are rejected for the expected reasons: no
  accredited localization, no human limits, no authorization.
- **Hardware:** camera calibration, the drone pose from the ArduPilot EKF, an accredited JetRacer localization and
  driver. A preparation document and a lab checklist exist; nothing has been connected.

## Opik

Experiments and traces are prepared for Opik. Only one historical trace is uploaded. The re-import of the other
ten is prepared and waits for authorization.

## Limitations

- This is not a flight: the demo is fully offline and synthetic.
- Results come from very few cases and are preliminary.
- The detector has not been validated on real photographs.
- The flat-ground depth assumption has no real calibration behind it.
- The only executor is a dry-run adapter.
