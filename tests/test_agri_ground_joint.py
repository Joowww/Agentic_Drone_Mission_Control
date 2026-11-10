"""Joint R1 path: REAL coordinator -> REAL adapter -> REAL executor admission -> start -> REAL worker
(Ros2RoverAdapter + RoverControlCore.navigate) -> closure -> REAL lookup/query -> acceptance.

Only the physical session is synthetic: the rover's kinematic model (extended here) integrates the controller's
own velocity commands and answers the explicit disarm service, so samples derive from the commands sent,
never from a prebuilt result. Start uses the executor's real start_ground_trial with a declaration rebuilt
from durable records; closure uses the authorized DISARM_AFTER_OBSERVED_STOP_V1 policy when requested.

Isolation: the rover's `setup` fixture (temporary RUN_ROOT/LOCK_ROOT, TEST-ONLY policy, no subprocess). Every input
is a TEST_DOUBLE, the executor labels the result SYNTHETIC_TEST_DOUBLE, and the real H2 scenario is never
completed. No ROS, Docker, simulator or real reservation is involved.
"""
from dataclasses import asdict
import copy
import json
import math
import os
from pathlib import Path
import sys
import threading

import pytest

from planning.artifact_store import fingerprint, sha256
from reporting import agri_scenario_summary as summary
from tests.test_rover_ground_executor import setup  # noqa: F401 (the rover's isolated executor fixture)
from tests.test_rover_navigation import BIND, Clock, Session
from tools import agri_ground_coordinator as coordinator
from tools import agri_ground_demo as demo
from tools import rover_ground_executor as ground
from tools import vehicle_execution_lock as locks
from tools.rover_control import RoverLimits
from tools.rover_ros2_adapter import Ros2RoverAdapter

ROOT = Path(__file__).resolve().parents[1]
H2_VIEW = ROOT / "evaluation/observability/agri_scenario_view_h2_2026_10_24/scenario_view.json"
TARGET = (0.8, 0.4)
LIMITS = RoverLimits(.4, 1., 130., 1., 3., .5, .03, .03)  # max_duration covers the R1 global timeout (120 s)
CONTROLLER = {"yaw_rad": 0.2, "yaw_tolerance_rad": math.pi, "command_hz": 10., "max_samples": 256,
              "progress_rad": 0.01}
SESSION = "00000000-0000-4000-8000-00000000c0de"  # TEST lifecycle session (the executor requires a UUID)
HOLD = 4


class KinematicSession(Session):
    """The rover's synthetic kinematics with header stamps on the SIMULATION clock. Extra physical behaviours:
    `source` (publisher GID changes) and `disturb_dwell` (pushed out of the radius during dwell)."""

    def probe(self, **kw):
        return {**super().probe(**kw), "session_id": self.session_id}  # the current transport's session

    def observe(self, **kw):
        if self.failure == "disturb_dwell" and self.reads == 40:
            self.x -= .3
        raw = super().observe(**kw)
        sec, nanosec = divmod(int(round(self.clock.now * 1e9)), 10**9)  # never regresses at a second boundary
        stamp = {"sec": sec, "nanosec": nanosec}
        raw["odometry"]["header"]["stamp"] = stamp
        raw["status"]["header"]["stamp"] = stamp
        if self.failure == "source" and self.reads > 5:
            raw["odometry_publisher_gid"] = "5" * 48
        return raw


def synthetic_view():
    """The saved H2 view, re-identified as the synthetic demo scenario (no H2 record or key is used)."""
    view = copy.deepcopy(json.loads(H2_VIEW.read_text()))
    view["scenario"]["sequence"]["sequence_id"] = demo.DEMO_SEQUENCE_ID
    view["sources"] = {"binding_record": {"path": None, "sha256": "SYNTHETIC_DEMO"}}
    return view


FINALIZATION = {"kind": "DISARM_AFTER_OBSERVED_STOP_V1", "timeout_s": 5.0}


