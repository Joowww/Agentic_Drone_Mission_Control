# Integrated precision-agriculture demo, offline evidence (2026-11-06)

`python -m multiagent.demo --all-scenarios --out <dir>/scenarios` from the commit in `manifest.json`. 16 scenarios,
each with its SYNTHETIC_TEST image (`scene.png`), the scene manifest, the result (classification, status ladder,
detection, geometry, gate, coordinator summary, execution request, executor events, per-agent records), the
coordinator log and the proposals. Agents are scripted test doubles (DETERMINISTIC_AGENT); events are TEST_FIXTURE;
no LLM, no SITL, no sensor, no vehicle. Best possible end: planning completed, execution pending a human
authorization. `manifest.json` also holds indicative timings of the detector, geometry, gate and coordinator.
