"""Pilot preflight: a probe that cannot show its state blocks; reservations are read from every worktree.

No Docker, ps or git process is used except where stated: ``pilot._run`` is replaced by a recording double and the
worktrees are temporary directories. Reproduces the review's counterexamples: a failed ``docker top`` accepted as a
running container without simulation processes, and a wrong or missing lock checkout read as zero reservations."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from multiagent.benchmark import agents_pilot as ap
from multiagent.benchmark import pilot

UNKNOWN_TABLE = pilot.UNREADABLE_PROCESS_TABLE


def commands(answers):
    """A ``_run`` double: answers[(argv[0], argv[1])] -> (code, output); records every call."""
    calls = []

    def run(cmd):
        calls.append(cmd)
        return answers[(cmd[0], cmd[1])]
    return run, calls


# ------------------------------------------------------------ container --
def test_failed_docker_top_is_unknown_not_a_clear_container(monkeypatch):
    """Counterexample: docker top failing gave RUNNING with no matches, and the check accepted it."""
    run, _ = commands({("docker", "ps"): (0, "Up 5 minutes\n"), ("docker", "top"): (1, "Error: permission denied")})
    monkeypatch.setattr(pilot, "_run", run)
    container = pilot.container_processes()
    assert container["status"] == "UNKNOWN" and container["reason"] == "DOCKER_TOP_FAILED"
    assert pilot.container_clear(container) is False


def test_empty_docker_top_listing_is_unknown(monkeypatch):
    run, _ = commands({("docker", "ps"): (0, "Up 5 minutes\n"), ("docker", "top"): (0, "PID ELAPSED COMMAND\n")})
    monkeypatch.setattr(pilot, "_run", run)
    container = pilot.container_processes()
    assert container["reason"] == "DOCKER_TOP_EMPTY" and not pilot.container_clear(container)


def test_read_container_listing_is_judged_by_its_processes(monkeypatch):
    listing = "PID ELAPSED COMMAND\n1 00:10 sleep infinity\n"
    run, _ = commands({("docker", "ps"): (0, "Up 5 minutes\n"), ("docker", "top"): (0, listing)})
    monkeypatch.setattr(pilot, "_run", run)
    assert pilot.container_clear(pilot.container_processes()) is True
    busy = listing + "2 00:09 gz sim -r world.sdf\n"
    run, _ = commands({("docker", "ps"): (0, "Up 5 minutes\n"), ("docker", "top"): (0, busy)})
    monkeypatch.setattr(pilot, "_run", run)
    assert pilot.container_clear(pilot.container_processes()) is False


@pytest.mark.parametrize("container,clear", [
    ({"status": "RUNNING", "matches": []}, False),                        # the counterexample's shape: nothing read
    ({"status": "RUNNING (Up)", "processes_read": "yes", "matches": []}, False),
    ({"status": "DOCKER_UNAVAILABLE", "matches": []}, False),
    ({"status": "UNKNOWN", "matches": []}, False),
    ({}, False),
    ({"status": "NOT_RUNNING", "matches": []}, True),
    ({"status": "RUNNING (Up)", "processes_read": True, "matches": []}, True),
    ({"status": "RUNNING (Up)", "processes_read": True, "matches": ["1 arducopter"]}, False),
])
def test_container_is_clear_only_when_shown(container, clear):
    assert pilot.container_clear(container) is clear


def test_preconditions_block_on_failed_docker_top(monkeypatch):
    run, _ = commands({("docker", "ps"): (0, "Up 5 minutes\n"), ("docker", "top"): (125, "")})
    monkeypatch.setattr(pilot, "_run", run)
    probes = {"version": lambda: {"version": "x"}, "model": lambda: {"digest": "d"}, "host": lambda: [],
              "reservations": lambda: [], "gpu": lambda: {"status": "MEASURED", "memory_used_mib": 1}}
    result = pilot.check_preconditions({"expected_model": {"name": "m", "digest": "d"}}, probes=probes)
    assert result["checks"]["no_simulation_process_in_container"] is False and result["ok"] is False


# ---------------------------------------------------------- host tables --
@pytest.mark.parametrize("answer", [(1, "ps: error"), (127, "OSError"), (0, ""), (0, "COMMAND\n")])
def test_unreadable_host_process_table_is_a_blocking_finding(monkeypatch, answer):
    run, _ = commands({("ps", "-eo"): answer})
    monkeypatch.setattr(pilot, "_run", run)
    assert pilot.host_processes() == [UNKNOWN_TABLE]
    assert ap._ps_lines() == [UNKNOWN_TABLE]
    assert ap.concurrent_pilots(ap._ps_ppid_lines(), set()) == [UNKNOWN_TABLE]
    assert ap.sampled_processes(samples=1) == [UNKNOWN_TABLE]
    assert ap._not_a_test(UNKNOWN_TABLE)  # counted as a session, never ignored as a test runner


def test_resource_isolation_blocks_on_unreadable_process_tables(monkeypatch):
    run, _ = commands({("ps", "-eo"): (1, "ps: error"), ("docker", "ps"): (0, ""),
                       ("nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu"): (1, ""),
                       ("nvidia-smi", "--query-compute-apps=pid,process_name,used_memory"): (1, "")})
    monkeypatch.setattr(pilot, "_run", run)
    monkeypatch.setattr("time.sleep", lambda s: None)  # sampled_processes pauses between samples
    facts = {"ollama_ps": lambda: [], "locks": lambda: [], "git": lambda: "", "contract_pinned": lambda: True,
             "manifest_integrity": lambda: {"ok": True}, "activity": lambda: [], "meminfo": lambda: {"available_mib": 1}}
    base = {"version": lambda: {"version": "x"}, "model": lambda: {"digest": "d"}, "reservations": lambda: []}
    manifest = {"model": {"candidate": "ollama:m", "digest": "d"}}
    monkeypatch.setattr(ap.base_pilot, "check_preconditions",
                        lambda m, probes: {"checks": {"ollama_answers_locally": True,
                                                      "model_installed_with_expected_digest": True,
                                                      "no_external_endpoint": True},
                                           "facts": {"gpu": {"status": "NOT_MEASURED"},
                                                     "reservations_original_checkout": []}})
    result = ap.resource_isolation(manifest, probes={**base, **facts})
    assert result["facts"]["concurrent_llm_processes"] == [UNKNOWN_TABLE]
    assert UNKNOWN_TABLE in result["facts"]["operational_processes"]
    assert result["checks"]["1_no_concurrent_llm_experiment"] is False
    assert result["checks"]["2_no_gazebo_or_sitl_session"] is False
    assert result["checks"]["5_no_protected_operation"] is False


# ---------------------------------------------------------- lock source --
@pytest.fixture
def trees(tmp_path):
    """Two worktrees of one repository, both with a lock root; returns (runtime, other, worktree records)."""
    runtime, other = tmp_path / "main", tmp_path / "integration"
    for root in (runtime, other):
        (root / pilot.LOCK_SUBDIR).mkdir(parents=True)
    return runtime, other, [{"path": str(runtime), "prunable": False}, {"path": str(other), "prunable": False}]


def test_verified_lock_source_covers_every_worktree(trees):
    runtime, other, records = trees
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "VERIFIED" and sources["roots"] == [str(runtime), str(other)]
    assert pilot.reservations(sources) == []


def test_reservation_in_another_worktree_is_found(trees):
    """Lock state is per checkout: a reservation held in the other worktree is still a reservation."""
    runtime, other, records = trees
    (other / pilot.LOCK_SUBDIR / "v3.json").write_text("{}")
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert pilot.reservations(sources) == [f"{other}:v3.json"]


@pytest.mark.parametrize("case,reason", [
    ("missing_runtime", "RUNTIME_CHECKOUT_NOT_A_WORKTREE_OF_THIS_REPOSITORY"),
    ("foreign_runtime", "RUNTIME_CHECKOUT_NOT_A_WORKTREE_OF_THIS_REPOSITORY"),
    ("runtime_without_lock_root", "RUNTIME_LOCK_ROOT_MISSING"),
    ("unreadable_worktree", "WORKTREE_UNREADABLE"),
    ("lock_root_is_a_file", "LOCK_ROOT_NOT_A_DIRECTORY"),
    ("no_worktree_list", "WORKTREE_LIST_UNREADABLE"),
])
def test_unverifiable_lock_source_is_unknown_never_zero_reservations(trees, tmp_path, case, reason):
    """Counterexample: a wrong or non-existent TFG_RUNTIME_CHECKOUT was read as zero reservations."""
    runtime, other, records = trees
    if case == "missing_runtime":
        runtime = tmp_path / "does-not-exist"
    elif case == "foreign_runtime":
        runtime = tmp_path / "elsewhere"
        (runtime / pilot.LOCK_SUBDIR).mkdir(parents=True)
    elif case == "runtime_without_lock_root":
        (runtime / pilot.LOCK_SUBDIR).rmdir()
    elif case == "unreadable_worktree":
        records = records + [{"path": str(tmp_path / "unmounted"), "prunable": False}]
    elif case == "lock_root_is_a_file":
        (other / pilot.LOCK_SUBDIR).rmdir()
        (other / pilot.LOCK_SUBDIR).write_text("")
    elif case == "no_worktree_list":
        records = []
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "UNKNOWN" and any(r.startswith(reason) for r in sources["reasons"])
    found = pilot.reservations(sources)
    assert found and all(f.startswith("UNKNOWN: ") for f in found)
    assert ap.recent_locks(sources) == found and ap.recent_checkout_activity(sources) == found


def test_pruned_worktree_without_directory_holds_no_lock_state(trees, tmp_path):
    runtime, _, records = trees
    records = records + [{"path": str(tmp_path / "gone"), "prunable": True}]
    assert pilot.lock_sources(runtime=runtime, worktrees=records)["status"] == "VERIFIED"


def test_unreadable_worktree_list_from_git_is_unknown(monkeypatch):
    run, _ = commands({("git", "-C"): (128, "fatal: not a git repository")})
    monkeypatch.setattr(pilot, "_run", run)
    assert pilot.repository_worktrees() is None
    assert pilot.lock_sources()["status"] == "UNKNOWN"


def test_worktree_list_parsing(monkeypatch):
    out = ("worktree /a\nHEAD 1\nbranch refs/heads/x\n\nworktree /b\nHEAD 2\ndetached\nprunable gitdir file points to "
           "non-existent location\n\n")
    run, calls = commands({("git", "-C"): (0, out)})
    monkeypatch.setattr(pilot, "_run", run)
    assert pilot.repository_worktrees() == [{"path": "/a", "prunable": False}, {"path": "/b", "prunable": True}]
    assert calls[0][-3:] == ["worktree", "list", "--porcelain"]


def test_recent_locks_and_activity_read_every_worktree(trees, monkeypatch):
    runtime, other, records = trees
    (runtime / pilot.LOCK_SUBDIR / "lifecycle.json").write_text("{}")
    (other / "tools").mkdir()
    (other / "tools" / "x.py").write_text("")
    monkeypatch.setattr(pilot, "REPO_ROOT", runtime)  # the pilot runs from `runtime`; its own edits are not activity
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    now = datetime.now(timezone.utc)
    assert ap.recent_locks(sources, now=now) == [f"{runtime}:lifecycle.json"]
    assert ap.recent_checkout_activity(sources, now=now) == [f"{other}:tools/x.py"]


def test_this_repository_lists_its_own_checkout():
    """Real git, read only: the worktree list of this repository includes the checkout the code runs from."""
    trees = pilot.repository_worktrees()
    assert trees and pilot.REPO_ROOT.resolve() in {Path(t["path"]).resolve() for t in trees}


# ------------------------------------------- lock roots: links and reads --
@pytest.mark.parametrize("component", ["missions", "missions/generated", "missions/generated/vehicle_locks"])
@pytest.mark.parametrize("dangling", [True, False])
def test_symlinked_lock_root_component_is_unknown(trees, tmp_path, component, dangling):
    """Counterexample: a dangling link at a registered peer's lock root was read as no root, VERIFIED and empty."""
    runtime, other, records = trees
    import shutil
    shutil.rmtree(other / "missions")
    link = other / component
    link.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "unavailable"
    if not dangling:
        (target / "vehicle_locks").mkdir(parents=True)
        (target / "vehicle_locks" / "v1.json").write_text("{}")  # a reservation behind the link stays unknown
    link.symlink_to(target, target_is_directory=True)
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "UNKNOWN"
    assert any(r.startswith("LOCK_ROOT_SYMLINK:") for r in sources["reasons"])
    found = pilot.reservations(sources)
    assert found and all(f.startswith("UNKNOWN: ") for f in found)
    assert ap.recent_locks(sources) == found


