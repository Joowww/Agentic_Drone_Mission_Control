"""STOP close modes through the public lifecycle entry and the pinned process reader.

PASSIVE, DIAGNOSTIC and ORDINARY are exclusive. A STOP whose owner is unknown, ambiguous or incompatible with an
open or uncertain protected session is refused before any lease, subprocess or signal; a diagnostic close always
carries its exact descriptor and boot, so the pinned reader never falls back to the general project selection.

No Docker, container, process or signal is used: the backend, subprocess, environment readers and process table
are doubles, and every lock and session record lives in a temporary directory. Reproduces the review's
counterexamples (UNSCOPED_STOP, DIAGNOSTIC_STOP, DIAGNOSTIC_READER) and their variants."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from simulation.ros2_gazebo.scripts import sim_processes as cleanup
from tools import reconciliation_environment, simulation_lifecycle as life, vehicle_execution_lock as locks
from tools.rover_xrce_trace import selection
from tests.test_simulation_lifecycle import FakeProcesses, launch

MANIFEST = {"container_id": "c" * 64, "engine_id": "engine", "image_id": "sha256:" + "i" * 64}
DESCRIPTOR = {"manifest": MANIFEST, "lifecycle_id": "fixture-diagnostic", "selection_sha256": "s" * 64}
EXECUTION = {"persistent_identity": {**MANIFEST, "name": "/tfg-ardupilot-gazebo", "created_at": "2026-11-01T00:00:00Z"},
             "container_started_at": "2026-11-01T00:00:01Z", "container_boot_id": "fixture-boot"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Temporary lock and session roots; every backend, subprocess and environment read is recorded."""
    calls = {"backend": [], "subprocess": []}
    monkeypatch.setattr(locks, "LOCK_ROOT", tmp_path / "locks")
    monkeypatch.setattr(life, "PASSIVE_SESSION_ROOT", tmp_path / "passive")
    monkeypatch.setattr(selection, "check_frozen_descriptor", lambda d: d)
    monkeypatch.setattr(reconciliation_environment, "inspect_environment", lambda: {"status": "ACTIVE", **MANIFEST})
    current = {"execution": json.loads(json.dumps(EXECUTION))}

    def read_execution():
        value = current["execution"]
        if isinstance(value, Exception):
            raise value
        return json.loads(json.dumps(value))
    monkeypatch.setattr(reconciliation_environment, "inspect_active_execution", read_execution)

    def run(args, **kwargs):
        calls["subprocess"].append({"args": args, "env": kwargs.get("env", {})})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(life.subprocess, "run", run)
    real_backend = life._backend

    def backend(*args):
        calls["backend"].append(json.loads((locks.LOCK_ROOT / "lifecycle.json").read_text()))
        return real_backend(*args)
    monkeypatch.setattr(life, "_backend", backend)
    target_path = tmp_path / "diagnostic_agent_session.json"
    return SimpleNamespace(root=tmp_path, calls=calls, current=current, target=target_path)


def passive_session(world, state="STARTED"):
    owner = str(uuid.uuid4())
    world.root.joinpath("passive").mkdir(exist_ok=True)
    path = world.root / "passive" / (owner + ".json")
    path.write_text(json.dumps({"schema": "tfg.rover.passive-session-state/1", "session_id": owner, "state": state,
                                "scope_sha256": "x", "environment_execution": EXECUTION}))
    return owner, path


def diagnostic_target(world, state="STARTED", execution=EXECUTION):
    value = {"descriptor": DESCRIPTOR, "state": state, "operation_path": str(world.root / "op.json")}
    if execution is not None:
        value["environment_execution"] = execution
    world.target.write_text(json.dumps(value))
    return value


def nothing_reached(world):
    return world.calls["backend"] == [] and world.calls["subprocess"] == []


# ------------------------------------------------- passive session open --
@pytest.mark.parametrize("profile", ["two_drones", "two_drones_rover"])
@pytest.mark.parametrize("state", ["OPENING", "STARTED", "STOPPING", "UNCONFIRMED"])
def test_stop_of_another_profile_never_reaches_a_protected_passive_session(world, profile, state):
    """Counterexample UNSCOPED_STOP: an ordinary STOP was admitted with a STARTED passive session."""
    _, path = passive_session(world, state)
    before = path.read_bytes()
    result = life.run_lifecycle("stop", gui=False, profile=profile)
    assert result["status"] == "BLOCKED" and "passive rover session" in result["message"]
    assert nothing_reached(world) and path.read_bytes() == before
    assert not (locks.LOCK_ROOT / "lifecycle.json").exists()


