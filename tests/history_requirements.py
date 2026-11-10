"""Tests that read pinned revisions skip, with the reason, only when those revisions are absent from this clone.

The pinned revisions (rover snapshots, contract and bridge commits, the pilot registration commit) are reachable from
the archive of the development history (tag archive/integration-history-2026-11-10). A clone of the main branch alone
does not contain them: current behaviour is still tested there, and reproducing sealed evidence needs the archive.
Only a revision that git reports as absent is a reason to skip; any other git failure fails the test."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def commit_present(commit: str) -> bool:
    """True if present, False if git reports it absent; any other outcome (no repository, git failure) raises."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode == 0:
        return True
    if result.returncode == 1 and not result.stderr.strip():
        return False
    raise RuntimeError(f"cannot determine whether {commit} is present: git exit {result.returncode} "
                       f"{result.stderr.strip()[:200]}")


def require_commits(*commits: str) -> None:
    missing = []
    for commit in commits:
        try:
            present = commit_present(commit)
        except RuntimeError as exc:
            pytest.fail(str(exc))
        if not present:
            missing.append(commit)
    if missing:
        pytest.skip("pinned revision(s) not in this clone (archive tag absent): " + ", ".join(missing))