def test_runtime_lock_root_symlink_is_unknown(trees, tmp_path):
    runtime, _, records = trees
    real = tmp_path / "real-locks"
    real.mkdir()
    (runtime / pilot.LOCK_SUBDIR).rmdir()
    (runtime / pilot.LOCK_SUBDIR).symlink_to(real, target_is_directory=True)
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "UNKNOWN" and any("LOCK_ROOT_SYMLINK" in r for r in sources["reasons"])


def test_legitimate_absence_is_distinguished_from_an_anomalous_one(trees):
    runtime, other, records = trees
    (other / pilot.LOCK_SUBDIR).rmdir()                      # runtime-created component missing: legitimate
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "VERIFIED" and sources["lock_roots"][str(other)]["state"] == "ABSENT"
    assert pilot.reservations(sources) == []
    (other / "missions" / "generated").rmdir()
    (other / "missions").rmdir()                             # versioned component missing: anomalous
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "UNKNOWN"
    assert any(r.startswith("LOCK_ROOT_COMPONENT_MISSING:") for r in sources["reasons"])


def test_inconsistent_runtime_path_is_unknown(trees, tmp_path):
    """A path that resolves to a registered worktree only through a link that later changes is not trusted twice."""
    runtime, other, records = trees
    alias = tmp_path / "alias"
    alias.symlink_to(runtime, target_is_directory=True)
    assert pilot.lock_sources(runtime=alias, worktrees=records)["status"] == "VERIFIED"  # same directory
    alias.unlink()
    alias.symlink_to(tmp_path / "nowhere", target_is_directory=True)
    sources = pilot.lock_sources(runtime=alias, worktrees=records)
    assert any(r.startswith("RUNTIME_CHECKOUT_NOT_A_WORKTREE_OF_THIS_REPOSITORY") for r in sources["reasons"])


