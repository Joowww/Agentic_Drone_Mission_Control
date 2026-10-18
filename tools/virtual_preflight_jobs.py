"""Persistent asynchronous admission and read-only lookup. Never flies on lookup."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID, uuid4

from planning.mission_artifacts import artifact_for_input

from tools.vehicle_execution_lock import (
    PROJECT_ROOT, VehicleBusy, atomic_json, file_mutex, identity_alive,
    process_identity, release, reserve, restriction, utc_now,
)

RUN_ROOT = PROJECT_ROOT / "missions/generated/preflights"
LEGACY_ROOT = PROJECT_ROOT / "simulation/ros2_gazebo/results"
TERMINAL = {"PASSED", "FAILED", "BLOCKED", "ERROR"}
MAX_INPUT_BYTES = 5_000_000
KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")


def valid_run_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("run_id must be a canonical lowercase UUID")
    return value


def key_path(key):
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise ValueError("request_key must have 1..96 letters, digits, dots, underscores or hyphens")
    return RUN_ROOT / "requests" / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def run_directory(run_id):
    path = RUN_ROOT / valid_run_id(run_id)
    if not path.resolve().is_relative_to(RUN_ROOT.resolve()):
        raise ValueError("Run directory escapes the configured storage root")
    return path


def read_json(path, root):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact escapes configured storage root")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def read_mission_input(mission_path):
    # Do not let a FIFO/device or a huge input hold the admission lock indefinitely.
    descriptor = os.open(mission_path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as file:
        metadata = os.fstat(file.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Mission input must be a regular file")
        if metadata.st_size > MAX_INPUT_BYTES:
            raise ValueError("Mission input exceeds 5 MB")
        content = file.read(MAX_INPUT_BYTES + 1)
        if len(content) > MAX_INPUT_BYTES:
            raise ValueError("Mission input exceeds 5 MB")
        return content


def paths(directory):
    return {"run_directory": str(directory), "snapshot_path": str(directory / "mission.json"),
            "input_path": str(directory / "input.json"), "report_path": str(directory / "report.json"),
            "job_path": str(directory / "job.json"), "worker_log_path": str(directory / "worker.log")}


def locate_preflight_report(run_id):
    """Resolve a report only within configured run/evidence roots; read-only."""
    directory = run_directory(run_id)
    job = read_json(directory / "job.json", RUN_ROOT)
    report = read_json(directory / "report.json", RUN_ROOT)
    actual_report_path = directory / "report.json"
    if job is None and report is None:
        matches = []
        # Only fixed repository evidence locations; never open a path from JSON.
        for candidate in sorted(LEGACY_ROOT.glob("virtual_preflight_*/*_report.json")):
            historical = read_json(candidate, LEGACY_ROOT)
            if historical and historical.get("run_id") == run_id:
                matches.append((historical, candidate))
        if len(matches) > 1:
            raise ValueError("Ambiguous historical run_id: multiple persisted reports")
        if matches:
            report, actual_report_path = matches[0]
    return report, actual_report_path


def _view(run_id):
    directory = run_directory(run_id)
    job = read_json(directory / "job.json", RUN_ROOT)
    report, actual_report_path = locate_preflight_report(run_id)
    if job is None and report is None:
        return {"run_id": run_id, "job_state": "NOT_FOUND", "result_status": None, "phase": None}
    if report is not None and report.get("run_id") != run_id:
        raise ValueError("Report identity does not match requested run_id")
    if job is not None and job.get("run_id") != run_id:
        raise ValueError("Job identity does not match requested run_id")
    final = bool(report and report.get("status") in TERMINAL and report.get("finished_at"))
    identity = job.get("worker") if job else None
    alive = identity_alive(identity) if identity else None
    state = "FINISHED" if final else (job or {}).get("job_state", "UNCONFIRMED")
    if not final and job:
        if state == "FINISHED":
            state = "UNCONFIRMED"
        if identity and not alive:
            state = "INTERRUPTED"
        elif not identity:
            state = "UNCONFIRMED"  # includes admission/spawn window: no restart on lookup
    return {
        "run_id": run_id, "request_key": (job or {}).get("request_key"),
        "admission_status": (job or {}).get("admission_status", "LEGACY"),
        "job_state": state, "phase": (report or {}).get("stage", (job or {}).get("phase")),
        "result_status": report["status"] if final else None,
        "mission_sha256": (report or {}).get("mission_sha256") or (job or {}).get("input_sha256"),
        "worker_alive": alive, "worker": identity,
        "worker_error": (job or {}).get("error"),
        "created_at": (job or {}).get("created_at"),
        "worker_started_at": (job or {}).get("started_at"),
        "worker_finished_at": (job or {}).get("finished_at"),
        "paths": {**paths(directory), "report_path": str(actual_report_path)},
        "report": report, "vehicle_restriction": restriction(),
        "message": ("No final result: do not infer landing, clear a restriction or restart."
                    if state in {"INTERRUPTED", "UNCONFIRMED"} else "Read-only status; no execution initiated."),
    }


def get_virtual_preflight(*, run_id=None, request_key=None):
    """Lookup by exactly one recoverable ID. No mkdir, writes, spawn or flight."""
    try:
        if (run_id is None) == (request_key is None):
            raise ValueError("Supply exactly one of run_id or request_key")
        if request_key is not None:
            record = read_json(key_path(request_key), RUN_ROOT)
            if record is None:
                return {"request_key": request_key, "job_state": "NOT_FOUND", "result_status": None}
            run_id = record["run_id"]
        return _view(valid_run_id(run_id))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"job_state": "ERROR", "result_status": None, "errors": [str(exc)]}


def start_virtual_preflight(mission_path: str, request_key: str):
    """Persist admission, reserve v1, detach once and return without waiting for flight."""
    try:
        request_path = key_path(request_key)
        with file_mutex(RUN_ROOT / "admission.lock"):
            prior = read_json(request_path, RUN_ROOT)
            if prior is not None:
                existing = _view(valid_run_id(prior["run_id"]))
                # The key always binds to the first admission, even after completion.
                try:
                    digest = hashlib.sha256(read_mission_input(mission_path)).hexdigest()
                except OSError:
                    digest = prior["input_sha256"]
                return {**existing, "admission_status": "EXISTING" if digest == prior["input_sha256"]
                        else "REQUEST_CONFLICT", "spawned": False}
            content = read_mission_input(mission_path)
            digest = hashlib.sha256(content).hexdigest()
            source_artifact = artifact_for_input(mission_path, digest)
            run_id = str(uuid4())
            launch_token = uuid4().hex
            try:
                reserve(run_id, "asynchronous_preflight")
            except VehicleBusy as exc:
                return {"admission_status": "VEHICLE_BUSY", "job_state": "REJECTED",
                        "result_status": None, "spawned": False, "message": str(exc)}
            directory = run_directory(run_id)
            try:
                directory.mkdir(parents=True)
                (directory / "input.json").write_bytes(content)
                job = {"run_id": run_id, "request_key": request_key, "input_sha256": digest,
                       "source_artifact": source_artifact,
                       "original_source_path": str(Path(mission_path).resolve()),
                       "launch_token_sha256": hashlib.sha256(launch_token.encode()).hexdigest(),
                       "created_at": utc_now(), "admission_status": "ACCEPTED", "job_state": "ADMITTED",
                       "phase": "admitted", "worker": None, **paths(directory)}
                atomic_json(directory / "job.json", job)
                request_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_json(request_path, {"run_id": run_id, "input_sha256": digest})
            except Exception:
                release(run_id)  # no worker spawn has been attempted
                raise
            try:
                with (directory / "worker.log").open("ab") as log:
                    child = subprocess.Popen(
                        [sys.executable, "-m", "tools.virtual_preflight_worker", "--run-id", run_id,
                         "--launch-token", launch_token],
                        cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=log,
                        stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
                    )
                job.update(job_state="STARTING", phase="worker_starting", worker=process_identity(child.pid))
                atomic_json(directory / "job.json", job)
            except Exception as exc:
                # A spawn/setup ambiguity is not a reason to spawn again or clear v1.
                job.update(job_state="UNCONFIRMED", phase="worker_start_uncertain", error=str(exc))
                atomic_json(directory / "job.json", job)
            return {"run_id": run_id, "request_key": request_key, "admission_status": "ACCEPTED",
                    "job_state": job["job_state"], "phase": job["phase"], "result_status": None,
                    "mission_sha256": digest, "paths": paths(directory), "worker": job["worker"],
                    "spawned": job["job_state"] == "STARTING",
                    "message": "Admission only; validation and acceptance remain pending. Query this run, never restart it."}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"admission_status": "ERROR", "job_state": "ERROR", "result_status": None,
                "spawned": False, "errors": [str(exc)]}