def inputs(mission_path, *, tolerance=0.05, target=TARGET, transform_sha="4" * 64, transform=True,
           finalization=None):
    values = {"target_in_rover_frame": {"x_m": target[0], "y_m": target[1], "frame": "odom"},
              "ground_tolerance_m": tolerance,
              "rover_mission": {"path": str(mission_path), "sha256": sha256(Path(mission_path).read_bytes())},
              "completion_evidence": "executor r1_ground_result samples (synthetic kinematic session)",
              "execution_limits": {"rover_limits": asdict(LIMITS), "controller": CONTROLLER}}
    if transform:
        values["frame_transform"] = {"status": "VERIFIED", "sha256": transform_sha,
                                     "from_frame": "SYNTHETIC_POI_FRAME", "to_frame": "odom"}
    if finalization:
        values["finalization_policy"] = finalization
    return {name: {"value": value, "source": "TEST_DOUBLE joint"} for name, value in values.items()}


def authorize(prepared, session=SESSION):
    return {"source": "OPERATOR_DECLARED", "statement": "TEST_DOUBLE declaration, joint offline test only",
            "candidate_sha256": prepared["candidate_sha256"],
            "mission_sha256": prepared["candidate"]["rover_mission"]["value"]["sha256"], "session_id": session}


class HarnessAdapter(coordinator.RoverGroundExecutorAdapter):
    """The REAL adapter with ONLY the physical interface injected (synthetic kinematic session).
    `lose_reply` makes the start reply disappear after the real start ran."""

    def __init__(self, *, pose=(0., 0., 0.), failure=None, cancelled=lambda: False, lose_reply=False):
        self.lose_reply, self.starts, self.session = lose_reply, 0, None

        def factory(journal):
            clock = Clock()
            session = KinematicSession(clock, pose)
            session.failure, session.frozen, session.session_id = failure, failure == "stuck", SESSION
            self.session = session
            return Ros2RoverAdapter(session, binding=BIND, clock=clock, journal=journal)
        super().__init__(physical_factory=factory, readiness=lambda **kw: {"ready": True}, cancelled=cancelled)

    def start(self, run_id, record):
        self.starts += 1
        reply = super().start(run_id, record)
        if self.lose_reply:
            raise TimeoutError("start reply lost after the real start ran")
        return reply

    @property
    def report(self):  # the executor's stored report, read back exactly as the coordinator would
        runs = list(ground.RUN_ROOT.iterdir()) if ground.RUN_ROOT.exists() else []
        reports = sorted((r / "report.json" for r in runs if (r / "report.json").is_file()),
                         key=lambda p: p.stat().st_mtime)
        return json.loads(reports[-1].read_text()) if reports else None


@pytest.fixture
def joint(setup, tmp_path, monkeypatch):  # noqa: F811
    calls = []
    original = ground.admit_ground_trial

    def counted(*args, **kwargs):  # a spy: the real admission still runs
        calls.append(args[1])
        return original(*args, **kwargs)
    monkeypatch.setattr(ground, "admit_ground_trial", counted)
    return {"mission": setup[0], "root": tmp_path / "coordinator", "admissions": calls}


def walk(joint, key="r1-joint", *, values=None, finalize=False, **options):
    adapter = HarnessAdapter(**options)
    view = synthetic_view()
    values = values or inputs(joint["mission"], finalization=FINALIZATION if finalize else None)
    created = coordinator.request(joint["root"], key, view, values,
                                  authorize(coordinator.prepare(view, values, adapter)), adapter)
    assert created["state"] == "ADMITTED", created
    started = coordinator.start(joint["root"], key, adapter)
    final = coordinator.track(joint["root"], key, coordinator.RoverGroundExecutorAdapter())  # restarted coordinator
    return created, started, adapter, final


# --- Nominal path and closure ----------------------------------------------------------------------------

def test_preparation_and_query_never_admit_or_start(joint):
    adapter = HarnessAdapter()
    facts = adapter.facts()
    assert facts["policy_enabled"] is True and facts["navigation_request_supported"] is True  # TEST-ONLY policy
    prepared = coordinator.prepare(synthetic_view(), inputs(joint["mission"]), adapter)
    assert prepared["stages"]["eligibility"] == "ELIGIBLE" and prepared["stages"]["authorization"] == "ABSENT"
    assert coordinator.query(joint["root"], "r1-joint")["state"] == "NOT_FOUND"
    assert joint["admissions"] == [] and adapter.starts == 0