@pytest.mark.parametrize("error", [PermissionError, OSError])
def test_lock_root_read_errors_are_unknown(trees, monkeypatch, error):
    runtime, other, records = trees
    real_lstat = pilot.os.lstat

    def lstat(path, *a, **k):
        if str(path).startswith(str(other / "missions")):
            raise error("simulated read error")
        return real_lstat(path, *a, **k)
    monkeypatch.setattr(pilot.os, "lstat", lstat)
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "UNKNOWN" and any(r.startswith("LOCK_ROOT_UNREADABLE:") for r in sources["reasons"])


def test_unlistable_lock_root_is_unknown(trees, monkeypatch):
    runtime, other, records = trees
    real_listdir = pilot.os.listdir
    monkeypatch.setattr(pilot.os, "listdir", lambda p: (_ for _ in ()).throw(PermissionError("denied"))
                        if str(p) == str(other / pilot.LOCK_SUBDIR) else real_listdir(p))
    assert pilot.lock_sources(runtime=runtime, worktrees=records)["status"] == "UNKNOWN"


def test_inaccessible_worktree_is_unknown(trees, monkeypatch):
    runtime, other, records = trees
    real_stat = pilot.os.stat
    monkeypatch.setattr(pilot.os, "stat", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError("denied"))
                        if str(p) == str(other) else real_stat(p, *a, **k))
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "UNKNOWN" and any(r.startswith("WORKTREE_UNREADABLE:") for r in sources["reasons"])


