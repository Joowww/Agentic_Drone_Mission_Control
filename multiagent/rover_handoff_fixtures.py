"""Fixtures of the rover hand-off (TEST_FIXTURE, OFFLINE_TEST mode only): a synthetic rover, pose, declared frame,
a transform accredited ONLY inside the fixture, explicit limits, a fixture authorization and a fixture receipt.
They prove software connections; they are not an operator's approval and cannot be used in OPERATIONAL mode."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path

from multiagent import frames2d as f, human_authorization as ha, integrated_mission as im, rover_executor_bridge as rb
from multiagent import rover_handoff as rh

SITE, _ = im._site_fleet(im.load_context(im.CONTEXT))
SITE_FRAME = SITE.local_frame.frame_id
M4C_R1 = Path(rh.ROOT) / "multiagent/benchmark/results/m4c_r1_integrated_v1_2026-11-07_f1ec396c9"
TASK = {"task_id": "GROUND_rover_01", "vehicle_id": "rover_01", "target_point": "POI_3", "start_point": "ROVER_START"}
DEPS = [{"task_id": "GROUND_rover_01", "after": "AIR_drone_02", "condition": "POI_REACHED", "point": "POI_3"}]
HUMAN_LIMITS = {"max_speed_mps": 0.3, "timeout_s": 60.0}
EXECUTOR_PARAMS = {"limits": {"max_yaw_rate_rad_s": 0.5, "call_timeout_s": 2.0, "stop_timeout_s": 2.0,
                              "observation_max_age_s": 0.5, "stopped_linear_mps": 0.02, "stopped_angular_rad_s": 0.02},
                   "goal": {"tolerance_m": 0.3, "yaw_tolerance_rad": 0.5, "dwell_s": 1.0, "command_hz": 10.0,
                            "no_progress_s": 10.0, "progress_m": 0.05, "progress_rad": 0.05, "max_samples": 64}}
# localization_max_age_s: the rover's adapter checks freshness on the REAL clock, so a fixture limit must leave room for a
# loaded test machine (2.0 s flaked under the full suite on 07/11); stale cases use 30 s and stay stale.
LIMITS = {"max_total_sigma_m": 0.5, "localization_max_age_s": 10.0, "max_distance_m": 5.0,
          "localization_max_uncertainty_m": 0.3}
AREA = [(-10.0, -10.0), (30.0, -10.0), (30.0, 30.0), (-10.0, 30.0)]
SITE_GOAL = {"frame": SITE_FRAME, "x_m": 8.0, "y_m": 4.0, "sigma_m": 0.12}   # POI_3, as the perception gate gives it


def transform(now, **kw):
    """site <- odom: odom origin at site (1, -1.5), axes rotated +90 deg. Accredited ONLY in this fixture."""
    base = dict(parent=SITE_FRAME, child="odom", x_m=1.0, y_m=-1.5, yaw_rad=math.pi / 2, sigma_m=0.02, sigma_rad=0.001,
                not_before=now - timedelta(hours=1), expires=now + timedelta(hours=1), source="TEST_FIXTURE_SURVEY",
                source_sha256="e" * 64, accredited=True)
    return f.Transform(**{**base, **kw})


def localization(now, **kw):
    return {"frame": "odom", "x_m": 5.5, "y_m": -5.0, "yaw_rad": math.pi / 2, "sigma_m": 0.05, "validated": True,
            "source": "TEST_FIXTURE_LOCALIZATION", "source_sha256": "c" * 64,
            "observed_at": now - timedelta(seconds=0.2), "vehicle_id": "rover_01", "boot_id": "rover-boot-1", **kw}


def request(now, *, limits=HUMAN_LIMITS, signed_limits=None, signed_vehicle=None, sign=True, at=None, valid_for_s=300.0):
    req = rb.execution_request(TASK, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=DEPS, human_limits=limits)
    if not sign or not limits:
        return req
    task = {**TASK, "vehicle_id": signed_vehicle} if signed_vehicle else TASK
    signed = rb.execution_request(task, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=DEPS,
                                  human_limits=signed_limits or limits)
    rec = ha.record(signed, operator_id="TEST_FIXTURE_OPERATOR", at=at or now - timedelta(seconds=1),
                    valid_for_s=valid_for_s, statement="offline fixture; no human approved a mission")
    return rb.execution_request(TASK, SITE, proposal={"proposal_sha256": "b" * 64}, dependencies=DEPS,
                                human_limits=limits, authorization=rec)


def synthetic_inputs(now, **override) -> rh.HandoffInputs:
    base = dict(mode="OFFLINE_TEST", now=now, ground_state="READY_FOR_AUTHORIZATION", site_goal=dict(SITE_GOAL),
                graph=f.FrameGraph([transform(now)]), rover_frame="odom", localization=localization(now),
                limits=dict(LIMITS), authorized_area=list(AREA), receipt_provider=rh.fixture_receipt_provider("OFFLINE_TEST"),
                executor_params=EXECUTOR_PARAMS, observation_sha256="d" * 64, observation_id="red_target-obs-1",
                observation_data_kind="TEST_FIXTURE observation from a SYNTHETIC_TEST image",
                rover_identity={"vehicle_id": "rover_01", "boot_id": "rover-boot-1"},
                execution_identity={"host_boot_id": "rover-boot-1", "container_boot_id": "rover-boot-1"},
                stop_state="CONFIRMED",  # TEST_FIXTURE declaration: no vehicle exists in the offline path
                observation={"source": "perception gate (detector on a SYNTHETIC_TEST image)",
                             "observed_at": (now - timedelta(seconds=2)).isoformat(), "uncertainty_m": 0.12,
                             "original_pose": {"frame": SITE_FRAME, "chain": [SITE_FRAME, "drone_02/base_link",
                                                                             "cam_down_fixture_optical"],
                                               "pose_source": "TEST_FIXTURE"}},
                # declared by the fixture: the offline test mode converts here; the final contract is ROVER_ADAPTER
                conversion_owner="MULTIAGENT_FRAMES2D")
    base.update(override)
    return rh.HandoffInputs(**base)


def historical(now):
    """The sealed M4c-r1 request and the facts its run recorded (read-only; nothing added: no limits, no
    authorization, no rover localization are invented). The plan came from REAL_LOCAL_LLM calls made on 07/11/2026;
    reading it here calls no model. Final contract: ROVER_ADAPTER owns the conversion."""
    raw = (M4C_R1 / "demo/result.json").read_bytes()
    res = json.loads(raw)
    tgt = res["observation_gate"]["target"]
    rover = res["agent_records"].get("rover_phase_b") or {}
    prov = {"kind": "SEALED_REAL_RUN_READ_ONLY", "evidence": M4C_R1.name, "result_sha256": hashlib.sha256(raw).hexdigest(),
            "agents_recorded_as": res["provenance"]["agents"], "new_llm_calls": 0,
            "aerial_assignments": {t["vehicle_id"]: t["points"] for t in res["aerial_tasks"]},
            "drone_gate_accepted": res["agent_records"]["drone"]["accepted_by_gate"],
            "rover_gate_accepted": rover.get("accepted_by_gate"),
            "supervisor": res["supervisor"], "separation": res["coordinator"]["separation"],
            "dependencies": res["execution_request"]["dependencies"], "ground_target": tgt,
            "coordinator_ground": res["coordinator"]["ground"]["G1"], "request_problems": res["request_problems"]}
    inp = rh.HandoffInputs(mode="OFFLINE_TEST", now=now, ground_state=res["coordinator"]["ground"]["G1"]["state"],
                           site_goal={"frame": tgt["map_frame"], "x_m": tgt["x_m"], "y_m": tgt["y_m"],
                                      "sigma_m": tgt["sigma_m"]},
                           observation_id=res["coordinator"]["ground"]["G1"].get("observation_id"),
                           observation_data_kind=f"image {res['provenance']['image']}, camera {res['provenance']['camera']}",
                           observation={"source": "perception gate", "point_from": tgt.get("point_from"),
                                        "uncertainty_m": tgt.get("sigma_m"), "original_pose": res.get("geometry")},
                           conversion_owner="ROVER_ADAPTER", provenance=prov)
    return res["execution_request"], inp


def cases(now) -> dict:
    """name -> (request, inputs, expected classification): the historical plan, the synthetic case and the
    negatives (one cause each). Used by the evidence generator; the tests assert the stage reasons."""
    expired = f.FrameGraph([transform(now, not_before=now - timedelta(hours=2), expires=now - timedelta(hours=1))])
    hist_req, hist_inp = historical(now)
    b = "BLOCKED_BEFORE_SUBMISSION"
    return {
        "historical_m4c_r1": (hist_req, hist_inp, b),
        "synthetic_complete": (request(now), synthetic_inputs(now), "READY_TO_SUBMIT_EXECUTOR_POLICY_BLOCKED"),
        "wrong_scope": (request(now, signed_limits={"max_speed_mps": 1.0, "timeout_s": 60.0}), synthetic_inputs(now), b),
        "other_vehicle": (request(now, signed_vehicle="rover_02"), synthetic_inputs(now), b),
        "no_authorization": (request(now, sign=False), synthetic_inputs(now), b),
        "expired_authorization": (request(now, at=now - timedelta(seconds=400)), synthetic_inputs(now), b),
        "target_expired": (request(now), synthetic_inputs(now, ground_state="BLOCKED_OBSERVATION_EXPIRED"), b),
        "aerial_dependency_lost": (request(now), synthetic_inputs(now, ground_state="BLOCKED_DEPENDENCY_LOST"), b),
        "observation_refused_still_waiting": (request(now),
                                              synthetic_inputs(now, ground_state="CONDITIONAL_AWAITING_OBSERVATION"), b),
        "mission_cancelled": (request(now), synthetic_inputs(now, ground_state="CANCELLED"), b),
        "rover_without_position": (request(now), synthetic_inputs(now, localization=None), b),
        "incompatible_frame": (request(now), synthetic_inputs(now, localization=localization(now, frame="map")), b),
        "no_transform": (request(now), synthetic_inputs(now, graph=f.FrameGraph([])), b),
        "expired_transform": (request(now), synthetic_inputs(now, graph=expired), b),
        "speed_and_duration_not_set": (request(now, limits=None), synthetic_inputs(now), b),
        "no_operator_receipt": (request(now), synthetic_inputs(now, receipt_provider=None), b),
        "executor_parameters_not_declared": (request(now), synthetic_inputs(now, executor_params=None),
                                             "V2_READY_EXECUTOR_REQUEST_INCOMPLETE"),
        "operational_mode_refuses_fixtures": (request(now), synthetic_inputs(now, mode="OPERATIONAL",
                                                                          receipt_provider=None), b),
    }
