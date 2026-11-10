"""R1 coordination after a verified aerial sequence: dependency -> candidate -> eligibility -> authorization ->
admission (through an explicit executor interface) -> tracking -> acceptance -> scenario result.

The aerial coordinator (tools.preflight_sequences) is closed once FINISHED and is not modified: R1 is a
later stage bound to its sequence by id and hashes. State lives in ONE record per request key, written with
the same key grammar, atomic JSON and mutex helpers as the existing admissions. This module never starts or
stops services, never reserves or releases vehicles and never sends a command: the executor does, or refuses.
Preparing and querying never admit. A lost admission response is never answered with another admission.

Executor interface (kept minimal): admit(task), lookup(request_key), query(run_id). Per-attempt facts are
derived by the adapter from the executor's existing read-only checks; the executor keeps the final decision.

Provenance: VERIFIED requires that the evaluated result is the one held in the REAL executor's local records
for this request (key index -> job -> stored request/authorization -> hash-checked report). Labels such as
origin EXECUTED, an adapter flag or a result's own binding are never enough. Limit: anyone able to rewrite all
of those local records consistently can forge them; hashes here detect inconsistency, they do not
authenticate who produced a record.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from planning.artifact_store import fingerprint as executor_fingerprint
from planning.artifact_store import request_path as executor_request_path
from reporting import agri_scenario_summary as summary
from tools import virtual_preflight_jobs as jobs
from tools.vehicle_execution_lock import PROJECT_ROOT, atomic_json, file_mutex, utc_now

TASK_ROOT = PROJECT_ROOT / "missions/generated/agri_ground_tasks"
RECORD_SCHEMA = "tfg.agri-r1-task/2"
NAVIGATION_KIND = "ROVER_NAVIGATE_V1"
# Coordinator states (one record per request key). Live states are re-queried read-only; none is ever "fixed"
# by re-admitting or restarting:
#   ADMISSION_REQUESTED  intent persisted, executor called after it     ADMISSION_UNCONFIRMED  reply lost/unknown
#   ADMITTED             admission accredited (reply or key lookup)     ADMITTED_NO_WORKER     executor records no worker
#   START_REQUESTED      start intent persisted before the call         START_UNCONFIRMED      start reply lost/refused
#   WORKER_OBSERVED      executor reports a live, owning worker         WORKER_UNCONFIRMED     identity, no confirmation
#   CLOSURE_PENDING      goal facts recorded; executor closure UNCONFIRMED (e.g. armed after HOLD)
# Terminal: VERIFIED, VERIFIED_SYNTHETIC, FAILED, UNCERTAIN, EXECUTION_FAILED, REJECTED_RESULT, REJECTED_BY_EXECUTOR.
LIVE = {"ADMISSION_REQUESTED", "ADMISSION_UNCONFIRMED", "ADMITTED", "ADMITTED_NO_WORKER", "START_REQUESTED",
        "START_UNCONFIRMED", "WORKER_OBSERVED", "WORKER_UNCONFIRMED", "CLOSURE_PENDING"}
TERMINAL = {"REJECTED_BY_EXECUTOR", "FAILED", "UNCERTAIN", "EXECUTION_FAILED", "REJECTED_RESULT", "VERIFIED",
            "VERIFIED_SYNTHETIC"}
AUTHORIZATION_KEYS = {"source", "statement", "candidate_sha256", "mission_sha256", "session_id"}


class GroundExecutor(Protocol):
    def admit(self, task: dict) -> dict: ...                # ADMITTED (run_id) / BLOCKED / REJECTED + reason
    def lookup(self, request_key: str) -> dict | None: ...  # read-only; None = no accredited lookup
    def query(self, run_id: str) -> dict: ...               # read-only; report.r1_ground_result when FINISHED
    def start(self, run_id: str, record: dict) -> dict: ...  # STARTED / UNSUPPORTED / REJECTED (+ reason)


def _executor():
    from tools import rover_ground_executor
    return rover_ground_executor


class RoverGroundExecutorAdapter:
    """Real route over tools.rover_ground_executor, unchanged. Refusals are returned verbatim."""
    kind = "ROVER_GROUND_EXECUTOR"

    def __init__(self, *, physical_factory=None, readiness=None, cancelled=None):
        # The PHYSICAL interface (adapter factory, readiness, cancellation) is the executor's/the rover's to supply;
        # without it start_ground_trial refuses. Tests inject a synthetic kinematic session here.
        self.physical_factory, self.readiness, self.cancelled = physical_factory, readiness, cancelled
        self.launch_tokens = {}  # legacy bounded-control token, memory only; navigation never uses it

    def facts(self) -> dict:
        """Per-attempt facts from the executor's own read-only executor_facts() (no filesystem/ROS access)."""
        executor = _executor()
        if not hasattr(executor, "executor_facts"):
            return {"kind": self.kind, "policy_enabled": executor.OPERATIONAL_ROVER_ENABLED is True,
                    "navigation_request_supported": None,
                    "navigation_request_detail": "EXECUTOR_HAS_NO_executor_facts"}
        facts = executor.executor_facts()
        return {"kind": self.kind, "policy_enabled": facts.get("policy_enabled") is True,
                "navigation_request_supported": facts.get("navigation_request_supported") is True
                and facts.get("navigation_kind") == NAVIGATION_KIND,
                "navigation_request_detail": facts.get("navigation_kind"), "executor_facts": facts}

    def admit(self, task: dict) -> dict:
        executor = _executor()
        try:  # the executor applies its own gates in its own order (policy first, then validation)
            reply = executor.admit_ground_trial(task["mission_path"], task["request_key"], task["request"],
                                                task["executor_authorization"],
                                                coordination_context=task["coordination_context"])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return {"status": "REJECTED", "reason": f"{type(exc).__name__}: {exc}"}
        if reply.get("status") == "ADMITTED" and reply.get("launch_token"):
            self.launch_tokens[reply["run_id"]] = reply["launch_token"]
        return {**{k: v for k, v in reply.items() if k != "launch_token"}, "status": reply.get("status"),
                "reason": reply.get("reason") or reply.get("validation")}

    def lookup(self, request_key: str) -> dict:
        """The executor's own read-only lookup (validates index, snapshot and scope)."""
        return _executor().lookup_ground_trial(request_key)

    def query(self, run_id: str) -> dict:
        return _executor().query_ground_trial(run_id)

    def start(self, run_id: str, record: dict) -> dict:
        """start_ground_trial with a start declaration rebuilt from DURABLE records (no token, no memory).
        Synchronous: the caller becomes the worker. Its returned report is not trusted; tracking re-reads it."""
        executor = _executor()
        if not hasattr(executor, "start_ground_trial"):
            return {"status": "UNSUPPORTED", "reason": "EXECUTOR_HAS_NO_RECOVERABLE_START_ENTRY"}
        view = executor.query_ground_trial(run_id)
        binding = view.get("coordination_binding") or {}
        declaration = {"run_id": run_id, "input_sha256": view.get("input_sha256"),
                       **{k: binding.get(k) for k in ("candidate_sha256", "session_id", "authorization_sha256")},
                       "statement": f"Start of the admitted R1 job for request {record['request_key']}"}
        if any(declaration[k] != record[f] for k, f in (("candidate_sha256", "candidate_sha256"),
                                                         ("authorization_sha256", "authorization_sha256"))):
            return {"status": "REJECTED", "reason": "EXECUTOR_BINDING_DIFFERS_FROM_RECORD"}
        options = {k: v for k, v in (("adapter_factory", self.physical_factory), ("readiness", self.readiness),
                                     ("cancelled", self.cancelled)) if v is not None}
        try:
            reply = executor.start_ground_trial(run_id, declaration, **options)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return {"status": "REJECTED", "reason": f"{type(exc).__name__}: {exc}"}
        if reply.get("status") == "BLOCKED":
            return {"status": "REJECTED", "reason": reply.get("reason")}
        return {"status": "STARTED", "worker_report_status": reply.get("status")}


