"""Per-vehicle ``.plan`` files and the global mission manifest (tfg.multiagent.mission-manifest/1).

Files of one mission directory (``<out>/<mission_id>/``):
  plans/drone_1.plan, plans/drone_2.plan   ArduCopter (inputs.qgc_plan_export, QGC_PLAN_ARDUCOPTER_V2)
  plans/drone_N.mission.json               the MissionDefinition bytes the H2 executor runs (bound by sha256)
  plans/rover.plan                         ArduRover (inputs.qgc_rover_plan_export, QGC_PLAN_ARDUROVER_V1)
  manifest.json                            vehicles, files, hashes, dependencies, execution order

Immutability: plan files are written once (an existing file with other bytes is an error, never overwritten) and
made read-only. Every later stage (approval, execution gate) re-hashes the bytes on disk; a difference is
PLAN_MODIFIED_AFTER_APPROVAL. Neutral names: drone_01 -> drone_1.plan, rover_01 -> rover.plan (one rover).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

MANIFEST_SCHEMA = "tfg.multiagent.mission-manifest/1"


class WriteOnceError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                      default=str).encode("utf-8")


def digest(value) -> str:
    return sha256_bytes(canonical(value))


def write_once(path: Path, data: bytes, *, read_only: bool = True) -> str:
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise WriteOnceError(f"{path.name} exists with other content: never overwritten")
        return sha256_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    if read_only:
        path.chmod(0o444)
    return sha256_bytes(data)


def write_json_once(path: Path, value, *, read_only: bool = True) -> str:
    return write_once(path, (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                        default=str) + "\n").encode("utf-8"), read_only=read_only)


def write_json(path: Path, value) -> str:
    """Mutable state files (status, results). Never used for plans or the manifest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str)
            + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return sha256_bytes(data)


def plan_filename(vehicle_id: str, role: str, rover_count: int = 1) -> str:
    n = re.search(r"(\d+)$", vehicle_id)
    if role == "rover":
        return "rover.plan" if rover_count == 1 else f"rover_{int(n.group(1)) if n else vehicle_id}.plan"
    return f"drone_{int(n.group(1))}.plan" if n else f"{vehicle_id}.plan"


def plan_header(data: bytes) -> dict:
    plan = json.loads(data)
    m = plan.get("mission") or {}
    return {"firmwareType": m.get("firmwareType"), "vehicleType": m.get("vehicleType"),
            "items": len(m.get("items") or []), "commands": [i.get("command") for i in m.get("items") or []]}


def build_manifest(*, mission_id: str, scenario_id: str, data_kind: str, intent_sha256: str, proposal_sha256: str,
                   entries: list[dict], dependencies: list[dict], execution_order: list[str], created_at: str) -> dict:
    body = {"schema": MANIFEST_SCHEMA, "mission_id": mission_id, "scenario_id": scenario_id, "data_kind": data_kind,
            "created_at": created_at, "intent_sha256": intent_sha256, "proposal_sha256": proposal_sha256,
            "vehicles": entries, "dependencies": dependencies, "execution_order": execution_order,
            "approval": {"required": True, "per_vehicle": True,
                         "note": "a validated manifest is not an approval; an approval is not an execution"}}
    return {**body, "manifest_sha256": digest(body)}


def check_manifest(mission_dir: Path) -> tuple[dict | None, list[str]]:
    """(manifest, problems): the manifest digest and every listed file's bytes are re-checked on disk."""
    mission_dir = Path(mission_dir)
    try:
        manifest = json.loads((mission_dir / "manifest.json").read_bytes())
    except (OSError, ValueError) as exc:
        return None, [f"MANIFEST_UNREADABLE: {exc}"]
    problems = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        problems.append("MANIFEST_SCHEMA")
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if digest(body) != manifest.get("manifest_sha256"):
        problems.append("MANIFEST_MODIFIED: digest does not match its content")
    for v in manifest.get("vehicles") or []:
        for key in ("plan", "mission_json"):
            ref = v.get(key)
            if not ref:
                continue
            path = mission_dir / ref["path"]
            if not path.exists():
                problems.append(f"{v['vehicle_id']}: FILE_MISSING {ref['path']}")
            elif sha256_file(path) != ref["sha256"]:
                problems.append(f"{v['vehicle_id']}: PLAN_MODIFIED_AFTER_VALIDATION {ref['path']}")
    return manifest, problems
