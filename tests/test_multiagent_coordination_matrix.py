"""Coordination matrix (offline, TEST_FIXTURE events, scripted agents): one test per situation of the demo chain,
plus the SITL interfaces (frame transform rules equal to the rover's v2). Nothing moves; no model is called."""
from datetime import timedelta
import subprocess
import types

import pytest

from multiagent import integrated_mission as im, precision_demo as pd, rover_sitl_interfaces as si
from multiagent.benchmark import run as bench
from tests.test_multiagent_coordinator import NOW, coord, ev, g, obs, signed, through_validated

SCN = {}


def scenario(name):
    if name not in SCN:
        SCN[name] = pd.run_scenario(name, quiet=True)
    return SCN[name]


def ready(c, dt=0.0):
    c.handle(ev("HEARTBEAT", dt, task_id="AIR_drone_02"))
    c.handle(ev("OBSERVATION", dt + 1, observation=obs(f"o{dt}", dt=dt + 1)))
    c.handle(ev("AERIAL_POINT_REACHED", dt + 2, task_id="AIR_drone_02", point="POI_3"))
    for phase in ("GROUND_PLANNED", "GROUND_VALIDATED", "AUTHORIZATION_REQUESTED"):
        c.handle(ev("MISSION_PHASE", dt + 3, phase=phase))
    return c


def test_01_single_drone():
    a = im.plan_phase_a(pd.CONFIG, text=pd.TEXT_ONLY_POI_3, safety_policy="safety/4")["phase_a"]
    air = a["proposal"]["aerial"]["proposals"]
    assert [p["vehicle_id"] for p in air] == ["drone_02"] and a["proposal"]["status"] == "PROPOSED_PENDING_AUTHORIZATION"
    assert (a["proposal"].get("swarm_coordination") or {}).get("status") in (None, "NOT_APPLICABLE", "CLEAR")


def test_02_two_drones_and_04_separation_conflict():
    r = scenario("red_target")
    assert sorted(t["vehicle_id"] for t in r["aerial_tasks"]) == ["drone_01", "drone_02"]
    assert r["coordinator"]["separation"] == "DECONFLICTED_BY_START_DELAY"
    assert any("set by the deterministic deconfliction" in line for line in r["console"])


def test_03_unassigned_objectives_stay_visible():
    r = scenario("unassigned_objective")
    assert r["classification"].endswith("_WITH_UNASSIGNED") and r["unassigned"]


def test_05_valid_detection():
    r = scenario("red_target")
    assert r["status_ladder"]["target_spatially_validated"] and r["observation_gate"]["target"]["matched_poi"] == "POI_3"


def test_06_stale_detection():
    assert scenario("stale_observation")["classification"] == "OBSERVATION_REFUSED"


def test_07_multiple_cards_bind_at_most_one_target_per_task():
    c = through_validated(coord())
    c.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    first = obs("card-a", dt=1)
    second = obs("card-b", dt=1)
    second["detection"] = {**second["detection"], "object_class": "yellow_card", "target_id": "card_yellow_2"}
    c.handle(ev("OBSERVATION", 1, observation=first))
    c.handle(ev("OBSERVATION", 1.5, observation=second))
    assert c.states()["G1"]["observation_id"] == "card-a"


def test_08_duplicate_observation_is_idempotent():
    r = scenario("duplicate_observation")
    assert "DUPLICATE" in " ".join(r["console"]) and r["classification"].startswith("PLANNING_COMPLETED")


def test_09_rover_without_localization():
    assert scenario("missing_localization")["classification"] == "EXECUTION_BLOCKED_NO_LOCALIZATION"


def test_10_rover_waiting_without_detection():
    r = scenario("no_target")
    assert r["classification"] == "NO_DETECTION_ROVER_KEEPS_WAITING"
    assert r["coordinator"]["ground"]["G1"]["state"] == "CONDITIONAL_AWAITING_OBSERVATION"


def test_11_frame_error():
    assert scenario("wrong_frame")["classification"] == "TARGET_NOT_GEOREFERENCED"


RIGID = {"source_frame": "synthetic_orchard_local", "target_frame": "odom", "validated": True, "source": "TEST_FIXTURE",
         "source_sha256": "f" * 64, "matrix": [[0.0, -1.0, 1.0], [1.0, 0.0, -1.5], [0.0, 0.0, 1.0]],
         "uncertainty_m": 0.05, "uncertainty_rad": 0.01,
         "not_before_utc": (NOW - timedelta(hours=1)).isoformat(), "expires_at_utc": (NOW + timedelta(hours=1)).isoformat()}
GOAL = si.SiteGoal("synthetic_orchard_local", 8.0, 4.0, 0.12, "obs-1", "POI_3")


