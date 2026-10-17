"""Cooperative v1 exclusion: OS mutex plus a durable, fail-closed reservation.

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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_ROOT = PROJECT_ROOT / "missions/generated/vehicle_locks"
_owner = ContextVar("v1_execution_owner", default=None)


@dataclass
class _ExecutionAuthority:
    owner_id: str
    pid: int
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
            raise VehicleBusy("Another v1 execution owns the OS mutex") from exc
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def restriction():
    path = LOCK_ROOT / "v1.json"
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def reserve(owner_id: str, actor: str):
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = restriction()
        if current is not None:
            raise VehicleBusy(f"v1 restricted by {current['owner_id']}; no automatic release or retry")
        atomic_json(LOCK_ROOT / "v1.json", {
            "owner_id": owner_id, "actor": actor, "state": "RESERVED",
            "created_at": utc_now(), "process": process_identity(),
        })


def mark_uncertain(owner_id: str):
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = restriction()
        if current and current["owner_id"] == owner_id:
            atomic_json(LOCK_ROOT / "v1.json", {**current, "state": "UNCONFIRMED", "updated_at": utc_now()})


def release(owner_id: str):
    # Only callers with positive no-flight/landing evidence may call this.
    with file_mutex(LOCK_ROOT / "registry.lock"):
        current = restriction()
        if current is None or current["owner_id"] != owner_id:
            raise VehicleBusy("Reservation owner changed; refusing release")
        (LOCK_ROOT / "v1.json").unlink()


@contextmanager
def execution_scope(owner_id: str):
    with file_mutex(LOCK_ROOT / "v1.execution.lock", blocking=False):
        with file_mutex(LOCK_ROOT / "registry.lock"):
            current = restriction()
            if not current or current["owner_id"] != owner_id:
                raise VehicleBusy("Missing or different v1 reservation")
            atomic_json(LOCK_ROOT / "v1.json", {
                **current, "state": "EXECUTING", "process": process_identity(), "updated_at": utc_now(),
            })
        authority = _ExecutionAuthority(owner_id, os.getpid())
        token = _owner.set(authority)
        try:
            yield
        finally:
            # Copied Context objects share this revocable authority. Wait for an
            # already borrowed executor call before dropping the actual OS lock.
            with authority.call_lock:
                authority.active = False
            _owner.reset(token)


def safe_executor_exit(raw):
    if not isinstance(raw, dict):
        return False
    if (raw.get("status") == "BLOCKED" and raw.get("success") is False
            and raw.get("stage") in {"EXECUTION_GATE", "EXECUTION_COMPATIBILITY"}
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


def serialized_v1(fn):
    @wraps(fn)
    def wrapped(mission_path, *, vehicle="v1", progress=True):
        if vehicle != "v1":
            return fn(mission_path, vehicle=vehicle, progress=progress)
        def blocked(message):
            return {"success": False, "status": "BLOCKED", "stage": "VEHICLE_EXCLUSION",
                    "vehicle": "v1", "message": message}

        def invoke(authority):
            if not authority.call_lock.acquire(blocking=False):
                return blocked("An executor call already uses this v1 authority")
            try:
                current = restriction()
                if (not authority.active or authority.pid != os.getpid() or not current
                        or current.get("owner_id") != authority.owner_id
                        or current.get("state") != "EXECUTING"
                        or current.get("process") != process_identity()):
                    return blocked("Expired or unconfirmed v1 execution authority")
                return fn(mission_path, vehicle=vehicle, progress=progress)
            finally:
                authority.call_lock.release()

        active = _owner.get()
        if active is not None:
            return invoke(active)
        owner_id = str(uuid4())
        try:
            reserve(owner_id, "synchronous_executor")
        except VehicleBusy as exc:
            return {"success": False, "status": "BLOCKED", "stage": "VEHICLE_EXCLUSION",
                    "vehicle": "v1", "message": str(exc)}
        try:
            with execution_scope(owner_id):
                raw = invoke(_owner.get())
            if safe_executor_exit(raw):
                release(owner_id)
            else:
                mark_uncertain(owner_id)
            return raw
        except BaseException:
            mark_uncertain(owner_id)
            raise
    return wrapped