def test_goal_met_with_armed_hold_keeps_both_facts_and_waits_for_executor_closure(joint):
    created, started, adapter, final = walk(joint)
    stored = ground._read(ground.directory(created["run_id"]), "request.json")
    assert stored == created["task"]["request"] and stored["goal"]["tolerance_m"] == 0.05  # authorized values
    assert started["start_status"] == "STARTED" and adapter.report["result"]["goal_outcome"] == "GOAL_REACHED"
    a = final["acceptance"]
    assert final["state"] == "CLOSURE_PENDING" and a["executor_closure"] == "UNCONFIRMED"
    assert a["outcome"] == "VERIFIED" and a["arrival_observed"] and a["dwell_observed_s"] >= 5.0  # goal facts
    assert a["stop_confirmed"] is True and a["armed_after_stop"] == [True, True]  # stop facts: HOLD, still armed
    assert a["authorized_parameters"]["arrival_tolerance_m"] == 0.05 and a["unresolved_contract"] == []
    assert locks.restriction("v3")["owner_id"] == created["run_id"]  # executor keeps its reservation
    assert summary.scenario_with_r1(synthetic_view(), final)["scenario_complete"] is False


def test_authorized_finalization_lets_the_executor_finish_and_the_scenario_is_synthetic_complete(joint):
    created, _, _, final = walk(joint, finalize=True)
    assert ground.query_ground_trial(created["run_id"])["status"] == "FINISHED"  # the executor's own closure
    assert locks.restriction("v3") is None  # released by the executor, never by the coordinator
    a = final["acceptance"]
    assert final["state"] == "VERIFIED_SYNTHETIC" and a["armed_after_stop"] == [True, True]  # stop observed armed
    assert a["finalization"]["status"] == "DISARMED_STATIONARY_OBSERVED" and a["authorized_finalization"] == FINALIZATION
    assert a["closure"]["job_close"] == "COMMIT_ELIGIBLE" and a["closure"]["vehicle_close"] == "DISARMED_STATIONARY_OBSERVED"
    assert a["closure"]["armed_observed"] is False and a["executor_closure"] == "FINISHED"  # then disarmed, committed
    result = summary.scenario_with_r1(synthetic_view(), final)
    assert result == {"scenario_status": "SYNTHETIC_COMPLETE", "scenario_complete": False,
                      "synthetic_complete": True, "r1_state": "VERIFIED_SYNTHETIC"}


def test_goal_met_with_uncertain_stop_shows_both_facts(joint):
    _, _, adapter, final = walk(joint, failure="stop")  # HOLD rejected by the vehicle
    a = final["acceptance"]
    assert adapter.report["result"]["goal_outcome"] == "GOAL_REACHED" and final["state"] == "CLOSURE_PENDING"
    assert a["arrival_observed"] is True and a["stop_confirmed"] is False and "STOP_UNCONFIRMED" in a["reasons"]


def test_goal_failed_with_confirmed_stop_is_terminal_failed(joint):
    _, _, adapter, final = walk(joint, failure="stuck", finalize=True)
    a = final["acceptance"]
    assert adapter.report["result"]["goal_outcome"] == "GOAL_FAILED" and final["state"] == "FAILED"
    assert a["stop_confirmed"] is True and a["arrival_observed"] is False


def test_interruption_during_dwell_restarts_the_dwell_and_the_goal_is_reached_again(joint):
    _, _, adapter, final = walk(joint, failure="disturb_dwell", finalize=True)
    inside = [d["inside"] for d in adapter.report["result"]["decisions"]]
    first_in = inside.index(True)
    left = inside.index(False, first_in)  # entered, then pushed out: dwell interrupted
    assert left > first_in and inside[-1] is True and adapter.report["result"]["goal_outcome"] == "GOAL_REACHED"
    a = final["acceptance"]
    assert final["state"] == "VERIFIED_SYNTHETIC" and a["dwell_observed_s"] >= 5.0
    reentry = len(inside) - inside[::-1].index(False)  # first sample of the final inside run
    assert reentry > left  # the accepted dwell is the run AFTER the interruption


def _authorized_goal(tmp_path):
    """The NavigationGoal exactly as the coordinator would send it for an authorized R1 candidate."""
    from tools.rover_control import NavigationGoal
    mission = tmp_path / "mission.json"
    mission.write_text("{}")
    view, values = synthetic_view(), inputs(mission)
    candidate = summary.prepare_ground_task(view, inputs=values, executor_facts={
        "kind": "TEST", "policy_enabled": True, "navigation_request_supported": True})["candidate"]
    return NavigationGoal(**coordinator.navigation_request(candidate)["goal"])


