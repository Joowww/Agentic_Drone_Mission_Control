"""Persistent, ordered two-mission admissions. Queries never launch or resume work."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from models.mission_definition import MissionDefinition
from planning.mission_artifacts import artifact_for_input
from tools import virtual_preflight_jobs as jobs
from tools.simulated_vehicle import resolve_mission_vehicle
from tools.vehicle_execution_lock import (
    PROJECT_ROOT, VehicleBusy, atomic_json, end_sequence, file_mutex, identity_alive,
    process_identity, reserve_sequence, restriction, sequence_restriction, utc_now,
)

SEQUENCE_ROOT = PROJECT_ROOT / "missions/generated/preflight_sequences"
MISSION_ROOT = PROJECT_ROOT / "missions"
FINAL = {"PASSED", "FAILED", "BLOCKED", "ERROR"}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def directory(sequence_id):
    path = SEQUENCE_ROOT / jobs.valid_run_id(sequence_id)
    if not path.resolve().is_relative_to(SEQUENCE_ROOT.resolve()):
        raise ValueError("Sequence directory escapes configured root")
    return path


def request_path(key):
    jobs.key_path(key)  # same public key grammar, separate namespace
    return SEQUENCE_ROOT / "requests" / (digest(key.encode()) + ".json")


def paths(root):
    return {"directory": str(root), "plan_path": str(root / "plan.json"),
            "operation_path": str(root / "operation.json"), "coordinator_log_path": str(root / "coordinator.log")}


def stored_bytes(root, name):
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Sequence artifact escapes its directory")
    return path.read_bytes()


def load(sequence_id):
    root = directory(sequence_id)
    op = jobs.read_json(root / "operation.json", SEQUENCE_ROOT)
    if op is None:
        raise FileNotFoundError("Sequence not found")
    content = stored_bytes(root, "plan.json")
    plan = json.loads(content)
    if (not isinstance(plan, dict) or op.get("sequence_id") != sequence_id or plan.get("sequence_id") != sequence_id
            or digest(content) != op["plan_sha256"] or not isinstance(plan.get("children"), list)
            or len(plan["children"]) != 2 or not all(isinstance(c, dict) for c in plan["children"])
            or not isinstance(op.get("children"), list) or len(op["children"]) != 2
            or not all(isinstance(c, dict) for c in op["children"])):
        raise ValueError("Sequence plan/identity integrity error")
    record = jobs.read_json(request_path(plan["request_key"]), SEQUENCE_ROOT)
    if not record or record.get("sequence_id") != sequence_id or record.get("plan_sha256") != op["plan_sha256"]:
        raise ValueError("Sequence request index disagrees with plan")
    vehicles = []
    for index, child in enumerate(plan["children"]):
        content = stored_bytes(root, f"mission_{index + 1}.json")
        mission = MissionDefinition.model_validate_json(content)
        selected = resolve_mission_vehicle(mission).as_dict()
        if (child["index"] != index or digest(content) != child["mission_sha256"]
                or selected != child["vehicle_selection"]):
            raise ValueError("Sequence mission snapshot/selection integrity error")
        vehicles.append(selected["vehicle_id"])
        child_root = jobs.run_directory(child["run_id"])
        job = jobs.read_json(child_root / "job.json", jobs.RUN_ROOT)
        if not (child_root / "input.json").resolve().is_relative_to(child_root.resolve()):
            raise ValueError("Child input escapes its directory")
        if (not job or job.get("run_id") != child["run_id"] or job.get("sequence_id") != sequence_id
                or job.get("sequence_index") != index or job.get("input_sha256") != child["mission_sha256"]
                or jobs.job_vehicle_selection(job, child_root) != selected):
            raise ValueError("Sequence child admission disagrees with plan")
        if job["job_state"] == "QUEUED" and (child_root / "report.json").exists():
            raise ValueError("Queued child contradicts existing execution report; never overwrite/replay")
    if set(vehicles) != {"drone_01", "drone_02"}:
        raise ValueError("Sequence requires exactly one mission for each supported vehicle")
    return op, plan


def verified_child(child):
    # Reuse full report/snapshot/analysis verification, not a PASSED label alone.
    from planning.verified_preflight import verified_source
    from tools.vehicle_execution_lock import safe_executor_exit
    verified = verified_source(child["run_id"])
    report = verified["report"]
    if (verified["mission_sha256"] != child["mission_sha256"]
            or report.get("vehicle_selection") != child["vehicle_selection"]):
        raise ValueError("Child final report differs from authorized plan")
    safe = (report.get("execution_attempted") is False
            or safe_executor_exit(report.get("executor_result"), selection=child["vehicle_selection"]))
    return verified, safe


def get_preflight_sequence(*, sequence_id=None, request_key=None, detail=False):
    """Read fixed-root artifacts and reservations only, including after reload."""
    try:
        if (sequence_id is None) == (request_key is None):
            raise ValueError("Supply exactly one of sequence_id or request_key")
        if request_key is not None:
            record = jobs.read_json(request_path(request_key), SEQUENCE_ROOT)
            if record is None:
                return {"job_state": "NOT_FOUND", "result_status": None, "request_key": request_key}
            sequence_id = record["sequence_id"]
        op, plan = load(jobs.valid_run_id(sequence_id))
        children = []
        for index, child in enumerate(plan["children"]):
            status = jobs.get_virtual_preflight(run_id=child["run_id"])
            if status["job_state"] in {"ERROR", "NOT_FOUND"}:
                raise ValueError(f"Child lookup failed: {status}")
            saved = op["children"][index]
            if saved.get("report_sha256"):
                verified, _ = verified_child(child)
                if verified["report_sha256"] != saved["report_sha256"]:
                    raise ValueError("Final child report changed")
            child_state = saved["state"]
            if child_state == "STARTING":
                child_state = {"RUNNING": "RUNNING", "FINISHED": "VERIFYING"}.get(status["job_state"], child_state)
            if status["job_state"] in {"INTERRUPTED", "UNCONFIRMED"} and saved["state"] != "NOT_STARTED":
                child_state = "UNCONFIRMED"
            children.append({**child, **saved, "state": child_state,
                             "observed_result_status": status["result_status"], "job_state": status["job_state"],
                             "phase": status["phase"], "worker_alive": status["worker_alive"],
                             "paths": status["paths"], **({"detail": status} if detail else {})})
        alive = identity_alive(op.get("coordinator")) if op.get("coordinator") else None
        guard = sequence_restriction()
        state = op["job_state"]
        if op["result_status"] == "PASSED" and any(
            c["state"] != "FINISHED" or c["result_status"] != "PASSED" or not c.get("report_sha256") for c in children
        ):
            raise ValueError("Sequence PASSED contradicts child evidence")
        if (state != "FINISHED" and (not alive or not guard or guard["owner_id"] != sequence_id
                                    or guard["state"] == "UNCONFIRMED")
                or state == "FINISHED" and guard and guard["owner_id"] == sequence_id):
            state = "UNCONFIRMED"
        return {**op, "job_state": state, "result_status": op["result_status"] if state == "FINISHED" else None,
                "plan": plan, "children": children, "coordinator_alive": alive,
                "sequence_restriction": guard, "global_flight_restriction": restriction(),
                "paths": paths(directory(sequence_id)), "view": "detail" if detail else "summary",
                "hardware_authorized": False, "subsequent_execution_authorized": False,
                "uncertainties": (["Coordinator/outcome/reservation not confirmed; no automatic continuation or release."]
                                  if state == "UNCONFIRMED" else []),
                "message": "Read only. ACCEPTED is admission; no resume/retry or new flight consent."}
    except FileNotFoundError as exc:
        known = sequence_id is not None and (directory(sequence_id) / "operation.json").is_file()
        return {"job_state": "ERROR" if known else "NOT_FOUND", "result_status": None, "errors": [str(exc)]}
    except (ValueError, OSError, KeyError, TypeError, VehicleBusy) as exc:
        return {"job_state": "ERROR", "result_status": None, "errors": [str(exc)]}


def _inputs(mission_paths, authorization_statement):
    if (not isinstance(mission_paths, list) or len(mission_paths) != 2
            or not isinstance(authorization_statement, str) or not authorization_statement.strip()):
        raise ValueError("Exactly two ordered mission paths and a nonempty authorization_statement are required")
    values = []
    for value in mission_paths:
        if not isinstance(value, str) or not value:
            raise ValueError("Mission path must be a nonempty string")
        path = Path(value).resolve(strict=True)
        if not path.is_relative_to(MISSION_ROOT.resolve()):
            raise ValueError("Sequence mission paths must stay within the project missions root")
        content = jobs.read_mission_input(path)
        mission = MissionDefinition.model_validate_json(content)
        values.append((path, content, resolve_mission_vehicle(mission).as_dict()))
    if {v[2]["vehicle_id"] for v in values} != {"drone_01", "drone_02"}:
        raise ValueError("Provide exactly one drone_01 mission and one drone_02 mission, in requested order")
    fingerprint = digest(json.dumps({"hashes": [digest(v[1]) for v in values],
                                     "authorization_statement": authorization_statement}, sort_keys=True).encode())
    return values, fingerprint


def start_preflight_sequence(mission_paths, request_key, authorization_statement):
    """Quick admission only; exactly two detached-coordinator jobs, no flight here."""
    try:
        index_path = request_path(request_key)
        with file_mutex(jobs.RUN_ROOT / "admission.lock"):
            prior = jobs.read_json(index_path, SEQUENCE_ROOT)
            if prior:
                view = get_preflight_sequence(sequence_id=prior["sequence_id"])
                try:
                    _, fingerprint = _inputs(mission_paths, authorization_statement)
                except OSError:
                    return {**view, "admission_status": "EXISTING", "request_comparison": "UNAVAILABLE", "spawned": False}
                except ValueError as exc:
                    return {**view, "admission_status": "REQUEST_CONFLICT", "errors": [str(exc)], "spawned": False}
                return {**view, "admission_status": "EXISTING" if fingerprint == prior["fingerprint"]
                        else "REQUEST_CONFLICT", "spawned": False}
            values, fingerprint = _inputs(mission_paths, authorization_statement)
            sequence_id = str(uuid4())
            root = directory(sequence_id)
            children = [{"index": i, "run_id": str(uuid4()), "request_key": f"sequence-{sequence_id}-{i+1}",
                         "mission_sha256": digest(content), "vehicle_selection": selected,
                         "original_source_path": str(path), "source_artifact": artifact_for_input(str(path), digest(content))}
                        for i, (path, content, selected) in enumerate(values)]
            plan = {"schema_version": 1, "sequence_id": sequence_id, "request_key": request_key,
                    "authorization": {"source": "OPERATOR_DECLARED_VIA_AGENT", "statement": authorization_statement,
                                      "scope": "These two ordered snapshots only; SITL; no further flights or hardware"},
                    "children": children}
            plan_bytes = json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False).encode()
            plan_hash = digest(plan_bytes)
            guard_children = [{"owner_id": c["run_id"], "vehicle": c["vehicle_selection"]["simulated_vehicle"],
                               "input_sha256": c["mission_sha256"]} for c in children]
            try:
                reserve_sequence(sequence_id, plan_hash, guard_children)
            except VehicleBusy as exc:
                return {"admission_status": "VEHICLE_BUSY", "job_state": "REJECTED", "result_status": None,
                        "spawned": False, "message": str(exc)}
            token = uuid4().hex
            try:
                root.mkdir(parents=True)
                (root / "plan.json").write_bytes(plan_bytes)
                for i, (_, content, _) in enumerate(values):
                    (root / f"mission_{i+1}.json").write_bytes(content)
                    child = children[i]
                    child_root = jobs.run_directory(child["run_id"])
                    job = {"schema_version": 2, "sequence_id": sequence_id, "sequence_index": i,
                           "vehicle_selection": child["vehicle_selection"], "run_id": child["run_id"],
                           "request_key": child["request_key"], "input_sha256": child["mission_sha256"],
                           "source_artifact": child["source_artifact"], "original_source_path": child["original_source_path"],
                           "launch_token_sha256": None, "created_at": utc_now(), "admission_status": "ACCEPTED",
                           "job_state": "QUEUED", "phase": "sequence_queued", "worker": None, **jobs.paths(child_root)}
                    jobs.persist_admission(child_root, content, job)
                op = {"schema_version": 1, "sequence_id": sequence_id, "request_key": request_key,
                      "plan_sha256": plan_hash, "created_at": utc_now(), "admission_status": "ACCEPTED",
                      "job_state": "ADMITTED", "phase": "admission", "coordinator": None,
                      "launch_token_sha256": digest(token.encode()), "result_status": None, "reasons": [],
                      "children": [{"state": "NOT_STARTED", "result_status": None} for _ in children]}
                atomic_json(root / "operation.json", op)
                index_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_json(index_path, {"sequence_id": sequence_id, "plan_sha256": plan_hash, "fingerprint": fingerprint})
            except Exception:
                end_sequence(sequence_id, plan_hash, unspawned=True)
                raise
            try:
                with (root / "coordinator.log").open("ab") as log:
                    child = subprocess.Popen([sys.executable, "-m", "tools.preflight_sequence_worker",
                                              "--sequence-id", sequence_id, "--launch-token", token],
                                             cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=log,
                                             stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
                op.update(job_state="STARTING", phase="coordinator_starting", coordinator=process_identity(child.pid))
            except Exception as exc:
                op.update(job_state="UNCONFIRMED", phase="spawn_uncertain", reasons=[str(exc)])
            atomic_json(root / "operation.json", op)
            return {**op, "paths": paths(root), "plan": plan, "spawned": op["job_state"] == "STARTING",
                    "message": "Admission only, not validation/PASSED. Query the same sequence; never retry flights."}
    except (ValueError, OSError, KeyError, TypeError, VehicleBusy) as exc:
        return {"admission_status": "ERROR", "job_state": "ERROR", "result_status": None,
                "spawned": False, "errors": [str(exc)]}
