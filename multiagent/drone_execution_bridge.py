"""Drone missions (hermes_mission_adapter) -> an execution REQUEST for the historical H2 two-drone path, prepared by
the boundary tools/multiagent_drone_sequence.py in a SEPARATE process (this package never imports executor or
vehicle-control code). Nothing is submitted: the result names the call an operator would make.

States: PENDING_AUTHORIZATION (no operator statement), READY_TO_REQUEST_EXECUTION (statement present and the H2
admission's own checks pass), REJECTED. EXECUTED never appears here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def request_execution(adapted: dict, *, mission_dir: Path, request_key: str, mode: str = "OFFLINE_TEST",
                      authorization_statement: str | None = None, timeout_s: float = 120.0) -> dict:
    from multiagent.hermes_mission_adapter import mission_files
    if adapted.get("status") != "PLANNING_VALID":
        return {"schema": "tfg.multiagent.drone-execution-request/1", "status": "REJECTED", "submitted": False,
                "commands": [], "problems": [f"PLAN_NOT_VALID: adapter status {adapted.get('status')}"]}
    files = mission_files(adapted)
    by = {d["vehicle_id"]: d for d in adapted["drones"]}
    request = {"mode": mode, "mission_dir": str(mission_dir), "request_key": request_key,
               "authorization_statement": authorization_statement,
               "missions": [{"vehicle_id": v, "mission_json": b.decode(), "mission_sha256": by[v]["mission_sha256"],
                             "start_delay_s": by[v]["start_delay_s"]} for v, b in files.items()]}
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    p = subprocess.run([sys.executable, "-B", "-m", "tools.multiagent_drone_sequence"], input=json.dumps(request),
                       capture_output=True, text=True, cwd=ROOT, env=env, timeout=timeout_s)
    if p.returncode != 0:
        return {"schema": "tfg.multiagent.drone-execution-request/1", "status": "REJECTED", "submitted": False,
                "commands": [], "problems": [f"BOUNDARY_FAILED: rc {p.returncode}: {p.stderr[-400:]}"]}
    out = json.loads(p.stdout)
    out["mission_id"], out["proposal_sha256"] = adapted.get("mission_id"), adapted.get("proposal_sha256")
    return out
