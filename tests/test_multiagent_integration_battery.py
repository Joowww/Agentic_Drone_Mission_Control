"""The offline integration battery: real modules end to end (scripted agents, NOT Qwen), the rover's real code from a
snapshot, dry-run executor. Every row as expected and zero commands."""
import pytest

from multiagent import integration_battery as ib, rover_handoff as rh


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    try:
        snap = rh.ensure_snapshot(tmp_path_factory.mktemp("rover_side") / f"snapshot_{rh.ROVER_CONTRACT_COMMIT}")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"rover contract commit not available: {exc}")
    return {r["scenario"]: r for r in ib.run_all(snap)}


def test_every_mission_of_the_battery_is_as_expected_without_commands(rows):
    assert len(rows) == 18
    bad = {k: (r["checks"], r["demo_classification"], r["handoff"], r["coordinator_final"]) for k, r in rows.items()
           if not r["as_expected"]}
    assert not bad, bad
    assert all(r["commands"] == 0 for r in rows.values())
    assert all("NOT Qwen" in r["agents"] for r in rows.values())


def test_key_outcomes(rows):
    assert rows["two_cards"]["detections"] == 2 and rows["two_cards"]["handoff"] == "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED"
    assert rows["rover_without_localization"]["ground_final"] == "WAITING_FOR_ROVER_LOCALIZATION"
    assert rows["uncertain_stop"]["coordinator_final"] == "UNKNOWN"
    assert rows["red_card"]["coordinator_final"] == "EXECUTION_BLOCKED"   # never EXECUTION_PENDING with a blocked executor
