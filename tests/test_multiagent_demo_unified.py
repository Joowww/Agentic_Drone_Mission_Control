"""The unified demo: .plan input (with and without its semantics manifest) and the rover block showing the offline
test path and the final ROVER_ADAPTER contract with labels. No model, no vehicle."""
from pathlib import Path

import pytest

from multiagent import demo, rover_handoff as rh

PLAN = Path(demo.__file__).parent / "fixtures/plans/red_target_aerial.plan"
MANIFEST = PLAN.with_name(PLAN.name + ".semantics.json")


def test_plan_input_with_its_manifest_keeps_sensors_and_reports_the_ground_task_it_cannot_carry(capsys):
    assert demo.main(["--input-plan", str(PLAN), "--plan-manifest", str(MANIFEST)]) == 0
    out = capsys.readouterr().out
    assert "STRUCTURED_INPUT" in out and "MANIFEST_APPLIED" in out
    assert "sensor rgb (inspect at waypoint POI_1)" in out and "sensor multispectral (take_photo at waypoint POI_3)" in out
    assert "drone_01 -> ['POI_1']" in out and "drone_02 -> ['POI_3']" in out and "commands sent 0" in out
    assert "NOT REPRESENTABLE in a .plan: the conditional rover task" in out


def test_plan_input_without_the_manifest_says_what_was_lost(capsys):
    assert demo.main(["--input-plan", str(PLAN)]) == 0
    out = capsys.readouterr().out
    assert "NO_MANIFEST" in out and "SENSOR_NOT_STATED" in out and "sensor None" in out


def test_the_rover_block_shows_both_paths_with_their_labels(capsys, tmp_path):
    try:
        snap = rh.ensure_snapshot(tmp_path / "rev", reviewed=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"rover snapshot unavailable: {exc}")
    assert demo.main(["--scenario", "red_target", "--rover-snapshot", str(snap), "--rover-reviewed"]) == 0
    out = capsys.readouterr().out
    for label in ("OFFLINE_DETERMINISTIC", "SYNTHETIC_SENSOR", "REAL_CONTRACT_CODE", "TEST_FIXTURE", "DRY_RUN_EXECUTOR",
                  "OFFLINE TEST PATH (conversion owner MULTIAGENT_FRAMES2D", "FINAL CONTRACT (conversion owner ROVER_ADAPTER"):
        assert label in out, label
    assert "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED; commands 0" in out
    assert "V2_READY_AWAITING_ROVER_ADAPTER; commands 0" in out and "transform REQUIRED_NOT_APPLIED" in out
    assert "ROVER_ADAPTER_NOT_IN_SNAPSHOT: 2e206f1fa+551eb1fefebc" in out
