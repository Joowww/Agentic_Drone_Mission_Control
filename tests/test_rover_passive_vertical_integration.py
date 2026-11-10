import pytest
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
import hashlib
import json

from tools import simulation_lifecycle as life
from tools.rover_passive_phases import PHASES
from tools.rover_passive_scope import canonical_json, authorization_text, scope_sha256
from tools.rover_parameter_correlation import REQUIRED
from tools.rover_stationarity import StationarityThresholds, analyze
from test_rover_passive_scope_start import scope_auth, setup, start

STATUS_GID="a"*48
ODOM_GID="b"*48


def stationary_capture(lifecycle_id, host_boot_id):
    records=[]
    for i in range(100):
        t=i*0.35
        stamp=int((i+1)*350_000_000)
        records.append({"lifecycle_id":lifecycle_id,"host_boot_id":host_boot_id,
            "host_received_monotonic_s":t,"host_clock":"HOST_MONOTONIC_S",
            "sample_metadata":{"status":{"stamp_ns":stamp,"received_monotonic_s":t+0.01,
                "stamp_clock":"SIMULATED_STAMP_NS","receipt_clock":"WORKER_MONOTONIC_S"},
                "odometry":{"stamp_ns":stamp,"received_monotonic_s":t+0.02,
                "stamp_clock":"SIMULATED_STAMP_NS","receipt_clock":"WORKER_MONOTONIC_S"}},
            "worker_telemetry_age_s":{"status":0.05,"odometry":0.05},
            "status":{"armed":False,"flying":False,"failsafe":[]},
            "status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID,
            "frame_id":"odom","child_frame_id":"base_link","driving":False,
            "measurement_units":{"position":"m","linear_velocity":"m/s","angular_velocity":"rad/s","orientation":"quaternion_xyzw"},
            "position":{"x":0.0,"y":0.0,"z":0.0},"orientation":{"x":0.0,"y":0.0,"z":0.0,"w":1.0},
            "linear_velocity":{"x":0.0,"y":0.0,"z":0.0},"angular_velocity":{"x":0.0,"y":0.0,"z":0.0}})
    capture={"capture_complete":True,"records":records,"movement_authorized":False,"commands_sent":0}
    digest=hashlib.sha256(canonical_json(capture).encode()).hexdigest()
    return capture,digest


