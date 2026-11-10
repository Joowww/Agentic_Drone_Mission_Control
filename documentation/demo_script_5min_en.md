# Five-minute demo script (for Toni)

**What it shows:** a three-agent mission planned with a real local LLM; the deterministic checks; the hand-off to
The rover executor's contract. **What it does not show:** any flight, rover motion, real camera or simulator.

## 0:00–0:45 · Context

- **Three agents:** a supervisor, a drone agent and a rover agent. LLMs propose, rule-based validators decide, a
  human authorizes, and only a protected executor could act.
- **The mission:** "Inspect two zones with drones; if a camera sees a red or yellow card, prepare a rover task to go
  there."

## 0:45–2:00 · The real-Qwen run, replayed (no model is called)

```bash
python -m multiagent.demo --replay multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9
```

Point out:
1. The evidence is verified first: hashes, manifest, and the prompt and reply of every call.
2. Four real Qwen calls: supervisor, drone agent, and rover agent twice.
3. The supervisor's brief invented nothing.
4. The drone agent called its route and separation tools. The separation conflict was resolved by the **validator**
   with a 45 s delay, not by the model.
5. The rover agent first waited, then planned to POI_3 after the synthetic card was validated.
6. Zero commands, and the "not recorded" section.

## 2:00–3:30 · The full chain offline, with scripted agents (clearly labelled "not Qwen")

```bash
python -m multiagent.demo --scenario red_target --rover-snapshot /tmp/rover_snapshot
```

Point out:
- the ten stages, the tool calls, the separation line and the detection;
- the target in the site frame, and the rover route;
- the `[rover]` block: our request goes through the rover executor's **real** contract code (a frozen snapshot)
  and stops at its executor's disabled policy, with zero commands.

## 3:30–4:30 · Robustness

```bash
python -m multiagent.demo --all-scenarios
python -m multiagent.demo --battery --rover-snapshot /tmp/rover_snapshot
```

17 scenarios plus 18 integration missions, all as expected, zero commands. Pick two to explain: "rover without
localization" and "uncertain STOP → UNKNOWN".

## 4:30–5:00 · Limits and next step

- One real integrated LLM run (an existence proof).
- Synthetic perception.
- No simulator or vehicle yet.
- Next: a joint test with the rover executor in SITL (subsistema rover), and real card photos.
