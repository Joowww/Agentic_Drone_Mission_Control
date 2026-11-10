"""R1 coordination with SYNTHETIC aerial sequences (real aerial coordinator + doubles) and a TEST_DOUBLE
ground executor. No ROS, Docker, simulator, reservation or rover command is involved."""
import json
import os
import subprocess
import sys

import pytest

REAL_POPEN = subprocess.Popen  # captured at import, before fixtures replace it for the aerial doubles

from reporting import agri_scenario_summary as summary
from tests.test_agri_scenario import _real_view, declared, h2, scenario  # noqa: F401 (pytest fixtures)
from tests.test_preflight_sequences import run, start
from tools import agri_ground_coordinator as coordinator
from tools import agri_ground_demo as demo
from tools import preflight_sequences as seq


@pytest.fixture
def views(declared, scenario):  # noqa: F811
    run(scenario, start(scenario, key="r1-coordination"))
    sequence = seq.get_preflight_sequence(request_key="r1-coordination", detail=True)
    binding = summary._bind_expected(*summary.record_associations(declared))
    return demo.synthetic_views(sequence, binding), sequence, binding


def _request(root, view, executor, key="r1-test", *, inputs=None, authorized=True):
    inputs = demo.demo_inputs() if inputs is None else inputs
    prepared = coordinator.prepare(view, inputs, executor)
    authorization = demo.demo_authorization(prepared) if authorized and prepared["candidate"] else None
    return coordinator.request(root, key, view, inputs, authorization, executor)


def _record_path(root, key="r1-test"):
    return coordinator._paths(root, key)[0]


def test_prepare_and_query_never_admit_or_write(views, tmp_path):
    view = views[0]["base"]
    executor = demo.TestDoubleGroundExecutor()
    prepared = coordinator.prepare(view, demo.demo_inputs(), executor)
    assert prepared["stages"]["dependency"] == "MET" and prepared["stages"]["eligibility"] == "ELIGIBLE"
    assert prepared["stages"]["authorization"] == "ABSENT" and prepared["movement_authorized"] is False
    assert coordinator.query(tmp_path, "r1-test") == {"state": "NOT_FOUND", "request_key": "r1-test"}
    assert executor.admit_calls == 0 and not tmp_path.joinpath("records").exists()


def test_repeated_request_never_duplicates_and_conflicts_are_explicit(views, tmp_path):
    view, executor = views[0]["base"], demo.TestDoubleGroundExecutor()
    first = _request(tmp_path, view, executor)
    again = _request(tmp_path, view, executor)
    assert (first["request_status"], again["request_status"], executor.admit_calls) == ("CREATED", "EXISTING", 1)
    other_inputs = demo.demo_inputs()
    other_inputs["ground_tolerance_m"]["value"] = 3.0  # a different candidate under the same key
    conflict = _request(tmp_path, view, executor, inputs=other_inputs)
    assert conflict["request_status"] == "REQUEST_CONFLICT" and executor.admit_calls == 1


def test_lost_admission_reply_is_recovered_by_read_only_lookup_never_by_a_second_admission(views, tmp_path):
    view = views[0]["base"]
    executor = demo.TestDoubleGroundExecutor(admit_mode="LOSE_RESPONSE")
    assert _request(tmp_path, view, executor)["state"] == "ADMISSION_UNCONFIRMED"
    assert _request(tmp_path, view, executor)["request_status"] == "EXISTING"
    states = [coordinator.track(tmp_path, "r1-test", executor)["state"] for _ in range(3)]
    assert states == ["WORKER_OBSERVED", "VERIFIED_SYNTHETIC", "VERIFIED_SYNTHETIC"] and executor.admit_calls == 1


def test_lost_reply_without_lookup_stays_unconfirmed_forever(views, tmp_path):
    executor = demo.TestDoubleGroundExecutor(admit_mode="LOSE_RESPONSE", lookup_supported=False)
    _request(tmp_path, views[0]["base"], executor)
    for _ in range(3):
        assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "ADMISSION_UNCONFIRMED"
    assert executor.admit_calls == 1 and len(executor.reservations) == 1  # the executor's job is not abandoned


def test_coordinator_crash_after_intent_is_recovered_from_the_record(views, tmp_path):
    view, executor = views[0]["base"], demo.TestDoubleGroundExecutor()
    _request(tmp_path, view, executor)
    path = _record_path(tmp_path)
    record = json.loads(path.read_text())
    record.update(state="ADMISSION_REQUESTED", run_id=None, session_id=None)  # reply never persisted
    path.write_text(json.dumps(record))
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "WORKER_OBSERVED"  # restarted coordinator
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "VERIFIED_SYNTHETIC"
    assert executor.admit_calls == 1


