"""STOP at the shell/process boundary: the real stop_sim_backend.sh with a recording docker double.

No Docker, container, ROS process or signal is used: the docker double only records its arguments and answers
inspection queries. Covers passive-session close, a close boot fence without its descriptor, inspection failures,
an ordinary STOP, a failed STOP, and the process reader's own behaviour for an empty descriptor and foreign
processes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from simulation.ros2_gazebo.scripts import sim_processes as cleanup
from tests.test_simulation_lifecycle import FakeProcesses, files, launch, proc  # noqa: F401  (files: tmp state)

REPO = Path(__file__).resolve().parents[1]
DOCKER = '''#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps(args) + "\\n")
if args[0] == "inspect":
    print(os.environ["RUNNING"]); sys.exit(int(os.environ["INSPECT_CODE"]))
if args[0] == "exec":
    sys.exit(int(os.environ["EXEC_CODE"]))
'''


@pytest.fixture
def backend(tmp_path):
    """Run the real stop script against a docker double; returns (result, docker calls)."""
    project = tmp_path / "project"
    scripts = project / "simulation/ros2_gazebo/scripts"
    scripts.mkdir(parents=True)
    script = scripts / "stop_sim_backend.sh"
    script.write_text((REPO / "simulation/ros2_gazebo/scripts/stop_sim_backend.sh").read_text()
                      .replace("/tmp/tfg_simulation_control.lock", str(tmp_path / "lock")))
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!" + sys.executable + "\nimport sys\nif sys.argv[1] == '-c': exec(sys.argv[2])\n")
    python.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(DOCKER)
    (bindir / "docker").chmod(0o755)
    calls = tmp_path / "calls"

    def run(*, running="true", inspect_code=0, exec_code=0, **variables):
        calls.write_text("")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TFG_DIAGNOSTIC_", "TFG_PASSIVE_"))}
        env.update({"PATH": f"{bindir}:/usr/bin:/bin", "CALLS": str(calls), "RUNNING": running,
                    "INSPECT_CODE": str(inspect_code), "EXEC_CODE": str(exec_code), **variables})
        result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=20)
        return result, [json.loads(line) for line in calls.read_text().splitlines()]
    return run


def test_passive_close_is_refused_before_any_inspection_or_signal(backend):
    result, calls = backend(TFG_PASSIVE_SESSION_ID="session-1", TFG_PASSIVE_SESSION_BOOT_ID="boot-1",
                            TFG_DIAGNOSTIC_CLOSE_BOOT_ID="boot-1")
    assert result.returncode == 3 and "PASSIVE_STOP_OWNERSHIP_UNVERIFIABLE" in result.stderr
    assert calls == []  # no docker inspect, cp or exec: nothing inventoried or signalled


def test_close_boot_fence_without_descriptor_is_refused(backend):
    result, calls = backend(TFG_DIAGNOSTIC_CLOSE_BOOT_ID="boot-1", TFG_DIAGNOSTIC_CLOSE_TARGET="")
    assert result.returncode == 3 and "CLOSE_DESCRIPTOR_MISSING" in result.stderr
    assert calls == []


@pytest.mark.parametrize("running,inspect_code", [("", 1), ("", 125), ("paused", 0), ("unknown", 0)])
def test_ordinary_stop_with_uninspectable_or_unexpected_state_is_unknown(backend, running, inspect_code):
    result, calls = backend(running=running, inspect_code=inspect_code)
    assert result.returncode == 1 and "UNKNOWN" in result.stderr
    assert [c[0] for c in calls] == ["inspect"]  # no copy or exec after an unknown state


def test_ordinary_stop_of_a_stopped_container_sends_nothing(backend):
    result, calls = backend(running="false")
    assert result.returncode == 0 and [c[0] for c in calls] == ["inspect"]


def test_ordinary_stop_runs_the_project_cleanup_once(backend):
    result, calls = backend(running="true")
    assert result.returncode == 0 and "SIMULATION STOPPED" in result.stdout
    execs = [c for c in calls if c[0] == "exec"]
    assert len(execs) == 1 and execs[0][-1] == "stop"
    assert "TFG_DIAGNOSTIC_CLOSE_TARGET=" in execs[0] and "TFG_DIAGNOSTIC_CLOSE_BOOT_ID=" in execs[0]


def test_failed_stop_is_reported_as_failure(backend):
    result, calls = backend(running="true", exec_code=2)
    assert result.returncode != 0 and "SIMULATION STOPPED" not in result.stdout


def test_process_reader_refuses_an_empty_descriptor_before_scanning(monkeypatch):
    """The pinned reader fails closed: with a boot fence and an empty descriptor it never scans or signals."""
    monkeypatch.setenv("TFG_DIAGNOSTIC_CLOSE_BOOT_ID", Path("/proc/sys/kernel/random/boot_id").read_text().strip())
    monkeypatch.setenv("TFG_DIAGNOSTIC_CLOSE_TARGET", "")
    fail = lambda *a, **k: pytest.fail("scan or signal reached")
    with pytest.raises(ValueError):
        cleanup.shutdown(scan=fail, send=fail, read=fail, monotonic=lambda: 0, sleep=lambda s: None)


def test_ordinary_cleanup_never_signals_foreign_processes(monkeypatch):
    monkeypatch.delenv("TFG_DIAGNOSTIC_CLOSE_BOOT_ID", raising=False)
    monkeypatch.delenv("TFG_DIAGNOSTIC_CLOSE_TARGET", raising=False)
    monkeypatch.setattr(cleanup, "begin_diagnostic_closure", lambda **kw: None)
    own = [launch(10), proc(11, 10, "parameter_bridge")]
    foreign = [launch(60, "iris_runway.launch.py"), proc(61, 60, "parameter_bridge"), proc(70, name="arducopter")]
    env = FakeProcesses(own + foreign)
    env.stop()
    assert env.sent and {pid for pid, _ in env.sent} <= {10, 11}
    assert all(sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL) for _, sig in env.sent)


DESCRIPTOR = json.dumps({"manifest": {"container_id": "fixture-container", "engine_id": "e", "image_id": "i"}})


@pytest.mark.parametrize("variables", [
    # counterexample MIXED_PASSIVE: passive mark with a diagnostic descriptor and boot reached docker exec
    {"TFG_PASSIVE_SESSION_ID": "s", "TFG_PASSIVE_SESSION_BOOT_ID": "b", "TFG_DIAGNOSTIC_CLOSE_TARGET": DESCRIPTOR,
     "TFG_DIAGNOSTIC_CLOSE_BOOT_ID": "b"},
    {"TFG_PASSIVE_SESSION_ID": "s", "TFG_DIAGNOSTIC_CLOSE_TARGET": DESCRIPTOR},
    {"TFG_PASSIVE_SESSION_BOOT_ID": "b"},
], ids=["passive+descriptor+boot", "passive+descriptor", "passive-boot-only"])
def test_any_passive_mark_refuses_the_stop_before_docker(backend, variables):
    result, calls = backend(**variables)
    assert result.returncode == 3 and "PASSIVE_STOP_OWNERSHIP_UNVERIFIABLE" in result.stderr and calls == []


@pytest.mark.parametrize("boot", [None, ""], ids=["absent", "empty"])
def test_descriptor_without_boot_is_refused_before_docker(backend, boot):
    """Counterexample DIAGNOSTIC_STOP at the shell: the descriptor alone reached the reader's general selection."""
    variables = {"TFG_DIAGNOSTIC_CLOSE_TARGET": DESCRIPTOR}
    if boot is not None:
        variables["TFG_DIAGNOSTIC_CLOSE_BOOT_ID"] = boot
    result, calls = backend(**variables)
    assert result.returncode == 3 and "CLOSE_BOOT_MISSING" in result.stderr and calls == []


def test_diagnostic_close_passes_its_exact_descriptor_and_boot(backend):
    result, calls = backend(TFG_DIAGNOSTIC_CLOSE_TARGET=DESCRIPTOR, TFG_DIAGNOSTIC_CLOSE_BOOT_ID="fixture-boot")
    assert result.returncode == 0
    assert calls[0] == ["inspect", "-f", "{{.State.Running}}", "fixture-container"]
    (execs,) = [c for c in calls if c[0] == "exec"]
    assert f"TFG_DIAGNOSTIC_CLOSE_TARGET={DESCRIPTOR}" in execs and "TFG_DIAGNOSTIC_CLOSE_BOOT_ID=fixture-boot" in execs
