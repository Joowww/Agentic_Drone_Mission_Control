"""Offline verifier for a single owner-bound passive session phase journal.

It only validates receipts and never opens transports or authorizes controls.
"""
from __future__ import annotations
import hashlib
import json
import math

SCHEMA = "tfg.rover.passive-phase-journal/1"
PHASES = ("START", "READY_ARMABLE", "MOTION_BINDING_V2", "PARAMETERS_READ",
          "WORKER_OPEN", "OBSERVATIONS", "OBSERVATIONS_VALIDATED", "WORKER_CLOSE",
          "STOP", "FINAL_INVENTORY")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def receipt_sha256(receipt):
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def verify(journal, *, now_monotonic_s=None):
    reasons=[]
    if not isinstance(journal, dict) or journal.get("schema") != SCHEMA:
        return {"verdict":"UNCONFIRMED", "reasons":["UNKNOWN_JOURNAL_SCHEMA"], "complete":False}
    ident=journal.get("identity") or {}
    required_identity=("scope_sha256","owner_id","lifecycle_id","host_boot_id","container_boot_id","container_id","vehicle_id")
    if any(not isinstance(ident.get(k),str) or not ident[k] for k in required_identity):
        reasons.append("SESSION_IDENTITY_INCOMPLETE")
    if not isinstance(ident.get("scope_sha256"),str) or len(ident.get("scope_sha256", "")) != 64:
        reasons.append("SCOPE_DIGEST_INVALID")
    deadline=journal.get("deadline") or {}
    start=deadline.get("started_host_monotonic_s"); end=deadline.get("deadline_host_monotonic_s")
    if (not isinstance(start,(int,float)) or isinstance(start,bool) or not math.isfinite(start)
        or not isinstance(end,(int,float)) or isinstance(end,bool) or not math.isfinite(end) or end<=start):
        reasons.append("HOST_MONOTONIC_DEADLINE_INVALID")
    elif now_monotonic_s is not None and (not math.isfinite(now_monotonic_s) or now_monotonic_s > end):
        reasons.append("SESSION_DEADLINE_EXPIRED")
    receipts=journal.get("receipts")
    if not isinstance(receipts,list): receipts=[]; reasons.append("RECEIPTS_MISSING")
    seen=[]; worker_open=False; observation_count=0; stop_seen=False; previous_hash=None; previous_time=None
    for i,r in enumerate(receipts):
        if not isinstance(r,dict): reasons.append("RECEIPT_MALFORMED"); continue
        phase=r.get("phase")
        if phase not in PHASES: reasons.append("UNKNOWN_PHASE"); continue
        if phase in seen: reasons.append("DUPLICATE_PHASE:"+phase); continue
        if len(seen)>=len(PHASES) or PHASES[len(seen)] != phase:
            reasons.append("PHASE_ORDER_INVALID:"+phase)
        seen.append(phase)
        for key in required_identity:
            if r.get(key) != ident.get(key): reasons.append("RECEIPT_IDENTITY_MISMATCH:"+phase+":"+key)
        digest=receipt_sha256(r)
        if r.get("receipt_sha256") != digest: reasons.append("RECEIPT_HASH_MISMATCH:"+phase)
        if r.get("previous_receipt_sha256") != previous_hash: reasons.append("RECEIPT_CHAIN_MISMATCH:"+phase)
        stamp=r.get("timestamp_host_monotonic_s")
        if not isinstance(stamp,(int,float)) or isinstance(stamp,bool) or not math.isfinite(stamp):
            reasons.append("RECEIPT_TIMESTAMP_INVALID:"+phase)
        elif isinstance(end,(int,float)) and stamp > end:
            reasons.append("RECEIPT_AFTER_DEADLINE:"+phase)
        elif previous_time is not None and stamp <= previous_time:
            reasons.append("RECEIPT_TIMESTAMP_NOT_INCREASING:"+phase)
        else: previous_time=stamp
        previous_hash=digest
        if r.get("status") != "CONFIRMED": reasons.append("PHASE_NOT_CONFIRMED:"+phase)
        if r.get("commands_sent") != 0 or r.get("movement_authorized") is not False:
            reasons.append("NONPASSIVE_RECEIPT:"+phase)
        data=r.get("evidence") if isinstance(r.get("evidence"),dict) else r
        op=r.get("operation")
        if phase in PHASES and not isinstance(op,str):
            reasons.append("OPERATION_MISSING:"+phase)
        if phase == "READY_ARMABLE" and (data.get("armed") is not False or data.get("armable") is not True):
            reasons.append("READY_ARMABLE_NOT_CONFIRMED")
        if phase == "MOTION_BINDING_V2" and data.get("binding_schema") != "tfg.rover.motion-binding/2":
            reasons.append("MOTION_BINDING_V2_NOT_CONFIRMED")
        if phase == "PARAMETERS_READ" and data.get("parameter_write_count") != 0:
            reasons.append("PARAMETER_WRITE_DETECTED")
        if phase == "WORKER_OPEN":
            if worker_open: reasons.append("DUPLICATE_WORKER")
            worker_open=True
        if phase == "OBSERVATIONS":
            observation_count=data.get("observation_count")
            if type(observation_count) is not int or observation_count != 100:
                reasons.append("OBSERVATION_COUNT_NOT_EXACTLY_100")
        if phase == "WORKER_CLOSE":
            if not worker_open or data.get("closed") is not True: reasons.append("WORKER_CLOSE_UNCONFIRMED")
            worker_open=False
        if phase == "OBSERVATIONS_VALIDATED" and (data.get("verdict") != "STATIONARY_OBSERVED"
                or data.get("positions_and_velocities_validated") is not True):
            reasons.append("OBSERVATIONS_NOT_VALIDATED")
        if phase == "STOP": stop_seen=True
        if phase == "FINAL_INVENTORY" and not stop_seen: reasons.append("FINAL_INVENTORY_BEFORE_STOP")
    if worker_open: reasons.append("WORKER_STILL_OPEN")
    if seen != list(PHASES): reasons.append("REQUIRED_PHASES_INCOMPLETE")
    return {"schema":"tfg.rover.passive-phase-verification/1",
            "verdict":"COMPLETE_PASSIVE_SESSION" if not reasons else "CLOSED_INCOMPLETE",
            "complete":not reasons,"reasons":reasons,"phases_seen":seen,
            "observations":observation_count,"movement_authorized":False,"commands_sent":0}
