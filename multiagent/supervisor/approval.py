"""Per-vehicle plan approval (tfg.multiagent.plan-approval/1): a RECORD bound to one exact plan, never a boolean.

What an operator approves: this mission, this manifest (sha256), this vehicle, this task, this .plan (sha256) and, for
drones, the MissionDefinition bytes the executor runs, within a validity window and an operator session. ``check``
recomputes everything from the manifest and the files on disk; a record for another plan, vehicle, session or
manifest, a tampered record or an expired one is refused.

Sources accepted per mode:
  OFFLINE_TEST   TEST_FIXTURE only (tests, offline flows; can only reach the test-double executor);
  OPERATIONAL    OPERATOR_CLI only (``python -m multiagent.supervisor approve``), NOT AUTHENTICATED. It can at
                 most make a vehicle READY_TO_REQUEST_EXECUTION: the effectful call stays with the protected entry
                 (H2 sequence / rover controller), which keeps its own authorization and preconditions.
A model (Hermes) can never create an approval: the MCP facade exposes no approval tool.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from multiagent.supervisor.plans import digest

SCHEMA = "tfg.multiagent.plan-approval/1"
ACCEPTED_SOURCES = {"OFFLINE_TEST": ("TEST_FIXTURE",), "OPERATIONAL": ("OPERATOR_CLI",)}


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _body(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "approval_id"}


def entry(manifest: dict, vehicle_id: str) -> dict | None:
    return next((v for v in manifest.get("vehicles") or [] if v["vehicle_id"] == vehicle_id), None)


def record(manifest: dict, vehicle_id: str, *, operator_id: str, session_id: str, session_expires_at: datetime,
           at: datetime, valid_for_s: float, statement: str, source: str = "TEST_FIXTURE") -> dict:
    v = entry(manifest, vehicle_id)
    if v is None:
        raise ValueError(f"{vehicle_id} is not in the manifest")
    if v.get("validation") != "PASS":
        raise ValueError(f"{vehicle_id}: only a validated plan can be approved (validation {v.get('validation')})")
    if not statement or not operator_id or not session_id:
        raise ValueError("an approval needs an operator id, a session id and an explicit statement")
    rec = {"schema": SCHEMA, "source": source, "authentication": "NOT_AUTHENTICATED",
           "approved_by": {"role": "HUMAN_OPERATOR", "id": operator_id},
           "mission_id": manifest["mission_id"], "manifest_sha256": manifest["manifest_sha256"],
           "vehicle_id": vehicle_id, "vehicle_class": v["vehicle_class"], "task_id": v["task_id"],
           "plan_sha256": v["plan"]["sha256"],
           "mission_json_sha256": (v.get("mission_json") or {}).get("sha256"),
           "session": {"session_id": session_id, "expires_at_utc": _utc(session_expires_at)},
           "approved_at_utc": _utc(at), "expires_at_utc": _utc(at + timedelta(seconds=valid_for_s)),
           "statement": statement}
    return {**rec, "approval_id": digest(rec)}


def check(rec, manifest: dict, vehicle_id: str, *, now: datetime, mode: str, session_id: str | None,
          plan_sha256_on_disk: str | None, mission_json_sha256_on_disk: str | None = None) -> list[str]:
    """[] only when the record approves exactly this vehicle's plan in this manifest, now, in this session."""
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA:
        return ["NOT_AN_APPROVAL_RECORD: a boolean, a statement or a bare hash is not an approval"]
    if mode not in ACCEPTED_SOURCES:
        return [f"UNKNOWN_MODE: {mode!r}"]
    reasons = []
    if rec.get("approval_id") != digest(_body(rec)):
        reasons.append("TAMPERED: the record does not match its own digest")
    if mode == "OPERATIONAL" and rec.get("source") == "TEST_FIXTURE":
        reasons.append("FIXTURE_APPROVAL_NOT_ACCEPTED_IN_OPERATIONAL_MODE")
    elif rec.get("source") not in ACCEPTED_SOURCES[mode]:
        reasons.append(f"SOURCE_NOT_ACCEPTED: {rec.get('source')!r} in mode {mode}")
    who = rec.get("approved_by") or {}
    if who.get("role") != "HUMAN_OPERATOR" or not who.get("id"):
        reasons.append("NO_IDENTIFIED_HUMAN_OPERATOR")
    v = entry(manifest, vehicle_id)
    if v is None:
        return reasons + [f"VEHICLE_NOT_IN_MANIFEST: {vehicle_id}"]
    expected = {"mission_id": manifest["mission_id"], "manifest_sha256": manifest["manifest_sha256"],
                "vehicle_id": vehicle_id, "vehicle_class": v["vehicle_class"], "task_id": v["task_id"],
                "plan_sha256": v["plan"]["sha256"], "mission_json_sha256": (v.get("mission_json") or {}).get("sha256")}
    for field, value in expected.items():
        if rec.get(field) != value:
            reasons.append(f"{field.upper()}_MISMATCH")
    if plan_sha256_on_disk != v["plan"]["sha256"]:
        reasons.append("PLAN_MODIFIED_AFTER_APPROVAL: the .plan bytes on disk differ from the approved hash")
    if v.get("mission_json") and mission_json_sha256_on_disk != v["mission_json"]["sha256"]:
        reasons.append("MISSION_MODIFIED_AFTER_APPROVAL: the executor mission bytes differ from the approved hash")
    session = rec.get("session") or {}
    if not session_id or session.get("session_id") != session_id:
        reasons.append("SESSION_MISMATCH: the execution request is not in the approving session")
    try:
        if now > datetime.fromisoformat(session["expires_at_utc"]):
            reasons.append("SESSION_EXPIRED")
        start, end = datetime.fromisoformat(rec["approved_at_utc"]), datetime.fromisoformat(rec["expires_at_utc"])
        if not start <= now <= end:
            reasons.append("APPROVAL_OUTSIDE_VALIDITY_WINDOW")
    except (KeyError, TypeError, ValueError):
        reasons.append("VALIDITY_WINDOW_INVALID")
    return reasons