class RecordIntegrityError(ValueError):
    pass


def _sha(value) -> str:
    """ONE digest function on both sides of the boundary: planning.artifact_store.fingerprint
    (JSON, sort_keys, ensure_ascii=False, allow_nan=False, UTF-8, SHA-256)."""
    return executor_fingerprint(value)


def _paths(root: Path, request_key: str) -> tuple[Path, Path]:
    jobs.key_path(request_key)  # same public key grammar as every other admission
    name = hashlib.sha256(request_key.encode()).hexdigest()
    return root / "records" / f"{name}.json", root / "admission.lock"


def prepare(view: dict, inputs: dict | None, executor) -> dict:
    """Pure: preparation with facts of THIS attempt. Never admits, never persists."""
    facts = executor.facts()
    return summary.prepare_ground_task(view, inputs=inputs, executor_facts=facts)


def navigation_request(candidate: dict) -> dict:
    """ROVER_NAVIGATE_V1 from the candidate only. Missing operator limits raise; nothing is defaulted."""
    target = candidate["target_in_rover_frame"]["value"]
    limits = candidate["execution_limits"]["value"]
    controller, visit = limits["controller"], candidate["visit_parameters"]
    if candidate["frame_transform"]["value"].get("to_frame") != target["frame"]:
        raise ValueError("target frame is not the verified transformation's frame")
    goal = {"x_m": target["x_m"], "y_m": target["y_m"], "yaw_rad": controller["yaw_rad"], "frame": target["frame"],
            "unit": "m", "transform": "IDENTITY_SAME_ACCREDITED_FRAME",  # target already in the accredited frame
            "tolerance_m": candidate["ground_tolerance_m"]["value"], "yaw_tolerance_rad": controller["yaw_tolerance_rad"],
            "dwell_s": visit["dwell_s"], "command_hz": controller["command_hz"], "timeout_s": visit["global_timeout_s"],
            "no_progress_s": visit["no_progress_window_s"], "progress_m": visit["min_progress_m"],
            "progress_rad": controller["progress_rad"], "max_samples": controller["max_samples"]}
    request = {"kind": NAVIGATION_KIND, "limits": dict(limits["rover_limits"]), "goal": goal}
    if candidate.get("finalization_policy"):
        request["finalization"] = candidate["finalization_policy"]["value"]  # the authorized closure policy
    return request