# The OLD defect (recovery after arrival had to beat the best-ever distance by progress_m, so a slow recovery
# ended in NO_PROGRESS) was reproduced on 25/10 and is recorded in evaluation/observability/
# agri_r1_joint_closure_2026_10_25 (historical, unchanged). The tests below check the rover's CORRECTION with the
# authorized R1 parameters; they do not reproduce the old behaviour.

def test_corrected_controller_recovers_after_disturbance_with_the_authorized_r1_parameters(tmp_path):
    from tools.rover_control import GoalController
    goal = _authorized_goal(tmp_path)
    assert (goal.tolerance_m, goal.progress_m, goal.no_progress_s, goal.dwell_s, goal.timeout_s) == \
        (0.05, 0.5, 10.0, 5.0, 120.0)  # from the candidate, not test-local values
    c = GoalController(goal, LIMITS)
    c.step(0.0, 0.0, 0.2, 0.0)
    first = c.step(0.8, 0.4, 0.2, 2.0)
    assert first["phase"] == "DWELL" and not first["reached"]
    assert not c.step(0.8, 0.4, 0.2, 4.0)["reached"]          # 2 s of dwell only
    phases, distances = [], []
    for k, now in enumerate((5.0, 8.0, 11.0, 14.0, 17.0)):     # displaced 0.3 m at t=5, recovering at 0.02 m/s
        d = c.step(0.5 + k * 0.06, 0.4, 0.2, now)
        phases.append(d["phase"]), distances.append(d["distance_m"])
        assert not d["reached"]
    assert phases == ["RECOVERY"] * 5                          # the dwell was interrupted
    assert distances == sorted(distances, reverse=True)       # approaching again, no NO_PROGRESS raised
    back = c.step(0.8, 0.4, 0.2, 18.0)                         # radius regained
    assert back["phase"] == "DWELL" and not back["reached"]
    assert not c.step(0.8, 0.4, 0.2, 22.9)["reached"]          # a NEW dwell: 4.9 s is not enough
    assert c.step(0.8, 0.4, 0.2, 23.0)["reached"]              # complete new dwell (5 s from re-entry)
    assert c.started == 0.0                                    # phases never moved the global start


def test_phase_changes_never_extend_the_global_timeout(tmp_path):
    from dataclasses import replace
    from tools.rover_control import GoalController
    goal = replace(_authorized_goal(tmp_path), timeout_s=30.0)
    c = GoalController(goal, LIMITS)
    c.step(0.8, 0.4, 0.2, 0.0)
    with pytest.raises(ValueError, match="GOAL_TIMEOUT"):
        for n in range(1, 40):  # genuine displacement/recovery cycles, each with real progress
            c.step(0.5 if n % 4 in (1, 2) else 0.8, 0.4, 0.2, float(n))
    assert c.started == 0.0


def test_immobile_after_disturbance_still_ends_in_no_progress(tmp_path):
    from tools.rover_control import GoalController
    c = GoalController(_authorized_goal(tmp_path), LIMITS)
    c.step(0.0, 0.0, 0.2, 0.0)
    c.step(0.8, 0.4, 0.2, 2.0)
    c.step(0.5, 0.4, 0.2, 5.0)                                 # displaced and stuck
    with pytest.raises(ValueError, match="NO_PROGRESS"):
        c.step(0.5, 0.4, 0.2, 15.0)


def test_repeated_disturbances_without_net_recovery_end_in_no_progress(tmp_path):
    from tools.rover_control import GoalController
    c = GoalController(_authorized_goal(tmp_path), LIMITS)
    c.step(0.0, 0.0, 0.2, 0.0)
    c.step(0.8, 0.4, 0.2, 2.0)
    with pytest.raises(ValueError, match="NO_PROGRESS"):
        for k in range(40):  # pushed back to the same place each time it starts recovering
            c.step(0.5 if k % 2 == 0 else 0.53, 0.4, 0.2, 3.0 + k)


class SlowRecoverySession(KinematicSession):
    """Displaced 0.3 m during dwell, then the vehicle can only move at 0.02 m/s (slow recovery)."""

    def observe(self, **kw):
        if self.reads == 40 and not getattr(self, "displaced", False):
            self.x -= .3
            self.displaced = True
        return super().observe(**kw)

    def exchange(self, command, **kw):
        reply = super().exchange(command, **kw)
        if getattr(self, "displaced", False):
            self.v = min(self.v, .02)
        return reply


