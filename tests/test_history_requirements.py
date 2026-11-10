"""Without the pinned git objects, historical verification and reproduction are refused, never reported as done.

These tests run in every clone (never skipped): they replace the pinned revision with one that cannot exist, so they
exercise exactly what a clone of main without the archive tag does."""
from __future__ import annotations

import io
import subprocess

import pytest

from multiagent import historical_identifiers as hist, replay, rover_handoff as rh
from multiagent.benchmark import milestone
from multiagent.benchmark import run as bench
from tests import history_requirements as req

M4C_R1 = bench.ROOT / "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9"
ABSENT = "0" * 40  # a commit id that cannot be in any repository


def test_sealed_evidence_without_its_registration_commit_does_not_verify(monkeypatch):
    monkeypatch.setitem(hist.PILOT_MANIFEST_REGISTRATIONS, "m4c_r1_integrated_v1", ABSENT)
    v = milestone.verify(M4C_R1)
    assert v["ok"] is False and v["manifest_equals_registered"] is False
    assert v["manifest_registration_commit"] == ABSENT  # never replaced by a commit found in the branch history


def test_replay_without_its_registration_commit_is_refused(monkeypatch):
    monkeypatch.setitem(hist.PILOT_MANIFEST_REGISTRATIONS, "m4c_r1_integrated_v1", ABSENT)
    out = io.StringIO()
    result = replay.replay(M4C_R1, out=out)
    assert result["status"] == "REFUSED_UNVERIFIED" and out.getvalue().startswith("REFUSED")


def test_snapshot_of_an_absent_revision_fails_explicitly(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        rh.ensure_snapshot(tmp_path / "snapshot", ABSENT)
    assert not (tmp_path / "snapshot" / ".snapshot_commit").exists()


def test_require_commits_skips_only_for_an_absent_revision():
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=req.ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()
    req.require_commits(head)  # present: no skip
    with pytest.raises(pytest.skip.Exception, match=ABSENT):
        req.require_commits(head, ABSENT)


def test_require_commits_fails_when_presence_cannot_be_determined(tmp_path, monkeypatch):
    monkeypatch.setattr(req, "ROOT", tmp_path)  # not a git repository: git exits 128
    with pytest.raises(pytest.fail.Exception, match="cannot determine"):
        req.require_commits(ABSENT)
