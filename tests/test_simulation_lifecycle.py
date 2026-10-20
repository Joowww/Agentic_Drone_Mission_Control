"""Offline process tables/signals only: never inspect or signal real processes."""
from dataclasses import replace
import json
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

import simulation.ros2_gazebo.scripts.sim_processes as lifecycle


def proc(pid, parent=1, name="relay", *, tagged=False, ticks=None):
    return lifecycle.Process(pid, parent, ticks or pid * 10, (name,), tagged)


def launch(pid, filename="tfg_demo_2drones.launch.py"):
    return replace(proc(pid), argv=("/usr/bin/python3", "/opt/ros/humble/bin/ros2", "launch",
                                   "ardupilot_gz_bringup", filename, "gui:=true"))


@pytest.fixture(autouse=True)
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(lifecycle, "PID_FILE", tmp_path / "pid")
    monkeypatch.setattr(lifecycle, "LOG_FILE", tmp_path / "demo.log")


class FakeProcesses:
    def __init__(self, processes, exit_on=signal.SIGINT):
        self.table = {p.pid: p for p in processes}
        self.sent = []
        self.now = 0
        self.exit_on = exit_on

    def send(self, pid, sig):
        self.sent.append((pid, sig))
        if sig == self.exit_on:
            owned = lifecycle.select_owned(self.table, set())
            self.table = {pid: p for pid, p in self.table.items() if pid not in owned}

    def sleep(self, seconds):
        self.now += seconds

    def stop(self, **kwargs):
        return lifecycle.shutdown(scan=lambda: dict(self.table), read=self.table.get,
                                  send=self.send, monotonic=lambda: self.now, sleep=self.sleep, **kwargs)


def test_four_project_supervisors_and_all_auxiliaries_are_selected():
    records = [launch(i) for i in (10, 20, 30, 40)]
    records += [proc(11, 10, "parameter_bridge"), proc(12, 11, "relay"),
                proc(21, 20, "robot_state_publisher"), proc(22, 20, "micro_ros_agent"),
                proc(31, 30, "ruby"), proc(32, 31, "gz sim"),
                proc(41, 40, "arducopter"), proc(42, 40, "mavproxy.py"),
                proc(43, 40, "create"), proc(44, 40, "rviz2")]
    foreign = [launch(60, "iris_runway.launch.py"), proc(61, 60, "parameter_bridge"),
               proc(70, name="arducopter"), proc(71, name="gz sim"),
               replace(proc(80), argv=("bash", "-lc", "ros2 launch ardupilot_gz_bringup tfg_demo.launch.py"))]
    table = {p.pid: p for p in records + foreign}
    assert set(lifecycle.select_owned(table, set())) == {p.pid for p in records}


def test_graceful_shutdown_signals_all_roots_and_no_foreign_processes():
    env = FakeProcesses([launch(10), proc(11, 10), launch(20), proc(21, 20), proc(90)])
    # Real launch shutdown removes its own tree, not the other supervisor's tree.
    def graceful(pid, sig):
        env.sent.append((pid, sig))
        for victim in (pid, pid + 1):
            env.table.pop(victim, None)
    env.send = graceful
    result = env.stop()
    assert result["success"]
    assert env.sent == [(10, signal.SIGINT), (20, signal.SIGINT)]
    assert set(env.table) == {90}
    assert not lifecycle.STATE.exists()


def test_bounded_escalation_includes_helpers_and_verifies_survivors():
    env = FakeProcesses([launch(10), proc(11, 10), proc(90)], exit_on=None)
    result = env.stop()
    assert not result["success"]
    assert [p["pid"] for p in result["remaining"]] == [10, 11]
    assert env.sent == [(10, signal.SIGINT), (10, signal.SIGTERM), (11, signal.SIGTERM),
                        (10, signal.SIGKILL), (11, signal.SIGKILL)]
    assert env.now == 20
    assert lifecycle.STATE.exists()


def test_orphaned_marker_is_recognized_without_a_live_launch():
    env = FakeProcesses([proc(11, name="parameter_bridge", tagged=True), proc(12, 11), proc(90)])
    assert env.stop()["success"]
    assert env.sent == [(11, signal.SIGINT)]
    assert 90 in env.table


def test_reparented_legacy_helpers_remain_owned_during_escalation():
    env = FakeProcesses([launch(10), proc(11, 10, "relay")], exit_on=None)
    def reparent(pid, sig):
        env.sent.append((pid, sig))
        if pid == 10:
            env.table.pop(10, None)
            env.table[11] = replace(env.table[11], ppid=1)
        else:
            env.table.pop(11, None)
    env.send = reparent
    assert env.stop()["success"]
    assert env.sent == [(10, signal.SIGINT), (11, signal.SIGTERM)]


def test_stale_pid_file_never_selects_an_unrelated_process():
    lifecycle.PID_FILE.write_text("90")
    env = FakeProcesses([proc(90, name="bash")])
    assert env.stop()["success"]
    assert env.sent == []
    assert 90 in env.table


def test_reused_pid_not_signaled_even_if_snapshot_was_owned():
    env = FakeProcesses([launch(10)], exit_on=None)
    def reused(pid):
        return replace(proc(pid), start_ticks=9999)
    result = lifecycle.shutdown(scan=lambda: dict(env.table), read=reused,
                                send=env.send, monotonic=lambda: env.now, sleep=env.sleep)
    assert not result["success"]
    assert env.sent == []


def test_own_shell_and_ancestors_are_protected(monkeypatch):
    monkeypatch.setattr(lifecycle.os, "getpid", lambda: 99)
    env = FakeProcesses([launch(10), proc(99, 10)], exit_on=None)
    result = env.stop()
    assert not result["success"]
    assert result["errors"]
    assert env.sent == []