@pytest.mark.parametrize("owner_kind", ["close_owner", "ground_owner"])
def test_protected_closes_of_other_owners_are_refused_while_a_passive_session_is_open(world, owner_kind):
    passive_session(world)
    result = life.run_lifecycle("stop", gui=False, profile="two_drones_rover", **{owner_kind: str(uuid.uuid4())})
    assert result["status"] == "BLOCKED" and nothing_reached(world)


@pytest.mark.parametrize("damage", ["dangling_registry", "registry_is_file", "malformed_record", "unknown_state"])
def test_unreadable_passive_state_is_unknown_never_no_session(world, damage):
    registry = world.root / "passive"
    if damage == "dangling_registry":
        registry.symlink_to(world.root / "gone", target_is_directory=True)
    elif damage == "registry_is_file":
        registry.write_text("")
    else:
        registry.mkdir()
        owner = str(uuid.uuid4())
        state = "STARTED" if damage == "malformed_record" else "SOMETHING_ELSE"
        text = "{not json" if damage == "malformed_record" else json.dumps(
            {"schema": "tfg.rover.passive-session-state/1", "session_id": owner, "state": state})
        (registry / (owner + ".json")).write_text(text)
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["status"] == "BLOCKED" and nothing_reached(world)


def test_passive_stop_with_an_open_diagnostic_session_is_ambiguous(world):
    owner, _ = passive_session(world)
    diagnostic_target(world)
    result = life.run_lifecycle("stop", gui=False, profile="rover_only", passive_session_owner=owner)
    assert result["status"] == "BLOCKED" and "ambiguous" in result["message"] and nothing_reached(world)


# ---------------------------------------------- diagnostic session open --
def test_diagnostic_close_carries_its_exact_descriptor_and_boot(world):
    """Counterexample DIAGNOSTIC_STOP: the descriptor reached the reader without its boot."""
    diagnostic_target(world)
    result = life.run_lifecycle("stop", gui=False, profile="two_drones_rover")
    assert result["success"], result
    (lease,) = world.calls["backend"]
    assert lease["closing_diagnostic_session"] is True and lease["environment_execution"] == EXECUTION
    (child,) = world.calls["subprocess"]
    assert json.loads(child["env"]["TFG_DIAGNOSTIC_CLOSE_TARGET"]) == DESCRIPTOR
    assert child["env"]["TFG_DIAGNOSTIC_CLOSE_BOOT_ID"] == EXECUTION["container_boot_id"]
    assert "TFG_PASSIVE_SESSION_ID" not in child["env"]
    assert json.loads(world.target.read_text())["state"] == "CLOSED"


@pytest.mark.parametrize("profile", ["two_drones", "rover_only_ground"])
def test_another_profile_cannot_close_a_diagnostic_session(world, profile):
    diagnostic_target(world)
    kwargs = {"profile": "two_drones"} if profile == "two_drones" else {"profile": "rover_only",
                                                                         "ground_owner": str(uuid.uuid4())}
    result = life.run_lifecycle("stop", gui=False, **kwargs)
    assert result["status"] == "BLOCKED" and nothing_reached(world)
    assert json.loads(world.target.read_text())["state"] == "STARTED"


def test_diagnostic_session_without_recorded_execution_is_not_closed_generally(world):
    diagnostic_target(world, execution=None)  # a session opened before its execution was recorded
    result = life.run_lifecycle("stop", gui=False, profile="two_drones_rover")
    assert result["status"] == "BLOCKED" and "recorded execution" in result["message"]
    assert nothing_reached(world) and json.loads(world.target.read_text())["state"] == "STARTED"


@pytest.mark.parametrize("change", ["restarted", "other_boot", "unreadable"])
def test_diagnostic_close_with_changed_or_unreadable_execution_is_refused(world, change):
    diagnostic_target(world)
    if change == "unreadable":
        world.current["execution"] = reconciliation_environment.ActiveExecutionReadError(
            "metadata.before", "status", "METADATA_NOT_ACTIVE")
    else:
        field, value = (("container_started_at", "2026-11-02T00:00:00Z") if change == "restarted"
                        else ("container_boot_id", "other-boot"))
        world.current["execution"] = {**EXECUTION, field: value}
    result = life.run_lifecycle("stop", gui=False, profile="two_drones_rover")
    assert result["status"] == "BLOCKED" and nothing_reached(world)
    assert json.loads(world.target.read_text())["state"] == "STARTED"


