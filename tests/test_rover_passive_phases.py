from copy import deepcopy
from tools.rover_passive_phases import PHASES, SCHEMA, receipt_sha256, verify


def journal():
    identity={"scope_sha256":"a"*64,"owner_id":"owner-1","lifecycle_id":"life-1",
      "host_boot_id":"host-1","container_boot_id":"container-1","container_id":"container-id","vehicle_id":"rover_01"}
    out={"schema":SCHEMA,"identity":identity,
         "deadline":{"started_host_monotonic_s":10.0,"deadline_host_monotonic_s":310.0},"receipts":[]}
    for phase in PHASES:
        r={**identity,"phase":phase,"status":"CONFIRMED","operation":phase.lower(),
           "commands_sent":0,"movement_authorized":False}
        if phase=="READY_ARMABLE": r.update(armed=False,armable=True)
        if phase=="MOTION_BINDING_V2": r["binding_schema"]="tfg.rover.motion-binding/2"
        if phase=="PARAMETERS_READ": r["parameter_write_count"]=0
        if phase=="OBSERVATIONS": r["observation_count"]=100
        if phase=="WORKER_CLOSE": r["closed"]=True
        if phase=="OBSERVATIONS_VALIDATED": r.update(verdict="STATIONARY_OBSERVED",positions_and_velocities_validated=True)
        out["receipts"].append(r)
    previous=None
    for i,r in enumerate(out["receipts"]):
        r["timestamp_host_monotonic_s"]=10.0+i
        r["previous_receipt_sha256"]=previous
        r["receipt_sha256"]=receipt_sha256(r)
        previous=r["receipt_sha256"]
    return out


def test_complete_owner_bound_sequence_is_only_a_passive_completion():
    result=verify(journal(),now_monotonic_s=100.0)
    assert result["complete"] and result["verdict"]=="COMPLETE_PASSIVE_SESSION"
    assert result["commands_sent"]==0 and result["movement_authorized"] is False


def test_missing_or_reordered_receipts_close_incomplete():
    value=journal(); value["receipts"].pop(4)
    assert verify(value)["verdict"]=="CLOSED_INCOMPLETE"
    value=journal(); value["receipts"][0],value["receipts"][1]=value["receipts"][1],value["receipts"][0]
    assert "PHASE_ORDER_INVALID:READY_ARMABLE" in verify(value)["reasons"]


def test_duplicate_worker_identity_replay_and_false_command_claim_fail_closed():
    value=journal(); duplicate=deepcopy(value["receipts"][4]); duplicate["receipt_sha256"]=receipt_sha256(duplicate); value["receipts"].insert(5,duplicate)
    assert any(reason.startswith("DUPLICATE_PHASE:WORKER_OPEN") for reason in verify(value)["reasons"])
    value=journal(); value["receipts"][5]["observation_count"]=99; value["receipts"][5]["receipt_sha256"]=receipt_sha256(value["receipts"][5])
    assert "OBSERVATION_COUNT_NOT_EXACTLY_100" in verify(value)["reasons"]
    value=journal(); value["receipts"][0]["host_boot_id"]="other"; value["receipts"][0]["receipt_sha256"]=receipt_sha256(value["receipts"][0])
    assert "RECEIPT_IDENTITY_MISMATCH:START:host_boot_id" in verify(value)["reasons"]
    value=journal(); value["receipts"][0]["commands_sent"]=1; value["receipts"][0]["receipt_sha256"]=receipt_sha256(value["receipts"][0])
    assert "NONPASSIVE_RECEIPT:START" in verify(value)["reasons"]


def test_expired_host_monotonic_deadline_fails_closed():
    assert "SESSION_DEADLINE_EXPIRED" in verify(journal(),now_monotonic_s=311.0)["reasons"]