def test_lock_root_replaced_after_verification_is_unknown(trees, tmp_path):
    runtime, other, records = trees
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert sources["status"] == "VERIFIED"
    lock_root = other / pilot.LOCK_SUBDIR
    lock_root.rename(tmp_path / "moved")
    lock_root.symlink_to(tmp_path / "moved", target_is_directory=True)  # same contents, now behind a link
    found = pilot.reservations(sources)
    assert any(f.startswith("UNKNOWN: LOCK_ROOT_CHANGED_DURING_SCAN") for f in found)
    assert any(f.startswith("UNKNOWN: LOCK_ROOT_CHANGED_DURING_SCAN") for f in ap.recent_locks(sources))


def test_reservation_entry_that_is_a_link_still_counts(trees, tmp_path):
    runtime, other, records = trees
    (other / pilot.LOCK_SUBDIR / "lifecycle.json").symlink_to(tmp_path / "missing.json")
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    assert pilot.reservations(sources) == [f"{other}:lifecycle.json"]


def test_unreadable_entry_during_lock_walk_is_unknown(trees, monkeypatch):
    runtime, other, records = trees
    (other / pilot.LOCK_SUBDIR / "sub").mkdir()
    sources = pilot.lock_sources(runtime=runtime, worktrees=records)
    real_walk = ap.os.walk

    def walk(top, onerror=None, followlinks=False):
        for item in real_walk(top, onerror=onerror, followlinks=followlinks):
            yield item
        onerror(PermissionError("denied while scanning"))
    monkeypatch.setattr(ap.os, "walk", walk)
    found = ap.recent_locks(sources)
    assert any(f.startswith("UNKNOWN: LOCK_ROOT_UNREADABLE:") for f in found)