def _authorization_problem(authorization, prepared) -> str | None:
    """A declared scope bound to the exact candidate and session; not human authentication."""
    candidate = prepared["candidate"] or {}
    mission = (candidate.get("rover_mission") or {}).get("value") or {}
    if not isinstance(authorization, dict) or set(authorization) != AUTHORIZATION_KEYS:
        return "AUTHORIZATION_ABSENT_OR_MALFORMED"
    if authorization["source"] != "OPERATOR_DECLARED" or not str(authorization["statement"]).strip():
        return "AUTHORIZATION_NOT_AN_OPERATOR_DECLARATION"
    if not isinstance(authorization["session_id"], str) or not authorization["session_id"]:
        return "AUTHORIZATION_WITHOUT_SESSION"
    if (authorization["candidate_sha256"] != prepared["candidate_sha256"]
            or authorization["mission_sha256"] != mission.get("sha256")):
        return "AUTHORIZATION_SCOPE_DIFFERS_FROM_CANDIDATE"
    return None


def _check(record: dict) -> dict:
    """Recompute every bound hash; a changed record is never acted on."""
    task = record.get("task") or {}
    if (record.get("schema") != RECORD_SCHEMA or _sha(record.get("candidate")) != record.get("candidate_sha256")
            or _sha(record.get("authorization")) != record.get("authorization_sha256")
            or _sha(record.get("view")) != record.get("view_sha256")
            or _sha(task) != record.get("task_sha256")
            or _sha([record["candidate_sha256"], record["authorization_sha256"], record["view_sha256"],
                     record["task_sha256"]]) != record.get("fingerprint")):
        raise RecordIntegrityError("R1 record hashes do not match its content; no action taken")
    return record


def _load(path: Path, root: Path):
    record = jobs.read_json(path, root)
    return None if record is None else _check(record)


def _transition(path: Path, record: dict, state: str, **fields) -> dict:
    record.update(state=state, **fields)
    record.setdefault("history", []).append({"at": utc_now(), "state": state,
                                             **({"reason": fields["reason"]} if fields.get("reason") else {})})
    atomic_json(path, record)
    return record


