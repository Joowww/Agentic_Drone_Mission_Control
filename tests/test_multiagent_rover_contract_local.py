"""The multi-agent hand-off against this repository's rover code, imported in-process (no Git snapshot).

Real rover contract, adapter, offline authorization ledger and executor admission; TEST_FIXTURE limits, authorization,
transform and localization. Nothing is executed: admission is BLOCKED by the disabled operational policy."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from multiagent import integration_battery as ib, rover_contract_local as rl, rover_handoff as rh

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def contract():
    with rh.rover_contract() as c:
        yield c


def test_normal_path_imports_this_repository_rover_modules(contract):
    assert isinstance(contract, rl.LocalRoverContract)
    for module in (contract.adapter, contract.executor, contract.v2):
        assert Path(module.__file__).resolve().parent == ROOT / "tools"


def test_provenance_names_the_exact_commit_and_file_hashes(contract):
    info = contract.call("info")
    assert info["ok"] and info["result"]["operational_rover_enabled"] is False
    prov = info["result"]["provenance"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert prov["source"] == "LOCAL_REPOSITORY_IMPORT" and prov["repository_head"] == head
    assert contract.tag.startswith("local " + head[:12])
    for rel, digest in prov["contract_sha256"].items():
        assert digest == hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def test_historical_sources_are_still_snapshots(tmp_path):
    from tests.history_requirements import require_commits
    require_commits(rh.ROVER_CONTRACT_COMMIT)
    snap = rh.rover_contract(tmp_path / "committed")
    assert isinstance(snap, rh.RoverSnapshot) and snap.tag == rh.ROVER_CONTRACT_COMMIT


def test_a_sitl_trial_declaration_is_refused_before_the_executor(contract, monkeypatch):
    monkeypatch.setattr(contract.executor, "admit_ground_trial", lambda *a, **k: pytest.fail("executor reached"))
    out = contract.call("executor_admit", request={"kind": "ROVER_NAVIGATE_V1", "sitl_trial": {}}, authorization=None)
    assert out == {"ok": False, "error": out["error"]} and "sitl_trial" in out["error"]


def test_admission_is_refused_if_the_operational_policy_were_enabled(contract, monkeypatch):
    monkeypatch.setattr(contract.executor, "OPERATIONAL_ROVER_ENABLED", True)
    monkeypatch.setattr(contract.executor, "admit_ground_trial", lambda *a, **k: pytest.fail("executor reached"))
    out = contract.call("executor_admit", request={"kind": "ROVER_NAVIGATE_V1"}, authorization=None)
    assert not out["ok"] and "operational rover policy is enabled" in out["error"]


def test_the_integration_battery_passes_against_the_current_rover_code():
    rows = ib.run_all()
    assert len(rows) == len(ib.BATTERY)
    assert [r["scenario"] for r in rows if not r["as_expected"]] == []
    assert sum(r["commands"] for r in rows) == 0
    by_name = {r["scenario"]: r for r in rows}
    assert by_name["executor_refuses"]["handoff"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED"
