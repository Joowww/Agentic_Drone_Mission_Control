# Integrated multi-agent mission, OFFLINE and SIMULATED (2026-11-06, commit ea08c7426)

`python -m multiagent.integrated_mission --simulated --out <dir>`. The three agents ran with SCRIPTED TEST DOUBLES
(`multiagent/simulated_llm.py`: integrated_orchestrator, single_shot_drone, single_shot_rover): this is NOT a model
result. The observation is a TEST_FIXTURE (no camera ran). No ROS, Gazebo, SITL, vehicle or Opik send.

Phase A: brief with aerial A1 POI_1 (rgb) and A2 POI_3 (multispectral) and ground G1 without a point (held as
AWAITING_OBSERVATION); drone_01 and drone_02 planned. Observation gate: ACCEPTED (red_card at POI_3, sigma 0.18 m,
TEST_FIXTURE). Phase B: G1 -> POI_3, rover_01 waits for drone_02 (POI_REACHED); separation resolved by a start
delay; rover proposal AGREES with the deterministic agent. Final: PROPOSED_PENDING_AUTHORIZATION, 3 tasks,
authorization granted false, commands_sent 0. The Opik files are dry runs (test doubles are general spans).