def test_slow_recovery_crosses_coordinator_executor_and_acceptance(joint, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "KinematicSession", SlowRecoverySession)
    _, _, adapter, final = walk(joint, key="r1-slow", finalize=True, pose=(0.8, 0.4, 0.2))
    decisions = adapter.report["result"]["decisions"]
    recovery = [d for d in decisions if d["phase"] == "RECOVERY"]
    assert recovery and recovery[-1]["received_monotonic_s"] - recovery[0]["received_monotonic_s"] > 10.0
    assert adapter.report["result"]["goal_outcome"] == "GOAL_REACHED"
    a = final["acceptance"]
    assert final["state"] == "VERIFIED_SYNTHETIC" and a["dwell_observed_s"] >= 5.0  # the NEW dwell, sim clock
    assert a["authorized_parameters"]["arrival_tolerance_m"] == 0.05 and a["closure"]["job_close"] == "COMMIT_ELIGIBLE"
    out = os.environ.get("AGRI_JOINT_EVIDENCE_DIR")
    if out:  # explicit, opt-in export of THIS synthetic run (never into an existing directory)
        target = Path(out) / "slow_recovery"
        target.mkdir(parents=True, exist_ok=False)
        view = synthetic_view()
        prepared = coordinator.prepare(view, inputs(joint["mission"], finalization=FINALIZATION), HarnessAdapter())
        (target / "joint_report.md").write_text(
            "<!-- SYNTHETIC JOINT RUN: slow recovery after a dwell disturbance; no rover moved -->\n"
            + summary.render_ground_report(view, prepared, final) + "\n")
        (target / "r1_record.json").write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n")
        phases = [{k: d.get(k) for k in ("phase", "distance_m", "inside", "reached", "progress_age_s",
                                         "progress_quantum_m", "received_monotonic_s")} for d in decisions]
        (target / "controller_decisions.json").write_text(json.dumps(phases, indent=2) + "\n")


@pytest.mark.parametrize("failure", ["lost", "frame", "source"])
def test_observation_failures_never_yield_success(joint, failure):
    created, _, adapter, final = walk(joint, failure=failure)
    assert adapter.report["result"]["goal_outcome"] != "GOAL_REACHED"
    assert final["state"] in ("CLOSURE_PENDING", "EXECUTION_FAILED", "UNCERTAIN", "FAILED")
    assert final.get("acceptance", {}).get("outcome") != "VERIFIED"
    assert locks.restriction("v3")["owner_id"] == created["run_id"]


def test_cancellation_is_not_success(joint):
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] > 5
    _, _, adapter, final = walk(joint, cancelled=cancel)
    assert adapter.report["result"]["goal_outcome"] == "GOAL_FAILED"
    assert final["acceptance"]["outcome"] != "VERIFIED" and final["state"] == "CLOSURE_PENDING"


# --- Authorization, transformation and requests -----------------------------------------------------------

def test_incompatible_authorization_is_refused_by_coordinator_and_by_executor(joint):
    adapter = HarnessAdapter()
    view, values = synthetic_view(), inputs(joint["mission"])
    stale = authorize(coordinator.prepare(view, values, adapter))
    moved = inputs(joint["mission"], target=(0.9, 0.4))
    assert coordinator.request(joint["root"], "r1-a", view, moved, stale, adapter)["reason"] \
        == "AUTHORIZATION_SCOPE_DIFFERS_FROM_CANDIDATE"
    # At the boundary: a coordination context mixing candidate B with the authorization of candidate A.
    candidate_b = coordinator.prepare(view, moved, adapter)["candidate"]
    request_b = coordinator.navigation_request(candidate_b)
    reply = adapter.admit({"mission_path": joint["mission"], "request_key": "r1-mix", "request": request_b,
                           "executor_authorization": {"mission_sha256": stale["mission_sha256"],
                                                      "request_fingerprint": fingerprint(request_b), "statement": "x"},
                           "coordination_context": {"candidate": candidate_b, "authorization": stale}})
    assert reply["status"] == "REJECTED" and "contradiction" in reply["reason"]
    assert joint["admissions"] == ["r1-mix"]  # the executor itself refused; nothing admitted