def request(root: Path, request_key: str, view: dict, inputs: dict | None, authorization: dict | None,
            executor) -> dict:
    """Idempotent admission request under the admission mutex: at most one admission intent per key.
    Preparation is recomputed INSIDE the mutex, so eligibility is that of this attempt."""
    path, lock = _paths(root, request_key)
    with file_mutex(lock):
        try:
            prior = _load(path, root)
        except RecordIntegrityError as exc:
            return {"request_status": "RECORD_INTEGRITY_ERROR", "reason": str(exc), "executor_called": False}
        prepared = prepare(view, inputs, executor)
        if prior is not None:
            same = (prior["candidate_sha256"] == prepared["candidate_sha256"]
                    and prior["authorization_sha256"] == _sha(authorization) and prior["view_sha256"] == _sha(view))
            return {**prior, "request_status": "EXISTING" if same else "REQUEST_CONFLICT", "executor_called": False}
        refusal = ("DEPENDENCY_" + prepared["stages"]["dependency"] if prepared["stages"]["dependency"] != "MET"
                   else "NO_CANDIDATE" if prepared["candidate"] is None
                   else "NOT_ELIGIBLE" if prepared["stages"]["eligibility"] != "ELIGIBLE"
                   else _authorization_problem(authorization, prepared))
        if refusal:
            return {"request_status": "BLOCKED", "reason": refusal, "blockers": prepared["blockers"],
                    "executor_called": False, "admission_created": False, "movement_authorized": False}
        candidate = prepared["candidate"]
        try:
            nav = navigation_request(candidate)
        except (KeyError, TypeError, ValueError) as exc:
            return {"request_status": "BLOCKED", "reason": f"REQUEST_NOT_BUILDABLE: {exc}", "executor_called": False}
        mission = candidate["rover_mission"]["value"]
        if _sha(candidate) != prepared["candidate_sha256"]:  # same object, two serializers: must agree exactly
            return {"request_status": "BLOCKED", "reason": "CANDIDATE_DIGEST_SERIALIZATION_DIFFERS",
                    "executor_called": False}
        authorization_sha = _sha(authorization)
        coordination_context = {"candidate": candidate, "authorization": authorization}
        executor_authorization = {
            "mission_sha256": mission["sha256"], "request_fingerprint": executor_fingerprint(nav),
            "statement": f"{authorization['statement']} | R1 candidate {prepared['candidate_sha256']} | "
                         f"coordinator authorization {authorization_sha} | session {authorization['session_id']}"}
        task = {"request_key": request_key, "task_id": "R1", "mission_path": mission.get("path"),
                "mission_sha256": mission["sha256"], "request": nav, "executor_authorization": executor_authorization,
                "coordination_context": coordination_context,
                "candidate_sha256": prepared["candidate_sha256"], "authorization_sha256": authorization_sha,
                "result_schema": summary.GROUND_RESULT_SCHEMA}
        record = {"schema": RECORD_SCHEMA, "request_key": request_key, "task_id": "R1", "created_at": utc_now(),
                  "view": view, "view_sha256": _sha(view), "candidate": candidate,
                  "candidate_sha256": prepared["candidate_sha256"], "authorization": authorization,
                  "authorization_sha256": authorization_sha, "task": task, "task_sha256": _sha(task),
                  # The executor's admission scope over the same objects it receives.
                  "executor_scope": executor_fingerprint([mission["sha256"], executor_fingerprint(nav),
                                                          executor_authorization, coordination_context]),
                  "executor_kind": executor.facts().get("kind"),
                  "inputs_include_test_doubles": prepared["inputs_include_test_doubles"],
                  "sequence_id": candidate["depends_on_sequence"], "run_id": None, "executor_session_id": None,
                  "acceptance": None, "movement_authorized": False}
        record["fingerprint"] = _sha([record["candidate_sha256"], record["authorization_sha256"],
                                      record["view_sha256"], record["task_sha256"]])
        path.parent.mkdir(parents=True, exist_ok=True)
        # Durable intent BEFORE calling the executor: a lost reply is then visible, never re-sent.
        _transition(path, record, "ADMISSION_REQUESTED")
        try:
            reply = executor.admit(task)
        except Exception as exc:  # lost/failed reply: effects unknown, so no new attempt from here
            return {**_transition(path, record, "ADMISSION_UNCONFIRMED", reason=f"{type(exc).__name__}: {exc}"),
                    "request_status": "UNCONFIRMED", "executor_called": True}
        status = (reply or {}).get("status")
        if status == "ADMITTED" and reply.get("run_id"):
            _transition(path, record, "ADMITTED", run_id=reply["run_id"], executor_session_id=reply.get("session_id"))
        elif status in ("BLOCKED", "REJECTED"):
            _transition(path, record, "REJECTED_BY_EXECUTOR", reason=str(reply.get("reason") or status),
                        executor_reply={k: v for k, v in reply.items() if k != "launch_token"})
        else:
            _transition(path, record, "ADMISSION_UNCONFIRMED", reason=f"Unrecognized executor reply {status!r}")
        # A launch token, if any, belongs to the executor's own worker path; it is never stored here.
        return {**record, "request_status": "CREATED", "executor_called": True}