@pytest.mark.parametrize("field,value", [("session_id", "OTHER-SESSION"), ("mission_sha256", "f" * 64),
                                         ("simulated_vehicle", "v1"), ("ground_run_id", "OTHER-RUN")])
def test_results_of_another_session_mission_or_vehicle_are_rejected(views, tmp_path, field, value):
    executor = demo.TestDoubleGroundExecutor()
    original = executor._result
    executor._result = lambda job: {**original(job), "binding": {**original(job)["binding"], field: value}}
    _request(tmp_path, views[0]["base"], executor)
    coordinator.track(tmp_path, "r1-test", executor)
    final = coordinator.track(tmp_path, "r1-test", executor)
    assert final["state"] == "REJECTED_RESULT" and final["acceptance"]["reasons"] == [f"BINDING_MISMATCH:{field}"]


def test_passed_job_without_ground_result_does_not_complete_r1(views, tmp_path):
    executor = demo.TestDoubleGroundExecutor()
    executor.query = lambda run_id: {"status": "FINISHED", "report": {"status": "PASSED"}}
    _request(tmp_path, views[0]["base"], executor)
    final = coordinator.track(tmp_path, "r1-test", executor)
    assert final["state"] == "REJECTED_RESULT"
    assert coordinator.scenario_result(views[0]["base"], final)["scenario_complete"] is False


def test_altered_record_hashes_block_every_action(views, tmp_path):
    view, executor = views[0]["base"], demo.TestDoubleGroundExecutor()
    _request(tmp_path, view, executor)
    path = _record_path(tmp_path)
    record = json.loads(path.read_text())
    record["candidate"]["ground_tolerance_m"]["value"] = 50.0  # hash no longer matches
    path.write_text(json.dumps(record))
    calls = executor.admit_calls
    assert coordinator.query(tmp_path, "r1-test")["state"] == "RECORD_INTEGRITY_ERROR"
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "RECORD_INTEGRITY_ERROR"
    assert _request(tmp_path, view, executor)["request_status"] == "RECORD_INTEGRITY_ERROR"
    assert executor.admit_calls == calls


def test_executor_unconfirmed_stays_live_unknown_status_is_terminal_and_nothing_is_released(views, tmp_path):
    executor = demo.TestDoubleGroundExecutor()
    _request(tmp_path, views[0]["base"], executor)
    executor.query = lambda run_id: {"status": "UNCONFIRMED"}  # admitted without live worker, or worker lost
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "ADMITTED_NO_WORKER"
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "ADMITTED_NO_WORKER"  # re-queried
    executor.query = lambda run_id: {"status": "NOT_FOUND"}
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "UNCERTAIN"
    executor.query = lambda run_id: pytest.fail("terminal records are not re-queried")
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "UNCERTAIN"
    assert len(executor.reservations) == 1 and not hasattr(coordinator.GroundExecutor, "release")


def test_fixture_claiming_executed_origin_is_still_only_synthetic(views, tmp_path):
    executor = demo.TestDoubleGroundExecutor()
    original = executor._result
    executor._result = lambda job: {**original(job), "origin": "EXECUTED"}
    _request(tmp_path, views[0]["base"], executor)
    coordinator.track(tmp_path, "r1-test", executor)
    final = coordinator.track(tmp_path, "r1-test", executor)
    assert final["state"] == "VERIFIED_SYNTHETIC"  # TEST_DOUBLE executor and doubled inputs
    assert coordinator.scenario_result(views[0]["base"], final) == {
        "scenario_status": "SYNTHETIC_COMPLETE", "scenario_complete": False, "synthetic_complete": True,
        "r1_state": "VERIFIED_SYNTHETIC"}


def test_real_route_keeps_the_executor_refusals_and_h2_stays_incomplete(tmp_path):
    real = coordinator.RoverGroundExecutorAdapter()
    facts = real.facts()
    assert facts["policy_enabled"] is False and facts["navigation_request_supported"] is True
    view = _real_view()  # the real H2 view
    refused = _request(tmp_path, view, real, authorized=True)
    assert refused["request_status"] == "BLOCKED" and refused["executor_called"] is False
    assert refused["reason"] in ("NOT_ELIGIBLE", "NO_CANDIDATE")
    # Called directly, the unchanged executor refuses before any filesystem write.
    reply = real.admit({"mission_path": None, "request_key": "r1-never", "request": None,
                        "executor_authorization": None, "coordination_context": None})
    assert reply["status"] == "BLOCKED" and reply["reason"] == "OPERATIONAL_ROVER_POLICY_DISABLED"
    assert coordinator.scenario_result(view, None)["scenario_complete"] is False