def test_ordinary_start_close_cannot_close_an_open_diagnostic_session(world):
    diagnostic_target(world)
    result = life.run_lifecycle("stop", gui=False, profile="two_drones_rover",
                                start_close_request=(str(uuid.uuid4()), "0" * 64, {}))
    assert result["status"] == "BLOCKED" and nothing_reached(world)


@pytest.mark.parametrize("damage", ["dangling_link", "directory"])
def test_unreadable_diagnostic_record_is_unknown_never_no_session(world, damage):
    if damage == "dangling_link":
        world.target.symlink_to(world.root / "gone.json")
    else:
        world.target.mkdir()
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["status"] == "BLOCKED" and nothing_reached(world)


def test_backend_refuses_a_descriptor_without_boot_even_if_a_lease_carries_one(world):
    """Defence in depth: whatever the lease, a descriptor never leaves without its boot fence."""
    locks.LOCK_ROOT.mkdir(parents=True)
    locks.atomic_json(locks.LOCK_ROOT / "lifecycle.json", {"profile": "two_drones_rover",
                                                           "diagnostic_close_target": DESCRIPTOR})
    with pytest.raises(locks.VehicleBusy, match="without its exact boot fence"):
        life._backend("stop", False, 0, {}, world.root / "backend.log")
    locks.atomic_json(locks.LOCK_ROOT / "lifecycle.json", {
        "profile": "two_drones_rover", "diagnostic_close_target": DESCRIPTOR, "closing_diagnostic_session": True,
        "environment_execution": EXECUTION, "passive_session_id": "p"})
    with pytest.raises(locks.VehicleBusy, match="exclusive"):
        life._backend("stop", False, 0, {}, world.root / "backend.log")
    assert world.calls["subprocess"] == []


# ------------------------------------------------- no protected session --
def test_ordinary_stop_without_protected_sessions_is_ordinary(world):
    result = life.run_lifecycle("stop", gui=False, profile="two_drones")
    assert result["success"]
    (child,) = world.calls["subprocess"]
    assert not any(k in child["env"] for k in ("TFG_DIAGNOSTIC_CLOSE_TARGET", "TFG_DIAGNOSTIC_CLOSE_BOOT_ID",
                                               "TFG_PASSIVE_SESSION_ID", "TFG_PASSIVE_SESSION_BOOT_ID"))


def test_closed_diagnostic_session_does_not_turn_a_stop_into_a_diagnostic_close(world):
    diagnostic_target(world, state="CLOSED")
    assert life.run_lifecycle("stop", gui=False, profile="two_drones")["success"]
    (child,) = world.calls["subprocess"]
    assert "TFG_DIAGNOSTIC_CLOSE_TARGET" not in child["env"]


# ----------------------------------------------------- pinned reader --
def test_pinned_reader_with_descriptor_and_boot_signals_only_its_session(tmp_path, monkeypatch):
    """Counterexample DIAGNOSTIC_READER, closed by the route: with the boot that every admitted diagnostic close now
    carries, the unmodified reader selects only the session's processes, not the other project session."""
    selected = cleanup.diagnostic_api().digest(DESCRIPTOR)
    fake = FakeProcesses([replace(launch(10), diagnostic_selection_sha256=selected),
                          replace(launch(20), diagnostic_selection_sha256="d" * 64)])

    def send(pid, sig):
        fake.sent.append((pid, sig))
        fake.table.pop(pid)
    fake.send = send
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    monkeypatch.setenv("TFG_DIAGNOSTIC_CLOSE_TARGET", json.dumps(DESCRIPTOR))
    monkeypatch.setenv("TFG_DIAGNOSTIC_CLOSE_BOOT_ID", boot)
    monkeypatch.setattr(cleanup, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(cleanup, "PID_FILE", tmp_path / "pid")
    monkeypatch.setattr(cleanup, "begin_diagnostic_closure", lambda **kw: None)
    fake.stop()
    assert fake.sent and {pid for pid, _ in fake.sent} == {10}


def test_pinned_reader_refuses_another_boot_before_any_signal(tmp_path, monkeypatch):
    fake = FakeProcesses([launch(10)])
    monkeypatch.setenv("TFG_DIAGNOSTIC_CLOSE_TARGET", json.dumps(DESCRIPTOR))
    monkeypatch.setenv("TFG_DIAGNOSTIC_CLOSE_BOOT_ID", "not-this-boot")
    monkeypatch.setattr(cleanup, "STATE", tmp_path / "state.json")
    with pytest.raises(ValueError, match="boot changed"):
        fake.stop()
    assert fake.sent == []
