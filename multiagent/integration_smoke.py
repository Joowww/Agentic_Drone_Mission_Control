"""Smoke tests for the unified TFG: run after any merge or rebase to check that nothing of Hermes, the .plan inputs,
the graph, the agents, perception, coordination, Opik (offline), the simulator mapping, the rover bridge, the CLI
or the replay broke. Offline only: no model call, no SITL/Gazebo, no ROS 2, no MAVLink, no Opik network.

  python -m multiagent.integration_smoke [--area NAME ...] [--json OUT]

Each area is one pytest process (its REAL exit code is kept; nothing is piped through tail) plus, for the CLI and
the replay, direct command checks. Exit code 0 only if every selected area passed. rover-owned suites (rover
lifecycle, executor, scopes) are NOT run here: they belong to the rover's integration candidate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
M4C_R1 = "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9"

AREAS: dict[str, dict] = {
    "hermes": {"what": "Hermes MCP tools, mission planning/validation, deterministic parser, structured session",
               "tests": ["tests/test_hermes_mcp_server.py", "tests/test_hermes_mission_planning.py",
                         "tests/test_hermes_mission_validation.py", "tests/test_mission_planner.py",
                         "tests/test_mission_state.py"]},
    "plan_input": {"what": "QGC .plan export, import, comparison; georeference; mission-input/1 contract",
                   "tests": ["tests/test_qgroundcontrol_exporter.py", "tests/test_qgroundcontrol_adapter.py",
                             "tests/test_qgc_plan_compare.py", "tests/test_site_geometry.py",
                             "tests/test_scenario_package.py", "tests/test_multiagent_mission_inputs.py",
                             "tests/test_multiagent_plan_semantics.py"]},
    "preflight": {"what": "preflight sequences and virtual preflight (process doubles only)",
                  "tests": ["tests/test_preflight_sequences.py", "tests/test_virtual_preflight.py",
                            "tests/test_virtual_preflight_jobs.py"]},
    "langgraph": {"what": "the agri scenario graph and partial-geometry planning (main.py, graph/)",
                  "tests": ["tests/test_agri_scenario_flow.py", "tests/test_agri_scenario.py",
                            "tests/test_partial_geometry_planning.py"],
                  # a REAL passive capture that .gitignore excludes: present only where it was recorded (the rover's
                  # checkout). Without it these tests cannot run; they are reported, never counted as passed.
                  "requires_untracked": {
                      "simulation/ros2_gazebo/results/rover_worker_lifecycle_2026_10_25/"
                      "4ac58516-8fad-457e-918e-253483a2d728": ["REAL_VIEW_measured_facts",
                                                              "ground_report_keeps_measured_facts"]}},
    "supervisor": {"what": "Mission Orchestrator, brief provenance /4, supervisor v3, safety policies",
                   "tests": ["tests/test_multiagent_brief_provenance.py", "tests/test_multiagent_supervisor_v3.py",
                             "tests/test_multiagent_v3.py"]},
    "drone_agent": {"what": "Drone/Swarm Agent, deconfliction, swarm",
                    "tests": ["tests/test_multiagent_drone_v3.py", "tests/test_multiagent_deconfliction.py",
                              "tests/test_multiagent_swarm.py"]},
    "rover_agent": {"what": "Rover Agent gate and UAV-UGV cases",
                    "tests": ["tests/test_multiagent_agents_v2.py", "tests/test_multiagent_uav_ugv_cases.py"]},
    "perception": {"what": "card detector, geometry, observation gate",
                   "tests": ["tests/test_multiagent_perception.py", "tests/test_multiagent_vision.py"]},
    "coordination": {"what": "mission coordinator, coordination matrix, SITL event contract",
                     "tests": ["tests/test_multiagent_coordinator.py", "tests/test_multiagent_coordination_matrix.py",
                               "tests/test_multiagent_sitl_events.py", "tests/test_multiagent_sitl_topics.py",
                               "tests/test_multiagent_coordination_extras.py"]},
    "opik_offline": {"what": "Opik export/bridge offline (fake transports; nothing published)",
                     "tests": ["tests/test_opik_export.py", "tests/test_multiagent_opik_bridge.py"]},
    "simulator": {"what": "simulated vehicle selection and mission mapping (no simulator started)",
                  "tests": ["tests/test_simulated_vehicle_selection.py", "tests/test_simulation_mission_mapper.py"]},
    "rover_bridge": {"what": "bridge, v1/v2 contracts against rover snapshots, hand-off, ROVER_ADAPTER, frames",
                     "tests": ["tests/test_multiagent_rover_contract_v1.py", "tests/test_multiagent_rover_v2_contract.py",
                               "tests/test_multiagent_rover_handoff.py", "tests/test_multiagent_rover_integration_v2.py",
                               "tests/test_multiagent_rover_adapter_contract.py", "tests/test_multiagent_frames2d.py",
                               "tests/test_multiagent_integration_battery.py"]},
    "two_drones": {"what": "drone plan -> Hermes missions -> H2 request (no effects), schedule, camera, end-to-end demo",
                   "tests": ["tests/test_multiagent_hermes_mission_adapter.py", "tests/test_multiagent_drone_schedule.py",
                             "tests/test_multiagent_drone_execution_bridge.py",
                             "tests/test_multiagent_camera_observation.py", "tests/test_multiagent_two_drone_demo.py"],
                   "commands": [["-m", "multiagent.demo", "--two-drones"]]},
    "cli_replay": {"what": "demo CLI scenarios and the sealed M4c-r1 replay",
                   "tests": ["tests/test_multiagent_precision_demo.py", "tests/test_multiagent_replay.py",
                             "tests/test_multiagent_demo_unified.py"],
                   "commands": [["-m", "multiagent.demo", "--list-scenarios"],
                                ["-m", "multiagent.demo", "--all-scenarios"],
                                ["-m", "multiagent.demo", "--replay", M4C_R1]]},
}


def run_area(name: str, python: str) -> dict:
    spec = AREAS[name]
    missing = [t for t in spec["tests"] if not (ROOT / t).is_file()]
    absent = {path: kws for path, kws in spec.get("requires_untracked", {}).items() if not (ROOT / path).exists()}
    deselect = [k for kws in absent.values() for k in kws]
    t0 = time.monotonic()
    cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *[t for t in spec["tests"] if t not in missing]]
    if deselect:
        cmd += ["-k", " and ".join(f"not {k}" for k in deselect)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=_env())
    last = (p.stdout.strip().splitlines() or [""])[-1]
    out = {"area": name, "what": spec["what"], "pytest_exit": p.returncode, "summary": last, "missing": missing,
           "commands": [], "seconds": round(time.monotonic() - t0, 1),
           "not_run_data_absent": {path: f"tests matching {kws} NOT RUN: untracked data absent here"
                                   for path, kws in absent.items()}}
    for c in spec.get("commands", []):
        r = subprocess.run([python, *c], cwd=ROOT, capture_output=True, text=True, env=_env())
        out["commands"].append({"argv": c, "exit": r.returncode})
    out["passed"] = p.returncode == 0 and not missing and all(c["exit"] == 0 for c in out["commands"])
    return out


def _env():
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return env


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--area", action="append", choices=sorted(AREAS))
    a.add_argument("--json", type=Path, help="write the results here (new file)")
    args = a.parse_args(argv)
    rows = [run_area(n, sys.executable) for n in (args.area or AREAS)]
    for r in rows:
        cmds = " ".join(f"[{' '.join(c['argv'][1:3])}: {c['exit']}]" for c in r["commands"])
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['area']:13s} {r['summary']} {cmds} "
              f"{'missing ' + str(r['missing']) if r['missing'] else ''}"
              f"{'NOT_RUN_DATA_ABSENT ' + str(list(r['not_run_data_absent'].values())) + ' ' if r['not_run_data_absent'] else ''}"
              f"({r['seconds']} s)")
    if args.json:
        with args.json.open("x") as fh:
            json.dump({"schema": "tfg.multiagent.integration-smoke/1", "areas": rows}, fh, indent=1)
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