def test_offline_demo_walks_every_variant_through_the_real_stages(views, tmp_path):
    _, sequence, binding = views
    result = demo.run_demo(tmp_path, sequence, binding)
    table = {v["variant"]: (v["request_status"], v["final_state"], v["admit_calls"], v["scenario"]["scenario_status"])
             for v in result["variants"]}
    assert table == {
        "complete": ("CREATED", "VERIFIED_SYNTHETIC", 1, "SYNTHETIC_COMPLETE"),
        "first_drone_failed": ("BLOCKED", "NOT_FOUND", 0, "FAILED"),
        "poi_not_reached": ("BLOCKED", "NOT_FOUND", 0, "AERIAL_COMPLETED_R1_DEPENDENCY_NOT_MET"),
        "transform_absent": ("BLOCKED", "NOT_FOUND", 0, "AERIAL_COMPLETED_GROUND_PENDING"),
        "authorization_absent": ("BLOCKED", "NOT_FOUND", 0, "AERIAL_COMPLETED_GROUND_PENDING"),
        "executor_refuses": ("CREATED", "REJECTED_BY_EXECUTOR", 1, "AERIAL_COMPLETED_GROUND_REJECTED_BY_EXECUTOR"),
        "insufficient_dwell": ("CREATED", "FAILED", 1, "AERIAL_COMPLETED_GROUND_FAILED"),
        "stop_uncertain": ("CREATED", "UNCERTAIN", 1, "AERIAL_COMPLETED_GROUND_UNCERTAIN"),
        "lost_admission_response": ("UNCONFIRMED", "VERIFIED_SYNTHETIC", 1, "SYNTHETIC_COMPLETE"),
    }
    assert all(v["scenario"]["scenario_complete"] is False for v in result["variants"])


def test_ground_report_is_derived_from_records_and_keeps_h2_incomplete(views, tmp_path):
    real = _real_view()
    report = summary.render_ground_report(real, summary.prepare_ground_task(real))
    assert "`AERIAL_COMPLETED_GROUND_PENDING`; completo: **no**" in report  # no R1 record: the view's status
    assert "Solicitud y admisión: **NOT_REQUESTED_VIA_THIS_COORDINATOR**" in report
    assert "candidato `ninguno`" in report and "frame_transform" in report
    view, executor = views[0]["base"], demo.TestDoubleGroundExecutor()
    _request(tmp_path, view, executor)
    coordinator.track(tmp_path, "r1-test", executor)
    record = coordinator.track(tmp_path, "r1-test", executor)
    prepared = coordinator.prepare(view, demo.demo_inputs(), executor)
    synthetic = summary.render_ground_report(view, prepared, record)
    assert "`SYNTHETIC_COMPLETE`; completo: **no**; completo solo en la demostración sintética" in synthetic
    assert "Parada confirmada: True" in synthetic and "Dobles de prueba en las entradas: ['completion_evidence'" in synthetic
    assert summary.render_ground_report(view, prepared, record) == synthetic  # deterministic
    tasks = summary.scenario_tasks(view, prepared, record)
    assert [t["task_id"] for t in tasks] == ["A1", "A2", "R1"]
    assert tasks[1]["depends_on"] and tasks[2]["artifacts"]["frame_transform"]["status"] == "VERIFIED"
    assert tasks[2]["objective"]["status"] == "PROPOSED_NOT_APPROVED"


# --- Concurrency and interruption points (isolated roots; TEST_DOUBLE executor) ---------------------------

CONCURRENT = r'''
import json, sys, time
from pathlib import Path
from tools import agri_ground_coordinator as coordinator, agri_ground_demo as demo
root, view_file, counter = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
class FileCountingDouble(demo.TestDoubleGroundExecutor):
    def admit(self, task):
        with counter.open("a") as f: f.write(task["request_key"] + "\n")
        time.sleep(0.5)  # widen the window: a check without exclusion would admit twice
        return super().admit(task)
view = json.loads(view_file.read_text())
executor = FileCountingDouble()
inputs = demo.demo_inputs()
prepared = coordinator.prepare(view, inputs, executor)
result = coordinator.request(root, "r1-race", view, inputs, demo.demo_authorization(prepared), executor)
print(result["request_status"])
'''


