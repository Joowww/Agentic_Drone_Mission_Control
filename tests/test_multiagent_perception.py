"""Observation contract and gate (drone camera -> rover target) and the integrated offline mission. Fixtures only:
no camera, ROS, simulator or vehicle. Frame transforms, every refusal reason, and that a refused observation never
yields a rover task."""
from datetime import timedelta
import json
from pathlib import Path

import pytest

from multiagent import integrated_mission as im, perception as pc
from multiagent.contracts import load_context

CTX = load_context(im.CONTEXT)
SITE, FLEET = im._site_fleet(CTX)
NOW = pc.utc_now()
FIX = pc.Policy(allow_fixtures=True)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no network, camera or process")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("subprocess.run", refuse)


def gate(obs, policy=FIX, cams=im.CAMERAS, now=NOW):
    return pc.ground_target_from_observation(obs, site=SITE, context=CTX, fleet=FLEET, now=now, policy=policy,
                                             camera_ids=cams)


def obs(**kw):
    return pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_3", now=NOW, **kw)


def test_a_valid_fixture_maps_onto_its_declared_point():
    r = gate(obs())
    assert r["status"] == "ACCEPTED" and r["data_kind"] == "TEST_FIXTURE"
    t = r["target"]
    assert (t["x_m"], t["y_m"], t["z_m"]) == (8.0, 4.0, 0.0) and t["matched_poi"] == "POI_3"
    assert t["map_frame"] == SITE.local_frame.frame_id and t["point_from"] == "BACK_PROJECTED_STEREO"


def test_the_back_projection_uses_pixel_depth_and_pose():
    # camera 2 m east of POI_3 looking down; the card appears 80 px left of centre at 10 m with fx=400 -> 2 m west
    o = obs(offset_m=(2.0, 0.0))
    o["image"] = {**o["image"], "u_px": 240.0}
    r = gate(o)
    assert r["status"] == "ACCEPTED" and (r["target"]["x_m"], r["target"]["y_m"]) == (8.0, 4.0)
    o["image"] = {**o["image"], "u_px": 320.0}  # without the pixel offset the point is 2 m off: not POI_3
    r = gate(o)
    assert r["status"] == "REFUSED" and r["candidate_point"]["x_m"] == 10.0
    assert any(x.startswith("MATCHES A DECLARED POI") for x in r["reasons"])


def test_a_given_relative_position_is_used_instead_of_pixels():
    o = obs()
    o["depth"] = None
    o["relative_position_m"] = [0.0, 0.0, 10.0]
    r = gate(o)
    assert r["status"] == "ACCEPTED" and r["target"]["point_from"] == "RELATIVE_POSITION_GIVEN"


@pytest.mark.parametrize("change, reason", [
    (lambda o: o.update(depth=None), "METRIC 3D POINT: NO_METRIC_DEPTH"),
    (lambda o: o.update(intrinsics=None), "METRIC 3D POINT: NO_INTRINSICS"),
    (lambda o: o.update(depth={"depth_m": 10.0, "source": "MONOCULAR_ESTIMATE"}), "METRIC 3D POINT"),
    (lambda o: o.update(camera_pose=None), "CAMERA POSE GIVEN"),
    (lambda o: o["camera_pose"].update(frame_id="map"), "POSE IN THE SITE FRAME"),
    (lambda o: o["camera_pose"].update(orientation_xyzw=[1.0, 0.2, 0.0, 0.0]), "UNIT QUATERNION"),
    (lambda o: o["camera_pose"].update(stamp_utc=(NOW - timedelta(seconds=5)).isoformat()), "POSE CLOSE IN TIME"),
    (lambda o: o["camera_pose"].update(position_sigma_m=None), "POSITION UNCERTAINTY"),
    (lambda o: o.update(detection_sigma_m=0.9), "POSITION UNCERTAINTY"),
    (lambda o: o["detection"].update(confidence=0.4), "CONFIDENCE"),
    (lambda o: o["detection"].update(object_class="person"), "TARGET CLASS"),
    (lambda o: o["observer"].update(vehicle_id="drone_77"), "OBSERVER IS A DECLARED DRONE"),
    (lambda o: o["observer"].update(camera_id="cam_x"), "CAMERA DECLARED"),
    (lambda o: o["camera_pose"].update(source="VEHICLE_EKF"), "POSE SOURCE CONSISTENT"),
])
def test_each_missing_or_doubtful_element_refuses(change, reason):
    o = obs()
    change(o)
    r = gate(o)
    assert r["status"] == "REFUSED" and r["target"] is None
    assert any(x.startswith(reason) for x in r["reasons"]), r["reasons"]


