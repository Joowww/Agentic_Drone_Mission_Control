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
import hashlib
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
    mission_sha256: str | None = None
    consumed: bool = False
    executing: bool = False


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
    sequence = sequence_restriction()
    if records and sequence:
        record = records[0]
        active = sequence.get("active_child")
        if (not isinstance(active, dict) or record.get("sequence_id") != sequence["owner_id"]
                or any(record.get(k) != active.get(k) for k in ("owner_id", "vehicle", "input_sha256"))):
            raise VehicleBusy("Sequence/child reservations disagree; no automatic release")
    elif records and records[0].get("sequence_id"):
        raise VehicleBusy("Child reservation without its sequence guard")
    return records[0] if records else sequence


def sequence_restriction():
    """Persistent outer guard; absence of a child never makes the slot free."""
    try:
        value = json.loads((LOCK_ROOT / "sequence.json").read_text())
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        raise VehicleBusy("Unreadable sequence guard") from exc
    if (not isinstance(value, dict) or value.get("kind") != "PREFLIGHT_SEQUENCE"
            or not isinstance(value.get("owner_id"), str) or not value["owner_id"]
            or value.get("state") not in {"RESERVED", "EXECUTING", "UNCONFIRMED"}
            or not isinstance(value.get("children"), list) or len(value["children"]) != 2
            or type(value.get("next_index")) is not int
            or type(value.get("completed_count")) is not int
            or not 0 <= value["completed_count"] <= value["next_index"] <= 2):
        raise VehicleBusy("Malformed sequence guard; no automatic release")
    if (not all(isinstance(c, dict) and isinstance(c.get("owner_id"), str)
                and c.get("vehicle") in ("v1", "v2") and isinstance(c.get("input_sha256"), str)
                for c in value["children"])
            or {c["vehicle"] for c in value["children"]} != {"v1", "v2"}
            or len({c["owner_id"] for c in value["children"]}) != 2
            or not isinstance(value.get("plan_sha256"), str)):
        raise VehicleBusy("Malformed sequence child bindings")
    return value


def reserve_sequence(owner_id, plan_sha256, children):
    with file_mutex(LOCK_ROOT / "registry.lock"):
        if restriction() is not None:
            raise VehicleBusy("Global flight slot is reserved")
        atomic_json(LOCK_ROOT / "sequence.json", {
            "kind": "PREFLIGHT_SEQUENCE", "owner_id": owner_id, "actor": "sequential_preflight",
            "state": "RESERVED", "plan_sha256": plan_sha256, "children": children,
            "next_index": 0, "completed_count": 0, "active_child": None,
            "created_at": utc_now(), "process": process_identity(), "coordinator": None,
        })


def _sequence_owner(owner_id, plan_sha256):
    current = sequence_restriction()
    if (not current or current["owner_id"] != owner_id or current["plan_sha256"] != plan_sha256
            or current["state"] != "EXECUTING" or current.get("coordinator") != process_identity()):
        raise VehicleBusy("Missing, uncertain or different sequence authority")
    return current


def claim_sequence(owner_id, plan_sha256):
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = sequence_restriction()
        if (not current or current["owner_id"] != owner_id or current["plan_sha256"] != plan_sha256
                or current["state"] != "RESERVED" or current.get("coordinator") is not None):
            raise VehicleBusy("Sequence cannot be claimed twice or resumed")
        atomic_json(LOCK_ROOT / "sequence.json", {
            **current, "state": "EXECUTING", "coordinator": process_identity(), "updated_at": utc_now(),
        })


def reserve_sequence_child(owner_id, plan_sha256, index):
    """Consume one exact slot before granting its ordinary per-vehicle reservation."""
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = _sequence_owner(owner_id, plan_sha256)
        if (current["next_index"] != index or current["completed_count"] != index
                or current["active_child"] is not None
                or any(_restriction(v) is not None for v in ("v1", "v2"))):
            raise VehicleBusy("Child is out of order, already consumed or previous outcome uncertain")
        child = current["children"][index]
        validate_interface(child["vehicle"])
        atomic_json(LOCK_ROOT / "sequence.json", {
            **current, "next_index": index + 1, "active_child": child, "updated_at": utc_now(),
        })
        atomic_json(LOCK_ROOT / f"{child['vehicle']}.json", {
            **child, "sequence_id": owner_id, "actor": "sequence_child", "state": "RESERVED",
            "vehicle_id": logical_vehicle_for_interface(child["vehicle"]),
            "created_at": utc_now(), "process": process_identity(),
        })


def complete_sequence_child(owner_id, plan_sha256, index):
    # Caller has verified the final report/landing AND normal child release.
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = _sequence_owner(owner_id, plan_sha256)
        if (current["next_index"] != index + 1 or current["completed_count"] != index
                or current["active_child"] != current["children"][index]
                or any(_restriction(v) is not None for v in ("v1", "v2"))):
            raise VehicleBusy("Child completion/reservations are inconsistent")
        atomic_json(LOCK_ROOT / "sequence.json", {
            **current, "completed_count": index + 1, "active_child": None, "updated_at": utc_now(),
        })


def end_sequence(owner_id, plan_sha256, *, uncertain=False, unspawned=False):
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = sequence_restriction()
        if not current or current["owner_id"] != owner_id or current["plan_sha256"] != plan_sha256:
            raise VehicleBusy("Sequence owner changed")
        if uncertain:
            atomic_json(LOCK_ROOT / "sequence.json", {**current, "state": "UNCONFIRMED"})
            return
        if unspawned:
            if current["state"] != "RESERVED" or current.get("coordinator") is not None:
                raise VehicleBusy("Coordinator may have started; cannot discard guard")
        else:
            _sequence_owner(owner_id, plan_sha256)
        if any(_restriction(v) is not None for v in ("v1", "v2")):
            raise VehicleBusy("Child reservation remains; cannot release sequence")
        (LOCK_ROOT / "sequence.json").unlink()


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
        authority = _ExecutionAuthority(owner_id, os.getpid(), vehicle,
                                        mission_sha256=current.get("input_sha256") if current.get("sequence_id") else None)
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
            or current.get("state") != "EXECUTING" or current.get("process") != process_identity()
            or authority.mission_sha256 is not None and not authority.executing):
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
                if authority.mission_sha256 is not None:
                    if authority.consumed:
                        return blocked("Sequence child flight authority is single-use")
                    authority.consumed = True  # consume BEFORE attempting any executor call
                    try:
                        if hashlib.sha256(Path(mission_path).read_bytes()).hexdigest() != authority.mission_sha256:
                            return blocked("Executor input differs from the authorized sequence snapshot")
                    except OSError as exc:
                        return blocked(str(exc))
                    authority.executing = True
                try:
                    assert_execution_authority(vehicle)
                except VehicleBusy as exc:
                    return blocked(str(exc))
                return fn(mission_path, vehicle=vehicle, progress=progress)
            finally:
                authority.executing = False
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