def query(root: Path, request_key: str) -> dict:
    """Read-only: never calls the executor, never changes the record."""
    path, _ = _paths(root, request_key)
    try:
        record = _load(path, root)
    except RecordIntegrityError as exc:
        return {"state": "RECORD_INTEGRITY_ERROR", "reason": str(exc)}
    return record if record is not None else {"state": "NOT_FOUND", "request_key": request_key}


def executor_records(record: dict) -> dict | None:
    """The REAL executor's local records for this run (read-only), or None when it holds none."""
    executor = _executor()
    try:
        root = executor.directory(record["run_id"])
    except (ValueError, TypeError):
        return None
    if not (root / "job.json").is_file():
        return None
    index_path = executor_request_path(executor.RUN_ROOT, record["request_key"])
    try:
        query_view = executor.query_ground_trial(record["run_id"])  # re-verifies job/report hashes and identity
        return {"query": query_view, "job": executor._read(root, "job.json"),
                "request": executor._read(root, "request.json"),
                "coordination": executor._read(root, "coordination.json") if (root / "coordination.json").is_file() else None,
                "index": json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else None}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"integrity_error": f"{type(exc).__name__}: {exc}"}


def _translated_samples(observations: list) -> list:
    """The executor's own translation of full Observations into result samples, recomputed to prove that the
    result carries exactly those samples, clocks and GIDs (no dropped or substituted sample)."""
    return [{"x_m": s["position_m"][0], "y_m": s["position_m"][1], "frame": s["pose_frame"],
             "linear_mps": sum(v * v for v in s["linear_mps"]) ** .5,
             "angular_rad_s": sum(v * v for v in s["angular_rad_s"]) ** .5,
             "source_stamp_ns": s["velocity_source_ns"], "received_monotonic_s": s["motion_received_monotonic_s"],
             "message_publisher_gid": s["odometry_publisher_gid"]} for s in observations]


def _provenance_problems(record: dict, real: dict, held: dict | None) -> tuple[list, list]:
    """(problems, unresolved). Each digest is compared only with a digest of the SAME object made by the SAME
    function (planning.artifact_store.fingerprint); no label or self-declared field is trusted alone."""
    if real.get("integrity_error"):
        return ["EXECUTOR_RECORD_INTEGRITY: " + real["integrity_error"]], []
    job, query_view, index = real["job"], real["query"], real.get("index") or {}
    report = query_view.get("report") or {}
    r1 = report.get("r1") or {}
    binding = (held or {}).get("binding") or {}
    task, candidate = record["task"], record["candidate"]
    transform_sha = candidate["frame_transform"]["value"]["sha256"]
    expected_binding = {"candidate_sha256": record["candidate_sha256"], "authorization_sha256": record["authorization_sha256"],
                        "session_id": record["authorization"]["session_id"], "frame_sha256": transform_sha}
    checks = {
        "KEY_INDEX_RUN_DIFFERS": index.get("run_id") == record["run_id"],               # executor key index
        "KEY_INDEX_SCOPE_DIFFERS": index.get("scope") == record["executor_scope"],      # admission scope
        "JOB_SCOPE_DIFFERS": job.get("admission_scope_sha256") == record["executor_scope"],
        "JOB_MISSION_DIFFERS": job.get("mission_sha256") == task["mission_sha256"],     # sha256(mission bytes)
        "JOB_REQUEST_DIFFERS": real.get("request") == task["request"],                  # request object
        "JOB_AUTHORIZATION_DIFFERS": job.get("authorization") == task["executor_authorization"],
        "JOB_COORDINATION_DIFFERS": real.get("coordination") == task["coordination_context"],
        "JOB_COORDINATION_BINDING_DIFFERS": job.get("coordination_binding") == expected_binding,
        "JOB_SESSION_DIFFERS": job.get("session_id") == record["authorization"]["session_id"],
        "JOB_VEHICLE_DIFFERS": job.get("vehicle_selection") == {"vehicle_id": "rover_01", "simulated_vehicle": "v3"},
        "REPORT_RUN_DIFFERS": report.get("run_id") == record["run_id"],
        "RESULT_BINDING_DIFFERS": binding == {
            "candidate_sha256": record["candidate_sha256"], "mission_sha256": task["mission_sha256"],
            "authorization_sha256": record["authorization_sha256"], "vehicle_id": "rover_01",
            "simulated_vehicle": "v3", "session_id": record["authorization"]["session_id"],
            "ground_run_id": record["run_id"]},
        "RESULT_FRAME_DIFFERS": ((held or {}).get("frame") or {}).get("name")
        == candidate["target_in_rover_frame"]["value"]["frame"],
        "REPORT_SAMPLES_DIGEST_DIFFERS": bool(r1) and r1.get("samples_sha256") == executor_fingerprint(r1.get("samples")),
        "RESULT_SAMPLES_DIFFER_FROM_EXECUTOR_OBSERVATIONS": bool(r1) and (held or {}).get("samples")
        == _translated_samples(r1.get("samples") or []),
    }
    problems = [name for name, ok in checks.items() if not ok]
    unresolved = [] if job.get("session_id") else ["EXECUTOR_RECORDS_NO_SESSION_ID"]
    return problems, unresolved