def test_two_coordinator_processes_create_at_most_one_admission_intent(views, tmp_path):
    view_file, counter = tmp_path / "view.json", tmp_path / "admits.txt"
    view_file.write_text(json.dumps(views[0]["base"]))
    root = tmp_path / "coordinator"
    script = tmp_path / "race.py"
    script.write_text(CONCURRENT)
    procs = [REAL_POPEN([sys.executable, str(script), str(root), str(view_file), str(counter)],
                        cwd=str(coordinator.PROJECT_ROOT), stdout=subprocess.PIPE, text=True,
                        env={**os.environ, "PYTHONPATH": str(coordinator.PROJECT_ROOT)})
             for _ in range(2)]
    outputs = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
    assert outputs == ["CREATED", "EXISTING"]
    assert counter.read_text().splitlines() == ["r1-race"]  # exactly one admission call across processes
    assert len(list((root / "records").iterdir())) == 1


def test_crash_before_persisting_the_intent_leaves_nothing_and_a_retry_admits_once(views, tmp_path, monkeypatch):
    executor, original = demo.TestDoubleGroundExecutor(), coordinator._transition
    monkeypatch.setattr(coordinator, "_transition", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        _request(tmp_path, views[0]["base"], executor)
    assert executor.admit_calls == 0 and coordinator.query(tmp_path, "r1-test")["state"] == "NOT_FOUND"
    monkeypatch.setattr(coordinator, "_transition", original)
    assert _request(tmp_path, views[0]["base"], executor)["request_status"] == "CREATED" and executor.admit_calls == 1


def test_crash_after_intent_before_the_executor_call_is_never_readmitted(views, tmp_path):
    class Killed(demo.TestDoubleGroundExecutor):
        def admit(self, task):
            raise SystemExit("process killed after the intent, before any executor effect")
    executor = Killed()
    with pytest.raises(SystemExit):
        _request(tmp_path, views[0]["base"], executor)
    assert coordinator.query(tmp_path, "r1-test")["state"] == "ADMISSION_REQUESTED"
    recovered = coordinator.track(tmp_path, "r1-test", executor)  # accredited lookup: nothing under the key
    assert recovered["state"] == "ADMISSION_UNCONFIRMED" and "new request key" in recovered["history"][-1]["reason"]
    assert _request(tmp_path, views[0]["base"], executor)["request_status"] == "EXISTING"


def test_failed_query_changes_nothing_and_tracking_resumes(views, tmp_path):
    executor = demo.TestDoubleGroundExecutor()
    _request(tmp_path, views[0]["base"], executor)
    before = coordinator.query(tmp_path, "r1-test")
    real_query = executor.query
    executor.query = lambda run_id: (_ for _ in ()).throw(TimeoutError("query lost"))
    failed = coordinator.track(tmp_path, "r1-test", executor)
    assert failed["tracking_error"].startswith("TimeoutError") and coordinator.query(tmp_path, "r1-test") == before
    executor.query = real_query
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "WORKER_OBSERVED"


def test_crash_before_persisting_acceptance_is_re_evaluated_identically(views, tmp_path, monkeypatch):
    executor = demo.TestDoubleGroundExecutor()
    _request(tmp_path, views[0]["base"], executor)
    coordinator.track(tmp_path, "r1-test", executor)  # WORKER_OBSERVED
    original = coordinator.atomic_json
    monkeypatch.setattr(coordinator, "atomic_json", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        coordinator.track(tmp_path, "r1-test", executor)
    assert coordinator.query(tmp_path, "r1-test")["state"] == "WORKER_OBSERVED"  # nothing half-written
    monkeypatch.setattr(coordinator, "atomic_json", original)
    final = coordinator.track(tmp_path, "r1-test", executor)
    assert final["state"] == "VERIFIED_SYNTHETIC" and executor.admit_calls == 1


# --- Executor phases and start interruptions (TEST_DOUBLE query answers, no executor process) ---------------

@pytest.mark.parametrize("answer,state", [
    ({"status": "ADMITTED", "worker_phase": "ADMITTED_NOT_STARTED", "worker": None}, "ADMITTED_NO_WORKER"),
    ({"status": "STARTING", "worker_phase": "STARTING", "worker": None}, "WORKER_OBSERVED"),  # identity pending
    ({"status": "UNCONFIRMED", "worker_phase": "STARTING_WORKER_LOST_OR_UNKNOWN", "worker": None}, "START_UNCONFIRMED"),
    ({"status": "UNCONFIRMED", "worker_phase": "START_INTENT_WITHOUT_CONFIRMED_WORKER", "worker": None},
     "START_UNCONFIRMED"),
    ({"status": "UNCONFIRMED", "worker_phase": "WORKER_LOST_OR_UNKNOWN", "worker": {"pid": 7}}, "WORKER_UNCONFIRMED"),
    ({"status": "UNCONFIRMED", "worker_phase": "WORKER_LOST_OR_UNKNOWN", "worker": {"pid": 7},
      "failure": {"status": "UNCONFIRMED"}}, "EXECUTION_FAILED"),
    ({"status": "NOT_FOUND"}, "UNCERTAIN"),
])
def test_executor_phases_map_to_explicit_states_without_inference(views, tmp_path, answer, state):
    executor = demo.TestDoubleGroundExecutor()
    _request(tmp_path, views[0]["base"], executor)
    executor.query = lambda run_id: answer
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == state


class StartingDouble(demo.TestDoubleGroundExecutor):
    def __init__(self, behaviour):
        super().__init__()
        self.behaviour, self.start_calls = behaviour, 0

    def start(self, run_id, record):
        self.start_calls += 1
        if self.behaviour == "killed_before_call":
            raise SystemExit("coordinator killed after START_REQUESTED, before the executor call")
        if self.behaviour == "lost_after_start":
            raise TimeoutError("executor started; reply lost")
        return {"status": "STARTED"}


def test_crash_after_start_intent_is_never_restarted(views, tmp_path):
    executor = StartingDouble("killed_before_call")
    _request(tmp_path, views[0]["base"], executor)
    with pytest.raises(SystemExit):
        coordinator.start(tmp_path, "r1-test", executor)
    assert coordinator.query(tmp_path, "r1-test")["state"] == "START_REQUESTED"
    executor.query = lambda run_id: {"status": "ADMITTED", "worker_phase": "ADMITTED_NOT_STARTED", "worker": None}
    # No worker recorded after a start request is NOT proof that it never started: kept, never restarted.
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "START_UNCONFIRMED"
    assert coordinator.start(tmp_path, "r1-test", executor)["start_status"] == "NOT_STARTABLE"
    assert executor.start_calls == 1


def test_lost_start_reply_then_tracking_observes_the_worker(views, tmp_path):
    executor = StartingDouble("lost_after_start")
    _request(tmp_path, views[0]["base"], executor)
    assert coordinator.start(tmp_path, "r1-test", executor)["start_status"] == "UNCONFIRMED"
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "WORKER_OBSERVED"  # double: RUNNING
    assert coordinator.track(tmp_path, "r1-test", executor)["state"] == "VERIFIED_SYNTHETIC"
    assert coordinator.start(tmp_path, "r1-test", executor)["start_status"] == "NOT_STARTABLE"
    assert executor.start_calls == 1 and executor.admit_calls == 1


def test_real_adapter_start_refuses_when_the_executor_records_do_not_match_the_record():
    import uuid
    record = {"request_key": "r1-none", "candidate_sha256": "a" * 64, "authorization_sha256": "b" * 64}
    reply = coordinator.RoverGroundExecutorAdapter().start(str(uuid.uuid4()), record)  # read-only query: NOT_FOUND
    assert reply == {"status": "REJECTED", "reason": "EXECUTOR_BINDING_DIFFERS_FROM_RECORD"}


def test_prepare_query_and_report_with_the_real_adapter_create_no_process_socket_or_write(tmp_path):
    events, active = [], {"on": True}

    def hook(event, args):
        if not active["on"]:
            return
        if event == "open" and len(args) > 1 and isinstance(args[1], str) and set(args[1]) & set("wax+"):
            events.append((event, args[0]))
        elif event in ("os.mkdir", "os.rename", "os.replace", "os.remove", "subprocess.Popen", "socket.connect",
                       "os.fork", "os.exec"):
            events.append((event, args[0] if args else None))
    sys.addaudithook(hook)
    try:
        real, view = coordinator.RoverGroundExecutorAdapter(), _real_view()
        prepared = coordinator.prepare(view, None, real)
        missing = coordinator.query(tmp_path, "r1-none")
        text = summary.render_ground_report(view, prepared, None)
    finally:
        active["on"] = False
    assert events == [] and missing["state"] == "NOT_FOUND" and "completo: **no**" in text
    assert prepared["stages"]["admission"] == "NOT_REQUESTED" and prepared["movement_authorized"] is False