def test_absent_or_changed_transformation(joint):
    adapter = HarnessAdapter()
    view = synthetic_view()
    absent = inputs(joint["mission"], transform=False)
    assert coordinator.request(joint["root"], "r1-t0", view, absent, None, adapter)["reason"] == "NO_CANDIDATE"
    # The candidate's transformation differs from the adapter's accredited pose reference: the worker refuses.
    changed = inputs(joint["mission"], transform_sha="5" * 64)
    created, _, adapter, final = walk(joint, key="r1-t1", values=changed)
    failure = ground.query_ground_trial(created["run_id"])["failure"]
    assert failure["status"] == "UNCONFIRMED" and failure["control_attempted"] is False and adapter.session.commands == []
    assert final["state"] == "EXECUTION_FAILED" and "frame" in json.dumps(final["executor_failure"]).lower()


def test_duplicate_and_conflicting_requests_never_reach_the_executor_twice(joint):
    adapter = HarnessAdapter()
    view, values = synthetic_view(), inputs(joint["mission"])
    prepared = coordinator.prepare(view, values, adapter)
    first = coordinator.request(joint["root"], "r1-dup", view, values, authorize(prepared), adapter)
    again = coordinator.request(joint["root"], "r1-dup", view, values, authorize(prepared), adapter)
    other = inputs(joint["mission"], tolerance=0.1)
    changed = coordinator.request(joint["root"], "r1-dup", view, other,
                                  authorize(coordinator.prepare(view, other, adapter)), adapter)
    other_session = coordinator.request(joint["root"], "r1-dup", view, values, authorize(prepared, "OTHER"), adapter)
    assert (first["request_status"], again["request_status"], changed["request_status"],
            other_session["request_status"]) == ("CREATED", "EXISTING", "REQUEST_CONFLICT", "REQUEST_CONFLICT")
    assert joint["admissions"] == ["r1-dup"]