def phase_operations(host_boot_id):
    def binding(ctx):
        return {"binding_schema":"tfg.rover.motion-binding/2","verdict":"BOUND","lifecycle_id":ctx["session_id"],
            "host_boot_id":host_boot_id,"container_boot_id":"container-boot-1","vehicle_id":"rover_01",
            "status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID,"commands_sent":0}
    values={name:1.0 for name in REQUIRED}
    capture,digest=stationary_capture("pending",host_boot_id)
    def observe(ctx):
        # Rebind session identity after START; capture fixture is never sent to a transport.
        capture["records"]=[{**row,"lifecycle_id":ctx["session_id"]} for row in capture["records"]]
        digest=hashlib.sha256(canonical_json(capture).encode()).hexdigest()
        return {"observation_count":100,"records":capture["records"],"capture_sha256":digest,
            "commands_sent":0,"movement_authorized":False}
    def open_worker(ctx):
        life.consume_passive_worker_reservation(ctx["session_id"],ctx["worker_reservation_id"],ctx["scope"]["environment_execution"]["persistent_identity"]["container_id"])
        return {"worker_id":"worker-1","reservation_id":ctx["worker_reservation_id"],"container_id":ctx["scope"]["environment_execution"]["persistent_identity"]["container_id"],
            "mode":"PASSIVE","status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID}
    return {"ready":lambda ctx:{"armed":False,"armable":True},"motion_binding":binding,
        "parameters":lambda ctx:{"ros_values":values,"mavlink_values":dict(values),"parameter_write_count":0},
        "open_worker":open_worker,
        "observe":observe,"close_worker":lambda ctx:{"worker_id":ctx["worker_id"],"closed":True}}


class OfflineFixtureAuthority:
    def verify(self, scope, declaration, *, revocation="ACTIVE", vehicle_id="rover_01"):
        exact=authorization_text(scope["operator_id"],scope_sha256(scope))
        return (revocation=="ACTIVE" and vehicle_id==scope["vehicle"]["vehicle_id"] and declaration==exact)


def test_vertical_offline_session_uses_protected_lifecycle_and_records_all_phases(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc); precheck,scope,digest,authorization=scope_auth(now)
    setup(monkeypatch,tmp_path)
    authority=OfflineFixtureAuthority()
    assert authority.verify(scope,authorization)
    assert not authority.verify(scope,authorization,revocation="REVOKED")
    assert not authority.verify(scope,authorization,vehicle_id="another-rover")
    result=life.run_passive_sequence(scope,digest,authorization,phase_operations("host-boot-1"),gui=False)
    assert result["status"]=="COMPLETE",result
    state=json.loads((life.PASSIVE_SESSION_ROOT/(scope["session_id"]+".json")).read_text())
    assert state["state"]=="CLOSED", state["phase_verification"]["reasons"]
    assert state["phase_verification"]["complete"] is True
    assert state["phase_verification"]["phases_seen"]==list(PHASES)
    assert state["phase_verification"]["observations"]==100
    assert state["movement_authorized"] is False
    assert result["stop"]["operation"]["passive_phase_verification"]["verdict"]=="COMPLETE_PASSIVE_SESSION"


def test_runtime_phase_journal_rejects_duplicate_worker_wrong_gid_incomplete_params_and_short_capture(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc); precheck,scope,digest,authorization=scope_auth(now)
    setup(monkeypatch,tmp_path)
    opened=start((precheck,scope,digest,authorization),authorization)
    assert opened["status"]=="SUCCESS"
    owner=scope["session_id"]
    life.record_passive_phase(owner,"READY_ARMABLE",{"armed":False,"armable":True})
    binding={"binding_schema":"tfg.rover.motion-binding/2","verdict":"BOUND","lifecycle_id":owner,
        "host_boot_id":"host-boot-1","container_boot_id":"container-boot-1","vehicle_id":"rover_01",
        "status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID}
    life.record_passive_phase(owner,"MOTION_BINDING_V2",binding)
    values={name:1.0 for name in REQUIRED}
    life.record_passive_phase(owner,"PARAMETERS_READ",{"ros_values":values,"mavlink_values":values,"parameter_write_count":0})
    reservation=life.reserve_passive_worker(owner)
    life.consume_passive_worker_reservation(owner,reservation,"a"*64)
    life.record_passive_phase(owner,"WORKER_OPEN",{"worker_id":"worker-1","reservation_id":reservation,"container_id":"a"*64,"mode":"PASSIVE",
        "status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID})
    import pytest
    with pytest.raises(Exception,match="already reserved"):
        life.reserve_passive_worker(owner)
    with pytest.raises(Exception,match="out of order"):
        life.record_passive_phase(owner,"WORKER_OPEN",{"worker_id":"worker-2","mode":"PASSIVE",
            "status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID})
    with pytest.raises(Exception,match="exactly 100"):
        life.record_passive_phase(owner,"OBSERVATIONS",{"observation_count":99,"records":[{}]*99,
            "commands_sent":0,"movement_authorized":False})
    result=life.run_lifecycle("stop",gui=False,profile="rover_only",passive_session_owner=owner)
    assert result["status"]=="SUCCESS"
    state=json.loads((life.PASSIVE_SESSION_ROOT/(owner+".json")).read_text())
    assert state["state"]=="CLOSED_INCOMPLETE"
    assert state["phase_verification"]["complete"] is False

def test_host_monotonic_supervisor_requests_protected_stop_while_provider_is_blocked(monkeypatch,tmp_path):
    import time
    from tools import rover_passive_scope as passive
    monkeypatch.setattr(passive,"MAX_SESSION_DURATION_S",0.15)
    monkeypatch.setattr(life,"PASSIVE_STOP_GUARD_S",0.03)
    now=datetime.now(timezone.utc); precheck,scope,digest,authorization=scope_auth(now)
    _,sessions,_,calls=setup(monkeypatch,tmp_path)
    def blocked_ready(ctx):
        time.sleep(0.25)
        return {"armed":False,"armable":True}
    ops={"ready":blocked_ready,"motion_binding":lambda ctx:{},"parameters":lambda ctx:{},
         "open_worker":lambda ctx:{},"observe":lambda ctx:{},"close_worker":lambda ctx:{}}
    result=life.run_passive_sequence(scope,digest,authorization,ops,gui=False)
    assert calls==["start","stop"], result
    assert result["stop"]["status"]=="SUCCESS"
    assert result["session_state"]=="CLOSED_INCOMPLETE"
    assert result["movement_authorized"] is False

def _advance_to_observations(owner, scope, *, observation_mutation=None):
    life.record_passive_phase(owner,"READY_ARMABLE",{"armed":False,"armable":True})
    life.record_passive_phase(owner,"MOTION_BINDING_V2",{"binding_schema":"tfg.rover.motion-binding/2","verdict":"BOUND",
        "lifecycle_id":owner,"host_boot_id":"host-boot-1","container_boot_id":"container-boot-1",
        "vehicle_id":"rover_01","status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID})
    values={name:1.0 for name in REQUIRED}
    life.record_passive_phase(owner,"PARAMETERS_READ",{"ros_values":values,"mavlink_values":dict(values),"parameter_write_count":0})
    reservation=life.reserve_passive_worker(owner)
    life.consume_passive_worker_reservation(owner,reservation,scope["environment_execution"]["persistent_identity"]["container_id"])
    life.record_passive_phase(owner,"WORKER_OPEN",{"worker_id":"worker-1","reservation_id":reservation,
        "container_id":scope["environment_execution"]["persistent_identity"]["container_id"],"mode":"PASSIVE",
        "status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID})
    capture,digest=stationary_capture(owner,"host-boot-1")
    if observation_mutation:
        observation_mutation(capture["records"])
    digest=hashlib.sha256(canonical_json(capture).encode()).hexdigest()
    evidence={"observation_count":100,"records":capture["records"],"capture_sha256":digest,
        "commands_sent":0,"movement_authorized":False}
    life.record_passive_phase(owner,"OBSERVATIONS",evidence)
    return digest


def test_runtime_rejects_incomplete_parameters_before_worker_reservation(monkeypatch,tmp_path):
    import pytest
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    _,_,_,calls=setup(monkeypatch,tmp_path)
    assert start((p,scope,digest,authorization),authorization)["status"]=="SUCCESS"
    owner=scope["session_id"]
    life.record_passive_phase(owner,"READY_ARMABLE",{"armed":False,"armable":True})
    life.record_passive_phase(owner,"MOTION_BINDING_V2",{"binding_schema":"tfg.rover.motion-binding/2","verdict":"BOUND",
        "lifecycle_id":owner,"host_boot_id":"host-boot-1","container_boot_id":"container-boot-1",
        "vehicle_id":"rover_01","status_publisher_gid":STATUS_GID,"odometry_publisher_gid":ODOM_GID})
    with pytest.raises(Exception,match="Parameter evidence incomplete"):
        life.record_passive_phase(owner,"PARAMETERS_READ",{"ros_values":{"GUID_TIMEOUT":1.0},
            "mavlink_values":{"GUID_TIMEOUT":1.0},"parameter_write_count":0})
    assert life._read_passive_session(owner)["phase_journal"]["receipts"][-1]["phase"]=="MOTION_BINDING_V2"
    life.run_lifecycle("stop",gui=False,profile="rover_only",passive_session_owner=owner)
    assert calls==["start","stop"]


@pytest.mark.parametrize("mutate",[
    lambda rows: [row.update(status_publisher_gid="c"*48) for row in rows],
    lambda rows: [row["worker_telemetry_age_s"].update(odometry=2.0) for row in rows],
    lambda rows: [row["position"].update(x=i*0.002) for i,row in enumerate(rows)],
],ids=["wrong-gid","stale-odometry","excessive-drift"])
def test_runtime_stationarity_rejects_bad_observation_evidence(monkeypatch,tmp_path,mutate):
    import pytest
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    setup(monkeypatch,tmp_path)
    assert start((p,scope,digest,authorization),authorization)["status"]=="SUCCESS"
    owner=scope["session_id"]
    capture_digest=_advance_to_observations(owner,scope,observation_mutation=mutate)
    with pytest.raises(Exception,match="Observation analysis failed"):
        life.record_passive_phase(owner,"OBSERVATIONS_VALIDATED",{"capture_sha256":capture_digest})
    result=life.run_lifecycle("stop",gui=False,profile="rover_only",passive_session_owner=owner)
    assert result["status"]=="SUCCESS"
    state=json.loads((life.PASSIVE_SESSION_ROOT/(owner+".json")).read_text())
    assert state["state"]=="CLOSED_INCOMPLETE"


def test_stop_timeout_returns_unknown_without_retry_or_forced_cleanup(monkeypatch,tmp_path):
    import time
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    _,_,_,calls=setup(monkeypatch,tmp_path)
    monkeypatch.setattr(life,"PASSIVE_STOP_CONFIRMATION_WAIT_S",0.03)
    original=life._backend
    stop_entered=__import__("threading").Event()
    def delayed_backend(action,gui,descriptor,process,log_path):
        if action=="stop":
            stop_entered.set()
            time.sleep(0.15)
        return original(action,gui,descriptor,process,log_path)
    monkeypatch.setattr(life,"_backend",delayed_backend)
    result=life.run_passive_sequence(scope,digest,authorization,phase_operations("host-boot-1"),gui=False)
    assert result["status"]=="UNCONFIRMED"
    assert result["stop"]["status"]=="UNCONFIRMED"
    assert stop_entered.wait(0.2)
    assert calls.count("start")==1
    assert result["movement_authorized"] is False
    time.sleep(0.2)
    assert calls.count("stop")==1


def test_interruption_still_requests_protected_stop_once(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    _,_,_,calls=setup(monkeypatch,tmp_path)
    def interrupted(_ctx):
        raise KeyboardInterrupt()
    ops={"ready":interrupted,"motion_binding":lambda ctx:{},"parameters":lambda ctx:{},
         "open_worker":lambda ctx:{},"observe":lambda ctx:{},"close_worker":lambda ctx:{}}
    import pytest
    with pytest.raises(KeyboardInterrupt):
        life.run_passive_sequence(scope,digest,authorization,ops,gui=False)
    assert calls==["start","stop"]
    state=json.loads((life.PASSIVE_SESSION_ROOT/(scope["session_id"]+".json")).read_text())
    assert state["state"]=="CLOSED_INCOMPLETE"


def test_blocked_worker_observation_is_stopped_and_not_closed_late(monkeypatch,tmp_path):
    import time
    from tools import rover_passive_scope as passive
    monkeypatch.setattr(passive,"MAX_SESSION_DURATION_S",0.15)
    monkeypatch.setattr(life,"PASSIVE_STOP_GUARD_S",0.03)
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    _,_,_,calls=setup(monkeypatch,tmp_path)
    ops=phase_operations("host-boot-1")
    closed=[]
    def blocked_observe(_ctx):
        time.sleep(0.25)
        return {"observation_count":100,"records":[],"commands_sent":0,"movement_authorized":False}
    ops["observe"]=blocked_observe
    ops["close_worker"]=lambda ctx:closed.append(ctx["worker_id"]) or {"worker_id":ctx["worker_id"],"closed":True}
    result=life.run_passive_sequence(scope,digest,authorization,ops,gui=False)
    assert calls==["start","stop"], result
    assert result["session_state"]=="CLOSED_INCOMPLETE"
    assert "WORKER_CLOSE_UNCONFIRMED_AFTER_SUPERVISOR_STOP" in result["failures"]
    assert closed==[]


def test_lost_stop_response_remains_unconfirmed_without_replay(monkeypatch,tmp_path):
    import pytest
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    _,_,_,calls=setup(monkeypatch,tmp_path)
    original=life._backend
    def stop_then_drop_response(action,gui,descriptor,process,log_path):
        result=original(action,gui,descriptor,process,log_path)
        if action=="stop":
            raise ConnectionError("synthetic response lost after stop side effect")
        return result
    monkeypatch.setattr(life,"_backend",stop_then_drop_response)
    result=life.run_passive_sequence(scope,digest,authorization,phase_operations("host-boot-1"),gui=False)
    assert result["status"]=="UNCONFIRMED"
    assert result["stop"]["status"]=="UNCONFIRMED"
    assert calls==["start","stop"]
    state=json.loads((life.PASSIVE_SESSION_ROOT/(scope["session_id"]+".json")).read_text())
    assert state["state"]=="UNCONFIRMED"


def test_late_worker_close_cannot_complete_after_supervisor_stop(monkeypatch,tmp_path):
    import time
    from tools import rover_passive_scope as passive
    monkeypatch.setattr(passive,"MAX_SESSION_DURATION_S",0.15)
    monkeypatch.setattr(life,"PASSIVE_STOP_GUARD_S",0.03)
    now=datetime.now(timezone.utc);p,scope,digest,authorization=scope_auth(now)
    _,_,_,calls=setup(monkeypatch,tmp_path)
    ops=phase_operations("host-boot-1")
    close_returned=[]
    def delayed_close(ctx):
        time.sleep(0.25)
        close_returned.append(ctx["worker_id"])
        return {"worker_id":ctx["worker_id"],"closed":True}
    ops["close_worker"]=delayed_close
    result=life.run_passive_sequence(scope,digest,authorization,ops,gui=False)
    assert calls==["start","stop"]
    assert close_returned==["worker-1"]
    assert result["session_state"]=="CLOSED_INCOMPLETE"
    assert result["status"]=="CLOSED_INCOMPLETE"