def candidate_params(candidate: dict) -> dict:
    """Acceptance parameters = exactly those of the authorized candidate (and therefore of the goal sent)."""
    return {**candidate["visit_parameters"], "arrival_tolerance_m": candidate["ground_tolerance_m"]["value"]}


def _evaluate(record: dict, status: dict) -> tuple[list, dict]:
    """(provenance problems, separated facts). Facts keep goal, stop, arming, executor closure and uncertainty
    apart; nothing here decides the R1 state on its own."""
    offered = ((status or {}).get("report") or {}).get("r1_ground_result")
    expected = {"session_id": record["authorization"]["session_id"], "authorization_sha256": record["authorization_sha256"],
                "ground_run_id": record["run_id"]}
    params = candidate_params(record["candidate"])
    real = executor_records(record)
    if real is not None:
        held = ((real.get("query") or {}).get("report") or {}).get("r1_ground_result")
        problems, unresolved = _provenance_problems(record, real, held if isinstance(held, dict) else None)
        if not isinstance(held, dict):
            problems.append("NO_R1_GROUND_RESULT_IN_EXECUTOR_REPORT")
        elif offered != held:
            problems.append("RESULT_DIFFERS_FROM_EXECUTOR_RECORD")  # mixed real records and other samples
        if problems:
            return problems, {"provenance": "EXECUTOR_RECORDS_MISMATCH"}
        report = real["query"]["report"]
        # Frame: candidate transformation VERIFIED (coordinator input) AND the executor bound THAT digest to the
        # adapter's accredited pose reference before any command (JOB_COORDINATION_BINDING above).
        goal = summary.evaluate_ground_result({**held, "frame": {**held["frame"], "transform_status": "VERIFIED"}},
                                              record["candidate"], expected, params)
        facts = {"provenance": "EXECUTOR_LOCAL_RECORDS_MATCHED", "unresolved_contract": unresolved,
                 "frame_basis": "CANDIDATE_TRANSFORM_VERIFIED_INPUT+EXECUTOR_BOUND_POSE_REFERENCE_DIGEST",
                 "executor_frame_label": held["frame"].get("transform_status"), "declared_origin": held.get("origin"),
                 "binding_basis": held.get("binding_basis"),
                 "executor_goal_outcome": (report.get("r1") or {}).get("goal_outcome"),
                 "armed_after_stop": [o.get("armed") for o in (((report.get("result") or {}).get("stop") or {})
                                                                .get("observations") or [])] or None,
                 "closure": report.get("closure"), "finalization": {k: (report.get("finalization") or {}).get(k) for k in
                                                                    ("policy", "status", "disarm_attempted",
                                                                     "disarm_acknowledged", "disarmed_observed")}
                 if report.get("finalization") else None,
                 "authorized_finalization": (record["candidate"].get("finalization_policy") or {}).get("value"),
                 "synthetic": bool(record["inputs_include_test_doubles"]) or held.get("origin") == "SYNTHETIC_TEST_DOUBLE"}
    else:
        if not isinstance(offered, dict):
            return ["NO_R1_GROUND_RESULT_IN_EXECUTOR_REPORT"], {"provenance": "NO_EXECUTOR_RECORD"}
        goal = summary.evaluate_ground_result(offered, record["candidate"], expected, params)
        facts = {"provenance": "NO_EXECUTOR_RECORD", "declared_origin": offered.get("origin"), "synthetic": True,
                 "armed_after_stop": None}  # without executor records: at most synthetic, whatever it declares
    facts.update(executor_closure=(status or {}).get("status"),
                 authorized_parameters={"target": record["candidate"]["target_in_rover_frame"]["value"],
                                        "transform_sha256": record["candidate"]["frame_transform"]["value"]["sha256"],
                                        **{k: params[k] for k in ("arrival_tolerance_m", "dwell_s", "global_timeout_s")}})
    return [], {**goal, **facts, "executor_job_status": (status or {}).get("status")}


