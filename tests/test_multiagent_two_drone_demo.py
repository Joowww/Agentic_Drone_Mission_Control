"""The end-to-end offline two-drone demo: real repository code for planning, Hermes validation, the H2 request, the
schedule, the camera adapter, the coordinator, the Rover Agent and the rover's contract; fixtures only for sensors,
vehicles and approvals; zero commands."""
from pathlib import Path

import pytest

from multiagent import demo, rover_handoff as rh, two_drone_demo as tdd


def test_the_scripted_demo_runs_every_step_with_zero_commands():
    r = tdd.run(quiet=True)
    assert r["status"] == "COMPLETED_OFFLINE" and r["commands"] == 0
    assert r["steps"]["adapter"]["status"] == "PLANNING_VALID"
    assert r["steps"]["agenda"]["reproduced"]["drone_01"]["start_delay_s"] == 45.0
    assert r["steps"]["agenda"]["sitl_effective"]["drone_01"]["start_delay_s"] == 45.0
    assert r["steps"]["execution_request"]["status"] == "READY_TO_REQUEST_EXECUTION"
    assert r["steps"]["execution_request"]["submitted"] is False
    s = r["steps"]["schedule"]
    assert (s["first"], s["second"], s["second_decision"]["decision"]) == ("drone_02", "drone_01", "START_PERMITTED")
    assert r["observation"]["status"] == "OBSERVED" and r["observation"]["target_site_frame"]["matched_poi"] == "POI_3"
    assert r["coordinator"]["ground"]["G1"]["state"] == "READY_FOR_AUTHORIZATION"
    assert r["steps"]["rover"]["request_problems"][0].startswith("NO_NAVIGATION_PLAN")    # no human limits invented
    assert r["labels"] == {"agents": "LIVE", "sensor": "SYNTHETIC_SENSOR", "events": "TEST_FIXTURE",
                           "executor": "DRY_RUN", "simulation": "NOT_EXECUTED"}


def test_the_replayed_m4c_r1_plan_drives_the_same_chain_to_rover_matrix_s_blocked_admission(tmp_path, capsys):
    try:
        snap = rh.ensure_snapshot(tmp_path / "rev", reviewed=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"rover snapshot unavailable: {exc}")
    assert demo.main(["--two-drones", "--replay-plan", "--rover-snapshot", str(snap), "--rover-reviewed",
                      "--out", str(tmp_path / "run")]) == 0
    text = capsys.readouterr().out
    assert "REPLAY: sealed M4c-r1 plan (recorded REAL_LOCAL_LLM, 0 new calls); identical missions to the scripted plan: True" in text
    assert "final contract V2_READY_AWAITING_ROVER_ADAPTER" in text and "OPERATIONAL_ROVER_POLICY_DISABLED" in text
    assert "commands 0" in text and "SITL/Gazebo NOT_EXECUTED" in text and "not a Gazebo capture" in text
    lines = [ln[:4] for ln in text.splitlines() if ln.startswith("[")]
    assert [n for n in lines if n.strip("[] ")][:1] == ["[ 1]"] and "[18]" in lines
    assert (tmp_path / "run/result.json").is_file() and sorted(p.name for p in (tmp_path / "run/missions").iterdir()) == \
        ["drone_01.json", "drone_02.json"]
