"""Boundary: multi-agent drone missions -> the historical H2 two-drone SITL path, prepared WITHOUT any effect.

H2 (24/10/2026) ran: Hermes missions -> tools.preflight_sequences.start_preflight_sequence(mission_paths,
request_key, authorization_statement) -> detached coordinator (tools.preflight_sequence_worker) -> per child the
virtual preflight graph (validate, SITL readiness, compatibility, tools.simulation_mission_executor.
execute_approved_mission, analysis) -> PASSED. The children run ONE AFTER THE OTHER: the second only after the first
PASSED (landed, disarmed, evidence verified).

This module runs the side-effect-free part of that path with the real code and STOPS before the first effect:
  - writes the exact mission bytes (the only files it writes) and re-checks their sha256;
  - tools.hermes_mission_validation.validate_mission_file on the written file (FEASIBLE / APPROVED);
  - tools.simulation_mission_executor._execution_compatibility_errors (+ mission home), as the sequence worker does;
  - tools.simulated_vehicle.resolve_mission_vehicle (drone_01->v1, drone_02->v2);
  - with an operator statement: tools.preflight_sequences._inputs, the admission's own validation (exactly one
    drone_01 and one drone_02 mission, inside the missions root, in the requested order) and its fingerprint.
It NEVER calls start_preflight_sequence (reservation, files, detached process), check_simulation_ready,
execute_approved_mission or any MCP tool. Its output names the call an operator would make; nothing is submitted.

Minimal adaptation proposed for the H2 code (not applied): split start_preflight_sequence into a pure
build_sequence_plan(values, request_key, statement) and the effectful admission, so this boundary can reuse the plan
construction instead of describing it.

  python -m tools.multiagent_drone_sequence < request.json > result.json      (JSON in, JSON out)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

SCHEMA = "tfg.multiagent.drone-execution-request/1"
H2_ENTRY = "tools.preflight_sequences.start_preflight_sequence"
SINGLE_ENTRY = "tools.virtual_preflight.run_virtual_preflight"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def prepare(request: dict) -> dict:
    """``request``: {"mode": "OFFLINE_TEST" | "OPERATIONAL", "mission_dir": str, "request_key": str,
    "authorization_statement": str | None, "missions": [{"vehicle_id", "mission_json", "mission_sha256",
    "start_delay_s"}]}. In OFFLINE_TEST the missions root of the admission check is ``mission_dir``'s parent
    (recorded); in OPERATIONAL it is the project's missions root, as in H2."""
    from tools import preflight_sequences as seq
    from tools.hermes_mission_validation import validate_mission_file
    from tools.simulated_vehicle import VehicleSelectionError, resolve_mission_vehicle
    from tools.simulation_mission_executor import _execution_compatibility_errors
    from models.mission_definition import MissionDefinition
    out = {"schema": SCHEMA, "mode": request.get("mode"), "submitted": False, "commands": [],
           "effects": "mission snapshot files only; no reservation, no process, no simulator, no vehicle",
           "missions": [], "problems": []}
    mode = request.get("mode")
    if mode not in ("OFFLINE_TEST", "OPERATIONAL"):
        out.update(status="REJECTED", problems=[f"UNKNOWN_MODE: {mode!r}"])
        return out
    mission_dir = Path(request["mission_dir"]).resolve()
    root = seq.MISSION_ROOT.resolve() if mode == "OPERATIONAL" else mission_dir.parent
    if mode == "OPERATIONAL" and not mission_dir.is_relative_to(root):
        out.update(status="REJECTED", problems=[f"MISSION_DIR_OUTSIDE_MISSIONS_ROOT: {mission_dir}"])
        return out
    mission_dir.mkdir(parents=True, exist_ok=True)
    # the agenda: the H2 path runs the missions one after the other, in start order
    ordered = sorted(request["missions"], key=lambda m: (m.get("start_delay_s") or 0.0, m["vehicle_id"]))
    paths = []
    for m in ordered:
        data = m["mission_json"].encode() if isinstance(m["mission_json"], str) else m["mission_json"]
        row = {"vehicle_id": m["vehicle_id"], "start_delay_s": m.get("start_delay_s"), "problems": []}
        if _sha(data) != m.get("mission_sha256"):
            row["problems"].append("PLAN_MODIFIED_AFTER_VALIDATION: mission bytes differ from the validated sha256")
        path = mission_dir / f"{m['vehicle_id']}.json"
        if path.exists() and path.read_bytes() != data:
            row["problems"].append(f"SNAPSHOT_EXISTS_WITH_OTHER_CONTENT: {path.name}")
        elif not path.exists():
            path.write_bytes(data)
        row["path"], row["sha256"] = str(path), _sha(path.read_bytes())
        v = validate_mission_file(str(path), export_qgc=False)
        row["hermes_validation"] = {k: v.get(k) for k in ("mission_status", "execution_status", "failure_reasons",
                                                          "errors")}
        if v.get("execution_status") != "APPROVED":
            row["problems"].append(f"HERMES_NOT_APPROVED: {v.get('mission_status')}/{v.get('execution_status')}")
        mission = MissionDefinition.model_validate_json(path.read_bytes())
        compat = _execution_compatibility_errors(mission)
        if mission.route.home is None:
            compat.append("Simulation mapping requires a mission home")
        row["executor_compatibility_errors"] = compat
        row["problems"] += [f"EXECUTOR_INCOMPATIBLE: {e}" for e in compat]
        try:
            row["sitl_binding"] = resolve_mission_vehicle(mission).as_dict()
            if row["sitl_binding"]["vehicle_id"] != m["vehicle_id"]:
                row["problems"].append(f"VEHICLE_MISMATCH: mission for {row['sitl_binding']['vehicle_id']}")
        except VehicleSelectionError as exc:
            row["sitl_binding"] = None
            row["problems"].append(f"NO_SITL_BINDING: {exc}")
        out["missions"].append(row)
        paths.append(str(path))
        out["problems"] += [f"{m['vehicle_id']}: {p}" for p in row["problems"]]
    statement = request.get("authorization_statement")
    if len(paths) == 2:
        out["execution_path"] = {"entry": H2_ENTRY, "realization": "SEQUENTIAL_H2",
                                 "note": "the second mission starts only after the first PASSED; this is stricter "
                                         "than the planned start offset"}
    elif len(paths) == 1:
        out["execution_path"] = {"entry": SINGLE_ENTRY, "realization": "SINGLE_VEHICLE",
                                 "note": "arms and takes off the resolved simulated vehicle: separate authorization"}
    else:
        out["problems"].append(f"UNSUPPORTED_MISSION_COUNT: {len(paths)} (the H2 path takes one or two)")
    if out["problems"]:
        out["status"] = "REJECTED"
        return out
    if not statement:
        out.update(status="PENDING_AUTHORIZATION", would_call=None,
                   note="no operator statement: nothing can be requested (a valid plan is not an authorization)")
        return out
    if len(paths) == 2:
        saved = seq.MISSION_ROOT
        try:
            seq.MISSION_ROOT = root            # OFFLINE_TEST: the admission's own checks against the test root
            values, fingerprint = seq._inputs(paths, statement)
        except (ValueError, OSError) as exc:
            out.update(status="REJECTED", problems=[f"H2_ADMISSION_CHECK: {exc}"])
            return out
        finally:
            seq.MISSION_ROOT = saved
        out["admission_check"] = {"function": "tools.preflight_sequences._inputs", "missions_root": str(root),
                                  "fingerprint": fingerprint,
                                  "vehicle_selection": [v[2] for v in values],
                                  "mission_sha256": [seq.digest(v[1]) for v in values]}
    out["authorization"] = {"source": "OPERATOR_DECLARED_VIA_AGENT", "statement": statement,
                            "authenticated": False, "note": "the H2 model: a declared statement, not authenticated"}
    out["would_call"] = {"function": out["execution_path"]["entry"],
                         "args": {"mission_paths": paths, "request_key": request.get("request_key"),
                                  "authorization_statement": statement} if len(paths) == 2 else
                         {"mission_path": paths[0]}}
    out["status"] = "READY_TO_REQUEST_EXECUTION"
    return out


def main() -> int:
    request = json.loads(sys.stdin.read())
    sys.stdout.write(json.dumps(prepare(request), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