def test_concurrent_duplicate_request_and_start_run_once(joint):
    adapter = HarnessAdapter()
    view, values = synthetic_view(), inputs(joint["mission"], finalization=FINALIZATION)
    auth = authorize(coordinator.prepare(view, values, adapter))
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        coordinator.request(joint["root"], "r1-race", view, values, auth, adapter)["request_status"]))
        for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    starts = []
    threads = [threading.Thread(target=lambda: starts.append(
        coordinator.start(joint["root"], "r1-race", adapter)["start_status"])) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["CREATED", "EXISTING"] and sorted(starts) == ["NOT_STARTABLE", "STARTED"]
    assert joint["admissions"] == ["r1-race"] and adapter.starts == 1


# --- Lost replies and restarts ------------------------------------------------------------------------------

def test_lost_admission_reply_is_recovered_through_the_executor_index_without_readmission(joint):
    class LosingAdapter(HarnessAdapter):
        def admit(self, task):
            super().admit(task)
            self.launch_tokens.clear()  # the reply, token included, is lost
            raise TimeoutError("reply lost after the executor admitted")
    view, values = synthetic_view(), inputs(joint["mission"])
    adapter = LosingAdapter()
    auth = authorize(coordinator.prepare(view, values, adapter))
    assert coordinator.request(joint["root"], "r1-lost", view, values, auth, adapter)["state"] == "ADMISSION_UNCONFIRMED"
    assert coordinator.request(joint["root"], "r1-lost", view, values, auth, adapter)["request_status"] == "EXISTING"
    recovered = coordinator.track(joint["root"], "r1-lost", coordinator.RoverGroundExecutorAdapter())
    assert recovered["state"] == "ADMITTED_NO_WORKER" and recovered["run_id"]
    # Start is rebuilt from durable records only (no token): a fresh adapter in a "new process" starts it once.
    fresh = HarnessAdapter()
    assert coordinator.start(joint["root"], "r1-lost", fresh)["start_status"] == "STARTED"
    assert coordinator.start(joint["root"], "r1-lost", fresh)["start_status"] == "NOT_STARTABLE"
    final = coordinator.track(joint["root"], "r1-lost", coordinator.RoverGroundExecutorAdapter())
    assert final["state"] == "CLOSURE_PENDING" and final["acceptance"]["outcome"] == "VERIFIED"
    assert len(joint["admissions"]) == 1 and fresh.starts == 1
    assert locks.restriction("v3")["owner_id"] == recovered["run_id"]  # no finalization requested: retained


def test_lost_start_reply_is_never_repeated_and_the_result_is_recovered_from_storage(joint):
    created, started, adapter, final = walk(joint, key="r1-lost-start", lose_reply=True, finalize=True)
    assert started["start_status"] == "UNCONFIRMED" and adapter.starts == 1
    assert coordinator.start(joint["root"], "r1-lost-start", adapter)["start_status"] == "NOT_STARTABLE"
    assert final["state"] == "VERIFIED_SYNTHETIC"  # recovered by a fresh coordinator from the executor's records
    assert [h["state"] for h in final["history"]] == ["ADMISSION_REQUESTED", "ADMITTED", "START_REQUESTED",
                                                      "START_UNCONFIRMED", "VERIFIED_SYNTHETIC"]


def test_coordinator_restart_between_admission_and_start_needs_nothing_from_memory(joint):
    adapter = HarnessAdapter()
    view, values = synthetic_view(), inputs(joint["mission"], finalization=FINALIZATION)
    coordinator.request(joint["root"], "r1-restart", view, values,
                        authorize(coordinator.prepare(view, values, adapter)), adapter)
    del adapter  # the admitting process is gone
    restarted = HarnessAdapter()
    assert coordinator.start(joint["root"], "r1-restart", restarted)["start_status"] == "STARTED"
    final = coordinator.track(joint["root"], "r1-restart", coordinator.RoverGroundExecutorAdapter())
    assert final["state"] == "VERIFIED_SYNTHETIC"


# --- Evidence integrity against the executor's authoritative records -----------------------------------------

def _forge(run_id, mutate):
    """Rewrite report.json and job.report_sha256 CONSISTENTLY (someone with write access to all local records)."""
    root = ground.directory(run_id)
    report = json.loads((root / "report.json").read_text())
    mutate(report)
    locks.atomic_json(root / "report.json", report)
    job = json.loads((root / "job.json").read_text())
    job["report_sha256"] = sha256((root / "report.json").read_bytes())
    locks.atomic_json(root / "job.json", job)


def _reaccept(joint, key):
    record = coordinator.query(joint["root"], key)
    try:
        status = ground.query_ground_trial(record["run_id"])
    except ValueError:  # the executor itself detected the inconsistency; acceptance must refuse too
        status = {"status": "FINISHED", "report": {}}
    return coordinator._evaluate(record, status)


def test_samples_of_another_job_are_rejected(joint):
    walk(joint, key="r1-a", finalize=True)
    _, _, adapter_b, _ = walk(joint, key="r1-b", finalize=True, pose=(0.8, 0.4, 0.2))
    record_a = coordinator.query(joint["root"], "r1-a")
    problems, _ = coordinator._evaluate(record_a, {"status": "FINISHED", "report": adapter_b.report})
    assert "RESULT_DIFFERS_FROM_EXECUTOR_RECORD" in problems


def test_reference_to_another_report_is_rejected(joint):
    created_a, _, _, _ = walk(joint, key="r1-ra", finalize=True)
    created_b, _, _, _ = walk(joint, key="r1-rb", finalize=True, pose=(0.8, 0.4, 0.2))
    root_a, root_b = ground.directory(created_a["run_id"]), ground.directory(created_b["run_id"])
    job = json.loads((root_a / "job.json").read_text())
    job["report_sha256"] = json.loads((root_b / "job.json").read_text())["report_sha256"]
    locks.atomic_json(root_a / "job.json", job)
    problems, _ = _reaccept(joint, "r1-ra")
    assert problems and problems[0].startswith("EXECUTOR_RECORD_INTEGRITY")
    record = coordinator.query(joint["root"], "r1-ra")
    tracked = coordinator.track(joint["root"], "r1-ra", coordinator.RoverGroundExecutorAdapter())
    assert tracked["state"] == record["state"]  # terminal record unchanged; nothing re-accepted


def test_destination_substitution_is_rejected(joint):
    created, _, _, _ = walk(joint, key="r1-dest", finalize=True)
    root = ground.directory(created["run_id"])
    request = json.loads((root / "request.json").read_text())
    request["goal"]["x_m"] = 5.0
    locks.atomic_json(root / "request.json", request)
    problems, _ = _reaccept(joint, "r1-dest")
    assert problems and problems[0].startswith("EXECUTOR_RECORD_INTEGRITY")


def test_consistently_forged_passed_without_samples_is_rejected(joint):
    created, _, _, _ = walk(joint, key="r1-empty", finalize=True)
    _forge(created["run_id"], lambda r: r["r1_ground_result"].update(samples=[]))
    problems, _ = _reaccept(joint, "r1-empty")
    assert "RESULT_SAMPLES_DIFFER_FROM_EXECUTOR_OBSERVATIONS" in problems


def test_consistently_forged_short_dwell_is_judged_by_all_samples_not_the_last_one(joint):
    created, _, _, _ = walk(joint, key="r1-short", finalize=True)

    def keep_last(report):  # keep only the final (correct) samples, in BOTH result and observations
        report["r1"]["samples"] = report["r1"]["samples"][-4:]
        report["r1"]["samples_sha256"] = fingerprint(report["r1"]["samples"])
        report["r1_ground_result"]["samples"] = report["r1_ground_result"]["samples"][-4:]
    _forge(created["run_id"], keep_last)
    problems, acceptance = _reaccept(joint, "r1-short")
    assert problems == [] and acceptance["outcome"] == "FAILED"
    assert acceptance["dwell_observed_s"] < 5.0 and "PASSED_THROUGH_NO_DWELL" in acceptance["reasons"]


def test_executed_label_added_to_synthetic_evidence_does_not_upgrade_it(joint):
    created, _, _, _ = walk(joint, key="r1-label", finalize=True)
    _forge(created["run_id"], lambda r: r["r1_ground_result"].update(origin="EXECUTED"))
    problems, acceptance = _reaccept(joint, "r1-label")
    assert problems == [] and acceptance["synthetic"] is True  # TEST_DOUBLE inputs: at most VERIFIED_SYNTHETIC
    assert coordinator._final_state(acceptance) == "VERIFIED_SYNTHETIC"


def test_the_real_h2_view_is_never_completed(joint):
    real = json.loads(H2_VIEW.read_text())
    refused = coordinator.request(joint["root"], "r1-h2", real, None, None, HarnessAdapter())
    assert refused["request_status"] == "BLOCKED" and refused["reason"] == "NO_CANDIDATE"
    assert summary.scenario_with_r1(real, None)["scenario_complete"] is False and joint["admissions"] == []


# --- Deterministic report and opt-in evidence export ---------------------------------------------------------

REPORT_VARIANTS = {"armed_hold": {}, "finalized": {"finalize": True}, "stop_uncertain": {"failure": "stop"},
                   "goal_failed": {"failure": "stuck", "finalize": True}}
EXPECTED = {"armed_hold": "estado R1: **CLOSURE_PENDING**", "finalized": "`SYNTHETIC_COMPLETE`",
            "stop_uncertain": "Parada confirmada: False", "goal_failed": "estado R1: **FAILED**"}


@pytest.mark.parametrize("name", sorted(REPORT_VARIANTS))  # one isolated executor store per variant
def test_joint_deterministic_report(joint, name):
    created, _, adapter, final = walk(joint, key=f"r1-report-{name}", **REPORT_VARIANTS[name])
    view = synthetic_view()
    prepared = coordinator.prepare(view, inputs(joint["mission"]), HarnessAdapter())
    text = summary.render_ground_report(view, prepared, final)
    assert EXPECTED[name] in text and "no es autenticación humana" in text
    assert summary.render_ground_report(view, prepared, final) == text  # deterministic
    out = os.environ.get("AGRI_JOINT_EVIDENCE_DIR")
    if out:  # explicit, opt-in export of THIS synthetic run (never into an existing directory)
        target = Path(out) / name
        target.mkdir(parents=True, exist_ok=False)
        (target / "joint_report.md").write_text(
            "<!-- SYNTHETIC JOINT RUN: real coordinator/adapter/executor/worker, kinematic session; "
            "no rover moved -->\n" + text + "\n")
        (target / "r1_record.json").write_text(json.dumps(final, indent=2, ensure_ascii=False) + "\n")
        (target / "executor_report.json").write_text(json.dumps(adapter.report, indent=2, ensure_ascii=False) + "\n")


def test_executor_keeps_the_reservation_after_an_armed_hold_so_a_second_r1_is_refused(joint):
    walk(joint, key="r1-first")  # armed HOLD: job UNCONFIRMED, v3 reservation kept
    adapter = HarnessAdapter()
    view, values = synthetic_view(), inputs(joint["mission"], tolerance=0.06)
    second = coordinator.request(joint["root"], "r1-second", view, values,
                                 authorize(coordinator.prepare(view, values, adapter)), adapter)
    assert second["state"] == "REJECTED_BY_EXECUTOR" and second["executor_reply"]["status"] == "BLOCKED"
