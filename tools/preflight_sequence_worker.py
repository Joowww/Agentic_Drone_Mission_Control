"""Detached one-shot coordinator; existing child workers execute inline, never concurrently."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import traceback
from uuid import uuid4

from models.mission_definition import MissionDefinition
from tools import preflight_sequences as seq
from tools import virtual_preflight_jobs as jobs
from tools.virtual_preflight_worker import run_worker
from tools.hermes_mission_validation import validate_mission
from tools.simulation_mission_executor import _execution_compatibility_errors
from tools.vehicle_execution_lock import (
    VehicleBusy, atomic_json, claim_sequence, complete_sequence_child, end_sequence,
    file_mutex, process_identity, reserve_sequence_child, restriction, sequence_restriction, utc_now,
)


def run_coordinator(sequence_id, launch_token):
    root = seq.directory(sequence_id)
    with file_mutex(jobs.RUN_ROOT / "admission.lock"):
        op, plan = seq.load(sequence_id)
        identity = process_identity()
        if (identity is None or not launch_token or seq.digest(launch_token.encode()) != op["launch_token_sha256"]
                or op["job_state"] not in {"ADMITTED", "STARTING"}
                or op.get("coordinator") not in (None, identity)):
            return False
        claim_sequence(sequence_id, op["plan_sha256"])
        op.update(job_state="RUNNING", phase="prevalidate_both", coordinator=identity, started_at=utc_now())
        atomic_json(root / "operation.json", op)
    print(f"{utc_now()} sequence={sequence_id} coordinator claimed", flush=True)

    def persist():
        atomic_json(root / "operation.json", op)

    def finish(result, reasons):
        if result == "PASSED":
            for index, child in enumerate(plan["children"]):
                verified, safe = seq.verified_child(child)
                if (not safe or verified["report"]["status"] != "PASSED"
                        or verified["report_sha256"] != op["children"][index]["report_sha256"]):
                    raise ValueError("Final pair evidence changed; PASSED/release forbidden")
        op.update(job_state="FINALIZING", phase="finish", proposed_result=result, reasons=reasons)
        persist()
        end_sequence(sequence_id, op["plan_sha256"])
        op.update(job_state="FINISHED", result_status=result, finished_at=utc_now())
        persist()
        print(f"{utc_now()} sequence={sequence_id} result={result}", flush=True)
        return True

    try:
        checks = []
        for index in range(2):
            mission = MissionDefinition.model_validate_json(seq.stored_bytes(root, f"mission_{index+1}.json"))
            validation = validate_mission(mission)
            errors = _execution_compatibility_errors(mission)
            if mission.route.home is None:
                errors.append("Simulation mapping requires a mission home")
            checks.append({"validation": validation, "compatibility_errors": errors})
        op["prevalidation"] = checks
        persist()
        if any(c["compatibility_errors"] or c["validation"]["execution_status"] != "APPROVED"
               or c["validation"]["errors"] for c in checks):
            return finish("BLOCKED", ["Both missions must pass deterministic validation and compatibility before any child."])

        for index, child in enumerate(plan["children"]):
            seq.load(sequence_id)  # verify BOTH immutable snapshots and queued/finished child inputs again
            if index:
                previous, safe = seq.verified_child(plan["children"][0])
                if (not safe or previous["report"]["status"] != "PASSED"
                        or previous["report_sha256"] != op["children"][0]["report_sha256"]):
                    raise ValueError("First child's final evidence changed; second child forbidden")
            with file_mutex(jobs.RUN_ROOT / "admission.lock"):
                child_root = jobs.run_directory(child["run_id"])
                job = jobs.read_json(child_root / "job.json", jobs.RUN_ROOT)
                if job["job_state"] != "QUEUED" or job.get("worker") is not None:
                    raise ValueError("Child is not an untouched queued job; no retry")
                reserve_sequence_child(sequence_id, op["plan_sha256"], index)
                token = uuid4().hex
                job.update(job_state="ADMITTED", phase="sequence_dispatch", launch_token_sha256=seq.digest(token.encode()))
                atomic_json(child_root / "job.json", job)
                op["children"][index].update(state="STARTING", started_at=utc_now())
                op.update(phase=f"child_{index+1}")
                persist()  # durable dispatch intent BEFORE invoking any worker/executor
            # The whole coordinator is detached; every child additionally retains its own worker log.
            # No reusable ambient flight authority spans these calls: run_worker creates/revokes each scope.
            with (child_root / "worker.log").open("a", encoding="utf-8") as log:
                with redirect_stdout(log), redirect_stderr(log):
                    done = run_worker(child["run_id"], token)
            if not done:
                raise ValueError("Child worker failed/disappeared or refused its claim; no next flight")
            seq.load(sequence_id)
            job = jobs.read_json(child_root / "job.json", jobs.RUN_ROOT)
            verified, safe = seq.verified_child(child)
            guard = sequence_restriction()
            if (job["job_state"] != "FINISHED" or not safe or not guard
                    or guard["owner_id"] != sequence_id or guard["plan_sha256"] != op["plan_sha256"]
                    or restriction() != guard):
                raise VehicleBusy("No consistent final child/landing/release evidence; sequence stays restricted")
            report = verified["report"]
            op["children"][index].update(state="FINISHED", result_status=report["status"],
                                         report_sha256=verified["report_sha256"], finished_at=utc_now(),
                                         reasons=report.get("reasons", []))
            persist()
            if report["status"] != "PASSED":
                return finish(report["status"], [f"Child {index+1} is {report['status']}; subsequent child not started."])
            complete_sequence_child(sequence_id, op["plan_sha256"], index)
        return finish("PASSED", [])
    except BaseException as exc:
        traceback.print_exc()
        # Never turn process disappearance, corrupt evidence or a missing lease into a safe release.
        try:
            end_sequence(sequence_id, op["plan_sha256"], uncertain=True)
        except (ValueError, OSError, KeyError, TypeError, VehicleBusy) as guard_error:
            # Persist the contradiction even when a damaged/missing guard cannot be updated.
            op["guard_error"] = str(guard_error)
        for child in op["children"]:
            if child["state"] == "STARTING":
                child["state"] = "UNCONFIRMED"
        op.update(job_state="UNCONFIRMED", result_status=None, phase="reconciliation_required",
                  reasons=[f"{type(exc).__name__}: {exc}"], interrupted_at=utc_now())
        persist()
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--launch-token", required=True)
    args = parser.parse_args()
    return 0 if run_coordinator(jobs.valid_run_id(args.sequence_id), args.launch_token) else 1


if __name__ == "__main__":
    raise SystemExit(main())