def test_zombies_do_not_count_as_live_project_processes():
    env = FakeProcesses([replace(launch(10), zombie=True)])
    assert env.stop()["success"]
    assert env.sent == []


def test_proc_parser_uses_start_time_and_exact_environment_marker(tmp_path):
    directory = tmp_path / "123"
    directory.mkdir()
    # Fields 3..22 after the comm field, which can contain spaces/parentheses.
    fields = ["S", "10"] + ["0"] * 17 + ["12345"]
    (directory / "stat").write_text("123 (name (with spaces)) " + " ".join(fields))
    (directory / "cmdline").write_bytes(b"/usr/bin/ros2\0launch\0")
    (directory / "environ").write_bytes(f"{lifecycle.MARKER}={lifecycle.PROJECT}\0".encode())
    parsed = lifecycle.read_process(123, tmp_path)
    assert parsed.start_ticks == 12345 and parsed.ppid == 10 and parsed.tagged
    assert lifecycle.read_process(999, tmp_path) is None


def test_start_refuses_duplicate_project_processes_without_spawning(monkeypatch):
    monkeypatch.setattr(lifecycle, "snapshot", lambda: {10: launch(10)})
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *a, **k: pytest.fail("duplicate spawn"))
    with pytest.raises(RuntimeError, match="second launch"):
        lifecycle.start()


def test_start_marks_children_restores_sigint_and_preserves_old_log(monkeypatch):
    lifecycle.LOG_FILE.write_text("previous evidence")
    monkeypatch.setattr(lifecycle, "snapshot", lambda: {})
    captured = {}
    def fake_popen(args, **kwargs):
        captured.update(args=args, **kwargs)
        return SimpleNamespace(pid=10)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(lifecycle, "read_process", lambda pid: launch(pid))
    signals = []
    monkeypatch.setattr(lifecycle.signal, "signal", lambda *args: signals.append(args))
    result = lifecycle.start()
    assert result["success"]
    assert captured["start_new_session"] is True
    assert captured["env"][lifecycle.MARKER] == lifecycle.PROJECT
    assert signals == [(signal.SIGINT, signal.SIG_DFL)]
    assert any(p.read_text() == "previous evidence" for p in lifecycle.LOG_FILE.parent.glob("tfg_demo.*.log"))
    assert lifecycle.remembered_identities() == {(10, 100)}


def test_unattributed_namespaced_orphan_blocks_success_but_is_never_signaled():
    ambiguous = replace(proc(20), argv=("/opt/ros/humble/lib/ros_gz_bridge/parameter_bridge",
                                         "--ros-args", "-r", "__ns:=/drone1"))
    env = FakeProcesses([ambiguous])
    result = env.stop()
    assert not result["success"]
    assert [p["pid"] for p in result["unattributed_auxiliaries"]] == [20]
    assert env.sent == []


def test_unrelated_namespaces_and_launch_argument_text_are_not_owned_or_blockers():
    unrelated = replace(proc(20), argv=("/opt/ros/humble/lib/ros_gz_bridge/parameter_bridge",
                                       "--ros-args", "-r", "__ns:=/other_project"))
    env = FakeProcesses([unrelated])
    assert env.stop()["success"]
    assert env.sent == []


@pytest.mark.parametrize("script", ["start_sim.sh", "stop_sim.sh", "restart_sim.sh"])
def test_scripts_abort_on_cleanup_failure_with_a_fake_docker_only(tmp_path, monkeypatch, script):
    import os
    import subprocess
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    log = tmp_path / "calls.jsonl"
    docker.write_text("""#!/usr/bin/env python3
import json,os,sys
with open(os.environ['TFG_TEST_DOCKER_LOG'],'a') as f:
    f.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1] == 'inspect':
    print('true')
if sys.argv[-1] == 'stop':
    print('simulated cleanup failed')
    sys.exit(1)
""")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TFG_TEST_DOCKER_LOG", str(log))
    # A separate temporary project exercises the REAL wrappers/lease/backend with
    # fake Docker, without reading or changing the real runtime reservations.
    import shutil
    import sys
    project = tmp_path / "project"
    source = Path(__file__).resolve().parents[1]
    relative_files = ["tools/__init__.py", "tools/simulated_vehicle.py", "tools/vehicle_execution_lock.py",
                      "tools/simulation_lifecycle.py", "tools/simulation_profiles.py", "simulation/ros2_gazebo/launch/tfg_demo_2drones.launch.py"]
    relative_files += ["simulation/ros2_gazebo/scripts/"+name for name in
                       ("start_sim.sh", "stop_sim.sh", "restart_sim.sh", "start_sim_backend.sh", "stop_sim_backend.sh", "sim_processes.py")]
    for relative in relative_files:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if (source/relative).exists(): shutil.copyfile(source/relative, target)
        else: target.touch()
    python = project / ".venv/bin/python"
    python.parent.mkdir(parents=True); python.symlink_to(sys.executable)
    path = project / "simulation/ros2_gazebo/scripts" / script
    result = subprocess.run(["bash", str(path)], cwd=project, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(call[-1] == "stop" for call in calls)
    assert not any(call[-1] == "start" for call in calls)
    assert "SIMULATION STOPPED" not in result.stdout


def test_permission_error_does_not_claim_a_successful_shutdown():
    env = FakeProcesses([launch(10)], exit_on=None)
    def denied(pid, sig):
        raise PermissionError("signal denied")
    env.send = denied
    result = env.stop()
    assert not result["success"]
    assert result["remaining"] and result["errors"]