@pytest.mark.parametrize("bad, reason", [
    (None, "FRAME_TRANSFORM_REQUIRED"),
    ({**RIGID, "matrix": [[1.0, 0.5, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]}, "FRAME_TRANSFORM_NOT_RIGID_2D"),
    ({**RIGID, "validated": False}, "FRAME_TRANSFORM_NOT_VALIDATED"),
    ({**RIGID, "expires_at_utc": (NOW - timedelta(seconds=1)).isoformat()}, "FRAME_TRANSFORM_EXPIRED_OR_NOT_YET_VALID"),
    ({**RIGID, "target_frame": "map"}, "FRAME_TRANSFORM_ENDPOINT_MISMATCH"),
])
def test_12_an_invalid_transform_converts_nothing(bad, reason):
    assert reason in si.transform_problems(bad, source_frame=GOAL.frame, target_frame="odom", now=NOW)
    with pytest.raises(ValueError, match="NO_ACCREDITED_TRANSFORM"):
        si.site_goal_to_odom(GOAL, bad, now=NOW)


def test_12b_an_accredited_transform_converts_with_uncertainty():
    out = si.site_goal_to_odom(GOAL, RIGID, now=NOW)
    assert (out["frame"], out["x_m"], out["y_m"]) == ("odom", -3.0, 6.5)  # 90 deg rotation + translation
    assert out["sigma_m"] > GOAL.sigma_m and out["transform_sha256"] == "f" * 64


def test_12c_the_transform_rules_equal_rover_v2():
    try:
        src = subprocess.run(["git", "show", "1514053da:tools/rover_mission_payload.py"], cwd=bench.ROOT,
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("rover contract commit not available")
    rover_side = types.ModuleType("rover_v2")
    exec(compile(src, "rover_side@v2", "exec"), rover_side.__dict__)
    cases = [RIGID, None, {**RIGID, "validated": False}, {**RIGID, "matrix": [[2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]},
             {**RIGID, "expires_at_utc": (NOW - timedelta(seconds=1)).isoformat()}, {**RIGID, "uncertainty_m": -1.0},
             {**RIGID, "source_sha256": "nope"}]
    for t in cases:
        assert sorted(si.transform_problems(t, source_frame=GOAL.frame, target_frame="odom", now=NOW)) == \
            sorted(rover_side._valid_transform(t, source_frame=GOAL.frame, target_frame="odom", now=NOW)), t


def test_13_an_expired_plan_cannot_be_authorized():
    c = ready(through_validated(coord(ready_hold_s=60, stale_after_s=10_000)))
    c.handle(ev("HEARTBEAT", 100, task_id="AIR_drone_02"))
    assert g(c) == "BLOCKED_OBSERVATION_EXPIRED"
    assert c.handle(ev("AUTHORIZATION", 101, **signed(101)))["outcome"] == "REFUSED"


def test_14_a_wrong_authorization_is_refused():
    c = ready(through_validated(coord()))
    assert c.handle(ev("AUTHORIZATION", 5, **signed(5, vehicle="rover_02")))["outcome"] == "REFUSED"
    assert c.handle(ev("AUTHORIZATION", 5, human_authorized=True, scope_sha256="s"))["outcome"] == "REFUSED"
    assert c.mission_state == "AUTHORIZATION_REQUESTED"


def test_15_cancellation():
    assert scenario("mission_cancelled")["classification"] == "MISSION_CANCELLED"


def test_16_an_uncertain_stop_is_never_assumed():
    c = ready(through_validated(coord()))
    assert c.handle(ev("AUTHORIZATION", 5, **signed(5), preconditions=["DRY_RUN_ADAPTER"]))["outcome"] == "APPLIED"
    c.handle(ev("EXECUTOR_FEEDBACK", 6, feedback_type=si.feedback_type("STOP_REQUESTED_NO_STANDSTILL_OBSERVED")))
    assert c.mission_state == "UNKNOWN"
    assert si.feedback_type("COMPLETED_UNVERIFIED") == "GROUND_TASK_STATUS"  # completion needs localization evidence


def test_17_loss_of_aerial_information_blocks_the_ground_task():
    c = ready(through_validated(coord(stale_after_s=10)))
    c.handle(ev("CLOCK", 30))
    assert g(c) == "BLOCKED_DRONE_REPORTS_STALE"
    c2 = through_validated(coord())
    c2.handle(ev("HEARTBEAT", task_id="AIR_drone_02"))
    c2.handle(ev("OBSERVATION", 1, observation=obs("x", dt=1)))
    c2.handle(ev("AERIAL_TASK_ABORTED", 2, task_id="AIR_drone_02"))
    assert g(c2) in ("BLOCKED_DEPENDENCY_LOST", "BLOCKED_NO_DRONE_TASK_AT_TARGET")
