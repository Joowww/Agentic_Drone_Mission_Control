"""Detached one-shot worker; never serves MCP and never resumes an old run."""
from __future__ import annotations

import argparse
import hashlib
import traceback
from tools.simulated_vehicle import recorded_report_selection

from tools import virtual_preflight_jobs as jobs
from tools.vehicle_execution_lock import (
    atomic_json, execution_scope, file_mutex, mark_uncertain, process_identity,
    release, safe_executor_exit, utc_now,
)


def run_worker(run_id, launch_token=None):
    directory = jobs.run_directory(run_id)
    # Admission holds this lock through Popen and publication of worker identity.
    with file_mutex(jobs.RUN_ROOT / "admission.lock"):
        job = jobs.read_json(directory / "job.json", jobs.RUN_ROOT)
        identity = process_identity()
        token_hash = hashlib.sha256(launch_token.encode()).hexdigest() if launch_token else None
        if (identity is None or not job or token_hash != job.get("launch_token_sha256")
                or job["job_state"] not in {"ADMITTED", "STARTING"}
                or job.get("worker") not in (None, identity)):
            return False  # duplicate, terminal, interrupted or different worker: never fly
        try:
            selected = jobs.job_vehicle_selection(job, directory, for_execution=True)
        except (ValueError, OSError, KeyError, TypeError):
            return False  # corrupted admission never launches or releases a reservation
        vehicle = selected["simulated_vehicle"]
        job.update(worker=identity, job_state="RUNNING", phase="workflow", started_at=utc_now())
        atomic_json(directory / "job.json", job)
    print(f"{utc_now()} run={run_id} worker claimed admission", flush=True)
    try:
        # Import the existing graph only after identity has been published.
        from tools.virtual_preflight import run_preflight_in_directory
        with execution_scope(run_id, vehicle):
            report = run_preflight_in_directory(
                directory / "input.json", run_id, directory, started_at=job["created_at"],
                expected_sha256=job["input_sha256"], persist_progress=True,
                source_artifact=job.get("source_artifact"),
                vehicle_selection=selected,
            )
        report_selection = recorded_report_selection(report)
        if report_selection is not None and report_selection != selected:
            raise ValueError("Worker report vehicle differs from its admission")
        if report.get("mission_sha256") != job["input_sha256"]:
            raise ValueError("Worker report mission hash differs from its admission")
        job.update(job_state="FINISHED", phase=report.get("stage"), finished_at=utc_now())
        atomic_json(directory / "job.json", job)
        if (report.get("status") in jobs.TERMINAL and report.get("report_persisted") is True
                and (report.get("execution_attempted") is False
                     or safe_executor_exit(report.get("executor_result"), selection=selected))):
            release(run_id, vehicle)
        else:
            mark_uncertain(run_id, vehicle)
        print(f"{utc_now()} run={run_id} result={report.get('status')} worker finished", flush=True)
        return True
    except BaseException as exc:
        # In particular, no automatic LAND claim, retry, or clearing of the lease.
        traceback.print_exc()
        mark_uncertain(run_id, vehicle)
        job.update(job_state="UNCONFIRMED", phase="worker_exception", error=f"{type(exc).__name__}: {exc}")
        atomic_json(directory / "job.json", job)
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--launch-token", required=True)
    args = parser.parse_args()
    return 0 if run_worker(jobs.valid_run_id(args.run_id), args.launch_token) else 1


if __name__ == "__main__":
    raise SystemExit(main())
