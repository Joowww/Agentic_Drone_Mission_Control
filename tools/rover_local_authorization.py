"""Offline reference backend for a future separately-owned rover approval helper.

This module is deliberately not an operational identity provider. Fixture principals
are always labelled TEST_FIXTURE and the verifier refuses them in production mode.
The JSON ledger is atomically updated and hash-chained for corruption/replay
-detection, but hashes are not signatures and do not resist a same-UID attacker.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

SCHEMA = "tfg.rover.local-authorization-ledger/1"
TOKEN_SCHEMA = "tfg.rover.local-authorization/1"
FIXTURE = "TEST_FIXTURE"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Principal:
    principal_id: str
    uid: int
    pid: int
    process_start_ticks: int
    evidence_source: str

    def valid(self):
        return (isinstance(self.principal_id, str) and bool(self.principal_id)
                and type(self.uid) is int and self.uid >= 0
                and type(self.pid) is int and self.pid > 0
                and type(self.process_start_ticks) is int and self.process_start_ticks > 0
                and self.evidence_source in {FIXTURE, "LOCAL_HELPER_PEERCRED"})


class AuthorizationError(ValueError):
    pass


class JsonLedger:
    """Single-host atomic ledger. flock serializes processes; hash chain is not auth."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read(self):
        if not self.path.exists():
            return {"schema": SCHEMA, "revision": 0, "head": None, "records": []}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorizationError("LEDGER_UNREADABLE") from exc
        self.validate(data)
        return data

    @staticmethod
    def validate(data):
        if not isinstance(data, dict) or set(data) != {"schema", "revision", "head", "records"}:
            raise AuthorizationError("LEDGER_SHAPE_INVALID")
        if data["schema"] != SCHEMA or type(data["revision"]) is not int or data["revision"] < 0 or not isinstance(data["records"], list):
            raise AuthorizationError("LEDGER_SCHEMA_INVALID")
        prev = None
        seen = set()
        for row in data["records"]:
            if not isinstance(row, dict) or set(row) != {"event", "previous", "event_sha256"}:
                raise AuthorizationError("LEDGER_RECORD_INVALID")
            if row["previous"] != prev or digest(row["event"]) != row["event_sha256"]:
                raise AuthorizationError("LEDGER_CHAIN_INVALID")
            rid = row["event"].get("authorization_id")
            if rid in seen:
                # Multiple append-only events per authorization are expected.
                pass
            seen.add(rid)
            prev = row["event_sha256"]
        if data["head"] != prev or data["revision"] != len(data["records"]):
            raise AuthorizationError("LEDGER_HEAD_INVALID")

    def append(self, event):
        with self.locked():
            data = self.read()
            row = {"event": event, "previous": data["head"], "event_sha256": digest(event)}
            data["records"].append(row)
            data["revision"] += 1
            data["head"] = row["event_sha256"]
            encoded = (canonical(data) + "\n").encode()
            fd, tmp = tempfile.mkstemp(prefix=".rover-auth-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(encoded)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
                dfd = os.open(self.path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return data


class LocalAuthorizationProvider:
    """Issue/consume/revoke exact-scope grants; fixture mode is offline only."""
    def __init__(self, ledger, *, fixture_mode=False, clock=None):
        self.ledger = JsonLedger(ledger)
        self.fixture_mode = fixture_mode
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def issue_fixture(self, principal, binding, *, valid_for_s=60):
        if not self.fixture_mode:
            raise AuthorizationError("FIXTURE_BACKEND_FORBIDDEN_IN_PRODUCTION")
        if not isinstance(principal, Principal) or not principal.valid() or principal.evidence_source != FIXTURE:
            raise AuthorizationError("FIXTURE_PRINCIPAL_INVALID")
        self._binding(binding)
        if type(valid_for_s) not in (int, float) or not 0 < valid_for_s <= 300:
            raise AuthorizationError("AUTHORIZATION_TTL_INVALID")
        now = self.clock().astimezone(timezone.utc)
        record = {"schema": TOKEN_SCHEMA, "authorization_id": str(uuid.uuid4()),
                  "principal": principal.__dict__, "principal_status": FIXTURE,
                  "binding": binding, "issued_at_utc": now.isoformat(),
                  "expires_at_utc": (now + timedelta(seconds=valid_for_s)).isoformat(),
                  "state": "ACTIVE", "single_use": True}
        self.ledger.append({"type": "ISSUED", "authorization_id": record["authorization_id"],
                            "record": record, "at_utc": now.isoformat()})
        return record

    def consume(self, authorization, principal, expected_binding):
        self._require_offline_fixture_backend(principal)
        return self._transition("CONSUMED", authorization, principal, expected_binding)

    def revoke(self, authorization_id, principal):
        self._require_offline_fixture_backend(principal)
        if not isinstance(principal, Principal) or not principal.valid():
            raise AuthorizationError("PRINCIPAL_UNVERIFIED")
        with self.ledger.locked():
            data = self.ledger.read()
            record = self._latest(data, authorization_id)
            if record is None or record["state"] != "ACTIVE":
                raise AuthorizationError("AUTHORIZATION_NOT_ACTIVE")
            if record["principal"] != principal.__dict__:
                raise AuthorizationError("PRINCIPAL_MISMATCH")
            event = {"type": "REVOKED", "authorization_id": authorization_id,
                     "principal": principal.__dict__, "at_utc": self.clock().astimezone(timezone.utc).isoformat()}
            # Append under the same lock without re-entering flock.
            self._append_locked(data, event)
            return "REVOKED"

    def _require_offline_fixture_backend(self, principal):
        # A string such as LOCAL_HELPER_PEERCRED is caller-controlled data here.
        # This module has no authenticated IPC channel, so it must never be used
        # as a production helper/provider, even when the fixture switch is false.
        if not self.fixture_mode:
            raise AuthorizationError("OFFLINE_BACKEND_FORBIDDEN_IN_PRODUCTION")
        if not isinstance(principal, Principal) or not principal.valid():
            raise AuthorizationError("PRINCIPAL_UNVERIFIED")
        if principal.evidence_source != FIXTURE:
            raise AuthorizationError("FIXTURE_PRINCIPAL_REQUIRED")

    def _transition(self, target, authorization, principal, expected_binding):
        if not isinstance(authorization, dict) or authorization.get("schema") != TOKEN_SCHEMA:
            raise AuthorizationError("AUTHORIZATION_MALFORMED")
        if not isinstance(principal, Principal) or not principal.valid():
            raise AuthorizationError("PRINCIPAL_UNVERIFIED")
        self._binding(expected_binding)
        if authorization.get("principal_status") == FIXTURE and not self.fixture_mode:
            raise AuthorizationError("FIXTURE_AUTHORIZATION_FORBIDDEN_IN_PRODUCTION")
        with self.ledger.locked():
            data = self.ledger.read()
            current = self._latest(data, authorization.get("authorization_id"))
            if current is None:
                raise AuthorizationError("AUTHORIZATION_NOT_IN_LEDGER")
            if current["state"] != "ACTIVE":
                raise AuthorizationError("AUTHORIZATION_NOT_ACTIVE")
            if current != authorization:
                raise AuthorizationError("AUTHORIZATION_NOT_IN_LEDGER")
            if current["principal"] != principal.__dict__:
                raise AuthorizationError("PRINCIPAL_MISMATCH")
            if current["binding"] != expected_binding:
                raise AuthorizationError("AUTHORIZATION_BINDING_MISMATCH")
            expiry = utc(current.get("expires_at_utc"))
            now = self.clock().astimezone(timezone.utc)
            if expiry is None or expiry <= now:
                raise AuthorizationError("AUTHORIZATION_EXPIRED")
            changed = dict(current, state=target, consumed_at_utc=now.isoformat())
            self._append_locked(data, {"type": target, "authorization_id": current["authorization_id"],
                                       "record": changed, "at_utc": now.isoformat()})
            return changed

    @staticmethod
    def _binding(binding):
        required = {"scope_sha256", "session_id", "owner_id", "vehicle_id", "profile", "operations",
                    "host_boot_id", "container_boot_id", "environment_sha256"}
        if not isinstance(binding, dict) or set(binding) != required:
            raise AuthorizationError("AUTHORIZATION_BINDING_FIELDS_INVALID")
        for key in required - {"operations"}:
            if not isinstance(binding[key], str) or not binding[key]:
                raise AuthorizationError("AUTHORIZATION_BINDING_INVALID:" + key)
        if not isinstance(binding["operations"], list) or not binding["operations"] or any(not isinstance(x, str) or not x for x in binding["operations"]):
            raise AuthorizationError("AUTHORIZATION_OPERATIONS_INVALID")

    @staticmethod
    def _latest(data, authorization_id):
        found = None
        for row in data["records"]:
            event = row["event"]
            if event.get("authorization_id") != authorization_id:
                continue
            if event["type"] == "ISSUED":
                found = event["record"]
            elif event["type"] in {"CONSUMED", "REVOKED"}:
                found = event["record"] if "record" in event else dict(found or {}, state=event["type"])
        return found

    def _append_locked(self, data, event):
        row = {"event": event, "previous": data["head"], "event_sha256": digest(event)}
        data["records"].append(row)
        data["revision"] += 1
        data["head"] = row["event_sha256"]
        encoded = (canonical(data) + "\n").encode()
        fd, tmp = tempfile.mkstemp(prefix=".rover-auth-", dir=self.ledger.path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encoded); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.ledger.path)
            dfd=os.open(self.ledger.path.parent, os.O_DIRECTORY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
