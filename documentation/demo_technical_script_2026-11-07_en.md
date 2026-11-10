# Technical demo script: the unified TFG (7 Nov 2026, updated in the afternoon)

**What it shows:** one mission, entered in natural language or as a QGroundControl `.plan`. It goes through the
supervisor, the Drone Agent and the Rover Agent, the safety validation, a synthetic card detection and the spatial
transformation, and reaches the ground target. From there it goes through the v2 bridge into the real admission code
of the rover subsystem's protected executor. The executor refuses on operational grounds, and nothing is commanded.

**What it does not show:**
- any flight or rover motion;
- any simulator or Gazebo image (the card image is synthetic, not a Gazebo capture);
- any real camera;
- any model call during the demo.

## Labels

| Label | Meaning |
| --- | --- |
| `REAL_LOCAL_LLM` (historical, via `REPLAY`) | Real local-Qwen calls, recorded in the sealed M4c-r1 pilot. The replay **shows** them; it does not call the model again |
| `OFFLINE_DETERMINISTIC` | Scripted agents in the three roles. No model is called |
| `STRUCTURED_INPUT` | The mission comes from a `.plan` through Hermes' importer. No model is called |
| `SYNTHETIC_SENSOR` / `TEST_FIXTURE` | A rendered card image, and fixture limits, authorization, transform and rover pose. Fixtures are refused in `OPERATIONAL` mode |
| `REAL_CONTRACT_CODE` | The rover subsystem's own validators and executor admission, run from an immutable snapshot of its commit |
| `DRY_RUN_EXECUTOR` | Our dry-run adapter. It refuses, and there is no physical effect |

## Commands

```bash
python -m multiagent.demo --scenario red_target --rover-snapshot <dir> --rover-reviewed      # 13 steps, NL input
python -m multiagent.demo --input-plan multiagent/fixtures/plans/red_target_aerial.plan \
    --plan-manifest multiagent/fixtures/plans/red_target_aerial.plan.semantics.json          # step 2 as a .plan
python -m multiagent.demo --replay multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9
python -m multiagent.demo --list-scenarios | --all-scenarios | --battery --rover-snapshot <dir> [--rover-reviewed]
python -m multiagent.integration_smoke                                                       # 13 areas, offline
```

`--rover-snapshot <dir>` extracts the rover subsystem's pinned commit with `git archive`, never from a working copy.
`--rover-reviewed` adds its protected review patch. The patch's sha256 is checked, and the patch is applied only
inside that directory.

## The 13 steps

| # | Step | What to point at | Label |
| ---: | --- | --- | --- |
| 1 | Operator's mission | `operator  mission: Inspect POI_1 with the RGB camera and take multispectral images of POI_3. If a drone camera reports a red or yellow card, send rover_01 …` | — |
| 2 | Input as NL or `.plan` | **NL:** the same line, interpreted by the supervisor. **`.plan`:** `[plan] 1 input … (Hermes importer)`, then `2 semantics MANIFEST_APPLIED`, then `objective A1 … sensor rgb (inspect at waypoint POI_1)` | OFFLINE_DETERMINISTIC / STRUCTURED_INPUT |
| 3 | Supervisor | `supervisor  status PROPOSED_PENDING_AUTHORIZATION …; ground objectives waiting: ['G1']` | OFFLINE_DETERMINISTIC |
| 4 | Drone Agent | `drone_agent  drone_01 -> ['POI_1']`, `drone_02 -> ['POI_3']`, and its tool calls | OFFLINE_DETERMINISTIC |
| 5 | Rover Agent | Phase A: `WAIT_FOR_OBSERVATION` (gate ACCEPTED). After detection: `PLAN_TO_DECLARED_POI POI_3 -> AGREES` | OFFLINE_DETERMINISTIC |
| 6 | Safety validation | `DECONFLICTED_BY_START_DELAY … 0 residual` (deterministic) and `drone gate … accepted` | deterministic |
| 7 | Synthetic card detection | `perception  SYNTHETIC_SENSOR: rendering a SYNTHETIC_TEST image (no camera)`, then `DETECTED red_card` | SYNTHETIC_SENSOR |
| 8 | Spatial transformation | Image → site: `geometry … BUILT {chain: site -> drone_02/base_link -> camera}`. Site → rover: the **final contract** keeps the goal in the site frame with the transform `REQUIRED_NOT_APPLIED`, because the rover subsystem's adapter converts once. The **offline test path** shows `converted once by multiagent.frames2d` | TEST_FIXTURE transform |
| 9 | Ground target | `gate ACCEPTED: target POI_3 at (8.0, 4.0) sigma 0.12 m`, then the coordinator's `READY_FOR_AUTHORIZATION` | deterministic |
| 10 | Bridge v2 | `[rover] payload v2: … the rover subsystem decision READY_TO_SUBMIT, schema errors 0`, and the submission envelope `READY_TO_SUBMIT_NOT_EXECUTED (not a command)` | REAL_CONTRACT_CODE |
| 11 | Executor admission | Offline test path: `rover_bridge PASS`, `rover_v2 PASS`, `executor_request PASS`. Final contract: `executor_request NOT_REACHED ROVER_ADAPTER_NOT_IN_SNAPSHOT …` (its adapter is not committed yet) | REAL_CONTRACT_CODE |
| 12 | Operational refusal | `executor_admit BLOCKED ['OPERATIONAL_ROVER_POLICY_DISABLED']`: no operational authorization or policy exists. The **real** M4c-r1 request is refused earlier: no human limits, no authorization, no accredited position | REAL_CONTRACT_CODE / DRY_RUN_EXECUTOR |
| 13 | Zero commands | `READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED; commands 0; movement executed False` and `V2_READY_AWAITING_ROVER_ADAPTER; commands 0` | — |

## Talking points

- **One controller, one authorization model, one conversion.**
  - The rover subsystem's executor is the only controller.
  - `READY_TO_SUBMIT` is never an authorization.
  - The site → rover conversion happens once, by its declared owner. The final owner is the rover subsystem's adapter. A second
    conversion is refused.
- **A `.plan` cannot carry everything.**
  - It cannot carry the sensor type, `take_photo`/`inspect`, the waypoint names or the conditional rover task.
  - The real MAVLink camera commands address a camera *instance*, not a sensor type. Using them would mean inventing a
    camera id.
  - A manifest bound by sha256 to the `.plan` keeps the rest. Without it, every lost field is reported.
- **The rover agent cannot authorize itself.** A reply that claims authority or contains commands is rejected.
- **Losing the rover's position** blocks any authorization (`NO_POSITION`, then `WAITING_FOR_ROVER_LOCALIZATION`).
- **Real LLM, without repeating the pilot.** M4c-r1 is shown through the replay; the model is not called again.

## Evidence

- `multiagent/benchmark/results/codex_adapter_integration_2026-11-07_32c19517d/` (SYNTHETIC, sealed).
- `multiagent/benchmark/results/codex_integration_v2_2026-11-07_0dab97317/` (the morning round).
