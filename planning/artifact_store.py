"""Small artifact helpers; files next to the mission remain the source of truth."""
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

from tools.vehicle_execution_lock import atomic_json, file_mutex, utc_now


class Conflict(ValueError):
    pass


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())


def identifier(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Expected canonical UUID")
    return value


def child(root, value):
    path = root / identifier(value)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact escapes configured root")
    return path


def read_object(path):
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path.name}")
    return value


def safe_mission_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Unsafe mission_id for export filename")


def request_path(root, key):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", key):
        raise ValueError("Invalid request_key")
    return root / "requests" / (sha256(key.encode()) + ".json")


def prior_request(path, digest):
    if not path.exists():
        return None
    record = read_object(path)
    if record["fingerprint"] != digest:
        raise Conflict("request_key already binds different inputs")
    result = record["result"]
    if not isinstance(result, dict) or result.get("status") not in {"BUILDING", "PROPOSED", "REVISED"}:
        raise ValueError("Invalid persistent request result; never recreate its artifact")
    keys = [key for key in ("proposal_id", "revision_id") if key in result]
    if not keys:
        raise ValueError("Persistent request result lacks artifact identity")
    for key in keys:
        identifier(result[key])
    return result


def save_request(path, digest, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {"fingerprint": digest, "result": result})


def boundary(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Conflict as exc:
            return {"status": "CONFLICT", "errors": [str(exc)]}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return {"status": "ERROR", "errors": [str(exc)]}
    return call


def structured_diff(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for key in sorted(old.keys() | new.keys()):
            result.extend(structured_diff(old.get(key), new.get(key), f"{path}/{key}"))
        return result
    if old == new:
        return []
    return [{"path": path, "before": old, "after": new}]
