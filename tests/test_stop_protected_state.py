"""STOP admission against every way a protected-session source can be read: the central criterion.

An ordinary STOP is admitted only when every protected-session source (passive session registry, diagnostic session
record, lock records) was read completely and shows no open session; a directed STOP additionally needs a compatible
owner and identity. Every UNKNOWN, INVALID or ambiguous read is refused before a lease or a backend call.

Each refused case checks: status BLOCKED, zero backend calls, zero subprocesses, zero signals and no change to the
protected records (no lease or operation directory created either). The legitimate cases check that an ordinary STOP
still runs when no protected session exists. Doubles only: no Docker, container, process or signal; every record
lives in a temporary directory. Reproduces the review's counterexamples (null diagnostic record, unlistable passive
registry)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid

import pytest

from tools import simulation_lifecycle as life, vehicle_execution_lock as locks
from tools.rover_xrce_trace import selection
from tests.test_stop_close_modes import DESCRIPTOR, EXECUTION, world  # noqa: F401  (world: recorded doubles)

ROOT_USER = os.geteuid() == 0


@pytest.fixture
def guarded(world, monkeypatch):  # noqa: F811
    """``world`` plus signal doubles that fail the test, and a snapshot of the protected records."""
    def no_signal(*args):
        pytest.fail(f"signal sent: {args}")
    monkeypatch.setattr(os, "kill", no_signal)
    monkeypatch.setattr(os, "killpg", no_signal)

    def snapshot():
        found = {}
        for base in (world.root / "passive", world.target, locks.LOCK_ROOT):
            if not os.path.lexists(base):
                continue
            paths = [base] if not base.is_dir() or base.is_symlink() else [base, *sorted(base.rglob("*"))]
            if base == locks.LOCK_ROOT and not base.is_symlink():
                paths = paths[1:]  # the lock directory itself is created by the lifecycle mutex; its records count
            for path in paths:
                if path.name.endswith(".lock"):
                    continue  # mutex files are created by the lifecycle's own exclusion, not protected state
                st = os.lstat(path)
                content = os.readlink(path) if path.is_symlink() else (
                    path.read_bytes() if path.is_file() and os.access(path, os.R_OK) else None)
                found[str(path)] = (st.st_mode, st.st_mtime_ns, content)
        return found
    world.snapshot = snapshot
    return world


def refused(world, before, result):
    assert result["status"] == "BLOCKED", result
    assert world.calls["backend"] == [] and world.calls["subprocess"] == []
    assert world.snapshot() == before
    assert not os.path.lexists(locks.LOCK_ROOT / "lifecycle.json")
    assert not os.path.lexists(world.root / "simulation_lifecycle")


def write_target(world, raw: str):
    world.target.write_text(raw)


def passive_registry(world):
    registry = world.root / "passive"
    registry.mkdir(exist_ok=True)
    return registry


def passive_record(world, state="STARTED", **extra):
    owner = str(uuid.uuid4())
    path = passive_registry(world) / (owner + ".json")
    path.write_text(json.dumps({"schema": "tfg.rover.passive-session-state/1", "session_id": owner, "state": state,
                                **extra}))
    return owner, path


# ------------------------------------------------------- the two counterexamples --
def test_null_diagnostic_record_is_not_an_absent_session(guarded):
    """Counterexample A: a record containing JSON null was read as no diagnostic session and an ordinary STOP
    without descriptor or boot reached the backend."""
    write_target(guarded, "null\n")
    before = guarded.snapshot()
    result = life.run_lifecycle("stop", gui=False, profile="two_drones_rover")
    refused(guarded, before, result)
    assert "PROTECTED_STATE_UNKNOWN diagnostic session" in result["message"]


def test_unlistable_passive_registry_is_not_an_empty_one(guarded, monkeypatch):
    """Counterexample B: Path.glob suppressed PermissionError, the STARTED session was not seen and an ordinary STOP
    of another profile reached the backend."""
    _, record = passive_record(guarded)
    registry = record.parent
    original = os.scandir

    def denied(path):
        if Path(path) == registry:
            raise PermissionError("fixture: cannot list the passive registry")
        return original(path)
    monkeypatch.setattr(os, "scandir", denied)
    before = guarded.snapshot()
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    refused(guarded, before, result)
    assert "passive session registry" in result["message"] and "cannot be listed" in result["message"]


# ------------------------------------------------- diagnostic record matrix --
@pytest.mark.parametrize("raw", [
    "null", "[]", '"STARTED"', "0", "true", "{}", "", "{not json",
    json.dumps({"state": "STARTED"}),                                        # incomplete: no descriptor
    json.dumps({"state": "STARTED", "descriptor": None}),
    json.dumps({"state": "STARTED", "descriptor": []}),
    json.dumps({"state": "SOMETHING", "descriptor": DESCRIPTOR}),            # unknown state
    json.dumps({"descriptor": DESCRIPTOR}),                                  # no state
], ids=["null", "list", "string", "number", "bool", "empty-object", "empty-file", "invalid-json", "no-descriptor",
        "null-descriptor", "list-descriptor", "unknown-state", "no-state"])
@pytest.mark.parametrize("profile", ["two_drones", "two_drones_rover"])
def test_invalid_diagnostic_record_blocks_every_stop(guarded, raw, profile):
    write_target(guarded, raw)
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile=profile))


def test_diagnostic_descriptor_that_fails_its_check_blocks(guarded, monkeypatch):
    write_target(guarded, json.dumps({"state": "STARTED", "descriptor": DESCRIPTOR,
                                      "environment_execution": EXECUTION}))
    monkeypatch.setattr(selection, "check_frozen_descriptor",
                        lambda d: (_ for _ in ()).throw(ValueError("frozen descriptor differs")))
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile="two_drones_rover"))


@pytest.mark.parametrize("kind", ["link_to_valid", "dangling_link", "directory", "fifo", "unreadable"])
def test_diagnostic_record_that_is_not_a_readable_regular_file_blocks(guarded, kind):
    valid = json.dumps({"state": "CLOSED", "descriptor": DESCRIPTOR})
    if kind == "link_to_valid":
        (guarded.root / "elsewhere.json").write_text(valid)
        guarded.target.symlink_to(guarded.root / "elsewhere.json")
    elif kind == "dangling_link":
        guarded.target.symlink_to(guarded.root / "gone.json")
    elif kind == "directory":
        guarded.target.mkdir()
    elif kind == "fifo":
        os.mkfifo(guarded.target)  # must be refused by type, never opened (opening would block)
    else:
        if ROOT_USER:
            pytest.skip("permission bits do not restrict root")
        write_target(guarded, valid)
        guarded.target.chmod(0)
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile="two_drones"))


def test_diagnostic_record_replaced_while_read_blocks(guarded, monkeypatch):
    write_target(guarded, json.dumps({"state": "CLOSED", "descriptor": DESCRIPTOR}))
    original = os.lstat
    seen = []

    def lstat(path, *a, **k):
        st = original(path, *a, **k)
        if Path(path) == guarded.target:
            seen.append(1)
            if len(seen) == 2:  # the re-check after reading sees another inode
                return os.stat_result((st.st_mode, st.st_ino + 1, *tuple(st)[2:]))
        return st
    monkeypatch.setattr(os, "lstat", lstat)
    before_target = guarded.target.read_bytes()
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["status"] == "BLOCKED" and "changed while being read" in result["message"]
    assert guarded.calls["backend"] == [] and guarded.calls["subprocess"] == []
    assert guarded.target.read_bytes() == before_target


# ---------------------------------------------------- passive registry matrix --
@pytest.mark.parametrize("kind", ["dangling_link", "link_to_directory", "file", "unreadable", "unlistable"])
def test_passive_registry_that_cannot_be_shown_empty_blocks(guarded, kind):
    registry = guarded.root / "passive"
    if kind == "dangling_link":
        registry.symlink_to(guarded.root / "gone", target_is_directory=True)
    elif kind == "link_to_directory":
        (guarded.root / "real").mkdir()
        registry.symlink_to(guarded.root / "real", target_is_directory=True)
    elif kind == "file":
        registry.write_text("")
    else:
        if ROOT_USER:
            pytest.skip("permission bits do not restrict root")
        passive_record(guarded)
        registry.chmod(0o300 if kind == "unreadable" else 0)
    try:
        before = guarded.snapshot() if kind not in ("unreadable", "unlistable") else None
        result = life.run_lifecycle("stop", gui=False, profile="two_drones")
        assert result["status"] == "BLOCKED" and guarded.calls["backend"] == [] and guarded.calls["subprocess"] == []
        if before is not None:
            assert guarded.snapshot() == before
    finally:
        if registry.is_dir() and not registry.is_symlink():
            registry.chmod(0o700)


@pytest.mark.parametrize("raw", ["null", "[]", '"STARTED"', "{}", "", "{not json"],
                         ids=["null", "list", "string", "empty-object", "empty-file", "invalid-json"])
def test_invalid_passive_record_blocks(guarded, raw):
    owner = str(uuid.uuid4())
    (passive_registry(guarded) / (owner + ".json")).write_text(raw)
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile="two_drones"))


@pytest.mark.parametrize("change", ["schema", "session_id", "state"])
def test_inconsistent_passive_record_blocks(guarded, change):
    owner, path = passive_record(guarded, state="CLOSED")
    value = json.loads(path.read_text())
    value.update({"schema": "other/1"} if change == "schema" else
                 {"session_id": str(uuid.uuid4())} if change == "session_id" else {"state": "MAYBE"})
    path.write_text(json.dumps(value))
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile="two_drones"))


@pytest.mark.parametrize("name", ["notes.txt", "ABCDEF.json", "{u}.json.0123abcd.tmp", "{U}.json"],
                         ids=["foreign-file", "non-uuid", "interrupted-write", "non-canonical-uuid"])
def test_unexpected_entry_in_passive_registry_blocks(guarded, name):
    u = str(uuid.uuid4())
    (passive_registry(guarded) / name.format(u=u, U=u.upper())).write_text("{}")
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile="two_drones"))


@pytest.mark.parametrize("kind", ["link", "directory"])
def test_passive_record_that_is_not_a_regular_file_blocks(guarded, kind):
    owner_path = passive_registry(guarded) / (str(uuid.uuid4()) + ".json")
    if kind == "link":
        owner_path.symlink_to(guarded.root / "gone.json")
    else:
        owner_path.mkdir()
    before = guarded.snapshot()
    refused(guarded, before, life.run_lifecycle("stop", gui=False, profile="two_drones"))


def test_passive_registry_changing_while_listed_blocks(guarded, monkeypatch):
    registry = passive_registry(guarded)
    original = os.scandir

    def racing(path):
        iterator = original(path)
        if Path(path) == registry:
            (registry / (str(uuid.uuid4()) + ".json")).write_text("{}")  # a session appears during the listing
        return iterator
    monkeypatch.setattr(os, "scandir", racing)
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["status"] == "BLOCKED" and guarded.calls["backend"] == [] and guarded.calls["subprocess"] == []


# -------------------------------------------------------- lock records --
@pytest.mark.parametrize("name", ["lifecycle.json", "reconciliation.json", "sequence.json", "v1.json", "v3.json"])
@pytest.mark.parametrize("kind", ["dangling_link", "link_to_valid", "directory"])
def test_lock_record_that_is_not_a_regular_file_blocks(guarded, name, kind):
    """A dangling link was read by the lock module as an absent reservation."""
    locks.LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    path = locks.LOCK_ROOT / name
    if kind == "dangling_link":
        path.symlink_to(guarded.root / "gone.json")
    elif kind == "link_to_valid":
        (guarded.root / "valid.json").write_text(json.dumps({"owner_id": "x", "state": "RESERVED"}))
        path.symlink_to(guarded.root / "valid.json")
    else:
        path.mkdir()
    before = guarded.snapshot()
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["status"] == "BLOCKED" and guarded.calls["backend"] == [] and guarded.calls["subprocess"] == []
    assert guarded.snapshot() == before


@pytest.mark.parametrize("which", ["lock_root", "state_root"])
def test_linked_lock_or_state_root_blocks(guarded, monkeypatch, which):
    real = guarded.root / "real-dir"
    real.mkdir()
    link = guarded.root / "linked-dir"
    link.symlink_to(real, target_is_directory=True)
    if which == "lock_root":
        monkeypatch.setattr(locks, "LOCK_ROOT", link)
    else:
        (real / "locks").mkdir()
        monkeypatch.setattr(locks, "LOCK_ROOT", link / "locks")
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["status"] == "BLOCKED" and "symbolic link" in result["message"]
    assert guarded.calls["backend"] == [] and guarded.calls["subprocess"] == []


# ------------------------------------------------- other directed reads --
def test_unreadable_host_process_is_unknown_not_absent(monkeypatch):
    original = Path.read_bytes

    def read_bytes(self):
        if self.name == "cmdline" and self.parent.name == "1":
            raise PermissionError("fixture: hidden process")
        return original(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(life.ProtectedStateUnknown, match="host process 1"):
        life.host_role_processes()


@pytest.mark.parametrize("raw", ["null", "[]", "{not json"])
def test_unreadable_completed_close_record_is_unknown(world, raw):  # noqa: F811
    record = world.root / "simulation_lifecycle" / str(uuid.uuid4()) / "operation.json"
    record.parent.mkdir(parents=True)
    record.write_text(raw)
    with pytest.raises(life.ProtectedStateUnknown):
        life.completed_start_close(str(uuid.uuid4()))


# ------------------------------------------------------ legitimate states --
@pytest.mark.parametrize("state", ["no_sources", "empty_registry", "closed_sessions", "closed_diagnostic"])
def test_ordinary_stop_runs_when_no_protected_session_exists(guarded, state):
    if state == "empty_registry":
        passive_registry(guarded)
    elif state == "closed_sessions":
        passive_record(guarded, state="CLOSED")
        passive_record(guarded, state="CLOSED_INCOMPLETE")
    elif state == "closed_diagnostic":
        write_target(guarded, json.dumps({"state": "CLOSED", "descriptor": DESCRIPTOR}))
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["success"], result
    (child,) = guarded.calls["subprocess"]
    assert not any(k in child["env"] for k in ("TFG_DIAGNOSTIC_CLOSE_TARGET", "TFG_DIAGNOSTIC_CLOSE_BOOT_ID",
                                               "TFG_PASSIVE_SESSION_ID", "TFG_PASSIVE_SESSION_BOOT_ID"))


def test_protected_state_reader_reports_the_sources_it_read(guarded):
    passive_record(guarded, state="CLOSED")
    open_owner, _ = passive_record(guarded, state="STARTED")
    write_target(guarded, json.dumps({"state": "CLOSED", "descriptor": DESCRIPTOR}))
    locks.LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    state = life.protected_session_state()
    assert [s["session_id"] for s in state["passive_open"]] == [open_owner]
    assert state["diagnostic"]["state"] == "CLOSED"
