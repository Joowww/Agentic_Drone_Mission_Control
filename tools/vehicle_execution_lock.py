"""Per-vehicle durable reservations with ONE project-wide flight authority.

A dead owner never clears its reservation automatically. This is coordination
between repository entry points, not a security boundary against manual ROS.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
from functools import wraps
import json
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from tools.simulated_vehicle import validate_interface, logical_vehicle_for_interface

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_ROOT = PROJECT_ROOT / "missions/generated/vehicle_locks"
_owner = ContextVar("simulated_execution_owner", default=None)


@dataclass
class _ExecutionAuthority:
    owner_id: str
    pid: int
    vehicle: str
    active: bool = True
    call_lock: object = field(default_factory=Lock)


class VehicleBusy(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2, ensure_ascii=False, allow_nan=False)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def process_identity(pid: int | None = None):
    pid = os.getpid() if pid is None else pid
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "start_ticks": int(fields[19]),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def identity_alive(identity):
    return bool(identity) and process_identity(identity["pid"]) == identity


@contextmanager
def file_mutex(path: Path, *, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise VehicleBusy("Another project execution owns the OS mutex") from exc
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def _restriction(vehicle):
    path = LOCK_ROOT / f"{validate_interface(vehicle)}.json"
    try:
        record = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise VehicleBusy(f"Unreadable {vehicle} reservation; no automatic release") from exc
    if (not isinstance(record, dict) or not isinstance(record.get("owner_id"), str)
            or not record["owner_id"] or record.get("state") not in {"RESERVED", "EXECUTING", "UNCONFIRMED"}
            or record.get("vehicle", vehicle) != vehicle
            or record.get("vehicle_id", logical_vehicle_for_interface(vehicle)) != logical_vehicle_for_interface(vehicle)):
        raise VehicleBusy(f"Malformed {vehicle} reservation; no automatic release")
    return record


def restriction(vehicle=None):
    """No argument returns the global blocker; lookup never clears or migrates it."""
    if vehicle is not None:
        return _restriction(vehicle)
    records = [record for v in ("v1", "v2") if (record := _restriction(v)) is not None]
    if len(records) > 1:
        raise VehicleBusy("Conflicting vehicle reservations; operator reconciliation required")
    return records[0] if records else None


def reserve(owner_id: str, actor: str, vehicle="v1"):
    validate_interface(vehicle)
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = restriction()
        if current is not None:
            raise VehicleBusy(f"Global flight restriction held by {current['owner_id']}; no automatic release or retry")
        atomic_json(LOCK_ROOT / f"{vehicle}.json", {
            "owner_id": owner_id, "actor": actor, "state": "RESERVED",
            "vehicle": vehicle,
            "vehicle_id": logical_vehicle_for_interface(vehicle),
            "created_at": utc_now(), "process": process_identity(),
        })


def mark_uncertain(owner_id: str, vehicle="v1"):
    validate_interface(vehicle)
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = restriction(vehicle)
        if current and current["owner_id"] == owner_id:
            atomic_json(LOCK_ROOT / f"{vehicle}.json", {**current, "state": "UNCONFIRMED", "updated_at": utc_now()})


def release(owner_id: str, vehicle="v1"):
    validate_interface(vehicle)
    # Only callers with positive no-flight/landing evidence may call this.
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = restriction()
        if current is None or current["owner_id"] != owner_id or restriction(vehicle) != current:
            raise VehicleBusy("Reservation owner changed; refusing release")
        (LOCK_ROOT / f"{vehicle}.json").unlink()


@contextmanager
def execution_scope(owner_id: str, vehicle="v1"):
    validate_interface(vehicle)
    # Retain the existing file name: this is the GLOBAL OS flight mutex for
    # both interfaces, including old v1 entry points. Never one mutex per drone.
    with file_mutex(LOCK_ROOT / "v1.execution.lock", blocking=False):
        with file_mutex(LOCK_ROOT / "registry.lock"):
            current = restriction()
            if not current or current["owner_id"] != owner_id or restriction(vehicle) != current:
                raise VehicleBusy("Missing or different vehicle reservation")
            atomic_json(LOCK_ROOT / f"{vehicle}.json", {
                **current, "state": "EXECUTING", "process": process_identity(), "updated_at": utc_now(),
            })
        authority = _ExecutionAuthority(owner_id, os.getpid(), vehicle)
        token = _owner.set(authority)
        try:
            yield
        finally:
            # Copied Context objects share this revocable authority. Wait for an
            # already borrowed executor call before dropping the actual OS lock.
            with authority.call_lock:
                authority.active = False
            _owner.reset(token)


def safe_executor_exit(raw, *, selection=None):
    if not isinstance(raw, dict):
        return False
    if selection and (raw.get("vehicle") != selection["simulated_vehicle"]
                      or raw.get("vehicle_id") != selection["vehicle_id"]):
        return False
    if (raw.get("status") == "BLOCKED" and raw.get("success") is False
            and raw.get("stage") in {"EXECUTION_GATE", "EXECUTION_COMPATIBILITY", "VEHICLE_SELECTION"}
            and not raw.get("events") and not raw.get("recovery")):
        return True
    def landed(value):
        return (isinstance(value, dict) and value.get("landed") is True
                and value.get("armed") is False and value.get("flying") is False)
    events = raw.get("events", [])
    if (raw.get("status") == "COMPLETED" and raw.get("success") is True
            and isinstance(events, list) and events and isinstance(events[-1], dict)):
        return events[-1].get("event") == "LANDED" and landed(events[-1])
    recovery = raw.get("recovery")
    return (raw.get("status") == "FAILED" and raw.get("success") is False
            and isinstance(recovery, dict) and recovery.get("landing_completed") is True
            and landed(recovery.get("landing")))


def assert_execution_authority(vehicle):
    """Flight primitives may only borrow the live matching project authority."""
    validate_interface(vehicle)
    authority = _owner.get()
    current = restriction()
    if (authority is None or not authority.active or authority.pid != os.getpid()
            or authority.vehicle != vehicle or current is None
            or current.get("owner_id") != authority.owner_id or restriction(vehicle) != current
            or current.get("state") != "EXECUTING" or current.get("process") != process_identity()):
        raise VehicleBusy("Missing, expired or mismatched global flight authority")


def serialized_execution(fn):
    @wraps(fn)
    def wrapped(mission_path, *, vehicle="v1", progress=True):
        validate_interface(vehicle)
        def blocked(message):
            return {"success": False, "status": "BLOCKED", "stage": "VEHICLE_EXCLUSION",
                    "vehicle": vehicle, "message": message}

        def invoke(authority):
            if not authority.call_lock.acquire(blocking=False):
                return blocked("An executor call already uses this global authority")
            try:
                try:
                    assert_execution_authority(vehicle)
                except VehicleBusy as exc:
                    return blocked(str(exc))
                return fn(mission_path, vehicle=vehicle, progress=progress)
            finally:
                authority.call_lock.release()

        active = _owner.get()
        if active is not None:
            return invoke(active)
        owner_id = str(uuid4())
        try:
            reserve(owner_id, "synchronous_executor", vehicle)
        except VehicleBusy as exc:
            return {"success": False, "status": "BLOCKED", "stage": "VEHICLE_EXCLUSION",
                    "vehicle": vehicle, "message": str(exc)}
        try:
            with execution_scope(owner_id, vehicle):
                raw = invoke(_owner.get())
            if safe_executor_exit(raw, selection={"vehicle_id": logical_vehicle_for_interface(vehicle),
                                                  "simulated_vehicle": vehicle}):
                release(owner_id, vehicle)
            else:
                mark_uncertain(owner_id, vehicle)
            return raw
        except BaseException:
            mark_uncertain(owner_id, vehicle)
            raise
    return wrapped


# Compatibility for Python callers/tests; v2 is now protected too, never skipped.
serialized_v1 = serialized_execution