def _final_state(acceptance: dict) -> str:
    """R1 completes only when goal, observed stop AND the executor's own closure (FINISHED) all hold."""
    goal = acceptance["outcome"]
    closure = acceptance.get("closure")
    # Authority: the executor's committed job state (FINISHED, checked by the caller) AND its report's closure:
    # job_close eligible for that commit and the vehicle's close observed. Anything else is never accepted.
    if closure is not None and (closure.get("job_close") not in ("COMMIT_ELIGIBLE", "CONFIRMED")
                                or closure.get("vehicle_close") in (None, "UNCONFIRMED", "UNKNOWN")):
        return "UNCERTAIN"
    if goal == "VERIFIED" and acceptance.get("stop_confirmed"):
        return "VERIFIED_SYNTHETIC" if acceptance["synthetic"] else "VERIFIED"
    return {"FAILED": "FAILED", "UNCERTAIN": "UNCERTAIN"}.get(goal, "REJECTED_RESULT")


def _executor_fact(status: dict) -> str:
    """Classify the executor's read-only query (status + worker_phase) without inferring what it does not record."""
    job, phase = (status or {}).get("status"), (status or {}).get("worker_phase")
    if job == "FINISHED":
        return "FINISHED"
    if job in ("BLOCKED", "REJECTED"):
        return "REJECTED"
    if job not in ("ADMITTED", "STARTING", "RUNNING", "FINALIZING", "UNCONFIRMED"):
        return "NOT_FOUND"
    if (status.get("report") or {}).get("r1_ground_result"):
        return "GOAL_FINISHED_CLOSURE_UNCONFIRMED"
    if status.get("failure"):
        return "FAILED_UNCONFIRMED"
    if job in ("STARTING", "RUNNING", "FINALIZING"):
        return "WORKER_OBSERVED"
    if phase in ("START_INTENT_WITHOUT_CONFIRMED_WORKER", "STARTING_WORKER_LOST_OR_UNKNOWN"):
        return "START_UNCONFIRMED"
    if job == "ADMITTED" or (phase is None and status.get("worker") is None):
        return "NO_WORKER_RECORDED"  # the worker records its identity BEFORE any backend effect
    return "WORKER_UNCONFIRMED"  # identity recorded, liveness/ownership not confirmed: pending or lost


def start(root: Path, request_key: str, executor) -> dict:
    """Request the start of an ADMITTED job ONCE. The intent is durable (under the coordinator mutex) before the
    call; the synchronous start runs OUTSIDE the mutex so tracking stays possible. A lost/failed reply is
    START_UNCONFIRMED and is never repeated. A query never becomes an order; request_key is not a credential."""
    path, lock = _paths(root, request_key)
    with file_mutex(lock):
        try:
            record = _load(path, root)
        except RecordIntegrityError as exc:
            return {"state": "RECORD_INTEGRITY_ERROR", "reason": str(exc), "executor_called": False}
        if record is None or record["state"] not in ("ADMITTED", "ADMITTED_NO_WORKER"):
            return {**(record or {"request_key": request_key}), "start_status": "NOT_STARTABLE", "executor_called": False}
        if not callable(getattr(executor, "start", None)):
            return {**record, "start_status": "UNSUPPORTED", "executor_called": False}
        record = _transition(path, record, "START_REQUESTED")
    try:
        reply = executor.start(record["run_id"], record)
    except Exception as exc:  # lost/failed reply: the worker may or may not exist; never start again
        reply = {"status": "LOST", "reason": f"{type(exc).__name__}: {exc}"}
    with file_mutex(lock):
        current = _load(path, root)
        status = (reply or {}).get("status")
        if current["state"] != "START_REQUESTED":  # tracking already moved on: keep the newer facts
            return {**current, "start_status": status, "executor_called": True}
        if status == "UNSUPPORTED":  # nothing was attempted: the job is exactly as before
            return {**_transition(path, current, "ADMITTED_NO_WORKER", reason=reply.get("reason")),
                    "start_status": "UNSUPPORTED", "executor_called": False}
        if status != "STARTED":
            return {**_transition(path, current, "START_UNCONFIRMED", reason=f"start {status}: {reply.get('reason')}"),
                    "start_status": "UNCONFIRMED", "executor_called": True}
        return {**current, "start_status": "STARTED", "executor_called": True}


