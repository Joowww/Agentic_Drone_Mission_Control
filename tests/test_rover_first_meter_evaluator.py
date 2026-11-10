from tools.rover_first_meter_evaluator import evaluate


def evidence():
    return {"mission_id":"m1","plan_id":"p1","vehicle_id":"rover_01","lifecycle_id":"l1",
      "host_boot_id":"h1","frame":"odom","start_pose":{"x_m":0.0,"y_m":0.0},
      "final_pose":{"x_m":1.0,"y_m":0.0},"heading_rad":0.0,"maximum_speed_mps":0.1,
      "elapsed_host_monotonic_s":10.0,"maximum_pose_age_s":0.1,"final_speed_mps":0.0,
      "commands_sent":1,"armed_at_end":False,"stationary_at_end":True,"stop_confirmed":True,
      "worker_closed":True,"localization_validated":True}


def test_synthetic_one_meter_evidence_meets_thresholds_without_authority():
    result=evaluate(evidence())
    assert result["verdict"]=="EVIDENCE_MEETS_THRESHOLDS"
    assert result["movement_authorized"] is False and result["progress_m"]==1.0


def test_bad_frame_or_distance_or_missing_stop_never_passes():
    value=evidence(); value["final_pose"]["x_m"]=0.7; value["stop_confirmed"]=False
    result=evaluate(value)
    assert result["verdict"]=="UNCONFIRMED"
    assert "DISTANCE_OUT_OF_TOLERANCE" in result["reasons"]
    assert "STOP_UNCONFIRMED" in result["reasons"]


def test_missing_identity_heading_and_stale_pose_fail_closed():
    value=evidence(); value.pop("vehicle_id"); value.pop("heading_rad"); value["maximum_pose_age_s"]=2.0
    result=evaluate(value)
    assert result["verdict"]=="UNCONFIRMED"
    assert "MISSING:vehicle_id" in result["reasons"]
    assert "START_HEADING_MISSING" in result["reasons"]
    assert "POSE_STALE" in result["reasons"]