def test_time_validity():
    assert gate(obs(age_s=40.0))["status"] == "REFUSED"  # older than max_age_s 30
    stale = obs(age_s=10.0)
    stale["valid_for_s"] = 5.0
    assert any(x.startswith("FRESH") for x in gate(stale)["reasons"])
    future = obs(age_s=-5.0)
    assert any(x.startswith("NOT FROM THE FUTURE") for x in gate(future)["reasons"])


def test_sources_fixture_mode_and_sensor_evidence():
    assert any(x.startswith("FIXTURES ALLOWED") for x in gate(obs(), policy=pc.Policy())["reasons"])
    real = obs()
    real["source"] = {"kind": "REAL_SENSOR", "device": "oak-d-pro-w"}
    real["camera_pose"]["source"] = "VEHICLE_EKF"
    r = gate(real, policy=pc.Policy())
    assert any(x.startswith("SENSOR EVIDENCE") for x in r["reasons"])
    real["source"]["evidence_sha256"] = "a" * 64
    assert any(x.startswith("CALIBRATED CAMERA (REAL SENSOR)") for x in gate(real, policy=pc.Policy())["reasons"])
    real["camera_calibration"] = "CALIBRATED"  # since 2be329f2d a real sensor never presumes a calibration
    assert gate(real, policy=pc.Policy())["status"] == "ACCEPTED"  # a real source needs no fixture mode


def test_schema_is_strict():
    extra = obs()
    extra["global_lat_lon"] = [41.0, 2.0]
    assert gate(extra)["reasons"] == ["SCHEMA_INVALID"]
    naive = obs()
    naive["stamp_utc"] = "2026-11-06T10:00:00"
    assert gate(naive)["reasons"] == ["SCHEMA_INVALID"]


def test_targets_outside_the_site_or_off_the_drivable_line_are_refused():
    far = gate(pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_3", now=NOW, offset_m=(400.0, 0.0)))
    assert any(x.startswith("INSIDE THE OPERATION PERIMETER") for x in far["reasons"])
    ditch = gate(pc.fixture_observation(site=SITE, drone="drone_01", poi="POI_4", now=NOW))
    assert ditch["status"] == "REFUSED" and any(x.startswith("GROUND ROUTE TO THE TARGET") for x in ditch["reasons"])


# ------------------------------------------------------------------------ integrated mission --
def test_the_integrated_offline_mission_ends_pending_authorization():
    r = im.run(now=NOW)
    final = r["final"]
    assert r["status"] == final["status"] == "PROPOSED_PENDING_AUTHORIZATION"
    assert r["phase_a"]["pending_ground"][0]["state"] == "AWAITING_OBSERVATION"
    assert [t["vehicle_id"] for t in final["tasks"]] == ["drone_01", "drone_02", "rover_01"]
    assert {"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED", "point": "POI_3"} in \
        final["template"]["dependencies"]
    assert final["authorization"]["granted"] is False and final["commands_sent"] == 0 and final["vehicles_contacted"] == 0
    assert r["data_kind"] == "SIMULATED_TEST_DOUBLES" and r["observation_gate"]["data_kind"] == "TEST_FIXTURE"
    records = r["traces"]["phase_a"] + r["traces"]["phase_b"]
    llm = [x for x in records if x["kind"] == "llm"]
    assert llm and all((x.get("model_call") or {}).get("data_kind") == "SYNTHETIC" for x in llm)
    assert {x["agent"] for x in llm} == {"mission_orchestrator", "drone_swarm_agent", "rover_agent"}
    gate_span = next(x for x in r["traces"]["phase_b"] if x["name"] == "observation_gate")
    assert gate_span["status"] == "ACCEPTED"


def test_a_refused_observation_never_creates_a_rover_task():
    bad = pc.fixture_observation(site=SITE, drone="drone_02", poi="POI_3", now=NOW)
    bad["depth"] = None  # pixels only
    r = im.run(now=NOW, observation=bad)
    assert r["status"] == "GROUND_TASK_AWAITING_OBSERVATION" and "phase_b" not in r
    assert all(t["vehicle_id"] != "rover_01" for t in r["final"]["tasks"])


def test_the_cli_writes_a_sealed_offline_record(tmp_path):
    assert im.main(["--simulated", "--out", str(tmp_path / "m")]) == 0
    names = {p.name for p in (tmp_path / "m").iterdir()}
    assert {"result.json", "trace_phase_a.jsonl", "trace_phase_b.jsonl", "opik_phase_b.dry_run.json", "SHA256SUMS"} <= names
    dry = json.loads((tmp_path / "m/opik_phase_b.dry_run.json").read_text())
    spans = [s for b in dry["bodies"]["spans"] for s in b["spans"]]
    assert dry["status"] == "DRY_RUN_NOT_SENT" and not any(s["type"] == "llm" for s in spans)
    with pytest.raises(SystemExit, match="registered experiment"):
        im.main(["--out", str(tmp_path / "x")])
