"""Rover Agent plan -> our bridge -> the rover's v2 contract -> the rover's protected executor (admission only), exercising
REAL code on both sides. The rover's code runs from an immutable snapshot of a pinned commit (git archive) in its own
process (rover_snapshot_runner.py); the rover working tree is never read for execution or written. Only the protected
operations are replaced: the executor's admission is called with the operational policy as committed (disabled)
and without any SITL declaration, so it returns BLOCKED before touching a file; our side then uses the dry-run
adapter. Nothing here can emit a command.

Stages (each returns PASS / WAITING / BLOCKED / REFUSED / NOT_REACHED with structured reasons):
  1 request          our rover-execution-request/1 (rover_executor_bridge.validate_request)
  2 coordinator      the ground task must be READY_FOR_AUTHORIZATION (dependencies, expiry, cancellation)
  3 authorization    our human-authorization record, checked against the request in the given MODE
  4 rover_bridge     the rover's validate_bridge_request on bridge_view(request)
  5 frames           frames2d.goal_for_rover: site goal -> rover frame, localization, area, uncertainty
  6 rover_v2         the rover's adapt_request + v2 validator (needs an authenticated operator receipt)
  7 executor_request the rover's executor _request on a ROVER_NAVIGATE_V1 built from the plan and the rover-frame goal
  8 executor_admit   the rover's admit_ground_trial (policy as committed)
  9 dry_run          our DryRunRoverExecutor (physical_effect false)
Modes: OFFLINE_TEST (fixtures allowed) / OPERATIONAL (fixtures refused, no receipt provider exists).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Callable

from multiagent import rover_v2_bridge as cb, frames2d, human_authorization as ha, rover_executor_bridge as rb
from multiagent import rover_goal_contract as gc
from multiagent import historical_identifiers as hist

ROVER_CONTRACT_COMMIT = "57a0e303a"   # contract files identical to 1514053da (checked by contract_digest)
CONTRACT_FILES = ("tools/rover_mission_payload.py", "tools/rover_agent_adapter.py", "tools/rover_ground_executor.py",
                  "tools/rover_control.py", "schemas/rover-mission-execution-v2.schema.json")
RUNNER = Path(__file__).with_name("rover_snapshot_runner.py")
ROOT = Path(__file__).resolve().parents[1]


def contract_digest(commit: str = ROVER_CONTRACT_COMMIT) -> dict:
    out = {}
    for f in CONTRACT_FILES:
        blob = subprocess.run(["git", "show", f"{commit}:{f}"], cwd=ROOT, capture_output=True, check=True).stdout
        out[f] = hashlib.sha256(blob).hexdigest()
    return out


# the rover's protected review package (committed as a FILE in 2e206f1fa, not applied to the working tree): it adds the optional
# authorization.bridge_scope_sha256 to the v2 schema and an offline reference authorization ledger. It is applied
# only inside a snapshot, after its sha256 is verified.
REVIEWED = {"commit": "2e206f1fa", "patch": "docs/checkpoints/2026-11-07-rover-protected-review.patch",
            "patch_sha256": "551eb1fefebcaf31ee635472859d8dee3809755d635dd98a717919996eb3a594"}


def ensure_snapshot(dest: Path, commit: str = ROVER_CONTRACT_COMMIT, *, reviewed: bool = False) -> Path:
    """An immutable extraction of the pinned commit (from git objects, not from the rover's working tree); with
    reviewed=True, REVIEWED's commit plus its protected review patch (sha256-verified), applied in the snapshot only."""
    dest = Path(dest)
    tag = f"{REVIEWED['commit']}+{REVIEWED['patch_sha256'][:12]}" if reviewed else commit
    marker = dest / ".snapshot_commit"
    if marker.is_file() and marker.read_text().split()[0] == tag:
        return dest
    dest.mkdir(parents=True, exist_ok=False)
    base = REVIEWED["commit"] if reviewed else commit
    archive = subprocess.run(["git", "archive", base], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    if reviewed:
        patch = subprocess.run(["git", "show", f"{base}:{REVIEWED['patch']}"], cwd=ROOT, capture_output=True,
                               check=True).stdout
        if hashlib.sha256(patch).hexdigest() != REVIEWED["patch_sha256"]:
            raise RuntimeError("protected review patch does not match its recorded sha256")
        subprocess.run(["git", "apply", "-p1"], cwd=dest, input=patch, check=True)
    marker.write_text(f"{tag} {json.dumps(contract_digest(base), sort_keys=True)}\n")
    return dest


def rover_contract(snapshot: Path | None = None, *, reviewed: bool = False):
    """The rover side of the hand-off. Normal path (``snapshot`` None): this repository's rover modules imported
    in-process (multiagent.rover_contract_local). With ``snapshot``: the historical pinned revision (``reviewed`` adds
    its protected review patch) extracted into that directory, kept to reproduce sealed evidence."""
    if snapshot is None:
        from multiagent.rover_contract_local import LocalRoverContract
        return LocalRoverContract()
    return RoverSnapshot(ensure_snapshot(snapshot, reviewed=reviewed))


class RoverSnapshot:
    """One isolated process running the rover's code from the snapshot."""

    def __init__(self, snapshot: Path):
        self.snapshot = Path(snapshot)
        self.proc = None
        marker = self.snapshot / ".snapshot_commit"   # written by ensure_snapshot: the commit (+ patch) it holds
        self.tag = marker.read_text().split()[0] if marker.is_file() else "UNIDENTIFIED_SNAPSHOT"
        # every pinned snapshot revision writes this provenance.source into its plans (part of the plan digest)
        self.provenance_source = hist.SNAPSHOT_ADAPTER_PROVENANCE_SOURCE

    def __enter__(self):
        self.proc = subprocess.Popen([sys.executable, "-I", "-B", str(RUNNER), str(self.snapshot)],
                                     cwd=self.snapshot, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        return self

    def __exit__(self, *exc):
        if self.proc:
            self.proc.stdin.close()
            self.proc.wait(timeout=30)

    def call(self, op: str, **args) -> dict:
        self.proc.stdin.write(json.dumps({"op": op, "args": args}, default=str) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("rover snapshot runner stopped: " + self.proc.stderr.read()[:400])
        return json.loads(line)


def rover_ledger_receipt_provider(mode: str, ledger: Path, *, revoke: bool = False) -> Callable:
    """Uses the rover's OWN offline authorization ledger (rover_local_authorization, reviewed snapshot) to issue, optionally
    revoke, and consume a single-use FIXTURE grant bound to the exact rover plan scope. The receipt reports what the
    ledger proves and nothing more: a fixture principal is DECLARED, never AUTHENTICATED, so the rover's validator rejects it
    (OPERATOR_NOT_AUTHENTICATED). The mapping from an authenticated grant to the v2 receipt is the rover's to define."""
    if mode != "OFFLINE_TEST":
        raise PermissionError("the rover's fixture ledger is offline-only")

    def provide(view, kwargs, rover_side):
        scope = rover_side.call("plan_scope", payload=_rover_payload(view, kwargs, rover_side.provenance_source))["result"]
        principal = {"principal_id": "TEST_FIXTURE_OPERATOR", "uid": 1000, "pid": 4242, "process_start_ticks": 1,
                     "evidence_source": "TEST_FIXTURE"}
        binding = {"scope_sha256": scope["scope_sha256"], "session_id": view["task_id"], "owner_id": "multiagent-planner",
                   "vehicle_id": view["vehicle_id"], "profile": "rover_mission_v2", "operations": ["SUBMIT_MISSION_V2"],
                   "host_boot_id": "TEST_FIXTURE", "container_boot_id": "TEST_FIXTURE", "environment_sha256": "0" * 64}
        issued = rover_side.call("auth_issue_fixture", ledger=str(ledger), principal=principal, binding=binding)
        if not issued["ok"]:
            return {"refused": issued["error"]}
        if revoke:
            rover_side.call("auth_revoke", ledger=str(ledger), authorization_id=issued["result"]["authorization_id"],
                       principal=principal)
        used = rover_side.call("auth_consume", ledger=str(ledger), authorization=issued["result"], principal=principal,
                          binding=binding)
        if not used["ok"]:
            return {"refused": used["error"]}
        record = used["result"]
        return {"bridge_scope_sha256": view["expected_scope_sha256"], "scope_sha256": scope["scope_sha256"],
                "human_authorized": True, "operator_id": record["principal"]["principal_id"],
                "operator_status": "DECLARED" if record["principal_status"] == "TEST_FIXTURE" else "UNKNOWN",
                "revocation_status": "ACTIVE",  # it was ACTIVE when consumed, single use
                "authorization_receipt_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()}
    return provide


def fixture_receipt_provider(mode: str, *, revocation_status: str = "ACTIVE") -> Callable:
    """A TEST_FIXTURE 'authenticated operator receipt', bound to both scopes exactly as the rover's adapter requires.
    Refuses to exist outside OFFLINE_TEST. It authenticates nobody. ``revocation_status`` lets a test present a
    revoked receipt to the rover's validator (which must refuse it)."""
    if mode != "OFFLINE_TEST":
        raise PermissionError("a fixture receipt provider cannot be created outside OFFLINE_TEST")

    def provide(view, kwargs, rover_side) -> dict:
        probe = rover_side.call("adapt_v2", view=view, kwargs=kwargs,
                           receipt={"bridge_scope_sha256": view["expected_scope_sha256"], "scope_sha256": "0" * 64})
        # the rover side rejects the probe (scope not bound); the plan scope is derived exactly as the adapter does
        if not probe["ok"] or probe["result"].get("decision") != "REJECTED":
            return None
        scope = rover_side.call("plan_scope", payload=_rover_payload(view, kwargs, rover_side.provenance_source))["result"]
        return {"bridge_scope_sha256": view["expected_scope_sha256"], "human_authorized": True,
                "operator_id": "TEST_FIXTURE_OPERATOR", "operator_status": "AUTHENTICATED", "revocation_status": revocation_status,
                "authorization_receipt_sha256": hashlib.sha256(b"TEST_FIXTURE_RECEIPT").hexdigest(),
                "scope_sha256": scope["scope_sha256"]}
    return provide


def _rover_payload(view, kwargs, source: str) -> dict:
    """The payload the rover's adapter builds (to compute its plan scope for a fixture receipt)."""
    plan = view["navigation_plan"]
    return {"schema": "tfg.rover.mission-execution/2", "mission": kwargs["mission"], "plan_id": plan["plan_id"],
            "rover": kwargs["rover"], "goal": {"objective": "reach_agent_declared_point:" + view["target"]["point_id"],
                                               "frame": plan["frame"], "x_m": plan["target_x_m"],
                                               "y_m": plan["target_y_m"], "conditional": False},
            "localization": kwargs["localization"], "dependencies": list(kwargs["dependencies"]),
            "constraints": kwargs["constraints"],
            "operator_limits": {**kwargs["operator_limits"], "max_speed_mps": plan["max_speed_mps"],
                                "timeout_s": plan["timeout_s"]},
            "provenance": {**kwargs["provenance"], "source": source,
                           "source_sha256": hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":"))
                                                           .encode()).hexdigest()},
            # The adapter computes the plan scope on the payload carrying the receipt; since the 07/11 rover package
            # a present authorization.bridge_scope_sha256 is bound into that scope (earlier contracts ignore it and
            # authorization is not a plan field), so the receipt is derived with the same bridge digest.
            "authorization": {"bridge_scope_sha256": view["expected_scope_sha256"]},
            "validity": kwargs["validity"], "executor": kwargs["executor"],
            "stop_conditions": list(kwargs["stop_conditions"])}


@dataclass
class HandoffInputs:
    mode: str
    now: datetime
    ground_state: str | None
    site_goal: dict | None
    platform: str = "ArduRover SITL"
    graph: frames2d.FrameGraph | None = None
    rover_frame: str = "odom"
    localization: dict | None = None          # frames2d shape (rover frame), accredited by its source
    limits: dict = field(default_factory=dict)  # max_total_sigma_m, localization_max_age_s, max_distance_m
    authorized_area: list | None = None
    receipt_provider: Callable | None = None
    executor_params: dict | None = None       # declared executor configuration (RoverLimits/NavigationGoal extras)
    observation_sha256: str | None = None
    observation_id: str | None = None
    observation_data_kind: str | None = None
    rover_identity: dict | None = None        # {vehicle_id, boot_id} the localization must belong to
    # {host_boot_id, container_boot_id} of the rover execution the final adapter must bind the localization to
    execution_identity: dict | None = None
    # state of the rover's last STOP as known to the caller; the final adapter refuses anything but CONFIRMED
    stop_state: str | None = None
    # who converts site -> rover frame: exactly ONE component, ALWAYS declared (no default; see rover_goal_contract).
    # ROVER_ADAPTER (final): this side checks and describes, the rover's executor adapter converts. MULTIAGENT_FRAMES2D:
    # offline test mode only, frames2d converts here and the executor gets IDENTITY_SAME_ACCREDITED_FRAME.
    conversion_owner: str | None = None
    observation: dict | None = None           # source, timestamp, original pose / camera chain, uncertainty
    provenance: dict | None = None            # where the plan comes from (e.g. a sealed real run, replayed)
    snapshot_label: str | None = None         # None: the snapshot's own marker (commit, or commit+patch) is used


def handoff(req: dict, inp: HandoffInputs, rover_side: RoverSnapshot) -> dict:
    if inp.snapshot_label is None:
        inp.snapshot_label = getattr(rover_side, "tag", "UNIDENTIFIED_SNAPSHOT")
    stages = []

    def stage(name, status, reasons=(), **extra):
        stages.append({"stage": name, "status": status, "reasons": list(reasons), **extra})
    # 1-2: our request and the coordinator state
    r1 = rb.validate_request(req)
    stage("request", "PASS" if not r1 else "WAITING", r1)
    stage("coordinator", "PASS" if inp.ground_state == "READY_FOR_AUTHORIZATION" else "BLOCKED",
          [] if inp.ground_state == "READY_FOR_AUTHORIZATION" else [f"GROUND_TASK_NOT_READY: {inp.ground_state}"])
    # 3: our authorization record
    rec = req.get("authorization")
    r3 = ["NO_HUMAN_AUTHORIZATION_RECORD"] if rec is None else ha.check(rec, req, now=inp.now, mode=inp.mode)
    stage("authorization", "PASS" if not r3 else "BLOCKED", r3)
    # 4: the rover's bridge check (authorization shape derived only from a record accepted in this mode)
    view = cb.bridge_view(req, now=inp.now)
    if r3:
        view["authorization"] = None
    r4 = rover_side.call("bridge_check", view=view)
    stage("rover_bridge", "PASS" if r4["ok"] and not r4["result"]["reasons"] else "WAITING",
          r4["result"]["reasons"] if r4["ok"] else [r4["error"]])
    # 5: frames: the SAME checks whoever converts; the conversion itself happens once, by the declared owner
    owner_bad = gc.owner_problems(inp.conversion_owner, inp.mode)
    apply_here = inp.conversion_owner == gc.OFFLINE_TEST_OWNER and not owner_bad
    if inp.graph is None or inp.site_goal is None:
        fr = {"status": "REFUSED", "reasons": ["NO_FRAME_GRAPH" if inp.graph is None else "NO_SITE_GOAL"]
              + ([] if inp.localization else ["ROVER_LOCALIZATION_NOT_ACCREDITED"]), "goal_rover": None,
              "applied": False, "transform_reference": None, "delegated_checks": []}
    else:
        fr = frames2d.goal_for_rover(inp.site_goal, inp.graph, rover_frame=inp.rover_frame,
                                     localization=inp.localization, limits=inp.limits, now=inp.now,
                                     authorized_area=inp.authorized_area, rover_identity=inp.rover_identity,
                                     apply=apply_here)
    goal_rec = gc.build(owner=inp.conversion_owner, site_goal=inp.site_goal,
                        point_id=(req.get("target") or {}).get("point_id"), rover_frame=inp.rover_frame,
                        observation={"observation_id": inp.observation_id, "sha256": inp.observation_sha256,
                                     "data_kind": inp.observation_data_kind, **(inp.observation or {})},
                        dependencies=req.get("dependencies"), localization=inp.localization,
                        rover_identity=inp.rover_identity,
                        constraints={"human": {k: (req.get("navigation_plan") or {}).get(k)
                                               for k in ("max_speed_mps", "timeout_s")},
                                     "operator": dict(inp.limits), "authorized_area_site_frame": inp.authorized_area},
                        frames_result=fr)
    if inp.conversion_owner == gc.FINAL_OWNER:
        fr["conversion"] = {"owner": gc.FINAL_OWNER, "applied_here": False, "site_goal": inp.site_goal,
                            "transform": (fr.get("transform_reference") or {}).get("rover_matrix"),
                            "transform_reference": fr.get("transform_reference"),
                            "delegated_checks": fr.get("delegated_checks"), "reasons": list(fr["reasons"])}
    r5 = owner_bad + list(fr["reasons"]) + gc.conversion_problems(goal_rec)
    stage("frames", "PASS" if not r5 else "REFUSED", r5, goal_rover=fr.get("goal_rover"),
          goal_base_link=fr.get("goal_base_link"), conversion=fr.get("conversion"), goal_handoff=goal_rec)
    # 6: the rover v2 payload (localization in the rover's shape; site goal frame; transform odom->site from the graph)
    loc_v2 = _localization_v2(inp, fr)
    kwargs = cb.adapter_inputs(req, platform=inp.platform, observation_sha256=inp.observation_sha256,
                               localization=loc_v2, operator_limits={
                                   "max_distance_m": inp.limits.get("max_distance_m"),
                                   "localization_max_uncertainty_m": inp.limits.get("localization_max_uncertainty_m"),
                                   "localization_max_age_s": inp.limits.get("localization_max_age_s")}, now=inp.now)
    receipt, receipt_refused = None, None
    if inp.receipt_provider is not None and req.get("navigation_plan") and not r3:
        receipt = inp.receipt_provider(view, kwargs, rover_side)
        if isinstance(receipt, dict) and "refused" in receipt:
            receipt_refused, receipt = receipt["refused"], None
    r6 = rover_side.call("adapt_v2", view=view, kwargs=kwargs, receipt=receipt)
    res6 = r6.get("result") or {}
    if receipt_refused:
        res6 = {**res6, "reasons": [f"RECEIPT_REFUSED_BY_LEDGER: {receipt_refused}"] + list(res6.get("reasons") or [])}
    schema_errors = rover_side.call("schema_v2", payload=res6["payload"])["result"]["errors"] if res6.get("payload") else None
    stage("rover_v2", {"READY_TO_SUBMIT": "PASS"}.get(res6.get("decision"), res6.get("decision") or "ERROR"),
          res6.get("reasons") or ([r6["error"]] if not r6["ok"] else []), schema_errors=schema_errors,
          commands=res6.get("commands", (res6.get("proposal") or {}).get("commands")),
          movement_authorized=res6.get("movement_authorized", (res6.get("proposal") or {}).get("movement_authorized")))
    # 7: the rover executor request (goal must already be in the rover's accredited frame: IDENTITY_SAME_ACCREDITED_FRAME)
    nav, missing = _navigate_request(req, fr, inp)
    awaiting_adapter = False
    prepared = None
    final_adapter = inp.conversion_owner == gc.FINAL_OWNER and getattr(rover_side, "supports_final_adapter", False)
    if final_adapter:
        # The rover's final adapter receives the exact v2 payload, converts site -> rover frame once and builds the only
        # executor request; limits come from the payload, never from executor parameters. Offline test path only:
        # evidence and stop state are TEST_FIXTURE declarations, the adapter refuses OPERATIONAL mode.
        param_problems = executor_parameter_problems(inp.executor_params)
        r7 = {"ok": True, "result": {"status": "REFUSED", "reason": param_problems[0]}} if param_problems else \
            rover_side.call("prepare_executor_request", payload=res6.get("payload"), mode=inp.mode,
                             executor_params=inp.executor_params, rover_frame=inp.rover_frame,
                             localization_evidence=_fixture_localization_evidence(inp, loc_v2),
                             dependencies_satisfied=inp.ground_state == "READY_FOR_AUTHORIZATION",
                            expected_identity=_expected_identity(inp), stop_state=inp.stop_state or "UNKNOWN")
        prepared = r7.get("result") if r7["ok"] else None
        if prepared and prepared.get("status") == "REQUEST_VALID":
            nav, missing = prepared["request"], []
        else:
            nav, missing = None, [(prepared or {}).get("reason") or r7.get("error") or "ADAPTER_REFUSED"]
    elif inp.conversion_owner == gc.FINAL_OWNER:
        present = (rover_side.call("rover_adapter_presence").get("result") or {}).get("present")
        awaiting_adapter = True
        nav, missing = None, ["CONVERSION_DELEGATED_TO_ROVER_ADAPTER: no rover-frame goal is built on this side",
                              (f"ROVER_ADAPTER_IN_SNAPSHOT_NOT_INTEGRATED: {inp.snapshot_label}" if present else
                               f"ROVER_ADAPTER_NOT_IN_SNAPSHOT: {inp.snapshot_label} has no "
                               "tools/rover_payload_executor_adapter.py (not promoted)")]
    elif nav is not None:
        bad = gc.executor_goal_problems(goal_rec, nav)
        if bad:
            nav, missing = None, bad
    if final_adapter:
        stage("executor_request", "PASS" if nav is not None else "REFUSED", missing, request=nav,
              adapter_audit=(prepared or {}).get("audit"), adapter="tools.rover_payload_executor_adapter")
    elif nav is None:
        stage("executor_request", "NOT_REACHED", missing)
    else:
        r7 = rover_side.call("executor_request_check", request=nav)
        stage("executor_request", "PASS" if r7["ok"] else "REFUSED", [] if r7["ok"] else [r7["error"]], request=nav)
    # 8: the rover executor admission (policy as committed; no SITL declaration; no executor authorization fabricated)
    if final_adapter:
        r8 = rover_side.call("admit_executor_request", prepared=prepared)
        res8 = ((r8.get("result") or {}).get("executor_result") or {}) if r8["ok"] else {}
        status8 = (res8.get("status", "NOT_REACHED") if nav is not None else "NOT_REACHED") if r8["ok"] else "REFUSED"
        stage("executor_admit", status8, [res8.get("reason")] if res8 else ([] if r8["ok"] else [r8["error"]]))
    else:
        r8 = rover_side.call("executor_admit", request=nav, authorization=None)
        res8 = r8.get("result") or {}
        stage("executor_admit", res8.get("status", "ERROR") if r8["ok"] else "REFUSED",
              [res8.get("reason")] if r8["ok"] else [r8["error"]])
    # 9: our dry-run adapter
    fb = rb.DryRunRoverExecutor().execute(req.get("navigation_plan") or {}, rec or {})
    stage("dry_run", "REFUSED", [fb.get("error") or fb.get("status")], physical_effect=fb.get("physical_effect"))
    blocking = [s for s in stages[:6] if s["status"] != "PASS"]
    cls = ("BLOCKED_BEFORE_SUBMISSION" if blocking else
           "V2_READY_AWAITING_ROVER_ADAPTER" if awaiting_adapter else
           "V2_READY_EXECUTOR_REQUEST_INCOMPLETE" if stages[6]["status"] != "PASS" else
           "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED" if stages[7]["status"] == "BLOCKED" else "UNEXPECTED")
    reasons = [f"{s['stage']}: {r}" for s in stages for r in s["reasons"] if s["status"] not in ("PASS",)]
    commands = [c for s in stages for c in (s.get("commands") or [])]
    envelope = submission_envelope(req, inp, fr, res6, receipt, nav, stages) if not blocking else None
    if envelope is not None:
        envelope["goal_handoff"] = goal_rec
    errors = structured_errors(stages)
    # the coordinator reads semantic prefixes: any localization problem is NO_POSITION (never a valid authorization)
    pre = [f"NO_POSITION: {e['stage']}: {e['code']}" if e["category"] == "LOCALIZATION" else f"{e['stage']}: {e['code']}"
           for e in errors]
    return {"schema": "tfg.multiagent.rover-handoff/1", "mode": inp.mode, "rover_snapshot": inp.snapshot_label,
            "rover_commit": ROVER_CONTRACT_COMMIT, "classification": cls, "stages": stages, "envelope": envelope,
            "conversion_owner": inp.conversion_owner, "provenance": inp.provenance, "errors": errors,
            "error_categories": sorted({e["category"] for e in errors}),
            "commands": commands, "movement_executed": False,
            "coordinator_events": [{"type": "EXECUTOR_PRECONDITIONS", "reasons": pre, "detail": reasons},
                                   {"type": "EXECUTOR_FEEDBACK",
                                    "feedback_type": rb.feedback_event(fb, task_id=req["task_id"], at=inp.now)["type"]}]}


# reason code prefix -> category the coordinator acts on (unknown codes stay UNCLASSIFIED, never treated as a pass)
CATEGORIES = (
    ("LOCALIZATION", ("ROVER_LOCALIZATION", "ROVER_POSE", "NO_ACCREDITED_ROVER_LOCALIZATION", "LOCALIZATION_",
                      "ROVER_IDENTITY_MISMATCH", "ROVER_BOOT_CHANGED", "NO_POSITION")),
    ("AUTHORIZATION", ("NO_HUMAN_AUTHORIZATION", "OUTSIDE_VALIDITY_WINDOW", "FIXTURE_AUTHORIZATION", "OPERATOR_",
                       "RECEIPT_REFUSED", "AUTHENTICATED_OPERATOR_RECEIPT", "AUTHORIZATION_", "NO_AUTHORIZATION",
                       "HUMAN_NOT_AUTHORIZED", "REVOK")),
    ("SCOPE", ("PLAN_ID_MISMATCH", "ROVER_ID_MISMATCH", "SCOPE", "PLAN_SHA", "BRIDGE_SCOPE", "LIMITS_MISMATCH",
               "PROPOSAL_")),
    ("CONVERSION", ("CONVERSION_", "DOUBLE_CONVERSION", "MULTIAGENT_FRAMES2D", "GOAL_ALREADY_IN_ROVER_FRAME",
                    "ROVER_ADAPTER", "TRANSFORM_STATUS", "EXECUTOR_WOULD_CONVERT", "EXECUTOR_GOAL_DIFFERS")),
    ("FRAMES", ("UNKNOWN_FRAME", "CHAIN_NOT_USABLE", "NO_CHAIN", "CIRCULAR", "SAME_FRAME", "NO_FRAME_GRAPH",
                "NO_SITE_GOAL", "UNCERTAINTY", "GOAL_OUTSIDE", "GOAL_BEYOND", "GOAL_INVALID", "AUTHORIZED_AREA",
                "DISTANCE_LIMIT", "NO_GOAL_IN_ROVER_FRAME")),
    ("COORDINATOR", ("GROUND_TASK_NOT_READY",)),
    ("PLAN", ("NO_NAVIGATION_PLAN", "NAVIGATION_PLAN_PENDING", "EXECUTOR_PARAMETERS_NOT_DECLARED")),
    ("EXECUTOR_POLICY", ("OPERATIONAL_ROVER_POLICY_DISABLED",)),
)


def categorize(code: str) -> str:
    for cat, prefixes in CATEGORIES:
        if code.startswith(prefixes):
            return cat
    return "UNCLASSIFIED"


def structured_errors(stages: list[dict]) -> list[dict]:
    """Every non-PASS reason as {stage, code, detail, category}; the dry-run refusal is reported, not an error."""
    out = []
    for s in stages:
        if s["status"] == "PASS" or s["stage"] == "dry_run":
            continue
        for r in s["reasons"]:
            r = str(r)
            code = r.split(":", 1)[0].strip()
            out.append({"stage": s["stage"], "code": code, "detail": r, "category": categorize(code)})
    return out


def submission_envelope(req, inp, fr, v2, receipt, nav, stages) -> dict:
    """tfg.multiagent.rover-submission/1: everything the protected executor's canonical entry needs, in one record.
    It is NOT a command; its authorization block only references a checked record and receipt (never the agent)."""
    rec = req.get("authorization") or {}
    payload = v2.get("payload") or {}
    return {"schema": "tfg.multiagent.rover-submission/1", "status": "READY_TO_SUBMIT_NOT_EXECUTED",
            "mission_id": req["task_id"], "plan_id": (req.get("navigation_plan") or {}).get("plan_id"),
            "rover_id": req["vehicle_id"], "proposal_sha256": req["proposal_sha256"],
            "target": {"point_id": (req.get("target") or {}).get("point_id"), "site_goal": inp.site_goal},
            "observation": {"observation_id": inp.observation_id, "sha256": inp.observation_sha256,
                            "data_kind": inp.observation_data_kind},
            "dependencies": req.get("dependencies"), "coordinator_state": inp.ground_state,
            "limits": {"human": {k: (req.get("navigation_plan") or {}).get(k) for k in ("max_speed_mps", "timeout_s")},
                       "operator": dict(inp.limits)},
            "scope": {"bridge_scope_sha256": req.get("expected_scope_sha256"),
                      "rover_plan_sha256": payload.get("plan_sha256"),
                      "rover_scope_sha256": (payload.get("authorization") or {}).get("scope_sha256")},
            "validity": payload.get("validity"),
            "authorization": ({"record_id": rec.get("authorization_id"), "record_source": rec.get("source"),
                               "receipt_sha256": (receipt or {}).get("authorization_receipt_sha256"),
                               "operator_status": (receipt or {}).get("operator_status"), "mode": inp.mode}
                              if rec else None),
            "conversion": fr.get("conversion"), "conversion_owner": inp.conversion_owner,
            "rover_side": {"snapshot": inp.snapshot_label, "v2_decision": v2.get("decision"), "v2_payload": payload,
                      "executor_request": nav},
            "commands": [], "movement_authorized": False}


def _localization_v2(inp: HandoffInputs, fr: dict) -> dict | None:
    loc = inp.localization
    if not (isinstance(loc, dict) and loc.get("validated") is True and inp.graph is not None and inp.site_goal):
        return None
    try:
        site_from_rover = inp.graph.resolve(inp.site_goal["frame"], loc["frame"], now=inp.now)
    except ValueError:
        return None
    return {"frame": loc["frame"], "x_m": loc["x_m"], "y_m": loc["y_m"], "uncertainty_m": loc["sigma_m"],
            "source": loc["source"], "source_sha256": loc["source_sha256"], "validated": True,
            "observed_at_utc": loc["observed_at"].isoformat(), "transform": site_from_rover.to_rover_matrix()}


# Keys of the executor request that the approved plan and the converted goal define. Executor parameters may only add
# the executor's own tolerances and timings; they can never replace (and so never raise) a plan limit or move the goal.
PLAN_LIMIT_KEYS = frozenset({"max_forward_mps", "max_duration_s"})
PLAN_GOAL_KEYS = frozenset({"x_m", "y_m", "yaw_rad", "frame", "unit", "transform", "timeout_s"})


def executor_parameter_problems(params) -> list[str]:
    if not params:
        return ["EXECUTOR_PARAMETERS_NOT_DECLARED"]
    if (not isinstance(params, dict) or set(params) != {"limits", "goal"} or not isinstance(params["limits"], dict)
            or not isinstance(params["goal"], dict)):
        return ["EXECUTOR_PARAMETERS_INVALID: exactly {limits, goal} mappings are required"]
    clash = sorted(PLAN_LIMIT_KEYS & set(params["limits"])) + sorted(PLAN_GOAL_KEYS & set(params["goal"]))
    return [f"EXECUTOR_PARAMETERS_OVERRIDE_PLAN: {', '.join(clash)}"] if clash else []


def _expected_identity(inp: HandoffInputs) -> dict:
    ident = {**({"vehicle_id": (inp.rover_identity or {}).get("vehicle_id")} if inp.rover_identity else {}),
             **(inp.execution_identity or {})}
    return {k: ident[k] for k in ("vehicle_id", "host_boot_id", "container_boot_id") if k in ident}


def _fixture_localization_evidence(inp: HandoffInputs, loc_v2):
    """Localization evidence for the final adapter: a TEST_FIXTURE declaration in OFFLINE_TEST mode only."""
    if inp.mode != "OFFLINE_TEST" or loc_v2 is None:
        return None
    return {"status": "FRESH", "evidence_source": "TEST_FIXTURE", "identity": _expected_identity(inp),
            "localization": loc_v2}


def _navigate_request(req: dict, fr: dict, inp: HandoffInputs):
    plan, params, goal = req.get("navigation_plan"), inp.executor_params, fr.get("goal_rover")
    missing = []
    if not plan:
        missing.append("NO_NAVIGATION_PLAN: speed and timeout not set by a human")
    if goal is None:
        missing.append("NO_GOAL_IN_ROVER_FRAME")
    missing += executor_parameter_problems(params)
    loc = inp.localization
    if not (isinstance(loc, dict) and loc.get("validated") is True):
        missing.append("NO_ACCREDITED_ROVER_LOCALIZATION")
    if missing:
        return None, missing
    heading = math.atan2(goal["y_m"] - loc["y_m"], goal["x_m"] - loc["x_m"])  # derived: face the travel direction
    return {"kind": "ROVER_NAVIGATE_V1",
            "limits": {"max_forward_mps": plan["max_speed_mps"], "max_duration_s": plan["timeout_s"], **params["limits"]},
            "goal": {"x_m": goal["x_m"], "y_m": goal["y_m"], "yaw_rad": heading, "frame": inp.rover_frame, "unit": "m",
                     "transform": "IDENTITY_SAME_ACCREDITED_FRAME", "timeout_s": plan["timeout_s"], **params["goal"]}}, []


def write_evidence(out: Path, snapshot: Path, *, reviewed: bool = False) -> dict:
    """Run every fixture case through the real code and seal the traces (a new directory; never overwritten)."""
    from datetime import timezone
    from multiagent import rover_handoff_fixtures as fx
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    rows = {}
    label = (f"reviewed {REVIEWED['commit']}+{REVIEWED['patch_sha256'][:12]}" if reviewed else f"committed {ROVER_CONTRACT_COMMIT}")
    with RoverSnapshot(ensure_snapshot(snapshot, reviewed=reviewed)) as rover_side:
        info = rover_side.call("info")["result"]
        for name in fx.cases(now):
            # each case is stamped right before it runs: the rover's adapter checks freshness on the real clock
            req, inp, expected = fx.cases(datetime.now(timezone.utc))[name]
            inp.snapshot_label = label
            trace = handoff(req, inp, rover_side)
            (out / f"{name}.json").write_text(json.dumps(trace, indent=1, sort_keys=True, default=str) + "\n")
            rows[name] = {"classification": trace["classification"], "expected": expected,
                          "as_expected": trace["classification"] == expected, "commands": trace["commands"],
                          "first_blocking": next((f"{s['stage']}: {s['reasons'][:1]}" for s in trace["stages"]
                                                  if s["status"] not in ("PASS",)), None)}
    summary = {"schema": "tfg.multiagent.rover-handoff-evidence/1", "generated_utc": now.isoformat(),
               "rover_commit": REVIEWED["commit"] if reviewed else ROVER_CONTRACT_COMMIT, "rover_snapshot": label,
               "rover_review_patch_sha256": REVIEWED["patch_sha256"] if reviewed else None,
               "rover_contract_sha256": contract_digest(REVIEWED["commit"] if reviewed else ROVER_CONTRACT_COMMIT), "rover_info": info,
               "data_kind": "TEST_FIXTURE + sealed M4c-r1 request (read-only)", "all_as_expected":
               all(r["as_expected"] for r in rows.values()), "no_command_anywhere": all(r["commands"] == [] for r in rows.values()),
               "cases": rows}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    with (out / "SHA256SUMS").open("w") as sums:
        for p in sorted(out.iterdir()):
            if p.name != "SHA256SUMS":
                sums.write(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.name}\n")
    return summary


def main(argv=None) -> int:
    import argparse
    a = argparse.ArgumentParser(description="rover hand-off through the rover's real code (offline, dry-run)")
    a.add_argument("--evidence", type=Path, required=True, help="new directory for the sealed traces")
    a.add_argument("--snapshot", type=Path, required=True, help="where the immutable rover snapshot lives")
    args = a.parse_args(argv)
    s = write_evidence(args.evidence, args.snapshot)
    for name, r in s["cases"].items():
        print(f"{'OK ' if r['as_expected'] else 'BAD'} {name:36s} {r['classification']:42s} {r['first_blocking']}")
    return 0 if s["all_as_expected"] and s["no_command_anywhere"] else 1


if __name__ == "__main__":
    sys.exit(main())
