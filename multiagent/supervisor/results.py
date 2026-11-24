"""Results: one per vehicle and one global, compatible with SafeFlight Desktop's contracts.

  results/<vehicle_id>/vehicle_result.json   tfg.multiagent.vehicle-result/1, ALWAYS written (plan, validation,
                                             approval, execution state, errors, evidence)
  results/<vehicle_id>/result.json           safeflight.sitl-result v1, written ONLY when something executed
                                             (TEST_DOUBLE -> synthetic: true; REAL_SITL -> synthetic: false). A plan
                                             that was only validated or approved gets no SafeFlight result.
  results/<vehicle_id>/result.receipt.json   safeflight.sitl-receipt v1 (HMAC-SHA256), ONLY for REAL_SITL results
                                             and only with a key file supplied by the operator (never in the repo)
  results/global_result.json                 tfg.multiagent.global-result/1

Global status (``global_status``): COMPLETED only when every mandatory vehicle has a REAL_SITL observation COMPLETED
with no failed criterion. A test double can reach COMPLETED_TEST_DOUBLE at most; a validated or approved plan is
never reported as executed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import shutil

from multiagent.supervisor.plans import sha256_bytes, sha256_file, write_json

VEHICLE_SCHEMA = "tfg.multiagent.vehicle-result/1"
GLOBAL_SCHEMA = "tfg.multiagent.global-result/1"
RECEIPT_DOMAIN = "safeflight.sitl-receipt/1"
RUN_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SF_STATUS = {"COMPLETED": "completed", "FAILED": "failed", "ABORTED": "aborted", "TIMEOUT": "timeout"}
CLASS_NAMES = {"ArduCopter": "ArduCopter", "ArduRover": "ArduRover"}


def safeflight_result(obs: dict, vehicle: dict, *, plan_name: str, run_id: str, group_id: str, created_at: str,
                      producer: dict, environment: dict, evidence: list[dict]) -> dict:
    if obs["execution_status"] not in SF_STATUS:
        raise ValueError("a SafeFlight result describes an execution; this vehicle did not execute")
    synthetic = obs["data_kind"] != "REAL_SITL"
    criteria = obs["criteria"]
    failed = [c["id"] for c in criteria if c["result"] == "fail"]
    mandatory = {"mission_readback_match", "all_waypoints_reached", "mission_end_reached"}
    unevaluated = [c["id"] for c in criteria if c["id"] in mandatory and c["result"] != "pass"]
    if obs["execution_status"] != "COMPLETED" or failed:
        verdict = {"result": "fail", "reasons": [r for r in [obs.get("failure_reason")] if r]
                   + [f"criterion {c} failed" for c in failed] or ["execution not completed"]}
    elif unevaluated or obs["transformed"]:
        verdict = {"result": "inconclusive", "reasons": [f"criterion {c} not evaluated" for c in unevaluated]
                   + (["the executed artifact is not the .plan (transformed)"] if obs["transformed"] else [])}
    else:
        verdict = {"result": "pass", "reasons": []}
    execution = {"status": SF_STATUS[obs["execution_status"]], "started_at": obs["started_at"],
                 "finished_at": obs["finished_at"]}
    if obs["execution_status"] != "COMPLETED":
        execution["failure_reason"] = obs.get("failure_reason") or "not completed"
    executed_sha = obs["plan_sha256"] if not obs["transformed"] else (obs.get("executed_artifact_sha256")
                                                                       or obs["plan_sha256"])
    return {"schema": "safeflight.sitl-result", "schema_version": 1, "run_id": run_id, "group_id": group_id,
            "synthetic": synthetic, "created_at": created_at, "producer": producer,
            "vehicle": {"vehicle_id": vehicle["vehicle_id"], "autopilot": "ArduPilot",
                        "vehicle": CLASS_NAMES[vehicle["vehicle_class"]],
                        **({"frame": "synthetic"} if synthetic else {})},
            "mission": {"source_plan_name": plan_name, "source_plan_sha256": obs["plan_sha256"],
                        "executed_plan_sha256": executed_sha, "transformed": bool(obs["transformed"]),
                        "transformations": obs["transformations"]},
            "environment": environment, "execution": execution, "verdict": verdict, "criteria": criteria,
            "metrics": {k: v for k, v in obs["metrics"].items() if isinstance(v.get("value"), (int, float))},
            "evidence": evidence}


def copy_evidence(obs: dict, run_dir: Path) -> list[dict]:
    """Evidence files are copied under run_dir/evidence and hashed after copying (relative POSIX paths)."""
    out = []
    for i, item in enumerate(obs.get("evidence") or []):
        src = item.get("source_path")
        if not src:
            continue
        dest = Path(run_dir) / "evidence" / f"{i:02d}_{Path(src).name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        got = sha256_file(dest)
        if item.get("sha256") and got != item["sha256"]:
            raise ValueError(f"evidence changed while copying: {src}")
        out.append({"path": f"evidence/{dest.name}", "kind": item["kind"], "sha256": got,
                    **({"description": item["description"]} if item.get("description") else {})})
    return out


def write_synthetic_log(run_dir: Path, obs: dict) -> dict:
    path = Path(run_dir) / "evidence" / "executor.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TEST DOUBLE - NOT A SIMULATOR RUN\nvehicle {obs['vehicle_id']} task {obs['task_id']} "
                    f"scripted outcome {obs['execution_status']}\n", encoding="utf-8")
    return {"path": "evidence/executor.log", "kind": "executor_log", "sha256": sha256_file(path),
            "description": "Executor log (synthetic test double)"}


def write_receipt(run_dir: Path, result: dict, key: bytes) -> Path:
    """safeflight.sitl-receipt v1 over the exact bytes of result.json on disk. Refused for synthetic results."""
    if result.get("synthetic") is not False:
        raise PermissionError("no trusted receipt for a synthetic result")
    if not RUN_ID.fullmatch(result["run_id"]):
        raise ValueError("run_id not valid for a receipt")
    if len(key) < 32:
        raise ValueError("receipt key must be at least 32 bytes")
    data = (Path(run_dir) / "result.json").read_bytes()
    digest = sha256_bytes(data)
    msg = f"{RECEIPT_DOMAIN}\n{result['run_id']}\n{digest}\n".encode("utf-8")
    receipt = {"schema": "safeflight.sitl-receipt", "schema_version": 1, "algorithm": "HMAC-SHA256",
               "key_id": hashlib.sha256(b"safeflight.sitl-receipt/key-id\n" + key).hexdigest()[:16],
               "run_id": result["run_id"], "result_sha256": digest,
               "hmac_sha256": hmac.new(key, msg, hashlib.sha256).hexdigest()}
    path = Path(run_dir) / "result.receipt.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


def load_key_file(path: Path) -> bytes:
    text = Path(path).read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError("key file must hold 64 lowercase hex characters")
    return bytes.fromhex(text)


def vehicle_result(vehicle: dict, *, validation: str, approval: dict | None, gate: dict | None, obs: dict | None,
                   errors: list[str], safeflight: dict | None) -> dict:
    executed = obs is not None and obs["execution_status"] in SF_STATUS
    return {"schema": VEHICLE_SCHEMA, "vehicle_id": vehicle["vehicle_id"], "vehicle_class": vehicle["vehicle_class"],
            "task_id": vehicle["task_id"], "mandatory": vehicle.get("mandatory", True),
            "plan": vehicle["plan"], "validation": validation,
            "approval": {"status": "APPROVED" if approval else "NOT_APPROVED",
                         "approval_id": (approval or {}).get("approval_id"),
                         "source": (approval or {}).get("source")},
            "gate": gate, "execution": {
                "state": obs["execution_status"] if obs else "NOT_EXECUTED",
                "confirmed": bool(executed), "data_kind": obs["data_kind"] if obs else None,
                "executor": obs["executor"] if obs else None,
                "physical_effect": bool(obs and obs.get("physical_effect"))},
            "metrics": (obs or {}).get("metrics") or {}, "criteria": (obs or {}).get("criteria") or [],
            "errors": errors, "safeflight_result": safeflight}


def global_status(vehicles: list[dict], *, planning_status: str) -> str:
    if planning_status != "PLANNED":
        return planning_status                     # BLOCKED / NEEDS_CLARIFICATION / REFUSED_UNSAFE / INFEASIBLE
    mandatory = [v for v in vehicles if v["mandatory"]]
    states = [v["execution"]["state"] for v in mandatory]
    kinds = {v["execution"]["data_kind"] for v in mandatory if v["execution"]["confirmed"]}
    clean = lambda v: not any(c["result"] == "fail" for c in v["criteria"])  # noqa: E731
    if all(s == "COMPLETED" for s in states) and all(clean(v) for v in mandatory):
        return "COMPLETED" if kinds == {"REAL_SITL"} else "COMPLETED_TEST_DOUBLE"
    if any(s in ("FAILED", "ABORTED", "TIMEOUT") for s in states):
        return "PARTIAL" if any(s == "COMPLETED" for s in states) else "FAILED"
    if any(s == "COMPLETED" for s in states):
        return "PARTIAL_IN_PROGRESS_OR_BLOCKED"
    if any(v["execution"]["state"] in ("BLOCKED", "CANCELLED_DEPENDENCY") for v in mandatory):
        return "EXECUTION_BLOCKED"
    if any(v["execution"]["state"] == "READY_TO_REQUEST_EXECUTION" for v in mandatory):
        return "READY_TO_REQUEST_EXECUTION"
    if all(v["approval"]["status"] == "APPROVED" for v in mandatory):
        return "APPROVED_NOT_EXECUTED"
    return "PLANNED_PENDING_APPROVAL"


def global_result(*, manifest: dict | None, mission_id: str, planning_status: str, vehicles: list[dict],
                  reasons: list[str], decisions_sha256: str | None, trace_sha256: str | None) -> dict:
    status = global_status(vehicles, planning_status=planning_status)
    return {"schema": GLOBAL_SCHEMA, "mission_id": mission_id, "status": status,
            "manifest_sha256": (manifest or {}).get("manifest_sha256"),
            "data_kind": (manifest or {}).get("data_kind"),
            "vehicles": [{"vehicle_id": v["vehicle_id"], "vehicle_class": v["vehicle_class"],
                          "task_id": v["task_id"], "mandatory": v["mandatory"], "plan_sha256": v["plan"]["sha256"],
                          "validation": v["validation"], "approval": v["approval"]["status"],
                          "execution_state": v["execution"]["state"],
                          "execution_confirmed": v["execution"]["confirmed"],
                          "data_kind": v["execution"]["data_kind"], "errors": v["errors"],
                          "metrics": v["metrics"]} for v in vehicles],
            "reasons": reasons, "decisions_sha256": decisions_sha256, "trace_sha256": trace_sha256,
            "completion_rule": "COMPLETED requires every mandatory vehicle COMPLETED in REAL_SITL with no failed "
                               "criterion; a test double reaches COMPLETED_TEST_DOUBLE at most"}


def write_vehicle(results_dir: Path, vr: dict) -> None:
    write_json(Path(results_dir) / vr["vehicle_id"] / "vehicle_result.json", vr)