def track(root: Path, request_key: str, executor) -> dict:
    """Read-only towards the executor (lookup/query); persists only this record's transitions.
    Recoverable after a coordinator restart: all state is in the record."""
    path, lock = _paths(root, request_key)
    with file_mutex(lock):
        try:
            record = _load(path, root)
        except RecordIntegrityError as exc:
            return {"state": "RECORD_INTEGRITY_ERROR", "reason": str(exc), "executor_called": False}
        if record is None:
            return {"state": "NOT_FOUND", "request_key": request_key}
        if record["state"] in TERMINAL:
            return record
        try:
            if record["state"] in ("ADMISSION_REQUESTED", "ADMISSION_UNCONFIRMED"):
                found = executor.lookup(request_key)
                if found is None:
                    return _transition(path, record, "ADMISSION_UNCONFIRMED",
                                       reason="No accredited lookup by key; admission unknown. Never re-admitted.")
                if not found.get("found"):
                    return _transition(path, record, "ADMISSION_UNCONFIRMED",
                                       reason="Accredited lookup: no admission under this key; not re-admitted. "
                                              "A new attempt needs a new request key.")
                if found.get("scope") is not None and found["scope"] != record["executor_scope"]:
                    return _transition(path, record, "UNCERTAIN", reason="KEY_BOUND_TO_A_DIFFERENT_EXECUTOR_SCOPE")
                record = _transition(path, record, "ADMITTED", run_id=found["run_id"],
                                     executor_session_id=found.get("session_id"))
            status = executor.query(record["run_id"])
        except Exception as exc:  # a failed read changes nothing; tracking can simply be repeated
            return {**record, "tracking_error": f"{type(exc).__name__}: {exc}"}
        fact = _executor_fact(status)
        job = (status or {}).get("status")

        def move(state, **fields):
            same = record["state"] == state and all(record.get(k) == v for k, v in fields.items())
            return record if same else _transition(path, record, state, executor_status=job, **fields)
        if fact in ("FINISHED", "GOAL_FINISHED_CLOSURE_UNCONFIRMED"):
            problems, acceptance = _evaluate(record, status)
            if problems:
                return move("REJECTED_RESULT", acceptance={"outcome": "REJECTED", "reasons": problems, **acceptance},
                            reason=",".join(problems))
            if fact == "GOAL_FINISHED_CLOSURE_UNCONFIRMED":  # goal facts kept; awaits the executor's own closure
                return move("CLOSURE_PENDING", acceptance=acceptance,
                            reason="executor closure UNCONFIRMED (e.g. armed after HOLD); reservation kept by the executor")
            state = _final_state(acceptance)
            return move(state, acceptance=acceptance, reason=",".join(acceptance.get("reasons") or []) or None)
        if fact == "REJECTED":
            return move("REJECTED_BY_EXECUTOR", reason=f"executor {job}")
        if fact == "FAILED_UNCONFIRMED":
            return move("EXECUTION_FAILED", reason="executor failure evidence; job UNCONFIRMED (kept, never released)",
                        executor_failure=status.get("failure"))
        if fact == "WORKER_OBSERVED":
            return move("WORKER_OBSERVED", worker_phase=status.get("worker_phase"))
        if fact == "START_UNCONFIRMED":
            return move("START_UNCONFIRMED", reason=f"executor phase {status.get('worker_phase')}; never restarted")
        if fact == "NO_WORKER_RECORDED":
            # Absence of a worker record after a start request is NOT proof that it never started.
            if record["state"] in ("START_REQUESTED", "START_UNCONFIRMED"):
                return move("START_UNCONFIRMED", reason="start requested; no worker recorded yet; never restarted")
            return move("ADMITTED_NO_WORKER")
        if fact == "WORKER_UNCONFIRMED":
            return move("WORKER_UNCONFIRMED", reason="worker identity recorded; liveness/ownership not confirmed")
        return move("UNCERTAIN", reason=f"executor status {job!r}")


def scenario_result(view: dict, record: dict | None) -> dict:
    """Scenario status from the aerial view and the R1 record (see reporting.scenario_with_r1)."""
    return summary.scenario_with_r1(view, record)
